"""Spelarregistret: de fem profilerna som möts i matcherna.

Spelarens egen profil bor i **parametrarna** (``caution``, ``statistics``,
``unpredictability``, ``reading``), inte i namnet. Namnen är neutrala med flit.
En värderande etikett som "Rackar-Rakel" säger åt modellen vem den *ska vara*,
och då spelar den en karikatyr i stället för att spela spelet.

Fem profiler, byggda som **två baslinjer och tre varianter**:

- **Axel** är grundtaktiken: utan LLM, med ``reading = 0``. Han är den fasta
  mätstickan de andra jämförs mot.
- **Berit** har exakt samma parametrar som Axel men använder LLM. Skillnaden
  mellan dem visar effekten av att byta beslutsmotor från regler till
  språkmodell — inget annat skiljer dem.
- **Cecilia**, **David** och **Elsa** lyfter en dimension var: försiktighet,
  statistik respektive oförutsägbarhet. Alla tre har ``reading = 0,5``, alltså
  samma läsförmåga som varandra. De jämförs med varandra, inte med baslinjen,
  eftersom de skiljer sig från baslinjen i två avseenden (den lyfta dimensionen
  *och* läsförmågan).

``reading = 0`` betyder att agenten inte använder motståndarnas historik alls.
Det är därför Axel och Berit får ``reading = 0`` och varianterna ``0,5``.

Bluffandet finns inte som parameter. I Meier måste den som slår alltid höja över
det som står, och då blir en del påståenden lögner vad spelaren än vill. Bluffen
är ett nödvändigt ont i spelet, inte en personlighetsegenskap att skruva på.

Alla fem går genom samma :class:`~meier.agents.strategic.StrategicAgent`. LLM:en,
när den finns, äger draget. Repliken byggs i stället lokalt ur draget, så att
modellen aldrig behöver hitta på vad spelaren säger. Utan LLM faller agenten
tillbaka på :class:`~meier.policy.BasePolicy`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..policy import AgentParams
from .base import Role


@dataclass(frozen=True)
class Profile:
    """En spelares identitet: namn, egen profil (parametrar) och LLM-val."""

    key: str
    name: str
    description: str
    params: AgentParams
    uses_llm: bool = True

    @property
    def role(self) -> Role:
        return Role(key=self.key, name=self.name, description=self.description, style="")


#: Baslinjen: grundtaktiken utan LLM, ingen läsning.
_BASE = AgentParams(
    caution=0.50, statistics=0.50, unpredictability=0.20, reading=0.00
)

#: Varianternas gemensamma läsförmåga. Lika för alla tre, så att deras inbördes
#: jämförelse bara handlar om den dimension de lyfter.
_READING = 0.50

ROSTER: dict[str, Profile] = {
    "axel": Profile(
        key="axel",
        name="Axel",
        description="Grundtaktiken. Regelstyrd utan språkmodell, läser ingen motståndare.",
        params=_BASE,
        uses_llm=False,
    ),
    "berit": Profile(
        key="berit",
        name="Berit",
        description="Samma grundtaktik som Axel, men besluten fattas av en språkmodell.",
        params=_BASE,
    ),
    "cecilia": Profile(
        key="cecilia",
        name="Cecilia",
        description="Försiktig. Undviker risk och låter andra ta besluten.",
        params=AgentParams(
            caution=0.80, statistics=0.50, unpredictability=0.20, reading=_READING
        ),
    ),
    "david": Profile(
        key="david",
        name="David",
        description="Statistisk. Håller sig hårt till sannolikheterna.",
        params=AgentParams(
            caution=0.50, statistics=0.80, unpredictability=0.20, reading=_READING
        ),
    ),
    "elsa": Profile(
        key="elsa",
        name="Elsa",
        description="Oförutsägbar. Varierar sitt spel för att vara svår att läsa.",
        params=AgentParams(
            caution=0.50, statistics=0.50, unpredictability=0.80, reading=_READING
        ),
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
    """Bygg en **LLM-spelare** för ``key``.

    ``llm`` är obligatorisk för alla roller utom Axel. En LLM-spelare får aldrig
    skapas utan modell: då skulle den tyst spela grundtaktiken, och simulatorn
    skulle mäta en räkneregel i stället för modellen. Saknas klienten höjs ett
    fel, så felet syns direkt i stället för i resultatet.

    Repliken byggs alltid lokalt ur draget. Axel får aldrig en LLM — han är
    referensen utan språkmodell.

    Slumpen bakom ``unpredictability`` skapas inuti agenten. Den behöver ingen
    yttre styrning: varje spelare ska bete sig olika från gång till gång.
    """
    from .strategic import StrategicAgent

    profile = get_profile(key)
    if not profile.uses_llm:
        if llm is not None:
            raise ValueError(
                f"{profile.name} spelar utan språkmodell och kan inte få en LLM-klient."
            )
        return StrategicAgent(profile.role, profile.params)

    if llm is None:
        raise ValueError(
            f"{profile.name} är en LLM-spelare och kräver en LLM-klient. "
            f"Vill du spela rollen som regelspelare använder du make_rule_player()."
        )
    return StrategicAgent(profile.role, profile.params, llm=llm)


def make_rule_player(key: str):
    """Bygg en **regelspelare** för ``key``: ``BasePolicy``, ingen språkmodell.

    Alla roller kan spelas så. Det är ett uttalat val (utvärderingsläget
    ``--no-llm``), inte en reservväg: en LLM-spelare som inte svarar avbryter
    matchen i stället för att hamna här.
    """
    from .strategic import StrategicAgent

    profile = get_profile(key)
    return StrategicAgent(profile.role, profile.params)


def make_players(keys, *, llm_factory=None):
    """Bygg spelarna och den **delade** motståndarmodellen för en match.

    Returnerar ``(players, tracker)``. Alla läsande spelare pekar på samma
    tracker, så de delar bilden av motståndarna — precis som vid ett riktigt
    bord. Trackern matas av motorn (via ``Session.tracker``) i takt med att
    händelser blir offentliga.

    ``llm_factory`` kallas en gång per LLM-spelare för att ge var och en sin
    egen klient (så tokenräkningen per spelare hålls åtskild). Utan
    ``llm_factory`` byggs **regelspelare** för alla roller: det är uttalat
    utvärderingsläge, inte en reservväg.

    Antalet spelare är fritt: ``keys`` får innehålla två eller fler roller.
    """
    from ..opponents import OpponentTracker

    tracker = OpponentTracker()
    players = []
    for key in keys:
        profile = get_profile(key)
        if llm_factory is not None and profile.uses_llm:
            player = make_player(key, llm=llm_factory())
        else:
            player = make_rule_player(key)
        if player.params.reading > 0.0:
            player.tracker = tracker
        players.append(player)
    return players, tracker
