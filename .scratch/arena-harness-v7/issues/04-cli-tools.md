# 04: Move the remaining tools into the CLI; arena doctor

**What to build:** Every script left in `tools/` becomes a real Cyclopts command of the one `arena` CLI, with typed
flags (the same flag names as today), Rich output, and `--json` on the commands that report. `tools/` stops
existing: its code lives under `arena/cli/`, and the graph viewer's HTML, JS and CSS become package data. A new
`arena doctor` checks the things that drift silently (pins, vendor submodule commits, the benchmark hash, the Pi
version, the model price table, the official token counter, the optional Langfuse plugin patch). The Pi extension
keeps working unchanged: `arena protocol` stays the JSON contract it calls.

**Blocked by:** 03: CLI skeleton, vendor adapter, MiMo provider (committed below your branch).

**Status:** done

**Branch:** `v7/04-cli-tools` (stacked on `v7/03-cli`)

**Read first:** spec sections "Operator: CLI, packaging, tests" (stories 101-105, 107), "Modules" -> "CLI and
packaging", "Testing Decisions" (isolation); plan §7.0, §7.1 (command table), §7.2 (housekeeping: `benchmark/`,
`SHA256SUMS`, `measure-versions.json`), §2d (price check); decisions D1, D32, D38.

## Context: where things are now

- `arena/cli/__init__.py`: the Cyclopts `app`, `load_env()`, and pass-through commands `run`, `campaign`, `check`,
  `eval`, hidden `protocol`. Each takes `*tokens` and calls `_delegate("<tools module>", ...)`, which imports
  `tools.<module>` and runs its argparse `main()`. `main()` at the bottom is the `arena` console script.
- `tools/` (a namespace package: there is no `tools/__init__.py`) holds these scripts, each with an argparse
  `main()`:
  - `run_pi_budgeted.py` (the `arena run` body; also defines `MODELS`, `THINKING_LEVELS`, `CONFIG`,
    `attempt_has_model_error`, `autocheck`; `arena/package.py` and several tests import from it);
  - `run_campaign.py` (`arena campaign`; keeps unknown flags and forwards them to each run after `--`);
  - `arena_certify.py`, `arena_check.py`, `arena_eval.py`, `arena_merge_worker.py`, `arena_package.py`,
    `arena_preflight.py`, `arena_campaign.py` (the JSON protocol the Pi extension spawns);
  - `build_candidate_graph.py`, `serve_candidate_graph.py` (+ the asset folder `graph_viewer/`: `index.html`,
    `app.js`, `charts.js`, `dashboard.*`, `hub.*`, `highlight.js`, `style.css`);
  - `provision_workspace.py`, `provision_progress.py`, `run_experiment_matrix.py`, `lean_load_test.py`,
    `langfuse_plugin.py` (`--check` / `--apply` of the Langfuse plugin patch), `smoke_theorems.py` (a script with
    no `main()`; it imports `tests.pi_support.FakeRun`).
- Scripts start each other by path: `run_campaign.py`, `run_experiment_matrix.py` and `arena_preflight.py` build
  command lines with `[sys.executable, str(ROOT / "tools/run_pi_budgeted.py"), ...]` (and `tools/arena_preflight.py`).
  `tests/pi_support.py` (`FakeRun.command`) does the same with `tools/run_pi_budgeted.py`.
- The Pi extension `packages/arena-pi/extensions/arena.ts` spawns `uv run --no-sync arena protocol <action> ...`.
  Do not change that file in this ticket.
- Tests that import or spawn tools: `tests/test_campaign.py` (`from tools import run_campaign as rc`),
  `tests/test_lean_health.py` (`run_campaign as rc`, `run_pi_budgeted as rpb`), `tests/test_environments.py`
  (`arena_certify`), `tests/test_graph.py` (`tools.build_candidate_graph`, `tools.run_pi_budgeted`,
  `tools.serve_candidate_graph`, and `patch("tools.serve_candidate_graph...")` strings), `tests/test_viewer.py`
  (`from tools import serve_candidate_graph as server`; `ASSETS = ... / "graph_viewer"`),
  `tests/test_lean_load_test.py` (`from tools import lean_load_test as llt`), `tests/test_matrix.py` and
  `tests/test_traces.py` (spawn `tools/run_experiment_matrix.py`), `tests/test_protocol.py` (spawns
  `-m tools.arena_campaign`), `tests/test_package.py:244` (asserts `REPRODUCE.md` mentions
  `tools/arena_package.py`), `tests/test_cli.py` (pass-through tests).
