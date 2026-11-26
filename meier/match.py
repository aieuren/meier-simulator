"""Batchkörning och statistik för Meier.

Modulen spelar många matcher mellan LLM-baserade agenter och samlar varje
match i ett strukturerat, JSON-serialiserbart protokoll. Protokollet är byggt
för efteranalys: varje åtgärd sparas med spelare, roll, tärningsutfall, påstående,
om påståendet var sant eller en bluff, livsställning och rundnummer. Därutöver
sammanfattas varje match och hela serien med aggregerad statistik.

Poängen är att kunna köra hundratals matcher och sedan undersöka vilka
strategier som verkar löna sig.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agents.roster import make_players
from .legacy import upgrade_record
from .llm import LLMClient
from .rules import MEIER, rank
from .session import LogEntry, Session

#: Åtgärder som är spelarens eget påstående (spelaren säger ett värde).
CLAIM_ACTIONS = ("påstå", "slå", "höja")
#: Åtgärder där spelaren svarar på någon annans påstående.
DECISION_ACTIONS = ("slå", "skicka", "syna")

#: Protokollversion. Höjs när postens form ändras på ett sätt som gör att en
#: äldre post inte längre kan läsas som en ny. Läsaren kräver ``format``, så en
#: post utan fältet avvisas i stället för att tolkas tyst och fel.
PROTOCOL_FORMAT = 2


def _new_agents(role_keys: Iterable[str]):
    """Bygg spelarna för en match, med LLM-klienter för replikerna.

    Varje LLM-spelare får sin egen klient så att tokenräkningen hålls åtskild.
    Axel får ingen klient — han är referensen utan språkmodell.
    """
    players, _tracker = make_players(role_keys, llm_factory=LLMClient)
    return players


def _new_agents_no_llm(role_keys: Iterable[str]):
    """Samma roller som **regelspelare**: ``BasePolicy``, ingen språkmodell.

    Det är utvärderingsläget. Det är inte samma sak som en LLM-spelare som
    misslyckats: en sådan avbryter matchen. Här är regelspelandet ett val, och
    matchen går på millisekunder i stället för minuter.
    """
    players, _tracker = make_players(role_keys)
    return players


def _attach_tracker(agents: list) -> "OpponentTracker":
    """Ge varje läsande spelare samma motståndarmodell. Returnera den."""
    from .opponents import OpponentTracker

    tracker = OpponentTracker()
    for agent in agents:
        params = getattr(agent, "params", None)
        if params is not None and params.reading > 0.0:
            agent.tracker = tracker
    return tracker


def _elimination_order(log: list[LogEntry]) -> list[str]:
    """Ordningen spelare slogs ut, härledd ur livsraderna."""
    order: list[str] = []
    seen: set[str] = set()
    for entry in log:
        if entry.kind == "life" and (entry.lives_left or 0) <= 0:
            if entry.player_name not in seen:
                order.append(entry.player_name)
                seen.add(entry.player_name)
    return order


def _player_stats(log: list[LogEntry], names: list[str]) -> dict[str, dict[str, Any]]:
    """Per-spelare-statistik för en enskild match, räknad ur loggen."""
    stats: dict[str, dict[str, Any]] = {
        name: {
            "claims": 0,          # egna påståenden (påstående/slå/höja)
            "unseen": 0,        # egna påståenden efter ett slag utan att titta (såg inte tärningarna)
            "bluffs": 0,        # egna påståenden där spelaren tittat och inte sa sanningen
            "truths": 0,        # egna påståenden där spelaren tittat och sa sanningen
            "decisions": 0,     # svar på andras påståenden
            "raises": 0,        # "slå" (valde att slå i stället för att syna/skicka)
            "passes": 0,        # "skicka"
            "calls": 0,         # "syna"
            "calls_won": 0,     # syn där motståndaren förlorade
            "calls_lost": 0,    # syn där spelaren själv förlorade
            "lives_lost": 0,
            "eliminated": False,
        }
        for name in names
    }
    for entry in log:
        name = entry.player_name
        if name not in stats:
            continue
        s = stats[name]
        if entry.kind == "life":
            s["lives_lost"] += entry.lives_lost
            if (entry.lives_left or 0) <= 0:
                s["eliminated"] = True
            continue
        if entry.kind != "action":
            continue
        if entry.action in CLAIM_ACTIONS:
            s["claims"] += 1
            # Den som valt bort titten gjorde inget medvetet löfte – räkna inte som bluff.
            if entry.unseen:
                s["unseen"] += 1
            elif entry.truth:
                s["truths"] += 1
            else:
                s["bluffs"] += 1
        if entry.action in DECISION_ACTIONS:
            s["decisions"] += 1
            if entry.action == "slå":
                s["raises"] += 1
            elif entry.action == "skicka":
                s["passes"] += 1
            elif entry.action == "syna":
                s["calls"] += 1
                if entry.caller_loses:
                    s["calls_lost"] += 1
                else:
                    s["calls_won"] += 1
    return stats


@dataclass
class GameRecord:
    """Ett strukturerat protokoll för en spelad match.

    ``players`` bär varje spelares fyra förmågor (``params``), så att en serie
    kan kopplas till den uppsättning som spelade. ``lives_per_player`` anger
    startvillkoret, eftersom ``lives`` bara är vad som återstår vid slutet.
    """

    game: int
    provider: str
    model: str
    players: list[dict[str, Any]]
    order: list[str]
    starter: str
    winner: str
    winner_role: str
    rounds: int
    lives: dict[str, int]
    elimination_order: list[str]
    events: list[dict[str, Any]]
    player_stats: dict[str, dict[str, Any]]
    usage: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    lives_per_player: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": PROTOCOL_FORMAT,
            "game": self.game,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "provider": self.provider,
            "model": self.model,
            "players": self.players,
            "order": self.order,
            "starter": self.starter,
            "winner": self.winner,
            "winner_role": self.winner_role,
            "rounds": self.rounds,
            "lives": self.lives,
            "lives_per_player": self.lives_per_player,
            "elimination_order": self.elimination_order,
            "player_stats": self.player_stats,
            "usage": self.usage,
            "events": self.events,
        }


def play_match(
    role_keys: list[str],
    *,
    game: int = 1,
    lives: int = 3,
    with_llm: bool = True,
    on_progress: "callable[[int, int], None] | None" = None,
) -> GameRecord:
    """Spela en hel match mellan rollerna och returnera protokollet.

    ``with_llm`` styr om spelarna får en LLM-klient för replikerna. Draget ägs
    ändå av policyn, så med ``with_llm=False`` blir matchen mekanisk och går på
    millisekunder — det är läget för utvärdering och statistik. En profil med
    ``unpredictability`` över noll varierar sig ändå.

    ``on_progress(runda, kvar)`` anropas när en ny runda börjar. En match tar
    minuter, så utan den står en statusrad still utan att något är fel.

    Antalet spelare är fritt: ``role_keys`` får innehålla två eller fler roller.
    """
    build = _new_agents if with_llm else _new_agents_no_llm
    agents = build(role_keys)
    tracker = _attach_tracker(agents)
    session = Session.new(agents, lives=lives)
    session.tracker = tracker
    if on_progress is not None:
        on_progress(session.round, len(session._active_indices()))
    session.play_to_end(on_round=on_progress)

    names = [a.name for a in agents]
    remaining = {session.name_of(i): session.lives[i] for i in range(len(agents))}
    alive = [n for n in names if remaining[n] > 0]
    winner = alive[0] if len(alive) == 1 else max(names, key=lambda n: remaining[n])
    winner_role = next(a.role.key for a in agents if a.name == winner)

    # Första spelaren med en LLM-klient anger provider/model (Axel har ingen).
    cfg = next(
        (getattr(a.llm, "config", None) for a in agents if getattr(a, "llm", None) is not None),
        None,
    )
    provider = getattr(cfg, "provider", "none")
    model = getattr(cfg, "model", "none")
    return GameRecord(
        game=game,
        provider=provider,
        model=model,
        players=[
            _player_entry(i, agents[i], lives) for i in range(len(agents))
        ],
        order=[session.name_of(i) for i in session.order],
        starter=session.name_of(session.order[0]),
        winner=winner,
        winner_role=winner_role,
        rounds=session.round,
        lives=remaining,
        elimination_order=_elimination_order(session.log),
        events=[e.to_dict() for e in session.log],
        player_stats=_player_stats(session.log, names),
        usage=_match_usage(agents),
        lives_per_player=lives,
        finished_at=time.time(),
    )


def params_dict(agent: Any) -> dict[str, float] | None:
    """Agentens fyra förmågor som tal, eller ``None`` för en agent utan profil.

    Detta är postens viktigaste fält för efteranalys: utan det går det inte att
    säga vilken uppsättning som spelade, och då kan två serier inte jämföras.
    """
    params = getattr(agent, "params", None)
    if params is None:
        return None
    return {
        "caution": round(params.caution, 3),
        "statistics": round(params.statistics, 3),
        "unpredictability": round(params.unpredictability, 3),
        "reading": round(params.reading, 3),
    }


def _player_entry(index: int, agent: Any, lives: int) -> dict[str, Any]:
    """En spelares rad i protokollet: namn, roll, förmågor och spelartyp.

    ``uses_llm`` skiljer en LLM-spelare från en regelspelare, så att en serie
    som blandar dem (Axel är alltid regelspelare) går att dela upp i analysen.
    """
    role = getattr(agent, "role", None)
    client = getattr(agent, "llm", None)
    return {
        "index": index,
        "role": getattr(role, "key", None),
        "name": getattr(agent, "name", None),
        "uses_llm": client is not None,
        "model": getattr(getattr(client, "config", None), "model", None),
        "style": getattr(role, "style", None),
        "params": params_dict(agent),
        "lives_at_start": lives,
    }


def _match_usage(agents: list) -> dict[str, Any]:
    """Summera LLM-förbrukningen för alla agenter i en match.

    Varje LLM-spelare har sin egen klient, så en matchs total är summan över dem.
    ``by_role`` visar hur mycket varje roll drog, vilket avslöjar om en
    spelare (t.ex. en som resonerar mer) är dyrare än de andra. Axel saknar
    klient och bidrar med noll.
    """
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    calls = 0
    by_role: dict[str, dict[str, int]] = {}
    models: dict[str, int] = {}
    for agent in agents:
        client = getattr(agent, "llm", None)
        usage = getattr(client, "total_usage", None) or {}
        calls += getattr(client, "calls", 0)
        for key in total:
            total[key] += int(usage.get(key, 0))
        for model, n in (getattr(client, "model_calls", None) or {}).items():
            models[model] = models.get(model, 0) + n
        by_role[agent.role.key] = {
            "calls": getattr(client, "calls", 0),
            **{k: int(usage.get(k, 0)) for k in total},
        }
    return {"total": total, "calls": calls, "by_role": by_role, "models": models}


@dataclass
class FailedMatch:
    """En match som inte kunde spelas klart.

    Den sparas i stället för att kastas vidare, så att resten av serien kan
    fortsätta. ``error`` är felet i klartext; ``kind`` skiljer på ett LLM-fel
    (modellen svarade inte) och ett oväntat fel (en bugg).
    """

    game: int
    error: str
    kind: str = "llm"
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "failed": True,
            "kind": self.kind,
            "error": self.error,
            "started_at": self.started_at,
        }


def _is_llm_error(exc: BaseException) -> bool:
    from .llm import LLMError

    return isinstance(exc, LLMError)


def run_matches(
    role_keys: list[str],
    count: int,
    *,
    lives: int = 3,
    workers: int = 1,
    with_llm: bool = True,
    progress: "callable[[int, int], None] | None" = None,
    on_match_progress: "callable[[int, int, int], None] | None" = None,
) -> Iterator[GameRecord | FailedMatch]:
    """Spela ``count`` matcher och ge protokollen efter hand.

    Med ``workers`` > 1 spelas flera matcher samtidigt i trådar. Varje match har
    sina egna agenter och sin egen LLM-klient, så trådarna delar ingen status.
    Protokollen ges i den ordning matcherna blir klara.

    En match som kastar ett fel avbryter **inte** serien. Den lämnas i stället
    som en :class:`FailedMatch`, så att de matcher som redan spelats och de som
    återstår behåller sitt värde.

    ``with_llm=False`` stänger av LLM-anropen helt (bara mekaniska repliker).
    Draget ägs ändå av policyn, så resultatet blir detsamma — men en serie går
    från minuter till millisekunder. Det är läget för utvärdering.

    ``on_match_progress(match, runda, kvar)`` anropas när en match byter runda.
    Statusraden kan då visa vad som händer medan matchen spelas.
    """

    def _play(i: int) -> GameRecord | FailedMatch:
        kwargs = {}
        if on_match_progress is not None:
            # on_progress skickas bara när någon lyssnar, så att play_match kan
            # bytas ut i tester utan att känna till kroken.
            kwargs["on_progress"] = (
                lambda round_no, alive, _i=i: on_match_progress(_i + 1, round_no, alive)
            )

        try:
            return play_match(
                role_keys, game=i + 1, lives=lives, with_llm=with_llm, **kwargs
            )
        except Exception as exc:  # noqa: BLE001 - en match får aldrig fälla serien
            return FailedMatch(
                game=i + 1,
                error=f"{type(exc).__name__}: {exc}",
                kind="llm" if _is_llm_error(exc) else "oväntat",
            )

    if workers <= 1:
        for i in range(count):
            if progress is not None:
                progress(i + 1, count)
            yield _play(i)
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_play, i): i for i in range(count)}
        for finished, fut in enumerate(as_completed(futures), start=1):
            if progress is not None:
                progress(finished, count)
            yield fut.result()


def write_jsonl(records: Iterable[GameRecord | FailedMatch], path: str | Path) -> int:
    """Skriv protokollen som en JSON-rad per match. Returnerar antalet rader.

    Bortfall skrivs också, med ``failed: true``, så att en seriefil alltid
    återspeglar hur många matcher som faktiskt försöktes.
    """
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Läs tillbaka en JSONL-fil med matchprotokoll.

    Filen läses som den är, men äldre nyckelnamn översätts vid inläsning, så
    att en logg från före namnbytet går att läsa som en ny. Filerna skrivs
    aldrig om: de är historik.
    """
    records: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(upgrade_record(json.loads(line)))
    return records


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _failed_reasons(failed: list[dict[str, Any]]) -> dict[str, int]:
    """Räkna bortfallen per orsak, så ett återkommande fel syns i sammanfattningen."""
    reasons: dict[str, int] = {}
    for rec in failed:
        key = rec.get("kind") or "okänt"
        reasons[key] = reasons.get(key, 0) + 1
    return reasons


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregera en serie matcher till statistik per roll och totalt.

    Fokus ligger på mått som kan belysa strategier: vinstfrekvens, hur ofta man
    bluffar, hur aggressivt man höjer, hur ofta man synar och hur ofta synen
    lyckas.

    Bortfall (``failed: true``) räknas **inte** som spelade matcher. De
    rapporteras separat, eftersom de inte är slumpmässiga: en modell som svarar
    503 faller bort oftare just när den pressas, och då skulle en tyst
    bortskrivning försköna statistiken.
    """
    played = [rec for rec in records if not rec.get("failed")]
    failed = [rec for rec in records if rec.get("failed")]
    per_role: dict[str, dict[str, Any]] = {}
    role_params: dict[str, set[tuple]] = {}
    total_games = len(played)
    total_rounds = 0
    winner_counts: dict[str, int] = {}
    starter_wins = 0
    call_outcomes = {"caller_wins": 0, "caller_loses": 0}
    token_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    token_calls = 0
    model_calls: dict[str, int] = {}
    lives_per_player: set[int] = set()

    for rec in played:
        total_rounds += rec.get("rounds", 0)
        winner_counts[rec["winner_role"]] = winner_counts.get(rec["winner_role"], 0) + 1
        if rec.get("starter") == rec.get("winner"):
            starter_wins += 1
        if rec.get("lives_per_player"):
            lives_per_player.add(int(rec["lives_per_player"]))

        usage = rec.get("usage") or {}
        for key in token_totals:
            token_totals[key] += int((usage.get("total") or {}).get(key, 0))
        token_calls += int(usage.get("calls", 0))
        for model, n in (usage.get("models") or {}).items():
            model_calls[model] = model_calls.get(model, 0) + int(n)

        for p in rec["players"]:
            bucket = per_role.setdefault(
                p["role"],
                {
                    "name": p["name"],
                    "games": 0,
                    "wins": 0,
                    "eliminated": 0,
                    "lives_lost": 0,
                    "claims": 0,
                    "unseen": 0,
                    "bluffs": 0,
                    "truths": 0,
                    "decisions": 0,
                    "raises": 0,
                    "passes": 0,
                    "calls": 0,
                    "calls_won": 0,
                    "calls_lost": 0,
                },
            )
            bucket["games"] += 1
            params = p.get("params")
            if params:
                role_params.setdefault(p["role"], set()).add(
                    tuple(sorted((k, round(float(v), 3)) for k, v in params.items()))
                )
                bucket.setdefault("params", params)
                bucket.setdefault("uses_llm", p.get("uses_llm"))

        for name, s in rec["player_stats"].items():
            role = next(p["role"] for p in rec["players"] if p["name"] == name)
            bucket = per_role[role]
            bucket["wins"] += 1 if name == rec["winner"] else 0
            bucket["eliminated"] += 1 if s["eliminated"] else 0
            bucket["lives_lost"] += s["lives_lost"]
            for key in (
                "claims",
                "unseen",
                "bluffs",
                "truths",
                "decisions",
                "raises",
                "passes",
                "calls",
                "calls_won",
                "calls_lost",
            ):
                bucket[key] += s[key]

        for event in rec["events"]:
            if event.get("action") == "syna":
                if event.get("caller_loses"):
                    call_outcomes["caller_loses"] += 1
                else:
                    call_outcomes["caller_wins"] += 1

    for b in per_role.values():
        games = b["games"] or 1
        b["win_rate"] = _rate(b["wins"], b["games"])
        b["elimination_rate"] = _rate(b["eliminated"], b["games"])
        b["avg_lives_lost"] = round(b["lives_lost"] / games, 3)
        b["bluff_rate"] = _rate(b["bluffs"], b["claims"])
        b["unseen_rate"] = _rate(b["unseen"], b["claims"])
        b["raise_rate"] = _rate(b["raises"], b["decisions"])
        b["pass_rate"] = _rate(b["passes"], b["decisions"])
        b["call_rate"] = _rate(b["calls"], b["decisions"])
        b["call_success_rate"] = _rate(b["calls_won"], b["calls"])

    return {
        "games": total_games,
        "attempted": len(records),
        "failed": {
            "count": len(failed),
            "rate": _rate(len(failed), len(records)),
            "games": [rec.get("game") for rec in failed],
            "reasons": _failed_reasons(failed),
        },
        "avg_rounds": round(total_rounds / total_games, 3) if total_games else 0.0,
        "winner_counts": winner_counts,
        "starter_win_rate": _rate(starter_wins, total_games),
        "call_outcomes": call_outcomes,
        "roles": per_role,
        "tactics": _tactics(played),
        "tactics_by_outcome": _tactics_by_outcome(played),
        "abilities": _abilities(per_role),
        "setup": _setup(per_role, role_params, lives_per_player, total_games),
        "tokens": {
            "total": token_totals,
            "calls": token_calls,
            "per_game": {
                key: round(value / total_games, 1) if total_games else 0.0
                for key, value in token_totals.items()
            },
            "calls_per_game": round(token_calls / total_games, 1) if total_games else 0.0,
            # Vilka modeller som faktiskt svarade. Reservmodellerna kan göra en
            # serie blandad, och då ska det gå att se utan att gräva i loggen.
            "models": model_calls,
        },
    }


#: Förmågorna som seriesammanställningen grupperar på.
ABILITY_KEYS = ("caution", "statistics", "unpredictability", "reading")


def _steps(higher: int | None, lower: int | None) -> int | None:
    """Hur många steg ``higher`` ligger över ``lower`` i ordningen.

    Ordningen är en stege, inte tal: ``rules.rank`` ger 0 för Meier och 20 för
    31. Skillnaden i rang är därför ett mått på hur stort ett kliv är, oavsett
    vilka tärningar som visades.
    """
    if higher is None or lower is None:
        return None
    try:
        return rank(lower) - rank(higher)
    except ValueError:
        return None


def _new_tactics() -> dict[str, Any]:
    """Räknare för en spelares spelsätt."""
    return {
        "claim_rows": 0,
        "raise_rows": 0,
        "raise_steps_total": 0,
        "raise_steps_min": 0,
        "bluff_rows": 0,
        "bluff_margin_total": 0,
        "understate_rows": 0,
        "understate_margin_total": 0,
        "meier_claims": 0,
        "call_rows": 0,
        "call_rank_total": 0,
        "call_correct": 0,
        "bluffs_called": 0,
        "claims_upheld": 0,
    }


def _was_lie(event: dict[str, Any]) -> bool:
    """Var påståendet i en synrad en lögn?

    Räknas ur budet och tärningarna, inte ur ``truth``: på en synrad är
    ``truth`` alltid False, eftersom den som synar inte påstår något.
    """
    claim = event.get("accepted_claim") or event.get("claim")
    shown = event.get("shown")
    if claim is None or shown is None:
        return False
    return claim != shown


def _collect_tactics(
    records: list[dict[str, Any]], key_of
) -> dict[str, dict[str, Any]]:
    """Räkna spelsättet, grupperat på ``key_of(record, role)``."""
    buckets: dict[str, dict[str, Any]] = {}
    for rec in records:
        if rec.get("failed"):
            continue
        by_name = {p.get("name"): p.get("role") for p in rec.get("players", [])}
        for event in rec.get("events", []):
            role = by_name.get(event.get("player_name"))
            if role is None:
                continue
            acc = buckets.setdefault(key_of(rec, role), _new_tactics())
            action = event.get("action")
            claim = event.get("claim")
            # En rad utan bud är ingen påståenderad. Tärningsrader (kind "roll")
            # bär utfallet men inget bud, och ska inte räknas som ett påstående.
            if action in CLAIM_ACTIONS and claim is not None:
                acc["claim_rows"] += 1
                if claim == MEIER:
                    acc["meier_claims"] += 1
                steps = _steps(claim, event.get("accepted_claim"))
                if steps is not None:
                    acc["raise_rows"] += 1
                    acc["raise_steps_total"] += steps
                    if steps == 1:
                        acc["raise_steps_min"] += 1
                if event.get("unseen"):
                    continue
                if event.get("truth") is False:
                    margin = _steps(claim, event.get("shown"))
                    if margin is not None:
                        acc["bluff_rows"] += 1
                        acc["bluff_margin_total"] += margin
                elif event.get("truth") and claim != event.get("shown"):
                    margin = _steps(event.get("shown"), claim)
                    if margin is not None:
                        acc["understate_rows"] += 1
                        acc["understate_margin_total"] += margin
            elif action == "syna":
                acc["call_rows"] += 1
                try:
                    acc["call_rank_total"] += rank(event.get("accepted_claim"))
                except (TypeError, ValueError):
                    pass
                # Synraden sätter ``truth`` till False med flit: den som synar
                # påstår inget. Om påståendet var en lögn avgörs av budet mot
                # tärningarna, och det är samma villkor som reglerna dömer på.
                if _was_lie(event):
                    acc["call_correct"] += 1

        # En synad bluff avgörs av synraden: vem höll påståendet, och var det
        # sant? Det ger hur ofta ett påstående stod sig när det synades.
        for event in rec.get("events", []):
            if event.get("action") != "syna":
                continue
            holder_role = by_name.get(event.get("holder_name"))
            if holder_role is None:
                continue
            acc = buckets.setdefault(key_of(rec, holder_role), _new_tactics())
            if _was_lie(event):
                acc["bluffs_called"] += 1
            else:
                acc["claims_upheld"] += 1

    return {key: _tactic_rates(acc) for key, acc in buckets.items()}


def _tactic_rates(acc: dict[str, Any]) -> dict[str, Any]:
    """Vänd räknarna till andelar och snitt."""
    claims = acc["claim_rows"]
    raise_rows = acc["raise_rows"]
    call_rows = acc["call_rows"]
    challenged = acc["bluffs_called"] + acc["claims_upheld"]
    return {
        "claims": claims,
        "raises": raise_rows,
        "bluffs": acc["bluff_rows"],
        "raise_steps": round(acc["raise_steps_total"] / (raise_rows or 1), 2),
        "raise_min_share": _rate(acc["raise_steps_min"], raise_rows),
        "bluff_margin": round(acc["bluff_margin_total"] / (acc["bluff_rows"] or 1), 2),
        "understate_share": _rate(acc["understate_rows"], claims),
        "understate_margin": round(
            acc["understate_margin_total"] / (acc["understate_rows"] or 1), 2
        ),
        "meier_share": _rate(acc["meier_claims"], claims),
        "calls": call_rows,
        # Synar per påstående. Antalet synar i sig går inte att jämföra mellan
        # vinnare och förlorare: den som överlever längre spelar fler rundor och
        # hinner därför syna fler gånger. Kvoten normaliserar för det.
        "calls_per_claim": round(call_rows / (claims or 1), 2),
        "call_height": round(acc["call_rank_total"] / (call_rows or 1), 2),
        "call_precision": _rate(acc["call_correct"], call_rows),
        "claims_challenged": challenged,
        "lies_revealed": acc["bluffs_called"],
        "claims_upheld": _rate(acc["claims_upheld"], challenged),
    }


def _tactics(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Spelsätt per roll, mätt ur händelserna i varje match.

    Förmågorna (``params``) säger hur en spelare är tänkt att spela. Det här
    mäter hur spelet faktiskt blev, vilket är det som går att koppla till
    vinster: hur stora kliv spelaren tar, hur djärva bluffarna är, om den säger
    svagare än tärningarna, hur högt uppe den synar, och hur ofta synen träffar.

    Alla mått räknas ur offentliga händelser i protokollet. Inget extra behöver
    loggas.
    """
    return _collect_tactics(records, lambda rec, role: role)


