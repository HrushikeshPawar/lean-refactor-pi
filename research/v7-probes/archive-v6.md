# Archive cell keys on v6 runs

`archive_probe.py`; 20 runs with >=8 nodes and a keep (1791 nodes). Route = mix signature with hysteresis (route_replay.py), assigned causally in arrival order. Archive = best node per cell (proxy; closed with no proxy = 0; sketches ranked by fewer `sorry`). Depth = recorded-parent depth. K0 only covers nodes that have a v6 route event.

## Per-key summary (pooled over runs)

| key | cells median / mean / max | runs with <=12 cells | stability: diff-cell share of <=3-line pairs (total / route / depth / status / axis) | final best in archive | final-best lineage in archive (any / latest, mean over time) | cells visited mean | top-cell share mean / max |
|---|---|---|---|---|---|---|---|
| K0 | 2 / 18.0 / 316 | 19/20 | 0.086 / 0.086 / - / - / - (n=370) | 19/20 | 0.85 / 0.62 | 18.0 | 0.77 / 1.00 |
| K1 | 9 / 8.9 / 12 | 20/20 | 0.394 / 0.000 / 0.083 / 0.345 / - (n=505) | 20/20 | 1.00 / 0.73 | 8.9 | 0.35 / 0.79 |
| K2 | 4 / 3.6 / 6 | 20/20 | 0.345 / 0.000 / - / 0.345 / - (n=505) | 20/20 | 1.00 / 0.71 | 3.6 | 0.57 / 0.79 |
| K3 | 12 / 12.1 / 17 | 11/20 | 0.527 / 0.000 / 0.083 / 0.345 / 0.493 (n=505) | 20/20 | 1.00 / 0.79 | 12.1 | 0.31 / 0.79 |
| K4 | 3 / 2.4 / 4 | 20/20 | 0.000 / 0.000 / - / - / - (n=505) | 20/20 | 0.91 / 0.71 | 2.4 | 0.90 / 1.00 |

## Stall-move usefulness (m=12, lineage scope; firings pooled) (headline)

Descend = some LATER keep descends from the picked cell's best node (recorded lineage). Closest = the best node is among the text-closest earlier nodes of some later keep. Cell = some later keep is filed in the picked cell. Next = the very next keep is filed in the picked cell. Random = mean over 100 random non-empty cells per firing. Only firings with at least one later keep count.

| key | firings (with later keep) | descend: key / random | closest: key / random | cell: key / random | next keep cell: key / random |
|---|---|---|---|---|---|
| K0 | 8 | 50.0% / 65.2% | 0.0% / 19.8% | 12.5% / 39.0% | 12.5% / 39.0% |
| K1 | 8 | 75.0% / 51.4% | 0.0% / 7.9% | 0.0% / 7.6% | 0.0% / 7.6% |
| K2 | 8 | 100.0% / 71.9% | 12.5% / 20.9% | 25.0% / 29.0% | 25.0% / 29.0% |
| K3 | 8 | 100.0% / 54.4% | 0.0% / 5.6% | 0.0% / 4.9% | 0.0% / 4.9% |
| K4 | 8 | 100.0% / 87.0% | 12.5% / 28.9% | 37.5% / 57.8% | 37.5% / 57.8% |

## Stall-move usefulness (m=6, lineage scope; firings pooled) (sensitivity, more firings)

Descend = some LATER keep descends from the picked cell's best node (recorded lineage). Closest = the best node is among the text-closest earlier nodes of some later keep. Cell = some later keep is filed in the picked cell. Next = the very next keep is filed in the picked cell. Random = mean over 100 random non-empty cells per firing. Only firings with at least one later keep count.

