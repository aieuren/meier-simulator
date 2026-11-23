"""Spelaragent där **LLM:en fattar besluten** och koden bara dömer.

Uppdelningen är hela poängen:

- :mod:`meier.agents.legality` äger reglerna. Den räknar upp vilka drag som är
  lagliga i ett givet läge.
- :mod:`meier.agents.personality` beskriver spelaren i ord, så att ``caution``,
  ``statistics``, ``unpredictability`` och ``reading`` blir en människa att
  spela som — inte tal i en formel.
- LLM:en väljer drag bland de lagliga. Den får aldrig bryta mot reglerna, men
  den bestämmer själv vad den vill göra.

En tidigare version gjorde tvärtom: :class:`~meier.policy.BasePolicy` räknade
fram draget och LLM:en formulerade bara repliken. Då blev varje spelare samma
algoritm med olika konstanter, och modellen fick aldrig påverka påståendevalet.

Utan LLM-klient faller agenten tillbaka på :class:`~meier.policy.BasePolicy`.
Det läget används av ``axel`` (referensen utan språkmodell) samt av tester som
ska gå på millisekunder utan nätverk. Kravet på Axel är att taktiken inte
innehåller någon LLM — inte att varje drag är reproducerbart in i minsta
slumpval.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from .. import rules
from ..llm import LLMClient, parse_json_object
from ..opponents import OpponentProfile, OpponentTracker
from ..policy import AgentParams, BasePolicy
from .. import legality
from . import personality
from .base import Agent, Role
from .player import ActionDecision, Announcement
from .reader import OpponentReader

_RULES = """\
Två tärningar läses som ett tal med den högsta tärningen först: 2 och 5 blir 52.
21 kallas Meier och är högst. Sedan faller ordningen:
{rang}.

Ett varv:
1. Spelaren med bägaren skakar, tittar i smyg och säger ett påstående: det sanna,
   ett högre (en bluff) eller ett lägre.
2. Nästa spelare väljer ett av tre:
   - Slå: skaka bägaren utan att titta och säga ett strikt högre påstående.
   - Syna: lyft locket. Visar tärningarna lägre än påståendet förlorar den som påstod
     ett liv. Visar de samma eller högre förlorar den som synade ett liv.
   - Skicka vidare: skicka bägaren vidare med samma påstående. Du tar då över
     ansvaret för påståendet.
3. Den som slår måste alltid säga ett strikt högre påstående, vad tärningarna än visar.
4. Kommer bägaren ett helt varv tillbaka till den som påstod måste denne höja. Är
   påståendet Meier slår spelaren i stället om och börjar en ny runda.
5. Meier kostar dubbelt: om påståendet är Meier, eller om tärningarna visar Meier vid
   en syn, förlorar man två liv i stället för ett.
