-- Kernel-term features of a compiled candidate, for route fingerprints. `arena_route` elaborates the
-- candidate declaration, reads the kernel value of the declaration (and of the auxiliary declarations
-- generated for it), reports JSON features, and then restores the environment, so many candidates for
-- the same theorem can be read in one file without name clashes.
open Lean in
meta partial def arena_route_ser (fuel : Nat) (e : Lean.Expr) (d : Nat) : String :=
  match fuel with
  | 0 => "…"
  | fuel + 1 =>
    match e with
    | .bvar i => if i < d then s!"#{i}" else "_"
    | .const n _ => n.toString
    | .app f a => "(" ++ arena_route_ser fuel f d ++ " " ++ arena_route_ser fuel a d ++ ")"
    | .lam _ t b _ => "(λ " ++ arena_route_ser fuel t d ++ " " ++ arena_route_ser fuel b (d + 1) ++ ")"
    | .forallE _ t b _ => "(∀ " ++ arena_route_ser fuel t d ++ " " ++ arena_route_ser fuel b (d + 1) ++ ")"
    | .letE _ t v b _ => "(let " ++ arena_route_ser fuel t d ++ " " ++ arena_route_ser fuel v d ++ " " ++ arena_route_ser fuel b (d + 1) ++ ")"
    | .lit (.natVal n) => toString n
    | .lit (.strVal s) => s.quote
    | .mdata _ b => arena_route_ser fuel b d
    | .proj s i b => s!"{s}.{i}" ++ arena_route_ser fuel b d
    | .sort _ => "S"
    | _ => "_"

open Lean in
meta def arena_route_head (e : Lean.Expr) : String :=
  match e.getAppFn with
  | .const n _ => n.toString
  | .forallE .. => "∀"
  | .lam .. => "λ"
  | _ => "_"

-- Claims: the statement of a `have`/`let` binder or of a `calc` step, hashed with loose variables erased.
open Lean in
meta def arena_route_claim (t : Lean.Expr) : String :=
  s!"{arena_route_head t}#{(hash (arena_route_ser 40 t 0)).toNat % 4294967296}"

-- Binders the structural-recursion and induction machinery introduces, not claims the proof makes.
open Lean in
meta def arena_route_machinery (t : Lean.Expr) : Bool :=
  match t.getAppFn with
  | .const n _ => match n with
    | .str _ s => s == "below" || s == "ibelow" || s == "PProd" || s == "PUnit" || s.startsWith "motive"
    | _ => false
  | .fvar _ | .bvar _ => true
  | _ => false

open Lean in
meta partial def arena_route_walk (seen : IO.Ref (Std.HashSet Lean.Expr)) (claims : IO.Ref (Array String))
    (witnesses : IO.Ref (Array String)) (e : Lean.Expr) : IO Unit := do
  if (← seen.get).contains e then return
  seen.modify (·.insert e)
  match e with
  | .app f a =>
    let args := e.getAppArgs
    match e.getAppFn with
    | .const n _ =>
      if n == ``letFun && args.size ≥ 4 then unless arena_route_machinery args[0]! do claims.modify (·.push (arena_route_claim args[0]!))
      else if n == ``Trans.trans && args.size ≥ 10 then unless arena_route_machinery args[8]! do claims.modify (·.push (arena_route_claim args[8]!))
      else if n == ``Exists.intro && args.size ≥ 4 then
        witnesses.modify (·.push s!"Exists.intro@{arena_route_head args[2]!}")
    | _ => pure ()
    arena_route_walk seen claims witnesses f
    arena_route_walk seen claims witnesses a
  | .lam _ t b _ => do arena_route_walk seen claims witnesses t; arena_route_walk seen claims witnesses b
  | .forallE _ t b _ => do arena_route_walk seen claims witnesses t; arena_route_walk seen claims witnesses b
  | .letE _ t v b _ => do
    unless t.isConst || t.isSort || arena_route_machinery t do claims.modify (·.push (arena_route_claim t))
    arena_route_walk seen claims witnesses t; arena_route_walk seen claims witnesses v
    arena_route_walk seen claims witnesses b
  | .mdata _ b => arena_route_walk seen claims witnesses b
  | .proj _ _ b => arena_route_walk seen claims witnesses b
  | _ => pure ()

