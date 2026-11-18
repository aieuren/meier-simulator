"""Meier – LLM-baserade agenter som spelar tärningsspelet Meier."""

from . import rules
from .agents.player import MeierPlayerAgent
from .agents.roster import ROSTER, get_profile, make_player, role_keys

__all__ = [
    "rules",
    "ROSTER",
    "get_profile",
    "make_player",
    "role_keys",
    "MeierPlayerAgent",
]
__version__ = "1.0.0"
