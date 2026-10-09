# v6cov time_deriv (Electromagnetism) run study: rerun on the lrx + vqm fixes vs the truncated original

Theorem: `Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema` (reference 1372 tok / 26970 HB, 1 toolchain version, rates: 1 token = 0.024 pt, 100 HB = 0.124 pt). Model DeepSeek V4.1 Flash, thinking high, soft cap $0.5.
Rerun: `runs/pi-budget/v6cov-rerun-Electromagnetism.ElectromagneticPotentia-deepseek-v4.1-flash-r1/`. Original: `runs/analysis/v6cov/archive/20261009-em-truncation/v6cov-Electromagnetism.ElectromagneticPotentia-deepseek-v4.1-flash-r1/`.
Times are local (IST). Session JSONL timestamps are UTC (11:23Z = 16:53). Read-only study; no Lean builds, no paid calls.

## TL;DR

- **Both fixes worked.** 0 `length` stops in 50 turns (the original had 4 at exactly 32000 tokens, all thinking-only). Two turns exceeded 32K and completed normally (39,734 and 35,078 output tokens, both ending in a tool call); the old limit would have cut both. The wire carried `max_tokens 64000`. The only compaction was a threshold one (502K tokens, reason `threshold`) and its ledger reserve is `purpose: compaction`, reason "compaction summary bypasses the budget guard". Its estimate ($0.197) exceeded the remaining soft allowance ($0.112), so without lrx it would have been refused.
- **Score 78.33 vs 60.81 at similar spend ($0.466 vs $0.394 settled).** Best #13 = 573 tok / 6275 HB (-58% tokens, -77% HB), found at 48.4 min / $0.449; post-best spend only $0.0167. Caveat: one sample each, so the +17.5 gap is partly luck of route discovery (the rerun found a navigation-style rewrite at 28 min that the original never found), not only the fixes. The fixes' measurable value is the removed waste: the original lost about $0.16 (40% of its spend) and ~15 min to 4 truncations + 5 compactions + 4 cache resets.
- **The "13 minutes" is wrong.** The run lasted 51 min (first request 16:53:16, finish confirmed 17:44:05). The 17:31 line in `campaign-rerun.log` is a log artifact: the run dir, `lean-session.log` and first ledger rows all start at 16:52-16:53, concurrent with the main campaign (2 live Lean sessions until 17:31:27). 97% of wall time is model generation (2958 s of 3050 s) at ~157 output tok/s; tools took 92 s in total.
- **Reasoning is the cost.** 403K of 466K output tokens (86.6%) were reasoning; output tokens cost $0.281 = 60% of spend, and with their re-entry as uncached input about 65%. Median turn 5.4K reasoning tokens, 8 turns >=16K carry 41% of all output.
- **Only 2 routes because the harness fingerprint split one design in two, and finish never refused.** r1 (15 attempts, best 53.54) is the model's first calc-form rewrite, absorbed into the original's route (similarity 0.53-0.74); r2 (30 attempts, 78.33) is the same math in navigation form (similarity 0.475 at birth, 0.79 at the end). The model never opened a third skeleton; the stop rule never refused it (first `arena_finish` at 8.95% left), so no pressure to branch.
- **The compaction was net negative.** It cost $0.0551 (360K uncached input tokens; cache read only 13.5K) plus ~$0.013 refill = ~$0.068 = 14.6% of the cap, to save about $0.015 of cache reads over the 9-10 remaining turns. Break-even is price_input/price_cacheRead = 50 more requests at the compacted size; this run could never reach it. Raising DeepSeek `at_tokens` (window 1M) is the largest deterministic saving available.
- **Harness gaps with evidence:** `arena_find` returns `not_found` for the `@[to_fun]`-generated `fun_deriv_sub` that pinned source uses (name mentioned in 21 turns' reasoning, 84K reasoning tokens in turns 10, 11, 13 (partly about it) before it was confirmed); the model cannot see its spend before the first compaction (guessed the 10% window at turn 47); idea labels i2-i7 were never recorded.
- **Marginal return fell fast:** first $0.226 bought +38.6 pt (71.93); next $0.106 +5.4; last $0.134 +1.0. After the first structural step, 11 of 13 candidate steps were token golf worth 0.02-0.8 pt each.

## 1. Did the fixes work?

| check | original (archive) | rerun |
|---|---|---|
| session stop reasons | 37 toolUse + 4 `length` (32000 reasoning tokens each, no tool call) | 50 toolUse + 1 final empty `stop` (finish marker) |
| turns >32K output | 0 (cut at 32K) | 2 (39,734 at turn 13; 35,078 at turn 19), both completed |
| max_tokens on the wire | 32000 | 64000 (`max_tokens` 64000 + `reasoning_effort` high in the request journal) |
| compactions | 4 overflow compactions after length stops at 19.0, 24.6, 34.8, 40.4 min (tokensBefore 123K, 56K, 87K, 61K, far below any real window limit) + 1 more settle; compaction total 5 x $0.0374 | 1 compaction, `reason: threshold`, tokensBefore 501,870 vs `compact_at_tokens` 500000, at 17:34:29 (41.2 min) |
| ledger purpose "compaction" | none (the ledger had no purpose flag) | 1: `purpose: compaction`, gate `allow`, reason "compaction summary bypasses the budget guard", estimate $0.1973, settled $0.0551 |
| overflow compaction after a length stop | 4 | 0 |
| cache resets | 4 (uncached input 67K/74K/69K/71K on the next turn) + final | 1 (63.5K uncached on turn 40) |
| spend lost to truncated turns | 4 x ~$0.021 = $0.0857 (summary: "reasoning 4x$0.0857") | $0 |
| stop | SIGTERM (`interrupted`), $0.052 reserve still open | `finished` (confirmed), 0 unresolved |

Counterfactual for the rerun under the old 32K limit: turn 13 (105K chars of reasoning at 240 s, $0.024) and turn 19 (77.7K chars, 201 s, $0.021) would have been cut mid-thought, each followed by an overflow compaction. Turn 13 is the turn in which the model confirmed that the first draft's remaining errors were localized and issued the `lean_hover_info` calls; turn 19 produced the draft that led to the navigation-form breakthrough (p9/p13 at turns 22-24). Losing either would have repeated the original's pattern.

What the fixes did not change: the model still spends 87% of output on reasoning and still hit 39.7K in one turn; 64K is headroom, not a reduction (largest turn used 62% of it). A 64K turn costs up to ~$0.038 in output alone.

## 2. Timeline (spend and score)

Minutes from first request (16:53:16). Spend is cumulative settled USD at the event.

| event | min | $ | proxy | tok / HB | what changed |
|---|---|---|---|---|---|
| baseline (#1) | 0 | 0 | 33.33 | 1372 / 26970 | original proof |
| first probe (p1, sorry skeleton) | 9.1 | 0.066 | - | - | after 11 survey/design turns ($0.046, 52K output tokens) |
| #2 first compile | 17.2 | 0.130 | 53.54 | 1395 / 10171 | first compiling rewrite (stepwise equational chain); HB -62%, tokens +23 above reference |
| #3 | 28.5 | 0.226 | 71.93 | 791 / 7163 | navigation-style rewrite: the chain of equalities is replaced by targeted rewrites at selected subterms; tokens -43%, HB -74% |
| #4 | 33.3 | 0.263 | 73.42 | 733 / 7097 | two intermediate facts inlined (-58 tok) |
| #6 | 36.1 | 0.289 | 75.49 | 665 / 6755 | merged the sum-linearity and const-extraction steps into one rewrite list (-68 tok, -340 HB) |
| #8 | 39.0 | 0.317 | 76.69 | 628 / 6517 | two navigation blocks merged (-37 tok) |
| #9 | 40.9 | 0.332 | 77.35 | 607 / 6396 | generated function-form lemma replaces a 13-token `change` (-21 tok) |
| compaction | 41.2 | 0.332 -> 0.388 | | | $0.0551 |
| #10, #11 | 44.2, 45.7 | 0.418, 0.428 | 77.35, 78.00 | 607 / 6395, 589 / 6225 | deprecated-name rename (no token change), `Space.deriv` spelled out instead of `∂[..]` (-18 tok, -170 HB) |
| #12, #13 | 48.4 | 0.449 | 78.23, **78.33** | 576 / 6292, **573 / 6272** | `simp only []` then `beta_reduce` replace the `change` (-16 tok) |
| `arena_finish` review / confirm | 50.1, 50.8 | 0.455, 0.461 | | | 8.95% left at review; 2 requests, $0.0167 after best, 0 gain |

Marginal return: $0 -> $0.226: +38.6 pt (171 pt/$); $0.226 -> $0.332: +5.4 (51 pt/$); $0.332 -> $0.449: +0.98 (8 pt/$); $0.449 -> $0.466: 0. The only structural step (#2 -> #3, +18.4 pt) came at 28.5 min; everything after is token golf plus small HB savings. Cold verification of #13: recorded 6272 HB, cold 6275 (confirmed). Score composition at the end: tokens 58.2%, HB 76.7%, compat 100%.

Where the money went by phase (turns, output tokens, $):

| phase | turns | output tok | $ |
|---|---|---|---|
| A survey + first design (0-10) | 11 | 52.5K | 0.046 |
| B first drafts -> #2 (11-16) | 6 | 122.4K | 0.097 |
| C finds navigation route -> #3 (17-25) | 9 | 100.5K | 0.089 |
| D golf to #9 (26-39) | 14 | 104.7K | 0.101 |
| compaction | - | - | 0.055 |
| E post-compaction golf to #13 (40-49) | 10 | 85.9K | 0.078 |

28% of the cap ($0.130) and 17 min passed before any compiling candidate existed; phase B (6 turns, 122K output tokens, $0.097) got from the first 590-token skeleton to a compiling 1395-token proof, using 4 probe calls with 1+3+1+... drafts (first five drafts all failed or were sorry skeletons).

## 3. Tool use

Session tool calls (59 results, 0 errors, `isError` never set):

| tool | calls | median latency | mean result size |
|---|---|---|---|
| arena_probe | 24 (45 drafts: 33 recorded failures/skeletons, 12 compiled) | 1.3 s | 4.5K chars |
| arena_source | 15 | 0.2 s | 5.6K chars |
| arena_find | 9 | 4.1 s (max 7.3 s) | 8.8K (max 32K at turn 40, limit 60) |
| arena_profile | 3 | 1.2 s | 9.6K |
| lean_hover_info | 2 | 6.3 s | 0.4K |
| lean_goal / lean_diagnostic_messages | 1 / 1 | 1.3 s / 1.0 s | 3.4K / 1.7K |
| arena_finish / arena_state / arena_idea | 2 / 1 / 1 | 4.8 s / 0.1 s / 0.2 s | <1K |

- **Lean latency:** 45 model-lane checks, p50 1.0 s, p95 1.5 s, 0 timeouts, gate healthy. Per-version eval seconds 0.9-1.34 s. The original ran at p50 3.7 s / p95 7.7 s (3.1-4.6 s per eval) before the SharedDrive switch to ntfs3. Lean is 3% of wall time; it was never the bottleneck, and even the slow original spent only 232 s in tools.
- **Compile outcomes:** 33 failed probes, 12 compiled candidates. First-error classes: `rewrite` pattern not found 14, unsolved goals 10, application type mismatch 4, `sorry` skeleton accepted 2 (counted as P), invalid rewrite argument 1, `change` failed 1, `fun_prop` failure 1. 42% of failures are "pattern not found" inside the navigation block; they came in streaks (turns 27-31 and 33-35 each spent several drafts on one rewrite-matching issue: 31.2, 31.7, 34.5, 35.4 min).
- **Cache reuse:** 94.5% overall (11.23M read / 0.65M uncached input / 0 written), 86.9% over the last ten requests. Uncached input outside the compaction request is mostly the previous turn's output re-entering as input (e.g. turn 14: 40,107 input tokens right after the 39.7K-token turn 13); the thinking text is sent back (`reasoning_content` in the wire body), so retained reasoning, not tool output, dominates the 500K context.
- **Repeated or wasted calls:** no duplicate drafts (all `cached: false`); 9 `arena_find` calls overlap (turns 1, 3, 7, 8, 9, 10 searched the same derivative/sum lemma family; turns 40-41 re-searched it after the compaction, 20 queries, one returning 32K chars); `arena_state` (turn 37) did not report allowance, so the call answered nothing the model wanted; the final probe (p33, 549 tok) failed for $0.0069. Bookkeeping (state, idea, 2x finish) is 4 requests / $0.0226 = 4.9% of spend, so it is not a problem here.
- **Cost categories (summary.txt):** compile (probe/evaluate turns) 27 requests $0.2632, context (find/source/profile/lean) 19 requests $0.1248, compaction 1 request $0.0551, bookkeeping 4 requests $0.0226. By component: output $0.281, uncached input $0.151 (of which the compaction request $0.054), cache reads $0.034.

## 4. Model reasoning

Reasoning budget per turn (50 turns): mean 8.1K reasoning tokens, median 5.4K, max 39.6K; 16 turns >=10K, 8 turns >=16K, 12 turns <3K (those are tool-result reading turns). Every turn of the five largest (13, 19, 11, 22, 6) was a "design the next full draft" turn in which the model wrote the whole proof in its head, estimated token counts per line, then pasted it into one probe call. Reasoning-to-output ratio: >=0.95 on all large turns, i.e. no visible narration (text is 0 chars on 48 of 50 turns; two one-line sentences).

Strategy by effect on the proof:

1. **Survey (turns 0-10, 6.4 min).** Reads the Ampere-Maxwell lemma, the existing second-derivative lemma for B, and the derivative API files (`Time/Derivatives.lean`, `Space/Derivatives/Basic.lean`). Turn 6 alone is 19.3K reasoning tokens (130 s) deciding between a calc chain and a direct rewrite chain.
2. **Stepwise equational chain (turns 11-16, to #2).** Whole-proof rewrite in a calc of 5 equalities (88 lines, 1395 tok). HB fell 62% (26970 -> 10171) but tokens rose 23 above the reference; this is the "fewer heartbeats but no token saving" shape. The profile (turn 16) put 2018 HB in the calc elaboration itself and 619 in one `field_simp` side-fact.
3. **Navigation-style rewrite (turns 19-25, #3).** Uses `conv_lhs` + `enter [...]` to rewrite only the relevant subterm of the left-hand side and drops the calc and the restated intermediate equalities: 1395 -> 791 tok and 10171 -> 7163 HB in one step. Partial sorry-drafts verified each navigation step (p9 turn 22 "the conv navigation WORKS", p13 turn 24 "only 371 tokens") before the full draft. This is the structural gain of the run (+18.4 pt).
4. **Token golf (turns 26-49).** Eleven candidate steps: inline single-use facts, merge sum-linearity/const-extraction/Gauss into one rewrite list, replace a long `change` by `beta_reduce` (13 -> 1 token), generated-lemma form instead of `change`, spelling `Space.deriv` instead of the `∂[..]` macro (-170 HB), merging two navigation blocks. Heartbeats dropped 7163 -> 6272 only as side effects; the model profiled three times (#2, #3, #8) and each time identified the largest block (#8: big navigation block 2382 HB = 36.6%, 234 tokens) but then golfed tokens around it, never changing it.

What failed and why:
- Turn 11 first draft: `rw ... at h` changed `h` from `IsExtrema` to the conjunction, so a later lemma needing `IsExtrema` failed (model spotted at turn 12).
- Generated lemma name: `Space.fun_deriv_sub` is not found by `arena_find` ("not_found", 0 files scanned); the model returned to it in turns 8, 10, 11, 13 (those three big turns hold 84K reasoning tokens, a share of it on this question) before deciding it exists, confirmed via `lean_hover_info` (turn 13) and used it only in #9 at 40.9 min (-21 tok).
- `rw [sub_apply]` failed because the name is about `.val`; the pointwise-subtraction defeq is not seen by `rw` (needed a `change`), cost ~2 probe rounds (turns 21-24).
- The merged `hs2` draft (p21) failed because the coercion `⇑(∑ ...)` hid the sum from `fderiv_fun_sum` (turns 28-31, 4 probes).
- `hc'` re-proofs failed twice with the wrong association after `mul_inv_rev` (turns 20, 33).
- Final-phase gradient route (p30/p31, `Space.grad_smul`): failed at the match of `fun y => ε₀⁻¹ * ρ y` against `ε₀⁻¹ • ρ`; the Pi-smul unification is not up to defeq in `rw`.
- Root-level rewrite of the first navigation step (p33, turn 48): `Time.deriv_euclid` pattern did not occur at the root; expected saving was ~19 tokens (0.46 pt); not retried.

Misreads of tool feedback: (1) the model believed `idea_id i3..i7` created ideas; the tool reply "not a recorded idea; kept as a label" was only acted on at turn 38/45 (idea tracking stayed on i1 for 10 attempts; i1 was auto-abandoned at 47.5 min when i8 was declared). (2) At turn 47 it wrote "arena_state doesn't report the budget ... I can't cheaply check", then called `arena_finish` as a probe of the budget (it was at 8.95%, so it was allowed to proceed). (3) After p33 failed, it estimated a 4-token saving and stopped, with $0.034 unspent. No misread of a compile result was found: its diagnoses of `rewrite` failures were correct in all 14 cases where it explained them.

## 5. Context and compaction

- Peak context 502K tokens at the one compaction (turn 39: 491.9K + 8.7K output); threshold 500K of a 1M window; `keep_recent_tokens` 40K.
- Compaction request: 1.055 MB payload, 360,029 uncached input tokens, only 13,568 read from cache (the summarization prompt does not share the conversation prefix), 1,790 output tokens, $0.0551. The reserve estimate was $0.1973 (byte-bound) against $0.0551 actual, i.e. 3.6x over; it is not a spend, only a gate number.
- Pi treated the run as one user turn, so the summary is a "split turn" summary beginning "No prior history" (5.3K chars). It describes the state at about turn 30: best "#4 733 tok 73.42" and "Current failing draft p21", while the true best at compaction was #9 (607 tok, 77.35). The harness `arena-memory` message (979 chars, injected at the compaction) corrected this: "Best verified candidate: #9 proxy 77.35 ... Allowance: $0.3876 of $0.5 spent, $0.1124 left." The model's first post-compaction line (turn 40) starts from "#9: 607 tokens" and not from the summary's #4, so the stale summary did no harm here.
- After the compaction: cache reset (turn 40: 63,552 uncached + 5,376 cached = 68.9K context), recovering to 86.9% reuse over the last ten requests. Post-compaction work: 2 `arena_find` calls re-searching lemma names (20 queries), then 8 probes and the finish. Four new candidates (#10-#13) added +0.98 pt for $0.078.
- Economics: compaction ($0.0551) + refill (turn 40 pays $0.0095 uncached input where a continuing turn would have paid ~$0.0009) ~ $0.064-0.068. Not compacting: cache read of ~500-600K tokens costs $0.0015-0.0018 per turn; over the 9-10 remaining turns that is ~$0.015. Net loss ~$0.05 = 10% of the cap, about 0.6 pt at the post-compaction rate (12.6 pt/$). models.yaml says "a compaction costs ~3 uncached requests (~$0.03)"; at 500K the measured cost is ~2x that, and it scales linearly with context (the 200K compactions in the v6 pilot cost $0.016-0.028).
- No length stops (0), no failed compactions, 0 retries.

## 6. Why only 2 routes

- Routes are lemma-fingerprint clusters (`route` ledger events). r1 got 15 attempts (all the model's calc-form attempts #2 and 14 probes, similarity 0.53-0.74 to the original) and r2 30 attempts from #3 (similarity 0.475 at birth, then 0.77-0.96 as variants of itself). The first model attempt (p1, turn 11) already had the target skeleton (rewrite the LHS, split, apply Faraday, substitute Gauss); #3 differs from #2 mostly in rewrite navigation, so the "second route" is the same decomposition in a different syntactic shape; both are Ampere-Maxwell + Faraday + Gauss. Route stats at the end: r1 best 53.54 (#2), r2 best 78.33 (#13), stale streak 7, 40% of attempts produced a goal state new to their route.
- The model never attempted a third skeleton: after #3 it only changed within r2 (all 30 r2 events have similarity >= 0.77 to r2 itself except its birth).
- The stop rule did not push: the first `arena_finish` was at 8.95% remaining (<=10%), so it returned the factual review directly (no refusal, `refusals` never incremented); the model made one more probe (p33) and confirmed. In earlier runs the refusal ladder (10% rule, "new credited route required") forced one or two new routes; here the spend arrived at the 10% line before the model ever called finish.
- Budget: r1's 15 attempts took the first 28.6 min / $0.226, i.e. 45% of the cap went before r2 opened. After that the 14-turn golf phase (phase D) was profitable per dollar early (#4-#9: 5.4 pt for $0.106) and then flat.
- The `label` of r2 in the summary is a lemma diff ("+ContinuousLinearMap.smul_apply +ContinuousLinearMap.sub_apply +Space.deriv_sub ..."), which is not informative to the model (it only sees "r2 (credited)" in the memory message).

## 7. The pace: 51 minutes, not 13

- Timestamps: run dir and lean-session.log 16:52, session start 11:23:14Z = 16:53:14, first ledger row 16:53:16, `finish confirmed` 17:44:05, lean shutdown 17:44:07. Elapsed 50.8 min.
- `campaign-rerun.log` begins "17:31:27 main campaign exited; starting the time_deriv rerun" and also contains an argparse usage block with no timestamps; the log was written by more than one process (rerun-em.sh truncates it with `: >` at launch, an older waiter appended at 17:31). The 17:31 stamp is the old waiter message, not the start of this run. The Lean session log confirms concurrency: "share 4 (2 live sessions)" at 16:52:04 and "share 8 (1 live sessions)" at 17:31:27 when the main campaign ended.
- The wall-time budget: 51 requests, 59 s per request on average. Turn time is generation time: 2958 s of 3050 s (97%), measured as the gap between consecutive assistant messages minus tool time; tools 92 s. Model throughput 465,950 output tokens / 2958 s = 157 tok/s. The five largest turns took 130-240 s each (turn 13: 39.7K tokens in 240 s). The original had the same shape (134 tok/s, 3035 s model time, 232 s tools).
- Therefore pace is set by reasoning volume, not by Lean or the harness: 1 minute of wall time ~ 9.4K output tokens ~ $0.0092 at the output price ($0.0097 including re-entry), so $0.5 ~ 54 min.

## 8. Original vs rerun

| | original | rerun |
|---|---|---|
| proxy / tokens / HB | 60.81 / 1060 / 10870 | 78.33 / 573 / 6275 |
| settled / wall | $0.394 (+$0.052 unresolved) / 54.9 min | $0.466 / 50.8 min |
| requests, stop | 47, SIGTERM at 21% left (after a finish refusal) | 51, finished at 8.95% left |
| length stops | 4 x 32K thinking-only (18.6, 24.1... 39.9 min) | 0 |
| compactions | 5 settles ($0.0374), 4 overflow at 56K-123K context | 1 threshold at 502K ($0.0551) |
| first compile | 10.8 min / $0.061 (1383 tok, 21016 HB) | 17.2 min / $0.130 (1395 tok, 10171 HB) |
| Lean eval seconds | 3.1-4.6 (p50 3.7 s) | 0.9-1.3 (p50 1.0 s) |
| routes | 1 (17 attempts, 0 credited) | 2 (15 + 30 attempts, 1 credited) |
| probes / candidates | 8 / 10 | 33 / 13 |
| cache reuse | 83.4% | 94.5% |

Waste in the original: 4 truncated turns ($0.0857) + 5 compaction settles ($0.0374) + 4 cache resets (~$0.04 extra uncached input) = ~$0.16, 40% of its spend, and 15 min of generation time (4 x 213-243 s). It also ran Lean 3.7x slower; both effects cut the number of Lean-checked attempts to 18 evaluations vs 24 here. The rerun got 4x more probes for 1.2x the spend. The score gap cannot be attributed only to the fixes: the original stayed with the calc-form rewrite (best 1060 tok / 10870 HB, never found the navigation-style step), whereas the rerun reached it at 28 min.

## 9. What the MODEL could have done better

1. **Spent 28% of the cap and 17 minutes before a first compiling candidate** (turns 0-16: 175K output tokens, $0.143). The first probe was a 590-token skeleton with 1 draft; the second probe batch used 3 drafts. After the 1395-token proof it needed another 9 turns to find the navigation form. A cheaper path: probe skeleton drafts with `sorry` at each step boundary from the first call (it did this only at turn 22, after which the route opened up within 3 turns).
2. **Large design turns were reasoned in one go.** Turns 6, 10, 11, 13, 19: 19.3K, 18.8K, 25.7K, 39.6K, 30.7K reasoning tokens (134K total = 33% of all reasoning, $0.10) mostly re-deriving lemma signatures and estimating token counts line by line. The probe tool returns exact tokens and goal states for $0.001-0.002 per check at ~1.3 s; the arithmetic estimates were never decisive.
3. **Profile data not used for the heavy axis.** The third profile (#8) showed one block at 2382 HB (36.6%) and 234 tokens; subsequent drafts only shaved around it (HB 6517 -> 6272, 4%). The 14-turn golf phase moved tokens 628 -> 573 (+1.3 pt) and HB -245 (+0.3 pt).
4. **Idea hygiene.** Used `idea_id` labels i2-i7 that were never created; the harness showed "i1 active, 10 attempts" for the whole middle of the run; the memory message said "Ideas: i1 [active]: 10 attempts" at compaction. Declaring routes with `arena_idea` early (turn 11 supplied `idea` text once) would have given the harness correct per-route accounting.
5. **Budget awareness.** It could not see its allowance until the compaction message; at turn 47 it guessed and used a finish call as a meter. Not an error on its part (see harness list), but it left $0.034 (6.9%) unspent.
6. **One-route search.** All 45 drafts are the same decomposition. The task text asks for "at least two structurally different routes before golf"; the model took the instruction as satisfied after r2 opened. No attempt to compare against a different decomposition was made, so the 573-token floor of this decomposition is untested against alternatives (the effect of one: the navigation block alone is 234 tokens and 36% of HB).
7. **Retries on the same rewrite family.** 14 of 33 failed probes were "pattern not found" in the same navigation block; four of them arrived as pairs of drafts (turns 27-31, 33-35) which differed in the failing step only by wording.

## 10. What the HARNESS could have done better (sorted by likely impact on score per dollar)

1. **Raise or disable late compaction for DeepSeek** (`models.yaml` `deepseek-v4.1-flash.compaction.at_tokens: 500000`, passed via `tools/run_pi_budgeted.py:243-247,364-366` as `reserveTokens`). Measured cost at 500K: $0.0551 compaction + ~$0.013 refill; saving over the remaining turns ~$0.015. Break-even is 50 further requests at that size (input price / cache-read price = 0.15/0.003); with a $0.5 cap a run has ~50-90 requests in total, so any compaction after ~40 requests loses money. Window 1M with 64K output: `at_tokens` ~ 850K leaves room. Expected: +$0.05 of exploration (~10% of cap, ~0.6 pt at the observed late rate; more in rows where context grows faster). Also correct the models.yaml comment ("~$0.03"), which was measured at 200K. Risk: quality at long context is unmeasured here (the model's late behaviour was fine up to 502K).
2. **Make `arena_find` / `arena_declarations` index generated declarations** (`@[to_fun]` produces `fun_deriv_sub`, `fun_deriv_add`, ...; `arena_find` returned `not_found, files_scanned 0` for these at turn 8, and "fun_deriv" returned only `MeromorphicAt.fun_deriv`). Implementation: in the pinned-source search (`arena/` source index used by `arena_find`), either expand `@[to_fun]`/`@[simps]`-style attributes to their generated names, or on a miss fall back to a Lean `#check`/`lean_local_search` over the compiled environment (the `mcp__arena_lean__lean_local_search` tool exists but is not offered in the tool list the model used). Evidence: the name appears in the reasoning of 21 of 50 turns (7, 25, 25 mentions in turns 10, 11, 13); the lemma was only used at 40.9 min. The saving is hard to size; the token gain it enabled was 21 tokens (+0.5 pt). Likely gain: a few cents and the 21-token step earlier.
3. **Give the model its spend, factually.** The only allowance line is in the post-compaction memory message (`arena/memory.py:51`); `arena_state` (stateLine, `packages/arena-pi/extensions/arena.ts:~1303`) does not include it, and the model used `arena_finish` as a meter at turn 47. Add one line to `arena_state` and to the `[arena]` status suffix: "spent $X of $0.5; Y% left; last turn N output tokens". Purely factual. Saves ~1-2 wasted calls ($0.01-0.02) and removes the guessing at the 10% line; also helps the model weigh a 40K-token design turn ($0.024 = 5% of the cap) against the 0.02 pt it typically buys late.
4. **Surface reasoning cost per turn as a fact** (same status line): in this run 8 turns carried 41% of output; the three largest cost $0.024, $0.021, $0.016. Whether to test `thinking medium` for DeepSeek in a matched replicate is a harness experiment, not a nudge: reasoning is 86.6% of output and 65% of spend, so a 30% cut in reasoning tokens is worth ~$0.09 (~18% of cap). Not a certain gain; the 64K limit and `high` are fixed per run (`requestShape` in `budget.ts` forbids changing mid-run), so this needs an A/B across rows.
5. **Reconcile idea labels.** When `arena_probe`/`arena_evaluate` receive an unknown `idea_id` (i2-i7 here), create the idea from the supplied `idea`/title or return an error instead of "kept as a label": 7 probe/candidate records carry ids that do not exist in the ledger and the middle of the run is attributed to i1 (`idea` events: only i1 and i8). Low direct score impact; improves the `Ideas:` section of the memory message and the route credit accounting.
6. **Make the route label informative and route-splitting less noisy.** r2's label is a lemma diff against r1 (`+ContinuousLinearMap.smul_apply ... -Mathlib.Tactic.FieldSimp.NF.cons_eq_div_of_eq_div`), and the first calc-form rewrite was filed under the original's route (similarity 0.59 to the reference) because the fingerprint is lemma-set overlap. Suggestion: in the finish review and memory message state measurable quantities per route (best proxy, tokens, HB, attempts, new goal states) rather than the lemma diff; the memory line already has this partially. No effect on this run's score, but it matters when the 10% rule asks for a "new route".
7. **Stale compaction summary.** The summary written at 41 min described #4 (73.42) as the best while #9 (77.35) was the truth, because Pi's split-turn summary covers only the prefix before `keepRecentTokens`. The memory message corrected it; keep that message, and consider also injecting the best candidate's source/token profile in it when the best is older than the kept window (here the model had it in the kept turns). Low cost, protects the case where a compaction occurs just after a new best.
8. **Probe feedback near the end of a failing rewrite.** 14 of 33 failed probes stop at the first failing `rewrite` with "pattern not found" and give only the first error; subsequent steps are not elaborated, so the model learns one defect per ~$0.007-0.015 turn. `arena_probe` could automatically also return the goal state at the failing proof line (as it does for `sorry` holes) so that the failing step can be fixed together with its neighbours: the model did this by hand at turns 22 and 24 with partial `sorry` drafts, and these were the turns that unlocked the navigation form.
9. **Housekeeping:** the 17:31:27 line in `campaign-rerun.log` mislabels the run start; `rerun-em.sh` states it waits for PID 340066 but the script no longer waits, so the log has two writers. Have the script write its own start time into the log and use a distinct log file per launch.

## Appendix: key numbers

- Session: 51 assistant messages (50 turns + final empty `stop`), 59 tool results, 0 errors, 1 compaction. Output 465,950 tokens (reasoning 403,363). Uncached input 648,990 (of which the compaction request 360,029), cache read 11,227,008, cache write 0.
- Cost: $0.4657 settled; $0.4106 in turns + $0.0551 compaction; components output $0.2806, input $0.1514, cache read $0.0337. Soft remaining $0.0343, no overshoot, hard cap $3 untouched (not used in any argument above).
- Best #13 source: `submission.lean` (59 lines), parent chain #1 -> #2 -> #3 -> #5 -> #6 -> #8 -> #9 -> #10 -> #11 -> #13 (`ledger.jsonl` candidate events). Candidate sources in `proofs/`; per-draft diagnostics in `diagnostics/`.
- Compaction record: session JSONL `type: compaction` (`tokensBefore 501870`, `firstKeptEntryId 2c9697bc`); ledger `reserve` row with `purpose: compaction`; `memory` row at 17:34:29 (979 chars).
