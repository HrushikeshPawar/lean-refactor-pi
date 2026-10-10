# Hotspots for all 15 rows (cached data, no Lean)

Step table: `tok` = tokens attributed to the innermost tactic span covering each proof line (harness per-line counts, `line_tokens`); `hb` inclusive, `self` exclusive of nested tactics (units = raw/1000); `share` = self/measured total; points = what removing that step entirely would be worth (tok*pts/token + self*pts/hb), not predicted savings. Indent = depth.


## Heartbeat measurement notes
- Official worker code is not in vendor/arena-space (README.md:12-14: Lean compile and scoring run on a separate worker). Only the hint is public: app.py:1542-1546,1857-1860 (`#count_heartbeats`, getNumHeartbeats), contribution.md:21-22 (`set_option Elab.async false`). Official tokens: benchmark_data_warmup.jsonl `proof_length` (benchmark.py:117), reference hb: benchmark_heartbeats.jsonl (benchmark.py:83-118). Coverage: leaderboard.py:107-112 (passed/len(compat)).
- Ours: engine.py:28-40 wrapper, engine.py:123-133 measure_version (no override file exists), scoring.py:34-52 rates, scoring.py:62-100 metrics. Cannot be verified exact; docs/H1.md:84-92 records 1-3 hb differences on 5 rows.
- Reference profile measured_total vs official denominator: Putnam rows disagree (b2 -10.4%, a3 +27.1%, a4 profiled +25.6%); Binius 0.5-1.7%; others within 0.1%.

## Cross-row summary

| row | ref tok | best tok | ref hb | best hb | tok% | hb% | cov% | proxy | headroom axis (pts) | top ref hotspot | best profiled |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Core.InitsUpdatesComm | 224 | 76 | 4251 | 203 | 66.07 | 95.22 | 100.0 | 87.1 | tokens (11.3) | L36 1036hb (24.4%) | N |
| fundamental_theorem_of_variational_calculus' | 851 | 145 | 11947 | 1575 | 82.96 | 86.82 | 100.0 | 89.93 | tokens (5.7) | L42-43 3873hb (32.4%) | N |
| Cslib.CCS.bisimilarity_congr_choice | 251 | 83 | 3858 | 256 | 66.93 | 93.36 | 100.0 | 86.76 | tokens (11.0) | L58 797hb (20.7%) | N |
| CallElimCorrect.extractedOldExprInVars | 222 | 77 | 2696 | 487 | 65.32 | 81.94 | 100.0 | 82.42 | tokens (11.6) | L7-10 1108hb (41.1%) | N |
| CallElimCorrect.substOldPostSubset | 313 | 26 | 5175 | 2230 | 91.69 | 56.91 | 100.0 | 82.87 | heartbeats (14.4) | L6 1235hb (23.9%) | N |
| putnam_1964_a4 | 1769 | 312 | 111476 | 6515 | 82.36 | 94.16 | 100.0 | 92.17 | tokens (5.9) | L71-162 53552hb (38.3%) | N |
| putnam_1964_b2 | 1754 | 39 | 134499 | 2895 | 97.78 | 97.85 | 100.0 | 98.54 | tokens (0.7) | L172-209 25682hb (21.3%) | N |
| putnam_1995_a3 | 4085 | 433 | 14130 | 2412 | 89.4 | 82.93 | 100.0 | 90.78 | heartbeats (5.7) | L78-100 2035hb (11.3%) | N |
| Electromagnetism.Electromagnet..of_isExtrema | 1372 | 573 | 26970 | 6275 | 58.24 | 76.73 | 100.0 | 78.32 | tokens (13.9) | L20-126 3997hb (14.8%) | N |
| Cslib.LambdaCalculus.LocallyNa..ing.progress | 408 | 332 | 59830 | 1006 | 18.63 | 98.32 | 100.0 | 72.32 | tokens (27.1) | L66 24198hb (40.5%) | N |
| Cslib.SKI.parallelReduction_diamond | 407 | 240 | 1383 | 416 | 41.03 | 69.92 | 100.0 | 70.32 | tokens (19.7) | L29-31 67hb (4.8%) | N |
| Binius.BinaryBasefold.fiberwis..oding_radius | 1463 | 476 | 15645 | 3831 | 67.46 | 75.51 | 100.0 | 80.99 | tokens (10.8) | L87-88 1483hb (9.3%) | N |
| Binius.BinaryBasefold.fold_adv..luation_poly | 1906 | 258 | 45273 | 6766 | 86.46 | 85.06 | 100.0 | 90.51 | heartbeats (5.0) | L104 8678hb (19.1%) | N |
| interleaved_affine_gaps_imply_tensor_gaps | 1353 | 225 | 9198 | 2571 | 83.37 | 72.05 | 100.0 | 85.14 | heartbeats (9.3) | L143-167 1049hb (11.3%) | N |
| FieldSpecification.WickAlgebra..uteF_eq_time | 1217 | 590 | 42225 | 10463 | 51.52 | 75.22 | 100.0 | 75.58 | tokens (16.2) | L110 5845hb (13.9%) | N |

Rows needing one profile compile of the best proof: 15 of 15.


## Core.InitsUpdatesComm

