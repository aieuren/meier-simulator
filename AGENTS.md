# AGENTS.md

Repository memory for the Meier AI-agent project.

## What this project is

A Python library plus FastAPI web app where independent, LLM-based AI agents
play the Swedish dice game **Meier**. The core deliverable: given the outcome of
a two-dice roll, an agent decides how the player responds (truth, higher, or
lower bid). Multiple agents with distinct roles can also play full games.

## Layout

- `meier/rules.py` – game rules. Single source of truth for the ranking order,
  bid comparison, and call resolution. Change rules here only. The dice are
  elongated (length/width = `DIE_ELONGATION` = 1.3), so `roll` draws with
  `FACE_WEIGHTS`: faces 3-6 (the long sides) are 1.3x as likely as 1-2 (the
  square end faces). This makes Meier and 11 rarer than on a cube; odd and even
  stay equally likely, since 1/2 sit on the ends (one odd, one even).
- `meier/llm.py` – LLM client. Prefers Anthropic (Claude) via
  `ANTHROPIC_API_KEY`; falls back to the OpenHands agent-server proxy.
  `LLMClient.last_usage` holds the token count from the last call.
  Self-heals the agent-server LLM profile (see gotcha below).
- `meier/game.py` – multi-agent game engine. Keeps each agent isolated; no agent
  sees another's secret dice.
- `meier/session.py` – interactive session: full flow to a call (roll → raise
  (new shake) / pass → forced raise → call), random player order, and the log.
  The log is built downward: each shake starts with a `kind="roll"`
  entry (the dice, pure input), then one `kind="action"` entry per answer (bid,
  raise, pass, or call), and after a call a `kind="life"` entry (who lost how
  many lives, and how many remain). Every `kind="life"` entry also carries a
  `standings` snapshot (each player's name, role and remaining lives, in seating
  order) so the UI can show the life tally right after each call. When the match
  ends, `_finish()` appends one `kind="game_over"` entry naming the winner, and
  `to_dict()` adds `standings` and `winner` at the top level (the game-over row is
  not counted as a player action by the analysis). Every action entry carries
  `accepted_bid`
  (the bid the player answers) next to `bid` (the bid they then say), so the UI
  can show "Slår över X, säger Y" as separate parts. `to_dict` also reports
  `order` and `starter` so the UI can show the seating and who begins.
  `advance()` does one gated step;
  `run_to_round_end()` runs to the end of the current round (a call, or a new
  round after Meier), `run_to_call()` runs the whole flow to the next call, and
  `run_to_end()` plays the whole match to a winner.
  The web UI moves the *Ett drag* button into the log so it sits under the
  latest dice roll; the *Till slut på runda*, *Till syn* and *Hela matchen*
  buttons run multiple steps at once (all four controls are disabled while a
  call runs). When a raise is not strictly higher than the previous bid,
  `_enforce_bid` replaces it with the smallest legal raise.
- Call responsibility: the player who loses a life on a call is the one who
  *holds* the bid — the last player to say or pass the bid — not necessarily the
  one who first set it. `Session.holder` tracks this and is updated on every bid,
  blind shake, forced raise, and pass. The next round starts with the active
  player *before* the loser in turn order (`_previous_active`). `meier/game.py`
  keeps the same `holder` logic in its text log.
- `meier/agents/base.py` – `Agent`/`Role` base classes.
- `meier/agents/player.py` – `MeierPlayerAgent` and the role registry. The agent
  is the source of truth for legality: `_coerce_bid` and `_coerce_blind_bid`
  keep every bid valid and strictly higher, and `Session._enforce_bid` is the
  engine's backstop. The tests guard the rules.
- `meier/web/app.py` + `meier/web/static/` – web UI and JSON API. The UI has
  four tabs: *Spelarna* (the four player cards with name, description, and
  style), *Enskild spelare* (one player answers a roll),
  *Fyra spelare* (the interactive session), and *Matchserie* (run a series of
  matches and show per-player statistics plus a downloadable JSONL protocol).
  `/api/roles` returns each role's `style` too, so the
  first tab can show the full character text. Tab switching just toggles
  `[hidden]` on `.tab-panel`; note the `.tab-panel[hidden] { display: none }`
  rule — a bare `display: grid` would otherwise override `hidden` and show every
  panel at once. A match series is hundreds of LLM calls and takes minutes, so
  `/api/matches/run` starts a background thread and returns at once; the client
  polls `/api/matches/status` (field `running`) and renders matches as they
  finish. Only one series runs at a time (a second start gives 409). The request
  field `workers` (1–8) plays several matches at once; the JSONL file is written
  line by line as matches finish, so the download works mid-run. With
  `check_in` set, each finished match is committed and pushed to the log repo
  (see below); the outcome lands in the status field `push_status`. A push
  failure never fails the run.
