# Lean toolchain and harness audit — 2026-10-16

## Scope and outcome

This audit ran only local Lean workloads: direct cold evaluation, the existing serial Lean bench, and exact saved proof replays. No campaign runner, provider, model, network request, or campaign/provider LLM API was invoked. No harness implementation or GitButler branch/state was changed, and nothing was committed or pushed. Audit report and measurement artifacts were written locally under `docs/` and [`runs/analysis/lean-audit-2026-10-16/`](../runs/analysis/lean-audit-2026-10-16/).

The installed inventory contains **10 distinct Lean toolchains**, used by **36 project/version pins across 15 benchmark rows**. The final direct cold full-mode baseline passed all 36 pins with explicit per-pin `passed: true`. Three existing serial service benches completed for Core, SKI, and Putnam B2. Two exact historical Fiberwise tactic edits passed both warm LSP rechecks and all four cold pins; the old v4.28 timeout discrepancy did not reproduce at idle with a 180-second timeout. The sequential Core edit-load concurrency profiles at 1/2/3, one bounded timeout/recovery probe, and a cached REPL parity probe are complete.

All measured commands retain start/end UTC, exact command and the effective environment overrides/unsets recorded by the wrapper, exit status, GNU `time -v` CPU and maximum RSS, sampled process-tree CPU/RSS/PSS and host memory/swap/thermal/frequency, plus raw stdout/stderr and samples. The wrappers do not serialize every inherited environment variable. Process samples are taken every 0.5 seconds for service and edit probes and every 1 second for the all-pin matrix. GNU CPU totals and sampled service-tree CPU are separate metrics. Sampling can miss short-lived processes and initial intervals; sampled CPU is therefore incomplete. RSS/PSS samples are not interchangeable. Host swap and PSI are host-level and are not attributed to Lean.

### Coverage matrix

| Requirement | Evidence / status |
|---|---|
| A. Every required pinned toolchain/project combination | Complete: 15/15 rows, 36/36 pins, 10 distinct installed Lean versions; direct cold full-mode and explicit per-pin pass recorded. |
| B. Harness fast/full/cold and session paths | Complete source audit; cold full matrix complete; native warm session bench measured on Core/SKI/Putnam B2; exact real-edit LSP→cold replays measured on two Fiberwise candidates. Session result and cold correctness are distinct. |
| C. REPL compatibility | Complete for one cached Core v4.29.1 workspace: reference and trailing-comment edit pass in both LSP and REPL; intentional unknown-name case fails with identical diagnostic. Production `REPL_ENABLED` stayed false; no build/download occurred. This is a narrow parity probe, not full compatibility certification. |
| D. Bounded service concurrency/load | Complete: reference-only c=1 smoke; comparable edit-only c=1/2/3 profiles; and one intentional c=1 timeout/recovery probe. Six edit checks passed for each concurrency profile. The slow request timed out at 2.01s and was followed by a passing same-worker probe. |
| E. Historical endpoint replay | Complete from saved full/cold events: zero observed newest/oldest endpoint-pass with middle-version-fail cases in scanned complete events. Two Fiberwise cold-oldest discrepancies were replayed with exact proof bytes and both passed all pins in isolated idle checks. Historical counts are observational, not a false-safe rate guarantee or a causal wall-time comparison. |

## Runtime identity and version resolution

The harness head inspected through read-only GitButler was `03934d9bacaf8c1e8413b2cfcef11f645a6e310c` (`qsx`, “fix(pi): end the background checker when the run stops”), based on `428cb6c`. The current uncommitted `zz` workspace contains the design doc and `research/opencode-v2-vs-pi.md`; those pre-existing files were left untouched. Audit runner scripts are uncommitted audit artifacts and are not represented by the harness commit hash. `runtime-manifest.json` records this identity and the audit runner digest.

`benchmark/derived/measure-versions.json` was absent. The effective heartbeat/measurement version was therefore the newest listed pin per row (for Putnam A3/A4, v4.27.0; for B2, v4.26.0). The checked-in `benchmark/original/warmup.jsonl` lists 15 rows; the full mapping of all 36 Lean release/source-project commit pairs is in [`project-pins.json`](../runs/analysis/lean-audit-2026-10-16/project-pins.json). Every resolved workspace existed; the manifest records workspace path, source commit, `lean-toolchain`, lakefile/manifest digests, and reference proof SHA256. Exact per-row source pins:

