# Harness v8 plan

Started 2026-10-16, after v7 landed on main (`428cb6c`, tag `v7`). This doc lists what to build and test next, with pointers. v7 history stays in `docs/PLAN-harness-v7.md` (§12j, §12k cover the v8a campaign).

**Current direction, 2026-10-18:** this is still **v8**, extending the existing v8 branches after the completed v7 harness. [Section 6](#6-current-v8-design-sol-orchestrator-and-parallel-deepseek-search-2026-10-18) records the current decisions, research, implementation gaps, and remaining questions. It takes precedence over conflicting proposals below. Historical results remain dated snapshots, not current leaderboard or runtime claims. Updating this plan does not authorize a paid campaign or implement the proposed runtime.

The agreed behavior is synthesized in the [v8 specification](SPEC-harness-v8.md), marked `ready-for-agent` after confirmation of the existing test seams with fast-feedback budgets. The plan retains research, historical evidence, and decision rationale.

## 0. Where we stand

- **Latest (v8c submission, 2026-10-16 evening): official 89.35%, up one rank** (local projection 89.29). Built from `runs/pi-budget/v8c-campaign/submission-final/`.
  - Gap to the leader (91.28) is 1.93 on the mean, about 29 row-points; one axis point on one row is worth 1/45 of a mean point.
  - Weakest axes:
    - *heartbeats:* subst 60.17, SKI 65.08, extract 75.85;
    - *length:* SKI 65.85, Core 67.86, CCS 70.52, EM 72.67, Wick 73.13, extract 74.32.
  - Zero-shot is full on every row.
- **What counts from Nov 1:** the full 50-problem benchmark. Submissions are reproduced by the organizers.
  - The closed-track cap is the *maximum* per-problem API spend of **$3**, priced at list prices and counting every call, retries and discarded candidates included. Exceeding it is a desk reject.
  - The proofs must come from the submitted harness, and the tech report must account for spend per problem.
  - The current leaderboard, including the leader's 91.28, is on **these same 15 rows**, so our 89.35 compares directly. How the leaders built their entries is unknown.
  - **Next (user decision, 2026-10-16, extended 2026-10-18):** from-scratch v8 runs, no `--seed-proofs`. Sol now directs parallel DeepSeek searches under one actual-cost bucket; see §6. Historical best-of-submission comparisons remain development analysis, separate from a reproduced from-scratch pass.
  - Cumulative spend on the 15 dev rows is already above $3 on 7 rows (SKI $7.87, EM $6.02, Wick $5.55, Core $5.38, Fsub $3.85, fold $3.36, variational $3.30). This is fine for practice, but the full-benchmark pipeline must be a single budgeted pass.
- Previous: official closed track **88.45%, rank 7** (2026-10-16 morning). Leaders: 91.28 (emergence-mini), 91.15 (RMA, Claude Sonnet 5), 89.77.
- Our biggest gap is **heartbeats**: heartbeat reduction 83.73% vs about 89–90% for the top two. Length reduction is 81.63% vs 84.58%.
- Final submission: `runs/pi-budget/v8a-campaign/submission-final/` (MANIFEST.md lists the source per row). Built by `runs/analysis/hybrid-push/build_final.py`.
- v8a campaign: 15 rows, Sol at $1.5 per row, DeepSeek fallback at $0.5, about $16.3 spent. Mean 87.64 from runs alone; 88.39 local after the claude-push proofs and the minion golf pass.

### Official per-row weak spots (2026-10-16 submission)

| Row | Score | Length red. | HB red. | Work on |
|---|---|---|---|---|
| Cslib.SKI.parallelReduction_diamond | 76.59 | 67.1 | 62.7 | both |
| CallElimCorrect.substOldPostSubset | 83.74 | 91.1 | 60.2 | heartbeats |
| CallElimCorrect.extractedOldExprInVars | 83.39 | 74.3 | 75.9 | both |
| Electromagnetism…isExtrema | 83.17 | 68.7 | 80.9 | length |
| FieldSpecification…eq_time | 84.11 | 72.5 | 79.9 | both |
| Cslib.CCS.bisimilarity_congr_choice | 86.77 | 66.9 | 93.4 | length |
| Core.InitsUpdatesComm | 87.30 | 67.0 | 94.9 | length |
| interleaved_affine_gaps_imply_tensor_gaps | 87.22 | 87.8 | 73.9 | heartbeats |
| Binius…fiberwise_dist_lt… | 87.58 | 85.1 | 77.6 | heartbeats |

Rows above 90 (fold 94.0, Fsub 91.1, variational 90.6, Putnams 95.7–99.1) are low priority. Closing the gap to #1 needs about 42 score points over 15 rows.

## 1. Learnings from v7–v8a

1. Sol beats DeepSeek per row (SKI 76.6 vs 71.3; Fsub +17) but spends its 5h window after about 6 rows at $1.4 each. The fallback swap and `usage_limit` requeue worked.
2. Seeded fallback runs (`--seed-run`) went past Sol's best on both rows, then plateaued: FieldSpec made no gain from turn 30 to 92, CallElim none from turn 67 to 88.
3. The cheapest gains came after the runs, with Lean only and no model calls: about +0.75 on the mean.
   - **Proofs outside run dirs:** fiber +6.0 and inter +2.0 were sitting in `runs/analysis/claude-push/`.
   - **Greedy deletion:** removing one list item, line or `;` segment at a time gave Fsub +1.3, b2 and a3 +0.05 each.
   - **simp-list ablation:** fold +0.3, Field +0.07, EM +0.09.
   - **Small rewrites:** `rintro -`, and `simp only [..]` before `grind`. Together they gave subst +0.86 and extract +0.45.
4. Step-swap recombine (`arena/submit/recombine.py`) added nothing on these rows: the top proofs are near-copies.
5. Judge every edit by the full proxy. Several token cuts raised heartbeats and lost score; `simp` in place of `simp only` costs 400–1600 hb.
6. Bugs fixed in v8a:
   - CCS index name capture (`Act.name` vs the index script's `name` binder);
   - unseeded fallback runs;
   - the 0.1 MIN_GAIN gate dropping real gains;
   - the "-N never launched" count.

## 2. Original build list (2026-10-16; superseded where noted)

This list preserves the original rationale. Current ownership, spend, continuation, and evaluation policy is in §6. Automatic post-agent golf is disabled, and neither hidden plateau stops nor seeded competition evaluation are current requirements. Per-lemma costs, score feedback, and general search lessons remain useful proposals.

1. **Golf pass after the run, never in the background during it** (user, 2026-10-16: background edits would compete with the agent for Lean and memory).
   - *When:* once, after Pi exits, inside the closing drain, under a time cap and with one Lean check at a time; also usable offline over a submission. Optionally a model-invoked tool that runs one bounded pass through the normal lane scheduler.
   - *What:* tries single deletions (each `[..]` list item, each line, each `;`/`<;>` segment) and small rewrites (`intro h; clear h` → `rintro -`; `dsimp only` → `simp only` before `grind`/`simp_all`).
   - *Rules:* accept by full proxy; the result feeds the submission, not the running model.
   - *Prior art:* `tools/golf/dd.py` (minion script, copied from the session scratchpad), `runs/analysis/hybrid-push/ablate.py`, `mk.py`.
   - *Tool help:* `arena.prices.snippet_tokens` pre-filters token deltas offline.
2. **Per-lemma heartbeat costs.**
   - *2026-10-18 clarification:* this was proposed, not implemented or agreed as a prerequisite. Existing per-step/tactic profiling remains. The motivation was the recorded simp-list ablation gains and token cuts that raised heartbeats. Individual removal tests measure context-dependent deltas, not additive intrinsic lemma costs; "unused" means unnecessary in that exact checked experiment. Agent-requested anchored scratch experiments are a possible implementation. Scope remains to settle with the user.
   - Per-step profiles exist (ledger `profile`/`step_goals`). Add costs for each lemma inside `simp`/`grind`/`rw` lists, and mark lemmas whose removal keeps the goal closed as unused.
   - Show the model "tokens Δ, hb Δ, score Δ" on every check, so it stops trading heartbeats for tokens.
3. **Start from the best known proof.**
   - Campaign and run seeding should take the best cold-verified proof from any source (runs, `runs/analysis/**`, earlier submissions), not only a run dir.
   - Add `--seed-proof <file>`, or extend `--seed-run` to accept a proof file.
   - Pool loose proofs in `arena submission` too, so nothing like the claude-push fiber/inter proofs is missed.
4. **Stall escalation, then a hidden plateau stop.** v8b SKI: last gain at turn 23; turns 24–80 made 33 nodes, all on the best's route r2, 19 compiled candidates and none above the best. The harness sent one `stall` nudge at turn 47 (count 12, mode `best_other_cell`), Sol ignored it, and nothing escalated. Ladder: (1) the current nudge; (2) if ignored for N more tries, an automatic restart from the best node on another route (`_restart_order` exists); (3) compile replies report the route's tally, e.g. "route r2: 30 variants, none above best"; (4) the hidden plateau stop below. Neutral wording; the stop stays hidden.
   - *Built (v8/02):* steps (2) and (3). After a `stall` nudge, `STALL_RESTART_TRIES` (6) more nodes on one route with no new best make the extension call `stall_due`, then `stall_restart_packet` (ledger `restart` row, reason `stall`; best node of another route, else the best node's parent). Compile replies add `{label}: N variants, none above the best.` Plateau stop (4) still open.
   - **Hidden plateau stop.** End a run, harness-side, after N turns or $X with no new best. It must not be visible to the model (D42).
5. **Row-independent playbook in the packet.** The queued L1–L8 lessons (v7 PLAN §12f), plus the claude-push `LOG.md` structural moves, phrased neutrally.
6. **Restart on text-only turns** (deferred from v7). It helped DeepSeek on EM (44 → 78).
7. **recombine.py, smaller items:** rank donors by proxy, not tokens; per-arm/nested swaps keyed by goal; seed rows from loose proofs.

## 2b. Tool surface review (2026-10-16)

v8a tool use over 19 runs: compile 946 calls (1 error), scratch 434 (10), read 357 (9), search 260 (0), goal 109 (0). Scratch is a fifth of all calls and sits entirely outside the graph: its ledger row keeps only `code_sha256`, with no code, result, graph position or link to the node it explored. What Sol learns there (a working sub-proof, a cheaper tactic, a lemma's heartbeat cost) is lost to the graph, to salvage, to recombine, to seeded runs and to the session digest.

### Scratch overhaul (v8/02, after v8/01 lands)

**Status checked 2026-10-18:** the overhaul remains pending, with original-code retention now implemented. `scratch_tool` still accepts only `code`; it now persists that exact code alongside its hash in the scratch ledger event before context construction or Lean execution. Carry the remaining design into §6.5 rather than treating it as completed by the earlier branch label. The later user decisions require scratch-managed promotion without a second agent call and isolated checks with explicit helper dependencies. Those decisions supersede item 3's original "one click" wording.

1. **Anchor to a graph position.** Optional `at: <node>` / `at: <node>.<step>`. The harness builds the snippet's context from that position's recorded goal (`goal_before`), so an experiment is "try this tactic for step s of node n".
2. **Record in the graph.** Store the code, the outcome (OK or FAILED, error lines, body tokens, heartbeats per declaration) and the anchor as a `probe`-style event, shown under the node on the map. Seeded runs and the prior-work digest then carry experiments too.
3. **Promote, don't discard.** An anchored experiment that closes its step's goal and is cheaper than the step becomes a replacement candidate, scored through the normal compile path (one click for the model, no retyping). An unanchored snippet that proves the full target statement is offered as a candidate the same way.
4. **Keep free exploration.** `#check`, `#print` and `example` stay possible without an anchor, but are still recorded (code and outcome), so the next session can see what was already looked up.
5. Model-facing wording stays neutral, as for the rest of the tool text.

### Other tools
- **compile:** keep. Add the score preview from §2 item 2 ("tokens Δ, hb Δ, score Δ" against the parent and the best).
- **read:** keep; look at its 9 errors (Core had 4) for argument-form confusion.
- **goal:** keep, or fold into `read` as a view; 109 calls, no errors.
- **search:** keep. Seeded runs do not carry earlier search and read results (§12k), so a seeded run repeats lookups; carry a compact list of names already read.
- **New, to try:** `cost` (per-lemma heartbeat cost and unused-lemma marks for one node, §2 item 2), and a model-invoked bounded `golf` (one pass on one node through the lane scheduler; §2 item 1). Decide after the Pi + Lean MCP exploratory run (§3 item 1), which shows which tools Sol reaches for unprompted.
- **Readable reasoning from OpenAI models.** *Built (v8/02):* the `before_provider_request` hook sets `reasoning.summary = "detailed"` on Responses payloads (Pi defaults to `auto`, openai-codex-responses.js:424); `compile` already had an optional `note` (stored as the node's hypothesis, shown in the viewer as Note); viewer hides empty thinking blocks. Still to check on a capped Sol run. v8b Sol turns carry no text blocks and only about 35 readable reasoning characters per turn; the rest is encrypted. Find where pi-ai's OpenAI provider builds `reasoning` and request `summary: "detailed"` (Responses API). Check on one short capped Sol run that summaries get longer on the ChatGPT backend. If it works, the summaries feed the seeded-run digest; otherwise add an optional `note` argument to `compile`, stored on the node.
- **Remove:** nothing yet. Re-check each tool's share of calls and of new bests after v8b.

## 2c. Ideas borrowed from OpenProver and autoresearch (2026-10-16)

Sources: [OpenProver](https://github.com/kripner/OpenProver) (README only, code not read; paper arXiv 2607.09217) and karpathy/autoresearch `program.md`.

- **OpenProver:**
  - A planner LLM keeps `WHITEBOARD.md` (a terse scratchpad) and a `repo/` of lemmas, observations and findings linked by `[[wikilinks]]`.
  - It spawns up to `-P` parallel workers. Workers have `lean_verify` (runs `lake env lean`), `lean_store` (a verified snippet prepended to later checks) and `lean_search`.
  - Budget flags: `--max-time` / `--max-tokens`; `--conclude-after 0.99` starts a conclusion phase; `--history-budget` caps the planner's history.
  - State lives on disk (`steps/step_NNN/`, `archive/calls/`), so a run can resume.
- **autoresearch:**
  - A strict hill-climb: edit, then run on a fixed 5-minute budget, then append one row to `results.tsv` (commit, metric, memory, `keep`/`discard`/`crash`, short description), then keep or `git reset` to the best.
  - Simplicity criterion: an equal score with less code is a win.
  - The agent never stops to ask.
  - The human iterates on `program.md`; the code stays fixed.

### Build list, in order

1. **A required one-line description per candidate** (from autoresearch's `results.tsv`).
   - *Current status:* Q13 in §6.10 retains optional notes for new rationale, with no missing-note warning. This original required-note proposal is superseded.
   - *Why:* `compile`'s `note` is optional. In v8c only 22 of 32 (CCS) and 15 of 33 (Wick) candidates carried one. Sol's reasoning is encrypted, and the `"detailed"` summary request made no difference (64 vs 57 readable characters per block), so the note is the only readable record of intent.
   - *Change:* make `note` required in `agent-text/tools/compile.yaml`, wording neutral (what it changes, a few words). A missing note is a tool error with a one-line hint and no lost candidate. Alternatively, accept the candidate and send the hint in the reply; decide by whether the error rate stays below 1%.
   - *Viewer:* add a "Log" tab to `arena serve`, one row per candidate: #, parent, route, tokens, HB, fast estimate, full score, status (best / kept / below best / failed / salvaged), note. It is our `results.tsv`, derived from the ledger, with no new storage.
   - *Seeded runs:* the prior-work digest lists the last N notes per route, so the next model sees what was tried, not only scores.
2. **Campaign playbook** (from autoresearch's `program.md`, already listed in §2).
   - *Change:* `--playbook <file>` on `arena campaign` and `arena run`. A markdown file the operator edits between campaigns, rendered into the first packet under a neutral heading. Per-row overrides go in a `## <row name>` section.
   - *Content:* route-level lessons from earlier runs, e.g. merging `rintro` steps, a cheaper closing tactic for a family of goals, lemmas known to cost many heartbeats. Facts only; no stop or finish wording (hidden stop rule).
   - *Rule:* it lives with the run outputs (copied into the run dir and hashed in `summary.json`), not in `agent-text/`, because it changes per campaign. The neutral-framing rule still applies to its text.
3. **Whiteboard plus observations, tied to the graph** (from OpenProver; this is the §2b scratch overhaul with a concrete shape).
   - *Whiteboard:* one short model-written text (cap about 1,500 characters), replaced on every write and shown in every packet. Its ledger row is `{"kind":"whiteboard","text":...}`, so seeded runs carry it.
   - *Observations:* `observe(at: <node>[.<step>], text)`, or an `observe` field on an anchored scratch probe, stores a short fact on a graph position, e.g. "`omega` closes this goal" or "`simp` here costs about 400 HB". Shown under the node on the map and in packets when that node is in focus.
   - *Difference from OpenProver:* their memory is written by the model only. Ours keeps the harness-computed facts (route tally, lemma costs, step goals) and adds model-written ones next to them, both anchored to nodes, not free-floating.
4. **Default parent is the best node after a stall nudge** (from autoresearch's reset).
   - *2026-10-18 qualification:* a default filing anchor is not exact derivation. It must be actor-local and captured before execution; a worker must not retarget Sol's focus. See §6.6.
   - After a nudge, a `compile` without an explicit parent is built from the best node, not the last candidate. Explicit parents still work, so branching from non-best nodes stays possible. In v8c, CCS and Wick found late bests that way.
   - This is softer than the `STALL_RESTART_TRIES=2` restart, which never fired in v8c (models changed route after each nudge). Keep both.
5. **Parallel workers for the open track** (from OpenProver's `-P`). The closed-track version, Sol with DeepSeek minions, is detailed in the next subsection.
   - *Why:* on 4×A100 the marginal token cost is zero, and the limit is 48 h for 50 rows (about 58 min per row). Four copies of Qwen3.8-27B (55.6 GB BF16 each, one per GPU) or a planner plus three workers fit.
   - *Shape:* the planner (our normal run) gets a `delegate(at: <node>.<step>, goal)` tool. A worker gets one step goal and the step's context, with only `compile` and `search`, and a short budget (turns or seconds). Its candidates enter the same graph with `origin: worker`.
   - Optional: a Lean-trained model as a worker (Goedel-Prover-V2-32B, about 64 GB). It fits next to Qwen (about 120 GB total) and returns whole-step proofs that the harness compiles.
   - *Closed track:* only with a cheap worker model (DeepSeek), and only once the per-row $3 cap accounting covers workers.
6. **Pinned verified helpers** (from OpenProver's `lean_store`, lower priority).
   - A verified `have` or helper lemma can be pinned to a route, and later candidates on that route reuse it by name. Fits poorly for single-theorem refactors; revisit if candidates often retype the same helper.

### Sol planner with DeepSeek minions (closed track; extends item 5)

**Historical proposal, superseded by §6.** Keep this subsection as a record of the earlier design. Its hidden stall-triggered launch, step-only hill climbing, per-job and model-pool dollar limits, best-only publication, seeded comparison, and wall-time acceptance gate are not the current contract. Build explicit Sol delegation first, including whole-proof searches.

**Idea.** Sol is good at ideas but expensive per turn, because every turn re-sends its long context. DeepSeek V4.1 Flash is cheap and reliable at a narrow loop. Sol picks the idea and the anchor; a DeepSeek minion runs an autoresearch-style hill-climb on that anchor and returns a short table. Sol reads about 300 tokens instead of 6 compile replies. In v8b, SKI spent 33 Sol nodes on one route doing this kind of variant search by hand.

**Two search levels.**
- *Inside a minion:* a strict hill-climb (keep the variant if it beats the minion's local best, else revert). This suits golfing one step.
- *Across the graph:* Sol keeps branching from non-best nodes. CCS and Wick found their late v8c bests that way, so the graph level stays as it is.

**Minion contract.**
- *Input:*
  - the anchor `node.step`: that step's `goal_before` / `goal_after`, the step text and the surrounding proof;
  - the idea text (written by Sol or by the harness);
  - the parent proof;
  - `tries`.
- *Hidden from it:* the packet, the graph, other routes, the budget and any stop wording (hidden stop rule).
- *Tools:* `compile` (fast mode, replacing only the anchored step) and `search`. No `read` of other nodes, no scratch, no `delegate`.
- *Loop:* edit, then fast compile, then keep or revert. It stops at `tries` compiles (default 6) or its dollar cap (default $0.03), whichever comes first.
- *Output:* one table row per try (`#`, tokens Δ, HB Δ, status `kept`/`worse`/`failed`, a description of a few words). Its best kept variant, only if it beats the parent, enters the graph as a normal candidate with `origin: "minion"`, parent = the anchor node and `hypothesis` = the idea, then goes through the normal full-check queue. Failed tries are recorded as `probe`-style events under the anchor, so seeded runs and the digest see them.
- *Prompt:* a short system text in `agent-text/minion/` with the same neutral route framing. No model-facing strings in code.

**Lean capacity is the limit, not tokens.**
- Fast checks take about 30–40 s and full checks about 150 s. Free memory fell to 7.8 GB with 2 jobs (Wick, v8c). The fiberwise full-check starvation (fixed in `vkz`) shows what happens when background work crowds out the checks that matter.
- Minion compiles get their own lane, priority below the model's compiles and full checks: model compile, then full check, then minion compile, then salvage, assembly, step goals, profiles.
- At most 1 minion compile in flight per run on this machine (2 with `--jobs 1`), configurable through `ARENA_MINION_LANES`. On the open track's 4×A100 node it can go wider.
- The lane scheduler already checks `lean_health`. Minions pause with the model's work when Lean is unhealthy.

**Budget and accounting.**
- Minion LLM spend goes into the same per-row cost ledger as Sol's. The run limit is checked after every LLM call (budget rule v7), with no estimates or reservations.
- Campaign flags: `--minion-model deepseek-v4.1-flash`, `--minion-pool-usd 0.25`, `--minion-try-usd 0.03`. Once the pool is empty, minions stop and nothing changes for Sol.
- The per-row total across all runs, Sol plus minions plus fallback, must stay under the $3 track limit.

**Step 1: harness-triggered minions (no new Sol tool).**
- *Trigger:* when a stall nudge fires (`ARENA_STALL_M=8`), the harness sends one minion before the nudge text is delivered. Its result table is appended to the nudge reply.
- *Anchor:* the best node's most expensive step by per-lemma / per-step HB cost (§2 item 2; until that exists, the step with the most tokens).
- *Idea:* a fixed neutral text from `agent-text/minion/`, "shorten or cheapen this step, same goal".
- *Why first:* it tests whether minions find gains at all, without changing Sol's behavior, and it reuses the stall machinery from v8/02.
- *Ticket:* `v8/04-minion-on-stall`. Smoke test: one fake session where a stall fires and a fake minion returns one kept variant that lands as an `origin: minion` candidate.

**Step 2: a `delegate` tool for Sol (only if step 1 shows gains).**
- `delegate(at: <node>.<step>, idea: <text>, tries: <1..8>)`. It returns right away with a job id; the table arrives in a later compile reply like the other background updates, so Sol keeps working while the minion runs.
- At most 2 open delegate jobs per run. Further calls are refused with a short reason.
- It needs the graph anchoring from the scratch overhaul (§2b item 1), so build that first.
- *Ticket:* `v8/05-delegate`.

**Test: an A/B run on 3 rows** (SKI, Binius `fiberwise`, Wick), seeded from the current final proofs.
- *Arm A:* Sol $1.0 alone. *Arm B:* Sol $0.75 plus a $0.25 minion pool.
- *Measure:*
  - gain per dollar;
  - share of new bests with `origin: minion`;
  - minion tool-call error rate;
  - Lean wait time for Sol's own compiles (minions must not slow Sol);
  - duplicate tries across minions.
- *Decide:* keep minions if arm B's gain per dollar is at least as good as arm A's and Sol's compile wait does not grow by more than 10%.

**Risks.**
- *DeepSeek tool-call format errors:* small in our fallback runs; count them per minion.
- *Minions repeating each other:* one minion per anchor at a time, and the harness rejects an anchor and idea pair already tried.
- *Minion candidates crowding the full-check queue:* only the minion's single best kept variant becomes a candidate.
- *Sol over-delegating instead of thinking (step 2):* the 2-open-jobs cap and the per-try cost show up in the cost ledger.

### Do not copy

- **A visible conclusion phase** (`--conclude-after`). It breaks the hidden stop rule; v5/v6 models gamed visible stops.
- **An LLM verifier after each worker.** Lean is the verifier.
- **Strict keep-or-reset.** Our graph branches from non-best nodes, and v8c's late gains came from that.

### v8c findings: the background checker (2026-10-16)

Three bugs in the background checker. Together they hid most of v8c's gains from the model for about half of each long run, and kept two finished runs alive.

**1. Full checks starved by salvage (fixed, `vkz`).**
- *What happened:* `autocheck` (`arena/campaign.py`) restarts from the top of `("salvage", "assembly", "full", "step_goals", "profiles")` after every job. Each broken candidate adds a salvage job (70–265 s each, most ending `broken-no-progress`), so the salvage queue never emptied and full checks never ran.
- *Fiberwise:* the last full check was at minute 29 (#18, 91.34). In the next 33 minutes, #22 (167 tok / 2204 HB) and several others had better fast estimates and were never checked. Earlier in the same run, #12 and #13 waited behind three salvage jobs until #14 overtook them.
- *Interleaved:* the last full check was at minute 23 (#17, 89.54). The real best was **92.29** (#35), found only after the checker restarted.
- *Effect:* the model's packet showed a stale best for 20–30 minutes. Sol compared variants against the wrong node, and stall nudges fired on a best that was not stuck.
- *Fix:* `"full"` first in the background order. `_autocheck_jobs` only queues candidates whose estimate can beat the verified best, so salvage still runs once the leaders are checked. The test `test_background_drain_runs_full_checks_before_salvage` was updated.

**2. A hot fix does not reach a running checker (operator note).**
- *What happened:* the Pi extension starts one checker per run (`packages/arena-pi/extensions/arena.ts`, `kickAutocheck`), and it loops for as long as it has work. It keeps the code it loaded at start, so fix 1 did not reach the live runs.
- *Workaround used:* stopped each checker by PID. Its queue lives in the ledger and an interrupted salvage job is requeued, so nothing was lost. The next compile started a fresh checker with the new order, and within 2 minutes both runs logged new bests (fiberwise 91.53, interleaved 92.29).
- *Rule:* after changing `arena/campaign.py` during a campaign, restart the live checkers by PID; the runs themselves can keep going.

**3. A finished run stays alive while its checker runs (fixed in `arena.ts`, committed as `qsx`).**
- *What happened:* both runs ended their agent loop in the final tenth (Sol 97% and 93.5% spent; its last turn was text only). Pi then sat idle for 15–20 minutes with no network connection, because the spawned checker child kept the Node process alive. The checker was still draining salvage for a model that had stopped. `arena run` waits for Pi to exit before its closing drain, golf and cold verification, so the run never finished.
- *Workaround used:* stopped the checkers by PID. Pi exited at once and `arena run` went into `finish()`.
- *Fix:* in the stop branch of the agent-end handler, clear `kickAgain` and `checker?.kill("SIGTERM")`. The closing drain in `arena/cli/run.py` (`autocheck(..., closing=True)`) still full-checks every candidate that could beat the best, so the submission does not change.
  - Do not `unref()` the child instead: an orphaned checker would hold `autocheck.lock`, and the closing drain returns `running_elsewhere` without checking.
  - Extension tests pass (43). The golden session must pass on an idle machine before this is called ready.
- *Why earlier runs did not hang:* before fix 1 the tail was the same, but shorter runs had fewer broken candidates, so the salvage queue emptied within minutes of the stop.

**Still to build.**

*Historical checklist, 2026-10-16.* The subsequent [runtime optimization report](LEAN_RUNTIME_OPTIMIZATION_RESULTS_2026-10-16.md) records implemented phase/job visibility, cooperative salvage yielding, demand-driven growth, and PSS-informed admission. Preserve those changes. Automatic golf is removed; watcher logic must recognize intentional waiting for delegated results rather than flagging every interval without a model call. Remaining multi-agent visibility work is in §6.7.

- *Show the run phase and the checker's work in the log and in serve* (user request, 2026-10-16: "our logs and server should show that"). Today the campaign log prints only `start`, `cleanup` and `done`. Ledger rows for `closing_drain` and `golf` land only when each phase ends, so during the 10-minute golf pass or a 265 s salvage job nothing says what the run is doing.
  - *Phase events:* append `{"kind":"phase","phase":..., "state":"start"|"end", "seconds", ...}` to the ledger. The phases are:
    - `model` (agent loop);
    - `closing_drain` (jobs queued at start, checked at end);
    - `golf` (cap seconds at start; variants tried and accepted, tokens and HB before and after at end);
    - `cold_verify` (proxy and pass/fail per toolchain at end);
    - `summary`.
  - *Checker job events:* a `{"kind":"job","job":"full"|"salvage"|"assembly"|"step_goals"|"profiles","state":"start"|"end","candidate":#n,"seconds"}` pair per background job, plus the queue lengths at each start (full / salvage / assembly).
  - *Campaign log:* one line per phase change and per job longer than 30 s, e.g. `15:31:02 golf    v8c-Binius…: start (cap 600 s)`, `15:41:05 golf    v8c-Binius…: 2 of 37 accepted, 167→161 tok, 2204→2190 HB`, `15:43:40 verify  v8c-Binius…: cold 91.71 on 4/4`. The same lines go to the run's `stderr` log.
  - *serve:* a status strip per run with the current phase, elapsed time and cap; the checker's current job and its age; the queue lengths; and the age of the newest full check versus the newest fast check. Mark the full-check age red at 10 minutes or more while fast checks are still arriving (the same rule as the watcher alarm). In the run list, show the phase next to each run so "golf 7/10 min" is visible without opening the run.
  - *Watcher:* read the phase and job events instead of guessing from stderr.
  - *Smoke test:* one fake run that goes through all phases and checks that the log lines and the serve status JSON contain each phase.
- *Watcher alarm:* raise an alarm when a run's newest full check is more than 10 minutes old while fast checks keep arriving, and when Pi has made no LLM call for 5 minutes while its process is alive. Both bugs were found by the operator reading the viewer.
- *Parallel toolchains:* run the 3 extra toolchains of one full check in parallel when free memory allows (Wick dropped to 7.8 GB with 2 jobs).
- *Salvage limits:* cap the salvage time per run (e.g. 15% of wall time) or skip salvage of a node whose route already has a closed node with a better score. Most v8c salvage jobs ended `broken-no-progress` after 70–265 s.

### v8c results (Sol $1.0, DeepSeek fallback $0.25, seeded from submission-final)

| Row | Baseline | v8c | Gain | Spent |
|---|---|---|---|---|
| CCS `bisimilarity_congr_choice` | 86.76 | 87.21 | +0.45 | $0.92 |
| Wick `ι_timeOrderF_superCommuteF_eq_time` | 84.11 | 84.93 | +0.82 | $0.95 |
| Binius `fiberwise` | 87.01 | 91.53 (before closing) | +4.52 | $0.97 |
| `interleaved_affine_gaps` | 87.15 | 92.29 (before closing) | +5.14 | $0.93 |
| `Core.InitsUpdatesComm` | 87.29 | queued | | |

- Total so far **+10.93 points**, about **+0.73 on the 15-row mean**.
- *Stall nudges (at 8):* fired 1, 3, 0 and 2 times. A new best followed each nudge in CCS and Wick. The forced restart after 2 tries never fired; Sol changed route after every nudge.
- *Notes:* 22 of 32 (CCS) and 15 of 33 (Wick) candidates carried a note.
- *Reasoning summaries:* the `"detailed"` request made no visible difference: 64 readable characters per block, vs 57 in v8a. The ChatGPT backend appears to ignore it.
- *Golf pass:* accepted 1 edit on Wick and none on CCS.
- *Why the long rows gained most:* fiberwise went from 1,463 reference tokens to about 167. Heartbeats fell with tokens (2904 → about 2200 HB), because elaboration cost scales with the tactic steps.
- Fixes 1 and 3 changed a live campaign. Compare v8c with v8b with that in mind.

## 3. Test next

**Historical proposals.** The current sequence is §6.9: offline lifecycle evaluation first, then matched from-scratch comparisons. The seeded fallback campaign and automatic post-run golf below are superseded. The optional Pi plus Lean MCP exploration remains a separate research proposal, not a prerequisite for delegation.

1. **Pi + Lean MCP exploratory run with Sol.**
   - *Setup:* Pi with `lean-lsp-mcp` tools (goal state, hover, search, diagnostics) and its built-ins, without our harness tools.
   - *Row and cap:* SKI at a **$1.5** cap. Check Codex limits first with `python -m arena.codex_limits`.
   - *Prerequisite:* find or write an MCP adapter extension for Pi; Pi has no built-in MCP client as far as we know.
   - *Isolation (from scratch):* Pi runs in a sandbox (bubblewrap) whose only writable dir is a fresh temp copy of the row's Lake project with the theorem file reset to the reference proof (`engine.candidate_file`). The toolchain and `.lake` build outputs are mounted read-only. `runs/`, `runs/analysis/`, the repo, `~/.pi` sessions and other workspaces are not mounted, so no earlier proof is reachable. Pi gets no context files or skills (`--no-context-files --no-skills`), the network is limited to the model provider, and there is no web search.
   - *Lean verification:* inside the sandbox, `lean-lsp-mcp` (diagnostics, goals) and `lake env lean <file>` against that project copy; `count_heartbeats in` gives heartbeats natively. Optionally a small read-only score command (our `engine.evaluate` fast mode) exposed as a tool, so the agent optimizes the real proxy. The official answer comes after the run: the harness cold-checks the final file outside the sandbox on every toolchain.
   - *What to learn:* which tools Sol reaches for, how it searches and how it golfs. Turn the useful patterns into harness tickets.
2. **Next campaign on the weak rows** listed in §0: SKI, subst, extract, EM, Field, CCS, Core, inter, fiber.
   - Sol at $1.5 per row with the DeepSeek $0.5 fallback, seeded from the final proofs (needs item 2.3).
   - Per-row spend across all runs must stay under $3.
   - Sol's 5h window reset at 11:51 on 2026-10-16.
3. Run the golf pass (2.1) offline over the current final proofs first, to measure what it adds before wiring it into runs.

## 4. Where to look for more

- Per-step heartbeat profiles of the final proofs, rows with the lowest HB reduction first: subst, SKI, inter, extract, fiber.
- Viewer data: turns spent on search/read vs edits; tool error kinds (Core had 4 `read` and 3 `scratch` errors).
- Official vs local deltas: fiber was +0.57 higher officially; the others within 0.2.

### Open-source track (2026-10-16)

**Rules.** Open weights only. Inference on at most 4× 80 GB A100, and the full 50-row benchmark within 48 h (about 58 min per row). Deliverables: the JSONL, the inference code, and a short tech report on OpenReview. Full benchmark released November 1, deadline November 8.

**Leaderboard.** Fetch it with `gradio_api/call/_leaderboard_open_html`, the same two-step call as the closed board.
- Leader 79.1% (addarshh-refactor-open), then LARA-EPFL 78.2% and Vexorium 69.1% (self-hosted on 4×A100).
- RMA is 8th at 55.9% with Qwen3.8-27B-FP8 plus DeepSeek-V4-Flash on vLLM.
- Our closed score is 88.45%, so the harness has headroom here if it carries over to a weaker model.

**Models that fit at full precision** (320 GB; sizes from secondary sources, verify on the model cards):

| Model | Weights | Fits? | Notes |
|---|---|---|---|
| Qwen3.8-27B (dense, 262K context, Apache 2.0) | 55.6 GB BF16 | yes | First choice. Not on OpenCode Go. On OpenRouter as `qwen/qwen3.8-27b`, with a free variant that may have ended; NRP API for researchers. |
| Gemma 4 31B (256K context, native function calling) | about 62 GB BF16 | yes | Free endpoints on NVIDIA NIM, SiliconFlow and an OpenRouter free variant. SWE-bench Verified reportedly only 31%. |
| Goedel-Prover-V2-32B (Lean-trained, Qwen-based) | about 64 GB | yes | Writes whole proofs and has no tool calling. Use it as a worker behind the planner. |
| StepFun-Prover Preview 32B | about 64 GB | yes | Trained with Lean REPL feedback, 20K context, its own format. |
| GLM-5.3-Flash / Qwen3.8-Flash(-Next) / MiMo-V2.6-Flash / MiniMax M3 | 309–428B | no | Weights exceed 320 GB at native precision. |
| DeepSeek V4.1 Flash | very large MoE | no | Loads on 4×A100 but only with a 4K context (HF discussion 43). |

None of the OpenCode Go models fit comfortably at full precision. Go is still a cheap way to probe whether a larger open model beats the 27B.

**Plan.**
1. Add `qwen/qwen3.8-27b` (OpenRouter) and `gemma-4-31b-it` to Pi's `models.json` as OpenAI-compatible providers. Run 1 row each (SKI) at $0.25, cold start (no `--seed-proofs`).
2. Compare scores and count tool-call format errors in `tool-errors.log`.
3. If the winner reaches about 80 or more on a row, rent one A100 for an afternoon and serve the real BF16 weights with vLLM for comparable numbers. Then try the planner plus workers shape (§2c item 5): Qwen at about 55 GB plus Goedel at about 64 GB fit together.

### Reading list for harness ideas (mostly outside Lean)

- **Evolutionary search with an evaluator:**
  - [AlphaEvolve](https://arxiv.org/abs/2506.13131) (program database and sampling policy);
  - [FunSearch](https://www.nature.com/articles/s41586-023-06924-6) (islands with periodic reset, best-shot prompting);
  - [OpenEvolve](https://github.com/codelion/openevolve) (open code);
  - [ShinkaEvolve](https://arxiv.org/abs/2509.19349) (rejects near-duplicates before evaluation, which matters because Lean checks are our bottleneck);
  - [MAP-Elites](https://arxiv.org/abs/1504.04909) (best per tokens × HB cell; we already log `best_other_cell`);
  - [OPRO](https://arxiv.org/abs/2309.03409) (scored past solutions, sorted, in the prompt).
- **Superoptimization** (golfing a proof is one):
  - [STOKE](https://theory.stanford.edu/~aiken/publications/papers/asplos13.pdf) (MCMC with a cost function that tolerates incorrect intermediates; a model for a smarter golf pass);
  - [egg / equality saturation](https://arxiv.org/abs/2004.03082) (explore equivalent rewrites, extract the cheapest);
  - [delta debugging](https://www.st.cs.uni-saarland.de/papers/tse2002/) (the theory behind `tools/golf/dd.py`; finer-grained variants could cut inside `simp` lemma lists).
- **Agent memory and loop:**
  - [Reflexion](https://arxiv.org/abs/2303.11366) (written reflections; our required notes and whiteboard);
  - [Voyager](https://arxiv.org/abs/2305.16291) (skill library; playbook and pinned helpers);
  - [LATS](https://arxiv.org/abs/2310.04406) (tree search over agent actions);
  - [SWE-agent](https://arxiv.org/abs/2405.15793) (tool interface design);
  - [STOP](https://arxiv.org/abs/2310.02304) (an LLM improves its own scaffold);
  - [The AI Scientist](https://arxiv.org/abs/2408.06292) (experiment logging and review).
- **Lean, on our task:**
  - [ImProver](https://arxiv.org/abs/2410.04753) (an agent that rewrites Lean proofs to optimize a chosen metric; the closest prior work);
  - [LeanDojo](https://arxiv.org/abs/2306.15626) and [Lean Copilot](https://arxiv.org/abs/2404.12534).
- **Read first:** ShinkaEvolve (fewer checks), STOKE (golf pass), ImProver (direct prior work).
- Citations are from memory except the OpenProver and autoresearch pages. Check them before quoting.

## 5. Process notes

- Claude weekly quota was at 93% on 2026-10-16 and resets 2026-10-23. Use Haiku minions for mechanical work and Sonnet only for code.
- An index-script change renames every cached index (the digest covers `arena/lean/index.lean`). Copy semantically identical indexes to their new names instead of rebuilding.
- An operator SIGTERM stop still drains checks and cold-verifies the best, so plateaued runs can be stopped safely.

## 6. Current v8 design: Sol orchestrator and parallel DeepSeek search (2026-10-18)

This section extends v8. It replaces the tentative name "v9" used early in the planning conversation. The v7 harness is complete; existing v8 work and local runtime improvements remain the base. The decision table records user agreements. Proposed schemas and implementation choices below remain recommendations until verified or explicitly settled.

### 6.1 Agreed policies

| Area | Current decision |
|---|---|
| Objective | Optimize cold-verified proof score per dollar. Per the user's organizer clarification, the closed track has a $3 per-problem spend constraint and no time limit. Wall time is secondary; no search deadline or mandatory latency percentage is an acceptance gate. |
| Spend | Sol and all DeepSeek workers use one shared **$2.50 actual-cost bucket**, retaining $0.50 competition headroom. Add actual reported call costs and stop model activity when the total is `>= $2.50`. No estimates, reservations, model pools, per-job dollar caps, or final-turn reserve. |
| Sol lifetime | Sol continues until the spend stop. No voluntary finish, final-10% exception, plateau stop, or continuation-count success stop. Infrastructure failures and operator interruption remain failures or interruptions, not successful budget exhaustion. |
| Search control | **Q15 agreed.** Stall statistics and route suggestions are informational. Sol chooses strategic route changes and hypothesis/conversation restarts; remove forced strategic rerouting and restarts from the legacy loop. Normal Pi context compaction remains automatic, with complete durable lineage references retained. |
| Division of work | Sol directs distinct hypotheses and may experiment itself. DeepSeek V4.1 Flash workers perform independent proof search, including whole-proof structural hypotheses and step-anchored experiments. They are not restricted to mechanical golfing. |
| Worker tools | **Q16 agreed.** Workers receive `compile`, `goal`, `search`, `read`, and overhauled `scratch`, including access to shared findings. Sol owns delegation and cancellation. Workers cannot spawn further workers or replace the strategic whiteboard. |
| Model concurrency | Start with at most two active DeepSeek sessions. Queueing a hypothesis is distinct from activating another model session. Lean admission has separate limits. |
| Handoff and waiting | Delegation returns immediately. Sol may continue working or wait for an event-driven result without paid polling and without ending the run. |
| Session reuse | Each distinct hypothesis starts a fresh conversation. Follow-up work on that hypothesis continues its existing conversation. Preserve the hypothesis-to-session mapping when a worker releases its active slot. |
| Worker completion | A worker may report a useful result or an exhausted hypothesis and finish its assignment before the global spend stop. Sol decides whether to resume it or assign a different hypothesis. |
| Early findings | Publish candidates and evidence as they arrive. Job completion is separate from candidate availability. Notify Sol at its next tool boundary; do not wait for the worker's final report. |
| Team ownership | Either Sol's or a delegated worker's compiled candidate can become the submission after verification. A second Sol approval turn is unnecessary. A harness-generated combination needs an agent to compile or explicitly select that exact proof before eligibility. |
| Background assistance | **Q17 agreed.** Retain existing live salvage/assembly as fully traced proposals, below foreground and promising full checks. An exact generated proof needs agent compilation or selection for eligibility. Stop new transformations at the spend stop. Scratch's caller-authorized internal promotion follows its separately agreed rule. |
| Scratch promotion | When an experiment provides a well-defined candidate, scratch itself constructs and submits it through the normal compile path and returns the outcome. No second promotion call or retyping by the agent. An anchored scratch invocation authorizes its recorded replacement operation, not unrelated combinations. |
| Scratch state | Keep checks isolated. Persist experiment artifacts and reuse helpers only through explicit, recorded dependencies. No invisible accumulation of worker-local declarations. |
| Lineage retention | Retain the complete lineage exactly as recorded, including all input identities, operation details, actors, and alternate derivations. Serving, replay, export, seeding, and restart must not replace it with inferred ancestry or a reduced parent list. |
| Graph presentation | Show canonical proof nodes by default, with expandable attempts and alternative derivations plus a complete experiment/job log. Keep failed, duplicate, and cancelled work accessible. |
| Strategic memory | Sol owns the shared strategic whiteboard. Workers keep hypothesis-local notes and append attributed observations without replacing the shared board. |
| Candidate notes | Retain optional notes for genuinely new rationale. Reference existing delegation hypotheses without copying them into every call. No missing-note warnings or rejection of compile/promotion for absent prose. |
| Closing work | At the spend stop, cancel model activity and new experiments. Finish already-submitted candidate checks and final cold certification. Do not introduce new assemblies, salvage rewrites, or other proof transformations during closing. |
| Verification | Scratch success, fast checks, and endpoint screening do not certify a submission. Preserve full compatibility and independent cold acceptance on all required pins. |

The $2.50 threshold is a post-call stop, not a reservation guarantee. Requests already in flight may report costs after it is crossed; record those actual costs too. The $0.50 headroom does not become an additional pool available to either model. Settlements must be attributed and added once across sessions, including charged retries and compaction, without restoring reservation logic.

### 6.2 Evidence that changes the earlier plan

- [Timing audit](reports/V7_V8_TIMING_2026-10-18.md): 66 historical v7/v8 runs contain 45.03 summed observed run-hours, including 35.14 h of LLM intervals, 6.78 h of foreground tools, and 3.10 h of setup, tail, and gaps. These are overlapping run spans, not exclusive machine utilization.
- The audit records median request intervals of 9.83 s for Sol and 18.52 s for DeepSeek, with p95 24.98 s and 82.89 s. Different workloads and output volumes prevent a controlled speed comparison. Cheap tokens do not establish faster tasks. Async delegation avoids making every worker call a serial dependency, but its score-per-dollar benefit remains unmeasured.
- The 1,593 context-only tool-producing requests account for 7.23 h of LLM intervals. Focused worker packets and compact findings target repeated context gathering; this does not establish that the original context was unnecessary.
- [Packet forensics](reports/PACKET_FORENSIC_AUDIT_2026-10-17.md) measured about 95% cached prompt-token share in the substantive v8 cohorts. Do not equate packet bytes with uncached dollars or blindly shrink useful theorem context.
- Packet review now includes a [complete content and tool-reply review](reports/PACKET_CONTENT_AND_TOOL_REVIEW_2026-10-18.md) of the three [current baseline bundles](packet-review-2026-10-18/README.md), in addition to the forensic reconstruction, transport, size, usage, and caching audit. Confirmed issues include clipped-away Core goal conclusions, missing Fiberwise target definitions and goal coverage, invalid target-relative coordinates, qualified-import parsing, relevance-blind section fitting, tool-reply clipping/repetition, and inspection-schema drift. The controlled efficacy comparison proposed in the [October 16 design note](PI_LEAN_HARNESS_V8_NEXT_DESIGN_2026-10-16.md) remains uncompleted. The immutable exports were generated cache-only with Lean entry points blocked; they are inspection bundles, not parallel-worker prompts or captured provider requests.
- [Heavy-worker contention](reports/HEAVY_WORKER_CONTENTION_2026-10-17.md) measured 7.37 GiB sampled owned-tree PSS for a single-pin B2 probe. That is not one Lean worker's admission estimate. Those edit-only runs returned `FAIL` because they did not exercise timeout recovery; they do not prove foreground/background or multi-pin safety.
- Preserve the [runtime optimizations](LEAN_RUNTIME_OPTIMIZATION_RESULTS_2026-10-16.md), [follow-up measurements](LEAN_RUNTIME_FOLLOWUP_MEASUREMENTS_2026-10-16.md), and [worker lifecycle findings](reports/LEAN_WORKER_LIFECYCLE_2026-10-17.md). Do not overwrite newer local work with the committed v8 proposal.
- Use the [optimization cheatsheet](reports/AGENT_OPTIMIZATION_CHEATSHEET_2026-10-17.md) as a general search method. Whole-structure lemmas and symmetry routes matter alongside local tactic edits. Do not inject saved solutions to individual competition tasks into a from-scratch evaluation.

### 6.3 Pi framework research and proposed runtime

The checkout pins Pi 1.2.0 in `pyproject.toml`; the installed runtime examined in this session is 1.3.0. [Pi v1.3.0](https://github.com/earendil-works/pi/releases/tag/v1.3.0), released October 15, is the latest published release verified on October 18. Reconcile the pin and runtime before the integration evaluation, recording the actual version. Do not silently change it in a scored comparison.

Pi provides session primitives rather than a built-in subagent manager. Luna's research recommends **retaining Sol's current JSON runner and controlling isolated child Pi processes through RPC**:

1. An Arena `delegate` tool registers the hypothesis, launches or resumes its worker session, and returns a job ID immediately.
2. Child readers collect RPC events while Sol continues. RPC prompt acknowledgement means accepted or queued, not completed. Use session-scoped request IDs and continuously drain output.
3. An `await_results` tool holds a cancellable promise until relevant evidence or worker completion arrives. Pi's JSON runner awaits `session.prompt`, and its tool loop awaits execution, so this should keep Sol alive without another provider call. This is source-supported behavior, not yet an Arena integration result.
4. Continue the same session for a hypothesis follow-up. Give a distinct hypothesis a new session. Persist session paths and actor/job IDs independently of whether a child process remains alive.
5. Use `agent_settled` for a completed Pi assignment. `agent_end` can precede retries or continuation. Early proof publication uses tool/evaluation events and does not depend on settlement.
6. For cancellation, clear queued prompts before aborting, then wait for idle and process exit. Count a cancelled process against concurrency until it actually exits. The await tool must unblock on cancellation, failure, and global stop too.

Sources: [RPC mode](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/rpc.md), [RPC commands](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/rpc-commands.md), [JSON lifecycle](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/json.md), [SDK](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/sdk.md), and the [official subagent example](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/examples/extensions/subagent/README.md).

The official example waits for child JSON runs and defaults to disposable sessions. It is reference code, not the required asynchronous persistent manager. Embedded SDK `AgentSession` instances are an alternative, but require careful environment and extension-state isolation. Moving Sol itself to RPC is another alternative if the pending-tool approach fails the offline lifecycle evaluation. Pi Durable and third-party durable-subagent packages are separate integrations, not built-in replacements for the present Arena extension.

Release details to account for:

- v1.3.0 restores active tools on resume, rejects malformed final tool arguments, improves retry coverage, and pins internal dependencies exactly. Exercise these paths with the intended tool allowlist.
- GPT-6 thinking-level changes preserve cache on the documented API-key route. Do not assume that result for the current authentication route without checking it.
- Its 500K context fix names `openai-codex/gpt-6.1-sol`; current `models.yaml` selects `openai` with 272K assumptions. No automatic context expansion follows from that release note.
- The release's two-worker codemode limit concerns executor processes, not DeepSeek sessions or Lean admission. Arena still owns those limits.
- Current DeepSeek and Sol request output ceilings are 64K and 32K. Worker context/output configuration is an evaluation choice, not a new dollar sub-budget. Avoid importing unreleased compaction behavior from upstream `main`.

### 6.4 Delegated jobs, results, and Lean admission

The interface must express a whole-proof hypothesis or a node/step experiment, status, follow-up, cancellation, and waiting. Names and exact schema remain implementation details. Each job needs a stable identity, actor/session, hypothesis, explicit anchor where applicable, lifecycle state, and durable result references. Hypothesis identity is distinct from the process that happens to execute it. Q15–Q17 put strategy and worker management with Sol, give workers the full proof-search toolset, and retain existing background transformations as traced proposals subject to team-ownership eligibility.

Sol receives proof scores, hotspots, the candidate frontier, and its delegation ledger. A worker receives its hypothesis, necessary proof and goal context, source references, relevant prior findings, and tools sufficient for real search. Return compact evidence records and artifact IDs, not full worker transcripts. Failed and duplicate attempts remain available for analysis without repeated full checks.

Keep scheduling in a dedicated module rather than expanding `arena/campaign.py` further. Initial Lean policy remains conservative: foreground Sol requests and promising full checks precede speculative worker work; allow one DeepSeek Lean compilation at a time initially. Reuse matching pinned project/document state and retain the 5 GiB admission safeguard. More model sessions do not imply more warm Lean workers.

The current service has FIFO `model` and `background` lanes, not the proposed global priority queue. A new lane label alone does not create admission priority. Measure representative contention before choosing implementation details such as yielding, worker sharing, or separate slots. The earlier +10% foreground wait target is a diagnostic comparison, not a closed-track score acceptance gate. Memory health and verification correctness remain requirements.

### 6.5 Scratch as durable experiments

Carry forward §2b rather than designing scratch again. The [v8c handoff](../handoffs/2026-10-16-v8c.md) listed the scratch/whiteboard overhaul as pending. The first implemented increment now stores the original `code` alongside `code_sha256` in each accepted scratch event in the run's `ledger.jsonl`, before context construction or Lean execution. The ledger's existing locked append and fsync retain the submitted text, including whitespace and Unicode, independently of compiler success or timeout. Old hash-only events remain readable; their missing code is not reconstructed by guessing.

Current `arena/tools.py::scratch_tool` still accepts only `code` and replaces the target declaration in a pinned source file. Durable experiment outcomes, graph anchors, actor/job identity, and promotion remain to build. Scratch allows `sorry`, and its declarations do not persist into subsequent calls. Its success is neither a closed-proof claim nor all-pin compatibility evidence. Focused mocked-Lean tests cover exact code/hash retention across success, failure, timeout, and context-construction failure; this increment does not claim live-Lean or multi-agent validation.

Proposed experiment records preserve the submitted code or content-addressed artifact, source context, proof hash and step anchor, actor/session/job, hypothesis, raw and rendered diagnostics, declarations/goals checked, per-pin outcome, token/HB measurement provenance, timing, cancellation, and trace references. Keep general `#check`, `#print`, and `example` exploration possible. An experiment anchor records what was explored; it is not automatically a proof derivation edge.

**Promotion decision, Q10:** scratch handles promotion within the original tool invocation whenever the experiment defines a candidate. It constructs the exact parent proof plus replacement and invokes the normal compile path, recording both the experiment and the resulting attempt/derivation. The caller does not make a separate promotion or compile call. Promotion is not a certificate: a local scratch goal closing does not establish full proof compatibility or a better full proxy. Let ordinary checks measure those properties rather than assuming that cheaper local text improves the whole proof.

Promotion needs enough information to reconstruct the intended proof:

- For a step experiment, an immutable parent proof identity and exact replacement step/range or hole, plus which submitted code is the replacement. The proposed `at` anchor and snippet form must make that mapping unambiguous.
- The matching pinned source context, declaration scope, statement, and local proof context. Resolve these from the recorded parent and environment. A pretty-printed goal is evidence, not by itself a complete reconstructible Lean environment.
- Any helper declarations or assumptions the experiment uses, with explicit dependency/artifact identities. Helpers must be included in the resulting proof where legal, or the experiment is not yet promotable. Never rely on declarations left in a previous scratch process.
- Actor/session/job/hypothesis and creating call identities. The harness supplies these; do not ask the model to repeat metadata already present in the session or job.

The current code-only scratch API lacks the replacement mapping. The new anchored API must capture it in the original call, or inherit an exact anchor from the delegated job and record that resolved anchor before execution. `#check`, `#print`, successful examples about other statements, and incomplete snippets remain experiments rather than target-proof candidates. An unanchored complete target proof is promotable only when the tool can identify its target and extract the exact proof without guessing.

The response includes the experiment ID, promotion outcome or concrete reason it is not possible, candidate node/proof hash when one was filed, exact derivation/input references, diagnostics and measured score/token/HB deltas where available, and fast/full/cold verification state. Pending compatibility checks are reported as pending. A failed promoted compile remains a recorded attempt and does not erase the useful scratch result.

**Isolation decision, Q11:** checks remain isolated. Reusing an experiment or helper follows explicit artifact/dependency references. Durable observations and session memory do not silently mutate the Lean environment.

### 6.6 Proof identity, attempts, and exact lineage

The [v7 lineage study](PLAN-harness-v7.md#5b-agent--harness-lineage-by-construction-measurement-only-as-an-audit) already evaluated 20 runs and 1,791 nodes. The best text method matched explicitly named parents only 48.1% of the time, and did not confirm any of eight combine mentions. Preserve the resulting rule: operation-generated lineage is exact; focus filing, named parents, and measured similarity remain different relations.

Proposed organizing model:

| Record | Meaning and required links |
|---|---|
| Proof node | Immutable target/proof identity and hash, stored text, status, route/steps/holes, and evaluation references. Reuse the existing target and proof identity; do not replace it merely to add actor metadata. |
| Attempt | An actor's experiment or compile invocation, with its own ID, hypothesis/job, Pi session, request/tool-call references, input anchors, operation, submitted artifact, and outcome. Duplicate proofs still have distinct attempts. |
| Derivation | The operation and exact input proof/step identities that construct an output proof. One canonical proof may have several derivations. Preserve input roles for merges. |
| Observation | An actor's claim anchored to a proof, step, or experiment. Link supporting checks where present; distinguish a model-written claim from verified evidence. |
| Evaluation | Proof or experiment checked against particular source/toolchain pins, with fast/full/cold mode, result/cache identity, diagnostics, tokens, heartbeats, and timing. Different contexts or pins must not share evidence just because text matches. |
| Delegation | Who assigned a hypothesis to whom, its scope, session, lifecycle, and results. Delegation ancestry is not proof ancestry. |
| Eligibility | Agent compilation, or an agent's explicit selection of an exact harness-generated proof, followed separately by required verification. No inferred approval of transformed descendants. |

Costs belong to provider requests and can be grouped by actor/job. One request can produce several candidates; do not charge its full cost to every node or present an arbitrary allocation as measured per-proof cost.

**Exact retention is a user requirement.** Preserve the original lineage record and referenced artifacts, including every operation input, input role/step, output identity, actor/session/job, experiment reference, and alternate derivation. Keep the original serialized records and artifact bytes retrievable. Do not regenerate that record from similarity, creation order, current focus, a later summary, or a model-written note. Store later facts as additional records instead of overwriting the original. Compaction and restart may summarize conversational context, but must retain stable references to the complete original lineage. Display clipping must leave the original record retrievable. Replay and export must preserve the same relationships and details, not merely a plausible-looking graph. Test a lineage round trip across storage, serving, export/reload, and resumed sessions, including duplicate proofs with multiple derivations.

Verified implementation gaps to address:

- `Graph.from_history` reads `edge.from`, but `campaign.graph_state` and the served viewer still expose/draw legacy parents and derivations. Use one authoritative projection for agent tools, serving, export, and lineage analysis.
- `_file_node` deduplicates a proof and can retain only its existing edge. Preserve additional attempts and legitimate alternate derivations instead of losing the second agent's discovery.
- Default focus is shared, so one worker's batch can change another actor's filing context. Capture immutable anchors at job/attempt admission. Keep actor-local conversational focus and delivery cursors separate from the shared best/frontier. Current run-wide `delivered_seq` can hide an update from Sol after a worker consumes it.
- `node_calls` currently reads one run-level journal and can fall back to time windows. Join new multi-agent records by actor/session/request/tool-call identities and explicit journal references. Keep time-based ambiguity handling for historical logs; do not invent missing ancestry or actor data.

### 6.7 Served graph and node detail requirements

Retain the existing [Reasoning & calls viewer](../.scratch/arena-harness-v7/issues/18-viewer.md), including lazy loading, actual delivered versus untrimmed results, sibling nodes, steps, holes, and explicit ambiguity for older logs. Extend it rather than replacing its evidence with generated summaries.

Node details need exact and alternative derivations, experiment anchors, actor/model/session/job/hypothesis, source/toolchain and proof identities, verification evidence per pin, eligibility, notes/observations, score deltas with their comparison base, and links to the creating calls. Distinguish exact construction from claimed inspiration, default filing, and similarity.

Show every active actor/job with its anchor, model activity, Lean queue/check state, waiting reason, early findings, and cancellation state. Current viewer state can collapse several jobs into one `active_job`; expand that representation. A run intentionally awaiting worker evidence is not a hung Pi process merely because it has made no recent provider request. Keep shared spend visible with actor breakdowns of actual settlements, without implying separate allocations.

**Presentation decision, Q12:** canonical proof nodes are the default graph, with expandable attempts and alternate derivations plus a complete experiment/job log. Experiments retain their own identities and anchors. Failed, duplicate, and cancelled work remains accessible without presenting every lookup as a proof node. All views read the same retained lineage; graph simplification must not delete or reinterpret it.

**Memory decision, Q14:** Sol alone replaces the shared strategic whiteboard. Workers append attributed observations and maintain hypothesis-local notes. Preserve observation provenance and evidence links when Sol summarizes findings. The summary does not replace the original observations or lineage records.

### 6.8 Ownership examples checked in recent runs

These October 16 examples separate agent ownership from later correctness checks. Scores are local proxy values. Each cited Sol final answer matches its saved proof after whitespace normalization.

| Run | Sol's final proof | Later harness result | Team-ownership implication |
|---|---|---|---|
| Core | #10, 72 tokens, 215 HB, 87.60 | Golf accepted no edit; #10 passed cold verification | Already agent-produced. Later certification does not create a different proof. |
| WickAlgebra | #32, 329 tokens, 7,744 HB, 84.88 | Post-agent golf produced #33, 327 tokens, 7,739 cold HB, 84.93; actual submission #33 | The unapproved transformed child would be ineligible under the agreed policy. #32 would need its own cold certification; that counterfactual outcome was not measured. |
| Fiberwise | #33, 167 tokens, 2,192 HB, 91.53 | Golf #34 reached session proxy 91.64 but failed cold compatibility; submission fell back to #33 | Ownership and cold acceptance are separate. The actual delivered agent proof remains eligible. |

Evidence: [Core ledger](../runs/pi-budget/v8c-Core.InitsUpdatesComm-gpt-6.1-sol-r1/ledger.jsonl), [Wick ledger](../runs/pi-budget/v8c-FieldSpecification.WickAlgebra.-_timeOrd-gpt-6.1-sol-r1/ledger.jsonl), and [Fiberwise ledger](../runs/pi-budget/v8c-Binius.BinaryBasefold.fiberwise_dist_lt-gpt-6.1-sol-r1/ledger.jsonl), with final-text events at lines 10664, 12920, and 12355 of their respective `events.jsonl` files. This is historical evidence, not a request to re-enable golf. [The current policy audit](reports/AGENT_FINAL_PROOF_POLICY_2026-10-17.md) confirms automatic golf removal but an outstanding closing-assembly eligibility gap.

A worker-produced proof differs from those post-agent transformations: it is produced by a delegated agent. Team ownership allows its verified candidate to win even if Sol never gets another paid turn. An automatic assembly still needs an agent's exact-proof compile or selection before closing.

### 6.9 Implementation and evaluation sequence

Treat this as one coherent prototype with independently checkable parts. Documentation does not claim implementation or authorize API spend.

1. Reconcile the Pi pin with the intended runtime. Run an offline delegation/session lifecycle evaluation before choosing a larger runner migration. Reuse `tests/fake_opencode.ts`, `tests/pi_support.py::FakeRun`, and existing runner continuation/compaction tests.
   - Implement the packet/tool-text review in §6.11 after preserving the saved baseline bundles. Repair extraction and context selection before reducing text. Distinguish current baseline text from proposed Sol/worker text; correct shared-spend wording and inspection-renderer drift. Do not silently rewrite the baseline artifacts.
2. Establish actor/session/job identities, durable experiments and attempt records, exact derivation projection, per-session focus/delivery, and team-ownership eligibility. Scratch and served graph consume that common history.
3. Add nonblocking delegation, hypothesis session creation/resume, early result publication, event-driven waiting, cancellation, and the shared actual-cost accumulator. Preserve all settlements after stop and prevent duplicate settlement on replay/resume.
4. Route worker tools through the existing pinned Lean infrastructure with separate model and Lean admission. Preserve current memory safeguards, demand-driven allocation, cooperative yielding, checker shutdown, and cold gates.
5. Extend serving/logging with all active jobs, exact node evidence, experiment results, and actual spend attribution. Implement scratch-managed promotion, isolated helper dependencies, expandable canonical nodes, and Sol-owned strategic memory. Retain the agreed optional-note policy.
6. Offline acceptance must cover delayed worker responses while Sol continues, zero provider calls during waiting, fresh versus resumed context, two simultaneous results, duplicate proof discoveries through different derivations, actor-local focus/cursors, failed/cancelled jobs, and cancellation at the shared spend stop. Already-submitted checks finish; no new closing transformation is filed. Inspect process exit as well as reported cancellation.
7. Replay saved proofs through real Lean only after the offline lifecycle is sound, on an idle machine with isolated service/artifacts. Separate mock-provider results, real-Lean results, and paid search results.
8. Proposed paid pilot: matched from-scratch Sol-only versus Sol plus two DeepSeek workers on SKI diamond, Core, and Fiberwise. Both arms use the same selected total cap, pins, runtime fixes, and strategic packet improvements. No model pool split, saved-proof seed, or larger multi-agent allowance. The initial $1.50 pilot cap is a proposal, not a new production cap or spend authorization.
9. Repeat paired runs and expand rows before a score claim. Then evaluate all 15 development problems from scratch with the intended $2.50 shared stop and $0.50 headroom. Score per dollar and verified score are primary. Report wall time, useful discoveries, duplicate attempts, Sol context turns, Lean waits, PSS, swap/PSI, and failures as explanatory measurements.

The old fixed $0.75/$0.25 split, seeded arms, hidden-minion prerequisite, best-only publication, and mandatory +10% latency gate do not apply. Keep Harness²-style policy/meta-optimization outside the competition execution loop until the traces support a separate study.

### 6.10 Follow-up decisions

Do not reopen the agreed spend bucket, team ownership, fresh-per-hypothesis sessions, event-driven waiting, early publication, worker completion, or verification drain. The user also requires exact lineage retention, not merely correct initial recording. Q10–Q17 are settled and reflected in §§6.1 and 6.5–6.7. Q18 is partly settled below. Remaining framework and schema details need technical evaluation rather than another question about settled policies.

| Question | Decision or remaining trade-off |
|---|---|
| Q10. Does scratch perform promotion itself? | **Agreed.** Promote within the original scratch call whenever its recorded context defines a candidate, and return the details. No extra agent call. See §6.5 for required inputs and verification boundaries. |
| Q11. Do scratch helper declarations persist implicitly? | **Settled.** Checks are isolated. Reuse helpers only through explicit, recorded dependencies. |
| Q12. What is the default served graph? | **Agreed.** Canonical proof nodes with expandable attempts/alternate derivations and a complete experiment/job log. |
| Q13. Require, retain optionally, or remove candidate notes? | **Agreed for now.** Keep optional notes for new rationale, reference existing hypotheses, and emit no missing-note warnings. A note never establishes exact lineage or proof correctness. |
| Q14. Who writes shared strategic memory? | **Agreed.** Sol owns the shared strategic whiteboard. Workers append attributed observations and keep hypothesis-local notes. |
| Q15. Who controls strategic restarts and route changes? | **Agreed.** Sol chooses them; stall feedback remains informational. Ordinary Pi compaction remains automatic. |
| Q16. Which tools do workers receive? | **Agreed.** All five proof-search tools and shared findings, without nested delegation or replacement of Sol's strategic memory. |
| Q17. Keep live background salvage/assembly? | **Agreed.** Retain as traced proposals, subject to exact agent eligibility and the spend-stop transformation boundary. |
| Q18. What belongs in the first v8 milestone? | **Partly settled.** Defer separate Pi/MCP exploration and recombination work. Reuse the same agent architecture for the open track; choosing an eligible model and applying that track's run configuration does not require a separate orchestration rewrite. Per-lemma removal experiments remain a proposal, not an agreed mandatory workstream or an agreed deferral. Three-packet content review is complete; packet/tool-text redesign and efficacy evaluation remain pending. |

**Q13 evidence supporting the accepted optional-note policy.** A bounded inspection of the five v8c r1 runs found 141 unique model-origin candidate creation records, 74 with a nonblank hypothesis. This is initial candidate metadata, not compile-call coverage; deduplication can retain the first record's note. It does not replace the older §2c note counts, which use different denominators. Model-produced cold winners in [Core](../runs/pi-budget/v8c-Core.InitsUpdatesComm-gpt-6.1-sol-r1/ledger.jsonl), [CCS](../runs/pi-budget/v8c-Cslib.CCS.bisimilarity_congr_choice-gpt-6.1-sol-r1/ledger.jsonl), and [Interleaved](../runs/pi-budget/v8c-interleaved_affine_gaps_imply_tensor_gap-gpt-6.1-sol-r1/ledger.jsonl) have blank hypotheses at lines 173, 389, and 368 respectively. Absence of notes does not prevent a winning proof; this is not a controlled estimate of the value of notes.

Useful notes record otherwise unavailable intent, such as Core's "New structure: prove disjointness first, then use canonical commutation." Generic labels such as "Recheck baseline" add little beyond operation metadata. Notes can help delegation handoffs, failed-experiment interpretation, and later analysis, but consume output and future context tokens. Current `compile` accepts one note for an entire batch, so making it required would not provide a distinct rationale for every draft. A note is neither exact ancestry nor evidence of correctness.

Accepted policy: retain optional notes for genuinely new intent, link existing delegation hypotheses rather than copying them into every call, and derive operation labels from structured metadata. Do not reject compile or scratch promotion for missing prose, and do not emit missing-note reminders. No measured score benefit or total marginal cost has been established. For scale only, 100 notes of 20 output tokens each would cost $0.020 for Sol or $0.0012 for DeepSeek at current configured output rates in `models.yaml`; these are illustrative output-only calculations, excluding reasoning changes and later input/cache costs.

Technical questions about exact RPC schemas, lane implementation, dedupe locking, and event wake-up races are for source inspection and offline evaluation. They do not require preference questions when existing invariants determine the answer.


### 6.11 Packet and tool-text redesign from the completed content review

The [review report](reports/PACKET_CONTENT_AND_TOOL_REVIEW_2026-10-18.md) records source-backed findings, section character shares, saved tool-reply examples, and proposed acceptance cases. The primary reviewer read all three complete exports; supporting reviews checked extraction, tool replies, and generic lessons. No Lean or provider calls were used. This completes content analysis for those examples, not a controlled utility study or implementation.

**Correctness before compression.** Preserve Core's actual goal conclusions instead of clipping them behind long hypotheses. Fix Fiberwise's target-proof extraction, which appears vulnerable to an earlier binder `by`; validate that mechanism with Lean. Select definitions from the target theorem type so `hammingClose` is not displaced by auxiliary theorem types. Retain original source coordinates for external syntax rather than negative target-relative lines. Recognize `public import`. Separate extraction completion, packet coverage, and verification certification. Label published scoring denominators separately from cached local profile measurements.

**Information hierarchy.** Keep the immutable statement, scope, compatibility requirement, full proof access, score trade-offs, and usable hotspots. Keep raw pin hashes in harness provenance and on-demand evidence, not routine agent text. Present shared local context once with step/case-scoped goals. Combine relevant declarations into one catalog with role tags and stable source handles. Protect nearby reusable lemmas from wholesale eviction before lower-value occurrence inventories. Move raw occurrence telemetry, flattened locals across branches, repeated signatures, and unchanged graph summaries behind retrieval. Every clipped view must identify clipping and retain access to the complete original. A concise view must not alter proof bytes, line mappings, or retained lineage.

**Tool replies and inspection.** Return stable experiment/result references, intact essential signatures and targets, explicit pending/full/cold states, and changes since that actor's last delivery. Distinguish valid search misses from invalid requests and open goals from parser/type errors. Fix malformed Markdown fences. Prefer compact graph updates with an explicit full-map read. Generate inspection parameter help from actual registered schemas; remove legacy finish help. The historical stale compile-status issue is already refreshed in current source and must not be presented as a newly confirmed defect.

**Shared search guidance.** Review the [generic cheatsheet draft](packet-review-2026-10-18/GENERIC_CHEATSHEET_DRAFT.md) for inclusion in the common contract. Extract whole-structure lemmas, symmetry, native project APIs, distinct hypotheses, focused tests, current-candidate profiling, token/HB trade-offs, and evidence reuse. Keep named task solutions and analyst hybrids in offline reports. Qualify tactic folklore; do not require a lookup before every draft or small edits for a structural rewrite. The older report's blank-line token claim is contradicted by the current pinned counter and must not be propagated. This draft is not installed in live prompts.

**Acceptance.** Re-render all three packets and representative saved replies after implementation, preserving these baseline artifacts and hashes. Check semantic coverage and exact retrieval, not only size. Add targeted renderer/schema/reply cases and pinned Lean extraction cases; renderer tests alone do not validate the wrapper. Check compaction and resumed-worker context retain essential facts and exact evidence references. Compare search outcomes from scratch with matched spend and identical runtime/pins before claiming improved score per dollar. Current character shares, map repetition, and cached-token ratios are diagnostics, not savings estimates.


### 6.12 Packet and tool-output overhaul: content contract

The user requests an overhaul of content, templates, and formatting, rather than isolated shortening. This section makes the implementation scope concrete. It refines §6.11; runtime/templates have not yet been rewritten. Preserve all previous spend, ownership, lineage, and verification decisions.

#### Agent context versus harness provenance

Raw source commit hashes do not help the agent choose a proof when the harness selects and enforces the environment. Remove them from default startup packets, ordinary tool replies, and conversational memory. Retain exact hashes, source/toolchain identities, and evaluation/cache provenance unchanged in artifacts and the served evidence details. Expose them on demand for investigation. This is presentation selection, not deletion of provenance.

Default context needs the requirement to pass every required environment, their count, usable theorem/source handles, and the scope/imports needed to write Lean. Display specific Lean versions and diagnostics when they explain a compatibility failure; a concise version list can remain available in the environment view. Agents must not be asked to choose or repeat pin hashes already known to the harness.

#### SKI evidence and the replacement cost views

The exported SKI table has seven top-level rows, not empty metric columns. For example s4 spans lines 5–31 and reports 160 tokens, 4 self HB, 412 inclusive HB, and +23.03 estimated attributed points. Its total row has inapplicable dashes and embeds versions 4/4 and score 33.33 in the text column. The unconditional legend defines fields even when a view has no useful values. Separate total metrics from step rows and render explanations only for fields actually shown. Unknown, zero, pending, and inapplicable are different states.

`split_steps` intentionally exposes top-level edit steps, with special handling for calc relations. SKI's indentation tree contains 63 regions, but only seven become step rows; these regions are syntax partitions, not a measured count of Lean tactics. The 27-line s4 region alone contains 26 nested indentation regions. Therefore the top-level table is an overview, not a complete cost breakdown. The separate startup line profile shows only 12 selected self-HB entries and loses branch structure. Existing `read(view="tree")` uses measured nested profile entries but displays only 30 selected rows; it is not an unbounded full-tree renderer.

Replace the single overloaded presentation with three coordinated views:

1. **Proof summary.** Tokens, published scoring denominator, locally measured HB with provenance, compatibility, and score. Report unmeasured/pending facts explicitly. Keep reference score separate from locally remeasured values.
2. **Structural overview and nested hotspots.** Show top-level editable ranges with body-inclusive HB and tokens. Add relevant expensive nested measured spans, with parent path, proof identity, line range, concise text, and whether siblings/children are omitted. Do not assign new editable step IDs from indentation alone or imply arbitrary syntax spans are valid splice targets. Mark previews explicitly when clipped.
3. **Full cost details on demand.** Retain self/exclusive HB, inclusive HB, exact source and goal references, all available measured entries, and attribution coverage. Provide expansion or pagination when the existing 30-row view omits entries. Do not silently sum nested inclusive costs or overlapping token spans.

Remove `pts_if_gone` from the default table. It models elimination of attributed cost while other costs stay fixed; it is neither a measured optimization nor a general upper bound on improvement. If retained in a detailed view, label that assumption explicitly. Actual compile results report measured changes against a named comparison proof. Keep self HB in detailed profiling, where it distinguishes expensive elaboration at a node from cost in its children. Do not print an all-missing column or its legend. A missing important measurement gets one coverage/status statement and a retrieval route, not unexplained repeated dashes.

#### Common content rules for every output

| Surface | Essential content | Default presentation excludes |
|---|---|---|
| Startup contract | Task validity, actual shared-cost/lifetime policy, scoring, tool semantics, concise generic method | Raw revision hashes, obsolete finish instructions, universal tactic folklore, duplicated descriptions |
| Sol theorem packet | Statement/scope, complete proof access, relevant definitions/lemmas, cost overview plus nested hotspots, coverage, graph/jobs and strategic findings when present | Raw occurrence telemetry, locals merged across unrelated cases, duplicate signatures, empty ledger boilerplate |
| Worker packet | Distinct hypothesis, immutable parent/anchor, sufficient local or whole-proof context, relevant evidence and retrieval | Unrelated actor transcripts, copied strategic boilerplate, repeated known metadata |
| Compile reply | Candidate/attempt identity, operation/input references, outcome, measured deltas with base, diagnostics, holes, verification state, relevant graph/job changes | Unchanged full map, ambiguous best label, fake zero costs, missing-note reminders |
| Goal/trial reply | Exact proof/position/case, target, scoped hypotheses or full-state reference, closed/open/error outcome, changed goals | Repeated identical states, clipped-away targets, open-goal verdicts presented as malformed input |
| Search/read reply | Match/source identity, usable signature or exact text, source location, result count/coverage and continuation | Invalid-input language for no matches, repeated qualified names, irrelevant suggestions, clipped binder prefixes with no conclusion |
| Scratch reply | Experiment identity, submitted artifact/context, diagnostics, isolated result, promotion outcome or reason, candidate/derivation/evaluation references when present | Generic `scratch` as sole identity, implication of certification from local success, retyping metadata known by the harness |
| Compaction/resume | Current strategy, actor-local focus/jobs, useful failures and findings, exact durable references to proof/experiment/lineage | Repeated raw logs, hashes with no reasoning use, replacement of original evidence by summaries |
| Served graph/evidence | Full exact provenance, alternate derivations, attempts, evaluations, original artifacts and calls | No information loss from simplifying the default graph |

Schema-derived inspection help and shared structured evidence must feed these views. Keep tool schemas, values, templates, inspection exports, and served details consistent. Do not create another independently maintained packet-only interpretation. Formatting rules include valid fenced blocks, line-numbered proof displays with preserved raw artifacts, descriptive column names, conditional legends, explicit clipping/selection coverage, and consistent identities/status vocabulary.

#### Delivery and checks

Build this as a v8 workstream covering extraction/selection, content models, shared rendering, five tool outputs, schema inspection, and compaction/resume. Start with a field inventory assigning each fact to default text, on-demand text, or retained machine evidence. Scope live template/code edits into coherent independently reviewable changes; keep the original three exports intact.

Acceptance must demonstrate that the exact statement and useful goals survive, target predicates are retained, source coordinates/imports are correct, no default pin hashes or all-missing columns appear, nested hotspots remain visible under large top-level branches, totals do not pretend to be step rows, and all omitted details are retrievable. Include zero versus missing, all-missing profiles, partial coverage, long signatures, long case contexts, duplicate proofs/derivations, no search matches, pending checks, and resumed actors. Existing template text budgets and goldens must be updated deliberately, with semantic assertions alongside snapshots. Real wrapper/extraction checks require pinned Lean; offline render checks do not establish them. Only matched-spend search evaluation can establish score-per-dollar benefit.


### 6.13 Implementation-contract refinements and ticket breakdown, 2026-10-19

The [spec appendix](SPEC-harness-v8.md#implementation-contract-appendix-2026-10-19) defines durable operation/event identities, management-tool fields, request/job/candidate/evaluation transitions, actor-local delivery, atomic actual-cost dispatch, unknown usage, crash reconciliation, no-event waiting, and the exact proof-submission/stop ordering. Scratch promotion and all live transformations obey that same boundary. Inconclusive cold checks remain distinct from proof errors.

Current source confirms two integration gaps: the pre-provider notification hook cannot veto a call, and the spend helper treats missing/invalid usage as zero. Implementation must address both without introducing estimated-cost stops or reservations. Configured illustrative pricing also shows that 100K uncached Sol input plus a 32K output ceiling costs $0.52, already greater than the $0.50 headroom. This is not a measured bill or full worst-case bound. Production cap assurance therefore requires a separate offline assessment and explicit owner go/no-go when a bound is not established; the actual-cost policy is unchanged.

The [local ticket index](../.scratch/arena-harness-v8/README.md) groups narrow vertical slices under M1 identities/history/ownership, M2 scripted parallel lifecycle/accounting/recovery, M3 durable scratch and real verification, M4 context/evidence/text, and M5 admission/evaluation. The user requested publication as individual local Markdown issues. Their files carry the logical blocker edges and resolved GitButler stack parents; publication does not start implementation or a paid run.

Resource-efficiency evaluation separately compares existing cleanup with reuse-aware retention across SKI/CCS, Fiberwise/Binius, and Putnam sequences, one versus two selected heavy Lean workers, and foreground work during compatibility checks. It records verified throughput and resource health without making that optimization study a prerequisite for the first prototype. Track-specific execution deadlines remain separate from closed-track search policy and must survive restart. The latest minimum-smoke/final-E2E test policy in §6.15 supersedes earlier per-ticket integration-batch requirements.


### 6.14 Linear small-implementer ticket sizing, 2026-10-19

The user requires sequential implementation on GitButler branches stacked above the existing work. The [revised proposal](../.scratch/arena-harness-v8/README.md) contains 24 individual implementation issues numbered 03–26. The user requested removal of both obsolete draft sets, leaving one active issue per ticket. Eight split boundaries separate accounting/dispatch, fresh RPC/follow-ups, two-worker admission/event waiting, process/accounting recovery, experiment retention/promotion, stop races/cold outcomes, replies/schema help, and serving/compaction. This sizes work conservatively for a fresh Luna/Grok implementer; it is not a measured claim about either model's capability.

Every ticket has an ownership boundary, relevant spec decisions, numbered acceptance criteria, test budget, branch, immediate stack parent and stop conditions. Logical dependencies remain explicit, but execution is one oldest-to-newest chain with a review before the next branch. Keep coherent atomic commits within each ticket. The optional resource-study harness follows pilot preparation; its actual measurement matrix remains separate.

Read-only GitButler status showed `v8/02-stall-notes` as the latest committed v8 branch and existing empty planning/runtime/audit heads above it, with their work uncommitted. Resolve the actual existing stack top after those owners commit the baseline before creating the first new branch; do not discard or absorb their work. The implementation issues are now published locally. The current-work cleanup commits precede the first implementation branch; publishing the issues does not create branches 03–26.


### 6.15 Concrete ticket handoffs and minimum-fast-test policy, 2026-10-19

The user explicitly requires minimum fast tests per ticket and end-to-end coverage at the end of the stack. This supersedes all earlier instructions to run the complete fast suite or an actual Pi/Lean journey per implementation unit. One small reused/extended behavior smoke is normally enough to check out a ticket. Aim for seconds, usually 5–15 seconds and no more than 60 seconds. Do not add one test per acceptance bullet or run 30-minute suites after branches. Additional focused checks are justified by a failure or concrete adjacent concern, not by a blanket checklist.

The [shared implementation contracts](../.scratch/arena-harness-v8/contracts.md) fixes current entry points, proposed shared interfaces, input/error/recovery semantics, one smoke selector per ticket and deferred integration coverage. The [ticket manifest](../.scratch/arena-harness-v8/manifest.json) labels every new selector as proposed, not an existing passing test. Each of the 24 issue files includes its own concrete details and Verify command plus the resolved shared GitButler/testing rules. Earlier full-suite and selected actual-Pi/Lean ticket gates are removed.

The [final E2E checklist](../.scratch/arena-harness-v8/final-e2e.md) consolidates one broad fast run and selected scripted actual-Pi, real-Lean/cold, packet/reply/viewer/resume journeys after implementation. It keeps integration gaps visible without forcing exhaustive per-ticket tests. Resource measurements and paid search remain separate owner-scoped evaluations. No runtime code, tests, services or provider calls were started by this documentation work.

Source inspection identified a supported provider wrapper route through the installed Pi's streamSimple registration and injectable fetch. Preserve existing provider/auth/callbacks and gate each transport attempt, including retries; do not rely on a non-veto notification hook. This is a grounded implementation path, not a claim of completed actual-Pi integration. The handoff also fixes append-only operation receipts/lock ordering, decimal actual settlements, owned-child stop-and-resume rather than orphan-pipe reattachment, unambiguous scratch forms, filtered actor-delivery acknowledgements and request-class priority independent of Lean lane.


### 6.16 Published local issues and shared GitButler rules, 2026-10-19

Use [the local index](../.scratch/arena-harness-v8/README.md) to hand an implementer exactly one of the 24 files under `issues/`. The user explicitly requested this v7-style layout and deletion of drafts. The shared [_common.md](../.scratch/arena-harness-v8/issues/_common.md) is pasted into every issue with ticket number, branch and immediate parent resolved. It covers creating only the current branch, GitButler-only inspection/commits, atomic ownership-scoped commits, no push/lower-history rewriting, minimum fast checks and needs-review hand-back. Current changes are committed as a baseline on `v8/02-current-work`; ticket 03 stacks there, followed linearly by 04–26. No implementation branch is created merely by publishing its issue.
