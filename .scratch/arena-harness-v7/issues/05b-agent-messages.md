# 05b: Agent text: campaign/engine/TS messages moved verbatim, shown.yaml, literal lint

**What to build:** Every remaining string the model reads (tool-reply and error strings from the Python modules, the
tool descriptions, notices, the footer and the other messages in the TypeScript extension) moves, word for word, into
`agent-text/` and is rendered through the strict renderer built in ticket 05a. The code reads the shared constants from
`agent-text/numbers.yaml`. Every template file gets a `shown.yaml` entry (where the model sees it, how often), which
`arena text budget` now prints. A lint test fails if model-facing prose appears in code again. A golden test proves
the move changed nothing: every moved message and every tool description render byte-identical to what the code produced
before. **This ticket does not reword anything**: the rewrite is ticket 16.

**Blocked by:** 05a: Agent text: format, renderers, numbers.yaml, skill/packet/memory moved verbatim, `arena text` (the renderers `arena/text.py` and `text.ts`, `numbers.yaml`, and the `arena text` sub-app).

**Status:** ready-for-agent

**Branch:** `v7/05b-agent-messages` (stacked on `v7/05a-agent-text`)

**Read first:** spec "Modules" -> "Agent text", "Testing Decisions" (pure units), stories 36-45 and 108; plan §2
(2a layout, 2b rules, 2c tests, 2e order), §1d (where the text is today); decisions D3, D4, D6, D18.

## Context: where things are now

After ticket 05a: `arena/text.py` and `packages/arena-pi/extensions/text.ts` (the renderers), `agent-text/` (the skill,
the packet and the compaction memory, `numbers.yaml`, `README.md`), `arena text render|budget` (words). Still in code, and
moved by this ticket (find more with the lint in item 6; this list is the starting point):

- `arena/campaign.py`: about 50 tool-result and error strings (for example in `declarations`, `find`,
  `_source_range`, `_declaration_in_lean`, `resolve_candidate_ref`, `record_idea`, `record_evaluation`,
  `evaluate_request`, `probe_batch`, `normalize_draft`, `set_decision`, `_advisory`, `_check_text`,
  `_full_check_status`, `cold_verify`, `submission`, `merge_once`, `_refuse_if_tripped`, `init`). Constants
  `MAX_SOURCE_LINES = 400` and `MAX_SCAN_FILES = 30` are repeated as digits inside tool descriptions.
- `arena/engine.py` (`validate_proof` and others: `STATEMENT_MODIFIED`, `EXTRA_COMMAND`, ... messages that reach the
  model as tool errors), `arena/routes.py` (`routes_text`), `arena/profile.py`, `arena/merges.py`,
  `arena/goalstate.py`: a few strings each. Some may be log-only; check where each one goes before moving it.
- `packages/arena-pi/extensions/arena.ts`: the descriptions of 11 model tools and their parameters
  (`arena_evaluate`, `arena_probe`, `arena_profile`, `arena_idea`, `arena_state`, `arena_finish`,
  `arena_candidate`, `arena_skill_read`, `arena_source`, `arena_declarations`, `arena_find`), plus message strings:
  the `[arena]` line (`stateLine`, `briefText`), the block reasons in the `tool_call` hook, the `arena_finish`
  review and reminder texts, the idea auto-close reasons, `arena_skill_read` errors, the continuation text in
  `agent_before_settle`.
- `packages/arena-pi/extensions/rules.ts` (`planEvaluate` and `planProbe` notes, `leanPathViolation`, `routesText`,
  `staleNotice`, `allowanceFacts`, `finishPush`, `continuationPush`, `trimProfile`), `trim.ts` (the "already loaded"
  stub, the repeated-message pointer, the warning cut), `spend.ts` (`spendFooter`; `FINISH_REMAINING_FRACTION`).
  `rules.test.ts`, `trim.test.ts` and `spend.test.ts` assert exact text.
- `arena/lean/*.lean` print records, not prose for the model: leave them.
- `tests/fake_opencode.ts` is the fake provider Pi talks to in slow tests; its request log line has `tools` (names).

## What to build

Work in this order, as separate commits (every commit leaves the fast suite and `npm test` green). The lint test
(item 6) comes last, because it fails until everything has moved.

