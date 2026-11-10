"""Tester för analysmodulen och analys-API:t (utan riktiga LLM-anrop)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from mejer import analysis, match
from mejer.web import app as web_app
from tests.test_match import make_agents


def _records(n: int = 3) -> list[dict]:
    match._new_agents = make_agents
    return [match.play_match(["a", "b"], seed=s, game=s + 1).to_dict() for s in range(n)]


# -- analysis.py ------------------------------------------------------------


def test_parse_jsonl_skips_invalid_lines():
    rec = _records(1)[0]
    text = json.dumps(rec) + "\n" + "inte json\n" + json.dumps({"foo": 1}) + "\n"
    records, skipped = analysis.parse_jsonl_text(text)
    assert len(records) == 1
    assert skipped == 2


def test_build_digest_has_expected_keys():
    digest = analysis.build_digest(_records(3))
    assert digest["games"] == 3
    for key in ("roles", "actions", "bids", "outcomes", "call_outcomes"):
        assert key in digest
    assert isinstance(digest["games_series"], list)


def test_digest_text_mentions_roles():
    digest = analysis.build_digest(_records(2))
    text = analysis.render_digest_text(digest)
    assert "Antal matcher: 2" in text
    assert "PER ROLL" in text


def test_store_accumulates_and_clears():
    store = analysis.AnalysisStore()
    rec = json.dumps(_records(1)[0])
    assert store.add_text("a.jsonl", rec + "\n") == 1
    assert store.add_text("b.jsonl", rec + "\n") == 1
    info = store.info()
    assert info["games"] == 2
    assert info["sources"] == ["a.jsonl", "b.jsonl"]
    store.clear()
    assert store.info()["games"] == 0


class _StubLLM:
    last_usage = {"total_tokens": 7}

    def __init__(self, payload: str):
        self.payload = payload
        self.last_user = ""

    def complete(self, system, user, *, json_mode=False):
        self.last_user = user
        return self.payload


def test_ask_parses_answer_and_chart():
    digest = analysis.build_digest(_records(2))
    payload = json.dumps(
        {
            "answer": "Svar",
            "chart": {"type": "bar", "labels": ["a"], "values": [1]},
            "followups": ["F1", "F2"],
        }
    )
    result = analysis.ask(digest, "Vem bluffar mest?", client=_StubLLM(payload))
    assert result["answer"] == "Svar"
    assert result["chart"]["type"] == "bar"
    assert result["followups"] == ["F1", "F2"]


def test_ask_filters_bad_chart_and_non_json():
    digest = analysis.build_digest(_records(1))
    bad = json.dumps({"answer": "x", "chart": {"type": "pie"}, "followups": "nej"})
    result = analysis.ask(digest, "?", client=_StubLLM(bad))
    assert result["chart"] is None
    assert result["followups"] == []

    raw = analysis.ask(digest, "?", client=_StubLLM("inte json alls"))
    assert raw["answer"] == "inte json alls"
    assert raw["chart"] is None


def test_ask_rejects_empty_question():
    import pytest

    digest = analysis.build_digest(_records(1))
    with pytest.raises(ValueError):
        analysis.ask(digest, "   ", client=_StubLLM("{}"))


# -- Web-API ----------------------------------------------------------------


def test_analysis_upload_and_data(monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    client = TestClient(web_app.app)
    web_app._store.clear()

    rec = json.dumps(_records(2)[0]) + "\n"
    res = client.post(
        "/api/analysis/upload",
        files=[("files", ("min.jsonl", rec, "application/x-ndjson"))],
    )
    assert res.status_code == 200
    assert res.json()["games"] == 1

    data = client.get("/api/analysis/data").json()
    assert data["games"] == 1
    assert "min.jsonl" in data["sources"]
    assert data["digest_text"]

    assert client.post("/api/analysis/clear").json()["games"] == 0


def test_analysis_upload_rejects_garbage(monkeypatch):
    client = TestClient(web_app.app)
    web_app._store.clear()
    res = client.post(
        "/api/analysis/upload",
        files=[("files", ("skrap.txt", "ingen data här\n", "text/plain"))],
    )
    assert res.status_code == 400


def test_analysis_ask_requires_data(monkeypatch):
    client = TestClient(web_app.app)
    web_app._store.clear()
    res = client.post("/api/analysis/ask", json={"question": "Hej?"})
    assert res.status_code == 400


def test_analysis_ask_uses_llm(monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    client = TestClient(web_app.app)
    web_app._store.clear()
    web_app._store.add_text("x.jsonl", json.dumps(_records(1)[0]) + "\n")

    payload = json.dumps({"answer": "42", "chart": None, "followups": []})
    monkeypatch.setattr(analysis, "_client", lambda: _StubLLM(payload))

    res = client.post("/api/analysis/ask", json={"question": "Vem vinner?"})
    assert res.status_code == 200
    assert res.json()["answer"] == "42"


def test_analysis_export_roundtrip(monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    client = TestClient(web_app.app)
    web_app._store.clear()
    rec = json.dumps(_records(1)[0]) + "\n"
    client.post("/api/analysis/upload", files=[("files", ("a.jsonl", rec, "text/plain"))])
    export = client.get("/api/analysis/export")
    assert export.status_code == 200
    assert export.text.strip()
    # Det exporterade materialet går att läsa in igen.
    again = client.post(
        "/api/analysis/upload",
        files=[("files", ("b.jsonl", export.text, "text/plain"))],
    )
    assert again.status_code == 200
    assert client.get("/api/analysis/data").json()["games"] == 2
    web_app._store.clear()
