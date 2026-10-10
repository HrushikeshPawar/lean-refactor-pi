# 13: Price engine and instant token quotes

**What to build:** The model can read what a change is worth. Every scored compile reply carries a price row against its parent and the best node (tokens, heartbeats, versions, ending in the score change). A per-step price table (tokens, self and inclusive heartbeats, points if the step were gone, the per-axis rates) exists for the original proof and for archive nodes, filled by background profile compiles. Token counts of any text are free and instant (no Lean). The effort table of the map (points at stake against attempts per step) is built from these prices. The full tool surface is ticket 15; here the price row rides on the existing `arena_evaluate` / `arena_probe` replies, and the table, quotes and effort table are reachable through hidden protocol actions.

**Blocked by:** 10b: Per-step goals pipeline; 11: Routes, K1 archive, map, stall (this ticket profiles archive nodes and extends the map); 08c: Lean service callers, tests, speed gate. (Ticket 10a and ticket 12 are committed below this branch as well.)

**Status:** ready-for-agent

**Branch:** `v7/13-prices` (stacked on `v7/12-salvage`)

**Read first:** spec sections "Price engine", "Interfaces and contracts" (`compile check: tokens`), "Testing Decisions" (Seam A: price rows and instant token quotes; pure unit: scoring rates), "Model: what it is told" stories 38-40, 48-49; plan §3a, §3b, §3c, §4e, §5d (effort table), §1l; decisions D5, D17, D31, D32, D34. Decision 2 (owner, 2026-10-10): the library token-cost column is DROPPED; ignore any story or plan text (§3e) that asks for a token cost per library name. The ranked top-60 library (D34) stays and is not touched here.

