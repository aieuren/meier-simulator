"""Spelarpersonlighet som **prosa**, inte som formel.

Parametrarna ``risk``, ``press`` och ``reading`` beskriver en människa. Tidigare
matades de in i en formel som räknade fram draget, vilket gjorde varje spelare
till samma algoritm med olika tal. Här översätts de i stället till en
beskrivning som LLM:en får läsa, så att modellen kan spela *som* den personen i
stället för att räkna som en tabell.

Måtten är underlag, inte dom. De säger hur en spelare brukar bete sig — inte
vilket drag som är rätt i en viss situation.
"""

from __future__ import annotations

from ..policy import AgentParams


#: Fem nivåer. Tre slog ihop spelare som registret med flit skiljer på
#: (David 0,65 och Cecilia 0,50 blev samma text), och då tappar profilen sitt
#: syfte.
_LEVELS: tuple[str, ...] = ("mycket låg", "låg", "medel", "hög", "mycket hög")


def _level(value: float) -> str:
    idx = min(len(_LEVELS) - 1, int(value * len(_LEVELS)))
    return _LEVELS[idx]


def _scale(value: float) -> str:
    """Värdet som en läsbar siffra, så två spelare aldrig blir identiska i text."""
    return f"{round(value * 100)}"


#: Vad respektive nivå betyder i ord, per egenskap.
_RISK = {
    "mycket låg": "Du synar nästan bara när du är säker, och lägger dig hellre än chansar.",
    "låg": "Du undviker att förlora liv och synar helst när du är ganska säker.",
    "medel": "Du väger chansen att vinna mot risken att förlora ett liv.",
    "hög": "Du tar gärna chansen även när det kan kosta ett liv.",
    "mycket hög": "Du synar och chansar nästan vad som helst för att vinna rundan.",
}

_PRESS = {
    "mycket låg": "Du påstår nästan alltid sanningen och bluffar i stort sett aldrig.",
    "låg": "Du påstår nära vad tärningarna visar och bluffar sällan.",
    "medel": "Du bluffar ibland, mest när det är billigt att bli synad.",
    "hög": "Du pressar påståendet uppåt och bluffar ofta för att sätta press.",
    "mycket hög": "Du påstår hårt över tärningarna nästan varje gång.",
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
    risk, press, reading = _level(params.risk), _level(params.press), _level(params.reading)
    return (
        f"- Risktagande: {risk} ({_scale(params.risk)} av 100). {_RISK[risk]}\n"
        f"- Press och bluff: {press} ({_scale(params.press)} av 100). {_PRESS[press]}\n"
        f"- Läsning av motståndare: {reading} ({_scale(params.reading)} av 100). "
        f"{_READING[reading]}"
    )


def describe_opponent(
    *, kind: str, risk: float, press: float, confidence: float
) -> str:
    """Beskriv en motståndare som spelaren har läst, i ord.

    ``confidence`` styr hur säkert påståendet får låta. En bild byggd på en enda
    syn ska inte låta som en sanning.
    """
    if confidence < 0.25:
        hedge = "Du har knappt sett något av henne än."
    elif confidence < 0.6:
        hedge = "Du har sett en del av henne."
    else:
        hedge = "Du har sett henne spela ett tag nu."
    return (
        f"{hedge} Hon verkar vara av typen \"{kind}\", med "
        f"{_level(risk)} riskbenägenhet och {_level(press)} benägenhet att pressa."
    )
