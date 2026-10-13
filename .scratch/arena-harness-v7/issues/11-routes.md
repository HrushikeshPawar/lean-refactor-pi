# 11: Routes, K1 archive, map and stall detector

**What to build:** Every node gets a route the moment it is filed, computed in Python from the proof's shape (step skeleton mixed 50/50 with step-hash overlap, with hysteresis), with no Lean, no worker and no queue; the route is frozen once filed. The graph keeps an archive whose cell key is (route, depth bucket, closed or sketch), each cell holding its best node, and a map view of the archive, the best node and the recent nodes. When the lineage of the last improvement goes 12 nodes without improving, the harness moves the focus to another archive cell and says so in one fact line that reaches the model through the existing `[arena]` update line. The LLM route extraction and everything around it (background worker, queue, locks, Lean script) is deleted; the route table the old tools and reports read keeps its shape.

**Blocked by:** 10a: Graph core: steps, edges, focus, operations. (10b and everything below are committed below your branch too.)

**Status:** done

**Branch:** `v7/11-routes` (stacked on `v7/10b-step-goals`)

**Read first:** spec sections "Graph core" (routes, archive cells, stall detector), "Testing Decisions" (Seam A: route assignment and hysteresis, archive cells, the map, the stall detector), "Further Notes" (probe evidence); plan §5d, §5e, §5j, §2b (rule 1: no literal reaches the model from code); decisions D22, D27, D28, D29, D39.

## Context: where things are now
Names are as of ticket 10b. If a name below no longer exists and you cannot find its obvious successor, stop and report.
- `arena/routes.py` (641 lines): v6 route fingerprints. It holds the vocabulary fingerprint (`fingerprint`, `kernel`, `family`, `idf`, `similarity`, `assign`, `assign_by_text`, `label`, `short_label`, `vocabulary`, `exemplars`, `file_attempt`, `incomplete`, `empty`, `strategy`, the `WEIGHTS`/`PLUMBING` tables), and, separately, the **ledger readers** `attempt_results`, `route_table`, `progress`, `routes_text`, `routes_detail_text` and the constants `ROUTE_DEPTH`, `STALE_STREAK`, `MAX_SKELETON`. It also still has `proof_body` and `_heads` (top-level tactic heads), which this ticket keeps.
- Readers of the route table that must keep working unchanged: `arena/memory.py` (`routes_text`), `arena/summary.py` (`route_table`, `progress`, `routes_detail_text`), `arena/viewer_data.py` and `tools/serve_candidate_graph.py` (`route` events), `arena/campaign.py` (`route_table`, `_route_progress`, `frontier`, `graph_state`), `tools/run_campaign.py`, and the Pi extension (`packages/arena-pi/extensions/rules.ts` `RouteRow`, `routesText`, `sinceRefusal`, `staleNotice`, and the finish tool in `arena.ts`), which read the row keys `route, label, short_label, original, attempts, best_candidate, best_proxy, verified, depth, new_states, min_holes, stale_streak, compiled, explored, stale, credited, skeleton`.
- `arena/route_features.py` + `arena/lean/route.lean`: kernel-term features read by a cold Lean run (120 s timeout).
- `arena/campaign.py`: `_route_features`, `_record_route_later`, `_worker_running`, `_route_queue`, `_route_worker`, the constants `ROUTE_SLOTS`, `ROUTE_EXTRACT_GB`, `ROUTE_WAIT_SECONDS`, `REFERENCE_TRIES`, `REFERENCE_ROUNDS`, `REFERENCE_RETRY_SECONDS`, `_origin`, `_yield_to_lean_session`, `_room_for_extraction`, `_record_route`; calls to `_record_route_later` in `init` and in `record_evaluation`; `graph_state` reads `route` events into `nodes[...]["route"]`.
- Ticket 10a added: `graph.Graph.from_history`, `Node` (`status`, `score`, `depth`, `edge`, `steps`), the `edge` and `focus` events (ticket 10b added `step_goals`), `campaign._file_node` (called after a compile result is recorded, under `graph.lock`), `_settle_focus`, the `ContextVar` for the batch focus, `graph.similarity`, `steps.split_steps`, `tests/graph_support.py::FakeRunCase`.
- `research/v7-probes/` is committed and readable. `research/v7-probes/route_replay.py` (functions `skeleton`, `steps`, `sim_skel`, `sim_set`, `cluster`, `line_diff`) and `research/v7-probes/archive_probe.py` (functions `dbucket`, `build` for the K1 key and quality `q`, `archive_series`, `descends`, `fires` for the stall rule, `closest_prev`) are the replayed prototypes whose numbers are in the plan (route mix stable 0.991; K1 median 9 cells; m=12 cuts no final best). Port the logic; do not import from `research/`.
- `state()` in `arena/campaign.py` builds `updates` (`{seq, text}`) that the Pi extension appends to the next tool result; the stall fact line goes there.
- `tests/test_routes.py` (776 lines) has tests of the removed fingerprint code and tests of the kept readers (`LedgerTests.test_route_table_counts_attempts_and_best_proxy`, `test_routes_text_names_each_route`, `test_short_label_is_compact_and_the_model_text_has_no_label`, and `DepthTests`).

