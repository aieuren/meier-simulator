"""Tester för spelmotorn med skriptade (icke-LLM) agenter."""

import pytest

from meier import rules
from meier.agents.base import Agent, Role
from meier.agents.player import ActionDecision, Announcement, MeierPlayerAgent
from meier.agents.roster import make_players
from meier.game import Game


class ScriptedAgent(Agent):
    """Agent som följer ett förutbestämt manus i stället för att anropa en LLM."""

    def __init__(self, name, announcements, decisions):
        super().__init__(role=Role(key=name, name=name, description="", style=""))
        self._announcements = list(announcements)
        self._decisions = list(decisions)

    def system_prompt(self):
        return ""

    def announce(self, dice, *, previous_claim=None, opponent=None):
        shown = rules.read_dice(*dice)
        if previous_claim is not None:
            # Tvingad höjning: välj nästa högre påstående.
            claim = rules.next_higher(previous_claim) or rules.MEIER
        else:
            claim = self._announcements.pop(0) if self._announcements else shown
        return Announcement(
            dice=dice, shown=shown, claim=claim, truth=claim == shown, line="", reasoning="", role=self.role.key
        )

    def decide(self, claim, *, lives=3, opponent=None):
        action, new_claim = self._decisions.pop(0) if self._decisions else ("skicka", None)
        return ActionDecision(action=action, claim=new_claim, line="", reasoning="", role=self.role.key)


def test_game_requires_two_players():
    agent = ScriptedAgent("A", [], [])
    with pytest.raises(Exception):
        Game.new([agent])


def test_game_call_resolution_reduces_lives():
    # Spelare A säger 65, spelare B synar. Tärningarna visar 62 -> A förlorar ett liv.
    a = ScriptedAgent("A", [65], [])
    b = ScriptedAgent("B", [11], [("syna", None)])
    game = Game.new([a, b])
    # Tvinga fram ett bestämt slag: 6 och 2 -> 62.
    game.roll = lambda: (6, 2)
    winner = game.play()
    assert game.players[0].lives == 2  # A (hållaren) förlorade ett liv
    assert winner in game.players


def test_game_call_when_shown_higher_loses_caller():
    # A säger 31, B synar. Tärningarna visar 62 -> B (synaren) förlorar ett liv.
    a = ScriptedAgent("A", [31], [])
    b = ScriptedAgent("B", [11], [("syna", None)])
    game = Game.new([a, b])
    game.roll = lambda: (6, 2)
    game.play()
    assert game.players[1].lives == 2  # B förlorade ett liv


def test_game_meier_costs_double():
    # A säger 21 (Meier), B synar. Tärningarna visar 31 -> A förlorar två liv.
    a = ScriptedAgent("A", [21], [])
    b = ScriptedAgent("B", [11], [("syna", None)])
    game = Game.new([a, b])
    game.roll = lambda: (3, 1)
    game.play()
    assert game.players[0].lives == 1  # 3 - 2 = 1


def test_full_loop_forces_claimer_to_raise():
    # B skickar vidare så bägaren går tillbaka till A, som tvingas höja.
    a = ScriptedAgent("A", [62], [])
    b = ScriptedAgent("B", [11], [("skicka", None), ("syna", None)])
    game = Game.new([a, b])
    game.roll = lambda: (6, 2)  # -> 62
    game.play()
    log = "\n".join(game.log)
    assert "måste höja" in log
    assert "63" in log


def test_forced_raise_rerolls_the_dice():
    # Vid tvingad höjning slås tärningarna om, och det nya slaget avgör en syn.
    a = ScriptedAgent("A", [62], [])
    b = ScriptedAgent("B", [11], [("skicka", None), ("syna", None)])
    game = Game.new([a, b])
    rolls = iter([(6, 2), (5, 1)])  # först 62, sedan 51 vid omslaget
    game.roll = lambda: next(rolls, (3, 1))  # därefter ny runda
    game.play(max_rounds=1)
    log = "\n".join(game.log)
    # A slog om till 51 och höjde till 61; B synade och tärningarna (51) visade
    # lägre än påståendet, alltså förlorar hållaren A ett liv.
    assert "slår om" in log
    assert game.players[0].lives == 2


