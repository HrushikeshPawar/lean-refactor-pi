-- Declaration suffixes mirror `context.lean` so both paths agree on generated names.
meta def arenaGeneratedSuffixes : List String :=
  ["inj", "injEq", "brecOn", "binductionOn", "sizeOf_spec", "eq_def", "ext_iff", "noConfusion",
    "noConfusionType", "below", "ibelow", "casesOn", "recOn", "rec", "congr_simp", "induct",
    "induct_unfolding"]

meta unsafe def arena_indexModuleRanges (moduleName : Lean.Name) : IO (Array (Lean.Name × Lean.DeclarationRanges)) := do
  let fileName ← Lean.findOLean moduleName
  let parts ← Lean.readModuleDataParts #[fileName, Lean.OLeanLevel.server.adjustFileName fileName]
  for (data, _) in parts do
    for (extension, entries) in data.entries do
      if extension == Lean.declRangeExt.name then
        return unsafeCast entries
  return #[]

open Lean Elab Command Meta in
elab "arena_index" : command => do
  let env ← getEnv
  let outputPath : System.FilePath := @@INDEX_PATH@@
  let handle ← IO.FS.Handle.mk outputPath .write
  let moduleRanges ← IO.mkRef ({} : Std.HashMap Lean.Name (Array (Lean.Name × Lean.DeclarationRanges)))
  let isGenerated (name : Lean.Name) : Bool :=
    name.isInternal || name.isInternalDetail || match name with
      | .str _ last => arenaGeneratedSuffixes.contains last ||
          ((last.startsWith "match_" || last.startsWith "eq_") && last.length > 3 &&
            (last.drop 3).all (fun c => c.isDigit || c == '_'))
      | _ => false
  let declKind (name : Lean.Name) (info : Lean.ConstantInfo) : String :=
    if Lean.Meta.isInstanceCore env name then "instance" else
    match info with
    | .thmInfo _ => "theorem"
    | .axiomInfo _ => "axiom"
    | .defnInfo _ => "def"
    | .opaqueInfo _ => "opaque"
    | .inductInfo _ => if isClass env name then "class" else if isStructure env name then "structure" else "inductive"
    | .ctorInfo _ => "constructor"
    | .recInfo _ => "recursor"
    | .quotInfo _ => "quot"
  let rec stripPi : Nat → Lean.Expr → Lean.Expr
    | 0, expr => expr
    | fuel + 1, .forallE _ _ body _ => stripPi fuel body
    | fuel + 1, .mdata _ body => stripPi fuel body
    | _, expr => expr
  let headOf (expr : Lean.Expr) : String :=
    match (stripPi 100 expr).getAppFn with
    | .const name _ => name.toString
    | _ => ""
  let typeText (info : Lean.ConstantInfo) : CommandElabM String := do
    try
      let formatted ← liftTermElabM (do pure (← ppExpr info.type).pretty)
      pure (if formatted.length > 600 then (String.ofList (formatted.toList.take 599)) ++ "…" else formatted)
    catch _ => pure ""
  let rangesFor (name : Lean.Name) : CommandElabM (Option (Nat × Nat)) := do
    match ← findDeclarationRanges? name with
    | some range => pure (some (range.range.pos.line, range.range.endPos.line))
    | none =>
      match env.getModuleIdxFor? name with
      | none => pure none
      | some idx => do
        let moduleName := env.header.moduleNames[idx.toNat]!
        let ranges ← match (← moduleRanges.get)[moduleName]? with
          | some ranges => pure ranges
          | none => do
            let found ← try unsafe arena_indexModuleRanges moduleName catch _ => pure #[]
            moduleRanges.modify (·.insert moduleName found)
            pure found
        match ranges.find? (·.1 == name) with
        | some (_, range) => pure (some (range.range.pos.line, range.range.endPos.line))
        | none => pure none
  let rows := env.constants.map₁.toList ++ env.constants.map₂.toList
  let localNames := env.constants.map₂.toList.map (fun item => item.1)
  for (name, info) in rows do
    let privateName := isPrivateName name
    let generated := isGenerated name
    let moduleName := if localNames.contains name then "(this file)" else match env.getModuleIdxFor? name with
      | none => "(this file)"
      | some idx => (env.header.moduleNames[idx.toNat]!).toString
    let range ← rangesFor name
    let mut fields : List (String × Json) := [
      ("name", toJson name.toString),
      ("kind", toJson (declKind name info)),
      ("module", toJson moduleName),
      ("line", match range with | some (line, _) => toJson line | none => Json.null),
      ("end_line", match range with | some (_, line) => toJson line | none => Json.null),
      ("generated", toJson generated),
      ("private", toJson privateName)]
    if !generated && !privateName then
      let signature ← typeText info
      fields := fields ++ [("type", toJson signature)]
    let consts := info.type.getUsedConstants.filter (fun used => !used.isInternal && !Lean.Meta.isInstanceCore env used)
    fields := fields ++ [
      ("head", toJson (headOf info.type)),
      ("consts", Json.arr (((consts.toList.take 40).map (fun used => Json.str used.toString)).toArray))]
    handle.putStrLn (Json.mkObj fields).compress
  handle.flush

arena_index
