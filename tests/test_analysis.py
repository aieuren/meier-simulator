"""Tester för analysmodulen och analys-API:t (utan riktiga LLM-anrop)."""

from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from meier import analysis, match
from meier.web import app as web_app
from tests.test_match import make_agents


def _records(n: int = 3) -> list[dict]:
    match._new_agents = make_agents
    return [match.play_match(["a", "b"], game=g + 1).to_dict() for g in range(n)]


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
    for key in ("roles", "actions", "claims", "outcomes", "call_outcomes"):
        assert key in digest
    assert isinstance(digest["games_series"], list)


def test_digest_text_mentions_roles():
    digest = analysis.build_digest(_records(2))
    text = analysis.render_digest_text(digest)
    assert "Antal matcher: 2" in text
    assert "PER ROLL" in text
    assert "VAD SAMMANSTÄLLNINGEN INTE INNEHÅLLER" in text
    assert digest["events_total"] > 0


def test_store_accumulates_and_removes():
    store = analysis.AnalysisStore()
    rec = json.dumps(_records(1)[0])
    assert store.add_text("a.jsonl", rec + "\n") == 1
    assert store.add_text("b.jsonl", rec + "\n") == 1
    info = store.info()
    assert info["games"] == 2
    assert info["sources"] == ["a.jsonl", "b.jsonl"]
    assert store.remove("a.jsonl") is True
    assert store.remove("a.jsonl") is False
    assert store.info()["sources"] == ["b.jsonl"]
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
            "cannot_answer": "Enskilda tärningsslag saknas.",
        }
    )
    result = analysis.ask(digest, "Vem bluffar mest?", client=_StubLLM(payload))
    assert result["answer"] == "Svar"
    assert result["chart"]["type"] == "bar"
    assert result["followups"] == ["F1", "F2"]
    assert result["cannot_answer"] == "Enskilda tärningsslag saknas."


def test_ask_cannot_answer_defaults_to_none():
    digest = analysis.build_digest(_records(1))
    payload = json.dumps({"answer": "x", "chart": None, "followups": []})
    assert analysis.ask(digest, "?", client=_StubLLM(payload))["cannot_answer"] is None
    blank = json.dumps({"answer": "x", "cannot_answer": "   "})
    assert analysis.ask(digest, "?", client=_StubLLM(blank))["cannot_answer"] is None


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


def _log_repo(monkeypatch, tmp_path, games: int = 2) -> str:
    """Sätt upp ett lokalt loggrepo med en incheckad logg. Returnerar filnamnet."""
    import subprocess

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@e"], check=True)
    name = "2026-01-01-120000.jsonl"
    text = "".join(json.dumps(rec) + "\n" for rec in _records(games))
    (work / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-q", "-m", "logg"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "HEAD"], check=True)

    token = tmp_path / "token"
    token.write_text("dummy\n", encoding="utf-8")
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "clone"))
    monkeypatch.setenv("MEIER_LOGS_REMOTE_URL", str(remote))
    monkeypatch.setenv("MEIER_LOGS_TOKEN_FILE", str(token))
    # Klona in i testets katalog.
    from meier import logrepo

    logrepo.LogRepo().ensure_clone()
    return name


def test_analysis_lists_logs_from_repo(monkeypatch, tmp_path):
    name = _log_repo(monkeypatch, tmp_path, games=2)
    # Tom lokal katalog, så bara loggre pets fil räknas upp.
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "lokalt"))
    client = TestClient(web_app.app)
    web_app._store.clear()
    data = client.get("/api/analysis/logs").json()
    assert data["ready"] is True
    assert [e["name"] for e in data["logs"]] == [name]
    assert data["logs"][0]["games"] == 2
    # Tiden skickas som epoch så att gränssnittet kan formatera den i läsarens
    # tidszon i stället för att visa serverns (ofta UTC) klockslag.
    assert data["logs"][0]["started_at"] == 1767268800.0
    assert data["logs"][0]["label"] == "1 januari 2026, 12:00:00 (UTC)"
    assert data["logs"][0]["loaded"] is False


def test_analysis_select_loads_and_unloads(monkeypatch, tmp_path):
    name = _log_repo(monkeypatch, tmp_path, games=2)
    client = TestClient(web_app.app)
    web_app._store.clear()

    res = client.post("/api/analysis/select", json={"names": [name]})
    assert res.status_code == 200
    assert res.json()["games"] == 2

    logs = client.get("/api/analysis/logs").json()["logs"]
    assert logs[0]["loaded"] is True

    data = client.get("/api/analysis/data").json()
    assert data["games"] == 2
    assert name in data["sources"]
    assert data["digest_text"]

    # Att avmarkera loggen tar bort den ur materialet igen.
    assert client.post("/api/analysis/select", json={"names": []}).json()["games"] == 0


