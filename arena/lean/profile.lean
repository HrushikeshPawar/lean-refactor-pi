open Lean Elab Tactic in
elab "arena_hb_tac " line:num col:num depth:num endLine:num seq:tacticSeq : tactic => do
  let t0 ← IO.getNumHeartbeats
  try
    evalTactic seq
  finally
    let t1 ← IO.getNumHeartbeats
    logInfo m!"ARENA_PROFILE {line.getNat} {col.getNat} {depth.getNat} {endLine.getNat} {(t1 - t0) / 1000}"

open Lean Elab Command in
elab "arena_profile_heartbeats " cmd:command : command => do
  let fm ← getFileMap
  let maxDepth := @@MAX_DEPTH@@
  let rec wrap : Nat → Nat → Syntax → CommandElabM Syntax
    | 0, _, stx => pure stx
    | fuel + 1, depth, stx => do
      match stx with
      | .node info kind args =>
        let isSeq := kind == ``Lean.Parser.Tactic.tacticSeq1Indented ||
          kind == ``Lean.Parser.Tactic.tacticSeqBracketed
        let mut out : Array Syntax := #[]
        for arg in args do
          match arg with
          | .node ninfo `null items =>
            if isSeq then
              let mut newItems : Array Syntax := #[]
              let mut i := 0
              for item in items do
                if i % 2 == 0 then
                  let inner ← wrap fuel (depth + 1) item
                  match item.getPos?, item.getTailPos? with
                  | some p, some q =>
                    if depth <= maxDepth then
                      let l := (fm.toPosition p).line
                      let c := (fm.toPosition p).column
                      let e := (fm.toPosition q).line
                      let seq ← `(Lean.Parser.Tactic.tacticSeq| $(⟨inner⟩):tactic)
                      newItems := newItems.push (← `(tactic| arena_hb_tac $(Syntax.mkNumLit (toString l)) $(Syntax.mkNumLit (toString c)) $(Syntax.mkNumLit (toString depth)) $(Syntax.mkNumLit (toString e)) $seq))
                    else newItems := newItems.push inner
                  | _, _ => newItems := newItems.push inner
                else newItems := newItems.push item
                i := i + 1
              out := out.push (.node ninfo `null newItems)
            else out := out.push (← wrap fuel depth arg)
          | other => out := out.push (← wrap fuel depth other)
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
