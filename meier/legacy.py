"""Bakåtkompatibilitet för matchprotokoll skrivna före namnbytet.

Protokollet använde tidigare ``bid`` för påståendet, ``bud`` för handlingen och
``blind``/``bids`` i statistiken. Loggfilerna på disk skrivs inte om: de är
historik. I stället översätts de vid inläsning, så en gammal logg analyseras som
en ny.
"""

from __future__ import annotations

from typing import Any

#: Gamla nyckelnamn -> nya. Längst först, så att ingen delyckel träffar först.
_KEY_RENAMES: tuple[tuple[str, str], ...] = (
    ("accepted_bid_name", "accepted_claim_name"),
    ("previous_bid_name", "previous_claim_name"),
    ("accepted_bid", "accepted_claim"),
    ("previous_bid", "previous_claim"),
    ("bid_name", "claim_name"),
    ("bid", "claim"),
    ("blind", "unseen"),
    ("bids", "claims"),
)

_STAT_RENAMES: tuple[tuple[str, str], ...] = (("bids", "claims"), ("blinds", "unseen"))


def _rename_keys(obj: dict[str, Any], pairs) -> dict[str, Any]:
    """Byt nyckelnamn utan att skriva över en nyckel som redan finns."""
    out = dict(obj)
    for old, new in pairs:
        if old in out and new not in out:
            out[new] = out.pop(old)
        elif old in out:
            del out[old]
    return out


def upgrade_record(record: Any) -> Any:
    """Skriv om en gammal protokollpost till nuvarande nyckelnamn.

    Nya poster lämnas orörda. Finns både den gamla och den nya nyckeln vinner
    den nya, så funktionen kan köras om utan att skada något.
    """
    if not isinstance(record, dict):
        return record

    out = dict(record)
    if out.get("action") == "bud":
        out["action"] = "påstå"

    events = []
    for event in out.get("events") or []:
        if not isinstance(event, dict):
            events.append(event)
            continue
        upgraded = _rename_keys(event, _KEY_RENAMES)
        if upgraded.get("action") == "bud":
            upgraded["action"] = "påstå"
        events.append(upgraded)
    if "events" in out:
        out["events"] = events

    stats = out.get("player_stats")
    if isinstance(stats, dict):
        out["player_stats"] = {
            name: _rename_keys(s, _STAT_RENAMES) if isinstance(s, dict) else s
            for name, s in stats.items()
        }
    return out
