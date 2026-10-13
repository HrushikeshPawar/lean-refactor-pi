# 15a: Five-tool Python handlers and reply schema (beside the old tools)

**What to build:** The Python side of the five tools `compile`, `goal`, `search`, `read` and `finish` exists, tested, and reachable through new `arena protocol` actions, while every old tool, protocol action and handler keeps working untouched. All five return one reply schema: `ok`, `facts`, `items` (each with its own error), `handles`, `map`, `stop` and no prose built in Python. `compile` takes one to four drafts, or a `splice`, a `fill` or a `merge`, and returns for each draft its node id, how it was filed, its status, **all** errors with their goals, its holes, its price row and any salvage notice. `goal` answers goals at a hole or line and prices the model's own snippets. `search` and `read` serve the declaration index and the graph. `finish` returns the archive line and the points left and stops the run at once. The model still sees the old tools until ticket 15b registers the new ones; nothing the model sees changes in this ticket.

**Blocked by:** 05b: Agent text: campaign/engine/TS messages moved verbatim, literal lint; 11: Routes, K1 archive, map, stall; 12: Salvage chain and auto-assembly; 13: Price engine and instant token quotes; 14: Declaration index and search (all lower tickets are committed below your branch).

**Status:** done

**Branch:** `v7/15a-tool-handlers` (stacked on `v7/14-search`)

