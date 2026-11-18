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

from meier.agents.reader import OpponentReader
from meier.opponents import NEUTRAL_PRESS, OpponentProfile, OpponentTracker


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
            '{"estimated_risk": 0.7, "estimated_press": 0.9, '
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
        tracker.observe_bid("bluffare", blind=False)
        tracker.reveal("bluffare", was_bluff=True)
    for _ in range(6):
        tracker.observe_decision("bluffare", "syna")
    return tracker


# -- Profilen ---------------------------------------------------------------

def test_profile_clamps_out_of_range_values():
    # En LLM kan svara vad som helst; profilen får aldrig sprida skräp vidare.
    p = OpponentProfile(risk=1.7, press=-0.4, predictability=2.0, confidence=9.0)
    assert p.risk == 1.0
    assert p.press == 0.0
    assert p.predictability == 1.0
    assert p.confidence == 1.0


def test_profile_survives_garbage_from_the_model():
    p = OpponentProfile(risk="mycket", press=None, confidence=float("nan"))
    assert 0.0 <= p.risk <= 1.0
    assert 0.0 <= p.press <= 1.0
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
    assert "risk" not in ev and "press" not in ev


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
    assert profile.press == 0.9
    assert profile.confidence == 0.8


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
    tracker.observe_bid("bluffare", blind=False)
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
    assert profile.press == NEUTRAL_PRESS


# -- Fallback ---------------------------------------------------------------

def test_reader_falls_back_to_statistics_without_llm():
    tracker = _tracker_with_bluffer()
    reader = OpponentReader(llm=None)
    profile = reader.profile(tracker, "bluffare")
    assert profile.source == "statistik"
    assert profile.press > NEUTRAL_PRESS, "en känd bluffare ska bedömas högre"
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
    assert profile.press == NEUTRAL_PRESS


# -- Översättningen till beslut ---------------------------------------------

def test_profile_factor_is_one_for_a_neutral_profile():
    tracker = OpponentTracker()
    assert tracker.profile_factor(OpponentProfile()) == 1.0


def test_profile_factor_grows_with_press_and_confidence():
    tracker = OpponentTracker()
    low = tracker.profile_factor(OpponentProfile(press=0.9, confidence=0.2))
    high = tracker.profile_factor(OpponentProfile(press=0.9, confidence=1.0))
    assert 1.0 < low < high, "högre konfidens ska ge starkare genomslag"


def test_profile_factor_is_damped_by_confidence():
    tracker = OpponentTracker()
    # Samma press, olika konfidens: en osäker gissning får inte slå över tron.
    unsure = tracker.profile_factor(OpponentProfile(press=0.9, confidence=0.0))
    sure = tracker.profile_factor(OpponentProfile(press=0.9, confidence=1.0))
    assert unsure == 1.0
    assert sure > unsure


# -- Klartext för människan --------------------------------------------------

def test_profile_describe_has_words_and_numbers():
    from meier.opponents import OpponentProfile

    p = OpponentProfile(
        kind="bluffbenägen", risk=0.7, press=0.9, confidence=0.7, source="llm"
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
    session = Session.new(players, seed=7)
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

    cautious = describe_params(0.25, 0.25, 0.15)
    bold = describe_params(0.65, 0.60, 0.35)
    assert "sällan" in cautious
    assert "ofta" in bold
    # Siffrorna finns kvar i parentesen.
    assert "25 %" in cautious and "65 %" in bold
    # Ingen läsning ska sägas rakt ut, inte som "0 %".
    assert "läser ingen motståndare" in describe_params(0.5, 0.5, 0.0)