- [ ] 1. **Golden outputs first (test-only commit, before any move).** On the code as it stands at the start of this ticket,
  create `tests/test_agent_text_messages_golden.py` with `tests/fixtures/agent_text_messages_golden.json`, and
  `packages/arena-pi/extensions/agent-text-golden.test.ts` with `agent-text-golden.json` beside it. Each golden entry is
  `{"id", "source", "expected"}` as in ticket 05a (`source` names the file and function; `expected` is the exact output of
  the pre-move code). Cases:
  1. Every Python message string that reaches the model through `arena/campaign.py`, `arena/engine.py`,
     `arena/routes.py`, `arena/profile.py`, `arena/merges.py`, `arena/goalstate.py`: one entry per string, produced by
     calling the owning function with inputs that trigger it (most error paths need no Lean: for example
     `probe_batch` with five drafts, `resolve_candidate_ref` with an unknown `#N`). A string that cannot be reached
     without Lean or a workspace gets a hand-built entry: write the original f-string with chosen values substituted,
     copied from the source, and name its file and line in `source`. List the hand-built entries in the hand-back.
  2. Tool definitions. `arena.ts` cannot be imported by `node --test` (it imports `typebox`, which is not installed
     outside Pi), so capture them through Pi: extend `tests/fake_opencode.ts` so its request log line also records
     `tool_definitions` (each tool's `name`, `description` and `parameters`, as JSON) beside the existing `tools`
     (names); do not change `tools`. Run one `FakeRun` (no Lean; Pi required) on the unmodified code and save the
     first request's `tool_definitions` as the `tool_definitions` golden. A `@slow` test in
     `tests/test_agent_text_messages_golden.py` repeats the run and compares (this proves `arena.ts` wires the templates).
  3. TypeScript functions, in `agent-text-golden.test.ts` (they import only node modules): the output of
     `finishPush`, `continuationPush`, `routesText`, `staleNotice`, the `note` of `planEvaluate` and `planProbe`
     (each branch), `leanPathViolation`, `trimProfile`'s `trimmed_for_model`, `spendFooter`, and the
     `ResultTrimmer` stub and `compactDiagnostics` pointer and warning-cut texts, each with fixed inputs.
  Never regenerate a golden file after this commit. If a moved string differs, the code is wrong, not the golden.
- [ ] 2. **Wire the shared numbers.** `agent-text/numbers.yaml` exists (ticket 05a). Add every further number that appears inside a
  string moved by this ticket **and** equals a constant in the code. The code reads the same keys: `spend.ts` derives
  `FINISH_REMAINING_FRACTION` from `finish_remaining_pct / 100`; `campaign.py` sets `MAX_SOURCE_LINES` and
  `MAX_SCAN_FILES` from `arena.text.numbers()` (keys `source_lines_per_call`, `find_files_per_query`); `rules.ts`' `planProbe`
  and `campaign.py`'s `probe_batch` take the draft limit (`max_drafts`) from it; the hard-coded `0.1` / `10%` / `0.10` beside
  the finish rule in `rules.ts` become the same key. Stale or odd numbers inside existing text are moved as they are:
  ticket 16 fixes them.
- [ ] 3. **Move the Python tool-reply and error text** into `agent-text/replies/<area>.yaml` (areas: `evaluate`,
  `probe`, `profile`, `idea`, `state`, `finish`, `candidate`, `source`, `declarations`, `find`, `merge`,
  `submission`, `check`) and `agent-text/messages/errors.yaml`, with keys named after the situation
  (`replies/probe.too_many_drafts`). One key per sentence the model can read. The functions keep returning the same
  JSON; only the text values come from `arena.text.render`.
- [ ] 4. **Move the TypeScript text.** `agent-text/tools/<tool>.yaml` (a `description` and a `params` map per tool,
  all 11 tools), `agent-text/messages/footer.md`, `refusals.yaml` (`finishPush`, `continuationPush`,
  `allowanceFacts`), `continuation.md`, `arena-line.md` (`stateLine`/`briefText` pieces), `trim.yaml` (stubs and
  pointers), `notices.yaml` (the `planEvaluate`/`planProbe` notes, block reasons, idea auto-close reasons, `[arena]`
  stale-route line). `arena.ts`, `rules.ts`, `trim.ts` and `spend.ts` call `render(...)`; Typebox parameter
  descriptions become `description: render("tools/arena_probe.params.drafts", {...})`. Update `rules.test.ts`,
  `trim.test.ts` and `spend.test.ts` to call the same functions and compare with the goldens or with `render` output,
  not with string literals copied from the source.
- [ ] 5. **`agent-text/shown.yaml`**: for every template file under `agent-text/` (those of ticket 05a included), `where` (for example
  "system prompt addendum", "first user message", "tool list, every request", "tail of every tool result") and `per_run` (for
  example "once", "every request"). Fill each from the code that uses the template. A test fails if a template file has no
  entry. Extend `arena text budget` (`arena/cli/text.py`) with the columns "where shown" and "per run" read from it, in the
  Rich table, the `--json` output and the `--write` README table; the count stays in words.
- [ ] 6. **The literal lint** (`tests/test_text_lint.py`, last commit). It fails when model-facing prose is in code.
  - Python: parse each of `arena/campaign.py`, `arena/context.py`, `arena/memory.py`, `arena/engine.py`,
    `arena/routes.py`, `arena/profile.py`, `arena/merges.py`, `arena/goalstate.py`, `arena/skill.py` with `ast`.
    Every string constant that is not a docstring, with **four or more whitespace-separated words** (for an f-string,
    the constant parts joined), is a failure unless its first line, or the line above, carries the comment
    `# not-model-facing`.
  - TypeScript: scan `arena.ts`, `rules.ts`, `trim.ts`, `spend.ts` for string and template literals outside comments
    (a small tokenizer in the test: handle `"..."`, `'...'`, backticks with `${...}` replaced by a space, and
    `//` and `/* */` comments). Four or more words fails unless the line ends with `// not-model-facing`.
  - Mark only strings that provably never reach the model (log lines, `console.error`, exceptions caught and
    replaced, the `/arena` slash-command help for humans, internal subprocess code strings such as the
    `import sys; ...` snippet in `_record_route_later`). **Check where each goes before marking.** List every marked
    string (file, line, why) in the hand-back.
  - Unit-test the scanner itself on small snippets: an unmarked sentence is reported, a marked one is not, a docstring
    is not, a three-word literal is not, an f-string made of short pieces that adds up to four words is reported, a
    TS template literal with `${}` is handled, a `//` inside a string is not a comment.
- [ ] 7. **Byte-identical gate.** `tests/test_agent_text_messages_golden.py` (fast part), `agent-text-golden.test.ts` and, for the
  tool definitions, its `@slow` test (item 1) pass unchanged after items 2-4. A fast test in `tests/test_text.py` also
  renders every `tools/<tool>` description and parameter description and compares it with the `tool_definitions` golden.
  They are the proof that nothing was reworded. Run them after each moving commit. The goldens of ticket 05a must still pass.
- [ ] 8. **Update `agent-text/README.md`** with the final budget table (`arena text budget --write`), now with the where-shown and per-run columns.

## Do NOT

- Do not reword, reorder, fix typos in, or shorten any model-facing text: this ticket moves bytes. Stale or
  neutrality-violating text stays until ticket 16.
- Do not add the neutrality grep or the one-rule-one-place consistency tests: they would fail on verbatim text and
  belong to ticket 16.
- Do not change tool names, parameters, schemas, JSON keys or ledger rows: only the human text values move.
- Do not compute new per-theorem numbers or change which numbers the packet shows. Only constants that already exist in
  code move to `numbers.yaml`.
- Do not add a YAML library, a template engine, Jinja, or `str.format` on user-controlled text.
- Do not move text the model never reads (logs, exceptions that are caught, operator CLI output, Lean files);
  mark it instead.
- Do not touch the packet, skill or memory templates of ticket 05a, and do not regenerate any golden file after its first
  commit. Do not edit `docs/`.
- Do not touch the tool surface (tickets 15a-15c replace the old tools). Texts of tools that will be deleted are still
  moved now.

## Acceptance

- `grep` of the model-facing modules finds no unmarked sentence (the lint passes).
- `arena text budget` prints a table covering every template file with where-shown and per-run columns; the README
  table is current.
- Every moved message and every tool description match the goldens.
- Removing a placeholder value in a call, or adding an unused one, fails loudly.
- A Pi-backed run (fake provider) still starts, shows the skill in its first request and lists the tool descriptions.

## Verify

- `uv sync` -> ok.
- Targeted files first: `uv run pytest -q -p no:cacheprovider tests/test_text.py tests/test_text_lint.py
  tests/test_agent_text_messages_golden.py tests/test_agent_text_golden.py tests/test_campaign.py` -> all pass (add any
  other test file whose messages you changed).
- `cd packages/arena-pi && npm test` -> all pass (baseline plus the new tests).
- Then the fast suite, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count + the new tests).
- `uv run ruff check <touched files> && uv run ruff format --check <touched files>` -> clean;
  `uv run ty check arena/text.py arena/cli/text.py` -> no diagnostics.
