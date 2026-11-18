"""Strategisk spelaragent: deterministisk policy + läckagefri motståndarmodell.

Till skillnad från :class:`~meier.agents.player.MeierPlayerAgent` avgörs draget
här av :class:`~meier.policy.BasePolicy`, inte av LLM:en. LLM:en är valfri och
används bara för repliken — den kan **föreslå en formulering** men aldrig ändra
draget. Motiveringen som sparas är alltid policyns maskinella skäl, så det går
att se *varför* ett drag togs. Det är förutsättningen för att kunna mäta vilka
parametrar som vinner (se ``docs/agent-model.md``).

Agenten implementerar samma gränssnitt som motorn använder
(``announce``, ``announce_blind``, ``announce_forced``, ``decide``) och returnerar
motorns egna typer, så den kan sättas in i ``Session`` utan andra ändringar.
"""

from __future__ import annotations

from dataclasses import replace

from .. import rules
from ..llm import LLMClient, parse_json_object
from ..opponents import OpponentTracker
from ..policy import AgentParams, BasePolicy
from .base import Agent, Role
from .player import ActionDecision, Announcement

#: Kompakt regeltext för replikprompten. Den påverkar inte draget.
_RULES = (
    "Två tärningar läses med högsta först (2 och 5 blir 52). 21 kallas Meier och "
    "är högst, sedan faller ordningen ner till 31. Vid en syn: visar tärningarna "
    "lägre än budet förlorar budgivaren ett liv, annars synaren. Meier kostar "
    "dubbelt."
)


