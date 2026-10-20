# 13: Recover charges, candidate receipts and delivery after crashes

**What to build:** Restart recovers recorded usage and proof/results without double-charging, resending an uncertain call or dropping a candidate.

**Blocked by:** 12: Reconcile owned child processes after coordinator failure

**Status:** done

**Branch:** `v8/13-settlement-recovery`

**Stacked on:** `v8/12-process-recovery`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 8–10, 21–26; appendix A, D and F. The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** Durable request/candidate/evaluation/delivery recovery after the preceding process reconciliation.

**Shared contracts:** [S1](../contracts.md#s1-retain-the-existing-ledger-and-file-lock-model), [S2](../contracts.md#s2-shared-spend-and-dispatch-ordering), [S4](../contracts.md#s4-worker-process-policy)

## Current implementation context and contract

**Current entry points:** arena/cli/run.py::finish; arena/replay.py::load_run; arena/campaign.py::events, write_state; proposed run_control reconciliation.

**Implementation contract:** Rebuild only from committed control receipts, child cost journals and retained session/request evidence. Known settled IDs are idempotent. Definitely-unsent requests can be prepared anew with explicit lineage; possibly-sent requests are not resent blindly. Reconcile actual late usage or preserve unknown/failure. Complete an existing candidate evaluation intent by its original identity, and redeliver the same event after a cursor crash. Never reset stop reason, settled total or deadline origin.

**Smoke outcome:** Reload a history interrupted after actual settlement and candidate persistence but before acknowledgements; observe no double charge, one evaluation identity and retrievable repeated delivery identity.

## What to build and acceptance

- [x] 1. Crash around provider dispatch, response receipt and settlement append. Recover actual journal/session evidence using request identity and grouped-usage coverage.
- [x] 2. A repeated settlement is counted once. An uncertain remote call is not blindly resent, priced as zero or replaced with a worst-case estimate.
- [x] 3. Retain unknown accounting and explicit infrastructure failure when actual usage cannot be reconciled; no exactly-once remote-billing claim.
- [x] 4. Crash after candidate persistence before evaluation enqueue and after result persistence before cursor advance; stable receipts converge without duplicate attempts/checks or lost delivery.
- [x] 5. Recover original candidate/evaluation/artifact identities and maintain the recorded stop state. A restart cannot reset spend or the track deadline origin.
- [x] 6. Use the one assigned fast smoke for this slice. Retain the stated behavior requirements; actual-Pi/real-Lean journeys and the broader race matrix are final E2E coverage, not this ticket's gate.

## Verify

Use one focused smoke. This selector is **proposed**, not an already-passing test. Reuse or extend the named existing case when possible; if the module/class is new, add only the boundary smoke needed for this journey. No tests collected is not a pass.

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_orchestration.py::V8RecoverySmokeTests::test_v8_receipt_replay_after_crash
```

Expected: the named behavior check passes with no actual provider, Pi or Lean process. Aim for seconds and at most 60 seconds. No per-ticket full suite or slow suite.

**Deferred to final E2E:** Actual Pi usage recovery and the full interruption matrix. See the shared [final E2E checklist](../final-e2e.md).


## Review corrections and closure

The original two recovery tests passed in 0.15s, but review found implementation gaps. The evidence reader used fixture-only filenames; later known usage could not reconcile existing unknown coverage; overlapping groups could be skipped silently; candidate recovery fabricated evaluation IDs and owners; recovery acknowledged evidence before delivery; and a rejected retry could incorrectly authorize replacement of a possibly-sent request. A direct transport-history reproduction confirmed that last bug. The original fixture's fictitious candidate IDs were replaced with saved artifacts and canonical evaluation/check IDs, and the reference seed now describes an actual reference rather than an unevaluated model candidate.

Usage recovery now reads the actual cost ledger, trace journal and saved Pi sessions, with exact response/entry/request joins. Before shared settlement, the extension fsyncs a supporting `usage_evidence` record containing actual raw usage and exact grouped coverage. This record does not charge or update the total. Known zero remains known; missing usage and Pi's zero-filled error/abort placeholders remain unknown. Later known evidence explicitly reconciles unknown settlements. Ownership, malformed/torn artifacts, inconsistent actual amounts and incompatible coverage generate recovery issues that keep replacement fenced rather than guessing or double-charging. Live child sessions are not prematurely closed as unknown.

Proof recovery uses committed candidates, saved artifact hashes and pinned evaluator/toolchain context. It resumes the original fast/full evaluation and check identities through the existing background queue, including persistence before the attempt or evaluation intent was filed. Unprovable context remains an explicit recovery issue. Exact worker findings can be reconstructed from committed attempts and passing evaluations, while recovery itself never writes an acknowledgement or advances an actor cursor. A final queue test reproduced the real `queued → running → crash` replay bug. Recovery now records `recovery_of` referencing the interrupted transition, retains the original check/evaluation IDs and propagates that reference through the resumed running/terminal transitions.

Request lineage checks all transport attempts, preserves original ownership, replays existing exact preparation receipts and accepts only proven-unsent replacement. Once replaced, the old request cannot dispatch later. Late actual charges still count, but they cannot overwrite the original stop reason or deadline origin. No reservations, estimated charges or automatic remote resend were added.

Verified with the focused offline checks:

```bash
UV_CACHE_DIR=/tmp/arena-uv-cache uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_orchestration.py::V8RecoverySmokeTests tests/test_orchestration.py::V8WorkerSmokeTests tests/test_orchestration.py::V8ControlSmokeTests tests/test_recovery_usage.py tests/test_recovery_proofs.py tests/test_request_lineage.py
node packages/arena-pi/extensions/journal.test.ts
```

Results: **10 Python tests and 4 subtests passed in 0.58s; 8 Node tests passed**. Scoped Ruff and TypeScript syntax checks passed. Local Unix-socket access required scoped permission because the sandbox blocks binding. Independent review confirmed the final recovery-transition correction and found no remaining concrete blocker. No provider, real Pi, Lean, or live process inspection ran.

Actual Pi usage/session recovery, real Lean verification and the broader interruption matrix remain final E2E coverage. Ticket 14 was not changed. Reviewer marks ticket 13 **done**.

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 13, v8/13-settlement-recovery and v8/12-process-recovery resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/13-settlement-recovery --above v8/12-process-recovery`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
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

Your branch is **`v8/13-settlement-recovery`**, directly above **`v8/12-process-recovery`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/13-settlement-recovery -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-13`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/13-settlement-recovery`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-13
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
