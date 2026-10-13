# 08d: REPL pool and v4.32 header trial

**What to build:** A pool of Lean REPL processes, keyed by (toolchain workspace, file header), serves whole-proof checks (cross-version checks first) inside the shared Lean service from tickets 08a to 08c. One imported header serves many checks, with env pickling so a header survives a process restart. The benchmark compares it with the LSP lane; the pool is switched on by default only if it shows a gain by the rule below, otherwise it ships complete but off. A second, small trial measures Lean v4.32's `--incr-header-save` / `--incr-load` on the rows that use v4.32 or later.

**Blocked by:** 08c: Lean service callers, tests, speed gate (all lower tickets are committed below your branch).

**Status:** ready-for-agent

**Branch:** `v7/08d-repl-pool` (stacked on `v7/08c-lean-callers`)

**Read first:** SPEC "Lean service" (Modules), "Testing Decisions" Seam C (REPL pool and LSP lane agree), "Speed baseline and gate"; PLAN §9b (lanes, "Benchmark first" items 3 and 5), §9c ("Engine choice", "v7 target", "Cheap trials"); decisions D32, D35 and owner decisions 4 (speed gate noise floor) and 9 (REPL adoption rule), restated in checkboxes 11 and 15 below. SPEC user stories 22, 24.

## Context: where things are now
- Tickets 08a to 08c made `arena/lean_session.py` the machine-wide service: `Session` with lanes `model` and `background`, ops `status`, `lease`, `release`, `hold`, `unhold`, `warm` (with `"wait": false`), `check`, `goal`, `try`, `shutdown`, `service_dir()`, `ensure_service()`, `worker_pss()`, `pss.jsonl`, `WorkerBudget.opening()` (one header load at a time machine-wide, `RESERVE_GB` check). Ticket 07 added `arena lean bench` and a saved baseline.
- No REPL code exists anywhere in the repo (`grep -ri repl arena tools` finds nothing relevant). The Lean REPL is `https://github.com/leanprover-community/repl`; the tags `v4.25.0` to `v4.33.0` (including `v4.33.0-rc2`) exist, there is **no `v4.29.1` tag** (PLAN §9c). Toolchains are installed with elan under `~/.elan/toolchains` for every version the 15 rows list.
- `arena/engine.py`: `run_lean(row, project, text, timeout, prefix_end, lane)` sends the whole candidate file (`text`) with `header_end` (`prefix_end`) to the service; `compile_version` adds the `HEARTBEAT_WRAPPER` text (`arena_measure_heartbeats` command) right after the header when `measure=True`; `last_lean_run()` reports the path. `render(diagnostics, text, display)` in `lean_session.py` turns LSP diagnostics into the `file:line:col: severity: message` text `lean <file>` prints, which `structure_diagnostics` parses.
- `arena/campaign.py`: `autocheck` and `record_evaluation(..., lane="background")` drive the cross-version checks (mode `full`) through `_evaluate(..., lane=lane)` and `engine.evaluate`, which calls `compile_version(..., lane=lane)` per toolchain; `cold_verify` uses `force_cold()` (cold lane, untouched).
- Tests: `tests/test_lean_session_warm.py` (fast, scripted fake language server `FakeLean`), `tests/test_lean_session.py` (slow, real Lean, `SessionHarness.both` compares session and cold results; `TOLERANCE = 0.05` heartbeat tolerance).
- `runs/` and `workspaces/` are gitignored; `runs/cache/` already holds derived caches.

## What to build