- `meier/match.py` – batch play of many full matches between the roles, for
  strategy analysis. `play_match` plays one match to the end via
  `Session.play_to_end()` and returns a `GameRecord`; `run_matches` yields a
  series (optional sequential seeds, and `workers>1` plays matches in parallel
  threads); `write_jsonl`/`read_jsonl` persist one
  match per line; `summarize` aggregates a series per role (win rate, bluff
  rate, raise/call rates, call success, lives lost). `GameRecord.events` is the
  full session log (`LogEntry.to_dict()`), which carries the analysis fields
  (`accepted_bid`, `proposed`, `corrected`, `blind`, `lives_lost`, `lives_left`,
  `actor_lives`, `active_players`, `caller_loses`). Tests swap the module-level
  `_new_agents` factory for scripted agents.
- `meier/cli.py` – command line entry points (`announce`, `decide`, `play`,
  `session`, `match`, `summarize`).
- `meier/analysis.py` – analysis of collected match protocols. `build_digest`
  turns a list of `GameRecord.to_dict()` records into a compact summary
  (per-role stats from `summarize`, plus action/bid/outcome distributions and a
  per-match series) so it fits in the model context — the full event logs do
  not. `render_digest_text` formats it for the prompt (and for the UI). `ask`
  sends a question with the digest and expects JSON
  (`{"answer", "chart", "followups", "cannot_answer"}`); `_clean_chart` drops
  charts the frontend cannot draw, and `cannot_answer` (a short Swedish note,
  else null) is surfaced as a warning when the question needs detail the digest
  does not carry. `render_digest_text` also ends with a "VAD SAMMANSTÄLLNINGEN
  INTE INNEHÅLLER" section listing what the digest omits (raw rolls, per-bid
  detail, agent reasoning), so the model can tell a missing-detail question from
  a thin-data one. `AnalysisStore` keeps the loaded records grouped per source
  file, so a single log can be dropped again when the user unchecks it. The
  chart types are `bar` (`labels`/`values`), `line` (`labels`/`series`) and
  `table` (`columns`/`rows`); the frontend renders them as plain SVG. Records
  are loaded from logs already checked into the log repo: `/api/analysis/logs`
  lists them (`LogRepo.list_logs`, with `games` and `loaded`) and
  `/api/analysis/select` sets the selection — chosen names are read in,
  dropped names are removed (`LogRepo.log_path` rejects anything outside the
  clone).
- `tests/` – unit tests. No real LLM calls; `FakeLLM`/`ScriptedAgent` are used.

## Meier ranking is non-numeric (gotcha)

Higher is *not* the larger number. The order is `21` (Meier, highest), then
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
higher is corrected to the smallest legal raise: `Session._enforce_bid`.

## Forced raise (full lap) = a fresh shake too (gotcha)

When the cup comes back to the bidder after a full lap, the rule we play is
that the dice are **re-rolled** — not just a higher number said over the old
dice. The bidder may then look at the new dice or bid blind; both are allowed,
just like any other bid. So `Session._resolve_raise` and `Game._play_round`
roll new dice, log a fresh `kind="roll"` entry, and call
`MeierPlayerAgent.announce_forced` (which asks the model "look or blind?" via
`_forced_choice_context`, then delegates to `announce` or `announce_blind`).
`pending_dice` must be updated to the new roll, otherwise a later syna would be
judged against the stale dice. The **holder must also become the bidder** in
`Game._play_round` (Session already does `self.holder = self.bidder`) — miss it
and a later syna blames the wrong player. A forced raise is `blind=True` only
when the bidder chose to bid blind. (`höja` is still a bid, so it counts in
`BID_ACTIONS`; blind raises count as `blinds`, not bluffs.)

## Reasoning is logged for every decision (for later analysis)

