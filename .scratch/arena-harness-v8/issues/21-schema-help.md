# 21: Generate accurate actor-specific schema help

**What to build:** Inspection shows the same inputs, bounds and tools that Pi actually registers for Sol and workers.

**Blocked by:** 11: Wait without polling or no-event deadlocks; 15: Promote an anchored replacement inside scratch

**Status:** changes-requested

**Branch:** `v8/21-schema-help`

**Stacked on:** `v8/20-tool-replies`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 44, 58; appendix B and G. The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** Registered schemas and generated inspection/help consistency. Do not bundle another reply rewrite.

**Shared contracts:** [S7](../contracts.md#s7-initial-public-management-shapes-and-delivery-semantics)

## Current implementation context and contract

**Current entry points:** packages/arena-pi/extensions/arena.ts tool registration; arena/cli/text.py::render_template; agent-text/tools; packages/arena-pi/extensions/toolnames.test.ts.

**Implementation contract:** Extract schema metadata from the same registration definitions used by Pi. Expose nested fields, types, defaults and bounds without flattening compile operations into invented fields. Sol gets its management tools plus proof tools; workers get only five proof-search tools. Inspection is cache-only. Remove obsolete finish help and keep descriptions template-owned.

**Smoke outcome:** Compare one nested compile/help shape and a Sol/worker allowlist from the actual definitions using an injected registration context; no Pi process, Lean or provider.

## What to build and acceptance

- [x] 1. Generate help from actual registered schemas and shared descriptions, retaining nesting, field types, limits, defaults and exclusive input alternatives.
- [ ] 2. Cover five proof-search tools and Sol management tools; workers cannot see delegation or strategic-board replacement powers.
- [x] 3. Remove obsolete finish help and drift such as flattened fill/splice parameter descriptions.
- [ ] 4. Verify a documented request is accepted at the public tool boundary and malformed/over-limit inputs return the documented error class.
- [x] 5. Cache-only inspection starts neither Lean nor a provider; fixture output and schema shape agree across actor roles.
- [ ] 6. Update text budgets/goldens deliberately without duplicating rules or prose into a second schema catalog.

## Review findings (Claude, 2026-10-21)

Commit `564fc1b` gets the core design right: Pi TypeBox parameters and inspection help both come from `agent-text/tool-schemas.json`. A field-by-field comparison with the removed TypeBox code found nesting, optionality, bounds and the read-view union preserved. No new `tests/test_text.py` failure is attributable to this commit. Items 2, 4 and 6 are reopened:

1. **Item 2: help documents tools Sol cannot call.** `delegate`, `jobs` and `cancel` appear in Sol's help but are not registered with Pi, which breaks decision 58 ("represented accurately"). The registration gap predates this ticket (08–11 built them only at the Python boundary); wiring is ticket **21b**. In this ticket, keep them in the schema but make the help match what is executable at this commit, or land after 21b. Do not leave a schema field that the implementation ignores: `jobs.cursor` is documented, but `orchestration.jobs(directory, job_ids)` has no cursor and no actor filter. Settle that shape here and record it for 21b.
2. **Item 4: the boundary check uses a second validator.** `arena.tool_schema.accept_tool_input` is called only by the test, not on the live path, and it already disagrees with the real tools: `goal {}` is accepted by it but returns `empty_arguments` live, and `compile {}` returns `invalid_input` from it but `empty_arguments` live. Decision 44 forbids a separately maintained interpretation. Either route the live Python entry (the protocol/tool dispatch that receives Pi requests) through `accept_tool_input` and align the error classes, or delete it and assert accepted/rejected inputs against the real `tools.*_tool` entry points. Also: `delegate` mode with `scope` must require `at`, and `scope: step` needs exactly one of `steps`/`hole` (orchestration.py rejects both cases the schema accepts).
3. **Item 6: budgets are not current.** `test_repository_templates_parse_and_readme_budget_is_current` fails: regenerate with `arena text budget --write` (it also picks up ticket 20's reply rows). `test_word_budget_limits` reads 794 against `budget.static_words` 685. It went over in ticket 14 (+78 words in scratch help) and grew in 15/16/19. Make the deliberate call the item asks for: trim the scratch/tool descriptions, or raise `budget.static_words` in `numbers.yaml` with a one-line reason. The reviewer recommends raising it to 800, since v8 scratch genuinely does more.
4. **Nit:** the worker allowlist is five tools because arena.ts registers the proof tools unconditionally, not because `roles` is consulted. Gate all registrations through `executableTools(toolSchemas, actorRole)`.

Check for the rework: the named smoke plus whole `tests/test_text.py`. That file has older failures that are not this ticket's (v7 over-limit packet; ticket 11 `await_results` text naming finish; ticket 17 long literals in `campaign.py`/`context.py`; ticket 18/19 packet goal rows). The README budget and word-budget tests must pass after this rework. Report the rest unchanged.

## Verify

Use one focused smoke. This selector is **proposed**, not an already-passing test. Reuse or extend the named existing case when possible; if the module/class is new, add only the boundary smoke needed for this journey. No tests collected is not a pass.

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_text.py::TextRendererTests::test_v8_inspection_matches_actor_schema
```

Expected: the named behavior check passes with no actual provider, Pi or Lean process. Aim for seconds and at most 60 seconds. No per-ticket full suite or slow suite.

**Deferred to final E2E:** Actual Pi registered tool payloads and resumed allowlists. See the shared [final E2E checklist](../final-e2e.md).

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 21, v8/21-schema-help and v8/20-tool-replies resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/21-schema-help --above v8/20-tool-replies`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
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

Your branch is **`v8/21-schema-help`**, directly above **`v8/20-tool-replies`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/21-schema-help -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-21`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/21-schema-help`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-21
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
