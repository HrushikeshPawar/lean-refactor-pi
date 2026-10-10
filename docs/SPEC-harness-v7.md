# Harness v7 specification

Source of truth for every decision: `docs/PLAN-harness-v7.md` (decisions D1–D41, facts and probe evidence in §1,
traceability of every ISSUES, BACKLOG and WORKING item in §13). This spec states the behaviour to build. Section
references "plan §x" point to the evidence. Status: ready for implementation once the owner approves.

## Problem Statement

The operator runs a harness in which a model (DeepSeek v4.1 flash or MiMo 2.6 Pro) refactors one of 15 given Lean 4
proofs to cut proof tokens and Lean heartbeats while it still compiles on every listed toolchain. Submission v3
scored 84.41% (rank 4 of 27). The gap to the leader is mostly on the length axis. v6 runs exposed problems that
cost points, money and the operator's time:

- **Run control reacted to estimates, not actual spend.** Worst-case reservations, 17–30 times the real cost,
  counted against gates, produced false stops and inflated reports. Compaction failed on window checks. A
  one-minute provider outage ended runs.
- **The model was told things that were false or contradictory.** Rules were repeated in three or four places in
  code. A theorem-specific number sat in the generic skill. 165K characters of vendored references steered proof
  content, against the owner's neutrality rule.
- **The model had to guess what a change was worth.** Tokens and heartbeats per step were shown only as a top-10
  hotspot list or a 9 KB profile dump. Nothing priced an edit before it was compiled.
- **The candidate graph's bookkeeping was wrong.** Parents matched the text-closest node only 41% of the time.
  Merges the model performed by retyping text were lost. Ideas carried no information, since 99% defaulted.
  Routes arrived after the run ended because of a stalled serial Lean worker. The finish gate refused 84% of its
  calls.
- **Big edits failed repeatedly.** Drafts changing more than 30 lines compiled 23% of the time, against 69% for
  1–3 lines. Each retry re-sent the whole proof and learned of only one error.
- **Tools were many, overlapping and error-prone.** There were 16 model-visible tools, raw MCP tools addressed by
  file line (7% out-of-range errors), and a text search that stopped after 30 files and missed Lean core. Luna
  spent 47% of its money on bookkeeping-only turns.
- **Lean time was wasted.** There was one daemon per run, so every run re-imported every header (20–150 s each).
  Every candidate was cross-checked on every toolchain (up to 5.6 times the primary cost). lean-lsp-mcp ran
  uncounted workers. A v6 code change once made Lean so slow that 6 hours of work were lost.
- **Measurement was wrong on some rows.** Heartbeats were measured on the first listed toolchain, but the grader
  uses the newest. That put the Putnam rows off by −10% to +27%.
- **The best result came from outside the harness.** Hand-built cross-run hybrids were worth 43.58 points in v3,
  with no reproducible code.
- **The operator could not see what the model saw.** Nodes could not be linked to the reasoning and tool calls that
  produced them. There were 20 separate argparse scripts, no project packaging, and 495 unittest cases, many of
  them tautological.

## Solution

v7 rebuilds the harness around one principle: **the harness measures and keeps the books, and the model writes
proofs.** The model is never asked for bookkeeping, and its intent is never inferred.

- **Run control is reactive.** After every model call the actual settled cost is added. When it reaches the run
  limit ($0.50 now, never above $2), the agent stops and the harness closes the run. Pi's own retry and idle
  timeout handle transport failures. A long outage ends with a distinct, rerunnable stop reason.
- **Every word the model sees lives in one directory** of logic-free templates. Every number in it is computed per
  theorem at packet build. Each rule is stated once. Tests enforce consistency and neutrality, and a word-budget
  table makes every line justify its tokens.
- **The model sees prices.** The packet carries a per-step table for the original proof (tokens, heartbeats,
  points at stake). Every compile reply carries a price row against its parent and the best, ending in Δscore.
  Token counts of any phrasing are free and instant. Library names show their token cost.
- **Five tools with one reply schema:** compile, goal, search, read, and finish. Finish appears only when 10% or
  less of the budget is left. Graph moves (edit a region, fill a hole, merge steps, branch from a node) are compile
  modes, so lineage is exact by construction. A free-text draft is filed under the focus, and the reply says so.
- **A failed draft becomes a sketch.** The harness replaces failing steps with holes (54% of failed v6 drafts
  salvage, median 1 hole). The model fills holes one at a time, and the harness assembles the proof when all are
  filled.
