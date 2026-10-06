# Spec: Arena harness v5 — correct feedback, model-owned ideas, visible costs

Status: implemented and tested offline; acceptance experiment not yet run
Source: analysis of runs P0, luna-blank, luna-source, luna-v2, luna-v3, luna-v4, qwen38-v4 (2026-10-06)

## Problem Statement

We are building a Pi-based harness for the Lean Refactor Arena. Six harness runs on
`Core.InitsUpdatesComm` all scored below a naive, unharnessed Pi session (best harness 66.71
vs naive 76.72 local proxy) while consuming a comparable number of tokens. The analysis showed
the harness itself was the main obstacle:

- Lean diagnostics returned to the model are offset by 14 lines from the shadow file that
  `lean_goal` / `lean_multi_attempt` read, so goal inspection after a failure lands on the
  wrong line (sometimes in the next theorem).
- The idea scheduler forcibly rotates lanes after four development calls and rejects any
  candidate outside the scheduled lane; it rejected a compiling induct-first repair one step
  from success. Ideas were hard-coded (and leaked the known P0 solution) instead of being
  proposed by the model.
- Roughly 20–26% of spend went to protocol bookkeeping and rejected calls (parent rules,
  probe IDs that cannot be restored, unclear `arena_source` errors).
- The model never sees what the score rewards: it hill-climbs tokens (worth ~0.15 pt each)
  while the heartbeat axis (100 HB ≈ 0.78 pt) holds most of the value, and it has no idea
  which tactics are expensive.
- The generic lean4 skill (loaded in the naive run) is disabled by `--no-skills`, thinking is
  fixed at `medium`, and the kickoff packet lacks the inductive definitions and in-file lemmas
  that both successful sessions (P0, Qwen) read before rewriting.
- Prompt-cache behaviour was poor in earlier runs (luna-source wasted ~$0.79 on cache writes)
  and is still unmonitored; cost-ledger and run lifecycle bugs (mispricing, error-loop
  continuations, missing `cost.json` on kill) distorted small-budget experiments.
- The merge worker produced no real improvements and competes with the model for Lean CPU.
- Several code paths are Strata/InitsUpdatesComm-specific, blocking the other warm-up rows.

We deliberately keep running at small budgets ($0.10–$0.20 per run) to validate the harness
before spending real money, so every wasted turn and every misleading signal matters.

## Solution

A v5 harness where:

1. Every piece of Lean feedback is correct and line-aligned with what the model can inspect.
2. The model sees the scoring metrics for every evaluation (tokens, heartbeats, compatibility,
   per-axis contribution, local proxy, deltas vs reference and vs best) and a **per-tactic
   heartbeat profile**, and decides itself which trade-offs are worth making.
3. Ideas are proposed, recorded, pursued and abandoned by the model. The harness records and
   summarises them; it never gates evaluation on a schedule and contains no theorem-specific
   strategy text.
4. An Arena-specific Lean skill (derived from the vendored lean4 skill, trimmed to proof
   optimization) is loaded into every run, and thinking level is configurable per run.
5. The kickoff context is generic and source-derived: statement, original proof with its goal
   trace, definitions of the types/predicates in the statement, lemmas available earlier in
   the file, and signatures of everything the original proof uses.
6. The tool protocol is minimal and forgiving: parents and idea labels are optional metadata,
   probes are restorable, errors are actionable.
7. Prompt caching is designed for: stable prefix, append-only history, compact tool results,
   and per-run cache KPIs with alarms.
8. Run lifecycle and cost accounting are robust at small caps, and every run produces a
   comparable report so A/B harness experiments at $0.10–$0.20 are meaningful.
9. The evaluator works for any provisioned benchmark row without corpus-specific hacks.

## User Stories

