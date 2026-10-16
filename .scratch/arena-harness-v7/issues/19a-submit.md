# 19a: `arena submit`: selection, gates, outputs, filter parity

**What to build:** `arena submit --name <name> --runs <run-or-prefix>...` prepares the competition upload under `runs/submission/<name>/`. Per benchmark row it picks the best candidate across the named runs by settled (cold-measured) score. Every row passes the gates (exact statement, the official forbidden filter, no `sorry`, a fresh cold pass on every listed toolchain, the per-problem spend total of at most $3.00 summed over every contributing run) or blocks the file. It writes `proofs.jsonl`, a manifest, a provenance ledger and a diff against the previous submission, and replaces the v6 staging path. It prepares files only: the owner uploads them. Cross-run hybrids are the next ticket (19b); this ticket must work and be finishable without them.

**Blocked by:** 10a: Graph core: steps, edges, focus, operations; 13: Price engine and instant token quotes (both committed below your branch).

**Status:** done

**Branch:** `v7/19a-submit` (stacked on `v7/18-viewer`)

**Read first:** spec user stories 87-93 and "Submission builder", Testing Decisions ("`arena submit` gates on fixture rows", "filter parity with the official app"), Out of Scope (uploading); plan §7.1 row `arena submit`, §7.2 "Forbidden filter", phase 6 in §10; `docs/BACKLOG-harness-v7.md` §6 (all of it); `docs/SUBMISSION-checklist.md`; decisions D13, D14, D31; `review-decisions` rule 7 (the $3 per-problem total stays a reported gate).

