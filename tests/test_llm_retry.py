"""Tester för omförsök vid tillfälliga LLM-fel."""

from __future__ import annotations

import httpx
import pytest

from meier.llm import LLMClient, LLMConfig, LLMError, _RateLimited, _Transient


def _client(max_retries=3, backoff=0.0, rate_backoff=0.0) -> LLMClient:
    cfg = LLMConfig(
        provider="gemini",
        model="gemini-3.1-flash-lite",
        max_retries=max_retries,
        retry_backoff=backoff,
        rate_limit_backoff=rate_backoff,
    )
    return LLMClient(cfg)


def test_transient_failure_is_retried_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Transient("tillfälligt")
        return "klart"

    assert _client()._with_retries(flaky) == "klart"
    assert calls["n"] == 3


def test_persistent_transient_failure_gives_up():
    def always_fail():
        raise _Transient("nere")

    with pytest.raises(LLMError) as exc:
        _client(max_retries=2)._with_retries(always_fail)
    assert "2 försök" in str(exc.value)


def test_timeout_is_transient():
    def timeout():
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(LLMError):
        _client(max_retries=1)._with_retries(timeout)


def test_rate_limit_waits_longer_than_a_normal_retry():
    """429 ska vänta kvot-backoff, inte den korta standard-backoffen."""
    waited: list[float] = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _RateLimited("för många anrop")
        return "klart"

    client = _client(max_retries=2, backoff=0.0, rate_backoff=7.0)
    import meier.llm as llm_mod

    original = llm_mod.time.sleep
    llm_mod.time.sleep = waited.append
    try:
        assert client._with_retries(flaky) == "klart"
    finally:
        llm_mod.time.sleep = original
    assert waited and waited[0] == 7.0, waited


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_complete_retries_real_timeout_then_succeeds(monkeypatch):
    """Ett tidsavbrott i det riktiga anropet ska följas av ett nytt försök."""
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("timed out")
        return _FakeResponse(
            {"choices": [{"message": {"content": '{"bid": 52}'}}], "usage": {"total_tokens": 3}}
        )

    monkeypatch.setattr("meier.llm.httpx.post", fake_post)
    client = _client(max_retries=3)
    assert client.complete("system", "user") == '{"bid": 52}'
    assert calls["n"] == 2


def _overloaded() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(503, request=request, json={"error": {"code": 503}})
    return httpx.HTTPStatusError("503", request=request, response=response)


def test_overloaded_model_falls_back_without_retrying(monkeypatch):
    """503 ska byta modell direkt, inte göra om samma anrop.

    Googles "high demand" håller i sig i minuter. Att försöka igen mot samma
    modell kostar tre väntetider utan att hjälpa.
    """
    models: list[str] = []

    def fake_post(url, json=None, **kwargs):
        models.append(json["model"])
        if json["model"] == "primär":
            raise _overloaded()
        return _FakeResponse(
            {"choices": [{"message": {"content": "svar"}}], "usage": {"total_tokens": 1}}
        )

    monkeypatch.setattr("meier.llm.httpx.post", fake_post)
    cfg = LLMConfig(
        provider="gemini",
        model="primär",
        fallback_models=("reserv",),
        max_retries=3,
        retry_backoff=0.0,
    )
    client = LLMClient(cfg)
    assert client.complete("system", "user") == "svar"
    assert models == ["primär", "reserv"], models


def test_the_model_that_answered_is_tried_first_next_time(monkeypatch):
    """Efter ett byte ska reserven gå först, så varje beslut inte betalar omvägen."""
    models: list[str] = []

    def fake_post(url, json=None, **kwargs):
        models.append(json["model"])
        if json["model"] == "primär":
            raise _overloaded()
        return _FakeResponse(
            {"choices": [{"message": {"content": "svar"}}], "usage": {"total_tokens": 1}}
        )

    monkeypatch.setattr("meier.llm.httpx.post", fake_post)
    cfg = LLMConfig(
        provider="gemini",
        model="primär",
        fallback_models=("reserv",),
        max_retries=1,
        retry_backoff=0.0,
    )
    client = LLMClient(cfg)
    client.complete("system", "user")
    models.clear()
    client.complete("system", "user")
    assert models == ["reserv"], models


def test_all_models_overloaded_raises_with_each_reason(monkeypatch):
    def fake_post(url, **kwargs):
        raise _overloaded()

    monkeypatch.setattr("meier.llm.httpx.post", fake_post)
    cfg = LLMConfig(
        provider="gemini",
        model="primär",
        fallback_models=("reserv",),
        max_retries=1,
    )
    with pytest.raises(LLMError) as exc:
        LLMClient(cfg).complete("system", "user")
    message = str(exc.value)
    assert "primär" in message and "reserv" in message


def test_fallback_models_are_read_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "nyckel")
    monkeypatch.setenv("MEIER_FALLBACK_MODELS", " a , b ,, ")
    cfg = LLMConfig.from_env()
    assert cfg.fallback_models == ("a", "b")


def test_fallback_models_default_to_empty(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "nyckel")
    monkeypatch.delenv("MEIER_FALLBACK_MODELS", raising=False)
    assert LLMConfig.from_env().fallback_models == ()
