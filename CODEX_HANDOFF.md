# Codex Handoff — Lean Refactor Arena + Pi Harness

**Repo:** `/mnt/SharedDrive/ActiveProjects/lean-refactor-pi`  
**Branch:** `main`  
**Date:** 2026-10-03  
**Primary goal:** build a robust, Pi-native harness for the Lean Refactor Arena, starting from a verified P0 baseline and scaling from the 15 warm-up problems to the full benchmark.

---

## 0. How to use this handoff

This is the continuity document for a new Codex session. Do **not** reconstruct the project from scratch or repeat P0 unless a claim below is explicitly marked provisional.

Start by reading this file fully, inspecting the actual repository state, making the initial atomic commits, then beginning H1 from the architecture and constraints below. Treat the seven corrections in §8 as requirements.

Do not ask the user to repeat details already recorded here.

---

# 1. Project mission

We are building a competition harness around **Pi** for the **Lean Refactor Arena**.

The Arena task is proof optimization. Each benchmark theorem has a fixed statement and reference proof. A candidate is scored on three axes:

1. proof-length reduction
2. heartbeat reduction
3. zero-shot compatibility / transfer across all listed toolchains

The combined score is the mean of those axes. Invalid, rejected, statement-changing, or uncompilable proofs score zero for that theorem.

The current public warm-up has **15 problems across 5 corpora**:

- Strata
- PhysLib
- CSLib
- ArkLib
- PutnamBench

The eventual benchmark will contain many more. Therefore the harness must be **data-driven by benchmark rows and environment fingerprints**, not hard-coded per theorem.

---

# 2. Working philosophy / non-negotiables

## Context engineering is the primary lever

Prefer exact local Lean context at the moment of reasoning:

- actual goals
- actual diagnostics
- exact local declarations
- exact benchmark metadata
- compact evaluation feedback

Do not jump prematurely to generic RAG, multi-agent orchestration, embeddings, large attempt-memory systems, or a custom planner.

## Reuse before inventing

Existing pieces already in play:

- Pi
- `lean-lsp-mcp`
- `lean4-skills`
- upstream Lean Refactor proof utilities
- Arena Space/scoring source where available
- Langfuse Pi integration

Reuse pinned upstream functionality when it is authoritative.

## Tooling preferences

- Use `uv` / `uv run` / `uvx`.
- Do **not** introduce `pipx`.
- Avoid bare `python3` in user-facing commands; use `uv run --no-project python ...`.
- Ubuntu/Linux environment.
- Prefer meaningful implementation jumps over endless tiny scaffolding steps.

## P0 interpretation

P0 showed the model can do the Lean/proof reasoning. Most serious failures were in the **harness/interface**, not reasoning capability.

The next custom component should therefore be a deterministic evaluation + Pi interface boundary, not a smarter planner.

---

# 3. Current repository state

Last observed `git status`:

```text
On branch main

No commits yet

Changes to be committed:
        new file:   .gitmodules
        new file:   vendor/arena-space
        new file:   vendor/lean-refactor
        new file:   vendor/lean4-skills

Untracked files:
        .gitignore
        .pi/
        benchmark/
        docs/
        tools/
```

Pinned submodules:

```text
vendor/arena-space    d9e46ee13c822925fb3031b0a0eac53b51631198
vendor/lean-refactor  9c98a3a097e53724e35b2a2e7fe316c331efa20a
vendor/lean4-skills   b6243b85b9b0a0ddff5bb6773889044daf687f8e
```

Pi:

```text
1.0.0
```

Lean LSP MCP:

```text
lean-lsp-mcp 0.31.0
```

## First repo checkpoint

Before architecture changes, make targeted atomic commits:

1. repo bootstrap + pinned submodules + `.gitignore`
2. benchmark snapshot
3. P0 validation tooling/docs
4. `.pi` only after confirming it is portable and contains no absolute local paths/secrets

Do not commit `runs/`, `workspaces/`, `.bak`, caches, or generated scratch artifacts.

---

# 4. Pi / Lean setup already proven

Pi ↔ `lean-lsp-mcp` worked with 18 tools. Important direct tools included:

```text
lean_diagnostic_messages
lean_goal
lean_local_search
lean_multi_attempt
```

The P0 smoke test proved actual local Lean use:

- diagnostics worked with absolute paths
- local search found `Core.UpdateStatesDefined`
- hover returned its elaborated type
- `lean_multi_attempt` worked in memory
- no remote LeanSearch / Lean Finder / Loogle / Hammer was used

Important observed quirks:

- relative paths failed for diagnostics; absolute paths worked
- local search saw scratch `.lean` files inside the project
- hover is column-sensitive
- `lean_multi_attempt` must be interpreted using both diagnostics and goal state
- instrumentation files in worktrees contaminate retrieval

Future harness design should prevent these by construction.

---

# 5. Exact P0 benchmark target

Target:

```text
Core.InitsUpdatesComm
```

Benchmark metadata:

```text
source: strata
file: Strata/Languages/Core/StatementSemanticsProps.lean
reference proof tokens: 224
published heartbeat reference: 4251
```

Toolchains / commits:

```text
v4.29.1 -> 384e22374e0872095ad9c6f74c5998c09cfd93a9
v4.27.0 -> 4348c65a93a3b57b1a4541991ed2d2fcdd9fa35d
v4.26.0 -> 451e5f047bafa010d178856db76c00029bfa4d7f
```

Local worktrees:

```text
workspaces/strata-v4.29.1
workspaces/strata-v4.27.0
workspaces/strata-v4.26.0
```

The exact benchmark theorem source was verified byte-identical in all three.

A full Strata `lake build` is not a useful P0 gate. It failed late during native C generation due to compiler bracket nesting. Target `.olean` / direct Lean compilation succeeded.

The reference theorem compiled across all three versions. v4.26 has four unrelated pre-existing `sorry` warnings later in the source file.

---

# 6. P0 baseline run and proof result

Baseline used:

- fresh Pi session
- generic `lean4` skill
- `lean-lsp-mcp`
- exact Strata v4.29.1 project
- no custom Arena skill
- no RAG
- no planner
- no multi-agent system
- no heartbeat feedback in the first optimization prompt
- basic length checker + Arena forbidden wrapper

Langfuse identified the model only as:

```text
providedModelName: space-bunny-free
provider: opencode-go
```

Do not infer the hidden underlying model identity.

Length progression:

```text
224 -> 159 -> 127 -> 124
```

The 124-token proof was shortest locally but failed Lean v4.26 compatibility.

## Transfer-safe 126-token proof

```lean
theorem InitsUpdatesComm
  {P : PureExpr} {σ σ' σ'' : SemanticStore P}
  {ks ks' : List P.Ident} {vs vs' : List P.Expr} :
  UpdateStates σ ks vs σ' →
  InitStates σ' ks' vs' σ'' →
  ∃ σ₁,
    σ₁ = (updatedStates σ ks' vs') ∧
    InitStates σ ks' vs' σ₁ ∧
    UpdateStates σ₁ ks vs σ'' := by
  intros Hup Hinit
  induction Hup generalizing σ'' with
  | update_none =>
    exact Exists.intro σ'' ⟨InitStatesUpdated Hinit, Hinit, UpdateStates.update_none⟩
  | update_some Hup Hups ih =>
    have Hnd := UpdateStateNotDefMonotone'
      (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup
    have Hinits := updatedStatesInit (InitStatesLength Hinit) Hnd (InitStatesNodup Hinit)
    obtain ⟨_, rfl, _, htail⟩ := ih Hinit
    refine ⟨_, rfl, Hinits, ?_⟩
    refine UpdateStates.update_some ?_ htail
    simp only [updatedStates, UpdateStateUpdated Hup]
    cases Hup with
    | update Hold _ _ =>
      have hzip := List.unzip_zip (InitStatesLength Hinit)
      rw [← updatedStateComm' (by grind [isNotDefined])]
      exact updatedStateUpdate (InitStatesSomeMonotone Hold Hinits)
```

Exact token count:

```text
126
```

Compatibility:

```text
v4.29.1 PASS
v4.27.0 PASS
v4.26.0 PASS
```

The 124-token proof used:

```lean
grind [List.unzip_zip (InitStatesLength Hinit), isNotDefined]
```

and v4.26 rejected the applied theorem term syntax:

```text
unexpected token '('; expected ']'
```

The two-token repair introduced a local `hzip`, which old `grind` consumes automatically.

---

# 7. Heartbeat state — PROVISIONAL / unresolved

This is the largest open correctness issue before trusting H1 scoring.

Published Arena heartbeat reference:

```text
4251
```

Current local measurement of the unchanged reference:

```text
4399
4399
4399
```

Current local measurement of the 126-token candidate:

```text
578
578
578
```

Current local proxy calculation:

```text
tokens                  126
length reduction        43.750%
local heartbeats        578
local HB reduction      86.861%
compatibility           100.000% (3/3)
local combined proxy    76.870%
```

**Do not treat 76.870% as validated Arena score.**

The local reference 4399 is about 3.5% above the published 4251. Before heartbeat/scoring becomes authoritative, investigate why.

Current local measurement method used a custom command elaborator around the target declaration with approximately:

```text
IO.getNumHeartbeats delta / 1000
Elab.async false
maxHeartbeats 0
```

A profiler-based attempt produced ~6040 and was rejected as the wrong measurement mechanism.

Investigation candidates:

- exactly what the official worker wraps
- option differences
- async behavior
- in-place vs isolated/prefix-only compilation
- instrumentation import/environment perturbation
- which version produced the published denominator
- whether pinned Arena source contains actual worker/scorer logic

**Reuse-first applies here.** If the actual official scorer/evaluator exists in pinned upstream code, port or call it instead of duplicating `heartbeat.py` / `scoring.py`.

## Mandatory server calibration

Before H1 heartbeat/scoring is considered correct:

1. submit the 126-token proof to the real Arena
2. obtain the official per-problem result
3. compare official heartbeat and combined score with local evaluation
4. document the discrepancy or demonstrate equivalence

Local-only tests cannot prove the heartbeat denominator is correct.

---

# 8. Seven architecture corrections — REQUIREMENTS

These are the latest corrections and should drive the build.

## 8.1 Calibrate heartbeat/scoring to the actual Arena

Do not trust `4399` as official.

Investigate `4251` vs `4399` first. Reuse official/pinned evaluator or scorer logic if it exists.

H1 must include a real server comparison using the 126-token proof.

## 8.2 `arena_evaluate` must be tiered

Do **not** run all compatibility versions on every candidate.

Fast default path:

```text
candidate
  -> forbidden/statement checks
  -> primary compile
  -> primary heartbeat
```

Run all compatibility versions only when:

- candidate beats the relevant current primary/scalar threshold
- model explicitly requests full transfer evaluation
- final/promotion validation is required

Expose this intentionally, e.g.:

```text
arena_evaluate(proof, mode="fast")
arena_evaluate(proof, mode="full")
```

Broken exploratory attempts should not wait for all toolchains.

## 8.3 Do not assume many concurrent SDK sessions in one Node process

Pi SDK concurrency safety has not been established.

Keep mutable target state inside:

- extension factory/session closure, and/or
- session-scoped entries

Never store the active problem in mutable module-global state.

For benchmark parallelism use:

```text
one Pi session per OS process
+ bounded worker pool
```

This gives crash isolation, resumability, and clear resource ownership.

## 8.4 Workspaces must be read-only to the agent

Immutable Git-source reconstruction protects evaluation, but `lean-lsp-mcp` still reads the worktree.

If the model edits a workspace file, goals/diagnostics/search silently become wrong.

Add a Pi `tool_call` guard that blocks:

- edit/write operations under `workspaces/`
- bash redirections or mutation under `workspaces/`
- destructive git operations there
- model-created `.lean` instrumentation in workspaces

Give every problem/session a separate writable scratch directory.

Workspaces are read-only semantic context.

## 8.5 Parallelism is memory-bounded

Each active problem can load its own Lean server/project/Mathlib environment and consume several GB.

