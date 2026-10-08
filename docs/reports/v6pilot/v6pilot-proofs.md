# v6 pilot: proof-level analysis

Scoring recap (from arena/scoring.py): proxy = mean(token reduction %, heartbeat reduction %, compat %). Per theorem the exchange rate is 100/(3*ref_tokens) pt per token and 100/(3*ref_HB) pt per heartbeat. The pinned token counter (check_proof.py `_proof_length`) counts every identifier (dotted names are ONE token), every punctuation char (`·`, `(`, `,`, `⟨`, `⟩`, `:=` etc.), and each blank line; indentation is free. So the cheapest golf is fewer identifiers and fewer brackets, not shorter names.

## 1. Core.InitsUpdatesComm (ref 224 tok / 4251 HB)

Rates: 1 tok = 0.149 pt; 100 HB = 0.784 pt; 1 tok ~ 19 HB.

| who | tok | HB | proxy | route |
|---|---|---|---|---|
| reference | 224 | 4251 | ~0 | induction on UpdateStates, per-step lemmas (UpdateStateNotDefMonotone', updatedStateComm', updatedStateUpdate, InitStatesSomeMonotone), simp_all, split |
| DeepSeek best | 83 | 202 | 86.07 | no induction; whole-list lemmas |
| Qwen best | 81 | 246 | 86.02 | no induction; simp+rw [updatedStatesComm]+simp_all |
| Qwen 79-token | 79 | 286 | 86.00 | same, simp_all closes the Disjoint goal |
| Luna best | 86 | 267 | 85.11 | no induction; rw-heavy, `by` block inside anon constructor |
| hybrid (verified) | 76 | 203 | 87.10 | see below |

Dominant structural decision: abandon the reference's induction over `UpdateStates` and use the list-level lemmas `updatedStatesInit`, `updatedStatesUpdate`, `updatedStatesComm`, `updatedStatesDefMonotone`, `UpdateStatesDefined'` (none of these appear in the reference's dependency list; all three models found them through search/exploration). The whole proof then is: rewrite both endpoints with `UpdateStatesUpdated`/`InitStatesUpdated`, commute with `updatedStatesComm` (side goal: `ks'.Disjoint ks` after `List.unzip_zip`), and discharge the two bulk constructors. All three models converged to this; the 5-8 token and 50-80 HB differences are pure tactic-level golf. Going from induction to bulk lemmas was worth ~ 140 tokens (21 pt of the token axis) and ~4000 HB (~31 pt of the HB axis); everything after that is worth < 1.5 pt.

DeepSeek best (83/202):
```lean
  intro Hup Hinit
  cases UpdateStatesUpdated Hup
  cases InitStatesUpdated Hinit
  unfold updatedStates
  have L := UpdateStatesLength Hup
  have L2 := InitStatesLength Hinit
  refine ⟨_, rfl, updatedStatesInit L2 (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hup) (InitStatesNodup Hinit),
    (updatedStatesComm ?_).symm ▸ updatedStatesUpdate L (updatedStatesDefMonotone (UpdateStatesDefined' Hup))⟩
  simp [List.unzip_zip L, List.unzip_zip L2]
  intro a ha ha'
  simpa [InitStatesNotDefined Hinit a ha'] using UpdateStatesDefined Hup a ha
```
(`cases` on the `σ' = updatedStates ..` equations substitutes the states away: cheaper than `rw`, and the `▸` cast replaces a `rw [updatedStatesComm (by ..)]`.)

Qwen best (81/246; the 79-token variant is the same with `simp_all [List.unzip_zip]`): `simp [InitStatesUpdated .., UpdateStatesUpdated .., updatedStates]; rw [updatedStatesComm]; · exact ⟨..⟩; · simp_all [List.unzip_zip, ...]; intro x hx hx'; have h := ..; simp_all [...]`. Fewer tokens because simp does the rewrite+unfold in one step and `simp_all` replaces explicit `List.unzip_zip L` args, but `simp_all` is ~70 HB and the double `simp` ~40 HB more than DeepSeek's.

