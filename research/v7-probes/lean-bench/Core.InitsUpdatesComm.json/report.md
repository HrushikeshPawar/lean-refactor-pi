# Lean load test: FAIL

## Criteria

- PASS  1 no timeouts or failures except the deliberate slow kind: 0 timeouts, 0 other failures
- FAIL  2 post-timeout probe p95 < 10 s: no probes measured; 0 slow checks timed out
- PASS  3 model-lane non-slow p95 < 30 s after warm-up: n=8, p95=0.5 s
- PASS  4 zero fresh worker opens after warm-up (except after a crash): 0 fresh opens, 0 crashes logged
- PASS  5 zero orphan Lean/lake processes: 0 orphans
- PASS  6 MemAvailable never below 3 GB: min 21.08 GB

## Configuration

```json
{
  "rows": [
    "Core.InitsUpdatesComm"
  ],
  "runs": 1,
  "concurrency": 1,
  "background": 0,
  "minutes": 2.0,
  "timeout": 60.0,
  "seed": 1,
  "weights": {
    "sorry": 2.0,
    "reference": 2.0,
    "edit": 2.0,
    "error": 1.0
  },
  "max_checks": 8,
  "think": 1.0,
  "slots": null,
  "out": "runs/analysis/experiments/lean-bench/Core.InitsUpdatesComm.json"
}
```

## Warm-up per run

| run | warm op | warm-up s | ok | note |
|---|---|---|---|---|
| 0 | warm | 8.2 | True |  |

## Latency by kind, lane and version (seconds)

| kind | lane | version | n | p50 | p95 | max | timeouts | failed |
|---|---|---|---|---|---|---|---|---|
| edit | model | v4.29.1 | 3 | 0.5 | 0.5 | 0.6 | 0 | 0 |
| error | model | v4.29.1 | 1 | 0.3 | 0.3 | 0.3 | 0 | 0 |
| reference | model | v4.29.1 | 3 | 0.3 | 0.5 | 0.5 | 0 | 0 |
| sorry | model | v4.29.1 | 1 | 0.3 | 0.3 | 0.3 | 0 | 0 |

## Key metrics

- post-timeout probes: n=0, p50=- s, p95=- s, max=- s
- fresh worker opens after warm-up: 0
- min MemAvailable: 21.1 GB (start 22.1 GB)
- peak Lean/lake processes: 6
- peak mount.ntfs CPU: 0.0 %
- orphans: none
- requests: 8