There is no `workspaces/registry.json`. The normal resolver therefore uses each checkout's `.git` HEAD and only returns a workspace when that HEAD equals the requested `(source, version, commit)` pin (`arena/environments.py:22-63`). `engine.candidate_file()` then reads the pinned source object with `git show <commit>:<file>` (`arena/engine.py:236-279`). Because every measured row reached Lean and produced its expected per-pin result, the resolver's HEAD check succeeded for those checks. The measurement manifest records the requested commit pin and resolved path, but not a separately persisted `observed_head` field; the resolver source and successful resolution are the evidence for matching checkout HEAD.

| Row | Lean release / source-project commit pins |
|---|---|
| CallElimCorrect.substOldPostSubset | v4.26.0 / `451e5f047bafa010d178856db76c00029bfa4d7f` |
| CallElimCorrect.extractedOldExprInVars | v4.26.0 / `451e5f047bafa010d178856db76c00029bfa4d7f` |
| Core.InitsUpdatesComm | v4.29.1 / `384e22374e0872095ad9c6f74c5998c09cfd93a9`; v4.27.0 / `4348c65a93a3b57b1a4541991ed2d2fcdd9fa35d`; v4.26.0 / `451e5f047bafa010d178856db76c00029bfa4d7f` |
| fundamental_theorem_of_variational_calculus' | v4.32.0 / `c48433678e8fb6306ebcd48453300c8e16058a62` |
| Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema | v4.32.0 / `c48433678e8fb6306ebcd48453300c8e16058a62` |
| FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time | v4.32.0 / `c48433678e8fb6306ebcd48453300c8e16058a62` |
| Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress | v4.33.0-rc2 / `3aa9d4416c185e0b9faeb72bbd65abe85b95dbcc`; v4.32.0 / `197a7be621263b84c67ca4f803f69205b36d06df`; v4.31.0 / `8ea71c8df91acd63285515a04da952b23b78d266` |
| Cslib.SKI.parallelReduction_diamond | v4.33.0-rc2 / `3aa9d4416c185e0b9faeb72bbd65abe85b95dbcc`; v4.32.0 / `197a7be621263b84c67ca4f803f69205b36d06df`; v4.31.0 / `8ea71c8df91acd63285515a04da952b23b78d266`; v4.30.0 / `c7944a9fb44c3298f1a960a5e574ab23a6ab8ed5` |
| Cslib.CCS.bisimilarity_congr_choice | v4.33.0-rc2 / `3aa9d4416c185e0b9faeb72bbd65abe85b95dbcc`; v4.32.0 / `197a7be621263b84c67ca4f803f69205b36d06df`; v4.31.0 / `8ea71c8df91acd63285515a04da952b23b78d266` |
| Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius | v4.31.0 / `c1712f6c496d0aef04f09bae42aec13811b3273f`; v4.30.0 / `e6d77b18ca1334a91faf4d1ccf9f96d854d58ba4`; v4.29.0 / `de71a9dfd2f5a343e8895517b7efe857d9f1ce5c`; v4.28.0 / `673fa440714eb1949b8b50a28f2a4f52b1837e9b` |
| Binius.BinaryBasefold.fold_advances_evaluation_poly | v4.31.0 / `c1712f6c496d0aef04f09bae42aec13811b3273f`; v4.30.0 / `e6d77b18ca1334a91faf4d1ccf9f96d854d58ba4`; v4.29.0 / `de71a9dfd2f5a343e8895517b7efe857d9f1ce5c` |
| interleaved_affine_gaps_imply_tensor_gaps | v4.31.0 / `c1712f6c496d0aef04f09bae42aec13811b3273f`; v4.30.0 / `e6d77b18ca1334a91faf4d1ccf9f96d854d58ba4`; v4.29.0 / `de71a9dfd2f5a343e8895517b7efe857d9f1ce5c` |
| putnam_1964_a4 | v4.25.0 / `1ccd71f89cbbd82ae7d097723ce1722ca7b01c33`; v4.26.0 / `2df2f0150c275ad53cb3c90f7c98ec15a56a1a67`; v4.27.0 / `a3a10db0e9d66acbebf76c5e6a135066525ac900` |
| putnam_1964_b2 | v4.25.0 / `1ccd71f89cbbd82ae7d097723ce1722ca7b01c33`; v4.26.0 / `2df2f0150c275ad53cb3c90f7c98ec15a56a1a67` |
| putnam_1995_a3 | v4.25.0 / `1ccd71f89cbbd82ae7d097723ce1722ca7b01c33`; v4.26.0 / `2df2f0150c275ad53cb3c90f7c98ec15a56a1a67`; v4.27.0 / `a3a10db0e9d66acbebf76c5e6a135066525ac900` |

