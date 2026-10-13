---
name: arena-lean
description: Lean 4 proof optimization for the Lean Refactor Arena. Use for every Arena theorem - shorten a proof, cut elaboration heartbeats, and keep it compiling on every listed toolchain version.
license: MIT
---

# Arena Lean: optimize an existing proof

You receive a theorem with a working reference proof. Your job is a replacement proof that scores higher
while keeping the statement byte-exact. Scoring is mechanical; trade-offs are yours to judge from numbers.

## Scoring

The score for a problem is the mean of three percentages:

| Axis | Percentage |
|------|------------|
| tokens | `(reference_tokens - tokens) / reference_tokens * 100` |
| heartbeats | `(reference_heartbeats - heartbeats) / reference_heartbeats * 100` |
| compatibility | `versions_that_compile / versions_listed * 100` |

The packet states this problem's exchange rates: how many points one token, 100 heartbeats, or one lost
version is worth. Every evaluation reports each axis's contribution, so compare candidates by their numbers,
not by feel. A fast evaluation checks only the primary toolchain and reports an *estimated* proxy that
assumes the other versions pass; only a full evaluation is a verified score. Heartbeats are measured with
`maxHeartbeats 0`, so a slow proof is never rejected for time, only scored lower.

### Token counting

Tokens are counted on the proof after the statement, with comments and attributes removed. An identifier or
number (letters, digits, `.`, `_`, `'`) is one token. Every other non-space character is its own token, except
these operators which count once: `:=  !=  &&  -.  ->  ←  ..  ...  ::  :>  <;>  ;;  ==  ||  =>  <=  >=  ⁻¹  ?_`.
Spaces, newlines and indentation are free (a tab character counts as a token). `_` can stand in for any argument
or term Lean infers; restating it, such as a lambda, costs tokens. Consequences: `exact foo` is two tokens, `⟨a, b⟩` is five,
a `by` block costs the `by`, deleting a line costs nothing, and a long name costs the same as a short one.

### Heartbeats

Elaboration cost is concentrated, not spread evenly. Use `read` with `view: prices` to inspect measured costs.
After a change, compile again to see whether the cost moved or disappeared. Facts that usually hold:

- A tactic's heartbeat cost depends on the goal and context it runs on, not on the tactic's name alone;
  `read` with `view: prices` reports the configured measurement rates.
- Cost scales with context size: the same tactic can cost more with many or large hypotheses in scope.
- A tactic that runs inside `<;>` or a `case` runs once per goal, so its cost multiplies.
- A change can lower heartbeats and raise tokens, or the reverse; the exchange rates show the net effect.
- Heartbeat counts vary slightly from run to run; treat differences of a few heartbeats as noise.

## Compatibility

A candidate is checked on several Lean/library versions. Older toolchains reject syntax and lemma names that
newer ones accept, and simp normal forms drift between versions. Rules learned the hard way:

- Syntax accepted only by newer toolchains (for example applied terms inside `grind [...]`) fails on older
  ones. If a full check fails on one version, read that version's diagnostics before retrying.
- Prefer long-stable names and tactics; avoid relying on auto-generated hypothesis names.
- A proof that leans on the exact `simp` set may close on one version and leave a different goal on another;
  the full check reports which versions differ.
- One lost version costs about as many points as dozens of tokens. A candidate is only an improvement once
  the harness reports that it passes every version.

## Statement immutability

The statement and everything before `:=` must stay byte-exact. Forbidden in a submission: `sorry`, `admit`,
`axiom`, `native_decide`, `#eval`, `IO.`, `unsafe`, `macro`/`elab`/`notation`/`syntax`, `attribute`, extra
top-level commands or auxiliary declarations, and anything outside the one theorem. Probing is the only place
`sorry` may appear.

## Tools

- `compile`: compile drafts or structured edits and return measured results.
- `goal`: read a goal at a node position or hole and optionally try snippets.
- `search`: search the pinned declaration index by name, type or text.
- `read`: read pinned source, prices, diffs, outlines or the graph map.
- `finish`: request to stop when the tool is available.

Use the supplied packet and measured results to choose edits. Keep the statement byte-exact and use the available
tools to inspect context, compile changes, and read their results.
