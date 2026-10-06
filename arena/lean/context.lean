open Lean Elab Command Meta in
elab "arena_context " cmd:command : command => do
  let projectRoots : List String := [@@ROOTS@@]
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
  let isProjectLocal (n : Lean.Name) (env : Lean.Environment) : Bool :=
    match env.getModuleIdxFor? n with
    | none => true
    | some idx =>
      let m := env.header.moduleNames[idx.toNat]!
      projectRoots.contains m.getRoot.toString
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
  let usedRef ← IO.mkRef (#[] : Array (Lean.Name × Nat))
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
          if ti.stx.isIdent && !ti.isBinder then
            match ti.expr.getAppFn with
            | .const n _ =>
              unless (← usedRef.get).any (·.1 == n) do
                usedRef.modify (·.push (n, (fm.toPosition (ti.stx.getPos?.getD 0)).line))
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
  -- constants the declaration's source mentions
  for (n, line) in (← usedRef.get) do
    let ci? := env.find? n
    match ci? with
    | none => pure ()
    | some ci =>
      let decl := match ci with
        | .thmInfo _ => "theorem" | .defnInfo _ => "def" | .inductInfo _ => "inductive"
        | .ctorInfo _ => "constructor" | .axiomInfo _ => "theorem" | .opaqueInfo _ => "opaque"
        | .recInfo _ => "recursor" | .quotInfo _ => "quot"
      let modName := match env.getModuleIdxFor? n with
        | none => "this file"
        | some idx => (env.header.moduleNames[idx.toNat]!).toString
      emit [("kind", "used"), ("name", n.toString), ("line", line), ("decl", decl),
            ("module", modName), ("sig", clip (← sigOf n) 500)]
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
