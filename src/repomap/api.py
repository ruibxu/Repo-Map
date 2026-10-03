"""FastAPI application factory for local repository management."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from repomap.repositories import ImportErrorDetail, RepositoryCatalog
from repomap.indexing import IndexStore, Indexer, TaskManager
from repomap.vectors import VectorPipeline
from repomap.retrieval import SearchEngine
from repomap.exploration import Explorer


class RepositoryImport(BaseModel):
    kind: Literal["github", "local"]
    source: str = Field(min_length=1, max_length=4096)


class IndexRequest(BaseModel):
    exclusions: list[str] = Field(default_factory=list, max_length=100)


class SearchRequest(BaseModel):
    repository_id: str
    snapshot_id: str
    query: str = Field(min_length=1, max_length=4096)
    strategy: Literal["vector-only", "bm25", "hybrid", "ast-aware"] = "ast-aware"
    k: int = Field(default=10, ge=1, le=100)
    language: str | None = None
    path_prefix: str | None = None


def create_app(data_dir: Path | None = None, encoder=None) -> FastAPI:
    catalog = RepositoryCatalog(data_dir or Path(os.environ.get("REPOMAP_DATA_DIR", ".repomap")))
    store = IndexStore(catalog)
    vectors = VectorPipeline(store, encoder)
    engine = SearchEngine(store, vectors)
    explorer = Explorer(store)
    tasks = TaskManager(Indexer(store, vectors))

    @asynccontextmanager
    async def lifespan(app):
        yield
        tasks.close()

    application = FastAPI(title="repoMap", version="0.1.0", lifespan=lifespan)
    application.state.store = store
    application.state.engine = engine

    @application.exception_handler(ValueError)
    async def invalid_request(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @application.get("/api/v1/health")
    def health():
        return {"status": "ok", "stage": "retrieval"}

    @application.get("/api/v1/repositories")
    def repositories():
        return catalog.list()

    @application.post("/api/v1/repositories")
    def import_repository(request: RepositoryImport):
        try:
            return catalog.import_repository(request.kind, request.source)
        except ImportErrorDetail as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/repositories/{repository_id}/index", status_code=202)
    def index(repository_id: str, request: IndexRequest):
        return tasks.submit(repository_id, request.exclusions)

    @application.get("/api/v1/tasks/{task_id}")
    def task(task_id: str):
        return tasks.get(task_id)

    @application.get("/api/v1/repositories/{repository_id}/snapshots")
    def snapshots(repository_id: str):
        return store.snapshots(repository_id)

    @application.post("/api/v1/search")
    def search(request: SearchRequest):
        return engine.search(**request.model_dump())

    @application.get("/api/v1/files")
    def file(repository_id: str, snapshot_id: str, path: str,
             start_line: int = Query(1, ge=1), end_line: int | None = Query(None, ge=1)):
        return explorer.file(repository_id, snapshot_id, path, start_line, end_line)

    @application.get("/api/v1/symbols")
    def symbols(repository_id: str, snapshot_id: str, path: str | None = None):
        return explorer.symbols(repository_id, snapshot_id, path)

    @application.get("/api/v1/definitions")
    def definitions(repository_id: str, snapshot_id: str, symbol_id: str | None = None,
                    path: str | None = None, line: int | None = Query(None, ge=1), column: int = Query(0, ge=0)):
        return explorer.definitions(repository_id, snapshot_id, symbol_id, path, line, column)

    @application.get("/api/v1/references")
    def references(repository_id: str, snapshot_id: str, symbol_id: str | None = None,
                   path: str | None = None, line: int | None = Query(None, ge=1), column: int = Query(0, ge=0)):
        return explorer.references(repository_id, snapshot_id, symbol_id, path, line, column)

    @application.get("/api/v1/graph")
    def graph(repository_id: str, snapshot_id: str, path: str | None = None,
              symbol_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
        return explorer.graph(repository_id, snapshot_id, path, symbol_id, limit)

    return application
