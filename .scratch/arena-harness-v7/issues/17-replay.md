# 17: Replay blob store and `arena replay`

**What to build:** Every provider request in a run records exactly what the model saw, with exact joins. The system prompt, skill, tool schemas and packet are stored once each under their sha256 in a per-run blob store and referenced by hash from each request row. Every journal and ledger record carries a turn index, and every tool and node record carries the tool call id and request id. `arena replay <run> [--turn N] [--node nX] [--raw] [--json] [--render v7]` shows, for any turn of any journaled run (v6 runs included), the system prompt, skill, packet, tools, messages, each tool result as delivered with its trim difference, and that turn's reasoning, response and cost.

**Blocked by:** 05b: Agent text: campaign/engine/TS messages moved verbatim, literal lint; 10a: Graph core: steps, edges, focus, operations (both are committed below your branch).

**Status:** needs-review

**Branch:** `v7/17-replay` (stacked on `v7/16-text`)

**Read first:** spec "Replay and viewer" (Implementation Decisions, Modules), user stories 94-98 and 100, Testing Decisions seam B (journal records sufficient for an exact replay); plan §7a (all of it, including "Gaps today" and "v7 records"); decisions D11, D24. Ticket 16 (full text rewrite) is already committed below your branch and owns the `--render v7` map and reply sections (item 12).

## Context: where things are now
- `packages/arena-pi/extensions/journal.ts`: `DeltaChain` (stores a payload as the bytes between the prefix and suffix it shares with the previous one; keyframe every `KEYFRAME_EVERY` = 25 rows), `sha256`, `deltaBytes`, `applyDelta`. It has a test file `journal.test.ts`.
- `packages/arena-pi/extensions/arena.ts`, inside `arenaExtension`:
  - `appendTrace(event)` appends one row to `trace-journal.jsonl` (adds `ts`); `appendCost(event)` appends to `cost-ledger.jsonl`.
  - `hookFields(published)` encodes the post-hook payload into the request row (`post_hook_sha256`, `post_hook_encoding`, `post_hook_prefix`, `post_hook_suffix`, `post_hook`).
  - `pi.on("before_provider_request")` writes the `request` row (`id` = request id, `run_id`, `retry_of`, `model`, post-hook fields) and sets `pendingRequest` / `openAttempt`. `pi.on("after_provider_response")` writes `http_response`. `pi.on("message_end")` writes the `response` row (`content` blocks incl. `thinking`, `text`, `stop_reason`, `usage`, `settled_usd`) and the settle row via `settle(...)`.
  - `pi.on("tool_execution_start")` writes `tool_call` (`id` = the request id, `tool_call_id`, `name`, `args`); `pi.on("tool_execution_end")` writes `tool_result` (`result` as delivered, `text` = untrimmed text when trimmed, `trimmed: true`, `is_error`).
  - `pi.on("tool_result")` trims the result (`trimmer`, kept in `untrimmed` map) and appends the footer line (`stateLine` + `spendFooter`) to the delivered content. Today the footer is not a separate field.
  - `registerTool` (a wrapper near the top of `arenaExtension`) wraps every tool's `execute(id, params, ...)`. `campaign(action, args)` spawns `uv run --no-sync arena protocol <action> ...`; the child does not know Pi's tool call id.
- `arena/campaign.py` `_append(directory, event)` writes every `ledger.jsonl` row (`ts` + event). The ticket-10a graph event log writer also appends node and edge events (find it with `grep -n "def .*append\|event_log\|event log" arena/*.py`).
- `arena/traces.py`: `expand_journal(rows)` and `read_journal(path)` restore delta-compressed `post_hook` payloads and check their sha256. Ticket 02 removed the `wire` rows, so `request` rows are the record (decision D24).
- A v6 request payload is an OpenAI chat body: keys `model, messages, stream, stream_options, max_tokens, tools, thinking, reasoning_effort`. `messages[0]` is the system message; its text holds the system prompt, then an `<addendum>...</addendum>` section holding the skill. The first user message holds the kickoff packet (also saved as `<run>/packet.txt`). Example run: `runs/pi-budget/v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1/` (97 requests; use it for manual checks only, never copy it into the repo).
- `arena/cli/__init__.py`: the Cyclopts `app`; `arena replay` does not exist yet.

