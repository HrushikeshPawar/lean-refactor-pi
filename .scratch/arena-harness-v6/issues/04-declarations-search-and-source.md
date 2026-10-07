# 04: Declarations, search and source lookup

**What to build:** An agent can pass several names at once, read complete pinned declarations where source exists, search for other helpers, and follow every returned handle to the right file and line without guessing path syntax.

**Blocked by:** 03: Certified kickoff dependencies.

**Status:** needs-review

**Branch:** `hrushikesh/v6-04-declarations` (stacked on `hrushikesh/v6-03-kickoff`)

- [ ] Model-facing `arena_declarations` accepts several qualified names or returned handles and gives one result per input: complete human-readable source statement and body/proof, or a typed reason that a body is opaque, generated, private, external or unavailable. Local variables return scope/type instead of a fabricated global body. Replace the model-facing single-name `arena_declaration` rather than leaving two competing lookup paths.
- [ ] Long declarations page without losing content or silently dropping other requested names. Source bodies come from the pinned checkout; pretty-printed elaborated terms are not mislabeled as source proofs.
- [ ] Model-facing `arena_find` accepts several names or strings, counts distinct qualified declarations toward its limit, excludes scratch copies, and supplies useful qualified-name suggestions for misses. An unvalidated related-lemma ranking formula is not silently introduced.
- [ ] Every handle emitted by kickoff, search or declaration lookup round-trips through `arena_source`. Known project aliases and dependency roots resolve; results state pin, canonical path, file length and one-based file lines.
- [ ] Tests cover local, imported, private, generated, long and unavailable declarations, ambiguous names, bad ranges and returned-handle round trips on at least two theorem families. Genuine not-found results remain explicit errors.

## Hand-back

- Commits on `hrushikesh/v6-04-declarations`: `tpk`, `zlu`, `wlw`, `yky`, `knw`, `wvw`, `omv`, and this hand-back commit.
- Offline full suite: 183 tests passed, 1 live Langfuse test skipped (`ARENA_LIVE_LANGFUSE=1` required). This run preceded the final shared-parser refactor.
- After the shared-parser refactor: 16 focused lookup, declaration protocol, and kickoff packet tests passed.
- No Langfuse traces or session IDs were used. TypeScript typechecking was unavailable because the package has no local dependency installation or TypeScript project configuration.
- Standards feedback addressed by sharing namespace/declaration parsing between search and exact source lookup.

## Version control (GitButler)

Your branch is **`hrushikesh/v6-04-declarations`**, already created and stacked directly above `hrushikesh/v6-03-kickoff`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-04-declarations` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-04-declarations -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-04-declarations` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
