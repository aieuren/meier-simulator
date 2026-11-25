# AGENTS.md

Repository memory for the Meier AI-agent project.

## What this project is

A Python library plus FastAPI web app where independent, LLM-based AI agents
play the Swedish dice game Meier. The core deliverable: given the outcome of
a two-dice roll, an agent decides how the player responds (truth, higher, or
lower claim). Multiple agents with distinct roles can also play full games.

## Layout

- `meier/rules.py` – game rules. Single source of truth for the ranking order,
  claim comparison, and call resolution. Change rules here only. The dice are
  elongated (length/width = `DIE_ELONGATION` = 1.3). `_face_weights` derives
  each face weight from its solid angle seen from the centre of mass, so faces
  3-6 (the long sides) are 1.562x as likely as 1-2 (the square end faces).
  Solid angle is the chosen model (2026-11-22); the older area model gave 1.3
  and was dropped. Every probability in `meier/policy.py` is derived from
  `FACE_WEIGHTS`, so changing the die shape moves all of them. See
  `docs/agent-model.md` §3.0. Odd and even stay equally likely, since 1/2 sit
  on the ends (one odd, one even).
- `meier/llm.py` – LLM client, Gemini only. Key via
  `GEMINI_API_KEY`/`GOOGLE_API_KEY` (or `$MEIER_SECRETS_DIR/gemini.key`).
  This is the only provider; do not add another one.
  There is no fallback to the OpenHands agent-server. Gemini uses the
  OpenAI-compatible endpoint
  `https://generativelanguage.googleapis.com/v1beta/openai`.
  `LLMClient.last_usage` holds the token count from the last call. Without a
  key, `LLMConfig.from_env()` raises `LLMError`.
- `meier/game.py` – multi-agent game engine. Keeps each agent isolated; no agent
  sees another's secret dice.
- `meier/session.py` – interactive session: full flow to a call (roll → raise
  (new shake) / pass → forced raise → call), random player order, and the log.
  The log is built downward: each shake starts with a `kind="roll"`
  entry (the dice, pure input), then one `kind="action"` entry per answer (claim,
  raise, pass, or call), and after a call a `kind="life"` entry (who lost how
  many lives, and how many remain). Every `kind="life"` entry also carries a
  `standings` snapshot (each player's name, role and remaining lives, in seating
  order) so the UI can show the life tally right after each call. When the match
  ends, `_finish()` appends one `kind="game_over"` entry naming the winner, and
  `to_dict()` adds `standings` and `winner` at the top level (the game-over row is
  not counted as a player action by the analysis). Every action entry carries
  `accepted_claim`
  (the claim the player answers) next to `claim` (the claim they then say), so the UI
  can show "Slår över X, säger Y" as separate parts. `to_dict` also reports
  `order` and `starter` so the UI can show the seating and who begins.
  `advance()` does one gated step;
  `run_to_round_end()` runs to the end of the current round (a call, or a new
  round after Meier), `run_to_call()` runs the whole flow to the next call, and
  `run_to_end()` plays the whole match to a winner.
  The web UI moves the *Ett drag* button into the log so it sits under the
  latest dice roll; the *Till slut på runda*, *Till syn* and *Hela matchen*
  buttons run multiple steps at once (all four controls are disabled while a
  call runs). When a raise is not strictly higher than the previous claim,
  `_enforce_claim` replaces it with the smallest legal raise.
- Call responsibility: the player who loses a life on a call is the one who
  *holds* the claim — the last player to say or pass the claim — not necessarily the
  one who first set it. `Session.holder` tracks this and is updated on every claim,
  shake without a look, forced raise, and pass. The next round starts with the active
  player *before* the loser in turn order (`_previous_active`). `meier/game.py`
  keeps the same `holder` logic in its text log.
- `meier/agents/base.py` – `Agent`/`Role` base classes.
- `meier/agents/player.py` – `MeierPlayerAgent` and the role registry. The agent
  is the source of truth for legality: `_coerce_claim` and `_coerce_unseen_claim`
  keep every claim valid and strictly higher, and `Session._enforce_claim` is the
  engine's backstop. The tests guard the rules.
- `meier/web/app.py` + `meier/web/static/` – web UI and JSON API. The UI has
  five tabs: *Rollerna* (one card per player, with name, description, and
  style), *Enskild spelare* (one player answers a roll),
  *Spelarna möter varandra* (the interactive session), *Matchserie* (run a
  series of matches and show per-player statistics plus a downloadable JSONL
  protocol), and *Analys* (ask questions about loaded protocols).
  `/api/roles` returns each role's `style` too, so the
  first tab can show the full character text. Tab switching just toggles
  `[hidden]` on `.tab-panel`; note the `.tab-panel[hidden] { display: none }`
  rule — a bare `display: grid` would otherwise override `hidden` and show every
  panel at once. A match series is hundreds of LLM calls and takes minutes, so
  `/api/matches/run` starts a background thread and returns at once; the client
  polls `/api/matches/status` (field `running`) and renders matches as they
  finish. Only one series runs at a time (a second start gives 409). The request
  field `workers` (1–8) plays several matches at once; the JSONL file is written
  line by line as matches finish, so the download works mid-run. Every
  finished match is committed and pushed to the log repo (see below); the
  outcome lands in the status field `push_status`. Check-in is not optional:
  the `check_in` request field is ignored, and the series only falls back to
  local disk when the repo cannot be reached. A push failure never fails the
  run.
  `/api/announce` takes `previous_claim`. With no previous claim the player has
  peeked and simply announces. With a previous claim the call is a *slag* and
  goes through `announce_shake`, so the look choice is not skipped. 21 –
  Meier cannot be raised: that request returns 400, and Meier is left out of
  the "tidigare påstående" list in the UI.
- `meier/match.py` – batch play of many full matches between the roles, for
  strategy analysis. `play_match` plays one match to the end via
  `Session.play_to_end()` and returns a `GameRecord`; `run_matches` yields a
  series (`workers>1` plays matches in parallel threads); `write_jsonl`/`read_jsonl` persist one
  match per line; `summarize` aggregates a series per role (win rate, bluff
  rate, raise/call rates, call success, lives lost). `GameRecord.events` is the
  full session log (`LogEntry.to_dict()`), which carries the analysis fields
  (`accepted_claim`, `proposed`, `corrected`, `unseen`, `lives_lost`, `lives_left`,
  `actor_lives`, `active_players`, `caller_loses`). Tests swap the module-level
  `_new_agents` factory for scripted agents.
- `meier/legacy.py` – reads protocols written before the rename (`bid`, `bud`,
  `bids`, `blind`). `upgrade_record` rewrites an old record to the current keys
  at load time, so historical JSONL files keep working and are never rewritten
  on disk. Both `read_jsonl` and `analysis.parse_jsonl_text` call it. Do not
  delete it while old logs exist under `meier-logs/`.
