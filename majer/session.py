"""Interaktiv spelsession för Majer.

Här spelar flera oberoende agenter mot varandra, steg för steg. Slumpen avgör
ordningen på spelarna och vem som börjar. Varje svar sparas i en enkel logg med
tärningsutfallet, vem som svarade, vad spelaren svarade och om domaren godkänner
svaret eller har invändningar.

För närvarande är sessionen grindad: tärningsslaget visas och måste bekräftas
(OK) innan spelaren i tur får ge sitt svar. Det gör det lätt att kontrollera att
allt fungerar.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import rules
from .agents.player import MajerPlayerAgent
from .agents.referee import RefereeAgent, Verdict


@dataclass
class LogEntry:
    """En rad i loggen: ett svar från en spelare och domarens utlåtande."""

    round: int
    player: str  # rollens nyckel
    player_name: str
    dice: tuple[int, int]
    shown: int
    bid: int
    truth: bool
    line: str
    reasoning: str
    referee: Verdict
    proposed: int | None = None  # rå bud från modellen
    corrected: bool = False  # korrigerades budet?

    def to_dict(self) -> dict:
        return {
            "round": self.round,
            "player": self.player,
            "player_name": self.player_name,
            "dice": list(self.dice),
            "shown": self.shown,
            "shown_name": rules.name(self.shown),
            "bid": self.bid,
            "bid_name": rules.name(self.bid),
            "truth": self.truth,
            "lie": not self.truth,
            "line": self.line,
            "reasoning": self.reasoning,
            "proposed": self.proposed,
            "corrected": self.corrected,
            "referee": self.referee.to_dict(),
        }


@dataclass
class Session:
    """En pågående interaktiv Majer-session med flera agenter."""

    players: list[MajerPlayerAgent]
    referee: RefereeAgent
    order: list[int] = field(default_factory=list)
    turn_index: int = 0
    round: int = 1
    pending_dice: tuple[int, int] | None = None
    log: list[LogEntry] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    finished: bool = False

    @classmethod
    def new(
        cls,
        players: list[MajerPlayerAgent],
        referee: RefereeAgent,
        *,
        seed: int | None = None,
    ) -> "Session":
        if len(players) < 2:
            raise ValueError("En Majer-session kräver minst två spelare")
        rng = random.Random(seed)
        # Slumpen avgör ordningen på spelarna (och därmed vem som börjar).
        order = list(range(len(players)))
        rng.shuffle(order)
        session = cls(players=players, referee=referee, order=order, rng=rng)
        session._deal_roll()
        return session

    # -- Interna hjälpare ---------------------------------------------------
    def _deal_roll(self) -> None:
        """Slå fram nästa spelares tärningsutfall (väntar på OK)."""
        self.pending_dice = rules.roll(self.rng)

    @property
    def current_index(self) -> int:
        return self.order[self.turn_index % len(self.order)]

    @property
    def current_player(self) -> MajerPlayerAgent:
        return self.players[self.current_index]

    # -- Grinden: bekräfta tärningsslaget och låt spelaren svara -----------
    def advance(self) -> LogEntry:
        """Bekräfta tärningsslaget och låt spelaren i tur ge sitt svar.

        Returnerar loggposten för svaret. Sedan läggs nästa spelares tärningsslag
        fram och väntar på OK.
        """
        if self.finished:
            raise ValueError("Sessionen är redan avslutad")
        if self.pending_dice is None:
            raise ValueError("Inget tärningsslag väntar på bekräftelse")

        dice = self.pending_dice
        player = self.current_player
        ann = player.announce(dice)
        verdict = self.referee.review_announcement(
            dice,
            ann.bid,
            previous_bid=None,
            line=ann.line,
            proposed=ann.proposed,
            corrected=ann.corrected,
        )

        entry = LogEntry(
            round=self.round,
            player=player.role.key,
            player_name=player.name,
            dice=dice,
            shown=ann.shown,
            bid=ann.bid,
            truth=ann.truth,
            line=ann.line,
            reasoning=ann.reasoning,
            referee=verdict,
            proposed=ann.proposed,
            corrected=ann.corrected,
        )
        self.log.append(entry)

        # Nästa spelare i tur.
        self.turn_index += 1
        if self.turn_index % len(self.order) == 0:
            self.round += 1
        self._deal_roll()
        return entry

    def stop(self) -> None:
        self.finished = True
        self.pending_dice = None

    # -- Serialisering ------------------------------------------------------
    def to_dict(self) -> dict:
        pending = None
        if self.pending_dice is not None:
            shown = rules.read_dice(*self.pending_dice)
            pending = {
                "dice": list(self.pending_dice),
                "shown": shown,
                "shown_name": rules.name(shown),
            }
        return {
            "phase": "finished" if self.finished else "awaiting_ok",
            "round": self.round,
            "order": [
                {"name": self.players[i].name, "role": self.players[i].role.key, "index": i}
                for i in self.order
            ],
            "current": {
                "name": self.current_player.name,
                "role": self.current_player.role.key,
            }
            if not self.finished
            else None,
            "pending": pending,
            "log": [e.to_dict() for e in self.log],
        }
