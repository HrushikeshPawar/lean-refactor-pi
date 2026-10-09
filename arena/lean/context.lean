-- Declaration ranges of an imported module, read from its server olean part. Modules compiled
-- with the module system do not expose them through the environment.
meta unsafe def arena_moduleRanges (m : Lean.Name) : IO (Array (Lean.Name × Lean.DeclarationRanges)) := do
  let fname ← Lean.findOLean m
  let parts ← Lean.readModuleDataParts #[fname, Lean.OLeanLevel.server.adjustFileName fname]
  for (data, _) in parts do
    -- Not `ext`: Mathlib projects that define `ext` as a token make `(ext, entries)` an unsupported pattern.
    for (extName, entries) in data.entries do
      if extName == Lean.declRangeExt.name then
        return unsafeCast entries
  return #[]

open Lean Elab Command Meta in
elab "arena_context " cmd:command : command => do
  let projectRoots : List String := [@@ROOTS@@]
  let targetName := @@TARGET@@
  let envBefore ← getEnv
  modify fun s => { s with infoState := { s.infoState with enabled := true } }
  let before := (← get).infoState.trees.size
  elabCommand (← `(command| set_option Elab.async false in set_option maxHeartbeats 0 in $(⟨cmd.raw⟩):command))
  let fm ← getFileMap
  let emit (fields : List (String × Json)) : CommandElabM Unit :=
    logInfo m!"ARENA_CTX {(Lean.Json.mkObj fields).compress}"
  let clip (s : String) (n : Nat) : String := if s.length > n then (s.toList.take n).foldl String.push "" ++ "…" else s
  let sigOf (n : Lean.Name) : CommandElabM String := do
    match (← getEnv).find? n with
    | none => pure ""
    | some ci =>
      try
        liftTermElabM (do pure s!"{n} : {← ppExpr ci.type}")
      catch _ => pure ""
  -- Relevance summary of a statement: its constants and the shape of its conclusion. Equations and
  -- iffs report the heads and constants of their sides, so rewrite lemmas can be matched to goals.
  let rec stripPi : Nat → Lean.Expr → Lean.Expr
    | 0, e => e
    | fuel + 1, .forallE _ _ b _ => stripPi fuel b
    | fuel + 1, .mdata _ b => stripPi fuel b
    | _, e => e
  let headOf (e : Lean.Expr) : String := match e.getAppFn with | .const n _ => n.toString | _ => ""
  -- Library constants (Init, Std, Lean) are reported apart: they are generic glue, not subject matter.
  let isCoreConst (n : Lean.Name) (env : Lean.Environment) : Bool :=
    match env.getModuleIdxFor? n with
    | none => false
    | some idx => ["Init", "Std", "Lean"].contains (env.header.moduleNames[idx.toNat]!).getRoot.toString
  let constsOf (e : Lean.Expr) (env : Lean.Environment) (core : Bool) : Json :=
    Json.arr (((e.getUsedConstants.filter (fun n => !n.isInternal && !Lean.Meta.isInstanceCore env n &&
        isCoreConst n env == core)).toList.take 60).map (fun n => Json.str n.toString)).toArray
  let summ (ty : Lean.Expr) (env : Lean.Environment) : List (String × Json) :=
    let c := stripPi 100 ty
    let (rel, l, r) :=
      if c.isAppOfArity ``Eq 3 then ("eq", c.getArg! 1, c.getArg! 2)
      else if c.isAppOfArity ``Iff 2 then ("iff", c.getArg! 0, c.getArg! 1)
      else ("", c, c)
    -- Bound with `:=` so the list never starts a line after a term: project notations such as
    -- CSLib's `t [μ]↠ t'` would otherwise parse `("", c, c)` followed by `[` as their own syntax.
    let fields : List (String × Json) := [("consts", constsOf ty env false),
      ("core_consts", constsOf ty env true), ("concl_head", headOf c), ("rel", rel), ("lhs_head", headOf l),
      ("rhs_head", headOf r), ("lhs_consts", constsOf l env false)]
    fields
  -- Source line span of an imported declaration, so lookups read exact pinned lines without searching.
  let moduleRanges ← IO.mkRef (({} : Std.HashMap Lean.Name (Array (Lean.Name × Lean.DeclarationRanges))))
  let rangeOf (n : Lean.Name) : CommandElabM (List (String × Json)) := do
    let fields := fun (r : DeclarationRanges) =>
      [("start_line", (r.range.pos.line : Json)), ("end_line", (r.range.endPos.line : Json))]
    match (← getEnv).getModuleIdxFor? n with
    | none => pure []
    | some idx =>
      match ← findDeclarationRanges? n with
      | some r => pure (fields r)
      | none =>
        let m := (← getEnv).header.moduleNames[idx.toNat]!
        if ["Init", "Std", "Lean"].contains m.getRoot.toString then pure [] else
        let known ← match (← moduleRanges.get)[m]? with
          | some rs => pure rs
          | none => do
            let rs ← try unsafe arena_moduleRanges m catch _ => pure #[]
            moduleRanges.modify (·.insert m rs)
            pure rs
        match known.find? (·.1 == n) with
        | some (_, r) => pure (fields r)
        | none => pure []
  let isProjectLocal (n : Lean.Name) (env : Lean.Environment) : Bool :=
    match env.getModuleIdxFor? n with
    | none => true
    | some idx =>
      let m := env.header.moduleNames[idx.toNat]!
      projectRoots.contains m.getRoot.toString
  -- Modules compiled with the module system expose imported theorems as `axiomInfo` stubs,
  -- so only the kernel's axioms and axioms declared in this file count as axioms.
  let isAxiomC := fun (n : Lean.Name) (env : Lean.Environment) =>
    match env.find? n with
    | some (.axiomInfo _) =>
      (env.getModuleIdxFor? n).isNone ||
        [``propext, ``Classical.choice, ``Quot.sound, ``sorryAx, ``Lean.ofReduceBool, ``Lean.trustCompiler].contains n
    | _ => false
  -- How a constant should be presented: generated and instance glue, axioms and core
  -- logic are tagged so only source-style helpers are offered as dependencies.
  let tagOf (n : Lean.Name) (env : Lean.Environment) : String :=
    let user := (privateToUserName? n).getD n
    let last := match user with | .str _ s => s | _ => ""
    let numbered := fun (pre : String) => last.startsWith pre && (last.drop pre.length).all Char.isDigit
                    && last.length > pre.length
    let root := match env.getModuleIdxFor? n with
      | none => ""
      | some idx => (env.header.moduleNames[idx.toNat]!).getRoot.toString
    if user.isInternal || user.isInternalDetail || numbered "match_" || numbered "eq_" then "generated"
    else if Lean.Meta.isInstanceCore env n then "instance"
    else if isAxiomC n env then "axiom"
    else if (n.components.any (fun c => c.toString == "Tactic" || c.toString == "Meta")) ||
        (match env.getModuleIdxFor? n with
          | none => false
          | some idx => (env.header.moduleNames[idx.toNat]!).components.any
              (fun c => c.toString == "Tactic" || c.toString == "Meta")) then "tactic"
    else if root == "Init" || root == "Lean" then "core"
    else "helper"
  -- top-level tactics of the declaration's `by` block
  let rec findBy : Nat → Lean.Syntax → Option Lean.Syntax
    | 0, _ => none
    | fuel + 1, s => if s.getKind == ``Lean.Parser.Term.byTactic then some s
                     else s.getArgs.findSome? (findBy fuel)
  let mut topLevel : Array (String.Pos.Raw × String.Pos.Raw) := #[]
  match findBy 200 cmd.raw with
  | some b =>
    let seq := b.getArg 1
    let items := ((seq.getArg 0).getArg 0).getArgs
    for i in [0:items.size] do
      if i % 2 == 0 then
        match items[i]!.getPos?, items[i]!.getTailPos? with
        | some p, some q => topLevel := topLevel.push (p, q)
        | _, _ => pure ()
  | none => pure ()
  let seenGoal ← IO.mkRef (#[] : Array (Nat × Nat))
  let goalConsts ← IO.mkRef (#[] : Array Lean.Name)
  let sourceRefs ← IO.mkRef (#[] : Array (Lean.Name × Nat × Nat))
  let rec visit : Nat → Option ContextInfo → InfoTree → CommandElabM Unit
    | 0, _, _ => pure ()
    | fuel + 1, ctx?, .context pci t => visit fuel (pci.mergeIntoOuter? ctx?) t
    | fuel + 1, ctx?, .node info cs => do
      match ctx? with
      | none => pure ()
      | some ctx =>
        match info with
        | .ofTacticInfo ti =>
          match ti.stx.getPos?, ti.stx.getTailPos? with
          | some p, some q =>
            if topLevel.any (fun (a, b) => a == p && b == q) then
              let line := (fm.toPosition p).line
              let endLine := (fm.toPosition q).line
              unless (← seenGoal.get).contains (line, endLine) do
                seenGoal.modify (·.push (line, endLine))
                let mut text := ""
                for g in ti.goalsBefore do
                  try
                    let f ← ({ ctx with mctx := ti.mctxBefore } : ContextInfo).runMetaM {} (ppGoal g)
                    text := text ++ toString f ++ "\n"
                  catch _ => pure ()
                let mut shape : List (String × Json) := []
                for g in ti.goalsBefore do
                  match ti.mctxBefore.findDecl? g with
                  | some d =>
                    let goalType := (instantiateMVarsCore ti.mctxBefore d.type).1
                    goalConsts.modify (· ++ goalType.getUsedConstants)
                    shape := shape ++ summ goalType ctx.env
                  | none => pure ()
                emit (([("kind", "goal"), ("line", line), ("endLine", endLine), ("text", text)] : List (String × Json)) ++
                  (if shape.length > 7 then shape.take 7 else shape))
          | _, _ => pure ()
        | .ofTermInfo ti =>
          let sourceAuthored := match ti.stx.getHeadInfo with
            | .original .. => true
            | _ => false
          if ti.stx.isIdent && !ti.isBinder && sourceAuthored then
            let pos := fm.toPosition (ti.stx.getPos?.getD 0)
            match ti.expr.getAppFn with
            | .const n _ => sourceRefs.modify (·.push (n, pos.line, pos.column))
            | .fvar id =>
              match ti.lctx.find? id with
              | some decl =>
                let ty ← ctx.runMetaM {} (withLCtx ti.lctx {} do pure (← ppExpr decl.type).pretty)
                emit [("kind", "local"), ("name", decl.userName.toString), ("line", pos.line),
                      ("column", pos.column), ("scope", "theorem proof context"), ("type", clip ty 500)]
              | none => pure ()
            | _ => pure ()
        | _ => pure ()
      for c in cs do visit fuel ctx? c
    | _, _, .hole _ => pure ()
  for tree in (← get).infoState.trees.toList.drop before do
    visit 3000 none tree
  let env ← getEnv
  -- definitions of project types appearing in the statement
  let newDecls := env.constants.map₂.toList.filter (fun (n, _) => !envBefore.contains n && !n.isInternal)
  let mut stmtNames : Array Lean.Name := #[]
  for (n, ci) in newDecls do
    match ci with
    | .thmInfo _ =>
      for u in ci.type.getUsedConstants do
        unless stmtNames.contains u do stmtNames := stmtNames.push u
    | _ => pure ()
  for n in stmtNames do
    if isProjectLocal n envBefore && !envBefore.isProjectionFn n then
      match envBefore.find? n with
      | some (.inductInfo v) =>
        let mut ctors : Array Json := #[]
        for c in v.ctors do ctors := ctors.push (Json.str (clip (← sigOf c) 400))
        emit [("kind", "type"), ("name", n.toString), ("decl", if isStructure envBefore n then "structure" else "inductive"),
              ("sig", clip (← sigOf n) 400), ("ctors", Json.arr ctors)]
      | some (.defnInfo v) =>
        let body ← liftTermElabM (do pure (toString (← ppExpr v.value)))
        emit [("kind", "type"), ("name", n.toString), ("decl", "def"),
              ("sig", clip (← sigOf n) 400), ("value", clip body 600)]
      | _ => pure ()
  -- Every resolvable identifier occurrence in the declaration's source.
  for (n, line, column) in (← sourceRefs.get) do
    let ci? := env.find? n
    match ci? with
    | none => pure ()
    | some ci =>
      let decl := match ci with
        | .thmInfo _ => "theorem" | .defnInfo _ => "def" | .inductInfo _ => "inductive"
        | .ctorInfo _ => "constructor" | .axiomInfo _ => if isAxiomC n env then "axiom" else "theorem" | .opaqueInfo _ => "opaque"
        | .recInfo _ => "recursor" | .quotInfo _ => "quot"
      let modName := match env.getModuleIdxFor? n with
        | none => "this file"
        | some idx => (env.header.moduleNames[idx.toNat]!).toString
      emit (([("kind", "source"), ("name", n.toString), ("line", line), ("column", column),
            ("decl", decl), ("module", modName), ("tag", tagOf n env), ("sig", clip (← sigOf n) 500)] : List (String × Json)) ++
            (← rangeOf n))
  -- Direct theorem and lemma constants in the elaborated proof term. Keep the full
  -- constant index available to the cache, but classify generated constants by kind.
  match env.find? targetName with
    | some (.thmInfo info) =>
      for n in info.value.getUsedConstants do
        let constantDecl := match env.find? n with
          | some (.thmInfo _) => "theorem"
          | some (.axiomInfo _) => if isAxiomC n env then "axiom" else "theorem"
          | some (.defnInfo _) => "def" | some (.inductInfo _) => "inductive"
          | some (.ctorInfo _) => "constructor" | some (.opaqueInfo _) => "opaque"
          | some (.recInfo _) => "recursor" | _ => "generated/other"
        let constantModule := match env.getModuleIdxFor? n with
          | none => "this file"
          | some idx => (env.header.moduleNames[idx.toNat]!).toString
        let tag := tagOf n env
        emit (([("kind", "constant"), ("name", n.toString), ("decl", constantDecl), ("tag", tag),
              ("origin", "elaborated-proof"), ("module", constantModule),
              ("sig", clip (← sigOf n) 500)] : List (String × Json)) ++ (← rangeOf n))
        unless n == targetName do
          match env.find? n with
          | some (.thmInfo _) | some (.axiomInfo _) =>
            emit [("kind", "dependency"), ("name", n.toString), ("decl", constantDecl), ("tag", tag),
                  ("module", constantModule), ("sig", clip (← sigOf n) 500)]
          | _ => pure ()
    | _ => emit [("kind", "failure"), ("message", s!"Pinned theorem {targetName} did not elaborate as a theorem")]
  -- Statement constants of the pinned theorem, for ranking earlier lemmas by relevance.
  match env.find? targetName with
    | some ci => emit (([("kind", "target")] : List (String × Json)) ++ summ ci.type env)
    | none => pure ()
  -- declarations earlier in this file, nearest first, each with its relevance summary
  let mut earlier : Array (Nat × Lean.Name) := #[]
  for (n, ci) in envBefore.constants.map₂.toList do
    unless n.isInternal || isPrivateName n || ((toString n).splitOn "rena_").length > 1 do
      match ← findDeclarationRanges? n with
      | some r => earlier := earlier.push (r.range.pos.line, n)
      | none => pure ()
  let sorted := (earlier.qsort (fun a b => a.1 > b.1)).toList.take 400
  let earlierSet : Std.HashSet Lean.Name := sorted.foldl (fun acc (_, n) => acc.insert n) {}
  for (line, n) in sorted do
    let decl := match envBefore.find? n with
      | some (.thmInfo _) => "theorem" | some (.defnInfo _) => "def" | some (.inductInfo _) => "inductive"
      | some (.ctorInfo _) => "constructor" | _ => "other"
    let shape := match envBefore.find? n with
      | some ci => summ ci.type envBefore
      | none => []
    -- earlier declarations of this file that the lemma's proof uses
    let uses : Json := match envBefore.find? n with
      | some (.thmInfo v) =>
        Json.arr ((v.value.getUsedConstants.filter (fun u => u != n && earlierSet.contains u)).toList.take 40
          |>.map (fun u => Json.str u.toString)).toArray
      | _ => Json.arr #[]
    emit (([("kind", "earlier"), ("name", n.toString), ("line", line), ("decl", decl),
          ("sig", clip (← sigOf n) 400), ("uses", uses)] : List (String × Json)) ++ shape)
  -- Imported theorems whose statements match the goal. Each theorem scores the IDF-weighted mass of the
  -- constants of its statement that also occur in the pinned theorem's statement (weight 1), the goals of the
  -- reference proof (0.7) and the statements of the lemmas its source names (0.5), saturated against its own
  -- unshared mass so long generic statements do not win. A theorem in the namespace of such a constant
  -- (`Continuous.foo`, `HomBisimilarity.foo`) counts that constant once more. Rare constants dominate: the
  -- IDF is taken over every imported theorem. The scan stops after a time budget.
  let libStart ← IO.monoMsNow
  let referenced := (← sourceRefs.get).map (·.1)
  let goalNames ← goalConsts.get
  let isParentProj := fun (u : Lean.Name) => (match u with
    | .str _ s => s.length > 2 && s.startsWith "to" && (s.get ⟨2⟩).isUpper
    | _ => false) && env.isProjectionFn u
  let usable := fun (u : Lean.Name) => !u.isInternal && !Lean.Meta.isInstanceCore env u && !isParentProj u
  let wanted : Std.HashMap Lean.Name Float := Id.run do
    let mut w : Std.HashMap Lean.Name Float := {}
    let bump := fun (w : Std.HashMap Lean.Name Float) (n : Lean.Name) (x : Float) =>
      if usable n && w.getD n 0.0 < x then w.insert n x else w
    for n in referenced do
      match env.find? n with
      | some ci => for u in ci.type.getUsedConstants do w := bump w u 0.5
      | none => pure ()
    for u in goalNames do w := bump w u 0.7
    match env.find? targetName with
    | some ci => for u in ci.type.getUsedConstants do w := bump w u 1.0
    | none => pure ()
    return w
  -- Tactic, meta and Lean-internal modules and generated declarations are not statements a proof would cite.
  let rec hasComp : Lean.Name → Bool
    | .str p s => s == "Tactic" || s == "Meta" || hasComp p
    | .num p _ => hasComp p
    | .anonymous => false
  let skipModule : Array Bool := env.header.moduleNames.map fun m => m.getRoot.toString == "Lean" || hasComp m
  let generatedSuffixes := ["inj", "injEq", "brecOn", "binductionOn", "sizeOf_spec", "eq_def", "ext_iff", "noConfusion",
    "noConfusionType", "below", "ibelow", "casesOn", "recOn", "rec", "congr_simp", "induct", "induct_unfolding"]
  let generatedName := fun (n : Lean.Name) =>
    n.isInternal || n.isInternalDetail || (match n with
      | .str _ s => generatedSuffixes.contains s ||
          ((s.startsWith "match_" || s.startsWith "eq_") && s.length > 3 && (s.drop 3).all (fun c => c.isDigit || c == '_'))
      | _ => false)
  let mut pool : Array (Lean.Name × Array Lean.Name) := #[]
  let mut df : Std.HashMap Lean.Name Nat := {}
  let mut scanned := 0
  let mut truncated := false
  for (n, ci) in env.constants.map₁ do
    scanned := scanned + 1
    if scanned % 8192 == 0 && (← IO.monoMsNow) - libStart > 30000 then
      truncated := true
      break
    let isThm := match ci with | .thmInfo _ => true | .axiomInfo _ => !isAxiomC n env | _ => false
    if isThm && n != targetName && !generatedName n && !isPrivateName n &&
        (match env.getModuleIdxFor? n with | some idx => !skipModule[idx.toNat]! | none => false) then
      let usedConsts := ci.type.getUsedConstants.filter usable
      for u in usedConsts do df := df.insert u (df.getD u 0 + 1)
      pool := pool.push (n, usedConsts)
  let scanMs := (← IO.monoMsNow) - libStart
  let total := pool.size.toFloat
  let idf := fun (u : Lean.Name) => Float.log ((total + 1.0) / ((df.getD u 0).toFloat + 0.5))
  let mut scored : Array (Float × Lean.Name) := #[]
  for (n, usedConsts) in pool do
    let mut shared := 0.0
    let mut rest := 0.0
    for u in usedConsts do
      match wanted[u]? with
      | some w => shared := shared + w * idf u
      | none => rest := rest + idf u
    match n with
    | .str ns _ =>
      match wanted[ns]? with
      | some w => shared := shared + w * idf ns
      | none => pure ()
    | _ => pure ()
    if shared > 0.0 then scored := scored.push (shared / (shared + 0.5 * rest + 3.0), n)
  let top := (scored.qsort (fun a b => a.1 > b.1 || (a.1 == b.1 && a.2.toString < b.2.toString))).toList.take 60
  for (score, n) in top do
    match env.find? n with
    | some ci =>
      let shared := (ci.type.getUsedConstants.filter (fun u => wanted.contains u)).toList
      let sharedSorted := (shared.toArray.qsort (fun a b => wanted.getD a 0.0 * idf a > wanted.getD b 0.0 * idf b)).toList.take 4
      emit [("kind", "library"), ("name", n.toString), ("score", (Float.round (score * 10000.0) / 10000.0 : Float).toString),
            ("module", match env.getModuleIdxFor? n with
              | some idx => (env.header.moduleNames[idx.toNat]!).toString | none => ""),
            ("shared", Json.arr ((sharedSorted.map (fun u => Json.str u.toString)).toArray)),
            ("sig", clip (← sigOf n) 600)]
    | none => pure ()
  emit [("kind", "library_scan"), ("scanned", scanned), ("pool", pool.size), ("truncated", truncated),
        ("scan_ms", scanMs), ("ms", ((← IO.monoMsNow) - libStart : Nat))]
  emit [("kind", "end")]

arena_context