The actual local `lean --version` build commits and SHA256 identities are below. Executable hashes alone do not identify the runtime: several releases share the same Lean executable bytes while their `libleanshared.so` and/or `libInit_shared.so` differ. The full manifest has full hashes and resolved paths for both `lean` and `lake`.

| Toolchain | Lean build commit | Lean SHA256 prefix | Lake SHA256 prefix | `libleanshared.so` SHA256 prefix |
|---|---|---|---|---|
| v4.25.0 | `cdd38ac5115bdeec5f609e9126cce00f51ae88b3` | `8fadc3ed92cc9dec` | `5f3828d1d1977654` | `21f705df2eca6216` |
| v4.26.0 | `d8204c9fd894f91bbb2cdfec5912ec8196fd8562` | `8fadc3ed92cc9dec` | `6ee6035294625046` | `c508a88b41e3ee01` |
| v4.27.0 | `db93fe1608548721853390a10cd40580fe7d22ae` | `8fadc3ed92cc9dec` | `6ee6035294625046` | `6f2913b84d15678e` |
| v4.28.0 | `7e01a1bf5c70fc6167d49c345d3bf80596e9a79b` | `3e0d0d3d80167535` | `a608ff084d7e2af2` | `cbfea1d1a2681923` |
| v4.29.0 | `98dc76e3c0a9b856c9b98726b713fb04fab16740` | `3e0d0d3d80167535` | `a608ff084d7e2af2` | `05624e0f914c8cab` |
| v4.29.1 | `f72c35b3f637c8c6571d353742168ab66cc22c00` | `3e0d0d3d80167535` | `a608ff084d7e2af2` | `92e7892c5ab7123c` |
| v4.30.0 | `d024af099ca4bf2c86f649261ebf59565dc8c622` | `3e0d0d3d80167535` | `d3e1f322c08d87f0` | `86c5222603b164cd` |
| v4.31.0 | `68218e876d2a38b1985b8590fff244a83c321783` | `e8baaa71855a616d` | `60330ab6f07dce20` | `844963455a7800b4` |
| v4.32.0 | `8c9756b28d64dab099da31a4c09229a9e6a2ef35` | `e8baaa71855a616d` | `60330ab6f07dce20` | `52c37024db38569f` |
| v4.33.0-rc2 | `d8b18978322de05a8f3dba51ef03cf5461676c17` | `e8baaa71855a616d` | `60330ab6f07dce20` | `0e2ffc1639d133cf` |

## How the harness routes Lean work

Source inspection covered `arena/engine.py`, `arena/lean_session.py`, `arena/lean_repl.py`, `arena/campaign.py`, and `arena/cli/lean_bench.py`, cross-checked against `handoffs/2026-10-16-v8c.md` and `docs/PI_LEAN_HARNESS_V8_NEXT_DESIGN_2026-10-16.md`. The expanded source findings and line references are in [`lean-harness-path-audit.md`](../runs/analysis/lean-audit-2026-10-16/source-audits/lean-harness-path-audit.md).

- `fast` checks first-listed primary and, when distinct, the measurement version; it stops on first failure. `full` checks every listed version. “Full” is every pin for one row, not every row or repeat. This audit explicitly invoked one `full` evaluation per row for the 15-row matrix.
- The measurement-version override file was absent; default is newest listed. Only that toolchain returns the benchmark heartbeat value. Per-pin proof acceptance and timing still come from each version's compile.
- Ordinary `engine.run_lean()` uses the session/LSP when configured. It sends project, source text, header boundary, lane, and heartbeat-measure flag. A successful result reports `path=session`; unavailable or refused service can fall back to a direct cold compile. Cold verification forces the direct path, requires every pin to pass, and applies a 5% heartbeat tolerance to the measurement version. It is a separate correctness gate from session success.
- LSP imports/header are opened once per worker; proof text is edited incrementally from its first changed line. Timeout handling attempts to restore the header, otherwise closes the document. This preserves warm imports, but does not establish cold correctness.
- Production `REPL_ENABLED=False` (`arena/lean_repl.py:24-28`). REPL is eligible only for supported builds and unmeasured/non-tactic batch/background checks when explicitly enabled. REPL errors fall back to LSP; failures there may fall back to cold. It cannot supply the recorded heartbeat on measured requests. Cached binaries existed for v4.29.1 and v4.31.0; no build or network download was attempted.
- Source config has per-run model/background locks, a candidate lock and `autocheck.lock`; separate lanes may overlap. Machine service worker-token defaults and planning estimates are policy constants, not measured capacities. Source reports default max 8 model workers, 64 reserved background slots, a 3 GB worker planning estimate, and 5 GB reserve. Queue waits/refusals/evictions are logged, though not all are joined to candidate IDs. Benchmarks time compiler requests/header opens, not full end-to-end candidate materialization/model-lock/ledger paths.
- Native bench includes cold/warm header opens, serial check distributions, worker PSS/free RAM, CPU clock and temperature. Existing edit scenarios are comment edits or comment splices; they do not measure realistic tactic changes. The exact replay below fills part of that gap.

