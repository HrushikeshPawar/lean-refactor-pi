# Route fingerprint from the compiled proof term: validation on stored history

Generated with `tools/route_validation.py` (`collect`, `extract`, `report`, `robust`). Raw data:
`runs/analysis/route-validation/` (`proofs.jsonl`, `features.jsonl` = per-proof kernel features, `clusters.json`,
`robustness.jsonl`, `disagreements.json`, `routes.md`). Local Lean only; no model or API call was made.

## What was validated

- Collected every compiled model candidate (any evaluation whose per-version compile results all passed) from the 62 run
  ledgers under `runs/pi-budget/*/` (`proofs/<id>.lean`), each theorem's original, `runs/analysis/*.lean` hybrids and
  scratch files, `runs/baseline`, `runs/p0`, and `runs/submission-staging`. Deduped by comment-stripped,
  whitespace-normalised text: **352 distinct proofs** over 15 theorems.
- Compiled each in the theorem's measure-version workspace (batches of 10 per Lean process, 3 processes in parallel,
  `arena_route` restores the environment after each proof, so no renaming is needed) and read the kernel value.
  **334 proofs extracted**, 18 did not (below); only 5 theorems have more than 3 proofs, because every stored run
  covers Core.InitsUpdatesComm, the two CallElimCorrect rows, the CCS row and the PhysLib variational row.
- Same fingerprint code path as the harness (`routes.fingerprint`, `routes.assign`, `routes.label`), replayed in arrival
  order: original first, then runs in name order. OLD = the previous text fingerprint (induction veto, kickoff-vocabulary
  lemmas, best match over all earlier proofs), reproduced in `tools/route_validation.py:old_cluster`.

## Per-theorem result (threshold 0.5)

| theorem | proofs | old routes | new routes | old sizes | new sizes | new routes at 0.4/0.5/0.6 |
|---|---|---|---|---|---|---|
| CallElimCorrect.extractedOldExprInVars | 36 | 1 | 2 | [36] | [26, 10] | 1/2/2 |
| CallElimCorrect.substOldPostSubset | 15 | 1 | 2 | [15] | [14, 1] | 2/2/2 |
| Core.InitsUpdatesComm | 207 | 2 | 2 | [183, 24] | [183, 24] | 2/2/3 |
| Cslib.CCS.bisimilarity_congr_choice | 37 | 1 | 1 | [37] | [37] | 1/1/1 |
| fundamental_theorem_of_variational_calculus' | 36 | 1 | 2 | [36] | [22, 14] | 2/2/3 |
| putnam_1964_a4 | 1 | 1 | 1 | [1] | [1] | 1/1/1 |
| putnam_1964_b2 | 1 | 1 | 1 | [1] | [1] | 1/1/1 |
| putnam_1995_a3 | 1 | 1 | 1 | [1] | [1] | 1/1/1 |

The last column is the number of NEW routes with `SAME_ROUTE` = 0.4 / 0.5 / 0.6. Singleton rows are originals only.

### Routes and representative proofs (NEW)

### CallElimCorrect.extractedOldExprInVars

- **r1**: 10 proofs (pre-v5 1, v5 9); label: `recursion: Lambda.LExpr.rec; CallElimCorrect.List.Subset.app, CallElimCorrect.List.Subset.trans, Core.CoreIdent`
  - `e058b3680d404ab5` (benchmark):

```lean
 by
  intros Hnorm
  induction post <;>
    simp [Imperative.HasVarsPure.getVars, extractOldExprVars,
          Lambda.LExpr.LExpr.getVars] at * <;>
    try simp_all
  case app fn e fn_ih e_ih =>
  ...
```

  - `81ceb7c5366d6039` (v5-gen-20261007-extract-model-gpt-6-luna):

```lean
 by
  intros Hnorm
  induction post <;>
    simp [Imperative.HasVarsPure.getVars, extractOldExprVars,
          Lambda.LExpr.LExpr.getVars] at * <;>
    try simp_all
  case app fn e fn_ih e_ih =>
  ...
```

- **r2**: 26 proofs (v5 10, hybrid 17); label: `recursion: Core.OldExpressions.NormalizedOldExpr.rec instead of Lambda.LExpr.rec; +List.Subset.empty +List.Subset.refl +List.Subset.subset_app_of_or_2 −CallElimCorrect.List.Subset.trans −Core.OldExpressions.NormalizedOldExpr.abs −Core.OldExpressions.NormalizedOldExpr.app`
  - `75b9780d1a8e6307` (v5-gen-20261007-extract-model-gpt-6-luna):

