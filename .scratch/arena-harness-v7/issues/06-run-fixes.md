# 06: Run-control fixes (§12a): outage, retry/idle timeouts, MiMo thinking, newest toolchain

**What to build:** A provider outage of a few minutes no longer ends a run: transport failures wait and retry up to
a wall-clock limit (about 10 minutes), then the run stops with its own rerunnable reason `provider_unreachable`,
while `error_loop` stays for repeated model-side failures. Pi's native retry and idle timeout are configured from
`models.yaml` now that the provider wrapper is gone. A turn cut at the output limit keeps its reasoning in history
and the next message states where it was cut. MiMo gets `reasoning_effort: "none"` on turns that follow a tool
result. The summary's "best verified" label means "passes every listed version". Heartbeats are measured on the
newest listed toolchain (D31), proved over all 15 benchmark rows. A test that read the live machine is isolated.

**Blocked by:** 02: Actual-cost stop; 04: Move the remaining tools into the CLI (`arena/cli/run.py`, `campaigns.py`); 05b: Agent text: campaign/engine/TS messages moved verbatim, literal lint (`agent-text/messages/errors.yaml` and the lint that new text must satisfy; `text.ts` and the renderer come from 05a, below 05b).

**Status:** done

**Branch:** `v7/06-run-fixes` (stacked on `v7/05b-agent-messages`)

**Read first:** spec "Run control" and "Scoring and measurement" (Modules), "Testing Decisions" (seam B, seam C
bullet 1, isolation), stories 43-45; plan §12a (#3, #7, #35), §9 (items 4-5), §9a (MiMo "Turning thinking off"; DeepSeek
replay), §1l and D31, §8 (isolation); `docs/ISSUES-harness-v7.md` items 3, 6, 7, 14, 35; decisions D8, D24, D25, D31.

## Context: where things are now

