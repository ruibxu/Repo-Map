# Confirmed benchmark analysis

This run evaluates 45 held-out queries from 60 human-confirmed labels. Each of Flask, Express, and TypeScript contributes 15 test queries; its other 5 queries remain in the development split. Four strategies share each repository snapshot, chunks, filters, model, and K=20. There are 180 query/strategy rows and three warm latency repeats per row.

Vector-only has the highest Recall@20 (0.7000). Hybrid has the highest Recall@5 (0.5426) and MRR@10 (0.5455). AST-aware does not lead this run and has the largest p95 retrieval latency. These results describe this fixed corpus and implementation; they do not establish a general winner. Ranking constants and labels were not changed to favor a strategy.

See [report.md](report.md) for retrieval metrics, [results.csv](results.csv) for per-query measurements, and [results.json](results.json) for full configuration, versions, hardware, and indexing records.

## Indexing measurements

| Repository | Run | Files | Chunks | Build seconds | Parse seconds | Embed seconds | Files/second | Peak RSS MiB | Data directory MiB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| flask | full | 36 | 730 | 118.56 | 21.44 | 30.63 | 0.3037 | 859.4 | 32.3 |
| flask | incremental | 36 | 730 | 12.17 | 0.15 | 0.00 | 2.9590 | 793.3 | 56.4 |
| express | full | 16 | 338 | 25.65 | 2.16 | 15.13 | 0.6237 | 924.9 | 79.0 |
| express | incremental | 16 | 338 | 6.48 | 0.05 | 0.00 | 2.4703 | 707.9 | 98.1 |
| typescript | full | 360 | 26713 | 2068.59 | 80.44 | 971.42 | 0.1740 | 1552.0 | 731.4 |
| typescript | incremental | 360 | 26713 | 800.53 | 18.56 | 0.00 | 0.4497 | 1243.3 | 1058.0 |

Incremental measurements use unchanged source. All parsing and embedding outputs are reused, while new snapshot-specific SQLite/FTS5 and Chroma storage is built. They do not measure a changed-file workload. Full runs start with empty parsing/embedding caches in a fresh data directory; duplicate embedding inputs encountered within the TypeScript full run account for its 2,057 cache hits. The model download is already cached.

Build timing covers capture, parsing, binding, chunking, and text/vector storage; subsequent metric collection and retention cleanup are outside that timer. RSS is sampled process memory and includes the loaded model. Disk usage measures the selected data directory and is cumulative across repositories and snapshots. Local source checkouts outside that directory are excluded.

## Conditions and boundaries

The host is Windows 10 with Python 3.10.7, 6 physical/12 logical CPU cores, and approximately 15.7 GiB RAM. Embedding and Chroma worker configuration uses four CPU threads. The model is `sentence-transformers/all-MiniLM-L6-v2` at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Parser extraction is v6; chunking is `v2-statements`, with a 512-token limit including path/symbol context and 64-token overlap. Oversized statements require token-level splitting.

Retrieval follows indexing in the same process with the model loaded. The reported p50/p95 values use repeated warm retrieval calls. Separate first-query measurements are retained in CSV/JSON and are not process-cold startup measurements. Local development checks ran on the same workstation during indexing, so indexing figures are workstation observations rather than isolated performance guarantees. LLM generation is excluded.

The recorded implementation commit is `853f7e04b630b6a987f3efcfb387dfe85158d181`. The raw report correctly records a dirty working tree at metadata capture: pending edits were confined to frontend navigation and answer-error handling. Retrieval, indexing, evaluation, labels, and ranking configuration matched that commit.

The corpus excludes tests, examples, documentation, generated declarations, tooling, dependency/build directories, and files over 1 MB using recorded rules. TypeScript contains 360 eligible files and 26,713 chunks; its checker exceeds the size cap and is excluded. The full raw JSON retains all exclusion records. These are source-corpus results, not whole-repository coverage claims.