- `arena/package.py` imports `MODELS` from `tools.run_pi_budgeted` and writes `tools/...` command names into the
  `REPRODUCE.md` text (around line 393-396).
- `arena/traces.py` has `plugin_problems()` and `apply_plugin()` (the Langfuse plugin check and patch).
  `arena/models.py` has `catalog_price_problems()` (Pi catalog prices against `models.yaml`).
  `arena/provenance.py` has `code_version()` (reads the installed Pi version from
  `~/.pi/agent/install/current-version`). `arena/vendor.py` has the vendor paths. `arena/engine.py` has
  `problem()`, `versions()`, `validate_proof()` (calls the official token counter) and `ROOT`.
- `arena/lean_session.py` has `serve(directory, parent, max_slots)` and a `main()` with a `serve` sub-command.
  The daemon is started with `python -m arena.lean_session serve ...` (`start_daemon`) and `arena/lean_health.py`
  recognises daemons by that command line. Leave all of that alone.
- `benchmark/SHA256SUMS` holds one line: the sha256 of `benchmark/original/warmup.jsonl`. Nothing checks it today.
  `.gitmodules` lists `vendor/lean-refactor` and `vendor/arena-space`.

## What to build

Module layout (use these exact names; one module per command, all under `arena/cli/`):

| Old file | New module | Command |
|---|---|---|
| `run_pi_budgeted.py` | `arena/cli/run.py` | `arena run` |
| `run_campaign.py` | `arena/cli/campaigns.py` | `arena campaign` |
| `arena_certify.py` | `arena/cli/certify.py` | `arena certify` |
| `arena_check.py` | `arena/cli/check.py` | `arena check` |
| `arena_eval.py` | `arena/cli/evaluate.py` | `arena eval` |
| `arena_merge_worker.py` | `arena/cli/merge.py` | `arena merge` |
| `arena_package.py` | `arena/cli/package.py` | `arena package` (ticket 19a replaces it with `arena submit`) |
| `arena_preflight.py` | `arena/cli/preflight.py` | `arena preflight` |
| `arena_campaign.py` | `arena/cli/protocol.py` | `arena protocol` (hidden) |
| `serve_candidate_graph.py` | `arena/cli/serve.py` | `arena serve` |
| `build_candidate_graph.py` | `arena/cli/graph.py` | `arena graph export` |
| `provision_workspace.py` + `provision_progress.py` | `arena/cli/provision.py` | `arena provision [--progress]` |
| `run_experiment_matrix.py` | `arena/cli/experiment.py` | `arena experiment` |
| `lean_load_test.py` | `arena/cli/lean_load.py` | `arena lean load-test` |
| (new) | `arena/cli/lean.py` | `arena lean serve`, `arena lean health` |
| `langfuse_plugin.py` + new checks | `arena/cli/doctor.py` | `arena doctor` |
| `smoke_theorems.py` | `arena/cli/smoke.py` | `arena smoke` |

- [ ] 1. **Fixtures first.** Before moving anything, run the baseline (see "Before you start"). Then, in
  `arena/cli/__init__.py`, add `arena/cli/__main__.py` (`from arena.cli import main` / `main()`), so
  `python -m arena.cli <command> ...` works. Subprocess command lines in the code and tests use
  `[sys.executable, "-m", "arena.cli", "<command>", ...]` from now on. Commit this as its own small commit.
