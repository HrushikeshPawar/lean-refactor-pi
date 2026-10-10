# 19b: Cross-run recombination; `auto_merge` exclusion removed

**What to build:** `arena submit` gains cross-run recombination. After it has picked and gated the best candidate of a row, it tries hybrids that swap one step of that best for a cheaper step from any named run's node at the same subgoal, aligned by step goals. Each hybrid is cold-checked and gated, and kept only if its settled proxy is higher. Separately, a run's own `submission()` may now submit an `auto_merge` candidate when it is the best verified, instead of excluding it. Recombination uses Lean time only, never a model call.

**Blocked by:** 19a: `arena submit`: selection, gates, outputs, filter parity (committed below your branch).

**Status:** ready-for-agent

**Branch:** `v7/19b-recombine` (stacked on `v7/19a-submit`)

**Read first:** plan §5g (Recombination, the `auto_merge` exclusion), phase 6 in §10; `docs/BACKLOG-harness-v7.md` §6; spec "Submission builder"; decisions D13, D14, D31. Read ticket 19a (committed below you) for the `arena/submit/` layout.

## Context: where things are now
- `arena/submit/` (ticket 19a): `select.py` (`resolve_runs`, `pool`, selection by settled score), `gates.py` (`gate`, `cold_check`), `ledger.py`, `emit.py`, `diff.py`, and `build_submission` in `__init__.py` with a module-level hook `post_select(rows)` that today returns the rows unchanged. This ticket replaces that hook. `pool(theorem, runs)` already returns each node's steps with goals when recorded.
- Per-step goals (ticket 10a): every node records its steps (ids, text hash, goal before and after); the ticket-10a graph reader exposes them and a step splitter exists for splitting a proof into top-level steps (find both with `grep -n "def .*step" arena/graph.py arena/goalstate.py`). v6 nodes have no recorded goals.
- Token counting: `arena.engine._proof_length` through `arena.vendor` is the official counter.
- `arena/campaign.py` `submission(run_id)`: writes a run's own `submission.json` and `submission.lean`: the best verified full candidate by score, with a clean cold re-check when a Lean session was used (`cold_verify`). Its pool filter excludes `origin` in `("reference", "auto_merge")` (a comment above it says combined proofs are never submitted). `arena/merges.py` `merge_report` marks every combined proof `submitted: False`, its docstring says `submission` skips `auto_merge`, and `merge_text` says "never submitted". `tests/test_merges.py::test_combination_is_reported_and_not_submitted` asserts that exclusion. Other callers of `submission()` are in `tests/test_lean_session.py` and `tests/test_protocol.py`.
- The in-harness recombination of ticket 12 (salvage chain, auto-assembly) is separate and stays as it is.

## What to build
- [ ] 1. Cross-run recombination: new module `arena/submit/recombine.py`, and `build_submission` gains parameters `hybrids=True` and `max_hybrids=20`. Replace the `post_select` hook with a call to `recombine(rows, ...)` when `hybrids` is true (when false the rows pass through unchanged). For each row, take the gated best (ticket 19a item 6) as the base. Align steps of the base with steps of every other pool node (all runs): two steps are aligned when their goal-before text is identical (and goal-after identical when both are recorded). When a node has no recorded goals (v6), fall back to step position plus step hash: step `i` of the donor aligns with step `i` of the base only when both proofs have the same number of top-level steps and the donor's step text hashes differ. For each aligned donor step whose token count (official counter, `arena.engine._proof_length` through `arena.vendor`) is smaller than the base step's, build the hybrid by replacing that one step, order the hybrids by token saving descending, and `cold_check` + `gate` up to `--max-hybrids N` (default 20) of them. Accept a hybrid whose settled proxy is higher than the current best; after each accept, rebuild the remaining swaps on top of the accepted hybrid (greedy). Record every attempted hybrid with: base node, donor run and node, step index, token saving, gate result and settled proxy.
- [ ] 2. Step alignment is by step goals, across runs. When both nodes have recorded goals, align only by the recorded `goal_before` / `goal_after` text of their steps (the ticket-10a reader), never by a guess from proof text; the v6 position-and-hash fallback of item 1 applies only when a node has no recorded goals. A step of a donor node whose `goal_before` text equals the base step's `goal_before` text (and `goal_after` too when both are recorded) is aligned, wherever in the donor proof it sits and whichever run the donor is from. Same-proof steps are never donors. A donor step with a different goal is never swapped.
- [ ] 3. A hybrid is a harness-made merge candidate with `origin: "submit_merge"` and a `merged_from` list of every contributing `(run, node, step)`. It is written to the submission's own `hybrids/<row>-<n>.lean` and is never written into any source run directory (source runs stay untouched). A donor run counts toward the row's `spend_usd` and its calls are added to `provenance.json` (ticket 19a item 7), so a hybrid whose contributing runs sum over `--ceiling-usd` blocks the file with the sum reported.
- [ ] 4. Outputs: `proofs.jsonl` includes hybrids (still exactly `{"name", "proof"}`); add `proofs-no-hybrids.jsonl` (the single-run best for the same rows), written whenever any row's final proof is a hybrid. `manifest.json` and `MANIFEST.md` show, for a hybrid row, the hybrid id, its `merged_from`, per-version cold results and settled proxy, and gain a `hybrid_attempts` list holding every attempted hybrid (base node, donor run and node, step index, token saving, gate result, settled proxy, accepted or rejected with the reason). `diff.json`/`diff.md` compare final rows as before.
- [ ] 5. CLI: add to `submit` in `arena/cli/__init__.py` the options `hybrids: bool = True` (`--hybrids/--no-hybrids`) and `max_hybrids: int = 20` (`--max-hybrids`), and mention them in the help text. `--no-hybrids` must give exactly the 19a output.
- [ ] 6. Remove the `auto_merge` exclusion: in `arena/campaign.py` `submission()` change the pool filter to exclude only `reference` (an `auto_merge` candidate that passes every version is now eligible), update the comment above it, update the `arena/merges.py` module docstring and `merge_report`'s `submitted` value (`submitted` is now `True` exactly when the combined candidate's id equals the run's `submission.json` `candidate_id`; read that file when present, else False), and rewrite `tests/test_merges.py::test_combination_is_reported_and_not_submitted` as `test_the_best_combination_is_submitted` (the 80.0 combination is now the answer, `submission.lean` equals the combined text). `merge_text`'s "never submitted" wording is updated to match.
- [ ] 7. Tests (pure unit on fixture rows with injected fake `cold_check`; no Lean). In `tests/test_submit.py`: (a) two runs with recorded goals, a donor step at the same `goal_before` with fewer tokens produces an accepted hybrid with `origin: submit_merge` and a `merged_from` naming both runs, and a donor step with a different goal is never swapped; (b) the v6 fallback aligns by position and hash only when the step counts match, and not otherwise; (c) a hybrid that fails the cold check or lowers the proxy is rejected and logged in `hybrid_attempts`; (d) a donor run's calls appear in provenance and a hybrid row whose runs sum over the ceiling blocks; (e) `--no-hybrids` output equals the no-hybrid output of the same fixture; `proofs-no-hybrids.jsonl` appears only when a hybrid is final; (f) no file is written into a source run directory. In `tests/test_merges.py`: the rewritten test of item 6.

