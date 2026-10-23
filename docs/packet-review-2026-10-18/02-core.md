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

## Task (363 chars, 63 words)
Theorem: Core.InitsUpdatesComm
Original proof: node n1.
Statement:
```lean
theorem InitsUpdatesComm
  {P : PureExpr} {σ σ' σ'' : SemanticStore P}
  {ks ks' : List P.Ident} {vs vs' : List P.Expr} :
  UpdateStates σ ks vs σ' →
  InitStates σ' ks' vs' σ'' →
  ∃ σ₁,
    σ₁ = (updatedStates σ ks' vs') ∧
    InitStates σ ks' vs' σ₁ ∧
    UpdateStates σ₁ ks vs σ''
```

## Scoring (855 chars, 144 words)
Score: the mean of three percentages: token reduction, heartbeat reduction and compatibility.
Token reduction: percent fewer tokens than the reference proof (224 tokens).
Heartbeat reduction: percent fewer heartbeats than the reference proof (4251 heartbeats).
Compatibility: percent of the listed versions on which the proof compiles.
A proof that does not compile scores zero.
Rates: 1 token = 0.149 points; 100 heartbeats = 0.784 points; 1 version = 11.11 points.
Token count: proof text after `:=`, without comments and attributes.
Each identifier or number counts 1 token, whatever its length.
Each other nonspace character counts 1 token, except these groups, which count 1 token each: `:= != && -. -> ← .. ... :: :> <;> ;; == || => <= >= ⁻¹ ?_`.
Spaces and line breaks count 0; a tab counts 1.
Examples: `exact foo` = 2 tokens; `⟨a, b⟩` = 5 tokens.

## Pinned environment (890 chars, 64 words)
Pinned environment
Source: strata:Strata/Languages/Core/StatementSemanticsProps.lean:950-1004
Lean toolchain and source revisions: Lean v4.29.1 / source revision 384e22374e0872095ad9c6f74c5998c09cfd93a9; Lean v4.27.0 / source revision 4348c65a93a3b57b1a4541991ed2d2fcdd9fa35d; Lean v4.26.0 / source revision 451e5f047bafa010d178856db76c00029bfa4d7f
Available imports: import all Strata.DL.Imperative.CmdSemantics, import all Strata.DL.Imperative.CmdSemanticsProps, import all Strata.DL.Imperative.StmtSemantics, import all Strata.DL.Imperative.StmtSemanticsProps, import all Strata.DL.Imperative.HasVars, import all Strata.DL.Util.Nodup, import all Strata.DL.Util.ListUtils, import all Strata.Languages.Core.Statement, import all Strata.Languages.Core.StatementSemantics, import all Strata.DL.Imperative.Cmd, import all Strata.DL.Imperative.Stmt, import Std.Tactic.BVDecide.Normalize.BitVec

## Scope at the theorem (namespace, open, variable, universe in effect before the statement) (120 chars, 17 words)
Scope at the theorem (namespace, open, variable, universe in effect before the statement)
namespace Core
open Imperative

## Original proof and step prices (224 tokens) (3008 chars, 477 words)
Original proof and step prices (224 tokens)
```lean
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
  exists (updatedStates σ ks' vs')
  have Hk : (isDefined σ' ks) := UpdateStatesDefined Hup
  have Hlen1 := InitStatesLength Hinit
  have Hlen2 := UpdateStatesLength Hup
  induction Hup generalizing σ''
  case update_none =>
    simp_all
    apply And.intro
    refine updatedStatesInit Hlen1 ?_ ?_
    exact InitStatesNotDefined Hinit
    exact InitStatesNodup Hinit
    simp [InitStatesUpdated Hinit]
    constructor
  case update_some σ x v σ₀ xs vs σ₁ Hup Hups ih =>
    refine ⟨rfl, ?_, ?_⟩
    . apply updatedStatesInit Hlen1
      apply UpdateStateNotDefMonotone' ?_ Hup
      apply UpdateStatesNotDefMonotone' ?_ Hups
      exact InitStatesNotDefined Hinit
      exact InitStatesNodup Hinit
    . apply UpdateStates.update_some (σ':=updatedStates σ₀ ks' vs')
      . simp [UpdateStateUpdated Hup, updatedStates]
        rw [← updatedStateComm']
        . have Hdef := UpdateStateDefined' Hup
          simp [isDefined, Option.isSome] at Hdef
          split at Hdef <;> simp_all
          next val heq =>
          apply updatedStateUpdate (v':=val)
          apply InitStatesSomeMonotone heq
          apply updatedStatesInit
          . simp_all
          . apply UpdateStateNotDefMonotone' ?_ Hup
            apply UpdateStatesNotDefMonotone' ?_ Hups
            apply InitStatesNotDefined Hinit
          . exact InitStatesNodup Hinit
        . rw [List.unzip_zip] <;> simp_all
          have Hnd := InitStatesNotDefined Hinit
          simp [isNotDefined, isDefined] at *
          apply Not.intro
          intros Hin
          specialize Hnd _ Hin
          simp_all
      . apply (ih Hinit ?_ ?_).2.2
        . simp [isDefined] at * <;> simp_all
        . simp_all
```
| step | lines | tokens | self_hb | incl_hb | pts_if_gone | text |
|---|---|---|---|---|---|---|
| s1 | 10-10 | 3 | 0 | 0 | +0.45 | `intros Hup Hinit` |
| s2 | 11-11 | 7 | 593 | 593 | +5.69 | `exists (updatedStates σ ks' vs')` |
| s3 | 12-12 | 11 | 5 | 8 | +1.70 | `have Hk : (isDefined σ' ks) := UpdateSta` |
| s4 | 13-13 | 5 | 3 | 3 | +0.77 | `have Hlen1 := InitStatesLength Hinit` |
| s5 | 14-14 | 5 | 3 | 3 | +0.77 | `have Hlen2 := UpdateStatesLength Hup` |
| s6 | 15-15 | 4 | 11 | 11 | +0.68 | `induction Hup generalizing σ''` |
| s7 | 16-23 | 23 | 3 | 66 | +3.94 | `case update_none =>` |
| s8 | 24-55 | 165 | 2 | 3501 | +52.01 | `case update_some σ x v σ₀ xs vs σ₁ Hup H` |
| total | - | 224 | - | 4251 | - | versions 3/3 · score 33.33 |
self_hb: heartbeats of the step alone.
incl_hb: heartbeats of the step with its nested steps.
pts_if_gone: upper bound on the points gained by removing the step.
versions: listed versions on which the proof compiles.

