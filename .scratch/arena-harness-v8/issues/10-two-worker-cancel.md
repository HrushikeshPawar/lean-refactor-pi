# 10: Admit two workers and cancel stale work cleanly

**What to build:** Two independent workers run while a third waits; cancellation releases capacity only after the old child exits.

**Blocked by:** 09: Publish early results and resume the same hypothesis

**Status:** done

**Branch:** `v8/10-two-worker-cancel`

**Stacked on:** `v8/09-worker-followups`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 13–19; appendix B, C and G. The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** Two-session admission, queueing and process cancellation only. Do not change Lean concurrency.

**Shared contracts:** [S4](../contracts.md#s4-worker-process-policy), [S7](../contracts.md#s7-initial-public-management-shapes-and-delivery-semantics)

## Current implementation context and contract

**Current entry points:** arena/cli/run.py::kill_group, run; proposed orchestration activation admission and PiRpc lifecycle.

**Implementation contract:** One coordinator owns the active set, queued jobs and process ownership. Admit FIFO jobs while fewer than two model activations own a slot. cancel clears queued Pi messages then aborts and requests orderly child shutdown. Cancelling keeps its slot until process exit/positive absence. Repeated cancellation reuses the receipt; a late event cannot reopen the old activation. Lean slots are unaffected by model admission.

**Smoke outcome:** Start two fake owned children, queue a third, acknowledge cancel on one without exiting and observe no third launch; report its exit and observe exactly one new activation.

## What to build and acceptance

- [x] 1. Admit at most two active worker model sessions, with queueing separate from activation. Each worker retains independent tools/context and actor-local focus.
- [x] 2. Allow an exhausted/completed assignment to release a slot while Sol continues. Activate queued work only when capacity is truly available.
- [x] 3. Cancel idempotently, clearing queued prompts before abort. Retain cancelling state and slot ownership until child exit or confirmed absence.
- [x] 4. A cancellation acknowledgement preceding actual exit cannot admit a third live child. Late old results retain evidence without reactivating the assignment.
- [x] 5. Expose concurrent job, queue and cancellation states through normal management results.
- [x] 6. Use the one assigned fast smoke for this slice. Retain the stated behavior requirements; actual-Pi/real-Lean journeys and the broader race matrix are final E2E coverage, not this ticket's gate.

## Verify

Use one focused smoke. This selector is **proposed**, not an already-passing test. Reuse or extend the named existing case when possible; if the module/class is new, add only the boundary smoke needed for this journey. No tests collected is not a pass.

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_orchestration.py::V8WorkerSmokeTests::test_v8_cancel_releases_after_exit
```

Expected: the named behavior check passes with no actual provider, Pi or Lean process. Aim for seconds and at most 60 seconds. No per-ticket full suite or slow suite.

**Deferred to final E2E:** Actual Pi cancellation, output drain and descendant cleanup. See the shared [final E2E checklist](../final-e2e.md).

## Review corrections

The original worker smokes passed, but the injected cancellation protocol was wrong: Pi 1.3.0 clears pending messages with `clear_queue`, not an extra `queued` field on `abort`. Cancellation now writes `clear_queue` then `abort`, with separate command identities. The extended smoke reproduced both that mismatch and premature slot release when stdout closed while the injected process was still alive.

Durable `occupies_slot` is now independent of terminal assignment state. Completion, exhaustion, cancellation, read/write failure and stdout EOF do not prove process absence. `observe_exit(directory, activation_id)` checks the transport's `confirmed_absent()`, records release and admits FIFO exactly once. Terminal workers request orderly shutdown through the same release path. Configuration failure before spawning can release capacity; an unknown outcome after invoking the child factory retains it for recovery. Process identity/restart recovery remains ticket 12.

All admission and slot/state transitions use the run-control lock. New delegations cannot bypass an older queued assignment. Per-activation transport locks serialize prompt and cancellation writes; reader startup preserves an already committed cancellation. Factories are retained per accepted activation, so a retry or invalid call cannot replace a queued job's launcher.

Cancellation commits its state and receipt together, targets the exact activation, and preserves canonical evidence references on replay. Cancelling a later follow-up uses its own cancellation identity. Failed shutdown I/O records evidence and remains retryable with the slot held.

Verified: `uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_orchestration.py::V8WorkerSmokeTests` passed with 3 tests and 4 subtests in 0.20s. Ruff passed for `arena/orchestration.py`, `arena/pi_rpc.py` and `tests/test_orchestration.py`. The same smoke now distinguishes pipe EOF from process exit, checks cancellation replay across activations, and checks completed workers retaining capacity until confirmed absent. The earlier immediate-response fixture waits for durable terminal state before returning its write, then joins the reader outside that write, so serialized shutdown cannot deadlock the fixture.

These are offline injected-process checks. Real Pi cancellation, transport draining, positive descendant absence and the broader concurrency matrix remain final E2E coverage. Lean admission is unchanged. Ticket 11 is not started by this review.

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 10, v8/10-two-worker-cancel and v8/09-worker-followups resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/10-two-worker-cancel --above v8/09-worker-followups`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
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

Your branch is **`v8/10-two-worker-cancel`**, directly above **`v8/09-worker-followups`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/10-two-worker-cancel -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-10`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/10-two-worker-cancel`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-10
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
