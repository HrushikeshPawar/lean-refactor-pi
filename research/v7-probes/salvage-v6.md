# Salvage replay, v6 failed drafts

Each failed draft is compiled through `arena.engine.compile_version` (cold `lake env lean`). Error lines map to top-level steps; erroring steps are replaced by `sorry` (leading line kept when the step opens a block and the error is inside it); recompile. Max 4 replacement rounds. Change size = changed lines against the nearest clean node of the same run.

Failed-draft pool: 646 (skipped: {'no-text': 0, 'has-sorry': 49, 'no-change': 0, 'unbucketed': 0}). Sample: 37 drafts, total Lean time 526 s.

## By change size

| change bucket (lines) | n | % salvaged | median holes (salvaged) | median % steps kept (salvaged) | median Lean s per salvage |
|---|---|---|---|---|---|
| 1-3 | 7 | 29 | 1.0 | 83 | 23.8 |
| 4-10 | 10 | 40 | 1.0 | 73 | 7.1 |
| 11-30 | 10 | 40 | 1.0 | 83 | 8.9 |
| >30 | 10 | 50 | 1.0 | 75 | 4.2 |

## Row gate (reference compile, cold, must be clean and <= 120 s)

| theorem | ok | seconds | note |
|---|---|---|---|
| Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius | True | 23.86 | clean |
| Binius.BinaryBasefold.fold_advances_evaluation_poly | True | 8.87 | clean |
| Core.InitsUpdatesComm | True | 3.16 | clean |
| Cslib.CCS.bisimilarity_congr_choice | True | 7.6 | clean |
| Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress | True | 8.24 | clean |
| Cslib.SKI.parallelReduction_diamond | True | 1.01 | clean |
| Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema | True | 21.44 | clean |
| FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | True | 6.4 | clean |
| fundamental_theorem_of_variational_calculus' | True | 2.85 | clean |
| interleaved_affine_gaps_imply_tensor_gaps | True | 22.83 | clean |
| putnam_1964_a4 | True | 33.1 | clean |
| putnam_1964_b2 | True | 14.97 | clean |
| putnam_1995_a3 | True | 5.92 | clean |

## Per draft

