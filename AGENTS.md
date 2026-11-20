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
  elongated (length/width = `DIE_ELONGATION` = 1.3). `roll` weights each face
  by its **area** under that model, so faces 3-6 (the long sides) are 1.3x as
  likely as 1-2 (the square end faces). Area is a modelling choice, not physics:
  weighting by solid angle from the centre of mass gives 1.56 for the same
  shape. See `docs/agent-model.md` §3.0. Odd and even stay equally likely
  either way, since 1/2 sit on the ends (one odd, one even).
- `meier/llm.py` – LLM client. Provider priority: Anthropic (Claude) via
  `ANTHROPIC_API_KEY`, then Google Gemini via `GEMINI_API_KEY`/`GOOGLE_API_KEY`
  (or the key files under `MEIER_SECRETS_DIR`). Both are real endpoints; there
  is **no** fallback to the OpenHands agent-server. Gemini uses the
  OpenAI-compatible endpoint
  `https://generativelanguage.googleapis.com/v1beta/openai`.
  `LLMClient.last_usage` holds the token count from the last call. Without a
  key, `LLMConfig.from_env()` raises `LLMError`.
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

## The OpenHands agent-server proxy is gone (removed 2026-11-17)

Earlier the app could fall back to the local agent-server proxy
(`http://127.0.0.1:60000/v1/chat/completions`, model `openhands_<profile>`).
**That path is deleted.** Every request there started a whole OpenHands
conversation, so a match filled `/var/openhands/conversations` with hundreds of
conversations. `LLMConfig._from_provider_env()` now accepts only `anthropic` or
`gemini` and raises `LLMError` when no key exists.

Consequences to keep in mind:

- There is no proxy fallback. Without `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`
  (or the key files) the app fails fast with a clear message instead of quietly
  spending a conversation per call.
- The self-healing profile logic (`_MissingProfile`, `_ensure_profile`,
  `profile_name`) and the session-key helper are removed. Do not reintroduce
  them; the agent-server proxy is not a supported backend for this app.
- The old proxy added a large fixed prompt overhead (~17.4k tokens) per call.
  That cost is gone with the proxy.

`LLMClient.last_usage` still reports the real token count per call, and
`total_usage` sums a client's calls.

## Cleaning up conversations: two stores, not one (2026-11-17)

The fallback left conversations in **two** places, and the Agent Canvas sidebar
lists the **cloud** one:

