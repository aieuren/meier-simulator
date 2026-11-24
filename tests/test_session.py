"""Tester för den interaktiva sessionen (utan riktiga LLM-anrop)."""

import random

import pytest

from meier import match, rules
from meier.agents.base import Role
from meier.agents.player import MeierPlayerAgent
from meier.session import Session


class _FixedRoll(random.Random):
    """RNG som alltid slår ett bestämt tärningspar.

    ``Session.rng`` används både för att blanda ordningen och för att slå
    tärningarna. Den här ger samma par varje gång, så ett test som handlar om
    *att* tärningarna slås om inte faller på att de råkade bli lika.
    """

    def __init__(self, pair):
        super().__init__()
        self._pair = pair

    def choices(self, population, weights=None, *, cum_weights=None, k=1):
        return [self._pair[i % 2] for i in range(k)]


class ScriptedLLM:
    """LLM som svarar enligt ett manus beroende på sammanhanget.

    ``bids`` används i tur och ordning för påståenden (första påståendet och höjningar).
    ``actions`` används i tur och ordning för beslut mot ett påstående.
    """

    def __init__(self, bids=None, actions=None, unseen=False, seen=True):
        self.bids = list(bids or [])
        self.actions = list(actions or [])
        self.unseen = unseen
        self.seen = seen
        self._bid_i = 0
        self._act_i = 0

    def _next_bid(self, default):
        if self._bid_i < len(self.bids):
            v = self.bids[self._bid_i]
            self._bid_i += 1
            return v
        return default

    def complete(self, system, user, *, json_mode=False):
        # Tvingad höjning: spelaren väljer att titta eller bjuda utan att titta.
        if "helt varv" in user and "TITTA ELLER INTE TITTA" in user:
            return (
                '{"unseen": %s, "line": "Jag höjer.", "reasoning": "test"}'
                % ("true" if self.unseen else "false")
            )

        # Slag: spelaren väljer först om den vill titta på sina egna tärningar.
        if "SLAG – TITTA ELLER INTE TITTA" in user:
            return (
                '{"seen": %s, "reasoning": "test"}'
                % ("true" if self.seen else "false")
            )

        # Påstående (efter titt) eller slag utan att titta.
        if "MÅSTE säga" in user or "utan att titta" in user:
            bid = self._next_bid(52)
            return '{"bid": %s, "line": "Jag höjer.", "reasoning": "test"}' % bid

        # Beslut mot ett påstående.
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

        # Första påståendet (tittat i smyg).
        bid = self._next_bid(52)
        return '{"bid": %s, "line": "Jag säger så.", "reasoning": "test"}' % bid


def make_player(key, llm=None):
    role = Role(key=key, name=f"Spelare-{key}", description="test", style="spela")
    return MeierPlayerAgent(role=role, llm=llm or ScriptedLLM())


def test_session_requires_two_players():
    with pytest.raises(ValueError):
        Session.new([make_player("a")])


def test_session_shuffles_the_order():
    """Ordningen ska slumpas, och varje spelare ska vara med exakt en gång."""
    players = [make_player(k) for k in ("a", "b", "c", "d")]
    session = Session.new(players)
    assert sorted(session.order) == [0, 1, 2, 3]
    # Över många sessioner ska ordningen variera — annars är den inte slumpad.
    orders = {tuple(Session.new(players).order) for _ in range(40)}
    assert len(orders) > 1


def test_session_starts_with_pending_roll():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players)
    state = session.to_dict()
    assert state["phase"] == "awaiting_ok"
    assert state["step_kind"] == "roll"
    assert state["pending"]["kind"] == "roll"
    assert 11 <= state["pending"]["shown"] <= 66


def test_first_roll_produces_bid_then_awaits_action():
    players = [make_player(k, ScriptedLLM(bids=[44])) for k in ("a", "b")]
    session = Session.new(players)
    first = session.current_player.name
    entry = session.advance()

    assert entry.player_name == first
    assert entry.action == "bud"
    assert entry.bid == 44

    state = session.to_dict()
    assert state["step_kind"] == "action"
    assert state["pending"]["kind"] == "action"
    assert state["pending"]["bid"] == 44
    assert state["pending"]["bidder"] == first


