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

## Task (154 chars, 14 words)
Theorem: Cslib.SKI.parallelReduction_diamond
Original proof: node n1.
Statement:
```lean
theorem parallelReduction_diamond : Diamond ParallelReduction
```

## Scoring (853 chars, 144 words)
Score: the mean of three percentages: token reduction, heartbeat reduction and compatibility.
Token reduction: percent fewer tokens than the reference proof (407 tokens).
Heartbeat reduction: percent fewer heartbeats than the reference proof (1383 heartbeats).
Compatibility: percent of the listed versions on which the proof compiles.
A proof that does not compile scores zero.
Rates: 1 token = 0.082 points; 100 heartbeats = 2.41 points; 1 version = 8.33 points.
Token count: proof text after `:=`, without comments and attributes.
Each identifier or number counts 1 token, whatever its length.
Each other nonspace character counts 1 token, except these groups, which count 1 token each: `:= != && -. -> ← .. ... :: :> <;> ;; == || => <= >= ⁻¹ ?_`.
Spaces and line breaks count 0; a tab counts 1.
Examples: `exact foo` = 2 tokens; `⟨a, b⟩` = 5 tokens.

## Pinned environment (445 chars, 36 words)
Pinned environment
Source: cslib:Cslib/Languages/CombinatoryLogic/Confluence.lean:142-205
Lean toolchain and source revisions: Lean v4.33.0-rc2 / source revision 3aa9d4416c185e0b9faeb72bbd65abe85b95dbcc; Lean v4.32.0 / source revision 197a7be621263b84c67ca4f803f69205b36d06df; Lean v4.31.0 / source revision 8ea71c8df91acd63285515a04da952b23b78d266; Lean v4.30.0 / source revision c7944a9fb44c3298f1a960a5e574ab23a6ab8ed5
Available imports: none

## Scope at the theorem (namespace, open, variable, universe in effect before the statement) (132 chars, 19 words)
Scope at the theorem (namespace, open, variable, universe in effect before the statement)
namespace Cslib.SKI
open Red MRed Relation