## All-pin cold baseline: complete matrix

The final accepted run is `full-v3-matrix.json` with per-row raw command folders `full-v3-01` through `full-v3-15`. Each command was `/usr/bin/time -v ./.venv/bin/arena eval ROW reference.lean --mode full --json`, with `ARENA_LEAN_SESSION` removed and timeout 180 seconds. This ensures no session reuse. The corrected runner fails closed on command failure, malformed response, missing/extra expected pins, or any pin without explicit `passed: true`. **15/15 rows and all 36/36 expected pins passed; all row commands exited 0.** Sum of row wall times was 490.366 seconds. The table includes each per-pin wall time and the heartbeat only where measured; `HB` is not available per version for other pins.

| Row | Per-pin cold results (`version: seconds`, `*` = measurement version and HB) | Command wall | GNU CPU | Peak tree PSS | Min host MemAvailable |
|---|---|---:|---:|---:|---:|
| CallElimCorrect.substOldPostSubset | v4.26.0: 8.73s, HB 5175 | 9.250s | 43.34s | 1.21 GiB | 25.93 GiB |
| CallElimCorrect.extractedOldExprInVars | v4.26.0: 10.40s, HB 2698 | 11.331s | 50.77s | 1.20 GiB | 25.90 GiB |
| Core.InitsUpdatesComm | v4.29.1*: 3.29s, HB 4251; v4.27.0: 2.25s; v4.26.0: 2.20s | 8.136s | 20.17s | 1.02 GiB | 26.09 GiB |
| fundamental_theorem_of_variational_calculus' | v4.32.0: 9.72s, HB 11946 | 10.157s | 4.75s | 1.60 GiB | 26.23 GiB |
| Electromagnetism…isExtrema | v4.32.0: 15.23s, HB 26973 | 15.504s | 28.16s | 1.91 GiB | 26.18 GiB |
| FieldSpecification.WickAlgebra…eq_time | v4.32.0: 8.99s, HB 42165 | 9.222s | 11.47s | 1.79 GiB | 26.21 GiB |
| Cslib Fsub progress | v4.33.0-rc2*: 15.58s, HB 59812; v4.32.0: 11.01s; v4.31.0: 11.64s | 38.734s | 42.09s | 1.22 GiB | 26.35 GiB |
| Cslib SKI diamond | v4.33.0-rc2*: 1.84s, HB 1384; v4.32.0: 1.49s; v4.31.0: 1.73s; v4.30.0: 4.25s | 10.114s | 8.39s | 0.87 GiB | 26.52 GiB |
| Cslib CCS choice | v4.33.0-rc2*: 3.26s, HB 3855; v4.32.0: 3.23s; v4.31.0: 3.23s | 10.144s | 10.96s | 0.87 GiB | 26.47 GiB |
| Binius Fiberwise | v4.31.0*: 20.36s, HB 15913; v4.30.0: 21.68s; v4.29.0: 24.79s; v4.28.0: 40.37s | 108.036s | 147.71s | 6.11 GiB | 26.11 GiB |
| Binius fold advances | v4.31.0*: 11.97s, HB 45537; v4.30.0: 14.54s; v4.29.0: 15.91s | 43.349s | 81.35s | 3.91 GiB | 26.28 GiB |
| Interleaved affine gaps | v4.31.0*: 21.57s, HB 9281; v4.30.0: 21.19s; v4.29.0: 23.70s | 67.255s | 90.42s | 3.67 GiB | 26.19 GiB |
| Putnam 1964 A4 | v4.25.0: 27.44s; v4.26.0: 33.48s; v4.27.0*: 31.92s, HB 111476 | 93.739s | 52.16s | 5.82 GiB | 26.20 GiB |
| Putnam 1964 B2 | v4.25.0: 17.63s; v4.26.0*: 16.35s, HB 134518 | 35.017s | 30.39s | 5.85 GiB | 26.21 GiB |
| Putnam 1995 A3 | v4.25.0: 6.22s; v4.26.0: 6.31s; v4.27.0*: 6.67s, HB 14134 | 20.378s | 19.47s | 5.89 GiB | 26.21 GiB |

