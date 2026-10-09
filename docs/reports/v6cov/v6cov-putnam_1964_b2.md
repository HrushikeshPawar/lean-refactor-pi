# v6cov putnam_1964_b2, DeepSeek v4.1 Flash (run r1): how 98.54 was reached

Run: `runs/pi-budget/v6cov-putnam_1964_b2-deepseek-v4.1-flash-r1/`. Code before the mid-campaign fixes. Thinking high, soft cap $0.5, 104 requests, 66.6 min wall, settled $0.5275 (overshoot $0.0275). All dollar figures are settled cost-ledger numbers at list prices; "pre-miss" = excluding the final request.

## TL;DR

- Score came in two layers. The first compiling rewrite (#2, 2.7 min, $0.017) went 33.33 to 89.88 (500 tok / 2480 HB, vs reference 1754 tok / 134499 HB). A long golf chain then added 8.7 points; 98.34 was reached at $0.249, 98.47 at $0.282 (#32, 53% of final spend), 98.54 at $0.414 (#80, 39 tok / 2894 HB).
- The last +0.7 (97.76 at $0.183 to 98.47 at $0.282) came from one discovery at about $0.22: the model measured a search tactic (`grind`) it had written off as "expensive", on the strength of the skill's cost warning. It cut tokens 102 to 53 for +2100 HB, a net gain because 1 token = 0.019 pt and 100 HB = 0.0248 pt (1 token ~ 77 HB). From $0.282 to $0.414 the gain was +0.07; after #80, $0.029 of real spend plus the $0.0845 miss bought nothing.
- Compaction failed 23 times in a row (every turn from request 82, context 503K, to 104): `Arena context bound exceeds the context window` (`budget.ts:271`, already fixed by 7ee3e3c). Context grew to 562,793 tokens. About two thirds of it was the model's own replayed reasoning (1.0M chars of thinking, 366K reasoning tokens, vs 334K chars of tool results).
- The final request had 0 cache read and cost $0.0845 (16% of the run). It also ended the run: remaining allowance was 11.9% ($0.0597) before it, finish was refused 12 times, and the miss pushed settled spend over the 10% line so finish #13 was confirmed. Without it the run would have needed about 2 more turns. Score effect: none.
- Earlier stop: stopping at $0.282 would have cost 0.07 points (at $0.249 it would have cost 0.20; at $0.183, 0.78). Under the harness rule that unspent allowance has no value this is free, but per dollar the tail is poor: $0.16 pre-miss for +0.07.
- Better routing could not have moved the ceiling much: both axes are at 97.8% saved, 1.46 points from 100. The leverage was time-to-discovery: the search-tactic route opened at $0.227 and its best came from a 92-attempt route; the skill's reference on it was only read at 43 min. The library-theorem route (found at 46.7 min, $0.30) was tried 4 times, best 97.7 (99 tok / 1690 HB), and dropped.
- Bookkeeping: 12 refused `arena_finish` turns cost $0.036 pre-miss; the model called finish expecting route credit to unlock it, because the refusal text carries a route-credit clause even when only allowance is the reason. 24 find/profile/state/source/declarations/skill_read turns cost $0.092. Together 29% of pre-miss spend ($0.128 of $0.443).
- Top harness fixes by score per dollar: (1) lower DeepSeek's compaction threshold or stop replaying old reasoning (context-cost and miss exposure); (2) make the finish refusal say plainly that only allowance matters and show remaining allowance in tool results; (3) put grind guidance where the model sees it early, factually; (4) trim failure diagnostics (28 `grind failed` dumps).

## 1. Timeline

Best-so-far by spend (full evaluations from `ledger.jsonl`, spend from `cost-ledger.jsonl` settles; `#` = candidate number):

| min | spend | best | tok / HB | event |
|---|---|---|---|---|
| 2.7 | $0.017 | #2 89.88 | 500 / 2480 | first compile (turn 0 failed: `push_neg` gives `Nonempty` not `≠ ∅`; model read this correctly) |
| 8.3 | $0.055 | #3 92.22 | 382 / 2104 | |
| 11.2 | $0.075 | #5 94.11 | 286 / 1825 | |
| 15.6 | $0.103 | #9 95.89 | 193 / 1777 | |
| 20.1 | $0.126 | #12 96.43 | 166 / 1676 | |
| 28.7 | $0.183 | #19 97.76 | 102 / 1229 | last point of the first, explicit-terms route (HB-lean, token-heavy) |
| 36.8 | $0.227 | #21 98.16 | 53 / 3346 | search tactic replaces the hand-built disjointness argument |
| 39.6 | $0.249 | #25 98.34 | 57 / 2312 | |
| 44.1 | $0.282 | #32 98.47 | 43 / 2872 | |
| 56.6 | $0.377 | #58 98.53 | 37 / 3102 | |
| 62.0 | $0.414 | #80 98.54 | 39 / 2894 | final best, cold verified |

Wall time: 66.6 min, of which model latency 60.4 min (median 25 s, max 213 s per request) and tools 6.2 min (probes 2.3 min, finish 3.2 min including cold verification up to 47 s).

What changed, by effect on the proof:
- #2 to #19: the proof shrank 500 to 102 tokens at nearly flat heartbeats (2480 to 1229) by collapsing helper steps into single terms and rewriting the cardinality step in place. Each step was found in 1-3 turns.
- #21 (turn 38): replacing the hand-built argument with `grind` cost +2117 HB but 49 fewer tokens, net +0.40. Turn 38 quote: "grind closes it but costs +6082 HB" for the first variant (#20, 79 tok / 7311 HB, worse); the variant that let grind see a narrower goal (#21) won. aesop cost 237,408 HB and simp_all failed.
- #21 to #80: single-call grind variants and flag toggles (`-ac`, hint `Finset.mem_compl`) for 1-4 token and 100-500 HB steps. #80 is `grind -ac [Finset.mem_compl]`: 39 tok, 2894 HB, +0.014 over #58.

The model derived the exchange rate itself (turn 66: "need weighted sum 0.05701t + 0.0007435h < 4.59") and used it correctly to reject candidates; this is its strongest behaviour.

Where the best sits: depth 46 of a 48-deep chain. Depth here is mostly an artifact of the default parent being the current candidate; it equals roughly the number of accepted steps on the incumbent, not independent refinements. 67 probes hung off 33 distinct depths; 28 candidates had a parent at depth 40 or more.

## 2. Tool use

| tool | calls | result chars (total) | latency total |
|---|---|---|---|
| arena_probe | 70 (161 drafts: 1/2/3/4 per call = 15/23/28/4) | 210.7K (mean 3.0K) | 139 s (median 1.4 s, max 30.5 s) |
| arena_finish | 13 (12 refused, 1 confirmed) | 16.0K | 194 s |
| arena_find | 8 | 24.9K | 21 s |
| arena_profile | 6 | 44.9K (mean 7.5K) | 9.7 s |
| arena_state | 5 | 4.5K | 0.7 s |
| arena_source | 3 | 10.5K | 2.6 s |
| arena_declarations / arena_skill_read | 1 / 1 | 2.3K / 11.6K | |

- Tool errors: 0. Lean check latency: 156 model-lane checks, p50 0.7 s, p95 1.9 s, no timeouts. Wall time is model-bound.
- Drafts: 161 submitted; 65 failed to compile (40%); 28 of those failures were `grind failed`, 9 unsolved goals; 5 drafts (3%) were cache hits on an identical earlier draft. 89 candidates compiled, each auto-checked in full on both toolchains (89 full + 89 fast evaluations).
- Turn cost by kind: probe turns 70 / $0.3146; finish turns 13 / $0.1205 (of which $0.0845 is the miss); find, profile, state, source, declarations, skill_read turns 24 / $0.0924. Pre-miss bookkeeping-type turns: $0.128 = 29%.
- Cache: 97.0% reuse overall (35.9M read, 1.11M uncached input); every request but the last had cache reads. Cost split: output $0.253 (48%), uncached input $0.167 (32%, of which $0.0845 is the last request), cache read $0.108 (20%).

## 3. Model reasoning

Strategies, by effect:
1. First rewrite (turns 0-2): a long decomposition compiled at 500 tok / 2480 HB, already 98% under reference on heartbeats; the dominant gain (+56.5 of the +65.2 total).
2. Token golf on that route (turns 3-33): merged steps, inlined single-use steps, swapped rewrite chains, 500 to 102 tokens. Steady, 5 turns per ~0.3 point.
3. Turn 35 (34.6 min): after finish refusal 2 and "61% allowance unspent", a 28K-output turn (80K chars of reasoning, the largest of the run) brainstormed new structures, hand-counted tokens, and concluded "Skip". It ended with a skeleton with two `sorry` holes, written to satisfy the gate (turn 36: "This should satisfy the finish gate"). Turn 37 then tried three search tactics, which produced the #21 win. So the refusal pressure was productive here, though indirectly.
4. Turns 40-58: tuning grind (hint lists, toggles, one vs two calls). Worth +0.13 total.
5. Turn 60 (46.7 min, $0.30): `arena_find` on "intersecting" surfaced a library theorem that states the count for maximal families. The model built three compiled variants (#50 97.01: 139 tok / 1429 HB; #55 97.6: 109 / 1334; #56 97.7: 99 / 1690) and returned to the incumbent route at #57. Its grind attempts on the setup parts failed ("grind can't prove ... needs to unfold the definition"; `-splitIte` after a hint list is a syntax error).
6. Turns 76-103: toggle and hint variants on #80, plus two skeleton and one alternative-route probe to feed the finish gate; all worse.

Misreads of feedback:
- Finish: the refusal text says a repeat confirm needs "a credited route opened or an attempt produced a goal state new to its route". The model read that as the unlock and called finish at 28%, 26%, 19%, 15%, 14%, 13%, 12% remaining (turns 67, 75, 78, 85, 88, 94, 97, 99, 101). Quotes: turn 67 "A credited route exists ... So finish might be allowed now! Let me try."; turn 88 "Let me check allowance and continue if needed. Let me call finish." Every call was refused on allowance alone.
- Idea vs route ids: turn 37 "It opened route i5" then "the routes still show r1, r2, r3 only", confusion between idea ids and route ids; cost one turn.
- Hand token counts are off (model's 96 vs measured 102; 38 vs 40) even though `arena_probe` returns exact tokens: turns 35, 66, 71 spent 10-28K output tokens partly on this.
- Claim at turn 77: "having `this` in context breaks grind"; plausible from two failed drafts but untested beyond that.

Output limits: no turn stopped on `length`; max turn output 27,973 tokens (turn 35), nine turns above 10K, turn 0 at 20K ($0.0124 for a draft that failed on a coercion). Output tokens 421K, of which 366.6K were reasoning (87%).

## 4. Context and compaction

- Context grew linearly at about 5.4K tokens per turn: 18K at turn 0, 188K at turn 21, 287K at turn 35, 503K at turn 81, 562,793 at turn 103. Configured trigger: `compact_at_tokens` 500000 (`models.yaml`, DeepSeek entry).
- `events.jsonl`: 24 `compaction_start` events. Requests 82 through 104 each started a threshold compaction and each failed with `Turn prefix summarization failed: Arena context bound exceeds the context window` (23 failures, zero cost, no retry). The 24th (after the run stopped) reports success; the session JSONL has one compaction entry with summary "No prior history ... Turn Context (split turn)", `tokensBefore` 562,955 and zero usage, so no useful summary was written.
- Cause (see `docs/BACKLOG-harness-v7.md` §4a): the summary request went through `boundedPayload` with no prior request, so the guard used bytes + 4096 as the token bound; at about 2.7-2.9 bytes per token that passes 1M at roughly 345K real tokens, before the 500K trigger. Commit 7ee3e3c (`compactionPayload`, `budget.ts:282`, bypass in `arena.ts` near line 464) fixes this.
- Composition of the final 562K context (session JSONL, chars): thinking 1,007,639; tool results 334,340; tool-call arguments 141,365; first user message 40,265. The sum (1.52M chars at about 2.7 chars/token) matches 562K tokens only if reasoning is replayed, so reasoning is about two thirds of context.
- The miss: all 103 earlier requests had cache reads (reads grew with context); request 103 had 0 read of 562,793 input tokens, $0.0845 at $0.15/M. Pre-miss, a mean carried context of about 350K cost $0.0010 per request in cache reads.
- Counterfactual with compaction working at 500K: unclear benefit. A summary of 500K tokens is mostly uncached input (`models.yaml` estimates about 3 uncached requests, about $0.03), versus roughly $0.0015 per later request in cache reads over about 21 requests ($0.03). So at the 500K threshold compaction would roughly break even on cost and mainly reduce miss exposure; it would not have improved the score.

## 5. What the model could have done better

1. Measure the search tactic earlier. It dismissed grind at turn 2 ("grind is expensive") from the skill's general cost rule; its own exchange rate (1 token ~ 77 HB) already showed that a 2000 HB cost for 50 tokens is a win. Opening that route at turn 5 instead of 37 would have moved the 98.3 region from $0.25 to roughly $0.10-0.12, if everything else held.
2. Stop calling `arena_finish` when the remaining allowance, which it knew from earlier refusals, was clearly above 10%: 9 of 12 refusals were predictable. Cost about $0.03.
3. Use the exact token counts returned by `arena_probe` rather than hand-counting in reasoning (turn 35 alone: 28K output tokens, $0.0184).
4. Go deeper on the second route when it appeared (#55: 1334 HB, lowest heartbeat count seen after #19). It tried four drafts and left, with no measurement of where its 109 tokens went. The break-even for that route at 1334 HB is about 46 tokens, which looks out of reach, so this is a lower-value miss than item 1.
5. After about $0.28 the marginal step was 0.001-0.01 points per probe; no more structural probes were attempted besides gate-motivated ones.

## 6. What the harness could have done better (by likely score per dollar)

1. **Make long-run context cheap and safe.** (`models.yaml` DeepSeek `compaction.at_tokens`, `packages/arena-pi/extensions/arena.ts` message replay.) Two options: (a) lower the DeepSeek threshold toward 200-300K so the cache-miss exposure is bounded at about $0.03-0.045 instead of $0.0845, and a compaction costs about $0.02; (b) drop earlier turns' reasoning blocks from the replay if DeepSeek does not need them across tool-call turns (not verified here; check the provider's rule first). Reasoning is two thirds of context, so (b) would cut cache reads from $0.108 to about $0.04 and the miss to about $0.03. Expected effect on score: none directly; effect per dollar: roughly $0.07-0.10 per run of headroom at the $0.5 cap, i.e. 15-20% more search.
2. **Fail loudly when compaction fails repeatedly.** `arena.ts` around lines 431-480: 23 consecutive failures were visible only in `events.jsonl`. Log a cost-ledger event after 2 consecutive failures and surface it in `summary.txt`.
3. **Fix the refusal wording and add a remaining-allowance line.** `rules.ts` `finishPush` (lines 172-200) appends the route-credit clause and "a repeat confirm is refused again unless..." even when allowance is the only reason, and `arena.ts:1101` repeats it in the tool description. State: "Refused: $X (Y%) left; finish becomes possible at $0.05 regardless of routes tried." Also include `remaining_usd` in `arena_state` and probe replies so the model never needs a finish call to learn it. Saves about $0.03-0.04 per run (12 finish turns at about $0.003) and removes a confusing signal. Factual only.
4. **Make grind guidance measured, not directional.** `packages/arena-pi/skills/arena-lean/SKILL.md` line 43 says search tactics "cost far more than explicit terms". Add the measured fact available in `references/grind-tactic.md`: a heartbeat cost versus token cost table at the run's exchange rate (here 1 token ~ 77 HB), and say that the reference exists in the opening packet. Do not recommend any tactic. This targets the time-to-discovery of the main gain (turn 5 vs 37).
5. **Trim failure payloads.** 28 of 65 failed drafts were `grind failed` with multi-KB goal diagnostics (probe results average 3.0K chars, 210.7K in total, about 70K tokens carried to the end). Truncate the `[grind] Goal diagnostics` block in `arena_probe` results to the first error line plus counts; full text stays in `diagnostics/`. At 350K mean carried context this saves about $0.01-0.02 and some uncached input.
6. **Cap the finish-driven tail.** The only gain after $0.282 was 0.07; a quiet rule is acceptable ("no stop before 10% left"), but consider making the 10% threshold relative to the best-so-far change rate (for example, allow finish once 40 consecutive attempts moved the best by under 0.01 points). That is a policy choice, not a code defect; flagged for the owner.
7. **Branch-credit rule** (BACKLOG §4b): in this run it behaved reasonably (4 credited routes, 5 explored, best from the 92-attempt route r4), so no change is argued from b2.
8. **Route-id vs idea-id.** `arena_idea` ids (i1-i6) and route ids (r1-r6) appear in the same tool replies; label them distinctly (for example `idea i5 / route r5`) to avoid the turn-37 confusion. Minor.

## Appendix: numbers

- Scoring: compat axis 33.33 fixed (2/2 versions); tokens 1754 ref, HB 134,499 ref. 1 token = 0.019 pt; 100 HB = 0.0248 pt. #80: tokens 97.78% saved, HB 97.85% saved. Remaining headroom to 100: 1.46 points.
- Finish: 12 refusals (at 76.6%, 61.1%, 56.1%, 34.1%, 28.2%, 26.1%, 20.6%, 18.9%, 15.4%, 13.8%, 12.9%, 11.9% remaining), confirmed at turn 103 after the miss.
- Routes (summary.txt): r1 original, 2 attempts, no score; r2 best 94.11 (18 attempts); r3 98.49 (34); r4 98.54 (92 attempts, 32 goal states); r5 98.24 (9); r6 1 attempt, 1 hole, not credited. Post-best spend $0.1136 over 11 requests, of which $0.0845 is the miss.
- Sources: `summary.txt`, `cost-ledger.jsonl`, `ledger.jsonl`, `events.jsonl`, `trace-journal.jsonl`, `session/*.jsonl`, `proofs/`, `submission.lean`, `runs/analysis/v6cov/campaign.log`, `docs/BACKLOG-harness-v7.md`. Langfuse not used.