- **The graph steers without steering content.** A compact map shows the archive (best node per cell), an effort
  table (points at stake against attempts per step), open holes and recent nodes. When a lineage stalls (12 nodes
  without improvement), the harness moves the focus to another archive cell. Routes are internal, synchronous
  proof-shape signatures.
- **One shared Lean service per machine:** a header-keyed REPL pool for whole-proof checks, LSP documents for
  interactive edits, and cold compiles only for final checks. Campaigns run row-major to keep headers warm.
  Cross-version checks run only for candidates that could become the best. **A speed gate makes Lean match or beat
  the recorded baseline** before any change lands.
- **Heartbeats are measured on the newest listed toolchain**, with the existing wrapper, which matches the official
  denominators.
- **`arena submit` builds the submission inside the harness:** multi-run selection, cross-run step recombination
  aligned by subgoal, every gate, a manifest and a diff against the previous submission.
- **A single Cyclopts `arena` CLI with Rich output.** `arena replay` shows exactly what the model saw at any turn.
  The viewer shows each node's reasoning and tool calls. The project is a uv project, and pytest runs a minimal,
  behaviour-only suite.

## User Stories

### Operator: running and budgeting
1. As the operator, I want a run to stop only when its actual settled spend reaches the run limit, so that no run
   ends on an estimate.
2. As the operator, I want the overshoot past the limit to be at most one model call, so that spend stays
   predictable without pre-call estimation.
3. As the operator, I want compaction calls settled in the same ledger as model turns and never blocked, so that
   long sessions compact reliably.
4. As the operator, I want a provider outage handled by Pi's native retry and a wall-clock wait of about 10
   minutes, so that a short outage does not end a run.
5. As the operator, I want a run that stays unreachable past that wait to stop with `provider_unreachable`, so that
   I can rerun exactly those runs.
6. As the operator, I want `error_loop` reserved for repeated model-side failures, so that the stop reasons tell me
   what went wrong.
7. As the operator, I want stalled streams cut by an idle timeout and retried, so that a hung stream does not cost
   minutes.
8. As the operator, I want every report to show one spend figure (settled), so that reports and the cap agree.
9. As the operator, I want each run's record to carry the harness commit, a dirty flag, the `models.yaml` hash and
   the Pi version, so that I always know which code produced a result.
10. As the operator, I want a campaign report to warn when its runs used different code versions, so that mixed
    campaigns are visible.
11. As the operator, I want `arena run` to load provider keys from `.env`, so that runs need no manual export.
12. As the operator, I want Pi's model configuration generated from `models.yaml`, so that each price lives in
    exactly one place.
13. As the operator, I want a test that the configured prices match each provider's published prices, so that the
    actual-cost stop is exact.
14. As the operator, I want MiMo 2.6 Pro (via primalab) and DeepSeek v4.1 flash (via opencode-go) as the only
    models, so that the harness has no code for retired models.
15. As the operator, I want MiMo's thinking switched off on tool-result turns (`reasoning_effort: none`), as Xiaomi
    advises, so that tool calls do not leak into reasoning.
16. As the operator, I want MiMo's earlier reasoning replayed and DeepSeek's reasoning replay controlled by
    configuration, so that each model gets the history it needs.
17. As the operator, I want `arena campaign --check` to run every real gate with no model call, so that a plan that
    passes the check also passes the launch.
18. As the operator, I want a lock that prevents two campaigns, or a provision and a campaign, from overlapping, so
    that runs never compete for Lean memory by accident.
19. As the operator, I want swap, swap-in/out and free disk recorded and new runs held above a threshold, so that
    the machine never thrashes mid-campaign.
20. As the operator, I want campaigns ordered by workspace, toolchain set, row and replicate, so that warm headers
    are reused.

### Operator: Lean speed and resources
21. As the operator, I want one shared Lean service per machine reused by every run and campaign, so that headers
    are imported once per row and toolchain, not once per run.
22. As the operator, I want whole-proof checks (cross-version, salvage, recombination, index, certify) served by a
    header-keyed REPL pool with LRU eviction and a per-process memory cap, so that many checks share one import.
23. As the operator, I want the model's interactive edits served by warm LSP documents, so that splice edits
    re-elaborate only from the changed line.
24. As the operator, I want cold `lake env lean` used only for final verification and submission, so that the hot
    path never pays a cold import.
25. As the operator, I want the primary toolchain warmed first and the others lazily, so that the model starts
    sooner (three parallel opens took 148 s, against 45 s for one).
26. As the operator, I want model-lane workers never evicted by cross-version warm-up, so that the model never
    waits on re-opens.