Luna best (86/267): `exact ⟨_, rfl, updatedStatesInit .., by rw [..]; unfold updatedStates; rw [← updatedStatesComm (by simp [List.unzip_zip, ..]; intro x hx hx'; simpa [..] using ..)]; apply updatedStatesUpdate ..; exact updatedStatesDefMonotone ..⟩`. Same lemmas, extra `rw`s/`apply`/`exact` lines cost ~6 tokens and ~65 HB.

Hybrid (verified cold, 3 versions, 76 tok / 203 HB / 87.10; saved as runs/analysis/Core_InitsUpdatesComm-hybrid-v6-87.10.lean; identical to the earlier hybrid-87.10, re-verified this session):
```lean
  intro Hup Hinit
  have := InitStatesLength Hinit
  refine .intro _ ⟨rfl, updatedStatesInit this (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hup) (InitStatesNodup Hinit), ?_⟩
  have := UpdateStatesLength Hup
  cases InitStatesUpdated Hinit
  cases UpdateStatesUpdated Hup
  unfold updatedStates
  refine updatedStatesComm ?_ ▸ updatedStatesUpdate this (updatedStatesDefMonotone (UpdateStatesDefined' Hup))
  simp [List.unzip_zip, *]
  intro a h2 h1
  cases InitStatesNotDefined Hinit a h2 ▸ UpdateStatesDefined Hup a h1
```
Ideas combined: DeepSeek's `cases ..Updated` + bulk-lemma skeleton; Qwen's "let simp use the in-context length facts (`*`)" to drop the explicit `List.unzip_zip L L2` args and the named `L`/`L2`; the `exists/refine` split so the `UpdateStates` goal is handled after the `cases` (no `_` unifier hassle); Luna's idea of closing the final contradiction with a term (`cases (h ▸ h')`, found by the previous attempt) instead of `simpa`. The `.intro _ ⟨` form saves nothing in tokens vs `⟨_, rfl, .., ?_⟩` but is ~14 HB cheaper (203 vs 217 measured).

Tried this session (each cold, 3 versions): `⟨_, rfl, ..⟩` instead of `.intro` 76/217/86.99; `simp only [List.unzip_zip, *]` 77/202/86.96; dropping `unfold updatedStates` fails at the `▸` (motive); `simp [.., List.Disjoint]` 78/283/86.17; `exact (.. ▸ ..: _)` type mismatch. Verdict: 87.10 is a local optimum (10 attempts incl. the earlier session; no variant beat it).

Per-axis headroom (profile events, DeepSeek 15c509, 83 tok/204 HB): HB axis is already at 95.2% reduction (30.4/33.3); the biggest self-costs are `refine (updatedStatesComm ?_).symm ▸ ⟨_, rfl, ..⟩` 83 HB (elaboration of the `▸` cast + unifying the constructor tuple), `simp [List.unzip_zip ..]` 19, `cases UpdateStatesUpdated` 15, `simpa` 14; 54 HB unattributed (kernel/`theorem` overhead; not reducible). Even removing everything would gain < 1.2 pt on HB. Token axis: 76/224 = 66% reduced -> 22.0/33.3; headroom 11.3 pt but the floor for the lemma-applications alone is ~ 60 tokens (each lemma application with its args costs 4-9 tokens and five are required).

## 2. Cslib.CCS.bisimilarity_congr_choice (ref 251 tok / 3858 HB)

Rates: 1 tok = 0.133 pt (~15 HB); 100 HB = 0.864 pt.

| who | tok | HB | proxy | route |
|---|---|---|---|---|
| reference | 251 | 3858 | ~0 | `exists ChoiceBisim`; prove IsBisimulation by hand: left/right x (choice/bisim) = 4 case blocks, `obtain` + `exists`/`constructor` each |
| DeepSeek best | 85 | 263 | 86.44 | `rw [HomBisimilarity.symm_simulation]`: only ONE simulation direction + `Std.Symm ChoiceBisim` via `ChoiceBisim.rec` |
| Qwen best | 136 | 406 | 78.43 | both directions, `constructor <;> intro <;> cases htr with`, `first | follow_fst | follow_snd` |
| Qwen 100-tok | 100 | 1270 | 75.75 | same, second half `grind [ChoiceBisim, IsBisimulation]` |
| Luna best | 155 | 440 | 75.62 | `induction hr`, both directions, `HB := Bisimilarity.isBisimulation ..`, `first` trick |
| hybrid (verified) | 83 | 256 | 86.76 | DeepSeek proof with `▸` instead of `rw` |

Dominant structural decision: HomBisimilarity.symm_simulation (`HomBisimilarity lts = fun s1 s2 => ∃ r, r s1 s2 ∧ Std.Symm r ∧ IsHomSimulation lts r`). It is in the Bisimulation file but not in the reference proof's dependency list, so it was never in the packet; only DeepSeek discovered it. It removes the whole right/`follow_snd` half (reference: 2 of 4 blocks, Luna/Qwen: a duplicated direction) at the price of a 17-token symmetry proof (`⟨fun _ _ => ChoiceBisim.rec (.choice ·.symm) (.bisim ·.symm)⟩`). Second decision: the three leaf cases use `.imp`/`And.imp` one-liners on `follow_fst` instead of `obtain ⟨_, _, _⟩ ; exists ; constructor` sequences (-60 tokens vs reference).

DeepSeek best (85/263):
```lean
  intro h
  rw [HomBisimilarity.symm_simulation]
  refine ⟨ChoiceBisim, .choice h, ⟨fun _ _ => ChoiceBisim.rec (.choice ·.symm) (.bisim ·.symm)⟩, ?_⟩
  rintro a b (hp | hb) μ a' htr
  cases htr <;> rename_i h
  exact (hp.follow_fst h).imp fun t => And.imp Tr.choiceL ChoiceBisim.bisim
  exact ⟨a', h.choiceR, .bisim (HomBisimilarity.refl _)⟩
  exact (hb.follow_fst htr).imp fun t => And.imp_right ChoiceBisim.bisim
