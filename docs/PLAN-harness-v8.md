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
5. **Parallel workers for the open track** (from OpenProver's `-P`).
   - *Why:* on 4×A100 the marginal token cost is zero, and the limit is 48 h for 50 rows (about 58 min per row). Four copies of Qwen3.8-27B (55.6 GB BF16 each, one per GPU) or a planner plus three workers fit.
   - *Shape:* the planner (our normal run) gets a `delegate(at: <node>.<step>, goal)` tool. A worker gets one step goal and the step's context, with only `compile` and `search`, and a short budget (turns or seconds). Its candidates enter the same graph with `origin: worker`.
   - Optional: a Lean-trained model as a worker (Goedel-Prover-V2-32B, about 64 GB). It fits next to Qwen (about 120 GB total) and returns whole-step proofs that the harness compiles.
   - *Closed track:* only with a cheap worker model (DeepSeek), and only once the per-row $3 cap accounting covers workers.
6. **Pinned verified helpers** (from OpenProver's `lean_store`, lower priority).
   - A verified `have` or helper lemma can be pinned to a route, and later candidates on that route reuse it by name. Fits poorly for single-theorem refactors; revisit if candidates often retype the same helper.

### Do not copy

- **A visible conclusion phase** (`--conclude-after`). It breaks the hidden stop rule; v5/v6 models gamed visible stops.
- **An LLM verifier after each worker.** Lean is the verifier.
- **Strict keep-or-reset.** Our graph branches from non-best nodes, and v8c's late gains came from that.

### Related v8c finding: full checks wait behind salvage

- **What happened:** on Binius `fiberwise`, the best stayed at #10 while #12 (188 tok / 2610 HB) and #13 (185 / 2614) had better fast estimates. None of the three had a full check yet.
  - A full check takes about 150 s (4 toolchains) and runs one at a time.
  - `autocheck` (`arena/campaign.py`) drains `("salvage", "assembly", "full", "step_goals", "profiles")` in that order, so salvage jobs (117 s, 70 s, 9 s, the last two failed) ran before the full check of the leader.
  - #14 then overtook #12 and #13, which were correctly skipped once #14 verified at 90.57.
- **Effect:** the model's packet showed a stale best for about 4 minutes, so it compared variants against the wrong node and could get a stall nudge while a better proof waited in the queue.
- **Fix (after v8c ends):**
  - put `"full"` first in the background order, so a candidate whose fast estimate beats the verified best is checked before any salvage;
  - later, run the extra toolchains of one full check in parallel when free memory allows (Wick dropped to 7.8 GB).

### v8c early results (Sol $1.0, DeepSeek fallback $0.25, seeded from submission-final)

| Row | Baseline | v8c | Gain |
|---|---|---|---|
| CCS `bisimilarity_congr_choice` | 86.76 | 87.21 | +0.45 |
| Wick `ι_timeOrderF_superCommuteF_eq_time` | 84.11 | 84.93 | +0.82 |
| Binius `fiberwise` (running) | 87.01 | 91.34 | +4.33 |
| `interleaved_affine_gaps` (running) | 87.15 | 89.54 | +2.39 |

- Stall nudges at 8 fired 1, 3, 0 and 2 times. A new best followed each nudge in CCS and Wick.
- The forced restart after 2 tries never fired.
- The golf pass accepted 1 edit on Wick and none on CCS.

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

## 5. Process notes

- Claude weekly quota was at 93% on 2026-10-16 and resets 2026-10-23. Use Haiku minions for mechanical work and Sonnet only for code.
- An index-script change renames every cached index (the digest covers `arena/lean/index.lean`). Copy semantically identical indexes to their new names instead of rebuilding.
- An operator SIGTERM stop still drains checks and cold-verifies the best, so plateaued runs can be stopped safely.
