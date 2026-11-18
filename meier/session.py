"""Interaktiv spelsession för Meier – ett fullt flöde fram till en syn.

Flera oberoende agenter spelar mot varandra, steg för steg. Slumpen avgör
ordningen på spelarna och vem som börjar. Varje svar sparas i en logg med
tärningsutfallet, vem som svarade och vad spelaren svarade.

Flödet följer reglerna:

1. Första spelaren slår och **tittar i smyg** – säger sanningen, ett högre eller
   ett lägre resultat.
2. Nästa spelare väljer **Slå** (skakar bägaren på nytt och säger ett högre bud),
   **Syna** (lyfter locket) eller **Skicka vidare** (samma bud).
3. När bägaren kommer ett helt varv tillbaka till budgivaren måste denne höja.
   Är budet Meier får spelaren i stället slå om och börja en ny runda.
4. Vid en syn lyfts locket: visar tärningarna lägre än budet förlorar den
   spelare som ansvarar för budet (den som sa det senast, eller skickade vidare
   och därmed tog över ansvaret) ett liv, annars den som synade. Meier kostar
   dubbelt. Den som förlorar livet loggas som en egen rad.

Sessionen är grindad: varje steg (ett tärningsslag, en höjning eller ett svar)
måste bekräftas innan nästa steg sker. Det gör det lätt att kontrollera att
allt fungerar. ``run_to_round_end`` kör fram till rundans slut och
``run_to_call`` kör hela flödet fram till en syn på en gång.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

from . import rules
from .agents.player import MeierPlayerAgent
from .opponents import OpponentTracker


@dataclass
class LogEntry:
    """En rad i loggen.

    Tre slag av rader:

    - ``kind == "roll"``: ett tärningsutfall (indata). Ingen spelare har svarat
      än. Detta är steget där OK-knappen hör hemma.
    - ``kind == "action"``: en spelares svar – ett bud, en blind höjning, en
      syn eller ett skickande.
    - ``kind == "life"``: någon har förlorat ett (eller två) liv efter en syn.
      Raden ligger direkt efter synen och visar hur många liv som är kvar.
    - ``kind == "game_over"``: matchen är slut och en vinnare står kvar. Sista
      raden i loggen. ``winner_name`` och ``winner_role`` anger vinnaren.
    """

    kind: str  # "roll", "action", "life" eller "game_over"
    round: int
    dice: tuple[int, int]
    shown: int
    action: str = "bud"  # "bud", "slå", "skicka", "syna", "höja", "liv", "slut"
    player: str | None = None  # rollens nyckel (endast action/life)
    player_name: str | None = None
    bid: int | None = None  # sagt bud (endast action)
    truth: bool = False
    line: str = ""
    reasoning: str = ""
    previous_bid: int | None = None
    accepted_bid: int | None = None  # budet spelaren svarar på (slå/skicka/syna)
    proposed: int | None = None  # rå bud från modellen
    corrected: bool = False  # korrigerades budet?
    blind: bool = False  # slog spelaren bägaren på nytt (fick inte lyfta locket)?
    choice_line: str = ""  # vid tvingad höjning: replik för titta/blint-valet
    choice_reasoning: str = ""  # vid tvingad höjning: motivering för valet
    lives_lost: int = 0  # antal förlorade liv (endast life)
    lives_left: int | None = None  # kvarvarande liv (endast life)
    actor_lives: int | None = None  # den agerandes liv vid tillfället (analys)
    active_players: int | None = None  # antal spelare kvar vid tillfället (analys)
    caller_loses: bool | None = None  # vid syn: förlorade den som synade? (analys)
    holder_name: str | None = None  # vid syn: den som ansvarar för budet (analys)
    winner_name: str | None = None  # vid game_over: vinnarens namn
    winner_role: str | None = None  # vid game_over: vinnarens rollnyckel
    standings: list[dict] | None = None  # livsställning direkt efter en syn (life)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "round": self.round,
            "dice": list(self.dice),
            "shown": self.shown,
            "shown_name": rules.name(self.shown),
            "action": self.action,
            "player": self.player,
            "player_name": self.player_name,
            "bid": self.bid,
            "bid_name": rules.name(self.bid) if self.bid is not None else None,
            "truth": self.truth,
            "lie": (not self.truth) if self.bid is not None else None,
            "line": self.line,
            "reasoning": self.reasoning,
            "previous_bid": self.previous_bid,
            "previous_bid_name": rules.name(self.previous_bid)
            if self.previous_bid is not None
            else None,
            "accepted_bid": self.accepted_bid,
            "accepted_bid_name": rules.name(self.accepted_bid)
            if self.accepted_bid is not None
            else None,
            "proposed": self.proposed,
            "corrected": self.corrected,
            "blind": self.blind,
            "choice_line": self.choice_line,
            "choice_reasoning": self.choice_reasoning,
            "lives_lost": self.lives_lost,
            "lives_left": self.lives_left,
            "actor_lives": self.actor_lives,
            "active_players": self.active_players,
            "caller_loses": self.caller_loses,
            "holder_name": self.holder_name,
            "winner_name": self.winner_name,
            "winner_role": self.winner_role,
            "standings": self.standings,
        }


@dataclass
class CallResult:
    """Utfallet av en syn."""

    bid: int
    shown: int
    caller: str
    bidder: str  # den som satte budet
    holder: str  # den som är ansvarig för budet (kan ha skickat vidare)
    caller_loses: bool
    loser: str  # namn på den som förlorar liv
    lives: int  # antal förlorade liv
    reasoning: str = ""  # synarens motivering
    line: str = ""  # synarens replik

    def to_dict(self) -> dict:
        return {
            "bid": self.bid,
            "bid_name": rules.name(self.bid),
            "shown": self.shown,
            "shown_name": rules.name(self.shown),
            "caller": self.caller,
            "bidder": self.bidder,
            "holder": self.holder,
            "caller_loses": self.caller_loses,
            "loser": self.loser,
            "lives": self.lives,
            "reasoning": self.reasoning,
            "line": self.line,
        }


@dataclass
class Session:
    """En pågående interaktiv Meier-session med flera agenter."""

    players: list[MeierPlayerAgent]
    order: list[int] = field(default_factory=list)
    round: int = 1
    lives: list[int] = field(default_factory=list)
    log: list[LogEntry] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    finished: bool = False
    result: CallResult | None = None
    #: Valfri motståndarmodell. Motorn matar den med varje händelse i takt med
    #: att den blir offentlig, så en läsande agent bara ser det en riktig spelare
    #: skulle se. ``None`` = ingen spårning.
    tracker: OpponentTracker | None = None

    # -- Steg som väntar på bekräftelse ------------------------------------
    step_kind: str = ""  # "roll", "action" eller "raise"
    pending_dice: tuple[int, int] | None = None  # det hemliga slaget (tärningar)
    pending_bid: int | None = None  # aktuellt bud
    bidder: int = 0  # spelarindex för den som satte budet
    holder: int = 0  # spelarindex för den som ansvarar för budet (kan ha skickat vidare)
    actor: int = 0  # spelarindex som ska agera
    #: Spelarindex för den som senast *annonserade* ett bud (bud/höja/slå). Det är
    #: den spelaren ett avslöjande attribueras till. Ett blint bud är ett svagare
    #: löfte, så ``bid_was_blind`` styr hur tungt avslöjandet väger.
    last_announcer: int = 0
    bid_was_blind: bool = False
    #: Sant om det stående budet kom från en **tvingad** höjning (bägaren har gått
    #: ett helt varv). En sådan är mekanisk — budgivaren måste höja vad tärningarna
    #: än visar — och får aldrig räknas in i motståndarprofilen.
    bid_was_forced: bool = False

    @classmethod
    def new(
        cls,
        players: list[MeierPlayerAgent],
        *,
        seed: int | None = None,
        lives: int = 3,
    ) -> "Session":
        if len(players) < 2:
            raise ValueError("En Meier-session kräver minst två spelare")
        rng = random.Random(seed)
        # Slumpen avgör ordningen på spelarna (och därmed vem som börjar).
        order = list(range(len(players)))
        rng.shuffle(order)
        session = cls(
            players=players,
            order=order,
            lives=[lives] * len(players),
            rng=rng,
        )
        session._prepare_round(starter=order[0])
        return session

    # -- Hjälpare -----------------------------------------------------------
    @property
    def current_player(self) -> MeierPlayerAgent:
        return self.players[self.actor]

    def name_of(self, idx: int) -> str:
        return self.players[idx].name

    def _prepare_round(self, *, starter: int) -> None:
        """Starta en ny runda: den som börjar slår och tittar i smyg.

        Tärningsutfallet loggas direkt som en egen rad (indata). Budet läggs
        sedan på som en egen rad när spelaren har svarat.
        """
        self.pending_dice = rules.roll(self.rng)
        self.step_kind = "roll"
        self.actor = starter
        self.bidder = starter
        self.holder = starter
        self.pending_bid = None
        self._log_roll(
            player=self.players[starter].name,
            dice=self.pending_dice,
            shown=rules.read_dice(*self.pending_dice),
        )

    def _log_roll(self, *, player: str, dice: tuple[int, int], shown: int) -> LogEntry:
        """Logga ett tärningsutfall som en egen rad (indata till spelaren)."""
        entry = LogEntry(
            kind="roll",
            round=self.round,
            dice=dice,
            shown=shown,
            player_name=player,
        )
        self.log.append(entry)
        return entry

    def _prepare_action(self, *, actor: int) -> None:
        """Nästa spelare ska agera mot ett bud (slå/syna/skicka)."""
        self.actor = actor
        self.step_kind = "action"

    def _prepare_raise(self) -> None:
        """Budgivaren måste höja efter ett helt varv."""
        self.actor = self.bidder
        self.step_kind = "raise"

    def _next_actor(self, idx: int) -> int:
        """Nästa spelare i sittordning som fortfarande är med."""
        pos = self.order.index(idx)
        n = len(self.order)
        for step in range(1, n + 1):
            cand = self.order[(pos + step) % n]
            if self.lives[cand] > 0:
                return cand
        return idx

    def _previous_active(self, idx: int) -> int:
        """Närmaste spelare före ``idx`` i sittordning som fortfarande är med."""
        pos = self.order.index(idx)
        n = len(self.order)
        for step in range(1, n + 1):
            cand = self.order[(pos - step) % n]
            if self.lives[cand] > 0:
                return cand
        return idx

    def _active_indices(self) -> list[int]:
        return [i for i in self.order if self.lives[i] > 0]

    # -- Motståndarmodell: mata spåraren när något blir offentligt ----------
    def _notify_bid(self, player_name: str, *, blind: bool, forced: bool = False) -> None:
        if self.tracker is not None:
            self.tracker.observe_bid(player_name, blind=blind, forced=forced)

    def _notify_decision(self, player_name: str, action: str) -> None:
        if self.tracker is not None:
            self.tracker.observe_decision(player_name, action)

    def _notify_reveal(
        self, announcer_idx: int, *, blind: bool, forced: bool, was_bluff: bool
    ) -> None:
        """Facit efter en syn. Tvingade höjningar är mekaniska och hoppas över —
        de säger inget om spelarens benägenhet (se :class:`OpponentTracker`)."""
        if self.tracker is not None:
            self.tracker.reveal(
                self.name_of(announcer_idx),
                was_bluff=was_bluff,
                blind=blind,
                forced=forced,
            )

    def _ask_decide(self, player, bid: int):
        """Fråga spelaren om ett bud och skicka med vem som håller det.

        Den som överväger att syna får veta *vem* den möter, så en läsande agent
        kan använda motståndarens profil. Icke-läsande agenter ignorerar det.
        """
        return player.decide(
            bid, lives=self.lives[self.actor], opponent=self.name_of(self.holder)
        )

    def _log_game_over(self) -> LogEntry | None:
        """Logga en egen rad när matchen är slut och en vinnare står kvar."""
        alive = self._active_indices()
        if len(alive) != 1:
            return None
        winner_idx = alive[0]
        entry = LogEntry(
            kind="game_over",
            round=self.round,
            dice=self.pending_dice or (1, 1),
            shown=rules.read_dice(*(self.pending_dice or (1, 1))),
            action="slut",
            player=self.players[winner_idx].role.key,
            player_name=self.name_of(winner_idx),
            winner_name=self.name_of(winner_idx),
            winner_role=self.players[winner_idx].role.key,
            active_players=1,
        )
        self.log.append(entry)
        return entry

    def _finish(self) -> None:
        self.finished = True
        self.step_kind = ""
        self._log_game_over()
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

    def play_to_end(self, *, max_steps: int = 20000) -> LogEntry | None:
        """Spela hela sessionen klart, runda för runda, utan grind.

        Används för batchkörning av många matcher. Returnerar den sista
        loggposten. Ett skyddsnät stoppar efter ``max_steps`` steg.
        """
        last: LogEntry | None = None
        steps = 0
        while not self.finished and self.step_kind and steps < max_steps:
            steps += 1
            last = self.advance()
        return last

    def run_to_end(self, *, max_steps: int = 20000) -> list[LogEntry]:
        """Spela hela matchen klart och returnera alla nya loggposter.

        Samma flöde som ``play_to_end``, men avsett för den interaktiva
        sessionen: grindens steg bekräftas automatiskt tills någon står kvar
        som vinnare. Ett skyddsnät stoppar efter ``max_steps`` steg.
        """
        created: list[LogEntry] = []
        steps = 0
        while not self.finished and self.step_kind and steps < max_steps:
            steps += 1
            entry = self.advance()
            if entry is not None:
                created.append(entry)
        return created

    def run_to_round_end(self, *, max_steps: int = 200) -> list[LogEntry]:
        """Kör flödet fram till rundans slut.

        En runda tar slut när någon synar (någon förlorar ett liv) eller när
        budet Meier går ett helt varv tillbaka och budgivaren slår om. Båda
        fallen startar en ny runda, så vi kör tills rundnumret ändras – eller
        tills spelet tar slut.
        """
        created: list[LogEntry] = []
        start_round = self.round
        steps = 0
        while not self.finished and self.step_kind and steps < max_steps:
            steps += 1
            entry = self.advance()
            if entry is not None:
                created.append(entry)
            if self.round != start_round:
                break
        return created

    # -- Steg 1: tärningsslaget (första budet) -----------------------------
    def _resolve_roll(self) -> LogEntry:
        dice = self.pending_dice
        assert dice is not None
        player = self.players[self.actor]
        ann = player.announce(dice)
        self._notify_bid(player.name, blind=False)
        entry = self._log_entry(
            player, dice, ann, action="bud", previous_bid=None, blind=False, actor_idx=self.actor
        )
        self.pending_bid = ann.bid
        self.bidder = self.actor
        self.holder = self.actor
        self.last_announcer = self.actor
        self.bid_was_blind = False
        self.bid_was_forced = False
        self._prepare_action(actor=self._next_actor(self.actor))
        return entry

    # -- Steg 2: slå, syna eller skicka vidare -----------------------------
    def _resolve_action(self) -> LogEntry | None:
        bid = self.pending_bid
        assert bid is not None
        player = self.players[self.actor]
        decision = self._ask_decide(player, bid)

        if decision.action == "syna":
            self._notify_decision(player.name, "syna")
            return self._resolve_call(player, decision)

        if decision.action == "slå":
            self._notify_decision(player.name, "slå")
            # Spelaren skakar bägaren på nytt: ett färskt slag, och locket lyfts inte.
            dice = rules.roll(self.rng)
            self._log_roll(player=player.name, dice=dice, shown=rules.read_dice(*dice))
            ann = player.announce_blind(dice, previous_bid=bid)
            ann = self._enforce_bid(ann, previous_bid=bid)
            self._notify_bid(player.name, blind=True)
            entry = self._log_entry(
                player,
                dice,
                ann,
                action="slå",
                previous_bid=bid,
                blind=True,
                accepted_bid=bid,
                actor_idx=self.actor,
            )
            self.pending_dice = dice
            self.pending_bid = ann.bid
            self.bidder = self.actor
            self.holder = self.actor
            self.last_announcer = self.actor
            self.bid_was_blind = True
            self.bid_was_forced = False
            self._after_bid(actor=self.actor)
            return entry

        # Skicka vidare: samma bud går vidare. Spelaren tar över ansvaret för budet.
        self._notify_decision(player.name, "skicka")
        entry = LogEntry(
            kind="action",
            round=self.round,
            dice=self.pending_dice or (1, 1),
            shown=rules.read_dice(*(self.pending_dice or (1, 1))),
            player=player.role.key,
            player_name=player.name,
            bid=bid,
            truth=False,
            line=decision.line,
            reasoning=decision.reasoning,
            action="skicka",
            previous_bid=bid,
            accepted_bid=bid,
            actor_lives=self.lives[self.actor],
            active_players=len(self._active_indices()),
        )
        self.log.append(entry)
        self.holder = self.actor
        self._after_bid(actor=self.actor)
        return entry

    # -- Steg 3: tvingad höjning när bägaren gått ett helt varv ------------
    def _resolve_raise(self) -> LogEntry:
        bid = self.pending_bid
        assert bid is not None
        player = self.players[self.bidder]
        # Tärningarna slås om när bägaren gått ett helt varv. Budgivaren väljer
        # själv om den tittar på dem eller bjuder blint (som vid ett slag).
        dice = rules.roll(self.rng)
        self._log_roll(player=player.name, dice=dice, shown=rules.read_dice(*dice))
        ann = player.announce_forced(dice, previous_bid=bid)
        ann = self._enforce_bid(ann, previous_bid=bid)
        # Tvingad höjning: mekanisk, räknas separat i motståndarprofilen.
        self._notify_bid(player.name, blind=ann.blind, forced=True)
        entry = self._log_entry(
            player,
            dice,
            ann,
            action="höja",
            previous_bid=bid,
            blind=ann.blind,
            actor_idx=self.bidder,
            choice_line=ann.choice_line,
            choice_reasoning=ann.choice_reasoning,
        )
        self.pending_dice = dice
        self.pending_bid = ann.bid
        self.holder = self.bidder
        self.last_announcer = self.bidder
        self.bid_was_blind = ann.blind
        self.bid_was_forced = True
        self._after_bid(actor=self.bidder)
        return entry

    def _enforce_bid(self, ann, *, previous_bid: int):
        """Se till att ett bud som står kvar är strikt högre än det förra.

        Spelaragenten korrigerar redan ett olagligt bud (se
        ``MeierPlayerAgent._coerce_bid``), men budet som *står* får aldrig vara
        lägre än det förra. Minsta lagliga höjning tar över i så fall, och
        ``corrected`` markeras så att loggen visar att budet rättades.
        """
        if rules.is_valid_value(ann.bid) and rules.is_higher(ann.bid, previous_bid):
            return ann
        higher = rules.higher_options(previous_bid)
        if not higher:
            # Ingen höjning finns (budet är Meier) – kan inte korrigeras här.
            return ann
        return replace(ann, bid=higher[-1], truth=False, corrected=True)

    def _after_bid(self, *, actor: int) -> None:
        """Efter ett bud: gå vidare till nästa spelare – eller hela varvet runt."""
        nxt = self._next_actor(actor)
        if nxt == self.bidder:
            if rules.is_meier(self.pending_bid):
                # Budet är Meier – budgivaren slår om och börjar en ny runda.
                starter = self.bidder
                self.round += 1
                self._prepare_round(starter=starter)
            else:
                self._prepare_raise()
        else:
            self._prepare_action(actor=nxt)

    # -- Steg 4: synen -----------------------------------------------------
    def _resolve_call(self, caller_agent: MeierPlayerAgent, decision=None) -> LogEntry:
        bid = self.pending_bid
        dice = self.pending_dice
        assert bid is not None and dice is not None
        shown = rules.read_dice(*dice)
        caller_idx = self.actor
        # Den som ansvarar för budet: den som sa det senast (eller skickade
        # vidare och därmed tog över ansvaret). Det är den "föregående spelaren"
        # i regeln, inte nödvändigtvis den som först satte budet.
        holder_idx = self.holder

        result = rules.resolve_call(bid, shown)
        loser_idx = caller_idx if result.caller_loses else holder_idx
        self.lives[loser_idx] = max(0, self.lives[loser_idx] - result.lives)

        entry = LogEntry(
            kind="action",
            round=self.round,
            dice=dice,
            shown=shown,
            player=caller_agent.role.key,
            player_name=caller_agent.name,
            bid=bid,
            truth=False,
            line=getattr(decision, "line", "") or "",
            reasoning=getattr(decision, "reasoning", "") or "",
            action="syna",
            previous_bid=bid,
            accepted_bid=bid,
            actor_lives=self.lives[caller_idx],
            active_players=len(self._active_indices()),
            caller_loses=result.caller_loses,
            holder_name=self.name_of(holder_idx),
        )
        self.log.append(entry)

        # En egen rad om det förlorade livet, direkt efter synen.
        self._log_life(loser_idx, result.lives, active_players=len(self._active_indices()))

        self.result = CallResult(
            bid=bid,
            shown=shown,
            caller=self.name_of(caller_idx),
            bidder=self.name_of(self.bidder),
            holder=self.name_of(holder_idx),
            caller_loses=result.caller_loses,
            loser=self.name_of(loser_idx),
            lives=result.lives,
            reasoning=getattr(decision, "reasoning", "") or "",
            line=getattr(decision, "line", "") or "",
        )

        # Facit är nu offentligt — tärningarna ligger på bordet. Först nu får
        # motståndarmodellen veta om det senaste budet var en bluff. Ett blint bud
        # är inget löfte och avslöjas aldrig (se ``_notify_reveal``).
        self._notify_reveal(
            self.last_announcer,
            blind=self.bid_was_blind,
            forced=self.bid_was_forced,
            was_bluff=(bid != shown),
        )
        if self.tracker is not None:
            self.tracker.record_call_outcome(
                self.name_of(caller_idx), won=not result.caller_loses
            )

        if len(self._active_indices()) <= 1:
            self._finish()
            return entry

        # Nästa runda: bägaren går till föregående spelare (före den som förlorade
        # livet), som slår och börjar en ny runda.
        self.round += 1
        self._prepare_round(starter=self._previous_active(loser_idx))
        return entry

    def _log_life(self, loser_idx: int, lost: int, *, active_players: int | None = None) -> LogEntry:
        """Logga en egen rad när någon förlorar ett (eller två) liv."""
        entry = LogEntry(
            kind="life",
            round=self.round,
            dice=self.pending_dice or (1, 1),
            shown=rules.read_dice(*(self.pending_dice or (1, 1))),
            action="liv",
            player=self.players[loser_idx].role.key,
            player_name=self.name_of(loser_idx),
            lives_lost=lost,
            lives_left=self.lives[loser_idx],
            active_players=active_players,
            standings=self._standings(),
        )
        self.log.append(entry)
        return entry

    # -- Hjälpare för loggposter -------------------------------------------
    def _log_entry(
        self,
        player: MeierPlayerAgent,
        dice: tuple[int, int],
        ann,
        *,
        action: str,
        previous_bid: int | None,
        blind: bool,
        accepted_bid: int | None = None,
        actor_idx: int | None = None,
        choice_line: str = "",
        choice_reasoning: str = "",
    ) -> LogEntry:
        entry = LogEntry(
            kind="action",
            round=self.round,
            player=player.role.key,
            player_name=player.name,
            dice=dice,
            shown=ann.shown,
            bid=ann.bid,
            truth=ann.truth,
            line=ann.line,
            reasoning=ann.reasoning,
            action=action,
            previous_bid=previous_bid,
            accepted_bid=accepted_bid,
            proposed=ann.proposed,
            corrected=ann.corrected,
            blind=blind,
            choice_line=choice_line,
            choice_reasoning=choice_reasoning,
            actor_lives=self.lives[actor_idx] if actor_idx is not None else None,
            active_players=len(self._active_indices()),
        )
        self.log.append(entry)
        return entry

    def stop(self) -> None:
        self.finished = True
        self.step_kind = ""
        self.pending_dice = None
        self.pending_bid = None

    def _standings(self) -> list[dict]:
        """Livsställning per spelare i spelordning (för sammanställningen)."""
        return [
            {
                "name": self.players[i].name,
                "role": self.players[i].role.key,
                "lives": self.lives[i],
                "active": self.lives[i] > 0,
            }
            for i in self.order
        ]

    def _winner(self) -> dict | None:
        """Vinnaren när matchen är slut (en spelare kvar), annars None."""
        alive = self._active_indices()
        if len(alive) != 1:
            return None
        idx = alive[0]
        return {"name": self.name_of(idx), "role": self.players[idx].role.key}

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
                pending["holder"] = self.name_of(self.holder)

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
            "starter": self.name_of(self.order[0]),
            "current": {
                "name": self.current_player.name,
                "role": self.current_player.role.key,
            }
            if self.step_kind
            else None,
            "step_kind": self.step_kind,
            "pending": pending,
            "result": self.result.to_dict() if self.result else None,
            "standings": self._standings(),
            "winner": self._winner(),
            "log": [e.to_dict() for e in self.log],
        }

    def _phase(self) -> str:
        if self.finished:
            return "finished"
        return "awaiting_ok"
