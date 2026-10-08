# v6 pilot: results, findings and the first official submission (2026-10-08)

The pilot ran 9 runs: 3 theorems × DeepSeek V4.1 Flash, GPT-6 Luna and Qwen 3.8 Flash.
- Each run had a $0.50 soft cap and thinking set to high, and runs went 3 at a time (`--jobs 3`). Total spend was $3.96.
- The harness changed during the pilot (timeline in §6), so runs did not all see the same code.
- Detailed reports are in `docs/reports/v6pilot/`: `v6pilot-deepseek.md`, `v6pilot-luna.md`, `v6pilot-harness-audit.md`, `v6pilot-proofs.md` and `submission-v1-MANIFEST.md`.

## 1. Results

| Theorem (reference tok / HB) | DeepSeek | Qwen | Luna | Best verified hybrid |
|---|---|---|---|---|
| `Core.InitsUpdatesComm` (224 / 4251) | **86.07** finished | 86.02 finished | 85.11 error loop at $0.17 | 87.10 (76 / 203) |
| `fundamental_theorem_of_variational_calculus'` (851 / 11947) | **88.25** finished | 87.32 soft cap | 66.13 soft cap | **89.93** (145 / 1575) |
| `Cslib.CCS.bisimilarity_congr_choice` (251 / 3858) | **86.44** finished | 78.43 (stopped by the user at $0.13) | 75.62 finished | **86.76** (83 / 256) |

Scores are the local proxy, and the original proof scores 33.33. **DeepSeek won every theorem** and was the only model to stop on its own every time under the "stop only with ≤10% left" rule. All three DeepSeek results beat every earlier run. Earlier results for comparison:
- v6 at a $0.10 cap: Core 83.88, PhysLib 81.07.
- v5 bests: Core 84.58, PhysLib 83.35, CSLib 78.55.

## 2. First official submission (2026-10-08 13:27 UTC, user "Hrushi", Closed-source LLM track)

**Combined 28.45%, 5 of 15 rows compiled.** The uploaded file was `runs/analysis/submission-v1/submission.jsonl`, which includes 3 offline hybrids.

| Row | Official | Our proxy |
|---|---|---|
| substOldPostSubset | 82.87 | 82.86 |
| extractedOldExprInVars | 82.44 | 82.42 |
| Core.InitsUpdatesComm | 87.11 | 87.10 |
| variational calculus | 88.10 | 88.25 (official HB 2018 vs our 1967) |
| CCS bisimilarity | 86.46 | 86.44 |

- **The proxy is trustworthy.** Token counts match the official ones exactly, and heartbeats drift by 2.6% at most.
- **Coverage is what limits the score now.** Combined = sum / 15, so each new row at about 85% adds about 5.7 points.
  - Four unsubmitted rows run on workspaces we already have: PhysLib Electromagnetism, PhysLib WickAlgebra, CSLib Fsub progress and CSLib SKI diamond.
  - The six other rows need Mathlib, ArkLib or PutnamBench workspaces.
- **Rules risk.** Closed-track entries must be reproducible from the harness within $3 per problem. The hybrid rows were assembled outside the harness, so before the full benchmark either a harness merge step produces them or we submit only harness rows.

## 3. Why DeepSeek wins

- **One early structural rewrite gives most of the score.** It found the rewrite in 2–5 minutes for $0.02–0.04, and that one change accounts for 73–83% of the total gain:
  - Core drops the induction for `updatedStatesComm`/`Init`/`Update`;
  - PhysLib uses `Continuous.integral_pos_of_hasCompactSupport_nonneg_nonzero` with a `ContDiffBump`;
  - CSLib uses `HomBisimilarity.symm_simulation`.
- **Everything after that was golf worth 0.01–1.5 points per step:** `.imp`, `And.imp`, `▸`, anonymous constructors, and hoisting or inlining `have`.
- **It searches for library lemmas before its first draft,** and does explicit score arithmetic ("each token = 0.149 pt").
- **It thinks in long turns:** 5–7K output tokens per turn, about 2.3 drafts per probe, and 2–7% of spend on bookkeeping. Its largest turn was 24K tokens against the 32K limit, and it never truncated.
- **Weakness:** routes it tried after a finish refusal never won. On Core it got past the refusal by recompiling a one-token variant of the original. The A/B/C credit rule (`qxz`) now refuses that.

## 4. Why Luna lost despite looking busy

| | Core | CSLib | PhysLib |
|---|---|---|---|
| Ideas → kernel-fingerprinted routes | 9 → 4 | 29 → 2 | 23 → 1 |
| Bookkeeping share of spend | ~28% | ~55% | ~37% |
| Cache reads as share of spend | 58% | 71% | 77% |

- **Its breadth was cosmetic.** On PhysLib its 19 "succeeded" ideas were 1–5% trims of the reference proof.
- **It never found the key lemma.** Luna's whole PhysLib run never mentions the lemma DeepSeek used, so it kept the reference skeleton at 601 tokens (DeepSeek: 160). Its compile rates (50–74%) were no worse than DeepSeek's.
- **Its turns were small:** about 1K output tokens per turn, one draft per probe, and 52–64% of turns with no proof attempt.
- **The biggest single cause was a harness bug:** compaction never succeeded (§5), so its context grew to 300K+ tokens, crossed the >272K price tier on 26–27 requests (+18% of its cap), and cache reads dominated cost.

