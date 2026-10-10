# 15c: Old tools out: protocol actions, ideas, v6-shape tests

**What to build:** Everything that served the v6 tools is deleted: the old `arena protocol` actions and their handlers in `arena/campaign.py`, the declared-ideas plumbing in the summary, the viewer data, the compaction memory, the viewer panels and the report scripts, the old model-facing templates only they used, and the tests of v6 tool shapes. Old runs' ledgers that still hold `idea` events keep loading. A dead-code sweep and a grep for the old tool names leave nothing behind except historical fixtures. Nothing the model sees changes: ticket 15b already hid the old tools.

**Blocked by:** 15b: TS five-tool surface, MCP server removed (all lower tickets are committed below your branch).

**Status:** ready-for-agent

**Branch:** `v7/15c-old-tools-out` (stacked on `v7/15b-tool-surface`)

**Read first:** spec "Tool surface" and "Out of Scope"; plan §4b table, §8 items 5-6, §12a; decisions D15, D16, D39; `docs/ISSUES-harness-v7.md` #25a.

## Context: where things are now
- After ticket 15b the Pi extension registers only `compile`, `goal`, `search`, `read`, `finish`; nothing in `packages/` calls the old protocol actions. After ticket 15a the new actions `compile goal search read finish reset_delivered` exist beside the old ones `evaluate probe idea candidate decision source declarations find profile`.
- `tools/arena_campaign.py` (reached through the hidden `arena protocol` command in `arena/cli/__init__.py`; ticket 04 may have moved its body, find it with `grep -rn "ACTIONS = (" arena tools`): the JSON protocol and its argparse options.
- `arena/campaign.py`: kept by this ticket: `init`, `autocheck`, `state`, `write_state`, `submission`, `cold_verify`, `frontier` (without ideas), `source_range` with `_split_source_handle`, `_source_target`, `_stdlib_source`, `_roots`, `_context`, `_session`, `_externalize_output`. Expected to be deleted (verify each by grep before deleting): `declarations`, `_declarations`, `_declaration_suggestions`, `_unavailable_reason`, `find`, `_find`, `_indexed_row`, `_unavailable_row`, `_declaration_row`, `_candidate_files`, `_declaration_hits`, `_scan`, `_resolve_declaration_source`, `declaration`, `_declaration`, `_source_declaration`, `_declaration_in_lean`, `record_idea`, `IDEA_STATUSES`, `_current_active_idea`, `_region`, `profile_request`, `candidate`, `probe`, `probe_batch`, `evaluate_request`, `resolve_candidate_ref`, `resolve_probe_ref`, `resolve_parent_ref`, `_model_view`, `_advisory`, `set_decision`.
- `arena/summary.py`: `COMPILE_TOOLS`, `BOOKKEEPING_TOOLS` (ticket 15a added the new names beside the old ones), ideas counting (`ideas`, `idea_attempts`, `ideas_without_attempts`). `arena/viewer_data.py`: `ideas_view`, `"ideas"` in the viewer payload. `tools/graph_viewer/app.js` and `dashboard.js`: idea panels. `arena/memory.py`: `_idea`, `MAX_IDEAS`, the `Ideas:` line, the `arena_candidate` hint.
- Tests of v6 tool shapes: `tests/test_protocol.py`, `tests/test_campaign_lookups.py`, `tests/test_tool_replay.py` (+ `tests/fixtures/proof_tool_replay.json`), and old-tool parts of `test_summary.py`, `test_viewer.py`, `test_traces.py`, `test_memory.py`, `test_campaign.py`, `test_context.py`, `test_lean_session.py`. Ticket 15b already migrated `tests/test_runner.py` and the TS tests.
- `agent-text/` (tickets 05a/05b): templates whose only supplier was the Python code deleted here (idea, probe, evaluate, candidate, find, declarations replies and messages). `tests/test_agent_text.py` fails on a template no code supplies.
- Ticket 14 left `arena/campaign.py` `find`, `declarations` and `source_range` untouched for this ticket; `arena/index.py` and `arena/search.py` replace the first two.

