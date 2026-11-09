"""Tester för Mejer-reglerna."""

import pytest

from mejer import rules


def test_read_dice_high_first():
    assert rules.read_dice(2, 5) == 52
    assert rules.read_dice(5, 2) == 52
    assert rules.read_dice(2, 1) == 21
    assert rules.read_dice(1, 1) == 11


def test_read_dice_rejects_out_of_range():
    with pytest.raises(ValueError):
        rules.read_dice(0, 3)
    with pytest.raises(ValueError):
        rules.read_dice(7, 3)


def test_ranking_has_21_outcomes_and_mejer_first():
    assert len(rules.RANKING) == 21
    assert len(set(rules.RANKING)) == 21
    assert rules.RANKING[0] == rules.MEJER == 21
    assert rules.RANKING[-1] == 31


def test_ranking_matches_rule_table():
    expected = [
        21, 11, 22, 33, 44, 55, 66, 65, 64, 63, 62,
        61, 54, 53, 52, 51, 43, 42, 41, 32, 31,
    ]
    assert list(rules.RANKING) == expected


def test_rank_and_compare():
    assert rules.rank(21) == 0
    assert rules.rank(31) == 20
    assert rules.compare(21, 31) == 1  # 21 är högre
    assert rules.compare(31, 21) == -1
    assert rules.compare(52, 52) == 0
    assert rules.is_higher(65, 62)
    assert not rules.is_higher(62, 65)


def test_dice_from_value_roundtrip():
    for value in rules.RANKING:
        hi, lo = rules.dice_from_value(value)
        assert rules.read_dice(hi, lo) == value


def test_next_higher():
    assert rules.next_higher(31) == 32
    assert rules.next_higher(11) == 21
    assert rules.next_higher(21) is None


def test_higher_options():
    opts = rules.higher_options(62)
    assert opts == [21, 11, 22, 33, 44, 55, 66, 65, 64, 63]
    assert rules.higher_options(21) == []


def test_resolve_call_bidder_loses_when_shown_lower():
    # Bud 65, tärningarna visar 62 (lägre) -> budgivaren förlorar ett liv.
    result = rules.resolve_call(bid=65, shown=62)
    assert result.caller_loses is False
    assert result.lives == 1


def test_resolve_call_caller_loses_when_shown_equal_or_higher():
    # Bud 62, tärningarna visar 65 (högre) -> den som synade förlorar.
    result = rules.resolve_call(bid=62, shown=65)
    assert result.caller_loses is True
    assert result.lives == 1

    # Samma värde -> den som synade förlorar.
    result = rules.resolve_call(bid=52, shown=52)
    assert result.caller_loses is True
    assert result.lives == 1


def test_mejer_costs_double_as_bid():
    result = rules.resolve_call(bid=21, shown=11)
    assert result.lives == 2
    assert result.caller_loses is False  # visar lägre -> budgivaren förlorar


def test_mejer_costs_double_when_shown():
    # Bud 66 men tärningarna visar Mejer -> den som synade förlorar två liv.
    result = rules.resolve_call(bid=66, shown=21)
    assert result.caller_loses is True
    assert result.lives == 2


def test_resolve_call_rejects_invalid():
    with pytest.raises(ValueError):
        rules.resolve_call(bid=99, shown=11)
    with pytest.raises(ValueError):
        rules.resolve_call(bid=11, shown=99)


def test_name_mejer():
    assert "Mejer" in rules.name(21)
    assert rules.name(52) == "52"
