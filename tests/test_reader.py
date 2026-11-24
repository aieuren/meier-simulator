"""Tester för motståndarläsaren: LLM:en tolkar, sekreteraren bokför.

Två saker är viktiga att låsa fast:

- **Läsaren ser bara offentligt spel.** Sammanställningen som skickas till
  modellen får inte innehålla motståndarens verkliga parametrar eller dolda
  tärningar.
- **Utan LLM spelar matchen vidare.** Läsaren faller då tillbaka på
  sekreterarens aritmetik, så utvärderingsläget aldrig kraschar på en trasig
  läsning.
"""

from dataclasses import dataclass, field

import pytest

from meier import rules
from meier.agents.reader import OpponentReader
from meier.opponents import NEUTRAL_BLUFF, OpponentProfile, OpponentTracker


@dataclass
class FakeLLM:
    """Låtsas-LLM som svarar med ett förutbestämt JSON-objekt.

    Räknar anropen, så testerna kan visa att profilen cachas och inte räknas om
    vid varje beslut.
    """

    confidence: float = 0.8
    calls: int = field(default=0, init=False)
    last_user: str = field(default="", init=False)

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        self.calls += 1
        self.last_user = user
        return (
            '{"estimated_call": 0.7, "estimated_bluff": 0.9, '
            '"estimated_predictability": 0.3, "type": "bluffbenägen", '
            f'"confidence": {self.confidence}}}'
        )


class BrokenLLM:
    """En LLM som alltid kastar fel. Läsningen får aldrig fälla en match."""

    calls: int = 0

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        self.calls += 1
        raise RuntimeError("nätverket är nere")


def _tracker_with_bluffer() -> OpponentTracker:
    tracker = OpponentTracker()
    for _ in range(6):
        tracker.observe_bid("bluffare", unseen=False)
        tracker.reveal("bluffare", was_bluff=True)
    for _ in range(6):
        tracker.observe_decision("bluffare", "syna")
    return tracker


# -- Profilen ---------------------------------------------------------------

def test_profile_clamps_out_of_range_values():
    # En LLM kan svara vad som helst; profilen får aldrig sprida skräp vidare.
    p = OpponentProfile(call_tendency=1.7, bluff_tendency=-0.4, predictability=2.0, confidence=9.0)
    assert p.call_tendency == 1.0
    assert p.bluff_tendency == 0.0
    assert p.predictability == 1.0
    assert p.confidence == 1.0


def test_profile_survives_garbage_from_the_model():
    p = OpponentProfile(call_tendency="mycket", bluff_tendency=None, confidence=float("nan"))
    assert 0.0 <= p.call_tendency <= 1.0
    assert 0.0 <= p.bluff_tendency <= 1.0
    assert p.confidence == 0.5


# -- Sekreterarens underlag -------------------------------------------------

def test_evidence_is_public_only():
    tracker = _tracker_with_bluffer()
    ev = tracker.evidence("bluffare")
    assert ev["revealed"] == 6
    assert ev["revealed_bluffs"] == 6
    assert ev["bluff_rate"] == 1.0
    assert ev["call_rate"] == 1.0
    # Inga fält läcker motståndarens interna parametrar.
    assert not {"caution", "statistics", "unpredictability", "reading"} & set(ev)
    assert not {"call_tendency", "bluff_tendency", "predictability"} & set(ev)


def test_evidence_is_empty_for_unknown_player():
    tracker = OpponentTracker()
    ev = tracker.evidence("okänd")
    assert ev["revealed"] == 0
    assert ev["bluff_rate"] is None
    assert not tracker.has_evidence("okänd")


# -- Läsaren med LLM --------------------------------------------------------

def test_reader_uses_the_llm_when_available():
    tracker = _tracker_with_bluffer()
    llm = FakeLLM()
    reader = OpponentReader(llm=llm)
    profile = reader.profile(tracker, "bluffare")
    assert llm.calls == 1
    assert profile.source == "llm"
    assert profile.kind == "bluffbenägen"
    assert profile.bluff_tendency == 0.9
    # Sex synar har avgjorts vid bordet: 6/(6+3) = 0,667. Modellen bad om 0,8,
    # men underlaget sätter taket — en bild får inte vara säkrare än facit medger.
    assert profile.confidence == pytest.approx(6 / 9)


