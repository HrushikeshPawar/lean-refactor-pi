# 10b: Per-step goals pipeline

**What to build:** Every closed or sketch node gets the goal before and after each top-level step of its proof, computed by a background Lean job and stored in the run's ledger as a `step_goals` event. The graph projection joins those goals into each node's steps. Nothing the model sees changes yet; later tickets (the map, `read`, prices) read these goals. The job runs only in the background lane, derived from the ledger like the full checks, so a killed checker loses nothing. The Lean speed gate is run once at the end.

**Blocked by:** 10a: Graph core: steps, edges, focus, operations; 08c: Lean service callers, tests, speed gate. (Everything below is committed below this branch.)

**Status:** done

**Branch:** `v7/10b-step-goals` (stacked on `v7/10a-graph-core`)

**Read first:** spec sections "Graph core", "Testing Decisions" (Seam A) and "Further Notes" (probe evidence); plan §5a, §5g (the paragraph on goal states at step boundaries), §10 phase 3; decisions D7, D16, D23, D28, D39.

## Context: where things are now
Names are as of ticket 10a. If a name below no longer exists and you cannot find its obvious successor, stop and report.
- Ticket 10a added: `arena/steps.py` (`Step` frozen dataclass with `id`, `first_line`, `last_line`, `text`, `hash`, `indent`; `split_steps`, `step_range`), `graph.Graph.from_history(history, read_text)` with `Node` (`status` of `closed` / `sketch` / `broken`, `steps`, `edge`, ...), the `edge` and `focus` events (documented in the `arena/graph.py` module docstring), `tests/graph_support.py::FakeRunCase` (fake-Lean fixture), `tests/test_graph.py`.
- `autocheck(name, run_id, max_seconds)` in `arena/campaign.py` is the background checker (`arena protocol autocheck`, started by `kickAutocheck` in `packages/arena-pi/extensions/arena.ts`). It holds `autocheck.lock`, derives its job queue from the ledger so a killed checker loses nothing, and runs in the background lane. Its Lean calls go through the machine-wide service as ticket 08c left them (the LSP lane for background work); follow exactly the pattern the existing full-check job uses for the lane and its lock (today `lean_lock(directory, "background")`). `write_state` publishes `state.json`.
- `arena/lean/context.lean` already walks the info tree and emits, for each top-level tactic of the theorem's `by` block, a record `{"kind":"goal","line","endLine","text"}` with the goals before that tactic (`topLevel`, `visit`, `ppGoal`); `arena/context.py:lean_context` shows how a Lean script is inserted into the candidate file, run (`run_lean`) and parsed (`parse_context`). `arena/lean/profile.lean` + `arena/profile.py:_instrumented` do the same for heartbeats.
- `tests/test_protocol.py` has the Strata fixture `FIXTURE` and `CampaignCliTests` (class style for `@slow` Lean tests, decorator from `tests/slow.py`).

## What to build

**A. The event and the projection**
- [ ] 1. Define one new ledger event kind, documented in the `arena/graph.py` module docstring beside the others and written only through `campaign._append`: `{"kind":"step_goals","proof_id","goals":[{"id":"s1","before":str|None,"after":str|None}, ...]}` or `{"kind":"step_goals","proof_id","error":str}`.
- [ ] 2. Projection: add `before: str | None = None` and `after: str | None = None` to `steps.Step`, and make `Graph.from_history` join the goals of a node's last successful `step_goals` event into `Node.steps` by step id (`dataclasses.replace`). A node with no event, or only an `error` event, keeps `None` goals. Steps that the event does not list keep `None`.

**B. Per-step goals**
- [ ] 3. Create `arena/lean/steps.lean` by copying the part of `arena/lean/context.lean` that finds the `by` block's top-level tactics (`findBy`, `topLevel`) and walks the info tree (`visit`, `goalsBefore`, `ppGoal`), and delete everything else (declaration ranges, library scan, constants, locals). It is a command elaborator like `arena_context` and takes `@@TARGET@@` the same way. It emits one `logInfo` line per top-level tactic: `ARENA_STEPS {"line":..,"endLine":..,"text":..}` where `text` is the pretty-printed goals before that tactic (nothing printed means no goals).
- [ ] 4. Create `arena/step_goals.py`: `step_goals(name, proof, lane="background") -> list[dict]`. It builds the candidate file for `proof` (as `lean_context` does with `candidate_file`, inserting `steps.lean` before the declaration, `run_lean(..., lane=lane)`), parses the `ARENA_STEPS` lines, maps each record to a step by `line` (proof-relative, as `parse_context` does with `shift` and `start_line`; match `Step.first_line`), and returns `[{"id","before","after"}]` for every step of `split_steps(proof)`. `before` is the record's text; `after` is the next step's `before`, and for the last step `None` when the proof is closed (otherwise the goals Lean reports, or `None`). A step with no record gets `before: None`. A Lean failure or timeout raises `ValueError`. Keep the parse of the Lean output in its own pure function so tests can feed canned output.
- [ ] 5. Queue and recording: `autocheck` also drains **step-goal jobs**, derived from the ledger: nodes with status `closed` or `sketch` that have neither a `step_goals` event nor an error recorded for them. Each job runs in the background lane (same lock/lane pattern as the full checks), appends a `step_goals` event (an `error` string when it raised), and calls `write_state` as the full checks do. Job order: full checks first, then step goals (a node is only useful to the model through its score first).

