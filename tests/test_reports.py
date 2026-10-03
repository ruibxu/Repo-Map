import json

from repomap.reports import reports


def test_reports_read_valid_files_and_skip_malformed(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
    valid = {"status": "provisional", "split": "test", "summary": {}, "hardware": {}, "indexing": {}}
    (root / "results.json").write_text(json.dumps(valid))
    malformed = root / "bad"
    malformed.mkdir()
    (malformed / "results.json").write_text("not json")
    result = reports(tmp_path)
    assert len(result) == 1
    assert result[0]["status"] == "provisional"


def test_report_api_omits_skip_records_and_rejects_invalid_metric_shapes(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
    report = {"status": "human-confirmed", "split": "test", "hardware": {},
        "summary": {"bm25": {key: 1.0 for key in ("recall@5", "recall@10", "recall@20", "mrr@10", "p50_ms", "p95_ms")}},
        "indexing": {"example": {"files": 1, "chunks": 2, "total_seconds": 3.0, "peak_rss_bytes": 4,
            "skipped": [{"path": "excluded.txt", "reason": "excluded-path"}]}}}
    path = root / "results.json"
    path.write_text(json.dumps(report))
    metrics = reports(tmp_path)[0]["indexing"]["example"]
    assert metrics["files"] == 1 and metrics["skipped_files"] == 1
    assert "skipped" not in metrics
    assert json.loads(path.read_text())["indexing"]["example"]["skipped"]
    report["summary"]["bm25"]["p50_ms"] = "invalid"
    path.write_text(json.dumps(report))
    assert reports(tmp_path) == []
    path.write_text("[]")
    assert reports(tmp_path) == []