def test_game_terminates_with_passive_agents():
    # Båda skickar alltid; skyddsnätet tvingar fram en syn så spelet tar slut.
    a = ScriptedAgent("A", [], [("skicka", None)] * 500)
    b = ScriptedAgent("B", [], [("skicka", None)] * 500)
    game = Game.new([a, b])
    winner = game.play(max_rounds=50)
    assert winner is not None


def test_meier_full_loop_triggers_reroll():
    # A säger Meier (21), B skickar vidare -> bägaren tillbaka, A slår om.
    a = ScriptedAgent("A", [21], [])
    b = ScriptedAgent("B", [11], [("skicka", None), ("syna", None)])
    game = Game.new([a, b])
    game.roll = lambda: (2, 1)  # -> 21 (Meier)
    game.play()
    log = "\n".join(game.log)
    assert "Meier" in log and "slår om" in log


def test_bag_goes_to_previous_active_player_every_round():
    """Regeln: bägaren går till föregående spelare, som börjar nästa runda.

    Utslagna spelare hoppas över. Detta mäts på riktiga matcher, så att
    ``_previous_active`` inte kan glida ifrån regeltexten.
    """
    import re

    from meier.agents.roster import make_players

    checks = 0
    for _ in range(40):
        players, _ = make_players(["axel", "berit", "cecilia", "david"])
        game = Game.new(players)
        game.play()
        names = [p.name for p in game.players]
        out: set[str] = set()
        loser = None
        for line in game.log:
            found = re.search(r"Syn!.*?(\w+) har nu \d+ liv", line)
            if found:
                loser = found.group(1)
            gone = re.match(r"\s+(\w+) är ute!", line)
            if gone:
                out.add(gone.group(1))
            if line.startswith("Runda ") and loser:
                starter = re.search(r"Runda \d+: (\w+) slår", line).group(1)
                active = [n for n in names if n not in out]
                if loser in active:
                    expected = active[(active.index(loser) - 1) % len(active)]
                else:
                    idx = names.index(loser)
                    expected = next(
                        names[(idx - off) % len(names)]
                        for off in range(1, len(names) + 1)
                        if names[(idx - off) % len(names)] not in out
                    )
                assert starter == expected, (
                    f"{loser} förlorade, men {starter} började "
                    f"(väntat {expected})"
                )
                checks += 1
                loser = None
    assert checks > 300, "för få rundor för att testet ska betyda något"


def test_engine_accepts_lower_first_claim():
    """Reglerna tillåter 'det sanna, ett högre eller ett lägre'.

    Motorn ska acceptera ett lägre påstående. Att policyn sedan aldrig väljer det är
    ett strategival – se docs/regler/granskning.md.
    """
    from meier.agents.base import Role
    from meier.agents.player import MeierPlayerAgent

    class LowerLLM:
        def complete(self, system, user, json_mode=False):
            return '{"claim": 31, "line": "31", "reasoning": "lägre"}'

    role = Role(key="test", name="Test", description="t", style="t")
    agent = MeierPlayerAgent(role, llm=LowerLLM())
    announcement = agent.announce((5, 2))  # tärningarna visar 52
    assert announcement.claim == 31
    assert rules.compare(announcement.claim, 52) < 0


