# AGENTS.md

Repository memory for the Majer AI-agent project.

## What this project is

A Python library plus FastAPI web app where independent, LLM-based AI agents
play the Swedish dice game **Majer**. The core deliverable: given the outcome of
a two-dice roll, an agent decides how the player responds (truth, higher, or
lower bid). Multiple agents with distinct roles can also play full games.

## Layout

- `majer/rules.py` – game rules. Single source of truth for the ranking order,
  bid comparison, and call resolution. Change rules here only.
- `majer/llm.py` – LLM client. Prefers Anthropic (Claude) via
  `ANTHROPIC_API_KEY`; falls back to the OpenHands agent-server proxy.
- `majer/game.py` – multi-agent game engine. Keeps each agent isolated; no agent
  sees another's secret dice.
- `majer/session.py` – interactive session: full flow to a call (roll → blind
  raise / pass → forced raise → call), random player order, referee review, and
  the log of every answer. `advance()` does one gated step; `run_to_call()` runs
  the whole flow to the next call.
- `majer/agents/base.py` – `Agent`/`Role` base classes.
- `majer/agents/player.py` – `MajerPlayerAgent` and the role registry.
- `majer/agents/referee.py` – `RefereeAgent` (Domare-Doris). Judges each answer.
- `majer/web/app.py` + `majer/web/static/` – web UI and JSON API.
- `majer/cli.py` – command line entry points (`announce`, `decide`, `play`,
  `session`).
- `tests/` – unit tests. No real LLM calls; `FakeLLM`/`ScriptedAgent` are used.

## Majer ranking is non-numeric (gotcha)

Higher is *not* the larger number. The order is `21` (Mejer, highest), then
`11, 22, 33, 44, 55, 66`, then `65, 64, …` down to `31` (lowest). So `33` is
higher than `44`, and `55` is higher than `66`. Always compare with
`rules.is_higher` / `rules.compare` — never with `<`/`>` on the raw value.

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
python -m uvicorn majer.web.app:app --port 12000
python -m majer.cli announce 2 5 --role rackar
python -m majer.cli play rackar kalkyl trygg
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