## Context: where things are now
- `arena/package.py` (v6): `stage(name, run_ids, ...)` writes `proofs.jsonl`, `provenance.json`, `report.md`, `REPRODUCE.md` and a code archive into `runs/submission-staging/<name>/`. Its pieces: `audit_run` and `check_candidate` (v6-only gates: needs a v6 trace journal, a model in `ELIGIBLE_MODELS`, `submission.json` answer, cold verification), `select` (best `proxy` per theorem from each run's single answer), `discover_runs`, `budget_by_problem`, `violations` (the `CEILING_USD` = 3.0 per-problem ceiling over every call of every run of the problem), `provenance`, `attempts` (every charged `settle` row joined to the journal), `trace_ids`, `build_archive`, `submodule_pins`, `reproduce_text`, `report`, `load_manifest`, `sha256_text`. `tools/arena_package.py` is a thin argparse wrapper that is not wired into `arena/cli`. `tests/test_package.py` tests `package.py`.
- `arena/campaign.py` `submission(run_id)`: writes a run's own `submission.json` and `submission.lean`: the best verified full candidate by score, with a clean cold re-check when a Lean session was used (`cold_verify`). Its pool filter excludes `origin` in `("reference", "auto_merge")`. `arena/merges.py` `merge_report` marks every combined proof `submitted: False`, and its docstring says `submission` skips `auto_merge`. `tests/test_merges.py::test_combination_is_reported_and_not_submitted` asserts that exclusion.
- `arena/forbidden.py`: `FORBIDDEN` (list of `(label, compiled regex)`) and `remove_comments(text)`, "synced from" the official Space `vendor/arena-space/app.py`, which defines `_MAX_PROOF_BYTES`, `_FORBIDDEN_PATTERNS`, `_strip_lean_comments` and `_check_forbidden(code) -> label | None` (it also imports gradio, so it cannot be imported). `arena/engine.py` `validate_proof(row, proof, allow_sorry=False)` checks the byte-exact statement, the `:=` that follows, the second top-level command, and `FORBIDDEN`.
- Prior art for loading the official filter without gradio: `runs/analysis/submission-v3/build.py` (parses `app.py` with `ast`, keeps only the named assignments and functions, `exec`s them). Do not import from `runs/analysis`; re-implement the loader in the package.
- Cold evaluation: `arena/engine.py` `evaluate(name, proof, "full")` under `force_cold()` evaluates on every listed toolchain with no session; `arena/campaign.py` `cold_verify` uses it. `arena/scoring.py` `metrics(...)` and `local_proxy(...)` give the proxy; the measure version is the newest listed toolchain (D31, ticket 06).
- Per-step goals (ticket 10a): every node records its steps (ids, text hash, goal before and after); the ticket-10a graph reader exposes them and a step splitter exists for splitting a proof into top-level steps (find both with `grep -n "def .*step" arena/graph.py arena/goalstate.py`). v6 nodes have no recorded goals.
- Run directories hold `run-config.json`, `ledger.jsonl`, `cost-ledger.jsonl` (settle rows), `proofs/<candidate id>.lean`, `submission.json`, `trace-journal.jsonl`. The official statements are in `benchmark/original/warmup.jsonl` (`load_manifest`).
- CLI: `arena/cli/__init__.py` (Cyclopts). There is no `arena submit`.

## What to build
- [ ] 1. Package `arena/submit/` with modules `gates.py`, `select.py`, `ledger.py`, `emit.py`, `diff.py` and an `__init__.py` exporting `build_submission(name, runs, previous=None, max_cold=5, ceiling_usd=3.0, discover=False, archive=False, overwrite=False, cold_check=None, memory_reader=None)` (`cold_check` and `memory_reader` are injection points for tests). `build_submission` runs selection per row (item 6), then calls one module-level hook `post_select(rows)` that returns the rows unchanged (ticket 19b replaces the hook with recombination), then ledger, manifest, outputs and diff. Reuse the generic helpers from `arena/package.py` by import (`sha256_text`, `load_manifest`, `attempts`, `trace_ids`, `build_archive`, `submodule_pins`, `reproduce_text`, `report`); do not copy them.
- [ ] 2. Run selection (`select.py`): `resolve_runs(names_or_prefixes, runs_root)` expands each argument that is a directory name under `runs/pi-budget` as itself and otherwise as a prefix (`name*`); an argument matching nothing is an error naming it. `pool(theorem, runs)` returns every node of every run on that theorem whose status is `full` and `verified`, origin not `reference`, with: run id, candidate id, proof text (from `proofs/<id>.lean`), recorded tokens, heartbeats and proxy, and its steps with goals when recorded. No run-level filter on harness version or model name (a v6 and a v7 run can both contribute); a run with no `run-config.json` is rejected with the reason "unknown provenance".
- [ ] 3. Gates (`gates.py`), one function `gate(row, proof, cold)` returning a list of failure strings (empty = pass), run in this order: (a) `validate_proof(row, proof)` (exact statement byte for byte, followed by `:=`, no second top-level command, no forbidden construct); (b) the official filter `_check_forbidden` loaded from `vendor/arena-space/app.py` (item 4) returns None; (c) no `sorry`, `admit` or `sorryAx` anywhere in the proof (even in a comment: reject on the plain-text match as well as the filtered one); (d) the cold result `cold` (from item 5) passed on every toolchain listed for the row; (e) the cold-measured proxy agrees with the candidate's recorded proxy: `abs(cold - recorded) <= 0.05 * max(recorded, 1)` (same tolerance as `COLD_TOLERANCE` in `arena/campaign.py`; import it). Any failure blocks that candidate; if every candidate of a row fails, the row blocks the file.
- [ ] 4. Vendored official filter: `arena/forbidden.py` gains `official_filter() -> Callable[[str], str | None]` that reads `vendor/arena-space/app.py`, parses it with `ast`, keeps only the top-level assignments (plain `=` and annotated `:`, as `_FORBIDDEN_PATTERNS: list[...] = [...]` is) and function definitions for `_MAX_PROOF_BYTES`, `_FORBIDDEN_PATTERNS`, `_strip_lean_comments`, `_check_forbidden` (and any other top-level assignment or function those four reference by name, found transitively), executes them with `re` in a fresh namespace and returns `_check_forbidden`. It must not import gradio. Cache the result with `functools.cache`. If a wanted name is missing from `app.py`, raise `RuntimeError` naming it.
- [ ] 5. Cold compile (`gates.py`): `cold_check(name, proof)` calls `arena.engine.evaluate(name, proof, "full")` inside `force_cold()`, one proof at a time (a module-level lock, sequential), and returns the result dict with `passed` per toolchain, tokens, heartbeats and proxy. Before each compile it waits until free memory is at least `ARENA_SUBMIT_MIN_FREE_GB` (default 8) using `arena.lean_session._available_gb()` (returns GB free, or None when unknown: then do not wait); the reader is injected as a parameter so tests never read `/proc`. A Lean error or timeout is a gate failure, never an exception.
- [ ] 6. Selection by settled score (`select.py`): for each row, rank the pool by recorded proxy descending (tie: fewer tokens, then earlier run id), then walk down the ranking: cold-check, gate, and take the first candidate that passes. Its settled score is the cold-measured proxy, never a label. Stop after `--max-cold N` cold compiles per row (default 5) with the row blocked. Rows with no run among the named ones are carried over from the `--previous <name>` submission (its `proofs.jsonl` row, re-gated with the same gate, cold compile included) and marked `source: previous`; rows with neither are listed under `missing` and never silently dropped.
- [ ] 7. Provenance ledger (`ledger.py`): `provenance.json` with, per row: source run(s), candidate id, proof sha256, model, provider and version from the run's `run-config.json`, pinned sources and toolchains, code version (the run record's `code` block from ticket 03 when present, else absent), local verification, and **every charged call of every contributing run** (selected and discarded; donors are added by ticket 19b): use `attempts(directory)` for each run, listing each `settle` row (id, usd, tokens, retry_of, model) and the run's reconciled total. Per row `spend_usd` = the sum over all contributing runs of the settled spend. The $3.00 per-problem total gate: a row's `spend_usd` summed over every contributing run (a run counts when its candidate is selected, or, in 19b, donates a step; discarded runs named in `--runs` for the same theorem count too, since their calls were paid) above `--ceiling-usd` (default 3.0, the closed-track per-problem maximum in `docs/SUBMISSION-checklist.md`) blocks the file and is reported per row with the sum and the runs that make it up. It is a reported gate, not a silent filter. Include the run ids of any other run of the same theorem under `runs/pi-budget` that was not listed, as `unlisted_runs` with their spend (informational; they count against the ceiling only with `--discover`).
- [ ] 8. Manifest (`emit.py`): `manifest.json` and `MANIFEST.md` with, per row: source run, candidate id, per-axis proxy (tokens, heartbeats, toolchain share) and the combined proxy, tokens, heartbeats, per-version cold results, settled spend of all contributing runs, and the code version; plus the run list, the gate results of every rejected candidate with its reasons, and the `missing` rows. Ticket 19b adds the hybrid attempts to the same file.
- [ ] 9. Outputs under `runs/submission/<name>/` (the name must match `[A-Za-z0-9][A-Za-z0-9._-]*`; an existing directory is an error unless `--overwrite`): `proofs.jsonl` (one object per row, exactly `{"name", "proof"}`), `manifest.json`, `MANIFEST.md`, `provenance.json`, `diff.md`, `diff.json`, and with `--archive` the code archive and `REPRODUCE.md` via `build_archive` (update `reproduce_text` so its regenerate step names `uv run arena submit --name <name> --runs <runs>`). Never write a file when any row is blocked: write only `blocked.json` (row, candidate, reasons) and exit with code 1. Never upload or contact any network service.
- [ ] 10. Diff (`diff.py`): `diff_submissions(new_rows, previous_dir)` compares with `runs/submission/<--previous>/proofs.jsonl` and `manifest.json`: per row `changed`, old and new proxy, delta; rows that got worse are listed first under "WORSE" in `diff.md` and exit code stays 0 but the CLI prints them in red and the summary line says how many got worse. Without `--previous`, `diff.md` says "no previous submission". A row present before and absent now is a "WORSE" row.
- [ ] 11. CLI: Cyclopts command `submit(*, name: str, runs: list[str], previous: str | None = None, max_cold: int = 5, ceiling_usd: float = 3.0, discover: bool = False, archive: bool = False, overwrite: bool = False, json: bool = False)` in `arena/cli/__init__.py` with Rich progress per row (candidate being cold-checked, gate failures as they occur). `arena submit --help` includes the checklist points of `docs/SUBMISSION-checklist.md` (the upload sequence, "prepares files only, the owner uploads", the Nov 1 and Nov 8 dates) in its help text. Exit 0 = every row passed, 1 = blocked, 2 = bad arguments.
- [ ] 12. Retire the v6 staging path: delete `arena/cli/package.py` (ticket 04 moved `tools/arena_package.py` there as `arena package`) and its registration in `arena/cli/__init__.py`, so `arena package` no longer exists, update any test in `tests/test_cli.py` that names it, delete from `arena/package.py` the functions replaced by `arena/submit/` (`stage`, `select`, `audit_run`, `check_candidate`, `discover_runs`, `budget_by_problem`, `violations`, `provenance`, `ELIGIBLE_MODELS`, `RUNS` if unused) and the corresponding tests in `tests/test_package.py`; keep the helpers listed in item 1 and their tests. Move whichever still-needed constants (`CEILING_USD`, `MANIFEST`, `RUNS`, `DEPENDENCY_FILES`) with the helpers that use them.
- [ ] 13. Tests (pure unit on fixture rows with an injected fake `cold_check`; no Lean). New `tests/test_submit.py`: (a) gates: a candidate with a modified statement, one containing `sorry` (also one whose only `sorry` is in a comment), and one whose cold result fails on one of its toolchains each block the file (`blocked.json`, exit 1, no `proofs.jsonl`); (b) selection picks, across two runs of one theorem, the candidate with the best settled (cold) proxy, not the best recorded proxy, when they disagree; (c) a row with no run is carried over from `--previous`, and a row with neither is listed under `missing`; (d) provenance lists every charged call of the selected and discarded runs and its `spend_usd` equals the sum; two runs of one theorem that are each under $3.00 but sum to more block with the sum reported; (e) the diff lists a row that got worse first and a row dropped from the previous submission as worse; (f) the post-select hook returns rows unchanged (a clean fixture writes every file of item 9). In `tests/test_forbidden_parity.py` (pure unit): `official_filter()` and `arena.forbidden` agree, on a corpus of at least 40 strings (one per `FORBIDDEN` label that triggers it, the same text inside a line comment and a block comment, `macro` as an identifier prefix, a long proof just over and under `_MAX_PROOF_BYTES`), on whether the text is rejected; and every label in `arena.forbidden.FORBIDDEN` has an official pattern that matches the same sample (a test that fails when the vendored `app.py` gains or loses a pattern).

