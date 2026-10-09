# v6ark Binius fiberwise_dist_lt run study: the "$0.80 vs $0.50" is three unsettled reservations, the real spend was $0.451

Theorem: `Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius` (ArkLib, reference 1463 tok / 15645 HB, 4 toolchains v4.28-v4.31; rates: 1 token = 0.023 pt, 100 HB = 0.213 pt, one lost version = 8.33 pt). Model DeepSeek V4.1 Flash, thinking high, soft cap $0.50, hard cap $3, compaction at 850K.
Run: `runs/pi-budget/v6ark-Binius.BinaryBasefold.fiberwise_dist_lt-deepseek-v4.1-flash-r1/`. Campaign: `runs/analysis/arklib/campaign.log`.
Times are local (IST), minutes are from session start 20:09:10 unless stated. "Settle #N" is the Nth settled request in `cost-ledger.jsonl` (1-83). The trace journal and events count 86 requests because 3 failed attempts sit between settle #59 and #60 (trace request 60-62). Arena candidate numbers are 1-based (original = #1). Read-only study; no Lean, no paid calls.

## TL;DR

- **The soft cap was never crossed.** Settled spend is $0.45118 (83 priced requests, matches Pi's embedded estimate to 1e-8), 9.8% of the $0.50 left at the stop. The campaign figure $0.8021 is `spent + unresolved`, where "unresolved" ($0.3509) is **three reservations of $0.11697 each** that never settled. They belong to the three retry attempts of one hung request (trace request 60-62, 21:07:13-21:09:12, min 58.0-60.0): one stream that was `terminated` after 113 s, then two instant `Connection error.` attempts, then success. Not a single request exceeded $0.0185. A $0.30 last-request overshoot is not possible and did not happen.
- **Why the three count as unresolved:** `packages/arena-pi/extensions/arena.ts:659` treats any attempt whose wire body was recorded (`wireIndex > 0`) as "sent" and writes `kind: "unknown"` (line 661), which keeps the full reservation in `unresolved`. The two `Connection error.` attempts failed 10 ms and 6 ms after the wire record, with no response id: they cannot have been billed. Only the first (a stream with a response id that died mid-generation) may have been billed, at most about $0.012 (508K cached prompt tokens = $0.0015 plus up to ~17K streamed output tokens at the 157 tok/s rate for 113 s = $0.010). Realistic all-call cost is $0.451-$0.463, not $0.802.
- **Soft/hard cap logic behaved as designed.** All 86 gates were `allow` ("estimate fits remaining allowance"); the gate compares estimate to the $3 hard cap minus spent minus unresolved (`budget.ts` `budgetGate`), and unresolved only reduced hard headroom (3.00 to 2.198). The soft-cap figure (`soft_remaining_usd`) uses settled spend only and read $0.154 before and $0.1507 after the incident. The run ended because the model's `arena_finish` was accepted at 9.76% left (`FINISH_ALLOWED_REMAINING_FRACTION = 0.10`), not because the cap tripped.
- **Result:** best verified #46 = 476 tok / 3831 HB, proxy **80.99**, 4/4 versions (tokens -67.5%, heartbeats -75.5%, compat 100). Submission #46 cold-verified. Spend at best: $0.4489 (best was the last candidate, post-best spend $0).
- **Fixes mostly worked:** the budget footer was present in 85 of 85 tool results; finish refusals carried facts only (3 refusals at 18.4%, 11.8%, 10.8% left, confirmed at 9.8%); no compaction (peak context 606,563 tokens, 71% of 850K); 0 "invalid declaration name" errors; Unicode names resolve (`fin_ℓ_steps_lt_ℓ_add_R`, `ℓ_lt_r`); failed drafts carry `compiled:false` and `heartbeat_to_failure` (28 of 30). The facts-only continuation text was never exercised (0 continuations).
- **0 routes credited is a harness limit, not model behavior:** all 45 route events are `source: "text"`, filed 21:43:33-21:56:48, i.e. 3 to 16 minutes **after** the run ended (summary.json written 21:40:33 says `routes: []`). A text fingerprint can never credit a route (`arena/routes.py:20`). The original proof was never filed, so r1 is seeded from the model's first candidate (similarity 0.0, then 0.65-0.96 for the other 44). The sibling Binius run (fold_advances) is also 69/69 text; the two non-Binius ArkLib runs got kernel fingerprints. Kernel extraction fails for this file; the reason is swallowed (`arena/campaign.py:893`).
- **Packet:** 39,951 of 40,000 chars with the whole library section shed and 1 goal kept. Local variables were not shed (47 lines kept, floor 20), because the fit stopped after the library stage. The b410f10 fix is in the code path but was not what decided this packet.
- **What limited the score:** one idea (`fiber-count`, never updated) pursued by 45 micro-refinements of one skeleton. Tokens fell 838 to 476 and heartbeats 9811 to 3831, but the last 12 candidates moved the proxy by +0.9 for $0.05; about 900 HB (896 unattributed in the last profile) are not reachable by proof edits.

## 1. Timeline

| Time (IST) | Min | Event | Evidence |
|---|---|---|---|
| 20:09:10 | 0.0 | run starts, Lean session up (4 slots, shared with another live run: 3 model + 1 background) | `lean-session.log` |
| 20:09:12-20:11:47 | 0-2.6 | v4.31.0 warm: slot 3 66.5 s, slot 2 127.4 s, slot 1 155.7 s; `Session4.lean` header 88.7 s | `lean-session.log` |
| 20:11:59-20:15:13 | 2.8-6.1 | v4.30.0 (44.5 s), v4.29.0 (26.0 s), v4.28.0 (56.0 s) warmed one after another in the background lane | same |
| 20:15:53 | 6.7 | `lean-health.json` finishes: verdict healthy, wall 402.3 s, check times 5.7 / 37.5 / 23.6 / 39.7 s | `lean-health.json` |
| 20:15:54 | 6.9 | **first model request** (settle #1, 18,850 input tokens, 64 KB) | cost-ledger ts 1791557154621 |
| 20:22:14 | 13.1 | first compile result: probe p1 (sorry draft, 411 tok), header `Session11.lean` 11.3 s | trace tool_result |
| 20:24:45 | 15.1 | first fully compiled probe p2 (failed, 8051 HB to failure) | trace |
| 20:26:59 | 17.8 | **first compiled candidate #2**: 838 tok / 9811 HB, est. 60.0 (after settle #12, $0.075) | ledger |
| 21:20:44 | 71.6 | first cold verification (#38) | ledger |
| 21:20:44 (ts 1791561044) | 72.2 | first `arena_finish`: refused (18% left), tool call blocked 170 s | trace request 75 |
| 21:37:59 | 88.8 | last candidate #46 (476 tok / 3831 HB, 80.99) | ledger |
| 21:38:08 | 89.0 | `arena_finish` confirmed (9.76% left); stop `finished` | cost-ledger control row |
| 21:40:34 | 91.4 | cold verification of #46 passes (ledger 21:40:33); session shutdown | ledger, lean-session.log |

Dead time before the model could work: **6.7 minutes (404 s)**, all inside the preflight Lean health gate (4 toolchains, v4.31 header 155.7 s under 2-session contention, then three more sequential warm-ups plus their check compiles). Then 6.3 more minutes until the first compile result (13.1 min): that is model time, requests 1-8 were source and lookup reads (`arena_source` x4, `arena_find` x6, `arena_declarations` x2, $0.0425 by settle #8) and the first 28K-token plan turn (settle #6, 190 s, $0.0185).

Wall split inside the model window (82.2 min, first request to confirm): generation 3652 s (74%, includes the 113 s hung stream), tool execution 1264 s (26%). Of the tool time, **871 s is three refused `arena_finish` calls** (170 s, 439 s, 262 s) that block while the background cold verification runs; ordinary probes took 4-6 s each (Lean model lane: 75 checks, p50 3.9 s, p95 6.0 s, 0 timeouts).

## 2. Spend

### Breakdown (settled, $0.45118)

| Component | USD | Share |
|---|---|---|
| output (452,088 tokens) | 0.2713 | 60.1% |
| uncached input (603,289 tokens) | 0.0905 | 20.1% |
| cache read (29,811,840 tokens) | 0.0894 | 19.8% |
| cache write | 0 | 0 |

- 83 settled requests, all model turns. Compaction requests: 0. Bookkeeping classification in summary.txt ("context 15x$0.0727", "bookkeeping 5x$0.0160") is the harness's own bucket of turns, not extra calls.
- Median turn 3,986 output tokens. 15 turns with >= 8K output carry 48% of output tokens. Largest: settle #6 (28,372 tok, $0.0185), #18 (26,251, $0.0171), #11 (17,152), #10 (17,233), #20 (16,856).
- Per-request estimates (reserve) grew from $0.0486 to $0.1306 while actuals stayed $0.001-$0.0185; the reserve is 20-30x the actual cost. This is harmless for the $3 hard cap but it is what inflates "unresolved".

### Where $0.80 comes from

`$0.8021 = $0.45118 settled + $0.35092 unresolved`. `unresolved` = sum of unmatched reservations in `cost-ledger.jsonl`: the three `kind: "unknown"` rows (`reason: provider_attempt_without_settled_usage`), each `estimate_usd 0.1169733`:

| Trace req | ts (ms) | Elapsed | Result | Cost-ledger |
|---|---|---|---|---|
| 60 (`...tamhgmxa1ho`) | 1791560233422 | 113.1 s | stream `terminated` mid-generation, response id present, partial thinking only | unknown, $0.1170 reserve kept |
| 61 (`...y3mt4vkwaxj`, retry_of 60) | 1791560348645 | 0.05 s | `Connection error.`, no response id | unknown |
| 62 (`...i6fzdwivvwo`, retry_of 61) | 1791560352710 | 0.05 s | `Connection error.` | unknown |
| 63 = settle #60 | 1791560360776 | 24.4 s | success: input 18, cache read 508,288, output 3,127, $0.00340 | settle |

Pi's `auto_retry_start` events (events.jsonl lines 159730, 159738, 159746) show attempt 1/3 "terminated" delay 2 s, 2/3 and 3/3 "Connection error." delays 4 s and 8 s; `auto_retry_end success:true` at line 160620. Total delay burned: 113 s hang + 2+4+8 s backoff + 24 s success = 151 s for one turn.

Settle #60's cache read (508,288) exceeds settle #59's total prompt (502,398) plus its output, so the prefix survived the outage; no cache miss resulted.

### Crossing $0.50

There is no crossing. Settled spend reached $0.4512 at settle #83 and the run stopped. The soft cap gate (`softCapGate`) never tripped; the model's stop came from `arena_finish` being accepted at 9.76% left. The all-call figure only exceeds $0.50 because the $0.351 of reservations is added at the end (it would already read above $0.50 at settle #60 where $0.3493 + $0.351 = $0.700); reservations are never charged, so that sum has no meaning for the cap.

### Finish rule cost

Three refusals (settle #72, #79, #81; trace request 75, 82, 84) held the run at 18.4%, 11.8% and 10.8% left. The 11 requests after the first refusal cost $0.0431 (settle #73-#83) and moved the best from 80.00 (#38, verified at the first refusal) to 80.99 (+0.99). Refusal texts are factual ("Stop refused: $0.41 of $0.5 spent, $0.09 (18%) left. A finish confirm is accepted once 10% or less of the allowance remains. Routes tried: none. Current best ... tokens 65% saved, 11.7 pts left; heartbeats 75% saved, 8.3 pts left.") and carry no advice.

## 3. Did the new fixes behave

| Fix | Observed |
|---|---|
| Budget footer `[arena] ... budget: $X of $Y spent` | present in **85/85** tool results (combined with state line, e.g. `[arena] #39 passes all 4 versions: proxy 78.92 · best verified: #38 proxy 80 (510 tok, 3833 HB) · budget: $0.41 of $0.50 spent · 18% left`). Uses settled spend only (`arena.ts:878`). First: `$0.00 of $0.50` (tool result 2). Last: `$0.45 of $0.50 spent · 10% left` |
| Facts-only finish refusal | yes, 3 refusals (see above); confirm result: `{"phase":"confirmed","stop":true,"best_verified":{"candidate":"#44",...}}` |
| Facts-only continuation | not exercised: `control` row shows `continuations: 0, plateau: 0, no_work_turns: 0, error_streak: 0` |
| Compaction at 850K | did not trigger; peak prompt 606,563 tokens (settle #83), 0 compaction rows, 0 `compaction` events. Growth was ~7.3K tokens/request: 850K would have needed about 33 more requests |
| Routes only from compiled proofs | held: 0 credited. All 45 route events are text fingerprints filed after the run, and the original (reference) was never filed |
| `compiled:false` / `heartbeat_to_failure` on failed drafts | 76 drafts in 55 probe calls: 46 compiled, 30 failed; 28 of 30 carry `heartbeat_to_failure` (8051 HB on the first); the other two are one sorry draft (`contains_sorry:true`, goals reported) and one `compiled:false` without HB-to-failure |
| Unicode declaration names | 0 "Invalid declaration name" hits in 210 diagnostics files and all results; `arena_declarations` found `ℓ_lt_r` and `fin_ℓ_steps_lt_ℓ_add_R`; probes used `Φ`, `𝔽q`, `ℓ` freely |
| Packet local-variable shedding | in code (`arena/context.py:538-539,605-610`) but not the deciding stage here: packet 39,951/40,000 chars, **library section removed entirely**, goals reduced to 1, local variables kept at 47 lines (floor 20). The shed order goes library, then locals, then goals to 1; locals past the floor would have freed ~2-3K chars and kept some of the ranked library lines. The packet was a cached certification (`certify2.log`, 20:06) |

Not exercised or lacking in this run: `arena_find` returned `not_found` with `files_scanned: 0` for four core `Nat.*` names (settle #60), and `arena_declarations` returned `found: null` for 7 of 8 `Nat.*` items (settle #17); the model worked around it with one `mcp__arena_lean__lean_multi_attempt` call. Same known gap as in the v6cov studies, not a regression.

## 4. Model behaviour

- **One idea, never updated.** `arena_idea fiber-count` at settle #8 (12.7 min), status `active`, never revised, no second idea. Ideas without attempts: 0. Edits: 34 structural, 11 local; 90 evaluations (46 fast + 44 auto full), 30 probes flagged failed. All attempts are variants of one skeleton; the route table sees one route.
- **Profile use:** 8 `arena_profile` calls (settle #13, 19, 22, 26, 32, 42, 48, 70). Each one preceded a drop in the dominant block: profiled total 8777 (#2) to 5674 (#4) to 5148 to 4836 to 4123 to 3993 to 3732 to 3037 (#38). Unattributed stays ~900-1030 HB (about 23% of the final 3.9K) and cannot be removed by proof edits.
- **Score trajectory (proxy est., tokens / HB):**

| Candidate | Settle / min / cum $ | Tokens | HB | Proxy |
|---|---|---|---|---|
| #2 first | 12 / 17.8 / 0.075 | 838 | 9811 | 60.00 |
| #3 | 18 / 24.5 / 0.107 | 792 | 7725 | 65.49 |
| #8 | 24 / 30.2 / 0.149 | 699 | 5882 | 71.54 |
| #14 | 31 / 35.9 / 0.189 | 644 | 5049 | 74.57 |
| #20 | 41 / 44.5 / 0.250 | 607 | 4922 | 75.68 |
| #28 | 54 / 54.6 / 0.320 | 598 | 4111 | 77.62 |
| #32 | 62 / 62.2 / 0.359 | 580 | 4103 | 78.04 |
| #35 | 66 / 65.3 / 0.382 | 523 | 3972 | 79.62 |
| #38 | 69 / 67.2 / 0.396 | 510 | 3933 | 80.00 |
| #44 | 78 / 75.7 / 0.438 | 478 | 3842 | 80.92 |
| **#46** | 82 / 88.8 / 0.449 | **476** | **3831** | **80.99** |

  Axis highs: tokens 476 (-67.5%, 22.5 of 33.3 pts), heartbeats 3831 (-75.5%, 25.2 of 33.3), compat 4/4 (33.3). Pts left: tokens 10.8, heartbeats 8.2. Cost per +1 proxy: 60 to 70 cost $0.074; 70 to 78 $0.21; 78 to 81 $0.09 more and it needed 24 more requests.
- **Plateaus and regressions:** #31 (632 tok / 5074 HB, 74.79) and #35 (566 / 4931) were regressions of -3.3 and -3.0 pts from the preceding best (HB spikes), each undone the next turn. #43 (484 tok, 80.79) passed the session full check but **failed cold verification on v4.28.0 with no diagnostics** (`cold_verification` ts 1791561603, 80.9 min, passed v4.28 false); #42, #44, #46, same structure, all cold-passed. This is a flake with no recorded cause (candidate's v4.28 diagnostics file is the same 1.5 KB of warnings as for #44).
- **What limited the score:** (1) the heartbeat floor of ~900 unattributed HB; (2) a single skeleton (tokens fell by 4-30 per refinement in the last 20 candidates); (3) 15 turns >= 8K output tokens spent on analysis rather than probes; (4) no second approach was ever opened, and the stop rule asked for exactly this ("Routes tried: none" in all 3 refusals) but the harness's own route table was empty at that time (section 5).

## 5. Routes: why 0 credited

- `route-queue.jsonl` has 92 lines for 46 unique proofs (each queued twice: once at `arena_probe`, once at candidate evaluation). At summary time (21:40:33) the ledger held **0 route events**; they were filed 21:43:33 to 21:56:48. The `route-worker.lock` is dated 20:09, i.e. a worker started at init and sat on the reference (queued first), blocked in `_room_for_extraction(wait=inf)` / `_yield_to_lean_session` or retrying it (`REFERENCE_TRIES`/`REFERENCE_ROUNDS`, `arena/campaign.py:947-975`). It started producing as soon as the sibling runs ended (21:42:23: MemAvailable 18.8 GB vs 10-13.8 GB during the run). Memory wait is the timing correlate; the log does not record the wait, so this is inferred.
- All 45 events are `source: "text"`; the original proof (`fab3fe1a...`) has no route event, so `arena/campaign.py:1045` (reference "never filed from text") left r1 seeded by the first model candidate `c7199e3d` (`label: text fingerprint, first route`, similarity 0.0). 44 later attempts joined r1 at similarity 0.65-0.96; none opened a second route.
- Credit rule (`arena/routes.py:20, 452`): `credited = new and by_kernel and origin == "model"`; a text-only attempt never opens or earns a route. So even after the worker drained, route depth stays 0 credited / 0 explored, and `summary.json` (`route_progress: 0/0`) was written before any route existed. `runs/pi-budget/v6ark-Binius...fold_advances...` shows the same pattern (69/69 text, first row 20:25:44); the two non-Binius ArkLib runs got kernel fingerprints for their reference. Kernel extraction recompiles a ~1260-line ArkLib prefix and failure details are discarded (`_route_features` returns None on any exception, `arena/campaign.py:893-894`; non-ok `route_features.extract` records, `arena/route_features.py:56-70`, are not persisted).
- Consequence: the model never saw a route table (finish text "Routes tried: none"), and any "route fix" for this row cannot show up in this run's numbers.

## 6. Cache

- Reuse **98.02%** (29.81M read vs 0.60M input tokens), cost savings 96.06%; last ten requests 99.40% / 97.42%. Cache write is 0 for this provider.
- **No full miss:** cacheRead never falls below 90% of the previous request's cacheRead (first request 2,048 then monotonic growth to 606K). Largest uncached inputs are the turns right after the two 26-28K-token thinking turns (settle #7: 29,685; #19: 27,213), because generated tokens re-enter as uncached input. Cache alarms: 0.
- The outage did not break the prefix: settle #60 read 508,288 cached after a 151 s stall.

## 7. Ranked findings and fixes

1. **Over-cap "all-call cost" is an accounting artifact (high, cosmetic but misleading).** Fix in `packages/arena-pi/extensions/arena.ts:659-661`: treat an attempt as unbilled (`kind: "release"`) when `stopReason == error`, the error is a transport error ("Connection error.", "terminated before first byte"), and there is no `response_id` / no streamed bytes; this matches the `costState()` comment at `arena.ts:347-349` that zero-usage transport errors are releases. For a stream that dies after the response id appears (like request 60), keep it as `unknown` but record a bounded charge (cache-read tokens times cache-read price plus streamed output estimate) instead of the 20-30x reserve. In `tools/run_campaign.py:172` and `arena/summary.py:161,518,412` report "settled" and "unsettled attempts (n, upper bound)" separately and do not add them into the headline "all-call cost" that campaign.log compares to the soft cap.
2. **Route worker is starved and the summary is cut before routes exist (high for route metrics).** Make `summary.json` generation drain or wait for the queue (or print "routes pending: 46 queued") in `arena/summary.py` (route table section, ~line 333), and log the extraction failure reason in the route event (`arena/campaign.py:893-894`, add `features.error` to `routes.file_attempt`). Investigate why kernel extraction fails for `Binius.BinaryBasefold` rows (two runs, 114 text events, 0 kernel) while Wick/interleaved rows succeed; the reference never being filed makes the whole row text-only. The 3 retries at `REFERENCE_TRIES=3` with 20 s sleeps and `_room_for_extraction(wait=inf)` hide the failure mode; add a per-run `route-worker.log`.
3. **Packet shed order drops the entire ranked library (medium).** `arena/context.py:605-610`: at 39,951/40,000 chars this packet had no library lines; shed locals past `LOCAL_FLOOR` before the last library lines (about 2-3K chars were available) or shed library lines to a floor of 5-8 first. Evidence: 47 local lines kept, 0 library, 1 goal.
4. **Hung stream with no client timeout (medium).** Request 60 stalled 113 s before `terminated` and cost 151 s including retries; add a first-token / idle timeout (for example 60 s) in the Pi provider call so retry happens sooner and an unsettled reserve is smaller. The retry kept the same prompt and the cache survived.
5. **`arena_finish` blocks up to 439 s on cold verification (low).** Three refusals cost 871 s wall (about 20% of the model window) with no spend. Return the refusal immediately and queue verification in the background, or skip verification when the answer is `refused`.
6. **Cold-check flake (low, needs a log).** #43 failed cold on v4.28.0 with zero diagnostics while identical-structure candidates passed; record the cold compile's exit code / timeout in `cold_verification` (`arena/campaign.py:2203-2206`) so a transient failure can be told apart from a real incompatibility.
7. **Core-name lookup gap (low, known).** `arena_find` `not_found` with `files_scanned: 0` and `arena_declarations` `found: null` for `Nat.*` core names (settle #17, #60); expected to be covered by the existing core-index work.
8. **Reserve estimates 20-30x actual (low).** The estimate path in `budget.ts` (`boundedPayload`) prices the prompt as if uncached at ~$0.15/M; with cacheRead at $0.003/M the reserve could use the previous request's observed cache-read share. Only matters once item 1 is fixed or if the hard cap is lowered.
9. **Model behaviour (informational).** One skeleton, one idea, three refusals, 45 candidates; the proxy gains in the last 24 requests were +3.0 for $0.09. Nothing about routes was shown to the model because the table was empty; the finish text "Routes tried: none" is factual but was produced by the extraction failure, not by the model's choices.
