"""Spelmotor för Mejeri.

Motorn håller ordning på spelare, liv, bud och turen, och låter oberoende
agenter spela mot varandra. Varje agent får bara den information en riktig
spelare skulle ha; ingen agent ser de andra agenternas hemliga tärningar.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from . import rules
from .agents.player import MejeriPlayerAgent


class GameError(RuntimeError):
    pass


@dataclass
class PlayerState:
    name: str
    agent: MejeriPlayerAgent
    lives: int = 3
    out: bool = False

    def lose_life(self, n: int) -> None:
        self.lives -= n
        if self.lives <= 0:
            self.lives = 0
            self.out = True


@dataclass
class Turn:
    """En spelares tur: de slår och säger ett bud."""

    player_index: int
    dice: tuple[int, int]
    shown: int
    bid: int
    line: str
    reasoning: str
    truth: bool


@dataclass
class Game:
    """Ett pågående Mejeri-spel."""

    players: list[PlayerState]
    rng: random.Random = field(default_factory=random.Random)
    log: list[str] = field(default_factory=list)
    rounds: int = 0
    on_log: "Callable[[str], None] | None" = None

    @classmethod
    def new(cls, agents: list[MejeriPlayerAgent], *, seed: int | None = None) -> "Game":
        if len(agents) < 2:
            raise GameError("Mejeri kräver minst två spelare")
        players = [PlayerState(name=a.name, agent=a) for a in agents]
        return cls(players=players, rng=random.Random(seed))

    def _record(self, text: str) -> None:
        self.log.append(text)
        if self.on_log is not None:
            self.on_log(text)

    @property
    def active(self) -> list[PlayerState]:
        return [p for p in self.players if not p.out]

    def roll(self) -> tuple[int, int]:
        return self.rng.randint(1, 6), self.rng.randint(1, 6)

    def play(self, *, max_rounds: int = 100) -> PlayerState:
        """Spela klart hela spelet och returnera vinnaren."""
        self._record("Spelet börjar. " + ", ".join(f"{p.name} ({p.lives} liv)" for p in self.players))

        starter = 0
        while len(self.active) > 1 and self.rounds < max_rounds:
            self.rounds += 1
            starter = self._play_round(starter)

        winner = self.active[0] if len(self.active) == 1 else max(self.active, key=lambda p: p.lives)
        self._record(f"{winner.name} vinner med {winner.lives} liv kvar!")
        return winner

    def _play_round(self, starter: int) -> int:
        """Spela en runda. Returnera index för nästa startspelare.

        Turen går i sittordning bland de spelare som är kvar. Den som sätter
        budet ("budgivaren") slår och säger ett bud. När bägaren kommer tillbaka
        till budgivaren ett helt varv senare måste denne höja – eller, om budet
        är Mejer, slå om och börja en ny runda.
        """
        active_idx = [i for i, p in enumerate(self.players) if not p.out]
        if starter not in active_idx:
            starter = active_idx[0]
        # Rotera så att startspelaren är först i turen.
        pos0 = active_idx.index(starter)
        order = active_idx[pos0:] + active_idx[:pos0]

        bidder = order[0]
        dice = self.roll()
        shown = rules.read_dice(*dice)
        ann = self.players[bidder].agent.announce(dice)
        bid = ann.bid
        self._record(
            f"Runda {self.rounds}: {self.players[bidder].name} slår och säger "
            f"{rules.name(bid)} ({ann.line}) [visar {rules.name(shown)}]"
        )

        pos = 1
        turns = 0
        max_turns = 200
        while True:
            turns += 1
            if turns > max_turns:
                # Skyddsnät: ingen ville syna. Tvinga fram en syn så rundan tar slut.
                idx = order[pos % len(order)]
                if idx == bidder:
                    idx = order[(pos + 1) % len(order)]
                self._record(f"  {self.players[idx].name} tvingas syna (rundan tog för lång tid).")
                result = rules.resolve_call(bid, shown)
                loser = bidder if not result.caller_loses else idx
                self.players[loser].lose_life(result.lives)
                self._record(f"  Syn! {result.describe()}")
                return self._previous_active(loser)

            idx = order[pos % len(order)]
            if idx == bidder:
                # Bägaren har gått ett helt varv tillbaka till budgivaren.
                if rules.is_mejer(bid):
                    self._record(
                        f"  Bägaren tillbaka hos {self.players[bidder].name} med Mejer "
                        "– slår om och börjar ny runda."
                    )
                    return bidder
                # Budgivaren tittar på samma tärningar och måste höja.
                forced = self.players[bidder].agent.announce(dice, previous_bid=bid)
                bid = forced.bid
                self._record(
                    f"  Bägaren tillbaka hos {self.players[bidder].name}, som måste höja "
                    f"till {rules.name(bid)} ({forced.line})."
                )
                pos += 1
                continue

            player = self.players[idx]
            decision = player.agent.decide(bid, lives=player.lives)
            self._record(f"  {player.name} väljer: {decision.action} ({decision.line})")

            if decision.action == "syna":
                result = rules.resolve_call(bid, shown)
                loser = bidder if not result.caller_loses else idx
                self.players[loser].lose_life(result.lives)
                self._record(
                    f"  Syn! {result.describe()} "
                    f"{self.players[loser].name} har nu {self.players[loser].lives} liv."
                )
                if self.players[loser].out:
                    self._record(f"  {self.players[loser].name} är ute!")
                # Bägaren går till föregående spelare, som slår och börjar ny runda.
                return self._previous_active(loser)

            if decision.action == "slå" and decision.bid is not None:
                bid = decision.bid
                bidder = idx

            pos += 1

    def _previous_active(self, player_idx: int) -> int:
        """Föregående aktiva spelare i sittordning (för nästa rundas start)."""
        active_idx = [i for i, p in enumerate(self.players) if not p.out]
        if player_idx in active_idx:
            pos = active_idx.index(player_idx)
            return active_idx[(pos - 1) % len(active_idx)]
        # Spelaren är ute: ta den aktiva spelaren precis före i sittordning.
        for offset in range(1, len(self.players) + 1):
            cand = (player_idx - offset) % len(self.players)
            if not self.players[cand].out:
                return cand
        return active_idx[0]

    def to_dict(self) -> dict:
        return {
            "players": [
                {"name": p.name, "lives": p.lives, "out": p.out, "role": p.agent.role.key}
                for p in self.players
            ],
            "log": self.log,
            "rounds": self.rounds,
        }
