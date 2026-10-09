# v6ark2 interleaved_affine_gaps_imply_tensor_gaps: 85.14 proxy, $0.459 settled, finished, 0 unresolved reservations

Run: `runs/pi-budget/v6ark2-interleaved_affine_gaps_imply_tensor_gap-deepseek-v4.1-flash-r1/` (campaign `runs/analysis/arklib/campaign2.log`, ran beside the FieldSpecification row until 23:04:21). DeepSeek V4.1 Flash, thinking high, soft cap $0.50, `compact_at_tokens` 850000, ArkLib pin c1712f6, 3 toolchains (v4.31.0 primary, v4.30.0, v4.29.0). Reference 1353 tok / 9198 HB (proxy 33.33); 1 token = 0.0246 pt, 100 HB = 0.362 pt.
Times are local (IST) and minutes from Lean session start (22:07:04, ledger `init`). "req N" is the 0-based N-th reserve row of `cost-ledger.jsonl` (74 reserves, 74 settles); "tN" is the N-th model turn (turn N is req N); "#N" a candidate; "pN" a probe id; "eN" a 0-based line of `events.jsonl`. ISSUES = `docs/ISSUES-harness-v7.md`. Read-only study: no Lean, no paid calls.

## 1. Result

| | value |
|---|---|
| best verified | **#77**, proxy **85.14**: 225 tok (-83.4%, +27.79 pt), 2571 cold HB (-72.0%, +24.02 pt), compat 3/3 (+33.33 pt). `submission.json`: `verified_by: cold compile`, session HB 2572 |
| gain | +51.81 pt over the baseline (33.33). Points still open: tokens 5.5, heartbeats 9.3 |
| per toolchain | compat passed on v4.31.0, v4.30.0, v4.29.0 (cold verification of #77: all three true). HB is measured on v4.31.0 only (the other two report `heartbeats: None`), so the proxy is the same on every version; there is no per-version score |
| per-axis highs | tokens 217 (#56, proxy 83.04), HB 2572 (#77), proxy 85.14 (#77) |
| settled spend | **$0.4590** (91.8% of the cap): output $0.2777 (60.5%, 462,880 tok), uncached input $0.1004 (21.9%, 669K tok), cache read $0.0810 (17.6%, 26.98M tok). `unresolved_usd` 0, `open_reserves` [], `overshoot_usd` 0, reconciliation `balanced` |
| stop | `finished` (control row: `continuations 0, plateau 0, no_work_turns 0, error_streak 0`). Gate refused at 10.08% left (`arena_finish` t70), accepted at 8.2% left (t73) |
| volume | 74 requests, 93 tool results, 0 retries, 0 tool errors; 154 evaluations (77 fast + 77 full), 52 failed probes, 77 candidates (#2-#78), edits 54 structural / 23 local |
| wall | 82.0 min from session up, 76.6 min from the first request (22:12:25) to the last cold verification (23:28:56) |

### First attempt (`v6ark-interleaved...-r1`, died of the outage)
Ran 21:37:16-21:42:22 (5 min). 7 requests completed (settled **$0.0146**): a survey only (9 tool results, `arena_state`/`arena_source`/`arena_find`), 0 probes, 0 candidates, 0 evaluations, no best (the original stands). Then 12 consecutive attempts failed with no content (21:39:32-21:42:22, 2 min 50 s; nine inside Pi's own retry, then three harness attempts with `error_streak` 1, 2, 3 at 21:41:47, 21:42:04, 21:42:22 and backoffs of 2 s and 4 s) and the run stopped `error_loop`. Its summary shows $0.5876 "unresolved" (12 `unknown` rows of about $0.049 each) against $0.0146 settled. Confirms ISSUES #1 and #3. The rerun has none of this: no failed attempt, 0 unresolved.

## 2. v6 fixes: observed behaviour

| fix | observed | verdict |
|---|---|---|
| Unicode names | 15 `arena_source` and 6 `arena_find` calls; `decl:Code.jointProximityNat₂` and `arena_find` of `⋈|`, `splitHalfRowWiseInterleavedWords`, `Fin.snoc_init_self` resolved; 0 "Invalid declaration name" in 93 results. The only `not_found` is a deliberate miss (e10303, a core name). Draft errors containing `unexpected token '⋈|'` (p1-p3, p23) are a model-side precedence slip, not a harness one | works |
| `compiled:false` / `heartbeat_to_failure` | 52 failed probe drafts: 43 `compiled:false` + `heartbeat_to_failure`; 5 Lean timeouts (`compiled:false`, error `Lean timed out after 180 seconds`, no HB); 3 `sorry` skeletons (p11-p13; `scored:false`, `contains_sorry`, goals returned, no `compiled` key); 1 parse-error draft (p23, `compiled:false`, no HB) | works. The 5 timeouts still return nothing about where time went (ISSUES #15) |
| Budget footer | on **93/93** tool results (events) and 93/93 `tool_result` rows of `trace-journal.jsonl`. Starts `$0.00 of $0.50 spent · 99% left`, ends `$0.46 ... 8% left`; the model quotes it from t43 | works. ISSUES #42 (journal lacks footer) **not reproduced** here |
| Facts-only finish / continuation | refusal text (t70): "Stop refused: $0.45 of $0.5 spent, $0.05 (10%) left. A finish confirm is accepted once 10% or less of the allowance remains. Routes tried: r1 (original's route) · 2 attempts · 0 goal states · best proxy 68.38 (#3); r2 (credited) · 73 attempts · 1 goal state · best proxy 84.8 (#63). Current best, saving ... tokens 83% saved, 5.7 pts left; heartbeats 71% saved, 9.7 pts left." Facts only, content-neutral, counts correct (r2 = #4-#76 = 73). Continuation text never fired (`continuations 0`; every turn ended in a tool call) | refusal works; continuation text untested here |
| Routes from compiled proofs only | 78 route events = 78 candidates; the 3 `sorry` skeletons (p11-p13) and all 52 failed probes opened none. **All 78 came from kernel extraction** (`source: kernel`, 0 text fallbacks), unlike the Binius runs (ISSUES #5) | works |
| Route filing vs run end | original filed at **+2.15 min** (22:09:13). Every event was filed before the run ended (last 23:27:23, summary written 23:28+): **0 post-run filings**. But 34 events (#10-#43) landed 62-919 s late: #10 candidate 22:49:18, filed 23:00:53; #11 filed 23:04:37; #12-#13 at 23:04:46-23:05:00; the backlog drained by 23:09:02. Median delay 30 s. The stall ends 16 s after the peer FieldSpecification run finished (23:04:21, share `8 (1 live sessions)` at 23:04:42), which supports the memory-wait suspicion (ISSUES #5 note, `arena/campaign.py:965,1002-1014`; nothing logged) | #5 partly confirmed (stall), partly not (no post-run, no text fallback) |
| Compaction at 850K | **not triggered**. Peak prompt 666,412 tok at req73 (3,628 uncached + 662,784 cached). Growth was 6.7K tok per turn over reqs 49-73, so 850K needed about 27 more turns, about $0.14 more, i.e. past the $0.50 cap. At this cap the DeepSeek threshold is effectively unreachable; no live evidence either way | still unseen live |
| Packet shedding | packet 39,911 of 40,000 chars (89 spare). Sections present: task 2,448; pinned env 476; types 3,229; scope 1,802; reference proof 4,606; profile 3,979; goals 689 (1 goal: the proof is one top-level tactic block, lines 9-177); source-named 3,868 + signature preview 1,720; dependencies 242; **local variables 9,787 chars / 71 lines (24.5%)**; manifest 433. **Absent: "Relevant lemmas from this file (ranked)" and "Imported library lemmas ... (ranked)"**. `_fit` (`arena/context.py:608`) sheds in the order earlier lemmas, goals to 8, library, local variables to a floor of 20, goals to 1, so both ranked sections went to zero while 71 local-variable lines (51 above the floor) survived. The local list ends at `ε` (alphabetical tail intact), so little or none of it was cut. I could not re-render the pre-shed sizes (re-render is blocked here) | ISSUES #16 order unchanged: ranked lemma sections lost entirely, local-variable list kept |
| Packet vs route rule | packet line 5 still says "a draft with `sorry` holes that elaborates is fingerprinted and opens a route" (1 occurrence); the 3 sorry probes opened none | ISSUES #4 live |

## 3. Timeline

| time (min) | event |
|---|---|
| 22:07:04 (0) | Lean session up (4 slots, 2 live sessions sharing: model 3, background 1) |
| 22:09:13 (2.2) | original filed as route r1 (kernel) |
| 22:07:06-22:09:34 | v4.31.0: 3 workers ready at 44.5 s, 70.5 s, 148.3 s; header open (Session1) 116.1 s |
| 22:09:46-22:11:51 (4.7) | v4.30.0 started (slot ready 45.1 s, header 25.4 s), v4.29.0 started (43.3 s, header 28.5 s). **Two v4.31.0 workers were evicted "to make room" (22:10:32, 22:11:51)** and re-opened only at 22:21:03 and 22:23:14 |
| 22:12:23 (5.3) | health gate `healthy`, `wall_seconds` 319.5; check times 5.2 / 30.8 / 32.4 s |
| **22:12:25 (5.35)** | **first model request** (req0, 18,548 uncached tok, $0.0030). Dead time before it: 321 s (ISSUES #13: here 3 toolchains, 5.3 min against 6.7 min with 4). The primary version had a worker at 22:07:50 and its first header open finished 22:09:02, so about 3 min could have been saved by starting once v4.31.0 was ready |
| 22:21:03 (14.0) | first probe (3 drafts, 24 s) with the run's only idea `i1` filed inline |
| 22:20:32-22:21:52 | v4.30.0 / v4.29.0 servers closed (idle 600 s) |
| 22:28:47, 22:33:52 | two consecutive 180 s probe timeouts (t16, t18) |
| **22:40:03 (33.0)** | **first compile**: #2, 532 tok / 5284 HB, proxy 67.74 (req24 result; settled $0.1337; 27.6 min after the first request, 24 requests, 13 failed or skeleton probes first). The other two versions had to be re-opened (headers 21.5, 35.9, 45.0 s at 22:40:28-22:42:08); full check came **22:42:15, 129 s later** |
| 22:42:49 (35.8) | r2 opened by #4 (route credited) |
| 22:57:16 (50.2) | #33 81.36 ($0.236) |
| 23:16:46 (69.7) | #63 84.80 ($0.397) |
| **23:27:04 (80.0)** | **best #77 85.14** (full eval; candidate recorded 23:26:48; settled $0.4523) |
| 23:24:55-23:26:36 | `arena_finish` t70 refused after **101.1 s** (cold verification of #63 ran inside the refused call, `cold_verification` row 23:26:36) |
| 23:27:25-23:28:56 | `arena_finish` t73 confirmed after **91.3 s** (cold verification of #77, 2571 HB) |
| 23:29:00 (81.9) | session shutdown |

`arena_finish` blocking (ISSUES #12): 192.4 s in two calls, 4.2% of the run wall, and the first 101 s verified a candidate that was beaten two minutes later. Confirmed, smaller than in fiberwise (871 s). Tool time overall: probes 1,032 s (17.2 min, 22.5% of the 76.6 min), of which 720 s were four 180 s timeouts; `lean_multi_attempt` 355 s summed (about 4.3 min of wall, calls run in pairs); finish 192 s. Model generation and queueing is the remaining ~52 min.

## 4. Model behaviour

**Shape.** 74 turns, 462,880 output tokens; reasoning 1.07M chars, tool-call arguments 0.21M, tool results 0.49M (probe results 225K = 46%, sources 123K, multi_attempt 49K, profiles 39K). About 59% of the final context is replayed reasoning (ISSUES #11 confirmed); probe results are never trimmed (#10). Largest turns: req9 41,163 out ($0.0282, 6.1% of spend, the survey-to-first-draft turn), req40 23,989, req8 18,593.

**Ideas and routes.** One idea `i1`, created inline on the first probe (0 `arena_idea` calls), never updated or closed (the packet tells the model to update status with a reason; ISSUES #32). All 131 drafts (48 probe calls, 79 compile records of which 2 cache hits, 52 failures) carry it. Routes: r1 holds the original plus #2, #3; r2 holds #4-#78 (75 attempts, 1 goal state new to its route, stale streak 74). The model wrote that it should try a "structurally different route" (t40, t45, t56, t66; t56: "spend the remaining budget on a couple of 'different route' attempts (per the instructions ...), then finish") and never did: every candidate keeps one skeleton (kernel similarity 0.54-0.98 to r2's members).

**The r1/r2 split is a threshold artefact (NEW).** #3 and #4 are both direct edits of #2 and differ from each other by **one line** (text similarity 0.994; `arena` proofs `#3` vs `#4`). Kernel similarity to r1 was 0.514 for #3 (joins r1) and 0.495 for #4 (opens r2) against `SAME_ROUTE = 0.5` (`arena/routes.py:34`). So "1 credited / 2 explored routes" in the summary, the refusal text and the campaign report ("route depth credited/explored 1/1 / 2/2") describe one proof family sliced at a noise threshold.

**Lean MCP use (`lean_multi_attempt`, ISSUES #25a).** 10 `lean_multi_attempt` (5 turns: t14, t15, t17, t23, t29; 5 of the 10 before the first score), 3 `lean_goal`, 1 `lean_diagnostic_messages`. All 14 calls sit in turns 13-29; turns 13-23 (11 turns, the stretch before #2 that debugged the first draft) cost **$0.0448 = 9.8% of spend**, 8 of them issued MCP calls; MCP-issuing turns alone $0.0267 (5.8%). The MCP result text is 56.4K chars (about 19.5K tok, avg 4.9K per multi_attempt) kept untrimmed for the rest of the run, roughly $0.006 of extra input and cache-read cost (1.3%). So far smaller than FieldSpecification's 20%. Visibility: `summary.json` `tools.calls` now lists the 10 calls, but `summary.txt` does not, and neither attributes their cost or time (#25a partly stale).

**Profile use.** 4 `arena_profile` calls (t26 on #2, t31 on #9, t52 on #49, t60 on #63), 4-7 s each. HB path: 5284 (#2) -> 3.3K at #33 (t39, 22:57) after the first two profiles, -> 3125 (#54) after the third, 2666 (#63) at t59 just before the fourth, 2572 (#77). Productive early, thin late.

**Multi-error drafts (ISSUES #9).** Of 44 failing non-timeout drafts, 29 returned exactly 1 error, 9 returned 2, 6 returned 3 (the 3-error ones are the first drafts p1-p6 and p23). 16 of the 29 single-error and 5 of the 9 two-error drafts came from t41 on, when the model was fixing one error per turn. Confirmed, milder than FieldSpecification.

**Probe batches wait for the slowest draft (NEW, variant of #15).** A probe call returns once, after its last draft. At t30 (#7, #8, #9 compiled in seconds, p22 timed out) the call returned after 180 s; at t64 (#69 compiled, p50 timed out) the same. Four 180 s calls in all: t16 and t18 (two in a row, 6 min, both before the first compile), t30, t64 = 12.0 min, 15.7% of the run. Results of finished drafts could have come back at once.

**Score trajectory** (best verified so far; settled $ at the event):

| candidate | time (min) | settled $ | tok | HB | proxy |
|---|---|---|---|---|---|
| #1 baseline | 0 | 0 | 1353 | 9198 | 33.33 |
| #2 first compile | 35.2 (full) | 0.147 | 532 | 5284 | 67.74 |
| #10 | 42.4 | 0.175 | 410 | 4836 | 72.37 |
| #18 | 43.8 | 0.187 | 403 | 3877 | 76.02 |
| #33 | 50.2 | 0.236 | 269 | 3315 | 81.36 |
| #41 | 59.5 | 0.310 | 234 | 3282 | 82.34 |
| #54 | 65.3 | 0.359 | 222 | 3125 | 83.21 |
| #63 | 69.7 | 0.397 | 225 | 2666 | 84.80 |
| #77 best | 80.0 | 0.452 | 225 | 2572 | 85.14 |

92.7% of the gain (48.03 of 51.81 pt) was in the first 51% of the spend ($0.236 -> #33). The last $0.223 added +3.78; the last $0.062 (after #63) added +0.34. No candidate failed a version: all 77 full evaluations passed 3/3 (compat stayed 100%).

**What limited the score.** Heartbeats: the profile of #63 attributes 1,852 of 2,666 HB; 814 are unattributed and the statement alone floors at 698 HB, so about 30% of the final HB is a floor the proof cannot touch. One span (proof lines 16-18) carries 857 HB (32%) and did not move across #49 -> #63 (956 -> 857). Tokens: 225 (best axis value 217 at #56); from #56 to #78 the token count stays within 217-234. From #64 on, 15 variants scored 82.78-85.14.

**Post-best spend and finish-gate reasoning (ISSUES #8, #44).** Post-best (after #77): $0.0067 over 2 requests (see finding 8 for the summary's "1 requests"). Post-#63 (reqs 60-73): $0.0624, 14 requests, +0.34 pt. The model first says it must "spend down to 10% ($0.05) before finishing" at **t43 ($0.2805)**; "finish" appears in the reasoning of 23 turns, "10%" in 20 (t43-t73), "harmless/gaming/waste" about the extra probes in 9 (t40, 57, 58, 64, 65, 66, 69, 71, 72). Examples: t66 "Let me do one final probe ... then finish", t68 "Let me do a final probe with 2 drafts that are safe (won't beat #63 but will spend)". At t70 it called `arena_finish` at $0.4496 (10.08% left), got "$0.05 (10%) left ... accepted once 10% or less" **as a refusal**, and spent t71-t72 ($0.0067) working out that "10%" meant 10.08%. Whether the spend-down is intended (the owner's call, ISSUES #8), the gate's displayed rounding costs the model attention (#44 confirmed live).

**Duplicates (ISSUES #45).** The same draft was submitted twice in one batch twice (t34 #19, t54 #55); both repeats were served `cached:true`, so no Lean time was lost (mitigated), only model tokens.

## 5. Cost

| item | value |
|---|---|
| components | output $0.2777 / uncached input $0.1004 / cache read $0.0810 / cache write 0 |
| by turn type | compile 50 req $0.3583; context 21 req $0.0927; bookkeeping 3 req $0.0080 (1.7%) |
| cache | 97.6% reuse over the run, 99.4% over the last ten requests; savings 95.6%; 0 alarms |
| full misses | none: after req0 (2,048 of 20,596 prompt tokens cached) no request had more than 35% uncached prompt (largest uncached input: req10 44K after the long think, req41 26K). The `cacheRead == 0` alarm gap (ISSUES #23) was not exercised |
| growth | prompt 20.6K (req0) -> 100K (req10) -> 0.5M (req49) -> 0.666M (req73); $0.003-0.005 per request at the end |
| where the money went | surveying (req0-9) $0.0609 (13%); before the first score (req0-24) $0.1337 (29%); reqs 25-49 $0.19; reqs 50-73 $0.14 |
| reservations | 74 reserves, 74 settles; **0 unknown, 0 release, 0 open**. Reserve estimates ran $0.0485 -> $0.1402 (median 17x the actual settle, `bound_violation` never) but all settled, so none leaked into `unresolved_usd`. The phantom-reservation problem (ISSUES #1) needs a failed attempt; this run had none |
| campaign report | `campaign2.log` shows "all-call cost $1.0269" for the 2 rows: $0.4590 + $0.5679 (FieldSpecification $0.4521 settled + $0.1158 unresolved), real settled $0.9111. The mislabel (ISSUES #2) is still in the campaign output |

## 6. Ranked findings

NEW (this run):

1. **Route split is a threshold artefact** (P2). `SAME_ROUTE = 0.5` at `arena/routes.py:34`: #3 (kernel similarity 0.514 to r1) and #4 (0.495) are one line apart in text (0.994) yet land on r1 and r2; r2 is then "credited" and holds 75 of 77 attempts. "1 credited / 2 explored routes" and the finish-refusal route lines overstate route diversity. Fix idea: judge route identity on more than the kernel-constant overlap (e.g. also require the text/skeleton to differ) or report credit only when a fingerprint differs by a margin, not a hair.
2. **A probe call returns only when its slowest draft does** (P2). Two of the four 180 s timeouts (t30, t64) held up 3 and 1 already-compiled drafts (up to 180 s each, 360 s total). Return finished drafts' results as they come, or give a lower per-draft timeout when siblings finished. Related to #15 (which covers the timeout payload and the slow next probe); 2 consecutive timeouts before the first compile (t16, t18) cost 6 min of the 33 to first compile.
3. **Warm-up evictions and idle-close slow the first cross-version result** (P3, probable). `lean-session.log`: two warmed v4.31.0 workers evicted at 22:10:32 and 22:11:51 and re-opened 22:21:03 and 22:23:14 (the first probes of 3 drafts took 24-25 s, later ones 4-9 s with 3 workers); v4.30.0/v4.29.0 closed idle at 22:20:32/22:21:52, so #2's other-version check took 129 s (22:40:06 -> 22:42:15) with 45 s and 36 s header re-opens. Keep the extra versions alive while no candidate exists, or do not evict model-lane slots for background warm-up.
4. **The 850K compaction threshold is out of reach at a $0.50 cap** (P3, observation): 666K at 74 turns; 850K needs about 100 turns and $0.6. The `lrx` bypass path stays unobserved live; test it in a lab run rather than waiting for a campaign row.
5. **Packet drops both ranked-lemma sections but keeps 9.8K chars of local variables** (P2; #16 unchanged). Shed order `arena/context.py:608` removes the earlier-lemma and library sections to zero before any local-variable line goes below the floor of 20 (here 71 kept, 24.5% of the packet, vs 0 ranked lemmas). Suggest keeping a floor of lines for each ranked section too.
6. **"10%" shown on a refusal** (#44 confirmed with cost): refusal at 10.08% prints "(10%) left ... accepted once 10% or less"; the model spent 2 more requests ($0.0067) and the reasoning of t71-t72 to resolve it. Print one decimal (`arena.ts:1131` area).
7. **A refused `arena_finish` runs the cold verification** (#12 confirmed with numbers): 101.1 s on the refusal (verifying #63, superseded 2 min later), then 91.3 s again for #77. Refuse before verifying.
8. **Summary "post-best" mixes two clocks** (P3): `arena/summary.py:398-403` takes spend from settle timestamps after `best_at` (the async full-evaluation time, 23:27:04) but requests from reserve timestamps, giving "$0.0067 over 1 requests" for 2 settled requests (req72 reserved 23:26:52, settled after the full eval). Also `best_at` is the full-evaluation time, not the candidate record time.
9. **Idea bookkeeping**: one idea, created inline by the first probe, never updated; the instruction to update status with a reason was not followed in 74 turns (relates to #32).

Confirmed existing: #1/#2 (reservations: none leaked here; first attempt $0.5876 phantom; campaign "all-call" $1.0269 vs $0.9111 settled), #3 (first attempt, `error_loop` after a 2 min 50 s outage), #4 (packet clause live), #5 (all kernel extraction, original at 2.15 min, no post-run filing; stall of 62-919 s on 34 events coinciding with the peer run's end, `arena/campaign.py:965,1002-1014`), #8 (spend-down from t43, 23 turns), #9 (29/44 single-error), #10/#11 (probe results 46% of result chars; reasoning about 59% of context), #12, #13 (321 s, 3 toolchains), #15 (4 timeouts = 12 min, no payload), #16, #25a (partly stale: counted in `summary.json` `tools.calls`, no cost or time attribution), #44.

Verified fixed and not reopened: Unicode names (0 errors), budget footer (93/93), facts-only refusal, `compiled:false`/`heartbeat_to_failure` (43/43 with HB; the 9 without are 5 timeouts, 3 skeletons, 1 parse error), routes from compiled proofs only (0 opened by 55 non-compiled drafts), the ledger-vs-Pi reconciliation (`gap_usd` 0). Not reproduced: #42 (journal has the footer on 93/93). Mitigated: #45 (duplicates served from cache). Not exercised: continuation text (0 continuations), compaction (never reached), #23 (no full miss).