- `meier/cli.py` – command line entry points (`announce`, `decide`, `play`,
  `session`, `match`, `summarize`).
- `meier/analysis.py` – analysis of collected match protocols. `build_digest`
  turns a list of `GameRecord.to_dict()` records into a compact summary
  (per-role stats from `summarize`, plus action/claim/outcome distributions and a
  per-match series) so it fits in the model context — the full event logs do
  not. `render_digest_text` formats it for the prompt (and for the UI). `ask`
  sends a question with the digest and expects JSON
  (`{"answer", "chart", "followups", "cannot_answer"}`); `_clean_chart` drops
  charts the frontend cannot draw, and `cannot_answer` (a short Swedish note,
  else null) is surfaced as a warning when the question needs detail the digest
  does not carry. `render_digest_text` also ends with a "VAD SAMMANSTÄLLNINGEN
  INTE INNEHÅLLER" section listing what the digest omits (raw rolls, per-claim
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

### Vad "högt" och "lågt" betyder i prosan

Ett **högt** påstående står högt i ordningen, nära Meier. Ett **lågt** står
nära 31. Riktningen är alltså samma som i "21 är högst". `64` är högre än
`63`, och `11` är högre än `64`.

Följden är lätt att vända fel, och det har hänt tre gånger:

- **Synen lyckas bättre på höga påståenden.** `CALL_ODDS[claim].p_win` faller
  monotont längs `rules.RANKING`: 11 → 96 %, 64 → 65 %, 63 → 58 %, 31 → 0 %.
  Tärningarna når sällan upp till ett starkt påstående, så en syn på 11 vinner
  oftast.
- **Ett lågt påstående är lätt att slå över**, eftersom nästa spelare lätt
  hittar något högre (31 → 95 % chans till ett sant påstående ovanför). Ett
  högt påstående är svårt att slå över men synas oftare (`p_called` stiger med
  nivån: 31 → 10 %, 66 → 38 %, Meier → 50 %).
- **Livsvärdet, inte vinstchansen, avgör draget.** En förlorad syn kan kosta
  två liv vid Meier, så "synen vinner oftast" räcker inte som skäl.

`test_axel_section_says_calls_get_easier_on_higher_claims` låser riktningen i
texten. Skriv aldrig "chansen faller ju högre påståendet är".

## Slå = a fresh shake, not a peek (gotcha)

The three choices are: slå (shake the cup again and name a higher claim
without looking), syna (lift the lid) and skicka (pass the same claim).
So slå is *not* a peek at the old dice — the player shakes a brand new roll, and
the claim must be strictly higher than the previous one whatever the dice show.
This is why the engine logs a fresh `kind="roll"` entry before every slå, and
why `announce_unseen` (not `announce`) is used for it. A slå that is not strictly
higher is corrected to the smallest legal raise: `Session._enforce_claim`.

## Two different raises — do not conflate them (gotcha)

The docs used to claim "the raise is always one step, never more". That is true
of exactly one of the two decisions. Keep them apart:

- `decide_claim(shown)` — claimer *has* seen the dice. A bluff over `shown` is
  always exactly one step above it (`min(higher_options(shown))`), at every
  `unpredictability`. Higher claims get called more often, so a longer jump is
  pure downside.
- `decide_raise(claim)` — shake without a look, dice unseen. The minimum legal raise is
  safest. With probability `unpredictability` the agent instead picks a random
  higher option (up to Meier), so it cannot be read as "always the minimum".
  There is no "true level" to sit just above when the dice are unknown.

Measured on 80 no-LLM matches: 63.3 % of raises were one step, 36.7 % were
more, up to 18. So "always one step" was wrong for the table as played.

Guarded by `tests/test_policy.py::test_unpredictability_makes_unseen_raises_vary` and
`::test_seen_claim_bluff_is_always_exactly_one_step`, plus
`tests/test_docs.py::test_om_meier_does_not_claim_raises_are_always_one_step`.

## Forced raise (full lap) = a fresh shake too (gotcha)

When the cup comes back to the claimer after a full lap, the rule we play is
that the dice are re-rolled — not just a higher number said over the old
dice. The claimer may then look at the new dice or claim without looking; both are allowed,
just like any other claim. So `Session._resolve_raise` and `Game._play_round`
roll new dice, log a fresh `kind="roll"` entry, and call
`MeierPlayerAgent.announce_forced` (which asks the model "look or not?" via
`_forced_choice_context`, then delegates to `announce` or `announce_unseen`).
`pending_dice` must be updated to the new roll, otherwise a later syna would be
judged against the stale dice. The holder must also become the claimer in
`Game._play_round` (Session already does `self.holder = self.claimer`) — miss it
and a later syna blames the wrong player. A forced raise is `unseen=True` only
when the claimer chose not to look. (`höja` is still a claim, so it counts in
`BID_ACTIONS`; raises without a look count as `unseen`, not bluffs.)

## Prose style for docs: no bold

Do not bold words in running text. It was used for emphasis on nearly every
noun and made the docs read like a highlight reel. Write plain sentences
instead; if a point needs weight, give it its own sentence or paragraph.

Bold is still fine for table row labels and short list labels, where it marks
structure rather than emphasis.

## The game says "påstående", and the order is syna, slå, skicka

The word for what a player says about the dice is **påstående**. The older
Swedish term is out of the game, the code, the docs and the tests; do not
reintroduce it. In code the field is `claim`, the action label is `"påstå"`, and
the actor is `claimer`. Unrelated verbs (`bjuda`, `erbjuda`, `förbjuda`) are
ordinary Swedish and stay as they are.

The current rules PDF (fetched 2026-11-24) lists the three answers in the order
**syna, slå, skicka vidare**, and that order is the presentation order in
`legality.RESPONSES`, in the prompts and in the UI. It also states that the
player who *slår* may always lift the lid and look at their own dice; not looking
is a deliberate choice. `tests/test_docs.py` guards both the word and the order
inside the PDF.

## The rules file describes the game, not the code

`docs/regler/meier-regler.md` holds the rules of Meier and nothing else. Keep
implementation details out of it: no module or field names, no `DIE_ELONGATION`,
no strategy choices, no notes about how the engine or an agent behaves. Those
belong in `docs/agent-model.md` or `docs/regler/granskning.md`.

Two things bridge the gap to the repo without turning the file into a spec.
One is the wording note: the PDF and this text both say "påstående", and the
older Swedish term is gone from the game, the code and the docs. The
other is the short closing section "Några tolkningar för denna simulator",
which lists the open choices (passing without a look, raising without a look, bluff frequency,
die shape) as choices, not rules. Keep that section to a handful of bullets and
link out for detail.

## The friend doc is `docs/om-meier-simulatorn.md`

It used to be `docs/om-meier.md`, which readers mistook for a document about
the game rather than about the simulator. The file name and the title now say
"meier-simulatorn". The test constant is still `OM_MEIER`.