| run | theorem | change | status | rounds | holes | % kept | Lean s | first error |
|---|---|---|---|---|---|---|---|---|
| v6pilot-Core.InitsUpdatesComm-qwen3.8-flash-r1 | Core.InitsUpdatesComm | 3 | broken-outside-steps | 1 | 0 | 100 | 2.59 | L9: unsolved goals |
| v6ark2-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1 | FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | 2 | broken-no-progress | 3 | 2 | 0 | 13.8 | L5: (lean.unknownIdentifier): Unknown identifier `timeOrder_superCommute_eq_time_mid` |
| v6ark2-interleaved_affine_gaps_imply_tensor_gap-deepseek-v4.1-flash-r1 | interleaved_affine_gaps_imply_tensor_gaps | 2 | salvaged | 1 | 1 | 80 | 44.46 | L47: Type mismatch |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 3 | broken-no-progress | 3 | 2 | 60 | 10.84 | L8: `grind` failed |
| v6pilot-Core.InitsUpdatesComm-qwen3.8-flash-r1 | Core.InitsUpdatesComm | 3 | salvaged | 1 | 1 | 86 | 3.23 | L16: unsolved goals |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 3 | broken-no-progress | 3 | 2 | 60 | 10.88 | L8: (lean.unknownIdentifier): Unknown constant `compl_involutive.bijective` |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 3 | broken-no-progress | 3 | 2 | 50 | 12.44 | L10: Tactic `rewrite` failed: Did not find an occurrence of the pattern in the current goal |
| v6pilot-Core.InitsUpdatesComm-qwen3.8-flash-r1 | Core.InitsUpdatesComm | 5 | salvaged | 1 | 1 | 86 | 3.36 | L15: Invalid `⟨...⟩` notation: The expected type |
| v6pilot-Cslib.CCS.bisimilarity_congr_choice-deepseek-v4.1-flash-r1 | Cslib.CCS.bisimilarity_congr_choice | 8 | broken-no-progress | 2 | 2 | 33 | 4.62 | L4: Invalid `⟨...⟩` notation: The expected type |
| v6cov-Cslib.LambdaCalculus.LocallyNameless.Fsu-deepseek-v4.1-flash-r1 | Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress | 4 | salvaged | 1 | 1 | 50 | 9.9 | L5: invalid `grind` theorem, failed to find an usable pattern using different modifiers |
| v6cov-Cslib.SKI.parallelReduction_diamond-deepseek-v4.1-flash-r1 | Cslib.SKI.parallelReduction_diamond | 5 | broken-no-progress | 4 | 3 | 25 | 3.44 | L5: `grind` failed |
| v6ark2-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1 | FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | 9 | broken-no-progress | 2 | 3 | 0 | 8.04 | L6: unsolved goals |
| v6ark2-interleaved_affine_gaps_imply_tensor_gap-deepseek-v4.1-flash-r1 | interleaved_affine_gaps_imply_tensor_gaps | 7 | salvaged | 1 | 1 | 80 | 39.3 | L44: Application type mismatch: The argument |
| v6cov-putnam_1964_a4-deepseek-v4.1-flash-r1 | putnam_1964_a4 | 10 | broken-no-progress | 3 | 2 | 83 | 10.76 | L15: Invalid match expression: The type of pattern variable 'a' contains metavariables: |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 4 | broken-no-progress | 3 | 2 | 60 | 10.74 | L9: `grind` failed |
| v6pilot-Core.InitsUpdatesComm-qwen3.8-flash-r1 | Core.InitsUpdatesComm | 7 | broken-no-progress | 3 | 2 | 67 | 4.9 | L11: Invalid `⟨...⟩` notation: The expected type of this term could not be determined |
| v6pilot-Cslib.CCS.bisimilarity_congr_choice-deepseek-v4.1-flash-r1 | Cslib.CCS.bisimilarity_congr_choice | 8 | salvaged | 1 | 2 | 67 | 4.37 | L8: (lean.invalidField): Invalid field `bisim`: The environment does not contain `Exists.bisim`, so it is not possible to pr |
| v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1 | Binius.BinaryBasefold.fold_advances_evaluation_poly | 25 | broken-no-progress | 3 | 2 | 80 | 18.95 | L37: Application type mismatch: The argument |
| v6pilot-Core.InitsUpdatesComm-deepseek-v4.1-flash-r1 | Core.InitsUpdatesComm | 14 | broken-outside-steps | 1 | 0 | 100 | 1.61 | L9: unexpected token 'fun'; expected '{' or tactic |
| v6pilot-Cslib.CCS.bisimilarity_congr_choice-deepseek-v4.1-flash-r1 | Cslib.CCS.bisimilarity_congr_choice | 19 | salvaged | 1 | 4 | 50 | 4.55 | L12: Application type mismatch: The argument |
| v6cov-rerun-Electromagnetism.ElectromagneticPotentia-deepseek-v4.1-flash-r1 | Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema | 28 | broken-no-progress | 4 | 2 | 89 | 46.31 | L57: Tactic `rewrite` failed: Did not find an occurrence of the pattern |
| v6cov-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1 | FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | 12 | salvaged | 1 | 1 | 86 | 9.62 | L42: Tactic `simp` failed with a nested error: |
| v6ark2-interleaved_affine_gaps_imply_tensor_gap-deepseek-v4.1-flash-r1 | interleaved_affine_gaps_imply_tensor_gaps | 11 | salvaged | 1 | 1 | 80 | 42.59 | L40: Application type mismatch: The argument |
| v6cov-putnam_1964_a4-deepseek-v4.1-flash-r1 | putnam_1964_a4 | 20 | salvaged | 1 | 1 | 92 | 8.1 | L25: unsolved goals |
| v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1 | putnam_1964_b2 | 27 | broken-no-progress | 3 | 2 | 83 | 10.71 | L21: unexpected token ';'; expected ')', ',' or ':' |
| v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1 | Binius.BinaryBasefold.fold_advances_evaluation_poly | 26 | broken-no-progress | 3 | 2 | 80 | 17.65 | L28: (lean.synthInstanceFailed): failed to synthesize instance of type class |
| v6pilot-Core.InitsUpdatesComm-deepseek-v4.1-flash-r1 | Core.InitsUpdatesComm | 14 | broken-no-progress | 4 | 2 | 75 | 6.29 | L17: Tactic `rewrite` failed: Did not find an occurrence of the pattern |
| v6ark-Binius.BinaryBasefold.fiberwise_dist_lt-deepseek-v4.1-flash-r1 | Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius | 239 | broken-no-progress | 3 | 3 | 73 | 30.81 | L26: don't know how to synthesize implicit argument `b` |
| v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1 | Binius.BinaryBasefold.fold_advances_evaluation_poly | 57 | salvaged | 1 | 1 | 95 | 13.25 | L77: `simp` made no progress |
| v6c1-Core.InitsUpdatesComm-gpt-6-luna-r1 | Core.InitsUpdatesComm | 44 | salvaged | 1 | 1 | 75 | 3.07 | L31: unsolved goals |
| v6pilot-Cslib.CCS.bisimilarity_congr_choice-qwen3.8-flash-r1 | Cslib.CCS.bisimilarity_congr_choice | 59 | salvaged | 1 | 1 | 67 | 4.25 | L6: `grind` failed |
| v6cov-Cslib.LambdaCalculus.LocallyNameless.Fsu-deepseek-v4.1-flash-r1 | Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress | 46 | broken-pass-limit | 4 | 4 | 67 | 22.51 | L8: unsolved goals |
| v6cov-Cslib.SKI.parallelReduction_diamond-deepseek-v4.1-flash-r1 | Cslib.SKI.parallelReduction_diamond | 37 | salvaged | 1 | 2 | 71 | 1.7 | L21: too many variable names provided |
| v6cov-rerun-Electromagnetism.ElectromagneticPotentia-deepseek-v4.1-flash-r1 | Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema | 37 | broken-no-progress | 3 | 2 | 90 | 30.12 | L19: Application type mismatch: The argument |
| v6ark2-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1 | FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | 49 | broken-no-progress | 3 | 2 | 33 | 11.63 | L46: Tactic `rewrite` failed: Did not find an occurrence of the pattern |
| v6pilot-fundamental_theorem_of_variational_calcu-deepseek-v4.1-flash-r1 | fundamental_theorem_of_variational_calculus' | 121 | broken-no-progress | 3 | 2 | 83 | 4.11 | L23: don't know how to synthesize implicit argument `g` |
| v6ark2-interleaved_affine_gaps_imply_tensor_gap-deepseek-v4.1-flash-r1 | interleaved_affine_gaps_imply_tensor_gaps | 39 | salvaged | 1 | 1 | 83 | 40.49 | L19: interval_cases failed: unsupported type Fin 2 |

## Observations

- 15 of 37 drafts salvaged (41%). Outcomes: 19 broken-no-progress, 2 broken-outside-steps, 1 broken-pass-limit.
- "No progress" means the errors land on a step already reduced to `sorry`, so the next rebuild changes nothing. This is the dominant failure, so the sorry rule itself is the limit, not the 4-round cap.
- Salvaged drafts usually end with 1 hole after one round. Holes do not grow with change size; the 1-3 bucket is the exception (median 1, n=7 only).
- The 1-3 bucket has only 7 drafts in the pool, so it is short of the planned 10. The pool is dominated by larger changes.
- Lean time: 526 s total over 37 drafts (5 cold compiles max per draft). Per-compile cost ranged from about 1 s (SKI) to about 45 s (Electromagnetism, interleaved_affine_gaps).
- Gate: 13 of 13 reference compiles were clean and under 120 s. The gate did not exclude any row.
- Not checked: whether the error-to-step mapping is exact for every draft. The first error is recorded per draft in the table above for spot checks.
