"""Local import, indexing, search, and evaluation commands."""

import argparse
import json
from pathlib import Path

from repomap.repositories import RepositoryCatalog
from repomap.indexing import Indexer, IndexStore
from repomap.vectors import VectorPipeline
from repomap.retrieval import SearchEngine, STRATEGIES
from repomap.evaluation import evaluate


def main():
    parser = argparse.ArgumentParser(prog="repomap")
    parser.add_argument("--data-dir", type=Path, default=Path(".repomap"))
    commands = parser.add_subparsers(dest="command", required=True)
    imported = commands.add_parser("import")
    imported.add_argument("kind", choices=["local", "github"])
    imported.add_argument("source")
    indexed = commands.add_parser("index")
    indexed.add_argument("repository_id")
    indexed.add_argument("--exclude", action="append", default=[])
    search = commands.add_parser("search")
    search.add_argument("repository_id")
    search.add_argument("snapshot_id")
    search.add_argument("query")
    search.add_argument("--strategy", choices=STRATEGIES, default="ast-aware")
    search.add_argument("--k", type=int, default=10)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("dataset", type=Path)
    evaluation.add_argument("--output", type=Path, default=Path(".repomap/reports"))
    evaluation.add_argument("--split", choices=["dev", "test"], default="test")
    evaluation.add_argument("--repeats", type=int, default=3)
    evaluation.add_argument("--allow-draft", action="store_true")
    args = parser.parse_args()
    catalog = RepositoryCatalog(args.data_dir)
    if args.command == "import":
        result = catalog.import_repository(args.kind, args.source)
    else:
        store = IndexStore(catalog)
        vectors = VectorPipeline(store)
        if args.command == "index":
            result = {"snapshot_id": Indexer(store, vectors).run(args.repository_id, args.exclude)}
        elif args.command == "search":
            result = SearchEngine(store, vectors).search(args.repository_id, args.snapshot_id, args.query, args.strategy, args.k)
        else:
            result = evaluate(SearchEngine(store, vectors), json.loads(args.dataset.read_text(encoding="utf-8")), args.output, args.split, args.repeats, args.allow_draft)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