The friend doc must track the architecture, not an older one. It once claimed
the model only phrases the move and a shared calculation decides it. That was
wrong after the LLM took ownership of the move. When you change who decides
what, update this file in the same commit. `test_om_meier_says_the_model_makes_the_move`
guards the specific claim.

## The `line` is built locally, never written by the model

The model only produces the move (`claim`, `action`, `unseen`). The spoken `line`
is assembled in code from the move: `StrategicAgent._say` for a claim,
`_say_action` for syna/skicka/slå, and a fixed string for the look-or-not
choice. No prompt asks for `"line"` any more, and any `"line"` in a model reply
is ignored.

This keeps the line short and predictable, and it stops the model from inventing
wording (it used to slip back to the older term after the rename; guard tests
in `tests/test_docs.py` keep that term out of the docs). When you add a
new decision path, build its line the same way — do not add `"line"` to the
prompt. `tests/test_strategic.py` has three tests that lock this down: one feeds
a reply containing `"line"` and asserts it is dropped, one asserts no prompt
mentions `"line"`, and one checks `choice_line` stays local while
`choice_reasoning` keeps the model's text.

## Reasoning is logged for every decision (for later analysis)

The model's free-text `reasoning` is stored on every logged decision, so it can
be mined later (e.g. by an LLM). Two gaps used to exist and
are now closed:

- syna was logged with empty `line`/`reasoning`. `Session._resolve_call`
  now takes the caller's `ActionDecision` and stores its `line`/`reasoning` on
  the log entry and on the `CallResult` (shown in the web UI).
- Forced raise (look or not?) discarded the choice's motivation.
  `_wants_unseen_forced` now returns an `ActionDecision` (`action` is `"titta"`
  or `"unseen"`), and `announce_forced` carries `choice_line`/`choice_reasoning`
  onto the announcement, the log entry and `Game`'s text log.

So `Announcement.choice_line`/`choice_reasoning` and
`LogEntry.choice_line`/`choice_reasoning` are populated for `höja` rows.
Note: `build_digest` does not include reasoning — to analyse it you must
feed selected raw events to the model, not the digest.

Investigated a reported "raise after an unseen slå" bug: it is not reproducible.
`accepted_claim` is the claim the player *answers*, so a raise showing
`accepted=52, claim=61` is just the forced raise at the end of a full lap, not a
double raise. A property check over 500 random matches (200 for `claim >=
accepted`, 300 for the `slå → höja` pattern) found 0 violations, and every `slå`
is `unseen=True`.

## The OpenHands agent-server proxy is gone (removed 2026-11-17)

Earlier the app could fall back to the local agent-server proxy
(`http://127.0.0.1:60000/v1/chat/completions`, model `openhands_<profile>`).
That path is deleted. Every request there started a whole OpenHands
conversation, so a match filled `/var/openhands/conversations` with hundreds of
conversations. `LLMConfig._from_provider_env()` now accepts only `gemini` and
raises `LLMError` when no key exists.

Consequences to keep in mind:

- There is no proxy fallback. Without `GEMINI_API_KEY`
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

The fallback left conversations in two places, and the Agent Canvas sidebar
lists the cloud one:

1. Local agent-server – `/var/openhands/conversations/<hex32>/`. The
   agent-server builds an in-memory registry from this directory at start, so
   deleting a directory by hand does not lower `/api/conversations/count` until
   the next restart. Delete through the API to keep the registry in sync:
   `DELETE http://127.0.0.1:60000/api/conversations/<uuid>` with header
   `X-Session-API-Key: $SESSION_API_KEY` (the key is in pid 1's environ).
2. OpenHands Cloud – the sidebar's list. These are real cloud objects, so
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
- Real match via the web app (Gemini `gemini-3.1-flash-lite`, 8 rounds):
  62 018 tokens over 82 calls (~756 tokens/call). Earlier log
  files show 94–197 calls per match (8–13 rounds), so budget ~60–120k tokens
  and ~100–200 calls per match. Roles that reason more (e.g. `kalkyl`) are
  the costliest.
- Gemini free tier is 15 requests/minute (per-minute, not just per-day).
  A match needs far more, so a naive run hits HTTP 429. Retries handle it:
  429 raises `_RateLimited`, which waits `rate_limit_backoff` (default 20 s,
  ×attempt) instead of the short `retry_backoff`.
- The Gemini endpoint also hangs on some requests (stuck in an SSL read,
  ~12% in a 25-request probe). With the old 180 s timeout × 3 tries, one
  decision could block for 9 minutes. Default timeout is now 60 s, and
  `MEIER_TIMEOUT` / `MEIER_RETRIES` (set to 30 / 6 in `run.sh`) trade a shorter
  wait for more attempts. A match then finishes in ~11 min on the free tier.
- The path `…/v1beta/openai/v1/chat/completions` (a doubled `/v1`) still
  answers 200; the base URL is not the problem when a call fails.

## Why every LLM call spawned a full OpenHands conversation (fixed 2026-11-17)

The agent-server's `/v1/chat/completions` is an OpenAI-compatible shim: it
starts a whole OpenHands conversation per request (model
`openhands/deepseek-v4.1-flash`, 500 iterations, terminal/editor/browser), with
the Meier prompt as `initial_message`. One call = one conversation. A match
made ~100 calls, so a single run created dozens of conversations (34 in
`/var/openhands/conversations`, clustered 16:18–16:26 UTC).

Root cause: `LLMConfig._from_provider_env()` read the Gemini key only from
the environment. `run.sh` exports `GEMINI_API_KEY` from
`/workspace/meier-secrets/gemini.key`, but any run started another way (the
CLI, a test, a hook) had no key in its environment. It then fell through to
the `openhands` provider, whose base URL is the local agent-server shim — and
every call became a conversation.

Fix (two steps): `_read_secret()` now reads the persistent key file
(`MEIER_SECRETS_DIR`, default `/workspace/meier-secrets`) for
`gemini.key`, so key selection is the same no matter how the process starts. Then the `openhands` fallback was deleted
entirely: without a key the client raises `LLMError` instead of starting a
conversation. Verified: a decision made with no key in the environment creates
zero new conversations, and the app reports `provider: gemini`.

The agent-server itself is still running — this change is about the app no
longer using it as an LLM backend.

## Quota strategy (free tier)

Measured limits for `gemini-3.1-flash-lite` on the free tier (a 429 response
states the exact value):

- RPM = 15 (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`). Quotas
  are per project, not per API key, so every client shares one budget.
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
`MeierPlayerAgent._coerce_claim` / `_coerce_unseen_claim` keep every claim valid and
strictly higher, and `Session._enforce_claim` is the engine's backstop for the claim
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
| `docs/regler/meier-regler.md` | anyone asking "is this a rule or a choice?" | the rules only – no code, no strategy, no modelling |
| `docs/om-meier-simulatorn.md` | a friend who just wants to understand | what it is, rules, players, how the machine is built |
| `docs/agent-model.md` | whoever tunes the model | formulas, calibration, measurements |
| `docs/regler/granskning.md` | anyone doubting the engine | rule-by-rule audit with measurements |

The rules file is canonical. If code and rules disagree, the code is wrong.
If prose in `docs/om-meier-simulatorn.md` and the rules file disagree, the prose is wrong.

`docs/om-meier-simulatorn.md` describes the machine, not what it produced. It must not
contain win rates, bluff frequencies, match lengths or any other result of a
simulation run – those belong in a report, and they age. It may describe
construction: dice weights, reading caps, roster parameters. `tests/test_docs.py`
enforces the boundary (`test_om_meier_describes_the_machine_not_its_results`).
`docs/agent-model.md` is the place for measurements, because its reader tunes
the model and needs them.

`docs/regler/granskning.md` records the rule audit: 19 checks, each measured
in running code. It documents one known deviation – the engine accepts a
lower first claim (as the rules allow), but `BasePolicy` never chooses one.
That is a strategy choice, not a rule break, and it means policy players and
LLM players are not perfectly comparable.

When you change a player parameter, a measured statistic, or the dice weights,
update the affected files and let the tests tell you what else broke. The
tests read the markdown as text and compare against `ROSTER`, `describe_params`
and `FACE_WEIGHTS`. They caught real drift already: the README described roles
that had been deleted, the companion doc claimed a claim the policy never makes,
and it called a round "always ending in a life loss" when the Meier full loop
ends one without.

Three rules that keep the companion doc honest:

- No commands, no installation. It is prose for non-developers. A test
  asserts the absence of `pip install`, `uvicorn`, `pytest`, `curl`, `export`.
- Describe the machine, not its output. The companion doc says what is
  set up: dice weights, reading caps, roster parameters. It does not say who
  wins, how often players bluff, or how long a match runs. Those are results
  of a simulation, they change from run to run, and the project is not hunting
  strategies. Results go in `docs/agent-model.md` or a separate report.
- Every number that stays is a construction number. If a figure would
  change when the players play differently, it does not belong here.

## Conventions

- Code comments and docstrings are in Swedish, matching the domain. Keep them.
- Player personality lives in four numbers (`caution`, `statistics`,
  `unpredictability`, `reading`), never in the player's name. Names are
  deliberately neutral: an evocative label makes
  the model play a caricature of the label instead of playing the game, and then
  you cannot tell whether it wins on tactics or on its name. The old roles
  (Ärlig-Adolf, Rackar-Rakel, …) were removed for this reason.
- `axel` has `uses_llm=False` on purpose. He is the LLM-free reference the
  others are measured against — not a bit-for-bit deterministic one, since his
  `unpredictability` still varies his play. Do not "upgrade" him.
- The 21-outcome ranking is fixed: 21, 11, 22, 33, 44, 55, 66, 65, 64, 63, 62,
  61, 54, 53, 52, 51, 43, 42, 41, 32, 31. Meier (21) is highest and costs double.
- Agents must always respond with a JSON object; parsing tolerates code fences
  and surrounding text (`llm.parse_json_object`).
- `truth` on an announcement means the claim is at or below the dice
  (`rules.is_true_claim`), not that it equals them. Saying 31 while holding 52 is
  true, just weaker — a call on it still loses for the caller. Only a claim
  *above* the dice is a bluff.
- `decide_claim` has no voluntary bluff. It says `shown` when that is legal, and
  the minimal legal raise (`legal[-1]`) otherwise. There is no valuation step.
- `BLUFF_GAIN` was removed. It made an *uncalled lie* worth 0.5 lives while an
  uncalled *truth* was worth nothing (`p_called * l_lose`, which vanishes as
  `p_called -> 0`). That asymmetry alone produced "raise one step on weak dice":
  making the truth worth the same removed every bluff, and it was a side effect
  of a constant, not a property of Meier. Do not reintroduce it without adding a
  symmetric term for the truth.
- `opponent_factor` was removed from `decide_claim`, and `_call_factor` from
  `StrategicAgent`: both only fed the bluff branch. Reading still works, but
  through `opponent_q` in `decide_response` (bluff tendency, flips 61-63 to
  `syna` against a known bluffer), not through the claim.
- The claim prompt lists every legal claim with its direction against the dice
  (`StrategicAgent._legal_claims_listed`): "högre, alltså bluff", "exakt dina
  tärningar", or "lägre, alltså sant men svagare". Models rank Meier values
  worse than the code does, and without the tags a model called a *higher* claim
  "lägre" in its reasoning. Keep the tags: they stop the stated reasoning from
  contradicting the move.
- The engine coerces illegal model output back to legal moves (e.g. forces a
  higher claim when the rules require it). Keep that safety net.
- A "slå" claim is unseen: the player shakes their *own* cup and does not look
  at their own dice, so the claim is not a truth-or-bluff claim. Only "påstående" and
  "höja" claims where the player actually looked carry the sant/bluff label; any
  claim without a look (a slå, or a forced raise where the claimer chose not to
  look) is labelled "påstående utan att titta" and counted as `unseen`, never as
  `bluffs`, in the stats.
  This is deliberate: it adds a psychological dimension, so `unseen_rate`
  is tracked per role to see whether bidding without a look pays off over many matches.
- Note that pairs (11–66) outrank high singles, so e.g. 44 beats 65. When a call
  looks "wrong", check the ranking before assuming a bug.
- "Deterministic" means `unpredictability == 0`, not "no LLM". `axel` is the
  LLM-free reference, but his params carry `unpredictability = 0.2`, so his
  claims vary between runs by design. A test that compares two agents' claims must
  pass `AgentParams(unpredictability=0.0)`; otherwise it fails ~20 % of runs.
  This bit `tests/test_legality.py::test_agent_without_llm_is_deterministic`,
  which was flaky until it built its own params instead of `AgentParams()`.

## The dice are weighted, so count outcomes, not pairs

`rules.FACE_WEIGHTS` comes from a solid-angle model of the oblong dice, so
1 and 2 are rarer than 3-6. `policy.OUTCOME_P` is the exact distribution and
`policy.CALL_ODDS[claim].p_win` is the true `P(the caller wins)`. Never quote
"x of 36" from a fair-dice count; that was wrong by about four points on 11
(91.7 % vs the real 95.6 %). Read the numbers from `CALL_ODDS` and let
`tests/test_docs.py` compare them.

Two prose traps in the Axel section of the friend doc:

- `axel` carries `unpredictability = 0.2`, so `decide_forced` returns
  "unseen" about 10 % of the time. The text must not say he never declines to
  look. The tables only hold at `unpredictability = 0`.
- The example part has all three players following the rule-engine policy, so
  it must be labelled as constructed. In a real match Berit and Cecilia decide
  with the model. The moves are pinned by
  `test_axel_section_example_part_moves_match_the_policy`.

## An LLM player never falls back to the rule engine

This is a simulator, not a hardened game server. The numbers only mean
"what the model does" if the model actually answered. So the old silent
fallback to `BasePolicy` is gone.

- `StrategicAgent._ask` makes `DECISION_ATTEMPTS` (3) attempts per decision.
  Unparseable JSON and illegal values count as attempts, with the error fed
  back into the next prompt. Bad JSON is not a transport failure: try again.
- A transport error (`LLMError` from the client) aborts at once. The client
  already retried with backoff, so waiting again can block a decision for
  minutes.
- When attempts run out, `LLMError` is raised and the match aborts. The web
  API turns it into HTTP 502 with the player and decision in the message.
- `make_player(key)` refuses to build a non-Axel role without a client.
  `make_rule_player(key)` (and `--no-llm`) is the explicit rule-engine path.
  Keeping those two separate is what stops the silent path from reopening.
- `corrected` no longer means "the model failed". It only carries the
  session-level correction in `Session._enforce_claim` (see `player.py`), so do
  not use it as a health signal for the LLM path. Read the 502 instead.

## Personality parameters were renamed

The old names `risk` and `press` are gone. Current fields on `AgentParams` are
`caution`, `statistics`, `unpredictability`, `reading`. On `OpponentProfile`
the pair is `call_tendency` (was `risk`) and `bluff_tendency` (was `press`),
and the factor helpers are `call_factor` / `bluff_factor` with
`NEUTRAL_CALL` / `NEUTRAL_BLUFF` (was `NEUTRAL_RISK` / `NEUTRAL_PRESS`).
Bluffing is **not** a parameter at all, and `BasePolicy` never bluffs on
purpose: it claims `shown`. Lying only happens when the rules force a raise the
dice cannot cover.

Watch the two traps when touching this:

- Swedish prose still says "undviker risk" and "sätter press". That is correct
  language about behaviour, not a stale identifier. Only change backticked
  identifiers and code.
- `tests/test_docs.py` used to allowlist `"risk"` and `"press"` so percentage
  lines in the companion doc would pass. Once the doc stopped using those
  words the entries were dead weight and were removed. If you add a percentage
  line to that doc, add its context word back deliberately.

## Environment notes

- In the Agent Canvas runtime the app talks straight to Gemini,
  not to the local agent-server. The old proxy path
  (`http://127.0.0.1:60000`, model `openhands_Default`, header
  `X-Session-API-Key`) is removed: every request there started an OpenHands
  conversation.
- Gemini free tier (verified 2026-11-15): the free tier allows ~10k
  requests/day, which covers ~94 matches (a match is ~106 calls / ~80k tokens).
  Model `gemini-2.5-flash` is closed to new users; use `gemini-3.1-flash-lite`
  (fast, generous quota, good enough for this decision problem) or
  `gemini-3.8-flash` (heavier, sometimes 503 under load). Set the key in
  `GEMINI_API_KEY` to activate. Free-tier prompts may be used by Google to
  improve their models — fine for a dice game, but not for anything sensitive.
  The key lives outside the repo at `/workspace/meier-secrets/gemini.key`
  (mode 600), which `run.sh` reads. `/workspace` is a persistent volume;
  `/home` and `/tmp` are wiped on restart.
- A Gemini flash model answers `503 UNAVAILABLE` ("currently experiencing high
  demand") in bursts that last minutes. The client retries the same model
  three times, then raises `LLMError`. `MEIER_FALLBACK_MODELS`
  (comma-separated, set in `run.sh`) makes `LLMClient` try the next model
  instead. A 503 raises `_Overloaded`, which is deliberately *not* `_Transient`,
  so no retry is wasted on a model that is down. The model that last answered
  goes first in the chain, so the switch is paid once, not on every decision.
- **There is no `BasePolicy` fallback for an LLM player.** When the client
  gives up, `StrategicAgent._ask` raises `LLMError` and the match aborts. Three
  attempts are made per decision (`DECISION_ATTEMPTS`); a transport error
  aborts at once, because the client already retried with backoff. The match
  must not continue on a rule engine while claiming to measure the model.
  `make_player` refuses to build an LLM role without a client, so the silent
  path is closed at construction too. `make_rule_player` (and `--no-llm`) is
  the explicit way to play a rule engine.
- Never print the session API key. Read it from the process env if needed.
- The web app is served on port 12000 in this environment.
- Long runs / sandbox lifetime: the runtime pauses an idle environment
  (`OH_RUNTIME_IDLE_TIMEOUT_SECONDS`, 1200s = 20 min in Canvas). LLM traffic and
  the client's 3s status polling keep it awake. A match series runs in a
  background thread, so closing the tab does not stop it, and the JSONL is
  appended as matches finish — a pause mid-series does not lose finished games.
  For runs that must exceed the idle window, run the CLI outside Canvas with a
  real `GEMINI_API_KEY` (optionally `nohup`).
- The analysis tab keeps loaded protocols in memory (`web.app._store`),
  so they are lost on restart. Tests clear the store to stay isolated.
- Git remote: `https://github.com/aieuren/mejer-simulator.git` (branch `main`).
  The game was renamed Mejer → Meier everywhere in the code, but the GitHub
  repo still carries the old name: renaming it needs `administration:write`,
  which `$GITHUB_PUSH_TOKEN` does not have (it has `push`/`admin` on the repo
  itself but the rename endpoint returned 403). Rename it by hand in the GitHub
  UI to `meier-simulator`; the log repo is already `meier-simulator-logs`.
  `git push` needs auth: a repo-local `credential.helper` reads
  `$GITHUB_PUSH_TOKEN` (not stored on disk), since `$GITHUB_TOKEN` lacks write
  access to this repo. The variable is only exported when its name appears in
  the command, so run `GITHUB_PUSH_TOKEN="$GITHUB_PUSH_TOKEN" git push …`.
  Gotcha (2026-11-15): a *global* helper (`credential.https://github.com.helper`
  → `~/.openhands/git-credential-helper`) is also configured and returns a
  different 40-char token with no write access. Git tries both in order, so the
  wrong one can win and the push fails with `403 Write access to repository not
  granted` even though `$GITHUB_PUSH_TOKEN` has `push`. The repo-local config now
  clears the list first (`credential.helper ""` then the push-token helper), so
  `GITHUB_PUSH_TOKEN="$GITHUB_PUSH_TOKEN" git push origin main` works. The
  variable name must appear in the command — otherwise the secret is not
  exported and the helper sends an empty password, which fails with
  `Invalid username or token`. If the 403 returns, run
  `git config --local --unset-all credential.helper` and re-add
  `""` + the `!f() { echo username=x-access-token; echo password=$GITHUB_PUSH_TOKEN; }; f`
  entry. As a fallback, `git push
  "https://x-access-token:${GITHUB_PUSH_TOKEN}@github.com/aieuren/meier-simulator.git" main`
  bypasses the helper entirely.
  Gotcha (2026-11-18): putting `$GITHUB_TOKEN` in the remote URL also fails
  (403) — that token has read-only access here. Push must go through
  `GITHUB_PUSH_TOKEN`. Don't rewrite the remote; just run
  `GITHUB_PUSH_TOKEN="$GITHUB_PUSH_TOKEN" git push origin main` and let the
  repo-local credential helper inject it.
  Gotcha (2026-11-08): a token baked into the remote URL *shadows* the
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

Lösningen är en SessionStart-krok i repot: `.openhands/hooks.json` +
`.openhands/hooks/start_meier.sh`. Den gör två saker: installerar om
Canvas-panelen och startar webbappen om den inte kör. Båda behövs, eftersom
både panelregistret och appen bor i miljöer som nollställs.

Varför just den här vägen fungerar (verifierat 2026-11-17):

- Agent-servern stödjer hook-typerna `pre_tool_use`, `post_tool_use`,
  `user_prompt_submit`, `session_start`, `session_end`, `stop`
  (`HookConfig` i `/openapi.json`).
- En projekt-lokal `.openhands/hooks.json` läses inte automatiskt när en
  konversation skapas direkt mot API:t (testat: `hook_config: null`, ingen
  `HookExecutionEvent`).
- Men Agent Canvas läser den: `hooks-service` i Canvas-frontenden anropar
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

Allt nedan är testat och fungerar inte som autostart vid containerstart.
Listan finns för att slippa upprepa felsökningen.

- SessionStart-kroken kör inte vid kallstart. Den kräver att en konversation
  skapas *med* `hook_config`. Att bara öppna en konversation (`GET
  /api/conversations/{id}`, som Canvas gör) kör den inte — testat: appen förblev
  `HTTP 000`.
- Ingen startkrok i agent-servern. `openhands-agent-server --help` visar
  bara `--host/--port/--reload/--import-modules/--extra-python-path`. Inga
  träffar på `OH_STARTUP`, `startup_command`, `runtime_services`, `prestart`,
  `boot_command` i binären.
- `POST …/runtime/reprovision` svarar `200 {"runtime_status":"available"}`
  men startar inte appen.
- `.openhands/setup.sh` körs inte — varken vid kallstart eller reprovision.
- App-backend (`backend` i manifestet) är fel verktyg. Servern har
  `canvas_app_backend_enable_lifecycle_v1` och endpoints
  `/api/canvas-extensions/installed/{name}/backend/{prepare,start,stop,logs}`,
  och docsen säger "Agent Canvas starts the app through the server lifecycle
  automatically". Men en backend är en nedladdad binär (`.tar.gz` med
  `sha256`, `argv`), avsedd för appar som *äger* sin tjänst. Meier är redan en
  Python-app som körs via `run.sh`; att paketera om den som binär artifact vore
  ett stort ingrepp för samma resultat som panelens auto-start ger.
- Idle-timern ska inte manipuleras. `GET /server_info` visar `idle_time`, och
  det är "the exact signal runtime-api polls to decide when a sandbox is idle
  enough to pause/reap" (officiell cookbook). Ett bash-anrop via API:et
  nollställer timern — men att polla för att hålla sandlådan vaken kringgår
  plattformens design och görs inte.

Det som faktiskt löser användarens önskan: panelens auto-start (se
"Startpanelen i Agent Canvas" ovan). Laddar Canvas den aktiverade panelen kör
`activate()` en health-koll och startar appen om den är nere.

## Startpanelen i Agent Canvas (self-service)

The user wanted a way to start the web app without asking the agent. The answer
is a Canvas app at `canvas-app/`: a page in the Canvas UI with Start/Stop/Refresh
buttons. It calls the agent-server bash endpoint through
`host.agentServer.request`, so Canvas handles auth and no secret lives in the
app code. No own server is needed.

- Install/update: `./canvas-app/install.sh` (uses `SESSION_API_KEY` from
  `/proc/1/environ`). Install leaves the app disabled; the script enables it too.
- The panel self-starts on activate. Canvas calls `activate(host)` whenever it
  loads the enabled app, and the panel then runs `CMD_ENSURE_START`: a health
  probe that exits early when the app answers and otherwise runs the full
  `CMD_START`. So after a container wake, simply loading Canvas brings the app
  back without opening the panel or pressing anything. The health-first check is
  what keeps it safe — a plain `CMD_START` would kill and restart a live match on
  every page load.
- The panel lives in the agent-server home (`~/.openhands/canvas-extensions/`),
  which is not a persistent volume. Re-run `install.sh` after a restart.
- The bash endpoint's shell does have `RUNTIME_URL`, so the panel can show
  the public web address.
- Gotcha: `pkill -f 'uvicorn …'` kills its own shell because the pattern matches
  the command line. Use the bracket trick `pkill -f '[u]vicorn meier.web.app'`.
- Gotcha: `pkill` returns at once, but the dying server still answers health
  checks for about a second. Pressing Stop then Start therefore made `run.sh`
  see a live port, skip the start, and leave nothing running. The panel's Start
  now stops, waits for the port to go quiet, and only then calls `run.sh`.
- Install from Git works only for a public repo. The server fetches the
  source without credentials, so a private repo fails with "Failed to fetch
  extension from github:…". Install is pinned to the commit it resolved; push a
  fix, then reinstall to move the pin.
- Gotcha: Agent Canvas is a separate frontend mounted at `/canvas`. The root
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
  the ephemeral overlay filesystem, not on the persistent `/workspace` ext4
  volume. A container restart wipes it, so `GET /api/canvas-extensions/installed`
  returns `[]` and the Canvas sidebar entry is gone. The SessionStart hook above
  reinstalls the panel on every new session, so this now heals itself; to do it
  by hand, run `./canvas-app/install.sh`.
- The Canvas UI is hard-locked to OpenHands Cloud: its HTML sets
  `window.__AGENT_CANVAS_LOCK_TO_CLOUD__="https://app.all-hands.dev"` and
  `__AGENT_CANVAS_BASE_PATH__="/canvas"`. Apps are only available with a
  local backend — the official docs state "Apps … are currently available
  with supported local backends. They are not available when an OpenHands Cloud
  backend is active." So the sidebar entry depends on the active backend being
  this sandbox's agent server, and on the panel being installed there.
- The user-visible error "Not available / This app is disabled, missing, or does
  not provide this page" means the backend has no such app installed. It is
  not the same as the plain 502 "Bad Gateway" you get from the public web
  URL when the Meier app itself is down — that is a separate, expected condition
  the SessionStart hook fixes.

## Match logs are checked into a separate GitHub repo

Long series used to be lost: the protocol was written to `/tmp/meier_matches.jsonl`,
which a container restart wipes. Now a series can be committed and pushed to a
separate log repo after every finished match.

- Module: `meier/logrepo.py` (`LogRepo`, `series_filename`, `series_label`,
  `push_enabled`). One file per series: `meier-matcher-<YYYY-MM-DD-HHMMSS>.jsonl`
  (seconds, so two runs cannot collide and truncate each other).
  `series_label` turns the filename into a readable Swedish label
  ("12 november 2026, 02:46:13") used by the analysis tab and `list_logs`.
- Log repo: `aieuren/meier-simulator-logs` (private), clone at
  `/workspace/meier-logs` — deliberately outside the code repo, so the two
  are not nested git repos. `MEIER_LOGS_DIR` overrides the path.
- Token: `/workspace/meier-secrets/logs.token` (mode 600), read by a git
  credential-helper passed via `-c`, so the value never lands on the command
  line (it would otherwise show up in `ps`). Fine-grained PAT with only
  Contents: Read and write on the log repo. `MEIER_LOGS_PUSH=0` disables push.
- Wire-up: `web/app.py` `_MatchJob`. Each record is appended and
  then `commit_and_push` runs; `push_status` reports the outcome.
  A push failure is caught and returned as a string — it must never kill a run.
- Check-in is **always on**. The checkbox in the UI is gone (2026-11-25), and
  `MatchRequest.check_in` no longer controls anything: it stays in the model so
  an old client that sends `check_in=false` still gets its series checked in.
  Series belong in git, not only on disk.
- Local fallback: when the repo cannot be reached or `MEIER_LOGS_PUSH=0`
  is set, the series is written to `MEIER_LOCAL_LOG_DIR` (default
  `/workspace/meier-runs`), read at call time by `_local_log_dir()`. That
  directory is deliberately **outside** the clone at `/workspace/meier-logs`.
  `push_status` says where the file went ("Serien sparas lokalt i …").
- `MEIER_LOGS_PUSH=0` still really disables check-in. It is now an
  emergency brake for tests and for a broken remote, not a choice in the UI.
  `_open_log` checks `logrepo.push_enabled()` first.
- **Credential-helper gotcha (root cause of the 403s, 2026-11-25).** The
  token in `logs.token` was fine all along. OpenHands installs a global
  `credential.https://github.com.helper` in `~/.gitconfig`, and git **appends**
  helpers to that list. The app's own helper therefore came last, the global
  one answered first with a token that lacks access to the log repo, and every
  push failed with `Write access to repository not granted` (403). Fix in
  `LogRepo._credential_config`: emit `credential.helper=` (empty) before the
  real helper, which resets the list. Verified: a full series pushed and the
  remote HEAD moved.
- **Test leakage (2026-11-25).** While push was broken, tests that ran series
  wrote to the **real** log repo without anyone noticing. Once push worked, two
  invented series went out on the remote. Fixed in `tests/conftest.py`: an
  autouse fixture points `MEIER_LOGS_DIR`, `MEIER_LOCAL_LOG_DIR` and
  `MEIER_LOGS_TOKEN_FILE` at `tmp_path` and sets `MEIER_LOGS_PUSH=0`. Tests
  that probe check-in override these themselves. After a suite run, confirm
  `git -C /workspace/meier-logs rev-parse HEAD` is unchanged.
- **Restart recovery.** `_current_match_file` lives in memory, so a restart
  used to make `/api/matches/status` return 404 and the UI claim the series was
  lost. Now `_MatchJob._open_log` writes `last-series.json` in
  `MEIER_LOCAL_LOG_DIR`, and `_match_file()` / `_status_from_file()` read it
  back. Status, download and summary keep working after a restart, and the
  response carries `restored: true`.
- **Local series in the analysis tab.** `/api/analysis/logs` lists the log repo
  **and** `MEIER_LOCAL_LOG_DIR`, with `local: true` on the latter. Marked
  `· local` in the UI. `_count_lines` counts only successful records, so a
  series where every match fell on a 503 does not look played.
- A series can sit at `done: 0` for 15+ minutes with no error and a 0-byte file.
  Nothing is wrong with the code: the record is written only when a match
  *finishes*, and a match is ~100 LLM calls. `MEIER_MAX_RPM` (default 15) is a
  shared limiter across all worker threads, so 5 parallel matches queue on the
  same budget. Worse, a 503 burst makes every decision burn its retries. Check
  progress with a direct client call before blaming the app:
  `LLMClient(LLMConfig.from_env()).complete("Kort.","Hej.")`. If that raises
  503, wait — a run started during a burst will look hung.
- There is no stop endpoint. To abort a running series, kill the uvicorn PID
  (`ps aux | grep "uvicorn meier"`), then remove the partial file from the
  clone and `git reset --hard` there. A partial series is still a valid JSONL
  up to the last complete match.
- `_current_match_file` (module global) holds the file for the latest series;
  `/api/matches/download|summary` read it.
- Gotcha: `git -c key=value` must be passed as two argv items before the
  subcommand. `["-c", "user.name=Meier Bot"]` works; `["-cuser.name=Meier Bot"]`
  fails with "unknown option".
- Tests use a local bare repo via `MEIER_LOGS_REMOTE_URL` — no network, no real
  token. See `tests/test_logrepo.py` and the check-in tests in
  `tests/test_web_matches.py`.

## The machine: four players, one policy core (roster)

The roster was rebuilt. The old roles (`arling`/`trygg`/`kalkyl`/`rackar`) are
gone — replaced by four neutral-named players in `meier/agents/roster.py`:

| Key | Name | Risk | Press | Reading | LLM |
|---|---|---:|---:|---:|---|
| `axel` | Axel | 0.50 | 0.50 | 0.00 | no (BASE) |
| `berit` | Berit | 0.25 | 0.25 | 0.15 | yes |
| `cecilia` | Cecilia | 0.50 | 0.45 | 0.50 | yes |
| `david` | David | 0.65 | 0.60 | 0.35 | yes |

- Names are neutral on purpose. A value-laden label ("Rackar-Rakel") tells
  the model who to *be*, so it plays a caricature and you cannot tell whether a
  profile wins on its tactics or its label. Personality lives in the params.
- Axel is BASE — deterministic, non-reading, no LLM. He is the fixed
  measuring stick the others are compared against. He is allowed to lose often.
- The LLM owns the move (changed 2026-11-18). `StrategicAgent`
  (`meier/agents/strategic.py`) asks the model which move to make and accepts
  any legal answer. It does not pick the move for the model.
  - `meier/legality.py` owns the rules: it enumerates the legal claims,
    responses and forced choices for a position, and rejects everything else.
    A player can never break the rules, whatever the model says.
  - `meier/agents/personality.py` turns `caution`/`statistics`/
    `unpredictability`/`reading` into prose
    for the prompt. The params describe a human to play as; they are no longer
    fed into a formula that computes the move.
  - An illegal or unparseable answer is retried up to `DECISION_ATTEMPTS`
    (three) times, each naming the error. After that the agent raises
    `LLMError` and the match aborts. There is no `BasePolicy` fallback: a
    silent fallback would look like a model move. The web API turns the error
    into HTTP 502 with the reason.
- Why it changed. The old design computed the move in `BasePolicy` and left
  only the line to the LLM. Every player then played the same algorithm with
  different constants: `berit` always claim 43 and `david` always 64 when
  bluffing, regardless of the dice. The old `press` parameter drove a claim
  choice the model never saw. The params are now material for simulating a real
  player, and judging what the players do is the user's job, not the machine's.
- No more silent rewriting. `decide_claim` now takes `previous_claim` and
  chooses among the legal claims directly. Before, it chose as if the table were
  empty and the engine rewrote 47.9 % of claims (805/1680) without a trace.
  That is now 0 %, guarded by
  `tests/test_legality.py::test_policy_never_silently_rewrites_the_claim`.
- `slå` is not legal against Meier. `legality.response_actions` drops it
  when no higher claim exists. A real LLM match crashed here before the fix,
  because the player chose `slå` and the engine asked for a claim above the
  highest one that exists. Guarded by
  `::test_shaking_is_not_offered_against_meier`.
- Secretary vs reader. `OpponentTracker` (`meier/opponents.py`) is the
  secretary: it *records* public play in numbers (claims, reveals, bluffs, calls,
  passes) and never interprets. `OpponentReader` is the reader: the LLM decides
  alone what the numbers mean. The reader is fed only
  `tracker.evidence(player)` — never the session log — so it cannot see hidden
  dice. Ask "who judges?" and the answer is: the LLM. The secretary only writes.
- `OpponentProfile` has `call_tendency`, `bluff_tendency`, `predictability`,
  `kind`, `confidence`, `source`. `source` is `"llm"`, `"statistik"` (fallback
  without LLM) or `"population"` (no data). Values are clamped to 0–1 so a
  garbled LLM reply cannot leak junk into decisions.
- `confidence` is capped by evidence at the table, not by the LLM's self-report.
  `OpponentTracker.evidence_strength()` = `reveals / (reveals + 3)` over the whole
  match (every player's settled calls), and `reader.profile()` takes
  `min(llm_confidence, strength)`. The same cap applies to the arithmetic fallback
  in `statistical_profile`. So an early guess cannot claim to be certain: one call
  gives 0.25, three give 0.50, nine give 0.75. Both `table_reveals` and `strength`
  are also sent to the model in the summary so it knows how thin the evidence is.
- Plain-language view. `OpponentProfile.describe()` renders the numbers as a
  sentence with the percentages in parentheses (e.g. *"Försiktig: bluffar nästan
  aldrig, synar nästan aldrig och är mycket förutsägbar (bluff 10 %, syn 20 %,
  förutsägbarhet 90 %; gott underlag)."*). `describe_params()` does the same for a
  player's own known character in the roster list. Presentation only — never an
  input to a decision. The web app shows each agent's picture of the others in
  the game tab, fed by `Session._views()` (which drops `source == "population"`
  entries so only pictures with evidence are shown).
- The profile is cached per opponent and recomputed only when new evidence
  becomes public (a reveal). So a match makes a handful of reader calls per
  opponent, not one per decision.
- Relative scaling, never absolute. `bluff_factor` maps `bluff_tendency` to a
  factor around 1.0 centred on `NEUTRAL_BLUFF = 0.5`, damped by `confidence`; the
  agent's own `reading` then scales how much of that signal it wants. This
  preserves the `reading = 0 → exact CALL_PRIOR` invariant. Absolute bluff rates
  here are ~0.72 for everyone, so feeding them in raw inflates every opponent —
  the factor must stay relative.
- `call_tendency` no longer reaches the claim. `call_factor` still maps it to a
  factor around 1.0 centred on `NEUTRAL_CALL = 0.5`, but the only consumer was
  the removed bluff branch. `opponent_factor` is gone from `decide_claim`, and
  `_call_factor` is gone from `StrategicAgent`. If you wire it back in, the claim
  must stop being a pure "say the dice" rule — decide that on purpose.
  `bluff_tendency` adjusts belief about a claim (`_opponent_prior`),
  `call_tendency` adjusts the chance of being called (`_p_called`) — different
  terms, both live.
- The same absolute-scale trap hits `call_tendency`. Raw call rate is ~0.265 for
  every role, so feeding it straight onto the 0–1 scale makes every opponent look
  timid and the agent bluffs wildly against all of them.
  `POPULATION_CALL_RATE = 0.265` plus `OpponentTracker.call_ratio()` keep it
  relative: ratio 1.0 = "calls as much as people usually do". The LLM summary
  states this reference point too, so the model does not read 26 % as "never
  calls".
- Evaluation runs without LLM. `play_match(..., with_llm=False)` and
  `cli match --no-llm` give a deterministic match: the reader falls back to the
  secretary's arithmetic. Fast (milliseconds vs minutes). Use `--no-llm` for
  statistics; turn LLM on when the lines and the reading should be real.
- The opponent model is now wired into the engine. `Session.tracker` feeds
  the shared `OpponentTracker` as events become public; `make_players()` gives
  every reading player the same tracker (one shared view of the table).
- Monkeypatch seam: `play_match` builds agents through `match._new_agents`
  (LLM on) or `match._new_agents_no_llm` (LLM off). Tests patch `_new_agents`.
- Provider: Gemini only, via `GEMINI_API_KEY` or
  `$MEIER_SECRETS_DIR/gemini.key`. `LLMConfig.from_env()` raises `LLMError`
  without a key.
- The Gemini proxy hits a 429 quota. When it does, `LLMError` surfaces after
  three retries and a full LLM round can hang for many minutes. Do not use a live
  session to verify model wiring while the quota is exhausted — a session-level
  check needs dozens of calls. Verify the mechanism with a fake LLM instead:
  `tests/test_reader.py` has a `FakeLLM` that returns fixed JSON, and an
  end-to-end `Session` with a fake client shows the confidence curve in seconds.
  Check quota first with a one-shot `LLMClient().complete("Svara kort.", "hej")`.

### Running an evaluation

```bash
# Fast, deterministic self-play (no LLM) — the default for measurement
python3 -m meier.cli match axel berit cecilia david --count 200 \
    --workers 4 --no-llm --out /tmp/meier_eval.jsonl
```

Baseline (400 matches, four players, chance 25 %): Axel 31 %, Berit 28 %,
Cecilia 22 %, David 19 %. David is weakest despite (or because of) the highest
`statistics`; the flat-prior baseline reads the claim level less.
