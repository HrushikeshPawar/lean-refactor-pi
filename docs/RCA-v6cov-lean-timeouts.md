# RCA: v6cov campaign — every Lean check timed out (2026-10-09)

## Summary

The v6cov campaign (DeepSeek V4.1 Flash, 7 rows, $0.50 soft cap, 2 at a time) started at 00:24 and was stopped at
06:03 with both Putnam runs unfinished. In 5.6 hours, `putnam_1964_a4` got **0 of 238** Lean checks back (every one hit
the 180 s limit, the untouched reference proof included); `putnam_1964_b2` got 6 of 115. The model spent $0.69
settled (+$0.09 unresolved) working blind. The other 5 rows never started.

The harness is not slow in itself: when a Lean worker was warm, checks took **0.3–0.6 s**. Three faults combined:

1. **Storage (root cause).** On the NTFS SharedDrive (FUSE, `mount.ntfs`), a bare `import Mathlib` on the Putnam
   workspace takes 128–192 s; the same files on a kernel filesystem take 6–7 s.
2. **Timeout design (amplifier).** The 180 s budget includes that import, and a timeout closes the worker's document,
   so the next check re-imports from scratch and times out again: a loop no run can leave.
3. **No health gate (why it ran for hours).** Nothing checked that the reference compiles inside the limit before
   spending, and nothing stopped a run whose Lean checks all fail.

## Impact

| Run | Wall | Settled spend | Lean checks | Timed out | Best result |
|---|---|---|---|---|---|
| putnam_1964_a4 | 5.64 h | $0.3749 (+$0.0871 unresolved) | 238 | 238 (100%) | none |
| putnam_1964_b2 | 5.31 h | $0.3147 | 115 | 111 (97%) | #14: 264 tok, 1642 HB, est. proxy 94.58, **unverified** |

- b2's #14 (estimated 94.58) was lost: its v4.26.0 compatibility check timed out at 182 s (cold), so it was never
  verified and nothing was submitted.
- Wall time spent waiting on Lean: 87% (a4) and 91% (b2), against 11% in the v6pilot PhysLib run.
- 5 rows (PhysLib ×2, CSLib ×2, putnam_1995_a3) did not run.

## Evidence

**Per-run Lean timings** (`runs/analysis/v6cov/archive/20261009-0024-ntfs-timeouts/v6cov-*/ledger.jsonl`, `lean-session.log`):

- a4: every probe and evaluation `path: session`, `seconds: 180`, `error: Lean timed out after 180 seconds`.
- `lean-session.log` shows 4 workers opening in the first 15 min, then timeouts in batches of four every ~196 s until
  shutdown: all slots stuck re-importing.
- b2, 04:02: a fresh worker finished one check in **175.16 s** (just under the limit); the next five checks on that warm
  worker took **0.34–0.55 s**. It fell back into the loop at the next timeout.

**Earlier rows, same harness** (v6pilot DeepSeek):

| Row | Toolchain | Fresh-worker check | Typical check |
|---|---|---|---|
| Core (Strata) | v4.29.1 | 5 s | 0–1 s |
| PhysLib variational | v4.32.0 | (none needed) | 0–1 s |
| CSLib CCS | v4.33.0-rc2 | 58 s | 54–67 s median |
| **Putnam (v6cov)** | v4.25.0 | 175 s or timeout | timeout |

**Import benchmark** (`import Mathlib` + `example : True := trivial`, v4.25.0 oleans, quiet machine, one process):

| Where the oleans live | Search order | Time |
|---|---|---|
| NTFS SharedDrive, `lake env lean` (harness cold path) | lake's (Mathlib last) | 192 s cold, 128–137 s cached |
| NTFS SharedDrive, direct `lean` | Mathlib first | 35–42 s |
| RAM disk (tmpfs) | either | 6–8 s |
| `Library` USB HDD (exFAT, kernel driver) | either | 6.7–7.4 s cached; 340 s first read from disk |
| (v4.26.0 on NTFS, `lake env lean`) | lake's | 108 s cold, 73 s cached |

Copying all 5 GB of oleans off NTFS took 27 s, so bandwidth is fine; the cost is per-file operations through the
single-threaded FUSE daemon. `lake env` puts the 8 dependency folders before Mathlib's own build folder in
`LEAN_PATH`, so each of ~7,000 Mathlib modules is first looked up (and missed) in 8 places: ~56,000 failed lookups,
each a FUSE round trip. On a kernel filesystem the misses cost almost nothing (6.3 s vs 7.7 s on tmpfs).

PhysLib rows import only the Mathlib modules they need (the workspace has no `Mathlib.olean`), which is why they never
hit this. Putnam files `import Mathlib` in full.

## Root causes

### RC1. Workspaces on NTFS via FUSE (environment)

Every Lean process maps thousands of `.olean` files through `mount.ntfs`. Each open, stat and miss is a user-space
round trip, serialised in one daemon. It is 5–6× slower than a kernel filesystem with the best search order and
~20× slower with lake's order. Two runs × up to 4 workers each, plus route extraction, all import at once, so the
real cost under load was higher than the single-process numbers above.

### RC2. Timeout includes the import, and a timeout throws the import away (harness design)

- `arena/lean_session.py` `LeanServer.check` (around line 331): the 180 s `waitForDiagnostics` budget covers the whole
  document, imports included. A fresh worker on Putnam needs ~175 s before the proof starts.
- On timeout it calls `close_doc`, which tears the worker down. The next check on that slot `didOpen`s a new
  document and re-imports Mathlib. Once one check times out, every later check starts cold and times out too.
