import json

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
