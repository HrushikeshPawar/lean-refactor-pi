# Harness v7: issues to fix (from v6pilot, v6cov and v6ark, 2026-10-09)

Bugs and gaps that v6 left open, with evidence from real runs. The design ideas (definition-unfolding ranking,
routes by subgoals, shallow-branch credit) live in `docs/BACKLOG-harness-v7.md`. This file is the fix list.

**Overhaul.** Backlog §5 plans a full overhaul of the candidate graph and the tool UX for v7. It should close
#4, #5, #5a, #9, #10, #17, #18 and #26–#32 by design rather than one patch at a time.

**v6 outcome, for context.** v6cov covered 7 rows, and submission v2 scored about 65.1% (v1: 28.45%). v6ark
fiberwise reached 80.99 and fold_advances 90.51, both within the $0.50 cap, and every v6 fix checked was verified
live. The interleaved and FieldSpecification rows were rerun as v6ark2 after a network outage.

**Sources.** The per-run studies are in `docs/reports/v6pilot/`, `docs/reports/v6cov/` and
`runs/analysis/reports/`. The other sources are `docs/WORKING-harness-v6-decisions.md`, `docs/SPEC-harness-v6.md`,
the RCA and the session log. Every item was checked against the code on `hrushikesh/v6-08-submission` on
2026-10-09.

**Severity.**
- **P1:** wrong numbers, a false stop, or the model is told something false.
- **P2:** wastes money, time or model attention.
- **P3:** polish.

"Decision" marks items that need the owner's choice before work starts.

## P1: correctness

### 1. Failed requests keep their full reservation for good
- **Seen (v6ark).**
  - fiberwise: all-call cost $0.80 against $0.451 actually spent.
  - fold_advances: $1.32 against $0.453.
  - The whole campaign: $3.30 against $0.92.
  - The two runs lost to the outage show about $0.58 each with $0.00–0.015 spent.
- **Cause.**
  - `packages/arena-pi/extensions/arena.ts:659-666` records any attempt that reached the wire hook as `unknown`
    and keeps its whole reservation. `costState()` (`arena.ts:340-361`) never releases it.
  - The reservation is a worst case: the full prompt uncached plus 64K output. At 490K context that is $0.116,
    17–30x the real cost of $0.001–0.018. It ignores the measured cache-read share.
  - A `Connection error.` returned in about 10 ms cannot have been billed. A stream cut partway may have been, up to
    about $0.01.
- **Risk.** Unresolved reservations count against the **$3 hard gate**. About 15 more failed attempts at that
  context size would have forced a false hard stop with almost nothing spent.
- **Fix.**
  - Release attempts that fail with a transport error and no content.
  - Price a cut stream from the characters it delivered.
  - Keep unresolved spend out of the hard-gate check, or cap it.
  - Estimate from the previous request's cache-read share and output, with a margin. Keep the worst case only for
    the first request and the first after a compaction.

### 2. Reports count reservations as spend
- **Where.**
  - `tools/run_campaign.py:172` labels `spent + unresolved` "all-call cost".
  - `arena/summary.py:161,412,518` does the same.
  - The **submission provenance ledger**, `arena/package.py:107-110,241,243,289`, does too, so the submitted
    report would show $0.80 for fiberwise.
- **Fix.** Report `settled_usd` and `unresolved_upper_bound_usd` as separate fields, and compare only settled spend
  with the cap.

### 3. A short network outage ends a run (`error_loop`)
- **Seen.**
  - v6ark: interleaved and FieldSpecification died at 21:42 after 11–12 failed attempts, with $0 and $0.015 spent.
  - v6pilot: Core Luna stopped at 33% of its cap after 3 errors.
  - v6cov a3 stopped with $0.092 unspent after 3 identical guard refusals.
- **Cause.**
  - `arena.ts:22` sets `MAX_ERROR_STREAK = 3`.
  - Every outcome other than `completed` counts toward the streak (`:1250,1255`); the stop is at `:1276`.
  - The backoff is 2 s, 4 s, 8 s, capped at 30 s (`:1294`). An outage of about a minute or less ends the run.
  - Our own deterministic guard refusals count as provider errors.
