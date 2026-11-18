"""Spelarregistret: de fyra profilerna som möts i matcherna.

Personligheten bor i **parametrarna** (``risk``, ``press``, ``reading``), inte i
namnet. Namnen är neutrala med flit. En värderande etikett som "Rackar-Rakel"
säger åt modellen vem den *ska vara*, och då spelar den en karikatyr i stället
för att spela spelet. Det gör det omöjligt att veta om en profil vinner på sin
taktik eller på sin etikett. Neutrala namn tar bort den signalen.

Fyra profiler:

- **Axel** är basmodellen: deterministisk, icke-läsande, utan LLM. Han är den
  fasta mätstickan de andra jämförs mot (se ``docs/agent-model.md``).
- **Berit**, **Cecilia** och **David** är samma policykärna med milda
  personligheter ovanpå: försiktig, kalkylerande och djärv. Ingen av dem är så
  extrem som de gamla rollerna var — de historiska loggarna visade att en
  extremt pressande profil (``press`` ≈ 0,9) förlorade varje match.

Alla fyra drivs av samma :class:`~meier.policy.BasePolicy`. LLM:en, när den
finns, formulerar bara repliken; draget ägs av policyn.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..policy import AgentParams
from .base import Role


@dataclass(frozen=True)
class Profile:
    """En spelares identitet: namn, personlighet (parametrar) och LLM-val."""

    key: str
    name: str
    description: str
    params: AgentParams
    uses_llm: bool = True

    @property
    def role(self) -> Role:
        return Role(key=self.key, name=self.name, description=self.description, style="")


#: Parametrarna är en startpunkt, kalibrerade mot de historiska loggarna och
#: avsiktligt milda. De justeras när vi utvärderar tillsammans.
ROSTER: dict[str, Profile] = {
    "axel": Profile(
        key="axel",
        name="Axel",
        description="Basmodellen. Fast, läser ingen motståndare och ändrar sig aldrig.",
        params=AgentParams(risk=0.50, press=0.50, reading=0.00),
        uses_llm=False,
    ),
    "berit": Profile(
        key="berit",
        name="Berit",
        description="Försiktig. Bjuder nära sanningen och synar sällan.",
        params=AgentParams(risk=0.25, press=0.25, reading=0.15),
    ),
    "cecilia": Profile(
        key="cecilia",
        name="Cecilia",
        description="Kalkylerande. Väger risk mot vinst och läser motståndaren.",
        params=AgentParams(risk=0.50, press=0.45, reading=0.50),
    ),
    "david": Profile(
        key="david",
        name="David",
        description="Djärv. Pressar budet högre och tar fler risker än de andra.",
        params=AgentParams(risk=0.65, press=0.60, reading=0.35),
    ),
}


def role_keys() -> list[str]:
    """Alla rollnycklar i registret, i presentationsordning."""
    return list(ROSTER)


def get_profile(key: str) -> Profile:
    try:
        return ROSTER[key]
    except KeyError:
        raise ValueError(
            f"Okänd roll '{key}'. Välj bland: {', '.join(ROSTER)}"
        ) from None


def make_player(key: str, *, llm=None):
    """Bygg spelaren för ``key`` som en strategisk agent.

    ``llm`` är valfri. Utan den formulerar agenten en mekanisk replik; med den
    får LLM:en formulera repliken (aldrig draget). Axel får aldrig en LLM — han
    är den deterministiska referensen.
    """
    from .strategic import StrategicAgent

    profile = get_profile(key)
    client = llm if profile.uses_llm else None
    return StrategicAgent(profile.role, profile.params, llm=client)


def make_players(keys, *, llm_factory=None):
    """Bygg spelarna och den **delade** motståndarmodellen för en match.

    Returnerar ``(players, tracker)``. Alla läsande spelare pekar på samma
    tracker, så de delar bilden av motståndarna — precis som vid ett riktigt
    bord. Trackern matas av motorn (via ``Session.tracker``) i takt med att
    händelser blir offentliga.

    ``llm_factory`` kallas en gång per LLM-spelare för att ge var och en sin
    egen klient (så tokenräkningen per spelare hålls åtskild). Axel får ingen.

    En läsande spelare får dessutom en **läsare** med sin egen LLM-klient: det är
    den som tolkar motståndarnas beteende. Utan klient (``llm_factory=None``)
    faller läsaren tillbaka på sekreterarens aritmetik, så utvärderingsläget
    spelar exakt som förut men utan nätverk.
    """
    from ..opponents import OpponentTracker

    tracker = OpponentTracker()
    players = []
    for key in keys:
        profile = get_profile(key)
        llm = llm_factory() if (llm_factory is not None and profile.uses_llm) else None
        player = make_player(key, llm=llm)
        if player.params.reading > 0.0:
            player.tracker = tracker
        players.append(player)
    return players, tracker
