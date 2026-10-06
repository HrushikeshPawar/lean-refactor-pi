# Spec: Arena harness v6 — context that finds structure, a cap that holds, measurements we can trust

Status: planned. Phase 0 (v5 replicates r3, r4) is done; its evidence and the revised priorities are below.
Open design questions to settle before Phase 1 are listed under "Ideas under discussion".
Source: v5 acceptance runs `v5-accept-20261006` (aborted) and `v5-accept-20261006-r2` (Luna and Qwen on
`Core.InitsUpdatesComm` at $0.10 each), three parallel run analyses, and a harness audit (2026-10-06).
Predecessor: `docs/SPEC-harness-v5.md`.

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
- **Generality is untested and already broken.** On the second provisioned Strata row
  (`CallElimCorrect.extractedOldExprInVars`) the generic packet silently lacks its definitions, goal trace,
  signatures and earlier-lemma sections (3.8K characters vs 21.5K). Every result so far comes from one theorem.
- **Results depend on luck in discovery.** Three replicates per model (Phase 0) show the score is decided by
  proof structure: runs that found three in-file lemmas 600 lines above the theorem reached 81.8–84.6; the four
  runs that did not stayed between 73.8 and 76.5, below the naive baseline. Qwen found them in 2 of 3 runs,
  Luna in none. A proof built from the runs' own ingredients reaches 87.10, so the headroom is real.

We keep small budgets ($0.10–$0.20 per run) until the harness is validated, so every wasted turn and every wrong
measurement matters.

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
8. Experiments the data now motivates — session episodes, model relays, adaptive thinking — can be run through
   the matrix as declared factors.

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
17. (Demoted: replicates refuted the cause.) As a harness developer, I want the option to keep the output limit and thinking budget constant for a run, so that if deep budget cuts ever prove to break a provider's cache we can turn reshaping off; 26 of 27 reshaped requests kept their cache.
18. As a harness developer, I want the guard's decision and the estimate behind it recorded in the cost ledger, so that every stop can be audited.
19. As the model, I want the remaining budget in the status line once it falls below a quarter of the cap, so that I can finish the most valuable work.
20. (Demoted: would rarely have changed anything in r3/r4.) As the model, I want the status line to state the requests and money spent since my last improvement, counted from my first candidate, once that crosses a threshold, so that I can judge whether to change approach; the harness gives no advice.
21. As a harness developer, I want the plateau facts computed per request rather than per agent turn, so that one long turn cannot hide a plateau.
65. As a harness developer, I want an optional miss-aware term in the gate (last prompt size × cache-write price) for providers known to drop caches, so that a full cache rewrite on the last request cannot overshoot; off by default, because it would have cost Luna its last four improvements.
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

### Generality

49. As a harness developer, I want the generic packet complete on every provisioned Strata row, with a test per row, so that results transfer beyond one theorem.
50. As a harness developer, I want certification to report packet completeness, reference profile coverage and exchange rates per row, so that a row is trusted before use.
51. As a harness developer, I want every acceptance experiment run on at least two theorems, so that the harness is not tuned to one proof.
52. As a harness developer, I want rows with a single toolchain version handled explicitly (a lost version is worth a third of the score), so that compatibility messages and exchange rates stay correct.

### Experiments the data motivates (v6 factors)

53. As a harness developer, I want an "episodes" mode that ends a session when its context passes a threshold or it plateaus, and starts a fresh one with a compact handoff (best proof, ideas with outcomes, recent failures), so that cache-read cost (51% of Luna's spend) stops growing with history.
54. As a harness developer, I want a relay mode where one model explores structure and a second model golfs its best candidate, so that we can test whether combining Qwen-like structure finding and Luna-like golfing beats either alone.
55. As a harness developer, I want the thinking level adjustable per episode (e.g. high while exploring, lower while golfing), so that long, low-yield reasoning turns late in a run can be measured and avoided.
56. As a harness developer, I want each of these declared as a matrix factor with replicates, so that adoption is decided by measurement, not anecdote.
72. As a harness developer, I want the model's tool surface declared as a matrix factor (strict = v5; batched = strict plus multi-draft probes; extended = batched plus `lean_code_actions` for Lean's own "Try this" suggestions), so that any widening of tools is decided by measurement; Pi's codemode stays off in every profile (see the decision record).
73. As a harness developer, I want a relay variant where the first model's discovery (lemmas found, structure chosen) is handed to a second model as context rather than a proof, so that we can separate "finding the route" from "golfing it".
57. As a harness developer, I want cross-run memory for the same theorem to stay off by default and be its own factor, so that results stay independent unless we choose otherwise.

### Viewer

