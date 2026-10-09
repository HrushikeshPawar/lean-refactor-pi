# v6ark: ArkLib campaign and FieldSpecification rerun (2026-10-09)

The campaign ran DeepSeek V4.1 Flash, one run per row, with a $0.50 soft cap, thinking high and two runs at a time,
on the full v6 code (`hrushikesh/v6-08-submission`).
- Two runs (interleaved and FieldSpecification) died in a network outage at 21:42 (`error_loop`) and were rerun as
  `v6ark2`.
- The per-run studies are in `docs/reports/v6ark/`, along with the submission v3 manifest.

## 1. Results

| Row (reference tok) | Proxy | Settled spend | Stop | Versions |
|---|---|---|---|---|
| fold_advances_evaluation_poly (1906) | **90.51** | $0.453 | finished | 3/3 |
| interleaved_affine_gaps_imply_tensor_gaps (1353) | **85.14** | $0.459 | finished | 3/3 |
| fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius (1463) | **80.99** | $0.451 | finished | 4/4 |
| FieldSpecification…eq_time (1217) | **75.58**, was 44.73 in v6cov | $0.452 | finished | 1/1 |

**Submission v3** (`runs/analysis/submission-v3/`) has all 15 rows, each one cold-verified, and every row passed the
statement check and the official filter.
- With hybrids, the proxy sum is 1263.75, about 84.25% combined (v2: about 65.1% estimated, 59.4% official).
- Harness-only, it is about 81.34%.

The campaign log's "all-call cost" ($3.30 for v6ark) adds reservations for failed requests that were never billed.
Settled spend is the real cost (ISSUES-v7 #1/#2).

## 2. v6 fixes, verified live

| Fix | Evidence |
|---|---|
| Unicode declaration names | 0 "Invalid declaration name" errors in any run (v6cov FieldSpecification had 5) |
| `compiled:false` / `heartbeat_to_failure` | Every failed draft that reached elaboration carries it (25/25 Field, 43/43 interleaved) |
| Budget footer | On every tool result (85/85, 92/92, 96/96, 93/93), and the model quotes it |
| Facts-only finish refusals | All runs stopped `finished` at 8–10% left |
| Routes from compiled proofs only | No route was opened by a `sorry` or failed draft |
| Locate/measure fixes and packet shedding | All 4 rows certified and ran; packets 36.9–39.95K characters |

**FieldSpecification before and after (same row and model):**
- 1 of 31 drafts compiled before, against 33 of 58 after;
- the proxy went from 44.73 to 75.58.

**Not observable:** compaction at 850K. Context peaked at 606–666K, so the trigger cannot be reached at a $0.50 cap.

## 3. Main new findings (details in `docs/ISSUES-harness-v7.md`)

- **#3: a network outage ends a run.** Three failed requests in a row stop it, with at most 30 s of backoff.
- **#1: holds on failed requests are never released.** The $0.116 reservations also count against the $3 hard gate.
- **#4: the packet still says `sorry` drafts open routes.** This is a v6 regression from `osu`, and it was live in
  all v6ark packets.
- **#5: routes are filed late,** in stalls of about 12 min that line up with a parallel run's memory use.
- **#5a: wrong parent labels.** In a batch, the last draft becomes the parent, and the label is wrong 10/33 to 35/50
  times by text. This motivates the graph and tool overhaul (backlog §5).
- **#8: the finish gate is read as a spend target.** The model reasons about spending down to the 10% line.
- **#25a: `lean_multi_attempt` is invisible.** It took up to 20% of spend.
- **#25b: a probe call waits for its slowest draft.**
- **#13: Lean warm-up of 1.5–6.7 min** before the first request.
