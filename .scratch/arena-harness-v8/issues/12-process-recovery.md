# 12: Reconcile owned child processes after coordinator failure

**What to build:** Restart reconciles owned workers and durable activations before replacing them, so one hypothesis cannot run twice after a crash.

**Blocked by:** 10: Admit two workers and cancel stale work cleanly

**Status:** done

**Branch:** `v8/12-process-recovery`

**Stacked on:** `v8/11-event-waiting`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 14, 18, 25; appendix A, C and F. The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** Coordinator/process ownership and activation reconciliation. Do not promise exactly-once provider billing.

**Shared contracts:** [S2](../contracts.md#s2-shared-spend-and-dispatch-ordering), [S4](../contracts.md#s4-worker-process-policy)

## Current implementation context and contract

**Current entry points:** arena/cli/run.py::run, kill_group; proposed orchestration ownership record; proposed PiRpc spawn/exit handlers.

**Implementation contract:** Adopt S4 restart policy: no attachment to abandoned pipes. Record coordinator generation, PID/group, process-start identity, session path and activation before acknowledgement. Fence grants, verify old owned group, stop it if alive, confirm exit and then create a new child only after request journals are reconciled. A mismatched/reused PID is not signalled. Process inspection/signals are injected at the boundary.

**Smoke outcome:** Reload a persisted activation with a reused PID and a separate positively identified owned child; do not signal the reused PID or launch a replacement until the owned child is gone.

## What to build and acceptance

- [x] 1. Persist launch intent and activation before spawning; identify owned processes by creation identity and coordinator generation, not PID alone.
- [x] 2. Fence new activation/dispatch during reconciliation. Attach/reconcile or stop the old owned child before launching its replacement.
- [x] 3. Crash immediately before/after launch and after child exit but before completion recording; recover slot/session ownership from durable evidence.
- [x] 4. Do not touch other runs or reinterpret a reused PID as a child. Machine/process identity is injected in deterministic tests.
- [x] 5. Late old-generation events can add evidence but cannot reopen cancelled activations or release another activation's slot.
- [x] 6. Use the one assigned fast smoke for this slice. Retain the stated behavior requirements; actual-Pi/real-Lean journeys and the broader race matrix are final E2E coverage, not this ticket's gate.

## Verify

Use one focused smoke. This selector is **proposed**, not an already-passing test. Reuse or extend the named existing case when possible; if the module/class is new, add only the boundary smoke needed for this journey. No tests collected is not a pass.

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_orchestration.py::V8RecoverySmokeTests::test_v8_owned_child_reconciliation
```

Expected: the named behavior check passes with no actual provider, Pi or Lean process. Aim for seconds and at most 60 seconds. No per-ticket full suite or slow suite.

**Deferred to final E2E:** Actual coordinator death and OS process-group cleanup. See the shared [final E2E checklist](../final-e2e.md).


## Review corrections and closure

The original named smoke passed in 0.11s, but source review and an injected post-spawn crash reproduced two children with recovery incorrectly reporting `running`. Review also found missing production startup/transport wiring, historical settled dispatches remaining uncertain, absent generation propagation, skipped terminal slots, lost queued launchers, old-reader mutation races, and unchecked late-evidence attribution. These were implementation defects, rather than deferred real-Pi coverage.

Recovery is now serialized against launch and other reconciliation calls. An intent without a spawned identity or explicit never-spawned evidence remains fenced. Every occupied activation, including terminal ones, is reconciled; queued jobs regain their launch adapter. Confirmed group absence and known request coverage are required before replacement. Unknown usage keeps the fence; known settlement closes the uncertainty without adding estimates or changing spend. The current generation is committed before replacement prompts, and old readers cannot change state or release ownership across transport/generation boundaries. Committed stops suppress replacement.

The runner-owned coordinator invokes reconciliation before exposing management or launching Sol. Production adapters implement RPC pipes and injected process inspection/signalling. Creation identity includes boot identity and start ticks, plus process group, run, generation and session validation. A reused PID is not signalled. A missing leader does not prove group absence, and a still-live identified leader that left its old group remains unknown. Both Sol and worker launches receive the admitted generation. A startup with unresolved ownership or requests refuses with `recovery_required`.

Late findings require a committed passing evaluation and an exact attempt with matching actor, session, activation and generation. Construction records now retain these available worker identities without changing proof/derivation content or its digest. Invalid or foreign evidence cannot be published against an old activation. The previous verification smoke class was also restored after `vpx` accidentally nested its test under the recovery fixture.

Verified with one focused combined check:

```bash
UV_CACHE_DIR=/tmp/arena-uv-cache uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_orchestration.py::V8RecoverySmokeTests tests/test_orchestration.py::V8VerificationSmokeTests tests/test_orchestration.py::V8WorkerSmokeTests tests/test_recovery_runtime.py tests/test_coordinator_wait.py tests/test_verification_wait.py
```

Result: **12 tests and 4 subtests passed in 1.05s**. Scoped access was required only for local Unix socket binding blocked by the sandbox. A subsequent narrow pipe-cleanup correction preserves buffered stdout until reader EOF while closing stdin after confirmed process absence; the four runtime tests passed in 0.11s, including retained late bytes. Scoped Ruff passed. Independent review confirmed the queued-launcher, stale-reader, attribution and pipe-drain fixes and found no remaining blocker.

All process inspection, signalling and spawn outcomes were injected. No live `/proc`, real Pi, Lean, or provider process was used in the tests. Actual coordinator death, OS group cleanup, real Pi session resumption and the broader crash/race matrix remain final E2E coverage. Ticket 13 was not changed. Reviewer marks ticket 12 **done**.

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 12, v8/12-process-recovery and v8/11-event-waiting resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/12-process-recovery --above v8/11-event-waiting`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
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

Your branch is **`v8/12-process-recovery`**, directly above **`v8/11-event-waiting`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/12-process-recovery -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-12`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/12-process-recovery`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-12
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
