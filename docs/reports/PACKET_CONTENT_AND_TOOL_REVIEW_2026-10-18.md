# Startup packets and tool replies: content review

Date: 2026-10-18. Status: source-backed review and proposed redesign, not an implemented prompt rewrite.

## Scope and conclusion

The primary reviewer read all three [complete packet exports](../packet-review-2026-10-18/README.md), then checked extraction, selection, rendering, actual saved tool replies, and earlier optimization reports. Supporting reviews covered source defects, tool replies, and generalizable lessons. No Lean, provider request, cache refresh, or paid evaluation was run.

The packets contain useful proof-search material, but their selection and presentation sometimes hide the most important facts. Fix missing or misleading context before optimizing size. Keep the original proof and exact evidence available; use concise views with explicit coverage and stable retrieval references. There is no measured score or spend improvement from the proposed redesign yet.

Review method follows Fix Root Causes by tracing missing facts through caches, extraction, selection, and display. Explain the Number keeps character shares separate from model tokens, cost, and measured search benefit.

Apply the same information design to startup packets, tool replies, compaction memory, and delegated findings. A shorter startup packet will not solve repeated verbose replies or missing context after compaction.

## What the three packets actually contain

Counts below are Unicode characters in the exact task packet, not provider tokens, total HTTP payload, or cost. Tool documentation and system/skill text are outside these counts. Percentages use each packet's task characters; separators account for small differences.

| Packet | Task characters | Largest sections | Useful strategic signal |
|---|---:|---|---|
| SKI | 19,426 | Imported declarations 7,027 (36.2%); original proof/prices 2,770 (14.3%); locals 2,548 (13.1%) | Structural branch s4 has 160 tokens and 412 inclusive HB. Consider a different structural argument, not just tactic spelling. |
| Core | 34,608 | Earlier declarations 11,847 (34.2%); imports 6,715 (19.4%); goals 3,358 (9.7%) | s8 has 165 tokens and 3,501 inclusive HB, versus 2 self HB. Whole-structure replacement matters more than its outer tactic's self cost. |
| Fiberwise | 39,972 | Original proof/prices 13,607 (34.0%); source-name inventory 7,117 (17.8%); imports 6,670 (16.7%); definitions 5,876 (14.7%) | s11 has 721 tokens and 8,372 inclusive HB. The definition of the conclusion and a usable local goal are more valuable than a long binder prefix. |

Source: [manifest and per-section hashes](../packet-review-2026-10-18/manifest.json). These are three contrasting examples, not a representative estimate of all competition rows. The forensic audit's high cached-token share means character reductions cannot be converted directly into dollar savings.

## Correctness and completeness fixes

### 1. Preserve the goal, not just the start of its context

Core's s7 and s8 cached goal states have 1,362 and 963 characters. The renderer prefix-clips each at 700 characters, removing their goal tails, including `⊢`. A model receives hundreds of characters of assumptions without the obligation it needs to solve.

Render the target first or reserve space for it. Group common hypotheses once, retain case identity, and provide a full-state reference. Clipping must be explicit. Never suggest that the displayed prefix is the complete state. See [goal rendering](../../arena/context.py:396) and [limits](../../agent-text/numbers.yaml:27).

Fiberwise is a different failure. Its context cache has one goal, not goals for the 23 rendered top-level steps. The wrapper finds the first `by` in the declaration and assumes a fixed parser shape. A binder contains `by omega`, making selection of the wrong proof block a plausible source-level cause that still needs a real-Lean regression check. Fix declaration-proof selection rather than filling the packet with unavailable states. See [wrapper traversal](../../arena/lean/context.lean:116).

Packet fitting leaves only eight `unavailable` entries. Replace this with an explicit coverage statement, including missing steps and how to request current goals. Distinguish extraction failure, no cached state, and state omitted for space.

### 2. Select definitions from the target statement

Fiberwise's cache contains nine definition/type entries. `hammingClose`, the conclusion's predicate, is ninth and disappears because rendering takes the first eight. Meanwhile auxiliary theorem types such as `qMap_total_fiber` occupy the section titled definitions of types and predicates in the statement.

The wrapper collects constants from types of multiple generated declarations. Collect the exact target theorem type first, rank its predicates and project types, then add explicitly relevant proof definitions. `BBF_Code` is proof-local and should not be misclassified as a statement dependency. See [definition collection](../../arena/lean/context.lean:190) and [first-eight selection](../../arena/context.py:335).

### 3. Correct source coordinates and imports

