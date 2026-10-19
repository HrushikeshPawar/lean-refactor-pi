# Lean runtime follow-up measurements — 2026-10-16

## Scope and status

Model-free, cached-toolchain measurements only. No provider, LLM, network, download, or build calls were made. Local Arena compile-tool and campaign APIs were exercised with recorded proofs and no model calls. Production sources were not edited. All new run artifacts are under [`runs/analysis/lean-runtime-followup-2026-10-16/`](../runs/analysis/lean-runtime-followup-2026-10-16/); progress is recorded in `progress.json`.

Three new live workload areas completed: end-to-end compile-tool replay, foreground/background contention with cooperative salvage yield, and repeated Fiberwise worker reuse. The original B2 repeated-request bench predates the current source changes; a fresh current-code one-pin sequence is now recorded below. An isolated audit-process control also compares current cooperative yield against the same run with only its yield callback disabled. The historical ledger census is complete, with two safe live fallback reproductions.

## Recorded compile-tool replay: Putnam 1964 B2

The same request was run twice against the same proof and two pinned projects. Each run created an isolated Arena run, invoked `arena.tools.compile_tool` directly with a saved request, and captured the full handler response and ledger. The request edits the exact reference proof only by adding a trailing comment, so it measures the tool path and compiler/session behavior rather than a proof improvement.

| Run | Path | Command wall | Tool handler wall | Lean work | Result |
|---|---|---:|---:|---|---|
| `lrft-b2-replay-01` | Cold control, `ARENA_LEAN_SESSION` unset | 87.04 s | 83.65 s | v4.25.0 26.38 s; v4.26.0 39.15 s | Passed 2/2 pins |
| `lrft-b2-replay-02` | Private session service | 76.64 s | 73.79 s | v4.25.0 26.34 s; v4.26.0 30.87 s | Passed 2/2 pins |

The session request timings split as follows:

| Pin | Queue | Header open | Check | Candidate preparation | Worker |
|---|---:|---:|---:|---:|---|
| v4.25.0 | 1.670 s | 6.721 s | 17.835 s | 0.001 s | New worker |
| v4.26.0 | 1.703 s | 10.953 s | 18.044 s | 0.003 s | New worker |

The tool recorded candidate-lock wait 0.002 s, Lean-lock wait 0.000 s, then materialized and filed the candidate. `evaluation_span` recorded 0.158 s for fast record/materialize/file and 0.075 s for the automatic full record. Those short ledger spans start after `probe_batch` has already compiled the draft; they are not end-to-end evaluation times. Total handler wall is the complete user-facing latency. The automatic full record reused the successful fast result for the same proof, so it added no extra Lean compile.

The cold control is intentional: the runner did not set a session socket. It is distinct from `cold-fallback`; it measures the ordinary cold path. The session replay used the existing `.venv`, cached workspaces, and a private `/tmp/lrf2/service.sock`. Both runs exited 0, returned the filed result, and retained their exact input, source/candidate SHA256, pins, request, response, and logs.

Session replay telemetry sampled at 0.5 s: 141 samples; peak owned-tree PSS 14,478,703 KB (13.81 GiB), peak RSS 15,828,020 KB (15.09 GiB), no RSS fallback at the peak sample; sampled tree CPU 127.87 s (incomplete). GNU time around the Python CLI recorded 0.89 s user + 0.53 s system; detached Lean service CPU is only in the sampled tree, and these totals are not additive complete CPU. Host MemAvailable minimum was 18,589,056 KB (17.71 GiB), SwapFree reached 0 KB, and host `pswpout` increased by 552,309 pages (about 2.11 GiB at 4 KiB/page). These host-wide swap counters cannot be attributed solely to this run. Highest thermal sensor reading was 85°C (`x86_pkg_temp`/`TCPU` at the start, raw readings preserved); max sampled CPU frequency was 3,975 MHz. The service logged `session shutdown`, removed its socket, and exited; no owned Lean process remained. Given the swap exhaustion, I did not repeat the B2 cold-start replay.