## Original proof and step prices (407 tokens) (2770 chars, 543 words)
Original proof and step prices (407 tokens)
```lean
theorem parallelReduction_diamond : Diamond ParallelReduction := by
  intro a a₁ a₂ h₁ h₂
  cases h₁
  case refl => exact ⟨a₂, h₂, .refl a₂⟩
  case par a a' b b' ha' hb' =>
    cases h₂
    case refl =>
      use a' ⬝ b'
      exact ⟨.refl (a' ⬝ b'), .par ha' hb'⟩
    case par a'' b'' ha'' hb'' =>
      let ⟨a₃, ha⟩ := parallelReduction_diamond ha' ha''
      let ⟨b₃, hb⟩ := parallelReduction_diamond hb' hb''
      use a₃ ⬝ b₃
      constructor
      · exact .par ha.1 hb.1
      · exact .par ha.2 hb.2
    case red_I =>
      rw [I_irreducible a' ha']
      use b', .red_I b'
    case red_K =>
      let ⟨a₂', ha₂'⟩ := Ka_irreducible a₂ a' ha'
      rw [ha₂'.2]
      use a₂'
      exact ⟨.red_K a₂' b', ha₂'.1⟩
    case red_S a c =>
      let ⟨a'', c', h⟩ := Sab_irreducible a c a' ha'
      rw [h.2.2]
      use a'' ⬝ b' ⬝ (c' ⬝ b'), .red_S a'' c' b'
      apply ParallelReduction.par <;>
        apply ParallelReduction.par <;>
        grind
  case red_I =>
    cases h₂
    case refl => use a₁; exact ⟨.refl a₁, .red_I a₁⟩
    case par c a₁' hc ha =>
      rw [I_irreducible c hc]
      use a₁'
      exact ⟨ha, .red_I a₁'⟩
    case red_I => use a₁; exact ⟨.refl a₁, .refl a₁⟩
  case red_K c =>
    cases h₂
    case refl => use a₁; exact ⟨.refl a₁, .red_K a₁ c⟩
    case par a' c' ha hc =>
      let ⟨a₁', h'⟩ := Ka_irreducible a₁ a' ha
      rw [h'.2]
      use a₁'
      exact ⟨h'.1, .red_K a₁' c'⟩
    case red_K =>
      use a₁; exact ⟨.refl a₁, .refl a₁⟩
  case red_S a b c =>
    cases h₂
    case refl =>
      use a ⬝ c ⬝ (b ⬝ c)
      exact ⟨.refl _, .red_S ..⟩
    case par d c' hd hc =>
      let ⟨a', b', h⟩ := Sab_irreducible a b d hd
      rw [h.2.2]
      use a' ⬝ c' ⬝ (b' ⬝ c')
      constructor
      · apply ParallelReduction.par
        · exact .par h.left hc
        · exact .par h.2.1 hc
      · exact .red_S ..
    case red_S => exact ⟨a ⬝ c ⬝ (b ⬝ c), .refl _, .refl _,⟩
```
| step | lines | tokens | self_hb | incl_hb | pts_if_gone | text |
|---|---|---|---|---|---|---|
| s1 | 2-2 | 6 | 1 | 1 | +0.52 | `intro a a₁ a₂ h₁ h₂` |
| s2 | 3-3 | 2 | 23 | 23 | +0.72 | `cases h₁` |
| s3 | 4-4 | 12 | 0 | 6 | +1.13 | `case refl => exact ⟨a₂, h₂, .refl a₂⟩` |
| s4 | 5-31 | 160 | 4 | 412 | +23.03 | `case par a a' b b' ha' hb' =>` |
| s5 | 32-39 | 55 | 3 | 163 | +8.43 | `case red_I =>` |
| s6 | 40-49 | 67 | 3 | 185 | +9.95 | `case red_K c =>` |
| s7 | 50-64 | 104 | 2 | 196 | +13.24 | `case red_S a b c =>` |
| total | - | 407 | - | 1384 | - | versions 4/4 · score 33.33 |
self_hb: heartbeats of the step alone.
incl_hb: heartbeats of the step with its nested steps.
pts_if_gone: upper bound on the points gained by removing the step.
versions: listed versions on which the proof compiles.

## Original proof heartbeats by line (1061 chars, 252 words)
Original proof heartbeats by line
line 8 · 42 self hb · 4 tokens · use a' ⬝ b'
line 13 · 46 self hb · 4 tokens · use a₃ ⬝ b₃
line 23 · 42 self hb · 2 tokens · use a₂'
line 29 · 67 self hb · 3 tokens · apply ParallelReduction.par <;>
line 34 · 42 self hb · 14 tokens · case refl => use a₁; exact ⟨.refl a₁, .red_I a₁⟩
line 37 · 43 self hb · 2 tokens · use a₁'
line 39 · 42 self hb · 14 tokens · case red_I => use a₁; exact ⟨.refl a₁, .refl a₁⟩
line 42 · 43 self hb · 15 tokens · case refl => use a₁; exact ⟨.refl a₁, .red_K a₁ c⟩
line 46 · 42 self hb · 2 tokens · use a₁'
line 49 · 41 self hb · 11 tokens · use a₁; exact ⟨.refl a₁, .refl a₁⟩
line 53 · 43 self hb · 10 tokens · use a ⬝ c ⬝ (b ⬝ c)
line 58 · 47 self hb · 10 tokens · use a' ⬝ c' ⬝ (b' ⬝ c')
Measured 1384 heartbeats; 986 are attributed to lines (top 12 by self hb shown); 398 (28.8%) are not tied to any line.
The original proof refers to its own theorem name at proof lines 11, 12. The 398 heartbeats outside any line are not split by cause; Lean may spend part of them checking those references.

