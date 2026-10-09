# Harness v7 backlog (noted 2026-10-08)

Agreed for v7, not started. The deferred v6 items (compaction memory text, F: hide the incumbent proof) stay in
`docs/WORKING-harness-v6-decisions.md` under "Next improvements" and carry over to v7 unchanged.

## 1. Library dependency graph: definitions one level down

**Why.** A library lemma costs one token and almost no heartbeats (its proof is already compiled), and the rules
forbid auxiliary declarations, so finding the existing lemma that carries the argument is the main structural lever.
DeepSeek won PhysLib and CSLib this way.

**What exists (v6, `sxv`).** The packet ranks imported lemmas by IDF-weighted constants shared with the statement,
its goals and source-named lemmas. That is one hop: theorem → its constants → lemmas mentioning them.

**Gap.** A lemma about what a definition is built from (say `List.foldl` under `InitStates`) shares no constant
with the statement and is never ranked. Add one hop of definition unfolding: the constants in the bodies of the
statement's definitions join the wanted set at a lower weight.

**Not a model tool.** Every extra tool adds bookkeeping calls (Luna spent 26% on bookkeeping in `v6check`).
Compute offline and put the result in the packet.

**Experiment before enabling (free: Lean only, no model calls, about 15 min).**
1. Answer key: for the 5 rows with a best proof, the lemmas it uses that the reference does not.
2. A switch in `arena/lean/context.lean`'s library scan adds the unfolded constants (weight about 0.4).
3. Scan each row with the switch off and on, one Lean process at a time.
4. Output `runs/analysis/experiments/unfold-ranking.md`: answer-key ranks before and after, and packet sizes.
5. Pass: answer-key lemmas rise on average, PhysLib's winner stays 1st and CSLib's in the top 5, packets stay
   under 40,000 characters. Only 5 rows have an answer, so this is a sanity check.

## 2. Routes identified by their subgoals

**Why.** The v6 fingerprint (lemmas 0.45, recursion 0.25, claims 0.20, logic 0.10) measures vocabulary. It merges
genuinely different approaches that use the same lemmas (generalising first, a different characterisation, one
automation call replacing a manual argument), and lemma swaps can open a "new" route without new mathematics. It
also fits the pilot's two winning moves (drop the induction, use one strong lemma), which is 3 theorems of evidence.

**Proposal.** A route is how the proof breaks the problem down: the top-level step (main lemma or recursor) and the
statements of the subproblems it leaves. Lemmas and recursion stay as secondary data for analysis. A proof that is a
single automation call has no subgoals and forms its own "closed directly" route.

**Experiment before enabling (free: Lean only, about 1–1.5 h).**
1. Input: every stored attempt of the 9 `v6pilot` runs and `v6check`.
2. Add a separate subgoal-signature output to `arena/lean/route.lean`; live credit is unchanged.
3. Re-extract every attempt cold, one at a time under the memory guard.
4. Compare per run: route counts (Luna's PhysLib trims should stay one route), whether DeepSeek's key rewrites still
   open routes, and a short verdict on each attempt the two methods classify differently.
5. Output `runs/analysis/experiments/route-by-subgoals.md`. No harness change until it is reviewed.

## 3. Also carried over

- Harness merge step, so hybrid rows come from inside the harness and its budget (needed for closed-track rules).
- A live compaction test: `v6check` never crossed Luna's 200K threshold (max prompt 194K), so compaction and the
  memory message are unverified on the fixed harness.

## 4. Findings from v6cov runs 1–2 (2026-10-09, a4 and b2)

### 4a. Compaction must bypass the budget guard (agreed fix)

**Seen.** All compactions failed: 25 in a4, 24 in b2 (`Arena context bound exceeds the context window`). The
context only grew (a4 ended at 696K tokens), so b2's single provider cache miss cost $0.0845 on 563K uncached
tokens.

**Cause (harness, not Pi).** The compaction summary request goes through the same guard as model turns
(`packages/arena-pi/extensions/budget.ts` `boundedPayload`). It is not a growth of the prior request, so the guard
falls back to one token per byte. Payloads run about 2.9 bytes per token, so DeepSeek's summary request "exceeds"
the 1M window from about 345K real tokens, below the 500K trigger.

**Fix.** Compaction is a required step and always within budget, so it never passes the window check or the cost
gate. Pi marks it with `session_before_compact`, and its usage is still settled in the cost ledger so spend stays
exact. Model turns are unchanged.

### 4b. Credit for opening a route: where the branch starts (needs thought)

**Seen.** In a4, `finish` was refused 25 times. Each refusal was followed by a batch of `sorry` skeletons that differed
only in one or two `have` statements. Each opened a "credited" route, giving 311 route openings and
"165 credited routes, 4 explored", with no score gain after #19 ($0.32 spent after the best). a4's candidate graph is
a chain 28 deep, and 292 of about 360 probes hung off the deepest node. In b2 (chain 48 deep) deep refinement found
the best (#80, about depth 47).

**Idea.** For `finish` credit, require a new route to branch from a shallow node of the candidate graph, so new
routes start where diversity is likelier. Normal work from any node stays allowed.

**Open questions.**
- Shallow as an absolute level (1–2), relative to graph depth, or "off the current best's ancestor chain"?
- Parents are labels (the default is the current candidate; the model may name any parent). How do we verify a draft
  really came from its stated parent? Text similarity to the parent can backfire: a genuinely new draft resembles no
  node, and a small edit of the tip can be relabelled. Needs a design, not a quick fix.
- Must stay content-neutral: the rule may say where to branch, never what kind of proof to write.

### 4c. Refusal message grows with the route count

The `finish` refusal lists every route, which reached about 10K characters in a4 (165 routes) and is re-read in
context each time. Cap the list and summarise the rest in one neutral count.