The model's free-text `reasoning` (and `line`) is stored on every logged
decision, so it can be mined later (e.g. by an LLM). Two gaps used to exist and
are now closed:

- **syna** was logged with empty `line`/`reasoning`. `Session._resolve_call`
  now takes the caller's `ActionDecision` and stores its `line`/`reasoning` on
  the log entry and on the `CallResult` (shown in the web UI).
- **Forced raise (look or blind?)** discarded the choice's motivation.
  `_wants_blind_forced` now returns an `ActionDecision` (`action` is `"titta"`
  or `"blint"`), and `announce_forced` carries `choice_line`/`choice_reasoning`
  onto the announcement, the log entry and `Game`'s text log.

So `Announcement.choice_line`/`choice_reasoning` and
`LogEntry.choice_line`/`choice_reasoning` are populated for `höja` rows.
Note: `build_digest` does **not** include reasoning — to analyse it you must
feed selected raw events to the model, not the digest.

Investigated a reported "raise after a blind slå" bug: it is **not** reproducible.
`accepted_bid` is the bid the player *answers*, so a raise showing
`accepted=52, bid=61` is just the forced raise at the end of a full lap, not a
double raise. A property check over 500 random matches (200 for `bid >=
accepted`, 300 for the `slå → höja` pattern) found 0 violations, and every `slå`
is `blind=True`.

## Agent Canvas: LLM profiles vanish on container restart (gotcha)

The app talks to the LLM through the local agent-server proxy
(`http://127.0.0.1:60000/v1/chat/completions`) with the model name
`openhands_<profile>`. The agent server keeps its LLM profiles **in memory**, so
a container restart wipes them. Then every call fails with
`404 {"detail":"Profile '<name>' not found"}`, and the web app looks dead.

