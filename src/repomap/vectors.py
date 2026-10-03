"""Local embeddings and persistent Chroma indexes with explicit model identity."""

import hashlib
import json
import os
import threading
import time

from repomap.parsing import identity

MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def fts_table(snapshot):
    import re
    if not re.fullmatch(r"[a-f0-9]{32}", snapshot):
        raise ValueError("Invalid snapshot identity.")
    return "fts_" + snapshot


class LocalEncoder:
    def __init__(self, model=None, revision=None):
        self.name = model or os.environ.get("REPOMAP_EMBEDDING_MODEL", MODEL)
        self.revision = revision or os.environ.get("REPOMAP_EMBEDDING_REVISION")
        self._model = None
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            if self._model is None:
                threads = os.environ.get("REPOMAP_CPU_THREADS", "4")
                for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
                    os.environ.setdefault(variable, threads)
                import torch
                torch.set_num_threads(int(threads))
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.name, revision=self.revision, device="cpu")
                self._model.max_seq_length = 512
            return self._model

    @property
    def tokenizer(self):
        return self.load().tokenizer

    @property
    def fingerprint(self):
        model = self.load()
        config = model[0].auto_model.config
        revision = getattr(config, "_commit_hash", None) or self.revision
        if not revision:
            raise ValueError("Configure an immutable embedding model revision for this model.")
        return f"{self.name}@{revision}:max512:normalized:v1"

    def encode(self, texts):
        with self.lock:
            return self.load().encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32).tolist()


def split_code(text, tokenizer, budget=448, overlap=64):
    """Split at line/statement boundaries when possible, using exact token offsets."""
    offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
    start = 0
    while start < len(offsets):
        end = min(start + budget, len(offsets))
        char_start = offsets[start][0]
        char_end = offsets[end - 1][1]
        if end < len(offsets):
            boundary = text.rfind("\n", char_start, char_end)
            if boundary > char_start:
                adjusted = next((i for i in range(end - 1, start, -1) if offsets[i][1] <= boundary), None)
                if adjusted is not None and adjusted - start > overlap:
                    end, char_end = adjusted + 1, offsets[adjusted][1]
        yield char_start, char_end, text[char_start:char_end]
        if end == len(offsets):
            break
        start = max(start + 1, end - overlap)


def make_chunks(snapshot_id, files, tokenizer):
    chunks = []
    for path, file in sorted(files.items()):
        content = file["content"]
        raw = content.encode()
        units = []
        covered = []
        for symbol in file["parsed"]["symbols"]:
            start, end = symbol["start_byte"], symbol["end_byte"]
            if symbol["kind"] in {"class", "interface", "namespace"}:
                children = [s["start_byte"] for s in file["parsed"]["symbols"] if s["scope"] == symbol["id"]]
                if children:
                    end = min(children)
            units.append((start, raw[start:end].decode(), symbol))
            covered.append((start, end))
        # Preserve module-level code, documentation, and syntax-error regions.
        cursor = 0
        for start, end in sorted(covered):
            if start > cursor:
                units.append((cursor, raw[cursor:start].decode(), None))
            cursor = max(cursor, end)
        if cursor < len(raw):
            units.append((cursor, raw[cursor:].decode(), None))
        for offset, unit, symbol in units:
            prefix = f"{path}\n{symbol['qualified_name'] if symbol else ''}\n"
            prefix_tokens = tokenizer(prefix, add_special_tokens=False)["input_ids"][:60]
            prefix = tokenizer.decode(prefix_tokens, skip_special_tokens=True) + "\n"
            for start, end, code in split_code(unit, tokenizer):
                if not code.strip():
                    continue
                byte_start = offset + len(unit[:start].encode())
                byte_end = offset + len(unit[:end].encode())
                chunks.append({"id": identity(snapshot_id, path, byte_start, byte_end, symbol["id"] if symbol else ""),
                    "snapshot_id": snapshot_id, "path": path, "language": file["parsed"]["language"],
                    "symbol_id": symbol["id"] if symbol else None,
                    "symbol": symbol["qualified_name"] if symbol else None,
                    "start_byte": byte_start, "end_byte": byte_end,
                    "start_line": raw[:byte_start].count(b"\n") + 1,
                    "end_line": raw[:byte_end].count(b"\n") + 1,
                    "excerpt": code, "embedding_text": prefix + code})
    return chunks


