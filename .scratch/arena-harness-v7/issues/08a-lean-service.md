# 08a: Machine-wide Lean service process

**What to build:** One long-lived Lean service per machine replaces the per-run daemon. Every run and campaign talks to it over one socket, so a header imported for a row stays warm for the next replicate and the next campaign. A run takes a lease naming its primary toolchain and the others it uses; the service closes a toolchain's workers when no live lease and no hold needs it, not on idle timers, and exits after a quiet spell. Nothing else about Lean behaviour changes in this ticket: lanes, the memory policy, the health gate and goals come in 08b to 08c. The Lean speed gate from ticket 07 must pass against the new service.

**Blocked by:** 07: Lean speed baseline and gate (all lower tickets are committed below your branch).

**Status:** done

**Branch:** `v7/08a-lean-service` (stacked on `v7/07-lean-gate`)

**Read first:** SPEC "Lean service" (Modules), "Speed baseline and gate", "Testing Decisions" Seam C; PLAN §9b (Lean machinery), §9c (Lean audit, savings 2 and 7), §9d (blockers to sharing, close policy); decisions D31, D35 and owner decision 4 (speed gate, restated in the last checkbox). SPEC user stories 21, 23, 26, 27.

## Context: where things are now
- `arena/lean_session.py` (about 1,400 lines) is the whole Lean machinery:
  - `Session` owns `entries: dict[str, _Entry]`, one `_Entry` per project path (a workspace is one toolchain, for example `workspaces/arklib-v4.30.0`). An entry holds one `LeanServer` (`lake env lean --server`) and `slots`, a list of `_Doc` (one LSP document = one file worker). `_Doc.lane` is `"model"` or `"background"`; `_Doc.header` is the text the document was opened with.
  - `Session.primary` is the first project asked for. `Session._share()` splits `MACHINE_MAX_WORKERS=8` across live sessions through `WorkerBudget.register/live_sessions/share` (session lock files in the token directory). `MAX_SLOTS=4` model documents per toolchain, `BACKGROUND_SLOTS=1`.
  - `Session._evict_idle` closes another toolchain's idle model worker to make room for a model request. `Session.reap_idle` closes background workers idle for `BACKGROUND_IDLE_S=900` and non-primary toolchains idle for `IDLE_SECONDS=600`. (Ticket 08b removes the eviction; leave `_evict_idle` as it is here.)
  - `Session._guard_prefix` stops the whole entry when the file prefix of a display name changes.
  - `WorkerBudget` (flock token files, `acquire`, `available`, `opening`) is machine-wide: `opening()` lets one header load at a time and checks `RESERVE_GB=5.0`. Keep it unchanged.
  - `serve(directory, parent, max_slots)` runs the daemon: a Unix socket in the RUN directory (`socket_path(directory)`), `lean-session.json` with pids, exits when `--parent-pid` dies. `start_daemon`, `stop_daemon`, `request`, `configured()` (env `ARENA_LEAN_SESSION` holds the socket path) are the client side. Ops: `status`, `warm`, `check`. `PROTOCOL = 1`. `memory_pressure(directory)` reads the marker file `lean-session.waiting` that `Session._refused` touches.
- `arena/engine.py`: `run_lean(row, project, text, timeout, prefix_end, lane)` sends `op: check` through `lean_session.request` and falls back to `_run_cold`; `warm_session(row, version, commit, slots, lane)` sends `op: warm`; `last_lean_run()`; `measure_version(row)`; `versions(row)`; `workspace(row, version, commit)`.
- `tools/run_pi_budgeted.py`: `start_lean_session(directory, parent_pid)` starts a daemon for the run; `lean_gate` runs only when `_LEAN["process"]` is set; `stop_lean_session()` stops the daemon on every way out of `run()`/`main` and removes a run directory that holds only session files; the `--no-lean-session` flag turns the session off.
- `tools/run_campaign.py`: `Housekeeping`, `reap_run`, `lingering`, `recorded_pids`, `read_session_info`, `ours` read each run's `lean-session.json`. `arena/campaign.py`: `_yield_to_lean_session(directory)` and `lean_session.memory_pressure(directory)` read the marker in the run directory; `init()` ignores `lean_session.SESSION_FILES` in the run directory.
- The Lean load tool: `arena/cli/lean_load.py` (command `arena lean load-test`, moved there by ticket 04; if `grep -rn "start_daemon" arena tools tests` finds it in `tools/lean_load_test.py` instead, use that file). `SimRun.start` starts one daemon per simulated run, `simulate` stops them.
- Tests: `tests/test_lean_session_warm.py` (fast: `FakeLean`, a scripted fake language server patched over `lean_session.LeanServer`, `Base.session(...)`, `Base.request(...)`), `tests/test_lean_session.py` (slow, real Lean: Core row `Core.InitsUpdatesComm`, PhysLib row; `SessionHarness`, `LifecycleTests`, `RunnerSessionTests`).
- `arena lean` group: `arena/cli/` (ticket 04), with `arena lean bench` (ticket 07) and its baseline `benchmark/derived/lean-baseline.json`.

