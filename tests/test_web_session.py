"""Test för sessions-API:t, inklusive knappen "Hela matchen" (utan LLM-anrop)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from meier import rules
from meier.agents.base import Role
from meier.agents.player import MeierPlayerAgent
from meier.web import app as web_app
from tests.test_session import ScriptedLLM


def _agent(key: str) -> MeierPlayerAgent:
    role = Role(key=key, name=f"Spelare-{key}", description="test", style="spela")
    return MeierPlayerAgent(role=role, llm=ScriptedLLM(claims=[11], actions=["syna"]))


def _client(monkeypatch) -> TestClient:
    web_app._session = None
    monkeypatch.setattr(web_app, "_get_agent", _agent)
    return TestClient(web_app.app)


def test_session_end_plays_whole_match(monkeypatch):
    client = _client(monkeypatch)
    start = client.post("/api/session/new", json={})
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


def test_announce_endpoint_shakes_when_a_previous_claim_is_given(monkeypatch):
    """"Avancerat"-panelen är ett slag, inte ett första påstående.

    Ett tidigare påstående ska gå via ``announce_shake`` så att spelaren får
    välja att titta. Annars hoppas titt-valet över i webbappen.
    """
    calls = []

    class SpyAgent(MeierPlayerAgent):
        def announce(self, dice, **kw):
            calls.append("announce")
            return super().announce(dice, **kw)

        def announce_shake(self, dice, **kw):
            calls.append("announce_shake")
            return super().announce_shake(dice, **kw)

    role = Role(key="k", name="K", description="test", style="spela")
    agent = SpyAgent(role=role, llm=ScriptedLLM(claims=[11, 21], seen=True))
    web_app._session = None
    monkeypatch.setattr(web_app, "_get_agent", lambda key: agent)

    client = TestClient(web_app.app)

    first = client.post("/api/announce", json={"die1": 5, "die2": 2, "role": "cecilia"})
    assert first.status_code == 200
    assert calls == ["announce"]

    calls.clear()
    shaken = client.post(
        "/api/announce",
        json={"die1": 5, "die2": 2, "role": "cecilia", "previous_claim": 44},
    )
    assert shaken.status_code == 200
    assert calls[0] == "announce_shake", (
        "slag efter påstående måste gå via announce_shake"
    )
    body = shaken.json()["announcement"]
    assert body["unseen"] is False, "standard är att spelaren tittar"


def test_announce_endpoint_marks_the_unseen_choice(monkeypatch):
    """Väljer spelaren bort titten ska svaret säga det."""
    role = Role(key="k", name="K", description="test", style="spela")
    agent = MeierPlayerAgent(role=role, llm=ScriptedLLM(claims=[11, 21], seen=False))
    web_app._session = None
    monkeypatch.setattr(web_app, "_get_agent", lambda key: agent)
    client = TestClient(web_app.app)

    res = client.post(
        "/api/announce", json={"die1": 5, "die2": 2, "role": "cecilia", "previous_claim": 44}
    )
    assert res.status_code == 200
    body = res.json()["announcement"]
    assert body["unseen"] is True
    assert body["choice_line"] == "Jag påstår utan att titta."
    assert rules.is_higher(body["claim"], 44)


def test_announce_rejects_raising_over_meier(monkeypatch):
    """21 – Meier går inte att höja. API:t ska säga det, inte krascha.

    Reglerna låter hållaren slå om och börja en ny runda i stället.
    """
    role = Role(key="k", name="K", description="test", style="spela")
    agent = MeierPlayerAgent(role=role, llm=ScriptedLLM(claims=[11], seen=True))
    web_app._session = None
    monkeypatch.setattr(web_app, "_get_agent", lambda key: agent)
    client = TestClient(web_app.app)

    res = client.post(
        "/api/announce", json={"die1": 5, "die2": 2, "role": "cecilia", "previous_claim": 21}
    )
    assert res.status_code == 400
    assert "Meier" in res.json()["detail"]


def test_llm_failure_aborts_the_match_with_502(monkeypatch):
    """En LLM-spelare som inte svarar ska synas som avbrott, inte som ett tyst drag.

    ``session_advance`` fångar ``LLMError`` och svarar 502. Testet bevisar att
    felet når klienten i stället för att spelet spelar vidare på en räkneregel.
    """
    from meier.llm import LLMError

    class DeadLLM:
        def complete(self, system, prompt, json_mode=True):
            raise LLMError("modellen svarade inte")

    def dead_agent(key: str) -> MeierPlayerAgent:
        role = Role(key=key, name=f"Spelare-{key}", description="test", style="spela")
        return MeierPlayerAgent(role=role, llm=DeadLLM())

    client = _client(monkeypatch)
    monkeypatch.setattr(web_app, "_get_agent", dead_agent)

    client.post("/api/session/new", json={})
    res = client.post("/api/session/advance")

    assert res.status_code == 502
    assert "LLM-fel" in res.json()["detail"]
    assert "modellen svarade inte" in res.json()["detail"]


def test_rules_pdf_is_served():
    """Regellänken i headern ska fungera, inte peka på en fil som saknas."""
    client = TestClient(web_app.app)
    res = client.get("/regler.pdf")

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content[:5] == b"%PDF-"


def test_index_links_to_the_rules_pdf():
    client = TestClient(web_app.app)
    html = client.get("/").text

    assert 'href="/regler.pdf"' in html


def test_previous_claim_offers_start_of_round_as_default():
    """Flik 2 ska ha ett val för rundans början, inte en tom "inget"-post."""
    client = TestClient(web_app.app)
    html = client.get("/").text

    assert "Start på runda" in html
    assert 'value="" selected' in html
    assert "Avancerat: slår efter ett tidigare påstående" not in html


def test_opponent_views_come_after_the_log():
    """Motståndarbilderna ska stå efter loggen, så loggen läses först."""
    client = TestClient(web_app.app)
    html = client.get("/").text

    assert html.index('id="log"') < html.index('id="viewsBox"')