Per-version compile seconds are measured from the evaluator result. CPU and memory columns are per-command aggregates because one CLI invocation traverses every pin. CPU is GNU `time -v` around the CLI plus a separate sampled PID/start-time process-tree series; the sampled series is incomplete for short-lived processes. GNU max RSS is retained separately in each row folder's `time-v.txt`. Process-tree PSS comes from sampled `smaps_rollup`; this cold matrix had no PSS→RSS fallback samples. Maximum thermal-zone readings reached 87°C during the matrix; the raw zone names/readings and frequency are retained in samples. Initial external process snapshot was not used as proof of absence.

The v3 JSON's `gnu_elapsed` display field has a parser-format defect (`mm:ss or m:ss): ...`); elapsed times in the table use wrapper monotonic duration and per-pin evaluator seconds, and GNU CPU totals/max RSS are present. Raw GNU `time-v.txt` is retained for every row. Earlier `full-v2` artifacts contain invalid PID-churn CPU deltas and are superseded; first corrected attempt stopped fail-closed on a runner pin-map mismatch. Those attempts are preserved but not included as measurements.

## Existing production-path session benches

These were existing `arena lean bench` CLI invocations with `--versions first --repeats 3 --timeout 180`; each serially ran 3 repetitions per request type against the selected first pin. Each has full output and process samples under the named folder. The benchmarks' “edit” case changes a trailing comment; it is not a tactic edit. Process-tree CPU is sampled across the detached `arena.lean_session` service and descendants; GNU time encloses only the CLI process, so the two CPU totals are not additive complete totals.

| Row / project pin | Wall, samples | GNU CLI CPU | Sampled service-tree CPU (incomplete) | Peak sampled tree PSS / RSS | Min host free / swap | Max thermal zone |
|---|---|---:|---:|---:|---:|---:|
| Core / v4.29.1, commit `384e223…` | 13.980s, 22 | 0.80s | 35.67s | 1.245 / 2.185 GiB, no PSS fallback | 25.64 / 2.88 GiB | 92°C |
| SKI / v4.33.0-rc2, commit `3aa9d44…` | 13.192s, 21 | 2.00s | 13.05s | 1.847 / 3.623 GiB, no fallback | 25.44 / 2.89 GiB | 84°C |
| Putnam B2 / v4.25.0, commit `1ccd71f…` | 172.021s, 199 | 18.04s | 267.01s | pure sampled PSS peak 8.16 GiB; RSS peak 18.46 GiB | 22.84 / 2.94 GiB | 93°C |

The B2 8.16 GiB peak is pure: the one sample with RSS fallback is the final service-shutdown sample, where process-tree PSS and RSS both read zero; the peak sample had zero fallback processes. CPU peaks and service CPU are sampled and can miss short-lived PIDs. `gnu_elapsed` in these early v2 bench command JSONs is malformed, but wrapper monotonic duration is valid and raw `time-v.txt` remains available.

Native bench request p50/p95 values (n=3) include Core reference 0.52/0.61s, comment edit 0.30/0.381s, and SKI reference 0.24/0.267s, comment edit 0.24/0.24s. Putnam B2 reference was 14.59/19.072s and comment edit was 2.63/3.089s. These are descriptive values from a very small sample; p95 is not a reliable tail percentile at n=3. They are per-request warm-path compiler metrics, not end-to-end user-visible time. Opening imports was 1.81/1.76s for Core and 4.94/4.75s for B2 (cold then warm). Bench's internal worker samples showed Core worker PSS around 0.52 GiB and B2 around 4.88 GiB; B2 `raw.jsonl` saw three worker PIDs around 1.97–2.07 GiB each at a sample. This is a sample-level observation, not evidence that those workers were all simultaneously busy. Raw bench rows are in each `bench-out/raw.jsonl`.

One earlier Core attempt had CLI exit 0 but post-processing failed with metadata `KeyError`, so its resource attribution is marked incomplete and excluded above. The accepted Core rerun is the v2 folder above. No all-row repeated session bench was run; repeated B2 cost 172s and peak PSS was high, so subsequent session work focused on the two exact proof edits.

## Paired realistic tactic edits and historical Fiberwise cold discrepancy

