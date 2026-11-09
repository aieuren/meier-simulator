"""Mejeri – LLM-baserade agenter som spelar tärningsspelet Mejeri."""

from . import rules
from .agents.player import ROLES, MejeriPlayerAgent, get_role

__all__ = ["rules", "ROLES", "MejeriPlayerAgent", "get_role"]
__version__ = "1.0.0"