Reference: 224 tokens, 4251 hb (official denominators); measured on v4.29.1; profile Core.InitsUpdatesComm-384e22374e08-d27c68789f2e.json (current), measured total 4251, profiled 4183, floor 36. Rates: 0.149 pts/token, 0.784 pts/100 hb, 11.11 pts/lost version (3 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 10 | 3 | 0 | 0 | 0.0 | 0.45 | 0.0 | intros Hup Hinit |
| 2 | 11 | 7 | 593 | 593 | 13.9 | 1.04 | 4.65 | exists (updatedStates σ ks' vs') |
| 3 | 12 | 11 | 7 | 7 | 0.2 | 1.64 | 0.05 | have Hk : (isDefined σ' ks) := UpdateStatesDefin |
| 4 | 13 | 5 | 3 | 3 | 0.1 | 0.74 | 0.02 | have Hlen1 := InitStatesLength Hinit |
| 5 | 14 | 5 | 3 | 3 | 0.1 | 0.74 | 0.02 | have Hlen2 := UpdateStatesLength Hup |
| 6 | 15 | 4 | 11 | 11 | 0.3 | 0.6 | 0.09 | induction Hup generalizing σ'' |
| 7 | 16-23 | 22 | 66 | 3 | 0.1 | 3.28 | 0.02 | case update_none => |
| 8 | 17 | 1 | 46 | 46 | 1.1 | 0.15 | 0.36 | . simp_all |
| 9 | 24-55 | 31 | 3500 | 3 | 0.1 | 4.62 | 0.02 | case update_some σ x v σ₀ xs vs σ₁ Hup Hups ih = |
| 10 | 25 | 8 | 33 | 33 | 0.8 | 1.19 | 0.26 | . refine ⟨rfl, ?_, ?_⟩ |
| 11 | 31-55 | 11 | 3448 | 2 | 0.0 | 1.64 | 0.02 | . . apply UpdateStates.update_some (σ':=updatedSta |
| 12 | 32-52 | 8 | 2679 | 1 | 0.0 | 1.19 | 0.01 | . . . simp [UpdateStateUpdated Hup, updatedStates] |
| 13 | 33 | 5 | 46 | 46 | 1.1 | 0.74 | 0.36 | . . . rw [← updatedStateComm'] |
| 14 | 34-45 | 6 | 1205 | 2 | 0.0 | 0.89 | 0.02 | . . . . have Hdef := UpdateStateDefined' Hup |
| 15 | 35 | 8 | 72 | 72 | 1.7 | 1.19 | 0.56 | . . . . simp [isDefined, Option.isSome] at Hdef |
| 16 | 36 | 5 | 1036 | 1036 | 24.4 | 0.74 | 8.12 | . . . . split at Hdef <;> simp_all |
| 17 | 37-45 | 34 | 91 | 91 | 2.1 | 5.07 | 0.71 | . . . . next val heq => |
| 18 | 46-52 | 13 | 1416 | 3 | 0.1 | 1.94 | 0.02 | . . . . rw [List.unzip_zip] <;> simp_all |
| 19 | 46 | 7 | 1031 | 1031 | 24.3 | 1.04 | 8.08 | . . . . . rw [List.unzip_zip] <;> simp_all |
| 20 | 48 | 8 | 224 | 224 | 5.3 | 1.19 | 1.76 | . . . . simp [isNotDefined, isDefined] at * |
| 21 | 52 | 1 | 150 | 150 | 3.5 | 0.15 | 1.18 | . . . . simp_all |
| 22 | 53-55 | 9 | 762 | 1 | 0.0 | 1.34 | 0.01 | . . . apply (ih Hinit ?_ ?_).2.2 |
| 23 | 54 | 0 | 481 | 1 | 0.0 | 0.0 | 0.01 | . . . . simp [isDefined] at * <;> simp_all |
| 24 | 54 | 9 | 480 | 480 | 11.3 | 1.34 | 3.76 | . . . . . simp [isDefined] at * <;> simp_all |
| 25 | 55 | 0 | 277 | 0 | 0.0 | 0.0 | 0.0 | . . . . simp_all |
| 26 | 55 | 2 | 277 | 277 | 6.5 | 0.3 | 2.17 | . . . . . simp_all |

(tokens on lines outside any tactic span: 1; total 224 vs ref 224)

Top-3 hb: #16 L36 1036 (24.4%); #19 L46 1031 (24.3%); #2 L11 593 (13.9%)

Top-3 tokens: #17 L37-45 34; #9 L24-55 31; #7 L16-23 22

Best submitted (v3): 76 tokens; hb 203 on v4.29.1, tok% 66.07, hb% 95.22, cov% 100.0, proxy 87.1 (cand core_hybrid); needs one profile compile.

## fundamental_theorem_of_variational_calculus'

Reference: 851 tokens, 11947 hb (official denominators); measured on v4.32.0; profile fundamental_theorem_of_variational_calculus_-c48433678e8f-f4d01d667f94.json (current), measured total 11946, profiled 11044, floor 543. Rates: 0.039 pts/token, 0.279 pts/100 hb, 33.33 pts/lost version (1 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 7 | 0 | 7 | 7 | 0.1 | 0.0 | 0.02 | rw [funext_iff]; by_contra h₀ |
| 2 | 7 | 7 | 35 | 35 | 0.3 | 0.27 | 0.1 | rw [funext_iff]; by_contra h₀ |
| 3 | 8 | 9 | 7 | 7 | 0.1 | 0.35 | 0.02 | obtain ⟨x₀, hx0⟩ := not_forall.1 h₀ |
| 4 | 9 | 3 | 15 | 15 | 0.1 | 0.12 | 0.04 | simp at hx0 -- hx0 : f x₀ ≠ 0 |
| 5 | 13 | 13 | 112 | 112 | 0.9 | 0.51 | 0.31 | let f₂ : Y → WithLp 2 V := toL2 ℝ ∘ f |
| 6 | 14 | 5 | 2 | 2 | 0.0 | 0.2 | 0.01 | let x₂ := f₂ x₀ |
| 7 | 16-17 | 8 | 291 | 113 | 0.9 | 0.31 | 0.32 | have hx2 : x₂ ≠ 0 := by |
| 8 | 17 | 13 | 178 | 178 | 1.5 | 0.51 | 0.5 | . intro h; apply hx0; exact congrArg (fromL2 ℝ) h |
| 9 | 19 | 16 | 443 | 443 | 3.7 | 0.62 | 1.24 | have hcont₂ : ContinuousAt f₂ x₀ := ((toL2 ℝ).co |
| 10 | 24-26 | 18 | 588 | 181 | 1.5 | 0.7 | 0.5 | obtain ⟨δ₂, hδ₂_pos, hδ₂⟩ := |
| 11 | 26 | 12 | 407 | 407 | 3.4 | 0.47 | 1.14 | . (by simpa [half_pos] using (norm_pos_iff.mpr hx2 |
| 12 | 28-43 | 33 | 4878 | 53 | 0.4 | 1.29 | 0.15 | have inner_pos₂ : ∀ x (hx : x ∈ Metric.ball x₀ δ |
| 13 | 32-34 | 17 | 400 | 175 | 1.5 | 0.66 | 0.49 | . have hclose : ‖f₂ x - x₂‖ < ‖x₂‖ / 2 := by |
| 14 | 33 | 5 | 72 | 72 | 0.6 | 0.2 | 0.2 | . . convert hδ₂ hx using 1 |
| 15 | 34 | 3 | 153 | 153 | 1.3 | 0.12 | 0.43 | . . exact mem_sphere_iff_norm.mp rfl |
| 16 | 35 | 24 | 97 | 97 | 0.8 | 0.94 | 0.27 | . have hself : ⟪x₂, x₂⟫_ℝ = ‖x₂‖^2 := real_inner_s |
| 17 | 37-38 | 33 | 256 | 256 | 2.1 | 1.29 | 0.71 | . have hcs : -(‖f₂ x - x₂‖ * ‖x₂‖) ≤ ⟪f₂ x - x₂, x |
| 18 | 39 | 11 | 62 | 62 | 0.5 | 0.43 | 0.17 | . have hxp : 0 < ‖x₂‖ := norm_pos_iff.mpr hx2 |
| 19 | 40-41 | 29 | 137 | 23 | 0.2 | 1.13 | 0.06 | . have inner_eq_self_add_diff : ⟪f₂ x, x₂⟫_ℝ = ⟪x₂ |
| 20 | 41 | 7 | 77 | 77 | 0.6 | 0.27 | 0.21 | . . rw [← inner_add_left]; simp |
| 21 | 42-43 | 16 | 3873 | 3873 | 32.4 | 0.62 | 10.81 | . nlinarith [inner_eq_self_add_diff, hcs, hself, h |
| 22 | 45 | 28 | 94 | 94 | 0.8 | 1.09 | 0.26 | have inner_pos_V : ∀ x ∈ Metric.ball x₀ δ₂, 0 <  |
| 23 | 49-62 | 74 | 1594 | 156 | 1.3 | 2.89 | 0.44 | have bump_exists : ∃ φ : Y → ℝ, IsTestFunction φ |
| 24 | 55-56 | 6 | 666 | 82 | 0.7 | 0.23 | 0.23 | . let φ1 : ContDiffBump x₀ := |
| 25 | 56 | 0 | 312 | 312 | 2.6 | 0.0 | 0.87 | . . ⟨δ₂ / 4, δ₂ / 2, by positivity, by linarith⟩ |
| 26 | 56 | 15 | 272 | 272 | 2.3 | 0.58 | 0.76 | . . ⟨δ₂ / 4, δ₂ / 2, by positivity, by linarith⟩ |
| 27 | 57-59 | 35 | 237 | 191 | 1.6 | 1.36 | 0.53 | . refine ⟨φ1.toFun, ⟨φ1.contDiff, φ1.hasCompactSup |
| 28 | 62 | 0 | 496 | 43 | 0.4 | 0.0 | 0.12 | . exact Metric.mem_ball.mpr (lt_of_le_of_lt hx (by |
| 29 | 62 | 19 | 419 | 419 | 3.5 | 0.74 | 1.17 | . . exact Metric.mem_ball.mpr (lt_of_le_of_lt hx (by |
| 30 | 63-64 | 16 | 21 | 21 | 0.2 | 0.62 | 0.06 | obtain ⟨φ, hφ_testfun, hφ_pos_x₀, hφ_non_neg, hφ |
| 31 | 66 | 15 | 303 | 303 | 2.5 | 0.58 | 0.85 | let g : Y → V := fun x => φ x • f x₀ |
| 32 | 68 | 9 | 57 | 57 | 0.5 | 0.35 | 0.16 | have hg_test : IsTestFunction g := IsTestFunctio |
| 33 | 72 | 6 | 2 | 2 | 0.0 | 0.23 | 0.01 | have key_integral := hg g hg_test |
| 34 | 74 | 9 | 34 | 34 | 0.3 | 0.35 | 0.09 | simp only [g, inner_smul_right'] at key_integral |
| 35 | 81-82 | 10 | 374 | 93 | 0.8 | 0.39 | 0.26 | have support_subset : Function.support φ ⊆ Metri |
| 36 | 82 | 8 | 281 | 281 | 2.4 | 0.31 | 0.78 | . hφ_support_subset.trans (Metric.ball_subset_ball |
| 37 | 83-86 | 29 | 154 | 33 | 0.3 | 1.13 | 0.09 | have supp_subset2 : Function.support (fun x => φ |
| 38 | 86 | 6 | 120 | 120 | 1.0 | 0.23 | 0.33 | . simp [hφ0] at hprod |
| 39 | 87-88 | 35 | 87 | 87 | 0.7 | 1.36 | 0.24 | have hinner_cont : Continuous (fun x => ⟪f x, f  |
| 40 | 89-93 | 32 | 191 | 191 | 1.6 | 1.25 | 0.53 | have integrable_prod : |
| 41 | 96-102 | 53 | 110 | 17 | 0.1 | 2.07 | 0.05 | have h_nonneg : ∀ x, 0 ≤ φ x * ⟪f x, f x₀⟫_ℝ :=  |
| 42 | 106-107 | 16 | 438 | 143 | 1.2 | 0.62 | 0.4 | have hμ_ball : 0 < μ (Metric.ball x₀ (δ₂/4)) := |
| 43 | 107 | 9 | 295 | 295 | 2.5 | 0.35 | 0.82 | . Metric.isOpen_ball.measure_pos μ (Metric.nonempt |
| 44 | 108-109 | 22 | 89 | 89 | 0.7 | 0.86 | 0.25 | have hμ : 0 < μ (Metric.closedBall x₀ (δ₂/4)) := |
| 45 | 110-120 | 40 | 787 | 41 | 0.3 | 1.56 | 0.11 | have closedBall_subset_support : |
| 46 | 115-116 | 14 | 395 | 55 | 0.5 | 0.55 | 0.15 | . have hin : 0 < ⟪f x, f x₀⟫_ℝ := |
| 47 | 116 | 10 | 340 | 340 | 2.8 | 0.39 | 0.95 | . . inner_pos_V x (Metric.closedBall_subset_ball (by |
| 48 | 117 | 11 | 82 | 82 | 0.7 | 0.43 | 0.23 | . simp only [Function.support_mul, Set.mem_inter_i |
| 49 | 119 | 0 | 180 | 0 | 0.0 | 0.0 | 0.0 | . · linarith |
| 50 | 119 | 2 | 180 | 180 | 1.5 | 0.08 | 0.5 | . . · linarith |
| 51 | 120 | 0 | 86 | 1 | 0.0 | 0.0 | 0.0 | . · linarith |
| 52 | 120 | 2 | 85 | 85 | 0.7 | 0.08 | 0.24 | . . · linarith |
| 53 | 123-125 | 36 | 148 | 148 | 1.2 | 1.4 | 0.41 | have integral_pos : 0 < ∫ x, φ x * ⟪f x, f x₀⟫_ℝ |
| 54 | 126 | 1 | 183 | 183 | 1.5 | 0.04 | 0.51 | linarith |

(tokens on lines outside any tactic span: 1; total 851 vs ref 851)

Top-3 hb: #21 L42-43 3873 (32.4%); #9 L19 443 (3.7%); #29 L62 419 (3.5%)

Top-3 tokens: #23 L49-62 74; #41 L96-102 53; #45 L110-120 40

Best submitted (v3): 145 tokens; hb 1575 on v4.32.0, tok% 82.96, hb% 86.82, cov% 100.0, proxy 89.93 (cand phys_hybrid); needs one profile compile.

## Cslib.CCS.bisimilarity_congr_choice

Reference: 251 tokens, 3858 hb (official denominators); measured on v4.33.0-rc2; profile Cslib.CCS.bisimilarity_congr_choice-3aa9d4416c18-24886bff410d.json (current), measured total 3858, profiled 3740, floor 40. Rates: 0.133 pts/token, 0.864 pts/100 hb, 11.11 pts/lost version (3 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 3 | 2 | 0 | 0 | 0.0 | 0.27 | 0.0 | intro h |
| 2 | 4 | 6 | 43 | 43 | 1.1 | 0.8 | 0.37 | exists @ChoiceBisim _ _ defs |
| 3 | 5 | 1 | 0 | 0 | 0.0 | 0.13 | 0.0 | constructor |
| 4 | 6 | 4 | 2 | 1 | 0.0 | 0.53 | 0.01 | · constructor; assumption |
| 5 | 7 | 5 | 1 | 1 | 0.0 | 0.67 | 0.01 | intro s1 s2 r μ |
| 6 | 8 | 1 | 1 | 1 | 0.0 | 0.13 | 0.01 | constructor |
| 7 | 9-35 | 6 | 1844 | 3 | 0.1 | 0.8 | 0.03 | case left => |
| 8 | 11 | 2 | 21 | 21 | 0.5 | 0.27 | 0.18 | . cases r |
| 9 | 12-27 | 17 | 995 | 3 | 0.1 | 2.26 | 0.03 | . case choice p q r hbisim => |
| 10 | 14 | 2 | 52 | 52 | 1.3 | 0.27 | 0.45 | . . cases htr |
| 11 | 15-21 | 31 | 614 | 3 | 0.1 | 4.12 | 0.03 | . . case choiceL a b c htr => |
| 12 | 17 | 2 | 587 | 587 | 15.2 | 0.27 | 5.07 | . . . exists s2' |
| 13 | 22-27 | 16 | 320 | 3 | 0.1 | 2.13 | 0.03 | . . case choiceR a b c htr => |
| 14 | 23 | 2 | 309 | 309 | 8.0 | 0.27 | 2.67 | . . . exists s1' |
| 15 | 28-35 | 35 | 825 | 4 | 0.1 | 4.66 | 0.03 | . case bisim hbisim => |
| 16 | 31 | 2 | 796 | 796 | 20.6 | 0.27 | 6.88 | . . exists s2' |
| 17 | 36-62 | 6 | 1849 | 2 | 0.1 | 0.8 | 0.02 | case right => |
| 18 | 38 | 2 | 22 | 22 | 0.6 | 0.27 | 0.19 | . cases r |
| 19 | 39-54 | 17 | 998 | 3 | 0.1 | 2.26 | 0.03 | . case choice p q r hbisim => |
| 20 | 41 | 2 | 52 | 52 | 1.3 | 0.27 | 0.45 | . . cases htr |
| 21 | 42-48 | 31 | 616 | 3 | 0.1 | 4.12 | 0.03 | . . case choiceL a b c htr => |
| 22 | 44 | 2 | 588 | 588 | 15.2 | 0.27 | 5.08 | . . . exists s1' |
| 23 | 49-54 | 16 | 321 | 4 | 0.1 | 2.13 | 0.03 | . . case choiceR a b c htr => |
| 24 | 50 | 2 | 309 | 309 | 8.0 | 0.27 | 2.67 | . . . exists s2' |
| 25 | 55-62 | 36 | 827 | 4 | 0.1 | 4.79 | 0.03 | . case bisim hbisim => |
| 26 | 58 | 2 | 797 | 797 | 20.7 | 0.27 | 6.89 | . . exists s1' |

(tokens on lines outside any tactic span: 1; total 251 vs ref 251)

Top-3 hb: #26 L58 797 (20.7%); #16 L31 796 (20.6%); #22 L44 588 (15.2%)

Top-3 tokens: #25 L55-62 36; #15 L28-35 35; #11 L15-21 31

Best submitted (v3): 83 tokens; hb 256 on v4.33.0-rc2, tok% 66.93, hb% 93.36, cov% 100.0, proxy 86.76 (cand cslib_hybrid); needs one profile compile.

## CallElimCorrect.extractedOldExprInVars

Reference: 222 tokens, 2696 hb (official denominators); measured on v4.26.0; profile CallElimCorrect.extractedOldExprInVars-451e5f047baf-ef08679f998c.json (current), measured total 2698, profiled 2497, floor 17. Rates: 0.15 pts/token, 1.236 pts/100 hb, 33.33 pts/lost version (1 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 2 | 0 | 0 | 0.0 | 0.3 | 0.0 | intros Hnorm |
| 2 | 7-10 | 16 | 1108 | 1108 | 41.1 | 2.4 | 13.69 | induction post <;> |
| 3 | 11-38 | 7 | 648 | 3 | 0.1 | 1.05 | 0.04 | case app fn e fn_ih e_ih => |
| 4 | 12 | 2 | 15 | 15 | 0.6 | 0.3 | 0.19 | . unfold extractOldExprVars |
| 5 | 13 | 1 | 60 | 60 | 2.2 | 0.15 | 0.74 | . split |
| 6 | 14-16 | 5 | 28 | 1 | 0.0 | 0.75 | 0.01 | . . simp [Lambda.LExpr.LExpr.getVars] |
| 7 | 14 | 5 | 24 | 24 | 0.9 | 0.75 | 0.3 | . . . simp [Lambda.LExpr.LExpr.getVars] |
| 8 | 17-25 | 0 | 47 | 1 | 0.0 | 0.0 | 0.01 | . . next Hfalse => |
| 9 | 17-25 | 4 | 46 | 0 | 0.0 | 0.6 | 0.0 | . . . next Hfalse => |
| 10 | 18-25 | 19 | 46 | 29 | 1.1 | 2.85 | 0.36 | . . . cases Hnorm with |
| 11 | 26-38 | 0 | 495 | 0 | 0.0 | 0.0 | 0.0 | . . cases Hnorm with |
| 12 | 26-38 | 12 | 495 | 27 | 1.0 | 1.8 | 0.33 | . . . cases Hnorm with |
| 13 | 29-33 | 10 | 232 | 2 | 0.1 | 1.5 | 0.02 | . . . . apply List.Subset.trans |
| 14 | 33 | 1 | 225 | 225 | 8.3 | 0.15 | 2.78 | . . . . simp_all |
| 15 | 34-38 | 10 | 232 | 2 | 0.1 | 1.5 | 0.02 | . . . . apply List.Subset.trans |
| 16 | 38 | 1 | 225 | 225 | 8.3 | 0.15 | 2.78 | . . . . simp_all |
| 17 | 39-41 | 8 | 23 | 1 | 0.0 | 1.2 | 0.01 | case abs ih => |
| 18 | 40 | 2 | 21 | 21 | 0.8 | 0.3 | 0.26 | . cases Hnorm |
| 19 | 42-55 | 16 | 175 | 3 | 0.1 | 2.4 | 0.04 | case quant trih eih => |
| 20 | 43 | 2 | 26 | 26 | 1.0 | 0.3 | 0.32 | . cases Hnorm |
| 21 | 48-51 | 10 | 72 | 2 | 0.1 | 1.5 | 0.02 | . . apply List.Subset.trans |
| 22 | 51 | 1 | 64 | 64 | 2.4 | 0.15 | 0.79 | . . simp_all |
| 23 | 52-55 | 10 | 71 | 1 | 0.0 | 1.5 | 0.01 | . . apply List.Subset.trans |
| 24 | 55 | 1 | 64 | 64 | 2.4 | 0.15 | 0.79 | . . simp_all |
| 25 | 56-71 | 10 | 372 | 2 | 0.1 | 1.5 | 0.02 | case ite cih tih eih => |
| 26 | 57 | 2 | 26 | 26 | 1.0 | 0.3 | 0.32 | . cases Hnorm |
| 27 | 59-62 | 10 | 113 | 2 | 0.1 | 1.5 | 0.02 | . . apply List.Subset.trans |
| 28 | 62 | 1 | 105 | 105 | 3.9 | 0.15 | 1.3 | . . simp_all |
| 29 | 64-67 | 10 | 112 | 2 | 0.1 | 1.5 | 0.02 | . . apply List.Subset.trans |
| 30 | 67 | 1 | 104 | 104 | 3.9 | 0.15 | 1.29 | . . simp_all |
| 31 | 68-71 | 10 | 111 | 2 | 0.1 | 1.5 | 0.02 | . . apply List.Subset.trans |
| 32 | 71 | 1 | 103 | 103 | 3.8 | 0.15 | 1.27 | . . simp_all |
| 33 | 72-82 | 7 | 171 | 3 | 0.1 | 1.05 | 0.04 | case eq ih1 ih2 => |
| 34 | 73 | 2 | 22 | 22 | 0.8 | 0.3 | 0.27 | . cases Hnorm |
| 35 | 75-78 | 10 | 71 | 1 | 0.0 | 1.5 | 0.01 | . . apply List.Subset.trans |
| 36 | 78 | 1 | 64 | 64 | 2.4 | 0.15 | 0.79 | . . simp_all |
| 37 | 79-82 | 10 | 71 | 2 | 0.1 | 1.5 | 0.02 | . . apply List.Subset.trans |
| 38 | 82 | 1 | 63 | 63 | 2.3 | 0.15 | 0.78 | . . simp_all |

(tokens on lines outside any tactic span: 1; total 222 vs ref 222)

Top-3 hb: #2 L7-10 1108 (41.1%); #14 L33 225 (8.3%); #16 L38 225 (8.3%)

Top-3 tokens: #10 L18-25 19; #2 L7-10 16; #19 L42-55 16

Best submitted (v3): 77 tokens; hb 487 on v4.26.0, tok% 65.32, hb% 81.94, cov% 100.0, proxy 82.42 (cand extract_hybrid); needs one profile compile.

## CallElimCorrect.substOldPostSubset

Reference: 313 tokens, 5175 hb (official denominators); measured on v4.26.0; profile CallElimCorrect.substOldPostSubset-451e5f047baf-5447253c7ae6.json (current), measured total 5175, profiled 4887, floor 68. Rates: 0.106 pts/token, 0.644 pts/100 hb, 33.33 pts/lost version (1 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 7 | 1235 | 1235 | 23.9 | 0.74 | 7.95 | induction post <;> simp [substOld] |
| 2 | 7-14 | 19 | 44 | 3 | 0.1 | 2.01 | 0.02 | case fvar => |
| 3 | 14 | 1 | 39 | 39 | 0.8 | 0.11 | 0.25 | . simp_all |
| 4 | 15-21 | 19 | 44 | 3 | 0.1 | 2.01 | 0.02 | case op => |
| 5 | 21 | 1 | 39 | 39 | 0.8 | 0.11 | 0.25 | . simp_all |
| 6 | 22-26 | 12 | 41 | 3 | 0.1 | 1.27 | 0.02 | case const => |
| 7 | 26 | 1 | 38 | 38 | 0.7 | 0.11 | 0.24 | . simp_all |
| 8 | 27-31 | 12 | 41 | 3 | 0.1 | 1.27 | 0.02 | case bvar => |
| 9 | 31 | 1 | 38 | 38 | 0.7 | 0.11 | 0.24 | . simp_all |
| 10 | 32-33 | 4 | 33 | 1 | 0.0 | 0.42 | 0.01 | case abs ih => |
| 11 | 33 | 2 | 32 | 32 | 0.6 | 0.21 | 0.21 | . exact ih |
| 12 | 34-51 | 10 | 937 | 4 | 0.1 | 1.06 | 0.03 | case ite cih tih eih => |
| 13 | 35 | 8 | 133 | 133 | 2.6 | 0.85 | 0.86 | . simp [Imperative.HasVarsPure.getVars, Lambda.LEx |
| 14 | 37-41 | 10 | 334 | 2 | 0.0 | 1.06 | 0.01 | . . apply List.Subset.trans |
| 15 | 40 | 1 | 197 | 197 | 3.8 | 0.11 | 1.27 | . . simp_all |
| 16 | 41 | 4 | 130 | 130 | 2.5 | 0.42 | 0.84 | . . cases Hin <;> simp_all |
| 17 | 43-47 | 10 | 333 | 3 | 0.1 | 1.06 | 0.02 | . . apply List.Subset.trans |
| 18 | 46 | 1 | 197 | 197 | 3.8 | 0.11 | 1.27 | . . simp_all |
| 19 | 47 | 4 | 128 | 128 | 2.5 | 0.42 | 0.82 | . . cases Hin <;> simp_all |
| 20 | 48-51 | 10 | 125 | 2 | 0.0 | 1.06 | 0.01 | . . apply List.Subset.trans |
| 21 | 51 | 1 | 118 | 118 | 2.3 | 0.11 | 0.76 | . . simp_all |
| 22 | 52-71 | 5 | 1596 | 2 | 0.0 | 0.53 | 0.01 | case app ih1 ih2 => |
| 23 | 53 | 1 | 49 | 49 | 0.9 | 0.11 | 0.32 | . split |
| 24 | 54-60 | 0 | 368 | 2 | 0.0 | 0.0 | 0.01 | . . split |
| 25 | 54 | 2 | 50 | 50 | 1.0 | 0.21 | 0.32 | . . . split |
| 26 | 55-57 | 3 | 159 | 1 | 0.0 | 0.32 | 0.01 | . . . simp [Imperative.HasVarsPure.getVars, Lambda.L |
| 27 | 55 | 9 | 88 | 88 | 1.7 | 0.95 | 0.57 | . . . . simp [Imperative.HasVarsPure.getVars, Lambda.L |
| 28 | 57 | 1 | 70 | 70 | 1.4 | 0.11 | 0.45 | . . . simp_all |
| 29 | 58-60 | 3 | 157 | 1 | 0.0 | 0.32 | 0.01 | . . . simp [Imperative.HasVarsPure.getVars, Lambda.L |
| 30 | 58 | 9 | 89 | 89 | 1.7 | 0.95 | 0.57 | . . . . simp [Imperative.HasVarsPure.getVars, Lambda.L |
| 31 | 60 | 1 | 67 | 67 | 1.3 | 0.11 | 0.43 | . . . simp_all |
| 32 | 61-71 | 2 | 1177 | 3 | 0.1 | 0.21 | 0.02 | . . simp [Imperative.HasVarsPure.getVars, Lambda.L |
| 33 | 61 | 9 | 445 | 445 | 8.6 | 0.95 | 2.87 | . . . simp [Imperative.HasVarsPure.getVars, Lambda.L |
| 34 | 63-67 | 10 | 548 | 2 | 0.0 | 1.06 | 0.01 | . . . apply List.Subset.trans |
| 35 | 66 | 1 | 298 | 298 | 5.8 | 0.11 | 1.92 | . . . simp_all |
| 36 | 67 | 4 | 243 | 243 | 4.7 | 0.42 | 1.56 | . . . cases Hin <;> simp_all |
| 37 | 68-71 | 10 | 177 | 2 | 0.0 | 1.06 | 0.01 | . . . apply List.Subset.trans |
| 38 | 71 | 1 | 170 | 170 | 3.3 | 0.11 | 1.09 | . . . simp_all |
| 39 | 72-85 | 7 | 489 | 3 | 0.1 | 0.74 | 0.02 | case quant trih eih => |
| 40 | 73 | 8 | 81 | 81 | 1.6 | 0.85 | 0.52 | . simp [Imperative.HasVarsPure.getVars, Lambda.LEx |
| 41 | 75-81 | 31 | 302 | 3 | 0.1 | 3.29 | 0.02 | . . apply List.Subset.trans |
| 42 | 80 | 1 | 191 | 191 | 3.7 | 0.11 | 1.23 | . . simp_all |
| 43 | 81 | 4 | 90 | 90 | 1.7 | 0.42 | 0.58 | . . cases Hin <;> simp_all |
| 44 | 82-85 | 10 | 99 | 2 | 0.0 | 1.06 | 0.01 | . . apply List.Subset.trans |
| 45 | 85 | 1 | 92 | 92 | 1.8 | 0.11 | 0.59 | . . simp_all |
| 46 | 86-97 | 7 | 427 | 3 | 0.1 | 0.74 | 0.02 | case eq ih1 ih2 => |
| 47 | 87 | 8 | 81 | 81 | 1.6 | 0.85 | 0.52 | . simp [Imperative.HasVarsPure.getVars, Lambda.LEx |
| 48 | 89-93 | 10 | 240 | 2 | 0.0 | 1.06 | 0.01 | . . apply List.Subset.trans |
| 49 | 92 | 1 | 144 | 144 | 2.8 | 0.11 | 0.93 | . . simp_all |
| 50 | 93 | 4 | 89 | 89 | 1.7 | 0.42 | 0.57 | . . cases Hin <;> simp_all |
| 51 | 94-97 | 10 | 99 | 2 | 0.0 | 1.06 | 0.01 | . . apply List.Subset.trans |
| 52 | 97 | 1 | 92 | 92 | 1.8 | 0.11 | 0.59 | . . simp_all |

(tokens on lines outside any tactic span: 1; total 313 vs ref 313)

Top-3 hb: #1 L6 1235 (23.9%); #33 L61 445 (8.6%); #35 L66 298 (5.8%)

Top-3 tokens: #41 L75-81 31; #2 L7-14 19; #4 L15-21 19

Best submitted (v3): 26 tokens; hb 2230 on v4.26.0, tok% 91.69, hb% 56.91, cov% 100.0, proxy 82.87 (cand subst_hybrid); needs one profile compile.

## putnam_1964_a4

Reference: 1769 tokens, 111476 hb (official denominators); measured on v4.25.0; profile putnam_1964_a4-1ccd71f89cbb-525ed6d96533.json (current), measured total None, profiled 139969, floor 792. Rates: 0.019 pts/token, 0.03 pts/100 hb, 11.11 pts/lost version (3 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 6-61 | 78 | 73428 | 109 | 0.1 | 1.48 | 0.03 | have h_main : ∃ (i j : ℕ), i < j ∧ (u i = u j ∧  |
| 2 | 8-60 | 66 | 73307 | 99 | 0.1 | 1.25 | 0.03 | . have h₁ : ∃ (i j : ℕ), i < j ∧ (u i = u j ∧ u (i |
| 3 | 10-60 | 66 | 73208 | 9 | 0.0 | 1.25 | 0.0 | . . classical |
| 4 | 13-35 | 14 | 55882 | 7 | 0.0 | 0.27 | 0.0 | . . . have h₂ : Set.Finite (Set.range f) := by |
| 5 | 14-27 | 112 | 47614 | 47614 | 34.0 | 2.13 | 14.28 | . . . . have h₃ : Set.range f ⊆ Set.Icc (B, B, B, B) (T, |
| 6 | 29-34 | 65 | 8253 | 8253 | 5.9 | 1.23 | 2.48 | . . . . have h₄ : Set.Finite (Set.Icc (B, B, B, B) (T, T |
| 7 | 37-52 | 40 | 12000 | 17 | 0.0 | 0.76 | 0.01 | . . . have h₃ : ∃ (i j : ℕ), i < j ∧ f i = f j := by |
| 8 | 39-50 | 61 | 11773 | 11773 | 8.4 | 1.16 | 3.53 | . . . . have h₅ : Function.Injective f := by |
| 9 | 56-60 | 17 | 5221 | 163 | 0.1 | 0.32 | 0.05 | . . . simp [f] at h₅ ⊢ |
| 10 | 58 | 8 | 5058 | 5058 | 3.6 | 0.15 | 1.52 | . . . . (try simp_all [Prod.ext_iff]) <;> |
| 11 | 63-184 | 43 | 66540 | 40 | 0.0 | 0.82 | 0.01 | have h_periodic : ∃ N c : ℕ, c > 0 ∧ ∀ n ≥ N, u  |
| 12 | 65-163 | 28 | 53607 | 26 | 0.0 | 0.53 | 0.01 | . have h₁ : ∀ m : ℕ, u (i + m) = u (j + m) := by |
| 13 | 67-162 | 25 | 53580 | 25 | 0.0 | 0.47 | 0.01 | . . have h₂ : ∀ m : ℕ, u (i + m) = u (j + m) := by |
| 14 | 69-162 | 10 | 53555 | 3 | 0.0 | 0.19 | 0.0 | . . . induction m using Nat.strong_induction_on with |
| 15 | 71-162 | 964 | 53552 | 53552 | 38.3 | 18.32 | 16.07 | . . . . match m with |
| 16 | 164-183 | 52 | 12877 | 37 | 0.0 | 0.99 | 0.01 | . have h₂ : ∃ N c : ℕ, c > 0 ∧ ∀ n ≥ N, u (n + c)  |
| 17 | 170-183 | 6 | 12475 | 2 | 0.0 | 0.11 | 0.0 | . . · intro n hn |
| 18 | 171-182 | 45 | 12472 | 35 | 0.0 | 0.85 | 0.01 | . . . have h₄ : u (n + (j - i)) = u n := by |
| 19 | 172-175 | 44 | 1253 | 1253 | 0.9 | 0.84 | 0.38 | . . . . have h₅ : u (i + (n - i)) = u (j + (n - i)) := b |
| 20 | 178-179 | 21 | 740 | 740 | 0.5 | 0.4 | 0.22 | . . . . have h₇ : j + (n - i) = n + (j - i) := by |
| 21 | 182 | 1 | 10053 | 10053 | 7.2 | 0.02 | 3.02 | . . . . linarith |
| 22 | 186 | 2 | 1 | 1 | 0.0 | 0.04 | 0.0 | exact h_periodic |

(tokens on lines outside any tactic span: 1; total 1769 vs ref 1769)

Top-3 hb: #15 L71-162 53552 (38.3%); #5 L14-27 47614 (34.0%); #8 L39-50 11773 (8.4%)

Top-3 tokens: #15 L71-162 964; #5 L14-27 112; #1 L6-61 78

Best submitted (v3): 312 tokens; hb 6515 on v4.25.0, tok% 82.36, hb% 94.16, cov% 100.0, proxy 92.17 (cand a4_ds); needs one profile compile.

## putnam_1964_b2

Reference: 1754 tokens, 134499 hb (official denominators); measured on v4.25.0; profile putnam_1964_b2-1ccd71f89cbb-c2c6501953bf.json (current), measured total 120486, profiled 119967, floor 156. Rates: 0.019 pts/token, 0.025 pts/100 hb, 16.67 pts/lost version (2 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 7-12 | 58 | 87 | 21 | 0.0 | 1.1 | 0.01 | have h_no_empty : ∀ (T : Set S), T ∈ P → T.Nonem |
| 2 | 14-126 | 75 | 61093 | 34 | 0.0 | 1.43 | 0.01 | have h_subset_or_compl : ∀ (A : Set S), A ∈ P ∨  |
| 3 | 20-55 | 28 | 20597 | 31 | 0.0 | 0.53 | 0.01 | . have h₃ : ∃ (U : Set S), U ∈ P ∧ A ∩ U = ∅ := by |
| 4 | 21-40 | 34 | 9466 | 35 | 0.0 | 0.65 | 0.01 | . . have h₄ : ¬(A ∉ P ∧ ∀ (U : Set S), U ∈ P → A ∩ U |
| 5 | 23-39 | 39 | 9429 | 40 | 0.0 | 0.74 | 0.01 | . . . have h₆ : ∃ (T : Set S), T ∉ P ∧ (∀ U ∈ P, T ∩ U |
| 6 | 27-39 | 66 | 9381 | 9381 | 7.8 | 1.25 | 2.35 | . . . . · intro U hU |
| 7 | 42-53 | 58 | 7468 | 3 | 0.0 | 1.1 | 0.0 | . . · have h₆ : ¬(∀ (U : Set S), U ∈ P → A ∩ U ≠ ∅)  |
| 8 | 48-52 | 22 | 7385 | 18 | 0.0 | 0.42 | 0.0 | . . . have h₉ : A ∩ U = ∅ := by |
| 9 | 51-52 | 6 | 7281 | 7281 | 6.0 | 0.11 | 1.82 | . . . . simp_all [Set.ext_iff] |
| 10 | 54-55 | 2 | 3555 | 2 | 0.0 | 0.04 | 0.0 | . . · exfalso |
| 11 | 55 | 1 | 3551 | 3551 | 2.9 | 0.02 | 0.89 | . . . simp_all |
| 12 | 57-92 | 28 | 22628 | 39 | 0.0 | 0.53 | 0.01 | . have h₄ : ∃ (V : Set S), V ∈ P ∧ Aᶜ ∩ V = ∅ := b |
| 13 | 58-77 | 34 | 10620 | 42 | 0.0 | 0.65 | 0.01 | . . have h₅ : ¬(Aᶜ ∉ P ∧ ∀ (U : Set S), U ∈ P → Aᶜ ∩ |
| 14 | 60-76 | 39 | 10576 | 41 | 0.0 | 0.74 | 0.01 | . . . have h₇ : ∃ (T : Set S), T ∉ P ∧ (∀ U ∈ P, T ∩ U |
| 15 | 64-76 | 66 | 10524 | 10524 | 8.7 | 1.25 | 2.63 | . . . . · intro U hU |
| 16 | 79-90 | 58 | 8297 | 4 | 0.0 | 1.1 | 0.0 | . . · have h₇ : ¬(∀ (U : Set S), U ∈ P → Aᶜ ∩ U ≠ ∅) |
| 17 | 85-89 | 22 | 8206 | 20 | 0.0 | 0.42 | 0.01 | . . . have h₉ : Aᶜ ∩ V = ∅ := by |
| 18 | 88-89 | 6 | 8095 | 8095 | 6.7 | 0.11 | 2.02 | . . . . simp_all [Set.ext_iff] |
| 19 | 91-92 | 2 | 3590 | 1 | 0.0 | 0.04 | 0.0 | . . · exfalso |
| 20 | 92 | 1 | 3587 | 3587 | 3.0 | 0.02 | 0.9 | . . . simp_all |
| 21 | 97-104 | 36 | 3770 | 17 | 0.0 | 0.68 | 0.0 | . have h₅ : U ⊆ Aᶜ := by |
| 22 | 100 | 0 | 3669 | 14 | 0.0 | 0.0 | 0.0 | . . have h₇ : x ∈ A := by simp_all [Set.mem_compl_if |
| 23 | 100 | 12 | 3655 | 3655 | 3.0 | 0.23 | 0.91 | . . . have h₇ : x ∈ A := by simp_all [Set.mem_compl_if |
| 24 | 105-112 | 36 | 3774 | 11 | 0.0 | 0.68 | 0.0 | . have h₆ : V ⊆ A := by |
| 25 | 108 | 0 | 3677 | 16 | 0.0 | 0.0 | 0.0 | . . have h₈ : x ∈ Aᶜ := by simp_all [Set.mem_compl_i |
| 26 | 108 | 12 | 3661 | 3661 | 3.0 | 0.23 | 0.92 | . . . have h₈ : x ∈ Aᶜ := by simp_all [Set.mem_compl_i |
| 27 | 114-122 | 51 | 3917 | 20 | 0.0 | 0.97 | 0.01 | . have h₇ : U ∩ V = ∅ := by |
| 28 | 121-122 | 6 | 3826 | 3826 | 3.2 | 0.11 | 0.96 | . . simp_all [Set.mem_compl_iff] |
| 29 | 125-126 | 6 | 6207 | 6207 | 5.2 | 0.11 | 1.55 | . simp_all [Set.ext_iff] |
| 30 | 128-138 | 72 | 196 | 31 | 0.0 | 1.37 | 0.01 | have h_not_both : ∀ (A : Set S), A ∈ P → Aᶜ ∉ P  |
| 31 | 140-292 | 15 | 58590 | 44 | 0.0 | 0.28 | 0.01 | have h_card : P.card = 2 ^ (Fintype.card S - 1)  |
| 32 | 141-292 | 56 | 58546 | 17 | 0.0 | 1.06 | 0.0 | . classical |
| 33 | 145-211 | 10 | 28704 | 9 | 0.0 | 0.19 | 0.0 | . . have h₁ : P.card = Q.card := by |
| 34 | 147-152 | 59 | 825 | 30 | 0.0 | 1.12 | 0.01 | . . . have h₂ : ∀ (A : Set S), A ∈ P → Aᶜ ∈ Q := by |
| 35 | 152 | 1 | 655 | 655 | 0.5 | 0.02 | 0.16 | . . . . tauto |
| 36 | 153-168 | 68 | 2178 | 33 | 0.0 | 1.29 | 0.01 | . . . have h₃ : ∀ (A : Set S), A ∈ Q → Aᶜ ∈ P := by |
| 37 | 155-157 | 26 | 842 | 842 | 0.7 | 0.49 | 0.21 | . . . . have h₄ : A ∈ (Finset.univ : Finset (Set S)) :=  |
| 38 | 158-160 | 18 | 632 | 632 | 0.5 | 0.34 | 0.16 | . . . . have h₅ : A ∉ P := by |
| 39 | 170-210 | 10 | 25691 | 8 | 0.0 | 0.19 | 0.0 | . . . have h₄ : P.card = Q.card := by |
| 40 | 172-209 | 121 | 25682 | 25682 | 21.3 | 2.3 | 6.42 | . . . . have h₅ : P.card = Q.card := by |
| 41 | 213-258 | 53 | 11050 | 38 | 0.0 | 1.01 | 0.01 | . . have h₂ : P.card + Q.card = 2 ^ Fintype.card S : |
| 42 | 214-245 | 91 | 8151 | 36 | 0.0 | 1.73 | 0.01 | . . . have h₃ : P.card + Q.card = (Finset.univ : Finse |
| 43 | 220-238 | 97 | 7308 | 7308 | 6.1 | 1.84 | 1.83 | . . . . have h₅ : P ∪ Q = (Finset.univ : Finset (Set S)) |
| 44 | 258 | 1 | 2466 | 2466 | 2.0 | 0.02 | 0.62 | . . . linarith |
| 45 | 260-263 | 34 | 2832 | 42 | 0.0 | 0.65 | 0.01 | . . have h₃ : P.card * 2 = 2 ^ Fintype.card S := by |
| 46 | 263 | 1 | 2747 | 2747 | 2.3 | 0.02 | 0.69 | . . . linarith |
| 47 | 271-291 | 39 | 15694 | 46 | 0.0 | 0.74 | 0.01 | . . have h₅ : P.card = 2 ^ (Fintype.card S - 1) := b |
| 48 | 274-284 | 44 | 1948 | 145 | 0.1 | 0.84 | 0.04 | . . . have h₈ : 2 ^ (Fintype.card S - 1) * 2 = 2 ^ Fin |
| 49 | 278-284 | 65 | 1524 | 1524 | 1.3 | 1.23 | 0.38 | . . . . calc |
| 50 | 285-290 | 50 | 13648 | 47 | 0.0 | 0.95 | 0.01 | . . . have h₉ : P.card = 2 ^ (Fintype.card S - 1) := b |
| 51 | 288-289 | 16 | 13417 | 13417 | 11.1 | 0.3 | 3.35 | . . . . have h₁₂ : P.card = 2 ^ (Fintype.card S - 1) :=  |
| 52 | 294 | 2 | 1 | 1 | 0.0 | 0.04 | 0.0 | exact h_card |

(tokens on lines outside any tactic span: 1; total 1754 vs ref 1754)

Top-3 hb: #40 L172-209 25682 (21.3%); #51 L288-289 13417 (11.1%); #15 L64-76 10524 (8.7%)

Top-3 tokens: #40 L172-209 121; #43 L220-238 97; #42 L214-245 91

Best submitted (v3): 39 tokens; hb 2895 on v4.25.0, tok% 97.78, hb% 97.85, cov% 100.0, proxy 98.54 (cand b2_ds); needs one profile compile.

## putnam_1995_a3

Reference: 4085 tokens, 14130 hb (official denominators); measured on v4.25.0; profile putnam_1995_a3-1ccd71f89cbb-5e7661376d6d.json (current), measured total 17959, profiled 17264, floor 271. Rates: 0.008 pts/token, 0.236 pts/100 hb, 11.11 pts/lost version (3 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 7-281 | 252 | 17262 | 54 | 0.3 | 2.02 | 0.13 | have h_main : ∀ (d e f : (Fin 9 → ℤ)), ((relatio |
| 2 | 18-65 | 70 | 4051 | 130 | 0.7 | 0.56 | 0.31 | . have h₅ : ∀ (i : Fin 9), 7 ∣ (e i - d i) * (10 : |
| 3 | 21-55 | 49 | 3506 | 115 | 0.6 | 0.39 | 0.27 | . . have h₇ : (digits_to_num (fun j : Fin 9 => if j  |
| 4 | 22-55 | 161 | 3391 | 440 | 2.5 | 1.29 | 1.04 | . . . calc |
| 5 | 24-26 | 6 | 591 | 591 | 3.3 | 0.05 | 1.39 | . . . . simp [hdigits_to_num] |
| 6 | 29-51 | 397 | 2029 | 2029 | 11.3 | 3.18 | 4.79 | . . . . calc |
| 7 | 53-55 | 6 | 331 | 331 | 1.8 | 0.05 | 0.78 | . . . . simp [hdigits_to_num] |
| 8 | 56-58 | 37 | 140 | 123 | 0.7 | 0.3 | 0.29 | . . have h₈ : 7 ∣ digits_to_num d + (e i - d i) * (1 |
| 9 | 60-64 | 35 | 250 | 54 | 0.3 | 0.28 | 0.13 | . . have h₉ : 7 ∣ (e i - d i) * (10 : ℤ) ^ (i : ℕ) + |
| 10 | 62 | 0 | 184 | 89 | 0.5 | 0.0 | 0.21 | . . . have h₁₀ : (e i - d i) * (10 : ℤ) ^ (i : ℕ) + di |
| 11 | 62 | 51 | 95 | 95 | 0.5 | 0.41 | 0.22 | . . . . have h₁₀ : (e i - d i) * (10 : ℤ) ^ (i : ℕ) + di |
| 12 | 67-114 | 70 | 4074 | 113 | 0.6 | 0.56 | 0.27 | . have h₆ : ∀ (i : Fin 9), 7 ∣ (f i - e i) * (10 : |
| 13 | 70-104 | 49 | 3546 | 110 | 0.6 | 0.39 | 0.26 | . . have h₈ : (digits_to_num (fun j : Fin 9 => if j  |
| 14 | 71-104 | 161 | 3436 | 477 | 2.7 | 1.29 | 1.13 | . . . calc |
| 15 | 73-75 | 6 | 593 | 593 | 3.3 | 0.05 | 1.4 | . . . . simp [hdigits_to_num] |
| 16 | 78-100 | 397 | 2035 | 2035 | 11.3 | 3.18 | 4.8 | . . . . calc |
| 17 | 102-104 | 6 | 331 | 331 | 1.8 | 0.05 | 0.78 | . . . . simp [hdigits_to_num] |
| 18 | 105-107 | 37 | 140 | 123 | 0.7 | 0.3 | 0.29 | . . have h₉ : 7 ∣ digits_to_num e + (f i - e i) * (1 |
| 19 | 109-113 | 35 | 251 | 55 | 0.3 | 0.28 | 0.13 | . . have h₁₀ : 7 ∣ (f i - e i) * (10 : ℤ) ^ (i : ℕ)  |
| 20 | 111 | 0 | 184 | 89 | 0.5 | 0.0 | 0.21 | . . . have h₁₁ : (f i - e i) * (10 : ℤ) ^ (i : ℕ) + di |
| 21 | 111 | 51 | 95 | 95 | 0.5 | 0.41 | 0.22 | . . . . have h₁₁ : (f i - e i) * (10 : ℤ) ^ (i : ℕ) + di |
| 22 | 116-189 | 14 | 6499 | 24 | 0.1 | 0.11 | 0.06 | . have h₇ : 7 ∣ digits_to_num e + digits_to_num d  |
| 23 | 117-133 | 36 | 1959 | 121 | 0.7 | 0.29 | 0.29 | . . have h₈ : digits_to_num e = digits_to_num d + ∑  |
| 24 | 118-133 | 181 | 1838 | 830 | 4.6 | 1.45 | 1.96 | . . . calc |
| 25 | 119 | 29 | 309 | 309 | 1.7 | 0.23 | 0.73 | . . . . digits_to_num e = ∑ i : Fin 9, e i * (10 : ℤ) ^  |
| 26 | 123 | 1 | 86 | 86 | 0.5 | 0.01 | 0.2 | . . . . ring |
| 27 | 127 | 1 | 103 | 103 | 0.6 | 0.01 | 0.24 | . . . . ring |
| 28 | 131-133 | 6 | 430 | 430 | 2.4 | 0.05 | 1.01 | . . . . simp [hdigits_to_num] |
| 29 | 134 | 35 | 129 | 129 | 0.7 | 0.28 | 0.3 | . . have h₉ : ∀ i : Fin 9, 7 ∣ (e i - d i) * (10 : ℤ |
| 30 | 135-138 | 45 | 190 | 132 | 0.7 | 0.36 | 0.31 | . . have h₁₀ : 7 ∣ ∑ i : Fin 9, ((e i - d i) * (10 : |
| 31 | 139-146 | 66 | 1073 | 238 | 1.3 | 0.53 | 0.56 | . . have h₁₁ : ∑ i : Fin 9, ((e i - d i) * (10 : ℤ)  |
| 32 | 140-146 | 106 | 835 | 441 | 2.5 | 0.85 | 1.04 | . . . calc |
| 33 | 144-146 | 10 | 352 | 352 | 2.0 | 0.08 | 0.83 | . . . . simp [Finset.sum_const, Finset.card_fin] |
| 34 | 147-149 | 45 | 180 | 162 | 0.9 | 0.36 | 0.38 | . . have h₁₂ : 7 ∣ ∑ i : Fin 9, (e i - d i) * (10 :  |
| 35 | 150-188 | 18 | 2943 | 22 | 0.1 | 0.14 | 0.05 | . . have h₁₃ : 7 ∣ digits_to_num e + digits_to_num d |
| 36 | 151-152 | 41 | 829 | 140 | 0.8 | 0.33 | 0.33 | . . . have h₁₄ : digits_to_num e + digits_to_num d = 2 |
| 37 | 152 | 1 | 689 | 689 | 3.8 | 0.01 | 1.63 | . . . . linarith |
| 38 | 154-187 | 39 | 2079 | 136 | 0.8 | 0.31 | 0.32 | . . . have h₁₅ : 7 ∣ 2 * digits_to_num d + ∑ i : Fin 9 |
| 39 | 155 | 37 | 136 | 136 | 0.8 | 0.3 | 0.32 | . . . . have h₁₆ : 7 ∣ ∑ i : Fin 9, (e i - d i) * (10 :  |
| 40 | 156-186 | 449 | 1805 | 1805 | 10.1 | 3.59 | 4.26 | . . . . have h₁₇ : 7 ∣ 2 * digits_to_num d + ∑ i : Fin 9 |
| 41 | 191-222 | 80 | 1227 | 103 | 0.6 | 0.64 | 0.24 | . have h₈ : ∀ (i : Fin 9), 7 ∣ (f i - d i) * (10 : |
| 42 | 193 | 30 | 106 | 106 | 0.6 | 0.24 | 0.25 | . . have h₉ : 7 ∣ (f i - e i) * (10 : ℤ) ^ (i : ℕ) + |
| 43 | 197-209 | 79 | 410 | 58 | 0.3 | 0.63 | 0.14 | . . have h₁₂ : 7 ∣ (f i - e i) * (10 : ℤ) ^ (i : ℕ)  |
| 44 | 203-204 | 43 | 95 | 71 | 0.4 | 0.34 | 0.17 | . . . have h₁₅ : 7 ∣ ((f i - e i) * (10 : ℤ) ^ (i : ℕ) |
| 45 | 206-207 | 61 | 166 | 107 | 0.6 | 0.49 | 0.25 | . . . have h₁₆ : ((f i - e i) * (10 : ℤ) ^ (i : ℕ) + d |
| 46 | 211-221 | 93 | 532 | 48 | 0.3 | 0.74 | 0.11 | . . have h₁₃ : 7 ∣ (f i - d i) * (10 : ℤ) ^ (i : ℕ)  |
| 47 | 215-216 | 60 | 162 | 105 | 0.6 | 0.48 | 0.25 | . . . have h₁₆ : 7 ∣ ((f i - e i) * (10 : ℤ) ^ (i : ℕ) |
| 48 | 218-219 | 75 | 197 | 131 | 0.7 | 0.6 | 0.31 | . . . have h₁₇ : ((f i - e i) * (10 : ℤ) ^ (i : ℕ) - d |
| 49 | 224-277 | 24 | 1215 | 26 | 0.1 | 0.19 | 0.06 | . have h₉ : ∀ (i : Fin 9), 7 ∣ d i - f i := by |
| 50 | 226 | 27 | 97 | 97 | 0.5 | 0.22 | 0.23 | . . have h₁₀ : 7 ∣ (f i - d i) * (10 : ℤ) ^ (i : ℕ)  |
| 51 | 227-268 | 58 | 814 | 23 | 0.1 | 0.46 | 0.05 | . . have h₁₁ : 7 ∣ (f i - d i) := by |
| 52 | 232-242 | 46 | 257 | 26 | 0.1 | 0.37 | 0.06 | . . . have h₁₄ : ¬(7 : ℤ) ∣ (10 : ℤ) ^ (i : ℕ) := by |
| 53 | 235-237 | 33 | 210 | 210 | 1.2 | 0.26 | 0.5 | . . . . have h₁₅ : (7 : ℕ) ∣ (10 : ℕ) ^ (i : ℕ) := by |
| 54 | 244-267 | 73 | 456 | 20 | 0.1 | 0.58 | 0.05 | . . . have h₁₅ : (7 : ℤ) ∣ (f i - d i) := by |
| 55 | 249-266 | 192 | 368 | 368 | 2.0 | 1.54 | 0.87 | . . . . have h₁₈ : (7 : ℤ) ∣ (f i - d i) := by |
| 56 | 270-276 | 54 | 277 | 28 | 0.2 | 0.43 | 0.07 | . . have h₁₂ : 7 ∣ d i - f i := by |
| 57 | 272-273 | 15 | 134 | 23 | 0.1 | 0.12 | 0.05 | . . . have h₁₄ : 7 ∣ -(f i - d i) := by |
| 58 | 273 | 3 | 111 | 111 | 0.6 | 0.02 | 0.26 | . . . . exact dvd_neg.mpr h₁₃ |
| 59 | 282 | 2 | 2 | 2 | 0.0 | 0.02 | 0.0 | exact h_main |

(tokens on lines outside any tactic span: 1; total 4085 vs ref 4085)

Top-3 hb: #16 L78-100 2035 (11.3%); #6 L29-51 2029 (11.3%); #40 L156-186 1805 (10.1%)

Top-3 tokens: #40 L156-186 449; #6 L29-51 397; #16 L78-100 397

Best submitted (v3): 433 tokens; hb 2412 on v4.25.0, tok% 89.4, hb% 82.93, cov% 100.0, proxy 90.78 (cand a3_ds); needs one profile compile.

## Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema

Reference: 1372 tokens, 26970 hb (official denominators); measured on v4.32.0; profile Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema-c48433678e8f-6f4bf2407beb.json (current), measured total 26973, profiled 25801, floor 664. Rates: 0.024 pts/token, 0.124 pts/100 hb, 33.33 pts/lost version (1 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 10-11 | 37 | 196 | 196 | 0.7 | 0.89 | 0.24 | have hEs : ∀ j, ContDiff ℝ 2 (fun y => A.electri |
| 2 | 12-13 | 36 | 209 | 209 | 0.8 | 0.86 | 0.26 | have hEd : ∀ j k, Differentiable ℝ (∂[k] (fun y  |
| 3 | 14-17 | 59 | 219 | 219 | 0.8 | 1.42 | 0.27 | have hBt : ∀ j, Differentiable ℝ |
| 4 | 18-19 | 26 | 99 | 49 | 0.2 | 0.62 | 0.06 | have hJt : Differentiable ℝ (fun s => J.currentD |
| 5 | 20-126 | 998 | 25078 | 3997 | 14.8 | 23.95 | 4.96 | calc _ |
| 6 | 24-30 | 45 | 147 | 147 | 0.5 | 1.08 | 0.18 | . conv_lhs => |
| 7 | 34 | 4 | 176 | 176 | 0.7 | 0.1 | 0.22 | . rw [fderiv_fun_sub] |
| 8 | 35 | 11 | 260 | 260 | 1.0 | 0.26 | 0.32 | . simp only [one_div, mul_inv_rev, FunLike.coe_sub |
| 9 | 36 | 14 | 331 | 331 | 1.2 | 0.34 | 0.41 | . rw [fderiv_const_mul (Differentiable.fun_sum fun |
| 10 | 37 | 5 | 213 | 213 | 0.8 | 0.12 | 0.26 | . rw [fderiv_const_mul hJt.differentiableAt] |
| 11 | 38 | 4 | 2784 | 2784 | 10.3 | 0.1 | 3.45 | . simp [Time.deriv_eq] |
| 12 | 39 | 0 | 258 | 1 | 0.0 | 0.0 | 0.0 | . · exact ((Differentiable.fun_sum fun j _ => hBt  |
| 13 | 39 | 16 | 257 | 257 | 1.0 | 0.38 | 0.32 | . . · exact ((Differentiable.fun_sum fun j _ => hBt  |
| 14 | 45 | 13 | 230 | 230 | 0.9 | 0.31 | 0.29 | . rw [fderiv_fun_sum fun i _ => (hBt i).differenti |
| 15 | 46 | 7 | 261 | 261 | 1.0 | 0.17 | 0.32 | . simp only [FunLike.coe_sum, Finset.sum_apply] |
| 16 | 54 | 4 | 124 | 124 | 0.5 | 0.1 | 0.15 | . rw [Space.time_deriv_comm_space_deriv] |
| 17 | 60 | 1 | 269 | 269 | 1.0 | 0.02 | 0.33 | . congr |
| 18 | 75 | 16 | 489 | 489 | 1.8 | 0.38 | 0.61 | . rw [fderiv_fun_sub (hEd _ _).differentiableAt (h |
| 19 | 76 | 5 | 605 | 605 | 2.2 | 0.12 | 0.75 | . simp [← Space.deriv_eq_fderiv_basis] |
| 20 | 79 | 20 | 2398 | 2398 | 8.9 | 0.48 | 2.97 | . 1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t :=  |
| 21 | 85 | 11 | 231 | 231 | 0.9 | 0.26 | 0.29 | . rw [Space.deriv_commute _ (hEs _), Space.deriv_e |
| 22 | 91 | 4 | 189 | 189 | 0.7 | 0.1 | 0.23 | . rw [fderiv_fun_sum] |
| 23 | 92 | 5 | 1744 | 1744 | 6.5 | 0.12 | 2.16 | . simp [← Space.deriv_eq_fderiv_basis] |
| 24 | 113-119 | 15 | 2795 | 4 | 0.0 | 0.36 | 0.0 | . · rw [Space.deriv_eq_fderiv_basis] |
| 25 | 114 | 4 | 183 | 183 | 0.7 | 0.1 | 0.23 | . . rw [fderiv_const_mul] |
| 26 | 115 | 5 | 1224 | 1224 | 4.5 | 0.12 | 1.52 | . . simp [← Space.deriv_eq_fderiv_basis] |
| 27 | 116 | 1 | 1150 | 1150 | 4.3 | 0.02 | 1.43 | . . field_simp |
| 28 | 125 | 4 | 2644 | 2644 | 9.8 | 0.1 | 3.28 | . simp [FreeSpace.c_sq] |
| 29 | 126 | 1 | 3283 | 3283 | 12.2 | 0.02 | 4.07 | . field_simp |

(tokens on lines outside any tactic span: 1; total 1372 vs ref 1372)

Top-3 hb: #5 L20-126 3997 (14.8%); #29 L126 3283 (12.2%); #11 L38 2784 (10.3%)

Top-3 tokens: #5 L20-126 998; #3 L14-17 59; #6 L24-30 45

Best submitted (v3): 573 tokens; hb 6275 on v4.32.0, tok% 58.24, hb% 76.73, cov% 100.0, proxy 78.32 (cand timederiv_ds); needs one profile compile.

## Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress

Reference: 408 tokens, 59830 hb (official denominators); measured on v4.33.0-rc2; profile Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress-3aa9d4416c18-58ecaddbd7c8.json (current), measured total 59812, profiled 59690, floor 52. Rates: 0.082 pts/token, 0.056 pts/100 hb, 11.11 pts/lost version (3 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 9 | 6 | 6 | 0.0 | 0.74 | 0.0 | generalize eq : [] = Γ at der |
| 2 | 3 | 9 | 10 | 10 | 0.0 | 0.74 | 0.01 | have der' : Typing Γ t τ := der |
| 3 | 4 | 5 | 90 | 90 | 0.2 | 0.41 | 0.05 | induction der <;> subst eq |
| 4 | 5 | 5 | 68 | 1 | 0.0 | 0.41 | 0.0 | case var mem => grind |
| 5 | 6-22 | 12 | 7579 | 2 | 0.0 | 0.98 | 0.0 | case app t₁ _ _ t₂ l r ih_l ih_r => |
| 6 | 8-22 | 22 | 7577 | 12 | 0.0 | 1.8 | 0.01 | . cases ih_l rfl l with |
| 7 | 10-18 | 34 | 4499 | 14 | 0.0 | 2.79 | 0.01 | . . cases ih_r rfl r with |
| 8 | 13 | 5 | 1143 | 1143 | 1.9 | 0.41 | 0.64 | . . . exists t₁ ^ᵗᵗ t₂ |
| 9 | 17 | 3 | 3085 | 3085 | 5.2 | 0.25 | 1.73 | . . . exists t₁.app t₂' |
| 10 | 21 | 3 | 2963 | 2963 | 5.0 | 0.25 | 1.66 | . . exists t₁'.app t₂ |
| 11 | 23-34 | 12 | 3067 | 3 | 0.0 | 0.98 | 0.0 | case tapp σ' der _ ih => |
| 12 | 26-34 | 32 | 3061 | 10 | 0.0 | 2.62 | 0.01 | . cases ih with |
| 13 | 29 | 5 | 532 | 532 | 0.9 | 0.41 | 0.3 | . . exists t ^ᵗᵞ σ' |
| 14 | 33 | 4 | 2075 | 2075 | 3.5 | 0.33 | 1.16 | . . exists .tapp t' σ' |
| 15 | 35-44 | 13 | 8364 | 2 | 0.0 | 1.07 | 0.0 | case let' t₁ σ t₂ τ L der _ ih _ => |
| 16 | 37-44 | 23 | 8362 | 14 | 0.0 | 1.89 | 0.01 | . cases ih rfl der with |
| 17 | 39 | 5 | 2860 | 2860 | 4.8 | 0.41 | 1.6 | . . exists t₂ ^ᵗᵗ t₁ |
| 18 | 43 | 3 | 5111 | 5111 | 8.5 | 0.25 | 2.86 | . . exists t₁'.let' t₂ |
| 19 | 45-52 | 6 | 4361 | 1 | 0.0 | 0.49 | 0.0 | case inl der _ ih => |
| 20 | 46-52 | 26 | 4360 | 13 | 0.0 | 2.13 | 0.01 | . cases (ih rfl der) with |
| 21 | 51 | 3 | 4183 | 4183 | 7.0 | 0.25 | 2.34 | . . exists .inl t' |
| 22 | 53-60 | 6 | 4363 | 0 | 0.0 | 0.49 | 0.0 | case inr der _ ih => |
| 23 | 54-60 | 26 | 4363 | 14 | 0.0 | 2.13 | 0.01 | . cases (ih rfl der) with |
| 24 | 59 | 3 | 4185 | 4185 | 7.0 | 0.25 | 2.34 | . . exists .inr t' |
| 25 | 61-70 | 17 | 30637 | 1 | 0.0 | 1.39 | 0.0 | case case t₁ _ _ t₂ _ t₃ _ der _ _ ih _ _ => |
| 26 | 63-70 | 31 | 30636 | 15 | 0.0 | 2.54 | 0.01 | . cases ih rfl der with |
| 27 | 66 | 18 | 24198 | 24198 | 40.5 | 1.48 | 13.55 | . . cases lr <;> [exists t₂ ^ᵗᵗ t₁; exists t₃ ^ᵗᵗ t₁ |
| 28 | 69 | 4 | 6182 | 6182 | 10.3 | 0.33 | 3.46 | . . exists t₁'.case t₂ t₃ |
| 29 | 71 | 0 | 406 | 1 | 0.0 | 0.0 | 0.0 | case sub => grind |
| 30 | 71 | 4 | 405 | 405 | 0.7 | 0.33 | 0.23 | . case sub => grind |
| 31 | 72-77 | 31 | 365 | 2 | 0.0 | 2.54 | 0.0 | case abs σ _ τ L _ _=> |
| 32 | 78-83 | 28 | 374 | 3 | 0.0 | 2.3 | 0.0 | case tabs L _ _=> |

(tokens on lines outside any tactic span: 1; total 408 vs ref 408)

Top-3 hb: #27 L66 24198 (40.5%); #28 L69 6182 (10.3%); #18 L43 5111 (8.5%)

Top-3 tokens: #7 L10-18 34; #12 L26-34 32; #26 L63-70 31

Best submitted (v3): 332 tokens; hb 1006 on v4.33.0-rc2, tok% 18.63, hb% 98.32, cov% 100.0, proxy 72.32 (cand fsub_ds); needs one profile compile.

## Cslib.SKI.parallelReduction_diamond

Reference: 407 tokens, 1383 hb (official denominators); measured on v4.33.0-rc2; profile Cslib.SKI.parallelReduction_diamond-3aa9d4416c18-c3cdad6c8ce5.json (current), measured total 1384, profiled 984, floor 8. Rates: 0.082 pts/token, 2.41 pts/100 hb, 8.33 pts/lost version (4 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 6 | 1 | 1 | 0.1 | 0.49 | 0.02 | intro a a₁ a₂ h₁ h₂ |
| 2 | 3 | 2 | 23 | 23 | 1.7 | 0.16 | 0.55 | cases h₁ |
| 3 | 4 | 12 | 6 | 0 | 0.0 | 0.98 | 0.0 | case refl => exact ⟨a₂, h₂, .refl a₂⟩ |
| 4 | 5-31 | 9 | 411 | 3 | 0.2 | 0.74 | 0.07 | case par a a' b b' ha' hb' => |
| 5 | 6 | 2 | 33 | 33 | 2.4 | 0.16 | 0.8 | . cases h₂ |
| 6 | 7-9 | 16 | 49 | 1 | 0.1 | 1.31 | 0.02 | . case refl => |
| 7 | 8 | 4 | 42 | 42 | 3.0 | 0.33 | 1.01 | . . use a' ⬝ b' |
| 8 | 10-16 | 18 | 94 | 4 | 0.3 | 1.48 | 0.1 | . case par a'' b'' ha'' hb'' => |
| 9 | 11 | 10 | 20 | 20 | 1.4 | 0.82 | 0.48 | . . let ⟨a₃, ha⟩ := parallelReduction_diamond ha' ha |
| 10 | 12 | 10 | 18 | 18 | 1.3 | 0.82 | 0.43 | . . let ⟨b₃, hb⟩ := parallelReduction_diamond hb' hb |
| 11 | 13 | 4 | 46 | 46 | 3.3 | 0.33 | 1.11 | . . use a₃ ⬝ b₃ |
| 12 | 17-19 | 3 | 16 | 1 | 0.1 | 0.25 | 0.02 | . case red_I => |
| 13 | 18 | 6 | 8 | 8 | 0.6 | 0.49 | 0.19 | . . rw [I_irreducible a' ha'] |
| 14 | 19 | 5 | 7 | 7 | 0.5 | 0.41 | 0.17 | . . use b', .red_I b' |
| 15 | 20-24 | 11 | 75 | 3 | 0.2 | 0.9 | 0.07 | . case red_K => |
| 16 | 21 | 11 | 19 | 19 | 1.4 | 0.9 | 0.46 | . . let ⟨a₂', ha₂'⟩ := Ka_irreducible a₂ a' ha' |
| 17 | 22 | 4 | 8 | 8 | 0.6 | 0.33 | 0.19 | . . rw [ha₂'.2] |
| 18 | 23 | 2 | 42 | 42 | 3.0 | 0.16 | 1.01 | . . use a₂' |
| 19 | 25-31 | 5 | 141 | 1 | 0.1 | 0.41 | 0.02 | . case red_S a c => |
| 20 | 26 | 14 | 34 | 34 | 2.5 | 1.15 | 0.82 | . . let ⟨a'', c', h⟩ := Sab_irreducible a c a' ha' |
| 21 | 27 | 4 | 10 | 10 | 0.7 | 0.33 | 0.24 | . . rw [h.2.2] |
| 22 | 28 | 15 | 29 | 29 | 2.1 | 1.23 | 0.7 | . . use a'' ⬝ b' ⬝ (c' ⬝ b'), .red_S a'' c' b' |
| 23 | 29-31 | 7 | 67 | 67 | 4.8 | 0.57 | 1.61 | . . apply ParallelReduction.par <;> |
| 24 | 32-39 | 3 | 163 | 3 | 0.2 | 0.25 | 0.07 | case red_I => |
| 25 | 33 | 2 | 20 | 20 | 1.4 | 0.16 | 0.48 | . cases h₂ |
| 26 | 34 | 0 | 42 | 1 | 0.1 | 0.0 | 0.02 | . case refl => use a₁; exact ⟨.refl a₁, .red_I a₁⟩ |
| 27 | 34 | 14 | 38 | 38 | 2.7 | 1.15 | 0.92 | . . case refl => use a₁; exact ⟨.refl a₁, .red_I a₁⟩ |
| 28 | 35-38 | 14 | 56 | 2 | 0.1 | 1.15 | 0.05 | . case par c a₁' hc ha => |
| 29 | 36 | 6 | 8 | 8 | 0.6 | 0.49 | 0.19 | . . rw [I_irreducible c hc] |
| 30 | 37 | 2 | 43 | 43 | 3.1 | 0.16 | 1.04 | . . use a₁' |
| 31 | 39 | 0 | 42 | 1 | 0.1 | 0.0 | 0.02 | . case red_I => use a₁; exact ⟨.refl a₁, .refl a₁⟩ |
| 32 | 39 | 14 | 38 | 38 | 2.7 | 1.15 | 0.92 | . . case red_I => use a₁; exact ⟨.refl a₁, .refl a₁⟩ |
| 33 | 40-49 | 4 | 185 | 3 | 0.2 | 0.33 | 0.07 | case red_K c => |
| 34 | 41 | 2 | 24 | 24 | 1.7 | 0.16 | 0.58 | . cases h₂ |
| 35 | 42 | 0 | 43 | 1 | 0.1 | 0.0 | 0.02 | . case refl => use a₁; exact ⟨.refl a₁, .red_K a₁  |
| 36 | 42 | 15 | 39 | 39 | 2.8 | 1.23 | 0.94 | . . case refl => use a₁; exact ⟨.refl a₁, .red_K a₁  |
| 37 | 43-47 | 15 | 73 | 3 | 0.2 | 1.23 | 0.07 | . case par a' c' ha hc => |
| 38 | 44 | 11 | 17 | 17 | 1.2 | 0.9 | 0.41 | . . let ⟨a₁', h'⟩ := Ka_irreducible a₁ a' ha |
| 39 | 45 | 4 | 8 | 8 | 0.6 | 0.33 | 0.19 | . . rw [h'.2] |
| 40 | 46 | 2 | 42 | 42 | 3.0 | 0.16 | 1.01 | . . use a₁' |
| 41 | 48-49 | 3 | 42 | 1 | 0.1 | 0.25 | 0.02 | . case red_K => |
| 42 | 49 | 11 | 38 | 38 | 2.7 | 0.9 | 0.92 | . . use a₁; exact ⟨.refl a₁, .refl a₁⟩ |
| 43 | 50-64 | 6 | 195 | 1 | 0.1 | 0.49 | 0.02 | case red_S a b c => |
| 44 | 51 | 2 | 29 | 29 | 2.1 | 0.16 | 0.7 | . cases h₂ |
| 45 | 52-54 | 11 | 49 | 2 | 0.1 | 0.9 | 0.05 | . case refl => |
| 46 | 53 | 10 | 43 | 43 | 3.1 | 0.82 | 1.04 | . . use a ⬝ c ⬝ (b ⬝ c) |
| 47 | 55-63 | 12 | 105 | 4 | 0.3 | 0.98 | 0.1 | . case par d c' hd hc => |
| 48 | 56 | 14 | 34 | 34 | 2.5 | 1.15 | 0.82 | . . let ⟨a', b', h⟩ := Sab_irreducible a b d hd |
| 49 | 57 | 4 | 10 | 10 | 0.7 | 0.33 | 0.24 | . . rw [h.2.2] |
| 50 | 58 | 10 | 47 | 47 | 3.4 | 0.82 | 1.13 | . . use a' ⬝ c' ⬝ (b' ⬝ c') |
| 51 | 60-62 | 13 | 9 | 2 | 0.1 | 1.07 | 0.05 | . . · apply ParallelReduction.par |
| 52 | 64 | 0 | 11 | 0 | 0.0 | 0.0 | 0.0 | . case red_S => exact ⟨a ⬝ c ⬝ (b ⬝ c), .refl _, . |
| 53 | 64 | 22 | 11 | 11 | 0.8 | 1.8 | 0.27 | . . case red_S => exact ⟨a ⬝ c ⬝ (b ⬝ c), .refl _, . |

(tokens on lines outside any tactic span: 1; total 407 vs ref 407)

Top-3 hb: #23 L29-31 67 (4.8%); #50 L58 47 (3.4%); #11 L13 46 (3.3%)

Top-3 tokens: #53 L64 22; #8 L10-16 18; #6 L7-9 16

Best submitted (v3): 240 tokens; hb 416 on v4.33.0-rc2, tok% 41.03, hb% 69.92, cov% 100.0, proxy 70.32 (cand ski_ds); needs one profile compile.

## Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius

Reference: 1463 tokens, 15645 hb (official denominators); measured on v4.31.0; profile Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius-c1712f6c496d-a0d463beab80.json (current), measured total 15913, profiled 14651, floor 752. Rates: 0.023 pts/token, 0.213 pts/100 hb, 8.33 pts/lost version (4 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 12 | 6 | 112 | 112 | 0.7 | 0.14 | 0.24 | let d_H := Code.distFromCode f C_i |
| 2 | 16-23 | 15 | 392 | 15 | 0.1 | 0.34 | 0.03 | have h_d_i_gt_0 : d_i > 0 := by |
| 3 | 18-20 | 46 | 110 | 45 | 0.3 | 1.06 | 0.1 | . have h_exp_lt : ℓ - i.val < ℓ + 𝓡 - i.val := by |
| 4 | 21-22 | 29 | 152 | 117 | 0.7 | 0.67 | 0.25 | . have h_pow_lt : 2 ^ (ℓ - i.val) < 2 ^ (ℓ + 𝓡 - i |
| 5 | 25-27 | 14 | 263 | 91 | 0.6 | 0.32 | 0.19 | have h_C_i_nonempty : Nonempty C_i := by |
| 6 | 27 | 18 | 148 | 108 | 0.7 | 0.41 | 0.23 | . exact Submodule.nonempty (BBF_Code 𝔽q β (h_ℓ_add |
| 7 | 30-49 | 70 | 670 | 195 | 1.2 | 1.61 | 0.42 | obtain ⟨g', h_g'_mem, h_g'_min_card⟩ : ∃ g' ∈ C_ |
| 8 | 33-34 | 25 | 246 | 246 | 1.5 | 0.57 | 0.52 | . let S := (fun (g : C_i) => (fiberwiseDisagreemen |
| 9 | 49 | 14 | 109 | 27 | 0.2 | 0.32 | 0.06 | . exact ⟨g_subtype.val, g_subtype.property, by exa |
| 10 | 52-147 | 46 | 8373 | 212 | 1.3 | 1.06 | 0.45 | have h_dist_le_fw_dist_times_fiber_size : (hammi |
| 11 | 56 | 28 | 242 | 242 | 1.5 | 0.64 | 0.52 | . change (Δ₀(f, g') : ℕ∞) ≤ ↑d_fw * ((2 ^ steps :  |
| 12 | 59 | 15 | 449 | 449 | 2.8 | 0.34 | 0.96 | . set ΔH := Finset.filter (fun x => f x ≠ g' x) Fi |
| 13 | 60-61 | 10 | 143 | 22 | 0.1 | 0.23 | 0.05 | . have h_dist_eq_card : hammingDist f g' = ΔH.card |
| 14 | 61 | 9 | 121 | 121 | 0.8 | 0.21 | 0.26 | . . simp only [hammingDist, ne_eq, ΔH] |
| 15 | 64 | 11 | 480 | 480 | 3.0 | 0.25 | 1.02 | . set Y_bad := fiberwiseDisagreementSet 𝔽q β i ste |
| 16 | 69 | 11 | 167 | 72 | 0.5 | 0.25 | 0.15 | . have hFinType_Y_bad : Fintype Y_bad := by exact  |
| 17 | 73-114 | 105 | 4730 | 276 | 1.7 | 2.42 | 0.59 | . have h_ΔH_subset_bad_fiber_points : ΔH ⊆ Finset. |
| 18 | 74 | 26 | 157 | 157 | 1.0 | 0.6 | 0.33 | . . (t := fun y => ((qMap_total_fiber 𝔽q β (i := ⟨i, |
| 19 | 83 | 5 | 137 | 137 | 0.9 | 0.11 | 0.29 | . . apply Finset.mem_biUnion.mpr; use y_of_x |
| 20 | 85-104 | 60 | 2730 | 59 | 0.4 | 1.38 | 0.13 | . . have h_elemenet_Y_bad : y_of_x ∈ Y_bad.toFinset  |
| 21 | 87-88 | 21 | 1483 | 1483 | 9.3 | 0.48 | 3.16 | . . . simp only [fiberwiseDisagreementSet, iteratedQuo |
| 22 | 91-92 | 24 | 250 | 123 | 0.8 | 0.55 | 0.26 | . . . have h_X_in_source : X ∈ sDomain 𝔽q β h_ℓ_add_R_ |
| 23 | 94 | 2 | 141 | 141 | 0.9 | 0.05 | 0.3 | . . . use h_X_in_source |
| 24 | 96-99 | 15 | 575 | 174 | 1.1 | 0.34 | 0.37 | . . . have h_forward_iterated_qmap : Polynomial.eval X |
| 25 | 97 | 12 | 119 | 119 | 0.7 | 0.28 | 0.25 | . . . . (intermediateNormVpoly 𝔽q β h_ℓ_add_R_rate ⟨↑i,  |
| 26 | 98 | 14 | 224 | 224 | 1.4 | 0.32 | 0.48 | . . . . ⟨steps, by simp only; omega⟩) = y_of_x := by |
| 27 | 107-108 | 35 | 690 | 613 | 3.9 | 0.8 | 1.31 | . . set qMapFiber := qMap_total_fiber 𝔽q β (i := ⟨i, |
| 28 | 109 | 15 | 185 | 185 | 1.2 | 0.34 | 0.39 | . . simp only [coe_univ, Set.image_univ, Set.toFinse |
| 29 | 110-111 | 30 | 238 | 172 | 1.1 | 0.69 | 0.37 | . . use (pointToIterateQuotientIndex (i := ⟨i, by om |
| 30 | 120-141 | 52 | 1100 | 3 | 0.0 | 1.2 | 0.01 | . · -- The size of the sum is the number of bad fi |
| 31 | 122 | 5 | 113 | 113 | 0.7 | 0.11 | 0.24 | . . simp only [Set.toFinset_card] |
| 32 | 125-126 | 11 | 133 | 133 | 0.8 | 0.25 | 0.28 | . . simp only [Set.image_univ, Fintype.card_ofFinset |
| 33 | 127-134 | 74 | 654 | 331 | 2.1 | 1.7 | 0.71 | . . have h_card_fiber_of_each_y : ∀ y ∈ Y_bad.toFins |
| 34 | 132-133 | 17 | 125 | 70 | 0.4 | 0.39 | 0.15 | . . . have hy_card_fiber_of_y := h_card_fiber_per_quot |
| 35 | 134 | 11 | 122 | 122 | 0.8 | 0.25 | 0.26 | . . . simp only [coe_univ, Set.image_univ, Fintype.car |
| 36 | 142-147 | 9 | 498 | 3 | 0.0 | 0.21 | 0.01 | . · -- Prove that the fibers for distinct quotient |
| 37 | 144-145 | 21 | 243 | 115 | 0.7 | 0.48 | 0.24 | . . have h_disjoint := qMap_total_fiber_disjoint (i  |
| 38 | 144 | 20 | 115 | 115 | 0.7 | 0.46 | 0.24 | . . . have h_disjoint := qMap_total_fiber_disjoint (i  |
| 39 | 146 | 7 | 199 | 199 | 1.3 | 0.16 | 0.42 | . . simp only [Function.onFun, coe_univ] |
| 40 | 150-159 | 15 | 640 | 93 | 0.6 | 0.34 | 0.2 | have h_dist_bridge : d_H ≤ d_fw * 2 ^ steps := b |
| 41 | 152 | 23 | 135 | 135 | 0.8 | 0.53 | 0.29 | . apply le_trans (a := d_H) (c := d_fw * 2 ^ steps |
| 42 | 153-158 | 3 | 410 | 1 | 0.0 | 0.07 | 0.0 | . · -- ⊢ d_H ≤ ↑Δ₀(f, g') |
| 43 | 154 | 14 | 275 | 275 | 1.7 | 0.32 | 0.59 | . . simp only [distFromCode, SetLike.mem_coe, hammin |
| 44 | 158 | 2 | 113 | 113 | 0.7 | 0.05 | 0.24 | . . use g' |
| 45 | 163-165 | 18 | 114 | 41 | 0.3 | 0.41 | 0.09 | have h_fw_bound : 2 * d_fw ≤ d_i_plus_steps - 1  |
| 46 | 169-178 | 43 | 873 | 52 | 0.3 | 0.99 | 0.11 | have h_algebraic_identity : (d_i_plus_steps - 1) |
| 47 | 172-174 | 23 | 474 | 112 | 0.7 | 0.53 | 0.24 | . have h1 : ℓ + 𝓡 - (↑i + steps) + steps = ℓ + 𝓡 - |
| 48 | 173-174 | 12 | 362 | 95 | 0.6 | 0.28 | 0.2 | . . rw [Nat.sub_add_eq_sub_sub_rev (h1 := by omega)  |
| 49 | 173 | 0 | 123 | 123 | 0.8 | 0.0 | 0.26 | . . . rw [Nat.sub_add_eq_sub_sub_rev (h1 := by omega)  |
| 50 | 173 | 16 | 144 | 144 | 0.9 | 0.37 | 0.31 | . . . rw [Nat.sub_add_eq_sub_sub_rev (h1 := by omega)  |
| 51 | 175-177 | 21 | 232 | 74 | 0.5 | 0.48 | 0.16 | . have h2 : (ℓ - (↑i + steps) + steps) = ℓ - i :=  |
| 52 | 176-177 | 28 | 158 | 95 | 0.6 | 0.64 | 0.2 | . . rw [Nat.sub_add_eq_sub_sub_rev (h1 := by omega)  |
| 53 | 182-185 | 18 | 189 | 16 | 0.1 | 0.41 | 0.03 | have h_dH_ne_top : d_H ≠ ⊤ := by |
| 54 | 184 | 6 | 127 | 127 | 0.8 | 0.14 | 0.27 | . rw [Code.distFromCode_eq_top_iff_empty f C_i] |
| 55 | 192-200 | 39 | 1569 | 42 | 0.3 | 0.9 | 0.09 | have h_final_inequality : 2 * d_H_nat ≤ d_i - 1  |
| 56 | 196-200 | 28 | 1449 | 228 | 1.4 | 0.64 | 0.49 | . calc 2 * d_H_nat |
| 57 | 197 | 14 | 626 | 626 | 3.9 | 0.32 | 1.33 | . . _ ≤ 2 * (d_fw * 2 ^ steps) := by gcongr |
| 58 | 199 | 15 | 566 | 566 | 3.6 | 0.34 | 1.21 | . . _ ≤ (d_i_plus_steps - 1) * 2 ^ steps := by gcong |
| 59 | 206 | 34 | 617 | 559 | 3.5 | 0.78 | 1.19 | change ((2 : ℕ) : ℕ∞) * ↑Δ₀(f, C_i).toNat < ↑(BB |
| 60 | 208-209 | 28 | 420 | 420 | 2.6 | 0.64 | 0.89 | apply Nat.lt_of_le_pred (n := 2 * Δ₀(f, C_i).toN |

(tokens on lines outside any tactic span: 105; total 1463 vs ref 1463)

Top-3 hb: #21 L87-88 1483 (9.3%); #57 L197 626 (3.9%); #27 L107-108 613 (3.9%)

Top-3 tokens: #17 L73-114 105; #33 L127-134 74; #7 L30-49 70

Best submitted (v3): 476 tokens; hb 3831 on v4.31.0, tok% 67.46, hb% 75.51, cov% 100.0, proxy 80.99 (cand fiber_ds); needs one profile compile.

## Binius.BinaryBasefold.fold_advances_evaluation_poly

Reference: 1906 tokens, 45273 hb (official denominators); measured on v4.31.0; profile Binius.BinaryBasefold.fold_advances_evaluation_poly-c1712f6c496d-03b7733bee86.json (current), measured total 45520, profiled 42889, floor 2513. Rates: 0.017 pts/token, 0.074 pts/100 hb, 11.11 pts/lost version (3 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 14-15 | 39 | 410 | 135 | 0.3 | 0.66 | 0.1 | apply mul_two_add_bit_lt_two_pow (c := ℓ - i) (a |
| 2 | 18-19 | 39 | 262 | 135 | 0.3 | 0.66 | 0.1 | apply mul_two_add_bit_lt_two_pow (c := ℓ - i) (a |
| 3 | 27-28 | 35 | 323 | 276 | 0.6 | 0.6 | 0.2 | set fiberMap := qMap_total_fiber 𝔽q β (i := ⟨i,  |
| 4 | 29 | 5 | 253 | 253 | 0.6 | 0.09 | 0.19 | set x₀ := fiberMap 0 |
| 5 | 30 | 5 | 256 | 256 | 0.6 | 0.09 | 0.19 | set x₁ := fiberMap 1 |
| 6 | 31 | 18 | 425 | 353 | 0.8 | 0.31 | 0.26 | set P_i := intermediateEvaluationPoly 𝔽q β h_ℓ_a |
| 7 | 32-47 | 87 | 2269 | 631 | 1.4 | 1.48 | 0.47 | set new_coeffs := fun j : Fin (2^(ℓ - (i + 1)))  |
| 8 | 34 | 0 | 448 | 139 | 0.3 | 0.0 | 0.1 | . have h : j.val * 2 < 2^(ℓ - (i + 1)) * 2 := by o |
| 9 | 34 | 23 | 309 | 309 | 0.7 | 0.39 | 0.23 | . . have h : j.val * 2 < 2^(ℓ - (i + 1)) * 2 := by o |
| 10 | 35-40 | 76 | 559 | 230 | 0.5 | 1.29 | 0.17 | . have h2 : 2^(ℓ - i) = 2^(ℓ - (i + 1)) * 2 := by |
| 11 | 41 | 1 | 376 | 376 | 0.8 | 0.02 | 0.28 | . omega |
| 12 | 48-54 | 82 | 657 | 156 | 0.3 | 1.39 | 0.12 | have h_eval_qMap_x₀ : (AdditiveNTT.qMap 𝔽q β ⟨i, |
| 13 | 56-62 | 82 | 633 | 160 | 0.4 | 1.39 | 0.12 | have h_eval_qMap_x₁ : (AdditiveNTT.qMap 𝔽q β ⟨i, |
| 14 | 69-111 | 105 | 18701 | 93 | 0.2 | 1.79 | 0.07 | have h_fiber_diff : x₁.val - x₀.val = 1 := by |
| 15 | 71 | 6 | 317 | 317 | 0.7 | 0.1 | 0.23 | . rw [hx₁, hx₀] |
| 16 | 72 | 9 | 236 | 236 | 0.5 | 0.15 | 0.17 | . simp only [Fin.isValue, AddSubmonoidClass.coe_fi |
| 17 | 73 | 0 | 458 | 122 | 0.3 | 0.0 | 0.09 | . have h_index : ℓ + 𝓡 - i = (ℓ + 𝓡 - (i.val + 1)) |
| 18 | 73 | 25 | 336 | 336 | 0.7 | 0.43 | 0.25 | . . have h_index : ℓ + 𝓡 - i = (ℓ + 𝓡 - (i.val + 1)) |
| 19 | 74 | 10 | 507 | 507 | 1.1 | 0.17 | 0.38 | . rw! (castMode := .all) [h_index] |
| 20 | 75 | 6 | 534 | 534 | 1.2 | 0.1 | 0.4 | . rw [Fin.sum_univ_succ, Fin.sum_univ_succ] -- (fr |
| 21 | 77-78 | 27 | 1419 | 1419 | 3.1 | 0.46 | 1.05 | . simp only [fiber_coeff, eqRec_eq_cast, lt_one_if |
| 22 | 79-85 | 77 | 629 | 136 | 0.3 | 1.31 | 0.1 | . have h_cast_0 : |
| 23 | 86-93 | 79 | 542 | 136 | 0.3 | 1.34 | 0.1 | . have h_cast_1 : |
| 24 | 94 | 8 | 275 | 275 | 0.6 | 0.14 | 0.2 | . simp only [h_cast_0, ↓reduceDIte] |
| 25 | 99 | 14 | 321 | 321 | 0.7 | 0.24 | 0.24 | . simp only [h_getBit_0_of_1, one_ne_zero, ↓reduce |
| 26 | 100 | 11 | 819 | 819 | 1.8 | 0.19 | 0.61 | . rw! (castMode := .all) [←h_index] |
| 27 | 101 | 4 | 494 | 494 | 1.1 | 0.07 | 0.37 | . rw [cast_eq] |
| 28 | 102 | 13 | 1408 | 1408 | 3.1 | 0.22 | 1.04 | . simp only [get_sDomain_basis, Fin.coe_ofNat_eq_m |
| 29 | 103 | 6 | 563 | 563 | 1.2 | 0.1 | 0.42 | . rw [normalizedWᵢ_eval_βᵢ_eq_1 𝔽q β] |
| 30 | 104 | 1 | 8678 | 8678 | 19.1 | 0.02 | 6.42 | . ring_nf |
| 31 | 107 | 2 | 313 | 313 | 0.7 | 0.03 | 0.23 | . congr 1 |
| 32 | 110-111 | 26 | 751 | 751 | 1.6 | 0.44 | 0.56 | . simp only [mem_univ, congr_eqRec, Fin.val_succ,  |
| 33 | 112-113 | 20 | 602 | 558 | 1.2 | 0.34 | 0.41 | set P_i_plus_1 := |
| 34 | 115-119 | 58 | 1971 | 746 | 1.6 | 0.99 | 0.55 | set P₀_coeffs := fun j : Fin (2^(ℓ - (i + 1))) = |
| 35 | 116 | 0 | 421 | 134 | 0.3 | 0.0 | 0.1 | . have h1 : ℓ - (i + 1) + 1 = ℓ - i := by omega |
| 36 | 116 | 19 | 287 | 287 | 0.6 | 0.32 | 0.21 | . . have h1 : ℓ - (i + 1) + 1 = ℓ - i := by omega |
| 37 | 118 | 36 | 238 | 207 | 0.5 | 0.61 | 0.15 | . have h3 : 2^(ℓ - (i + 1)) * 2 = 2^(ℓ - (i + 1) + |
| 38 | 119 | 11 | 325 | 325 | 0.7 | 0.19 | 0.24 | . rw [← h2, ← h3]; omega⟩ |
| 39 | 120-124 | 60 | 1820 | 770 | 1.7 | 1.02 | 0.57 | set P₁_coeffs := fun j : Fin (2^(ℓ - (i + 1))) = |
| 40 | 121 | 19 | 278 | 134 | 0.3 | 0.32 | 0.1 | . have h1 : ℓ - (i + 1) + 1 = ℓ - i := by omega |
| 41 | 123 | 36 | 238 | 207 | 0.5 | 0.61 | 0.15 | . have h3 : 2^(ℓ - (i + 1)) * 2 = 2^(ℓ - (i + 1) + |
| 42 | 124 | 11 | 328 | 328 | 0.7 | 0.19 | 0.24 | . rw [← h2, ← h3]; omega⟩ |
| 43 | 125 | 9 | 393 | 393 | 0.9 | 0.15 | 0.29 | set P₀ := evenRefinement 𝔽q β h_ℓ_add_R_rate i c |
| 44 | 126 | 9 | 396 | 396 | 0.9 | 0.15 | 0.29 | set P₁ := oddRefinement 𝔽q β h_ℓ_add_R_rate i co |
| 45 | 135 | 27 | 895 | 845 | 1.9 | 0.46 | 0.63 | set f_i := fun (x : (sDomain 𝔽q β h_ℓ_add_R_rate |
| 46 | 136 | 30 | 727 | 666 | 1.5 | 0.51 | 0.49 | set f_i_plus_1 := fold (i := ⟨i, by omega⟩) (h_i |
| 47 | 138-140 | 37 | 283 | 283 | 0.6 | 0.63 | 0.21 | have h_fold_def : f_i_plus_1 y = |
| 48 | 142-184 | 292 | 10144 | 1203 | 2.6 | 4.96 | 0.89 | calc f_i_plus_1 y |
| 49 | 152 | 17 | 426 | 426 | 0.9 | 0.29 | 0.32 | . x₁.val * (r_chal - (1 - r_chal) * x₀.val)) := by |
| 50 | 154 | 15 | 369 | 369 | 0.8 | 0.26 | 0.27 | . P₁.eval y.val * ((x₁.val - x₀.val) * r_chal) :=  |
| 51 | 157-158 | 17 | 283 | 283 | 0.6 | 0.29 | 0.21 | . simp only [P_i_plus_1, P₀, P₁, new_coeffs, evenR |
| 52 | 162 | 5 | 480 | 480 | 1.1 | 0.09 | 0.36 | . rw [←Polynomial.eval_add] |
| 53 | 164 | 1 | 3199 | 3199 | 7.0 | 0.02 | 2.37 | . congr |
| 54 | 165 | 7 | 501 | 501 | 1.1 | 0.12 | 0.37 | . simp_rw [mul_sum, ←Finset.sum_add_distrib] |
| 55 | 172-176 | 49 | 757 | 339 | 0.7 | 0.83 | 0.25 | . conv_lhs => enter [1]; rw [mul_comm (a := Polyno |
| 56 | 174-175 | 46 | 381 | 152 | 0.3 | 0.78 | 0.11 | . . apply mul_two_add_bit_lt_two_pow (c := ℓ - i) (a |
| 57 | 177-180 | 37 | 494 | 238 | 0.5 | 0.63 | 0.18 | . conv_lhs => enter [2]; rw [mul_comm (a := Polyno |
| 58 | 178-179 | 46 | 256 | 153 | 0.3 | 0.78 | 0.11 | . . apply mul_two_add_bit_lt_two_pow (c := ℓ - i) (a |
| 59 | 182 | 5 | 509 | 509 | 1.1 | 0.09 | 0.38 | . rw [←mul_add] |
| 60 | 183 | 1 | 916 | 916 | 2.0 | 0.02 | 0.68 | . congr |

(tokens on lines outside any tactic span: 378; total 2219 vs ref 1906)

Top-3 hb: #30 L104 8678 (19.1%); #53 L164 3199 (7.0%); #21 L77-78 1419 (3.1%)

Top-3 tokens: #48 L142-184 292; #14 L69-111 105; #7 L32-47 87

Best submitted (v3): 258 tokens; hb 6766 on v4.31.0, tok% 86.46, hb% 85.06, cov% 100.0, proxy 90.51 (cand fold_ds); needs one profile compile.

## interleaved_affine_gaps_imply_tensor_gaps

Reference: 1353 tokens, 9198 hb (official denominators); measured on v4.31.0; profile interleaved_affine_gaps_imply_tensor_gaps-c1712f6c496d-33cf5d7d83c6.json (current), measured total 9281, profiled 8402, floor 698. Rates: 0.025 pts/token, 0.362 pts/100 hb, 11.11 pts/lost version (3 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 9-177 | 3 | 8402 | 15 | 0.2 | 0.08 | 0.05 | classical |
| 2 | 11-177 | 14 | 8387 | 5 | 0.1 | 0.35 | 0.02 | . induction ϑ with |
| 3 | 16-177 | 141 | 8371 | 34 | 0.4 | 3.53 | 0.12 | . . cases ϑ_sub_1 with |
| 4 | 19 | 13 | 93 | 93 | 1.0 | 0.33 | 0.34 | . . . simp only [zero_add, gt_iff_lt, zero_lt_one, Mod |
| 5 | 21 | 14 | 71 | 71 | 0.8 | 0.35 | 0.26 | . . . let toAffineLineEval := multilinearCombine₁_eq_a |
| 6 | 23 | 6 | 57 | 57 | 0.6 | 0.15 | 0.21 | . . . simp_rw [toAffineLineEval] at hprob_gt |
| 7 | 24-25 | 33 | 667 | 667 | 7.2 | 0.83 | 2.41 | . . . let prob_eq := prob_uniform_singleton_finFun_eq  |
| 8 | 27 | 12 | 181 | 181 | 2.0 | 0.3 | 0.66 | . . . simp_rw [prob_eq, Nat.cast_one, ENNReal.coe_one, |
| 9 | 30-34 | 18 | 204 | 35 | 0.4 | 0.45 | 0.13 | . . . have h_u_eq: u = finMapTwoWords (u 0) (u 1) := b |
| 10 | 32-34 | 11 | 164 | 164 | 1.8 | 0.28 | 0.59 | . . . . match rowIdx with |
| 11 | 44-45 | 30 | 223 | 223 | 2.4 | 0.75 | 0.81 | . . . set U₀ : Fin (2 ^ (ϑ_sub_2 + 1)) → Word A ι := |
| 12 | 46-47 | 30 | 226 | 226 | 2.4 | 0.75 | 0.82 | . . . set U₁ : Fin (2 ^ (ϑ_sub_2 + 1)) → Word A ι := |
| 13 | 51-63 | 77 | 553 | 70 | 0.8 | 1.93 | 0.25 | . . . have h_finsnoc_eq_r: ∀ r: Fin (ϑ_sub_2 + 1 + 1)  |
| 14 | 58-63 | 74 | 440 | 440 | 4.7 | 1.85 | 1.59 | . . . . · have h_i_ne_last: i ≠ Fin.last (ϑ_sub_2 + 1) : |
| 15 | 64-65 | 42 | 339 | 339 | 3.7 | 1.05 | 1.23 | . . . let P : F → (Fin (ϑ_sub_2 + 1) → F) → Prop := fu |
| 16 | 66-67 | 21 | 317 | 317 | 3.4 | 0.53 | 1.15 | . . . let hP_split_r_last := prob_split_last_uniform_s |
| 17 | 69 | 6 | 79 | 79 | 0.9 | 0.15 | 0.29 | . . . simp_rw [h_finsnoc_eq_r] at hP_split_r_last |
| 18 | 99-104 | 42 | 265 | 181 | 2.0 | 1.05 | 0.66 | . . . have multilinearCombine_snoc_eq_multilinearCombi |
| 19 | 102 | 4 | 54 | 54 | 0.6 | 0.1 | 0.2 | . . . . rw [multilinearCombine_recursive_form] |
| 20 | 106-107 | 6 | 76 | 76 | 0.8 | 0.15 | 0.28 | . . . simp_rw [multilinearCombine_snoc_eq_multilinearC |
| 21 | 112 | 22 | 53 | 53 | 0.6 | 0.55 | 0.19 | . . . let R_star_set := R_star_tensor MC (m:=ϑ_pred) ( |
| 22 | 114-118 | 35 | 506 | 434 | 4.7 | 0.88 | 1.57 | . . . have h_prob_Rstar_gt_eps_div_q : Pr_{ let r ← $ᵖ |
| 23 | 116-117 | 34 | 54 | 54 | 0.6 | 0.85 | 0.2 | . . . . let res := prob_R_star_gt_threshold (MC := MC) ( |
| 24 | 120-132 | 29 | 857 | 12 | 0.1 | 0.73 | 0.04 | . . . have h_R_star_card_gt_eps : R_star_set.card > ε  |
| 25 | 121 | 6 | 45 | 45 | 0.5 | 0.15 | 0.16 | . . . . rw [prob_uniform_eq_card_filter_div_card] at h_p |
| 26 | 124-129 | 72 | 500 | 500 | 5.4 | 1.8 | 1.81 | . . . . have h_cancel_q_denom := ENNReal.div_lt_div_iff_ |
| 27 | 131 | 9 | 242 | 242 | 2.6 | 0.23 | 0.88 | . . . . simp only [filter_univ_mem, Nat.cast_lt] at h_pr |
| 28 | 134-139 | 33 | 290 | 165 | 1.8 | 0.83 | 0.6 | . . . have h_line_close_to_C_m : ∀ (r : R_star_set), |
| 29 | 138-139 | 20 | 125 | 125 | 1.3 | 0.5 | 0.45 | . . . . apply correlatedAgreement_of_mem_R_star_tensor |
| 30 | 143-167 | 123 | 2724 | 1049 | 11.3 | 3.08 | 3.8 | . . . have h_prob_line_gt_eps_div_q : |
| 31 | 151-159 | 115 | 654 | 654 | 7.0 | 2.88 | 2.37 | . . . . have h_r_implies: ∀ (r : F), r ∈ R_star_set → |
| 32 | 160-165 | 116 | 957 | 957 | 10.3 | 2.9 | 3.46 | . . . . let Pr_le := Pr_le_Pr_of_implies (D := $ᵖ F) |
| 33 | 169-175 | 84 | 249 | 170 | 1.8 | 2.1 | 0.62 | . . . have h_final_gap : jointProximityNat₂ |
| 34 | 173-175 | 57 | 79 | 79 | 0.9 | 1.43 | 0.29 | . . . . apply h_C_m_gap (u₀ := ⋈/(show WordStack A (Fin  |

(tokens on lines outside any tactic span: 1; total 1353 vs ref 1353)

Top-3 hb: #30 L143-167 1049 (11.3%); #32 L160-165 957 (10.3%); #7 L24-25 667 (7.2%)

Top-3 tokens: #3 L16-177 141; #30 L143-167 123; #32 L160-165 116

Best submitted (v3): 225 tokens; hb 2571 on v4.31.0, tok% 83.37, hb% 72.05, cov% 100.0, proxy 85.14 (cand inter_ds); needs one profile compile.

## FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time

Reference: 1217 tokens, 42225 hb (official denominators); measured on v4.32.0; profile FieldSpecification.WickAlgebra.__timeOrderF_superCommuteF_eq_time-c48433678e8f-e7614c303183.json (current), measured total 42165, profiled 41272, floor 309. Rates: 0.027 pts/token, 0.079 pts/100 hb, 33.33 pts/lost version (1 versions).

| id | lines | tok | hb incl | self | share% | pts tok | pts hb | step |
|---|---|---|---|---|---|---|---|---|
| 1 | 5-7 | 57 | 405 | 405 | 1.0 | 1.54 | 0.32 | let pb (b : 𝓕.FieldOpFreeAlgebra) (hc : b ∈ Subm |
| 2 | 8 | 8 | 78 | 78 | 0.2 | 0.22 | 0.06 | change pb b (Basis.mem_span _ b) |
| 3 | 9 | 2 | 11 | 11 | 0.0 | 0.05 | 0.01 | apply Submodule.span_induction |
| 4 | 10-112 | 18 | 29512 | 5 | 0.0 | 0.49 | 0.0 | · rintro x ⟨φs, rfl⟩ |
| 5 | 11 | 9 | 607 | 607 | 1.4 | 0.24 | 0.48 | . simp only [ofListBasis_eq_ofList, map_mul, pb] |
| 6 | 12-14 | 59 | 405 | 405 | 1.0 | 1.59 | 0.32 | . let pa (a : 𝓕.FieldOpFreeAlgebra) (hc : a ∈ Subm |
| 7 | 17-107 | 33 | 16967 | 6 | 0.0 | 0.89 | 0.0 | . · rintro x ⟨φs', rfl⟩ |
| 8 | 18 | 9 | 611 | 611 | 1.4 | 0.24 | 0.48 | . . simp only [ofListBasis_eq_ofList, map_mul, pa] |
| 9 | 19-95 | 707 | 11285 | 1577 | 3.7 | 19.09 | 1.25 | . . calc _ |
| 10 | 26-30 | 27 | 2018 | 2018 | 4.8 | 0.73 | 1.59 | . . . conv_lhs => |
| 11 | 31 | 7 | 799 | 799 | 1.9 | 0.19 | 0.63 | . . . simp only [map_smul, sub_right_inj] |
| 12 | 32 | 1 | 302 | 302 | 0.7 | 0.03 | 0.24 | . . . module |
| 13 | 39 | 1 | 847 | 847 | 2.0 | 0.03 | 0.67 | . . . module |
| 14 | 62-63 | 13 | 272 | 21 | 0.0 | 0.35 | 0.02 | . . . have h1 := insertionSort_of_eq_list 𝓕.crAnTimeOr |
| 15 | 63 | 4 | 251 | 251 | 0.6 | 0.11 | 0.2 | . . . . (by simp_all) |
| 16 | 64 | 30 | 234 | 153 | 0.4 | 0.81 | 0.12 | . . . rw [crAnTimeOrderList, show φs' ++ φ :: ψ :: φs  |
| 17 | 65-66 | 13 | 825 | 22 | 0.1 | 0.35 | 0.02 | . . . have h2 := insertionSort_of_eq_list 𝓕.crAnTimeOr |
| 18 | 66 | 4 | 803 | 803 | 1.9 | 0.11 | 0.63 | . . . . (by simp_all) |
| 19 | 67 | 30 | 244 | 163 | 0.4 | 0.81 | 0.13 | . . . rw [crAnTimeOrderList, show φs' ++ ψ :: φ :: φs  |
| 20 | 68 | 0 | 523 | 40 | 0.1 | 0.0 | 0.03 | . . . repeat rw [ofCrAnListF_append] |
| 21 | 68 | 5 | 483 | 483 | 1.1 | 0.14 | 0.38 | . . . . repeat rw [ofCrAnListF_append] |
| 22 | 69 | 1 | 1113 | 1113 | 2.6 | 0.03 | 0.88 | . . . simp |
| 23 | 81 | 6 | 895 | 895 | 2.1 | 0.16 | 0.71 | . . . simp [mul_sub, sub_mul] |
| 24 | 92 | 1 | 394 | 394 | 0.9 | 0.03 | 0.31 | . . . congr |
| 25 | 95 | 5 | 1122 | 1122 | 2.7 | 0.14 | 0.89 | . . . simp [← ofCrAnListF_append] |
| 26 | 97 | 0 | 378 | 28 | 0.1 | 0.0 | 0.02 | . . repeat rw [mul_assoc] |
| 27 | 97 | 5 | 350 | 350 | 0.8 | 0.14 | 0.28 | . . . repeat rw [mul_assoc] |
| 28 | 98-99 | 20 | 636 | 636 | 1.5 | 0.54 | 0.5 | . . rw [← map_mul, ← map_mul, ← map_mul, ← ofCrAnLis |
| 29 | 101 | 13 | 1293 | 1293 | 3.1 | 0.35 | 1.02 | . . simp [decide_not, Bool.decide_and, List.append_a |
| 30 | 103 | 18 | 544 | 544 | 1.3 | 0.49 | 0.43 | . . by_cases hq : (𝓕 />ₛ φ) ≠ (𝓕 />ₛ ψ) |
| 31 | 104 | 0 | 676 | 0 | 0.0 | 0.0 | 0.0 | . . · simp [ι_superCommuteF_of_diff_statistic hq] |
| 32 | 104 | 6 | 676 | 676 | 1.6 | 0.16 | 0.53 | . . . · simp [ι_superCommuteF_of_diff_statistic hq] |
| 33 | 105-107 | 0 | 1295 | 1 | 0.0 | 0.0 | 0.0 | . . · rw [crAnTimeOrderSign, Wick.koszulSign_eq_rel_ |
| 34 | 105-106 | 8 | 514 | 309 | 0.7 | 0.22 | 0.24 | . . . · rw [crAnTimeOrderSign, Wick.koszulSign_eq_rel_ |
| 35 | 105 | 15 | 205 | 205 | 0.5 | 0.4 | 0.16 | . . . . · rw [crAnTimeOrderSign, Wick.koszulSign_eq_rel_ |
| 36 | 107 | 7 | 780 | 780 | 1.8 | 0.19 | 0.62 | . . . simp only [map_smul, Algebra.mul_smul_comm] |
| 37 | 108 | 0 | 1029 | 0 | 0.0 | 0.0 | 0.0 | . · simp only [map_mul, zero_mul, map_zero, mul_ze |
| 38 | 108 | 14 | 1029 | 1029 | 2.4 | 0.38 | 0.81 | . . · simp only [map_mul, zero_mul, map_zero, mul_ze |
| 39 | 109-110 | 8 | 5849 | 2 | 0.0 | 0.22 | 0.0 | . · intro x y hx hy hpx hpy |
| 40 | 110 | 8 | 5845 | 5845 | 13.9 | 0.22 | 4.62 | . . simp_all [pa,mul_add, add_mul] |
| 41 | 111-112 | 5 | 4522 | 1 | 0.0 | 0.14 | 0.0 | . · intro x hx hpx |
| 42 | 112 | 4 | 4520 | 4520 | 10.7 | 0.11 | 3.57 | . . simp_all [pa] |
| 43 | 113 | 0 | 1019 | 0 | 0.0 | 0.0 | 0.0 | · simp only [map_mul, mul_zero, map_zero, pb] |
| 44 | 113 | 12 | 1019 | 1019 | 2.4 | 0.32 | 0.81 | . · simp only [map_mul, mul_zero, map_zero, pb] |
| 45 | 114-115 | 8 | 5787 | 1 | 0.0 | 0.22 | 0.0 | · intro x y hx hy hpx hpy |
| 46 | 115 | 6 | 5784 | 5784 | 13.7 | 0.16 | 4.57 | . simp_all [pb,mul_add] |
| 47 | 116-117 | 5 | 4460 | 1 | 0.0 | 0.14 | 0.0 | · intro x hx hpx |
| 48 | 117 | 4 | 4458 | 4458 | 10.6 | 0.11 | 3.52 | . simp_all [pb] |

(tokens on lines outside any tactic span: 1; total 1217 vs ref 1217)

Top-3 hb: #40 L110 5845 (13.9%); #46 L115 5784 (13.7%); #42 L112 4520 (10.7%)

Top-3 tokens: #9 L19-95 707; #6 L12-14 59; #1 L5-7 57

Best submitted (v3): 590 tokens; hb 10463 on v4.32.0, tok% 51.52, hb% 75.22, cov% 100.0, proxy 75.58 (cand field_v6ark2); needs one profile compile.