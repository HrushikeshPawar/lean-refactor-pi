# Submission v3: Lean Refactor Arena warm-up benchmark, all 15 rows (2026-10-09)

There are two upload files, and **you choose which one to submit.** Both now contain all 15 rows.

| File | Contents | Sum of proxies (15 rows) | Combined /15 |
|---|---|---|---|
| `submission.jsonl` | Best verified proof per row, **including 5 offline hybrids** | 1263.75 | **84.25** |
| `submission-harness-only.jsonl` | Every row is the best proof of one harness run (no offline hybrids) | 1220.17 | 81.34 |

- v2 scored an estimated 65.08 with hybrids and 62.18 harness-only, out of 15 rows: 12 were included and 3 counted
  as 0.
- The official v2 score was 59.4%. Core scored 0% because the grader could not resolve github.com, an issue reported
  on Discord. v3 includes Core again.
- Proxy is our local estimate, not the official score.

## What changed from v2

| Theorem | Source | Proxy | Tokens (ref) | HB | Versions (all passed cold) |
|---|---|---|---|---|---|
| Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius | v6ark DeepSeek, #46 | **80.99** (new row) | 476 (1463) | 3831 | v4.31.0, v4.30.0, v4.29.0, v4.28.0 |
| Binius.BinaryBasefold.fold_advances_evaluation_poly | v6ark DeepSeek, #67 | **90.51** (new row) | 258 (1906) | 6766 | v4.31.0, v4.30.0, v4.29.0 |
| interleaved_affine_gaps_imply_tensor_gaps | v6ark2 DeepSeek, #77 | **85.14** (new row) | 225 (1353) | 2571 | v4.31.0, v4.30.0, v4.29.0 |
| FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | v6ark2 DeepSeek, #33 | **75.58** (was 44.69) | 590 (1217) | 10463 | v4.32.0 |

The other 11 rows are byte-identical to v2. Their sources, hybrids and verification are listed in
`../submission-v2/MANIFEST.md`.

## Verification (this folder)

- **`build.py`** builds both files from v2's files: it drops v2's FieldSpecification row and adds the 4 rows above.
  It then checks **all 15 rows** of both files:
  - each proof begins with the exact benchmark statement (`arena.engine.validate_proof`);
  - each proof passes the official forbidden-content filter (`_check_forbidden` from `vendor/arena-space/app.py`,
    loaded via `ast` because the app imports gradio).
  - Result: 0 problems in either file.
  - Both checks were tested and reject a modified statement, `sorry` and `native_decide`.
- **`verify.py`** cold-compiled the 4 new rows (`evaluate(..., "full")` under `force_cold()`) on every toolchain the
  official checker uses, one at a time (`run.sh`). All passed with exit 0, and every cold proxy equals the run's
  recorded proxy (`results.jsonl`, `verify.stdout`).

## Rule notes

1. **Spend per row.**
   - The 4 new rows each come from one DeepSeek run at a $0.50 soft cap. Settled spend was $0.451 for fiberwise,
     $0.453 for fold_advances, $0.459 for interleaved and $0.452 for FieldSpecification.
   - interleaved's first attempt (v6ark) died in a network outage after settling about $0.015 before the v6ark2 rerun.
   - FieldSpecification also had the v6cov run ($0.519). It is now superseded, but the report should count it.
   - The campaign log's "all-call cost" adds back reservations for failed requests that were never billed (ISSUES-v7
     #1/#2). Report settled spend.
2. **Hybrids are a rules risk.** These are the same 5 rows as in v2, which is why the harness-only file exists. The
   difference is 43.58 proxy points in the sum.
3. Rows left out of a submission count as 0. Both files have all 15.

## Files

`submission.jsonl`, `submission-harness-only.jsonl`, `cands/` (v2's candidates plus `fiber_ds`, `fold_ds`,
`inter_ds`, `field_v6ark2`), `build.py`, `verify.py`, `run.sh`, `results.jsonl`, `verify.stdout`.
