"""Vaktar att README och koden beskriver samma spelare.

README drev iväg en gång: den beskrev rollerna "Ärlig-Adolf" och
"Rackar-Rakel" långt efter att registret bytt till Axel, Berit, Cecilia och
David. Exempelkommandona gick inte att köra. De här testerna läser README som
text och jämför mot registret, så glidningen upptäcks direkt.
"""

from __future__ import annotations

import re
from pathlib import Path

from meier.agents.roster import ROSTER
from meier.opponents import describe_params

README = Path(__file__).resolve().parent.parent / "README.md"


def _text() -> str:
    return README.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Radbrytningar i README ska inte kunna bryta en jämförelse."""
    return " ".join(text.split())


def test_readme_lists_exactly_the_registered_players():
    text = _text()
    for key, profile in ROSTER.items():
        assert f"`{key}`" in text, f"README saknar rollnyckeln {key}"
        assert profile.name in text, f"README saknar namnet {profile.name}"


def test_readme_has_no_dead_role_keys():
    """Gamla rollnamn får inte ligga kvar och se ut som om de fungerade."""
    text = _text()
    for dead in ("arling", "rackar", "kalkyl", "trygg"):
        assert dead not in text, f"README nämner den borttagna rollen '{dead}'"


def test_readme_parameters_match_the_roster():
    """Siffertabellen i README ska visa samma värden som registret."""
    text = _text()
    for profile in ROSTER.values():
        row = next(
            (ln for ln in text.splitlines() if ln.startswith(f"| `{profile.key}` |")),
            None,
        )
        assert row is not None, f"README saknar tabellrad för {profile.name}"
        cells = [c.strip() for c in row.split("|")[1:-1]]
        risk, press, reading = cells[2], cells[3], cells[4]
        assert risk == f"{profile.params.risk:.2f}".replace(".", ","), (
            f"risk för {profile.name}: README {risk} mot kod {profile.params.risk}"
        )
        assert press == f"{profile.params.press:.2f}".replace(".", ",")
        assert reading == f"{profile.params.reading:.2f}".replace(".", ",")


def test_readme_plain_language_matches_generated_text():
    """Klartextraderna ska vara den text som describe_params() faktiskt ger."""
    text = _flat(_text())
    for profile in ROSTER.values():
        expected = _flat(
            describe_params(
                profile.params.risk, profile.params.press, profile.params.reading
            )
        )
        assert expected in text, (
            f"README:s klartext för {profile.name} stämmer inte med koden. "
            f"Koden ger: {expected}"
        )


def test_readme_cli_examples_use_real_roles():
    """Varje --role och varje rollargument i README måste finnas i registret."""
    text = _text()
    for match in re.finditer(r"--role\s+(\w+)", text):
        assert match.group(1) in ROSTER, f"README använder okänd roll: {match.group(1)}"
    for match in re.finditer(r"meier\.cli play ([\w\s]+)", text):
        for word in match.group(1).split():
            assert word in ROSTER, f"README spelar med okänd roll: {word}"
    for match in re.finditer(r'"role":\s*"(\w+)"', text):
        assert match.group(1) in ROSTER, f"README-API-exempel: okänd roll {match.group(1)}"


def test_readme_links_to_the_full_model():
    assert "docs/agent-model.md" in _text()
