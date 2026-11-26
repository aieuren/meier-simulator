"""Analys av insamlade matchprotokoll.

Modulen läser en eller flera JSONL-filer med matchprotokoll, bygger en kompakt
sammanställning (en *digest*) och låter en LLM svara på frågor om materialet.
Digesten hålls liten med flit: hela händelseloggar får inte plats i
modellkontexten, så den innehåller aggregerade mått och fördelningar i stället.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from .legacy import upgrade_record
from .llm import LLMClient, LLMConfig, LLMError, parse_json_object
from .match import PROTOCOL_FORMAT, summarize

#: Fält som måste finnas i en post för att den ska räknas som ett protokoll.
#: ``format`` står inte här: poster skrivna före protokollversionen saknar det
#: men är fullt läsbara i övrigt. De läses in och flaggas i stället för att
#: kastas, så att äldre serier fortfarande går att analysera.
_REQUIRED = ("players", "events", "player_stats", "winner_role")

#: Protokollversioner vi känner igen. 2 är den nuvarande. Poster utan ``format``
#: skrevs före versioneringen och saknar spelarnas förmågor.
_KNOWN_FORMATS = (2,)

#: Hur många av de vanligaste värdena som tas med per fördelning.
_TOP_N = 12

#: Hur många matcher som listas radvis (för tidslinjediagram).
_MAX_SERIES = 100


def normalize_record(obj: Any) -> dict[str, Any] | None:
    """Returnera posten om den ser ut som ett matchprotokoll, annars None.

    En post utan ``format`` är en äldre logg. Den saknar spelarnas förmågor,
    men händelserna och statistiken finns, så den går att analysera. Den
    behålls och får ``format`` 0, vilket sammanställningen flaggar.
    """
    if not isinstance(obj, dict):
        return None
    if not all(key in obj for key in _REQUIRED):
        return None
    if record_format(obj) is None:
        obj = {**obj, "format": 0}
    return obj


def record_format(obj: dict[str, Any]) -> int | None:
    """Protokollversionen som ett tal, eller None om fältet saknas."""
    value = obj.get("format")
    return value if isinstance(value, int) else None


def parse_jsonl_text(text: str) -> tuple[list[dict[str, Any]], int]:
    """Tolka JSONL-text till protokoll. Returnerar (protokoll, antal överhoppade)."""
    records: list[dict[str, Any]] = []
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        # Filerna skrivs aldrig om; äldre nyckelnamn översätts vid inläsning.
        rec = normalize_record(upgrade_record(obj))
        if rec is None:
            skipped += 1
            continue
        records.append(rec)
    return records, skipped


def _top(counter: Counter, n: int = _TOP_N) -> dict[str, int]:
    return {str(k): v for k, v in counter.most_common(n)}


def build_digest(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Bygg en kompakt sammanställning av en eller flera matchers protokoll."""
    summary = summarize(records) if records else {"games": 0, "roles": {}}

    actions: Counter = Counter()
    claims: Counter = Counter()
    outcomes: Counter = Counter()
    unseen_claims = 0
    total_events = 0
    calls = {"caller_wins": 0, "caller_loses": 0}
    series: list[dict[str, Any]] = []

    for i, rec in enumerate(records, start=1):
        for e in rec.get("events", []):
            total_events += 1
            if e.get("kind") == "game_over":
                # Vinnarraden är inte en spelåtgärd – räkna den inte i statistiken.
                continue
            action = e.get("action")
            if action:
                actions[str(action)] += 1
            if action in ("påstå", "slå", "höja") and e.get("claim_name"):
                claims[str(e["claim_name"])] += 1
            if e.get("shown_name"):
                outcomes[str(e["shown_name"])] += 1
            if e.get("unseen"):
                unseen_claims += 1
            if action == "syna":
                calls["caller_loses" if e.get("caller_loses") else "caller_wins"] += 1

        series.append(
            {
                "game": rec.get("game", i),
                "rounds": rec.get("rounds"),
                "winner_role": rec.get("winner_role"),
                "starter": rec.get("starter"),
                "starter_won": rec.get("starter") == rec.get("winner"),
            }
        )

    formats = Counter(record_format(r) for r in records)
    legacy = formats.get(0, 0)
    unknown = sum(n for f, n in formats.items() if f not in _KNOWN_FORMATS and f != 0)

    return {
        "games": len(records),
        "formats": dict(formats),
        "legacy_games": legacy,
        "unknown_format_games": unknown,
        "avg_rounds": summary.get("avg_rounds", 0.0),
        "starter_win_rate": summary.get("starter_win_rate", 0.0),
        "roles": summary.get("roles", {}),
        "tactics": summary.get("tactics", {}),
        "tactics_by_outcome": summary.get("tactics_by_outcome", {}),
        "abilities": summary.get("abilities", {}),
        "setup": summary.get("setup", {}),
        "call_outcomes": calls,
        "actions": _top(actions),
        "claims": _top(claims),
        "outcomes": _top(outcomes),
        "unseen_claims": unseen_claims,
        "events_total": total_events,
        "games_series": series[:_MAX_SERIES],
        "games_series_truncated": len(series) > _MAX_SERIES,
    }