**Read first:** spec "Tool surface" and "Interfaces and contracts" (Implementation Decisions), user stories 43-45 and 46-69, "Testing Decisions" Seam A; plan §4f, §4b table, §4e, §5b (the operations table and "v7 rule" 1-4), §5d, §5f ("All errors at once"), §5h, §12a (#8, #12); decisions D15, D16, D20, D28, D30, D39; `docs/ISSUES-harness-v7.md` #9, #10, #17, #25a, #25b.

## Context: where things are now
- `tools/arena_campaign.py` (reached through the hidden `arena protocol` command in `arena/cli/__init__.py`; ticket 04 may have moved its body, find it with `grep -rn "ACTIONS = (" arena tools`): the JSON protocol, actions `init evaluate probe idea frontier candidate decision source declarations find profile autocheck state submission memory`. This ticket **adds** actions; it removes none (ticket 15c does).
- `arena/campaign.py`: all handlers behind the old actions. This ticket reuses, unchanged: `init`, `autocheck`, `state`, `write_state`, `frontier`, `source_range` with `_split_source_handle`, `_source_target`, `_stdlib_source`, `_roots`, `_externalize_output`. Everything else in it (the idea, probe, evaluate, candidate, find, declarations code) stays as it is.
- The graph core (ticket 10a: node filing, operations, event log, focus, holes), per-step goals (10b), routes and the map (11), salvage and auto-assembly (12), the price engine and instant token quotes (13) and the declaration index and `arena.search.search` / `resolve_handle` (14) are modules under `arena/` below you in the stack. Read their code first; this ticket calls them and does not change them. Lean calls go through the Lean service (08a) and its lanes; goals at a position and a snippet run at a hole come from the LSP lane (08b); the callers use it through `arena/engine.py` (08c).
- `arena/summary.py`: `COMPILE_TOOLS`, `BOOKKEEPING_TOOLS` (by tool name).
- `agent-text/` (tickets 05a and 05b): `numbers.yaml`, `replies/`, `messages/`, the Python renderer and loader (strict: a missing key is an error). Find the layout with `ls -R agent-text` and the loader with `grep -rn "numbers.yaml" arena`.
- Tests: `tests/test_runner.py` fake-provider helpers are for ticket 15b; this ticket's tests are Python-only and use the fixture rows and the fake Lean that tickets 10a to 13 added (`grep -rn "fake" tests/*.py`; do not write a second fake).

## What to build
- [ ] 1. **Reply schema, `arena/reply.py`.** One builder used by all five handlers. JSON shape returned by every new `arena protocol` tool action:
  ```
  {"ok": true, "error": null, "facts": ["..."], "items": [{"ref": "d1", "ok": true, "lines": ["..."], "error": null}],
   "handles": ["n44", "decl:Nat.add_comm"], "map": null, "stop": false}
  ```
  `ok` is false only when the whole request is invalid (then `error` is set and `items` is empty); a bad item sets that item's `ok: false` and `error` and never changes the top-level `ok` (story 66). `stop` is true only in the reply of `finish`. `error` is `{"code": str, "input": str, "valid": [str, ...], "forms": [str, ...]}`: `input` names the bad value, `valid` lists up to 8 valid values (for example existing node ids), `forms` lists the accepted shapes (for example `nN`, `nN.hK`, `nN.sK`, `decl:<name>`). **Every error built anywhere names its bad input and lists the valid forms** (story 64). An argument object with none of the tool's keys, or with only empty values, gets code `empty_arguments` with `valid` = the tool's keys (story 65, plan §12a #27). Python owns this error and its wording; ticket 15b makes the TS side forward the arguments and render malformed or null ones. All prose (fact lines, item lines, error text) is rendered from templates under `agent-text/replies/` and `agent-text/messages/errors.yaml` with the Python renderer from ticket 05a, never from literals in Python (D3). Add the templates you need with **minimal neutral wording**; ticket 16 rewrites them. `facts` and `lines` are final strings.
- [ ] 2. **Pending harness updates and the map.** `reply.py` prepends to `facts` every background update not yet delivered (cross-version results, salvage notices, auto-assembly, focus moves, from the `updates` that `arena/campaign.py` `state()` / `state.json` already hold; tickets 11 and 12 may have extended them), and records the delivered sequence number in a file in the run directory so that a later protocol process does not repeat them. When a reply carries the map (ticket 11's map function) the map goes in `map` as pre-rendered lines, **only when it changed since the last delivered map** (hash stored in the same file), or always for `read view:"map"`. Add protocol action `reset_delivered` that clears the stored map hash and the dedup registry of checkbox 3; the extension calls it after a compaction (ticket 15b), since the earlier text is then gone.
- [ ] 3. **Deduplicated diagnostics (#10).** In compile items, a goal text identical (after the whitespace normalisation of `arena/goalstate.py`) to one already shown in this context is replaced by `same goal as <ref>` where `<ref>` is the error id (`n44.e2`) of its first appearance; a diagnostic message of 120 or more characters that repeats an earlier one shows its first line and `same as <ref>`. The full texts stay on disk (use the existing `_externalize_output` pattern of `campaign.py`, key `<node>`, under the run directory's `diagnostics/`). The registry (text hash to ref) lives in a run-directory file.
- [ ] 4. **`compile` handler, `arena/tools.py` function `compile_tool(theorem, run_id, request) -> dict`.** Request (validated in Python, one place):
  - exactly one of `drafts` (1 to 4 strings, each a complete theorem, a `by` body or a `:=` body, accepted exactly as `normalize_draft` accepts them today), `splice` `{base?, steps, text}` (`steps` is `s4` or `s4-s5`, `base` defaults to the focus), `fill` `{hole, text}` (`hole` is `n30.h2`), `merge` `{base?, take: [{from, step}]}`;
  - optional `base` (a node id; with `drafts` it is the node the variants are made from and the edge is the exact edge ticket 10a defines for that), `from` (audit only: stored as `named_parent`, never used by any rule), `note` (stored on the node), `check` (`"lean"` default, or `"tokens"`).
  - Maximum drafts is read from `agent-text/numbers.yaml` key `compile_max_drafts` (add it with value 4 if absent); ticket 15b's TS schema reads the same value.
  - Combining operations, or none, is an error with code `bad_operation` and `valid` listing the four.
- [ ] 5. **`compile` with `check: "tokens"`.** For each draft, or the splice text, call ticket 13's instant-quote function: return the token count and the delta against the focus (or the replaced steps for `splice`). No Lean, no node is created, no ledger event except a trace row. Items carry `tokens` and `delta`.
- [ ] 6. **`compile` with `check: "lean"`, one item per draft.** Build the text for the operation with ticket 10a's functions (`splice`, `fill`, `merge` build the text from the graph; `drafts` are filed under the focus or `base`). Identical texts inside one call compile once and the later items say `same as <ref>`; a text equal to an existing node's text creates no node and the item points to it (#54, #45). Drafts compile concurrently through the Lean service (08a, callers 08c), never more at once than its model lane allows. Each item carries: the node id, the filing line (`n44 ← n30 fill h2`, `n51 ← focus n41`, `n52 filed as new root`), status `closed`, `sketch` or `broken`, the errors of checkbox 7, the holes with their goals, the price row (ticket 13), per-version results when already known, and the salvage notice when ready (ticket 12). A draft that timed out returns the partial messages the Lean service returns (08a) with status `timeout`. Stragglers do not hold the reply beyond the Lean service's own timeout (open question in the hand-back: plan §4f says "as each finishes", which needs a pending-result channel this ticket does not add).
- [ ] 7. **All errors at once, each with its goal (#9, plan §5f).** A draft that does not compile reports **every** error of the draft, not only the first, each with the goal at the error position. Put this in `arena/tools.py` as `all_errors(...)`. First look in ticket 12's salvage module for a function that already returns every error of a text with goals; if one exists call it and do not write a second. If none exists: pass 0 is the compile of checkbox 6; for each reported error take its step (the top-level step as ticket 10a defines steps; the innermost enclosing step for a nested error), replace that step's body with `sorry`, recompile on the model lane, and collect the errors that now appear (they were hidden behind the earlier ones); repeat, at most `numbers.yaml` key `error_passes_max` passes (add it with value 3). If ticket 12's salvage chain already ran replacement compiles for this draft, reuse the errors it found instead of compiling again. The goal for an error comes from the compile's own goal data at that position (ticket 10b's per-step goals, or the LSP lane's goal at a position from 08b); if none is available the item lists the error without a goal and is not an error itself. Errors are listed in line order with ids `<node>.e<K>` (K from 1, stable across passes) and feed the dedup of checkbox 3. The replacement texts are never filed as nodes and never shown. The draft's status stays the status of pass 0. A draft that compiles, or that timed out, runs no passes. The passes stop at the Lean service's timeout and the item then carries a fact that the error list may be incomplete (template, minimal neutral wording).
- [ ] 8. **Cross-version results inside the call (#17).** After the drafts compile, for the nodes that are closed call the existing `autocheck(name, run_id, max_seconds=...)` with `max_seconds` read from `numbers.yaml` key `cross_version_wait_seconds` (add it with value 10 if absent and list it under Open questions) and attach what finished as facts of this reply; whatever is still running continues in the background and arrives on a later reply through checkbox 2.
- [ ] 9. **`goal` handler `goal_tool`.** Request: `node` with `hole` (`h2`) or `line` (node-relative proof line, 1-based), or `hole: "n30.h2"` alone; optional `try` (list of snippets, at most `numbers.yaml` key `goal_try_max`, add with value 6). Goals come from the Lean service's LSP document lane (08b: goal at a position) at the position; the harness converts node-relative lines to file positions, the model never sees offsets. If the hole or line is not reached because of an earlier error, the item says which error and its line (story 58) instead of an empty list. With `try`, each snippet replaces the hole's `sorry` (or the step at `line`), compiles on the LSP lane without creating a node (08b: snippet at a hole), and returns: closes or not, remaining goals or errors, tokens delta (ticket 13 quote function) and heartbeats delta when measured. One item per snippet with its own error. If the LSP lane has no goal-at-position or snippet-at-hole call, stop and report (see "Stop and report if"); never call the MCP server.
- [ ] 10. **`search` handler `search_tool`.** Request `queries` (list), `kind` (`name` default, `type`, `text`), optional `after` (completions). Calls `arena.search.search` from ticket 14 and renders items from its data: handle, signature preview, location (module and line), `why`, the confusable hint, suggestions on a miss, `dropped` for text. There is no token-cost column (decision 2: the official counter scores any identifier as one token). Each query is one item with its own error (story 66). The `handles` list holds the handles returned. Templates in `agent-text/replies/search.md`.
- [ ] 11. **`read` handler `read_tool`.** Request: exactly one of `handle`, `node`, `hole`; `view` (`source` default, `prices`, `diff`, `outline`, `map`); `against` (a node id, only for `diff`). Handles: `decl:<qualified name>` optionally followed by `:<first>-<last>` (file lines); resolve with ticket 14's `resolve_handle` and read the lines with `campaign.source_range` (up to `numbers.yaml` key `read_source_lines`, add with value 400; the reply's `facts` holds the continuation handle, same form, when cut). Node views: `source` the node's proof text, `prices` ticket 13's price table, `diff` a unified diff of the node against `against` (default its parent) by steps, `outline` the steps with line ranges, goals before and after and the holes, `map` ticket 11's map. Hole: `source` is the goal and fills. A view not valid for the target is an error naming the target and listing the valid views. Every `read` of a `decl:` handle appends `{"kind": "read", "handle", "first", "last"}` to the run's event log (ticket 16's "read so far" list reads these).
- [ ] 12. **`finish` handler `finish_tool`: one call, stops at once (decision 6).** Returns the archive line (ticket 11) and the per-axis points left (the same arithmetic as `axisHeadroom` in `rules.ts`, capped in length by `numbers.yaml`; implement it in Python here; ticket 15b removes the TS copy) and nothing else, with `stop: true`. There is no confirm step, no refusal path and no reminder: the tool is not offered before the allowance reaches the finish fraction (gate in ticket 15b), and one call ends the run.
- [ ] 13. **Operation bookkeeping for the A/B (plan §10 phase 5).** Add to `arena/summary.py` output: `compile_calls`, `compile_calls_with_operation` (calls using `splice`, `fill`, `merge` or `base`), `calls_before_first_compile`, and keep `bookkeeping_and_rejected_pct`, where bookkeeping is a turn whose calls are only `read` with `view` `map` or `outline`, `goal` without `try`, or `finish`. **Add** the new tool names to `COMPILE_TOOLS` and `BOOKKEEPING_TOOLS` and keep the old names in them (the old tools still run until ticket 15c; it removes the old names).
- [ ] 14. **Protocol actions.** In `arena protocol` add `compile`, `goal`, `search`, `read`, `finish`, `reset_delivered`. Each takes `--request-file <path>` (the validated JSON; ticket 15b's extension writes it to a temp file) and prints one JSON line of the reply schema; a Python exception prints `{"ok": false, "error": {...}}` with code `internal_error` and `input` set to the exception's one-line message. Leave every old action and handler in place. Keep `init`, `frontier`, `state`, `autocheck`, `submission`, `memory`.
- [ ] 15. **Seam A tests: reply and compile (new, fast, fake Lean).** `tests/test_tools_reply.py` and `tests/test_tools_compile.py`. They prove: (a) one compile call with two drafts returns two items, one broken with every error and its goal and one closed with a price row, and the top-level `ok` stays true; (b) a request with two operations, no operation, an unknown node and an unknown hole each return an error whose `input` is the bad value and whose `valid` and `forms` are non-empty; `{}` returns `empty_arguments`; (c) duplicate drafts compile once; (d) `splice` and `fill` and `merge` each create exactly the graph edge ticket 10a defines (assert on the event log, not on text); (e) `check: "tokens"` creates no node and calls no Lean; (f) a goal text repeated in two replies shows `same goal as <ref>` the second time and the full text is on disk; after `reset_delivered` it is shown in full again; (g) a pending cross-version update appears once, on the next reply, and not twice.
- [ ] 16. **Seam A test: all errors at once with goals (#9).** In `tests/test_tools_compile.py`, with the fake Lean scripted so that a draft of three top-level steps has an error in each step but the later two errors only appear after the earlier step is replaced by `sorry`: the compile item lists all three errors in line order with ids `.e1`, `.e2`, `.e3`, each with its goal; the status is `broken`; no extra node exists in the event log and no replacement text appears in the reply. A second case with more hidden errors than `error_passes_max` passes returns the errors found and the incomplete-list fact. A third case where one error has no goal data lists it without a goal and the item is still ok.
- [ ] 17. **Seam A tests: goal, search, read, finish.** `tests/test_tools_read_goal_search.py`: (h) `goal` on a hole behind an earlier error names that error; `goal try` returns one priced item per snippet and one bad snippet does not reject the others; (i) `search` with one empty query and one valid query returns an error item and a hit item, and no hit carries a token-cost field; (j) `read` of a `decl:` handle appends a read event, a view not valid for a hole is an error listing valid views; (k) `finish` returns the archive line and points left with `stop: true` on its first and only call. Add to `tests/test_summary.py` one test that the new bookkeeping counters count `compile` calls with and without an operation.

## Do NOT
- Do not touch `packages/arena-pi/` (ticket 15b), and do not delete or edit any old protocol action, handler, idea code, old template, old test or the old tool names in `COMPILE_TOOLS`/`BOOKKEEPING_TOOLS` (ticket 15c). The old tools must keep working; the suite must stay green.
- Do not rewrite model-facing text for quality, shorten it or re-organise it: ticket 16 owns the full rewrite. Add only the templates this ticket needs, with minimal neutral wording, and keep one rule in one place.
- Do not put a model-facing literal in Python (D3). Error codes, keys and ids are not prose; sentences are.
- Never name a kind of proof ("induction", "lemma", "recursion", "simp") in any template, error or fact. The reply states graph position and numbers.
- Do not change the graph core, routes, salvage, price engine, Lean service or search code of tickets 08a to 14. If a function you need is missing, stop and report.
- Do not add a token-cost column for library or search names (decision 2).
- Do not add harness-run suggestion engines, `goal suggest`, remote search or `hover`/`outline` of source files beyond what is specified (D30, D19).
- Do not call the lean-lsp-mcp server from any handler.
- Do not touch `submission/`-style packaging, the viewer, `arena replay` or the blob store (tickets 17 to 19).
- Do not add a confirm step or a refusal path to `finish`.

## Acceptance
- `arena protocol compile` with two drafts returns both results in one JSON reply; the broken one lists every error with its goal; a repeated goal reads `same goal as nN.eK`; a closed one carries its price row and filing line.
- `compile check:"tokens"` returns counts with no Lean and no new node. `splice`, `fill` and `merge` create the exact edges of ticket 10a.
- A bad argument anywhere names the bad input and lists the valid forms; `{}` is reported as `empty_arguments`, never as a missing field.
- `finish` returns `stop: true` on the first call.
- Every old tool and protocol action still works; the old Pi tests pass unchanged.

## Verify
Test budget: targeted files first, the fast suite once at the end. No slow file is needed: this ticket changes no Lean or Pi behaviour.
- `uv run pytest -q -p no:cacheprovider tests/test_tools_reply.py tests/test_tools_compile.py tests/test_tools_read_goal_search.py tests/test_summary.py` -> all pass.
- `uv run arena protocol init ...` (see `tests/test_runner.py` for the init call), then `uv run arena protocol compile --theorem Core.InitsUpdatesComm --run-id smoke --request-file <file with {"check":"tokens","drafts":["by simp"]}>` -> one JSON line with `"ok": true` and an item with `tokens`.
- `uv run ruff check arena/reply.py arena/tools.py arena/summary.py tests/test_tools_reply.py tests/test_tools_compile.py tests/test_tools_read_goal_search.py && uv run ruff format --check arena/reply.py arena/tools.py arena/summary.py tests/test_tools_reply.py tests/test_tools_compile.py tests/test_tools_read_goal_search.py && uv run ty check arena/reply.py arena/tools.py` -> clean.
- At the end, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count plus the new tests; give both numbers).

## Stop and report if
- Any function you need from tickets 10a to 14 is missing or differs from what this ticket assumes (filing a text under the focus, building text for splice, fill and merge, the price row and table, the map, hole goals, per-step goals, salvage notices, an all-errors path, instant token quote, `resolve_handle`). List what you looked for and stop.
- Ticket 08b's LSP lane has no goal-at-position request, or cannot run a snippet at a hole without creating a node (checkboxes 7 and 9). Do not fall back to the MCP server.
- The fake Lean of tickets 10a to 13 cannot script the three-error case of checkbox 16 without changing it. Report; do not write a second fake.
- Adding a template breaks the agent-text consistency test (`tests/test_agent_text.py`) in a way you cannot fix by supplying or deleting your own keys.
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

Your branch is **`v7/15a-tool-handlers`**, already created and stacked directly above `v7/14-search`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/15a-tool-handlers` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/15a-tool-handlers -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-15a`.
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
- [ ] Every change is committed on `v7/15a-tool-handlers`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-15a
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
