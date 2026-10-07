# 06: Proof-tool UX and error replay

**What to build:** Natural agent inputs for drafting, scoring and inspecting a proof work through the model-facing tools, while truly invalid data fails clearly. The valid-intent mistakes seen in v5 no longer waste provider turns.

**Blocked by:** 04: Declarations, search and source lookup; 05: Hotspots and live profiles.

**Status:** needs-review

**Branch:** `hrushikesh/v6-06-proof-tools` (stacked on `hrushikesh/v6-05-hotspots`)

- [ ] Probe one to four drafts per call in the model's Lean lane. Normalize `by` and `:=` bodies against the exact benchmark statement and return one outcome per draft: fails, compiles with holes and goals, or complete and compiling with an automatically promoted candidate ID.
- [ ] Complete probes in a batch are candidates, and partial probes expose all actual hole goals. Stable probe/candidate IDs and parent lineage survive scoring, restoration and profiling.
- [ ] Evaluation accepts complete proof text or an unambiguous stable reference. Conflicting candidate/probe references are rejected or resolved explicitly; `sorry` sent to evaluation points to probing. Diagnostics and profiles label proof-relative and source-file lines accepted by goal lookup.
- [ ] Tool schemas match runtime-required fields. Malformed JSON never silently becomes an empty object; a misnamed tool suggests the nearest registered tool. Missing names, invalid ranges, Lean rejection and provider failure retain distinct typed outcomes.
- [ ] Add a small, sanitized replay fixture for the valid-intent inputs from all 14 v5 runs, independent of ignored local run logs. Classify the 32 historical error-returning calls and achieve zero preventable errors and zero mismatched line lookups on replay without turning genuine failures into success.
- [ ] Demonstrate the complete agent route from batched search or declaration lookup to source, probe, evaluation, profile and goal inspection on pinned Core and PhysLib rows.
- [ ] Remove `arena_polish` from the model-facing tools. Keep `arena_candidate` for restoration (the Lean MCP `lean_goal` reads the restored file) and `arena_skill_read` unchanged. A tool that defaults to "the current candidate" keeps the existing meaning: the original at kickoff, then the latest evaluated or restored candidate.

## Version control (GitButler)

Your branch is **`hrushikesh/v6-06-proof-tools`**, already created and stacked directly above `hrushikesh/v6-05-hotspots`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-06-proof-tools` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-06-proof-tools -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-06-proof-tools` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
