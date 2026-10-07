# 08: Integrated evaluation and manual submission package

**What to build:** An operator can run v6 across different pinned theorem families, compare replicated results, and hand the user a complete, locally checked first warm-up submission package made only from v6 model-produced proofs.

**Blocked by:** 07: Ideas, finish and run accounting.

**Status:** ready-for-agent

**Branch:** `hrushikesh/v6-08-submission` (stacked on `hrushikesh/v6-07-ideas-finish`)

- [ ] Run the full campaign path on at least Core and PhysLib with certified packets, tool round trips, a cheap live Langfuse preflight, complete exact traces, local Lean checks and the stable request gate. An absent mandatory observation or packet section stops evaluation before paid runs.
- [ ] Compare at least two theorem rows and use three sequential replicates per configuration before claiming a score gain. Report score distribution, helper discovery, truly unattempted ideas, preventable tool errors, cache outcomes, corrected bookkeeping plus rejected spend and all-call per-problem cost. The targets are zero preventable tool errors and under 5% combined overhead.
- [ ] Select only complete, locally verified, model-produced v6 candidates. No v5 proof, analyst-combined hybrid, incomplete proof or unverifiable provenance enters the submission set.
- [ ] Produce and validate warm-up proof JSONL with exact benchmark identifiers from the official manifest `benchmark/original/warmup.jsonl`, full declarations and prohibited-construct checks. Recompute each proof hash and join it to candidate/run IDs, pinned source/toolchains, model/provider/version, Langfuse trace identities and **every** charged API attempt, including retries and discarded candidates.
- [ ] Enforce the closed-track $3 per-problem ceiling and confirm eligibility of each actually used model. Prepare a code archive with top-level reproduction instructions and pinned dependencies. Obtain and pin the official competition template bundle, then produce and build its report with Approach, Models, Budget accounting and Reproduction using the actual run data; the repository currently contains staging instructions but no template files.
- [ ] Stage the final proof JSONL, provenance, archive and report for the user's manual Hugging Face and OpenReview actions. Do not upload or submit automatically. Record local checks and leave the official worker result as the final calibration after the user uploads.

## Langfuse

**Required.** Use the Langfuse skill (`/langfuse`) for the live preflight read-back and for run analysis: query observations by run/session ID, reconcile all-call costs and collect the trace IDs recorded in provenance (instance: `~/.pi/agent/langfuse.json`; v4 observations API).

## Version control (GitButler)

Your branch is **`hrushikesh/v6-08-submission`**, already created and stacked directly above `hrushikesh/v6-07-ideas-finish`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-08-submission` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-08-submission -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-08-submission` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