- **Fix.**
  - Transport errors (no content, no usage) mean "waiting for the provider": back off up to a wall-clock limit of
    about 10 min, then stop with a distinct reason, `provider_unreachable`, that marks the run for rerun.
  - Count guard refusals separately; force a compaction or a fresh session instead of stopping.
  - Log the error text in the control row.
  - Keep `error_loop` for repeated model-side failures.

### 4. The packet contradicts the route rule (v6 regression from `osu`)
- `arena/context.py:637` tells the model that "a draft with `sorry` holes that elaborates is fingerprinted and
  opens a route". Since `osu`, the tool description (`arena.ts:1003`), SKILL.md and `campaign.py:1741` all say
  drafts never open a route.
- The `arena/routes.py` docstring (lines 17-19) is stale too.
- The model gets two contradictory statements in one context. This is live in the v6ark2 packets.
- **Fix.**
  - Delete the clause and update the docstring.
  - Re-certify the packets.
  - Add a test that the packet text and the tool description agree.

### 5. Routes are filed after the run ends, so no route is ever credited live
- **Seen (both v6ark Binius runs).**
  - All 45 route events in fiberwise were filed 3–16 min after the run ended, and after `summary.json` was written.
  - The original proof was never filed.
  - Kernel extraction failed, so every event fell back to a text fingerprint, which can never credit a route.
  - The result is 0 credited routes; "routes tried" is an artefact of timing.
- **Cause.** Partly unknown. `arena/campaign.py:893` swallows the extraction failure reason. The delay probably comes
  from the route worker waiting for memory, but nothing logs that.
- **Fix.**
  - Record the extraction error in the route event.
  - Find out why Binius kernel extraction fails.
  - Make the summary wait for the route queue, or flag it as pending.
  - File the original proof at start.

### 5a. The candidate graph records the wrong parent for batch drafts
- **Seen.** In a sibling set, the last-numbered sibling is always shown as the one expanded, however it scored.
  - v6cov-rerun time_deriv: #4 (73.42) and #5 (72.87) differ in one line. The graph says #6 came from #5, but #6
    through #11 keep #4's `x - _`.
  - v6pilot Core DeepSeek: the graph shows #11 (84.0) expanded, but the text of #12–#14 comes from #8 (84.91).
- **Scale.** The label disagrees with the closest sibling by text in:
  - 35/50 (variational DeepSeek);
  - 21/30 (a3);
  - 19/24 (Core DeepSeek);
  - 14/19 (Core Qwen);
  - 3/3 (CSLib Qwen).
  - Script: `sibs.py` in that session's scratchpad.
- **Cause.** Each compiled draft in a batch appends a `current` event (`arena/campaign.py:1557-1559`), so the last
  draft becomes current. An unnamed parent defaults to current (`campaign.py:1713`, `1773`).
- **Effects.**
  - Graph analysis (depth, which node was expanded, backlog §4b) and parent-based credit rest on wrong labels.
  - The materialized candidate file that `lean_goal` reads is the batch's last draft, not its best.
