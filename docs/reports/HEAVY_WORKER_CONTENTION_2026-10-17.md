# Heavy-worker reuse and memory contention — 2026-10-17

## Scope

These are real-Lean, cached-toolchain, model-free checks against the current session-service code (`code=74c03d8fd24511f7` in all three service status replies). I ran the existing `arena lean load-test` path with an isolated `/tmp` service directory for each family, `ARENA_MACHINE_MAX_WORKERS=1`, one warm slot, two concurrent model-lane callers, no background callers, `weights=edit=1`, and a 12-second post-warm launch window (`--minutes 0.2`). Each generated edit appends a harmless comment. Each run ends with service shutdown; the logs show no remaining owned Lean processes.

The probes measure concurrent callers contending for one warm model worker on the row's selected measurement pin. They do not test foreground against background work, or concurrent work across several pins. The active pins were: CCS `v4.33.0-rc2` (`3aa9d441…`), Fiberwise `v4.31.0` (`c1712f6c…`), and Putnam B2 `v4.26.0` (`2df2f015…`). B2 also lists `v4.25.0`, but `engine.measure_version` selected `v4.26.0`; the load probe leased and checked only that pin. The older, separate two-pin B2 end-to-end replay reached 13.81 GiB sampled tree PSS and exhausted host swap; it is documented in [LEAN_RUNTIME_FOLLOWUP_MEASUREMENTS_2026-10-16.md](../LEAN_RUNTIME_FOLLOWUP_MEASUREMENTS_2026-10-16.md). These new single-pin results do not supersede or reproduce that configuration.

## Results

| Family and selected pin | Warm | Real checks | Reuse and latency | Sampled owned-tree peak PSS / RSS | Minimum MemAvailable / SwapFree |
|---|---:|---:|---|---:|---:|
| CCS, `v4.33.0-rc2` | 7.39 s | 6/6 passed | 0 fresh opens; edit p95 0.6 s, max 0.7 s | 1.98 / 2.43 GiB | 13.38 / 8.00 GiB |
| Fiberwise, `v4.31.0` | 35.24 s | 3/3 passed before the launch window closed | 0 fresh opens; observed edit wall 8.08–14.10 s | 5.23 / 5.94 GiB | 12.76 / 7.46 GiB |
| Putnam B2, `v4.26.0` | 29.09 s | 2/2 passed before the launch window closed | 0 fresh opens; edit p95 27.3 s, max 27.5 s | 7.37 / 8.04 GiB | 13.98 / 5.97 GiB |

The different counts are the requests actually admitted before the fixed post-warm window ended; `--max-checks 6` is a per-run ceiling, not a promise of six completed checks. For Fiberwise, the two simultaneous callers each began at elapsed 35.32 s: their end-to-end client waits were 8.08 s and 14.10 s, while their reported check times were 7.95 s and 6.03 s. For B2 both began at 29.17 s: client waits were 24.43 s and 27.50 s, while check times were 24.28 s and 3.11 s. The second B2 caller therefore waited about 24 seconds behind the first check, then completed on the same worker. CCS completed all six edits with 0.42–0.67 s client waits. Across all three runs the warm worker count remained one and every post-warm result reported `new_worker=false`.

Peak service estimates were 0.661 GiB for CCS, 3.60 GiB for Fiberwise, and 5.45 GiB for B2. These are worker-planning estimates from service status; the table's larger owned-tree PSS includes the command, daemon, and Lean process tree. The load-test memory-floor check passed in all runs (floor 3 GiB). B2's host `pswpin`/`pswpout` counters increased during its interval, but counters are host-wide and attribution to Lean is not possible. Its minimum observed free swap was still 5.97 GiB. Fiberwise also had host-wide page-out growth; CCS had no observed swap-counter delta. None of these measurements demonstrates memory use for simultaneous opens on multiple pins.

The harness returned exit 1 / `FAIL` for each edit-only run because criterion 2 requires a post-timeout probe and the selected workload contains no slow request. I did not alter that criterion or relabel the harness verdict. The independently recorded checks show zero unexpected failures/timeouts, zero fresh opens after warm-up, zero owned orphans, and MemAvailable above 12.7 GiB in every profile. This is a narrow reuse/queue observation, not a full foreground/background contention or timeout-recovery result.

## Setup attempt and validation boundary

The first CCS attempt under the default sandbox did not reach Lean: `ensure_service()` raised `SessionError: the Lean service does not answer` after about 37 seconds, and the private directory contained only `start.lock` with no service log or socket. That first attempt's same-tag wrapper outputs were reused by the successful replay, so its exact command output is not retained as a separate raw artifact; this paragraph records the observed exception and setup state. After the coordinator authorized the previously used local-only escalation path, the same isolated CCS profile started its private AF_UNIX service and completed. The three successful probes made no provider, model, network, download, or build calls.

## Artifacts

- CCS: [`ccs/load/report.md`](../../runs/analysis/heavy-worker-contention-2026-10-17/ccs/load/report.md), [`raw.jsonl`](../../runs/analysis/heavy-worker-contention-2026-10-17/ccs/load/raw.jsonl), [`ccs-telemetry.json`](../../runs/analysis/heavy-worker-contention-2026-10-17/ccs-telemetry.json), service log `/tmp/lrft-hwc-ccs-20261017/service.log`.
- Fiberwise: [`fiberwise/load/report.md`](../../runs/analysis/heavy-worker-contention-2026-10-17/fiberwise/load/report.md), [`raw.jsonl`](../../runs/analysis/heavy-worker-contention-2026-10-17/fiberwise/load/raw.jsonl), [`fiberwise-telemetry.json`](../../runs/analysis/heavy-worker-contention-2026-10-17/fiberwise-telemetry.json), service log `/tmp/lrft-hwc-fiberwise-20261017/service.log`.
- Putnam B2: [`b2/load/report.md`](../../runs/analysis/heavy-worker-contention-2026-10-17/b2/load/report.md), [`raw.jsonl`](../../runs/analysis/heavy-worker-contention-2026-10-17/b2/load/raw.jsonl), [`b2-telemetry.json`](../../runs/analysis/heavy-worker-contention-2026-10-17/b2-telemetry.json), service log `/tmp/lrft-hwc-b2-20261017/service.log`.
- The isolated 0.5-second process and host sampler is [`supervise.py`](../../runs/analysis/heavy-worker-contention-2026-10-17/supervise.py); its command, CSV/JSONL samples, GNU time output, stdout, and stderr are retained beside each family tag.

