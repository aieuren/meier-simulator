"""Agenter för Majer."""

from .base import Agent, Role
from .player import ROLES, ActionDecision, Announcement, MajerPlayerAgent, get_role
from .referee import REFEREE_ROLE, RefereeAgent, Verdict

__all__ = [
    "Agent",
    "Role",
    "ROLES",
    "get_role",
    "MajerPlayerAgent",
    "Announcement",
    "ActionDecision",
    "RefereeAgent",
    "REFEREE_ROLE",
    "Verdict",
]
