# Exploration credit: offline replay on the finished v6pilot Core.InitsUpdatesComm runs

Read-only on `runs/pi-budget/v6pilot-Core.InitsUpdatesComm-{deepseek-v4.1-flash,qwen3.8-flash,gpt-6-luna}-r1`
(the only v6pilot-*-r1 runs with summary.json). One Lean process at a time extracted the kernel features of every
probe and candidate proof (`.scratch/replay_extract.py`); `.scratch/replay_analyze.py` re-filed every attempt in ledger
order with the new `routes.file_attempt` and recomputed the route table (`routes.route_table`). No spend, no provider calls.
The context cache for the lemma vocabulary was empty in the worktree, so text features (used only for unreadable
drafts) had no vocabulary; kernel fingerprints are unaffected.

## What Lean does with failed drafts (the errored-attempt question)

Lean adds the declaration even when a tactic fails or errors: the failing tactic block is replaced by a synthetic
`sorryAx _ true`, so the kernel term exists and `route.lean` can read it (verified in `tests/test_route_features.py`,
slow). Explicit `sorry` is `sorryAx _ false`. The extractor now reports `read` (term exists), `errored`, `holes`
(explicit sorries) and `synthetic` (error-recovery sorries), counted as occurrences in the term. Only a parse
error (the command never parses, so there is no declaration) gives no term; those drafts fall back to text and
are assigned by best text match (`assigned_by: "text"`), never opening a route.

## Findings

* Probes: of 38 / 25 / 27 probes (DeepSeek / Qwen / Luna), the kernel term was read for 34 / 25 / 23. 2 / 3 / 4 had
  explicit sorry holes; 33 / 22 / 19 were errored-but-fingerprinted; 4 / 0 / 4 were unreadable (parse errors).
  An errored draft whose term has no recursion, lemma, claim or logic content (e.g. only `intro` then a failing
  tactic) carries no strategy and is also assigned by text (about 10 per run).
* Probes were the main place where goal-state depth shows up. All 34-37 compiled candidates per run on the large
  route have the single signature `closed`, so cosmetic compiled variants add nothing; the depth comes from
  probes that leave different goals.
* Routes credited (kernel-opened, not the original): DeepSeek 2 (r2, r3), Qwen 3 (r2, r3, r4), Luna 4 (r2..r5;
  r3 was opened by a skeleton, a probe with a hole). The old ledgers had 3 / 2 / 4 routes.
* The model-attempt share that produced a goal state new to its route: DeepSeek 36% (27/74), Qwen 41% (24/58), Luna 67% (30/45).
  DeepSeek r2: 55 attempts, 15 goal states, 40 stale attempts; the 34 compiled candidates there contribute one state (`closed`).
* DeepSeek's single attempts after refusals (the question that motivated this):
  * after refusal 3 (the old "r1" attempt): candidate ceed6bfe, a compiled variant of the original (similarity 1.0 to r1).
    Its signature is `closed`, which the original already seeds on r1, so it is NOT a new goal state and does not count as progress.
  * after refusal 4 (the old "r3" attempt): candidate b031e9c1 is kernel-read and opens a credited route; it COUNTS as progress.
    Caveat: its similarity to r2 is 0.498 against the 0.5 threshold, so this is borderline and moves with the IDF
    population (drafts with holes or errors are excluded from IDF to keep it close to the candidates-only behavior).
    In the same window, probe 447e900a left a goal state new to r2 (also progress).
  * after refusal 1 (8 attempts) the window had 3 new goal states (two skeleton probes on r1 with holes), so that repeat refusal would not
    have been called out; after refusal 2 there were no attempts at all.
* Luna: every refusal window except the last two (no attempts) counted as progress; Qwen: all windows counted.

Caveats: signatures hash the goals Lean prints for the first compat version (the `goals` list is capped at 12
traces and 1500 characters each); `sorry` in term position (`have h : T := sorry`) prints no goal, so such skeletons share
the empty-goal signature unless an error also appears. Bound-variable names inside a goal's target are not renamed (only
hypothesis names are), so renaming an `∃` binder in the statement the model restates would count as a new state.

## v6pilot-Core.InitsUpdatesComm-deepseek-v4.1-flash-r1

