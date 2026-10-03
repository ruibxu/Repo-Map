"""Version-pinned retrieval evaluation without tuning on held-out queries."""

import csv
import importlib.metadata
import json
import platform
import statistics
import time
from pathlib import Path

from repomap.retrieval import STRATEGIES


def metrics(results, relevant):
    ids = [r["id"] for r in results]
    if not relevant:
        raise ValueError("A query has no relevant indexed chunks; check its source annotations.")
    return {**{f"recall@{k}": len(set(ids[:k]) & relevant) / len(relevant) for k in (5, 10, 20)},
            "mrr@10": next((1 / rank for rank, id_ in enumerate(ids[:10], 1) if id_ in relevant), 0)}


def evaluate(engine, dataset, output: Path, split="test", repeats=3, allow_draft=False):
    if repeats < 1 or split not in {"dev", "test"}:
        raise ValueError("Choose dev or test and at least one repeat.")
    if not allow_draft and not all(q.get("human_confirmed") for q in dataset["queries"]):
        raise ValueError("Ground truth requires human confirmation. Use --allow-draft only for clearly labeled provisional runs.")
    rows, indexing = [], {}
    for entry in dataset["repositories"]:
        snapshot = engine.store.require(entry["repository_id"], entry["snapshot_id"])
        if snapshot["commit_sha"] != entry["commit_sha"]:
            raise ValueError("Benchmark commit does not match the indexed snapshot.")
        indexing[entry["name"]] = json.loads(snapshot["metrics"])
    entries = {entry["name"]: entry for entry in dataset["repositories"]}
    for query in dataset["queries"]:
        if query["split"] != split:
            continue
        entry = entries[query["repository"]]
        with engine.store.catalog.connect() as db:
            chunks = [json.loads(r["data"]) for r in db.execute("SELECT data FROM chunks WHERE snapshot_id=?", (entry["snapshot_id"],))]
        relevant = {c["id"] for c in chunks for annotation in query["relevant"] if c["path"] == annotation["path"] and c["start_line"] <= annotation["end_line"] and c["end_line"] >= annotation["start_line"]}
        for strategy in STRATEGIES:
            args = (entry["repository_id"], entry["snapshot_id"], query["query"], strategy, 20)
            first = engine.search(*args)
            warm = [engine.search(*args) for _ in range(repeats)]
            rows.append({"query_id": query["id"], "repository": entry["name"], "strategy": strategy,
                **metrics(warm[-1]["results"], relevant), "first_query_ms": first["latency_ms"],
                "latencies_ms": [r["latency_ms"] for r in warm]})
    if not rows:
        raise ValueError("The selected evaluation split is empty.")
    summary = {}
    for strategy in STRATEGIES:
        selected = [r for r in rows if r["strategy"] == strategy]
        latencies = sorted(t for r in selected for t in r["latencies_ms"])
        summary[strategy] = {key: statistics.mean(r[key] for r in selected) for key in ("recall@5", "recall@10", "recall@20", "mrr@10")}
        summary[strategy].update({"p50_ms": statistics.median(latencies), "p95_ms": latencies[max(0, __import__('math').ceil(len(latencies) * .95) - 1)]})
    report = {"status": "provisional" if allow_draft else "human-confirmed", "split": split,
        "repeats": repeats, "conditions": "One first-query measurement per strategy/query followed by repeated warm runs; not process-cold latency.",
        "hardware": {"platform": platform.platform(), "processor": platform.processor(), "python": platform.python_version()},
        "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "summary": summary, "indexing": indexing, "rows": rows, "repositories": dataset["repositories"]}
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    flat = [{**{k: v for k, v in row.items() if k != "latencies_ms"}, "latencies_ms": json.dumps(row["latencies_ms"])} for row in rows]
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)
    text = f"# repoMap Evaluation\n\nStatus: {report['status']}. Split: {split}. Queries: {len(rows) // 4}.\n\n{report['conditions']}\n\n"
    text += "| Strategy | Recall@5 | Recall@10 | Recall@20 | MRR@10 | p50 ms | p95 ms |\n|---|---:|---:|---:|---:|---:|---:|\n"
    for strategy, values in summary.items():
        text += "| " + strategy + " | " + " | ".join(f"{v:.4f}" for v in values.values()) + " |\n"
    text += "\nSee results.json for immutable commits, model identity, index metrics, hardware, and dependency versions. LLM generation is excluded. No superiority claim is assumed.\n"
    (output / "report.md").write_text(text, encoding="utf-8")
    return report
