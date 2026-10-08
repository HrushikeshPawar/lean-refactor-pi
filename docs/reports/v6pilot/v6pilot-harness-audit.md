# v6 pilot harness audit (9 runs)

Runs: runs/pi-budget/v6pilot-*-r1. Method: cost-ledger.jsonl, Langfuse via arena.traces.list_observations, summary/events. Read-only.
Timestamps local (UTC+5:30) unless stated.

## 1. Cost integrity

| run (theorem/model) | settled | requests (ledger) | Langfuse gens | LF cost | orphan reserves | gate refusals | overshoot |
|---|---|---|---|---|---|---|---|
| Core DS | 0.4601 | 67 | 65 (2 zero-output) | 0.4601 | 0 | 0 | 0 |
| Core Luna | 0.1662 | 104 | 104 | 0.1662 | 0 | 0 | 0 |
| Core Qwen | 0.4535 | 88 | 86 | 0.4324 | 0 | 0 | 0 |
| CSLib DS | 0.4551 | 78 | 44 | 0.2844 | 1 ($0.0457 est) | 0 | 0 |
| CSLib Luna | 0.4575 | 151 | 74 | 0.1652 | 2 (0.0216, 0.0798) | 0 | 0 |
| CSLib Qwen | 0.0913 | 19 | 10 | 0.0533 | 1 (0.041, killed) | 0 | 0 |
| PhysLib DS | 0.4614 | 88 | 87 | 0.4614 | 1 (0.100) | 0 | 0 |
| PhysLib Luna | 0.5024 | 171 | 172 | 0.4145 | 1 (0.0718) | 0 | 0.0024 |
| PhysLib Qwen | 0.5019 | 98 | 65 | 0.2908 | 1 (0.0516) | 1 (soft cap reached, correct) | 0.0019 |

Findings
- Ledger tokens match Langfuse exactly wherever Langfuse is complete (Core DS, Core Luna, PhysLib DS): ledger is trustworthy. No bound_violation, no usage-unknown settles, all gates allowed except the single legitimate soft-cap refusal.
- HIGH: Langfuse lost generations in a window 17:24-18:25 (local) in 4 runs: CSLib DS 36 missing, CSLib Luna 79, CSLib Qwen 10, PhysLib Qwen 34 (PhysLib Qwen 34; PhysLib Luna, Core runs are fine). Windows coincide with the detached-probe process pile (~126 procs / 2.1GB) and the 18:01 memory events. So Langfuse is NOT a full audit source for those runs; arena.traces.judge preflight would flag them. Fix: make the langfuse plugin flush/retry with a local spill file; alert when ledger requests != LF generations.
- MEDIUM: Luna ledger charges the >272K prompt tier (26 requests CSLib, 27 PhysLib, prompts up to 301-307K) at about 2x; Langfuse prices them "Standard". Extra spend about $0.084 / $0.090, i.e. about 18% of the $0.5 cap. This is correct per run-config price_basis, but compaction (compact_at_tokens 200000) did not keep Luna under 272K. Fix: compact at <=250K for tiered models (or lower for Luna) so the tier is not crossed; adjust Langfuse model price tiers so cost comparison works.
- MEDIUM: orphan reserves = "provider_attempt_without_settled_usage" kind=unknown, one per run except Core. They are failed provider attempts (Langfuse levels: "Connection error." Luna x2, "Request timed out." DS PhysLib, "terminated" at 18:12:36/18:12:48 for DS+Luna CSLib simultaneously, "429 Endpoint is unavailable" Qwen PhysLib; Qwen CSLib = user kill). Unknown whether the provider billed them (the attempt may have produced tokens; terminated ones likely billed partial). Ledger shows "unresolved" 0.04-0.10 per run in summary.txt cost line (estimate, not spend), which makes the summary look scarier than it is. Soft cap gate counts settled only, so undercount risk is at most one request per run (~$0.02-0.10, up to 20% of cap in PhysLib DS 0.100).
- Soft-cap overshoot is tiny ($0.0024/$0.0019), as designed. Core DS/Qwen finish with $0.04 left; fine.
- LOW: summary stop label inconsistent: summary.txt "stop interrupted" vs campaign.txt "model_stopped" for Qwen CSLib (killed by user); campaign.txt "all-call cost" counts it as a stop reason of model.
- LOW: run-config.json hard_cap_usd=0.5 while summary says hard $3 / soft $0.5 (naming drift).

## 2. Stop rule (arena_finish, refusals, continuation)