theorem Core.InitsUpdatesComm; extractor read 71/75 proofs (37 complete)

- probes 38: elaborated (kernel term read) 34; with explicit sorry holes 2; errored but fingerprinted 33; not readable (text, parse errors etc.) 4
- candidates 37: kernel-read 37, of which complete 37, errored 0; text 0
- old route events: r1 1 attempts; r2 34 attempts; r3 1 attempts

| route | label | credited | skeleton-opened | attempts | goal states (depth) | min holes | stale now | stale attempts | explored | best proxy |
|---|---|---|---|---|---|---|---|---|---|---|
| r1 (original) | recursion: Core.UpdateStates.rec; Core.InitStatesLength, Core.InitStat | False | False | 18 | 11 | 0 | 1 | 7 | True | 33.49 |
| r2 | recursion: none instead of Core.UpdateStates.rec; +Core.UpdateStatesUp | True | False | 55 | 15 | 0 | 0 | 40 | True | 86.07 |
| r3 | recursion: none instead of Core.UpdateStates.rec; +Imperative.isDefine | True | False | 1 | 1 | 0 | 0 | 0 | True | 80.25 |

- run level: {'credited_routes': 2, 'explored_routes': 3, 'new_state_attempts': 27, 'new_state_share': 0.365}; stale attempts 47/74

- assignments (route, by): r1/kernel=19, r2/kernel=41, r2/text=14, r3/kernel=1

Attempts in each window before a refusal (new_state = left a goal state new to its route; credited = opened a credited route):

- before refusal 1: 63 attempts, new goal state 22, credited 1 -> counts as progress: True
- after refusal 1, before refusal 2: 8 attempts, new goal state 3, credited 0 -> counts as progress: True
    - probe 5233a7f7 r1 sig=84dca957 new_state=True credited=False holes=1+0 by=kernel sim=1.0
    - probe 91e900fe r1 sig=a6830960 new_state=True credited=False holes=1+0 by=kernel sim=1.0
    - candidate/model 5db454fb r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.693
    - candidate/model 8241487c r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.693
    - candidate/model a2b13495 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.693
    - probe 5da2207a r2 sig=67264829 new_state=True credited=False holes=0+1 by=text sim=0.933
    - candidate/model 8b3afdbe r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.693
    - candidate/model 9c259c7b r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.694
- after refusal 2, before refusal 3: 0 attempts, new goal state 0, credited 0 -> counts as progress: False
- after refusal 3, before refusal 4: 1 attempts, new goal state 0, credited 0 -> counts as progress: False
    - candidate/model ceed6bfe r1 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=1.0
- after refusal 4 (to the end): 2 attempts, new goal state 2, credited 1 -> counts as progress: True
    - probe 447e900a r2 sig=b35500f3 new_state=True credited=False holes=0+1 by=kernel sim=1.0
    - candidate/model b031e9c1 r3 sig=closed new_state=True credited=True holes=0+0 by=kernel sim=0.498

## v6pilot-Core.InitsUpdatesComm-qwen3.8-flash-r1

theorem Core.InitsUpdatesComm; extractor read 59/59 proofs (34 complete)

- probes 25: elaborated (kernel term read) 25; with explicit sorry holes 3; errored but fingerprinted 22; not readable (text, parse errors etc.) 0
- candidates 34: kernel-read 34, of which complete 34, errored 0; text 0
- old route events: r1 0 attempts; r2 33 attempts

| route | label | credited | skeleton-opened | attempts | goal states (depth) | min holes | stale now | stale attempts | explored | best proxy |
|---|---|---|---|---|---|---|---|---|---|---|
| r1 (original) | recursion: Core.UpdateStates.rec; Core.InitStatesLength, Core.InitStat | False | False | 6 | 6 | 1 | 0 | 0 | True | None |
| r2 | recursion: none instead of Core.UpdateStates.rec; +Core.UpdateStatesUp | True | False | 50 | 16 | 0 | 1 | 34 | True | 86.02 |
| r3 | recursion: Core.InitStates.rec instead of Core.UpdateStates.rec; +Func | True | False | 1 | 1 | 2 | 0 | 0 | False | None |
| r4 | recursion: Core.InitStates.rec instead of Core.UpdateStates.rec; +Core | True | False | 1 | 1 | 1 | 0 | 0 | False | None |