```lean
 by
  intro H
  induction H <;> try exact List.Subset.empty <;>
    simp only [Imperative.HasVarsPure.getVars, extractOldExprVars, Lambda.LExpr.LExpr.getVars] at *
  case abs => assumption
  case quant tr e x y | eq tr e x y =>
    apply List.Subset.app
  ...
```

  - `c6eb5ee6c7fd0ac2` (v5-gen-20261007-extract-model-gpt-6-luna):

```lean
 by
  intro H
  induction H <;> try exact .empty <;>
    simp only [Imperative.HasVarsPure.getVars, extractOldExprVars, Lambda.LExpr.LExpr.getVars] at *
  case abs => assumption
  case quant tr e x y | eq tr e x y =>
    apply List.Subset.app
  ...
```


### CallElimCorrect.substOldPostSubset

- **r1**: 14 proofs (pre-v5 1, v5 13); label: `recursion: Lambda.LExpr.rec; CallElimCorrect.List.Subset.app, CallElimCorrect.List.Subset.trans, Core.CoreIdent`
  - `c5ed57536e66f678` (benchmark):

```lean
 by
  induction post <;> simp [substOld]
  case fvar =>
    intros x Hin
    rename_i m name ty2
    simp at m
    simp at name
  ...
```

  - `dfc224c4578d075a` (v5-gen-20261007-subst-model-gpt-6-luna):

```lean
 by
  induction post <;> simp only [substOld]
  all_goals simp [Imperative.HasVarsPure.getVars, Lambda.LExpr.LExpr.getVars] at *
  case fvar => simp [List.Subset]
  case abs ih => exact ih
  case ite cih tih eih =>
    apply List.Subset.app
  ...
```

- **r2**: 1 proofs (hybrid 1); label: `+Bool.not_eq_true +Lean.Grind.MatchCond +Lean.Grind.PreMatchCond −ite_congr −CallElimCorrect.List.Subset.app −CallElimCorrect.List.Subset.trans`
  - `7bac67f1397ed32f` (analysis/CallElimCorrect_substOldPostSubset-hybrid-82.86.lean):

```lean
 by
  dsimp [Imperative.HasVarsPure.getVars]
  intro x
  induction post <;> dsimp only [substOld] <;> repeat' split
  all_goals dsimp only [Lambda.LExpr.LExpr.getVars]; grind
```


### Core.InitsUpdatesComm

- **r1**: 183 proofs (pre-v5 104, naive 3, v5 69, v6 9); label: `recursion: Core.UpdateStates.rec; Core.InitStatesLength, Core.InitStatesNodup, Core.InitStatesNotDefined`
  - `c9296a9d193833b4` (benchmark):

```lean
 by
  intros Hup Hinit
  exists (updatedStates σ ks' vs')
  have Hk : (isDefined σ' ks) := UpdateStatesDefined Hup
  have Hlen1 := InitStatesLength Hinit
  have Hlen2 := UpdateStatesLength Hup
  induction Hup generalizing σ''
  ...
```

  - `d8ec30e2c29f2b50` (inits-luna-source-20261005-01):

```lean
 by
  intros Hup Hinit
  exists (updatedStates σ ks' vs')
  have Hk : (isDefined σ' ks) := UpdateStatesDefined Hup
  have Hlen1 := InitStatesLength Hinit
  have Hlen2 := UpdateStatesLength Hup
  induction Hup generalizing σ''
  ...
```

- **r2**: 24 proofs (v5 12, v6 11, pre-v5 1, hybrid 1); label: `recursion: none instead of Core.UpdateStates.rec; +Core.UpdateStatesUpdated +Core.updatedStatesComm +Core.updatedStatesDefMonotone −Option.casesOn −Core.UpdateStateNotDefMonotone −Imperative.isNotDefined`
  - `aed353370e54760a` (v5-accept-20261006-r2-model-qwen3.8-flash):

```lean
 by
  intros Hup Hinit
  have Hl := InitStatesLength Hinit
  have Hw := UpdateStatesLength Hup
  refine ⟨updatedStates σ ks' vs', rfl, ?_, ?_⟩
  · exact updatedStatesInit Hl (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hup) (InitStatesNodup
  · have Hdis : List.Disjoint ks ks' := by
  ...
```

  - `4cdbdca41de22b5b` (v5-accept-20261006-r2-model-qwen3.8-flash):

