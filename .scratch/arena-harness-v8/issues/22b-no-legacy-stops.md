# 22b: Remove Sol's legacy finish, plateau and forced-restart control

**What to build:** Sol keeps searching until the shared $2.50 actual-cost stop, or until a provider, infrastructure or operator failure. The harness never ends a below-budget run because of a voluntary finish, plateau, no-work or continuation count. It never forces a restart, an island or a focus move. Stall statistics stay informational.

**Blocked by:** 06 (shared stop), 11 (event waiting / no_pending_work continuation)

**Status:** ready-for-agent

**Branch:** `v8/22b-no-legacy-stops`

**Stacked on:** `v8/22-served-evidence`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 1, 8, 11, 20; appendix C (Run row: "There is no successful below-budget Sol finish") and F (no_pending_work gives a normal continuation). Plan §6.1 rows "Sol lifetime" and "Search control" (Q15). The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** Sol's turn-end control decision and the harness-side stall/restart actions. Do not change provider dispatch or the shared stop (06), compaction summaries (23), or reply text beyond removing references to the removed behaviors.

**Why this exists:** Review on 2026-10-21 found that no ticket removes the v7 control loop. `packages/arena-pi/extensions/control.ts::stopDecision` still returns these stops in the final tenth of the run limit: `finished` (text-only turn), `continuation_limit` (`MAX_CONTINUATIONS` 12), `no_work_fallback` (2 no-work turns) and `plateau` (4+4). Earlier in the run it forces `restart`/`island` (no-work, `STALL_RESTART_FRACTION` 0.12 of the limit without a new best, or `stall_due`) and `moveFocus`. `arena/campaign.py::_check_stall` appends a forced `focus` row with `reason: "stall"`. The owner confirmed removal of the forced stall focus move on 2026-10-21.

## Current implementation context and contract

**Current entry points:**
- `packages/arena-pi/extensions/control.ts::stopDecision` and its constants;
- the turn-end handler in `packages/arena-pi/extensions/arena.ts` (~800–900: `finishAllowed`, `finishTurn`, `islandTurn`, `stallDue`, the `restart` branch, `moveFocus` → `no_work_focus`);
- `arena/campaign.py::_check_stall`, `stall_due`, `STALL_RESTART_TRIES`, `stall_restart_packet`/`restart_packet`/`island_packet`/`no_work_focus`;
- `arena/cli/protocol.py` actions `stall_due` and the restart/island/no-work-focus actions;
- `packages/arena-pi/extensions/control.test.ts`.

**Implementation contract:**
- Stops that remain: the shared actual-cost stop (`limit_reached`, from the 06 ledger), `usage_limit`, `provider_unreachable`, `error_loop`, and operator interruption. Each keeps its distinct reason. Remove `finished`, `continuation_limit`, `no_work_fallback` and `plateau`, plus the `finishAllowed`/`remainingFraction` final-tenth logic that gates them. A text-only or no-work Sol turn below the threshold gets an ordinary continuation (or event-driven waiting per 11), never a stop.
- Remove forced `restart`, `island` and `moveFocus` decisions, `stall_due`, `STALL_RESTART_FRACTION` and `STALL_RESTART_TRIES`. Delete the code paths and protocol actions that only they used (`stall_restart_packet`, `island_packet`, `no_work_focus`, and `restart_packet` if nothing else calls it). Do not keep them behind a flag.
- `_check_stall` still records the informational `stall` audit row (root, count, mode, target) and its route statistics. It must not append a `focus` row. Agents can see stall information in replies; it does not change focus or conversation.
- Normal Pi context compaction stays automatic and untouched (23 owns its summaries).
- Remove model-facing text that only described removed behaviors: final-tenth finish wording, island and restart continuation messages, and finish naming in `tools/await_results.description`. This fixes `tests/test_text.py::HiddenStopTests::test_finish_is_named_only_by_the_texts_shown_once_it_is_offered`.

**Smoke outcome:** `stopDecision` returns no stop for a text-only turn, plateau, no-work turns and many continuations at any remaining fraction below the threshold. It returns `limit_reached`/`usage_limit`/`provider_unreachable`/`error_loop` with their reasons. A stall audit adds no focus row.

## What to build and acceptance