- run level: {'credited_routes': 3, 'explored_routes': 2, 'new_state_attempts': 24, 'new_state_share': 0.414}; stale attempts 34/58

- assignments (route, by): r1/kernel=7, r2/kernel=46, r2/text=4, r3/kernel=1, r4/kernel=1

Attempts in each window before a refusal (new_state = left a goal state new to its route; credited = opened a credited route):

- before refusal 1: 19 attempts, new goal state 9, credited 1 -> counts as progress: True
- after refusal 1, before refusal 2: 28 attempts, new goal state 12, credited 0 -> counts as progress: True
    - candidate/model 88772773 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.792
    - probe 1c3b0496 r2 sig=0e285957 new_state=True credited=False holes=0+2 by=kernel sim=0.892
    - candidate/model 14780295 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.715
    - candidate/model 5abdfbac r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.713
    - probe 99529b6e r2 sig=18299efa new_state=True credited=False holes=0+1 by=kernel sim=0.806
    - candidate/model 5fc5cb7b r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.575
    - probe 3512d16c r2 sig=2ea90656 new_state=True credited=False holes=0+1 by=kernel sim=0.799
    - candidate/model 076327ed r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.72
    - candidate/model aaf85f83 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.722
    - candidate/model 46ca6445 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.723
- after refusal 2, before refusal 3: 9 attempts, new goal state 2, credited 2 -> counts as progress: True
    - probe 9f2c522a r3 sig=01492b8d new_state=True credited=True holes=0+2 by=kernel sim=0.125
    - probe 3468bddd r4 sig=6a86525d new_state=True credited=True holes=0+1 by=kernel sim=0.437
    - candidate/model 4c487376 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.669
    - candidate/model 207618ea r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.657
    - candidate/model cee60974 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.626
    - candidate/model 3f478c00 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.734
    - candidate/model 6495f576 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.733
    - candidate/model be17841d r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.688
    - candidate/model c2b22d37 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.733
- after refusal 3 (to the end): 2 attempts, new goal state 1, credited 0 -> counts as progress: True
    - probe 0e07fc6a r2 sig=20d93e5f new_state=True credited=False holes=0+1 by=text sim=1.0
    - candidate/model 5d04a07b r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.763

## v6pilot-Core.InitsUpdatesComm-gpt-6-luna-r1

theorem Core.InitsUpdatesComm; extractor read 42/46 proofs (19 complete)

- probes 27: elaborated (kernel term read) 23; with explicit sorry holes 4; errored but fingerprinted 19; not readable (text, parse errors etc.) 4
- candidates 19: kernel-read 19, of which complete 19, errored 0; text 0
- old route events: r1 1 attempts; r2 14 attempts; r3 1 attempts; r4 2 attempts

| route | label | credited | skeleton-opened | attempts | goal states (depth) | min holes | stale now | stale attempts | explored | best proxy |
|---|---|---|---|---|---|---|---|---|---|---|
| r1 (original) | recursion: Core.UpdateStates.rec; Core.InitStatesLength, Core.InitStat | False | False | 12 | 11 | 0 | 0 | 1 | True | 37.53 |
| r2 | recursion: none instead of Core.UpdateStates.rec; +Core.UpdateStatesUp | True | False | 18 | 4 | 0 | 1 | 14 | True | 85.11 |
| r3 | recursion: Core.InitStates.rec instead of Core.UpdateStates.rec; −Core | True | True | 6 | 6 | 0 | 0 | 0 | True | 58.18 |
| r4 | recursion: List.rec instead of Core.UpdateStates.rec; +List.map +List. | True | False | 2 | 2 | 0 | 0 | 0 | True | -0.78 |
| r5 | recursion: List.rec instead of Core.UpdateStates.rec; +Core.InitStates | True | False | 7 | 7 | 0 | 0 | 0 | True | 49.91 |

- run level: {'credited_routes': 4, 'explored_routes': 5, 'new_state_attempts': 30, 'new_state_share': 0.667}; stale attempts 15/45

