"""Tester för Meier-spelaragenten med en fejkad LLM.

Vi testar agentens logik (tolkning av LLM-svar, regelkoercion) utan att
anropa en riktig modell.
"""

import json

from meier.agents.player import ROLES, MeierPlayerAgent, get_role
from meier.llm import LLMClient


class FakeLLM(LLMClient):
    """LLM som returnerar ett förutbestämt svar."""

    def __init__(self, payload):
        self.payload = payload
        self.last_system = None
        self.last_user = None

    def complete(self, system, user, *, json_mode=False):
        self.last_system = system
        self.last_user = user
        return json.dumps(self.payload) if not isinstance(self.payload, str) else self.payload


def make_agent(payload, role="kalkyl"):
    return MeierPlayerAgent(role=get_role(role), llm=FakeLLM(payload))


def test_announce_parses_valid_bid():
    agent = make_agent({"bid": 52, "line": "Jag säger 52.", "reasoning": "lagom"})
    ann = agent.announce((2, 5))
    assert ann.shown == 52
    assert ann.bid == 52
    assert ann.truth is True
    assert ann.line == "Jag säger 52."


def test_announce_detects_lie():
    agent = make_agent({"bid": 65, "line": "65!", "reasoning": "bluffar"})
    ann = agent.announce((2, 5))
    assert ann.shown == 52
    assert ann.bid == 65
    assert ann.truth is False


def test_announce_falls_back_to_truth_on_invalid_bid():
    agent = make_agent({"bid": "trams", "line": "?", "reasoning": ""})
    ann = agent.announce((3, 4))
    assert ann.bid == ann.shown == 43


def test_announce_forces_higher_bid_when_required():
    # Modellen föreslår ett för lågt bud trots att den måste höja.
    from meier import rules

    agent = make_agent({"bid": 41, "line": "41", "reasoning": ""})
    ann = agent.announce((2, 1), previous_bid=52)  # tärningarna visar 21 (Meier)
    assert rules.is_higher(ann.bid, 52)


def test_announce_accepts_string_bid():
    agent = make_agent({"bid": "63", "line": "", "reasoning": ""})
    ann = agent.announce((3, 6))
    assert ann.bid == 63


def test_system_prompt_contains_rules():
    agent = make_agent({"bid": 11})
    prompt = agent.system_prompt()
    assert "Meier" in prompt
    assert "21" in prompt
    assert agent.name in prompt


def test_decide_parses_actions():
    for raw, expected in [
        ("syna", "syna"),
        ("slå", "slå"),
        ("skicka", "skicka"),
        ("Syna!", "syna"),
    ]:
        agent = make_agent({"action": raw, "bid": 65, "line": "", "reasoning": ""})
        decision = agent.decide(52)
        assert decision.action == expected


def test_decide_raise_gets_higher_bid():
    agent = make_agent({"action": "slå", "bid": 65, "line": "höjer", "reasoning": ""})
    decision = agent.decide(52)
    assert decision.action == "slå"
    assert decision.bid == 65


def test_decide_raise_with_invalid_bid_picks_higher():
    agent = make_agent({"action": "slå", "bid": 11, "line": "", "reasoning": ""})
    decision = agent.decide(52)  # måste höja över 52
    from meier import rules

    assert decision.bid is not None
    assert rules.is_higher(decision.bid, 52)


def test_decide_unknown_action_defaults_to_skicka():
    agent = make_agent({"action": "???", "bid": None, "line": "", "reasoning": ""})
    decision = agent.decide(43)
    assert decision.action == "skicka"


def test_decide_cannot_raise_over_meier():
    # Budet är Meier (högst) – går inte att slå, agenten får skicka vidare.
    agent = make_agent({"action": "slå", "bid": 11, "line": "", "reasoning": ""})
    decision = agent.decide(21)
    assert decision.action == "skicka"
    assert decision.bid is None


def test_roles_are_distinct():
    assert set(ROLES) == {"arling", "rackar", "kalkyl", "trygg"}
    names = {r.name for r in ROLES.values()}
    assert len(names) == len(ROLES)


def test_get_role_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        get_role("finns-inte")
