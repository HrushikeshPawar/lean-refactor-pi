# 12: Salvage chain and auto-assembly

**What to build:** When a draft fails to compile, the harness quietly tries to turn it into a sketch in the background: it replaces failing steps with `sorry` holes (finer sub-step first, then a header-aware `have ... := sorry`, then the parent block), recompiling up to 6 times. A sketch that elaborates becomes a node linked to the failed draft, and the model learns of it on its next tool result ("p3 salvaged from p2: compiles with 1 hole (line 16)"). Holes are first-class: a hole can be filled by an operation, and when every hole of a sketch has a closing fill the harness assembles the full proof from the cheapest fills, compiles it, records it as a node and tells the model, listing the alternatives. No change to the old tools' own replies; the new results travel on the existing `[arena]` update line.

**Blocked by:** 10a: Graph core: steps, edges, focus, operations; 08c: Lean service callers, tests, speed gate. (Tickets 10b and 11 are also committed below this branch; this ticket uses 11's route filing and `map_view`, and 10b's step-goal job in the autocheck queue, but needs nothing else from them.)

**Status:** ready-for-agent

**Branch:** `v7/12-salvage` (stacked on `v7/11-routes`)

**Read first:** spec sections "Salvage and assembly", "Graph core", "Testing Decisions" (Seam A: salvage outcomes on fixture drafts, auto-assembly), "Further Notes" (salvage needs no size threshold, 54%); plan §5f, §5g (auto-assembly), §5c (holes are first-class); decisions D21, D23, D39.

## Context: where things are now
Names are as of ticket 11. Lean calls in this ticket go through the machine-wide service as ticket 08c left them (background work on the LSP lane): copy the lane and lock pattern of the existing autocheck full-check job; `lean_lock(directory, "background")` below means that pattern. If a name below no longer exists and you cannot find its obvious successor, stop and report.
- `research/v7-probes/` is committed and readable. `research/v7-probes/salvage_replay_v2.py` is the replayed prototype (54% salvaged on 37 failed v6 drafts, median 1 hole): `parse`/`build`/`Node` (already ported to `arena/steps.py` by ticket 10a), `plan` (one replacement round, strategies S2, S3, S4), `render`/`render_node`, `whole_sorry`, `hole_goals`, `kept_frac`, `salvage2` (the driver, `MAX_COMPILES = 6`), with `OPENER`, `HEAD_RE`, `TYPE_RE`. Its compile step is `salvage_replay.compile_text` (error lines from the compile output; `clean` = exit 0 and no error; `unlocated` = nonzero exit with no located error). Port the logic; do not import from `research/`.
- `arena/engine.py:evaluate(name, proof, "probe", lane=...)` compiles a draft with `sorry` allowed on the primary toolchain; its `compat[version]` has `passed`, `diagnostics` (each `{severity, proof_line, file_line, message}`, errors first, capped), `diagnostic_counts`, `outside_target`, and `goals` (the goals at tactic-position `sorry`s: `{proof_line, goals}`, via `instrument_sorries`/`extract_goals`). `campaign._evaluate(name, proof, mode, known, lane)` forwards to it.
- `campaign.autocheck` (background checker, one at a time via `autocheck.lock`; its queue is derived from the ledger; ticket 10b added step-goal jobs). `campaign.state()` builds `updates` (`{seq, text}`) that the Pi extension appends to the next tool result. `kickAutocheck()` in `packages/arena-pi/extensions/arena.ts` starts the checker after tool calls; `arena_probe` kicks it only when a draft became a candidate (`if (result.candidate) ...`, `if (result.drafts?.some(...))`), so a failed draft would never start a salvage.
- Ticket 10a: `graph.Graph.from_history`, `Node.status` (`closed`/`sketch`/`broken`), the `edge` event types `edited_from`/`merged_from`/`filed_under_focus`/`root`, `campaign._file_node` (files the edge, ticket 11 adds the route), `compile_operation` with the hidden protocol action `operation`, `resolve_node_ref`, `steps.split_steps`, `graph.splice_text`, `tests/graph_support.py::FakeRunCase`. Ticket 11: `graph.map_view` with the empty `open` list, `campaign.node_label` (`#N` or `pN`), the update-line mechanism in `state()`.
- A **probe** event (`{"kind":"probe","proof_id","parent","result"}`) is how a draft that is not a closed candidate becomes a node; its `result["goals"]` are the hole goals of a sketch.
- `campaign.record_evaluation(..., origin=..., operation=...)` records a complete proof as a candidate; `origin` values today are `model`, `reference`, `auto_merge`.
- `engine._proof_length(text, statement=None)` is the official token counter; `_proof_length("theorem x : True := " + snippet)` counts exactly the tokens of `snippet`.

