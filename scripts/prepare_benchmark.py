"""Prepare pinned source proposals, index twice, and run a provisional benchmark."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.specification import QUERIES, REPOSITORIES
from repomap.evaluation import evaluate
from repomap.indexing import Indexer, IndexStore
from repomap.parsing import VERSION, parse
from repomap.repositories import RepositoryCatalog, git
from repomap.retrieval import SearchEngine
from repomap.vectors import VectorPipeline

EXCLUSIONS = ["tests/*", "test/*", "examples/*", "docs/*", ".github/*", ".vscode/*", "src/testRunner/*", "src/harness/*", "src/lib/*", "lib/*", "package-lock.json", "uv.lock"]


def proposals(root):
    queries = []
    for name, specs in QUERIES.items():
        checkout = root / name
        if git("-C", str(checkout), "rev-parse", "HEAD") != REPOSITORIES[name]["commit_sha"]:
            raise ValueError(f"{name} checkout does not match the pinned benchmark commit.")
        cache = {}
        for index, (query, path, symbol_name, category) in enumerate(specs):
            if path not in cache:
                cache[path] = parse(path, (checkout / path).read_text(encoding="utf-8"))
            matches = [s for s in cache[path]["symbols"] if s["qualified_name"] == symbol_name or s["name"] == symbol_name]
            if not matches:
                raise ValueError(f"Missing annotation target {name}:{path}:{symbol_name}")
            target = matches[0]
            queries.append({"id": f"{name}-{index + 1:02}", "repository": name, "query": query,
                "category": category, "split": "dev" if index < 5 else "test", "human_confirmed": False,
                "relevant": [{"path": path, "start_line": target["start_line"],
                              "end_line": min(target["end_line"], target["start_line"] + 30)}],
                "proposal_symbol": target["qualified_name"]})
    return queries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations-only", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=Path(".repomap"))
    args = parser.parse_args()
    root = Path(".repomap/benchmarks")
    queries = proposals(root)
    manifest = {"repositories": [{"name": name, **entry} for name, entry in REPOSITORIES.items()], "queries": queries,
                "annotation_status": "Agent-generated source range proposals; require human review before final evaluation."}
    annotation_path = Path("benchmarks/annotations.json")
    if annotation_path.exists():
        manifest = json.loads(annotation_path.read_text(encoding="utf-8"))
        queries = manifest["queries"]
    else:
        annotation_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if args.annotations_only:
        print("Loaded 60 annotations; existing review status was preserved.", flush=True)
        return
    catalog = RepositoryCatalog(args.data_dir)
    store = IndexStore(catalog)
    vectors = VectorPipeline(store)
    indexer = Indexer(store, vectors)
    entries = []
    for name, spec in REPOSITORIES.items():
        repository = catalog.import_repository("local", str((root / name).resolve()))
        exclusions = [p for p in EXCLUSIONS if p != "lib/*" or name == "typescript"]
        print(f"Indexing {name} at {spec['commit_sha']}", flush=True)
        snapshots = store.snapshots(repository["id"])
        ready = [s for s in snapshots if s["status"] == "ready" and s["commit_sha"] == spec["commit_sha"]
                 and s["metrics"].get("parser") == VERSION and s["metrics"].get("exclusions") == exclusions
                 and s["metrics"].get("model") == vectors.encoder.fingerprint]
        if len(ready) >= 2:
            full, incremental = ready[1]["id"], ready[0]["id"]
        else:
            full = indexer.run(repository["id"], exclusions, lambda value: print(f"{name} full {value:.0%}", flush=True) if value == 1 else None)
            incremental = indexer.run(repository["id"], exclusions)
        runs = {s["id"]: s for s in store.snapshots(repository["id"])}
        entries.append({"name": name, **spec, "repository_id": repository["id"], "snapshot_id": incremental,
                        "exclusions": exclusions, "indexing_runs": {"full": runs[full]["metrics"], "incremental": runs[incremental]["metrics"]}})
        print(f"Completed {name}: {runs[incremental]['metrics']['chunks']} chunks", flush=True)
    dataset = {**manifest, "repositories": entries}
    (args.data_dir / "benchmark-runtime.json").write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    confirmed = all(q.get("human_confirmed") for q in queries)
    report_name = "confirmed" if confirmed else "provisional"
    report_path = Path(".repomap/reports") / report_name
    result = evaluate(SearchEngine(store, vectors), dataset, report_path, repeats=3, allow_draft=not confirmed)
    destination = Path("benchmarks/results") / report_name
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("results.json", "results.csv", "report.md"):
        (destination / name).write_bytes((report_path / name).read_bytes())
    print(json.dumps(result["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
