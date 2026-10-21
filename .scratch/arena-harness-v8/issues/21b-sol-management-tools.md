# 21b: Let Sol call delegate, jobs and cancel from Pi

**What to build:** In a real `arena run`, Sol can call `delegate`, `jobs` and `cancel` as Pi tools. Each call reaches the live coordinator that owns worker processes. Workers cannot call them.

**Blocked by:** 08, 10, 11 (the Python implementations), 21 (shared tool schema)

**Status:** done

**Branch:** `v8/21b-sol-management-tools`

**Stacked on:** `v8/21-schema-help`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 4, 12–18, 58; appendix A, B and F. The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** The Sol-side transport for the three management tools: Pi registration, protocol action and coordinator socket dispatch. Do not change orchestration semantics in `arena/orchestration.py` beyond what the bridge strictly needs, and do not touch reply text for the proof tools.

**Why this exists:** Review of ticket 21 found that tickets 08–11 implemented `orchestration.delegate/jobs/cancel` and tested them only at the Python boundary with injected transports. `packages/arena-pi/extensions/arena.ts` registers only the five proof tools plus `await_results`. `arena/cli/protocol.py` bridges only `await_results`. `Coordinator._serve` (`arena/coordinator.py` ~106) rejects every other action. So Sol cannot delegate in a real run, and the ticket 25 pilot is impossible.

## Current implementation context and contract

**Current entry points:** `arena/coordinator.py::Coordinator._serve` and the module-level `await_results` client (~175); `arena/cli/protocol.py::run` (`await_results` branch ~100); `packages/arena-pi/extensions/arena.ts` `await_results` registration (~742); `agent-text/tool-schemas.json` (`delegate`, `jobs`, `cancel`); `arena/orchestration.py::delegate` (1066), `cancel` (1180), `jobs` (192).

**Implementation contract:**
- `delegate` and `cancel` must run inside the live `Coordinator` that `arena run` creates (`run.py:785`). They need its `open_child`, `signal` and process inspector, so a standalone protocol subprocess must not call them directly or it would orphan workers. Send them over the existing coordinator socket with the same generation check that `await_results` uses. Generalize `_serve` to a small action table, not a second server.
- `jobs` is read-only and starts no provider request. It may run in-process like the other read paths. Implement the shape that ticket 21 settles for `jobs` (cursor or no cursor, and which actor's jobs are returned); the schema and the implementation must agree.
- Identity comes from the harness, not the model: `ARENA_ACTOR_ID` (default `sol`), `ARENA_SESSION_ID` (default run id, matching `arena.ts:233`) and the tool call id `ARENA_TOOL_CALL_ID` as the operation id, so a retried tool call returns its recorded receipt (appendix A). Never accept `actor_id` from the request body for these three tools; `protocol.py:109` currently falls back to `request.get("actor_id")`, so drop that fallback for them.
- The coordinator rejects `delegate`/`cancel` unless the actor is `sol` (decision 4: workers cannot delegate or cancel), even if a request reaches the socket directly.
- Map the schema's `at` to `orchestration.delegate(anchor=...)`. Reject before dispatch what orchestration would reject anyway (scope without `at`; `scope: step` without exactly one of `steps`/`hole`), with the documented error class.
- Register the three tools in `arena.ts` through `executableTools(toolSchemas, actorRole)`, so workers never see them. Mirror the `await_results` request-file pattern and the reply shape: raw JSON result, `isError` when `ok === false`.

**Smoke outcome:** With an injected `open_child` and a coordinator on a temporary run directory, a protocol-level `delegate` request returns a receipt through the socket. A retry with the same tool call id returns the same receipt and opens no second child. `cancel` from `sol` is accepted, and a forged worker-actor `delegate` is rejected. The worker role registers none of the three tools.

## What to build and acceptance

- [x] 1. Sol's `delegate`, `jobs` and `cancel` are registered Pi tools built from `agent-text/tool-schemas.json`. Worker registration excludes them by construction.
- [x] 2. `delegate` and `cancel` execute in the run's live coordinator over its socket. No child process is spawned outside the coordinator.
- [x] 3. Operation, actor and session identity come from the harness environment. Retrying one tool call is idempotent; reusing its id with different arguments fails as `operation_conflict`.
- [x] 4. A non-Sol actor cannot delegate or cancel, including by writing to the socket directly.
- [x] 5. Documented input errors are rejected before dispatch with the documented class; the help from ticket 21 matches what executes.
- [x] 6. Use one focused smoke for this slice. Actual Pi registration payloads and a real two-worker journey are final E2E coverage.

## Review closure

Sonnet and Claude reviews confirmed the following:
- Identity comes only from the harness environment, and a body `actor_id` is ignored.
- A missing tool-call id fails closed with `invalid_input/identity`.
- A same-id retry returns the receipt without a second child, and different arguments give `operation_conflict`.
- The coordinator rejects a non-Sol `delegate`/`cancel` even at the socket.
- Nothing spawns a child outside the coordinator.

One blocker was fixed in `srm`. `_delegate`/`_cancel` had been inserted inside `Coordinator.close()`, leaving its tail unreachable. Shutdown then kept `coordinator.json`, the socket directory and the run-owner lock (appendix F). `tests/test_recovery_runtime.py::test_startup_reconciles_before_endpoint` caught it; the named smoke did not exercise `close()`. The same commit makes an unexpected exception from delegate/cancel return a retryable `recovery_required` reply instead of dropping the connection, because the receipt may already be committed.

Checks: `tests/test_recovery_runtime.py tests/test_coordinator_wait.py tests/test_orchestration.py` pass (15), ruff clean. Notes: `await_results` in protocol.py still falls back to a body `actor_id` when `ARENA_ACTOR_ID` is unset. `jobs` is not filtered by actor (Sol is the only delegator). The delegate help does not say that `proof` scope rejects steps/hole.

## Verify

The selector is **proposed**, not an existing test.

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_coordinator_wait.py -k v8_management_bridge
```

Expected: the smoke passes with an injected child and no actual provider, Pi or Lean process. Also run the whole test files you touch, not only the selector; earlier tickets broke neighbouring tests that a single selector did not catch.

**Deferred to final E2E:** Sol delegating two real workers through Pi, a queued third, cancel during activity, and resume after a released slot. See the shared [final E2E checklist](../final-e2e.md).

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 21b, v8/21b-sol-management-tools and v8/21-schema-help resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/21b-sol-management-tools --above v8/21-schema-help`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
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

Your branch is **`v8/21b-sol-management-tools`**, directly above **`v8/21-schema-help`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/21b-sol-management-tools -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-21b`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/21b-sol-management-tools`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-21b
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