Fiberwise has target-relative coordinates such as `S:-1541`, and locals attributed to negative proof lines. These positions already exist in the cache. Traversal can collect syntax from earlier declarations; Python subtracts the target offset and labels earlier positions as statement occurrences. Record source identity, coordinate system, and target span. Classify a location as target statement/proof only if it falls within that span. Preserve external context with its actual source location. Do not clamp negative values into plausible target lines. See [position conversion](../../arena/context.py:114) and [term traversal](../../arena/lean/context.lean:168).

SKI says `Available imports: none`, but its prefix contains two `public import` commands. The [import matcher](../../arena/context.py:554) recognizes only bare `import`. Preserve qualified import commands rather than making an incorrect absence claim.

### 4. Separate extraction completion from useful context coverage

Current cache `complete` records completion of the extraction stream, not complete usable theorem context. Manifest checks verify flags and section presence before packet fitting. They do not catch missing goals, lost conclusions, unrelated definitions, invalid coordinates, or a discarded earlier-lemma section.

Expose extraction completion and packet coverage separately. Suggested coverage includes captured/expected step states, omitted declaration groups, target-definition coverage, clipping, and source-location validity. A packet can be reproducible yet strategically deficient. See [cache completion](../../arena/context.py:101), [manifest checks](../../arena/context.py:557), and [fitting](../../arena/context.py:764).

### 5. Keep metric provenance visible

Fiberwise's published scoring denominator is 15,645 HB, while its cached local profile measures 15,913 HB. SKI similarly shows 1,383 versus 1,384. The step table uses the local measurement while its total row is assigned reference score 33.33. These are different sources, not proof of a scorer defect.

Label the published scoring reference and cached profiling measurement separately. Attach pin, proof identity, mode, and measurement identity where applicable. Do not imply the locally measured total itself produces exactly 33.33 under the published denominator. See [scoring reference](../../arena/scoring.py:11) and [table construction](../../arena/context.py:824).

`pts_if_gone` is a local estimate based on attributed tokens and HB. Removing or rewriting a step can change other costs, so calling it a general upper bound overstates the evidence. Prefer “attributed points, assuming other costs unchanged.” Keep self and inclusive HB distinct. Missing measurements must remain missing, not zero. See [price calculation](../../arena/prices.py:75).

## What to keep, move, combine, and remove

| Content | Recommendation | Reason and trade-off |
|---|---|---|
| Exact statement, scope, compatibility requirement, proof constraints | Keep immediately visible | Raw source/toolchain hashes belong in retained provenance and on-demand environment details, not default agent text. Preserve exact source bytes. |
| Original proof | Keep accessible as exact immutable text, with a line-numbered working view | Structural search needs the whole argument. Fiberwise is long, but deleting it by default risks losing the proof's mathematical explanation. Display line numbers must not alter proof artifacts. |
| Score, published denominators, trade-off rates | Keep one concise block | Guides token/HB trade-offs. Distinguish proof tokens, provider tokens, and API dollars. |
| Step prices and key hotspots | Keep; connect hotspot rows directly to node/step/line anchors | Surface inclusive cost and coverage. Mark shortened previews with an ellipsis and retrieval reference. Current 40-character previews silently cut identifiers. |
| Full repeated before-step goal states | Replace startup repetition with scoped contexts and selected goals | Same names can have different types in different branches. Full exact states remain retrievable. |
| Flattened global locals | Move most to per-step/case views | SKI aggregates `h`, `ha`, and `h₂` across incompatible scopes. Keep ambient theorem binders and namespace context. |
| Raw source-name occurrence lists and `S/P/U` telemetry | Move full occurrence detail to source/dependency view | Repeated names and internal positions are less useful than a readable declaration signature and source handle. Retain raw provenance. |
| Statement definitions, earlier lemmas, ranked imports | Combine into one declaration catalog with role tags | Print each signature once, then reference it from statement/proof/earlier/search roles. Relevance must precede count limits. |
| Nearby reusable declarations | Protect from wholesale eviction | Core's earlier list contains whole-list lemmas that can replace the induction. Fiberwise has 43 cached earlier declarations but fitting removes the section before reducing other bulk. |
| Parser descriptor declarations, generated representation machinery, generic infrastructure | Demote unless directly relevant | SKI's imports include parser and representation entries. Filter by role and relevance, not a blacklist of name substrings. |
| Long pretty-printed instance/binder prefixes | Show shared ambient parameters once; prioritize conclusion and explicit arguments | Fiberwise signatures can use the entire preview on ambient parameters. Offer exact expanded types and source on demand. |
| Repeated full theorem/module/name on each declaration row | Print stable handle, signature, source once | Existing rows can repeat a qualified name three times. Avoid losing distinguishing namespace information. |
| Detailed token examples and tactical folklore in mandatory skill | Move qualified heuristics into a generic cheatsheet | Keep normative rules separate from fallible advice. Avoid universally prescribing `#check` or particular tactic substitutions. |
| Historical task-specific solutions and analyst hybrids | Keep in offline reports | Extract search patterns, not exact competition answers or unearned ownership claims. |
| Legacy finish help | Remove from current inspection output | Current Pi exposes five tools; v8 also forbids voluntary Sol exit. This is inspection drift, not evidence Pi currently offers that tool. |

