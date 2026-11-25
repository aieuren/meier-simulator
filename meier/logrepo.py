"""Automatisk incheckning av matchloggar till ett separat GitHub-repo.

Varje matchserie skrivs som en egen JSONL-fil med datum och klockslag i
namnet, i en klon av loggrepet. Efter varje färdig match checkas filen in
(commit + push) så att resultatet finns kvar även om miljön rivs.

Token skickas till git via en credential-helper som läser den från en fil,
så att den aldrig hamnar på kommandoraden (och därmed inte i processlistan).

Miljövariabler:
    MEIER_LOGS_DIR         katalog för klonen (standard /workspace/meier-logs)
    MEIER_LOGS_REPO        GitHub-repo (standard aieuren/meier-simulator-logs)
    MEIER_LOGS_TOKEN_FILE  fil med åtkomsttoken
                           (standard /workspace/meier-secrets/logs.token)
    MEIER_LOGS_PUSH        "0" stänger av automatisk push
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

DEFAULT_DIR = "/workspace/meier-logs"
DEFAULT_REPO = "aieuren/meier-simulator-logs"
DEFAULT_TOKEN_FILE = "/workspace/meier-secrets/logs.token"
COMMIT_NAME = "Meier Bot"
COMMIT_EMAIL = "meier-bot@users.noreply.github.com"


class LogRepoError(RuntimeError):
    """Fel när loggrepet ska läsas eller uppdateras."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def logs_dir() -> Path:
    return Path(_env("MEIER_LOGS_DIR", DEFAULT_DIR))


def logs_repo() -> str:
    return _env("MEIER_LOGS_REPO", DEFAULT_REPO)


def remote_url() -> str:
    """Klonings-URL. Kan överstyras helt med MEIER_LOGS_REMOTE_URL."""
    override = _env("MEIER_LOGS_REMOTE_URL")
    if override:
        return override
    return f"https://github.com/{logs_repo()}.git"


def token_file() -> Path:
    return Path(_env("MEIER_LOGS_TOKEN_FILE", DEFAULT_TOKEN_FILE))


def push_enabled() -> bool:
    """Är automatisk push påslagen? (stäng av med MEIER_LOGS_PUSH=0)"""
    return _env("MEIER_LOGS_PUSH", "1").lower() not in ("0", "false", "no", "off")


_SERIES_STAMP = "%Y-%m-%d-%H%M%S"
_SERIES_STAMP_LEGACY = "%Y-%m-%d-%H%M"
#: Prefix som äldre seriefiler har. Nya filer är bara en tidsstämpel.
_SERIES_PREFIX = "meier-matcher-"


def series_filename(now: datetime | None = None) -> str:
    """Filnamn för en serie: ÅÅÅÅ-MM-DD-TTMMSS.jsonl."""
    stamp = (now or datetime.now()).strftime(_SERIES_STAMP)
    return f"{stamp}.jsonl"


#: Svenska månadsnamn för läsbara etiketter.
_MONTHS = (
    "januari", "februari", "mars", "april", "maj", "juni",
    "juli", "augusti", "september", "oktober", "november", "december",
)


def _parse_stamp(stamp: str) -> tuple[datetime, bool] | None:
    """Tidpunkt och om namnet har sekunder, ur en tidsstämpel."""
    for fmt, has_seconds in ((_SERIES_STAMP_LEGACY, False), (_SERIES_STAMP, True)):
        try:
            return datetime.strptime(stamp, fmt), has_seconds
        except ValueError:
            continue
    return None


def _series_stamp(name: str) -> str | None:
    """Tidsstämpeln ur ett seriefilnamn, gammalt eller nytt format."""
    if not name.endswith(".jsonl"):
        return None
    stem = name[: -len(".jsonl")]
    if stem.startswith(_SERIES_PREFIX):
        stem = stem[len(_SERIES_PREFIX):]
    return stem


def parse_series_time(name: str) -> datetime | None:
    """Tidpunkten ur ett seriefilnamn, eller None om namnet inte matchar.

    Accepterar både det nya namnet (bara tidsstämpel) och det äldre med
    prefixet ``meier-matcher-``, samt äldre stämplar utan sekunder, så att
    loggar från tidigare körningar får rätt etikett.
    """
    stamp = _series_stamp(name)
    if stamp is None:
        return None
    parsed = _parse_stamp(stamp)
    return parsed[0] if parsed else None


def series_label(name: str) -> str:
    """Läsbar etikett ur filnamnet: "12 november 2026, 02:46:13".

    Äldre namn utan sekunder visar bara timme och minut. Faller tillbaka på
    själva filnamnet om det inte går att tolka.
    """
    stamp = _series_stamp(name)
    if stamp is None:
        return name
    parsed = _parse_stamp(stamp)
    if parsed is None:
        return name
    when, has_seconds = parsed
    clock = f"{when:%H:%M:%S}" if has_seconds else f"{when:%H:%M}"
    return f"{when.day} {_MONTHS[when.month - 1]} {when.year}, {clock}"


