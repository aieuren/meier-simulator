"""Majer – LLM-baserade agenter som spelar tärningsspelet Majer."""

from . import rules
from .agents.player import ROLES, MajerPlayerAgent, get_role

__all__ = ["rules", "ROLES", "MajerPlayerAgent", "get_role"]
__version__ = "1.0.0"
