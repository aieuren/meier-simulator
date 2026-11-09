"""FastAPI-webbapp för Mejer-agenterna.

Webbappen låter dig skriva in tärningsutfallet (två tärningar) och få
spelarens svar från en LLM-baserad agent. Du kan välja roll och ange ett
tidigare bud om spelaren slår efter någon annan.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import rules
from ..agents.player import ROLES, get_role
from ..llm import LLMClient, LLMError
from ..agents.player import MejerPlayerAgent
from ..agents.referee import REFEREE_ROLE, RefereeAgent
from ..session import Session

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Mejer-agenten", version="1.1.0")

# En agent per roll, skapade på begäran så att LLM-klienten återanvänds.
_agents: dict[str, MejerPlayerAgent] = {}

# Den aktiva interaktiva sessionen (en åt gången).
_session: Session | None = None


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
        "referee": {
            "key": REFEREE_ROLE.key,
            "name": REFEREE_ROLE.name,
            "description": REFEREE_ROLE.description,
            "style": REFEREE_ROLE.style,
        },
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
    """Skapa en ny session: slumpad ordning, domare och första tärningsslag."""
    global _session
    roles = req.roles or list(ROLES)
    for key in roles:
        if key not in ROLES:
            raise HTTPException(status_code=400, detail=f"Okänd roll: {key}")
    if len(roles) < 2:
        raise HTTPException(status_code=400, detail="Minst två roller krävs")

    players = [_get_agent(key) for key in roles]
    referee = RefereeAgent(llm=LLMClient())
    _session = Session.new(players, referee, seed=req.seed)
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


@app.post("/api/session/stop")
def session_stop() -> dict:
    session = _require_session()
    session.stop()
    return session.to_dict()


app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")
