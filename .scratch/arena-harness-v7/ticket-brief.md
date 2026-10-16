# Brief for drafting v7 tickets (for the drafting agents, not for implementers)

You are drafting implementation tickets for harness v7 of a Lean proof-refactoring harness, in
/mnt/SharedDrive/ActiveProjects/lean-refactor-pi. The tickets will be implemented by a SMALL, LITERAL model
(Luna 6 in Codex), one ticket at a time, in one checkout, on stacked GitButler branches. It will do exactly
what the ticket says and nothing it does not say. So each ticket must be complete and unambiguous: the ask,
numbered checkboxes, constraints, exact verify commands, stop conditions. It must leave nothing broken or
half-done.

## Sources (read them; ground every claim)
- `docs/SPEC-harness-v7.md`: problem, user stories, Implementation Decisions (modules, interfaces), Testing
  Decisions (seams A/B/C), Out of Scope, Further Notes (probe evidence that must not be undone).
- `docs/PLAN-harness-v7.md`: decisions D1-D39 (binding), and the detailed sections each ticket names.
- The code as it is NOW (tickets 00-03 are done): `arena/` (package), `arena/cli/__init__.py` (Cyclopts app,
  pass-through commands), `arena/vendor.py`, `arena/models.py`, `arena/provenance.py`, `tools/` (scripts still
  to be folded into the CLI), `packages/arena-pi/extensions/` (TS Pi extension: arena.ts, spend.ts, rules.ts,
  trim.ts, journal.ts, toolnames.ts), `tests/`, `models.yaml`, `agent-text/` does not exist yet (ticket 05).
- The v6 ticket format for reference: `.scratch/arena-harness-v6/issues/06b-persistent-lean-session.md`.
- The shared sections every ticket ends with: `.scratch/arena-harness-v7/issues/_common.md`.

Read the code a ticket touches before writing it, and name the CURRENT location of things (file, function,
class) so the implementer can find them. Verify every path/function you name exists (grep). Line numbers in
the plan may be stale after a reformat; name functions, not line numbers.

## The stack (fixed; one straight stack, each branch above the previous)
| NN | Branch | Title |
|---|---|---|
| 04 | v7/04-cli-tools | Move the remaining tools into the CLI; arena doctor |
| 05 | v7/05-agent-text | Agent text moved out of code (verbatim), renderer, numbers.yaml |
| 06 | v7/06-run-fixes | Run-control fixes (§12a): outage, retry/idle timeouts, MiMo thinking, newest toolchain |
| 07 | v7/07-lean-gate | Lean speed baseline (+ArkLib, PSS) and gate |
| 08a | v7/08a-lean-service | Shared machine-wide Lean service |
| 08b | v7/08b-repl-pool | REPL pool and v4.32 header trial |
| 09 | v7/09-scheduler | Campaign scheduler |
| 10 | v7/10-graph-core | Graph core: event log, operation edges, focus, per-step goals |
| 11 | v7/11-routes | Routes, K1 archive, map, stall detector (drops LLM route extraction) |
| 12 | v7/12-salvage | Salvage chain and auto-assembly |
| 13 | v7/13-prices | Price engine and instant token quotes |
| 14 | v7/14-search | Declaration index and search |
| 15 | v7/15-tools | Five-tool surface (drops old tools, ideas, skill_read) |
| 16 | v7/16-text | Full text rewrite, compaction memory, packet |
| 17 | v7/17-replay | Replay blob store and `arena replay` |
| 18 | v7/18-viewer | Viewer "Reasoning & calls" tab |
| 19 | v7/19-submit | `arena submit` and cross-run recombination |
| 20 | v7/20-campaign | Owner's paid campaign (not for the implementer) |
Lower branch of 04 is `v7/03-cli`; of 08a is `v7/07-lean-gate`; of 08b is `v7/08a-lean-service`; of 09 is
`v7/08b-repl-pool`; otherwise the previous row.