```
Hybrid (verified cold on v4.33.0-rc2/v4.32.0/v4.31.0; 83 tok, 256 HB, 86.76; runs/analysis/Cslib_CCS_bisimilarity_congr_choice-hybrid-v6-86.76.lean): identical except `refine HomBisimilarity.symm_simulation ▸ ⟨ChoiceBisim, ..⟩` replaces `rw [...]` + `refine ⟨` (-2 tokens, -7 HB). Luna/Qwen contributed no structural idea that DeepSeek lacked here (Luna's `induction hr` and Qwen's `first | follow_fst | follow_snd` both cost more tokens than the symmetric route). Note the earlier runs/analysis hybrid-84.52 is superseded (below DeepSeek's own 86.44).

Tried and failed to beat: wildcard names + dot-constructors (`fun _ => .imp .choiceL .bisim`, `⟨_, .choiceR h, .bisim (.refl _)⟩`) 86 tok / 86.29 (token counter treats `_`/`a'`/`Tr.choiceL`/`.choiceL` all as one token, so renaming gains nothing); bullet+`‹_›` layout 90 tok / 85.75.

Per-axis headroom: tokens 83/251 = 66.9% (22.3 pt of 33.3); HB 256/3858 = 93.4% (31.1 pt; profile: `cases htr` 51, `refine` 42, `rintro` 23, leaf `exact` 18, 89 unattributed -> <= 2 pt left); compat 3/3. Only token golf is live and each token is 0.133 pt. Qwen's `grind` experiment shows the trade: -36 tokens (+4.8 pt) for +860 HB (-7.4 pt): grind is a loss on this scale (1 token ~ 15 HB).

## 3. fundamental_theorem_of_variational_calculus' (PhysLib; ref 851 tok / 11947 HB, single toolchain v4.32.0)

Rates: 1 tok = 0.039 pt (~14 HB); 100 HB = 0.279 pt. Reference is 150 lines: L2 embedding (`toL2`), `bump_exists`, nlinarith inner-product estimate, integrability, `integral_pos_iff_support_of_nonneg`, measure of balls.