-- `sorryAx _ false` is a `sorry` the proof wrote (a hole); `sorryAx _ true` is what error recovery left behind.
-- Counted as occurrences in the term, memoised on structure so shared subterms cost nothing to revisit.
open Lean in
meta partial def arena_route_sorries (cache : IO.Ref (Std.HashMap Lean.Expr (Nat × Nat))) (e : Lean.Expr) : IO (Nat × Nat) := do
  if let some r := (← cache.get)[e]? then return r
  let add (a b : Nat × Nat) : Nat × Nat := (a.1 + b.1, a.2 + b.2)
  let r ← match e with
    | .app f a =>
      let args := e.getAppArgs
      match e.getAppFn with
      | .const n _ =>
        if n == ``sorryAx && args.size ≥ 2 then
          pure (if args[1]!.isConstOf ``Bool.true then (0, 1) else (1, 0))
        else pure (add (← arena_route_sorries cache f) (← arena_route_sorries cache a))
      | _ => pure (add (← arena_route_sorries cache f) (← arena_route_sorries cache a))
    | .lam _ t b _ => pure (add (← arena_route_sorries cache t) (← arena_route_sorries cache b))
    | .forallE _ t b _ => pure (add (← arena_route_sorries cache t) (← arena_route_sorries cache b))
    | .letE _ t v b _ => pure (add (add (← arena_route_sorries cache t) (← arena_route_sorries cache v)) (← arena_route_sorries cache b))
    | .mdata _ b => arena_route_sorries cache b
    | .proj _ _ b => arena_route_sorries cache b
    | _ => pure (0, 0)
  cache.modify (·.insert e r)
  return r

open Lean in
meta def arena_route_value (ci : Lean.ConstantInfo) : Option Lean.Expr :=
  match ci with
  | .thmInfo v => some v.value
  | .defnInfo v => some v.value
  | .opaqueInfo v => some v.value
  | _ => none