```lean
 by
  intros Hup Hinit
  have Hdis : List.Disjoint ks ks' := fun k hk hk' =>
    absurd (UpdateStatesDefined Hup k hk) (by rw [InitStatesNotDefined Hinit k hk']; simp)
  have Hz : List.Disjoint (List.zip ks vs).unzip.1 (List.zip ks' vs').unzip.1 := by
    rwa [List.unzip_zip (UpdateStatesLength Hup), List.unzip_zip (InitStatesLength Hinit)]
  refine ⟨updatedStates σ ks' vs', rfl,
  ...
```


### Cslib.CCS.bisimilarity_congr_choice

- **r1**: 37 proofs (pre-v5 1, v5 33, hybrid 5); label: `recursion: none; Cslib.CCS.Act.coname, Cslib.CCS.Act.name, Cslib.CCS.Act.τ`
  - `68a4eff7bfb32732` (benchmark):

```lean
 by
  intro h
  exists @ChoiceBisim _ _ defs
  constructor
  · constructor; assumption
  intro s1 s2 r μ
  constructor
  ...
```

  - `077103dd86b15991` (v5-gen-20261007-cslib-model-gpt-6-luna):

```lean
 by
  intro h
  use @ChoiceBisim _ _ defs, .choice h
  intro s1 s2 rel μ
  constructor
  · intro s1' htr
    cases rel
  ...
```


### fundamental_theorem_of_variational_calculus'

- **r1**: 22 proofs (pre-v5 1, v5 9, v6 12); label: `recursion: none; Classical.not_forall, Classical.propDecidable, ContDiff.continuous`
  - `33784c36cef4b631` (benchmark):

```lean
 by
  
    rw [funext_iff]; by_contra h₀
    obtain ⟨x₀, hx0⟩ := not_forall.1 h₀
    simp at hx0 

  
  ...
```

  - `564fa1131ed1d5fa` (v6c3-fundamental_theorem_of_variational_calcu-gpt-6-luna-r1):

```lean
 by
  rw [funext_iff]
  by_contra h₀
  obtain ⟨x₀, hx0⟩ := not_forall.1 h₀
  simp at hx0
  let f₂ : Y → WithLp 2 V := toL2 ℝ ∘ f
  let x₂ := f₂ x₀
  ...
```

- **r2**: 14 proofs (v5 3, hybrid 1, v6 11); label: `+ContDiffBump.continuous +ContinuousAt.tendsto +Filter.Eventually −sq_nonneg −Mathlib.Tactic.Linarith.add_nonpos −Mathlib.Tactic.Linarith.le_of_le_of_eq`
  - `eaf66014b6a24a91` (v5-gen-20261007-physlib-model-qwen3.8-flash):

```lean
 by
  rw [funext_iff]; by_contra h₀
  obtain ⟨x₀, hx0⟩ := not_forall.1 h₀
  have h2 : 0 < ⟪f x₀, f x₀⟫_ℝ :=
    lt_of_not_ge fun h => hx0 (inner_self_eq_zero'.mp (le_antisymm h real_inner_self_nonneg'))
  have hc : Continuous (fun x => ⟪f x, f x₀⟫_ℝ) := Continuous.inner' f (fun _ => f x₀) hf continuous_const
  obtain ⟨δ, hδ, hb⟩ : ∃ δ > (0 : ℝ), ∀ x ∈ Metric.ball x₀ δ, 0 < ⟪f x, f x₀⟫_ℝ :=
  ...
```

  - `8db0fc248136eb6a` (v5-gen-20261007-physlib-model-qwen3.8-flash):

```lean
 by
  rw [funext_iff]; by_contra h₀
  obtain ⟨x₀, hx0⟩ := not_forall.1 h₀
  have hc : Continuous (fun x => ⟪f x, f x₀⟫_ℝ) := Continuous.inner' f (fun _ => f x₀) hf continuous_const
  obtain ⟨δ, hδ, hb⟩ : ∃ δ > (0 : ℝ), ∀ x ∈ Metric.ball x₀ δ, 0 < ⟪f x, f x₀⟫_ℝ :=
    Metric.eventually_nhds_iff.mp (hc.continuousAt.tendsto.eventually_const_lt
      (lt_of_not_ge fun h => hx0 (inner_self_eq_zero'.mp (le_antisymm h real_inner_self_nonneg'))))
  ...
```


### putnam_1964_a4

- **r1**: 1 proofs (pre-v5 1); label: `recursion: Nat.strong_induction_on; Classical.propDecidable, Finset.Icc, Function.Injective`
  - `71bbc4bd4206f3cf` (benchmark):