## What to build

**A. Holes (pure, in `arena/graph.py`)**
- [ ] 1. `holes(text: str, goals: list[dict]) -> list[dict]`: every `sorry` token of the proof text outside `--` and `/- -/` comments, in order. Each hole: `{"index": k (1-based), "line": proof line (1-based), "column": int, "goal": str | None, "goal_source": "lean" | "stated" | None}`. `goal` comes from the compile result's `goals` entry with the same `proof_line` (the k-th entry on that line when several holes share it), source `lean`; otherwise, for a `have`/`obtain`/`let` line with a stated type (`TYPE_RE` of the prototype), the stated type, source `stated`; otherwise `None`.
- [ ] 2. `Graph.from_history` gives every `sketch` node `holes`: each as above plus `id` = `"<node id>.h<k>"`, `status` (`open` or `filled`) and `filled_by` (a node id or `None`). A hole is filled when some node has an `edge` of type `filled_from` from this node with `operation.hole` equal to the hole id, that node's status is not `broken`, and `operation.text` contains no `sorry` token. That is a **closing fill**; a broken fill leaves the hole open. Several closing fills may exist for one hole; `filled_by` is the cheapest (item 5) and `Hole.fills` lists all of them, cheapest first.
- [ ] 3. Allow two more edge types in `_file_node` and the projection: `filled_from` (exact, `from: [base]`, `operation: {"hole","text"}`) and `salvaged_from` (exact, `from: [failed draft]`).
- [ ] 4. `fill_text(proof: str, hole: dict, text: str) -> str` (pure): replaces the hole's `sorry` (found by `line` and `column`) with `text`. `text` is dedented; its first line takes the token's place; every further line is indented by the indentation of the hole's line, plus 2 spaces when the `sorry` is not the first token on its line. All other bytes are unchanged. A `line`/`column` that does not point at `sorry` raises `ValueError`.
- [ ] 5. `fill_cost(text) -> int`: `engine._proof_length("theorem x : True := " + text)`. The cheapest closing fill has the smallest cost, ties go to the earlier node.
- [ ] 6. `compile_operation` (ticket 10a) accepts `{"type":"fill","hole":"n30.h2","text":str}`: the base is the node in the hole id; it must be a `sketch`, and the hole must exist and be open or filled (a re-fill is allowed). A bad id, a base that is not a sketch or a missing hole raises `ValueError` naming the input and listing the sketch's hole ids with their lines. The proof is `fill_text(...)`, compiled through the same path, and lineage is `filled_from` with `operation: {"hole", "text"}`. Return the old reply plus `node` and `edge` (structured, no sentence).
- [ ] 7. `graph.map_view` fills `open` (item 8 of ticket 11): for every sketch node that is the best node of an archive cell, one row per open hole `{node, label, hole, line, goal}` (`goal` clipped to 120 characters).

**B. The salvage chain (new `arena/salvage.py`)**
- [ ] 8. Port `plan`, `render`, `render_node`, `whole_sorry`, `deepest`, `hdr_end` and the three regexes from `salvage_replay_v2.py` into `arena/salvage.py`, on top of `arena/steps.py` (`Node`, `parse`). Behaviour must be the prototype's: S2 sorries the innermost erroring body or leaf; S3 turns an erroring `have`/`obtain`/`let` header with a stated type into `<head> := sorry` (the next compile checks the type; if the error stays on that line the step is dropped and its parent block sorried), a header without a type drops the step and sorries the parent; S4 only when S2/S3 change nothing sorries the parent block of each erroring step, and a top-level step has no parent so it is sorried itself; replacing every top-level step is a failure (`broken-whole-proof-sorried`).
- [ ] 9. `salvage(name, proof, compile) -> dict` where `compile(text) -> dict` is injected (so tests need no Lean) and returns `{"clean": bool, "error_lines": [proof lines], "unlocated": bool, "result": <the evaluate result>}`. The driver is `salvage2`: at most `MAX_COMPILES = 6` compiles (the first is the draft itself), rounds of `plan` between them. Result: `{"status", "compiles", "rounds": [{"round","errors","strategies"}], "text": sketch text | None, "result": last compile result | None, "kept": float | None}`. `status` is one of `salvaged`, `clean-as-is`, `unparseable`, `broken-unlocated`, `broken-outside-steps`, `broken-no-progress`, `broken-whole-proof-sorried`, `broken-pass-limit`, `unavailable` (the compile raised). There is **no size threshold**: every failed draft is tried (probe: 54% salvaged, flat across sizes).
- [ ] 10. The real compile function, `campaign._salvage_compile(name, text)`: `_evaluate(name, text, "probe", lane="background")` under `lean_lock(directory, "background")`. From `compat[<first version>]`: `clean` = `passed` and no `error` diagnostic; `error_lines` = the `proof_line` of every error diagnostic; `unlocated` = not clean and no error line (a timeout or an error outside the proof counts). A raised `ValueError`/`FileNotFoundError` becomes status `unavailable`; never retried.

