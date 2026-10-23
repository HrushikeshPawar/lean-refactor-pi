# Agent-owned final-proof policy — 2026-10-17

## Decision implemented here

The runner no longer performs a proof-golfing pass after the agent exits. `finish()` still drains queued full checks, then summarizes the run and chooses the submission. The legacy `--no-golf` option remains accepted for compatibility and is now inert because post-run golf is disabled for every run.

Explicit golf workflows remain available through the `arena golf` command and `arena.golf.golf_run`; this change removes only the implicit call from the run finalizer. Historical golf records and their readers remain available for research attribution.

## Caller and ownership audit

The live background autocheck scheduler processes full checks, salvage, assembly, step goals, and profiles. Salvage takes a broken filed node, constructs a sketch with holes, files that sketch as an unscored probe, and publishes a state update asking the agent to fill those holes. Assembly runs once every hole has a closing fill, selects fills, compiles their combination, and publishes the result and selected sources in the next state update.

The closing drain uses a different queue: it performs pending full checks and then automatic assembly. It intentionally skips salvage, step goals, and profiles. Therefore an assembly can still be created after the agent exits. `submission()` considers verified full candidates from every non-reference origin, including `assembly`, and ranks them by score. If that automatically assembled candidate wins, it can become the delivered proof without a post-assembly agent compile or selection. Cold verification may certify the candidate's Lean behavior, but does not establish agent ownership.

## Ownership boundary and remaining work

The implemented boundary is limited to removing post-exit tactic deletion by golf. Verification of already filed candidates continues after the agent exits. Automatic salvage and assembly remain enabled as existing in-run assistance, and closing assembly remains enabled; their outputs are recorded and surfaced through state updates when they occur during the live session.

Strict agent-owned submission is not yet enforced for salvage or assembly. The ledger records salvage lineage (`salvaged_from`) and assembly lineage (`merged_from`, `origin=assembly`), but submission eligibility currently depends on verification and score, not on an explicit agent selection event. A strict ownership policy would need to define and implement which origins become eligible only after an agent sees and explicitly compiles or selects them. That broader eligibility change is outside this patch and should be decided separately before claiming that all final proofs are agent-owned.