## What to build

**A. Synchronous routes**
- [ ] 1. In `arena/routes.py` add the v7 signature and assignment (pure, no Lean), borrowing `skeleton`, `steps`, `sim_skel`, `sim_set`, `cluster` and `line_diff` from `route_replay.py`:
  - `signature(proof: str) -> dict`: `{"skeleton": [...], "steps": [sorted 10-hex hashes]}`. The skeleton is `_heads(proof_body(proof))` (top-level tactic heads, arguments dropped). Step hashes are the sha1 (first 10 hex digits) of each nonblank body line with whitespace collapsed and every name matching `\b(h[A-Za-z0-9_'₀-₉]*|this|H[A-Za-z0-9_'₀-₉]*|ih[A-Za-z0-9_']*)\b` replaced by `_h` (as `route_replay.steps` does); lines equal to `by` are skipped. No lemma names enter the signature.
  - `similarity(a, b) -> float`: `0.5 * SequenceMatcher(None, a.skeleton, b.skeleton, autojunk=False).ratio() + 0.5 * Jaccard(a.steps, b.steps)`; two empty skeletons count as 1.0 and two empty step sets as 1.0.
  - Constants `JOIN = 0.60`, `OPEN_BELOW = 0.35`, `MARGIN = 0.10`, `SMALL_EDIT_LINES = 3`, `MAX_ROUTES = 12`.
  - `assign(members: dict[str, list[dict]], sig: dict, parent_route: str | None, parent_line_diff: int | None) -> dict`: returns `{"route", "new", "similarity", "runner_up": {"route","similarity"} | None}`. Rules, in this order: no routes yet -> `r1`, new. An edit of at most `SMALL_EDIT_LINES` lines from its parent (`parent_line_diff <= 3`, parent has a route) -> the parent's route, never new. Otherwise each route's score is the **maximum** similarity over its members (single link); `top` is the best score, `second` the next. `top >= JOIN` -> join the best. `top < OPEN_BELOW` -> open a new route `r<k+1>`. Grey band: join the best when `top - second >= MARGIN` or the parent's route is the best or the node has no parent route; otherwise stay in the parent's route. **Cap (decision 8):** when `MAX_ROUTES` routes exist, a node that would open a new route (route 13 and later) joins the best-scoring route instead; routes stay frozen once filed, so no merging of routes after the fact.
  - `line_diff(a: str, b: str) -> int`: as in `route_replay.line_diff` (proof-body lines; 99 when the line counts differ by more than 3 so such a pair is never a small edit).
