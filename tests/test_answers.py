import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from repomap.answers import AnswerService


def test_no_key_mode_keeps_results(searchable, monkeypatch):
    _, repository, _, _, engine, snapshot = searchable
    monkeypatch.delenv("REPOMAP_LLM_BASE_URL", raising=False)
    result = AnswerService(engine).answer(repository["id"], snapshot, "login")
    assert result["status"] == "disabled"
    assert result["results"]
    assert result["citations"] == []


def test_cited_answer_and_unknown_citation_rejection(searchable, monkeypatch):
    _, repository, _, _, engine, snapshot = searchable
    monkeypatch.setenv("REPOMAP_LLM_BASE_URL", "https://llm.example.invalid/v1")
    monkeypatch.setenv("REPOMAP_LLM_MODEL", "test-model")

    def respond(request):
        payload = json.loads(request.content)
        evidence = json.loads(payload["messages"][1]["content"])["evidence"]
        assert len(evidence) <= 20
        id_ = evidence[0]["id"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"answer": f"Login is implemented here [{id_}].", "citations": [id_]})}}]})

    result = AnswerService(engine, httpx.MockTransport(respond)).answer(repository["id"], snapshot, "login")
    assert result["status"] == "answered"
    assert result["citations"][0]["path"] == "auth.py"
    assert result["context_tokens"] <= 5500
    invalid = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"Made up","citations":["unknown"]}'}}]}))
    result = AnswerService(engine, invalid).answer(repository["id"], snapshot, "login")
    assert result["status"] == "unavailable"
    assert result["results"]


def test_llm_http_failure_retains_retrieved_code(searchable, monkeypatch):
    _, repository, _, _, engine, snapshot = searchable
    monkeypatch.setenv("REPOMAP_LLM_BASE_URL", "https://llm.example.invalid/v1")
    monkeypatch.setenv("REPOMAP_LLM_MODEL", "test-model")
    result = AnswerService(engine, httpx.MockTransport(lambda _: httpx.Response(503))).answer(repository["id"], snapshot, "login")
    assert result["status"] == "unavailable"
    assert result["results"]


def test_local_chat_service_without_api_key_uses_real_http(searchable, monkeypatch):
    _, repository, _, _, engine, snapshot = searchable
    observed = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed["path"] = self.path
            observed["authorization"] = self.headers.get("Authorization")
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            evidence = json.loads(body["messages"][1]["content"])["evidence"]
            id_ = evidence[0]["id"]
            reply = json.dumps({"choices": [{"message": {"content": json.dumps({"answer": f"The retrieved definition is here [{id_}].", "citations": [id_]})}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("REPOMAP_LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("REPOMAP_LLM_MODEL", "local-test-service")
    monkeypatch.delenv("REPOMAP_LLM_API_KEY", raising=False)
    try:
        result = AnswerService(engine).answer(repository["id"], snapshot, "login")
        assert result["status"] == "answered"
        assert result["citations"][0]["path"] == "auth.py"
        assert observed == {"path": "/v1/chat/completions", "authorization": None}
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