- assignments (route, by): r1/kernel=10, r1/text=3, r2/kernel=16, r2/text=2, r3/kernel=6, r4/kernel=1, r4/text=1, r5/kernel=7

Attempts in each window before a refusal (new_state = left a goal state new to its route; credited = opened a credited route):

- before refusal 1: 19 attempts, new goal state 8, credited 2 -> counts as progress: True
- after refusal 1, before refusal 2: 6 attempts, new goal state 4, credited 0 -> counts as progress: True
    - probe 0e0b3790 r1 sig=59719a2f new_state=True credited=False holes=2+0 by=kernel sim=1.0
    - candidate/model d2d2afe6 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.736
    - probe 29f04ac2 r1 sig=2da3135a new_state=True credited=False holes=1+0 by=kernel sim=1.0
    - candidate/model f0fcd31b r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.737
    - probe d9de7e40 r2 sig=45f39997 new_state=True credited=False holes=0+1 by=text sim=0.812
    - probe 6c28d950 r2 sig=97343c72 new_state=True credited=False holes=0+1 by=text sim=0.75
- after refusal 2, before refusal 3: 2 attempts, new goal state 1, credited 0 -> counts as progress: True
    - probe 359e054a r1 sig=a845f88e new_state=True credited=False holes=0+3 by=kernel sim=0.913
    - candidate/model 698b384a r1 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=1.0
- after refusal 3, before refusal 4: 4 attempts, new goal state 4, credited 1 -> counts as progress: True
    - probe 0c634e9b r1 sig=5ff429ca new_state=True credited=False holes=None+None by=text sim=0.435
    - probe febdf0ff r1 sig=695321aa new_state=True credited=False holes=None+None by=text sim=0.385
    - probe 64eaa4f7 r1 sig=a6830960 new_state=True credited=False holes=None+None by=text sim=0.385
    - candidate/model a2d300ea r4 sig=closed new_state=True credited=True holes=0+0 by=kernel sim=0.233
- after refusal 4, before refusal 5: 6 attempts, new goal state 6, credited 0 -> counts as progress: True
    - probe b407eb34 r3 sig=edd41d22 new_state=True credited=False holes=1+0 by=kernel sim=1.0
    - probe 66af4739 r3 sig=34814abb new_state=True credited=False holes=0+1 by=kernel sim=1.0
    - probe 545a35e9 r4 sig=270951e0 new_state=True credited=False holes=None+None by=text sim=0.304
    - probe dc8a614e r3 sig=e8b34367 new_state=True credited=False holes=0+1 by=kernel sim=1.0
    - probe 796c0fc5 r3 sig=7dd1982c new_state=True credited=False holes=0+1 by=kernel sim=1.0
    - candidate/model e38bc557 r3 sig=closed new_state=True credited=False holes=0+0 by=kernel sim=1.0
- after refusal 5, before refusal 6: 8 attempts, new goal state 7, credited 1 -> counts as progress: True
    - probe f7898d48 r5 sig=adcc3cf2 new_state=True credited=True holes=0+1 by=kernel sim=0.437
    - probe d0509b0c r5 sig=505fa692 new_state=True credited=False holes=0+1 by=kernel sim=1.0
    - probe b188c2e9 r5 sig=7605445b new_state=True credited=False holes=0+1 by=kernel sim=1.0
    - probe ab01ca0f r5 sig=cc55e849 new_state=True credited=False holes=0+1 by=kernel sim=1.0
    - probe 163e60fe r5 sig=802243cb new_state=True credited=False holes=0+3 by=kernel sim=1.0
    - probe ed5860b9 r5 sig=2aa4e5c0 new_state=True credited=False holes=0+1 by=kernel sim=1.0
    - candidate/model 084599cd r5 sig=closed new_state=True credited=False holes=0+0 by=kernel sim=1.0
    - candidate/model fed72d11 r2 sig=closed new_state=False credited=False holes=0+0 by=kernel sim=0.738
- after refusal 6, before refusal 7: 0 attempts, new goal state 0, credited 0 -> counts as progress: False
- after refusal 7 (to the end): 0 attempts, new goal state 0, credited 0 -> counts as progress: False