| key | firings (with later keep) | descend: key / random | closest: key / random | cell: key / random | next keep cell: key / random |
|---|---|---|---|---|---|
| K0 | 31 | 64.5% / 74.6% | 6.5% / 21.7% | 22.6% / 44.1% | 19.4% / 42.4% |
| K1 | 32 | 84.4% / 54.4% | 3.1% / 10.8% | 6.2% / 10.8% | 6.2% / 10.8% |
| K2 | 32 | 93.8% / 71.0% | 9.4% / 20.4% | 15.6% / 27.6% | 15.6% / 27.6% |
| K3 | 32 | 93.8% / 55.0% | 3.1% / 8.4% | 6.2% / 6.1% | 6.2% / 5.5% |
| K4 | 32 | 90.6% / 82.9% | 18.8% / 31.6% | 37.5% / 60.5% | 37.5% / 60.5% |

## Per run

| run | nodes | keeps | fires | v6 routes in ledger? | mix routes | final depth | sub=final | K0 cells / topshare | K1 cells / topshare | K2 cells / topshare | K3 cells / topshare | K4 cells / topshare | K1 stab diff-cell | K1 lineage any/latest | K1 stall hit (desc/close of n) | K1 random |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ark:Binius.BinaryBasefold.fiberwise_dist_lt- | 76 | 32 | 1 | 45 | 2 | 37 | True | 1 / 1.0 | 9 / 0.32 | 3 / 0.59 | 14 / 0.22 | 2 / 0.99 | 9/24 | 1.00/0.71 | 0/0 of 0 | 0.0/0.0 |
| ark:Binius.BinaryBasefold.fold_advances_eval | 122 | 39 | 2 | 69 | 1 | 41 | True | 1 / 1.0 | 8 / 0.39 | 2 / 0.57 | 13 / 0.25 | 1 / 1.0 | 18/47 | 1.00/0.55 | 0/0 of 0 | 0.0/0.0 |
| ark2:FieldSpecification.WickAlgebra.-_timeOr | 61 | 24 | 1 | 34 | 4 | 27 | True | 3 / 0.5 | 11 / 0.21 | 5 / 0.54 | 15 / 0.16 | 4 / 0.95 | 12/23 | 1.00/0.66 | 0/0 of 0 | 0.0/0.0 |
| ark2:interleaved_affine_gaps_imply_tensor_ga | 130 | 43 | 3 | 78 | 1 | 38 | True | 2 / 0.96 | 8 / 0.31 | 2 / 0.59 | 12 / 0.17 | 1 / 1.0 | 12/52 | 1.00/0.42 | 1/0 of 1 | 1.0/0.0 |
| cov:Cslib.LambdaCalculus.LocallyNameless.Fsu | 59 | 11 | 2 | 59 | 2 | 10 | True | 2 / 0.98 | 7 / 0.41 | 3 / 0.68 | 10 / 0.41 | 2 / 0.98 | 8/13 | 1.00/0.64 | 0/0 of 1 | 0.4/0.2 |
| cov:Cslib.SKI.parallelReduction_diamond-DS | 54 | 19 | 1 | 54 | 2 | 22 | True | 1 / 1.0 | 12 / 0.22 | 4 / 0.52 | 17 / 0.22 | 2 / 0.91 | 4/8 | 1.00/0.70 | 0/0 of 0 | 0.0/0.0 |
| cov:FieldSpecification.WickAlgebra.-_timeOrd | 32 | 1 | 4 | 32 | 3 | 1 | True | 2 / 0.84 | 4 / 0.75 | 4 / 0.75 | 4 / 0.75 | 3 / 0.78 | 0/0 | 1.00/1.00 | 0/0 of 0 | 0.0/0.0 |
| cov:putnam_1964_a4-DS | 412 | 15 | 63 | 412 | 3 | 11 | True | 316 / 0.1 | 10 / 0.79 | 4 / 0.79 | 13 / 0.79 | 3 / 0.79 | 5/11 | 1.00/0.98 | 0/0 of 0 | 0.0/0.0 |
| cov:putnam_1964_b2-DS | 157 | 22 | 8 | 157 | 3 | 46 | True | 6 / 0.59 | 10 / 0.43 | 4 / 0.57 | 12 / 0.4 | 3 / 0.97 | 30/94 | 1.00/0.42 | 3/0 of 3 | 1.5/0.3 |
| cov:putnam_1995_a3-DS | 100 | 26 | 4 | 100 | 2 | 43 | True | 3 / 0.7 | 9 / 0.47 | 3 / 0.72 | 13 / 0.32 | 2 / 0.99 | 8/41 | 1.00/0.43 | 1/0 of 1 | 0.3/0.1 |
| cov:rerun-Electromagnetism.ElectromagneticPo | 46 | 10 | 1 | 46 | 3 | 9 | True | 2 / 0.65 | 10 / 0.3 | 5 / 0.46 | 10 / 0.3 | 3 / 0.7 | 2/6 | 1.00/0.78 | 0/0 of 0 | 0.0/0.0 |
| pilot:Core.InitsUpdatesComm-DS | 75 | 14 | 3 | 37 | 4 | 17 | True | 3 / 0.92 | 12 / 0.31 | 6 / 0.45 | 15 / 0.31 | 4 / 0.89 | 15/28 | 1.00/0.39 | 1/0 of 1 | 0.4/0.0 |
| pilot:Core.InitsUpdatesComm-Luna | 46 | 13 | 3 | 19 | 3 | 12 | True | 4 / 0.74 | 10 / 0.28 | 5 / 0.33 | 12 / 0.28 | 3 / 0.61 | 3/11 | 1.00/1.00 | 0/0 of 0 | 0.0/0.0 |
| pilot:Core.InitsUpdatesComm-Qwen | 59 | 11 | 3 | 34 | 3 | 12 | True | 2 / 0.97 | 8 / 0.32 | 4 / 0.56 | 11 / 0.25 | 3 / 0.95 | 12/19 | 1.00/0.85 | 0/0 of 0 | 0.0/0.0 |
| pilot:Cslib.CCS.bisimilarity_congr_choice-DS | 82 | 16 | 1 | 37 | 3 | 14 | True | 2 / 0.54 | 12 / 0.23 | 5 / 0.48 | 16 / 0.23 | 3 / 0.78 | 26/37 | 1.00/0.95 | 0/0 of 0 | 0.0/0.0 |
| pilot:Cslib.CCS.bisimilarity_congr_choice-Lu | 51 | 8 | 4 | 25 | 1 | 9 | True | 2 / 0.6 | 6 / 0.31 | 2 / 0.57 | 9 / 0.27 | 1 / 1.0 | 7/16 | 1.00/0.98 | 0/0 of 1 | 0.5/0.0 |
| pilot:Cslib.CCS.bisimilarity_congr_choice-Qw | 21 | 3 | 0 | 17 | 3 | 3 | True | 1 / 1.0 | 7 / 0.24 | 4 / 0.43 | 8 / 0.24 | 3 / 0.81 | 1/3 | 1.00/0.86 | 0/0 of 0 | 0.0/0.0 |
| pilot:fundamental_theorem_of_variational_cal | 109 | 25 | 3 | 64 | 1 | 26 | True | 4 / 0.72 | 8 / 0.3 | 2 / 0.58 | 12 / 0.21 | 1 / 1.0 | 15/40 | 1.00/0.49 | 0/0 of 0 | 0.0/0.0 |
| pilot:fundamental_theorem_of_variational_cal | 35 | 23 | 0 | 31 | 1 | 22 | True | 1 / 1.0 | 8 / 0.26 | 2 / 0.71 | 11 / 0.23 | 1 / 1.0 | 3/14 | 1.00/0.97 | 0/0 of 0 | 0.0/0.0 |
| pilot:fundamental_theorem_of_variational_cal | 64 | 19 | 2 | 10 | 3 | 24 | True | 2 / 0.6 | 10 / 0.22 | 4 / 0.59 | 14 / 0.22 | 3 / 0.97 | 9/18 | 1.00/0.75 | 0/0 of 0 | 0.0/0.0 |

Submission source node (run's own submission.json candidate) is in the K1 archive at the end in 20/20 runs; it equals the proxy-final-best in 20/20.

