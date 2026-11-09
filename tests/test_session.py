"""Tester för den interaktiva sessionen (utan riktiga LLM-anrop)."""

import pytest

from majer import rules
from majer.agents.base import Role
from majer.agents.player import MajerPlayerAgent
from majer.agents.referee import RefereeAgent
from majer.session import Session


class ScriptedLLM:
    """LLM som svarar enligt ett manus beroende på sammanhanget.

    ``bids`` används i tur och ordning för bud (första bud och höjningar).
    ``actions`` används i tur och ordning för beslut mot ett bud.
    """

    def __init__(self, bids=None, actions=None):
        self.bids = list(bids or [])
        self.actions = list(actions or [])
        self._bid_i = 0
        self._act_i = 0

    def _next_bid(self, default):
        if self._bid_i < len(self.bids):
            v = self.bids[self._bid_i]
            self._bid_i += 1
            return v
        return default

    def complete(self, system, user, *, json_mode=False):
        if "domare" in system.lower():
            return '{"ok": true, "comment": "Godkänt."}'

        # Slag (bägaren skakas på nytt) eller vanligt bud.
        if "MÅSTE säga" in user or "utan att titta" in user:
            bid = self._next_bid(52)
            return '{"bid": %s, "line": "Jag höjer.", "reasoning": "test"}' % bid

        # Beslut mot ett bud.
        if "DITT VAL" in user:
            if self._act_i < len(self.actions):
                act = self.actions[self._act_i]
                self._act_i += 1
            else:
                act = "syna"
            if act == "slå":
                bid = self._next_bid(66)
                return (
                    '{"action": "slå", "bid": %s, "line": "Jag slår!", "reasoning": "test"}'
                    % bid
                )
            return '{"action": "%s", "line": "Jag gör så.", "reasoning": "test"}' % act

        # Första budet (tittat i smyg).
        bid = self._next_bid(52)
        return '{"bid": %s, "line": "Jag säger så.", "reasoning": "test"}' % bid


def make_player(key, llm=None):
    role = Role(key=key, name=f"Spelare-{key}", description="test", style="spela")
    return MajerPlayerAgent(role=role, llm=llm or ScriptedLLM())


def make_referee():
    return RefereeAgent(llm=ScriptedLLM(), use_llm=False)


def test_session_requires_two_players():
    with pytest.raises(ValueError):
        Session.new([make_player("a")], make_referee())


def test_session_randomizes_order_deterministically_with_seed():
    players = [make_player(k) for k in ("a", "b", "c", "d")]
    s1 = Session.new(players, make_referee(), seed=1)
    s2 = Session.new(players, make_referee(), seed=1)
    assert s1.order == s2.order
    assert sorted(s1.order) == [0, 1, 2, 3]


def test_session_starts_with_pending_roll():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players, make_referee(), seed=7)
    state = session.to_dict()
    assert state["phase"] == "awaiting_ok"
    assert state["step_kind"] == "roll"
    assert state["pending"]["kind"] == "roll"
    assert 11 <= state["pending"]["shown"] <= 66


def test_first_roll_produces_bid_then_awaits_action():
    players = [make_player(k, ScriptedLLM(bids=[44])) for k in ("a", "b")]
    session = Session.new(players, make_referee(), seed=3)
    first = session.current_player.name
    entry = session.advance()

    assert entry.player_name == first
    assert entry.action == "bud"
    assert entry.bid == 44
    assert entry.referee.ok is True

    state = session.to_dict()
    assert state["step_kind"] == "action"
    assert state["pending"]["kind"] == "action"
    assert state["pending"]["bid"] == 44
    assert state["pending"]["bidder"] == first


def test_skicka_passes_bid_and_forces_raise_with_two_players():
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["skicka"])) for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    order = session.order
    session.advance()  # första budet
    entry = session.advance()  # nästa spelare skickar vidare

    assert entry.action == "skicka"
    assert entry.bid == 44
    # Nästa aktör är budgivaren (bara två spelare) -> tvingad höjning.
    assert session.to_dict()["step_kind"] == "raise"
    assert session.current_player.name == players[order[0]].name


def test_full_loop_forces_bidder_to_raise():
    # 33 är högre än 44 i Majer-ordningen, så budgivaren kan höja till 33.
    players = [
        make_player(k, ScriptedLLM(bids=[44, 33], actions=["skicka"]))
        for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # bud 44
    session.advance()  # skicka -> tvingad höjning
    assert session.to_dict()["step_kind"] == "raise"

    entry = session.advance()  # budgivaren höjer
    assert entry.action == "höja"
    assert entry.bid == 33
    assert entry.previous_bid == 44
    assert rules.is_higher(33, 44)
    assert session.to_dict()["step_kind"] == "action"


def test_slag_logs_fresh_roll_before_action():
    # Att slå är att skaka bägaren på nytt: ett färskt slag loggas före budet.
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["slå"])) for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # bud 44
    entry = session.advance()  # nästa spelare slår
    kinds = [row["kind"] for row in session.to_dict()["log"]]
    assert kinds == ["roll", "action", "roll", "action"]
    assert entry.action == "slå"
    assert entry.blind is True


