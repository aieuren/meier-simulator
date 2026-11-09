"""Test för matchserie-API:t (utan riktiga LLM-anrop).

Jobbet körs i en bakgrundstråd, så testet väntar tills det är klart och
kontrollerar sedan status, protokoll och nedladdning.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from mejer import match
from mejer.web import app as web_app
from tests.test_match import make_agents


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(match, "_new_agents", make_agents)
    return TestClient(web_app.app)


def _wait_done(client: TestClient, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get("/api/matches/status").json()
        if not data["running"]:
            return data
        time.sleep(0.05)
    raise AssertionError("matchserien blev inte klar i tid")


def test_run_series_and_fetch_status(monkeypatch):
    client = _client(monkeypatch)
    start = client.post("/api/matches/run", json={"count": 2, "base_seed": 1})
    assert start.status_code == 200
    assert start.json()["running"] is True

    data = _wait_done(client)
    assert data["error"] is None
    assert data["done"] == 2
    assert data["count"] == 2
    assert len(data["records"]) == 2
    assert data["summary"]["games"] == 2
    # Varje match är ett komplett protokoll.
    rec = data["records"][0]
    assert rec["winner"] and rec["events"] and rec["player_stats"]


def test_summary_and_download_after_run(monkeypatch):
    client = _client(monkeypatch)
    client.post("/api/matches/run", json={"count": 1})
    _wait_done(client)

    summary = client.get("/api/matches/summary")
    assert summary.status_code == 200
    assert summary.json()["games"] == 1

    dl = client.get("/api/matches/download")
    assert dl.status_code == 200
    assert dl.text.strip()  # minst en JSON-rad


def test_unknown_role_is_rejected(monkeypatch):
    client = _client(monkeypatch)
    res = client.post("/api/matches/run", json={"count": 1, "roles": ["finns-inte"]})
    assert res.status_code == 400
