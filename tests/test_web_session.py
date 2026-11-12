"""Test för sessions-API:t, inklusive knappen "Hela matchen" (utan LLM-anrop)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from meier.agents.base import Role
from meier.agents.player import MeierPlayerAgent
from meier.web import app as web_app
from tests.test_session import ScriptedLLM


def _agent(key: str) -> MeierPlayerAgent:
    role = Role(key=key, name=f"Spelare-{key}", description="test", style="spela")
    return MeierPlayerAgent(role=role, llm=ScriptedLLM(bids=[11], actions=["syna"]))


def _client(monkeypatch) -> TestClient:
    web_app._session = None
    monkeypatch.setattr(web_app, "_get_agent", _agent)
    return TestClient(web_app.app)


def test_session_end_plays_whole_match(monkeypatch):
    client = _client(monkeypatch)
    start = client.post("/api/session/new", json={"seed": 11})
    assert start.status_code == 200
    assert start.json()["phase"] == "awaiting_ok"

    res = client.post("/api/session/end")
    assert res.status_code == 200
    data = res.json()
    assert data["phase"] == "finished"
    # En vinnare står kvar, och loggen innehåller minst en syn.
    assert len([p for p in data["order"] if p["lives"] > 0]) == 1
    assert any(e.get("action") == "syna" for e in data["log"])


def test_session_end_without_session_is_404(monkeypatch):
    client = _client(monkeypatch)
    res = client.post("/api/session/end")
    assert res.status_code == 404
