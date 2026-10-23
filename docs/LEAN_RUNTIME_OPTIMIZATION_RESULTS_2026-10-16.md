# Lean runtime optimization results — 2026-10-16

This report closes the five-step optimization evaluation described in the [handoff](../handoffs/2026-10-16-lean-runtime-optimization.md). It separates source/fake validation, bounded Lean measurements, and the unchanged final cold gate. No model/provider calls, campaign, download, or build ran for these measurements. The full accepted cold matrix and earlier source audit remain in [LEAN_TOOLCHAIN_AUDIT_2026-10-16.md](LEAN_TOOLCHAIN_AUDIT_2026-10-16.md).

## Five-step status

| Step | Change and evidence | Decision |
|---|---|---|
| 1. Visibility | Durable phase/job events and stderr mirrors; queue age starts from durable fast-check time where applicable; viewer freshness timestamps. Focused campaign/background/viewer validation is recorded in the handoff. | Keep. This gives operators current phase, queue, and fast/full freshness without changing check ownership. |
| 2. Salvage yield | Salvage yields between Lean requests for newly eligible full checks, deadline, or soft cap; active compile finishes and continuation state resumes. Fake compiler coverage and test results are in the handoff. | Keep. Priority changes do not cancel a running Lean request or alter the final gate. |
| 3. Demand growth | Paired serial Core measurement: worker growth fell from three workers to one; first request was 3.25s both times, second was 1.57s before and 0.79s after; sampled peak PSS/RSS fell from 1.22/2.17 GiB to 0.91/1.03 GiB. This is one short workload; CPU sampling is incomplete. | Keep. It supports removing speculative growth for serial demand, not a general latency claim. Raw pair artifacts are under [`step3/`](../runs/analysis/lean-runtime-optimization-2026-10-16/step3/). |
| 4. Memory admission | Admission uses the max of per-slot PSS, largest worker PSS, and 0.5 GiB floor after a valid sample; before then it keeps the 3 GiB fallback. Invalid samples do not lower the estimate and unopened reservations are excluded. The focused suite passed 61 tests; see the handoff. | Keep. The conservative startup fallback and bounded admission waits remain. |
| 5. Evaluation | Fresh Core c=1/2/3 edit-load probes, cached LSP/REPL parity, and an SKI endpoint-screen → known-result promotion → force-cold full check. Raw artifacts are under [`step5/`](../runs/analysis/lean-runtime-optimization-2026-10-16/step5/). | Do not enable a production endpoint shortcut from this evaluation. Treat the SKI flow as an experiment-only scheduling/reuse demonstration; retain all-pin promotion and the existing cold gate for acceptance. Leave REPL disabled. |

## Core edit-load probes

Each profile used `Core.InitsUpdatesComm` v4.29.1, one simulated run, six distinct trailing-comment edits, no background workers, and an explicit three-slot warm-up. Thus these measure warm comment-edit traffic and reuse, not tactic edits or default serial worker-demand growth. Runs were sequential, each with its own service directory. The harness's overall CLI exit was **1** for each profile because no slow check timed out and therefore no post-timeout probes existed. All six proof checks passed in each profile, with zero proof failures, zero timeouts, no fresh post-warm worker opens, and no orphans. The harness report is retained as FAIL with only criterion 2 (the intentionally absent post-timeout probe) failing; it is not relabeled as a passing load test.

| Concurrency | Check latency p50 / p95 / max | Wall / CLI exit | GNU CLI CPU | Sampled tree CPU | Peak PSS / RSS | Min MemAvailable / SwapFree | Max thermal / CPU frequency |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.3 / 0.5 / 0.5 s | 19.198 s / 1 | 0.35 s | 16.13 s | 1.22 / 2.16 GiB | 18.02 / 2.86 GiB | 92°C / 4200.0 MHz |
| 2 | 0.4 / 0.6 / 0.6 s | 19.168 s / 1 | 0.33 s | 17.98 s | 1.24 / 2.18 GiB | 17.99 / 2.86 GiB | 93°C / 4200.0 MHz |
| 3 | 0.5 / 0.7 / 0.7 s | 19.318 s / 1 | 0.32 s | 18.08 s | 1.24 / 2.18 GiB | 18.01 / 2.86 GiB | 89°C / 4200.0 MHz |

UTC windows were c=1 `17:15:28.790–17:15:47.988`, c=2 `17:15:58.495–17:16:17.664`, and c=3 `17:16:23.807–17:16:43.124` on 2026-10-16. PSS/RSS and host memory values are sampled maxima/minima over 0.5-second intervals. The peak-PSS samples used smaps PSS without RSS fallback. Each raw sample file names only its run's dedicated service PID; no other Lean service root appeared. GNU time encloses the CLI; sampled tree CPU covers the CLI/service PID tree and can miss short-lived work, so the CPU figures are distinct and should not be added. Six checks per point and three profiles are too small to support a scaling or tail-latency claim. Raw command JSON, stdout/stderr, harness report, GNU time, host snapshots, PID/start-time samples, and metrics are in `core-c{1,2,3}-edits/`.

## Cached REPL parity

