"""Kommandoradsgränssnitt för Mejeri-agenterna.

Exempel:
    python -m mejeri.cli announce 2 5 --role rackar
    python -m mejeri.cli decide 43 --role trygg
    python -m mejeri.cli play rackar kalkyl trygg
    python -m mejeri.cli session
"""

from __future__ import annotations

import argparse
import sys

from . import rules
from .agents.player import ROLES, get_role, MejeriPlayerAgent
from .agents.referee import RefereeAgent
from .game import Game
from .session import Session


def _cmd_announce(args: argparse.Namespace) -> int:
    agent = MejeriPlayerAgent(role=get_role(args.role))
    ann = agent.announce((args.die1, args.die2), previous_bid=args.previous_bid)
    print(f"Roll:        {agent.name}")
    print(f"Tärningarna: {rules.read_dice(args.die1, args.die2)} ({args.die1} och {args.die2})")
    if args.previous_bid is not None:
        print(f"Före bud:    {rules.name(args.previous_bid)}")
    print(f"Spelaren säger: {rules.name(ann.bid)}")
    print(f"Sanning?     {'ja' if ann.truth else 'nej (bluff)'}")
    if ann.line:
        print(f"Replik:      “{ann.line}”")
    if ann.reasoning:
        print(f"Motivering:  {ann.reasoning}")
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    agent = MejeriPlayerAgent(role=get_role(args.role))
    decision = agent.decide(args.bid, lives=args.lives)
    print(f"Roll:      {agent.name}")
    print(f"Motståndarens bud: {rules.name(args.bid)}")
    print(f"Spelaren väljer:   {decision.action}")
    if decision.bid is not None:
        print(f"Nytt bud:  {rules.name(decision.bid)}")
    if decision.line:
        print(f"Replik:    “{decision.line}”")
    if decision.reasoning:
        print(f"Motivering: {decision.reasoning}")
    return 0


def _cmd_play(args: argparse.Namespace) -> int:
    agents = [MejeriPlayerAgent(role=get_role(key)) for key in args.roles]
    game = Game.new(agents, seed=args.seed)
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
            f"{current} måste höja – bägaren har gått ett helt varv. "
            f"Aktuellt bud: {pending.get('bid_name')}."
        )
    return (
        f"{current} ska svara på budet {pending.get('bid_name')} "
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
    verdict = entry.referee
    if verdict.ok:
        print("  Domaren: OK")
    else:
        print(f"  Domaren: INVÄNDNING – {' '.join(verdict.objections)}")


def _cmd_session(args: argparse.Namespace) -> int:
    roles = args.roles or list(ROLES)
    players = [MejeriPlayerAgent(role=get_role(key)) for key in roles]
    referee = RefereeAgent()
    session = Session.new(players, referee, seed=args.seed)

    print("Spelordning: " + " → ".join(players[i].name for i in session.order))
    print("Tryck Enter (OK) för nästa steg. Skriv 'k' för att köra fram till en syn.")
    print("Skriv 'q' för att avsluta.\n")

    try:
        while not session.finished and session.step_kind:
            state = session.to_dict()
            print(f"Runda {session.round}. {_describe_step(state)}")
            answer = input("  [Enter = OK, k = kör till syn, q = avsluta] ").strip().lower()
            if answer == "q":
                break
            if answer == "k":
                for entry in session.run_to_call():
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
            f"\nSyn! Tärningarna visade {rules.name(result.shown)} mot budet "
            f"{rules.name(result.bid)}. {result.loser} förlorar {result.lives} liv."
        )
    print("\nLogg:")
    for e in session.log:
        verdict = "OK" if e.referee.ok else "invändning"
        print(
            f"  R{e.round}: {e.player_name} [{e.action}] {rules.name(e.bid)} "
            f"– domare: {verdict}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mejeri", description="Mejeri med LLM-agenter")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ann = sub.add_parser("announce", help="Givet ett tärningsslag: spelarens svar")
    p_ann.add_argument("die1", type=int, choices=range(1, 7))
    p_ann.add_argument("die2", type=int, choices=range(1, 7))
    p_ann.add_argument("--role", default="kalkyl", choices=list(ROLES))
    p_ann.add_argument("--previous-bid", type=int, default=None)
    p_ann.set_defaults(func=_cmd_announce)

    p_dec = sub.add_parser("decide", help="Spelaren möter ett bud")
    p_dec.add_argument("bid", type=int)
    p_dec.add_argument("--role", default="kalkyl", choices=list(ROLES))
    p_dec.add_argument("--lives", type=int, default=3)
    p_dec.set_defaults(func=_cmd_decide)

    p_play = sub.add_parser("play", help="Spela ett helt spel med flera agenter")
    p_play.add_argument("roles", nargs="+", choices=list(ROLES))
    p_play.add_argument("--seed", type=int, default=None)
    p_play.set_defaults(func=_cmd_play)

    p_sess = sub.add_parser(
        "session", help="Interaktiv session: OK-grind på tärningsslaget, domare och logg"
    )
    p_sess.add_argument("roles", nargs="*", choices=list(ROLES))
    p_sess.add_argument("--seed", type=int, default=None)
    p_sess.set_defaults(func=_cmd_session)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