| who | tok | HB | proxy | route |
|---|---|---|---|---|
| reference | 851 | 11947 | ~0 | measure-theoretic assembly |
| DeepSeek best | 160 | 1967 | 88.25 | one-shot `Continuous.integral_pos_of_hasCompactSupport_nonneg_nonzero` + `ContDiffBump` + primed inner lemmas |
| Qwen best | 194 | 1822 | 87.32 | same lemma; extra `let ψ`, `hb`, ascription; `hg _ ..` |
| Luna best | 601 | 3702 | 66.13 | kept the reference's skeleton (bump_exists, hμ_ball, integral_pos_iff_support_of_nonneg, linear_combination); never found the one-shot lemma |
| hybrid (verified) | 145 | 1575 | 89.93 | below |

Dominant structural decision (worth ~700 tokens / 10000 HB = ~28 + ~25 pt): collapse steps [3]-[4.2.4] into the single mathlib lemma `Continuous.integral_pos_of_hasCompactSupport_nonneg_nonzero` (continuous, compact support, `0 ≤ f`, `f x₀ ≠ 0` => `0 < ∫ f`), which removes integrability, support-subset, ball-measure and `integral_pos_iff_support_of_nonneg`. Second decision: skip the WithLp/`toL2` detour by using the primed lemmas `real_inner_self_nonneg'`, `inner_self_eq_zero'`, `Continuous.inner'` that work for the repo's own inner-product class on V. Third: a `ContDiffBump` built directly from `δ/2 < δ` instead of `bump_exists` with a 5-clause existential. DeepSeek and Qwen both found all three; Luna found none and ended 450 tokens longer (only lemma Luna used that others missed: `InnerProductSpace'.inner_top_equiv_norm`, which is more expensive than `real_inner_self_nonneg'`).

