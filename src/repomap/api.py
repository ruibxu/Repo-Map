"""FastAPI application factory for local repository management."""

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from repomap.repositories import ImportErrorDetail, RepositoryCatalog


class RepositoryImport(BaseModel):
    kind: Literal["github", "local"]
    source: str = Field(min_length=1, max_length=4096)


def create_app(data_dir: Path | None = None) -> FastAPI:
    catalog = RepositoryCatalog(data_dir or Path(os.environ.get("REPOMAP_DATA_DIR", ".repomap")))
    application = FastAPI(title="repoMap", version="0.1.0")

    @application.get("/api/v1/health")
    def health():
        return {"status": "ok", "stage": "repository-import"}

    @application.get("/api/v1/repositories")
    def repositories():
        return catalog.list()

    @application.post("/api/v1/repositories")
    def import_repository(request: RepositoryImport):
        try:
            return catalog.import_repository(request.kind, request.source)
        except ImportErrorDetail as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return application
