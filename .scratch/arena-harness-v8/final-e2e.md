# Final v8 integration and E2E checklist

Run after the linear implementation stack, not once per ticket. This is the one place to check cross-ticket gaps that a small smoke cannot establish. No checks below have been run by writing this plan.

## Preparation

- Confirm the final branch stack, intended Pi version, effective model/tool schemas and fresh temporary run/service directories. Preserve owners' other runs.
- Collect the 24 focused smoke results. Run the broad offline fast suite once against the integrated stack, not again after every successful step. A failing integrated behavior justifies a targeted rerun after its fix.
- Keep provider traffic scripted/local only. The integration helper must price the selected model correctly; its existing DeepSeek-only fixture assumptions cannot silently price Sol calls.
- The proposed E2E selectors below do not exist yet. Implement the smallest number of full journeys in a new slow-marked final integration module, reusing the existing Pi runner helper, fake provider, graph fixtures and Lean client. Do not create 24 separate slow suites.

## Journey 1: scripted parallel run, stop and recovery

Proposed selector: `tests/test_v8_e2e.py::V8E2ETests::test_parallel_run_stop_and_resume`.

Use actual Pi RPC children and the real runner with a scripted provider. Inject Lean responses so this journey isolates lifecycle and accounting.

- Sol delegates two distinct jobs and continues before a held worker response. A third job queues. A passing candidate publishes before assignment settlement.
- Same-hypothesis follow-up resumes its session; a distinct hypothesis receives a fresh one. Actor focus and delivery remain independent.
- Await uses no provider polling, handles an event arriving at registration, and returns no_pending_work after producers settle. A handled prompt does not leave a phantom run awaited.
- Cancellation clears the queue, aborts and waits for actual exit before a replacement occupies its slot. Check owned process groups after shutdown.
- Actual configured usage for turns, retries and compaction reaches one shared threshold. Unknown usage remains explicit; replay and late settlement do not double-charge. Every transport attempt passes the gate, including retries and summaries; no fetch begins after the stop ordering boundary.
- Interrupt and restart the coordinator at one meaningful launch/settlement boundary. Owned old children are reconciled before replacement; an uncertain remote request is not blindly resent.
- Exercise deterministic stop barriers across compile, scratch, salvage and assembly. Submitted exact candidates may finish checks; evidence from unfinished experiments cannot create a new candidate after stop.

Use one bounded scenario plus fixture-driven barrier variants, not a matrix of real process launches. Preserve real-Pi versus injected-Lean labels in the result.

## Journey 2: actual Lean context, promotion and certification

Proposed selector: `tests/test_v8_e2e.py::V8E2ETests::test_real_lean_promotion_and_cold`.

Run only on an isolated service with actual pinned Lean and saved proofs, no model calls. Choose representative lightweight fixtures first; declare heavy work before launching it.

- Confirm the extractor selects the target proof when an earlier binder contains `by`; check actual goal coverage and target predicate definitions. Cache-only snapshots do not establish this.
- Demonstrate isolated scratch, explicit helper dependencies, exact anchored reconstruction and in-call promotion, with one successful proof and one real invalid proof.
- Verify primary/full/cold distinctions and all required pins for the selected fixture. Endpoint success cannot certify unchecked middle versions.
- Inject resource/worker failures to confirm inconclusive outcomes and certified fallback separately from the real invalid proof result.
- Compete a foreground request, full check and DS experiment through actual service admission. Confirm conservative worker limits, matching-state reuse, timeout recovery and clean shutdown. Record queue/memory outcomes without turning this into the optional resource-efficiency matrix.

Use targeted cases and finite timeouts; do not launch entire historical slow files. Record any unexercised project or pin explicitly instead of claiming full coverage.

## Journey 3: packets, replies, graph and resumed evidence

Proposed selector: `tests/test_v8_e2e.py::V8E2ETests::test_packet_reply_viewer_evidence`.

- Re-render the three preserved packet examples and a worker packet. Check actual goals/definitions, qualified imports, source coordinates, protected nearby lemmas and nested hotspots. Preserve the baseline hashes and distinguish raw proof from line-numbered display.
- Exercise the five proof tools and Sol management tools against actual registered schemas. Help matches nesting/defaults/bounds/allowlists; malformed fences, false search input errors, clipped conclusions and all-missing columns are absent.
- Inspect actual delivered replies, compact graph updates and full retrieval of every shortened signature/goal/diagnostic. Check provisional/all-pin/cold status and measured/reference metric provenance.
- Serve/replay/export/reload a canonical proof with multiple actor attempts and derivations. Retrieve the original record bytes and exact source artifacts, preserving delivered/untrimmed distinction and historical ambiguity.
- Compact/resume, recover strategy/jobs/focus and retrieve evidence by its durable references. Do not restart cancelled jobs or replace original lineage with the summary.
- Check viewer escaping, lazy loading and the intentional-waiting display. A concise graph still exposes failed, duplicate and cancelled work.

## Execution and reporting

The exact new test module/selectors are proposed. Run only these selected journeys once after the broad fast suite. A final batch may take longer than a per-ticket smoke, so record its expected scope, actual duration, failures and skipped prerequisites before broadening it. Do not accidentally start a 30-minute suite after every branch.

Report offline-fast, actual-Pi with scripted provider, actual-Lean, and remaining gaps separately. Production readiness needs the integrated results; ticket smoke success alone is not that claim. Do not mask an assertion failure as a missing prerequisite.

## Separate evaluation, not E2E prerequisites

- Offline cap assurance must be recorded. Current illustrative configuration does not guarantee the $3 cap; owner go/no-go is required for competition execution when assurance is not established. Do not change actual-cost-only stopping or introduce reservations.
- Paid matched pilot, repeats, full development/held-out evaluation and competition submission require their existing owner authorization. No paid call belongs in the automated E2E pass.
- Retention and one/two-heavy-worker experiments remain separately bounded, model-free resource studies. Running that matrix is not a prerequisite for validating the basic conservative prototype.
