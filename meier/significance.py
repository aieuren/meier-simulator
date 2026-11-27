"""Bedöm om skillnaden i antal vinster kan bero på slumpen.

Ett chi-square goodness-of-fit-test mot att alla spelare vinner lika ofta.
Svaret är en zon och en kort mening på svenska — aldrig ett påstående om bevis.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: Under så få matcher säger siffrorna ingenting alls.
MIN_MATCHES = 3
#: p-värde över det här: skillnaden kan mycket väl vara slump.
RANDOM_P = 0.20
#: p-värde under det här: skillnaden ger en indikation.
DIFFERENCE_P = 0.05

_EPS = 3e-16
_TINY = 1e-300


def _gamma_q(a: float, x: float) -> float:
    """Q(a, x) — den regulariserade övre ofullständiga gammafunktionen.

    Serieutveckling när x < a + 1 och kedjebråk annars; samma uppdelning som i
    Numerical Recipes, för serien tappar precision när x är stort.
    """
    if x <= 0.0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        ap = a
        total = delta = 1.0 / a
        for _ in range(1000):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * _EPS:
                break
        return 1.0 - total * math.exp(-x + a * math.log(x) - gln)

    b = x + 1.0 - a
    c = 1.0 / _TINY
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _TINY:
            d = _TINY
        c = b + an / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi2_sf(x: float, df: int) -> float:
    """P(chi2 med ``df`` frihetsgrader > ``x``), alltså p-värdet."""
    if df <= 0:
        return 0.0
    if x <= 0.0:
        return 1.0
    return _gamma_q(df / 2.0, x / 2.0)


def _names(names: Sequence[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} och {names[1]}"
    return ", ".join(names[:-1]) + f" och {names[-1]}"


def _match_word(n: int) -> str:
    return "match" if n == 1 else "matcher"


def win_difference(
    results: Sequence[tuple[str, int]],
    matches_played: int | None = None,
) -> dict | None:
    """Bedöm vinstfördelningen i en serie.

    ``results`` är (visningsnamn, antal vinster) per spelare. Antalet matcher
    räknas som summan av vinsterna om det inte anges. Ger ``None`` när färre än
    två spelare har resultat, för då finns inget att jämföra.
    """
    players = len(results)
    if players < 2:
        return None
    matches = int(matches_played if matches_played is not None else sum(w for _, w in results))
    top = max(w for _, w in results)
    leaders = [name for name, w in results if w == top]

    if matches < MIN_MATCHES:
        return {
            "zone": "insufficient_data",
            "text": (
                f"Endast {matches} {_match_word(matches)} har spelats. Det är för få för att "
                "avgöra om skillnaden i vinster beror på slumpen eller på olika spelstilar."
            ),
            "matches": matches,
            "players": players,
            "chi_square": None,
            "p_value": None,
            "leaders": leaders,
            "leader_wins": top,
        }

    expected = matches / players
    chi = sum((w - expected) ** 2 / expected for _, w in results)
    p = chi2_sf(chi, players - 1)

    if p >= RANDOM_P:
        zone = "likely_random"
        text = (
            "Skillnaden i antal vinster är så pass liten att den mycket väl kan bero på "
            f"slumpen. Med {matches} matcher spelade och {players} spelare finns ingen tydlig "
            "indikation på att spelstilarna påverkar vinstfördelningen."
        )
    elif p >= DIFFERENCE_P:
        zone = "uncertain"
        text = (
            f"Med {matches} matcher spelade och {players} spelare pekar skillnaden i antal "
            f"vinster svagt mot att {_names(leaders)} kan ha en fördel, men den är inte "
            "tillräckligt tydlig för att skiljas från slumpen. Fler matcher ger en säkrare "
            "bedömning."
        )
    else:
        zone = "likely_difference"
        share = f"{100 * top / matches:.0f}"
        each = "" if len(leaders) == 1 else " var"
        text = (
            f"Med {matches} matcher spelade och {players} spelare pekar skillnaden i antal "
            "vinster att deras olika spelstilar spelar roll för vinstfördelningen. "
            f"{_names(leaders)} har vunnit {top} av {matches} matcher{each}, "
            f"motsvarande {share} %."
        )

    return {
        "zone": zone,
        "text": text,
        "matches": matches,
        "players": players,
        "chi_square": round(chi, 4),
        "p_value": round(p, 6),
        "leaders": leaders,
        "leader_wins": top,
    }