### Correct Lean feedback
1. As the model, I want diagnostic line numbers to match the candidate file I can query with `lean_goal`, so that I inspect the goal that actually failed.
2. As the model, I want each diagnostic to also carry a proof-relative line number and the source line text, so that I can locate errors without arithmetic.
3. As the model, I want the error headlines to exclude warnings from unrelated parts of the file, so that I focus on my proof.
4. As the model, I want the candidate file materialized for `lean_goal` to be byte-identical (apart from the heartbeat wrapper) to the file that produced the diagnostics, so that goals and errors agree.
5. As a harness developer, I want a regression test proving diagnostic lines map to the shadow file lines, so that the offset bug cannot return.
6. As the model, I want to compile a draft containing `sorry` in probe mode and see the remaining goals, so that I can develop a structural rewrite hole by hole (as the naive run did with `trace_state; sorry`).
7. As a harness developer, I want `sorry` drafts never to become candidates or be scored, so that probe convenience cannot leak into submissions.

### Metrics and trade-off visibility
8. As the model, I want every evaluation result to show tokens, heartbeats, compatibility, and each axis's percentage and contribution to the local proxy, so that I understand what improved.
9. As the model, I want deltas against the reference, the parent, and the current best in each result, so that I can judge whether an edit was worthwhile.
10. As the model, I want a fast evaluation to report an estimated proxy (assuming full compatibility) labelled as an estimate, so that I can rank fast candidates without running full checks.
11. As the model, I want the exchange rate between axes stated once in context (e.g. 1 token ≈ N heartbeats, one lost version ≈ M tokens) for this specific problem, so that I can weigh trade-offs.
12. As the model, I want a per-tactic heartbeat profile of the original proof at kickoff, so that I know where elaboration cost is concentrated before editing.
13. As the model, I want to request a per-tactic heartbeat profile for any compiling candidate or probe, so that I can see whether a change moved cost or removed it.
14. As the model, I want the profile to show cost per source line / tactic block with cumulative share, so that I can spot that, e.g., one `simp_all` holds half the heartbeats.
15. As the model, I want the profile to state its total and how it relates to the measured whole-proof heartbeats, so that I can trust it.
16. As the model, I want a measured heartbeat floor for the statement (e.g. the cost of elaborating the statement itself) where measurable, so that I know how much heartbeat headroom remains.
17. As the model, I want the harness to make no recommendations about which tactic to use, so that I make the pros/cons decision myself from the numbers.

### Model-owned ideas
18. As the model, I want to record my own ideas (title, hypothesis, target proof region, expected effect on each axis), so that my strategy persists across turns and continuations.
19. As the model, I want to mark ideas as active, parked, succeeded or abandoned with a reason, so that I and future continuations do not repeat dead ends.
20. As the model, I want to tag candidates and probes with an idea when I choose to, so that results are attributed, but I want untagged evaluations to be accepted.
21. As the model, I want the frontier to summarise ideas with their attempts, best result per idea and last failure reason, so that I can decide where to invest.
22. As the model, I never want an evaluation rejected because a different idea is "scheduled", so that I can finish a repair I am close to.
23. As a harness developer, I want no theorem-specific or solution-derived strategy text in packets, prompts, skills or code, so that runs measure the harness's generality.
24. As a harness developer, I want an optional, advisory "breadth nudge" (e.g. noting that all recent attempts share one structure) that never blocks, so that diversity is encouraged without coercion.
25. As the model, I want to be prompted at kickoff to propose several structurally different ideas before committing, so that I consider rewrites, not only local edits.

### Skill and reasoning
26. As a harness developer, I want an Arena Lean skill derived from the vendored lean4 skill loaded into every run, so that the model has Lean proof-engineering guidance the naive run had.
27. As a harness developer, I want the Arena skill to cover the scoring axes, token counting rules, heartbeat-cost reasoning, compatibility pitfalls across versions, and the harness tool workflow, so that knowledge lives in one versioned place rather than in prompts.
28. As a harness developer, I want the skill's referenced files (proof golfing, simplification, performance, tactic references) available for on-demand reading by the model, so that context stays small until needed.
29. As a harness developer, I want the skill to be general (no problem-specific content) and its content hash recorded in the run config, so that runs are reproducible and comparable.
30. As a harness developer, I want the thinking level to be a runner option recorded in the run config, so that I can A/B `medium` vs `high` reasoning at small budgets.
31. As the model, I want to read skill reference files through a read-only tool scoped to the skill directory, so that built-in file tools can stay disabled.

