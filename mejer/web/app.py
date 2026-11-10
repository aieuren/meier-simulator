"""FastAPI-webbapp för Mejer-agenterna.

Webbappen låter dig skriva in tärningsutfallet (två tärningar) och få
spelarens svar från en LLM-baserad agent. Du kan välja roll och ange ett
tidigare bud om spelaren slår efter någon annan.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import rules
from ..agents.player import ROLES, get_role
from ..llm import LLMClient, LLMError
from ..agents.player import MejerPlayerAgent
from ..match import GameRecord, read_jsonl, run_matches, summarize
from ..session import Session
from .. import analysis

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Mejer-agenten", version="1.2.0")

# En agent per roll, skapade på begäran så att LLM-klienten återanvänds.
_agents: dict[str, MejerPlayerAgent] = {}

# Den aktiva interaktiva sessionen (en åt gången).
_session: Session | None = None

# Senaste batchkörningen av matcher (för nedladdning och statistik).
_MATCH_FILE = Path("/tmp/mejer_matches.jsonl")


def _get_agent(role_key: str) -> MejerPlayerAgent:
    if role_key not in _agents:
        _agents[role_key] = MejerPlayerAgent(role=get_role(role_key), llm=LLMClient())
    return _agents[role_key]


class AnnounceRequest(BaseModel):
    die1: int = Field(..., ge=1, le=6, description="Första tärningen")
    die2: int = Field(..., ge=1, le=6, description="Andra tärningen")
    role: str = Field("kalkyl", description="Agentens roll")
    previous_bid: int | None = Field(
        None, description="Tidigare bud om spelaren slår efter någon annan"
    )


class DecideRequest(BaseModel):
    bid: int = Field(..., description="Motståndarens bud")
    role: str = Field("kalkyl", description="Agentens roll")
    lives: int = Field(3, ge=0, le=3)


@app.get("/")
def index() -> FileResponse:
    # Ingen cachning: filerna ändras ofta och gamla kopior gav "undefined" i UI:t.
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, must-revalidate"},
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
            {"key": r.key, "name": r.name, "description": r.description, "style": r.style}
            for r in ROLES.values()
        ],
        "ranking": [{"value": v, "name": rules.name(v)} for v in rules.RANKING],
    }


@app.post("/api/announce")
def announce(req: AnnounceRequest) -> dict:
    """Givet ett tärningsutfall: hur svarar spelaren?"""
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Okänd roll: {req.role}")
    try:
        shown = rules.read_dice(req.die1, req.die2)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.previous_bid is not None and not rules.is_valid_value(req.previous_bid):
        raise HTTPException(status_code=400, detail=f"Ogiltigt tidigare bud: {req.previous_bid}")

    agent = _get_agent(req.role)
    try:
        ann = agent.announce((req.die1, req.die2), previous_bid=req.previous_bid)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fel: {exc}") from exc

    return {
        "shown": shown,
        "shown_name": rules.name(shown),
        "previous_bid": req.previous_bid,
        "announcement": ann.to_dict(),
    }


@app.post("/api/decide")
def decide(req: DecideRequest) -> dict:
    """Givet en motståndares bud: slår, synar eller skickar spelaren vidare?"""
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Okänd roll: {req.role}")
    if not rules.is_valid_value(req.bid):
        raise HTTPException(status_code=400, detail=f"Ogiltigt bud: {req.bid}")

    agent = _get_agent(req.role)
    try:
        decision = agent.decide(req.bid, lives=req.lives)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fel: {exc}") from exc

    result = decision.to_dict()
    if decision.action == "syna":
        # Vad som händer vid en syn beror på de dolda tärningarna; visa regeln.
        result["note"] = (
            "Vid syn: visar tärningarna lägre än budet förlorar budgivaren, "
            "annars förlorar den som synar. Mejer kostar dubbelt."
        )
    return result


@app.get("/api/health")
def health() -> dict:
    cfg = LLMClient().config
    return {"status": "ok", "provider": cfg.provider, "model": cfg.model}


# -- Interaktiv spelsession ------------------------------------------------


class NewSessionRequest(BaseModel):
    roles: list[str] = Field(
        default_factory=lambda: list(ROLES),
        description="Roller som spelar. Standard: alla fyra.",
    )
    seed: int | None = Field(None, description="Slumpfrö för reproducerbarhet")


def _require_session() -> Session:
    if _session is None:
        raise HTTPException(status_code=404, detail="Ingen aktiv session. Skapa en först.")
    return _session


@app.post("/api/session/new")
def session_new(req: NewSessionRequest) -> dict:
    """Skapa en ny session: slumpad ordning och första tärningsslag."""
    global _session
    roles = req.roles or list(ROLES)
    for key in roles:
        if key not in ROLES:
            raise HTTPException(status_code=400, detail=f"Okänd roll: {key}")
    if len(roles) < 2:
        raise HTTPException(status_code=400, detail="Minst två roller krävs")

    players = [_get_agent(key) for key in roles]
    _session = Session.new(players, seed=req.seed)
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
        default_factory=lambda: list(ROLES),
        description="Roller som spelar. Standard: alla fyra.",
    )
    count: int = Field(5, ge=1, le=200, description="Antal matcher")
    base_seed: int | None = Field(None, description="Basfrö för reproducerbarhet")
    lives: int = Field(3, ge=1, le=10)
    workers: int = Field(
        3, ge=1, le=8, description="Antal matcher som spelas samtidigt"
    )


class _MatchJob:
    """Ett bakgrundsjobb som spelar en serie matcher."""

    def __init__(
        self,
        roles: list[str],
        count: int,
        base_seed: int | None,
        lives: int,
        workers: int = 1,
    ):
        self.roles = roles
        self.count = count
        self.base_seed = base_seed
        self.lives = lives
        self.workers = workers
        self.done = 0
        self.records: list[GameRecord] = []
        self.error: str | None = None
        self.running = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            # Skriv protokollet radvis medan serien spelas, så att nedladdningen
            # fungerar även innan hela serien är klar.
            with open(_MATCH_FILE, "w", encoding="utf-8") as fh:
                for rec in run_matches(
                    self.roles,
                    self.count,
                    base_seed=self.base_seed,
                    lives=self.lives,
                    workers=self.workers,
                ):
                    with self.lock:
                        self.records.append(rec)
                        self.done += 1
                    fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
                    fh.flush()
        except LLMError as exc:
            self.error = f"LLM-fel: {exc}"
        except Exception as exc:  # pragma: no cover - skyddsnät
            self.error = f"Oväntat fel: {exc}"
        finally:
            self.running = False

    def status(self) -> dict:
        with self.lock:
            snapshot = [rec.to_dict() for rec in self.records]
        summary = summarize(snapshot) if snapshot else None
        return {
            "running": self.running,
            "done": self.done,
            "count": self.count,
            "error": self.error,
            "games": self.done,
            "records": snapshot,
            "summary": summary,
            "download_url": "/api/matches/download",
        }


_match_job: _MatchJob | None = None


@app.post("/api/matches/run")
def matches_run(req: MatchRequest) -> dict:
    """Starta en serie matcher i bakgrunden. Följ den med /api/matches/status."""
    global _match_job
    roles = req.roles or list(ROLES)
    for key in roles:
        if key not in ROLES:
            raise HTTPException(status_code=400, detail=f"Okänd roll: {key}")
    if len(roles) < 2:
        raise HTTPException(status_code=400, detail="Minst två roller krävs")
    if _match_job is not None and _match_job.running:
        raise HTTPException(status_code=409, detail="En matchserie kör redan.")

    _match_job = _MatchJob(roles, req.count, req.base_seed, req.lives, req.workers)
    _match_job.thread.start()
    return _match_job.status()


@app.get("/api/matches/status")
def matches_status() -> dict:
    """Läget för den senaste (eller pågående) matchserien."""
    if _match_job is None:
        raise HTTPException(status_code=404, detail="Ingen matchserie startad.")
    return _match_job.status()


@app.get("/api/matches/summary")
def matches_summary() -> dict:
    """Sammanfatta den senaste batchkörningen."""
    if not _MATCH_FILE.exists():
        raise HTTPException(status_code=404, detail="Ingen batchkörning gjord ännu.")
    return summarize(read_jsonl(_MATCH_FILE))


@app.get("/api/matches/download")
def matches_download() -> FileResponse:
    """Ladda ner protokollet från den senaste batchkörningen (JSONL)."""
    if not _MATCH_FILE.exists():
        raise HTTPException(status_code=404, detail="Ingen batchkörning gjord ännu.")
    return FileResponse(
        _MATCH_FILE,
        media_type="application/x-ndjson",
        filename="mejer-matcher.jsonl",
    )


# -- Analys: ställ frågor mot insamlade matchprotokoll ---------------------
#
# Användaren laddar upp en eller flera JSONL-filer (nedladdade efter tidigare
# körningar). De sammanställs till en kompakt digest som en LLM får svara på
# frågor om. Digesten hålls liten med flit: hela händelseloggarna ryms inte i
# modellkontexten.

#: Största tillåtna uppladdning per fil (skydd mot misstag).
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_store = analysis.AnalysisStore()


@app.get("/api/analysis/data")
def analysis_data() -> dict:
    """Vad som finns inläst: antal matcher, källor och sammanställningen."""
    info = _store.info()
    digest = _store.digest()
    return {
        **info,
        "digest": digest,
        "digest_text": analysis.render_digest_text(digest),
    }


@app.post("/api/analysis/upload")
async def analysis_upload(files: list[UploadFile]) -> dict:
    """Ladda upp en eller flera JSONL-filer med matchprotokoll."""
    if not files:
        raise HTTPException(status_code=400, detail="Inga filer skickades")
    added = 0
    details: list[dict] = []
    for f in files:
        raw = await f.read()
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Filen {f.filename} är för stor (max 25 MB)",
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"Filen {f.filename} är inte UTF-8-text"
            ) from exc
        n = _store.add_text(f.filename or "fil", text)
        added += n
        details.append({"name": f.filename, "games": n})
    if added == 0:
        raise HTTPException(
            status_code=400,
            detail="Inga giltiga matchprotokoll hittades i filerna",
        )
    info = _store.info()
    return {**info, "added": added, "files": details}


@app.post("/api/analysis/load-latest")
def analysis_load_latest() -> dict:
    """Läs in protokollet från den senaste matchserien i servern."""
    if not _MATCH_FILE.exists():
        raise HTTPException(status_code=404, detail="Ingen matchserie körd ännu.")
    added = _store.add_file(_MATCH_FILE)
    return {**_store.info(), "added": added}


@app.post("/api/analysis/clear")
def analysis_clear() -> dict:
    """Töm allt inläst analysmaterial."""
    _store.clear()
    return _store.info()


@app.get("/api/analysis/export")
def analysis_export() -> PlainTextResponse:
    """Ladda ner allt inläst material som en JSONL-fil igen."""
    if not _store.snapshot():
        raise HTTPException(status_code=404, detail="Inget material inläst.")
    return PlainTextResponse(
        _store.to_jsonl() + "\n",
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="mejer-analys.jsonl"'},
    )


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