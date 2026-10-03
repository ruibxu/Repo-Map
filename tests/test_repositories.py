import subprocess

import pytest
from fastapi.testclient import TestClient

from repomap.api import create_app
from repomap.repositories import ImportErrorDetail, RepositoryCatalog


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / "example.py").write_text("def hello():\n    return 'hello'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"], check=True, capture_output=True)
    return root


def test_local_import_is_persistent_and_idempotent(tmp_path, repository):
    catalog = RepositoryCatalog(tmp_path / "data")
    first = catalog.import_repository("local", str(repository))
    assert len(first["commit_sha"]) == 40
    assert catalog.import_repository("local", str(repository))["id"] == first["id"]
    assert RepositoryCatalog(tmp_path / "data").list() == [first]
    assert (repository / "example.py").read_text().startswith("def hello")


@pytest.mark.parametrize("source", ["https://user:token@github.com/a/b", "https://example.com/a/b", "https://github.com/a/b?token=x", "https://github.com/../b", "--help"])
def test_rejects_invalid_remote_before_git(tmp_path, source):
    with pytest.raises(ImportErrorDetail):
        RepositoryCatalog(tmp_path).import_repository("github", source)


def test_rejects_nested_local_directory(tmp_path, repository):
    nested = repository / "nested"
    nested.mkdir()
    with pytest.raises(ImportErrorDetail, match="root"):
        RepositoryCatalog(tmp_path / "data").import_repository("local", str(nested))


def test_api_import_and_validation(tmp_path, repository):
    with TestClient(create_app(tmp_path / "data")) as client:
        assert client.get("/api/v1/health").status_code == 200
        response = client.post("/api/v1/repositories", json={"kind": "local", "source": str(repository)})
        assert response.status_code == 200
        assert client.get("/api/v1/repositories").json() == [response.json()]
        assert client.post("/api/v1/repositories", json={"kind": "invalid", "source": "x"}).status_code == 422
        assert client.post("/api/v1/repositories", json={"kind": "local", "source": str(tmp_path / "missing")}).status_code == 400


def test_github_import_pins_commit_and_normalizes_url(tmp_path, monkeypatch):
    calls = []
    commit = "a" * 40

    def fake_git(*args, **kwargs):
        calls.append(args)
        return commit if "rev-parse" in args else ""

    monkeypatch.setattr("repomap.repositories.git", fake_git)
    catalog = RepositoryCatalog(tmp_path / "data")
    result = catalog.import_repository("github", "https://github.com/example/project")
    assert result["source"] == "https://github.com/example/project.git"
    assert result["commit_sha"] == commit
    assert calls[-1][-3:] == ("checkout", "--detach", commit)
    assert catalog.import_repository("github", result["source"])["id"] == result["id"]
    assert len(calls) == 3


def test_failed_clone_does_not_publish_repository(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise ImportErrorDetail("Repository not found.")

    monkeypatch.setattr("repomap.repositories.git", fail)
    catalog = RepositoryCatalog(tmp_path / "data")
    with pytest.raises(ImportErrorDetail):
        catalog.import_repository("github", "https://github.com/example/missing")
    assert catalog.list() == []
