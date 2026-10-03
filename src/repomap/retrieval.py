"""Comparable BM25, vector, hybrid, and AST-aware retrieval."""

import json
import time
from collections import defaultdict

from repomap.vectors import fts_table, terms

STRATEGIES = ("vector-only", "bm25", "hybrid", "ast-aware")


class SearchEngine:
    def __init__(self, store, vectors):
        self.store, self.vectors = store, vectors

    def search(self, repository_id, snapshot_id, query, strategy="ast-aware", k=10, language=None, path_prefix=None):
        started = time.perf_counter()
        snapshot = self.store.require(repository_id, snapshot_id)
        if strategy not in STRATEGIES or not 1 <= k <= 100 or not query.strip():
            raise ValueError("Use a supported strategy, a nonempty query, and K between 1 and 100.")
        with self.store.catalog.connect() as db:
            rows = db.execute("SELECT data FROM chunks WHERE snapshot_id=?", (snapshot_id,)).fetchall()
        chunks = {c["id"]: c for c in (json.loads(r["data"]) for r in rows)
                  if (not language or c["language"] == language) and (not path_prefix or c["path"].startswith(path_prefix))}
        lexical, semantic = [], []
        if strategy != "vector-only":
            tokens = list(dict.fromkeys(terms(query)))[:64]
            if tokens:
                expression = " OR ".join('"' + token + '"' for token in tokens)
                with self.store.catalog.connect() as db:
                    table = fts_table(snapshot_id)
                    hits = db.execute(f"SELECT id, bm25({table},0,2,4,1) AS score FROM {table} WHERE {table} MATCH ? ORDER BY score, id", (expression,)).fetchall()
                lexical = [(r["id"], -r["score"]) for r in hits if r["id"] in chunks][:100]
        if strategy != "bm25" and chunks:
            if json.loads(snapshot["metrics"])["model"] != self.vectors.encoder.fingerprint:
                raise ValueError("The configured embedding model differs from this snapshot. Restore its model or reindex.")
            where = None
            paths = sorted(set(c["path"] for c in chunks.values()))
            if language or path_prefix:
                where = {"path": {"$in": paths}}
            result = self.vectors.collection(snapshot_id).query(
                query_embeddings=self.vectors.encoder.encode([query]), n_results=min(100, len(chunks)),
                where=where, include=["distances"])
            semantic = [(id_, 1 - distance) for id_, distance in zip(result["ids"][0], result["distances"][0]) if id_ in chunks]
        scores, origins = {}, {}

        def add(id_, score, origin, maximum=False):
            if id_ not in chunks:
                return
            scores[id_] = max(scores.get(id_, 0), score) if maximum else scores.get(id_, 0) + score
            origins.setdefault(id_, [])
            if origin not in origins[id_]:
                origins[id_].append(origin)

        if strategy == "bm25":
            for id_, score in lexical:
                add(id_, score, "bm25")
        elif strategy == "vector-only":
            for id_, score in semantic:
                add(id_, score, "vector")
        else:
            for origin, channel in (("bm25", lexical), ("vector", semantic)):
                for rank, (id_, _) in enumerate(channel, 1):
                    add(id_, 1 / (60 + rank), origin)
        if strategy == "ast-aware":
            names = set(query.strip().split())
            symbols = self.store.records("symbols", snapshot_id)
            exact = {s["id"] for s in symbols if s["name"] in names or s["qualified_name"] == query.strip()}
            for id_, chunk in chunks.items():
                if chunk["symbol_id"] in exact:
                    add(id_, 1 / 61, "exact-symbol")
            seeds = sorted(scores, key=lambda id_: (-scores[id_], id_))[:20]
            seed_scores = {id_: scores[id_] for id_ in seeds}
            edges = self.store.records("edges", snapshot_id)
            by_path, by_symbol, imported_paths, related_symbols = (defaultdict(set) for _ in range(4))
            for id_, chunk in chunks.items():
                by_path[chunk["path"]].add(id_)
                if chunk["symbol_id"]:
                    by_symbol[chunk["symbol_id"]].add(id_)
            for edge in edges:
                if edge["status"] != "resolved":
                    continue
                if edge["kind"] == "import":
                    imported_paths[edge["source_path"]].add(edge["target_path"])
                else:
                    related_symbols[edge["source_symbol"]].add(edge["target_symbol"])
                    related_symbols[edge["target_symbol"]].add(edge["source_symbol"])
            for seed in seeds:
                chunk = chunks[seed]
                neighbors = set()
                for path in imported_paths[chunk["path"]]:
                    neighbors.update(by_path[path])
                if chunk["symbol_id"]:
                    for symbol in related_symbols[chunk["symbol_id"]]:
                        neighbors.update(by_symbol[symbol])
                for id_ in sorted(neighbors - {seed})[:5]:
                    add(id_, seed_scores[seed] * 0.5, "dependency-expansion", maximum=True)
        ranked = sorted(scores, key=lambda id_: (-scores[id_], id_))[:k]
        return {"repository_id": repository_id, "snapshot_id": snapshot_id, "strategy": strategy,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "results": [{key: value for key, value in chunks[id_].items() if key != "embedding_text"} | {"score": scores[id_], "origins": origins[id_]} for id_ in ranked]}