- **Outage (#3).** `packages/arena-pi/extensions/arena.ts`: `MAX_ERROR_STREAK = 3` (top of file) and the
  `agent_before_settle` handler near the end. It sets `failed = event.outcome !== "completed"`, increments
  `errorStreak` for every failed turn, stops with `error_loop` at 3, and otherwise sleeps
  `min(30_000, ARENA_BACKOFF_MS(default 2000) * 2^(errorStreak-1))`. Control rows go to the cost ledger with
  `appendCost({kind: "control", ...})`. A transport failure (no content, no usage) and a model-side failure are
  treated alike, so an outage of about a minute ends the run. The arena-guard provider wrapper that used to turn
  guard refusals into errors is already gone (ticket 02).
  `tests/test_runner.py::ErrorLoopAndContinuationTests::test_consecutive_provider_errors_stop_with_error_loop_without_burning_continuations`
  and `test_a_recovered_error_resets_the_streak_and_continuation_work_counts_normally` script `{"error": "..."}` steps.
  `tests/fake_opencode.ts` is the fake provider (a step may be `{error, delay_ms, usage, stop_reason: "length"}`).
- **Runner stop handling.** `arena/cli/run.py` (ticket 04 moved it from `tools/run_pi_budgeted.py`):
  `_stopped_on_purpose()` treats only `limit_reached` and `finished` as deliberate stops. `arena/summary.py`
  `stop_reason_of()` returns the last control row's `stop`. `arena/cli/campaigns.py` (from `tools/run_campaign.py`):
  `lean_unhealthy_rows()` and a "LEAN UNHEALTHY" line in the campaign report, `campaign.json` key
  `lean_unhealthy_runs`; the model for how a run that must be redone is reported.
- **Pi settings (#14, retry).** `arena/cli/run.py` writes the run's `.pi/settings.json` with
  `compaction`, `autoEnableCodemode: false`, `httpIdleTimeoutMs: PROVIDER_TIMEOUT_MS` and
  `retry: {"provider": {"timeoutMs": PROVIDER_TIMEOUT_MS, "maxRetries": 0}}`. `PROVIDER_TIMEOUT_MS` comes from
  `models.yaml` `provider_timeout_ms` (120000), validated in `arena/models.py` `validate()`. The agent-level
  `retry.enabled`, `retry.maxRetries`, `retry.baseDelayMs`, `retry.maxAgentDelayMs` are not set, so Pi's defaults
  apply (3 retries, 2 s base, 60 s cap). Pi's settings reference: `~/.pi/agent/install/releases/1.1.0/node_modules/@earendil-works/pi-coding-agent/docs/settings.md`, "Network and retries".
- **Truncated turns (#35).** The v6 traces show cut turns with `usage.output` exactly equal to the request ceiling
  (16000, 32000) and only a `thinking` block. Pi (`pi-ai/dist/utils/overflow.js` `isRecoverableLength`,
  `pi-coding-agent/dist/core/agent-session.js` near "recoverableLength" and `_omitRecoveryAttempt`) treats a
  `length` stop as **recoverable** when `usage.output < model.maxTokens`. Our ceiling
  (`request_output_tokens`, 64000, clamped in `before_provider_request` in `arena.ts`) is far below DeepSeek's
  `maxTokens` (384000 in Pi's catalog), so every cut turn is "recoverable": Pi drops the cut attempt from history,
  runs a paid compaction and retries. That is how the reasoning is lost. A cut turn's own text is
  `agent-loop.js` `failToolCallsFromTruncatedMessage` (when it had tool calls).
- **MiMo.** `models.yaml` entry `mimo-v2.6-pro` (provider `primalabs`, registered by `arena.ts` from
  `ARENA_MODELS_JSON`, built by `arena/models.py` `pi_json()`; `ARENA_MODEL` and `ARENA_PI_MODEL_ID` name the model).
  `before_provider_request` in `arena.ts` already rewrites the output ceiling in the payload and journals it.
  Probe 2026-10-10 (plan §9a): the API honours `reasoning_effort: "none"` (0 reasoning tokens) and ignores
  `thinking: {type: disabled}`; Pi's `--thinking off` only cut 45 to 10 tokens.
- **Summary label (#7).** `arena/summary.py` `_progress()` takes `best_verified_candidate` from evaluations with
  `mode == "full"` and `metrics.proxy is not None`; `build_summary()` overwrites it from `submission_result`.
  `arena/scoring.py` `metrics()` fills `axes.compat` with `passed`, `checked`, `total`; a full evaluation of a
  candidate that fails one non-primary version still gets a proxy (compat below 100).
- **Measure version (D31).** `arena/engine.py` `measure_version(row)` returns the override from
  `benchmark/derived/measure-versions.json` when that file exists (it does not exist in the repo), else
  `versions(row)[0]` (the first listed). `evaluate()` compiles `[targets[0], measured_on]` in fast mode when they
  differ and takes heartbeats from `measured_on`. Callers of `measure_version`: `context.py`, `profile.py`,
  `route_features.py`, `campaign.py`, `lean_health.gate_versions`, `cli/lean_load.py`
  (ticket 07 owns that last one). The 15 rows list: only the Putnam rows list oldest first
  (`putnam_1964_a4` v4.25.0, v4.26.0, v4.27.0; `putnam_1964_b2` v4.25.0, v4.26.0; `putnam_1995_a3` v4.25.0, v4.26.0,
  v4.27.0); `Core.InitsUpdatesComm` lists v4.29.1, v4.27.0, v4.26.0. `tests/test_environments.py`
  `MeasurementVersionTests` covers the override.
- **Isolation (#6).** `tests/test_lean_session.py::SessionLogTests::test_a_worker_open_and_a_memory_refusal_are_logged_and_marked`
  patches `lean_session._available_gb` but `Session._acquire` also asks `WorkerBudget.share()` (via
  `Session._share()`), which counts live sessions from lock files on the real machine, so the test fails while real
  Lean sessions run. `arena/lean_session.py`: `WorkerBudget.live_sessions()`, `share()`, `_available_gb()`.

## What to build

- [ ] 1. **Fake provider.** In `tests/fake_opencode.ts`, let an `error` step carry `usage` (a model-side failure that
  was billed): the failed message then has usage and no content. Keep every existing step shape working.
- [ ] 2. **Outage classifier (TS, pure).** New `packages/arena-pi/extensions/outage.ts` exporting
  `classifyFailure(message)`: given the last assistant message of a failed turn, return `"transport"` when
  `stopReason` is `"error"` with no usage tokens (`usage.totalTokens` falsy) and no content blocks, `"model"` when it
  failed with usage or content, and `undefined` otherwise; and `nextWait(attempt, baseMs, startedAt, now, limitMs)`
  returning `{stop: true}` once `now - startedAt >= limitMs`, else `{stop: false, delayMs}` with the same backoff as
  today (`min(30_000, baseMs * 2^(attempt-1))`) shortened to the time left. `outage.test.ts` (node:test) covers:
  transport vs model vs completed, the delay sequence, the cut at the limit, and a recovered outage resetting
  the clock (use injected `now`).
- [ ] 3. **Wire it in `agent_before_settle`** (`arena.ts`). A failed turn classified `transport` does **not** touch
  `errorStreak`: the first one records `outageStartedAt`, then the handler waits `nextWait(...)`; once the wall-clock
  limit passes it stops with `provider_unreachable` (distinct from `error_loop`). A completed turn clears
  `outageStartedAt` and `errorStreak`. A `model` failure counts into `errorStreak` as today (`error_loop` at
  `MAX_ERROR_STREAK`). Every failed-turn control row (`appendCost({kind: "control", ...})`) gets
  `error_message` (the message's `errorMessage`, truncated to 300 characters), `failure` (`transport` or `model`) and,
  for transport failures, `outage_ms`. The limit comes from `models.yaml` (item 5) through
  `ARENA_OUTAGE_LIMIT_MS`; `ARENA_BACKOFF_MS` stays the base delay. The outage state resets on `session_start`
  like the other counters, and survives a resumed run only through the control rows that already persist
  (do not add new persistence).
- [ ] 4. **Runner and campaign.** `provider_unreachable` is not a deliberate stop: `_stopped_on_purpose()` stays as is,
  and `stop_reason_of()` already reports it from the control row. In `arena/cli/campaigns.py` add
  `provider_unreachable_rows(runs)` (like `lean_unhealthy_rows`), a campaign report line
  `PROVIDER UNREACHABLE (rerun): <run ids and spend>`, and the key `provider_unreachable_runs` in `campaign.json`.
  Add one test for the helper and the report line (pure, seam: the campaign report).
- [ ] 5. **`models.yaml` and Pi settings.** Add to `models.yaml` and `arena/models.py` `validate()` (all positive
  integers): top-level `outage_limit_ms: 600000` and `retry: {max_retries: 3, base_delay_ms: 2000, max_delay_ms:
  60000}` (these equal Pi's defaults; plan §12a). Factor the settings the runner writes into one pure function
  `pi_settings(args, config) -> dict` in `arena/cli/run.py` that returns the whole `.pi/settings.json` content:
  `httpIdleTimeoutMs` and `retry.provider.timeoutMs` from `provider_timeout_ms` (value stays 120000), `retry.provider.maxRetries: 0`
  (provider-level retries stay off, as Pi's docs advise), `retry.enabled: true`, `retry.maxRetries`,
  `retry.baseDelayMs`, `retry.maxAgentDelayMs` from `retry`, plus the existing keys unchanged. The runner exports
  `ARENA_OUTAGE_LIMIT_MS` to Pi. For tests only, the env var `ARENA_RETRY_BASE_MS`, when set, replaces
  `retry.baseDelayMs`. Test `pi_settings` (pure): the keys and values above come from the config, a changed config
  changes the output, and the existing compaction values are untouched.
- [ ] 6. **Seam B tests** (`tests/test_runner.py`, new `@slow` class `OutageTests`, Pi and the fake provider, no
  Lean; use `env={"ARENA_BACKOFF_MS": "10", "ARENA_RETRY_BASE_MS": "10", "ARENA_OUTAGE_LIMIT_MS": ...}`):
  (a) 25 transport errors in a row with a 300 ms limit end with control `stop == "provider_unreachable"`, summary
  `stop_reason == "provider_unreachable"`, the error text in a control row, and `error_loop` never recorded;
  (b) five transport errors followed by a normal answer do not stop the run and the run continues past them
  (limit large);
  (c) repeated model-side failures (error steps with usage) still stop with `error_loop` after 3, without burning
  continuations. Rewrite the two v6 tests named above accordingly (they currently use transport-style errors for
  `error_loop`); do not delete their intent.
- [ ] 7. **Truncated turns (#35).** First reproduce: an `@slow` test `TruncationTests` scripts a step
  `{"text": "...thinking...", "stop_reason": "length", "usage": {"output": <ceiling>}}` (the fake provider's
  catalog `maxTokens` equals `models.yaml` `max_tokens`) and records whether Pi compacts and whether the next request
  contains the cut turn. Expected on today's code: a compaction runs and the cut turn is missing. Then fix it:
  set Pi's `maxTokens` for the run model to the run's output ceiling (`request_output_tokens`), so a turn that stops at
  the ceiling is not "recoverable". Use only a supported Pi mechanism (first look at `docs/models.md` `modelOverrides` and
  `docs/custom-provider.md`; the extension already calls `pi.registerProvider`). If no supported mechanism sets
  Pi's `maxTokens` for a built-in catalog model, **stop and report** (owner decision 5) with what you found; do not patch Pi, do not
  rewrite `usage`. After the fix the test shows: no compaction, the cut turn (its reasoning included) present in
  the next request. Then the notice: when the last assistant message of the turn has `stopReason == "length"`, the
  next harness-authored text the model reads (the continuation message built in `agent_before_settle`, and, if the
  cut turn had tool calls, the error results Pi creates) ends with one line from
  `agent-text/messages/errors.yaml` key `turn_cut`, text `The previous turn was cut at {tokens} tokens.`
  (`tokens` = that message's `usage.output`), rendered with `text.ts`. Neutral, one fact, no advice.
  Test it in `TruncationTests` (seam B) and with a unit test of the small function that builds the line.
- [ ] 8. **MiMo thinking on tool-result turns.** Add an optional per-model key `tool_turn_reasoning_effort`
  (non-empty string) to `models.yaml` and `validate()`; set it to `none` for `mimo-v2.6-pro` only (a comment cites
  plan §9a). It reaches the extension in `ARENA_MODELS_JSON` as `toolTurnReasoningEffort` (camelized by
  `pi_json`). New `packages/arena-pi/extensions/thinking.ts` exports
  `applyToolTurnEffort(payload, effort)`: when `effort` is set, `payload` is an object whose `messages` array ends
  with a message of role `tool`, return a copy with `reasoning_effort: effort`; otherwise return the same payload
  object. It never mutates its input. In `before_provider_request`, apply it for the model named by `ARENA_MODEL`
  **before** the request row is journaled, so the trace shows what was sent. `thinking.test.ts` (node:test): sets the
  field after a tool result; leaves a user-last payload alone; leaves a payload with no setting alone; does not mutate
  the input; ignores non-object payloads. The `models` test checks `validate()` accepts the key and rejects an empty
  string.
- [ ] 9. **DeepSeek reasoning replay stays as it is** (D25: quality needs an A/B). Do not add or change
  `compat.requiresReasoningContentOnAssistantMessages` or any replay trimming.
- [ ] 10. **Isolation (#6).** `Session.__init__` already accepts `budget: WorkerBudget | None`; with `None` it builds a
  `WorkerBudget()` over the machine-wide token directory (`$XDG_RUNTIME_DIR/arena-lean-workers`), which is the live
  reading. In `SessionLogTests.setUp` build the session with `budget=lean_session.WorkerBudget(<temp dir>/"tokens", <limit>)`
  (as `tests/test_lean_session_warm.py` does), keep patching `_available_gb`, and assert nothing else changes. Prove it:
  run the test once while another real session holds tokens (start `arena lean serve` in a temp run dir
  yourself, or hold a token file with `flock` from a helper process; kill it by PID afterwards) and see it still pass.
  Then audit the non-`@slow` tests: `rg "/proc|_available_gb\(|live_sessions|MemAvailable|processes_named" tests` and fix every
  non-slow test that still reads the live machine (inject the reading or temp directories). A test that must read the
  machine is `@slow`. Add nothing that reads `/proc`.
- [ ] 11. **The "verified" label (#7), reproduce first.** In `tests/test_summary.py` build ledger fixtures and call
  `summary.build_summary` for: (a) a row with one listed version and a full evaluation that passes; (b) a row with
  three versions and a full evaluation that passes only the primary one (`axes.compat.passed < total`, proxy set);
  (c) a fast evaluation that passes the primary version. Run them on the unchanged code and note which give a wrong
  `best_verified_candidate`. Expected: (b) is wrongly labelled verified. Then fix `_progress()`: a candidate is
  verified only when `mode == "full"`, `proxy` is not None and `axes.compat.passed == axes.compat.total`; the
  `submission_result` overwrite in `build_summary()` stays (it is the cold all-version check). Keep (a) verified,
  (b) and (c) not verified; update `render_text` only if its wording would now be false. If none of (a)-(c) fails on
  the unchanged code, keep the tests, change nothing else, and say so in the hand-back.
- [ ] 12. **Newest listed toolchain (D31).** In `arena/engine.py` add `toolchain_key(version) -> tuple` ordering Lean
  toolchain names (`v4.25.0` < `v4.29.1` < `v4.33.0-rc2` < `v4.33.0`; a `-rcN` sorts below the release with the same
  numbers; an unparseable name raises `ValueError` naming it) and make `measure_version(row)` return the newest
  listed `(version, commit)` by that key. The explicit override file still wins when present and must name a listed
  version; the missing-file case is the normal one: keep the code path, write in the docstring that
  `benchmark/derived/measure-versions.json` is an optional per-row override (plan §7.2), and do not create the file.
  Update the docstring's "primary listed version".
- [ ] 13. **D31 test over all 15 rows** (`tests/test_engine.py`, pure, seam C): load `engine.BENCHMARK` and assert
  `measure_version(row)[0]` against this table, written in the test as the expected data: CallElimCorrect.substOldPostSubset v4.26.0;
  CallElimCorrect.extractedOldExprInVars v4.26.0; Core.InitsUpdatesComm v4.29.1;
  fundamental_theorem_of_variational_calculus' v4.32.0; Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema v4.32.0;
  FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time v4.32.0;
  Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress v4.33.0-rc2; Cslib.SKI.parallelReduction_diamond v4.33.0-rc2;
  Cslib.CCS.bisimilarity_congr_choice v4.33.0-rc2; Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius v4.31.0;
  Binius.BinaryBasefold.fold_advances_evaluation_poly v4.31.0; interleaved_affine_gaps_imply_tensor_gaps v4.31.0;
  putnam_1964_a4 v4.27.0; putnam_1964_b2 v4.26.0; putnam_1995_a3 v4.27.0. Use the full row names from
  `warmup.jsonl` (the table abbreviates none; copy them from the file, not from here). Also test `toolchain_key` ordering
  and the override: it wins when it names a listed version and raises when it names an unlisted one (adapt
  `MeasurementVersionTests`: its fixture row `[v2, v1]` still picks `v2`, so add a row listed oldest first).
  The existing test that fast mode compiles both the primary and the measure version must still pass.
- [ ] 14. **Consequences, no new work.** Do not regenerate `runs/cache/` context or profile files: for the three
  Putnam rows the cache key (it contains the measure version's commit) changes and they rebuild on first use. Do not
  edit `cli/lean_load.py` (ticket 07 decides the load tool's primary toolchain).

## Do NOT

- Do not change the spend rule, `limit_reached`, or the finish gate (ticket 02).
- Do not change DeepSeek's reasoning replay or trimming (D25), and do not remove
  `requires_reasoning_content_on_assistant_messages` for MiMo (Xiaomi says keep it).
- Do not lower `provider_timeout_ms` or change its 120000 value: whether it should be lower is an owner decision
  (plan §9 says "low"; list it as an open question in the hand-back).
- Do not make `error_loop` fire on transport failures, and do not let `provider_unreachable` fire before the wall-clock
  limit.
- Do not hide the real error text: it goes in the control row; the model never sees provider error text.
- Do not add a new continuation text for failed requests (`request_failed`, ISSUES #26) or new
  malformed-argument handling (#27): they belong to later tickets. Only the `turn_cut` line is added here.
- Do not create `benchmark/derived/measure-versions.json`. Do not touch `HEARTBEAT_WRAPPER` (D32).
- Do not read `/proc` or live Lean sessions in any new test.
- New model-facing text lives in `agent-text/` (D3); the `turn_cut` template is the only one this ticket adds.

## Acceptance

- Five failed requests with no content, then a good answer: the run keeps going. A silent provider for longer than
  `outage_limit_ms` ends the run with `provider_unreachable`, the error text in the control row, and the campaign
  report lists it for rerun.
- Three model-side failures in a row still end with `error_loop`.
- A turn that stops at the output ceiling causes no compaction, its reasoning is in the next request, and the next
  message states `The previous turn was cut at N tokens.`
- `arena run --dry-run` for MiMo shows `reasoning_effort: "none"` is applied only to tool-result turns (the unit test
  proves it); DeepSeek payloads are unchanged.
- `measure_version` returns the newest listed toolchain for all 15 rows, equal to the old first-listed for every
  non-Putnam row.
- The summary no longer labels a candidate that fails a listed version as "best verified".
- No non-slow test reads the live machine.

## Verify

- `uv sync` -> ok.
- Targeted files first: `uv run pytest -q -p no:cacheprovider tests/test_engine.py tests/test_summary.py tests/test_models.py
  tests/test_environments.py tests/test_campaign.py tests/test_lean_session.py` -> all pass (use the real file names
  that hold the tests you changed).
- Then the fast suite, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count + new tests).
- `cd packages/arena-pi && npm test` -> all pass (baseline 36 + outage, thinking and any new tests).
- `uv run ruff check <touched files> && uv run ruff format --check <touched files>` -> clean;
  `uv run ty check arena/engine.py arena/summary.py arena/models.py` -> no new diagnostics.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_runner.py -k "OutageTests or TruncationTests"` -> pass.
  Then `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_runner.py -k "LifecycleTests or CompactionPolicyTests or FinishReplayTests"` -> pass.
  One slow command at a time.
- `uv run python -c "from arena import engine; import json; [print(r['name'][:40], engine.measure_version(r)[0]) for r in map(json.loads, engine.BENCHMARK.read_text().splitlines())]"` -> 15 lines; the Putnam rows print v4.27.0, v4.26.0, v4.27.0.
- Known pre-existing slow failures (also fail on tag v6; do not fix unless this ticket is about them):
  `tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas`
  and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`
  (fixed by tickets 15c/16); `LeanMcpTests` is flaky. The two outage tests of item 6 are rewritten, not left failing.

## Stop and report if

- No supported Pi mechanism lowers `maxTokens` for the run's model (item 7). Report what you found about
  `modelOverrides`, `registerProvider` and the agent directory.
- Pi still compacts or drops the cut turn after `maxTokens` equals the ceiling (for example because a provider
  reports slightly less output than the ceiling): show the `usage.output` values you saw.
- The `agent_before_settle` event does not expose the last assistant message or its failure kind well enough to
  classify transport against model failures, so item 2 cannot be built as written.
- Reproduction in item 11 shows a different bug from the expected one.
- Changing `measure_version` breaks a test or caller for a reason other than the three Putnam rows.

## Before you start

1. Read, in this order: this whole ticket; `docs/SPEC-harness-v7.md` (sections named in this ticket); the
   `docs/PLAN-harness-v7.md` sections named in this ticket. The plan's decision rows (D1-D39 at the top) are
   binding: do not undo a decision, and do not undo any "probe evidence" listed in the spec's Further Notes.
2. Run `uv sync` once. All Python runs through `uv run`.
3. Record a baseline **before any edit**, only for the tests this ticket touches: run the test files named in
   this ticket's "Verify" section (and the test files for the modules you will change). Keep the output for
   your hand-back. Do **not** run the whole slow suite for a baseline.
4. If something in this ticket contradicts the code you find, or a step is impossible as written, **stop and
   report**. Do not guess, and do not redesign.

## Rules for every change

- Do exactly what the checkboxes ask. Nothing outside this ticket's scope: no drive-by refactors, no renames,
  no "while I'm here" fixes. If you see a real bug outside scope, list it in the hand-back.
- **No model-facing text in code** (D3): any string the model reads (tool descriptions, replies, notices,
  packet text) goes in `agent-text/` (after ticket 05a) and is rendered by the template renderer.
- **Neutral wording** in anything the model reads: graph position and numbers only. Never name a kind of proof
  ("induction", "lemma", "recursion", "simp proof", ...).
- Match the surrounding code: naming, comment density, idioms. Python 3.13, type hints where the file uses them.
- Python you touch must pass `uv run ruff check <files>` and `uv run ruff format <files>`. Fix ty diagnostics
  in the files you touch (`uv run ty check <files>`); do not touch other files to fix them.
- **Test runtime budget.** Today the fast suite (`uv run pytest -q -p no:cacheprovider`, no Lean, no Pi) takes
  about 35 s; `tests/test_runner.py` with `ARENA_SLOW_TESTS=1` takes about 7 min; the full slow suite takes most of
  an hour. So:
  - While developing, run only the tests you changed or that cover the code you changed:
    `uv run pytest -q -p no:cacheprovider tests/test_x.py -k <name>`.
  - Run the fast suite **once**, at the end, before your final commit.
  - Run a slow test file (`ARENA_SLOW_TESTS=1 ...`) only if this ticket's "Verify" lists it, and only **once**
    at the end (plus once for the baseline). Never run `ARENA_SLOW_TESTS=1` on the whole `tests/` directory.
  - `npm test` is under a second; run it whenever you change TS.
  - If a test you add takes more than 5 s, it must be `@slow`.
- Tests: only behaviour where a bug costs points, money or time. No tautological tests (no restating
  constants or config, no "mock was called", no substrings copied from the source under test, no dataclass
  defaults). Python tests are unittest style, run by pytest. Lean- or Pi-backed tests use the `@slow`
  decorator from `tests/slow.py`. TS tests use `node:test`.
- Never read `/proc` or live Lean sessions from a test; inject machine readings.
- Foreground commands only. No background jobs, no polling loops, no `sleep` loops. Kill processes **by PID
  only**, never by name or pattern (`pkill -f`, `killall` are forbidden).
- Never print, log or commit secrets (`.env` holds API keys). Never spend money: no real model calls. Paid runs
  are launched by the owner only.
- Do not edit `docs/`, `research/`, `vendor/` or other tickets. Proposed doc changes go in the hand-back.

## Version control (GitButler)

Your branch is **`v7/06-run-fixes`**, already created and stacked directly above `v7/05b-agent-messages`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/06-run-fixes` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/06-run-fixes -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-06`.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`,
  `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or
  `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`,
  `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`,
  `branch`, `update-ref`, `push`, `rm`, `mv`). Read-only `git log`, `git show`, `git diff` and `git blame` are
  fine. To delete or move a tracked file, use the shell (`rm`, `mv`); GitButler sees the change.
- If you need to change code a lower ticket introduced, do it in a commit on your own branch and say so in the
  hand-back. If `but commit` reports a dependency or conflict error, stop and report rather than moving branches.

## Hand-back (required)

Your work is finished only when all of this is true:

- [ ] Every checkbox in "What to build" and "Acceptance" is done, or listed below as not done with the reason.
- [ ] Every change is committed on `v7/06-run-fixes`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-06
Commits: <id> <summary>, one per line, oldest first
Checkboxes: each checkbox, done / not done (+ reason)
Tests: baseline -> final counts for every command you ran, with failures named
Verify: output summary of each Verify command (timings, numbers)
Files: every file added, changed or deleted, one line each on why
Decisions: anything you had to decide that this ticket did not say
Deviations: anything done differently from the ticket, and why
Out of scope: bugs or problems noticed but not fixed
Open questions: for the reviewer
```

Do not mark the ticket done; the reviewer does.
