# v6cov Cslib.SKI.parallelReduction_diamond, deepseek-v4.1-flash r1: single-route run study

Run: `runs/pi-budget/v6cov-Cslib.SKI.parallelReduction_diamond-deepseek-v4.1-flash-r1/` (16:37:41 to 17:31:19, 54 min wall, last row of the v6cov campaign). Cap $0.5 soft, thinking high, code with lrx (compaction bypasses the budget guard) and vqm (request `max_tokens` = 64000). Sources: summary.txt/json, cost-ledger.jsonl, ledger.jsonl, trace-journal.jsonl, events.jsonl, the Pi session JSONL (all 57 turns of reasoning read), proofs/, route-queue.jsonl, campaign.log. No Langfuse.

## TL;DR

- **Result:** best verified #30, proxy 70.34 (240 tok, 415 HB; baseline 407 tok / 1383 HB = 33.33). Score parts: compat 33.33 + tokens 13.68 (41% saved) + heartbeats 23.33 (70% saved). $0.4529 settled (+$0.0433 unresolved, see 6.8), 57 requests, stop `finished` at 9.4% left (rule obeyed).
- **What capped it:** the heartbeat axis was harvested by the first compiled candidate (#2: 412 HB at 4.3 min) and never moved again (405 to 436 for 48 minutes; +3 net). Every later point (+11.7) came from tokens, 384 to 240, one to six tokens per turn. The run was cut by the cap while still improving: +4.8 pts in the last $0.14 before #26, then 0.08 pt for the last five turns. Overhead took roughly a third of the money (compaction 13.7%, bookkeeping+rejected 12.1%, context reads 11.6%).
- **Why one route:** 0 of 53 attempts reached route-credit. Every attempt, complete or sorry stub, fingerprinted at similarity 0.56 to 1.00 against the original (threshold 0.5), because every proof of this row shares the same constructors and three helper lemmas. The finish gate, which says "Only one route has been tried", did not constrain the run: refusal depended only on the 10% remaining rule. It did push the model into about $0.03 of stub drafts (4 route-seeking turns) that could not be credited.
- **The finish gate was net positive here:** the model first tried to stop at 55% unspent (turn 30, 63.95). All of the +6.4 pts after that came from continued work. It misjudged its own spend (said "60-70%" at actual 38%) because no tool result shows spend.
- **Fixes behaved.** lrx: one threshold compaction at 503,922 tokens, bypass fired (reserve est. $0.2123, actual $0.0623), ledger reconciled, summary 2.7K output tokens, `stop` not `length`, memory message injected 34 s later, model resumed without re-reading. vqm: 57/57 requests carried `max_tokens 64000`; max turn output 23,114 (36%), no length stop (a 32K cap would not have bound either). The compaction repair also fixed one null-argument tool call.
- **Biggest harness cost: the compaction itself.** It sent 404K uncached input tokens (cacheRead 0) = $0.0623, plus a cold follow-up turn $0.0123: about $0.075, 15% of the cap, about 9 productive turns. Keeping 504K in cache costs ~$0.0015 per turn, so break-even is about 55 turns; about 10 turns remained. The models.yaml note ("~3 uncached requests, ~$0.03") is off by 2.5x.
- **Other concrete defects:** (a) `arena/engine.py:277` `_SORRY_TACTIC` misses `| case => sorry`, so 6 of 9 sorry drafts returned no goals (incl. every stub meant to open a route); (b) the fast-to-full check completes about 1.1 s after the fast eval but its result reaches the model one turn late (~80 s), so 3 candidates were built on a lemma that fails on v4.30.0; (c) a failed connection attempt leaves a $0.0433 reservation that is reported as cost (inflates all-call cost 9.6%).
- **Model:** strong golf discipline (no duplicate drafts, only 1 cached draft in 54, compat trap caught and avoided afterwards), but it spent about $0.057 (11%) on learning tactic semantics by experiment, made 4 heartbeat profiles and ran about one targeted heartbeat experiment, and did not know its spend.

## 1. Timeline: spend and score

Spend is settled USD at the time of evaluation (cost-ledger). t is minutes from first request.

| t (min) | spend | best verified | event |
|---|---|---|---|
| 0.1 | $0.003 | - | turn 0 reads the source; the 2nd request got `Connection error`, auto-retried (2 s) |
| 4.3 | $0.023 | **#2 58.62** (384 tok / 412 HB) | first compiled draft; HB 1383 to 412 (-70%), tokens only -5.7% |
| 6 to 16 | $0.04 to $0.10 | 58.62 | research turns: 23K, 18K, 21K, 21K-token thinking turns, reading a sibling lambda-calculus proof, `Join` API, `use` semantics |
| 16.2 | $0.099 | #3 61.97 (336/436) | `use`-form closings, named hypotheses |
| 24 to 26 | $0.156 to $0.172 | 61.97 | #5/#6/#7 use a name absent in v4.30.0: fast est. 63.2 but full 54.87. Three candidates wasted |
| 28.8 | $0.196 | #11 63.33 (328/407), #12 63.7 (324/405) | `obtain` for `let` pattern: -30 HB (the only HB win of the run) |
| 31.7 | $0.224 | #13 63.95 | first `arena_finish` at 55% unspent: refused |
| 34 | $0.232 | #16 54.32 (327 tok / **784 HB**) | the "reference structure" draft as a new route: 2x HB, rejected |
| 34.9 to 40.8 | $0.245 to $0.290 | #17 64.66, #18 65.01, #19 65.03, #20 65.49, #21 65.58 | removing instance-line variants, `cases X; rename_i` for `obtain` (-6 tok, +6 HB) |
| 44.9 to 47.5 | $0.316 to $0.338 | #22 67.11, #23 67.44, #24 67.76, #25 68.5 | `rename_i` to name hypotheses, bullets instead of `case` labels (-19 tok), renaming all names in one `rename_i` |
| 48.3 | $0.345 | **#26 70.26** (241/415) | dropping the bullet layout and running the cases as a flat sequence: -20 tok (+1.76 pts in one turn) |
| 50.4 | $0.369 | #30 70.34 (240/415) | -1 token |
| 51.2 | $0.369 to $0.44 | - | compaction (503,922 tokens) |
| 52.7 | $0.4529 | submit #30 | `arena_finish` confirmed at $0.0471 left |

Value of spend: first $0.023 bought +25.3 pts; $0.023 to $0.29 bought +7.0 ($0.038/pt); $0.29 to $0.345 bought +4.7 ($0.012/pt, the flat-layout restructure); the last $0.108 bought +0.08. Post-best spend per the summary ($0.0836 over 5 requests) is 74% compaction ($0.0623); the 5 real turns cost $0.0214.

Axis story: HB 412 (#2), 436 (#3 to #9), 405 to 407 (#12 to #15), 412 to 420 (#18 to #25), 415 (#26 to #30). One token = 0.082 pt, 100 HB = 2.41 pt (about 29 tokens). The 30 HB gained at #11 equalled 9 tokens. The sum of every HB change after #2 is worth -0.07 pt.

## 2. Tool use

57 requests, 61 tool results (35 `arena_probe` incl. 1 error, 6 `arena_finish`, 6 `arena_source`, 5 `lean_goal`, 4 `arena_profile`, 3 `arena_state`, 2 `arena_find`; 0 `arena_evaluate`, `arena_idea`, `arena_candidate`, `arena_declarations`).

| item | value |
|---|---|
| drafts per probe call | 54 drafts in 34 successful calls (1 draft in 22 calls, 2 in 8, 3 in 4); 1 cached draft |
| draft outcomes | 29 compiled (became candidates, 30 incl. baseline), 15 failed to compile, 9 sorry stubs |
| first-error classes (15 failed) | type mismatch 4, too many variable names 3, kernel invalid projection 2, `subst` needs a variable 2, grind (redundant arg / failed) 2, rcases on non-inductive 1, constructor fields 1 |
| Lean latency | 53 model-lane checks, p50 0.23 s, p95 2.16 s, max tool call 7.1 s, 0 timeouts, gate healthy, warm workers on all 4 versions |
| tool wall time total | about 70 s of 54 min (about 2%); `arena_finish` 4 to 7 s each (state+frontier+submission subprocesses) |
| model latency | mean 55 s per request, median 51 s, max 155 s (about 145 output tok/s), sum 51.7 min = 96% of wall |
| cache | 95.7% reuse (12.95M read vs 0.58M uncached tool-turn input), 93.8% savings; recent ten 95.3% |
| cost split | output 444K tokens = $0.266 (59%), uncached input 985K = $0.148 (33%, of which compaction $0.061), cache read $0.039 (9%) |
| by turn type (summary) | compile 38x $0.283 (62.5%), compaction 1x $0.062 (13.7%), context 7x $0.053 (11.6%), bookkeeping 9x $0.048 (10.6%), rejected 1x $0.0065 (1.4%) |

Wasted or repeated calls:
- **Error call (turn 12):** `arena_probe` arrived with `arguments: null` after 4,759 output tokens (drafts were in the thinking). Result: "the tool call arrived without arguments; resend it". Turn 13 re-emitted three drafts (1,825 tokens). Cost $0.0084, about 2 min wall. `compaction_repair` later logged `null_tool_arguments: 1` (the null-argument call was repaired in history before the compaction request).
- **6 `arena_finish` calls** (turns 30, 39, 48, 51, 53, 55) = $0.030 of turn cost, used to learn the budget (the model says so at turn 30: "call it to check the budget"). Refusals 1 to 3 happened at 55%, 42%, 29% remaining; 4 and 5 at 11.2% and 10.2%; the sixth confirmed.
- **5 `lean_goal` calls** (turns 4 to 5) exist only because the sorry probe returned no goals (see 6.3).
- **3 `arena_state`** at turns 23, 36, 38: the same information the `[arena]` footer already carried.
- No repeated `arena_source`/`arena_find` result (trim.ts stubs never triggered), no duplicate drafts.
- The `[arena]` footer appears on the next tool result; the pass/fail of #6/#7 arrived about 80 s after the fast eval although the full check finished 1.1 s after it (ledger evaluation timestamps).

## 3. Model reasoning and strategies

All 57 turns are thinking-only (no visible text), 1.30M characters of thinking in total, no length stops. Output: mean 7.9K tokens/turn, median 7.2K, 7 turns at least 16K, 4 at least 20K, max 23,114 (turn 8; 61K chars of research on a sibling theorem). Context replays all reasoning_content (the single agent turn never resets), so about 400K of the 504K peak context is the model's own thinking.

Strategies by effect on the proof (tokens, HB):
1. **Turn 2 plan:** three candidate shapes (keep structure + golf, one recursion with per-case automation, heavy automation). The automation draft failed: 3,475 HB failing and "redundant parameter" errors; the model concluded the automation cannot build a witness, abandoned it, and never returned to automation-heavy forms.
2. **#2 (4.3 min): 407 to 384 tok, 1383 to 412 HB.** Replacing the reference's automation-closed leaf cases and recursion by explicit closings removed about 970 HB in one step; 3 of the first 4 probes failed on parse issues (`⬝` vs look-alike `⭝` application operator typed wrongly, `Exists` field counts).
3. **Token golf (steps with measured effect):** `use` instead of `exact ⟨…⟩` (-2 tok each); `..` for remaining args (-2); dot-notation chains (`hc.1.par hd.1` is one token); inferred witnesses `_`; `Std.Refl` instance line (+8 tok, -11 tok and about -9 closings; kept after v4.30 check); label names dropped (`| red_K =>`); `cases X; rename_i a b` instead of `obtain ⟨a, b⟩` (-3 tok, +6 HB, a trade it priced at +0.02 pt); bullets instead of `case` labels (-19 tok); `rename_i` of several names at once (-4 to -9 tok); finally the flat sequence with no bullets (-20 tok, -5 HB).
4. **HB:** `obtain` instead of `let ⟨⟩` pattern: -30 HB (the only measurable HB win). Tried and failed: `clear` (0 HB), single-line layout (0 HB, +10 tok), reference structure with explicit recursion (+380 HB). Profile (4 calls) said: 4 case splits 116 to 136 self-HB (28 to 33%), 81 to 85 "unattributed", the rest about 20 closings of 10 to 19 HB. The model labelled the splits "inherent" and did not run an experiment aimed at them.
5. **Route-seeking (under finish pressure):** i2 (reference structure, completed, 784 HB, rejected), i3 and i4 (35 to 105 token sorry stubs, never completed, got no goals), i5/i6 (mirrored order, 35 and 40 token stubs). None completed beyond the stub, none credited.

Misreads and detours:
- Believed `use` auto-closes residual goals with `assumption`; spent turns 11 to 15 and 19 testing that (about $0.057 for 6 turns of 18K to 23K tokens of mixed reading and experiment). It was useful (the closings are shorter) but the semantic could have been settled with one tiny probe.
- Treated a fast-eval estimate as a score: #5/#6/#7 est. 63.2 to 63.4, full 54.8 to 55.1 (fails v4.30.0, `Join.refl.refl` unknown constant); the [arena] state still listed #7 as "leading unverified est. 63.38" at turn 23. Built three candidates on the trick before the failure showed (turns 20 to 22, $0.033).
- Misjudged budget: "I've used maybe 60-70%" at 38% actual (turn 24); first finish at 55% unspent.
- Misread consistent numbers as inconsistent after compaction (memory said $0.0684 left, finish reported $0.0561 after one more request). Harmless.
- Idea attribution: one idea per probe call, so a golf draft sent with the new idea's stub is credited to the new idea (i5 shows "succeeded" with #30).

## 4. Context and compaction

| item | value |
|---|---|
| context at turn 0 | 13.8K tokens (packet 19,958 chars, certified) |
| growth | about 10K tokens per turn, 95% from the model's replayed thinking |
| compaction | 1, reason `threshold`, at turn 50, tokensBefore 503,922 (compact_at 500,000, keep 40,000, window 1M) |
| compaction request | 404,159 input tokens, **cacheRead 0**, 2,728 output, stop `stop`, $0.06226; reserve est. $0.2123 (1.16 MB body) with reason "compaction summary bypasses the budget guard"; settled as `orphan_stream` / `compaction_summary`; ledger reconciled (`balanced: true`) |
| summary | "No prior history" + split-turn checkpoint, 4,783 chars; states #21 as best and 42% remaining (stale: #22 to #30 and $ left are not in it) |
| after compaction | memory message injected 34 s later (1,263 chars: #30, routes, ideas, latest failures, $0.0684 left); the next request carried 65,640 uncached input tokens ($0.0124, cacheRead 5K), then cache rebuilt (71K, 76K, 82K) |
| behaviour after | turn 51 `arena_finish`, turn 52 `arena_probe`: no re-reading, no duplicate drafts; the model worked from the memory message |
| peak context | 503,922 |
| length stops | 0 of 57 (stop reasons: 55 toolUse, 1 connection error on the 2nd request, 1 final stop); request body `max_tokens 64000` on every request (vqm confirmed) |
| failures | none; `session_compact_failed` never fired; one `compaction_repair` (1 null tool call) |

lrx behaved as designed: the bypass fired, nothing was blocked at the $0.5 soft level, the stop reason stayed `finished`. The issue is not correctness, it is price (6.1).

vqm was not stressed: the largest turn (23,114) is below the old 32K cap, and DeepSeek never produced a length stop in this run. The estimate-per-request (gate estimate $0.045 to $0.21) now includes a 64K worst-case output ($0.038); harmless because only the hard cap gates.

## 5. What the MODEL could have done better

1. **Take the heartbeat lever seriously after #2.** 100 HB = 29 tokens. The `obtain` finding (-30 HB) was worth 9 tokens in one probe. The profile showed 116 to 136 self-HB in four split sites and 81 to 85 unattributed; no probe was aimed at reducing split count or goal size, and 4 profiles were requested (turns 16, 24, 34, 45) against 35 probe calls. At the late golf rate ($0.01/pt after #21) an HB experiment worth 20 HB (+0.5 pt) is comparable to 6 tokens.
2. **Do not build on a fast estimate.** Fast eval is explicitly an estimate; wait for the `[arena] passes all 4 versions` line (arrives one turn later) before stacking candidates on a new name. Cost of not doing it: about $0.033 here.
3. **Know the spend.** The model never saw an allowance figure and tried to finish at 55% unspent. Reading `arena_state`/`arena_finish` costs a turn each; a spend line in the footer (6.2) removes the need.
4. **Settle tactic semantics with the smallest probe.** `use` behaviour took six turns (about $0.057, 11% of cap) of long reasoning where a two-line probe would answer it.
5. **Route attempts should be complete or skipped.** Three of five new-idea drafts were 35 to 105 token stubs with 0 goals (see 6.3) that could not score or be credited; the one completed alternative (#16, 784 HB) was already known from the reference to be expensive.
6. **Check goals before writing long drafts.** The first 4 probes failed on operator typing and field counts; one `lean_goal` or a sorry probe with traced goals at the start would have been cheaper than the early 21K to 23K-token thinking turns.

Credit: no duplicate drafts across 54, compat checked before the final choice, stopped exactly at the stop rule, solid unit economics in the golf (it priced every trade in points, e.g. "+0.02 net, marginal").

## 6. What the HARNESS could have done better (sorted by impact per dollar)

### 6.1 Compaction price and policy (about $0.075 = 15% of cap, about 9 turns)
- **Why it cost so much:** the summary request has a different prefix than the agent's own requests, so DeepSeek's automatic cache gave 0 of 404K tokens: $0.0606 input. The next turn is cold again (65.6K uncached, $0.0099 of its $0.0124).
- **Rule of thumb check:** per-turn cache-read at 500K context is $0.0015 (about 20% of an average $0.0079 turn). A compaction saves about $0.0013 per turn afterwards and costs $0.075: break-even is about 57 turns. At the $0.5 cap the compaction fired at 74% of spend with about 10 turns left, so it can never pay back. The models.yaml comment (`models.yaml:55` "~3 uncached requests (~$0.03)") is stale for 500K context; the actual price is 2.5x.
- **Suggestions**
  1. `packages/arena-pi/extensions/arena.ts` (`session_before_compact` handler near line 687; summary request path at lines 456 to 480): skip or defer the threshold compaction when the estimated compaction cost (uncached input at list price, which `compactionPayload` in `budget.ts` already estimates: $0.2123 here) exceeds a fraction of the remaining allowance (for example when remaining allowance < 3x the estimate or spend > 50% of the cap) and the context is still well under the window (504K of 1M). Estimated gain: about $0.075 back, about +1 to +2 pts at the late rate ($0.012 to $0.03 per pt).
  2. Make the summary request cache-friendly: send the agent's own system prompt and message prefix and append the summarization instruction as the last user message (the compaction hook `fromHook` path in Pi), so 95% of 404K is a cache hit (about $0.003 plus output instead of $0.0606). Estimated saving about $0.055 per compaction.
  3. `models.yaml` deepseek `at_tokens`: for a $0.5 cap use a value above where the run ends (say 850K) or scale it with cap; fix the comment.

### 6.2 Spend visibility (about $0.03 of finish turns plus premature wrap-up; low cost to fix)
- No tool result contains spend. The model learned its allowance only by calling `arena_finish` (6 times, $0.030, 4 to 7 s each) and mis-estimated twice.
- Suggestion: add a factual allowance fragment to the `[arena]` footer and to `arena_state`: for example `allowance: $0.2236 of $0.5 spent (45%)`. This is a fact, not a direction. Files: the footer builder in `packages/arena-pi/extensions/arena.ts` (where `[arena] best verified` is assembled) and `arena/campaign.py` state. Expected gain: removes about 4 of the 6 finish turns ($0.02), the model plans its last turns for the 10% window.
- Also have `arena_finish` carry the same facts for the first call (done) but do not make it the only source.

### 6.3 `=> sorry` produces no goals (`arena/engine.py:277`)
- `_SORRY_TACTIC` matches `sorry` only after line start, `·`/`.`, `by` or `<;>`. In `| refl => sorry` (induction/match alternatives, the model's natural stub) it does not match, so `instrument_sorries` never inserts the trace. Evidence: probes ec827c, fb3569, 0934e7, aa6598, adf768, f6ce7f all contain `=> sorry` and all report `goals: []` while 414e80, acfc25, f064a1 (`· sorry`) reported 4, 4, 6 goals.
- Consequences: 5 `lean_goal` calls early; the three route-seeking stubs (i3 `adf768`, i4 `f6ce7f`) have an empty goal-state signature, so `sinceRefusal().newStates` can never count them and the "no goal state new to its route" refusal text applies automatically.
- Fix: add `=>[ \t]*` to the prefix group (and `\bwith\b`-style `|` alternatives are all `=>`); add a test. Cost: a one-line regex. Gain: honest goal-state depth for stubs and fewer wasted calls.

### 6.4 Route credit is unreachable for this row, and the finish message does not say so (about $0.03 of stub turns)
- 53 attempts, similarity to the nearest route 0.56 to 1.00 (complete proofs 0.64 to 0.75, #16 the reference-structure completion 0.91, term-level stubs 1.00); threshold `SAME_ROUTE = 0.5` (`arena/routes.py`, module constants). Every proof of this theorem uses the same constructors and the same three helper lemmas, so the lemma part (weight 0.45) and the recursion part are shared: credit requires a different vocabulary, which this row does not offer.
- Partial rule (`routes.py` `similarity`, containment branch): a stub whose only present part is `recursion` is 100% contained in the exemplar, so a stub of any other shape can join r1 at 1.0. Suggestion: require at least two parts present (or `claims`/`logic`) before an incomplete attempt can match by containment; otherwise stubs inherit the exemplar.
- The refusal text says "Only one route has been tried so far" and the tool description says a repeat confirm needs a credited route or a new goal state, but the `arena_finish` handler in `arena.ts` (`if (!room.allowed)` branch) refuses purely on `finishAllowed` (10% rule); `sinceRefusal` only changes the text. Suggestions: (i) append the measurement, for example "closest route similarity of the last N attempts: 0.69 (opens a route below 0.5)", so the model can judge reach; (ii) state in the tool description that confirmation needs only the 10% rule, or enforce what the text says. Both are factual.
- The refusals were useful for spend (the model quit at 55% and gained +6.4 pts after), so do not drop the 10% rule; trim the route-credit story where the measure cannot move.

### 6.5 Cross-version result delivered one turn late (about $0.017 here)
- `fast` and `full` evaluations of one candidate are 1.1 s apart (ledger: eval ts 24.4 min and 24.4 min +1.3 s). The `[arena]` pass/fail line is appended to the next tool result, one model turn (about 80 s) later, and the first footer says only "being checked" with the estimated proxy. #5/#6/#7 were built on a failing name: turns 20 to 22 $0.033.
- Suggestion: in `arena_probe`/`arena_evaluate`, await the background check for up to 3 s before building the footer (`packages/arena-pi/extensions/arena.ts` footer logic; `arena/campaign.py` background lane) so the result carries verified proxy or the failing version and error. Gain: about $0.015 per incident, and the est./verified confusion disappears.

### 6.6 Idea attribution per call
- `arena_probe` takes one `idea` per call, so a golf draft sharing a call with a new stub is credited to the new idea (i5 shows "succeeded" with #30). Accept `idea` per draft or attribute by candidate parent route. Low cost, improves summaries (`route`/`idea` tables) rather than score.

### 6.7 Null tool arguments
- Turn 12: provider returned `arguments: null` after 4.7K tokens; wasted $0.0084 and about 2 min. Detect null arguments in the stream hook and re-request the same turn once (rather than returning a tool error to the model and letting it re-emit about 1.8K tokens of drafts). `arena.ts` repair path (`compaction_repair` already handles history). Gain about $0.005 per event.

### 6.8 Cost reporting of failed attempts
- The first request failed with `Connection error` (no response), retried successfully; its reserve ($0.0433) was never released (`kind: unknown`, `provider_attempt_without_settled_usage`) and stays in `reserved_usd` for the whole run. `summary.txt` and `campaign.log` therefore report $0.4962 although settled spend was $0.4529. Settled gating ignored it (remaining = $0.0471), but cross-row cost-per-point comparisons are inflated by 9.6%. Suggestion: if no bytes were received on a failed attempt, release the reservation and report $0 unresolved; otherwise report settled and unresolved separately in the campaign table.

### 6.9 Lower-confidence ideas to test, not to ship
- Thinking effort: 59% of cost is output; mean 7.9K tokens per turn at "high". A medium-effort row at the same cap would show whether turns of 5K output give similar per-turn gain (not measured here).
- The early research phase (turns 8 to 15, $0.075 for +3.4 pts) is the least efficient part of the run. A one-line pointer in the packet to tactic semantics is a fact, but only worth adding if it recurs across rows.

## 7. Answers to the three key questions

1. **Why one route.** Structural plus mechanical. Structurally, the row's proofs differ only in layout and closing style; the fingerprint separates by lemma vocabulary and recursion kind, so the nearest-route similarity stayed 0.56 to 1.00 for all 53 attempts (below 0.5 would be a new route). Mechanically, the stubs the model wrote to seek a route were assigned to r1 by containment and returned no goals due to the `=> sorry` regex gap, so even `newStates` could not rise. The finish gate did its spending job (refused 5 times, run continued from $0.22 to $0.45) but was not coupled to route credit in code. 0 credited routes, 1 explored (19 goal states, 36% new-state share).
2. **What capped at 70.** HB: 70% saved after the first candidate and unchanged (the only gains were 30 HB at #11). Tokens: 41% saved; the last 20 tokens came from a layout change worth +1.76 pts; micro-edits then paid 0 to 0.08. The cap ended the run before a plateau: from #21 to #26 the rate was $0.012 per point. Overhead of about $0.19 (compaction $0.075, 6 finish turns $0.030, stub/route turns $0.03, context reads $0.053) is what a 70.3 to about 72 result would have been made from at the observed late rate.
3. **Did the fixes behave.** Yes. Compaction ran once, bypassed the guard, balanced the ledger, ended in `stop`, and the model resumed from the memory message with no re-read. `max_tokens` 64000 was on every request and no length stop occurred (max 23.1K, 36% of the limit). The issue lrx exposed is cost, not correctness (6.1).

## Appendix: file references

- Run: `runs/pi-budget/v6cov-Cslib.SKI.parallelReduction_diamond-deepseek-v4.1-flash-r1/` (`cost-ledger.jsonl` gate/reserve/settle ids 1791547139313 for the compaction, `session/*.jsonl` compaction entry, `trace-journal.jsonl` `compaction_repair`).
- Harness: `packages/arena-pi/extensions/arena.ts` (finish at ~1100 to 1170, compaction at ~456 to 480 and ~687), `packages/arena-pi/extensions/rules.ts` (`finishPush`, `sinceRefusal`), `packages/arena-pi/extensions/budget.ts` (`finishAllowed`, `compactionPayload`), `arena/routes.py` (`SAME_ROUTE`, `similarity`), `arena/engine.py:277` (`_SORRY_TACTIC`), `models.yaml:48-56`.
