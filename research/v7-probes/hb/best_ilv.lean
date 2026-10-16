theorem interleaved_affine_gaps_imply_tensor_gaps
    (hC_proximityGapAffineLines : e_ε_correlatedAgreementAffineLinesNat
      (F := F) (A := A) (ι := ι) (C := MC) (e := e) (ε := ε))
    (h_interleaved_gaps : ∀ m : ℕ, m ≥ 1 →
      e_ε_correlatedAgreementAffineLinesNat (F := F)
        (A := InterleavedSymbol A (Fin m)) (ι := ι) (C := MC ^⋈ (Fin m)) e ε) :
    ∀ (ϑ : ℕ), (hϑ_gt_0 : ϑ > 0) → δ_ε_multilinearCorrelatedAgreement_Nat (F := F) (A := A)
      (ι := ι) (C := MC) (ϑ := ϑ) (e := e) (ε := ε) := by
  intro ϑ hϑ
  obtain ⟨n, rfl⟩ := Nat.exists_eq_succ_of_ne_zero hϑ.ne'
  clear hϑ
  induction n
  case zero =>
    intro u hP
    simp only [multilinearCombine₁_eq_affineLineEvaluation (F := F) u, Nat.cast_one,
      ENNReal.coe_one, one_mul] at hP
    rw [prob_uniform_singleton_finFun_eq (F := F)
        (fun r => Δ₀(affineLineEvaluation (u 0) (u 1) r, MC) ≤ e)] at hP
    have h2 : finMapTwoWords (u 0) (u 1) = u := by funext i; fin_cases i <;> rfl
    exact h2 ▸ hC_proximityGapAffineLines (u 0) (u 1) hP
  case succ k ih =>
    intro u hP
    have hsplit := prob_split_last_uniform_sampling_of_finFun (F := F)
      (fun r_last r_init => Δ₀(multilinearCombine u (Fin.snoc r_init r_last), MC) ≤ e)
    simp only [← Fin.init_def, Fin.snoc_init_self] at hsplit
    rw [hsplit] at hP
    simp only [multilinearCombine_recursive_form (u := u), Fin.snoc_last, Fin.init_snoc] at hP
    apply CA_split_rowwise_implies_CA (u := u) (C := MC)
    apply h_interleaved_gaps _ Nat.one_le_two_pow
    refine lt_of_le_of_lt' (Pr_le_Pr_of_implies _ _ _ ?_)
      (prob_R_star_gt_threshold MC u _ hP)
    intro r hr
    exact correlatedAgreement_of_mem_R_star_tensor MC ih u ⟨r, hr⟩