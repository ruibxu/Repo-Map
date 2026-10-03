# repoMap

A local, single-user repository intelligence and retrieval research engine.

## Implementation status

The first implementation provides a FastAPI repository catalog backed by SQLite, public GitHub imports pinned to commit SHAs, local Git root registration, and a React repository import screen. Duplicate imports return the existing catalog entry. Git operations disable interactive credential prompts; public GitHub clones disable Git credential helpers.

Tree-sitter extraction, conservative lexical/import binding, immutable source capture, parsing and embedding caches, serial indexing tasks, Chroma vectors, per-snapshot FTS5 indexes, and all four retrieval strategies are implemented. Indexes are published only after structural, text, and vector indexing succeed. Structural query APIs, graph browsing, question answering, and the full benchmark are subsequent milestones. An imported repository is not an indexed snapshot. Local registration records the current HEAD without changing the working tree. GitHub cloning runs synchronously with a 120-second Git operation timeout. Failed clone directories may remain under the ignored data directory, but failed imports are not added to the catalog.

## Local development on Windows

Requires Python 3.10 or newer, Git, and Node.js 22 or newer. Run backend commands from the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python -m pip install --no-build-isolation -e .
.\.venv\Scripts\python -m uvicorn repomap.api:create_app --factory --host 127.0.0.1 --port 8000
```

SQLite and downloaded repositories are stored in `.repomap/`. Set `REPOMAP_DATA_DIR` to change this location. The backend API documentation is available at `http://127.0.0.1:8000/docs` when running.

In a second PowerShell terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open the localhost URL printed by Vite. Its development server proxies `/api` requests to the backend on port 8000. Local import paths refer to directories on the backend machine. Select a Git repository root with at least one commit.

## Verification

From the repository root:

```powershell
.\.venv\Scripts\python -m pytest -q
```

From `frontend`:

```powershell
npm run build
```

Tests cover local import persistence and idempotency, invalid URLs, nested-directory rejection, API validation, mocked GitHub commit pinning, and failed-import catalog isolation. Mocked acquisition tests do not establish live GitHub clone behavior. A production frontend build does not establish browser interaction correctness.

## Indexing, search, and evaluation CLI

Run commands from the repository root. Import returns a repository ID; indexing returns a snapshot ID. Substitute those actual IDs in later commands:

```powershell
.\.venv\Scripts\python -m repomap.cli import local 'D:\projects\example'
.\.venv\Scripts\python -m repomap.cli index REPOSITORY_ID
.\.venv\Scripts\python -m repomap.cli search REPOSITORY_ID SNAPSHOT_ID 'Where is authentication implemented?' --strategy ast-aware
.\.venv\Scripts\python -m repomap.cli evaluate DATASET.json --output .repomap/reports --split test
```

The first indexing run downloads the CPU embedding model. Configure `REPOMAP_EMBEDDING_MODEL` and optionally `REPOMAP_EMBEDDING_REVISION` to replace it. Every snapshot records the resolved immutable model revision. Changing models requires reindexing. The encoder uses a 512-token limit; chunks reserve space for path and symbol context. The default MiniLM model was trained with a shorter sequence limit, so longer chunks are a documented model tradeoff rather than a claim of optimal quality.

Evaluation datasets contain `repositories` (name, repository_id, snapshot_id, commit_sha) and `queries` (id, repository, query, split, human_confirmed, relevant source path/start_line/end_line ranges). Final evaluation rejects unconfirmed ground truth. `--allow-draft` explicitly produces provisional results. Output includes JSON, CSV, and Markdown, retrieval quality and latency, indexing metrics, model identity, hardware, and installed dependency versions.

After downloading the model, run the opt-in integration test:

```powershell
$env:REPOMAP_TEST_LOCAL_MODEL = '1'
.\.venv\Scripts\python -m pytest -q tests/test_local_model.py
```

`POST /api/v1/repositories/{id}/index` queues an index with an optional `exclusions` list. Poll `/api/v1/tasks/{task_id}`, list `/api/v1/repositories/{id}/snapshots`, and search with `POST /api/v1/search`. Unpublished, failed, retired, and foreign-repository snapshots cannot be searched.

## Next phases

1. AST parsing, conservative symbol binding, and immutable SQLite index snapshots.
2. Vector-only, BM25, hybrid, and AST-aware retrieval with an evaluation CLI.
3. Code browsing, reference lookup, and dependency graph exploration in React.
4. Optional cited LLM answers and a manually confirmed benchmark for Flask, Express, and TypeScript.

See [AGENTS.md](AGENTS.md) for architecture constraints and the evaluation protocol.