## Foreground compile, background salvage, and fast-to-full freshness

On Core `InitsUpdatesComm`, the runner filed an intentionally broken probe, then started the actual `campaign._run_salvage` path in a background-lane thread. While salvage's first real Lean request was active, the foreground path recorded and compiled a valid candidate. The fast candidate became eligible for a full check. Salvage finished its in-flight compile, checked eligibility at the next request boundary, and deferred with `reason=full_check_arrived`, `compiles=1`; it did not start its next proof compile. The full-only autocheck then ran all pending pins.

| Event | UTC / duration | Evidence |
|---|---:|---|
| Background salvage first compile | 2.43 s | Session path; new background worker; 2.116 s header + 0.288 s check |
| Foreground fast candidate | 0.89 s | Session path; reused model worker; check 0.758 s |
| Full check eligible → started | 1.45 s queue age | `eligibility_source=fast_evaluation`; job queue depth full=1, salvage=1 |
| Full check | 8.31 s | Background autocheck; all remaining pins passed |
| Salvage result | 1 compile, then deferred | `full_check_arrived`; next strategy round not compiled |

This is a live demonstration of the cooperative yield between Lean requests. It does not cancel a request already in flight. New contention command wall was 14.06 s; 28 samples at 0.5 s; peak PSS 3,326,207 KB (3.17 GiB), RSS 4,138,640 KB (3.95 GiB); max one RSS fallback process in the sample set. Host MemAvailable minimum was 20.15 GiB, SwapFree minimum 0.49 GiB, and max thermal sensor reading was 94°C (`x86_pkg_temp`/`TCPU`). The max worker PSS estimate visible in the service was 3.57 GiB after a valid sample. The private service logged shutdown and its socket was absent.

### Core current-yield versus isolated callback-disabled control

`core-yield-control-20261016/` runs the same saved `Core.InitsUpdatesComm` source, invalid probe, and valid fast candidate in two isolated campaign directories and private service directories. Candidate SHA256 was identical (`583dc698…`). The only experimental difference was an audit-process monkeypatch that passed `should_yield=None` into `salvage_proof`; no production file changed. Both actual Lean checks passed the valid candidate's full gate. The scheduler admitted the full job quickly in both runs: full queue ages were 0.04 s with yield and 0.06 s in the control. With yield enabled, salvage stopped after one compile as `deferred/full_check_arrived`; the full evaluation span was 8.781 s. With the callback disabled, salvage issued two compiles and ended `broken-no-progress`; the full evaluation span was 12.019 s. This single controlled pair shows one extra salvage request and 3.238 s more full-evaluation time under contention, while recorded scheduler queue age barely changed. It is not a historical old-implementation comparison and is only one pair, so it does not support a latency distribution claim.

| Mode | UTC start–end | Fast wall | Salvage compiles / outcome | Full queue age | Full span | Command wall | Peak PSS |
|---|---|---:|---|---:|---:|---:|---:|
| Yield enabled | 17:44:28.455–17:44:41.030 | 0.830 s | 1, deferred `full_check_arrived` | 0.04 s | 8.781 s | 12.576 s | 3,429,387 KB |
| Callback disabled in audit process | 17:44:49.764–17:45:05.630 | 0.911 s | 2, `broken-no-progress` | 0.06 s | 12.019 s | 15.869 s | 3,495,407 KB |

Both sessions were capped at two workers. Enabled/control peaks were 3,429,387/3,495,407 KB PSS (3.27/3.33 GiB), with one RSS-fallback process in each sample set; MemAvailable minima were 20,657,724/20,493,368 KB. The control's host `pswpin` delta was 1,134 pages and `pswpout` did not change; enabled deltas were 208/282 pages. Peak thermal readings were 92°C in both. Each private service logged shutdown and removed its socket. Raw phases, per-process samples, and event sequences are retained with each run.