58. As a harness developer, I want to compare two runs side by side (score, tokens, heartbeats and spend on shared axes), so that replicate and A/B results are visible at a glance.
74. As a harness developer, I want each score card's headline to show the best value, not the latest, so that the card agrees with the submission (Qwen r2 showed 81.62 while its best was 81.76).
75. As a harness developer, I want the run hub exportable as one static snapshot, so that a replicate comparison can be shared without a server.
59. As a harness developer, I want the viewer to mark episodes, relays and plateaus on the timeline, so that experiment structure is visible.

## Implementation Decisions

### Phase plan
- **Phase 0 (now):** two or three replicate runs of the unchanged v5 harness (see the handoff below). Their
  analysis is appended to this document and may reorder the P0–P2 lists. No v5.x patches.
- **Phase 1:** P0 items, in the order set by Phase 0: context discovery (60–63, 1–3, 7), survey-first kickoff
  (62), the cap gate (15, 16, 66) and generic proof-transformation rules (64); then P1 items (inputs,
  bookkeeping, removing `arena_polish`). P2 measurement fixes land first so Phase 1 is measured correctly.
- **Phase 2:** the experiment factors (episodes, relay, adaptive thinking), each through the matrix with
  replicates and on two theorems.

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

### Probing and profiles
- `arena_probe` accepts either one proof or a list of drafts (bounded, e.g. at most 4) and returns a table. Each
  draft follows the single-probe rules (holes → probe with goals; complete and compiling → candidate).
- Profile entries carry `proof_line` and `file_line`; a token profile (pinned token counter applied per line)
  is added to the same result.
- Idea summaries include probe and candidate counts at abandonment; facts only.

### Cap and plateau
- The guard keeps the request payload unchanged. It refuses a request when
  `remaining < k × max(cost of the last 5 settled requests)` with `k = 1.5` by default, and records the
  estimate. An optional miss-aware term covers providers that drop caches.
  The continuation gate uses the same rule. Before five requests have settled, the guard falls back to the
  current behaviour.
- Reshaping the final request's output limit stays allowed (replicates showed no cache effect); a flag keeps it
  constant if a provider ever proves otherwise.
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
- Relay: a matrix factor naming the explorer model, the golfer model and the split of the budget.
- Adaptive thinking: a per-episode thinking level.
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
  - With a scripted cost sequence, the guard refuses the request that would exceed the cap and the continuation
    gate refuses a continuation with too little budget.
  - The payload's output limit and thinking budget are identical across all requests of a run, on both wire
    formats.
  - The status line shows remaining budget and plateau facts at the thresholds.
  - The summary's acceptance fields and prefix reuse match hand-computed values for a scripted run.
  - The live log reports probe outcomes.
- **Regression replays:** the r2 runs' tool inputs, replayed through the campaign CLI, must produce zero
  rejections.
- **Prior art:** the campaign CLI and protocol tests, the runner tests with the fake provider, the Lean MCP
  end-to-end test, and the Anthropic wire test.
- **Acceptance experiment** (not a unit test): the v6 harness on two theorems, Luna and Qwen, three replicates
  each, at $0.10. Success:
  - zero rejections and zero misaligned goal lookups;
  - corrected overhead below 5%;
  - prefix reuse above 95% (excluding a final miss);
  - overshoot below 5% of the cap;
  - mean score on `Core.InitsUpdatesComm` above the naive baseline (76.72) for at least one model;
  - every run below the reference heartbeats on both theorems.

## Out of Scope

- Increasing per-run budgets beyond $0.20.
- Opening Pi's codemode or the full Lean MCP to the model. Capabilities stay harness-mediated (see Further
  Notes).
- Provisioning PhysLib, CSLib, ArkLib and PutnamBench workspaces. v6 generality uses the provisioned Strata rows.
- Official server submission and calibration against the Arena worker.
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
3. **Is the final-request cache miss tied to the guard shrinking `max_tokens`?** Refuted: 26 of 27 reshaped
   requests kept their cache, and the r2 miss is the only one in 337 requests. Treat it as a provider event.
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
2. **Relay (one model explores, another golfs).**
   - Direction: the data favours Qwen for structure and Luna for fast local steps, but Luna's golfing never
     beat Qwen's own polish.
   - Budget split and handover: a proof, or discovered context (User Story 73)?
   - Proposal: first test "discovery as context" against "proof as start", same budget.
3. **Adaptive thinking.** What signal switches the level (first candidate? plateau?), and can it be changed
   without breaking the cache? Since reshaping did not break caches (Phase 0 answer 3), a per-episode level is
   safe; within a session it is unproven.
4. **Lemma ranking details.** Shared-constant counts may rank ubiquitous helpers first. Alternatives: weight by
   the statement's head symbols, by the lemma's conclusion matching a goal's head predicate, or by inverse
   frequency across the file. Proposal: head symbols with inverse-frequency weights, tested against the three
   provisioned Strata rows.
