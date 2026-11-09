"""Domaragent för Mejeri.

Domaren är också en LLM-baserad agent, men till skillnad från spelarna är dess
uppgift att *övervaka* att reglerna följs. Den granskar varje svar en spelare ger
och säger **ok** eller kommer med **invändningar**.

Domaren litar inte blint på språkmodellen: de formella regelkontrollerna
(rangordning, giltiga utfall, tvungen höjning) är alltid auktoritativa. LLM-lagret
lägger till en språklig kommentar och fångar otydligheter, men kan aldrig godkänna
ett formellt regelbrott.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import rules
from ..llm import LLMClient, LLMError
from .base import Agent, Role

REFEREE_ROLE = Role(
    key="domare",
    name="Domare-Doris",
    description="Opartisk domare som övervakar att alla följer reglerna.",
    style=(
        "Du är en sträng men rättvis domare i tärningsspelet Mejeri. Du kontrollerar "
        "att varje bud är ett giltigt utfall, att den som slår alltid höjer, och att "
        "syn och Mejer hanteras rätt. Du säger kort och tydligt om svaret är ok eller "
        "om det finns en invändning."
    ),
)


@dataclass
class Verdict:
    """Domarens utlåtande om ett svar."""

    ok: bool
    objections: list[str] = field(default_factory=list)
    comment: str = ""
    source: str = "regler"  # "regler" eller "llm"

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "objections": list(self.objections),
            "comment": self.comment,
            "source": self.source,
        }


class RefereeAgent(Agent):
    """Domare som granskar spelarnas svar mot reglerna."""

    def __init__(self, llm: LLMClient | None = None, *, use_llm: bool = True):
        super().__init__(role=REFEREE_ROLE, llm=llm or LLMClient())
        self.use_llm = use_llm

    def system_prompt(self) -> str:
        ranking = ", ".join(rules.name(v) for v in rules.RANKING)
        return (
            f"Du är domaren {self.role.name} i tärningsspelet Mejeri.\n"
            f"Roll: {self.role.description}\n\n"
            "REGLER\n"
            "- Två tärningar läses med den högsta först: 2 och 5 blir 52.\n"
            f"- Ordning (högst först): {ranking}.\n"
            "- Ett bud måste vara ett giltigt utfall.\n"
            "- Den som slår måste säga ett strikt högre bud än det förra.\n"
            "- Vid syn: visar tärningarna lägre än budet förlorar budgivaren, annars den som synar.\n"
            "- Mejer (21) kostar dubbelt.\n\n"
            "Din uppgift är att säga om ett svar är godkänt eller om det finns en invändning.\n"
            "Svara ALLTID med ett JSON-objekt: "
            '{"ok": true|false, "comment": "<kort utlåtande>"}'
        )

    # -- Granska en spelares svar (bud) -------------------------------------
    def review_announcement(
        self,
        dice: tuple[int, int],
        bid: int,
        *,
        previous_bid: int | None = None,
        line: str = "",
        proposed: int | None = None,
        corrected: bool = False,
    ) -> Verdict:
        """Granska spelarens svar.

        ``proposed`` är det bud modellen faktiskt föreslog innan eventuell
        regelkorrigering, och ``bid`` är det bud som står. Domaren dömer svaret
        som spelaren gav – alltså det råa förslaget om det finns.
        """
        shown = rules.read_dice(*dice)
        answer = proposed if proposed is not None else bid
        objections: list[str] = []

        if not rules.is_valid_value(answer):
            objections.append(f"Budet {answer} är inte ett giltigt Mejeri-utfall.")
        elif previous_bid is not None:
            if not rules.is_valid_value(previous_bid):
                objections.append(f"Det tidigare budet {previous_bid} är ogiltigt.")
            elif not rules.is_higher(answer, previous_bid):
                objections.append(
                    f"Spelaren slår men höjer inte: {rules.name(answer)} är inte högre än "
                    f"{rules.name(previous_bid)}."
                )

        verdict = Verdict(
            ok=not objections,
            objections=objections,
            comment=self._rule_comment(objections, bid, shown, previous_bid, corrected),
            source="regler",
        )

        if self.use_llm:
            verdict = self._llm_second_opinion(
                verdict, dice, bid, previous_bid, line, proposed=proposed
            )
        return verdict

    # -- Granska en spelares beslut mot ett bud ----------------------------
    def review_decision(
        self,
        action: str,
        *,
        bid: int,
        new_bid: int | None = None,
        line: str = "",
    ) -> Verdict:
        objections: list[str] = []
        if action not in ("slå", "syna", "skicka"):
            objections.append(f"Okänd handling: {action}.")
        if not rules.is_valid_value(bid):
            objections.append(f"Budet {bid} är ogiltigt.")
        if action == "slå":
            if new_bid is None:
                objections.append("Spelaren slår men anger inget nytt bud.")
            elif not rules.is_higher(new_bid, bid):
                objections.append(
                    f"Spelaren slår men höjer inte: {rules.name(new_bid)} är inte högre än {rules.name(bid)}."
                )

        return Verdict(
            ok=not objections,
            objections=objections,
            comment="Svaret följer reglerna." if not objections else "Se invändningar.",
            source="regler",
        )

    # -- Interna hjälpare ---------------------------------------------------
    def _rule_comment(
        self,
        objections: list[str],
        bid: int,
        shown: int,
        previous_bid: int | None,
        corrected: bool = False,
    ) -> str:
        if objections:
            return "Invändning: " + " ".join(objections)
        extra = ""
        if previous_bid is not None:
            extra = f" och höjer korrekt över {rules.name(previous_bid)}"
        note = " (budet korrigerades för att följa reglerna)" if corrected else ""
        return f"Godkänt: {rules.name(bid)} är ett giltigt bud{extra}.{note}"

    def _llm_second_opinion(
        self,
        verdict: Verdict,
        dice: tuple[int, int],
        bid: int,
        previous_bid: int | None,
        line: str,
        *,
        proposed: int | None = None,
    ) -> Verdict:
        """Låt domar-agenten kommentera. Formella fel kan inte övertalas bort."""
        shown = rules.read_dice(*dice)
        answer = proposed if proposed is not None else bid
        context = "\n".join(
            [
                f"Tärningarna visar: {rules.name(shown)}.",
                f"Spelarens bud: {rules.name(answer)}."
                if rules.is_valid_value(answer)
                else f"Spelarens bud: {answer} (ogiltigt).",
                f"Tidigare bud: {rules.name(previous_bid)}." if previous_bid is not None else "Tidigare bud: inget (första budet).",
                f"Spelarens replik: \"{line}\"" if line else "",
                f"Formell regelkontroll: {'OK' if verdict.ok else 'INVÄNDNING – ' + ' '.join(verdict.objections)}",
                "",
                "Bekräfta med ett kort utlåtande. Du får inte godkänna ett formellt regelbrott.",
                'Svara med JSON: {"ok": true|false, "comment": "<kort utlåtande>"}',
            ]
        )
        try:
            data = self.respond(context)
        except LLMError:
            return verdict

        comment = str(data.get("comment") or "").strip()
        llm_ok = data.get("ok")
        # LLM får bara skärpa, aldrig upphäva, ett formellt underkänt svar.
        ok = verdict.ok and (llm_ok is not False)
        merged = verdict
        if comment:
            merged = Verdict(
                ok=ok,
                objections=verdict.objections,
                comment=comment,
                source="llm",
            )
        elif not ok:
            merged = Verdict(ok=ok, objections=verdict.objections, comment=verdict.comment, source="llm")
        return merged
