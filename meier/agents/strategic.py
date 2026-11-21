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
from ..opponents import OpponentProfile, OpponentTracker
from ..policy import AgentParams, BasePolicy
from .base import Agent, Role
from .player import ActionDecision, Announcement
from .reader import OpponentReader

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
        reader: OpponentReader | None = None,
    ):
        # Ingen LLM-klient skapas om ingen ges: agenten kan spela utan nätverk.
        self.role = role
        self.llm = llm
        self.params = params
        self.tracker = tracker
        self.policy = policy or BasePolicy(params)
        # Läsaren bygger motståndarprofiler. Utan LLM faller den tillbaka på
        # sekreterarens aritmetik, så en match kan alltid spelas klart.
        self.reader = reader or OpponentReader(llm=llm)
        #: Senaste profilen per motståndare, för insyn i loggen.
        self.profiles: dict[str, OpponentProfile] = {}

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
    def opponent_profile(self, opponent: str | None) -> OpponentProfile | None:
        """Motståndarprofilen för ``opponent``, eller ``None`` om ingen läsning.

        Profilen byggs av :class:`~meier.agents.reader.OpponentReader`, där
        LLM:en tolkar sekreterarens sammanställning. Utan läsande agent (Axel)
        eller utan motståndare finns ingen profil.
        """
        if self.tracker is None or opponent is None or self.params.reading <= 0.0:
            return None
        profile = self.reader.profile(self.tracker, opponent)
        self.profiles[opponent] = profile
        return profile

    def _opponent_prior(self, bid: int, opponent: str | None) -> float | None:
        """Budspecifik tro, justerad för motståndaren — eller None (populationen).

        Justeringen är **relativ**: motståndarens benägenhet skalas in i den
        budspecifika tron, precis som :meth:`OpponentTracker.bluff_ratio`. Att i
        stället sätta in motståndarens absoluta bluff-frekvens vore fel — ett lågt
        bud skulle då bedömas som en bluff och agenten skulle syna bud som nästan
        alltid är sanna.
        """
        from ..policy import CALL_PRIOR

        profile = self.opponent_profile(opponent)
        if profile is None:
            return None
        base = CALL_PRIOR[bid]
        # Faktorn är motståndarens benägenhet (ur profilen, dämpad av LLM:ens
        # konfidens). Agentens egen ``reading`` avgör hur mycket den **vill**
        # låta den styra — en agent som läser lite tar bara en bråkdel av
        # signalen. ``reading = 0`` ger exakt den frysta populationstabellen.
        factor = self.tracker.profile_factor(profile)
        factor = 1.0 + self.params.reading * (factor - 1.0)
        return min(0.95, base * factor)

    def _call_factor(self, opponent: str | None) -> float:
        """Hur mycket oftare motståndaren synar, relativt det normala.

        Samma relativa konstruktion som :meth:`_opponent_prior`, men för
        motståndarens **risk** i stället för dess bluffbenägenhet. Används när
        agenten väljer bud: en synbenägen motståndare gör bluffen dyrare.
        ``reading = 0`` eller ingen profil ger exakt 1,0.
        """
        profile = self.opponent_profile(opponent)
        if profile is None:
            return 1.0
        factor = self.tracker.risk_factor(profile)
        return 1.0 + self.params.reading * (factor - 1.0)

    @staticmethod
    def _coerce_higher(bid: int, previous_bid: int) -> int:
        """Se till att budet är strikt högre än det förra."""
        if rules.is_higher(bid, previous_bid):
            return bid
        higher = rules.higher_options(previous_bid)
        return higher[-1] if higher else bid

    # -- Beslut 1: första budet (ser tärningarna) ------------------------
    def announce(
        self,
        dice: tuple[int, int],
        *,
        previous_bid: int | None = None,
        opponent: str | None = None,
    ) -> Announcement:
        shown = rules.read_dice(*dice)
        decision = self.policy.decide_bid(shown, opponent_factor=self._call_factor(opponent))
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
    def announce_blind(
        self, dice: tuple[int, int], *, previous_bid: int, opponent: str | None = None
    ) -> Announcement:
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
    def announce_forced(
        self, dice: tuple[int, int], *, previous_bid: int, opponent: str | None = None
    ) -> Announcement:
        if not rules.is_valid_value(previous_bid):
            raise ValueError(f"{previous_bid} är inte ett giltigt bud")
        choice = self.policy.decide_forced(previous_bid)
        if choice.action == "blint":
            ann = self.announce_blind(
                dice, previous_bid=previous_bid, opponent=opponent
            )
        else:
            ann = self.announce(dice, previous_bid=previous_bid, opponent=opponent)
        return replace(
            ann,
            choice_line=choice.reason,
            choice_reasoning=choice.reason,
        )

    # -- Beslut 3: syna, skicka eller slå --------------------------------
    def decide(self, bid: int, *, lives: int = 3, opponent: str | None = None) -> ActionDecision:
        """Svara på ett bud. Agenten ser inte sina egna tärningar här."""
        if not rules.is_valid_value(bid):
            raise ValueError(f"{bid} är inte ett giltigt bud")
        profile = self.opponent_profile(opponent)
        decision = self.policy.decide_response(
            bid, lives=lives, opponent_q=self._opponent_prior(bid, opponent)
        )
        reason = decision.reason
        if profile is not None:
            reason = f"{reason} | bild av {opponent}: {profile.kind} (press {profile.press:.2f}, konf {profile.confidence:.2f})"

        if decision.action == "syna":
            verb = "syna budet"
            fallback = f"Jag synar {rules.name(bid)}."
        elif decision.action == "slå":
            verb = "slå bägaren och bjuda högre"
            fallback = f"Jag slår och bjuder högre än {rules.name(bid)}."
        else:
            verb = "skicka vidare"
            fallback = f"Jag skickar vidare {rules.name(bid)}."

        situation = f"Motståndaren bjöd {rules.name(bid)}. Din strategi säger att du ska {verb}."
        return ActionDecision(
            action=decision.action,
            bid=None,
            line=self._narrate(situation, fallback),
            reasoning=reason,
            role=self.role.key,
        )
