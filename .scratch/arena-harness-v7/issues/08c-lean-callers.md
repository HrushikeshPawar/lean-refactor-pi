# 08c: Lean service callers, tests, speed gate

**What to build:** The runner and the campaign command use the service the way the gate now allows. After the primary toolchain's reference proof passes, the runner starts the reference checks of the other listed toolchains in a background thread; if any of them fails, the run is marked unhealthy and Pi is stopped before further spend, with a truthful stop reason that names the toolchain. Campaign housekeeping counts the memory of the warm service as available so a resident service never makes runs wait. The end-to-end runner tests and the speed gate close the Lean-service work. Final verification at close-out still cold-compiles the best proof on every listed toolchain, and `arena submit` still requires every toolchain green; this ticket does not relax either.

**Blocked by:** 08b: Lean service lanes, memory, goals/snippets on the LSP lane (all lower tickets are committed below your branch).

**Status:** ready-for-agent

**Branch:** `v7/08c-lean-callers` (stacked on `v7/08b-lean-lanes`)

**Read first:** SPEC "Lean service" (Modules), "Speed baseline and gate", "Testing Decisions" Seam C; PLAN §9b, §9d (blockers to sharing), §12b (#13); decision D35 and owner decisions 3 (health gate, callers and tests), 4 (speed gate). SPEC user stories 23, 26, 27.

## Context: where things are now
(After tickets 08a and 08b. Verify each name with grep.)
- `arena/lean_health.py`: `gate()` returns once the primary toolchain's reference proof is decided and lists the other toolchains in `report["pending"]`; `check_others(theorem, directory, *, row_fn, versions_fn, check_fn, cancelled, log, now_fn)` runs their reference checks one after another, updates `lean-health.json` and calls `trip_unhealthy(directory, version, detail)` on the first failure, which writes `lean-unhealthy.json` (`TRIPPED_FILE`, `source: "reference_check"`, `version`, `detail`, `stop_reason: "lean_unhealthy"`); `tripped(directory)` reads it. Nothing calls `check_others` yet.
- `tools/run_pi_budgeted.py`: `lean_gate(theorem, directory, gate_fn)` (called from `run()` right after the gate point, then `stop_unhealthy(args, directory, health["reasons"])` when the verdict is unhealthy); `run()` launches Pi in one segment with a local `state` dict (`process`, `signal`, `timer`, `tripped`), a `force_stop()` and an `interrupt()` handler, and in its stdout loop stops Pi cleanly when `lean_health.tripped(directory)` becomes true (printing "Lean circuit breaker tripped (N consecutive Lean timeouts or failures)"); `finish(..., tripped=...)` turns that into stop reason `lean_unhealthy` and exit code `lean_health.EXIT_CODE` (75). `start_lean_session(row)` / `stop_lean_session()` lease and release (ticket 08a); `_LEAN` holds the service state.
- `arena/campaign.py`: `_refuse_if_tripped(directory)` refuses model-lane work after the marker exists; `cold_verify(run_id, row)` cold-compiles a candidate on every listed version (not changed here).
- `tools/run_campaign.py`: `Housekeeping(min_free_gb, max_wait, started, evaluations, *, mem_fn, reap_fn, lingering_fn, sweep_fn, sleep_fn, now_fn, log)` with `before_run` waiting until finished runs' Lean processes are gone and, when nothing else runs, `MemAvailable >= min_free_gb`; `mem_available_gb()` reads `/proc/meminfo`. With the persistent service, resident workers lower `MemAvailable` between runs.
- `arena/lean_session.py` `request()`, `status` op (per-server `gb`), `service_dir()`; `arena/lean_session.configured()`.
- Tests: `tests/test_lean_health.py` (fast; has `HousekeepingTests` around `rc.Housekeeping(...)`), `tests/test_lean_session.py` (slow; `RunnerSessionTests` run the real runner and Pi against a scripted provider through `tests/pi_support.py` `FakeRun`).

## What to build

- [ ] 1. Runner: after `lean_gate` returns a healthy verdict in `run()`, call new `start_background_checks(theorem, directory, report, check_fn=None)` in `tools/run_pi_budgeted.py`. When `report["pending"]` is empty (one toolchain, no service, or the gate is off) it returns `None` and starts nothing. Otherwise it starts a daemon thread that calls `lean_health.check_others(theorem, directory, cancelled=_BACKGROUND["stop"].is_set)` (`check_fn` injects it in tests) and, when the returned list holds a failed entry, sets `_BACKGROUND["failed"]` (a `threading.Event`). `_BACKGROUND = {"thread": None, "stop": threading.Event(), "failed": threading.Event()}` is module state next to `_LEAN`; reset both events at the start of `run()` so a resumed run starts clean. At every way out of `main` set `stop` (do not wait for the thread). Change the printed gate line in `lean_gate` to say that the primary toolchain is checked first and the others in the background (operator console text, not model-facing).
- [ ] 2. Stop at once on a background failure: add `watch_background_failure(failed: threading.Event, directory: Path, stop_fn) -> threading.Thread` to `tools/run_pi_budgeted.py`: a daemon thread that waits on `failed` and then calls `stop_fn(message)` once, where `message` is built from `lean_health.tripped(directory)`: `Lean unhealthy on <version>: <detail>; stopping before further spend`. In `run()` start it for the Pi segment with a `stop_fn` that does what the breaker path in the stdout loop does: set `state["tripped"] = True`, print the message to stderr, `process.terminate()` and start the `force_stop` timer (reuse the same lines; factor them into one local function used by both). The existing per-line breaker check stays; in its printed message use the marker's `source` (a `reference_check` marker prints the `Lean unhealthy on ...` message instead of the "consecutive Lean timeouts" text). The stop reason and exit code are the existing `lean_unhealthy` and 75; `cost.json` and `summary.json` are written as for the breaker. No new stop reason.
- [ ] 3. Do not change the close-out: `cold_verify`, `submission` and the final verification still cold-compile the best proof on every listed toolchain, and a candidate counts as verified only when every listed toolchain passed. If no existing test in `tests/` asserts that `cold_verify` compiles every listed version (run `grep -rn "cold_verify" tests`), add one fast test that does, with a fake compile per version and one version failing; if one exists, name it in the hand-back and add nothing.
- [ ] 4. Housekeeping: `tools/run_campaign.py` gets `service_gb(status_fn=None) -> float` (sum of the `gb` fields of the service's `status` reply through `lean_session.request`; `0.0` when no service answers) and `Housekeeping.__init__` gets `service_gb_fn=service_gb` (keyword). In `before_run` compare `free + service_gb` with `min_free_gb` (`low = alone and free is not None and free + service_gb < self.min_free_gb`) and show both numbers in the waiting message. Without this a warm service makes every run wait the full `CLEANUP_WAIT_S`. `reap_run`, `lingering`, `recorded_pids`, `read_session_info`, `ours` stay as ticket 08a left them.
- [ ] 5. Fast tests in `tests/test_lean_health.py` and a new `tests/test_run_background_checks.py` (no Lean, no Pi, no model):
  - `start_background_checks` starts nothing when `pending` is empty; with a `check_fn` that reports one failed entry it sets `failed`; with all passing it does not;
  - `watch_background_failure` calls `stop_fn` exactly once with a message naming the failing version and detail when `failed` is set (write a real marker with `lean_health.trip_unhealthy` into a temp directory), and never when it is not set;
  - the runner's stop path for a `reference_check` marker maps to stop reason `lean_unhealthy` (call `finish` or the smallest function that decides it, with `tripped=True`; do not start Pi);
  - `HousekeepingTests`: with free memory 8 GB, `min_free_gb` 20 and the injected `service_gb_fn` returning 20.0, `before_run` starts at once; with `service_gb_fn` returning 0.0 it waits (the existing test style: injected `sleep_fn` and `now_fn`).
- [ ] 6. Slow test update in `tests/test_lean_session.py` `RunnerSessionTests` (they were moved to the service in ticket 08a): confirm each passes with the new gate (primary-first). Add one assertion to `test_tool_calls_run_in_the_session_and_nothing_is_left_after_the_run` that `lean-health.json` in the run directory lists the primary version as checked and passed. No new slow test is needed for the background failure path (the Core row lists one toolchain; the path is covered by the fast tests).
- [ ] 7. Speed gate, run **once, at the end** (owner decision 4): `uv run arena lean bench --compare benchmark/derived/lean-baseline.json` (other flags as ticket 07 recorded the baseline with; `--help`). A figure fails only if it exceeds BOTH the relative tolerance (+10% p50, +20% p95) AND the 0.25 s absolute noise floor; the command already applies this. Paste the table in the hand-back. If a figure fails, stop and report; do not loosen the tolerance or the floor.

## Do NOT
- Do not change `lean_health.gate`, `check_others` or `choose_limit` (ticket 08b), the service ops, the lanes or the memory policy.
- Do not change `cold_verify`, `submission`, `arena submit` or the verified definition; no relaxing of "every listed toolchain".
- Do not add a new stop reason, a new exit code, or a new marker file; reuse `lean-unhealthy.json`, `lean_unhealthy` and 75.
- Do not wait for the background thread at run end, and do not call `check_others` from anywhere but `start_background_checks`.
- Do not change `packages/arena-pi/` or `models.yaml`. No model-facing text is added.
- Do not run `ARENA_SLOW_TESTS=1` on anything but the file named in Verify, and never over all of `tests/`. Never run two Lean-heavy commands at once.
- Kill processes by PID only; never `pkill`, `killall` or `pgrep -f | kill`. Do not leave a service running: run `uv run arena lean stop` and confirm `uv run arena lean status` says no service.

## Acceptance
- With a fake `check_fn` that fails the second toolchain, the runner's stop path fires once, the marker names that toolchain, the stop reason is `lean_unhealthy`, and no model request is sent after the marker (the existing refusal in `_refuse_if_tripped` and the Pi stop).
- With every toolchain passing, the background checks add no stop and `lean-health.json` shows every version checked.
- A campaign started while a warm service holds memory does not wait for it (the housekeeping test shows it).
- The close-out still cold-verifies every listed toolchain (existing or added test).
- The ticket-07 speed gate passes.

## Verify
TEST BUDGET: targeted files, then the fast suite once, then one slow class, then the gate once.
- `uv run pytest -q -p no:cacheprovider tests/test_run_background_checks.py tests/test_lean_health.py` -> all pass.
- `uv run ruff check arena tools tests && uv run ruff format --check arena tools tests` -> clean for the files you touched.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_lean_session.py -k RunnerSessionTests` -> all pass (real runner and Pi against the scripted provider; the only slow selection this ticket needs).
- `uv run arena lean bench --compare benchmark/derived/lean-baseline.json` -> exit 0.
- `uv run pytest -q -p no:cacheprovider` (fast suite, once, at the end) -> all pass.
- `cd packages/arena-pi && npm test` -> all pass (unchanged).
- `uv run arena lean stop && uv run arena lean status` -> "no service".
Known pre-existing slow failures (also fail on tag v6; do not fix): `tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas` and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`; `LeanMcpTests` is flaky. Neither is run by this ticket.

## Stop and report if
- `lean_health.check_others`, `trip_unhealthy` or `report["pending"]` (ticket 08b), or `start_lean_session(row)` with `lease`/`release` (ticket 08a), do not exist as described.
- Stopping Pi from a thread needs a change to `finish`, the Pi extension or the stop-reason list beyond what checkboxes 1 and 2 say.
- A `RunnerSessionTests` test that passed before your change fails and the cause is not in code you wrote.
- The speed gate fails on any figure.
- Another process is using the machine's Lean while you need the idle machine for the gate.

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

Your branch is **`v7/08c-lean-callers`**, already created and stacked directly above `v7/08b-lean-lanes`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/08c-lean-callers` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/08c-lean-callers -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-08c`.
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
- [ ] Every change is committed on `v7/08c-lean-callers`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-08c
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
