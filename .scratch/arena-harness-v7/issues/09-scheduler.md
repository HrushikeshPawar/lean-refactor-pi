# 09: Campaign scheduler

**What to build:** `arena campaign` orders its runs by workspace and toolchain set, then row, then replicate, so replicates of one row run back to back against warm Lean workers. During the last 10-15 minutes of a row it pre-warms the next row's headers in the shared Lean service, one header at a time. A lock stops two campaigns from overlapping, and `arena provision` refuses while a campaign holds it. `campaign.json` records the settings the campaign ran with (jobs, memory and load limits) and what it observed (minimum free memory, maximum load, overlapping runs).

**Blocked by:** 08c: Lean service callers, tests, speed gate (all lower tickets, 08d included, are committed below your branch).

**Status:** needs-review

**Branch:** `v7/09-scheduler` (stacked on `v7/08d-repl-pool`)

**Read first:** SPEC "Campaign scheduler" (Modules), user stories 18 and 20; PLAN §9d (scheduling around warm caches), §7.1 (`arena campaign`, `arena provision` rows), §12b (#21), §12d (#40); ISSUES #21 and #40 text in `docs/ISSUES-harness-v7.md`; decision D35.

## Context: where things are now
- The campaign command is `tools/run_campaign.py` (`main`, `plan`, `execute`, `Housekeeping`, `aggregate`, `render`), reached as `arena campaign` (`arena/cli/__init__.py`, pass-through). Ticket 04 may have moved it into `arena/cli/`: run `grep -rn "def plan" arena tools` and use that file wherever "the campaign command module" is named below.
- `plan(prefix, rows, models, replicates)` is replicate-major: `for k in replicates: for row in rows: for model in models`. Specs are `{row, model, replicate, run_id}`. `main` runs them with `ThreadPoolExecutor(max_workers=args.jobs)` and `pool.map`, so specs start in plan order.
- `Housekeeping` (`before_run`, `after_run`) waits before each run until finished runs' Lean processes are gone and, when nothing else runs, `MemAvailable >= --min-free-gb`; `mem_available_gb()` reads `/proc/meminfo`. Since ticket 08a the Lean service keeps workers resident across runs, so that memory test must add the service's resident memory (ticket 08c added `service_gb_fn`; reuse it).
- `main` writes `campaign.json` and `campaign.txt` only at the end (`aggregate`, `lean_unhealthy_rows`); it records neither `--jobs` nor memory nor load nor overlap. There is no lock: two campaigns can run at once (ISSUES #40).
- `arena provision` (ticket 04 merged `tools/provision_workspace.py` and `tools/provision_progress.py` into the CLI; find it with `grep -rn "provision" arena/cli`) does not know about campaigns (ISSUES #21: "No builds during a campaign" is only a convention).
- Lean service client (tickets 08a to 08c, `arena/lean_session.py`): `ensure_service()`, `request()`, ops `hold` and `unhold` (08a), `warm` with `"wait": false` (08b), `status`. A `model` request for a project that a `hold` names, and that no live lease names as primary, is served on the model lane (08b), which is what the pre-warm of the next row's primary relies on. `arena/engine.py`: `warm_session(row, version, commit, slots, lane="model", wait=True)`, `measure_version(row)`, `versions(row)`, `workspace(row, version, commit)`, `problem(name)`.
- `tests/test_campaign.py` has `test_replicates_are_sequential_and_ids_distinct`, `test_sequential_execution_order` and `test_aggregation_over_replicates`, which call `rc.plan("p", ["A", "B"], ["deepseek-v4.1-flash"], 2)` with fake row names; the first one asserts replicate-major order and will change.

## What to build

- [ ] 1. New module `arena/scheduler.py` holding all new logic as plain, injectable functions and classes (so the campaign command module only wires them). No `/proc`, clock or socket access except through arguments with real defaults.
- [ ] 2. Ordering: `plan_order(rows: list[str], group_of: Callable[[str], object]) -> list[str]` returns the rows grouped by `group_of(row)` (groups in order of first appearance, rows keep their given order inside a group). `row_group(row: dict) -> tuple` is the real group key: `(row["source"], tuple(version names in the row's listed order))`. In the campaign command module change `plan(prefix, rows, models, replicates, group_of=None)`: with `group_of=None` the rows keep their given order; the specs are generated as `for row in ordered_rows: for k in replicates: for model in models` (row-major, replicate before model so that models stay balanced within a row; plan §9d "group, then row, then replicate"). `main` passes `group_of=lambda name: scheduler.row_group(engine.problem(name))`. Run IDs, validation and error messages stay as they are. Update the three tests named above to the new order and add one test that `plan_order` groups interleaved rows of two sources (`[A1, B1, A2]` -> `[A1, A2, B1]`).
- [ ] 3. Lock: in `arena/scheduler.py` add `LOCK_PATH = ROOT / "runs" / "campaign.lock"`, `class CampaignLocked(RuntimeError)`, `class CampaignLock(path=LOCK_PATH)` with `acquire(info: dict)` (open the file, `fcntl.flock(LOCK_EX | LOCK_NB)`; on failure raise `CampaignLocked` whose message names the holder's `pid`, `prefix` and `started`, read from the file; on success write `info` as one JSON line: `pid`, `prefix`, `started` (ISO time), `argv`), `release()`, context-manager use, and `holder(path=LOCK_PATH) -> dict | None` (the recorded info if the lock is currently held by a live process, found by trying the same non-blocking flock and releasing it at once; `None` when free or the file is missing or stale). A crashed holder frees the lock by itself (flock). Create `runs/` if missing.
- [ ] 4. `arena campaign` takes the lock right after argument validation and before the first step that spends money or uses Lean (packet checks, preflight, the first run), keeps it until the process ends, and on `CampaignLocked` prints the message to stderr and exits 1 without touching anything. `--dry-run` never takes the lock. If the command has a `--check` mode (ticket 04 or 06), it takes the lock too. `arena run` does not take it.
- [ ] 5. `arena provision` refuses while a campaign holds the lock: at the start of the command (after argument parsing, before any clone, fetch or build; `--dry-run` skips the check), `holder()` not `None` -> print `a campaign (pid N, prefix P, started T) holds the lock; provisioning is refused` to stderr and exit 1. `--dry-run` only prints the plan and is allowed.
- [ ] 6. Recorded settings (ISSUES #40): the campaign command writes `campaign.json` at the start, before the first run, with `{"settings": {"prefix", "rows", "models", "replicates", "jobs", "limit_usd", "thinking", "min_free_gb", "cleanup_wait_s", "prewarm_minutes", "order": [run_id, ...], "started", "cpu_count", "mem_total_gb", "lock": <the lock info>}}`, and rewrites it at the end with the existing report keys plus an `observed` block. A campaign that dies still leaves its settings.
- [ ] 7. Observed resources: `class ResourceSampler(interval=30.0, *, mem_fn, load_fn, swap_fn, disk_fn, now_fn)` in `arena/scheduler.py`, a thread started with the campaign (defaults read `/proc/meminfo` MemAvailable, `/proc/loadavg` 1-minute load, swap used from `/proc/meminfo`, free disk of `ROOT` through `shutil.disk_usage`). It keeps `min_mem_available_gb`, `max_load1`, `max_swap_used_gb`, `min_disk_free_gb`, `samples`. `execute` increments and decrements a counter under a lock so `max_concurrent_runs` is known. At the end `observed` = `{"min_mem_available_gb", "max_load1", "max_swap_used_gb", "min_disk_free_gb", "max_concurrent_runs", "samples"}`. Do not hold new runs on swap or disk thresholds (open question for the owner; ISSUES #21 asks for it, this ticket only records).
- [ ] 8. Holds: while the campaign runs it keeps the Lean service from closing toolchains a queued row still needs. `scheduler.row_projects(row) -> list[Path]` returns the workspace path of every version a row lists (`engine.workspace`; a version that is not provisioned is skipped). `HoldKeeper(owner, pid, request_fn)` sends `hold` with the union of `row_projects` over every row that still has an unfinished spec (queued or running), at campaign start and again whenever a row's last spec finishes, and `unhold` at the end (in a `finally`). If the service is unreachable it logs once and carries on (cold fallback is already the rule).
- [ ] 9. Pre-warm. `class Prewarm` in `arena/scheduler.py`, constructed with the ordered row list, the number of specs per row, `lead_s` (default `PREWARM_LEAD_S = 720`, that is 12 minutes, inside the plan's 10-15), `now_fn`, and `warm_fn(row_name) -> None`. The campaign calls `started(spec)` when a run starts and `finished(spec, seconds)` when it ends. `due(now) -> str | None` returns the next row's name when all of these hold, once per row: (a) every spec of the current row (the row of the earliest unfinished spec) has started; (b) an estimate E exists: the median wall time of finished runs of that row, else of finished runs of earlier rows, else none (with no estimate nothing is pre-warmed and a log line says so); (c) for the longest-running unfinished run of the current row, `E - elapsed <= lead_s`. There is a next row, and it is not in the same group with all its toolchains already resident (the service skips resident ones anyway, so just call `warm_fn`). A background thread started with the campaign polls `due` every 30 s and calls `warm_fn`.
- [ ] 10. The real `warm_fn` pre-warms serially, because only one header may load at a time: for the next row, `engine.warm_session(row, measure_version_name, commit, slots=1, lane="model")` (waits for the primary header), then for each other listed version `engine.warm_session(row, version, commit, 1, lane="background", wait=False)`. A refusal (`no room for a Lean worker`) is logged and ignored. It sends no `lease`: the hold from checkbox 8 keeps those toolchains open until the row starts. Add `--prewarm-minutes N` (default 12; `0` turns pre-warming off) to `arena campaign`; `lead_s = 60 * N`.
- [ ] 11. Wire it into the campaign command module: `execute` calls `prewarm.started/finished` and the sampler counters; `main` builds `Prewarm`, `HoldKeeper`, `ResourceSampler`, writes `campaign.json` as in checkbox 6, runs the specs with `ThreadPoolExecutor(max_workers=args.jobs)` in the new order, stops the helper threads in a `finally`, and releases the lock last. `Housekeeping` is not rewritten; only its memory wait uses `service_gb_fn` (08c), and `--min-free-gb` stays.
- [ ] 12. Tests, fast, in a new `tests/test_scheduler.py` (injected clocks, readers and sockets; no `/proc`, no Lean, no model; Seam A style for the protocol around a campaign, Seam C style for the service calls):
  - `plan_order` grouping and the row-major spec order for 2 sources, 3 rows, 2 models, 2 replicates (replicate before model inside a row);
  - the lock: a second `CampaignLock.acquire` in another process (use `subprocess` with `sys.executable -I -c`, no Lean) raises `CampaignLocked` naming the first holder's pid and prefix; after the holder exits, `acquire` works and `holder()` is `None`;
  - `arena provision` refuses while the lock is held (run the CLI function with the lock held in-process through a temp `LOCK_PATH` patched in; assert exit code 1 and that no provisioning function was called, using an injected one) and runs again after release;
  - `Prewarm.due`: not due while a spec of the row has not started; not due with no estimate; due exactly when `E - elapsed <= lead_s`, once; the estimate falls back to earlier rows; no next row means never due;
  - `HoldKeeper` sends the union of unfinished rows' projects and narrows it when a row finishes, and sends `unhold` at the end;
  - `ResourceSampler` with fake readers records min memory, max load, max swap, min disk, and the concurrency counter's maximum;
  - `campaign.json` after a dry-run-free fake campaign (fake `run_fn`, as `test_sequential_execution_order` does) has `settings` before the first run and `observed` after the last.
- [ ] 13. One slow test (`@slow`, new file `tests/test_scheduler_slow.py`): with the real service and the Core row, call `engine.warm_session(...)` for the primary as the pre-warm does, then take a `lease` for the row and compile once: the compile has `new_worker` false and `header_seconds` None. Skip when `workspaces/strata-v4.29.1` is missing.

## Do NOT
- Do not change how a single run starts, runs or ends (`arena run`), the Lean service, the lanes, the REPL pool or the speed gate. This ticket only calls the service's existing ops (`hold`, `unhold`, `warm`, `status`).
- Do not start Lean heavy work from the scheduler except the serial pre-warm of checkbox 10, and never more than one header open at a time.
- Do not add swap or disk thresholds that hold or abort runs.
- Do not change run IDs, `--limit-usd` handling, preflight, packet checks, `aggregate` keys or `render` text (only add to `campaign.json`).
- Do not put the lock under a run directory; it is machine-wide at `runs/campaign.lock`.
- Do not edit `runs/analysis/v6cov/rerun-em.sh` (untracked, outside the repo's tracked files); mention it in the hand-back.
- No model-facing text.
- Never run two Lean-heavy commands at once. Kill processes by PID only; never `pkill`, `killall` or `pgrep -f | kill`. Do not run a real campaign (no model spend): use `--dry-run`, fakes and the single slow test. Leave no service running: finish with `uv run arena lean stop`.

## Acceptance
- `uv run arena campaign --dry-run --prefix t --rows <3 rows of two sources interleaved> --models deepseek-v4.1-flash --replicates 2` prints the runs grouped by source, each row's replicates adjacent.
- A second `arena campaign` (without `--dry-run`) started while the first holds the lock exits 1 naming the first's pid and prefix; after the first ends it starts normally.
- `arena provision` exits 1 with the holder named while a campaign runs and works again afterwards.
- `campaign.json` contains `settings` as soon as the campaign starts and `observed` at the end.
- With a fake clock, the pre-warm fires once per row, within the last `lead_s` of the estimated row time, and the service receives the next row's header warm-ups serially.

## Verify
- `uv run pytest -q -p no:cacheprovider tests/test_scheduler.py tests/test_campaign.py` -> all pass (the three updated campaign tests pass in the new order).
- `uv run pytest -q -p no:cacheprovider` (fast suite, once, at the end) -> all pass (baseline count plus the new tests).
- `cd packages/arena-pi && npm test` -> all pass (unchanged).
- `uv run ruff check arena tools tests && uv run ruff format --check arena tools tests` -> clean for the files you touched.
- `uv run arena campaign --dry-run --prefix t --rows <row1>,<row2>,<row3> --models deepseek-v4.1-flash --replicates 2` -> run order as in Acceptance, exit 0, no lock file left holding a process.
- `uv run arena provision --row <any row> --dry-run` -> plan printed, exit 0.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_scheduler_slow.py` -> passes, one Lean process at a time (the only slow file this ticket needs; the speed gate is not run here because the Lean service is unchanged).
- Known pre-existing slow failures (also fail on tag v6; do not fix): `tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas` and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`; `LeanMcpTests` is flaky.

## Stop and report if
- `arena provision` (ticket 04) or the ops `hold`, `unhold` (08a), `warm` with `"wait": false` (08b) or `service_gb_fn` (08c) do not exist as described.
- The campaign command module cannot be found with `grep -rn "def plan" arena tools`, or it no longer has `Housekeeping`/`execute`.
- Taking the lock would require changing `arena run` or a Pi extension.
- A dry run reaches the network, Lean, or a model (it must not).
- The pre-warm would have to open more than one header at a time to be useful (report the figures instead).

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

Your branch is **`v7/09-scheduler`**, already created and stacked directly above `v7/08d-repl-pool`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/09-scheduler` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/09-scheduler -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-09`.
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
- [ ] Every change is committed on `v7/09-scheduler`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-09
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
