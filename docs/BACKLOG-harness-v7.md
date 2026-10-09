# Harness v7 backlog (noted 2026-10-08)

Agreed for v7, not started. The deferred v6 items (compaction memory text, F: hide the incumbent proof) stay in
`docs/WORKING-harness-v6-decisions.md` under "Next improvements" and carry over to v7 unchanged. Bugs and fixes found in runs are listed in `docs/ISSUES-harness-v7.md`.

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

## 5. Overhaul: candidate graph and tool UX (agreed for v7, 2026-10-09)

The candidate graph and the tool surface grew one fix at a time through v5–v6. v6 showed that both need a redesign,
not more patches. This section sets the scope. The individual defects stay listed in `docs/ISSUES-harness-v7.md`,
and this overhaul should close them.

### 5a. Candidate graph

**What is wrong today.**
- **Parents are labels, not facts.** An unnamed parent defaults to the last-materialized candidate. In a batch, that
  is the last draft, whatever it scored. By text, the label is wrong 21/30 to 35/50 times in the long v6 runs
  (ISSUES #5a).
- **Two jobs share one state.** `current` means both "the file the Lean tools read" and "where the next proof came
  from".
- **Probes, candidates, ideas and routes are four separate structures** with their own ids (`pN`, `#N`, `iN`, `rN`).
  They are linked loosely: an unknown `idea_id` becomes a label, idea credit is per call, and routes are filed after
  the run ends (ISSUES #5, #32).
- **Every downstream number inherits these flaws:** graph depth, which node was expanded, route and finish credit,
  shallow-branch credit (§4b), and the viewer.

**Design goals.**
1. **One node type.** Every draft the harness compiles, closed or not, is a node with a stable id. "Candidate" is a
   status (compiled, scored, verified per version), not a different object.
2. **Measured lineage.** The harness records the parent from the text: the closest existing node by a token-level
   diff. The model's named parent is kept as a separate field, and both are reported. The diff size is stored on
   the edge.
3. **Separate the Lean focus from lineage.** The materialized file is an explicit focus the model sets, or the best
   node after a batch. It never decides lineage.
4. **Routes and ideas as views.** A route is computed over the node graph (the backlog §2 subgoal signature), live
   during the run, not filed afterwards. An idea is a model annotation on nodes, never a parent.
5. **One event log, append-only, with every edge typed:** `derived_from` (measured), `named_parent` (model),
   `restored_from` and `merged_from`. The viewer, summary and credit all read this one log.
6. **Re-derive the v6 graphs** from stored proofs with the new lineage, and redo the §4b analysis on true parents
   before any credit rule uses depth.

### 5b. Tool UX

**What is wrong today.** There are 11 `arena_*` tools plus the Lean MCP tools, with overlapping jobs and
inconsistent replies:
- **Probe, evaluate and candidate overlap.** `from_probe` and `candidate:"#N"` exist because of that.
- **Search is split** across `arena_find`, `arena_declarations`, `arena_source` and `lean_local_search`. Each has
  its own handle forms and miss messages (ISSUES #18, #28, #31).
- **Probe replies give one error per draft and are untrimmed** (ISSUES #9, #10, #30). Cross-version results arrive a
  turn late (#17).
- **Errors are not actionable:** batch rejections without naming the item, malformed arguments read as missing
  fields, and wrong continuation text (#26–#28).
- **Bookkeeping cost.** Luna spent 26% on bookkeeping in `v6check`, and every extra tool adds calls.

**Design goals.**
1. **Fewer, orthogonal tools.** About five:
   - `compile`: one to four drafts, any status. Returns all errors, goals at holes and a score when closed.
   - `search`: one interface over names, text and the core library, with one handle form.
   - `read`: source by handle or range.
   - `profile`.
   - `finish`.
   - `state` and `restore` fold into compile and read replies where they can.
2. **One reply schema** for every tool:
   - `ok`;
   - `facts` (short lines);
   - `items` (per-draft or per-name results, each with its own error);
   - `next_handles`;
   - the budget footer.
3. **Deduplicate by content.** Repeated goals or diagnostics say "same as pN" and keep the full text on disk.
4. **Every error names the bad input and lists the valid forms.** No silent coercion: a malformed or empty argument
   is reported as malformed.
5. **Results arrive when ready.** Cross-version results that land during a call are attached to that call's reply.
6. **Facts only.** No reply suggests a kind of proof or a route. Graph position and per-axis numbers are fine.
7. **Measure before and after.** Use the same rows and model at the $0.50 cap. Measure the bookkeeping share, tool
   errors per run, calls before the first compile, and the proxy. The overhaul ships only if bookkeeping and errors
   fall without a proxy loss.

### 5c. Order of work

1. Do the lineage re-derivation on v6 data first (free: no model calls). It shows how different the true graph is,
   and it unblocks §4b.
2. Ship the graph model and event log behind the existing tools, and check that the viewer and summary match the
   re-derived v6 graphs.
3. Ship the new tool surface on top. Rewrite SKILL.md and the packet together, with a test that the packet, the tool
   descriptions and SKILL.md state the same rules (ISSUES #4).

## 6. Submission build and final verification inside the harness (agreed for v7, 2026-10-09)

**Today, by hand.** Submissions v1–v3 were put together outside the harness by analysis agents using ad hoc
scripts (`runs/analysis/submission-v*/build.py`, `verify.py`, `run.sh`):
- pick each row's best proof across runs and offline hybrids;
- check that each proof starts with the exact benchmark statement (`arena.engine.validate_proof`);
- apply the official forbidden-content filter (`_check_forbidden` from `vendor/arena-space/app.py`, loaded via
  `ast` because the app imports gradio);
- cold-compile every row on every toolchain, one at a time under a memory wait;
- write the `submission.jsonl` files and a hand-written MANIFEST.

None of this is reproducible from the harness code, and hybrids are a rules risk for that reason (BACKLOG §3).

**Proposal: `tools/arena_submit.py`, one command run after a campaign.**
1. **Select.** For each benchmark row, take the best cold-verified candidate across the named runs or prefixes.
   Selection uses the settled score, never a label. Rows with no run are kept from a named previous submission.
   Missing rows are listed.
2. **Merge (optional).** Hybrids come from the harness merge step (BACKLOG §3), run inside the budget and recorded
   as candidates. Nothing is assembled by hand.
3. **Gate every row.**
   - Exact statement (`validate_proof`).
   - The official filter. Vendor it as an importable module, kept in step with `app.py` by a test.
   - A fresh cold compile on every listed toolchain, sequential, with memory, swap and disk checks.
   - Agreement with the run's recorded proxy, within noise.
   - Any failure blocks the file.
4. **Emit.**
   - `submission.jsonl`, plus a harness-only variant when hybrids are present.
   - `MANIFEST.md` and `manifest.json` with each row's source run, candidate, proxy per axis, tokens,
     heartbeats, per-version results, settled spend per row (all runs that contributed, ISSUES #2) and code
     revision (ISSUES #19).
   - The provenance ledger for the report.
5. **Diff.** Compare with the previous submission: rows changed, score delta, and rows that got worse. A row
   never regresses silently.

**Tests.**
- A fixture row with a modified statement, one with `sorry`, and one that fails on one toolchain. Each must block
  the file.
- A test that the vendored filter matches `app.py`.
