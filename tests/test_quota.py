"""Test för dagskvotsräkningen i ``meier/quota.py`` och ``/api/quota``.

Google redovisar inte kvarvarande kvot, så modulen räknar våra egna anrop.
Testerna prövar räkningen, dygnsbytet, uppskattningen av antal matcher,
återställningstiden och att en trasig kvotfil inte stoppar en match.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from meier import quota
from meier.llm import LLMClient, LLMConfig
from meier.web import app as web_app


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_raknar_per_modell(monkeypatch, tmp_path):
    monkeypatch.setenv("MEIER_QUOTA_FILE", str(tmp_path / "kvot.json"))
    quota.record_call("gemini-3.1-flash-lite")
    quota.record_call("gemini-3.1-flash-lite")
    quota.record_call("reserv-modell")
    data = quota.snapshot("gemini-3.1-flash-lite")
    assert data["used"] == 2
    assert data["models"]["reserv-modell"] == 1


def test_nytt_dygn_nollstaller(monkeypatch, tmp_path):
    path = tmp_path / "kvot.json"
    monkeypatch.setenv("MEIER_QUOTA_FILE", str(path))
    path.write_text(
        '{"day": "2000-01-01", "calls": {"m": 42}, '
        '"exhausted": {"hint": "1h", "at": 0}}',
        encoding="utf-8",
    )
    data = quota.snapshot("m")
    assert data["used"] == 0
    assert data["exhausted_hint"] is None


def test_uppskattning_av_matcher(monkeypatch, tmp_path):
    monkeypatch.setenv("MEIER_QUOTA_FILE", str(tmp_path / "kvot.json"))
    monkeypatch.setenv("MEIER_DAILY_CALLS", "500")
    monkeypatch.setenv("MEIER_CALLS_PER_MATCH", "80")
    for _ in range(200):
        quota.record_call("m")
    data = quota.snapshot("m")
    assert data["remaining"] == 300
    assert data["matches_left"] == 3


def test_taket_ger_noll_kvar(monkeypatch, tmp_path):
    monkeypatch.setenv("MEIER_QUOTA_FILE", str(tmp_path / "kvot.json"))
    monkeypatch.setenv("MEIER_DAILY_CALLS", "10")
    for _ in range(12):
        quota.record_call("m")
    data = quota.snapshot("m")
    assert data["remaining"] == 0
    assert data["matches_left"] == 0


def test_reset_ar_midnatt_stillahavstid():
    moment = _utc(2026, 11, 26, 12, 0)  # 04:00 i Los Angeles
    local = quota.reset_at(moment).astimezone(quota.PACIFIC)
    assert (local.hour, local.minute) == (0, 0)
    assert local.date() == moment.astimezone(quota.PACIFIC).date() + timedelta(days=1)


def test_google_hint_sparas(monkeypatch, tmp_path):
    monkeypatch.setenv("MEIER_QUOTA_FILE", str(tmp_path / "kvot.json"))
    quota.note_exhausted("5h38m11s")
    assert quota.snapshot("m")["exhausted_hint"] == "5h38m11s"


def test_trasig_kvotfil_stoppar_inte(monkeypatch, tmp_path):
    path = tmp_path / "kvot.json"
    path.write_text("{ inte json", encoding="utf-8")
    monkeypatch.setenv("MEIER_QUOTA_FILE", str(path))
    quota.record_call("m")
    assert quota.snapshot("m")["used"] == 1


def test_llm_anrop_raknas(monkeypatch, tmp_path):
    """Ett lyckat LLM-svar ska öka dagens räkning för rätt modell."""
    monkeypatch.setenv("MEIER_QUOTA_FILE", str(tmp_path / "kvot.json"))
    cfg = LLMConfig(provider="gemini", model="gemini-3.1-flash-lite")
    LLMClient(cfg)._record_usage({"total_tokens": 10}, model="reserv-modell")
    data = quota.snapshot("gemini-3.1-flash-lite")
    assert data["models"] == {"reserv-modell": 1}
    assert data["used"] == 0


def test_api_quota(monkeypatch, tmp_path):
    monkeypatch.setenv("MEIER_QUOTA_FILE", str(tmp_path / "kvot.json"))
    quota.record_call("gemini-3.1-flash-lite")
    data = TestClient(web_app.app).get("/api/quota").json()
    for key in (
        "limit",
        "used",
        "remaining",
        "matches_left",
        "calls_per_match",
        "reset_at",
        "reset_in_seconds",
        "models",
    ):
        assert key in data
    assert data["limit"] == 500
    assert data["reset_in_seconds"] > 0
    assert data["models"]["gemini-3.1-flash-lite"] == 1