**C. Tests** (unittest style; fast tests have no Lean; Seam A unless stated)
- [ ] 6. Pure part: the parse of `ARENA_STEPS` output into `[{"id","before","after"}]` on a canned Lean output (middle steps get the next step's `before` as `after`; the last step of a closed proof gets `after: None`; a missing record gives `before: None`).
- [ ] 7. Projection (in `tests/test_graph.py`): a `step_goals` event fills `before`/`after` into `Node.steps` by id; an `error` event leaves them `None`; a later successful event wins.
- [ ] 8. Queue (fake Lean, `FakeRunCase`, patch `step_goals.step_goals`): the autocheck queue offers a closed or sketch node until a `step_goals` event (success or `error` form) exists for it, so a checker killed before it wrote the event loses nothing and a recorded error is not retried; broken nodes are never offered; the job is run with `lane="background"`; full checks are drained before step goals.
- [ ] 9. One `@slow` Lean test in `tests/test_protocol.py` (Strata fixture `FIXTURE`, class style of `CampaignCliTests`): `step_goals(NAME, FIXTURE.read_text())` returns one entry per top-level step; the first `before` is non-null and does not contain `Hup`; the first `after` contains `Hup` and `Hinit` and equals the second step's `before`; and the last `after` is `None`. Run it once and put its output in the hand-back.
- [ ] 10. Run `uv run ruff check` and `uv run ruff format` on every file you touched, and `uv run ty check arena/steps.py arena/graph.py arena/step_goals.py` plus the files you touched (fix only diagnostics in lines you wrote).

**D. Speed gate (once, at the end)**
- [ ] 11. This ticket adds Lean work, so run the gate of ticket 07 **once**, after every other item is done and committed: `uv run arena lean bench --compare benchmark/derived/lean-baseline.json` (the quick gate: Core, Putnam and CSLib, about 6 minutes; owner decision 2026-10-13) and `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_lean_speed_gate.py`, one command at a time, machine otherwise idle. A figure fails only if it exceeds BOTH the relative tolerance (+10% p50, +20% p95) AND the 0.25 s absolute noise floor. Paste both results in the hand-back. If it fails, do not change the baseline or the tolerances: stop and report.

## Do NOT
- Do not change any model-facing string or old reply field. This ticket adds no model-facing text.
- Do not run Lean in the model lane for step goals and do not run it inside the model's compile call; it is a background job only.
- Do not edit `arena/lean/context.lean` (copy from it; do not move or change it).
- Do not expose step goals through a Pi tool or edit `packages/arena-pi/extensions/arena.ts`.
- Do not change the graph's node ids, edges, filing or focus rules (ticket 10a), or add holes, routes or prices.
- Do not change the Lean toolchain, workspaces, `models.yaml`, the speed baseline file or the gate tolerances.
- Do not run the speed gate more than once, and never as part of the fast suite.

## Acceptance
- Every closed or sketch node gets a `step_goals` event from `autocheck`, in the background lane, with one entry per top-level step; `Graph.from_history` exposes the goals on `Node.steps`.
- A checker killed mid-job is harmless: running `autocheck` again picks up every node still without an event; a node with a recorded error is not retried.
- The old tools' replies are byte-for-byte what they were.
- The Lean speed gate passes (or the failure is reported, not hidden).

## Verify
Test budget: targeted files, the fast suite once, one named slow file, the gate once.
- `uv run pytest -q -p no:cacheprovider tests/test_graph.py tests/test_protocol.py` -> all pass (baseline count + the new tests).
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_protocol.py -k step_goals` -> the new slow test passes (needs the Strata workspace; if it is not provisioned the test skips: say so in the hand-back).
- `uv run ruff check arena tests && uv run ruff format --check arena tests` -> clean for the files you touched.
- `uv run pytest -q -p no:cacheprovider` -> the fast suite, once: all pass.
- `uv run arena lean bench --compare benchmark/derived/lean-baseline.json` -> exit 0 (item 11).
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_lean_speed_gate.py` -> passes (item 11).

## Stop and report if
- `arena/campaign.py` no longer has `autocheck` with a ledger-derived queue (ticket 08c or 09 changed it): report how background Lean work is scheduled now.
- The info-tree walk in `context.lean` cannot be copied into a stand-alone script that still elaborates on the Strata fixture (report the Lean error; do not redesign the goal capture).
- Recording a `step_goals` event needs a Lean compile longer than 60 s on the Strata fixture in the background lane.
- The speed gate fails.
- Any existing test needs its assertions changed.
- A decision the ticket does not make seems necessary: stop and ask; do not pick one.


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

Your branch is **`v7/10b-step-goals`**, already created and stacked directly above `v7/10a-graph-core`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/10b-step-goals` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/10b-step-goals -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-10b`.
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
- [ ] Every change is committed on `v7/10b-step-goals`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-10b
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
