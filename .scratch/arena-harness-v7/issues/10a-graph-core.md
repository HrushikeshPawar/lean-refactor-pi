# 10a: Graph core: steps, edges, focus, operations

**What to build:** Every compiled draft, closed, sketch or broken, becomes a node with a stable id `n1`, `n2`, ... in the run's one append-only ledger. Each node carries a typed lineage edge that records how it came to exist: exact when a graph operation (draft against a base, splice, merge) built its text, or `filed_under_focus` / new root for a free-text draft. A separate focus pointer says which node a free-text draft is filed under. Proofs are split into top-level steps (`s1`, `s2`, ...) so operations can name them. The five-tool surface does not exist yet, so the old tools (`arena_probe`, `arena_evaluate`, `arena_candidate`, ...) keep their exact replies and run on top of the new model, and the operations are reachable only through one hidden protocol action. (Per-step goals are ticket 10b.)

**Blocked by:** 04: Move the remaining tools into the CLI; arena doctor; 05b: Agent text: campaign/engine/TS messages moved verbatim, literal lint. (Tickets 06-09 are committed below this branch too.)

**Status:** ready-for-agent

**Branch:** `v7/10a-graph-core` (stacked on `v7/09-scheduler`)

**Read first:** spec sections "Graph core", "Interfaces and contracts" (the `compile` request), "Testing Decisions" (Seam A) and "Further Notes" (probe evidence); plan §5a, §5b, §5c, §10 phase 3; decisions D7, D16, D23, D27 (for context only), D28, D39.

## Context: where things are now
Names are as of ticket 09. Ticket 04 may have moved `tools/arena_campaign.py` into `arena/cli/`; `grep -rn '"autocheck"' arena tools` finds the action table wherever it lives. If a name below no longer exists and you cannot find its obvious successor, stop and report.
- `arena/campaign.py` is the run's state, backed by `ledger.jsonl` (one JSON object per line, appended by `_append` under `flock`, read by `events(directory)`). Event kinds today: `init`, `candidate`, `probe`, `evaluation`, `derivation`, `current`, `idea`, `idea_update`, `decision`, `merge_check`, `route`, `profile`, `cold_verification`.
- A **candidate** is a proof text that was evaluated (`record_evaluation`, id = `sha256(name + "\0" + proof)`, written to `proofs/<id>.lean` by `_snapshot`). A **probe** is a draft compiled with `sorry` allowed (`probe`, `probe_batch`, `_compile_probes`); only drafts that do not become candidates get a `probe` event. The model addresses them as `#N` (order of `candidate` events) and `pN` (`_probe_numbers`).
- `record_evaluation(name, run_id, proof, mode, parents, hypothesis, origin, merge, materialize_live, idea_id, lane, trigger, precomputed)` writes the `candidate` event with `parents` = the model's named parents, else `[_current(history)]` (the last materialized candidate, set by `current` events). It writes a `derivation` event when a known candidate is re-submitted with different named parents.
- `probe(name, run_id, proof, idea_id, parent)` uses `parent_id = resolve_parent_ref(...)  or _current(history)`; `probe_batch` fixes the parent for the batch.
- `candidate(name, run_id, reference)` restores a candidate or probe into the shadow project (writes a `current` event).
- `merge_once` / `merge_batch` build harness merges with `graph.merge_text` and call `record_evaluation(..., origin="auto_merge", merge={...})`.
- `graph_state(run_id)` builds the viewer's node list from the ledger (`parents`, `children`, `route`, `status`, ...). `_summaries(history)` is the per-candidate score and status table (`full` = verified on every version, `primary`, `fail`). `state()` / `write_state()` publish `state.json`, whose `updates` list (`{seq, text}`) the Pi extension appends to the next tool result.
- `arena/goalstate.py` (`closed`, `signature`, `parts`) classifies a compile result. `arena/graph.py` has `common_base`, `edit_fingerprint`, `merge_text`, `ranked_frontier` (all still used; keep them).
- `research/v7-probes/salvage_replay_v2.py` has a tested step parser (`hdr_index`, `build`, `parse`, `Node`) and `research/v7-probes/graph_audit.py` the difflib line similarity (`lines_of`, `ratio`) used for "measured parent". `research/v7-probes/` is committed and readable. Borrow the logic; do not import from `research/`.
- `tests/test_protocol.py::ProtocolLogicTests` is the fake-Lean fixture for the campaign (it patches `campaign.evaluate`, `problem`, `versions`, `materialize`, `validate_proof`, `ROOT`).