1. **Local agent-server** – `/var/openhands/conversations/<hex32>/`. The
   agent-server builds an in-memory registry from this directory at start, so
   deleting a directory by hand does not lower `/api/conversations/count` until
   the next restart. Delete through the API to keep the registry in sync:
   `DELETE http://127.0.0.1:60000/api/conversations/<uuid>` with header
   `X-Session-API-Key: $SESSION_API_KEY` (the key is in pid 1's environ).
2. **OpenHands Cloud** – the sidebar's list. These are real cloud objects, so
   they survive any local cleanup. Use the cloud API:
   `GET /api/v1/app-conversations/search?limit=100` (max 100 per page, follow
   `next_page_id`) and `DELETE /api/v1/app-conversations/<id>`, both with
   `Authorization: Bearer $OPENHANDS_API_KEY`. `.../count` gives the total.

Deleting a local directory by hand only removes disk usage; the cloud entry and
the in-memory registry stay. Do both stores. `OH_CONVERSATIONS_PATH` points at
the local one; the cloud base is `https://app.all-hands.dev`.

## Token accounting and Gemini rate limits (measured 2026-11-17)

- Each `LLMClient` keeps `total_usage` (accumulated) and `calls`. A match has
  one client per agent, so `_match_usage()` sums them into `GameRecord.usage`
  (`total`, `calls`, `by_role`). `summarize()` aggregates this as `tokens`
  (`total`, `per_game`, `calls_per_game`), shown in the CLI and the web summary.
- Real match via the web app (Gemini `gemini-3.1-flash-lite`, seed 11, 8
  rounds): **62 018 tokens over 82 calls** (~756 tokens/call). Earlier log
  files show 94–197 calls per match (8–13 rounds), so budget ~60–120k tokens
  and ~100–200 calls per match. Roles that reason more (e.g. `kalkyl`) are
  the costliest.
- **Gemini free tier is 15 requests/minute** (per-minute, not just per-day).
  A match needs far more, so a naive run hits HTTP 429. Retries handle it:
  429 raises `_RateLimited`, which waits `rate_limit_backoff` (default 20 s,
  ×attempt) instead of the short `retry_backoff`.
- The Gemini endpoint also **hangs on some requests** (stuck in an SSL read,
  ~12% in a 25-request probe). With the old 180 s timeout × 3 tries, one
  decision could block for 9 minutes. Default timeout is now 60 s, and
  `MEIER_TIMEOUT` / `MEIER_RETRIES` (set to 30 / 6 in `run.sh`) trade a shorter
  wait for more attempts. A match then finishes in ~11 min on the free tier.
- The path `…/v1beta/openai/v1/chat/completions` (a doubled `/v1`) still
  answers 200; the base URL is not the problem when a call fails.

## Why every LLM call spawned a full OpenHands conversation (fixed 2026-11-17)

The agent-server's `/v1/chat/completions` is an OpenAI-compatible **shim**: it
starts a whole OpenHands conversation per request (model
`openhands/deepseek-v4.1-flash`, 500 iterations, terminal/editor/browser), with
the Meier prompt as `initial_message`. One call = one conversation. A match
made ~100 calls, so a single run created dozens of conversations (34 in
`/var/openhands/conversations`, clustered 16:18–16:26 UTC).

Root cause: `LLMConfig._from_provider_env()` read the Gemini key **only from
the environment**. `run.sh` exports `GEMINI_API_KEY` from
`/workspace/meier-secrets/gemini.key`, but any run started another way (the
CLI, a test, a hook) had no key in its environment. It then fell through to
the `openhands` provider, whose base URL is the local agent-server shim — and
every call became a conversation.

Fix (two steps): `_read_secret()` now reads the persistent key file
(`MEIER_SECRETS_DIR`, default `/workspace/meier-secrets`) for both
`gemini.key` and `anthropic.key`, so provider selection is the same no matter
how the process starts. Then the `openhands` fallback was **deleted
entirely**: without a key the client raises `LLMError` instead of starting a
conversation. Verified: a decision made with no key in the environment creates
**zero** new conversations, and the app reports `provider: gemini`.

The agent-server itself is still running — this change is about the app no
longer using it as an LLM backend.

## Quota strategy (free tier)

Measured limits for `gemini-3.1-flash-lite` on the free tier (a 429 response
states the exact value):

- **RPM = 15** (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`). Quotas
  are **per project, not per API key**, so every client shares one budget.
- RPD and TPM are not shown without signing in to AI Studio. The free tier
  typically allows ~1 000 requests/day, which is ~10 matches at ~100 calls
  each.

We stay under the limit instead of only reacting to 429s:

- A shared `_RateLimiter` spaces calls to `60 / max_rpm × margin` seconds
  apart (`margin = 1.15`), so we target ~13 calls/min, not 15. The margin
  absorbs the sliding window; sitting exactly on the limit still trips a 429.
- `MEIER_MAX_RPM` sets the ceiling (default 15 for Gemini; `0` disables it).
- The limiter is keyed on `(max_rpm, margin)` and shared process-wide, so all
  agents in a match share one pacer.
- A 429 still raises `_RateLimited` and waits `rate_limit_backoff` (20 s), so
  an unexpected limit degrades gracefully rather than aborting the match.

A match of ~100 calls at ~13/min takes ~8 minutes of pacing, plus the model's
own latency. Lower `MEIER_MAX_RPM` if other projects share the same key.

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
python -m meier.cli announce 2 5 --role david
python -m meier.cli play berit cecilia david
```

## Four documents, four audiences

Documentation drifts. This repo keeps four files that must agree with the
code, and `tests/test_docs.py` enforces it:

| File | Reader | Content |
|---|---|---|
| `README.md` | whoever runs and changes the code | install, CLI, API, config |
| `docs/regler/meier-regler.md` | anyone asking "is this a rule or a choice?" | **canonical rules** – the source of truth |
| `docs/om-meier.md` | a friend who just wants to understand | what it is, rules, players, how the machine is built |
| `docs/agent-model.md` | whoever tunes the model | formulas, calibration, measurements |
| `docs/regler/granskning.md` | anyone doubting the engine | rule-by-rule audit with measurements |

The rules file is canonical. If code and rules disagree, the code is wrong.
If prose in `docs/om-meier.md` and the rules file disagree, the prose is wrong.

`docs/om-meier.md` describes the machine, not what it produced. It must not
contain win rates, bluff frequencies, match lengths or any other result of a
simulation run – those belong in a report, and they age. It may describe
construction: dice weights, reading caps, roster parameters. `tests/test_docs.py`
enforces the boundary (`test_om_meier_describes_the_machine_not_its_results`).
`docs/agent-model.md` is the place for measurements, because its reader tunes
the model and needs them.

`docs/regler/granskning.md` records the rule audit: 19 checks, each measured
in running code. It documents one known deviation – the engine accepts a
lower first bid (as the rules allow), but `BasePolicy` never chooses one.
That is a strategy choice, not a rule break, and it means policy players and
LLM players are not perfectly comparable.

When you change a player parameter, a measured statistic, or the dice weights,
update the affected files **and** let the tests tell you what else broke. The
tests read the markdown as text and compare against `ROSTER`, `describe_params`
and `FACE_WEIGHTS`. They caught real drift already: the README described roles
that had been deleted, the companion doc claimed a bid the policy never makes,
and it called a round "always ending in a life loss" when the Meier full loop
ends one without.

Three rules that keep the companion doc honest:

- **No commands, no installation.** It is prose for non-developers. A test
  asserts the absence of `pip install`, `uvicorn`, `pytest`, `curl`, `export`.
- **Describe the machine, not its output.** The companion doc says what is
  set up: dice weights, reading caps, roster parameters. It does not say who
  wins, how often players bluff, or how long a match runs. Those are results
  of a simulation, they change with the seed, and the project is not hunting
  strategies. Results go in `docs/agent-model.md` or a separate report.
- **Every number that stays is a construction number.** If a figure would
  change when the players play differently, it does not belong here.

## Conventions

- Code comments and docstrings are in Swedish, matching the domain. Keep them.
- Player personality lives in three numbers (`risk`, `press`, `reading`), never
  in the player's name. Names are deliberately neutral: an evocative label makes
  the model play a caricature of the label instead of playing the game, and then
  you cannot tell whether it wins on tactics or on its name. The old roles
  (Ärlig-Adolf, Rackar-Rakel, …) were removed for this reason.
- `axel` has `uses_llm=False` on purpose. He is the deterministic reference the
  others are measured against. Do not "upgrade" him.
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

- In the Agent Canvas runtime the app talks straight to Gemini (or Anthropic),
  **not** to the local agent-server. The old proxy path
  (`http://127.0.0.1:60000`, model `openhands_Default`, header
  `X-Session-API-Key`) is removed: every request there started an OpenHands
  conversation. Claude models are not reachable through the managed proxy key;
  set `ANTHROPIC_API_KEY` to use a real Claude account.
- **Gemini free tier** (verified 2026-11-15): the free tier allows ~10k
  requests/day, which covers ~94 matches (a match is ~106 calls / ~80k tokens).
  Model `gemini-2.5-flash` is closed to new users; use `gemini-3.1-flash-lite`
  (fast, generous quota, good enough for this decision problem) or
  `gemini-3.8-flash` (heavier, sometimes 503 under load). Set the key in
  `GEMINI_API_KEY` to activate. Free-tier prompts may be used by Google to
  improve their models — fine for a dice game, but not for anything sensitive.
  The key lives outside the repo at `/workspace/meier-secrets/gemini.key`
  (mode 600), which `run.sh` reads. `/workspace` is a persistent volume;
  `/home` and `/tmp` are wiped on restart.
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
  **Gotcha (2026-11-15):** a *global* helper (`credential.https://github.com.helper`
  → `~/.openhands/git-credential-helper`) is also configured and returns a
  different 40-char token with no write access. Git tries both in order, so the
  wrong one can win and the push fails with `403 Write access to repository not
  granted` even though `$GITHUB_PUSH_TOKEN` has `push`. The repo-local config now
  clears the list first (`credential.helper ""` then the push-token helper), so
  `GITHUB_PUSH_TOKEN="$GITHUB_PUSH_TOKEN" git push origin main` works. **The
  variable name must appear in the command** — otherwise the secret is not
  exported and the helper sends an empty password, which fails with
  `Invalid username or token`. If the 403 returns, run
  `git config --local --unset-all credential.helper` and re-add
  `""` + the `!f() { echo username=x-access-token; echo password=$GITHUB_PUSH_TOKEN; }; f`
  entry. As a fallback, `git push
  "https://x-access-token:${GITHUB_PUSH_TOKEN}@github.com/aieuren/meier-simulator.git" main`
  bypasses the helper entirely.
  **Gotcha (2026-11-18):** putting `$GITHUB_TOKEN` in the remote URL also fails
  (403) — that token has read-only access here. Push must go through
  `GITHUB_PUSH_TOKEN`. Don't rewrite the remote; just run
  `GITHUB_PUSH_TOKEN="$GITHUB_PUSH_TOKEN" git push origin main` and let the
  repo-local credential helper inject it.
  **Gotcha (2026-11-08):** a token baked into the remote URL *shadows* the
  credential helper — git uses the URL credentials and never asks the helper.
  Symptom: `Invalid username or token` or `403` even though `GITHUB_PUSH_TOKEN`
  is fine. Fix: `git remote set-url origin https://github.com/aieuren/meier-simulator.git`
  (no credentials in the URL), then push and let the helper inject the token.
- The user has delegated version control: from now on, commit and push to
  `main` yourself when the work is green and complete — no need to ask first.
- Secrets for this conversation live in the agent-server, not the shell:
  `GET/PUT /api/settings/secrets[/{name}]` manages them, and
  `POST /api/conversations/{id}/secrets` attaches one to a running conversation.
  A secret added mid-conversation is not injected until it is attached this way.
  Names must be valid shell identifiers (letters, digits, underscore) — a hyphen
  makes the value unusable as an environment variable.

## Autostart efter container-vila (self-service)

Sandlådan stängs av efter 20 minuters inaktivitet
(`OH_RUNTIME_IDLE_TIMEOUT_SECONDS=1200`). Vid nästa besök startar containern om,
men webbappen gör det inte — och den installeras under `~/.openhands`, som
ligger på overlay-filsystemet och nollställs. Bara `/workspace` är beständigt
(ext4).

Lösningen är en **SessionStart-krok** i repot: `.openhands/hooks.json` +
`.openhands/hooks/start_meier.sh`. Den gör två saker: installerar om
Canvas-panelen och startar webbappen om den inte kör. Båda behövs, eftersom
både panelregistret och appen bor i miljöer som nollställs.

Varför just den här vägen fungerar (verifierat 2026-11-17):

- Agent-servern stödjer hook-typerna `pre_tool_use`, `post_tool_use`,
  `user_prompt_submit`, `session_start`, `session_end`, `stop`
  (`HookConfig` i `/openapi.json`).
- En projekt-lokal `.openhands/hooks.json` läses **inte** automatiskt när en
  konversation skapas direkt mot API:t (testat: `hook_config: null`, ingen
  `HookExecutionEvent`).
- Men **Agent Canvas läser den**: `hooks-service` i Canvas-frontenden anropar
  `POST /api/hooks` med arbetsmappen och skickar svaret vidare som
  `hook_config` i `StartConversationRequest` (`agent-server-adapter`:
  `o.hook_config ? s.hook_config = o.hook_config : e.workspaceHookConfig && …`).
  Kedjan är alltså: `.openhands/hooks.json` → Canvas → `hook_config` → körs.
- Fälten `load_project_hooks` och `load_user_hooks` finns på `/api/hooks` men
  defaultar bara till sant för den *explicita* hämtningen; en ren
  `POST /api/conversations` utan `hook_config` kör inga krokar.

Kroken är idempotent: den kollar `/api/health` först och gör inget om appen
redan svarar. Den återanvänder `run.sh --background`, som redan löser
Gemini-nyckeln från `/workspace/meier-secrets/gemini.key` och installerar
saknade paket. Logg: `/workspace/meier-logs/start-hook.log`.

Fullt verifierat skarpt: panel avinstallerad + app nere (`HTTP 000`) →
konversation skapad med `hook_config` → panel återinstallerad (`enabled=true`)
och app uppe (`HTTP 200`), `HookExecutionEvent` i loggen. Kroken körs också vid
återupptagning av en befintlig konversation (`POST /api/conversations/{id}/run`).

### Vad som INTE startar appen (utrett 2026-11-17)

Allt nedan är testat och fungerar **inte** som autostart vid containerstart.
Listan finns för att slippa upprepa felsökningen.

- **SessionStart-kroken kör inte vid kallstart.** Den kräver att en konversation
  skapas *med* `hook_config`. Att bara öppna en konversation (`GET
  /api/conversations/{id}`, som Canvas gör) kör den inte — testat: appen förblev
  `HTTP 000`.
- **Ingen startkrok i agent-servern.** `openhands-agent-server --help` visar
  bara `--host/--port/--reload/--import-modules/--extra-python-path`. Inga
  träffar på `OH_STARTUP`, `startup_command`, `runtime_services`, `prestart`,
  `boot_command` i binären.
- **`POST …/runtime/reprovision`** svarar `200 {"runtime_status":"available"}`
  men startar inte appen.
- **`.openhands/setup.sh` körs inte** — varken vid kallstart eller reprovision.
- **App-backend (`backend` i manifestet) är fel verktyg.** Servern har
  `canvas_app_backend_enable_lifecycle_v1` och endpoints
  `/api/canvas-extensions/installed/{name}/backend/{prepare,start,stop,logs}`,
  och docsen säger "Agent Canvas starts the app through the server lifecycle
  automatically". Men en backend är en **nedladdad binär** (`.tar.gz` med
  `sha256`, `argv`), avsedd för appar som *äger* sin tjänst. Meier är redan en
  Python-app som körs via `run.sh`; att paketera om den som binär artifact vore
  ett stort ingrepp för samma resultat som panelens auto-start ger.
- **Idle-timern ska inte manipuleras.** `GET /server_info` visar `idle_time`, och
  det är "the exact signal runtime-api polls to decide when a sandbox is idle
  enough to pause/reap" (officiell cookbook). Ett bash-anrop via API:et
  nollställer timern — men att polla för att hålla sandlådan vaken kringgår
  plattformens design och görs **inte**.

**Det som faktiskt löser användarens önskan:** panelens auto-start (se
"Startpanelen i Agent Canvas" ovan). Laddar Canvas den aktiverade panelen kör
`activate()` en health-koll och startar appen om den är nere.

## Startpanelen i Agent Canvas (self-service)

The user wanted a way to start the web app without asking the agent. The answer
is a Canvas app at `canvas-app/`: a page in the Canvas UI with Start/Stop/Refresh
buttons. It calls the agent-server bash endpoint through
`host.agentServer.request`, so Canvas handles auth and **no secret lives in the
app code**. No own server is needed.

- Install/update: `./canvas-app/install.sh` (uses `SESSION_API_KEY` from
  `/proc/1/environ`). Install leaves the app disabled; the script enables it too.
- **The panel self-starts on activate.** Canvas calls `activate(host)` whenever it
  loads the enabled app, and the panel then runs `CMD_ENSURE_START`: a health
  probe that exits early when the app answers and otherwise runs the full
  `CMD_START`. So after a container wake, simply loading Canvas brings the app
  back without opening the panel or pressing anything. The health-first check is
  what keeps it safe — a plain `CMD_START` would kill and restart a live match on
  every page load.
- The panel lives in the agent-server home (`~/.openhands/canvas-extensions/`),
  which is **not** a persistent volume. Re-run `install.sh` after a restart.
- The bash endpoint's shell **does** have `RUNTIME_URL`, so the panel can show
  the public web address.
- Gotcha: `pkill -f 'uvicorn …'` kills its own shell because the pattern matches
  the command line. Use the bracket trick `pkill -f '[u]vicorn meier.web.app'`.
- Gotcha: `pkill` returns at once, but the dying server still answers health
  checks for about a second. Pressing Stop then Start therefore made `run.sh`
  see a live port, skip the start, and leave nothing running. The panel's Start
  now stops, waits for the port to go quiet, and only then calls `run.sh`.
- Install from Git works only for a **public** repo. The server fetches the
  source without credentials, so a private repo fails with "Failed to fetch
  extension from github:…". Install is pinned to the commit it resolved; push a
  fix, then reinstall to move the pin.
- Gotcha: **Agent Canvas is a separate frontend mounted at `/canvas`.** The root
  app (`app.all-hands.dev/`) has no `/extensions/…` route and no sidebar entry
  for App pages, so a page URL without the prefix looks like a 404 even though
  the install is fine. Both are SPAs that answer 200 for any path, so a 200
  proves nothing — check the route manifest instead. Correct URLs:
  - Panel: `/canvas/extensions/meier-startpanel/meier-start`
  - Apps manager: `/canvas/customize` → Apps (also `/canvas/apps`)
- `nav_label` in the page manifest is dropped by the agent server; the sidebar
  falls back to the page `title`. Setting `nav_label` has no effect.
- Gotcha (the real reason the panel "disappears"): the installed-app registry
  lives in the agent-server home (`~/.openhands/canvas-extensions/`), which is on
  the **ephemeral overlay** filesystem, not on the persistent `/workspace` ext4
  volume. A container restart wipes it, so `GET /api/canvas-extensions/installed`
  returns `[]` and the Canvas sidebar entry is gone. The SessionStart hook above
  reinstalls the panel on every new session, so this now heals itself; to do it
  by hand, run `./canvas-app/install.sh`.
- The Canvas UI is **hard-locked to OpenHands Cloud**: its HTML sets
  `window.__AGENT_CANVAS_LOCK_TO_CLOUD__="https://app.all-hands.dev"` and
  `__AGENT_CANVAS_BASE_PATH__="/canvas"`. Apps are only available with a
  **local** backend — the official docs state "Apps … are currently available
  with supported local backends. They are not available when an OpenHands Cloud
  backend is active." So the sidebar entry depends on the active backend being
  this sandbox's agent server, and on the panel being installed there.
- The user-visible error "Not available / This app is disabled, missing, or does
  not provide this page" means the backend has no such app installed. It is
  **not** the same as the plain 502 "Bad Gateway" you get from the public web
  URL when the Meier app itself is down — that is a separate, expected condition
  the SessionStart hook fixes.

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

## The machine: four players, one policy core (roster)

The roster was rebuilt. The old roles (`arling`/`trygg`/`kalkyl`/`rackar`) are
**gone** — replaced by four neutral-named players in `meier/agents/roster.py`:

| Key | Name | Risk | Press | Reading | LLM |
|---|---|---:|---:|---:|---|
| `axel` | Axel | 0.50 | 0.50 | 0.00 | no (BASE) |
| `berit` | Berit | 0.25 | 0.25 | 0.15 | yes |
| `cecilia` | Cecilia | 0.50 | 0.45 | 0.50 | yes |
| `david` | David | 0.65 | 0.60 | 0.35 | yes |

- **Names are neutral on purpose.** A value-laden label ("Rackar-Rakel") tells
  the model who to *be*, so it plays a caricature and you cannot tell whether a
  profile wins on its tactics or its label. Personality lives in the params.
- **Axel is BASE** — deterministic, non-reading, **no LLM**. He is the fixed
  measuring stick the others are compared against. He is allowed to lose often.
- **The policy owns the move.** `StrategicAgent` (`meier/agents/strategic.py`)
  computes the move with `BasePolicy`. The LLM has **two** jobs, neither of which
  is the move itself:
  1. **Narrate the line** (`_narrate`) — say what the player says.
  2. **Read the opponents** (`OpponentReader`, `meier/agents/reader.py`) — turn
     the secretary's public numbers into an `OpponentProfile`.
  The profile is an **input** to the policy, not a free choice: the policy still
  computes the move. The stored `reasoning` is the policy's machine reason plus
  the profile label and confidence (e.g. `"EV=-0.386 liv | bild av David:
  försiktig (press 0.10, konf 0.40)"`).
- **Secretary vs reader.** `OpponentTracker` (`meier/opponents.py`) is the
  secretary: it *records* public play in numbers (bids, reveals, bluffs, calls,
  passes) and never interprets. `OpponentReader` is the reader: the **LLM decides
  alone** what the numbers mean. The reader is fed only
  `tracker.evidence(player)` — never the session log — so it cannot see hidden
  dice. Ask "who judges?" and the answer is: the LLM. The secretary only writes.
- **`OpponentProfile`** has `risk`, `press`, `predictability`, `kind`,
  `confidence`, `source`. `source` is `"llm"`, `"statistik"` (fallback without
  LLM) or `"population"` (no data). Values are clamped to 0–1 so a garbled LLM
  reply cannot leak junk into decisions.
- **`confidence` is capped by evidence at the table, not by the LLM's self-report.**
  `OpponentTracker.evidence_strength()` = `reveals / (reveals + 3)` over the whole
  match (every player's settled calls), and `reader.profile()` takes
  `min(llm_confidence, strength)`. The same cap applies to the arithmetic fallback
  in `statistical_profile`. So an early guess cannot claim to be certain: one call
  gives 0.25, three give 0.50, nine give 0.75. Both `table_reveals` and `strength`
  are also sent to the model in the summary so it knows how thin the evidence is.
- **Plain-language view.** `OpponentProfile.describe()` renders the numbers as a
  sentence with the percentages in parentheses (e.g. *"Försiktig: bluffar nästan
  aldrig, synar sällan och är mycket förutsägbar (risk 20 %, press 10 %,
  förutsägbarhet 90 %; gott underlag)."*). `describe_params()` does the same for a
  player's own known character in the roster list. Presentation only — never an
  input to a decision. The web app shows each agent's picture of the others in
  the game tab, fed by `Session._views()` (which drops `source == "population"`
  entries so only pictures with evidence are shown).
- **The profile is cached per opponent** and recomputed only when new evidence
  becomes public (a reveal). So a match makes a handful of reader calls per
  opponent, not one per decision.
- **Relative scaling, never absolute.** `profile_factor` maps `press` to a factor
  around 1.0 centred on `NEUTRAL_PRESS = 0.5`, damped by `confidence`; the agent's
  own `reading` then scales how much of that signal it wants. This preserves the
  `reading = 0 → exact CALL_PRIOR` invariant. Absolute bluff rates here are ~0.72
  for everyone, so feeding them in raw inflates every opponent — the factor must
  stay relative.
- **`risk` is wired into bidding too, not just `press`.** `risk_factor` maps the
  opponent's `risk` to a factor around 1.0 centred on `NEUTRAL_RISK = 0.5`; it
  flows as `opponent_factor` into `BasePolicy.decide_bid()` and on to `_p_called`,
  which scales the chance the bid gets called. A calling opponent makes bluffing
  expensive, so the agent moves closer to the truth. Measured: 5 % call rate →
  factor 0.31 → bluffs in 20/20 spots; 19 % → 0.93 → 14/20; 45 % → 1.93 → 5/20.
  `press` adjusts belief about a bid (`_opponent_prior`), `risk` adjusts the
  chance of being called (`_p_called`) — different terms, both live.
- **The same absolute-scale trap hits `risk`.** Raw call rate is ~0.19 for every
  role, so feeding it straight onto the 0–1 scale makes every opponent look timid
  and the agent bluffs wildly against all of them. `POPULATION_CALL_RATE = 0.19`
  plus `OpponentTracker.call_ratio()` keep it relative: ratio 1.0 = "calls as much
  as people usually do". The LLM summary states this reference point too, so the
  model does not read 19 % as "never calls".
- **Evaluation runs without LLM.** `play_match(..., with_llm=False)` and
  `cli match --no-llm` give a deterministic match: the reader falls back to the
  secretary's arithmetic. Fast (milliseconds vs minutes). Use `--no-llm` for
  statistics; turn LLM on when the lines and the reading should be real.
- **The opponent model is now wired into the engine.** `Session.tracker` feeds
  the shared `OpponentTracker` as events become public; `make_players()` gives
  every reading player the same tracker (one shared view of the table).
- **Monkeypatch seam:** `play_match` builds agents through `match._new_agents`
  (LLM on) or `match._new_agents_no_llm` (LLM off). Tests patch `_new_agents`.
- **Provider:** Anthropic Claude if `ANTHROPIC_API_KEY` is set, otherwise Gemini
  via `GEMINI_API_KEY`. In this sandbox only the Gemini key is present, so the
  fallback is what runs. `LLMConfig.from_env()` reports which is active.
- **The Gemini proxy hits a 429 quota.** When it does, `LLMError` surfaces after
  three retries and a full LLM round can hang for many minutes. Do not use a live
  session to verify model wiring while the quota is exhausted — a session-level
  check needs dozens of calls. Verify the mechanism with a fake LLM instead:
  `tests/test_reader.py` has a `FakeLLM` that returns fixed JSON, and an
  end-to-end `Session` with a fake client shows the confidence curve in seconds.
  Check quota first with a one-shot `LLMClient().complete("Svara kort.", "hej")`.

### Running an evaluation

```bash
# Fast, deterministic self-play (no LLM) — the default for measurement
python3 -m meier.cli match axel berit cecilia david --count 200 --seed 1000 \
    --workers 4 --no-llm --out /tmp/meier_eval.jsonl
```

Baseline (200 matches, four players, chance 25 %): Berit 28 %, Cecilia 29.5 %,
Axel 23.5 %, David 19 %. David is weakest, as expected with the highest `press`.
