# v6cov: coverage campaign results and findings (2026-10-09)

The campaign covered 7 new benchmark rows with DeepSeek V4.1 Flash, one run each.
- Each run had a $0.50 soft cap and thinking set to high, with 2 runs at a time.
- Commits `lrx` (compaction bypasses the budget guard) and `vqm` (Pi sees the enforced per-request output limit; DeepSeek 64K) landed mid-campaign. They were live from FieldSpecification onward and in the time_deriv rerun.
- One study per run is in `docs/reports/v6cov/`, along with the submission v2 manifest.

## 1. Results

| Row (reference tok) | Proxy | Spend | Stop | Code |
|---|---|---|---|---|
| putnam_1964_b2 (1754) | **98.54** | $0.528 | soft cap | old |
| putnam_1964_a4 (1769) | 92.17 | $0.456 | finished | old |
| putnam_1995_a3 (4085) | 90.81 | $0.408 | error_loop (compaction bug) | old |
| time_deriv…isExtrema (1372) | 78.33 rerun / 60.81 original | $0.466 / $0.394 | finished / stopped | new / old |
| Fsub.Typing.progress (408) | 72.32 | $0.458 settled | finished | new |
| SKI.parallelReduction_diamond (407) | 70.34 | $0.453 settled | finished | new |
| FieldSpecification…eq_time (1217) | 44.73 | $0.519 | finished | new |

**Submission v2** (`runs/analysis/submission-v2/`) has 12 rows, all cold-verified on every toolchain the official checker uses:
- with hybrids: proxy sum 976.22, about 65.1% combined (v1 scored 28.45%);
- harness-only: about 62.2%.

The 3 ArkLib rows are still to come.

## 2. What the fixes did (new-code runs)

- **`vqm`:** every request carried `max_tokens 64000`. There were 0 `length` stops across 4 runs. Turns of 35–40K output tokens, which would have been cut off at 32K, finished normally.
- **`lrx`:** each new-code run had one threshold compaction at about 503–509K tokens. All four went through on the bypass. In two of them the estimate exceeded the remaining allowance, so the old guard would have blocked them.
- **a3 ended on the old code from a threshold compaction, not a length stop:**
  1. The turn-prefix summary was refused by the guard.
  2. Pi retried that as an overflow, which failed the same way.
  3. The next agent request was measured against a `priorRequest` seeded by the summary and refused three times, so `error_loop` fired.
- **b2 and a4 never compacted.** Their compactions failed 23 and 24 times in a row on the same bug.

## 3. Findings across runs, ranked by score per dollar

1. **Compaction at 500K loses money at a $0.5 cap.** It cost $0.055–0.075 (summary plus the cold turn after it) in all 4 new-code runs, against about $0.015 of cache savings afterwards. Break-even is about 50 more requests; about 10 remained.
   - The `models.yaml` comment (~$0.03) is stale.
   - In Fsub, the compaction's cost opened the finish gate (23% → 8% remaining).
   - **Rule:** compaction itself is never budget-checked. The lever is where it triggers: DeepSeek's `at_tokens` against its 1M window, or making the summary request cache-friendly.
2. **The finish-refusal text contradicts the gate.** The gate refuses only on the ≤10% remaining rule. The text says a credited route unlocks the next confirm, and that "micro-golf will not close it" (`rules.ts` `finishPush`, `arena.ts` around line 1101).
   - The model chased route credit in a4 (37 of 49 turns, $0.153), b2 and a3.
   - The gate itself is intended (unspent allowance has no value) and paid off in SKI (+6.4 after a refusal at 55% left).
   - The text should state only facts: amount left, the 10% rule, points left per axis.
3. **The model can't see its spend.** It used `arena_finish` as a budget meter in every run, and its own estimates were off by about 2×. **Fix:** a factual spent/remaining line in the `[arena]` tool footer.
4. **Route credit by text similarity fails both ways.**
   - In a4, 314 drafts of the same two lines with only a numeral changed (`hB 20` … `hB 1003`) each counted as a new route. Claim hashes and goal signatures don't normalise literals.
   - In SKI, no route could ever be credited, because every proof shares the same constructors (similarity 0.56–1.00 against a 0.5 threshold).
   - Labels such as "no induction · −27" show the model proof-content framing, which breaks the neutral-framing rule.
   - See backlog §4b (shallow-branch credit). The default parent is the newest compiled candidate, which is what makes the chains deep.
5. **Heartbeats on failing drafts mislead the model** (FieldSpecification, Fsub, b2). The number is only the work done before the error. Report `compiled:false` at the top level and rename it `heartbeat_to_failure`.
6. **ASCII-only declaration-name regex** (`arena/campaign.py` lines 324, 539–549, 649, 700, 792). This caused all 5 FieldSpecification tool errors (`ι_*` names), and those lemmas were unsearchable with `arena_find`. **ArkLib and Mathlib names use Greek letters and subscripts too: fix before the ArkLib campaign.**
7. **Unexplained full cache misses:** Fsub request 29 ($0.056) and b2's final request ($0.085). In both, the request prefix was nearly identical to the previous one and no time had passed. `cacheAlarm` fires only on `write > read`; it should also fire on `cacheRead == 0` after a cached request.
8. **Sorry and goal output gaps:**
   - `_SORRY_TACTIC` misses `| case => sorry` (6 of 9 SKI stubs returned no goals).
   - Goals are cut at 1500 characters.
   - `lean_goal` out-of-range errors don't give the candidate's line span.
9. **Cross-version results reach the model one turn late,** about 80 s, though the check finishes 1.1 s after the fast eval. In SKI, 3 candidates ($0.033) were built on a name that fails on v4.30.0.
10. **Unsettled reservations inflate the reported cost:** Fsub +$0.052, SKI +$0.043. Settle aborted streams from what was actually sent.
11. **Smaller items:**
    - `arena_find` misses generated declarations (`fun_deriv_sub`);
    - truncated turns' reasoning is dropped (a3 re-derived it);
    - cold verification runs inside `arena_finish` (a3: 409 s);
    - route extraction lags (median 79 s; 149 route events landed after a4 ended);
    - `grind` is described as "expensive" in SKILL.md, which held b2 back until the model measured it itself.

## 4. Model behaviour (DeepSeek V4.1 Flash)

- **Strong:**
  - most of the score comes early (a3: 97% of the gain by 43% of spend; b2: 89.88 on the first compile);
  - it prices trade-offs in points;
  - it rarely sends duplicate drafts.
- **Weak:**
  - reasoning is 87–91% of output tokens, and output is about 60% of spend;
  - it rewrites big regions in one go instead of editing a compiled candidate step by step (FieldSpecification: 0 compiled drafts after #2);
  - it learns tactic behaviour by trial and error (SKI: 11% of the cap);
  - it seldom profiles the candidate that matters (a4 never profiled #19, where one `simp` held 54% of the heartbeats).
