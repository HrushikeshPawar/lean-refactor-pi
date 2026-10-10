# 05a: Agent text: format, renderers, numbers.yaml, skill/packet/memory moved verbatim, `arena text`

**What to build:** The strings the model reads in the system prompt and the first user message (the skill, the packet
prose, the compaction memory) move, word for word, out of Python into one root-level directory, `agent-text/`, as
logic-free templates. A strict renderer (Python and TypeScript, the same rules, one shared case file) fills `{name}` and
`{name:fmt}` placeholders and fails on any missing or unused key. Harness constants that the text states (the 10% finish
rule and a few list sizes) live once in `agent-text/numbers.yaml`. A golden test proves the move changed nothing: the
system prompt, the packet and the memory text render byte-identical to what the code produced before. Operators get
`arena text render` and `arena text budget` (a table of what each template costs in **words**). **This ticket does not
reword anything**: the rewrite is ticket 16. The campaign, engine and TypeScript messages, `shown.yaml` and the literal
lint are ticket 05b.

**Blocked by:** 04: Move the remaining tools into the CLI; arena doctor (this ticket edits `arena/cli/run.py` and adds a sub-app to `arena/cli/__init__.py`).

**Status:** ready-for-agent

**Branch:** `v7/05a-agent-text` (stacked on `v7/04-cli-tools`)

**Read first:** spec "Modules" -> "Agent text", "Testing Decisions" (pure units), stories 36-45 and 108; plan §2
(2a layout, 2b rules, 2c tests, 2e order), §1d (where the text is today); decisions D3, D4, D6, D18.

## Context: where things are now

Model-facing text this ticket moves (the rest, in `arena/campaign.py`, `engine.py`, `arena.ts` and the other TypeScript
files, is ticket 05b):

- `packages/arena-pi/skills/arena-lean/SKILL.md`: the skill (YAML front matter, then Markdown). `arena/skill.py`:
  `SKILL_DIR`, `skill_hash()` (hash of every file under the directory), `skill_prompt()` (the body without front
  matter, stripped; `arena run` appends it with `--append-system-prompt`). `ARENA_SKILL_DIR` is set from
  `SKILL_DIR` in `arena/cli/run.py` (ticket 04 moved it from `tools/run_pi_budgeted.py`), and the `arena_skill_read`
  tool in `packages/arena-pi/extensions/arena.ts` reads files under it.
- `arena/context.py`: `SCORING_FACTS`, `_rates()`, `render_packet()` (the task lines, section titles such as
  "Pinned environment and candidate", "Reference proof (N tokens)", and the manifest lines), `EARLIER_TITLE`,
  `LOCAL_TITLE`, `LIBRARY_TITLE`, `_profile_section()`, `_goal_section()`, `_types_section()`, `_used_section()`,
  `_dependency_section()`, `_local_section()`, `_library_section()`, `_earlier_section()`, `_scope_section()`.
- `arena/memory.py`: `memory_text()` (the text injected after a compaction), `_metrics()`, `_idea()`.
- Tests that read these strings from source files: `tests/test_context.py` (the class that reads `context.py`,
  `arena.ts` and `SKILL.md` for the route-rule phrase), `tests/test_runner.py` (`SkillAndThinkingTests`,
  `SkillToolNamesTests`, which use `SKILL_DIR`).
- `arena/engine.py` has `_proof_length(text)`, the pinned competition token counter. `arena text budget` does **not**
  use it (owner decision 10: words).
- `arena/cli/__init__.py` is the Cyclopts app; sub-apps are registered there (`lean`, `graph`, ...).
- The repo has no YAML dependency: `arena/models.py` has its own small parser, and the TypeScript side has no
  third-party packages (no lockfile). Do not add a dependency; item 2 specifies a small YAML subset and a parser on
  each side.

## What to build

Work in this order, as separate commits (every commit leaves the fast suite and `npm test` green).

