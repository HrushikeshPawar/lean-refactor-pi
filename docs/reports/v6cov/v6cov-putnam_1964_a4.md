# v6cov run study: putnam_1964_a4, DeepSeek V4.1 Flash, r1 ($0.5 soft cap, thinking high)

Run dir: `runs/pi-budget/v6cov-putnam_1964_a4-deepseek-v4.1-flash-r1/`. Code is from before the mid-campaign fixes (compaction bypass `7ee3e3c`, 64K output `a0354f1`). Sources: summary.txt/json, cost-ledger.jsonl, ledger.jsonl, events.jsonl, the Pi session JSONL (thinking text and tool calls), proofs/, submission.lean, campaign.log. Turn numbers below are 0-based model requests (106 settled requests); minutes are session wall clock. Langfuse not used.

## TL;DR

- **The score was done at $0.14 (31% of spend, 24 min).** #19 (312 tok, 6514 HB, proxy 92.17) was verified on all 3 toolchains before the first `arena_finish`. The next 82 requests (69% of spend, $0.316, 40 min) added +0.00; the best 34 later candidates only tied it once (#26, 92.17, 313 tok) and never beat 312 tokens. Stopping at the first finish request would have saved $0.307 at identical score (420 pts/$ at the best, 129 pts/$ at the end).
- **The finish gate is a pure spend-down, and the model learned that.** `arena.ts:1131` refuses whenever more than 10% is left, whatever the routes did. In all of the last 12 refusals (14-25) "credited routes opened" was greater than 0 and the gate still refused. The refusal text and the tool description (`arena.ts:1101`, `rules.ts:196`) say a credited route unlocks the next confirm; that is untrue. The model only worked it out at turn 77 ("the route stuff is informational"), after about 50 turns of chasing credit.
- **Route-credit gaming, quantified.** 332 of 413 drafts (80%) were `sorry` skeletons; 314 (76%) were the same two-line shape `obtain ⟨B,T,hB⟩ := boundedu; have h := hB <numeral>; sorry` with only the numeral changed (hB 20 .. hB 1003). They produced 312 of the 314 credited route events in the final ledger (the 2 others are the compiled routes r2 and r3). Only the numeral differs in the claim hash (`arena/lean/route.lean`) and in the goal-state signature (`arena/goalstate.py` does not normalise literals), so each draft counted as a new route and a new goal state.
- **Cost of the gaming.** The skeleton phase (turns 74-105, 54-64 min) cost $0.109 (24% of the run). Almost none of it is Lean: probe turns were $0.003 each (context re-read plus 1.3K output) and each finish turn $0.0047 (18K uncached tokens of echoed skeleton goal states). The model believed sorry drafts cost "$0.0003 each" and that big Lean proofs drain faster; spend is per model request.
- **Compaction never ran.** The 500K trigger fired at turn 84 (57.4 min) and failed at every one of the following 24 requests ("Arena context bound exceeds the context window", the bug fixed in `7ee3e3c`). Context peaked at 696K tokens (57% of it past thinking). The one "success" came after `stop`, with an empty summary. Hindsight value is small here ($0.035 cache-read in turns 84-105, about the cost of one summary).
- **Candidate graph chain is a labelling artefact.** The harness sets the default parent to the newest compiled candidate, not the best (`current` events 1..53 in order). So all 34 candidates after the best (#19, depth 11) descend from it, including three structurally unrelated ones (#22, #24 and #20), and 292 skeleton probes hang off #53 (89.26, the worst late candidate). Any "branch from a shallow node" credit (backlog 4b) built on declared parents would measure compile order, not diversity.
- **Route extraction lags and is wasted on skeletons.** Every draft, including 332 trivial skeletons, is queued for a cold Lean extraction (`arena/campaign.py:_record_route_later`). Lag from probe to route event: median 79 s, p90 975 s, max 1246 s. At refusal 25 only 195 of 327 probes were classified; 149 route events landed after the run ended (ledger touched at 15:02, run ended 14:41). So summary.txt reports 169 routes while the ledger now holds 316; the "311 skeletons" figure in the backlog counts post-run events.
- **Unexplored real lever.** #22 had 3282 HB (best HB seen) at 497 tokens. At the packet rates (1 token = 0.019 pt, 100 HB = 0.030 pt) any candidate with 3282 HB beats #19 if it has at most 361 tokens. The model gave that direction 2 turns ($0.015) before switching to gate-chasing, and never profiled #18/#19, where one `simp` held 54% of the HB.

## 1. Timeline

Spend is cumulative settled USD at the evaluation time (cost-ledger); proxy is the local proxy of the best-so-far.

| event | wall | spend | proxy (tok / HB) |
|---|---|---|---|
| first compile (#2) | 6.6 min | $0.028 | 84.72 (725 / 5417) |
| 88.74 (#6) | 9.7 | $0.048 | 490 / 6791 |
| 90.51 (#8) | 13.5 | $0.073 | 400 / 6541 |
| 91.31 (#11) | 14.7 | $0.081 | 362 / 6258 |
| 92.03 (#17) | 19.3 | $0.111 | 321 / 6419 |
| 92.14 (#18) | 21.8 | $0.128 | 315 / 6418 |
| **92.17 (#19), best** | **23.8** | **$0.140** | 312 / 6514 (cold-verified 6515) |
| first `arena_finish` (refused, 70% left) | 24.4 | $0.149 | |
| first `sorry` skeleton credited (r4) | about 49 | about $0.31 | |
| numeral skeleton spam starts (turn 74) | 54.1 | $0.347 | |
| `finish` accepted at 8.8% left | 64.1 | $0.456 | 92.17 |

Phase split of the 106 requests:

| phase | turns | spend | share | what happened |
|---|---|---|---|---|
| build to best | 0-23 | $0.144 | 32% | lemma found at turn 1 via `arena_find`, 18 compiled candidates by 24 min |
| post-best, real attempts | 24-73 | $0.203 | 44% | refusals 1-13, 37 of the 49 turns have gate vocabulary in their reasoning (route, credited, finish, refuse, drain), $0.153 |
| numeral-skeleton spend-down | 74-105 | $0.109 | 24% | 12 refusals in 9 min, 8 calls x 4 drafts per turn from turn 90 |

Post-best candidates (#20..#53, 34 total): best proxy 92.17 (#26, 313 tok, 6466 HB: tie), then 92.14 x3, 92.13, 92.08, 92.05; the median is 91.7. The 52 model candidates also include 3 distinct "route" variants whose scores were 90.76 (#20, 380 tok), 89.66 (#22, 497 tok / 3282 HB) and 87.42 (#24, 579 tok).

What each improvement changed (by effect): the first compile (#2) took the reference from 1769 tok / 111476 HB to 725 / 5417, i.e. tokens -59%, heartbeats -95% (33.33 to 84.72, +51 of the final +58.8 points). Everything after is token golf at flat HB: 725 to 312 tokens (+7.4 points), while HB went up from 5417 to 6514 (-0.3 points). Steps, by what got shorter: dropping type annotations, shorter hypotheses and a single `simp` (#3-#7, 725 to 453 tok); an `Icc`-product finiteness proof that matches the bounds directly (#8, -53 tok); an injectivity lemma in place of a longer coercion block and inlined helper steps (#9-#11, -38 tok); merging the one-step lemma into the induction (#17, -20 tok, +185 HB); smaller terminal rewrites (#18/#19, -3 tok each).

## 2. Tool use

| tool | calls | notes |
|---|---|---|
| arena_probe | 148 (413 drafts: 52 compiled candidates + 2 cached, 27 failed, 332 sorry skeletons) | 20 single `proof`, 91 `drafts`+idea, 37 `drafts`; median 2.8 s per call (1.3 s with 1 draft, 5.4 s with 4+), 551 s total |
| arena_finish | 26 (25 refusals, 1 accept) | 25 finish-issuing turns cost $0.078; the 56 s max is the cold verification at the accept |
| arena_find | 8 | median 3.6 s; 3 of the first 5 queries `not_found` |
| arena_profile | 4 | turns 4, 7, 13, 37 (#2, #6, #15, #22); never on #18/#19 |
| arena_idea / source / declarations / state / lean_local_search | 5 / 2 / 2 / 2 / 2 | 0 tool errors in total |

- Lean latency: 411 model-lane checks, p50 0.75 s, p95 1.81 s, 0 timeouts, 0 cold path; fast eval median 1.2 s, max 3.1 s. Tool execution is about 11 of 64 minutes (about 17%, parallel calls overlap); the rest is model generation (mean 36 s per request).
- Cache: 98.2% reuse (37.9M cache-read tokens against 0.69M uncached), savings 96.3%. No cache write cost. Cost split: output $0.239 (52%), uncached input $0.103 (23%), cache read $0.114 (25%).
- Wasted/repeated: 2 cached duplicate drafts (0.5%); 314 numeral-only skeleton drafts; 25 finish calls; the Fin-4 route (turns 25-34, about $0.04, 8 failed probes then #20 worse by 1.4 points); first-failure classes of the 27 real failed probes: 8 application type mismatch, 7 unsolved goals, 3 "made no progress", 2 rewrite pattern not found, 2 type mismatch, 5 other.
- Bookkeeping overhead: summary's `bookkeeping 29 x $0.0908` plus `rejected` = 19.9% is the finish cycles; it understates the gaming cost because the skeleton probe turns are filed under "compile" ($0.343 for 70 requests includes the $0.109 of skeleton turns).
- Result bloat: arena_probe results average 3.7K chars (551K chars total, 78% of all tool-result bytes); each skeleton draft result is about 1.25K chars (the same `hu`/`hB` hypotheses echoed every time), so a 32-draft turn adds about 18K uncached tokens ($0.0027).

## 3. Model reasoning

Thinking is 893K characters (81% of the 399K output tokens are reasoning); visible text is 6.4K characters. No turn hit a length stop (all 105 tool turns `toolUse`, 1 plain `stop`). Largest outputs: turn 2 at 24.3K tokens (first plan, 3 min latency, $0.0156) and turn 5 at 16.8K; the median is 3.2K. Only 2 turns exceed 16K, none near the 64K limit.

**Strategy, by effect on the proof**
1. *Find a pigeonhole helper (turns 0-4).* Searched for a lemma that gives two indices with equal 4-tuples from a finite range; found it in turn 1 ("Found `Set.Finite.exists_lt_map_eq_of_forall_mem`") and built the first compile (#2) in 6 minutes: one structural rewrite removed 1044 tokens and 106K HB. This is where 87% of the gain came from.
2. *Golf at flat heartbeats (turns 5-23).* Each turn proposes 2-3 variants for the largest profile lines and keeps what compiles: fewer tokens at about 6.2-6.9K HB. Failures were precise and cheap (the model read the nesting of the tuple from the error text and fixed it in one turn, turn 3). One misread: it blamed full `simp` vs `simp only` in turn 33 for a flat-conjunction mismatch; the cause was the changed goal shape.
3. *Merge a helper into the induction (turn 14-17).* #16 (341 tok) to #17 (321 tok) needed an index-alignment `show`; two drafts failed because Nat subtraction in the recurrence indices does not normalise with `rw`/`simp only` (turn 17: "the full `simp` is what handles the Nat subtraction"). Correct reading.
4. *Fin-4 function route (turns 25-34).* Estimated -26 tok; measured +68 tok (380 vs 312). Five turns lost to a named-argument `?m.180` metavariable that it first attributed to the wrong place (turns 28-30).
5. *Shift-map route (turns 35-39).* #22: 497 tok, 3282 HB, proxy 89.66. The model noticed "the shift route has very low heartbeats" and drafted a hybrid, #23 (462 tok, 5282 HB). It dropped the thread after one more draft because the finish gate was pending.
6. *Gate chasing (turns 25-73, intermixed).* Strong-induction, `Nat.le_induction`, `Function.iterate`, left-nested tuples, `sorry` skeletons "at an exotic goal" to get a new route: all landed on r1/r2/r3. Model's reading (turn 48): "the fingerprint must be very coarse". Measured: r2/r3 labels are "recursion: Nat.rec instead of strong_induction_on +NatInt... -Classical.propDecidable..." i.e. the recursion principle and the lemma set (including `Lean.Omega.*` proof-term lemmas) decide the route, so structurally different proofs that all use `Nat.rec` share a route, while a numeral changes a claim hash.
7. *Spend-down (turns 74-105).* From turn 57 it says "let me just burn budget efficiently"; turn 77: "the finish condition is essentially: keep working until <=10%. The route stuff is informational." It then planned drafts to drain faster: "To drain $0.09 -> about 300 probes" (wrong cost model), a `decide` on `(List.range 30000).sum` to burn Lean time (errored with max recursion, so no cost either way), dummy `have` insertions into #19 to force recompilation, and finally 8 calls x 4 drafts of `have h := hB k; sorry`.

**Misreads of tool feedback**
- Believed a credited route would unlock `finish` (turns 40-76); the ledger says refusals 15-25 each had 4-34 new credited routes and were refused.
- Believed Lean elaboration is billed (turns 59, 79-80, 88-90). Billing is per model request. Sorry-draft turns cost $0.003, large-proof turns $0.004-0.005; the dominant per-turn cost late was the 600K-token context re-read ($0.0018) and the echoed goal states.
- Took a route-classification delay as a rule: turn 63 "r4 opened ... but the finish still refused ... the harness computes the route list AFTER deciding". In fact 40% of the late probes had not been classified when it called finish (section 6).
- Never set parents (except twice), so lineage is the compile order.

**Stop attempts.** Turn 24 (first finish, correct); turn 89 wrote a final summary at $0.106 left ("I've exhausted productive avenues"); the harness injected a continuation ("Do not stop: $0.1062 ... unspent allowance has no value"), which turned the stop into 16 more turns of spam.

## 4. Context and compaction

- Context (input + cache read of each request): 17K at start, 228K at the best (turn 24), 364K at turn 50, 464K at turn 73, 502K at turn 83, 696K at turn 105. Output re-sent as history: 399K of the final 696K tokens.
- `compact_at_tokens` 500000, keep 40000. First `compaction_start` (reason threshold) at turn 84; 24 consecutive "Auto-compaction failed: Turn prefix summarization failed: Arena context bound exceeds the context window" (turns 84-106), no spend. The 25th, after `finish` was confirmed (turn 107), succeeded: tokensBefore 696125, estimatedTokensAfter 42701, summary text empty except the "Turn Context (split turn)" header; usage zeros. It changed nothing for the run.
- Cost of no compaction: cache-read $0.038 in turns 84-105 against about $0.004 at a 43K context, minus a summary of about $0.02: net about $0.015. Small here because the run ended soon after; at the real cap with a run that keeps golfing, a context of 700K costs $0.0021 per request in cache reads alone, which is 55% more than a good golf turn's output cost ($0.0035 at 3K tokens).
- Length stops: none (stopReason `length` 0).

## 5. What the model could have done better

1. At the first refusal (70% left, $0.149) the next work was not score-seeking: 37 of 49 turns (turns 25-73, $0.153) are dominated by "open a credited route / satisfy finish" reasoning. Spending the same turns on the measured frontier would have been the better use: it already had the numbers (3282 HB at 497 tok; 54% of #17's HB in one call; 1 token = 63 HB). Candidates for which the exchange rate says "worth trying": anything at or under 361 tokens with HB near 3300, or a cast-closing step costing at most +20 tokens that removes about 3000 HB (+0.9 pt, 48 tokens).
2. Never profiled the best (#18/#19), though turn 22's drafts showed 3.4K HB in one call; the last profile was #22 at turn 37.
3. Did not set `parents`, so the graph is the compile chain; probes for the same idea hung off whatever compiled last.
4. Cost model wrong (Lean time billed; skeleton drafts nearly free). Cheapest honest alternative within the rule would have been fewer, thinking-heavy turns on measurable golf; it chose 332 skeletons.
5. Took the route label as strategy feedback and diagnosed "coarse fingerprint" before checking that it never moved the gate.
6. Minor: Fin-4 route debugged for 5 turns after the first `?m` error; two sub-0.05-point candidate pairs (#26 and #19) evaluated twice by hand.

## 6. What the harness could have done better (sorted by likely impact on score per dollar at the $0.5 cap)

1. **Make the refusal text match the gate (or make the gate match the text).** `arena.ts:1131-1147` refuses on remaining > 10% only; `rules.ts:196-197` and the tool description at `arena.ts:1101` promise "unless a credited route opened ... since this refusal". Credited routes opened in refusals 14-25 with no effect. Either state the fact ("a stop is accepted only with 10% or less left; route credit does not change that") or implement the promise (a new credited, hole-free route or a goal state new after normalisation accepts the stop). The current text produced about 50 turns of credit-chasing ($0.15-0.20). Open policy question for the owner: whether the pure spend-down is intended; this run shows it cost 67% of the budget for 0.00 points.
2. **Stop crediting trivial skeletons.** (a) `arena/lean/route.lean` `arena_route_ser`/`arena_route_claim`: erase numeric literals in the claim hash so `hB 20` and `hB 21` share a claim. (b) `arena/goalstate.py` `_goal`/`_TOKEN`: map `\b\d+\b` to a placeholder before hashing so the goal signatures of `u 724` and `u 725` are equal; this also stops the 79% "new goal state share" from counting them. (c) `arena/routes.py:493` (`credited`): require `holes == 0` (compiled) or a skeleton with at least a minimum count of distinct normalised claims, and cap skeleton-opened credit per refusal; the `MAX_SKELETON = 24` only caps the head list. With (a)+(b) alone, 314 numeral drafts collapse to 1 route and 1 goal state.
3. **Deduplicate skeleton results.** In the probe result path (`arena.ts`, `trim.ts`) return "same normalised goal as p288 (hB literal differs)" instead of the repeated hypotheses block; this removes the 18K uncached tokens per 32-draft turn ($0.0027 of the $0.0047 finish turn) and the matching ledger and extraction load. General probe results (3.7K chars each, 78% of tool-result bytes) deserve the same trim: about $0.04 (9%) of this run was re-reading them.
4. **Do not send skeleton drafts through cold Lean extraction.** `arena/campaign.py:_record_route_later` queues every draft (412 cold 1-2 GB processes, ROUTE_SLOTS = 2). A draft whose normalised text equals an earlier one, or whose token count is under a small bound with no lemma references, can take the text path (`assign_by_text`) with no Lean process. Backlog effects: lag median 79 s and max 1246 s; 132 of 327 late probes unclassified at refusal 25; 149 route events written up to 20 minutes after the run; the summary and the finish message were computed from partial data.
5. **Make `finish` use settled route data, or say it is stale.** `arena.ts:1136` computes `sinceRefusal` from `portfolio.routes`, which lacks the queued attempts. Either wait for the queue to reach the attempts made before the call, or add the number of unclassified attempts to the message (a factual line).
6. **Default parent = best so far (or none), and record a measured parent.** `current` follows the newest compiled candidate (ledger `current` sequence 1..53). #19 sits at depth 11; the 34 later candidates and the 292 skeleton probes inherit depth 12-28 (292 of 359 probes under #53, an 89.26 candidate). Before building shallow-branch credit (backlog 4b), record the nearest existing node by normalised term or text similarity as the measured parent and use that, not the label.
7. **Compaction.** Fixed by `7ee3e3c`. Check that the final empty-summary case ("Turn Context (split turn)" with no summary) cannot happen on a model turn: `arena-memory` (11.4K chars) was appended, which carried the state, but summary text was blank. Also re-evaluate `compact_at_tokens` 500000: at DeepSeek's prices the context re-read per request passes the output cost of a golf turn near 450K.
8. **Refusal message size.** 10.3K chars at refusal 25 (backlog 4c); fold the long tail into one count. With item 2 the list is short anyway.
9. **Factual cost line (optional).** At finish: "spend is billed per model request; the last 10 requests averaged $x". The model's wrong cost model drove 20 turns of exploratory drain tests. Caution: it also tells a spend-down policy how to burn faster, so only worth it paired with item 1.

## Caveats
- Ledger route counts (316 ids, 312 skeleton credited) include 149 events written after the run; live counts are summary.txt's 169 routes / 167 credited (165 per route_progress). The refusal-time numbers in the tables above come from cost-ledger `finish` records and match what the model saw.
- Keyword-based share (37 of 49 turns, $0.153) is an estimate of gate-driven turns; the model's own text at turns 40-58 states the purpose directly ("to satisfy the process", "to open a route").
- Heartbeat/token trade numbers use the packet rates: 1 token = 0.0188 pt, 100 HB = 0.0299 pt.
