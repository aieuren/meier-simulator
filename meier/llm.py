"""LLM-klient för Meier-agenterna.

Klienten använder Google Gemini via ``GEMINI_API_KEY``, som talar
OpenAI-liknande ``/v1/chat/completions`` på ``/v1beta/openai``.

Det finns **ingen** återfallsväg till OpenHands agent-server. Den proxyn är en
shim som startar en hel OpenHands-konversation per anrop, vilket fyllde
``/var/openhands/conversations`` med hundratals konversationer under en match.
Saknas nyckel avbryts anropet i stället, med ett tydligt fel.

Anropen görs om några gånger vid tillfälliga fel (timeout, nätverksfel, 429 och
5xx), eftersom en lång matchserie annars avbryts av ett enstaka tidsavbrott.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


class LLMError(RuntimeError):
    """Fel vid anrop mot språkmodellen."""


class _Transient(LLMError):
    """Tillfälligt fel som är värt att försöka igen (timeout, 429, 5xx)."""


class _RateLimited(_Transient):
    """Kvottak (429). Kräver längre väntan än ett vanligt tillfälligt fel."""


def _env_float(name: str, default: float) -> float:
    """Läs en miljövariabel som flyttal, annars standardvärdet."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    """Läs en miljövariabel som heltal, annars standardvärdet."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _read_secret(filename: str, env_names: tuple[str, ...]) -> str:
    """Läs en nyckel från miljön, annars från den beständiga nyckelfilen.

    ``/home`` nollställs vid en containeromstart, men ``/workspace`` ligger kvar.
    Nyckeln bor därför i ``MEIER_SECRETS_DIR`` (standard ``/workspace/meier-secrets``).
    Utan denna fallback saknar en körning som startas utanför ``run.sh``
    nyckeln och faller tillbaka på agent-serverns proxy – som skapar en full
    konversation per anrop i stället för att bara svara.
    """
    for env_name in env_names:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    secrets_dir = os.environ.get("MEIER_SECRETS_DIR", "/workspace/meier-secrets")
    try:
        return (Path(secrets_dir) / filename).read_text().strip()
    except OSError:
        return ""


class _RateLimiter:
    """Delad taktbegränsare som håller anropen under kvottaket.

    Kvoten gäller per projekt, inte per klient, så alla klienter delar en
    instans (se ``_limiter_for``). Anropen jämnas ut i stället för att komma i
    skurar, och en marginal gör att vi aldrig ligger exakt på taket – annars
    räcker det att fönstret glider lite för att en 429:a ska slå till.
    """

    def __init__(self, max_rpm: float, margin: float = 1.15) -> None:
        self.max_rpm = max_rpm
        self.margin = margin
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    @property
    def interval(self) -> float:
        """Minsta tid mellan två anrop, med marginal."""
        return 60.0 / self.max_rpm * self.margin

    def acquire(self) -> None:
        """Blockera tills nästa anrop får göras."""
        if self.max_rpm <= 0:
            return
        interval = self.interval
        with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + interval


_limiters: dict[tuple[float, float], _RateLimiter] = {}
_limiters_lock = threading.Lock()


def _limiter_for(max_rpm: float, margin: float) -> _RateLimiter:
    """Hämta den delade taktbegränsaren för en given kvot."""
    key = (max_rpm, margin)
    with _limiters_lock:
        limiter = _limiters.get(key)
        if limiter is None:
            limiter = _RateLimiter(max_rpm, margin)
            _limiters[key] = limiter
        return limiter


def _is_transient_exc(exc: Exception) -> bool:
    """Avgör om ett SDK-undantag är tillfälligt (timeout, anslutning, 429, 5xx)."""
    name = type(exc).__name__.lower()
    if "timeout" in name or "connection" in name or "ratelimit" in name:
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text or "overloaded" in text


