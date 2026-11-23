"""Tester för Meier-spelaragenten med en fejkad LLM.

Vi testar agentens logik (tolkning av LLM-svar, regelkoercion) utan att
anropa en riktig modell.
"""

import json

import pytest

from meier.agents.base import Role
from meier.agents.player import MeierPlayerAgent
from meier.agents.roster import ROSTER, get_profile
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


def _role(key="kalkyl"):
    return Role(key=key, name=key, description="test", style="spela")


def make_agent(payload, role="kalkyl"):
    return MeierPlayerAgent(role=_role(role), llm=FakeLLM(payload))


def test_announce_parses_valid_bid():
    agent = make_agent({"bid": 52, "reasoning": "lagom"})
    ann = agent.announce((2, 5))
    assert ann.shown == 52
    assert ann.bid == 52
    assert ann.truth is True
    assert ann.line == "Jag säger 52."


def test_announce_ignores_line_from_model():
    """Modellen ska bara ta fram påståendet, inte formulera repliken."""
    agent = make_agent({"bid": 52, "line": "MITT EGET BUD", "reasoning": "lagom"})
    ann = agent.announce((2, 5))
    assert ann.line == "Jag säger 52."
    assert "MITT EGET BUD" not in ann.line


def test_prompts_do_not_ask_for_line():
    """Promptarna ska inte be modellen skriva en replik."""
    agent = make_agent({})
    for context in (
        agent._announce_context((2, 5), 52, None, []),
        agent._blind_announce_context(52, [54, 53]),
        agent._forced_choice_context(52, [54, 53]),
        agent._decide_context(52, [54, 53], 3),
    ):
        assert "\"line\"" not in context


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
    # Modellen föreslår ett för lågt påstående trots att den måste höja.
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
    # Påståendet är Meier (högst) – går inte att slå, agenten får skicka vidare.
    agent = make_agent({"action": "slå", "bid": 11, "line": "", "reasoning": ""})
    decision = agent.decide(21)
    assert decision.action == "skicka"
    assert decision.bid is None


def test_roster_has_the_five_players():
    assert set(ROSTER) == {"axel", "berit", "cecilia", "david", "elsa"}
    names = {p.name for p in ROSTER.values()}
    assert len(names) == len(ROSTER)


def test_axel_is_the_llm_free_base_model():
    axel = ROSTER["axel"]
    assert axel.uses_llm is False
    assert axel.params.reading == 0.0
    # Axel och Berit delar taktik; bara beslutsmotorn skiljer dem.
    assert axel.params == ROSTER["berit"].params


def test_get_profile_unknown_raises():
    with pytest.raises(ValueError):
        get_profile("finns-inte")
