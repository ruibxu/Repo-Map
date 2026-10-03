import time

from fastapi.testclient import TestClient

from test_retrieval import TestEncoder
from repomap.api import create_app


def test_async_index_poll_search_and_explore(indexed_repo, tmp_path):
    root, _, _ = indexed_repo
    with TestClient(create_app(tmp_path / "api-data", TestEncoder())) as client:
        repository = client.post("/api/v1/repositories", json={"kind": "local", "source": str(root)}).json()
        response = client.post(f"/api/v1/repositories/{repository['id']}/index", json={})
        assert response.status_code == 202
        task = response.json()
        deadline = time.monotonic() + 30
        while task["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(.05)
            task = client.get(f"/api/v1/tasks/{task['id']}").json()
        assert task["status"] == "completed", task
        snapshot = task["snapshot_id"]
        context = {"repository_id": repository["id"], "snapshot_id": snapshot}
        result = client.post("/api/v1/search", json={**context, "query": "login"}).json()
        assert result["results"]
        symbol_id = result["results"][0]["symbol_id"]
        assert client.get("/api/v1/definitions", params={**context, "symbol_id": symbol_id}).json()["status"] == "resolved"
        assert client.get("/api/v1/references", params={**context, "symbol_id": symbol_id}).status_code == 200
        assert client.get("/api/v1/graph", params={**context, "path": "auth.py"}).json()["nodes"]
        assert client.get("/api/v1/files", params={**context, "path": "../outside"}).status_code == 400
