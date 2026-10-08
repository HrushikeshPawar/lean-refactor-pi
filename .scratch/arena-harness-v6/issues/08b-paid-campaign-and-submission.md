# 08b: Paid campaign and manual submission package

**What to build:** Run the v6 campaign with ticket 08a's tooling, compare replicated results and stage a locally checked first warm-up submission package for the user's manual uploads.

**Blocked by:** 08a: Evaluation tooling, submission packager and fast tests.

**Status:** ready-for-agent

**Branch:** `hrushikesh/v6-08b-campaign` (stacked on `hrushikesh/v6-08-submission`)

- [ ] First cheap runs ($0.10 cap) with Luna and DeepSeek confirm the whole path end to end before the full campaign.
- [ ] Run the full campaign path on at least Core and PhysLib, with certified packets, the live Langfuse preflight, complete exact traces, local Lean checks and the stable request gate.
- [ ] Compare at least two theorem rows with three sequential replicates per configuration before claiming a score gain. Targets: zero preventable tool errors and under 5% combined overhead.
- [ ] Produce and validate the warm-up proof JSONL, provenance ledger, code archive and report. Obtain and pin the official template bundle (the user supplies it).
- [ ] Stage everything for the user's manual Hugging Face and OpenReview actions; never upload or submit automatically. Record local checks; the official worker result is the final calibration.

## Langfuse

**Required.** Use `/langfuse` for the live preflight read-back and run analysis (instance: `~/.pi/agent/langfuse.json`).

## Version control (GitButler)

Your branch is **`hrushikesh/v6-08b-campaign`**, already created and stacked directly above `hrushikesh/v6-08-submission`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-08b-campaign` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-08b-campaign -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-08b-campaign` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