27. As the operator, I want workers closed when no queued row needs them, not on idle timers, so that warm workers
    survive between runs of the same row.
28. As the operator, I want cross-version checks run only for candidates that could become the best verified, and
    at close-out, so that Lean time is not spent on dominated candidates.
29. As the operator, I want the probe timeout set near three times the warm p95 instead of 180 s, with partial
    messages returned on a timeout, so that a stuck draft costs seconds.
30. As the operator, I want lean-lsp-mcp behind the shared service or capped at one worker, so that no Lean process
    runs outside the memory budget.
31. As the operator, I want the memory (PSS) of every Lean worker logged, so that worker caps rest on measurements.
32. As the operator, I want `arena lean bench` to measure, per toolchain, cold and warm header opens, warm compile
    p50/p95, splice-edit scaling and per-worker memory, so that Lean speed is a number, not a feeling.
33. As the operator, I want a recorded Lean speed baseline and a gate that fails when a change makes any measured
    figure slower beyond tolerance, so that no code change can again make Lean slow without being caught.
34. As the operator, I want the speed gate to report which figure regressed, on which toolchain, by how much, so
    that a regression is diagnosed in minutes.
35. As the operator, I want v7's Lean machinery to match or beat the v6 baseline on every benchmarked figure before
    v7 is accepted, so that the overhaul cannot cost speed.

### Model: what it is told
36. As the model, I want every rule stated exactly once, so that I never read two contradictory statements.
37. As the model, I want every number I am given to be measured for this theorem, so that I can trust it.
38. As the model, I want the packet to include the original proof with a per-step price table (tokens, self and
    inclusive heartbeats, versions, points if the step were gone), so that I know where the points are.
39. As the model, I want the per-axis exchange rates (points per token, per thousand heartbeats, per version), so
    that I can weigh a trade-off myself.
40. As the model, I want the ranked library (top 60) with the token cost of writing each name, so that I can see
    when a long name costs points.
41. As the model, I want no text that suggests a kind of proof, so that my choices are my own.
42. As the model, I want a short facts sheet only for what the harness cannot measure (for example forbidden
    constructs), so that I do not read 165K characters of mismatched references.
43. As the model, I want a budget footer with spent and left on every reply, so that I always know my position.
44. As the model, I want a failed request explained by its own fact line, so that I am not told my turn ended with
    text.
45. As the model, I want a truncated turn to keep its reasoning and the reply to say where it was cut, so that I do
    not re-derive it.

### Model: tools
46. As the model, I want one `compile` tool that takes one to four drafts and returns, per draft, as soon as each
    finishes, so that a slow draft never holds back the others.
47. As the model, I want every error of a failing draft at once, each with its goal, so that I fix them in one
    turn.
48. As the model, I want each compiled draft's price row (tokens, heartbeats, versions, Δscore against its parent
    and the best), so that I can see whether a gain was paid for elsewhere.
49. As the model, I want `compile check:"tokens"` to count tokens of drafts or snippets instantly with no Lean, so
    that I can price phrasings before compiling.
50. As the model, I want `compile splice` to replace a range of steps of a base node and send only that range, so
    that I do not re-send unchanged proof text.
51. As the model, I want `compile fill` to solve one hole of a sketch, so that I can work on part of a proof.
52. As the model, I want `compile merge` to take steps from other nodes into a base node, so that I can combine
    work without retyping it.
53. As the model, I want `compile base` to make variants of any node, so that I can branch from anywhere.
54. As the model, I want duplicate drafts compiled once, so that a batch is not wasted.
55. As the model, I want cross-version results that land during a call attached to that call's reply, so that I
    never build on a name that fails elsewhere.
56. As the model, I want a `goal` tool addressed by node and hole, or a node-relative line, so that I never
    compute file offsets.
57. As the model, I want `goal try` to run my own snippets at a hole and price each, so that I can compare closers
    cheaply.
58. As the model, I want a reason when a hole is not reached (an error at an earlier line), so that an empty goal
    list is explained.
59. As the model, I want `search` over names, types and text across the project, its dependencies and Lean core,
    returning only declarations visible from this theorem's imports, so that every hit is usable.
60. As the model, I want each search hit to carry a signature preview, its token cost and one handle form, so that
    I often need no follow-up read.
61. As the model, I want a near-miss name answered with its look-alike from the statement (for example `𝔽q` for
    `ℱq`), so that confusables cost one turn, not five.
