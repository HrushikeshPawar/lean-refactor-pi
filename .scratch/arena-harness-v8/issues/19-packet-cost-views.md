# 19: Show readable packets and nested measured hotspots

**What to build:** Agents see useful theorem context and expensive nested work, with full original evidence still retrievable.

**Blocked by:** 04: Isolate actor state and enforce exact ownership; 18: Recover usable target goals and definitions

**Status:** ready-for-agent

**Branch:** `v8/19-packet-cost-views`

**Stacked on:** `v8/18-context-correctness`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 44–54, 59; appendix J; packet/output content contract. The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** Shared packet/cost/declaration views, generic search guidance and their cache-only behavior. Do not redesign each tool schema.

**Shared contracts:** [S6](../contracts.md#s6-scope-and-error-contracts)

## Current implementation context and contract

**Current entry points:** arena/context.py::packet_sections, render_packet; arena/prices.py::step_table; arena/campaign.py::cost_tree, render_price_table; agent-text/packet templates.

**Implementation contract:** Use one structured evidence view for proof totals, top-level edit ranges, nested measured spans and declaration catalog. Keep exact source/proof retrieval independent of display budgets. Remove default hashes and pts_if_gone, put self HB in detail, distinguish missing/zero/pending and published/local measurement. Mark omitted spans and paginate full tree; never turn indentation alone into legal splice IDs. Incorporate only generic search methods.

**Smoke outcome:** Render cached SKI with one expensive nested span and one missing metric; observe the nested parent/range, separate totals, no all-missing column and an exact full-detail reference.

## What to build and acceptance

- [ ] 1. Show exact statement/scope, compatibility requirement, full proof access and one relevant declaration catalog. Remove default raw revision hashes, flattened branch-local dumps and repeated occurrence/signature telemetry.
- [ ] 2. Separate proof totals from structural rows. Show inclusive costs and nested measured hotspots with parent/range/proof identity, clipping/omission coverage and full-detail retrieval.
- [ ] 3. Keep exclusive/self costs in detailed views; omit all-missing columns and conditional legends; remove default pts_if_gone and distinguish published denominators from local measurement.
- [ ] 4. Do not sum overlapping spans or treat indentation regions as legal splice targets. Full profile access expands/pages beyond the existing selected-row limit.
- [ ] 5. Add the generic search method without task-specific solutions, compulsory lookup rituals, fixed budget phases or universal tactic-cost claims.
- [ ] 6. Cache-only comparisons of all three examples prove intact facts and reachable full evidence. Preserve raw proof bytes/line mappings and update text budgets deliberately.

## Verify

Use one focused smoke. This selector is **proposed**, not an already-passing test. Reuse or extend the named existing case when possible; if the module/class is new, add only the boundary smoke needed for this journey. No tests collected is not a pass.

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_context.py::FixturePacketTests::test_v8_packet_nested_hotspot_and_retrieval
```

Expected: the named behavior check passes with no actual provider, Pi or Lean process. Aim for seconds and at most 60 seconds. No per-ticket full suite or slow suite.

**Deferred to final E2E:** All three full packets, worker-role context and search-efficacy comparison. See the shared [final E2E checklist](../final-e2e.md).

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 19, v8/19-packet-cost-views and v8/18-context-correctness resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/19-packet-cost-views --above v8/18-context-correctness`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
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

Your branch is **`v8/19-packet-cost-views`**, directly above **`v8/18-context-correctness`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/19-packet-cost-views -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-19`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/19-packet-cost-views`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-19
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
