"""Tester för analysmodulen och analys-API:t (utan riktiga LLM-anrop)."""

from __future__ import annotations

import json

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
    for key in ("roles", "actions", "bids", "outcomes", "call_outcomes"):
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
    name = "meier-matcher-2026-01-01-120000.jsonl"
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
    client = TestClient(web_app.app)
    web_app._store.clear()
    data = client.get("/api/analysis/logs").json()
    assert data["ready"] is True
    assert [e["name"] for e in data["logs"]] == [name]
    assert data["logs"][0]["games"] == 2
    assert data["logs"][0]["label"] == "1 januari 2026, 12:00:00"
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
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "finns-inte"))
    client = TestClient(web_app.app)
    data = client.get("/api/analysis/logs").json()
    assert data == {"ready": False, "logs": []}


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
