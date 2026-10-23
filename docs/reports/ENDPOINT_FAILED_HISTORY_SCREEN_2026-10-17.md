# Endpoint screening against failed histories — 2026-10-17

## Scope and method

This is a read-only replay of saved evidence. I scanned all 178 `runs/pi-budget/*/ledger.jsonl` files. Of these, 176 have an initialized theorem row and contribute to per-theorem counts; `test-scratch-fix` and `test-search-fix` have no theorem-bearing `init` event and are listed as excluded in the scan artifact. I grouped evaluation events by theorem and used the saved pin sets (cross-checked against `benchmark/original/warmup.jsonl`) to define each theorem's oldest endpoint, newest endpoint, and middle pins. I counted full events, not unique candidate IDs. A missing `compat` entry or a non-Boolean `passed` value is unknown, never a pass. The scan read saved ledgers and proof snapshots only; no Lean, model, provider, network, or campaign commands ran.

Endpoint screening remains disabled. The source currently distinguishes fast and full evaluation: `arena/engine.py` checks all targets for `full`, while `fast` checks the first target (and may also the measured version) and stops after its first failure. A fast result therefore cannot establish compatibility on omitted middle pins.

## Multi-pin full-event results

The endpoint-relevant corpus contains nine theorems with at least three distinct pins. All **1,451/1,451** full events contain an explicit Boolean result for every expected pin. There are no missing pin keys, missing middle results, or unknown `passed` values in these full events.

| Theorem | Pins, oldest to newest | Full events | Failed full events | Both endpoints pass, middle fails |
|---|---|---:|---:|---:|
| `Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius` | `v4.28.0`, `v4.29.0`, `v4.30.0`, `v4.31.0` | 72 | 0 | 0 |
| `Binius.BinaryBasefold.fold_advances_evaluation_poly` | `v4.29.0`, `v4.30.0`, `v4.31.0` | 230 | 2 | 0 |
| `Core.InitsUpdatesComm` | `v4.26.0`, `v4.27.0`, `v4.29.1` | 423 | 1 | 0 |
| `Cslib.CCS.bisimilarity_congr_choice` | `v4.31.0`, `v4.32.0`, `v4.33.0-rc2` | 120 | 0 | 0 |
| `Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress` | `v4.31.0`, `v4.32.0`, `v4.33.0-rc2` | 104 | 0 | 0 |
| `Cslib.SKI.parallelReduction_diamond` | `v4.30.0`, `v4.31.0`, `v4.32.0`, `v4.33.0-rc2` | 215 | 17 | 0 |
| `interleaved_affine_gaps_imply_tensor_gaps` | `v4.29.0`, `v4.30.0`, `v4.31.0` | 112 | 0 | 0 |
| `putnam_1964_a4` | `v4.25.0`, `v4.26.0`, `v4.27.0` | 83 | 0 | 0 |
| `putnam_1995_a3` | `v4.25.0`, `v4.26.0`, `v4.27.0` | 92 | 0 | 0 |
| **Total** |  | **1,451** | **20** | **0** |

Every failed full event failed at least the oldest endpoint. The 20 failures account for 27 false per-pin results: 2 on `v4.29.0` for Binius fold advances, 1 on `v4.26.0` for Core, and 24 on SKI. Seven SKI events fail both `v4.30.0` (oldest endpoint) and `v4.31.0` (a middle pin); the other ten SKI failures affect only the oldest pin. Thus the corpus contains real middle-version proof failures, but all seven are already rejected by an endpoint screen because the oldest endpoint also fails.

The failure diagnostics are proof/compiler errors, not Lean timeouts. For example, SKI candidate `2225fdca…` in `runs/pi-budget/v7-check4-Cslib.SKI.parallelReduction_diamond-deepseek-v4.1-flash-r1/ledger.jsonl` has an `Unknown identifier le_join_of_refl` error on both `v4.31.0` and `v4.30.0`, while `v4.32.0` and `v4.33.0-rc2` pass. Core candidate `b520ebac…` in `runs/pi-budget/smoke-harness-20261005/ledger.jsonl` passes `v4.29.1` and `v4.27.0` but has syntax and unsolved-goal diagnostics on `v4.26.0`. These examples show why an endpoint failure should reject, while a middle failure cannot be inferred from endpoint successes alone.

