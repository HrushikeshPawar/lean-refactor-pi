# Submission v2: Lean Refactor Arena warm-up benchmark (2026-10-09)

Two upload files. **You choose which one to submit.** ArkLib rows (3) are not covered here; another agent prepares them.

| File | Contents | Sum of proxies (12 rows) | Combined /15 |
|---|---|---|---|
| `submission.jsonl` | Best verified proof per row, **including 5 offline hybrids** | 976.22 | 65.08 |
| `submission-harness-only.jsonl` | Every row is the best proof of one harness run (no offline hybrids) | 932.64 | 62.18 |

The 12 rows are the 5 v1 rows plus the 7 v6cov rows. Proxy is our local estimate, not the official score. Numbers below are the cold-compile measurements in `results.jsonl` (cold heartbeats differ by a few from the run ledgers).

## Rows (best file)

| Theorem | Source | Hybrid? | Proxy | Tokens | HB | Ref tokens | Changed vs v1 |
|---|---|---|---|---|---|---|---|
| Core.InitsUpdatesComm | hybrid (v5/v6, `core_hybrid`) | yes | 87.10 | 76 | 203 | 224 | same |
| fundamental_theorem_of_variational_calculus' | hybrid v6 (`phys_hybrid`) | yes | 89.93 | 145 | 1575 | 851 | **new, was 88.25** |
| Cslib.CCS.bisimilarity_congr_choice | hybrid v6 (`cslib_hybrid`) | yes | 86.76 | 83 | 256 | 251 | **new, was 86.44** |
| CallElimCorrect.extractedOldExprInVars | hybrid v5 | yes | 82.42 | 77 | 487 | 222 | same |
| CallElimCorrect.substOldPostSubset | hybrid v5 | yes | 82.87 | 26 | 2230 | 313 | same |
| putnam_1964_a4 | v6cov DeepSeek run, #19 | no | 92.17 | 312 | 6515 | 1769 | new row |
| putnam_1964_b2 | v6cov DeepSeek run, #80 | no | 98.54 | 39 | 2895 | 1754 | new row |
| putnam_1995_a3 | v6cov DeepSeek run, #68 | no | 90.78 | 433 | 2412 | 4085 | new row |
| Electromagnetism...time_deriv_time_deriv_electricField_of_isExtrema | v6cov rerun DeepSeek, #13 | no | 78.32 | 573 | 6275 | 1372 | new row |
| FieldSpecification...ι_timeOrderF_superCommuteF_eq_time | v6cov DeepSeek run, #2 (the only candidate; near the reference) | no | 44.69 | 1267 | 26103 | 1217 | new row |
| Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress | v6cov DeepSeek run, #16 | no | 72.32 | 332 | 1006 | 408 | new row |
| Cslib.SKI.parallelReduction_diamond | v6cov DeepSeek run, #30 | no | 70.34 -> 70.32 cold | 240 | 416 | 407 | new row |

(SKI cold proxy is 70.32; the run reported 70.34.)

## Harness-only file: differences

Same as above for the 7 v6cov rows. The 5 v1 rows use single-run proofs: Core DeepSeek 86.07, PhysLib DeepSeek 88.25, CSLib DeepSeek 86.44, extractedOldExprInVars Luna 72.29, substOldPostSubset Luna 52.45 (the v1 harness-only choices; all re-verified cold).

## How hybrids were built and verified

- The 5 hybrids were assembled offline by Claude Code analysis agents from several model runs: `runs/analysis/*-hybrid-*.lean` (PhysLib: DeepSeek skeleton + Qwen's `hg _ (.smul_right ..)` + 4 small edits; CSLib: DeepSeek's proof with `symm_simulation ▸`; the other three as in v1).
- Each was cold-compiled with `verify.py` (`arena.engine.evaluate(..., "full")` under `force_cold()`), on all toolchains: Core v4.29.1/v4.27.0/v4.26.0; PhysLib v4.32.0; CSLib v4.33.0-rc2/v4.32.0/v4.31.0; CallElim v4.26.0; Putnam rows v4.25.0/v4.26.0/(v4.27.0 for a4, a3); EM and Field v4.32.0; Fsub v4.33.0-rc2/4.32.0/4.31.0; SKI v4.33.0-rc2/4.32.0/4.31.0/4.30.0. All passed with exit 0.
- No new hybrids were built for the v6cov rows. The top candidates of each run sit within 0.1-0.2 proxy of each other, differ by 1-3 tokens, and the ceiling from mixing the best-token and best-HB candidates is under 0.5 points per row (e.g. Fsub 335 tok/669 HB vs 332/1006). The Field row has a single candidate. The archived EM attempt (60.81) is worse than the rerun.
- Statement check (proof starts with the exact benchmark statement) and the official `_check_forbidden` filter (from `vendor/arena-space/app.py`) were run on every row of both files.

## Rule notes (carried over from v1)

1. **Track.** The closed-source LLM track is the natural fit (API dollars; DeepSeek V4.1 Flash and GPT-6 Luna, Qwen used only in a hybrid piece via API).
2. **Hybrids are a risk.** The 5 hybrid rows were assembled after the runs by Claude Code analysis agents, outside the harness, and their cost is not counted; organizers could not reproduce them from the harness code. This is why the harness-only file exists. It costs 43.58 proxy points in the sum.
3. **Spend per problem.** The v6cov rows come from one DeepSeek run each (soft cap about $0.50; only $3 is the hard cap). The v1 rows' harness-only proofs come from single runs at $0.46-0.56 (v6pilot) or about $0.10 (v5). Choosing the best across several runs of the same theorem adds up those runs' spend, still under $3 per row; the tech report should say so. The time_deriv row also had a discarded first attempt (truncated, archived) before the rerun, so its total spend is two runs.
4. Warm-up benchmark: `SUBMISSIONS_ENABLED = True`; code and report intake opens with the full benchmark. Rows left out count as 0 reduction.

## Files

`submission.jsonl`, `submission-harness-only.jsonl`, `cands/` (one .lean per verified candidate), `verify.py`, `run.sh`, `verify.log`, `verify.stdout`, `results.jsonl`.