## Heavy-row reuse, admission, throughput, and timeout context

### Fiberwise: new repeated session run

Four real checks used the exact historical Fiberwise reference and candidate saved in the audit artifacts. Three checks after the initial reference reused the same v4.31.0 worker; the second was the exact tactic-edited candidate, and the last two were harmless comment variants to repeat the incremental path.

| Request | Wall | Header | Check | Worker behavior | Result |
|---|---:|---:|---|---|---|
| Reference | 28.715 s | 20.610 s | 6.213 s | New worker; queue 1.778 s | Pass |
| Exact tactic edit | 4.670 s | — | 4.542 s | Reused; changed from line 1273 | Pass |
| Comment repeat 2 | 4.800 s | — | 4.716 s | Reused; changed from line 1279 | Pass |
| Comment repeat 3 | 3.643 s | — | 3.555 s | Reused; changed from line 1279 | Pass |

Candidate preparation stayed between 0.005–0.011 s. The service estimate moved from its 3 GiB startup fallback to a measured PSS high-water estimate of 3.57 GiB; status reported provenance `conservative PSS planning high-water`, with four valid samples after the four requests. This is one worker and one toolchain, not a concurrency/admission threshold sweep. All checks passed and none timed out. Telemetry: 84 samples at 0.5 s; peak PSS 5,436,708 KB (5.19 GiB), peak RSS 6,144,232 KB (5.86 GiB), zero RSS-fallback processes; min MemAvailable 19.68 GiB, min SwapFree 0.45 GiB; max sensor 94°C (`x86_pkg_temp`/`TCPU`); max frequency 4,136 MHz. Host `pswpout` rose by 13,354 pages (~52 MiB), a whole-host counter. Service shutdown and socket removal were confirmed.

The same saved candidate's prior warm reference→exact-edit replay also passed: v4.31.0 reference 34.91 s, then exact tactic edit 4.61 s on the same worker; its cold four-pin gate passed with per-pin times 13.57, 24.38, 28.76, and 42.55 s. This corroborates the one-worker repeat, but the prior cold pass is not a timing control for the session check.

### Putnam B2: prior three-repeat bench and new tool replay

The existing production-path B2 bench ran on v4.25.0 at the original pinned commit, with three repetitions per request type and a 180 s timeout. It completed 24 requests: every request reported `new_worker=false`, none timed out, and observed request times ranged from 0.21–19.57 s. Repeated reference checks took 14.19–19.57 s; edit checks 2.61–3.14 s. Peak sampled tree PSS was 8,560,853 KB (8.16 GiB), peak RSS 19,369,952 KB (18.46 GiB), and one sample used RSS fallback. This is historical context only; it predates current source changes and is not the fresh current-code comparison.

Fresh current-code replay `current-b2-onepin-20261016/` ran one v4.25.0 worker (commit `1ccd71f89cbbd82ae7d097723ce1722ca7b01c33`), with service max workers set to 1 and one pin per request. It compiled the reference and three saved incremental proof versions in parent order: `0c1141…` from the reference, `594560…` from `0c1141…`, and `b895af…` from `594560…`. All four passed. The reference took 19.03 s (queue 1.122, header 4.997, check 12.815, prepare 0.002); the three edits took 0.459, 0.394, and 0.385 s and reused the same worker (`new_worker=false`; changed-from lines 14, 16, 31). These saved snapshots are locally recorded candidate proofs; no provider call was made.

