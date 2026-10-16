# Routes in v6: mechanics, flaws, timing, v7 signatures

Replay: `route_replay.py` (read-only; no Lean, no models), raw output `route_replay.out.json` (21 runs: v6cov, v6ark, v6ark2, v6pilot).

## 1. v6 mechanics
- Fingerprint (`arena/routes.py`): kernel record from `arena/lean/route.lean` via `route_features.extract` (cold Lean process on the file prefix, background lane). Parts: lemma families minus PLUMBING (0.45, IDF-weighted ln(1+N/df)), recursors (0.25), hashed `have`/`calc` claim statements (0.20), logic markers (0.10). An empty part is a normal value.
- Text fallback (`source: "text"`): recursion flag, vocabulary lemmas named, top-level tactic heads. It never opens a credited route. A kernel attempt joins a text exemplar only at >= 0.7.
- Clustering: arrival order, against each route's FIRST attempt (exemplar). Join best exemplar if sim >= `SAME_ROUTE = 0.5`, else open `rN`. Incomplete (sorry) attempts are compared by containment.
- Credit: a route is credited only if a kernel fingerprint opened it.
- Depth: distinct goal-state signatures (`goalstate.signature`) per route, `ROUTE_DEPTH = 3`.

## Observed flaws
- Hard threshold (ISSUES #25c): v6ark2 interleaved, #3/#4 one line apart (text sim 0.994) scored 0.514 vs 0.495 against exemplar #1, so r2 absorbed 75 of 77 attempts.
- Over-splitting (BACKLOG §4b): a4 had 311 route openings, "165 credited routes, 4 explored", from `sorry` skeletons differing in one or two `have` statements. Replay on v6cov putnam_1964_a4: 316 credited routes over 412 nodes, and only 1.7% of node pairs <= 3 lines apart share a route.
- Vocabulary, not structure (BACKLOG §2): lemma swaps open "new" routes; one strong lemma replacing a manual argument is merged.
- Text-only runs (ISSUES #5): both v6ark Binius runs had 0 credited routes (45 and 69 events, all text).
- Late filing (ISSUES #5, #5/v6ark2 note): see section 2.
- Exemplar is a fixed first attempt, so drift is invisible and the order of arrival decides the split.
- Refusal text grows with the route count (about 10K characters at 165 routes, BACKLOG §4c).

## 2. Timing root cause
Path: `_record_route_later` (`campaign.py:898`, called at 1168 for the reference and 1556 per compiled candidate) writes `route-queue.jsonl` and spawns ONE detached worker (911). `_route_worker` (947) takes entries serially; each runs `_yield_to_lean_session` (964, sleeps while the run's own Lean session reports memory pressure), then `_room_for_extraction(wait=float("inf"))` (965; loop at 1002-1014, sleeps 5 s until free RAM >= reserve + worker + 2 GB). Then `_record_route` (1017) takes the per-run lock, a shared slot lock (`ROUTE_SLOTS = 2` across parallel runs, 1032-1045), re-checks memory, and runs a cold Lean extraction (`route_features.extract` -> `run_lean`, 120 s timeout). Only after that is the event appended to the ledger, which is all `route_table`, the finish refusals and the summary read.

Most likely cause: the two infinite waits (965, 1014) on a machine where the Lean session daemons are themselves memory-bound. They are unlogged and, with one serial worker, every later attempt queues behind the stalled one (the v6ark2 12-minute stall, "r3 - 1 attempt" while 11 and then 15 were assigned). Compounding factors: each extraction costs a full Mathlib/ArkLib import (128-192 s on the old FUSE mount), and the queue is a serial cold process per proof. On Binius the extractor itself failed and the error is swallowed (`campaign.py:893`).

v7 fix: the signature computed in Python from the proof text at compile time (about 1 ms in the replay, 21 runs in 6 s) needs no worker, no queue, no memory wait. Lean enrichment stays optional and asynchronous, and can never change an already assigned route.

## 3. Replay (hysteresis: join if sim >= 0.60; open new only < 0.35; in the grey band stay with the parent's route unless the best beats the runner-up by 0.10; single link to any member)
Stability = share of node pairs <= 3 changed lines that share a route. Separation = share of pairs of best-closed nodes of different v6 routes that land in different routes. Means over runs; counts for runs with the data.

| method | routes median / max | stability mean / min | separation mean (12 runs) |
|---|---|---|---|
| v6 (ledger, events only) | 2 / 316 | 0.92 / 0.017 | 1.0 (by definition) |
| (a) step skeleton | 1 / 3 | 0.996 / 0.954 | 0.24 |
| (c) step-hash Jaccard | 5 / 17 | 0.974 / 0.80 | 0.22 |
| (a)+(c) mix 50/50 | 3 / 4 | 0.991 / 0.85 | 0.21 |
| (b') final goals from stored compile | 16 / 347 | 0.48 / 0.011 | 0.0 |

(b) is not possible as specified: per-step goal states are not stored. The ledger and `diagnostics/` keep only final goals and errors. (b') is that final-state set, and it fragments badly: every sorry draft shows a new goal, and all closed proofs share one signature. Use it only for depth. The v6 stability figure covers only the nodes with route events, so it is not the same pair set.

Reading: (a) is stable but too coarse (the 12 runs collapse to 1-3 routes). (c) is stable but fragments on rename-heavy proofs (CSLib 17, SKI 12 routes). The mix is stable with 3-4 routes. Weak point: the best nodes of different v6 routes mostly stay together (0.21), and v6 routes often differ only by lemma choice, which the neutral rule forbids us to distinguish by name. The 0.21 therefore measures agreement with a vocabulary criterion, not correctness. Separation was good only on Core/Luna (0.83). This has not been checked against a human verdict.

## 4. Recommendation
Define "same route" as same proof shape under small edits: a node belongs to a route if its step skeleton and normalized step set are close (mix >= 0.60) to ANY member of that route (single link), with the grey band 0.35-0.60 resolved by the parent's route, then margin. Rules:
- Synchronous: computed in Python at compile time from the proof text. No Lean, no queue, no memory wait. Assignment is frozen at filing (no retroactive moves), so the route shown to the harness is the final one.
- Content-neutral: heads and hashed lines only. No lemma names, and nothing is shown to the model. Routes stay internal.
- Archive cell key: (route id, graph depth bucket, closed or not). A cell keeps its best node (score, then heartbeats), and next-node selection picks the least-visited cell first, then the best node in it. Sorry drafts fill cells but are not credited. A parent edit within <= 3 lines never opens a cell.
- Stay robust in two ways: cap routes per run (merge the closest pair beyond about 12) and log every assignment with its similarity and runner-up.
- Optional later: kernel or subgoal enrichment (BACKLOG §2) as a secondary label only, filed after the fact, never changing the cell.
- Before relying on it, validate separation with a hand-labelled sample of 20 node pairs from b2 and Core/Luna.
