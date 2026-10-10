# 16: Full text rewrite, compaction memory, packet

**What to build:** Every word the model reads is rewritten once, against the final five tools, and lives only in `agent-text/`: the skill, the tool and parameter descriptions, the reply lines, the messages (footer, continuation, errors, focus notice, map rows) and the packet. The packet gives the statement, the original proof with its per-step price table and the exchange rates, the ranked library top 60 (no token-cost column), and the goal before each top-level step. It sheds local-variable lines before library lines when it is over the size limit. The compaction memory, rebuilt from the v7 graph, is one text that also serves as the fresh-context seed. Tests check that every template parses and is fully supplied, that each rule is stated in one place with identical numbers, that no model-facing literal is left in code, that no template names a kind of proof, and that the word-budget table (counted in words) stays within its budget.

**Blocked by:** 15c: Old tools out: protocol actions, ideas, v6-shape tests (all lower tickets, 04 to 15b, are also committed below your branch).

**Status:** ready-for-agent

**Branch:** `v7/16-text` (stacked on `v7/15c-old-tools-out`)

**Read first:** spec "Agent text", "Packet", "Compaction memory and fresh seed" (Implementation Decisions), user stories 36-45 and 108, "Testing Decisions" (pure units); plan §1d, §2 (2a to 2d), §3 (all), §4e, §5d, §5e (phase notice), §12a (#8, #26, #35), §12b (#16, #34), §12c; decisions D3, D4, D5, D6, D15, D16, D17, D18, D34. Read the organizers' prompts **for ideas only; copy nothing** (not a sentence, not a list): `vendor/lean-refactor/lean_refactor/agents/*.py`, `vendor/lean-refactor/lean_refactor/cc_agent/prompts/*.md`, `vendor/lean-refactor/lean_refactor/cc_agent/scripts/run_golf.py`.

## Context: where things are now
- `agent-text/` (tickets 05a and 05b; layout in plan §2a): `numbers.yaml`, `skill/SKILL.md`, `packet/` (`task.md`, `scoring.md`, `price-table.md`, `sections.yaml`, `library.md`, `profile.md`), `tools/<tool>.yaml`, `replies/*.md`, `messages/*`, `README.md` with a generated word-budget table. Ticket 05a added the format, the Python and TS renderers (strict: a missing key is an error), `numbers.yaml` and the CLI commands `arena text render` and `arena text budget`; ticket 05b moved the campaign, engine and TS messages in verbatim and added the literal lint. Ticket 15a added minimal templates for the five tools' replies, ticket 15b the tool descriptions, `request_failed` / `turn_ended_with_text` continuation keys and `arguments_missing` / `empty_arguments` errors, and ticket 15c deleted the old ones. Find the real layout with `ls -R agent-text` and the loader with `grep -rn "numbers.yaml" arena packages`.
- `arena/context.py`: `render_packet(name)` builds the packet from `lean_context(name)` records and the reference profile; `SCORING_FACTS`/`_rates` (now templates), `_goal_section` ("Goal before each top-level tactic of the reference proof"), `_library_section` (top 60 by IDF-weighted overlap, `LIMITS["library"]`), `_earlier_section` (`score_earlier`), `_used_section`, `_dependency_section`, `_local_section` (`LOCAL_TITLE`, `LOCAL_FLOOR`), `_types_section`, `_scope_section`, `_profile_section` (heartbeat profile and top-ten hotspots), `_fit(parts, limit)` (the shed order; `MAX_PACKET_CHARS = 40_000`; stages `EARLIER_TITLE`, goals above `GOALS_FLOOR`, `LIBRARY_TITLE`, `LOCAL_TITLE` above `LOCAL_FLOOR`, remaining goals), `packet_manifest` / `certify_manifest` / `REQUIRED_SECTIONS`.
- Ticket 13's price engine (modules under `arena/`): per-step price table for the original and for any node, exchange rates, the `price-table.md` data (there is no library token-cost column: decision 2). Ticket 11: the map and focus notice. Ticket 10a: node ids (`nN`), step ids (`sK`), holes (`nN.hK`); ticket 10b: per-step goals before and after. Ticket 15a: `read` events appended to the event log (`{"kind": "read", "handle", "first", "last"}`).
- `arena/memory.py`: `memory_text(front, spent_usd, cap_usd)` and `memory(run_id, ...)` (the `arena protocol memory` action): best candidate, routes, failures, allowance (ideas were removed by ticket 15c). It is injected once after a Pi compaction by the extension (`session_compact` path in `arena.ts`).
- `arena/skill.py`: `SKILL_DIR`, `skill_hash`, `skill_prompt()` (SKILL.md without front matter; the body goes into the system prompt). The current skill is about 7.5K characters and still contains tactic-specific advice.
- Tests today: `tests/test_context.py` (packet tests), `tests/test_memory.py`, `tests/test_agent_text.py` (tickets 05a and 05b: renderer, verbatim-packet and literal-lint tests; read it first).
- `docs/PLAN-harness-v7.md` §1d lists the defects to remove: the 10% rule stated 4 times, token rules in two places (about 250 wasted tokens per run), a theorem-specific number in the generic skill ("original scores only 33"), a hard-coded token example, "90% down on heartbeats", strategy words in the references.

## What to build
- [ ] 1. **Baseline and inventory.** Before editing, run `uv run arena text budget` (counts words) and save the table; run `uv run arena text render --theorem <row>` (ticket 05a) for `Core.InitsUpdatesComm`, `putnam_1964_b2` and `Cslib.SKI.parallelReduction_diamond` and record the character and word counts per part (system prompt, skill, tool descriptions, packet sections). Read the organizers' prompts named under "Read first" and write at most 8 bullets of observations (structure, what they state about scoring, what they leave out) into your hand-back. Nothing from them is copied into `agent-text/`.
- [ ] 2. **Rule table.** Create `agent-text/rules.yaml`: a list of every rule the model is told, each with an id, the one template key that states it, and the numbers it uses. It must contain at least: the score definition and per-axis rates; the token-counting rules; statement immutability; forbidden constructs; the budget and stop (`numbers.yaml` finish fraction, the spend limit); the operations (`splice`, `fill`, `merge`, `base`) and node, step and hole ids; what a status (`closed`, `sketch`, `broken`) means; what the price row columns mean. No rule appears twice. The consistency test of checkbox 17 reads this file.
- [ ] 3. **Rewrite the skill, `agent-text/skill/SKILL.md`** (the file `arena/skill.py` reads; delete any other copy so there is one). From zero, for the final tools. It states the task in a few lines and points to the tools; it states the rules that belong to the skill by `rules.yaml` and nothing else. No strategy, no tactic names, no syntax tutorial, no theorem-specific number, no "learned the hard way" lists, no advice about which route to try. Facts the harness cannot measure (forbidden constructs, statement immutability) go in `agent-text/skill/lean-facts.md` (plan §3f; included in the skill, under 700 words). Every number in it is rendered from `numbers.yaml` or computed.
- [ ] 4. **Rewrite every tool description and parameter description** in `agent-text/tools/compile.yaml`, `goal.yaml`, `search.yaml`, `read.yaml`, `finish.yaml`. One short paragraph per tool and one sentence per parameter. Each states what the tool does, its inputs and what it returns; nothing about when to use it as strategy. `compile` states the draft limit from `numbers.yaml`; `finish` states when it is offered. No sentence duplicates a skill or packet sentence (one rule, one place).
- [ ] 5. **Rewrite all reply and message templates** under `agent-text/replies/` (`compile.md`, `goal.md`, `search.md`, `read.md`, `finish.md`, `map.md`) and `agent-text/messages/` (`footer.md`, `errors.yaml`, `refusals.yaml` if anything remains, `continuation.md`, `phase.md`, `arena-line.md` and whatever else tickets 15a and 15b left). Rules: facts and numbers only, one line per fact; error text names the bad input and lists the valid forms (keep ticket 15a's codes unchanged); `continuation.md` has the two keys ticket 15b added, `request_failed` (the request failed, with the cause when known; plan §12a #26) and `turn_ended_with_text` (a turn that ended with text, stating only the spend, the stop condition and the points left per axis): rewrite their wording, keep the keys and the selection logic; a truncated turn gets a reply line saying where it was cut (`cut_at_tokens`, plan §12a #35; the extension already keeps the reasoning, ticket 06) and nothing else. No template names a kind of proof, a route or an idea.
- [ ] 6. **Packet rewrite: sections and templates.** Rewrite `render_packet` and `agent-text/packet/*` so the packet is, in this order: (1) `task.md`: the theorem name, the statement must stay byte-exact, the original proof is node `n1` (use the id ticket 10a assigns); (2) `scoring.md`: the score definition, the exchange rates computed by `exchange_rates()` and the token rules with examples whose counts are computed by `arena.engine._proof_length` at build time (no hard-coded count); (3) the pinned environment and scope as today (`_scope_section`, imports, toolchain pins) with template headings; (4) the original proof and its price table from ticket 13 (D17), rows keyed by step id, the totals row and the rates line; (5) the goals before each top-level step, **under the same step ids** as the price table; (6) the library, top 60 (`LIMITS["library"]`, D34), each line `rank. handle · module · signature` (no token-cost column: the official counter scores any identifier as one token, decision 2); (7) the sections that exist today and carry statement-level facts: definitions of project types in the statement, source-named declarations, elaborated proof dependencies, local variables, earlier declarations of this file (rename the `Relevant lemmas from this file` heading to a neutral one). Remove: `_profile_section` and the hotspot list (replaced by the price table, plan §3f), `agent-text/packet/profile.md`, and the "Kickoff inventory manifest" block from the model-facing text (keep `packet_manifest` and `certify_manifest` and where certification reads them; update `REQUIRED_SECTIONS` to the new titles). Open question (list in hand-back): plan §2a still lists `profile.md` and the spec's Packet bullet names only five parts; keeping the existing statement-level sections in (7) is what plan §3f and D34 ("4% from other packet sections") imply.
- [ ] 7. **Shed order (#16).** In `_fit` change the stages to: earlier declarations, then goals beyond `GOALS_FLOOR`, then **local-variable lines (down to none)**, then library lines (from the end of the ranking), then the remaining goals down to one. `MAX_PACKET_CHARS` and `LIMITS` keep their values. Remove `LOCAL_FLOOR` if nothing else uses it. A test (checkbox 18) fixes the order on a fixture that is over the limit.
- [ ] 8. **Numbers computed per theorem.** Every number in the packet and skill is either a `numbers.yaml` value (finish fraction, list caps, draft limit) or computed at packet build: rates from `exchange_rates()`, token examples from the counter, price table from ticket 13. Run `grep -rn "[0-9]\{2,\}" agent-text/skill agent-text/packet agent-text/tools` and make sure the only literal numbers left are placeholders or in `numbers.yaml`. Add keys to `numbers.yaml` when a cap needs a number (packet list caps and the memory caps of checkbox 12), with the values the code uses today where they exist.
- [ ] 9. **Compaction memory and fresh seed: `arena/memory.py` rewrite.** `memory_text(state) -> str` (a pure function of one state dict built by `memory(run_id)` from the v7 event log, the map, the packet library records and the run's `read` events) returns one text with, in this order: (a) the **full text of the best node** with its id and price row; (b) the map (ticket 11's renderer, `read view:"map"`); (c) the library lines the best proof uses: every library record (packet top 60 and every `search`/`read` handle the model read) whose name occurs in the best proof's text, with its signature, at most `numbers.yaml` key `memory_library_lines` (add with value 15); (d) the `read so far` list: the `read` events merged into handles with their line ranges (adjacent or overlapping ranges merged), most recent last, at most `memory_read_entries` (add with value 30); (e) open holes with their goals (`nN.hK: <goal>`). It states no allowance line (the footer does that on every reply) and no ideas, routes or advice. Two header templates in `agent-text/messages/compaction-memory.md`: `compaction_header` (context was compacted) and `seed_header` (a new context starts); `memory_text(state, seed=False)` selects. The fresh-context experiment (D22 b) is not wired: only the function and its test exist. Keep the protocol action `memory` and the extension's one-time injection after compaction; delete the code of the old lines.
- [ ] 10. **Compaction residual fixes that live in text or memory (plan §12b #34).** Only if ticket 06 or 15b did not: skip the summary request on an empty history, and log each compaction failure as a ledger event with an alarm line. If both are already done, say so in the hand-back and change nothing.
- [ ] 11. **Word-budget table.** Make `uv run arena text budget --write` (ticket 05a's command; add the flag if it lacks it) regenerate the table in `agent-text/README.md`: template, words (the same word count `arena text budget` uses, decision 10), where shown, how often per run. Add a `budget` section to `numbers.yaml` or a `budget.yaml` with the **proposed** limits (the owner may change them; list as an open question): static text sent every turn (system prompt, skill, five tool descriptions) at most 60% of the baseline total you measured in checkbox 1; packet text outside the dynamic sections (task, scoring, price-table headings, library and goal headings) at most 60% of its baseline; every reply template at most 40 words. The README table is committed; the test of checkbox 17 fails when a template exceeds its limit or the table is stale. Put the final table in your hand-back.
- [ ] 12. **Memory and packet caps in `numbers.yaml`.** `memory_library_lines`, `memory_read_entries` (checkbox 9) and any packet cap you moved. Code reads them through the same loader as `finish_fraction`.
- [ ] 13. **Delete the leftovers of the old text.** `SCORING_FACTS`, `_rates` if now unused, the hard-coded task prose in `render_packet`, `agent-text/packet/profile.md`, any template key no code supplies (the consistency test finds them), the old skill file location, and any second copy of a rule. `grep -rn "10%\|ten percent" agent-text` must find the finish fraction rule once (rendered from `numbers.yaml`).
- [ ] 14. **Literal lint.** Implement in `tests/test_agent_text.py` (extend the file of tickets 05a and 05b): scan the Python modules that build model-facing text (`arena/context.py`, `arena/memory.py`, `arena/reply.py`, `arena/tools.py`, `arena/campaign.py`, `arena/summary.py` only where it builds model text; list the modules in the test) with `ast`, and the TS files `arena.ts`, `rules.ts`, `trim.ts`, `reply.ts`, `spend.ts`, with a regex, for string literals of 30 or more characters containing a space. Allowed: docstrings, comments, strings passed to `raise`, `logging`, `print` to stderr, `appendTrace`/`appendCost` keys, and any line marked `# log` (Python) or `// log` (TS) with a short reason. Anything else fails with file and line. Fix the findings by moving the text to a template. (Decision: 30 characters with a space is the threshold; plan §2b rule 1 gives none; list under Open questions.)
- [ ] 15. **Neutrality test.** In `tests/test_agent_text.py`: render every template (skill, packet templates, tool descriptions, replies, messages, memory headers) with a neutral dummy for every placeholder (`X` for text, `1` for numbers), and assert no whole-word, case-insensitive match of the denylist in `tests/fixtures/neutrality_terms.txt` (one term per line, create it): `induction`, `inductive`, `recursion`, `recursive`, `lemma`, `strategy`, `route`, `idea`, `simp`, `rw`, `rewrite`, `grind`, `omega`, `linarith`, `nlinarith`, `ring`, `field_simp`, `norm_num`, `positivity`, `aesop`, `decide`, `cases`, `rcases`, `obtain`, `calc`, `golf`. If an existing legitimate use trips a term (for example `calc` in a path), fix the template; do not weaken the list. Add a test that the denylist file itself contains each of the first twelve terms (so it cannot be emptied).
- [ ] 16. **Placeholder and template tests.** In the same file: every template parses; every placeholder is supplied by each renderer that uses it and no supplied key is unused (ticket 05a's helper if it exists); a missing key raises; plurals and conditionals are never in templates (no `if`, no `{x|...}`).
- [ ] 17. **Consistency test.** Using `rules.yaml`: each rule's template key exists, is rendered by exactly one template, and no other rendered text (skill, packet, tools, replies) contains a copy of its key sentence; every `numbers.yaml` value that appears in rendered text appears with the same digits everywhere it appears (render for two different theorem fixtures and check the per-theorem numbers differ between them while the `numbers.yaml` ones do not).
- [ ] 18. **Packet and memory behaviour tests** (fast, fixture contexts from `tests/test_context.py`; no Lean): (a) the packet for a fixture row contains, in order, the task, scoring with rates equal to `exchange_rates()` output, the price table with a row per step, goals under the same step ids, and a library line `rank. handle · module · signature` with no tokens column; (b) a second fixture row with different denominators yields different rates and token examples in the packet; (c) on a fixture that exceeds `MAX_PACKET_CHARS`, local-variable lines are all gone before the first library line is removed, and the packet is within the limit (the fiberwise failure); (d) `memory_text` contains the full best proof text, the open holes with their goals, the map, only the library lines whose names occur in the best proof, and merges `read` ranges (two events `decl:X:10-20` and `decl:X:15-30` become one entry `10-30`); it contains no allowance, idea or route text; `seed=True` changes only the header; (e) the word-budget test (words, not Lean tokens): the README table equals `arena text budget` output and no limit of checkbox 11 is exceeded.
- [ ] 19. **Update older tests** that quote old text (`tests/test_context.py` strings, `tests/test_memory.py`, `tests/test_runner.py` assertions on skill or packet text) to assert behaviour (the section exists, the number equals the computed one) instead of copied sentences. Delete any test that only restates a literal.
- [ ] 20. **Confirm the two known slow failures are gone.** Tickets 15b and 15c rewrote or deleted both (`ErrorLoopAndContinuationTests::test_continuation_names_the_best_candidate_and_the_models_active_ideas` and `AutomaticChecksTests::test_background_result_arrives_on_the_next_tool_result_without_rewriting_history`). Check with `grep -n "active_ideas\|without_rewriting_history" tests/test_runner.py` that only rewritten versions exist; they run in the slow file of the Verify section. If either old test still exists and fails, fix it or delete it with the reason in the hand-back.
- [ ] 21. **Smoke render.** Run `uv run arena text render --theorem <row>` for the three rows of checkbox 1 and for one row from each of the other four sources (a total of at most 7 rows, all with a cached context; if a row has no cached context, skip it and say so, do not start Lean). Put the before and after counts per part (characters and words) in the hand-back and confirm `uv run arena check` (the real gates, no model call) passes for the rows whose contexts are cached.

## Do NOT
- Do not copy any sentence, list or structure from the organizers' prompts or from the old skill and references. Rewrite from the facts.
- Do not suggest a kind of proof, tactic, lemma family or strategy anywhere, including examples. Examples of code in the token rules use generic text (`exact foo`, `⟨a, b⟩`) with computed counts.
- Do not state any rule twice. If two templates need the same fact, one states it and the other does not mention it.
- Do not change tool schemas, protocol actions, reply codes or the graph, price or map data from tickets 10a to 15c. If a template needs a field that does not exist, stop and report.
- Do not put model-facing literals in code to save time; the lint of checkbox 14 will fail.
- Do not change `MAX_PACKET_CHARS`, `LIMITS` or the library ranking (D33, D34); the library stays top 60, ranked as today, with no token-cost column (decision 2).
- Do not touch `arena replay`, the blob store, the viewer, `arena submit` (tickets 17 to 19b), or run-control code (ticket 06).
- Do not wire the fresh-context experiment (D22 b) or the hide-the-incumbent variant.

## Acceptance
- `uv run arena text render --theorem putnam_1964_b2` shows a skill with no theorem-specific number and no tactic name, five short tool descriptions, and a packet with the price table, the rates, the library without a token-cost column and goals under step ids.
- The finish fraction is stated once in rendered text. Changing `finish_fraction` in `numbers.yaml` changes that sentence and nothing else, and the consistency test still passes.
- On an over-limit fixture packet, library lines survive after all local-variable lines are gone.
- `memory_text` for a fixture run lists the full best proof, the map, the used library lines, the read-so-far ranges and the open holes with goals.
- The neutrality grep and the literal lint pass; the word-budget table is committed and within its limits.

## Verify
Test budget: targeted files first, the fast suite once at the end. The slow file is listed because the rewritten skill, tool descriptions and messages are what Pi sends to the model and its assertions were changed in checkbox 19; run it once at the end plus once for the baseline. Never `ARENA_SLOW_TESTS=1` over all of `tests/`.
- `uv run pytest -q -p no:cacheprovider tests/test_agent_text.py` -> all pass in under 10 s.
- `uv run pytest -q -p no:cacheprovider tests/test_context.py tests/test_memory.py` -> all pass.
- `uv run arena text budget` -> prints the table in words; `uv run arena text budget --write` followed by `git diff --stat agent-text/README.md` shows no change on a second run.
- `uv run arena text render --theorem Core.InitsUpdatesComm` -> skill, tools and packet; no `{` placeholder left unrendered.
- `grep -rn "arena_probe\|arena_idea\|arena_state\|lemma\|induction" agent-text` -> no output.
- `uv run ruff check <touched files> && uv run ruff format --check <touched files> && uv run ty check arena/memory.py arena/context.py` -> clean.
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_runner.py` -> pass, or each failure identical in your baseline and named.
- At the end, once: `uv run pytest -q -p no:cacheprovider` -> all pass (baseline count plus the new tests; give both); `cd packages/arena-pi && npm test` -> all pass.

## Stop and report if
- Ticket 05a's renderer, `arena text render` or `arena text budget` does not exist or lacks the per-template "where shown" data you need for the table; report what is missing.
- Any data a template needs (price table rows, per-step goals, the map, read events) is not produced by tickets 10a to 15a.
- A neutrality or literal-lint finding sits in code owned by an earlier ticket and cannot be fixed by moving text to a template.
- The packet certification (`certify_manifest`) fails after the section changes and the fix would alter the manifest's meaning.
- A word budget cannot be met without removing a rule listed in checkbox 2; do not drop a rule to meet a budget, report the table.
- The packet is not byte-stable between two builds for the same row and inputs (the prompt cache depends on it): report the differing part.

## Before you start

1. Read, in this order: this whole ticket; `docs/SPEC-harness-v7.md` (sections named in this ticket); the
   `docs/PLAN-harness-v7.md` sections named in this ticket. The plan's decision rows (D1-D39 at the top) are
   binding: do not undo a decision, and do not undo any "probe evidence" listed in the spec's Further Notes.
2. Run `uv sync` once. All Python runs through `uv run`.
3. Record a baseline **before any edit**, only for the tests this ticket touches: run the test files named in
   this ticket's "Verify" section (and the test files for the modules you will change). Keep the output for
   your hand-back. Do **not** run the whole slow suite for a baseline.
4. If something in this ticket contradicts the code you find, or a step is impossible as written, **stop and
   report**. Do not guess, and do not redesign.

## Rules for every change

- Do exactly what the checkboxes ask. Nothing outside this ticket's scope: no drive-by refactors, no renames,
  no "while I'm here" fixes. If you see a real bug outside scope, list it in the hand-back.
- **No model-facing text in code** (D3): any string the model reads (tool descriptions, replies, notices,
  packet text) goes in `agent-text/` (after ticket 05a) and is rendered by the template renderer.
- **Neutral wording** in anything the model reads: graph position and numbers only. Never name a kind of proof
  ("induction", "lemma", "recursion", "simp proof", ...).
- Match the surrounding code: naming, comment density, idioms. Python 3.13, type hints where the file uses them.
- Python you touch must pass `uv run ruff check <files>` and `uv run ruff format <files>`. Fix ty diagnostics
  in the files you touch (`uv run ty check <files>`); do not touch other files to fix them.
- **Test runtime budget.** Today the fast suite (`uv run pytest -q -p no:cacheprovider`, no Lean, no Pi) takes
  about 35 s; `tests/test_runner.py` with `ARENA_SLOW_TESTS=1` takes about 7 min; the full slow suite takes most of
  an hour. So:
  - While developing, run only the tests you changed or that cover the code you changed:
    `uv run pytest -q -p no:cacheprovider tests/test_x.py -k <name>`.
  - Run the fast suite **once**, at the end, before your final commit.
  - Run a slow test file (`ARENA_SLOW_TESTS=1 ...`) only if this ticket's "Verify" lists it, and only **once**
    at the end (plus once for the baseline). Never run `ARENA_SLOW_TESTS=1` on the whole `tests/` directory.
  - `npm test` is under a second; run it whenever you change TS.
  - If a test you add takes more than 5 s, it must be `@slow`.
- Tests: only behaviour where a bug costs points, money or time. No tautological tests (no restating
  constants or config, no "mock was called", no substrings copied from the source under test, no dataclass
  defaults). Python tests are unittest style, run by pytest. Lean- or Pi-backed tests use the `@slow`
  decorator from `tests/slow.py`. TS tests use `node:test`.
- Never read `/proc` or live Lean sessions from a test; inject machine readings.
- Foreground commands only. No background jobs, no polling loops, no `sleep` loops. Kill processes **by PID
  only**, never by name or pattern (`pkill -f`, `killall` are forbidden).
- Never print, log or commit secrets (`.env` holds API keys). Never spend money: no real model calls. Paid runs
  are launched by the owner only.
- Do not edit `docs/`, `research/`, `vendor/` or other tickets. Proposed doc changes go in the hand-back.

## Version control (GitButler)

Your branch is **`v7/16-text`**, already created and stacked directly above `v7/15c-old-tools-out`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/16-text` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/16-text -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-16`.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`,
  `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or
  `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`,
  `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`,
  `branch`, `update-ref`, `push`, `rm`, `mv`). Read-only `git log`, `git show`, `git diff` and `git blame` are
  fine. To delete or move a tracked file, use the shell (`rm`, `mv`); GitButler sees the change.
- If you need to change code a lower ticket introduced, do it in a commit on your own branch and say so in the
  hand-back. If `but commit` reports a dependency or conflict error, stop and report rather than moving branches.

## Hand-back (required)

Your work is finished only when all of this is true:

- [ ] Every checkbox in "What to build" and "Acceptance" is done, or listed below as not done with the reason.
- [ ] Every change is committed on `v7/16-text`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-16
Commits: <id> <summary>, one per line, oldest first
Checkboxes: each checkbox, done / not done (+ reason)
Tests: baseline -> final counts for every command you ran, with failures named
Verify: output summary of each Verify command (timings, numbers)
Files: every file added, changed or deleted, one line each on why
Decisions: anything you had to decide that this ticket did not say
Deviations: anything done differently from the ticket, and why
Out of scope: bugs or problems noticed but not fixed
Open questions: for the reviewer
```

Do not mark the ticket done; the reviewer does.