5. **Idea evidence.** Surfacing "abandoned with 0 probes" may push models to probe every idea, which costs
   money. Options: a facts-only line; a skill rule "one skeleton probe per structural idea before abandoning
   it"; or harness-run skeleton checks. Proposal: facts-only line plus the skill rule; measure probe spend.
6. **Harness-run discovery pass (User Story 63).** How large may it be before it bloats the cached prefix, and
   should it run per goal (on demand) as well as at kickoff? Proposal: kickoff only, bounded to the top 15
   signatures; on-demand through the related-lemmas tool.
7. **Re-surfacing parked ideas.** When a newly seen lemma concludes the goal's head predicate, should the status
   line mention parked ideas? It is factual but edges toward advice. Proposal: defer until after 60–63 land.
8. **Extended tool profile.** Is `lean_code_actions` worth a schema slot? It surfaces Lean's `Try this`
   suggestions at no CPU cost. Proposal: include only in the extended profile and let the matrix decide.
9. **Generic proof-transformation rules (User Story 64).** Several came from one theorem. Proposal: keep only
   rules that hold for Lean in general (token counting, `rw` vs `▸` costs) and verify each on the second
   Strata row before adding it to the skill.

---

## Handoff: Phase 0 replicate runs (v5, unchanged)

Purpose: measure variance and answer the open questions above before building v6. The harness is frozen at the
current `hrushikesh/harness-v5` head; do not change code between replicates.

### Runs
Two replicate pairs on the same configuration as r2 (a third if the first two disagree on the open questions):

```bash
cd /mnt/SharedDrive/ActiveProjects/lean-refactor-pi
python tools/run_experiment_matrix.py --theorem Core.InitsUpdatesComm --prefix v5-rep-20261006-r3 \
  --factor model --values gpt-6-luna,qwen3.8-flash --cap 0.1 --parallel 2
# after r3 finishes:
python tools/run_experiment_matrix.py --theorem Core.InitsUpdatesComm --prefix v5-rep-20261006-r4 \
  --factor model --values gpt-6-luna,qwen3.8-flash --cap 0.1 --parallel 2
# optional third replicate, same command with --prefix v5-rep-20261006-r5
```

Watch (one terminal each):
```bash
tail -f runs/pi-budget/v5-rep-20261006-r3-matrix/*.log
# one page for every replicate: an overview table plus a live tab per run (new runs appear by themselves)
PYTHONPATH=. uv run --no-project python tools/serve_candidate_graph.py --match 'v5-*-20261006-*' --port 8765
```
Stop with one Ctrl+C in the matrix terminal (a clean stop that writes `cost.json` and the summary).

Do not use `CallElimCorrect` rows for Phase 0: their packet is currently degraded (User Story 7), so results
would measure missing context, not the harness.

### Analysis protocol (per replicate pair)
Run the same three read-only analyses used for r2, in parallel:
1. **Per-model narrative.** Ideas, structures tried, the candidates where the score jumped and what changed, the
   final proof vs the original, where each lemma in the best proof was learned (packet, search or declaration),
   tool calls and errors with messages, spend after the last improvement.
2. **Harness audit.** Background check latency and coverage, accuracy of the `[arena]` lines, continuations and
   stop reasons, the corrected overhead breakdown, overshoot and the request that caused it (including whether
   `max_tokens` had been reduced), prefix-cache reuse, misaligned `lean_goal` lines, the probe-parent notes.
3. **Cross-replicate comparison** (from the second pair on). Score mean and spread per model, how often the
   induction-free route is found, overshoot frequency, `arena_polish` gains.

Remember that `summary.txt` overhead and cache figures carry the v5 measurement defects (P2). Report the
corrected values from the analysis, not the raw ones.

### Where to record results
Append one block per pair to "Phase 0 evidence" below, using the same table shape as the r2 evidence summary,
plus answers to the open questions. Then revise the Phase 1 priority order at the end of that section if the
evidence calls for it.

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

### Priority revisions after Phase 0
1. **Promoted to the top of P0:** context discovery (60–63, then 1–3, 7). It decided the route in 6/6 runs.
2. **New P0:** survey-first kickoff (62) and generic transformation rules (64, verified on a second row).
3. **Kept P0 but retuned:** cap gate with k ≈ 1–1.5 (15), continuation gate (16, 66); the miss-aware term
   (65) is optional.
4. **Demoted:** constant payload (17) and plateau facts (20, 21); neither would have changed Phase 0
   outcomes.
5. **Raised within P1:** compact `arena_idea` (33, 34); path prefix and `by` bodies (23–25), which recur in
   every Luna run.
6. **Decided:** remove `arena_polish` (38).
7. **Experiment order for Phase 2:** discovery as relay context (73) before episodes (53), then tool profiles
   (72).
