"""Test för matchserie-API:t (utan riktiga LLM-anrop).

Jobbet körs i en bakgrundstråd, så testet väntar tills det är klart och
kontrollerar sedan status, protokoll och nedladdning.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from meier import match
from meier.web import app as web_app
from tests.test_match import make_agents


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(match, "_new_agents", make_agents)
    # Lokala serier ska inte hamna i den riktiga loggkatalogen under test, och
    # incheckning ska vara av så att tester aldrig rör det riktiga loggrepet.
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", tempfile.mkdtemp(prefix="meier-test-"))
    monkeypatch.setenv("MEIER_LOGS_PUSH", "0")
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
    start = client.post("/api/matches/run", json={"count": 2, "check_in": False})
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
    client.post("/api/matches/run", json={"count": 1, "check_in": False})
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
    start = client.post("/api/matches/run", json={"count": 3, "workers": 3})
    assert start.status_code == 200

    data = _wait_done(client)
    assert data["error"] is None
    assert data["done"] == 3
    assert sorted(r["game"] for r in data["records"]) == [1, 2, 3]


def test_a_failing_match_does_not_stop_the_web_series(monkeypatch):
    """En kraschad match i webbappen ska bara kosta den matchen.

    Förut dog hela serien: ett LLM-fel satte ``error`` och ``running`` till
    False, och de matcher som redan spelats syntes aldrig i sammanfattningen.
    """
    from meier.llm import LLMError

    def flaky_agents(role_keys):
        agents = make_agents(role_keys)
        counter = {"n": 0}
        for a in agents:
            original = a.llm.complete

            def complete(system, user, *, json_mode=False, _o=original):
                counter["n"] += 1
                if counter["n"] == 3:
                    raise LLMError("överbelastad (503)")
                return _o(system, user, json_mode=json_mode)

            a.llm.complete = complete
        return agents

    monkeypatch.setattr(match, "_new_agents", flaky_agents)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", tempfile.mkdtemp(prefix="meier-test-"))
    client = TestClient(web_app.app)
    client.post("/api/matches/run", json={"count": 2, "check_in": False})
    data = _wait_done(client)

    # Serien gick vidare och matcherna efter felet spelades.
    assert data["done"] == 2
    assert data["games"] + len(data["failures"]) == 2
    assert data["failures"], "bortfallet ska rapporteras, inte tystas"
    for f in data["failures"]:
        assert f["failed"] is True
        assert f["error"] and f["kind"]
    # Sammanfattningen räknar bara de spelade matcherna men redovisar bortfallet.
    summary = data["summary"]
    assert summary["attempted"] == 2
    assert summary["games"] == 2 - summary["failed"]["count"]
    assert summary["failed"]["count"] == len(data["failures"])


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
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", tempfile.mkdtemp(prefix="meier-test-"))
    client = TestClient(web_app.app)
    run = {"count": 1, "check_in": False}
    assert client.post("/api/matches/run", json=run).status_code == 200
    second = client.post("/api/matches/run", json=run)
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
    # Dessa tester prövar incheckningen och behöver push påslagen. Sätts efter
    # _client, som annars stänger av den.
    monkeypatch.setenv("MEIER_LOGS_PUSH", "1")
    client.post("/api/matches/run", json={"count": 2, "check_in": True})
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
    # Detta test prövar incheckningen och behöver push påslagen. Sätts efter
    # _client, som annars stänger av den.
    monkeypatch.setenv("MEIER_LOGS_PUSH", "1")
    # Före första körningen är klonen inte gjord – inte redo.
    assert client.get("/api/matches/logrepo").json()["ready"] is False
    client.post("/api/matches/run", json={"count": 1, "check_in": True})
    _wait_done(client)
    assert client.get("/api/matches/logrepo").json()["ready"] is True


def test_local_series_is_written_outside_tmp(monkeypatch, tmp_path):
    """En lokal serie får aldrig hamna i /tmp.

    Containern startar om efter 20 minuters inaktivitet och nollställer /tmp.
    En serie som bara låg där försvann, och felet syntes först när sidan sökte
    status ("Failed to fetch"). Filen ska ligga i den beständiga katalogen.
    """
    log_dir = tmp_path / "bestandig"
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(log_dir))
    monkeypatch.setattr(match, "_new_agents", make_agents)
    client = TestClient(web_app.app)

    client.post("/api/matches/run", json={"count": 1, "check_in": False})
    data = _wait_done(client)

    assert data["error"] is None
    path = log_dir / data["file"]
    assert path.exists(), f"seriefilen skrevs inte till {path}"
    assert path.read_text(encoding="utf-8").strip()


def test_default_log_dir_is_persistent(monkeypatch):
    """Utan konfiguration ska serien hamna i /workspace, inte i /tmp.

    /tmp nollställs vid omstart, /workspace ligger kvar.
    """
    monkeypatch.delenv("MEIER_LOCAL_LOG_DIR", raising=False)
    monkeypatch.delenv("MEIER_LOGS_DIR", raising=False)

    default = web_app._local_log_dir()
    assert str(default).startswith("/workspace/"), default
    assert not str(default).startswith("/tmp/")


def test_two_local_series_do_not_overwrite_each_other(monkeypatch, tmp_path):
    """Två lokala serier ska bli två filer, inte en som skrivs över."""
    log_dir = tmp_path / "serier"
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(log_dir))
    monkeypatch.setattr(match, "_new_agents", make_agents)
    client = TestClient(web_app.app)

    client.post("/api/matches/run", json={"count": 1, "check_in": False})
    first = _wait_done(client)["file"]
    time.sleep(1.1)  # filnamnet har sekundupplösning
    client.post("/api/matches/run", json={"count": 1, "check_in": False})
    second = _wait_done(client)["file"]

    assert first != second
    assert (log_dir / first).exists()
    assert (log_dir / second).exists()


def test_push_disabled_really_disables_check_in(monkeypatch, tmp_path):
    """MEIER_LOGS_PUSH=0 ska stänga av incheckningen på riktigt.

    Flaggan styrde tidigare bara kryssrutan i gränssnittet. En körning med
    check_in=True skrev ändå till loggrepet och committade där.
    """
    log_dir = tmp_path / "lokalt"
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(log_dir))
    monkeypatch.setenv("MEIER_LOGS_PUSH", "0")
    monkeypatch.setattr(match, "_new_agents", make_agents)
    client = TestClient(web_app.app)

    client.post("/api/matches/run", json={"count": 1, "check_in": True})
    data = _wait_done(client)

    assert data["error"] is None
    assert data["push_status"] == "Incheckning avstängd (MEIER_LOGS_PUSH=0)."
    # Serien skrevs lokalt i stället, och inget hamnade i loggrepet.
    assert (log_dir / data["file"]).exists()


def test_unreachable_remote_falls_back_to_local_with_message(monkeypatch, tmp_path):
    """Går loggrepet inte att nå ska serien sparas lokalt och säga var.

    Annars ser ett trasigt loggrepo ut som en förlorad serie, fast filen
    ligger kvar på disk.
    """
    local = tmp_path / "lokalt"
    remote = tmp_path / "finns-inte.git"  # aldrig skapad → kloning misslyckas
    token = tmp_path / "token"
    token.write_text("dummy\n", encoding="utf-8")
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "clone"))
    monkeypatch.setenv("MEIER_LOGS_REMOTE_URL", str(remote))
    monkeypatch.setenv("MEIER_LOGS_TOKEN_FILE", str(token))
    client = _client(monkeypatch)
    # Sätts efter _client, som annars pekar om katalogen och stänger av push.
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(local))
    monkeypatch.setenv("MEIER_LOGS_PUSH", "1")

    client.post("/api/matches/run", json={"count": 1, "check_in": True})
    data = _wait_done(client)

    assert data["error"] is None
    assert "Serien sparas lokalt i" in data["push_status"]
    assert str(local) in data["push_status"]
    assert (local / data["file"]).exists()


def test_check_in_is_on_by_default():
    """Incheckning ska vara på som standard, så serien bevaras.

    Standardvärdet var tidigare av, och då kunde en hel serie försvinna utan
    att något gick att göra åt saken i efterhand.
    """
    from meier.web.app import MatchRequest

    assert MatchRequest().check_in is True