def render_digest_text(digest: dict[str, Any]) -> str:
    """Gör digesten läsbar för modellen (och för en människa i loggen)."""
    lines: list[str] = []
    lines.append(f"Antal matcher: {digest.get('games', 0)}")
    lines.append(f"Snitt antal rundor per match: {digest.get('avg_rounds', 0)}")
    lines.append(
        f"Startspelaren vinner: {digest.get('starter_win_rate', 0)} av matcherna"
    )
    lines.append(f"Påståenden utan att titta totalt: {digest.get('unseen_claims', 0)}")

    lines.append("")
    lines.append("PER ROLL")
    roles = digest.get("roles", {})
    for role, b in roles.items():
        lines.append(
            "- {name} ({role}): {games} matcher, {wins} vinster "
            "(vinst% {win_rate}), påståenden {claims}, bluff {bluffs} (bluff% {bluff_rate}), "
            "utan att titta {unseen} (andel {unseen_rate}), höjningar {raises}, "
            "skicka {passes}, synar {calls} (syn% {call_rate}), "
            "syn lyckas {calls_won}/{calls} ({call_success_rate}), "
            "snitt liv förlorade {avg_lives_lost}, utslagen {eliminated} ({elimination_rate})".format(
                role=role, **b
            )
        )

    lines.append("")
    co = digest.get("call_outcomes", {})
    lines.append(
        f"SYNAR: synaren vann {co.get('caller_wins', 0)}, "
        f"synaren förlorade {co.get('caller_loses', 0)}"
    )

    for label, key in (("ÅTGÄRDER", "actions"), ("PÅSTÅENDEN (vanligast)", "claims"),
                       ("TÄRNINGSUTFALL (vanligast)", "outcomes")):
        dist = digest.get(key, {})
        if dist:
            lines.append("")
            lines.append(label)
            lines.append(", ".join(f"{k}: {v}" for k, v in dist.items()))

    series = digest.get("games_series", [])
    if series:
        lines.append("")
        lines.append("MATCHER I ORDNING (game, rundor, vinnarroll, startspelare vann)")
        for row in series:
            lines.append(
                f"- {row['game']}: {row['rounds']} rundor, {row['winner_role']}, "
                f"startspelare vann: {'ja' if row['starter_won'] else 'nej'}"
            )
        if digest.get("games_series_truncated"):
            lines.append(f"(endast de första {_MAX_SERIES} matcherna visas)")

    if digest.get("legacy_games"):
        lines.append("")
        lines.append(
            f"OBS: {digest['legacy_games']} av {digest['games']} matcher skrevs före "
            "protokollversionen och saknar spelarnas förmågor. Deras händelser och "
            "statistik räknas som vanligt, men FÖRMÅGA MOT UTFALL bygger bara på de "
            "matcher som har profiler."
        )
    if digest.get("unknown_format_games"):
        lines.append("")
        lines.append(
            f"OBS: {digest['unknown_format_games']} matcher har en protokollversion "
            "den här koden inte känner igen. De läses ändå, men fält kan saknas."
        )

    lines.append("")
    lines.append("SPELSÄTT PER ROLL (mätt ur händelserna)")
    tactics = digest.get("tactics", {})
    for role, t in tactics.items():
        lines.append(
            "- {role}: {claims} påståenden. Kliv över förra budet {raise_steps} steg "
            "i snitt, {raise_min_share} av höjningarna var minsta möjliga kliv. "
            "Bluffar låg {bluff_margin} steg över tärningarna i snitt. "
            "Sa svagare än tärningarna i {understate_share} av påståendena "
            "({understate_margin} steg under). Mejer {meier_share} av påståendena. "
            "{calls} synar, i snitt {call_height} steg ner i ordningen, "
            "träffade {call_precision}. Av {claims_challenged} synade påståenden "
            "fälldes {lies_revealed} som lögn.".format(role=role, **t)
        )

    lines.append("")
    lines.append("SPELSÄTT: VANN MOT FÖRLORADE (samma mått, delat på matchutfall)")
    for key, t in (digest.get("tactics_by_outcome") or {}).items():
        lines.append(
            "- {key}: {claims} påståenden, kliv {raise_steps} steg, "
            "bluffmarginal {bluff_margin} steg, svagare än tärningarna {understate_share}, "
            "Mejer {meier_share}, {calls} synar på höjd {call_height} "
            "(träff {call_precision}), påståenden som höll vid syn {claims_upheld}".format(
                key=key, **t
            )
        )

    lines.append("FÖRMÅGA MOT UTFALL (vinstfrekvens per nivå)")
    abilities = digest.get("abilities", {})
    if not abilities:
        lines.append(
            "  (tomt: matcherna saknar spelarnas förmågor, så nivåerna kan inte "
            "räknas. Kör en ny serie med nuvarande version för att få dem.)"
        )
    for key, levels in abilities.items():
        for level, b in levels.items():
            lines.append(
                f"- {key} {level}: {b['games']} matcher, vinst {b['win_rate']}, "
                f"snitt liv förlorade {b['avg_lives_lost']}, bluff {b['bluff_rate']}, "
                f"syn {b['call_rate']} (träff {b['call_success_rate']}), "
                f"spelare: {', '.join(b['players'])}"
            )

    setup = digest.get("setup") or {}
    if setup:
        lines.append("")
        lines.append(f"Uppsättning: {setup.get('player_count')} spelare, "
                     f"{', '.join(setup.get('roles') or [])}")
        lives = setup.get("lives_per_player") or []
        if lives:
            lines.append(f"Liv per spelare: {lives}")
        else:
            lines.append("Liv per spelare: okänt (loggen skrevs före protokollversionen)")
        lines.append(
            "Profiler oförändrade i serien: "
            f"{'ja' if setup.get('stable') else 'nej'}"
        )

    lines.append("")
    lines.append("VAD SAMMANSTÄLLNINGEN INTE INNEHÅLLER")
    events = digest.get("events_total", 0)
    lines.append(
        f"Den bygger på {digest.get('games', 0)} matcher och {events} spelhändelser, "
        "men visar bara aggregat och den korta matchlistan ovan."
    )
    lines.append(
        "- Inga enskilda tärningsslag eller rundsekvenser. Frågor som "
        "'vad slogs i runda 3' går inte att besvara härifrån."
    )
    lines.append(
        "- Inga enskilda påståenden per spelare och tillfälle, bara fördelningar."
    )
    lines.append(
        "- Ingen information om vem som mötte vem i en viss runda, utöver "
        "matchlistans startspelare och vinnare."
    )
    lines.append(
        "- Inga motiveringar från agenterna bakom sina beslut."
    )
    lines.append(
        "- Bara de vanligaste värdena per fördelning, och bara de första "
        f"{_MAX_SERIES} matcherna i matchlistan."
    )

    return "\n".join(lines)


