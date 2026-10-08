# v6 pilot: why GPT-6 Luna explored the most and scored lowest

Scope: 3 Luna runs (Core.InitsUpdatesComm 85.11, FTVC 66.13, CSLib bisimilarity_congr_choice 75.62) vs DeepSeek (86.07 / 88.25 / 86.44). Sources: events.jsonl, ledger.jsonl, cost-ledger.jsonl, submissions. Read-only.

## Headline
Luna's "exploration" was wide but shallow and expensive. Three mechanisms:
1. **Money**: 71-77% of Luna spend (CSLib, FTVC) is cache-READ of a 170-180K-token context re-sent on every one of 150-170 small turns; auto-compaction fails 100% of the time on Luna (66/66 and 82/82 "Auto-compaction failed: Cannot convert undefined or null to object"), so context grows to ~300K. DeepSeek: output 58-61% of spend, 67-89 requests, compaction succeeds (3 per run).
2. **Turn shape**: Luna emits ~800-1100 output tokens/turn (reasoning ~400-760) vs DeepSeek 5-7K; one tool call per turn, 1 draft per arena_probe (DS 2.3-2.5 drafts/probe). Luna makes 27-49 probe calls yielding 27-49 drafts; DS 40-47 calls yielding 74-103 drafts. Evaluations: Luna 37/58/55 vs DS 73/56/126.
3. **Ideas are not routes**: 9/29/23 declared ideas collapse to 4/2/1 kernel-fingerprinted routes. Each idea costs two arena_idea calls (declare active, then status+reason) = 47-58 turns, 17%/39%/29% of spend. Add arena_finish (15 refusals on CSLib) + arena_state: bookkeeping turns = 28%/55%/37% of spend by turn cost.
4. **Strategy**: Luna never left the reference's lemma family. FTVC: DeepSeek found one library lemma (Continuous.integral_pos_of_hasCompactSupport_nonneg_nonzero, 0 mentions in Luna's whole run, found via broad queries "integral_pos_of_pos", "Continuous.integral") and wrote 25 lines / 160 tokens; Luna kept the reference's bump_exists + integral_pos_iff_support_of_nonneg skeleton (58 lines, 601 tokens, 3716 HB vs DS 1951) and hill-climbed it 916 -> 601 tokens over 30 micro-candidates.

