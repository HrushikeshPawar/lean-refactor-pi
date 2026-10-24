# Lean golf strategy bank

77 generic proof-golfing cards (`cards.yaml`), in the style of the Lean Refactor paper's strategy bank: each card says when a move applies, how to do it, a before/after example, the effect direction by proof position, and version risks.

## Rule: no benchmark specifics
The bank contains nothing taken from the 15 benchmark theorems: no theorem names, no project identifiers or lemmas, no proof fragments. Our run data was used only to learn which generic moves pay off (aggregate counts and signs per move class and proof position). Every example was written fresh on generic statements (Nat, Int, List, Finset, Prop). `leak_check.py` enforces this: it fails if any non-generic benchmark identifier or any 25+ character (whitespace-normalised) substring of a benchmark source, submission or run proof appears in `cards.yaml`. Run it after every edit to the cards; it must exit 0.

## Files
- `mine_moves.py`: walks `runs/pi-budget/*`, takes (parent, child) pairs where the child is verified and has fewer tokens or heartbeats, splits both with `arena.steps.split_steps`, diffs at step level, classifies each diff by syntax features only, and records the diff's position in the parent proof: `opening` (first step or first 20%), `closing` (last step or last 20%), `middle` (rest). Writes `move-stats.json` (aggregates only, no diff text).
- `move-stats.json`: per move class, overall and per position: n, how many diffs cut/raised step tokens, and (for pairs with a single changed step block, the only case where a proof-level heartbeat change can be attributed to one edit) how many cut/raised heartbeats. Counts live only here.
- `replaces.py`: for each card, regexes for the code its move rewrites (`replaces` on the card); retrieval ranks by these first. Cards without an entry get a derivation from tactic heads that `before` uses more than `after`.
- `build_cards.py`: holds the hand-written cards, derives `effect` from `move-stats.json` and `verified` from `verify.json`; emits `cards.yaml` and `cards.json` (same content, for tools without a YAML parser).
- `verify_cards.py`: compiles every `before` and `after` (see below); writes `verify.json`.
- `leak_check.py`: the gate above (`--allowlist` prints the generic vocabulary it ignores).

Order after any edit: `build_cards.py`, `verify_cards.py`, `build_cards.py` (to embed `verified`), `leak_check.py`.

## Effect format
```
effect: {tokens: down|up|mixed|unknown,
         heartbeats: {opening: .., middle: .., closing: ..},
         confidence: high|medium|low, note: <one generic sentence>}
```
A direction is `down`/`up` when at least 70% of mined diffs share that sign, `mixed` otherwise, `unknown` when fewer than 3 diffs fall in the bucket (or the card has no mined move class). `confidence` comes from the move class's total mined count (>=50 high, >=10 medium, else low). The position matters: the same move can cut heartbeats at the end of a proof and raise them at the start (for example a closing `grind` versus an opening one), so read the heartbeat direction for the position of the edit. Cards carry no numbers; text in `how`/`when` quotes none.

## Verification
Every `before` and `after` is a self-contained `example`, compiled with `import Mathlib` in the PutnamBench workspaces (`workspaces/putnambench-v4.25.0`, `-v4.26.0`, `-v4.27.0`; v4.27.0 is the primary) via `lake env lean <tempfile>` run from the workspace. `verify_cards.py` puts all examples of one toolchain into one file (examples are independent) and maps Lean errors back to cards by line, so one run per toolchain takes about 10 s. `verified: {v4.25.0: pass|fail, ...}` is stored on each card. Only an error fails a card; warnings (unused variables, linters) pass. Both halves of a card prove the same statement.

## Caveats
Pairs were selected because the child improved tokens or heartbeats, so signs are biased toward `down`; compare moves and positions with each other rather than reading `down` as a guarantee. Heartbeat signs are noisy and cover whole proofs. `other_shrink` and `unclassified` are catch-alls and have no card. Version notes beyond 4.27 are from documentation, not compiled here.

## Retrieval by a harness
`arena/patterns.py` ranks first by `replaces` matches in the step text (see its docstring), then by the tag scheme below. Each card has `tags` (tactic or syntax features). To retrieve: take the step being edited (or the profiler's hottest step), extract its tactic heads and features (`simp`, `have`, `rw`, `calc`, `intro`, `by_contra`, `induction`, bullets, `(x : T)`, `fun x =>`, ...), score cards by tag overlap with the step text, break ties by `effect` (token direction, heartbeat direction at the edit's position, `confidence`), and show the top 3-5. For a heartbeat-driven edit prefer cards whose heartbeat direction at that position is `down`; for a token-driven edit, cards with token direction `down`. Always show `version_notes` with the card and re-run the cross-version gate on the result.

Note: do not import `mine_moves.py` from other scripts; it re-mines `runs/` and overwrites `move-stats.json` at import.
