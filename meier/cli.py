"""Kommandoradsgränssnitt för Meier-agenterna.

Exempel:
    python -m meier.cli announce 2 5 --role rackar
    python -m meier.cli decide 43 --role trygg
    python -m meier.cli play rackar kalkyl trygg
    python -m meier.cli session
"""

from __future__ import annotations

import argparse
import json
import sys

from . import rules
from .agents.roster import ROSTER, get_profile, make_player, make_players, role_keys
from .game import Game
from .match import read_jsonl, run_matches, summarize, write_jsonl
from .session import Session


def _cmd_announce(args: argparse.Namespace) -> int:
    agent = make_player(args.role)
    ann = agent.announce((args.die1, args.die2), previous_bid=args.previous_bid)
    print(f"Spelare:     {agent.name}")
    print(f"Tärningarna: {rules.read_dice(args.die1, args.die2)} ({args.die1} och {args.die2})")
    if args.previous_bid is not None:
        print(f"Före påstående: {rules.name(args.previous_bid)}")
    print(f"Spelaren säger: {rules.name(ann.bid)}")
    print(f"Sanning?     {'ja' if ann.truth else 'nej (bluff)'}")
    if ann.line:
        print(f"Replik:      “{ann.line}”")
    if ann.reasoning:
        print(f"Motivering:  {ann.reasoning}")
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    agent = make_player(args.role)
    decision = agent.decide(args.bid, lives=args.lives)
    print(f"Spelare:   {agent.name}")
    print(f"Motståndarens påstående: {rules.name(args.bid)}")
    print(f"Spelaren väljer:   {decision.action}")
    if decision.bid is not None:
        print(f"Nytt påstående: {rules.name(decision.bid)}")
    if decision.line:
        print(f"Replik:    “{decision.line}”")
    if decision.reasoning:
        print(f"Motivering: {decision.reasoning}")
    return 0


def _cmd_play(args: argparse.Namespace) -> int:
    agents, _tracker = make_players(args.roles)
    game = Game.new(agents)
    game.on_log = lambda line: print(line, flush=True)
    winner = game.play()
    print(f"\nVinnare: {winner.name}")
    return 0


def _describe_step(state: dict) -> str:
    pending = state.get("pending") or {}
    current = state["current"]["name"]
    kind = state["step_kind"]
    if kind == "roll":
        return (
            f"{current} slår. Tärningsslaget visar {pending.get('shown_name')} "
            f"(tärning {pending['dice'][0]} och {pending['dice'][1]})."
        )
    if kind == "raise":
        return (
            f"{current} slår om – bägaren har gått ett helt varv – och måste höja. "
            f"Aktuellt påstående: {pending.get('bid_name')}."
        )
    return (
        f"{current} ska svara på påståendet {pending.get('bid_name')} "
        f"(sagt av {pending.get('bidder')})."
    )


def _print_entry(entry) -> None:
    action = entry.action
    if action == "syna":
        print(f"  {entry.player_name}: Synar")
    elif action == "skicka":
        print(f"  {entry.player_name}: Skickar vidare {rules.name(entry.bid)}")
    elif action == "slå":
        print(f"  {entry.player_name}: Slår {rules.name(entry.bid)}")
    elif action == "höja":
        print(f"  {entry.player_name}: Höjer {rules.name(entry.bid)}")
    else:
        print(f"  {entry.player_name}: Säger {rules.name(entry.bid)}")


def _cmd_session(args: argparse.Namespace) -> int:
    roles = args.roles or role_keys()
    players, tracker = make_players(roles)
    session = Session.new(players)
    session.tracker = tracker

    print("Spelordning: " + " → ".join(players[i].name for i in session.order))
    print("Tryck Enter (Ett drag) för nästa steg.")
    print("Skriv 'r' för att köra fram till rundans slut, 'k' för att köra till en syn.")
    print("Skriv 'q' för att avsluta.\n")

    try:
        while not session.finished and session.step_kind:
            state = session.to_dict()
            print(f"Runda {session.round}. {_describe_step(state)}")
            answer = input(
                "  [Enter = ett drag, r = till slut på runda, k = till syn, q = avsluta] "
            ).strip().lower()
            if answer == "q":
                break
            if answer == "k":
                for entry in session.run_to_call():
                    _print_entry(entry)
            elif answer == "r":
                for entry in session.run_to_round_end():
                    _print_entry(entry)
            else:
                entry = session.advance()
                if entry is not None:
                    _print_entry(entry)
            print()
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        session.stop()

    if session.result:
        result = session.result
        print(
            f"\nSyn! Tärningarna visade {rules.name(result.shown)} mot påståendet "
            f"{rules.name(result.bid)}. {result.loser} förlorar {result.lives} liv."
        )
    print("\nLogg:")
    for e in session.log:
        if e.kind == "life":
            print(f"  R{e.round}: {e.player_name} förlorar {e.lives_lost} liv ({e.lives_left} kvar)")
        else:
            print(f"  R{e.round}: {e.player_name} [{e.action}] {rules.name(e.bid)}")
    return 0


