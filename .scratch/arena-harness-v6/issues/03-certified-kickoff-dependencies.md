# 03: Certified kickoff dependencies

**What to build:** An agent opening a pinned theorem sees the names the original declaration actually uses, plus additional direct theorem and lemma dependencies from its elaborated proof, and can tell whether the inventory is complete.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

**Branch:** `hrushikesh/v6-03-kickoff` (stacked on `hrushikesh/v6-02-spend-gate`)

- [ ] Inventory every resolvable source-named declaration in the original theorem declaration. Preserve occurrences and distinguish first appearance in the statement from appearances in the proof without claiming those sets are exclusive.
- [ ] Separately identify additional theorem and lemma constants directly used by the elaborated original proof term. Keep the complete constant index queryable by name, kind and origin; generated tactic and typeclass entries are not presented as source-authored lemmas.
- [ ] The kickoff gives each required name a qualified form, kind, origin and usable source handle; local variables have scope/type. It identifies the pinned revision/toolchain, available tactic imports and original proof as candidate #1.
- [ ] Show a bounded signature preview with inventory/shown/unavailable counts. No required name disappears silently during packet fitting, and a deterministic section manifest fails certification when an expected section is absent.
- [ ] Repeated builds for the same pin have identical packet bytes. Pinned Core and PhysLib fixtures account for every known source name and extra direct theorem/lemma dependency; provisioned rows certify or fail before a paid run.
- [ ] Kickoff guidance asks the agent to survey the supplied references before recording a route; it does not impose a three-ideas-at-start quota.

## Version control (GitButler)

Your branch is **`hrushikesh/v6-03-kickoff`**, already created and stacked directly above `hrushikesh/v6-02-spend-gate`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-03-kickoff` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-03-kickoff -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-03-kickoff` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
