# v5 harness across five theorems — results and findings (2026-10-07)

Morning report for the overnight runs. Harness v5 unchanged except for the generality fixes made before the runs
(wrapper placement before doc comments, qualified Lean names, packet scope section, MCP prewarm). Every run: $0.10 cap,
thinking high, GPT-6 Luna (OpenAI Responses path) and Qwen3.8-flash (Anthropic Messages path).
Raw per-analysis reports: `runs/analysis/reports/*.md` (not in git). Verified hybrid proofs: `runs/analysis/*-hybrid-*.lean`.

## 1. Results at a glance

| Theorem (family) | Reference | Versions | Luna best | Qwen best | Best hybrid (verified) |
|---|---|---|---|---|---|
| `Core.InitsUpdatesComm` (Strata) ×3 replicates | 224 tok / 4251 HB | 3 | 74.72 / 74.00 / 76.51 | 81.76 / **84.58** / 73.79 | **87.10** (76 / 203) |
| `CallElimCorrect.extractedOldExprInVars` (Strata) | 222 / 2696 | 1 | **72.29** (141 / 529) | 53.86 (236 / 866) | **82.42** (77 / 487) |
| `CallElimCorrect.substOldPostSubset` (Strata) | 313 / 5175 | 1 | **52.45** (239 / 3431) | none compiled | **82.86** (26 / 2231) |
| `Cslib.CCS.bisimilarity_congr_choice` (CSLib) | 251 / 3858 | 3 | **78.55** (137 / 377) | 78.45 (139 / 358) | **84.52** (92 / 378) |
| `fundamental_theorem_of_variational_calculus'` (PhysLib) | 851 / 11947 | 1 | 45.91 (844 / 7536) | **83.35** (268 / 2205) | not built (see §6) |

Scores are the local proxy (mean of token %, heartbeat %, compatibility %); the original proof scores 33.33. The naive
unharnessed baseline on InitsUpdatesComm was 76.72.

Headline: **neither model is better in general; the theorem decides.** Qwen wins big when a structural rewrite exists
and is found by looking things up (InitsUpdatesComm 2/3, PhysLib +37 points); Luna wins when the route is one cheap
trial away or reachable by golfing (extract, subst; CSLib tie). And on every theorem with a hybrid attempt, a proof built
only from the runs' own ingredients beats the best model run by 2.5–30 points.

## 2. What decides the score (cross-theorem)

| Lever | InitsUpdatesComm | extract | subst | CSLib |
|---|---|---|---|---|
| Decisive idea | induction-free route via 3 in-file lemmas | induct on the derivation `H`, imported ListUtils lemmas | intro the element *before* induction, then one uniform `grind` | `Bisimilarity.follow_fst/snd` (imported) as term closers |
| Where the key information lived | same file, 600 lines above (outside packet window) | imported project file | core lemmas + restructuring | imported project file |
| Who found it | Qwen 2/3 (search-first) | Luna (cheap trial, $0.028) | Qwen had the idea, failed on `tauto` (no Mathlib) | Qwen $0.020, Luna $0.067 |
| Rest of the gap to the hybrid | generic golfs | removing dead code and failing `<;> try exact` | the restructure itself (+30 pt) | scaffolding only (+6 pt, all tokens) |

What generalises:
1. **The key lemma is almost never in the packet.** In 4/4 theorems the decisive lemma was outside the packet: in-file
   but far above (InitsUpdatesComm) or imported from another project file (extract, CSLib). Discovery by search decides
   runs, and search is unreliable (small default limits, duplicates, `index: warming/error`).
2. **Luna golfs locally with many short turns; Qwen thinks deeply in few turns.** Which wins depends on the theorem:
   deep search wins when the route is hidden (InitsUpdatesComm); cheap trial wins when the route is one tactic away
   (extract) or reachable by golfing (CSLib). Qwen's depth can also exhaust the budget before any candidate exists (subst).
3. **Models stop at the leaves; the remaining points are in scaffolding.** Every hybrid's gain over the best run came
   from structure the models never touched: merged intro chains, positional goal handling, shared closers, dead code.
4. **Generic transformation rules mostly hold, with theorem-specific exceptions** (§4).

