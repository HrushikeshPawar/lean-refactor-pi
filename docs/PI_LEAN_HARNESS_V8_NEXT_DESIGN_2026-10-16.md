# pi-lean-harness v8 — next design decisions

**Verification strategy · agent ownership · packet audit · Lean performance experiments**  
**Date:** 16 October 2026 · **Status:** design proposal / read-only code review (not implemented)  
**Inspected code:** [`HrushikeshPawar/lean-refactor-pi`, `v8/02-stall-notes`, `03934d9`](https://github.com/HrushikeshPawar/lean-refactor-pi/tree/03934d9bacaf8c1e8413b2cfcef11f645a6e310c)  
**Source of operating constraints:** supplied `PLAN-harness-v8.md` and `2026-10-16-v8c.md`.

> **Central design principle:** The *agent* produces the refactored proof; the harness supplies precise context, Lean experiments, resource-aware verification, score feedback, and reproducibility. It must not silently improve the proof after the agent stops.

## 1. Decisions and open questions

| Item | Recommendation | Status |
|---|---|---|
| Check only oldest and newest Lean toolchains? | **Yes for inexpensive screening; no as a substitute for final all-version checks.** Test false-safe rate and wall-time saving before enabling by default. | Proposed experiment |
| Post-agent mechanical golf | **Disable.** Remove it from the normal `finish()` path. Do not substitute another automatic proof optimizer. | User decision |
| Agent refactoring | Agent proposes, runs experiments, inspects costs, and explicitly accepts its chosen final proof. Preserve full provenance in the candidate graph. | User decision |
| Proof-improvement cheatsheet | Offer a concise, neutral, cross-row playbook derived from v7–v8 results. No row-specific answer, hidden-stop hint, or unverified tactic claim. | Design to test |
| What goes into model packets? | Audit **actual captured provider requests**, not just the kickoff template. Compare byte/estimated-token share, utility, repetition, trimming, and cost. | Priority diagnostic |
| Lean bottleneck | Reuse the existing `arena lean bench` / `load-test` infrastructure first; distinguish queueing, header, elaboration, cold fallback, pinned-version verification, and memory pressure. | Priority diagnostic |
| Model spend | Retain strict per-problem closed-track cap of **$3 for all model calls** in a reproduced run. No experiment should compromise official verification. | Existing rule |

This revises the earlier v8 plan's *"harness does the mechanical golf, model does the ideas"* premise. The correct distinction is now **harness measures; agent refactors**. A research-only offline optimizer may still be used to discover generic lessons, but its outputs must not be silently inserted into competition submissions. Any such separate experiment must be labelled outside the agent-produced track.

## 2. Oldest/newest verification: quantified and guarded

### 2.1 Observed version distribution in the 15 development problems

Based on the checked-in [`benchmark/original/warmup.jsonl`](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/benchmark/original/warmup.jsonl):

| Versions per problem | Problems | All checks | Endpoint checks (deduplicated) | Checks saved |
|---:|---:|---:|---:|---:|
| 1 | 5 | 5 | 5 | 0 |
| 2 | 1 | 2 | 2 | 0 |
| 3 | 7 | 21 | 14 | 7 |
| 4 | 2 | 8 | 4 | 4 |
| **Total** | **15** | **36** | **25** | **11 (30.6%)** |

This is a **count**, not a time benchmark: different toolchains have very different header/import and elaboration costs. In the current `engine.evaluate()` fast path, three Putnam examples check both the first listed version and the newest measurement version. Other rows generally check the first listed version. On this warm-up set, that produces **18 version checks in the initial fast stage**. Under an endpoint-only promotion stage, the *additional* checks would fall from **18 to 7** (11 fewer, or 61.1% of those additional checks). Actual savings depend on queueing, caches, timeouts, and versions already known. [Engine source](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/engine.py#L769-L834).

### 2.2 Why endpoint success cannot certify the middle

Pinned versions are not necessarily ordered by an inclusion relation: library declarations, simp lemmas, imports, and tactic behavior can appear and disappear independently. The benchmark also pins **different source commits** or **Mathlib release commits**, not just a Lean executable. For example, the SKI row lists `v4.30.0`, `v4.31.0`, `v4.32.0`, and `v4.33.0-rc2`; fiberwise lists `v4.28.0` through `v4.31.0`. [Benchmark schema](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/benchmark.py) · [Organizers' rationale](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/contribution.md).

The organizer's scorer computes the mean of token reduction, heartbeat reduction, and compatibility; compatibility counts passes over **all listed versions**. A candidate that passes two endpoints but fails one of three versions can lose about **11.11 points on that problem**; with four versions, one failure costs **8.33 points**. Such a miss is large relative to the 1.93-point benchmark-average gap recorded in the attached plan. [Official leaderboard scorer](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/leaderboard.py).

### 2.3 Recommended staged policy

1. **Primary fast check:** preserve the compiler version used for measurement and required primary diagnostics. Never skip the heartbeat-measurement version.
2. **Endpoint screen:** if there are more than two distinct versions, check the oldest and newest (reuse any already-known results). Label the outcome **`endpoint-screened`**, never `fully-verified`.
3. **Full promotion:** for any contender likely to become the best or to be returned to the agent as verified, check **every remaining pinned version**. Order optional checks by measured time-to-rejection; do not treat a failure as an absent check.
4. **Cold certification:** retain final independent cold compilation on **every pinned version**, including middle releases, with heartbeat drift controls. [Current cold gate](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/campaign.py#L3625-L3650).
5. **Score fidelity:** intermediate compatibility remains explicitly **unknown** until checked. Never report a screen estimate as an observed full score or silently credit unknown versions.

**Important qualification:** This is an experiment, not an instruction to weaken the official check. The existing background queue is already ordered with `full` ahead of `salvage`; that fix should be retained. [Background checker](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/campaign.py#L3305-L3382).

### 2.4 Replay experiment before adopting the shortcut

Replay cached, previously observed candidates from SKI, Core, CCS, fiberwise, and the Putnam rows. For each candidate, compare endpoint outcomes against recorded **all-version** outcomes. Do this on an idle machine, with no LLM calls; classify exact toolchain hashes and commits. Include both correct and intentionally failing proof variants.

Collect: `(endpoint_pass, middle_pass, all_pass, elapsed_endpoint_s, elapsed_full_s, worker_peak_pss_gb, first_failed_version)` for each candidate; report **false-safe rate** (endpoints pass, a middle version fails), median/p95 time saved, and false-safe score penalty. Candidates with incomplete previous verification must not be counted as ground truth. **Decision rule:** if any false-safe occurs, endpoint checks remain a *screen only*; if no false-safe occurs, still retain the final full gate because the sample cannot prove monotonicity.

## 3. Remove post-agent golfing and preserve genuine agent ownership

### 3.1 What must change

Currently [`arena/cli/run.py`](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/cli/run.py#L903-L948) runs `closing_drain`, then—unless `--no-golf`—calls `closing_golf()`. [`arena/golf.py`](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/golf.py#L273-L350) tries and files new improved proofs after the model has left. This should **not run in the default competition pipeline**. The run should terminate with the agent's explicitly produced proof candidates, run pending *verification*, cold-certify the best eligible agent candidate, and summarize. Keep historical golf data for research attribution.

A related provenance audit is necessary for automatic **salvage**, **assembly**, and **cross-run recombination**. They can create valid combined/improved proofs not explicitly chosen by the agent. For strict agent-owned runs:

- A harness-generated suggestion may be shown **to the agent** as a proposal with its cost and provenance, but it cannot become the final answer unless the agent explicitly compiles/selects it inside its live run.
- After the agent exits: verification and faithful emission only; no new tactic deletion, rewriting, merging, salvage, or score optimization.
- Distinguish `origin=model`, `origin=agent-delegated-worker`, `origin=harness-suggestion`, `origin=research-offline` in the ledger; submission eligibility is defined by policy, not just `score > best`.
- Keep the full **$3** model-spend accounting, all-version cold gate, neutral wording, and hidden stop rule unchanged. The proposal must work in fresh, non-seeded runs.

The issue is *not* whether a mechanical step is clever; it is who chose it, who received its feedback, and whether the submitted proof really came from the reproduced agent process.

### 3.2 Agent-facing cheatsheet (short, grounded, neutral)

This is a candidate playbook section, not a solved proof. It should be available in the first packet and retrievable later; do not add all of it verbatim to every tool reply.

> **Proof-cost experiments**
>
> - Compare edits by **both** token count and measured heartbeats; fewer tokens can cost more heartbeats.
> - Identify high-cost tactic steps from the price/goal views. Try one specific hypothesis at a time, keep a short `note`, and compare against the previous best.
> - In `simp`/`simp_all` or `simp only [...]`, test whether individual lemma arguments are necessary. A smaller rewrite set sometimes reduces search, but may also break the proof.
> - Look for redundant `have` chains, repeated goals, unused binders, and repeated subexpressions. Shorter introductions such as `rintro -` are *candidate transformations*, not universal improvements.
> - Where proof states permit, test `simp only [..]` before more expensive search tactics such as `grind`; measure rather than assume an improvement.
> - A changed `rw`, `simp`, `exact`, or `apply` may behave differently across versions. Do not assume one successful version establishes compatibility.
> - Use `read`/`goal`/`search` for missing facts. Prefer step-anchored experiments to rewriting the full proof blindly.
> - Record meaningful failures as well as successes so a restarted run does not repeat the same variant.

This is based on observed v7–v8 notes: `rintro -` and `simp only` substitutions helped some rows; changing `simp only` to broad `simp` sometimes raised HB by hundreds or more. It does **not** claim any given change will work on every theorem. [Attached plan, §1 and §2](PLAN-harness-v8.md) (local source).

**Prompt rule:** Do not include a list of task-specific prepared proof edits, named winners, or externally discovered solutions. The playbook teaches **ways to investigate**, not preselects an answer.

## 4. Packet audit: what the agent actually receives

### 4.1 Current request topology (source-grounded)

The initial request is not a single text blob. It combines components with different lifetimes:

| Layer | Origin | Sent when | Present content / issue to inspect |
|---|---|---|---|
| System prompt | `agent-text/messages/run.yaml` | Run + provider context | A short Lean proof-optimization instruction; externalized. |
| Appended skill | `agent-text/skill/SKILL.md` via `arena.skill` | Run + provider context | Task contract, graph IDs, five tools, constraints, general work advice. **Currently says Lean checks are free** (misleading for wall time). |
| Tool schemas | `agent-text/tools/*.yaml`, registered in `packages/arena-pi/extensions/arena.ts` | Every provider request | `compile`, `goal`, `search`, `read`, `scratch`; full parameter descriptions can consume repeated context. |
| Initial theorem packet | `arena/context.py::packet_sections()` | First prompt / retained context | Statement, scoring and per-row rates, pin list, imports, full original proof + step prices, reference HB hotspots, original goals, types, scope, source-named declarations, dependencies, locals, related earlier and library declarations. |
| Optional prior work | `arena/seed.py::prior_work()` | Seeded/restarted scenario | Graph map, session digest, recent tool results, clipped previous thoughts/text. Full historical transcript is not preserved in a packet. |
| Tool replies + budget footer | `agent-text/replies/tools.yaml` + Pi extension | After each tool call | Candidate status, diagnostics, price updates, map/route information, new-best notifications and budget footer. Repeated content may be trimmed. |
| Continuations / restarts | `agent-text/messages/continuation.yaml` + `arena/campaign.py::restart_packet()` | Selected turns | Facts, focus material, restart start point, expensive steps, tried-idea digest, graph map; can replace prior conversation state. |
| Hidden internal control | Pi extension | Harness only | Hidden plateau/end safeguards **must not be disclosed via playbook or packet**. |

**Source links:** [initial section builder](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/context.py#L795-L901), [runner invokes Pi](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/cli/run.py#L556-L597), [Pi extension](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/packages/arena-pi/extensions/arena.ts#L602-L697), [seed digest](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/seed.py#L232-L297).

The kickoff builder caps its assembled packet at **40,000 characters**, not a tokenizer-derived provider token budget (`agent-text/numbers.yaml: packet_max_chars: 40000`). Under pressure, it trims earlier declarations, excess goals, locals, and library entries in a fixed priority order; it certifies required-section presence before fitting. This is better than blindly truncating the whole request, but might still preserve verbose low-utility sections while removing a useful nearby fact. [Fitting algorithm](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/context.py#L760-L781).

### 4.2 Six packet questions to answer with real traces

1. **What is actually sent?** Compare `packet.txt`, constructed initial sections, *post-hook provider payload*, and later request contexts; distinguish changed prompt text from cached/repeated context.
2. **Where do tokens go?** Estimate tokens and raw bytes by `system / skill / tools / initial-packet sections / user+assistant messages / tool replies / restarts`. Track provider-reported usage and cache-read/write separately. Character counts are not enough.
3. **What does the model use?** Link subsequent calls and candidate changes to recently displayed goals, hotspots, dependency names, source snippets, and previous-failure facts. Correlation is not proof of causal utility; A/B tests come later.
4. **What gets lost or duplicated?** Repeated signatures, old goal states, clipped search results, unreadable thinking, stale costs, missing `note`s, and seed digests that repeat earlier exploration.
5. **How does the packet change?** Compare first prompt, second turn, after a full-check improvement, after a stalled route, after compaction, and after a seeded restart.
6. **Does it induce poor behavior?** In particular, does "Lean checks are free" encourage excess scratch/compile calls, or does the massive dependency/context section distract from the highest-cost step?

The extension **already persists complete post-hook provider payloads as a delta journal**, plus content-addressed blobs for system, skill, tool definitions, and the first user packet. [`splitRequest()`](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/packages/arena-pi/extensions/journal.ts#L72-L87) and [`before_provider_request`](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/packages/arena-pi/extensions/arena.ts#L255-L287) make this review feasible **without changing the live prompt**. [`arena.traces.read_journal`](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/traces.py#L266-L335) reconstructs recorded payloads. The stored `packet` blob is simply the *first user message*, not necessarily the initial theorem packet on all subsequent turns; the full `post_hook` must be inspected for restarts and accumulated conversation.

**Limitation:** The GitHub repository contains packet templates and tracing code, but it does **not** provide a representative local `runs/.../packet.txt` and provider trace from the user's machine for this review. Therefore token shares, repeated-context rates, and packet-effect estimates are **not measured yet** and should not be presented as facts.

### 4.3 Proposed output: one packet diagnostic per run

Produce a read-only `packet-audit.json` and a readable short report from a run's journal:

| Metric | Intended interpretation |
|---|---|
| Initial packet: chars / estimated tokens by section | Which parts consume the kickoff budget |
| Tools + skill: estimated tokens | Fixed per-request overhead and provider-cache opportunity |
| First vs later requests: total / cached tokens | Whether unchanged context is cheap or expensive for the selected provider |
| Tool-reply bytes and trimmed bytes, by tool | Context growth from each interface |
| Repeated signatures / stale facts | Candidates for compaction or deduplication |
| Source/search/read material used in later calls | An approximate measure of context utility |
| Time from full verified update to next provider request | Whether the agent gets important verification feedback in time |
| Missing `note` count and route repetitions | Whether the agent's learning survives a restart |

**Auditing approach:** Keep the first experiment read-only and use existing trace reconstruction. Then run a small A/B of **baseline packet** vs **compact packet plus cheatsheet**, with the same row, model, spend cap and Lean environment. Use multiple attempts where affordable; one outcome is not a reliable efficacy estimate. Preserve the protected sections: statement, scoring rule, pins, original proof, and enough local context to make the task feasible. Do not change hidden stop messages.

### 4.4 Three immediate packet edits worth testing (not yet shipping)

- **Fix the false economic cue:** Replace "Lean checks are free" with "Lean checks do not use API dollars, but consume wall time and memory; prioritize informative tests." Keep the rest of the agent's freedom intact.
- **Insert a small experiment cheatsheet/playbook:** concise ideas with explicit uncertainty, available on demand after startup rather than pasted into every compile reply.
- **Make candidate intent durable:** require a short neutral `note` (or non-blocking warning if enforcement causes tool errors). Keep failed experiments and their goals in the graph so continuation packets summarize meaningful hypotheses, not only scores.

Do not shrink dependency information or remove tools before inspecting the trace: a declaration that looks unimportant in an initial packet might enable the successful proof found later.

## 5. Lean engine test — use existing tooling first

### 5.1 Known instrumentation, not a new benchmark from scratch

The repository already implements [`arena lean bench`](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/cli/lean_bench.py): checks `sorry`, unchanged reference, edited text, error paths, and early/late **comment splices**, while recording p50/p95 latency, worker PSS, free RAM, CPU clock, and temperature. It compares against a saved baseline and distinguishes first/second header opens. [`arena lean load-test`](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/cli/lean_load.py) separately exercises concurrent model/background work and timeout recovery. Do **not** run these during a live paid campaign.

Lean's own server architecture supports reusing syntax and elaboration snapshots across document edits, with limitations at intra-tactic boundaries. Therefore, an incremental-reuse experiment is well grounded, but its benefit depends on the pinned Lean version and the actual edit. [Lean server architecture](https://github.com/leanprover/lean4/blob/master/src/Lean/Server/README.md) · [Incremental elaboration](https://github.com/leanprover/lean4/blob/master/src/Lean/Language/Lean.lean).

### 5.2 Experimental matrix (idle machine, pinned toolchains)

| Phase | Rows | Comparison | Measurements | Question answered |
|---|---|---|---|---|
| A. Baseline | Core, SKI, Putnam b2, fiberwise | Existing `lean bench` cold/warm openings, reference/errors, early/late *comment* splices | p50/p95, header seconds, peak PSS, CPU clock | What is import cost vs request cost? |
| B. Realistic incremental edits | SKI, fiberwise | Valid proof edits near the beginning, middle, and end, warm LSP vs fresh cold Lean | compile wall seconds; `changed_from_line`; correctness; HB | Does tactic-level incremental reuse materially help us? |
| C. Engine choice | SKI, Core | Existing LSP, eligible REPL, cold `lake env lean`; **same proof** | acceptance parity, HB parity where measurable, peak PSS | Is a wider REPL fast path safe? |
| D. Concurrency | SKI, Wick or fiberwise | 1, 2, and 3 workers plus one pending background full check | completed verifications/min, queue wait, RAM/swap/PSS, p95 latency | Is worker crowding the actual bottleneck? |
| E. Version screen | SKI, fiberwise, Core, CCS, Putnams | Endpoint-only vs all-version replay of known proofs | false-safe, wall-time saving, per-version failures | Is endpoint screening worth adopting? |
| F. Live feedback | One short cap-limited from-scratch run | existing packet vs compact/cheatsheet packet | cost, proof score, compile/scratch calls, stale full-check age | Does more targeted context improve the agent loop? |

A and E can run with **zero LLM spend**; F is deliberately last. A's early/late edits are comments in the current benchmark and therefore **do not prove** that real tactic rewrites enjoy the same incremental reuse. Phase B must be added for that question.

### 5.3 Concrete first commands (to run on the user's idle checkout)

```bash
# Baseline the same toolchains before changing Lean execution code.
.venv/bin/arena lean bench \
  --rows Cslib.SKI.parallelReduction_diamond \
  --versions all --repeats 3 \
  --out runs/analysis/bench/next-ski-all

.venv/bin/arena lean bench \
  --rows Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius \
  --versions all --repeats 3 \
  --out runs/analysis/bench/next-fiberwise-all

# Existing quick concurrency smoke. Run separately, never beside a campaign.
.venv/bin/arena lean load-test \
  --rows Core.InitsUpdatesComm --runs 1 \
  --concurrency 1 --background 0 --minutes 2 \
  --max-checks 2 --weights slow=1 --timeout 20
```

These commands are grounded in the current CLI definitions; **none was executed here**. Change row/version selection only after confirming local provisioned projects and no active campaign. The load-test invocation is a smoke check, not the full concurrency matrix. Avoid overheating/page-cache confounding: repeat a suspect comparison on an idle machine and record CPU frequency/temperature rather than treating one wall-clock sample as a compiler regression.

### 5.4 What to instrument if the current bench leaves gaps

Collect spans **outside** Lean too: `candidate_file/git show` time, waiting for the model-lane lock, waiting for service token, header open, Lean check, converting diagnostics, `record_evaluation` ledger/I/O, the full-check queue, and any `cold-fallback` path. The runner currently builds candidate text using a `git show` command, and the server can fall back to fresh compilation if a session request fails. [Candidate construction](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/engine.py#L236-L279) · [Cold fallback](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/engine.py#L580-L642).

A running checker must not starve new high-value checks, especially after the documented v8c starvation (29–33 minute gaps). Add **phase start/end**, **checker job start/end**, queue depths, and age of latest *fast* versus latest *full* result to the operator log and viewer before attempting preemption. Keep background worker memory measured: in v8c, free memory reached roughly 7.8 GB under two jobs. The proposed timing diagnostic should make it possible to say which of these is dominant: (i) actual Lean elaboration, (ii) imports/worker startup, (iii) CPU/RAM contention, (iv) queue scheduling, or (v) redundant candidate evaluations.

## 6. Small delivery sequence (no broad rewrite yet)

1. **Decision/spec first:** record the agent-ownership rule; make post-run golf disabled by default, and review whether salvage/assembly/hybrids violate the same rule. Preserve existing historical outputs; do not delete them.
2. **Packet audit first, no prompt change:** reconstruct 2–3 prior run traces, produce section and request token breakdowns, inspect tool replies and stale facts. If run journals are unavailable, inspect a future run rather than inventing numbers.
3. **Lean baseline:** use existing bench and load-test scripts on the idle laptop; add only the real-tactic-edit and request-span instrumentation missing from current tests.
4. **Endpoint A/B:** replay known candidates; test *screen then all-version promote* against original all-version promotion, with no LLM spend.
5. **Cheatsheet A/B:** one compact row-independent agent playbook, `note` preservation, and corrected Lean-cost language. Test the same from-scratch task and budget before broadly shipping.
6. **Only then** consider adaptive worker count, more REPL checks, richer step-local tools or agent-delegated minions. Require documented performance wins and strict provenance.

### Acceptance gates

- **Correctness:** a chosen final proof passes every pinned version under cold certification; recorded HB is within the existing tolerance.
- **Agent ownership:** every selected proof is directly authored, explicitly accepted, or intentionally delegated **by the running agent**; no post-exit proof transformation.
- **Score fidelity:** no missing intermediate check is represented as a pass or as a full score.
- **System health:** no orphan Lean workers, uncontrolled swap, or hidden background check starvation; model-lane p95 is not worsened materially by new workers.
- **Efficiency:** compare verified gain per Lean-minute, not just nominal number of skipped versions or number of candidates.
- **Packet value:** trace-backed changes yield less low-value repetition or better measured agent behavior; preserve the original reference, pin information, and clean tool feedback.

## 7. Evidence register and limitations

**Current implementation (pin `03934d9`):**

- [Benchmark pinned versions](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/benchmark/original/warmup.jsonl)
- [Engine versions, fast/full evaluator](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/engine.py#L769-L834)
- [Cold verification](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/campaign.py#L3625-L3650)
- [Runner finalization and golf invocation](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/cli/run.py#L903-L948)
- [Kickoff packet assembly](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/context.py#L795-L901)
- [Packet budgeting](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/context.py#L760-L781)
- [Actual provider request journaling](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/packages/arena-pi/extensions/arena.ts#L255-L287)
- [Snapshot / packet decoding](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/packages/arena-pi/extensions/journal.ts#L72-L87)
- [Lean benchmarking infrastructure](https://github.com/HrushikeshPawar/lean-refactor-pi/blob/03934d9bacaf8c1e8413b2cfcef11f645a6e310c/arena/cli/lean_bench.py)

**External references:**

- [Organizer benchmark schema](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/benchmark.py)
- [Official compatibility and score logic](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/leaderboard.py)
- [Organizer explanation of pinned cross-version proofs](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/contribution.md)
- [Lean language-server architecture](https://github.com/leanprover/lean4/blob/master/src/Lean/Server/README.md)
- [Lean incremental processing details](https://github.com/leanprover/lean4/blob/master/src/Lean/Language/Lean.lean)

**Limitations:** This document is a **source-level architectural analysis**, not a measured result from the user's laptop. The 36-to-25 toolchain count is calculated directly from the checked-in 15 warm-up records; saved *wall time* is not yet known. Packet construction and journal recording were inspected, but actual session request payloads and historical local Lean timings were not available in the current workspace. The recommended actions are therefore design proposals and experiments, with exact correctness and resource gates stated explicitly.