## Do NOT
- Do not upload anything or call the network, ever. `arena submit` prepares files; the owner uploads (Out of Scope).
- Do not modify any source run directory: no new files, no ledger rows (cold verifications for submission live in the submission directory, not in the runs).
- Do not weaken a gate to make a fixture pass, and do not read the recorded proxy as the settled score. Do not drop the $3.00 per-problem total: it is summed over all contributing runs and reported.
- Do not build hybrids, step alignment or the `auto_merge` change here; they are ticket 19b. Do not add `--hybrids`, `--max-hybrids` or `proofs-no-hybrids.jsonl`.
- No model call, no spend. Do not run Lean from tests; inject `cold_check` and the memory reader. Tests must not read `/proc`.
- Do not change `arena.engine.validate_proof`'s checks or `arena/forbidden.FORBIDDEN`'s patterns (the parity test reports drift; fixing drift in `FORBIDDEN` needs the owner: stop and report).
- Do not edit `vendor/` or `docs/`.
- `submission()` in `arena/campaign.py` is untouched here.

## Acceptance
- `uv run arena submit --help` shows the options and the upload checklist text.
- On fixture rows (tests) every gate failure blocks the file and names the row and reason; a clean fixture writes all files of item 9 and the diff.
- `provenance.json` lists every charged call (selected and discarded runs) and the per-row sum; a row whose sum is over `--ceiling-usd` blocks.
- The parity test fails if `vendor/arena-space/app.py`'s patterns diverge from `arena.forbidden`.
- `uv run python -c "import arena.package, arena.submit"` works and `arena package` is gone (`uv run arena --help` no longer lists it, and lists `submit`).
- Reviewer (owner machine, real Lean, one Lean process at a time): `uv run arena submit --name smoke --runs <one existing v6 run of Core.InitsUpdatesComm>` writes `runs/submission/smoke/` with that row passing cold on every listed toolchain.