- **Fix.**
  - After a batch, make the best-scoring compiled draft current.
  - When no parent is named, record the closest existing candidate by text as the parent (the backlog's "measured
    parent"), and keep the label only as a hint.

- **v6ark2 FieldSpecification.** The original was filed at 2.8 min, so filing works when the worker is not stalled.
  16 of 34 route events still landed after the run ended, after a stall of about 12 min that began after #18. The
  finish refusals showed "r3 · 1 attempt" when 11 and then 15 attempts had been assigned. The suspected cause is
  the memory wait at `arena/campaign.py:965,1002-1014`, which nothing logs.

### 6. Test isolation: one test reads the live machine
- `tests.test_lean_session.SessionLogTests.test_a_worker_open_and_a_memory_refusal_are_logged_and_marked` fails
  whenever real Lean sessions run, because it reads the machine's real fair share.
- **Fix.** Inject the fair-share and memory readings.

### 7. The summary may label a single-version pass "best verified" (unconfirmed)
- `arena/summary.py:297-302` takes `best_verified_candidate` from `mode == "full"` evaluations;
  `summary.py:384-388` overwrites it from `submission_result`.
- This was noted on 2026-10-09 and never fixed. The trigger is not yet reproduced.
- **Fix.** Derive "verified" from the all-version check. Add a test for a one-version row. Reproduce it before
  fixing.

## P2: cost, time and model attention

### 8. Finish gate wording (Decision)
- **Seen (fold_advances).** From turn 50, 33 turns of reasoning say the run must "spend down to ~$0.45" before it
  can finish. Eight of them call extra probes "gaming the budget". The last $0.19 added 1.4 points.
- **Context.** The ≤10% rule is intended (unspent allowance has no value), and it paid off in SKI (+6.4).
- **Related.** Compaction spend counts toward the 10% test. In Fsub, a compaction moved the remaining allowance from
  22.9% to 8.3% and so opened the gate.
- **Options.**
  - A: keep the rule, state it as a stop condition, and add neutral facts (routes and candidates per route, points
    left per axis).
  - B: leave it as is.
- **Rule.** Facts only, and never name a kind of proof.

### 9. A failing draft returns only its first error
- **Seen.**
  - FieldSpecification (v6cov): $0.324 spent after the best with 0 compiled. 14 of 20 post-best probes returned
    1–2 errors, and the model fixed one per turn.
  - time_deriv: 14 of 33 failed probes stopped at the first failing rewrite.
- **Fix.** After a failing compile, replace the erroring tactic with `sorry` and run again, up to 3–4 passes at
  about 1–2 s of Lean each. Return all errors with proof lines and the goal at each. Facts only.
- **Related.** An `arena_probe` splice mode (`base:"#N"` plus a line range) so that edits to one region reuse the
  compiled prefix.

### 10. Probe results are never trimmed or deduplicated
- **Seen.**
  - a4: probe results were 78% of all tool-result bytes.
  - b2: 28 multi-KB `grind failed` dumps (210K characters) were carried to the end of the run.
- **Cause.** `trim.ts` stubs only read tools. `_model_view` (`campaign.py:1419`) passes goals and diagnostics through
  whole.
- **Fix.** A goal identical to one already shown says "same goal as pN". Cut repeated diagnostic blocks to the first
  line and a count; the full text stays in `diagnostics/`.

### 11. Replayed reasoning is about two thirds of the context
- **Seen.**
  - b2: the final 562K context held 1.0M characters of reasoning against 334K of tool results.
  - SKI: about 400K of the 504K peak was reasoning.
  - Cache reads were 20–25% of spend.
- **Cause.** Earlier turns' reasoning is replayed every turn (`arena.ts:134-136`).
- **Fix.** Check (free) whether DeepSeek needs earlier turns' reasoning across tool-call turns. If not, replay only
  the latest turn's reasoning.

### 12. A refused `arena_finish` blocks on cold verification
- fiberwise: 3 refused calls waited 871 s in total, up to 439 s each. v6cov a3 waited 409 s once.
- **Fix.** Return the refusal at once, and move cold verification out of `arena_finish`.

### 13. Lean warm-up is dead time on large libraries
- ArkLib waited 6.7 min (404 s) for the health gate before the first model request. It has 4 toolchains, header
  opens of 19–89 s, and v4.28 workers of about 6 GB each.
- **Fix.** Start the model once the primary version is ready, and warm the others in the background.

### 14. Hung streams have no idle timeout
- fiberwise: one stream hung for 113 s and cost 151 s before it was cut.
- **Fix.** Add an idle timeout on time to first byte and between chunks, then retry.

### 15. Lean timeouts on a draft return nothing, and the next probe is slow
- fold_advances: two 180 s timeouts cost 6 min with no information.
- After a timeout, the probe p95 is 19 s because Lean's cancellation is cooperative (RCA-v6cov).
- **Fix.**
  - Return the last elaborated position or the partial messages.
  - Run the next draft in a fresh worker, or cancel hard.

### 16. The packet sheds library lines before local-variable lines
- fiberwise: 39,951 of 40,000 characters. The whole library section was shed and 47 local-variable lines kept.
- **Fix.** Change the shed order in `arena/context.py:605-610`.

### 17. Cross-version results reach the model one turn late
- v6cov SKI: the check finished 1.1 s after the fast evaluation, but the result arrived about 80 s later. Three
  candidates ($0.033) were built on a name that fails on v4.30.0.

### 18. Name search misses Lean core and generated declarations
- **Core names.** `arena_find` returned `not_found, files_scanned: 0` for four `Nat.*` names, and
  `arena_declarations` returned null for 7 of 8 (fiberwise).
  - Cause: `_candidate_files` (`campaign.py:423-448`) scans only the project and its dependencies. `STDLIB_ALIAS`
    (`:470`) is used only by `arena_source`.
- **Generated declarations.** `fun_deriv_sub` is not found.
- **Fix.** Index the toolchain's core sources, and return a handle that `arena_source` accepts. At minimum, return a
  typed `core_not_indexed` reason.

### 19. Runs do not record which code they ran on
- `run-config.json` holds the theorem, model, cap, packet hash, thinking, compaction settings and skill hash
  (`run_pi_budgeted.py:310-316`). It has no harness commit, dirty flag, `models.yaml` hash or Pi version.
- Commits `lrx` and `vqm` landed mid-campaign in v6cov, and the per-run code version had to be rebuilt from file
  times (v6pilot and v6cov).
- **Fix.**
  - Write `code: {commit, dirty, models_yaml_sha, pi_version}` into the run config and the summary header.
  - Warn in the campaign report when runs in one campaign differ.

### 20. `run_campaign --dry-run` skips the real gates
- `tools/run_campaign.py:482` returns before the run-ID clash check (`:484`) and before packet certification
  (`:489`). A dry run can pass a plan that the real launch then refuses.
- **Fix.** Run the clash check and a packet-cache lookup in dry runs, or add a `--check` that runs the full gate with
  no model call.

### 21. Swap and disk pressure are not monitored
- Only `MemAvailable` is read (`lean_session.py:628`, `run_campaign.py:363-399`).
- Swap filled to 8/8 GB during v6ark, and `/` is 94% full.
- "No builds during a campaign" is a convention, not a check.
- **Fix.**
  - Record swap, si/so and free disk in `lean-health.json` and the campaign log.
  - Hold new runs above a swap or disk threshold.
  - Make `provision_workspace.py` refuse to run while a campaign is live.

### 22. Langfuse trace IDs in the package need an environment flag
- `arena/package.py:114-125` looks trace IDs up live only under `ARENA_LIVE_LANGFUSE=1`. Without it, a package can
  list no trace IDs.
- **Related.** Nothing checks the per-run ledger against Langfuse outside preflight, although v6pilot lost 10–79
  generations per run.
- **Fix.**
  - Look trace IDs up by default.
  - Fail loudly when a run has 0 trace IDs.
  - Flag a ledger/Langfuse count mismatch in `summary.txt`.

### 23. Cache-miss alarm misses full misses
- v6cov: Fsub request 29 ($0.056) and b2's last request ($0.085) both had a near-identical prefix.
- **Fix.** Also alarm on `cacheRead == 0` after a cached request. `cacheAlarm` checks only `write > read`.

### 24. Cold-verification failures carry no cause
- fiberwise #43 failed cold on v4.28.0 with no diagnostics, while #42, #44 and #46, which have the same structure,
  passed.
- **Fix.** Record the exit code or timeout in `cold_verification`.

### 25. Official report template (owner action)
- The LaTeX template is not in the repo. `arena/package.py:386-388` falls back to `DEFAULT_TEMPLATE`.
- `submission.jsonl` is unaffected; only the written report needs the template, before the Nov 1 code upload.
- **Fix.** Obtain the template, pass it as `template=` and test the placeholders.

### 25a. `lean_multi_attempt` is invisible to scoring and the summary
- **v6ark2 FieldSpecification.** 18 calls came before the first score. They cost $0.089, 20% of spend, and returned
  187K characters, all untrimmed.
- None of it shows in the summary, the candidate graph or the bookkeeping share.
- **Fix.** Count MCP Lean calls in the summary, and trim their results. Overhaul §5b folds this into `compile`.

### 25b. A probe call waits for its slowest draft
- v6ark2 interleaved: two 180 s timeouts held back drafts in the same call that had already compiled (t30, t64).
  Four 180 s timeouts took 12 min in all, two of them before the first compile.
- **Fix.** Return each draft's result as soon as it finishes, or cap a timed-out draft early when the others are
  done. Overhaul §5b.

### 25c. Route split decided by a hard threshold
- v6ark2 interleaved: #3 and #4 are one line apart (text similarity 0.994). Their kernel similarity was 0.514
  against #1 for one and 0.495 for the other, either side of `SAME_ROUTE = 0.5` (`arena/routes.py:34`). So r2 is a
  "credited" route holding 75 of 77 attempts.
- **Fix.** Use hysteresis, or require a margin. Backlog §2 (routes by subgoals) supersedes this.

### 25d. Worker eviction delays cross-version results
- v6ark2 interleaved: warm-up evicted the v4.31 workers, and idle-closing v4.30 and v4.29 delayed the first
  cross-version result by about 129 s. This is probable, not proven. Related to #13 and #17.

## P3: messages, tools and polish

26. **Wrong continuation text after a failed request.** After the outage, fold_advances was told "The turn ended
    with text and no tool call", but the turn was a failed request with empty content. Give failed requests their
    own factual text.
27. **Malformed or empty tool arguments give misleading errors.**
    - Invalid JSON becomes `{}`, which passes `requireToolArguments` (`toolnames.ts:85-87`, null only) and surfaces
      as "A new idea needs a title".
    - A null-argument call makes the model re-emit its drafts (SKI: 1.8K tokens, `toolnames.ts:82`).
    - Fix: reject objects with no recognised keys as "arrived empty or malformed". Re-request the turn once on null
      arguments.
28. **Lookup errors are not actionable.**
    - `arena_source`: the model invented `compoly:` and the error did not list the valid handle forms. A miss in the
      pinned project (`campaign.py:752`) gives no pointer to `arena_declarations`.
    - `arena_declarations` rejects a whole batch for one invalid name without naming it (`campaign.py:705,797`).
    - Fix: return per-item errors and continue with the rest.
29. **Unicode look-alikes.** fold_advances used `ℱq` (U+2131) for `𝔽q` (U+1D53D) and got `Unknown identifier`.
    Add the fact "identifier `𝔽q` appears in the statement" when an unknown name's confusable form matches one.
30. **Goal output gaps.**
    - Goals are cut at 1500 characters.
    - `lean_goal` out-of-range errors do not give the candidate's line span.
    - An empty goal list from a `sorry` that was never reached, because of an earlier error, has no reason
      (`engine.py:337`). Say "hole at line N not reached (error at line M)".
31. **Lean MCP quirks are undocumented** in `references/lean-lsp-server.md`.
    - `lean_goal` returns "complete" with no goals on an erroring file, and null goals at the last tactic line.
    - `lean_multi_attempt` at some lines shows the original goal.
    - `lean_local_search` reports `"index":"error"` (not marked as an error) or `"warming"` (results incomplete), and
      its default limit of 10 missed key results.
32. **Ideas.**
    - An unknown `idea_id` is silently kept as a label (`campaign.py:1515-1516`); time_deriv's i2–i7 were never
      created.
    - Idea credit is per call, not per draft.
    - Replies use `iN` and `rN` without saying which is an idea and which a route.
33. **Goal-state signatures keep numerals** (`arena/goalstate.py:19`). a4's drafts differing only in `hB 20` …
    `hB 1003` counted as new goal states (79% share). Normalise literals here and in the claim hash in
    `arena/lean/route.lean`.
34. **Compaction residuals.** These matter mainly for Luna (200K) and Qwen (300K) now that DeepSeek is at 850K.
    - The summary request is cache-cold: 0 of 404K tokens cached, $0.061 against about $0.003 shared.
    - An empty history-summary request is paid for.
    - Repeated failures leave no ledger event, alarm or summary line (b2 had 23 in a row).
    - The compaction-memory text item carries over from WORKING.
35. **Truncated turns lose their reasoning.** a3 re-derived it after a cut.
36. **Long `finish` refusals.** The refusal grows with the route count (about 10K characters in a4). Cap it; see
    backlog §4c.
37. **Byte bound.** `boundedPayload` assumes one token per byte. Use the measured ratio of about 2.9.
38. **Qwen output limit.** `request_output_tokens` is 16000, and Qwen reached 15.0K three times. Raise it to about
    24K.
39. **Cap naming.** The CLI flag is still `--hard-cap-usd` for the soft cap (`run_pi_budgeted.py:216`).
40. **Campaign tooling.**
    - `tools/arena_certify.py` prints nothing until the end and keeps results only in memory. It catches only
      `ValueError` and `FileNotFoundError` per row, so one Lean timeout loses all rows. Print and write per row,
      and catch per row.
    - `campaign.json` does not record `--jobs`, overlapping runs or min memory and max load (SPEC story 74, never
      built).
    - `runs/analysis/v6cov/rerun-em.sh` claims to wait for the campaign PID but does not, and it truncates a shared
      log. Campaign scripts should take a lock so that two campaigns cannot overlap.
41. **SPEC-harness-v6.md is stale.** It describes the old finish confirm, not the ≤10% rule. It does not cover route
    fingerprints and credit, the compaction bypass and per-model thresholds, `models.yaml`, or the Lean health gate
    and breaker. Update it, or mark its sections superseded.

42. **The trace journal stores MCP results without the budget footer the model saw.** Not reproduced in v6ark2 interleaved (93/93 in the journal). 78 of 96 results lack it in
    the journal, while events.jsonl has it on 96/96. The cause is inferred from code.
43. **`arena_evaluate` with a candidate id and a proof body gives a misleading `STATEMENT_MODIFIED` error**
    (`rules.ts:22`).
44. **Refusal rounding.** The refusal shows 10.7% as "11%", but the gate uses the unrounded fraction
    (`arena.ts:1131`). Print one decimal.
45. **Duplicate drafts in one batch** (p13 and p14) are compiled twice. Deduplicate by text before compiling.

46. **Summary clocks.** `summary.py:398-403` mixes settle and reserve clocks, so it reports "$0.0067 over 1
    requests" for 2 settled requests.
47. **Ideas unused.** In v6ark2 interleaved the one idea was created inline and never updated, with zero
    `arena_idea` calls. The overhaul (§5a) makes ideas annotations.
48. **Compaction at 850K cannot be observed at a $0.50 cap.** Context peaked at 606–666K in all four v6ark runs.
    Test it with a synthetic long session or a higher-cap run.

## Pending actions (not code)

- Remove the empty branch `hrushikesh/v6-08b-campaign`.
- Merge v6 into main after v6ark2 succeeds, on the owner's go.
- Undecided since WORKING "Ideas under discussion" 8: tool profiles (SPEC story 72) and `lean_code_actions`.

## Verified fixed in v6 (do not reopen)

- **Unicode declaration names:** v6ark2 FieldSpecification had 0 "Invalid declaration name" errors, against 5 in
  v6cov.
- **Budget footer:** present on 85/85 and 92/92 tool results; the model quotes it.
- **Facts-only finish refusals:** the gate refused at 10.7% left and accepted at 9.4%.
- **`compiled:false` and `heartbeat_to_failure`:** present on 28/30 and 38/47 failed drafts. The rest are `sorry`
  skeletons or timeouts.
- **Routes from compiled proofs only:** 12 `sorry` probes opened no route (but see #4 for the packet text).
- **Compaction bypassing the guard (`lrx`):** worked in all 4 new-code v6cov runs.
- **`models.yaml` compaction cost comment:** updated to $0.055–0.075.
- **`| case => sorry` goals:** fixed.
- **From the RCA:** the Lean health gate, circuit breaker, header-first warm open, background lane, Lean latency
  in the summary, and event timestamps.
- **From v6pilot:** compaction null-argument repair, null-argument retry text, tool-argument aliases, the
  text-exemplar absorption cap, unified stop labels, and `lean-session.log`.
- **Operations:** the Brave crashpad loop on ntfs3 was fixed by relinking the crash directories to ext4 (verified
  0 errors).
- **Still to be seen live:** compaction at 850K. It did not trigger in v6ark (peaks of 606K and 633K).
