"""Meier – LLM-baserade agenter som spelar tärningsspelet Meier."""

from . import rules
from .agents.player import ROLES, MeierPlayerAgent, get_role

__all__ = ["rules", "ROLES", "MeierPlayerAgent", "get_role"]
__version__ = "1.0.0"
