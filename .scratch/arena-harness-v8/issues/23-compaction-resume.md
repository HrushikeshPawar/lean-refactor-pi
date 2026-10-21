# 23: Recover strategic context and exact evidence after compaction

**What to build:** A resumed Sol or worker recovers its jobs, focus and useful findings using durable references to complete originals.

**Blocked by:** 11: Wait without polling or no-event deadlocks; 22: Inspect every concurrent attempt and exact derivation

**Status:** needs-review

**Branch:** `v8/23-compaction-resume`

**Stacked on:** `v8/22b-no-legacy-stops`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 20, 25, 32, 60; appendix A, F and G. The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** Compaction working context, resumed-session recovery and evidence references. Reuse the completed viewer/projection and lifecycle.

**Shared contracts:** [S4](../contracts.md#s4-worker-process-policy), [S6](../contracts.md#s6-scope-and-error-contracts), [S7](../contracts.md#s7-initial-public-management-shapes-and-delivery-semantics)

## Current implementation context and contract

**Current entry points:** arena/memory.py::memory, memory_text; arena/reply.py::reset_delivered; packages/arena-pi/extensions/arena.ts compaction/resume handling.

**Implementation contract:** Summary includes current strategy and actor-local focus/jobs, useful findings/failures and exact evidence references. It must not overwrite original logs or treat summarization as a new proof derivation. After resume recover jobs from retained state, not the prose alone. Sol-owned strategy remains distinct from worker notes. Keep actual shared-spend policy and remove voluntary-finish/rerouting language.

**Smoke outcome:** Build memory for a completed/cancelled worker plus an alternate derivation, reload it and retrieve original evidence; neither job reactivates merely because it appears in the summary.

## What to build and acceptance

- [x] 1. Retain current strategy, actor-local focus/jobs, useful failed experiments and exact proof/experiment/lineage references in the working summary.
- [x] 2. Sol alone replaces shared strategy; workers retain attributed observations and hypothesis-local notes. Notes remain optional for new intent.
- [x] 3. Retrieve complete original records and artifacts after compaction/resume; summaries cannot overwrite lineage or erase alternate derivations.
- [x] 4. Keep actual shared-cost and no-voluntary-finish wording consistent; do not reintroduce raw pin hashes, transcript dumps or paid waiting polls.
- [x] 5. Combine compacted/resumed session evidence with jobs/no-event waiting so a settled or cancelled assignment is not restarted accidentally.
- [x] 6. Use the one assigned fast smoke for this slice. Retain the stated behavior requirements; actual-Pi/real-Lean journeys and the broader race matrix are final E2E coverage, not this ticket's gate.

## Review findings (Claude, 2026-10-21)

Commit `nxl` writes nothing to the ledger, keeps strategy Sol-only, reuses `orchestration.jobs` and reply focus state, and adds no finish, island or restart wording. The items below are reopened. Tickets 20 and 22 had the same failure as the first two, so fix them through the shared paths, not new filters.

**Blockers**
1. **Raw history in the summary and in retrieval.** `memory.memory` (memory.py:202) and `memory.original_evidence` (:181) read `campaign.events()`. Only the Graph gets `committed_operation_ids`; strategy, findings, evidence, reads, library, holes and `_recovery` all use the raw rows. An aborted or unreceipted attempt, derivation or scratch row therefore appears in the compaction summary and is returned by retrieval, and ticket 16 says it must not exist. Use `run_control.published_history(directory, history)` once, as `experiments._scratch` and `orchestration._history` do, and pass that one history everywhere.
2. **The summary is not actor-local** (decisions 26, 32; contract "actor-local focus/jobs"). `memory(run_id)` takes no actor. It lists every actor's focus (`reply.actor_focuses`), every actor's hypothesis notes and findings, and every job, so a resumed worker can adopt another worker's focus or notes as its own. Pass the compacting actor (`current_actor()`). Show Sol's plan to everyone and attributed shared observations to everyone, but only that actor's focus and hypothesis-local notes. Sol sees all jobs; a worker sees its own job.

**Should-fix**
3. **Path traversal in `original_evidence`.** `_proof_reader` builds `proofs/{ref}.lean` from the ref without validation, so `../../../x` reads any `.lean` file. A proof file is also returned without checking that its attempt committed. Accept only proof ids in the stored id format, reject anything else as missing, and require a committed attempt.
4. **Every emitted ref must resolve.** `_event_ref` falls back to `experiment_id`, then `operation_id`, but `original_evidence` matches only `event_id`, `experiment_id`, code hash and proof id. A row listed as `derivation <operation_id>` then retrieves nothing. Emit only ref forms the retriever accepts, or accept `operation_id`.
5. **Retrieval is not reachable by the model** (acceptance 3). `original_evidence` has no caller outside tests: it is in neither `arena/cli/protocol.py` nor any Pi tool. After compaction the model sees references it cannot follow. Expose it through an existing read path (for example `read` with a `ref`, or the experiment retrieval that already exists) without changing other tools' public forms. If that needs a schema change, record it in ticket 21's schema file and help.
6. **Unbounded summary.** Findings and Evidence have no cap, unlike `memory_read_entries` and `memory_library_lines`, so every attempt and derivation is relisted at every compaction. Cap them with a template-owned number and say how many were omitted; the references stay retrievable.

Extend the smoke with one uncommitted row (excluded from the summary and from retrieval), two workers (each sees only its own focus and notes), and one traversal ref (returns missing). Run the whole touched test files. Older failures that are not this ticket's and predate ticket 19's tip: `tests/test_context.py::ProfileSectionTests` (2), `tests/test_text_lint.py::test_model_facing_modules_have_no_inline_prose`, `tests/test_tools_reply.py::test_an_update_names_its_source_node_only_once_the_model_has_seen_it`, plus the known `tests/test_text.py` ones.

## Verify

Use one focused smoke. This selector is **proposed**, not an already-passing test. Reuse or extend the named existing case when possible; if the module/class is new, add only the boundary smoke needed for this journey. No tests collected is not a pass.

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_memory.py::MemoryTests::test_v8_resume_recovers_references_not_work
```

Expected: the named behavior check passes with no actual provider, Pi or Lean process. Aim for seconds and at most 60 seconds. No per-ticket full suite or slow suite.

**Deferred to final E2E:** Actual Pi compaction/retry and resumed provider context. See the shared [final E2E checklist](../final-e2e.md).

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 23, v8/23-compaction-resume and v8/22b-no-legacy-stops resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/23-compaction-resume --above v8/22b-no-legacy-stops`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
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

Your branch is **`v8/23-compaction-resume`**, directly above **`v8/22b-no-legacy-stops`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/23-compaction-resume -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-23`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/23-compaction-resume`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-23
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
