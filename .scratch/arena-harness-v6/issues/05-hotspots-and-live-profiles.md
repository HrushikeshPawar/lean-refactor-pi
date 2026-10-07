# 05: Hotspots and live profiles

**What to build:** The kickoff points an agent to the ten most costly starting lines in the reference proof, and the same agent can request an honest heartbeat and token profile after compiling a new candidate.

**Blocked by:** 03: Certified kickoff dependencies.

**Status:** needs-review

**Branch:** `hrushikesh/v6-05-hotspots` (stacked on `hrushikesh/v6-04-declarations`)

- [ ] Derive the top-ten ranking from all raw tactic records before detailed-output truncation. Attribute nested tactic **self** heartbeats to their starting proof line, combine that baseline cost with proof-line tokens using the row's score exchange rates, and display both axes with proof/file coordinates and tactic spans.
- [ ] Count tokens with the competition's proof tokenizer and maintain a source map through comment and blank-line removal. Per-line counts reconcile to the whole-proof token total; otherwise mark token attribution unavailable rather than inventing numbers.
- [ ] The kickoff distinguishes measured whole-proof heartbeats, attributed tactic coverage, statement floor (the existing `statement_floor_hb` measurement) and unattributed remainder. It labels the ranking as baseline cost, not predicted savings, and remains deterministic for a pinned row.
- [ ] `arena_profile` accepts the original or any complete compiling candidate and returns a full source-ordered heartbeat/token profile with both line coordinate systems. `arena_evaluate` reports whole-proof totals; repeat profiling of identical proof text uses a valid cache.
- [ ] Instrument only a scratch copy, on the row-selected measurement toolchain, with synchronous elaboration and no heartbeat limit. Insert wrappers before attached doc comments/attributes and preserve name resolution inside the theorem's scope. Never require instrumentation in a submitted proof.
- [ ] Pinned Core and PhysLib tests cover nested/multi-line tactics, top-ten order, no inclusive-cost double counting, token reconciliation, measured-versus-profile coverage, line mapping and a clearly labeled coarse fallback when fine instrumentation fails. No fabricated zero-cost table passes certification.

## Version control (GitButler)

Your branch is **`hrushikesh/v6-05-hotspots`**, already created and stacked directly above `hrushikesh/v6-04-declarations`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-05-hotspots` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-05-hotspots -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-05-hotspots` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
