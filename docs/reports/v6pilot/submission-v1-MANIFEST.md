# Submission v1: Lean Refactor Arena warm-up benchmark (2026-10-08)

There are two upload files. **You choose which one to submit.**

| File | What it contains | Sum of proxies over 5 rows |
|---|---|---|
| `submission-harness-only.jsonl` | Every row is the best proof of a single harness run, within that run's budget. It is reproducible from our code. | 385.50 |
| `submission.jsonl` | The best verified proof per theorem, **including 3 hybrids that analysis agents assembled offline** from several runs. | 427.07 |

## Rows

Proxy is our local score estimate, not the official score. Tokens count the proof body; HB is heartbeats.

| Theorem | Harness-only (source, proxy, tok, HB) | Best (source, proxy, tok, HB) | Reference tok |
|---|---|---|---|
| Core.InitsUpdatesComm | v6pilot DeepSeek, 86.07, 83, 202 | hybrid (v5), 87.10, 76, 203 | 224 |
| fundamental_theorem_of_variational_calculus' | v6pilot DeepSeek, 88.25, 160, 1967 | same | 851 |
| Cslib.CCS.bisimilarity_congr_choice | v6pilot DeepSeek, 86.44, 85, 263 | same (the v5 hybrid scored 84.52) | 251 |
| CallElimCorrect.extractedOldExprInVars | v5-gen Luna, 72.29, 141, 529 | hybrid (v5), 82.42, 77, 487 | 222 |
| CallElimCorrect.substOldPostSubset | v5-gen Luna, 52.45, 239, 3431 | hybrid (v5), 82.86, 26, 2231 | 313 |

The source files are in `cands/`, and each one is a copy of the run's `submission.lean` or of `runs/analysis/*-hybrid-*.lean`.

## Verification (`verify.log`, `results.jsonl`)

- **Cold compile:** every candidate was compiled from scratch with the harness checker (`arena.engine.evaluate(..., "full")` under `force_cold()`) on each toolchain the official checker uses:
  - Core: v4.29.1, v4.27.0, v4.26.0;
  - PhysLib: v4.32.0;
  - CSLib: v4.33.0-rc2, v4.32.0, v4.31.0;
  - CallElim: v4.26.0.

  All passed with exit 0.
- **Statement:** each proof starts with the benchmark row's exact `statement` text from `vendor/arena-space/benchmark_data_warmup.jsonl`. The two CallElim rows begin with `open OldExpressions in`, exactly as the benchmark does.
- **Forbidden patterns:** each proof passes the official `_check_forbidden` list, run against the source of `vendor/arena-space/app.py`. That list includes no `sorry`, `axiom`, `native_decide` or auxiliary declarations, and a limit of 256 KB per proof.
- **Names:** every row name is a benchmark id. The benchmark has 15 rows.

## How scoring treats rows you leave out

`leaderboard.py` says theorems missing from a submission count as **0 reduction**, which is the same as not improving them. Rows are ranked by combined %, so adding every verified improvement only helps. The other 10 warm-up rows (Mathlib, ArkLib, PutnamBench, Strata…) are not covered yet.

## Rule notes: please read before choosing

1. **Track.**
   - Closed-source LLM track: the models are API models, $3 of API spend per problem at list prices, and you upload proofs, the full harness code and a tech report.
   - Open-source track: open weights, and the run must work on 4×A100 within 48 h.
   - Our proofs come from DeepSeek V4.1 Flash and GPT-6 Luna through APIs. Luna is closed; DeepSeek has open weights but we called it through an API. The **closed track** is the natural fit, since its budget is defined in API dollars.
2. **Hybrids are a risk.** The 3 hybrid rows (Core 87.10, extract 82.42, subst 82.86) were assembled after the runs, by Claude Code analysis agents combining proofs from several model runs. That step is not part of the harness and its cost is not counted, so organizers could not reproduce those rows from the harness code. This is the main reason the harness-only file exists.
3. **Spend per problem.**
   - Every harness-only row comes from one run with a soft cap of $0.50 or less: the v6pilot runs settled $0.46–$0.56, and the v5 runs about $0.10.
   - Choosing the best across several runs of the same theorem adds up those runs' spend. It is still under $3 for every row here, but the tech report should state it.
4. This is the **warm-up** benchmark: `SUBMISSIONS_ENABLED = True`, and code and report intake (`ARTIFACTS_ENABLED`) opens with the full benchmark.

## Upload steps (from the site)

1. Benchmark tab: confirm the ids still match. They were checked against our vendored copy of the app.
2. Choose the track (Closed-source LLM) and a **stable username** of 2–40 characters. The first person to use a name claims it.
3. Upload the chosen `.jsonl`, and **save the submission key** the site shows: it unlocks "My submissions".
4. You can close the tab; scoring runs in the background. A row that fails to compile, has a changed statement, or contains `sorry` scores 0% on every axis.