The two source proof snapshots are exact historical campaign candidates. Their proof bytes and parent bytes are hashed in `candidate-metadata.json`; the saved `proof-diff.patch` shows tactic changes, not trailing comments. The CLI contract (`arena/cli/__init__.py:95-103`, `arena/cli/evaluate.py:14-16`) reads the supplied proof file and passes its text to `engine.evaluate`. Candidate file SHA256 matches the original historical snapshot. Warm calls used isolated one-worker services; reference ran first to open the worker, then the exact proof candidate ran in the reused worker. The candidate results had `path=session`, `engine=lsp`, `new_worker=false`, and non-null `changed_from_line`. Cold full calls removed `ARENA_LEAN_SESSION`, checked exact expected pin sets, and required explicit true for every pin.

| Candidate ID prefix / original SHA256 | Warm reference → exact candidate | Cold full pins / heartbeat | Cold command telemetry |
|---|---|---|---|
| `003ace87ceb8` / `0a9b049b75d90331dc6feaa6933aabf8a0c1816710388f54fa96c250146ba9d4` | v4.31.0 reference passed, HB15913, 34.91s Lean/35.335s wall; exact real tactic edit passed, HB3840, changed line1287, same worker, 4.61s Lean/5.322s wall | v4.31 13.57s (HB3839); v4.30 24.38s; v4.29 28.76s; v4.28 42.55s; all passed | 110.209s; GNU CPU155.51s/141%; sampled tree CPU148.52s; PSS/RSS peak 6.121/6.131 GiB; min MemAvail20.735 GiB, min SwapFree2.875 GiB; max zone73°C |
| `ab0f537560e8` / `15f258d0580be20f6f8c877d6965d57d0d33fed9a0438fedbd052c7d74a83709` | v4.31.0 reference passed, HB15913, 35.99s Lean/36.339s wall; exact real tactic edit passed, HB2192, changed line1285, same worker, 4.61s Lean/5.388s wall | v4.31 13.46s (HB2191); v4.30 24.15s; v4.29 21.95s; v4.28 37.59s; all passed | 97.614s; GNU CPU153.45s/157%; sampled tree CPU146.10s; PSS/RSS peak 6.092/6.101 GiB; min MemAvail21.393 GiB, min SwapFree1.546 GiB; max zone73°C |

The reference-first and candidate-second timings are asymmetric: the reference opens imports on a new worker (23.667s and 26.955s header opens), while the candidate reuses that worker and gets an incremental edit path. These observations prove that reuse occurred for realistic tactic edits; they are **not** a controlled tactic-speed comparison and do not isolate edit time from worker/header startup. Each candidate has one edit sample, so no latency distribution or general speedup estimate is claimed. The first candidate came from v6ark; historical cold detail for its false bit was not retained, so its old failure's cause remains unknown. The second came from v8c; historical cold verification retained “Lean timed out after 60 seconds” on v4.28.0 while the same candidate's full session event passed all four pins. In these idle replays both exact proofs passed v4.28 within 42.55s and 37.59s with a 180s configured timeout. This does not establish that they pass under campaign load or that every old timeout was purely contention; it shows neither discrepancy reproduced in this isolated replay. Historical endpoint scan found zero endpoint-pass/middle-fail cases among complete saved full events. Its counts and exact qualifications are in [`lean-endpoint-replay-inventory.md`](../runs/analysis/lean-audit-2026-10-16/source-audits/lean-endpoint-replay-inventory.md).

During the second cold replay, host SwapFree fell from about 3.0 GiB toward 1.5 GiB while MemAvailable remained above 21 GiB. Added `/proc/vmstat` `pswpin`/`pswpout` and `/proc/pressure/memory` point samples to `candidate-replays/host-swap-telemetry.jsonl`; these are whole-host counters, not Lean-attributed swap. Thermal maximum for the two candidate cold commands was 73°C. Warm service commands briefly reached 94°C on the package sensor; this value is retained in their samples. The temperature sensors are reported by their raw kernel zone names because zone semantics vary by hardware.

## Bounded load and REPL parity probes

The reference-only concurrency-1 command reached Lean and passed its proof work: three reference requests passed, including a warm slot open in 6.22s and a first compile in 0.53s; the second and third requests were unchanged and took 0.00s. It exited 1 because the CLI's second acceptance criterion asks for post-timeout probes; reference-only weights intentionally have no slow timeout checks, so there were no probes. The other five criteria passed, including no failures/timeouts, warm latency, worker reuse, no orphans, and memory floor. This run is not reported as an overall passing load test and is not a concurrency scaling result.