62. As the model, I want dot-notation completions through `search`, so that I can discover what follows `h.`.
63. As the model, I want `read` by handle, node or hole, with views for source, prices, diff and map, so that one
    tool answers every lookup.
64. As the model, I want every error to name the bad input and list the valid forms, so that I can correct it.
65. As the model, I want a malformed or empty argument reported as malformed, never as a missing field, so that I
    know what happened.
66. As the model, I want per-item results in batch calls, so that one bad name does not reject the batch.
67. As the model, I want repeated goals and diagnostics shown as "same as pN", with the full text kept on disk, so
    that my context is not filled with copies.
68. As the model, I want `finish` to appear only when 10% or less of the budget is left, so that I never spend
    turns on refused stops.
69. As the model, I want a short finish reply with the archive and per-axis points left, so that the stop decision
    is informed and cheap.

### Model and operator: candidate graph
70. As the model, I want every compiled draft to become a node with a stable id, closed, sketch or broken, so that
    I can refer to anything I made.
71. As the model, I want each reply to echo how my draft was filed (`n44 ← n30 fill h2`, `n51 ← focus n41`), so
    that I always know the graph.
72. As the operator, I want lineage edges recorded exactly when a graph operation built the text (edited, filled,
    merged, salvaged), so that bookkeeping is correct by construction.
73. As the operator, I want a free-text draft filed under the focus and stated as such, or as a new root when it
    resembles nothing, so that no hidden default creates false parents.
74. As the operator, I want the model's named parent and the measured text-closest parent kept as audit fields
    only, so that analysis can compare them without either driving a rule.
75. As the operator, I want the best node of a batch to become the focus, so that the next splice starts from the
    best, not the last.
76. As the model, I want a failed draft salvaged into a sketch by replacing failing steps with holes (finer
    sub-steps, header-aware `have`, then escalation to the parent block), so that a big edit is not wasted.
77. As the model, I want the salvage result attached when ready ("n44 salvaged: 1 hole at line 16"), so that I can
    fill instead of re-send.
78. As the model, I want the harness to assemble and compile the full proof when every hole has a closing fill,
    using the cheapest fill and listing the alternatives, so that I never retype a skeleton.
79. As the model, I want a map (best node, archive per cell, recent nodes with keep/discard/broken/filled status,
    per-step effort table, open holes) on replies when it changes, so that I see where effort has and has not
    gone.
80. As the model, I want a fact line when the harness moves the focus after a stall, so that I know why the
    default base changed.
81. As the operator, I want routes computed synchronously at compile time from proof shape (step skeleton mixed
    50/50 with step-hash overlap, hysteresis 0.60/0.35, frozen once filed), so that they never arrive late and
    never depend on a Lean worker.
82. As the operator, I want archive cells keyed by (route, depth bucket, closed or sketch), each keeping its best
    node, so that diversity is visible in at most about 12 cells.
83. As the operator, I want a stall defined as 12 nodes without improvement in the last improvement's lineage
    subtree, so that productive deep chains continue (b2's best was at depth 46) and dead ones end.
84. As the operator, I want the stall-move target configurable (best other cell, least-visited, or map only), so
    that phase 5 can A/B it.
85. As the operator, I want the goal before and after each top-level step recorded for every node, so that steps
    can be aligned by subgoal across nodes and runs.
86. As the operator, I want one append-only event log with typed edges that the viewer, summary, map and
    submission all read, so that every number comes from one record.

### Operator: submission and hybrids
87. As the operator, I want `arena submit` to pick each row's best cold-verified candidate across named runs by
    settled score, so that selection is reproducible.
88. As the operator, I want cross-run recombination that swaps a step of the best for a cheaper step from any node
    of any run with the same subgoal at that position, so that the 43-point hybrid gains come from the harness.
89. As the operator, I want every submitted row gated by exact statement, the official forbidden filter, a fresh
    cold compile on every listed toolchain and agreement with its recorded proxy, so that nothing invalid ships.
90. As the operator, I want a parity test between our forbidden filter and the official app's, so that the filters
    never drift.
91. As the operator, I want a manifest (source run, candidate, per-axis proxy, tokens, heartbeats, per-version
    results, settled spend of all contributing runs, code version) and a provenance ledger, so that the report is
    complete.
92. As the operator, I want a diff against the previous submission that lists every row that got worse, so that
    no row regresses silently.
93. As the operator, I want harness-made merge nodes allowed in the submission, so that in-budget hybrids count.

### Operator: observability
94. As the operator, I want `arena replay <run> --turn N` to show the system prompt, skill, packet, tools, messages,
    tool results as delivered (with the trim difference) and the reasoning, so that I see exactly what the model
    saw.
95. As the operator, I want `arena replay --node nX` to resolve the node to its tool call and turn, so that I can
    start from the graph.
96. As the operator, I want `arena replay --render v7` to show what the v7 packet, map and replies would have shown
    at a historical turn, so that text changes can be tested on real history before a paid run.
97. As the operator, I want the system prompt, skill, tools and packet stored once by content hash and referenced
    from each request record, so that journals are small and exact.
98. As the operator, I want every node and ledger event to carry its tool call id, request id and turn, so that
    joins are exact, not time-based.
99. As the operator, I want the viewer's node panel to show the reasoning and tool calls (with delivered and
    untrimmed results) that produced the node, so that I understand each node.
