theorem InitsUpdatesComm
  {P : PureExpr} {σ σ' σ'' : SemanticStore P}
  {ks ks' : List P.Ident} {vs vs' : List P.Expr} :
  UpdateStates σ ks vs σ' →
  InitStates σ' ks' vs' σ'' →
  ∃ σ₁,
    σ₁ = (updatedStates σ ks' vs') ∧
    InitStates σ ks' vs' σ₁ ∧
    UpdateStates σ₁ ks vs σ'' := by
  intros Hup Hinit
  refine ⟨_, rfl, ?_⟩
  have Hlen1 := InitStatesLength Hinit
  induction Hup generalizing σ''
  case update_none =>
    constructor
    · exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)
    · rw [InitStatesUpdated Hinit]
      constructor
  case update_some σ x v σ₀ xs vs σ₁ Hup Hups ih =>
    have hn := UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup
    have hnd := InitStatesNodup Hinit
    refine ⟨updatedStatesInit Hlen1 hn hnd, ?_⟩
    apply UpdateStates.update_some (σ':=updatedStates σ₀ ks' vs')
    · simp [UpdateStateUpdated Hup, updatedStates]
      cases Hup with
      | update h _ _ =>
        rw [← updatedStateComm']
        · exact updatedStateUpdate (InitStatesSomeMonotone h (updatedStatesInit Hlen1 hn hnd))
        · rw [List.unzip_zip Hlen1]
          exact fun hx => by simpa [h] using hn x hx
    · exact (ih Hinit).2