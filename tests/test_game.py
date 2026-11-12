"""Tester för spelmotorn med skriptade (icke-LLM) agenter."""

import pytest

from meier import rules
from meier.agents.base import Agent, Role
from meier.agents.player import ActionDecision, Announcement
from meier.game import Game


class ScriptedAgent(Agent):
    """Agent som följer ett förutbestämt manus i stället för att anropa en LLM."""

    def __init__(self, name, announcements, decisions):
        super().__init__(role=Role(key=name, name=name, description="", style=""))
        self._announcements = list(announcements)
        self._decisions = list(decisions)

    def system_prompt(self):
        return ""

    def announce(self, dice, *, previous_bid=None):
        shown = rules.read_dice(*dice)
        if previous_bid is not None:
            # Tvingad höjning: välj nästa högre bud.
            bid = rules.next_higher(previous_bid) or rules.MEIER
        else:
            bid = self._announcements.pop(0) if self._announcements else shown
        return Announcement(
            dice=dice, shown=shown, bid=bid, truth=bid == shown, line="", reasoning="", role=self.role.key
        )

    def decide(self, bid, *, lives=3):
        action, new_bid = self._decisions.pop(0) if self._decisions else ("skicka", None)
        return ActionDecision(action=action, bid=new_bid, line="", reasoning="", role=self.role.key)


def test_game_requires_two_players():
    agent = ScriptedAgent("A", [], [])
    with pytest.raises(Exception):
        Game.new([agent])


def test_game_call_resolution_reduces_lives():
    # Spelare A säger 65, spelare B synar. Tärningarna visar 62 -> A förlorar ett liv.
    a = ScriptedAgent("A", [65], [])
    b = ScriptedAgent("B", [11], [("syna", None)])
    game = Game.new([a, b], seed=0)
    # Tvinga fram ett bestämt slag: 6 och 2 -> 62.
    game.roll = lambda: (6, 2)
    winner = game.play()
    assert game.players[0].lives == 2  # A (budgivaren) förlorade ett liv
    assert winner in game.players


def test_game_call_when_shown_higher_loses_caller():
    # A säger 31, B synar. Tärningarna visar 62 -> B (synaren) förlorar ett liv.
    a = ScriptedAgent("A", [31], [])
    b = ScriptedAgent("B", [11], [("syna", None)])
    game = Game.new([a, b], seed=0)
    game.roll = lambda: (6, 2)
    game.play()
    assert game.players[1].lives == 2  # B förlorade ett liv


def test_game_meier_costs_double():
    # A säger 21 (Meier), B synar. Tärningarna visar 31 -> A förlorar två liv.
    a = ScriptedAgent("A", [21], [])
    b = ScriptedAgent("B", [11], [("syna", None)])
    game = Game.new([a, b], seed=0)
    game.roll = lambda: (3, 1)
    game.play()
    assert game.players[0].lives == 1  # 3 - 2 = 1


def test_full_loop_forces_bidder_to_raise():
    # B skickar vidare så bägaren går tillbaka till A, som tvingas höja.
    a = ScriptedAgent("A", [62], [])
    b = ScriptedAgent("B", [11], [("skicka", None), ("syna", None)])
    game = Game.new([a, b], seed=0)
    game.roll = lambda: (6, 2)  # -> 62
    game.play()
    log = "\n".join(game.log)
    assert "måste höja" in log
    assert "63" in log


def test_forced_raise_rerolls_the_dice():
    # Vid tvingad höjning slås tärningarna om, och det nya slaget avgör en syn.
    a = ScriptedAgent("A", [62], [])
    b = ScriptedAgent("B", [11], [("skicka", None), ("syna", None)])
    game = Game.new([a, b], seed=0)
    rolls = iter([(6, 2), (5, 1)])  # först 62, sedan 51 vid omslaget
    game.roll = lambda: next(rolls, (3, 1))  # därefter ny runda
    game.play(max_rounds=1)
    log = "\n".join(game.log)
    # A slog om till 51 och höjde till 61; B synade och tärningarna (51) visade
    # lägre än budet, alltså förlorar budgivaren A ett liv.
    assert "slår om" in log
    assert game.players[0].lives == 2


def test_game_terminates_with_passive_agents():
    # Båda skickar alltid; skyddsnätet tvingar fram en syn så spelet tar slut.
    a = ScriptedAgent("A", [], [("skicka", None)] * 500)
    b = ScriptedAgent("B", [], [("skicka", None)] * 500)
    game = Game.new([a, b], seed=42)
    winner = game.play(max_rounds=50)
    assert winner is not None


def test_meier_full_loop_triggers_reroll():
    # A säger Meier (21), B skickar vidare -> bägaren tillbaka, A slår om.
    a = ScriptedAgent("A", [21], [])
    b = ScriptedAgent("B", [11], [("skicka", None), ("syna", None)])
    game = Game.new([a, b], seed=0)
    game.roll = lambda: (2, 1)  # -> 21 (Meier)
    game.play()
    log = "\n".join(game.log)
    assert "Meier" in log and "slår om" in log
