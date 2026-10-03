"""Read local evaluation reports without accepting arbitrary filesystem paths."""

import json

from repomap.parsing import identity


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
            output.append({"id": identity(str(path.relative_to(root))), "name": str(path.parent.relative_to(root)),
                           **{key: report[key] for key in ("status", "split", "summary", "hardware", "indexing")}})
        except (ValueError, KeyError, OSError):
            continue
    return output
