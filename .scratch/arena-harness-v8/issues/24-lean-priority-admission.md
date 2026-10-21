# 24: Demonstrate real Lean admission priorities

**What to build:** Foreground, compatibility and worker requests receive demonstrated priority and conservative memory admission under contention.

**Blocked by:** 10: Admit two workers and cancel stale work cleanly; 17: Distinguish proof failures from inconclusive cold checks

**Status:** changes-requested

**Branch:** `v8/24-lean-priority-admission`

**Stacked on:** `v8/23-compaction-resume`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 40–43; appendix H and J. The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** Service-client dispatch/admission and its measured outcomes. Preserve toolchain/cache identity and do not speculate on extra workers.

**Shared contracts:** [S6](../contracts.md#s6-scope-and-error-contracts)

## Current implementation context and contract

**Current entry points:** arena/lean_session.py::Session.check, _lane, _acquire, _new_slot; WorkerBudget; arena/campaign.py::_evaluate.

**Implementation contract:** Add request_class independently of lane using S6. Choose highest-priority queued class then FIFO within it, preserve warm header choice/memory/tokens, and keep one DS Lean operation. Executing calls finish safely; priority affects the next admission, not unsafe preemption. Inject memory and worker availability. Return explicit queued/denied reasons and classify infrastructure denial as inconclusive.

**Smoke outcome:** Feed an injected service dispatcher speculative/full/Sol requests with one available worker; observe Sol then full then DS dispatch, preserve one-DS limit and the memory-denial reason.

## What to build and acceptance

- [x] 1. Initially allow one DeepSeek Lean compilation. Demonstrate Sol foreground and promising full checks ahead of speculative worker experiments, with opportunistic background work last.
- [x] 2. Do not infer priority from lane labels or attempt unsafe preemption. Show how already-running checks yield/complete safely and queued work is selected.
- [x] 3. Preserve warm-state identity, demand-driven allocation, the 5 GiB safeguard, timeout recovery and checker cleanup. Inject resource readings in deterministic tests.
- [x] 4. Compete foreground, worker and full-check requests with recorded dispatch order and memory-denial/inconclusive outcomes; tests do not read other live runs.
- [x] 5. Use the one assigned fast smoke for this slice. Retain the stated behavior requirements; actual-Pi/real-Lean journeys and the broader race matrix are final E2E coverage, not this ticket's gate.
- [x] 6. Keep more-worker/retention optimization in its separate experiment, not speculative new defaults.

## Review findings (Claude, 2026-10-21)

Commit `qln` implements real dispatch priority: `select_waiter` chooses by class and then FIFO, the one-DS-compile cap is rechecked under `self.lock` with the rejected slot freed, and `check`/`try_snippets` release in `finally` and notify waiters. The items below are reopened. Admission is only as strong as its least-guarded path, and the first two items let Lean work avoid it entirely.

**Blocker**
1. **A denial becomes an unadmitted cold Lean** (decision 42; acceptance 3–4). `engine.run_lean` checks only `reply.get("ok")`. Any other reply, including memory denial (`no room for a Lean worker: memory`), the queue timeout and the new DS-cap rejection, falls through to `_run_cold`, which spawns `lake env lean` with no class, memory, token or cap check. Three speculative DS compiles under memory pressure become three heavy unadmitted processes, and a capped second DS compile simply runs cold. `_admission_reply`'s `outcome: inconclusive`, `cause` and `admission` are never read by `run_lean`, so a denial turns into a cold pass or fail instead of an inconclusive result.
   - **Fix:** when the session is configured and replies with `admission` denied or queued, or with an `inconclusive` outcome, return an inconclusive result to the caller (no cold run) and preserve `cause`. Keep the cold path only for "no session configured" or an unreachable daemon, and never for `ds_experiment` or `opportunistic`.
   - Make the callers that report verdicts (compile, scratch, `evaluate`) show inconclusive with the cause, never a proof error.

**Should-fix**
2. **`force_cold` paths skip admission** but carry class labels that are never consulted: `golf_file` (golf.py:362, 371), `build_index` (index.py:261), `cold_verify` (campaign.py:4669) and `submission.py:131`. Cold certification must stay a fresh independent process (ticket 17), but it and the other cold paths still need the 5 GiB memory admission before spawning. Take an admission token from the session (or the same memory check) before any cold spawn, with the call's class. Golf and index are `opportunistic`; cold certification is `full_check`.
3. **Fail-open defaults.** An omitted class becomes `sol_foreground` in `run_lean`/`evaluate` and `full_check` at the daemon. Callers without a class:
   - `profile.compile_version` (profile.py:425, 432, 474);
   - `lean_repl.py:263`;
   - the `lean_load.py:462` payload;
   - `warm_session` (engine.py:686; campaigns.py:1338, 1344);
   - `cli/certify.py` fast;
   - `cli/evaluate.py`.

   Pass explicit classes at every call site. Make the omitted default `opportunistic` (the daemon's too). Only tool calls that originate from an agent derive `sol_foreground`/`ds_experiment` from the actor.
4. **"Promising" full checks.** Every `mode == "full"` evaluation becomes `full_check`, including a full check a DS worker requests in its own tool call, which then outranks and escapes the DS cap. Use `full_check` for harness-submitted promising checks (the autocheck queue and certification). A full check requested in a worker's tool call keeps `ds_experiment`.

**Nits**
- A queue timeout is reported as `admission: denied`, so the queued branch of `_admission_reply` is unreachable.
- `try_snippets` and `warm` failures do not carry `outcome`/`cause`/`admission`.
- The DS cap is global across workers, which matches "one DS Lean compilation"; state it in the code comment.

**Test stubs broken by the new keyword:** `request_class` reaches stubs that do not accept it. This breaks 4 tests outside the named smoke:
- `tests/graph_support.py::FakeRunCase.fake_eval` (used by `test_tools_read_goal_search.py::test_goal_at_error_line_is_blocked_until_error_is_replaced` and `test_goal_try_at_the_failing_line_runs_in_place_of_that_line`);
- `compile_stub` in `tests/test_environments.py::MeasurementVersionTests::test_fast_mode_also_compiles_the_measurement_version_and_records_it`;
- `fake` in `tests/test_lean_session_warm.py::ColdPathTests::test_arena_lean_timeout_is_used_and_named_in_the_error`.

Accept the keyword in the stubs. `test_environments.py::CertificationTests::test_matching_reference_is_certified` failed before this ticket and is not yours.

Extend the existing admission smoke with one denied DS request (inconclusive, no cold spawn: inject `_run_cold` and assert it is not called) and one omitted-class harness call (opportunistic). Run the whole touched test files. No real Lean is needed.

## Verify

Use one focused smoke. This selector is **proposed**, not an already-passing test. Reuse or extend the named existing case when possible; if the module/class is new, add only the boundary smoke needed for this journey. No tests collected is not a pass.

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_orchestration.py::V8AdmissionSmokeTests::test_v8_request_class_dispatch
```

Expected: the named behavior check passes with no actual provider, Pi or Lean process. Aim for seconds and at most 60 seconds. No per-ticket full suite or slow suite.

**Deferred to final E2E:** Actual contention, PSS/swap/PSI, warm retention and checker shutdown. See the shared [final E2E checklist](../final-e2e.md).

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 24, v8/24-lean-priority-admission and v8/23-compaction-resume resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/24-lean-priority-admission --above v8/23-compaction-resume`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
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

Your branch is **`v8/24-lean-priority-admission`**, directly above **`v8/23-compaction-resume`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/24-lean-priority-admission -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-24`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/24-lean-priority-admission`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-24
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