## Do NOT
- Do not upload anything or call the network. No model call, no spend: recombination is Lean time only.
- Do not accept a hybrid that was not cold-checked and gated; do not hand-assemble hybrids; do not weaken a gate.
- Do not modify any source run directory.
- Do not run Lean from tests; inject `cold_check` and the memory reader. Tests must not read `/proc`.
- Do not touch the in-harness recombination of ticket 12 or the merge worker beyond item 6's exclusion removal.
- `submission()` still re-verifies session-vouched candidates cold; keep that. Only the `auto_merge` exclusion goes; `reference` stays excluded.
- Do not change 19a's gates, selection, provenance sums or filter parity.

## Acceptance
- A hybrid appears in `proofs.jsonl` only with its `merged_from`, cold results and settled proxy in `manifest.json`; `proofs-no-hybrids.jsonl` holds the single-run best for the same rows.
- `arena submit --help` lists `--hybrids/--no-hybrids` and `--max-hybrids`.
- `--no-hybrids` output is identical to ticket 19a's.
- `campaign.submission` returns an `auto_merge` candidate when it is the best verified full one.
- Reviewer (owner machine, real Lean): `uv run arena submit --name smoke-hy --runs <two existing runs of one theorem>` completes, with every attempted hybrid listed in `manifest.json`.

## Verify
- `uv run pytest -q -p no:cacheprovider tests/test_submit.py tests/test_merges.py tests/test_protocol.py` -> all pass (baseline + new; `test_combination_is_reported_and_not_submitted` replaced). No slow file: Lean is injected.
- `uv run arena submit --help` -> exit 0 and lists `--hybrids` and `--max-hybrids`.
- `uv run ruff check arena/submit arena/campaign.py arena/merges.py arena/cli/__init__.py tests/test_submit.py tests/test_merges.py`, then the same with `uv run ruff format --check` -> clean (fix `ty` diagnostics only in the files you touch).
- Last, once: `uv run pytest -q -p no:cacheprovider` (fast suite) -> all pass.

## Stop and report if
- Ticket 10a stores step goals in a shape that does not give `goal_before` per top-level step, or has no reader usable on a run directory outside the running campaign.
- A step splitter or goal reader would have to be written from scratch (that belongs to ticket 10a).
- Ticket 19a's `post_select` hook or `pool` steps are missing or shaped differently from the context above.
- Removing the `auto_merge` exclusion breaks a test other than `test_combination_is_reported_and_not_submitted`.
- A gate fails for every hybrid of every row of a real run set: report; do not relax.

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

Your branch is **`v7/19b-recombine`**, already created and stacked directly above `v7/19a-submit`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/19b-recombine` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/19b-recombine -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-19b`.
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
- [ ] Every change is committed on `v7/19b-recombine`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-19b
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
