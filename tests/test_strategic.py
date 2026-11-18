"""Integrationstester för den strategiska agenten kopplad till motorn.

Dessa tester fångar de fel som faktiskt uppstod under utvecklingen och som en
enhetstestning av policyn aldrig hade hittat:

- matcher som aldrig tog slut (livelock vid Meier när ingen synade),
- motståndarmodellen som inte matades av motorn,
- den läsande agenten som blev för passiv och därför aldrig synade.

De täcker också att registret (Axel + Berit/Cecilia/David) spelar en hel match
och att Axel är den LLM-fria referensen.
"""

import pytest

from meier.agents.base import Role
from meier.agents.roster import ROSTER, make_players
from meier.agents.strategic import StrategicAgent
from meier.opponents import OpponentTracker
from meier.policy import AgentParams
from meier.session import Session


def make(name: str, params: AgentParams, tracker: OpponentTracker):
    role = Role(key=name, name=name, description="", style="")
    return StrategicAgent(role, params, tracker=tracker)


def play(names: list[str], seed: int, lives: int = 3):
    """Spela en match med registrets profiler och en delad motståndarmodell."""
    tracker = OpponentTracker()
    players = [make(n, ROSTER[n].params, tracker) for n in names]
    session = Session.new(players, seed=seed, lives=lives)
    session.tracker = tracker
    session.play_to_end()
    return session, tracker


def test_full_match_terminates():
    session, _ = play(["axel", "berit", "cecilia", "david"], seed=1)
    assert session.finished
    assert session._winner() is not None


@pytest.mark.parametrize("seed", range(20))
def test_matches_always_terminate(seed):
    # Livelock-buggen: utan Meier-regeln fastnade matcherna i tusentals rundor.
    session, _ = play(["axel", "berit", "cecilia", "david"], seed=seed)
    assert session.finished
    assert session.round < 200


def test_every_action_in_log_is_legal():
    session, _ = play(["axel", "berit", "cecilia", "david"], seed=3)
    for entry in session.log:
        if entry.kind != "action":
            continue
        if entry.action in {"bud", "höja", "slå"}:
            assert entry.bid is not None


def test_tracker_receives_engine_events():
    session, tracker = play(["axel", "berit", "cecilia", "david"], seed=5)
    assert tracker.stats, "motståndarmodellen fick inga händelser"
    total = sum(s.decisions for s in tracker.stats.values())
    assert total > 0, "inga beslut spårades"


def test_tracker_sees_bluffs_only_after_reveal():
    # Varje avslöjat bud måste ha skett vid en syn, aldrig i förväg.
    session, tracker = play(["axel", "berit", "cecilia", "david"], seed=7)
    calls = sum(1 for e in session.log if e.kind == "action" and e.action == "syna")
    revealed = sum(s.revealed for s in tracker.stats.values())
    assert revealed <= calls


def test_a_reading_agent_still_calls():
    # Den läsande agenten fick EV djupt negativ mot en "ärlig" motståndare och
    # synade aldrig — matchen fastnade. Den ska fortfarande svara på bud.
    session, _ = play(["cecilia", "berit"], seed=11)
    calls = sum(1 for e in session.log if e.kind == "action" and e.action == "syna")
    assert calls > 0


def test_no_agent_passes_forever():
    # Ingen agent får skicka vidare ett Meier-bud: det är bevisbart sämre.
    session, _ = play(["axel", "berit", "cecilia", "david"], seed=13)
    for entry in session.log:
        if entry.kind == "action" and entry.action == "skicka":
            assert entry.bid != 21, "Meier skickades vidare"


def test_base_model_is_deterministic():
    # Axel har ingen LLM och ingen läsning: samma frö måste ge samma match.
    a, _ = play(["axel", "berit", "cecilia", "david"], seed=99)
    b, _ = play(["axel", "berit", "cecilia", "david"], seed=99)
    assert a._winner() == b._winner()
    assert a.round == b.round
    assert a.lives == b.lives


def test_reading_changes_the_prior():
    # Läsning ska göra något: en läsande agent ska bedöma en känd bluffare
    # annorlunda än en känd ärlig spelare, givet samma historik.
    tracker = OpponentTracker()
    for _ in range(20):
        tracker.observe_bid("bluffare", blind=False)
        tracker.reveal("bluffare", was_bluff=True)
        tracker.observe_bid("ärlig", blind=False)
        tracker.reveal("ärlig", was_bluff=False)

    reader = make("reader", AgentParams(risk=0.5, press=0.5, reading=1.0), tracker)
    blind = make("blind", AgentParams(risk=0.5, press=0.5, reading=0.0), tracker)

    assert tracker.bluff_ratio("bluffare") > tracker.bluff_ratio("ärlig")
    # En agent utan läsning faller tillbaka på populationen (inget omdöme).
    assert blind._opponent_prior(61, "bluffare") is None
    # Den läsande agenten tror mer på ett högt bud från en känd bluffare än
    # från en känd ärlig spelare.
    assert reader._opponent_prior(61, "bluffare") > reader._opponent_prior(61, "ärlig")


def test_make_players_shares_one_tracker_among_readers():
    players, tracker = make_players(["axel", "berit", "cecilia", "david"])
    by_key = {p.role.key: p for p in players}
    # Axel läser inget: ingen tracker.
    assert by_key["axel"].tracker is None
    # Alla läsande spelare delar samma tracker.
    readers = [p for p in players if p.params.reading > 0.0]
    assert readers, "minst en spelare ska läsa"
    assert all(p.tracker is tracker for p in readers)
    # Axel får aldrig en LLM-klient.
    assert by_key["axel"].llm is None