## Verify
- `uv run pytest -q -p no:cacheprovider tests/test_submit.py tests/test_forbidden_parity.py tests/test_package.py tests/test_cli.py` -> all pass (baseline minus removed `test_package` stage tests plus the new tests). No slow file: tests inject the cold check.
- `uv run arena submit --help` -> exit 0 and the checklist text.
- `uv run ruff check arena/submit arena/forbidden.py arena/package.py arena/cli/__init__.py tests/test_submit.py tests/test_forbidden_parity.py`, then the same with `uv run ruff format --check` -> clean (fix `ty` diagnostics only in the files you touch).
- Last, once: `uv run pytest -q -p no:cacheprovider` (fast suite) -> all pass.

## Stop and report if
- Ticket 10a stores step goals in a shape that does not give `goal_before` per top-level step, or has no reader usable on a run directory outside the running campaign (the pool needs the steps for 19b).
- `arena.lean_session._available_gb` is gone or changed meaning (do not write a new `/proc` reader without asking).
- `vendor/arena-space/app.py` has changed its filter so that the four names of item 4 are no longer top-level definitions.
- The parity test finds drift between `app.py` and `arena/forbidden.py` on the current vendored commit (report the differing labels; do not edit `FORBIDDEN`).
- A step splitter or goal reader would have to be written from scratch (that belongs to ticket 10a).
- Per-row spend over the ceiling for a real run set, or a gate that fails for every candidate of a real row: report; do not relax.

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

Your branch is **`v7/19a-submit`**, already created and stacked directly above `v7/18-viewer`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/19a-submit` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/19a-submit -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-19a`.
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
- [ ] Every change is committed on `v7/19a-submit`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-19a
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
