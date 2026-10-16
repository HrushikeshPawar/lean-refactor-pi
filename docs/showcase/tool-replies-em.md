# Tool replies exactly as the model sees them

Theorem: EM (`time_deriv_time_deriv_electricField_of_isExtrema`). A scripted session ran through Pi, the arena extension and real Lean (run `test-showcase-em2`). Each reply is copied from the provider request, so it is byte-for-byte what DeepSeek receives.

Order: read source → search (exact + missing name) → search after → read a library declaration → scratch lookups → scratch passing → scratch failing → compile passing (n2) → compile failing (n3) → read outline → read outline one step → read prices → read tree → read map.

## 1. `read`

**Call**

```json
{
  "node": "n1",
  "view": "source"
}
```

**Reply** (7569 bytes)

````markdown
## Result
n1 source (line numbers as in errors and the outline)
1: lemma time_deriv_time_deriv_electricField_of_isExtrema {A : ElectromagneticPotential d}
2:     {𝓕 : FreeSpace}
3:     (hA : ContDiff ℝ ∞ A) (J : LorentzCurrentDensity d)
4:     (hJ : ContDiff ℝ ∞ J) (h : IsExtrema 𝓕 A J)
5:     (t : Time) (x : Space d) (i : Fin d) :
6:     ∂ₜ (∂ₜ (A.electricField 𝓕.c · x i)) t =
7:       𝓕.c ^ 2 * ∑ j, (∂[j] (∂[j] (A.electricField 𝓕.c t · i)) x) -
8:       𝓕.c ^ 2 / 𝓕.ε₀ * ∂[i] (J.chargeDensity 𝓕.c t ·) x -
9:       𝓕.c ^ 2 * 𝓕.μ₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
10:   have hEs : ∀ j, ContDiff ℝ 2 (fun y => A.electricField 𝓕.c t y j) :=
11:     fun j => electricField_apply_contDiff_space (i := j) (hA.of_le (right_eq_inf.mp rfl)) t
12:   have hEd : ∀ j k, Differentiable ℝ (∂[k] (fun y => A.electricField 𝓕.c t y j)) :=
13:     fun j k => Space.deriv_differentiable (hEs j) k
14:   have hBt : ∀ j, Differentiable ℝ
15:       (fun s => ∂[j] (fun y => A.magneticFieldMatrix 𝓕.c s y (j, i)) x) :=
16:     fun j => Space.space_deriv_differentiable_time (i := j)
17:       (magneticFieldMatrix_contDiff _ (hA.of_le (right_eq_inf.mp rfl)) (j, i)) x
18:   have hJt : Differentiable ℝ (fun s => J.currentDensity 𝓕.c s x i) :=
19:     LorentzCurrentDensity.currentDensity_apply_differentiable_time (hJ.differentiable (by simp)) x i
20:   calc _
21:     _= ∂ₜ (fun t =>
22:       1 / (𝓕.μ₀ * 𝓕.ε₀) * ∑ j, Space.deriv j (fun x => magneticFieldMatrix 𝓕.c A t x (j, i)) x -
23:       1 / 𝓕.ε₀ * LorentzCurrentDensity.currentDensity 𝓕.c J t x i) t := by
24:         conv_lhs =>
25:           enter [1]
26:           change fun t => ∂ₜ (A.electricField 𝓕.c · x i) t
27:           enter [t]
28:           rw [Time.deriv_euclid (electricField_differentiable_time
29:             (hA.of_le (right_eq_inf.mp rfl)) _),
30:             time_deriv_electricField_of_isExtrema hA J hJ h]
31:     _ = 1 / (𝓕.μ₀ * 𝓕.ε₀) * ∂ₜ (fun t => ∑ j, ∂[j] (A.magneticFieldMatrix 𝓕.c t · (j, i)) x) t -
32:       1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
33:       rw [Time.deriv_eq]
34:       rw [fderiv_fun_sub]
35:       simp only [one_div, mul_inv_rev, FunLike.coe_sub, Pi.sub_apply]
36:       rw [fderiv_const_mul (Differentiable.fun_sum fun j _ => hBt j).differentiableAt]
37:       rw [fderiv_const_mul hJt.differentiableAt]
38:       simp [Time.deriv_eq]
39:       · exact ((Differentiable.fun_sum fun j _ => hBt j).const_mul _).differentiableAt
40:       · exact hJt.differentiableAt.const_mul _
41:     _ = 1 / (𝓕.μ₀ * 𝓕.ε₀) * ((∑ j, ∂ₜ (fun t => ∂[j] (A.magneticFieldMatrix 𝓕.c t · (j, i)) x)) t) -
42:       1 / 𝓕.ε₀ * (∂ₜ (J.currentDensity 𝓕.c · x i) t) := by
43:       congr
44:       rw [Time.deriv_eq]
45:       rw [fderiv_fun_sum fun i _ => (hBt i).differentiableAt]
46:       simp only [FunLike.coe_sum, Finset.sum_apply]
47:       rfl
48:     _ = 1 / (𝓕.μ₀ * 𝓕.ε₀) * (∑ j, ∂[j] (fun x => ∂ₜ (A.magneticFieldMatrix 𝓕.c · x (j, i)) t)) x -
49:         1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
50:       congr
51:       simp only [Finset.sum_apply]
52:       congr
53:       funext k
54:       rw [Space.time_deriv_comm_space_deriv]
55:       apply magneticFieldMatrix_contDiff
56:       apply hA.of_le (right_eq_inf.mp rfl)
57:     _ = 1 / (𝓕.μ₀ * 𝓕.ε₀) *(∑ j, ∂[j] (fun x => ∂[j] (A.electricField 𝓕.c t · i) x -
58:         ∂[i] (A.electricField 𝓕.c t · j) x)) x -
59:         1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
60:         congr
61:         simp only [Finset.sum_apply]
62:         congr
63:         funext k
64:         congr
65:         funext x
66:         rw [time_deriv_magneticFieldMatrix _ (hA.of_le (ENat.LEInfty.out))]
67:     _ = (1 / (𝓕.μ₀ * 𝓕.ε₀) * ∑ j, (∂[j] (fun x => ∂[j] (A.electricField 𝓕.c t · i) x) x -
68:           ∂[j] (fun x => ∂[i] (A.electricField 𝓕.c t · j) x) x)) -
69:           1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
70:         congr
71:         simp only [Finset.sum_apply]
72:         congr
73:         funext j
74:         rw [Space.deriv_eq_fderiv_basis]
75:         rw [fderiv_fun_sub (hEd _ _).differentiableAt (hEd _ _).differentiableAt]
76:         simp [← Space.deriv_eq_fderiv_basis]
77:     _ = 1 / (𝓕.μ₀ * 𝓕.ε₀) * ∑ j, (∂[j] (fun x => ∂[j] (A.electricField 𝓕.c t · i) x) x) -
78:           1 / (𝓕.μ₀ * 𝓕.ε₀) * ∑ j, (∂[j] (fun x => ∂[i] (A.electricField 𝓕.c t · j) x) x) -
79:           1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by simp [mul_sub]
80:     _ = 1 / (𝓕.μ₀ * 𝓕.ε₀) * ∑ j, (∂[j] (fun x => ∂[j] (A.electricField 𝓕.c t · i) x) x) -
81:         1 / (𝓕.μ₀ * 𝓕.ε₀) * ∑ j, (∂[i] (fun x => ∂[j] (A.electricField 𝓕.c t · j) x) x) -
82:         1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
83:         congr
84:         funext j
85:         rw [Space.deriv_commute _ (hEs _), Space.deriv_eq_fderiv_basis]
86:       _ = 1 / (𝓕.μ₀ * 𝓕.ε₀) * ∑ j, (∂[j] (fun x => ∂[j] (A.electricField 𝓕.c t · i) x) x) -
87:           1 / (𝓕.μ₀ * 𝓕.ε₀) * (∂[i] (fun x => ∑ j, ∂[j] (A.electricField 𝓕.c t · j) x) x) -
88:           1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
89:         congr
90:         rw [Space.deriv_eq_fderiv_basis]
91:         rw [fderiv_fun_sum]
92:         simp [← Space.deriv_eq_fderiv_basis]
93:         intro j _
94:         exact (hEd j j).differentiableAt
95:       _ = 1 / (𝓕.μ₀ * 𝓕.ε₀) * ∑ j, (∂[j] (fun x => ∂[j] (A.electricField 𝓕.c t · i) x) x) -
96:           1 / (𝓕.μ₀ * 𝓕.ε₀) * (∂[i] (fun x => (∇ ⬝ (A.electricField 𝓕.c t)) x) x) -
97:           1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
98:         rfl
99:       _ = 1 / (𝓕.μ₀ * 𝓕.ε₀) * ∑ j, (∂[j] (∂[j] (A.electricField 𝓕.c t · i)) x) -
100:           1 / (𝓕.μ₀ * 𝓕.ε₀ ^ 2) * ∂[i] (J.chargeDensity 𝓕.c t ·) x -
101:           1 / 𝓕.ε₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
102:         congr 2
103:         rw [isExtrema_iff_gauss_ampere_magneticFieldMatrix] at h
104: 
105:         conv_lhs =>
106:           enter [2, 2, x]
107:           rw [(h t x).1]
108:         trans 1 / (𝓕.μ₀ * 𝓕.ε₀) * Space.deriv i
109:             (fun x => (1/ 𝓕.ε₀) * LorentzCurrentDensity.chargeDensity 𝓕.c J t x) x
110:         · congr
111:           funext x
112:           ring
113:         · rw [Space.deriv_eq_fderiv_basis]
114:           rw [fderiv_const_mul]
115:           simp [← Space.deriv_eq_fderiv_basis]
116:           field_simp
117:           apply Differentiable.differentiableAt
118:           apply LorentzCurrentDensity.chargeDensity_differentiable_space
119:           exact hJ.differentiable (by simp)
120:         · exact hA
121:         · exact hJ
122:       _ = 𝓕.c ^ 2 * ∑ j, (∂[j] (∂[j] (A.electricField 𝓕.c t · i)) x) -
123:             𝓕.c ^ 2 / 𝓕.ε₀ * ∂[i] (J.chargeDensity 𝓕.c t ·) x -
124:             𝓕.c ^ 2 * 𝓕.μ₀ * ∂ₜ (J.currentDensity 𝓕.c · x i) t := by
125:           simp [FreeSpace.c_sq]
126:           field_simp

