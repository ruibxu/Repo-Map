# Fixed repository retrieval benchmark

The benchmark uses Flask, Express, and TypeScript at exact commits recorded in `specification.py` and `annotations.json`. There are 20 English queries per repository: the first 5 are development queries and the remaining 15 are held-out test queries. Categories cover functionality, symbols, calls, and dependencies.

## Annotation status

`annotations.json` contains 60 human-confirmed query labels. The user supplied 14 source-range corrections and explicitly confirmed the remaining 46 labels on October 2, 2026. Review provenance is recorded on each query. The Express JSONP correction ends at line 308, the exact implementation boundary at its pinned commit.

Results produced with `--allow-draft` are provisional. They validate the execution pipeline and expose measurements; they do not establish definitive retrieval quality or superiority of any method. Human confirmation must come from an actual reviewer, never from an agent changing the flag to satisfy a test.

## Reproduction

Clone the three URLs from `specification.py` into `.repomap/benchmarks/flask`, `.repomap/benchmarks/express`, and `.repomap/benchmarks/typescript`. Check out their recorded commits with detached HEADs. The TypeScript commit corresponds to v5.7.3 and intentionally uses the TypeScript compiler implementation.

From the project root:

```powershell
.\.venv\Scripts\python scripts/prepare_benchmark.py --annotations-only
.\.venv\Scripts\python scripts/prepare_benchmark.py --data-dir .repomap/benchmark-current
```

The preparation script preserves existing reviewed annotations, creates full and unchanged incremental indexes, saves `benchmark-runtime.json` under the selected data directory, and runs a test-split evaluation. It reuses existing pairs of published snapshots only when parser, model, commit, and exclusions match. A fresh data directory provides cold parsing and embedding caches; model download/cache conditions must still be reported separately. Fully confirmed annotations produce `confirmed` reports; otherwise the run is provisional.

Tests, examples, documentation, generated library declarations, and tooling directories are excluded through explicit patterns recorded with each runtime repository entry. Standard index exclusions also apply, including the 1 MB file cap. Consequently, the TypeScript checker is excluded: it exceeds that cap. This is a documented corpus boundary, not a whole-repository quality claim.

Reports include JSON, CSV, and Markdown, with commit/model identities, shared chunks, configuration, full/incremental index measurements, sampled peak process RSS, total local data disk usage, quality metrics, and first-query versus repeated warm latency. RSS includes the host process and loaded model; disk usage includes caches and imported repositories. First-query latency is not process-cold latency. LLM generation is excluded.

Results also record the implementation Git commit and whether the working tree was dirty, the parser and statement-aware chunking versions, and binding time. The default CPU embedding and Chroma worker count is four. Full indexes use a fresh data directory for cold parsing/embedding caches; the model is already downloaded. The unchanged incremental run reuses those caches and rebuilds snapshot-specific storage.