The cache-only Core v4.29.1 probe used the already-built REPL binary and compared reference, trailing-comment edit, and an intentional unknown identifier. LSP and REPL both passed the first two and both rejected the bad name; all three outcomes matched (`overall_parity=true`). This is a small parity check, not broad equivalence or a speed comparison. `REPL_ENABLED` was false and remained false; the script restored its original value. No build or network call occurred. Its UTC window was 17:16:48.510–17:16:57.672; wall 9.162 s, sampled process-tree CPU 12.77 s, peak PSS/RSS 1.15/1.66 GiB, min MemAvailable/SwapFree 18.31/2.86 GiB, max thermal zone / CPU frequency 90°C / 3802.5 MHz. The wrapper did not produce a GNU `time -v` file, so no GNU CLI CPU is claimed for this row. See [`cached-repl-parity/result.json`](../runs/analysis/lean-runtime-optimization-2026-10-16/step5/cached-repl-parity/result.json) and its samples/logs.

## SKI endpoint screen and promotion

The reference proof in `Cslib.SKI.parallelReduction_diamond` had SHA256 `35f528e8e77dceff098e735cfb0ee98ea989fecca8258a7d59632f211cc5ffdc`; the four pinned projects were v4.33.0-rc2, v4.32.0, v4.31.0, and v4.30.0. The runner used production `engine.evaluate`, `engine.compile_version`, `known` results, and `force_cold` in this order:

| Stage | Checks / outcome | Wall |
|---|---|---:|
| Fast endpoint (v4.33.0-rc2, the measured version) | 1 passed | 4.959 s |
| Oldest endpoint (v4.30.0) | 1 passed | 4.854 s |
| Full promotion with endpoint results supplied as `known` | Both deferred middle pins compiled and passed; all four pins reported pass | 9.517 s |
| Final `force_cold` full evaluation | All four pins compiled cold and passed | 5.794 s |

The measured result used cold compilation in every production stage (`lean.path=cold`); it did not exercise warm LSP reuse for the endpoint stages. The fast result's compatibility count was one of four and was not treated as acceptance. Promotion performed two deferred middle checks, then the independent final gate performed four cold checks: screening changed order and deferred work, but did not reduce the accepted proof's total checks. The cold result had heartbeat count 1384, matching the promoted result exactly and therefore within the existing 5% `COLD_TOLERANCE`; its proof hash was identical. Screening never supplies a pass for an unknown or unpromoted middle pin.

No proof was rejected in this reference-proof sample, so it is not a measured false-safe/rejection test. The separate historical endpoint replay inventory reports zero endpoint-pass/middle-fail cases among complete saved full events; that historical count is context, not new step-5 measurement. Only promotion plus the unchanged all-version cold gate can accept a proof. See [`ski-promotion/result.json`](../runs/analysis/lean-runtime-optimization-2026-10-16/step5/ski-promotion/result.json), `telemetry.json`, `samples.csv`, and [`lean-endpoint-replay-inventory.md`](../runs/analysis/lean-audit-2026-10-16/source-audits/lean-endpoint-replay-inventory.md).

The SKI UTC window was 17:17:33.062–17:17:58.350. The command completed in 25.293s with GNU timed-work CPU 14.68s. The sampled tree reported CPU 5.92s and peak PSS/RSS 0.89/0.90 GiB; all production stages reported `lean.path=cold`, so the private service was not started. Min MemAvailable/SwapFree was 18.86/2.77 GiB and maximum thermal zone / CPU frequency was 86°C / 4212.2 MHz. GNU and sampled CPU are separate observations, not additive. Its final all-pin cold correctness result is explicit in the raw result.

## Interpretation and limits

- The c=1/2/3 edit probes show all six requests completed without proof errors or timeouts at each concurrency, with a small observed latency increase across the single trial. They do not establish throughput scaling or reliable tail behavior.
- Step 3 is the evidence for avoiding speculative worker growth under serial demand. Step-5's explicit three-slot warm-up intentionally does not retest that behavior.
- Cached REPL parity is one reference/edit/negative sample. Production remains on LSP; no REPL enablement is recommended from this probe.
- This experiment does not enable a production endpoint shortcut: no proof is accepted or rejected based only on endpoint results. The SKI flow only demonstrates experiment-side ordering and known-result reuse; it showed no rejection or runtime win. Keep all middle pins pending until promotion, and retain the final cold all-pin gate.
- Historical accepted full outcomes remain separately inventoried. No aggregate score, campaign result, or broad false-safe rate is inferred from this small probe set.
- Resource units above are binary GiB (KiB ÷ 1,048,576). CPU sampling is PID/start-time based at 0.5s and incomplete; GNU time is CLI-only where present. Host MemAvailable, swap, frequency, and thermal observations are whole-host snapshots, not Lean-attributed pressure.
- Two runner setup attempts failed before any Lean launch: the first C1 wrapper resolved the repository root incorrectly (127), and an initial SKI run lacked its fresh output directory (1). Both are preserved under `step5/setup-attempts/` and excluded from measurements.
- The campaign queue-age integration and viewer edits were made after the Lean probes and were not exercised by them. `engine.py` and `lean_session.py` remained frozen during step 5; report-close hashes for them and the final campaign/viewer sources and runner scripts are in [`source-hashes.json`](../runs/analysis/lean-runtime-optimization-2026-10-16/step5/source-hashes.json). The final combined fake regression after the fixture-only correction passed 220 tests and 3 subtests, skipped 69, in 42.85s with `ARENA_SLOW_TESTS=0`; no Lean/model/provider work ran. Ruff scoped validation passed with the pre-existing `RUF012` ignore, compileall passed, and both hub and dashboard JavaScript syntax checks passed. The full log and exact commands are in [`final-validation/`](../runs/analysis/lean-runtime-optimization-2026-10-16/final-validation/).
- The dedicated service sockets are absent, service logs end in shutdown, the REPL session reports shutdown, and no `python -m arena.lean_session serve` process remains from these probes.