## Original proof heartbeats by line (867 chars, 194 words)
Original proof heartbeats by line
line 11 · 593 self hb · 7 tokens · exists (updatedStates σ ks' vs')
line 17 · 46 self hb · 1 tokens · simp_all
line 25 · 33 self hb · 8 tokens · refine ⟨rfl, ?_, ?_⟩
line 33 · 46 self hb · 5 tokens · rw [← updatedStateComm']
line 35 · 72 self hb · 8 tokens · simp [isDefined, Option.isSome] at Hdef
line 36 · 1036 self hb · 5 tokens · split at Hdef <;> simp_all
line 37 · 91 self hb · 4 tokens · next val heq =>
line 46 · 1035 self hb · 7 tokens · . rw [List.unzip_zip] <;> simp_all
line 48 · 224 self hb · 8 tokens · simp [isNotDefined, isDefined] at *
line 52 · 150 self hb · 1 tokens · simp_all
line 54 · 481 self hb · 9 tokens · . simp [isDefined] at * <;> simp_all
line 55 · 277 self hb · 2 tokens · . simp_all
Measured 4251 heartbeats; 4185 are attributed to lines (top 12 by self hb shown); 66 (1.6%) are not tied to any line.

## Goals before original steps (3358 chars, 663 words)
Goals before original steps
before s1: P : PureExpr
σ σ' σ'' : SemanticStore P
ks ks' : List P.Ident
vs vs' : List P.Expr
⊢ UpdateStates σ ks vs σ' →
    InitStates σ' ks' vs' σ'' → ∃ σ₁, σ₁ = updatedStates σ ks' vs' ∧ InitStates σ ks' vs' σ₁ ∧ UpdateStates σ₁ ks vs σ''
before s2: P : PureExpr
σ σ' σ'' : SemanticStore P
ks ks' : List P.Ident
vs vs' : List P.Expr
Hup : UpdateStates σ ks vs σ'
Hinit : InitStates σ' ks' vs' σ''
⊢ ∃ σ₁, σ₁ = updatedStates σ ks' vs' ∧ InitStates σ ks' vs' σ₁ ∧ UpdateStates σ₁ ks vs σ''
before s3: P : PureExpr
σ σ' σ'' : SemanticStore P
ks ks' : List P.Ident
vs vs' : List P.Expr
Hup : UpdateStates σ ks vs σ'
Hinit : InitStates σ' ks' vs' σ''
⊢ updatedStates σ ks' vs' = updatedStates σ ks' vs' ∧
    InitStates σ ks' vs' (updatedStates σ ks' vs') ∧ UpdateStates (updatedStates σ ks' vs') ks vs σ''
before s4: P : PureExpr
σ σ' σ'' : SemanticStore P
ks ks' : List P.Ident
vs vs' : List P.Expr
Hup : UpdateStates σ ks vs σ'
Hinit : InitStates σ' ks' vs' σ''
Hk : isDefined σ' ks
⊢ updatedStates σ ks' vs' = updatedStates σ ks' vs' ∧
    InitStates σ ks' vs' (updatedStates σ ks' vs') ∧ UpdateStates (updatedStates σ ks' vs') ks vs σ''
before s5: P : PureExpr
σ σ' σ'' : SemanticStore P
ks ks' : List P.Ident
vs vs' : List P.Expr
Hup : UpdateStates σ ks vs σ'
Hinit : InitStates σ' ks' vs' σ''
Hk : isDefined σ' ks
Hlen1 : ks'.length = vs'.length
⊢ updatedStates σ ks' vs' = updatedStates σ ks' vs' ∧
    InitStates σ ks' vs' (updatedStates σ ks' vs') ∧ UpdateStates (updatedStates σ ks' vs') ks vs σ''
before s6: P : PureExpr
σ σ' σ'' : SemanticStore P
ks ks' : List P.Ident
vs vs' : List P.Expr
Hup : UpdateStates σ ks vs σ'
Hinit : InitStates σ' ks' vs' σ''
Hk : isDefined σ' ks
Hlen1 : ks'.length = vs'.length
Hlen2 : ks.length = vs.length
⊢ updatedStates σ ks' vs' = updatedStates σ ks' vs' ∧
    InitStates σ ks' vs' (updatedStates σ ks' vs') ∧ UpdateStates (updatedStates σ ks' vs') ks vs σ''
before s7: case update_none
P : PureExpr
σ σ' : SemanticStore P
ks ks' : List P.Ident
vs vs' : List P.Expr
Hlen1 : ks'.length = vs'.length
σ✝ σ'' : SemanticStore P
Hinit : InitStates σ✝ ks' vs' σ''
Hk : isDefined σ✝ []
Hlen2 : [].length = [].length
⊢ updatedStates σ✝ ks' vs' = updatedStates σ✝ ks' vs' ∧
    InitStates σ✝ ks' vs' (updatedStates σ✝ ks' vs') ∧ UpdateStates (updatedStates σ✝ ks' vs') [] [] σ''
case update_some
P : PureExpr
σ σ' : SemanticStore P
ks ks' : List P.Ident
vs vs' : List P.Expr
Hlen1 : ks'.length = vs'.length
σ✝ : SemanticStore P
x✝ : P.Ident
v✝ : P.Expr
σ'✝ : SemanticStore P
xs✝ : List P.Ident
vs✝ : List P.Expr
σ''✝ : SemanticStore P
a✝¹ : UpdateState P σ✝ x✝ v✝ σ'✝
a✝ : UpdateS…
before s8: case update_some
P : PureExpr
σ σ' : SemanticStore P
ks ks' : List P.Ident
vs vs' : List P.Expr
Hlen1 : ks'.length = vs'.length
σ✝ : SemanticStore P
x✝ : P.Ident
v✝ : P.Expr
σ'✝ : SemanticStore P
xs✝ : List P.Ident
vs✝ : List P.Expr
σ''✝ : SemanticStore P
a✝¹ : UpdateState P σ✝ x✝ v✝ σ'✝
a✝ : UpdateStates σ'✝ xs✝ vs✝ σ''✝
a_ih✝ :
  ∀ {σ'' : SemanticStore P},
    InitStates σ''✝ ks' vs' σ'' →
      isDefined σ''✝ xs✝ →
        xs✝.length = vs✝.length →
          updatedStates σ'✝ ks' vs' = updatedStates σ'✝ ks' vs' ∧
            InitStates σ'✝ ks' vs' (updatedStates σ'✝ ks' vs') ∧ UpdateStates (updatedStates σ'✝ ks' vs') xs✝ vs✝ σ''
σ'' : SemanticStore P
Hinit : InitStates σ''✝ ks' vs' σ''
Hk…

## Imported declarations (ranked) (6715 chars, 1125 words)
Imported declarations (ranked)
1. decl:Imperative.UpdateStateDef · Strata.DL.Imperative.CmdSemanticsProps · Imperative.UpdateStateDef : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {e : P.Expr} {v : P.Ident}, UpdateState P σ v e σ' → isDefined σ [v] ∧ isDefined σ' [v]
2. decl:Imperative.UpdateStateDefMonotone · Strata.DL.Imperative.CmdSemanticsProps · Imperative.UpdateStateDefMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {e : P.Expr} {v : P.Ident}, isDefined σ vs → UpdateState P σ v e σ' → isDefined σ' vs
3. decl:Imperative.isNotDefinedCons' · Strata.DL.Imperative.CmdSemanticsProps · Imperative.isNotDefinedCons' : ∀ {P : PureExpr} {σ : SemanticStore P} {h : P.Ident} {t : List P.Ident}, isNotDefined σ (h :: t) → isNotDefined σ [h] ∧ isNotDefined σ t
4. decl:Imperative.isDefinedCons' · Strata.DL.Imperative.CmdSemanticsProps · Imperative.isDefinedCons' : ∀ {P : PureExpr} {σ : SemanticStore P} {h : P.Ident} {t : List P.Ident}, isDefined σ (h :: t) → isDefined σ [h] ∧ isDefined σ t
5. decl:Imperative.isNotDefinedCons · Strata.DL.Imperative.CmdSemanticsProps · Imperative.isNotDefinedCons : ∀ {P : PureExpr} {σ : SemanticStore P} {v : P.Ident} {vs2 : List P.Ident}, isNotDefined σ [v] → isNotDefined σ vs2 → isNotDefined σ (v :: vs2)
6. decl:Imperative.isDefinedCons · Strata.DL.Imperative.CmdSemanticsProps · Imperative.isDefinedCons : ∀ {P : PureExpr} {σ : SemanticStore P} {v : P.Ident} {vs2 : List P.Ident}, isDefined σ [v] → isDefined σ vs2 → isDefined σ (v :: vs2)
7. decl:Imperative.UpdateStateUniqueResult · Strata.DL.Imperative.CmdSemanticsProps · Imperative.UpdateStateUniqueResult : ∀ {P : PureExpr} {σ σ' σ'' : SemanticStore P} {e : P.Expr} {v : P.Ident}, UpdateState P σ v e σ' → UpdateState P σ v e σ'' → σ' = σ''
8. decl:Imperative.UpdateState_preserves_none · Strata.DL.Imperative.CmdSemanticsProps · Imperative.UpdateState_preserves_none : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {x : P.Ident} {v : P.Expr} {y : P.Ident}, UpdateState P σ x v σ' → σ y = none → σ' y = none
9. decl:Imperative.isNotDefinedApp' · Strata.DL.Imperative.CmdSemanticsProps · Imperative.isNotDefinedApp' : ∀ {P : PureExpr} {σ : SemanticStore P} {t1 t2 : List P.Ident}, isNotDefined σ (t1 ++ t2) → isNotDefined σ t1 ∧ isNotDefined σ t2
10. decl:Imperative.isDefinedApp' · Strata.DL.Imperative.CmdSemanticsProps · Imperative.isDefinedApp' : ∀ {P : PureExpr} {σ : SemanticStore P} {t1 t2 : List P.Ident}, isDefined σ (t1 ++ t2) → isDefined σ t1 ∧ isDefined σ t2
11. decl:Imperative.UpdateStateComm · Strata.DL.Imperative.CmdSemanticsProps · Imperative.UpdateStateComm : ∀ {P : PureExpr} {x1 x2 : P.Ident} {σ σ' σ'' σ1 σ2 : SemanticStore P} {v1 v2 : P.Expr} [DecidableEq P.Ident], ¬x1 = x2 → UpdateState P σ x1 v1 σ1 → UpdateState P σ1 x2 v2 σ' → UpdateState P σ x2 v2 σ2 → UpdateState P σ2 x1 v1 σ'' → σ' = σ''
12. decl:List.zip_eq_cons_iff · Init.Data.List.Zip · List.zip_eq_cons_iff : ∀ {α : Type u_1} {β : Type u_2} {a : α} {b : β} {l : List (α × β)} {l₁ : List α} {l₂ : List β}, l₁.zip l₂ = (a, b) :: l ↔ ∃ l₁' l₂', l₁ = a :: l₁' ∧ l₂ = b :: l₂' ∧ l = l₁'.zip l₂'
13. decl:List.of_mem_zip · Init.Data.List.Zip · List.of_mem_zip : ∀ {α : Type u_1} {β : Type u_2} {a : α} {b : β} {l₁ : List α} {l₂ : List β}, (a, b) ∈ l₁.zip l₂ → a ∈ l₁ ∧ b ∈ l₂
14. decl:Imperative.isNotDefinedApp · Strata.DL.Imperative.CmdSemanticsProps · Imperative.isNotDefinedApp : ∀ {P : PureExpr} {σ : SemanticStore P} {vs1 vs2 : List P.Ident}, isNotDefined σ vs1 → isNotDefined σ vs2 → isNotDefined σ (vs1 ++ vs2)
15. decl:Imperative.isDefinedApp · Strata.DL.Imperative.CmdSemanticsProps · Imperative.isDefinedApp : ∀ {P : PureExpr} {σ : SemanticStore P} {vs1 vs2 : List P.Ident}, isDefined σ vs1 → isDefined σ vs2 → isDefined σ (vs1 ++ vs2)
16. decl:List.unzip_nil · Init.Data.List.Basic · List.unzip_nil : ∀ {α : Type u} {β : Type v}, [].unzip = ([], [])
17. decl:List.zip_cons_cons · Init.Data.List.Basic · List.zip_cons_cons : ∀ {α : Type u_1} {a : α} {as : List α} {α_1 : Type u_2} {b : α_1} {bs : List α_1}, (a :: as).zip (b :: bs) = (a, b) :: as.zip bs
18. decl:List.exists_mem_nil · Init.Data.List.Lemmas · List.exists_mem_nil : ∀ {α : Type u_1} (p : α → Prop), ¬∃ x x_1, p x
19. decl:Imperative.InitStateDefCons · Strata.DL.Imperative.CmdSemanticsProps · Imperative.InitStateDefCons : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {e : P.Expr} {v : P.Ident}, isDefined σ vs → InitState P σ v e σ' → isDefined σ' (v :: vs)
20. decl:List.nodup_cons · Init.Data.List.Pairwise · List.nodup_cons : ∀ {α : Type u_1} {a : α} {l : List α}, (a :: l).Nodup ↔ ¬a ∈ l ∧ l.Nodup
21. decl:Imperative.InitStateDefMonotone · Strata.DL.Imperative.CmdSemanticsProps · Imperative.InitStateDefMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {e : P.Expr} {v : P.Ident}, isDefined σ vs → InitState P σ v e σ' → isDefined σ' vs
22. decl:List.zip_nil_left · Init.Data.List.Basic · List.zip_nil_left : ∀ {α : Type u} {β : Type v} {l : List β}, [].zip l = []
23. decl:List.zip_nil_right · Init.Data.List.Basic · List.zip_nil_right : ∀ {α : Type u} {β : Type v} {l : List α}, l.zip [] = []
24. decl:List.unzip_zip_left · Init.Data.List.Zip · List.unzip_zip_left : ∀ {α : Type u_1} {β : Type u_2} {l₁ : List α} {l₂ : List β}, l₁.length ≤ l₂.length → (l₁.zip l₂).unzip.fst = l₁
25. decl:List.eq_append_cons_of_mem · Init.Data.List.Lemmas · List.eq_append_cons_of_mem : ∀ {α : Type u_1} {a : α} {xs : List α}, a ∈ xs → ∃ as bs, xs = as ++ a :: bs ∧ ¬a ∈ as
26. decl:Imperative.storeAgreement_supplies_mono_premise · Strata.DL.Imperative.CmdSemantics · Imperative.storeAgreement_supplies_mono_premise : ∀ {P : PureExpr} (σ_struct σ_cfg : SemanticStore P), StoreAgreement σ_struct σ_cfg → ∀ (x : P.Ident) (w : P.Expr), σ_struct x = some w → σ_cfg x = some w
27. decl:List.eq_of_mem_singleton · Init.Data.List.Lemmas · List.eq_of_mem_singleton : ∀ {α : Type u_1} {b a : α}, a ∈ [b] → a = b
28. decl:List.zip_eq_append_iff · Init.Data.List.Zip · List.zip_eq_append_iff : ∀ {α : Type u_1} {β : Type u_2} {l₁' l₂' : List (α × β)} {l₁ : List α} {l₂ : List β}, l₁.zip l₂ = l₁' ++ l₂' ↔ ∃ ws xs ys zs, ws.length = ys.length ∧ l₁ = ws ++ xs ∧ l₂ = ys ++ zs ∧ l₁' = ws.zip ys ∧ l₂' = xs.zip zs
29. decl:List.mem_singleton_self · Init.Data.List.Lemmas · List.mem_singleton_self : ∀ {α : Type u_1} (a : α), a ∈ [a]
30. decl:List.length_eq_one_iff · Init.Data.List.Lemmas · List.length_eq_one_iff : ∀ {α : Type u_1} {l : List α}, l.length = 1 ↔ ∃ a, l = [a]
31. decl:Imperative.InitStateUniqueResult · Strata.DL.Imperative.CmdSemanticsProps · Imperative.InitStateUniqueResult : ∀ {P : PureExpr} {σ σ' σ'' : SemanticStore P} {e : P.Expr} {v : P.Ident}, InitState P σ v e σ' → InitState P σ v e σ'' → σ' = σ''

## Definitions of project types and predicates in the statement (1678 chars, 283 words)
Definitions of project types and predicates in the statement
decl:Imperative.PureExpr [structure] Imperative.PureExpr : Type 1
  | Imperative.PureExpr.mk : (Ident : Type) →
  DecidableEq Ident →
    (Expr : Type) →
      Type → Type → Type → Type → (Factory : Type) → (Factory → (Ident → Option Expr) → Expr → Option Expr) → PureExpr
decl:Imperative.SemanticStore [def] Imperative.SemanticStore : PureExpr → Type
  := fun P => P.Ident → Option P.Expr
decl:Core.UpdateStates [inductive] Core.UpdateStates : {P : PureExpr} → SemanticStore P → List P.Ident → List P.Expr → SemanticStore P → Prop
  | Core.UpdateStates.update_none : ∀ {P : PureExpr} {σ : SemanticStore P}, UpdateStates σ [] [] σ
  | Core.UpdateStates.update_some : ∀ {P : PureExpr} {σ : SemanticStore P} {x : P.Ident} {v : P.Expr} {σ' : SemanticStore P} {xs : List P.Ident}
  {vs : List P.Expr} {σ'' : SemanticStore P},
  UpdateState P σ x v σ' → UpdateStates σ' xs vs σ'' → UpdateStates σ (x :: xs) (v :: vs) σ''
decl:Core.InitStates [inductive] Core.InitStates : {P : PureExpr} → SemanticStore P → List P.Ident → List P.Expr → SemanticStore P → Prop
  | Core.InitStates.init_none : ∀ {P : PureExpr} {σ : SemanticStore P}, InitStates σ [] [] σ
  | Core.InitStates.init_some : ∀ {P : PureExpr} {σ : SemanticStore P} {x : P.Ident} {v : P.Expr} {σ' : SemanticStore P} {xs : List P.Ident}
  {vs : List P.Expr} {σ'' : SemanticStore P},
  InitState P σ x v σ' → InitStates σ' xs vs σ'' → InitStates σ (x :: xs) (v :: vs) σ''
decl:Core.updatedStates [def] Core.updatedStates : {P : PureExpr} → SemanticStore P → List P.Ident → List P.Expr → SemanticStore P
  := fun {P} σ idents vals => updatedStates' σ (idents.zip vals)

## Source-named declarations (2835 chars, 354 words)
Source-named declarations
Qualified name [kind] S:statement lines P:proof lines U:lines whose position could not be placed (no top-level `:=` found); use `decl:<name>` as its source handle.
decl:And.intro [constructor] S:- P:18
decl:Core.InitStates [inductive] S:5,8 P:-
decl:Core.InitStatesLength [theorem] S:- P:13
decl:Core.InitStatesNodup [theorem] S:- P:21,30,45
decl:Core.InitStatesNotDefined [theorem] S:- P:20,29,44,47
decl:Core.InitStatesSomeMonotone [theorem] S:- P:39
decl:Core.InitStatesUpdated [theorem] S:- P:22
decl:Core.UpdateStateDefined' [theorem] S:- P:34
decl:Core.UpdateStateNotDefMonotone' [theorem] S:- P:27,42
decl:Core.UpdateStateUpdated [theorem] S:- P:32
decl:Core.UpdateStates [inductive] S:4,9 P:-
decl:Core.UpdateStates.update_some [constructor] S:- P:31
decl:Core.UpdateStatesDefined [theorem] S:- P:12
decl:Core.UpdateStatesLength [theorem] S:- P:14
decl:Core.UpdateStatesNotDefMonotone' [theorem] S:- P:28,43
decl:Core.updatedStateComm' [theorem] S:- P:33,33
decl:Core.updatedStateUpdate [theorem] S:- P:38
decl:Core.updatedStates [def] S:7 P:11,31,32,32
decl:Core.updatedStatesInit [theorem] S:- P:19,26,40
decl:Imperative.PureExpr [inductive] S:2,2 P:-
decl:Imperative.PureExpr.Expr [def] S:3,3 P:-
decl:Imperative.PureExpr.Ident [def] S:3,3 P:-
decl:Imperative.SemanticStore [def] S:2,2,2 P:-
decl:Imperative.isDefined [def] S:- P:12,35,35,48,48,54,54
decl:Imperative.isNotDefined [def] S:- P:48,48
decl:List [inductive] S:3,3,3,3 P:-
decl:List.unzip_zip [theorem] S:- P:46,46
decl:Not.intro [theorem] S:- P:49
decl:Option.isSome [def] S:- P:35,35
decl:rfl [def] S:- P:25,25

Signature preview: 5 shown of 30 distinct source names; 0 unavailable.
[decl:Core.InitStatesLength · theorem · this file] Core.InitStatesLength : ∀ {P : PureExpr} {σ : SemanticStore P} {ks : List P.Ident} {vs : List P.Expr} {σ' : SemanticStore P}, InitStates σ ks vs σ' → ks.length = vs.length
[decl:Core.InitStatesNodup · theorem · this file] Core.InitStatesNodup : ∀ {P : PureExpr} {σ : SemanticStore P} {hs : List P.Ident} {vs : List P.Expr} {σ' : SemanticStore P}, InitStates σ hs vs σ' → hs.Nodup
[decl:Core.InitStatesNotDefined · theorem · this file] Core.InitStatesNotDefined : ∀ {P : PureExpr} {σ : SemanticStore P} {hs : List P.Ident} {vs : List P.Expr} {σ' : SemanticStore P}, InitStates σ hs vs σ' → isNotDefined σ hs
[decl:Core.InitStatesSomeMonotone · theorem · this file] Core.InitStatesSomeMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {k' : P.Ident} {v' : P.Expr} {ks' : List P.Ident} {vs' : List P.Expr}, σ k' = some v' → InitStates σ ks' vs' σ' → σ' k' = some v'
[decl:Core.InitStatesUpdated · theorem · this file] Core.InitStatesUpdated : ∀ {P : PureExpr} {σ' : SemanticStore P} {ks : List P.Ident} {vs : List P.Expr} {σ'' : SemanticStore P}, InitStates σ' ks vs σ'' → σ'' = updatedStates σ' ks vs

## Local variables (2049 chars, 347 words)
Local variables
Local variable name : type; lines are where the Lean local context exposes the variable.
Hdef : (match σ x with | some val => true | none => false) = true [scope: theorem proof context; lines: 36]
Hdef : isDefined σ [x] [scope: theorem proof context; lines: 35]
Hin : x ∈ ks' [scope: theorem proof context; lines: 51]
Hinit : InitStates σ' ks' vs' σ'' [scope: theorem proof context; lines: 13]
Hinit : InitStates σ₁ ks' vs' σ'' [scope: theorem proof context; lines: 29,30,44,45,47,53]
Hinit : InitStates σ✝ ks' vs' σ'' [scope: theorem proof context; lines: 20,21,22]
Hlen1 : ks'.length = vs'.length [scope: theorem proof context; lines: 19,26]
Hnd : ∀ (v : P.Ident), v ∈ ks' → σ₁ v = none [scope: theorem proof context; lines: 51]
Hup : UpdateState P σ x v σ₀ [scope: theorem proof context; lines: 27,32,34,42]
Hup : UpdateStates σ ks vs σ' [scope: theorem proof context; lines: 12,14,15]
Hups : UpdateStates σ₀ xs vs σ₁ [scope: theorem proof context; lines: 28,43]
P : PureExpr [scope: theorem proof context; lines: 2,3]
heq : σ x = some val [scope: theorem proof context; lines: 39]
ih : ∀ {σ'' : SemanticStore P}, InitStates σ₁ ks' vs' σ'' → isDefined σ₁ xs → xs.length = vs.length → updatedStates σ₀ ks' vs' = updatedStates σ₀ ks' vs' ∧ InitStates σ₀ ks' vs' (updatedStates σ₀ ks' vs') ∧ UpdateStates (updatedStates σ₀ ks' vs') xs vs σ'' [scope: theorem proof context; lines: 53]
ks : List P.Ident [scope: theorem proof context; lines: 4,9,12]
ks' : List P.Ident [scope: theorem proof context; lines: 5,7,8,11,31]
val : P.Expr [scope: theorem proof context; lines: 38]
vs : List P.Expr [scope: theorem proof context; lines: 4,9]
vs' : List P.Expr [scope: theorem proof context; lines: 5,7,8,11,31]
σ : SemanticStore P [scope: theorem proof context; lines: 4,7,8,11]
σ' : SemanticStore P [scope: theorem proof context; lines: 4,5,12]
σ'' : SemanticStore P [scope: theorem proof context; lines: 5,9,15]
σ₀ : SemanticStore P [scope: theorem proof context; lines: 31]
σ₁ : SemanticStore P [scope: theorem proof context; lines: 7,8,9]

## Earlier declarations from this file (ranked) (11847 chars, 1914 words)
Earlier declarations from this file (ranked)
line 809 [decl:Core.updatedStateComm' · theorem · mentions updatedStates', updatedState, unzip · equation overlap] Core.updatedStateComm' : ∀ {P : PureExpr} {σ : SemanticStore P} {k : P.Ident} {v : P.Expr} {kvs : List (P.Ident × P.Expr)}, ¬k ∈ kvs.unzip.fst → updatedState (updatedStates' σ kvs) k v = updatedStates' (updatedState σ k v) kvs
line 553 [decl:Core.InitStatesApp' · theorem · mentions updatedStates, And, Exists · concludes Exists] Core.InitStatesApp' : ∀ {P : PureExpr} {σ : SemanticStore P} {k1 k2 : List P.Ident} {v1 v2 : List P.Expr} {σ' : SemanticStore P}, InitStates σ (k1 ++ k2) (v1 ++ v2) σ' → k1.length = v1.length → k2.length = v2.length → ∃ σ₁, σ₁ = updatedStat…
line 375 [decl:Core.updatedStatesInit · theorem · mentions updatedStates, isNotDefined, length · used by nearby declarations] Core.updatedStatesInit : ∀ {P : PureExpr} {σ : SemanticStore P} {hs : List P.Ident} {vs : List P.Expr}, hs.length = vs.length → isNotDefined σ hs → hs.Nodup → InitStates σ hs vs (updatedStates σ hs vs)
line 342 [decl:Core.updatedStatesUpdate · theorem · mentions updatedStates, UpdateStates, isDefined] Core.updatedStatesUpdate : ∀ {P : PureExpr} {σ : SemanticStore P} {hs : List P.Ident} {vs : List P.Expr}, hs.length = vs.length → isDefined σ hs → UpdateStates σ hs vs (updatedStates σ hs vs)
line 540 [decl:Core.UpdateStatesUpdated · theorem · mentions updatedStates, UpdateStates] Core.UpdateStatesUpdated : ∀ {P : PureExpr} {σ' : SemanticStore P} {ks : List P.Ident} {vs : List P.Expr} {σ'' : SemanticStore P}, UpdateStates σ' ks vs σ'' → σ'' = updatedStates σ' ks vs
line 274 [decl:Core.updatedStateUpdate · theorem · mentions updatedState, UpdateState, some · used by nearby declarations] Core.updatedStateUpdate : ∀ {P : PureExpr} {σ : SemanticStore P} {h : P.Ident} {v v' : P.Expr}, σ h = some v' → UpdateState P σ h v (updatedState σ h v)
line 308 [decl:Core.updatedStatesDefMonotone · theorem · mentions updatedStates', isDefined, Prod · used by nearby declarations] Core.updatedStatesDefMonotone : ∀ {P : PureExpr} {σ : SemanticStore P} {vs : List P.Ident} {ves : List (P.Ident × P.Expr)}, isDefined σ vs → isDefined (updatedStates' σ ves) vs
line 824 [decl:Core.updatedStatesComm · theorem · mentions updatedStates', unzip, fst · equation overlap] Core.updatedStatesComm : ∀ {P : PureExpr} {σ : SemanticStore P} {kvs kvs' : List (P.Ident × P.Expr)}, kvs.unzip.fst.Disjoint kvs'.unzip.fst → updatedStates' (updatedStates' σ kvs) kvs' = updatedStates' (updatedStates' σ kvs') kvs
line 323 [decl:Core.updatedStatesDefined · theorem · mentions updatedStates, isDefined, length] Core.updatedStatesDefined : ∀ {P : PureExpr} {σ : SemanticStore P} {ks : List P.Ident} {vs : List P.Expr}, ks.length = vs.length → isDefined (updatedStates σ ks vs) ks
line 528 [decl:Core.UpdateStateUpdated · theorem · mentions updatedState, UpdateState · used by nearby declarations] Core.UpdateStateUpdated : ∀ {P : PureExpr} {σ' : SemanticStore P} {k : P.Ident} {v : P.Expr} {σ'' : SemanticStore P}, UpdateState P σ' k v σ'' → σ'' = updatedState σ' k v
line 402 [decl:Core.updatedStates'App · theorem · mentions updatedStates', Prod · equation overlap] Core.updatedStates'App : ∀ {P : PureExpr} {σ : SemanticStore P} {a b : List (P.Ident × P.Expr)}, updatedStates' σ (a ++ b) = updatedStates' (updatedStates' σ a) b
line 868 [decl:Core.UpdateStatesSomeMonotone · theorem · mentions UpdateStates, mem, Not] Core.UpdateStatesSomeMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {k' : P.Ident} {v' : P.Expr} {ks' : List P.Ident} {vs' : List P.Expr}, ¬k' ∈ ks' → σ k' = some v' → UpdateStates σ ks' vs' σ' → σ' k' = some v'
line 291 [decl:Core.updatedStateDefMonotone · theorem · mentions updatedState, isDefined · used by nearby declarations] Core.updatedStateDefMonotone : ∀ {P : PureExpr} {σ : SemanticStore P} {vs : List P.Ident} {v' : P.Ident} {e' : P.Expr}, isDefined σ vs → isDefined (updatedState σ v' e') vs
line 231 [decl:Core.UpdateStatesDefMonotone' · theorem · mentions UpdateStates, isDefined · used by nearby declarations] Core.UpdateStatesDefMonotone' : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {es' : List P.Expr} {vs' : List P.Ident}, isDefined σ' vs → UpdateStates σ vs' es' σ' → isDefined σ vs
line 194 [decl:Core.UpdateStatesDefMonotone · theorem · mentions UpdateStates, isDefined · used by nearby declarations] Core.UpdateStatesDefMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {es' : List P.Expr} {vs' : List P.Ident}, isDefined σ vs → UpdateStates σ vs' es' σ' → isDefined σ' vs
line 283 [decl:Core.updatedStateId · theorem · mentions updatedState, some, Option · equation overlap] Core.updatedStateId : ∀ {P : PureExpr} {σ : SemanticStore P} {h : P.Ident} {v : P.Expr}, σ h = some v → updatedState σ h v = σ
line 162 [decl:Core.UpdateStateDefined' · theorem · mentions UpdateState, isDefined, cons · used by nearby declarations] Core.UpdateStateDefined' : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {e : P.Expr} {v : P.Ident}, UpdateState P σ v e σ' → isDefined σ [v]
line 153 [decl:Core.UpdateStateDefined · theorem · mentions UpdateState, isDefined, cons · used by nearby declarations] Core.UpdateStateDefined : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {e : P.Expr} {v : P.Ident}, UpdateState P σ v e σ' → isDefined σ' [v]
line 110 [decl:Core.UpdateStateNotDefMonotone' · theorem · mentions isNotDefined, UpdateState · used by nearby declarations] Core.UpdateStateNotDefMonotone' : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {e : P.Expr} {v : P.Ident}, isNotDefined σ' vs → UpdateState P σ v e σ' → isNotDefined σ vs
line 75 [decl:Core.UpdateStateNotDefMonotone · theorem · mentions isNotDefined, UpdateState · used by nearby declarations] Core.UpdateStateNotDefMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {e : P.Expr} {v : P.Ident}, isNotDefined σ vs → UpdateState P σ v e σ' → isNotDefined σ' vs
line 130 [decl:Core.UpdateStatesNotDefMonotone' · theorem · mentions isNotDefined, UpdateStates] Core.UpdateStatesNotDefMonotone' : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {es' : List P.Expr} {vs' : List P.Ident}, isNotDefined σ' vs → UpdateStates σ vs' es' σ' → isNotDefined σ vs
line 95 [decl:Core.UpdateStatesNotDefMonotone · theorem · mentions isNotDefined, UpdateStates] Core.UpdateStatesNotDefMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {es' : List P.Expr} {vs' : List P.Ident}, isNotDefined σ vs → UpdateStates σ vs' es' σ' → isNotDefined σ' vs
line 593 [decl:Core.ReadValuesAppKeys' · theorem · mentions And, Exists · concludes Exists] Core.ReadValuesAppKeys' : ∀ {P : PureExpr} {σ : SemanticStore P} {k1 k2 : List P.Ident} {vs : List P.Expr}, ReadValues σ (k1 ++ k2) vs → ∃ v1 v2, v1 ++ v2 = vs ∧ ReadValues σ k1 v1 ∧ ReadValues σ k2 v2
line 259 [decl:Core.UpdateStatesDefined' · theorem · mentions UpdateStates, isDefined] Core.UpdateStatesDefined' : ∀ {P : PureExpr} {σ : SemanticStore P} {vs : List P.Ident} {es : List P.Expr} {σ' : SemanticStore P}, UpdateStates σ vs es σ' → isDefined σ vs
line 245 [decl:Core.UpdateStatesDefined · theorem · mentions UpdateStates, isDefined] Core.UpdateStatesDefined : ∀ {P : PureExpr} {σ : SemanticStore P} {vs : List P.Ident} {es : List P.Expr} {σ' : SemanticStore P}, UpdateStates σ vs es σ' → isDefined σ' vs
line 209 [decl:Core.UpdateStateDefMonotone' · theorem · mentions UpdateState, isDefined · used by nearby declarations] Core.UpdateStateDefMonotone' : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {e : P.Expr} {v : P.Ident}, isDefined σ' vs → UpdateState P σ v e σ' → isDefined σ vs
line 172 [decl:Core.UpdateStateDefMonotone · theorem · mentions UpdateState, isDefined · used by nearby declarations] Core.UpdateStateDefMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {vs : List P.Ident} {e : P.Expr} {v : P.Ident}, isDefined σ vs → UpdateState P σ v e σ' → isDefined σ' vs
line 515 [decl:Core.InitStatesUpdated · theorem · mentions updatedStates] Core.InitStatesUpdated : ∀ {P : PureExpr} {σ' : SemanticStore P} {ks : List P.Ident} {vs : List P.Expr} {σ'' : SemanticStore P}, InitStates σ' ks vs σ'' → σ'' = updatedStates σ' ks vs
line 643 [decl:Core.UpdateStatesLength · theorem · mentions UpdateStates, length, Nat] Core.UpdateStatesLength : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {ks : List P.Ident} {vs : List P.Expr}, UpdateStates σ ks vs σ' → ks.length = vs.length
line 503 [decl:Core.InitStateUpdated · theorem · mentions updatedState · used by nearby declarations] Core.InitStateUpdated : ∀ {P : PureExpr} {σ' : SemanticStore P} {k : P.Ident} {v : P.Expr} {σ'' : SemanticStore P}, InitState P σ' k v σ'' → σ'' = updatedState σ' k v
line 796 [decl:Core.updatedStateComm · theorem · mentions updatedState · equation overlap] Core.updatedStateComm : ∀ {P : PureExpr} {σ : SemanticStore P} {k k' : P.Ident} {v v' : P.Expr}, k ≠ k' → updatedState (updatedState σ k v) k' v' = updatedState (updatedState σ k' v') k v
line 428 [decl:Core.InitStatesNotDefined · theorem · mentions isNotDefined · used by nearby declarations] Core.InitStatesNotDefined : ∀ {P : PureExpr} {σ : SemanticStore P} {hs : List P.Ident} {vs : List P.Expr} {σ' : SemanticStore P}, InitStates σ hs vs σ' → isNotDefined σ hs
line 366 [decl:Core.updatedStateInit · theorem · mentions updatedState, none, Option · used by nearby declarations] Core.updatedStateInit : ∀ {P : PureExpr} {σ : SemanticStore P} {h : P.Ident} {v : P.Expr}, σ h = none → InitState P σ h v (updatedState σ h v)
line 849 [decl:Core.UpdateStateSomeMonotone · theorem · mentions UpdateState, some, Option · used by nearby declarations] Core.UpdateStateSomeMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {k' : P.Ident} {v' e : P.Expr} {v : P.Ident}, v ≠ k' → σ k' = some v' → UpdateState P σ v e σ' → σ' k' = some v'
line 684 [decl:Core.UpdateStateReadValuesMonotone · theorem · mentions UpdateState, mem, Not · used by nearby declarations] Core.UpdateStateReadValuesMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {ks : List P.Ident} {vs : List P.Expr} {e : P.Expr} {v : P.Ident}, ¬v ∈ ks → ReadValues σ ks vs → UpdateState P σ v e σ' → ReadValues σ' ks vs
line 726 [decl:Core.UpdateStateReadValues · theorem · mentions UpdateState, cons, nil · used by nearby declarations] Core.UpdateStateReadValues : ∀ {P : PureExpr} {σ : SemanticStore P} {v : P.Ident} {e : P.Expr} {σ' : SemanticStore P}, UpdateState P σ v e σ' → ReadValues σ' [v] [e]
line 36 [decl:Core.UpdateStatesEmpty · theorem · mentions UpdateStates, nil] Core.UpdateStatesEmpty : ∀ {P : PureExpr} {σ σ' : SemanticStore P}, UpdateStates σ [] [] σ' → σ = σ'
line 934 [decl:Core.InitStatesSomeMonotone' · theorem · mentions mem, Not, some] Core.InitStatesSomeMonotone' : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {k' : P.Ident} {v' : P.Expr} {ks' : List P.Ident} {vs' : List P.Expr}, ¬k' ∈ ks' → σ' k' = some v' → InitStates σ ks' vs' σ' → σ k' = some v'
line 772 [decl:Core.InitVarsInitStates · theorem · mentions Exists · concludes Exists] Core.InitVarsInitStates : ∀ {P : PureExpr} {σ : SemanticStore P} {vars : List P.Ident} {σ' : SemanticStore P}, InitVars σ vars σ' → ∃ modvals, InitStates σ vars modvals σ'
line 698 [decl:Core.UpdateStatesReadValuesMonotone · theorem · mentions UpdateStates · used by nearby declarations] Core.UpdateStatesReadValuesMonotone : ∀ {P : PureExpr} {σ σ' : SemanticStore P} {ks : List P.Ident} {vs es' : List P.Expr} {vs' : List P.Ident}, (ks ++ vs').Nodup → ReadValues σ ks vs → UpdateStates σ vs' es' σ' → ReadValues σ' ks vs
line 752 [decl:Core.UpdateStatesReadValues · theorem · mentions UpdateStates] Core.UpdateStatesReadValues : ∀ {P : PureExpr} {σ : SemanticStore P} {vs : List P.Ident} {es : List P.Expr} {σ' : SemanticStore P}, vs.Nodup → UpdateStates σ vs es σ' → ReadValues σ' vs es