Hybrid (verified, 145 tok / 1575 HB / 89.93 on v4.32.0; runs/analysis/fundamental_theorem_of_variational_calculus'-hybrid-v6-89.93.lean). Body:
```lean
  refine funext fun x₀ => ?_
  by_contra hx0
  have hpos := real_inner_self_nonneg'.lt_of_ne' (inner_self_eq_zero'.not.mpr hx0)
  have hcont := Continuous.inner' (𝕜 := ℝ) _ (fun _ => f x₀) hf continuous_const
  obtain ⟨δ, hδpos, hδ⟩ := Metric.isOpen_iff.mp (isOpen_lt continuous_const hcont) x₀ hpos
  let φ1 : ContDiffBump x₀ := ⟨_, _, half_pos hδpos, half_lt_self hδpos⟩
  refine (Continuous.integral_pos_of_hasCompactSupport_nonneg_nonzero
    (φ1.continuous.mul hcont) φ1.hasCompactSupport.mul_right
    (by
      intro x
      by_cases h : dist x x₀ < δ
      · exact mul_nonneg φ1.nonneg (hδ h).le
      · simp [φ1.zero_of_le_dist (not_lt.1 h)])
    (mul_pos (φ1.pos_of_mem_ball (Metric.mem_ball_self φ1.rOut_pos)) hpos).ne').ne'
    (by simpa only [inner_smul_right', Pi.mul_apply] using
      hg _ (.smul_right ⟨φ1.contDiff, φ1.hasCompactSupport⟩ contDiff_const))
```
Ideas combined and their measured value (10 cold single-toolchain attempts, each cumulative from DeepSeek's 160/1967/88.25):
1. `refine funext fun x₀ => ?_; by_contra hx0` instead of `by_contra h₀; obtain ⟨x₀, hx0⟩ := Function.ne_iff.mp h₀`: 157/1940 (88.44). (-3 tok; `0 x₀` is defeq to `0` so `inner_self_eq_zero'` still applies)
2. `⟨_, _, half_pos hδpos, half_lt_self hδpos⟩`: radii inferred from the proof terms: 155/1912 (88.60).
3. `φ1.continuous.mul hcont` for `Continuous.mul φ1.continuous hcont`: 154/1904 (88.65). (Switching `x ∈ Metric.ball x₀ δ` to `dist x x₀ < δ` is token-neutral, HB-neutral.)
4. Qwen's `hg _ (...)` instead of the explicit `hg (fun x => φ1 x • f x₀) (IsTestFunction.smul_right ..)`, plus `.smul_right` dot-resolution: 145/1592 (89.88). This is the Qwen-heartbeat idea: the explicit lambda is elaborated twice (once as the argument, once against `Pi.mul_apply`) and costs ~300 HB; leaving `_` lets unification find it from the lemma's expected type. (Without the surrounding `simpa only [.., Pi.mul_apply]` it fails, tried: `simpa only [inner_smul_right']` -> type mismatch.)
5. `(mul_pos A hpos).ne'` instead of `mul_ne_zero A.ne' hpos.ne'`: 145/1575 (89.93).
Rejected: dropping `only` in the final simpa: 151 tok/1993 HB (88.53; -3 tokens = +0.12 pt but +89 HB = -0.25 pt); `if h : .. then .. else ..` term instead of by_cases: 154/1898 (no gain).

Per-axis headroom (profile events): DeepSeek's 160-token version has 640+ of 1967 HB unattributed (statement/instance elaboration; irreducible), and the self-cost leaders were `let φ1 : ContDiffBump ..` (~135-300 depending on how the radii are proven; `by positivity, by linarith` cost 2x the `half_pos` terms), the explicit `hg (fun x => φ1 x • ..)` (~310-440) and the final `exact ne_of_lt (..integral_pos..)` (300). Token axis is 145/851 = 83% reduced (27.7 of 33.3 pt), HB axis 1575/11947 = 86.8% reduced (28.9 pt). Remaining headroom ~ 4.5 pt token side (floor ~ 100 tokens given the 6 required arguments of the integral lemma) and ~ 4 pt HB side, all in the same 3 or 4 elaboration-heavy lines.

## 4. Cross-model patterns

* Luna (gpt-6-luna) tends to stay close to the reference's proof shape and adds structure (explicit `have` with full statements, `bump_exists`-style existentials, `by first | exact .. | exact ..` search wrappers, `induction hr`). On Inits it did find the bulk-lemma route (86 tok, 85.11: it was within 3 tokens of DeepSeek), but on Cslib (155 tok vs 85) and Phys (601 vs 160) it executed the reference's decomposition and never searched for a global shortcut (`HomBisimilarity.symm_simulation`, `Continuous.integral_pos_of_hasCompactSupport_nonneg_nonzero`). Its ideas that would have scored if executed: its own idea "commute-bulk-updates" (Inits) was executed well; on Cslib its idea of `HB := Bisimilarity.isBisimulation` + per-direction cases is dominated by the symmetric-simulation route; Phys: `by_contra!`/`linear_combination` micro-ideas are cheaper than DeepSeek's equivalents only inside the reference's skeleton, so were irrelevant once the one-shot lemma is used.
* DeepSeek (v4.1-flash) wins by global lemma search first (symm_simulation, integral_pos_of_..._nonzero, updatedStatesComm family), then golf: `cases h` on equations to substitute states, `▸` casts, dot-notation `.imp`/`And.imp` one-liners, anonymous-constructor term proofs. Its remaining slack is local: `Function.ne_iff` + obtain (3 tok), explicit radii (4 tok), `hg (fun ..)` (+300 HB), `rw` vs `▸` (2 tok).
* Qwen (3.8-flash) finds the same global lemmas on Inits and Phys, but pays for automation instead of terms: `simp_all`, `simp [..]; rw [..]`, `first | exact .. | exact ..`, and on Cslib `grind` (-36 tokens, +860 HB, net loss). It does hit the cheapest-HB choices DeepSeek missed (Phys `hg _ ..` -> 1822 HB vs 1967; Inits 79-token variant). Qwen golf: 79 tokens on Inits by `simp_all [List.unzip_zip]` but at 286 HB (net -0.1 pt vs the 83-token DeepSeek).
* Cross-model hybrids do help, but only on the micro level: Inits +1.03 over best (86.07 -> 87.10; Qwen's "let simp use context length facts" + DeepSeek skeleton), Cslib +0.32 (86.44 -> 86.76; one ▸ trick, nothing from Luna/Qwen), Phys +1.68 (88.25 -> 89.93; Qwen's `hg _`, own golf). The structural decision was found by one model in each theorem and the others' versions are dominated. Proxy gaps between models are ~0.1-2 pt wherever the same structure was found, but 10-22 pt wherever a model missed the shortcut (Luna Phys -22, Luna/Qwen Cslib -8 to -11).

## 5. Learnings for packet / harness

1. Global shortcut lemmas are the whole game and are not in the reference's dependency list, so the packet's "Elaborated proof dependencies" never shows them. Add a "library lemmas whose statement matches subterms of the goal" section: e.g. for Inits `updatedStatesComm/Init/Update` (bulk versions of the step lemmas the reference uses); for Cslib `HomBisimilarity.symm_simulation`, `IsBisimulation.inv`, `Std.Symm`; for Phys the `Continuous.integral_pos_of_hasCompactSupport_nonneg_nonzero` family and `ContDiffBump` API. Rank candidates by "the reference proves by hand what this lemma states" (the reference's `have` statements/`induction` shape can be pattern-matched against lemma conclusions). Luna was the model most dependent on the packet shape and the one that missed these.
2. Heartbeat lever that no model tried systematically: unify via `_` and expected types instead of restating lambdas/types (Phys: -310 HB, +1.6 pt, via `hg _ ..`). Worth a profile hint when a `fun x => ..` argument is the top self-cost line; the profile output already shows it (310-440 HB lines), but the harness hint does not say "replace by `_`".
3. Token-counter facts the packet should state: every identifier is one token regardless of length (`Tr.choiceL` = `.choiceL` = `_`), each punctuation char and each blank line is one; so renaming/dot-notation is free to neutral, while `by`/`fun`/`(`/`)`/`·`/`,`/`:=` are what to remove. Measured wins in this session were all structural (`▸` instead of `rw [..]`+`refine`: -2; `funext`+`by_contra` instead of `by_contra`+`obtain`: -3; inferred radii `_ _`: -2; `.mul` dot-composition: -1).
4. Trade-off table per theorem (already in the packet) should be used for `grind`/`simp_all`: break-even is ~14-19 HB per token on all three theorems; every `grind`/`simp_all` call measured here costs 70-900 HB to save 3-36 tokens, so it only pays on Inits-sized (4251 ref HB, 19 HB/token) cases when saving >= 4 tokens per 70 HB.
5. Compat: all three Core/Cslib hybrids pass all 3 toolchains; Phys has a single version. Heartbeats vary by ~14 between equivalent token-equal variants (`.intro _ ⟨` vs `⟨_,`), so for last-mile tuning a cold repeat is needed rather than session heartbeats.
6. Cslib/Core packets should also mention that Lean version used by the harness for a probe differs from the one in the header for Cslib (probe ran v4.33.0-rc2 first); the verified set is v4.33.0-rc2/v4.32.0/v4.31.0.

## Verified hybrids (cold, full mode, all listed toolchains)
* Core.InitsUpdatesComm: 76 tok / 203 HB / 87.10 (v6 best 86.07): runs/analysis/Core_InitsUpdatesComm-hybrid-v6-87.10.lean
* Cslib.CCS.bisimilarity_congr_choice: 83 tok / 256 HB / 86.76 (v6 best 86.44): runs/analysis/Cslib_CCS_bisimilarity_congr_choice-hybrid-v6-86.76.lean
* fundamental_theorem_of_variational_calculus': 145 tok / 1575 HB / 89.93 (v6 best 88.25): runs/analysis/fundamental_theorem_of_variational_calculus'-hybrid-v6-89.93.lean
