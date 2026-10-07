"""Repository acquisition and SQLite catalog; no indexing is performed here."""

import os
import re
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class ImportErrorDetail(ValueError):
    """An actionable repository import failure."""


def git(*args: str, timeout: int = 120) -> str:
    env = os.environ.copy()
    # Fail clearly rather than wait for credentials in a service request.
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, timeout=timeout, env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ImportErrorDetail("Git is unavailable or the operation timed out.") from error
    if result.returncode:
        raise ImportErrorDetail(result.stderr.decode("utf-8", errors="replace").strip())
    return os.fsdecode(result.stdout).strip()


class RepositoryCatalog:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database = self.data_dir / "catalog.sqlite3"
        with self.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS repositories (
                id TEXT PRIMARY KEY, source TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL,
                commit_sha TEXT NOT NULL, imported_at TEXT NOT NULL
            )""")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            # sqlite3 transaction contexts do not close connections; release
            # file handles explicitly after each operation.
            connection.close()

    def list(self) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM repositories ORDER BY imported_at, id"
            )]

    def import_repository(self, kind: str, source: str) -> dict:
        source = source.strip()
        repository_id = uuid.uuid4().hex
        if kind == "github":
            match = re.fullmatch(
                r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?",
                source,
            )
            if not match or any(part in {".", ".."} for part in match.groups()):
                raise ImportErrorDetail("Use an HTTPS public GitHub repository URL without credentials or query parameters.")
            owner, name = match.groups()
            source = f"https://github.com/{owner}/{name}.git"
            destination = self.data_dir / "repositories" / repository_id
        elif kind == "local":
            requested = Path(source).expanduser().resolve()
            if not requested.is_dir():
                raise ImportErrorDetail("The local repository directory does not exist.")
            root = Path(git("-C", str(requested), "rev-parse", "--show-toplevel")).resolve()
            if root != requested:
                raise ImportErrorDetail("Select the Git repository root directory.")
            destination = root
            source = str(root)
            name = root.name
        else:
            raise ImportErrorDetail("Repository kind must be github or local.")

        with self.connect() as connection:
            existing = connection.execute("SELECT * FROM repositories WHERE source = ?", (source,)).fetchone()
            if existing:
                return dict(existing)

        if kind == "github":
            destination.parent.mkdir(parents=True, exist_ok=True)
            git("-c", "credential.helper=", "clone", "--depth", "1", "--", source, str(destination))
        commit = git("-C", str(destination), "rev-parse", "HEAD")
        if kind == "github":
            git("-C", str(destination), "checkout", "--detach", commit)
        row = dict(id=repository_id, source=source, kind=kind, name=name,
                   path=str(destination), commit_sha=commit,
                   imported_at=datetime.now(timezone.utc).isoformat())
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO repositories VALUES (:id, :source, :kind, :name, :path, :commit_sha, :imported_at)", row,
            )
            stored = connection.execute("SELECT * FROM repositories WHERE source = ?", (source,)).fetchone()
        return dict(stored)
