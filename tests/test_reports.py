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
