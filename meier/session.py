"""Interaktiv spelsession för Meier – ett fullt flöde fram till en syn.

Flera oberoende agenter spelar mot varandra, steg för steg. Slumpen avgör
ordningen på spelarna och vem som börjar. Varje svar sparas i en logg med
tärningsutfallet, vem som svarade och vad spelaren svarade.

Flödet följer reglerna:

1. Första spelaren slår och **tittar i smyg** – säger sanningen, ett högre eller
   ett lägre resultat.
2. Nästa spelare väljer **Slå** (skakar bägaren på nytt och säger ett högre påstående),
   **Syna** (lyfter locket) eller **Skicka vidare** (samma påstående).
3. När bägaren kommer ett helt varv tillbaka till den som påstod måste denne höja.
   Är påståendet Meier får spelaren i stället slå om och börja en ny runda.
4. Vid en syn lyfts locket: visar tärningarna lägre än påståendet förlorar den
   spelare som ansvarar för påståendet (den som sa det senast, eller skickade vidare
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
    - ``kind == "action"``: en spelares svar – ett påstående (efter titt eller
      utan att titta), ett slag, en syn eller ett skickande.
    - ``kind == "life"``: någon har förlorat ett (eller två) liv efter en syn.
      Raden ligger direkt efter synen och visar hur många liv som är kvar.
    - ``kind == "game_over"``: matchen är slut och en vinnare står kvar. Sista
      raden i loggen. ``winner_name`` och ``winner_role`` anger vinnaren.
    """

    kind: str  # "roll", "action", "life" eller "game_over"
    round: int
    dice: tuple[int, int]
    shown: int
    action: str = "påstå"  # "påstå", "slå", "skicka", "syna", "höja", "liv", "slut"
    player: str | None = None  # rollens nyckel (endast action/life)
    player_name: str | None = None
    claim: int | None = None  # sagt påstående (endast action)
    truth: bool = False
    line: str = ""
    reasoning: str = ""
    previous_claim: int | None = None
    accepted_claim: int | None = None  # påståendet spelaren svarar på (slå/skicka/syna)
    proposed: int | None = None  # rått påstående från modellen
    corrected: bool = False  # korrigerades påståendet?
    unseen: bool = False  # slog spelaren bägaren på nytt (fick inte lyfta locket)?
    choice_line: str = ""  # vid tvingad höjning: replik för valet att titta eller inte
    choice_reasoning: str = ""  # vid tvingad höjning: motivering för valet
    lives_lost: int = 0  # antal förlorade liv (endast life)
    lives_left: int | None = None  # kvarvarande liv (endast life)
    actor_lives: int | None = None  # den agerandes liv vid tillfället (analys)
    active_players: int | None = None  # antal spelare kvar vid tillfället (analys)
    caller_loses: bool | None = None  # vid syn: förlorade den som synade? (analys)
    holder_name: str | None = None  # vid syn: den som ansvarar för påståendet (analys)
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
            "claim": self.claim,
            "claim_name": rules.name(self.claim) if self.claim is not None else None,
            "truth": self.truth,
            "lie": (not self.truth) if self.claim is not None else None,
            "line": self.line,
            "reasoning": self.reasoning,
            "previous_claim": self.previous_claim,
            "previous_claim_name": rules.name(self.previous_claim)
            if self.previous_claim is not None
            else None,
            "accepted_claim": self.accepted_claim,
            "accepted_claim_name": rules.name(self.accepted_claim)
            if self.accepted_claim is not None
            else None,
            "proposed": self.proposed,
            "corrected": self.corrected,
            "unseen": self.unseen,
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

    claim: int
    shown: int
    caller: str
    claimer: str  # den som satte påståendet
    holder: str  # den som är ansvarig för påståendet (kan ha skickat vidare)
    caller_loses: bool
    loser: str  # namn på den som förlorar liv
    lives: int  # antal förlorade liv
    reasoning: str = ""  # synarens motivering
    line: str = ""  # synarens replik

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "claim_name": rules.name(self.claim),
            "shown": self.shown,
            "shown_name": rules.name(self.shown),
            "caller": self.caller,
            "claimer": self.claimer,
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
    pending_claim: int | None = None  # aktuellt påstående
    claimer: int = 0  # spelarindex för den som satte påståendet
    holder: int = 0  # spelarindex för den som ansvarar för påståendet (kan ha skickat vidare)
    actor: int = 0  # spelarindex som ska agera
    #: Spelarindex för den som senast *annonserade* ett påstående (påstående/höja/slå). Det är
    #: den spelaren ett avslöjande attribueras till. Ett påstående utan att titta är ett svagare
    #: löfte, så ``claim_was_unseen`` styr hur tungt avslöjandet väger.
    last_announcer: int = 0
    claim_was_unseen: bool = False
    #: Sant om det stående påståendet kom från en **tvingad** höjning (bägaren har gått
    #: ett helt varv). En sådan är mekanisk — den som påstod måste höja vad tärningarna
    #: än visar — och får aldrig räknas in i motståndarprofilen.
    claim_was_forced: bool = False

    @classmethod
    def new(
        cls,
        players: list[MeierPlayerAgent],
        *,
        lives: int = 3,
    ) -> "Session":
        if len(players) < 2:
            raise ValueError("En Meier-session kräver minst två spelare")
        session = cls(
            players=players,
            order=list(range(len(players))),
            lives=[lives] * len(players),
        )
        # Slumpen avgör ordningen på spelarna (och därmed vem som börjar).
        session.rng.shuffle(session.order)
        session._prepare_round(starter=session.order[0])
        return session

    # -- Hjälpare -----------------------------------------------------------
    @property
    def current_player(self) -> MeierPlayerAgent:
        return self.players[self.actor]

    def name_of(self, idx: int) -> str:
        return self.players[idx].name

    def _prepare_round(self, *, starter: int) -> None:
        """Starta en ny runda: den som börjar slår och tittar i smyg.

        Tärningsutfallet loggas direkt som en egen rad (indata). Påståendet läggs
        sedan på som en egen rad när spelaren har svarat.
        """
        self.pending_dice = rules.roll(self.rng)
        self.step_kind = "roll"
        self.actor = starter
        self.claimer = starter
        self.holder = starter
        self.pending_claim = None
        self._log_roll(
            player=self.players[starter].name,
            dice=self.pending_dice,
            shown=rules.read_dice(*self.pending_dice),
        )

    def _log_roll(self, *, player: str, dice: tuple[int, int], shown: int) -> LogEntry:
        """Logga ett tärningsutfall som en egen rad (indata till spelaren).

        ``action`` sätts till ``"slag"`` med flit. Standardvärdet är ``"påstå"``,
        och då räknades rena tärningsrader som påståenden i analysen.
        """
        entry = LogEntry(
            kind="roll",
            round=self.round,
            dice=dice,
            shown=shown,
            action="slag",
            player_name=player,
        )
        self.log.append(entry)
        return entry

    def _prepare_action(self, *, actor: int) -> None:
        """Nästa spelare ska agera mot ett påstående (slå/syna/skicka)."""
        self.actor = actor
        self.step_kind = "action"

    def _prepare_raise(self) -> None:
        """Hållaren måste höja efter ett helt varv."""
        self.actor = self.claimer
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
    def _notify_claim(self, player_name: str, *, unseen: bool, forced: bool = False) -> None:
        if self.tracker is not None:
            self.tracker.observe_claim(player_name, unseen=unseen, forced=forced)

    def _notify_decision(self, player_name: str, action: str) -> None:
        if self.tracker is not None:
            self.tracker.observe_decision(player_name, action)

    def _notify_reveal(
        self, announcer_idx: int, *, unseen: bool, forced: bool, was_bluff: bool
    ) -> None:
        """Facit efter en syn. Tvingade höjningar är mekaniska och hoppas över —
        de säger inget om spelarens benägenhet (se :class:`OpponentTracker`)."""
        if self.tracker is not None:
            self.tracker.reveal(
                self.name_of(announcer_idx),
                was_bluff=was_bluff,
                unseen=unseen,
                forced=forced,
            )

    def _ask_decide(self, player, claim: int):
        """Fråga spelaren om ett påstående och skicka med vem som håller det.

        Den som överväger att syna får veta *vem* den möter, så en läsande agent
        kan använda motståndarens profil. Icke-läsande agenter ignorerar det.
        """
        return player.decide(
            claim, lives=self.lives[self.actor], opponent=self.name_of(self.holder)
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
        self.pending_claim = None

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

    def play_to_end(
        self,
        *,
        max_steps: int = 20000,
        on_round: "callable[[int, int], None] | None" = None,
    ) -> LogEntry | None:
        """Spela hela sessionen klart, runda för runda, utan grind.

        Används för batchkörning av många matcher. Returnerar den sista
        loggposten. Ett skyddsnät stoppar efter ``max_steps`` steg.

        ``on_round(runda, kvar)`` anropas när en ny runda tar vid, så att en
        pågående match kan visas levande i stället för att se ut att ha fastnat.
        """
        last: LogEntry | None = None
        steps = 0
        round_no = self.round
        while not self.finished and self.step_kind and steps < max_steps:
            steps += 1
            last = self.advance()
            if on_round is not None and self.round != round_no:
                round_no = self.round
                on_round(round_no, len(self._active_indices()))
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
        påståendet Meier går ett helt varv tillbaka och den som påstod slår om. Båda
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

    # -- Steg 1: tärningsslaget (första påståendet) -----------------------------
    def _resolve_roll(self) -> LogEntry:
        dice = self.pending_dice
        assert dice is not None
        player = self.players[self.actor]
        # Den som sitter näst efter är den som först får svara på påståendet.
        ann = player.announce(dice, opponent=self.name_of(self._next_actor(self.actor)))
        self._notify_claim(player.name, unseen=False)
        entry = self._log_entry(
            player, dice, ann, action="påstå", previous_claim=None, unseen=False, actor_idx=self.actor
        )
        self.pending_claim = ann.claim
        self.claimer = self.actor
        self.holder = self.actor
        self.last_announcer = self.actor
        self.claim_was_unseen = False
        self.claim_was_forced = False
        self._prepare_action(actor=self._next_actor(self.actor))
        return entry

    # -- Steg 2: slå, syna eller skicka vidare -----------------------------
    def _resolve_action(self) -> LogEntry | None:
        claim = self.pending_claim
        assert claim is not None
        player = self.players[self.actor]
        decision = self._ask_decide(player, claim)

        if decision.action == "syna":
            self._notify_decision(player.name, "syna")
            return self._resolve_call(player, decision)

        if decision.action == "slå":
            self._notify_decision(player.name, "slå")
            # Spelaren skakar bägaren på nytt. Reglerna låter spelaren lyfta på
            # locket på sitt eget slag; att avstå är ett eget val (fintaktik).
            dice = rules.roll(self.rng)
            self._log_roll(player=player.name, dice=dice, shown=rules.read_dice(*dice))
            ann = player.announce_shake(
                dice, previous_claim=claim, opponent=self.name_of(self._next_actor(self.actor))
            )
            ann = self._enforce_claim(ann, previous_claim=claim)
            self._notify_claim(player.name, unseen=ann.unseen)
            entry = self._log_entry(
                player,
                dice,
                ann,
                action="slå",
                previous_claim=claim,
                unseen=ann.unseen,
                accepted_claim=claim,
                actor_idx=self.actor,
                choice_line=ann.choice_line,
                choice_reasoning=ann.choice_reasoning,
            )
            self.pending_dice = dice
            self.pending_claim = ann.claim
            self.claimer = self.actor
            self.holder = self.actor
            self.last_announcer = self.actor
            self.claim_was_unseen = ann.unseen
            self.claim_was_forced = False
            self._after_claim(actor=self.actor)
            return entry

        # Skicka vidare: samma påstående går vidare. Spelaren tar över ansvaret för påståendet.
        self._notify_decision(player.name, "skicka")
        entry = LogEntry(
            kind="action",
            round=self.round,
            dice=self.pending_dice or (1, 1),
            shown=rules.read_dice(*(self.pending_dice or (1, 1))),
            player=player.role.key,
            player_name=player.name,
            claim=claim,
            # Spelaren sa inget eget bud, men bär nu budet. Flaggan beskriver
            # därför budet mot tärningarna – inte spelaren – och ska inte sättas
            # till False rakt av, då ser varje vidarebefordran ut som en lögn.
            truth=rules.is_true_claim(
                claim, rules.read_dice(*(self.pending_dice or (1, 1)))
            ),
            line=decision.line,
            reasoning=decision.reasoning,
            action="skicka",
            previous_claim=claim,
            accepted_claim=claim,
            actor_lives=self.lives[self.actor],
            active_players=len(self._active_indices()),
        )
        self.log.append(entry)
        self.holder = self.actor
        self._after_claim(actor=self.actor)
        return entry

    # -- Steg 3: tvingad höjning när bägaren gått ett helt varv ------------
    def _resolve_raise(self) -> LogEntry:
        claim = self.pending_claim
        assert claim is not None
        player = self.players[self.claimer]
        # Tärningarna slås om när bägaren gått ett helt varv. Hållaren väljer
        # själv om den tittar på dem eller påstår utan att titta (som vid ett slag).
        dice = rules.roll(self.rng)
        self._log_roll(player=player.name, dice=dice, shown=rules.read_dice(*dice))
        ann = player.announce_forced(
            dice, previous_claim=claim, opponent=self.name_of(self._next_actor(self.claimer))
        )
        ann = self._enforce_claim(ann, previous_claim=claim)
        # Tvingad höjning: mekanisk, räknas separat i motståndarprofilen.
        self._notify_claim(player.name, unseen=ann.unseen, forced=True)
        entry = self._log_entry(
            player,
            dice,
            ann,
            action="höja",
            previous_claim=claim,
            unseen=ann.unseen,
            actor_idx=self.claimer,
            choice_line=ann.choice_line,
            choice_reasoning=ann.choice_reasoning,
        )
        self.pending_dice = dice
        self.pending_claim = ann.claim
        self.holder = self.claimer
        self.last_announcer = self.claimer
        self.claim_was_unseen = ann.unseen
        self.claim_was_forced = True
        self._after_claim(actor=self.claimer)
        return entry

    def _enforce_claim(self, ann, *, previous_claim: int):
        """Se till att ett påstående som står kvar är strikt högre än det förra.

        Spelaragenten korrigerar redan ett olagligt påstående (se
        ``MeierPlayerAgent._coerce_claim``), men påståendet som *står* får aldrig vara
        lägre än det förra. Minsta lagliga höjning tar över i så fall, och
        ``corrected`` markeras så att loggen visar att påståendet rättades.
        """
        if rules.is_valid_value(ann.claim) and rules.is_higher(ann.claim, previous_claim):
            return ann
        higher = rules.higher_options(previous_claim)
        if not higher:
            # Ingen höjning finns (påståendet är Meier) – kan inte korrigeras här.
            return ann
        return replace(ann, claim=higher[-1], truth=False, corrected=True)

    def _after_claim(self, *, actor: int) -> None:
        """Efter ett påstående: gå vidare till nästa spelare – eller hela varvet runt."""
        nxt = self._next_actor(actor)
        if nxt == self.claimer:
            if rules.is_meier(self.pending_claim):
                # Påståendet är Meier – den som påstod slår om och börjar en ny runda.
                starter = self.claimer
                self.round += 1
                self._prepare_round(starter=starter)
            else:
                self._prepare_raise()
        else:
            self._prepare_action(actor=nxt)

    # -- Steg 4: synen -----------------------------------------------------
    def _resolve_call(self, caller_agent: MeierPlayerAgent, decision=None) -> LogEntry:
        claim = self.pending_claim
        dice = self.pending_dice
        assert claim is not None and dice is not None
        shown = rules.read_dice(*dice)
        caller_idx = self.actor
        # Den som ansvarar för påståendet: den som sa det senast (eller skickade
        # vidare och därmed tog över ansvaret). Det är den "föregående spelaren"
        # i regeln, inte nödvändigtvis den som först satte påståendet.
        holder_idx = self.holder

        result = rules.resolve_call(claim, shown)
        loser_idx = caller_idx if result.caller_loses else holder_idx
        self.lives[loser_idx] = max(0, self.lives[loser_idx] - result.lives)

        entry = LogEntry(
            kind="action",
            round=self.round,
            dice=dice,
            shown=shown,
            player=caller_agent.role.key,
            player_name=caller_agent.name,
            claim=claim,
            truth=False,
            line=getattr(decision, "line", "") or "",
            reasoning=getattr(decision, "reasoning", "") or "",
            action="syna",
            previous_claim=claim,
            accepted_claim=claim,
            actor_lives=self.lives[caller_idx],
            active_players=len(self._active_indices()),
            caller_loses=result.caller_loses,
            holder_name=self.name_of(holder_idx),
        )
        self.log.append(entry)

        # En egen rad om det förlorade livet, direkt efter synen.
        self._log_life(loser_idx, result.lives, active_players=len(self._active_indices()))

        self.result = CallResult(
            claim=claim,
            shown=shown,
            caller=self.name_of(caller_idx),
            claimer=self.name_of(self.claimer),
            holder=self.name_of(holder_idx),
            caller_loses=result.caller_loses,
            loser=self.name_of(loser_idx),
            lives=result.lives,
            reasoning=getattr(decision, "reasoning", "") or "",
            line=getattr(decision, "line", "") or "",
        )

        # Facit är nu offentligt — tärningarna ligger på bordet. Först nu får
        # motståndarmodellen veta om det senaste påståendet var en bluff. Ett påstående utan att titta
        # är inget löfte och avslöjas aldrig (se ``_notify_reveal``).
        self._notify_reveal(
            self.last_announcer,
            unseen=self.claim_was_unseen,
            forced=self.claim_was_forced,
            was_bluff=(claim != shown),
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
        previous_claim: int | None,
        unseen: bool,
        accepted_claim: int | None = None,
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
            claim=ann.claim,
            truth=ann.truth,
            line=ann.line,
            reasoning=ann.reasoning,
            action=action,
            previous_claim=previous_claim,
            accepted_claim=accepted_claim,
            proposed=ann.proposed,
            corrected=ann.corrected,
            unseen=unseen,
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
        self.pending_claim = None

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
            if self.pending_claim is not None:
                pending["claim"] = self.pending_claim
                pending["claim_name"] = rules.name(self.pending_claim)
                pending["claimer"] = self.name_of(self.claimer)
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
            "views": self._views(),
            "log": [e.to_dict() for e in self.log],
        }

    def _views(self) -> list[dict]:
        """Vad varje agent tror om de andra, för insyn i webbappen.

        En agent har en ``profiles``-mapp (motståndarnamn → profil). Den fylls
        när agenten svarar på ett påstående. Läsande agenter listas därför i takt med
        att de får en bild; Axel (ingen läsning) får aldrig någon.
        """
        views = []
        for idx in self.order:
            player = self.players[idx]
            profiles = getattr(player, "profiles", None)
            if not profiles:
                continue
            # Bara bilder som vilar på något: en profil utan underlag säger
            # inget och skulle bara skräpa i listan.
            shown = [
                (opp, prof)
                for opp, prof in profiles.items()
                if prof.source != "population"
            ]
            if not shown:
                continue
            views.append(
                {
                    "agent": player.name,
                    "role": player.role.key,
                    "profiles": [
                        {
                            "opponent": opp,
                            "profile": prof.to_dict(),
                            "text": prof.describe(),
                        }
                        for opp, prof in shown
                    ],
                }
            )
        return views

    def _phase(self) -> str:
        if self.finished:
            return "finished"
        return "awaiting_ok"
