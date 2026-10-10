# 20: Owner's paid campaign (v6 against v7, and the new-model check)

**What to build:** Nothing is built. The owner launches the paid v7 measurement campaign (plan §10 phase 5, D37), and the reviewing session (the orchestrator) writes the report from its results.

**Blocked by:** 16: Full text rewrite, compaction memory, packet; 06: Run-control fixes (the whole v7 stack, 04 to 19b, reviewed and applied in the workspace, and green, before launch).

**Status:** owner-only

**Branch:** none (no code is written; the stack is `v7/04` to `v7/19b`, with this row last).

**NOT for the implementer.** This ticket is the owner-launched paid campaign. An implementing agent must never run it, never spend money, and never mark it done. It has no GitButler implementer sections and no hand-back format.

**Read first (owner and orchestrator):** plan §10 phase 5 and D37, D8, D10; spec "Testing Decisions" (the v7 campaign paragraph).

## Setup (the owner checks before launching)
- The v7 stack (04 to 19b) is reviewed and applied in this checkout's GitButler workspace. **Nothing is merged to main for the campaign** (owner rule); each run records `code.branch` and `code.branch_commit` (the top stack branch) and `code.tree`. The tag `v6` (commit 4205d4e) exists. All Lean speed-gate checks (ticket 07) pass on this machine and nothing else is running on it (idle machine; one campaign only).
- `.env` holds the keys for opencode-go (DeepSeek v4.1 flash) and primalabs (MiMo 2.6 Pro). Run `uv run arena doctor` and fix every failure first (ticket 04).
- `models.yaml` lists both models with prices; the price check passes.

## Design
| Cell | Harness | Model | Rows | Limit |
|---|---|---|---|---|
| A (baseline) | v6 (export of tag `v6`, separate worktree) | DeepSeek v4.1 flash | putnam_1964_b2 (best, 98.54); Cslib.SKI.parallelReduction_diamond (worst, 70.37) | $0.50 per run (`--cap 0.5` at v6) |
| B | v7 | DeepSeek v4.1 flash | the same two rows | $0.50 per run |
| C (new-model check) | v7 | MiMo 2.6 Pro | the same two rows | $0.50 per run |
Six runs, at most $3.00 in total. One replicate each (variance sets and further A/Bs follow only if the owner extends the campaign: plan §10).

## Commands the owner runs
Run the v6 cell from a separate export of the tag `v6`, so v7's code is never involved. The tag has no `pyproject.toml`: it runs as scripts, and its `tools/` scripts put their own checkout root first on `sys.path`. Its flags are the v6 ones (`--cap`, not `--limit-usd`; there is no `arena` command at that tag).
1. Export the tag without touching git state (the recipe the orchestrator used on 2026-10-10 for the v6 slow-test
   comparison):
   ```
   V6=$HOME/lean-refactor-pi-v6; mkdir -p $V6
   git archive v6 | tar -x -C $V6
   mkdir -p $V6/vendor/lean-refactor $V6/vendor/arena-space
   git -C vendor/lean-refactor archive 9c98a3a | tar -x -C $V6/vendor/lean-refactor   # v6's pinned commits
   git -C vendor/arena-space archive d9e46ee | tar -x -C $V6/vendor/arena-space
   ln -s $PWD/workspaces $V6/workspaces      # same provisioned Lean projects
   ln -s $PWD/runs $V6/runs                  # v6 run dirs land in this repo's runs/pi-budget
   cp .env $V6/.env
   ```
   v6 is stdlib-only Python and runs with `uv run --no-project` from inside `$V6`. Its Pi extension runs
   `uv run --no-project python -m tools.arena_campaign`, so `$V6` is the import root and v7 code is never used.
   v6 used `~/.pi/agent/models.json` only for its own (opencode-go) models; DeepSeek needs nothing extra.
2. Check the import root: `cd $V6 && uv run --no-project python -c "import arena; print(arena.__file__)"` must print
   a path under `$V6`. If it prints this repository's path, stop and ask the orchestrator.