def test_referee_stops_illegal_slag_and_corrects_bid():
    # ScriptedLLM föreslår 66 när den slår, men 66 är lägre än budet 44.
    # Domaren ska stoppa budet och minsta lagliga höjning tar över.
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["slå"])) for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # bud 44
    entry = session.advance()  # slår med ett för lågt bud

    assert entry.action == "slå"
    assert entry.bid == 33  # minsta lagliga höjning över 44
    assert entry.previous_bid == 44
    assert rules.is_higher(entry.bid, entry.previous_bid)
    assert entry.corrected is True
    assert entry.referee.ok is True
    assert "stoppade" in entry.referee.comment.lower()
    # Budet som står i sessionen är det korrigerade.
    assert session.to_dict()["pending"]["bid"] == 33


def test_bid_never_decreases_when_slagging():
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["slå"])) for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # bud 44
    for _ in range(6):
        state = session.to_dict()
        if state["phase"] == "finished" or state.get("result"):
            break
        entry = session.advance()
        if entry is not None and entry.action == "slå":
            assert entry.previous_bid is not None
            assert rules.is_higher(entry.bid, entry.previous_bid)


def test_forced_raise_is_stopped_if_not_higher():
    # Budgivaren måste höja men föreslår 43, som är lägre än 44.
    players = [
        make_player(k, ScriptedLLM(bids=[44, 43], actions=["skicka"]))
        for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # bud 44
    session.advance()  # skicka -> tvingad höjning
    entry = session.advance()  # höjningen stoppas och korrigeras
    assert entry.action == "höja"
    assert rules.is_higher(entry.bid, entry.previous_bid)
    assert entry.corrected is True
    assert entry.referee.ok is True


def test_out_player_is_skipped_in_turn_order():
    players = [make_player(k) for k in ("a", "b", "c")]
    session = Session.new(players, make_referee(), seed=1)
    session.order = [0, 1, 2]
    session.lives = [3, 0, 3]  # spelare 1 är ute
    assert session._next_actor(0) == 2
    assert session._previous_active(0) == 2
    assert session._previous_active(2) == 0


def test_new_round_starts_with_previous_active_before_loser():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b", "c")
    ]
    session = Session.new(players, make_referee(), seed=5)
    session.order = [0, 1, 2]
    session.advance()  # a bjuder 66
    session.advance()  # b synar -> någon tappar ett liv

    result = session.result
    assert result is not None
    loser_idx = next(i for i, p in enumerate(players) if p.name == result.loser)
    expected = session._previous_active(loser_idx)
    # Nästa runda börjar hos spelaren före den som förlorade livet.
    assert session.actor == expected
    last = session.to_dict()["log"][-1]
    assert last["kind"] == "roll"
    assert last["player_name"] == players[expected].name


