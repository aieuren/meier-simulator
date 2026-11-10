"""E-postavisering när en matchserie är klar.

Modulen skickar resultatfilen (JSONL) som bilaga via SMTP. Den är opt-in:
utan ``MEJER_SMTP_HOST`` och en mottagare (``MEJER_MAIL_TO`` eller en adress i
anropet) gör den ingenting. Ett fel här ska aldrig fälla själva körningen, så
anroparen fångar ``MailError`` och rapporterar den vid sidan av resultatet.

Miljövariabler:
    MEJER_SMTP_HOST     SMTP-server (krävs för att skicka)
    MEJER_SMTP_PORT     port (standard 587, eller 465 för implicit TLS)
    MEJER_SMTP_USER     användarnamn
    MEJER_SMTP_PASSWORD lösenord (eller app-lösenord)
    MEJER_MAIL_FROM     avsändare (standard: MEJER_SMTP_USER)
    MEJER_MAIL_TO       standardmottagare, kommaseparerad
    MEJER_SMTP_TLS      "0" stänger av STARTTLS (för testservrar)
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


class MailError(RuntimeError):
    """Fel när e-post ska skickas."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def mail_configured() -> bool:
    """Finns det tillräckligt med inställningar för att kunna skicka?"""
    return bool(_env("MEJER_SMTP_HOST") and (_env("MEJER_MAIL_TO") or _env("MEJER_MAIL_FROM")))


def _recipients(to: str) -> list[str]:
    return [addr.strip() for addr in to.replace(";", ",").split(",") if addr.strip()]


def _smtp_port() -> int:
    try:
        return int(_env("MEJER_SMTP_PORT", "587") or "587")
    except ValueError as exc:
        raise MailError("MEJER_SMTP_PORT är inte ett tal") from exc


def _build_message(
    *, sender: str, to: list[str], subject: str, body: str, attachment: Path | None
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment is not None and attachment.exists():
        data = attachment.read_bytes()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="x-ndjson",
            filename=attachment.name,
        )
    return msg


def send_matches(
    path: str | Path,
    *,
    subject: str,
    body: str,
    to: str | None = None,
    smtp_factory=None,
) -> list[str]:
    """Skicka ``path`` som bilaga till mottagarna. Returnerar mottagarlistan.

    ``to`` ersätter standardmottagaren från miljön. ``smtp_factory`` används
    av testerna för att byta ut den riktiga SMTP-klienten.
    """
    host = _env("MEJER_SMTP_HOST")
    if not host:
        raise MailError("MEJER_SMTP_HOST saknas")

    recipients = _recipients(to or _env("MEJER_MAIL_TO"))
    if not recipients:
        raise MailError("Ingen mottagare (MEJER_MAIL_TO eller 'to' i anropet)")

    sender = _env("MEJER_MAIL_FROM") or _env("MEJER_SMTP_USER")
    if not sender:
        raise MailError("Ingen avsändare (MEJER_MAIL_FROM eller MEJER_SMTP_USER)")

    port = _smtp_port()
    user = _env("MEJER_SMTP_USER")
    password = os.environ.get("MEJER_SMTP_PASSWORD", "")
    use_ssl = port == 465
    use_tls = _env("MEJER_SMTP_TLS", "1") not in ("0", "false", "no")

    msg = _build_message(
        sender=sender,
        to=recipients,
        subject=subject,
        body=body,
        attachment=Path(path) if path else None,
    )

    factory = smtp_factory or (smtplib.SMTP_SSL if use_ssl else smtplib.SMTP)
    try:
        with factory(host, port, timeout=30) as smtp:
            if use_tls and not use_ssl:
                smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"Kunde inte skicka e-post: {exc}") from exc

    return recipients


def summary_body(summary: dict | None, *, count: int, file_name: str) -> str:
    """Kort, läsbar sammanfattning av en matchserie för mejlets brödtext."""
    lines = ["Mejer-körningen är klar.", ""]
    if summary:
        lines.append(f"Matcher: {summary.get('games', count)}")
        lines.append(f"Snitt antal rundor per match: {summary.get('avg_rounds', '?')}")
        winners = summary.get("winner_counts") or {}
        if winners:
            lines.append("")
            lines.append("Vinster per roll:")
            for role, wins in sorted(winners.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {role}: {wins}")
        roles = summary.get("roles") or {}
        if roles:
            lines.append("")
            lines.append("Vinstfrekvens per roll:")
            for role, stats in sorted(
                roles.items(), key=lambda kv: -kv[1].get("win_rate", 0)
            ):
                rate = round(100 * stats.get("win_rate", 0))
                lines.append(
                    f"  {stats.get('name', role)} ({role}): {rate}% "
                    f"av {stats.get('games', 0)} matcher"
                )
    else:
        lines.append(f"Matcher: {count}")
    lines.append("")
    lines.append(f"Hela protokollet ligger i bilagan: {file_name}")
    lines.append("")
    lines.append("-- Mejer-simulatorn")
    return "\n".join(lines)
