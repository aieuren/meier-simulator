"""Tester för att koden äger reglerna och LLM:en äger besluten.

Tyngdpunkten ligger på gränsen mellan dem: ett drag som bryter mot reglerna får
aldrig nå bordet, hur säker modellen än är. Samtidigt får koden inte lägga sig i
vilket *lagligt* drag som väljs — det är spelarens sak.
"""

from dataclasses import dataclass, field

import pytest

from meier import legality, rules
from meier.agents.base import Role
from meier.agents.roster import ROSTER
from meier.agents.strategic import StrategicAgent
from meier.policy import AgentParams


# -- Legalitetslagret -------------------------------------------------------


def test_all_three_responses_are_legal_below_meier():
    for bid in rules.RANKING:
        if rules.is_meier(bid):
            continue
        assert legality.response_actions(bid=bid) == ["syna", "skicka", "slå"]


def test_shaking_is_not_offered_against_meier():
    """Mot Meier finns inget högre påstående, så ``slå`` går inte att utföra.

    Ett riktigt parti kraschade här: spelaren valde ``slå`` mot Meier och
    motorn bad om ett påstående över det högsta som finns.
    """
    assert "slå" not in legality.response_actions(bid=rules.MEIER)
    assert "syna" in legality.response_actions(bid=rules.MEIER)
    assert "skicka" in legality.response_actions(bid=rules.MEIER)


def test_llm_choosing_shake_against_meier_never_crashes():
    agent = agent_with(['{"action": "slå", "reasoning": "trotsar"}'])
    decision = agent.decide(rules.MEIER)
    assert decision.action in legality.response_actions(bid=rules.MEIER)


def test_first_bid_may_be_anything_in_the_ranking():
    # Ingen undre gräns vid rundans första påstående: även 31 är lagligt.
    assert legality.legal_bids(shown=52) == list(rules.RANKING)


def test_bids_above_a_previous_bid_are_strictly_higher():
    legal = legality.legal_bids(shown=31, previous_bid=61)
    assert all(rules.is_higher(b, 61) for b in legal)
    assert 61 not in legal
    assert 31 not in legal


def test_meier_has_no_higher_bid():
    assert legality.legal_bids(shown=31, previous_bid=rules.MEIER) == []
    assert legality.blind_bids(previous_bid=rules.MEIER) == []
    assert legality.forced_choices(previous_bid=rules.MEIER) == []


def test_forced_choice_exists_for_every_non_meier_bid():
    for bid in rules.RANKING:
        if rules.is_meier(bid):
            continue
        assert legality.forced_choices(previous_bid=bid) == ["titta", "blint"]


def test_illegal_bids_are_rejected():
    assert not legality.is_legal_bid(52, previous_bid=61)
    assert not legality.is_legal_bid(99)
    assert legality.is_legal_bid(62, previous_bid=61)


# -- LLM:en fattar beslutet ------------------------------------------------


@dataclass
class ScriptedLLM:
    """Svarar med en förutbestämd sekvens av JSON-strängar."""

    replies: list[str]
    calls: int = field(default=0, init=False)
    prompts: list[str] = field(default_factory=list, init=False)

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        self.prompts.append(user)
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply


def agent_with(replies: list[str], *, params: AgentParams | None = None) -> StrategicAgent:
    role = Role(key="test", name="Test", description="", style="")
    return StrategicAgent(role, params or AgentParams(), llm=ScriptedLLM(replies))


def test_llm_bid_is_used_when_legal():
    agent = agent_with(['{"bid": 64, "reasoning": "bluffar"}'])
    ann = agent.announce((2, 5))
    assert ann.bid == 64
    assert ann.corrected is False


def test_llm_illegal_bid_is_rejected_and_asked_again():
    # Först ett olagligt påstående under det som ligger, sedan ett lagligt.
    agent = agent_with(['{"bid": 52}', '{"bid": 62}'])
    ann = agent.announce((1, 1), previous_bid=61)
    assert ann.bid == 62
    assert ann.corrected is False
    assert agent.llm.calls >= 2


def test_llm_that_never_complies_falls_back_to_a_legal_bid():
    # 31 ligger under 61 i rangordningen, så det är olagligt att säga där.
    agent = agent_with(['{"bid": 31}'])
    ann = agent.announce((1, 1), previous_bid=61)
    assert rules.is_higher(ann.bid, 61)
    assert ann.corrected is True