def test_lives_never_go_negative_on_mejer_call():
    # Mejer kostar två liv. Med bara ett liv kvar får livet aldrig bli negativt.
    players = [
        make_player(k, ScriptedLLM(bids=[21], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3, lives=1)
    session.advance()  # bud Mejer
    session.advance()  # syn -> två livs kostnad, men bara ett finns
    assert all(lives >= 0 for lives in session.lives)
    assert session.to_dict()["phase"] == "finished"


def test_call_resolves_lives_and_result():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # bud
    entry = session.advance()  # syn

    assert entry.action == "syna"
    assert session.result is not None
    result = session.result
    assert result.bid == 66

    # Utfallet ska följa reglerna för en syn.
    expected = rules.resolve_call(result.bid, result.shown)
    assert result.caller_loses == expected.caller_loses
    assert result.lives == expected.lives
    assert result.loser == (result.caller if expected.caller_loses else result.bidder)

    state = session.to_dict()
    assert state["result"]["bid"] == 66
    total = sum(p["lives"] for p in state["order"])
    assert total == 6 - result.lives


def test_mejer_call_costs_two_lives():
    players = [
        make_player(k, ScriptedLLM(bids=[21], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # bud Mejer
    session.advance()  # syn
    assert session.result is not None
    assert session.result.lives == 2


def test_run_to_call_reaches_a_call():
    players = [
        make_player(
            k, ScriptedLLM(bids=[11, 22, 33, 44], actions=["skicka", "skicka", "syna"])
        )
        for k in ("a", "b", "c", "d")
    ]
    session = Session.new(players, make_referee(), seed=11)
    created = session.run_to_call()
    assert session.result is not None
    assert any(e.action == "syna" for e in created)


def test_session_finishes_when_one_player_left():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3, lives=1)
    session.advance()  # bud
    session.advance()  # syn -> någon tappar sitt enda liv
    assert session.finished is True
    assert session.to_dict()["phase"] == "finished"


def test_advance_requires_step_after_stop():
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


# -- Kontrakt mot frontend: fälten måste alltid finnas ----------------------
# Buggen "undefined" i webbappen kom från att dessa fält saknades i vissa steg.


def test_order_entries_always_have_lives():
    players = [make_player(k) for k in ("a", "b", "c", "d")]
    session = Session.new(players, make_referee(), seed=2)
    for p in session.to_dict()["order"]:
        assert "lives" in p and isinstance(p["lives"], int)
        assert p["name"] and p["role"]


def test_roll_step_pending_has_dice_and_shown():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players, make_referee(), seed=4)
    state = session.to_dict()
    assert state["step_kind"] == "roll"
    pending = state["pending"]
    assert pending["kind"] == "roll"
    assert isinstance(pending["dice"], list) and len(pending["dice"]) == 2
    assert isinstance(pending["shown"], int)
    assert pending["shown_name"]


def test_action_step_pending_has_bid_bidder_and_dice():
    players = [make_player(k, ScriptedLLM(bids=[44])) for k in ("a", "b")]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # första budet -> action-steg
    state = session.to_dict()
    assert state["step_kind"] == "action"
    pending = state["pending"]
    # Både budet och tärningarna måste finnas: budet är indata till beslutet.
    assert pending["bid"] == 44
    assert pending["bid_name"]
    assert pending["bidder"] == players[session.bidder].name
    assert isinstance(pending["dice"], list) and len(pending["dice"]) == 2
    assert pending["shown_name"]


def test_raise_step_pending_has_bid_and_dice():
    players = [
        make_player(k, ScriptedLLM(bids=[44, 33], actions=["skicka"]))
        for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # bud 44
    session.advance()  # skicka -> tvingad höjning
    state = session.to_dict()
    assert state["step_kind"] == "raise"
    pending = state["pending"]
    assert pending["bid"] == 44
    assert pending["bid_name"]
    assert isinstance(pending["dice"], list) and len(pending["dice"]) == 2


def test_log_starts_with_roll_entry_before_any_bid():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players, make_referee(), seed=4)
    log = session.to_dict()["log"]
    assert len(log) == 1
    assert log[0]["kind"] == "roll"
    assert log[0]["shown_name"]
    # Ännu inget bud i loggen.
    assert all(row["kind"] == "roll" for row in log)


def test_new_round_logs_a_fresh_roll_entry():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, make_referee(), seed=3)
    session.advance()  # bud
    session.advance()  # syn -> ny runda, nytt tärningsutfall
    kinds = [row["kind"] for row in session.to_dict()["log"]]
    # roll, action(bud), action(syna), roll(ny runda)
    assert kinds == ["roll", "action", "action", "roll"]


def test_run_to_call_log_is_ordered_downward():
    players = [
        make_player(
            k, ScriptedLLM(bids=[11, 22, 33, 44], actions=["skicka", "skicka", "syna"])
        )
        for k in ("a", "b", "c", "d")
    ]
    session = Session.new(players, make_referee(), seed=11)
    session.run_to_call()
    log = session.to_dict()["log"]
    rounds = [row["round"] for row in log]
    # Rundnumret får aldrig gå bakåt: loggen byggs nedåt.
    assert rounds == sorted(rounds)
    # Varje action följer efter ett tärningsutfall.
    assert log[0]["kind"] == "roll"


def test_log_entries_always_have_frontend_fields():
    players = [
        make_player(
            k, ScriptedLLM(bids=[11, 22, 33, 44], actions=["skicka", "skicka", "syna"])
        )
        for k in ("a", "b", "c", "d")
    ]
    session = Session.new(players, make_referee(), seed=11)
    session.run_to_call()
    log = session.to_dict()["log"]
    # Loggen byggs nedåt: tärningsutfallet kommer före budet på det.
    kinds = [row["kind"] for row in log]
    assert kinds[0] == "roll"
    assert kinds[1] == "action"
    for row in log:
        for key in ("kind", "round", "dice", "shown", "shown_name"):
            assert key in row, f"loggposten saknar {key}"
        assert len(row["dice"]) == 2

    for row in log:
        if row["kind"] == "roll":
            # Tärningsutfallet är ren indata: inget bud, ingen domare.
            assert row["player_name"]
            assert row["bid"] is None
            assert row["referee"] is None
        else:
            assert row["player_name"]
            assert row["action"]
            assert row["referee"] is not None and "ok" in row["referee"]