- [ ] 1. `arena/lean_repl.py` (new): REPL build and registry. `repl_dir(toolchain: str) -> Path` is `runs/cache/repl/<toolchain>/` (for example `v4.30.0`). `build(toolchain, log=print) -> Path` clones `leanprover-community/repl` at tag `<toolchain>` (shallow), runs `lake build` inside it with that toolchain (elan finds it from the checkout's `lean-toolchain`), and returns the path of the built `repl` binary. If the tag does not exist (v4.29.1), clone the nearest earlier tag (`v4.29.0`), overwrite its `lean-toolchain` with `leanprover/lean4:<toolchain>`, build, and record in `runs/cache/repl/<toolchain>/build.json` `{"tag", "toolchain", "built_with_override": true, "ok": bool, "error"}`. A build failure is recorded, not raised, and later checks treat that toolchain as `repl_unsupported`. Network is required; with no network the build records `ok: false` and says so.
- [ ] 2. CLI: `arena lean repl-build [--toolchain V ...]` (default: every toolchain the 15 benchmark rows list, deduplicated) in the existing `arena lean` group; one build at a time, a Rich line per toolchain (`ok`/`failed` plus seconds), `--json`. Builds are Lean-heavy: they run strictly one after another.
- [ ] 3. Compatibility check for v4.29.1 (PLAN §9c): after the build, `arena lean repl-build --toolchain v4.29.1` also runs `lean_repl.smoke(toolchain, project)` : start a REPL for the Core row's workspace `workspaces/strata-v4.29.1`, import the Core row's file header, check the reference proof, and require pass plus the same pass/fail as the LSP lane. Result goes in `build.json` as `smoke: {"ok", "seconds"}`. If it fails, the toolchain stays `repl_unsupported`; the ticket is still complete (the pool falls back to the LSP lane for it). Put the outcome in the hand-back.
- [ ] 4. REPL process wrapper in `arena/lean_repl.py`: `class ReplProcess` (start `lake env <repl binary>` with the workspace's `LEAN_PATH` exactly as `engine._lean_command` and `LeanServer.command` obtain it, in its own process group with `start_new_session=True`; JSON commands on stdin separated by a blank line; read one JSON reply per command; timeout per command; `alive()`, `stop()`, `pgid`). Methods: `run(cmd: str, env: int | None, timeout) -> dict` (REPL `{"cmd", "env"}` request), `pickle(env, path)` (`{"pickleTo": path, "env": n}`), `unpickle(path) -> int` (`{"unpickleEnvFrom": path}`). A timeout kills the process (REPL commands cannot be cancelled) and raises `ReplError`.
- [ ] 5. Message conversion `render_repl(messages: list[dict], header: str, display: str) -> tuple[int, str]` producing exactly what `lean_session.render` produces for the same file: REPL messages carry `severity` (`error`, `warning`, `info`), `pos {line (1-based, relative to the command), column (code points)}` and `data`; add the number of lines in `header` to every line, print `info` messages as bare text, warnings and errors as `<display>:<line>:<col>: error|warning: <text>`, return code 1 if any error. A fast test feeds one REPL reply and the equivalent LSP diagnostics to both renderers and requires identical text (Seam C).
- [ ] 6. Pool in the service: `class ReplPool` in `arena/lean_repl.py`, owned by `Session` (`Session.repl`). Key `(project_path, sha256(header)[:16])`; one `ReplProcess` per key holding the env number after the header. `check(project, header, body, timeout) -> dict`: get or create the process (first command is the whole `header` text, which imports and loads the file prefix; its env is kept), run `body` with that env. The header load goes through `WorkerBudget.opening(...)` like an LSP header open. Limits: `REPL_MAX_PROCESSES = 5` resident in all, LRU eviction of the least recently used idle process when a sixth is needed; `REPL_MAX_GB = 4.0` PSS per process, checked with `worker_pss` after every command, over the cap the process is stopped and dropped after replying (the next check re-imports). Both numbers are placeholders chosen by this ticket's benchmark (open question for the owner: the plan gives only "about 5 resident"); put the measured PSS in the hand-back. Referenced-project rule from 08a applies: close a project's REPL processes when its entry is closed.
- [ ] 7. Env pickling: after a header loads, `ReplProcess.pickle` writes `runs/cache/repl/pickles/<toolchain>/<header sha>.olean`-style file (any single file the REPL accepts); a process that dies or is evicted is restarted by `unpickle` instead of re-importing. Verify the round trip once per (toolchain, header): after the first `unpickle`, run the row's reference proof and one failing draft on the fresh env and on the unpickled env and require equal pass/fail and messages. If they differ (PLAN §9c: scoped extensions do not round-trip), write `<sha>.nopickle` next to the file and never unpickle that header again. The pickle directory is deleted by `arena lean repl-build --clean`.
- [ ] 8. New request lane `batch`: `{"op":"check","lane":"batch",...}` (same fields as the existing `check` op; `header_end` required). The service answers from the REPL pool when `REPL_ENABLED` (constant, see 11) is true, the toolchain is not `repl_unsupported`, and the request is not a `measure` request that needs per-tactic data; in every other case it serves the request on that project's `background` lane exactly as before and the reply says `"lane": "background"`. A REPL error or timeout on a batch request falls back to the background lane once, and the reply says `"fallback": "repl"`. The reply carries `engine: "repl"|"lsp"`, `returncode`, `output`, `seconds`.
- [ ] 9. `engine.run_lean` accepts `lane="batch"` (the lane value is forwarded unchanged), puts `engine` into `last_lean_run()`, and its timeout budget math is unchanged. In `arena/campaign.py` the cross-version autocheck (`record_evaluation(... lane="background")` called from `autocheck`) uses `lane="batch"`. `cold_verify`, `submission` and everything on the model lane are not changed.
- [ ] 10. Benchmark: extend `arena lean bench` (ticket 07; find it with `grep -rn "def bench" arena tools`) with `--engine lsp|repl|both`, default `both` for the new comparison table only (the baseline gate keeps using the model lane). On the saved drafts of each benchmarked row (the check mix of ticket 07 plus 20 drafts per row: reference, edits, error drafts, sorry drafts; the same drafts for both engines) report per toolchain: header cost cold (fresh import) and via unpickle, check p50/p95 for the batch lane vs the background LSP lane, PSS per REPL process vs per LSP worker, pickle file size, and the number of pass/fail disagreements and the largest heartbeat difference. Rows: the three of the baseline plus one ArkLib row (`Binius.BinaryBasefold.fold_advances_eval`) and one PhysLib row; toolchains without a built REPL are listed as `unsupported`. Save the table as JSON next to the ticket-07 baseline (same directory, file `repl-compare.json`).
- [ ] 11. Adoption rule, coded in the benchmark's report (`adopt: true|false` per toolchain and overall) and in `REPL_ENABLED` (default `False` in code; the ticket sets it to `True` only if the overall rule holds). The rule (owner decision 9, binding; do not tune the numbers): adopt only if on every compared row (a) there are 0 pass/fail disagreements between the REPL and the LSP lane, (b) heartbeats agree within 5% (the certification tolerance) and the batch lane's heartbeat figures stay within 5% of the LSP lane's measurement, (c) the batch check p50 is no more than 10% above the LSP background check p50, and (d) either the unpickled header load is at most half of a fresh header open or the PSS per REPL process is below the PSS per LSP worker on the same toolchain. Otherwise the pool ships disabled (`REPL_ENABLED = False`) and the ticket is still complete. If the rule fails, leave `REPL_ENABLED = False`, still commit everything (pool, builds, tests and benchmark all stay), and say so first in the hand-back.
- [ ] 12. v4.32 header-snapshot trial (rows whose toolchain is v4.32.0 or newer: the PhysLib rows and the Cslib rows). Read `lean --help` under the v4.32 toolchain for the exact flags (PLAN names them `--incr-header-save` and `--incr-load`). If they are absent, record `not available` and stop this checkbox. Otherwise add `lean_repl.header_snapshot_trial(project, header, timeout)` that compiles a header once with the save flag, then a second time with the load flag, and `arena lean bench --trial header-snapshot` prints cold import seconds vs load seconds and whether diagnostics equal a plain `lean` compile of the same file. Nothing in the service uses it; the output decides a later ticket. Do not change the service for it.
- [ ] 13. Pool lifecycle tests, fast, in a new `tests/test_lean_repl.py`, using a scripted fake REPL (a short Python script that speaks the REPL JSON, like `FakeLean` in `tests/test_lean_session_warm.py`) injected through a `ReplPool(factory=...)` argument:
  - one header serves many bodies with one import (the fake counts header commands);
  - the sixth distinct header evicts the least recently used idle process, never a busy one;
  - a process over `REPL_MAX_GB` (injected `pss_fn`) is dropped after its reply and the next check re-imports (or unpickles);
  - a timeout kills the process, the request falls back to the background lane once with `fallback: "repl"`, and the next batch check starts a fresh process;
  - a header whose pickle round trip differs gets `.nopickle` and is never unpickled again;
  - releasing the last lease and hold of a project stops its REPL processes;
  - `render_repl` equals `render` (checkbox 5).
- [ ] 14. Seam C slow test in `tests/test_lean_session.py` (needs a built REPL for the Core row's toolchain, skip with a clear message otherwise): for a compiling, a failing and a hole draft of the Core row, the batch lane (force `REPL_ENABLED` for the test) and the LSP background lane return the same `passed`, `diagnostic_counts`, `goals`, and heartbeats within `TOLERANCE` (use `SessionHarness.assertSameResult` style comparison with `measure=True`). Add the same for one Cslib row if its REPL is built.
- [ ] 15. Speed gate, run **once, at the end** (owner decision 4): `uv run arena lean bench --full --compare benchmark/derived/lean-baseline.json` (the full gate: every row and toolchain the baseline holds, ArkLib's four included, about 25 minutes; this ticket closes the service work, a milestone, owner decision 2026-10-13). A figure fails only if it exceeds BOTH the relative tolerance (+10% p50, +20% p95) AND the 0.25 s absolute noise floor; the command already applies this. Paste the table in the hand-back. If a figure fails, stop and report; do not loosen the tolerance or the floor. The model lane is untouched here, so a failure points at the pool's memory or start-up cost.

## Do NOT
- Do not change the model lane, the background lane's behaviour when a request is not `batch`, `render`, the heartbeat wrapper, `_run_cold`, or the cold lane. The LSP lane stays the source of truth for scoring heartbeats (D32); `batch` requests are pass/fail checks plus, in tests only, heartbeats.
- Do not route anything but the autocheck's cross-version checks to `batch` in this ticket. Salvage, recombination, declaration index and certify will adopt it in their own tickets.
- Do not store pickles or REPL builds in tracked paths (`runs/` is gitignored).
- Do not fetch or build anything except `leanprover-community/repl` tags. Do not touch `workspaces/`.
- No model-facing text.
- Never run two Lean-heavy commands at once: REPL builds, the benchmark and slow tests go one after another, with the service otherwise idle. Kill processes by PID only (service pid from `service.json`, REPL pids from `arena lean status`); never `pkill`, `killall` or `pgrep -f | kill`. Leave no service or REPL process running: finish with `uv run arena lean stop`.

## Acceptance
- `arena lean repl-build` builds every needed REPL, records v4.29.1's outcome (built with the override and smoke-tested, or `repl_unsupported` with the reason).
- With `REPL_ENABLED` forced on, a batch check of the same file twice imports its header once, and a restart of the service reuses a pickled header or re-imports when the pickle is marked bad.
- On the benchmark rows the batch lane and the LSP background lane agree on pass/fail and on heartbeats within 5%.
- `repl-compare.json` exists, states per toolchain and overall whether the adoption rule holds, and `REPL_ENABLED` matches it.
- The v4.32 trial reports numbers or `not available`.
- The model-lane speed gate is unchanged.

## Verify
TEST BUDGET: targeted files, then the fast suite once, then one slow file, then the gate once.
- `uv run pytest -q -p no:cacheprovider tests/test_lean_repl.py` -> all pass.
- `uv run ruff check arena tools tests && uv run ruff format --check arena tools tests` -> clean for the files you touched.
- `uv run arena lean repl-build` -> one line per toolchain, exit 0 even when v4.29.1 is unsupported.
- `uv run arena lean bench --engine both ...` (rows and flags per ticket 07; `--help`) -> writes `repl-compare.json`, prints the table and the adoption verdict.
- `uv run arena lean bench --trial header-snapshot ...` -> numbers or `not available`.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_lean_session.py` -> all pass, one at a time (the REPL tests of checkbox 14 skip with a clear message if no REPL is built).
- `uv run arena lean bench --full --compare benchmark/derived/lean-baseline.json` (checkbox 15) -> exit 0, no figure over both tolerance and 0.25 s.
- `uv run pytest -q -p no:cacheprovider` (fast suite, once, at the end) -> all pass (baseline plus the new fast tests).
- `uv run arena lean stop && uv run arena lean status` -> "no service".

## Stop and report if
- There is no network, so no REPL tag can be cloned (report which builds failed; do not vendor a REPL by other means).
- A REPL build for a toolchain other than v4.29.1 fails.
- The REPL's JSON protocol on a built binary differs from checkboxes 4 and 5 (for example `pickleTo` or `unpickleEnvFrom` is rejected): report the reply you got.
- Pass/fail disagreements appear between the REPL and the LSP lane on the reference or a failing draft (a correctness issue, not a tuning one).
- The adoption rule gives different answers on different rows in a way you cannot explain.
- The ticket-07 baseline or `arena lean bench` is missing, or the service from 08a is not the one running.

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

Your branch is **`v7/08d-repl-pool`**, already created and stacked directly above `v7/08c-lean-callers`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/08d-repl-pool` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/08d-repl-pool -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-08d`.
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
- [ ] Every change is committed on `v7/08d-repl-pool`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-08d
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
