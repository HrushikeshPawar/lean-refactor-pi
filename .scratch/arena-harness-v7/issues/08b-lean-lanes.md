# 08b: Lean service lanes, memory, goals and snippets on the LSP lane

**What to build:** The Lean service from ticket 08a gets its memory policy and its lanes. The model's primary toolchain keeps 2-3 warm workers that nothing evicts; every other toolchain has one background worker that is opened lazily and never at the model's expense; every worker's memory (PSS) is logged. The health gate returns as soon as the primary toolchain's reference proof passes, and the other toolchains are warmed in the background. A timed-out check returns the messages produced so far, and the probe timeout drops from 180 s to about three times the warm reference check. The LSP lane also answers "what are the goals at this position" and "run these snippets at this hole", which is what the lean-lsp-mcp server did and which ticket 15b removes. Cross-version checks run only for candidates that could become the best verified, and at close-out.

**Blocked by:** 08a: Machine-wide Lean service process (all lower tickets are committed below your branch).

**Status:** needs-review

**Branch:** `v7/08b-lean-lanes` (stacked on `v7/08a-lean-service`)

**Read first:** SPEC "Lean service" (Modules), "Speed baseline and gate", "Testing Decisions" Seam C; PLAN §9b (Lean machinery), §9c (Lean audit, savings 3, 4, 6, 7), §9d (blockers to sharing), §4b ("Gap" paragraph on lean-lsp-mcp), §12b (#13, #15, #25d); decisions D31, D35, D40 and owner decisions 3 (health gate), 4 (speed gate), 11 (MCP removed), 12 (stories 28 and 29), restated in the checkboxes below. SPEC user stories 21, 23-31 (28 and 29 are in this ticket).

## Context: where things are now
(After ticket 08a. Verify each name with grep before you edit.)
- `arena/lean_session.py`: the machine-wide service. `Session` has `leases` and `holds` (ticket 08a), `_referenced(project)`, `_is_primary(project)` (true when a live lease names the project as `primary`) and `_is_adhoc(entry)`. `Session._may_open(entry, lane, reserve)` limits model documents per toolchain by `MAX_SLOTS` (4) and the machine by the worker tokens (`MACHINE_MAX_WORKERS`, `BACKGROUND_TOKENS`); `BACKGROUND_SLOTS = 1` is the background worker per toolchain. `Session._evict_idle(keep)` closes another toolchain's idle model worker to make room for a model request (PLAN §12b #25d); `_acquire` calls it. `Session._grow` opens the remaining model documents in the background after the first model check on a primary project. `Session.warm(request)` opens documents and waits. `Session.check(request)` serves one check; on timeout `LeanServer.check` returns `{"timeout": True, "warm_kept": ...}` and the partial diagnostics in `_Doc.diagnostics` are dropped. `render(diagnostics, text, display)` turns LSP diagnostics into `lean <file>` text. `_codepoint_column` converts an LSP (UTF-16) column to a code-point column. `process_tree`, `tree_pss_gb`, `_available_gb` read `/proc`; `Session._measure` records one average PSS per worker the first time; nothing logs PSS per worker.
- `arena/engine.py`: `run_lean(row, project, text, timeout, prefix_end, lane)`, `warm_session(row, version, commit, slots, lane)`, `_session_request(row, project, text, prefix_end)`, `lean_timeout()` (env `ARENA_LEAN_TIMEOUT`, default `DEFAULT_LEAN_TIMEOUT = 180`), `last_lean_run()` (the `_LAST.info` dict), `measure_version(row)`, `workspace(row, version, commit)`.
- `arena/lean_health.py`: `gate(theorem, slots, directory, *, row_fn, versions_fn, warm_fn, check_fn, log, now_fn)` warms every listed version and compiles the reference proof on every one (`_reference_check`, always `lane="model"`), `choose_limit(slowest_warm)` is `clamp(max(LIMIT_FLOOR=180, 3 x slowest warm reference check), <= LIMIT_CAP=900)`, `HEALTH_FILE = "lean-health.json"`, `TRIPPED_FILE = "lean-unhealthy.json"`, `STOP_REASON = "lean_unhealthy"`, `tripped(directory)`, `trip_if_unhealthy`, `apply_timeout_env`.
- `tools/run_pi_budgeted.py`: `lean_gate(theorem, directory, gate_fn)` computes `slots = min(lean_session.MAX_SLOTS, 4)` and calls `lean_health.gate`.
- `arena/campaign.py`: `_autocheck_jobs(rows)` returns every candidate whose status is `primary` and that has no `full` evaluation, best score first; `autocheck(name, run_id, max_seconds)` drains that queue in the background lane through `record_evaluation(..., "full", lane="background", trigger="auto")`; `_best(rows)` ranks by `(verified, score)`. Callers: the TS extension spawns `arena protocol autocheck` while the run goes (`packages/arena-pi/extensions/arena.ts`, `tools/arena_campaign.py` action `autocheck`), and `tools/run_pi_budgeted.py` drains it once at close-out (`autocheck(args.theorem, args.run_id, DRAIN_S)` in `finish`).
- lean-lsp-mcp (`packages/arena-pi/extensions/arena.ts`, server `arena-lean`, `lean-lsp-mcp==0.31.0`) starts its own Lean workers outside every budget; its `lean_goal` and `lean_multi_attempt` are what the model uses today for goals and for trying snippets. Ticket 15b removes the server (D40); ticket 15a builds the model-facing tools on top of what this ticket adds.
- Tests: `tests/test_lean_session_warm.py` (fast; `FakeLean` is a scripted fake language server in the `FAKE` script, patched over `lean_session.LeanServer`; `Base.session(...)`, `Base.request(...)`), `tests/test_lean_session.py` (slow, real Lean, `SessionHarness`, `TOLERANCE = 0.05`), `tests/test_lean_health.py` (fast), `tests/test_protocol.py` (fast; the autocheck tests around `test_autocheck_reuses_the_primary_result_and_checks_best_first`).

## What to build

### Lanes and memory policy

- [ ] 1. Lanes by name in `Session.check` / `Session.warm` (the request's `lane` field): `model` (interactive compile, goals, snippets, per-step goals; one `_Doc` per concurrent draft) and `background` (the lazy cross-version lane). `cold` is not served here: `engine._run_cold` stays the cold lane, untouched. A `model` request for a project that a live lease names as `primary`, or that a `hold` names, or that is ad hoc (ticket 08a), is served on the model lane. A `model` request for any other project (one that is only in `others` of a lease) is served on that project's background lane, never opens a model worker there, and the reply says `"lane": "background"`.
- [ ] 2. Memory policy as constants and rules in `Session._may_open`: `PRIMARY_MIN_WORKERS = 2` (the number the runner and the gate warm; kept warm while the project is referenced as primary, which ticket 08a's close rule already guarantees), `PRIMARY_MAX_WORKERS = 3` (model documents per primary or ad hoc project), `OTHER_WORKERS = 1` (the background worker of every project), `RESERVE_GB = 5.0` (unchanged). Replace `MAX_SLOTS`, `MAX_WORKERS` and `BACKGROUND_SLOTS` by these (delete the old constants; `grep -rn "MAX_SLOTS\|BACKGROUND_SLOTS\|MAX_WORKERS" arena tools tests` and update every use). The machine-wide worker tokens stay. `warm` with `lane: "model"` opens at most `PRIMARY_MAX_WORKERS`; `_grow` still opens the remaining model documents after the first model check on a primary project, up to `PRIMARY_MAX_WORKERS`, as memory allows. In `tools/run_pi_budgeted.py` `lean_gate` set `slots = lean_session.PRIMARY_MIN_WORKERS`.
- [ ] 3. Never evict a model worker of a referenced primary project: delete `Session._evict_idle` and its call in `_acquire`. A new worker that does not fit (memory or token) may only be made room for by closing idle **background** workers of other projects, longest idle first, never the requesting project's own and never a worker that is busy; if none can be closed the request fails with `no room for a Lean worker: <why>` as today and `_refused` touches the marker.
- [ ] 4. Lazy cross-version lane: add `"wait": false` to the `warm` op. With it the service starts the open in a thread and replies at once with `{"ok": true, "started": true}`. Opens still go through `WorkerBudget.opening`, so only one header loads at a time machine-wide. In `arena/engine.py` `warm_session(row, version, commit, slots, lane="model", wait=True)` forwards it.
- [ ] 5. Memory logging: (a) `worker_pss(root_pid) -> dict[int, float]` returning PSS in GB per Lean worker process (`lean --worker`) under a server pid, built on the existing `process_tree` and `smaps_rollup` reading; (b) `external_lean_pss(own_pids) -> dict[int, float]`: PSS of every other process on the machine whose command name is `lean` (a hand-run Lean, or lean-lsp-mcp's workers while the MCP server still exists); (c) the service's 1-second `watch` loop appends one JSON line to `pss.jsonl` in the service directory every `PSS_LOG_S = 60` seconds: `{"ts", "mem_available_gb", "swap_used_gb", "servers":[{"project","workers":[{"pid","gb","lane"}]}], "external_lean_gb"}`, and `_log`s a one-line summary; rotate `pss.jsonl` to `pss.jsonl.1` above 5 MB. `Session` takes `mem_fn`, `pss_fn` and `external_fn` constructor arguments (defaults: the real readers) so tests inject readings. `status` includes the same numbers.
- [ ] 6. External Lean processes are still counted (D40; the MCP server goes away in ticket 15b, so nothing here depends on it): their memory reaches the service through `external_lean_gb` in `status` and `pss.jsonl`, and through `MemAvailable`, which `_may_open` and `WorkerBudget.opening` already read, so it already lowers what the service may open. Do not change `packages/arena-pi/extensions/arena.ts`, and do not add any code that makes lean-lsp-mcp a backend of the service or of `compile`/`goal` (ticket 15b deletes the server).

### Health gate (owner decision 3, revised)

- [ ] 7. `arena/lean_health.py` `gate`: the model starts as soon as the **primary** toolchain's reference proof passes. The primary is `gate_versions(row)[0]`. It is warmed with `slots` model workers and its reference proof is compiled on the model lane, as now. Every other version is warmed with `warm_fn(row, version, commit, 1, lane="background", wait=False)` and is **not** reference-checked inside `gate`: it does not enter the verdict, the reasons or the limit (`choose_limit` uses the primary's check only). Each such version is recorded in the report and in `lean-health.json` as `{"warmup": "background", "checked": false}`; the report gets `"pending": [version, ...]` (the versions whose reference check is still to run). `_reference_check(row, version, commit, timeout=LIMIT_CAP, lane="model")` gains the `lane` argument. `gate` returns once the primary is decided; it must not wait for the other warm-ups.
- [ ] 8. Add `lean_health.check_others(theorem, directory, *, row_fn=None, versions_fn=None, check_fn=None, cancelled=lambda: False, log=print, now_fn=time.time) -> list[dict]` (the background half of the gate; ticket 08c starts it in a thread). For each version in `gate_versions(row)[1:]`, one after another, unless `cancelled()` is true: run `check_fn(row, version, commit, lane="background")` (default `_reference_check`), then update that version's entry in `lean-health.json` (read the file, set `checked: true`, `passed`, `check_seconds`, `timed_out`, `detail`, rewrite it) and append the entry to the returned list. If a version fails (not passed, or no worker could open its header), call the new `lean_health.trip_unhealthy(directory, version, detail, now_fn=time.time)` and stop checking: it writes `TRIPPED_FILE` as one JSON line `{"ts", "stop_reason": STOP_REASON, "source": "reference_check", "version", "detail"}` (the same file `tripped()` already reads) and logs a one-line truthful reason naming the version. A version that passes only logs. Nothing in this ticket calls `check_others` outside tests.
- [ ] 9. Probe timeout near three times the warm reference check (spec story 29; PLAN §9c savings 4): in `choose_limit` change `LIMIT_FLOOR` from 180 to 60, so the per-check limit `ARENA_LEAN_TIMEOUT` is `clamp(max(60, 3 x the primary's reference check seconds), <= 900)` instead of never below 180 s. The header import is not charged to a check's timeout (`OPEN_TIMEOUT`), so the lower floor does not make header loads time out. `MAX_USE` and `LIMIT_CAP` stay. `DEFAULT_LEAN_TIMEOUT = 180` in `engine.py` stays (it applies only when no gate ran). The floor of 60 s is this ticket's pick (open question for the owner: the plan says only "near 3x warm p95"); put the limits the gate chose on the four baseline rows in the hand-back.
- [ ] 10. Timeout returns partial messages (spec Seam C, story 29): in `LeanServer.check`, on `TimeoutError` before the document is reset to its header, read `doc.diagnostics` if its `version` equals the sent version, and record the last `$/lean/fileProgress` line seen for the document (handle that notification in `_dispatch`; store the highest `range.start.line` of a `processing` item as `doc.progress_line`, 0-based). Return `{"timeout": True, "partial": <diagnostics list or []>, "progress_line": <int or None>, ...}`. `Session.check` passes both through and adds a rendered `partial_output` (use `render`). In `engine.run_lean` put `partial_output` and `progress_line` into `_LAST.info`; the return value on timeout stays `None`. Nothing else consumes them yet (tickets 10b and 15a do). The `warm_kept` behaviour is unchanged.

### Goals and snippets at a hole (owner decision 11, D40)

- [ ] 11. Service op `goal` on the LSP lane: request `{"op":"goal","protocol":2,"project","fingerprint","text","display","header_end","position":{"line":int,"column":int},"timeout":float,"lane":"model"}`; `line` is 0-based and `column` counts code points (add `_utf16_column(line_text, column)`, the inverse of `_codepoint_column`, for the LSP request). It is served like `check` (same lane rule, same worker acquisition, same stale and error replies): the document is first made to hold `text` through `LeanServer.check` (cheap when it already holds exactly this text), then `$/lean/plainGoal` and `$/lean/plainTermGoal` are requested at the position through `LeanServer._request`. Reply `{"ok": true, "goals": [str, ...], "rendered": str | None, "term_goal": str | None, "seconds", "lane", "new_worker", "header_seconds"}`: `goals` is the `goals` list of the plain-goal result (empty when Lean says there are none, or the position is past the last goal), `rendered` its `rendered` text, `term_goal` the `goal` string of the term-goal result. A timeout in the check returns the same `timeout` reply as `check`.
- [ ] 12. Service op `try` (the model's `goal try`): request `{"op":"try","protocol":2,"project","fingerprint","text","display","header_end","hole":{"line","column","end_line","end_column"},"snippets":[str, ...],"timeout":float,"lane":"model"}` with the same coordinates as `goal`, `snippets` having 1 to `TRY_MAX_SNIPPETS = 8` entries (more is an error reply; ticket 15a sets the model-facing limit). `text` is the whole candidate file and `hole` the range to replace. For each snippet, one after another on the one worker the request holds: the variant file is `text` with the hole range replaced by the snippet; make the document hold it through `LeanServer.check`, render its diagnostics against the variant (`render`), and request `$/lean/plainGoal` at the end of the inserted snippet. Reply `{"ok": true, "results": [{"returncode", "output", "goals_after": str | None, "seconds", "timeout": bool}, ...], "lane", "new_worker", "header_seconds"}`; `goals_after` is the rendered goal text, or `None` when no goals remain. A snippet that times out gives `{"timeout": true}` for that entry only; later snippets still run. The document is left at the last variant, which is fine because every request names its whole text.
- [ ] 13. Client wrappers in `arena/engine.py`: `lean_goals(row, project, text, prefix_end, line, column, timeout=None) -> dict | None` and `lean_try(row, project, text, prefix_end, hole, snippets, timeout=None) -> dict | None`. Each builds its payload from `_session_request` plus the op fields, sends it with `lean_session.request`, and returns the reply, or `None` when no service is configured (no cold fallback here; ticket 15a decides what the model sees). `timeout` defaults to `lean_timeout()`. They are unused until ticket 15a.

### Cross-version checks only when they could matter (spec story 28)

- [ ] 14. `arena/campaign.py`: `_autocheck_jobs(rows, closing=False)` returns every candidate it returns today when `closing` is true; otherwise it keeps only candidates that could become the best verified: let `bar` be the `score` of `_best([r for r in rows if r["verified"]])` (no bar when there is none); a job stays when `bar` is `None`, or its `score` is `None`, or `score >= bar`. `autocheck(name, run_id, max_seconds=None, closing=False)` passes it through (including to the `remaining` list it returns). In `tools/run_pi_budgeted.py` the close-out drain call becomes `autocheck(args.theorem, args.run_id, DRAIN_S, closing=True)`. The in-run callers (the TS extension's `arena protocol autocheck` and `tools/arena_campaign.py`) keep the default `closing=False`; do not change them or the `checking` list in the state text.

### Tests and gate

- [ ] 15. Fast tests in `tests/test_lean_session_warm.py` (use `FakeLean`; patch `_available_gb` as `Base.setUp` does). Delete `test_model_requests_do_not_evict_for_background_but_may_for_another_model_request`. Rewrite `test_background_never_evicts_a_model_worker_even_with_no_machine_room` and `test_background_is_guaranteed_even_when_model_workers_hold_every_machine_token` for the new limits. Add (Seam C):
  - cross-version warm-up never evicts the model lane: a primary project holding `PRIMARY_MIN_WORKERS` warm documents, three other projects warmed on the background lane with no memory room: no `didClose` of a primary document; the others are refused or closed among themselves;
  - a `model` request for a project that is only in `others` of a lease is served on the background lane (`reply["lane"] == "background"`) and opens no model worker; a project named by a `hold` serves model requests on the model lane;
  - a new background worker with no room closes only an idle background worker of another project, never a busy one and never a model worker;
  - `warm` with `"wait": false` replies `started` before the fake's header open finishes, and two such opens never load a header at the same time;
  - a timeout reply carries `partial` and `progress_line`, the next check does not reopen the header (extend `FAKE` so it publishes one diagnostics batch and a `$/lean/fileProgress` line before the slow part);
  - the `goal` op returns the fake's goals and term goal for a position (extend `FAKE` to answer `$/lean/plainGoal` and `$/lean/plainTermGoal`), and a column with a non-BMP character is converted to the right UTF-16 column;
  - the `try` op runs each snippet on the same document, returns one result per snippet in order with `goals_after`, a timed-out snippet does not stop the later ones, and 9 snippets are refused.
- [ ] 16. Fast tests for the memory log in the same file: with injected `mem_fn`/`pss_fn`/`external_fn`, one watch step writes a `pss.jsonl` line with per-worker `gb` and `external_lean_gb`, and rotation happens above the size limit (patch a small limit through a constant).
- [ ] 17. Update `tests/test_lean_health.py` for the new `gate` and add tests for `check_others`: the primary is warmed with model workers and checked, the gate returns without waiting for the other warm-ups; other versions get a `lane="background", wait=False` warm and no check inside `gate`, with entry `{"warmup": "background", "checked": false}` and `report["pending"]` listing them; an unhealthy non-primary version does not make the verdict unhealthy; `choose_limit` follows `max(60, 3 x slowest)` and stays under 900; `check_others` checks the others one after another, updates `lean-health.json`, writes `lean-unhealthy.json` with `source: "reference_check"` and the version on the first failure and does not check later versions, stops when `cancelled()` is true, and writes no marker when every version passes. Delete only the assertions that no longer hold; do not weaken the tests for the primary.
- [ ] 18. Fast tests in `tests/test_protocol.py` for checkbox 14: with `closing=False` a candidate scoring below the best verified is not queued and one at or above it is; with no verified candidate every job is queued; with `closing=True` all are queued; `remaining` follows the same rule. Keep `test_autocheck_reuses_the_primary_result_and_checks_best_first` passing (adjust its setup only if the new rule changes which candidates it queues, and say so in the hand-back).
- [ ] 19. Slow tests in `tests/test_lean_session.py` (Core row; build drafts the way the existing tests do with `SessionHarness`): (a) a draft that runs past a 1 s timeout (the `slow` kind of `make_proof` in `arena/cli/lean_load.py`, or `tools/lean_load_test.py` if ticket 04 left it there) returns `timeout`, `warm_kept` and a `partial_output` string, and the next quick check on the same worker has `new_worker` false and `header_seconds` None; (b) `goal` at the position of a `sorry` in a draft returns at least one goal containing the theorem's hypotheses, and at the end of a proof that compiles returns none; (c) `try` with two snippets at a hole, one that closes the goal and one that does not: the first has `returncode` 0 and `goals_after` None, the second `returncode` 1 or non-empty `goals_after`. Keep every session-equals-cold test unchanged.
- [ ] 20. Speed gate, run **once, at the end** (owner decision 4): `uv run arena lean bench --compare benchmark/derived/lean-baseline.json` (other flags as ticket 07 recorded the baseline with; `--help`). A figure fails only if it exceeds BOTH the relative tolerance (+10% p50, +20% p95) AND the 0.25 s absolute noise floor; the command already applies this. Paste the table in the hand-back. If a figure fails, stop and report; do not loosen the tolerance or the floor.

## Do NOT
- Do not change `WorkerBudget.acquire`, `available` or `opening`, `RESERVE_GB`, `OPEN_TIMEOUT`, the header-first open, the `warm_kept` timeout behaviour, `render`, `fingerprint`, `reorder_lean_path`, `NO_LAKE`, or LSP message handling beyond checkboxes 10 to 12.
- Do not touch `engine.run_lean`'s fallback logic (`cold`, `cold-fallback`), `_run_cold`, `compile_version` or the heartbeat wrapper. The cold lane stays as it is.
- Do not start `check_others` from the runner (ticket 08c does) and do not change `tools/run_pi_budgeted.py` beyond the `slots` line (checkbox 2) and the `closing=True` call (checkbox 14).
- Do not change `cold_verify`, `submission`, or the rule that every listed toolchain must pass for a candidate to count as verified: the final verification at close-out still cold-compiles the best proof on every listed toolchain.
- Do not add the REPL pool (ticket 08d) or the campaign pre-warm (ticket 09).
- Do not change `packages/arena-pi/` (the MCP server is removed in ticket 15b, not here), do not add lean-lsp-mcp as a backend of anything, and do not edit `models.yaml`.
- No model-facing text is added. `partial_output`, `goals` and `goals_after` are data for later tickets.
- Do not weaken a session-equals-cold test, and do not replace real-Lean slow tests by fakes.
- Never run two Lean-heavy commands at once: the slow tests, `arena lean bench` and any manual Lean run go one after another, and no `lake build` or `arena provision` while one runs. The machine has 8 cores and 30 GB; the baseline was recorded on an idle machine.
- Kill processes by PID only (the service pid from `service.json`); never `pkill`, `killall` or `pgrep -f | kill`. Do not leave a service running when you finish: run `uv run arena lean stop` and confirm `uv run arena lean status` says no service.

## Acceptance
- A model request never evicts another project's model worker; cross-version warm-up never closes a primary worker (the fast test shows it).
- The health gate returns as soon as the primary toolchain's reference proof has passed; the other toolchains are warming in the background, are not part of the gate's verdict, and `lean-health.json` says so. `check_others` marks the run unhealthy (`lean-unhealthy.json`, stop reason `lean_unhealthy`, the failing version named) when a reference check fails.
- The per-check limit for a row whose reference check takes 3 s is 60 s, not 180 s.
- A timed-out check returns partial messages and the worker stays warm.
- `goal` returns the goals at a `sorry` position and `try` runs snippets at a hole and reports each result, on the LSP lane, with no lean-lsp-mcp involved.
- `pss.jsonl` gets a line every 60 s while workers exist; `arena lean status` shows per-worker PSS and `external_lean_gb`.
- During a run, candidates that cannot beat the best verified are not queued for cross-version checks; the close-out drain still checks every candidate.
- The ticket-07 speed gate passes.

## Verify
TEST BUDGET: targeted files, then the fast suite once, then one slow file, then the gate once.
- `uv run pytest -q -p no:cacheprovider tests/test_lean_session_warm.py tests/test_lean_health.py tests/test_protocol.py -k "lean or health or autocheck or session or warm"` -> all pass.
- `uv run ruff check arena tools tests && uv run ruff format --check arena tools tests` -> clean for the files you touched.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_lean_session.py` -> all pass, one test at a time (needs `workspaces/strata-v4.29.1`; PhysLib tests skip when it is absent).
- `uv run arena lean bench --compare benchmark/derived/lean-baseline.json` (checkbox 20) -> exit 0.
- `uv run pytest -q -p no:cacheprovider` (fast suite, once, at the end) -> all pass.
- `cd packages/arena-pi && npm test` -> all pass (unchanged).
- `uv run arena lean stop && uv run arena lean status` -> "no service".
Known pre-existing slow failures (also fail on tag v6; do not fix): `tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas` and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`; `LeanMcpTests` is flaky. Neither is run by this ticket.

## Stop and report if
- Ticket 08a's service, leases, holds, `Session._is_primary` or `Session._is_adhoc` do not exist as described, or `arena lean bench` and its saved baseline (ticket 07) are missing.
- The speed gate fails on any figure after checkbox 20.
- The language server does not answer `$/lean/plainGoal` or `$/lean/plainTermGoal` with the shapes in checkbox 11 (report the reply you got).
- A slow test that passed before your change fails and the cause is not in code you wrote.
- Another process (a campaign, a run, another service) is using the machine's Lean while you need the idle machine for the gate.
- Removing `MAX_SLOTS`, `MAX_WORKERS` or `BACKGROUND_SLOTS` breaks a caller outside the files named here.
- Lowering the limit floor to 60 s makes a slow test or a baseline row time out that passed before.

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

Your branch is **`v7/08b-lean-lanes`**, already created and stacked directly above `v7/08a-lean-service`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/08b-lean-lanes` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/08b-lean-lanes -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-08b`.
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
- [ ] Every change is committed on `v7/08b-lean-lanes`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-08b
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