_SYSTEM_PROMPT = """\
Du är dataanalytiker för tärningsspelet Meier (bluffspel med två tärningar). Du
får en sammanställning av spelade matcher och en fråga om materialet.

Svara ALLTID med ett JSON-objekt och inget annat:
{"answer": "<ditt svar i markdown>", "chart": <diagram eller null>, "followups": ["<fråga>", "<fråga>"], "cannot_answer": <null eller text>}

Fältet "cannot_answer":
- Sätt det till null när du kan besvara frågan med sammanställningen.
- Sätt det annars till en kort mening (på svenska) om vilken detalj som
  saknas, t.ex. "Frågan kräver enskilda tärningsslag, som inte finns i
  sammanställningen". Skriv då också i "answer" vad som ändå går att säga.
- Sätt det INTE för att frågan är svår eller för att underlaget är litet. Det
  gäller bara när själva detaljtypen saknas i sammanställningen.

Diagrammet ska vara null om inget diagram passar. Annars något av:
- stapel: {"type": "bar", "title": "...", "labels": ["a", "b"], "values": [1, 2]}
- linje:  {"type": "line", "title": "...", "labels": ["a", "b"], "series": [{"name": "x", "values": [1, 2]}]}
- tabell: {"type": "table", "title": "...", "columns": ["A", "B"], "rows": [["1", "2"]]}

Regler:
- Använd bara siffror som finns i sammanställningen. Hitta inte på data.
- Räkna gärna om till procent eller andelar när det gör svaret tydligare, och visa talen.
- Är underlaget för litet för en säker slutsats: säg det rakt ut.
- Skriv kort och konkret på svenska. Ingen inledning, inga ursäkter.
- Föreslå 2-3 lämpliga följdfrågor i "followups"."""