## What to build

**A. Steps (pure, new module `arena/steps.py`)**
- [ ] 1. Create `arena/steps.py` with the proof step structure, ported from `salvage_replay_v2.py` (`hdr_index`, `build`, `parse`, `Node`) without changing its behaviour: a proof is parsed into a tree of `StepNode(start, end, parent, kids)` (0-based line indexes into `proof.split("\n")`, `end` exclusive). The header is the first line whose stripped text ends with `:= by`; steps are the lines at the body's minimum indentation (comment-only lines never start a step). `parse(lines)` returns `None` when there is no header or no step.
- [ ] 2. In the same module add `@dataclass(frozen=True) class Step` with `id` (`"s1"`, `"s2"`, ... in order), `first_line` and `last_line` (1-based proof lines, inclusive; the first step's `first_line` is the line after the header; a step's `last_line` is the last non-blank line before the next step), `text` (the step's lines joined with `\n`), `hash` (first 10 hex digits of the sha1 of the text with each run of whitespace collapsed to one space) and `indent`. Add `split_steps(proof: str) -> list[Step]`: the top-level steps. A proof with no `:= by` header, or a term-mode proof, is one step `s1` covering everything after the statement's `:=` (`arena.routes.proof_body` finds that point; keep using it, do not copy it).
- [ ] 3. Add `step_range(steps, spec: str) -> tuple[Step, Step]`: `spec` is `"s3"` or `"s3-s5"`. An unknown id or a reversed range raises `ValueError` whose message names the bad input and lists the valid ids (`"unknown step s9; steps are s1-s7"`).
- [ ] 4. Add the two text operations as pure functions in `arena/graph.py`, built on `steps.split_steps`:
  - `splice_text(proof: str, spec: str, text: str) -> str`: replaces the lines of the named step range with `text`. `text` is dedented (`textwrap.dedent`) and re-indented to the replaced step's indentation. All other lines are byte-identical, and the trailing newline of the base is kept.
  - `merge_steps(base: str, takes: list[dict]) -> str`: each take is `{"text": donor_proof, "step": "s3"}`; the donor's step with that id replaces the base's step with the **same id** (plan §5b leaves the target position open; this is the simplest rule and is recorded under Decisions in your hand-back). Donor lines are dedented and re-indented like a splice. Two takes for the same id, an id the base lacks, or an id the donor lacks raise `ValueError` naming it.

**B. The event log and the graph projection**
- [ ] 5. In `arena/graph.py` add the node projection, a pure function of the ledger: `Graph.from_history(history, read_text)` where `read_text(proof_id) -> str | None` returns `proofs/<id>.lean`. Node ids are `n<k>`, `k` = order of first appearance of each distinct proof id among `candidate` and `probe` events (the reference is `n1`). Each `Node` has: `id`, `proof_id`, `status` (`closed` when `goalstate.closed` holds for its best evaluation or probe result; `sketch` when its primary compile passed and its text contains a `sorry` token; otherwise `broken`), `origin`, `score` (the proxy of its best evaluation: `full` over `primary`, as `campaign._summaries` chooses; `None` when not scored), `verified`, `tokens`, `heartbeats`, `versions` (`{version: passed}` from the compile result), `edge` (the node's edge event, or `None`), `steps` (the list from `split_steps` of its text; ticket 10b adds per-step goals to it) and `depth` (0 for a root, else depth of the first parent + 1). `Graph` also has `focus` (proof id of the last `focus` event) and `order`. Do not import `campaign` from `graph` (the projection takes plain dicts, so it needs its own 3-line `score` helper).
- [ ] 6. Define two new ledger event kinds, documented in the `arena/graph.py` module docstring (one place) and written only through `campaign._append`:
  - `{"kind":"edge","proof_id","type","from":[proof_id,...],"exact":bool,"similarity":float|None,"named_parent":proof_id|None,"measured_parent":proof_id|None,"measured_similarity":float|None,"operation":{...}|None}`. `type` is one of `edited_from` (a draft built against a base, or a splice), `merged_from` (a merge, with the steps taken in `operation`), `filed_under_focus`, `root`. (`filled_from` and `salvaged_from` are added by ticket 12; leave them out.) `exact` is true for every type except `filed_under_focus` and a `root` that was a filing; the reference's `root` is exact.
  - `{"kind":"focus","proof_id","reason"}`; `reason` is one of `start`, `batch_best`, `restore` (ticket 11 adds `stall`).
  The `step_goals` event is added by ticket 10b; do not add it here. `named_parent` and `measured_parent` are audit fields only: no rule, filter or default in this ticket may read them.
- [ ] 7. Similarity and the audit parent, pure in `arena/graph.py`: `similarity(a: str, b: str) -> float` is `difflib.SequenceMatcher(None, la, lb, autojunk=False).ratio()` over the lists of stripped lines of at least 6 characters that are not `by` (the `lines_of` of `graph_audit.py`). `measured_parent(texts: list[tuple[str, str]], text: str) -> tuple[str | None, float]`: the best similarity over the **20 most recent** earlier nodes, ties to the most recent (plan §5b item 3). Add the constant `FILING_MIN_SIMILARITY = 0.50` with a comment that it is fixed by decision 8 and **must not be tuned**.
- [ ] 8. Filing, in `campaign.py`: `_file_node(directory, history, proof_id, proof, named_parent=None, operation=None) -> dict` appends the node's `edge` event while holding a new flock `directory/"graph.lock"` around reading the history and appending (the same pattern as `lean_lock`). With an `operation` (`{"type": "edited_from" | "merged_from", "from": [proof ids], ...}`) the edge is exact and copies the operation. With none, the node is compared with the focus node: similarity at least `FILING_MIN_SIMILARITY` gives `filed_under_focus` from `[focus]` with the similarity; below it gives `root` (not exact) with `from: []`. The reference node is `root`, exact, and `init` appends `focus` (`reason: "start"`) for it right after the reference's `candidate` event. Filing happens **after the compile result is recorded** (end of `record_evaluation`, after the `probe` event in `probe`), so status and score exist, and only for a proof id that has no `edge` event yet (a repeated text files nothing). Resolve a named parent with a new `_named_parent_id(history, reference)` (`#N` and hash prefixes through `resolve_candidate_ref`; `pN` to the probe's own proof id, not its parent; anything unresolvable gives `None`; the old "parent ... ignored" notes stay exactly as they are).
- [ ] 9. Focus. In `campaign.py` add `_settle_focus(directory, proof_ids)`: among the batch's nodes whose status is `closed` or `sketch`, pick the best (closed beats sketch; closed by score, an unscored closed node ranks 0.0; sketches by fewest `sorry` tokens) and append `focus` (`batch_best`) when it differs from the current focus; no non-broken node leaves the focus unchanged. A single `record_evaluation`, a single `probe` and a whole `probe_batch` are each one batch: `probe_batch` sets a `ContextVar` (like `_PRECOMPILED`) holding the focus as it was before the batch, so every draft of the batch is filed under that same focus, and calls `_settle_focus` once at the end; `probe` and `record_evaluation` call it themselves only when that variable is unset. `candidate()` (restore) appends `focus` (`restore`) for the restored node.
- [ ] 10. Operations and the one hidden entry: add `campaign.compile_operation(name, run_id, operation: dict, mode="fast", idea_id=None) -> dict` and register it as the hidden protocol action `operation` (JSON in, JSON out, in the same action table as `evaluate` and `probe`; the request is one JSON argument `--operation`). Operation shapes: `{"type":"draft","base":ref,"text":str}` (the text is compiled as written, lineage `edited_from` base), `{"type":"splice","base":ref,"steps":"s2-s3","text":str}` (`graph.splice_text` builds the proof), `{"type":"merge","base":ref,"take":[{"from":ref,"step":"s3"}]}` (`graph.merge_steps`). `ref` is `nK`, `#N`, `pN` or a hash prefix (add `resolve_node_ref(history, ref) -> proof_id`; a bad ref raises `ValueError` naming the input and listing the valid forms). It builds the text, normalizes it with `normalize_draft`, compiles through the existing path (`probe` with a new keyword `operation=None`; a complete draft that compiles is still promoted to a candidate through `record_evaluation(..., operation=...)`, which gains the same keyword), and returns the old reply (`_model_view`) plus `"node": "nK"` and `"edge": {type, from}`. It returns structured data only: no sentence for the model (rendering belongs to ticket 15a). `record_evaluation(..., origin="auto_merge")` from `merge_once` passes `operation={"type":"merged_from","from":<the pair's proof ids>}`.
- [ ] 11. Keep the old tools exactly as they are: no old reply changes shape or wording, `candidate.parents`, `derivation` and `current` events are still written as today (they are legacy fields removed with the old tools in ticket 15c, D39), `_current` is still the default parent of `probe`. Only additions: `graph_state()` gains `"node"` and `"edge"` on every node row and probe row, and a top-level `"focus"`; `tools/serve_candidate_graph.py` and the viewer need no change.

**C. Tests** (unittest style; no Lean; Seam A unless stated)
- [ ] 12. Move the fake-Lean fixture out of `tests/test_protocol.py::ProtocolLogicTests` verbatim (`setUp`, `fake_eval`, `evaluate`, `calls`) into a new `tests/graph_support.py` as base class `FakeRunCase(unittest.TestCase)`; `ProtocolLogicTests` subclasses it. No test changes behaviour. Later tickets reuse this class.
- [ ] 13. Pure units (in `tests/test_graph.py`): `split_steps` on fixture proofs (a three-step tactic proof; a first tactic on the `:= by` line is one step; a term-mode proof is one step; comment-only lines never start a step; nested bullets stay inside their step); `step_range` errors list the valid ids; `splice_text` replaces a middle range, re-indents a dedented replacement and leaves every other byte alone; `merge_steps` takes a donor step by id and rejects a duplicate id; `similarity` is 1.0 for identical text and drops with edits; `measured_parent` looks only at the 20 most recent.
- [ ] 14. Seam A, graph operations and exact edges (fake Lean): (a) a `splice` operation files an `edited_from` edge with `exact: true` and `from` = the base; (b) a `merge` operation files `merged_from` with the steps in `operation`; (c) a `draft` with a base files `edited_from`; (d) a bad node ref and a bad step id return an error that names the input and lists the valid forms; (e) re-submitting a known text creates no second node and no second edge; (f) a compile that fails still produces a `broken` node with an edge.
- [ ] 15. Seam A, focus filing: a free-text draft whose text resembles the focus is `filed_under_focus` from it with the similarity recorded; a dissimilar one is a `root` (not exact); the named parent (`parents=["#2"]` or `--parent`) and the measured parent are stored on the edge and change neither the filing nor the focus; in a batch of three drafts every draft is filed under the focus as it was before the batch and the batch's best node becomes the focus afterwards; a batch with only broken nodes leaves the focus alone; `candidate` (restore) sets the focus; `init` sets the focus to the reference.
- [ ] 16. Seam A, projection: node ids follow first appearance and are stable when more events arrive; `status` is `closed` / `sketch` / `broken` for the three kinds of fake result; `depth` follows the first parent; the old reply shapes are unchanged (the existing `ProtocolLogicTests` still pass unmodified).
- [ ] 17. Run `uv run ruff check` and `uv run ruff format` on every file you touched, and `uv run ty check arena/steps.py arena/graph.py` plus the files you touched (fix only diagnostics in lines you wrote).

## Do NOT
- Do not change any model-facing string or old reply field. This ticket adds no model-facing text; the filing sentence (`n51 <- focus n41`) is rendered by ticket 15a.
- Do not expose operations through a Pi tool or edit `packages/arena-pi/extensions/arena.ts`. The only new entry is the hidden protocol action `operation`.
- Do not remove or rewrite `candidate.parents`, `derivation`, `current`, ideas, `decision`, `ranked_frontier`, `merge_check` or the old `route` machinery (tickets 11 and 15c own those).
- Do not let any code read `named_parent` or `measured_parent` for a decision (filing, focus, merge, default parent). They are stored and exposed only.
- Do not tune `FILING_MIN_SIMILARITY` (0.50, decision 8).
- Do not add per-step goals, `steps.lean` or the `step_goals` event (ticket 10b), holes, `filled_from` or `salvaged_from` (ticket 12), routes or archive cells (ticket 11), price rows (ticket 13).
- Do not infer lineage from text anywhere except the single `filed_under_focus` / `root` decision and the audit field. Probe evidence: text can recover the model's meaning only 48% of the time.
- Do not change the Lean toolchain, workspaces or `models.yaml`.

## Acceptance
- A run's ledger holds one `edge` event per distinct draft text, written after its compile result, and `Graph.from_history` of that ledger gives stable `n1..nK` ids, a status per node and the focus.
- `uv run arena protocol operation ... --operation '{"type":"splice",...}'` (or the hidden command ticket 04 provides for protocol actions) returns the old reply plus `node` and `edge`, and the ledger holds an `edited_from` edge with `exact: true`.
- A batch of four drafts is filed under one focus; afterwards the focus is the batch's best non-broken node.
- The old tools' replies are byte-for-byte what they were (the unchanged `ProtocolLogicTests` and `tests/test_protocol.py` pass).

## Verify
Test budget: targeted files first, the fast suite once at the end. This ticket changes no Lean or Pi behaviour, so no slow file and no speed gate.
- `uv run pytest -q -p no:cacheprovider tests/test_graph.py tests/test_protocol.py` -> all pass (baseline count + the new tests; slow tests skip).
- `uv run ruff check arena tests && uv run ruff format --check arena tests` -> clean for the files you touched.
- `uv run python -c "from arena.steps import split_steps; print([ (s.id, s.first_line, s.last_line) for s in split_steps(open('runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt').read())])"` -> prints one tuple per top-level step (paste it in the hand-back).
- `uv run pytest -q -p no:cacheprovider` -> the fast suite, once, at the end: all pass (the two known slow failures are not part of it).

## Stop and report if
- `arena/campaign.py` no longer has `record_evaluation`, `probe`, `probe_batch`, `merge_once` or `autocheck` with the shapes above.
- Any existing test outside the ones you moved in item 12 needs its assertions changed.
- You find a place where an old reply would change wording or shape.
- A decision the ticket does not make seems necessary (for example how an unparseable proof's steps should be numbered): stop and ask; do not pick one.


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

Your branch is **`v7/10a-graph-core`**, already created and stacked directly above `v7/09-scheduler`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/10a-graph-core` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/10a-graph-core -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-10a`.
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
- [ ] Every change is committed on `v7/10a-graph-core`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-10a
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