def test_pass_is_unseen_the_dice_never_reach_the_chooser():
    """Den som skickar vidare får inte se tärningarna.

    Att lyfta på locket är att syna. Kunde spelaren titta och sedan skicka
    vidare vore "skicka vidare" en gratis syn. Testet fångar varje anrop till
    ``decide`` och kontrollerar att inget tärningsvärde följer med.
    """
    seen_calls: list[dict] = []

    class Spy:
        def __init__(self, inner):
            self.name = inner.name
            self._inner = inner

        def announce(self, dice, **kw):
            return self._inner.announce(dice, **kw)

        def announce_forced(self, dice, **kw):
            return self._inner.announce_forced(dice, **kw)

        def announce_shake(self, dice, **kw):
            return self._inner.announce_shake(dice, **kw)

        def decide(self, claim, **kw):
            seen_calls.append({"claim": claim, **kw})
            return self._inner.decide(claim, **kw)

    for _ in range(5):
        spied = [Spy(p) for p in make_players(["axel", "berit", "cecilia", "david"])[0]]
        Game.new(spied).play()

    assert len(seen_calls) > 100, "för få beslut för att testet ska betyda något"
    for call in seen_calls:
        assert set(call) == {"claim", "lives"}, (
            f"beslutsmottagaren fick mer än påstående och liv: {sorted(call)}. "
            "Tärningarna får aldrig nå den som väljer handling – att titta är att syna."
        )
        assert isinstance(call["claim"], int)
        assert rules.is_valid_value(call["claim"])


def test_decide_signature_cannot_take_dice():
    """Skyddar mot att någon lägger till tärningarna i anropet senare."""
    import inspect

    params = set(inspect.signature(MeierPlayerAgent.decide).parameters)
    assert params == {"self", "claim", "lives", "opponent"}, (
        f"decide har fått nya parametrar: {params}. Om tärningarna läggs till "
        "bryts regeln att skicka vidare sker utan att syna."
    )


class ScriptedSeen:
    """Svarar på slagets val: titta på tärningarna (seen) eller avstå."""

    def __init__(self, seen: bool):
        self.seen = seen

    def complete(self, system, user, *, json_mode=False):
        if "SLAG – TITTA ELLER INTE TITTA" in user:
            return '{"seen": %s, "reasoning": "test"}' % (
                "true" if self.seen else "false"
            )
        return '{"claim": 52, "reasoning": "test"}'


def test_shake_offers_the_player_a_look():
    """Reglerna låter spelaren lyfta på locket på sitt eget slag.

    Att titta är det normala, och att avstå är ett eget val. Frågan ska därför
    ställas, och prompten ska säga att titten är tillåten.
    """
    role = Role(key="test", name="Test", description="t", style="t")
    agent = MeierPlayerAgent(role, llm=ScriptedSeen(True))

    announcement = agent.announce_shake((5, 2), previous_claim=44)

    assert announcement.unseen is False, "spelaren valde att titta"
    assert announcement.choice_line == "Jag tittar på tärningarna."
    # Tärningarna 52 får styra påståendet, eftersom spelaren såg dem.
    assert announcement.shown == 52
    assert rules.compare(announcement.claim, 44) > 0, "påståendet måste vara högre än det förra"


def test_shake_can_choose_not_to_look():
    """Utan att titta är ett val, inte ett tvång. Det ska fortfarande gå."""
    role = Role(key="test", name="Test", description="t", style="t")
    agent = MeierPlayerAgent(role, llm=ScriptedSeen(False))

    announcement = agent.announce_shake((5, 2), previous_claim=44)

    assert announcement.unseen is True
    assert announcement.choice_line == "Jag påstår utan att titta."
    assert rules.compare(announcement.claim, 44) > 0


def test_shake_prompt_says_the_look_is_allowed():
    """Prompten får aldrig påstå att locket måste ligga kvar vid ett slag."""
    role = Role(key="test", name="Test", description="t", style="t")
    agent = MeierPlayerAgent(role, llm=ScriptedSeen(True))
    prompt = agent._shake_choice_context(44)

    assert "får lyfta på det" in prompt
    assert "Titta: du ser tärningarna" in prompt
    assert "får inte" not in prompt.lower(), "prompten får inte förbjuda titten"
