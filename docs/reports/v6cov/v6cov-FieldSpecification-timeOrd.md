# v6cov run study: FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time (DeepSeek v4.1 Flash, r1)

Run dir: `runs/pi-budget/v6cov-FieldSpecification.WickAlgebra.-_timeOrd-deepseek-v4.1-flash-r1/`
Sources used: summary.txt/json, cost.json, cost-ledger.jsonl, ledger.jsonl, trace-journal.jsonl, events.jsonl, the Pi session JSONL (assistant reasoning, tool calls, usage), proofs/, diagnostics/, submission.lean, campaign.log. No Langfuse. All times are minutes from session start (Pi session 10:13:41 to 11:07:36 UTC, 53.9 min). All dollars are against the $0.5 soft cap.

## TL;DR

- **Low score = the proof's shape plus a model strategy that never banked a second win; not tool errors, not Lean cost.** The only compiled candidate (#2, 20.5 min, $0.135 = 27% of the cap) is the reference with four heavy automation calls swapped for cheap ones: heartbeats 42,225 to 26,059 (-38.3%) but tokens 1217 to 1267 (+4.1%, which is negative on the token axis). Proxy 33.33 to 44.73. Nothing after it compiled: 20 more probes, $0.324 (71% of spend), 6 complete drafts, 0 compiled.
- **The model diagnosed the right target and could not land it.** `arena_profile` (A#31) showed one `calc` block (proof lines 19-95) holding 691 of 1267 tokens (55%) and 11.3K of 26K HB (43%). All 20 later drafts rewrote that whole region at once; each failed at its first error, so the model learned one error per probe. Two drafts reported 14.1K to 16.0K HB with 638 to 655 tokens while failing; those would score about 70 if they compiled, but a failing draft's heartbeat number is only what ran before the error.
- **Output volume was the cost driver.** 443K output tokens ($0.266 = 58% of settled spend), mean 7.0K/turn, max 56.6K. Eight turns of 15K+ tokens were 50% of all output and $0.150 (37% of Pi-billed spend). Two turns (A#18, A#42) were 56.6K and 54.2K tokens (88% and 85% of the 64K cap) and took 6.1 and 5.2 min. One turn contained 524 occurrences of "Hmm". Lean time is negligible (31 checks, p50 1.5 s, 57 s of probe time in a 54 min run); 96% of wall time is model generation.
- **The 5 tool errors are one harness bug.** Four `arena_declarations` calls and one `arena_source` all returned `Invalid declaration name` because `arena/campaign.py` lines 700 and 792 use an ASCII-only regex and every name involved starts with `ι`. The same ASCII regex (lines 324, 539-542, 649) hides `ι_*` declarations from the `arena_find` index (queries for `ι_superCommuteF_ofCrAnOpF_ofCrAnOpF_mem_center` returned unrelated `equiv_iff_exists_add`). Cost is small in dollars (~3 wasted turns) but the three lemmas the proof depends on could not be looked up with the arena tools.
- **The fixes behaved.** lrx: the one compaction (threshold, 505K tokens, 44.5 min) was reserved at an estimate of $0.187 against $0.173 remaining, with the gate reason "compaction summary bypasses the budget guard"; without lrx the guard would have refused it. Actual cost $0.0553. vqm: the wire body carried `max_tokens: 64000`; no turn was length-stopped (max 56.6K); the single failed turn (A#16) was a provider stream drop ("Stream ended without finish_reason"), retried by Pi, not a length event.
- **Compaction was a net loss at this cap.** $0.0553 for the summary request (352,586 uncached input tokens, zero cache hits) plus $0.0114 for the first post-compaction request (76K uncached) = $0.067 (14.6% of spend), double the "~$0.03" in `models.yaml:55`. Carrying 500K of cached context for the remaining 12 turns would have cost about $0.017. Net about -$0.05, roughly 6 probes at the post-best rate.
- **The finish refusal bought nothing here.** The model tried to finish at 34.7 min with $0.251 left and a 22-probe dry spell; refused (rule: at most 10% left). The next $0.21 of spend produced 0 new points. This is rule-consistent; the point is that after 22 failed probes the marginal value was already near zero, while the model had one cheap unexplored lever (the token axis of #2; see section 5).
- **Highest-value harness changes (by score per dollar):** (1) report all errors of a failing draft in one probe (error-recovery pass), (2) stop printing heartbeat figures for failing drafts, (3) widen/de-truncate sorry goal output (8 `lean_goal` round-trips), (4) fix the Unicode regex, (5) budget-aware compaction threshold. Details in section 6.

## 1. Timeline

Reference (packet): 1217 tokens, 42,225 HB (measured 42,165), one toolchain (v4.32.0), so compat is 100% whenever it compiles. Rates: 1 token = 0.027 pt, 100 HB = 0.079 pt. Spend column is Pi-billed cumulative, plus the compaction after 44.5 min.

| min | spend | event |
|---|---|---|
| 0.0 to 8.7 | $0.047 | Survey: 14 `arena_source` reads (134K chars), 5 `arena_find`, 4 failing `arena_declarations`, 2 `lean_local_search`. A#16 (8.2 min): 52.7K chars of thinking lost to a dropped stream, 2.3 min, Pi auto-retry succeeded. |
| 8.7 to 14.8 | $0.082 | A#18: one 56.6K-token turn (148,868 chars of thinking, 6.1 min, $0.035), ends in `arena_idea` i1 plus the first probe. |
| 14.8 to 20.5 | $0.135 | p1 to p10: scaffolding drafts with `sorry`. p1 type mismatch; the span-induction scaffold elaborated at p5 (16.6 min); p6 to p10 build-ups. |
| **20.5** | **$0.135** | **#2 compiled, proxy 44.73 (1267 tok, 26,059 HB). Best of the run.** Built by keeping the reference's calc verbatim and replacing four `simp_all` calls with explicit `simp only` branches (A#29 reasoning). |
| 21.5 | $0.143 | `arena_profile` of #2: calc 11,279 HB (43.3%), `conv_lhs` 2,017, tail simps about 1.1 to 1.3K each, branch proofs about 6.6K. |
| 22.5 to 34.7 | $0.249 | p11 to p18: eight draft skeletons of a rewritten calc region, 8 `lean_goal`/diagnostic calls. A#42 (32.5 min): 54.2K tokens, $0.034. |
| 34.7 | $0.249 | First `arena_finish`: refused, 50% unspent. Spent so far: r1 14 attempts, r2 5 attempts, best 44.73. |
| 35 to 44.5 | $0.382 incl. compaction | p19 to p25: full drafts, each failing in the last third (koszulSign rewrite pattern, scalar-bracket orientation). Compaction at 44.5 min (threshold, tokensBefore 505,182). |
| 44.5 to 53.8 | $0.459 | p26 to p30, an `arena_candidate #2` re-fetch, a micro-golf attempt that broke the already-working branches (p30). Second `arena_finish` at 53.9 min with 8.2% left: confirmed, stop `finished`. |

Score over time: 33.33 (baseline) until 20.5 min, 44.73 from then to the end. Post-best spend: $0.324 over 35 requests, 0 gain. First credited route: none (r1 original route 26 attempts; r2 5 attempts, min holes 1, no scored proof).

## 2. Tool use

| tool | calls | notes |
|---|---|---|
| arena_probe | 29 | 31 drafts: 1 compiled (#2), 8 skeletons with `sorry` that elaborated, 6 complete drafts that failed (p19, p20, p24, p25, p27, p30), the rest failed. 27 of 29 calls had a single draft (pilot runs had about 2.3 drafts per call). Latency mean 2.0 s, max 3.9 s. |
| arena_source | 20 | 134K chars returned. Latency 0.2 s. Three post-compaction/late reads overlap earlier ones (TimeOrder.lean 162-282 read at 20.9 min; 255-285 and 228-258 at 48.5 to 48.7 min). |
| mcp lean_goal | 8 | 1.5 s each, one model turn each; used because probe goal output was truncated or empty (section 6.3). |
| arena_find | 5 | 4.8 s mean (10 s max). |
| arena_declarations | 4 | all errors |
| lean_local_search | 2 | the only tool that located the `ι_*` lemmas |
| arena_finish | 2 | refused once, confirmed once (5.4 s mean) |
| arena_profile, arena_idea, arena_state, arena_candidate, lean_diagnostic_messages | 1 each | |

Tool errors, all of them (5):
1. 10:14:07, A#2: `arena_declarations` items `["FieldSpecification.WickAlgebra.ι_superCommuteF_ofCrAnOpF_ofCrAnOpF_mem_center", "FieldSpecification.crAnTimeOrderSign_swap_eq_time", "FieldSpecification.WickAlgebra.ι_superCommuteF_of_diff_statistic", ...]` returned `{"ok":false,"error":"Invalid declaration name"}`. One bad name rejects the whole batch.
2 to 4. A#8, A#9 (two calls): the same call with `ι_*` names, again `Invalid declaration name`. The model re-tried three times in three consecutive turns without learning which name was rejected (the message does not say).
5. 48.5 min, A#58: `arena_source` with `handle: "decl:FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time"` (the target theorem itself), same error. The model then used a file handle with line ranges.

Root cause: `arena/campaign.py:700` and `:792` use `re.fullmatch(r"[A-Za-z_][A-Za-z_0-9'.]*", symbol)`. The kickoff/`arena_find` path has the same class pattern (`:324`, `:539`, `:541`, `:542`, `:649`), so declarations whose local name starts with `ι` are neither indexed nor resolvable. This row is a Physlib file where `ι` is the quotient map used throughout.

Bookkeeping overhead is small (summary: bookkeeping 3 x $0.0191, rejected 4 x $0.0069, total 5.7%). Cache: 95.0% overall reuse (12.7M read, 665K uncached), 93.0% over the last ten requests. Wasted or repeated work: the three consecutive identical-class `arena_declarations` turns ($0.004 total), the dropped stream (about 13K output tokens regenerated, about 2.3 min; the ledger books the attempt as an unresolved $0.0599 estimate and it did not count against the cap), 3 overlapping source reads.

Lean cost: `lean-session.log`: 3 warm workers ready in 44 to 62 s, one background-worker idle close at 15:58 (900 s) and reopen (header 8.4 s). 31 model-lane checks, p50 1.5 s, p95 2.9 s, 0 timeouts, 0 cold-path. Total probe time 57 s of 54 min. Whole-proof HB for #2 under cold verification: 26,103 (session 26,059).

## 3. Model reasoning and strategies

By effect on the proof:
- **Survey (0 to 8.7 min).** Read the target file, `SuperCommute.lean`, `FieldOpFreeAlgebra/TimeOrder.lean`, `InsertionSort.lean`, `Basic.lean`. Concluded at A#6: the reference's `calc` is the bulk and no ready-made lemma shortens it (a search for `timeOrderF_superCommuteF_eq_time`-style variants at 17 min and again at 48 min returned none).
- **Scaffold and branch swap (14.8 to 20.5 min), the win.** Replaced the let-bound predicates and four `simp_all` calls with explicit predicates and `simp only` branch proofs. Effect: 42,225 to 26,059 HB (-16.2K) with +50 tokens. The model's own count: "the reference's `pb`/`pa` ... four `simp_all` calls (≈20600 hb, 49%)".
- **Restructure of the calc region (22.5 to 53 min), nothing landed.** It first proposed a shorter replacement for the 691-token calc, then attempted to fix: (a) `rw [h1, h2, h3]` ordering (h3 rewrote subterms newly introduced by h1/h2; found at A#44), (b) moving a central element through a right-nested product (the A#42 turn, 54K tokens, 524 "Hmm"), (c) `𝓢(..) • a * b` parsed as `(𝓢 • a) * b` so a folding step did not match (A#62), (d) the sign rewrite not matching `crAnTimeOrderSign` until it is unfolded (p19 vs p30), (e) an argument name (`φ'` not `ψ`) in p30. Every one of these is a first-error-only finding: the probe returns one error, the model fixes it, the next error appears.
- **Micro-golf at the end (A#63, p30).** It dropped `add_mul` / `Algebra.smul_mul_assoc` from the branch simp sets because #2's lint said they were unused. The lint applied to the outer branches only (A#56 had noted this); p30 shortened the inner branches as well and they then failed with "simp made no progress" (A#64). The correct subset (2 tokens, about 0.05 pt) was never submitted.

Misreads of tool feedback:
- Heartbeats on failing drafts. p19 reported `tokens 649, heartbeat 16605` with `compiled:false`; the model carried "p19 indicates the rewritten route can reach ~16605 heartbeats, which would be a large score gain" in its compaction summary and its working plan. A draft that fails partway reports only the work done before the error; the real figure for a complete proof of that shape is unknown.
- The probe's `goals` field: p9 and p10 returned `goals:""` (a `sorry` after an earlier error); p11 to p25 `goals` were exactly 1500 chars (truncation limit at `arena/engine.py:310`). The model spent 8 `lean_goal` turns recovering full goals ("Excellent! Now I can see the goal" at A#69 after two empty probes).

Output limits and length stops: none. Max turn 56,571 output tokens (A#18), second 54,221 (A#42) against a 64,000 cap; turns >=16K: 8 (A#18, A#34, A#42, A#44, A#45, A#49, A#50, A#61). No `stopReason: length`. The one `error` stop (A#16) was the stream drop.

## 4. Context and compaction

- Peak context 499,530 tokens (A#52). No other compaction. Context growth was dominated by retained thinking (443K output tokens carried forward in history plus 134K chars of source reads).
- Compaction: reason `threshold`, `tokensBefore` 505,182, `compact_at_tokens` 500,000, `keep_recent` 40,000. The summary opened with "No prior history ... Turn Context (split turn)" and then reproduced the task, the route, the banked candidate, lemma facts and the open errors; it is accurate (it cites #2, the 649-token p19 state, the two remaining errors, the 50% refusal). The harness injected the `arena-memory` message 53 s later with best candidate, route tallies and the latest three failures. After compaction the model re-read the source (A#58 to A#60) and re-fetched #2 (A#62); no draft was repeated.
- First post-compaction request: 75,941 uncached input tokens ($0.0114); then 80K cached.
- lrx evidence: reserve `0.187` vs remaining `0.173` at the compaction request, `reason: "compaction summary bypasses the budget guard"`, `purpose: compaction`, settle $0.0553 (`orphan_stream` / `compaction_summary`). Worst-case estimate was 3.4x the actual cost; without the bypass the guard would have blocked the compaction.
- vqm evidence: wire body `max_tokens: 64000`, `reasoning_effort: high`, `thinking: enabled`; no `length` stop in 65 requests. A length stop was not exercised, so the interaction with Pi's "length below model.maxTokens means compact" rule remains untested on this row.

## 5. What the model could have done better

1. **Bank before restructuring, then edit in pieces.** After #2 (20.5 min) the model made 20 probes that each replaced the entire 691-token calc region. Every probe ended with an error in the last third of the proof. Editing the region one step at a time while keeping the proof compiled would have yielded intermediate candidates (each scored) and a measured HB per step, using `arena_profile` of the new best. The profile at 21.5 min already listed the individual step costs (`conv_lhs` 2,017 HB, two simp steps about 1.1K each).
2. **Fix the free token loss in #2.** #2 is +50 tokens against the reference: the explicit `simp only [...]` lists are the extra tokens. At 0.027 pt per token that is 1.4 pt of the 11.4 pt gain. Trimming the outer-branch simp lists (flagged unused by the linter at lines 279 and 282 of #2) was a known, free, safe improvement; it was started (p30) but combined with a risky rewrite and never banked on its own.
3. **Do not read heartbeats from failing drafts as targets** (section 3).
4. **Cap the long thinking.** Two turns at 54K to 57K tokens cost $0.069 together (15% of spend, 12 min). In the A#42 turn the model was working on associativity bookkeeping of a product; later turns (A#44 to A#61) were mostly 15K to 22K tokens each. A draft that stalled twice in the same place (the reorder step) justified a smaller step, not a longer think.
5. **Use multi-draft probes.** 27 of 29 probes had one draft. Three or four small variants (for example the same failing region with different closing steps) would pay the same per-turn overhead for more information.

## 6. What the harness could have done better

Sorted by likely score per dollar.

1. **Report every error in a failing draft (error-recovery pass).** In `arena/engine.py` after a failing compile, re-run with the first erroring tactic replaced by `sorry` (up to 4 passes, 2 s of Lean time each) and return the list of errors with proof lines. Evidence: of the 20 post-best probes, 14 returned one or two errors; the model needed one probe per error (p19 to p25 fix the sign rewrite, then the bracket, then the pattern, in sequence). This is the largest lever: a failing draft is where almost all of the post-best $0.324 went, at roughly $0.016 per probe. Because the model's own reasoning is the expensive part, one probe revealing 3 errors can save two turns (about $0.03). Hook point: `arena/campaign.py:1416` `_model_view` already shapes the result.
2. **Do not show a heartbeat number for a failing draft** (or label it `heartbeat_partial`). `arena/campaign.py:1416` includes `heartbeat` for results that did not compile; `compat.heartbeats` repeats it. p19 to p30 showed 14.1K to 23.1K and the model used 16.6K as a projection. This costs nothing to fix and removes a misleading anchor; it does not change the scoring.
3. **Make the sorry goals usable.** `arena/engine.py:310` truncates each goal block to 1500 chars; in this run every skeleton from p11 on was cut at exactly 1500, and p9, p10, p26, p28, p29 had an empty first block. The model made 8 `lean_goal` calls (8 extra turns, about $0.02 to $0.03 including re-read). Options: hypothesis diff against the previous probe's goal (the let-bound `pa`/`pb` bodies repeat verbatim every time), print the turnstile line first, and write "hole not reached (earlier error at proof line N)" in place of `goals: ""`.
4. **Fix the Unicode name regex** (`arena/campaign.py` lines 324, 539, 541, 542, 649, 700, 792). Use `[^\W\d]` or an explicit Unicode identifier class. Also make `arena_declarations` name the rejected item and process the valid ones (one bad name currently rejects the batch). Effect here: 5 errors, 3 wasted turns, the target theorem unresolvable by `decl:` handle, `ι_*` declarations invisible to `arena_find`. The same bug will hit every Physlib/Mathlib row whose helper lemmas start with `ι`, `Φ`, `𝓣` and so on.
5. **Make compaction budget-aware.** `models.yaml:55` assumes ~$0.03 per compaction; this run paid $0.0553 + $0.0114 because the 352,586-token summary request hit no cache. Cached carry at 480K to 500K cost about $0.0014 to $0.0015 per request, so for the 12 requests that remained the saving was about $0.017. Rule of thumb: compact only if (expected remaining requests x context x cache-read price) exceeds (context sent x input price), and use the remaining allowance for the expected-requests estimate (about $0.007 per request here). At a $0.5 cap with a 1M window, raising `at_tokens` for DeepSeek to about 750K (or disabling it when remaining allowance is under about $0.15) would have left $0.05 for more probes. Keep the lrx bypass: the $0.187 worst-case estimate was above remaining allowance.
6. **Probe-batching nudge, factual only.** State in the probe tool result the count of drafts in the call and the median draft count so far ("1 draft this call; 27 of 29 calls so far had 1 draft"). Only the count, no direction. Low impact.
7. **Surface per-turn spend, factual only.** After a turn above 30K output tokens, append one line to the next tool result: "previous turn: 54,221 output tokens, $0.034 (6.8% of the allowance)". The existing `arena-memory` message already carries allowance; a per-turn line makes the cost of a long turn visible to the model. Low impact, no change in rules.
8. **Splice-style probe (larger change).** Let `arena_probe` accept `base: "#N"` plus a proof-line range to replace, so a draft that edits one region keeps everything else byte-identical and reuses the compiled prefix. It reduces tokens per draft (a draft here was 500 to 740 tokens, the output cost of rewriting unchanged text is part of the 7K-token average turn) and gives per-step HB deltas. Highest build cost, likely worthwhile for rows with 1000+ token references where the reference is the incumbent.

Fine points checked and found fine: cache behaviour (95.0%), Lean latency, gate decisions (64 allow, 0 deny), bookkeeping share (5.7%), finish refusal text (it says the smaller-saving axis has the most room, which is factual here: tokens -4%).

## 7. Why this row scores low, in one paragraph

The reference is already a 1217-token, 42K-HB proof built from one long `calc` with explicit intermediate terms. The cheap win (replacing four expensive `simp_all` calls) was found by 20.5 min and is worth +11.4 pt, almost all from heartbeats; the token axis moved the wrong way. Every remaining point (up to about +25 pt if the 650-token, 14K-HB shapes seen in failing drafts compiled) sat inside the calc region, where the model's attempts failed on one fine-grained mismatch after another, each costing a probe and a long thinking turn. Tool errors and Lean latency had no measurable effect on the score; the Unicode bug cost about three turns and left the key lemmas unsearchable by the arena tools. Budget went to output tokens ($0.266), uncached carry of those tokens ($0.100), compaction ($0.055), and cache reads ($0.038).
