"""Kommandoradsgränssnitt för Majer-agenterna.

Exempel:
    python -m majer.cli announce 2 5 --role rackar
    python -m majer.cli decide 43 --role trygg
    python -m majer.cli play rackar kalkyl trygg
"""

from __future__ import annotations

import argparse
import sys

from . import rules
from .agents.player import ROLES, get_role, MajerPlayerAgent
from .game import Game


def _cmd_announce(args: argparse.Namespace) -> int:
    agent = MajerPlayerAgent(role=get_role(args.role))
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
    agent = MajerPlayerAgent(role=get_role(args.role))
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
    agents = [MajerPlayerAgent(role=get_role(key)) for key in args.roles]
    game = Game.new(agents, seed=args.seed)
    game.on_log = lambda line: print(line, flush=True)
    winner = game.play()
    print(f"\nVinnare: {winner.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="majer", description="Majer med LLM-agenter")
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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
