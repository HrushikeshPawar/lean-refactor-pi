open Lean Elab Tactic in
elab "arena_hb_tac " line:num col:num depth:num endLine:num endCol:num seq:tacticSeq : tactic => do
  let t0 ← IO.getNumHeartbeats
  try
    evalTactic seq
  finally
    let t1 ← IO.getNumHeartbeats
    logInfo m!"ARENA_PROFILE {line.getNat} {col.getNat} {depth.getNat} {endLine.getNat} {endCol.getNat} tactic {(t1 - t0) / 1000}"

-- A conv tactic (inside `conv_lhs => ...`, `conv => ...`, `{ ... }`): same record as `arena_hb_tac`.
open Lean Elab Tactic in
elab "arena_hb_conv " line:num col:num depth:num endLine:num endCol:num seq:Lean.Parser.Tactic.Conv.convSeq : conv => do
  let t0 ← IO.getNumHeartbeats
  try
    evalTactic seq
  finally
    let t1 ← IO.getNumHeartbeats
    logInfo m!"ARENA_PROFILE {line.getNat} {col.getNat} {depth.getNat} {endLine.getNat} {endCol.getNat} tactic {(t1 - t0) / 1000}"

-- A stated term (a chained relation's right side, a `show` or local declaration type): the heartbeats spent
-- elaborating it where it stands. Work Lean postpones past this point is booked where it finally runs.
open Lean Elab Term in
elab "arena_hb_term " line:num col:num depth:num endLine:num endCol:num e:term : term => do
  let t0 ← IO.getNumHeartbeats
  try
    elabTerm e none
  finally
    let t1 ← IO.getNumHeartbeats
    logInfo m!"ARENA_PROFILE {line.getNat} {col.getNat} {depth.getNat} {endLine.getNat} {endCol.getNat} term {(t1 - t0) / 1000}"

open Lean Elab Command in
elab "arena_profile_heartbeats " cmd:command : command => do
  let fm ← getFileMap
  let maxDepth := @@MAX_DEPTH@@
  let place (stx : Lean.Syntax) : Option (Nat × Nat × Nat × Nat) :=
    match stx.getPos?, stx.getTailPos? with
    | some p, some q => some ((fm.toPosition p).line, (fm.toPosition p).column, (fm.toPosition q).line, (fm.toPosition q).column)
    | _, _ => none
  let lit (k : Nat) : Lean.Syntax := Syntax.mkNumLit (toString k)
  -- Wrap a term in `arena_hb_term`, keeping the original's place for the record.
  let termWrap (orig inner : Lean.Syntax) (depth : Nat) : CommandElabM Lean.Syntax := do
    match place orig with
    | some (l, c, e, ec) =>
      if depth <= maxDepth then
        `(term| (arena_hb_term $(⟨lit l⟩) $(⟨lit c⟩) $(⟨lit depth⟩) $(⟨lit e⟩) $(⟨lit ec⟩) $(⟨inner⟩)))
      else pure inner
    | none => pure inner
  let rec wrap : Nat → Nat → Lean.Syntax → CommandElabM Lean.Syntax
    | 0, _, stx => pure stx
    | fuel + 1, depth, stx => do
      match stx with
      | .node info kind args =>
        let isSeq := kind == ``Lean.Parser.Tactic.tacticSeq1Indented ||
          kind == ``Lean.Parser.Tactic.tacticSeqBracketed
        let isConvSeq := kind == ``Lean.Parser.Tactic.Conv.convSeq1Indented ||
          kind == ``Lean.Parser.Tactic.Conv.convSeqBracketed
        let mut out : Array Lean.Syntax := #[]
        for arg in args do
          match arg with
          | .node ninfo `null items =>
            if isSeq || isConvSeq then
              let mut newItems : Array Lean.Syntax := #[]
              let mut i := 0
              for item in items do
                if i % 2 == 0 then
                  let inner ← wrap fuel (depth + 1) item
                  match place item with
                  | some (l, c, e, ec) =>
                    if depth <= maxDepth then
                      if isConvSeq then
                        let seq ← `(Lean.Parser.Tactic.Conv.convSeq| $(⟨inner⟩):conv)
                        newItems := newItems.push (← `(conv| arena_hb_conv $(⟨lit l⟩) $(⟨lit c⟩) $(⟨lit depth⟩) $(⟨lit e⟩) $(⟨lit ec⟩) $seq))
                      else
                        let seq ← `(Lean.Parser.Tactic.tacticSeq| $(⟨inner⟩):tactic)
                        newItems := newItems.push (← `(tactic| arena_hb_tac $(⟨lit l⟩) $(⟨lit c⟩) $(⟨lit depth⟩) $(⟨lit e⟩) $(⟨lit ec⟩) $seq))
                    else newItems := newItems.push inner
                  | none => newItems := newItems.push inner
                else newItems := newItems.push item
                i := i + 1
              out := out.push (.node ninfo `null newItems)
            else out := out.push (← wrap fuel depth arg)
          | other => out := out.push (← wrap fuel depth other)
        -- Stated terms: a chained relation's right side, a `show` type, a local declaration's type.
        if (kind == `Lean.calcStep || kind == `Lean.calcFirstStep) && args.size > 0 then
          match args[0]!, out[0]! with
          | .node _ _ rel, .node ri rk rel' =>
            if rel.size == 3 && rel'.size == 3 then
              out := out.set! 0 (.node ri rk (rel'.set! 2 (← termWrap rel[2]! rel'[2]! depth)))
          | _, _ => pure ()
        else if kind == `Lean.Parser.Term.show && args.size > 1 then
          out := out.set! 1 (← termWrap args[1]! out[1]! depth)
        else if (kind == `Lean.Parser.Term.letIdDecl || kind == `Lean.Parser.Term.haveIdDecl) && args.size > 2 then
          match args[2]!, out[2]! with
          | .node _ `null spec, .node si sk spec' =>
            if spec.size == 1 then
              match spec[0]!, spec'[0]! with
              | .node _ _ ts, .node ti tk ts' =>
                if ts.size == 2 && ts'.size == 2 then
                  out := out.set! 2 (.node si sk #[.node ti tk (ts'.set! 1 (← termWrap ts[1]! ts'[1]! depth))])
              | _, _ => pure ()
          | _, _ => pure ()
        return .node info kind out
      | other => return other
  let rewritten ← wrap 400 0 cmd.raw
  let t0 ← IO.getNumHeartbeats
  try
    elabCommand (← `(command|
      set_option Elab.async false in
      set_option maxHeartbeats 0 in
      $(⟨rewritten⟩):command))
  finally
    let t1 ← IO.getNumHeartbeats
    logInfo m!"ARENA_PROFILE_TOTAL {(t1 - t0) / 1000}"

arena_profile_heartbeats
