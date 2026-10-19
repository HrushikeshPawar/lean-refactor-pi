## system prompt (103 chars, 18 words)
You are improving one Lean proof in the Arena. Only the listed tools are available. Keep replies short.

## skill (1655 chars, 279 words)
# Arena task

Replace the proof of one theorem with a proof that scores more points and compiles on every listed Lean version.
The packet states the scoring rule and this theorem's rates.
The tools are `compile`, `goal`, `search`, `read` and `scratch`; each description states its inputs and replies.
The harness files every compiled proof as a node of a graph.
Ids: node nN, top-level step sK, open hole nN.hK.
A node's outcome is one of three phrases: "compiles" (the node compiles with no open hole), "compiles with N open holes" (it compiles; its holes are open), or "does not compile".
Spend counts only your own tokens, reasoning included; Lean checks are free, so a scratch test is cheaper than long reasoning.
`#check` a declaration before passing it positional arguments. One compile call takes up to 4 drafts.
Recaps are not needed.

The theorem statement and all bytes before `:=` must remain unchanged.
A submitted proof may contain no `sorry`, `admit`, `axiom`, `native_decide`, `#eval`, `IO.`, `unsafe`, `macro`, `elab`, `notation`, `syntax`, `attribute`, auxiliary declaration, or extra top-level command.
A dotted name such as `h.1`, `x.inl` or `Nat.succ_le` is one run of letters, digits, `.`, `_` and `'`, so it counts 1 token.
Measured: `case inl x y => exact x` is 7 tokens; `case inl => rename_i x y; exact x` is 9.
`all_goals tac` and `tac <;> tac'` run one tactic on every goal.
A closing step costs more heartbeats on a bigger goal: state the needed identity as a small equation, prove it, then substitute it.
A scratch `example` has only the hypotheses it states; try a step that needs the proof's context with `goal` at its line.

## tools/compile (1016 chars, 166 words)
Compile up to 4 proof drafts, or apply one graph edit: splice, fill or merge. Returns for each node its id, outcome, errors, open holes with goals, and price.
base: Node the drafts are filed under.
check: Valid values: tokens (count tokens only, no Lean) or lean (compile).
drafts: Up to 4 plain strings, each the whole theorem, `by` plus tactics, or tactic lines alone.
fill: Replace one open hole with proof text.
fill_hole: Open hole id, for example n2.h1.
fill_text: Proof text for the hole.
from: Parent node recorded with the result.
merge: Copy selected steps into one node.
merge_base: Node that receives the steps; default: the focus.
merge_from: Node that supplies the step.
merge_step: Id of the supplied step.
merge_take: Pairs of source node and step.
note: Optional: what this tries, why.
splice: Replace a range of steps in one node.
splice_base: Node whose steps are replaced; default: the focus.
splice_steps: Inclusive step range, for example s2-s3.
splice_text: Proof text that replaces the range.

## tools/goal (428 chars, 73 words)
Return the goals at a node line or hole, with a map of each case's hypothesis names. Snippets in try replace that line's whole step or that hole; each reports its verdict, tokens, and the goals left after that snippet alone.
hole: Open hole identifier, such as n2.h1.
line: One-based line number in the node proof.
node: Node identifier containing the position.
try: Proof snippets for the selected position; needs line or hole.

## tools/search (313 chars, 43 words)
Search declarations visible from this theorem's imports. Return handles, signatures, and locations.
after: Name prefix for completion results; without queries it lists every completion of the prefix.
kind: Match declaration names, types, or source text.
queries: Search strings, returned as separate result items.

## tools/read (472 chars, 70 words)
Return pinned source or a node's prices, diff, outline, tree, or graph map.
against: Comparison node for the diff view.
handle: Declaration handle from search, e.g. decl:Nat.add_comm, or file lines, e.g. ArkLib/Foo.lean:120-150; or decl:Nat.add_comm:20-50.
hole: Hole identifier for its goal view.
node: Node identifier for node views.
step: Step id; outline view gives its goals.
view: Choose source, prices, diff, outline, tree (cost per tactic and stated term), or map.

## tools/finish (115 chars, 22 words)
End the run. Returns the archive and the points left per axis. Offered when at most 10% of the spend limit remains.

## tools/scratch (390 chars, 63 words)
Run Lean commands in this theorem's environment, such as example ... := by trace_state; rfl, #check or #print. Nothing becomes a node or is scored. Replies give OK or FAILED, error and warning counts, body tokens (after :=), messages by line, and each declaration's heartbeats and points.
code: Lean commands that take the target declaration's place; no import lines. sorry is allowed here.

## Task (569 chars, 69 words)
Theorem: Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius
Original proof: node n1.
Statement:
```lean
theorem fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius (i : Fin ℓ) (steps : ℕ)
    [NeZero steps] (h_i_add_steps : i.val + steps ≤ ℓ)
    (f : OracleFunction 𝔽q β (h_ℓ_add_R_rate := h_ℓ_add_R_rate) ⟨i, by omega⟩)
  (h_fw_dist_lt : fiberwiseClose 𝔽q β (h_ℓ_add_R_rate := h_ℓ_add_R_rate)
    (i := i) (steps := steps) (h_i_add_steps := h_i_add_steps) (f := f)) :
  hammingClose 𝔽q β (h_ℓ_add_R_rate := h_ℓ_add_R_rate) ⟨i, by omega⟩ f
```

## Scoring (856 chars, 144 words)
Score: the mean of three percentages: token reduction, heartbeat reduction and compatibility.
Token reduction: percent fewer tokens than the reference proof (1463 tokens).
Heartbeat reduction: percent fewer heartbeats than the reference proof (15645 heartbeats).
Compatibility: percent of the listed versions on which the proof compiles.
A proof that does not compile scores zero.
Rates: 1 token = 0.023 points; 100 heartbeats = 0.213 points; 1 version = 8.33 points.
Token count: proof text after `:=`, without comments and attributes.
Each identifier or number counts 1 token, whatever its length.
Each other nonspace character counts 1 token, except these groups, which count 1 token each: `:= != && -. -> ← .. ... :: :> <;> ;; == || => <= >= ⁻¹ ?_`.
Spaces and line breaks count 0; a tab counts 1.
Examples: `exact foo` = 2 tokens; `⟨a, b⟩` = 5 tokens.

## Pinned environment (846 chars, 51 words)
Pinned environment
Source: arklib:ArkLib/ProofSystem/Binius/BinaryBasefold/Prelude.lean:1265-1473
Lean toolchain and source revisions: Lean v4.31.0 / source revision c1712f6c496d0aef04f09bae42aec13811b3273f; Lean v4.30.0 / source revision e6d77b18ca1334a91faf4d1ccf9f96d854d58ba4; Lean v4.29.0 / source revision de71a9dfd2f5a343e8895517b7efe857d9f1ce5c; Lean v4.28.0 / source revision 673fa440714eb1949b8b50a28f2a4f52b1837e9b
Available imports: import ArkLib.Data.CodingTheory.BerlekampWelch.BerlekampWelch, import ArkLib.Data.CodingTheory.ReedSolomon, import CompPoly.Fields.Binary.AdditiveNTT.AdditiveNTT, import ArkLib.Data.MvPolynomial.Multilinear, import ArkLib.Data.MvPolynomial.RestrictDegree, import CompPoly.Data.Vector.Basic, import ArkLib.ProofSystem.Sumcheck.Spec.SingleRound, import ArkLib.ProofSystem.Sumcheck.Structured.SingleRound

## Scope at the theorem (namespace, open, variable, universe in effect before the statement) (818 chars, 126 words)
Scope at the theorem (namespace, open, variable, universe in effect before the statement)
namespace Binius.BinaryBasefold
open OracleSpec OracleComp ProtocolSpec Finset AdditiveNTT Polynomial MvPolynomial
  Binius.BinaryBasefold
open scoped NNReal
open Code BerlekampWelch
open Finset AdditiveNTT Polynomial MvPolynomial Nat Matrix
variable {r : ℕ} [NeZero r]
variable {L : Type} [Field L] [Fintype L] [DecidableEq L] [CharP L 2]
variable (𝔽q : Type) [Field 𝔽q] [Fintype 𝔽q] [DecidableEq 𝔽q]
  [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] [hF₂ : Fact (Fintype.card 𝔽q = 2)]
