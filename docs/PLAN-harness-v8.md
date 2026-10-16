# Harness v8 plan

Started 2026-10-16, after v7 landed on main (`428cb6c`, tag `v7`). This doc lists what to build and test next, with pointers. v7 history stays in `docs/PLAN-harness-v7.md` (§12j, §12k cover the v8a campaign).

## 0. Where we stand

- Official closed track: **88.45%, rank 7** (2026-10-16). Leaders: 91.28 (emergence-mini), 91.15 (RMA, Claude Sonnet 5), 89.77.
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

## 2. Build next (harness does the mechanical golf, the model does the ideas)

Ordered by expected gain per effort. Model-facing text stays neutral and the hidden stop rule stays absolute.

1. **Golf pass after the run, never in the background during it** (user, 2026-10-16: background edits would compete with the agent for Lean and memory).
   - *When:* once, after Pi exits, inside the closing drain, under a time cap and with one Lean check at a time; also usable offline over a submission. Optionally a model-invoked tool that runs one bounded pass through the normal lane scheduler.
   - *What:* tries single deletions (each `[..]` list item, each line, each `;`/`<;>` segment) and small rewrites (`intro h; clear h` → `rintro -`; `dsimp only` → `simp only` before `grind`/`simp_all`).
   - *Rules:* accept by full proxy; the result feeds the submission, not the running model.
   - *Prior art:* `tools/golf/dd.py` (minion script, copied from the session scratchpad), `runs/analysis/hybrid-push/ablate.py`, `mk.py`.
   - *Tool help:* `arena.prices.snippet_tokens` pre-filters token deltas offline.
2. **Per-lemma heartbeat costs.**
   - Per-step profiles exist (ledger `profile`/`step_goals`). Add costs for each lemma inside `simp`/`grind`/`rw` lists, and mark lemmas whose removal keeps the goal closed as unused.
   - Show the model "tokens Δ, hb Δ, score Δ" on every check, so it stops trading heartbeats for tokens.
3. **Start from the best known proof.**
   - Campaign and run seeding should take the best cold-verified proof from any source (runs, `runs/analysis/**`, earlier submissions), not only a run dir.
   - Add `--seed-proof <file>`, or extend `--seed-run` to accept a proof file.
   - Pool loose proofs in `arena submission` too, so nothing like the claude-push fiber/inter proofs is missed.
4. **Stall escalation, then a hidden plateau stop.** v8b SKI: last gain at turn 23; turns 24–80 made 33 nodes, all on the best's route r2, 19 compiled candidates and none above the best. The harness sent one `stall` nudge at turn 47 (count 12, mode `best_other_cell`), Sol ignored it, and nothing escalated. Ladder: (1) the current nudge; (2) if ignored for N more tries, an automatic restart from the best node on another route (`_restart_order` exists); (3) compile replies report the route's tally, e.g. "route r2: 30 variants, none above best"; (4) the hidden plateau stop below. Neutral wording; the stop stays hidden.
   - **Hidden plateau stop.** End a run, harness-side, after N turns or $X with no new best. It must not be visible to the model (D42).
5. **Row-independent playbook in the packet.** The queued L1–L8 lessons (v7 PLAN §12f), plus the claude-push `LOG.md` structural moves, phrased neutrally.
6. **Restart on text-only turns** (deferred from v7). It helped DeepSeek on EM (44 → 78).
7. **recombine.py, smaller items:** rank donors by proxy, not tokens; per-arm/nested swaps keyed by goal; seed rows from loose proofs.

## 2b. Tool surface review (2026-10-16)

v8a tool use over 19 runs: compile 946 calls (1 error), scratch 434 (10), read 357 (9), search 260 (0), goal 109 (0). Scratch is a fifth of all calls and sits entirely outside the graph: its ledger row keeps only `code_sha256`, with no code, result, graph position or link to the node it explored. What Sol learns there (a working sub-proof, a cheaper tactic, a lemma's heartbeat cost) is lost to the graph, to salvage, to recombine, to seeded runs and to the session digest.

### Scratch overhaul (v8/02, after v8/01 lands)
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
- **Readable reasoning from OpenAI models.** v8b Sol turns carry no text blocks and only about 35 readable reasoning characters per turn; the rest is encrypted. Find where pi-ai's OpenAI provider builds `reasoning` and request `summary: "detailed"` (Responses API). Check on one short capped Sol run that summaries get longer on the ChatGPT backend. If it works, the summaries feed the seeded-run digest; otherwise add an optional `note` argument to `compile`, stored on the node.
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

**3. A finished run stays alive while its checker runs (fixed in `arena.ts`, not yet committed).**
- *What happened:* both runs ended their agent loop in the final tenth (Sol 97% and 93.5% spent; its last turn was text only). Pi then sat idle for 15–20 minutes with no network connection, because the spawned checker child kept the Node process alive. The checker was still draining salvage for a model that had stopped. `arena run` waits for Pi to exit before its closing drain, golf and cold verification, so the run never finished.
- *Workaround used:* stopped the checkers by PID. Pi exited at once and `arena run` went into `finish()`.
- *Fix:* in the stop branch of the agent-end handler, clear `kickAgain` and `checker?.kill("SIGTERM")`. The closing drain in `arena/cli/run.py` (`autocheck(..., closing=True)`) still full-checks every candidate that could beat the best, so the submission does not change.
  - Do not `unref()` the child instead: an orphaned checker would hold `autocheck.lock`, and the closing drain returns `running_elsewhere` without checking.
  - Extension tests pass (43). The golden session must pass on an idle machine before this is called ready.
- *Why earlier runs did not hang:* before fix 1 the tail was the same, but shorter runs had fewer broken candidates, so the salvage queue emptied within minutes of the stop.

**Still to build.**
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
