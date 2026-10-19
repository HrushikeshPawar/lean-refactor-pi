# Agent optimization cheatsheet — 2026-10-17

Use these examples as search and editing patterns for Lean proof optimization. The measured gains came from changing the proof structure and finding library results that discharged whole obligations. They did not come from renaming identifiers or blindly replacing tactics.

## Establish the baseline first

Record the reference token count, heartbeat count, proxy score, and toolchain set. In this harness, tokens are counted literally: identifiers are one token regardless of name length, and punctuation and blank lines also count. The score averages token reduction, heartbeat reduction, and compatibility, so a shorter proof can lose if it spends too many heartbeats.

For each candidate, search before drafting. Look for a theorem whose conclusion matches the work being done by the reference proof, including imported project lemmas and lemmas far above the target declaration. The successful candidates below all found a shortcut missing from the reference dependency list.

## Three high-value transformations

### Replace stepwise induction with a whole-list result

For Core.InitsUpdatesComm, the reference has 224 tokens and 4,251 heartbeats. Its proof inducts through UpdateStates and handles the individual state updates. DeepSeek’s model-authored run candidate searched for whole-list results such as updatedStatesComm, updatedStatesInit, and updatedStatesUpdate. It reached 83 tokens and 202 heartbeats, score 86.07.

An offline analyst-built hybrid reached 76 tokens and 203 heartbeats, score 87.10. It combines the model’s bulk-lemma proof with smaller ideas from other model runs: use cases on the UpdateStatesUpdated and InitStatesUpdated equations to substitute states, use the commutation theorem as a cast, and let simp use length facts already in context.

    cases InitStatesUpdated Hinit
    cases UpdateStatesUpdated Hup
    unfold updatedStates
    refine updatedStatesComm ?_ ▸ updatedStatesUpdate this (updatedStatesDefMonotone (UpdateStatesDefined' Hup))

The main gain was structural: the model proof removed 141 tokens and 4,049 heartbeats from the reference. The hybrid saved another 7 tokens while heartbeats stayed effectively level. Do not copy the exact theorem names to unrelated goals; search for a whole-structure lemma that matches the local induction’s conclusion.

Evidence: the model candidate is in [the DeepSeek run archive](../../runs/pi-budget/v6pilot-Core.InitsUpdatesComm-deepseek-v4.1-flash-r1/submission.lean). The hybrid artifact is [Core.InitsUpdatesComm-hybrid-v6-87.10.lean](../../runs/analysis/Core_InitsUpdatesComm-hybrid-v6-87.10.lean). The proof comparison, token rules, and validation notes are in [the proof-level report](v6pilot/v6pilot-proofs.md).

### Use symmetry to remove a duplicated proof direction

For Cslib.CCS.bisimilarity_congr_choice, the reference has 251 tokens and 3,858 heartbeats. DeepSeek’s model-authored candidate found HomBisimilarity.symm_simulation, which lets one simulation direction establish the symmetric relation. It reached 85 tokens and 263 heartbeats, score 86.44.

The offline analyst-built hybrid uses the theorem as a cast and reaches 83 tokens and 256 heartbeats, score 86.76. The remaining branches use the existing follow_fst results and map their conjunctions directly with imp and And.imp.

    refine HomBisimilarity.symm_simulation ▸ ⟨ChoiceBisim, .choice h, ⟨fun _ _ => ChoiceBisim.rec (.choice ·.symm) (.bisim ·.symm)⟩, ?_⟩
    exact (hp.follow_fst h).imp fun t => And.imp Tr.choiceL ChoiceBisim.bisim

This saves 168 tokens and 3,595 heartbeats against the reference. The symmetry theorem was outside the reference dependency list. Search for an equivalence, converse, or symmetry characterization before proving both directions by hand.

Evidence: the model candidate is in [the DeepSeek run archive](../../runs/pi-budget/v6pilot-Cslib.CCS.bisimilarity_congr_choice-deepseek-v4.1-flash-r1/submission.lean). The hybrid artifact is [Cslib_CCS_bisimilarity_congr_choice-hybrid-v6-86.76.lean](../../runs/analysis/Cslib_CCS_bisimilarity_congr_choice-hybrid-v6-86.76.lean). The hybrid passed cold full checks on v4.33.0-rc2, v4.32.0, and v4.31.0.

### Replace a manual analytic construction with the exact library theorem

For fundamental_theorem_of_variational_calculus', the reference has 851 tokens and 11,947 heartbeats. DeepSeek’s model-authored candidate found Continuous.integral_pos_of_hasCompactSupport_nonneg_nonzero, then used the project’s primed inner-product lemmas directly instead of embedding through WithLp. Its candidate reached 160 tokens and 1,967 heartbeats, score 88.25.

The offline analyst-built hybrid reduces this to 145 tokens and 1,575 heartbeats, score 89.93. It builds a ContDiffBump directly and leaves a test-function argument inferred from the expected type:

    hg _ (.smul_right ⟨φ1.contDiff, φ1.hasCompactSupport⟩ contDiff_const)

The reference-to-model change saves 691 tokens and 9,980 heartbeats. The hybrid’s inferred argument removed an explicit lambda that cost roughly 300 heartbeats in the measured profile. This hybrid was cold-checked only on v4.32.0; do not extend that validation claim to other versions.

Evidence: the model candidate is in [the DeepSeek run archive](../../runs/pi-budget/v6pilot-fundamental_theorem_of_variational_calcu-deepseek-v4.1-flash-r1/submission.lean). The hybrid artifact is [the PhysLib proof file](../../runs/analysis/fundamental_theorem_of_variational_calculus'-hybrid-v6-89.93.lean). The detailed comparison and single-toolchain caveat are in [the proof-level report](v6pilot/v6pilot-proofs.md).

## Keep provenance clear

The three DeepSeek candidates above were produced inside their provider runs and are run-validated candidates. The 76-token Core, 83-token Cslib, and 145-token PhysLib versions are offline analyst-built hybrids assembled from model-produced ideas and later local edits. They demonstrate measured headroom, but they are not evidence that a single model produced the same transformation unaided. The hybrid cold-check claims are recorded separately in the proof-level report.

## Spend heartbeats and tokens together

After a structural improvement compiles, profile it and compare the token and heartbeat changes using the reference’s exchange rate. The Core reference is about 19 heartbeats per token; Cslib is about 15; PhysLib is about 14. On Cslib, a Qwen variant saved 36 tokens but added 860 heartbeats, lowering the combined score. On Core, a 79-token simp_all variant used 286 heartbeats versus 83 tokens and 202 heartbeats for DeepSeek, with virtually no score improvement. Treat simp_all and grind as candidates to measure, not default golf tools.

## Practical editing order

1. Read the target theorem and reference proof. List the repeated obligations, inductions, casts, and local helper facts.
2. Search for a library result matching the whole obligation, including imported project files and the project’s own typeclass API.
3. Sketch the new proof shape before golfing. Check whether a symmetry result removes a branch, or a bulk result removes induction.
4. Compile the structural candidate. Then profile its expensive lines and use expected types to infer redundant lambdas or arguments where elaboration permits.
5. Make one small edit at a time. Recheck token count, heartbeats, score, and compatibility after each edit.
6. Keep the evidence attached to the claim: model-run candidate, offline hybrid, run validation, and cold toolchain coverage are separate facts.

The examples and measurements are historical results from the v6 pilot, not guarantees for a different theorem, Lean version, or scoring contract. Use the source reports and saved proof files linked above when adapting a pattern.