budget: $0.00 of $0.10 spent · 100% left
````

## 2. `search`

**Call**

```json
{
  "queries": [
    "Time.deriv_eq",
    "Time.deriv_sub"
  ]
}
```

**Reply** (4218 bytes)

````markdown
## Result
2 queries, 1 exact
### Time.deriv_eq
| name | signature | module:line | match |
|---|---|---|---|
| Time.deriv_eq | ∀ {M : Type} [inst : AddCommGroup M] [inst_1 : Module ℝ M] [inst_2 : TopologicalSpace M] (f : Time → M) (t : Time), ∂ₜ f t = (fderiv ℝ f t) 1 | Physlib.SpaceAndTime.Time.Derivatives:66 | exact |
| Time.deriv_eq_mfderiv | ∀ {M : Type} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] (f : Time → M) (t : Time), ∂ₜ f t = (mfderiv% f t) 1 | Physlib.SpaceAndTime.Time.Derivatives:91 | prefix |
| Time.deriv_eq_manifoldDeriv | ∀ {M : Type} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] (f : Time → M) (t : Time), ∂ₜ f t = Time.manifoldDeriv (modelWithCornersSelf ℝ M) f t | Physlib.SpaceAndTime.Time.Derivatives:101 | prefix |
| SpaceTime.deriv_eq | ∀ {M : Type} [inst : AddCommGroup M] [inst_1 : Module ℝ M] [inst_2 : TopologicalSpace M] {d : ℕ} (μ : Fin 1 ⊕ Fin d) (f : SpaceTime d → M) (y : SpaceTime d), ∂_ μ f y = (fderiv ℝ f y) (Lorentz.Vector… | Physlib.SpaceAndTime.SpaceTime.Derivatives:88 | substring |
| SpaceTime.deriv_eq_mfderiv | ∀ {M : Type} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] {d : ℕ} (μ : Fin 1 ⊕ Fin d) (f : SpaceTime d → M) (y : SpaceTime d), ∂_ μ f y = (mfderiv% f y) (Lorentz.Vector.basis μ) | Physlib.SpaceAndTime.SpaceTime.Derivatives:111 | substring |
| SpaceTime.deriv_equivariant | ∀ {n d : ℕ} {c : Fin n → Color} {M : Type} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] [inst_2 : (realLorentzTensor d).Tensorial c M] [T2Space M] (f : SpaceTime d → M) (Λ : ↑(LorentzGrou… | Physlib.SpaceAndTime.SpaceTime.Derivatives:257 | substring |
| SpaceTime.deriv_eq_manifoldDeriv | ∀ {M : Type} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] {d : ℕ} (μ : Fin 1 ⊕ Fin d) (f : SpaceTime d → M) (y : SpaceTime d), ∂_ μ f y = SpaceTime.manifoldDeriv (modelWithCornersSelf ℝ M… | Physlib.SpaceAndTime.SpaceTime.Derivatives:120 | substring |
| deriv_eq | ∀ {𝕜 : Type u} [inst : NontriviallyNormedField 𝕜] {F : Type v} [inst_1 : NormedAddCommGroup F] [inst_2 : NormedSpace 𝕜 F] {f f' : 𝕜 → F}, (∀ (x : 𝕜), HasDerivAt f (f' x) x) → _root_.deriv f = f' | Mathlib.Analysis.Calculus.Deriv.Basic:441 | fuzzy |
### Time.deriv_sub
No declaration named Time.deriv_sub. Names under Time.deriv_: Time.deriv_eq, Time.deriv_add, Time.deriv_div, Time.deriv_neg, Time.deriv_smul, Time.deriv_const, Time.deriv_space, Time.deriv_euclid, Time.deriv_fun_sum, Time.deriv_mul_const, Time.deriv_eq_mfderiv, Time.deriv_lorentzVector
| name | signature | module:line | match |
|---|---|---|---|
| deriv_sub | ∀ {𝕜 : Type u} [inst : NontriviallyNormedField 𝕜] {F : Type v} [inst_1 : NormedAddCommGroup F] [inst_2 : NormedSpace 𝕜 F] {f g : 𝕜 → F} {x : 𝕜}, DifferentiableAt 𝕜 f x → DifferentiableAt 𝕜 g x → _roo… | Mathlib.Analysis.Calculus.Deriv.Add:380 | fuzzy |
| Space.deriv_sub | ∀ {M : Type u_1} {d : ℕ} {u : Fin d} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] (f1 f2 : Space d → M), Differentiable ℝ f1 → Differentiable ℝ f2 → Space.deriv u (f1 - f2) = Space.deriv … | Physlib.SpaceAndTime.Space.Derivatives.Basic:175 | fuzzy |
| deriv_sum | ∀ {𝕜 : Type u} [inst : NontriviallyNormedField 𝕜] {F : Type v} [inst_1 : NormedAddCommGroup F] [inst_2 : NormedSpace 𝕜 F] {x : 𝕜} {ι : Type u_1} {u : Finset ι} {A : ι → 𝕜 → F}, (∀ i ∈ u, Differentiab… | Mathlib.Analysis.Calculus.Deriv.Add:243 | fuzzy |
| fderiv_sub | ∀ {𝕜 : Type u_1} [inst : NontriviallyNormedField 𝕜] {E : Type u_2} [inst_1 : NormedAddCommGroup E] [inst_2 : NormedSpace 𝕜 E] {F : Type u_3} [inst_3 : NormedAddCommGroup F] [inst_4 : NormedSpace 𝕜 F]… | Mathlib.Analysis.Calculus.FDeriv.Add:726 | fuzzy |
| deriv_mul | ∀ {𝕜 : Type u} [inst : NontriviallyNormedField 𝕜] {x : 𝕜} {𝔸 : Type u_3} [inst_1 : NormedRing 𝔸] [inst_2 : NormedAlgebra 𝕜 𝔸] {c d : 𝕜 → 𝔸}, DifferentiableAt 𝕜 c x → DifferentiableAt 𝕜 d x → _root_.d… | Mathlib.Analysis.Calculus.Deriv.Mul:295 | fuzzy |

budget: $0.00 of $0.10 spent · 100% left
````

## 3. `search`

**Call**

```json
{
  "after": "Time.deriv"
}
```

**Reply** (2595 bytes)

````markdown
## Result
1 queries, 0 exact
### Time.deriv
| name | signature | module:line | match |
|---|---|---|---|
| Time.deriv_eq | ∀ {M : Type} [inst : AddCommGroup M] [inst_1 : Module ℝ M] [inst_2 : TopologicalSpace M] (f : Time → M) (t : Time), ∂ₜ f t = (fderiv ℝ f t) 1 | Physlib.SpaceAndTime.Time.Derivatives:66 | completion |
| Time.deriv_add | ∀ {M : Type} {t : Time} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] (f g : Time → M), DifferentiableAt ℝ f t → DifferentiableAt ℝ g t → ∂ₜ (fun s => f s + g s) t = ∂ₜ f t + ∂ₜ g t | Physlib.SpaceAndTime.Time.Derivatives:132 | completion |
| Time.deriv_div | ∀ {t : Time} {c g : Time → ℝ}, DifferentiableAt ℝ c t → DifferentiableAt ℝ g t → g t ≠ 0 → ∂ₜ (fun s => c s / g s) t = (∂ₜ c t * g t - c t * ∂ₜ g t) / g t ^ 2 | Physlib.SpaceAndTime.Time.Derivatives:149 | completion |
| Time.deriv_neg | ∀ {M : Type} {t : Time} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] (f : Time → M), ∂ₜ (-f) t = -∂ₜ f t | Physlib.SpaceAndTime.Time.Derivatives:127 | completion |
| Time.deriv_smul | ∀ {d : ℕ} {t : Time} (f : Time → EuclideanSpace ℝ (Fin d)) (k : ℝ), Differentiable ℝ f → ∂ₜ (fun t => k • f t) t = k • ∂ₜ (fun t => f t) t | Physlib.SpaceAndTime.Time.Derivatives:120 | completion |
| Time.deriv_const | ∀ {M : Type} {t : Time} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] (m : M), ∂ₜ (fun x => m) t = 0 | Physlib.SpaceAndTime.Time.Derivatives:169 | completion |
| Time.deriv_space | ∀ {d : ℕ} {f : Time → Space d}, Differentiable ℝ f → ∀ (t : Time) (i : Fin d), ∂ₜ (fun s => (f s).val i) t = (∂ₜ f t).val i | Physlib.SpaceAndTime.Time.Derivatives:259 | completion |
| Time.deriv_euclid | ∀ {n : ℕ} {μ : Fin n} {f : Time → EuclideanSpace ℝ (Fin n)}, Differentiable ℝ f → ∀ (t : Time), ∂ₜ (fun t => (f t).ofLp μ) t = (∂ₜ (fun t => f t) t).ofLp μ | Physlib.SpaceAndTime.Time.Derivatives:226 | completion |
| Time.deriv_fun_sum | ∀ {M : Type} {t : Time} {ι : Type u_1} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] (s : Finset ι) (a : ι → Time → M), (∀ i ∈ s, DifferentiableAt ℝ (a i) t) → ∂ₜ (fun x => ∑ i ∈ s, a i x)… | Physlib.SpaceAndTime.Time.Derivatives:138 | completion |
| Time.deriv_mul_const | ∀ {t : Time} (f : Time → ℝ) (c : ℝ), DifferentiableAt ℝ f t → ∂ₜ (fun s => f s * c) t = ∂ₜ f t * c | Physlib.SpaceAndTime.Time.Derivatives:144 | completion |