The edit-only c=1/2/3 profiles are complete. Each command used `runs=1`, `background=0`, a fixed six-check budget shared among its concurrency threads, `weights=edit=1`, `think=0`, timeout 180s, and an explicit one-minute cap. The generated edits append distinct trailing comments; this measures small edit traffic and worker reuse, not tactic elaboration. The observed p50/p95 values are small-sample descriptions, not tail estimates. The CLI exit code was 1 for all three because no synthetic slow case meant no post-timeout probe; all six check requests per profile passed with no timeout or proof failure. The isolated timeout/recovery probe timed out the slow request at 2.01s with `warm_kept=true`, then passed a same-worker recovery health probe using generated `sorry` in 0.33s (`new_worker=false`). The command exited 0; all six criteria passed, one worker was retained, and no orphan remained. Its `core-timeout-recovery/` folder has full raw telemetry.

| Profile | Proof checks | Wall / samples | GNU CLI CPU; sampled service-tree CPU | Peak tree RSS/PSS (GiB; peak used smaps PSS; one fallback sample occurred elsewhere) | Min MemAvailable / SwapFree (GiB) | CLI result |
|---|---|---:|---:|---:|---:|---|
| Core c=1, reference-only | 3 passed; first compile 0.53s, warm slots 6.22s; two later checks unchanged | 19.977s / 29 | 0.31 CPU-s; 24.08 CPU-s sampled, 713% one-core peak | 2.113 / 1.178 | 21.87 / 1.995 | exit 1 only for no post-timeout probes (0 slow checks); other 5/6 criteria passed |
| Core c=1, distinct comment edits | 6/6 passed; 3 warm slots in 6.15s, edit checks p50 0.30s / p95 0.50s / max 0.52s | 19.971s / 29 | 0.33 CPU-s; 23.91 CPU-s sampled, 723% one-core peak | 2.122 / 1.185 | 21.77 / 2.012 | exit 1 only for the same intentionally absent post-timeout probe; no proof failures/timeouts |
| Core c=2, distinct comment edits | 6/6 passed; two concurrent checks per launch wave; 3 warm slots in 6.10s, p50 0.34s / p95 0.60s / max 0.60s | 19.555s / 28 | 0.32 CPU-s; 22.46 CPU-s sampled, 624% one-core peak | 2.164 / 1.227 | 21.54 / 2.016 | exit 1 only for the intentionally absent post-timeout probe; no proof failures/timeouts |
| Core c=3, distinct comment edits | 6/6 passed; three concurrent checks in first launch wave; 3 warm slots in 5.50s, p50 0.36s / p95 0.60s / max 0.62s | 19.305s / 28 | 0.34 CPU-s; 23.00 CPU-s sampled, 746% one-core peak | 2.181 / 1.243 | 21.65 / 2.028 | exit 1 only for the intentionally absent post-timeout probe; no proof failures/timeouts |

The load CLI has a six-criterion result, so an exit 1 from these no-slow profiles is not a Lean check rejection. Their raw reports name the one expected inapplicable criterion. The c=1 reference-only profile is a smoke observation and not the c=1 row used to compare concurrency; only the same `edit=1` profile across c=1/2/3 is comparable.

The timeout/recovery case used one simulated run, one concurrency thread, two checks, timeout=2s, and `weights=slow=1`. The source-generated slow tactic request timed out after 2.01s; the immediately following harness health probe using generated `sorry` passed in 0.33s using the retained worker. This validates worker recovery, not a user proof. It had 28 samples over 19.309s; GNU CLI CPU was 0.31s and sampled service-tree CPU was 20.19s (incomplete, 670% peak one-core). Peak tree RSS/PSS was 2.162/1.225 GiB (peak PSS sample had zero fallback processes; one fallback sample occurred elsewhere); host MemAvailable/SwapFree minima were 21.52/2.036 GiB; max thermal zone was 91°C. Exit 0, all criteria pass, no orphan; service shut down and socket was removed.

