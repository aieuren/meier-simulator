"""FastAPI-webbapp för Meier-agenterna.

Webbappen låter dig skriva in tärningsutfallet (två tärningar) och få
spelarens svar från en LLM-baserad agent. Du kan välja roll och ange ett
tidigare påstående om spelaren slår efter någon annan.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import rules
from ..agents.roster import ROSTER, make_player, make_players, role_keys
from ..llm import LLMClient, LLMError
from ..match import (
    GameRecord,
    match_brief,
    match_detail,
    read_jsonl,
    run_matches,
    summarize,
)
from ..opponents import OpponentTracker, describe_params
from ..session import Session
from .. import analysis, logrepo, quota

STATIC_DIR = Path(__file__).parent / "static"
RULES_PDF = Path(__file__).resolve().parents[2] / "docs" / "regler" / "meier-regler.pdf"

app = FastAPI(title="Meier-agenten", version="2.0.0")

# En agent per roll, skapade på begäran så att LLM-klienten återanvänds.
_agents: dict[str, object] = {}

# Den aktiva interaktiva sessionen (en åt gången).
_session: Session | None = None

# Senaste batchkörningen av matcher (för nedladdning och statistik).
#
# Filen måste ligga i /workspace: containern startar om efter 20 minuters
# inaktivitet, och då nollställs /tmp och /home. En serie som bara skrevs till
# /tmp försvann vid omstarten, utan att något fel syntes förrän sidan sökte
# status. Standard är nu en egen katalog under /workspace, skild från
# loggrepets klon.
def _local_log_dir() -> Path:
    """Katalog för lokala seriefiler som inte checkas in.

    Läses vid anrop, inte vid import, så att ``MEIER_LOCAL_LOG_DIR`` och
    ``MEIER_LOGS_DIR`` kan sättas i efterhand (t.ex. i tester).

    Katalogen ligger **utanför** loggrepets klon. Låg den i klonen skulle
    lokala, ej incheckade serier dyka upp i analysen som om de vore
    incheckade, och de skulle skräpa ner git-arbetskatalogen.
    """
    return Path(
        os.environ.get("MEIER_LOCAL_LOG_DIR")
        or "/workspace/meier-runs"
    )


_current_match_file: Path = _local_log_dir() / "meier_matches.jsonl"

#: Pekfil med senaste serien. Servern tappar allt i minnet vid omstart, men
#: filen ligger kvar i /workspace. Utan pekfil svarar status 404 och serien ser
#: förlorad ut fast den finns på disk.
_LAST_SERIES = "last-series.json"

_restored = False


def _last_series_path() -> Path:
    return _local_log_dir() / _LAST_SERIES


def _remember_series(path: Path, count: int, started_at: float | None = None) -> None:
    """Skriv pekfil så att serien hittas igen efter en omstart."""
    _write_series_pointer(
        {
            "file": str(path),
            "count": count,
            "started_at": started_at if started_at is not None else time.time(),
        }
    )


def _write_series_pointer(data: dict) -> None:
    try:
        _last_series_path().parent.mkdir(parents=True, exist_ok=True)
        _last_series_path().write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        # Pekfilen är en bekvämlighet. Går den inte att skriva får serien
        # fortfarande sin loggfil, och den syns i analysen.
        pass


def _remember_series_end(finished_at: float) -> None:
    """Spara sluttiden i pekfilen, så tiderna finns kvar efter omstart."""
    info = _last_series_info()
    if not info:
        return
    info["finished_at"] = finished_at
    _write_series_pointer(info)


def _restore_last_series() -> None:
    """Läs pekfilen en gång och peka om till serien från förra körningen."""
    global _current_match_file, _restored
    if _restored:
        return
    _restored = True
    try:
        data = json.loads(_last_series_path().read_text(encoding="utf-8"))
        path = Path(data["file"])
    except (OSError, ValueError, KeyError, TypeError):
        return
    if path.is_file():
        _current_match_file = path


def _last_series_count() -> int:
    """Antalet matcher i serien enligt pekfilen, annars 0."""
    try:
        return int(_last_series_info().get("count") or 0)
    except (TypeError, ValueError):
        return 0


def _last_series_info() -> dict:
    """Innehållet i pekfilen, eller en tom dict om den saknas."""
    try:
        data = json.loads(_last_series_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _match_file() -> Path:
    _restore_last_series()
    return _current_match_file


def _get_agent(role_key: str):
    if role_key not in _agents:
        _agents[role_key] = _build_agent(role_key)
    return _agents[role_key]


def _build_agent(role_key: str):
    """Bygg spelaren för webbappen.

    Axel är regelspelare och får ingen klient. Övriga roller är LLM-spelare och
    kräver en: utan den avbryts matchen i stället för att tyst spela vidare på
    räkneregeln.
    """
    from ..agents.roster import get_profile

    if not get_profile(role_key).uses_llm:
        return make_player(role_key)
    return make_player(role_key, llm=LLMClient())


class AnnounceRequest(BaseModel):
    die1: int = Field(..., ge=1, le=6, description="Första tärningen")
    die2: int = Field(..., ge=1, le=6, description="Andra tärningen")
    role: str = Field("cecilia", description="Agentens roll")
    previous_claim: int | None = Field(
        None, description="Tidigare påstående om spelaren slår efter någon annan"
    )


class DecideRequest(BaseModel):
    claim: int = Field(..., description="Motståndarens påstående")
    role: str = Field("cecilia", description="Agentens roll")
    lives: int = Field(3, ge=0, le=3)


@app.get("/")
def index() -> FileResponse:
    # Ingen cachning: filerna ändras ofta och gamla kopior gav "undefined" i UI:t.
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@app.get("/regler.pdf")
def rules_pdf() -> FileResponse:
    """Reglerna som PDF, så de går att läsa utan att lämna appen."""
    return FileResponse(
        RULES_PDF,
        media_type="application/pdf",
        filename="meier-regler.pdf",
    )


class NoCacheStaticFiles(StaticFiles):
    """Serverar statiska filer utan cachning så att UI:t alltid är färskt."""

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


@app.get("/api/roles")
def list_roles() -> dict:
    return {
        "roles": [
            {
                "key": p.key,
                "name": p.name,
                "description": p.description,
                "uses_llm": p.uses_llm,
                "params": {
                    "caution": p.params.caution,
                    "statistics": p.params.statistics,
                    "unpredictability": p.params.unpredictability,
                    "reading": p.params.reading,
                },
                "style_text": describe_params(
                    p.params.caution,
                    p.params.statistics,
                    p.params.unpredictability,
                    p.params.reading,
                ),
            }
            for p in ROSTER.values()
        ],
        "ranking": [{"value": v, "name": rules.name(v)} for v in rules.RANKING],
    }


@app.post("/api/announce")
def announce(req: AnnounceRequest) -> dict:
    """Givet ett tärningsutfall: hur svarar spelaren?"""
    if req.role not in ROSTER:
        raise HTTPException(status_code=400, detail=f"Okänd roll: {req.role}")
    try:
        shown = rules.read_dice(req.die1, req.die2)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.previous_claim is not None and not rules.is_valid_value(req.previous_claim):
        raise HTTPException(status_code=400, detail=f"Ogiltigt tidigare påstående: {req.previous_claim}")

    agent = _get_agent(req.role)
    try:
        if req.previous_claim is None:
            # Rundans första påstående: spelaren har tittat i smyg.
            ann = agent.announce((req.die1, req.die2))
        elif rules.is_meier(req.previous_claim):
            # Meier går inte att höja. Reglerna låter i stället hållaren slå om
            # och börja en ny runda, så det finns inget slag att svara på här.
            raise HTTPException(
                status_code=400,
                detail=(
                    "21 – Meier går inte att höja. I spelet slår hållaren om "
                    "bägaren och börjar en ny runda i stället."
                ),
            )
        else:
            # Ett slag efter ett tidigare påstående. Spelaren får lyfta på locket
            # och avgör själv om den vill det.
            ann = agent.announce_shake(
                (req.die1, req.die2), previous_claim=req.previous_claim
            )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fel: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "shown": shown,
        "shown_name": rules.name(shown),
        "previous_claim": req.previous_claim,
        "announcement": ann.to_dict(),
    }


@app.post("/api/decide")
def decide(req: DecideRequest) -> dict:
    """Givet en motståndares påstående: slår, synar eller skickar spelaren vidare?"""
    if req.role not in ROSTER:
        raise HTTPException(status_code=400, detail=f"Okänd roll: {req.role}")
    if not rules.is_valid_value(req.claim):
        raise HTTPException(status_code=400, detail=f"Ogiltigt påstående: {req.claim}")

    agent = _get_agent(req.role)
    try:
        decision = agent.decide(req.claim, lives=req.lives)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fel: {exc}") from exc

    result = decision.to_dict()
    if decision.action == "syna":
        # Vad som händer vid en syn beror på de dolda tärningarna; visa regeln.
        result["note"] = (
            "Vid syn: visar tärningarna lägre än påståendet förlorar den som påstod, "
            "annars förlorar den som synar. Meier kostar dubbelt."
        )
    elif decision.action == "slå":
        result["note"] = (
            "Vid slag: bägaren skakas om utan att spelaren tittar, och nästa påstående måste vara högre, "
            "oavsett vad tärningarna visar."
        )
    else:
        result["note"] = (
            "Vid skicka vidare: påståendet står kvar och spelaren tar över ansvaret "
            "för det. Bägaren går vidare utan att slås om."
        )
    return result


@app.get("/api/health")
def health() -> dict:
    """Appen svarar även utan LLM-nyckel; då är llm false och modellen null.

    run.sh, SessionStart-kroken och Canvas-panelen avgör om appen kör med
    hjälp av den här slutpunkten. En 500 på grund av en saknad nyckel skulle
    få dem att tro att appen är nere och starta om den i tid och otid, trots
    att regelbaserat spel fungerar.
    """
    try:
        cfg = LLMClient().config
    except LLMError:
        return {"status": "ok", "llm": False, "provider": None, "model": None}
    return {"status": "ok", "llm": True, "provider": cfg.provider, "model": cfg.model}


# -- Interaktiv spelsession ------------------------------------------------


class NewSessionRequest(BaseModel):
    roles: list[str] = Field(
        default_factory=role_keys,
        description="Roller som spelar. Standard: alla fem.",
    )


def _require_session() -> Session:
    if _session is None:
        raise HTTPException(status_code=404, detail="Ingen aktiv session. Skapa en först.")
    return _session


@app.post("/api/session/new")
def session_new(req: NewSessionRequest) -> dict:
    """Skapa en ny session: slumpad ordning och första tärningsslag."""
    global _session
    roles = req.roles or role_keys()
    for key in roles:
        if key not in ROSTER:
            raise HTTPException(status_code=400, detail=f"Okänd roll: {key}")
    if len(roles) < 2:
        raise HTTPException(status_code=400, detail="Minst två roller krävs")

    players = [_get_agent(key) for key in roles]
    tracker = OpponentTracker()
    for p in players:
        if getattr(p, "params", None) is not None and p.params.reading > 0.0:
            p.tracker = tracker
    _session = Session.new(players)
    _session.tracker = tracker
    return _session.to_dict()


@app.get("/api/session")
def session_state() -> dict:
    """Hämta hela sessionens tillstånd, inklusive loggen."""
    return _require_session().to_dict()


@app.post("/api/session/advance")
def session_advance() -> dict:
    """Bekräfta (OK) det aktuella steget och utför det."""
    session = _require_session()
    try:
        session.advance()
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fel: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_dict()


@app.post("/api/session/run")
def session_run() -> dict:
    """Kör hela flödet fram till en syn (stänger av grinden)."""
    session = _require_session()
    try:
        session.run_to_call()
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fel: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_dict()


@app.post("/api/session/round")
def session_round() -> dict:
    """Kör flödet fram till rundans slut (en syn eller en ny runda)."""
    session = _require_session()
    try:
        session.run_to_round_end()
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fel: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_dict()


@app.post("/api/session/end")
def session_end() -> dict:
    """Spela hela matchen klart, tills någon står kvar som vinnare."""
    session = _require_session()
    try:
        session.run_to_end()
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fel: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_dict()


@app.post("/api/session/stop")
def session_stop() -> dict:
    session = _require_session()
    session.stop()
    return session.to_dict()


# -- Batchkörning: många matcher för statistik -----------------------------
#
# En match är hundratals LLM-anrop och tar minuter. Att köra hela serien i en
# synkron HTTP-begäran skulle blockera i upp till en timme. Därför körs serien i
# en bakgrundstråd och klienten följer den med statuspollning.


class MatchRequest(BaseModel):
    roles: list[str] = Field(
        default_factory=role_keys,
        description="Roller som spelar. Standard: alla fyra.",
    )
    count: int = Field(5, ge=1, le=200, description="Antal matcher")
    lives: int = Field(3, ge=1, le=10)
    workers: int = Field(
        3, ge=1, le=8, description="Antal matcher som spelas samtidigt"
    )
    with_llm: bool = Field(
        True,
        description=(
            "Låt agenterna använda språkmodellen. False ger ett snabbt, "
            "deterministiskt läge utan LLM-anrop och utan kvotförbrukning."
        ),
    )
    check_in: bool = Field(
        True,
        description=(
            "Checka in loggfilen till loggrepet på GitHub efter varje match. "
            "Alltid på: serier ska hamna i git, inte bara på disk. Fältet finns "
            "kvar för äldre klienter men styr inget — servern checkar alltid in."
        ),
    )


class _MatchJob:
    """Ett bakgrundsjobb som spelar en serie matcher."""

    def __init__(
        self,
        roles: list[str],
        count: int,
        lives: int,
        workers: int = 1,
        check_in: bool = False,
        with_llm: bool = True,
    ):
        self.roles = roles
        self.count = count
        self.lives = lives
        self.workers = workers
        self.check_in = check_in
        self.with_llm = with_llm
        self.done = 0
        self.records: list[GameRecord] = []
        #: Matcher som inte kunde spelas klart. Serien fortsätter ändå.
        self.failures: list[dict] = []
        self.error: str | None = None
        self.push_status: str | None = None
        #: När serien startade och när sista matchen var klar (epoch-sekunder).
        self.started_at = time.time()
        self.finished_at: float | None = None
        #: Pågående matcher: {"game", "round", "alive"}. En match tar minuter,
        #: så statusraden behöver något som rör sig medan den spelas.
        self.live: dict[int, dict] = {}
        self.file: Path = _current_match_file
        self.running = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _open_log(self) -> tuple[Path, logrepo.LogRepo | None]:
        """Välj fil för serien och en loggreps-klon.

        Incheckning är alltid på: serier ska hamna i git. Går den inte att
        starta (token saknas, fjärren onåbar, MEIER_LOGS_PUSH=0) sparas serien
        i stället lokalt i /workspace, och statusraden säger var.
        """
        global _current_match_file
        repo: logrepo.LogRepo | None = None
        if not logrepo.push_enabled():
            # MEIER_LOGS_PUSH=0 stänger av incheckningen på riktigt. Det är en
            # nödbroms för tester och för en trasig fjärr, inte ett val i UI:t.
            self.push_status = "Incheckning avstängd (MEIER_LOGS_PUSH=0)."
        else:
            repo = logrepo.LogRepo()
            try:
                repo.ensure_clone()
                repo.sync()
            except logrepo.LogRepoError as exc:
                self.push_status = f"Incheckning avstängd: {exc}"
                repo = None
        if repo is not None:
            path = repo.directory / logrepo.series_filename()
        else:
            path = _local_log_dir() / logrepo.series_filename()
            # En lokal serie får eget namn, så att en ny körning inte skriver
            # över den förra. Incheckade serier har redan datum i namnet.
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.push_status = f"Kunde inte skapa {path.parent}: {exc}"
            if self.push_status and not self.push_status.startswith("Incheckning avstängd (MEIER_LOGS_PUSH"):
                # Incheckningen gick inte att starta. Säg var serien hamnar i
                # stället, så att den går att hitta efter en omstart.
                self.push_status = f"{self.push_status} Serien sparas lokalt i {path.parent}"
        self.file = path
        _current_match_file = path
        _remember_series(path, self.count, self.started_at)
        return path, repo

    def _run(self) -> None:
        try:
            path, repo = self._open_log()
            # Skriv protokollet radvis medan serien spelas, så att nedladdningen
            # fungerar även innan hela serien är klar.
            with open(path, "w", encoding="utf-8") as fh:
                for rec in run_matches(
                    self.roles,
                    self.count,
                    lives=self.lives,
                    workers=self.workers,
                    with_llm=self.with_llm,
                    on_match_progress=self._on_match_progress,
                ):
                    data = rec.to_dict()
                    with self.lock:
                        if data.get("failed"):
                            self.failures.append(data)
                        else:
                            self.records.append(rec)
                        self.done += 1
                        self.live.pop(data.get("game") or 0, None)
                    fh.write(json.dumps(data, ensure_ascii=False) + "\n")
                    fh.flush()
                    if repo is not None and not data.get("failed"):
                        self._check_in(repo, rec)
        except Exception as exc:  # pragma: no cover - skyddsnät
            self.error = f"Oväntat fel: {exc}"
        finally:
            with self.lock:
                self.finished_at = time.time()
                self.live.clear()
            _remember_series_end(self.finished_at)
            self.running = False

    def _on_match_progress(self, game: int, round_no: int, alive: int) -> None:
        """En match har bytt runda. Spara läget så statusraden kan visa det."""
        with self.lock:
            self.live[game] = {"game": game, "round": round_no, "alive": alive}

    def _check_in(self, repo: logrepo.LogRepo, rec: GameRecord) -> None:
        """Commit + push efter en färdig match. Får aldrig fälla körningen."""
        winner = rec.winner_role or rec.winner
        msg = f"Meier: match {self.done}/{self.count} klar (vinnare {winner})"
        status = repo.commit_and_push(self.file, msg)
        if not status.startswith(("Incheckat", "Inga ändringar")):
            # Datan ligger kvar i den lokala klonen. Säg det, så att ett
            # misslyckat push inte ser ut som en förlorad serie.
            status = f"{status} Serien finns kvar lokalt: {self.file}"
        with self.lock:
            self.push_status = status

    def status(self) -> dict:
        with self.lock:
            # Matcherna spelas parallellt och blir klara i olika ordning.
            # Visa dem i matchnummer, så att listan blir läsbar.
            snapshot = [rec.to_dict() for rec in sorted(self.records, key=lambda r: r.game)]
            failures = list(self.failures)
            live = sorted(self.live.values(), key=lambda m: m["game"])
            started_at = self.started_at
            finished_at = self.finished_at
        summary = summarize(snapshot + failures) if snapshot or failures else None
        return {
            "running": self.running,
            "done": self.done,
            "count": self.count,
            "error": self.error,
            "push_status": self.push_status,
            "file": self.file.name,
            "games": len(snapshot),
            "failures": failures,
            "records": snapshot,
            "summary": summary,
            "live": live,
            "started_at": started_at,
            "finished_at": finished_at,
            "download_url": "/api/matches/download",
            # Detaljvyn hämtar händelserna per match härifrån, i stället för
            # att få alla 1800 händelser i varje statuspoll.
            "source": self.file.name,
        }


_match_job: _MatchJob | None = None


@app.post("/api/matches/run")
def matches_run(req: MatchRequest) -> dict:
    """Starta en serie matcher i bakgrunden. Följ den med /api/matches/status."""
    global _match_job
    roles = req.roles or role_keys()
    for key in roles:
        if key not in ROSTER:
            raise HTTPException(status_code=400, detail=f"Okänd roll: {key}")
    if len(roles) < 2:
        raise HTTPException(status_code=400, detail="Minst två roller krävs")
    if _match_job is not None and _match_job.running:
        raise HTTPException(status_code=409, detail="En matchserie kör redan.")

    _match_job = _MatchJob(
        roles, req.count, req.lives, req.workers,
        check_in=req.check_in,
        with_llm=req.with_llm,
    )
    _match_job.thread.start()
    return _match_job.status()


@app.get("/api/matches/status")
def matches_status() -> dict:
    """Läget för den senaste (eller pågående) matchserien.

    Efter en omstart finns inget jobb i minnet. Då läses serien tillbaka från
    filen i stället, så att status, nedladdning och sammanfattning fortsätter
    fungera. Tidigare gavs 404 och serien såg förlorad ut fast den låg kvar.
    """
    if _match_job is None:
        return _status_from_file()
    return _match_job.status()


def _status_from_file() -> dict:
    """Bygg en statusrad ur den senaste seriefilen, för visning efter omstart."""
    path = _match_file()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Ingen matchserie startad.")
    records: list[dict] = []
    failures: list[dict] = []
    for rec in read_jsonl(path):
        (failures if rec.get("failed") else records).append(rec)
    # Filen skrivs i den ordning matcherna blev klara. Läsaren vill se dem i
    # matchnummer, precis som den levande listan.
    records.sort(key=lambda r: r.get("game") or 0)
    failures.sort(key=lambda r: r.get("game") or 0)
    # Antalet matcher i serien står i pekfilen. Faller tillbaka på antalet
    # rader om pekfilen saknas, t.ex. för en serie spelad före den infördes.
    info = _last_series_info()
    count = _last_series_count() or len(records) + len(failures)
    # Tiderna finns i pekfilen. Saknas de (äldre serie) visas ingen tid alls
    # hellre än en påhittad.
    started_at = info.get("started_at") if isinstance(info.get("started_at"), (int, float)) else None
    finished_at = info.get("finished_at") if isinstance(info.get("finished_at"), (int, float)) else None
    return {
        "running": False,
        "done": len(records) + len(failures),
        "count": count,
        "error": None,
        "push_status": None,
        "file": path.name,
        "games": len(records),
        "failures": failures,
        "records": records,
        "summary": summarize(records + failures) if records or failures else None,
        "live": [],
        "started_at": started_at,
        "finished_at": finished_at,
        "download_url": "/api/matches/download",
        "restored": True,
        "source": path.name,
    }


@app.get("/api/matches/summary")
def matches_summary() -> dict:
    """Sammanfatta den senaste batchkörningen."""
    path = _match_file()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Ingen batchkörning gjord ännu.")
    return summarize(read_jsonl(path))


@app.get("/api/matches/download")
def matches_download() -> FileResponse:
    """Ladda ner protokollet från den senaste batchkörningen (JSONL)."""
    path = _match_file()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Ingen batchkörning gjord ännu.")
    return FileResponse(
        path,
        media_type="application/x-ndjson",
        filename=path.name,
    )


@app.get("/api/matches/logrepo")
def matches_logrepo() -> dict:
    """Om loggrepet är konfigurerat för automatisk incheckning."""
    repo = logrepo.LogRepo()
    return {
        "ready": repo.ready(),
        "push_enabled": logrepo.push_enabled(),
        "dir": str(repo.directory),
        "repo": logrepo.logs_repo(),
    }


@app.get("/api/quota")
def quota_state() -> dict:
    """Dagskvoten för Gemini: använt, kvar och när den fylls på.

    Google redovisar inte återstående kvot i något API, så siffrorna bygger på
    vår egen räkning (``meier/quota.py``) och gränsen för fri nivå. Ett 429
    som säger att dygnstaket är nått sparas med Googles egen väntetid.
    """
    try:
        model = LLMClient().config.model
    except LLMError:
        model = None
    return quota.snapshot(model)


# -- Analys: ställ frågor mot insamlade matchprotokoll ---------------------
#
# Användaren väljer en eller flera loggar som redan checkats in i loggrepet.
# De sammanställs till en kompakt digest som en LLM får svara på frågor om.
# Digesten hålls liten med flit: hela händelseloggarna ryms inte i
# modellkontexten.

_store = analysis.AnalysisStore()


def _count_lines(path: Path) -> int:
    """Antal spelade matcher i en JSONL-fil.

    Rader som markerats som misslyckade räknas inte: en serie där alla matcher
    föll på ett LLM-fel ska inte se ut som en spelad match i listan.
    """
    ok = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    if not json.loads(line).get("failed"):
                        ok += 1
                except ValueError:
                    continue
    except OSError:
        return 0
    return ok


@app.get("/api/analysis/data")
def analysis_data() -> dict:
    """Vad som finns inläst: antal matcher, källor och sammanställningen."""
    info = _store.info()
    digest = _store.digest()
    return {
        **info,
        "source_labels": [logrepo.series_label(s) for s in info["sources"]],
        "source_times": {s: logrepo.series_epoch(s) for s in info["sources"]},
        "digest": digest,
        "digest_text": analysis.render_digest_text(digest),
    }


@app.get("/api/analysis/logs")
def analysis_logs() -> dict:
    """Lista loggar: de incheckade i loggrepet och de lokala i /workspace."""
    repo = logrepo.LogRepo()
    logs: list[dict] = []
    if repo.is_repo():
        try:
            logs = repo.list_logs()
        except logrepo.LogRepoError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    local = _local_log_files()
    known = {e["name"] for e in logs}
    # Lokala serier listas efter de incheckade. En lokal serie kan heta samma
    # sak som en incheckad (samma tidsstämpel), då vinner den incheckade.
    logs += [e for e in local if e["name"] not in known]
    loaded = set(_store.sources())
    for entry in logs:
        entry["games"] = _count_lines(_path_for_log(entry))
        entry["loaded"] = entry["name"] in loaded
    return {"ready": True, "logs": logs, "local_dir": str(_local_log_dir())}


def _source_records(source: str) -> list[dict]:
    """Protokollen för en källa, från minnet om den är inläst, annars från disk.

    Detaljvyn ska fungera även för en serie som inte är inläst i analysen, och
    efter en omstart då butiken är tom. Filen läses då direkt, med samma
    översättning av äldre nyckelnamn som analysen använder.
    """
    records = _store.records_for(source)
    if records:
        return records
    for entry in _local_log_files():
        if entry["name"] == source:
            return read_jsonl(_local_log_dir() / source)
    try:
        return read_jsonl(logrepo.LogRepo().log_path(source))
    except (logrepo.LogRepoError, FileNotFoundError, ValueError):
        return []


@app.get("/api/analysis/matches")
def analysis_matches(source: str) -> dict:
    """Matcherna i en källa, för detaljvyn i flikarna.

    Svaret är en lätt lista utan händelser. Händelserna hämtas per match med
    ``/api/analysis/match``, så att en stor serie inte skickas i onödan.
    """
    records = _source_records(source)
    if not records:
        raise HTTPException(status_code=404, detail=f"Källan finns inte: {source}")
    return {
        "source": source,
        "games": len(records),
        "matches": [match_brief(i, rec) for i, rec in enumerate(records, start=1)],
    }


@app.get("/api/analysis/match")
def analysis_match(source: str, game: int) -> dict:
    """En match med alla sina händelser, för utvikning till runda och händelse."""
    records = _source_records(source)
    if not records:
        raise HTTPException(status_code=404, detail=f"Källan finns inte: {source}")
    for i, rec in enumerate(records, start=1):
        if (rec.get("game") or i) == game:
            return {
                "source": source,
                "match": match_detail(rec),
            }
    raise HTTPException(status_code=404, detail=f"Matchen finns inte: {game}")


def _local_log_files() -> list[dict]:
    """JSONL-serier i den lokala katalogen, nyaste först."""
    directory = _local_log_dir()
    out: list[dict] = []
    if not directory.is_dir():
        return out
    for p in sorted(directory.glob("*.jsonl")):
        try:
            stat = p.stat()
        except OSError:
            continue
        out.append(
            {
                "name": p.name,
                "label": logrepo.series_label(p.name),
                "started_at": logrepo.series_epoch(p.name),
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
                "local": True,
            }
        )
    out.sort(key=lambda d: d["modified"], reverse=True)
    return out


def _path_for_log(entry: dict) -> Path:
    """Sökvägen till en logg, antingen i loggrepet eller lokalt."""
    if entry.get("local"):
        return _local_log_dir() / entry["name"]
    return logrepo.LogRepo().directory / entry["name"]


class _SelectLogsRequest(BaseModel):
    names: list[str] = Field(default_factory=list, description="Valda loggfilnamn")


@app.post("/api/analysis/select")
def analysis_select(req: _SelectLogsRequest) -> dict:
    """Sätt vilka loggar som är inlästa. Valda läses in, övriga tas bort."""
    repo = logrepo.LogRepo()
    local_names = {e["name"]: e for e in _local_log_files()}
    wanted = list(dict.fromkeys(req.names))
    loaded = set(_store.sources())
    for name in wanted:
        if name in loaded:
            continue
        try:
            if name in local_names:
                path = _local_log_dir() / name
            else:
                path = repo.log_path(name)
        except logrepo.LogRepoError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _store.add_file(path)
    for name in loaded:
        if name not in wanted:
            _store.remove(name)
    return _store.info()


class AnalysisAskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Frågan till analysen")


@app.post("/api/analysis/ask")
def analysis_ask(req: AnalysisAskRequest) -> dict:
    """Ställ en fråga mot det inlästa materialet och få svar (+ ev. diagram)."""
    if not _store.snapshot():
        raise HTTPException(status_code=400, detail="Inget material inläst ännu.")
    try:
        result = analysis.ask(_store.digest(), req.question)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fel: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")