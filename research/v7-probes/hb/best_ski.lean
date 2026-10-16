theorem parallelReduction_diamond : Diamond ParallelReduction := by
  haveI : Std.Refl ParallelReduction := ⟨.refl⟩
  intro a a₁ a₂ h₁ h₂
  induction h₁ generalizing a₂
  use a₂, h₂, .refl a₂
  cases h₂
  exact ⟨_, .refl _, .red_I ..⟩
  exact Std.Refl.refl _
  rename_i d ha hb
  cases ha; use d, hb, .red_I ..
  cases h₂
  exact ⟨_, .refl _, .red_K ..⟩
  exact Std.Refl.refl _
  rename_i ha hb
  cases Ka_irreducible _ _ ha
  rename_i u h
  cases h.2
  use u, h.1, .red_K ..
  cases h₂
  exact ⟨_, .refl _, .red_S ..⟩
  exact Std.Refl.refl _
  rename_i hd he
  obtain ⟨u, v, h⟩ := Sab_irreducible _ _ _ hd
  cases h.2.2
  exact ⟨_, (h.1.par he).par (h.2.1.par he), .red_S ..⟩
  rename_i b' ha hb iha ihb
  cases h₂
  exact ⟨_, .refl _, ha.par hb⟩
  cases ha; use b', .red_I b'
  cases Ka_irreducible _ _ ha
  rename_i u h
  cases h.2
  use u, .red_K .., h.1
  obtain ⟨u, v, h⟩ := Sab_irreducible _ _ _ ha
  cases h.2.2
  exact ⟨_, .red_S .., (h.1.par hb).par (h.2.1.par hb)⟩
  rename_i ha₂ hb₂
  cases iha ha₂
  rename_i hc
  cases ihb hb₂
  rename_i hd
  exact ⟨_, hc.1.par hd.1, hc.2.par hd.2⟩