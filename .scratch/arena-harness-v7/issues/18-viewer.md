# 18: Viewer "Reasoning & calls" tab

**What to build:** Clicking a node in the candidate-graph viewer shows, in a new "Reasoning & calls" tab, the model's reasoning and the tool calls (with the result as delivered and the untrimmed result) that produced that node, taken from the local journal. A lazy per-node endpoint serves it. For v7 nodes the tab also shows the step-origin line and the hole registry.

**Blocked by:** 17: Replay blob store and `arena replay` (committed below your branch; ticket 04 is below it too).

**Status:** ready-for-agent

**Branch:** `v7/18-viewer` (stacked on `v7/17-replay`)

**Read first:** spec user story 99 and "Replay and viewer"; plan §7b (all of it), §7a "Gaps today"; decisions D12, D24.

## Context: where things are now
- Ticket 04 (committed below your branch) moved the viewer assets (`app.js`, `index.html`, `style.css`, `highlight.js`, `dashboard.*`, `charts.js`, `hub.*`) to `arena/graph_viewer/` as package data, moved the server to `arena/cli/serve.py` (`arena serve`), and deleted `tools/`. "The server" below is `arena/cli/serve.py` and "the assets" are `arena/graph_viewer/`. Confirm with `ls arena/graph_viewer` and `grep -rn "VIEWER_FILES" arena`; if either is missing, stop and report.
- The server: `handler_for(runs, langfuse)` builds the request handler; its `viewer(run_id, rest)` answers `graph.json`, `dashboard.json`, `langfuse.json` and static files listed in `VIEWER_FILES`. `graph_payload(run_id)` builds the graph. The hub serves `/run/<id>/<rest>`; a single-run server serves `/<rest>`.
- `arena/viewer_data.py`: `tool_timeline(directory, start)` pairs `tool_call` and `tool_result` rows of `trace-journal.jsonl` by `tool_call_id` (no node link, text clipped by `_clip` at `TEXT_LIMIT`); `_trace(path)` and `read_jsonl` are the cached readers; `_seconds(ts)` normalizes ms or s timestamps.
- `arena/traces.py` `read_journal(path)` restores delta-compressed request payloads. After ticket 17 each journal row has `turn`, `request_id`; `tool_call` and `tool_result` rows have `tool_call_id`; `tool_result` rows have `result` (delivered), `text` (untrimmed), `trimmed`, `footer`, `delivered_text`; node and ledger events carry `tool_call_id`, `request_id`, `turn` (v6 ledgers have none of these). `arena/replay.py` has `load_run`, `node_turn` (resolves a node to its turn by id or by time) and `split_request`.
- The node panel in the assets' `app.js`: `detail()` renders the side card; `DETAIL_TABS` lists the tabs (`overview`, `diff`, `proof`, `lineage`, `evals`); `renderDetailTab(node, tab)` fills the tab; `openDetail(tab)` opens the dialog. The overview tab shows `node.hypothesis` under the label "Reasoning" (the model's own one-line claim, not its reasoning blocks).
- Existing tests: `tests/test_viewer.py` (`test_endpoints_and_assets`, `test_viewer_scripts_parse`, `test_assets_keep_csp_rules_and_do_not_rebuild_open_selects`). The CSP the server sends is `default-src 'self'; script-src 'self'; style-src 'self'; ...`: no inline scripts or styles may be added.

