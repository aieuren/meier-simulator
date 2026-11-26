"""Dagskvot för Gemini: räkning, uppskattning och återställningstid.

Google redovisar inte återstående dygnskvot i något API. Vi räknar därför våra
egna anrop per modell och dygn och jämför med gränsen för fri nivå. Dygnskvoten
fylls på vid midnatt i Stillahavstid, och ett 429-svar anger exakt hur länge
som återstår; den tiden sparas när den dyker upp så att gränssnittet kan visa
Googles egen siffra i stället för vår uppskattning.

Räkningen är en uppskattning, inte ett kvitto: anrop som görs från AI Studio
eller ett annat projekt på samma nyckel syns inte här, och ett anrop som
avvisas med 429 drar ingen kvot men räknas ändå inte. Modulen får aldrig
kasta vidare till anroparen – en trasig kvotfil ska inte stoppa en match.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

#: Googles dygnskvot nollställs vid midnatt Stillahavstid.
PACIFIC = ZoneInfo("America/Los_Angeles")

#: Anrop per dygn och modell på fri nivå, enligt AGENTS.md.
DEFAULT_DAILY_CALLS = 500

#: Uppmätt snitt per match med fyra LLM-spelare (76–88 anrop i loggarna).
DEFAULT_CALLS_PER_MATCH = 80

_lock = threading.Lock()


def _state_path() -> Path:
    explicit = os.environ.get("MEIER_QUOTA_FILE")
    if explicit:
        return Path(explicit)
    base = os.environ.get("MEIER_LOCAL_LOG_DIR") or "/workspace/meier-runs"
    return Path(base) / "quota.json"


def daily_limit() -> int:
    """Anrop per dygn och modell. ``0`` stänger av räkningen."""
    raw = os.environ.get("MEIER_DAILY_CALLS", "")
    if raw.strip():
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_DAILY_CALLS


def calls_per_match() -> int:
    raw = os.environ.get("MEIER_CALLS_PER_MATCH", "")
    if raw.strip():
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return DEFAULT_CALLS_PER_MATCH


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_of(moment: datetime) -> str:
    return moment.astimezone(PACIFIC).date().isoformat()


def _read() -> dict[str, Any]:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _for_day(data: dict[str, Any], day: str) -> dict[str, Any]:
    if data.get("day") != day:
        return {"day": day, "calls": {}, "exhausted": None}
    data.setdefault("calls", {})
    data.setdefault("exhausted", None)
    return data


def record_call(model: str) -> None:
    """Räkna ett anrop för dagen. Får aldrig kasta vidare."""
    if not model:
        return
    try:
        with _lock:
            data = _for_day(_read(), _day_of(_now()))
            calls = data["calls"]
            calls[model] = int(calls.get(model, 0)) + 1
            _write(data)
    except Exception:
        pass


def note_exhausted(hint: str | None) -> None:
    """Spara Googles egen väntetid från ett 429-svar."""
    try:
        with _lock:
            data = _for_day(_read(), _day_of(_now()))
            data["exhausted"] = {
                "hint": (hint or "").strip(),
                "at": _now().timestamp(),
            }
            _write(data)
    except Exception:
        pass


def reset_at(moment: datetime | None = None) -> datetime:
    """Nästa midnatt i Stillahavstid, i UTC, då dygnskvoten fylls på."""
    local = (moment or _now()).astimezone(PACIFIC)
    midnight = datetime.combine(
        local.date() + timedelta(days=1), datetime.min.time(), tzinfo=PACIFIC
    )
    return midnight.astimezone(timezone.utc)


def snapshot(primary_model: str | None = None) -> dict[str, Any]:
    """Läget just nu: använda anrop, kvarvarande, matcher och återställning.

    ``remaining`` gäller den primära modellen, eftersom en serie avbryts när
    just dess dygnstak tar slut. Reservmodellerna har egna tak men används
    bara vid 503, så de räknas inte in i uppskattningen.
    """
    now = _now()
    data = _for_day(_read(), _day_of(now))
    used_by_model = {m: int(n) for m, n in (data.get("calls") or {}).items()}
    limit = daily_limit()
    model = primary_model or next(iter(used_by_model), "")
    used = used_by_model.get(model, 0)
    remaining = max(0, limit - used) if limit else 0
    per_match = calls_per_match()
    reset = reset_at(now)
    exhausted = data.get("exhausted") or {}
    return {
        "day": data.get("day"),
        "model": model,
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "calls_per_match": per_match,
        "matches_left": remaining // per_match if limit else 0,
        "models": used_by_model,
        "reset_at": reset.isoformat(),
        "reset_in_seconds": max(0, int((reset - now).total_seconds())),
        "exhausted_hint": (exhausted.get("hint") or None),
        "exhausted_at": exhausted.get("at"),
    }
