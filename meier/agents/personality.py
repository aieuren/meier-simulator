"""Spelarpersonlighet som **prosa**, inte som formel.

Parametrarna ``caution``, ``statistics``, ``unpredictability`` och ``reading``
beskriver en människa. Tidigare matades de in i en formel som räknade fram
draget, vilket gjorde varje spelare till samma algoritm med olika tal. Här
översätts de i stället till en beskrivning som LLM:en får läsa, så att modellen
kan spela *som* den personen i stället för att räkna som en tabell.

Måtten är underlag, inte dom. De säger hur en spelare brukar bete sig — inte
vilket drag som är rätt i en viss situation.
"""

from __future__ import annotations

from ..policy import AgentParams


#: Fem nivåer. Tre slog ihop spelare som registret med flit skiljer på
#: (David 0,65 och Cecilia 0,50 blev samma text), och då tappar profilen sitt
#: syfte.
_LEVELS: tuple[str, ...] = ("mycket låg", "låg", "medel", "hög", "mycket hög")


def level_name(value: float) -> str:
    """Den grova nivån för ett parametervärde, som ett ord.

    Används både i beskrivningen till modellen och när en serie ska gruppera
    spelare efter förmåga. Samma indelning på båda ställena, annars kan texten
    säga "hög" om en spelare som statistiken kallar "medel".
    """
    idx = min(len(_LEVELS) - 1, int(value * len(_LEVELS)))
    return _LEVELS[idx]


def _level(value: float) -> str:
    return level_name(value)


def _scale(value: float) -> str:
    """Värdet som en läsbar siffra, så två spelare aldrig blir identiska i text."""
    return f"{round(value * 100)}"


#: Vad respektive nivå betyder i ord, per egenskap.
_CAUTION = {
    "mycket låg": "Du tar stora risker och synar hellre än lägger dig.",
    "låg": "Du tar gärna chansen även när det kan kosta ett liv.",
    "medel": "Du väger chansen att vinna mot risken att förlora ett liv.",
    "hög": "Du undviker att förlora liv och synar helst när du är ganska säker.",
    "mycket hög": "Du synar nästan bara när du är säker, och lägger dig hellre än chansar.",
}

_STATISTICS = {
    "mycket låg": "Du spelar på känsla och bryr dig inte om hur sannolikt något är.",
    "låg": "Du lutar åt känslan och räknar sällan på oddsen.",
    "medel": "Du väger in sannolikheterna när du tvekar.",
    "hög": "Du håller dig till sannolikheterna och låter dem styra dina val.",
    "mycket hög": "Du räknar hårt på sannolikheterna och följer dem även när känslan säger annat.",
}

_UNPREDICTABILITY = {
    "mycket låg": "Du spelar likadant varje gång och är lätt att läsa.",
    "låg": "Du varierar dig sällan och håller dig till ditt invanda mönster.",
    "medel": "Du varierar ditt spel då och då så att det inte blir förutsägbart.",
    "hög": "Du byter taktik ofta för att motståndarna inte ska kunna läsa dig.",
    "mycket hög": "Du byter spel hela tiden; ingen ska kunna förutse vad du gör härnäst.",
}

_READING = {
    "mycket låg": "Du spelar ditt eget spel och struntar i vad motståndarna gör.",
    "låg": "Du spelar ditt eget spel och bryr dig föga om motståndarnas mönster.",
    "medel": "Du lägger märke till hur motståndarna brukar påstå och syna.",
    "hög": "Du följer noga hur varje motståndare beter sig och anpassar dig efter det.",
    "mycket hög": "Du väger varje drag mot allt du lärt dig om motståndarnas vanor.",
}


def describe(params: AgentParams) -> str:
    """Beskriv spelarens sätt att spela, i löpande svensk text."""
    caution = _level(params.caution)
    statistics = _level(params.statistics)
    unpredictability = _level(params.unpredictability)
    reading = _level(params.reading)
    return (
        f"- Försiktighet: {caution} ({_scale(params.caution)} av 100). {_CAUTION[caution]}\n"
        f"- Statistik: {statistics} ({_scale(params.statistics)} av 100). "
        f"{_STATISTICS[statistics]}\n"
        f"- Oförutsägbarhet: {unpredictability} "
        f"({_scale(params.unpredictability)} av 100). {_UNPREDICTABILITY[unpredictability]}\n"
        f"- Läsning av motståndare: {reading} ({_scale(params.reading)} av 100). "
        f"{_READING[reading]}"
    )


def describe_opponent(
    *,
    kind: str,
    call_tendency: float,
    bluff_tendency: float,
    confidence: float,
    predictability: float | None = None,
) -> str:
    """Beskriv en motståndare som spelaren har läst, i ord.

    ``confidence`` styr hur säkert påståendet får låta. En bild byggd på en enda
    syn ska inte låta som en sanning. ``predictability`` får vara ``None`` när
    ingen har bedömt den — då sägs det rakt ut i stället för att en gissning
    kläs i ord.
    """
    if confidence < 0.25:
        hedge = "Du har knappt sett något av henne än."
    elif confidence < 0.6:
        hedge = "Du har sett en del av henne."
    else:
        hedge = "Du har sett henne spela ett tag nu."
    if predictability is None:
        readable = "Hur lätt hon är att läsa har du ingen uppfattning om."
    elif predictability < 0.35:
        readable = "Hon är svår att läsa — hennes drag säger dig lite."
    elif predictability < 0.65:
        readable = "Hon går delvis att läsa."
    else:
        readable = "Hon är lätt att läsa — hennes mönster upprepar sig."
    return (
        f"{hedge} Hon verkar vara av typen \"{kind}\", med "
        f"{_level(call_tendency)} benägenhet att syna och "
        f"{_level(bluff_tendency)} benägenhet att bluffa. {readable}"
    )