What does not generalise: "look far up the file for lemmas" (only InitsUpdatesComm), "avoid grind" (grind was the best
uniform finisher on subst but useless on CSLib), "Qwen wins".

## 3. Harness findings (all theorems)

### Cap and cache — Qwen deep cuts correlate with cache misses (P0)
In these v5 runs, all three Qwen final requests whose reconstructed output cap fell below ~4.5K lost the
provider's whole prompt cache; eight larger cuts kept it (Luna used a different OpenAI path).

| Run | Reconstructed `max_tokens` cap after cut | Cache |
|---|---|---|
| InitsUpdatesComm r2 | 4,520 | **miss** ($0.028) |
| subst | 1,486 (thinking dropped) | **miss** ($0.031) |
| CSLib | 3,738 | **miss** ($0.022) |
| all other Qwen cuts (8 requests) | 5,472 – 13,807 | hit |

Thinking budgets at the misses were 3,496 / none / 2,714, at hits ≥4,448. Pi's high setting starts at
16,384 thinking tokens, and the harness's `boundedPayload` changes that budget on **all 11** cut Qwen requests,
including the eight cache hits. A thinking-budget change alone therefore does not distinguish hit from miss.
Actual generated output on the three misses was 2,095 / 1,486 / 242 tokens; the table values are request caps,
reconstructed from the guard and cost ledger because v5 did not retain the final outgoing payload.
Anthropic documents that such changes can invalidate cached prefixes, but this is an Anthropic-compatible Qwen
host; its exact cache rule is unverified. Two misses followed the prior request by under 20 seconds, so ordinary
cache expiry is unlikely. The logs lack outgoing wire payloads. A direct Pi experiment with identical synthetic
prefixes at ~35K and ~122K cached tokens **hit** at the historical 4,520/3,496 and 3,738/2,714
output/thinking settings. At 1,486, removing thinking selected a separate reusable cache entry. Thus output
cap or thinking-budget changes while thinking stays enabled do not suffice to reproduce the r2/CSLib misses;
removing thinking plausibly explains subst. An exact historical replay is unavailable because the v5 session
projection omits the old system prompt, tool schema, cache marker placement and final wire payload. V6 must
capture these before assigning provider-internal causes.
For production, refuse a request before send if the unchanged request risks breaching the cap.
Related: the harness sent continuations after Qwen declared it was done (CSLib: 3 more turns, the last one the miss).

