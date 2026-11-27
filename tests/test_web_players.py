"""Test för valet av vilka spelare som är med (fliken Spelarna).

Valet ligger i processminnet och gäller hela appen: sessioner, enskilda anrop
och matchserier. Testerna nollställer det efter sig.
"""

from __future__ import annotations

import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from meier import match
from meier.agents.base import Role
from meier.agents.player import MeierPlayerAgent
from meier.agents.roster import role_keys
from meier.web import app as web_app
from tests.test_match import make_agents
from tests.test_session import ScriptedLLM


@pytest.fixture(autouse=True)
def _reset_active():
    yield
    web_app._active.set(role_keys())


def _client() -> TestClient:
    return TestClient(web_app.app)


def _agent(key: str) -> MeierPlayerAgent:
    role = Role(key=key, name=f"Spelare-{key}", description="test", style="spela")
    return MeierPlayerAgent(role=role, llm=ScriptedLLM(claims=[11], actions=["syna"]))


def _wait_done(client: TestClient, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get("/api/matches/status").json()
        if not data["running"]:
            return data
        time.sleep(0.05)
    raise AssertionError("matchserien blev inte klar i tid")


def test_all_five_are_active_by_default():
    data = _client().get("/api/players").json()
    assert data["active"] == role_keys()
    assert data["all"] == role_keys()
    assert data["min"] == 2


def test_choose_two_players_keeps_roster_order():
    client = _client()
    res = client.put("/api/players", json={"roles": ["cecilia", "axel"]})
    assert res.status_code == 200
    assert res.json()["active"] == ["axel", "cecilia"]
    assert client.get("/api/players").json()["active"] == ["axel", "cecilia"]


def test_roles_endpoint_marks_active_players():
    client = _client()
    client.put("/api/players", json={"roles": ["axel", "berit"]})
    roles = {r["key"]: r["active"] for r in client.get("/api/roles").json()["roles"]}
    assert roles == {
        "axel": True,
        "berit": True,
        "cecilia": False,
        "david": False,
        "elsa": False,
    }


def test_unknown_player_is_rejected():
    client = _client()
    res = client.put("/api/players", json={"roles": ["axel", "nils"]})
    assert res.status_code == 400
    assert "nils" in res.json()["detail"]
    assert client.get("/api/players").json()["active"] == role_keys()


def test_single_player_is_rejected():
    client = _client()
    res = client.put("/api/players", json={"roles": ["axel"]})
    assert res.status_code == 400
    assert "Minst två" in res.json()["detail"]


def test_session_uses_the_active_players(monkeypatch):
    web_app._session = None
    monkeypatch.setattr(web_app, "_get_agent", _agent)
    client = _client()
    client.put("/api/players", json={"roles": ["axel", "berit"]})
    data = client.post("/api/session/new", json={}).json()
    assert sorted(p["role"] for p in data["order"]) == ["axel", "berit"]


def test_series_uses_the_active_players(monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", tempfile.mkdtemp(prefix="meier-test-"))
    client = _client()
    client.put("/api/players", json={"roles": ["axel", "david"]})
    start = client.post(
        "/api/matches/run",
        json={"count": 1, "check_in": False, "with_llm": False},
    )
    assert start.status_code == 200
    data = _wait_done(client)
    assert data["error"] is None
    assert len(data["records"][0]["players"]) == 2