- [ ] 2. **Move code without changing behaviour** (one commit per 2-3 modules, in this order: leaf tools
  `check`, `evaluate`, `certify`, `merge`, `package`; then `run`, `campaigns`, `preflight`, `experiment`; then
  `serve`, `graph`, `provision`, `lean_load`, `protocol`). Use `mv` so history follows. In each moved module:
  - replace `ROOT = Path(__file__).resolve().parents[1]` with `from arena.engine import ROOT`; delete the
    `sys.path.insert(...)` lines and the `if __name__ == "__main__"` block;
  - replace `from tools.<x> import ...` with `from arena.cli.<new module> import ...`;
  - replace every `str(ROOT / "tools/<script>.py")` command with `"-m", "arena.cli", "<command>"` as above;
  - keep every function, constant and class name the tests use (`rc.command`, `rc.plan`, `rpb.attempt_has_model_error`,
    `server.graph_payload`, `llt.percentile`, ...). Update the tests' imports and `patch("tools.serve_candidate_graph.x")`
    strings to the new dotted paths. Do not weaken or delete assertions.
- [ ] 3. **Real Cyclopts commands.** For each moved module, replace its argparse `main()`/`run()` with:
  - a frozen `@dataclass` of options whose field names are the old flag names with `-` -> `_` (so `--limit-usd` is
    still `--limit-usd`; Cyclopts maps `limit_usd` to `--limit-usd`), with the old types, defaults, `choices`
    (use `Literal[...]` for fixed choices) and help text (put the help text in the field docstring or
    `Parameter(help=...)`);
  - an `execute(options) -> int` function holding the old body, taking the dataclass where the body used
    `args.<name>`;
  - a command function in the module registered in `arena/cli/__init__.py` as
    `def run(options: Annotated[RunOptions, Parameter(name="*")]) -> int: ...` (Cyclopts flattens the dataclass;
    this is Cyclopts's documented pattern). Required flags stay required. `argparse` `required=True`,
    `nargs`, `action="append"` and `action="store_true"` map to required fields, `list[str]` fields and `bool`
    fields (Cyclopts gives bool flags a `--no-<name>` twin; that is fine, but do not rename `--no-skill`,
    `--no-mcp`, `--no-lean-session`, `--no-langfuse`: keep them as plain `bool` fields named `no_skill`, etc.).
  - Dynamic choices (`--model` from `models.yaml`, `--thinking` levels, `--preset`, `--factor`) are checked inside
    `execute` and fail with a clear message and exit code 2, because `Literal` cannot be built from a file.
  - Positional arguments (`arena eval NAME PROOF_FILE`, `arena graph export RUN_ID`, `arena serve RUN_ID...`,
    `arena package RUN_ID...`, `arena merge RUN_ID`) stay positional.
  - `arena campaign` keeps forwarding unknown flags to each run: declare `*passthrough` with
    `Parameter(allow_leading_hyphen=True)`; they are the tokens after `--`. `arena campaign ... --dry-run` must
    still print the planned `arena run` command lines and return 0 without spending.
  - `load_env()` stays called first by `run` and `campaign`, as now (preflight starts runs through `arena run`, which loads it).
  - Delete `_delegate`, `Tokens` and the pass-through docstring in `arena/cli/__init__.py`.
- [ ] 4. **`arena protocol` (hidden).** Convert `arena_campaign.py` the same way: same actions, same flag names
  (all 27, including `--spent-usd` and `--cap-usd`, which the `memory` action uses), same JSON on stdout,
  same exit codes. No Rich, no extra stdout: the Pi extension parses the last stdout line as JSON. Its commands
  stay `show=False`. `tests/test_protocol.py` spawns `[sys.executable, "-m", "arena.cli", "protocol", ...]` after
  this ticket.
- [ ] 5. **Rich output and `--json`.** Reporting commands print a Rich table or panel for people and print one JSON
  document with `--json`:
  `check`, `eval`, `certify`, `preflight`, `provision --progress`, `lean health`, `doctor`. The campaign run
  report (`arena campaign`) keeps writing `campaign.json` and `campaign.txt` as today; add a Rich table of the
  per-run rows to the terminal output and `--json` printing the same dict as `campaign.json`. Long-running
  commands (`run`, `campaign`, `provision`) keep their line-by-line progress output: Rich must not swallow it
  (use `console.print` per line, never a live display, so redirected logs still get every line).
  `arena certify` today has `--json PATH` meaning "write the results here": rename that option to `--output PATH`
  and make `--json` the boolean "print JSON".
- [ ] 6. **`arena lean`.** Add `arena/cli/lean.py`: a sub-app `lean` with
  - `serve --run-dir PATH [--parent-pid N] [--max-slots N]` calling `arena.lean_session.serve(...)`;
  - `health RUN [--json]` where RUN is a run id under `runs/pi-budget/` or a directory: print the run's
    `lean-health.json` (`arena.lean_health.read_health`) and the `lean-unhealthy.json` marker
    (`arena.lean_health.tripped`) in a table; exit 1 when tripped or missing;
  - `load-test ...` taking the old `lean_load_test` flags as typed options (as in item 3).
  Do not change how `lean_session.start_daemon` launches the daemon.
- [ ] 7. **`arena provision`.** One command: without `--progress` it is the old `provision_workspace` (flags
  `--row`, `--build-timeout`, `--full-cache`, `--version` repeatable, `--dry-run`, plus whatever the old parser
  has); with `--progress [--watch] [--only ...]` it is the old `provision_progress` display. No campaign lock
  exists yet (ticket 09 adds the overlap lock and the "refuse while a campaign runs" rule): do not add one here.
- [ ] 8. **Graph viewer as package data.** `mv tools/graph_viewer arena/graph_viewer`. In `arena/cli/serve.py` and
  `arena/cli/graph.py`, locate it with `Path(__file__).resolve().parents[1] / "graph_viewer"` (not through
  `ROOT`). Update `tests/test_viewer.py`'s `ASSETS` line. Confirm `uv build --wheel` includes the files (Verify).
- [ ] 9. **`arena smoke`.** Move `smoke_theorems.py` into `arena/cli/smoke.py` as `arena smoke ROW [ROW...]`
  (positional rows, exit 1 if any row fails, same PASS/FAIL line per row). It needs the Pi test fixture, so it
  imports `tests.pi_support` lazily inside `execute` and, if that import fails (not run from a checkout),
  prints "arena smoke needs a source checkout (tests/pi_support.py)" and exits 2. Wrap the old module-level code
  in `execute`.
- [ ] 10. **`arena doctor`.** In `arena/cli/doctor.py`: `arena doctor [--json] [--apply-langfuse-plugin]`. It runs
  these checks, each returning `(name, status, detail)` with status `ok`, `warn` or `fail`, never raising:
  1. **Pins.** Read `pi_version` from a new `[tool.arena.pins]` table in `pyproject.toml` (add
     `pi_version = "1.1.0"`; plan §7.2 allows `pyproject` or `models.yaml` for the pins, this ticket picks
     `pyproject`). Compare with `arena.provenance.code_version()["pi_version"]`: different -> `fail`; Pi not
     installed (`None`) -> `warn`. Also report the pinned Langfuse plugin version
     (`arena.traces.PLUGIN_VERSION`) as an `ok` line.
  2. **Vendor submodule commits.** For `vendor/arena-space` and `vendor/lean-refactor`: the commit checked out
     (`git -C <dir> rev-parse HEAD`) must equal the commit the repo records
     (`git ls-tree HEAD vendor/<name>` -> the gitlink hash), and `git -C <dir> status --porcelain` must be empty.
     Mismatch or dirty -> `fail`; submodule missing -> `fail`. Show the first 7 characters of each commit.
  3. **Benchmark hash.** `sha256` of `benchmark/original/warmup.jsonl` against the entry in
     `benchmark/SHA256SUMS` (format: `<hash>  <path>`, path relative to the repo root). Mismatch or missing
     entry -> `fail`.
  4. **Official token counter.** For all 15 rows of `warmup.jsonl`, `arena.engine.validate_proof(row, row["src"])`
     (the official counter through `arena.vendor`) must equal `row["proof_length"]`. Any difference -> `fail`
     listing the row names.
  5. **Price table.** `arena.models.catalog_price_problems()`: each problem string -> `fail` (one line per
     problem); an empty list -> `ok`; Pi not installed (the function returns an empty list) -> `ok`.
  6. **Langfuse plugin patch (optional).** `arena.traces.plugin_problems()`. If `traces.INSTALLED_PLUGIN` does not
     exist, status `warn` with "Langfuse plugin not installed (optional)". Otherwise problems -> `warn` (never
     `fail`: it is optional). `--apply-langfuse-plugin` first calls `arena.traces.apply_plugin()` (this
     replaces `langfuse_plugin.py --apply`), then runs the check.
  7. **Measure-version override file.** If `benchmark/derived/measure-versions.json` exists, every key must be a
     row name and every value a version listed for that row, else `fail`; a missing file is `ok` ("no overrides").
  Exit code 1 if any check is `fail`, else 0. Machine readings (Pi version, git output, hashes) come from small
  functions that the tests replace; no check calls Lean, a model or the network.
- [ ] 11. **Delete `tools/`.** After every module is moved: `git ls-files tools` must be empty and the directory
  must not exist (remove leftover `__pycache__` with `rm -r tools`). Update `models.yaml` comments, which say
  `tools/run_pi_budgeted.py` and `run_campaign.py`, to name `arena run` and `arena campaign`. Update
  `arena/package.py`'s `REPRODUCE.md` text to the new commands (`arena provision`, `arena run`, `arena package`)
  and `tests/test_package.py:244` to match.
- [ ] 12. **Tests (behaviour only).**
  - `tests/test_cli.py` (rewrite `PassThroughTests`): every command in the table answers `--help` with exit code 0
    (parametrized, in-process); `arena eval` without arguments exits non-zero; `arena campaign --prefix t
    --rows Core.InitsUpdatesComm --models deepseek-v4.1-flash --dry-run` exits 0 and prints one `run` line per
    planned run without creating `runs/` entries (seam: the CLI).
  - `arena campaign ... --models no-such-model --dry-run` exits 2 with the model named in the message (dynamic
    choice).
  - `tests/test_doctor.py`: each check function, fed injected readings, returns `ok` for a good fixture and `fail`
    for a bad one: wrong Pi version, a submodule whose HEAD differs from the gitlink, a dirty submodule, a
    benchmark hash mismatch, a token-counter mismatch on one row, a price problem; the optional plugin check is
    `warn`, never `fail`, when the plugin is missing or unpatched; `--json` output parses and has the keys
    `checks` (list of `{name, status, detail}`) and `ok` (bool). No test reads real git state, `~/.pi` or the
    network.
  - Existing tests that spawn tools (`test_protocol`, `test_matrix`, `test_traces`, `tests/pi_support.py`) pass
    through the new `-m arena.cli ...` command lines.
- [ ] 13. **Slow Pi path still works.** Run the Pi-backed run tests (see Verify): they start `arena run` through
  `tests/pi_support.py`, so they prove the extension, the runner and `arena protocol` still work together.

## Do NOT

- Do not edit `packages/arena-pi/extensions/*` (they already call `arena protocol`) or `docs/`.
- Do not change behaviour while moving: same flags, defaults, output files, exit codes, ledger rows. The one
  intended flag change is `arena certify --json PATH` -> `--output PATH` plus a boolean `--json`.
- Do not touch `arena/lean_session.py`'s daemon launch (`python -m arena.lean_session serve`) or
  `arena/lean_health.py`'s process matching.
- Do not add `arena submit`, `arena replay`, `arena text` or `arena lean bench` (tickets 19a, 17, 05a, 07).
- Do not add a `src/` layout, a new top-level package, or new runtime dependencies (Cyclopts and Rich exist).
- Do not convert `arena protocol` output to Rich or add output lines: stdout is a machine contract.
- Do not delete `arena smoke` for being "test-like"; the plan keeps it (plan §7.1: "keep, or move into pytest").
- Do not "fix" `benchmark/SHA256SUMS` or `warmup.jsonl` if the doctor reports a mismatch: report it.
- Do not change `engine.measure_version` or the `measure-versions.json` handling (ticket 06).

## Acceptance

- `arena --help` lists: run, campaign, certify, check, eval, merge, package, preflight, serve, graph, provision,
  experiment, lean, doctor, smoke (and not `protocol`); `arena lean --help` lists serve, health, load-test;
  `arena graph --help` lists export.
- `arena doctor` prints a table with the seven checks; on this checkout it exits 0 or reports a real finding
  (list each finding in the hand-back); `arena doctor --json` prints valid JSON.
- `arena campaign --prefix x --rows Core.InitsUpdatesComm --models deepseek-v4.1-flash --dry-run` prints the plan
  with `arena run`-style command lines and exits 0.
- `tools/` does not exist; `git grep -n "tools/\|tools\." -- ':!docs' ':!research' ':!vendor' ':!.scratch'` shows
  no reference to a removed script (references to `.tools.`, `tools.get(...)` or the Pi "tools" concept are fine).
- The wheel built from the project contains `arena/graph_viewer/index.html`.
- The Pi-backed `LifecycleTests` pass with the new command lines.

## Verify

- `uv sync` -> ok.
- Targeted files first: `uv run pytest -q -p no:cacheprovider tests/test_cli.py tests/test_doctor.py tests/test_protocol.py
  tests/test_campaign.py tests/test_lean_health.py tests/test_environments.py tests/test_graph.py tests/test_viewer.py
  tests/test_lean_load_test.py tests/test_matrix.py tests/test_traces.py tests/test_package.py` -> all pass.
- Then the fast suite, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline 491 collected; the count changes by the tests you
  rewrite or add: state the before and after in the hand-back).
