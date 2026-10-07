# 07: Ideas, finish and run accounting

**What to build:** The agent records a structural route once, sees its attempts and outcomes without repeated bookkeeping, and can end a run after one bounded review. The run summary tells the operator what was tried, what improved and what was spent.

**Blocked by:** 02: Fixed request shape and spend gate; 06: Proof-tool UX and error replay.

**Status:** ready-for-agent

**Branch:** `hrushikesh/v6-07-ideas-finish` (stacked on `hrushikesh/v6-06-proof-tools`)

- [ ] One short `arena_idea` creation sets the current strategy. Later probes, evaluations and candidates inherit it unless explicitly overridden; append-only events derive attempts, failures, candidates and best result. A directly promoted complete probe counts as an attempt even without a separate probe event.
- [ ] An agent can revise or abandon an idea with a short reason and can start another without erasing earlier lineage. `arena_state` and status responses are concise, show the verified baseline truthfully and never demand repeated title/hypothesis text.
- [ ] The first argument-free `arena_finish` returns one factual review of the best verified candidate and current idea. At most one reminder is issued for a current idea with no linked proof attempt; the agent can probe or abandon it. A later finish confirms stop, and new ideas cannot reset review/reminder limits.
- [ ] Two consecutive completed turns with no new proof attempt, verified improvement or substantive context result trigger a no-work fallback. A distinct newly returned declaration, goal or source span counts as discovery; repeated reads, idea-only and state-only turns do not reset it. The first finish-review turn is excluded so the agent gets a full decision turn; a confirmed finish sends no further provider request and the spend gate still takes precedence.
- [ ] Sanitized turn-boundary replays preserve the later best candidates after Luna r2's and Qwen CSLib's first finals, then stop after confirmation. Replay Qwen's 16–19-turn search-first discovery without premature fallback and prove repeated identical reads cannot prolong a stalled run. A single failed skeleton does not automatically close an idea.
- [ ] The live log and run/matrix summaries count requests separately from tool results, classify bookkeeping and rejected spend correctly, report retries, cache prefix reuse, overshoot, post-best spend and zero-attempt ideas, and use the **same** candidate for score, tokens and heartbeats.

## Langfuse

Use the Langfuse skill (`/langfuse`) when checking replay and summary counts against traced requests and tool spans (instance: `~/.pi/agent/langfuse.json`; v4 observations API).

## Version control (GitButler)

Your branch is **`hrushikesh/v6-07-ideas-finish`**, already created and stacked directly above `hrushikesh/v6-06-proof-tools`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-07-ideas-finish` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-07-ideas-finish -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-07-ideas-finish` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