def test_analysis_select_rejects_unknown_name(monkeypatch, tmp_path):
    _log_repo(monkeypatch, tmp_path, games=1)
    client = TestClient(web_app.app)
    web_app._store.clear()

    bad = client.post("/api/analysis/select", json={"names": ["../x.jsonl"]})
    assert bad.status_code == 404
    missing = client.post("/api/analysis/select", json={"names": ["saknas.jsonl"]})
    assert missing.status_code == 404


def test_analysis_logs_without_repo(monkeypatch, tmp_path):
    """Utan loggrepo listas ändå lokala serier, och ready är True."""
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "finns-inte"))
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "lokalt"))
    client = TestClient(web_app.app)
    data = client.get("/api/analysis/logs").json()
    assert data["ready"] is True
    assert data["logs"] == []


def test_analysis_logs_without_repo_but_with_local_series(monkeypatch, tmp_path):
    """En lokal serie ska synas även när loggrepet inte finns alls.

    Detta var hela poängen: serien ska gå att analysera utan git-incheckning.
    """
    local = tmp_path / "lokalt"
    local.mkdir()
    name = "2026-01-01-120000.jsonl"
    (local / name).write_text(json.dumps(_records(1)[0]) + "\n", encoding="utf-8")
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "finns-inte"))
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(local))
    client = TestClient(web_app.app)
    web_app._store.clear()

    data = client.get("/api/analysis/logs").json()
    assert data["ready"] is True
    assert [e["name"] for e in data["logs"]] == [name]
    assert data["logs"][0]["local"] is True

    res = client.post("/api/analysis/select", json={"names": [name]})
    assert res.status_code == 200
    assert res.json()["games"] == 1


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


# -- Detaljvy: match → runda → händelse -------------------------------------


def test_group_rounds_splits_on_round_number():
    rec = _records(1)[0]
    rounds = match.group_rounds(rec["events"])
    assert len(rounds) == rec["rounds"]
    # Alla händelser ska hamna i exakt en runda, i loggordning.
    assert sum(len(r["events"]) for r in rounds) == len(rec["events"])
    assert [r["round"] for r in rounds] == list(range(1, rec["rounds"] + 1))


def test_group_rounds_counts_rolls_and_lives():
    rec = _records(1)[0]
    rounds = match.group_rounds(rec["events"])
    for bucket in rounds:
        kinds = [e["kind"] for e in bucket["events"]]
        assert bucket["rolls"] == kinds.count("roll")
        lost = sum(e.get("lives_lost") or 0 for e in bucket["events"])
        assert bucket["lives_lost"] == lost
        for name in bucket["losers"]:
            assert any(
                e.get("player_name") == name and e["kind"] == "life"
                for e in bucket["events"]
            )


def test_claim_truth_matches_dice_not_log_flag():
    """Loggens truth är False på syn- och skickarader, men budet kan vara sant."""
    # 64 slaget mot tärningarna 64: budet är sant, även på en synrad.
    assert match.claim_truth({"claim": 64, "dice": [6, 4]}) is True
    assert match.claim_truth({"claim": 65, "dice": [6, 4]}) is False
    # Mejer (21) är högst och sant bara när tärningarna visar just 21.
    assert match.claim_truth({"claim": 21, "dice": [1, 2]}) is True
    assert match.claim_truth({"claim": 21, "dice": [2, 2]}) is False
    # Utan bud finns inget att döma.
    assert match.claim_truth({"claim": None, "dice": [6, 4]}) is None
    assert match.claim_truth({"claim": 64, "dice": None}) is None


def test_match_detail_marks_claim_truth_on_call_events():
    rec = _records(1)[0]
    detail = match.match_detail(rec)
    calls = [
        e
        for bucket in detail["rounds_list"]
        for e in bucket["events"]
        if e["action"] == "syna" and e.get("claim_name")
    ]
    assert calls, "matchen ska innehålla minst en syn"
    for e in calls:
        assert isinstance(e["claim_truth"], bool)


def test_group_rounds_tracks_final_dice_after_reroll():
    """Ett slag mitt i rundan byter tärningar. Rubriken ska visa båda."""
    events = [
        {"kind": "roll", "round": 1, "shown_name": "43", "dice": [3, 4]},
        {"kind": "action", "round": 1, "action": "påstå", "shown_name": "43"},
        {"kind": "roll", "round": 1, "shown_name": "64", "dice": [6, 4]},
        {"kind": "action", "round": 1, "action": "påstå", "shown_name": "64"},
    ]
    [bucket] = match.group_rounds(events)
    assert bucket["shown"] == "43"
    assert bucket["final_shown"] == "64"
    assert bucket["rolls"] == 2