## 5. Harness findings (audit), with status

| Severity | Finding | Status |
|---|---|---|
| Critical | **Compaction crashed for Luna and Qwen** (66/66, 82/82, 55/55 and 24/27 failures, "Cannot convert undefined or null to object"). A single tool call with `null` arguments makes Pi's `serializeConversation` crash on every later compaction. Reproduced offline. | **fixed `pnp`**: arguments repaired in `session_before_compact`; verified on all 4 failing sessions |
| High | Luna's Core run hit an error loop: the byte bound counted 665 KB of encrypted reasoning | **fixed `puk`** |
| High | 8 tool calls with null arguments across all 3 providers. The stream had no argument deltas, so the gateway or Pi stream dropped them. | compaction side fixed; the model still sees a validation error |
| High | Memory squeeze from 17:10 to 18:20: Lean workers were refused, 41 of 100 CSLib probes ran cold (55–144 s), route events arrived up to 56 min late, and Langfuse dropped 10–79 generations per run | **fixed** detached-process pile-up (one queue worker per run, memory guard); **fixed `zxo`** viewer and driver memory (journal payloads skipped, 2.4 GB → 214 MB). Use 2 jobs at a time on CSLib/PhysLib |
| Medium | Qwen's wrong argument names (`draft`, `idea`): 12 rejected requests, 13.7% of its Core spend | **fixed `vou`** |
| Medium | `arena_source` rejected `.lean-stdlib/...` paths from `lean_local_search` | **fixed `qwk`** |
| Medium | The live viewer showed "done" on running runs | **fixed `vyt`** |
| Medium | The kickoff packet changed mid-pilot (one sentence in `a5acc5c`), affecting only Qwen's CSLib run | known; freeze code before a campaign |
| Medium | Luna's PhysLib baseline was fingerprinted from text, so all 31 of its attempts were absorbed into r1 | open |
| Medium | Compaction costs DeepSeek 14% of spend (the summarizer prefix is not cached) | open |
| Low | summary/campaign stop-reason labels disagree; `lean-session.log` is empty; the `hard_cap` naming is confusing | open |

**Clean:**
- The cost ledger matches Langfuse exactly where Langfuse is complete, and soft-cap overshoot was at most $0.0024.
- The finish rule confirmed at 10–13% remaining.
- Trims lost no error text.
- The memory message works: nothing was redone after DeepSeek's 9 compactions. That same analysis found re-reads of source in the first pilot run; see the deferred memory items in `WORKING-harness-v6-decisions.md`.

## 6. Mid-pilot timeline (which run had what)

| Time | Change |
|---|---|
| 15:13 | Start, 3 at a time |
| 16:11 | `puk` context bound (TypeScript: runs started after this) and `qwk` stdlib paths (Python: applied immediately) |
| 17:10–17:59 | `qxz` exploration credit A/B/C. Python applied immediately; the TypeScript texts and packet reached only Qwen's CSLib run |
| 18:01 | `zxo` journal memory fix |
| 18:36 | Pilot ended; the user stopped Qwen's CSLib run |
| ~19:00 | After the pilot: `pnp` compaction repair, `vou` argument-key aliases |

Exploration credit (A/B/C) has **no clean live data yet**. The only run with all of it, Qwen on CSLib, was starved by cold Lean and stopped early.

## 7. Proof-level learnings (`v6pilot-proofs.md`)

- **One shortcut per theorem decides the score.** One or two models found it, and a model that missed it lost 10–22 points.
- **Heartbeats are nearly used up** (87–95% reduced). The token axis is where the points are now, and 1 token is worth about 14–19 HB, so `grind`/`simp_all` rarely pay.
- **New hybrids, all cold-verified:**
  - PhysLib **89.93**: DeepSeek's skeleton, Qwen's `hg _ (.smul_right ..)` and 4 small edits;
  - CSLib **86.76**: DeepSeek's proof with `symm_simulation ▸`;
  - Core 87.10, unchanged.
- **For the packet:**
  1. Add "library lemmas matching goal subterms", because the winning lemmas are not in the reference's dependency list. This is the biggest lever.
  2. State how tokens are counted: every identifier is one token, and so is each piece of punctuation.
  3. Prefer `_` over a restated lambda.

## 8. Next steps (proposed)

1. Run a **coverage campaign** with DeepSeek on the 4 rows that use provisioned workspaces: $0.50 each, 2 at a time, on the fixed harness. It costs about $2 and could raise the combined score from 28% to about 50%.
2. Add **library-lemma ranking by goal subterms** to the packet; in the PhysLib analysis this decided the score.
3. Build a **harness merge step** so hybrids come from inside the harness and its budget, which makes them submittable.
4. A clean A/B of exploration credit: run with frozen code, then compare route depth and new-goal-state share against this pilot.
5. Later, the deferred items: the memory-text improvements and F (hide the best proof) as an offline replay.
