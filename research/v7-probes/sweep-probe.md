# Pre-run sweep probe (warm-up rows, primary toolchain)

The sweep cuts the VALID original proof (tail, subproof and branch cuts, at most 12 per row), asks each
engine (exact?, simp?, aesop?, omega, decide, simp_all, grind, rw?) to close the hole, and verifies every
suggestion or closing engine as a full proof. `d_tok` is against the original proof (negative is shorter).
Heartbeats are measured the harness way (counted wrapper, maxHeartbeats 0); the sweep itself runs with
maxHeartbeats 400000. Lean runs cold, one process at a time, 180 s cap per batch file.

## Per row

| row | toolchain | status | cuts | engine hits (closed / suggest) | verified replacements | compiles | best d_tok | best d_hb (same) | orig tok | known-best tok | Lean s | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CallElimCorrect.substOldPostSubset | v4.26.0 | done | 12 | 0 / 14 | 174 tried, 0 compile | 0 | - | - | 313 | 26 | 229 | - |
| CallElimCorrect.extractedOldExprInVars | v4.26.0 | done | 12 | 0 / 14 | 47 tried, 0 compile | 0 | - | - | 222 | 77 | 111 | - |
| Core.InitsUpdatesComm | v4.29.1 | done | 10 | 0 / 20 | 128 tried, 0 compile | 0 | - | - | 224 | 76 | 51 | - |
| fundamental_theorem_of_variational_calculus' | v4.32.0 | skipped | 0 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 851 | 145 | 5 | original does not compile in batch: ["unexpected token 'set_option'; expected 'lemma'"] |
| Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema | v4.32.0 | skipped | 12 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 1372 | 573 | 195 | sweep batch exceeded 180 s (96 variants) |
| FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | v4.32.0 | skipped | 12 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 1217 | 590 | 191 | sweep batch exceeded 180 s (96 variants) |
| Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress | v4.33.0-rc2 | skipped | 0 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 408 | 332 | 16 | original does not compile in batch: ["unexpected token 'set_option'; expected 'lemma'"] |
| Cslib.SKI.parallelReduction_diamond | v4.33.0-rc2 | skipped | 0 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 407 | 240 | 1 | original does not compile in batch: ["unexpected token 'set_option'; expected 'lemma'"] |
| Cslib.CCS.bisimilarity_congr_choice | v4.33.0-rc2 | skipped | 0 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 251 | 83 | 3 | original does not compile in batch: ["unexpected token 'set_option'; expected 'lemma'"] |
| Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius | v4.31.0 | skipped | 0 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 1463 | 476 | 19 | original does not compile in batch: ["unexpected token 'set_option'; expected 'lemma'"] |
| Binius.BinaryBasefold.fold_advances_evaluation_poly | v4.31.0 | skipped | 0 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 1906 | 258 | 13 | original does not compile in batch: ["unexpected token 'set_option'; expected 'lemma'"] |
| interleaved_affine_gaps_imply_tensor_gaps | v4.31.0 | skipped | 10 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 1353 | 225 | 199 | sweep batch exceeded 180 s (80 variants) |
| putnam_1964_a4 | v4.25.0 | skipped | 12 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 1769 | 312 | 213 | sweep batch exceeded 180 s (96 variants) |
| putnam_1964_b2 | v4.25.0 | skipped | 12 | 0 / 0 | 0 tried, 0 compile | 0 | - | - | 1754 | 39 | 201 | sweep batch exceeded 180 s (96 variants) |

## Engine totals

| engine | closed | suggestion | unavailable |
|---|---|---|---|
| exact? | 0 | 1 | 0 |
| simp? | 0 | 13 | 0 |
| aesop? | 0 | 0 | 34 |
| omega | 0 | 0 | 0 |
| decide | 0 | 0 | 0 |
| simp_all | 0 | 0 | 0 |
| grind | 0 | 0 | 0 |
| rw? | 0 | 34 | 0 |

Rows with at least one verified shorter replacement: 0 (none).
Total Lean seconds (all batches): 1447.

