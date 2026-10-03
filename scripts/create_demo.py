"""Create an ignored demonstration repository and a real local model index."""

import json
import subprocess
from pathlib import Path

from repomap.indexing import Indexer, IndexStore
from repomap.repositories import RepositoryCatalog
from repomap.vectors import VectorPipeline


def main():
    root = Path(".repomap/demo-source").resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
        (root / "auth.py").write_text('''def authenticate(username, password):
    """Validate credentials and return an authentication decision."""
    return username == "demo" and password == "example"
''', encoding="utf-8")
        (root / "routes.py").write_text('''from auth import authenticate

def login_route(username, password):
    """Authenticate a login request before creating its session."""
    return authenticate(username, password)
''', encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=repoMap Demo", "-c", "user.email=demo@example.invalid", "commit", "-m", "Add demo authentication flow"], check=True, capture_output=True)
    catalog = RepositoryCatalog(Path(".repomap"))
    repository = catalog.import_repository("local", str(root))
    store = IndexStore(catalog)
    snapshot = Indexer(store, VectorPipeline(store)).run(repository["id"])
    print(json.dumps({"repository_id": repository["id"], "snapshot_id": snapshot}))


if __name__ == "__main__":
    main()