@dataclass
class LLMConfig:
    """Konfiguration för en LLM-anslutning."""

    provider: str  # alltid "gemini"
    model: str
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 1024
    temperature: float = 0.7
    timeout: float = 60.0
    max_retries: int = 3
    retry_backoff: float = 1.5
    #: Väntetid vid kvottak (429). Kvotfönstret är en minut, så väntan måste
    #: vara längre än vid ett vanligt tidsavbrott.
    rate_limit_backoff: float = 20.0
    #: Tak för anrop per minut (0 = ingen begränsning). Håller oss under
    #: leverantörens kvot så att en match inte stoppas av 429:or.
    max_rpm: float = 0.0
    #: Marginal över kvottaket: vi siktar på 1/marginal av tillåten takt.
    rate_limit_margin: float = 1.15

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Välj anslutning utifrån miljövariabler.

        Bara Google Gemini stöds. Nyckeln läses från ``GEMINI_API_KEY`` eller
        ``GOOGLE_API_KEY``, annars från ``$MEIER_SECRETS_DIR/gemini.key``.

        Saknas nyckeln höjs ett fel. Det finns ingen återfallsväg till
        OpenHands agent-server, eftersom varje anrop där startar en egen
        konversation.
        """
        cfg = cls._from_provider_env()
        # Gemini-endpointen hänger ibland i flera minuter. En kort timeout gör
        # att ett sådant anrop snabbt görs om i stället för att blockera ett helt
        # beslut. MEIER_TIMEOUT och MEIER_RETRIES styr detta per körning.
        cfg.timeout = _env_float("MEIER_TIMEOUT", cfg.timeout)
        cfg.max_retries = _env_int("MEIER_RETRIES", cfg.max_retries)
        # Håll anropen under leverantörens kvot. MEIER_MAX_RPM=0 stänger av.
        cfg.max_rpm = _env_float("MEIER_MAX_RPM", cfg.max_rpm or 15.0)
        return cfg

    @classmethod
    def _from_provider_env(cls) -> "LLMConfig":
        # Gemini talar OpenAI-format på /v1beta/openai.
        gemini_key = _read_secret("gemini.key", ("GEMINI_API_KEY", "GOOGLE_API_KEY"))
        if gemini_key:
            return cls(
                provider="gemini",
                model=os.environ.get("MEIER_MODEL", "gemini-3.1-flash-lite"),
                api_key=gemini_key,
                base_url=os.environ.get(
                    "MEIER_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta/openai",
                ),
            )

        raise LLMError(
            "Ingen LLM-nyckel hittades. Sätt GEMINI_API_KEY, eller lägg nyckeln i "
            f"{os.environ.get('MEIER_SECRETS_DIR', '/workspace/meier-secrets')}"
            "/gemini.key. Anrop mot OpenHands agent-server används medvetet inte: "
            "varje anrop där startar en egen konversation."
        )


@dataclass
class LLMClient:
    """Tunn klient som skickar en system- och en användarprompt."""

    config: LLMConfig = field(default_factory=LLMConfig.from_env)

    #: Tokenräkning från det senaste anropet (prompt/completion/total).
    last_usage: dict[str, int] = field(default_factory=dict, init=False)

    #: Summan av alla anrop klienten gjort (prompt/completion/total).
    total_usage: dict[str, int] = field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        init=False,
    )
    #: Antal anrop som gjorts.
    calls: int = field(default=0, init=False)

    def _record_usage(self, usage: dict[str, Any]) -> None:
        """Spara senaste anropets räkning och lägg den till summan."""
        self.last_usage = {
            k: int(v) for k, v in usage.items() if isinstance(v, (int, float))
        }
        if "total_tokens" not in self.last_usage:
            self.last_usage["total_tokens"] = self.last_usage.get(
                "prompt_tokens", 0
            ) + self.last_usage.get("completion_tokens", 0)
        self.calls += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.total_usage[key] += self.last_usage.get(key, 0)

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        return self._with_retries(
            lambda: self._complete_http(system, user, json_mode=json_mode)
        )

    def _with_retries(self, call):
        """Kör ett LLM-anrop och gör om det vid tillfälliga fel.

        Ett kvottak (429) behöver längre väntan än ett vanligt tidsavbrott,
        eftersom fönstret är en minut. ``retry_backoff`` trappas därför upp
        snabbare vid 429.
        """
        attempts = max(1, self.config.max_retries)
        limiter = (
            _limiter_for(self.config.max_rpm, self.config.rate_limit_margin)
            if self.config.max_rpm > 0
            else None
        )
        last: Exception | None = None
        for attempt in range(attempts):
            if limiter is not None:
                limiter.acquire()
            try:
                return call()
            except (_Transient, httpx.HTTPError) as exc:
                last = exc
                if attempt + 1 >= attempts:
                    break
                delay = self.config.retry_backoff * (attempt + 1)
                if isinstance(exc, _RateLimited):
                    delay = max(delay, self.config.rate_limit_backoff * (attempt + 1))
                time.sleep(delay)
        raise LLMError(f"Kunde inte nå LLM efter {attempts} försök: {last}") from last

    # -- Gemini via OpenAI-kompatibelt HTTP --------------------------------
    def _complete_http(self, system: str, user: str, *, json_mode: bool) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"

        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        resp = self._post(url, payload, headers)
        data = resp.json()
        self._record_usage(data.get("usage") or {})
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Oväntat LLM-svar: {json.dumps(data)[:300]}") from exc

    def _post(self, url: str, payload: dict, headers: dict) -> httpx.Response:
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=self.config.timeout)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429 or status >= 500:
                message = f"LLM-anropet avvisades tillfälligt ({status}): {exc.response.text[:200]}"
                if status == 429:
                    raise _RateLimited(message) from exc
                raise _Transient(message) from exc
            raise LLMError(
                f"LLM-anrop misslyckades ({status}): {exc.response.text[:300]}"
            ) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _Transient(f"Kunde inte nå LLM: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Kunde inte nå LLM: {exc}") from exc


def parse_json_object(text: str) -> dict[str, Any]:
    """Plocka ut ett JSON-objekt ur ett LLM-svar.

    Modellen ombeds svara med ren JSON, men vi tål en kodstaket eller
    omgivande text genom att leta upp det första balanserade objektet.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()

    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : i + 1])
                        if isinstance(value, dict):
                            return value
                    except json.JSONDecodeError:
                        break
    raise LLMError(f"Kunde inte tolka JSON ur LLM-svaret: {text[:200]}")