budget: $0.00 of $0.10 spent · 100% left
````

## 4. `read`

**Call**

```json
{
  "handle": "decl:Space.deriv_sub"
}
```

**Reply** (496 bytes)

````markdown
## Result
Physlib/SpaceAndTime/Space/Derivatives/Basic.lean:175-181 (declaration Space.deriv_sub)
175: /-- Derivatives on space distribute over subtraction. -/
176: @[to_fun]
177: lemma deriv_sub [NormedAddCommGroup M] [NormedSpace ℝ M]
178:     (f1 f2 : Space d → M) (hf1 : Differentiable ℝ f1) (hf2 : Differentiable ℝ f2) :
179:     ∂[u] (f1 - f2) = ∂[u] f1 - ∂[u] f2 := by
180:   ext x
181:   simp [deriv_eq, fderiv_sub (hf1 x) (hf2 x)]

budget: $0.00 of $0.10 spent · 100% left
````

## 5. `scratch`

**Call**

```json
{
  "code": "#check @Space.deriv_sub\n#check Time.deriv_sub\n#print FreeSpace.c_sq\n"
}
```

**Reply** (939 bytes)

````markdown
## Result
FAILED: errors 1, warnings 0
line 2 error: Unknown constant `Time.deriv_sub`
| line | command | output |
|---|---|---|
| 1 | `#check @Space.deriv_sub` | @Space.deriv_sub : ∀ {M : Type u_1} {d : ℕ} {u : Fin d} [inst : NormedAddCommGroup M] [inst_1 : NormedSpace ℝ M] (f1 f2 : Space d → M), Differentiable ℝ f1 → Differentiable ℝ f2 → Space.deriv u (f1 - f2) = Space.deriv u f1 - Space.deriv u f2 |
| 2 | `#check Time.deriv_sub` |  |
| 3 | `#print FreeSpace.c_sq` | theorem Electromagnetism.FreeSpace.c_sq : ∀ (𝓕 : FreeSpace), 𝓕.c.val ^ 2 = 1 / (𝓕.ε₀ * 𝓕.μ₀) := <not imported> |
unknown Time.deriv_sub; names under Time.deriv_: Time.deriv_eq, Time.deriv_add, Time.deriv_div, Time.deriv_neg, Time.deriv_smul, Time.deriv_const, Time.deriv_space, Time.deriv_euclid, Time.deriv_fun_sum, Time.deriv_mul_const, Time.deriv_eq_mfderiv, Time.deriv_lorentzVector