- [ ] 1. **Golden outputs first (test-only commit, before any move).** On the unmodified code, create
  `tests/test_agent_text_golden.py` with `tests/fixtures/agent_text_golden.json`. Each golden entry is
  `{"id", "source", "expected"}`: `source` names the file and function the text came from (for the reviewer), `expected` is
  the exact output of the pre-move code. Cases (the messages, tool definitions and TypeScript functions get their goldens
  in ticket 05b):
  1. `arena.skill.skill_prompt()` (the whole system-prompt addendum).
  2. `arena.context.render_packet(name)` for `Core.InitsUpdatesComm` and one more row of your choice, with
     `lean_context`, `reference_profile` and any other function that needs Lean or a provisioned workspace patched
     to return saved data (copy the cached context and profile JSON that `arena.context._cache(...)` names for these
     rows from `runs/cache/` into `tests/fixtures/`; keep the smallest files that exist). The test must pass on a
     machine with no `workspaces/`. If more than four functions need patching, **stop and report**.
  3. `arena.memory.memory_text` with three `front` dictionaries (empty; one with a best candidate, routes, ideas,
     failures and an advisory; spend given and not given).
  Never regenerate a golden file after this commit. If a moved string differs, the code is wrong, not the golden.
- [ ] 2. **The format, and the Python renderer.** Create `agent-text/README.md` (how to edit, the format below, and
  the budget table markers `<!-- budget:start -->` / `<!-- budget:end -->`) and `arena/text.py`. Format:
  - A `*.md` file is one template. Its key is its path under `agent-text/` without the extension
    (`skill/SKILL`, `packet/task`).
  - A `*.yaml` file is a map. A key inside it is `<file path without extension>.<key>`, with nested maps joined by
    dots (`tools/arena_probe.params.drafts`). The YAML subset: `#` comment lines; `key: value` with a plain scalar
    (the rest of the line, trimmed), a double-quoted scalar (JSON escapes), or a block scalar `|-` (lines indented
    two spaces deeper, joined with `\n`, no trailing newline) or `|` (same, one trailing newline); nested maps by
    two-space indentation. Nothing else (no lists, anchors, flow style). All values are strings, except in
    `numbers.yaml`, whose plain scalars become `int` or `float`.
  - Placeholders: `{name}` and `{name:fmt}`, where `name` matches `[a-z][a-z0-9_]*` and `fmt` is one of `d`,
    `.Nf` (N is a digit), `g` (general format, as Python's `format(x, "g")`). A literal brace is written `{{` or
    `}}`. Any other use of braces is a parse error that names the key.
  - `render(key, **values) -> str` is strict: a placeholder with no value (in `values` or in `numbers.yaml`) raises
    `TextError` naming key and placeholder; a supplied `values` key that no placeholder uses also raises. Values
    from `numbers.yaml` are available to every template without being passed; a `values` key that collides with a
    numbers key raises. `template(key)` returns the raw text; `keys()` lists all keys; `numbers()` returns the
    numbers dict. Files are read once and cached; `ARENA_TEXT_DIR` overrides the directory (tests).
  - Templates contain no logic. Where the code has a plural or a conditional (`attempt${n === 1 ? "" : "s"}`,
    `" (not yet verified)"`), the template has a placeholder (`{attempts} attempt{s}`) and the code passes the ready-made
    fragment. Never split a sentence across keys just to avoid a placeholder.
- [ ] 3. **Tests for the Python renderer and the format** (`tests/test_text.py`, pure): the YAML subset parses
  to the expected structure (use the shared cases file in item 4); `render` formats `{x:.2f}`, `{n:d}`, `{v:g}`;
  `{{` escapes; a missing key, an unused key, a numbers collision and a stray brace each raise `TextError` with the key
  in the message; every template under `agent-text/` parses and every placeholder in it is a `numbers.yaml` key or
  is supplied by a renderer (the last part is enforced by the renderers' own strict calls plus the byte-identical test;
  do not duplicate it by listing keys).
- [ ] 4. **The TypeScript renderer** `packages/arena-pi/extensions/text.ts`: `render(key, values)`, `template(key)`,
  `numbers()`, the same parser and the same errors (throw `Error` with key and placeholder in the message). The
  directory is `process.env.ARENA_TEXT_DIR ?? resolve(import.meta.dirname, "../../../agent-text")`. No dependency.
  `text.test.ts` runs the **shared cases** `tests/fixtures/text-cases.json` (create it: a list of
  `{"files": {path: content}, "key", "values", "expect"}` or `{"error": "<substring>"}`); the Python tests of item 3
  run the same file, so the two renderers cannot drift.
- [ ] 5. **`agent-text/numbers.yaml`.** Create it with at least `finish_remaining_pct: 10`, `max_drafts: 4`,
  `source_lines_per_call: 400`, `find_files_per_query: 30`, plus every other number that appears inside a string moved
  by this ticket (skill, packet, memory) **and** equals a constant in the code (check each digit run and number word,
  for example "four", "two or three"). Templates read these keys without being passed them. Wiring the code that holds
  those constants (`campaign.py`, `rules.ts`, `spend.ts`) to the same keys is ticket 05b: do not touch those files here.
  Stale or odd numbers inside existing text (for example "original scores only 33" in SKILL.md) are moved as they are:
  ticket 16 fixes them.
- [ ] 6. **Move the skill.** `mv packages/arena-pi/skills/arena-lean/SKILL.md agent-text/skill/SKILL.md` and remove the
  old directory. The file keeps its front matter. In `arena/skill.py`: `SKILL_DIR = ROOT / "agent-text/skill"`;
  `skill_prompt()` renders `skill/SKILL` through `arena.text` and returns the same text as before (front matter
  removed, stripped); `skill_hash()` becomes the sha256 of that rendered text (what the model actually reads; state
  this in the hand-back). `arena_skill_read` in `arena.ts` renders `.md` files it returns through `text.ts` (so the
  model sees what `skill_prompt()` gives, not raw placeholders). Update `ARENA_SKILL_DIR` users and the tests that
  name `packages/arena-pi/skills/...`.
- [ ] 7. **Move the packet and memory text.** Create `agent-text/packet/` (`task.md`, `scoring.md` for `SCORING_FACTS`,
  `rates.md`, `sections.yaml` for the section titles and fixed lines, `library.md`, `profile.md`, `inventory.md`) and
  `agent-text/messages/compaction-memory.yaml`. `context.py` and `memory.py` render them; dynamic parts (names,
  counts, rates, joined lists) are placeholders filled by the code. The packet and the memory text must be
  byte-identical to the goldens of item 1. `LOCAL_TITLE`, `LIBRARY_TITLE`, `EARLIER_TITLE` and the shed-order titles
  in `_fit()` keep working (they match section titles by prefix: read the same keys).
- [ ] 8. **`arena text`** (`arena/cli/text.py`, a sub-app registered in `arena/cli/__init__.py`):
  - `arena text render KEY [--var NAME=VALUE ...] [--json]` prints the rendered template; a missing or unused
    variable exits 2 with the `TextError` message. `arena text render --list` prints every key. `arena text render
    --skill` prints exactly what `skill_prompt()` returns.
  - `arena text budget [--json] [--write]` prints a Rich table: template file and **words** (owner decision 10: it counts
    WORDS, whitespace-separated, on the raw template text; it does not use the Lean token counter). Ticket 05b adds the
    columns "where shown" and "per run" when `shown.yaml` exists. `--write` replaces the text between the README markers
    with the same table as Markdown. A test (`tests/test_text.py`) fails if the README table differs from what `--write`
    would produce, so the table cannot go stale.
  - `--json` on both prints one JSON document.
- [ ] 9. **Byte-identical gate and README.** `tests/test_agent_text_golden.py` passes unchanged after items 5-7 (run it after
  each moving commit). Update `agent-text/README.md` with the final budget table (`arena text budget --write`).

## Do NOT

- Do not reword, reorder, fix typos in, or shorten any model-facing text: this ticket moves bytes. Stale or
  neutrality-violating text (for example the skill's strategy words, "original scores only 33") stays until ticket 16.
- Do not touch `arena/campaign.py`, `arena/engine.py`, `arena/routes.py`, `arena/profile.py`, `arena/merges.py`,
  `arena/goalstate.py`, `rules.ts`, `trim.ts`, `spend.ts`, or the tool descriptions in `arena.ts` (ticket 05b). The only
  `arena.ts` change here is `arena_skill_read` (item 6).
- Do not add the literal lint, `shown.yaml`, or the neutrality and one-rule-one-place consistency tests (05b and 16).
- Do not change tool names, parameters, schemas, JSON keys or ledger rows: only the human text values move.
- Do not compute new per-theorem numbers or change which numbers the packet shows (D3's "computed per theorem" is
  ticket 16). Only constants that already exist in code move to `numbers.yaml`.
- Do not add a YAML library, a template engine, Jinja, or `str.format` on user-controlled text. The renderer is the
  strict one of item 2.
- Do not move text the model never reads (logs, exceptions that are caught, operator CLI output, Lean files).
- Do not regenerate the golden files after the first commit. Do not edit `docs/`.
- Do not use the Lean token counter for `arena text budget`: words only.

## Acceptance

- `arena text render --skill` equals the old `skill_prompt()` byte for byte; `arena text render --list` lists the
  keys; `arena text budget` prints a table of words covering every template file; the README table is current.
- The packet of two rows and the memory text match the goldens.
- Removing a placeholder value in a call, or adding an unused one, fails loudly (renderer tests); the Python and
  TypeScript renderers pass the same shared case file.
- A Pi-backed run (fake provider) still starts and shows the skill in its first request.

## Verify

- `uv sync` -> ok.
- Targeted files first: `uv run pytest -q -p no:cacheprovider tests/test_text.py tests/test_agent_text_golden.py
  tests/test_context.py tests/test_memory.py tests/test_cli.py` -> all pass (use the real file names for the packet and
  memory tests).
- `cd packages/arena-pi && npm test` -> all pass (baseline 36 + `text.test.ts`).
- Then the fast suite, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count + the new tests).
- `uv run ruff check <touched files> && uv run ruff format --check <touched files>` -> clean;
  `uv run ty check arena/text.py arena/cli/text.py` -> no diagnostics.
- `uv run arena text render --list | wc -l` -> the key count; `uv run arena text render --skill | head -3` -> the
  skill's first lines (no front matter).
- `uv run arena text budget` and `uv run arena text budget --json | uv run python -m json.tool > /dev/null` -> table of words, valid JSON.
- `uv run arena text budget --write && git diff --stat -- agent-text/README.md` -> no further change.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_runner.py -k "SkillAndThinkingTests or SkillToolNamesTests"` -> pass
  (Pi and the fake provider; no Lean). The only slow command this ticket needs (the skill's location and the
  `arena_skill_read` tool changed).
- Known pre-existing slow failures (also fail on tag v6; do not fix unless this ticket is about them):
  `tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas`
  and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`
  (fixed by tickets 15c/16); `LeanMcpTests` is flaky.

## Stop and report if

- The packet golden cannot be made independent of Lean and workspaces with at most four patched functions.
- A string's text depends on logic that cannot be expressed as `{name}` / `{name:fmt}` placeholders plus ready-made
  fragments without changing a single byte of output.
- A moved string would change output for any input you can construct (the golden differs).
- The Python and TypeScript renderers cannot both pass the shared case file without a rule change.
- The ticket is too large for one context: stop at a clean commit boundary, hand back what is done, and say which
  items remain. Do not leave a half-moved file.

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

Your branch is **`v7/05a-agent-text`**, already created and stacked directly above `v7/04-cli-tools`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/05a-agent-text` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/05a-agent-text -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-05a`.
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
- [ ] Every change is committed on `v7/05a-agent-text`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-05a
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
