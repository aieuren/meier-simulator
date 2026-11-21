"""Vad som är lagligt i ett givet spelläge — och inget mer.

Det här lagret äger **reglerna**. Det svarar på frågan "vilka drag får spelaren
göra just nu?" och aldrig på "vilket drag är bäst?". Den frågan hör till
spelaren (LLM:en), inte till koden.

Uppdelningen är avsiktlig. En tidigare version lade strategin i koden och
lämnade bara repliken åt modellen. Det gjorde varje spelare till samma formel
med olika konstanter. Här är koden i stället domare: den räknar upp de lagliga
dragen och avvisar allt annat, så att en LLM kan spela fritt utan att kunna
bryta spelets regler.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import rules

#: De tre svar en spelare kan ge på ett bud, i presentationsordning.
RESPONSES: tuple[str, ...] = ("syna", "skicka", "slå")

#: De två valen vid en tvingad höjning (bägaren har gått ett helt varv).
FORCED_CHOICES: tuple[str, ...] = ("titta", "blint")


def response_actions(*, bid: int) -> list[str]:
    """Vilka svar som är lagliga på budet ``bid``.

    ``syna`` och ``skicka`` är alltid lagliga. ``slå`` kräver att det finns ett
    högre bud att säga, så mot Meier — som är högst — faller det bort. Att erbjuda
    ett slag utan högre bud vore att erbjuda ett drag som inte går att utföra.
    """
    if not rules.is_valid_value(bid):
        raise ValueError(f"{bid} är inte ett giltigt bud")
    if rules.higher_options(bid):
        return list(RESPONSES)
    return [a for a in RESPONSES if a != "slå"]


def legal_bids(*, shown: int, previous_bid: int | None = None) -> list[int]:
    """Alla bud spelaren får säga, givet vad tärningarna visar.

    ``shown`` är det spelaren ser i bägaren. ``previous_bid`` är budet som ligger
    (``None`` vid rundans första bud). Regeln är att budet måste vara **strikt
    högre** än det som ligger, och att det alltid måste vara ett giltigt utfall.

    Vid första budet finns ingen undre gräns utöver utfallen själva, så hela
    rangordningen är laglig — även ``31``, det lägsta. Det är därför en spelare
    kan bjuda under sina egna tärningar.
    """
    if not rules.is_valid_value(shown):
        raise ValueError(f"{shown} är inte ett giltigt utfall")
    if previous_bid is None:
        return list(rules.RANKING)
    if not rules.is_valid_value(previous_bid):
        raise ValueError(f"{previous_bid} är inte ett giltigt bud")
    return rules.higher_options(previous_bid)


def blind_bids(*, previous_bid: int) -> list[int]:
    """Bud som är lagliga när spelaren slår utan att titta.

    Samma krav som annars: strikt högre än budet som ligger. Att spelaren inte
    ser tärningarna ändrar inte vad som är lagligt, bara vad som är klokt.
    """
    if not rules.is_valid_value(previous_bid):
        raise ValueError(f"{previous_bid} är inte ett giltigt bud")
    return rules.higher_options(previous_bid)


def forced_choices(*, previous_bid: int) -> list[str]:
    """Vilka val som är lagliga vid en tvingad höjning.

    Bägaren har gått ett helt varv tillbaka till budgivaren, som måste höja.
    Finns ett högre bud kan spelaren välja att titta på de nya tärningarna eller
    att bjuda blint. Är budet redan Meier finns inget högre: då slår spelaren om
    och börjar en ny runda, och valet faller bort.
    """
    if not rules.is_valid_value(previous_bid):
        raise ValueError(f"{previous_bid} är inte ett giltigt bud")
    if not rules.higher_options(previous_bid):
        return []
    return list(FORCED_CHOICES)


def is_legal_bid(bid: int, *, previous_bid: int | None = None) -> bool:
    """Är ``bid`` ett lagligt bud att säga?"""
    if not rules.is_valid_value(bid):
        return False
    if previous_bid is None:
        return True
    if not rules.is_valid_value(previous_bid):
        return False
    return rules.is_higher(bid, previous_bid)


def is_legal_response(action: str, *, bid: int) -> bool:
    """Är ``action`` ett lagligt svar på budet ``bid``?"""
    if not rules.is_valid_value(bid):
        return False
    return action in RESPONSES


def is_legal_forced(choice: str, *, previous_bid: int) -> bool:
    """Är ``choice`` lagligt vid en tvingad höjning över ``previous_bid``?"""
    return choice in forced_choices(previous_bid=previous_bid)


@dataclass(frozen=True)
class Violation:
    """Ett avvisat drag: vad spelaren ville göra och varför det inte gick."""

    action: str
    reason: str