def _cmd_match(args: argparse.Namespace) -> int:
    roles = args.roles or role_keys()
    out = args.out or "matches.jsonl"

    def progress(done: int, total: int) -> None:
        print(f"  match {done}/{total}", flush=True)

    records = list(
        run_matches(
            roles,
            args.count,
            lives=args.lives,
            workers=args.workers,
            with_llm=not args.no_llm,
            progress=progress if args.verbose else None,
        )
    )
    n = write_jsonl(records, out)
    print(f"\nSpelade {n} matcher. Protokoll: {out}")

    stats = summarize([r.to_dict() for r in records])
    print(f"\nVinnare per roll (av {stats['games']} matcher):")
    for role, b in stats["roles"].items():
        print(
            f"  {b['name']:12} vinst {b['wins']:3}/{b['games']:<3} "
            f"({b['win_rate'] * 100:4.1f}%)  bluff {b['bluff_rate'] * 100:4.1f}%  "
            f"syn {b['call_rate'] * 100:4.1f}% (lyckas {b['call_success_rate'] * 100:4.1f}%)"
        )

    if args.no_llm:
        print("\n(utan LLM-anrop: bara mekaniska repliker, inga tokens förbrukade)")
    else:
        tok = stats["tokens"]
        print(f"\nTokenförbrukning (provider {records[0].provider}, modell {records[0].model}):")
        print(
            f"  per match: {tok['per_game']['total_tokens']:.0f} tokens "
            f"({tok['per_game']['prompt_tokens']:.0f} in, "
            f"{tok['per_game']['completion_tokens']:.0f} ut), "
            f"{tok['calls_per_game']:.0f} LLM-anrop"
        )
        print(f"  hela serien: {tok['total']['total_tokens']} tokens, {tok['calls']} anrop")

    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    stats = summarize(read_jsonl(args.path))
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meier", description="Meier med LLM-agenter")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ann = sub.add_parser("announce", help="Givet ett tärningsslag: spelarens svar")
    p_ann.add_argument("die1", type=int, choices=range(1, 7))
    p_ann.add_argument("die2", type=int, choices=range(1, 7))
    p_ann.add_argument("--role", default="cecilia", choices=role_keys())
    p_ann.add_argument("--previous-bid", type=int, default=None)
    p_ann.set_defaults(func=_cmd_announce)

    p_dec = sub.add_parser("decide", help="Spelaren möter ett påstående")
    p_dec.add_argument("bid", type=int)
    p_dec.add_argument("--role", default="cecilia", choices=role_keys())
    p_dec.add_argument("--lives", type=int, default=3)
    p_dec.set_defaults(func=_cmd_decide)

    p_play = sub.add_parser("play", help="Spela ett helt spel med flera agenter")
    p_play.add_argument("roles", nargs="+", choices=role_keys())
    p_play.set_defaults(func=_cmd_play)

    p_sess = sub.add_parser(
        "session", help="Interaktiv session: OK-grind på tärningsslaget och logg"
    )
    p_sess.add_argument("roles", nargs="*", choices=role_keys())
    p_sess.set_defaults(func=_cmd_session)

    p_match = sub.add_parser(
        "match", help="Spela många matcher och skriv ett JSONL-protokoll för analys"
    )
    p_match.add_argument("roles", nargs="*", choices=role_keys())
    p_match.add_argument("--count", type=int, default=10, help="Antal matcher")
    p_match.add_argument("--out", default="matches.jsonl", help="Utfil (JSONL)")
    p_match.add_argument("--lives", type=int, default=3)
    p_match.add_argument(
        "--workers", type=int, default=1, help="Antal matcher som spelas samtidigt"
    )
    p_match.add_argument(
        "--no-llm",
        action="store_true",
        help="Stäng av LLM-anrop (bara mekaniska repliker). Snabb utvärdering.",
    )
    p_match.add_argument("--verbose", action="store_true")
    p_match.set_defaults(func=_cmd_match)

    p_sum = sub.add_parser("summarize", help="Sammanfatta ett JSONL-protokoll")
    p_sum.add_argument("path")
    p_sum.set_defaults(func=_cmd_summarize)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
