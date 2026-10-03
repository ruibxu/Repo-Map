# repoMap

A local, single-user repository intelligence and retrieval research engine.

## Implementation status

The first implementation provides a FastAPI repository catalog backed by SQLite, public GitHub imports pinned to commit SHAs, local Git root registration, and a React repository import screen. Duplicate imports return the existing catalog entry. Git operations disable interactive credential prompts; public GitHub clones disable Git credential helpers.

AST parsing, index snapshots, embedding generation, the four retrieval strategies, reference lookup, dependency graphs, question answering, and benchmarks are planned work. An imported repository is not an indexed snapshot. Local registration records the current HEAD without changing the working tree. GitHub cloning runs synchronously with a 120-second Git operation timeout; persisted background indexing tasks belong to the next phase. Failed clone directories may remain under the ignored data directory, but failed imports are not added to the catalog.

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

## Next phases

1. AST parsing, conservative symbol binding, and immutable SQLite index snapshots.
2. Vector-only, BM25, hybrid, and AST-aware retrieval with an evaluation CLI.
3. Code browsing, reference lookup, and dependency graph exploration in React.
4. Optional cited LLM answers and a manually confirmed benchmark for Flask, Express, and TypeScript.

See [AGENTS.md](AGENTS.md) for architecture constraints and the evaluation protocol.