### Generic kickoff context
32. As the model, I want the kickoff packet to include the definitions (including constructors) of every inductive type, structure, and definition appearing in the theorem statement, so that I can reason about the induction structure.
33. As the model, I want the statements of all lemmas declared earlier in the same file listed compactly, so that I know which project lemmas are usable.
34. As the model, I want the goal state before each tactic of the original proof (a goal trace), so that I understand what each step establishes without probing.
35. As the model, I want signatures of all constants used by the original proof, including namespaced names, constructors, and dependency-package (Mathlib/Std) lemmas, so that lookups never return "not found" for valid names.
36. As a harness developer, I want the packet to be built from elaboration data (info trees / constants) rather than regexes, so that it works for every corpus.
37. As a harness developer, I want the packet to be size-bounded with deterministic truncation, so that cache prefix stays stable and small.

### Minimal, forgiving protocol
38. As the model, I want `parent` to be optional and default to the candidate currently materialized, so that I never fail on bookkeeping.
39. As the model, I want to run a full check of an existing candidate by its number without naming any parent, so that "candidate cannot be its own parent" never occurs.
40. As the model, I want probes to get short IDs and be restorable into the shadow file, so that I can return to a promising draft.
41. As the model, I want to promote a passing probe to a candidate by ID without resending the proof, so that I save output tokens.
42. As the model, I want `arena_source` to accept larger ranges (or paginate) with a clear message showing the file length, so that I don't waste turns guessing.
43. As the model, I want any tool error to be a one-line actionable message (never a Python traceback), so that recovery costs one turn.
44. As the model, I want the frontier result to be compact (best candidates, active ideas, recent failures) and not repeat static information, so that it is cheap to call.
45. As a harness developer, I want the number of model-facing Arena tools reduced to the essentials, so that the tool schema prefix is small and stable.

### Cache efficiency
46. As a harness developer, I want the system prompt, tool schemas, skill and kickoff packet to form a byte-stable prefix for the whole run, so that every request after the first is a cache hit on the prefix.
47. As a harness developer, I want tool results never rewritten after being returned, and no dynamic values injected into earlier messages, so that history stays cacheable.
48. As a harness developer, I want dynamic state (budget remaining, current best) delivered only in new messages (tool results or continuation messages), so that it never invalidates the prefix.
49. As a harness developer, I want tool results compacted (no duplicated proof text, no unrelated warnings, diagnostics truncated with an option to fetch full text), so that per-turn context growth is small.
50. As a harness developer, I want per-request cache read/write tokens recorded and a run-level alarm when a request writes more than it reads after warm-up, so that cache regressions are caught immediately.
51. As a harness developer, I want the run report to include cache reuse %, cost per evaluation, and cost per turn type (compile, context, bookkeeping, rejected), so that I can compare harness versions.
52. As a harness developer, I want a deliberate policy for context growth (e.g. compaction threshold) that preserves the cached prefix, so that long runs do not degrade.

### Run lifecycle and accounting at small budgets
53. As a harness developer, I want the cost ledger priced per request with the correct tier, so that small caps are not consumed by mispricing.
54. As a harness developer, I want the hard cap enforced on actual usage only, with the last allowed request bounded so overshoot stays small and reported.
55. As a harness developer, I want continuations not to fire in a tight loop after provider or extension errors, so that plateau/continuation limits reflect real work.
56. As a harness developer, I want a SIGINT/SIGTERM-safe runner that always writes `cost.json` and a run summary, so that killed runs remain analysable.
57. As a harness developer, I want the continuation message to reference the current best candidate and the model's own active ideas, so that it never points at stale seeds.
58. As a harness developer, I want a run summary (best per axis, proxy timeline, structural vs local edit counts, cost breakdown, cache KPIs, tool error counts) written at the end of each run, so that experiments are compared without manual trace digging.
59. As a harness developer, I want an experiment matrix runner that launches identical-packet runs varying one factor (model, thinking level, skill on/off) at a fixed small cap, so that harness changes are evaluated fairly.

### Deterministic support work
60. As a harness developer, I want the merge worker disabled by default, so that it stops consuming Lean CPU without producing gains.
61. As the model, I want an optional on-demand "polish report" tool that tries mechanical variants of a candidate (line deletion, simp-only via `simp?`, closing-tactic substitutions) on CPU and returns the passing variants with their metrics, so that I decide which to adopt.
62. As a harness developer, I want the polish tool to run with bounded concurrency and never in parallel with a model evaluation, so that heartbeat measurements and latency are not distorted.