## What to build
- [ ] 1. **Delete the old protocol actions and handlers.** Remove from `arena protocol`: `evaluate probe idea candidate decision source declarations find profile` and their argparse options. Delete from `arena/campaign.py` every function reachable only from them (the list under Context is the expected set; for each, `grep -rn "<name>" arena tools tests packages` must show no remaining user before you delete it) and the module-level constants they alone use (`IDEA_STATUSES`, `MAX_SCAN_FILES`, `MAX_DECLARATION_PAGE_CHARS`, `PROBE_*` if unused). Keep `source_range` and what it needs (ticket 15a's `read` uses it). List each deleted function in the hand-back.
- [ ] 2. **Delete the old model-facing templates and old tool names.** Delete from `agent-text/` every template key whose only supplier was code deleted by checkbox 1 or checkbox 3 (the consistency test of ticket 05a finds them). Remove the old tool names (`arena_probe`, `arena_evaluate`, `arena_candidate`, `arena_state`, `arena_idea`, `arena_profile`, `arena_skill_read`, `arena_find`, `arena_declarations`, `arena_source`, `arena_finish`) from `COMPILE_TOOLS` and `BOOKKEEPING_TOOLS` in `arena/summary.py`, keeping only the five new names, and update the summary tests accordingly. Reading old traces that contain the old names must still work (unknown tool names count as other calls).
- [ ] 3. **Delete ideas everywhere.** `arena/summary.py` (`ideas`, `idea_attempts`, `ideas_without_attempts`, the report line), `arena/viewer_data.py` (`ideas_view`, the `"ideas"` payload key), `arena/memory.py` (`_idea`, `MAX_IDEAS`, the `Ideas:` line, the `arena_candidate` hint; ticket 16 rewrites the rest), `tools/graph_viewer/app.js` and `dashboard.js` and the HTML/CSS for idea panels (remove only the idea panels; no other viewer change, ticket 18 owns the viewer), `tools/run_campaign.py` and `tools/run_experiment_matrix.py` report columns for ideas (or their moved copies; `grep -rln "idea" arena tools packages tests`).
- [ ] 4. **Old ledgers keep loading (test).** Add one test in `tests/test_summary.py` that summarises a ledger containing an `idea` event and an old-named tool call and does not raise; it counts the old call as an other call. Add one in `tests/test_viewer.py` that the viewer payload builds from the same ledger without an `ideas` key.
- [ ] 5. **Delete tests of v6 tool shapes** (plan §8 item 5). Delete `tests/test_protocol.py`. In `tests/test_campaign_lookups.py` keep only tests of functions kept (`LeanNameTests` if `_LEAN_NAME` is still used, `SourceHandleTests` and other `source_range` tests) by moving them into `tests/test_source.py`, then delete the file. Keep from `tests/test_tool_replay.py` the tests that exercise `source_range` path aliases (move to `tests/test_source.py`), delete the rest and `tests/fixtures/proof_tool_replay.json` if nothing uses it. Update `tests/test_summary.py`, `test_viewer.py`, `test_traces.py`, `test_memory.py`, `test_campaign.py`, `test_context.py`, `test_lean_session.py` for renamed tools and removed ideas, asserting behaviour rather than copied sentences. Confirm the two known slow failures are gone: both tests were rewritten or deleted in ticket 15b (`grep -n "active_ideas\|without_rewriting_history" tests/test_runner.py` shows only the rewritten versions).
- [ ] 6. **Dead-code sweep.** Run `uv run ruff check --select F401,F841 arena tools tests` and fix what your deletions left unused. Run `grep -rn "arena_probe\|arena_evaluate\|arena_candidate\|arena_state\|arena_idea\|arena_profile\|arena_skill_read\|arena_find\|arena_declarations\|arena_source\|arena_finish\|lean_goal\|mcp__arena_lean" arena tools packages tests agent-text` and report any remaining hit (the only allowed hits are inside historical fixtures under `tests/fixtures/` that replay old runs, and `docs/`). Also run `grep -rn "ideas\b" arena tools packages tests agent-text` and report what is left.

## Do NOT
- Do not delete `source_range`, `autocheck`, `state`, `submission`, `cold_verify`, `frontier`, `init`, or the `memory` action, or any new handler of ticket 15a.
- Do not delete `arena/index.py`, `arena/search.py`, `arena/reply.py`, `arena/tools.py`.
- Do not rewrite model-facing text for quality: ticket 16 owns it. Only delete templates this ticket orphans.
- Do not change any viewer behaviour except removing the idea panels; do not touch `arena replay` or the blob store (tickets 17 to 18).
- Do not change the graph core, routes, salvage, price engine, search or Lean service code.
- Do not keep a deleted tool, action or function as an alias.
- Do not edit `tests/fixtures/` files that replay historical runs, except removing `tests/fixtures/proof_tool_replay.json` when nothing uses it.

## Acceptance
- `uv run arena protocol --help` (or the action list in the module) shows only `init`, `frontier`, `state`, `autocheck`, `submission`, `memory`, `compile`, `goal`, `search`, `read`, `finish`, `reset_delivered`.
- The grep of checkbox 6 finds nothing outside historical fixtures and `docs/`. `tests/test_protocol.py` and `tests/test_campaign_lookups.py` no longer exist.
- A ledger from a v6 run (with `idea` events and old tool names) summarises and loads in the viewer payload without error.
- The agent-text consistency test passes (no orphan template).

## Verify
Test budget: targeted files first, the fast suite once at the end. No slow file: this ticket deletes code that nothing reachable from Pi calls.
- `uv run pytest -q -p no:cacheprovider tests/test_source.py tests/test_summary.py tests/test_viewer.py tests/test_traces.py tests/test_memory.py tests/test_campaign.py tests/test_context.py tests/test_agent_text.py` -> all pass.
- `grep -rn "arena_probe\|arena_evaluate\|arena_candidate\|arena_state\|arena_idea\|arena_profile\|arena_skill_read\|arena_find\|arena_declarations\|arena_source\|arena_finish\|mcp__arena_lean" arena tools packages tests agent-text` -> no output except historical fixtures under `tests/fixtures/`.
- `uv run ruff check --select F401,F841 arena tools tests` -> clean; `uv run ruff check <touched files> && uv run ruff format --check <touched files> && uv run ty check <touched python files>` -> clean.
- At the end, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count minus deleted tests plus new ones; give both numbers); `cd packages/arena-pi && npm test` -> all pass, unchanged count.

## Stop and report if
- Deleting a function in checkbox 1 breaks a test that proves something about a kept behaviour (graph, ledger, submission). Stop before deleting; list the test.
- The old protocol actions are used by something outside `arena/`, `tools/`, `packages/` and `tests/`.
- A function you expected to delete still has a caller in code of tickets 10a to 15b. List the caller and keep the function.
- The viewer's idea panels share code with other panels so that removing them changes other behaviour.
- You run out of context. Commit what is finished, set nothing to `needs-review`, and report which checkboxes remain.

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

Your branch is **`v7/15c-old-tools-out`**, already created and stacked directly above `v7/15b-tool-surface`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/15c-old-tools-out` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/15c-old-tools-out -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-15c`.
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
- [ ] Every change is committed on `v7/15c-old-tools-out`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-15c
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
