theorem putnam_1964_a4
(u : ℕ → ℤ)
(boundedu : ∃ B T : ℤ, ∀ n : ℕ, B ≤ u n ∧ u n ≤ T)
(hu : ∀ n ≥ 4, u n = ((u (n - 1) + u (n - 2) + u (n - 3) * u (n - 4)) : ℝ) / (u (n - 1) * u (n - 2) + u (n - 3) + u (n - 4)) ∧ (u (n - 1) * u (n - 2) + u (n - 3) + u (n - 4)) ≠ 0)
: (∃ N c : ℕ, c > 0 ∧ ∀ n ≥ N, u (n + c) = u n) := by
  obtain ⟨B, T, hB⟩ := boundedu
  let f n := (u n, u (n + 1), u (n + 2), u (n + 3))
  have hBT := Set.finite_Icc B T
  obtain ⟨i, j, hij, hfij⟩ := Set.Finite.exists_lt_map_eq_of_forall_mem (f := f) (Set.mem_range_self ·) (by
    apply Set.Finite.subset (hBT.prod (hBT.prod (hBT.prod hBT)))
    rintro _ ⟨n, rfl⟩
    simp only [f, Set.mem_prod, Set.mem_Icc]
    exact ⟨hB n, hB (n + 1), hB (n + 2), hB (n + 3)⟩)
  have hper : ∀ m, f (i + m) = f (j + m) := by
    intro m
    induction m with
    | zero => simpa using hfij
    | succ m ih =>
      simp [f] at ih ⊢
      obtain ⟨e0, e1, e2, e3⟩ := ih
      refine ⟨e1, e2, e3, ?_⟩
      show u (i + m + 4) = u (j + m + 4)
      exact Int.cast_injective (α := ℝ) (by simp [e0, e1, e2, e3, hu (i + m + 4) (by omega), hu (j + m + 4) (by omega)])
  refine ⟨i, j - i, by omega, fun n hn => ?_⟩
  have h := congrArg Prod.fst (hper (n - i))
  rw [Nat.add_sub_of_le hn, show j + (n - i) = n + (j - i) by omega] at h
  exact h.symm