variable [Algebra 𝔽q L]
variable (β : Fin r → L) [hβ_lin_indep : Fact (LinearIndependent 𝔽q β)]
  [h_β₀_eq_1 : Fact (β 0 = 1)]
variable {ℓ 𝓡 ϑ : ℕ} (γ_repetitions : ℕ) [NeZero ℓ] [NeZero 𝓡] [NeZero ϑ]
variable {h_ℓ_add_R_rate : ℓ + 𝓡 < r}

## Original proof and step prices (1463 tokens) (13607 chars, 2264 words)
Original proof and step prices (1463 tokens)
```lean
theorem fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius (i : Fin ℓ) (steps : ℕ)
    [NeZero steps] (h_i_add_steps : i.val + steps ≤ ℓ)
    (f : OracleFunction 𝔽q β (h_ℓ_add_R_rate := h_ℓ_add_R_rate) ⟨i, by omega⟩)
  (h_fw_dist_lt : fiberwiseClose 𝔽q β (h_ℓ_add_R_rate := h_ℓ_add_R_rate)
    (i := i) (steps := steps) (h_i_add_steps := h_i_add_steps) (f := f)) :
  hammingClose 𝔽q β (h_ℓ_add_R_rate := h_ℓ_add_R_rate) ⟨i, by omega⟩ f := by
  unfold fiberwiseClose at h_fw_dist_lt
  unfold hammingClose
  -- 2 * Δ₀(f, ↑(BBF_Code 𝔽q β ⟨↑i, ⋯⟩)) < ↑(BBF_CodeDistance ℓ 𝓡 ⟨↑i, ⋯⟩)
  let d_fw := fiberwiseDistance 𝔽q β (i := i) steps h_i_add_steps f
  let C_i := (BBF_Code 𝔽q β (h_ℓ_add_R_rate := h_ℓ_add_R_rate) ⟨i, by omega⟩)
  let d_H := Code.distFromCode f C_i
  let d_i := BBF_CodeDistance ℓ 𝓡 (⟨i, by omega⟩)
  let d_i_plus_steps := BBF_CodeDistance ℓ 𝓡 ⟨i.val + steps, by omega⟩

  have h_d_i_gt_0 : d_i > 0 := by
    dsimp [d_i, BBF_CodeDistance] -- ⊢ 2 ^ (ℓ + 𝓡 - ↑i) - 2 ^ (ℓ - ↑i) + 1 > 0
    have h_exp_lt : ℓ - i.val < ℓ + 𝓡 - i.val := by
      exact Nat.sub_lt_sub_right (a := ℓ) (b := ℓ + 𝓡) (c := i.val) (by omega) (by
        apply Nat.lt_add_of_pos_right; exact pos_of_neZero 𝓡)
    have h_pow_lt : 2 ^ (ℓ - i.val) < 2 ^ (ℓ + 𝓡 - i.val) := by
      exact Nat.pow_lt_pow_right (by norm_num) h_exp_lt
    omega

  have h_C_i_nonempty : Nonempty C_i := by
    simp only [nonempty_subtype, C_i]
    exact Submodule.nonempty (BBF_Code 𝔽q β (h_ℓ_add_R_rate := h_ℓ_add_R_rate) ⟨i.val, by omega⟩)

  -- 1. Relate Hamming distance `d_H` to fiber-wise distance `d_fw`.
  obtain ⟨g', h_g'_mem, h_g'_min_card⟩ : ∃ g' ∈ C_i, d_fw
    = (fiberwiseDisagreementSet 𝔽q β i steps h_i_add_steps f g').ncard := by
    -- Let `S` be the set of all possible fiber-wise disagreement sizes.
    let S := (fun (g : C_i) => (fiberwiseDisagreementSet 𝔽q β i steps h_i_add_steps
      f g).ncard) '' Set.univ
    -- The code `C_i` (a submodule) is non-empty, so `S` is also non-empty.
    have hS_nonempty : S.Nonempty := by
      refine Set.image_nonempty.mpr ?_

      exact Set.univ_nonempty
    -- For a non-empty set of natural numbers, `sInf` is an element of the set.
    have h_sInf_mem : sInf S ∈ S := Nat.sInf_mem hS_nonempty
    -- By definition, `d_fw = sInf S`.
    unfold d_fw at h_sInf_mem
    -- Since `sInf S` is in the image set `S`, there must be an element `g_subtype` in the domain
    -- (`C_i`) that maps to it. This `g_subtype` is the codeword we're looking for.
    rw [Set.mem_image] at h_sInf_mem
    rcases h_sInf_mem with ⟨g_subtype, _, h_eq⟩
    -- Extract the codeword and its membership proof.
    exact ⟨g_subtype.val, g_subtype.property, by exact id (Eq.symm h_eq)⟩

  -- The Hamming distance to any codeword `g'` is bounded by `d_fw * 2 ^ steps`.
  have h_dist_le_fw_dist_times_fiber_size : (hammingDist f g' : ℕ∞) ≤ d_fw * 2 ^ steps := by
    -- This proves `dist f g' ≤ (fiberwiseDisagreementSet ... f g').ncard * 2 ^ steps`
    -- and lifts to ℕ∞. We prove the `Nat` version `hammingDist f g' ≤ ...`,
    -- which is equivalent.
    change (Δ₀(f, g') : ℕ∞) ≤ ↑d_fw * ((2 ^ steps : ℕ) : ℕ∞)
    rw [←ENat.coe_mul, ENat.coe_le_coe, h_g'_min_card]
    -- Let ΔH be the finset of actually bad x points where f and g' disagree.
    set ΔH := Finset.filter (fun x => f x ≠ g' x) Finset.univ
    have h_dist_eq_card : hammingDist f g' = ΔH.card := by
      simp only [hammingDist, ne_eq, ΔH]
    rw [h_dist_eq_card]
    -- Y_bad is the set of quotient points y that THERE EXISTS a bad fiber point x
    set Y_bad := fiberwiseDisagreementSet 𝔽q β i steps h_i_add_steps f g'
    simp only at * -- simplify domain indices everywhere

    -- ⊢ #ΔH ≤ Y_bad.ncard * 2 ^ steps

    have hFinType_Y_bad : Fintype Y_bad := by exact Fintype.ofFinite ↑Y_bad
    -- Every point of disagreement `x` must belong to a fiber over some `y` in `Y_bad`,
    -- BY DEFINITION of `Y_bad`. Therefore, `ΔH` is a subset of the union of the fibers
    -- of `Y_bad`
    have h_ΔH_subset_bad_fiber_points : ΔH ⊆ Finset.biUnion Y_bad.toFinset
        (t := fun y => ((qMap_total_fiber 𝔽q β (i := ⟨i, by omega⟩) (steps := steps)
          (h_i_add_steps := by apply Nat.lt_add_of_pos_right_of_le; omega) (y := y)) ''
          (Finset.univ : Finset (Fin ((2:ℕ)^steps)))).toFinset) := by
      -- ⊢ If any x ∈ ΔH, then x ∈ Union(qMap_total_fiber(y), ∀ y ∈ Y_bad)
      intro x hx_in_ΔH; -- ⊢ x ∈ Union(qMap_total_fiber(y), ∀ y ∈ Y_bad)
      simp only [ΔH, Finset.mem_filter] at hx_in_ΔH
      -- Now we actually apply iterated qMap into x to get y_of_x,
      -- then x ∈ qMap_total_fiber(y_of_x) by definition
      let y_of_x := iteratedQuotientMap 𝔽q β h_ℓ_add_R_rate i steps h_i_add_steps x
      apply Finset.mem_biUnion.mpr; use y_of_x
      -- ⊢ y_of_x ∈ Y_bad.toFinset ∧ x ∈ qMap_total_fiber(y_of_x)
      have h_elemenet_Y_bad : y_of_x ∈ Y_bad.toFinset := by
        -- ⊢ y ∈ Y_bad.toFinset
        simp only [fiberwiseDisagreementSet, iteratedQuotientMap, ne_eq, Subtype.exists,
          Set.toFinset_setOf, mem_filter, mem_univ, true_and, Y_bad]
        -- one bad fiber point of y_of_x is x itself
        let X := x.val
        have h_X_in_source : X ∈ sDomain 𝔽q β h_ℓ_add_R_rate (i := ⟨i, by omega⟩) := by
          exact Submodule.coe_mem x
        use X
        use h_X_in_source
        -- ⊢ Ŵ_steps⁽ⁱ⁾(X) = y (iterated quotient map) ∧ ¬f ⟨X, ⋯⟩ = g' ⟨X, ⋯⟩
        have h_forward_iterated_qmap : Polynomial.eval X
            (intermediateNormVpoly 𝔽q β h_ℓ_add_R_rate ⟨↑i, by omega⟩
              ⟨steps, by simp only; omega⟩) = y_of_x := by
          simp only [iteratedQuotientMap, X, y_of_x];
        have h_eval_diff : f ⟨X, by omega⟩ ≠ g' ⟨X, by omega⟩ := by
          unfold X
          simp only [Subtype.coe_eta, ne_eq, hx_in_ΔH, not_false_eq_true]
        simp only [h_forward_iterated_qmap, Subtype.coe_eta, h_eval_diff,
          not_false_eq_true, and_self]
      simp only [h_elemenet_Y_bad, true_and]

      set qMapFiber := qMap_total_fiber 𝔽q β (i := ⟨i, by omega⟩) (steps := steps)
        (h_i_add_steps := by apply Nat.lt_add_of_pos_right_of_le; omega) (y := y_of_x)
      simp only [coe_univ, Set.image_univ, Set.toFinset_range, mem_image, mem_univ, true_and]
      use (pointToIterateQuotientIndex (i := ⟨i, by omega⟩) (steps := steps)
        (h_i_add_steps := by omega) (x := x))
      have h_res := is_fiber_iff_generates_quotient_point 𝔽q β i steps (by omega)
        (x := x) (y := y_of_x).mp (by rfl)
      exact h_res
    -- ⊢ #ΔH ≤ Y_bad.ncard * 2 ^ steps
    -- The cardinality of a subset is at most the cardinality of the superset.
    apply (Finset.card_le_card h_ΔH_subset_bad_fiber_points).trans
    -- The cardinality of a disjoint union is the sum of cardinalities.
    rw [Finset.card_biUnion]
    · -- The size of the sum is the number of bad fibers (`Y_bad.ncard`) times
      -- the size of each fiber (`2 ^ steps`).
      simp only [Set.toFinset_card]
      have h_card_fiber_per_quotient_point := card_qMap_total_fiber 𝔽q β
        (h_ℓ_add_R_rate := h_ℓ_add_R_rate) i steps h_i_add_steps
      simp only [Set.image_univ, Fintype.card_ofFinset,
        Subtype.forall] at h_card_fiber_per_quotient_point
      have h_card_fiber_of_each_y : ∀ y ∈ Y_bad.toFinset,
          Fintype.card ((qMap_total_fiber 𝔽q β (i := ⟨↑i, by omega⟩) (steps := steps)
            (h_i_add_steps := by apply Nat.lt_add_of_pos_right_of_le; omega) (y := y)) ''
            ↑(Finset.univ : Finset (Fin ((2:ℕ)^steps)))) = 2 ^ steps := by
        intro y hy_in_Y_bad
        have hy_card_fiber_of_y := h_card_fiber_per_quotient_point (a := y) (b := by
          exact Submodule.coe_mem y)
        simp only [coe_univ, Set.image_univ, Fintype.card_ofFinset, hy_card_fiber_of_y]
      rw [Finset.sum_congr rfl h_card_fiber_of_each_y]
      -- ⊢ ∑ x ∈ Y_bad.toFinset, 2 ^ steps ≤ Y_bad.encard.toNat * 2 ^ steps
      simp only [sum_const, Set.toFinset_card, smul_eq_mul, ofNat_pos, pow_pos,
        _root_.mul_le_mul_right, ge_iff_le]
      conv_rhs => rw [←_root_.Nat.card_coe_set_eq] -- convert .ncard back to .card
      -- ⊢ Fintype.card ↑Y_bad ≤ Nat.card ↑Y_bad
      simp only [card_eq_fintype_card, le_refl]
    · -- Prove that the fibers for distinct quotient points y₁, y₂ are disjoint.
      intro y₁ hy₁ y₂ hy₂ hy_ne
      have h_disjoint := qMap_total_fiber_disjoint (i := ⟨↑i, by omega⟩) (steps := steps)
        (h_i_add_steps := by omega) (y₁ := y₁) (y₂ := y₂) (hy_ne := hy_ne)
      simp only [Function.onFun, coe_univ]
      exact h_disjoint

  -- The minimum distance `d_H` is bounded by the distance to this specific `g'`.
  have h_dist_bridge : d_H ≤ d_fw * 2 ^ steps := by
    -- exact h_dist_le_fw_dist_times_fiber_size
    apply le_trans (a := d_H) (c := d_fw * 2 ^ steps) (b := hammingDist f g')
    · -- ⊢ d_H ≤ ↑Δ₀(f, g')
      simp only [distFromCode, SetLike.mem_coe, hammingDist, ne_eq, d_H];
      -- ⊢ Δ₀(f, C_i) ≤ ↑Δ₀(f, g')
      -- ⊢ sInf {d | ∃ v ∈ C_i, ↑(#{i | f i ≠ v i}) ≤ d} ≤ ↑(#{i | f i ≠ g' i})
      apply sInf_le
      use g'
    · exact h_dist_le_fw_dist_times_fiber_size

  -- 2. Use the premise : `2 * d_fw < d_{i+steps}`.
  -- As a `Nat` inequality, this is equivalent to `2 * d_fw ≤ d_{i+steps} - 1`.
  have h_fw_bound : 2 * d_fw ≤ d_i_plus_steps - 1 := by
    -- Convert the ENat inequality to a Nat inequality using `a < b ↔ a + 1 ≤ b`.
    exact Nat.le_of_lt_succ (WithTop.coe_lt_coe.1 h_fw_dist_lt)

  -- 3. The Algebraic Identity.
  -- The core of the proof is the identity : `(d_{i+steps} - 1) * 2 ^ steps = d_i - 1`.
  have h_algebraic_identity : (d_i_plus_steps - 1) * 2 ^ steps = d_i - 1 := by
    dsimp [d_i, d_i_plus_steps, BBF_CodeDistance]
    rw [Nat.sub_mul, ←Nat.pow_add, ←Nat.pow_add];
    have h1 : ℓ + 𝓡 - (↑i + steps) + steps = ℓ + 𝓡 - i := by
      rw [Nat.sub_add_eq_sub_sub_rev (h1 := by omega) (h2 := by omega),
        Nat.add_sub_cancel (n := i) (m := steps)]
    have h2 : (ℓ - (↑i + steps) + steps) = ℓ - i := by
      rw [Nat.sub_add_eq_sub_sub_rev (h1 := by omega) (h2 := by omega),
        Nat.add_sub_cancel (n := i) (m := steps)]
    rw [h1, h2]

  -- 4. Conclusion : Chain the inequalities to prove `2 * d_H < d_i`.
  -- We know `d_H` is finite, since `C_i` is nonempty.
  have h_dH_ne_top : d_H ≠ ⊤ := by
    simp only [ne_eq, d_H]
    rw [Code.distFromCode_eq_top_iff_empty f C_i]
    exact Set.nonempty_iff_ne_empty'.mp h_C_i_nonempty

  -- We can now work with the `Nat` value of `d_H`.
  let d_H_nat := ENat.toNat d_H
  have h_dH_eq : d_H = d_H_nat := (ENat.coe_toNat h_dH_ne_top).symm

  -- The calculation is now done entirely in `Nat`.
  have h_final_inequality : 2 * d_H_nat ≤ d_i - 1 := by
    have h_bridge_nat : d_H_nat ≤ d_fw * 2 ^ steps := by
        rw [←ENat.coe_le_coe]
        exact le_of_eq_of_le (id (Eq.symm h_dH_eq)) h_dist_bridge
    calc 2 * d_H_nat
      _ ≤ 2 * (d_fw * 2 ^ steps) := by gcongr
      _ = (2 * d_fw) * 2 ^ steps := by rw [mul_assoc]
      _ ≤ (d_i_plus_steps - 1) * 2 ^ steps := by gcongr;
      _ = d_i - 1 := h_algebraic_identity

  simp only [d_H, d_H_nat] at h_dH_eq
  -- This final line is equivalent to the goal statement.
  rw [h_dH_eq]
  -- ⊢ 2 * ↑Δ₀(f, C_i).toNat < ↑(BBF_CodeDistance ℓ 𝓡 ⟨↑i, ⋯⟩)
  change ((2 : ℕ) : ℕ∞) * ↑Δ₀(f, C_i).toNat < ↑(BBF_CodeDistance ℓ 𝓡 ⟨↑i, by omega⟩)
  rw [←ENat.coe_mul, ENat.coe_lt_coe]
  apply Nat.lt_of_le_pred (n := 2 * Δ₀(f, C_i).toNat) (m := d_i) (h := h_d_i_gt_0)
    (h_final_inequality)
```
| step | lines | tokens | self_hb | incl_hb | pts_if_gone | text |
|---|---|---|---|---|---|---|
| s1 | 7-7 | 4 | - | - | - | `unfold fiberwiseClose at h_fw_dist_lt` |
| s2 | 8-9 | 2 | - | - | - | `unfold hammingClose` |
| s3 | 10-10 | 14 | - | - | - | `let d_fw := fiberwiseDistance 𝔽q β (i :=` |
| s4 | 11-11 | 19 | - | - | - | `let C_i := (BBF_Code 𝔽q β (h_ℓ_add_R_rat` |
| s5 | 12-12 | 6 | - | - | - | `let d_H := Code.distFromCode f C_i` |
| s6 | 13-13 | 14 | - | - | - | `let d_i := BBF_CodeDistance ℓ 𝓡 (⟨i, by ` |
| s7 | 14-14 | 14 | - | - | - | `let d_i_plus_steps := BBF_CodeDistance ℓ` |
| s8 | 16-23 | 90 | 5 | 391 | +2.88 | `have h_d_i_gt_0 : d_i > 0 := by` |
| s9 | 25-29 | 32 | 3 | 264 | +1.29 | `have h_C_i_nonempty : Nonempty C_i := by` |
| s10 | 30-51 | 109 | 196 | 669 | +3.91 | `obtain ⟨g', h_g'_mem, h_g'_min_card⟩ : ∃` |
| s11 | 52-149 | 721 | 10 | 8372 | +34.26 | `have h_dist_le_fw_dist_times_fiber_size ` |
| s12 | 150-162 | 57 | 4 | 640 | +2.66 | `have h_dist_bridge : d_H ≤ d_fw * 2 ^ st` |
| s13 | 163-168 | 18 | 2 | 114 | +0.65 | `have h_fw_bound : 2 * d_fw ≤ d_i_plus_st` |
| s14 | 169-181 | 143 | 5 | 874 | +5.12 | `have h_algebraic_identity : (d_i_plus_st` |
| s15 | 182-187 | 24 | 4 | 189 | +0.95 | `have h_dH_ne_top : d_H ≠ ⊤ := by` |
| s16 | 188-188 | 5 | - | - | - | `let d_H_nat := ENat.toNat d_H` |
| s17 | 189-191 | 12 | - | - | - | `have h_dH_eq : d_H = d_H_nat := (ENat.co` |
| s18 | 192-200 | 96 | 4 | 1571 | +5.53 | `have h_final_inequality : 2 * d_H_nat ≤ ` |
| s19 | 202-203 | 9 | - | - | - | `simp only [d_H, d_H_nat] at h_dH_eq` |
| s20 | 204-205 | 4 | - | - | - | `rw [h_dH_eq]` |
| s21 | 206-206 | 34 | 560 | 618 | +2.09 | `change ((2 : ℕ) : ℕ∞) * ↑Δ₀(f, C_i).toNa` |
| s22 | 207-207 | 7 | - | - | - | `rw [←ENat.coe_mul, ENat.coe_lt_coe]` |
| s23 | 208-209 | 28 | 420 | 420 | +1.53 | `apply Nat.lt_of_le_pred (n := 2 * Δ₀(f, ` |
| total | - | 1463 | - | 15913 | - | versions 4/4 · score 33.33 |
self_hb: heartbeats of the step alone.
incl_hb: heartbeats of the step with its nested steps.
pts_if_gone: upper bound on the points gained by removing the step.
versions: listed versions on which the proof compiles.

## Original proof heartbeats by line (1357 chars, 273 words)
Original proof heartbeats by line
line 59 · 449 self hb · 15 tokens · set ΔH := Finset.filter (fun x => f x ≠ g' x) Finset.univ
line 64 · 480 self hb · 11 tokens · set Y_bad := fiberwiseDisagreementSet 𝔽q β i steps h_i_add_steps f g'
line 73 · 277 self hb · 7 tokens · have h_ΔH_subset_bad_fiber_points : ΔH ⊆ Finset.biUnion Y_bad.toFinset
line 87 · 1483 self hb · 11 tokens · simp only [fiberwiseDisagreementSet, iteratedQuotientMap, ne_eq, Subty…
line 107 · 678 self hb · 21 tokens · set qMapFiber := qMap_total_fiber 𝔽q β (i := ⟨i, by omega⟩) (steps :=…
line 127 · 331 self hb · 8 tokens · have h_card_fiber_of_each_y : ∀ y ∈ Y_bad.toFinset,
line 154 · 275 self hb · 14 tokens · simp only [distFromCode, SetLike.mem_coe, hammingDist, ne_eq, d_H];
line 173 · 362 self hb · 16 tokens · rw [Nat.sub_add_eq_sub_sub_rev (h1 := by omega) (h2 := by omega),
line 197 · 654 self hb · 14 tokens · _ ≤ 2 * (d_fw * 2 ^ steps) := by gcongr
line 199 · 594 self hb · 15 tokens · _ ≤ (d_i_plus_steps - 1) * 2 ^ steps := by gcongr;
line 206 · 618 self hb · 34 tokens · change ((2 : ℕ) : ℕ∞) * ↑Δ₀(f, C_i).toNat < ↑(BBF_CodeDistance ℓ 𝓡 ⟨↑i…
line 208 · 420 self hb · 25 tokens · apply Nat.lt_of_le_pred (n := 2 * Δ₀(f, C_i).toNat) (m := d_i) (h := h…
Measured 15913 heartbeats; 14653 are attributed to lines (top 12 by self hb shown); 1260 (7.9%) are not tied to any line.

## Goals before original steps (227 chars, 28 words)
Goals before original steps
before s1: (unavailable)
before s2: (unavailable)
before s3: (unavailable)
before s4: (unavailable)
before s5: (unavailable)
before s6: (unavailable)
before s7: (unavailable)
before s8: (unavailable)

## Imported declarations (ranked) (6670 chars, 1221 words)
Imported declarations (ranked)
1. decl:AdditiveNTT.sDomain_card · CompPoly.Fields.Binary.AdditiveNTT.Domain · AdditiveNTT.sDomain_card : ∀ {r : ℕ} [inst : NeZero r] {L : Type u} [inst_1 : Field L] [inst_2 : Fintype L] [inst_3 : DecidableEq L] (𝔽q : Type u) [inst_4 : Field 𝔽q] [inst_5 : Fintype 𝔽q] [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] [inst_6 : Algebra 𝔽q L] (β : Fin r → L) [hβ_lin_indep : Fact (LinearIndependent 𝔽q β)] {ℓ R_rate : ℕ…
2. decl:Polynomial.frobenius_identity_in_ground_field · CompPoly.Data.Polynomial.Frobenius · Polynomial.frobenius_identity_in_ground_field : ∀ {Fq : Type u_1} [inst : Field Fq] [inst_1 : Fintype Fq] [Fact (Nat.Prime (ringChar Fq))] (f g : Fq[X]), (f + g) ^ Fintype.card Fq = f ^ Fintype.card Fq + g ^ Fintype.card Fq
3. decl:Fintype.not_linearIndependent_iffₛ · Mathlib.LinearAlgebra.LinearIndependent.Defs · Fintype.not_linearIndependent_iffₛ : ∀ {ι : Type u'} {R : Type u_2} {M : Type u_4} {v : ι → M} [inst : Semiring R] [inst_1 : AddCommMonoid M] [inst_2 : Module R M] [inst_3 : Fintype ι], ¬LinearIndependent R v ↔ ∃ f g, ∑ i, f i • v i = ∑ i, g i • v i ∧ ∃ i, f i ≠ g i
4. decl:Fintype.sum_pow_mul_eq_add_pow · Mathlib.Algebra.BigOperators.Ring.Finset · Fintype.sum_pow_mul_eq_add_pow : ∀ {R : Type u_4} [inst : CommSemiring R] (ι : Type u_5) [inst_1 : Fintype ι] (a b : R), ∑ s, a ^ #s * b ^ (Fintype.card ι - #s) = (a + b) ^ Fintype.card ι
5. decl:Polynomial.frobenius_identity_in_algebra · CompPoly.Data.Polynomial.Frobenius · Polynomial.frobenius_identity_in_algebra : ∀ {Fq : Type u_1} [inst : Field Fq] [inst_1 : Fintype Fq] {L : Type u_2} [inst_2 : CommRing L] [Algebra Fq L] [Nontrivial L] [Fact (Nat.Prime (ringChar Fq))] (f g : L[X]), (f + g) ^ Fintype.card Fq = f ^ Fintype.card Fq + g ^ Fintype.card Fq
6. decl:Fin.lt_card_filter_univ_iff_apply_of_imp · Mathlib.Data.Fintype.Fin · Fin.lt_card_filter_univ_iff_apply_of_imp : ∀ {n : ℕ} {j : Fin n} (p : Fin n → Prop) [inst : DecidablePred p], (∀ (i j : Fin n), j ≤ i → p i → p j) → (↑j < #{i | p i} ↔ p j)
7. decl:Finset.card_le_card_biUnion_add_card_fiber · Mathlib.Algebra.Order.BigOperators.Group.Finset · Finset.card_le_card_biUnion_add_card_fiber : ∀ {ι : Type u_1} {α : Type u_2} [inst : DecidableEq α] {s : Finset ι} {f : ι → Finset α}, (↑s).PairwiseDisjoint f → #s ≤ #(s.biUnion f) + #({i ∈ s | f i = ∅})
8. decl:Finset.sum_card_le · Mathlib.Algebra.Order.BigOperators.Group.Finset · Finset.sum_card_le : ∀ {α : Type u_2} [inst : DecidableEq α] {B : Finset (Finset α)} {n : ℕ} [inst_1 : Fintype α], (∀ (a : α), #({b ∈ B | a ∈ b}) ≤ n) → ∑ s ∈ B, #s ≤ Fintype.card α * n
9. decl:Finset.le_sum_card · Mathlib.Algebra.Order.BigOperators.Group.Finset · Finset.le_sum_card : ∀ {α : Type u_2} [inst : DecidableEq α] {B : Finset (Finset α)} {n : ℕ} [inst_1 : Fintype α], (∀ (a : α), n ≤ #({b ∈ B | a ∈ b})) → Fintype.card α * n ≤ ∑ s ∈ B, #s
10. decl:Affine.instNonemptySubtypeForallMemFinsetImageFinUniv_arkLib · ArkLib.Data.CodingTheory.Prelims · Affine.instNonemptySubtypeForallMemFinsetImageFinUniv_arkLib : ∀ {ι : Type u_1} [inst : Fintype ι] {F : Type u_2} {k : ℕ} [inst_1 : DecidableEq F] [NeZero k] {f : Fin k → ι → F}, Nonempty ↥(image f univ)
11. decl:Fin.le_iff_lt_succ · CompPoly.Data.Fin.BigOperators · Fin.le_iff_lt_succ : ∀ {r : ℕ} [inst : NeZero r] (a b : Fin r), ↑b + 1 < r → (a ≤ b ↔ a < b + 1)
12. decl:Code.distFromCode_le_card_index_of_Nonempty · ArkLib.Data.CodingTheory.Basic.Distance · Code.distFromCode_le_card_index_of_Nonempty : ∀ {n : Type u_1} [inst : Fintype n] {R : Type u_2} [inst_1 : DecidableEq R] (u : n → R) {C : Set (n → R)} [Nonempty ↑C], Δ₀(u, C) ≤ ↑(Fintype.card n)
13. decl:Fin.le_succ · CompPoly.Data.Fin.BigOperators · Fin.le_succ : ∀ {r : ℕ} [inst : NeZero r] (a : Fin r), ↑a + 1 < r → a ≤ a + 1
14. decl:Finset.sum_card · Mathlib.Algebra.Order.BigOperators.Group.Finset · Finset.sum_card : ∀ {α : Type u_2} [inst : DecidableEq α] {B : Finset (Finset α)} {n : ℕ} [inst_1 : Fintype α], (∀ (a : α), #({b ∈ B | a ∈ b}) = n) → ∑ s ∈ B, #s = Fintype.card α * n
15. decl:Finset.card_filter_le_iff · Mathlib.Data.Finset.Card · Finset.card_filter_le_iff : ∀ {α : Type u_1} (s : Finset α) (P : α → Prop) [inst : DecidablePred P] (n : ℕ), #(filter P s) ≤ n ↔ ∀ s' ⊆ s, n < #s' → ∃ a ∈ s', ¬P a
16. decl:Fin.sum_univ_pow_two_even_add_odd · CompPoly.Data.Fin.BigOperators · Fin.sum_univ_pow_two_even_add_odd : ∀ {n : ℕ} {M : Type u_1} [inst : AddCommMonoid M] (f : ℕ → M), ∑ i, f (2 * ↑i) + ∑ i, f (2 * ↑i + 1) = ∑ i, f ↑i
17. decl:FiniteField.sum_pow_lt_card_sub_one · Mathlib.FieldTheory.Finite.Basic · FiniteField.sum_pow_lt_card_sub_one : ∀ (K : Type u_1) [inst : Field K] [inst_1 : Fintype K], ∀ i < Fintype.card K - 1, ∑ x, x ^ i = 0
18. decl:Fintype.card_subtype · Mathlib.Data.Fintype.Card · Fintype.card_subtype : ∀ {α : Type u_1} [inst : Fintype α] (p : α → Prop) [inst_1 : Fintype { a // p a }] [inst_2 : DecidablePred p], Fintype.card { x // p x } = #{x | p x}
19. decl:Fin.sum_pow_mul_eq_add_pow · Mathlib.Algebra.BigOperators.Fin · Fin.sum_pow_mul_eq_add_pow : ∀ {n : ℕ} {R : Type u_3} [inst : CommSemiring R] (a b : R), ∑ s, a ^ #s * b ^ (n - #s) = (a + b) ^ n
20. decl:Fin.val_add_one' · CompPoly.Data.Fin.BigOperators · Fin.val_add_one' : ∀ {r : ℕ} [inst : NeZero r] (a : Fin r), ↑a + 1 < r → ↑(a + 1) = ↑a + 1
21. decl:Fintype.card_fin_lt_of_le · Mathlib.Data.Fintype.Card · Fintype.card_fin_lt_of_le : ∀ {m n : ℕ}, m ≤ n → Fintype.card { i // ↑i < m } = m
22. decl:Fin.mk_eq_zero · Init.Data.Fin.Lemmas · Fin.mk_eq_zero : ∀ {n a : ℕ} {ha : a < n} [inst : NeZero n], ⟨a, ha⟩ = 0 ↔ a = 0
23. decl:Fin.zero_eq_mk · Init.Data.Fin.Lemmas · Fin.zero_eq_mk : ∀ {n a : ℕ} {ha : a < n} [inst : NeZero n], 0 = ⟨a, ha⟩ ↔ a = 0
24. decl:Fin.lt_add_one_of_succ_lt · Mathlib.Algebra.Group.Fin.Basic · Fin.lt_add_one_of_succ_lt : ∀ {n : ℕ} [inst : NeZero n] {a : Fin n}, ↑a + 1 < n → a < a + 1
25. decl:Fin.lt_succ' · CompPoly.Data.Fin.BigOperators · Fin.lt_succ' : ∀ {r : ℕ} [inst : NeZero r] (a : Fin r), ↑a + 1 < r → a < a + 1
26. decl:LinearCombination.linearCombination_ne_zero · ArkLib.Data.CodingTheory.Prelims · LinearCombination.linearCombination_ne_zero : ∀ {F : Type u_4} [inst : Field F] {ℓ : Type u_5} [inst_1 : Fintype ℓ] {M : Type u_6} [inst_2 : AddCommMonoid M] [inst_3 : Module F M] {P : ℓ → M}, LinearIndependent F P → ∀ {v : ℓ → F}, v ≠ 0 → ∑ j, v j • P j ≠ 0
27. decl:not_linearIndependent_iffₛ · Mathlib.LinearAlgebra.LinearIndependent.Defs · not_linearIndependent_iffₛ : ∀ {ι : Type u'} {R : Type u_2} {M : Type u_4} {v : ι → M} [inst : Semiring R] [inst_1 : AddCommMonoid M] [inst_2 : Module R M], ¬LinearIndependent R v ↔ ∃ s f g, ∑ i ∈ s, f i • v i = ∑ i ∈ s, g i • v i ∧ ∃ i ∈ s, f i ≠ g i

## Definitions of project types and predicates in the statement (5876 chars, 893 words)
Definitions of project types and predicates in the statement
decl:Binius.BinaryBasefold.qMap_total_fiber [def] Binius.BinaryBasefold.qMap_total_fiber : {r : ℕ} →
  [inst : NeZero r] →
    {L : Type} →
      [inst_1 : Field L] →
        [inst_2 : Fintype L] →
          [inst_3 : DecidableEq L] →
            (𝔽q : Type) →
              [inst_4 : Field 𝔽q] →
                [inst_5 : Fintype 𝔽q] →
                  [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] →
                    [inst_6 : Algebra 𝔽q L…
  := fun {r} [NeZero r] {L} [Field L] [Fintype L] [DecidableEq L] 𝔽q [Field 𝔽q] [Fintype 𝔽q] [Fact (Nat.Prime (ringChar 𝔽q))]
    [Algebra 𝔽q L] β [Fact (LinearIndependent 𝔽q β)] {ℓ 𝓡} {h_ℓ_add_R_rate} i steps h_i_add_steps y =>
  if h_steps : steps = 0 then
    Eq.ndrec (motive := fun steps =>
      (h_i_add_steps : ↑i + steps < ℓ + 𝓡) →
        ↥(sDomain 𝔽q β h_ℓ_add_R_rate ⟨↑i + steps, ⋯⟩) → Fin (2 ^ steps) → ↥(sDomain 𝔽q β h_ℓ_add_R_rate i))
      (fun h_i_add_steps y x => ⋯.mp y) ⋯ h_i_add_steps y
  else
    have basis_y := sDomain_basis 𝔽q β h_ℓ_add_R_rate ⟨↑i + steps, ⋯⟩ h_i_add_steps;
    h…
decl:Binius.BinaryBasefold.pointToIterateQuotientIndex [def] Binius.BinaryBasefold.pointToIterateQuotientIndex : {r : ℕ} →
  [inst : NeZero r] →
    {L : Type} →
      [inst_1 : Field L] →
        [inst_2 : Fintype L] →
          [inst_3 : DecidableEq L] →
            (𝔽q : Type) →
              [inst_4 : Field 𝔽q] →
                [inst_5 : Fintype 𝔽q] →
                  [DecidableEq 𝔽q] →
                    [h_Fq_char_prime : Fact (Nat.Prime (ringChar …
  := fun {r} [NeZero r] {L} [Field L] [Fintype L] [DecidableEq L] 𝔽q [Field 𝔽q] [Fintype 𝔽q] [DecidableEq 𝔽q]
    [Fact (Nat.Prime (ringChar 𝔽q))] [Algebra 𝔽q L] β [Fact (LinearIndependent 𝔽q β)] {ℓ 𝓡} [NeZero 𝓡] {h_ℓ_add_R_rate}
    i steps h_i_add_steps x =>
  let basis_x := sDomain_basis 𝔽q β h_ℓ_add_R_rate ⟨↑i, ⋯⟩ ⋯;
  let x_coeffs := basis_x.repr x;
  let k_bits := fun j => if x_coeffs ⟨↑j, ⋯⟩ = 0 then 0 else 1;
  have k := binaryFinMapToNat k_bits ⋯;
  k
decl:Binius.BinaryBasefold.fiber_coeff [def] Binius.BinaryBasefold.fiber_coeff : {r : ℕ} →
  (𝔽q : Type) →
    [inst : Field 𝔽q] →
      {ℓ 𝓡 : ℕ} →
        (i : Fin r) → (steps : ℕ) → Fin (ℓ + 𝓡 - ↑i) → Fin (2 ^ steps) → (Fin (ℓ + 𝓡 - (↑i + steps)) →₀ 𝔽q) → 𝔽q
  := fun {r} 𝔽q [Field 𝔽q] {ℓ 𝓡} i steps j elementIdx y_coeffs =>
  if hj : ↑j < steps then if (↑j).getBit ↑elementIdx = 0 then 0 else 1 else y_coeffs ⟨↑j - steps, ⋯⟩
decl:Binius.BinaryBasefold.Fin2ToF2 [def] Binius.BinaryBasefold.Fin2ToF2 : (𝔽q : Type u_1) → [Ring 𝔽q] → Fin 2 → 𝔽q
  := fun 𝔽q [Ring 𝔽q] k => if k = 0 then 0 else 1
decl:Binius.BinaryBasefold.OracleFunction [def] Binius.BinaryBasefold.OracleFunction : {r : ℕ} →
  [NeZero r] →
    {L : Type} →
      [inst : Field L] →
        [Fintype L] →
          [DecidableEq L] →
            (𝔽q : Type) →
              [inst_3 : Field 𝔽q] →
                [Fintype 𝔽q] →
                  [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] →
                    [inst_5 : Algebra 𝔽q L] →
                      (β : Fin r →…
  := fun {r} [NeZero r] {L} [Field L] [Fintype L] [DecidableEq L] 𝔽q [Field 𝔽q] [Fintype 𝔽q] [Fact (Nat.Prime (ringChar 𝔽q))]
    [Algebra 𝔽q L] β [Fact (LinearIndependent 𝔽q β)] {ℓ 𝓡} {h_ℓ_add_R_rate} i =>
  ↥(sDomain 𝔽q β h_ℓ_add_R_rate ⟨↑i, ⋯⟩) → L
decl:Binius.BinaryBasefold.fiberwiseDistance [def] Binius.BinaryBasefold.fiberwiseDistance : {r : ℕ} →
  [inst : NeZero r] →
    {L : Type} →
      [inst_1 : Field L] →
        [inst_2 : Fintype L] →
          [inst_3 : DecidableEq L] →
            (𝔽q : Type) →
              [inst_4 : Field 𝔽q] →
                [inst_5 : Fintype 𝔽q] →
                  [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] →
                    [inst_6 : Algebra 𝔽q …
  := fun {r} [NeZero r] {L} [Field L] [Fintype L] [DecidableEq L] 𝔽q [Field 𝔽q] [Fintype 𝔽q] [Fact (Nat.Prime (ringChar 𝔽q))]
    [Algebra 𝔽q L] β [Fact (LinearIndependent 𝔽q β)] [Fact (β 0 = 1)] {ℓ 𝓡} {h_ℓ_add_R_rate} i steps [NeZero steps]
    h_i_add_steps f =>
  have C_i := BBF_Code 𝔽q β ⟨↑i, ⋯⟩;
  have disagreement_sizes := (fun g => (fiberwiseDisagreementSet 𝔽q β i steps h_i_add_steps f ↑g).ncard) '' Set.univ;
  sInf disagreement_sizes
decl:Binius.BinaryBasefold.fiberwiseDisagreementSet [def] Binius.BinaryBasefold.fiberwiseDisagreementSet : {r : ℕ} →
  [inst : NeZero r] →
    {L : Type} →
      [inst_1 : Field L] →
        [inst_2 : Fintype L] →
          [inst_3 : DecidableEq L] →
            (𝔽q : Type) →
              [inst_4 : Field 𝔽q] →
                [inst_5 : Fintype 𝔽q] →
                  [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] →
                    [inst_6 : Alge…
  := fun {r} [NeZero r] {L} [Field L] [Fintype L] [DecidableEq L] 𝔽q [Field 𝔽q] [Fintype 𝔽q] [Fact (Nat.Prime (ringChar 𝔽q))]
    [Algebra 𝔽q L] β [Fact (LinearIndependent 𝔽q β)] [Fact (β 0 = 1)] {ℓ 𝓡} {h_ℓ_add_R_rate} i steps [NeZero steps]
    h_i_add_steps f g =>
  {y | ∃ x, iteratedQuotientMap 𝔽q β h_ℓ_add_R_rate i steps h_i_add_steps x = y ∧ f x ≠ g x}
decl:Binius.BinaryBasefold.fiberwiseClose [def] Binius.BinaryBasefold.fiberwiseClose : {r : ℕ} →
  [inst : NeZero r] →
    {L : Type} →
      [inst_1 : Field L] →
        [inst_2 : Fintype L] →
          [inst_3 : DecidableEq L] →
            (𝔽q : Type) →
              [inst_4 : Field 𝔽q] →
                [inst_5 : Fintype 𝔽q] →
                  [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] →
                    [inst_6 : Algebra 𝔽q L] …
  := fun {r} [NeZero r] {L} [Field L] [Fintype L] [DecidableEq L] 𝔽q [Field 𝔽q] [Fintype 𝔽q] [Fact (Nat.Prime (ringChar 𝔽q))]
    [Algebra 𝔽q L] β [Fact (LinearIndependent 𝔽q β)] [Fact (β 0 = 1)] {ℓ 𝓡} {h_ℓ_add_R_rate} i steps [NeZero steps]
    h_i_add_steps f =>
  2 * ↑(fiberwiseDistance 𝔽q β i steps h_i_add_steps f) < ↑(BBF_CodeDistance ℓ 𝓡 ⟨↑i + steps, ⋯⟩)

## Source-named declarations (7117 chars, 767 words)
Source-named declarations
Qualified name [kind] S:statement lines P:proof lines U:lines whose position could not be placed (no top-level `:=` found); use `decl:<name>` as its source handle.
decl:AdditiveNTT.intermediateNormVpoly [def] S:- P:97
decl:AdditiveNTT.iteratedQuotientMap [def] S:- P:82,87,87,99,99
decl:AdditiveNTT.sDomain [def] S:- P:91
decl:Algebra [inductive] S:-1538,-1538 P:-
decl:Binius.BinaryBasefold.BBF_Code [def] S:- P:11,27
decl:Binius.BinaryBasefold.BBF_CodeDistance [def] S:- P:13,14,17,17,170,170,206
decl:Binius.BinaryBasefold.OracleFunction [def] S:3 P:-
decl:Binius.BinaryBasefold.card_qMap_total_fiber [theorem] S:- P:123
decl:Binius.BinaryBasefold.fiberwiseClose [def] S:4 P:7
decl:Binius.BinaryBasefold.fiberwiseDisagreementSet [def] S:- P:31,33,64,87,87
decl:Binius.BinaryBasefold.fiberwiseDistance [def] S:- P:10
decl:Binius.BinaryBasefold.hammingClose [def] S:6 P:8
decl:Binius.BinaryBasefold.is_fiber_iff_generates_quotient_point [theorem] S:- P:112
decl:Binius.BinaryBasefold.pointToIterateQuotientIndex [def] S:- P:110
decl:Binius.BinaryBasefold.qMap_total_fiber [def] S:- P:74,107,128
decl:Binius.BinaryBasefold.qMap_total_fiber_disjoint [theorem] S:- P:144
decl:CharP [inductive] S:-1541,-2,-1541 P:-
decl:Code.distFromCode [def] S:- P:12,154,154
decl:Code.distFromCode_eq_top_iff_empty [theorem] S:- P:184
decl:DecidableEq [def] S:-1541,-1540,-1541,-1540 P:-
decl:ENat.coe_le_coe [theorem] S:- P:57,57,194,194
decl:ENat.coe_lt_coe [theorem] S:- P:207,207
decl:ENat.coe_mul [theorem] S:- P:57,57,207,207
decl:ENat.coe_toNat [theorem] S:- P:189
decl:ENat.toNat [def] S:- P:188
decl:Eq.symm [theorem] S:- P:49,195
decl:Fact [inductive] S:-1539,-1539,-1537,-1536,-1539,-1539,-1537,-1536 P:-
decl:Field [inductive] S:-1541,-1540,-1541,-1540 P:-
decl:Fin [inductive] S:-1537,-1537,1 P:76,130
decl:Fin.val [def] S:2 P:14,18,18,19,21,21,27
decl:Finset [inductive] S:- P:76,130
decl:Finset.biUnion [def] S:- P:73
decl:Finset.card [def] S:- P:60
decl:Finset.card_biUnion [theorem] S:- P:119,119
decl:Finset.card_le_card [theorem] S:- P:117
decl:Finset.coe_univ [theorem] S:- P:109,109,134,134,146,146
decl:Finset.filter [def] S:- P:59
decl:Finset.mem_biUnion [theorem] S:- P:83
decl:Finset.mem_filter [theorem] S:- P:79,79,88,88
decl:Finset.mem_image [theorem] S:- P:109,109
decl:Finset.mem_univ [theorem] S:- P:88,88,109,109
decl:Finset.sum_congr [theorem] S:- P:135
decl:Finset.sum_const [theorem] S:- P:137,137
decl:Finset.univ [def] S:- P:59,59,76,76,130,130
decl:Fintype [inductive] S:-1541,-1540,-1541,-1540 P:69
decl:Fintype.card [def] S:-1539,-1539 P:128
decl:Fintype.card_ofFinset [theorem] S:- P:125,125,134,134
decl:Fintype.ofFinite [def] S:- P:69
decl:Function.onFun [def] S:- P:146,146
decl:Iff.mpr [theorem] S:- P:83
decl:InfSet.sInf [def] S:- P:41
decl:LinearIndependent [def] S:-1537,-1537 P:-
decl:Nat.Prime [def] S:-1539,-1539 P:-
decl:Nat.add_sub_cancel [theorem] S:- P:174,177
decl:Nat.card_coe_set_eq [theorem] S:- P:139,139
decl:Nat.card_eq_fintype_card [theorem] S:- P:141,141
decl:Nat.le_of_lt_succ [theorem] S:- P:165
decl:Nat.lt_add_of_pos_right [theorem] S:- P:20
decl:Nat.lt_add_of_pos_right_of_le [theorem] S:- P:75,108,129
decl:Nat.lt_of_le_pred [theorem] S:- P:208
decl:Nat.ofNat_pos [theorem] S:- P:137,137
decl:Nat.pos_of_neZero [theorem] S:- P:20
decl:Nat.pow_add [theorem] S:- P:171,171,171,171
decl:Nat.pow_lt_pow_right [theorem] S:- P:22
decl:Nat.sInf_mem [theorem] S:- P:41
decl:Nat.sub_add_eq_sub_sub_rev [theorem] S:- P:173,176
decl:Nat.sub_lt_sub_right [theorem] S:- P:19
decl:Nat.sub_mul [theorem] S:- P:171,171
decl:NeZero [inductive] S:-1542,-1535,-1535,-1535,-2,-1542,-1535,-1535,-1535,2 P:-
decl:Nonempty [inductive] S:- P:25
decl:Polynomial.eval [def] S:- P:96
decl:Set.Nonempty [def] S:- P:36
decl:Set.image_nonempty [theorem] S:- P:37
decl:Set.image_univ [theorem] S:- P:109,109,125,125,134,134
decl:Set.mem_image [theorem] S:- P:46,46
decl:Set.nonempty_iff_ne_empty' [theorem] S:- P:185
decl:Set.toFinset [def] S:- P:73,85,127
decl:Set.toFinset_card [theorem] S:- P:122,122,137,137
decl:Set.toFinset_range [theorem] S:- P:109,109
decl:Set.toFinset_setOf [theorem] S:- P:88,88
decl:Set.univ [def] S:- P:34,34
decl:Set.univ_nonempty [theorem] S:- P:39,39
decl:SetLike.mem_coe [theorem] S:- P:154,154
decl:Submodule.coe_mem [theorem] S:- P:92,133
decl:Submodule.nonempty [theorem] S:- P:27
decl:Subtype.coe_eta [theorem] S:- P:102,102,103,103
decl:Subtype.exists [theorem] S:- P:87,87
decl:Subtype.forall [theorem] S:- P:126,126
decl:Subtype.property [theorem] S:- P:49
decl:Subtype.val [def] S:- P:49,90
decl:WithTop.coe_lt_coe [theorem] S:- P:165
decl:and_self [theorem] S:- P:104,104
decl:ge_iff_le [theorem] S:- P:138,138
decl:hammingDist [def] S:- P:52,60,61,61,152,154,154
decl:id [def] S:- P:49,195
decl:le_of_eq_of_le [theorem] S:- P:195
decl:le_refl [theorem] S:- P:141,141
decl:le_trans [theorem] S:- P:152
decl:mul_assoc [theorem] S:- P:198,198
decl:mul_le_mul_right [theorem] S:- P:138,138
decl:ne_eq [theorem] S:- P:61,61,87,87,102,102,154,154,183,183
decl:nonempty_subtype [theorem] S:- P:26,26
decl:not_false_eq_true [theorem] S:- P:102,102,104,104
decl:pow_pos [theorem] S:- P:137,137
decl:rfl [def] S:- P:135,135
decl:ringChar [def] S:-1539,-1539 P:-
decl:sInf_le [theorem] S:- P:157
decl:smul_eq_mul [theorem] S:- P:137,137
decl:true_and [theorem] S:- P:88,88,105,105,109,109

Signature preview: 5 shown of 109 distinct source names; 0 unavailable.
[decl:Binius.BinaryBasefold.BBF_Code · def · this file] Binius.BinaryBasefold.BBF_Code : {r : ℕ} → [inst : NeZero r] → {L : Type} → [inst_1 : Field L] → [inst_2 : Fintype L] → [inst_3 : DecidableEq L] → (𝔽q : Type) → [inst_4 : Field 𝔽q] → [inst_5 : Fintype 𝔽q] → [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] → [inst_6 : Algebra 𝔽q L] → (β : Fin r → L) → [hβ_lin_indep :…
[decl:Binius.BinaryBasefold.BBF_CodeDistance · def · this file] Binius.BinaryBasefold.BBF_CodeDistance : (ℓ : ℕ) → ℕ → Fin (ℓ + 1) → ℕ
[decl:Binius.BinaryBasefold.OracleFunction · def · this file] Binius.BinaryBasefold.OracleFunction : {r : ℕ} → [NeZero r] → {L : Type} → [inst : Field L] → [Fintype L] → [DecidableEq L] → (𝔽q : Type) → [inst_3 : Field 𝔽q] → [Fintype 𝔽q] → [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] → [inst_5 : Algebra 𝔽q L] → (β : Fin r → L) → [hβ_lin_indep : Fact (LinearIndependent 𝔽q β)]…
[decl:Binius.BinaryBasefold.card_qMap_total_fiber · theorem · this file] Binius.BinaryBasefold.card_qMap_total_fiber : ∀ {r : ℕ} [inst : NeZero r] {L : Type} [inst_1 : Field L] [inst_2 : Fintype L] [inst_3 : DecidableEq L] (𝔽q : Type) [inst_4 : Field 𝔽q] [inst_5 : Fintype 𝔽q] [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] [inst_6 : Algebra 𝔽q L] (β : Fin r → L) [hβ_lin_indep : Fact (Lin…
[decl:Binius.BinaryBasefold.fiberwiseClose · def · this file] Binius.BinaryBasefold.fiberwiseClose : {r : ℕ} → [inst : NeZero r] → {L : Type} → [inst_1 : Field L] → [inst_2 : Fintype L] → [inst_3 : DecidableEq L] → (𝔽q : Type) → [inst_4 : Field 𝔽q] → [inst_5 : Fintype 𝔽q] → [h_Fq_char_prime : Fact (Nat.Prime (ringChar 𝔽q))] → [inst_6 : Algebra 𝔽q L] → (β : Fin r → L) → [hβ_lin_in…

## Elaborated proof dependencies (1381 chars, 222 words)
Elaborated proof dependencies
Qualified declaration names used by the original proof; project and this file first.
decl:Binius.BinaryBasefold.fin_ℓ_steps_lt_ℓ_add_R
decl:Finset.filter_congr
decl:Fintype.card_congr'
decl:LE.le.trans
decl:Set.toFinset_congr
decl:mul_le_mul'

Other categories: generated 35, instance 9, axiom 1, tactic 2, core 18; also source-named: 52.
Signature preview: 5 shown of 6 helpers; 0 unavailable.
[decl:Binius.BinaryBasefold.fin_ℓ_steps_lt_ℓ_add_R · theorem · this file] Binius.BinaryBasefold.fin_ℓ_steps_lt_ℓ_add_R : ∀ {ℓ 𝓡 : ℕ} [NeZero 𝓡] (i : Fin ℓ) (steps : ℕ), ↑i + steps ≤ ℓ → ↑i + steps < ℓ + 𝓡
[decl:Finset.filter_congr · theorem · Mathlib.Data.Finset.Filter] Finset.filter_congr : ∀ {α : Type u_1} {p q : α → Prop} [inst : DecidablePred p] [inst_1 : DecidablePred q] {s : Finset α}, (∀ x ∈ s, p x ↔ q x) → filter p s = filter q s
[decl:Fintype.card_congr' · theorem · Mathlib.Data.Fintype.Card] Fintype.card_congr' : ∀ {α β : Type u_4} [inst : Fintype α] [inst_1 : Fintype β], α = β → Fintype.card α = Fintype.card β
[decl:LE.le.trans · theorem · Mathlib.Order.Basic] LE.le.trans : ∀ {α : Type u_1} [inst : Preorder α] {a b c : α}, a ≤ b → b ≤ c → a ≤ c
[decl:Set.toFinset_congr · theorem · Mathlib.Data.Fintype.Sets] Set.toFinset_congr : ∀ {α : Type u_1} {s t : Set α} [inst : Fintype ↑s] [inst_1 : Fintype ↑t], s = t → s.toFinset = t.toFinset

## Local variables (625 chars, 90 words)
Local variables
Local variable name : type; lines are where the Lean local context exposes the variable.
C_i : Submodule L (↥(sDomain 𝔽q β h_ℓ_add_R_rate ⟨↑⟨↑i, ⋯⟩, ⋯⟩) → L) [scope: theorem proof context; lines: 12,25,26,30,33,184,206,208]
L : Type [scope: theorem proof context; lines: -1541,-1538,-1537,-2]
S : Set ℕ [scope: theorem proof context; lines: 36,41]
X : L [scope: theorem proof context; lines: 91,93,96,99,100,101]
Y_bad : Set ↥(sDomain 𝔽q β h_ℓ_add_R_rate ⟨↑i + steps, ⋯⟩) [scope: theorem proof context; lines: 64,69,73,85,88,127]
d_H : ℕ∞ [scope: theorem proof context; lines: 150,152,154,182,183,188,189,202]