def test_llm_chooses_among_all_three_responses():
    for action in ("syna", "skicka", "slå"):
        agent = agent_with([f'{{"action": "{action}", "reasoning": "x"}}'])
        assert agent.decide(61).action == action


def test_unknown_action_is_rejected():
    agent = agent_with(['{"action": "fuska"}'])
    decision = agent.decide(61)
    assert decision.action in legality.RESPONSES


def test_llm_can_choose_blind_at_forced_raise():
    agent = agent_with(['{"blind": true, "reasoning": "döljer"}'])
    ann = agent.announce_forced((3, 3), previous_bid=54)
    assert ann.blind is True
    assert rules.is_higher(ann.bid, 54)


def test_forced_raise_over_meier_is_not_a_choice():
    # Meier är högst: motorn slår om i stället, så det finns inget val att göra.
    agent = agent_with(['{"blind": true}'])
    with pytest.raises(ValueError):
        agent.announce_forced((3, 3), previous_bid=rules.MEIER)


# -- Ett anrop per beslut --------------------------------------------------


def test_each_decision_costs_exactly_one_llm_call():
    """Repliken får inte kosta ett eget modellanrop.

    Den formuleras ur draget i stället. Ett extra anrop per drag dubblade
    kostnaden och sänkte antalet matcher per kvot, utan att påverka spelet.
    """
    for label, reply, act in (
        ("bud", '{"bid": 62, "reasoning": "x"}',
         lambda a: a.announce((1, 1), previous_bid=61)),
        ("svar", '{"action": "syna", "reasoning": "x"}', lambda a: a.decide(61)),
        ("blint", '{"bid": 62, "reasoning": "x"}',
         lambda a: a.announce_blind((1, 1), previous_bid=61)),
    ):
        llm = ScriptedLLM([reply])
        agent = StrategicAgent(
            Role(key="test", name="Test", description="", style=""),
            AgentParams(),
            llm=llm,
        )
        act(agent)
        assert llm.calls == 1, f"{label} kostade {llm.calls} anrop, inte 1"


def test_line_does_not_need_an_llm():
    """Repliken ska gå att bygga utan modell, eftersom den inte är ett beslut."""
    agent = StrategicAgent(
        Role(key="test", name="Test", description="", style=""), AgentParams()
    )
    assert agent._say(62) == "Jag säger 62."
    assert agent._say_action("syna", 61) == "Jag synar 61."


# -- Utan LLM: deterministisk referens ------------------------------------


def test_agent_without_llm_is_deterministic():
    """Utan LLM och utan ``unpredictability`` är agenten helt mekanisk.

    Slumpen är den enda källan till variation, så två agenter med
    ``unpredictability = 0`` måste bjuda exakt lika. Axel själv har
    ``unpredictability > 0`` och får därför variera mellan körningar — se
    ``test_base_model_uses_no_llm_and_no_reading``.
    """
    role = Role(key="axel", name="Axel", description="", style="")
    params = AgentParams(unpredictability=0.0)
    a = StrategicAgent(role, params)
    b = StrategicAgent(role, params)
    for dice in [(1, 1), (2, 5), (6, 6), (1, 6)]:
        assert a.announce(dice).bid == b.announce(dice).bid


def test_policy_never_silently_rewrites_the_bid():
    """Påståendet ska vara spelarens eget, inte rättat i efterhand.

    Tidigare valde policyn påståenden utan att veta vad som låg, och motorn skrev tyst
    om 48 % av alla påståenden. Nu väljer policyn bland de lagliga påståendena direkt.
    """
    role = Role(key="axel", name="Axel", description="", style="")
    agent = StrategicAgent(role, AgentParams())
    for previous in rules.RANKING:
        if rules.is_meier(previous):
            continue
        for shown in rules.RANKING:
            hi, lo = divmod(shown, 10)
            ann = agent.announce((hi, lo), previous_bid=previous)
            assert rules.is_higher(ann.bid, previous)
            assert ann.corrected is False


def test_every_role_bids_legally_against_every_previous_bid():
    for key, profile in ROSTER.items():
        role = Role(key=key, name=profile.name, description="", style="")
        agent = StrategicAgent(role, profile.params)
        for previous in rules.RANKING:
            if rules.is_meier(previous):
                continue
            for shown in rules.RANKING:
                hi, lo = divmod(shown, 10)
                ann = agent.announce((hi, lo), previous_bid=previous)
                assert rules.is_higher(ann.bid, previous), (
                    f"{key} bjöd {rules.name(ann.bid)} över {rules.name(previous)}"
                )
