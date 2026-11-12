"""Regler för tärningsspelet Meier (också kallat Mia, Mire, Kuriki, Kunito).

Två tärningar läses som ett tvåsiffrigt tal med den högsta tärningen först:
2 och 5 blir 52. Alla 21 möjliga utfall har en fast rangordning där 21
("Meier") är högst och 31 är lägst.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# Rangordning, högst först. Index 0 är Meier (21), index 20 är lägst (31).
RANKING: tuple[int, ...] = (
    21,  # Meier – högst
    11,
    22,
    33,
    44,
    55,
    66,
    65,
    64,
    63,
    62,
    61,
    54,
    53,
    52,
    51,
    43,
    42,
    41,
    32,
    31,  # lägst
)

# value -> rangordningsindex (0 = bäst). Praktiskt för uppslag.
_RANK_INDEX: dict[int, int] = {value: i for i, value in enumerate(RANKING)}

MEIER = 21


#: Tärningens längd delad med dess bredd. 1,0 vore en perfekt kub.
DIE_ELONGATION = 1.3

#: Vikter per tärningssida 1..6 för en avlång tärning.
#:
#: Ändytorna (1 och 2) är kvadratiska med arean w². Långytorna (3-6) har arean
#: w·L, där L är längden. Vikten är ytans area, så en sida 3-6 är
#: DIE_ELONGATION gånger så sannolik som en sida 1-2. En kub (1,0) ger
#: likformig fördelning. Udda och jämn förblir alltid lika sannolika, eftersom
#: 1 och 2 ligger på ändytorna (en udda, en jämn) och 3-6 på långytorna.
FACE_WEIGHTS: tuple[float, ...] = (
    1.0, 1.0, DIE_ELONGATION, DIE_ELONGATION, DIE_ELONGATION, DIE_ELONGATION,
)


_FACES: tuple[int, ...] = (1, 2, 3, 4, 5, 6)


def roll(rng: random.Random | None = None) -> tuple[int, int]:
    """Slå två avlånga tärningar. Returnerar (tärning 1, tärning 2)."""
    r = rng or random
    a, b = r.choices(_FACES, weights=FACE_WEIGHTS, k=2)
    return a, b


def read_dice(a: int, b: int) -> int:
    """Läs två tärningar som ett tal med den högsta först.

    >>> read_dice(2, 5)
    52
    >>> read_dice(2, 1)
    21
    """
    if not (1 <= a <= 6 and 1 <= b <= 6):
        raise ValueError(f"Tärningarna måste vara mellan 1 och 6, fick {a} och {b}")
    hi, lo = max(a, b), min(a, b)
    return hi * 10 + lo


def dice_from_value(value: int) -> tuple[int, int]:
    """Motsatt riktning av :func:`read_dice`. Returnerar (högsta, lägsta)."""
    if value not in _RANK_INDEX:
        raise ValueError(f"{value} är inte ett giltigt utfall")
    hi, lo = divmod(value, 10)
    return hi, lo


def is_valid_value(value: int) -> bool:
    return value in _RANK_INDEX


def is_meier(value: int) -> bool:
    return value == MEIER


def rank(value: int) -> int:
    """Rangordningsindex för ett utfall. Lägre är bättre (0 = Meier)."""
    try:
        return _RANK_INDEX[value]
    except KeyError:
        raise ValueError(f"{value} är inte ett giltigt utfall") from None


def compare(a: int, b: int) -> int:
    """Jämför två bud/utfall.

    Returnerar 1 om ``a`` är högre än ``b``, -1 om lägre och 0 om lika.
    """
    ra, rb = rank(a), rank(b)
    if ra == rb:
        return 0
    return 1 if ra < rb else -1


def is_higher(a: int, b: int) -> bool:
    return compare(a, b) > 0


def next_higher(value: int) -> int | None:
    """Nästa utfall som är strikt högre än ``value`` (eller None om högst)."""
    idx = rank(value)
    if idx == 0:
        return None
    return RANKING[idx - 1]


def higher_options(value: int) -> list[int]:
    """Alla utfall som är strikt högre än ``value``."""
    return list(RANKING[: rank(value)])


def name(value: int) -> str:
    """Läsbart namn för ett utfall."""
    if value == MEIER:
        return "21 – Meier"
    return str(value)


def format_dice(a: int, b: int) -> str:
    return f"{read_dice(a, b)} ({max(a, b)} och {min(a, b)})"


@dataclass(frozen=True)
class CallResult:
    """Resultatet av att någon synar ett bud."""

    bid: int
    shown: int
    caller_loses: bool  # True om den som synade förlorar, annars budgivaren
    lives: int  # antal liv som förloras (1 eller 2)

    @property
    def loser(self) -> str:
        return "caller" if self.caller_loses else "bidder"

    def describe(self) -> str:
        who = "den som synade" if self.caller_loses else "budgivaren"
        return (
            f"Tärningarna visar {name(self.shown)} mot budet {name(self.bid)}. "
            f"{who.capitalize()} förlorar {self.lives} liv."
        )


def resolve_call(bid: int, shown: int) -> CallResult:
    """Avgör en syn (ett "call").

    - Visar tärningarna lägre än det sagda förlorar föregående spelare (budgivaren).
    - Är värdet samma eller högre förlorar den som synade.
    - Meier kostar dubbelt: om budet är Meier, eller om tärningarna visar Meier
      när någon synar, förloras två liv i stället för ett.
    """
    if not is_valid_value(bid):
        raise ValueError(f"{bid} är inte ett giltigt bud")
    if not is_valid_value(shown):
        raise ValueError(f"{shown} är inte ett giltigt utfall")

    # Lägre visat värde än budet -> budgivaren förlorar.
    caller_loses = compare(shown, bid) >= 0

    double = is_meier(bid) or is_meier(shown)
    lives = 2 if double else 1

    return CallResult(bid=bid, shown=shown, caller_loses=caller_loses, lives=lives)


def lives_for_meier(value: int) -> int:
    """Meier kostar dubbelt."""
    return 2 if is_meier(value) else 1