100. As the operator, I want the local journal to be the record and Langfuse a secondary view, so that lost
     generations never cost data.

### Operator: CLI, packaging, tests
101. As the operator, I want one `arena` command (run, campaign, certify, eval, check, submit, replay, serve,
     graph export, provision, lean serve/health/bench, experiment, merge, preflight, doctor, text render/budget,
     smoke) with Rich output and `--json`, so that the harness has one entry point.
102. As the operator, I want the Pi extension's JSON interface kept as a hidden `arena protocol` command, so that
     the machine contract stays stable.
103. As the operator, I want `arena doctor` to check pins, vendor submodule commits, the benchmark hash, the Pi
     version, the price test and the official token counter against all 15 `proof_length` values, so that drift
     is caught before a run.
104. As the operator, I want a uv project (flat layout, Python 3.13) and node-native TS tests, so that setup is one
     command and tests run on the production runtime.
105. As the operator, I want every vendored import behind one adapter, so that an upstream change (such as a new
     sibling import) is fixed in one place.
106. As the operator, I want a minimal pytest suite of about 80–120 behaviour tests that runs in under 60 s without
     Lean, plus Lean tests behind a marker, so that tests are fast and meaningful.
107. As the operator, I want no test that reads the live machine, so that tests are deterministic.
108. As the operator, I want `arena text budget` to print each template's tokens, where it shows and how often, so
     that every word justifies its place.
109. As the operator, I want `arena experiment` and a harness-results log (commit, change, rows, replicates, mean
     proxy, spread, bookkeeping share, tool errors, keep/discard), so that harness changes are kept only when they
     measurably help.

## Implementation Decisions

### Modules
- **Agent text.** A root-level directory holding every model-facing string as templates: skill, packet sections,
  per-tool descriptions and parameter descriptions, per-tool reply lines, messages (footer, refusals,
  continuation, compaction memory, errors, phase or focus notices, map rows), and a shared numbers file read by
  code too. Templates contain no logic: `{name}` and `{name:fmt}` placeholders only. Code supplies
  plurals and conditionals as ready-made fragments. A strict renderer exists in Python and in TS, and a missing key
  is an error. Strings are first moved verbatim, verified by a byte-identical packet, and rewritten together with
  the tool surface. (plan §2)
- **Run control** (TS extension). Delete the budget module, its reservations, estimates, window and byte bounds,
  unresolved spend and the $3 gate. Delete the custom provider wrapper. Malformed-argument repair moves to the
  message or context hooks. Request and response records move to Pi's provider request and response hooks. The
  per-call cost comes from Pi's usage on `message_end`, and compaction cost from the compaction event. The stop is
  `spent >= limitUsd` in the existing settle hook. The finish tool is activated with Pi's `setActiveTools` when
  10% or less remains. (plan §2d, D8, D15)
- **Scoring and measurement.** The measure version is the **newest listed toolchain** (D31). The existing
  heartbeat wrapper stays (D32). The official token counter is used through the vendor adapter. Exchange rates
  feed every price row. (plan §1l)
- **Lean service.** One machine-wide service keyed by (workspace, toolchain). Lanes:
  - an LSP document lane for interactive compile, goal, splice and per-step goals;
  - a REPL pool keyed by (toolchain, header) for whole-proof checks;
  - a lazy cross-version lane that never evicts model-lane workers;
  - a cold lane for final checks.

  Memory: the primary pinned at 2–3 workers, 1 per other toolchain, `RESERVE_GB=5`, PSS logged, external Lean
  processes counted (the MCP server goes in ticket 15, D40). The LSP lane serves goals at a position or hole and
  runs snippets at a hole, which `goal` needs once MCP is gone. Close at row end. The REPL pool is adopted after the benchmark confirms a gain. Lean v4.32
  header snapshots are trialled on rows that use v4.32 or later. The REPL for the v4.29.1 row needs a
  compatibility check. (plan §9b–9d)
