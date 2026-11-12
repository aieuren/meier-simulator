"""Batchkörning och statistik för Meier.

Modulen spelar många matcher mellan LLM-baserade agenter och samlar varje
match i ett strukturerat, JSON-serialiserbart protokoll. Protokollet är byggt
för efteranalys: varje åtgärd sparas med spelare, roll, tärningsutfall, bud,
om budet var sant eller en bluff, livsställning och rundnummer. Därutöver
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

from .agents.player import MeierPlayerAgent, get_role
from .llm import LLMClient
from .session import LogEntry, Session

#: Åtgärder som är spelarens eget bud (spelaren säger ett värde).
BID_ACTIONS = ("bud", "slå", "höja")
#: Åtgärder där spelaren svarar på någon annans bud.
DECISION_ACTIONS = ("slå", "skicka", "syna")


def _new_agents(role_keys: Iterable[str]) -> list[MeierPlayerAgent]:
    return [MeierPlayerAgent(role=get_role(key), llm=LLMClient()) for key in role_keys]


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
            "bids": 0,          # egna bud (bud/slå/höja)
            "blinds": 0,        # egna bud efter ett blind slag (såg inte tärningarna)
            "bluffs": 0,        # egna bud där spelaren tittat och inte sa sanningen
            "truths": 0,        # egna bud där spelaren tittat och sa sanningen
            "decisions": 0,     # svar på andras bud
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
            "events": self.events,
        }


def play_match(
    role_keys: list[str],
    *,
    game: int = 1,
    seed: int | None = None,
    lives: int = 3,
) -> GameRecord:
    """Spela en hel match mellan rollerna och returnera protokollet."""
    agents = _new_agents(role_keys)
    session = Session.new(agents, seed=seed, lives=lives)
    session.play_to_end()

    names = [a.name for a in agents]
    remaining = {session.name_of(i): session.lives[i] for i in range(len(agents))}
    alive = [n for n in names if remaining[n] > 0]
    winner = alive[0] if len(alive) == 1 else max(names, key=lambda n: remaining[n])
    winner_role = next(a.role.key for a in agents if a.name == winner)

    cfg = getattr(agents[0].llm, "config", None)
    provider = getattr(cfg, "provider", "unknown")
    model = getattr(cfg, "model", "unknown")
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
    )


def run_matches(
    role_keys: list[str],
    count: int,
    *,
    base_seed: int | None = None,
    lives: int = 3,
    workers: int = 1,
    progress: "callable[[int, int], None] | None" = None,
) -> Iterator[GameRecord]:
    """Spela ``count`` matcher och ge protokollen efter hand.

    Med ``workers`` > 1 spelas flera matcher samtidigt i trådar. Varje match har
    sina egna agenter och sin egen LLM-klient, så trådarna delar ingen status.
    Protokollen ges i den ordning matcherna blir klara.
    """
    if workers <= 1:
        for i in range(count):
            seed = None if base_seed is None else base_seed + i
            if progress is not None:
                progress(i + 1, count)
            yield play_match(role_keys, game=i + 1, seed=seed, lives=lives)
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _one(i: int) -> GameRecord:
        seed = None if base_seed is None else base_seed + i
        return play_match(role_keys, game=i + 1, seed=seed, lives=lives)

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

    for rec in records:
        total_rounds += rec.get("rounds", 0)
        winner_counts[rec["winner_role"]] = winner_counts.get(rec["winner_role"], 0) + 1
        if rec.get("starter") == rec.get("winner"):
            starter_wins += 1

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
    }