| UTC start–end | Variant | Proof SHA256 | Wall | Queue / header / check / prepare | Worker | Result |
|---|---|---|---:|---|---|---|
| 17:43:22.668–17:43:41.699 | Reference | `16f0c2b3…` | 19.032 s | 1.122 / 4.997 / 12.815 / 0.002 s | New | Pass |
| 17:43:41.794–17:43:42.252 | `0c1141…` | `35bc66c3…` | 0.459 s | 0 / — / 0.354 / 0.006 s | Reused, line 14 | Pass |
| 17:43:42.392–17:43:42.787 | `594560…` | `ff148db4…` | 0.394 s | 0 / — / 0.302 / 0.002 s | Reused, line 16 | Pass |
| 17:43:42.903–17:43:43.287 | `b895af…` | `90cb5419…` | 0.385 s | 0 / — / 0.290 / 0.002 s | Reused, line 31 | Pass |

The run lasted 21.01 s with 42 half-second samples. Peak tree PSS was 7,531,468 KB (7.18 GiB), RSS 8,199,388 KB (7.82 GiB). Host MemAvailable minimum was 20,191,536 KB (19.26 GiB); SwapFree minimum was 607,084 KB. Host `pswpin` rose by 1,367 pages (5.34 MiB) and `pswpout` by 20,254 pages (79.12 MiB); attribution is host-wide only. Thermal maximum was 94°C. No RSS fallback occurred. The service log contains shutdown and the socket was removed. This bounded one-worker run supports same-worker incremental reuse; it is not an estimate for opening both B2 pins concurrently.

The new end-to-end tool replay exercised both current B2 pins on newly opened service workers and passed the request through candidate preparation, Lean/session lock acquisition, header opens, checks, ledger writes, materialization and filing. Its high observed tree PSS and host swap exhaustion show that parallel per-pin opening can be much more memory intensive than the one-worker reused path above; the configurations differ and do not establish a regression by themselves.

Timeout context from the existing audit: the B2 repeated bench had 0/24 timeouts. A bounded Core timeout/recovery workload timed out its intentionally slow request at 2.01 s, retained the warm worker, and passed the next health probe in 0.33 s on that worker. Fiberwise's 180 s cold all-pin checks all passed, with the slowest at 42.55 s. These are separate workload/configuration results; no Fiberwise timeout was induced in this follow-up.

## Cold-fallback census and safe reproductions

The census parsed 175 recorded run ledgers (`runs/pi-budget/*/ledger.jsonl`): 5,036 evaluation events, 7,629 per-version evaluation results. `path=cold-fallback` occurred 138 times, all with the exact reason class `no room for a Lean worker: memory (...)`; 108 were full and 30 fast evaluations. All 138 were in three 2026-10-05 CSLib CCS runs: DeepSeek 57, GPT-6-Luna 62, Qwen 19. Exact available-memory text and per-event durations are preserved in `cold-fallback-census.json`.

The fallback compile durations summed to 10,984.09 s, ranged 35.16–136.36 s, median 74.17 s, and empirical p95 126.48 s. The exact reason strings vary by reported available memory, from 2.5 to 7.8 GB; 42 distinct exact strings are retained in the JSON. This is historical fallback latency and should not be read as the cost of a single deterministic proof or as a 2026-10-16 benchmark.

The census separately found 31 `path=cold` records with no reason. Four are from the explicitly intentional no-session B2 cold-control run above. The other 27 legacy cold-path records do not retain `force_cold` or service-configuration intent, so the ledger cannot classify those precisely as forced cold versus missing/unconfigured session. They are **not** counted among the 138 unexpected `cold-fallback` records.

Two safe live Core reproductions both passed using cached sources and cold Lean. An intentionally unreachable private socket reproduced `cold-fallback` with `session unreachable: FileNotFoundError` in 1.81 s. An audit-only stub returned the historical memory-admission refusal `no room for a Lean worker: memory (4.0 GB available)` and correctly drove the same cold path in 1.74 s. The second case validates fallback routing and reporting, not the actual service's memory admission decision. No production state was changed.

## Ranked harness findings