### Generality across rows
63. As a harness developer, I want environments resolved from row metadata (source, version, commit) through an environment registry rather than `{source}-{version}` naming, so that any provisioned corpus works.
64. As a harness developer, I want rows without a file path (standalone, e.g. PutnamBench) reconstructed from their header plus statement, so that they can be evaluated once provisioned.
65. As a harness developer, I want the candidate file truncated after the target theorem's end line, so that compile time and timeouts do not depend on later declarations.
66. As a harness developer, I want the heartbeat measurement version to be explicit per row (defaulting to the version matching the published denominator), so that measurement is consistent.
67. As a harness developer, I want a certification command that runs the reference proof of every provisioned row through fast and full evaluation and reports token and heartbeat calibration, so that new environments are trusted before use.

## Implementation Decisions

### Testing seams (two, at the highest level)
- **Seam A — campaign JSON CLI** (the existing `arena_campaign` action interface used by the Pi extension). All evaluator, packet, profile, idea, probe, frontier and source behaviour is specified and tested through this interface with real Lean on the Strata fixture plus synthetic rows.
- **Seam B — budgeted Pi runner with the fake provider** (the existing fake OpenCode test double). Prompt assembly, skill loading, cache-prefix stability, continuation behaviour, error-loop handling, cost ledger and run summary are tested by running the runner end-to-end against scripted fake model responses.
- No new seams are introduced; the extension remains a thin adapter between Pi and Seam A.

### Evaluator (engine)
- Split compile output into structured diagnostics: `{severity, file_line, proof_line, column, message, source_line_text}`. Diagnostics from the measured compile are remapped by subtracting the wrapper line count for lines after the insertion point; this mapping lives in one function with a unit test.
- Only diagnostics within the target declaration's line span are returned as headlines; out-of-span diagnostics are counted and summarised.
- The file is truncated after the target declaration before compilation (statement integrity checks still run on the pinned full source).
- A new `probe` evaluation mode allows `sorry`/`admit` and returns remaining goals at each `sorry` location; probe results can never be stored as candidates nor scored.
- Results carry a `metrics` block: tokens, heartbeats, compat map, per-axis percentages, per-axis contribution, proxy (full) or estimated proxy (fast, labelled `assumes_full_compat`), and deltas vs reference / parent / best.
- Exchange rates (points per token, per 100 heartbeats, per lost version) are computed per row from the pinned denominators and reported in the packet.

### Per-tactic heartbeat profiler
- A new profiler action instruments a compiling proof by wrapping each tactic step (at the tactic-sequence level, recursively into nested blocks up to a depth limit) in a heartbeat-counting tactic implemented in the same way as the existing command-level wrapper (heartbeat delta around evaluation, divided by 1000).
- Output: per proof line / tactic block — heartbeats, share of total, and nesting; plus `profiled_total` vs `measured_total` and an `unattributed` remainder (term elaboration outside tactics, kernel check).
- The instrumented file is a scratch artifact only; profiling never alters candidates, and failures to instrument degrade to a coarse per-top-level-tactic profile.
- The kickoff packet includes the original proof's profile. The model can request profiles for any candidate or probe ID.
- Heartbeat floor: measured once per row by elaborating the statement with a minimal stub where possible; reported as informational.

### Ideas: model-owned
- Remove all hard-coded idea lanes, the scheduler gate, the idea-shape check, and the structural-lane text from packet generation. No strategy content remains in code or prompts.
- Idea records: `{id, title, hypothesis, region (proof lines), expected_effect (per axis), status ∈ {active, parked, succeeded, abandoned}, reason}`. Created and updated only by the model.
- `idea_id` on evaluate/probe is optional metadata. Frontier summarises ideas (attempts, probes, best metrics, last failure).
- A non-blocking advisory may be attached to results when the last N candidates descend from one lineage with no metric gain; it states facts only.
- Kickoff instruction (generic, in the skill and packet template): first propose at least three structurally different ideas with expected axis effects, then pursue them.

