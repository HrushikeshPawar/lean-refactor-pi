# 07: Lean speed baseline (+ArkLib, PSS) and gate

**What to build:** `arena lean bench` measures Lean speed per benchmark row and toolchain: header open (first and
repeat), warm compile p50/p95 for the standard check mix (sorry probe, reference proof, small edit, error draft),
splice-edit time for a late against an early step, and the memory (PSS) of every Lean worker. A baseline recorded
with it (the v6 rows plus an ArkLib row with all four of its toolchains) is committed as a versioned file. `arena lean
bench --compare` and a `slow` gate test fail when a measured figure is slower than the baseline by more than +10% (p50 figures) or +20% (p95 figures) **and**
by more than the 0.25 s noise floor, and say which figure, on which toolchain, by how much. The gate is run once, at the
end, by every ticket that touches Lean machinery: 08a, 08b, 08c, 08d, 10b and 12. It is never part of the fast suite.

**Blocked by:** 04: Move the remaining tools into the CLI (the load test and the `arena lean` sub-app live in `arena/cli/` after it); 06: Run-control fixes (the measure version it changes is why the bench names its toolchain explicitly).

**Status:** done

**Branch:** `v7/07-lean-gate` (stacked on `v7/06-run-fixes`)

**Read first:** spec "Operator: Lean speed and resources" (stories 31-35) and "Speed baseline and gate",
"Testing Decisions" (seam C last bullet, isolation); plan §9b (Today, Measured, Recorded v6 speed baseline,
"Benchmark first" items 1, 2, 4), §9c only for context, D35; `research/v7-probes/lean-bench/` (the three v6 raw results:
`<row>.json/report.md`, `raw.jsonl`).

## Context: where things are now

- `arena/cli/lean_load.py` (moved from `tools/lean_load_test.py` by ticket 04; command `arena lean load-test`):
  - pure parts: `percentile()`, `parse_weights()`, `make_proof(kind, row, serial, timeout)` with kinds
    `sorry`, `reference`, `edit` (trailing comment), `error`, `slow`; `summarise()`, `evaluate()`, `render_report()`;
  - `SimRun`: one simulated run with its own session daemon (`start()` calls `lean_session.start_daemon`,
    `warm()` sends the `warm` op, `check(kind, lane, version, proof)` sends one check through
    `lean_session.request` and records seconds, `new_worker`, `header_seconds`, `changed_from_line`; `payload()` builds
    the request with `engine.candidate_file`). `SimRun.primary` is set from `engine.measure_version(row)` in its
    constructor. After ticket 06 that is the **newest** listed toolchain (differs from the first listed only for
    the three Putnam rows), but the v6 baseline was taken on the first listed toolchain.
  - `Sampler`: samples `MemAvailable`, Lean process counts and the daemon's `status` reply every 5 s;
    `find_orphans()`; `simulate()` runs the whole load test; `Recorder` writes `raw.jsonl`.
