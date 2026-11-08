"""Interaktiv spelsession för Majer – ett fullt flöde fram till en syn.

Flera oberoende agenter spelar mot varandra, steg för steg. Slumpen avgör
ordningen på spelarna och vem som börjar. Varje svar sparas i en logg med
tärningsutfallet, vem som svarade, vad spelaren svarade och om domaren godkänner
svaret eller har invändningar.

Flödet följer reglerna:

1. Första spelaren slår och **tittar i smyg** – säger sanningen, ett högre eller
   ett lägre resultat.
2. Nästa spelare väljer **Slå** (höjer utan att titta), **Syna** (lyfter locket)
   eller **Skicka vidare** (samma bud).
3. När bägaren kommer ett helt varv tillbaka till budgivaren måste denne höja.
   Är budet Mejer får spelaren i stället slå om och börja en ny runda.
4. Vid en syn lyfts locket: visar tärningarna lägre än budet förlorar budgivaren
   ett liv, annars den som synade. Mejer kostar dubbelt.

Sessionen är grindad: varje steg (ett tärningsslag, en höjning eller ett svar)
måste bekräftas med OK innan nästa steg sker. Det gör det lätt att kontrollera
att allt fungerar. ``run_to_call`` kör hela flödet fram till en syn på en gång.
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
    action: str = "bud"  # "bud", "slå", "skicka", "syna", "höja"
    previous_bid: int | None = None
    proposed: int | None = None  # rå bud från modellen
    corrected: bool = False  # korrigerades budet?
    blind: bool = False  # slog spelaren utan att titta?

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
            "action": self.action,
            "previous_bid": self.previous_bid,
            "previous_bid_name": rules.name(self.previous_bid)
            if self.previous_bid is not None
            else None,
            "proposed": self.proposed,
            "corrected": self.corrected,
            "blind": self.blind,
            "referee": self.referee.to_dict(),
        }


@dataclass
class CallResult:
    """Utfallet av en syn."""

    bid: int
    shown: int
    caller: str
    bidder: str
    caller_loses: bool
    loser: str  # namn på den som förlorar liv
    lives: int  # antal förlorade liv

    def to_dict(self) -> dict:
        return {
            "bid": self.bid,
            "bid_name": rules.name(self.bid),
            "shown": self.shown,
            "shown_name": rules.name(self.shown),
            "caller": self.caller,
            "bidder": self.bidder,
            "caller_loses": self.caller_loses,
            "loser": self.loser,
            "lives": self.lives,
        }


@dataclass
class Session:
    """En pågående interaktiv Majer-session med flera agenter."""

    players: list[MajerPlayerAgent]
    referee: RefereeAgent
    order: list[int] = field(default_factory=list)
    round: int = 1
    lives: list[int] = field(default_factory=list)
    log: list[LogEntry] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    finished: bool = False
    result: CallResult | None = None

    # -- Steg som väntar på bekräftelse ------------------------------------
    step_kind: str = ""  # "roll", "action" eller "raise"
    pending_dice: tuple[int, int] | None = None  # det hemliga slaget (tärningar)
    pending_bid: int | None = None  # aktuellt bud
    bidder: int = 0  # spelarindex för den som satte budet
    actor: int = 0  # spelarindex som ska agera

    @classmethod
    def new(
        cls,
        players: list[MajerPlayerAgent],
        referee: RefereeAgent,
        *,
        seed: int | None = None,
        lives: int = 3,
    ) -> "Session":
        if len(players) < 2:
            raise ValueError("En Majer-session kräver minst två spelare")
        rng = random.Random(seed)
        # Slumpen avgör ordningen på spelarna (och därmed vem som börjar).
        order = list(range(len(players)))
        rng.shuffle(order)
        session = cls(
            players=players,
            referee=referee,
            order=order,
            lives=[lives] * len(players),
            rng=rng,
        )
        session._prepare_round(starter=order[0])
        return session

    # -- Hjälpare -----------------------------------------------------------
    @property
    def current_player(self) -> MajerPlayerAgent:
        return self.players[self.actor]

    def name_of(self, idx: int) -> str:
        return self.players[idx].name

    def _prepare_round(self, *, starter: int) -> None:
        """Starta en ny runda: den som börjar slår och tittar i smyg."""
        self.pending_dice = rules.roll(self.rng)
        self.step_kind = "roll"
        self.actor = starter
        self.bidder = starter
        self.pending_bid = None

    def _prepare_action(self, *, actor: int) -> None:
        """Nästa spelare ska agera mot ett bud (slå/syna/skicka)."""
        self.actor = actor
        self.step_kind = "action"

    def _prepare_raise(self) -> None:
        """Budgivaren måste höja efter ett helt varv."""
        self.actor = self.bidder
        self.step_kind = "raise"

    def _next_actor(self, idx: int) -> int:
        pos = self.order.index(idx)
        return self.order[(pos + 1) % len(self.order)]

    def _active_indices(self) -> list[int]:
        return [i for i in self.order if self.lives[i] > 0]

    def _finish(self) -> None:
        self.finished = True
        self.step_kind = ""
        self.pending_dice = None
        self.pending_bid = None

    # -- Grinden: bekräfta och utför nästa steg ----------------------------
    def advance(self) -> LogEntry | None:
        """Bekräfta (OK) det aktuella steget och utför det.

        Returnerar loggposten om steget var ett svar, annars None.
        """
        if self.finished:
            raise ValueError("Sessionen är redan avslutad")
        if self.step_kind == "":
            raise ValueError("Inget steg väntar på bekräftelse")

        if self.step_kind == "roll":
            return self._resolve_roll()
        if self.step_kind == "raise":
            return self._resolve_raise()
        return self._resolve_action()

    def run_to_call(self, *, max_steps: int = 200) -> list[LogEntry]:
        """Kör hela flödet fram till en syn (eller tills spelet tar slut).

        Returnerar de loggposter som skapades. Ett skyddsnät stoppar efter
        ``max_steps`` steg om ingen vill syna.
        """
        created: list[LogEntry] = []
        steps = 0
        while not self.finished and self.step_kind and self.result is None:
            steps += 1
            if steps > max_steps:
                break
            entry = self.advance()
            if entry is not None:
                created.append(entry)
        return created

    # -- Steg 1: tärningsslaget (första budet) -----------------------------
    def _resolve_roll(self) -> LogEntry:
        dice = self.pending_dice
        assert dice is not None
        player = self.players[self.actor]
        ann = player.announce(dice)
        verdict = self.referee.review_announcement(
            dice,
            ann.bid,
            previous_bid=None,
            line=ann.line,
            proposed=ann.proposed,
            corrected=ann.corrected,
        )
        entry = self._log_entry(
            player, dice, ann, verdict, action="bud", previous_bid=None, blind=False
        )
        self.pending_bid = ann.bid
        self.bidder = self.actor
        self._prepare_action(actor=self._next_actor(self.actor))
        return entry

    # -- Steg 2: slå, syna eller skicka vidare -----------------------------
    def _resolve_action(self) -> LogEntry | None:
        bid = self.pending_bid
        assert bid is not None
        player = self.players[self.actor]
        decision = player.decide(bid, lives=self.lives[self.actor])

        if decision.action == "syna":
            return self._resolve_call(player)

        if decision.action == "slå" and decision.bid is not None:
            dice = self.pending_dice
            assert dice is not None
            ann = player.announce_blind(dice, previous_bid=bid)
            verdict = self.referee.review_announcement(
                dice,
                ann.bid,
                previous_bid=bid,
                line=ann.line,
                proposed=ann.proposed,
                corrected=ann.corrected,
            )
            entry = self._log_entry(
                player, dice, ann, verdict, action="slå", previous_bid=bid, blind=True
            )
            self.pending_bid = ann.bid
            self.bidder = self.actor
            self._after_bid(actor=self.actor)
            return entry

        # Skicka vidare: samma bud går vidare.
        verdict = self.referee.review_decision("skicka", bid=bid, line=decision.line)
        dice = self.pending_dice or (1, 1)
        entry = LogEntry(
            round=self.round,
            player=player.role.key,
            player_name=player.name,
            dice=dice,
            shown=rules.read_dice(*dice),
            bid=bid,
            truth=False,
            line=decision.line,
            reasoning=decision.reasoning,
            referee=verdict,
            action="skicka",
            previous_bid=bid,
        )
        self.log.append(entry)
        self._after_bid(actor=self.actor)
        return entry

    # -- Steg 3: tvingad höjning när bägaren gått ett helt varv ------------
    def _resolve_raise(self) -> LogEntry:
        bid = self.pending_bid
        dice = self.pending_dice
        assert bid is not None and dice is not None
        player = self.players[self.bidder]
        ann = player.announce(dice, previous_bid=bid)
        verdict = self.referee.review_announcement(
            dice,
            ann.bid,
            previous_bid=bid,
            line=ann.line,
            proposed=ann.proposed,
            corrected=ann.corrected,
        )
        entry = self._log_entry(
            player, dice, ann, verdict, action="höja", previous_bid=bid, blind=False
        )
        self.pending_bid = ann.bid
        self._after_bid(actor=self.bidder)
        return entry

    def _after_bid(self, *, actor: int) -> None:
        """Efter ett bud: gå vidare till nästa spelare – eller hela varvet runt."""
        nxt = self._next_actor(actor)
        if nxt == self.bidder:
            if rules.is_mejer(self.pending_bid):
                # Budet är Mejer – budgivaren slår om och börjar en ny runda.
                starter = self.bidder
                self.round += 1
                self._prepare_round(starter=starter)
            else:
                self._prepare_raise()
        else:
            self._prepare_action(actor=nxt)

    # -- Steg 4: synen -----------------------------------------------------
    def _resolve_call(self, caller_agent: MajerPlayerAgent) -> LogEntry:
        bid = self.pending_bid
        dice = self.pending_dice
        assert bid is not None and dice is not None
        shown = rules.read_dice(*dice)
        caller_idx = self.actor
        bidder_idx = self.bidder

        result = rules.resolve_call(bid, shown)
        loser_idx = caller_idx if result.caller_loses else bidder_idx
        self.lives[loser_idx] -= result.lives

        verdict = self.referee.review_decision("syna", bid=bid, line="")
        entry = LogEntry(
            round=self.round,
            player=caller_agent.role.key,
            player_name=caller_agent.name,
            dice=dice,
            shown=shown,
            bid=bid,
            truth=False,
            line=f"Syn! {result.describe()}",
            reasoning="",
            referee=verdict,
            action="syna",
            previous_bid=bid,
        )
        self.log.append(entry)

        self.result = CallResult(
            bid=bid,
            shown=shown,
            caller=self.name_of(caller_idx),
            bidder=self.name_of(bidder_idx),
            caller_loses=result.caller_loses,
            loser=self.name_of(loser_idx),
            lives=result.lives,
        )

        if len(self._active_indices()) <= 1:
            self._finish()
            return entry

        # Nästa runda: föregående spelare (budgivaren) börjar. Slår om.
        self.round += 1
        self._prepare_round(starter=bidder_idx)
        return entry

    # -- Hjälpare för loggposter -------------------------------------------
    def _log_entry(
        self,
        player: MajerPlayerAgent,
        dice: tuple[int, int],
        ann,
        verdict: Verdict,
        *,
        action: str,
        previous_bid: int | None,
        blind: bool,
    ) -> LogEntry:
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
            action=action,
            previous_bid=previous_bid,
            proposed=ann.proposed,
            corrected=ann.corrected,
            blind=blind,
        )
        self.log.append(entry)
        return entry

    def stop(self) -> None:
        self.finished = True
        self.step_kind = ""
        self.pending_dice = None
        self.pending_bid = None

    # -- Serialisering ------------------------------------------------------
    def to_dict(self) -> dict:
        pending = None
        if self.step_kind:
            pending = {"kind": self.step_kind}
            # Tärningarna är alltid med – de är indata till spelaren i rundan.
            if self.pending_dice is not None:
                shown = rules.read_dice(*self.pending_dice)
                pending["dice"] = list(self.pending_dice)
                pending["shown"] = shown
                pending["shown_name"] = rules.name(shown)
            if self.pending_bid is not None:
                pending["bid"] = self.pending_bid
                pending["bid_name"] = rules.name(self.pending_bid)
                pending["bidder"] = self.name_of(self.bidder)

        return {
            "phase": self._phase(),
            "round": self.round,
            "order": [
                {
                    "name": self.players[i].name,
                    "role": self.players[i].role.key,
                    "index": i,
                    "lives": self.lives[i],
                }
                for i in self.order
            ],
            "current": {
                "name": self.current_player.name,
                "role": self.current_player.role.key,
            }
            if self.step_kind
            else None,
            "step_kind": self.step_kind,
            "pending": pending,
            "result": self.result.to_dict() if self.result else None,
            "log": [e.to_dict() for e in self.log],
        }

    def _phase(self) -> str:
        if self.finished:
            return "finished"
        return "awaiting_ok"