budget: $0.00 of $0.10 spent · 100% left
````

## 6. `scratch`

**Call**

```json
{
  "code": "example {d : ℕ} {A : ElectromagneticPotential d} {𝓕 : FreeSpace}\n    (hA : ContDiff ℝ ∞ A) (J : LorentzCurrentDensity d)\n    (hJ : ContDiff ℝ ∞ J) (h : IsExtrema 𝓕 A J)\n    (t : Time) (x : Space d) (i : Fin d) :\n    1 / (𝓕.μ₀ * 𝓕.ε₀) * (X - 1 / 𝓕.ε₀ * D) - 1 / 𝓕.ε₀ * DJ =\n      𝓕.c ^ 2 * X - 𝓕.c ^ 2 / 𝓕.ε₀ * D - 𝓕.c ^ 2 * 𝓕.μ₀ * DJ := by\n  simp only [FreeSpace.c_sq]\n  field_simp\n"
}
```

**Reply** (152 bytes)

````markdown
## Result
OK: errors 0, warnings 0, body tokens 7 (after :=)
line 1: 7 body tokens, 2678 HB, 3.5 pts at stake

budget: $0.00 of $0.10 spent · 100% left
````

## 7. `scratch`

**Call**

```json
{
  "code": "example {d : ℕ} {A : ElectromagneticPotential d} {𝓕 : FreeSpace}\n    (hA : ContDiff ℝ ∞ A) (J : LorentzCurrentDensity d)\n    (hJ : ContDiff ℝ ∞ J) (h : IsExtrema 𝓕 A J)\n    (t : Time) (x : Space d) (i : Fin d) :\n    1 / (𝓕.μ₀ * 𝓕.ε₀) * (X - 1 / 𝓕.ε₀ * D) - 1 / 𝓕.ε₀ * DJ =\n      𝓕.c ^ 2 * X - 𝓕.c ^ 2 / 𝓕.ε₀ * D - 𝓕.c ^ 2 * 𝓕.μ₀ * DJ := by\n  simp only [FreeSpace.c_sq]\n"
}
```

**Reply** (608 bytes)

````markdown
## Result
FAILED: errors 1, warnings 0, body tokens 6 (after :=)
line 6 error: unsolved goals
X D DJ : ℝ
d : ℕ
A : ElectromagneticPotential d
𝓕 : FreeSpace
hA : ContDiff ℝ ∞ A.val
J : LorentzCurrentDensity d
hJ : ContDiff ℝ ∞ J
h : IsExtrema 𝓕 A J
t : Time
x : Space d
i : Fin d
⊢ 1 / (𝓕.μ₀ * 𝓕.ε₀) * (X - 1 / 𝓕.ε₀ * D) - 1 / 𝓕.ε₀ * DJ =
    1 / (𝓕.ε₀ * 𝓕.μ₀) * X - 1 / (𝓕.ε₀ * 𝓕.μ₀) / 𝓕.ε₀ * D - 1 / (𝓕.ε₀ * 𝓕.μ₀) * 𝓕.μ₀ * DJ
line 1: 6 body tokens, 887 HB, 1.2 pts at stake

budget: $0.00 of $0.10 spent · 99% left
````

## 8. `compile`

**Call**

```json
{
  "drafts": [
    "lemma time_deriv_time_deriv_electricField_of_isExtrema {A : ElectromagneticPotential d}\n    {𝓕 : FreeSpace}\n    (hA : ContDiff ℝ ∞ A) (J : LorentzCurrentDensity d)\n    (hJ : ContDiff ℝ ∞ J) (h : IsExtrema 𝓕 A J)\n    (t : Time) (x : Space d) (i : Fin d) :\n    ∂ₜ (∂ₜ (A.electricField 𝓕.c · x i)) t =\n \n… (3463 chars; cut here only)"
  ]
}
```

**Reply** (2984 bytes)

