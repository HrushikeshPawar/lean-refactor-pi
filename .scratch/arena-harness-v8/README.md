# Harness v8 implementation tickets

This is the local Markdown issue tracker requested by the user, following the v7 layout. There is one implementation ticket per Markdown file under `issues/`. Read and send an agent the individual ticket, not a draft bundle.

- [Shared implementation rules](issues/_common.md) cover GitButler, linear stacking, atomic commits, ownership, one small fast check and hand-back. The resolved rules are also pasted into every ticket as in v7.
- [Shared contracts](contracts.md) define stable cross-ticket interfaces. Each ticket links only the sections it needs and includes its own implementation context, contract and Verify command.
- [Specification](../../docs/SPEC-harness-v8.md) and [plan](../../docs/PLAN-harness-v8.md) retain the design authority and evidence.
- [Final E2E](final-e2e.md) runs broad integration at the end. No full suite, actual Pi/Lean or paid call is a routine ticket gate.
- Run all Python scripts, snippets and tests through `uv run`. The ticket smoke commands use `uv run --no-sync python` to reuse the existing environment without dependency synchronization.

## Linear GitButler stack

The current cleanup baseline is committed on `v8/02-current-work` above the existing v8 work. Ticket 03 stacks there; each later ticket stacks immediately above the preceding ticket. Creating these files does not create all 24 implementation branches. Each implementer prepares only its own branch using the resolved GitButler instructions after the predecessor is reviewed. Never drop or absorb another ticket's work.

## Tickets

| Ticket | File | Branch | Immediate parent | Logical blockers |
|---|---|---|---|---|
| 03 | [Retain exact attempts and derivations](issues/03-exact-history.md) | `v8/03-exact-history` | `v8/02-current-work` | None |
| 04 | [Isolate actor state and enforce exact ownership](issues/04-actor-state-ownership.md) | `v8/04-actor-state-ownership` | `v8/03-exact-history` | 03 |
| 05 | [Settle one shared actual-cost ledger](issues/05-actual-cost-ledger.md) | `v8/05-actual-cost-ledger` | `v8/04-actor-state-ownership` | 03 |
| 06 | [Enforce the stop before every provider dispatch](issues/06-provider-dispatch-stop.md) | `v8/06-provider-dispatch-stop` | `v8/05-actual-cost-ledger` | 05 |
| 07 | [Assess configuration cap exposure offline](issues/07-cap-assurance.md) | `v8/07-cap-assurance` | `v8/06-provider-dispatch-stop` | None |
| 08 | [Delegate one fresh RPC worker asynchronously](issues/08-one-worker-rpc.md) | `v8/08-one-worker-rpc` | `v8/07-cap-assurance` | 04, 06 |
| 09 | [Publish early results and resume the same hypothesis](issues/09-worker-followups.md) | `v8/09-worker-followups` | `v8/08-one-worker-rpc` | 08 |
| 10 | [Admit two workers and cancel stale work cleanly](issues/10-two-worker-cancel.md) | `v8/10-two-worker-cancel` | `v8/09-worker-followups` | 09 |
| 11 | [Wait without polling or no-event deadlocks](issues/11-event-waiting.md) | `v8/11-event-waiting` | `v8/10-two-worker-cancel` | 10 |
| 12 | [Reconcile owned child processes after coordinator failure](issues/12-process-recovery.md) | `v8/12-process-recovery` | `v8/11-event-waiting` | 10 |
| 13 | [Recover charges, candidate receipts and delivery after crashes](issues/13-settlement-recovery.md) | `v8/13-settlement-recovery` | `v8/12-process-recovery` | 12 |
| 14 | [Retain and retrieve isolated scratch experiments](issues/14-scratch-evidence.md) | `v8/14-scratch-evidence` | `v8/13-settlement-recovery` | 04 |
| 15 | [Promote an anchored replacement inside scratch](issues/15-scratch-promotion.md) | `v8/15-scratch-promotion` | `v8/14-scratch-evidence` | 14 |
| 16 | [Order candidate submission against the shared stop](issues/16-stop-submission-races.md) | `v8/16-stop-submission-races` | `v8/15-scratch-promotion` | 06, 15 |
| 17 | [Distinguish proof failures from inconclusive cold checks](issues/17-cold-outcomes.md) | `v8/17-cold-outcomes` | `v8/16-stop-submission-races` | 16 |
| 18 | [Recover usable target goals and definitions](issues/18-context-correctness.md) | `v8/18-context-correctness` | `v8/17-cold-outcomes` | None |
| 19 | [Show readable packets and nested measured hotspots](issues/19-packet-cost-views.md) | `v8/19-packet-cost-views` | `v8/18-context-correctness` | 04, 18 |
| 20 | [Make five-tool replies concise and complete](issues/20-tool-replies.md) | `v8/20-tool-replies` | `v8/19-packet-cost-views` | 09, 15, 19 |
| 21 | [Generate accurate actor-specific schema help](issues/21-schema-help.md) | `v8/21-schema-help` | `v8/20-tool-replies` | 11, 15 |
| 21b | [Let Sol call delegate, jobs and cancel from Pi](issues/21b-sol-management-tools.md) | `v8/21b-sol-management-tools` | `v8/21-schema-help` | 08, 10, 11, 21 |
| 22 | [Inspect every concurrent attempt and exact derivation](issues/22-served-evidence.md) | `v8/22-served-evidence` | `v8/21b-sol-management-tools` | 04, 09, 15 |
| 23 | [Recover strategic context and exact evidence after compaction](issues/23-compaction-resume.md) | `v8/23-compaction-resume` | `v8/22-served-evidence` | 11, 22 |
| 24 | [Demonstrate real Lean admission priorities](issues/24-lean-priority-admission.md) | `v8/24-lean-priority-admission` | `v8/23-compaction-resume` | 10, 17 |
| 25 | [Prepare the owner-run matched-spend pilot](issues/25-matched-pilot.md) | `v8/25-matched-pilot` | `v8/24-lean-priority-admission` | 07, 13, 20, 21, 23, 24 |
| 26 | [Prepare a separate retention and concurrency experiment](issues/26-resource-efficiency-study.md) | `v8/26-resource-efficiency-study` | `v8/25-matched-pilot` | 24 |

## Start here

The first agent handoff is [03: Retain exact attempts and derivations](issues/03-exact-history.md). Complete and review tickets oldest to newest. The implementation model must read its entire ticket, including the pasted shared rules. It must not implement later tickets or invent a broader architecture.

Status `ready-for-agent` means the local ticket is published for handoff, subject to its logical blockers and reviewed stack parent. New module/API/test names remain proposals to implement, not claims of already working runtime. Paid pilot execution and live resource matrices remain owner-scoped evaluation.
