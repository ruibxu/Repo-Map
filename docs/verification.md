# Implementation verification

Verified on October 3, 2026. All five planned MVP phases have implemented execution paths. The constraints in AGENTS.md remain project requirements rather than a completion report.

| Phase | Implemented deliverables | Verification evidence |
|---|---|---|
| 1 | FastAPI/SQLite catalog, public GitHub commit-pinned imports, local Git registration, React import view | Live Express GitHub import; persistence, idempotency, URL validation, failed-import isolation tests |
| 2 | Tree-sitter extraction, conservative binding, captured source, caches, immutable snapshots, persisted serial tasks | Python/JS/JSX/TS/TSX tests; nested scopes, aliases, relative imports, re-exports, tsconfig paths, ambiguous references, Unicode positions, syntax-error fallback, additions/deletions/modifications, restart recovery, failure preservation and isolation tests |
| 3 | Chroma cosine retrieval, per-snapshot FTS5 BM25, RRF hybrid, one-hop AST-aware expansion, CLI evaluation | Real MiniLM/Chroma integration exercising all four strategies; filter/isolation and known-ranking metric tests; complete held-out benchmark |
| 4 | Snapshot source, position/symbol definition and reference lookup, one-hop graph APIs and React explorer | API tests and browser checks of source links, resolved authentication references, graph expansion, a real background update, and rapid result navigation |
| 5 | Optional Chat Completions answers, bounded evidence, citation validation, report API/viewer, reviewed benchmark | Mocked provider error/citation tests and a real local HTTP fixture without credentials; 60 human-confirmed labels; 45 test queries/180 strategy rows exported as JSON, CSV and Markdown |

The final backend test run passed **49 tests**, including the real local embedding model. One upstream AnyIO deprecation warning was emitted. The frontend TypeScript check and Vite production build passed. `pip check` reported no broken requirements; the frontend dependency audit previously reported no vulnerabilities.

Actual full-suite command from the repository root:

```powershell
$env:REPOMAP_TEST_LOCAL_MODEL = '1'
$env:HF_HUB_OFFLINE = '1'
$env:OMP_NUM_THREADS = '4'
$env:OPENBLAS_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
.\.venv\Scripts\python -m pytest -q
```

`HF_HUB_OFFLINE` requires the model to have been downloaded already. Without the integration-test environment flag, the real-model test is intentionally skipped. The verified frontend build command is `npm run build` from `frontend`.

See [the confirmed benchmark analysis](../benchmarks/results/confirmed/README.md) for quality, latency, full/unchanged incremental indexing measurements, exact conditions and corpus boundaries. Artifact validation checked all 180 rows, the 45 held-out query IDs, three repeats per row, the 60 confirmed labels and their hash, and matching CSV/JSON row counts.

A live cloud LLM provider was not configured. The local HTTP fixture verifies request compatibility and citation handling, not a model's reasoning quality. Search and captured-source inspection work without LLM credentials. The implementation uses conservative structural rules rather than full type inference; dynamic and ambiguous relationships retain their confidence status. Private repositories, multiple users, cross-repository queries, live watching, external queues, extra vector backends, query rewriting and rerankers remain outside the first-release scope.
