"""Test för matchserie-API:t (utan riktiga LLM-anrop).

Jobbet körs i en bakgrundstråd, så testet väntar tills det är klart och
kontrollerar sedan status, protokoll och nedladdning.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from meier import match
from meier.web import app as web_app
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


def test_parallel_workers_series(monkeypatch):
    client = _client(monkeypatch)
    start = client.post("/api/matches/run", json={"count": 3, "base_seed": 5, "workers": 3})
    assert start.status_code == 200

    data = _wait_done(client)
    assert data["error"] is None
    assert data["done"] == 3
    assert sorted(r["seed"] for r in data["records"]) == [5, 6, 7]


def test_second_series_while_running_conflicts(monkeypatch):
    # Långsam agent så att den första serien hinner vara igång.
    def slow_agents(role_keys):
        agents = make_agents(role_keys)
        for a in agents:
            original = a.llm.complete

            def complete(system, user, *, json_mode=False, _o=original):
                time.sleep(0.1)
                return _o(system, user, json_mode=json_mode)

            a.llm.complete = complete
        return agents

    monkeypatch.setattr(match, "_new_agents", slow_agents)
    client = TestClient(web_app.app)
    assert client.post("/api/matches/run", json={"count": 1}).status_code == 200
    second = client.post("/api/matches/run", json={"count": 1})
    assert second.status_code == 409
    _wait_done(client, timeout=30.0)

def _git(*args, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


def test_check_in_writes_file_to_log_repo(monkeypatch, tmp_path):
    """Med check_in skrivs loggen i loggrepet och checkas in där."""
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-q", str(remote))
    token = tmp_path / "token"
    token.write_text("dummy\n", encoding="utf-8")
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "clone"))
    monkeypatch.setenv("MEIER_LOGS_REMOTE_URL", str(remote))
    monkeypatch.setenv("MEIER_LOGS_TOKEN_FILE", str(token))

    client = _client(monkeypatch)
    client.post("/api/matches/run", json={"count": 2, "base_seed": 1, "check_in": True})
    data = _wait_done(client)

    assert data["error"] is None
    assert data["done"] == 2
    assert data["push_status"] and "pushat" in data["push_status"].lower()
    # Filnamnet har datum och klockslag.
    assert data["file"].startswith("meier-matcher-") and data["file"].endswith(".jsonl")
    # Filen finns i fjärren med båda matcherna.
    names = _git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "HEAD").stdout
    assert data["file"] in names
    log = _git("--git-dir", str(remote), "log", "--oneline", "HEAD").stdout
    assert log.count("Meier: match") == 2


def test_logrepo_endpoint_reports_ready(monkeypatch, tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-q", str(remote))
    token = tmp_path / "token"
    token.write_text("dummy\n", encoding="utf-8")
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "clone"))
    monkeypatch.setenv("MEIER_LOGS_REMOTE_URL", str(remote))
    monkeypatch.setenv("MEIER_LOGS_TOKEN_FILE", str(token))
    client = _client(monkeypatch)
    # Före första körningen är klonen inte gjord – inte redo.
    assert client.get("/api/matches/logrepo").json()["ready"] is False
    client.post("/api/matches/run", json={"count": 1, "check_in": True})
    _wait_done(client)
    assert client.get("/api/matches/logrepo").json()["ready"] is True