### Context and tools
- Packet lemma coverage must include **imported project lemmas**, not only the theorem's file (extract, CSLib).
- Packet should list **constructors of local inductives** (CSLib's private `ChoiceBisim`) and state **which tactic
  libraries exist** (subst: `tauto` assumed, project has no Mathlib).
- Goal trace is shown after the reference's normalising `simp`, which re-associates appends and misled both models (extract).
- `lean_local_search` returns `.lean-stdlib/...` paths that `arena_source` refuses (extract, subst); small default
  limit missed key lemmas; index reported `warming`/`error`.
- `arena_declaration` still prints mangled private names (`_private._stdin.0...`); the packet fix did not reach the tool.
- Invalid JSON tool arguments from Qwen are silently turned into `{}` by Pi (subst: 4 `arena_idea` errors).
- Recurring input errors: `strata/` path prefix, probe bodies starting with `by`, a leading newline before the statement.
- Probes with `sorry` sometimes return no `goals` field despite the packet promising goals.
- `arena_polish`: 0 gains in 8 more calls (one 307 s, incomplete). Remove.
- Background checks: 100% coverage everywhere, 0 version failures on CSLib's 3 toolchains; latency up to 250 s while two
  runs competed for CPU.
- New packet scope section: accurate, no namespace/unknown-name errors on CSLib/PhysLib (helped by not hurting).

## 4. Proof-transformation lessons for the v6 skill

Held on every theorem where applicable:
- Count tokens literally: brackets, commas, `_`, bullets cost; dotted names cost 1 regardless of length.
- No bullets; positional goal handling (`iterate`, `rotate_left`, `swap`, `rename_i`) over case headers.
- One shared `all_goals` closer for identical goals.
- Avoid `simp_all` and `simp … at *` (dominant heartbeat cost on subst: 2,633–3,838 HB).

Theorem-dependent (teach as trade-offs, not rules):
- `grind` as a uniform finisher: excellent for propositional membership (subst), fails on grind-tagged inductive
  predicates (CSLib).
- `<;> try`/`first` chains: cheap only when alternatives succeed or fail fast; each failed `exact` forces unfolding of
  recursive definitions (extract: +250–330 HB).

New traps:
- `any_goals exact …` is not a filter: `exact` error-recovers and closes non-matching goals with `sorry`.
- Or-patterns on a multi-constructor indexed family bind names by position across all constructors.
- `use` elaborates arguments separately (implicits and `_` fail); `exists`/`refine ⟨…⟩` unify jointly.

## 5. Implications for v6 (see docs/WORKING-harness-v6-decisions.md)

1. **P0 discovery** extends to imported project lemmas, with signatures, ranked by shared head symbols; search results
   de-duplicated and counted in distinct names; `arena_source` accepts the paths search returns.
2. **P0 request stability:** do not reshape `max_tokens` or `thinking.budget_tokens` at the cap edge; gate the
   unchanged request against the competition's $3/problem allowance and respect the model's own stop.
3. **New P1:** packet lists local inductive constructors and available tactic libraries; goal trace before normalising
   simp; Pi's silent `{}` for invalid tool JSON surfaced as an error; readable names in `arena_declaration`.
4. **Skill:** the §4 rules, with grind and `<;>` as explicit trade-offs.
5. **Experiment priority:** exact Langfuse traces, original-proof reference inventory, batched complete-body
   lookup and source/tool repairs precede any relay trial. The hybrids are analyst-built; they establish
   headroom in proof scaffolding, not a measured benefit from switching models.

## 6. PhysLib

`fundamental_theorem_of_variational_calculus'` (851 tokens, 11,947 HB, one version). Qwen **83.35** (268 tok / 2,205 HB)
in 25 requests; Luna **45.91** (844 / 7,536) in 70 requests. The largest gap of the night.

- **Decisive change (Qwen):** the reference embeds `f` into `WithLp 2 V` (`toL2`) to work in a genuine inner-product
  space; Qwen dropped the embedding and worked directly with PhysLib's `InnerProductSpace'` API (`inner_self_eq_zero'`,
  `real_inner_self_nonneg'`, `Continuous.inner'`, `inner_smul_right'`), with a bump-function test `φ x • f x₀` and
  `integral_pos_iff_support_of_nonneg`. Its first candidate was already structural (337 tok, 80.04); two refinements
  reached 83.35.
- **How it got there:** 15 `arena_declaration` and 11 `lean_local_search` calls plus 5 source reads before and while
  drafting; mean 3,816 output tokens per request (max 15,174). Same "look things up, think deeply" pattern as its
  InitsUpdatesComm wins.
- **Luna:** kept the `WithLp` structure and golfed it locally (9 candidates between 844 and 908 tokens); 27 `lean_goal`
  and 13 `lean_multi_attempt` calls; 46 of 70 requests were context turns.
- **Harness:** MCP prewarm worked (40 Lean MCP calls, no timeouts); no cache miss or overshoot (Qwen's final requests were
  not deeply cut: $0.0022 overshoot); one `STATEMENT_MODIFIED` (Luna) and one idea marked succeeded without a reason
  (Qwen); the scope section's `variable`/`open` context produced no unknown-name errors.
- **Not done:** the dedicated PhysLib proof-level hybrid search and the per-model deep dive were cut short by an account
  usage limit at ~03:50 (resets 05:30 IST). The facts above come from direct inspection of the run files. A hybrid
  attempt (Qwen's structure with Luna-style local golfs) is the obvious next step; the exchange rate here (1 token ≈ 0.039
  pt, 100 HB ≈ 0.279 pt) favours heartbeat reductions.

## 7. Spend

Overnight runs: 8 runs, **$0.857** in total (overshoots: Qwen subst $0.030, Qwen CSLib $0.020, others ≤ $0.002).
Analyses and hybrid compiles: local only (no model cost beyond this session).
