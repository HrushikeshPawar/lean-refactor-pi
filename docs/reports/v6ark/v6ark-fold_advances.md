# v6ark Binius fold_advances_evaluation_poly run study: 90.51 proxy, "$1.32 all-call cost" is $0.453 real spend plus $0.864 of phantom reservations

Theorem: `Binius.BinaryBasefold.fold_advances_evaluation_poly` (ArkLib pin c1712f6, 3 toolchain versions; reference 1906 tok / 45273 HB; 1 token = 0.0525 pt, 100 HB = 0.074 pt). Model DeepSeek V4.1 Flash, thinking high, soft cap $0.5, `compact_at_tokens` 850000.
Run: `runs/pi-budget/v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1/` (campaign `runs/analysis/arklib/campaign.log`). Times are local (IST); session JSONL is UTC (14:42Z = 20:12). "Event N" is a 0-based line of `events.jsonl`; "req N" is the N-th reserve row of `cost-ledger.jsonl` (97 in total); "turn N" is the N-th assistant message in the session file (98, of which 8 are error turns). Read-only study: no Lean, no paid calls.

## TL;DR

- **There was no over-cap spend.** Settled (billed) spend is **$0.4531 = 90.6% of the $0.5 soft cap**; `overshoot_usd` 0, no `bound_violation`, all 97 gates `allow`, `soft_cap_reached` never fired. The reported "$1.3167 all-call cost" is `spent_usd + unresolved_usd` (`tools/run_campaign.py:172`), and **$0.8635 (65.6%) of it is eight reservation estimates for failed provider attempts that returned no usage**: one stream cut at req 9 ($0.0502) and seven attempts in a 32-second network outage at 21:04 (reqs 67-73, 6 x `Connection error.` + 1 `Request timed out.`, $0.1162 each). Those 8 attempts have `usage` all zero and no response body; they are never released (`arena.ts:354-360`, `arena.ts:659-666`), so they sit in `unresolved` for good and are summed into "cost".
- **The 7 outage attempts did not add a cent of settled spend and the retries were not billed by anything visible.** The $0.1162 each is the worst-case estimate (full 490K-token prompt uncached + 64K output); the real cost of a request at that context was about $0.0066 (median of reqs 60-66). The only attempt that could have been billed is req 9 (stream delivered 8,781 chars of reasoning in 86 s, then `terminated`); an upper bound is about $0.01 (2.5K output tokens + a 65K prompt, mostly cached).
- **The same artifact inflates the whole campaign:** the "4 runs, all-call cost $3.2985" is real settled $0.919 (0.4512 + 0.4531 + 0.0146 + 0). The two runs that died of `error_loop` at 21:42 show $0.5876 and $0.5776 of "cost" with $0.0146 and $0.0000 settled (11 and 12 `Connection error.`/timeout rows, no successful response in the second).
- **Soft cap / finish gate behaved as designed.** Footer on 92 of 92 tool results, correct to the cent; the finish gate refused at 10.71% left (req 96, event 192516 area), accepted at 9.4% (req 97); stop `finished`, remaining $0.0469. Compaction never triggered (max context 633,205 tokens at req 89 vs 850,000), so 0 compaction rows and 0 bypass rows.
- **Score 90.51 (258 tok / 6766 cold HB, -86.5% tokens, -85.1% HB, compat 100) at $0.432 and 76.1 min.** Post-best spend $0.0213 over 5 requests. 84.72 was reached at $0.136 (30% of the settled spend); the last $0.32 added +5.8 pt, the last $0.19 only +1.4.
- **Single-route run.** 69 compiled candidates all stayed in r1 (similarity 0.61-0.91 to #2); one idea `i1` was recorded (110 attempts). The model wrote "the guidance says to try at least two structurally different routes" at turn 29 ($0.19), then judged its route "near optimal" and never opened another one.
- **Spend-down behaviour is the main model-side finding.** From turn 50 ($0.25 spent) 33 turns' reasoning contains "I need to spend down to ~$0.45 before I can finish" (turns 50, 53, 55-66, 75-81, 83-93, 96); 8 of them call cheap re-probes "gaming the budget" (turns 50, 53, 60, 62, 64, 79, 88, 96), and the model deliberately probed near-duplicates "to spend budget" (turns 79, 83, 94, 96). The finish rule (`rules.ts:168`, SKILL.md lines 85 and 99) is working as intended but the model reads "unspent allowance has no value" as an instruction to burn money, not to open new routes.
- **One tool error** (`arena_source` with handle `compoly:CompPoly/...`, turn 6): the model invented a `<repo>:` prefix. The two `lean_local_search` calls returned `"index":"error"` with only stdlib hits and are not counted as tool errors.

## 1. Timeline

| time | event |
|---|---|
| 20:09:10 | Lean session up (pid 1405779, 4 slots, 5 GB reserve; 2 live sessions sharing) |
| 20:09:12-20:09:45 | arklib-v4.31.0 server; header `Session1.lean` open 6.9 s; slots ready at 14.4 s, 22.2 s, 33.1 s |
| 20:10:10-20:11:05 | arklib-v4.30.0 started, slot ready in 54.8 s; header Session6 24.7 s (evicted a v4.31 worker) |
| 20:11:43-20:12:21 | arklib-v4.29.0 started, ready 24.9 s; header Session8 13.5 s. Total Lean warm-up before the first request: 3.5 min |
| 20:12:43 | **first model request** (req 1, 21,821 uncached prompt tokens, $0.0035). First tool calls: `arena_state` + `arena_source` |
| 20:12:43-20:18:50 | survey: reqs 1-8, 3 `arena_find`/`arena_declarations`/`arena_source` rounds, $0.0177 |
| 20:15:47 | req 9 killed by the provider (`terminated`) after 86 s and 8,781 chars of reasoning (event 5003); retried automatically (event 5004), req 10 produced 16,239 output tokens and `arena_candidate #1` |
| 20:19:55 | first probe (p1, a `sorry` skeleton; `Unknown identifier ℱq`), $0.034 |
| 20:21:05-20:23:38 | idle-close of v4.30/v4.29 servers (600 s), re-opened on the background lane (Session9/11/12 headers 6.8-25.8 s) |
| 20:23:40 | **first compile**: #2 = 1257 tok / 20484 HB, proxy 62.93, $0.054 (14.5 min from Lean start, 11 min after the first request) |
| 20:25:39 | `arena_idea` i1 (the only idea); #3 at 20:26:40 (818 tok / 16707 HB, 73.39) |
| 20:36:00 | #9: 462 tok / 9785 HB, 84.72, $0.136 |
| 20:53:01 | Lean check ran past 180 s (probe at event 103480, turn 48), `compiled:false`, worker kept warm |
| 21:04:30-21:05:00 | network outage: events 146794-146845, reqs 67-73 (see section 2) |
| 21:17:53 | second 180 s timeout (probe at event 166171, turn 79) |
| 21:25:16 | **best #67**: 258 tok / 6759 HB (cold 6766), proxy 90.51, $0.432, 76.1 min after Lean start |
| 21:27:05-21:30:23 | `arena_finish` review refused (req 96, 10.71% left), one more probe (#70, 90.35), then `arena_finish` confirm triggered a cold verification of 3 versions (198 s, event 192516) |
| 21:31:07-21:31:13 | confirm accepted (req 97, $0.4531, 9.4% left), `stop: finished`, session shutdown |

Wall time 82.0 min (78.4 min from the first request). Tool time 879 s = 18.7% of the wall from the first request: 2 x 180 s Lean timeouts (7.7% of wall) and 198 s of cold verification; median probe about 3.5 s. The remaining ~3,825 s (81%) is model generation at about 117 output tok/s (446,751 output tokens).

## 2. Spend: where the $1.3167 comes from

### 2.1 Decomposition

| item | requests | USD | share of "all-call" |
|---|---|---|---|
| settled agent turns (89 turns with usage; 0 compaction, 0 route extraction, 0 other calls) | 89 | 0.4531 | 34.4% |
| unresolved: stream cut (req 9) | 1 | 0.0502 | 3.8% |
| unresolved: outage attempts (reqs 67-73) | 7 | 0.8135 | 61.8% |
| **all-call (`spent + unresolved`)** | 97 | **1.3167** | 100% |

Settled by component: output $0.2681 (59.2%, 446.8K tokens), uncached input $0.0953 (21.0%, 635K tokens), cache read $0.0898 (19.8%, 29.9M tokens). Every settled request is an ordinary model turn: there is no `purpose: compaction` reserve, no summary request, and route extraction is done by the text-fingerprint worker with no model call (`route-queue.jsonl`, 141 lines). By turn type (summary.json): compile 73 x $0.3847, context 11 x $0.0501, bookkeeping 4 x $0.0168, rejected 1 x $0.0015 (the `compoly:` source call). $0.0033 per evaluation (138 evaluations).

### 2.2 Why the unresolved rows exist and why they are phantom

- `closeRequest` (`arena.ts:593-668`) writes a `settle` row only when `message.usage.totalTokens` is non-zero. Otherwise it writes `release` if the request never hit the wire and `unknown` if `wireIndex > 0`. All 8 failed attempts passed the `wire` hook (the hook fires before the connection), so they were recorded `unknown` with reason `provider_attempt_without_settled_usage`.
- `costState()` (`arena.ts:340-361`) deletes a reservation only on `settle` or `release`. An `unknown` row leaves it open forever, so it counts in `unresolved` (and in `hard_remaining_usd`, `cost.json`: 1.683 = 3 - 0.453 - 0.864) and in the campaign "cost".
- Evidence that the 7 outage attempts never reached the model: trace-journal `wire` rows for reqs 68-70 and 72-73 have `suffix: 0` and an empty `body` (the body was not even assembled to the end), responses carry `content: []`, `response_id: null`, `error_message: "Connection error."`; req 67 (`Request timed out.`, wire body sent, 1,444,510 prefix bytes) lasted 10.1 s with no response bytes. Settled usage is zero for all.
- The estimate is a worst case by construction: $0.1162 = 490K input tokens at the uncached rate ($0.0735) + 64K output at $0.6/M ($0.0384). Against 89 settled requests the estimate exceeded the actual price every time (`bound_violation` false 89/89); median actual at that context $0.0066, so the estimate is about 17x the real price.

### 2.3 Where spend "crossed" $0.50

- **Settled spend never crossed $0.50.** Maximum $0.4531 at req 97. Soft remaining at the last settle: $0.0469.
- **All-call crossed $0.50 at req 68** (21:04:37, event 146802, first `Connection error.` after the timeout): all-call $0.4967 after req 67 ($0.3303 settled + $0.0502 + $0.1162 + ... ) and $0.6128 after req 68; it reached $1.1938 at req 73 (event 146842, the last failed attempt, 55.6 min after the first request). The soft-cap gate and the footer use settled spend only (`soft_remaining_usd` stayed 0.1697 across all eight `unknown` rows), so nothing reacted, correctly.
- What happened next: the 3-attempt auto-retry ran out (events 146795-146819: attempts 1-3 all failed), the harness continuation fired (event 146820), 3 more attempts failed (events 146826-146842, `willRetry` true each time) and the third retry succeeded (event 150319, `auto_retry_end success true attempt 3`). Req 74 settled at 21:05:00 ($0.0070) and the run went on. Error streak reached 1 (`control` row at 55.4 min) and never 3, so `error_loop` (`MAX_ERROR_STREAK` = 3, `arena.ts:22`) did not fire. The two sibling runs that died at 21:42 hit exactly that rule (11 and 12 failed attempts).
- Could the unresolved rows have blocked this run? The hard gate subtracts them: `budgetGate` (`budget.ts:300-310`) compares the estimate against `3 - spent - unresolved`. Remaining after the outage was $1.806; each further failed attempt at 500K context removes $0.116, so 15 more failed attempts would have refused every later request with `estimated_request_unaffordable`, a false stop at $0.45 real spend. Not reached here.

### 2.4 Retries and billing

8 `auto_retry`/error turns (7 outage + req 9), summary `retries: 8`. Zero billed usage appears for any of them, and the next successful request after each shows cache read equal to the pre-failure context (req 66: 491,776 read vs 491,849 context before the outage; req 11: 68,736 read, unchanged), so no failed attempt wrote or invalidated the prefix. Only req 9 may have been billed provider-side (partial reasoning); the ledger cannot see it. Upper bound $0.01 (2% of the cap).

A later run's `Connection error.` death at 21:40 is the same outage class: `v6ark-FieldSpecification...` has 12 failed rows and no `settle` at all; `v6ark-interleaved...` has 11 `Connection error.`, 1 timeout, 7 successful turns. Both ended `error_loop` with settled $0 and $0.0146 and the "unresolved" $0.5776 and $0.5876 are the same phantom estimates.

## 3. Did the new fixes behave?

| fix | observed | verdict |
|---|---|---|
| Budget footer `[arena] ... budget: $X of $Y spent · N% left` | present on 92/92 tool results (65 probe, 8 profile, 5 source, 5 find, 2 declarations, 2 finish, 2 lean_local_search, 1 state, 1 candidate, 1 idea); values follow settled spend only ($0.00 at turn 1, $0.45 and 9% at turn 97); stayed correct during the outage ($0.33 / 66%) | works; the model read it (it quotes "$0.17, 34%" and "$0.05 left" in reasoning) |
| Facts-only continuation / finish refusal | refusal at req 96: "Stop refused: $0.45 of $0.5 spent, $0.05 (11%) left. A finish confirm is accepted once 10% or less of the allowance remains. Routes tried: r1 (not credited) · 1 attempt · 1 goal state · best proxy 62.93 (#2). Current best, saving vs the original and score points not yet earned per axis: tokens 86% saved, 4.7 pts left; heartbeats 85% saved, 5.0 pts left." Facts only, no advice | works. Defect: it quoted `best proxy 62.93 (#2)` for r1 (the route's *first* attempt) next to a global best of 90.51, which reads as stale; the one continuation message (event 146820) begins "The turn ended with text and no tool call." although the turn was a failed request (empty content, `Connection error.`); wrong label from `rules.ts:202` called on the `failed` path at `arena.ts:1305-1313` |
| Compaction at 850K | not triggered: max context 633,205 tokens (req 89); at the recent ~4.5K tokens per turn it would have taken about 40 more turns at the recent 4.5K tokens per turn (the run average is 6.9K) | untested here; cost 0 |
| Routes credited only from compiled proofs | 12 `sorry`-bearing probe drafts (5 passed with `declaration uses sorry`, 7 failed to compile) opened no route; r1 was born at #2 (first compiled proof, similarity 0.0, `new true`); 68 later records stayed in r1 (similarity 0.61-0.91) | works. Result: 0 credited / 1 explored; "100% new goal state share" is 1 of 1 and carries no signal |
| `compiled:false` / `heartbeat_to_failure` | 47 of 123 drafts `compiled:false`; 38 carry `heartbeat_to_failure` (e.g. 12,835 at turn 20); the 9 without it are 7 `sorry` skeletons and the 2 Lean timeouts | works; for the 2 timeouts (`Lean timed out after 180 seconds`, turns 48 and 79) there is no line, no partial HB, nothing to learn from |
| Unicode declaration names | `arena_declarations` resolved 9/9 including `AdditiveNTT.normalizedWᵢ_eval_βᵢ_eq_1` | works. Separate model-side slip: first drafts used `ℱq` (U+2131) instead of `𝔽q` (U+1D53D), `Unknown identifier ℱq` in the first 2 drafts (turn 11, p1/p2), (first probe at $0.034, 10.7 min) |
| `max_tokens` / length stops | stop reasons: 89 `toolUse`, 8 `error`, 1 `stop`; 0 `length`; largest turn 16,940 output tokens (turn 29) | ok |

The one tool error: turn 6, `arena_source {"handle": "compoly:CompPoly/Fields/Binary/AdditiveNTT/Intermediate.lean"}` returned `compoly:... does not exist in the pinned project or its dependency roots` (`arena/campaign.py:533`). `arena_find` had returned `path: "CompPoly/Fields/..."` with a *different pin* (e95ba1b); the model guessed a `repo:` prefix by analogy with the `arklib:` handle it had used (turn 1) and retried without the prefix next turn (7 s, $0.0015). The message does not name the valid forms.

## 4. Model behaviour

Shape: 98 turns, 446.8K output tokens, 1.02M chars of reasoning vs 0.26M chars of tool arguments (reasoning about 80% of output), median turn 4,449 output tokens, 20 turns of 8K or more carry 48% of output. 65 `arena_probe` calls (123 drafts, 52 probe rows + 69 fast/full evaluations = 138 evaluations), 8 `arena_profile`, 5 `arena_find`, 5 `arena_source`, 2 `arena_declarations`, 1 `arena_state`, 1 `arena_candidate`, 1 `arena_idea`, 2 `arena_finish`, 2 `lean_local_search`.

### 4.1 Score trajectory (best-so-far at each step; cost is settled spend at the evaluation)

| candidate | settled $ | tokens (axis %) | HB (axis %) | proxy |
|---|---|---|---|---|
| #1 baseline | 0 | 1906 (0) | 45273 (0) | 33.33 |
| #2 first compile | 0.054 | 1257 (34.1) | 20484 (54.8) | 62.93 |
| #3 | 0.080 | 818 (57.1) | 16707 (63.1) | 73.39 |
| #8 | 0.127 | 682 (64.2) | 11778 (74.0) | 79.40 |
| #9 | 0.136 | 462 (75.8) | 9785 (78.4) | 84.72 |
| #20 | 0.195 | 402 (78.9) | 8013 (82.3) | 87.07 |
| #29 | 0.264 | 319 (83.3) | 7259 (84.0) | 89.08 |
| #40 | 0.324 | 295 (84.5) | 7075 (84.4) | 89.63 |
| #50 | 0.362 | 281 (85.3) | 6855 (84.9) | 90.04 |
| #67 best | 0.432 | 258 (86.5) | 6759 (85.1) | 90.51 |

Compat stayed 100% on all kept candidates; #60 (79.23) and #61 failed one version (v4.29.0, "unsolved goals", background check) and were fixed by #62 two evaluations later. Per-axis highs: tokens 251 (#43, but HB 10823, proxy 87.64), HB 6759 (#67). Points still available: 4.5 on tokens, 5.0 on HB (the finish review printed 4.7 / 5.0 for #69).

Marginal return: $0-0.054: +29.6; $0.054-0.136: +21.8; $0.136-0.264: +4.4; $0.264-0.362: +0.96; $0.362-0.432: +0.47. 97% of the total gain over the baseline (55.8 of 57.2 pt) was in the first $0.264 (stopping at $0.264, 58% of the settled spend, would have given 89.08 vs 90.51; the last 1.43 points cost $0.19).

### 4.2 Ideas, routes, profile

- **One idea.** `i1` at +16.5 min ($0.072): "use qMap_total_fiber_one_level_eq for the fiber difference and replace the polynomial-sum calc by a linearity identity", expected tokens down ~600, HB down ~30K. Reality: 1906 -> 1257 -> 818 tokens and 45K -> 16.7K HB by #3; the idea was never closed or amended (`attempts 110, probes 42` at the end, `ideas without attempts 0`).
- **One route.** r1 "text fingerprint, first route": best proxy 62.93 (#2), 1 attempt, 1 goal state, min holes 0, explored, not credited. The 68 later compiled candidates fingerprinted at 0.61-0.91 against r1 and joined it. The model considered a second route at turn 29 ($0.19) and turn 44, 50, 62 ("let me think whether any completely different route could do much better", "near the floor for this route") but each time resolved to micro-optimise; no second skeleton was ever probed.
- **Profile use was productive and early.** 8 `arena_profile` calls at +13.6, 17.5, 20.9, 22.2, 28.4, 34.8, 47.5, 49.2 min; each was followed by a heartbeat drop (20484 -> 16707 -> 15520 -> 12995 -> 9785 -> 8596 -> 7931 -> 7259 HB). After 49 min the model profiled no more and HB moved only 7259 -> 6759 (-500 HB = +0.37 pt) over the remaining $0.19, when its own reasoning listed the top HB items (turn 62: "h_fiber_diff 960, h_coeff 663, set F 347, ring 314").
- **Spend-down behaviour** (turns 50-97): after the first refused-finish rule check in its own reasoning (turn 50: "So I can't finish yet! ... I need to spend down to ~$0.45"), 33 reasoning blocks repeat the need; probes are described as "to spend budget", "harmless variant", "re-probe the same #67 to cross the threshold" (turns 79, 83, 94, 96). Cost of turns 50-97 is about $0.21 for +2.9 pt, but the last request before the confirm (req 96-97, $0.0067) was a stand-alone filler: #70 scored 90.35 < 90.51 and the finish confirm waited 4.1 min (cold verification) after that.

### 4.3 What limited the score

1. **Route diversity, not effort.** All 69 candidates are variants of one skeleton; tokens (86.5%) and HB (85.1%) both sit about 14 points from the ceiling and the model's own estimate by turn 46 ($0.28) was "near the floor for this route". Nothing in the run tested whether another skeleton lowers the floor.
2. **Heartbeat floor 6.8-7.1K from $0.33 on**; its biggest known components (about 960 + 660 + 350 + 310 HB) were examined for 50 turns without a step.
3. **Two 180 s Lean timeouts** (turns 48 and 79) consumed 6 of 78 minutes and returned no information about the failing draft.
4. **Reasoning volume**: output tokens are 59% of spend and re-enter as uncached input next turn (the wire body carries `reasoning_content`), which accounts for most of the $0.095 input spend.

## 5. Cache

Reuse 97.92% overall (29,917,056 read / 635,449 uncached input, write 0), recent ten 99.35%, cost savings 96.0%/97.4%, 0 alarms. The only full miss is req 1 (21,821 uncached, expected); the lowest later per-request reuse is 74.0% (reqs 2-3, small contexts of 29-40K) and 76.8% at req 10 (the retry after the stream cut, when the 16K-token turn plus tool results is new content). The outage left the prefix intact (see 2.4). Uncached input averages 7.1K tokens per turn (previous output plus tool results), largest 21.8K at req 1, 20.7K at req 10, 18.6K at req 29, 16.1K at req 24, 15.2K at req 72. Cache read is 19.8% of spend ($0.0898 over 29.9M tokens at $0.003/M); an 850K compaction would have been priced against that, but the run never came near it.

## 6. Ranked findings and fixes

1. **"All-call cost" counts failed-attempt estimates as spend (HIGH, accounting; this report's headline).** $0.8635 of $1.3167 here; $3.2985 vs $0.919 real for the campaign; two sibling runs show $0.58-0.59 "cost" with $0.00-0.015 settled. Fixes: (a) `packages/arena-pi/extensions/arena.ts:659-666` classify an attempt as `release` (not `unknown`) when the response has no content, no usage and `errorMessage` is `Connection error.` or `Request timed out.`; keep `unknown` only for a stream that delivered content then died (req 9), and price it from the delivered characters, not the 64K-output estimate; (b) `arena.ts:340-361` do not keep `unknown` reservations in `unresolved` at full estimate (or cap them at the delivered-content price); (c) `tools/run_campaign.py:172` and its summary line should print `settled` and `unresolved (upper bound)` separately and never add them for "cost"; the campaign headline `all-call cost $3.2985` should read the settled sum.
2. **Unknown reservations erode the $3 hard gate (MEDIUM, latent false stop).** 7 outage attempts consumed $0.81 of $3 headroom; at about 500K context 15 more would refuse the next request as `estimated_request_unaffordable`. Same fix as 1(a)/(b); also add a test with 8 consecutive transport errors that asserts `hard_remaining_usd` is unchanged (`packages/arena-pi/extensions/` tests next to `rules.test.ts`).
3. **Finish rule teaches spend-down (MEDIUM, model behaviour).** 33 turns of reasoning, 4 explicit "gaming the budget" admissions, filler probes at $0.0067-$0.015 each. The text is correct ("Unspent allowance has no value", `SKILL.md:99`) but the refusal message only lists what was tried, so the cheapest compliant action is another probe. A factual fix: have the refusal and the continuation include the route count and the per-route attempt counts already shown ("Routes tried: r1 ... 1 attempt") plus the number of probes since the last new route; and describe the finish threshold as a stop condition, not a target ("The run ends when 10% or less is left" instead of "A finish confirm is accepted once ..."). Test by A/B on this row (same packet, `ARENA` finish text variants); measure turns with spend-down language.
4. **Single-route outcome (MEDIUM).** The model never opened a second skeleton despite the skill ("try at least two structurally different routes"). The harness fingerprint put every compiled candidate into r1 (similarity at least 0.61) so `Routes tried: r1 ... 1 attempt` is all the facts line can show. Fix: state the position count, e.g. "69 compiled candidates, all in r1" (counts already in `ledger.jsonl` route rows) in the continuation and refusal facts, so a one-route run is visible without any content hint; keep the wording neutral (graph position only).
5. **Failed-turn continuation has the wrong text (LOW).** `rules.ts:202` `continuationPush` begins "The turn ended with text and no tool call." for a turn whose content was empty and `stopReason` `error` (event 146820). Fix: in `arena.ts:1305-1313` on the `failed` path emit a distinct fact ("The last request failed with no response") or skip the custom message.
6. **Lean 180 s timeouts return no signal (LOW-MEDIUM).** Two drafts, 6 minutes of wall time, `compiled:false` with only `Lean timed out after 180 seconds`. Fix: return the elapsed heartbeats if the worker can report them, or the last tactic line reached, or lower the model-lane limit for probes after the first timeout; cite `lean-session.log` lines 20:53:01 and 21:17:53.
7. **`arena_source` handle error is not actionable (LOW).** `arena/campaign.py:533` raises `"<path> does not exist in the pinned project or its dependency roots"`. Fix: when the first path component contains `:` and the prefix is not a known root, retry without the prefix or list valid prefixes (`arklib:` ...) in the error. The same message carries the failing path, which hides the cause.
8. **`lean_local_search` reports `"index":"error"` with stdlib-only hits (LOW).** Both calls (turn 18, one batch) returned index errors; since it is not `isError` the summary shows `tool errors 1` and hides it. Fix: mark the result `isError` or surface the index status in `summary.json` `tools.errors`.
9. **Model slip: `ℱq` for `𝔽q` (LOW).** `Unknown identifier ℱq` in the first 2 probes; the diagnostic could append "similar identifier `𝔽q` is in the statement" via a confusables map in the diagnostic post-processor. 
10. **Run tail cost (LOW).** The finish review at 10.71% forced one filler probe and a 4-minute cold verification; consider a 1e-2 tolerance on `FINISH_ALLOWED_REMAINING_FRACTION` (`budget.ts` near line 312) only if the user wants it; per the stop rule memory this is design, not a bug.

## Evidence index

- Cost ledger: `cost-ledger.jsonl` (309 rows: 97 gate, 97 reserve, 89 settle, 8 `unknown`, 13 discovery, 3 finish, 2 control); unknown ids in `summary.json` `cost.reconciliation.unknown_requests`.
- Events: 5003-5004 (stream cut, retry), 10046 (retry success), 103480 and 166171 (180 s probes), 146794-146845 (outage), 146820 (mislabelled continuation), 192516 (cold verification), 194072-194073 (final stop, settle).
- Session: `session/2026-10-09T14-42-34-185Z_*.jsonl`, 204 rows; footer check done on all 92 tool results.
- `lean-session.log`, `lean-health.json`, `state.json`, `submission.json` (#67, cold verified, 258 tok, 6766 HB).
