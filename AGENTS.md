# RepoMap Agent Guidelines

## Applicability and Current Status

These guidelines apply throughout the repository. Follow the confirmed project constraints below. Obtain explicit user authorization before changing the technology stack, product scope, or evaluation protocol.

This document defines the target architecture and requirements; it is not a feature completion report. Consult README.md and actual verification results for implementation status. Progress reports, README content, and change descriptions must distinguish implemented, planned, and unverified behavior using actual code and verification results.

## Language Requirements

Use English for all project documentation and code, including AGENTS.md, README files, design documents, evaluation reports, identifiers, comments, docstrings, test descriptions, and authored user-facing messages. Preserve externally supplied source code, repository content, and quoted data in their original form when necessary for accurate indexing and evaluation.

## Project Goals and Scope

RepoMap is a local, single-user code search and repository intelligence research MVP. It combines AST analysis and retrieval to locate functionality, find definitions and references, explore dependencies, and reproducibly benchmark retrieval strategies.

- Support public GitHub repositories and local Git directories, with management of multiple repositories.
- Restrict each query to one repository and one published index snapshot.
- Support structural parsing for Python, JavaScript, TypeScript, JSX, and TSX. Provide text retrieval for other eligible text files.
- Run indexing, embeddings, and storage locally. Cloud LLM answers are optional; search and context inspection must work without API credentials.
- Exclude private GitHub repositories, multi-user authorization, cross-repository search, live file watching, and complete type inference from the first release.

## Fixed Technology Stack and Architecture Boundaries

- Use Python and FastAPI for the backend, with `/api/v1` as the public API prefix.
- Use Tree-sitter for source parsing and language-specific rules for symbol binding.
- Use SQLite as the source of truth for structured data and indexing state, with FTS5 for BM25.
- Use Chroma PersistentClient for local vectors. Do not add FAISS or another vector backend in the first release.
- Use React, TypeScript, and Vite for the frontend. Access data through backend APIs rather than directly accessing databases, vector storage, or repository files.
- Default to `sentence-transformers/all-MiniLM-L6-v2` for embeddings, with configurable replacement. The model requires an initial download; record the actual model revision in evaluations.
- Integrate optional LLM answers through a Chat Completions-compatible service. Configure credentials through environment variables and bind the application to localhost by default.

Separate repository acquisition, language parsing, symbol binding, storage, retrieval, question answering, evaluation, and frontend responsibilities. Parsing must not depend on the UI or an LLM. Keep answer generation outside the four retrieval strategies. Lock dependency versions during implementation.

## Indexing and Data Contracts

- Pin GitHub imports to a commit SHA. For local directories, read Git-tracked files, allow uncommitted changes, and record actual content hashes.
- Create immutable snapshots for each indexing run. Updates are user-triggered. Publish a snapshot only after parsing, text indexing, structural relationships, and vector indexing have all completed.
- Retain the current and previous successful snapshots. Indexing failures must preserve the previous successful version. Bind queries to explicit snapshots and never mix old and new data.
- Reuse parsing and embedding caches for unchanged files through content hashes. Cache identities must include parser, chunking configuration, or model versions that affect the cached output.
- Exclude binary files, dependency directories, build artifacts, generated files, and files larger than 1 MB. Support configurable exclusions and show reasons for skipped files.
- Run background indexing serially and persist task status and progress in SQLite. Mark interrupted tasks as failed after restart and allow retries. Do not introduce an external task queue in the first release.
- Store snapshots, files, symbols, references, dependency edges, chunks, and tasks in SQLite. Use corresponding chunk IDs in Chroma and isolate snapshot identities.
- Use functions, methods, and class headers as primary chunks, including signatures, documentation, and paths. Split long chunks at statement boundaries, defaulting to 512 embedding tokens with 64 tokens of overlap. Use equivalent windows for unstructured text.

## Structural Analysis and Reference Confidence

Extract functions, classes, methods, scopes, imports, exports, identifier references, and call sites. Record paths, languages, qualified names, byte ranges, and line numbers.

- Cover relative imports and module lookup in Python binding rules. Cover relative imports, `tsconfig` paths, and re-exports in TS/JS rules.
- Record external dependencies as module edges without inventing repository-local definitions.
- Distinguish `resolved`, `candidate`, and `unresolved` references. Expose binding status in definition and reference queries.
- Tree-sitter provides syntax structure, not complete semantic or type analysis. Do not establish definite relationships solely from matching names, syntax patterns, dynamic calls, or ambiguous member access.
- Record syntax diagnostics and retain valid structures that can be extracted. Fall back to text retrieval for regions that cannot be parsed safely; do not generate misleading definite bindings.