def test_match_detail_has_rounds_and_summary():
    rec = _records(2)[1]
    detail = match.match_detail(rec)
    assert detail["game"] == rec["game"]
    assert detail["winner"] == rec["winner"]
    assert detail["rounds"] == rec["rounds"]
    assert detail["events"] == len(rec["events"])
    assert len(detail["rounds_list"]) == rec["rounds"]
    assert all("events" in r for r in detail["rounds_list"])
    # Rundorna bär händelserna, så listan ska inte ligga med en gång till.
    assert "events_list" not in detail


def test_match_brief_merges_player_stats():
    rec = _records(1)[0]
    brief = match.match_brief(rec["game"], rec)
    assert brief["events"] == len(rec["events"])
    assert brief["legacy"] is False
    by_name = {p["name"]: p for p in brief["players"]}
    for entry in rec["players"]:
        assert by_name[entry["name"]]["role"] == entry["role"]
    # Statistiken ska följa med, så att listan kan visa bluff och syn.
    assert any(p.get("decisions") for p in brief["players"])


def _loaded_client(monkeypatch, tmp_path) -> TestClient:
    name = _log_repo(monkeypatch, tmp_path, games=3)
    client = TestClient(web_app.app)
    web_app._store.clear()
    client.post("/api/analysis/select", json={"names": [name]})
    return client


def test_analysis_matches_lists_without_events(monkeypatch, tmp_path):
    client = _loaded_client(monkeypatch, tmp_path)
    source = web_app._store.sources()[0]
    data = client.get("/api/analysis/matches", params={"source": source}).json()
    assert data["source"] == source
    assert data["games"] == 3
    assert [m["game"] for m in data["matches"]] == [1, 2, 3]
    for m in data["matches"]:
        assert m["events"] > 0
        assert "rounds_list" not in m


def test_analysis_match_returns_rounds(monkeypatch, tmp_path):
    client = _loaded_client(monkeypatch, tmp_path)
    source = web_app._store.sources()[0]
    rec = client.get(
        "/api/analysis/match", params={"source": source, "game": 2}
    ).json()["match"]
    assert rec["game"] == 2
    assert len(rec["rounds_list"]) == rec["rounds"]
    first = rec["rounds_list"][0]
    assert first["events"]
    assert first["events"][0]["round"] == first["round"]


def test_analysis_match_unknown_game_is_404(monkeypatch, tmp_path):
    client = _loaded_client(monkeypatch, tmp_path)
    source = web_app._store.sources()[0]
    res = client.get("/api/analysis/match", params={"source": source, "game": 99})
    assert res.status_code == 404


def test_analysis_matches_unknown_source_is_404(monkeypatch, tmp_path):
    client = _loaded_client(monkeypatch, tmp_path)
    res = client.get("/api/analysis/matches", params={"source": "finns-inte.jsonl"})
    assert res.status_code == 404


def test_analysis_detail_reads_disk_when_not_loaded(monkeypatch, tmp_path):
    """Efter omstart är butiken tom, men detaljvyn ska ändå fungera."""
    name = _log_repo(monkeypatch, tmp_path, games=2)
    client = TestClient(web_app.app)
    web_app._store.clear()
    res = client.get("/api/analysis/matches", params={"source": name})
    assert res.status_code == 200
    assert res.json()["games"] == 2


def test_analysis_detail_reads_record_without_format(monkeypatch, tmp_path):
    """En logg från före format 2 saknar format-fältet men ska gå att öppna."""
    name = _log_repo(monkeypatch, tmp_path, games=2)
    # Servern läser klonen, inte arbetskatalogen.
    path = tmp_path / "clone" / name
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        rec.pop("format", None)
        lines.append(json.dumps(rec))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    client = TestClient(web_app.app)
    web_app._store.clear()
    data = client.get("/api/analysis/matches", params={"source": name}).json()
    assert data["games"] == 2
    assert all(m["legacy"] for m in data["matches"])