## Goals before original steps (1616 chars, 411 words)
Goals before original steps
before s1: ⊢ Diamond ParallelReduction
before s2: a a₁ a₂ : SKI
h₁ : a ⭢ₚ a₁
h₂ : a ⭢ₚ a₂
⊢ Join ParallelReduction a₁ a₂
before s3: case refl
a a₂ : SKI
h₂ : a ⭢ₚ a₂
⊢ Join ParallelReduction a a₂
case red_I
a₁ a₂ : SKI
h₂ : (I ⬝ a₁) ⭢ₚ a₂
⊢ Join ParallelReduction a₁ a₂
case red_K
a₁ a₂ b✝ : SKI
h₂ : (K ⬝ a₁ ⬝ b✝) ⭢ₚ a₂
⊢ Join ParallelReduction a₁ a₂
case red_S
a₂ a✝ b✝ c✝ : SKI
h₂ : (S ⬝ a✝ ⬝ b✝ ⬝ c✝) ⭢ₚ a₂
⊢ Join ParallelReduction (a✝ ⬝ c✝ ⬝ (b✝ ⬝ c✝)) a₂
case par
a₂ a✝² a'✝ b✝ b'✝ : SKI
a✝¹ : a✝² ⭢ₚ a'✝
a✝ : b✝ ⭢ₚ b'✝
h₂ : (a✝² ⬝ b✝) ⭢ₚ a₂
⊢ Join ParallelReduction (a'✝ ⬝ b'✝) a₂
before s4: case red_I
a₁ a₂ : SKI
h₂ : (I ⬝ a₁) ⭢ₚ a₂
⊢ Join ParallelReduction a₁ a₂
case red_K
a₁ a₂ b✝ : SKI
h₂ : (K ⬝ a₁ ⬝ b✝) ⭢ₚ a₂
⊢ Join ParallelReduction a₁ a₂
case red_S
a₂ a✝ b✝ c✝ : SKI
h₂ : (S ⬝ a✝ ⬝ b✝ ⬝ c✝) ⭢ₚ a₂
⊢ Join ParallelReduction (a✝ ⬝ c✝ ⬝ (b✝ ⬝ c✝)) a₂
case par
a₂ a✝² a'✝ b✝ b'✝ : SKI
a✝¹ : a✝² ⭢ₚ a'✝
a✝ : b✝ ⭢ₚ b'✝
h₂ : (a✝² ⬝ b✝) ⭢ₚ a₂
⊢ Join ParallelReduction (a'✝ ⬝ b'✝) a₂
before s5: case red_I
a₁ a₂ : SKI
h₂ : (I ⬝ a₁) ⭢ₚ a₂
⊢ Join ParallelReduction a₁ a₂
case red_K
a₁ a₂ b✝ : SKI
h₂ : (K ⬝ a₁ ⬝ b✝) ⭢ₚ a₂
⊢ Join ParallelReduction a₁ a₂
case red_S
a₂ a✝ b✝ c✝ : SKI
h₂ : (S ⬝ a✝ ⬝ b✝ ⬝ c✝) ⭢ₚ a₂
⊢ Join ParallelReduction (a✝ ⬝ c✝ ⬝ (b✝ ⬝ c✝)) a₂
before s6: case red_K
a₁ a₂ b✝ : SKI
h₂ : (K ⬝ a₁ ⬝ b✝) ⭢ₚ a₂
⊢ Join ParallelReduction a₁ a₂
case red_S
a₂ a✝ b✝ c✝ : SKI
h₂ : (S ⬝ a✝ ⬝ b✝ ⬝ c✝) ⭢ₚ a₂
⊢ Join ParallelReduction (a✝ ⬝ c✝ ⬝ (b✝ ⬝ c✝)) a₂
before s7: case red_S
a₂ a✝ b✝ c✝ : SKI
h₂ : (S ⬝ a✝ ⬝ b✝ ⬝ c✝) ⭢ₚ a₂
⊢ Join ParallelReduction (a✝ ⬝ c✝ ⬝ (b✝ ⬝ c✝)) a₂