```lean
 by 
  have h_main : ∃ (i j : ℕ), i < j ∧ (u i = u j ∧ u (i + 1) = u (j + 1) ∧ u (i + 2) = u (j + 2) ∧ u (i + 3) = 
    obtain ⟨B, T, hB⟩ := boundedu
    have h₁ : ∃ (i j : ℕ), i < j ∧ (u i = u j ∧ u (i + 1) = u (j + 1) ∧ u (i + 2) = u (j + 2) ∧ u (i + 3) = u 
      
      classical
      
  ...
```


### putnam_1964_b2

- **r1**: 1 proofs (pre-v5 1); label: `recursion: none; Classical.choice, Classical.propDecidable, DecidableEq`
  - `18a3ba5fdc41963e` (benchmark):

```lean
 by 
  have h_no_empty : ∀ (T : Set S), T ∈ P → T.Nonempty := by
    intro T hT
    have h₁ : T ∩ T ≠ ∅ := hPP T hT T hT
    have h₂ : T ∩ T = T := by simp [Set.ext_iff]
    rw [h₂] at h₁
    exact Set.nonempty_iff_ne_empty.mpr h₁
  ...
```


### putnam_1995_a3

- **r1**: 1 proofs (pre-v5 1); label: `recursion: none; Finset.card, Finset.dvd_sum, Finset.sum_add_distrib`
  - `33ad270ea1571dc6` (benchmark):

```lean
 by 
  have h_main : ∀ (d e f : (Fin 9 → ℤ)), ((relation d e) ∧ (relation e f)) → (∀ i : Fin 9, 7 ∣ d i - f i) := b
    intro d e f h
    have h₁ : relation d e := h.1
    have h₂ : relation e f := h.2
    have h₃ : ∀ (i : Fin 9), 7 ∣ (digits_to_num (fun j : Fin 9 => if j = i then e j else d j)) := by
      have h₄ : (∀ i : Fin 9, 7 ∣ (digits_to_num (fun j : Fin 9 => if j = i then e j else d j))) := (hrelation
  ...
```


## (b) Known distinct routes

