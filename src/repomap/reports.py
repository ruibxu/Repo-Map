"""Read local evaluation reports without accepting arbitrary filesystem paths."""

import json
import math

from repomap.parsing import identity

QUALITY_FIELDS = ("recall@5", "recall@10", "recall@20", "mrr@10", "p50_ms", "p95_ms")
INDEX_FIELDS = ("files", "chunks", "total_seconds", "peak_rss_bytes")


def numeric_fields(value, keys):
    return isinstance(value, dict) and all(type(value.get(key)) in (int, float) and math.isfinite(value[key]) for key in keys)


def reports(data_dir):
    root = data_dir / "reports"
    if not root.exists():
        return []
    output = []
    for path in sorted(root.rglob("results.json")):
        if not path.resolve().is_relative_to(root.resolve()):
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(report, dict) or not all(isinstance(report.get(key), dict) for key in ("summary", "hardware", "indexing")):
                continue
            if not all(numeric_fields(value, QUALITY_FIELDS) for value in report["summary"].values()) or not all(numeric_fields(value, INDEX_FIELDS) for value in report["indexing"].values()):
                continue
            # Send summary metrics rather than thousands of skipped paths to the UI.
            # Full exclusion records remain in the original report on disk.
            indexing = {name: {**{key: value for key, value in metrics.items() if key != "skipped"},
                               "skipped_files": len(metrics.get("skipped", []))} for name, metrics in report["indexing"].items()}
            output.append({"id": identity(str(path.relative_to(root))), "name": str(path.parent.relative_to(root)),
                           **{key: report[key] for key in ("status", "split", "summary", "hardware")}, "indexing": indexing})
        except (ValueError, KeyError, TypeError, OSError):
            continue
    return output