````markdown
## Result
n2 compiles on all 1 versions; score 78.33.
n2 compiles · a new root
n2 new root · tokens 573 · heartbeats 6273 · versions 1/1 · score 78.33
## Search map
### Best and original
best n2 score 78.33 tokens 573 heartbeats 6273
n1 original proof tokens 1372 heartbeats 26970
### Proof shapes (nodes grouped by structure, depth and status; each row is the group's best node; open-hole nodes have no score)
| node | status | tokens | heartbeats | score | nodes in group |
|---|---|---|---|---|---|
| n2 | compiles | 573 | 6273 | 78.33 | 1 |
### Latest nodes
| node | made from | status | tokens | heartbeats | score |
|---|---|---|---|---|---|
| n2 | new root | compiles | 573 | 6273 | 78.33 |
### Steps of best n2, ranked by points at stake
pts: points if the step cost nothing · tries: nodes that changed it · shortest: token change of its shortest closed replacement, and that node (+ is longer) · last gain: nodes since a change to it raised the score
| step | tokens | heartbeats | pts | tries | shortest | last gain |
|---|---|---|---|---|---|---|
| s7 | 189 | 2214 | 7.33 | 0 | - | - |
| s9 | 157 | 1535 | 5.71 | 0 | - | - |
| s4 | 54 | 246 | 1.62 | 0 | - | - |
| s6 | 52 | 179 | 1.48 | 0 | - | - |
7 more steps at 1.33 pts or less.
### Lines of best n2 whose own tactic costs the most heartbeats
| line | text | heartbeats | tokens |
|---|---|---|---|
| 51 | `rw [← Finset.sum_apply, ← FunLike.coe_sum,` | 1168 | 8 |
| 29 | `rw [Time.deriv_eq,` | 754 | 4 |
| 34 | `simp only [_root_.sub_apply, _root_.smul_apply, smul_eq_mul]` | 509 | 9 |
| 42 | `rw [Space.fun_deriv_sub (Space.deriv j (A.electricField 𝓕.c t · i))` | 257 | 14 |
| 35 | `rw [← Time.deriv_eq, ← Time.deriv_eq]` | 231 | 8 |
### Lines of best n2 that run no tactic (stated terms, continued arguments), by tokens
heartbeats: spent elaborating a stated term where it stands (a chained relation's right side, a declared type); - when the line is part of a larger term.
| line | text | tokens | heartbeats |
|---|---|---|---|
| 53 | `show (fun y => ∑ j, Space.deriv j (A.electricField 𝓕.c t · j) y) = ∇ ⬝ (A.electricField 𝓕…` | 30 | 60 |
| 54 | `show (∇ ⬝ (A.electricField 𝓕.c t)) = fun y => 𝓕.ε₀⁻¹ * J.chargeDensity 𝓕.c t y from` | 22 | 31 |
| 40 | `(magneticFieldMatrix_contDiff _ (hA.of_le (right_eq_inf.mp rfl)) (j, i)) t x,` | 19 | - |
| 41 | `funext fun y => time_deriv_magneticFieldMatrix A (hA.of_le (right_eq_inf.mp rfl)) t y j i]` | 18 | - |
| 52 | `← fderiv_fun_sum (fun j _ => (Space.deriv_differentiable (hE j) j).differentiableAt),` | 18 | - |
Repeated text (shared once, saves):
5× 7 tok, saves 17 tok (0.41 pts): (hA.of_le (right_eq_inf.mp rfl))
4× 7 tok, saves 10 tok (0.24 pts): (A.electricField 𝓕.c t · j)
A tactic's heartbeats depend on the goal it runs on and how much it searches. A stated term costs its tokens wherever it appears; it leaves the proof only when nothing needs it stated.

budget: $0.00 of $0.10 spent · 99% left
````

## 9. `compile`

**Call**

```json
{
  "drafts": [
    "lemma time_deriv_time_deriv_electricField_of_isExtrema {A : ElectromagneticPotential d}\n    {𝓕 : FreeSpace}\n    (hA : ContDiff ℝ ∞ A) (J : LorentzCurrentDensity d)\n    (hJ : ContDiff ℝ ∞ J) (h : IsExtrema 𝓕 A J)\n    (t : Time) (x : Space d) (i : Fin d) :\n    ∂ₜ (∂ₜ (A.electricField 𝓕.c · x i)) t =\n \n… (3457 chars; cut here only)"
  ]
}
```

**Reply** (4664 bytes)

````markdown
## Result
n3 does not compile · made from focus n2
Lean messages:
n3.e1 line 9: unsolved goals
Goal: (9 unchanged hypotheses omitted)
d : ℕ
hG :
  ∀ (t : Time) (x : Space d),
    Space.div (electricField 𝓕.c A t) x = LorentzCurrentDensity.chargeDensity 𝓕.c J t x / 𝓕.ε₀ ∧
      ∀ (i : Fin d),
        𝓕.μ₀ * 𝓕.ε₀ * (∂ₜ (fun t => electricField 𝓕.c A t x) t).ofLp i =
          ∑ j, Space.deriv j (fun x => magneticFieldMatrix 𝓕.c A t x (j, i)) x -
            𝓕.μ₀ * (LorentzCurrentDensity.currentDensity 𝓕.c J t x).ofLp i
hc' : 𝓕.c.val ^ 2 * 𝓕.μ₀ = 1 / 𝓕.ε₀
hE : ∀ (j : Fin d), ContDiff ℝ 2 fun x => (electricField 𝓕.c A t x).ofLp j
hB : ∀ (j : Fin d), Differentiable ℝ fun s => Space.deriv j (fun x => magneticFieldMatrix 𝓕.c A s x (j, i)) x
hJt : Differentiable ℝ fun x_1 => (LorentzCurrentDensity.currentDensity 𝓕.c J x_1 x).ofLp i
hs2 :
  ∑ j, Space.deriv i (Space.deriv j fun x => (electricField 𝓕.c A t x).ofLp j) x =
    𝓕.ε₀⁻¹ * Space.deriv i (fun x => LorentzCurrentDensity.chargeDensity 𝓕.c J t x) x
⊢ 𝓕.c.val ^ 2 *
        (∑ x_1, Space.deriv x_1 (Space.deriv x_1 fun x => (electricField 𝓕.c A t x).ofLp i) x -
          𝓕.ε₀⁻¹ * Space.deriv i (fun x => LorentzCurrentDensity.chargeDensity 𝓕.c J t x) x) -
      1 / 𝓕.ε₀ * ∂ₜ (fun x_1 => (LorentzCurrentDensity.currentDensity 𝓕.c J x_1 x).ofLp i) t =
    𝓕.c.val ^ 2 * ∑ j, Space.deriv j (Space.deriv j fun x => (electricField 𝓕.c A t x).ofLp i) x -
        𝓕.c.val ^ 2 / 𝓕.ε₀ * Space.deriv i (fun x => LorentzCurrentDensity.chargeDensity 𝓕.c J t x) x -
      1 / 𝓕.ε₀ * ∂ₜ (fun x_1 => (LorentzCurrentDensity.currentDensity 𝓕.c J x_1 x).ofLp i) t
## Search map
### Best and original
best n2 score 78.33 tokens 573 heartbeats 6273
n1 original proof tokens 1372 heartbeats 26970
### Proof shapes (nodes grouped by structure, depth and status; each row is the group's best node; open-hole nodes have no score)
| node | status | tokens | heartbeats | score | nodes in group |
|---|---|---|---|---|---|
| n2 | compiles | 573 | 6273 | 78.33 | 1 |
### Latest nodes
| node | made from | status | tokens | heartbeats | score |
|---|---|---|---|---|---|
| n2 | new root | compiles | 573 | 6273 | 78.33 |
| n3 | made from n2 | does not compile | 572 | - | - |
### Steps of best n2, ranked by points at stake
pts: points if the step cost nothing · tries: nodes that changed it · shortest: token change of its shortest closed replacement, and that node (+ is longer) · last gain: nodes since a change to it raised the score
| step | tokens | heartbeats | pts | tries | shortest | last gain |
|---|---|---|---|---|---|---|
| s7 | 189 | 2214 | 7.33 | 0 | - | - |
| s9 | 157 | 1535 | 5.71 | 0 | - | - |
| s4 | 54 | 246 | 1.62 | 0 | - | - |
| s6 | 52 | 179 | 1.48 | 0 | - | - |
7 more steps at 1.33 pts or less.
### Lines of best n2 whose own tactic costs the most heartbeats
| line | text | heartbeats | tokens |
|---|---|---|---|
| 51 | `rw [← Finset.sum_apply, ← FunLike.coe_sum,` | 1168 | 8 |
| 29 | `rw [Time.deriv_eq,` | 754 | 4 |
| 34 | `simp only [_root_.sub_apply, _root_.smul_apply, smul_eq_mul]` | 509 | 9 |
| 42 | `rw [Space.fun_deriv_sub (Space.deriv j (A.electricField 𝓕.c t · i))` | 257 | 14 |
| 35 | `rw [← Time.deriv_eq, ← Time.deriv_eq]` | 231 | 8 |
### Lines of best n2 that run no tactic (stated terms, continued arguments), by tokens
heartbeats: spent elaborating a stated term where it stands (a chained relation's right side, a declared type); - when the line is part of a larger term.
| line | text | tokens | heartbeats |
|---|---|---|---|
| 53 | `show (fun y => ∑ j, Space.deriv j (A.electricField 𝓕.c t · j) y) = ∇ ⬝ (A.electricField 𝓕…` | 30 | 60 |
| 54 | `show (∇ ⬝ (A.electricField 𝓕.c t)) = fun y => 𝓕.ε₀⁻¹ * J.chargeDensity 𝓕.c t y from` | 22 | 31 |
| 40 | `(magneticFieldMatrix_contDiff _ (hA.of_le (right_eq_inf.mp rfl)) (j, i)) t x,` | 19 | - |
| 41 | `funext fun y => time_deriv_magneticFieldMatrix A (hA.of_le (right_eq_inf.mp rfl)) t y j i]` | 18 | - |
| 52 | `← fderiv_fun_sum (fun j _ => (Space.deriv_differentiable (hE j) j).differentiableAt),` | 18 | - |
Repeated text (shared once, saves):
5× 7 tok, saves 17 tok (0.41 pts): (hA.of_le (right_eq_inf.mp rfl))
4× 7 tok, saves 10 tok (0.24 pts): (A.electricField 𝓕.c t · j)
A tactic's heartbeats depend on the goal it runs on and how much it searches. A stated term costs its tokens wherever it appears; it leaves the proof only when nothing needs it stated.

budget: $0.00 of $0.10 spent · 99% left
````

## 10. `read`

**Call**

```json
{
  "node": "n2",
  "view": "outline"
}
```

**Reply** (1123 bytes)

````markdown
## Result
| step | lines | tokens | heartbeats | pts | first line |
|---|---|---|---|---|---|
| s1 | 10-10 | 11 | 11 | 0.28 | `have hG := (isExtrema_iff_gauss_ampere_magneticFieldMatrix …` |
| s2 | 11-14 | 37 | 350 | 1.33 | `have hc' : 𝓕.c ^ 2 * 𝓕.μ₀ = 1 / 𝓕.ε₀ := by` |
| s3 | 15-16 | 29 | 197 | 0.95 | `have hE : ∀ j, ContDiff ℝ 2 (A.electricField 𝓕.c t · j) :=` |
| s4 | 17-19 | 54 | 246 | 1.62 | `have hB : ∀ j, Differentiable ℝ (fun s => Space.deriv j (A.…` |
| s5 | 20-21 | 23 | 108 | 0.69 | `have hJt : Differentiable ℝ (J.currentDensity 𝓕.c · x i) :=` |
| s6 | 22-27 | 52 | 179 | 1.48 | `conv_lhs =>` |
| s7 | 28-46 | 189 | 2214 | 7.33 | `conv_lhs =>` |
| s8 | 47-47 | 13 | 29 | 0.35 | `conv_lhs => enter [1, 2]; rw [Finset.sum_sub_distrib]` |
| s9 | 48-58 | 157 | 1535 | 5.71 | `have hs2 : (∑ j, Space.deriv i (Space.deriv j (A.electricFi…` |
| s10 | 59-59 | 6 | 129 | 0.31 | `rw [hs2, hc']` |
| s11 | 60-60 | 1 | 133 | 0.19 | `ring` |
pts: points if the step cost nothing; - when not measured yet. step: sN gives one step's goals.

budget: $0.00 of $0.10 spent · 99% left
````

## 11. `read`

**Call**

```json
{
  "node": "n2",
  "view": "outline",
  "step": "s7"
}
```

**Reply** (2320 bytes)

````markdown
## Result
s7 lines 28-46
before: d : ℕ
A : ElectromagneticPotential d
𝓕 : FreeSpace
hA : ContDiff ℝ ∞ A.val
J : LorentzCurrentDensity d
hJ : ContDiff ℝ ∞ J
h : IsExtrema 𝓕 A J
t : Time
x : Space d
i : Fin d
hG :
  ∀ (t : Time) (x : Space d),
    Space.div (electricField 𝓕.c A t) x = LorentzCurrentDensity.chargeDensity 𝓕.c J t x / 𝓕.ε₀ ∧
      ∀ (i : Fin d),
        𝓕.μ₀ * 𝓕.ε₀ * (∂ₜ (fun t => electricField 𝓕.c A t x) t).ofLp i =
          ∑ j, Space.deriv j (fun x => magneticFieldMatrix 𝓕.c A t x (j, i)) x -
            𝓕.μ₀ * (LorentzCurrentDensity.currentDensity 𝓕.c J t x).ofLp i
hc' : 𝓕.c.val ^ 2 * 𝓕.μ₀ = 1 / 𝓕.ε₀
hE : ∀ (j : Fin d), ContDiff ℝ 2 fun x => (electricField 𝓕.c A t x).ofLp j
hB : ∀ (j : Fin d), Differentiable ℝ fun s => Space.deriv j (fun x => magneticFieldMatrix 𝓕.c A s x (j, i)) x
hJt : Differentiable ℝ fun x_1 => (LorentzCurrentDensity.currentDensity 𝓕.c J x_1 x).ofLp i
⊢ ∂ₜ
      (fun s =>
        𝓕.c.val ^ 2 * ∑ j, Space.deriv j (fun x => magneticFieldMatrix 𝓕.c A s x (j, i)) x -
          1 / 𝓕.ε₀ * (LorentzCurrentDensity.currentDensity 𝓕.c J s x).ofLp i)
      t =
    𝓕.c.val ^ 2 * ∑ j, Space.deriv j (Space.deriv j fun x => (electricField 𝓕.c A t x).ofLp i) x -
        𝓕.c.val ^ 2 / 𝓕.ε₀ * Space.deriv i (fun x => LorentzCurrentDensity.chargeDensity 𝓕.c J t x) x -
      𝓕.c.val ^ 2 * 𝓕.μ₀ * ∂ₜ (fun x_1 => (LorentzCurrentDensity.currentDensity 𝓕.c J x_1 x).ofLp i) t
after: (15 unchanged hypotheses omitted)
⊢ 𝓕.c.val ^ 2 *
        ∑ j,
          (Space.deriv j (Space.deriv j fun x => (electricField 𝓕.c A t x).ofLp i) x -
            Space.deriv i (Space.deriv j fun x => (electricField 𝓕.c A t x).ofLp j) x) -
      1 / 𝓕.ε₀ * ∂ₜ (fun x_1 => (LorentzCurrentDensity.currentDensity 𝓕.c J x_1 x).ofLp i) t =
    𝓕.c.val ^ 2 * ∑ j, Space.deriv j (Space.deriv j fun x => (electricField 𝓕.c A t x).ofLp i) x -
        𝓕.c.val ^ 2 / 𝓕.ε₀ * Space.deriv i (fun x => LorentzCurrentDensity.chargeDensity 𝓕.c J t x) x -
      𝓕.c.val ^ 2 * 𝓕.μ₀ * ∂ₜ (fun x_1 => (LorentzCurrentDensity.currentDensity 𝓕.c J x_1 x).ofLp i) t

budget: $0.00 of $0.10 spent · 99% left
````

## 12. `read`

**Call**

```json
{
  "node": "n2",
  "view": "prices"
}
```

**Reply** (1308 bytes)

````markdown
## Result
n2 tokens 573 heartbeats 6273 versions 1/1
| step | lines | tokens | self_hb | incl_hb | pts_if_gone | text |
|---|---|---|---|---|---|---|
| s1 | 10-10 | 11 | 11 | 11 | +0.28 | `have hG := (isExtrema_iff_gauss_ampere_m` |
| s2 | 11-14 | 37 | 17 | 350 | +1.33 | `have hc' : 𝓕.c ^ 2 * 𝓕.μ₀ = 1 / 𝓕.ε₀ := ` |
| s3 | 15-16 | 29 | 107 | 197 | +0.95 | `have hE : ∀ j, ContDiff ℝ 2 (A.electricF` |
| s4 | 17-19 | 54 | 153 | 246 | +1.62 | `have hB : ∀ j, Differentiable ℝ (fun s =` |
| s5 | 20-21 | 23 | 28 | 108 | +0.69 | `have hJt : Differentiable ℝ (J.currentDe` |
| s6 | 22-27 | 52 | 19 | 179 | +1.48 | `conv_lhs =>` |
| s7 | 28-46 | 189 | 25 | 2214 | +7.33 | `conv_lhs =>` |
| s8 | 47-47 | 13 | 17 | 29 | +0.35 | `conv_lhs => enter [1, 2]; rw [Finset.sum` |
| s9 | 48-58 | 157 | 3 | 1535 | +5.71 | `have hs2 : (∑ j, Space.deriv i (Space.de` |
| s10 | 59-59 | 6 | 129 | 129 | +0.31 | `rw [hs2, hc']` |
| s11 | 60-60 | 1 | 133 | 133 | +0.19 | `ring` |
| total | - | 573 | - | 6273 | - | versions 1/1 · score 78.33 |
self_hb: heartbeats of the step alone.
incl_hb: heartbeats of the step with its nested steps.
pts_if_gone: upper bound on the points gained by removing the step.
versions: listed versions on which the proof compiles.

budget: $0.00 of $0.10 spent · 99% left
````

## 13. `read`

**Call**

```json
{
  "node": "n2",
  "view": "tree"
}
```

**Reply** (4210 bytes)

````markdown
## Result
### Cost tree of n2: profiled tactics and stated terms in source order, · per nesting level; tokens and heartbeats include nested nodes, own heartbeats exclude them; pts: points if the node cost nothing
| line | node | kind | tokens | heartbeats | own heartbeats | pts |
|---|---|---|---|---|---|---|
| 10 | `have hG := (isExtrema_iff_gauss_ampere_magneticFieldMatrix hA J hJ).mp h` | tactic | 11 | 11 | 11 | 0.28 |
| 11 | `have hc' : 𝓕.c ^ 2 * 𝓕.μ₀ = 1 / 𝓕.ε₀ := by rw [FreeSpace.c_sq, mul_comm 𝓕.ε₀ 𝓕.μ₀, div_eq…` | tactic | 37 | 350 | 17 | 1.33 |
| 11 | `· 𝓕.c ^ 2 * 𝓕.μ₀ = 1 / 𝓕.ε₀` | term | 9 | 154 | 154 | 0.41 |
| 12 | `· rw [FreeSpace.c_sq, mul_comm 𝓕.ε₀ 𝓕.μ₀, div_eq_mul_inv, one_mul, mul_inv_rev, mul_assoc, …` | tactic | 22 | 122 | 122 | 0.69 |
| 15 | `have hE : ∀ j, ContDiff ℝ 2 (A.electricField 𝓕.c t · j) := fun j => electricField_apply_c…` | tactic | 29 | 197 | 107 | 0.95 |
| 15 | `· ∀ j, ContDiff ℝ 2 (A.electricField 𝓕.c t · j)` | term | 13 | 90 | 90 | 0.43 |
| 17 | `have hB : ∀ j, Differentiable ℝ (fun s => Space.deriv j (A.magneticFieldMatrix 𝓕.c s · (j…` | tactic | 54 | 246 | 153 | 1.62 |
| 17 | `· ∀ j, Differentiable ℝ (fun s => Space.deriv j (A.magneticFieldMatrix 𝓕.c s · (j, i)) x)` | term | 24 | 93 | 93 | 0.7 |
| 20 | `have hJt : Differentiable ℝ (J.currentDensity 𝓕.c · x i) := LorentzCurrentDensity.current…` | tactic | 23 | 108 | 28 | 0.69 |
| 20 | `· Differentiable ℝ (J.currentDensity 𝓕.c · x i)` | term | 9 | 30 | 30 | 0.26 |
| 22 | `conv_lhs => enter [1] change fun s => ∂ₜ (A.electricField 𝓕.c · x i) s enter [s] rw [Time…` | tactic | 52 | 179 | 19 | 1.48 |
| 24 | `· change fun s => ∂ₜ (A.electricField 𝓕.c · x i) s` | tactic | 14 | 44 | 44 | 0.39 |
| 26 | `· rw [Time.deriv_euclid (electricField_differentiable_time (hA.of_le (right_eq_inf.mp rfl))…` | tactic | 28 | 114 | 114 | 0.82 |
| 28 | `conv_lhs => rw [Time.deriv_eq, fderiv_fun_sub ((Differentiable.fun_sum fun j _ => hB j).c…` | tactic | 189 | 2214 | 25 | 7.33 |
| 29 | `· rw [Time.deriv_eq, fderiv_fun_sub ((Differentiable.fun_sum fun j _ => hB j).const_mul _).…` | tactic | 40 | 754 | 754 | 1.9 |
| 34 | `· simp only [_root_.sub_apply, _root_.smul_apply, smul_eq_mul]` | tactic | 9 | 509 | 509 | 0.85 |
| 35 | `· rw [← Time.deriv_eq, ← Time.deriv_eq]` | tactic | 8 | 231 | 231 | 0.48 |
| 37 | `· rw [Time.deriv_fun_sum (ha := fun j _ => (hB j).differentiableAt)]` | tactic | 17 | 139 | 139 | 0.58 |
| 39 | `· rw [Space.time_deriv_comm_space_deriv (i := j) (magneticFieldMatrix_contDiff _ (hA.of_le …` | tactic | 45 | 179 | 179 | 1.31 |
| 42 | `· rw [Space.fun_deriv_sub (Space.deriv j (A.electricField 𝓕.c t · i)) (Space.deriv i (A.ele…` | tactic | 42 | 257 | 257 | 1.34 |
| 46 | `· rw [congrFun (Space.deriv_commute _ (hE j)) x]` | tactic | 13 | 115 | 115 | 0.46 |
| 47 | `conv_lhs => enter [1, 2]; rw [Finset.sum_sub_distrib]` | tactic | 13 | 29 | 17 | 0.35 |
| 48 | `have hs2 : (∑ j, Space.deriv i (Space.deriv j (A.electricField 𝓕.c t · j)) x) = 𝓕.ε₀⁻¹ * …` | tactic | 157 | 1535 | 3 | 5.71 |
| 48 | `· (∑ j, Space.deriv i (Space.deriv j (A.electricField 𝓕.c t · j)) x) = 𝓕.ε₀⁻¹ * Space.deriv…` | term | 32 | 101 | 101 | 0.9 |
| 50 | `· simp only [Space.deriv_eq_fderiv_basis]` | tactic | 5 | 76 | 76 | 0.22 |
| 51 | `· rw [← Finset.sum_apply, ← FunLike.coe_sum, ← fderiv_fun_sum (fun j _ => (Space.deriv_diff…` | tactic | 115 | 1355 | 1168 | 4.47 |
| 53 | `· · (fun y => ∑ j, Space.deriv j (A.electricField 𝓕.c t · j) y) = ∇ ⬝ (A.electricField 𝓕.c t)` | term | 26 | 60 | 60 | 0.71 |
| 54 | `· · (∇ ⬝ (A.electricField 𝓕.c t)) = fun y => 𝓕.ε₀⁻¹ * J.chargeDensity 𝓕.c t y` | term | 20 | 31 | 31 | 0.52 |
| 55 | `· · rw [(hG t y).1, div_eq_mul_inv, mul_comm]` | tactic | 13 | 45 | 45 | 0.37 |
| 59 | `rw [hs2, hc']` | tactic | 6 | 129 | 129 | 0.31 |
4 smaller nodes not shown.
Measured 6273 heartbeats; 5131 spent in the top-level nodes above; 1142 outside every node: 664 for the statement, 478 after the proof.

budget: $0.00 of $0.10 spent · 99% left
````

## 14. `read`

**Call**

```json
{
  "view": "map"
}
```

**Reply** (2882 bytes)

````markdown
## Search map
### Best and original
best n2 score 78.33 tokens 573 heartbeats 6273
n1 original proof tokens 1372 heartbeats 26970
### Proof shapes (nodes grouped by structure, depth and status; each row is the group's best node; open-hole nodes have no score)
| node | status | tokens | heartbeats | score | nodes in group |
|---|---|---|---|---|---|
| n2 | compiles | 573 | 6273 | 78.33 | 1 |
### Latest nodes
| node | made from | status | tokens | heartbeats | score |
|---|---|---|---|---|---|
| n2 | new root | compiles | 573 | 6273 | 78.33 |
| n3 | made from n2 | does not compile | 572 | - | - |
### Steps of best n2, ranked by points at stake
pts: points if the step cost nothing · tries: nodes that changed it · shortest: token change of its shortest closed replacement, and that node (+ is longer) · last gain: nodes since a change to it raised the score
| step | tokens | heartbeats | pts | tries | shortest | last gain |
|---|---|---|---|---|---|---|
| s7 | 189 | 2214 | 7.33 | 0 | - | - |
| s9 | 157 | 1535 | 5.71 | 0 | - | - |
| s4 | 54 | 246 | 1.62 | 0 | - | - |
| s6 | 52 | 179 | 1.48 | 0 | - | - |
7 more steps at 1.33 pts or less.
### Lines of best n2 whose own tactic costs the most heartbeats
| line | text | heartbeats | tokens |
|---|---|---|---|
| 51 | `rw [← Finset.sum_apply, ← FunLike.coe_sum,` | 1168 | 8 |
| 29 | `rw [Time.deriv_eq,` | 754 | 4 |
| 34 | `simp only [_root_.sub_apply, _root_.smul_apply, smul_eq_mul]` | 509 | 9 |
| 42 | `rw [Space.fun_deriv_sub (Space.deriv j (A.electricField 𝓕.c t · i))` | 257 | 14 |
| 35 | `rw [← Time.deriv_eq, ← Time.deriv_eq]` | 231 | 8 |
### Lines of best n2 that run no tactic (stated terms, continued arguments), by tokens
heartbeats: spent elaborating a stated term where it stands (a chained relation's right side, a declared type); - when the line is part of a larger term.
| line | text | tokens | heartbeats |
|---|---|---|---|
| 53 | `show (fun y => ∑ j, Space.deriv j (A.electricField 𝓕.c t · j) y) = ∇ ⬝ (A.electricField 𝓕…` | 30 | 60 |
| 54 | `show (∇ ⬝ (A.electricField 𝓕.c t)) = fun y => 𝓕.ε₀⁻¹ * J.chargeDensity 𝓕.c t y from` | 22 | 31 |
| 40 | `(magneticFieldMatrix_contDiff _ (hA.of_le (right_eq_inf.mp rfl)) (j, i)) t x,` | 19 | - |
| 41 | `funext fun y => time_deriv_magneticFieldMatrix A (hA.of_le (right_eq_inf.mp rfl)) t y j i]` | 18 | - |
| 52 | `← fderiv_fun_sum (fun j _ => (Space.deriv_differentiable (hE j) j).differentiableAt),` | 18 | - |
Repeated text (shared once, saves):
5× 7 tok, saves 17 tok (0.41 pts): (hA.of_le (right_eq_inf.mp rfl))
4× 7 tok, saves 10 tok (0.24 pts): (A.electricField 𝓕.c t · j)
A tactic's heartbeats depend on the goal it runs on and how much it searches. A stated term costs its tokens wherever it appears; it leaves the proof only when nothing needs it stated.

budget: $0.09 of $0.10 spent · 9% left
````
