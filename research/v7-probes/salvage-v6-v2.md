# Salvage replay v2, v6 failed drafts

Escalation per draft in the order S2 (innermost erroring body or leaf) -> S3 (have/obtain/let header: `:= sorry` with the type checked by the next compile, else drop and sorry the parent) -> S4 (on no progress, sorry the parent block). At most 6 compiles per draft (1 + 5 replacement rounds). Sorrying every top-level step is a failure. Same 37 drafts as v1 (`salvage-results.json`).

Pool reproduced: 37. Total Lean time 694 s over 114 cold compiles (median 4.1 s per compile).

## Salvage rate by strategy

Chain = the draft's salvaging chain used this strategy in any round. Final = the strategy of the round that produced the clean compile. Holes = sorry sites in the final sketch. Kept = share of the original non-blank body lines kept verbatim (line-based). Lean s = median per draft (all compiles).

| strategy | overall % (n/37) | 1-3 | 4-10 | 11-30 | >30 | median holes | median % kept | median Lean s |
|---|---|---|---|---|---|---|---|---|
| S1 v1 baseline (not re-run) | 41 (15/37) | 29 (2/7) | 40 (4/10) | 40 (4/10) | 50 (5/10) | 1.0 | 80 | 8.1 |
| S2 (chain) | 41 (15/37) | 29 (2/7) | 50 (5/10) | 30 (3/10) | 50 (5/10) | 1.0 | 68 | 7.0 |
| S3 (chain) | 16 (6/37) | 29 (2/7) | 0 (0/10) | 20 (2/10) | 20 (2/10) | 1.0 | 69 | 9.6 |
| S4 (chain) | 19 (7/37) | 14 (1/7) | 20 (2/10) | 20 (2/10) | 20 (2/10) | 1.0 | 68 | 13.4 |
| **Combined S2→S4** | 54 (20/37) | 57 (4/7) | 50 (5/10) | 50 (5/10) | 60 (6/10) | 1.0 | 78 | 7.4 |

Final-round attribution (count of salvaged drafts whose last round used the strategy): S2 13, S3 6, S4 7.

## Hole goals (SMALL = goal text under 300 chars)

- Salvaged sketches with every hole under 300 chars: 15/20 (75%).
- Holes under 300 chars: 19/24 (79%).

Goal text is a proxy: a `have/obtain : T := sorry` hole uses T; other holes use the original text they replaced, since Lean's goal state is not extracted.

## Status counts

| status | n |
|---|---|
| salvaged | 20 |
| broken-no-progress | 11 |
| broken-pass-limit | 3 |
| broken-outside-steps | 2 |
| broken-whole-proof-sorried | 1 |

## Per draft

