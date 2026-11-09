"""Mejer – LLM-baserade agenter som spelar tärningsspelet Mejer."""

from . import rules
from .agents.player import ROLES, MejerPlayerAgent, get_role

__all__ = ["rules", "ROLES", "MejerPlayerAgent", "get_role"]
__version__ = "1.0.0"