def test_confidence_is_capped_by_the_evidence_at_the_table():
    """En bild byggd på en enda syn får inte räknas som säker."""
    tracker = OpponentTracker()
    tracker.observe_bid("bluffare", unseen=False)
    tracker.reveal("bluffare", was_bluff=True)
    reader = OpponentReader(llm=FakeLLM(confidence=1.0))
    profile = reader.profile(tracker, "bluffare")
    assert profile.confidence == pytest.approx(1 / 4)  # 1/(1+3)


def test_confidence_grows_as_more_calls_are_revealed():
    """Ju fler synar bordet har facit på, desto säkrare får bilden bli."""
    seen = []
    for reveals in (1, 3, 9):
        tracker = OpponentTracker()
        for _ in range(reveals):
            tracker.observe_bid("bluffare", unseen=False)
            tracker.reveal("bluffare", was_bluff=True)
        reader = OpponentReader(llm=FakeLLM(confidence=1.0))
        seen.append(reader.profile(tracker, "bluffare").confidence)
    assert seen[0] < seen[1] < seen[2]
    assert seen == sorted(seen)


def test_reader_never_sends_hidden_information():
    tracker = _tracker_with_bluffer()
    llm = FakeLLM()
    reader = OpponentReader(llm=llm)
    reader.profile(tracker, "bluffare")
    # Sammanställningen är räknad ur offentliga händelser — inga dolda tärningar.
    assert "bluffare" in llm.last_user
    assert "tärning" not in llm.last_user.lower()


def test_reader_caches_until_new_evidence_arrives():
    tracker = _tracker_with_bluffer()
    llm = FakeLLM()
    reader = OpponentReader(llm=llm)
    reader.profile(tracker, "bluffare")
    reader.profile(tracker, "bluffare")
    assert llm.calls == 1, "profilen ska cachas mellan beslut"

    # Ny syn → nytt bevis → profilen räknas om.
    tracker.observe_bid("bluffare", unseen=False)
    tracker.reveal("bluffare", was_bluff=False)
    reader.profile(tracker, "bluffare")
    assert llm.calls == 2


def test_reader_asks_nothing_before_there_is_evidence():
    tracker = OpponentTracker()
    llm = FakeLLM()
    reader = OpponentReader(llm=llm)
    profile = reader.profile(tracker, "okänd")
    assert llm.calls == 0, "inget att tolka: inget anrop"
    assert profile.source == "population"
    assert profile.bluff_tendency == NEUTRAL_BLUFF


# -- Fallback ---------------------------------------------------------------

def test_reader_falls_back_to_statistics_without_llm():
    tracker = _tracker_with_bluffer()
    reader = OpponentReader(llm=None)
    profile = reader.profile(tracker, "bluffare")
    assert profile.source == "statistik"
    assert profile.bluff_tendency > NEUTRAL_BLUFF, "en känd bluffare ska bedömas högre"
    assert profile.confidence > 0.0


def test_reader_survives_a_broken_llm():
    tracker = _tracker_with_bluffer()
    llm = BrokenLLM()
    reader = OpponentReader(llm=llm)
    profile = reader.profile(tracker, "bluffare")
    # Läsningen misslyckades, men spelet går vidare på sekreterarens siffror.
    assert llm.calls == 1
    assert profile.source == "statistik"


def test_statistical_profile_is_population_without_data():
    tracker = OpponentTracker()
    profile = tracker.statistical_profile("okänd")
    assert profile.source == "population"
    assert profile.bluff_tendency == NEUTRAL_BLUFF


# -- Översättningen till beslut ---------------------------------------------

def test_bluff_factor_is_one_for_a_neutral_profile():
    tracker = OpponentTracker()
    assert tracker.bluff_factor(OpponentProfile()) == 1.0


