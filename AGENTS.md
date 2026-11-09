# AGENTS.md

Repository memory for the Mejer AI-agent project.

## What this project is

A Python library plus FastAPI web app where independent, LLM-based AI agents
play the Swedish dice game **Mejer**. The core deliverable: given the outcome of
a two-dice roll, an agent decides how the player responds (truth, higher, or
lower bid). Multiple agents with distinct roles can also play full games.

## Layout

- `mejer/rules.py` – game rules. Single source of truth for the ranking order,
  bid comparison, and call resolution. Change rules here only.
- `mejer/llm.py` – LLM client. Prefers Anthropic (Claude) via
  `ANTHROPIC_API_KEY`; falls back to the OpenHands agent-server proxy.
  `LLMClient.last_usage` holds the token count from the last call.
  Self-heals the agent-server LLM profile (see gotcha below).
- `mejer/game.py` – multi-agent game engine. Keeps each agent isolated; no agent
  sees another's secret dice.
- `mejer/session.py` – interactive session: full flow to a call (roll → raise
  (new shake) / pass → forced raise → call), random player order, referee review,
  and the log. The log is built downward: each shake starts with a `kind="roll"`
  entry (the dice, pure input), then one `kind="action"` entry per answer (bid,
  raise, pass, or call). `advance()` does one gated step; `run_to_round_end()`
  runs to the end of the current round (a call, or a new round after Mejer), and
  `run_to_call()` runs the whole flow to the next call. The web UI moves the
  *Ett drag* button into the log so it sits under the latest dice roll; the
  *Till slut på runda* and *Till syn* buttons run multiple steps at once. When a
  raise is not strictly higher than the previous bid, `_enforce_bid` lets the
  referee stop it and the smallest legal raise takes over.
- `mejer/agents/base.py` – `Agent`/`Role` base classes.
- `mejer/agents/player.py` – `MejerPlayerAgent` and the role registry.
- `mejer/agents/referee.py` – `RefereeAgent` (Domare-Doris). Judges each answer.
- `mejer/web/app.py` + `mejer/web/static/` – web UI and JSON API. The UI has
  three tabs: *Enskild spelare* (one player answers a roll), *Fyra agenter* (the
  interactive session), and *Hela spel* (per-game log, placeholder for now).
  Tab switching just toggles `[hidden]` on `.tab-panel`; note the
  `.tab-panel[hidden] { display: none }` rule — a bare `display: grid` would
  otherwise override `hidden` and show every panel at once.
- `mejer/cli.py` – command line entry points (`announce`, `decide`, `play`,
  `session`).
- `tests/` – unit tests. No real LLM calls; `FakeLLM`/`ScriptedAgent` are used.

## Mejer ranking is non-numeric (gotcha)

Higher is *not* the larger number. The order is `21` (Mejer, highest), then
`11, 22, 33, 44, 55, 66`, then `65, 64, …` down to `31` (lowest). So `33` is
higher than `44`, and `55` is higher than `66`. Always compare with
`rules.is_higher` / `rules.compare` — never with `<`/`>` on the raw value.

## Slå = a fresh shake, not a peek (gotcha)

The three choices are: **slå** (shake the cup again and name a higher bid
without looking), **syna** (lift the lid) and **skicka** (pass the same bid).
So slå is *not* a peek at the old dice — the player shakes a brand new roll, and
the bid must be strictly higher than the previous one whatever the dice show.
This is why the engine logs a fresh `kind="roll"` entry before every slå, and
why `announce_blind` (not `announce`) is used for it. A slå that is not strictly
higher is stopped by the referee: `Session._enforce_bid` lets the smallest legal
raise take over and records the objection.

## Agent Canvas: LLM profiles vanish on container restart (gotcha)

The app talks to the LLM through the local agent-server proxy
(`http://127.0.0.1:60000/v1/chat/completions`) with the model name
`openhands_<profile>`. The agent server keeps its LLM profiles **in memory**, so
a container restart wipes them. Then every call fails with
`404 {"detail":"Profile '<name>' not found"}`, and the web app looks dead.

`LLMClient` self-heals: on that 404 it recreates the profile and retries once.
The profile points at a concrete model (`MEJER_PROFILE_MODEL`, default
`openhands/deepseek-v4.1-flash`). Note the model-name forms:

- `openhands_Default` – a *profile* name; must exist in the agent server.
- `openhands/deepseek-v4.1-flash` – the concrete model the profile targets.

Useful endpoints (header `X-Session-API-Key: $SESSION_API_KEY`):
`GET /api/settings`, `GET /api/llm/models/verified`, `GET /api/profiles`,
`POST /api/profiles/<name>`, `POST /api/profiles/<name>/activate`.

Token cost (measured): the proxy adds a large fixed prompt overhead (~17.4k
tokens) to every call, independent of our own prompt length. Asking the model
for a `reasoning` field costs extra output tokens (roughly +200–600, more when
the model thinks longer). `LLMClient.last_usage` reports the real count.

## Environment restarts wipe global packages

Dependencies are installed globally (no venv). After a container restart,
`python3 -m uvicorn` fails with "No module named uvicorn", and pip's scripts
land in `~/.local/bin` (not always on PATH).

Fix: run `./run.sh`. It checks imports, installs from `requirements.txt` if
anything is missing, then starts the server. Use `./run.sh --background` to
detach (log at `/tmp/mejer_web.log`) and `./run.sh --check` to test only.
It also refuses to double-start if `/api/health` already answers on the port.

Manual fallback: `pip install -r requirements.txt`, then
`python3 -m uvicorn mejer.web.app:app --host 0.0.0.0 --port 12000`.

## Referee design (important)

The referee judges the answer the player *actually gave*: the model's raw
proposal (`Announcement.proposed`), not the value after rule coercion. This is
what makes objections meaningful — otherwise the player agent's own coercion
would make every answer trivially legal.

The formal rule checks are authoritative. The LLM layer may add a comment or
sharpen a verdict, but it can never approve a formal rule breach (see
`RefereeAgent._llm_second_opinion`). Keep that property when editing.

## Commands

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                     # run tests (fast, no network)
python -m uvicorn mejer.web.app:app --port 12000
python -m mejer.cli announce 2 5 --role rackar
python -m mejer.cli play rackar kalkyl trygg
```

## Conventions

- Code comments and docstrings are in Swedish, matching the domain. Keep them.
- The 21-outcome ranking is fixed: 21, 11, 22, 33, 44, 55, 66, 65, 64, 63, 62,
  61, 54, 53, 52, 51, 43, 42, 41, 32, 31. Mejer (21) is highest and costs double.
- Agents must always respond with a JSON object; parsing tolerates code fences
  and surrounding text (`llm.parse_json_object`).
- The engine coerces illegal model output back to legal moves (e.g. forces a
  higher bid when the rules require it). Keep that safety net.

## Environment notes

- In the Agent Canvas runtime, the working LLM endpoint is the local
  agent-server at `http://127.0.0.1:60000`, model `openhands_Default`, with the
  session key in `X-Session-API-Key`. Claude models are not reachable through the
  managed proxy key; set `ANTHROPIC_API_KEY` to use a real Claude account.
- Never print the session API key. Read it from the process env if needed.
- The web app is served on port 12000 in this environment.
- Secrets for this conversation live in the agent-server, not the shell:
  `GET/PUT /api/settings/secrets[/{name}]` manages them, and
  `POST /api/conversations/{id}/secrets` attaches one to a running conversation.
  A secret added mid-conversation is not injected until it is attached this way.
  Names must be valid shell identifiers (letters, digits, underscore) — a hyphen
  makes the value unusable as an environment variable.
