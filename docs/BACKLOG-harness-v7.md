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
