"""Tester för den deterministiska policy-kärnan (BASE).

Policyn är spelets "source of truth" för värdering: den avgör vad en agent
bjuder, hur den höjer och när den synar. Testerna låser de egenskaper som
motorn och analysen bygger på, särskilt de som höll på att gå förlorade:

- budet är alltid lagligt och strikt högre vid höjning,
- svaret på ett bud har tre lagliga val (syna, skicka, slå) och ingen av dem
  tvingas fram av en regel — bara av värderingen,
- ``caution``, ``statistics``, ``unpredictability`` och ``reading`` är de enda
  personlighetsmåtten; bluffandet är ingen parameter,
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
    return BasePolicy(AgentParams())


# -- Bud (beslut 1) --------------------------------------------------------

def test_bid_is_always_a_valid_value(base):
    for shown in rules.RANKING:
        decision = base.decide_bid(shown)
        assert rules.is_valid_value(decision.bid)


def test_meier_shown_is_bid_as_meier(base):
    decision = base.decide_bid(rules.MEIER)
    assert decision.bid == rules.MEIER


def test_bluffing_is_not_a_parameter():
    """Bluffen ska inte gå att skruva på: den följer av reglerna, inte profilen.

    Alla fyra dimensionerna varieras, men antalet bluffar ska vara detsamma —
    annars har bluffandet smygit in som en femte, oavsiktlig parameter.
    """
    from meier.policy import BLUFF_GAIN

    assert BLUFF_GAIN > 0.0
    assert {f.name for f in AgentParams.__dataclass_fields__.values()} == {
        "caution",
        "statistics",
        "unpredictability",
        "reading",
    }

    counts = set()
    for caution in (0.0, 0.5, 1.0):
        for statistics in (0.0, 0.5, 1.0):
            for unpredictability in (0.0,):
                p = BasePolicy(
                    AgentParams(
                        caution=caution,
                        statistics=statistics,
                        unpredictability=unpredictability,
                        reading=0.0,
                    )
                )
                counts.add(
                    sum(
                        rules.compare(p.decide_bid(s).bid, s) > 0
                        for s in rules.RANKING
                    )
                )
    assert len(counts) == 1, f"bluffantalet varierade med profilerna: {counts}"


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

def test_meier_call_ev_never_forbids_calling(base):
    # Meier är det dyraste budet att bära, så synen är alltid värd att ta i
    # tvåvägsvalet. Det är en egenskap hos EV-kurvan, inte en påtvingad regel:
    # spelaren får skicka vidare (se test_response_meier_can_be_passed_on).
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


# -- Svar: syna, skicka eller slå (beslut 3b) -----------------------------

def test_response_offers_all_three_actions():
    # Alla tre åtgärderna måste vara nåbara. Vilken som väljs beror på profilen
    # och på slumpen, så svepet går över parametrarna i stället för att kräva
    # alla tre hos en enda agent.
    seen = set()
    for caution in (0.0, 0.5, 1.0):
        for statistics in (0.0, 0.5, 1.0):
            policy = BasePolicy(
                AgentParams(caution=caution, statistics=statistics, reading=0.0)
            )
            seen |= {policy.decide_response(bid).action for bid in rules.RANKING}
    assert seen == {"syna", "skicka", "slå"}


def test_response_can_shake_when_shaking_is_best():
    # Blindslaget blir det minsta lagliga höjningen, och då är hållarvärdet
    # bättre än att skicka vidare 31.
    calm = BasePolicy(AgentParams(unpredictability=0.0))
    assert calm.decide_response(31).action == "slå"


def test_response_meier_is_not_forced_to_call():
    # Meier synas i praktiken, men av ett skäl: att bära budet är dyrt
    # (hållarvärde −0,92 liv). Ingen regel hindrar att det skickas vidare.
    # Om hållarvärdet vore högt ska valet falla på "skicka" — det bevisar att
    # tvånget är borta och att bara EV-kurvan styr.
    class GenerousHold(BasePolicy):
        def _hold_value(self, bid: int) -> float:
            return 1.0

    assert GenerousHold(AgentParams()).decide_response(rules.MEIER).action == "skicka"
    assert BasePolicy(AgentParams()).decide_response(rules.MEIER).action == "syna"


def test_response_never_invents_a_bid(base):
    for bid in rules.RANKING:
        decision = base.decide_response(bid)
        assert decision.action in {"syna", "skicka", "slå"}
        assert decision.bid is None


def test_response_picks_the_best_available_option():
    # Slå får bara väljas när det faktiskt är bäst av de tre. Bruset stängs av
    # här: testet mäter värderingen, inte variationen.
    base = BasePolicy(AgentParams(unpredictability=0.0))
    for bid in rules.RANKING:
        decision = base.decide_response(bid)
        hold = base._hold_value(bid)
        if decision.action == "slå":
            raise_bid = base.decide_raise(bid)
            assert raise_bid.action == "slå"
            assert base._hold_value(raise_bid.bid) >= hold


# -- Tvingad höjning (beslut 4) -------------------------------------------

def test_forced_choice_is_titta_or_blint(base):
    # Vid Meier finns inget högre bud; då återstår bara att syna (motorn slår
    # annars om och startar en ny runda). För alla andra bud är valet titta/blint.
    for bid in rules.RANKING:
        if rules.is_meier(bid):
            continue
        assert base.decide_forced(bid).action in {"titta", "blint"}


def test_forced_choice_follows_unpredictability():
    import random

    calm = BasePolicy(AgentParams(unpredictability=0.0))
    assert calm.decide_forced(54).action == "titta"

    bold = BasePolicy(AgentParams(unpredictability=1.0))
    seen = {bold.decide_forced(54).action for _ in range(40)}
    assert "blint" in seen, "en oförutsägbar profil ska ibland påstå blint"


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
    for field in ("caution", "statistics", "unpredictability", "reading"):
        with pytest.raises(ValueError):
            AgentParams(**{field: 1.5})


def test_baseline_pair_share_every_parameter():
    """Axel och Berit ska bara skilja sig i om de använder LLM."""
    assert ROSTER["axel"].params == ROSTER["berit"].params
    assert ROSTER["axel"].uses_llm is False
    assert ROSTER["berit"].uses_llm is True


def test_each_variant_lifts_exactly_one_dimension():
    """Cecilia, David och Elsa ska skilja sig från baslinjen i en dimension var.

    Alla tre delar samma ``reading``, så deras inbördes jämförelse handlar bara
    om den dimension de lyfter.
    """
    base = ROSTER["axel"].params
    variants = {key: ROSTER[key].params for key in ("cecilia", "david", "elsa")}
    dimensions = ("caution", "statistics", "unpredictability")

    readings = {v.reading for v in variants.values()}
    assert readings == {0.5}, f"varianterna ska dela läsförmåga: {readings}"

    for key, params in variants.items():
        differs = {
            d for d in dimensions if getattr(params, d) != getattr(base, d)
        }
        assert len(differs) == 1, f"{key} skiljer sig i {differs}, ska vara en"
    lifted = {
        next(d for d in dimensions if getattr(p, d) != getattr(base, d))
        for p in variants.values()
    }
    assert lifted == set(dimensions), "varianterna ska lyfta olika dimensioner"


def test_axel_reads_no_opponent():
    assert ROSTER["axel"].params.reading == 0.0
    assert ROSTER["berit"].params.reading == 0.0


# -- Höjningens längd: två olika beslut, två olika regler ------------------

def test_blind_raise_is_minimum_without_unpredictability():
    """Utan oförutsägbarhet är blindslaget alltid minsta lagliga höjning.

    Spelaren ser inte tärningarna, så det minsta steget är det säkraste. Det är
    bara ``unpredictability`` som får agenten att hoppa högre.
    """
    opts = rules.higher_options(31)
    p = BasePolicy(AgentParams(unpredictability=0.0))
    assert p.decide_raise(31).bid == opts[-1]


def test_unpredictability_makes_blind_raises_vary():
    """En oförutsägbar agent ska inte alltid välja samma höjning."""
    opts = rules.higher_options(31)
    bids = set()
    for _ in range(40):
        p = BasePolicy(AgentParams(unpredictability=0.8))
        bids.add(p.decide_raise(31).bid)
    assert len(bids) > 1, "höjningen ska variera mellan anrop"
    assert bids <= set(opts), "alla höjningar ska vara lagliga"


def test_seen_bid_bluff_is_always_exactly_one_step():
    """Bluff över *sedda* tärningar är alltid exakt ett steg, oavsett profil."""
    for statistics in (0.0, 0.5, 1.0):
        p = BasePolicy(AgentParams(statistics=statistics, unpredictability=0.0))
        for shown in rules.RANKING:
            d = p.decide_bid(shown)
            if d.bid is None or d.bid == shown:
                continue
            opts = rules.higher_options(shown)
            if d.bid not in opts:
                continue
            steps = len(opts) - opts.index(d.bid)
            assert steps == 1, (
                f"statistics={statistics} visar {rules.name(shown)} bjöd {rules.name(d.bid)} "
                f"({steps} steg) — bluffen ska vara exakt ett steg"
            )