- `arena/route_features.py` (`TIMEOUT = 120`) sends background route extraction through the same session and slots;
  its 120 s timeouts (`check ran past 120 s` every 2–4 min in the log) also close documents and take slots.
- Compatibility checks on the other versions (v4.26.0, v4.27.0) open a new server each time and are always cold, so on
  Putnam they could never pass: b2's best proof failed v4.26.0 at 182 s.
- The fixed 180 s limit does not scale with the row. The Putnam references are heavy (111k and 134k heartbeats).

### RC3. No gate before spending, and no circuit breaker during the run (harness design)

- The campaign's checks before spending are packet certification (cold `lake env lean`, 360 s, cached) and the
  Langfuse preflight. Neither runs the reference proof through the session under the 180 s limit.
- Nothing stops a run when Lean is broken. The model received "Lean timed out after 180 seconds" 238 times and kept
  probing. `summary.txt` reported `alarms 0`: the only alarm is cache-related.
- `events.jsonl` has no timestamps on tool events, and the summary and viewer show no Lean latency or timeout rate,
  so the problem was invisible without reading the session log.

### RC4. Process: we did not test what the campaign does

- Subagent D's `runs/analysis/workspaces/validate.py` would have caught it (a full evaluation of each reference). It
  was stopped before running and never re-run.
- I measured the Putnam reference at **133 s cold** against a **180 s** limit and called it "works but slow". That
  was the warning, and I did not act on it. My packet certification exercised the cold path with a 360 s limit, not the
  session path the runs use.
- The fixes that night (orphaned Lean processes, `String.ofList`, the `all` pattern) were real, but they only made
  certification pass. Nobody ran one model step on a new row before launching 7.

## Plan

Ordered by what unblocks the campaign. Phases A–C are free (no model calls). Nothing is launched without your go.

### Phase A: fast storage for workspaces

1. **Move the workspaces off NTFS.** Recommended: a **single ext4 image file on `Library`**, mounted with a loop
   device, mapped through `workspaces/registry.json`. It keeps the kernel-filesystem speed measured above (6–7 s),
   avoids exFAT's 512 KB clusters (5 GB of oleans took **23 GB** as plain files there), and supports symlinks and
   permissions. Size: about 200 GB for all workspaces. Mounting needs `sudo` once per boot, or an fstab entry.
   - Alternative: plain directories on exFAT. Works, but wastes about 4× the space and has no symlinks.
   - Caveats: the drive must stay attached during runs; the first read after boot comes off a spinning disk (~5 min per
     Mathlib version, once), so the session warms one worker per toolchain before the model starts.
2. Measure again on the new storage: import time, a fresh session worker, and a warm check of each reference.

### Phase B: harness fixes

3. **Keep workers warm across timeouts.** On timeout, replace the document text with its header (imports only)
   instead of closing it: Lean cancels the elaboration and keeps the imports loaded.
4. **Separate the import from the proof budget.** Open each worker with the header only and a long limit (600 s);
   start the proof timer only after the header is ready.
5. **Scale the limit per row:** `max(180 s, 3 × warm reference check time)`, measured by the gate in step 8.
6. **Separate background work from the model's workers.** Route extraction and compatibility checks use their own
   low-priority worker, pause while the run is unhealthy, and never close a model worker.
7. **Direct `lean` with Mathlib first in `LEAN_PATH`** for cold compiles (`_run_cold`), instead of `lake env lean`.
   That is 3–4× faster on NTFS and harmless elsewhere.

### Phase C: gates and visibility

8. **Lean health gate per row before spending** (in `run_campaign.py`, free): start the session, warm one worker per
   listed version, check the reference on each, and record fresh-open and warm-check times. Refuse the row if a warm
   reference check uses more than half its limit or any version fails. This replaces "packet certified" as the go
   signal.
9. **Circuit breaker in the run:** after 5 consecutive Lean timeouts or failures (or the reference timing out), stop
   sending model requests, end the run with stop reason `lean_unhealthy`, and let the campaign continue with the next
   row.
10. **Visibility:** timestamps on tool events; Lean p50/p95 and timeout rate in `summary.txt` and the viewer, with an
    alarm above 20%.
11. **One worker budget for the whole machine** across concurrent runs (a file semaphore), so two runs cannot open 8+
    Mathlib workers at once.

### Phase D: test protocol before any campaign

12. For every new row: `validate.py` (a full evaluation of the reference on all versions), then the gate in step 8.
13. Before a multi-row launch: one run of about $0.05 on one row per workspace family, checking Lean p95 and timeout
    rate in its summary.
14. Fast tests plus targeted slow tests for the session changes (worker kept warm across a timeout, header-first
    open, circuit breaker), using a fake slow Lean the way the orphaned-process fix was tested.

### Then

15. Relaunch v6cov (7 rows) with your go, after A–C and the step 13 check.
16. Re-verify b2's #14 (264 tokens, est. 94.58) on all three versions once the storage is fast. It may already be a
    usable submission row without a new run.

## Appendix: commands and data

- Lean timing script: `leanstats.py` in the session scratchpad. It reads `ledger.jsonl` and groups probe and
  evaluation `compat[*].lean.seconds` by kind and version.
- Import benchmark files: `/run/media/hrushikesh/Library/lean-olean-test/` (v4.25.0 oleans, 23 GB on exFAT; safe to
  delete).
- Session logs: `runs/analysis/v6cov/archive/20261009-0024-ntfs-timeouts/v6cov-putnam_1964_{a4,b2}-deepseek-v4.1-flash-r1/lean-session.log`.