def terms(text):
    import re
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.findall(r"[a-z0-9]+", expanded.lower().replace("_", " "))


class VectorPipeline:
    def __init__(self, store, encoder=None):
        self.store = store
        self.encoder = encoder or LocalEncoder()
        self._client = None
        self.lock = threading.Lock()
        with store.catalog.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, path TEXT NOT NULL,
                    language TEXT NOT NULL, symbol_id TEXT, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunks_snapshot ON chunks(snapshot_id);
                CREATE TABLE IF NOT EXISTS embedding_cache (key TEXT PRIMARY KEY, vector TEXT NOT NULL);
            """)

    @property
    def client(self):
        with self.lock:
            if self._client is None:
                import chromadb
                from chromadb.config import Settings
                self._client = chromadb.PersistentClient(path=str(self.store.catalog.data_dir / "vectors"), settings=Settings(anonymized_telemetry=False))
            return self._client

    def collection(self, snapshot):
        return self.client.get_collection("snapshot_" + snapshot, embedding_function=None)

    def build(self, snapshot, files, progress):
        started = time.perf_counter()
        model_started = time.perf_counter()
        fingerprint = self.encoder.fingerprint
        model_seconds = time.perf_counter() - model_started
        chunk_started = time.perf_counter()
        chunks = make_chunks(snapshot, files, self.encoder.tokenizer)
        chunk_seconds = time.perf_counter() - chunk_started
        table = fts_table(snapshot)
        with self.store.catalog.connect() as db:
            db.execute(f"CREATE VIRTUAL TABLE {table} USING fts5(id UNINDEXED, path, symbol, code, tokenize='unicode61')")
        collection = self.client.create_collection("snapshot_" + snapshot, embedding_function=None, metadata={"hnsw:space": "cosine", "hnsw:num_threads": int(os.environ.get("REPOMAP_CPU_THREADS", "4")), "model": fingerprint})
        hits = 0
        encode_seconds = 0
        for offset in range(0, len(chunks), 64):
            batch = chunks[offset:offset + 64]
            vectors = [None] * len(batch)
            missing, keys = [], []
            for i, chunk in enumerate(batch):
                key = hashlib.sha256((fingerprint + ":chunks-v1:" + chunk["embedding_text"]).encode()).hexdigest()
                keys.append(key)
                with self.store.catalog.connect() as db:
                    cached = db.execute("SELECT vector FROM embedding_cache WHERE key=?", (key,)).fetchone()
                if cached:
                    vectors[i] = json.loads(cached["vector"])
                    hits += 1
                else:
                    missing.append(i)
            if missing:
                encode_started = time.perf_counter()
                encoded = self.encoder.encode([batch[i]["embedding_text"] for i in missing])
                encode_seconds += time.perf_counter() - encode_started
                with self.store.catalog.connect() as db:
                    for i, vector in zip(missing, encoded):
                        vectors[i] = vector
                        db.execute("INSERT OR REPLACE INTO embedding_cache VALUES (?,?)", (keys[i], json.dumps(vector)))
            collection.add(ids=[c["id"] for c in batch], embeddings=vectors,
                metadatas=[{"path": c["path"], "language": c["language"]} for c in batch])
            with self.store.catalog.connect() as db:
                for chunk in batch:
                    db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", (chunk["id"], snapshot, chunk["path"], chunk["language"], chunk["symbol_id"], json.dumps(chunk)))
                    db.execute(f"INSERT INTO {table} VALUES (?,?,?,?)", (chunk["id"],
                        " ".join(terms(chunk["path"])), " ".join(terms(chunk["symbol"] or "")), " ".join(terms(chunk["excerpt"]))))
            progress(0.5 + 0.45 * min(offset + 64, len(chunks)) / max(1, len(chunks)))
        return {"chunks": len(chunks), "embedding_cache_hits": hits,
                "embedding_seconds": encode_seconds, "vector_pipeline_seconds": time.perf_counter() - started,
                "model_load_seconds": model_seconds, "chunking_seconds": chunk_seconds, "model": fingerprint,
                "chunking": {"max_tokens": 512, "overlap": 64, "version": "v1"}}

    def delete(self, snapshot):
        self.client.delete_collection("snapshot_" + snapshot)
        with self.store.catalog.connect() as db:
            db.execute(f"DROP TABLE IF EXISTS {fts_table(snapshot)}")
            db.execute("DELETE FROM chunks WHERE snapshot_id=?", (snapshot,))