Real dependency edges (put in "Blocked by"): 04←03; 05←03; 06←02,03; 07←03; 08a←07; 08b←08a; 09←08a;
10←03; 11←10; 12←10,08a; 13←10,08a; 14←04; 15←02,05,11,12,13,14; 16←15; 17←05,10; 18←17; 19←10,13; 20←16,06.

## Ticket file format (write exactly this structure)

File: `.scratch/arena-harness-v7/issues/<NN>-<slug>.md` (slug = branch name after `v7/<NN>-`).

```
# <NN>: <Title>

**What to build:** 2-5 sentences, the end-to-end behaviour from the operator's or model's point of view.

**Blocked by:** <list of "NN: title"> (all are committed below your branch).

**Status:** ready-for-agent

**Branch:** `v7/<NN>-<slug>` (stacked on `<lower branch>`)

**Read first:** spec sections ...; plan sections ... (by heading); decisions D...

## Context: where things are now
Bullets naming current files/functions/classes/commands this ticket changes, verified by grep, with one line each
on what they do today.

## What to build
Numbered checkboxes `- [ ] 1. ...`. Each one concrete and checkable: what module/function/command/file to
create or change, its inputs/outputs or interface (signatures or JSON shapes where the spec gives them),
behaviour on edge cases and errors. Split big items. Include the tests to add as their own checkboxes, each
naming the behaviour it proves and which seam (spec Testing Decisions) it belongs to. Include deletions of
replaced code as their own checkboxes. 8-25 checkboxes is typical.

## Do NOT
Bullets: specific traps for this ticket (things out of scope, decisions not to undo, files not to touch,
behaviour that must stay the same).

## Acceptance
Behaviour-level checks a reviewer can run or observe (not "code exists").

## Verify
Exact shell commands, each with the expected result. TEST BUDGET (owner rule): list only the TARGETED test files
for this ticket; the fast suite (~35 s) once at the end; a slow file (`ARENA_SLOW_TESTS=1 <file>`) only when the
ticket truly changes Lean/Pi behaviour, and name the file. NEVER `ARENA_SLOW_TESTS=1` over all of tests/ (it
takes most of an hour). E.g.
- `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count + new tests)
- `cd packages/arena-pi && npm test` -> all pass
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_X.py` -> ...
- `uv run arena ...` -> ...
Known pre-existing slow failures (also fail on tag v6; do not fix unless this ticket is about them):
`tests/test_runner.py::ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas`
and `tests/test_runner.py::AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`
(fixed by tickets 15/16); `LeanMcpTests` is flaky.

## Stop and report if
Bullets: conditions under which the implementer must stop and report instead of improvising.

<then paste the full content of _common.md below the comment block, replacing <NN>, <BRANCH>, <LOWER>>
```

Rules for you, the drafter:
- Do not invent decisions. If the plan/spec leave something open that the implementer would have to decide,
  either pick the option the plan recommends and say "(plan §x recommends)", or add it under "Stop and report
  if" / list it in your report to the orchestrator as an open question.
- Respect Out of Scope and D-decisions. Respect "kept until replacement lands" (D39): route extraction goes in
  11, ideas/skill_read/old tools go in 15.
- Model-facing strings: from ticket 05 on, every model-facing string lives in `agent-text/` (D3); tickets after
  05 must say so where they add text. The full rewrite happens only in 16 (text written once); tickets 06-15
  that need new model-facing text add it as templates in agent-text with minimal neutral wording.
- Size: each ticket must fit one fresh context of a small model. If one is too big, say so in your report and
  propose a split (do not split on your own).
- You may NOT edit anything except the ticket files you were assigned. No VCS commands (no git writes, no
  `but`). Foreground commands only; no background jobs, no Monitor, no sleep loops.

Report back to the orchestrator: the files written; for each ticket, the open questions and any size concern;
anything in the plan/spec you found contradictory or stale.