Worker-pool size must be based on measured RAM/RSS, not CPU count alone.

Start conservatively and measure.

## 8.6 Scalar combined score promotes; frontier supplies mutation seeds

The competition score is specified, so the **combined scalar score** controls submission-incumbent promotion after full compatibility validation.

The frontier remains useful as a mutation-seed pool.

Example:

```text
124 tokens / 2 of 3 compatible:
  useful seed
  not submission incumbent

126 tokens / 3 of 3 compatible:
  transfer-safe seed
  currently strong local proxy
```

Remove "retain Pareto candidates" instructions from the model skill. The evaluator manages frontier state; the model receives compact frontier summaries/seeds.

## 8.7 H4 must include Track 1 observability and cost enforcement

For SDK workers:

- explicitly load Langfuse into SDK sessions; do not assume interactive plugin discovery carries over
- account usage per theorem
- enforce a `turn_end` or equivalent cost guard
- stop around **$2.50/problem** to leave margin under the **$3/problem** Track 1 cap

The final harness must be able to emit per-problem cost accounting.

---

# 9. Revised Pi-native architecture

A Python CLI is useful as a developer/CI/reproduction surface, but it should **not** be the model-facing harness API.

Recommended architecture:

```text
                            Lean Refactor Arena
                                     |
                     +---------------+---------------+
                     |                               |
               interactive `pi`                 batch workers
                     |                         one OS process/problem
                     |                               |
                     +---------------+---------------+
                                     |
                              Arena Pi Package
                                     |
              +----------------------+----------------------+
              |                      |                      |
          Extension              Arena Skill              Prompt
      executable/state         strategy only          kickoff only
              |
              +---- dynamic primary `lean-lsp-mcp`
              |
              +---- evaluator engine
              |       |
              |       +-- fast primary validation
              |       +-- heartbeat/scoring
              |       +-- full compatibility when required
              |
              +---- frontier/session state
              |
              +---- workspace write guards
```

## Pi package

Likely shape:

```text
packages/arena-pi/
  package.json
  extensions/
    arena.ts
  skills/
    lean-refactor-arena/
      SKILL.md
  prompts/
    arena-optimize.md
```

Use the vendored generic `lean4` skill for Lean reasoning. The Arena skill should only teach benchmark strategy and evaluator workflow.

## Extension responsibilities

The extension is the primary Pi-facing harness layer. It owns:

- active problem selection
- session-local target state
- dynamic Lean MCP registration for the primary environment
- Arena evaluator tools
- frontier access
- workspace write guards
- scratch-directory allocation
- later cost/observability hooks

Keep the model-facing API small, likely:

```text
arena_target()
arena_evaluate(proof, mode="fast"|"full")
arena_frontier()
```

## MCP

Continue using `lean-lsp-mcp` as MCP.

Do not turn our Arena evaluator into another MCP server by default. A direct extension-to-engine call is simpler. Add an Arena MCP only if cross-host portability becomes an explicit goal.

---

# 10. Environment model for 15+ problems

Do not create one setup per theorem.

Environment identity should derive from benchmark metadata, approximately:

```text
(source, repo URL, Lean/toolchain version, source commit)
```

Problems should reuse matching environments.

Likely broad environment providers:

```text
ProjectEnvironment
  - Strata
  - PhysLib
  - CSLib
  - ArkLib
  - future repo-resident corpora

StandaloneMathlibEnvironment
  - PutnamBench
  - similar standalone rows
```

Only add corpus-specific adapters if actual setup differences require them.

An environment manager should eventually expose concepts like:

```text
ensure(problem, version)
resolve_primary(problem)
resolve_compat(problem)
```

Avoid full builds by default. Build only what is needed for Lean/LSP/evaluation readiness.

---

# 11. Source integrity model

The evaluator must not trust a possibly mutated worktree as the scoring source.

Prefer immutable pinned source, conceptually:

```text
git show <commit>:<file_path>
```

Then evaluation source is constructed from:

```text
immutable upstream prefix
+ candidate theorem
```

This makes context integrity true by construction.

Separately, workspace write guards are still necessary because Lean LSP reads worktree files for goals/diagnostics/search.

