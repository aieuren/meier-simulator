"""Motståndarläsaren: LLM:en tolkar historiken och sätter motståndarprofilen.

Ansvarsfördelningen är medvetet skarp:

- **Sekreteraren** (:class:`~meier.opponents.OpponentTracker`) bokför vad som
  hänt vid bordet — antal påstående, hur många som avslöjats, hur många av dem som var
  lögner, hur spelaren svarat. Rena siffror, ingen tolkning.
- **Läsaren** (denna modul) tolkar siffrorna och avgör **helt själv** vad de
  betyder: "den här spelaren bluffar ofta", "den ger upp under press". Det är
  LLM:ens uppgift.

Läsaren får **aldrig** se motståndarens verkliga parametrar — bara offentligt
observerbart beteende. Det är inte bara en konvention: sammanställningen byggs av
``OpponentTracker``, som per konstruktion bara tar emot offentliga händelser
(se modulens docstring).

Utan LLM (utvärderingsläget) faller läsaren tillbaka på sekreterarens
aritmetiska sammanställning, så en match kan alltid spelas klart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..llm import LLMClient, parse_json_object
from ..opponents import OpponentProfile, OpponentTracker, _clamp01

#: Kort regeltext så modellen kan tolka siffrorna rätt.
_RULES = (
    "Meier spelas med två tärningar. Tärningarna läses med högsta först (2 och 5 "
    "blir 52). 21 kallas Meier och är högst, 31 lägst. Vid en syn: visar "
    "tärningarna lägre än påståendet förlorar den som påstod ett liv, annars synaren. "
    "Meier kostar dubbelt. Att 'skicka vidare' betyder att man ger upp påståendet."
)

_SYSTEM = (
    "Du är en erfaren Meier-spelare som bedömer dina motståndare. Du får en "
    "sammanställning av vad som offentligt hänt vid bordet och ska avgöra hur en "
    "viss motståndare spelar.\n"
    f"REGLER: {_RULES}\n"
    "Du ser bara offentliga händelser — aldrig motståndarens tärningar eller "
    "dess interna inställningar. Gissa utifrån beteendet.\n"
    "Bedöm på en skala 0–1:\n"
    "  estimated_risk: hur gärna motståndaren tar en osäker chans (synar).\n"
    "  estimated_press: hur ofta motståndaren bluffar och pressar påståendet.\n"
    "  estimated_predictability: hur förutsägbar motståndaren är.\n"
    "  confidence: hur säker du är, givet hur mycket data som finns. Lite data "
    "ger låg confidence.\n"
    "  type: en kort etikett på svenska, t.ex. 'bluffbenägen', 'försiktig', "
    "'oförutsägbar' eller 'okänd'.\n"
    'Svara med JSON: {"estimated_risk": 0.5, "estimated_press": 0.5, '
    '"estimated_predictability": 0.5, "type": "...", "confidence": 0.0}'
)


def _fmt_rate(value: Any) -> str:
    return "–" if value is None else f"{float(value):.2f}"


def _summarise(player: str, ev: dict, *, table_reveals: int, strength: float) -> str:
    """Gör sekreterarens siffror till en läsbar sammanställning för modellen."""
    lines = [
        f"Motståndare: {player}",
        f"Synliga (frivilliga) påståenden: {ev['visible_bids']}",
        f"Avslöjade påståenden (efter syn): {ev['revealed']}",
        f"Därav lögner: {ev['revealed_bluffs']}",
        f"Bluff-frekvens bland avslöjade: {_fmt_rate(ev['bluff_rate'])}",
        f"Svar på påståenden: {ev['decisions']} totalt",
        f"  skickade vidare: {ev['passes']} (frekvens {_fmt_rate(ev['pass_rate'])})",
        f"  slog högre: {ev['raises']}",
        f"  synade: {ev['calls']} (frekvens {_fmt_rate(ev['call_rate'])})",
        f"  synen gick hem: {ev['calls_won']}",
        "",
        "JÄMFÖRELSE: en vanlig Meier-spelare synar ungefär 19 % av gångerna och "
        "bluffar ofta (runt 70 % av de avslöjade påståendena). Bedöm motståndaren "
        "RELATIVT det — inte som om 0 vore normalt.",
        "",
        f"Synar som avgjorts vid bordet hittills (alla spelare): {table_reveals}",
        f"Underlagets styrka: {strength:.2f} av 1,00 "
        "(0 = inget facit än, 1 = gott om facit)",
    ]
    return "\n".join(lines)


@dataclass
class OpponentReader:
    """Bygger motståndarprofiler. LLM:en tolkar; sekreteraren levererar underlag.

    ``llm`` är valfri. Utan den (utvärderingsläget) används sekreterarens
    aritmetiska profil, så spelet går vidare utan nätverk.

    Profilen räknas om bara när **nytt bevis** blivit offentligt, och cachas
    sedan. En match gör därför ett fåtal anrop per motståndare, inte ett per
    beslut.
    """

    llm: LLMClient | None = None
    #: Anropen räknas, så en serie kan rapportera hur många profiler som byggdes.
    calls: int = field(default=0, init=False)
    _cache: dict[str, tuple[tuple, OpponentProfile]] = field(default_factory=dict, init=False)

    @staticmethod
    def _signature(ev: dict) -> tuple:
        """Ändras när nytt bevis tillkommit; annars återanvänds profilen."""
        return (
            ev["revealed"],
            ev["revealed_bluffs"],
            ev["decisions"],
            ev["passes"],
            ev["calls"],
        )

    def profile(self, tracker: OpponentTracker, player: str) -> OpponentProfile:
        """Motståndarprofilen för ``player``. LLM:en avgör; trackern underbygger."""
        ev = tracker.evidence(player)
        signature = self._signature(ev)
        cached = self._cache.get(player)
        if cached is not None and cached[0] == signature:
            return cached[1]

        profile = self._ask_llm(player, ev, tracker) if self.llm is not None else None
        if profile is None:
            profile = tracker.statistical_profile(player)
        self._cache[player] = (signature, profile)
        return profile

    def _ask_llm(self, player: str, ev: dict, tracker: OpponentTracker) -> OpponentProfile | None:
        """Låt LLM:en tolka sammanställningen. ``None`` om den inte svarar."""
        if not tracker_has_evidence(ev):
            # Inget att tolka: låt sekreteraren svara (populationen).
            return None
        table_reveals = tracker.reveal_count()
        strength = tracker.evidence_strength()
        try:
            raw = self.llm.complete(
                _SYSTEM,
                _summarise(
                    player, ev, table_reveals=table_reveals, strength=strength
                ),
                json_mode=True,
            )
            data = parse_json_object(raw)
        except Exception:  # noqa: BLE001 - en trasig läsning får aldrig fälla en match
            return None
        if not data:
            return None
        self.calls += 1
        # LLM:en får säga hur säker den är på sin tolkning. Men underlaget sätter
        # ett **tak**: en bild byggd på en enda syn får inte räknas som säker,
        # hur tvärsäker modellen än är. Bordets facit är ett hårdare mått än
        # modellens självförtroende, och det växer när fler synar avslöjas.
        asked = _clamp01(data.get("confidence", 0.0))
        return OpponentProfile(
            risk=_clamp01(data.get("estimated_risk", 0.5)),
            press=_clamp01(data.get("estimated_press", 0.5)),
            predictability=_clamp01(data.get("estimated_predictability", 0.5)),
            kind=str(data.get("type") or "okänd")[:32],
            confidence=min(asked, strength),
            source="llm",
        )


def tracker_has_evidence(ev: dict) -> bool:
    """Finns något alls att tolka i sammanställningen?"""
    return (ev["revealed"] > 0) or (ev["decisions"] > 0)
