"""Meier-spelaragenten.

Agenten simulerar en spelare i tärningsspelet Meier. Den centrala uppgiften är:
givet utfallet av ett tärningsslag med två tärningar, bestäm hur spelaren
svarar. Spelaren har tittat i smyg på tärningarna och ska säga ett resultat till
nästa spelare – sanningen, ett högre eller ett lägre.

Agenten kan också fatta beslut när den möter ett påstående från en annan spelare:
**Syna** (lyfta locket), **Slå** (skaka bägaren på nytt och säga ett högre
påstående) eller **Skicka vidare**.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .. import rules
from ..llm import LLMClient
from .base import Agent, Role


@dataclass
class Announcement:
    """Spelarens svar efter att ha tittat på tärningarna."""

    dice: tuple[int, int]
    shown: int  # vad tärningarna faktiskt visar
    claim: int  # vad spelaren säger (efter regelkorrigering)
    truth: bool  # säger spelaren sanningen?
    line: str  # repliken spelaren säger
    reasoning: str  # varför
    role: str
    proposed: int | None = None  # rå värdet modellen föreslog (kan vara ogiltigt)
    corrected: bool = False  # behövde påståendet korrigeras för att följa reglerna?
    unseen: bool = False  # påstod spelaren utan att titta på tärningarna?
    choice_line: str = ""  # vid tvingad höjning: replik för valet att titta eller inte
    choice_reasoning: str = ""  # vid tvingad höjning: motivering för valet

    def to_dict(self) -> dict:
        return {
            "dice": list(self.dice),
            "shown": self.shown,
            "shown_name": rules.name(self.shown),
            "claim": self.claim,
            "claim_name": rules.name(self.claim),
            "truth": self.truth,
            "lie": not self.truth,
            "line": self.line,
            "reasoning": self.reasoning,
            "role": self.role,
            "proposed": self.proposed,
            "corrected": self.corrected,
            "unseen": self.unseen,
            "choice_line": self.choice_line,
            "choice_reasoning": self.choice_reasoning,
        }


@dataclass
class ActionDecision:
    """Spelarens val när den möter ett påstående: Syna, Slå eller Skicka vidare.

    Används också för valet att titta eller inte vid en tvingad höjning, där ``action``
    är ``"titta"`` eller ``"unseen"``.
    """

    action: str  # "syna", "slå", "skicka" (eller "titta"/"unseen" vid tvingad höjning)
    claim: int | None  # nytt påstående om spelaren slår
    line: str
    reasoning: str
    role: str

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "claim": self.claim,
            "claim_name": rules.name(self.claim) if self.claim is not None else None,
            "line": self.line,
            "reasoning": self.reasoning,
            "role": self.role,
        }


class MeierPlayerAgent(Agent):
    """En oberoende LLM-baserad Meier-spelare."""

    def __init__(self, role: Role, llm: LLMClient | None = None):
        super().__init__(role=role, llm=llm or LLMClient())

    # -- Systemprompt -------------------------------------------------------
    def system_prompt(self) -> str:
        ranking = ", ".join(rules.name(v) for v in rules.RANKING)
        return (
            f"Du spelar tärningsspelet Meier som spelaren {self.role.name}.\n"
            f"Roll: {self.role.description}\n"
            f"Spelstil: {self.role.style}\n\n"
            "REGLER\n"
            "- Två tärningar läses som ett tal med den högsta tärningen först: 2 och 5 blir 52.\n"
            "- 21 kallas Meier och är högst. Sedan faller ordningen:\n"
            f"  {ranking}.\n"
            "- Ordningen är inte talordning. Läs den som en stege, högst först, och "
            "jämför bara läge i stegen. Par slår singlar: 11, 22, 33, 44, 55 och 66 "
            "ligger alla över 65, som är det högsta singelparet. Alltså är 55 högre än "
            "66, och 44 högre än 65. 66 är bara sjua i ordningen, och sex påståenden "
            "ligger över det: 55, 44, 33, 22, 11 och 21. Att bordet står på 66 betyder "
            "alltså inte att bara Meier återstår. 31 är lägst av alla.\n"
            "- Du har tittat i smyg på tärningarna och ska säga ett påstående till nästa spelare: "
            "att tärningarna visar minst ett visst värde. Det kan vara sant, ett högre (en bluff) "
            "eller ett lägre (sant, men svagare).\n"
            "- Nästa spelare kan Syna (lyfta locket och granska påståendet), Slå (säga ett "
            "högre påstående; den som slår får alltid titta på sina egna tärningar om den vill) "
            "eller Skicka vidare (ta över ansvaret för samma påstående, utan att se tärningarna).\n"
            "- Om bägaren går ett helt varv tillbaka till den som påstod måste denne höja. "
            "Tärningarna slås då om, och spelaren får själv välja att titta på dem eller påstå utan att titta.\n"
            "- Om någon synar och tärningarna visar lägre än påståendet förlorar den som påstod ett liv. "
            "Visar de samma eller högre förlorar den som synade ett liv.\n"
            "- Meier kostar dubbelt: om påståendet är Meier, eller om tärningarna visar Meier när "
            "någon synar, förlorar man två liv.\n\n"
            "Terminologi: säg alltid 'påstående' när du talar om det du säger.\n\n"
            "Du svarar ALLTID med ett JSON-objekt och inget annat."
        )

    # -- Kärnfunktion: givet tärningsutfallet, hur svarar spelaren? ---------
    def announce(
        self,
        dice: tuple[int, int],
        *,
        previous_claim: int | None = None,
        opponent: str | None = None,
    ) -> Announcement:
        """Bestäm spelarens påstående givet utfallet av ett tärningsslag.

        ``previous_claim`` är det senaste påståendet i rundan om spelaren höjer efter
        ett helt varv och alltså redan har tittat på tärningarna. Då måste påståendet
        vara strikt högre. Att **slå** mot ett påstående går i stället via
        :meth:`announce_shake`, som först låter spelaren välja om den vill titta.
        """
        shown = rules.read_dice(*dice)
        higher = rules.higher_options(previous_claim) if previous_claim is not None else []

        context = self._announce_context(dice, shown, previous_claim, higher)
        data = self.respond(context)

        proposed = self._raw_claim(data.get("claim"))
        claim = self._coerce_claim(data.get("claim"), shown, previous_claim, higher)
        reasoning = str(data.get("reasoning") or "").strip()

        return Announcement(
            dice=(dice[0], dice[1]),
            shown=shown,
            claim=claim,
            truth=rules.is_true_claim(claim, shown),
            line=self._default_line(claim),
            reasoning=reasoning,
            role=self.role.key,
            proposed=proposed,
            corrected=proposed != claim,
        )

    def announce_shake(
        self, dice: tuple[int, int], *, previous_claim: int, opponent: str | None = None
    ) -> Announcement:
        """Spelaren slår: skakar bägaren på nytt och måste säga ett högre påstående.

        Reglerna låter spelaren lyfta på locket på sitt eget slag. Att titta är det
        normala; att avstå är ett eget val som döljer informationen för bordet.
        """
        if not rules.is_valid_value(previous_claim):
            raise ValueError(f"{previous_claim} är inte ett giltigt påstående")
        seen = self._wants_seen_shake(previous_claim)
        if seen:
            ann = self.announce(dice, previous_claim=previous_claim, opponent=opponent)
            return replace(
                ann,
                choice_line="Jag tittar på tärningarna.",
                choice_reasoning="Tittar innan jag påstår.",
            )
        ann = self.announce_unseen(dice, previous_claim=previous_claim, opponent=opponent)
        return replace(
            ann,
            choice_line="Jag påstår utan att titta.",
            choice_reasoning="Fintaktik: påstår utan att titta.",
        )

    def _wants_seen_shake(self, previous_claim: int) -> bool:
        """Fråga spelaren om den vill titta på sitt eget slag. Standard är ja."""
        context = self._shake_choice_context(previous_claim)
        data = self.respond(context)
        return self._coerce_seen_choice(data.get("seen"))

    def announce_unseen(
        self, dice: tuple[int, int], *, previous_claim: int, opponent: str | None = None
    ) -> Announcement:
        """Spelaren **slår** och måste säga ett strikt högre påstående.

        Detta är fintaktikens väg: spelaren har **valt** att inte lyfta på locket.
        Bägaren är då stängd, och påståendet måste vara strikt högre oavsett vad
        tärningarna visar.
        Tärningarna ``dice`` är det nya slaget; de används bara för att kunna
        avgöra en eventuell syn senare.
        """
        if not rules.is_valid_value(previous_claim):
            raise ValueError(f"{previous_claim} är inte ett giltigt påstående")
        shown = rules.read_dice(*dice)
        higher = rules.higher_options(previous_claim)

        context = self._unseen_announce_context(previous_claim, higher)
        data = self.respond(context)

        proposed = self._raw_claim(data.get("claim"))
        claim = self._coerce_unseen_claim(data.get("claim"), previous_claim, higher)
        reasoning = str(data.get("reasoning") or "").strip()

        return Announcement(
            dice=(dice[0], dice[1]),
            shown=shown,
            claim=claim,
            truth=rules.is_true_claim(claim, shown),
            line=self._default_line(claim),
            reasoning=reasoning,
            role=self.role.key,
            proposed=proposed,
            corrected=proposed != claim,
            unseen=True,
        )

    def announce_forced(
        self, dice: tuple[int, int], *, previous_claim: int, opponent: str | None = None
    ) -> Announcement:
        """Hållaren måste höja när bägaren gått ett helt varv.

        Tärningarna har redan slagits om av motorn. Spelaren får själv välja om
        den vill titta på dem (som vid ett vanligt påstående) eller påstå utan att titta (som
        vid ett slag). Båda sätten är tillåtna – valet är spelarens.
        """
        if not rules.is_valid_value(previous_claim):
            raise ValueError(f"{previous_claim} är inte ett giltigt påstående")
        higher = rules.higher_options(previous_claim)
        if not higher:
            raise ValueError(
                f"Kan inte höja: {rules.name(previous_claim)} är högst, det finns inget högre påstående"
            )
        choice = self._wants_unseen_forced(previous_claim, higher)
        if choice.action == "unseen":
            # Spelaren väljer att påstå utan att titta utan att titta på de nya tärningarna.
            ann = self.announce_unseen(
                dice, previous_claim=previous_claim, opponent=opponent
            )
        else:
            # Spelaren tittar på de nya tärningarna och höjer som vid ett vanligt påstående.
            ann = self.announce(dice, previous_claim=previous_claim, opponent=opponent)
        return replace(ann, choice_line=choice.line, choice_reasoning=choice.reasoning)

    def _wants_unseen_forced(self, previous_claim: int, higher: list[int]) -> ActionDecision:
        """Fråga spelaren: titta på de nya tärningarna eller påstå utan att titta?

        Returnerar valet som en :class:`ActionDecision` så att både själva valet
        (``action == "unseen"`` eller ``"titta"``) och dess motivering bevaras.
        """
        context = self._forced_choice_context(previous_claim, higher)
        data = self.respond(context)
        unseen = self._coerce_unseen_choice(data.get("unseen"))
        return ActionDecision(
            action="unseen" if unseen else "titta",
            claim=None,
            line="Jag påstår utan att titta." if unseen else "Jag tittar på tärningarna.",
            reasoning=str(data.get("reasoning") or "").strip(),
            role=self.role.key,
        )

    def _forced_choice_context(self, previous_claim: int, higher: list[int]) -> str:
        return "\n".join(
            [
                "TITTA ELLER INTE TITTA",
                "SITUATIONEN",
                f"Bägaren har gått ett helt varv och är tillbaka hos dig. Du måste höja "
                f"över {rules.name(previous_claim)}.",
                "Tärningarna har slagits om. Du får själv välja hur du gör:",
                "- Titta på de nya tärningarna och säga ett påstående (som vid ett vanligt påstående).",
                "- Påstå utan att titta (som när man slår).",
                "Båda sätten är tillåtna. Valet är ditt.",
                f"Giltiga påståenden: {', '.join(rules.name(v) for v in higher)}.",
                "",
                "Svara med JSON:",
                '{"unseen": <true om du påstår utan att titta, false om du tittar>, '
                '"reasoning": "<kort motivering>"}',
            ]
        )

    def _shake_choice_context(self, previous_claim: int) -> str:
        return "\n".join(
            [
                "SLAG – TITTA ELLER INTE TITTA",
                "SITUATIONEN",
                f"Du slår bägaren och måste säga ett strikt högre påstående än "
                f"{rules.name(previous_claim)}.",
                "Du har skakat bägaren själv och locket ligger på. Du får lyfta på det "
                "och titta innan du påstår – det är det vanliga.",
                "- Titta: du ser tärningarna och kan lägga påståendet rätt.",
                "- Avstå: du påstår utan att veta vad tärningarna visar. Påståendet går "
                "inte att läsa, men du gissar.",
                "Båda är tillåtna. Valet är ditt.",
                "",
                "Svara med JSON:",
                '{"seen": <true om du tittar, false om du påstår utan att titta>, '
                '"reasoning": "<kort motivering>"}',
            ]
        )

    @staticmethod
    def _coerce_seen_choice(value: object) -> bool:
        """Tolka modellens val av titta (True) eller påstå utan att titta (False)."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "ja", "j", "titta", "tittar"):
                return True
            if v in ("false", "nej", "n", "utan att titta", "tittar inte", "unseen"):
                return False
        return True

    @staticmethod
    def _coerce_unseen_choice(value: object) -> bool:
        """Tolka modellens val av titta (False) eller påstå utan att titta (True)."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "ja", "j", "utan att titta", "tittar inte"):
                return True
            if v in ("false", "nej", "n", "titta", "tittar"):
                return False
        return False

    def _unseen_announce_context(self, previous_claim: int, higher: list[int]) -> str:
        return "\n".join(
            [
                "SITUATIONEN",
                f"Du slår bägaren och måste säga ett strikt högre påstående än {rules.name(previous_claim)}.",
                "Du har valt att inte lyfta på locket, så du ser inte tärningarna.",
                "Du MÅSTE säga ett strikt högre påstående än det förra, vad tärningarna än visar.",
                f"Giltiga påståenden: {', '.join(rules.name(v) for v in higher) or 'inga (påståendet är högst)'}.",
                "",
                "UPPGIFT",
                "Säg ett högre påstående utan att lyfta på locket. Du har redan valt bort titten.",
                "",
                "Svara med JSON:",
                '{"claim": <heltal, ett giltigt utfall högre än det förra>, '
                '"reasoning": "<kort motivering>"}',
            ]
        )

    def _coerce_unseen_claim(self, value: object, previous_claim: int, higher: list[int]) -> int:
        """Se till att ett slag-påstående är giltigt och strikt högre."""
        if not higher:
            raise ValueError(
                f"Kan inte slå: {rules.name(previous_claim)} är högst, det finns inget högre påstående"
            )
        claim: int | None = None
        if isinstance(value, int) and not isinstance(value, bool) and rules.is_valid_value(value):
            claim = value
        elif isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if digits and rules.is_valid_value(int(digits)):
                claim = int(digits)

        if claim is None or not rules.is_higher(claim, previous_claim):
            # Minsta möjliga höjning om modellen inte gav ett giltigt högre påstående.
            claim = higher[-1]
        return claim

    @staticmethod
    def _raw_claim(value: object) -> int | None:
        """Modellens råa påstående som heltal, även om det är ogiltigt."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if digits:
                return int(digits)
        return None

    def _announce_context(
        self,
        dice: tuple[int, int],
        shown: int,
        previous_claim: int | None,
        higher: list[int],
    ) -> str:
        lines = [
            "TÄRNINGSLAGET",
            f"Tärning 1: {dice[0]}, Tärning 2: {dice[1]}.",
            f"Läses som: {shown} ({rules.name(shown)}).",
            f"Du ser alltså {rules.name(shown)}.",
        ]
        if previous_claim is not None:
            lines += [
                "",
                "SITUATIONEN",
                f"Du slår efter ett påstående på {rules.name(previous_claim)}.",
                "Du MÅSTE säga ett strikt högre påstående än det förra, vad tärningarna än visar.",
                f"Giltiga påståenden: {', '.join(rules.name(v) for v in higher)}.",
            ]
        lines += [
            "",
            "UPPGIFT",
            "Bestäm vilket resultat du säger till nästa spelare. Du får säga sanningen, "
            "ett högre eller ett lägre resultat.",
            "",
            "Svara med JSON:",
            '{"claim": <heltal, ett giltigt utfall>, '
            '"reasoning": "<kort motivering>"}',
        ]
        return "\n".join(lines)

    def _coerce_claim(
        self,
        value: object,
        shown: int,
        previous_claim: int | None,
        higher: list[int],
    ) -> int:
        """Se till att påståendet är giltigt och följer reglerna."""
        claim: int | None = None
        if isinstance(value, int) and rules.is_valid_value(value):
            claim = value
        elif isinstance(value, str) and value.strip().isdigit():
            candidate = int(value.strip())
            if rules.is_valid_value(candidate):
                claim = candidate

        if claim is None:
            # Modellen svarade inte med ett giltigt utfall – fall tillbaka på sanningen.
            claim = shown

        if previous_claim is not None and not rules.is_higher(claim, previous_claim):
            # Måste höja. Välj ett högre påstående så nära det visade som möjligt.
            options = higher or [rules.RANKING[0]]
            claim = min(options, key=lambda v: abs(rules.rank(v) - rules.rank(shown)))
        return claim

    def _default_line(self, claim: int) -> str:
        return f"Jag säger {rules.name(claim)}."

    def _say_action(self, action: str, claim: int) -> str:
        fallbacks = {
            "syna": f"Jag synar {rules.name(claim)}.",
            "skicka": f"Jag skickar vidare {rules.name(claim)}.",
            "slå": f"Jag slår och påstår högre än {rules.name(claim)}.",
        }
        return fallbacks.get(action, f"Jag säger {rules.name(claim)}.")

    # -- Beslut mot ett påstående: Syna, Slå eller Skicka vidare -------------
    def decide(self, claim: int, *, lives: int = 3, opponent: str | None = None) -> ActionDecision:
        """Välj handling när en annan spelare har sagt ``claim``.

        Spelaren kan **Syna**, **Slå** (höja) eller **Skicka vidare**.
        ``opponent`` är namnet på den som håller påståendet. Den här LLM-agenten
        använder det inte, men tar emot det så att motorn kan behandla alla
        agenttyper lika (den strategiska agenten läser det).
        """
        if not rules.is_valid_value(claim):
            raise ValueError(f"{claim} är inte ett giltigt påstående")

        higher = rules.higher_options(claim)
        context = self._decide_context(claim, higher, lives)
        data = self.respond(context)

        action = self._coerce_action(data.get("action"))
        new_claim: int | None = None
        if action == "slå":
            if not higher:
                # Påståendet är redan högst (Meier) – går inte att slå.
                action = "skicka"
            else:
                new_claim = self._coerce_claim(data.get("claim"), higher[-1], claim, higher)
                if not rules.is_higher(new_claim, claim):
                    new_claim = higher[-1]
        reasoning = str(data.get("reasoning") or "").strip()

        return ActionDecision(
            action=action,
            claim=new_claim,
            line=self._say_action(action, claim),
            reasoning=reasoning,
            role=self.role.key,
        )

    def _decide_context(self, claim: int, higher: list[int], lives: int) -> str:
        return "\n".join(
            [
                "SITUATIONEN",
                f"En annan spelare har sagt {rules.name(claim)}.",
                f"Du har {lives} liv kvar.",
                "",
                "DITT VAL",
                "- Syna: lyft locket. Visar tärningarna lägre än påståendet förlorar den förra spelaren ett liv. "
                "Är värdet samma eller högre förlorar du ett liv. Meier kostar dubbelt.",
                "- Slå: säg ett strikt högre påstående än det förra. Du får alltid titta på dina egna "
                "tärningar efter slaget om du vill.",
                "- Skicka vidare: skicka bägaren vidare med samma påstående. Du ser inte tärningarna.",
                "",
                f"Om du slår är giltiga påståenden: {', '.join(rules.name(v) for v in higher) or 'inga (påståendet är högst)'}.",
                "",
                "Svara med JSON:",
                '{"action": "syna" | "slå" | "skicka", '
                '"claim": <heltal eller null, endast om du slår>, '
                '"reasoning": "<kort motivering>"}',
            ]
        )

    def _coerce_action(self, value: object) -> str:
        if isinstance(value, str):
            v = value.strip().lower().rstrip("!.")
            if v in ("slå", "sla", "hit", "raise", "höj", "hoj"):
                return "slå"
            if v in ("syna", "call", "se", "syn"):
                return "syna"
            if v in ("skicka", "skicka vidare", "pass", "vidare", "skickar"):
                return "skicka"
        return "skicka"
