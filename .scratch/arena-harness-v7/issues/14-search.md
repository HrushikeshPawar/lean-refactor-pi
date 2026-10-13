# 14: Declaration index and search

**What to build:** At provisioning, per row, toolchain and header, the harness walks the Lean environment once and caches an index of every declaration visible from the theorem's imports: name, kind, pretty type, module, position, generated and private flags, the head symbol and constant set of its type. A new offline `search` function answers name, type and text queries from that index plus ripgrep over the pinned source trees. It returns, for each query, handles with a signature preview and a location. It covers Lean core and generated names, hints at look-alike names, and lists dot-completions. The model-facing `search` tool is wired to this in ticket 15a (handlers) and 15b (TS surface); this ticket delivers the index, the CLI commands and the Python search function with its tests.

**Blocked by:** 04: Move the remaining tools into the CLI; arena doctor; 05a: Agent text: format, renderers, numbers.yaml (all lower tickets, 05b to 13, are also committed below your branch).

**Status:** needs-review

**Branch:** `v7/14-search` (stacked on `v7/13-prices`)

**Read first:** spec "Declaration index and search" (Implementation Decisions), user stories 59-62 and 66; plan §4d (all of it, including the four layers and "Phase 0 checks"), §4b table row `lean_local_search` and `lean_completions`, §4c row `arena_find`, §12b #18 text in `docs/ISSUES-harness-v7.md` ("Name search misses Lean core and generated declarations"), §12e; decisions D19 (offline only), D20 (completions through `search`), D33, D34.

## Context: where things are now
- `arena/context.py` `lean_context(name)`: builds a candidate file with `arena.engine.candidate_file`, inserts `arena/lean/context.lean` (placeholders `@@ROOTS@@`, `@@TARGET@@`) before the theorem, runs it with `run_lean`, and caches the parsed records with `_cache("context", ...)` under `runs/cache/context/`. The cache salt includes the whole text of `context.lean`, so **editing `context.lean` invalidates every cached kickoff context and risks changing the packet**. Do not edit it.
- `arena/lean/context.lean`: the environment walk. It uses `env.constants.map₁` (imported) and `map₂` (this file), `env.getModuleIdxFor?`, `isPrivateName`, a `generatedName` test (`generatedSuffixes` list, `match_N`, `eq_N`, `isInternal`) and `sigOf` (`ppExpr` of the type). It reads declaration ranges of imported modules from the olean server part through `arena_moduleRanges` (modules built with the module system do not expose them through the environment).
- `arena/lean/declaration.lean`: `arena_decl`, kind names used today (`theorem`, `def`, `inductive`, `constructor`, `opaque`, `recursor`, `quot`; axioms are reported as `theorem`).
- `arena/campaign.py`: the v6 lookup code, **left untouched by this ticket** (ticket 15c deletes it): `find` / `_find` (text scan capped by `MAX_SCAN_FILES = 30`, no Lean core, no generated names), `declarations`, `source_range`, `_roots(project, commit)` (project plus locked git dependencies), `_package_roots`, `_module_file`, `_stdlib_source` and `STDLIB_ALIAS = ".lean-stdlib/lean/"` (Lean core source by version), `_LEAN_NAME` (identifier regex), `_declaration_suggestions`, `_HANDLE_SUFFIX`. The handle form is `decl:<qualified name>`.
- `arena/engine.py`: `problem(name)`, `versions(row)`, `measure_version(row)`, `workspace(row, version, commit)`, `candidate_file(...)`, `run_lean(...)`, `_proof_length(proof, statement=None)` (the pinned official token counter, through `arena/vendor.py`).
- `tools/provision_workspace.py` (moved into the CLI by ticket 04 as `arena provision`; find the current location with `grep -rn "def provision" arena tools`): provisions one worktree per (row, version). Header opens are 5 to 90 s; ArkLib is the largest.
- `/usr/bin/rg` (ripgrep) is installed. `sg` on this machine is util-linux, not ast-grep. Do not use it.
- `arena/cli/` is the Cyclopts app. Register new commands the way ticket 04 registered its commands.

