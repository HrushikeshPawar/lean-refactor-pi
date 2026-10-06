open Lean Elab Command Meta in
elab "arena_decl " ids:ident* : command => do
  let env ← getEnv
  for id in ids do
    let found ← try liftCoreM (resolveGlobalConst id) catch _ => pure []
    match found with
    | [] => logInfo m!"ARENA_DECL {(Lean.Json.mkObj [("symbol", id.getId.toString), ("found", false)]).compress}"
    | names =>
      for n in names do
        match env.find? n with
        | none => pure ()
        | some ci =>
          let sig ← try liftTermElabM (do pure s!"{n} : {← ppExpr ci.type}") catch _ => pure n.toString
          let modName := match env.getModuleIdxFor? n with
            | none => "this file"
            | some idx => (env.header.moduleNames[idx.toNat]!).toString
          let line ← try
              match ← findDeclarationRanges? n with
              | some r => pure (some r.range.pos.line)
              | none => pure none
            catch _ => pure none
          let kind := match ci with
            | .thmInfo _ => "theorem" | .axiomInfo _ => "theorem" | .defnInfo _ => "def"
            | .inductInfo _ => "inductive" | .ctorInfo _ => "constructor" | .opaqueInfo _ => "opaque"
            | .recInfo _ => "recursor" | .quotInfo _ => "quot"
          logInfo m!"ARENA_DECL {(Lean.Json.mkObj [("symbol", id.getId.toString), ("found", true), ("name", n.toString), ("kind", kind), ("module", modName), ("line", match line with | some l => Json.num l | none => Json.null), ("signature", sig)]).compress}"

