"""Globala skydd för testsviten.

Testerna ska aldrig röra det riktiga loggrepet på GitHub eller klonen i
/workspace. Utan skyddet skrev en testkörning serier dit: när pushen väl
fungerade gick två påhittade serier ut på fjärren.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_log_repo(monkeypatch, tmp_path):
    """Peka loggrepet mot en tom testkatalog och stäng av push.

    Ett test som prövar incheckningen sätter MEIER_LOGS_DIR,
    MEIER_LOGS_REMOTE_URL och MEIER_LOGS_PUSH själv, och då gäller det.
    """
    monkeypatch.setenv("MEIER_LOGS_DIR", str(tmp_path / "loggrepo-klon"))
    monkeypatch.setenv("MEIER_LOGS_TOKEN_FILE", str(tmp_path / "ingen-token"))
    monkeypatch.setenv("MEIER_LOCAL_LOG_DIR", str(tmp_path / "lokala-serier"))
    monkeypatch.setenv("MEIER_LOGS_PUSH", "0")
