"""Test för matchserie-API:t (utan riktiga LLM-anrop).

Jobbet körs i en bakgrundstråd, så testet väntar tills det är klart och
kontrollerar sedan status, protokoll och nedladdning.
"""

from __future__ import annotations

import json
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


def test_series_can_run_without_llm(monkeypatch):
    """Utan språkmodell ska serien spelas med den mekaniska agentfabriken.

    Kvoten på fri nivå tar slut, och då måste appen gå att använda ändå.
    """
    client = _client(monkeypatch)
    calls = []
    real = match._new_agents_no_llm

    def counting(role_keys):
        calls.append(list(role_keys))
        return real(role_keys)

    monkeypatch.setattr(match, "_new_agents_no_llm", counting)
    start = client.post(
        "/api/matches/run", json={"count": 1, "check_in": False, "with_llm": False}
    )
    assert start.status_code == 200

    data = _wait_done(client)
    assert data["error"] is None
    assert data["done"] == 1
    assert calls, "den LLM-fria fabriken ska ha använts"
    assert data["summary"]["games"] == 1


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
    assert data["file"].endswith(".jsonl") and data["file"][0].isdigit()
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
    client = _client(monkeypatch)
    log_dir = tmp_path / "bestandig"
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(log_dir))

    client.post("/api/matches/run", json={"count": 1})
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
    client = _client(monkeypatch)
    log_dir = tmp_path / "serier"
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(log_dir))

    client.post("/api/matches/run", json={"count": 1})
    first = _wait_done(client)["file"]
    time.sleep(1.1)  # filnamnet har sekundupplösning
    client.post("/api/matches/run", json={"count": 1})
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


def test_check_in_runs_even_when_client_says_no(monkeypatch, tmp_path):
    """Klienten kan inte längre välja bort incheckningen.

    Kryssrutan är borta ur gränssnittet. En gammal klient som skickar
    check_in=False ska ändå få serien incheckad, annars finns två beteenden
    kvar och den lokala filen blir återigen något man kan råka välja.
    """
    clone = tmp_path / "clone"
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    monkeypatch.setenv("MEIER_LOGS_DIR", str(clone))
    monkeypatch.setenv("MEIER_LOGS_REMOTE_URL", str(origin))
    monkeypatch.setenv("MEIER_LOGS_TOKEN_FILE", str(tmp_path / "token"))
    (tmp_path / "token").write_text("dummy\n", encoding="utf-8")
    client = _client(monkeypatch)
    monkeypatch.setenv("MEIER_LOGS_PUSH", "1")

    client.post("/api/matches/run", json={"count": 1, "check_in": False})
    data = _wait_done(client)

    assert data["error"] is None
    # Filen hamnade i klonen, inte i den lokala katalogen.
    assert (clone / data["file"]).exists()
    assert "Incheckat" in data["push_status"]


def test_status_works_after_restart_from_pointer_file(monkeypatch, tmp_path):
    """Efter omstart ska status läsas tillbaka från filen, inte ge 404.

    Servern tappar jobbet i minnet vid omstart. Filen ligger kvar i /workspace.
    Utan pekfil svarade status 404 och serien såg förlorad ut.
    """
    client = _client(monkeypatch)
    log_dir = tmp_path / "serier"
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(log_dir))

    client.post("/api/matches/run", json={"count": 2})
    done = _wait_done(client)
    name = done["file"]

    # Simulera omstart: jobbet i minnet är borta, pekfilen ligger kvar.
    monkeypatch.setattr(web_app, "_match_job", None)
    monkeypatch.setattr(web_app, "_restored", False)

    res = client.get("/api/matches/status")
    assert res.status_code == 200
    data = res.json()
    assert data["running"] is False
    assert data["restored"] is True
    assert data["file"] == name
    assert data["games"] == 2
    assert data["count"] == 2
    assert len(data["records"]) == 2


def test_pointer_file_lets_download_work_after_restart(monkeypatch, tmp_path):
    """Nedladdning och sammanfattning ska också fungera efter omstart."""
    client = _client(monkeypatch)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "serier"))

    client.post("/api/matches/run", json={"count": 1})
    done = _wait_done(client)

    monkeypatch.setattr(web_app, "_match_job", None)
    monkeypatch.setattr(web_app, "_restored", False)

    dl = client.get("/api/matches/download")
    assert dl.status_code == 200
    assert dl.content.strip()
    summary = client.get("/api/matches/summary")
    assert summary.status_code == 200
    assert summary.json()["games"] == 1
    assert done["file"] in dl.headers.get("content-disposition", "")


def test_analysis_lists_local_series(monkeypatch, tmp_path):
    """Analys-fliken ska visa lokala serier, inte bara incheckade.

    En serie som spelats utan fungerande fjärr ska gå att analysera. Tidigare
    listades bara loggre pets filer, så lokala serier var osynliga.
    """
    client = _client(monkeypatch)
    log_dir = tmp_path / "serier"
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(log_dir))

    client.post("/api/matches/run", json={"count": 1})
    done = _wait_done(client)

    res = client.get("/api/analysis/logs")
    assert res.status_code == 200
    data = res.json()
    names = [e["name"] for e in data["logs"]]
    assert done["file"] in names
    entry = next(e for e in data["logs"] if e["name"] == done["file"])
    assert entry["local"] is True
    assert entry["games"] == 1