**C. Recording and notices**
- [ ] 11. Salvage jobs, derived from the ledger like the full checks: every node with status `broken` that has an `edge` and no `salvage` event. `autocheck` drains them **first** (before full checks, assembly and step goals), one at a time, in the background lane, skipping them when `lean_health.tripped(directory)`. The job appends a `salvage` event `{"kind":"salvage","proof_id","status","compiles","rounds","kept","sketch_id": proof id | None}` and calls `write_state`. A checker killed mid-job leaves no event, so the job is offered again.
- [ ] 12. On status `salvaged`: write the sketch to `proofs/<id>.lean` (`_snapshot`) and, unless that text is already a node, append a `probe` event for it (`parent` = the failed draft, `result` = the final compile result marked `mode: "probe"`, `scored: false`, plus `"salvaged": true`), then `_file_node(..., operation={"type":"salvaged_from","from":[failed id]})` (this also files the route). `sketch_id` is the sketch's proof id (the existing node's, when the text was known). `clean-as-is` and every `broken-*`/`unparseable`/`unavailable` status record only the `salvage` event.
- [ ] 13. Model notice. Add `agent-text/messages/salvage.md` with the key `salvaged` (`{sketch} salvaged from {source}: compiles with {holes} ({lines}).`) rendered with ticket 05a's Python renderer (`grep -rn 'def render' arena/`; follow how its tests register template keys). Code supplies the fragments: `{sketch}` and `{source}` are `node_label` values (`pN`/`#N`), `{holes}` is `1 hole` / `3 holes`, `{lines}` is `line 16` / `lines 16, 22`. `campaign.state()` adds an `updates` item for each `salvage` event with status `salvaged`: `{"seq": index in history, "text": rendered}`. Failures produce no notice. Nothing else reaches the model.
- [ ] 14. In `packages/arena-pi/extensions/arena.ts`, make `arena_probe` call `kickAutocheck()` after every call (both branches, whether or not a draft became a candidate); `arena_evaluate` already does. The checker exits at once when its queues are empty. No other change to the file.

**D. Auto-assembly**
- [ ] 15. Assembly jobs, derived from the ledger: every `sketch` node whose holes all have a closing fill and that has no `assembly` event. `autocheck` runs them after salvage jobs, before full checks. For each hole choose the cheapest closing fill (item 5), apply every chosen fill to the sketch text with `fill_text`, working from the last hole to the first so earlier positions stay valid, and record the proof through `record_evaluation(name, run_id, text, "fast", lane="background", trigger="auto", materialize_live=False, origin="assembly", operation={"type":"merged_from","from":[sketch id, *chosen fill ids],"assembly":true})`. Then append `{"kind":"assembly","sketch","node": proof id | None,"fills":{hole id: fill node id},"alternatives":{hole id: [other closing fill node ids]},"status":"closed"|"broken"|"error","error"?}` (`error` when the compile raised; never retried) and call `write_state`. A broken assembled proof is an ordinary broken node and is salvaged by item 11.
- [ ] 16. Model notice for assembly: add `agent-text/messages/assembly.md` with keys `assembled` (`{node} assembled from {sketch}: {tokens} tokens, score {score}; fills used {used}; alternatives {alternatives}.`) and `assembly_failed` (`Assembly of {sketch} did not compile.`). Fragments built in code: `{used}` is `line 16: #5, line 22: p7`, `{alternatives}` is the same form with each alternative's token cost, or `none`. `state()` adds one `updates` item per `assembly` event with status `closed` or `broken` (not `error`).
- [ ] 17. `origin: "assembly"` nodes are ordinary candidates: they appear in the route table with the route their text gets (never `credited`, since `credited` requires origin `model`), they count for `_best`, and `submission()` may pick them. Do not change `submission()`.

