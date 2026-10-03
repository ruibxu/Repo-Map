# repoMap Evaluation

Status: human-confirmed. Split: test. Queries: 45.

One first-query measurement per strategy/query followed by repeated warm runs; not process-cold latency.

| Strategy | Recall@5 | Recall@10 | Recall@20 | MRR@10 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| vector-only | 0.4648 | 0.6130 | 0.7000 | 0.5348 | 25.3684 | 521.6631 |
| bm25 | 0.4185 | 0.5000 | 0.5630 | 0.4316 | 17.7786 | 537.5113 |
| hybrid | 0.5426 | 0.6167 | 0.6667 | 0.5455 | 29.9105 | 606.2560 |
| ast-aware | 0.5352 | 0.6167 | 0.6667 | 0.4918 | 43.3890 | 1289.7120 |

See results.json for immutable commits, model identity, index metrics, hardware, and dependency versions. LLM generation is excluded. No superiority claim is assumed.
