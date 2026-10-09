# v6cov run study: Cslib Fsub `Typing.progress`, DeepSeek V4.1 Flash r1

Run: `runs/pi-budget/v6cov-Cslib.LambdaCalculus.LocallyNameless.Fsu-deepseek-v4.1-flash-r1/`
Theorem `Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress` (reference 408 tokens, 59,830 HB, 3 toolchains).
Result: proxy 72.32 (#16: 332 tok, 1006 HB, cold-verified on all 3 versions), stop `finished`, 49 requests, 61 tool results.
All times are minutes after the first model request (wall 57.8 min; the 2.5 min Lean warm-up before it is excluded).

## TL;DR

- **The cap at 72 is the token axis.** Compat is 100 and heartbeats are 98.3% down (59,830 -> 1,006). Only tokens remain: 332/408 = 18.6% saved. Each token is worth 0.082 pt and the whole HB axis has at most 0.57 pt left. Reaching 75 needs about 299 tokens, 80 needs about 238.
- **Timeline is front-loaded.** The first scored proof came at 12.3 min / $0.071 (63.3). 71.34 came at 21.7 min / $0.141. The remaining $0.32 and 36 min bought +0.98. The last $0.2 bought +0.65 (about $0.31 per point).
- **Compaction ended the run and wasted about $0.07.** One threshold compaction at 508,615 tokens cost $0.0618 and the cold turn after it $0.0103. That is 14.5% of the cap. It pushed the remaining allowance from 22.9% to 8.3%, which opened the finish gate. Cached turns cost about $0.0058, so about 18 more turns were affordable. The other two non-putnam v6cov rows show the same shape ($0.0623 and $0.0553).
- **One unexplained full cache miss cost $0.0557 (12% of spend).** Request 29 sent 371,652 uncached tokens after a 36K-output turn. The prefix was byte-identical to the previous request for 98.8% of the wire body, and the gap was 1 s. `cacheAlarm` cannot see this case, so the alarms line reads 0.
- **The 3 tool errors were all `lean_goal` "Line N out of range (file has 97 lines)".** The model used line numbers from the 158-line original. They cost one turn ($0.0018) and nothing else. The Lean side is cheap: the p50 check is 0.28 s, 58 checks, 0 timeouts, and the 36 background checks on v4.32/v4.31 took about 0.25 s each.
- **vqm and lrx behaved.** The wire shows `max_tokens: 64000`. The largest turn was 36,213 output tokens (234 s), which would have been a `length` stop under the old 32K limit. There were 0 length stops and 8 turns of 16K or more. The compaction was settled as an orphan stream with the reason "compaction summary bypasses the budget guard". It was never needed to rescue a blocked request.
- **The big unexplored lever failed, not for lack of trying.** Short drafts of 25-45 tokens closed only 2 of 10 cases and cost 6.8k-25.8k HB. The model spent about $0.02 (excluding the cache miss) finding that out, and it was right to. If such a draft had worked, the proxy would be about 85-93.
- **Cost accounting overstates this run.** The headline $0.5099 includes a $0.0517 pre-flight reservation for one aborted stream that was never settled. Settled spend is $0.4583.

## 1. Timeline

Spend is cumulative settled USD. Proxy is recomputed from tokens and HB: `(100*(408-tok)/408 + 100*(59830-HB)/59830 + 100)/3`. Best-so-far steps only; all passed 3/3 versions.

| t (min) | spend | best | what changed |
|---|---|---|---|
| 0-12 | $0.071 | none (baseline 33.33) | 12 turns reading sources, lean_goal on skeleton goals, 3 probes. First scored proof at 12.3 min. |
| 12.3 | $0.071 | #2: 443 tok / 977 HB = 63.26 | HB from 59,830 to 977. Tokens went above the reference (+35). |
| 14.9 | $0.090 | #4: 385 / 991 = 67.99 | -58 tokens in one probe |
| 18.4 | $0.117 | #7: 358 / 994 = 70.20 | |
| 21.7 | $0.141 | #8: 344 / 1001 = 71.34 | 98.6% of the final score at 28% of the spend |
| 27.8 | $0.186 | #10: 340 / 1001 = 71.66 | |
| 30.4 | $0.204 | refusal 1 (59% unspent) | |
| 35.6 | $0.236 | #12: 339 / 1002 = 71.75 | the 36K-output turn bought 1 token |
| 36.9-43 | $0.296-0.328 | none | grind-heavy detour plus the cache miss |
| 47.2 | $0.345 | #14: 334 / 973 = 72.17 | |
| 52.5-53.4 | $0.365-0.370 | #15 332/1012 = 72.31, #16 332/1006 = 72.32 | final best |
| 53.4 | $0.370 | #17: 335 / 669 = 72.26 | -337 HB for +3 tokens, a wash (+0.19 from HB, -0.25 from tokens) |
| 57.3 | $0.385 | #18 ties #16 (332/1006); #19 338 is worse | |
| 57.8 | $0.447 | compaction | $0.0618 |
| 58.0 | $0.458 | `arena_finish` confirmed | 8.3% left |

Post-best spend is $0.088 over 4 requests. Of that, 83% is the compaction and the cold turn after it. Refusal checkpoints (remaining fraction): 59% at 30.4 min, 29% at 49.3 min (best 72.17), 25% at 54.2 min (best 72.32). Spend after refusal 1 was $0.255, for +0.66.

Cost by token type: output $0.2447 (53%, 404K tokens), uncached input $0.1776 (39%), cache read $0.0359 (8%). The three cache-cold requests (miss, compaction, post-compaction) hold $0.1155 of the input cost, about 25% of the whole run. By the harness category split: compile 31 turns $0.3287, context 11 turns $0.0402, bookkeeping 4 turns $0.0229, compaction $0.0618, rejected 1 turn $0.0046.

## 2. Tool use

| tool | calls | errors | latency |
|---|---|---|---|
| arena_probe | 29 calls, 58 drafts | 0 | p50 0.7 s, max 5.5 s |
| lean_goal | 12 | 3 | 0.1 s |
| arena_source | 10 | 0 | 0.1 s |
| arena_finish | 4 | 0 | p50 25.6 s (78 s total, waiting on cold verification) |
| arena_profile | 2 | 0 | 1.2 s |
| arena_find | 1 | 0 | 5.5 s (27 KB result) |
| arena_state / arena_candidate / lean_diagnostic_messages | 1 each | 0 | |

`arena_evaluate`, `lean_multi_attempt` and `arena_declarations` were never used. Wall time is about 92% model generation (about 128 output tok/s) and about 4% tool latency.

**The 3 tool errors.** Turn at 10:26 UTC called `lean_goal` at lines 91, 93, 99, 103 and 105. The candidate file was probe p2, which spans lines 76-97. Lines 99, 103 and 105 returned "Line N out of range (file has 97 lines)". The model re-issued the five valid lines on the next turn. These were guesses at line numbers taken from the original layout; the probe result had `start_line`/`end_line` (76-97). There were no other tool errors. One request-level error is separate: the stream ended without a finish reason (section 4).

**Drafts.** 58 drafts: 18 compiled (31%), 3 sorry-skeletons, 37 failed. First-error classes of the failures:

| class | count |
|---|---|
| unsolved goals | 11 |
| application type mismatch | 9 |
| invalid field | 4 |
| grind failed | 3 |
| invalid grind theorem (bad lemma list) | 2 |
| could not synthesize placeholder | 2 |
| invalid | 2 |
| function expected / type mismatch / unknown identifier / constructor arity | 4 |

All 18 compiled candidates passed all 3 versions, so the compat axis never constrained anything. No duplicate probes: the harness returned `cached:false` throughout.

**Multi-toolchain cost.**
- *Check latency:* warm checks on all 3 versions took about 0.25 s each. The only slow ones were the first v4.31/v4.32 checks (7.7 s and 10.8 s, cold workers). The 36 background checks added nothing visible to the model beyond one-line `[arena]` notes.
- *Startup:* the health gate took 152 s wall before the first request (47.7 s for 3 v4.33 workers, 16.3 s for v4.32, 18.3 s for v4.31). Two of the three servers were closed for idle at 600 s (15:58 and 15:59 local) and restarted at 16:01-16:02 (header open 9.6 s and 6.5 s). No timeouts, `cold_path` 0, `warm_kept` 0.
- *Cold verification:* the three cold verifications agreed with recorded heartbeats (1001/1001, 973/974, 1006/1006).
- *Verdict:* multi-toolchain checking was not a cost driver here.

**Cache reuse.** 93.8% overall (11.97M cache-read tokens), 98.1% over the last ten requests. The all-in figure is dragged down by the two cold requests below.

**Bookkeeping.** `arena_state` and `arena_candidate` were used once each. The three refused `arena_finish` calls each triggered a re-planning turn ($0.0048-0.0081) which mostly led to one more probe round; none changed the best score except #14-#16 later.

## 3. Model reasoning

**Strategy 1, explicit step terms (idea i1, 48 attempts, produced every best).** The reference proof leaves the step cases to a search tactic (the profile said the last case holds 51% of the 59,830 HB). The model replaced each step case with an explicit witness plus a constructor application, and got well-formedness facts from projections of the typing hypothesis. First scored result: HB 977 (-98.4%) but 443 tokens (+8.6% over the reference). Quote, first thinking: "The key insight: the reference proof does `generalize eq : [] = Γ at der` then induction ... the `case case` block costs 51% of heartbeats".

**Strategy 2, token golf from 443 to 332 (-111 tokens, +9 proxy points).** The effects, in order of size:
- Dropping a hypothesis the original carried made every inductive hypothesis take one fewer argument (#4, -58 tokens).
- Pattern lists that match as a suffix let trailing binders become `_` or vanish (model: "Key insight: patterns match as a suffix").
- Obtaining the well-formedness facts from a projection chain instead of the search tactic (10-20 HB instead of thousands).
- Combinator forms for the two injection cases (23 tokens each).
- Destructuring and case-inversion fusion in the last case.

Model's own per-line profile at #12 (339 tok): the injection cases 23 each, the last case 15+12+12, the application case 11+12+12+8+9+9. My re-count of the submission, by case block (approximate, within about 15%, because the harness's counter treats subscript letters differently): application 54, last case 67, let 41, type-application 37, abstraction/type-abstraction 14 each, two search-closed cases 3 each. About 43% of the tokens sit in two blocks.

**Failed or neutral attempts, with reasons.**
- *No generalisation of the context equation (i2):* the induction tactic refused ("Index in target's type is not a variable"). The model had written this down in its own notes before and still spent a turn on it.
- *Dot-notation on constructors (p31-p39, 4 "Invalid field" errors):* these are constructors, not projections. The model recorded this in its notes and then tried `let_body` as a field once more at p38.
- *Syntax variants (`set ... at der with eq`, flat comma patterns, `Exists.imp`, `use _`):* all failed on syntax, placeholders or elaboration. The `set` variant is the only draft that opened route r2 (see section 7).
- *Search-tactic-everywhere family (i3, 6 attempts):* p22 had 42 tokens and p24 had 25 tokens, but both did not compile (6,834 and 22,105 HB consumed). Per case, the search tactic closed only 2 of 10 goals. Adding lemma lists cut the failed run's HB (22.1k to 6.8k) but still left 8 cases open. This is the single result that could have moved the score a lot, and the model examined it properly (turns 78-86).
- *Auxiliary-statement family (i4):* p36 had 45 tokens and did not compile.

**Misreads of tool feedback.** One. The failed probe p22 returned `ok:true, tokens:42, heartbeat:6834, scored:false`. The model wrote "Very promising: a grind-based route could be far shorter" and computed a hypothetical proxy of 92.7. The next turn read the diagnostics ("the hb 6834 was for a failing attempt") and corrected itself. Net cost of the misread about $0.02, since the model was already looking at that family.

**Output-limit cutoffs.** None. Output per turn: median 6.1K, 8 turns >= 16K (181.6K tokens, 45% of all output, $0.109), max 36,213 (the #12 turn: 100K characters of thinking for a 1-token gain, $0.0243). The one transport error was a stream that "ended without finish_reason" 13K characters into a thinking block at 2.0 min. Pi retried after 2 s and it succeeded; the partial reasoning was discarded (`context_edit` replacement null) and the model re-derived it (7,653 output tokens on the retry).

## 4. Context and compaction

- **Peak context:** 508,615 tokens at compaction (last real request 500,229). Context grew about 10.5K tokens per turn.
- **Compactions:** exactly one, reason `threshold`, success. Settings come from `models.yaml` (DeepSeek `at_tokens: 500000`, `keep_recent_tokens: 40000`).
- **What the summary looked like:** 7,351 characters, headed "No prior history. Turn Context (split turn)". The whole run is a single user turn, so Pi cut inside it and wrote one turn-prefix summary. It was good: it kept the best proof text, failed experiments with reasons, and budget status.
- **Cost:** request 47 had 397,087 uncached input tokens and 3,800 output, $0.0618, because the summary prompt does not share the cached prefix. The next request had 68,692 uncached input, $0.0103. Total $0.0721.
- **lrx bypass:** the ledger reserved $0.2162 with reason "compaction summary bypasses the budget guard" and `gate_decision: bypass_compaction`. It settled as an `orphan_stream` / `compaction_summary`. The memory message was injected 79 ms later (1,341 characters, correct best, route and allowance data, "Allowance: $0.4472 of $0.5 spent, $0.0528 left"). The path worked, but at that moment the soft allowance ($0.1146) would have covered the real cost anyway, so the bypass was not stress-tested here.
- **After compaction:** the model's only action was `arena_finish`, which confirmed immediately (8.3% left). Its thinking: "Budget: hmm, let me check ... Let me call finish to see the remaining budget." Before the compaction the remaining fraction was 22.9% and finish would have been refused again.
- **Length stops:** 0. The wire request had `max_tokens: 64000` (vqm). The 36,213-token turn exceeds the previous 32K enforced limit and the 8 turns of 16K or more would all have been cut at 16K.
- **Cache-miss event (request 29):** after the 36K turn, the next request (371,652 input tokens, 0 cache read) cost $0.0600 versus about $0.0067 expected, a net loss of about $0.0545 (11.9% of the settled spend). The trace delta shows the prefix matched the previous request for 989,430 of 1,001,839 bytes, and the gap between the two requests was 1 s, so it is not a TTL expiry. The next request again read 378,496 cached tokens. A second event of this kind exists in another v6cov row (putnam_1964_b2, request 104, $0.0845), so it is rare (2 in 7 runs) but costly.

## 5. What the MODEL could have done better

1. **Fewer, bigger probes.** 58 drafts in 29 calls is 2.0 drafts per call; the tool takes 4. Each turn averaged $0.0081, mostly output. In the golf phase every turn re-derived the same unchanged blocks.
2. **Cap the length of a single turn.** The 36,213-token turn and the 8 turns of 16K or more held 24% of total spend. Only one of those turns produced a best-so-far (#2 at 22K, #4 at 25K, #12 at 36K).
3. **Avoid repeating known failures.** The constructor dot-notation failure was re-tried after it was recorded; the "no generalisation" experiment was re-tried despite the known error; 3 `lean_goal` calls used lines outside the 97-line candidate.
4. **Use the profile earlier.** The first `arena_profile` came at 23.7 min. The per-line token list was available from the first compiled candidate, and 43% of the tokens sat in two blocks.
5. **Use marginal exchange rates.** The packet states 1 token = 0.082 pt and 100 HB = 0.056 pt. The model used them in the right way for #17 (-337 HB for +3 tokens) and rejected it, which was correct (72.26 < 72.32).
6. **Time to first score.** The first scored proof came after 12 min and $0.071, mostly reading; 5.7 min and $0.031 passed before the first probe. The packet already held the reference and the statement.

## 6. What the HARNESS could have done better (by expected score per dollar)

1. **Make compaction budget-aware at the $0.5 cap** (`models.yaml` DeepSeek `compaction.at_tokens`; `tools/run_pi_budgeted.py:362-366` sets Pi's `reserveTokens = window - at_tokens`; hook `session_before_compact` in `packages/arena-pi/extensions/arena.ts:687`).
   - *Evidence:* compaction plus the cold turn cost $0.0721 (14.5% of the cap, 63% of the remaining $0.115). It also moved the run across the 10% finish line. `models.yaml` still says a compaction costs about $0.03; at 500K it is $0.06-0.07 (also $0.0623 in SKI and $0.0553 in FieldSpecification).
   - *Reasoning:* the DeepSeek window is 1M tokens and context grows about 10K per turn. A $0.5 run at $0.0058 per cached turn cannot pass about 600K, so compaction never pays at this cap.
   - *Change:* either derive `at_tokens` from the soft cap (for example, window x 0.9 when the soft cap is at most $1), or have `session_before_compact` skip the compaction when `soft_remaining < 3 * contextTokens * price.input`. I did not verify whether Pi's hook can cancel; if not, raising `reserveTokens` handles it.
   - *Impact:* about $0.07-0.11 per row at roughly $0.3 per point, so about +0.2-0.4 pt. Small in absolute terms but present in every long run.
2. **Make the finish gate independent of non-model spend.** The 10% rule opened because of a compaction, not because the model had exhausted its routes. Count compaction and cold-turn cost against a separate line, or apply the 10% test to the spend before the compaction request. Mechanism lives in `packages/arena-pi/extensions/rules.ts` (finish rule) and `budget.ts` (`finishAllowed`). Same impact as item 1 and not independent of it.
3. **Add a cache-miss alarm** (`packages/arena-pi/extensions/budget.ts:201` `cacheAlarm`): it only fires on `write > read`, and DeepSeek reports 0 writes, so the 371K-token miss registered nothing ("alarms 0"). Fire on `cacheRead == 0 && prior request cached > 100K tokens` and log gap seconds, previous output tokens, and the shared-prefix bytes from the trace delta. This will not recover the dollars but makes the next miss attributable (2 events so far, $0.056 and $0.085).
4. **Settle aborted streams from what was seen** (`packages/arena-pi/extensions/arena.ts:652-664`, `arena/summary.py:139-165`). The stream that ended without a finish reason left a $0.0517 pre-flight estimate as `unresolved` for the rest of the run. It is added to the headline cost (`$0.5099` versus $0.4583 settled), to `all_call_cost_usd` (`tools/run_campaign.py:171`) and to the hard-cap gate. Estimate the real charge from the observed prompt size and streamed characters (about $0.005 here) and write a `settle` with `usage_known:false`. Campaign comparisons are skewed by up to 10% per retried row otherwise.
5. **Probe output for non-compiling drafts** (`arena/engine.py` probe result; `arena/context.py:639`). The result has `ok:true`, `tokens:25`, `heartbeat:22105`, and `metrics.compiled:false` for a draft that did not compile. Report `compiled:false` at the top level, rename the heartbeat count to `heartbeat_to_failure`, and drop `ok:true` from failing drafts. This is factual, not directional, and removes the one misread seen here.
6. **Route credit from errored drafts** (`arena/routes.py`). Route `r2` was opened by a draft with a syntax error (`errored:true`). The kernel fingerprint was an empty one, which the label printed as "no induction · -27" and the finish review listed as "r2 (not credited) · 1 attempt". Skip fingerprinting for drafts whose first error is a parse error, so route tallies and refusal text do not contain phantom routes.
7. **`lean_goal` line guard** (`packages/arena-pi/extensions/arena.ts:840`). The "out of range" error could add the candidate's proof span ("proof lines 76-97") as a fact. Saves about one turn per occurrence ($0.002-0.005).
8. **Finish refusal wording** (`packages/arena-pi/extensions/rules.ts:191-195`). It already carries per-axis headroom, which is useful. A numeric line would help more than the sentence "a micro-golf of the current proof will not close it": for example "points left: tokens 81.4/3, heartbeats 1.7/3; one token = 0.082 pt". The model re-derived this on its own at turn 74.

## 7. Facts the next study can reuse

- Run state: `ledger.jsonl` has 40 probes, 36 evaluations (18 distinct candidates), 59 route events, 4 ideas. Routes: r1 (original's route) 57 attempts, 26 goal states, best 72.32; r2 1 attempt (errored), 0 credited routes.
- The summary line "47% of attempts produced a goal state new to its route" is consistent with the ledger (26 states / 57 attempts is 46%).
- Wall-clock (first request to finish) is 57.8 min; the campaign ran this row in parallel with the Electromagnetism/FieldSpecification rows on 4 shared Lean slots (`lean-session.log`: "share 4 (2 live sessions)").
- Hypothetical ceilings from the packet (not achieved): 42 tokens at 6.8k HB would be 92.7; 25 tokens at 22k HB would be 85.7. Neither compiled. The only compiled proofs sit at 332-477 tokens.
