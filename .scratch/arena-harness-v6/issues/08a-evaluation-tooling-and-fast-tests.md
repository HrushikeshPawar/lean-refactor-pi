# 08a: Evaluation tooling, submission packager and fast tests

**What to build:** Everything ticket 08b needs to run a v6 campaign and stage a submission, built and tested offline, so no money is spent before the tooling is reviewed. A default test run gives feedback in about two minutes.

**Blocked by:** 07: Ideas, finish and run accounting.

**Status:** in-progress

**Branch:** `hrushikesh/v6-08-submission` (stacked on `hrushikesh/v6-07-ideas-finish`)

- [ ] Fast default tests: `uv run python -m unittest discover -s tests -t .` finishes in about 2 minutes. Tests that start Pi, compile Lean, open a Lean session or call a live service run only with `ARENA_SLOW_TESTS=1`. The skip states that reason, and no test is deleted only for being slow. Tests that are redundant or near-duplicates may still be removed.
- [ ] Campaign driver: run several theorem rows × configurations × N sequential replicates (default 3) with one fixed packet per row. Before any paid run, stop if the Langfuse preflight fails or a mandatory observation or packet section is missing. A `--dry-run` prints the plan and its worst-case cost.
- [ ] Comparison report across replicates and rows: score distribution, helper discovery, ideas never attempted, preventable tool errors, cache outcomes, bookkeeping and rejected spend %, all-call per-problem cost. Reuse ticket 07's summary fields.
- [ ] Submission packager: select only complete, cold-verified, model-produced v6 candidates. Write warm-up JSONL whose names and statements match `benchmark/original/warmup.jsonl` exactly, with full declarations and prohibited-construct checks. Recompute each proof hash. Reject v5 proofs, hybrids, incomplete proofs and unknown provenance.
- [ ] Provenance ledger: join each proof hash to candidate and run IDs, pinned sources and toolchains, model/provider/version, `lean.path`, Langfuse trace IDs and **every** charged API attempt, including retries and discarded candidates.
- [ ] Enforce the closed-track $3 per-problem ceiling across all calls and check each model used against an eligibility list.
- [ ] Code archive with top-level reproduction instructions and pinned dependencies. A report generator with Approach, Models, Budget accounting and Reproduction sections, filled from run data. Leave the official template as a pluggable input, since the bundle is not in the repository yet.
- [ ] Offline tests for all of the above use fixture run directories, not live runs.

## Langfuse

Trace-ID collection uses the Langfuse v4 observations API (`~/.pi/agent/langfuse.json`). Offline tests use fixtures; live checks only under `ARENA_LIVE_LANGFUSE=1`.

## Version control (GitButler)

Your branch is **`hrushikesh/v6-08-submission`**, already created and stacked directly above `hrushikesh/v6-07-ideas-finish`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-08-submission` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-08-submission -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-08-submission` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
