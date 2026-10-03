import json
import re

import pytest

from test_structure import indexed_repo
from repomap.evaluation import evaluate, metrics
from repomap.indexing import Indexer
from repomap.retrieval import SearchEngine, STRATEGIES
from repomap.vectors import VectorPipeline, split_code
from repomap.parsing import parse


class TestTokenizer:
    """Explicit deterministic test double; never used in application retrieval."""
    def __call__(self, text, **kwargs):
        spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        return {"offset_mapping": spans, "input_ids": [text[a:b] for a, b in spans]}

    def decode(self, tokens, **kwargs):
        return " ".join(tokens)


class TestEncoder:
    tokenizer = TestTokenizer()
    fingerprint = "test-fixture-v1"

    def encode(self, texts):
        return [[1.0 if "login" in text.lower() else 0.0, 0.0 if "login" in text.lower() else 1.0] for text in texts]


@pytest.fixture
def searchable(indexed_repo):
    root, repository, store = indexed_repo
    vectors = VectorPipeline(store, TestEncoder())
    indexer = Indexer(store, vectors)
    snapshot = indexer.run(repository["id"])
    return root, repository, store, indexer, SearchEngine(store, vectors), snapshot


def test_four_strategies_and_snapshot_filters(searchable):
    _, repository, store, _, engine, snapshot = searchable
    for strategy in STRATEGIES:
        result = engine.search(repository["id"], snapshot, "login", strategy)
        assert result["results"][0]["symbol"] == "login"
        assert result["results"][0]["snapshot_id"] == snapshot
        assert result["results"][0]["origins"]
    assert not engine.search(repository["id"], snapshot, "login", language="typescript")["results"]
    assert not engine.search(repository["id"], snapshot, "login", path_prefix="missing/")["results"]
    with pytest.raises(ValueError):
        engine.search("another-repository", snapshot, "login")


def test_incremental_vectors_retention_and_immutability(searchable):
    root, repository, store, indexer, engine, first = searchable
    second = indexer.run(repository["id"])
    assert store.snapshots(repository["id"])[0]["metrics"]["embedding_cache_hits"] > 0
    (root / "auth.py").write_text("def logout():\n    return False\n")
    third = indexer.run(repository["id"])
    with pytest.raises(ValueError):
        store.require(repository["id"], first)
    assert "login" in store.source(second, "auth.py")["content"]
    assert "logout" in engine.search(repository["id"], third, "logout", "bm25")["results"][0]["excerpt"]


def test_failed_vector_build_preserves_ready_snapshot(searchable):
    _, repository, store, _, engine, snapshot = searchable
    class Broken:
        def build(self, *args):
            raise RuntimeError("embedding unavailable")
    with pytest.raises(RuntimeError):
        Indexer(store, Broken()).run(repository["id"])
    assert store.require(repository["id"], snapshot)["status"] == "ready"
    assert engine.search(repository["id"], snapshot, "login")["results"]
    assert store.snapshots(repository["id"])[0]["status"] == "failed"


def test_metrics_known_ranking():
    measured = metrics([{"id": "x"}, {"id": "b"}, {"id": "a"}], {"a", "b", "c"})
    assert measured["recall@5"] == pytest.approx(2 / 3)
    assert measured["mrr@10"] == .5


def test_evaluation_rejects_unconfirmed_truth_and_exports(searchable, tmp_path):
    _, repository, store, _, engine, snapshot = searchable
    dataset = {"repositories": [{"name": "fixture", "repository_id": repository["id"], "snapshot_id": snapshot, "commit_sha": repository["commit_sha"]}],
               "queries": [{"id": "q1", "repository": "fixture", "query": "login", "split": "test", "human_confirmed": False,
                            "relevant": [{"path": "auth.py", "start_line": 1, "end_line": 2}]}]}
    with pytest.raises(ValueError, match="human"):
        evaluate(engine, dataset, tmp_path / "report")
    report = evaluate(engine, dataset, tmp_path / "report", allow_draft=True)
    assert report["status"] == "provisional"
    assert len(report["rows"]) == 4
    assert {p.name for p in (tmp_path / "report").iterdir()} == {"results.json", "results.csv", "report.md"}


def test_long_chunks_progress_with_overlap():
    text = "\n".join("token " * 100 for _ in range(20))
    chunks = list(split_code(text, TestTokenizer(), budget=512, overlap=64))
    assert len(chunks) > 1
    assert all(len(chunk[2].split()) <= 512 for chunk in chunks)
    assert chunks[-1][1] == len(text.rstrip())


@pytest.mark.parametrize("path,source", [
    ("code.py", "prefix = one + two\nvalue = call(\n    first,\n    second,\n    third,\n    fourth,\n    fifth,\n    sixth,\n)\n"),
    ("code.ts", "const prefix = one + two;\nconst value = call(\n    first,\n    second,\n    third,\n    fourth,\n    fifth,\n    sixth,\n);\n"),
])
def test_multiline_statements_are_preferred_over_interior_newlines(path, source):
    parsed = parse(path, source)
    boundaries = [len(source.encode()[:point].decode()) for point in parsed["statement_ends"]]
    chunks = list(split_code(source, TestTokenizer(), budget=12, overlap=2, statement_ends=boundaries))
    assert chunks[0][2] == source.splitlines()[0]
    assert chunks[-1][1] == len(source.rstrip())
    assert all(len(code.split()) <= 12 for _, _, code in chunks)
