"""Test för självläkning av LLM-profilen i agent-servern.

Agent-serverns LLM-profiler ligger i minnet och försvinner när containern
startas om. Då slutar modellnamnet ``openhands_<profil>`` att fungera med 404.
Klienten ska då skapa profilen på nytt och göra om anropet.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from mejeri.llm import LLMClient, LLMConfig


class _Handler(BaseHTTPRequestHandler):
    """Liten stubbe av agent-serverns profil- och chatt-API."""

    profiles: dict[str, str] = {}

    def log_message(self, *args):  # tysta testutskrifter
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw or b"{}")

        if self.path.startswith("/api/profiles/") and self.path.endswith("/activate"):
            name = self.path.split("/")[3]
            if name not in self.profiles:
                return self._send(404, {"detail": f"Profile '{name}' not found"})
            return self._send(200, {"name": name, "message": "activated"})

        if self.path.startswith("/api/profiles/"):
            name = self.path.split("/")[3]
            self.profiles[name] = data["llm"]["model"]
            return self._send(201, {"name": name, "message": "saved"})

        if self.path == "/v1/chat/completions":
            model = data["model"]
            name = model[len("openhands_"):] if model.startswith("openhands_") else ""
            if name and name not in self.profiles:
                return self._send(404, {"detail": f"Profile '{name}' not found"})
            return self._send(
                200,
                {
                    "choices": [{"message": {"role": "assistant", "content": '{"bid": 41}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )

        return self._send(404, {"detail": "not found"})


def _serve() -> tuple[HTTPServer, str]:
    _Handler.profiles = {}
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def test_missing_profile_is_recreated_and_call_retried():
    server, base = _serve()
    try:
        cfg = LLMConfig(provider="openhands", model="openhands_Default", base_url=base)
        client = LLMClient(cfg)
        assert _Handler.profiles == {}
        out = client.complete("system", "user")
        assert "41" in out
        # Klienten skapade profilen och pekade den på en konkret modell.
        assert "Default" in _Handler.profiles
        assert _Handler.profiles["Default"].startswith("openhands/")
    finally:
        server.shutdown()


def test_existing_profile_is_used_without_recreation():
    server, base = _serve()
    try:
        _Handler.profiles["Default"] = "openhands/deepseek-v4.1-flash"
        cfg = LLMConfig(provider="openhands", model="openhands_Default", base_url=base)
        out = LLMClient(cfg).complete("system", "user")
        assert "41" in out
    finally:
        server.shutdown()


def test_profile_name_parsed_from_model():
    cfg = LLMConfig(provider="openhands", model="openhands_Default")
    assert cfg.profile_name == "Default"
    assert LLMConfig(provider="anthropic", model="claude-sonnet-4-5").profile_name == ""