1. **Reuse B2's worker and bound simultaneous opens.** The fresh one-pin run spent 19.03 s on its reference, then only 0.39/0.39/0.38 s on three incremental variants through the same worker. The earlier two-pin cold session reached 13.81 GiB tree PSS and host SwapFree zero. Keep heavy-row opening demand-driven and cap simultaneous B2 workers; the host counters do not prove every swapped page belonged to Lean.
2. **Cooperative salvage yield reduces one avoidable background compile.** In the controlled Core pair, yield skipped salvage compile two after the full job became eligible. The callback-disabled control ran two salvage compiles and its full evaluation span was 3.24 s longer; scheduler queue age itself remained 0.04–0.06 s. This is a one-pair result, without a historical implementation comparison.
3. **Measured per-worker PSS can replace the startup estimate on Fiberwise.** The service's estimate became 3.57 GiB after four valid samples, and three incremental checks reused the same worker with no queue delay. This supports measured high-water admission estimates; one worker does not establish a safe global worker count.
4. **Historical memory denials were very expensive.** All 138 recorded fallbacks had the same worker-memory denial class, with a 74.17 s median and 126.48 s p95. Preserve this cause in operator-visible logs and continue scheduling around measured free-memory headroom.

## Artifacts and reproducibility

- B2 end-to-end: `lrft-b2-replay-01/02-{input,request,tool-result}.json`, corresponding `*-command.json`, `*-samples.jsonl`, `*-samples.csv`, `*-time-v.txt`, stdout/stderr logs; service directories `/tmp/lrf1` and `/tmp/lrf2` contain shutdown logs.
- Live contention: `contention-input.json`, `contention-result.json`, `contention-01-{command,samples.jsonl,samples.csv,telemetry,time-v,stdout,stderr}` and `runs/pi-budget/lrft-core-contention-01/ledger.jsonl`.
- Current-code B2 one-worker reuse: [`current-b2-onepin-20261016/`](../runs/analysis/lean-runtime-followup-2026-10-16/current-b2-onepin-20261016/), including the four exact proof hashes/results, progress, wrapper CPU, and flushed host/process telemetry.
- Core callback control: [`core-yield-control-20261016/`](../runs/analysis/lean-runtime-followup-2026-10-16/core-yield-control-20261016/), including both campaign event streams and telemetry; run ledgers are `runs/pi-budget/lrft-core-yield-enabled-20261016/` and `runs/pi-budget/lrft-core-yield-disabled-callback-20261016/`.
- Fiberwise reuse: `fiberwise-reuse-result.json`, `fiberwise-reuse-02-{command,samples.jsonl,samples.csv,telemetry,time-v,stdout,stderr}`. The first setup attempt failed before Lean because the runner's path root was one directory high; it is preserved as `fiberwise-reuse-*` logs. The corrected run is suffixed `-02`.
- Fallback census and controlled paths: `cold-fallback-census.json`, `fallback-repro.json`, and `fallback-repros-{command,samples.jsonl,samples.csv,telemetry,time-v,stdout,stderr}`.
- Existing B2 repeated bench: [`session-v2-putnam_1964_b2/`](../runs/analysis/lean-audit-2026-10-16/session-v2-putnam_1964_b2/), including `command.json`, 24 raw requests, 199 telemetry samples, service log and GNU time.
- Existing exact Fiberwise warm/cold replay: [`candidate-replays/003ace87ceb8/`](../runs/analysis/lean-audit-2026-10-16/candidate-replays/003ace87ceb8/); the other exact candidate is [`candidate-replays/ab0f537560e8/`](../runs/analysis/lean-audit-2026-10-16/candidate-replays/ab0f537560e8/).

Sampling uses PID plus `/proc/<pid>/stat` start time to avoid PID reuse, samples `smaps_rollup` PSS and falls back per process to RSS only when unavailable, and flushes JSONL samples during each live workload. GNU time wraps the Python CLI; the detached Lean service tree is sampled separately. CPU and host memory/swap/PSI/frequency/thermal data have the scope and caveats stated above. No tests were run for this measurement-only task.