open Lean Elab Command Meta in
elab "arena_route " tag:str short:str cmd:command : command => do
  let basic : List String := ["Eq", "HEq", "And", "Or", "Iff", "Exists", "False", "True", "Empty", "PEmpty",
    "Subtype", "Prod", "PProd", "Sigma", "PSigma", "Unit", "PUnit", "Decidable", "Not"]
  let contra : List Lean.Name := [``Classical.byContradiction, ``Decidable.byContradiction, ``absurd,
    ``False.elim, ``False.rec, ``False.casesOn, ``Classical.not_not]
  let orElim : List Lean.Name := [``Or.elim, ``Or.casesOn, ``Or.rec, ``Or.recOn]
  let envBefore ← getEnv
  let messagesBefore := (← get).messages
  modify fun s => { s with messages := {} }
  let mut failure : Option String := none
  try
    elabCommand (← `(command| set_option Elab.async false in set_option maxHeartbeats 0 in $(⟨cmd.raw⟩):command))
  catch err => failure := some (← err.toMessageData.toString)
  let hadErrors := (← get).messages.hasErrors
  let env ← getEnv
  let started ← IO.monoMsNow
  let isNew (n : Lean.Name) : Bool := env.contains n && !envBefore.contains n
  let isCore (n : Lean.Name) : Bool :=
    match env.getModuleIdxFor? n with
    | none => false
    | some idx => ["Init", "Std", "Lean"].contains (env.header.moduleNames[idx.toNat]!).getRoot.toString
  let lastPart (n : Lean.Name) : String := match n with | .str _ s => s | _ => ""
  -- the declaration itself: the new non-internal theorem or definition named like the statement
  let mut main : Option Lean.Name := none
  for (n, ci) in env.constants.map₂.toList do
    if isNew n && !n.isInternal && !Lean.Meta.isMatcherCore env n && lastPart n == short.getString then
      match ci with
      | .thmInfo _ | .defnInfo _ => main := some n
      | _ => pure ()
  if main.isNone then
    for (n, ci) in env.constants.map₂.toList do
      if isNew n && !n.isInternal && !Lean.Meta.isMatcherCore env n then
        match ci with
        | .thmInfo _ => main := some n
        | _ => pure ()
  let mut fields : List (String × Lean.Json) := [("tag", Lean.Json.str tag.getString)]
  match main with
  | none =>
    fields := fields ++ [("ok", Lean.Json.bool false),
      ("error", Lean.Json.str (failure.getD (if hadErrors then "elaboration error" else "no declaration found")))]
  | some mainName =>
    let mainInfo := (env.find? mainName).get!
    -- the declaration plus the auxiliary declarations generated for it (proofs, matchers, unary forms, helpers);
    -- equation lemmas that `unfold` and `simp` generate for other definitions are not part of this proof
    let follow (n : Lean.Name) : Bool :=
      (isNew n && mainName.isPrefixOf n) || Lean.Meta.isMatcherCore env n
    let mut used : Std.HashSet Lean.Name := {}
    let mut visited : Std.HashSet Lean.Name := {}
    let mut queue : List Lean.Name := [mainName]
    let mut fuel := 4000
    let seen ← IO.mkRef ({} : Std.HashSet Lean.Expr)
    let claims ← IO.mkRef (#[] : Array String)
    let witnesses ← IO.mkRef (#[] : Array String)
    let sorryCache ← IO.mkRef ({} : Std.HashMap Lean.Expr (Nat × Nat))
    let mut holes := 0
    let mut synthetic := 0
    while fuel > 0 do
      fuel := fuel - 1
      match queue with
      | [] => fuel := 0
      | n :: rest =>
        queue := rest
        unless visited.contains n do
          visited := visited.insert n
          match env.find? n >>= arena_route_value with
          | none => pure ()
          | some v =>
            arena_route_walk seen claims witnesses v
            let (h, y) ← arena_route_sorries sorryCache v
            holes := holes + h
            synthetic := synthetic + y
            for c in v.getUsedConstants do
              if follow c then queue := c :: queue
              else used := used.insert c
    let statement : Std.HashSet Lean.Name := mainInfo.type.getUsedConstants.foldl (fun s c => s.insert c) {}
    let mut recursion : Array String := #[]
    let mut lemmas : Array String := #[]
    let mut logic : Array String := #[]
    let principle (s : String) : Bool :=
      ["induction", "induction_on", "rec_on", "recOn", "RecOn", "inductionOn", "induct", "strongRecOn",
       "strong_induction_on", "strongInductionOn", "le_induction", "span_induction"].any (fun p => s == p || s.endsWith ("_" ++ p))
    for c in used.toList do
      let s := lastPart c
      let owner := c.getPrefix.toString
      let mut isLogic := true
      if contra.contains c then logic := logic.push "contra"
      else if orElim.contains c then logic := logic.push "or"
      else if c == ``Trans.trans then logic := logic.push "calc"
      else if c == ``funext || c == ``propext || s == "ext" then logic := logic.push "ext"
      else isLogic := false
      let info := env.find? c
      match info with
      | some (.recInfo _) =>
        unless basic.contains owner do recursion := recursion.push s!"rec:{owner}"
      | _ =>
        let reflected := match c.getPrefix with
          | .str _ x => x == "brecOn" || x == "binductionOn" || x.startsWith "brecOn_"
          | _ => false
        if reflected then
          unless basic.contains c.getPrefix.getPrefix.toString do recursion := recursion.push s!"rec:{c.getPrefix.getPrefix}"
        else if ["brecOn", "binductionOn", "recOn"].contains s || s.startsWith "brecOn_" || s.startsWith "binductionOn_" then
          unless basic.contains owner do recursion := recursion.push s!"rec:{owner}"
        else if c == ``WellFounded.fix || c == ``WellFounded.fixF || c == ``WellFounded.induction then
          recursion := recursion.push s!"wf:{c}"
        else if principle s then recursion := recursion.push s!"ind:{c}"
        else if isLogic || s == "below" || s == "ibelow" || c.isInternal then pure ()
        else if statement.contains c || Lean.Meta.isInstanceCore env c || env.isProjectionFn c then pure ()
        else
          match info with
          | some (.inductInfo _) | some (.quotInfo _) => pure ()
          | some (.ctorInfo v) => unless isCore v.induct do lemmas := lemmas.push c.toString
          | _ =>
            unless s == "casesOn" && basic.contains owner do lemmas := lemmas.push c.toString
    logic := logic ++ (← witnesses.get)
    let sorted (a : Array String) : Lean.Json := Lean.Json.arr ((a.toList.eraseDups.toArray.qsort (· < ·)).take 600 |>.map Lean.Json.str)
    let sorryUsed := used.contains ``sorryAx
    -- `ok`: a complete proof; `read`: the term exists (a failed tactic leaves a synthetic `sorry`, so errored attempts are readable)
    fields := fields ++ [("ok", Lean.Json.bool (!hadErrors && failure.isNone && !sorryUsed)), ("read", Lean.Json.bool true),
      ("errored", Lean.Json.bool (hadErrors || failure.isSome)), ("holes", Lean.toJson holes), ("synthetic", Lean.toJson synthetic),
      ("main", Lean.Json.str mainName.toString), ("recursion", sorted recursion), ("lemmas", sorted lemmas),
      ("claims", sorted (← claims.get)), ("logic", sorted logic), ("aux", Lean.toJson (visited.size - 1))]
    if hadErrors || failure.isSome || sorryUsed then
      fields := fields ++ [("error", Lean.Json.str (failure.getD (if sorryUsed then "sorry" else "elaboration error")))]
  let finished ← IO.monoMsNow
  fields := fields ++ [("extract_ms", Lean.toJson (finished - started))]
  modify fun s => { s with messages := messagesBefore }
  setEnv envBefore
  logInfo m!"ARENA_ROUTE {(Lean.Json.mkObj fields).compress}"
