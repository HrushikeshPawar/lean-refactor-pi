---
name: arena-lean
description: Lean 4 proof optimization for the Lean Refactor Arena. Use for every Arena theorem - shorten a proof, cut elaboration heartbeats, and keep it compiling on every listed toolchain version.
license: MIT
---

# Arena Lean: optimize an existing proof

You receive a theorem with a working reference proof. Your job is a replacement proof that scores higher
while keeping the statement byte-exact. Scoring is mechanical; trade-offs are yours to judge from numbers.

## Scoring

The score for a problem is the mean of three percentages:

| Axis | Percentage |
|------|------------|
| tokens | `(reference_tokens - tokens) / reference_tokens * 100` |
| heartbeats | `(reference_heartbeats - heartbeats) / reference_heartbeats * 100` |
| compatibility | `versions_that_compile / versions_listed * 100` |

The packet states this problem's exchange rates: how many points one token, 100 heartbeats, or one lost
version is worth. Every evaluation reports each axis's contribution, so compare candidates by their numbers,
not by feel. A fast evaluation checks only the primary toolchain and reports an *estimated* proxy that
assumes the other versions pass; only a full evaluation is a verified score. Heartbeats are measured with
`maxHeartbeats 0`, so a slow proof is never rejected for time, only scored lower.

### Token counting

Tokens are counted on the proof after the statement, with comments and attributes removed. An identifier or
number (letters, digits, `.`, `_`, `'`) is one token. Every other non-space character is its own token, except
these operators which count once: `:=  !=  &&  -.  ->  ←  ..  ...  ::  :>  <;>  ;;  ==  ||  =>  <=  >=  ⁻¹  ?_`.
Whitespace, newlines and indentation are free. Consequences: `exact foo` is two tokens, `⟨a, b⟩` is five,
a `by` block costs the `by`, deleting a line costs nothing, and a long name costs the same as a short one.

### Heartbeats

Elaboration cost is concentrated, not spread evenly. Use `arena_profile` before editing to see which proof
lines or tactic blocks hold the heartbeats and what share of the total they are. After a change, profile again
to see whether cost moved or disappeared. Facts that usually hold:

- Search-style tactics (`simp_all`, `simp at *`, `grind`, `aesop`, `omega`/`decide` over big contexts) cost
  far more than explicit terms and `simp only [...]` with named lemmas.
- Cost scales with context size: clearing or avoiding large hypotheses before an expensive tactic helps.
- A tactic that runs inside `<;>` or a `case` runs once per goal, so its cost multiplies.
- Replacing one expensive tactic with several cheap ones can win heartbeats and lose tokens; the exchange
  rates tell you whether it is worth it.
- Heartbeat counts vary slightly from run to run; treat differences of a few heartbeats as noise.

## Compatibility

A candidate is checked on several Lean/library versions. Older toolchains reject syntax and lemma names that
newer ones accept, and simp normal forms drift between versions. Rules learned the hard way:

- Syntax accepted only by newer toolchains (for example applied terms inside `grind [...]`) fails on older
  ones. If a full check fails on one version, read that version's diagnostics before retrying.
- Prefer long-stable names and tactics; avoid relying on auto-generated hypothesis names.
- A proof that leans on the exact `simp` set may close on one version and leave a different goal on another;
  `simp only [...]` with explicit lemmas is more portable.
- One lost version costs about as many points as dozens of tokens. A candidate is only an improvement once
  the harness reports that it passes every version.

## Statement immutability

The statement and everything before `:=` must stay byte-exact. Forbidden in a submission: `sorry`, `admit`,
`axiom`, `native_decide`, `#eval`, `IO.`, `unsafe`, `macro`/`elab`/`notation`/`syntax`, `attribute`, extra
top-level commands or auxiliary declarations, and anything outside the one theorem. Probing is the only place
`sorry` may appear.

## Tool workflow

1. `arena_idea`: record several structurally different ideas (what you will change, expected effect on each
   axis) before editing. Update an idea's status with a reason when evidence arrives.
2. `arena_probe`: develop a structural rewrite hole by hole. `sorry` is allowed; you get the goal at each
   tactic-position `sorry`. A draft without `sorry` that compiles is recorded and scored as a candidate.
3. `lean_goal` / `lean_multi_attempt` / `lean_diagnostic_messages` on the candidate file the harness
   materializes. Diagnostic `file_line` values refer to exactly that file; `proof_line` counts from the
   statement's first line.
4. `arena_profile` on a compiling candidate or probe to see where heartbeats go.
5. `arena_evaluate` scores a complete proof on the primary version. `candidate: "#N"` re-reads an existing
   node; `from_probe: "pN"` promotes a probe without resending the proof.
6. You never request bookkeeping. The harness checks every compiling candidate on the other versions in the
   background, appends an `[arena]` line to a later tool result when a check finishes or the best candidate
   changes, and submits the best verified candidate when the run ends.

## Working principles

- Search before proving: `lean_local_search` and `arena_declaration` show real signatures. Do not guess names.
- Build incrementally and read the exact goal (`lean_goal`) before changing a failing step.
- Judge ideas by the per-axis numbers they produce. Local polish is cheap to try once a proof's overall
  structure is settled, so spend early effort on the structure.
- Never discard a compiling candidate: restore it with `arena_candidate` instead of retyping it.

## References (read on demand with `arena_skill_read`)

| File | Use |
|------|-----|
| `references/proof-golfing.md`, `references/proof-golfing-patterns.md` | shortening proofs safely |
| `references/proof-simplification.md` | strategy-level simplification |
| `references/performance-optimization.md`, `references/profiling-workflows.md` | heartbeat cost by symptom |
| `references/tactics-reference.md`, `references/tactic-patterns.md` | tactic lookup |
| `references/simp-reference.md`, `references/grind-tactic.md` | simp and grind behaviour |
| `references/calc-patterns.md` | calc chains |
| `references/compilation-errors.md` | error-by-error guidance |
| `references/lean-lsp-server.md` | Lean LSP tool behaviour |