## Failed fast histories

Among the same nine multi-pin theorem rows, there are 1,913 fast evaluation events. Forty-nine fail, all on Core's newest endpoint `v4.29.1`; the saved compat entries contain proof diagnostics. The 49 events represent 48 distinct candidate IDs. None has a same-run full event for that candidate ID. These are fast-screen rejections, not endpoint false-safes, and their one-version results say nothing about the skipped middle pins. One example is candidate `e8b48029…` in `runs/pi-budget/test-cafb588a07/ledger.jsonl`, which records a Core proof `Type mismatch` diagnostic at `v4.29.1`.

## Cold-check disagreements and timeouts

The nine multi-pin rows contain 78 cold-verification events. Two exact candidate IDs have same-run full-session maps that pass every pin, followed by a cold map with `v4.28.0` (the oldest endpoint for the Binius fiberwise theorem) false. One cold event explicitly says `Lean timed out after 60 seconds` (`runs/pi-budget/v8c-Binius.BinaryBasefold.fiberwise_dist_lt-gpt-6.1-sol-r1/ledger.jsonl`, candidate `ab0f5375…`). The other (`runs/pi-budget/v6ark-Binius.BinaryBasefold.fiberwise_dist_lt-deepseek-v4.1-flash-r1/ledger.jsonl`, candidate `003ace87…`) has no retained per-pin error or diagnostic, so its cause is unknown. Neither is a middle-pin disagreement, and neither should be classified as a proof rejection based on the available cold record.

The cold disagreement records are distinct from the 20 full-event proof failures above. The full failures have explicit compiler diagnostics; the cold timeout is an infrastructure/evaluation outcome, and the older cold record lacks enough detail to classify. A cold pass map is required for acceptance, and endpoint screening cannot replace the existing all-pin cold gate.

## Decision and limits

This recomputation finds zero endpoint-pass/middle-fail examples in the complete saved full histories. It does **not** establish that endpoint passes imply middle-pin passes: no such false-safe case appears in the corpus, and every observed middle error is paired with an oldest-endpoint error. Fast events also lack middle-pin coverage by construction. Keep screening disabled; any future endpoint experiment may use it only to reject candidates after an endpoint failure, with missing results treated as unknown, while the complete all-version cold gate remains the acceptance rule.

The counts are saved-history counts, not independent candidate trials or a measured false-safe rate. Repeated candidates and correlated campaign edits exist. The two Binius cold disagreements further show that session full maps and later cold checks can diverge on the oldest endpoint; the retained evidence does not justify averaging those outcomes or attributing the unexplained event to a proof error.

## Evidence pointers

- `runs/pi-budget/*/ledger.jsonl` — source evaluation and cold-verification records scanned.
- `runs/pi-budget/*/proofs/<candidate_id>.lean` — exact filed candidate snapshots, where retained.
- `benchmark/original/warmup.jsonl` — expected theorem pin inventories.
- `arena/engine.py` — `evaluate()` selects all versions for `full`, and a bounded target set for `fast`.
- `runs/pi-budget/v7-check4-Cslib.SKI.parallelReduction_diamond-deepseek-v4.1-flash-r1/ledger.jsonl` — SKI endpoint plus middle proof-error example.
- `runs/pi-budget/smoke-harness-20261005/ledger.jsonl` — Core oldest-endpoint proof-error example.
- `runs/pi-budget/v6ark-Binius.BinaryBasefold.fiberwise_dist_lt-deepseek-v4.1-flash-r1/ledger.jsonl` and `runs/pi-budget/v8c-Binius.BinaryBasefold.fiberwise_dist_lt-gpt-6.1-sol-r1/ledger.jsonl` — cold disagreement pair.
- [`scan_endpoint_history.py`](../../tools/audits/endpoint-failed-history-2026-10-17/scan_endpoint_history.py) — exact offline scanner used for the recomputation; run it from the repository root with `python tools/audits/endpoint-failed-history-2026-10-17/scan_endpoint_history.py`.
- [`scan-results.json`](../../tools/audits/endpoint-failed-history-2026-10-17/scan-results.json) — deterministic counts, per-theorem outcomes, anomaly IDs, and SHA-256 digests for all 178 scanned ledger files.