def _tactics_by_outcome(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Spelsätt uppdelat på om spelaren vann matchen eller inte.

    Det här är den direkta jämförelsen mellan vinnande och förlorande spel:
    tar vinnare större kliv? Synar de högre? Bluffar de försiktigare? Skillnaden
    är en ledtråd, inte ett bevis — samma spelare bidrar till båda grupperna,
    och tur avgör en enskild match. Med många matcher jämnas slumpen ut.
    """
    return _collect_tactics(
        records,
        lambda rec, role: "vann" if _role_won(rec, role) else "förlorade",
    )


def _role_won(rec: dict[str, Any], role: str) -> bool:
    """Vann rollen matchen?"""
    return rec.get("winner_role") == role


def _setup(
    per_role: dict[str, dict[str, Any]],
    role_params: dict[str, set[tuple]],
    lives_per_player: set[int],
    total_games: int,
) -> dict[str, Any]:
    """Uppsättningen som spelade: roller, förmågor och startvillkor.

    ``stable`` är falskt när samma roll spelat med olika förmågor i serien. Då
    går rollens siffror inte att läsa som en egenskap hos just den profilen, och
    det måste stå klart i underlaget i stället för att upptäckas i efterhand.
    """
    roles = {
        role: {
            "name": b["name"],
            "params": b.get("params"),
            "uses_llm": b.get("uses_llm"),
            "params_variants": len(role_params.get(role, ())),
        }
        for role, b in per_role.items()
    }
    return {
        "games": total_games,
        "roles": sorted(per_role),
        "player_count": len(per_role),
        "lives_per_player": sorted(lives_per_player),
        "stable": all(v["params_variants"] <= 1 for v in roles.values()),
        "role_detail": roles,
    }


def _abilities(per_role: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Vinst och beteende grupperat per förmåga, inte per spelare.

    Detta är svaret på frågan serien finns för: vilka förmågor lönar sig. Varje
    förmåga delas i nivåer (samma ord som spelarbeskrivningen använder), och
    varje nivå får vinstfrekvens, snitt liv kvar och beteendemått. Med få
    matcher per nivå är talen brusiga, därför redovisas ``games`` alltid.
    """
    from .agents.personality import level_name

    out: dict[str, Any] = {}
    for key in ABILITY_KEYS:
        buckets: dict[str, dict[str, Any]] = {}
        for b in per_role.values():
            params = b.get("params")
            if not params or key not in params:
                continue
            level = level_name(float(params[key]))
            acc = buckets.setdefault(
                level,
                {
                    "players": [],
                    "games": 0,
                    "wins": 0,
                    "lives_lost": 0,
                    "claims": 0,
                    "bluffs": 0,
                    "decisions": 0,
                    "calls": 0,
                    "calls_won": 0,
                    "unseen": 0,
                },
            )
            if b["name"] not in acc["players"]:
                acc["players"].append(b["name"])
            for field_name in (
                "games",
                "wins",
                "lives_lost",
                "claims",
                "bluffs",
                "decisions",
                "calls",
                "calls_won",
                "unseen",
            ):
                acc[field_name] += b[field_name]
        levels = {}
        for level, acc in buckets.items():
            levels[level] = {
                "players": acc["players"],
                "games": acc["games"],
                "win_rate": _rate(acc["wins"], acc["games"]),
                "avg_lives_lost": round(acc["lives_lost"] / (acc["games"] or 1), 3),
                "bluff_rate": _rate(acc["bluffs"], acc["claims"]),
                "call_rate": _rate(acc["calls"], acc["decisions"]),
                "call_success_rate": _rate(acc["calls_won"], acc["calls"]),
                "unseen_rate": _rate(acc["unseen"], acc["claims"]),
            }
        if levels:
            out[key] = levels
    return out