**E. Tests** (unittest style; Seam A unless noted; no Lean unless `@slow`). Put items 19-23 in a new `tests/test_salvage.py` (pure units, and Seam A on `FakeRunCase` from `tests/graph_support.py`).
- [ ] 18. Extend `FakeRunCase.fake_eval` (tests only) so mode `probe` returns what the real evaluator does for the fixtures below: `compat[<version>]` `passed` is false when a line contains the word `bad`, with an error diagnostic for each such line (`proof_line` = its 1-based index); otherwise passed; `contains_sorry` and one `goals` entry (`proof_line`, `goals`) per tactic-position `sorry`; `tokens` as before.
- [ ] 19. Pure salvage on fixture drafts through `salvage(name, proof, compile)` with a scripted `compile` (no Lean): (a) an error inside a nested `have ... := by` body is salvaged in one round by S2, one hole, status `salvaged`; (b) a bad stated type on a `have` header is turned into `... := sorry` (S3), and when the next compile still errors on that line the step is dropped and its parent sorried; (c) S2/S3 change nothing so S4 sorries the parent block; (d) every top-level step failing gives `broken-whole-proof-sorried`; (e) an error outside any step gives `broken-outside-steps`; (f) a compile that never goes clean stops at exactly 6 compiles with `broken-pass-limit`; (g) a draft with no `:= by` header gives `unparseable`; (h) a compile that raises gives `unavailable`; (i) a 100-line draft and a 3-line draft are both attempted (no size threshold).
- [ ] 20. Holes: `holes` on a fixture finds each `sorry` outside comments with its line and column; a `sorry` inside `--` and `/- -/` is ignored; goals attach by line (two holes on one line attach in order); a `have h : T := sorry` hole without a Lean goal gets `stated` source and `T`; `fill_text` keeps unrelated bytes and indents multi-line fills for both a whole-line and a mid-line `sorry`, and rejects a position that is not a `sorry`.
- [ ] 21. Seam A, salvage through the campaign (fake Lean): a failed probe draft is queued; `autocheck` salvages it in the background lane and the ledger then holds a `salvage` event, a sketch `probe` event, an `edge` of type `salvaged_from` from the failed node (exact), and a `route` event; `state()["updates"]` has the rendered notice with the right labels; a second `autocheck` does nothing for it; a job interrupted before its event is offered again; `unavailable` is recorded once and not retried; no notice for a failed salvage.
- [ ] 22. Seam A, holes and fills (fake Lean): `compile_operation` `fill` builds the text, files `filled_from` with the hole id and the fill text; a broken fill does not fill the hole; a bad hole id or a non-sketch base returns an error naming the input and listing the valid hole ids; a re-fill is allowed; `map_view()["open"]` lists the open holes of an archive-best sketch and drops a hole once filled.
- [ ] 23. Seam A, auto-assembly (fake Lean): with two holes and a closing fill for only one, no assembly job exists; once both are closed, `autocheck` assembles with the **cheapest** fill per hole (give one hole two fills of different cost), records a `merged_from` edge from the sketch and the chosen fills (exact, with `assembly: true`) with `origin: "assembly"`, writes an `assembly` event listing the other fill under `alternatives`, and `state()` has the rendered notice; running `autocheck` again assembles nothing; a fill containing `sorry` is not closing; an assembled proof that fails to compile is recorded broken and then gets its own `salvage` job.
- [ ] 24. Seam A, TS contract: the existing Pi-extension tests still pass; add no TS test (the kick change has no pure function to test).
- [ ] 25. One `@slow` Lean test in `tests/test_protocol.py` (Strata fixture, `CampaignCliTests` style): take `FIXTURE.read_text()`, replace `exact updatedStateUpdate (InitStatesSomeMonotone Hold Hinits)` with `exact rfl` (as `test_06_failed_evaluation_reports_aligned_lines` does), run `salvage` with the real compile function and assert status `salvaged`, `compiles <= 6`, at least one `sorry` in the sketch, the statement line unchanged and the sketch compiling with an `ok` result. Paste its output (status, compiles, rounds, holes, seconds) in the hand-back.
- [ ] 26. Run `uv run ruff check` / `uv run ruff format` on every file you touched and `uv run ty check arena/salvage.py arena/graph.py` (fix only diagnostics in lines you wrote).
- [ ] 27. **Speed gate, once, at the end.** This ticket adds background Lean work, so after every other item is done and committed run the gate of ticket 07 **once**: `uv run arena lean bench --full --compare benchmark/derived/lean-baseline.json` (the full gate, about 25 minutes: this is the last Lean ticket, a milestone, owner decision 2026-10-13) and `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_lean_speed_gate.py`, one command at a time, machine otherwise idle. A figure fails only if it exceeds BOTH the relative tolerance (+10% p50, +20% p95) AND the 0.25 s absolute noise floor. Paste both results in the hand-back. If it fails, do not change the baseline or tolerances: stop and report.