The cached REPL parity probe used Core v4.29.1 at source commit `384e22374e0872095ad9c6f74c5998c09cfd93a9`, with the cached binary and isolated pickle directory. It compared reference, trailing-comment edit, and intentional unknown-name cases. LSP and REPL both passed the first two and both rejected the third with the same unknown-identifier diagnostic (`overall_parity=true`). REPL reference startup included a 3.615s header import (4.047s total); comment edit took 0.435s; negative check 0.032s. This is one small parity sample, not a speed comparison or broad equivalence claim. `REPL_ENABLED` was false before/after and remained unchanged; no build or network call occurred during this audit. The cache metadata includes a prior `built_with_override` record, but the audit only read that metadata and used the existing binary. Its telemetry has 15 samples / 8.851s, GNU CLI CPU 0.94s, sampled tree CPU 16.22s (incomplete, 601% one-core peak), RSS/PSS peak 1.653/1.146 GiB (no fallback), host MemAvailable/SwapFree minima 21.86/2.05 GiB, max thermal zone 84°C. Full cases, diagnostics, command and raw telemetry are in [`cached-repl-parity/result.json`](../runs/analysis/lean-audit-2026-10-16/repl-load-probe/cached-repl-parity/result.json).

Probe details and source/command plan are in [`repl-load-audit.md`](../runs/analysis/lean-audit-2026-10-16/source-audits/repl-load-audit.md); raw results and samples are in `repl-load-probe/`.

## Telemetry, attempted commands, and evidence limits

- All-pin matrix: one command per row with `/usr/bin/time -v`, timeout 180s, cold (`ARENA_LEAN_SESSION` unset), 1s process samples. Raw logs, per-command CSV, `time-v.txt`, JSON matrix and progress are retained. The repaired sampler identifies processes by `(PID,starttime)`. GNU time is the aggregate CPU source for each command; sampled CPU is incomplete for sub-sample process churn.
- Session and candidate-edit commands: detached service and descendants sampled at 0.5s using `(PID,starttime)`. GNU time wraps the CLI only; service CPU is sampled separately and incomplete. Process RSS/PSS are sampled simultaneously at a point; GNU max RSS is an independent command-level metric. PSS fallback counts are per sample.
- Host measures include MemAvailable, SwapFree, CPU frequency, all readable thermal zones. Independent sibling monitor could not see the measurement PIDs in its namespace, so its zero process-tree values are explicitly not used. The authoritative per-command samplers run with their commands.
- Audit runner revisions/attempt folders are preserved. A system Python attempt failed import before any Lean command. A first venv service launch failed because the AF_UNIX path exceeded 100 bytes. A short-path readiness probe then used a mismatched socket basename; it launched only an idle owned service with no workers and was explicitly shut down. Corrected replays use `lean_session.socket_path()` under `/tmp`, a one-worker isolated service, and report successful startup/shutdown. No failed setup was counted as a Lean measurement.
- Load-probe setup produced distinct preserved failures before the measured c=1 run: the default `/run/user/1000/arena-lean-service` was read-only; a long audit-local socket path exceeded the 100-byte AF_UNIX limit; a short sandboxed service did not answer its socket. The c=1 measured run then used the isolated `/tmp/rplc1/service.sock` under narrow local-socket escalation. These setup attempts did not launch Lean and are not included as workloads. The successful bench and session workloads used narrowly approved local-only execution; no network use was needed. Avoid interpreting raw thermal/swap host measures as caused only by Lean.
- The corrected final all-pin matrix is the sole accepted correctness baseline. Earlier versions with invalid negative PID-churn CPU or fail-closed row-map errors are retained for audit trail and excluded from claims. No repository tests were run because this task requested measurements and source audit, not test execution.

## Artifact index

- [`full-v3-matrix.json`](../runs/analysis/lean-audit-2026-10-16/full-v3-matrix.json), [`full-v3-matrix.csv`](../runs/analysis/lean-audit-2026-10-16/full-v3-matrix.csv), 15 raw `full-v3-*` folders
- [`project-pins.json`](../runs/analysis/lean-audit-2026-10-16/project-pins.json), [`toolchain-metadata.json`](../runs/analysis/lean-audit-2026-10-16/toolchain-metadata.json), [`runtime-manifest.json`](../runs/analysis/lean-audit-2026-10-16/runtime-manifest.json)
- [`candidate-replays/summary.json`](../runs/analysis/lean-audit-2026-10-16/candidate-replays/summary.json), exact proof patches, candidate hashes, JSON results, samples and raw logs by candidate
- [`source-audits/`](../runs/analysis/lean-audit-2026-10-16/source-audits/) includes path/pin semantics, historical endpoint replay inventory, and REPL/load source audit
- Three accepted existing bench results in `session-v2-Core_InitsUpdatesComm`, `session-v2-Cslib_SKI_parallelReduction_diamond`, and `session-v2-putnam_1964_b2`
- Load/recovery and cached REPL measurements in `repl-load-probe/`, each with `command.json` or `result.json`, GNU `time-v.txt`, raw output, host snapshots, and process samples