- [ ] 2. In `campaign._file_node` (ticket 10a), after the `edge` event is appended and still under `graph.lock`, append the route event for the same node: `{"kind":"route","proof_id","route","new","similarity","runner_up","assigned_by":"signature","parent":proof_id|None,"holes":<count of sorry tokens in the text>,"credited":bool,"label":route,"short_label":route,"attempt_kind":"candidate"|"probe"}`. The route's members are all earlier nodes with a `route` event (every status, broken ones included; the replay did the same). `parent` is the first id of the edge's `from`. `credited` is true when the node opened a new route and its origin is `model`. It happens in the same call as filing: no subprocess, no queue file, no lock other than `graph.lock`. Old ledgers that lack the new fields keep reading (see item 4).
- [ ] 3. Delete the LLM route extraction and its machinery: `arena/route_features.py`, `arena/lean/route.lean`, `tests/test_route_features.py`; in `arena/campaign.py` the functions and constants listed under Context (`_route_features` ... `_record_route`) and both calls to `_record_route_later`; in `arena/routes.py` the fingerprint, kernel and label code listed under Context (keep `proof_body`, `_heads`, `MAX_SKELETON`, `attempt_results`, `route_table`, `progress`, `routes_text`, `routes_detail_text`, `ROUTE_DEPTH`, `STALE_STREAK`). Also remove the module docstring text that describes the kernel fingerprint and replace it with three sentences on the v7 signature. `lean_session.memory_pressure` and `_available_gb` stay (other code uses them). Run `grep -rn 'route_features\|route\.lean\|_record_route\|_route_worker\|ROUTES_INLINE\|ROUTE_SLOTS' arena tools tests packages --include='*.py' --include='*.ts'` and fix every hit; it must be empty. The route files `route-queue.jsonl`, `route-worker.lock`, `route-extract.lock`, `route.lock` are no longer created.
- [ ] 4. Adapt `routes.route_table` to the new event, changing only what must change: `credited` is `bool(event.get("credited")) and earned and kind != "reference"` (delete the later "a later compiled proof credits a route" block, and the legacy default for events without `credited`); `skeleton` is `False`; `min_holes` comes from the event's `holes` as today (`"holes" in event`). `depth`, `new_states`, `stale_streak`, `compiled`, `explored`, `stale`, `original` and the reference/`auto_merge` handling stay as they are. Row keys and `progress`, `routes_text`, `routes_detail_text` output formats do not change (the Pi extension and the reports read them until ticket 15c).
- [ ] 5. In the packet and tool text, the sentence that says routes are fingerprinted from complete proofs and drafts with holes are not is now false. `grep -rn 'fingerprint' agent-text packages/arena-pi arena --include='*'` (tickets 05a and 05b moved the text into `agent-text/`; the same sentence is in the `arena_probe` description in `packages/arena-pi/extensions/arena.ts` or its template). Delete only the clause that talks about routes and fingerprinting, nothing else, and update the byte-identical packet fixture or test that pins it. If the clause is in more than 3 places, stop and report.

