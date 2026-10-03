import json
from pathlib import Path

import pytest

from repomap.evaluation import validate_dataset


def test_reviewed_benchmark_has_fixed_splits_and_provenance():
    dataset = json.loads((Path(__file__).parents[1] / "benchmarks/annotations.json").read_text(encoding="utf-8"))
    validate_dataset(dataset)
    assert len(dataset["queries"]) == 60
    assert all(q["human_confirmed"] and q["review"] for q in dataset["queries"])
    assert sum(q["split"] == "test" for q in dataset["queries"]) == 45
    query = next(q for q in dataset["queries"] if q["id"] == "express-13")
    assert query["relevant"][0]["end_line"] == 308


def test_dataset_rejects_duplicate_ids_and_invalid_ranges():
    entry = {"id": "q", "repository": "r", "split": "test", "query": "find f", "relevant": [{"path": "f.py", "start_line": 3, "end_line": 2}]}
    dataset = {"repositories": [{"name": "r"}], "queries": [entry]}
    with pytest.raises(ValueError, match="range"):
        validate_dataset(dataset)
    entry["relevant"][0]["end_line"] = 4
    dataset["queries"].append(entry)
    with pytest.raises(ValueError, match="unique"):
        validate_dataset(dataset)