| run | theorem | bucket | change | status | rounds | chain | holes | % kept | Lean s | SMALL | first error |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v6pilot-Core.InitsUpdatesComm-qwen3.8-flash-r1 | Core.InitsUpdatesComm | 1-3 | 3 | broken-outside-steps | 0 | - | - | - | 1.33 | - | L9: unsolved goals |
| v6ark2-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1 | FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | 1-3 | 2 | broken-whole-proof-sorried | 1 | - | - | - | 8.72 | - | L5: (lean.unknownIdentifier): Unknown identifier `timeOrder_superCommute_eq_time_mid` |
| v6ark2-interleaved_affine_gaps_imply_tensor_gap-deepseek-v4.1-flash-r1 | interleaved_affine_gaps_imply_tensor_gaps | 1-3 | 2 | salvaged | 3 | S2,S4 | 1 | 42 | 67.63 | no | L47: Type mismatch |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 1-3 | 3 | salvaged | 1 | S3 | 1 | 80 | 7.43 | yes | L8: `grind` failed |
| v6pilot-Core.InitsUpdatesComm-qwen3.8-flash-r1 | Core.InitsUpdatesComm | 1-3 | 3 | salvaged | 1 | S2 | 1 | 86 | 3.12 | yes | L16: unsolved goals |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 1-3 | 3 | salvaged | 1 | S3 | 1 | 80 | 6.75 | yes | L8: (lean.unknownIdentifier): Unknown constant `compl_involutive.bijective` |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 1-3 | 3 | broken-no-progress | 2 | - | - | - | 10.52 | - | L10: Tactic `rewrite` failed: Did not find an occurrence of the pattern in the current goal |
| v6pilot-Core.InitsUpdatesComm-qwen3.8-flash-r1 | Core.InitsUpdatesComm | 4-10 | 5 | salvaged | 1 | S2 | 1 | 90 | 3.15 | yes | L15: Invalid `⟨...⟩` notation: The expected type |
| v6pilot-Cslib.CCS.bisimilarity_congr_choice-deepseek-v4.1-flash-r1 | Cslib.CCS.bisimilarity_congr_choice | 4-10 | 8 | broken-no-progress | 1 | - | - | - | 5.74 | - | L4: Invalid `⟨...⟩` notation: The expected type |
| v6cov-Cslib.LambdaCalculus.LocallyNameless.Fsu-deepseek-v4.1-flash-r1 | Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress | 4-10 | 4 | salvaged | 2 | S2,S4 | 1 | 50 | 13.39 | yes | L5: invalid `grind` theorem, failed to find an usable pattern using different modifiers |
| v6cov-Cslib.SKI.parallelReduction_diamond-deepseek-v4.1-flash-r1 | Cslib.SKI.parallelReduction_diamond | 4-10 | 5 | broken-no-progress | 3 | - | - | - | 3.42 | - | L5: `grind` failed |
| v6ark2-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1 | FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | 4-10 | 9 | broken-no-progress | 2 | - | - | - | 12.14 | - | L6: unsolved goals |
| v6ark2-interleaved_affine_gaps_imply_tensor_gap-deepseek-v4.1-flash-r1 | interleaved_affine_gaps_imply_tensor_gaps | 4-10 | 7 | salvaged | 3 | S2,S4 | 1 | 44 | 74.46 | no | L44: Application type mismatch: The argument |
| v6cov-putnam_1964_a4-deepseek-v4.1-flash-r1 | putnam_1964_a4 | 4-10 | 10 | broken-no-progress | 3 | - | - | - | 15.04 | - | L15: Invalid match expression: The type of pattern variable 'a' contains metavariables: |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 4-10 | 4 | salvaged | 1 | S2 | 1 | 83 | 7.35 | yes | L9: `grind` failed |
| v6pilot-Core.InitsUpdatesComm-qwen3.8-flash-r1 | Core.InitsUpdatesComm | 4-10 | 7 | broken-no-progress | 2 | - | - | - | 4.68 | - | L11: Invalid `⟨...⟩` notation: The expected type of this term could not be determined |
| v6pilot-Cslib.CCS.bisimilarity_congr_choice-deepseek-v4.1-flash-r1 | Cslib.CCS.bisimilarity_congr_choice | 4-10 | 8 | salvaged | 1 | S2 | 3 | 62 | 4.24 | yes | L8: (lean.invalidField): Invalid field `bisim`: The environment does not contain `Exists.bisim`, so it is not possible to pr |
| v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1 | Binius.BinaryBasefold.fold_advances_evaluation_poly | 11-30 | 25 | broken-no-progress | 4 | - | - | - | 30.25 | - | L37: Application type mismatch: The argument |
| v6pilot-Core.InitsUpdatesComm-deepseek-v4.1-flash-r1 | Core.InitsUpdatesComm | 11-30 | 14 | broken-outside-steps | 0 | - | - | - | 1.6 | - | L9: unexpected token 'fun'; expected '{' or tactic |
| v6pilot-Cslib.CCS.bisimilarity_congr_choice-deepseek-v4.1-flash-r1 | Cslib.CCS.bisimilarity_congr_choice | 11-30 | 19 | salvaged | 1 | S2 | 4 | 80 | 4.23 | yes | L12: Application type mismatch: The argument |
| v6cov-rerun-Electromagnetism.ElectromagneticPotentia-deepseek-v4.1-flash-r1 | Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema | 11-30 | 28 | broken-no-progress | 3 | - | - | - | 40.57 | - | L57: Tactic `rewrite` failed: Did not find an occurrence of the pattern |
| v6cov-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1 | FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | 11-30 | 12 | salvaged | 1 | S4 | 2 | 83 | 8.4 | no | L42: Tactic `simp` failed with a nested error: |
| v6ark2-interleaved_affine_gaps_imply_tensor_gap-deepseek-v4.1-flash-r1 | interleaved_affine_gaps_imply_tensor_gaps | 11-30 | 11 | salvaged | 3 | S2,S3 | 1 | 47 | 76.22 | no | L40: Application type mismatch: The argument |
| v6cov-putnam_1964_a4-deepseek-v4.1-flash-r1 | putnam_1964_a4 | 11-30 | 20 | salvaged | 1 | S4 | 2 | 70 | 7.63 | yes | L25: unsolved goals |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 11-30 | 27 | salvaged | 1 | S2,S3 | 1 | 59 | 6.99 | yes | L21: unexpected token ';'; expected ')', ',' or ':' |
| v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1 | Binius.BinaryBasefold.fold_advances_evaluation_poly | 11-30 | 26 | broken-no-progress | 4 | - | - | - | 30.24 | - | L28: (lean.synthInstanceFailed): failed to synthesize instance of type class |
| v6pilot-Core.InitsUpdatesComm-deepseek-v4.1-flash-r1 | Core.InitsUpdatesComm | 11-30 | 14 | broken-pass-limit | 5 | - | - | - | 9.45 | - | L17: Tactic `rewrite` failed: Did not find an occurrence of the pattern |
| v6ark-Binius.BinaryBasefold.fiberwise_dist_lt-deepseek-v4.1-flash-r1 | Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius | >30 | 239 | broken-pass-limit | 5 | - | - | - | 62.41 | - | L26: don't know how to synthesize implicit argument `b` |
| v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1 | Binius.BinaryBasefold.fold_advances_evaluation_poly | >30 | 57 | salvaged | 3 | S2,S4 | 1 | 90 | 26.94 | yes | L77: `simp` made no progress |
| v6c1-Core.InitsUpdatesComm-gpt-6-luna-r1 | Core.InitsUpdatesComm | >30 | 44 | salvaged | 1 | S2 | 1 | 97 | 3.11 | yes | L31: unsolved goals |
| v6pilot-Cslib.CCS.bisimilarity_congr_choice-qwen3.8-flash-r1 | Cslib.CCS.bisimilarity_congr_choice | >30 | 59 | salvaged | 1 | S2 | 1 | 75 | 4.31 | yes | L6: `grind` failed |
| v6cov-Cslib.LambdaCalculus.LocallyNameless.Fsu-deepseek-v4.1-flash-r1 | Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress | >30 | 46 | broken-pass-limit | 5 | - | - | - | 27.22 | - | L8: unsolved goals |
| v6cov-Cslib.SKI.parallelReduction_diamond-deepseek-v4.1-flash-r1 | Cslib.SKI.parallelReduction_diamond | >30 | 37 | salvaged | 2 | S2,S4 | 2 | 68 | 2.43 | no | L21: too many variable names provided |
| v6cov-rerun-Electromagnetism.ElectromagneticPotentia-deepseek-v4.1-flash-r1 | Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema | >30 | 37 | broken-no-progress | 4 | - | - | - | 50.55 | - | L19: Application type mismatch: The argument |
| v6ark2-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1 | FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | >30 | 49 | salvaged | 2 | S2,S3 | 1 | 4 | 11.78 | yes | L46: Tactic `rewrite` failed: Did not find an occurrence of the pattern |
| v6pilot-fundamental_theorem_of_variational_calcu-deepseek-v4.1-flash-r1 | fundamental_theorem_of_variational_calculus' | >30 | 121 | broken-no-progress | 2 | - | - | - | 4.23 | - | L23: don't know how to synthesize implicit argument `g` |
| v6ark2-interleaved_affine_gaps_imply_tensor_gap-deepseek-v4.1-flash-r1 | interleaved_affine_gaps_imply_tensor_gaps | >30 | 39 | salvaged | 1 | S3 | 1 | 96 | 36.59 | yes | L19: interval_cases failed: unsupported type Fin 2 |
