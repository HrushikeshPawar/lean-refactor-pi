# v6ark2 FieldSpecification `ι_timeOrderF_superCommuteF_eq_time`: 75.58 proxy (v6cov 44.73), $0.452 settled, finished

Run: `runs/pi-budget/v6ark2-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1/`. DeepSeek V4.1 Flash, thinking high, soft cap $0.50, `compact_at_tokens` 850000, one toolchain (physlib v4.32.0). Reference 1217 tok / 42,225 HB; 1 token = 0.027 pt, 100 HB = 0.079 pt.
Times are minutes from Lean session start (22:07:04 IST, ledger `init`). "req N" is the 0-based N-th reserve row of `cost-ledger.jsonl` (91 reserves, 90 settles); "#N" is a candidate number; "pN" is a probe id. Read-only study: no Lean, no paid calls. ISSUES = `docs/ISSUES-harness-v7.md`.

## 1. Result

| | v6cov (old code) | v6ark2 |
|---|---|---|
| best verified | #2, 44.73 | **#33, 75.58** (cold-verified 10,463 HB, session 10,461) |
| tokens | 1267 (-4.1%, contributes -1.4) | **590 (-51.5%, +17.17)** |
| heartbeats | 26,059 (-38.3%, +12.8) | **10,461 (-75.2%, +25.08)** |
| compat | 1/1 (+33.33) | 1/1 (+33.33) |
| settled spend | $0.519 (incl. a $0.067 compaction) | **$0.4521** (90.4% of cap), `overshoot_usd` 0 |
| scored candidates | 1 compiled in 31 drafts | **33 compiled of 58 drafts** (25 failed, 2 `sorry` skeletons) |
| stop | finished, 8.2% left | `finished` (confirmed at 9.6% left), control row `continuations 0, no_work_turns 0` |

Gain +30.85 points. Both axes moved; v6cov never got the token axis above zero. Settled spend by component: output $0.2637 (58%, 439K tokens), uncached input $0.0965 (21%, 644K), cache read $0.0919 (20%, 30.6M). The summary prints `settled` and `unresolved` separately ($0.4521 + $0.1158); the unresolved part is not spend (section 5).

## 2. Before/after on each v6 fix