- `cd packages/arena-pi && npm test` -> 36 pass (unchanged).
- `uv run ruff check <touched files> && uv run ruff format --check <touched files>` -> clean.
- `uv run ty check arena/cli` -> no new diagnostics (fix those in files you created or moved; do not touch others).
- `uv run arena --help` and `uv run arena lean --help` -> as in Acceptance.
- `uv run arena doctor` and `uv run arena doctor --json | uv run python -m json.tool > /dev/null` -> table, valid JSON.
- `uv run arena campaign --prefix t04 --rows Core.InitsUpdatesComm --models deepseek-v4.1-flash --dry-run` -> plan
  printed, exit 0, and `ls runs/pi-budget | grep t04` prints nothing.
- `test ! -e tools && git ls-files tools | wc -l` -> `0`.
- `d=$(mktemp -d) && uv build --wheel --out-dir "$d" && unzip -l "$d"/*.whl | grep graph_viewer/index.html` -> one line.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_runner.py -k LifecycleTests` -> passes (Pi
  and the fake provider; no Lean). Run one slow command at a time. This is the only slow file this ticket needs (it moves the command Pi tests start).
- Known pre-existing slow failures (also fail on tag v6; do not fix unless this ticket is about them):
  `tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas`
  and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`
  (fixed by tickets 15c/16); `LeanMcpTests` is flaky.

## Stop and report if

- Cyclopts cannot express a flag set the same way the argparse parser did (for example the `--` pass-through of
  `arena campaign`, or a flag the Pi extension, a test or a script passes today). Show the flag and the error.
- A moved module has an import cycle you cannot break without renaming functions the tests use.
- `arena doctor` finds that `benchmark/SHA256SUMS`, a submodule or the token counter really is out of date:
  report the finding, do not "fix" the data.
- A Pi-backed slow test fails after the move and also passes on your baseline (a regression you cannot explain).
- `uv build` leaves out the viewer assets and `uv_build` has no documented way to include them.

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

Your branch is **`v7/04-cli-tools`**, already created and stacked directly above `v7/03-cli`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/04-cli-tools` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/04-cli-tools -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-04`.
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
- [ ] Every change is committed on `v7/04-cli-tools`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-04
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