| run | finish calls | refusals | stop | remaining at confirm | post-refusal work | continuation pushes / no-work turns |
|---|---|---|---|---|---|---|
| Core DS | 5 | 4 | finished (confirmed) | ~10% | seg tails: 1-4 probes + 1 candidate between refusals | 0 / 0 |
| Core Luna | 7 | 7 | error_loop (3 provider errors "Arena context bound exceeds model window") | 91% left (spent $0.166) | normal idea+probe cycles | 0 / 0 (error streak only) |
| Core Qwen | 4 | 3 | finished | ~13% | 14 probes then 7 probes | 0 / 0 |
| CSLib DS | 4 | 3 | finished | ~13.5% | 8, 4, 3 probes | 0 / 0 |
| CSLib Luna | 15 | 14 | finished | ~10% | idea-heavy (58 arena_idea calls) + 1-3 probes per segment | 0 / 0 |
| CSLib Qwen | 0 | 0 | killed (user) | n/a | n/a | n/a |
| PhysLib DS | 4 | 3 | finished | ~11% | 12, 2, 5 calls | 0 / 0 |
| PhysLib Luna | 2 | 0 | soft_cap_reached (finish "review" at 2.3% left; confirm after one arena_idea) | 2.3% | n/a | 0 / 0 |
| PhysLib Qwen | 0 | 0 | soft_cap_reached (gate refuse) | 0 | never called arena_finish | 1 control row (final) |