Do not silently strip comments from the retained reference proof or change line coordinates. A compact working view must identify its source and mapping. The original bytes, complete lineage, and evidence must remain retrievable even when presentation is concise.

## Tool replies need the same redesign

The following examples come from saved runs; current source was inspected to distinguish surviving behavior from historical defects. They are not new multi-agent measurements.

| Finding | Evidence | Proposed behavior |
|---|---|---|
| Scratch `#check`/`#print` results lose the useful part of a signature | Message cells capped at 300 characters in [scratch rendering](../../arena/tools.py:1706); Fiberwise trace-journal line 40 | Preserve conclusion and essential arguments, mark clipping, return an experiment/result reference for the complete message. |
| Scratch has no unique model-visible experiment reference | Current reply uses `ref: scratch`; original code is now retained in ledger, but full experiment identity/outcomes remain pending | Return stable experiment ID, context/pin, diagnostics, promotion result, exact derivation, and verification status. Harness supplies actor/job metadata. |
| A valid search miss looks like an invalid request | Fiberwise trace-journal line 100 searches `ncard_le_mul`; reply says `not_found` and “Valid values: nonempty query” with irrelevant suggestions | Use `no matches` for valid searches. Reserve input errors for malformed requests. Suggestions need a relevance threshold. |
| Goal trials repeat entire states and mislabel unfinished proofs | Core trace-journal line 10; [trial verdict rendering](../../arena/tools.py:985) joins early error lines | Distinguish `leaves goals`, parse/type error, and closed. Reuse identical state references; show changed targets and cases. |
| Markdown fences can start after an inline label | Core trace-journal line 10 has `n2 line 11: ```lean` | Put label, newline, then fenced block. Test actual rendered Markdown, including multiple cases and embedded fences. |
| Full search maps consume substantial delivered text | Fiberwise 22 map-bearing replies among 91 replies, 60,618 of 179,801 characters (33.7%); Core 14 among 75, 39,008 of 141,678 (27.5%) | Default to changed frontier/steps, new evidence, and relevant job events. Keep a full-map read. Maps are already conditional on change; this is not a claim they appear on every reply. |
| “Best” can mix provisional discovery with certified submission readiness | Interleaved trace-journal line 120 has n18 score 89.17 and 1/3 versions | Label provisional best and all-pin verified best, with independent cold status. Partial evidence is legitimate; its meaning must be clear. |
| Inspection parameter docs flatten the actual schema | `fill_hole`, `splice_base`, and related rows differ from nested provider inputs; defaults, types and bounds are incompletely represented | Generate documentation/inspection from the registered schema plus shared descriptions. Test the actual five-tool interface and enforce bounds consistently. |

Trace locations are under `runs/pi-budget/v8c-<row>-gpt-6.1-sol-r1/trace-journal.jsonl`, with row directories `Binius.BinaryBasefold.fiberwise_dist_lt`, `Core.InitsUpdatesComm`, and `interleaved_affine_gaps_imply_tensor_gap` respectively. Character shares describe those saved delivered replies, including map text; they are not token shares, provider charges, or controlled estimates of savings.

An older compile-reply inconsistency, where one row reported full compatibility and another stale row reported only one checked pin, was found in prior audits. Current `_refresh_versions` refreshes rows after autocheck. Do not report that historical defect as newly confirmed. Still use a consistent evaluation snapshot when showing status and metrics.

Illustrative future reply shape, not existing API syntax:

```text
n18 · splice s2 from n16 · primary-pin pass
128 tokens (+1); 2,118 HB (-109); provisional score 89.17
Compatibility 1/3 passed, 2 pending; cold not checked
All-pin verified best n13
New evidence: one candidate; worker d2 still searching
```

Keep essential errors inline. Put verbose diagnostics behind stable references. A tool result should answer what happened, what changed, what is still uncertain, and how to inspect it. Repeated legends and unchanged run-wide summaries belong in documentation or explicit full-state views.

Actor-local delivery cursors are required when introducing workers. The current run-global cursor can make one actor consume another's update. This is a source-backed integration risk, not an observed failure of a deployed multi-agent run.

## Generic cheatsheet extracted from the learning record

A [standalone draft](../packet-review-2026-10-18/GENERIC_CHEATSHEET_DRAFT.md) captures structural search, symmetry, project abstractions, focused experiments, and combined token/HB tuning. It contains no task names, saved solutions, fixed model allocation, or task-specific theorem hints. It is not installed in live prompts.

The [October 17 cheatsheet](AGENT_OPTIMIZATION_CHEATSHEET_2026-10-17.md) has valuable examples but includes analyst hybrids and named solutions. Keep that report as evidence, not a competition startup packet. Its claim that blank lines count proof tokens should not be copied. An offline check of the current pinned counter returned 2 for both `by\n  trivial` and `by\n\n  trivial`, and 3 for `by\n\ttrivial`. Current packet wording about spaces/line breaks and tabs agrees with these examples. Identifiers are not cheaper merely because their names are shorter. These checks measure proof tokens, not provider tokenizer behavior.

Qualify earlier advice. “One small edit at a time” helps local attribution but must not prohibit a structural rewrite. A small intermediate equation may reduce elaboration cost; it is not always cheaper. `simp_all`, `grind`, explicit terms, and inferred arguments are experiments, not universal performance laws. A relevant library theorem can replace an entire proof route, including one absent from the original dependencies.

Do not turn context acquisition into a mandatory checklist before every candidate. Batch needed signature/source requests, reuse pinned evidence, and re-query when the question or environment changes. Record new failed-experiment findings once. Optional prose is useful when it adds intent not already captured by the hypothesis and operation records.

## Proposed packet hierarchy

1. **Shared contract.** Validity constraints, actual shared spend/lifetime policy, scoring, five-tool semantics, and concise generic search advice. Correct “only your own tokens” for shared accounting. Say Lean consumes no model API dollars rather than asserting scratch is always cheaper than reasoning.
2. **Sol strategy packet.** Exact theorem and scope, reference/current best proof, published score reference, usable hotspots with coverage, a compact relevant declaration catalog, graph frontier, delegation ledger, and strategic whiteboard. Empty ledgers need no verbose boilerplate.
3. **Worker hypothesis packet.** Assignment and exact immutable parent/step, sufficient proof and local context, relevant declarations and prior findings, experiment evidence, global spend state, and retrieval tools. Whole-proof workers need whole-proof context; do not force them into a tiny local fragment.
4. **Changes during search.** Compact new evidence and graph/job changes. Full source, goals, diagnostics, lineage, and alternative derivations remain accessible by stable references.

Keep authority distinct from advice. A model observation is not a Lean certificate. A delegation relationship is not a proof derivation. A concise summary is not a replacement for the original lineage record. Scratch promotions must return actual outcomes without making the model repeat metadata already known by the harness.

## Implementation order and acceptance

1. Repair extraction and fitting. Add targeted cases for binder `by` before the real proof, public imports, external syntax locations, the ninth target predicate, clipped goal conclusions, and section eviction with useful nearby lemmas. Real extraction fixes need pinned Lean validation; renderer-only tests cannot establish wrapper correctness.
2. Introduce structured goal/declaration/evidence views with coverage, stable references, and consistent source/metric identity. Use them for packets, replies, serving, and compaction. Avoid another separately maintained text projection.
3. Generate inspection help from actual tool schemas. Test fences, long signatures, no-match versus invalid input, trial outcomes, pending compatibility, and actor-local delivery. Preserve raw artifacts and exact lineage.
4. Re-render these same three packets and representative saved replies side by side. Verify required facts survive, every clipped item is retrievable, and generic advice contains no task-specific solution. Preserve the original exports and manifest.
5. Evaluate search utility from scratch with matched total spend and identical pins/runtime. Keep baseline and treatment distinguishable. Packet-size, cached-token share, and section membership alone do not establish an optimization benefit.

The content review is complete for these three examples. The redesign, real-Lean extraction regressions, refreshed packets, compaction retention checks, and controlled efficacy comparison remain implementation/evaluation work.


## Follow-up: pins, empty columns, and nested steps

The [v8 content contract](../PLAN-harness-v8.md#612-packet-and-tool-output-overhaul-content-contract) refines the initial recommendations after user review. Raw pin hashes belong in harness evidence, not default agent packets. SKI's saved columns are populated, but its total row has inapplicable dashes and mixes compatibility/score into the text column. The legend is unconditional. Show only useful columns, and distinguish missing from zero.

The seven SKI step rows are top-level edit units, not a full tactic profile. Its indentation parser yields 63 regions, including 26 below s4, but these are not interchangeable with measured Lean tactic entries or legal splice targets. Default presentation should combine structural overview with nested measured hotspots; full cost detail remains retrievable. Existing tree reads select at most 30 measured rows and need explicit expansion/pagination for complete access. Remove `pts_if_gone` from default text and retain self HB only where detailed attribution helps.
