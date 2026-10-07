# 02: Fixed request shape and spend gate

**What to build:** A proof run can use its allowance without the harness reshaping a request at the edge. The operator can see why a request was sent or refused and reconcile every charged attempt to the per-problem total.

**Blocked by:** 01: Exact traces and live preflight.

**Status:** needs-review

**Branch:** `hrushikesh/v6-02-spend-gate` (stacked on `hrushikesh/v6-01-traces`)

- [ ] Keep output limit, thinking presence and thinking budget fixed from the first through the last request of a run, including continuations and retries. Never shrink or delete them to consume a small remaining balance.
- [ ] Check a conservative estimate before every provider send and continuation against the aggregate closed-track $3 per-problem ceiling. Decline an unaffordable request before transport; count retries and discarded candidates in the same ledger.
- [ ] Record the estimate, gate decision, actual settled cost, cache read/write, remaining allowance and overshoot for each attempt. The gate does not encode an unproven Qwen output-cap cache threshold.
- [ ] A fake-provider replay with a near-cap balance shows the final provider-bound request shape is identical to earlier attempts when sent, and no request is sent when the estimate is unaffordable. The journal and Langfuse observations agree with the ledger.
- [ ] The first refused request and a refused continuation end cleanly with the best verified candidate and a truthful stop reason; no partial candidate is presented as verified.
- [ ] Default the runner (`tools/run_pi_budgeted.py`, currently $1.0) and experiment matrix (`tools/run_experiment_matrix.py`, currently $0.10) to the $3 allowance; tests may pass a smaller explicit cap.

## Langfuse

Use the Langfuse skill (`/langfuse`) to check that gate decisions, estimates and settled costs agree between the journal, ledger and Langfuse observations (instance: `~/.pi/agent/langfuse.json`; v4 observations API).

## Version control (GitButler)

Your branch is **`hrushikesh/v6-02-spend-gate`**, already created and stacked directly above `hrushikesh/v6-01-traces`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-02-spend-gate` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-02-spend-gate -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-02-spend-gate` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