- `arena/lean_session.py`: the per-run daemon. `status` op replies per server `project`, `workers`, `busy`, `gb`
  (`tree_pss_gb` of the server's process tree), `pgid`, `pids` (`process_tree(pgid)`); `tree_pss_gb(root)` sums
  `Pss` from `/proc/<pid>/smaps_rollup`; `process_tree(root)`; `start_daemon`, `stop_daemon`, `request`, `socket_path`,
  `OPEN_TIMEOUT`, `MAX_SLOTS`. Per-worker memory is not logged anywhere today (plan §9b "Measured").
- The recorded v6 baseline (spec "Speed baseline and gate"): three rows, one run, model lane only, 8 checks per row,
  idle machine, first listed toolchain: Core.InitsUpdatesComm (Strata v4.29.1) warm-up 8.2 s, edit p50/p95 0.5/0.5 s,
  reference 0.3/0.5, sorry 0.3, error 0.3; putnam_1964_b2 (Mathlib v4.25.0) 30.8 s, 12.2/13.5, 2.3/11.7, 0.2, 0.2;
  Cslib.SKI.parallelReduction_diamond (CSLib v4.33.0-rc2) 5.6 s, 0.2/0.3, 0.2/0.2, 0.2, 0.2. Raw results are under
  `research/v7-probes/lean-bench/` (tracked in git).
- Rows and toolchains (`benchmark/original/warmup.jsonl` `version_info`): Core.InitsUpdatesComm v4.29.1, v4.27.0,
  v4.26.0; putnam_1964_b2 v4.25.0, v4.26.0; Cslib.SKI.parallelReduction_diamond v4.33.0-rc2, v4.32.0, v4.31.0, v4.30.0;
  `Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius` (the ArkLib row) v4.31.0, v4.30.0,
  v4.29.0, v4.28.0. Workspaces are provisioned under `workspaces/` (`arklib-v4.28.0` ... `arklib-v4.31.0`,
  `strata-*`, `putnambench-*`, `cslib-*`).
- `benchmark/derived/` holds `workspaces.tsv`; `benchmark/` is tracked (research data in `runs/` is gitignored).
- `tests/slow.py` has the `slow` decorator; `tests/test_lean_load_test.py` tests the pure parts of the load test.

## What to build

Real Lean is needed to record the baseline (item 8). It is free. **Run one Lean-heavy command at a time**, never two
benchmark or Lean-test commands in parallel, and keep the machine otherwise idle while recording.

- [ ] 1. **Per-worker PSS helper.** In `arena/lean_session.py` add `pid_pss_gb(pid) -> float | None` (reads that
  process's `smaps_rollup` `Pss`, `None` when unreadable) and make `tree_pss_gb` use it. Behaviour unchanged. No test
  reads `/proc`: the helper is passed in where tests need it (item 2).
- [ ] 2. **Bench core, pure parts** in a new `arena/cli/lean_bench.py` (the command is item 6):
  - `make_splice(row, where, serial)` where `where` is `"early"` or `"late"`: returns the reference proof (statement
    included, as `make_proof` returns it) with one comment line `  -- bench splice <where> <serial>` inserted after the
    first (early) or last (late) line of the proof body (the lines after the statement). A one-line proof returns
    `None` (the figure is then `null`). The result still starts with the statement.
  - `plan_checks(repeats)`: the sequence of `(kind, recorded)` for one measurement, deterministic, no randomness:
    for each repeat `sorry, reference, edit, error, reference (reset, not recorded), splice_late, reference (reset, not
    recorded), splice_early`. Reset checks put the open document back to the reference so each splice is a diff against it.
  - `summarise_checks(records)`: per kind `{n, p50, p95, max, timeouts}` using `lean_load.percentile`; a timed-out
    check is counted in `timeouts` and excluded from the percentiles.
  - `summarise_pss(samples)`: from samples of `{pid: pss_gb}` taken while the daemon runs plus the set of worker pids,
    return `{workers_idle_gb: [per worker, the first sample after warm-up], worker_peak_gb: max over all workers and
    samples}`.
  - `compare(baseline, current, tolerance_p50=0.10, tolerance_p95=0.20, floor_s=0.25)` -> list of
    `Regression(row, toolchain, figure, baseline, current, ratio, limit)`. Figures and classes: **p50 class (+10%)**:
    each kind's `p50` and `splice_early` and `splice_late` p50; **p95 class (+20%)**: each kind's `p95`, `open_cold_s`,
    `open_warm_s`. A figure regresses when `current > baseline * (1 + tolerance)` **and** `current - baseline > floor_s`
    (the noise floor, owner decision 4: a figure fails only if it exceeds BOTH the relative tolerance AND 0.25 s
    absolute, so 0.2 s against 0.3 s does not fail the gate; keep it as the named constant `NOISE_FLOOR_S = 0.25`
    and the default of `floor_s`). PSS is reported but never gated. A figure missing
    from `current` is a regression named `missing`; rows or toolchains only in the baseline are skipped when the run
    did not ask for them; a row asked for but absent from the baseline raises `ValueError`.
  - `format_report(regressions)`: one line per regression, `row | toolchain | figure | baseline -> now | +NN% (limit +MM%)`.
- [ ] 3. **Bench runner (real Lean).** In the same module, `measure(rows, versions, repeats, timeout, out_dir)`
  returns the result structure of item 4. For each `(row, toolchain)`:
  1. **First open** (`open_cold_s`): start a fresh daemon with `SimRun` (reuse it; build it with a minimal config
     `{"max_checks": None, "timeout": timeout, "weights": {}, "slots": 1, "background": 0, "think": 0}` and a
     `Recorder`), set `run.primary = (toolchain, commit)` explicitly (do **not** rely on `measure_version`), call
     `run.warm()` and take `warm_seconds`. State in the report that the page cache is not dropped (that needs root):
     "cold" means the first open of this invocation.
  2. Stop that daemon (`lean_session.stop_daemon`), start a second fresh one and warm it again: `open_warm_s`, the
     repeat open with a hot page cache.
  3. On the second daemon, run `plan_checks(repeats)` sequentially through `run.check(kind, "model", toolchain, proof)`
     with proofs from `lean_load.make_proof` / `make_splice`, record each with seconds, `ok`, `timed_out`,
     `changed_from_line`.
  4. While the second daemon runs, sample every 2 s: the daemon's `status`, `MemAvailable`, and for each Lean worker
     process the PSS (`lean_session.pid_pss_gb`). A **worker** is a process of the server's tree whose
     `/proc/<pid>/cmdline` contains `--worker`. If that finds no worker on a real run, stop and report.
  5. Stop the daemon, kill any recorded orphan Lean process **by PID** (reuse `lean_load.find_orphans`), and fail the
     row if any orphan remained or any non-`slow` check timed out.
  Raw records go to `<out>/raw.jsonl`; nothing in `runs/` is committed.
- [ ] 4. **Baseline file.** Result structure and file `benchmark/derived/lean-baseline.json`:
  `{"schema": 1, "label": "v6", "recorded": "<date>", "code": <arena.provenance.code_version()>, "machine": {"cpus":
  <int>, "mem_total_gb": <float>}, "settings": {"repeats": N, "timeout": T}, "rows": {"<row>": {"<toolchain>": {"commit",
  "open_cold_s", "open_warm_s", "checks": {"sorry": {...}, "reference": {...}, "edit": {...}, "error": {...},
  "splice_early": {...} | null, "splice_late": {...} | null}, "pss_gb": {"workers_idle_gb": [...], "worker_peak_gb": x},
  "min_available_gb": x}}}}`. `load_baseline(path)` validates `schema == 1` and the shape and raises `ValueError`
  naming the problem. The comparison refuses to run when `settings.repeats` differs between baseline and current run.
- [ ] 5. **Gate behaviour in the command** (item 6): `--compare PATH` runs the measurement, calls `compare`, prints the
  report, exits 1 on any regression and 0 otherwise.
- [ ] 6. **`arena lean bench`** in `arena/cli/lean.py` (the sub-app of ticket 04), a real Cyclopts command with typed
  flags: `--rows NAME [NAME...]` (default: the four baseline rows), `--versions first|all|v4.x.y,...` (default `first`:
  the first listed toolchain; `all` every listed one), `--repeats N` (default 5), `--timeout S` (default 180, the
  production check limit), `--out DIR` (default `runs/analysis/bench/<timestamp>`), `--record PATH` (write a baseline
  file; refuses to overwrite an existing file unless `--force`; prints a table of old against new figures when it
  exists), `--compare PATH`, `--tolerance-p50` (0.10), `--tolerance-p95` (0.20), `--json`. A Rich table per row and
  toolchain shows: first and repeat open, per kind p50/p95, splice early and late, PSS idle and peak, min free memory;
  `--json` prints the result structure. A row needs its workspace: a missing one is a clear error naming the
  workspace directory, exit 2.
- [ ] 7. **Fast tests** (`tests/test_lean_bench.py`, pure, seam C): `make_splice` keeps the statement, inserts exactly
  one comment line at the first and at the last proof line, returns `None` for a one-line proof, and early differs
  from late; `plan_checks` is deterministic and its recorded kinds appear `repeats` times each; `summarise_checks`
  excludes timeouts from percentiles; `summarise_pss`; `compare`: equal passes, +9% p50 passes, +11% p50 fails, +19%
  p95 passes, +21% p95 fails, an improvement passes, a figure over the relative tolerance but under 0.25 s absolute passes, a figure over 0.25 s but under the relative
  tolerance passes, a figure over both fails, a missing figure fails
  with `missing`, a row absent from the baseline raises, differing `repeats` is refused; `format_report` names row,
  toolchain, figure and sizes; `load_baseline` accepts the committed file and rejects a wrong schema. Inject all
  machine readings; nothing reads `/proc` or a live session.
- [ ] 8. **Record the baseline.** On an idle machine (check `free -g` and no Lean/Pi/campaign process of yours is running),
  run, one command at a time: `uv run arena lean bench --rows Core.InitsUpdatesComm putnam_1964_b2
  Cslib.SKI.parallelReduction_diamond --versions first --record <scratch>/a.json --out <scratch>/a`, then
  `uv run arena lean bench --rows Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius --versions all
  --record <scratch>/b.json --out <scratch>/b` (this one opens ArkLib four times, twice each: expect tens of minutes).
  Merge the two outputs into `benchmark/derived/lean-baseline.json` with `label: "v6"` (a few lines of Python in the
  shell; no committed script). Put in your hand-back a table of the new figures against the v6 table in the spec
  (open, edit, reference, sorry, error per row) and say whether each is within noise (+/-20%). If any v6 row is more than
  +50% slower than the spec's figure, **stop and report** before committing (the machine may be loaded).
- [ ] 9. **Gate test** (`tests/test_lean_speed_gate.py`, `@slow`, real Lean, one process at a time): load the committed
  baseline, run `lean_bench.measure` in-process for the rows named in `ARENA_GATE_ROWS` (comma list; default every
  baseline row whose workspaces are provisioned; skip with a message if none) with the baseline's `repeats`, and
  `assertEqual(compare(baseline, current), [], format_report(...))`. The failure message is the report, so a regression
  names figure, toolchain and size.
- [ ] 10. **Re-run for stability.** Run `uv run arena lean bench --compare benchmark/derived/lean-baseline.json` for the
  three v6 rows once more and show that it exits 0. If it exits 1 on figures you just recorded, the noise is larger than
  the tolerances: stop and report with both result sets.
- [ ] 11. Update `tests/test_lean_load_test.py` only if the move in item 1-6 changed an import; the load test stays
  (`arena lean load-test` is not replaced).
- [ ] 12. **Who runs the gate.** In the `arena lean bench --help` text and in the docstring of
  `tests/test_lean_speed_gate.py`, state: "Run once at the end of every ticket that touches Lean machinery: 08a, 08b,
  08c, 08d, 10b, 12. Never in the fast suite." (Operator text only.)

## Do NOT

- Do not run two Lean-heavy commands at the same time. Do not run a paid model or Pi: the bench uses no model.
- Do not change how the session daemon works (`lean_session` aside from the PSS helper): this ticket measures
  the machinery, tickets 08a-08d change it.
- Do not use `engine.measure_version` for the bench's toolchain; the toolchain is the explicit loop variable.
- Do not add REPL, pickle or LSP-against-cold comparisons (plan §9b "Benchmark first" items 3 and 5: tickets 08b and 08d),
  parallel-open timing, or salvage-burst timing (no salvage exists yet).
- Do not gate PSS, and do not change the tolerances (+10% p50, +20% p95) or the 0.25 s noise floor (owner decision 4).
- Do not commit anything under `runs/`; commit only `benchmark/derived/lean-baseline.json`.
- Do not edit the spec's baseline table or `research/v7-probes/lean-bench/`; put proposed doc changes in the hand-back.
- Do not kill processes by name or pattern; PIDs only.
- Model-facing text: none here (the bench prints operator text only).

## Acceptance

- `arena lean bench --rows Core.InitsUpdatesComm --versions first --repeats 2` prints a table with first and repeat
  header open, p50/p95 for sorry, reference, edit, error, splice early and late, and worker PSS, and leaves no Lean
  process behind.
- `benchmark/derived/lean-baseline.json` is committed, `label` is `v6`, and it holds the four baseline rows (ArkLib with
  all four toolchains) with PSS per worker.
- `arena lean bench --compare benchmark/derived/lean-baseline.json` exits 0 on this code and exits 1 with a report
  naming row, toolchain, figure and size when a figure in the baseline file is edited to be 30% faster than reality.
- The gate test passes on this code under `ARENA_SLOW_TESTS=1` and fails with the report when the baseline is made
  stricter.

## Verify

- `uv sync` -> ok.
- `uv run pytest -q -p no:cacheprovider tests/test_lean_bench.py tests/test_lean_load_test.py tests/test_lean_session.py`
  -> all pass (targeted files first).
- Then the fast suite, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count + `test_lean_bench.py`).
- `cd packages/arena-pi && npm test` -> all pass (unchanged count).
- `uv run ruff check <touched files> && uv run ruff format --check <touched files>` -> clean;
  `uv run ty check arena/cli/lean_bench.py arena/lean_session.py` -> no new diagnostics.
- `uv run arena lean bench --help` -> lists the flags of item 6.
- `uv run arena lean bench --rows Core.InitsUpdatesComm --versions first --repeats 2 --out <scratch>/smoke` -> table, exit 0.
- `uv run arena lean bench --rows Core.InitsUpdatesComm putnam_1964_b2 Cslib.SKI.parallelReduction_diamond --versions first --compare benchmark/derived/lean-baseline.json` -> `0 regressions`, exit 0 (note the times).
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_lean_speed_gate.py` -> passes (one slow command at a time;
  with all four rows this takes a long time: use `ARENA_GATE_ROWS=Core.InitsUpdatesComm,putnam_1964_b2` for a quicker check and
  state which you ran). This is the only slow file this ticket needs; never run `ARENA_SLOW_TESTS=1` over `tests/`.
- Known pre-existing slow failures (also fail on tag v6; do not fix unless this ticket is about them):
  `tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas`
  and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`
  (fixed by tickets 15c/16); `LeanMcpTests` is flaky.

## Stop and report if

- Your recorded v6 figures are more than +50% slower than the spec's table, or the repeat run (item 10) fails the gate
  against your own baseline.
- No Lean worker is found by the `--worker` rule, or `smaps_rollup` is unreadable for Lean processes.
- A workspace needed for a baseline row is not provisioned (do not provision it from this ticket).
- A bench run leaves an orphan Lean process you cannot account for, or memory drops below 3 GB available.
- `arena lean bench` would need a change to the session protocol (new ops) to measure a figure.

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

Your branch is **`v7/07-lean-gate`**, already created and stacked directly above `v7/06-run-fixes`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/07-lean-gate` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/07-lean-gate -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-07`.
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
- [ ] Every change is committed on `v7/07-lean-gate`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-07
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