- The refusal ladder worked as designed: no run stopped before 10% remaining except by error (Core Luna) or kill. No "agent idle" turns occurred, so arena.ts agent_before_settle continuation pushes never fired (continuations=0 everywhere); the model always continued within tool loops. no_work_turns=0.
- HIGH (Core Luna): premature stop at 33% of the soft cap. 3 consecutive assistant errors "Arena context bound exceeds model window" (extension's pre-request bound estimate; reserve estimates $0.27 vs real $0.002) -> error_loop. This is the pre-16:11 bug that the later TS fix addresses; it cost this run about $0.33 of exploration (score 85.11 vs DS 86.07 / Qwen 86.02, so a small loss, but still). Verify: no later run (all started after the fix except Core*) shows the error. Also stop=error_loop after only 3 errors with 2s/4s backoff is aggressive; the bound error is deterministic so retries were useless, and the run could instead have compacted. Fix: when the bound error occurs, force compaction (or trim) and retry instead of counting an error; treat only provider/network errors in the streak.
- MEDIUM (Luna CSLib): 14 refusals; each refusal -> 1-3 probes. 57% of spend is bookkeeping (arena_idea 58 calls, arena_finish 15, arena_state 10). Luna keeps asking to finish early and the refusal loop converts into cheap idea churn rather than new routes (only 1 route all run). Improvement: after refusal N>=2 with no new route, the refusal text should require a route change (the data shows "new_idea_probed false" refusals 2-14).
- LOW: final segments for DS (2 probes, 2 probes, then confirm) show the model satisfying "new_idea_probed" with minimal probes; fine and cheap.
- Luna PhysLib: 46 arena_idea + 16 candidate calls before first finish; 40% bookkeeping; reached cap at 2.3% remaining with best 66.13 vs DS 88.25. Idea churn without route progress (single route).
- Qwen PhysLib never called arena_finish; stopped at the cap by gate refusal (settled $0.5019). Acceptable, but the model got no finish-review chance (hard summary "soft_cap_reached").

## 3. Tool errors by tool and cause (session isError=true; 28 total)

| tool | n | cause | models |
|---|---|---|---|
| arena_probe | 8 | 5x `arguments: null` (root: must be object; DS 1, Qwen 4) and 3x usage_error "Pass proof or drafts." (Qwen Core, sent `draft` instead of `proof`/`drafts`) | Qwen 7, DS 1 |
| arena_source | 9 | path/handle: `.lean-stdlib/...` not found (Qwen Core 1), `Strata/.../DL/Imperative/StmtSemanticsProps.lean` not found (hallucinated path), `project/Cslib/...` and `project:Physlib/...` (invented "project" prefix, Qwen CSLib 2 + PhysLib 1), `decl:` handle not found (Exists.imp, Continuous.inner, HasCompactSupport.mul_right), Luna "Only relative .lean paths" (passed a decl name as handle) | Qwen 6, DS 1, Luna 2 |
| arena_idea | 6 | "A new idea needs a title" (4: model used `idea` or only `reason`), unknown idea id i3, "Give a one-line reason when marking an idea succeeded" | Qwen 6 |
| mcp lean_multi_attempt | 2 | Qwen: "Column 65 out of range for line of length 9" (wrong line/col); Luna: null args | Qwen, Luna |
| arena_evaluate / arena_candidate | 2 | null args (Luna) | Luna |
| arena_local_search | 1 | "Tool arena_local_search not found" (Qwen invented the tool name; real one is mcp__arena_lean__lean_local_search) | Qwen |

Null-argument tool calls (8 in total: DS Core 1, Qwen Core 3 in a row at 10:11-10:12 UTC, Qwen PhysLib 1, Luna CSLib 1 arena_candidate, Luna PhysLib 2 multi_attempt/evaluate):
- Not malformed JSON and not truncation: in every case stopReason=toolUse, rawStopReason fine, output tokens 114..5772 and the event stream has `toolcall_start` immediately followed by `toolcall_end` with arguments=None, with NO toolcall_delta in between (events.jsonl); Langfuse generation output also shows the tool call with name and id only (no arguments). In the 4 DS/Qwen cases with visible thinking, the tail says "Let me write the drafts", i.e. the model intended arguments; the arguments never arrived (Luna shows no thinking text). It happens on Anthropic-style (Qwen, toolu_ ids), Responses (Luna) and chat-completions (DS), so it is at the provider/gateway or Pi stream parser level, not one model. The next call succeeded in 4 of 8 cases; Qwen Core repeated the null call 3 times in a row (each a full turn, $0.006 each) before getting through; Luna PhysLib's multi_attempt had a second valid call in the same message.
- HIGH side effect: a null-arguments toolCall left in history breaks Pi auto-compaction (section 5).
- Fix: have the extension's `tool_call` hook (or a Pi patch) normalise `arguments: null` to `{}` before it enters history, and return a specific retry message ("your call arrived without arguments, resend with proof/drafts"); the generic "root: must be object" text is not actionable.
- Qwen schema confusion: arena_probe `draft` vs `proof`/`drafts` (3x), arena_idea title vs idea (4x), invented `project:`/`project/` path prefixes (3x), invented arena_local_search. Suggest: accept `draft` as alias of `drafts`/`proof`, accept `idea` as alias of `title`, make arena_source accept project/ prefixes, and print valid forms in errors (the arena_source error text does not list how to name a path).
- No MCP/server errors, no lean_session errors in tool results; no Lean timeouts surfaced to the model (see 7).
- Other: odd text in Qwen PhysLib assistant thinking tail: "Understood. I'll use the current structured task actions and return only task-related output." (a canned acknowledgement of the system prompt, before a null probe; sign of the model drifting after the failed tool call).

## 4. Trims and repeat-read stubs

- Zero repeat-read stubs were produced in any run: no run re-read an identical arena_source/declarations/find/candidate/skill/local_search result (>=200 chars), so the stub path (STUBBABLE_TOOLS) is untested by this pilot. (After compaction, the identical-args re-reads were also 0, see 5.)
- Compared model-facing session text with untrimmed trace-journal text for all 926 tool results: 58 results shrank (lean_local_search, lean_goal, lean_multi_attempt, lean_diagnostic_messages), total savings ~ 50K chars across 9 runs (Luna PhysLib 25K, Qwen Core 22K); most of it is compact JSON. 0 omitted-warning cuts occurred, and 0 error messages lost (every severity=error message in the untrimmed text is in the model-facing text or points back via "same message as"). No problem found.
- MEDIUM design risk: ResultTrimmer.forget() runs on compaction (arena.ts 377/634), but a compaction that fails (section 5) leaves context intact, so no stale-stub problem; but if compaction partially succeeds with `firstKeptEntryId` earlier than the stubbed original (keepRecentTokens 40K), forget() clears the memory anyway, which is safe. OK.
- Trim contributes little (<1% of result chars); real context growth comes from arena_probe results and thinking blocks (see 5, 9).

## 5. Compaction and arena-memory

| run | compaction starts | ok | failed | cost of compaction requests | context peak (prompt tokens) | requests >200K |
|---|---|---|---|---|---|---|
| Core DS | 3 | 3 | 0 | 5 req $0.0660 (14.3% of spend) | 196K | 0 |
| CSLib DS | 3 | 3 | 0 | 5 req $0.0639 (14.0%) | 200K | 0 |
| PhysLib DS | 3 | 3 | 0 | 5 req $0.0673 (14.6%) | 196K | 0 |
| Core Qwen | 27 | 1 | 26 (2 "summary hit the token cap", 24 "Cannot convert undefined or null to object") | 3 req $0.0246 | 267K | 24 |
| PhysLib Qwen | 55 | 0 | 55 (all "Cannot convert...") | none | 352K | 53 |
| CSLib Luna | 66 | 0 | 66 (all "Cannot convert...") | none | 301K | 64 |
| PhysLib Luna | 82 | 0 | 82 (all "Cannot convert...") | none | 307K | 80 |
| Core Luna / CSLib Qwen | 0 | | | | 178K / 139K | 0 |

- CRITICAL/HIGH: Pi auto-compaction is broken for Luna and Qwen once a null-arguments toolCall is in the span to be summarized. Evidence: every failing run has its first `Cannot convert undefined or null to object` compaction failure after its first null-argument tool call (Luna CSLib: events line 15259 null, 38911 first failure; Luna PhysLib 15124/38915; Qwen PhysLib 17291/36426; Qwen Core 29626/71400). DS runs without null calls compacted cleanly every time (3/3/3). Qwen Core's one successful compaction kept the 3 null-call rows (66,68,70) in the "kept recent" region (firstKeptEntryId row 66 of compaction row 95), and failures started with the next compaction, which has to summarize them. A compaction retry is attempted every turn (66/82/55 times) and fails before any model request, so no money is spent, but context is never cut: prompt grows to 301-352K tokens.
- Consequences: (a) Luna crosses the 272K high-price tier in 26 (CSLib) / 27 (PhysLib) requests: ~$0.084 / $0.090 of extra cost, ~18% of the cap; (b) larger uncached prefix per cache miss; (c) Qwen PhysLib ran 53 requests at >200K, its cache "recent" stayed 99% so the cost impact is mild; (d) the soft cap came earlier than needed for Luna, whose 40-57% bookkeeping already burnt the budget. Fix: sanitize null `arguments` at tool_call time (above) and also repair existing history before compaction (session_before_compact hook), or make arena own compaction.
- MEDIUM: Qwen Core 2x "Turn prefix summarization failed: generation hit the token cap and the summary is incomplete" before the first success: compaction summary output cap (reserve) too small for Qwen's long thinking; each failure bills an output-capped request. Fix: higher max tokens for the summary call or lower thinking effort for compaction.
- DS compaction: fires at 201-208K tokens before; prompt falls to ~56-67K (keepRecent 40K) and the arena-memory message (1.2-1.6K chars; 3 per DS run, 1 in Qwen Core) is injected after each. Redone work after compaction: 0 identical re-reads of source/declarations/find/local_search/candidate/profile in the 3 windows of each DS run (0 of 8, 7, 4, 12, 6, 1, 10, 6, 6). First post-compaction calls are mostly source/find/probe, not repeated reads. So memory restate works and the summary does not cause redo.
- LOW: compaction summaries for DS begin "No prior history ... Turn Context (split turn)" because the whole run is one agent turn (no idle turns, continuations=0), so every compaction is a split-turn summary (2 requests per compaction = 5 requests for 3 compactions); costs ~14% of DS spend. Consider a cheaper summarizer or longer keepRecent to reduce count.

## 6. Route events (kernel vs text, labels, missing events)

Candidates that ever got a `route` event, by run (candidates counted from ledger `candidate` rows; route rows are keyed by proof_id):

| run | candidates | candidates with route row | route rows total | source mix | unrouted (never) |
|---|---|---|---|---|---|
| Core DS / Luna / Qwen | 37 / 19 / 34 | 37 / 19 / 34 | 37 / 19 / 34 | kernel only | 0 |
| PhysLib DS | 64 | 64 | 64 | kernel | 0 |
| PhysLib Luna | 31 | 31 | 31 | 25 kernel, 6 text | 0 |
| PhysLib Qwen | 25 | 7 | 10 | 9 kernel, 1 text | 18 (#6, #9-#25; all after 17:12:07) |
| CSLib DS | 29 | 17 | 37 (20 are for probes) | kernel | 12 (#11-#20, #22, #23) |
| CSLib Luna | 30 | 20 | 25 | kernel | 10 (#7, #11-#19) |
| CSLib Qwen | 9 | 7 | 17 | kernel | 2 (#1 original, #2) |

- HIGH: route events are not reliable for runs overlapping 17:10-18:20. Cause: at 17:10 (commit a5acc5c, Python live) probe fingerprinting moved to detached processes; each did a Lean elaboration cold (the Lean session was refused memory, section 7) and they piled up (~126 processes / 2.1 GB per your timeline) behind route-extract.lock. In PhysLib Qwen route-extract.lock was created at 17:12 and only candidates #1-#5, #7, #8 ever got a route row; the first missing candidate was 17:12:07. CSLib DS/Luna: first missing 17:12-17:13, last 17:58-18:01. After the 18:20 switch to one worker per run (route-queue.jsonl), backlogs were drained late: route row lag up to 3359 s (DS), median 1519 s (Luna), median 798 s (Qwen); the CSLib Qwen run's first route row is at 18:31:04 although it started 17:50, and its last at 18:48:58, i.e. 13 min AFTER the user kill (18:35). The queue holds duplicates (Luna 40 entries for 16 unique proof_ids; DS 30/26) and 1 queued item per run never routed.
- Consequence for analysis: summary.json `routes` for PhysLib Qwen (2 routes, 5 attempts) and CSLib DS/Luna (undercounted by 12/10 candidates) are NOT comparable to Core/PhysLib DS. "routes tried 1/2/3" in campaign.txt for those runs is an artifact; recompute route tables offline (re-fingerprinting needs Lean, not done here). Also the live feedback (route credit lines in finish pushes, "routes tried") the model saw during 17:10-18:20 was empty or stale.
- MEDIUM: baseline (#1 reference) route. PhysLib Luna's baseline was fingerprinted by `text` (16:17:32, kernel extraction failed on first call; first kernel row 16:18:50), so its r1 label is "no induction: ContinuousAt, Integrable, abs_real_inner_le_norm" whereas DS/Qwen r1 on the same theorem is "recursion: none; Classical.not_forall, Classical.propDecidable, ContDiff.continuous". Later kernel fingerprints compare against a text exemplar (routes.py: text features used if either lacks kernel) and all 31 attempts stayed on r1 (similarity 1.0 -> 0.59). Luna's summary therefore shows ONE route with 30 attempts and `original: true`, which is probably wrong (a proof at 0.59 similarity and 601 tokens vs 851 reference is not the original route). Same defect, other direction: CSLib Qwen's baseline never routed, so its single route r1 is labelled `original: false` and the label is the first probe's ("recursion: none; Cslib.LTS.IsBisimulation"). Fix: always fingerprint the baseline synchronously (or at least first in the queue) and re-run text-vs-kernel exemplars when the kernel arrives; do not let a text-only exemplar absorb kernel attempts at similarity < ~0.7.
- Text fallbacks: 6 of 31 in Luna PhysLib, 1 of 10 in Qwen PhysLib, 0 elsewhere; all come in bursts (Luna PhysLib 16:20-16:22) after kernel extraction failed; the cause was not logged. Labels otherwise sane: `recursion: none instead of ...` appears only with an original recursion; PhysLib routes use "+lemma -lemma" diffs; r3 (List.rec) in Core Luna has proxy -0.78 (route scored but terrible; fine).
- LOW: `route_progress` (depth, credited, explored, new_state share) exists only in the Qwen CSLib summary (new code); other 8 summaries have none, so campaign tables lack it for them.
- LOW: route rows exist for probes (CSLib DS: 20 non-candidate proofs) while route rows only for candidates in older runs; attempts per route therefore are not comparable across code versions.

## 7. Lean latency, timeouts, session errors, memory pressure

| run | arena_probe median / p90 / max (s) | probes "cold (session unavailable...)" | other |
|---|---|---|---|
| Core DS/Luna/Qwen | 0.7/1.3/3, 0.4/0.8/9, 0.6/1.0/3 | 0 | none |
| PhysLib DS/Luna/Qwen | 0.9/1.8/3, 1.4/1.8/2, 1.3/3.9/38 | 0 | Luna evaluate max 122 s, lean_multi_attempt max 40 s; arena_find med 3.5-5.7 s (30 files scanned/query) |
| CSLib DS | 54.8/103/128 | 11 of 44 (median 71 s; the rest 1.7 s) | |
| CSLib Luna | 57.2/99.5/127 | 24 of 49 (median 76 s) | arena_profile med 46 s |
| CSLib Qwen | 80.4/144/144 | 6 of 7 (median 122 s) | arena_profile 129 s |

- HIGH: on CSLib (the only theorem under parallel load > 2 jobs), `arena/lean_session.py` refused a Lean worker: "no room for a Lean worker: memory (3.2-7.5 GB available)" (rule: free - WORKER_GB 3.0 < RESERVE_GB 5.0 so needs >= 8 GB available; machine 30 GB). 87 such fallbacks (DS 23, Luna 48, Qwen 16 reports) between 16:57 and 18:30; the probes then ran as cold `lake`-style compiles, 40-100x slower (55-144 s vs 1.3 s). Probe latency by half hour for CSLib DS/Luna: 17:00 bucket median 71-76 s, 17:30 bucket 57-58 s, 18:00-18:29 bucket 1 s: the session came back after the ~18:01 summary/viewer memory fix and the 18:20 process cleanup. Qwen CSLib started at 17:50 (inside the pressure window) and 6/7 of its probes were cold, so its 45 min of wall time yielded only 7 probes / 19 requests: the run is NOT representative of Qwen's CSLib capability. Fix: admission control for parallel jobs (the harness can know the available memory at launch), or lower RESERVE_GB, or queue the route/fingerprint processes behind the Lean worker; log the fallback in the tool result as a note to the model ("slow cold compile; batch more drafts per call").
- Memory-pressure effects: (a) cold probes (above); (b) route fingerprints backlog (section 6); (c) Langfuse export loss window 17:24-18:25 (section 1); (d) the journals 70-290 MB (18:01 fix). All four are in the same window, so I attribute them to the parallel Python/Lean process pile plus 3 parallel Pi runs.
- lean-session.log is 0 bytes in all 9 runs: no logging of open/evict/refuse events; this audit had to infer from tool-result text. Fix: write session lifecycle lines there.
- No Lean timeouts, no heartbeat-limit tool errors, no lean_session errors reached the model; no MCP server errors (only tool-arg errors, section 3). Timeouts text hit in `arena_finish` results is the word "timeout/deadline" from review text, not an error.
- The 3 parallel Core runs at 15:13 and the PhysLib runs did not trigger the memory rule (all probes warm).

## 8. Provider retries, timeouts, truncation

| run | responses | error responses | retries (retry_of) | near output cap (>=90%) | latency p50/p90/max (s) |
|---|---|---|---|---|---|
| Core DS / Luna / Qwen | 67/104/88 | 0 | 0 | none (DS max 24,258 of 32K) | 41/130/178; 10/29/152; 40/120/183 |
| CSLib DS | 79 | 1 "terminated" 18:14:09 | 1 | none | 40/109/185 |
| CSLib Luna | 153 | 2: "Connection error." 16:59:10; "terminated" 18:14:09 | 2 | none | 11/31/81 |
| CSLib Qwen | 19 | 1 "terminated" 18:14:11 | 0 | 15,006 of 16K | 87/236/237 |
| PhysLib DS | 89 | 1 "Request timed out." 16:43:17 | 1 | none | 34/76/122 |
| PhysLib Luna | 172 | 1 "Connection error." 16:40:49 | 1 | none | 10/20/43 |
| PhysLib Qwen | 99 | 1 "429 ... Endpoint is unavailable" 17:18:17 | 1 | 15,072; 15,048 of 16K | 22/97/264 |

- Three "terminated" errors at 18:14:09-18:14:11 on three different providers/runs at the same second: a local/network event (right after the ~18:12 process cleanup, orphan reserves at 18:12:36 and 18:12:48), not provider flakiness. Likewise 16:40:47-16:41:16: Luna "Connection error." and DS request that timed out after 120 s (httpIdleTimeoutMs). Harness recovered each time with one retry (maxRetries 0 at Pi level; the extension retried; error_streak stayed <3). Billing of the failed attempts is unknown (orphans, section 1).
- No `length` stop on any agent turn: DS 32K cap never reached (max 24K, 17K, 17K); Luna max 5.6K. Qwen touched 15.0-15.1K of 16K in 3 turns (94%) without truncation; a 16K cap leaves no margin for Qwen thinking+draft; raise to 24K.
- The only stop_reason=length were Qwen Core compaction summaries (1,856 and 1,517 output tokens): the summary request's own cap (Pi turn-prefix summary) cut them (Pi message "generation hit the token cap and the summary is incomplete"), i.e. section 5; they billed an input-heavy request ($0.018 with 117K uncached, cache_read=0).
- Qwen latency is the highest (p50 22-87 s, max 264 s), DS next (p50 34-41 s), Luna fastest (10 s). 5 DS stop="stop" responses = the finish confirmations. No provider retry storms.

## 9. Cache anomalies

- Luna 98.2-99.0% cache reuse and Qwen 96.3-98.3% on Core/PhysLib: healthy. CSLib Qwen 88.4% (only 19 requests; cold start dominates).
- DS 90.0/91.8/92.8%: ~8 requests per run with <50% cache read, all clustered at the 3 compactions (the summarizer request has a different prefix, then the first post-compaction request and 1-2 more): about 535-560K uncached prompt tokens per DS run, i.e. $0.08 (17% of spend) at DS $0.15/M input vs $0.003/M cache read. Examples: Core DS request 17 (129,724 prompt, 6,144 cached), 18 (63,235, 4,096), 33-35 (56-73K, 0-4K cached), 48. Fix: make the summary request reuse the main prefix (append the summarization instruction as the last user message instead of a new system prompt) or compact less often by keepRecent/threshold changes.
- Qwen Core: the only cache_alarm (request 43, 15:54:24, cache_read 5,347, cache_write 52,086): first request after the successful compaction. Qwen's 117K cache_read=0 request at 15:51:37 is the compaction summary itself. Alarm threshold works.
- No cache anomalies for Luna beyond prices (section 1 tier note); no cache-write price issues; DS cacheWrite is 0 so DS never pays write.

## 10. Packet mismatch ("identical packets: False")

- Cause confirmed: only CSLib. DS (16:45) and Luna (16:55) share packet sha 274b07be..., 19,075 chars; Qwen (17:50) has 9d4b3ae3..., 19,203 chars. `diff` shows exactly one changed line (the arena_probe sentence): Qwen's packet adds "; a draft with `sorry` holes that elaborates is fingerprinted and opens a route, and filling the holes later stays on that route". Core and PhysLib packets are identical across models (Core 9aae848b 31,877 chars; PhysLib ec77819c 44,180 chars).
- Timeline correction: arena/context.py was edited at 17:10:26 and committed in a5acc5c (17:10:59, with campaign.py, routes.py, rules.ts, arena.ts and the other exploration-credit files) - not at 17:59 (that is the last mtime of arena/campaign.py, 17:58:44). Qwen CSLib started 17:50:10, so it is the only run whose packet and extension (rules.ts/arena.ts credit logic) are from a5acc5c; Python parts of a5acc5c were already live for all runs from 17:10. Later commits (8809e0c 18:59 null-args repair, 3ee8514 18:01 journal reader) are after every run; the compaction/null-arg bug found in section 5 is already fixed by 8809e0c.
- So the 3 Qwen-vs-other comparisons on CSLib differ in packet, extension and (partly) timing; the campaign is not a clean cross-model A/B for CSLib. Code versions per run: Core x3 + PhysLib DS: before 5c29aff (16:11 context bound) and before .lean-stdlib fix (Core Luna's error_loop is the old bug); PhysLib Luna/Qwen, CSLib DS/Luna: after 16:11, Python a5acc5c live from 17:10; CSLib Qwen: everything up to a5acc5c.

## 11. Qwen story

Per-run (Qwen 3.8 Flash):
| theorem | best proxy | spend | stop | candidates / probes | ideas (attempts) | routes per summary | tool errors | rejected requests |
|---|---|---|---|---|---|---|---|---|
| Core | 86.02 (#21) | $0.4535 | finished | 34 / 25 | i1 (19) succeeded, i2 (13) succeeded, i3 (5) active, i4 (2) active | 1 used route r2 (33 attempts); r1 original 0 | 13 | 12 x $0.0623 (13.7% of spend) |
| PhysLib | 87.32 (#25) | $0.5019 | soft cap (while still improving) | 25 / 39 | i1 (62) succeeded, i2 (1) abandoned | r1 (4 attempts, 77.34), r2 (6, 81.25); 18 of 25 candidates unrouted | 4 | 4 x $0.0188 |
| CSLib | 78.43 (#5) | $0.0913 settled (+$0.041 open) | killed by user at ~$0.13 | 9 / 12 | i1 (13), i2 (3), i3 (4), all active | r1 only ("recursion: none; Cslib.LTS.IsBisimulation", not original) | 4 | 4 x $0.0179 |

- Single chain on one route: yes on Core (33 of 34 attempts on r2, 4 ideas named but 1 fingerprinted route; ideas i1/i2/i3/i4 are variations inside the same route: commute updatedStates via updatedStatesComm vs relation-level monotonicity are both labelled "recursion: none instead of Core.UpdateStates.rec; +updatedStatesComm..."). On PhysLib the record is consistent with one chain (62 of 64 idea-attempts on i1 "continuity of psi"), but the route table cannot confirm it (18 of 25 candidates unrouted). On CSLib every routed proof is r1. So "ideas named" (4/2/3) are not distinct fingerprinted routes, the harness credits 1 route per run; Qwen never records a second route that the fingerprint would call new. Compare DS: 3/4/2 fingerprinted routes; Luna Core 4 routes.
- Golf progression (proxy by candidate order): Core 78.47 (#2) -> 79.78 -> 82.64 -> 82.78 -> 83.48 -> 84.32 -> 85.12 -> 86.00 (#20) -> 86.02 (#21): +7.5 in 20 candidates, small steps; PhysLib 75.92 (#2) -> 79.5 (#6) -> 81.25 (#7) -> 83.9 (#12) -> 86.06 (#18) -> 86.28 (#20) -> 87.32 (#25): +11.4 in 24 candidates, still rising at cap (the soft-cap gate refused one request at $0.5019; the last 5 candidates gained +1.0); CSLib 73.02 (#2) -> 77.67 (#3) -> 78.43 (#5) then 77.2/77.88/78.08/75.75/75.02: 5 candidates, then regression in the last two (#8, #9 fell to 75), killed there. Qwen's gains are slow monotone golf in one route rather than structural jumps (DS jumped 33.5->86 in Core by route r2 at #34 after 34 attempts; DS PhysLib 83.37 r2 -> 88.25 r3).
- Qwen-specific harness costs: (1) 4 of the 8 null-argument tool calls (three in a row in Core, 15:xx), plus 3 arena_probe usage errors (`draft` instead of `proof`) and 4 "needs a title" arena_idea errors: 12 rejected requests = 13.7% of Core spend ($0.0623); (2) compaction broken after null-arg calls (section 5): Core 24 failed + 2 token-cap failures; PhysLib 55 failed, context to 352K; (3) 16K output cap nearly hit (15.0K) 3 times; (4) latency p50 22-87 s, max 264 s per request. (5) 6 Qwen arena_source errors are invented or wrong path forms (`project/...`, `project:...`, `.lean-stdlib/...`, a nonexistent file) - it ignored the declared handle forms.
- CSLib (partial) under the new code (17:50 start, packet with the "fingerprinted and opens a route" sentence): only 19 requests in 45 min because 6 of its 7 probes were cold Lean (122 s median; section 7) and route events arrived 41+ minutes late (first at 18:31), so the new route-credit/stale/skeleton machinery had no data during the run: summary says "0 credited routes, 0 explored; 50% of attempts produced a goal state new to their route", r1 "opened, no scored proof, stale streak 1, skeleton false", but candidate #5 (78.43, verified, routed r1 at 18:40) is not shown as the route's best (route best_candidate null because the table was computed at kill time before cold verification/routing finished). [arena] notices shown to the model were consistent with ledger (best verified #2 73.02 -> #3 77.67 -> #5 78.43, #4/#6/#7 verified lower); no stale notice, no skeleton claim, no finish refusal (it never called arena_finish). So the "stale notices/skeletons" concern did not materialise, but only because the new feedback never fired. This run cannot judge the A/B/C exploration credit; rerun with admission control and the sentence in all three CSLib packets.
- Qwen's single-route behaviour in CSLib/Core is not evidence of a model deficit alone: Qwen Core stopped at "finished" with 12% budget, Qwen PhysLib reached the cap; both reach DS-level proxies (86.02 vs 86.07; 87.32 vs 88.25). Gap to DS on PhysLib is 0.93.

## Issues by severity (suggested fixes in sections above)

CRITICAL/HIGH
1. [5] Pi auto-compaction fails with "Cannot convert undefined or null to object" whenever a null-arguments tool call is in the span being summarized (Luna CSLib 66x, Luna PhysLib 82x, Qwen PhysLib 55x, Qwen Core 24x). Context grows to 301-352K; Luna pays the >272K tier ($0.084/$0.090, 18% of cap). Already fixed in 8809e0c (18:59), not in any pilot run; verify with a rerun.
2. [3] Tool calls with no arguments (8, all 3 providers; toolcall_start straight to toolcall_end, no deltas, not truncation); Qwen repeats it 3x in a row. Fix: normalise null to {} + specific retry message.
3. [6,7] 17:10-18:20 memory pressure: Lean session refused ("no room for a Lean worker", needs >= 8 GB free): 41 of 100 CSLib probes cold at 55-144 s; route extraction backlog; unrouted candidates (PhysLib Qwen 18/25, CSLib DS 12/29, Luna 10/30); route events up to 56 min late, 13 min after the kill. Route tables for these runs are wrong; campaign "routes tried" is an artifact.
4. [2] Core Luna: error_loop after 3x "Arena context bound exceeds model window" at 33% of the cap (pre-16:11 bug; compaction should have been forced). Fixed in 5c29aff.
5. [1] Langfuse lost 36/79/10/34 generations for CSLib DS/Luna/Qwen and PhysLib Qwen (17:24-18:25 window): Langfuse is not a complete audit source for them; ledger is consistent and complete.
MEDIUM
6. [6] Baseline route fingerprinting: Luna PhysLib baseline = text fingerprint, all 31 attempts absorbed into r1 (labelled original); Qwen CSLib baseline unrouted, r1 labelled not original.
7. [1,8] 7 orphan reserves ("provider_attempt_without_settled_usage"; $0.02-0.10 each, billing unknown); 3 simultaneous "terminated" at 18:14:09-11 point to a local event.
8. [2] Luna CSLib: 14 refusals, 57% bookkeeping (58 arena_idea); Luna PhysLib 40% bookkeeping and 1 route; refusal text does not force route change.
9. [5,9] DS compaction costs 14% of spend plus ~$0.08 of uncached prompts per run (summarizer prefix differs); Qwen compaction summaries hit a ~2K token cap twice.
10. [3] Qwen tool-schema confusion (arena_probe draft, arena_idea idea/title, project: paths): 12 rejected requests = 13.7% of Core spend.
11. [10] Packet differs for Qwen CSLib (one sentence; a5acc5c at 17:10:59, not 17:59); CSLib is not a clean cross-model A/B.
LOW
12. summary stop label "interrupted" vs campaign "model_stopped"; run-config hard_cap_usd 0.5 vs hard $3; lean-session.log empty everywhere; route_progress only in Qwen CSLib summary; Qwen output within 6% of the 16K cap three times; trims verified harmless (0 error text lost, 0 stubs produced).