## What to build
- [ ] 1. **Lean index command.** Create `arena/lean/index.lean` (a new file, not an edit of `context.lean`). It defines one `elab "arena_index" ...` command that walks the whole environment at the point where it is inserted and writes **one JSON object per line to a file** whose path is substituted for `@@INDEX_PATH@@` (use `IO.FS.Handle`, not `logInfo`: a Mathlib environment has several hundred thousand constants and must not go through stdout). Fields per object: `name`, `kind` (`theorem`, `axiom`, `def`, `opaque`, `inductive`, `structure`, `class`, `constructor`, `recursor`, `quot`, `instance`), `module` (the module name; `"(this file)"` for `env.constants.map₂`), `line` and `end_line` (declaration range, from `findDeclarationRanges?` for this file and `arena_moduleRanges` for imported modules, as `context.lean` does; null when unknown), `generated` (the same test as `context.lean`: copy its `generatedSuffixes` list and rules into `index.lean` and add a one-line comment that they mirror `context.lean`), `private` (`isPrivateName`), `type` (the pretty-printed type, clipped to 600 characters; **omitted for generated and private declarations** to keep the dump small), `head` (the head constant of the conclusion after stripping foralls, as `headOf (stripPi ..)` in `context.lean`; empty if none), `consts` (the used constants of the type, at most 40, internal names and instances removed). Take only the helpers you need from `context.lean`; do not import or share Lean code between the two files.
- [ ] 2. **Python index module `arena/index.py`.** Functions:
  - `build_index(name: str, version: str | None = None) -> dict`: builds the file for the row's primary (measure) version, or the given listed version, the way `lean_context` builds its file (`candidate_file`, insert `index.lean` before the theorem, `run_lean` with `CONTEXT_TIMEOUT`-style timeout of its own, constant in the module). Lean writes the JSONL to a temporary path next to the cache file; Python loads it into a **SQLite database** (stdlib `sqlite3`) with a table `declarations` and indexes on `name` (case-insensitive), `head` and the last name component. The cache path is `runs/cache/index/<row>-<version>-<commit12>-<digest12>.sqlite`, where the digest covers `index.lean` source, the header text (the file text before the theorem, so an import change gives a new index) and the schema version string defined in the module. Return `{"path", "declarations", "bytes", "seconds", "cached": bool}`. If the cache file exists, return it without running Lean.
  - `index_path(name, version=None) -> Path | None` (the cached file if present, never starts Lean) and `open_index(name, version=None) -> sqlite3.Connection` (raises `ValueError("declaration index missing for <row> <version>; run: arena index build <row>")` if absent).
  - For this-file declarations apply the same line shift `parse_context` applies to `local` and `goal` records, so their `line` values are lines of the original source file. If you cannot make this exact, store the lines as null and say so in the hand-back; do not guess.
- [ ] 3. **CLI.** Add `arena index build <row> [--version V]` (builds, prints path, declaration count, size, seconds; `--json` per the other reporting commands) and `arena index status [<row>]` (per listed version: present, path, size, age). Hook `build_index` into `arena provision` so that after each successfully provisioned (row, version) step the index is built; a failed index build prints `index FAILED: <reason>` and makes provisioning exit non-zero, but never undoes the provisioned worktree.
- [ ] 4. **Search module `arena/search.py`** with `search(theorem: str, queries: list[str], kind: str = "name", after: str | None = None, limit: int | None = None) -> dict`. It returns **data only, no prose** (ticket 15a renders replies from templates in `agent-text/replies/search.md`):
  ```
  {"kind": "name", "queries": [
     {"query": "...", "hits": [{"handle": "decl:Nat.add_comm", "name": "Nat.add_comm", "decl_kind": "theorem",
        "signature": "Nat.add_comm : ∀ (n m : ℕ), n + m = m + n",
        "module": "Init.Data.Nat.Basic", "file": "Init/Data/Nat/Basic.lean", "line": 123,
        "why": "exact"}],
      "hint": null, "truncated": false, "error": null}]}
  ```
  `why` is one of `exact`, `suffix`, `prefix`, `substring`, `fuzzy`, `confusable`, `type`, `text`, `completion`. A bad query yields `"error": {"code": ..., "input": ...}` with codes `empty_query`, `bad_kind`, `not_found`, `no_index`, `search_failed` **for that query only**; one bad query never rejects the batch (story 66). A bad `kind` is an error on every query with `valid: ["name", "type", "text"]`. The default `limit` and the maximum come from `agent-text/numbers.yaml` keys `search_hits_default` and `search_hits_max` (add them there with values 10 and 30 if ticket 05a has not; the Python code reads that file through the loader ticket 05a added). Signature preview is `name : type` clipped to 300 characters. Declarations flagged `private` or `generated` never appear in hits.
