# 22: Inspect every concurrent attempt and exact derivation

**What to build:** The served graph keeps canonical proofs readable while exposing every attempt, experiment, job and original call on demand.

**Blocked by:** 04: Isolate actor state and enforce exact ownership; 09: Publish early results and resume the same hypothesis; 15: Promote an anchored replacement inside scratch

**Status:** needs-review

**Branch:** `v8/22-served-evidence`

**Stacked on:** `v8/21b-sol-management-tools`

**Read first:** [Harness v8 specification](../../../docs/SPEC-harness-v8.md), Decisions 21–30, 61–63; appendix A and C. The shared GitButler/testing rules are included below, matching [_common.md](_common.md).

**Ownership:** Graph/node/experiment/job serving and replay evidence joins. Preserve current viewer security/lazy behavior.

**Shared contracts:** [S1](../contracts.md#s1-retain-the-existing-ledger-and-file-lock-model), [S6](../contracts.md#s6-scope-and-error-contracts)

## Current implementation context and contract

**Current entry points:** arena/cli/serve.py::graph_payload, handler_for; arena/viewer_data.py::node_calls, run_dashboard; arena/graph_viewer/hub.js.

**Implementation contract:** Serve canonical proofs with expandable attempt/derivation/experiment/job collections from the shared projection. Node detail joins explicit actor/session/request/tool IDs and preserves raw/original record references. Show all jobs and intentional waiting, actual spend grouped once and explicit provisional/full/cold evidence. Keep lazy call fetching, delivered/untrimmed distinction, escaping and CSP.

**Smoke outcome:** One stored two-actor duplicate-proof fixture builds a graph/node payload containing both attempts, original derivations, correct job states and raw call references without duplicate proof nodes.

## What to build and acceptance

- [x] 1. Show canonical proof nodes with expandable attempts/alternate derivations and a complete job/experiment log, including failed, duplicate and cancelled work.
- [x] 2. Expose all actors and queue/check/wait/cancellation states, one actual spend total and attributed costs without double-charging candidates.
- [x] 3. Preserve lazy reasoning/calls, delivered versus untrimmed results, exact new identity joins and explicit historical ambiguity/missing artifacts.
- [x] 4. Retrieve original serialized lineage/artifact bytes and every alternate derivation through node/experiment detail without generated replacements.
- [x] 5. Use existing viewer/replay fixtures with multi-actor histories, including duplicate proofs and historical ambiguity. Preserve lazy loading and escaped text.
- [x] 6. Compaction memory is not part of this slice; prove complete original evidence access first.

## Review findings (Claude, 2026-10-21)

Commit `ook` serves exact ledger bytes (`read_bytes`, byte offsets, sha256 per line), adds no text/time/similarity inference, and introduces no new failures in `tests/test_viewer.py`/`tests/test_graph.py`. The items below are reopened.

**Blockers**
1. **Uncommitted rows leak into node detail.** `experiments.original_lines` (used by `viewer_data._lineage_records` and `experiments.retrieve`) scans raw `ledger.jsonl`. `attempts`/`derivations` come from `published_history` and the committed projection. After a crash between `append_ledger` and the committed receipt, the panel shows an attempt/derivation/scratch row that ticket 16 says must not exist. Select lines whose `operation_id` is absent or in `run_control.committed_operation_ids(directory)`, matching `committed_history`.
2. **Two node numberings in one response.** `viewer_data` resolves `nN` via `_proof_of(read_jsonl(ledger), node)` (raw) in one place and via `published_history` in `_served_lineage`. One uncommitted candidate before the node shifts the numbering, so `attempts` describe one proof while `records`/`artifact` describe another. Resolve `proof_id` once from the published history and pass it through. Decision 26 asks for one projection.

**Should-fix**
3. **Serving must not write run state.** `serve._attributed_spend` calls `run_control.read_state`, which takes `control_lock` and can append `run_stop`/`accounting_failure` rows and rewrite `cost.json`. Every graph poll can therefore mutate the run and contend with writers. Read without repair, e.g. `_spend_view(_control_rows(directory))`.
4. **One actual spend total (decisions 30, 63; appendix D).**
   - With `control.jsonl` present, the payload carries both `spend.total` (control) and `cost.spent_usd` (legacy cost ledger), and they can disagree. Serve one total; derive any timeline from the same source or label it as a non-authoritative breakdown.
   - The no-control fallback skips `usage_known: false` rows yet reports `accounting: "known"`. Report it as unknown/incomplete.
   - The new `request_id` dedup makes the viewer disagree with `summary.ledger_spend` (0.2 vs 0.4 on the test ledger). Use one dedup rule in both, or none.
   - A torn tail line in `cost-ledger.jsonl` makes `json.loads` raise a 500. Skip torn lines.
5. **Joins and explicit missing (decisions 54, 57, 62).**
   - `call_refs` lacks `job_id`, `request_id` and evaluation ids.
   - Alternate attempts get a reference but no call.
   - A legacy node without attempt/derivation events gets no `artifact`/`records`/missing marker; mark it missing explicitly.
   - An undecodable artifact (`data.decode()`) raises a 500.
6. **Job log is a raw dump.**
   - `campaign._served_jobs` mixes orchestration jobs with runtime `job` events (`phase:kind:candidate` ids) under one `job_id` key, with no kind/activation/operation/event id, so consumers cannot tell them apart or join to originals.
   - `kind == "wait"` rows are never written, so intentional waiting (decision 63) is not served. Derive the waiting state from `await_results` registration, or drop the claim.
   - `_served_actors` keeps the first `session_id`; a multi-session actor must list all sessions or be marked ambiguous.

Extend the existing smoke with one uncommitted-row case and one unknown-usage case. Do not add a test per bullet. Run the whole touched test files. `tests/test_graph.py` has 7 older failures (6 lineage/stall plus 1 that needs `lake`) and `tests/test_viewer.py::DataTests::test_dashboard_sections` is older too; report them unchanged unless this rework fixes them.

## Verify

Use one focused smoke. This selector is **proposed**, not an already-passing test. Reuse or extend the named existing case when possible; if the module/class is new, add only the boundary smoke needed for this journey. No tests collected is not a pass.

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_viewer.py::NodeCallTests::test_v8_node_retains_alternate_actor_attempts
```

Expected: the named behavior check passes with no actual provider, Pi or Lean process. Aim for seconds and at most 60 seconds. No per-ticket full suite or slow suite.

**Deferred to final E2E:** Interactive browser rendering and real concurrent-process event streams. See the shared [final E2E checklist](../final-e2e.md).

---

<!-- Shared v8 implementation rules. Included in every numbered ticket with 22, v8/22-served-evidence and v8/21b-sol-management-tools resolved. This template is not an implementation ticket. -->

## Before you start

1. Read this whole ticket, the named sections of `docs/SPEC-harness-v8.md`, and the shared contract sections linked above. The current v8 decisions and the user's minimum-fast-test policy are binding. Do not rediscover or reverse settled budget, ownership, lineage or lifecycle decisions.
2. Read the installed `but` skill before version-control commands. Run `but status` to confirm the named stack parent and identify existing uncommitted work. You are not alone in the checkout. Do not modify or commit another ticket's work. Unrelated dirty files may remain; overlapping uncommitted changes or an unexpected parent must be reported before editing.
3. If your branch is absent and the named parent is the reviewed current top of the stack, create only this ticket's branch with `but branch new v8/22-served-evidence --above v8/21b-sol-management-tools`. If it exists, verify its position and continue. Do not create later branches, move existing lower branches, or repair an unexpected stack on your own.
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

Your branch is **`v8/22-served-evidence`**, directly above **`v8/21b-sol-management-tools`**. Work proceeds one reviewed ticket at a time, oldest to newest. Logical blockers are listed separately from this immediate stack parent.

- Use `but` for status, diffs, branch creation, commits and history inspection. Never substitute raw Git write commands or run `but setup`.
- Commit only your own changes. Use `but diff`, copy the current file/hunk IDs, then `but commit -b v8/22-served-evidence -m "type(scope): summary" <id> <id>`. Never omit IDs when another session has dirty work. Use hunk IDs if one file mixes ownership.
- Keep commits atomic. Put the behavior and its focused check together; separate unrelated generated output or documentation. One ticket may have several coherent commits; it must not become one giant unrelated commit.
- Use succinct Conventional Commits subjects. Include non-obvious decisions and the selected verification in the body when needed. End the body with `Ticket: v8-22`.
- For a small follow-up clearly belonging to your own unpublished commit, use `but amend -t <commit> <ids>`. Never rewrite another ticket, a reviewed/pushed commit, or ambiguous history. Such a change needs reviewer direction.
- Do not push, open PRs, pull, merge, discard other work, or move/restack lower branches. If a commit reports an unexpected dependency/conflict, report it; do not work around it by rebuilding the stack.
- Mutation output reports success. Do not append routine status/diff calls after every mutation. Reinspect only when the next action actually needs new IDs or remaining-change information.
- Do not change the plan, spec, shared contracts, other tickets, or `vendor/` to make an implementation appear compliant. Propose a concrete contract correction to the reviewer if required. Update only your own ticket's checkboxes/status as part of its hand-back.

## Hand-back

- Every acceptance item is done or explicitly reported incomplete with its reason.
- Your changes and focused check are committed only on `v8/22-served-evidence`. Other sessions' files/commits are preserved. A globally clean workspace is not claimed if unrelated work exists.
- Change this ticket's Status to `needs-review` in your final commit. The reviewer marks it done.
- Report the exact focused command and result, relevant baseline, changed interfaces, files/commits and deferred final-E2E coverage. Do not claim unrun integration or broad suites passed.

Use this concise review report:

```text
Review report: v8-22
Commits: oldest first
Acceptance: done / incomplete with reason
Check: exact command, baseline if relevant, result
Interfaces: changed contracts and callers
Deferred E2E: actual-Pi/Lean/cross-ticket coverage not run
Deviations: accepted mappings or unresolved contract conflicts
Out of scope: defects noticed, not changed
```
