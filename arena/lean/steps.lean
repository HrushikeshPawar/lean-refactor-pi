open Lean Elab Command Meta in
elab "arena_steps " cmd:command : command => do
  let targetName := @@TARGET@@
  let before := (← get).infoState.trees.size
  elabCommand (← `(command| set_option Elab.async false in set_option maxHeartbeats 0 in $(⟨cmd.raw⟩):command))
  match (← getEnv).find? targetName with
  | none => throwError m!"Target declaration {targetName} did not elaborate"
  | some _ => pure ()
  let fm ← getFileMap
  let emit (line endLine : Nat) (text : String) : CommandElabM Unit := do
    let fields := [("line", toJson line), ("endLine", toJson endLine), ("text", toJson text)]
    logInfo m!"ARENA_STEPS {(Lean.Json.mkObj fields).compress}"
  let rec findBy : Nat → Lean.Syntax → Option Lean.Syntax
    | 0, _ => none
    | fuel + 1, stx =>
      if stx.getKind == ``Lean.Parser.Term.byTactic then some stx
      else stx.getArgs.findSome? (findBy fuel)
  let mut topLevel : Array (String.Pos.Raw × String.Pos.Raw) := #[]
  match findBy 200 cmd.raw with
  | some block =>
    let sequence := block.getArg 1
    let items := ((sequence.getArg 0).getArg 0).getArgs
    for i in [0:items.size] do
      if i % 2 == 0 then
        match items[i]!.getPos?, items[i]!.getTailPos? with
        | some p, some q => topLevel := topLevel.push (p, q)
        | _, _ => pure ()
  | none => pure ()
  let seen ← IO.mkRef (#[] : Array (Nat × Nat))
  let rec visit : Nat → Option ContextInfo → InfoTree → CommandElabM Unit
    | 0, _, _ => pure ()
    | fuel + 1, context?, .context parent tree => visit fuel (parent.mergeIntoOuter? context?) tree
    | fuel + 1, context?, .node info children => do
      match context?, info with
      | some context, .ofTacticInfo tactic =>
        match tactic.stx.getPos?, tactic.stx.getTailPos? with
        | some p, some q =>
          if topLevel.any (fun (a, b) => a == p && b == q) then
            let line := (fm.toPosition p).line
            let endLine := (fm.toPosition q).line
            unless (← seen.get).contains (line, endLine) do
              seen.modify (·.push (line, endLine))
              let mut text := ""
              for goal in tactic.goalsBefore do
                try
                  let formatted ← ({ context with mctx := tactic.mctxBefore } : ContextInfo).runMetaM {} (ppGoal goal)
                  text := text ++ toString formatted ++ "\n"
                catch _ => pure ()
              emit line endLine text
        | _, _ => pure ()
      | _, _ => pure ()
      for child in children do visit fuel context? child
    | _, _, .hole _ => pure ()
  for tree in (← get).infoState.trees.toList.drop before do
    visit 3000 none tree
  pure ()

arena_steps
