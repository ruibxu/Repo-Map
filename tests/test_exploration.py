import subprocess

import pytest

from test_retrieval import searchable
from repomap.exploration import Explorer


def test_definition_reference_graph_and_captured_source(searchable):
    root, repository, store, indexer, engine, old = searchable
    (root / "main.py").write_text("from auth import login\ndef run():\n    return login()\n")
    subprocess.run(["git", "-C", str(root), "add", "main.py"], check=True)
    snapshot = indexer.run(repository["id"])
    explorer = Explorer(store)
    definition = explorer.definitions(repository["id"], snapshot, path="main.py", line=3, column=12)
    assert definition["status"] == "resolved"
    symbol = definition["definitions"][0]
    assert symbol["path"] == "auth.py"
    refs = explorer.references(repository["id"], snapshot, symbol_id=symbol["id"])
    assert any(r["path"] == "main.py" and r["status"] == "resolved" for r in refs["references"])
    graph = explorer.graph(repository["id"], snapshot, path="main.py")
    assert {e["kind"] for e in graph["edges"]} >= {"import", "call"}
    (root / "main.py").write_text("# changed after indexing")
    assert "return login" in explorer.file(repository["id"], snapshot, "main.py")["content"]
    assert any("dependency-expansion" in r["origins"] for r in engine.search(repository["id"], snapshot, "run", "ast-aware")["results"])


def test_file_escape_and_foreign_snapshot_rejected(searchable):
    _, repository, store, _, _, snapshot = searchable
    explorer = Explorer(store)
    with pytest.raises(ValueError):
        explorer.file(repository["id"], snapshot, "../secret")
    with pytest.raises(ValueError):
        explorer.file("foreign", snapshot, "auth.py")
    with pytest.raises(ValueError):
        explorer.file(repository["id"], snapshot, "auth.py", 99)
