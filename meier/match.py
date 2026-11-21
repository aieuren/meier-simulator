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
from .llm import LLMClient
from .session import LogEntry, Session

#: Åtgärder som är spelarens eget påstående (spelaren säger ett värde).
BID_ACTIONS = ("bud", "slå", "höja")
#: Åtgärder där spelaren svarar på någon annans påstående.
DECISION_ACTIONS = ("slå", "skicka", "syna")


def _new_agents(role_keys: Iterable[str]):
    """Bygg spelarna för en match, med LLM-klienter för replikerna.

    Varje LLM-spelare får sin egen klient så att tokenräkningen hålls åtskild.
    Axel får ingen klient — han är den deterministiska referensen.
    """
    players, _tracker = make_players(role_keys, llm_factory=LLMClient)
    return players


def _new_agents_no_llm(role_keys: Iterable[str]):
    """Samma spelare men utan LLM-klienter: bara mekaniska repliker.

    Draget ägs ändå av policyn, så resultatet blir detsamma — men matchen går
    på millisekunder i stället för minuter. Det är läget för utvärdering.
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
            "bids": 0,          # egna påståenden (bud/slå/höja)
            "blinds": 0,        # egna påståenden efter ett blind slag (såg inte tärningarna)
            "bluffs": 0,        # egna påståenden där spelaren tittat och inte sa sanningen
            "truths": 0,        # egna påståenden där spelaren tittat och sa sanningen
            "decisions": 0,     # svar på andras påståenden
            "raises": 0,        # "slå" (blind höjning)
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
        if entry.action in BID_ACTIONS:
            s["bids"] += 1
            # Ett blind slag är inget medvetet löfte – räkna det inte som bluff.
            if entry.blind:
                s["blinds"] += 1
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
    """Ett strukturerat protokoll för en spelad match."""

    game: int
    seed: int | None
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "seed": self.seed,
            "started_at": self.started_at,
            "provider": self.provider,
            "model": self.model,
            "players": self.players,
            "order": self.order,
            "starter": self.starter,
            "winner": self.winner,
            "winner_role": self.winner_role,
            "rounds": self.rounds,
            "lives": self.lives,
            "elimination_order": self.elimination_order,
            "player_stats": self.player_stats,
            "usage": self.usage,
            "events": self.events,
        }


def play_match(
    role_keys: list[str],
    *,
    game: int = 1,
    seed: int | None = None,
    lives: int = 3,
    with_llm: bool = True,
) -> GameRecord:
    """Spela en hel match mellan rollerna och returnera protokollet.

    ``with_llm`` styr om spelarna får en LLM-klient för replikerna. Draget ägs
    ändå av policyn, så med ``with_llm=False`` blir matchen helt deterministisk
    och går på millisekunder — det är läget för utvärdering och statistik.
    """
    build = _new_agents if with_llm else _new_agents_no_llm
    agents = build(role_keys)
    tracker = _attach_tracker(agents)
    session = Session.new(agents, seed=seed, lives=lives)
    session.tracker = tracker
    session.play_to_end()

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
        seed=seed,
        provider=provider,
        model=model,
        players=[
            {"index": i, "role": agents[i].role.key, "name": agents[i].name}
            for i in range(len(agents))
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
    )


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
    for agent in agents:
        client = getattr(agent, "llm", None)
        usage = getattr(client, "total_usage", None) or {}
        calls += getattr(client, "calls", 0)
        for key in total:
            total[key] += int(usage.get(key, 0))
        by_role[agent.role.key] = {
            "calls": getattr(client, "calls", 0),
            **{k: int(usage.get(k, 0)) for k in total},
        }
    return {"total": total, "calls": calls, "by_role": by_role}


def run_matches(
    role_keys: list[str],
    count: int,
    *,
    base_seed: int | None = None,
    lives: int = 3,
    workers: int = 1,
    with_llm: bool = True,
    progress: "callable[[int, int], None] | None" = None,
) -> Iterator[GameRecord]:
    """Spela ``count`` matcher och ge protokollen efter hand.

    Med ``workers`` > 1 spelas flera matcher samtidigt i trådar. Varje match har
    sina egna agenter och sin egen LLM-klient, så trådarna delar ingen status.
    Protokollen ges i den ordning matcherna blir klara.

    ``with_llm=False`` stänger av LLM-anropen helt (bara mekaniska repliker).
    Draget ägs ändå av policyn, så resultatet blir detsamma — men en serie går
    från minuter till millisekunder. Det är läget för utvärdering.
    """
    if workers <= 1:
        for i in range(count):
            seed = None if base_seed is None else base_seed + i
            if progress is not None:
                progress(i + 1, count)
            yield play_match(
                role_keys, game=i + 1, seed=seed, lives=lives, with_llm=with_llm
            )
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _one(i: int) -> GameRecord:
        seed = None if base_seed is None else base_seed + i
        return play_match(
            role_keys, game=i + 1, seed=seed, lives=lives, with_llm=with_llm
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, i): i for i in range(count)}
        for finished, fut in enumerate(as_completed(futures), start=1):
            if progress is not None:
                progress(finished, count)
            yield fut.result()


def write_jsonl(records: Iterable[GameRecord], path: str | Path) -> int:
    """Skriv protokollen som en JSON-rad per match. Returnerar antalet rader."""
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Läs tillbaka en JSONL-fil med matchprotokoll."""
    records: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregera en serie matcher till statistik per roll och totalt.

    Fokus ligger på mått som kan belysa strategier: vinstfrekvens, hur ofta man
    bluffar, hur aggressivt man höjer, hur ofta man synar och hur ofta synen
    lyckas.
    """
    per_role: dict[str, dict[str, Any]] = {}
    total_games = len(records)
    total_rounds = 0
    winner_counts: dict[str, int] = {}
    starter_wins = 0
    call_outcomes = {"caller_wins": 0, "caller_loses": 0}
    token_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    token_calls = 0

    for rec in records:
        total_rounds += rec.get("rounds", 0)
        winner_counts[rec["winner_role"]] = winner_counts.get(rec["winner_role"], 0) + 1
        if rec.get("starter") == rec.get("winner"):
            starter_wins += 1

        usage = rec.get("usage") or {}
        for key in token_totals:
            token_totals[key] += int((usage.get("total") or {}).get(key, 0))
        token_calls += int(usage.get("calls", 0))

        for p in rec["players"]:
            bucket = per_role.setdefault(
                p["role"],
                {
                    "name": p["name"],
                    "games": 0,
                    "wins": 0,
                    "eliminated": 0,
                    "lives_lost": 0,
                    "bids": 0,
                    "blinds": 0,
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

        for name, s in rec["player_stats"].items():
            role = next(p["role"] for p in rec["players"] if p["name"] == name)
            bucket = per_role[role]
            bucket["wins"] += 1 if name == rec["winner"] else 0
            bucket["eliminated"] += 1 if s["eliminated"] else 0
            bucket["lives_lost"] += s["lives_lost"]
            for key in (
                "bids",
                "blinds",
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
        b["bluff_rate"] = _rate(b["bluffs"], b["bids"])
        b["blind_rate"] = _rate(b["blinds"], b["bids"])
        b["raise_rate"] = _rate(b["raises"], b["decisions"])
        b["pass_rate"] = _rate(b["passes"], b["decisions"])
        b["call_rate"] = _rate(b["calls"], b["decisions"])
        b["call_success_rate"] = _rate(b["calls_won"], b["calls"])

    return {
        "games": total_games,
        "avg_rounds": round(total_rounds / total_games, 3) if total_games else 0.0,
        "winner_counts": winner_counts,
        "starter_win_rate": _rate(starter_wins, total_games),
        "call_outcomes": call_outcomes,
        "roles": per_role,
        "tokens": {
            "total": token_totals,
            "calls": token_calls,
            "per_game": {
                key: round(value / total_games, 1) if total_games else 0.0
                for key, value in token_totals.items()
            },
            "calls_per_game": round(token_calls / total_games, 1) if total_games else 0.0,
        },
    }
