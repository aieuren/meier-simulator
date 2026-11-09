"""LLM-klient för Mejeri-agenterna.

Klienten föredrar ett riktigt Anthropic-konto (Claude) via ``ANTHROPIC_API_KEY``.
Saknas den faller den tillbaka på OpenHands agent-server-proxyn, som finns i
Agent Canvas-miljön. Båda talar OpenAI-liknande ``/v1/chat/completions``, men
Anthropic används via sin egen SDK när nyckeln finns.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx


class LLMError(RuntimeError):
    """Fel vid anrop mot språkmodellen."""


class _MissingProfile(LLMError):
    """Agent-servern saknar LLM-profilen som modellnamnet pekar på."""


@dataclass
class LLMConfig:
    """Konfiguration för en LLM-anslutning."""

    provider: str  # "anthropic" eller "openhands"
    model: str
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 1024
    temperature: float = 0.7
    timeout: float = 120.0

    @property
    def profile_name(self) -> str:
        """Profilnamn i agent-servern för ett ``openhands_<namn>``-modellnamn."""
        prefix = "openhands_"
        return self.model[len(prefix):] if self.model.startswith(prefix) else ""


    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Välj anslutning utifrån miljövariabler.

        Prioritet:
        1. Anthropic (Claude-kontot) via ``ANTHROPIC_API_KEY``.
        2. OpenHands agent-server-proxy (Agent Canvas).
        """
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if anthropic_key:
            return cls(
                provider="anthropic",
                model=os.environ.get("MEJERI_MODEL", "claude-sonnet-4-5"),
                api_key=anthropic_key,
                base_url=os.environ.get("ANTHROPIC_BASE_URL", ""),
            )

        # Agent-servern på localhost proxar den hanterade nyckeln och kräver
        # endast sessionsnyckeln i X-Session-API-Key.
        base_url = os.environ.get("MEJERI_BASE_URL", "http://127.0.0.1:60000")
        model = os.environ.get("MEJERI_MODEL", "openhands_Default")
        return cls(provider="openhands", model=model, base_url=base_url)


def _session_api_key() -> str:
    """Hämta Agent Canvas sessionsnyckel utan att skriva ut den."""
    key = os.environ.get("SESSION_API_KEY", "")
    if key:
        return key
    for path in ("/proc/1/environ", "/proc/self/environ"):
        try:
            with open(path, "rb") as fh:
                for entry in fh.read().split(b"\0"):
                    if entry.startswith(b"SESSION_API_KEY="):
                        return entry.split(b"=", 1)[1].decode()
        except OSError:
            continue
    return ""


@dataclass
class LLMClient:
    """Tunn klient som skickar en system- och en användarprompt."""

    config: LLMConfig = field(default_factory=LLMConfig.from_env)

    #: Tokenräkning från det senaste anropet (prompt/completion/total).
    last_usage: dict[str, int] = field(default_factory=dict, init=False)

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if self.config.provider == "anthropic":
            return self._complete_anthropic(system, user)
        return self._complete_openhands(system, user, json_mode=json_mode)

    # -- Anthropic (Claude-kontot) ------------------------------------------
    def _complete_anthropic(self, system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("anthropic-paketet saknas: pip install anthropic") from exc

        kwargs: dict[str, Any] = {"api_key": self.config.api_key}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url

        client = anthropic.Anthropic(**kwargs)
        try:
            resp = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # pragma: no cover - nätverksberoende
            raise LLMError(f"Anthropic-anrop misslyckades: {exc}") from exc

        parts = [block.text for block in resp.content if getattr(block, "type", "") == "text"]
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self.last_usage = {
                "prompt_tokens": getattr(usage, "input_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
            self.last_usage["total_tokens"] = (
                self.last_usage["prompt_tokens"] + self.last_usage["completion_tokens"]
            )
        return "".join(parts).strip()

    # -- OpenHands agent-server-proxy ---------------------------------------
    def _complete_openhands(self, system: str, user: str, *, json_mode: bool) -> str:
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
        if self.config.provider == "openhands":
            headers["X-Session-API-Key"] = _session_api_key()
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        try:
            resp = self._post(url, payload, headers)
        except _MissingProfile:
            # Agent-servern tappar sina LLM-profiler vid omstart. Skapa profilen
            # på nytt och gör om anropet en gång.
            self._ensure_profile(base)
            try:
                resp = self._post(url, payload, headers)
            except _MissingProfile as exc:
                raise LLMError(str(exc)) from exc

        data = resp.json()
        self.last_usage = {
            k: int(v)
            for k, v in (data.get("usage") or {}).items()
            if isinstance(v, (int, float))
        }
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
            if exc.response.status_code == 404 and self.config.profile_name:
                try:
                    detail = exc.response.json().get("detail", "")
                except ValueError:
                    detail = ""
                if "not found" in str(detail):
                    raise _MissingProfile(
                        f"LLM-profilen '{self.config.profile_name}' saknas i agent-servern"
                    ) from exc
            raise LLMError(
                f"LLM-anrop misslyckades ({exc.response.status_code}): {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Kunde inte nå LLM: {exc}") from exc

    def _ensure_profile(self, base: str) -> None:
        """Skapa och aktivera LLM-profilen som modellnamnet pekar på.

        Agent-serverns profiler ligger i minnet och försvinner när containern
        startas om. Profilen pekar i sin tur på en konkret modell
        (``MEJERI_PROFILE_MODEL``, standard ``openhands/deepseek-v4.1-flash``).
        """
        name = self.config.profile_name
        if not name:
            return
        target = os.environ.get("MEJERI_PROFILE_MODEL", "openhands/deepseek-v4.1-flash")
        headers = {"Content-Type": "application/json", "X-Session-API-Key": _session_api_key()}
        body = {"llm": {"model": target}, "include_secrets": True}
        try:
            httpx.post(f"{base}/api/profiles/{name}", json=body, headers=headers, timeout=30)
            httpx.post(f"{base}/api/profiles/{name}/activate", json={}, headers=headers, timeout=30)
        except httpx.HTTPError as exc:
            raise LLMError(f"Kunde inte återskapa LLM-profilen '{name}': {exc}") from exc


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
