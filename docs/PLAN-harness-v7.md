# Harness v7 plan (brainstorm draft, 2026-10-10)

Status: **planning only. No code changes until the owner approves.** This document gathers the facts collected on
2026-10-10, the owner's decisions so far, and a proposed design. The fix list stays in `docs/ISSUES-harness-v7.md`
and the agreed backlog in `docs/BACKLOG-harness-v7.md`. This plan says how v7 closes them.

**Supersedes** BACKLOG §2 (routes by subgoals as the primary signature) and §5a (measured lineage as primary). §13
maps every ISSUES, BACKLOG and WORKING item to its answer.

**Starting point.** v6 is on main, tagged `v6` (4205d4e). Submission v3 scored 84.41%, rank 4 of 27. The official
scores match our cold proxies within ±0.6 on every row. The weakest axis is length: 69.95% against the leader's
79.58%.

## 0. Decisions so far

| # | Decision | Status |
|---|---|---|
| D1 | CLI framework: **Cyclopts**, with Rich output | decided |
| D2 | Cut tautological tests now, then write a minimal pytest suite against the v7 interfaces (not a port of the 495 unittest cases) | decided |
| D3 | No model-facing text in code: one directory holds every word the agent sees; every number is computed per theorem at packet build | decided |
| D4 | One rules source: skill, packet prose and tool descriptions come from the same templates, and a test checks they agree | decided |
| D5 | "Lean help" means **problem-specific numbers** (what each step costs and what a change would save in tokens and heartbeats), not syntax tutorials | decided |
| D6 | Complete rewrite of every agent-facing text: every word has to earn its place | decided |
| D7 | Candidate graph overhaul, combined with autoresearch ideas | decided, design below |
| D8 | **Delete `budget.ts` and all estimate and reservation machinery.** After every LLM call, add its actual cost. If the run total reaches the run's dollar limit, stop the agent and let the harness close the run. Limits: $0.50 for now, never above $2. The $3 closed-track cap is irrelevant | decided, §2d |
| D9 | The plan is a living document. Claude updates it at every decision, so it never goes stale | decided |
| D10 | **Models: DeepSeek v4.1 flash plus MiMo 2.6 Pro (via primalab).** Drop gpt-6-luna and qwen3.8-flash | decided, §9a |
| D11 | **`arena replay`**: the CLI shows exactly what the model saw at any turn of a historical run: system prompt, skill, packet, tool definitions, messages, tool results as delivered, reasoning | decided, §7a |
| D12 | **Viewer node panel** shows, beyond the proof and diffs, the reasoning and the tool calls (with results) that produced the node | decided, §7b |
| D13 | **The harness produces the final best proof, hybrids included** (in-harness recombination §5g plus `arena submit` BACKLOG §6), replacing the hand-run submission scripts | decided |
| D14 | Every design choice is backed by replay data, not guesses (the §5i replays; O12 grounded by the salvage replay) | decided |
| D15 | O1: `finish` is registered only when ≤10% of the budget is left | decided 2026-10-10 |
| D16 | O2: drop declared ideas. Routes are internal. An optional `note` on nodes is kept | decided |
| D17 | O4: the price table is included with the full original proof in the packet | decided |
| D18 | O7: `agent-text/` at the repo root | decided |
| D19 | O8: **search is offline only for now** (our own index, §4d). The competition always has network access, so remote search stays a later option | decided |
| D20 | O9: dot-notation completions are exposed through `search` | decided |
| D21 | O10: auto-assemble with the cheapest closing fill, and **tell the model** (the map lists the alternatives) | decided |
| D22 | O11: (a) focus moves within one session now. (b) fresh context and (c) islands are later experiments, **only if attempt diversity does not improve** | decided |
| D23 | O12: salvage every failed draft (the S2→S3→S4 chain) | decided |
| D24 | O13: accept Pi's post-hook payload. No fetch hook for wire bytes | decided |
| D25 | O6: decided by a probe test (§9a). **Probe done:** DeepSeek (opencode-go) accepts a tool-call history with earlier `reasoning_content` omitted. Quality impact needs an A/B run | API side settled; quality A/B owner-launched |
| D26 | O14: DeepSeek stays on opencode-go. primalab serves an older DeepSeek version | decided |
| D27 | O5: archive cell key **K1 = (route, depth bucket, closed/sketch)**. The leading score axis is dropped (probe, §5d) | decided by probe |
| D28 | "Credit" is retired. `finish` depends only on the ≤10% rule (D15), and diversity comes from stall moves (§5e). BACKLOG §4b shallow-branch credit is moot | decided |
| D29 | Route validation by hand labels is dropped (the owner found "same approach?" judgments on diffs meaningless). Routes are internal bookkeeping for archive cells. They are judged by outcomes: the archive probe now, and diversity metrics in phase 5 | decided |
| D30 | O3: **the pre-run sweep is dropped** (probe: 0 of 349 suggestions compiled). `goal try` stays (the model's own snippets, priced). No harness-run suggestion engines | decided |
| D31 | **Heartbeats are measured on the newest listed toolchain**, not the first listed (`engine.py:123`). Probe: Putnam reference denominators match exactly on the newest (a4 111,476 = 111,476; a3 14,134 vs 14,130; b2 134,518 vs 134,499). Only the Putnam rows list oldest-first, which caused the −10% to +27% mismatch. A P1 fix in phase 2, with a test over all 15 rows | decided by probe |
| D32 | Keep our `HEARTBEAT_WRAPPER`. It matches the official denominators more closely than the organizers' `#count_heartbeats` baseline (fold_advances 45,537 vs 47,746 against official 45,273; SKI 1,384 vs 1,505 against 1,383), and their method failed to run on 7 rows | decided by probe |
| D33 | **BACKLOG §1 (unfold hop) is dropped.** On 6 rows it ranked answer-key lemmas lower (e.g. 187→357, 16→37), moved the PhysLib key lemma from #1 to #2, and tripled the candidate pool. Most answer keys were empty or tiny: the best proofs rarely use library lemmas the reference does not | decided by probe (stopped early) |
| D34 | **Keep the packet's library section at the top 60**, adding a tokens column (§3e). Hit-rate probe (§12e): of 301 names in the 15 best proofs, 46% came from the reference, **6% from the packet's top 60** (18 names across 7 rows, including the PhysLib and b2 key lemmas), 4% from other packet sections, 15% appeared in search results, and 29% came from the model's own knowledge. The hits spread over ranks 1–58 (10 of 18 in the top 20), so cutting to 20 would lose about half | decided by probe |
| D35 | **Lean speed gate:** a recorded baseline (`arena lean bench`). v7 must match or beat it (+10% p50 / +20% p95 tolerance), and any later regression beyond tolerance fails, because a v6 code change once cost 6 hours by slowing Lean. **Two tiers (owner decision 2026-10-13):** each Lean ticket runs the quick gate (`--compare`, default rows Core, Putnam, CSLib on their first toolchain, about 6 min); the full gate (`--full --compare`: every row and toolchain the baseline holds, ArkLib's four included, about 25 min) runs after 12 (the one planned after 08d moved there, owner 2026-10-13; passed 2026-10-13, 0 regressions), and whenever the quick gate fails | decided |
| D36 | **Build order and implementers (spec review 2026-10-10).** Ticket 00 sets up the uv project first (`uv init --bare`, uv 0.13.0, then the flat-layout `pyproject.toml`). Ticket 01 deletes everything already decided as removed, before any refactor, so later tickets touch less code. Tickets are implemented by Luna 6 in Codex, one at a time on stacked GitButler branches, and reviewed here. Each ticket must therefore be self-contained: the ask, checkboxes, constraints, stop conditions, the GitButler rules, atomic commits with detailed messages, and a review report at hand-back. The ticket split is confirmed with the owner before the files are written | decided, §10 |
| D37 | **The v7 campaign is two rows:** the best-scoring row (putnam_1964_b2, 98.54: checks v7 does not regress where v6 is near the ceiling) and the worst (Cslib.SKI.parallelReduction_diamond, 70.37: checks v7 gains where v6 is weakest). DeepSeek does the v6-vs-v7 A/B; MiMo checks the new model on v7. Both rows are already in the Lean speed baseline | decided, §10 |
| D38 | **Tooling and branches (2026-10-10).** ruff and ty are dev dependencies configured in `pyproject.toml` (ruff: line 120, rules E F W I B UP SIM C4 PERF RUF; RUF001-003 ignored because Lean text uses ×, α, ℝ). The owner asked for the ruff noise to be removed at once: format plus safe and unsafe autofixes landed in ticket 01 (one unsafe F841 fix reverted by hand). The 31 findings without an autofix and the 144 ty diagnostics are fixed by the tickets that touch that code. Branches are named `v7/<NN>-<slug>`, one straight stack in ticket order on `v7/plan`, each reviewed before the next starts. **Nothing merges to main until the owner says so** (no milestone merges) | decided |
| D39 | **Ticket 01 scope.** Deleted up front: lean4-skills and its copied references, `arena_skill.py` (its live part moved to `arena/skill.py`), `route_validation.py`, `submission/` (checklist to `docs/SUBMISSION-checklist.md`), the benchmark research notes, Luna and Qwen, `budget.test.ts`/`testmodels.ts`, 9 tautological tests. **Kept until their replacement lands**, so the harness runs between tickets: the LLM route extraction (`route_features.py`, the background route worker; goes in ticket 11) and the idea tool plus `arena_skill_read` (go with the old tools in ticket 15) | decided |
| D40 | **The lean-lsp-mcp server is removed** (owner, 2026-10-10), not kept as a hidden backend. Ticket 15 deletes it; `compile` and `goal` run on the shared Lean service's LSP lane, so no Lean process runs outside the memory budget (spec story 30). Ticket 08a must therefore provide on that lane what the MCP tools gave: goals at a position or hole, and running a snippet at a hole (`goal try`) | decided |
| D41 | **Ticket review (owner, 2026-10-10).** Splits: 05→05a/05b, 08a→08a/08b/08c with the REPL ticket as 08d, 10→10a/10b, 15→15a/15b/15c, 19→19a/19b (27 tickets, 04–20, one straight stack). The library token-cost column is dropped (§3e). **Health gate:** the model starts once the primary toolchain's reference proof passes; the other toolchains' reference checks continue in the background and a failure marks the run unhealthy and stops it before further spend; final verification and `arena submit` still require every listed toolchain green. **Speed gate** noise floor 0.25 s (a figure fails only above both the % tolerance and 0.25 s), run at the end of 08a–08d, 10b and 12. Truncated turns (#35): Pi `maxTokens` set to the run ceiling if Pi supports it, else owner decision. Finish is one call that stops at once. `arena submit` keeps the $3 per-problem total (summed over contributing runs) as a reported gate. Stall default `best_other_cell`; route 13+ joins the best route; filing threshold 0.50. REPL adopted only on the stated agreement and speed rule, else shipped disabled. `arena text budget` counts words. "All errors at once" (#9) is in 15a; #26 and #27 in 15b; spec stories 28 and 29 in 08b | decided |

Open decisions are listed in §11.

## 1. Facts gathered (2026-10-10)

### 1a. Pi 1.1.0
- Installed and active (`pi --version` gives 1.1.0). The previous version was probably 1.0.4.
- The changelog has no breaking entries in 1.0.4 or 1.1.0. The only break since 1.0.0 was a provider rename we don't
  use. The `.d.ts` diff from 1.0.4 to 1.1.0 is additive only.
- Every hook and API that `packages/arena-pi/extensions/arena.ts` uses is present and unchanged.
- The Langfuse patch targets the plugin (0.1.2), not Pi. It still applies.
- **To check:**
  - 1.1.0 fixes cost reporting for models with prompt-length pricing tiers. Under D8 we take the cost from each call's
    usage, so check that Pi's per-call cost is right on long prompts for our models.
  - Pi's built-in retry may not reach our `arena-guard` provider wrapper. If the wrapper exists only for budget
    gating, D8 lets us delete it (§2d).
- **New or newly useful features:**
  - `agent_settled.aborted` and `tool_execution_end.durationMs` (new in 1.1.0).
  - Retry of `server_busy` and "at capacity" errors (new in 1.1.0).
  - `httpIdleTimeoutMs`, default 300 s. Not new, but unused by us.
  - `retry.*` settings.
- Nothing pins the Pi version. `packages/arena-pi/package.json` has peerDependencies `"*"`.

### 1b. CLI and packaging
- 20 argparse entrypoints, all under `tools/`, plus `arena/lean_session.py serve`.
- No `pyproject.toml`. Tests run with `uv run --no-project`. Python 3.13.
- `tools/arena_campaign.py` (27 flags) is the **JSON protocol the Pi extension calls**, not a human CLI.
- `tools/smoke_theorems.py` has no `__main__`, so it may be dead.

### 1c. Tests
- Python: 495 unittest cases, 25 modules, 7.6K lines.
- TypeScript: 56 `node:test` cases (budget 25, rules 16, trim 7, toolnames 5, journal 3).
- About 14 low-value cases were found: tests that restate the YAML, mock-only assertions, substrings copied from
  source, and one test that still asserts "cap $3 each".
- The ISSUES #6 test is at `tests/test_lean_session.py:628`.
- `rules.test.ts`, `budget.test.ts` and `trim.test.ts` assert exact text, so they move with the templates (§2).

### 1d. Model-facing text today
- **In code:** about 110–130 strings, about 30K characters, spread across
  - `arena.ts`: 12 tool descriptions;
  - `rules.ts`: refusals, pushes and route text;
  - `budget.ts`: footer and gates;
  - `trim.ts`: stubs;
  - `context.py`: packet prose and `SCORING_FACTS`;
  - `campaign.py`: about 40 tool-result and error strings;
  - `memory.py`: compaction memory.
- **Skill files:** 176K characters. SKILL.md is 8.7K, and 12 vendored lean4-skills references come to about 165K.
- **Duplication:**
  - The ≤10% rule is stated 4 times, and `0.1` and "10%" are hardcoded beside `FINISH_ALLOWED_REMAINING_FRACTION`.
  - The token-counting rules are in both `SCORING_FACTS` and SKILL.md, about 250 wasted tokens per run.
  - The sorry/route sentence is in 3 places.
- **Stale or hardcoded:**
  - "original scores only 33" (`SKILL.md:98`);
  - "`⟨a, b⟩` is 5" (`context.py:210`), which should be computed by the counter;
  - "90% down on heartbeats" (`SKILL.md:102`).
- **ISSUES #4 is already fixed** (`context.py:637` agrees with the tool description). What remains is the triplication.
- **The references steer proof content.** They contain strategy terms: tactics-reference 78 hits, simp-reference 40,
  performance-optimization 27. They also describe `lake build` and shell workflows the agent cannot use. This
  contradicts `context.py:8`, which says nothing in the packet suggests a strategy.

### 1e. Lean errors in v6 drafts
2,535 diagnostic files, about 1,750 errors.
- About 90% are semantic: unsolved goals 288, application type mismatch 229, rewrite pattern not found 138, type
  mismatch 80, "made no progress" 63.
- About 2% are syntax: `by`-block layout, and 13 unknown tactics. No Lean 3 syntax.
- Unknown identifiers are mostly scope slips. There was one confusable (`ℱq`/`𝔽q`).
- Deprecation warnings come from library source, not from drafts.
- **Conclusion: syntax help is not the gap.**

### 1f. Tool use in v6
22 runs, 1,960 calls. DeepSeek made about 80% of the calls (16 runs; Qwen 3, Luna 3).

| tool | calls | share | err | avg result | note |
|---|---|---|---|---|---|
| arena_probe | 963 | 49.1% | 0.3% | 3.0 KB | probe→probe→probe 400× |
| arena_source | 185 | 9.4% | 7.0% | 5.6 KB | source×3 34×, source→find→source 26× |
| arena_find | 162 | 8.3% | 0% | 5.5 KB | |
| arena_idea | 149 | 7.6% | 4.0% | 0.6 KB | Luna 123 of them |
| arena_finish | 113 | 5.8% | — | 1.9 KB | **84% refused** (95/113) |
| arena_profile | 102 | 5.2% | 0% | **9.3 KB** | probe↔profile about 100× |
| lean_multi_attempt | 56 | 2.9% | 1.8% | 5.4 KB | column out of range |
| arena_state | 54 | 2.8% | 0% | 0.8 KB | |
| arena_declarations | 44 | 2.2% | 9.1% | 3.4 KB | invalid name rejects the batch |
| lean_goal | 41 | 2.1% | 7.3% | 1.6 KB | line out of range (offsets) |
| arena_candidate | 36 | 1.8% | 0% | 3.7 KB | |
| lean_local_search | 25 | 1.3% | 0% | 0.8 KB | |
| arena_evaluate | 14 | 0.7% | 7.1% | 1.2 KB | compiling probes auto-promote |
| arena_skill_read | 7 | 0.4% | 0% | **14.3 KB** | |
| lean_diagnostic_messages / lean_hover_info | 6 / 2 | 0.4% | 0% | | |

- **Bookkeeping-only turns** (calls only to idea, state, candidate, skill_read or finish):
  - DeepSeek: 8.4% of spend.
  - Qwen: 5.4%.
  - **Luna: 47%** ($0.45 of $0.96).
- **Calls before the first compiled candidate:**
  - DeepSeek: median 16, mostly source, find and multi_attempt.
  - Luna: median 6.

### 1g. Autoresearch (karpathy/autoresearch and follow-ups)
- **Mechanics:**
  - One editable file and a read-only evaluator.
  - A fixed 5-minute budget per experiment.
  - Keep the change if `val_bpb` improves, otherwise reset.
  - One `results.tsv` log, one human-edited `program.md`.
  - At equal score, simpler wins.
  - The loop never stops on its own.
- **Reported pitfalls:**
  - Overfitting to the one metric used for selection.
  - Upward bias from picking the best of many noisy trials.
  - Agents exploiting shared state.
  - **Mode collapse onto near-identical edits** (arXiv 2609.00077).
  - No variance figures are reported.
- The papers are preprints, and `program.md` was read through a summarizer. Quote the raw files before citing them.

### 1h. Graph use and big edits in v6
See §5a. Models plan forks and merges in their reasoning but never express them through the tools. Drafts that
change more than 30 lines compile 23% of the time, against 69% for 1–3 lines.

### 1i. Offline search tools (READMEs and release notes; not run)
- **Loogle local** (lean-lsp-mcp `LEAN_LOOGLE_LOCAL`).
  - Offline, with name and type-pattern search.
  - Built per toolchain from a pinned commit, with a 900 s build timeout.
  - About 13 GiB peak RAM for a Mathlib index, about 7 GiB warm.
  - It may index only Mathlib (unverified).
- **LeanExplore local:** natural language plus name. A fixed set of packages (Mathlib, CSLib, PhysLean, core,
  others), with no ArkLib and no Strata.
- **LeanSearch v2, Lean Finder, LeanHammer premise selection:** remote services. They could be self-hosted, which
  is not trivial.
- **Core `Lean.LibrarySuggestions`** (v4.26+): `grind +suggestions` and `simp? +suggestions`, with a symbol-based
  premise selector. Not available on v4.25.
- **Lean Copilot `select_premises`:** tied to a fixed Mathlib snapshot.
- **`exact?`, `apply?`, `rw?`:** in core, on every toolchain, over the whole environment.
- **Our own index:** a declaration dump from `env.constants` per project and toolchain, which `context.lean`
  already half does. An optional embedding index over it: about 1 GB, about an hour on CPU for Mathlib, millisecond
  queries.

### 1j. Diversity research (abstract level; about 9 sources)
- "Beneath the Diff" (arXiv 2609.00077): the diversity of edits looks healthy while the diversity of mechanisms
  collapses. A harness-side coverage reweighting with an edit memory cut the decay by 69%.
- FunSearch islands: the worst islands are re-seeded from the best ones.
- FunFuzz (arXiv 2605.02789): soft migration beats full resets.
- DeepSeek-Prover V1.5 RMaxTS (arXiv 2408.08152): an intrinsic novelty reward, and resuming from any prefix.
- Sequential sampling repeats itself more than parallel sampling (arXiv 2608.28496, machine translation).
- A context reset alone gives mixed results (arXiv 2609.28150).
- ImProver (ICLR 2025): goal states plus error correction for proof optimisation.
- QDAIF (arXiv 2310.13032): a quality-diversity archive fills more of the behaviour space.
- Arbor (arXiv 2606.11926): a coordinator, short-lived executors and a persistent hypothesis tree.
- **No source tests structural diversity on weak models.** Treat it as a hypothesis to measure.

### 1k. Hybrids in submissions v1–v3
- **Five submitted rows are hand-built hybrids, worth 43.58 points in all** (v3 MANIFEST: 1263.75 with hybrids
  against 1220.17 harness-only).

| Row | Hybrid | Best single run | Gain |
|---|---|---|---|
| Core.InitsUpdatesComm | 87.10 | 86.07 | +1.03 |
| variational calculus' | 89.93 | 88.25 | +1.68 |
| CCS bisimilarity_congr_choice | 86.76 | 86.44 | +0.32 |
| CallElim extractedOldExprInVars | 82.42 | 72.29 | +10.13 |
| CallElim substOldPostSubset | 82.86 | 52.45 | +30.41 |

- **Method.** One run's proof is the skeleton. One or a few steps are swapped in from **another run** at the same
  position, then the result is cold-compiled. The 6 `runs/analysis/*-hybrid-*.lean` files have no script that
  produced them.
- **Existing in-harness merge.**
  - `arena/graph.py merge_text` does a line-level 3-way merge, and **needs a common ancestor**.
  - `campaign.py merge_once/merge_batch` (~1955-2055) and `tools/arena_merge_worker.py` run it.
  - Cross-run hybrids have no common ancestor, so this path could never have found them.
  - `submission()` (~2212-2250) reads one run and excludes `auto_merge` nodes.
- **Reusable:** `cold_verify`, the app.py filter loaded via `ast` (submission-v3 `build.py`), and the memory wait
  (`run.sh`).
- **To check:** the harness filter list (`tools/arena_check.FORBIDDEN`) and the official one (`app.py`) are separate
  copies.

### 1l. Heartbeat measurement and hotspots for the 15 rows (2026-10-10, `hotspots-15.md`)
**How each axis is measured:**
- **Tokens:** Python only, using the vendored official counter (`engine.py:46`).
- **Heartbeats:** the same fast compile on the measure version, the first listed toolchain, because
  `measure-versions.json` does not exist (`engine.py:123`). `HEARTBEAT_WRAPPER` (`engine.py:28`) reads
  `IO.getNumHeartbeats` around `elabCommand`, with `Elab.async false` and `maxHeartbeats 0`, divided by 1000.
- **Per-step heartbeats:** a second compile (`profile.py:262`).
- **Coverage:** one compile per other toolchain.

**Deterministic.** 1,033 (row, proof, toolchain) groups were measured more than once. 1,032 are identical, and one
differs by 1 heartbeat.

**The official grader is private.** `vendor/arena-space` is the UI only. Its public hints are `#count_heartbeats` /
`getNumHeartbeats` under `Elab.async false`, the reference denominators in `benchmark_heartbeats.jsonl`, and
coverage = passed / listed.
- Our measured reference matches the official denominator within 0.1% on 9 rows and within 1.7% on the Binius rows.
- It is **off on the Putnam rows**: b2 −10.4%, a3 +27.1%, a4 +25.6%.
- But the official per-row scores matched our proxies within ±0.6.
- **Resolved (D31, D32):** the official grader measures on the **newest listed toolchain**. We measured on the first
  listed, which differs only on the Putnam rows (listed oldest-first). Data: `research/v7-probes/hb/official-hb.jsonl`.
  Our wrapper stays: it is closer to the official numbers than the organizers' `#count_heartbeats` code.

**Headroom of submission v3** (coverage is 100% on every row, so only tokens and heartbeats differ):

| Row | tok% | hb% | Largest headroom | Top reference hotspot (self hb, share) |
|---|---|---|---|---|
| Fsub.progress | 18.6 | 98.3 | **tokens 27.1 pts** | L66, 24,198 (41%) |
| SKI diamond | 41.0 | 69.9 | tokens 19.7 | L29–31, 67 (5%) |
| FieldSpec timeOrderF | 51.5 | 75.2 | tokens 16.2 | L110, 5,845 (14%) |
| substOldPostSubset | 91.7 | 56.9 | **heartbeats 14.4** | L6, 1,235 (24%) |
| EM time_deriv | 58.2 | 76.7 | tokens 13.9 | L20–126, 3,997 (15%) |
| extractedOldExprInVars | 65.3 | 81.9 | tokens 11.6 | L7–10, 1,108 (41%) |
| Core.InitsUpdatesComm | 66.1 | 95.2 | tokens 11.3 | L36, 1,036 (24%) |
| CCS bisimilarity | 66.9 | 93.4 | tokens 11.0 | L58, 797 (21%) |
| Binius fiberwise | 67.5 | 75.5 | tokens 10.8 | L87–88, 1,483 (9%) |
| interleaved_affine_gaps | 83.4 | 72.1 | heartbeats 9.3 | L143–167, 1,049 (11%) |
| putnam_1964_a4 | 82.4 | 94.2 | tokens 5.9 | L71–162, 53,552 (38%) |
| variational calculus' | 83.0 | 86.8 | tokens 5.7 | L42–43, 3,873 (32%) |
| putnam_1995_a3 | 89.4 | 82.9 | heartbeats 5.7 | L78–100, 2,035 (11%) |
| Binius fold_advances | 86.5 | 85.1 | heartbeats 5.0 | L104, 8,678 (19%) |
| putnam_1964_b2 | 97.8 | 97.9 | tokens 0.7 | L172–209, 25,682 (21%) |

- None of the 15 best proofs has a cached per-step profile. Each needs one profile compile (15 compiles, Lean only)
  for its own price table.
- The ranking matches the weak-token rows in the next-session notes (Fsub, SKI, FieldSpec, EM).

## 2. Agent text: one directory, templates only (D3, D4, D6)

### 2a. Layout
`agent-text/` sits at the repo root, because both Python and TS read it.

```
agent-text/
  README.md            how to edit, placeholder rules, the word-budget table (generated)
  numbers.yaml         harness constants shown to the model (finish fraction, list caps); one source for code too
  skill/SKILL.md       rewritten from zero; references/ deleted (see 3d)
  packet/              task.md, scoring.md, price-table.md, sections.yaml, library.md, profile.md
  tools/<tool>.yaml    description + per-parameter descriptions, for each v7 tool (§4)
  replies/             compile.md, search.md, read.md, goal.md, finish.md: per-tool reply lines
  messages/            footer.md, refusals.yaml, continuation.md, compaction-memory.md, errors.yaml, arena-line.md
```

### 2b. Rules
1. **No literal reaches the model from code.** A lint test greps TS and Python for long string literals in
   model-facing modules and fails on any that is not a template key. Log and exception strings that never reach the
   model are allowed and must be marked.
2. **Templates contain no logic.** Placeholders take the form `{name}` or `{name:.2f}`. Plurals and conditionals stay in code,
   which passes ready-made fragments. Python renders with `str.format_map` and a strict dict that raises on a missing
   key. TS renders with an equivalent regex renderer, about 20 lines.
3. **Every number is computed.**
   - Token examples come from running `_proof_length` on the example text.
   - Rates come from `exchange_rates()`.
   - Thresholds come from `numbers.yaml`, which the code also reads.
   - Per-theorem facts are computed at packet build, after Lean has measured them.
4. **One statement per rule.** A rule lives in exactly one template. Others link to it by placement (the packet
   includes `scoring.md`), never by copy.
5. **Word budget.** The README carries a generated table: template → tokens (by the competition tokenizer) → where it
   is shown → how often per run. Each line of text has to justify its tokens × shows. Review it at every text change.
6. **Neutral.** No template names a kind of proof. A test greps the rendered skill, packet and tool descriptions for a
   denylist of strategy terms. It runs on rendered output, so placeholders filled from library names don't trip it.

### 2c. Tests (part of the minimal suite)
- Every template parses. Every placeholder is supplied by each renderer that uses it, and no supplied key is unused.
- The rendered skill, packet and tool descriptions state each `numbers.yaml` value identically. This closes ISSUES #4
  by construction.
- The literal lint and the neutrality grep described in 2b.

### 2d. Budget: actual cost only (D8)
- **As built (ticket 02, 2026-10-10).**
  - `spend.ts` holds the rule. The stop code is `limit_reached` (it replaces `soft_cap_reached`,
    `actual_usage_cap` and `estimated_request_unaffordable`).
  - The stop calls `ctx.abort()` from the settle step (`message_end`, `session_compact`): Pi 1.1.0 does not reach
    `agent_before_settle` while the model keeps calling tools, so a stop placed only there would let spend run on.
  - `arena_finish` is hidden with `setActiveTools` until 10% or less is left. Turning it on changes the tool list,
    which costs one cache miss per run (about $0.015 on DeepSeek).
  - Compaction summary requests bypass `before_provider_request`: they get no request row and no output clamp.
    Their cost still settles once from `session_compact`.
  - Byte-exact `wire` rows are gone with the provider wrapper; the request row carries the post-hook payload.
    Getting wire bytes back would need a fetch interposer.
  - **Pending (ticket 03):** the check of Pi's built-in catalog prices against `models.yaml`. Pi prices
    opencode-go models from its own catalog, so a stale catalog would make the stop wrong.
- **Rule.**
  - After each LLM call, including compaction calls, add the cost reported in that call's usage to the run total.
  - If total ≥ limit, stop the agent. The harness then closes the run: final verification, summary, submission pick.
  - The overshoot is at most one call, which is accepted.
- **Deleted:**
  - `packages/arena-pi/extensions/budget.ts`: reservations, worst-case request estimates, window and byte bounds
    (`boundedPayload`), unresolved spend, and the $3 gate.
  - The Python `unresolved` and `all-call cost` fields.
  - The compaction bypass, since there is no gate left to bypass.
- **Where "actual cost" comes from.** Pi computes `usage.cost` locally: provider-reported token counts × the
  model's configured prices (`pi-ai/dist/models.js:657-676`, tiers supported). It never reads a provider-reported
  dollar figure. So the stop is exact only if the prices in the Pi model config are right. The v6 price-mismatch
  refusal goes with `budget.ts`. In its place, one test checks the configured prices against the provider's price
  page for each model.
- **Kept, simplified:**
  - One ledger row per call with its actual cost.
  - The footer showing spent and left.
  - The finish fraction, which moves to `agent-text/numbers.yaml`.
- **Closes or makes moot:**
  - ISSUES #1, #2, #37, #39 and #46.
  - The gate half of #44. The rounding stays a text fix.
  - #48.
  - The gating parts of #34 and BACKLOG §4a.
  - #23, unless the cache alarm is kept as a diagnostic.
- **Removal map** (2026-10-10):
  - **TS, deleted (about 850–900 lines).**
    - In `budget.ts` (327 lines): caps, the model catalog and price checks, `boundedPayload`, `budgetGate`, the
      `sessionSpend` cross-checks and the reservation helpers.
    - The whole of `budget.test.ts` (25 tests) and `testmodels.ts`.
    - In `arena.ts`: the `costState` reserve and unresolved reduction (340-361), the `onPayload` gate (460-548),
      the reservation-outdated checks (424-429, 567-574), the virtual-model loop (555-580), and the
      unresolved, hard-remaining and embedded-estimate status fields (707-743).
    - The stop code `estimated_request_unaffordable`.
  - **TS, kept (shrunk):**
    - One settle row from `message.usage.cost.total` in `message_end` (arena.ts:676).
    - Compaction cost from `session_compact` (679-682).
    - The stop: `spent >= limitUsd` in the existing `agent_before_settle` handler (arena.ts:1246). Optionally
      `ctx.abort()` from `message_end` to cut a long tool batch.
    - The footer, with `stopUsd`/`BudgetLimits` collapsed to one `limitUsd`.
  - **Python (about 150–200 lines):** `unresolved_usd` and `all_call_cost_usd` in
    - `tools/run_campaign.py:171-236`;
    - the reserve reconciliation in `arena/summary.py:136-181, 333, 412, 518-524`;
    - `arena/package.py:77-110, 290`;
    - the reserve and window settings in `tools/run_pi_budgeted.py:217, 366, 513-517`.
  - The ledger keeps settle rows only.
- **`arena-guard` provider (arena.ts:409-553) can be deleted.** It does more than budgeting, but nothing it does
  needs a provider wrapper:
  - The malformed tool-argument repair (`guardMalformedToolArguments`) moves to `message_end` or `context`, as
    `compaction_repair` already does.
  - Request journaling and `request` trace rows move to `before_provider_request` and `after_provider_response`.
  - The per-attempt `retry_of` link is lost once Pi retries internally. Check what `arena/package.py:77-110`
    joins on before deleting.
  - Gain: Pi's native `retry.*` and `httpIdleTimeoutMs` apply directly (#3, #14), and guard refusals stop counting
    as provider errors.

### 2e. Order
First move the strings verbatim, which changes no behaviour and can be checked by a byte-identical packet. Then
rewrite them (D6) together with the tool surface (§4), so the text is written once for the final tools.

## 3. Problem-specific numbers: the price interface (D5)

**Problem.** Today the model must guess what a change is worth. The data exists: per-tactic heartbeats
(`arena/lean/profile.lean` → `arena/profile.py`), per-line tokens (`token_attribution`), and per-axis exchange rates
(`arena/scoring.py:38-56`). But it reaches the model only as a top-10 hotspot list and a 9.3 KB profile dump.

**Goal.** For any proof step or any edit, the model can read, from harness-measured numbers, how many tokens,
heartbeats and versions are at stake, and the net score change. No proof advice is given, only prices.

### 3a. Price table: in the packet, for the original, and on request for any node
One row per top-level step (a tactic block or term line):

```
step  lines   tokens  self_hb  incl_hb  versions  pts_if_gone   text (first 40 chars)
s1    3-5       14     1.2K     1.2K     5/5        +0.9        simp only [List.foldl, ...
s2    6-18      61    38.0K    41.3K     5/5        +6.8        induction l generalizing ...
total          212   120.0K              5/5   proxy 33.0
rates: 1 token = 0.124 pts · 1K hb = 0.081 pts · 1 version = 6.67 pts
```

- `pts_if_gone` is the upper bound on what that step alone can still earn. It is computed, not suggested.
- The table holds about 2 lines per step, capped by `numbers.yaml`. The text is in `packet/price-table.md`.
- The `text` column is the model's own proof text, so it is not steering. It is shown (D17).

### 3b. Price row on every compile reply
Each compiled draft returns one line comparing it with its measured parent and with the best:

```
n41 ← n37 (Δ 3 lines)   tokens 188 (−9 vs n37, −24 vs best)   hb 96.1K (+4.0K, −23.9K)   versions 5/5   Δscore +0.6 vs best
changed steps: s2 (61→52 tok, 41.3K→45.3K hb)
```

The model sees directly whether a token gain was paid for in heartbeats, and at what net.

### 3c. Instant quotes: token counts with no Lean
Token counting is pure Python (`arena/engine.py:46`), so it costs nothing and takes milliseconds.
- `compile` accepts `check: "tokens"`. For each draft or snippet it returns tokens and the Δ against the focus step,
  with no Lean run.
- The model can price ten phrasings of one step before compiling any. This addresses the guessing, and it is cheaper
  than a probe round trip of about 2 s of Lean plus a turn.

### 3d. Hole prices
Measured replacements at a hole, from the model's own snippets (`goal try`), each priced. Harness-run suggestion
engines were dropped after a negative probe (D30).

### 3e. Library prices (dropped, D41)
~~A `tokens` column on the ranked lemma list.~~ Dropped: the official counter scores any identifier as one token
(verified 2026-10-10: `Nat.add_comm_of_very_long_name_here`, `𝔽q` and `Nat.add_comm` each count 1), so the column
would be all 1s. The ranked top-60 library itself stays (D34).

### 3f. What is removed
- The 165K references.
- The generic syntax help.
- Any hardcoded "X costs N".

A small `skill/lean-facts.md` (well under 1K tokens) is kept only for facts the harness can't measure, such as the
forbidden `native_decide`. Its numbers are still rendered from the counter.

## 4. Tools: full analysis and the v7 surface

### 4a. What the agent must be able to do
The aim is to refactor a given proof using everything the pinned project offers: lemmas, theorems, tactics and
notation from the project, its dependencies, Mathlib and Lean core. No auxiliary declarations are allowed. The agent
needs four capabilities:
- **K. Know** what exists that it could use, including names it has never seen.
- **P. Price** any change it considers, in tokens, heartbeats, versions and net score, before and after compiling.
- **C. Compile** drafts, with all errors and the goals at holes.
- **G. Navigate the graph:** branch, merge, compare and plan (§5).

### 4b. Lean MCP server today
`lean-lsp-mcp==0.31.0` via `uvx` (`arena.ts:770`), registered as `arena-lean`. 5 tools are exposed and 17 are
disabled by `LEAN_DISABLED_TOOLS`. The stated reasons (WORKING-v6 decisions: 549-560) are that network search is
non-deterministic, builds and arbitrary code bypass the harness, and every tool adds a way to fail.

| Tool | Does | Net | v6 | Value here | v7 |
|---|---|---|---|---|---|
| lean_goal | Goals at a position | – | on | high | inside `goal` (node-relative addressing; #31 quirks handled) |
| lean_multi_attempt | Tries snippets at a line | – | on | high | inside `goal try`, priced |
| lean_diagnostic_messages | Errors in a range | – | on | med | inside `compile` replies |
| lean_hover_info | Type and docs at a position | – | on | med | inside `read` (`at:` position) |
| lean_local_search | Name or prefix search (workspace symbols) | – | on | med | inside `search` |
| lean_code_actions | Resolves TryThis edits (`exact?`, `simp?`, `apply?`) | – | off | **high** | inside `goal suggest` (§4d) |
| lean_completions | Dot-notation and partial-name completions | – | off | med | inside `search` (`after:` prefix), D20 |
| lean_declaration_file | Source of a symbol | – | off | med | already covered by `read` |
| lean_term_goal | Expected type at a position | – | off | low | inside `goal` (term positions) |
| lean_file_outline | Signatures in a file | – | off | low | `read view:"outline"` |
| lean_references | References to a symbol | – | off | low | off |
| lean_loogle | Type-pattern search | yes / local build | off | **high** | offline for now (D19); a local build per toolchain is optional |
| lean_leansearch, lean_leanfinder | Natural-language and semantic search | yes | off | med | later, if network is allowed (D19) |
| lean_hammer_premise | Premises at a goal | yes (http) | off | med | later (D19) |
| lean_run_code | Runs a snippet | – | off | low | off; the harness may use it internally |
| lean_verify | Axiom check and source scan | – | off | low | harness-internal (submission gate) |
| lean_minimal_hypotheses | Drops hypotheses and re-elaborates | – | off | low | off (the statement is fixed) |
| lean_profile_proof | `lean --profile` | – | off | low | off (our per-tactic profiler is better) |
| lean_build, widgets | Builds the project / widget data | – | off | none | off |

The MCP server becomes a backend that our tools call. The model no longer sees raw MCP tools, which removes the
file-line offset errors (lean_goal 7%), the "complete with no goals" quirk, and the invisible-to-scoring calls (#25a).

### 4c. Our tools in v6
Usage figures are from §1f.

| Tool | Finds / does | Gap |
|---|---|---|
| arena_find | Text scan of project and dependency sources (`campaign.py:423`) by exact leaf, prefix, substring | No Lean core (#18), no generated declarations, never by type |
| arena_declarations | Pinned bodies by name | Null for 7 of 8 core names. One bad name rejects the batch |
| arena_source | Lines by `decl:` handle or path | Core source reachable only if the path is known |
| arena_profile | Per-tactic heartbeats | 9.3 KB per call. Replaced by prices |
| arena_probe / evaluate / candidate / state / idea / skill_read / finish | See §1f | Folded or dropped (4f) |
| Packet library (`context.lean:286-365`) | Top 60 imported theorems by IDF-weighted constant overlap with the statement, goals and referenced names | Static, made once. One hop only (BACKLOG §1). Not driven by the goal. No token cost per name |

### 4d. Is search enough? No. Discovery in four layers, mostly our own index
Name and text search need the model to already know or guess a name. That fails on the vocabulary gap and on core
names (#18). Nothing exposed answers "what closes or shortens this goal?".

**Can we hand discovery off to existing tools?** Partly (§1i). Goal-directed suggestions go to Lean's own engines.
The index we own, because no external tool covers all our projects offline:
- Loogle local is about 13 GiB peak RAM per Mathlib index build and possibly indexes only Mathlib.
- LeanExplore has no ArkLib or Strata.
- LeanHammer and LeanSearch are remote.

The four layers, all measured and none advising:
1. **Declaration index, built per row and toolchain at provisioning (free at run time).**
   - `arena/lean/context.lean` already walks `env.constants` for the packet library. Extend it to emit every
     declaration visible from the proof's imports: name, pretty-printed type, module, head symbol and constant
     set, and the token cost of writing the name.
   - This covers Lean core and generated names (#18) and filters private and auxiliary declarations.
   - Cached by project commit plus toolchain, the same pattern lean-lsp-mcp uses.
   - `search` queries it in milliseconds:
     - `kind:name`: exact, prefix, fuzzy, and the confusable hint (#29).
     - `kind:type`: by head symbol and constant-set match. This is a light stand-in for Loogle.
     - `kind:text`: over the source, **backed by ripgrep** (`/usr/bin/rg` is installed). This replaces the Python scan
       capped at `MAX_SCAN_FILES = 30` (`campaign.py:551`). A trial matched a Mathlib theorem across every
       putnambench workspace in about 1 s. Harness-side only: the model sees `search`, not `rg`.
     - **ast-grep: not used.** No mature tree-sitter grammar exists for Lean 4, and `sg` on this machine is
       util-linux's, not ast-grep. Structural queries go through the declaration index (`env.constants`).
   - An optional embedding index over name plus type (about an hour on CPU for Mathlib, about 1 GB) waits for
     evidence that name and type search miss things.
2. **Packet (before turn 1).** The ranked library (no unfolding hop, D33) with a tokens column per name, and the
   price table of the original (§3a). Its size is to be justified by a library hit-rate check (§12e).
3. **~~Pre-run sweep~~ dropped (D30).** Probe result: 0 of 349 suggestions compiled. The design below is kept for
   the record.
   - For each step of the original, replace the step with a hole.
   - Run the local suggestion engines there, each capped in time and heartbeats:
     - `exact?`, `apply?`, `rw?`, `simp?`, `hint`;
     - `grind +suggestions` and `simp? +suggestions` on toolchains ≥ v4.26, where core ships a premise selector.
   - Compile the replacements that come back.
   - The packet lists the ones that compile, with measured Δtokens, Δheartbeats and versions.
4. **~~`goal suggest`~~ dropped (D30).** `goal try` with the model's own snippets, priced, remains.

**Optional later:**
- A real local Loogle, for unification-based type patterns, if layer 1's head-symbol match proves too coarse and
  the RAM fits beside the Lean workers.
- Remote search, later (D19).

**Phase 0 checks (Lean only):**
- Which engines exist and behave the same on v4.25–v4.33.
- Their heartbeat cost on Mathlib-sized imports (`exact?` often exceeds 200K).
- Whether `+suggestions` prints usable names.
- The size of the index dump per row.

### 4e. Pricing a change: one interface, everywhere
Every reply that contains proof text carries its price. Wording lives in `agent-text/replies/`.

| Need | How | Cost |
|---|---|---|
| "How many tokens is this phrasing?" | `compile check:"tokens"`: drafts or snippets, Δ against the focus step, no Lean | ms, free |
| "What does this edit really do?" | `compile`: the price row against the measured parent and the best (§3b) | about 2 s of Lean |
| "What does each step of node X cost?" | `read node:"nX" view:"prices"`: the price table (§3a) | cached |
| "What could replace this step, and at what price?" | `goal suggest` / the pre-run sweep | Lean only |
| "Is it worth it?" | Every price row ends with Δscore from the per-axis rates (`arena/scoring.py:38-56`). Break-even is a sign, not a judgement | free |

### 4f. v7 surface: 5 model tools, one reply schema
Reply schema: `ok`, `facts` (short lines), `items` (per draft or per name, each with its own error), `handles`, and
the footer.

| Tool | Replaces | Key parameters |
|---|---|---|
| `compile` | probe, evaluate, candidate, profile, idea | `drafts` (1–4) with optional `base`; `splice {base, steps, text}`; `fill {hole, text}`; `merge {base, take}` (§5b); `check: "tokens" \| "lean"`; `from` (named parent); `note` (D16). Returns per-draft results as each finishes (#25b), all errors (#9), goals at holes, the price row, node id and status, deduplicated diagnostics (#10), and cross-version results that land during the call (#17) |
| `goal` | lean_goal, lean_multi_attempt, lean_term_goal | `node`, `hole` or a node-relative line; `try: [snippets]` (priced) |
| `search` | find, declarations, lean_local_search, lean_completions | `queries`; `kind: name\|type\|text` over our declaration index (§4d); dot-notation completions (D20); returns handle, signature preview, tokens, location |
| `read` | source, skill_read, state, hover, outline | `handle`, `node` or `hole`; `view: source\|prices\|diff\|outline\|map`; `against:` for a diff |
| `finish` | finish | Registered only when ≤10% is left (D15). Assumes Pi's `setActiveTools`, to be checked in phase 0 |

Graph operations (fork, edit, fill, merge, compare) are modes of `compile` and views of `read`, not separate tools (§5b). Operations are the primary, exact lineage; a free-text draft is filed under the focus.

**Ships only if measured** (BACKLOG §5b-7): same rows, same model, $0.50 cap. Bookkeeping share, tool errors per run
and calls before the first compile must fall, with no loss on the proxy.

## 5. Candidate graph v7: the agent writes, the harness keeps the books and steers (D7)

### 5a. What v6 shows
Scripts: `research/v7-probes/graph_audit.py` and `bigedit.py`. Committed with the other probe scripts and reports in `research/v7-probes/`
(the scripts still write their outputs under `runs/analysis/experiments/`).
- **Models plan graph moves in their reasoning but don't express them through the tools.**
  - DeepSeek and Qwen named a parent in **0 of about 840** probe calls; all 120 named parents were Luna.
  - The reasoning holds 69 forks ("variants based on #9"), 39 returns ("fall back to #10") and 28 merges
    ("combine #13 + #14's h_fiber_diff").
- **Merges were retyped by hand and their edges lost.** `merge_text` exists in `arena/graph.py` but is not exposed.
- **Restores were used to inspect,** not to branch: 36 calls such as "restore p6 to read diagnostics".
- **Labels are mostly wrong.** The label agrees with the text-closest parent 41% of the time. Batches share one
  parent (a4: 385 of 411 siblings).
- **Ideas carry no information.** About 99% of nodes carry the active idea by default.
- **Big edits fail.** 642 real drafts on 10 large-row runs:

| Lines changed | n | compiles | spend share |
|---|---|---|---|
| 1–3 | 375 | 69% | 37.8% |
| 4–10 | 139 | 57% | 20.0% |
| 11–30 | 72 | 39% | 12.0% |
| >30 (median 90% of the proof) | 56 | **23%** | 14.4% |

  - A large success costs 3.8× a small one ($0.0158 against $0.0042).
  - Long failure streaks are small patches on a big uncompiled draft. In interleaved: 10 failing 170-line rewrites
    in a row, first error at lines 16, 16, 16, 19, 19, 19.
  - The first error repeats in 52% of consecutive failures. This is a lower bound, because only the first error is
    reported (#9).
  - 83% of draft text is re-sent unchanged. That is under 17% of output tokens, since reasoning is 78% of output.

**Conclusion.** Two-way bookkeeping by asking the model does not work. v7 makes the agent → harness direction a
by-product of the content: the harness measures it. The harness → agent direction becomes facts plus structural
steering.

### 5b. Agent → harness: lineage by construction, measurement only as an audit
**Replay verdict: no text method recovers what the model meant**
(`lineage-v6.md`, `lineage-v6-v2.md`; 20 runs, 1,791 nodes). Ground truth is Luna's 129 explicitly named parents,
31 of which were not the current node.

| Method | Agreement with Luna's named parent |
|---|---|
| step-hash, origin = earliest node (v1) | 20.2% |
| step-hash, length × IDF weighted (v2) | 39.5% (14 abstain) |
| difflib over the 20 most recent nodes | 47.3% |
| difflib argmax (graph_audit) | **48.1%** |

- Merges are undetectable from text: 0 of 8 "combine" mentions are confirmed.
- Forks are confirmed 29.6% of the time against an 8.2% base rate: a signal, but a weak one.
- Disagreement is not all error. Restores and deliberate recombinations look textually like something else.
- **Conclusion: lineage cannot be inferred. It has to be given, as a by-product of a functional input the model
  needs anyway.**

**v7 rule.**
1. **Operations are the primary lineage, and they are exact.** The model refers to a node because the operation
   cannot run without it. These are inputs that produce text, not bookkeeping fields:

| Operation | Use | Why the model uses it |
|---|---|---|
| `compile splice:{base:"n20", steps:"s4-s5", text}` | edit a region | it sends only the region (83% of draft text was re-sent in v6) and reuses the compiled prefix |
| `compile fill:{hole:"n30.h2", text}` | solve one hole | the only way to work on a salvaged sketch (§5f) |
| `compile merge:{base:"n13", take:[{from:"n14", step:"s3"}]}` | combine | the harness builds the text, so nothing is retyped |
| `compile base:"n9" drafts:[…]` | variants of a node | splice-style diffs against n9 |

2. **A free-text draft with no operation is filed under the focus,** and the reply says so in one line: "n51
   filed under focus n41 (text similarity 0.93)". If its similarity to the focus is below a threshold, it is filed
   as a new root: "n52 filed as new root (closest n12, 0.41)". The focus is explicit and harness-set at stalls
   (§5e), so "filed under focus" is an honest statement, not a hidden default. The batch's best becomes the focus
   after a batch (#5a).
3. **The model's optional `from`** is kept as `named_parent`. Measured lineage (difflib-recent) is stored as
   `measured_parent`. Both are audit signals for analysis and the viewer, never inputs to any rule.
4. **The reply echoes the filing** (`n44 ← n30 fill h2`, `n51 ← focus n41`), so the model always knows where its
   draft went and which ids it can reference. Ids appear in every reply, the map and `read node:`.

**Open risk.** DeepSeek and Qwen used 0 bookkeeping fields in v6. Whether DeepSeek and MiMo adopt `splice` and
`fill` when those are cheaper is unknown. `arena replay --render v7` (§7a) can show the v7 replies on old runs, but
only a paid run shows adoption. That goes into the phase 5 measurement (operation share of compiles).

### 5c. Core model
- **One node type.** Every compiled draft is a node: `closed` / `sketch` (has holes) / `broken`, plus score per axis
  and results per version. Duplicates are merged by hash (#45).
- **Holes are first-class.** `n30.h2` has its goal, its status (open, or filled by nX) and its fills.
- **Typed edges in one append-only log:** `edited_from`, `merged_from` (with the steps taken), `filled_from`,
  `salvaged_from` (5f), `filed_under_focus`, plus the audit fields `named_parent` and `measured_parent`. Each edge
  says whether it is exact (made by an operation) or a filing.
- **Focus is separate from lineage.** Lean reads any node by id, so restore-to-inspect disappears. The focus is only
  the default base for `splice`.
- **Routes are internal**, computed synchronously at compile time from proof shape (§5j), as the harness's map for
  archive cells and parent selection (5e). They are not a model-facing concept (#5, #32).
- **Declared ideas are dropped** (D16). An optional `note` on a node remains for the model's own memory.
- **Built (ticket 10a, 2026-10-13):** `arena/steps.py` splits a proof into top-level steps `s1..sK` (a term-mode proof
  is one step); `graph.splice_text` / `merge_steps` (a merge take replaces the base's step with the **same** id).
  The ledger gains `edge` (one per distinct proof text, written after its compile result) and `focus` (`start`,
  `batch_best`, `restore`) events; `Graph.from_history` projects stable `n1..nK` ids, status and depth. A free-text
  draft is `filed_under_focus` at similarity ≥ 0.50, else a non-exact `root`; every draft of a batch files under the
  focus as it was before the batch, and the batch's best non-broken node becomes the focus. Operations (`draft`,
  `splice`, `merge`) reach Lean only through the hidden protocol action `operation`; old tools reply as before. Note
  for 10b: `Graph.from_history` re-splits every node's steps on each filing, focus settle and `graph_state`, so
  per-step goals should be cached rather than recomputed there.
- **Built (ticket 10b, 2026-10-13):** `arena/step_goals.py` plus the Lean wrapper `arena/lean/steps.lean` record the
  goal state before each top-level tactic (`before`; `after` is the next step's `before`, `None` after the last step).
  `autocheck` drains the full checks first, then one background-lane `step_goals` job per closed or sketch node,
  queued from the ledger; a failure is an `error` event, so the queue moves on. `Graph.from_history` only joins the
  events. Ticket correction (reviewer): the fixture's `s1` is `intros Hup Hinit`, so `Hup` appears in `s1`'s
  `after`, not its `before`. Quick gate: 0 regressions. `tests/test_lean_speed_gate.py` measures every baseline row
  and toolchain, so it is the full gate (about 25 min, silent under `-q`) and runs after 12 with it. Watch in the
  first campaign: every closed or sketch node now costs one background Lean job (60 s limit).

### 5d. Harness → agent: what the agent sees
The agent never has to remember the graph. Each compile reply (when changed) and `read view:"map"` carry a compact
map. Row formats live in `agent-text/replies/map.md`.

```
best     n41 84.9 (tok 188 · hb 96.1K · 5/5)
archive  A n19 82.0 · B n41 84.9 · C n30 sketch (2 of 3 holes filled)        ← best per region of the graph
recent   n42 ← n41 edit   discard  83.7
         n43 ← n30 fill   h2 filled
effort   step   at stake   variants  best Δtok   last gain
         s2     +6.8 pts   14        −9          n37 (5 nodes ago)
         s5     +3.1 pts    0        —           —
         s7     +2.4 pts    3        +0          never
open     n30.h1  n30.h3
```

- **Archive:** the best node per cell, with cell = (route, depth bucket 0–2/3–7/8–15/16+, closed or sketch) (D27).
  Archive probe (`archive-v6.md`, 1,791 nodes):
  - median 9 cells and at most 12, within the map target in 20 of 20 runs;
  - the final best is kept in 20 of 20 runs;
  - the top cell holds 35% of nodes, against 77% for v6 routes;
  - the route part never splits on a ≤3-line edit.
  The leading-axis variant was unstable (0.49) and over the cell target in 9 of 20 runs.
- **Effort table:** per step of the best, the points at stake (`pts_if_gone`), how many variants have been tried, and
  when that step last improved. It says where effort has gone and where it hasn't, in numbers only.
- **Open holes:** sketch holes with no closing fill.
- **Status per node** (keep / discard / broken / filled) is autoresearch's ratchet as information, not a lock.

All of it is position and numbers. Nothing names a kind of proof.

### 5e. Harness → agent: structural steering by events (D22)
Research (§1j) agrees that weak models do not steer their own exploration well, and that diversity is best enforced
by the system choosing where work resumes:
- FunSearch islands;
- AlphaEvolve and MAP-Elites archives;
- DeepSeek-Prover V1.5's novelty reward with resume from any prefix;
- the coverage reweighting in "Beneath the Diff".

A context reset alone does not escape repetition. It must come with a different starting node.

**Replay evidence** (`research/v7-probes/phase-v6.md`; 19 runs, 10 with spend timestamps, nearly all
DeepSeek):
- **Bests come late.** 8 of 10 runs found their final best at 88–99% of spend. b2 at 78%, a4 at 30%.
- **Most points come early.** The best proxy as a share of the final (medians): 88% at 30% of spend, 98% at 75%,
  100% at 90%.
- **Gaps between keeps are short.** Median 1 node, p90 5, max 43. In dollars: median $0.009, p90 $0.034.
- **Waste after the last keep.** a4 spent 70% ($0.32) after its last keep.
- **Stall rule, scoped to the lineage subtree of the last keep:**
  - m=12 or m=16 would have cut 1 non-final keep (b2) and **no final bests**, out of 19 runs.
  - m=8 cuts 4 final bests.
  - The any-node version cuts finals even at m=12.
- **Fixed shares would have hurt.** First scores arrived only at 31–32% of spend in two runs, and deepening keeps
  paying until the end.

**Proposal: event-driven focus moves, not fixed phase shares.** At each event the harness sets the focus and says
so as a fact.

| Event | Focus chosen by the harness |
|---|---|
| start | the original (and the pre-run sweep's results) |
| first closed node | stays with the model's work. Exploring is the model's choice until a stall |
| **stall**: no keep in the last **12 nodes of the last keep's lineage subtree** | another archive cell's best node. **Which cell is unvalidated** (see below) |
| every hole of a sketch filled | auto-assembly (§5g), reported |
| reserve (≤10% left) | the finish window and final verification. Recombination runs on the pool |

- No depth cap: b2's best was at recorded depth 46.
- **Where to move is not validated.** The archive probe (§5d) tested "least-visited cell first". On the two strict
  tests ("a later keep is text-closest to" or "lands in" the picked cell) it did **no better than random**: 3% vs
  11% and 6% vs 11% at m=6, on 32 firings. History cannot answer this, because v6 never moved the focus; it only
  shows where the model went by itself. So *when* to move (lineage stall, m=12) is supported by data, and *where* to
  move is an A/B in phase 5: (i) the best other cell by proxy, (ii) least-visited, (iii) no move, only the map.
- m and the cell order are settings for the outer loop (§6). m=12 is backed by one mostly-DeepSeek sample, so it
  must be re-checked on MiMo.

- **The phase notice is one fact line**, e.g. "Focus set to n19 (archive A, 82.0, 4 nodes in its region)". The model
  may work anywhere: the focus is a default, not a lock. Wording lives in `agent-text/messages/phase.md`.
- **Optional fresh context at a stall move** (packet + map + focus node, no chain history) fights anchoring. Prompt
  caches match prefixes, so a fresh session sharing the system, tools and packet bytes should hit the cache. That is
  unverified for DeepSeek and MiMo (§9a), so it is measured as an experiment, not assumed. Parallel islands sharing
  one graph are the stronger version (D22).
- **Finish fits.** The ≤10% rule is the reserve. The finish tool appears when the reserve starts (D15).

### 5f. Big edits: a failed big draft becomes a sketch, not a waste
- **Salvage.** When a draft fails, the harness runs the sorry-replacement passes (#9): it replaces each erroring
  step with `sorry` and re-elaborates. If the result elaborates, it is recorded as a **sketch node** (`salvaged_from`
  the failed draft), with one hole per failed step and the goal at each. The reply says: "n44 salvaged: compiles
  with 1 hole (h1 line 16)".
- **Replay v1** (`salvage-v6.md`; 37 failed v6 drafts, 526 s of Lean in all):

| Change size | n | salvaged | median holes | median steps kept | median Lean s |
|---|---|---|---|---|---|
| 1–3 | 7 | 29% | 1 | 83% | 23.8 |
| 4–10 | 10 | 40% | 1 | 73% | 7.1 |
| 11–30 | 10 | 40% | 1 | 83% | 8.9 |
| >30 | 10 | **50%** | 1 | 75% | 4.2 |

  - 41% of all drafts were salvaged. A salvaged big draft typically keeps about 75% of its steps with **one hole
    left**: exactly the small-edit situation where success is 57–69% (§5a).
  - **Most failures (19) were "no progress".** The error sits on a step header (`have h : T`, `cases … with`,
    `calc` relations) or in a dependent step, so more rounds don't help.
- **Replay v2** (`salvage-v6-v2.md`; same 37 drafts, 114 compiles, 694 s, median 4.1 s per compile): a chain of
  - finer nested replacement (S2);
  - header-aware `have h : T := sorry` (S3);
  - escalation to the parent block (S4);
  - up to 6 compiles per draft.

| Strategy | salvaged | 1–3 | 4–10 | 11–30 | >30 | holes | kept |
|---|---|---|---|---|---|---|---|
| v1 (top-level step) | 41% | 29% | 40% | 40% | 50% | 1 | 80% |
| **v2 chain S2→S3→S4** | **54%** | 57% | 50% | 50% | 60% | 1 | 78% |

  - 75% of salvaged sketches have every hole under 300 characters (a text proxy, since goal states were not
    extracted), so they are fillable by small edits.
  - The v2 chain is the v7 salvage rule. 11 drafts still end with no progress. The real info-tree goals in the v7
    compile (§5g) should replace the indentation heuristic.
- **Fill, don't re-send.** The model fills holes one at a time (`fill`, small-edit success rates of 57–69%).
  Auto-assembly (5g) completes the proof when every hole has a closing fill.
- **All errors at once,** each with its goal (#9). This removes the "fix one, discover the next" loop behind the 52%
  repeat rate.
- **Repeated-failure fact.** "3 drafts in a row fail at the same step (n44.s3), same error." A number, not advice.
- `splice` cuts the re-sending (83% of draft text, up to 17% of output) as a side benefit.
- **Built (ticket 12, 2026-10-13):** `arena/salvage.py` (hole scan, fills and their cost, the S2→S3→S4 salvage chain,
  at most 6 background compiles per failed draft), the `fill` operation with `filled_from` lineage, open-hole map
  rows, and auto-assembly (each hole's cheapest closing fill; origin `assembly`, an ordinary candidate). A salvaged
  sketch is a `probe` event, so it shifts later `pN` labels (allowed by the ticket; the model can restore it). Review
  fix: the end-of-run drain (`closing`, 300 s) ran salvage and step goals before full checks and could leave the best
  candidate unverified; closing now runs full checks, then assembly, and skips salvage and step goals. Background
  events (`step_goals`, `salvage`, `assembly`) record `seconds` for ticket 20's load report. **Full gate after 12
  (D35): 0 regressions on all 7 toolchains**, against a baseline in which every row now carries its clock: ArkLib
  re-recorded on ticket 07's code plus the CPU logging and the orphan wait (`patch -p1`; 2600-2800 MHz). Putnam's
  reference was -16% clock-adjusted at a matched clock (2900 vs 2800 MHz), closing the 08b question.

### 5g. Harness work the agent doesn't pay for
- **Auto-assembly.** When every hole of a sketch has a closing fill, the harness assembles and compiles the full
  proof and records a `merged_from` node. With several closing fills it takes the cheapest (D21).
- **Recombination** (BACKLOG §3, D13).
  - Hybrids were worth **43.58 points** in v3, and every one was **cross-run** (§1k).
  - So recombination works on a **theorem-level pool**: the nodes of every run on that theorem, not one run's graph.
  - Steps are aligned by subgoal (the goal state at the step boundary), not by a common ancestor. This replaces
    `merge_text`'s 3-way merge, which needs one.
  - **v6 did not store goal states at step boundaries,** only the final goals and errors (§5j replay). The v7
    compile must record the goal before and after each top-level step for every node, from the info tree of the
    compile we already run. The machinery exists: the packet already shows the "goal before each top-level tactic
    of the reference proof" (`arena/context.py:607`). v7 runs it for every node (phase 3). Until then, cross-run
    alignment falls back to step position plus step hash.
  - The harness swaps a step of the best for a cheaper step from any pool node at the same subgoal, then compiles.
  - Inside a run, the results are ordinary nodes inside the budget. Across runs, `arena submit` runs the same
    recombination as a recorded, reproducible step. Lean time only, no model spend.
  - The `auto_merge` exclusion in `submission()` is removed.
- **Transfer.** When a step improves in one region, the harness tests the same step in the other archive nodes where
  it fits.
- Every harness-made node appears in the map as `harness` with its result. The agent's work improves the graph, and
  the graph's results feed the agent's next move.

### 5h. Finish without credit (D28)
- v6 used route "credit" to gate `finish`. v7 gates `finish` only by the ≤10% rule (D15), and the tool appears at
  that point. No credit is computed, so BACKLOG §4b (shallow-branch credit) is moot. The named and measured parents
  stay audit fields (§5b).
- At finish the model sees the archive line plus per-axis points left, capped (#36).

### 5i. First, free
1. Lineage replay: **done.** v1 and v2 both fail as primary lineage: at best 48% agreement with Luna's named parents (§5b). Lineage comes from operations instead.
2. Paper test: **done.** Forks are confirmed 29.6% of the time against an 8.2% base rate. Combines: 0 of 8. Merges must be an operation.
3. Salvage replay: **done.** v1 41%, v2 chain 54% salvaged, median 1 hole, 75% with small holes, no size dependence (§5f).
4. Phase replay: **done** (§5e). Fixed shares are rejected; a lineage stall at m=12 cuts no final best in 19 runs.

D27 (archive key) rests on the archive probe. Hand labels are dropped (D29). D23 (salvage) rests on the salvage replays.

### 5j. Routes in v7: what sets them apart
**v6 flaws** (replay in `research/v7-probes/routes-v6.md`):
- **Vocabulary fingerprint.** Lemmas 0.45, recursion 0.25, claims 0.20, logic 0.10. Lemma swaps open "new" routes.
- **Hard 0.5 threshold against a fixed exemplar.** Two drafts one line apart scored 0.514 and 0.495, so r2 took 75
  of 77 attempts (#25c).
- **Over-splitting.** a4 replays to 316 routes over 412 nodes, and only 1.7% of pairs within 3 lines share a route.
- **Binius runs got 0 credited routes,** because extraction failed and the error was swallowed (`campaign.py:893`).

**Why routes arrived late (#5), root cause:**
- One detached serial worker (`_route_worker`, campaign.py:947) runs a **cold Lean extraction** per attempt (120 s
  timeout, cold module import).
- Before each extraction it does **two unlogged infinite memory waits** (`_yield_to_lean_session` at 964 and
  `_room_for_extraction(wait=inf)` at 965/1002-1014), behind a shared `ROUTE_SLOTS = 2` lock.
- One stall queues every later attempt. That matches the 12-minute stall and the "r3 · 1 attempt" shown while 11
  to 15 attempts were assigned.
- Results reach the model only through the ledger, so nothing arrives until extraction finishes.

**v7 definition (replay-backed).** A route is **proof shape under small edits**.
- **Signature.** A 50/50 mix of the step skeleton (the sequence of top-level tactic heads with arguments
  abstracted) and the Jaccard similarity of normalized step hashes. No lemma names, so it is content-neutral, and
  the model never sees it.
- **Assignment** with hysteresis, single link to any member:
  - join at similarity ≥ 0.60;
  - open a new route below 0.35;
  - in the grey band, stay with the parent's route unless the best beats the runner-up by 0.10;
  - an edit of 3 lines or fewer from its parent never opens a route.
- **Synchronous and frozen.** Computed in Python at compile time (about 6 s for all 21 runs in the replay), with
  no queue, worker, Lean or memory wait. Once filed, it never changes. Optional Lean enrichment (kernel or subgoal
  data, BACKLOG §2) is a secondary label only.
- **Replay results** (means over 21 v6 runs):

| Signature | routes median / max | stability under ≤3-line edits mean / min |
|---|---|---|
| v6 fingerprint | 2 / 316 | 0.92 / 0.017 |
| skeleton only | 1 / 3 | 0.996 / 0.954 (too coarse) |
| step-hash Jaccard only | 5 / 17 | 0.974 / 0.80 (splits on renames) |
| **50/50 mix (chosen)** | **3 / 4** | **0.991 / 0.85** |
| final goals only | 16 / 347 | 0.48 / 0.011 |

- **Archive cell** = (route, depth bucket, closed or sketch) (D27, §5d). Each cell keeps its best node. Which cell a
  stall move picks is an A/B (§5e).
- **Caps.** At most about 12 routes per run; beyond that, the closest pair merges. Every assignment logs its
  similarity and the runner-up.
- **Validation by outcome, not labels (D29).** Separation of v6's distinct routes is low (0.21). v6 often split on
  lemma choice, which a neutral signature should not separate, so this is expected. Routes only shape the archive
  cells, whose probe passes (§5d). Phase 5 checks attempt diversity.
- **Built (ticket 11, 2026-10-13):** routes are assigned synchronously in `_file_node` from the 50/50 signature
  (`routes.signature`, `routes.assign`); the Lean route extraction (`route_features`, `route.lean`, the route worker
  and queue) is deleted, and the three model-facing "routes are fingerprinted" clauses are gone. Archive cells, the
  hidden `map` action and the stall detector are in `arena/graph.py`. Reviewer decisions: (1) a fire is a pure
  function of the node sequence (the counter resets on every fire, moved or not); every new fire appends an audit
  `{"kind":"stall","root","count","mode","target"}` that nothing reads, so `map_only` and no-target fires stay
  measurable for the A/B; only a `focus` event with reason `stall` renders the fact line. (2) Equal quality (or
  visits) breaks by the lower cell letter and still moves; no move only when the target already is the focus. The
  old tools still default to `_current`, so the stall line is information only until 15a.

## 6. Outer loop: autoresearch for the harness itself

- **What it is.** A harness change (a template edit, a tool change, a constant) is an experiment. It is kept only if a
  fixed evaluation set at a fixed cap improves beyond noise.
- **Tuned settings include** the stall length m and the cell order (§5e), the salvage replacement strategy (§5f), the route thresholds (§5j) and the map size.
- **Log.** `runs/harness-results.tsv` with columns commit (#19), change, rows, replicates, mean proxy, spread,
  bookkeeping share, tool errors, and keep/discard.
- **Variance first.** No change can be judged until run-to-run spread is known. Autoresearch itself reports none.
  This needs a paid replicate set, which the owner launches.
- **Held-out rows.** Tune on one set of rows and confirm on another. This guards against the overfitting and
  best-of-many bias the follow-up papers report.
- **Text as data.** Because §2 puts every word in `agent-text/`, a prompt change is a reviewable diff with a measured
  outcome.
- This is a process plus a CLI command (`arena experiment`), not an autonomous agent. Paid runs stay owner-launched.

## 7. CLI, packaging and repo layout (D1)

### 7.0 Packaging
- **uv project, flat layout.** `pyproject.toml` at the root with:
  - package `arena` (it stays at `arena/`, not `src/`);
  - `[project.scripts] arena = "arena.cli:app"`;
  - `requires-python = ">=3.13"`;
  - runtime dependencies `cyclopts` and `rich`; dev group `pytest`.

  Why flat: the code locates `benchmark/` and `vendor/` through `Path(__file__).parents[1]`, and a `src/` move
  breaks that for no gain. `tools/*` folds into `arena/cli/`. `engine.py:89`'s `from tools.arena_check import …`
  moves into the package.
- **Vendor code stays import-by-path,** isolated in one `arena/vendor.py`:
  - `scoring.py`'s `sys.path` insert for arena-space;
  - `engine.py:27`'s `spec_from_file_location` for the lean-refactor token counter.
- **TypeScript: plain node, not bun.**
  - Pi loads `.ts` directly through jiti ("no separate compilation step", Pi `extensions.md:38`) and needs
    node ≥ 22.19.
  - The tests already use `node:test`, and node 26 strips types natively. So `node --test
    packages/arena-pi/extensions/*.test.ts` runs on the same runtime as production.
  - No third-party dependencies, so no lockfile. Add a `test` script to `package.json`. The `bun test` mention
    in `docs/H1.md` is stale.

### 7.1 Command tree (Cyclopts, Rich output, `--json` on every reporting command)

| Command | From | Verdict and changes |
|---|---|---|
| `arena run` | run_pi_budgeted.py | keep. Loads `.env`, generates Pi `models.json` from `models.yaml`, records code version (#19), one `--limit-usd` (#39) |
| `arena campaign` | run_campaign.py | keep. Drop the reservation plumbing (D8). `--check` runs the real gates with no model call (#20). Lock, `--jobs` and memory recorded (#40) |
| `arena certify` | arena_certify.py | keep. Rich progress, write and catch errors per row (#40) |
| `arena eval`, `arena check` | arena_eval.py, arena_check.py | keep. `FORBIDDEN` and `remove_comments` move into the package |
| `arena submit` | arena_package.py + `arena/package.py` + the hand scripts in `runs/analysis/submission-v*` | **new.** BACKLOG §6: multi-run selection, gates, cross-run recombination (§5g), manifest, diff with the previous submission. Output to `runs/submission/<name>/` |
| `arena replay` | – | **new** (§7a) |
| `arena serve`, `arena graph export` | serve_candidate_graph.py, build_candidate_graph.py | keep and merge. Read the local journal first (§7b). `graph_viewer/` becomes package data |
| `arena provision [--progress]` | provision_workspace.py + provision_progress.py | merge. Refuses while a campaign holds the lock (#21) |
| `arena lean serve\|health\|load-test` | lean_session.py `serve`, lean_health, lean_load_test.py | keep. `load-test` grows into the §9b benchmark |
| `arena experiment` | run_experiment_matrix.py | merge into the outer loop (§6) |
| `arena merge` | arena_merge_worker.py | keep, rebuilt on step alignment (§5g) |
| `arena preflight` | arena_preflight.py | keep. Local journal first, Langfuse optional |
| `arena doctor` | langfuse_plugin.py + new checks | **new.** Pins, vendor submodule commits, `warmup.jsonl` hash, Pi version, price test (§2d), optional Langfuse plugin patch |
| `arena text render\|budget` | – | **new.** Renders `agent-text/` and prints the word-budget table (§2b) |
| `arena smoke` | smoke_theorems.py | keep, or move into pytest |
| `arena protocol` (hidden) | arena_campaign.py | keep the JSON contract for the Pi extension. Drop the budget flags |
| – | arena_skill.py | **delete** (lean4-skills references replaced, §3f) |
| – | route_validation.py | **delete** (routes are synchronous, §5j). Its stale `submission/*.lean` glob goes too |

### 7.2 Repo housekeeping
- **`submission/`.** It holds only a README: a checklist for the first manual upload. No code reads it, and the
  real work happened in `runs/analysis/submission-v1..v3`.
  - Delete it.
  - Move the checklist (provenance fields, the Nov 1 and Nov 8 dates, track eligibility) into `docs/` and into
    `arena submit --help`.
- **`benchmark/`.**
  - Keep `original/warmup.jsonl` (15 rows: statements, original proofs, version pins; read by `engine.py:26`,
    `arena.ts:757`, `provision_workspace.py:31`, `run_pi_budgeted.py:253`) and `derived/workspaces.tsv`.
  - `SHA256SUMS` is never checked; `arena doctor` verifies it.
  - `tooling-pins.txt` is read by nothing; fold it into `models.yaml` or pyproject.
  - Delete the two research-note files.
  - `engine.py:120` points at a `measure-versions.json` that doesn't exist. Confirm it is an optional override.
  - `vendor/arena-space/benchmark_data_warmup.jsonl` duplicates the row data. Scoring denominators come from there.
- **`vendor/`.** All three are git submodules. **arena-space and lean-refactor both come from the organizers**
  (`delta-lab-ai`: the HF Space `delta-lab-ai/lean-refactor-arena` and GitHub `delta-lab-ai/lean-refactor`).

| Vendor | What we use | Upstream since our pin | v7 verdict |
|---|---|---|---|
| arena-space (d9e46ee → 56aa7b8) | `scoring.py`: reference denominators (`benchmark_heartbeats.jsonl`, `benchmark.py`), `leaderboard.py`, the row data. The forbidden list is our own copy | prize and UI copy only. No scoring, filter or leaderboard change | **keep. Bumped to 56aa7b8 on 2026-10-10** (uncommitted submodule pointer). `scoring.py` still imports |
| lean-refactor (9c98a3a → a2372ca) | **the official token counter** `_proof_length` (`engine.py:27`) | (1) **`util/heartbeat.py` and `cc_agent/tools/heartbeat.py`: the organizers' heartbeat method**, `set_option Elab.async false in` + `#count_heartbeats in <decl>`, with `set_option maxHeartbeats 0` rewritten to `400000000` (because `#count_heartbeats` never ends at 0). (2) `check_proof.py` rejects `sorry`/`admit`/`sorryAx` as INCOMPLETE_PROOF. `_proof_length` is unchanged. (3) A multi-objective golfing mode with prompts (`prompt_golf_multi_obj.txt`, `*-multi-obj.md`) | **keep. Bumped to a2372ca on 2026-10-10** (uncommitted). The new `check_proof.py` imports its sibling `heartbeat` module, so `engine.py` now puts the checker's folder on `sys.path` before loading it (a 3-line fix, owner-approved; it moves into `arena/vendor.py` in phase 1). Token counts were identical before and after, and `tests.test_engine` passes. Upstream `_proof_length` was verified to match the official `proof_length` on **15 of 15** rows, the same as our pin. Test their heartbeat method against our `HEARTBEAT_WRAPPER` on all 15 rows, the likely cause of the Putnam mismatch (§1l). Our wrapper uses `IO.getNumHeartbeats` around `elabCommand` with `maxHeartbeats 0`. Read the multi-objective prompts as input to the text rewrite (§2): ideas only, nothing copied verbatim |
| lean4-skills (b6243b8, = upstream HEAD) | only `tools/arena_skill.py`, which copies 2 reference files into the skill | nothing new | **remove** with `arena_skill.py` and the copied references (§3f) |

  Option to slim down: instead of whole submodules, vendor only the files we import (`check_proof.py`,
  `heartbeat.py`, `benchmark.py`, `leaderboard.py`, the two JSONL data files), with a pinned commit and an `arena
  doctor` check against upstream. Decide at phase 1.
- **Forbidden filter.** The harness uses its own copy (`tools/arena_check.FORBIDDEN`, imported at `engine.py:89`),
  not `app.py`'s. Upstream did not change it, but phase 6 adds the parity test anyway (BACKLOG §6).

### 7a. `arena replay`: what the model saw (D11)
**Existing data is enough for v6 runs** (verified on v6ark2 FieldSpecification r1):
- `trace-journal.jsonl` holds, per turn:
  - the `request` payload (system prompt, skill as the `<addendum>`, 16 tools, messages with reasoning);
  - the `wire` bytes, byte-exact and checked by sha256 on 91/91;
  - the `response` (thinking, usage, cost);
  - the `tool_call` and `tool_result` rows. Each `tool_result` has the delivered `result`, with trim and footer,
    and the untrimmed `text`.
- `arena.traces.read_journal` restores the delta compression.

**Command.** `arena replay <run-id> [--turn N] [--node nX] [--raw] [--json]`
- Rich panels, in order: run config, system prompt, skill, packet, tools table, messages up to turn N, each tool
  result as delivered (with a trim diff against the original), then that turn's thinking, response and cost.
- `--node` resolves the node to its tool call and then to its turn.
- `--raw` prints the exact request bytes.

**Gaps today:**
- Ledger rows carry no call id. A time window joins them: 60/60 nodes matched with no ambiguity, but a batch call
  creates several nodes, which must be ordered by time.
- The skill and system prompt exist only inside each payload copy.
- Runs from before the journal (v5) cannot be replayed.

**v7 records:**
- A content-addressed `blobs/<sha>` store for the system prompt, skill, tools and packet, referenced by hash from
  each request row. This also shrinks the 13.6 MB journals.
- A turn index on every row.
- `tool_call_id`, `request_id` and turn on every ledger and node event, so the join is exact.
- Trimmed text and footer as separate fields.
- With `arena-guard` deleted (§2d), the request row comes from Pi's `before_provider_request` and the response from
  `after_provider_response`. The post-hook payload is the record (D24). It differs from the wire bytes only by SDK
  stream flags.

**Replay of v7 surfaces on old runs.** `arena replay --render v7 <run> --turn N` renders what the v7 packet, map and
replies would have shown at that turn, from the same ledger. This tests text changes (§2) against history before
any paid run.

### 7b. Viewer: reasoning and tool calls per node (D12)
- **Today.** The node panel (`tools/graph_viewer/app.js:400-462`) shows facts, the `hypothesis` labelled
  "Reasoning", the idea, evaluations and ancestry, with diff and proof tabs. `arena/viewer_data.py:271
  tool_timeline` already pairs calls with results, but without a node link.
- **Add:**
  - A node → call → turn join in `viewer_data.py` (by time for v6, by id for v7).
  - A lazy `/run/<id>/node/<id>.json` endpoint: call args, delivered and untrimmed results, and that turn's
    reasoning and response.
  - A "Reasoning & calls" tab.
  - For v7 nodes: the step-origin line (§5b) and the hole registry.
- **Source.** The local journal, not Langfuse. Langfuse lost 10–79 generations per run in v6pilot (#22), and its
  input is the redacted post-hook payload. Langfuse stays as a secondary view.
- **Size:** about 150–250 lines (about 80 Python, 70 JS, 60 tests).

## 8. Tests (D2)

1. **Now:** delete the low-value tests listed in the inventory: about 14 cases, plus tests of the YAML or the $3
   strings.
2. **During the build:** write pytest tests only for behaviour where a bug costs points or money:
   - the token counter and scoring rates against known rows;
   - the actual-cost stop: a run stops after the first call that reaches the limit, and never before (§2d);
   - measured lineage on fixture graphs (#5a);
   - the template renderer and its consistency tests (§2c);
   - reply schema and error naming (#27, #28);
   - submission gates (BACKLOG §6 fixtures);
   - finish gating at the exact fraction (#44);
   - outage backoff versus error loop (#3).
3. **Isolation:** inject machine readings (fair share, memory, swap) everywhere (#6). No test reads `/proc` or the
   live Lean sessions.
4. **Target:** about 80–120 tests that run in under 60 s without Lean. Lean-backed tests are behind a marker.
5. **Port nothing that tests a v6 tool shape.** `test_protocol.py` and `test_campaign_lookups.py` die with the old
   surface.
6. TS keeps `node:test`. Add a `test` script to `package.json`.

## 9. Pi 1.1.0 actions

1. Pin the version. Record `pi_version`, commit, dirty flag and `models.yaml` hash in `run-config.json` and the
   summary (#19).
2. Run the TS tests and one offline smoke test on 1.1.0.
3. Check Pi's per-call cost on a long prompt for each of our models (D8 relies on it).
4. Set `httpIdleTimeoutMs` low (#14). With `arena-guard` deleted (§2d), Pi's `retry.*` applies directly (#3).
5. Use `agent_settled.aborted` to tell a cancelled run from a finished one, and `durationMs` for traces.
6. Use `setActiveTools` for the gated `finish` (D15).

### 9a. Models: DeepSeek v4.1 flash plus MiMo 2.6 Pro via primalab (D10)
- **primalab is set up in Pi (2026-10-10, verified).**
  - Config: `~/.pi/agent/models.json`, provider `primalabs`, model `primalabs-ai/MiMo-V2.6-Pro`.
  - API: OpenAI chat completions at `https://api.primalabs.ai/v1`.
  - Key: `apiKey: "$PL_API_KEY"`, read from the environment.
  - `pi --list-models` shows it, and `pi -p` answers through it.
  - **The harness does not load `.env`.** `PL_API_KEY` must be exported in the shell that launches runs, or v7's
    `arena run` loads `.env` itself (phase 1).
  - Later, generate this config from `models.yaml` (one price source, §2d).
- **Prices** (primalab dashboard, which is authoritative over its docs table at $0.435): input **$0.43**, cached
  input **$0.0036**, output **$0.87** per 1M. No cache-write charge. Context 1,048,576.
  - Max output is not published; the Pi catalog's 131,072 is used.
  - Rate limits are not numeric: a per-user fair share and per-model concurrency, giving 429 or 503 with
    `Retry-After`. Pi's retry handles it once `arena-guard` is gone (§2d).
  - primalab also serves `DeepSeek-V4-Flash-0731`, an older version. DeepSeek stays on opencode-go (D26).
- **Probe results** (2026-10-10, about $0.01 in all):
  - **Cross-request prefix caching works.** Three independent requests sharing a ~6K-token prefix: requests 2 and
    3 read 5,968 of 5,996 tokens from cache. Through Pi, a second separate `pi -p` process read 10,816 of 10,847
    from cache. This makes the fresh context and islands of D22 (b)/(c) cheap on MiMo.
  - **Pi computes cost from the configured prices,** and this matches by hand (9,823 input × $0.43/M = $0.00422).
    D8 holds for MiMo.
  - **Tool calls work.** Replaying `reasoning_content` on the next turn is accepted (Xiaomi says keep it, so D25 /
    #11 trimming does not apply to MiMo).
  - **Turning thinking off:** the raw API honours `reasoning_effort:"none"` (0 reasoning tokens) and ignores
    `thinking:{type:disabled}`. Through Pi on a real tool turn, `--thinking off` gave **10 reasoning tokens against
    45 at high**, so it reduces thinking but does not remove it. To get 0 on tool turns, the extension sets
    `reasoning_effort:"none"` in `before_provider_request` when the last message is a tool result. Phase 2; A/B in
    phase 5.
- **DeepSeek reasoning replay (D25, #11), probe 2026-10-10.**
  - opencode-go accepted a tool-call continuation **without** the earlier turn's `reasoning_content`, with the same
    outcome as with it (`tool_calls`).
  - The opencode-go endpoint needs an `x-opencode-session` header and a non-Python user agent. Pi sends both.
  - So dropping replayed reasoning is allowed at the API level. If reasoning is never sent back, rather than trimmed
    later, the cached prefix stays stable.
  - The Pi lever is likely a `modelOverrides` entry setting `compat.requiresReasoningContentOnAssistantMessages:
    false` for DeepSeek. Check in phase 2.
  - Whether proxy quality drops needs an A/B on fixed rows at $0.50 (phase 5).
- **Removal.** About 169 code lines mention Luna or Qwen. The largest are `budget.test.ts` (goes anyway), the
  `proof_tool_replay.json` fixture, `test_models.py`, `test_runner.py` and the `v6-matrix` preset. The stale
  models.yaml comment "Pi's catalog has no tier" goes with Luna.
- **Per-model settings to measure:** `request_output_tokens` (≤131K for MiMo), the compaction threshold, and the
  thinking level on tool turns.

### 9b. Lean machinery for v7 (speed and memory)
**Today** (verified, `arena/lean_session.py`):
- One daemon per run. Per toolchain, one `lean --server` (:346-363) with per-document file workers.
- Caps: `MAX_SLOTS=4` per toolchain, `MAX_WORKERS=6` per daemon, `MACHINE_MAX_WORKERS=8` machine-wide via
  `WorkerBudget` (:45-53, :139).
- The memory guard lets one header load at a time and opens a worker only if `MemAvailable` minus the need is at
  least `RESERVE_GB=5` (:232-252).
- Header-first warm open (:519, :540). A timeout resets the document to the header, so the worker stays warm (:569).
- A background lane of one worker per toolchain. Idle close after 600–900 s, plus `_evict_idle` (:883).
- Total heartbeats come from the same compile (`HEARTBEAT_WRAPPER`, `engine.py:512`). The per-tactic profile is a
  **second** compile (`profile.py:258`).

**Measured** (v6ark2 logs):
- ArkLib header open: 43–148 s, rising with parallel opens; 21–45 s on a warm page cache.
- WickAlgebra header open: 78.5 s.
- Warm compile p50 / p95: 1.8 / 4.1 s (WickAlgebra), 3.9 / 8.2 s (ArkLib), with 180 s timeouts on ArkLib.
- Cross-version checks on ArkLib: 31–32 s.
- The eviction of v4.31 workers for v4.30 and v4.29 accounts for the about 129 s delay in #25d. Re-opens take 21 s.
- **Per-worker memory is not logged.** The 6 GB figure is unmeasured.

**Gap.** lean-lsp-mcp runs its own Lean workers outside `WorkerBudget`. That is uncounted memory. In v7 the MCP
goes behind our tools (§4b), so its workers come under the daemon's budget, or it is capped at 1 worker.

**v7 target** (lanes; §9c makes them one shared service across runs, with the REPL pool as the batch lane):

| Lane | Serves | How |
|---|---|---|
| Primary, model lane | compile, salvage (≤6 serialized edits), per-step goals, splice | The existing LSP daemon. Snapshot reuse already re-elaborates only from the changed line (`changed_from_line`, :613), so splice-prefix reuse is largely free (to be confirmed by measurement). Step goals come from the same documents |
| Primary, batch sidecar | declaration index, cross-run recombination, (sweep) | The REPL pool of §9c (`env` reuse; pickled header snapshots, header paid once per row and toolchain), confirmed by the benchmark. REPL tags for v4.25–v4.32 are unconfirmed, and scoped extensions are not pickled correctly |
| Cross-version | other toolchains | 1 background worker each, opened lazily, **never evicting model-lane workers** (#25d) |
| Cold | final verification, `arena submit` | `_run_cold` (direct `lean`, Mathlib first) |

- **Memory plan:** primary pinned at 2–3 workers, 1 per cross-version toolchain, `RESERVE_GB=5` kept, **PSS per
  worker logged** (`smaps_rollup`).
- **Profiling:** the cheap total-heartbeat wrapper on every draft. The full per-tactic profile only for the price
  table of archive nodes and submissions, because `arena_hb_tac` rewrites syntax.

**Recorded v6 speed baseline** (the gate in the spec: v7 must match or beat it):

| Row (toolchain) | Warm-up (header open) | Edit p50 / p95 | Reference p50 / p95 | Sorry probe | Error draft | Min free memory |
|---|---|---|---|---|---|---|
| Core.InitsUpdatesComm (Strata, v4.29.1) | 8.2 s | 0.5 / 0.5 s | 0.3 / 0.5 s | 0.3 s | 0.3 s | 21.1 GB |
| putnam_1964_b2 (Mathlib, v4.25.0) | 30.8 s | 12.2 / 13.5 s | 2.3 / 11.7 s | 0.2 s | 0.2 s | 18.1 GB |
| Cslib.SKI (CSLib, v4.33.0-rc2) | 5.6 s | 0.2 / 0.3 s | 0.2 / 0.2 s | 0.2 s | 0.2 s | 20.7 GB |

Recorded 2026-10-10 on an idle machine with the existing load tool: 1 run, model lane only, 8 checks per row,
the slow kind off. All real criteria passed: 0 timeouts, 0 fresh opens after warm-up, 0 orphans. Raw output is
in `research/v7-probes/lean-bench/`. The Putnam edit time reflects the row's heavy reference proof (about
120K heartbeats), not the machinery. Before v7 relies on this baseline it is extended with ArkLib (v4.28–v4.31,
the largest headers) and with PSS per worker.

**v7 bench baseline (ticket 07, 2026-10-11)** supersedes the table above as the gate's yardstick:
`benchmark/derived/lean-baseline.json` (label `v6`, recorded with `arena lean bench`, 5 repeats, first toolchain
for the three rows above plus ArkLib on v4.28–v4.31). Its figures are **not comparable** to the table above: the
bench runs a fixed check order, and a check's cost depends on the line where it differs from the previous
document. In the v6 run, Putnam's reference after a sorry probe took 12.7 s and after a trailing edit 2.3 s (the
table's p50 is the latter); the bench always times reference after sorry (12.3 s). Like for like, all three rows
are within noise of v6. The first open of a session (`open_cold_s`) is recorded but **not gated**: it measures the
page cache (Putnam 4.1 s warm, 18.8 s after ArkLib evicted it); owner decision 2026-10-11. The repeat open
(`open_warm_s`) does the same work with a hot cache and stays gated. The bench warns when a first open is over
twice the repeat (cold cache); a gate that fails right after other large Lean work gets one rerun, and a figure
that fails both runs is a regression. ArkLib v4.28.0 is the slowest setup measured
(open 46 s, edit p50 10.3 s, sorry 4.1 s, worker 6.0 GB; v4.29–v4.31 open about 30 s, sorry about 1.6 s, worker
3.6 GB).

**Benchmark first** (Lean only, phase 0/3), extending `tools/lean_load_test.py`, which already drives the real
client path and samples memory:
1. Header open cold and warm per toolchain, with PSS per worker.
2. Warm p50/p95 under salvage bursts and splice edits.
3. LSP edit vs REPL `env` reuse vs cold `lean` on 20 saved drafts per row, with heartbeats agreeing within a
   tolerance.
4. Splice-prefix scaling: edit the last tactic vs an early one.
5. Pickle round trip size and correctness on Mathlib and ArkLib rows.

### 9c. Lean audit: where the seconds go, and the savings (2026-10-10)
Data: 13 v6 runs (v6ark2, v6ark, v6cov), from ledger `lean.seconds`, `lean-session.log` and `lean-health.json`.
Header opens are not in `lean.seconds`.

| Site | Kind | Path | Trigger | Cost per run |
|---|---|---|---|---|
| `engine.py:512` fast | draft on the primary toolchain, with total heartbeats | daemon, model lane | each compile | 76–370 s (ArkLib 190–370) |
| `engine.py:512` probe | sorry draft | daemon, model lane | each probe | 20–250 s; interleaved 1,193 s including 5 timeouts of 180 s |
| `campaign.py:2090` autocheck | cross-version | daemon, background lane, serial | **every** candidate that passes the primary | ArkLib 440–1,040 s, **up to 5.6× the primary cost** |
| `campaign.py:892`, `route_features.py:63` | route extraction | background lane | each new proof | unlogged, about 80–500 s (gone in v7, §5j) |
| `profile.py:262` | per-tactic profile, a 2nd compile | model lane | each `arena_profile` (2–11 per run) | unlogged |
| `lean_health.py:70` | health gate: warm 3 primary + 1 per other version, check the reference | daemon | each run | 35–400 s wall (ArkLib 320–400) |
| worker (re)opens | header import | daemon | open, evict, idle close | sums of 250–860 s (ArkLib), 46–277 s (others) |
| `campaign.py:2174` | cold verify | `lake env lean`, versions in series | each submission | about 140 s (ArkLib) |
| lean-lsp-mcp | goals and attempts | **its own LSP, outside `WorkerBudget`** | each run | at least 1 extra header open, unmetered memory (REPL default 16 GB, `LEAN_REPL_MEM_MB`) |
| `context.py:149,178` | context and profile scan | daemon | per run on a cache miss | cached in `runs/cache/` by (name, commit) |

- **Already shared:** `.olean` files and Lake builds. The run scratch's `.lake` is a symlink to the workspace.
- **Not shared:** anything across toolchains. Each toolchain is its own workspace (ArkLib: 4 versions, 24.7 GB).

**Savings, ranked** (Lean-seconds per 13-run campaign; mostly inferred, to be confirmed by the §9b benchmark):
1. **Route extraction removed.** Synchronous Python routes (§5j) save about 1,500–3,000 s. Already decided.
2. **Shared Lean service across runs**, keyed by (workspace, toolchain) and reused by replicates and campaigns,
   instead of one daemon per run. About 2,400 s at 3 replicates, plus 100–400 s of gate time per run.
3. **Cross-version checks only for candidates that could become the best verified** (proxy ≥ best, or at
   close-out). About 1,000–1,500 s, mostly ArkLib. The model still sees per-version results for those (§4f).
4. **Probe timeout near 3× warm p95,** not 180 s, for sorry drafts. About 600 s on one run alone. On a timeout,
   partial messages come back and the draft moves to a fresh worker (§12b).
5. **lean-lsp-mcp behind our service** (§4b) removes a duplicate header open and an unmetered worker per run.
6. **Warm the primary worker first, others lazily.** Three parallel opens took 148 s against 45 s for one.
   About 100 s of ArkLib gate per run.
7. **Close workers at row end, not on idle timers,** and never evict model-lane workers (#25d). About 100–150 s per
   ArkLib run.
8. **Cold verify the versions in parallel** (about 90 s per ArkLib run). The profile's second compile reuses the
   fast compile's total heartbeats, and the full per-tactic profile runs only for archive nodes (§9b).

**Engine choice** (research, `kimina-lean-server`, `leanprover-community/repl`, LeanInteract, Lean v4.32 notes):
- **A warm REPL and a warm LSP document are about equally fast per check.** Each elaborates only the changed
  declaration.
- The REPL wins on **amortization**: one imported header serves many independent checks, across runs, with less
  memory than an LSP worker per file.
- The LSP wins on incremental edits (splice), exact error positions and per-tactic goals.
- Heartbeats for scoring are confirmed on the in-file path, because REPL options and async behaviour can differ.

**v7 target, refining §9b:**
- **One long-lived Lean service per machine,** shared by all runs.
- **REPL pool** (the Kimina pattern, our own code, multi-toolchain), keyed by (toolchain, header), with LRU
  eviction and a per-process memory cap, about 5 resident processes in all. It serves whole-proof checks:
  cross-version, salvage passes, recombination, declaration index, certify.
- **LSP documents** for the model's interactive edits, goals and splice.
- **Cold `lake env lean`** only for the final official-equivalent check.

**Built (ticket 08a, 2026-10-13):** one service per machine (`service_dir()`, socket `service.sock`), started on
demand by `ensure_service`; runs `lease` their primary and other toolchains, campaigns will `hold` queued rows
(ticket 09). Close policy, owner decision 2026-10-13: a project closes **RELEASE_GRACE_S = 120 s** after the last
lease or hold naming it ends (env `ARENA_LEAN_RELEASE_GRACE_S`), so the next run of a row reuses its warm workers
with no hold; a project nothing ever leased closes after `ADHOC_IDLE_S = 600 s` idle; the service exits after
`SERVICE_LINGER_S = 600 s` with nothing open. `arena lean status|stop|serve`. The bench runs its **own private
service** per measurement, so its repeat open stays a real reopen and it never touches another run's Lean.
Gate on an idle machine: Core and CSLib pass; ArkLib (4 toolchains) repeats within limits except two noise
figures (a p95 from 5 repeats, and +0.26 s on a 1.9 s split); Putnam varies about ±20% between runs on the same
code, and an A/B on one idle machine showed 08a within ±3% of 07 on every Putnam figure. Run the gate on an idle
machine (no backup, browser or second agent running Lean); a busy machine read as a +30% Putnam regression.
**Putnam variance RCA (2026-10-13):** the cause is the laptop's CPU clock, not Putnam or the code. Within one run
every long Putnam check (splice, edit, reference: the 300-line proof) slowed by the same factor (x1.08 to x1.26 across
runs), while the sorry and error checks (0.22 s, from line 14) never moved, and one run fell back to the clean
figures on its last repeat. Core's long checks slowed as much (x1.27 to x1.43) but stay under the 0.25 s floor, so
only Putnam's multi-second checks cross the gate. The i5-1135G7 runs `powersave`/`balance_performance` and reached
94 C within seconds of a Core check. Since 08b the bench samples the fastest core's clock and the package temperature
every 2 s while the checks run, shows them per row ("CPU MHz / C") and, once a baseline holds them, warns when a
row's median clock is more than 10% below the baseline's. Re-record the baseline at the next deliberate re-record so
the warning can fire.
**Built (ticket 08b, 2026-10-13):** lanes (a model request for a project only in a lease's `others` runs on the
background lane), `PRIMARY_MIN_WORKERS = 2` / `PRIMARY_MAX_WORKERS = 3` / `OTHER_WORKERS = 1`, no model worker is ever
evicted (only idle background workers of other projects), `warm` with `"wait": false`, per-worker PSS in `status` and
`pss.jsonl` (workers matched to documents by the URI Lean passes to `lean --worker`), the gate on the primary toolchain
only plus `check_others`, limit floor 60 s (all seven baseline rows get 60 s; Putnam's slowest reference, 18.3 s, gives
55 s), partial messages on timeout, and the `goal` / `try` ops (one worker per request). Review fixes: `goal` checked
twice on possibly different workers; the memory marker went to the machine-wide directory, so fast tests made every
real run's route extraction (and `test_routes`) wait 2 minutes. Gate: Core and CSLib pass; Putnam `edit` +14% and
ArkLib v4.31 `reference` +14% / `splice_late` +19% failed at a clock 17-25% below Core's in the same run (3000 and
2700 MHz vs 3573; 69-73 C). **Revised RCA:** the firmware's long-term power limit is 15 W over 28 s
(`intel-rapl-mmio`, short-term 40 W), so any load longer than about 28 s runs at 2.5-3.0 GHz instead of 3.8 GHz; heat is
not the limit. Owner decision 2026-10-13: gate on clock-adjusted figures (seconds x MHz / baseline MHz) from the next
Lean review (08c): re-record the baseline with CPU figures on ticket 07's code (v6 machinery) plus the CPU logging,
then gate 08b's and 08c's code against it. Raising the power limit (root) stays an option for later.
**Built (ticket 08c, 2026-10-13):** after the primary gate the runner checks the other toolchains in a background
thread (`start_background_checks`); a failure stops Pi once through the breaker's path, naming the toolchain (stop
reason `lean_unhealthy`, exit 75); housekeeping counts the warm service's memory as free. The Core row lists three
toolchains (not one), so the slow runner tests exercise the background warm-ups: a project closes only once its
header load ends (about 12 s for the last one), and the crash tests now allow 60 s. **Clock-adjusted gate in place:**
`compare` gates `seconds x current MHz / baseline MHz` when both sides carry a clock and reports the measured value.
Core, Putnam and CSLib were re-recorded with their clock on ticket 07's code plus the CPU logging (`rerecorded` in the
baseline; Putnam's reference 17.1 s at 2800 MHz scales to 12.6 s at turbo, against 12.3 s recorded then). ArkLib keeps
its 2026-10-11 figures until the full gate after 08d. 08c's quick gate: 0 regressions. Open (owner, later): replace
Putnam in the quick gate with a row whose full re-check takes 2-4 s and whose header is small (about 2 min instead of
6; Putnam's 15 full re-checks of about 13-17 s are 5 of the 6 minutes).
**Built (ticket 08d, 2026-10-13):** a pooled REPL lane (`arena/lean_repl.py`), built for all 10 toolchains in
`runs/cache/repl/<toolchain>/` (about 2 min; v4.29.1 from the v4.29.0 tag with the toolchain overridden). **Verdict:
REPL stays off** (`REPL_ENABLED = False`, `benchmark/derived/repl-compare.json`). On the Core row's three toolchains
the REPL agrees with the LSP lane (0 pass/fail disagreements, heartbeats within 2.4%, check p50 0.41-0.48 s vs
0.44-0.50 s), but no pickled header loads back correctly (the reference proof fails with a Lean PANIC after
unpickling; a verification step now catches this and marks the pickle unusable), unpickling takes 13-16 s against a
5-7 s cold import, and a REPL process holds 0.46-0.50 GB PSS against an LSP worker's 0.36-0.42 GB. Rule 9 needs every
compared row to pass, so the comparison was cut to Core. The v4.32 header-snapshot trial (`--incr-header-save` /
`--incr-load`) gave equal diagnostics on every ≥v4.32 row (not adopted; recorded only). **Gate:** the full gate after
08d is moved to after ticket 12 (owner, 2026-10-13): the 08d run stopped on a bench race (an exiting 5 GB Putnam
worker was reported as an orphan 0.1 s after SIGKILL; the bench now waits up to 2 s / 5 s), and its ArkLib re-record
was void (the CPU-logging patch was not applied: `git apply` inside a repo subfolder skips the paths silently; use
`patch -p1` next time), so ArkLib keeps its 2026-10-11 figures. 08d's quick gate: Core `reference.p95` +46% at 2751 MHz
on the first run (one slow sample), 0 regressions on the Core rerun; Putnam and CSLib passed.
 (Lean-only benchmark, phase 0/3):
- Lean v4.32's experimental `--incr-header-save` / `--incr-load` cross-process header snapshots, on the ≥v4.32 rows.
- REPL tags: **verified** for v4.25.0 through v4.33.0 (`git ls-remote`), including v4.33.0-rc2. **No `v4.29.1` tag**:
  test whether the v4.29.0 REPL works on the Core row's v4.29.1 toolchain, or build it from source.
- The REPL pickle caveat: scoped extensions do not round-trip.

### 9d. Campaign scheduling around warm caches
- **Today.** `run_campaign.plan` is replicate-major (every row at replicate 1, then replicate 2), so every run
  opens a different header. A header serves only its own row, because it is the file prefix.
- **v7 order:** group by (workspace, toolchain set), then row, then replicate.
  - Replicates of one row run back to back, or 2–3 at once, against the warm shared service. Concurrency is limited
    by the API, not by Lean.
  - **Pre-warm** the next row's headers during the current row's last 10–15 minutes, serially, because only one
    header loads at a time under the memory guard.
  - Rows of the same project are kept together, since the page cache makes a re-import cost 21–45 s instead of 148 s.
- **Close policy.** Close a (workspace, toolchain) only when no queued row needs it. About 5 resident workers within
  the 5 GB reserve on 30 GB. Log per-worker PSS so the cap rests on measurements.
- **Blockers to sharing:**
  - the per-run socket (`socket_path`);
  - workers owned by one run's `Session`;
  - per-replicate document ownership;
  - a fair-share rule across rows. `WorkerBudget` already counts workers machine-wide.
- **Built (ticket 09, 2026-10-13):** `arena/scheduler.py`. `arena campaign` plans row-major, grouped by (source,
  toolchains), replicate before model inside a row. A machine-wide `flock` at `runs/campaign.lock` stops a second
  campaign; `arena provision` refuses while it is held and takes it while building, so no campaign starts mid-build.
  `campaign.json` gets `settings` once the packet and preflight gates pass (an aborted campaign leaves nothing, so the
  prefix can be reused) and `observed` (min free memory, max load, swap, disk, peak concurrent runs) at the end. A
  `hold` keeps every queued row's toolchains open, narrowed as rows finish. The next row's primary header is pre-warmed
  when the current row's longest run is within `--prewarm-minutes` (default 12) of the median run time, then its other
  toolchains on the background lane. Slow test: a pre-warmed primary serves the run's first compile from the session
  with no new worker and no header load. Swap and disk are recorded only; thresholds stay an open owner question.

## 10. Order of work

| Phase | Work | Cost | Closes |
|---|---|---|---|
| 0 | **Done:** replays for lineage, paper test, salvage v1/v2, phases, routes and archive (§5i, §5j, §5d), plus the primalab and DeepSeek probes (§9a). **Remaining:** the Putnam heartbeat mismatch (§1l). 15 profile compiles of the best proofs for their price tables (§1l). ~~Pi `setActiveTools`~~ **verified** in Pi 1.1.0 (`types.d.ts:1267`), so D15 is feasible. ~~Unfold ranking~~ dropped (D33). The price-table prototype on stored proofs (§3a). Lean machinery benchmark (§9b).  | free | informs D15, D27, O3, B1 |
| 1 | `pyproject.toml` (flat layout, §7-0) and the Cyclopts command tree (§7.1); `arena run` loads `.env`. Repo housekeeping (§7.2): delete `submission/`, lean4-skills, `arena_skill.py`, `route_validation.py`. Test cull. `agent-text/` with strings moved verbatim, the renderer, `numbers.yaml` and the word-budget table. Code-version recording. Luna and Qwen removed. Pi `models.json` generated from `models.yaml`, plus the price test. Mark SPEC-v6 superseded. (The empty v6-08b branch was already gone.) **Done in tickets 00–03 except `agent-text/`, which moved to 05a/05b.** | free | #19, #39, #40, #41, D1–D4, D10, D18 |
| 2 | Delete `budget.ts` and `arena-guard` for the actual-cost stop (§2d). Outage handling, test isolation, the verified label, and the rest of §12a | free + smoke | #1, #2, #3, #6, #7, #12, #14, #26, #27, #35 |
| 3 | Shared Lean service across runs with the REPL pool and the LSP lane (§9c), campaign ordering (§9d), cheaper cross-version and probe timeouts. Event log, operation lineage with focus filing, and the graph model behind the old tools. Per-step goals recorded on every node. Live routes, archive (K1) and map (§5b–5d, §5j). Price engine (§3a–3c). Declaration index and completions (§4d). `arena replay` and the viewer panel (§7a, §7b). Lean-side fixes (§12b) | free | #5, #5a, #13, #15, #16, #18, #24, #25c, #25d, #33 |
| 4 | v7 tool surface plus the full text rewrite, together (§2, §4f). Salvage chain and auto-assembly (§5f, §5g). Stall-triggered focus moves (§5e). Gated `finish`. Neutrality and consistency tests | free + smoke | #9, #10, #17, #25a, #25b, #28–#32, #36, #43, #45 |
| 5 | **The v7 campaign, owner-launched (D37).** Two rows: our best-scoring row **putnam_1964_b2** (98.54, Mathlib v4.25.0) and our worst **Cslib.SKI.parallelReduction_diamond** (70.37 official, CSLib v4.33.0-rc2). DeepSeek v4.1 flash runs v6 against v7 on both rows at $0.50 (the A/B: proxy, bookkeeping share, tool errors, calls before the first compile, **share of compiles using an operation**). MiMo 2.6 Pro runs v7 on both rows (the new-model check). Variance set and further A/Bs (stall-move target §5e, DeepSeek reasoning replay D25, MiMo thinking on tool turns §9a) and the synthetic compaction session (#48) follow only if the owner extends the campaign | paid | §4f gate, §6, D25 |
| 6 | `arena submit` (BACKLOG §6): multi-run selection, the vendored app.py filter plus a parity test, removing the `auto_merge` exclusion. Cross-run recombination and transfer (§5g) | free | BACKLOG §3, §6, #22, #25 |
| 7 | Outer loop: `arena experiment` and `runs/harness-results.tsv` (§6). Later experiments: fresh context and islands (D22 b/c) only if diversity does not improve | paid | §6 |

## 11. Open decisions

All decided (D15–D35). New questions get added here as they arise.

## 12. Remaining ISSUES fixes (from the coverage audit, 2026-10-10)
Items the redesign does not close by itself. Code references were checked on 2026-10-10.

### 12a. Run control and messages (phase 2)
- **#3 Outage.**
  - `arena.ts:22` caps the error streak at 3, counting every non-completed outcome (`:1276`).
  - v7: Pi's native retry handles transport errors (no content, no usage) once `arena-guard` is gone (§2d).
  - The harness adds a wall-clock wait of up to about 10 minutes, then stops with `provider_unreachable`, which
    marks the run for rerun.
  - `error_loop` stays only for repeated model-side failures. Guard refusals no longer exist.
  - The error text is logged in the control row.
- **#7 "Best verified" label.** `summary.py:285-310` takes `best_verified_candidate` from `mode == "full"` rows.
  v7 derives "verified" only from the all-version check, with a one-version fixture test. Reproduce the bug first.
- **#8 Finish wording.** Option A is in effect (D15): the stop condition plus neutral facts, from
  `agent-text/replies/finish.md`.
- **#12 Refused finish blocks.** With gated `finish` (D15) there is no refusal path. Cold verification moves to the
  harness's close-out step after the model stops, never inside a tool call.
- **#26 Continuation text.** A failed request gets its own fact line, `messages/continuation.md` key
  `request_failed`, never "the turn ended with text".
- **#27 Malformed arguments.**
  - An object with no recognised keys is reported as "arrived empty or malformed", listing the valid keys
    (`toolnames.ts:85` accepts `{}` today).
  - A null-argument call is re-requested once with the same turn, at no extra wording cost. A second null is
    reported.
- **#35 Truncated turns.** When a turn stops at the output limit, its reasoning is kept in history, not dropped, and
  the reply says the turn was cut at N tokens.
- **#23 Cache alarm.** It stays as a diagnostic in the ledger: it fires on `cacheRead == 0` after a cached request,
  and on write > read. No stop.

### 12b. Lean side (phase 3)
- **#13 Warm-up.** Start the model once the primary toolchain is healthy, and warm the others in the background.
  ArkLib waited 404 s.
- **#15 Timeouts.** On a timeout, return the last elaborated position and the partial messages. The next draft runs
  in a fresh worker. Cancellation is cooperative (RCA-v6cov).
- **#16 Shed order.** `context.py:609` sheds library lines before local-variable lines. v7 sheds local variables
  first, because every hypothesis already appears in the goals. The library's lemma prices (§3e) make it the more
  valuable section.
- **#21 Swap and disk.** Record swap, si/so and free disk in `lean-health.json`. Hold new runs above a threshold.
  `arena provision` refuses while a campaign holds the lock.
- **#24 Cold-verification cause.** Record the exit code, the timeout flag and the last diagnostics in
  `cold_verification`.
- **#25d Worker eviction.** Primary-version workers are pinned. Warm-up of other versions may not evict them.
- **#33 Numerals in goal signatures.** Normalise literals in goal-state signatures. The route signature (§5j) is
  already free of numerals, because it abstracts arguments.
- **#34 Compaction residuals.** The budget gating is gone (D8). Still to do:
  - send the summary request with the cached prefix intact;
  - skip it on an empty history;
  - log each failure as a ledger event with an alarm.
  The memory text itself is §12c.

### 12c. Carried-over v6 items (WORKING "Next improvements")
- **Compaction memory.** It is rebuilt from v7 state rather than patched. The same text seeds a fresh context
  (D22 b). Its contents:
  - the full best proof (WORKING candidate 1);
  - the map (§5d);
  - the library lines the best proof uses, with statements (candidate 2);
  - a "read so far" list of handles and ranges (candidate 3);
  - the open holes with their goals (candidate 4).

  `arena replay --render v7` checks it on the v6pilot compaction turns before any run.
- **F: hide the incumbent.** A variant of the fresh-context experiment (D22 b): the seed without the best proof
  text. It runs only if diversity does not improve.
- **WORKING idea 4, lemma ranking weights.** BACKLOG §1 was dropped (D33). The IDF weighting stays, pending the
  hit-rate check (§12e).
- **Tool profiles (SPEC story 72).** Moot. v7 has one 5-tool surface for every model.
- **Relay (WORKING idea 2) and adaptive thinking (idea 3).** Out of scope for v7. Thinking per tool turn for MiMo
  is §9a.

### 12d. Owner actions and housekeeping
- **#25 Official LaTeX template.** The owner obtains it before the Nov 1 code upload. `arena submit` takes
  `template=`.
- **#41 SPEC-harness-v6 is stale.** Mark it superseded by this plan in phase 1.
- **#40 Campaign tooling.**
  - `arena campaign` records `--jobs`, minimum memory and maximum load in `campaign.json`, and takes a lock.
  - `runs/analysis/v6cov/rerun-em.sh` is retired.
- **#48 Compaction at 850K.** A synthetic long session in phase 5.
- **Done:** the empty `hrushikesh/v6-08b-campaign` branch no longer exists (checked 2026-10-10). v6 is merged and tagged.

## 13. Traceability: every ISSUES, BACKLOG and WORKING item
Status: ✔ covered · ∅ moot (with the decision) · ⚑ stale in ISSUES. Grounding: C = code reference, P = probe or
replay, D = design only.

| Item | Where | St | Gr |
|---|---|---|---|
| #1 reservations | §2d (D8) | ∅ | C |
| #2 reports count reservations | §2d (D8) | ∅ | C |
| #3 outage stop | §12a, §2d | ✔ | C |
| #4 packet vs route rule | §1d | ⚑ fixed, `context.py:637` | C |
| #5 routes filed late | §5j | ✔ | C+P |
| #5a batch parent | §5b | ✔ | P |
| #6 test isolation | §8 (`tests/test_lean_session.py:628`) | ✔ | C |
| #7 verified label | §12a | ✔ | C |
| #8 finish wording | §12a, D15 | ✔ | D |
| #9 first error only | §5f, §4f | ✔ | P |
| #10 untrimmed results | §4f | ✔ | D |
| #11 reasoning replay | D25, §9a | ✔ API; quality A/B in phase 5 | P |
| #12 finish blocks on cold verify | §12a | ✔ | D |
| #13 warm-up | §12b | ✔ | D |
| #14 idle timeout | §9, §2d | ✔ | D |
| #15 Lean timeouts | §12b | ✔ | D |
| #16 shed order | §12b | ✔ | C |
| #17 cross-version late | §4f | ✔ | D |
| #18 core names | §4d | ✔ | C |
| #19 code version | §9, phase 1 | ✔ | C |
| #20 dry-run gates | §7 | ✔ | C |
| #21 swap and disk | §12b | ✔ | D |
| #22 Langfuse ids | §7a/§7b (local journal is the record) | ✔ | P |
| #23 cache alarm | §12a | ✔ | D |
| #24 cold-verify cause | §12b | ✔ | D |
| #25 template | §12d | owner | D |
| #25a MCP invisible | §4b, §4f | ✔ | D |
| #25b slowest draft | §4f | ✔ | D |
| #25c hard threshold | §5j | ✔ | P |
| #25d eviction | §12b | ✔ | D |
| #26 continuation text | §12a | ✔ | D |
| #27 malformed args | §12a | ✔ | C |
| #28 lookup errors | §4f | ✔ | D |
| #29 look-alikes | §4d | ✔ | D |
| #30 goal output gaps | §4f (`goal` node-relative), §5f | ✔ | D |
| #31 MCP quirks | §4b (MCP hidden) | ∅ | D |
| #32 ideas | D16 | ∅ | P |
| #33 numerals | §12b, §5j | ✔ | D |
| #34 compaction residuals | §12b, §12c | ✔ | D |
| #35 truncated turns | §12a | ✔ | D |
| #36 long refusals | §5h | ✔ | D |
| #37 byte bound | §2d (D8) | ∅ | C |
| #38 Qwen output | D10 | ∅ | D |
| #39 cap naming | phase 1 | ✔ | C |
| #40 campaign tooling | §12d, §7 | ✔ | D |
| #41 stale SPEC | §12d | ✔ | D |
| #42 journal footer | §7a | ⚑ not reproduced (96/96 present) | P |
| #43 STATEMENT_MODIFIED | §4f (evaluate removed) | ∅ | D |
| #44 refusal rounding | §2d | ✔ | D |
| #45 duplicate drafts | §5c | ✔ | D |
| #46 summary clocks | §2d (D8) | ∅ | C |
| #47 ideas unused | D16 | ∅ | P |
| #48 compaction at 850K | §12d, phase 5 | ✔ | D |
| BACKLOG §1 unfold ranking | D33 | ∅ dropped by probe | P |
| BACKLOG §2 routes by subgoals | §5j: shape signature instead; subgoal data only as a secondary label | ∅ superseded | P |
| BACKLOG §3 harness merge | §5g, phase 6 | ✔ | C+P |
| BACKLOG §3 live compaction test | phase 5 | ✔ | D |
| BACKLOG §4a compaction bypass | §2d (D8) | ∅ | C |
| BACKLOG §4b shallow credit | §5h (D28) | ∅ | D |
| BACKLOG §4c refusal growth | §5h | ✔ | D |
| BACKLOG §5a graph | §5b–§5d: operation lineage instead of measured lineage | ✔ superseded in part | P |
| BACKLOG §5b tool UX | §4f | ✔ | P |
| BACKLOG §5c order | §10 | ✔ | — |
| BACKLOG §6 submit | phase 6 | ✔ | C |
| WORKING compaction memory | §12c | ✔ | D |
| WORKING F hide incumbent | §12c | ✔ (conditional) | D |
| WORKING ideas 1–9, tool profiles | §12c, D16, D22, §4d | ✔ / ∅ | D |
| Pending actions | §12d | ✔ | C |

**Grounding gaps.** About half the rows are design-only (D). Most are small, mechanical fixes. Those that change
model behaviour are tested in phase 5, not assumed: the stall target, salvage adoption, operation adoption,
reasoning replay, and MiMo thinking.

### 12e. Library section after D33: answered (D34)
- **Hit-rate probe** (`library_hitrate.py`, `library-hitrate.json`; offline): of 301 name tokens in the 15 best
  proofs:
  - 139 (46%) were already in the reference;
  - 18 (6%) were in the packet's top 60;
  - 12 (4%) were in other packet sections;
  - 46 (15%) appeared in some tool result in that row's runs (search or read);
  - 86 (29%) appeared nowhere visible, so they came from the model's own knowledge.

  The regex counts some local projections such as `h.1`, so the shares are rough.
- **The top 60 earns its place on the rows where it matters.** The key lemmas of the PhysLib, b2, CCS and CallElim
  rows came from it. Hits sit at ranks 1–58, so the section stays at 60 and gains the tokens column (§3e).
- **Model knowledge (29%) and search (15%) together beat the packet.** `search` stays first-class (§4d).
