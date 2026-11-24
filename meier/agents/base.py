"""Grundklass för LLM-baserade agenter.

En agent har en roll (profil/strategi) och en systemprompt. Den får ett
sammanhang och ska svara med strukturerad data. Alla agenter är oberoende: de
delar ingen intern state och kommunicerar bara via de meddelanden de får.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..llm import LLMClient, LLMError, parse_json_object


@dataclass
class Role:
    """En roll som formar agentens beteende."""

    key: str
    name: str
    description: str
    style: str  # instruktion till modellen om spelstil


@dataclass
class Agent:
    """En LLM-baserad agent med en roll."""

    role: Role
    llm: LLMClient = field(default_factory=LLMClient)

    @property
    def name(self) -> str:
        return self.role.name

    def system_prompt(self) -> str:
        raise NotImplementedError

    def announce_shake(
        self, dice: tuple[int, int], *, previous_claim: int, opponent: str | None = None
    ):
        """Standardbeteende för ett slag: titta på tärningarna och påstå högre.

        Reglerna låter spelaren lyfta på locket på sitt eget slag. En agent som vill
        avstå från att titta överskuggar detta och går via :meth:`announce_unseen`.
        """
        return self.announce(dice, previous_claim=previous_claim, opponent=opponent)

    def announce_forced(
        self, dice: tuple[int, int], *, previous_claim: int, opponent: str | None = None
    ):
        """Standardbeteende för tvingad höjning: höj som vid ett vanligt påstående.

        Agenten får de omslagna tärningarna ``dice`` och måste säga ett högre
        påstående. Spelaragenter kan överskugga detta för att i stället påstå utan att titta.
        """
        return self.announce(dice, previous_claim=previous_claim, opponent=opponent)

    def respond(self, context: str, *, json_mode: bool = True) -> dict:
        """Skicka sammanhanget till modellen och tolka svaret som JSON."""
        system = self.system_prompt()
        raw = self.llm.complete(system, context, json_mode=json_mode)
        try:
            return parse_json_object(raw)
        except LLMError:
            return {"raw": raw}
