"""Tester för e-postaviseringen (utan riktig SMTP-server)."""

from __future__ import annotations

import pytest

from mejer import notify


class FakeSMTP:
    """Fångar det som skickas i stället för att prata med en SMTP-server."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.started_tls = False
        self.logged_in = None
        self.message = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.message = msg


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "MEJER_SMTP_HOST",
        "MEJER_SMTP_PORT",
        "MEJER_SMTP_USER",
        "MEJER_SMTP_PASSWORD",
        "MEJER_MAIL_FROM",
        "MEJER_MAIL_TO",
        "MEJER_SMTP_TLS",
    ):
        monkeypatch.delenv(name, raising=False)
    FakeSMTP.instances = []
    yield


def test_mail_not_configured_without_host():
    assert notify.mail_configured() is False


def test_mail_configured_with_host_and_to(monkeypatch):
    monkeypatch.setenv("MEJER_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MEJER_MAIL_TO", "a@example.com")
    assert notify.mail_configured() is True


def test_send_without_host_raises():
    with pytest.raises(notify.MailError):
        notify.send_matches("x.jsonl", subject="s", body="b", to="a@example.com")


def test_send_attaches_file_and_uses_starttls(tmp_path, monkeypatch):
    payload = tmp_path / "mejer-matcher.jsonl"
    payload.write_text('{"game": 1}\n', encoding="utf-8")
    monkeypatch.setenv("MEJER_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MEJER_SMTP_PORT", "587")
    monkeypatch.setenv("MEJER_SMTP_USER", "me@example.com")
    monkeypatch.setenv("MEJER_SMTP_PASSWORD", "secret")

    sent = notify.send_matches(
        payload,
        subject="Klart",
        body="Hej",
        to="boss@example.com",
        smtp_factory=FakeSMTP,
    )

    assert sent == ["boss@example.com"]
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    assert smtp.started_tls is True
    assert smtp.logged_in == ("me@example.com", "secret")
    msg = smtp.message
    assert msg["To"] == "boss@example.com"
    assert msg["Subject"] == "Klart"
    attachments = [p for p in msg.iter_attachments()]
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "mejer-matcher.jsonl"
    assert attachments[0].get_payload(decode=True) == b'{"game": 1}\n'


def test_send_without_recipient_raises(monkeypatch):
    monkeypatch.setenv("MEJER_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MEJER_SMTP_USER", "me@example.com")
    with pytest.raises(notify.MailError):
        notify.send_matches("x.jsonl", subject="s", body="b")


def test_implicit_tls_on_port_465(monkeypatch, tmp_path):
    monkeypatch.setenv("MEJER_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MEJER_SMTP_PORT", "465")
    monkeypatch.setenv("MEJER_SMTP_USER", "me@example.com")
    monkeypatch.setenv("MEJER_MAIL_TO", "a@example.com")
    notify.send_matches(tmp_path / "f.jsonl", subject="s", body="b", smtp_factory=FakeSMTP)
    smtp = FakeSMTP.instances[0]
    # Implicit TLS: ingen separat starttls behövs.
    assert smtp.started_tls is False


def test_summary_body_lists_winners():
    summary = {
        "games": 3,
        "avg_rounds": 8.5,
        "winner_counts": {"trygg": 2, "rackar": 1},
        "roles": {
            "trygg": {"name": "Trygge-Tor", "win_rate": 0.66, "games": 3},
        },
    }
    body = notify.summary_body(summary, count=3, file_name="mejer-matcher.jsonl")
    assert "Mejer-körningen är klar" in body
    assert "trygg: 2" in body
    assert "Trygge-Tor" in body
    assert "mejer-matcher.jsonl" in body