## Retrieval and Optional Question Answering

Implement four independently runnable strategies using the same snapshot, shared chunk corpus, and filters:

1. `vector-only`: local embeddings and cosine similarity retrieval.
2. `bm25`: FTS5 retrieval over paths, symbols, documentation, and code, with additional snake_case and camelCase token splitting.
3. `hybrid`: retrieve the top 100 candidates from each channel and fuse them using RRF with a default constant of 60.
4. `ast-aware`: augment hybrid retrieval with exact symbol matching and one-hop expansion through resolved import, call, and containment relationships. Add at most 5 chunks per seed, assign expanded chunks 0.5 times the seed score, and deduplicate by retaining the highest score for each chunk.

Retain explainable match origins and ranking information. Do not add LLM query rewriting or a reranker in the first release, to avoid confounding strategy comparisons.

Default natural-language question answering to `ast-aware`. Return retrieval results first, then pass at most 20 chunks and approximately 6,000 total tokens of focused context to the optional LLM. Answers must cite chunk IDs that map to files and line numbers. Explicitly state when evidence is insufficient and never fabricate code citations.

## API and Interface Contracts

- Provide repository import and listing, indexing triggers and status polling, search, definition and reference lookup, dependency graphs, file-range reading, and optional question answering.
- Search inputs include repository, snapshot, query, strategy, K, and optional language and path filters.
- Search results consistently include chunk ID, file path, line range, symbol, excerpt, score, and match origin. All query interfaces carry explicit snapshot identities.
- Query definitions and references by file position or symbol ID. Retrieve one-hop graph neighbors by file or symbol.
- Restrict file reads to the corresponding repository snapshot and prevent path traversal.
- Provide repository and task pages, search strategy switching, code and reference sidebars, expandable dependency graphs, cited answers, and evaluation results in the frontend.

## Evaluation Protocol

- Use Flask, Express, and TypeScript as the three benchmark repositories. Select and record an exact commit SHA for each; do not use floating branches as final benchmark identities.
- Manually label 20 English queries per repository, totaling 60, covering functionality location, symbol location, call relationships, and dependency exploration.
- Reserve 5 queries per repository for development and the remaining 15 for testing. Tune only on the development set and use the 45 test queries for final comparisons.
- Store queries, relevant files, and source ranges in annotations, then map them to the shared chunk corpus. Ground truth requires human confirmation; model-generated results are not automatically correct labels.
- Share repository versions, chunks, embedding models, filters, and K across strategies. Report Recall@5/10/20, MRR@10, and retrieval latency p50/p95.
- Separately record full and incremental indexing time, parsing and embedding time, throughput, peak memory, and disk usage.
- Record hardware, dependency and model versions, runtime configuration, and cold-start and warm-up conditions. Report LLM latency separately from retrieval latency.
- Export JSON, CSV, and a readable report. Do not assume `ast-aware` must win or manipulate test labels or evaluation definitions to favor a strategy.

## Development and Verification

- Add meaningful tests where new behavior requires them. Documentation-only changes and low-impact reversible edits do not require new tests.
- Prioritize parsing ranges, nested scopes, import aliases, re-exports, ambiguous references, syntax-error fallback, file additions/deletions/modifications, incremental caching, failure recovery, and snapshot isolation.
- Verify the end-to-end flow: import a repository, index it, search with all four strategies, inspect definitions/references/dependencies, optionally generate a cited answer, update the index, and run the benchmark.
- Run checks relevant to the change. Report actual results and unverified areas; do not claim that unexecuted tests passed.
- Document only commands that actually exist and have been confirmed. Do not invent installation, test, startup, or evaluation commands before initialization.
- Do not commit API keys, credentials, imported repositories, model caches, databases, vector data, or other runtime artifacts. Configure appropriate ignore rules during initialization.

## Implementation Sequence

The following phases are planned work. Build verifiable deliverables in this order:

1. Project skeleton and repository import.
2. AST analysis, symbol binding, and SQLite indexing.
3. Four retrieval strategies and an evaluation CLI.
4. React code browsing, references, and dependency graph exploration.
5. Optional LLM answers, the complete manually labeled benchmark, and evaluation reports.

Do not introduce external task queues, additional vector backends, LLM rerankers, or out-of-scope features ahead of this sequence. Determine phase completion from code, tests, and functioning execution paths.
