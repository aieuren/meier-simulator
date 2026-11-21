"""Meier-spelaragenten.

Agenten simulerar en spelare i tärningsspelet Meier. Den centrala uppgiften är:
givet utfallet av ett tärningsslag med två tärningar, bestäm hur spelaren
svarar. Spelaren har tittat i smyg på tärningarna och ska säga ett resultat till
nästa spelare – sanningen, ett högre eller ett lägre.

Agenten kan också fatta beslut när den möter ett påstående från en annan spelare:
**Slå** (skaka bägaren på nytt och säga ett högre påstående), **Syna** eller
**Skicka vidare**.
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
    bid: int  # vad spelaren säger (efter regelkorrigering)
    truth: bool  # säger spelaren sanningen?
    line: str  # repliken spelaren säger
    reasoning: str  # varför
    role: str
    proposed: int | None = None  # rå värdet modellen föreslog (kan vara ogiltigt)
    corrected: bool = False  # behövde påståendet korrigeras för att följa reglerna?
    blind: bool = False  # påstod spelaren utan att titta på tärningarna?
    choice_line: str = ""  # vid tvingad höjning: replik för titta/blint-valet
    choice_reasoning: str = ""  # vid tvingad höjning: motivering för valet

    def to_dict(self) -> dict:
        return {
            "dice": list(self.dice),
            "shown": self.shown,
            "shown_name": rules.name(self.shown),
            "bid": self.bid,
            "bid_name": rules.name(self.bid),
            "truth": self.truth,
            "lie": not self.truth,
            "line": self.line,
            "reasoning": self.reasoning,
            "role": self.role,
            "proposed": self.proposed,
            "corrected": self.corrected,
            "blind": self.blind,
            "choice_line": self.choice_line,
            "choice_reasoning": self.choice_reasoning,
        }


@dataclass
class ActionDecision:
    """Spelarens val när den möter ett påstående: Slå, Syna eller Skicka vidare.

    Används också för titta/blint-valet vid en tvingad höjning, där ``action``
    är ``"titta"`` eller ``"blint"``.
    """

    action: str  # "slå", "syna", "skicka" (eller "titta"/"blint" vid tvingad höjning)
    bid: int | None  # nytt påstående om spelaren slår
    line: str
    reasoning: str
    role: str

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "bid": self.bid,
            "bid_name": rules.name(self.bid) if self.bid is not None else None,
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
            "- Du har tittat i smyg på tärningarna och ska säga ett påstående till nästa spelare: "
            "att tärningarna visar minst ett visst värde. Det kan vara sant, ett högre (en bluff) "
            "eller ett lägre (sant, men svagare).\n"
            "- Nästa spelare kan Slå (säga ett högre påstående), Syna (lyfta locket och granska "
            "påståendet) eller Skicka vidare (ta över ansvaret för samma påstående).\n"
            "- Om bägaren går ett helt varv tillbaka till den som påstod måste denne höja. "
            "Tärningarna slås då om, och spelaren får själv välja att titta på dem eller påstå blint.\n"
            "- Om någon synar och tärningarna visar lägre än påståendet förlorar den som påstod ett liv. "
            "Visar de samma eller högre förlorar den som synade ett liv.\n"
            "- Meier kostar dubbelt: om påståendet är Meier, eller om tärningarna visar Meier när "
            "någon synar, förlorar man två liv.\n\n"
            "Terminologi: säg alltid 'påstående' (aldrig 'bud') när du talar om det du säger.\n\n"
            "Du svarar ALLTID med ett JSON-objekt och inget annat."
        )

    # -- Kärnfunktion: givet tärningsutfallet, hur svarar spelaren? ---------
    def announce(
        self,
        dice: tuple[int, int],
        *,
        previous_bid: int | None = None,
        opponent: str | None = None,
    ) -> Announcement:
        """Bestäm spelarens påstående givet utfallet av ett tärningsslag.

        ``previous_bid`` är det senaste påståendet i rundan om spelaren höjer efter
        ett helt varv och alltså redan har tittat på tärningarna. Då måste påståendet
        vara strikt högre. Att **slå** mot ett påstående går i stället via
        :meth:`announce_blind`, för då får spelaren inte titta på tärningarna.
        """
        shown = rules.read_dice(*dice)
        higher = rules.higher_options(previous_bid) if previous_bid is not None else []

        context = self._announce_context(dice, shown, previous_bid, higher)
        data = self.respond(context)

        proposed = self._raw_bid(data.get("bid"))
        bid = self._coerce_bid(data.get("bid"), shown, previous_bid, higher)
        line = str(data.get("line") or self._default_line(bid, shown)).strip()
        reasoning = str(data.get("reasoning") or "").strip()

        return Announcement(
            dice=(dice[0], dice[1]),
            shown=shown,
            bid=bid,
            truth=bid == shown,
            line=line,
            reasoning=reasoning,
            role=self.role.key,
            proposed=proposed,
            corrected=proposed != bid,
        )

    def announce_blind(
        self, dice: tuple[int, int], *, previous_bid: int, opponent: str | None = None
    ) -> Announcement:
        """Spelaren **slår** och måste säga ett strikt högre påstående.

        Spelaren skakar bägaren själv och får inte lyfta på locket – bägaren är
        stängd och påståendet måste vara strikt högre oavsett vad tärningarna visar.
        Tärningarna ``dice`` är det nya slaget; de används bara för att kunna
        avgöra en eventuell syn senare.
        """
        if not rules.is_valid_value(previous_bid):
            raise ValueError(f"{previous_bid} är inte ett giltigt påstående")
        shown = rules.read_dice(*dice)
        higher = rules.higher_options(previous_bid)

        context = self._blind_announce_context(previous_bid, higher)
        data = self.respond(context)

        proposed = self._raw_bid(data.get("bid"))
        bid = self._coerce_blind_bid(data.get("bid"), previous_bid, higher)
        line = str(data.get("line") or self._default_line(bid, shown)).strip()
        reasoning = str(data.get("reasoning") or "").strip()

        return Announcement(
            dice=(dice[0], dice[1]),
            shown=shown,
            bid=bid,
            truth=bid == shown,
            line=line,
            reasoning=reasoning,
            role=self.role.key,
            proposed=proposed,
            corrected=proposed != bid,
            blind=True,
        )

    def announce_forced(
        self, dice: tuple[int, int], *, previous_bid: int, opponent: str | None = None
    ) -> Announcement:
        """Budgivaren måste höja när bägaren gått ett helt varv.

        Tärningarna har redan slagits om av motorn. Spelaren får själv välja om
        den vill titta på dem (som vid ett vanligt påstående) eller påstå blint (som
        vid ett slag). Båda sätten är tillåtna – valet är spelarens.
        """
        if not rules.is_valid_value(previous_bid):
            raise ValueError(f"{previous_bid} är inte ett giltigt påstående")
        higher = rules.higher_options(previous_bid)
        if not higher:
            raise ValueError(
                f"Kan inte höja: {rules.name(previous_bid)} är högst, det finns inget högre påstående"
            )
        choice = self._wants_blind_forced(previous_bid, higher)
        if choice.action == "blint":
            # Spelaren väljer att påstå blint utan att titta på de nya tärningarna.
            ann = self.announce_blind(
                dice, previous_bid=previous_bid, opponent=opponent
            )
        else:
            # Spelaren tittar på de nya tärningarna och höjer som vid ett vanligt påstående.
            ann = self.announce(dice, previous_bid=previous_bid, opponent=opponent)
        return replace(ann, choice_line=choice.line, choice_reasoning=choice.reasoning)

    def _wants_blind_forced(self, previous_bid: int, higher: list[int]) -> ActionDecision:
        """Fråga spelaren: titta på de nya tärningarna eller påstå blint?

        Returnerar valet som en :class:`ActionDecision` så att både själva valet
        (``action == "blint"`` eller ``"titta"``) och dess motivering bevaras.
        """
        context = self._forced_choice_context(previous_bid, higher)
        data = self.respond(context)
        blind = self._coerce_blind_choice(data.get("blind"))
        return ActionDecision(
            action="blint" if blind else "titta",
            bid=None,
            line=str(data.get("line") or "").strip(),
            reasoning=str(data.get("reasoning") or "").strip(),
            role=self.role.key,
        )

    def _forced_choice_context(self, previous_bid: int, higher: list[int]) -> str:
        return "\n".join(
            [
                "TITTA ELLER BLINT",
                "SITUATIONEN",
                f"Bägaren har gått ett helt varv och är tillbaka hos dig. Du måste höja "
                f"över {rules.name(previous_bid)}.",
                "Tärningarna har slagits om. Du får själv välja hur du gör:",
                "- Titta på de nya tärningarna och säga ett påstående (som vid ett vanligt påstående).",
                "- Påstå blint utan att titta (som när man slår).",
                "Båda sätten är tillåtna. Valet är ditt.",
                f"Giltiga påståenden: {', '.join(rules.name(v) for v in higher)}.",
                "",
                "Svara med JSON:",
                '{"blind": <true om du påstår utan att titta, false om du tittar>, '
                '"line": "<kort replik>", '
                '"reasoning": "<kort motivering>"}',
            ]
        )

    @staticmethod
    def _coerce_blind_choice(value: object) -> bool:
        """Tolka modellens val av titta (False) eller påstå blint (True)."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "ja", "j", "blint", "blind", "utan att titta"):
                return True
            if v in ("false", "nej", "n", "titta", "tittar"):
                return False
        return False

    def _blind_announce_context(self, previous_bid: int, higher: list[int]) -> str:
        return "\n".join(
            [
                "SITUATIONEN",
                f"Du slår bägaren och måste säga ett strikt högre påstående än {rules.name(previous_bid)}.",
                "Du skakar bägaren själv och lyfter inte på locket – du ser inte tärningarna.",
                "Du MÅSTE säga ett strikt högre påstående än det förra, vad tärningarna än visar.",
                f"Giltiga påståenden: {', '.join(rules.name(v) for v in higher) or 'inga (påståendet är högst)'}.",
                "",
                "UPPGIFT",
                "Säg ett högre påstående. Du får inte lyfta på locket.",
                "",
                "Svara med JSON:",
                '{"bid": <heltal, ett giltigt utfall högre än det förra>, '
                '"line": "<repliken du säger>", '
                '"reasoning": "<kort motivering>"}',
            ]
        )

    def _coerce_blind_bid(self, value: object, previous_bid: int, higher: list[int]) -> int:
        """Se till att ett slag-påstående är giltigt och strikt högre."""
        if not higher:
            raise ValueError(
                f"Kan inte slå: {rules.name(previous_bid)} är högst, det finns inget högre påstående"
            )
        bid: int | None = None
        if isinstance(value, int) and not isinstance(value, bool) and rules.is_valid_value(value):
            bid = value
        elif isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if digits and rules.is_valid_value(int(digits)):
                bid = int(digits)

        if bid is None or not rules.is_higher(bid, previous_bid):
            # Minsta möjliga höjning om modellen inte gav ett giltigt högre påstående.
            bid = higher[-1]
        return bid

    @staticmethod
    def _raw_bid(value: object) -> int | None:
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
        previous_bid: int | None,
        higher: list[int],
    ) -> str:
        lines = [
            "TÄRNINGSLAGET",
            f"Tärning 1: {dice[0]}, Tärning 2: {dice[1]}.",
            f"Läses som: {shown} ({rules.name(shown)}).",
            f"Du ser alltså {rules.name(shown)}.",
        ]
        if previous_bid is not None:
            lines += [
                "",
                "SITUATIONEN",
                f"Du slår efter ett påstående på {rules.name(previous_bid)}.",
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
            '{"bid": <heltal, ett giltigt utfall>, '
            '"line": "<repliken du säger>", '
            '"reasoning": "<kort motivering>"}',
        ]
        return "\n".join(lines)

    def _coerce_bid(
        self,
        value: object,
        shown: int,
        previous_bid: int | None,
        higher: list[int],
    ) -> int:
        """Se till att påståendet är giltigt och följer reglerna."""
        bid: int | None = None
        if isinstance(value, int) and rules.is_valid_value(value):
            bid = value
        elif isinstance(value, str) and value.strip().isdigit():
            candidate = int(value.strip())
            if rules.is_valid_value(candidate):
                bid = candidate

        if bid is None:
            # Modellen svarade inte med ett giltigt utfall – fall tillbaka på sanningen.
            bid = shown

        if previous_bid is not None and not rules.is_higher(bid, previous_bid):
            # Måste höja. Välj ett högre påstående så nära det visade som möjligt.
            options = higher or [rules.RANKING[0]]
            bid = min(options, key=lambda v: abs(rules.rank(v) - rules.rank(shown)))
        return bid

    def _default_line(self, bid: int, shown: int) -> str:
        return f"Jag säger {rules.name(bid)}."

    # -- Beslut mot ett påstående: Slå, Syna eller Skicka vidare -------------
    def decide(self, bid: int, *, lives: int = 3, opponent: str | None = None) -> ActionDecision:
        """Välj handling när en annan spelare har sagt ``bid``.

        Spelaren kan **Slå** (höja), **Syna** eller **Skicka vidare**.
        ``opponent`` är namnet på den som håller påståendet. Den här LLM-agenten
        använder det inte, men tar emot det så att motorn kan behandla alla
        agenttyper lika (den strategiska agenten läser det).
        """
        if not rules.is_valid_value(bid):
            raise ValueError(f"{bid} är inte ett giltigt påstående")

        higher = rules.higher_options(bid)
        context = self._decide_context(bid, higher, lives)
        data = self.respond(context)

        action = self._coerce_action(data.get("action"))
        new_bid: int | None = None
        if action == "slå":
            if not higher:
                # Budet är redan högst (Meier) – går inte att slå.
                action = "skicka"
            else:
                new_bid = self._coerce_bid(data.get("bid"), higher[-1], bid, higher)
                if not rules.is_higher(new_bid, bid):
                    new_bid = higher[-1]
        line = str(data.get("line") or "").strip()
        reasoning = str(data.get("reasoning") or "").strip()

        return ActionDecision(
            action=action, bid=new_bid, line=line, reasoning=reasoning, role=self.role.key
        )

    def _decide_context(self, bid: int, higher: list[int], lives: int) -> str:
        return "\n".join(
            [
                "SITUATIONEN",
                f"En annan spelare har sagt {rules.name(bid)}.",
                f"Du har {lives} liv kvar.",
                "",
                "DITT VAL",
                "- Slå: säg ett strikt högre påstående än det förra.",
                "- Syna: lyft locket. Visar tärningarna lägre än påståendet förlorar den förra spelaren ett liv. "
                "Är värdet samma eller högre förlorar du ett liv. Meier kostar dubbelt.",
                "- Skicka vidare: skicka bägaren vidare med samma påstående. Du ser inte tärningarna.",
                "",
                f"Om du slår är giltiga påståenden: {', '.join(rules.name(v) for v in higher) or 'inga (påståendet är högst)'}.",
                "",
                "Svara med JSON:",
                '{"action": "slå" | "syna" | "skicka", '
                '"bid": <heltal eller null, endast om du slår>, '
                '"line": "<repliken du säger>", '
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
