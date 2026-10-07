-- Declaration ranges of an imported module, read from its server olean part. Modules compiled
-- with the module system do not expose them through the environment.
meta unsafe def arena_moduleRanges (m : Lean.Name) : IO (Array (Lean.Name × Lean.DeclarationRanges)) := do
  let fname ← Lean.findOLean m
  let parts ← Lean.readModuleDataParts #[fname, Lean.OLeanLevel.server.adjustFileName fname]
  for (data, _) in parts do
    for (ext, entries) in data.entries do
      if ext == Lean.declRangeExt.name then
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
  let clip (s : String) (n : Nat) : String := if s.length > n then String.ofList (s.toList.take n) ++ "…" else s
  let sigOf (n : Lean.Name) : CommandElabM String := do
    match (← getEnv).find? n with
    | none => pure ""
    | some ci =>
      try
        liftTermElabM (do pure s!"{n} : {← ppExpr ci.type}")
      catch _ => pure ""
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
                emit [("kind", "goal"), ("line", line), ("endLine", endLine), ("text", text)]
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
  -- declarations earlier in this file, nearest first
  let mut earlier : Array (Nat × Lean.Name) := #[]
  for (n, ci) in envBefore.constants.map₂.toList do
    unless n.isInternal || isPrivateName n || ((toString n).splitOn "rena_").length > 1 do
      match ← findDeclarationRanges? n with
      | some r => earlier := earlier.push (r.range.pos.line, n)
      | none => pure ()
  let sorted := earlier.qsort (fun a b => a.1 > b.1)
  for (line, n) in sorted.toList.take 120 do
    let decl := match envBefore.find? n with
      | some (.thmInfo _) => "theorem" | some (.defnInfo _) => "def" | some (.inductInfo _) => "inductive"
      | some (.ctorInfo _) => "constructor" | _ => "other"
    emit [("kind", "earlier"), ("name", n.toString), ("line", line), ("decl", decl),
          ("sig", clip (← sigOf n) 400)]
  emit [("kind", "end")]

arena_context