- [ ] 1. No below-budget voluntary, plateau, no-work or continuation-count stop remains in Sol's control path.
- [ ] 2. No harness-forced restart, island or focus move remains. Stall statistics are recorded and shown, never acted on.
- [ ] 3. Failure, operator and actual-cost stops keep distinct reasons.
- [ ] 4. Dead protocol actions, constants and templates for the removed behaviors are deleted, not flagged off.
- [ ] 5. Update `control.test.ts` and the five `tests/test_graph.py::StallCampaignTests` cases. Those tests also need `committed_operations=campaign.committed_operation_ids(...)` in their `Graph.from_history` calls (stale since v8-16; see the 22 review closure). Their assertions about a forced focus row change to "no focus row".
- [ ] 6. One focused smoke plus the whole touched test files. A real Pi run reaching the $2.50 stop is final E2E coverage.

## Verify

The selector is **proposed**.

```bash
cd packages/arena-pi && node --test extensions/control.test.ts
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_graph.py::StallCampaignTests tests/test_text.py::HiddenStopTests
```

Expected: both pass with no actual provider, Pi or Lean process.

**Deferred to final E2E:** a scripted Sol session that ends text-only turns and plateaus below the threshold and continues until the actual-cost stop.

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 22b, v8/22b-no-legacy-stops and v8/22-served-evidence resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/22b-no-legacy-stops --above v8/22-served-evidence`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
4. Run every Python command through `uv run`, including tests, helper scripts and one-off snippets. Never invoke the virtualenv interpreter directly or use a bare Python interpreter. Use `uv run --no-sync python` with the existing environment for the single focused check in Verify. A cheap targeted baseline is useful when the old behavior is testable. A proposed new selector must be implemented or mapped to an existing equivalent; no tests collected is not a pass. Do not run dependency synchronization or install packages by habit.
5. If a named interface differs because a predecessor changed it, follow that reviewed interface and record the mapping. If the behavior contract conflicts with current callers, stop and report the concrete conflict instead of broadening the design.

## Rules for every change

- Own only the responsibility named in this ticket. Preserve runtime improvements and other agents' edits. No drive-by refactors or unrelated formatting. Report out-of-scope defects in the hand-back.
- Model-facing prose belongs in `agent-text/` and uses the shared renderer. Generic proof-search methods are allowed by v8; saved task-specific answers are not. Do not revive the obsolete v7 ban on all methodological advice.
- Keep operation-generated lineage and raw artifacts exact. Notes, similarity and default focus never replace exact construction records. No model judge or hidden proof transformation.
- Sol and workers share actual reported cost only. No reservations, model pools, per-job dollar limits or final-turn reserve. Unknown usage is not silently zero.
- Implement the working journey in the ticket and reuse existing public boundaries. New APIs, modules and `v8_*` test selectors are explicitly proposed; they are not already implemented merely because the ticket names them.
- Never print, log or commit secrets. No paid model calls, competition submission, or long live resource experiment. Fake providers are local fixtures. Actual Pi/Lean integration belongs to the final E2E pass unless the user explicitly changes this ticket's scope.
- No live `/proc` or other runs in the smoke test; inject process, memory, Lean and network outcomes. Production process ownership checks may use OS identity, but tests inject those readings. No sleep-based race tests or broad process-name kills.

## Minimum fast-test policy

- One small reused or extended behavior smoke is normally enough to check out this ticket. Aim for seconds, normally 5–15 seconds and no more than 60 seconds for the selected check. Do not add a regression test for every checkbox or cosmetic wording change.
- Run the focused Verify command. Do not run the whole fast suite, entire slow files, actual Pi, Lean, worker warm-ups or resource matrices after each ticket or commit.
- Use touched-file syntax/lint checks when relevant. Do not run repository-wide quality tools to chase unrelated diagnostics. Preserve meaningful assertions; report a pre-existing failure rather than weakening its setup.
- If the smoke fails or exposes a concrete adjacent risk, add only the targeted check needed to resolve it. A passing fixture proves the narrow behavior, not actual-Pi or real-Lean acceptance.
- The shared `final-e2e.md` checklist owns one broad fast-suite run and selected real-Pi/Lean integration at the end of the linear stack. Keep deferred coverage visible in every hand-back. No 30-minute gate per ticket.

## Version control (GitButler)

Your branch is **`v8/22b-no-legacy-stops`**, directly above **`v8/22-served-evidence`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/22b-no-legacy-stops -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-22b`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/22b-no-legacy-stops`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-22b
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