def test_analysis_can_load_local_series(monkeypatch, tmp_path):
    """En lokal serie ska gå att läsa in i analysen och räknas."""
    client = _client(monkeypatch)
    log_dir = tmp_path / "serier"
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(log_dir))

    client.post("/api/matches/run", json={"count": 2})
    done = _wait_done(client)

    res = client.post("/api/analysis/select", json={"names": [done["file"]]})
    assert res.status_code == 200
    assert res.json()["games"] == 2

    data = client.get("/api/analysis/data").json()
    assert data["games"] == 2


def test_status_reports_start_and_finish_time(monkeypatch, tmp_path):
    """Serien ska tala om när den startade och när den blev klar."""
    client = _client(monkeypatch)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "serier"))

    start = time.time()
    client.post("/api/matches/run", json={"count": 2})
    data = _wait_done(client)

    assert isinstance(data["started_at"], (int, float))
    assert isinstance(data["finished_at"], (int, float))
    assert data["started_at"] <= data["finished_at"]
    assert data["finished_at"] >= start
    # Ingen match pågår när serien är klar.
    assert data["live"] == []


def test_status_reports_live_round_while_running(monkeypatch, tmp_path):
    """Medan en match spelas ska statusraden visa runda och antal kvar."""
    client = _client(monkeypatch)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "serier"))

    seen_live: list[dict] = []
    real_play = match.play_match

    def slow_play(*args, on_progress=None, **kwargs):
        if on_progress is not None:
            on_progress(1, 2)
        time.sleep(0.3)
        return real_play(*args, on_progress=on_progress, **kwargs)

    monkeypatch.setattr(match, "play_match", slow_play)

    client.post("/api/matches/run", json={"count": 1})
    deadline = time.time() + 5
    while time.time() < deadline:
        data = client.get("/api/matches/status").json()
        if data.get("live"):
            seen_live = data["live"]
            break
        time.sleep(0.05)
    _wait_done(client)

    assert seen_live, "status ska visa pågående match med runda"
    assert seen_live[0]["game"] == 1
    assert seen_live[0]["round"] >= 1
    assert seen_live[0]["alive"] >= 1


def test_restored_status_keeps_the_times(monkeypatch, tmp_path):
    """Efter omstart ska start- och sluttid läsas tillbaka ur pekfilen."""
    client = _client(monkeypatch)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "serier"))

    client.post("/api/matches/run", json={"count": 1})
    done = _wait_done(client)

    monkeypatch.setattr(web_app, "_match_job", None)
    monkeypatch.setattr(web_app, "_restored", False)

    data = client.get("/api/matches/status").json()
    assert data["restored"] is True
    assert data["started_at"] == done["started_at"]
    assert data["finished_at"] == done["finished_at"]


def test_series_file_name_is_a_bare_timestamp(monkeypatch, tmp_path):
    """Nya seriefiler heter bara datum och tid, utan prefix."""
    client = _client(monkeypatch)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "serier"))

    client.post("/api/matches/run", json={"count": 1})
    data = _wait_done(client)

    name = data["file"]
    assert name.endswith(".jsonl")
    assert not name.startswith("meier-matcher-")
    # ÅÅÅÅ-MM-DD-TTMMSS
    assert len(name) == len("2026-11-25-202542.jsonl")
    assert name[4] == "-" and name[7] == "-" and name[10] == "-"


def test_records_are_listed_in_match_order(monkeypatch, tmp_path):
    """Matcherna spelas parallellt men ska listas i matchnummer."""
    client = _client(monkeypatch)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "serier"))

    client.post("/api/matches/run", json={"count": 4, "workers": 4})
    data = _wait_done(client)

    games = [rec["game"] for rec in data["records"]]
    assert games == sorted(games) == [1, 2, 3, 4]


def test_restored_records_are_sorted(monkeypatch, tmp_path):
    """Efter omstart ska filens matcher listas i matchnummer, inte i skrivordning."""
    log_dir = tmp_path / "serier"
    client = _client(monkeypatch)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(log_dir))

    client.post("/api/matches/run", json={"count": 3, "workers": 3})
    done = _wait_done(client)
    path = log_dir / done["file"]
    assert path.is_file()

    # Skriv om filen i "fel" ordning, som en parallell serie kan hamna på disk.
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    with path.open("w", encoding="utf-8") as fh:
        for rec in reversed(rows):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    monkeypatch.setattr(web_app, "_match_job", None)
    monkeypatch.setattr(web_app, "_restored", False)

    data = client.get("/api/matches/status").json()
    assert [r["game"] for r in data["records"]] == [1, 2, 3]