6. När någon förlorat ett liv går bägaren till föregående spelare, som slår och
   börjar en ny runda. Den som först mist tre liv är ute. Sist kvar vinner.""".format(
    rang=", ".join(rules.name(v) for v in rules.RANKING)
)


class StrategicAgent(Agent):
    """En Meier-spelare som låter LLM:en fatta alla beslut.

    ``tracker`` är valfri och ger agenten en bild av motståndarna. Bilden
    beskrivs i ord för modellen; den matas aldrig in i en formel.

    ``llm`` är valfri. Utan den spelar agenten enligt
    :class:`~meier.policy.BasePolicy`, vilket är nätverksfritt. Det är
    ``axel``s läge: taktiken innehåller ingen språkmodell.
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
        self.role = role
        self.llm = llm
        self.params = params
        self.tracker = tracker
        self.policy = policy or BasePolicy(params)
        self.reader = reader or OpponentReader(llm=llm)
        #: Senaste profilen per motståndare, för insyn i loggen.
        self.profiles: dict[str, OpponentProfile] = {}

    # -- Prompt -----------------------------------------------------------
    def system_prompt(self) -> str:
        return (
            f"Du spelar tärningsspelet Meier som {self.role.name}.\n"
            f"{self.role.description}\n\n"
            "DIN SPELSTIL\n"
            f"{personality.describe(self.params)}\n\n"
            "REGLER\n"
            f"{_RULES}\n\n"
            "Terminologi: säg alltid 'påstående' när du talar om "
            "det du säger.\n\n"
            "Du fattar själv alla beslut. Du får bara välja bland de lagliga "
            "alternativ som anges i uppgiften. Svara alltid med JSON."
        )

    # -- Motståndarbild ---------------------------------------------------
    def opponent_profile(self, opponent: str | None) -> OpponentProfile | None:
        """Motståndarprofilen för ``opponent``, eller ``None`` om ingen läsning.

        Utan läsande agent (``axel``), utan motståndare eller utan tracker finns
        ingen bild. ``reading = 0`` stänger också av läsningen.
        """
        if self.tracker is None or opponent is None or self.params.reading <= 0.0:
            return None
        profile = self.reader.profile(self.tracker, opponent)
        self.profiles[opponent] = profile
        return profile

    def _opponent_note(self, opponent: str | None) -> str:
        """Motståndaren i ord, om agenten har läst den. Annars tom sträng."""
        profile = self.opponent_profile(opponent)
        if profile is None:
            return ""
        text = personality.describe_opponent(
            kind=profile.kind,
            call_tendency=profile.call_tendency,
            bluff_tendency=profile.bluff_tendency,
            confidence=profile.confidence,
        )
        return f"\nMOTSTÅNDAREN {opponent}\n{text}\n"

    def _opponent_prior(self, bid: int, opponent: str | None) -> float | None:
        """Påståendespecifik tro, justerad för motståndaren — eller None (populationen).

        Används bara av reservpolicyn. LLM:en får motståndaren i ord i stället.
        """
        from ..policy import CALL_PRIOR

        profile = self.opponent_profile(opponent)
        if profile is None:
            return None
        base = CALL_PRIOR[bid]
        factor = self.tracker.bluff_factor(profile)
        factor = 1.0 + self.params.reading * (factor - 1.0)
        return min(0.95, base * factor)

    def _call_factor(self, opponent: str | None) -> float:
        """Hur mycket oftare motståndaren synar, relativt det normala."""
        profile = self.opponent_profile(opponent)
        if profile is None:
            return 1.0
        factor = self.tracker.call_factor(profile)
        return 1.0 + self.params.reading * (factor - 1.0)

    # -- LLM-anropet -------------------------------------------------------
    def _ask(
        self, context: str, parse: Callable[[dict], tuple[Any | None, str]]
    ) -> tuple[Any | None, str]:
        """Fråga modellen och tolka svaret.

        ``parse`` returnerar ``(värde, motivering)``, där ``värde`` är ``None`` om
        svaret inte gick att använda. Ett ogiltigt svar får **en** omfrågning med
        besked om vad som var fel. Sedan ger agenten upp och reservpolicyn tar
        över, så en trasig modell aldrig kan fälla en match.
        """
        if self.llm is None:
            return None, ""
        prompt = context
        reason = ""
        for _ in range(2):
            try:
                raw = self.llm.complete(self.system_prompt(), prompt, json_mode=True)
                data = parse_json_object(raw)
            except Exception:  # noqa: BLE001 - ett modellfel får aldrig fälla matchen
                return None, ""
            value, reason = parse(data)
            if value is not None:
                return value, reason
            prompt = (
                f"{context}\n\nDITT FÖRRA SVAR DUGER INTE. {reason}\n"
                "Välj ett av de lagliga alternativen ovan."
            )
        return None, reason

    @staticmethod
    def _as_bid(value: object) -> int | None:
        """Tolka ett påstående ur modellens svar, som heltal eller siffror i text."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if digits:
                return int(digits)
        return None

    def _parse_bid(self, data: dict, legal: list[int]) -> tuple[int | None, str]:
        bid = self._as_bid(data.get("bid"))
        if bid is None:
            return None, "Du angav inget påstående."
        if bid not in legal:
            return None, (
                f"{bid} är inte lagligt här. Lagliga påståenden: "
                f"{', '.join(rules.name(v) for v in legal)}."
            )
        return bid, str(data.get("reasoning") or "").strip()

    # -- Beslut 1: påståendet (spelaren ser tärningarna) -------------------
    def announce(
        self,
        dice: tuple[int, int],
        *,
        previous_bid: int | None = None,
        opponent: str | None = None,
    ) -> Announcement:
        """Vilket påstående säger spelaren, givet vad tärningarna visar?"""
        shown = rules.read_dice(*dice)
        legal = legality.legal_bids(shown=shown, previous_bid=previous_bid)
        context = self._bid_context(dice, shown, previous_bid, legal, opponent)
        bid, reason = self._ask(context, lambda d: self._parse_bid(d, legal))

        corrected = False
        if bid is None:
            # Reservpolicyn väljer bland samma lagliga påståenden, så valet är spelarens
            # eget även här. ``corrected`` betyder att LLM:en inte kunde svara.
            decision = self.policy.decide_bid(
                shown,
                opponent_factor=self._call_factor(opponent),
                previous_bid=previous_bid,
            )
            bid, reason = decision.bid, decision.reason
            # Bara en korrigering om LLM:en faktiskt svarade fel. Utan klient
            # ar policyn spelearens eget beslut, inte en rattselse av nagon annans.
            corrected = self.llm is not None

        return Announcement(
            dice=(dice[0], dice[1]),
            shown=shown,
            bid=bid,
            truth=bid == shown,
            line=self._say(bid),
            reasoning=reason,
            role=self.role.key,
            proposed=bid,
            corrected=corrected,
        )

    def _bid_context(
        self,
        dice: tuple[int, int],
        shown: int,
        previous_bid: int | None,
        legal: list[int],
        opponent: str | None,
    ) -> str:
        lines = [
            "TÄRNINGSLAGET",
            f"Du har skakat bägaren och tittat i smyg: tärning {dice[0]} och {dice[1]}.",
            f"Det visar {rules.name(shown)}.",
            self._opponent_note(opponent),
        ]
        if previous_bid is None:
            lines += ["", "DET ÄR DU SOM BÖRJAR RUNDAN."]
        else:
            lines += [
                "",
                "SITUATIONEN",
                f"Bägaren har gått ett helt varv tillbaka till dig och du måste höja "
                f"över {rules.name(previous_bid)}.",
            ]
        lines += [
            "",
            "LAGLIGA PÅSTÅENDEN",
            self._legal_bids_listed(shown, legal),
            "",
            "Du får säga sanningen, ett högre (en bluff) eller ett lägre. Tänk på vad "
            "du tjänar på: ett påstående under dina tärningar kan ingen syna utan att "
            "förlora, ett påstående över är en bluff.",
            "",
            "Svara med JSON:",
            '{"bid": <heltal ur listan ovan>, "reasoning": "<kort motivering>"}',
        ]
        return "\n".join(lines)

    def _legal_bids_listed(self, shown: int, legal: list[int]) -> str:
        """Lista de lagliga påståendena med riktning mot tärningarna.

        Modellen kan Meiers ordning sämre än koden. Utan riktningen händer det att
        den kallar ett högre påstående för "lägre" i motiveringen. Märkningen gör
        att motiveringen och draget inte kan peka åt olika håll.
        """
        marked = []
        for v in legal:
            if v == shown:
                tag = "exakt dina tärningar"
            elif rules.is_higher(v, shown):
                tag = "högre, alltså bluff"
            else:
                tag = "lägre, alltså sant men svagare"
            marked.append(f"{rules.name(v)} ({tag})")
        return "; ".join(marked)

    # -- Beslut 2: slå (spelaren ser inte tärningarna) ---------------------
    def announce_blind(
        self, dice: tuple[int, int], *, previous_bid: int, opponent: str | None = None
    ) -> Announcement:
        """Spelaren slår: bägaren är stängd och påståendet måste vara strikt högre."""
        if not rules.is_valid_value(previous_bid):
            raise ValueError(f"{previous_bid} är inte ett giltigt påstående")
        legal = legality.blind_bids(previous_bid=previous_bid)
        if not legal:
            raise ValueError(
                f"Kan inte slå: {rules.name(previous_bid)} är högst, det finns inget högre påstående"
            )
        shown = rules.read_dice(*dice)
        context = self._blind_context(previous_bid, legal, opponent)
        bid, reason = self._ask(context, lambda d: self._parse_bid(d, legal))

        corrected = False
        if bid is None:
            decision = self.policy.decide_raise(previous_bid)
            bid = decision.bid if decision.bid in legal else legal[-1]
            reason = decision.reason
            corrected = self.llm is not None

        return Announcement(
            dice=(dice[0], dice[1]),
            shown=shown,
            bid=bid,
            truth=bid == shown,
            line=self._say(bid),
            reasoning=reason,
            role=self.role.key,
            proposed=bid,
            corrected=corrected,
            blind=True,
        )

    def _blind_context(
        self, previous_bid: int, legal: list[int], opponent: str | None
    ) -> str:
        return "\n".join(
            [
                "DU SLÅR",
                "Du skakar bägaren själv och lyfter inte på locket. Du ser inte tärningarna.",
                f"Du måste säga ett strikt högre påstående än {rules.name(previous_bid)}.",
                self._opponent_note(opponent),
                "",
                "LAGLIGA PÅSTÅENDEN",
                ", ".join(rules.name(v) for v in legal),
                "",
                "Ett lågt påstående är svårare för nästa spelare att slå över. Ett högt "
                "påstående sätter press men synas oftare.",
                "",
                "Svara med JSON:",
                '{"bid": <heltal ur listan ovan>, "reasoning": "<kort motivering>"}',
            ]
        )

    # -- Beslut 3: titta eller påstå blint vid tvingad höjning -------------
    def announce_forced(
        self, dice: tuple[int, int], *, previous_bid: int, opponent: str | None = None
    ) -> Announcement:
        """Bägaren har gått ett helt varv: titta på de nya tärningarna eller påstå blint?"""
        if not rules.is_valid_value(previous_bid):
            raise ValueError(f"{previous_bid} är inte ett giltigt påstående")
        choices = legality.forced_choices(previous_bid=previous_bid)
        if not choices:
            # Påståendet är Meier. Motorn slår om och börjar en ny runda i stället.
            raise ValueError(
                f"Kan inte höja: {rules.name(previous_bid)} är högst, det finns inget högre påstående"
            )
        context = self._forced_context(previous_bid, choices, opponent)
        blind, reason = self._ask(context, self._parse_forced)

        if blind is None:
            choice = self.policy.decide_forced(previous_bid)
            blind, reason = choice.action == "blint", choice.reason

        if blind:
            ann = self.announce_blind(dice, previous_bid=previous_bid, opponent=opponent)
        else:
            ann = self.announce(dice, previous_bid=previous_bid, opponent=opponent)
        return replace(
            ann,
            choice_line="Jag påstår blint." if blind else "Jag tittar på tärningarna.",
            choice_reasoning=reason,
        )

    @staticmethod
    def _parse_forced(data: dict) -> tuple[bool | None, str]:
        reason = str(data.get("reasoning") or "").strip()
        value = data.get("blind")
        if isinstance(value, bool):
            return value, reason
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "ja", "j", "blint", "blind"):
                return True, reason
            if v in ("false", "nej", "n", "titta", "tittar"):
                return False, reason
        return None, 'Du måste svara med "blind": true eller false.'

    def _forced_context(
        self, previous_bid: int, choices: list[str], opponent: str | None
    ) -> str:
        return "\n".join(
            [
                "TITTA ELLER BLINT",
                f"Bägaren har gått ett helt varv och är tillbaka hos dig. Du måste höja "
                f"över {rules.name(previous_bid)}.",
                "Tärningarna har slagits om och ligger under locket.",
                self._opponent_note(opponent),
                "",
                f"LAGLIGA VAL: {', '.join(choices)}",
                "- titta: lyft locket och säg ett påstående som du ser tärningarna.",
                "- blint: påstå utan att titta, som när man slår.",
                "",
                "Svara med JSON:",
                '{"blind": true | false, "reasoning": "<kort motivering>"}',
            ]
        )

    # -- Beslut 4: syna, skicka vidare eller slå --------------------------
    def decide(
        self, bid: int, *, lives: int = 3, opponent: str | None = None
    ) -> ActionDecision:
        """Svara på ett påstående. Spelaren ser inte sina egna tärningar här."""
        if not rules.is_valid_value(bid):
            raise ValueError(f"{bid} är inte ett giltigt påstående")
        choices = legality.response_actions(bid=bid)
        context = self._response_context(bid, lives, choices, opponent)
        action, reason = self._ask(context, lambda d: self._parse_response(d, choices))

        if action is None:
            decision = self.policy.decide_response(
                bid, lives=lives, opponent_q=self._opponent_prior(bid, opponent)
            )
            action, reason = decision.action, decision.reason
            if action not in choices:
                # Reservpolicyn kan vilja slå mot Meier. Det går inte, så ta det
                # bästa av de val som återstår i stället för att kasta.
                action = "skicka"
            # Reservpolicyn väger in motståndarbilden i tal. Skriv ut den i
            # klartext också, så loggen visar vad den byggde på.
            profile = self.opponent_profile(opponent)
            if profile is not None:
                reason = (
                    f"{reason} | bild av {opponent}: {profile.kind} "
                    f"(bluff {profile.bluff_tendency:.2f}, "
                    f"konf {profile.confidence:.2f})"
                )

        return ActionDecision(
            action=action,
            bid=None,
            line=self._say_action(action, bid),
            reasoning=reason,
            role=self.role.key,
        )

    def _say_action(self, action: str, bid: int) -> str:
        """Repliken som hör till svaret på ett påstående — inte till ett eget påstående.

        Byggs ur draget, av samma skäl som :meth:`_say`.
        """
        fallbacks = {
            "syna": f"Jag synar {rules.name(bid)}.",
            "skicka": f"Jag skickar vidare {rules.name(bid)}.",
            "slå": f"Jag slår och påstår högre än {rules.name(bid)}.",
        }
        return fallbacks.get(action, f"Jag säger {rules.name(bid)}.")

    @staticmethod
    def _parse_response(data: dict, choices: list[str]) -> tuple[str | None, str]:
        value = data.get("action")
        if not isinstance(value, str):
            return None, 'Du måste svara med "action".'
        v = value.strip().lower().rstrip("!.")
        aliases = {
            "slå": "slå", "sla": "slå", "höj": "slå", "hoj": "slå", "raise": "slå",
            "syna": "syna", "syn": "syna", "call": "syna", "se": "syna",
            "skicka": "skicka", "skicka vidare": "skicka", "vidare": "skicka",
            "pass": "skicka", "skickar": "skicka",
        }
        action = aliases.get(v)
        if action is None or action not in choices:
            return None, f'"{value}" är inte ett av valen: {", ".join(choices)}.'
        return action, str(data.get("reasoning") or "").strip()

    def _response_context(
        self, bid: int, lives: int, choices: list[str], opponent: str | None
    ) -> str:
        return "\n".join(
            [
                "SITUATIONEN",
                f"Bägaren är hos {opponent or 'motståndaren'}, som säger {rules.name(bid)}.",
                f"Du har {lives} liv kvar.",
                self._opponent_note(opponent),
                "",
                f"LAGLIGA VAL: {', '.join(choices)}",
                "- slå: skaka bägaren utan att titta och säga ett strikt högre påstående.",
                "- syna: lyft locket. Visar tärningarna lägre än påståendet förlorar "
                "den som påstod ett liv, annars förlorar du ett. Meier kostar två.",
                "- skicka: skicka bägaren vidare med samma påstående och ta över ansvaret för det.",
                "",
                "Svara med JSON:",
                '{"action": "slå" | "syna" | "skicka", "reasoning": "<kort motivering>"}',
            ]
        )

    # -- Repliken ----------------------------------------------------------
    @staticmethod
    def _say(bid: int) -> str:
        """Repliken som hör till ett påstående.

        Den byggs ur draget, inte ur ett eget modellanrop. Repliken är kosmetisk
        och styrs inte av spelarens parametrar, så ett extra anrop per drag vore
        bara kostnad utan inverkan på spelet. Det som styr hur spelaren *spelar*
        är motiveringen och påståendet, och de kommer från beslutsanropet.
        """
        return f"Jag säger {rules.name(bid)}."
