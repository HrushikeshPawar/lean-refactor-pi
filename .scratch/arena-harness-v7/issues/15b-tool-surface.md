# 15b: TS five-tool surface, MCP server removed

**What to build:** The model sees exactly five tools: `compile`, `goal`, `search`, `read` and `finish`, registered by the Pi extension and served by the Python handlers of ticket 15a through `arena protocol`. Replies are rendered from the one reply schema; `finish` appears only when 10% or less of the budget is left and ends the run in one call. The Lean MCP server and the old eleven tools are gone from the extension, the run launcher and the Pi tests. A failed request gets its own factual continuation text, and malformed or null tool arguments are reported as "arrived empty or malformed" with the valid keys. The old Python protocol actions and handlers still exist and are deleted by ticket 15c.

**Blocked by:** 02: Actual-cost stop; 15a: Five-tool Python handlers and reply schema (all lower tickets are committed below your branch).

**Status:** done

**Branch:** `v7/15b-tool-surface` (stacked on `v7/15a-tool-handlers`)

**Read first:** spec "Tool surface" and "Interfaces and contracts" (Implementation Decisions), user stories 43-45 and 46-69, "Testing Decisions" Seam B; plan §4f, §4b table, §4e, §5h, §8 item 6, §12a (#8, #12, #26, #27, #35); decisions D15, D16, D28, D39, D40; `docs/ISSUES-harness-v7.md` #25a, #25b.

## Context: where things are now
- `packages/arena-pi/extensions/arena.ts`: registers 11 tools through `registerTool` (`arena_evaluate`, `arena_probe`, `arena_profile`, `arena_idea`, `arena_state`, `arena_finish`, `arena_candidate`, `arena_skill_read`, `arena_source`, `arena_declarations`, `arena_find`) and the Lean MCP server `arena-lean` in the `/arena` command handler (`pi.registerMcpServer`, `LEAN_DIRECT_TOOLS`, `LEAN_DISABLED_TOOLS`, `ARENA_NO_MCP`). Helpers there: `campaign(action, args)` (spawns `uv run --no-sync arena protocol <action> --theorem T --run-id R ...` and parses the last JSON line), `kickAutocheck`, `stateLine` / `readState` / `deliveredSeq` (the `[arena]` background-update line appended in the `tool_result` hook), `discoveryKeys`, `createIdea` / `inlineIdea`, `withStaleNotice`, `withProofFile(s)`, `applyFinishGate` (the finish tool is offered with `pi.setActiveTools` through `toolsForSpend`, `FINISH_TOOL = "arena_finish"`), the finish-review state (`finishReviewIssued`, `finishReminderIssued`, `finishRefusals`, `refusalIdeaIds`, `refusalRouteStats`, `refusalCredited`), the `agent_before_settle` continuation (it already computes `failed = event.outcome !== "completed"`, but builds the same "turn ended with text" content for both cases, with `continuationPush` and `frontier` ideas and routes), and the `tool_execution_end` bookkeeping (`turnHadProofAttempt`, `turnHadNovelContext`, `turnHadVerifiedImprovement`). `registerTool` wraps every tool with `prepareArguments: requireToolArguments`.
- `packages/arena-pi/extensions/rules.ts`: `planEvaluate`, `planProbe`, `resolveInlineIdea`, `leanPathViolation`, `routesText`, `sinceRefusal`, `staleNotice`, `finishPush`, `continuationPush`, `axisHeadroom`, `allowanceFacts`, `trimProfile`. Their strings are templates in `agent-text/` (tickets 05a and 05b). `rules.test.ts` tests them.
- `packages/arena-pi/extensions/trim.ts`: `ResultTrimmer` (`STUBBABLE_TOOLS` names old tools, `compactDiagnostics` for MCP results), `objectToolArguments`. `toolnames.ts`: `nearestToolName`, `normalizeToolArguments` (`KEY_SYNONYMS`, removes empty values, so `{}` passes through), `requireToolArguments` (throws `MISSING_ARGUMENTS_ERROR`, a literal sentence, on a null/undefined argument object), `toolCore` / `PREFIXES`. `spend.ts`: the one spend rule and `finishAllowed` / `toolsForSpend` (kept).
- Ticket 15a's Python side: `arena/reply.py` (reply schema `ok`, `error`, `facts`, `items`, `handles`, `map`, `stop`), `arena/tools.py` (`compile_tool` and the other four handlers), protocol actions `compile goal search read finish reset_delivered` taking `--request-file <path>` and printing one JSON line; `empty_arguments` is a Python error code; `finish` returns `stop: true` on its one call. Keys in `agent-text/numbers.yaml`: `compile_max_drafts` (and the finish fraction).
- Tests of old tool shapes in `tests/test_runner.py` (87 references): fake-provider helpers `cheap_tool(name, args, output=...)`, `tool_texts`, `message_text`, `self.fake([...])`, plus `tests/pi_support.py` and `tests/fake_opencode.ts`. The two known slow failures are `ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas` and `AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`. This ticket resolves both (rewritten or deleted, see checkbox 12). Also `tests/test_traces.py` and the TS tests `rules.test.ts`, `trim.test.ts`, `toolnames.test.ts`, `spend.test.ts`.
- Pi runs with `--no-builtin-tools` (`tools/run_pi_budgeted.py`, now possibly `arena run`), so the tool name `read` does not clash with a built-in.
- Ticket 08b put goal-at-position and snippet-at-hole on the Lean service's LSP lane; ticket 15a's `compile` and `goal` handlers use them. Nothing needs the MCP server any more.

## What to build
- [ ] 1. **Register the five tools in `arena.ts`.** Names exactly `compile`, `goal`, `search`, `read`, `finish`. Descriptions and every parameter description come from `agent-text/tools/<tool>.yaml` (create the five files with minimal neutral wording, one sentence per parameter; no old tool is mentioned; the description of `compile` states the draft limit and of `finish` the finish fraction, both rendered from `numbers.yaml`, ticket 05a's consistency test checks them). Schemas are top-level `Type.Object`s (a provider rejects a top-level `anyOf`): `compile` `{drafts?: string[1..max], splice?: {base?, steps, text}, fill?: {hole, text}, merge?: {base?, take: [{from, step}]}, base?, from?, note?, check?: "tokens"|"lean"}`; `goal` `{node?, hole?, line?, try?: string[]}`; `search` `{queries: string[], kind?: "name"|"type"|"text", after?}`; `read` `{handle?, node?, hole?, view?: "source"|"prices"|"diff"|"outline"|"map", against?}`; `finish` `{}`. `execute` writes the arguments to a temp file, calls `campaign("<tool>", ["--request-file", file])`, and returns the reply. Update `toolnames.ts` `KEY_SYNONYMS` (remove `title`; map `draft` and `proof` to `drafts` for `compile`) and its tests. The old eleven registrations are removed.
- [ ] 2. **Reply rendering, `packages/arena-pi/extensions/reply.ts`.** `renderReply(reply, footer)` builds the model-visible text: `facts` lines, then each item's `lines` (or its error line), then the map lines when present, then one line `handles: ...` when non-empty, then the footer. `details` keeps the full JSON. `isError` is `ok === false`. The footer is added in the existing `tool_result` hook for all five tools (it already adds the spend footer today; keep one place, keep the template from `messages/footer.md`). Delete `stateLine`, `readState`, `deliveredSeq`, `deliveredBest` from `arena.ts`: updates now arrive inside replies (ticket 15a). node:test `reply.test.ts` covers: item order, an item error rendered with its valid forms, handles line omitted when empty, `isError` only for a top-level failure.
- [ ] 3. **Finish gate and the one-call finish (decision 6).** `FINISH_TOOL = "finish"`; `applyFinishGate` / `toolsForSpend` unchanged in behaviour (finish offered only at or below the finish fraction, read from `numbers.yaml`; update `spend.test.ts` names). The `finish` execute calls `campaign("finish")`; a reply with `stop: true` sets `finishConfirmed` at once, writes the `control` row with `stop: "finished"` (or `"limit_reached"` when the limit was hit in the same call, as today) and `tool_execution_end` aborts the run as today. There is no confirm step, no review turn, no reminder and no refusal. Delete from `arena.ts` the finish-review state (`finishReviewIssued`, `finishReminderIssued`, `finishRefusals`, `refusalIdeaIds`, `refusalRouteStats`, `refusalCredited`, `finishReviewTurn`) and the `finish_review` activity field's use, and from `rules.ts` `finishPush`, `routesText`, `sinceRefusal`, `axisHeadroom` and `allowanceFacts` where nothing else calls them (the arithmetic is in Python since 15a; `grep` each name before deleting).
- [ ] 4. **Continuation text, including a failed request (#26).** In `agent_before_settle` keep the error streak, backoff and stop logic untouched (ticket 06 owns it). Replace the content built after it: `continuationPush` and the "Continue proof optimization" prompt use only spend, the 10% rule and per-axis points left (neutral facts, text from `agent-text/messages/continuation.md`; ticket 16 rewrites) and name the best node from `frontier`, with no ideas list and no routes. Add two keys to `continuation.md`: `request_failed` (states that the request failed, with the cause when Pi gives one, `event` or the failed message's `errorMessage`) and `turn_ended_with_text` (the existing "ended with text" fact). When `failed` is true use `request_failed`; otherwise `turn_ended_with_text`; a failed request is never described as a turn that ended with text. Both keys render the same spend and points-left facts, supplied by one helper.
- [ ] 5. **Malformed and null tool arguments (#27).** (a) An argument object with no recognised key, or only empty values, is no longer silently forwarded as `{}` from the TS side: `normalizeToolArguments` / the `execute` path keeps forwarding it to Python, which answers `empty_arguments` (ticket 15a), and the rendered reply says the call "arrived empty or malformed" and lists the tool's valid keys (template `agent-text/messages/errors.yaml`, key `empty_arguments`, supplied with the schema's property names by the TS renderer). (b) A null or undefined argument object (`requireToolArguments`) throws an error whose text comes from the template key `arguments_missing` of the same file (rendered with the tool's valid keys), replacing the literal `MISSING_ARGUMENTS_ERROR`; delete the literal. (c) Plan §12a #27 also says a null-argument call is re-requested once with the same turn and a second null is reported. Look at how Pi lets an extension re-issue a turn (`prepareArguments`, the `message_end` repair `repairMalformedToolArguments`, `agent_before_settle` returning `continue: true`). If there is a supported way, implement it with a counter that allows one re-request per turn; if there is none, implement only (a) and (b), do not build a mechanism around Pi, and list it under Open questions of the hand-back.
- [ ] 6. **Hooks and bookkeeping.** In `tool_execution_end`: `turnHadProofAttempt` is true after a `compile` with `check` lean that returned any item with a node; `turnHadNovelContext` after a `search`, `read` or `goal` result whose content signature is new (`discoveryKeys` reads `search` hits, `read` handles and ranges, `goal` goals); `turnHadVerifiedImprovement` unchanged. On `session_compact` call `campaign("reset_delivered")`, and keep `trimmer.forget()`. `ResultTrimmer`: `STUBBABLE_TOOLS` = `search`, `read`; delete `compactDiagnostics`, its tests and the `mcp__arena_lean__` branch (MCP is gone).
- [ ] 7. **Remove the Lean MCP server (decision 11, D40).** Delete the `pi.registerMcpServer` block, `LEAN_DIRECT_TOOLS`, `LEAN_DISABLED_TOOLS`, `leanProject`, the `mcp__arena_lean__` branch of the `tool_call` hook, `leanPathViolation` and its tests, and the `builtin:mcp` extension flag and `--no-mcp` / `ARENA_NO_MCP` option in the run launcher (`grep -rn "no_mcp\|ARENA_NO_MCP\|builtin:mcp" tools arena packages tests`). `goal` and `compile` are served by the Lean service lanes (ticket 08b for goals at a position/hole and snippets at a hole, 08c for the callers), so nothing calls the MCP backend and no text may say it becomes a hidden backend. The `tool_call` hook still blocks `bash`, `write` and `edit` into workspaces; reword its reason through `agent-text/messages/` to name the five tools. **If ticket 08b's LSP lane cannot return goals at a position or run a snippet at a hole, stop and report; do not keep the MCP server as a hidden backend without asking.**
- [ ] 8. **Delete the TS code the old tools alone used.** After checkboxes 1 to 7, remove from `arena.ts` and `rules.ts` every function, constant and flag with no remaining caller (`planEvaluate`, `planProbe`, `resolveInlineIdea`, `createIdea` / `inlineIdea`, `withStaleNotice`, `staleNotice`, `trimProfile`, `kickAutocheck` only if unused, the idea state, `ARENA_SKILL_DIR` and `SKILL_READ_LIMIT`), with their tests. For each name, `grep -rn "<name>" packages` must show no user before you delete it; list each deleted name in the hand-back. Delete the templates in `agent-text/` that only that code supplied, so the agent-text consistency test stays green.
- [ ] 9. **Minimal text updates so nothing mentions a deleted tool.** In `agent-text/` make the smallest edits that remove every mention of `arena_probe`, `arena_evaluate`, `arena_profile`, `arena_idea`, `arena_state`, `arena_candidate`, `arena_skill_read`, `arena_find`, `arena_declarations`, `arena_source`, `lean_goal`, `lean_multi_attempt`, `lean_diagnostic_messages`, `lean_hover_info`, `lean_local_search` and ideas from the skill, the packet task template, the continuation, memory and refusal messages, replacing them with one neutral sentence naming the five tools. In the skill remove the "Tool workflow" and "Working principles" tool sentences and the idea and `arena_skill_read` sections and add a five-line tool list. Do not rewrite for quality: ticket 16 does that. If a Python test asserts a sentence you removed (`tests/test_context.py`, `tests/test_memory.py`), change the assertion to the behaviour it protects and list it in the hand-back. Delete `ARENA_SKILL_DIR`, `SKILL_READ_LIMIT` and the `arena_skill_read` smoke prompt in the run launcher (replace it with a prompt that asks for one `read` of the original node and no more; keep the option).
- [ ] 10. **Migrate the Pi fake-provider tests (Seam B) in `tests/test_runner.py`.** Rewrite to the five tools, keeping what each proves: the run stops after the first call that reaches the limit and never before; `finish` is offered only in the final ten percent (use `read` of the original node as the cheap tool whose reported cost moves the spend, instead of `arena_state`) and one `finish` call ends the run; history append-only and cache alarm (cache tests); malformed JSON arguments are rejected, not run (use `compile`); a misnamed tool gets the nearest registered name (`compile` for `compil`); `every_arena_tool_succeeds_with_the_arguments_models_actually_send` for all five tools with the argument shapes models send (stringified lists, empty optional fields, `draft` for `drafts`); a cross-version result arrives in the compile reply, history is not rewritten, and the submission is the verified candidate (this rewrites `test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`); checks queued when the model stops are finished before submitting; error-loop and continuation tests keep their stop-code assertions with new tool names; the Anthropic wire tests keep their assertions with the new tool list; a skill-names test asserting the skill mentions only the five tools (replace `SkillToolNamesTests`). Delete `LeanMcpTests`, `test_search_first_discovery...`, `test_search_first_replay...` unless a `search`/`read` version proves something the other tests do not (identical `read` repeats become a stub and cannot extend the run: keep one such test), and the idea tests (`test_failed_skeleton_is_an_attempt_and_does_not_remind_or_abandon_idea`, `test_declaring_a_new_idea_closes_the_previous_one_from_known_outcomes`, `test_continuation_names_the_best_candidate_and_the_models_active_ideas`). `test_batch_probe_turns_count_as_proof_attempts` becomes a compile-drafts test. State every deleted test and the reason in the hand-back.
- [ ] 11. **Test: factual continuation after a failed request (#26).** In `tests/test_runner.py` (Seam B): a fake-provider run whose first request fails and whose next turn continues produces a continuation message that contains the failure fact and does not contain the "ended with text" wording; a turn that ends with text produces the other one. Assert on which template key was rendered through the stable parts of the message (the spend and points-left numbers equal the computed ones), not on copied sentences. Add a node:test in `rules.test.ts` for the helper that picks the key (failed gives `request_failed`, completed gives `turn_ended_with_text`, the numbers are identical in both).
- [ ] 12. **Test: malformed and null arguments (#27).** `toolnames.test.ts`: a null argument object and `{}` each render an error naming "arrived empty or malformed" through the template and listing the tool's valid keys (assert the keys appear, not the sentence); stringified lists and empty optional fields still normalise as before. In `tests/test_runner.py` keep one fake-provider case that sends `{}` and one that sends null arguments to `compile`: the run continues, the reply is an error item listing valid keys, and no Lean runs.
- [ ] 13. **TS unit tests.** Update `rules.test.ts`, `trim.test.ts`, `toolnames.test.ts`, `spend.test.ts` to the five tools; delete tests of deleted functions. Run `cd packages/arena-pi && npm test`.

## Do NOT
- Do not delete any Python protocol action, `arena/campaign.py` handler, idea code in `summary.py`, `viewer_data.py`, `memory.py` or the viewer, or any Python test of old tool shapes: ticket 15c does that. After this ticket the old actions are unreachable from Pi but still pass their own Python tests.
- Do not rewrite model-facing text for quality, shorten it or re-organise it: ticket 16 owns the full rewrite. Add and edit only the templates this ticket needs, with minimal neutral wording, and keep one rule in one place.
- Do not put a model-facing literal in TS (D3). Error codes, keys and ids are not prose; sentences are.
- Never name a kind of proof ("induction", "lemma", "recursion", "simp") in any template, error or fact.
- Do not touch `spend.ts` rules (limit, stop, `finishAllowed`) except renaming the finish tool, and do not change run-control logic (error streak, backoff, outage wait): ticket 06 owns it.
- Do not change the Python handlers or reply schema of ticket 15a, the graph core, routes, salvage, price engine, search or Lean service code. If a function you need is missing or differs, stop and report.
- Do not keep a deleted tool as an alias for compatibility, and do not keep the MCP server as a hidden backend. The model sees five tools only.
- Do not add a confirm step, a review turn or a reminder to `finish`.
- Do not touch the viewer, `arena replay` or the blob store (tickets 17 to 19).

## Acceptance
- A Pi run with the fake provider lists exactly five tool names at the start of the run: four of them (`compile`, `goal`, `search`, `read`) and `finish` only after the spend reaches the final 10%; the Lean MCP tools and the old tool names never appear.
- One `finish` call ends the run with stop reason `finished`.
- A `compile` call with two drafts returns both results in one rendered reply; `{}` and null arguments are reported as arrived empty or malformed with the valid keys, never as a missing field.
- After a failed request the continuation message states the failure and the same spend and points-left numbers as the other continuation; it never says the turn ended with text.
- `grep -rn "registerMcpServer\|ARENA_NO_MCP\|builtin:mcp\|mcp__arena_lean" packages tools arena tests` finds nothing.
- Neither known slow failure remains; the rewritten tests that replace them pass.

## Verify
Test budget: targeted files first, the fast suite once at the end. The slow file is listed because this ticket changes Pi behaviour; run it once at the end plus once for the baseline.
- `cd packages/arena-pi && npm test` -> all pass (give before and after counts).
- `uv run pytest -q -p no:cacheprovider tests/test_traces.py tests/test_memory.py tests/test_context.py` -> all pass (the files whose assertions you may have touched).
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_runner.py` -> all pass except tests that need a real Lean worker you cannot run; name any skipped or failing test and show that it fails identically on your baseline.
- `grep -rn "registerMcpServer\|ARENA_NO_MCP\|builtin:mcp\|mcp__arena_lean" packages tools arena tests` -> no output.
- `grep -rn "arena_probe\|arena_evaluate\|arena_candidate\|arena_state\|arena_idea\|arena_profile\|arena_skill_read\|arena_find\|arena_declarations\|arena_source\|arena_finish" packages agent-text tests/test_runner.py` -> no output.
- `uv run ruff check <touched python files> && uv run ruff format --check <touched python files>` -> clean.
- `uv run arena text budget` (ticket 05a) -> runs; list the five new tool templates and their word counts in the hand-back.
- At the end, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count minus deleted tests plus new ones; give both numbers).

## Stop and report if
- Ticket 15a's protocol actions or reply schema differ from what this ticket assumes (names, `--request-file`, `stop`, `empty_arguments`). List what differs and stop.
- Ticket 08b's LSP lane has no goal-at-position request, or cannot run a snippet at a hole without creating a node (checkbox 7).
- `pi.setActiveTools` does not accept the new names, or `--no-builtin-tools` does not remove a built-in named `read` in the fake-provider run.
- Deleting a function in checkbox 8 breaks a test that proves something about a kept behaviour (spend, error loop, submission). Stop before deleting; list the test.
- The continuation hook gives no failure cause: render `request_failed` without a cause and list it as an open question (do not stop for this alone).
- You run out of context. Commit what is finished, set nothing to `needs-review`, and report which checkboxes remain.

## Before you start

1. Read, in this order: this whole ticket; `docs/SPEC-harness-v7.md` (sections named in this ticket); the
   `docs/PLAN-harness-v7.md` sections named in this ticket. The plan's decision rows (D1-D39 at the top) are
   binding: do not undo a decision, and do not undo any "probe evidence" listed in the spec's Further Notes.
2. Run `uv sync` once. All Python runs through `uv run`.
3. Record a baseline **before any edit**, only for the tests this ticket touches: run the test files named in
   this ticket's "Verify" section (and the test files for the modules you will change). Keep the output for
   your hand-back. Do **not** run the whole slow suite for a baseline.
4. If something in this ticket contradicts the code you find, or a step is impossible as written, **stop and
   report**. Do not guess, and do not redesign.

## Rules for every change

- Do exactly what the checkboxes ask. Nothing outside this ticket's scope: no drive-by refactors, no renames,
  no "while I'm here" fixes. If you see a real bug outside scope, list it in the hand-back.
- **No model-facing text in code** (D3): any string the model reads (tool descriptions, replies, notices,
  packet text) goes in `agent-text/` (after ticket 05a) and is rendered by the template renderer.
- **Neutral wording** in anything the model reads: graph position and numbers only. Never name a kind of proof
  ("induction", "lemma", "recursion", "simp proof", ...).
- Match the surrounding code: naming, comment density, idioms. Python 3.13, type hints where the file uses them.
- Python you touch must pass `uv run ruff check <files>` and `uv run ruff format <files>`. Fix ty diagnostics
  in the files you touch (`uv run ty check <files>`); do not touch other files to fix them.
- **Test runtime budget.** Today the fast suite (`uv run pytest -q -p no:cacheprovider`, no Lean, no Pi) takes
  about 35 s; `tests/test_runner.py` with `ARENA_SLOW_TESTS=1` takes about 7 min; the full slow suite takes most of
  an hour. So:
  - While developing, run only the tests you changed or that cover the code you changed:
    `uv run pytest -q -p no:cacheprovider tests/test_x.py -k <name>`.
  - Run the fast suite **once**, at the end, before your final commit.
  - Run a slow test file (`ARENA_SLOW_TESTS=1 ...`) only if this ticket's "Verify" lists it, and only **once**
    at the end (plus once for the baseline). Never run `ARENA_SLOW_TESTS=1` on the whole `tests/` directory.
  - `npm test` is under a second; run it whenever you change TS.
  - If a test you add takes more than 5 s, it must be `@slow`.
- Tests: only behaviour where a bug costs points, money or time. No tautological tests (no restating
  constants or config, no "mock was called", no substrings copied from the source under test, no dataclass
  defaults). Python tests are unittest style, run by pytest. Lean- or Pi-backed tests use the `@slow`
  decorator from `tests/slow.py`. TS tests use `node:test`.
- Never read `/proc` or live Lean sessions from a test; inject machine readings.
- Foreground commands only. No background jobs, no polling loops, no `sleep` loops. Kill processes **by PID
  only**, never by name or pattern (`pkill -f`, `killall` are forbidden).
- Never print, log or commit secrets (`.env` holds API keys). Never spend money: no real model calls. Paid runs
  are launched by the owner only.
- Do not edit `docs/`, `research/`, `vendor/` or other tickets. Proposed doc changes go in the hand-back.

## Version control (GitButler)

Your branch is **`v7/15b-tool-surface`**, already created and stacked directly above `v7/15a-tool-handlers`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/15b-tool-surface` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/15b-tool-surface -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-15b`.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`,
  `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or
  `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`,
  `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`,
  `branch`, `update-ref`, `push`, `rm`, `mv`). Read-only `git log`, `git show`, `git diff` and `git blame` are
  fine. To delete or move a tracked file, use the shell (`rm`, `mv`); GitButler sees the change.
- If you need to change code a lower ticket introduced, do it in a commit on your own branch and say so in the
  hand-back. If `but commit` reports a dependency or conflict error, stop and report rather than moving branches.

## Hand-back (required)

Your work is finished only when all of this is true:

- [ ] Every checkbox in "What to build" and "Acceptance" is done, or listed below as not done with the reason.
- [ ] Every change is committed on `v7/15b-tool-surface`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-15b
Commits: <id> <summary>, one per line, oldest first
Checkboxes: each checkbox, done / not done (+ reason)
Tests: baseline -> final counts for every command you ran, with failures named
Verify: output summary of each Verify command (timings, numbers)
Files: every file added, changed or deleted, one line each on why
Decisions: anything you had to decide that this ticket did not say
Deviations: anything done differently from the ticket, and why
Out of scope: bugs or problems noticed but not fixed
Open questions: for the reviewer
```

Do not mark the ticket done; the reviewer does.