## Do NOT
- Do not add a size threshold, a retry loop or an LLM call to salvage. Do not change the strategy order or the 6-compile limit.
- Do not run salvage, assembly or step goals in the model lane or inside the model's tool call. Do not hold the model's Lean lock.
- Do not expose `fill` through a Pi tool (ticket 15a) or change any old tool's reply. The only model-facing output is the two `updates` lines (items 13 and 16), and they come from `agent-text/` templates.
- Do not write sentences in code. Fragments (`1 hole`, `lines 16, 22`, a label) are allowed; the sentence is the template.
- Do not name a kind of proof or a tactic in any template. Position and numbers only.
- Do not change `submission()`, the route table row keys or the stall rule.
- Do not tune the filing threshold `graph.FILING_MIN_SIMILARITY` (0.50) or anything in routes or the stall rule (decision 8).
- Do not run the speed gate more than once, and never as part of the fast suite.
- Do not treat a hole's goal text as an instruction. It is shown only in `map_view` rows and hole listings.
- Do not delete `research/v7-probes/salvage_replay_v2.py` or edit anything under `research/`.

## Acceptance
- With a failed draft in a run, running `uv run arena protocol autocheck --theorem <name> --run-id <id>` (the extension runs the same) ends with a sketch node linked to the failed draft by an exact `salvaged_from` edge, and the next tool result of the run carries a `... salvaged from ...` update line.
- `compile_operation` with a `fill` of the only hole of a one-hole sketch, followed by `autocheck`, yields an assembled node with origin `assembly`, a `merged_from` edge from the sketch and the fill, and an update line listing the alternatives (`none` when there are none).
- A killed checker loses nothing: running `autocheck` again picks up every unfinished salvage and assembly.
- All old tool replies are unchanged.
- The Lean speed gate passes (or the failure is reported, not hidden).

## Verify
Test budget: targeted files, the fast suite once, one named slow file, the gate once.
- `uv run pytest -q -p no:cacheprovider tests/test_salvage.py tests/test_graph.py tests/test_protocol.py` -> all pass (baseline count + the new tests).
- `cd packages/arena-pi && npm test` -> all pass (unchanged count; item 14 changes `arena.ts`).
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_protocol.py -k salvage` -> the slow salvage test passes (it skips if the Strata workspace is not provisioned: say so).
- `uv run ruff check arena tests && uv run ruff format --check arena tests` -> clean for the files you touched.
- The ticket-05a template tests (find them with `grep -rln 'agent-text' tests`; run those files) -> both new templates parse and every placeholder is supplied. `grep -rn 'def render' arena/` finds the renderer.
- `uv run pytest -q -p no:cacheprovider` -> the fast suite, once: all pass.
- `uv run arena lean bench --full --compare benchmark/derived/lean-baseline.json` -> exit 0 (item 27).
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_lean_speed_gate.py` -> passes (item 27).

## Stop and report if
- The prototype `plan` cannot be ported with identical results on the fixtures you write for item 19 (report the case; do not change the strategy).
- The real `evaluate(..., "probe")` result does not carry `proof_line` on error diagnostics or `goals` at holes (report the shape you found).
- `autocheck` no longer owns a ledger-derived queue (ticket 08c or 09 changed it): report how the background work is scheduled now.
- Ticket 05a's renderer or `agent-text/messages/` layout does not exist.
- The speed gate fails.
- Adding the sketch's `probe` event changes an old tool's reply in any way other than the probe count in `frontier` and the numbering of later `pN` labels (sketches are numbered like any probe, so the model can restore one with `arena_candidate pN`; list both effects under Decisions in the hand-back). Anything else: report it; do not suppress the event.
- A decision the ticket does not make seems necessary (for example what to do with a sketch whose holes have no `sorry` token in the text): stop and ask; do not pick one.


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

Your branch is **`v7/12-salvage`**, already created and stacked directly above `v7/11-routes`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/12-salvage` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/12-salvage -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-12`.
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
- [ ] Every change is committed on `v7/12-salvage`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-12
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
