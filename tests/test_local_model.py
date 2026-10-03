"""Opt-in real CPU model integration; downloads are never hidden by test doubles."""

import os

import pytest

from test_structure import indexed_repo
from repomap.indexing import Indexer
from repomap.retrieval import SearchEngine, STRATEGIES
from repomap.vectors import LocalEncoder, VectorPipeline


@pytest.mark.skipif(os.environ.get("REPOMAP_TEST_LOCAL_MODEL") != "1", reason="Set REPOMAP_TEST_LOCAL_MODEL=1 after downloading the model")
def test_real_cpu_embeddings_and_persistent_chroma(indexed_repo):
    _, repository, store = indexed_repo
    encoder = LocalEncoder(revision="1110a243fdf4706b3f48f1d95db1a4f5529b4d41")
    vectors = VectorPipeline(store, encoder)
    snapshot = Indexer(store, vectors).run(repository["id"])
    assert "1110a243" in encoder.fingerprint
    engine = SearchEngine(store, vectors)
    for strategy in STRATEGIES:
        result = engine.search(repository["id"], snapshot, "Where is login implemented?", strategy)
        assert result["results"][0]["path"] == "auth.py"
    restored = VectorPipeline(store, encoder)
    assert restored.collection(snapshot).count() > 0
