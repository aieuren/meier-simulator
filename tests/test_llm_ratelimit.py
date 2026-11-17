"""Tester för nyckelfilen och taktbegränsaren.

Två saker skyddas här. Dels att en körning utanför ``run.sh`` ändå hittar
Gemini-nyckeln (annars faller den tillbaka på agent-serverns proxy, som skapar
en full konversation per LLM-anrop). Dels att anropen jämnas ut under
leverantörens kvot i stället för att komma i skurar.
"""

from __future__ import annotations

import threading
import time

from meier.llm import LLMConfig, _limiter_for, _read_secret


def test_read_secret_prefers_env(tmp_path, monkeypatch):
    (tmp_path / "gemini.key").write_text("filnyckel")
    monkeypatch.setenv("MEIER_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "miljonyckel")
    assert _read_secret("gemini.key", ("GEMINI_API_KEY",)) == "miljonyckel"


def test_read_secret_falls_back_to_file(tmp_path, monkeypatch):
    (tmp_path / "gemini.key").write_text("  filnyckel\n")
    monkeypatch.setenv("MEIER_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert _read_secret("gemini.key", ("GEMINI_API_KEY",)) == "filnyckel"


def test_read_secret_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("MEIER_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert _read_secret("gemini.key", ("GEMINI_API_KEY",)) == ""


def test_from_env_raises_without_any_key(tmp_path, monkeypatch):
    """Utan nyckel ska anropet avbrytas – aldrig falla tillbaka på OpenHands."""
    import pytest

    from meier.llm import LLMError

    monkeypatch.setenv("MEIER_SECRETS_DIR", str(tmp_path))
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(LLMError) as exc:
        LLMConfig.from_env()
    assert "Ingen LLM-nyckel" in str(exc.value)


def test_no_openhands_provider_remains():
    """OpenHands-proxyn ska vara helt borta ur kodvägen."""
    import meier.llm as llm_mod

    assert not hasattr(llm_mod, "_session_api_key")
    assert not hasattr(llm_mod, "_MissingProfile")
    assert not hasattr(llm_mod.LLMClient, "_complete_openhands")
    assert not hasattr(llm_mod.LLMClient, "_ensure_profile")
    assert not hasattr(llm_mod.LLMConfig, "profile_name")
    assert "127.0.0.1:60000" not in open(llm_mod.__file__, encoding="utf-8").read()


def test_from_env_reads_gemini_key_from_file(tmp_path, monkeypatch):
    """Utan nyckel i miljön ska nyckelfilen ge gemini-providern."""
    (tmp_path / "gemini.key").write_text("filnyckel")
    monkeypatch.setenv("MEIER_SECRETS_DIR", str(tmp_path))
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    cfg = LLMConfig.from_env()
    assert cfg.provider == "gemini"
    assert cfg.api_key == "filnyckel"
    assert cfg.max_rpm == 15.0


def test_max_rpm_can_be_disabled(tmp_path, monkeypatch):
    (tmp_path / "gemini.key").write_text("filnyckel")
    monkeypatch.setenv("MEIER_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MEIER_MAX_RPM", "0")
    assert LLMConfig.from_env().max_rpm == 0.0


def test_limiter_spaces_calls_apart():
    """Två anrop ska inte få göras tätare än intervallet."""
    limiter = _limiter_for(120.0, 1.0)  # 2 anrop/s -> 0.5 s mellanrum
    start = time.monotonic()
    limiter.acquire()
    limiter.acquire()
    elapsed = time.monotonic() - start
    # Första anropet går direkt, andra väntar ~intervallet.
    assert elapsed >= 0.45, elapsed


def test_limiter_margin_slows_the_rate():
    fast = _limiter_for(60.0, 1.0)
    slow = _limiter_for(60.0, 2.0)
    assert slow.interval > fast.interval


def test_limiter_is_shared_for_same_settings():
    assert _limiter_for(33.0, 1.0) is _limiter_for(33.0, 1.0)


def test_limiter_is_thread_safe():
    """Flera trådar ska tillsammans inte överskrida takten."""
    limiter = _limiter_for(211.0, 1.0)  # 0.3 s mellanrum
    stamps: list[float] = []
    lock = threading.Lock()

    def worker():
        limiter.acquire()
        with lock:
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    assert len(stamps) == 3
    # Anrop 2 och 3 väntar minst ~intervallet efter föregående.
    assert stamps[1] - stamps[0] >= 0.25
    assert stamps[2] - stamps[1] >= 0.25


def test_client_paces_retries(monkeypatch):
    """Varje försök, även omförsök, ska gå genom taktbegränsaren."""
    from meier.llm import LLMClient, _Transient

    cfg = LLMConfig(
        provider="gemini",
        model="gemini-3.1-flash-lite",
        max_retries=3,
        retry_backoff=0.0,
        max_rpm=212.0,  # 0.3 s mellanrum
        rate_limit_margin=1.0,
    )
    client = LLMClient(cfg)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Transient("tillfälligt")
        return "klart"

    start = time.monotonic()
    assert client._with_retries(flaky) == "klart"
    elapsed = time.monotonic() - start
    # Tre försök: två väntor på ~0.3 s.
    assert elapsed >= 0.55, elapsed