class StrategicAgent(Agent):
    """En Meier-spelare som styrs av en deterministisk policy.

    ``tracker`` är valfri. Utan den läser agenten ingen motståndare och faller
    tillbaka på policyns globala ``q``. Med en tracker används motståndarnas
    avslöjade beteende, skalat av parametern ``reading``.

    ``llm`` är valfri och används **endast** för att formulera repliken. Saknas
    den blir repliken mekanisk (``"Jag säger 52."``), vilket är vad utvärderingen
    kör med — då går en match på millisekunder i stället för minuter.
    """

    def __init__(
        self,
        role: Role,
        params: AgentParams,
        *,
        tracker: OpponentTracker | None = None,
        policy: BasePolicy | None = None,
        llm: LLMClient | None = None,
    ):
        # Ingen LLM-klient skapas om ingen ges: agenten kan spela utan nätverk.
        self.role = role
        self.llm = llm
        self.params = params
        self.tracker = tracker
        self.policy = policy or BasePolicy(params)

    # -- Replik -----------------------------------------------------------
    def system_prompt(self) -> str:
        return (
            f"Du spelar tärningsspelet Meier som spelaren {self.role.name}. "
            f"{self.role.description}\n"
            f"REGLER: {_RULES}\n"
            "Din strategi har redan bestämt draget. Du formulerar bara en kort, "
            "naturlig replik på svenska (högst en mening) som spelaren säger.\n"
            "Repliken måste stämma med draget. Säg aldrig något som motsäger det "
            "(t.ex. tala inte om att höja när draget är att skicka vidare).\n"
            'Svara med JSON: {"line": "<replik>"}.'
        )

    def _narrate(self, situation: str, fallback: str) -> str:
        """Låt LLM:en formulera repliken. Misslyckas det används ``fallback``.

        Repliken får aldrig påverka draget, och ett LLM-fel får aldrig fälla en
        match. Därför fångas allt och den mekaniska repliken används i stället.
        """
        if self.llm is None:
            return fallback
        try:
            raw = self.llm.complete(self.system_prompt(), situation, json_mode=True)
            line = str(parse_json_object(raw).get("line") or "").strip()
            return line or fallback
        except Exception:  # noqa: BLE001 - repliken är kosmetisk, aldrig kritisk
            return fallback

    def _line(self, bid: int) -> str:
        return f"Jag säger {rules.name(bid)}."

    # -- Hjälpare ---------------------------------------------------------
    def _opponent_prior(self, bid: int, opponent: str | None) -> float | None:
        """Budspecifik tro, justerad för motståndaren — eller None (populationen).

        Justeringen är **relativ**: motståndarens benägenhet skalas in i den
        budspecifika tron. Att i stället sätta in motståndarens absoluta
        bluff-frekvens vore fel — se :meth:`OpponentTracker.bluff_ratio`.
        """
        if self.tracker is None or opponent is None or self.params.reading <= 0.0:
            return None
        return self.tracker.effective_prior(bid, opponent, reading=self.params.reading)

    @staticmethod
    def _coerce_higher(bid: int, previous_bid: int) -> int:
        """Se till att budet är strikt högre än det förra."""
        if rules.is_higher(bid, previous_bid):
            return bid
        higher = rules.higher_options(previous_bid)
        return higher[-1] if higher else bid

    # -- Beslut 1: första budet (ser tärningarna) ------------------------
    def announce(self, dice: tuple[int, int], *, previous_bid: int | None = None) -> Announcement:
        shown = rules.read_dice(*dice)
        decision = self.policy.decide_bid(shown)
        bid = decision.bid if decision.bid is not None else shown
        if previous_bid is not None:
            bid = self._coerce_higher(bid, previous_bid)
        situation = (
            f"Du ser tärning {dice[0]} och {dice[1]} (visar {rules.name(shown)})."
        )
        if previous_bid is not None:
            situation += f" Du måste höja över {rules.name(previous_bid)}."
        situation += f" Du säger {rules.name(bid)}."
        return Announcement(
            dice=(dice[0], dice[1]),
            shown=shown,
            bid=bid,
            truth=bid == shown,
            line=self._narrate(situation, self._line(bid)),
            reasoning=decision.reason,
            role=self.role.key,
            proposed=decision.bid,
            corrected=decision.bid != bid,
        )

    # -- Beslut 2: slå (ser inte tärningarna) ----------------------------
    def announce_blind(self, dice: tuple[int, int], *, previous_bid: int) -> Announcement:
        if not rules.is_valid_value(previous_bid):
            raise ValueError(f"{previous_bid} är inte ett giltigt bud")
        decision = self.policy.decide_raise(previous_bid)
        higher = rules.higher_options(previous_bid)
        bid = decision.bid if decision.bid is not None else (higher[-1] if higher else previous_bid)
        bid = self._coerce_higher(bid, previous_bid)
        shown = rules.read_dice(*dice)
        situation = (
            f"Du har slagit bägaren blint och måste höja över {rules.name(previous_bid)}. "
            f"Du säger {rules.name(bid)}."
        )
        return Announcement(
            dice=(dice[0], dice[1]),
            shown=shown,
            bid=bid,
            truth=False,
            line=self._narrate(situation, self._line(bid)),
            reasoning=decision.reason,
            role=self.role.key,
            blind=True,
        )

    # -- Beslut 4: tvingad höjning (titta eller blint) -------------------
    def announce_forced(self, dice: tuple[int, int], *, previous_bid: int) -> Announcement:
        if not rules.is_valid_value(previous_bid):
            raise ValueError(f"{previous_bid} är inte ett giltigt bud")
        choice = self.policy.decide_forced(previous_bid)
        if choice.action == "blint":
            ann = self.announce_blind(dice, previous_bid=previous_bid)
        else:
            ann = self.announce(dice, previous_bid=previous_bid)
        return replace(
            ann,
            choice_line=choice.reason,
            choice_reasoning=choice.reason,
        )

    # -- Beslut 3: syna eller skicka ------------------------------------
    def decide(self, bid: int, *, lives: int = 3, opponent: str | None = None) -> ActionDecision:
        """Svara på ett bud. Agenten ser inte sina egna tärningar här."""
        if not rules.is_valid_value(bid):
            raise ValueError(f"{bid} är inte ett giltigt bud")
        decision = self.policy.decide_call(
            bid, lives=lives, opponent_q=self._opponent_prior(bid, opponent)
        )
        verb = "syna budet" if decision.action == "syna" else "skicka vidare"
        situation = f"Motståndaren bjöd {rules.name(bid)}. Din strategi säger att du ska {verb}."
        if decision.action == "syna":
            fallback = f"Jag synar {rules.name(bid)}."
        else:
            fallback = f"Jag skickar vidare {rules.name(bid)}."
        return ActionDecision(
            action=decision.action,
            bid=None,
            line=self._narrate(situation, fallback),
            reasoning=decision.reason,
            role=self.role.key,
        )