def test_bluff_factor_grows_with_tendency_and_confidence():
    tracker = OpponentTracker()
    low = tracker.bluff_factor(OpponentProfile(bluff_tendency=0.9, confidence=0.2))
    high = tracker.bluff_factor(OpponentProfile(bluff_tendency=0.9, confidence=1.0))
    assert 1.0 < low < high, "högre konfidens ska ge starkare genomslag"


def test_bluff_factor_is_damped_by_confidence():
    tracker = OpponentTracker()
    # Samma benägenhet, olika konfidens: en osäker gissning får inte slå över tron.
    unsure = tracker.bluff_factor(OpponentProfile(bluff_tendency=0.9, confidence=0.0))
    sure = tracker.bluff_factor(OpponentProfile(bluff_tendency=0.9, confidence=1.0))
    assert unsure == 1.0
    assert sure > unsure


# -- Risk: motståndarens synbenägenhet --------------------------------------

def test_call_factor_is_one_for_a_neutral_profile():
    tracker = OpponentTracker()
    assert tracker.call_factor(OpponentProfile()) == 1.0


def test_call_factor_tracks_calls_not_bluffs():
    """Synbenägenhet handlar om att syna, bluffbenägenhet om att ljuga.

    De får inte blandas: ``call_factor`` ska bara läsa ``call_tendency``.
    """
    tracker = OpponentTracker()
    synbenägen = tracker.call_factor(OpponentProfile(call_tendency=0.9, bluff_tendency=0.1, confidence=1.0))
    lögnaktig = tracker.call_factor(OpponentProfile(call_tendency=0.1, bluff_tendency=0.9, confidence=1.0))
    assert synbenägen > 1.0 > lögnaktig


def test_call_factor_is_damped_by_confidence():
    tracker = OpponentTracker()
    unsure = tracker.call_factor(OpponentProfile(call_tendency=0.9, confidence=0.0))
    sure = tracker.call_factor(OpponentProfile(call_tendency=0.9, confidence=1.0))
    assert unsure == 1.0
    assert sure > unsure


def test_opponent_factor_never_lowers_the_bid_below_the_truth():
    """En synbenägen motståndare får aldrig locka fram en *högre* bluff.

    Ju oftare motståndaren synar, desto dyrare blir bluffen. Faktorn får
    alltså bara sänka påståendet, aldrig höja det.
    """
    from meier.policy import AgentParams, BasePolicy

    # Utan oförutsägbarhet blir jämförelsen mellan de två anropen meningsfull;
    # annars kan slumpen släppa en bluff i det ena anropet och inte i det andra.
    policy = BasePolicy(AgentParams(unpredictability=0.0))
    for shown in rules.RANKING:
        if rules.is_meier(shown):
            continue
        neutral = policy.decide_bid(shown)
        for factor in (2.0, 3.0):
            vs_caller = policy.decide_bid(shown, opponent_factor=factor)
            assert rules.compare(vs_caller.bid, neutral.bid) <= 0, (
                f"faktor {factor} höjde påståendet på {rules.name(shown)}"
            )


def test_call_ratio_is_relative_to_the_population():
    tracker = OpponentTracker()
    from meier.opponents import POPULATION_CALL_RATE

    n = 100
    normal_calls = round(n * POPULATION_CALL_RATE)
    for _ in range(n):
        tracker.observe_bid("normal", unseen=False)
    for i in range(n):
        tracker.observe_decision("normal", "syna" if i < normal_calls else "skicka")
    for _ in range(n):
        tracker.observe_bid("synare", unseen=False)
    for i in range(n):
        tracker.observe_decision("synare", "syna" if i < 60 else "skicka")
    normal = tracker.call_ratio("normal")
    synare = tracker.call_ratio("synare")
    assert normal == pytest.approx(1.0, abs=0.05), "typisk synfrekvens ska ge ratio ~1"
    assert synare > normal