## What to build
- [ ] 1. Pure splitter, written twice with the same behaviour. Add `splitRequest(payload)` to `packages/arena-pi/extensions/journal.ts` and `split_request(payload) -> dict` to a new `arena/replay.py`. Both take a post-hook payload (OpenAI chat shape above) and return `{system, skill, tools, packet, messages}`: `tools` = canonical JSON text of the `tools` array (`JSON.stringify` / `json.dumps(..., separators=(",", ":"), ensure_ascii=False)`); `system` = text of `messages[0]` before `<addendum>`; `skill` = text between `<addendum>` and `</addendum>` (empty string when absent); `packet` = the text of the first `user` message; `messages` = the payload's messages unchanged. A payload that does not match (no system message, no tools key) returns the missing parts as empty strings and never throws. Cross-language parity fixture: `tests/fixtures/replay/request-payload.json` (a small hand-built payload) and `tests/fixtures/replay/request-split.json` (the expected parts and their sha256 hashes); both the TS and the Python test read the same two files.
- [ ] 2. Blob store in `journal.ts`: `class BlobStore { constructor(directory: string); put(text: string): string }` writes `<directory>/<sha256>` only when absent (write to a temp name, then rename) and returns the sha256 of the UTF-8 bytes.
- [ ] 3. In `arena.ts` `before_provider_request`: split the payload, `put` the system, skill, tools and packet texts into `<run directory>/blobs/`, and add `blobs: {system, skill, tools, packet}` (hashes; omit a key whose text is empty) to the `request` row. The existing `post_hook` fields stay as they are (the delta chain already makes repeated text cheap; do not replace payload parts with placeholders).
- [ ] 4. Turn index. Keep one counter `turn` in `arenaExtension`, reset in `session_start` to the number of `request` rows already in the journal (so a resumed run continues), incremented in `before_provider_request`. Stamp (through a pure `stampRecord(row, turn, requestId)` in `journal.ts`) `turn` and `request_id` (the request's `id`) on every row of `trace-journal.jsonl` (`request`, `http_response`, `response`, `tool_call`, `tool_result`, `compaction_repair`) and on every `cost-ledger.jsonl` row written during that request (`settle`, `control`, `finish`, `discovery`, `cache_alarm`, `memory`). Rows written before the first request have `turn: 0` and no `request_id`.
- [ ] 5. Tool call id on node and ledger events. In the `registerTool` wrapper run `tool.execute` inside a Node `AsyncLocalStorage` store `{toolCallId, requestId, turn}`; `campaign()` reads the store and passes `ARENA_TOOL_CALL_ID`, `ARENA_REQUEST_ID`, `ARENA_TURN` in the spawned child's environment. This keeps working with the five-tool surface of ticket 15b, which is already committed below your branch,, because the wrapper is the only place that changes.
- [ ] 6. Python side: add `call_context() -> dict` to `arena/traces.py` returning `{"tool_call_id":..., "request_id":..., "turn": int}` from those three environment variables (keys absent when the variable is unset). `arena/campaign.py` `_append` and the ticket-10a graph event log writer both merge `call_context()` into every row they write (never overriding keys the event already has).
- [ ] 7. Trimmed text and footer as separate fields. In `arena.ts` stash the footer line the `tool_result` hook appends (alongside `untrimmed`) and write it to the `tool_result` journal row as `footer`; the row keeps `result` (as delivered, with footer), `text` (untrimmed) and `trimmed`. Add `delivered_text` (the delivered text without the footer).
- [ ] 8. `arena/replay.py`, `load_run(run_id, runs_root=None)`: reads `trace-journal.jsonl` through `arena.traces.read_journal`, the run's `ledger.jsonl` and `cost-ledger.jsonl`, and `run-config.json`; groups rows into turns. A turn = one `request` row plus its `response`, `tool_call` and `tool_result` rows. Turns are numbered 1..N in request order using the row's `turn` when present, else the request's position (v6 journals have no `turn`). A run with no journal raises `ReplayError("no trace journal: <run> predates the journal and cannot be replayed")`.
- [ ] 9. `request_parts(turn, run_directory)`: when the request row has `blobs`, read the parts from `<run>/blobs/<hash>` (a missing blob raises `ReplayError` naming the hash); otherwise call `split_request(post_hook)`. Messages always come from the `post_hook` payload.
- [ ] 10. Node resolution for `--node`. `node_turn(run, node)` returns the turn that created the node: when the ledger or event-log row that created the node carries `tool_call_id`, join on it (exact); otherwise (v6 runs) pick the `tool_call` / `tool_result` pair whose timestamps (`ts` seconds in the ledger, milliseconds in the journal) enclose the node's `candidate` ledger row; a batch call that created several nodes returns the same turn for each, ordered by time. A node with no match raises `ReplayError` naming the node. Accept `nX` ids, and for v6 runs `#N` and the candidate hash prefix.
- [ ] 11. Renderer. `render_turn(run, turn, raw=False)` returns an ordered list of `(title, text)` sections: run config, system prompt, skill, packet, tools (one line per tool: name and the first sentence of its description), messages up to this turn (role, text, reasoning when present, tool calls), each tool result of earlier turns as delivered with a unified diff against its untrimmed text when `trimmed`, then this turn's reasoning (`thinking` blocks), response text, tool calls, usage and cost (`settled_usd`). `raw=True` returns the single section holding the request's exact payload bytes (the restored `post_hook` JSON). No model-facing wording is produced here: section titles are operator labels only.
- [ ] 12. `--render v7`: `rerender_v7(run, turn)` returns the sections the v7 surfaces would have shown at that turn, built from the same ledger: the packet rendered by the ticket-05a renderer for the run's theorem (`arena.context.render_packet`, which reads `agent-text/`), and a node table (id, status, per-axis score, parent) of the nodes created before that turn, from the ledger or event log. Make it an extension point: a module dict `V7_SECTIONS: dict[str, Callable[[Run, int], tuple[str, str]]]` in `arena/replay.py` that `rerender_v7` iterates in insertion order. This ticket registers exactly two sections, `packet` and `nodes` (the two above). Ticket 16 owns the v7 map and reply text and their render functions (it is committed below your branch); this ticket only provides the extension point. If ticket 16 exposes render functions for the map and for a node's reply (find them with `grep -n "def .*map\|def .*reply" arena/text.py arena/context.py arena/*.py`), register each as one more entry (`map`, `reply`); if it exposes none, do not write them: register only the two sections and list this in the hand-back. Works on v6 runs (a section that cannot be built from a v6 ledger returns an empty body, never raises).
- [ ] 13. CLI. In `arena/cli/__init__.py` add a real Cyclopts command `replay(run: str, *, turn: int | None = None, node: str | None = None, raw: bool = False, json: bool = False, render: str | None = None)` printing Rich panels in the order of item 11 (`--json` prints `{"turn": N, "sections": [{"title", "text"}...]}`). `--render` accepts only `v7`; any other value exits with code 2 and a message listing `v7`. Without `--turn` and `--node` the command prints a one-line-per-turn index (turn, time, tools called, cost) instead. `--turn` and `--node` together exit with code 2. `ReplayError` prints its message and exits with code 1.
- [ ] 14. Tests (seam B for records; pure unit for the renderer). Python, in a new `tests/test_replay.py`: (a) `split_request` matches the shared fixture's expected parts and hashes; (b) a hand-built journal in v6 shape (no `turn`, no `blobs`) loads as numbered turns and `request_parts` splits from the payload; (c) a journal row with `blobs` reads its parts from the blob files, and a deleted blob raises `ReplayError` naming the hash; (d) `node_turn` joins by `tool_call_id` when present, by time enclosure for a v6 ledger, and orders two nodes created by one batch call; (e) a trimmed tool result renders with a diff between delivered and untrimmed text; (f) `rerender_v7` on a v6 fixture returns the packet and node table sections; (g) the CLI refuses `--turn` with `--node`, and a run with no journal exits 1 with the "predates the journal" message. TS, in `journal.test.ts`: `splitRequest` matches the same fixture; `BlobStore.put` returns the sha256, is idempotent and never rewrites an existing blob. Also extract the row stamping of item 4 into a pure `stampRecord(row, turn, requestId)` in `journal.ts` (returns the row with `turn` and, when given, `request_id`, never overriding existing keys) and test it in `journal.test.ts`.
- [ ] 15. Seam B test: using the existing fake provider support in `tests/pi_support.py` and `tests/test_runner.py`, add one `@slow` test that runs a short fake-provider session and asserts the journal has, for every turn, a `request` row with `blobs` hashes whose files exist and hash correctly, a `turn` on every journal and cost row, and a `tool_call_id` on every `candidate` row in `ledger.jsonl` written by a tool call. Skip it with the `slow` decorator exactly as the neighbouring tests do.

## Do NOT
- Do not change what is sent to the model or the payload bytes (the hooks return the payload unchanged except for the existing output-token ceiling).
- Do not add a fetch hook for wire bytes and do not bring back `wire` rows (D24).
- Do not replace any part of the stored `post_hook` payload with a blob placeholder; `expand_journal` and its sha256 check must keep working on old and new rows.
- Do not write model-facing text. Replay section titles are operator labels. Anything the v7 re-render shows to the model comes from `agent-text/` through the renderer.
- Do not touch the viewer (ticket 18), `arena submit` (tickets 19a, 19b), tool handlers, the graph model, or Langfuse code; Langfuse stays a secondary view (story 100).
- Runs from before the journal (v5) are not replayable: error, not a guess.
- Do not copy real run journals into `tests/fixtures`; hand-build tiny fixtures.

## Acceptance
- `uv run arena replay runs/pi-budget/v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1` prints a 97-row turn index; `--turn 5` prints the system prompt, skill, packet, tools, the messages through turn 4 (tool results with trim diffs), then turn 5's reasoning, response and cost.
- `--raw --turn 5` prints the exact payload JSON whose sha256 equals the request row's `post_hook_sha256`.
- `--node` resolves a v6 node to its turn; `--render v7 --turn 5` shows the v7 packet and node table.
- A new fake-provider run has `blobs/` with four hashes per distinct request body part, a `turn` and `request_id` on every row, and a `tool_call_id` on its node rows.
- The system prompt, skill and tools appear once in `blobs/` however many turns the run has.

## Verify
- `uv run pytest -q -p no:cacheprovider tests/test_replay.py tests/test_traces.py` -> all pass (baseline + new).
- `cd packages/arena-pi && npm test` -> all pass (baseline + new; this ticket changes TS).
- `ARENA_SLOW_TESTS=1 uv run pytest -q -p no:cacheprovider tests/test_replay.py` -> pass, once (this ticket changes Pi behaviour; the file holds the slow fake-provider test). Do not run any other slow file.
- `uv run arena replay runs/pi-budget/v6ark-Binius.BinaryBasefold.fold_advances_eval-deepseek-v4.1-flash-r1 --turn 5 --json | python3 -c "import json,sys; print(len(json.load(sys.stdin)['sections']))"` -> a number of 8 or more.
- `uv run arena replay runs/pi-budget/bench-after-7ca1f7` -> exit code 1 and the "predates the journal" message if that directory has no journal; otherwise pick any run directory without `trace-journal.jsonl`.
- `uv run ruff check arena/replay.py arena/traces.py arena/campaign.py arena/cli/__init__.py tests/test_replay.py`, then the same files with `uv run ruff format --check` -> clean.
- Last, once: `uv run pytest -q -p no:cacheprovider` (fast suite) -> all pass (baseline count + the new tests).

## Stop and report if
- The ticket-10a event log has no single writer function to stamp (item 6), or the node-creating event has no timestamp to join on.
- Pi's `before_provider_request` payload for a configured model is not an OpenAI-chat shape (no `messages[0]` system message): report the shape instead of widening the splitter.
- The `<addendum>` marker is gone or renamed after the ticket 05a/16 text moves (then the skill split must be redefined: ask).
- Adding `turn` or `request_id` to a row breaks `arena/traces.py` `judge` or `tests/test_traces.py`.
- `AsyncLocalStorage` does not propagate into `campaign()` calls (check that a stamped row arrives).

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

Your branch is **`v7/17-replay`**, already created and stacked directly above `v7/16-text`. The whole v7 stack is
applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; leave the
stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `v7/17-replay` exists, that every lower branch is present, that no
  commit is `{conflicted}`, and that there are no uncommitted changes. If anything differs, **stop and report**;
  do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then
  `but commit -b v7/17-replay -m "<message>" <id> <id>`. Use hunk IDs (`<file-id>:<hunk-id>`, copied from
  `but diff`) when a file also holds changes that belong in another commit. You may `but amend`, `but reword`,
  `but squash` or `but uncommit` commits **on your own branch only**.
- **Atomic commits.** One coherent change per commit: for example, a refactor that moves code without changing
  behaviour, then the behaviour change with its tests, then a deletion. Tests go in the same commit as the
  behaviour they verify. Every commit leaves the fast suite green.
- **Commit messages.** `type(scope): summary` (types: feat, fix, refactor, test, chore, docs, style, build;
  summary under 72 characters, imperative). Then a blank line and a body that says what changed, why, any
  decision you made, and how you verified it. End every message with the line
  `Ticket: v7-17`.
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
- [ ] Every change is committed on `v7/17-replay`; `but status` shows no uncommitted changes.
- [ ] This ticket's `**Status:**` line says `needs-review`, changed in your final commit.
- [ ] The fast suite (once, at the end), `npm test`, ruff on touched files and every "Verify" command pass, or
      each failure is shown to fail identically in your baseline. No full slow-suite run.

Then reply with a **review report** in exactly this shape:

```
## Review report: v7-17
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