| fix | v6cov | v6ark2 | verdict |
|---|---|---|---|
| Unicode names (`ι_*`) | 5 `Invalid declaration name` | **0**. `arena_declarations` found `...ι_commute_fieldOpFreeAlgebra_superCommuteF_ofCrAnOpF_ofCrAnOpF` (req 48 tool result, 29.3 min); `arena_find` with `ι_*` queries returned the `ι_*` declarations (5, 1, 1, 8 matches). Only tool errors: 2 (an out-of-range `arena_source` line range, a `STATEMENT_MODIFIED` on `arena_evaluate`) | verified |
| `compiled:false` + `heartbeat_to_failure` | absent; a failing draft's HB looked like a score | present on **25/25** failing drafts (p1, p4-p27); the 2 `sorry` skeletons (p2, p3) carry `contains_sorry` and goals instead | verified |
| budget footer | none | `[arena] ... budget: $x of $0.50 spent · N% left` on **96/96** model-visible results (events `tool_execution_end`). The trace journal stores MCP results before the hook, so a journal-only count shows 78/96. | verified |
| facts-only finish texts | refusal at 50% left | req 82 (53.2 min, 17.2% left): refused, text = spend, headroom, "accepted once 10% or less remains", routes tried, per-axis points left. req 88 (56.8 min, 10.7%): refused. req 90 (57.2 min, 9.6%): confirmed. No advice text. No continuation text occurred (0 continuations); the one failed request was retried inside Pi (`auto_retry_start`, `delayMs` 2000, `success` true), so ISSUES #26 was not exercised. | verified; but the route facts inside the refusals were stale (section 6, #5) |
| routes from compiled proofs only | n/a | 34 route events for 34 candidates (#1 + 33 compiled). The 2 `sorry` probes and 25 failing probes opened none. | verified |
| route filing time | n/a | #1 (original) filed at **2.8 min**, source `kernel` (ISSUES #5 said it was never filed). #2-#18 filed within 0-2.6 min of their evaluation. **#19-#34 (16 of 34) filed at 57.6-60.4 min, after the run ended (57.2 min) and after `summary.json`**; `ledger.jsonl` was still being written at 23:07, three minutes after the 23:04 summary | partial; ISSUES #5 still open |
| compaction at 850K | 1 compaction at 505K | **not triggered**: peak context 644,308 tokens (req 90), 75.8% of 850K | "still to be seen live" stays open |
| packet shedding | n/a | packet 36,872 chars < 40,000: nothing shed (library and local-variable sections both present). Not exercised. | untested here |

## 3. Timeline

| min | $ cum | event |
|---|---|---|
| 0 | 0 | session up (shared with another live run: `share 4 (2 live sessions): model 3, background 1`). Slots ready in 4.6 s, 10.9 s and 78.5 s (v6cov: 44-62 s). Health gate `healthy` after 86.5 s wall. |
| 1.5 | 0.003 | first model request (req 0), 89 s after session start. |
| 1.5-7.0 | 0.043 | survey: 12 `arena_source`, 11 `arena_find`, 2 `arena_declarations`. p1 (3.1 min) failed: a declaration defined after the target is not in scope (`Unknown identifier`, 308 HB to failure). p3 (7.0 min) `sorry` skeleton. |
| 7.8-19.2 | 0.145 | 18 `lean_multi_attempt` calls (tactic snippets at a line of the probe-materialized file): 20 requests, $0.089, 187K chars of results. No scored candidate is produced by that tool. |
| 20.2 | 0.178 | p4: first full draft, failed (2 errors, 20,388 HB to failure). |
| **21.2** | **0.185** | **#2 compiled: 54.73** (1058 tok, 20,638 HB). 41% of the final spend had gone before the first score (v6cov: 20.5 min, $0.135). |
| 24.6-32.4 | 0.185-0.259 | #3-#11 (57.34 to 62.07), 5 profiles (arena_profile at 25.1, 26.1, 32.8, 35.2, 42.5 min; 19,925 HB falling to 11,620 HB). |
| 34.8 | 0.259 | req 54 (43K chars of reasoning, 16.9K output tokens): #12 = 67.96 (753 tok). The one big jump (+5.9). |
| 40.6 | 0.311 | #17 72.23. Req 63: stream terminated after 88 s, no usage (section 5). |
| 43.1 | 0.328 | #18 73.29 (643 tok, 11,529 HB), opens route r3. |
| 45.8-51.1 | 0.348-0.400 | #19-#27 plateau 73.9-74.9. |
| 51.8 | 0.406 | #28 75.16. |
| 53.2 | 0.411 | `arena_finish` 1: refused at 17.2%; cold verification of #28 (12 s). |
| **56.4** | **0.447** | **#33 75.58, best.** |
| 56.8 | 0.450 | `arena_finish` 2: refused at 10.7%; cold verification of #33 (13 s). |
| 57.1 | 0.452 | #34 (75.54, worse), req 89-90. Finish 3 at 57.2 min: confirmed. |

Wall 55.7 min from first request. Model generation was 3,022 s (90.4%); the dropped stream cost 88 s; tools about 230 s. Lean: 60 model-lane checks, p50 1.8 s, p95 4.0 s, 0 timeouts, cold path 0 (probe calls 1-9 s; `arena_find` 3-6 s). Time blocked in `arena_finish`: 11.7 + 13.1 + 0.2 = **25 s** in total (cold verification ran warm; one toolchain). Compare fiberwise: 871 s over 3 refusals, so ISSUES #12 did not trigger here. Background worker: closed idle at 17.8 min, reopened at 21.2 min (header 7.6 s).

## 4. Model behaviour

- **Ideas and routes.** One idea only, `i1` ("Reuse the later WickAlgebra-level lemma ... via ι/map_mul rewriting"), status `active`, 60 attempts (all drafts credited to it). Its approach failed at p1 (3.1 min) and the model never recorded another idea although the work changed completely, so the idea record does not describe the proof that scored. Routes: r1 (original, 0 attempts), r2 (51 constants differ from r1; #2-#17, 16 attempts, best 72.23 at #17), r3 (70 constants differ from r1; first member #18 at 43.1 min, 17 members by the end, best 75.58). The model saw none of the route state except in finish refusals.
- **Profile use.** 5 `arena_profile` calls (about $0.019 in the requests that issued them). The model used each one to pick the next edit: line 47 final `rw` (2,544 HB), four near-identical simp calls (about 970 HB each), per-simp overhead about 500 HB, the key statements. Req 54 and req 66 reasoning quote profile lines directly; #4 cut 3.4K HB and #12 cut 168 tokens in the turns after a profile.
- **Multi-error drafts (ISSUES #9).** 12 of 25 failing drafts had one error, 13 had two to seven (p6: 7, p10: 6). The p18-p27 micro-variants of the best candidate each failed with one error late in the proof (HB to failure 8.2K-11.3K of about 11K), so a draft was refuted by its first failing tactic and the rest was not checked. The model hedged by sending two drafts per call in 17 of 43 `arena_probe` calls, with no more than one error found per draft. p13/p14 failed with identical errors at the same 1,878 HB (a twin draft). Existing #9; not worse than v6cov because most drafts here were one-line variants of a compiled proof.
- **Score trajectory.** 54.73 (#2) to 62.07 (#11) in 11 min; 67.96 at #12; 72.23 at #17; 73.29 at #18; then 74.05 to 75.58 over 11.7 min and $0.104 for +1.53 points. Edits: 23 structural, 10 local.
- **What limited the score.** Not the tools: the token axis has 16.0 points left (590 of 1217) and heartbeats 8.3. The profile at #18 shows the cost sitting in one rewrite of about 2.4K HB plus two statement blocks (about 700 and about 1,700 HB). Each later variant traded tokens for heartbeats (#24 vs #23: +7 tok, -203 HB).
- **Post-best spend.** $0.0091 over 3 requests (req 88-90): one probe (#34, 75.54), two finish turns. Req 89 reasoning says it will "do one tiny probe ... to cross the threshold" to reach 10% left (ISSUES #8). 19 of 91 turns' reasoning mention spending down to the gate; none says "gaming".
- **Lineage by text.** Of 33 candidates, 10 have a labelled parent that is not the closest candidate by text (#8, #11, #15, #16, #17, #20, #21, #27, #30, #31). Examples: #16 is labelled child of #14 (19 differing lines) and is 3 lines from #15; #8 is labelled child of #7 (37 lines, 57.07) and is 20 lines from #6 (60.5).

## 5. Cost

- 91 requests: compile 48 ($0.2794), context 36 ($0.1541), bookkeeping 4 ($0.0118), rejected 2 ($0.0069); bookkeeping plus rejected 4.1%. Per-request cost $0.001-0.0132 (median about $0.005). Largest four turns: req 28 (19.1K output tokens, 128 s, $0.0132), 54 (16.9K, 114 s), 47 (14.7K, 97 s), 29 (14.3K, 98 s): 14.8% of output tokens, $0.043.
- By the tool the turn issued: `arena_probe` 43 turns $0.261 (58%); `lean_multi_attempt` 18 turns $0.089 (20%); `arena_find` 7 $0.030; `arena_source` 7 $0.022; `arena_profile` 5 $0.019; finish 3 $0.009.
- Context: tool-result text 496K chars, tool-call arguments 300K, replayed reasoning 941K chars in the transcript (about 54%, ISSUES #11). `lean_multi_attempt` results were 187K chars (38% of all tool-result bytes), never trimmed (`trim.ts:32` only compacts diagnostics); ISSUES #10.
- Cache: reuse 97.9% (30.6M read, 644K uncached), savings 96.0%, last ten 99.3%; alarms 0. Reqs 0-5 and 13, 14, 17, 29 were below 90% only because the uncached part was a large new tool result (req 0: 11%, the first request). **No full miss after the first request** (every later request read at least 75%). Req 64, the retry, had 2 uncached input tokens and 501,632 cache read.
- **Unsettled reservation (1, not spend).** Req 63 (id `1791566263272-ymd4q29yj4`, 40.6 min): the stream was cut after 88 s (`stop_reason: error`, `error_message: terminated`, no usage, 5.5K chars of reasoning). Pi retried at once (`auto_retry`, `context_edit` removed the failed turn). The ledger kept the full worst-case reservation, **$0.1158**, as `unknown / provider_attempt_without_settled_usage`; it was never released. A real bill would be at most about $0.003-0.01 (497K mostly cached tokens plus under 2K output). The retry cost $0.0028. It does not touch the soft cap (soft remaining uses settled spend), but it counted against the hard gate (hard remaining 2.689 to 2.573). ISSUES #1/#2: confirmed; this run has exactly one such row, so "cost $0.452 + $0.116 unresolved" must not be quoted as spend.
- Reserve estimates were $0.048 (req 0) to $0.136 (req 90) against $0.001-0.013 real: 10-30x.

## 6. Ranked findings

**Existing items confirmed or sharpened**

1. **#5 (routes late), new evidence, P1.** 16 of 34 route events filed 0.4-3.2 min after the run ended; the stall began after #18's route (filed 45.7 min) and lasted about 12 min, then the backlog drained at about 10 s per proof. Kernel extraction works here (`source: kernel`), so the Binius extraction failure is not the only cause. Likely cause: the worker waits in `_room_for_extraction(wait=inf)` (`arena/campaign.py:965`, `:1002-1014`) or `_yield_to_lean_session` (`:964`, `:992-999`) while the other live run holds memory; nothing is logged. **Consequence, the model was told something false:** both finish refusals (53.2 and 56.8 min; texts built from `portfolio.routes`, `arena.ts:1138-1142`) say "r3 (credited) · 1 attempt" when 11 and then 15 attempts had already been assigned to r3 by text; `summary.json` ends with r3 = 1 attempt, r2 stale streak 15. Fix as in #5, plus show "N attempts pending extraction" in the finish text.
2. **#4 (packet contradicts route rule), confirmed live.** `packet.txt` line 5 (from `arena/context.py:637`): "a draft with `sorry` holes that elaborates is fingerprinted and opens a route". Here 2 `sorry` probes opened no route, so the model is told the opposite of what happens.
3. **#1 and #2 (reservations), confirmed.** One unreleased reservation, $0.1158, from a stream cut with no usage (section 5). The summary line and `cost.json` separate it; check the campaign report and package provenance for the combined figure.
4. **#5a (wrong parent labels), confirmed:** 10/33 candidates (30%), all in batches or after batches (section 4).
5. **#8 (finish gate), mild.** 19 turns of reasoning think about the gate; req 89 plans a probe "to cross the threshold". The last 3 requests cost $0.0091 and scored 0 (#34 lower). Cost was small because the gate opened at 10.7% to 9.6%.
6. **#9 (first error only), confirmed;** 13 of 25 failing drafts had several errors, 12 had one that hid the rest of the proof. Mitigated here because the model worked by one-line variants.
7. **#10 (probe/tool results not trimmed):** `lean_multi_attempt` is the largest single source of tool-result bytes (187K chars, 18 calls, 4.5-19K each).
8. **#11 (replayed reasoning, about 54% of transcript), #32 (idea credit per call):** one idea `i1` covers 60 attempts though its approach failed at p1; **#35 (reasoning lost on a cut turn):** the 5.5K chars of req 63 were dropped and re-derived (req 64: 6.4K chars).
9. **#12, #13, #16, #26, #34:** not triggered (finish blocked 25 s total; Lean warm-up 86 s; packet under the limit; no continuation text; no compaction).

**NEW (not in ISSUES)**

10. **P2, the lean_multi_attempt path is outside the scoring harness.** 18 calls and $0.089 (20% of spend, 20 of the first 41 requests, 7.8-19.2 min) before the first scored draft, producing no candidates, scores, routes or ledger rows. It worked (the model got from nothing to the first compile in one probe), but the cost and the content are invisible to `summary.json`. Suggest: count these calls in the summary (calls, bytes, cost), and apply the same trimming as probe results (`trim.ts:32`).
11. **P3, trace journal and model view differ for MCP tools.** `trace-journal.jsonl` `tool_result` rows for `mcp__arena_lean__*` lack the budget footer that the model saw (journal 78/96 with a footer, events 96/96). Any audit that uses the journal as "what the model saw" undercounts. Probably the journal records MCP results before the `tool_result` handler at `arena.ts:866-885` appends the footer (not checked in code).
12. **P3, `arena_evaluate` with `candidate` and a body proof.** Req 43 (25.4 min): `arena_evaluate {candidate:"#3", proof:<body only>}` returned `STATEMENT_MODIFIED ... got ' refine Submodule.span_induction'` (`arena/engine.py:83`) and the note "#3 was treated as the parent of the proof" (`rules.ts:22`). The error is accurate, but the model wanted the score of #3, which it already had. A turn ($0.004) lost; suggest the error name the form that works ("pass the full statement, or omit `proof`").
13. **P3, the finish refusal text says "(11%)" at 10.7% and "10% or less"** while the gate compares the unrounded fraction (`arena.ts:1131`, `budget.ts:318-321`): the model saw 11% left, was refused, and read it as 1 point away; it spent a probe to cross. Show the exact fraction (10.7%) or round the gate the same way.
14. **P3, 17 of 43 `arena_probe` calls sent two drafts, but one pair (p13, p14) was identical in outcome** (same errors at the same 1,878 HB). No duplicate-draft check inside a batch. Minor.

## Facts for the v6 sign-off

All v6 fixes checked here worked: 0 Unicode errors, `compiled:false` on 25/25, footer 96/96, facts-only finish texts, routes from compiled proofs only, original proof filed at 2.8 min, finish blocked only 25 s. Still open: ISSUES #5 (late routes, with false route counts in finish texts), #4 (packet text), #1/#2 (one unsettled reservation, $0.1158), 850K compaction not yet seen live.