## What to build
- [ ] 1. In `arena/viewer_data.py` add `node_calls(directory: Path, node: str) -> dict` returning, for one node, `{"node", "turn", "call": {...}, "reasoning": [...], "siblings": [...]} `. Use `arena.replay.node_turn` to find the creating turn and tool call (exact join by `tool_call_id` when the node's event has one; time enclosure for v6). `call` = `{tool_call_id, name, args, delivered, untrimmed, trimmed, footer, is_error}` from the `tool_call` and `tool_result` rows (full text, not clipped; `delivered` is `delivered_text` when present, else the text blocks of `result`; `untrimmed` is `text`). `reasoning` = the list of `thinking` blocks and assistant text blocks of that turn's `response` row (`[{"type": "thinking"|"text", "text": ...}]`). `siblings` = ids of the other nodes the same call created (a batch), ordered by time.
- [ ] 2. A node with no matching call (a run without journal, the original reference node, a harness-made node) returns `{"node": ..., "turn": null, "call": null, "reasoning": [], "siblings": [], "reason": "<one of: no journal, no call matched, harness-made>"}`. Never raise for a missing journal.
- [ ] 3. v7 nodes: when the node's event-log entry has `from_step`/step-origin data and holes (ticket 10a: edges `edited_from`, `filled_from`, `merged_from` with steps; node holes with goal and fills), add `"origin_line"` (the filing line the reply gave, rebuilt from the edge: e.g. the edge kind, parent id and steps) and `"holes"` (`[{id, goal, status, fills}]`) to the result. Read them through the ticket-10a graph reader; v6 nodes simply lack these keys. If the ticket-10a reader has no accessor for them, stop and report.
- [ ] 4. Endpoint in the server: `GET /run/<id>/node/<node>.json` (and `/node/<node>.json` for a single-run server) returning `node_calls(...)` as JSON (`application/json; charset=utf-8`, same headers as the other endpoints). `<node>` allows letters, digits, `.`, `_`, `-` and `#` is not allowed (the viewer sends the node id, not its display number). An unknown run is the existing 404; an id that matches nothing returns 200 with the `no call matched` shape of item 2; an id with other characters is 404.
- [ ] 5. "Reasoning & calls" tab in the assets' `app.js`: add `['calls', 'Reasoning & calls']` to `DETAIL_TABS`; `renderDetailTab` for `calls` fetches `node/<id>.json` lazily (only when the tab opens; show "Loading..." then the result; on a failed fetch show the error text and a Retry button). Render with the escaping helper the file already uses (`esc`): the turn number, the reasoning blocks (each in a `<pre>` with a heading "Thinking" or "Reply"), the tool call (name, pretty-printed args), the delivered result, and a collapsed `<details>` "Untrimmed result" shown only when `trimmed` is true, then the footer. When `reason` is set show it as a muted line. For v7 nodes show `origin_line` above the reasoning and a small table of `holes`. List `siblings` as buttons that select that node (reuse `goBtn`/`data-go`).
- [ ] 6. Keep the existing overview tab's "Reasoning" card; rename its heading to "Stated hypothesis" so the two are not confused. Add the style rules the tab needs to the assets' `style.css` (no inline styles; no media queries for mobile: `test_no_mobile_breakpoints` must still pass).
- [ ] 7. Size guard: results longer than 200 KB per field are cut with a final line `[truncated: N more characters; use arena replay]` (in `node_calls`, so the endpoint never sends a huge body); `untrimmed` and `delivered` are cut independently.
- [ ] 8. Tests (pure unit on a hand-built run directory; reuse the helpers in `tests/test_viewer.py` if present). In `tests/test_viewer.py`: (a) v7-style journal and event log with `tool_call_id` on the node: `node_calls` returns the exact call, its delivered and untrimmed text, the turn's thinking block and the sibling ids in time order; (b) v6-style run (no ids): the join by time picks the call whose window encloses the node's candidate event, and a batch call lists its sibling nodes; (c) a trimmed result has `trimmed: true` and different `delivered` and `untrimmed`; (d) a run without a journal returns the `no journal` shape and does not raise; (e) the endpoint serves `node/<id>.json` for a known run and returns 404 for an id with a `/` or `..`; (f) an oversized result is truncated with the marker line; (g) `test_viewer_scripts_parse` still passes with the new tab code, and the new tab code contains no `innerHTML` assignment from a fetched string that is not passed through `esc` (a source-grep test over the new function, like the neighbouring asset tests do).

## Do NOT
- Do not use Langfuse as a source for this tab; the local journal only (D12, plan §7b). Langfuse stays a secondary view.
- Do not change `arena replay` behaviour or the journal format (ticket 17 owns them); if a field you need is missing, stop and report.
- Do not add inline scripts, inline styles, external fonts or libraries: the CSP forbids them.
- Do not change the graph payload (`graph_payload`/`graph.json`) shape or send reasoning inside it; the data is lazy, per node.
- Do not remove or rename existing tabs.
- Do not render fetched text as HTML: escape everything.
- Do not guess a v6 join when two calls both enclose the node's event: return the earliest-starting call with `reason: "ambiguous"` (the only `reason` value besides those in item 2).
## Acceptance
- (Reviewer, interactive) Starting the viewer on a v6 run (`uv run arena serve <run>`) and clicking a candidate node shows a "Reasoning & calls" tab with the creating tool call, its result, and the turn's reasoning.
- For a batch call each sibling node shows the same call and a button to each sibling.
- The tab loads lazily: opening the page and clicking nodes without opening the tab makes no `node/*.json` request.
- A run with no journal shows "no journal" in the tab, with no error in the console.

## Verify
- `uv run pytest -q -p no:cacheprovider tests/test_viewer.py` -> all pass (baseline + new). No slow file: this ticket changes no Lean or Pi behaviour, and no TS, so `npm test` is not needed.
- Do not start the server (no background jobs); the endpoint is covered by the tests. Also run `uv run python -c` calling `arena.viewer_data.node_calls` on `runs/pi-budget/v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1` for one real node id taken from its `ledger.jsonl` `candidate` rows -> it returns a dict whose `call.name` is a tool name and whose `reasoning` is non-empty.
- `uv run ruff check arena/viewer_data.py arena/cli/serve.py tests/test_viewer.py`, then the same with `uv run ruff format --check` -> clean.
- Last, once: `uv run pytest -q -p no:cacheprovider` (fast suite) -> all pass.

## Stop and report if
- `arena/graph_viewer/` or `arena/cli/serve.py` does not exist (ticket 04 should have created them), or `tools/graph_viewer` still exists.
- `arena/replay.py` (ticket 17) lacks `node_turn`, or the node event has neither a `tool_call_id` nor a timestamp.
- The ticket-10a graph reader has no way to get a node's step origin or holes.
- A real v6 node resolves to no call in the example run (report the node id and its candidate event timestamp).

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

Your branch is **`v7/18-viewer`**, already created and stacked directly above `v7/17-replay`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/18-viewer` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/18-viewer -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-18`.
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
- [ ] Every change is committed on `v7/18-viewer`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-18
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