## Imported declarations (ranked) (7027 chars, 1398 words)
Imported declarations (ranked)
1. decl:Relation.Diamond.extend · Cslib.Foundations.Relation.Confluence · Relation.Diamond.extend : ∀ {α : Type u_1} {r : α → α → Prop} {a b c : α}, Diamond r → ReflTransGen r a b → r a c → Join (ReflTransGen r) b c
2. decl:Relation.Diamond.toConfluent · Cslib.Foundations.Relation.Confluence · Relation.Diamond.toConfluent : ∀ {α : Type u_1} {r : α → α → Prop}, Diamond r → Confluent r
3. decl:Cslib.SKI.parallel_mRed · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.parallel_mRed : ∀ {a a' b b' : SKI}, a ↠ a' → b ↠ b' → (a ⬝ b) ↠ a' ⬝ b'
4. decl:Cslib.SKI.parallel_red · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.parallel_red : ∀ {a a' b b' : SKI}, a ⭢ a' → b ⭢ b' → (a ⬝ b) ↠ a' ⬝ b'
5. decl:Cslib.SKI.mJoin_red_head · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.mJoin_red_head : ∀ {x x' : SKI} (y : SKI), MJoin Red x x' → MJoin Red (x ⬝ y) (x' ⬝ y)
6. decl:Cslib.SKI.mJoin_red_tail · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.mJoin_red_tail : ∀ (x : SKI) {y y' : SKI}, MJoin Red y y' → MJoin Red (x ⬝ y) (x ⬝ y')
7. decl:Relation.Join.refl · Mathlib.Logic.Relation · Relation.Join.refl : ∀ {α : Type u_1} {r : α → α → Prop} [Std.Refl r], Std.Refl (Join r)
8. decl:Cslib.SKI.MRed.I · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.MRed.I : ∀ (x : SKI), (I ⬝ x) ↠ x
9. decl:Cslib.SKI.MRed.K · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.MRed.K : ∀ (x y : SKI), (K ⬝ x ⬝ y) ↠ x
10. decl:Cslib.SKI.MRed.S · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.MRed.S : ∀ (x y z : SKI), (S ⬝ x ⬝ y ⬝ z) ↠ x ⬝ z ⬝ (y ⬝ z)
11. decl:Relation.Join.symm · Mathlib.Logic.Relation · Relation.Join.symm : ∀ {α : Type u_1} {r : α → α → Prop}, Std.Symm (Join r)
12. decl:Cslib.SKI.applyList_concat · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.applyList_concat : ∀ (f : SKI) (ys : List SKI) (z : SKI), f.applyList (ys ++ [z]) = f.applyList ys ⬝ z
13. decl:Cslib.SKI.«term_↠_» · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.«term_↠_» : Lean.TrailingParserDescr
14. decl:Cslib.SKI.«term_⬝_» · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.«term_⬝_» : Lean.TrailingParserDescr
15. decl:Cslib.SKI.«term_⭢_» · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.«term_⭢_» : Lean.TrailingParserDescr
16. decl:Cslib.SKI.MRed.head · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.MRed.head : ∀ {a a' : SKI} (b : SKI), a ↠ a' → (a ⬝ b) ↠ a' ⬝ b
17. decl:Cslib.SKI.MRed.tail · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.MRed.tail : ∀ (a : SKI) {b b' : SKI}, b ↠ b' → (a ⬝ b) ↠ a ⬝ b'
18. decl:Cslib.instReprSKI.repr · Cslib.Languages.CombinatoryLogic.Defs · Cslib.instReprSKI.repr : SKI → ℕ → Std.Format
19. decl:Lean.Grind.exists_and_left · Init.Grind.Norm · Lean.Grind.exists_and_left : ∀ {α : Sort u} {p : α → Prop} {b : Prop}, (∃ x, b ∧ p x) = (b ∧ ∃ x, p x)
20. decl:Lean.Grind.exists_and_right · Init.Grind.Norm · Lean.Grind.exists_and_right : ∀ {α : Sort u} {p : α → Prop} {b : Prop}, (∃ x, p x ∧ b) = ((∃ x, p x) ∧ b)
21. decl:Lean.Grind.exists_prop · Init.Grind.Norm · Lean.Grind.exists_prop : ∀ {a b : Prop}, (∃ _h, b) = (a ∧ b)
22. decl:Relation.DiamondCommute.toDiamond · Cslib.Foundations.Relation.Confluence · Relation.DiamondCommute.toDiamond : ∀ {α : Type u_1} {r : α → α → Prop}, DiamondCommute r r = Diamond r
23. decl:Exists.elim · Init.Core · Exists.elim : ∀ {α : Sort u} {p : α → Prop} {b : Prop}, (∃ x, p x) → (∀ (a : α), p a → b) → b
24. decl:Exists.fst · Mathlib.Logic.Basic · Exists.fst : ∀ {b : Prop} {p : b → Prop}, Exists p → b
25. decl:Exists.imp · Init.PropLemmas · Exists.imp : ∀ {α : Sort u_1} {p q : α → Prop}, (∀ (a : α), p a → q a) → (∃ a, p a) → ∃ a, q a
26. decl:Exists.imp' · Init.PropLemmas · Exists.imp' : ∀ {α : Sort u_2} {p : α → Prop} {β : Sort u_1} {q : β → Prop} (f : α → β), (∀ (a : α), p a → q (f a)) → (∃ a, p a) → ∃ b, q b
27. decl:And.imp · Init.PropLemmas · And.imp : ∀ {a c b d : Prop}, (a → c) → (b → d) → a ∧ b → c ∧ d
28. decl:And.imp_left · Init.PropLemmas · And.imp_left : ∀ {a b c : Prop}, (a → b) → a ∧ c → b ∧ c
29. decl:And.imp_right · Init.PropLemmas · And.imp_right : ∀ {a b c : Prop}, (a → b) → c ∧ a → c ∧ b
30. decl:And.right · Init.Prelude · And.right : ∀ {a b : Prop}, a ∧ b → b
31. decl:And.rotate · Mathlib.Logic.Basic · And.rotate : ∀ {a b c : Prop}, a ∧ b ∧ c → b ∧ c ∧ a
32. decl:And.symm · Init.Core · And.symm : ∀ {a b : Prop}, a ∧ b → b ∧ a
33. decl:Cslib.SKI.Red.ne · Cslib.Languages.CombinatoryLogic.Defs · Cslib.SKI.Red.ne : ∀ {x y : SKI}, x ⭢ y → x ≠ y
34. decl:Relation.reflexive_join · Mathlib.Logic.Relation · Relation.reflexive_join : ∀ {α : Type u_1} {r : α → α → Prop} [Std.Refl r], Std.Refl (Join r)
35. decl:exists_eq_left · Init.PropLemmas · exists_eq_left : ∀ {α : Sort u_1} {p : α → Prop} {a' : α}, (∃ a, a = a' ∧ p a) ↔ p a'
36. decl:exists_eq_left' · Init.PropLemmas · exists_eq_left' : ∀ {α : Sort u_1} {p : α → Prop} {a' : α}, (∃ a, a' = a ∧ p a) ↔ p a'
37. decl:exists_eq_right · Init.PropLemmas · exists_eq_right : ∀ {α : Sort u_1} {p : α → Prop} {a' : α}, (∃ a, p a ∧ a = a') ↔ p a'
38. decl:exists_eq_right' · Init.PropLemmas · exists_eq_right' : ∀ {α : Sort u_1} {p : α → Prop} {a' : α}, (∃ a, p a ∧ a' = a) ↔ p a'
39. decl:exists_eq_right_right · Init.PropLemmas · exists_eq_right_right : ∀ {α : Sort u_1} {p q : α → Prop} {a' : α}, (∃ a, p a ∧ q a ∧ a = a') ↔ p a' ∧ q a'
40. decl:exists_eq_right_right' · Init.PropLemmas · exists_eq_right_right' : ∀ {α : Sort u_1} {p q : α → Prop} {a' : α}, (∃ a, p a ∧ q a ∧ a' = a) ↔ p a' ∧ q a'
41. decl:exists_exists_and_eq_and · Mathlib.Logic.Basic · exists_exists_and_eq_and : ∀ {α : Sort u_1} {β : Sort u_2} {f : α → β} {p : α → Prop} {q : β → Prop}, (∃ b, (∃ a, p a ∧ f a = b) ∧ q b) ↔ ∃ a, p a ∧ q (f a)
42. decl:exists_exists_and_exists_and_eq_and · Mathlib.Logic.Basic · exists_exists_and_exists_and_eq_and : ∀ {α : Type u_3} {β : Type u_4} {γ : Type u_5} {f : α → β → γ} {p : α → Prop} {q : β → Prop} {r : γ → Prop}, (∃ c, (∃ a, p a ∧ ∃ b, q b ∧ f a b = c) ∧ r c) ↔ ∃ a, p a ∧ ∃ b, q b ∧ r (f a b)
43. decl:exists_exists_eq_and · Mathlib.Logic.Basic · exists_exists_eq_and : ∀ {α : Sort u_1} {β : Sort u_2} {f : α → β} {p : β → Prop}, (∃ b, (∃ a, f a = b) ∧ p b) ↔ ∃ a, p (f a)
44. decl:exists_exists_exists_and_eq · Mathlib.Logic.Basic · exists_exists_exists_and_eq : ∀ {α : Type u_3} {β : Type u_4} {γ : Type u_5} {f : α → β → γ} {p : γ → Prop}, (∃ c, (∃ a b, f a b = c) ∧ p c) ↔ ∃ a b, p (f a b)
45. decl:Relation.church_rosser · Mathlib.Logic.Relation · Relation.church_rosser : ∀ {α : Type u_1} {r : α → α → Prop} {a b c : α}, (∀ (a b c : α), r a b → r a c → ∃ d, ReflGen r b d ∧ ReflTransGen r c d) → ReflTransGen r a b → ReflTransGen r a c → Join (ReflTransGen r) b c
46. decl:Relation.isTrans_join · Mathlib.Logic.Relation · Relation.isTrans_join : ∀ {α : Type u_1} {r : α → α → Prop} [IsTrans α r], (∀ (a b c : α), r a b → r a c → Join r b c) → IsTrans α (Join r)
47. decl:Relation.symmetric_join · Mathlib.Logic.Relation · Relation.symmetric_join : ∀ {α : Type u_1} {r : α → α → Prop}, Std.Symm (Join r)

## Definitions of project types and predicates in the statement (831 chars, 168 words)
Definitions of project types and predicates in the statement
decl:Relation.Diamond [def] Relation.Diamond : {α : Type u_1} → (α → α → Prop) → Prop
  := fun {α} r => ∀ {a b c : α}, r a b → r a c → Join r b c
decl:Cslib.SKI [inductive] Cslib.SKI : Type
  | Cslib.SKI.S : SKI
  | Cslib.SKI.K : SKI
  | Cslib.SKI.I : SKI
  | Cslib.SKI.app : SKI → SKI → SKI
decl:Cslib.SKI.ParallelReduction [inductive] Cslib.SKI.ParallelReduction : SKI → SKI → Prop
  | Cslib.SKI.ParallelReduction.refl : ∀ (a : SKI), a ⭢ₚ a
  | Cslib.SKI.ParallelReduction.red_I : ∀ (a : SKI), (I ⬝ a) ⭢ₚ a
  | Cslib.SKI.ParallelReduction.red_K : ∀ (a b : SKI), (K ⬝ a ⬝ b) ⭢ₚ a
  | Cslib.SKI.ParallelReduction.red_S : ∀ (a b c : SKI), (S ⬝ a ⬝ b ⬝ c) ⭢ₚ a ⬝ c ⬝ (b ⬝ c)
  | Cslib.SKI.ParallelReduction.par : ∀ ⦃a a' b b' : SKI⦄, a ⭢ₚ a' → b ⭢ₚ b' → (a ⬝ b) ⭢ₚ a' ⬝ b'

## Source-named declarations (1283 chars, 197 words)
Source-named declarations
Qualified name [kind] S:statement lines P:proof lines U:lines whose position could not be placed (no top-level `:=` found); use `decl:<name>` as its source handle.
decl:And.left [theorem] S:- P:61
decl:Cslib.SKI.I_irreducible [theorem] S:- P:18,36
decl:Cslib.SKI.Ka_irreducible [theorem] S:- P:21,44
decl:Cslib.SKI.ParallelReduction [inductive] S:1,1 P:-
decl:Cslib.SKI.ParallelReduction.par [constructor] S:- P:29,30,30,60
decl:Cslib.SKI.Sab_irreducible [theorem] S:- P:26,56
decl:Relation.Diamond [def] S:1 P:-

Signature preview: 5 shown of 7 distinct source names; 0 unavailable.
[decl:Cslib.SKI.I_irreducible · theorem · this file] Cslib.SKI.I_irreducible : ∀ (a : SKI), I ⭢ₚ a → a = I
[decl:Cslib.SKI.Ka_irreducible · theorem · this file] Cslib.SKI.Ka_irreducible : ∀ (a c : SKI), (K ⬝ a) ⭢ₚ c → ∃ a', a ⭢ₚ a' ∧ c = K ⬝ a'
[decl:Cslib.SKI.ParallelReduction · inductive · this file] Cslib.SKI.ParallelReduction : SKI → SKI → Prop
[decl:Cslib.SKI.ParallelReduction.par · constructor · this file] Cslib.SKI.ParallelReduction.par : ∀ ⦃a a' b b' : SKI⦄, a ⭢ₚ a' → b ⭢ₚ b' → (a ⬝ b) ⭢ₚ a' ⬝ b'
[decl:Cslib.SKI.Sab_irreducible · theorem · this file] Cslib.SKI.Sab_irreducible : ∀ (a b c : SKI), (S ⬝ a ⬝ b) ⭢ₚ c → ∃ a' b', a ⭢ₚ a' ∧ b ⭢ₚ b' ∧ c = S ⬝ a' ⬝ b'

## Local variables (2548 chars, 487 words)
Local variables
Local variable name : type; lines are where the Lean local context exposes the variable.
a : SKI [scope: theorem proof context; lines: 26,53,56,64]
a' : SKI [scope: theorem proof context; lines: 8,9,18,21,26,44,58]
a'' : SKI [scope: theorem proof context; lines: 28]
a₁ : SKI [scope: theorem proof context; lines: 34,39,42,44,49]
a₁' : SKI [scope: theorem proof context; lines: 37,38,46,47]
a₂ : SKI [scope: theorem proof context; lines: 4,21]
a₂' : SKI [scope: theorem proof context; lines: 23,24]
a₃ : SKI [scope: theorem proof context; lines: 13]
b : SKI [scope: theorem proof context; lines: 53,56,64]
b' : SKI [scope: theorem proof context; lines: 8,9,19,24,28,58]
b₃ : SKI [scope: theorem proof context; lines: 13]
c : SKI [scope: theorem proof context; lines: 26,36,42,53,64]
c' : SKI [scope: theorem proof context; lines: 28,47,58]
d : SKI [scope: theorem proof context; lines: 56]
h : a ⭢ₚ a' ∧ b ⭢ₚ b' ∧ d = S ⬝ a' ⬝ b' [scope: theorem proof context; lines: 57,61,62]
h : a ⭢ₚ a'' ∧ c ⭢ₚ c' ∧ a' = S ⬝ a'' ⬝ c' [scope: theorem proof context; lines: 27]
h' : a₁ ⭢ₚ a₁' ∧ a' = K ⬝ a₁' [scope: theorem proof context; lines: 45,47]
ha : (K ⬝ a₁) ⭢ₚ a' [scope: theorem proof context; lines: 44]
ha : a' ⭢ₚ a₃ ∧ a'' ⭢ₚ a₃ [scope: theorem proof context; lines: 15,16]
ha : a₁ ⭢ₚ a₁' [scope: theorem proof context; lines: 38]
ha' : (K ⬝ a₂) ⭢ₚ a' [scope: theorem proof context; lines: 21]
ha' : (S ⬝ a ⬝ c) ⭢ₚ a' [scope: theorem proof context; lines: 26]
ha' : I ⭢ₚ a' [scope: theorem proof context; lines: 18]
ha' : a ⭢ₚ a' [scope: theorem proof context; lines: 9,11]
ha'' : a ⭢ₚ a'' [scope: theorem proof context; lines: 11]
ha₂' : a₂ ⭢ₚ a₂' ∧ a' = K ⬝ a₂' [scope: theorem proof context; lines: 22,24]
hb : b' ⭢ₚ b₃ ∧ b'' ⭢ₚ b₃ [scope: theorem proof context; lines: 15,16]
hb' : b ⭢ₚ b' [scope: theorem proof context; lines: 9,12]
hb'' : b ⭢ₚ b'' [scope: theorem proof context; lines: 12]
hc : I ⭢ₚ c [scope: theorem proof context; lines: 36]
hc : c ⭢ₚ c' [scope: theorem proof context; lines: 61,62]
hd : (S ⬝ a ⬝ b) ⭢ₚ d [scope: theorem proof context; lines: 56]
h₁ : a ⭢ₚ a₁ [scope: theorem proof context; lines: 3]
h₂ : (I ⬝ a₁) ⭢ₚ a₂ [scope: theorem proof context; lines: 33]
h₂ : (K ⬝ a₁ ⬝ c) ⭢ₚ a₂ [scope: theorem proof context; lines: 41]
h₂ : (S ⬝ a ⬝ b ⬝ c) ⭢ₚ a₂ [scope: theorem proof context; lines: 51]
h₂ : (a ⬝ b) ⭢ₚ a₂ [scope: theorem proof context; lines: 6]
h₂ : a ⭢ₚ a₂ [scope: theorem proof context; lines: 4]
parallelReduction_diamond : Diamond ParallelReduction [scope: theorem proof context; lines: 11,12]

## Earlier declarations from this file (ranked) (683 chars, 139 words)
Earlier declarations from this file (ranked)
line 129 [decl:Cslib.SKI.Sab_irreducible · theorem] Cslib.SKI.Sab_irreducible : ∀ (a b c : SKI), (S ⬝ a ⬝ b) ⭢ₚ c → ∃ a' b', a ⭢ₚ a' ∧ b ⭢ₚ b' ∧ c = S ⬝ a' ⬝ b'
line 123 [decl:Cslib.SKI.Sa_irreducible · theorem] Cslib.SKI.Sa_irreducible : ∀ (a c : SKI), (S ⬝ a) ⭢ₚ c → ∃ a', a ⭢ₚ a' ∧ c = S ⬝ a'
line 119 [decl:Cslib.SKI.S_irreducible · theorem] Cslib.SKI.S_irreducible : ∀ (a : SKI), S ⭢ₚ a → a = S
line 114 [decl:Cslib.SKI.Ka_irreducible · theorem] Cslib.SKI.Ka_irreducible : ∀ (a c : SKI), (K ⬝ a) ⭢ₚ c → ∃ a', a ⭢ₚ a' ∧ c = K ⬝ a'
line 110 [decl:Cslib.SKI.K_irreducible · theorem] Cslib.SKI.K_irreducible : ∀ (a : SKI), K ⭢ₚ a → a = K

