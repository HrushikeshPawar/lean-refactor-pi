theorem fold_advances_evaluation_poly
  (i : Fin (ℓ)) (h_i_succ_lt : i + 1 < ℓ + 𝓡)
  (coeffs : Fin (2 ^ (ℓ - ↑i)) → L) (r_chal : L) :
  let P_i : L[X] := intermediateEvaluationPoly 𝔽q β h_ℓ_add_R_rate (i := ⟨i, by
    exact Nat.lt_trans (n := i) (k := ℓ+1) (m := ℓ) (h₁ := i.isLt) (by exact Nat.lt_add_one ℓ)
  ⟩) coeffs
  let f_i := fun (x : (sDomain 𝔽q β h_ℓ_add_R_rate)
      ⟨i, by exact Nat.lt_trans (n := i) (k := r) (m := ℓ) (h₁ := by omega) (by omega)⟩) =>
    P_i.eval (x.val : L)
  let f_i_plus_1 := fold (i := ⟨i, by omega⟩) (h_i := by omega) (f := f_i) (r_chal := r_chal)
  let new_coeffs := fun j : Fin (2^(ℓ - (i + 1))) =>
    (1 - r_chal) * (coeffs ⟨j.val * 2, by
      rw [←Nat.add_zero (j.val * 2)]
      apply mul_two_add_bit_lt_two_pow (c := ℓ - i) (a := j) (b := ℓ - (↑i + 1))
        (i := 0) (by omega) (by omega)
    ⟩) +
    r_chal * (coeffs ⟨j.val * 2 + 1, by
      apply mul_two_add_bit_lt_two_pow (c := ℓ - i) (a := j) (b := ℓ - (↑i + 1))
        (i := 1) (by omega) (by omega)
    ⟩)
  let P_i_plus_1 :=
    intermediateEvaluationPoly 𝔽q β h_ℓ_add_R_rate (i := ⟨i+1, by omega⟩) new_coeffs
  ∀ (y : (sDomain 𝔽q β h_ℓ_add_R_rate)
    ⟨i+1, by omega⟩), f_i_plus_1 y = P_i_plus_1.eval y.val := by
  intro P_i f_i f_i_plus_1 new_coeffs P_i_plus_1 y
  unfold f_i_plus_1 fold f_i
  set F := qMap_total_fiber 𝔽q β ⟨i, by omega⟩ 1 h_i_succ_lt y
  have hq (k) : (AdditiveNTT.qMap 𝔽q β ⟨i, by omega⟩).eval (F k).val = y :=
    Subtype.ext_iff.mp ((iteratedQuotientMap_k_eq_1_is_qMap (x := F k)).symm.trans
      (generates_quotient_point_if_is_fiber_of_y 𝔽q β i 1 i.isLt (F k) y ⟨k, rfl⟩).symm)
  have h_fiber_diff : (F 1).val - (F 0).val = 1 := by
    have h0 := qMap_total_fiber_one_level_eq 𝔽q β i i.isLt y 0
    have h1 := qMap_total_fiber_one_level_eq 𝔽q β i i.isLt y 1
    simp only [F, h1, h0, Submodule.coe_add, Fin2ToF2, if_true, if_neg Fin.zero_ne_one'.symm,
      one_smul, zero_smul, zero_add, add_sub_cancel_right, get_sDomain_basis, add_zero,
      normalizedWᵢ_eval_βᵢ_eq_1]
  have h_split : P_i = _ := evaluation_poly_split_identity 𝔽q β h_ℓ_add_R_rate i coeffs
  have h_coeff : P_i_plus_1 =
      Polynomial.C (1 - r_chal) * evenRefinement 𝔽q β h_ℓ_add_R_rate i coeffs +
        Polynomial.C r_chal * oddRefinement 𝔽q β h_ℓ_add_R_rate i coeffs := by
    unfold P_i_plus_1 new_coeffs evenRefinement oddRefinement intermediateEvaluationPoly
    simp only [Finset.mul_sum, ← Finset.sum_add_distrib]
    apply Finset.sum_congr rfl
    intro j _
    simp only [Polynomial.C_add, Polynomial.C_mul, add_mul, mul_assoc]
  simp only [h_split, h_coeff, Polynomial.eval_add, Polynomial.eval_comp, Polynomial.eval_mul,
    Polynomial.eval_X, Polynomial.eval_C]
  rw [hq 0, hq 1, sub_eq_iff_eq_add'.mp h_fiber_diff]
  ring