### Arena Lean skill
- New skill package `arena-lean` inside the arena-pi package, derived from the vendored lean4 skill: keep core principles, LSP workflow, golfing/simplification/performance references; drop formalization, sorry-filling workflow commands, Mathlib contribution style and unrelated references.
- Adds Arena sections: scoring axes and token-counting rules, reasoning about heartbeat cost from profiles, cross-version compatibility pitfalls (recorded as general rules, e.g. syntax accepted only by newer toolchains), statement immutability, tool workflow (probe → profile → evaluate fast → full).
- Loaded explicitly via the runner's skill option; discovery stays off. The skill directory content hash is stored in the run config. A read-only `arena_skill_read` tool (or Pi's skill-file reading if it works with built-in tools disabled — to be verified) exposes reference files.
- Thinking level becomes a runner option (default `high` for v5 experiments), recorded in the run config.

### Generic context packet
- Packet built from Lean elaboration data rather than regex: constants used by the original proof and statement (via a small Lean metaprogram run in the pinned environment), resolved to signatures from the environment, including dependency packages, namespaced names and constructors.
- Definitions of inductive types/structures/defs appearing in the statement are pretty-printed with constructors.
- Lemmas declared earlier in the same file are listed as compact signatures (bounded count, nearest-first).
- Original-proof goal trace: goal before each top-level tactic, bounded per goal length.
- Packet is deterministic, size-bounded, and placed once at kickoff (cache prefix).

### Tool protocol
- Model-facing tools reduced to: `arena_target` (folded into packet; may remain for re-read), `arena_probe`, `arena_evaluate`, `arena_profile`, `arena_candidate` (restore candidate or probe), `arena_idea` (create/update), `arena_frontier`, `arena_source`, `arena_declaration`, plus Lean MCP direct tools. `arena_decision` merges into `arena_idea`/candidate status.
- `parent` optional, defaulting to the currently materialized candidate; `arena_evaluate` accepts `candidate: "#N"` to re-evaluate (e.g. full mode) an existing node.
- Probes get `p<N>` short IDs; `arena_evaluate` accepts `from_probe: "pN"` to promote.
- `arena_source` limit raised and paginated; errors include file length; paths outside the project/packages return a clear refusal. All CLI errors are caught and returned as one-line messages.
- Tool result payloads: metrics block, mapped diagnostics (truncated, with `full_diagnostics_ref`), candidate/probe ID, materialized path. No echoed proof text, no frontier dump in evaluate results (a one-line "best so far" only).

### Cache design
- Static prefix = system prompt + tool schemas + skill + packet; nothing dynamic before the first assistant turn.
- Budget/best-so-far appear only in new tool results or continuation messages.
- The extension never mutates past messages (existing rule kept and tested).
- Ledger records cache read/write per request; extension emits an alarm event when a post-warm-up request has `cache_write > cache_read`; run summary reports reuse % overall and recent.
- Compaction policy: disabled below a configured context size; when triggered, compacts only the tail beyond the stable prefix. Verified with the fake provider.

### Lifecycle and accounting
- Keep per-request tier pricing (v4 fix). Continuation logic counts only turns that produced a successful model response; consecutive error turns trigger a backoff and a distinct `error_loop` stop reason.
- Runner installs signal handlers that terminate Pi gracefully and always write `cost.json` and the run summary.
- Continuation text references the best candidate number and the model's active ideas; it contains no strategy advice.
- New run summary artifact (JSON + short text) per run; new experiment-matrix entry point that launches N runs with identical packets varying one declared factor, each at a fixed small cap ($0.10–$0.20), sequentially or with bounded parallelism by measured RAM.

### Deterministic support
- Merge worker off by default (flag to enable); not launched by the runner unless requested.
- Optional `arena_polish` tool: given a candidate, tries a bounded set of mechanical variants, evaluates fast only, returns passing variants with metrics; never auto-promotes. Runs serialized with model evaluations via a per-run Lean lock.

### Environment generality
- Environment registry keyed by `(source, version, commit)` mapping to a provisioned workspace path; replaces `{source}-{version}` naming.
- Standalone rows reconstructed as `header + statement + proof` in a scratch file within the matching Mathlib environment.
- Heartbeat measurement version: explicit per row, default the primary listed version, recorded in results.
- Certification action over all provisioned rows (reference compile, tokens = published, heartbeats vs published with tolerance, full compat).