**B. Archive, map and stall detector (pure, in `arena/graph.py`, plus wiring)**
- [ ] 6. `depth_bucket(depth: int) -> str`: `"0-2"`, `"3-7"`, `"8-15"`, `"16+"`. `quality(node) -> float | None`: the node's `score` when scored; `0.0` for a closed node with no score; `-1.0 - <number of sorry tokens>` for a sketch; broken nodes have none and are never archived (probe's q, `archive_probe.build`).
- [ ] 7. `Graph` gains `route` (from `route` events) and the archive: `archive(graph) -> list[Cell]` where a cell is keyed `(route, depth_bucket(node.depth), "closed" | "sketch")` (D27), keeps its best node (highest `quality`, ties to the earlier node) and counts `visits` (every non-broken node that falls in the cell). Cells are ordered by first appearance and get letters `A`, `B`, ... in that order (the letters are stable because cells are only added). Add `keeps(graph)`: nodes in order whose score is strictly above every earlier scored node's (the first scored node, normally the reference, is a keep).
- [ ] 8. `map_view(graph) -> dict` with exactly these keys: `best` (`{node, label, score, tokens, heartbeats, versions}` or `None`), `archive` (rows `{letter, route, depth_bucket, status, node, label, score, visits}`), `recent` (the last 8 nodes: `{node, label, edge, from, status, score}` where `status` is `keep`, `discard` or `broken`), `effort` (`[]`) and `open` (`[]`). The last two are filled by tickets 13 and 12; create them empty and say so in the docstring. `label` is `#N` for a node with a candidate event, else `pN` (add `campaign.node_label(history, proof_id)` if ticket 10 did not). Expose it as the hidden protocol action `map` (JSON) in the action table; no model-facing rendering (ticket 15).
- [ ] 9. Stall detector, replaying the probe's rule (`archive_probe.fires`): `stall_fire(graph, m) -> dict | None`. Let `root` be the latest keep (the first node when there is none). The counter is the number of nodes (any status) recorded after `root` that descend from it (following the first parent of `edge.from` up to `root`); it resets to 0 on a keep and on a fire. It fires when the counter reaches `m` and returns `{"root", "count"}`; nodes that do not descend from `root` do not count. `m` is `ARENA_STALL_M` (default 12; a positive integer, anything else raises `ValueError` at the call).
- [ ] 10. Stall target, `stall_target(graph, fired, mode) -> proof_id | None`, `mode` from the environment switch `ARENA_STALL_TARGET` in `best_other_cell`, `least_visited`, `map_only`. The default is `best_other_cell` (decision 8); the switch exists only so the owner can A/B the three modes; an unknown value raises `ValueError`. Candidate cells are the archive cells whose best node is not `fired["root"]` and does not descend from it. `best_other_cell` picks the cell whose best node has the highest `quality`; `least_visited` the fewest `visits` (ties: higher `quality`); `map_only` and an empty candidate list return `None` (no move).
- [ ] 11. Wiring in `campaign.py`: after `_settle_focus` (ticket 10a) in the same places, call `_check_stall(directory)`: project the graph, run `stall_fire`, and on a fire with a target append `{"kind":"focus","proof_id":target,"reason":"stall","root":fired_root,"cell":<letter>,"visits":<n>}`. Because the counter resets on a fire, replaying the whole ledger gives the same fires as the live run (add a test).
- [ ] 12. The fact line. Add the template (ticket 05a's layout: `agent-text/messages/phase.md`, one key `stall_focus`) `Focus set to {label} (archive {letter}, {score}, {visits} nodes in its region).` with neutral wording; `{score}` is the number, or `sketch`. Render it with ticket 05a's Python renderer (find it with `grep -rn 'def render' arena/`; call it the way its own tests do; register the key in the template tests exactly as ticket 05a requires). `campaign.state()` adds one `updates` item per `focus` event with reason `stall`: `{"seq": <index in history>, "text": <rendered line>}`. The Pi extension already appends new `updates` to the next tool result; do not touch `arena.ts`. The old tools still default to `_current`, so for them the line is information only; say so in the hand-back.

**C. Tests** (unittest style; Seam A with `FakeRunCase` unless noted)
- [ ] 13. Delete the tests of the removed code in `tests/test_routes.py` (the fingerprint, kernel, skeleton, recording, queue and reference classes, and `test_record_route_*`), keep and adapt `LedgerTests` and `DepthTests` to the new event shape (build events by hand), and replace `ProtocolLogicTests.test_only_a_compiled_candidate_is_queued_for_a_route` with the tests below.
- [ ] 14. Pure units, route signature on fixture proofs: two proofs one line apart score above `JOIN`; a rewrite with other tactic heads and other lines scores below `OPEN_BELOW`; renaming `h1` to `h2` does not change the step hashes; an empty proof does not crash.
- [ ] 15. Route assignment and hysteresis: the first node is `r1`; a node at or above 0.60 joins (single link: it joins through a distant member of a route); one below 0.35 opens a new route; in the grey band it joins the best route only with a margin of 0.10 or when the parent is there, otherwise it stays in the parent's route; an edit of at most 3 lines from its parent never opens a route even when its similarity is below 0.35; with 12 routes the 13th candidate joins the closest one; the route event never changes once written (filing more nodes leaves earlier `route` events byte-identical).
- [ ] 16. Synchronous and local: with `subprocess.Popen` and `lean_session` patched to raise, `record_evaluation`, `probe` and `compile_operation` still write the `route` event before returning; no `route-queue.jsonl` is created; the route table of that ledger has the expected attempts per route and `credited` only for the route a model node opened (the reference's route is `original`).
- [ ] 17. Archive: depth buckets at the boundaries 2/3, 7/8, 15/16; a cell keeps its best node and counts visits; a broken node never enters a cell; a sketch and a closed node of the same route and bucket are different cells; letters are stable as cells are added.
- [ ] 18. Stall: it fires at the 12th non-improving node descending from the last keep (not the 11th); a keep resets it; nodes in another lineage do not count; it fires once and then restarts at 0; replaying the full history gives the same fires as incremental checks; `ARENA_STALL_M` changes the threshold and an invalid value raises; the three target modes each pick as specified (with fixture cells), `map_only` and "no other cell" make no move and append no `focus` event; the fire appends a `focus` event with reason `stall` and `state()` returns the rendered update with the right `seq`.
- [ ] 19. Map: the `map` action returns exactly the keys of item 8; `recent` has at most 8 rows with `keep`, `discard`, `broken` statuses; `best` is `None` before any scored node.
- [ ] 20. Run `uv run ruff check` / `uv run ruff format` on every file you touched and `uv run ty check arena/routes.py arena/graph.py` (fix only diagnostics in lines you wrote).

## Do NOT
- Do not keep any Lean call, queue, worker, memory wait or lock in route assignment, not even "optional enrichment" (plan §5j allows one later as a secondary label; it is out of scope).
- Do not show routes, archive cells, the map or the stall line to the model any other way than the `[arena]` update line of item 12. No `read view:"map"`; that is ticket 15a.
- Do not change the route table row keys, `progress`, `routes_text` or `routes_detail_text` formats, or the finish tool's use of them (D39: old tools go in ticket 15c). Do not delete the credited concept from the table; D28 retires it with the finish tool in tickets 15b and 15c.
- Do not use the leading score axis in the archive key (D27: probe showed it unstable) and do not add a depth cap (the best of one run was at depth 46).
- Do not change the stall rule to any-node scope or another m without new data (probe: only the lineage-scoped m=12 cuts no final best).
- Do not name a kind of proof, a lemma or a strategy in any text.
- Do not tune the filing threshold `graph.FILING_MIN_SIMILARITY` (0.50) from ticket 10a, and do not change the route-13 cap rule or the stall default (decision 8).
- Do not touch `arena/merges.py`, `graph.merge_text` or the auto-merge worker.

## Acceptance
- After `record_evaluation` or `probe` returns, the ledger already holds the node's `route` event; the route of a one-line edit equals its parent's.
- `uv run arena protocol map ...` (or the equivalent hidden action) prints the archive with at most about a dozen rows for a fixture run, and the best node.
- Twelve consecutive non-improving nodes under the last keep make the next tool result carry a `Focus set to ...` update, and the ledger holds `focus` with reason `stall`.
- `grep -rn 'route_features\|route\.lean' arena tools tests packages` finds nothing.
- The viewer, `arena summary` and the Pi finish tool still read the route table (existing tests for them pass).

## Verify
Test budget: targeted files, then the fast suite once. This ticket removes Lean-based route extraction and adds no Lean work, so there is no slow file and no speed gate.
- `uv run pytest -q -p no:cacheprovider tests/test_routes.py tests/test_graph.py tests/test_protocol.py -v` -> all pass; paste the passing test names for items 14, 15, 17, 18 and 19 in the hand-back (give the test counts before and after: the deleted route tests lower it, the new ones raise it).
- `cd packages/arena-pi && npm test` -> all pass (unchanged count; item 5 may touch a template or fixture the TS tests read).
- `uv run ruff check arena tests && uv run ruff format --check arena tests` -> clean for the files you touched.
- `grep -rn 'route_features\|route\.lean\|_record_route\|_route_worker\|ROUTE_SLOTS' arena tools tests packages --include='*.py' --include='*.ts'` -> no output.
- `uv run pytest -q -p no:cacheprovider` -> the fast suite, once, at the end: all pass.

## Stop and report if
- Ticket 10a's `_file_node`, `Graph` or the `focus` event do not exist as described.
- Removing a name listed in item 3 breaks something other than the files listed (a hit in `tools/`, `viewer_data.py` or the extension you cannot trace): report the hit; do not keep the old code "just in case".
- A reader of the route table needs a row key the new events cannot supply.
- The fact-line template or the renderer from ticket 05a does not exist or cannot take a numeric `{score}` placeholder.
- A decision the ticket does not make seems necessary (for example what the stall target does when two cells tie exactly): stop and ask; do not pick one. The items above name the tie rules that exist.


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

Your branch is **`v7/11-routes`**, already created and stacked directly above `v7/10b-step-goals`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/11-routes` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/11-routes -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-11`.
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
- [ ] Every change is committed on `v7/11-routes`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-11
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
