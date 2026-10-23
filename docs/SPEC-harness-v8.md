# Harness v8 specification

Sol orchestration, parallel DeepSeek proof search, durable experiments, exact lineage, and agent-text overhaul.

Status: ready-for-agent. The user confirmed reuse of the v7 test seams with adjustments for fast development feedback. This document specifies behavior and does not claim implementation or authorize paid evaluation.

The current decisions in [plan §6](PLAN-harness-v8.md#6-current-v8-design-sol-orchestrator-and-parallel-deepseek-search-2026-10-18), including the packet/output contract in §6.12, are the source of agreement. Earlier conflicting proposals in the plan and v7 behavior are historical. This is v8 extending the completed v7 harness and newer local runtime work.

## Problem Statement

The operator needs a reproducible, from-scratch proof-optimization harness that improves cold-verified score per dollar within the competition's per-problem spend constraint. One model currently performs strategy, context gathering, and experimentation. This spends expensive model turns on repeated lookups and leaves independent proof hypotheses unexplored.

Adding workers without changing the surrounding architecture would introduce new failures. Independent sessions could consume one another's updates, change shared focus, lose alternate derivations when proofs deduplicate, or outlive the orchestrator. Separate session spend limits would not implement the agreed shared-cost stop. More model concurrency could create expensive Lean contention without useful proof gains.

Scratch exploration is insufficiently durable and cannot yet promote a precisely anchored result within its own call. Submitted scratch code is now retained, but stable experiment identities, outcomes, dependencies, and promotion remain incomplete. The served graph and replay do not yet preserve and expose all the identities and exact relationships required for concurrent agents.

Packets and tool replies also need a coordinated overhaul. Useful goals and definitions disappear through clipping or relevance-blind selection. Source coordinates and import descriptions can be wrong. Top-level cost tables obscure expensive nested work. Raw pin hashes, repeated locals, signatures, legends, and graph summaries consume attention while critical facts are absent. A successful implementation must improve the evidence available to agents, not merely shorten text.

## Solution

Retain Pi and the existing pinned Lean infrastructure. Sol owns strategy and directs at most two active DeepSeek V4.1 Flash sessions toward distinct whole-proof or step-anchored hypotheses. Delegation returns immediately. Sol can pursue another route or wait for evidence without a paid polling turn. Workers publish useful candidates as they appear, independently of assignment completion.

All charged activity uses one actual-cost ledger and the same $2.50 stop threshold, leaving $0.50 competition headroom. There are no reservations, model allocations, per-job dollar pools, or final-turn reserve. Sol continues until this spend stop; infrastructure failures and operator interruption remain distinct outcomes.

The team owns its agent-produced proofs. A verified worker candidate can become the submission without a second Sol approval. Harness-generated combinations require agent compilation or selection of that exact proof. Lean remains the correctness authority, including all required compatibility checks and independent cold acceptance.

Treat scratch calls as durable, isolated experiments. When an invocation defines an exact target-proof replacement, scratch promotes it through the normal compile path within that same call and returns the resulting evidence. Retain exact submitted artifacts, outcomes, inputs, actors, and alternate derivations through storage, graph serving, replay, export, compaction references, and restart.

Give agents concise, complete working views built from shared structured evidence. Default packets contain actionable theorem context, structural overview and nested hotspots, relevant declarations, and current findings. Full raw evidence remains retrievable. The served graph exposes canonical proofs with expandable attempts, derivations, experiments, and evaluations.

## User Stories

### Operator: objective, spend, and lifetime

1. As an operator, I want the same harness to optimize verified proof score per dollar, so that lower model prices produce useful search rather than merely more tokens.
2. As an operator, I want one $2.50 actual-cost bucket shared by Sol and all workers, so that independent sessions cannot behave as separate budgets.
3. As an operator, I want the remaining $0.50 treated as competition headroom, so that it is not silently available to further agent activity.
4. As an operator, I want the spend stop to use actual recorded costs only, so that estimates and reservations cannot end useful search early.
5. As an operator, I want retries, compaction, cancelled charged calls, and late settlements counted once, so that reports include all recorded API spending.
6. As an operator, I want the run to stop model activity when actual cost reaches the threshold, so that no new provider request starts after that stop.
7. As an operator, I want in-flight settlements retained after the threshold is crossed, so that overshoot remains visible rather than disappearing from accounting.
8. As an operator, I want Sol to continue working until the spend stop, so that plateau, voluntary finish, and continuation counts cannot end a successful search early.
9. As an operator, I want failures and operator interruptions reported separately from budget exhaustion, so that incomplete runs are not presented as normal completion.
10. As an operator, I want wall time and resource use reported without imposing a search deadline, so that evaluation follows the agreed competition objective.

### Sol: strategy and delegation

11. As an orchestrator, I want to assign a distinct whole-proof hypothesis, so that a worker can discover a larger theorem or alternative argument.
12. As an orchestrator, I want to assign an experiment against an immutable proof step or range, so that focused work has an exact starting point.
13. As an orchestrator, I want delegation to return a job identity immediately, so that a slow worker request does not block my reasoning.
14. As an orchestrator, I want to inspect queued and active jobs, so that I can distinguish pending assignments from work actually using a model session.
15. As an orchestrator, I want to await relevant evidence without generating provider requests, so that waiting does not consume the shared budget.
16. As an orchestrator, I want useful findings delivered before a worker finishes its assignment, so that I can act on discoveries promptly.
17. As an orchestrator, I want to cancel a stale hypothesis, so that obsolete work stops consuming model and Lean resources.
18. As an orchestrator, I want to resume the same hypothesis's conversation, so that follow-up work retains its previous findings.
19. As an orchestrator, I want a distinct hypothesis to start a fresh conversation, so that unrelated failed routes do not contaminate its context.
20. As an orchestrator, I want stall statistics to inform rather than force route changes, so that search strategy remains my responsibility.
21. As an orchestrator, I want to replace the shared strategic whiteboard, so that the team has one coherent strategic view.
22. As an orchestrator, I want compact worker evidence with original references, so that I can use results without reading complete worker transcripts.

### Worker: independent proof search

23. As a worker, I want the assigned hypothesis, exact parent, relevant context, and earlier findings, so that I can conduct a genuine independent experiment.
24. As a worker, I want whole-proof context when the assignment is structural, so that I am not restricted to local tactic deletion.
25. As a worker, I want compile, goal, search, read, and scratch, so that I can explore and test real Lean proofs.
26. As a worker, I want isolated conversation history and actor-local focus, so that another session cannot redirect my next edit.
27. As a worker, I want attributed observations and hypothesis-local notes, so that I can preserve discoveries without replacing Sol's strategy.
28. As a worker, I want to publish a passing candidate immediately, so that assignment completion does not delay a useful result.
29. As a worker, I want to finish an exhausted assignment and release my slot, so that the team can activate another hypothesis before the global stop.
30. As a worker, I want relevant shared findings delivered independently to me, so that another actor cannot consume my update stream.

### Team: proof ownership and verification

31. As an operator, I want a worker-produced proof to be eligible on the same basis as a Sol proof, so that it can win without another paid approval turn.
32. As an operator, I want harness combinations to require agent compilation or explicit selection of their exact text, so that an unapproved transformation cannot become the submission.
33. As an operator, I want eligibility and correctness tracked separately, so that approval is never mistaken for verification.
34. As an operator, I want primary, full-compatibility, and cold outcomes distinguished, so that a provisional success does not appear certified.
35. As an operator, I want already-submitted checks to finish at the spend stop, so that eligible discoveries can still be certified.
36. As an operator, I want new proof transformations to stop with model search, so that closing work cannot become a hidden optimizer.
37. As an operator, I want live salvage and assembly retained as traced proposals, so that useful existing assistance remains available under the ownership rules.

### Agent: durable scratch experiments

38. As an agent, I want general scratch checks and examples, so that I can answer small semantic questions without filing a target proof.
39. As an agent, I want exact scratch input retained before execution, so that failures, timeouts, and context errors do not erase the experiment.
40. As an agent, I want a stable experiment identity and complete diagnostics, so that I can retrieve an earlier result without repeating the call.
41. As an agent, I want explicit helper dependencies, so that an experiment does not rely on hidden declarations from an earlier process.
42. As an agent, I want scratch to promote an exactly anchored replacement itself, so that I do not need to retype it or make a second tool call.
43. As an agent, I want promotion to use the ordinary compile and lineage path, so that the resulting candidate has normal evidence and eligibility.
44. As an agent, I want a concrete reason when promotion is unavailable, so that I can distinguish useful exploration from a complete target candidate.
45. As an agent, I want the original experiment and a failed promoted compile both retained, so that one failure does not erase useful evidence.
46. As an agent, I want the harness to supply known actor, job, and context metadata, so that I do not spend tokens copying bookkeeping into calls.

### Operator: exact history and serving

47. As an operator, I want canonical proof identity separated from attempts, so that identical proof text can retain discoveries by multiple actors.
48. As an operator, I want every exact construction input and role retained, so that a merge or promotion has reproducible ancestry.
49. As an operator, I want delegation ancestry separated from proof derivation, so that assigning work does not invent a proof edge.
50. As an operator, I want failed, duplicate, cancelled, and successful attempts accessible, so that useful history survives graph simplification.
51. As an operator, I want original serialized lineage and artifact bytes retrievable unchanged, so that later projections cannot replace evidence with inferred ancestry.
52. As an operator, I want export, reload, replay, and resumed sessions to preserve all relationships, so that retained lineage is the same as recorded lineage.
53. As an operator, I want a canonical proof graph with expandable attempts and alternate derivations, so that the default view is readable without deleting history.
54. As an operator, I want node details linked to their exact actor, job, request, tool call, and evaluations, so that I can inspect what created a candidate.
55. As an operator, I want all active jobs and their waiting reasons visible, so that an intentionally waiting orchestrator does not look hung.
56. As an operator, I want actual spend grouped by actor and job without duplicated charges, so that attribution agrees with the run total.
57. As an operator, I want historical missing code and ambiguous joins marked as missing or ambiguous, so that older records are not repaired by guessing.

### Agent: packets, tools, and memory

58. As an agent, I want the exact theorem, scope, constraints, and useful source references, so that I can write a valid replacement.
59. As an agent, I want the compatibility requirement without raw revision hashes in routine text, so that environment bookkeeping does not obscure the task.
60. As an agent, I want statement definitions selected from the actual target, so that a conclusion predicate is not displaced by auxiliary declarations.
61. As an agent, I want complete goal conclusions with correctly scoped hypotheses, so that clipping cannot hide the obligation.
62. As an agent, I want explicit extraction and display coverage, so that missing context is distinguishable from intentionally omitted detail.
63. As an agent, I want accurate imports and source coordinates, so that available declarations and source locations are trustworthy.
64. As an agent, I want useful nearby lemmas protected during fitting, so that raw telemetry does not displace a structural proof route.
65. As an agent, I want one readable declaration catalog with role tags, so that repeated names and signatures do not consume the packet.
66. As an agent, I want top-level proof structure and nested measured hotspots, so that a large branch does not conceal its expensive substeps.
67. As an agent, I want proof totals separated from step rows, so that inapplicable fields and compatibility do not appear as confusing table cells.
68. As an agent, I want missing measurements distinguished from zero and pending checks, so that absence of evidence is not interpreted as a cheap step.
69. As an agent, I want published scoring denominators separated from locally measured profiles, so that I compare compatible quantities.
70. As an agent, I want complete evidence behind every shortened preview, so that compact presentation does not destroy access to the original.
71. As an agent, I want search misses distinguished from invalid requests, so that I do not waste a turn correcting an already-valid query.
72. As an agent, I want trial replies to distinguish open goals from syntax or type errors, so that I know how to continue.
73. As an agent, I want usable signatures, valid Markdown, and explicit clipping, so that tool formatting preserves meaning.
74. As an agent, I want relevant graph and job changes rather than unchanged full maps, so that each reply emphasizes new evidence.
75. As an agent, I want schemas and inspection help to describe the same interface, so that documented inputs actually work.
76. As an agent, I want a generic search cheatsheet without saved task solutions, so that learned methods help from-scratch search without injecting answers.
77. As an agent, I want optional notes only for new intent, so that bookkeeping never demands redundant prose.
78. As an agent, I want compaction to retain strategy and exact evidence references, so that a resumed session can recover complete original facts.

### Operator: resources and evaluation

79. As an operator, I want model concurrency separate from Lean admission, so that two reasoning workers do not imply two heavy Lean compilations.
80. As an operator, I want foreground and promising verification work prioritized over speculative experiments, so that parallel search preserves useful interactive capacity.
81. As an operator, I want the existing memory safeguards and warm-worker reuse preserved, so that new orchestration does not reintroduce resource failures.
82. As an operator, I want cancelled workers counted as active until they exit, so that cancellation cannot admit excess live sessions.
83. As an operator, I want offline scripted runs to prove lifecycle and accounting behavior before paid search, so that correctness does not depend on API spend.
84. As an operator, I want real-Lean validation separated from fake checks, so that test reports state what has actually been established.
85. As an operator, I want matched-spend, from-scratch comparisons, so that multi-agent gains cannot come from larger budgets or saved proof seeds.
86. As an operator, I want repeated and held-out evaluation before score claims, so that one lucky worker discovery is not treated as general improvement.
87. As an operator, I want model and track configuration separated from orchestration, so that an eligible open-track model can reuse the architecture.

## Implementation Decisions

### Authority and architecture

1. The current v8 decisions supersede conflicting legacy behavior, including voluntary finish, fixed model allocations, forced route changes, hidden stall-triggered delegation, and post-agent proof improvement.
2. Retain Pi and the existing Lean verification service. Arena owns delegation, actual-cost accounting, durable jobs/results, Lean admission, proof history, and eligibility. Do not add another model-based proof judge.
3. Keep scheduling and worker lifecycle in a dedicated orchestration component rather than expanding the campaign component into a second agent runtime.
4. Sol may experiment directly while directing worker hypotheses. Workers perform genuine proof search and receive all five existing proof-search tools. Sol alone controls delegation and cancellation; workers cannot recursively delegate or replace the strategic whiteboard.
5. Use distinct durable identities for actor, Pi session, delegated hypothesis/job, provider request, tool invocation, attempt, experiment, proof, derivation, observation, and evaluation. Resolve immutable input anchors before asynchronous work starts.

### Spend and stopping

6. Production search uses one $2.50 actual-cost stop threshold across Sol and all workers, with $0.50 retained outside agent availability. Count every charged model activity, including retries and compaction.
7. Do not reserve estimated cost, allocate model pools, impose per-job dollar caps, or protect a final-turn reserve. Trial/context/output configuration may bound an experiment but cannot introduce a hidden second spend policy.
8. Settle each provider request once. Aggregate actual settlements atomically across concurrent sessions and persist their identities so replay or recovery cannot add them twice.
9. The threshold is a post-call stop. Concurrent requests already in flight can settle after it is crossed; retain those costs. Do not promise reservation-style cap guarantees or a single-call overshoot bound for multiple sessions.
10. On the shared stop, prevent new provider requests and new proof transformations, wake waiters, cancel worker activity, and finish already-submitted checks and required cold certification. Do not create a final assembly, salvage edit, or optimizer candidate while closing.
11. Sol has no voluntary successful exit, plateau termination, or continuation-count escape. An ended Sol turn before the threshold must continue or enter event-driven waiting when appropriate. Provider failure, infrastructure failure, and operator interruption retain distinct stop reasons.

### Delegation and Pi lifecycle

12. Support whole-proof hypotheses and exact node/step/range experiments from the first prototype. Delegation returns a durable job identity and current lifecycle state immediately.
13. Limit active DeepSeek model sessions to two initially. Registering a queued assignment does not activate another session. A worker may complete or exhaust its assignment and release its active slot before the global stop.
14. Start a fresh conversation for a distinct hypothesis. Resume the same conversation for follow-ups to that hypothesis, even if its process was previously released. Persist session paths and hypothesis mappings.
15. Support status, continuation, cancellation, and event-driven waiting. Publish candidates and supporting evidence immediately rather than withholding them until job completion. Deliver updates independently per actor.
16. Waiting must not generate provider polling calls. It must wake on relevant evidence, assignment settlement, cancellation, global stop, and failure, including events that arrive near registration of a waiter.
17. The initial integration candidate keeps Sol's JSON runner and uses isolated child Pi processes controlled through RPC. Confirm its lifecycle through the offline runner seam before committing to a larger runner migration. Embedded sessions or moving Sol to RPC are technical alternatives if the current runner cannot satisfy this contract.
18. Distinguish RPC acceptance from completion, and a turn ending from an assignment settling. Continuously drain child output and correlate session-scoped request identities. Clear queued prompts before aborting; count a cancelled child against concurrency until actual exit.
19. Reconcile the repository Pi pin and installed runtime deliberately. Record the version used and exercise resume, tool allowlists, retries, malformed arguments, and cancellation. Do not silently change runtime versions between evaluation arms or import unreleased behavior as an established capability.
20. Stall signals remain informational. Sol decides hypothesis restarts and strategic route changes. Ordinary Pi context compaction remains automatic and preserves durable recovery references.

### Shared search history and ownership

21. A proof node represents immutable target/proof identity. Attempts record invocations, including unsuccessful or duplicate discoveries. Derivations record exact construction operations and every input role. Delegations record assignment ancestry, not proof ancestry.
22. Evaluations attach to exact proof/experiment and source/toolchain context, with mode, metrics, diagnostics, timing, and verification state. Observations remain attributed claims linked to evidence, not substitute certificates.
23. Deduplicate exact proof checks within matching contexts while retaining every attempt and alternate derivation. Do not erase a second actor's discovery because its text equals an existing proof. Different pins or environments cannot reuse evidence solely because proof text matches.
24. Exact lineage is generated by construction operations. Named parents, default filing, model-written inspiration, and similarity are separate relationships. Never infer an exact construction from temporal order or text resemblance.
25. Retain original serialized lineage records and referenced artifacts unchanged and retrievable. Later facts are additional records. Storage, graph projection, export/reload, replay, and restart must preserve all original inputs, roles, actors, identities, and alternate derivations.
26. Use one authoritative history projection for tool views, serving, replay/export, and lineage analysis. Keep shared best/frontier separate from actor-local focus and delivery cursors.
27. Either Sol's or a worker's compiled candidate is agent-owned. A second Sol approval is unnecessary. A harness-generated proof requires agent compilation or explicit selection of its exact identity/text; approval of an ancestor never approves a transformed descendant.
28. Eligibility is distinct from correctness. Every submission still requires full compatibility and independent cold acceptance on every required environment. Local scratch success and fast checks are provisional evidence only.
29. Keep live background salvage and assembly as traced proposals subordinate to foreground and promising verification. Preserve exact input/output relationships and the agent-eligibility requirement. Admit no new transformations after the spend stop.
30. Costs belong to provider requests. Group them by actor/job without assigning the entire request cost independently to each of several candidates it produced.
31. Notes are optional for new rationale. Inherit hypothesis references rather than duplicating their prose. Do not reject a candidate, block promotion, or issue reminders for missing notes.
32. Sol owns replacement of the shared strategic whiteboard. Workers append attributed observations and maintain hypothesis-local notes. Summaries retain references to original observations and cannot replace retained evidence.

### Scratch experiments and promotion

33. Retain general command, signature, and example exploration. Scratch environments remain isolated. Reuse helpers only through explicit recorded dependencies, never residual process state.
34. Persist exact validated input before context construction or Lean execution. Retain outcomes, context, diagnostic artifacts, measured quantities with provenance, actor/session/job/call links, timing, and cancellation. Give the model a stable experiment identity and retrieval route.
35. An anchor identifies the immutable proof and exact replacement step, range, or hole. Record which submitted code is the replacement. Resolve inherited job anchors before execution. A pretty-printed goal is insufficient to reconstruct a Lean environment.
36. If the original invocation unambiguously defines a candidate, scratch constructs it and invokes the ordinary compile path within that invocation. The invocation authorizes that exact replacement. Do not require a separate promotion call or retyping, and do not silently combine unrelated experiments.
37. Promotion must include legal helper dependencies or explain why the experiment is not promotable. General checks, unrelated examples, and incomplete snippets remain experiments. An unanchored full target proof is promotable only when target and exact proof extraction are unambiguous.
38. Return experiment outcome and promotion outcome separately, including a concrete non-promotion reason or candidate/attempt/derivation references, diagnostics, measured deltas where available, and fast/full/cold status. Retain failed promoted compiles without erasing the original experiment.
39. Do not present scratch measurement or proof holes as certified target-proof success. Apply normal validity, compatibility, and cold gates to promoted candidates.

### Lean service and resource admission

40. Separate model-session admission from Lean admission. Initially allow one DeepSeek Lean compilation in flight. Foreground Sol work and promising full checks precede speculative worker experiments; opportunistic profiling and background transformations are lowest priority.
41. Implement actual scheduling/admission behavior rather than assuming a new lane name adds priority. Validate contention at the existing service-client boundary.
42. Preserve existing warm-worker reuse keyed by matching project/document state, pinned toolchains, demand-driven allocation, cooperative yielding, checker shutdown, and the 5 GiB admission safeguard. Do not open speculative heavy workers based on idle CPU alone.
43. Retain resource telemetry and distinct failure/queue states. Wall time and foreground latency are diagnostic measurements, not a mandatory percentage gate for accepting score improvements. Memory safety and verification correctness remain required.

### Packet, template, and reply contract

44. Rework content selection, structured evidence, templates, and formatting together. Existing model-facing text remains template-owned. Shared facts and tool schemas must not acquire separately maintained packet, reply, inspection, or viewer interpretations.
45. Default agent text carries the exact statement, relevant scope/imports, validity constraints, scoring, compatibility requirement, useful source handles, and complete proof access. Raw source/toolchain hashes stay in retained provenance and on-demand evidence; do not repeat them in routine packets, replies, or memory.
46. Separate target-statement dependencies from generated auxiliary declarations. Prioritize the target's predicates and types before count limits. Preserve useful nearby reusable lemmas before lower-value raw occurrence inventories.
47. Parse qualified imports and retain actual source identity/coordinate systems. Only label positions as target statement/proof when inside the target span. External syntax must not become fabricated negative target-relative lines.
48. Preserve goal conclusions when limiting display. Group shared context and identify each branch/case. Expose extraction completion, captured/expected goal coverage, clipping, and display omissions separately. Do not fill a packet with repeated unavailable entries or call section presence proof of usefulness.
49. Preserve the exact reference artifact and provide a readable line-numbered view with an explicit coordinate mapping. Formatting cannot alter proof bytes or lineage. Shortened goals, signatures, diagnostics, and source views retain complete retrievable originals.
50. Present a separate proof summary, structural overview plus nested measured hotspots, and full details on demand. Top-level edit units are not a complete profile. Include parent path, exact range, proof identity, and omissions for nested spans; indentation alone cannot establish a legal edit anchor.
51. Use inclusive HB and proof tokens in the default structural overview. Keep self HB for detailed attribution. Distinguish measured zero, missing, pending, and inapplicable. Omit all-missing columns and unconditional legends, with one meaningful coverage statement for important unavailable measurements.
52. Remove `pts_if_gone` from default output. Any detailed attributed-cost estimate must state the assumption that other costs remain unchanged. It is not a measured optimization or a general upper bound. Do not sum overlapping token spans or nested inclusive costs.
53. Label published scoring reference and locally measured profile separately. Associate measurements with proof, context, pin, and mode. Do not assign a reference score to a mixed-provenance measurement and imply it was computed from that measurement.
54. Build one readable declaration catalog with stable handles, signatures, source locations, and role tags. Demote repeated occurrence telemetry and irrelevant generated machinery. Do not globally merge branch-local variable names or sacrifice essential arguments/conclusions to ambient binder prefixes.
55. Tool replies emphasize outcome, changed evidence, uncertainty, and retrieval. Separate provisional best, all-pin verified best, and cold status. Preserve exact operation/input references and meaningful diagnostic detail.
56. Render valid Markdown fences, descriptive headings/columns, explicit clipped previews, and conditional explanations. A normal no-match search is not an input error. Open goals are not parser/type errors. Suggestions must be relevant.
57. Deliver compact graph/job changes by actor-local cursor, with full-state views available explicitly. Do not repeat unchanged maps, legends, hypotheses, or metadata the harness already knows.
58. Generate inspection help from registered tool schemas and shared descriptions, preserving nesting, types, bounds, and defaults. Remove legacy finish help. Sol management tools and worker tool restrictions must be represented accurately in their respective schemas and rendered documentation.
59. Share a concise generic search cheatsheet covering whole-structure theorems, symmetry, native project APIs, distinct hypotheses, local context, focused tests, current-candidate profiling, combined token/HB tuning, and evidence reuse. Keep task-specific solutions and analyst hybrids outside from-scratch packets. Qualify tactical heuristics and do not impose mandatory lookups or local-only edits.
60. Compaction/resume retain strategy, actor-local jobs/focus, useful failures/findings, and exact durable references. Summaries are working context, not replacements for retained artifacts or lineage. Use actual shared-cost wording and remove obsolete finish or forced-reroute instructions.

### Serving and rollout

61. Default serving shows canonical proof nodes with expandable attempts and alternate derivations, plus a complete experiment/job log. Node detail exposes all relevant actors, calls, inputs, observations, evaluations, eligibility, deltas, original artifacts, and lineage.
62. Preserve lazy reasoning/call inspection and the distinction between actually delivered and untrimmed results. Join new records by explicit identities; retain explicit missing/ambiguous status for old logs rather than inventing joins or missing scratch code.
63. Show all actors/jobs and their model, Lean queue/check, waiting, and cancellation states. Show one actual spend total with actor/job breakdowns. Intentional event waiting is not inactivity failure.
64. Preserve newer local runtime improvements and historical packet exports. Implement coherent reviewable changes against current callers; do not replace local improvements with an older branch snapshot.
65. Introduce the architecture through offline lifecycle checks, saved-proof real-Lean checks, then separately authorized paid evaluation. Both comparison arms use the same total cap, pins, runtime, and relevant packet improvements, with no saved-proof seed.
66. Evaluate the three contrasting development rows first, repeat paired runs before improvement claims, then expand to all 15 development rows and held-out evaluation. Report verified score and score per actual dollar, with wall time, duplicates, useful discoveries, context-only turns, queues, PSS, swap/PSI, and failures as explanatory metrics.
67. Keep orchestration independent of model/track selection. Reusing it for the open track does not require a new agent architecture. Model eligibility remains a configuration concern, not an assumed permission for paid evaluation.

## Testing Decisions

The user confirmed reuse of the v7 boundaries, allowing adjustments that keep development feedback fast. Seam selection does not authorize running a broad slow suite or paid evaluation.

### Good tests

Test externally observable outcomes where an error loses points, money, evidence, or reliable execution. Prefer a complete request/run and its returned results/artifacts to assertions about internal calls, data-class defaults, copied constants, or source text. Use injected machine readings and temporary runs. Do not read another live session or rely on host load for deterministic coverage.

Keep a small number of stable boundaries. New orchestration behavior should be exercised through the runner and existing tool protocol instead of exposing every scheduler helper as a new test API. Pure parsing/rendering cases remain fast supporting tests rather than substitutes for end-to-end acceptance.

### Minimum fast tests per ticket; E2E once at the end

The user's October 19 instruction supersedes the earlier per-unit full-suite and selected live-test policy. Keep tests minimum and fast.

- One small focused behavior check per ticket is the default. Reuse or extend an existing test when possible; do not add one test per acceptance bullet or cosmetic edit.
- Aim for seconds, normally 5–15 seconds and no more than 60 seconds for the selected smoke. Use fixtures, injected outcomes, event barriers and temporary runs. Do not use sleeps or start real Pi/Lean/services in routine ticket checks.
- Run only that affected smoke during development. A relevant targeted baseline and touched-file syntax/lint are sufficient when useful. Do not run the whole fast suite after each ticket or commit.
- Do not run entire slow files, real-Pi/Lean checks, worker warm-ups or resource matrices for every branch. No 30-minute ticket gate is required.
- Perform one consolidated final integration/E2E pass after the stack is implemented, including one broad fast-suite run, selected actual-Pi scripted journeys and selected real-Lean/cold checks. The seam scenario lists below are aggregate final coverage, not a list of mandatory tests per ticket.
- When the chosen smoke fails or demonstrates a specific neighboring risk, add only the focused check needed to resolve it. Keep assertions meaningful; do not conceal failures to meet the time target.
- Report per-ticket smoke evidence separately from deferred final E2E, actual Lean and paid search. Fast smoke success is sufficient to check out the narrow ticket; production readiness still needs the final integrated result.

### Seam A: campaign and tool protocol, with persisted evidence

Prior art is the existing fake-Lean graph support, campaign protocol coverage, five-tool tests, replay/viewer fixtures, and cache-only text/context fixtures. Exercise the real request handling and resulting stored/retrieved evidence with deterministic Lean outcomes.

Required behavior includes:

- Two actors retain independent focus and delivery while sharing candidates/frontier.
- Duplicate proof discoveries retain both attempts, actors, jobs, and alternate derivations while avoiding redundant matching-context checks.
- Exact construction relationships survive store, project, serve, export/reload, replay, and resumed-session recovery. Assert the original serialized record and artifact bytes remain retrievable, not only that a graph looks equivalent.
- General scratch input/outcome survives success, compile failure, timeout, cancellation, and context-construction failure. Unicode, line endings, and whitespace remain exact.
- Anchored scratch promotes within its original invocation, with exact replacement/dependencies and normal compile evidence. Non-promotable, helper-dependent, and failed-promotion cases retain explicit outcomes.
- Worker proofs are eligible without Sol ratification; harness combinations remain ineligible until exact agent compilation/selection. Approval of an ancestor does not approve a transformed proof.
- The spend-stop boundary permits existing checks and certification but files no new closing transformation.
- The served graph exposes canonical nodes plus all attempts, jobs, derivations, evaluations, and exact call joins; old missing/ambiguous records remain explicit.

Packet and reply acceptance at this seam uses the three preserved packet examples plus focused fixtures. Assert retained facts and retrieval, not simply smaller output or new snapshots. Cover:

- An earlier binder `by` before the real proof, a ninth target predicate, qualified imports, external source locations, long goal contexts, lost goal tails, and fitting that would otherwise remove useful earlier lemmas.
- Large top-level branches with expensive nested measured spans; clear parent/range identity, omission counts, and full-detail retrieval without implying arbitrary syntax is editable.
- Zero versus missing costs, all-missing columns, partial measurements, pending checks, and published versus measured heartbeat provenance.
- Long signatures, actual Markdown fences, valid search misses, invalid arguments, open versus erroneous goal trials, optional notes, and separate provisional/verified/cold status.
- Schema-derived inspection parity, exact tool allowlists, bounds/defaults, conditional legends, and no default raw pin hashes or obsolete finish instructions.
- Compaction working summaries preserve usable evidence references and retrieve complete originals after resume.

### Seam B: real Pi runner with a scripted provider

Prior art is the existing scripted provider extension and runner helper. Use actual Pi/extension lifecycle with deterministic provider responses and no paid API requests. Extend the existing boundary to multiple child sessions rather than simulating all agent behavior inside a scheduler unit test.

Required scenarios include:

- Sol receives a delegation acknowledgement and continues before a delayed worker response.
- At most two worker sessions are active; queued jobs activate when a worker completes or exhausts its assignment.
- A fresh hypothesis receives a fresh conversation; a follow-up resumes the original conversation and tool restrictions.
- A passing candidate arrives while its worker remains active; simultaneous findings reach all intended actors without cursor loss.
- Event waiting produces zero provider calls and wakes on findings, settlement, failures, cancellation, and global stop, including arrival near wait registration.
- Scripted charged turns, retries, compaction, and late/cancelled settlements produce one shared exact total. Concurrent settlements and recovery never duplicate charges.
- No stop occurs from reservations or per-model budgets. The threshold crossing stops new model requests while retaining actual in-flight settlements.
- Sol continues after an ordinary turn end, plateau signal, or legacy continuation threshold. An assignment can settle early without ending the run.
- Cancellation clears queued prompts, drains events, wakes waiters, and waits for child exit before releasing the concurrency slot. No orphan model worker survives the run.
- Failure reasons, shared-cost records, actor/job/call identities, actual delivered replies, and replay artifacts agree.

A fake provider does not make all service operations fake. Isolate or inject Lean work where necessary and label any real-Pi or real-Lean prerequisites. Offline lifecycle success cannot establish proof correctness or paid-model effectiveness.

### Seam C: existing Lean service client

Prior art is the Lean service/session and warm-worker tests, augmented with saved proof fixtures. Use real pinned Lean behind the existing slow-test convention on an idle, isolated service. Serialize actual Lean validation when required by machine limits; inject memory readings in deterministic admission tests.

Verify target-proof context extraction, intact goals/definitions, actual scratch isolation, promoted whole-proof reconstruction, full compatibility, and independent cold checks. Exercise separate model/Lean admission, one worker compilation initially, meaningful foreground/verification priority, matching warm-state reuse, memory safeguards, timeout recovery, and child/checker cleanup. Do not replace the behavior under test with a passing fixture.

Replayed saved proofs establish verification/runtime behavior, not from-scratch search quality. Real extraction fixes require actual Lean tests; renderer fixtures alone cannot prove the wrapper selected the right proof.

### Evaluation outside automated acceptance

Paid search is a separately authorized operator evaluation. Start with matched-cap from-scratch Sol-only and Sol-plus-two-worker pairs on SKI diamond, Core, and Fiberwise. The previously discussed $1.50 pilot total is a proposal, not the production threshold or spending authorization. Do not split that total into fixed model pools.

Use identical runtime, pins, packet policy, and total cap across arms. Repeat before attributing score improvements to orchestration. After a successful prototype, evaluate all 15 development problems with the intended $2.50 stop and retain held-out outcomes separately. Report failures and verification status alongside scores. Packet character reductions and cached-token shares are diagnostics, not evidence of dollar or score benefit.

## Out of Scope

- Replacing Pi, replacing the Lean verifier, or adding a second model-based proof judge.
- Hidden harness-triggered minions as the foundation, nested worker delegation, or more than two active DeepSeek sessions initially.
- Budget reservations, per-model allocations, per-job dollar pools, final-turn reserves, estimate-based stops, or promises that concurrent in-flight calls cannot cross the post-call threshold.
- Successful voluntary Sol exit, forced strategic rerouting/restarts, a competition search deadline, or a mandatory foreground-latency percentage gate.
- Automatically adopting a harness-transformed proof without exact agent compilation/selection, or creating new proof transformations during closing.
- A separate Pi/MCP exploration project, new cross-run recombination work, or a standalone open-track orchestration rewrite.
- Mandatory automatic per-lemma profiling. Agents may use ordinary focused scratch experiments to study lemma removal; deltas are context-dependent and not additive intrinsic lemma prices.
- Harness²-style meta-optimization inside the competition execution loop, task-specific saved solutions in startup packets, and uncontrolled best-of-history comparisons presented as a single from-scratch run.
- Paid provider calls, competition submission, pushing branches, or opening pull requests as part of writing this spec.
- Reconstructing missing historical scratch code or lineage by guessing, discarding original evidence during compaction, or changing unrelated local runtime/audit work.

## Further Notes

### Source decisions and traceability

| Requirement group | Planning/evidence source |
|---|---|
| Actual-cost stop, lifetime, architecture, team ownership | [Plan §§6.1–6.4](PLAN-harness-v8.md#61-agreed-policies) |
| Durable scratch and automatic promotion | [Plan §6.5](PLAN-harness-v8.md#65-scratch-as-durable-experiments) |
| Exact lineage and actor-local state | [Plan §6.6](PLAN-harness-v8.md#66-proof-identity-attempts-and-exact-lineage) |
| Served graph and strategic memory | [Plan §6.7](PLAN-harness-v8.md#67-served-graph-and-node-detail-requirements) |
| Ownership examples and evaluation sequence | [Plan §§6.8–6.10](PLAN-harness-v8.md#68-ownership-examples-checked-in-recent-runs) |
| Packet and tool-output content contract | [Plan §§6.11–6.12](PLAN-harness-v8.md#612-packet-and-tool-output-overhaul-content-contract) |
| Packet examples, hashes, and generic methods | [Preserved exports](packet-review-2026-10-18/README.md), [cheatsheet draft](packet-review-2026-10-18/GENERIC_CHEATSHEET_DRAFT.md) |
| Source-backed text defects and recommendations | [Content/tool review](reports/PACKET_CONTENT_AND_TOOL_REVIEW_2026-10-18.md) |
| Timing and cache evidence | [Timing audit](reports/V7_V8_TIMING_2026-10-18.md), [packet forensics](reports/PACKET_FORENSIC_AUDIT_2026-10-17.md) |
| Runtime improvements to preserve | [Runtime results](LEAN_RUNTIME_OPTIMIZATION_RESULTS_2026-10-16.md), [follow-up measurements](LEAN_RUNTIME_FOLLOWUP_MEASUREMENTS_2026-10-16.md), [lifecycle audit](reports/LEAN_WORKER_LIFECYCLE_2026-10-17.md) |
| v7 specification and testing precedent | [v7 spec](SPEC-harness-v7.md), [v7 local ticket brief](../.scratch/arena-harness-v7/ticket-brief.md) |

### Current state versus target

The existing scratch increment saves exact accepted code and its hash before execution. It does not implement the full experiment or promotion contract. Current single-actor graph, delivery, serving, and session accounting behavior must not be mistaken for completed multi-agent support.

The Pi runtime research established an integration candidate, not a successful Arena delegation test. The packet review established concrete defects and selection losses, not a measured efficacy benefit. Historical leaderboard, runtime, and model timing figures remain dated evidence, not current competitive claims or controlled speed comparisons.

Development should proceed in coherent units covering common identities/history, extraction and shared text views, isolated lifecycle and accounting, Lean admission, scratch promotion, serving/recovery, and staged evaluation. Keep behavior tests with the changes they verify. Preserve the current GitButler stack and other sessions' work. The individual implementation tickets are published in the local Markdown tracker; this spec does not begin production changes.

### Publication state

The user explicitly requested individual local Markdown tickets and removal of the confusing drafts. The [local ticket index](../.scratch/arena-harness-v8/README.md) now links all 24 ready-for-agent files, numbered 03–26. Every ticket contains its implementation context, contract, one fast Verify command and resolved GitButler rules from the shared template. No external issue tracker is used or needed for this requested local workflow. The obsolete draft directories/manifests have been removed.

### Implementation contract appendix, 2026-10-19

This appendix closes the concurrency and recovery gaps raised in review. It refines the existing decisions without changing actual-cost-only stopping, team ownership, scratch-managed promotion, or exact lineage. Ticket breakdown approval is separate from the settled architecture. This is a behavioral contract, not implemented runtime behavior.

#### A. Durable identity, idempotency, and event delivery

Every command has a harness-generated operation identity, run identity, actor/session identity, and canonical argument digest. Retrying the same operation with the same arguments returns its recorded receipt and results. Reusing that identity with different arguments is an error. Do not ask the model to supply bookkeeping identities already available from its invocation.

A job identity denotes one hypothesis across process releases and follow-ups. Each activation has a separate identity and coordinator generation. A provider request, including a charged retry or compaction request, has its own identity distinct from a Pi command, turn, or tool call. One settlement cannot charge multiple requests accidentally; grouped provider usage must identify its covered requests and cannot also settle them individually.

Durable events have a schema version, run-local monotonic sequence, event identity, operation/actor/session/job/activation references where applicable, event kind, and typed payload. Timestamp is descriptive, not ordering authority. Store original payloads/artifacts and exact lineage unchanged. A projection may add fields without rewriting its inputs.

Result cursors belong to actors. Reading a view does not consume another actor's evidence. Commit the actor's delivery cursor with the durable delivered-reply record, not when a shared summary is computed. After a transport crash, at-least-once delivery can repeat an event identity; consumers deduplicate it. Do not claim exactly-once remote delivery from a local file append. Full retrieval remains available independent of cursor progress.

#### B. Management tools and replies

The following logical tool names and fields form the initial contract. Registered schemas and rendered documentation must agree. The harness adds operation identity and actor metadata automatically. Surface schema renames only when required by verified Pi constraints and update the spec and callers together.

| Tool | Inputs | Observable result |
|---|---|---|
| `delegate` | `task`; for a fresh job, `scope` of `proof` or `step` and an immutable parent anchor; for a follow-up, existing `job_id` | Immediate durable receipt with job, activation/session, state, resolved anchor, and result cursor. A distinct hypothesis always creates a fresh job/session. A follow-up retains its original hypothesis and anchor; incompatible changes are rejected. |
| `jobs` | Optional job identities and actor-local event cursor | Current queued/active/settled/cancelling states, new evidence, waiting reasons, and complete-detail references. This read never starts model work. |
| `await_results` | Actor-local cursor and optional job selection | New matching evidence or a structured wake reason. No provider polling, and no waiting on a job that cannot generate another event. |
| `cancel` | Job identity | Idempotent cancellation receipt with current state. State remains cancelling and the slot remains occupied until actual exit or confirmed absence. |

Proof anchors contain immutable target/proof identity. Step anchors also contain the exact step/range or hole and source mapping. A missing anchor can default only to the caller's captured actor-local focus and must be resolved and recorded before dispatch. Never resolve it later from mutable shared focus.

Every management reply identifies the operation receipt, shared actual spend and usage-completeness state, job results, actor-local next cursor, and durable evidence references. Render only changed/actionable facts by default. A follow-up to an active job is serialized or rejected as busy rather than silently creating a second concurrent prompt in that session.

#### C. State transitions

| Entity | Normal transitions | Failure and recovery rules |
|---|---|---|
| Run | `running` → `stopping` → `checking` → `closed` | A recorded spend threshold, operator interruption, configured track deadline, or infrastructure failure supplies the reason. `recovering` fences new dispatch while durable history and owned children reconcile. There is no successful below-budget Sol finish. |
| Assignment | `queued` → `launching` → `active` → `completed` or `exhausted` | `cancelling` → `cancelled` only after exit/confirmed absence. Unexpected exit becomes `failed` or `recovering`, not completed. A follow-up creates another activation of the same job; terminal activation records remain immutable. |
| Provider request | `prepared` → `dispatch_started` → `settled` | Also record rejected-before-dispatch, failed, aborted, and usage-unknown outcomes. Transport failure does not imply no charge. Terminal transport state and accounting state are separate. |
| Experiment | `accepted` → `executing` → outcome | Preserve failed/timed-out/cancelled outcomes. Promotion separately records candidate identity or an explicit not-promoted reason, including run stopped before submission. |
| Candidate attempt | `accepted` → `constructed` → `submitted` → evaluation outcomes | Construction does not certify or approve unrelated transformations. A duplicate resolves to the canonical proof while retaining this attempt and derivation. Submission must cross the durable stop boundary described below. |
| Evaluation | `queued` → `running` → `passed`, `proof_error`, or `inconclusive` | Inconclusive carries timeout, resource denial, worker crash, transport, or context/measurement failure. It does not count as a demonstrated proof failure or successful compatibility. |

Use explicit persisted transitions and compare expected state/generation before applying a completion. A late event from an old activation can add genuine evidence or cost but cannot reactivate a cancelled job or release another activation's slot.

#### D. Provider dispatch and usage completeness

Immediately before each actual provider request, an enforceable adapter must serialize dispatch authorization with settlements and run stopping. Under the same coordination boundary it checks the latest settled total and run state, records the request's dispatch start, and begins the transport. Once the stop commits, no new dispatch may begin. Requests already begun remain in flight and may settle later. This is a short check and ordering boundary, not a reservation or a lock held for the whole response.

Exercise ordinary turns, automatic retries, context recovery, and compaction. The current extension's notification hook is not sufficient: its errors do not veto the provider call. If the installed Pi lacks a reliable veto/interposition seam for any charged path, the integration must supply one at a supported adapter boundary and demonstrate it before claiming enforcement. Merely throwing from the present hook does not satisfy the contract.

A reported valid zero is known zero. Missing, negative, nonfinite, or otherwise invalid usage is unknown, not zero. Retain transport/request evidence and reconcile actual usage when available. An irreconcilable request is an accounting/infrastructure failure with incomplete spend reporting, not fabricated estimated cost or normal budget exhaustion. It cannot support a competition-cap assurance. No maximum-price estimate enters actual spend or changes the settled threshold.

#### E. Stop boundary for proofs, scratch, salvage, and assembly

Durable candidate submission and the run stop use the same serialized ordering boundary. A candidate is submitted only after its exact text, immutable inputs, derivation, caller authorization, and evaluation request are durably registered. A queued tool call, job admission, or experiment start is not candidate submission.

- If submission commits before the stop, its queued or active checks may finish, and its eligible proof may undergo final cold certification.
- If the stop commits first, the invocation may retain diagnostic and experiment evidence, but it may not construct, register, promote, or assemble a new candidate afterward.
- If construction began before the stop but submission has not committed, the construction result is not grandfathered in. Retain it as unsubmitted evidence if useful; do not turn it into a closing candidate.
- Scratch returns the local experiment outcome plus `not_promoted: run_stopped` when this boundary prevents its normal internal promotion. No extra agent call is required or permitted to bypass the boundary.
- Apply the same rule to foreground compile operations, live salvage, and automatic assembly. Deduplication after the stop cannot be used to record a new authorizing attempt for an unapproved generated proof.

Prove races with deterministic barriers before construction, before submission commit, after submission, during Lean execution, and before promotion. Reversing the ordering at each barrier must produce the corresponding outcome. Do not test races by sleeping and hoping for a particular interleaving.

#### F. Restart, crashes, and no-event waiting

Use one durable coordinator generation and a single active run owner. Persist launch intent and the activation identity before spawning. Track child ownership with process-start identity and generation, not PID alone. On recovery, reconcile durable intent, owned child/process state, Pi session events, and request/cost journals before activating replacement work. Inspect or stop only children belonging to this run. A replacement cannot run while an old unreconciled child could still dispatch charged requests.

Crash cases include before/after launch, before/after dispatch, response received before settlement append, settlement appended before acknowledgement, candidate persisted before evaluation enqueue, and completion persisted before delivery cursor advancement. Reuse saved receipts and evaluation identities to converge without duplicate proof submissions or charges. Never blindly resubmit a provider request whose remote outcome is uncertain. If its actual charge cannot be recovered, report usage unknown; exactly-once remote billing is not promised.

Register result listeners before dispatch and atomically check cursor/state while registering a wait. Return immediately for already-available events. If no selected active/queued assignment, submitted verification, or other registered producer can still generate a relevant event, return `no_pending_work` instead of blocking indefinitely. Sol then receives a normal continuation opportunity below budget. Do not invent a finishing escape or silently spawn a new hypothesis. If apparent active work has exited or become unrecoverable, emit the failure/recovery event rather than waiting on stale state.

#### G. Pi transport constraints

Verify against the selected Pi version. Subscribe before prompting, drain stdout continuously, honor stdin backpressure, and keep stderr separate. Correlate command responses by command ID rather than arrival order; session events have independent lifecycle association.

`started` or `queued` prompt disposition is not completion. `handled` starts no run for that prompt, so do not wait for a future settlement on its behalf. Report the handled/no-run outcome unless separately identified extension work exists. Use assignment settlement rather than low-level turn end for slot release, while still checking actual process state.

JSONL records split only at LF bytes, optionally stripping a preceding CR. U+2028 and U+2029 inside a JSON string are not delimiters. One focused framing test covers those characters, split UTF-8 chunks, CRLF, and partial records. This requires a correct small transport reader or reuse of a verified library, not a new general protocol framework.

Pinned primary references: [Pi 1.3.0 RPC](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/rpc.md), [command dispositions](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/rpc-commands.md).

#### H. Cold verification and track-specific stopping

A completed proof/type/validity error is negative evidence for that proof in that exact context. Timeout, memory denial, worker death, unavailable toolchain, or broken instrumentation is inconclusive, with cause and retryability recorded. A retry can repeat an already-submitted check against the same exact proof; it cannot modify the proof or start new model search during closing. Use bounded infrastructure recovery and retain all failed check attempts. If certification remains inconclusive, fall back only to an already eligible certified proof or report the absence of a certified submission.

Track policy separates search stopping from infrastructure timeouts. The closed-track search has no competition deadline under the user's clarification. Open-track reuse must apply its track-specific execution deadline, including checking and finalization within the allotted wall time; the local competition checklist records 48 hours. Recheck the official rule before an open-track run. Do not apply that deadline to closed-track search, or reset its origin on restart.

#### I. Quantified spend exposure and production readiness

Configured prices and ordinary output ceilings checked on October 19 produce this offline illustration, not a measured provider bill:

| Request component | Calculation | USD |
|---|---|---:|
| Sol output ceiling | 32,000 × $10 / million | 0.3200 |
| Each DeepSeek output ceiling | 64,000 × $0.60 / million | 0.0384 |
| One Sol plus two DeepSeek outputs only | 0.3200 + 2 × 0.0384 | 0.3968 |
| Sol with 100K uncached input plus its output ceiling | 100,000 × $2 / million + 0.3200 | 0.5200 |

The final example fits inside the configured 272K Sol context window even when input and output share that window. It alone exceeds the $0.50 headroom. Thus current configuration does not establish a worst-case $3 guarantee near the $2.50 threshold. Cache hits and typical shorter responses do not prove a bound. This arithmetic omits additional retry/compaction possibilities and is not a full worst-case assessment.

An offline readiness assessment must read the resolved provider/catalog prices and effective request limits, including retries, compaction, reasoning billing, cache tiers, input/output constraints, all concurrently charged paths, and unknown usage. Record assumptions, calculated exposure, and configuration identity. If a finite bound is unavailable or exceeds the headroom, classify cap assurance as not established and require an explicit owner go/no-go before competition execution. Do not silently lower caps, serialize models, reserve money, or count estimates against the actual-cost bucket. This is a configuration/readiness gate, not another runtime spend mechanism.

#### J. Scheduling, resource experiments, and milestone exits

Basic admission must demonstrate actual priority under competing Sol foreground, promising compatibility checks, and speculative DeepSeek work, with opportunistic background tasks last. Verify priority at dispatch; lane labels alone do not prove it. Already-running Lean calls may require safe yielding rather than unsafe preemption. Preserve memory admission and all-pin cold correctness.

A separate resource-efficiency experiment compares current cleanup against reuse-aware retention across SKI/CCS, Fiberwise/Binius, and Putnam sequences. Compare one versus two real Lean workers on selected heavy projects, foreground requests during compatibility work, cold/warm start conditions, and memory pressure. Record verified checks per minute, foreground latency, worker-opening/import overhead, owned-tree PSS, CPU, swap/PSI, queue waits, and check outcomes. Use saved proofs, no model calls, and an isolated service. Sampled PSS is evidence, not a guarantee of peak memory. This experiment is not a prerequisite for the first offline multi-agent prototype; its findings do not automatically authorize changing retention/concurrency defaults.

| Milestone | Exit evidence |
|---|---|
| M1. Identities/history/ownership | Offline requests show exact derivations, duplicate attempts, actor-local delivery, eligibility, and retained original records across serving and round trips. |
| M2. Sol and two scripted workers | Offline histories plus selected actual-Pi scripted runs prove nonblocking delegation, fresh/resumed sessions, no-event handling, cancellation, recovery, actual-cost stopping, and no dispatch after the stop. Record the separate cap-assurance result. |
| M3. Durable scratch and Lean | Offline barrier tests establish the stop ordering; selected real-Lean examples prove isolation, exact promotion, failed/inconclusive outcomes, all-pin checks, and cold certification. |
| M4. Context and evidence | Preserved packet examples and actual replies demonstrate intact goals/definitions, nested hotspots, usable references, schema-consistent help, compaction/recovery, and complete graph/evidence access. |
| M5. Admission and evaluation | Deterministic priority/admission tests plus selected real-Lean contention validate conservative defaults. Resource-efficiency experiments remain separately bounded. Paid matched-spend trials require owner authorization and readiness review. |

Packet extraction correctness fixes can begin independently while M1/M2 proceed. Final multi-actor text and serving consume the stable identity/event contract. Milestones are exit groupings, not five oversized agent assignments. Ticket dependencies record genuine blockers. The user subsequently chose linear GitButler execution above the existing branches; each ticket therefore also records its immediate stack predecessor, independently of those logical blockers. The latest test policy uses one small fast smoke per ticket and consolidates broad/live integration into final E2E. Earlier per-ticket full-suite or five-minute live-check requirements are superseded. No 30-minute development gate is introduced.


#### K. Small-implementer execution scope

Use the 24 published local tickets, numbered 03–26, as the handoff for fresh Luna/Grok sessions. The earlier draft sets have been removed; there is only one active issue file per ticket. Each slice fixes its ownership, contracts, input/output journey, targeted checks, and stop conditions. Models implement the accepted design rather than making unreviewed architecture choices.

Execute one branch at a time above the current existing stack, with review and atomic commits before continuing. Keep logical blockers separate from the immediate branch predecessor. Resolve the first branch's base after existing owners commit their pending work; do not silently include another session's uncommitted edits. Critical dispatch, recovery, promotion and stop-boundary slices require independent correctness review, using the focused smoke and accepted contract rather than a broad test suite at every branch. Neither implementation-model selection nor a small context window establishes their correctness.


#### L. Concrete handoff and latest validation policy

The [local ticket index](../.scratch/arena-harness-v8/README.md) links individual files containing verified current entry points, proposed interfaces/input forms, one named fast smoke and deferred integration coverage. The [shared contracts](../.scratch/arena-harness-v8/contracts.md) define cross-ticket interfaces. It fixes ledger/locking conventions, decimal actual-cost handling, a source-verified provider-wrapper/fetch route, owned-child shutdown/resume policy, scratch replacement mapping, evidence retrieval and request-class priority. Proposed APIs and test selectors are labeled as proposed; no runtime behavior is claimed implemented.

The [final E2E checklist](../.scratch/arena-harness-v8/final-e2e.md) aggregates integration coverage at the end of the linear stack. It replaces blanket per-ticket full-suite or real-Pi/Lean requirements. Model-free resource studies and paid pilot execution remain separate owner-scoped evaluation.
