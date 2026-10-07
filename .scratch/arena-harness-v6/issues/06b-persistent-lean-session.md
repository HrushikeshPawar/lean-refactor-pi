# 06b: Persistent Lean session for fast proof tools

**What to build:** Probing, evaluating and profiling a draft re-elaborates only the target theorem, not the imports and the unchanged file prefix. The agent waits seconds rather than half a minute per Lean call, while submitted candidates still pass a clean full compile.

**Blocked by:** 06: Proof-tool UX and error replay.

**Status:** needs-review

**Branch:** `hrushikesh/v6-06b-fast-lean` (stacked on `hrushikesh/v6-06-proof-tools`)

**Evidence (2026-10-07, PhysLib `fundamental_theorem_of_variational_calculus'`, warm page cache):** One `lake env lean` of the candidate file takes about 32 s:
- loading the imports takes about 7 s;
- re-elaborating the unchanged 98 lines above the theorem takes about 24 s;
- the theorem itself takes about 1 s.

A four-draft `arena_probe` batch takes 85 s in parallel and 184 s sequentially. Python start-up per tool call is under 0.1 s and is not a factor.

- [ ] Run the primary measurement toolchain's Lean compiles for probe, evaluate and profile through a persistent per-run Lean session that keeps the imports and the elaborated file prefix and re-elaborates only the changed theorem. The session can be Lean's server with incremental snapshots, the Lean REPL, or an equivalent. Model tool calls are one-shot `tools.arena_campaign` processes, so the session must outlive them: for example, a per-run daemon reached over a Unix socket in the run directory that the runner starts and stops. Concurrent drafts must remain possible, bounded by memory as in 06.
- [ ] Results must equal a cold compile: identical diagnostics with the same file and proof line coordinates, hole goals, success or failure, and wrapper-measured theorem heartbeats within the existing certification tolerance. Prove this with tests that compare session and cold results on pinned Core and PhysLib rows for a compiling candidate, a failing draft and a draft with holes.
- [ ] Fail safe: if the session is unavailable, crashed or stale (toolchain, pin, file prefix or wrapper changed), the call falls back to the current cold compile and reports which path ran. A session result is never presented as more trustworthy than a cold one. A candidate selected for submission or the final report is always re-verified by a clean cold compile (ticket 08 relies on this).
- [ ] Keep the instrumented profile compile and the background autocheck on the other toolchains correct; use the session where it is safe and measurably faster. Survey the remaining Lean-bound and I/O-bound paths (kickoff context and profile extraction, the heartbeat floor, autocheck, evaluation and profile measurement, `arena_find` fallbacks, run start-up) and fix any other avoidable repeated work. List each path with its before and after time in the hand-back.
- [ ] Report wall-clock before and after on Core and PhysLib for a single probe, a four-draft batch, an evaluate, a profile, and a run's first Lean call (session start-up). Targets on PhysLib after warm-up: a single probe, evaluate or profile under about 8 s, and a four-draft batch under about 15 s.
- [ ] Clean up: no orphaned Lean processes after a run ends, is interrupted with Ctrl+C or crashes. Memory use stays bounded on the 8-core, 30 GB machine. Add a lifecycle test.

## Version control (GitButler)

Your branch is **`hrushikesh/v6-06b-fast-lean`**, already created and stacked directly above `hrushikesh/v6-06-proof-tools`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-06b-fast-lean` exists, that every lower branch is present and that no commit is `{conflicted}`. Confirm there are no other implementer's uncommitted changes in this checkout; only one implementer works here at a time. If anything differs, stop and report; do not repair it.
- Commit only your own changes and only to your branch: run `but diff`, then `but commit -b hrushikesh/v6-06b-fast-lean -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code a lower ticket introduced, do it in a commit on your own branch and call it out in the hand-back; do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** every change is committed on `hrushikesh/v6-06b-fast-lean`, with nothing uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran and their results, the timing table, deviations from the criteria and open questions. Do not mark the ticket done.

## Hand-back

**Design.** `arena/lean_session.py`: a per-run daemon, started by `tools/run_pi_budgeted.py` before the kickoff packet, owns one `lean --server` per toolchain with one open LSP document per concurrent draft (up to 4, bounded by memory). A draft is a `didChange`, so Lean re-elaborates from the first changed line. The socket is `lean-session.sock` in the run dir (short-path fallback). `engine.run_lean` uses it when `ARENA_LEAN_SESSION` is set and otherwise, or on any failure, compiles cold; each compat entry records `lean.path` (`session`, `cold`, `cold-fallback` plus reason). Stale detection: toolchain, pin, manifest, evaluator code hash, file prefix. `--no-lean-session` opts out; FakeRun defaults to it. Submission re-verifies session-vouched candidates with a clean cold compile (heartbeats within 5%).

**Spike.** LSP works; no REPL needed. The server must run without `lake setup-file` (`LAKE` pointed at nothing): the lakefile options otherwise turned the `sorry` warning into an error. Heartbeats differ by at most 0.25%. A worker costs about 0.6 GB (PhysLib) or 0.26 GB (Core) PSS; 4 workers plus server: 3.2 GB / 1.3 GB.

**Timing (s, before cold -> after session; noisy machine).**

| Path | Core | PhysLib |
|---|---|---|
| first Lean call (session start-up) | 4.1 -> 5.8 | 30 -> 54 |
| single probe | 4.1 -> 0.5 | 31 -> 0.4 |
| 4-draft batch | 10.6 -> 0.8 warm | 65-72 -> 0.6 warm |
| evaluate | 5.2 -> 1.2 | 45 -> 2.8 |
| profile (uncached floor) | 10.3 -> 2.9 | 92 -> 3.7 |
| kickoff context + profile (uncached) | 25 -> 17.5 | 162 -> 64 |
| declaration lookup fallback | 5.3 -> 1.1-2.3 | 33 -> 3 |
| autocheck, other toolchains | 8.7 -> 17.9 first, 8.5 -> 1.3 next | n/a |
| polish | 126 -> 118 (two intrinsically slow variants) | not run |
| `workspace()` per call | 100-130 ms -> 9 ms | same |
| daemon start / run init | 0.05-0.1 / 1.3-2 (unchanged) | same |

A batch sent right after the first probe waits for the other workers to open: 11 s (Core); 96 s (PhysLib, measured with the earlier sequential warm-up). Warm-up is now parallel; all 4 PhysLib workers were warm 154 s after the first call.

**Verification.** `tests/test_lean_session.py` (37 tests): session vs cold on Core and PhysLib for a compiling, failing and hole draft; stale, crashed, timeout, concurrent documents; daemon, Ctrl+C, killed runner and killed daemon leave no Lean processes. Full suite: 255 tests OK, 1 known skip. Node tests: 20 pass.

**Deviations / questions.** Other toolchains also use the session, so the first autocheck costs more. Cold re-verification adds about 13 s (Core) or 45 s (PhysLib) at run end. Suggested spec note: `lean.path` and `ARENA_LEAN_SESSION` are evaluation provenance. Workspace lookup fast path (`arena/environments.py`) is an unrelated survey fix.
