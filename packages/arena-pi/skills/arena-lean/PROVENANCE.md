# Provenance

`SKILL.md` is written for the Arena. Files in `references/` are copied verbatim from the vendored lean4 skill at commit `b6243b85b9b0a0ddff5bb6773889044daf687f8e`:

- proof-golfing.md
- proof-golfing-patterns.md
- proof-simplification.md
- performance-optimization.md
- profiling-workflows.md
- tactics-reference.md
- tactic-patterns.md
- simp-reference.md
- grind-tactic.md
- calc-patterns.md
- compilation-errors.md

Adapted for the Arena (the model has no shell, no `lake build`, and only five Lean tools):

- lean-lsp-server.md: rewritten to describe only the Lean tools the harness exposes.
- performance-optimization.md: the profiling sections use `arena_profile` instead of `lean_profile_proof`.
