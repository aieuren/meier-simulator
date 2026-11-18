"""Tester för den deterministiska policy-kärnan (BASE).

Policyn är spelets "source of truth" för värdering: den avgör vad en agent
bjuder, hur den höjer och när den synar. Testerna låser de egenskaper som
motorn och analysen bygger på, särskilt de som höll på att gå förlorade:

- budet är alltid lagligt och strikt högre vid höjning,
- Meier synas alltid (annars tar rundan aldrig slut),
- ``press`` ger distinkt bluffbenägenhet mellan rollerna,
- den budspecifika tron följer den frysta tabellen.
"""

import pytest

from meier import rules
from meier.agents.roster import ROSTER
from meier.policy import (
    CALL_ODDS,
    CALL_PRIOR,
    AgentParams,
    BasePolicy,
)


@pytest.fixture
def base():
    return BasePolicy(AgentParams(risk=0.5, press=0.5, reading=0.0))


# -- Bud (beslut 1) --------------------------------------------------------

def test_bid_is_always_a_valid_value(base):
    for shown in rules.RANKING:
        decision = base.decide_bid(shown)
        assert rules.is_valid_value(decision.bid)


def test_meier_shown_is_bid_as_meier(base):
    decision = base.decide_bid(rules.MEIER)
    assert decision.bid == rules.MEIER


def test_low_press_bids_the_truth():
    policy = BasePolicy(AgentParams(risk=0.5, press=0.0, reading=0.0))
    for shown in rules.RANKING:
        assert policy.decide_bid(shown).bid == shown


def test_high_press_bluffs_more_than_low_press():
    low = BasePolicy(AgentParams(risk=0.5, press=0.05, reading=0.0))
    high = BasePolicy(AgentParams(risk=0.5, press=0.9, reading=0.0))
    low_bluffs = sum(
        rules.compare(low.decide_bid(s).bid, s) > 0 for s in rules.RANKING
    )
    high_bluffs = sum(
        rules.compare(high.decide_bid(s).bid, s) > 0 for s in rules.RANKING
    )
    assert high_bluffs > low_bluffs


def test_never_bids_below_shown_when_it_could_bid_truth(base):
    # Att bjuda under det man ser är aldrig värt något.
    for shown in rules.RANKING:
        assert rules.compare(base.decide_bid(shown).bid, shown) >= 0


# -- Höjning (beslut 2) ----------------------------------------------------

def test_raise_is_strictly_higher(base):
    for bid in rules.RANKING[:-1]:  # 31 är lägst och har alltid högre alternativ
        decision = base.decide_raise(bid)
        if decision.action == "slå":
            assert rules.is_higher(decision.bid, bid)


def test_raise_at_meier_has_no_option_but_call(base):
    # Meier är högst: det finns inget högre bud.
    decision = base.decide_raise(rules.MEIER)
    assert decision.action in {"syna", "skicka"}


# -- Syn (beslut 3) --------------------------------------------------------

def test_meier_is_always_called(base):
    decision = base.decide_call(rules.MEIER)
    assert decision.action == "syna"


def test_call_never_invents_a_bid(base):
    for bid in rules.RANKING:
        assert base.decide_call(bid).action in {"syna", "skicka"}


def test_low_bids_are_rarely_called(base):
    # Empirin: bud ≤ 54 synas nästan aldrig (0/871 i de gamla loggarna).
    low = [b for b in rules.RANKING if rules.compare(b, 54) < 0]
    called = sum(base.decide_call(b).action == "syna" for b in low)
    assert called == 0


def test_opponent_prior_can_shift_the_call(base):
    # En högre tro på att synen vinner gör att fler bud synas.
    bid = 61
    normal = base.decide_call(bid)
    greedy = base.decide_call(bid, opponent_q=0.9)
    assert normal.action == "skicka"
    assert greedy.action == "syna"


# -- Tvingad höjning (beslut 4) -------------------------------------------

def test_forced_choice_is_titta_or_blint(base):
    # Vid Meier finns inget högre bud; då återstår bara att syna (motorn slår
    # annars om och startar en ny runda). För alla andra bud är valet titta/blint.
    for bid in rules.RANKING:
        if rules.is_meier(bid):
            continue
        assert base.decide_forced(bid).action in {"titta", "blint"}


def test_forced_choice_follows_press():
    calm = BasePolicy(AgentParams(risk=0.5, press=0.0, reading=0.0))
    bold = BasePolicy(AgentParams(risk=0.5, press=1.0, reading=0.0))
    assert calm.decide_forced(54).action == "titta"
    assert bold.decide_forced(54).action == "blint"


# -- Den budspecifika tron -------------------------------------------------

def test_call_prior_covers_every_bid_level():
    assert set(CALL_PRIOR) == set(rules.RANKING)
    assert all(0.0 <= p <= 1.0 for p in CALL_PRIOR.values())


def test_meier_is_the_hardest_bid_to_call_profitably():
    # Meier är högst men svårast att syna: P(vinst) ska vara lägst av alla höga bud.
    assert CALL_PRIOR[rules.MEIER] < CALL_PRIOR[11]


def test_call_odds_break_even_is_sane():
    for bid, odds in CALL_ODDS.items():
        assert 0.0 <= odds.q_star <= 1.0


# -- Parametervalidering ---------------------------------------------------

def test_params_must_be_in_unit_range():
    with pytest.raises(ValueError):
        AgentParams(risk=1.5, press=0.5, reading=0.0)


def test_profiles_are_distinct():
    keys = {p.params.press for p in ROSTER.values()}
    assert len(keys) == len(ROSTER)