## Testing Decisions

- Good tests assert externally observable behaviour at the seams: JSON outputs of campaign actions, files written to a run directory, and the provider payloads/ledger produced by a fake-provider run. They do not assert internal function structure.
- **Seam A tests (Python, real Lean on Strata, marked slow):**
  - Failed candidate: every reported diagnostic line, when queried via `lean_goal`-equivalent lookup on the materialized file, has the reported `source_line_text`.
  - Probe with `sorry` returns remaining goals and cannot be promoted or scored.
  - Metrics block for the 126-token fixture reproduces proxy 76.72 in full mode and the labelled estimate in fast mode.
  - Profiler on the reference proof: per-line entries exist, `profiled_total` is within a tolerance of measured 4251, and `simp_all`-bearing lines are attributed non-zero cost.
  - Packet for the target contains constructors of the statement's inductive types, prior-file lemmas, goal trace, and contains none of a denylist of strategy phrases.
  - Evaluate with arbitrary/no `idea_id` and no parent succeeds; re-evaluating `#N` in full mode succeeds; probe restore and promote work.
  - Truncation after end line leaves results identical for the fixture.
  - Synthetic row tests (no Lean) for environment registry resolution and standalone reconstruction.
- **Seam B tests (TypeScript/Python with the fake provider):**
  - Skill is present in the first provider payload; skill hash recorded in run config; thinking level honoured.
  - Prefix bytes identical across all requests of a scripted multi-turn run; no earlier message mutated after a later tool result.
  - Cache alarm fires when the fake provider reports write > read.
  - Error-loop: scripted consecutive errors produce `error_loop` stop without burning continuations.
  - Kill during run still writes `cost.json` and summary.
  - Continuation text references the current best and active ideas.
- Prior art: `tests/test_graph.py` (ledger/graph behaviour via campaign functions), `tests/test_engine.py` (evaluator), `packages/arena-pi/extensions/budget.test.ts` (pricing/cap), `tests/fake_opencode.ts` (fake provider).
- Acceptance experiment (not a unit test): at $0.10 cap, v5 runs with Luna and Qwen on `Core.InitsUpdatesComm` using identical packets; record summaries. Success = no harness rejections, zero misaligned goal lookups, bookkeeping+rejected spend < 5%, cache reuse > 95%, and at least one run reaching an induction-first-class heartbeat reduction (< 1000 HB) without any hint.

## Out of Scope

- Increasing per-run budgets beyond $0.20 (deliberately deferred until the harness is validated).
- Provisioning PhysLib, CSLib, ArkLib and PutnamBench environments (H3); this spec only makes the code paths generic.
- Official server submission/calibration and the open-track model hosting requirements.
- Multi-session orchestration (best-of-N fresh sessions across models) and a Lean REPL-based sub-second compiler; noted as next steps once v5 is validated.
- Graph viewer changes beyond displaying new fields if trivial.
- Langfuse integration for budgeted runs.

## Further Notes

- Evidence for each defect is in the run artifacts under `runs/pi-budget/*` and `runs/analysis/*`; key numbers: 14-line offset (wrapper newline count), scheduler rejection at Luna v4 08:18:20 of a proof that compiles 3/3 (248 tok), bookkeeping/rejected spend 20% (Luna v4) and 26% (Qwen v4), luna-source cache-write waste ≈ $0.79, P0 total 7.17M tokens with reasoning bursts up to 15.6K vs Luna max ~2.9K output per turn.
- Exchange rates for the fixture: 1 token ≈ 0.149 pt, 100 HB ≈ 0.78 pt, one lost version ≈ 11.1 pt. These are reported as data; the model decides trade-offs.
- Suggested implementation order: (1) diagnostics mapping + truncation + metrics block; (2) remove scheduler/hard-coded ideas, model-owned idea records, protocol simplifications; (3) skill + thinking option; (4) profiler; (5) generic packet; (6) cache KPIs + lifecycle fixes + run summary; (7) merge worker off + optional polish; (8) environment registry. Run a $0.10 Luna/Qwen pair after steps 2, 4 and 6.