- `uv run arena text budget` and `uv run arena text budget --json | uv run python -m json.tool > /dev/null` -> table, valid JSON.
- `uv run arena text budget --write && git diff --stat -- agent-text/README.md` -> no further change.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_agent_text_messages_golden.py -k tool_definitions` -> pass
  (Pi and the fake provider; no Lean: the tool-description slow test). Then
  `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_runner.py -k LifecycleTests` -> pass. One slow command at a time.
- Known pre-existing slow failures (also fail on tag v6; do not fix unless this ticket is about them):
  `tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas`
  and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`
  (fixed by tickets 15c/16); `LeanMcpTests` is flaky.

## Stop and report if

- `tool_definitions` cannot be captured from the fake provider (for example Pi does not pass descriptions to it).
- A string's text depends on logic that cannot be expressed as `{name}` / `{name:fmt}` placeholders plus ready-made
  fragments without changing a single byte of output.
- You cannot tell whether a string reaches the model: do not guess; list it and ask.
- A moved string would change output for any input you can construct (the golden differs).
- The ticket is too large for one context (it touches about 130 strings in 7 Python and 4 TypeScript files): stop at
  a clean commit boundary, hand back what is done, and say which items remain. Do not leave a half-moved file.

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

Your branch is **`v7/05b-agent-messages`**, already created and stacked directly above `v7/05a-agent-text`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/05b-agent-messages` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/05b-agent-messages -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-05b`.
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
- [ ] Every change is committed on `v7/05b-agent-messages`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-05b
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