def test_session_dict_reports_order_and_starter():
    players = [make_player(k) for k in ("a", "b", "c", "d")]
    session = Session.new(players)
    state = session.to_dict()
    assert [p["name"] for p in state["order"]] == [
        players[i].name for i in session.order
    ]
    # Den som börjar är den första i ordningen.
    assert state["starter"] == players[session.order[0]].name


def test_skicka_logs_accepted_bid_and_keeps_same_bid():
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["skicka"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    entry = session.advance()  # skickar vidare

    assert entry.action == "skicka"
    # Påståendet spelaren svarar på, och det är oförändrat efter ett skickande.
    assert entry.accepted_bid == 44
    assert entry.bid == 44
    assert entry.to_dict()["accepted_bid_name"] == "44"


def test_slag_logs_accepted_bid_and_new_bid_separately():
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["slå"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    entry = session.advance()  # slår över 44 med ett nytt påstående

    assert entry.action == "slå"
    # Påståendet spelaren svarar på är 44; det nya (sagda) påståendet är högre.
    assert entry.accepted_bid == 44
    assert entry.bid != entry.accepted_bid
    assert rules.is_higher(entry.bid, entry.accepted_bid)


def test_syna_logs_accepted_bid():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 66
    entry = session.advance()  # synar påståendet

    assert entry.action == "syna"
    assert entry.accepted_bid == 66
    assert entry.to_dict()["accepted_bid_name"] == "66"


def test_syna_keeps_the_callers_reasoning():
    # Synen är spelarens mest avgörande beslut – motiveringen måste bevaras.
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 66
    entry = session.advance()  # synar påståendet

    assert entry.action == "syna"
    assert entry.reasoning == "test"
    # Repliken byggs lokalt ur draget; modellens egen "line" används aldrig.
    assert entry.line == "Jag synar 66."
    # Samma motivering finns i synresultatet (som frontend visar).
    assert session.result is not None
    assert session.result.reasoning == "test"
    assert session.to_dict()["result"]["reasoning"] == "test"


def test_skicka_passes_bid_and_forces_raise_with_two_players():
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["skicka"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    order = session.order
    session.advance()  # första påståendet
    entry = session.advance()  # nästa spelare skickar vidare

    assert entry.action == "skicka"
    assert entry.bid == 44
    # Nästa aktör är hållaren (bara två spelare) -> tvingad höjning.
    assert session.to_dict()["step_kind"] == "raise"
    assert session.current_player.name == players[order[0]].name


def test_full_loop_forces_bidder_to_raise():
    # 33 är högre än 44 i Meier-ordningen, så hållaren kan höja till 33.
    players = [
        make_player(k, ScriptedLLM(bids=[44, 33], actions=["skicka"]))
        for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    session.advance()  # skicka -> tvingad höjning
    assert session.to_dict()["step_kind"] == "raise"

    entry = session.advance()  # hållaren höjer
    assert entry.action == "höja"
    assert entry.bid == 33
    assert entry.previous_bid == 44
    assert rules.is_higher(33, 44)
    assert session.to_dict()["step_kind"] == "action"


def test_forced_raise_rerolls_the_dice():
    # När bägaren gått ett helt varv slås tärningarna om: en ny "roll"-rad
    # loggas och pending_dice uppdateras till det nya slaget.
    players = [
        make_player(k, ScriptedLLM(bids=[44, 33], actions=["skicka"]))
        for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    old_dice = session.pending_dice

    # Omslaget kan annars råka ge samma utfall som förra slaget (1 chans på 21),
    # och då faller testet av ett skäl som inte har med saken att göra. Styr
    # slaget till ett par som skiljer sig från det gamla.
    other = next(
        pair for pair in ((1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6))
        if rules.read_dice(*pair) != rules.read_dice(*old_dice)
    )
    session.rng = _FixedRoll(other)

    session.advance()  # skicka -> tvingad höjning
    entry = session.advance()  # höjning: tärningarna slås om

    kinds = [row["kind"] for row in session.to_dict()["log"]]
    # roll, action(påstående), action(skicka), roll(omslag), action(höja)
    assert kinds == ["roll", "action", "action", "roll", "action"]
    assert entry.dice == session.pending_dice
    assert session.pending_dice != old_dice
    # En senare syn ska döma mot de omslagna tärningarna.
    assert session.to_dict()["pending"]["dice"] == list(entry.dice)


def test_forced_raise_can_be_unseen():
    # Hållaren får själv välja att bjuda utan att titta på de omslagna tärningarna.
    players = [
        make_player(k, ScriptedLLM(bids=[44, 33], actions=["skicka"], unseen=True))
        for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    session.advance()  # skicka -> tvingad höjning
    entry = session.advance()  # höjning, utan att titta

    assert entry.action == "höja"
    assert entry.unseen is True
    stats = match._player_stats(session.log, [p.name for p in players])
    # Höjningsbudet utan att titta räknas som "unseen", inte som bluff eller sanning.
    assert stats[entry.player_name]["unseen"] == 1
    assert stats[entry.player_name]["bids"] == 2
    assert stats[entry.player_name]["bluffs"] + stats[entry.player_name]["truths"] == 1


def test_forced_raise_keeps_the_look_or_unseen_reasoning():
    # Vid tvingad höjning väljer spelaren att titta eller bjuda utan att titta.
    # Motiveringen för *det valet* ska bevaras på höjningsraden.
    players = [
        make_player(k, ScriptedLLM(bids=[44, 33], actions=["skicka"], unseen=True))
        for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    session.advance()  # skicka -> tvingad höjning
    entry = session.advance()  # höjning, utan att titta

    assert entry.action == "höja"
    assert entry.unseen is True
    assert entry.choice_reasoning == "test"
    # Repliken beskriver valet och byggs lokalt; motiveringen kommer från modellen.
    assert entry.choice_line == "Jag påstår utan att titta."
    assert entry.to_dict()["choice_reasoning"] == "test"


def test_slag_logs_fresh_roll_before_action():
    # Att slå är att skaka bägaren på nytt: ett färskt slag loggas före påståendet.
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["slå"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    entry = session.advance()  # nästa spelare slår
    kinds = [row["kind"] for row in session.to_dict()["log"]]
    assert kinds == ["roll", "action", "roll", "action"]
    assert entry.action == "slå"
    # Att titta är det normala vid ett slag: spelaren ser sina nya tärningar.
    assert entry.unseen is False
    assert entry.choice_line == "Jag tittar på tärningarna."


def test_slag_after_a_look_is_a_truth_or_bluff_claim():
    # Den som tittar på sitt eget slag gör ett medvetet påstående: det räknas
    # som sanning eller bluff, precis som ett vanligt påstående.
    players = [
        make_player(k, ScriptedLLM(bids=[44, 31], actions=["slå"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    entry = session.advance()  # nästa spelare slår och tittar

    assert entry.action == "slå"
    assert entry.unseen is False
    # Spelaren såg tärningarna, så påståendet är ett medvetet löfte: antingen
    # sant eller en bluff, aldrig "unseen".
    assert entry.to_dict()["lie"] is (not entry.truth)

    stats = match._player_stats(session.log, [p.name for p in players])
    slagger = stats[entry.player_name]
    assert slagger["unseen"] == 0
    assert slagger["truths"] + slagger["bluffs"] == 1


def test_unseen_slag_is_still_possible_and_not_counted_as_bluff():
    # Fintaktiken finns kvar: spelaren kan välja bort titten. Då såg den inte
    # tärningarna, och påståendet är inget medvetet löfte. Det räknas som
    # "unseen", inte som bluff eller sanning.
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["slå"], seen=False))
        for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44 (spelaren tittade)
    entry = session.advance()  # nästa spelare slår utan att titta

    assert entry.action == "slå"
    assert entry.unseen is True

    stats = match._player_stats(session.log, [p.name for p in players])
    slagger = stats[entry.player_name]
    assert slagger["unseen"] == 1
    assert slagger["bluffs"] == 0
    assert slagger["truths"] == 0


def test_unseen_flag_is_serialized():
    # Den som väljer bort titten får flaggan i protokollet.
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["slå"], seen=False))
        for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()
    session.advance()

    row = next(r for r in session.to_dict()["log"] if r["action"] == "slå")
    assert row["unseen"] is True


def test_illegal_slag_is_corrected_to_smallest_legal_raise():
    # Utan att titta får spelaren ingen hjälp av tärningarna. Föreslår modellen
    # 66 när påståendet är 44 är budet för lågt; det rättas till minsta lagliga höjning.
    players = [
        make_player(k, ScriptedLLM(bids=[44, 66], actions=["slå"], seen=False))
        for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    entry = session.advance()  # slår med ett för lågt påstående

    assert entry.action == "slå"
    assert entry.bid == 33  # minsta lagliga höjning över 44
    assert entry.previous_bid == 44
    assert rules.is_higher(entry.bid, entry.previous_bid)
    assert entry.corrected is True
    # Påståendet som står i sessionen är det korrigerade.
    assert session.to_dict()["pending"]["bid"] == 33


def test_bid_never_decreases_when_slagging():
    players = [
        make_player(k, ScriptedLLM(bids=[44], actions=["slå"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    for _ in range(6):
        state = session.to_dict()
        if state["phase"] == "finished" or state.get("result"):
            break
        entry = session.advance()
        if entry is not None and entry.action == "slå":
            assert entry.previous_bid is not None
            assert rules.is_higher(entry.bid, entry.previous_bid)


def test_forced_raise_is_stopped_if_not_higher():
    # Hållaren måste höja men föreslår 43, som är lägre än 44.
    players = [
        make_player(k, ScriptedLLM(bids=[44, 43], actions=["skicka"]))
        for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående 44
    session.advance()  # skicka -> tvingad höjning
    entry = session.advance()  # höjningen rättas till minsta lagliga höjning
    assert entry.action == "höja"
    assert rules.is_higher(entry.bid, entry.previous_bid)
    assert entry.corrected is True


def test_out_player_is_skipped_in_turn_order():
    players = [make_player(k) for k in ("a", "b", "c")]
    session = Session.new(players)
    session.order = [0, 1, 2]
    session.lives = [3, 0, 3]  # spelare 1 är ute
    assert session._next_actor(0) == 2
    assert session._previous_active(0) == 2
    assert session._previous_active(2) == 0


def test_new_round_starts_with_previous_active_before_loser():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b", "c")
    ]
    session = Session.new(players)
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


def test_lives_never_go_negative_on_meier_call():
    # Meier kostar två liv. Med bara ett liv kvar får livet aldrig bli negativt.
    players = [
        make_player(k, ScriptedLLM(bids=[21], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, lives=1)
    session.advance()  # påstående Meier
    session.advance()  # syn -> två livs kostnad, men bara ett finns
    assert all(lives >= 0 for lives in session.lives)
    assert session.to_dict()["phase"] == "finished"


def test_call_resolves_lives_and_result():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående
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

    # Syn-raden bär med sig vem som ansvarade för påståendet (för loggen).
    call_row = next(r for r in state["log"] if r["action"] == "syna")
    assert call_row["holder_name"] == result.holder


def test_meier_call_costs_two_lives():
    players = [
        make_player(k, ScriptedLLM(bids=[21], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående Meier
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
    session = Session.new(players)
    created = session.run_to_call()
    assert session.result is not None
    assert any(e.action == "syna" for e in created)


def test_run_to_round_end_stops_after_a_call():
    players = [
        make_player(k, ScriptedLLM(bids=[11], actions=["syna"])) for k in ("a", "b", "c", "d")
    ]
    session = Session.new(players)
    start_round = session.round
    created = session.run_to_round_end()
    # Synen avslutar rundan och en ny runda har börjat.
    assert any(e.action == "syna" for e in created)
    assert session.round == start_round + 1


def test_run_to_round_end_starts_a_new_round_with_a_roll():
    players = [
        make_player(k, ScriptedLLM(bids=[11], actions=["syna"])) for k in ("a", "b", "c", "d")
    ]
    session = Session.new(players)
    session.run_to_round_end()
    assert session.step_kind == "roll"
    assert session.to_dict()["log"][-1]["kind"] == "roll"


def test_run_to_end_finishes_the_whole_match():
    players = [
        make_player(k, ScriptedLLM(bids=[11], actions=["syna"])) for k in ("a", "b", "c", "d")
    ]
    session = Session.new(players, lives=1)
    created = session.run_to_end()
    assert session.finished is True
    assert session.to_dict()["phase"] == "finished"
    # Flera rundor spelades, och en vinnare står kvar.
    assert any(e.action == "syna" for e in created)
    state = session.to_dict()
    assert len([p for p in state["order"] if p["lives"] > 0]) == 1


def test_session_finishes_when_one_player_left():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, lives=1)
    session.advance()  # påstående
    session.advance()  # syn -> någon tappar sitt enda liv
    assert session.finished is True
    assert session.to_dict()["phase"] == "finished"


def test_advance_requires_step_after_stop():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players)
    session.stop()
    assert session.to_dict()["phase"] == "finished"
    with pytest.raises(ValueError):
        session.advance()


def test_roll_is_within_dice_range():
    for _ in range(200):
        a, b = rules.roll()
        assert 1 <= a <= 6 and 1 <= b <= 6


def test_roll_favours_the_long_faces():
    # Avlång tärning: sidorna 3-6 (långytorna) ska komma oftare än 1 och 2.
    rng = random.Random(1234)
    counts = {n: 0 for n in range(1, 7)}
    for _ in range(20000):
        for d in rules.roll(rng):
            counts[d] += 1
    low = counts[1] + counts[2]
    high = counts[3] + counts[4] + counts[5] + counts[6]
    # Jämför mot de vikter koden faktiskt använder, så att testet inte låser
    # en viss modell: (low/2) / (high/4) ska ligga nära w_änd / w_lång.
    expected = rules.FACE_WEIGHTS[0] / rules.FACE_WEIGHTS[2]
    assert high > low
    assert abs((low / 2) / (high / 4) - expected) < 0.02


def test_roll_keeps_odd_and_even_equally_likely():
    # 1 och 2 ligger på ändytorna (en udda, en jämn), 3-6 på långytorna
    # (två udda, två jämna). Därför ska udda och jämn vara lika vanliga.
    rng = random.Random(99)
    odd = even = 0
    for _ in range(20000):
        for d in rules.roll(rng):
            if d % 2:
                odd += 1
            else:
                even += 1
    assert abs(odd - even) / (odd + even) < 0.02


def test_face_weights_sum_and_shape():
    assert len(rules.FACE_WEIGHTS) == 6
    assert rules.FACE_WEIGHTS[0] == rules.FACE_WEIGHTS[1]
    assert rules.FACE_WEIGHTS[2] == rules.FACE_WEIGHTS[5]
    # Vikterna är normaliserade sannolikheter, inte råa vikter.
    assert abs(sum(rules.FACE_WEIGHTS) - 1.0) < 1e-12
    assert rules.FACE_WEIGHTS[2] > rules.FACE_WEIGHTS[0]


# -- Kontrakt mot frontend: fälten måste alltid finnas ----------------------
# Buggen "undefined" i webbappen kom från att dessa fält saknades i vissa steg.


def test_order_entries_always_have_lives():
    players = [make_player(k) for k in ("a", "b", "c", "d")]
    session = Session.new(players)
    for p in session.to_dict()["order"]:
        assert "lives" in p and isinstance(p["lives"], int)
        assert p["name"] and p["role"]


def test_roll_step_pending_has_dice_and_shown():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players)
    state = session.to_dict()
    assert state["step_kind"] == "roll"
    pending = state["pending"]
    assert pending["kind"] == "roll"
    assert isinstance(pending["dice"], list) and len(pending["dice"]) == 2
    assert isinstance(pending["shown"], int)
    assert pending["shown_name"]


def test_action_step_pending_has_bid_bidder_and_dice():
    players = [make_player(k, ScriptedLLM(bids=[44])) for k in ("a", "b")]
    session = Session.new(players)
    session.advance()  # första påståendet -> action-steg
    state = session.to_dict()
    assert state["step_kind"] == "action"
    pending = state["pending"]
    # Både påståendet och tärningarna måste finnas: påståendet är indata till beslutet.
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
    session = Session.new(players)
    session.advance()  # påstående 44
    session.advance()  # skicka -> tvingad höjning
    state = session.to_dict()
    assert state["step_kind"] == "raise"
    pending = state["pending"]
    assert pending["bid"] == 44
    assert pending["bid_name"]
    assert isinstance(pending["dice"], list) and len(pending["dice"]) == 2


def test_log_starts_with_roll_entry_before_any_bid():
    players = [make_player(k) for k in ("a", "b")]
    session = Session.new(players)
    log = session.to_dict()["log"]
    assert len(log) == 1
    assert log[0]["kind"] == "roll"
    assert log[0]["shown_name"]
    # Ännu inget påstående i loggen.
    assert all(row["kind"] == "roll" for row in log)


def test_new_round_logs_a_fresh_roll_entry():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players)
    session.advance()  # påstående
    session.advance()  # syn -> livsrad, ny runda, nytt tärningsutfall
    kinds = [row["kind"] for row in session.to_dict()["log"]]
    # roll, action(påstående), action(syna), life(förlorat liv), roll(ny runda)
    assert kinds == ["roll", "action", "action", "life", "roll"]


def test_run_to_call_log_is_ordered_downward():
    players = [
        make_player(
            k, ScriptedLLM(bids=[11, 22, 33, 44], actions=["skicka", "skicka", "syna"])
        )
        for k in ("a", "b", "c", "d")
    ]
    session = Session.new(players)
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
    session = Session.new(players)
    session.run_to_call()
    log = session.to_dict()["log"]
    # Loggen byggs nedåt: tärningsutfallet kommer före påståendet på det.
    kinds = [row["kind"] for row in log]
    assert kinds[0] == "roll"
    assert kinds[1] == "action"
    for row in log:
        for key in ("kind", "round", "dice", "shown", "shown_name"):
            assert key in row, f"loggposten saknar {key}"
        assert len(row["dice"]) == 2

    for row in log:
        if row["kind"] == "roll":
            # Tärningsutfallet är ren indata: inget påstående.
            assert row["player_name"]
            assert row["bid"] is None
        elif row["kind"] == "life":
            # Livsraden: vem som förlorade och hur många liv som är kvar.
            assert row["player_name"]
            assert row["lives_lost"] >= 1
            assert row["lives_left"] is not None
        else:
            assert row["player_name"]
            assert row["action"]


def _session_with_state(order, lives=(3, 3, 3, 3)):
    players = [make_player(k, ScriptedLLM()) for k in "abcd"]
    session = Session.new(players)
    session.order = list(order)
    session.lives = list(lives)
    session.log.clear()
    return session, players


def test_pass_moves_call_responsibility_to_the_passer():
    # A sätter påståendet, B och C skickar vidare, D synar. Tärningarna visar lägre
    # än påståendet, så den som ansvarar för påståendet förlorar – och det är C, som
    # skickade vidare sist, inte A som satte påståendet från början.
    session, players = _session_with_state([0, 1, 2, 3])
    session.pending_bid = 52
    session.pending_dice = (3, 1)  # visar 31, lägre än 52
    session.bidder = 0
    session.holder = 2  # C skickade vidare sist
    session.actor = 3  # D synar

    session._resolve_call(players[3])

    result = session.result
    assert result.caller_loses is False
    assert result.holder == players[2].name
    assert result.bidder == players[0].name
    assert result.loser == players[2].name
    assert session.lives[2] == 2
    assert session.lives[0] == 3


def test_caller_loses_when_dice_are_high_enough():
    # Påståendet är lågt men tärningarna visar högre: den som synade förlorar.
    session, players = _session_with_state([0, 1, 2, 3])
    session.pending_bid = 31
    session.pending_dice = (5, 2)  # visar 52, högre än 31
    session.bidder = 1
    session.holder = 1
    session.actor = 3

    session._resolve_call(players[3])

    result = session.result
    assert result.caller_loses is True
    assert result.loser == players[3].name
    assert session.lives[3] == 2
    assert session.lives[1] == 3


def test_life_loss_is_logged_as_its_own_row():
    session, players = _session_with_state([0, 1, 2, 3])
    session.pending_bid = 52
    session.pending_dice = (3, 1)
    session.bidder = 0
    session.holder = 0
    session.actor = 3

    session._resolve_call(players[3])

    life_rows = [row for row in session.to_dict()["log"] if row["kind"] == "life"]
    assert len(life_rows) == 1
    row = life_rows[0]
    assert row["player_name"] == players[0].name
    assert row["lives_lost"] == 1
    assert row["lives_left"] == 2
    # Livsraden ligger direkt efter synen.
    kinds = [r["kind"] for r in session.to_dict()["log"]]
    assert kinds.index("life") == kinds.index("action") + 1


def test_meier_call_logs_two_lives_lost():
    session, players = _session_with_state([0, 1])
    session.pending_bid = 21  # Meier
    session.pending_dice = (2, 1)  # visar Meier
    session.bidder = 0
    session.holder = 0
    session.actor = 1

    session._resolve_call(players[1])

    life_rows = [row for row in session.to_dict()["log"] if row["kind"] == "life"]
    assert len(life_rows) == 1
    assert life_rows[0]["lives_lost"] == 2
    assert life_rows[0]["lives_left"] == 1


# -- Livsställning och vinnarrad i loggen ----------------------------------


def test_standings_lists_all_players_in_order():
    players = [make_player(k) for k in ("a", "b", "c", "d")]
    session = Session.new(players, lives=3)
    standings = session.to_dict()["standings"]
    assert [p["name"] for p in standings] == [
        session.name_of(i) for i in session.order
    ]
    assert all(p["lives"] == 3 and p["active"] is True for p in standings)


def test_standings_reflect_lives_after_a_call():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b", "c")
    ]
    session = Session.new(players, lives=3)
    session.advance()  # påstående
    session.advance()  # syn -> någon tappar ett liv
    standings = {p["name"]: p for p in session.to_dict()["standings"]}
    total = sum(p["lives"] for p in standings.values())
    assert total == 9 - session.result.lives
    # Den som förlorade livet syns med färre liv kvar.
    loser = standings[session.result.loser]
    assert loser["lives"] == 3 - session.result.lives
    assert loser["active"] is True


def test_standings_marks_eliminated_player_inactive():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, lives=1)
    session.advance()  # påstående
    session.advance()  # syn -> någon är ute
    standings = {p["name"]: p for p in session.to_dict()["standings"]}
    out = [p for p in standings.values() if not p["active"]]
    assert len(out) == 1 and out[0]["lives"] == 0


def test_winner_is_none_while_match_runs():
    players = [make_player(k) for k in ("a", "b", "c", "d")]
    session = Session.new(players)
    assert session.to_dict()["winner"] is None


def test_finished_match_logs_a_game_over_row_with_winner():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, lives=1)
    session.advance()  # påstående
    session.advance()  # syn -> matchen är slut
    assert session.finished is True

    state = session.to_dict()
    assert state["phase"] == "finished"
    winner = state["winner"]
    assert winner is not None
    assert winner["name"] in [p.name for p in players]
    assert winner["role"] in ("a", "b")

    # Sista loggraden är vinnarraden och pekar ut rätt spelare.
    last = state["log"][-1]
    assert last["kind"] == "game_over"
    assert last["winner_name"] == winner["name"]
    assert last["winner_role"] == winner["role"]
    assert last["action"] == "slut"


def test_game_over_row_is_last_and_only_one():
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b", "c")
    ]
    session = Session.new(players, lives=1)
    session.run_to_end()
    kinds = [row["kind"] for row in session.to_dict()["log"]]
    assert kinds.count("game_over") == 1
    assert kinds[-1] == "game_over"


def test_winner_row_is_ignored_by_player_stats():
    # Vinnarraden får inte räknas som en spelåtgärd i statistiken.
    from meier import match as match_mod

    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b")
    ]
    session = Session.new(players, lives=1)
    session.play_to_end()
    # Vinnarraden finns i loggen ...
    assert session.log[-1].kind == "game_over"
    stats = match_mod._player_stats(session.log, [p.name for p in players])
    # ... men räknas inte: summan matchar antalet riktiga action-rader.
    action_rows = [e for e in session.log if e.kind == "action"]
    counted = sum(s["bids"] + s["decisions"] for s in stats.values())
    assert counted == len(action_rows)


def test_every_life_row_carries_a_standings_snapshot():
    # Livsställningen ska finnas med på varje livsrad, inte bara den sista.
    players = [
        make_player(k, ScriptedLLM(bids=[66], actions=["syna"])) for k in ("a", "b", "c")
    ]
    session = Session.new(players, lives=2)
    session.run_to_end()
    life_rows = [r for r in session.to_dict()["log"] if r["kind"] == "life"]
    assert life_rows, "matchen ska ha minst en livsrad"
    for row in life_rows:
        assert row["standings"], "varje livsrad ska ha en livsställning"
        names = [p["name"] for p in row["standings"]]
        assert names == [session.name_of(i) for i in session.order]
        # Livsställningen speglar radens egen livsnivå.
        loser = next(p for p in row["standings"] if p["name"] == row["player_name"])
        assert loser["lives"] == row["lives_left"]


def test_die_model_is_solid_angle():
    """Tärningens vikter ska härledas ur rymdvinkeln, inte ur arean.

    ``DIE_ELONGATION`` är längd/bredd. Med rymdvinkelmodellen blir en långsida
    1,562 gånger så sannolik som en ändyta för samma form. Areamodellen gav
    exakt 1,3 och är borttagen. Testet låser både talet och att det räknas fram
    ur formeln, så att ingen återinför en gissad konstant.
    """
    import math

    assert rules.DIE_ELONGATION == 1.3
    ratio = rules.FACE_WEIGHTS[2] / rules.FACE_WEIGHTS[0]
    assert math.isclose(ratio, 1.5620056285, rel_tol=1e-9)

    # Samma formel som koden, räknad här, ska ge samma vikter.
    def omega(a: float, b: float, d: float) -> float:
        return 4.0 * math.atan(a * b / (d * math.sqrt(a * a + b * b + d * d)))

    end = omega(0.5, 0.5, rules.DIE_ELONGATION / 2)
    side = omega(0.5, rules.DIE_ELONGATION / 2, 0.5)
    total = 2 * end + 4 * side
    for expected, actual in zip(
        (end / total, end / total, side / total, side / total, side / total, side / total),
        rules.FACE_WEIGHTS,
    ):
        assert math.isclose(expected, actual, rel_tol=1e-12)

    # P(21) följer av vikterna: ~2,94 %, inte areamodellens 3,86 %.
    from meier.policy import OUTCOME_P

    assert math.isclose(OUTCOME_P[21], 0.0293988, abs_tol=1e-7)