## Context: where things are now
Names are as of ticket 12. If a name below no longer exists and you cannot find its obvious successor, stop and report.
- `arena/scoring.py`: `reference(name)` (published token and heartbeat denominators), `exchange_rates(name, total_versions)` (rounded rates: `points_per_token`, `points_per_100_heartbeats`, `points_per_lost_version`, plus `reference_tokens`, `reference_heartbeats`, `versions`), `metrics(...)` (per-axis contributions, `deltas`), `local_proxy`. The score is the mean of three percentages, so each axis contributes a third of its own percentage.
- `arena/engine.py:_proof_length(text, statement=None)`: the official token counter through the vendor adapter. `_proof_length("theorem x : True := " + snippet)` counts exactly the tokens of `snippet` (verified: `simp` 1, `by\n  simp` 2, `omega\n  simp [foo]` 5). Under this counter any identifier is **one** token (`Nat.add_comm_of_very_long_name_here`, `𝔽q` and `Nat.add_comm` each count 1), which is why there is no per-name token cost anywhere in this ticket.
- `arena/profile.py`: `profile(name, proof, measured=None)` returns `entries` (per tactic: `proof_line`, `end_proof_line`, `depth`, `hb` inclusive, `self_hb`, `text`), `line_tokens` (`{proof line: tokens}`, **keys become strings after the result is saved as JSON**; `None` when the line attribution does not add up), `token_attribution_available`, `measured_total`, `profiled_total`, `hotspots`. Heartbeat numbers are in the scoring unit (raw count / 1000). `_instrumented(...)` and `profile(...)` run Lean through `run_lean`/`compile_version` in the model lane (no `lane` parameter yet). `campaign.profile_request` is the old `arena_profile` entry; it caches a `profile` event per proof id.
- `arena/context.py:reference_profile(name)`: the original's profile, cached on disk per row (computed when the packet is built).
- `campaign.record_evaluation` builds the reply (`metrics.deltas.vs_parent` / `vs_best` use the model's **named** parent, tokens, heartbeats and proxy) and `_model_view` filters the keys the model sees.
- Tickets 10a/10b/11/12: `graph.Graph` (`Node.score`, `status`, `edge`, `steps`, `verified`, `versions`), `steps.split_steps`, `graph.archive`, `graph.map_view` (with `effort: []`), `campaign.node_label`, the autocheck job queue (salvage, assembly, full checks, step goals), the update-line mechanism, `tests/graph_support.py::FakeRunCase`.
- `agent-text/` (ticket 05a): `replies/`, `packet/`, `numbers.yaml`, the Python renderer (`grep -rn 'def render' arena/`).

## What to build

**A. The engine (new module `arena/prices.py`, pure unless marked)**
- [ ] 1. `rates(reference_tokens: int, reference_heartbeats: int, total_versions: int) -> dict`: unrounded `points_per_token = 100/3/reference_tokens`, `points_per_1k_hb = 100/3/reference_heartbeats * 1000`, `points_per_version = 100/3/total_versions`. `campaign` passes `scoring.reference(name)`; do not change `scoring.py`. Add `fmt_hb(n) -> str` (`1234` -> `"1.2K"`, below 1000 the plain integer) and `fmt_signed(n, unit="")` using the true minus sign `−` (`+4.0K`, `−9`).
- [ ] 2. `step_table(proof: str, profile: dict | None, rates: dict, total_tokens: int, total_hb: int | None, versions: str | None) -> dict`: one row per top-level step from `steps.split_steps(proof)`: `{id, first_line, last_line, tokens, self_hb, incl_hb, pts_if_gone, text}`. `tokens` = the sum of `profile["line_tokens"]` over the step's lines (convert the keys with `int`) when `token_attribution_available` is true, else the snippet count of the step's text. `self_hb`/`incl_hb` come from the profile entry with `depth == 0` and `proof_line == step.first_line` (`self_hb`, `hb`); `None` when the profile is `None` or has no such entry. `pts_if_gone = tokens * points_per_token + (incl_hb or 0) / 1000 * points_per_1k_hb` (inclusive heartbeats, because removing a step removes everything inside it; the plan calls it the upper bound of what the step alone can still earn; decision recorded in the hand-back), rounded to 2 decimals. `text` is the first 40 characters of the step's first line, stripped. Return `{"rows": [...], "total": {"tokens", "heartbeats", "versions", "proxy"}, "rates": rates}`; `versions` is the node's `p/t` string (plan §3a shows `versions` per step; a step has no version result of its own, so it is shown on the total row only, noted in the hand-back).
- [ ] 3. `snippet_tokens(text: str) -> int` (`engine._proof_length("theorem x : True := " + text)`; raises `ValueError` on `>= 10**9` as `_proof_length` does) and `quote_tokens(name, items: list, against: dict | None = None, statement: str | None = None) -> dict`: per item `{"index", "kind": "draft" | "snippet", "tokens", "delta"}`. An item is a **draft** when, stripped, it starts with the statement, `:=` or `by` (as `campaign.normalize_draft` decides); a draft is normalized with `campaign.normalize_draft` and counted with `_proof_length(proof, statement)` (what the grader counts); anything else is a snippet counted with `snippet_tokens`. `against` is `{"text": str}` (the text of the step range it is compared with; the caller supplies it). For a snippet, `delta = tokens - snippet_tokens(against["text"])`; for a draft, `delta` is `None` (a whole proof is not compared with a step). With no `against`, `delta` is `None`. An item that is not a non-empty string gives `{"index", "error": "item <i> is not text (got <type>); pass a list of strings"}` and the other items are still answered (per-item errors).
- [ ] 4. `changed_lines(old: str, new: str) -> int` in `arena/graph.py`: `sum(max(i2 - i1, j2 - j1))` over the non-equal opcodes of `SequenceMatcher(None, old_lines, new_lines, autojunk=False)`.
- [ ] 5. `price_row(node, parent, best, lines_changed, step_changes) -> dict` of numbers, no text: `{label, parent_label, lines, tokens, tokens_vs_parent, tokens_vs_best, hb, hb_vs_parent, hb_vs_best, versions, score_vs_best, changed}`. `parent` is the node's first edge parent (the filing/operation parent, not the named one); `best` is the best scored node other than `node` (the reference counts). A comparison with an unscored or missing node is `None`. `step_changes` is `changed_steps(parent_steps, node_steps)`: align the two step lists by `SequenceMatcher` over the step hashes; each non-equal opcode yields `{"ids": [node step ids], "old_tokens", "new_tokens"}` (token counts from `snippet_tokens` of the joined step text) and, only when both nodes have per-step heartbeats (item 8), `old_hb` and `new_hb` (inclusive).

**B. Rendering (templates, ticket 05a's layout)**
- [ ] 6. Add `agent-text/replies/price-row.md` with the keys (logic-free `{name}` placeholders only):
  `row` = `{label} ← {parent_label} (Δ {lines} lines)   tokens {tokens} ({tokens_part})   hb {hb} ({hb_part})   versions {versions}   Δscore {score_part}`,
  `row_root` = `{label} (new root)   tokens {tokens}   hb {hb}   versions {versions}`,
  `changed` = `changed steps: {changes}`,
  `versions_full` = `{passed}/{total}`, `versions_pending` = `{checked} of {total} checked`.
  Code builds the fragments: `tokens_part` is `−9 vs #3, −24 vs best` (the vs-best half is left out when the parent is the best; `n/a` for a missing comparison), `hb_part` likewise with `fmt_signed`/`fmt_hb`, `score_part` is `+0.6 vs best`, `changes` is `s2 (61→52 tok, 41.3K→45.3K hb)` joined by `; ` (heartbeat half only when both are known). Register the keys with the template tests exactly as ticket 05a requires (every placeholder supplied, none unused). Wording is neutral: numbers and graph position only. Labels are `node_label` values (`#N`, `pN`) because the old tools address nodes that way; ticket 15a switches to `nK`.
- [ ] 7. Add `agent-text/packet/price-table.md` with the keys `header`, `row`, `total`, `rates` that render the table of plan §3a as text (`step  lines  tokens  self_hb  incl_hb  pts_if_gone  text`, one line per step, a total line with tokens, heartbeats, versions and proxy, and the rates line `rates: 1 token = {pts_token} pts · 1K hb = {pts_hb} pts · 1 version = {pts_version} pts`), and `campaign.render_price_table(table) -> str` that fills them. Nothing includes the table in the packet yet (ticket 16 decides where it goes); the renderer is used by the `prices` action's `text` field.

**C. Wiring**
- [ ] 8. Background profiles. Add `lane: str = "model"` to `profile.profile` and `profile._instrumented` and pass it to `run_lean` and to the `compile_version` call that measures heartbeats; behaviour for `lane="model"` is unchanged. `autocheck` drains **profile jobs** last (after salvage, assembly, full checks and step goals): every node that is the best node of an archive cell (ticket 11's `graph.archive`), has status `closed`, is not the reference and has no `profile` event. The job runs `profile(name, proof, measured=node heartbeats, lane="background")` under `lean_lock(directory, "background")` and appends the same `{"kind":"profile","proof_id","result"}` event `profile_request` uses (so the old `arena_profile` returns it cached). A `ValueError` is recorded as `{"kind":"profile_error","proof_id","error"}` (not a `profile` event, so `arena_profile` still compiles for itself) and is not retried. The original needs no job: its profile is `context.reference_profile(name)`.
- [ ] 9. `campaign.price_table(name, run_id, reference=None) -> dict` and the hidden protocol action `prices` (`--candidate` as `#N`, `pN`, `nK` or a hash prefix; default: the best scored node): builds `step_table` from the node's text and its cached profile (the `profile` event; for the reference `context.reference_profile(name)`), **never starting Lean**; missing heartbeats stay `None`. Returns the table plus `"text"` (item 7) and `"profiled": bool`.
- [ ] 10. The price row on the old replies: at the end of `campaign.record_evaluation`, for a scored (compiled) node, compute `price_row` and add `"price_row": <rendered lines>` to the returned dict; add `price_row` to the key list in `_model_view` so `arena_evaluate` and a promoted `arena_probe` reply carry it. Node steps for the row come from the nodes' texts (`split_steps`); per-step heartbeats only when both nodes have a cached profile. Drafts that do not compile or compile with `sorry` get no price row. Every other key and all wording of the old replies stay as they are (the existing `metrics.deltas` stay).
- [ ] 11. Instant quotes: `campaign.quote(name, run_id, items: list, against: dict | None = None) -> dict` and the hidden protocol action `quote` (`--items` JSON list; optional `--against` JSON `{"node": ref, "steps": "s2"}` which `quote` resolves with `resolve_node_ref` and `steps.step_range` into `{"text": the step range's text}`). A bad ref or step id gives the same error as `compile_operation` (names the input, lists valid forms). It runs no Lean, writes no ledger event and takes no lock.
- [ ] 12. Effort table. Fill the `effort` key of `graph.map_view` (ticket 11 left `[]`): one row per step of the best node, `{step, at_stake, variants, best_dtok, last_gain}`:
  - `at_stake`: the step's `pts_if_gone` from `step_table` (heartbeat part 0 when no profile is cached).
  - Align every other non-reference node's steps to the best node's by `SequenceMatcher` over step hashes. The best node's step is **varied** by a node when it falls in a non-equal opcode (replace or delete) range.
  - `variants`: the number of distinct nodes (any status except the reference and the best itself) that vary the step.
  - `best_dtok`: over closed varied nodes whose opcode replaces exactly this one best step with exactly one step, the minimum of (their step tokens minus the best step's tokens) by `snippet_tokens`; `None` when there is none.
  - `last_gain`: the number of nodes recorded after the most recent closed varied node whose score is above its first edge parent's score; `None` when there is none.
- [ ] 13. Expose the effort table through the existing hidden `map` action only (no new action, no model-facing rendering).

**D. Tests** (unittest style; Seam A unless noted). Put items 14-18 in a new `tests/test_prices.py` (pure units, and Seam A on `FakeRunCase` from `tests/graph_support.py`).
- [ ] 14. Pure units (scoring rates and prices): `rates` returns `100/3/ref` per unit (check two reference pairs by hand) and matches `scoring.exchange_rates` after its rounding for the same reference; `fmt_hb` and `fmt_signed` (including `0`, a negative and a value just below 1000); `step_table` on a fixture proof with a canned profile (JSON-style string keys in `line_tokens`): per-step tokens sum to the line tokens, `pts_if_gone` equals tokens times rate plus inclusive heartbeats times rate, a step with no profile entry has `None` heartbeats and a heartbeat-free `pts_if_gone`, a profile with `line_tokens: None` falls back to snippet counts; `changed_lines`; `changed_steps` for a replace, an insert and a delete.
- [ ] 15. Instant quotes (Seam A, fake Lean must not be called): a full draft is counted as the grader counts it (equals `_proof_length(proof, statement)` of the normalized draft); a snippet equals the number of tokens it would add; a body-only draft (`by ...`) is a draft; the delta against a step range equals tokens minus the range's tokens; a non-string item gives a per-item error and its neighbours are still answered; patching `engine.evaluate` and `subprocess` to raise proves no Lean is used; no ledger event is written.
- [ ] 16. Price rows (Seam A, `FakeRunCase`): a compiled node's reply has `price_row` with the right numbers against its filing parent and against the best (tokens, heartbeats, score deltas, versions fragment `1 of 2 checked` after a fast compile and `2/2` after the full check); a root node uses the `row_root` form; when the parent is the best the vs-best half is omitted; a draft that fails or has `sorry` has no `price_row`; the named parent (`parents=["#2"]`) does not change the row's parent (it is the filing parent); old reply keys and `metrics.deltas` are unchanged (existing protocol tests pass untouched).
- [ ] 17. Profiles and the table (Seam A, `profile.profile` patched): `autocheck` profiles an archive-best closed node once, in the background lane (assert the `lane` argument), never the reference, never a sketch or broken node; a `ValueError` becomes a `profile_error` event and is not retried and `profile_request` still compiles for itself; after the job `price_table` returns heartbeats for that node, and before it returns `None` heartbeats without starting Lean (patch `profile.profile` and `engine.evaluate` to raise in the `prices` call).
- [ ] 18. Effort table (pure on a hand-built `Graph`): variants counts distinct non-reference nodes that vary a step (a broken draft counts); the reference never counts; `best_dtok` only from one-for-one closed replacements; `last_gain` counts nodes recorded since the latest gaining variant and is `None` when none gained; `at_stake` matches `step_table`.
- [ ] 19. Run `uv run ruff check` / `uv run ruff format` on every file you touched and `uv run ty check arena/prices.py arena/graph.py arena/profile.py` (fix only diagnostics in lines you wrote).
- [ ] 20. One `@slow` Lean test in `tests/test_protocol.py` (Strata fixture, `CampaignCliTests` style): evaluate `FIXTURE.read_text()`, run `autocheck`, then `prices` for that node: every step row has tokens, at least one has `incl_hb`, the row sums of `incl_hb` are within 10% of the node's measured heartbeats, and the compile reply carried a `price_row`. Paste the table text in the hand-back.

## Do NOT
- Do not write any model-facing sentence in code; templates only (ticket 05a's rule). Fragments such as `−9 vs #3` are built in code, the sentence is the template.
- Do not add the price table to the packet or change the packet; ticket 16 owns packet text and size shedding. Do not add a row cap for the table (the plan says "capped by numbers.yaml" without a value; that belongs to ticket 16).
- Do not expose quotes, prices or the effort table as Pi tools or edit `packages/arena-pi/extensions/arena.ts`. Only hidden protocol actions (`quote`, `prices`, and the extended `map`).
- Do not add a library token-cost column, `library_token_costs`, or a token cost per library name anywhere (decision 2: the official counter scores any identifier as one token). Do not replace it with anything.
- Do not profile every node: heartbeats per step exist only for the original and archive-cell bests (spec "Price engine").
- Do not change `scoring.py`, `engine._proof_length`, the heartbeat wrapper or the measure version (D31, D32).
- Do not make the price row depend on the named parent or the measured parent (audit fields only).
- Do not suggest a replacement, a lemma or a kind of proof anywhere in a price line (D30: prices only, no advice).
- Do not fill the table's `versions` per step; it is on the total row only.
- Do not run `profile` in the model lane from `price_table` or from the reply path; profiles come from the background job.

## Acceptance
- A compiled node's `arena_evaluate`/`arena_probe` reply contains a `price_row` like `#7 ← #5 (Δ 3 lines)   tokens 188 (−9 vs #5, −24 vs best)   hb 96.1K (+4.0K, −23.9K)   versions 1 of 5 checked   Δscore +0.6 vs best`.
- `uv run arena protocol quote --theorem <name> --run-id <id> --items '["simp","omega"]'` (or the hidden command ticket 04 provides) prints token counts immediately and no Lean process starts.
- After `autocheck`, `prices` for the best node shows heartbeats per step, `pts_if_gone` per step and the rates line; for the original it works at once from the cached reference profile.
- No library token cost exists anywhere (`grep -rn 'library_token_costs' arena tests` finds nothing).
- The map JSON has an `effort` list with one row per step of the best node.

## Verify
Test budget: targeted files, the fast suite once, one named slow file. No speed gate (the profile job adds no new Lean machinery beyond a `lane` argument; if you change anything in the Lean call path, stop and report).
- `uv run pytest -q -p no:cacheprovider tests/test_prices.py tests/test_protocol.py` -> all pass (baseline count + the new tests).
- `cd packages/arena-pi && npm test` -> all pass (unchanged count).
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_protocol.py -k prices` -> passes (skips without the Strata workspace: say so).
- `uv run ruff check arena tests && uv run ruff format --check arena tests` -> clean for the files you touched.
- `grep -rn 'library_token_costs' arena tests` -> no output.
- Time the instant quote: `time uv run arena protocol quote ...` for 10 snippets -> well under 1 s of work after Python start-up (paste the number).
- `uv run pytest -q -p no:cacheprovider` -> the fast suite, once, at the end: all pass.

## Stop and report if
- `profile.profile` cannot take a `lane` without changing results for `lane="model"` (report; do not fork a second profile path).
- The profile entries do not carry `depth == 0` records matching step first lines on the Strata fixture (report what they hold; do not guess a different join).
- Ticket 05a's `agent-text/replies/` or renderer does not exist.
- `graph.archive` or `map_view` from ticket 11 do not exist as described.
- Any change would be needed in the Lean call path beyond the `lane` argument of item 8.
- A price number in a reply would differ from the same number in the old `metrics` block for the same node (they must agree; if they cannot, report both).
- A decision the ticket does not make seems necessary (for example what the price row should say for a node with no scored comparison node): stop and ask; do not pick one.


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

Your branch is **`v7/13-prices`**, already created and stacked directly above `v7/12-salvage`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/13-prices` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/13-prices -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-13`.
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
- [ ] Every change is committed on `v7/13-prices`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-13
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
