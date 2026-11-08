"""Tester för den interaktiva sessionen (utan riktiga LLM-anrop)."""

import pytest

from majer import rules
from majer.agents.base import Role
from majer.agents.player import MajerPlayerAgent
from majer.agents.referee import RefereeAgent
from majer.session import Session


class FakeLLM:
    """LLM som alltid säger sanningen och alltid godkänner."""

    def __init__(self, bid=None):
        self.bid = bid

    def complete(self, system, user, *, json_mode=False):
        if "domare" in system.lower() or "ok" in user.lower():
            return '{"ok": true, "comment": "Godkänt."}'
        return '{"bid": %s, "line": "Jag säger så.", "reasoning": "test"}' % (self.bid or 52)


def make_player(key):
    role = Role(key=key, name=f"Spelare-{key}", description="test", style="spela")
    return MajerPlayerAgent(role=role, llm=FakeLLM())


def make_referee():
    return RefereeAgent(llm=FakeLLM(), use_llm=False)


def test_session_requires_two_players():
    with pytest.raises(ValueError):
        Session.new([make_player("a")], make_referee())


def test_session_randomizes_order_deterministically_with_seed():
    players = [make_player(k) for k in ("a", "b", "c", "d")]
    s1 = Session.new(players, make_referee(), seed=1)
    s2 = Session.new(players, make_referee(), seed=1)
    assert s1.order == s2.order
    assert sorted(s1.order) == [0, 1, 2, 3]


def test_session_starts_with_pending_dice():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players, make_referee(), seed=7)
    state = session.to_dict()
    assert state["phase"] == "awaiting_ok"
    assert state["pending"] is not None
    assert 11 <= state["pending"]["shown"] <= 66


def test_advance_logs_entry_with_dice_player_bid_and_verdict():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players, make_referee(), seed=3)
    first = session.current_player.name
    entry = session.advance()

    assert entry.player_name == first
    assert entry.bid in rules.RANKING
    assert entry.referee.ok is True
    assert len(session.log) == 1

    state = session.to_dict()
    row = state["log"][0]
    assert row["player_name"] == first
    assert "shown_name" in row and "bid_name" in row
    assert row["referee"]["ok"] is True


def test_advance_rotates_turn_and_increments_round():
    players = [make_player(k) for k in ("a", "b", "c", "d")]
    session = Session.new(players, make_referee(), seed=5)
    order = list(session.order)
    names = [session.current_player.name]
    for _ in range(3):
        session.advance()
        names.append(session.current_player.name)
    expected = [players[i].name for i in order]
    assert names == expected
    assert session.round == 1
    session.advance()  # fjärde svaret -> ny runda
    assert session.round == 2


def test_advance_requires_pending_dice_after_stop():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players, make_referee(), seed=1)
    session.stop()
    assert session.to_dict()["phase"] == "finished"
    with pytest.raises(ValueError):
        session.advance()


def test_roll_is_within_dice_range():
    for _ in range(200):
        a, b = rules.roll()
        assert 1 <= a <= 6 and 1 <= b <= 6