---

# 12. H1 — revised build target

H1 is **not** "write a Python CLI."

H1 is:

> deterministic evaluator engine + Pi-facing extension boundary, proven on the P0 fixtures, with heartbeat discrepancy investigated before heartbeat scoring is declared authoritative.

A CLI can exist as a debug/CI/reproduction adapter.

## Fast evaluation

```text
candidate
  -> forbidden gate
  -> exact statement validation
  -> immutable-source reconstruction
  -> exact token count
  -> primary compile
  -> primary heartbeat
  -> structured result
```

## Full evaluation

```text
fast path
  -> all compatibility toolchains
  -> combined scalar score
  -> evaluator-managed frontier update
  -> submission-incumbent decision
```

## Promotion

Do not promote on proof length alone.

Submission incumbent requires full validation and is chosen by combined scalar score.

Frontier entries are alternate mutation seeds.

---

# 13. H1 fixtures / expected facts

These are the integration fixtures already established manually.

## Reference

```text
name: Core.InitsUpdatesComm
tokens: 224
published heartbeat: 4251
current local heartbeat: 4399 (PROVISIONAL)
compatibility: 3/3
```

## Shortest local seed

```text
tokens: 124
compatibility:
  v4.29.1 pass
  v4.27.0 pass
  v4.26.0 fail
reason:
  applied term syntax inside grind [...] rejected by older parser
```

This belongs in frontier state only.

## Transfer-safe seed

```text
tokens: 126
compatibility: 3/3
current local heartbeat: 578 (PROVISIONAL scheme)
current local combined proxy: 76.870% (NOT official)
```

## Harness/security regressions

Tests should memorialize these P0 failures:

```text
wrong candidate/temp path -> fail closed
FILE_MODIFIED -> hard failure
STATEMENT_MODIFIED -> hard failure
INCOMPLETE_PROOF -> hard failure
forbidden constructs rejected before Lean
Lean subprocess nonzero never hidden by tee/pipelines
candidate evaluation never mutates worktrees
scratch files never pollute local search
workspace write attempts from Pi are blocked
```

---

# 14. P0 harness bugs discovered

## Wrong candidate path

The model accidentally invoked the checker with:

```text
--temp-file-path "tools/arena_check.py"
```

The old flow could therefore bypass the file-integrity comparison.

A later wrapper guard rejected paths that did not match the expected Lean candidate naming convention.

## Upstream checker fail-open behavior

`check_proof.py` may print rejection markers such as:

```text
FILE_MODIFIED:
STATEMENT_MODIFIED:
```

and still exit `0` because it is designed as an interactive agent helper.

Do not treat its process exit code as an authoritative internal API.

## Pipeline false success

A failing Lean command piped to `tee` appeared to return success because `$?` referred to `tee`.

The evaluator must use structured subprocess return codes, not shell-pipeline status parsing.

## Dirty worktree

The model's working temp file had edits outside the target theorem. Rebuilding from pristine source + candidate isolated the proof correctly.

Future evaluator should construct files itself.

## Compatibility discovered too late

The 124-token local optimum passed primary/newer versions and failed 4.26. This motivates tiered evaluation plus full validation before promotion.

---

# 15. Langfuse / baseline trace findings

A complete Langfuse JSONL export was inspected in the previous session:

```text
exports_1791010087173-lf-events-export-local-project.jsonl
```

It may not be present in the Codex repo unless copied there.

Key findings:

- optimization became overwhelmingly bash-driven
- only one direct `lean_diagnostic_messages` call was observed during the optimization phase
- little/no optimization-time use of `lean_goal`, `lean_local_search`, or `lean_multi_attempt`
- the model built `/tmp` compile/repair loops itself
- context grew very large

This supports exposing one deterministic evaluator operation instead of forcing the model to reinvent shell plumbing.

Do not conclude MCP is useless. P0 proved MCP worked; the current interface simply incentivized bash orchestration.

---

# 16. Do NOT build yet

Until multi-problem traces justify them, do not build:

- generic RAG
- embeddings/vector DB
- custom theorem-search service
- multi-agent planner
- subagent swarm
- elaborate attempt-memory system
- research-grade context compiler
- local Loogle
- remote theorem search by default
- Arena MCP merely because MCP exists

First custom system: deterministic evaluator + Pi extension boundary.

---

# 17. H2 / H3 / H4 direction

## H2 — Pi package integration

Target UX:

```text
/arena Core.InitsUpdatesComm
```

Extension resolves the primary environment and dynamically binds Lean MCP.

Expose approximately:

```text
arena_target
arena_evaluate
arena_frontier
```

Arena skill teaches workflow, not plumbing.

## H3 — all warm-up environments

Provision all unique environments required by the 15 warm-up rows.

Run a reference self-check across all 15:

- token calibration
- primary compile
- heartbeat investigation/calibration
- every listed compatibility toolchain

This becomes the harness certification suite.

## H4 — batch baseline

Use Pi SDK with **one session per OS process**, bounded worker pool.

Each theorem gets a fresh context.

Explicitly load:

- Arena package
- generic Lean skill
- Langfuse integration/resources

Enforce approximately `$2.50/problem` stop budget.

Run the untouched baseline across all 15 before adding more context-engineering machinery.

---

# 18. Immediate Codex start sequence

Proceed in this order:

```text
A. inspect repo and make atomic initial commits
B. inspect vendor/arena-space and vendor/lean-refactor for reusable official scorer/evaluator code
C. investigate heartbeat 4251 vs 4399 before declaring local heartbeat authoritative
D. design tiered fast/full evaluator API
E. implement immutable-source candidate reconstruction
F. implement structured subprocess evaluation
G. implement evaluator-managed frontier + scalar promotion
H. add Pi extension skeleton with session-local state and workspace write guard
I. keep CLI only as debug/CI/reproduction adapter
J. prove H1 against the 224 / 124 / 126 P0 fixtures
K. submit the 126 candidate to the real Arena and compare official result
```

Do not jump to H2/H3 before H1 evaluation semantics are trustworthy.

---

# 19. Suggested Codex kickoff prompt

```text
Read CODEX_HANDOFF.md completely and treat it as the project continuity source.

We have completed P0 for the Lean Refactor Arena + Pi project. Do not redo the
baseline experiment. Start from the actual repository state.

First inspect git status and the pinned vendor repos, then make the targeted
atomic initial commits described in the handoff before changing architecture.

After the checkpoint, begin H1.

Critical priorities:
1. Investigate the published heartbeat 4251 vs deterministic local 4399 gap.
   Reuse official/pinned scorer/evaluator code if it exists; do not silently
   invent a second scoring implementation.
2. Design candidate evaluation as tiered fast/full evaluation.
3. Construct candidate files from immutable pinned Git source, never trusting a
   writable worktree as the scoring source.
4. Build the Pi-facing architecture around a native extension/package; a Python
   CLI is only a debug/CI/reproduction adapter.
5. Keep active problem state session-local. Do not assume many concurrent Pi SDK
   sessions are safe inside one Node process.
6. Add a Pi tool-call guard that makes workspaces read-only to the model and
   supplies a separate scratch directory.
7. Scalar combined score controls promotion after full compatibility validation.
   Frontier candidates are mutation seeds managed by the evaluator.
8. Preserve Langfuse in eventual SDK workers and plan a ~$2.50/problem cost stop.

Use uv/uvx for Python tooling. Do not use pipx.

Make meaningful implementation jumps, but keep every claim about heartbeat,
Pi concurrency, and server scoring evidence-backed.
```

---

# 20. Bottom line

P0 succeeded.

We have evidence that:

- plain Pi + generic Lean tooling can find a materially better proof
- the model can discover strong proof restructurings without a custom Arena skill
- the current evaluator/interface is the weak point
- multi-version compatibility matters
- exact local Lean context matters
- shell orchestration creates avoidable correctness hazards
- the next custom component should be a deterministic, Pi-native evaluation boundary

The biggest unresolved correctness question is **heartbeat equivalence with the real Arena worker**.

Resolve that before treating local combined scores as authoritative.