## 1. Real vs relabeled exploration
| run | ideas | kernel routes (attempts) | candidates | notes |
|---|---|---|---|---|
| Core | 9 (5 succeeded, 4 abandoned) | r1 1, r2 14 (best 85.11), r3 1, r4 2 | 19 | 14 of 18 candidates on one route ("recursion: none", from #1 chain parents 0..13) |
| CSLib | 29 (23 abandoned, 5 succeeded) | r1 10, r2 15 | 30 | 17 of 29 ideas got 0 probes and exactly 2 evals (fast+auto-full) of one draft each |
| FTVC | 23 (19 "succeeded") | r1 only (25 kernel + 6 text) | 31 | "succeeded" ideas are 1-5% token trims of the same proof: parents chain 3->4->...->30, tokens 916->601 |
Candidates are line-rewrites of the reference (line similarity 0.05-0.3), and ~50-75% compile, so they are real edits, but they do not change the lemma set, which is what the route fingerprint measures. CSLib's best came at candidate #7 (72.42, spend $0.053); the remaining $0.40 bought +3.2 points. DeepSeek CSLib used a different technique (HomBisimilarity.symm_simulation, ChoiceBisim.rec, term-mode `.imp fun t => And.imp ...`, 85 tokens) vs Luna's tactic induction + `first | exact` (155 tokens).

## 2. Where the money went
Spend share by cost component (cost-ledger settle): Luna CSLib cacheRead 71%, cacheWrite 9%, output 20%; FTVC 77/9/15; Core 58/13/28. DeepSeek: input 35%, output 59-61%, cacheRead 4-6%.
Avg context per request: Luna 95K / 168K / 182K (max 301K/307K); DS 112K / 117K / 122K.
Turn cost by category (Luna Core/CSLib/FTVC): proof tools (probe/candidate/evaluate/profile/lean_goal/multi_attempt) 52% / 37% / 54%; arena_idea 17% / 39% / 29%; arena_finish 7% / 10% / 2%; arena_state 4% / 6% / 6%; research (find/declarations/source/local_search) 20% / 9% / 10%. DeepSeek: proof 63-74%, research 24-29%, idea+finish+state <8%.
Cost per evaluation (total incl. unresolved / evaluations): Luna Core $0.0045, CSLib $0.0096, FTVC $0.0104; DeepSeek Core $0.0063, CSLib $0.0089, FTVC $0.0044. Luna is cheaper per request ($0.0016-0.0033 vs $0.0050-0.0069) but needs 2x the requests and gets 0.45x the evaluations on FTVC.
Turns with no proof attempt: Luna CSLib 98/154 (64%), FTVC 82/173 (47%), Core 56/107 (52%) (idea/finish/state/research/none turns).

## 3. Proof quality vs DeepSeek
Compile rates are not the problem: draft pass rate Luna 74% (FTVC), 57% (CSLib), 50% (Core) vs DS 58%, 37%, 51%. Failure classes where Luna fails: unsolved goals (sorry skeleton drafts) 22, type mismatch 8, grind/simp failed 4 (CSLib); grind-based closure idea failed once and was abandoned after 1 probe. Luna's 1-draft probes mean 49 compile-checks vs DS 82.
Good ideas not executed: (a) CSLib: symmetric-relation-forward (5 probes, same family as DS's symm_simulation trick) abandoned; term-mode golf (.imp/And.imp) never tried; Luna's final keeps `let L := ...; first | exact ... | exact ...` fallbacks. (b) FTVC: a single "positive integral of compact-support nonneg nonzero continuous function" lemma; Luna's arena_find queries targeted micro-lemmas (div_lt_self, abs_sub_lt, half_lt_self) 10+ times and strategy lemmas only via the reference's own name. (c) Core: Luna 86 tokens vs DS 82, parity; both submitted structurally the same proof (cases on UpdateStatesUpdated + updatedStatesComm).

## 4. Turn mechanics
- Output/turn: Luna mean 885 / 1125 / 790 (median 417-795, max 5.6K, never near 16K); DS 7.1K / 5.7K / 4.9K. Reasoning tokens/turn 407-765. Luna thinks briefly, then acts on one tool call per turn.
- Latency: median turn gap 10.8-17.2 s (includes Lean); CSLib wall 112 min vs DS 125 min, FTVC 40 min vs 63 (Luna stopped by cap earlier), Core 26 min (error loop).
- Cache hit 98-99%, so cache is not the issue; the issue is how much context is re-read. Retries: CSLib 2 (Connection error, terminated), FTVC 1; all recovered.
- Compaction: threshold-triggered 66 (CSLib) and 82 (FTVC) times, every one failed with "Cannot convert undefined or null to object" (likely the Responses-API reasoning items / encrypted content lacking a text field in the summarizer's serialization; Qwen shows the same error 24/55 times, DeepSeek works). Core Luna had no compaction events before stopping.
- Core error loop: at request 105 (context ~178K tokens, $0.166, 26 min) the Arena byte bound counted ~665KB of encrypted reasoning as prompt text and 3 consecutive "Arena context bound exceeds model window" errors triggered error_loop. Fixed 16:11 for later runs; the later two runs show the same oversized context but did not trip it.
- Finish refusals (CSLib): Luna called arena_finish 15 times (turns 39, 54, 59, ... 145); 14 refused, 1 confirmed at turn 152. After each refusal it spent ~7 turns on a new micro idea. Best moved 72.42 (turn 39) -> 72.56 -> 74.82 -> 75.35 -> 75.62; each finish call carries a full budget/best/baseline JSON back into context. FTVC only 2 finish calls; stopped on soft cap with 12 requests after best.

## 5. Harness quirks that hurt Luna
1. Compaction crash (above): context 3x larger than needed; 71-77% of spend is re-reading it.
2. Ideas protocol requires two arena_idea calls per idea and a "reason" on status; Luna follows it literally (29 ideas / 58 calls in CSLib), DS declares 2-6.
3. Probes accept `drafts` lists; Luna sends 1 draft per call. No parallel tool calls used.
4. arena_finish refusals repeat 14x with full JSON; each costs a turn at 170-250K context.
5. Route counting (kernel fingerprint) classes 29 ideas as 1-2 routes, so the "route depth" signals and finish gating cannot tell Luna's micro-trims from strategy change; "succeeded" status flatters micro-trims.
6. Byte-bound counts encrypted reasoning (fixed after Core).
7. Soft cap hit on FTVC with only $0.0874 spent after the best candidate: the climb was still improving ~1 token per candidate when it stopped.

## 6. Harness-side recommendations (no extra model bookkeeping)
1. Fix the compaction crash for Responses/encrypted-reasoning messages (null-safe serializer), or truncate/drop old reasoning items and old tool results (context_edit exists) when context > ~100K. Expected: cacheRead share 75% -> ~35%, roughly 1.8x more turns per dollar.
2. Make idea declaration implicit: auto-create an idea from the first arena_probe (hypothesis string already in `idea`) and auto-set status from evaluation outcome (improved => succeeded; no improvement after N probes => abandoned). Removes 25-40% of Luna's spend.
3. Return idea status updates, arena_state and refused finish text in a compact form (finish refusal one line: "refused: best X, Y budget left, try structural change"); do not echo full baseline/best JSON.
4. Encourage batching: in the probe tool result or tool description, state "send 2-3 drafts per call"; accept multi-tool calls per turn. Luna 1 draft/probe vs DS 2.4.
5. Add a research nudge after 3 consecutive same-route (kernel fingerprint) evaluations with <2% gain: auto-attach a ranked list of lemmas from library by statement similarity (kernel route fingerprint already available) to the next tool result; this is deterministic (harness-side), no model call. FTVC's missing lemma would be surfaced by goal-shape search (positive integral / compact support).
6. Count route novelty by kernel fingerprint in the status line ("5 attempts on route r1, 0 new routes in 20 evals") so the model sees it is trimming rather than exploring.
7. Do not count encrypted reasoning bytes toward the bound (already fixed); log bound violations separately.