## What to build

- [ ] 1. In `arena/lean_session.py` add `service_dir() -> Path`: env `ARENA_LEAN_SERVICE_DIR` if set, else `$XDG_RUNTIME_DIR/arena-lean-service`, else `/tmp/arena-lean-service-<uid>`. Files in it: `service.sock`, `service.json` (`pid`, `socket`, `code`, `protocol`, `pgids`, `pids`, `started`), `service.log` (the service's stderr, what `_log` writes), `start.lock`, `lean-session.waiting`, and the `lean-session/` folder of per-server logs. Change `socket_path(directory: Path | None = None)` to return `(directory or service_dir()) / "service.sock"`, and raise `SessionError` when the path is longer than `SOCKET_LIMIT`. Delete the long-path fallback and the `lean-session.sock` naming. Set `PROTOCOL = 2`. `Session(directory, budget=None)` takes the service directory.
- [ ] 2. Replace the run-scoped daemon lifecycle with `ensure_service(directory: Path | None = None, wait: float = 15.0) -> str` (returns the socket path). Under an `flock` on `start.lock`: (a) if the socket answers `op: status` with the current `protocol` and `code_sha()`, return it; (b) if it answers with another `code` or `protocol` and its status shows no leases and no holds, send `op: shutdown`, wait up to 20 s for the socket to go, then start a new one; (c) if it answers with another `code` while leases or holds exist, raise `SessionError("the Lean service runs older code with live runs")`; (d) if nothing answers, remove the stale socket and start `python -m arena.lean_session serve --service-dir <dir>` with `start_new_session=True`, stdout and stderr appended to `service.log`, no parent pid, then wait for the socket as `start_daemon` does today. `start_daemon` and `stop_daemon` are deleted; their callers use `ensure_service` (checkboxes 7 to 10).
- [ ] 3. Service ops (all in `Session`, dispatched by `_Handler`): `status` (adds `leases`, `holds`, per-server `workers`, `busy`, `gb`, `pids`), `lease`, `release`, `hold`, `unhold`, `warm`, `check`, `shutdown`. `Session` keeps `leases: dict[str, dict]` (run id to `pid`, `primary`, `others`) and `holds: dict[str, dict]` (owner to `pid`, `projects`) behind a lock, and offers `_referenced(project) -> bool`, `_is_primary(project) -> bool` (a live lease names it as `primary`) and `_is_adhoc(entry) -> bool` (see 4); ticket 08b uses all three. Request and reply shapes:
  - `{"op":"lease","protocol":2,"run_id":str,"pid":int,"primary":str,"others":[str]}` -> `{"ok":true}`. `primary` and `others` are project (workspace) paths as strings. Reject (`ok: false`, reason) when `pid` is not alive.
  - `{"op":"release","protocol":2,"run_id":str}` -> `{"ok":true,"closing":[project,...]}`. Drops the lease.
  - `{"op":"hold","protocol":2,"owner":str,"pid":int,"projects":[str]}` replaces `owner`'s hold list; `{"op":"unhold","owner":str}` removes it. Ticket 09 uses these for rows that are queued next.
  - `{"op":"shutdown","protocol":2}` -> `{"ok":true}`, then the service stops every server and exits.
- [ ] 4. Reference rule: a project is **referenced** while some live lease names it as `primary` or in `others`, or some live hold names it. A lease or hold whose `pid` is gone is dropped by the existing 1-second `watch` loop in `serve` (replace its parent-pid check with this). When a project stops being referenced and none of its slots is busy, close its whole entry (`_stop_entry`) and log `closed: no run or queued row needs it`; if a slot is busy, close it as soon as it is released. This replaces `IDLE_SECONDS` and `BACKGROUND_IDLE_S` for referenced and formerly referenced projects. An entry created by a request for a project nobody references (a request with no lease: tests, `arena eval`) is **ad hoc**: it keeps an idle rule and closes after `ADHOC_IDLE_S = 600` without a request. Delete `IDLE_SECONDS` and `BACKGROUND_IDLE_S` after moving their values to this rule. The service exits when it has had no entries, leases or holds for `SERVICE_LINGER_S = 600` seconds (open question for the owner: the plan gives no exit rule; with no entries the service holds no memory); on exit it removes `service.sock` and `service.json`.
- [ ] 5. Make a shared entry safe for several runs. (a) When an idle model document is chosen for a request in `_acquire`, prefer the idle document whose `_Doc.header` equals the request's header (`text[:header_end]`), then the most recently used one as today. (b) `_guard_prefix` must no longer stop the entry when the prefix of one display name changes: close only the documents whose header belongs to that display (add `_Doc.display`, set in `check` and `warm`), reset `entry.prefixes[display]`, and return the stale reply for that one request as today. The `fingerprint` mismatch rule in `_entry` (workspace changed or crashed) stays: it restarts the entry.
- [ ] 6. Delete the per-run machinery the service replaces: `WorkerBudget.register`, `live_sessions`, `share`, `Session._share`, `_last_share`, `registration`, the `session-*.lock` files, `Session.primary`, `Session.max_slots`, the `parent`/`--parent-pid`/`--run-dir`/`--max-slots` options of `serve` and `main`, `stop_daemon`'s run-directory pid-file logic, `INFO_NAME` and the `lean-session.json` writing. `WorkerBudget.acquire`, `available` and `opening` stay unchanged. Interim worker rules, until ticket 08b: `_may_open` keeps `MAX_SLOTS` model documents and `BACKGROUND_SLOTS` background documents per toolchain and the machine-wide tokens, and loses its share clause; the first model check on a project that is `_is_primary` or ad hoc still calls `_grow` (it used `str(project) == self.primary`); `reap_idle` loses its primary rule (checkbox 4 covers closing). Do not otherwise change `_may_open`, `_acquire` or `_evict_idle`.
- [ ] 7. Runner: in `tools/run_pi_budgeted.py` `start_lean_session(directory, parent_pid)` becomes `start_lean_session(row)` taking the benchmark row: call `lean_session.ensure_service()`, set `os.environ[lean_session.ENV]` to the socket path, then send `lease` with `run_id=args.run_id`, `pid=os.getpid()`, `primary=str(engine.workspace(row, *engine.measure_version(row)))`, `others=` the workspace of every other listed version. `_LEAN` records the socket and run id instead of a process (`lean_gate` runs when a socket is recorded). `stop_lean_session()` sends `release` and does not stop the service. It still removes a run directory that holds nothing the run created (the session files are no longer in it; keep the check for `lean-session.log` and whatever `init()` ignores). Failure to start the service or lease still only costs speed: calls run cold, as now. Keep the printed line `Lean session pid=...; socket=...` (pid of the service). The `--no-lean-session` flag keeps working.
- [ ] 8. CLI: add `arena lean status` (prints the service's `status` as a Rich table, `--json` prints the reply; prints `no service` and exits 0 when none answers), `arena lean stop` (sends `shutdown`; if the socket does not answer within 20 s, kills only the pid recorded in `service.json` after reading `/proc/<pid>/cmdline` and finding `arena.lean_session` in it; never pattern-kill) and `arena lean serve` (runs the service in the foreground). Put them in the existing `arena lean` group in `arena/cli/` (ticket 04); if that group does not exist, stop and report.
- [ ] 9. Campaign side: `memory_pressure(directory)` and `_yield_to_lean_session` in `arena/campaign.py`: the marker now lives in `service_dir()`; `memory_pressure()` takes no directory (update the caller). Leave `SESSION_FILES` and `init()` as they are. In `tools/run_campaign.py`, runs no longer write `lean-session.json` and the service is not a run's child: `reap_run`, `lingering`, `recorded_pids`, `read_session_info`, `ours` must keep working with no such file but can never signal the service; `ours()` already requires the run directory in the command line, keep that.
- [ ] 10. Port the Lean load tool (`arena lean load-test` / `arena lean bench`, whichever file `grep -rn "start_daemon" arena tools tests` shows): `SimRun.start` calls `ensure_service()` once (shared by all simulated runs) and `lease`; `simulate` releases its leases at the end and calls the stop op only when the tool started the service itself (the pid it records). It reports header opens per run from the `service.log` lines `header open`. Ticket 07's bench keeps working: `arena lean bench` must still run on the service.
- [ ] 11. Fast tests in `tests/test_lean_session_warm.py` (use `FakeLean`; patch `_available_gb` as `Base.setUp` does). Delete the tests that describe removed behaviour: `test_two_sessions_split_the_machine_budget_evenly`, `test_three_sessions_get_a_third_and_a_share_is_never_below_two`, `test_a_warm_op_gets_the_share_minus_the_background_reserve`, `test_a_dying_session_frees_its_tokens_and_registration`, `test_a_killed_process_drops_its_registration`, `test_a_shrinking_share_keeps_warm_workers_but_opens_no_more`, `test_an_idle_background_worker_is_closed_after_the_idle_limit` (replace it by the ad hoc idle test below). If another remaining test relied on the share rule or `Session.primary`, adapt it minimally and list it in the hand-back; leave `test_background_never_evicts_a_model_worker_even_with_no_machine_room`, `test_background_is_guaranteed_even_when_model_workers_hold_every_machine_token` and the eviction test as they are (ticket 08b rewrites them). Add (Seam C):
  - close at row end: after `release` of the last lease the entry is closed (`didClose` for every document) unless a `hold` names the project; a project in `others` of a live lease stays open;
  - a hold or lease whose `pid` has exited is dropped by the watch step, and `lease` with a dead pid is refused;
  - the second run of the same row reuses the first run's warm documents: `release`, then a new `lease`, then `check` shows no new `didOpen` and `new_worker` false;
  - a prefix change for one display closes only that display's documents, not another display's in the same entry; an idle document with the matching header is preferred;
  - an ad hoc project (no lease) closes after `ADHOC_IDLE_S` (patch the constant and the clock) and the service-level exit rule: no entries, leases or holds for `SERVICE_LINGER_S` ends the serve loop (patch the constant);
  - `ensure_service` logic with injected process start and status replies: reuse on matching `code`, shutdown-and-restart on a different `code` with no leases, `SessionError` on a different `code` with leases.
- [ ] 12. Update the slow tests in `tests/test_lean_session.py` (`SessionHarness`, `LifecycleTests`, `RunnerSessionTests`) to the service: `SessionHarness.setUpClass` sets `ARENA_LEAN_SERVICE_DIR` to a temp directory, calls `ensure_service`, sends a `lease`, and `tearDownClass` releases and sends `shutdown` (kill by recorded pid only if it does not exit). The lifecycle tests become: stopping the service stops its Lean processes; a killed runner's lease is dropped within 5 s and the Lean processes of its project are gone (use `wait_until`); `arena lean stop` leaves no `service.sock`. `RunnerSessionTests` stop reading `lean-session.json` from the run directory (it no longer exists): they read the service's pids from `service.json` and the run id from the lease. Keep every session-equals-cold test unchanged. Replace the pattern kill in `LifecycleTests` (`subprocess.run(["pkill", "-9", "-f", run.run_id])`, which breaks the kill-by-PID rule and can hit unrelated processes) with killing the recorded PIDs of the runner and its Pi child (for example from the runner's `Popen` and the run directory's pid file), then `wait_until` they are gone. Add one slow test: two sequential leases of the Core row, the second one's first compile has `new_worker` false and `header_seconds` None.
- [ ] 13. Speed gate, run **once, at the end** (owner decision 4): `uv run arena lean bench --compare benchmark/derived/lean-baseline.json` (other flags as ticket 07 recorded the baseline with; `--help`), against the service. A figure fails only if it exceeds BOTH the relative tolerance (+10% p50, +20% p95) AND the 0.25 s absolute noise floor; the command already applies this. Also run two leases back to back on one row and show in the hand-back that the second opens no header (`service.log`). Paste the table in the hand-back. If a figure fails, stop and report; do not loosen the tolerance or the floor.

## Do NOT
- Do not change `WorkerBudget.acquire`, `available` or `opening`, `RESERVE_GB`, `OPEN_TIMEOUT`, the header-first open, the `warm_kept` timeout behaviour, `render`, `fingerprint`, `reorder_lean_path`, `NO_LAKE` or any LSP message handling.
- Do not add lanes by name, the new memory constants, memory logging, `wait: false` warm, goals or snippets, or the gate change (ticket 08b), and do not change `_evict_idle` (ticket 08b deletes it).
- Do not touch `engine.run_lean`'s fallback logic (`cold`, `cold-fallback`), `_run_cold`, `compile_version` or the heartbeat wrapper. The cold lane stays as it is.
- Do not add the REPL pool (ticket 08d) or the campaign pre-warm and lock (ticket 09). `hold` and `unhold` exist here only because ticket 09 calls them; do not call them from anywhere but tests.
- Do not change `packages/arena-pi/` (the MCP server is removed in ticket 15b) or `models.yaml`.
- No model-facing text is added.
- Do not weaken a session-equals-cold test, and do not replace real-Lean slow tests by fakes.
- Never run two Lean-heavy commands at once: the slow tests, `arena lean bench` and any manual Lean run go one after another, and no `lake build` or `arena provision` while one runs. The machine has 8 cores and 30 GB; the baseline was recorded on an idle machine.
- Kill processes by PID only (the service pid from `service.json`); never `pkill`, `killall` or `pgrep -f | kill`. Do not leave a service running when you finish: run `uv run arena lean stop` and confirm `uv run arena lean status` says no service.

## Acceptance
- Two runs of the same row started one after the other (the first one finished) share warm workers: the second run's first compile reports `new_worker: false` and no `header open` line appears in `service.log` for it.
- `uv run arena lean status` shows leases, holds and per-project workers.
- After the last run of a row ends and nothing holds it, its Lean processes are gone within a few seconds; `arena lean stop` removes every trace.
- A prefix change for one file closes only that file's documents.
- A runner, a campaign and the load tool all work with no per-run daemon; nothing in the repo calls `start_daemon` or `stop_daemon`.
- The ticket-07 speed gate passes.

## Verify
TEST BUDGET: targeted files, then the fast suite once, then one slow file, then the gate once.
- `uv run pytest -q -p no:cacheprovider tests/test_lean_session_warm.py tests/test_lean_health.py` -> all pass (baseline count minus the deleted tests plus the new ones).
- `uv run ruff check arena tools tests && uv run ruff format --check arena tools tests` -> clean for the files you touched.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_lean_session.py` -> all pass, one test at a time (needs `workspaces/strata-v4.29.1`; PhysLib tests skip when it is absent).
- `uv run arena lean bench --compare benchmark/derived/lean-baseline.json` (checkbox 13) -> exit 0.
- `uv run pytest -q -p no:cacheprovider` (fast suite, once, at the end) -> all pass.
- `cd packages/arena-pi && npm test` -> all pass (unchanged).
- `uv run arena lean stop && uv run arena lean status` -> "no service".
Known pre-existing slow failures (also fail on tag v6; do not fix): `tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas` and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`; `LeanMcpTests` is flaky. Neither is run by this ticket.

## Stop and report if
- `arena lean` (ticket 04) or `arena lean bench` and its saved baseline (ticket 07) do not exist.
- The speed gate fails on any row or figure after checkbox 13.
- A slow test that passed before your change fails and the cause is not in code you wrote.
- Another process (a campaign, a run, another service) is using the machine's Lean while you need the idle machine for the gate.
- Deleting `Session.primary` or `max_slots` breaks a caller outside the files named here.

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

Your branch is **`v7/08a-lean-service`**, already created and stacked directly above `v7/07-lean-gate`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/08a-lean-service` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/08a-lean-service -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-08a`.
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
- [ ] Every change is committed on `v7/08a-lean-service`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-08a
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
