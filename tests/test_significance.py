"""Test för bedömningen av vinstskillnader (chi-square mot jämn fördelning)."""

from __future__ import annotations

import pytest

from meier.significance import chi2_sf, win_difference


def test_chi2_sf_matches_the_table_values():
    """P-värdet ska stämma med chi-square-tabellen."""
    assert chi2_sf(0.0, 2) == 1.0
    assert chi2_sf(5.0, 2) == pytest.approx(0.0821, abs=1e-4)
    assert chi2_sf(3.841, 1) == pytest.approx(0.05, abs=1e-3)
    assert chi2_sf(50.0, 2) == pytest.approx(1.4e-11, rel=0.05)
    # Stort x ska ge nästan noll, inte negativt eller NaN.
    assert 0.0 <= chi2_sf(500.0, 2) < 1e-100


def test_thirty_matches_is_uncertain():
    """Exemplet ur specen: 15/10/5 vinster på 30 matcher."""
    v = win_difference([("Spelare A", 15), ("Spelare B", 10), ("Spelare C", 5)], 30)
    assert v["zone"] == "uncertain"
    assert v["p_value"] == pytest.approx(0.082, abs=1e-3)
    assert v["leaders"] == ["Spelare A"]
    assert "30 matcher" in v["text"]
    assert "3 spelare" in v["text"]
    assert "Spelare A" in v["text"]
    # Aldrig ett påstående om bevis.
    assert "bevis" not in v["text"].lower()


def test_three_hundred_matches_indicate_a_difference():
    """Samma fördelning men 300 matcher: skillnaden syns."""
    v = win_difference([("Spelare A", 150), ("Spelare B", 100), ("Spelare C", 50)], 300)
    assert v["zone"] == "likely_difference"
    assert v["p_value"] < 0.001
    assert "300 matcher" in v["text"]
    assert "3 spelare" in v["text"]
    assert "rent statistiskt" in v["text"]
    # Siffrorna står i tabellen ovanför, inte i meningen.
    assert "har vunnit" not in v["text"]
    assert "bevis" not in v["text"].lower()


def test_even_split_is_likely_random():
    v = win_difference([("Axel", 5), ("Berit", 5)], 10)
    assert v["zone"] == "likely_random"
    assert v["p_value"] == pytest.approx(1.0)
    assert "slumpen" in v["text"]


def test_two_players_with_clear_edge():
    """4/1 i chi-square med en frihetsgrad ligger precis under 0,05."""
    v = win_difference([("Axel", 60), ("Berit", 40)], 100)
    assert v["p_value"] == pytest.approx(0.0455, abs=1e-3)
    assert v["zone"] == "likely_difference"


def test_two_players_with_a_small_edge_is_uncertain():
    v = win_difference([("Axel", 14), ("Berit", 6)], 20)
    assert v["p_value"] == pytest.approx(0.0736, abs=1e-3)
    assert v["zone"] == "uncertain"


def test_too_few_matches_says_nothing_about_styles():
    v = win_difference([("Axel", 2), ("Berit", 0)], 2)
    assert v["zone"] == "insufficient_data"
    assert v["p_value"] is None
    assert "Endast 2 matcher" in v["text"]
    assert "spelstil" in v["text"]


def test_one_match_is_singular_in_the_text():
    v = win_difference([("Axel", 1), ("Berit", 0)], 1)
    assert v["zone"] == "insufficient_data"
    assert "Endast 1 match har spelats" in v["text"]


def test_shared_lead_is_named_neutrally():
    """Delad ledning ska räknas upp, inte peka ut en slumpmässig vinnare."""
    v = win_difference([("Axel", 40), ("Berit", 40), ("Cecilia", 20)], 100)
    assert v["zone"] == "likely_difference"
    assert v["leaders"] == ["Axel", "Berit"]
    assert v["text"] == (
        "Med 100 matcher spelade och 3 spelare pekar skillnaden i antal vinster rent "
        "statistiskt på att deras olika spelstilar spelar roll för vinstfördelningen."
    )


def test_matches_are_counted_from_the_wins():
    v = win_difference([("Axel", 3), ("Berit", 1)])
    assert v["matches"] == 4


def test_a_single_player_has_nothing_to_compare():
    assert win_difference([("Axel", 5)]) is None


def test_summary_carries_the_verdict(monkeypatch):
    """Seriesammanställningen ska ha med bedömningen, så fliken kan visa den."""
    from meier import match
    from tests.test_match import make_agents

    monkeypatch.setattr(match, "_new_agents", make_agents)
    recs = [r.to_dict() for r in match.run_matches(["a", "b"], 4)]
    summary = match.summarize(recs)

    v = summary["win_difference"]
    assert v["zone"] in {"insufficient_data", "likely_random", "uncertain", "likely_difference"}
    assert v["matches"] == 4
    assert v["players"] == 2
    assert sum(summary["winner_counts"].values()) == 4