def test_call_tendency_reaches_the_bid_through_the_agent():
    """Synbenägenheten ska faktiskt styra agentens påståenden, inte bara räknas ut."""
    from meier.agents.base import Role
    from meier.agents.strategic import StrategicAgent
    from meier.policy import AgentParams

    def agent_for(call_rate: float) -> StrategicAgent:
        tracker = OpponentTracker()
        n = 40
        for _ in range(n):
            tracker.observe_bid("X", unseen=False)
            tracker.reveal("X", was_bluff=False)
        for i in range(n):
            tracker.observe_decision("X", "syna" if i < int(call_rate * n) else "skicka")
        role = Role(key="t", name="Test", description="", style="")
        return StrategicAgent(
            role,
            AgentParams(caution=0.5, statistics=0.5, unpredictability=0.0, reading=1.0),
            tracker=tracker,
        )

    timid = agent_for(0.03)
    caller = agent_for(0.50)
    assert timid._call_factor("X") < 1.0 < caller._call_factor("X")

    def bluffs(agent: StrategicAgent) -> int:
        count = 0
        for shown in rules.RANKING:
            if rules.is_meier(shown):
                continue
            d = agent.policy.decide_bid(shown, opponent_factor=agent._call_factor("X"))
            if d.bid is not None and rules.compare(d.bid, shown) > 0:
                count += 1
        return count

    assert bluffs(caller) < bluffs(timid)


def test_summary_gives_the_model_a_reference_point():
    """Modellen ska veta vad en *vanlig* synfrekvens är, inte läsa den som noll."""
    from meier.opponents import POPULATION_CALL_RATE

    tracker = _tracker_with_bluffer()
    llm = FakeLLM()
    reader = OpponentReader(llm=llm)
    reader.profile(tracker, "bluffare")
    # Referenspunkten ska komma ur konstanten, inte ur en siffra skriven i prompten.
    assert f"{POPULATION_CALL_RATE:.0%}" in llm.last_user
    assert "RELATIVT" in llm.last_user.upper()


# -- Klartext för människan --------------------------------------------------

def test_profile_describe_has_words_and_numbers():
    from meier.opponents import OpponentProfile

    p = OpponentProfile(
        kind="bluffbenägen", call_tendency=0.7, bluff_tendency=0.9, confidence=0.7, source="llm"
    )
    text = p.describe()
    assert "bluffbenägen" in text.lower()
    assert "bluffar" in text
    # Siffrorna står kvar i parentesen så beskrivningen går att kontrollera.
    assert "90 %" in text and "70 %" in text


def test_profile_describe_says_when_there_is_no_picture():
    from meier.opponents import OpponentProfile

    assert "Ingen bild" in OpponentProfile().describe()


def test_session_views_show_agents_picture_of_the_others():
    # En spelad match ska rapportera vilka bilder agenterna byggt, i klartext.
    from meier.agents.roster import make_players
    from meier.session import Session

    players, tracker = make_players(["axel", "berit", "cecilia", "david"])
    session = Session.new(players)
    session.tracker = tracker
    session.play_to_end()

    views = session.to_dict()["views"]
    assert views, "minst en agent ska ha en bild"
    # Axel läser ingen och får därför aldrig någon bild.
    assert all(v["agent"] != "Axel" for v in views)
    for v in views:
        assert v["profiles"], "en listad agent ska ha minst en bild"
        for p in v["profiles"]:
            assert p["text"], "bilden ska ha en klartext"
            assert p["profile"]["source"] != "population"


def test_describe_params_reads_as_a_character():
    from meier.opponents import describe_params

    cautious = describe_params(0.80, 0.50, 0.20, 0.50)
    bold = describe_params(0.10, 0.50, 0.20, 0.50)
    assert "ndviker risk" in cautious
    assert "ar stora risker" in bold
    # Siffrorna finns kvar i parentesen.
    assert "80 %" in cautious and "10 %" in bold
    # Ingen läsning ska sägas rakt ut, inte som "0 %".
    assert "läser ingen motståndare" in describe_params(0.5, 0.5, 0.2, 0.0)