def _client() -> LLMClient:
    """En LLM-klient med större svarsutrymme än spelets (analys kräver mer text)."""
    cfg = LLMConfig.from_env()
    cfg.max_tokens = max(cfg.max_tokens, 2000)
    return LLMClient(config=cfg)


def _clean_chart(chart: Any) -> dict[str, Any] | None:
    """Släpp igenom bara diagram som frontend kan rita."""
    if not isinstance(chart, dict):
        return None
    ctype = chart.get("type")
    if ctype in ("bar", "line"):
        if not isinstance(chart.get("labels"), list):
            return None
    elif ctype == "table":
        if not isinstance(chart.get("columns"), list):
            return None
    else:
        return None
    return chart


def ask(
    digest: dict[str, Any],
    question: str,
    *,
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """Låt en LLM svara på en fråga om det sammanställda materialet."""
    question = (question or "").strip()
    if not question:
        raise ValueError("Frågan är tom")

    user = f"DATA\n{render_digest_text(digest)}\n\nFRÅGA\n{question}"
    llm = client or _client()
    raw = llm.complete(_SYSTEM_PROMPT, user, json_mode=True)

    try:
        data = parse_json_object(raw)
    except LLMError:
        # Modellen svarade utan giltig JSON: visa texten som den är.
        return {
            "answer": raw,
            "chart": None,
            "followups": [],
            "cannot_answer": None,
            "usage": llm.last_usage,
        }

    followups = data.get("followups")
    if not isinstance(followups, list):
        followups = []
    followups = [str(f) for f in followups if str(f).strip()][:4]

    cannot = data.get("cannot_answer")
    cannot = str(cannot).strip() if cannot else ""
    cannot = cannot or None

    return {
        "answer": str(data.get("answer") or "").strip(),
        "chart": _clean_chart(data.get("chart")),
        "followups": followups,
        "cannot_answer": cannot,
        "usage": llm.last_usage,
    }


class AnalysisStore:
    """Håller de inlästa matchprotokollen och deras sammanställning.

    Protokollen grupperas per källfil, så att en enskild fil kan tas bort
    igen när användaren avmarkerar den.
    """

    def __init__(self) -> None:
        self._sources: dict[str, list[dict[str, Any]]] = {}
        self._skipped: dict[str, int] = {}
        self.lock = threading.Lock()

    def add_text(self, name: str, text: str) -> int:
        """Läs in protokollen i en JSONL-text under ``name``. Returnerar antalet."""
        records, skipped = parse_jsonl_text(text)
        with self.lock:
            self._sources[name] = records
            self._skipped[name] = skipped
        return len(records)

    def add_file(self, path: str | Path) -> int:
        p = Path(path)
        return self.add_text(p.name, p.read_text(encoding="utf-8"))

    def remove(self, name: str) -> bool:
        """Ta bort en inläst källa. Returnerar True om den fanns."""
        with self.lock:
            self._skipped.pop(name, None)
            return self._sources.pop(name, None) is not None

    def sources(self) -> list[str]:
        with self.lock:
            return list(self._sources)

    def clear(self) -> None:
        with self.lock:
            self._sources = {}
            self._skipped = {}

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return [rec for records in self._sources.values() for rec in records]

    def digest(self) -> dict[str, Any]:
        return build_digest(self.snapshot())

    def info(self) -> dict[str, Any]:
        with self.lock:
            return {
                "games": sum(len(v) for v in self._sources.values()),
                "sources": list(self._sources),
                "skipped": sum(self._skipped.values()),
            }
