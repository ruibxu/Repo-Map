"""Immutable source capture, structural indexing, and serial task coordination."""

import copy
import fnmatch
import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from repomap.binding import bind
from repomap.parsing import VERSION, parse
from repomap.repositories import RepositoryCatalog, git

EXCLUDED = {"node_modules", ".git", ".venv", "venv", "dist", "build", "__pycache__", ".repomap", "vendor"}


class IndexStore:
    def __init__(self, catalog: RepositoryCatalog):
        self.catalog = catalog
        with catalog.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, repository_id TEXT NOT NULL, commit_sha TEXT NOT NULL,
                    status TEXT NOT NULL, created_at REAL NOT NULL, metrics TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS files (
                    snapshot_id TEXT NOT NULL, path TEXT NOT NULL, content TEXT NOT NULL,
                    content_hash TEXT NOT NULL, language TEXT NOT NULL, diagnostics TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id, path)
                );
                CREATE TABLE IF NOT EXISTS symbols (
                    snapshot_id TEXT NOT NULL, id TEXT NOT NULL, path TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id, id)
                );
                CREATE TABLE IF NOT EXISTS refs (
                    snapshot_id TEXT NOT NULL, path TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    snapshot_id TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS parsed_cache (
                    key TEXT PRIMARY KEY, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, repository_id TEXT NOT NULL, snapshot_id TEXT,
                    status TEXT NOT NULL, progress REAL NOT NULL, error TEXT, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS refs_snapshot ON refs(snapshot_id, path);
                CREATE INDEX IF NOT EXISTS edges_snapshot ON edges(snapshot_id);
            """)

    def snapshots(self, repository_id):
        with self.catalog.connect() as db:
            rows = db.execute("SELECT * FROM snapshots WHERE repository_id=? ORDER BY created_at DESC", (repository_id,)).fetchall()
        return [{**dict(row), "metrics": json.loads(row["metrics"])} for row in rows]

    # Validate both identities so callers cannot read another repository's snapshot.
    def require(self, repository_id, snapshot_id, published=True):
        with self.catalog.connect() as db:
            row = db.execute("SELECT * FROM snapshots WHERE id=? AND repository_id=?", (snapshot_id, repository_id)).fetchone()
        if not row or published and row["status"] != "ready":
            raise ValueError("The selected snapshot is unavailable or not fully indexed.")
        return dict(row)

    def records(self, table, snapshot_id):
        if table not in {"symbols", "refs", "edges"}:
            raise ValueError("Invalid record type.")
        with self.catalog.connect() as db:
            rows = db.execute(f"SELECT * FROM {table} WHERE snapshot_id=?", (snapshot_id,)).fetchall()
        return [{**json.loads(row["data"]), **({"path": row["path"]} if "path" in row.keys() else {})} for row in rows]

    def source(self, snapshot_id, path):
        with self.catalog.connect() as db:
            row = db.execute("SELECT * FROM files WHERE snapshot_id=? AND path=?", (snapshot_id, path)).fetchone()
        if not row:
            raise ValueError("File not found in this snapshot.")
        return dict(row)


def capture(root: Path, exclusions=()) -> tuple[dict, list]:
    # Git selects tracked paths; working-tree bytes preserve uncommitted edits.
    # NUL separators also handle paths containing spaces or newlines.
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
    files, skipped = {}, []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = os.fsdecode(raw_path).replace("\\", "/")
        absolute = root / path
        reason = None
        if any(part in EXCLUDED for part in Path(path).parts) or any(fnmatch.fnmatch(path, pattern) for pattern in exclusions):
            reason = "excluded-path"
        elif absolute.is_symlink() or not absolute.resolve().is_relative_to(root.resolve()):
            reason = "symlink-or-outside-root"
        elif not absolute.is_file():
            reason = "deleted-or-non-file"
        elif absolute.stat().st_size > 1_000_000:
            reason = "larger-than-1MB"
        if reason:
            skipped.append({"path": path, "reason": reason})
            continue
        raw = absolute.read_bytes()
        if b"\0" in raw:
            skipped.append({"path": path, "reason": "binary"})
            continue
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            skipped.append({"path": path, "reason": "not-utf8"})
            continue
        if "@generated" in content[:2048].lower() or "auto-generated" in content[:2048].lower():
            skipped.append({"path": path, "reason": "generated"})
            continue
        files[path] = {"content": content, "hash": hashlib.sha256(raw).hexdigest()}
    return files, skipped


class Indexer:
    def __init__(self, store: IndexStore, vector_pipeline=None):
        self.store = store
        self.vector_pipeline = vector_pipeline

    def run(self, repository_id, exclusions=(), progress=lambda value: None, reserved_snapshot=None):
        import psutil
        process = psutil.Process()
        peak = [process.memory_info().rss]
        stop = threading.Event()

        def sample():
            while not stop.wait(0.05):
                peak[0] = max(peak[0], process.memory_info().rss)

        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        try:
            snapshot = self._run(repository_id, exclusions, progress, reserved_snapshot)
            with self.store.catalog.connect() as db:
                row = db.execute("SELECT metrics FROM snapshots WHERE id=?", (snapshot,)).fetchone()
                metrics = json.loads(row["metrics"])
                metrics["peak_rss_bytes"] = max(peak[0], process.memory_info().rss)
                metrics["data_disk_bytes"] = sum(p.stat().st_size for p in self.store.catalog.data_dir.rglob("*") if p.is_file())
                db.execute("UPDATE snapshots SET metrics=? WHERE id=?", (json.dumps(metrics), snapshot))
            return snapshot
        finally:
            stop.set()
            monitor.join()

    def _run(self, repository_id, exclusions=(), progress=lambda value: None, reserved_snapshot=None):
        started = time.perf_counter()
        with self.store.catalog.connect() as db:
            repository = db.execute("SELECT * FROM repositories WHERE id=?", (repository_id,)).fetchone()
        if not repository:
            raise ValueError("Repository not found.")
        root = Path(repository["path"])
        commit = git("-C", str(root), "rev-parse", "HEAD")
        files, skipped = capture(root, exclusions)
        parse_started = time.perf_counter()
        hits = 0
        for number, (path, file) in enumerate(sorted(files.items())):
            # Paths affect symbol identities; parser changes invalidate cached output.
            key = hashlib.sha256(f"{VERSION}:{path}:{file['hash']}".encode()).hexdigest()
            with self.store.catalog.connect() as db:
                cache = db.execute("SELECT data FROM parsed_cache WHERE key=?", (key,)).fetchone()
            if cache:
                # Binding mutates references; keep cached syntax independent of this run.
                file["parsed"] = copy.deepcopy(json.loads(cache["data"]))
                hits += 1
            else:
                file["parsed"] = parse(path, file["content"])
                with self.store.catalog.connect() as db:
                    db.execute("INSERT OR REPLACE INTO parsed_cache VALUES (?,?)", (key, json.dumps(file["parsed"])))
            progress(0.1 + 0.4 * (number + 1) / max(1, len(files)))
        parse_seconds = time.perf_counter() - parse_started
        tsconfig = {}
        if "tsconfig.json" in files:
            try:
                tsconfig = json.loads(files["tsconfig.json"]["content"]).get("compilerOptions", {})
            except (ValueError, AttributeError):
                skipped.append({"path": "tsconfig.json", "reason": "unsupported-config-syntax"})
        binding_started = time.perf_counter()
        edges = bind(files, tsconfig)
        binding_seconds = time.perf_counter() - binding_started
        snapshot_id = reserved_snapshot or uuid.uuid4().hex
        metrics = {"files": len(files), "bytes": sum(len(f["content"].encode()) for f in files.values()),
                   "parse_cache_hits": hits, "parse_seconds": parse_seconds, "binding_seconds": binding_seconds, "skipped": skipped,
                   "parser": VERSION, "exclusions": list(exclusions),
                   "commit_sha": commit, "content_manifest_hash": hashlib.sha256(json.dumps({p: f['hash'] for p, f in sorted(files.items())}, sort_keys=True).encode()).hexdigest()}
        with self.store.catalog.connect() as db:
            # Stage captured source first. Queries cannot use it until text and
            # vector indexing complete and the snapshot becomes ready.
            db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?)", (snapshot_id, repository_id, commit, "structured", time.time(), json.dumps(metrics)))
            for path, file in files.items():
                parsed = file["parsed"]
                db.execute("INSERT INTO files VALUES (?,?,?,?,?,?)", (snapshot_id, path, file["content"], file["hash"], parsed["language"], json.dumps(parsed["diagnostics"])))
                db.executemany("INSERT INTO symbols VALUES (?,?,?,?)", [(snapshot_id, s["id"], path, json.dumps(s)) for s in parsed["symbols"]])
                db.executemany("INSERT INTO refs VALUES (?,?,?)", [(snapshot_id, path, json.dumps(ref)) for ref in parsed["references"]])
            db.executemany("INSERT INTO edges VALUES (?,?)", [(snapshot_id, json.dumps(edge)) for edge in edges])
        try:
            if self.vector_pipeline:
                metrics.update(self.vector_pipeline.build(snapshot_id, files, progress))
            # Build timing excludes later publication, pruning, and metric collection.
            metrics["total_seconds"] = time.perf_counter() - started
            metrics["files_per_second"] = len(files) / max(metrics["total_seconds"], 0.000001)
            with self.store.catalog.connect() as db:
                db.execute("UPDATE snapshots SET status=?, metrics=? WHERE id=?", ("ready" if self.vector_pipeline else "structured", json.dumps(metrics), snapshot_id))
            if self.vector_pipeline:
                # Retire older data only after successful publication.
                self.prune(repository_id)
            progress(1)
            return snapshot_id
        except Exception:
            with self.store.catalog.connect() as db:
                db.execute("UPDATE snapshots SET status='failed' WHERE id=?", (snapshot_id,))
            raise

    def prune(self, repository_id):
        ready = [s for s in self.store.snapshots(repository_id) if s["status"] == "ready"]
        for snapshot in ready[2:]:
            if self.vector_pipeline:
                self.vector_pipeline.delete(snapshot["id"])
            with self.store.catalog.connect() as db:
                for table in ("files", "symbols", "refs", "edges"):
                    db.execute(f"DELETE FROM {table} WHERE snapshot_id=?", (snapshot["id"],))
                db.execute("UPDATE snapshots SET status='retired' WHERE id=?", (snapshot["id"],))


class TaskManager:
    def __init__(self, indexer: Indexer):
        self.indexer = indexer
        # One worker serializes API indexing without an external queue.
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="repomap-index")
        self.lock = threading.Lock()
        with indexer.store.catalog.connect() as db:
            # Recover interrupted API tasks without invalidating unrelated CLI indexes.
            db.execute("UPDATE tasks SET status='failed', error='Interrupted by application restart' WHERE status IN ('queued','running')")
            db.execute("UPDATE snapshots SET status='failed' WHERE status='structured' AND id IN (SELECT snapshot_id FROM tasks WHERE status='failed')")

    def submit(self, repository_id, exclusions=()):
        task_id = uuid.uuid4().hex
        with self.indexer.store.catalog.connect() as db:
            if not db.execute("SELECT id FROM repositories WHERE id=?", (repository_id,)).fetchone():
                raise ValueError("Repository not found.")
            # Reserve a snapshot identity so restart recovery can locate partial data.
            db.execute("INSERT INTO tasks VALUES (?,?,?,'queued',0,NULL,?)", (task_id, repository_id, task_id, time.time()))
        self.pool.submit(self._run, task_id, repository_id, exclusions)
        return self.get(task_id)

    def _run(self, task_id, repository_id, exclusions):
        def update(value):
            with self.indexer.store.catalog.connect() as db:
                db.execute("UPDATE tasks SET progress=? WHERE id=?", (value, task_id))
        with self.indexer.store.catalog.connect() as db:
            db.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
        try:
            snapshot = self.indexer.run(repository_id, exclusions, update, reserved_snapshot=task_id)
            with self.indexer.store.catalog.connect() as db:
                db.execute("UPDATE tasks SET status='completed', snapshot_id=?, progress=1 WHERE id=?", (snapshot, task_id))
        except Exception as error:
            with self.indexer.store.catalog.connect() as db:
                db.execute("UPDATE tasks SET status='failed', error=? WHERE id=?", (str(error), task_id))

    def get(self, task_id):
        with self.indexer.store.catalog.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError("Task not found.")
        return dict(row)

    def close(self):
        self.pool.shutdown(wait=True)