def test_analysis_delete_removes_the_log_from_the_repo(monkeypatch, tmp_path):
    """Borttagningen ska nå fjärren: filen bort ur git, inte bara ur vyn."""
    import subprocess

    name = _log_repo(monkeypatch, tmp_path, games=2)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "lokalt"))
    client = TestClient(web_app.app)
    web_app._store.clear()
    client.post("/api/analysis/select", json={"names": [name]})

    res = client.post("/api/analysis/delete", json={"names": [name]})

    assert res.status_code == 200
    data = res.json()
    assert data["deleted"] == [name]
    assert data["in_repo"] == [name]
    assert data["local"] == []
    assert "pushat" in data["status"].lower()
    # Loggen ska också vara borta ur analysmaterialet.
    assert data["games"] == 0

    assert not (tmp_path / "clone" / name).exists()
    names = subprocess.run(
        ["git", "--git-dir", str(tmp_path / "remote.git"), "ls-tree", "-r",
         "--name-only", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert name not in names
    assert client.get("/api/analysis/logs").json()["logs"] == []


def test_analysis_delete_removes_a_local_series(monkeypatch, tmp_path):
    local = tmp_path / "lokalt"
    local.mkdir()
    name = "2026-01-01-120000.jsonl"
    (local / name).write_text(json.dumps(_records(1)[0]) + "\n", encoding="utf-8")
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "finns-inte"))
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(local))
    client = TestClient(web_app.app)
    web_app._store.clear()
    client.post("/api/analysis/select", json={"names": [name]})

    res = client.post("/api/analysis/delete", json={"names": [name]})

    assert res.status_code == 200
    data = res.json()
    assert data["local"] == [name]
    assert data["in_repo"] == []
    assert data["games"] == 0
    assert not (local / name).exists()


def test_analysis_delete_rejects_bad_and_missing_names(monkeypatch, tmp_path):
    _log_repo(monkeypatch, tmp_path, games=1)
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "lokalt"))
    client = TestClient(web_app.app)

    assert client.post("/api/analysis/delete", json={"names": []}).status_code == 400
    # Sökvägar utanför klonen ska aldrig nå git.
    assert client.post(
        "/api/analysis/delete", json={"names": ["../x.jsonl"]}
    ).status_code == 400
    assert client.post(
        "/api/analysis/delete", json={"names": ["saknas.jsonl"]}
    ).status_code == 404


def test_analysis_delete_releases_the_last_series_pointer(monkeypatch, tmp_path):
    """Raderas serien som Matchserie-fliken pekar på ska pekfilen släppas."""
    local = tmp_path / "lokalt"
    local.mkdir()
    name = "2026-01-01-120000.jsonl"
    (local / name).write_text(json.dumps(_records(1)[0]) + "\n", encoding="utf-8")
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "finns-inte"))
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(local))
    web_app._current_match_file = local / name
    web_app._remember_series(local / name, 1)
    client = TestClient(web_app.app)

    res = client.post("/api/analysis/delete", json={"names": [name]})

    assert res.status_code == 200
    assert web_app._current_match_file.name != name
    assert not web_app._last_series_path().exists()


def test_analysis_lists_the_newest_series_first(monkeypatch, tmp_path):
    """Ordningen ska komma ur seriens tid i namnet, inte ur filens mtime.

    En logg som hämtas med git pull får mtime när den checkas ut, så
    mtime-ordning kastar om historiken: en gammal serie kunde hamna över en ny.
    Etiketten visar namnets tid, och listan ska följa samma tid.
    """
    local = tmp_path / "lokalt"
    local.mkdir()
    older = local / "2026-01-01-100000.jsonl"
    newer = local / "2026-01-02-090000.jsonl"
    for path in (older, newer):
        path.write_text(json.dumps(_records(1)[0]) + "\n", encoding="utf-8")
    # Den äldre serien får nyast mtime, som efter en utcheckning ur git.
    os.utime(older, (2_000_000_000, 2_000_000_000))
    os.utime(newer, (1_000_000_000, 1_000_000_000))
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "finns-inte"))
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(local))
    client = TestClient(web_app.app)
    web_app._store.clear()

    names = [e["name"] for e in client.get("/api/analysis/logs").json()["logs"]]
    assert names == [newer.name, older.name]


def test_analysis_lists_repo_and_local_series_in_one_order(monkeypatch, tmp_path):
    """De incheckade och de lokala loggarna ska blandas i samma tidsordning."""
    repo_name = _log_repo(monkeypatch, tmp_path, games=1)  # 2026-01-01-120000
    local = tmp_path / "lokalt"
    local.mkdir()
    newer = "2026-01-03-080000.jsonl"
    older = "2025-12-31-235900.jsonl"
    for name in (newer, older):
        (local / name).write_text(json.dumps(_records(1)[0]) + "\n", encoding="utf-8")
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(local))
    client = TestClient(web_app.app)
    web_app._store.clear()

    names = [e["name"] for e in client.get("/api/analysis/logs").json()["logs"]]
    assert names == [newer, repo_name, older]