`LLMClient` self-heals: on that 404 it recreates the profile and retries once.
The profile points at a concrete model (`MEIER_PROFILE_MODEL`, default
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
detach (log at `/tmp/meier_web.log`) and `./run.sh --check` to test only.
It also refuses to double-start if `/api/health` already answers on the port.

Manual fallback: `pip install -r requirements.txt`, then
`python3 -m uvicorn meier.web.app:app --host 0.0.0.0 --port 12000`.

## The engine is the source of truth

Legality lives in the engine and the player agent, not in a separate judge:
`MeierPlayerAgent._coerce_bid` / `_coerce_blind_bid` keep every bid valid and
strictly higher, and `Session._enforce_bid` is the engine's backstop for the bid
that actually stands. The tests in `tests/` guard the rules. There is no referee
agent — do not reintroduce a deterministic check as a "judge".

## Commands

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                     # run tests (fast, no network)
python -m uvicorn meier.web.app:app --port 12000
python -m meier.cli announce 2 5 --role rackar
python -m meier.cli play rackar kalkyl trygg
```

## Conventions

- Code comments and docstrings are in Swedish, matching the domain. Keep them.
- The 21-outcome ranking is fixed: 21, 11, 22, 33, 44, 55, 66, 65, 64, 63, 62,
  61, 54, 53, 52, 51, 43, 42, 41, 32, 31. Meier (21) is highest and costs double.
- Agents must always respond with a JSON object; parsing tolerates code fences
  and surrounding text (`llm.parse_json_object`).
- The engine coerces illegal model output back to legal moves (e.g. forces a
  higher bid when the rules require it). Keep that safety net.
- A "slå" bid is **blind**: the player shakes their *own* cup and does not look
  at their own dice, so the bid is not a truth-or-bluff claim. Only "bud" and
  "höja" bids where the player actually looked carry the sant/bluff label; any
  blind bid (a slå, or a forced raise where the bidder chose not to look) is
  labelled "blint bud" and counted as `blinds`, never as `bluffs`, in the stats.
  This is deliberate: it adds a psychological dimension, so `blind_rate`
  is tracked per role to see whether bidding blind pays off over many matches.
- Note that pairs (11–66) outrank high singles, so e.g. 44 beats 65. When a call
  looks "wrong", check the ranking before assuming a bug.

## Environment notes

- In the Agent Canvas runtime, the working LLM endpoint is the local
  agent-server at `http://127.0.0.1:60000`, model `openhands_Default`, with the
  session key in `X-Session-API-Key`. Claude models are not reachable through the
  managed proxy key; set `ANTHROPIC_API_KEY` to use a real Claude account.
- Never print the session API key. Read it from the process env if needed.
- The web app is served on port 12000 in this environment.
- **Long runs / sandbox lifetime**: the runtime pauses an idle environment
  (`OH_RUNTIME_IDLE_TIMEOUT_SECONDS`, 1200s = 20 min in Canvas). LLM traffic and
  the client's 3s status polling keep it awake. A match series runs in a
  background thread, so closing the tab does not stop it, and the JSONL is
  appended as matches finish — a pause mid-series does not lose finished games.
  For runs that must exceed the idle window, run the CLI outside Canvas with a
  real `ANTHROPIC_API_KEY` (optionally `nohup`).
- The analysis tab keeps loaded protocols **in memory** (`web.app._store`),
  so they are lost on restart. Tests clear the store to stay isolated.
- Git remote: `https://github.com/aieuren/mejer-simulator.git` (branch `main`).
  The game was renamed Mejer → **Meier** everywhere in the code, but the GitHub
  repo still carries the old name: renaming it needs `administration:write`,
  which `$GITHUB_PUSH_TOKEN` does not have (it has `push`/`admin` on the repo
  itself but the rename endpoint returned 403). Rename it by hand in the GitHub
  UI to `meier-simulator`; the log repo is already `meier-simulator-logs`.
  `git push` needs auth: a repo-local `credential.helper` reads
  `$GITHUB_PUSH_TOKEN` (not stored on disk), since `$GITHUB_TOKEN` lacks write
  access to this repo. The variable is only exported when its name appears in
  the command, so run `GITHUB_PUSH_TOKEN="$GITHUB_PUSH_TOKEN" git push …`.
- The user has delegated version control: from now on, commit and push to
  `main` yourself when the work is green and complete — no need to ask first.
- Secrets for this conversation live in the agent-server, not the shell:
  `GET/PUT /api/settings/secrets[/{name}]` manages them, and
  `POST /api/conversations/{id}/secrets` attaches one to a running conversation.
  A secret added mid-conversation is not injected until it is attached this way.
  Names must be valid shell identifiers (letters, digits, underscore) — a hyphen
  makes the value unusable as an environment variable.

## Match logs are checked into a separate GitHub repo

Long series used to be lost: the protocol was written to `/tmp/meier_matches.jsonl`,
which a container restart wipes. Now a series can be committed and pushed to a
**separate** log repo after every finished match.

- Module: `meier/logrepo.py` (`LogRepo`, `series_filename`, `series_label`,
  `push_enabled`). One file per series: `meier-matcher-<YYYY-MM-DD-HHMMSS>.jsonl`
  (seconds, so two runs cannot collide and truncate each other).
  `series_label` turns the filename into a readable Swedish label
  ("12 november 2026, 02:46:13") used by the analysis tab and `list_logs`.
- Log repo: `aieuren/meier-simulator-logs` (private), clone at
  `/workspace/meier-logs` — deliberately **outside** the code repo, so the two
  are not nested git repos. `MEIER_LOGS_DIR` overrides the path.
- Token: `/workspace/meier-secrets/logs.token` (mode 600), read by a git
  credential-helper passed via `-c`, so the value never lands on the command
  line (it would otherwise show up in `ps`). Fine-grained PAT with only
  Contents: Read and write on the log repo. `MEIER_LOGS_PUSH=0` disables push.
- Wire-up: `web/app.py` `_MatchJob(check_in=...)`. Each record is appended and
  then `commit_and_push` runs; `push_status` reports the outcome.
  A push failure is caught and returned as a string — it must never kill a run.
  When no token/clone is available the log falls back to `/tmp/meier_matches.jsonl`.
- `_current_match_file` (module global) holds the file for the latest series;
  `/api/matches/download|summary` read it.
- Gotcha: `git -c key=value` must be passed as **two** argv items before the
  subcommand. `["-c", "user.name=Meier Bot"]` works; `["-cuser.name=Meier Bot"]`
  fails with "unknown option".
- Tests use a local bare repo via `MEIER_LOGS_REMOTE_URL` — no network, no real
  token. See `tests/test_logrepo.py` and the check-in tests in
  `tests/test_web_matches.py`.