- **Campaign scheduler.** Row-major ordering, pre-warming the next row during the current row's last 10–15
  minutes, the overlap lock, and recorded jobs, memory and load settings. (plan §9d, #40)
- **Graph core.** An append-only event log. Node: id, text hash, status, per-axis score, per-version results,
  steps (ids, text hash, goal before and after), holes (id, goal, fills). Edges: `edited_from`, `filled_from`,
  `merged_from` (with steps), `salvaged_from`, `filed_under_focus`, plus the audit fields `named_parent` and
  `measured_parent`. Focus is a separate pointer. Routes are a synchronous Python function of the proof text.
  Archive cells are keyed by (route, depth bucket 0–2/3–7/8–15/16+, closed or sketch). The stall detector is
  lineage-scoped with m=12. (plan §5)
- **Salvage and assembly.** On compile failure the salvage chain runs in the background: finer sub-step holes,
  then header-aware `have … := sorry`, then escalation to the parent block, with up to 6 compiles. A sketch that
  elaborates becomes a node. When every hole has a closing fill, the harness assembles the proof with the cheapest
  fill. (plan §5f, §5g, D23, D21)
- **Price engine.** Per-step table: tokens via the official counter, self and inclusive heartbeats via the
  per-tactic profile (only for archive nodes and the original), points at stake via the rates. Price row per
  compile: total heartbeats from the same compile. Instant token quotes. Library token costs. (plan §3)
- **Declaration index and search.** At provisioning, per (workspace commit, toolchain, header), the existing
  environment walk emits every visible declaration (name, kind, pretty type, module, position, generated or
  private flags, name token cost) into a cached index. `search` merges index hits (exact, prefix, fuzzy,
  confusable, type by head symbol and constant set, dot completions) with ripgrep text hits mapped to enclosing
  declarations and filtered to the visible set. Results share one handle form. ast-grep is not used. (plan §4d)
- **Tool surface.** Five tools: compile, goal, search, read, finish. One reply schema: `ok`, `facts`, `items` (each
  with its own error), `handles`, footer. The lean-lsp-mcp server is removed (D40): the five tools run on the Lean service's LSP lane. Dropped:
  evaluate, candidate, state, idea, profile, skill_read, the separate MCP tools, and harness-run suggestion engines
  (D30). (plan §4f)
- **Packet.** Statement and original proof, the price table, exchange rates, the ranked library top 60 with token
  costs (D34), and goals before each top-level step. Shed order under the size limit drops local-variable lines
  before library lines (#16).
- **Compaction memory and fresh seed.** One text: full best proof, the map, the library lines the best uses, a
  "read so far" list, and open holes with goals. (plan §12c)
- **Submission builder.** Multi-run selection, theorem-level pool recombination aligned by step goals (step
  position and step hash as a fallback), gates, manifest, provenance ledger and diff. The `auto_merge` exclusion is
  removed. A vendored filter has a parity test. (plan §5g, BACKLOG §6)
- **Replay and viewer.** A content-addressed blob store for the system prompt, skill, tools and packet. Turn index,
  tool call id and request id on every record. A replay renderer, including a v7 re-render of historical turns. A
  viewer endpoint per node and a "Reasoning & calls" tab. (plan §7a, §7b)
- **CLI and packaging.** A Cyclopts app over the modules above, with the tools folded into a CLI package. A uv
  project with a flat layout. Vendored imports go through one adapter. The vendor submodules are on upstream:
  arena-space (UI changes only) and lean-refactor (its token counter matches all 15 official `proof_length`
  values; its new sibling import is handled by the adapter). lean4-skills, the skill-copy tool and the route
  validation tool are removed. `submission/` is removed. (plan §7)

### Interfaces and contracts
- **`compile` request:** `drafts[1..4]` | `splice{base, steps, text}` | `fill{hole, text}` |
  `merge{base, take:[{from, step}]}`; optional `base`, `from` (audit), `note`, `check: tokens|lean`.
  **Per-item result:** node id, filing line, status, all errors with goals, holes, price row, per-version results
  when known, salvage notice when ready.
- **`goal`:** `node` + `hole` | node-relative line; optional `try: [snippets]`. Returns goals and priced attempts.
- **`search`:** `queries`, `kind: name|type|text`, optional `after` for completions. Returns handles with a
  signature preview, token cost and location.
- **`read`:** `handle` | `node` | `hole`; `view: source|prices|diff|outline|map`; `against` for a diff.
- **`finish`:** registered only at 10% or less of the budget left. Returns the archive and points left.
- **The Pi extension ↔ harness protocol stays JSON**, now as hidden `arena protocol`.
- **The ledger keeps settle rows only.** Reports have one spend figure.
- **Run record** adds the `code` block (commit, dirty, models hash, Pi version).

### Speed baseline and gate
- `arena lean bench` measures, per benchmarked row and toolchain: cold and warm header open, warm compile p50 and
  p95 under the standard check mix (sorry probe, reference, small edit, error), splice-edit time for a late
  against an early step, and per-worker PSS. Results are saved as a versioned baseline.
- **The v6 baseline:**
  | Row (toolchain) | Warm-up (header open) | Edit p50 / p95 | Reference p50 / p95 | Sorry probe | Error draft | Min free memory |
  |---|---|---|---|---|---|---|
  | Core.InitsUpdatesComm (Strata, v4.29.1) | 8.2 s | 0.5 / 0.5 s | 0.3 / 0.5 s | 0.3 s | 0.3 s | 21.1 GB |
  | putnam_1964_b2 (Mathlib, v4.25.0) | 30.8 s | 12.2 / 13.5 s | 2.3 / 11.7 s | 0.2 s | 0.2 s | 18.1 GB |
  | Cslib.SKI (CSLib, v4.33.0-rc2) | 5.6 s | 0.2 / 0.3 s | 0.2 / 0.2 s | 0.2 s | 0.2 s | 20.7 GB |

  Recorded 2026-10-10 on an idle machine with the existing load tool: 1 run, model lane only, 8 checks per row,
  the slow kind off. All real criteria passed: 0 timeouts, 0 fresh opens after warm-up, 0 orphans. Raw output is
  in `research/v7-probes/lean-bench/`. The Putnam edit time reflects the row's heavy reference proof (about
  120K heartbeats), not the machinery. Before v7 relies on this baseline it is extended with ArkLib (v4.28–v4.31,
  the largest headers) and with PSS per worker.
- **Acceptance:** v7 matches or beats the baseline on every figure within a tolerance of +10% for p50 and +20% for
  p95 (measurement noise), and must be faster on header opens per campaign. Any later change that regresses a
  figure beyond tolerance fails the gate, with a report of the figure, toolchain and size.

## Testing Decisions

- **A good test checks external behaviour through a seam, never internals.** No tests restate configuration,
  assert that a mock was called, copy literals from source, or exercise dataclass defaults. Delete the existing
  tautological tests. Write new tests only where a bug costs points, money or time.
- **Seam A, the campaign protocol** (prior art: the existing protocol tests). It covers:
  - the five tools' replies and schema;
  - error naming and per-item errors;
  - graph operations and their exact edges;
  - focus filing;
  - route assignment and hysteresis;
  - archive cells;
  - the map;
  - the stall detector;
  - salvage outcomes on fixture drafts;
  - auto-assembly;
  - price rows and instant token quotes.

  Uses fixture rows with a fake Lean for speed, and real Lean behind a marker.
- **Seam B, a Pi run with a fake provider** (prior art: the existing fake provider wire and fake OpenCode
  support). It covers:
  - the actual-cost stop after the first call that reaches the limit, and never before;
  - outage backoff against error loop;
  - `finish` appearing at the exact fraction;
  - the MiMo thinking policy on tool-result turns;
  - malformed and null argument handling;
  - journal records (blob hashes, ids, turn index) sufficient for an exact replay.
- **Seam C, the Lean service client** (prior art: the existing Lean session tests and the load tool). It covers:
  - the measure version is the newest listed (a test over all 15 rows);
  - a timeout returns partial messages and keeps the model lane warm;
  - cross-version warm-up never evicts the model lane;
  - REPL pool and LSP lane give the same pass/fail and heartbeats within tolerance;
  - the **speed gate** against the recorded baseline.

  Real Lean, behind a `slow` marker, one Lean process at a time.
- **Pure units with no seam:**
  - template parsing, placeholder coverage, one-rule-one-place consistency across skill, packet and tool
    descriptions, the literal lint and the neutrality grep on rendered text;
  - the official token counter on all 15 rows equals `proof_length`;
  - scoring rates;
  - the route signature on fixture proofs;
  - `arena submit` gates on fixture rows (a modified statement, `sorry`, a failure on one toolchain each block the
    file);
  - filter parity with the official app.
- **Isolation.** Machine readings (fair share, memory, swap, disk) are injected. No test reads `/proc` or live
  sessions.
- **Targets.** About 80–120 Python tests in under 60 s without Lean. TS keeps `node:test`, run by node. No port of
  tests for v6 tool shapes.
- **The v7 campaign** (ticket 20, owner-launched) is not part of the suite. Two rows: the best-scoring
  putnam_1964_b2 (98.54) and the worst Cslib.SKI.parallelReduction_diamond (70.37). DeepSeek v4.1 flash runs v6 and
  v7 on both at $0.50 (proxy, bookkeeping share, tool errors, calls before the first compile, share of compiles
  using an operation). MiMo 2.6 Pro runs v7 on both as the new-model check.

## Out of Scope

- Remote search services (Loogle, LeanSearch, LeanFinder, hammer premises). Offline only for now (D19).
- Harness-run suggestion engines and the pre-run sweep (D30). Definition-unfolding library ranking (D33).
- Declared ideas and route credit (D16, D28). Hand-labelled route validation (D29).
- Fresh context per stall move and parallel islands: later experiments, only if diversity does not improve (D22).
- Relay or multi-model runs, adaptive thinking, per-model tool profiles.
- A local Loogle build or an embedding search index, unless name, type and text search prove insufficient.
- The closed-track $3 budget. Run limits stay at or below $2.
- Moving the package to a `src/` layout. Using bun.
- Uploading submissions: `arena submit` prepares files only. The owner uploads.

## Further Notes

- **Order of work** (plan §10, D36, D38, D41): one straight stack of GitButler branches `v7/<NN>-<slug>`,
  implemented one ticket at a time (00-03 by the orchestrator, 04-19b by Luna 6 in Codex, 20 by the owner), each
  reviewed before the next. Nothing merges to main until the owner says so. Ticket files are in
  `.scratch/arena-harness-v7/issues/`.
  - 00 uv; 01 removals and ruff; 02 actual-cost stop; 03 CLI skeleton, vendor adapter, MiMo provider (all done);
  - 04 tools into the CLI, `arena doctor`; 05a agent-text format, renderers, packet/skill/memory moved; 05b
    messages moved, literal lint; 06 run-control fixes; 07 Lean speed baseline and gate;
  - 08a Lean service process; 08b lanes, memory, goals and snippets on the LSP lane; 08c callers, tests, gate;
    08d REPL pool and header trial; 09 scheduler;
  - 10a graph core; 10b per-step goals; 11 routes, archive, map, stall; 12 salvage and assembly; 13 prices;
    14 search;
  - 15a tool handlers beside the old tools; 15b TS tool surface, MCP server removed; 15c old tools deleted;
    16 full text rewrite;
  - 17 replay; 18 viewer tab; 19a `arena submit`; 19b cross-run recombination;
  - 20 the owner's paid campaign (D37).

  Real dependencies: 04←03; 05a←04; 05b←05a; 06←02,04,05b; 07←04,06; 08a←07; 08b←08a; 08c←08b; 08d←08c;
  09←08c; 10a←04,05b; 10b←10a,08c; 11←10a; 12←10a,08c; 13←10b,11,08c; 14←04,05a; 15a←05b,11,12,13,14;
  15b←02,15a; 15c←15b; 16←15c; 17←05b,10a; 18←17; 19a←10a,13; 19b←19a; 20←16,06.
- **Text is written once:** the full rewrite (every word earns its place) happens in ticket 16, against the final
  tools, using the verbatim move from tickets 05a/05b as the baseline.
- **Probe evidence the implementer must not undo without new data:**
  - lineage cannot be inferred from text (48% agreement at best);
  - fixed phase shares hurt (bests come at 88–99% of spend);
  - salvage needs no size threshold (54%, flat across sizes);
  - the route signature mix is stable (0.991);
  - the K1 archive key fits the map (median 9 cells);
  - least-visited stall targets were no better than random offline (hence the A/B);
  - the sweep found nothing (0 of 349);
  - unfolding hurt ranking;
  - the library top 60 supplied 6% of best-proof names, including key lemmas;
  - heartbeats are measured on the newest toolchain;
  - our wrapper beats the organizers' `#count_heartbeats` on fidelity.
- **Uncommitted planning state at spec time:**
  - the plan;
  - both submodule bumps;
  - a three-line loader fix for the new upstream sibling import;
  - analysis scripts in a gitignored folder, to move into a tracked analysis folder.
- **Neutrality** remains a hard rule for every template, reply and harness notice: graph position and numbers
  only, never a kind of proof.