Core.InitsUpdatesComm: the original (induction on `UpdateStates`, `Core.UpdateStates.rec`) and the equational route
(DeepSeek's `updatedStatesComm` / `updatedStatesUpdate` proofs, no recursion) separate. All 6 DeepSeek proofs and 18 other
proofs (qwen v5, luna v6c3, the 87.10 hybrid) land in r2 `recursion: none instead of Core.UpdateStates.rec;
+Core.UpdateStatesUpdated +Core.updatedStatesComm +Core.updatedStatesDefMonotone ...`; similarity of a DeepSeek proof to the
original is 0.23 to 0.28. The 183-proof r1 is the induction family. Margin: within-route similarity to the exemplar is at
least 0.52 (median 0.81); similarity of any proof to the other route's exemplar is at most 0.32 (median 0.24); 3 of 412
comparisons fall in 0.4 to 0.6. OLD gave the same 183 / 24 split on this theorem, so there is no regression here.

## (a) Synonym robustness

Text-level rewrites of the original plus about 8 stored proofs per theorem (sampled across NEW routes), recompiled and
re-extracted. `similarity` is to the source proof under NEW, "same route" is the route the rewrite is assigned on the
full history.

| rewrite | recompiled ok / tried | same route (new) | mean similarity (new) | same route (old text fingerprint) |
|---|---|---|---|---|
| dot->bullets | 3/3 | 3/3 | 1.00 | 3/3 |
| intros->intro | 11/11 | 11/11 | 1.00 | 11/11 |
| exact->apply | 15/23 | 14/15 | 1.00 | 13/15 |
| all | 16/24 | 15/16 | 1.00 | 14/16 |
| bullets->dot | 19/19 | 18/19 | 1.00 | 19/19 |
| intro->intros | 21/21 | 20/21 | 1.00 | 21/21 |
| exists->refine | 3/3 | 3/3 | 1.00 | 3/3 |
| exists->use | 1/3 | 1/1 | 1.00 | 1/1 |
| swap-haves | 8/8 | 8/8 | 1.00 | 8/8 |
| obtain->rcases | 6/9 | 6/6 | 1.00 | 6/6 |
| use->exists | 5/5 | 5/5 | 1.00 | 5/5 |
| rcases->obtain | 3/3 | 3/3 | 1.00 | 3/3 |
| by_contra->byContradiction | 1/2 | 1/1 | 1.00 | 1/1 |

112 of 134 rewrites recompiled (the rest are `sorry` or parse errors: a rewrite that was not valid, discarded). Every
recompiled rewrite has similarity exactly 1.00 to its source under NEW, and OLD also keeps 108 of 112 above 0.5 (4 fall
to 0.33 through its skeleton fallback after `exact->apply`). The 4 NEW route mismatches are all one base proof (e1d4fcd8 in
extractedOldExprInVars) that itself arrived early and was assigned r1 while it is closer to the r2 exemplar (caveat 1): its
rewrites sit at 1.00 to it but are assigned r2 on the full history. These rewrites mostly do not touch what the old
fingerprint reads (lemma names), so this check shows NEW loses nothing; the evidence that NEW is better is (c).

## (c) OLD and NEW disagree: 10 pairs with verdicts

OLD here uses the real kickoff vocabulary of each row (`cached_context`; the missing context caches for the two
CallElimCorrect rows and the PhysLib row were generated with `lean_context`, local Lean). Pairs are sampled from
`disagreements.json` (15 sampled, up to 3 per old/new route combination). Every disagreement is of one kind: OLD says
same route, NEW says different; there is no pair OLD splits and NEW merges. NEW also separates more where OLD saw one
route: extractedOldExprInVars 1 -> 2, substOldPostSubset 1 -> 2, PhysLib 1 -> 2.

| # | theorem | pair (short ids) | OLD | NEW | verdict |
|---|---|---|---|---|---|
| 1 | extractedOldExprInVars | luna `2257935f` (`induction H`, `subset_app_of_or_2`) vs luna `ac2d496f` (`induction post`, `cases Hnorm`) | same | different | NEW right: induction on the normalisation derivation vs on the expression; different case structure and toolkit |
| 2 | extractedOldExprInVars | luna `ac2d496f` (`induction post`) vs hybrid h8c (`induction H`) | same | different | NEW right |
| 3 | extractedOldExprInVars | luna `6bbaa8bd` (`induction H`) vs qwen `837773ea` (`induction post`, `List.Subset.trans`) | same | different | NEW right |
| 4 | extractedOldExprInVars | luna `7df855b8` (`induction H`) vs luna `ac2d496f` (`induction post`) | same | different | NEW right |
| 5 | extractedOldExprInVars | luna `da297ef5` (`induction H`, `simp`) vs hybrid h1 (`induction H`, `exact Subset.empty`, per-case `Subset.app`) | same | different | NEW wrong (borderline): same strategy and same recursion target; `da297ef5` arrived before the r2 exemplar existed and was assigned r1 (caveat 1); the lemma toolkits also differ a little |
| 6 | extractedOldExprInVars | luna `2e43d28b` (`induction H`) vs hybrid h11 (`induction H`) | same | different | NEW wrong: same strategy; same arrival-order artefact as 5 |
| 7 | substOldPostSubset | luna `6f385af8` (`induction post`, `simp only`, hand-built `List.Subset.app/trans`) vs hybrid 82.86 (`induction post <;> dsimp <;> repeat' split; grind`) | same | different | NEW right: same induction but one composes `List.Subset.app/trans` per case, the other closes everything with `grind` (`Lean.Grind.MatchCond`); a different spend profile too |
| 8 | PhysLib variational | luna v5 `1e763943` vs DeepSeek v6c2 `ee2325a0` | same | different | NEW right: positivity near x0 from `Metric.continuousAt_iff` on `toL2 . f` (`inner_pos2`) vs an `isOpen_lt` / `Metric.mem_nhds_iff` neighbourhood from `Continuous.inner'` (`hpos0`) |
| 9 | PhysLib variational | luna v5 `5ced15ab` vs DeepSeek v6c2 `50d259cb` | same | different | NEW right (same two approaches) |
| 10 | PhysLib variational | DeepSeek `e1d0daaa` vs luna v6c3 `4a222425` | same | different | NEW right |

Score: NEW right in 8 of 10, wrong in 2 (5 and 6, both from arrival order). Over the whole theorem the PhysLib split is
clean: route r1 has `toL2` and `continuousAt_iff` in 21 of 22 proofs, r2 has `isOpen_lt` and `mem_nhds_iff` in 10 and 11 of
14. extractedOldExprInVars: r2 (26) is induction on `H` (`NormalizedOldExpr.rec`), r1 (10) induction on `post`, except
the 4 early arrivals above. OLD could not see the induction target (it only knows "recurses"), nor lemmas outside the kickoff
vocabulary.

## Threshold sensitivity (routes under NEW)

| theorem | 0.4 | 0.5 | 0.6 |
|---|---|---|---|
| CallElimCorrect.extractedOldExprInVars | 1 | 2 | 2 |
| CallElimCorrect.substOldPostSubset | 2 | 2 | 2 |
| Core.InitsUpdatesComm | 2 | 2 | 3 |
| Cslib.CCS.bisimilarity_congr_choice | 1 | 1 | 1 |
| fundamental_theorem_of_variational_calculus' | 2 | 2 | 3 |

0.5 is kept. At 0.4 extractedOldExprInVars collapses its two induction strategies (pairs 1 to 4 above argue
against that); at 0.6 Core and PhysLib gain a small satellite route. The PhysLib split is the least stable: 40 of 70
exemplar comparisons land in 0.4 to 0.6, because its proofs share a long common prefix (`by_contra`, `not_forall`, bump
function construction) and differ in the middle.

## Tuning done (and why)

Weights (0.25 / 0.45 / 0.20 / 0.10) and the threshold (0.5) are as specified; nothing was tuned on them. Three
changes to the feature extraction were made after looking at the first full run, each for an identified artefact:

1. Auxiliary declarations followed only if they belong to the theorem (`main._proof_N`, `match_N`, `_unary`, helpers) or
   are matchers. First version followed every new constant; equation lemmas that `unfold`/`simp` generate for other
   definitions (`extractOldExprVars.eq_def`, `match_1.eq_3`) injected `LExpr.rec`, `Identifier.rec`, `Visibility.rec`
   into every proof and hid the real induction target.
2. `T.brecOn.go` / `T.brecOn.eq` count as `T.rec`; claims typed `*.below`, `PProd`, `motive*` are dropped (structural
   recursion machinery, not claims).
3. Stoplist extended with what `simp`/`decide`/`grind` leave behind regardless of the lemmas given
   (`Decidable.decide`, `*.congr_simp`, `ctorIdx`, `noConfusion_of_Nat`, `ite_cond_eq_true`, `false_and`, ...). Before this,
   a Core pair of near-identical induction proofs scored 0.45 and split into a 38-proof satellite route.

## Failures (18 proofs not extracted)

- 7 originals whose workspace is not built (Binius x2 and interleaved_affine_gaps: `unknown module prefix 'ArkLib'`;
  Fsub, SKI, Electromagnetism, Wick: `object file ... missing` for cslib-v4.33.0-rc2 / physlib-v4.32.0 modules these files
  import). They are single originals, so no route statistics are lost.
- 10 CCS scratch drafts from `runs/analysis/scratch/cslib` that do not compile (the term contains `sorryAx`, or an
  elaboration error) and 1 extractedOldExprInVars scratch draft with `sorry`: correctly rejected.
- Putnam rows only have their originals stored (3 proofs).

## Cost

Extraction itself (the metaprogram, `extract_ms`): median 17 ms (Core), 36 ms (CCS), 112 ms (PhysLib), max 188 ms. The
Lean wall time per proof is dominated by compiling the file prefix and the candidate again: a single proof alone takes 4.2 s
(Core), 11 s (CCS), 19 s (PhysLib); inside a 10-proof batch 0.9 to 4.3 s per proof. The harness runs one proof at a time in
the background lane after scoring, so a candidate's own heartbeats and tokens are untouched; with a Lean session
configured (`run_lean` reuses the session) the prefix cost drops.

## Caveats

1. Online clustering by first proof is order dependent. Early on, IDF has almost no information, so a proof can join a
   route at 0.5+ that it would leave once more proofs exist (4 of the 36 extractedOldExprInVars proofs, 0 in Core).
   Re-running `routes.assign` over the ledger would fix them but changes already shown route ids, so it was not done.
2. Only 5 of the 15 theorems have more than one stored proof; claims about other rows (Putnam, ArkLib, Fsub, SKI) are
   untested.
3. The robustness rewrites are mostly invisible to the old fingerprint too; the evidence that NEW is better is the
   disagreement table, not the synonym table. The reading of the 10 pairs is mine, not a labelled test set.
4. Claim hashes are over de Bruijn-erased types with instance arguments; two spellings of the same claim that elaborate to
   different instances hash differently (claims carry 0.20).
5. In `_record_route` the extraction runs synchronously after scoring, inside the same tool call; it is bounded by a 120 s
   Lean timeout and falls back to text features (`source: "text"`) on any failure.