class LogRepo:
    """Klonen av loggrepet: filnamn, commit och push."""

    def __init__(self, directory: Path | str | None = None, token_path: Path | str | None = None):
        self.directory = Path(directory) if directory else logs_dir()
        self.token_path = Path(token_path) if token_path else token_file()

    # -- status ------------------------------------------------------------
    @property
    def token(self) -> str:
        try:
            return self.token_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def configured(self) -> bool:
        """Finns en token så att vi kan autentisera mot GitHub?"""
        return bool(self.token)

    def is_repo(self) -> bool:
        return (self.directory / ".git").is_dir()

    def ready(self) -> bool:
        return self.configured() and self.is_repo()

    # -- git-hjälpare ------------------------------------------------------
    def _credential_config(self) -> tuple[str, ...]:
        # Helpern läser token från fil, så att själva token aldrig står på
        # kommandoraden (den skulle annars synas i `ps`).
        #
        # Tomt värde först nollställer listan av helpers. Git lägger annars
        # ihop alla helpers som finns (t.ex. OpenHands globala
        # git-credential-helper) och frågar dem i tur och ordning; den
        # globala svarar med en token som saknar rättighet till loggrepet och
        # då blir pushen 403 trots att vår egen token fungerar.
        helper = (
            '!f() { echo "username=x-access-token"; '
            f'echo "password=$(cat {self.token_path})"; }}; f'
        )
        return ("credential.helper=", f"credential.helper={helper}")

    def _git(self, *args: str, check: bool = True, config: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"  # fråga aldrig interaktivt
        # -c-flaggor måste stå före subkommandot.
        conf: list[str] = []
        for c in config:
            conf += ["-c", c]
        cmd = ["git", "-C", str(self.directory), *conf, *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if check and proc.returncode != 0:
            raise LogRepoError(proc.stderr.strip() or proc.stdout.strip() or "git misslyckades")
        return proc

    # -- klon --------------------------------------------------------------
    def ensure_clone(self) -> None:
        """Klona loggrepet om klonen saknas."""
        if self.is_repo():
            return
        if not self.configured():
            raise LogRepoError(f"Ingen åtkomsttoken hittad i {self.token_path}")
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        url = remote_url()
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        conf: list[str] = []
        for c in self._credential_config():
            conf += ["-c", c]
        proc = subprocess.run(
            ["git", *conf, "clone", url, str(self.directory)],
            capture_output=True,
            text=True,
            env=env,
        )
        if proc.returncode != 0:
            raise LogRepoError(proc.stderr.strip() or "git clone misslyckades")
        self._git("config", "user.name", COMMIT_NAME)
        self._git("config", "user.email", COMMIT_EMAIL)

    def sync(self) -> None:
        """Best-effort: hämta eventuella ändringar från fjärren före körning."""
        self._git("pull", "--rebase", "--autostash", check=False)

    # -- läsa loggar -------------------------------------------------------
    def list_logs(self, sync: bool = True) -> list[dict]:
        """Lista JSONL-filerna i klonen, nyaste först.

        Hämtar nya commits från fjärren först (om möjligt), så att loggar som
        checkats in från en annan körning också syns.
        """
        if not self.is_repo():
            return []
        if sync:
            self.sync()
        out: list[dict] = []
        for p in sorted(self.directory.glob("*.jsonl")):
            try:
                stat = p.stat()
            except OSError:
                continue
            out.append({
                "name": p.name,
                "label": series_label(p.name),
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
            })
        out.sort(key=lambda d: d["modified"], reverse=True)
        return out

    def log_path(self, name: str) -> Path:
        """Sökväg till en logg i klonen. Skyddar mot sökvägar utanför klonen."""
        if not name or Path(name).name != name or not name.endswith(".jsonl"):
            raise LogRepoError(f"Ogiltigt loggnamn: {name!r}")
        path = self.directory / name
        if not path.is_file():
            raise LogRepoError(f"Loggen finns inte: {name}")
        return path

    # -- commit och push ---------------------------------------------------
    def commit_and_push(self, path: Path, message: str) -> str:
        """Checka in ``path`` och pusha. Returnerar en statusrad (fel kastas ej)."""
        try:
            self._git("add", "--", str(path))
            staged = self._git("diff", "--cached", "--quiet", check=False)
            if staged.returncode == 0:
                return "Inga ändringar att checka in."
            self._git(
                "commit", "-q", "-m", message,
                config=(f"user.name={COMMIT_NAME}", f"user.email={COMMIT_EMAIL}"),
            )
        except LogRepoError as exc:
            return f"Incheckning misslyckades: {exc}"
        return self._push_with_retry()

    def _push_with_retry(self) -> str:
        try:
            self._git("push", "origin", "HEAD", config=self._credential_config())
            return "Incheckat och pushat."
        except LogRepoError as exc:
            # Vanligaste orsaken är att fjärren hunnit få nya commits: hämta
            # och försök en gång till innan vi ger upp.
            self._git("pull", "--rebase", "--autostash", check=False)
            try:
                self._git("push", "origin", "HEAD", config=self._credential_config())
                return "Incheckat och pushat (efter omsynk)."
            except LogRepoError as exc2:
                return f"Push misslyckades: {exc2 or exc}"