3. v6 dry run, from `$V6`: `uv run --no-project python tools/run_campaign.py --prefix v7camp-v6-ds --rows
   putnam_1964_b2,Cslib.SKI.parallelReduction_diamond --models deepseek-v4.1-flash --cap 0.5 --replicates 1
   --dry-run` (check every flag with `--help` at the tag first; v6's `--cap` is a soft cap).
4. The same command without `--dry-run` (cell A). Check `--cap` with `--help` at the tag first: at v6 it is a soft cap (the last request may overshoot).
5. In the v7 checkout (this repository): `uv run arena doctor`, then `uv run arena campaign --dry-run --models deepseek-v4.1-flash --rows putnam_1964_b2,Cslib.SKI.parallelReduction_diamond --limit-usd 0.5 --prefix v7camp-v7-ds --replicates 1` (no model call; it must list two `arena run` lines). If `uv run arena campaign --help` of the finished v7 stack also lists `--check`, run that too: every gate must print OK.
6. Cell B: `uv run arena campaign --models deepseek-v4.1-flash --rows putnam_1964_b2,Cslib.SKI.parallelReduction_diamond --limit-usd 0.5 --prefix v7camp-v7-ds --replicates 1`
7. Cell C: the dry run `uv run arena campaign --dry-run --models mimo-v2.6-pro --rows putnam_1964_b2,Cslib.SKI.parallelReduction_diamond --limit-usd 0.5 --prefix v7camp-v7-mimo --replicates 1`, then the same command without `--dry-run`.
8. Confirm each run directory under `runs/pi-budget/<prefix>-*` (v6 runs land here too, through the `runs` link) has `summary.json`; if a run was killed by an outage, report it to the orchestrator before re-running (a re-run is a new paid run).
The v7 flags are those of `uv run arena campaign --help` in the finished v7 stack (`--models`, `--rows`, `--prefix`, `--limit-usd`, `--replicates`, `--dry-run`, ...); the orchestrator fixes this section to the final flags before launch.

## What the reviewer (orchestrator) reports
For each of the six runs and then per cell, from the local journals and ledgers (`arena replay`, `runs/pi-budget/<run>/summary.json`):
- **Proxy** (final submitted candidate, cold verified) and the original's proxy; tokens, heartbeats, toolchain share per axis.
- **Spend:** settled total, one figure (ledger settle rows), against the $0.50 limit; the overshoot of the last call.
- **Bookkeeping share:** the share of calls (and of settled spend) in turns that did not compile, search or read for the proof (state, candidate, idea and similar bookkeeping calls in v6; the equivalent in v7).
- **Tool errors:** count and rate of tool calls that returned an error, by kind.
- **Calls before the first compile:** tool calls issued before the first compile of a draft.
- **Share of compiles using an operation:** among v7 compiles, the share using `splice`, `fill` or `merge` instead of a free-text draft (cells B and C only; v6 has no operations).
- **Nodes and best-node depth, stall events, harness-made nodes** (v7 cells).
- **MiMo (cell C):** thinking on tool-result turns working as configured, no request rejected for history shape, spend per call against DeepSeek.
- **Verdicts:** B against A on both rows (ceiling row: no regression; weak row: gain), with the caveat of one replicate per cell; C reported as a check, not a ranking.
- Anything that looks like a harness defect (not a model failure) is listed with its run id and turn, for tickets, never fixed inside the campaign.
- The report goes to `docs/RESULTS-v7-campaign.md` (orchestrator's commit), with run ids, the v6 tag commit, and the v7 `code.branch_commit` and `code.tree` of each run.

## Stop conditions (owner)
- Any gate in a `--check` fails: do not launch; send the output to the orchestrator.
- Total settled spend exceeds $3.00, or any run's settled spend exceeds $2: stop and kill the campaign by PID only (never by name or pattern).
- A run ends with no journal or no `summary.json`: do not re-run until the orchestrator has looked.