- [ ] 5. **`kind: "name"`.** Match order, each class ranked after the previous: exact full name; exact last component (`add_comm` finds `Nat.add_comm`), shortest name first; prefix of the full name or of the last component; case-insensitive substring; fuzzy (edit distance at most 2 on the last component, or a subsequence match for queries of 4 or more characters). The `decl:` prefix is accepted and means exact only. The result for a miss includes `suggestions` (up to 5 closest names). The fuzzy step must not scan every row in Python: use an SQL prefilter (length band and shared trigrams, or a trigram table built at index load). Latency goal on a Mathlib-sized index: name queries p95 at most 1 s including opening the database; report the measured p50 and p95.
- [ ] 6. **Confusable hint.** Normalise the query and every candidate by Unicode NFKC then casefold (so `ℱq` and `𝔽q` both become `fq`). When a name query has no exact hit but its normalised form equals exactly the normalised form of one or more visible names, return those as hits with `why: "confusable"` and set `hint` to `{"query_char_codes": [...], "name": "<the name>"}` (the code points of the differing characters, so ticket 15a can print them). Prefer, when several match, names that occur in the theorem statement text (take the statement from `problem(name)["statement"]`).
- [ ] 7. **`kind: "type"`.** The query is Lean type text such as `∀ a b : ℕ, a + b = b + a` or `List.length (_ ++ _)`. Tokenise it with `_LEAN_NAME`-style identifiers (import the regex from `arena.campaign` only if that module is still importable without side effects; otherwise copy the one-line pattern with a comment), keep tokens that resolve to a visible name exactly or by a unique last component. Rank declarations by IDF-weighted overlap between the resolved set and the declaration's `consts` plus `head`, with a fixed bonus when the declaration's `head` is in the resolved set (IDF over the whole index, computed once and stored in a small table at build time). Return up to `limit` hits with `why: "type"`. If no token resolves, return `error: {"code": "no_constants", "input": query}` for that query. This is a light stand-in for Loogle, not a unifier: do not try to parse binders or unify.
- [ ] 8. **`kind: "text"`.** Run `rg --json --fixed-strings --ignore-case --glob '*.lean' --max-count 50 -- <query>` over: the project root, each locked dependency root from `campaign._roots(project, commit)`, and the Lean core sources for the version (resolve like `campaign._stdlib_source` / `STDLIB_ALIAS`; if the core source directory cannot be found for a version, search the others and add `"core_source": false` to the result). Map each hit to the enclosing declaration by (file, line) against the index (`file` from `module`; `line <= hit <= end_line`, nearest start wins). Keep only hits whose declaration is in the index and is neither private nor generated (this is the visible-set filter). One entry per declaration with `why: "text"` and a `match` field holding the first matching line clipped to 160 characters. Count hits dropped as outside any declaration or not visible in `dropped` (a number) on the query. Run `rg` with a 20 s timeout; on timeout return `error: {"code": "search_failed", "input": query}` for that query. If `rg` is not installed raise a clear error at the start of the call (not per query).
- [ ] 9. **Completions.** `after` is a namespace or type name such as `Nat`, `List.Perm` or `Real.sqrt` (decision: plan D20 says "what follows `h.`", but the harness cannot know a local hypothesis's type here, so this ticket takes the namespace explicitly; list it under Open questions). `search(theorem, ["<prefix>"], kind="name", after="Nat")` returns visible declarations whose name is `after + "." + <component>` with the component starting with the query (an empty-string query is allowed only when `after` is set and lists the first `limit` members, shortest first), one namespace level deep, `why: "completion"`.
- [ ] 10. **One handle form and resolver.** Handles are `decl:<qualified name>`. Add `resolve_handle(theorem, handle) -> dict | None` returning `name, decl_kind, signature, module, file, line, end_line` from the index; ticket 15a's `read` uses it. A `decl:` handle for a generated or private name resolves with `generated`/`private` true (reading is allowed; search never lists them).
- [ ] 11. **Test fixtures.** Add `tests/fixtures/declaration_index.jsonl` (about 40 records in the exact JSONL schema of checkbox 1: `Nat.add_comm`, `Nat.add_assoc`, `List.length_append`, `Real.sqrt` namespace members, a `ℱq` and a `𝔽q` pair, `Foo.casesOn` and `Foo.rec` (generated), a private name, a this-file declaration) and a small source tree `tests/fixtures/index_sources/` of three `.lean` files whose declaration lines match the fixture records. A test helper builds a SQLite database from the JSONL through the same loader `build_index` uses (split the loader out as `load_index(jsonl_path, db_path)` so tests do not need Lean).
- [ ] 12. **Tests (fast, no Lean, pure units behind the search function).** Name: exact before last-component before prefix before fuzzy, with an exact expected order for one query. Generated and private declarations never appear in any kind. Confusable: `ℱq` finds `𝔽q` with `why: "confusable"` and a hint naming both. Type: a query naming `List.length` and `HAppend.hAppend` ranks `List.length_append` first. Text (skip with `skipUnless(shutil.which("rg"))`): a string inside a fixture proof body returns its enclosing declaration's handle, once, and a hit in a non-visible declaration is dropped and counted. Completions: `after="Nat"` and prefix `add` lists exactly `Nat.add_assoc`, `Nat.add_comm`. Batch: a list with one empty query and one valid query returns an error for the first and hits for the second.
- [ ] 13. **Slow test (`@slow`, `tests/slow.py`).** Build the real index for `Core.InitsUpdatesComm` (Strata, v4.29.1) with `build_index`; assert that `Nat.add_comm` (a Lean core name) is found by `search(..., kind="name")`, that at least one generated name (`*.casesOn`) is in the database but not in any search result, that a text query for a string known to occur in the row's source file returns its enclosing declaration, and that a second `build_index` call returns `cached: true`.
- [ ] 14. **Measure and report** (in the hand-back, do not assert in tests): for Core.InitsUpdatesComm and for `putnam_1964_b2` (Mathlib, v4.25.0) the build time, the index file size, the declaration count and name-query p50/p95. Run the Mathlib build with nothing else using Lean.

## Do NOT
- Do not edit `arena/lean/context.lean`, `arena/context.py`'s `lean_context`, or anything that changes the packet text. `uv run arena text render` (if ticket 05a added it) or `render_packet` output for a cached row must stay byte-identical.
- Do not delete or change `arena/campaign.py` `find`, `declarations`, `source_range` or their tests. Ticket 15c removes the old tools.
- No name token-cost column anywhere (search hits, index, packet): the official counter scores any identifier as one token (verified: `Nat.add_comm_of_very_long_name_here`, `𝔽q` and `Nat.add_comm` each count 1), so the column carries no information (decision 2). Keep the ranked top-60 library as it is.
- No remote search (Loogle, LeanSearch, LeanFinder, hammer), no ast-grep, no embedding index, no network, no model calls (D19, Out of Scope).
- No proof advice: `search` returns names, types and locations only. Do not rank by "what closes this goal".
- No model-facing sentences in Python: return codes and data; wording belongs to ticket 15a's templates.
- Do not add Python dependencies. Standard library, the existing environment and `rg` only.
- Do not make provisioning fail when only the index fails after the worktree is built; the exit code reports it, the worktree stays.

## Acceptance
- `uv run arena index build Core.InitsUpdatesComm` prints a path, a declaration count in the tens of thousands or more, a size and seconds; a second call prints `cached`.
- `search("Core.InitsUpdatesComm", ["add_comm"], kind="name")` returns `Nat.add_comm` with a `decl:` handle, a signature and a module and line; `["Nat.casesOn"]` returns no hit and a `not_found` error with suggestions, while `resolve_handle(..., "decl:Nat.casesOn")` resolves.
- A look-alike pair in the fixture is found through the confusable hint; completions under `Nat` list members one level deep.
- A text query returns declarations (not raw lines) filtered to the visible set; the old 30-file cap no longer exists in the new code.
- The packet for an already cached row is byte-identical before and after this ticket.

## Verify
Test budget: targeted files first, the fast suite once at the end. The slow file is listed because the index is built by real Lean; never `ARENA_SLOW_TESTS=1` over all of `tests/`.
- `uv run pytest -q -p no:cacheprovider tests/test_index.py tests/test_search.py` -> all fast tests pass (the slow ones skip).
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_index.py tests/test_search.py` -> all pass (one Lean process at a time).
- `uv run arena index build Core.InitsUpdatesComm --json` -> JSON with `declarations`, `bytes`, `seconds`; rerun shows `cached: true`.
- `uv run arena index status --json` -> lists the built index and the versions still missing.
- `uv run ruff check arena/index.py arena/search.py tests/test_index.py tests/test_search.py && uv run ruff format --check arena/index.py arena/search.py tests/test_index.py tests/test_search.py` -> clean; `uv run ty check arena/index.py arena/search.py` -> no diagnostics.
- At the end, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count plus the new fast tests); `cd packages/arena-pi && npm test` -> all pass, unchanged count.
- Known pre-existing slow failures in `tests/test_runner.py` (`...test_continuation_names_the_best_candidate_and_the_models_active_ideas`, `...test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`) are not yours: ticket 15b rewrites them. `LeanMcpTests` is flaky.

## Stop and report if
- The index build for the Mathlib row takes more than 30 minutes or the SQLite file is larger than 1.5 GB. Report the figures and what dominates (type printing or range reading); do not shrink the index on your own.
- Declaration ranges cannot be read for imported modules on one of the toolchains (v4.25.0 or v4.29.1); report which fields are null.
- `index.lean` cannot be inserted the way `lean_context` inserts `context.lean` (for example a header that only allows one `elab`). Report; do not edit `context.lean`.
- A fuzzy or type query on the Mathlib index cannot meet a 1 s p95 with an SQL prefilter.
- `rg` is missing on the machine.

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

Your branch is **`v7/14-search`**, already created and stacked directly above `v7/13-prices`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/14-search` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/14-search -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-14`.
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
- [ ] Every change is committed on `v7/14-search`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-14
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
