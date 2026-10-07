# Working decisions for Arena harness v6

Status: working decision record, **not the final v6 specification**. Preserve the numbered user stories below as
the prior design inventory; the current decisions in this section take precedence where that inventory conflicts.
We will synthesize a final spec after the open choices are settled and the first official submission path is ready.
Source: v5 acceptance runs `v5-accept-20261006` (aborted) and `v5-accept-20261006-r2` (Luna and Qwen on
`Core.InitsUpdatesComm` at $0.10 each), three parallel run analyses, and a harness audit (2026-10-06).
Predecessor: `docs/SPEC-harness-v5.md`.
Rules checked against the [official Arena Space](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena)
and its [public app source](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/app.py).
Cache reasoning checked against [Anthropic's prompt-caching documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#what-invalidates-the-cache).

## Decisions after the cross-theorem and rules review (2026-10-07)

1. **First official submission is a v6 milestone.** The user will upload it manually. Prepare a warm-up JSONL from
   verified v6 model outputs, a code archive with a top-level reproduction README and pinned environment, a complete
   per-problem model-call/spend ledger, and a report in the official template. Warm-up proof upload is open now;
   code upload opens with the full benchmark on Nov 1, 2026. The report goes to OpenReview, not this Space. The
   user chose to wait for v6 proofs before assembling the JSONL. No post-hoc human hybrid is represented as a
   harness output. The competition's closed track has a **$3 maximum per problem** at public list prices, counting
   retries and discarded calls; the old $0.10–$0.20 experiment caps are no longer a design priority.
2. **Langfuse is a required run gate.** v5 ran Pi with `--no-extensions` and loaded only MCP and Arena, so the
   installed Langfuse extension recorded no v5 generations. Enable the extension explicitly, assign the Arena run
   ID as the trace/session join key, and before any evaluation matrix verify a real generation plus tool spans in
   Langfuse. The stock plugin records only the latest prompt or tool-result delta as generation input and truncates
   assistant text at 20,000 characters by default; that is **not** an exact request trace. Capture the final outgoing
   provider payload (or a lossless, reconstructible redacted equivalent) after the Arena budget hook, together with
   response text, model/version, token splits, cache counts, cost, retry identity and timing; join it to Langfuse
   observations and the local ledger. Fail preflight if export, query, or completeness fails. Local event/session
   logs remain the audit backup; v5 cannot be retroactively turned into exact Langfuse traces. Capture provider-
   supplied encrypted/redacted reasoning as delivered, without claiming access to hidden reasoning text.
3. **Keep model request shape stable throughout a run.** No mid-turn or per-episode thinking changes. The current
   `boundedPayload` reduces `max_tokens` and then clamps or deletes `thinking.budget_tokens` on the Anthropic
   Messages path. Anthropic documents that changing thinking parameters can invalidate cached prefixes, but the
   hosted Qwen service is only Anthropic-compatible, and eight larger Qwen cuts kept the cache **despite** changed
   thinking budgets. The three deep cuts (`max_tokens` caps 4,520 / 1,486 / 3,738) all missed; Luna's OpenAI path did
   not. Two misses followed the prior request in under 20 seconds, making ordinary cache expiry unlikely. Request
   shaping correlates with the misses; the provider's exact invalidation rule is **not yet proven**. Replace
   payload reshaping with a stop-before-send gate and capture actual wire settings and cache results in a controlled
   A/B preflight; the ~4,096-token threshold hypothesis was not supported by a direct Pi test. The test reused
   cache at the historical 4,520/3,496 and 3,738/2,714 output/thinking settings with synthetic stable ~35K
   and ~122K cached-token prefixes. Removing thinking at 1,486 selected a separate cache entry; repeating that shape hit its new entry,
   then re-enabling thinking hit the original. This makes the subst miss plausibly harness-triggered, but does not
   explain the historical r2 and CSLib misses. Do not encode an unproven output-cap threshold in v6.
4. **Make proof dependencies visible and retrievable.** The initial packet must inventory every resolvable
   declaration directly named in the original proof (lemma, theorem, axiom, definition, constructor, variable
   or local declaration), and clearly show which additional theorem/lemma dependencies occur directly in the
   elaborated proof term. The full proof-term constant inventory remains retrievable by the same lookup/index
   interface, grouped by kind and origin; its generated/tactic/typeclass entries must not silently masquerade
   as source-authored lemmas. Give qualified name, kind, source location and signature where available, and fetch
   full bodies on demand to bound the cached packet. Add one batched name lookup that accepts several names and returns each complete
   declaration statement and source body/proof, with explicit results for opaque, generated, private, external
   or unavailable bodies. Distinguish the original proof's direct references from transitive dependencies and
   avoid including the target theorem itself or false positives from comments/strings. Add ranked related-lemma
   discovery as a separate route for relevant declarations absent from the original proof. v5 already collects
   some resolved identifiers in `arena/lean/context.lean`, but `arena/context.py` drops `Init.Prelude`, caps the
   display at 50 signatures, clips each signature, and `_fit` can silently remove entries; it also shows no body.
   The PhysLib cache already contains 84 `used` records, 76 after the Prelude filter, but its saved packet shows
   only three signatures after `_fit`; the other four analyzed theorem contexts have 8–33 such records.
   An offline Lean probe found 438 proof-term constants on PhysLib, versus 84 syntax references captured from the
   theorem declaration; only 77 overlap. The current syntax collector traverses the whole declaration and
   de-duplicates on first occurrence: 15 names first appear in the statement and 69 in the proof. This does not
   prove the first 15 are absent from the proof, so a proof-only use count needs an occurrence-preserving pass.
   The 438 include 224 definitions, 168 axioms and tactic/typeclass machinery, so dumping all their signatures
   into kickoff would obscure the source-level dependencies. Reuse the Lean-aware extraction and add coverage
   accounting instead of replacing it with text matching.
   To return a human-readable theorem proof, locate its declaration in pinned source; pretty-printing an `.olean`
   proof term is not equivalent to retrieving the source proof.
5. **Relay is optional research, not a v6 deliverable.** Rules allow arbitrary harnesses and require every model
   disclosed; they do not ban multi-model runs. Track eligibility must still be checked for each actual model and
   all spend counted. A Qwen/Luna pairing cannot be assumed eligible for either track: Qwen publishes open weights
   for `Qwen3.8-Flash-Next`, while the hosted `Qwen3.8-Flash` is a related production model whose exact track status
   needs confirmation; Luna is closed. v5 hybrids were built by analysis, not relay trials, and Luna's local
   golfing did not prove a handoff gain. Defer User Stories 54 and 73 until single-model discovery and proof
   scaffolding are measured.
   Drop User Story 55: adaptive thinking conflicts with stable caching and has no observed benefit.
6. **Tools before codemode.** Start with exact batched declaration lookup, de-duplicated search with usable paths,
   source lookup for returned paths, and bounded multi-draft probes. Fix misleading goal/profile line numbers,
   missing hole goals and silent malformed tool JSON. Keep a strict, auditable tool surface while these cover the
   observed failures; reconsider codemode only against an unmet capability with model-call accounting and tool
   permissions intact.
7. **Bookkeeping decision (user-settled).** The agent records one idea per structural strategy. The harness links
   later probes/candidates to that idea, computes attempts, failures and improvements from append-only events,
   and updates status automatically where the outcome is unambiguous. The agent may explicitly abandon or
   revise an idea with a short reason; it does not repeat its full title/hypothesis on each update. Keep the
   first idea call for traceable intent rather than inferring every strategy from proof edits.
8. **Kickoff dependency display (user-settled).** Show all directly source-named declarations plus any additional
   theorem/lemma dependencies from the elaborated proof term. Keep the complete term-constant index available
   through lookup, rather than printing all generated, tactic and typeclass constants in the kickoff packet.
9. **Continuation is a bounded review, not an unconditional loop.** v5 forced all 14 runs to the usage cap,
   including continuations after Qwen CSLib explicitly declared a final state. Keep the early-stop safeguard that
   previously helped Luna: add `arena_finish()` as an explicit stop request. Its first early request gets one
   concrete review of the best proof and untried structural alternatives. If the current idea has no linked
   proof attempt (probe, evaluation or candidate),
   give one bounded reminder to test or abandon it with a short reason; the agent's next finish confirmation
   must be honored. The user chose one reminder, then agent judgment. Repeated no-work finals without the tool
   must also settle under a small fallback limit, rather than spending until the usage cap. Do not infer a
   definitive finish from arbitrary prose alone.
10. **Ranking formula remains an experiment.** Exact source-reference inventory and batched search are core.
    A crude shared-identifier ranking over 67 cached Core local declarations plus the first 30 proximity rows
    yielded 33 distinct names and found five of six known useful helpers, still missing
    `Core.updatedStatesDefMonotone`. The saved Extract/CSLib caches lack a complete imported candidate universe,
    so their decisive imported helpers cannot be ranked offline yet. Build a pinned imported-declaration fixture
    and score recall/false positives before choosing a ranking formula for the final packet.

Deferred design evidence: measure packet size on unusually reference-heavy proofs; exercise pinned-source body
retrieval for imported/generated/private declarations; compare batched probes with any deterministic scaffolding
proposal; and test episodes only if stable long-context runs show a measurable problem. These do not enlarge the
core scope in [SPEC-harness-v6.md](SPEC-harness-v6.md). The original story catalog and observations follow.

### Investigations completed before the final spec

- Across the 14 v5 runs, the summaries total 800 model requests and $1.48805 in ledger-priced spend. The event
  logs contain 32 error-returning tool calls: source path/root handling 10, proof-body/statement normalization 8,
  idea arguments 8, line/range coordinates 2, missing hover information 2, misnamed tool 1, and `sorry` sent to
  evaluation 1. Two provider timeouts were retried; 12 budget-stop turns after spend are a separate lifecycle
  issue. The 110 bookkeeping-class requests cost $0.163887. These are different measures: tool-error count is
  per tool result, while spend classes are per model request.
- Saved kickoff packets show 29 / 7 / 8 / 9 / 3 signatures from 33 / 8 / 10 / 9 / 84 captured `used` names on
  Inits / extract / subst / CSLib / PhysLib respectively. An offline Lean probe measured declaration-level syntax references versus
  elaborated proof-term constants: Inits 33 / 90, PhysLib 84 / 438, with intersections 32 and 77. PhysLib's term
  includes only nine theorem-kind constants but hundreds of axioms/definitions from tactic and typeclass machinery.
  Its sorted one-name-per-line term index is 10,295 UTF-8 bytes, so a complete name index is technically possible;
  its prompt value still needs a comparison against the compact view. The syntax collector covers the theorem
  statement and proof together: by first occurrence, Core splits 10 statement / 23 proof and PhysLib 15 / 69.
  Because names are de-duplicated before emission, those first-occurrence groups are not exclusive use sets.
  The source and proof-term views must remain distinct, with full retrieval and honest coverage counts.
- An offline fake-provider Arena session with the installed Langfuse extension explicitly loaded produced
  Langfuse generations and a tool span, linked by run ID. Most generation inputs were absent, and the first
  was a truncated prompt; the plugin does not store the full outgoing provider payload. The existing offline
  Anthropic-wire integration test passed and confirms the guard's payload path. Older Langfuse exports do exist:
  one naïve session has 72 generations and 69 tool spans, and a blank Luna session has 22 generations and 190
  tool spans. They are useful session histories, but the plugin clips prompt/output content at 20K characters,
  captures generation inputs as prompt/tool-result deltas, and sees the request before Arena's final budget hook.
  v5 omitted the plugin with `--no-extensions`. Enabling it alone does not yield exact post-guard requests.
- A direct Pi Qwen test captured final request settings, message hashes and cache usage without prompt text or
  credentials. It spent $0.046631 in Pi-reported usage. With unchanged messages and cache markers, cuts to
  4,520/3,496 and 3,738/2,714 (output/thinking) hit at synthetic ~35K and ~122K cached-token prefixes. At 1,486,
  removing thinking missed once; repeating with thinking absent hit that new partition, and restoring thinking
  hit the original partition. This rejects the proposed small-`max_tokens` cache rule and supports a
  thinking-presence partition. Historical r2/CSLib misses remain unexplained because v5 did not save wire payloads.
  A pre-miss CSLib session projection restores messages but omits system prompt, tool schemas and cache marker
  placement, so an exact historical replay cannot be verified from the saved artifacts.
- All 14 v5 runs ended at the usage cap; none ended by an agent finish or plateau. Eight runs contain 25 forced
  continuations. Qwen CSLib spent $0.047426 across 13 requests after its first explicit final answer. Among 90
  unique ideas, only 37 have a linked probe event; 19 were abandoned with zero probe events and 14 stayed active
  with zero probe events. Complete probes can create candidates without a separate probe event, so those counts
  do not measure never-tried ideas. The frontier ranks candidates, not strategy experiments. This supports active-idea default linkage,
  one bounded untried-idea review, and a small repair allowance after a failed structural probe.
- A read-only turn-boundary replay showed that stopping at the **first** clear final would lose Luna r2's later
  #21 (+0.31 proxy) and Qwen CSLib's later #8 (+0.38 proxy). Qwen's first review only created a new idea; its
  next continuation tried that idea and found #8. A review plus one zero-attempt grace, then stopping after the
  later verified finals, would have saved $0.031223 in these two clear cases with no later best lost. The replay
  used a text heuristic, so the implementation needs an explicit, testable finish protocol.
- A local-only ranking probe over Core's 67 cached earlier declarations found four of six known decisive helpers
  in the current packet and five of six in a 33-name proximity/lexical union. It did not test imported helper
  recall on Extract or CSLib because their caches omit a complete imported candidate universe. Do not treat the
  shared-identifier proxy as a validated final ranking algorithm.

### Provisional tool and context design for discussion

The agent owns the proof strategy: choose a structural idea, decide which references matter, author and repair
proof drafts, and decide when to stop. The harness owns facts and mechanics: build the dependency inventory,
resolve pinned source, normalize proof bodies and paths, compile and score drafts, map proof/file lines, track
candidate lineage and spend, record traces, and assemble only verified submission artifacts. The agent makes
one explicit idea call per structural strategy; the harness derives its attempts and outcomes from probe and
evaluation events. This boundary should make valid agent intent cheap without hiding actual failures.

Candidate model-visible tools (names and grouping still provisional):

| Job | Contract to test | Observed reason |
| --- | --- | --- |
| `arena_find` | Accept several exact names or goal/type queries; return distinct qualified declarations, rank, and source handles that all subsequent tools accept. | v5 search duplicated names and returned source paths that `arena_source` refused. |
| `arena_declarations` | Accept several qualified names/handles; return each full pinned source declaration, including statement and proof/body, or a typed `unavailable` reason. Page long bodies without dropping names. | The packet omits most captured dependencies on PhysLib; single-name signature lookup cannot follow a proof's lemma chain efficiently. |
| `arena_source` | Read every handle emitted by packet/search/declaration/profile; normalize known `strata:` and dependency roots; state line base and source revision. | Ten observed source path/root errors and two coordinate errors. |
| `arena_probe` | Accept up to four drafts per call, including proof bodies beginning `by`/`:=`; complete the pinned statement and return one outcome per draft with hole goals and candidate IDs. | Eight body/statement rejections; structural alternatives currently cost repeated calls. |
| `arena_evaluate` and `arena_profile` | Score a complete proof or candidate ID; return stable IDs and both `proof_line` and `file_line` in diagnostics/profile. | Agents confused probe/candidate routes and proof-relative/file-relative lines. |
| `arena_state` and one `arena_idea` call | Show concise frontier, budget, and current idea; record one title/hypothesis per strategy, then infer attempts and status from events. Permit a short explicit revise/abandon reason. | 110 bookkeeping requests; eight idea argument errors, including a schema that says optional where the CLI requires fields. |
| `arena_finish` | Request completion with no required arguments; first finish returns one factual review, and a current idea with no linked proof attempt gets one reminder. A repeated finish confirms the stop. | v5 continued after clear finals; an immediate stop would have lost later bests in Luna r2 and Qwen CSLib. |

Do not add a free-form codemode executor to obtain batching: it exposes Pi model access outside the Arena budget
guard. Test bounded batching in the tools above first. The runner does not honor final answers as a stop: it
continues completed turns until a cap, error streak, continuation count or plateau condition. Add the explicit
finish tool plus at most one early review and one zero-probe reminder, then stop after confirmation; a bounded
no-work fallback covers agents that forget the tool.
Treat `not_found`, `unavailable`, invalid input, Lean rejection and provider failure as distinct
typed outcomes; never silently replace malformed tool JSON with `{}` or relabel a real failure as success.

The kickoff packet should list **all** direct source references and additional theorem/lemma names from the
proof term, with origin, qualified name, kind and source handle. Signatures have a bounded ranked preview;
the packet reports preview and inventory counts, and batched lookup supplies full bodies. The complete term
constant index, including generated/internal entries, is queryable and counted separately. Whether to include
every one of those names in the initial packet remains open: PhysLib has 438, so a raw full dump may consume the
prefix without improving proof search. No original-proof source reference may disappear silently.

Before settling the final spec, replay **all 14 v5 runs' valid-intent tool inputs** through the candidate
contracts. The target is zero preventable tool errors and zero mismatched line lookups, with unavailable data
reported honestly. Measure bookkeeping plus rejected model spend below 5% rather than merely reducing call
count. For Langfuse, match every model attempt and retry to a trace observation and ledger entry, and verify
lossless final outgoing request data after the guard. For Qwen cache RCA, the direct one-factor trials are done;
the historical r2 and CSLib misses cannot be assigned a provider-internal cause without a near-final replay or
an equivalent complete wire capture.

## Problem Statement

v5 worked. At $0.10 a run, Qwen3.8-flash reached a proxy of **81.76** (110 tokens, 238 heartbeats, all three
toolchains), above the naive unharnessed baseline of 76.72 and every earlier run. GPT-6 Luna reached 74.72
(153 tokens, 320 HB), up from 60.37 under v4. Background full checks, the `[arena]` status line, probe
auto-promotion, the submission, diagnostic line alignment and the locked-down tool surface all behaved
as designed.

Three of the five v5 acceptance criteria still fail, and the runs exposed problems that will matter more as
budgets and benchmark rows grow:

- **The cap does not hold at its edge.** Qwen ended at $0.1262 on a $0.10 cap. Its last request missed the
  provider's prompt cache (0 read, 136,764 written, $0.028). It was the only request whose payload the budget
  guard had changed: `max_tokens` cut from 16,000 to 4,520 and the thinking budget with it. Luna's last
  continuation was sent with $0.0010 left, less than one cached read of its context.
- **Money is spent after the best result.** Qwen spent 41% of its budget after its best candidate, inside one
  agent turn where plateau detection never runs. Luna spent 26.5% on a plateau.
- **The structure-finding information was not in the context.** Qwen's induction-free proof uses four lemmas
  from the same file. The kickoff packet listed only one of them, because the "earlier lemmas" list is ordered
  by distance and cut off. Qwen spent 31% of its budget searching to find the other three. Luna recorded the
  same idea, then abandoned it twice by argument alone, without a single probe.
- **Reasonable model inputs are refused or misread.** Five rejections and three misaligned goal lookups, every
  one an input the harness could have understood: a `strata:` path prefix, a probe body starting with `by`,
  probe ids or `#0` given as parents, and proof-relative lines from `arena_profile` used as file lines.
- **Bookkeeping is too verbose.** Luna made 36 `arena_idea` calls, each re-sending the full title and
  hypothesis and getting the full record back.
- **Our measurements are wrong in places.** The overhead classifier reported Luna at 25.2% when about 11.6% is
  fair. The cache metric penalises long outputs. The runner log says "returned without a recorded node" for
  probes that created candidates. `matrix.json` cannot check the acceptance criteria.
- **At r2, generality was untested and broken.** On the second provisioned Strata row
  (`CallElimCorrect.extractedOldExprInVars`) the generic packet silently lacked its definitions, goal trace,
  signatures and earlier-lemma sections (3.8K characters vs 21.5K). The wrapper/scope fixes before the
  cross-theorem runs repaired that specific degradation; the saved packets still omit many proof dependencies.
- **Results depend on luck in discovery.** Three replicates per model (Phase 0) show the score is decided by
  proof structure: runs that found three in-file lemmas 600 lines above the theorem reached 81.8–84.6; the four
  runs that did not stayed between 73.8 and 76.5, below the naive baseline. Qwen found them in 2 of 3 runs,
  Luna in none. A proof built from the runs' own ingredients reaches 87.10, so the headroom is real.

These were diagnostic runs at $0.10. The official budget decision is the $3/problem cap above.

## Solution

A v6 harness, built after a Phase 0 of replicate v5 runs, where:

1. The kickoff context ranks in-file lemmas by relevance to the statement, so structural routes are visible from
   the first request; it is complete (or loudly incomplete) on every provisioned row.
2. Trying a structural idea is cheap: several drafts compile in one call, and an idea abandoned without any
   probe is visible as such.
3. The cap holds: requests are gated by expected cost, never reshaped, and the remaining budget and money spent
   since the last improvement are visible to the model as facts.
4. Every input a model reasonably sends is understood, and every line number the model sees can be used directly
   with the Lean tools.
5. Bookkeeping is cheap: short acknowledgements, compact updates, nothing re-sent.
6. Measurements are right and comparable: fair turn classes, prefix-cache reuse, overshoot, acceptance criteria
   and replicate statistics computed per run and per matrix.
7. Runs are tested on more than one theorem, and certification fails loudly when a row's context is degraded.
8. Experiments with session episodes and tool profiles can be run through the matrix as declared factors after
   trace completeness and the first submission path work.

## User Stories

### Context that reveals structure (P0)

1. As the model, I want the in-file lemmas that share constants with the statement listed first in the packet, so that I see lemmas such as commutation and update rules before reading any source.
2. As the model, I want each listed lemma to show its full signature and where it sits in the file, so that I can apply it without a declaration lookup.
3. As the model, I want the packet to state how many earlier lemmas exist and how many are shown, so that I know when to search for more.
4. As the model, I want an on-demand "related lemmas" request that ranks project lemmas by shared constants with a goal or term I give, so that I can find lemmas relevant to a subgoal mid-run.
5. As a harness developer, I want lemma ranking to use only the statement's constants and the environment, never theorem-specific text, so that the packet stays generic.
6. As a harness developer, I want the packet's lemma section to be deterministic and size-bounded, so that the cached prefix stays stable.
7. As a harness developer, I want packet generation to report which sections it produced and fail certification when a section that should exist is missing, so that degraded context never reaches a run unnoticed.
8. As a harness developer, I want the packet to state that the original proof is candidate #1, so that the model never refers to `#0`.
60. As the model, I want the packet's lemma section to cover the whole file before the theorem, not only a window near it, so that lemmas far up the file (the three that decided the route sat 600 lines above the theorem) are visible.
61. As the model, I want `lean_local_search` to count its limit in distinct declarations, so that a query is not filled by four copies of the same name.
62. As the model, I want the packet to ask me to survey the related lemmas before recording ideas, so that my first ideas are built on what the file already proves; v5's "propose ideas before editing" made three of six runs commit to a route at turn 0, before reading anything.
63. As a harness developer, I want the packet to include the results of a harness-run discovery pass (declarations whose signatures mention the statement's head symbols, with their signatures), so that discovery no longer depends on which query a model happens to try.
64. As the model, I want the skill to teach generic proof-transformation rules learned from the runs (literal token counting, `cases` on an equation instead of `rw`, `refine L ?_ ▸ t` instead of `rw` then `exact`, no bullets, `simp [lemma, *]` for conditional lemmas, `rw`/`exists`/`simp_all`/`grind` as heartbeat traps), so that every model golfs like the best hybrid.
76. As the model, I want every source-named or directly proof-term-used declaration in the original proof
listed at kickoff, tagged by origin and accompanied by kind, qualified name, location and signature where
available, so that I can reuse the proof's existing knowledge without guesswork.
77. As the model, I want one batched declaration lookup by names that returns complete source bodies and proofs where available, and explicitly explains unavailable bodies, so that following a chain of references takes one turn.

### Cheap structural exploration

9. As the model, I want to compile several drafts in one probe call and get one compact table (tokens, heartbeats, pass/fail, first error, probe id), so that comparing alternatives costs one turn, not several.
10. As a harness developer, I want batched drafts to run in the model's Lean lane with a bounded count, so that they cannot starve the background checks or the machine.
11. As the model, I want complete drafts in a batch to become candidates like single probes, so that a batch is never a dead end.
12. As the model, I want the idea summary to show how many probes and candidates each idea had when it was abandoned, so that I notice ideas dropped without evidence.
13. As the model, I want a token profile alongside the heartbeat profile (tokens per proof line with cumulative share), so that I see where tokens go as clearly as where heartbeats go.
14. As the model, I want profile entries to carry both the proof line and the file line, so that I can pass them straight to `lean_goal`.

### A cap that holds (P0)

15. As a harness developer, I want a request refused when the remaining budget is below k times the largest of the last five request costs (k ≈ 1–1.5; k = 2 lost up to 0.18 points and 14% of budget in replicates), so that the final request cannot overshoot materially.
16. As a harness developer, I want the same gate applied before sending a continuation, so that no continuation is sent with less money than one request needs.
17. (Promoted: cross-theorem correlation and stable-request principle.) As a harness developer, I want the output limit and thinking configuration fixed for a run, with no payload reshaping at the cap edge, so the harness avoids a reproducible cache-miss trigger.
18. As a harness developer, I want the guard's decision and the estimate behind it recorded in the cost ledger, so that every stop can be audited.
19. As the model, I want the remaining budget in the status line once it falls below a quarter of the cap, so that I can finish the most valuable work.
20. (Demoted: would rarely have changed anything in r3/r4.) As the model, I want the status line to state the requests and money spent since my last improvement, counted from my first candidate, once that crosses a threshold, so that I can judge whether to change approach; the harness gives no advice.
21. As a harness developer, I want the plateau facts computed per request rather than per agent turn, so that one long turn cannot hide a plateau.
65. (Superseded by 17 and the official $3/problem gate.) An optional provider-specific cache-miss reserve was proposed when the miss was unexplained; do not implement it as a v6 priority.
66. As a harness developer, I want no continuation sent when the remaining budget is below the last request's cost, so that we never pay for a reply that is cut off at the limit (seen in r2 and r4 Luna).
22. As a harness developer, I want an optional budget-preserving stop (no improvement for a set amount of money) that ends the run and reports the unspent budget, so that experiments can reuse it.

### Inputs the harness understands (P1)

23. As the model, I want `arena_source` to accept a path with or without the source prefix (`strata:` or `strata/`), so that copying the packet's path works.
24. As the model, I want the packet to print plain project-relative paths, so that the prefix question never arises.
25. As the model, I want a probe whose text starts with `by` or `:=` to be completed with the exact statement, so that I do not lose a turn resending it.
26. As the model, I want probe ids accepted as parents and recorded as lineage, so that the graph reflects how I worked.
27. As the model, I want `#0` and "original" accepted as the original proof, so that natural references resolve.
28. As the model, I want `arena_declaration` to return the constructors of an inductive type and the fields of a structure, so that one lookup is enough.
29. As the model, I want a not-found declaration to suggest real names that end with what I asked for (e.g. `Imperative.UpdateState` for `Core.UpdateState`), so that I recover in one turn.
30. As the model, I want `lean_local_search` results free of the harness's own scratch copies of the file, so that the result limit is spent on real declarations.
31. As the model, I want a tool-not-found error for a misnamed tool (e.g. an MCP-prefixed `lean_declaration`) to name the tool I probably meant, so that I recover in one turn.
67. As the model, I want `arena_evaluate` given both `candidate` and `from_probe` to use the probe (or reject the pair), and an empty `from_probe` ignored, so that a probe is never silently replaced by a cached candidate.
68. As the model, I want `arena_evaluate` given a draft with `sorry` to tell me to use `arena_probe`, and `arena_source` given a skill reference path to point me to `arena_skill_read`, so that each mistake costs one turn.
69. As the model, I want `arena_idea` with no arguments to answer with its usage, so that an empty call is not a silent error.
32. As the model, I want probe results to say "complete and compiles", "compiles with holes" or "fails" in one field, so that a `sorry` draft is never read as passing.

### Cheap bookkeeping (P1)

33. As the model, I want `arena_idea` updates to need only id, status and reason and to return a one-line acknowledgement, so that keeping ideas current is cheap.
34. As the model, I want the skill to say exactly that, so that I do not re-send titles and hypotheses.
35. As the model, I want the status line's first appearance to name the original proof as the verified baseline, not "none", so that it is accurate from the start.
36. As the model, I want the status line not to repeat what the same tool result already says, so that it carries only new facts.
37. As the model, I want the continuation message to say "all ideas closed" rather than "none recorded" when every idea is closed, so that it is truthful.
38. As a harness developer, I want `arena_polish` either removed or rebuilt around transformations that have produced gains in real runs, and never to tell the model to promote a variant that does not exist; across six runs it made 15 calls (12–89 s each) for one gain of 0.29 points that was superseded one candidate later. Decision: remove.

### Measurements we can trust (P2)

39. As a harness developer, I want turns classified by the most substantive tool they contain (compile over context over bookkeeping), with every Lean-running tool counted as compile, so that overhead is not inflated.
40. As a harness developer, I want cache reuse reported as prefix reuse (this request's cache read against the previous request's prompt) alongside the old ratio, so that models with long outputs are not penalised.
41. As a harness developer, I want the runner's live log to report each probe's outcome (candidate number, probe id, pass/fail), so that the log is readable during a run.
42. As a harness developer, I want the summary to count probe calls, promoted probes and failed probes separately, so that probe numbers are unambiguous.
43. As a harness developer, I want each run's summary to compute the acceptance criteria (rejections, misaligned goal lookups, overhead, prefix reuse, best heartbeats, overshoot), so that acceptance is checked by code.
44. As a harness developer, I want a misaligned goal lookup defined and detected (a `lean_goal` line outside the target's span, or one whose source text does not match any line the model was shown), so that criterion 2 is measurable.
45. As a harness developer, I want raw diagnostic files written in the candidate file's line numbers, so that humans and the viewer see what the model saw.
46. As a harness developer, I want `matrix.json` to include overshoot, prefix reuse, acceptance results and, for replicate groups, mean and spread of the score, so that a matrix answers "is this better" by itself.
47. As a harness developer, I want the matrix to accept a replicate count per configuration, so that variance is measured routinely.
70. As a harness developer, I want the summary and matrix to report tokens and heartbeats of the same candidate as the best proxy, so that the rows describe one proof (r3 and r4 Qwen mixed two candidates).
71. As a harness developer, I want replicate runs of one configuration started sequentially by the matrix (or their concurrency recorded), so that background-check latency does not differ between replicates (r3 and r4 ran at the same time).
48. As a harness developer, I want a preflight smoke mode that sends one real request per model and checks it settles, so that provider or wire problems are caught for cents before a matrix starts.
78. As a harness developer, I want preflight to prove the actual run appears in Langfuse with lossless outgoing
request/response data, usage, cost and tool spans, so that every measured v6 run has inspectable model traces.

### Generality

49. As a harness developer, I want the generic packet complete on every provisioned Strata row, with a test per row, so that results transfer beyond one theorem.
50. As a harness developer, I want certification to report packet completeness, reference profile coverage and exchange rates per row, so that a row is trusted before use.
51. As a harness developer, I want every acceptance experiment run on at least two theorems, so that the harness is not tuned to one proof.
52. As a harness developer, I want rows with a single toolchain version handled explicitly (a lost version is worth a third of the score), so that compatibility messages and exchange rates stay correct.

### Experiments the data motivates (v6 factors)

53. As a harness developer, I want an "episodes" mode that ends a session when its context passes a threshold or it plateaus, and starts a fresh one with a compact handoff (best proof, ideas with outcomes, recent failures), so that cache-read cost (51% of Luna's spend) stops growing with history.
54. (Deferred research.) As a harness developer, I may test a relay where one model explores structure and a second golfs its best candidate, after a measured single-model baseline and model eligibility check.
55. (Rejected.) Adaptive thinking within a run or episode is out: it risks cache invalidation and has no demonstrated score gain.
56. As a harness developer, I want each of these declared as a matrix factor with replicates, so that adoption is decided by measurement, not anecdote.
72. As a harness developer, I want the model's tool surface declared as a matrix factor (strict = v5; batched = strict plus multi-draft probes; extended = batched plus `lean_code_actions` for Lean's own "Try this" suggestions), so that any widening of tools is decided by measurement; Pi's codemode stays off in every profile (see the decision record).
73. (Deferred research.) A discovery-as-context relay was proposed; it needs direct handoff evidence before becoming a v6 factor.
57. As a harness developer, I want cross-run memory for the same theorem to stay off by default and be its own factor, so that results stay independent unless we choose otherwise.

### Viewer

58. As a harness developer, I want to compare two runs side by side (score, tokens, heartbeats and spend on shared axes), so that replicate and A/B results are visible at a glance.
74. As a harness developer, I want each score card's headline to show the best value, not the latest, so that the card agrees with the submission (Qwen r2 showed 81.62 while its best was 81.76).
75. As a harness developer, I want the run hub exportable as one static snapshot, so that a replicate comparison can be shared without a server.
59. As a harness developer, I want the viewer to mark episodes, relays and plateaus on the timeline, so that experiment structure is visible.

### Submission and reproducibility (P0)

79. As a competitor, I want a verified v6 proof JSONL with exact benchmark names and full declarations, so that my first manual warm-up upload exercises the official worker.
80. As a competitor, I want a code archive with a top-level reproduction README and pinned Lean/model environment, so that the organizers can regenerate the submitted JSONL.
81. As a competitor, I want a full per-problem accounting of every model call, including retries and discarded candidates, so that the $3/problem maximum and report table are defensible.
82. As a competitor, I want the report prepared in the official template with Approach, Models, Budget accounting and Reproduction sections, so that its required claims match the actual submission artifacts.

## Implementation Decisions

### Phase plan
- **Phase 0:** v5 replicates and cross-theorem runs are complete; findings below remain the evidence base.
- **Phase 1:** make Langfuse tracing and the official submission path work, then land direct proof-reference
  inventory and batched full-body lookup, related-lemma discovery, fixed request shape, and the observed tool
  repairs. Measurement fixes must precede comparative claims.
- **Phase 2:** evaluate episodes and further tool profiles with replicates on multiple theorems. Relay is deferred;
  adaptive thinking is rejected.

### Context packet
- Earlier-lemma ranking: score each earlier declaration by the number of distinct constants it shares with the
  statement (from the existing elaboration metaprogram), break ties by distance, show the top N with full
  signatures and file lines, and state "N of M shown". No text matching on names.
- No distance window: every declaration before the theorem is a ranking candidate; the cut is by rank and size
  only.
- Discovery pass: at packet build time the harness collects declarations whose signatures contain the
  statement's head symbols (taken from elaboration data, not names) and includes their signatures in the ranked
  section. The kickoff text asks the model to read that section and record ideas afterwards.
- `lean_local_search` results are de-duplicated by declaration and scratch copies are kept out of the index.
- On-demand related lemmas: the same ranking, seeded by constants of a term or goal the model supplies, served
  by the existing campaign CLI as a new action behind a new Arena tool.
- Completeness: the packet builder returns a section manifest. Certification asserts every section expected for
  the row is present and non-empty. A missing section is a certification failure and a warning in the run
  config, never silent. The `CallElimCorrect` degradation is the first test case.
- The packet names the original proof `#1` and prints plain paths.
- A separate Lean-aware pass inventories all directly named declarations and direct proof-term constants in
  the original proof, tagged by origin. It reports qualified name, kind, source location and signature for
  each where available, independent of the ranked discovery list.
  Names in comments/strings, local binders and the target itself must not be mistaken for global dependencies.
  A bounded packet can show the full inventory and short signatures; complete bodies are fetched by the batched
  name tool. An overflow is explicit, never silently truncated.

### Probing and profiles
- `arena_probe` accepts either one proof or a list of drafts (bounded, e.g. at most 4) and returns a table. Each
  draft follows the single-probe rules (holes → probe with goals; complete and compiling → candidate).
- Profile entries carry `proof_line` and `file_line`; a token profile (pinned token counter applied per line)
  is added to the same result.
- Idea summaries include probe and candidate counts at abandonment; facts only.

### Cap and plateau
- Keep the provider payload's output limit and thinking settings fixed through the run. The guard refuses a
  request or continuation before send when the remaining **aggregate per-problem** allowance cannot cover its
  conservative cost estimate; it records the estimate and all settled calls. Calibrate the estimate against the
  $3 official maximum, not a $0.10 diagnostic cap. Never solve a narrow remainder by clamping thinking.
- The status line gains two optional facts: remaining budget (below 25% of the cap) and "N requests / $X since
  the last improvement" (beyond a threshold), computed per request from the cost and candidate ledgers.
- The optional budget-preserving stop is a runner flag, off by default.

### Input handling
- Path normalisation for the source prefix; statement completion for drafts starting with `by` or `:=`; parent
  references accept `#N`, `pN`, `#0`, "original"; declaration lookups return constructors and fields and suggest
  suffix matches; misnamed-tool errors suggest the closest real tool; probe results carry one status field.
- Scratch copies used for compatibility and measurement compiles live outside the project tree the Lean server
  indexes.

### Bookkeeping
- `arena_idea` returns a one-line acknowledgement on update. The skill documents minimal updates.
- `arena_polish` is removed unless Phase 0 shows a gain. If it stays, its message is conditional on variants.

### Measurements
- Turn classes are ordered compile > context > bookkeeping > reasoning, and every tool that runs Lean counts as
  compile. Old and new overhead are both reported for one release so they can be compared.
- Prefix reuse = cache read of request i / (input + cache read + cache write of request i−1), reported overall
  and excluding the final request.
- Acceptance criteria are computed in the summary and aggregated in `matrix.json`, which also reports
  replicate mean and spread.
- The runner log uses the current result fields.
- A smoke preflight sends one request per model at a fixed tiny cost and checks it settles.

### Experiments
- Episodes: the runner, not Pi, ends and starts sessions. The handoff text is generated from the ledger
  (deterministic, size-bounded), and each episode has its own cached prefix.
- Relay is deferred until there is a direct A/B benefit and track eligibility is clear.
- Thinking stays fixed for every run; no adaptive factor.
- Tool profiles: strict, batched, extended (as User Story 72), selected per run and recorded in the run config.

## Testing Decisions

- Good tests assert externally observable behaviour at the existing seams: JSON from campaign actions (Seam A,
  real Lean on the Strata fixtures) and files and payloads from runner runs against the scripted provider
  (Seam B, including the Anthropic wire endpoint). No new seams are introduced.
- **Seam A:**
  - The ranked lemma section for `Core.InitsUpdatesComm` contains the four lemmas of the best known proof within
    the shown set.
  - The packet section manifest is complete for all three provisioned Strata rows.
  - A batched probe returns one row per draft and promotes complete drafts.
  - Profile entries carry file lines that match the materialized file.
  - Every input normalisation in User Stories 23–31 succeeds where v5 failed, replayed from the recorded inputs
    of the r2 runs.
  - `arena_idea` updates return a one-line acknowledgement.
- **Seam B:**
  - With a scripted cost sequence, the guard refuses the request that would exceed the aggregate per-problem
    cap and the continuation gate refuses a continuation with too little budget.
  - The payload's output limit and thinking budget are identical across all requests of a run, on both wire
    formats.
  - The status line shows remaining budget and plateau facts at the thresholds.
  - The summary's acceptance fields and prefix reuse match hand-computed values for a scripted run.
  - The live log reports probe outcomes.
  - Preflight finds the exact Arena run ID in Langfuse and verifies a complete real generation and tool span;
    unavailable or incomplete traces fail the run before comparative results are accepted.
- **Regression replays:** the r2 runs' tool inputs, replayed through the campaign CLI, must produce zero
  rejections.
- **Prior art:** the campaign CLI and protocol tests, the runner tests with the fake provider, the Lean MCP
  end-to-end test, and the Anthropic wire test.
- **Acceptance experiment** (not a unit test): the v6 harness on at least two theorems, with three replicates
  per eligible model configuration and trace-complete runs. Success:
  - zero rejections and zero misaligned goal lookups;
  - corrected overhead below 5%;
  - prefix reuse above 95% (excluding a final miss);
  - overshoot below 5% of the cap;
  - mean score on `Core.InitsUpdatesComm` above the naive baseline (76.72) for at least one model;
  - every run below the reference heartbeats on both theorems.

## Out of Scope

- Opening Pi's codemode or the full Lean MCP to the model. Capabilities stay harness-mediated (see Further
  Notes).
- Provisioning ArkLib and PutnamBench workspaces before the first warm-up submission; PhysLib and CSLib are now
  provisioned and belong in the cross-theorem validation set.
- A Lean REPL-based sub-second compiler.
- Cross-run memory as a default (it is only an experiment factor).

## Further Notes

### Evidence summary (r2, $0.10 cap each)

| | Luna (gpt-6-luna) | Qwen (qwen3.8-flash) |
|---|---|---|
| Best | #21: 153 tokens / 320 HB / 74.72 | #5: 110 tokens / 238 HB / 81.76 |
| Strategy | Golfed the original induction, guided by profiles | Replaced the induction with four in-file lemmas found by search |
| Requests / evaluations | 74 / 40 | 31 / 12 |
| Spend / overshoot | $0.1006 / $0.0006 | $0.1262 / $0.0262 |
| Overhead (reported / corrected) | 25.2% / ~11.6% | 3.9% / 4.0% |
| Cache reuse (ratio / prefix) | 97.6% / ~100% | 86.6% / 100% until the final miss |
| Spent after best | 5% | 41% |
| Tool errors | 4 (3 path prefix, 1 `by` body) | 1 (invented tool name) |
| Misaligned `lean_goal` | 3 (profile lines used as file lines) | 0 |

### What worked and must be kept
- Background full checks (26 of 26, 4–5 s), accurate `[arena]` lines delivered exactly once, auto-promotion of
  complete probes (Luna made zero `arena_evaluate` calls), correct submissions.
- Diagnostic line alignment (`file_line − proof_line` constant everywhere).
- The restricted tool surface (five direct Lean tools, no codemode).
- Generic context: the packet's in-file lemma gave Qwen its first idea before any tool call.

### Decision record: restricted tools (codemode)
Pi's codemode is a JavaScript sandbox that can call every tool and Pi's non-LLM `models` with the session's
credentials, outside the Arena budget guard. `lean_run_code` and `lean_verify` can run IO through `#eval`,
`lean_build` costs minutes of CPU, network search is non-deterministic, and every extra tool is a new way to
fail (one tool's arguments caused most of Luna's early errors). The model already has the capabilities that
matter: a complete probe is scored with heartbeats, `arena_profile` gives per-line heartbeats, and
`lean_multi_attempt` tries tactics without editing.

What codemode would add is batching: several calls in one turn, with only a summary returned. That is worth
having because cost is dominated by re-reading context per turn, and it is delivered safely by multi-draft
probes (User Story 9). The rule: the harness exposes capabilities, not mechanisms. Capabilities it can price,
lock and log; mechanisms such as "run any script against any tool" void every guarantee.

How this gets revisited: the tool profile is a matrix factor (User Story 72). Evidence that would justify more:
tool errors or thinking that show the model reaching for a capability it lacks, or runs of consecutive
single-draft probes that batching would collapse. In Phase 0 neither appeared: no run tried to call a missing
tool except invented names for existing ones, and the best result came from search plus single probes.

### Phase 0 answers (see the evidence section for the data)
1. **Does Qwen find the induction-free route every time?** No: 2 of 3 runs. The deciding factor was discovery
   of three lemmas 600 lines above the theorem, outside the packet's window. Winning runs had all three by
   $0.017; the losing run found one at $0.06, dismissed it, and rejected the route as "too speculative" at
   $0.097.
2. **Does Luna ever probe the commutation idea?** Never: 0 of 94 probes were induction-free. It abandoned the
   idea by argument twice, both times with factually wrong reasons, and once never saw the lemmas.
3. **Is the final-request cache miss tied to our guard?** Strongly indicated, with the exact mechanism open.
   All three Qwen requests cut to `max_tokens` caps of 4,520 / 1,486 / 3,738 lost the cache; eight larger cuts
   kept it. Those caps are reconstructed from the guard and ledger, not captured final wire payloads; actual
   generated outputs on the misses were 2,095 / 1,486 / 242 tokens.
   Pi's high setting starts with a 16,384-token thinking budget; our guard reduced that budget on **all** of
   these cut requests. Thus a changed thinking budget alone cannot distinguish hit from miss. Anthropic's cache
   rule is informative but may not govern this Anthropic-compatible Qwen host. Capture actual outgoing settings
   and compare fixed-shape requests in a controlled trace-backed preflight to complete the RCA.
4. **Run-to-run spread?** Qwen 81.76 / 84.58 / 73.79 (spread ~11, bimodal by route); Luna 74.72 / 74.00 /
   76.51 (spread ~2.5). Size v6 replicates for Qwen-like variance: at least three per configuration.
5. **Does `arena_polish` ever gain?** Once in 15 calls (+0.29, superseded at once). Remove it.

### Known best proof (analysis reference, never shown to models)
Combining tricks from the six runs gives **76 tokens / 203 HB / proxy 87.10** on all three versions (verified
independently; kept at `runs/analysis/Core_InitsUpdatesComm-hybrid-87.10.lean`, outside version control). It
uses the induction-free route of Qwen r2/r3 plus generic golfs (User Story 64). Estimated ceiling from these
ingredients: about 88. The gap between the best run (84.58) and this proof is a measure of what generic
transformation rules could still recover.

### Why Qwen usually beat Luna (cross-run analysis)
The runs split on proof structure, not golfing skill: all four induction runs ended between 73.8 and 76.5 and
none beat the naive baseline; both induction-free runs ended at 81.8–84.6.
- **Search before committing** decided the route. Qwen's winning runs searched and read for 16–19 turns before
  recording ideas; Luna and Qwen r4 recorded ideas at turn 0, as the v5 kickoff asked.
- **Discovery depended on luck.** The packet's lemma window started 450 lines too late, and
  `lean_local_search` filled its limit with four copies of each name, so a singular query missed the key lemma.
- **Ideas were dropped by argument, not by probe.** Luna's stated reasons were wrong; a single skeleton probe
  would have shown it.
- **Turn style.** Qwen spends on deep thinking (7–11 turns over 3K output tokens); Luna takes 2.4× more,
  shorter turns, and re-reading context is half its spend. Luna compiles 7–10× sooner and improves on almost
  every candidate, but at about 0.5 points a step under a structural ceiling of about 76.
Implication: make discovery deterministic (User Stories 60–63) and the route choice follows for any model.

## Ideas under discussion (not yet decided)

Each needs a decision before Phase 1 or Phase 2 implements it.

1. **Episodes (fresh session with a handoff).**
   - What triggers a reset: context size, a plateau, or both?
   - What the handoff carries: best proof and ideas only, or also failed approaches and lemmas found?
   - Does losing the reasoning history cost more than the cache-read savings (51% of Luna's spend)?
   - Proposal: trigger on context size only, carry lemmas found plus ideas with outcomes, and measure.
2. **Relay:** deferred until a single-model baseline leaves a specific, measured gap and both models are
   eligible for the chosen competition track. There is no v5 relay result.
3. **Adaptive thinking:** closed; keep settings fixed for the run.
4. **Lemma ranking details.** Shared-constant counts may rank ubiquitous helpers first. Alternatives: weight by
   the statement's head symbols, by the lemma's conclusion matching a goal's head predicate, or by inverse
   frequency across the file. Proposal: head symbols with inverse-frequency weights, tested against the three
   provisioned Strata rows.
5. **Idea evidence.** Surfacing "abandoned with 0 probes" may push models to probe every idea, which costs
   money. Options: a facts-only line; a skill rule "one skeleton probe per structural idea before abandoning
   it"; or harness-run skeleton checks. Proposal: facts-only line plus the skill rule; measure probe spend.
6. **Harness-run discovery pass (User Story 63).** Determine its size after the mandatory direct-reference
   inventory is measured. Keep related but unreferenced declarations ranked and bounded; fetch full bodies by
   name on demand.
7. **Re-surfacing parked ideas.** When a newly seen lemma concludes the goal's head predicate, should the status
   line mention parked ideas? It is factual but edges toward advice. Proposal: defer until after 60–63 land.
8. **Extended tool profile.** Is `lean_code_actions` worth a schema slot? It surfaces Lean's `Try this`
   suggestions at no CPU cost. Proposal: include only in the extended profile and let the matrix decide.
9. **Generic proof-transformation rules (User Story 64).** Several came from one theorem. Proposal: keep only
   rules that hold for Lean in general (token counting, `rw` vs `▸` costs) and verify each on the second
   Strata row before adding it to the skill.

## Phase 0 evidence

### r2 (2026-10-06) — baseline for the replicates
See "Evidence summary (r2)" above.

### r3 and r4 (2026-10-06, replicates; r3 and r4 ran concurrently)

| Run | Best (proxy) | Tokens / HB | Route | Requests | Spend / overshoot | Overhead reported / corrected | Spent after best |
|---|---|---|---|---|---|---|---|
| r2 Luna | 74.72 | 153 / 320 | induction | 74 | $0.1006 / $0.0006 | 25.2 / 11.6% | 5% |
| r2 Qwen | 81.76 | 110 / 238 | **no induction** | 31 | $0.1262 / $0.0262 | 3.9 / 3.3% | 41% |
| r3 Luna | 74.00 | 157 / 336 | induction | 86 | $0.1006 / $0.0006 | 23.4 / 23.4% | 13% |
| r3 Qwen | **84.58** | 90 / 258 | **no induction** | 35 | $0.1009 / $0.0009 | 10.6 / 2.9% | 8% |
| r4 Luna | 76.51 | 143 / 282 | induction | 79 | $0.1009 / $0.0009 | 10.5 / 10.5% | 10% |
| r4 Qwen | 73.79 | 162 / 268 | induction | 32 | $0.1017 / $0.0017 | 13.6 / 8.8% | 0% |

Harness findings across the six runs:
- Background checks: 100% coverage; latency 4–15 s (higher in r3/r4 because they ran concurrently). All six
  submissions correct. `[arena]` lines accurate; "best verified: none" at start in 6/6 runs.
- Tool errors recur: `strata/` path prefix 3/6 runs, `by`-only probe body 3/6 (every Luna run), invented
  `mcp__` tool names 1/6, `evaluate` with `sorry` 1/6, skill path given to `arena_source` 1/6, empty or
  reasonless `arena_idea` 1/6. New silent defect: `candidate` plus `from_probe` returned the cached candidate.
- Misaligned `lean_goal`: 2/6 runs (Luna only), always right after `arena_profile`.
- Bookkeeping is real for Luna (16–36 `arena_idea` calls; 22% in r3 even after correction).
- All runs stopped on the usage cap; plateau stops never came near firing; the largest dry stretch is Qwen's
  search before its first candidate (24–48% of budget), which context ranking addresses.

### Priority revisions after Phase 0 (historical; superseded by current decisions above)
1. **Promoted to the top of P0:** context discovery (60–63, then 1–3, 7). It decided the route in 6/6 runs.
2. **New P0:** survey-first kickoff (62) and generic transformation rules (64, verified on a second row).
3. **At the time:** cap gate with k ≈ 1–1.5 (15), continuation gate (16, 66); the miss-aware term
   (65) was optional. The current decision is a stable-payload gate against $3/problem.
4. **At the time:** constant payload (17) and plateau facts (20, 21) were demoted. Story 17 is now promoted
   by the cross-theorem cache evidence and the need for stable request settings.
5. **Raised within P1:** compact `arena_idea` (33, 34); path prefix and `by` bodies (23–25), which recur in
   every Luna run.
6. **Decided:** remove `arena_polish` (38).
7. **Experiment order for Phase 2:** exact-trace single-model episodes (53), then tool profiles
   (72).


### Cross-theorem runs (2026-10-07; full report: docs/RESULTS-v5-generalization.md)

Four more theorems on the unchanged v5 harness (two Strata, one CSLib, one PhysLib), one Luna/Qwen pair each.

| Theorem | Luna | Qwen | Verified hybrid |
|---|---|---|---|
| extractedOldExprInVars | **72.29** | 53.86 | 82.42 |
| substOldPostSubset | **52.45** | none | 82.86 |
| bisimilarity_congr_choice (3 versions) | **78.55** | 78.45 | 84.52 |
| fundamental_theorem_of_variational_calculus' | 45.91 | **83.35** | not built |

Priority revisions recorded with the cross-theorem report (current decisions above supersede items 2 and 5):
1. **P0 discovery** must cover *imported* project lemmas (decisive on extract and CSLib), not only the theorem's file.
2. **P0 request stability** (story 17 restored): keep output and thinking settings fixed; gate unchanged
   requests before send, and never continue after the model declares it is done. The old ~5.5K threshold
   proposal was based on correlation and is withdrawn.
3. **New P1:** constructors of local inductives in the packet; the tactic libraries available (no Mathlib → no `tauto`);
   goal trace before normalising `simp`; invalid tool JSON surfaced instead of Pi's silent `{}`; readable private names
   in `arena_declaration`; `arena_source` accepts the paths `lean_local_search` returns.
4. **Skill:** literal token counting, positional goal handling and shared closers held everywhere; `grind` and `<;>`
   chains are theorem-dependent trade-offs; new traps (`any_goals exact` is not a filter; positional or-patterns on
   multi-constructor families; `use` vs `exists` elaboration).
5. **Experiments:** the analyst-built hybrids show scaffolding headroom but do not establish a relay gain.
   Prioritize single-model tooling and trace-backed analysis before testing a handoff.
