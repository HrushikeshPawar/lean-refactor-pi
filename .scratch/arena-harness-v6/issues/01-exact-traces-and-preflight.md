# 01: Exact traces and live preflight

**What to build:** When an Arena run sends a model request or invokes a tool, an operator can inspect the exact provider-bound request, delivered response, tool arguments/results, retry and settled cost through one run identity in Langfuse. A cheap preflight proves this works before paid evaluation.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

**Branch:** `hrushikesh/v6-01-traces` (stacked on `hrushikesh/harness-v6`)

- [ ] Explicitly load the Langfuse integration in Arena runs while keeping the model extension allowlist deterministic; one run identity joins the Pi session, Langfuse session, local events and cost ledger, with distinct attempt and retry identities.
- [ ] Capture the final request **after** Arena's payload hooks and compare its serialized provider-bound body byte-for-byte with a fake provider's received body. Preserve complete system/messages/tool schemas, model/version, output and thinking settings, cache markers and timing.
- [ ] Preserve delivered response content, tool calls, provider usage/cache counters, complete tool inputs and outputs, retries and settled price entries. Provider-hidden reasoning is recorded only in the encrypted or redacted form actually delivered.
- [ ] A request, response and tool result longer than 20,000 characters survive Langfuse query/export without loss, directly or through a linked artifact whose content and hash can be read back. A hash or local-only journal is insufficient.
- [ ] Keep the local journal permission-restricted and exclude credentials and authentication headers from both stores. A missing, clipped or unjoinable observation fails preflight explicitly.
- [ ] Run a cheap real model request and harmless model-visible tool call for each selected provider; read back full input/output, tool span, usage and cost from Langfuse before allowing a paid matrix.
- [ ] Keep the raw request body in the fake-provider wire capture: `tests/pi_support.py` `AnthropicWire` currently stores `json.loads(body)`, which cannot support a byte-for-byte comparison.
- [ ] Use the vendored plugin patch (see "Langfuse plugin patch" below) as the full-request capture in Langfuse. Make applying or checking it reproducible from the repo, and have preflight fail when the installed plugin is not the patched 0.1.2. Load the plugin **after** `arena.ts` in the explicit extension list, and prove with a fake-provider test that the recorded Langfuse input equals the post-Arena-hook request (apart from Langfuse-key redaction).
- [ ] The runner sets `PI_LANGFUSE_MAX_CHARS` high enough to disable the plugin's clipping (e.g. `100000000`) and raises `LANGFUSE_TIMEOUT` from its 5 s default (e.g. `60`); preflight detects any `truncated: true` observation metadata or export failure. The byte-for-byte check compares the local journal with the fake provider's received bytes; Langfuse is checked for equal content, not equal bytes, because the plugin redacts key-like strings.

## Langfuse

**Required.** Use the Langfuse skill (`/langfuse`) and fetch current docs before writing tracing code; do not implement from memory of an older SDK. Instance: self-hosted Langfuse v4 configured in `~/.pi/agent/langfuse.json` (verified v4.50.0, 2026-10-07). Load its keys into `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST` for `npx langfuse-cli`, never print or commit them, and read back through `GET /api/public/v2/observations`; the CLI rejects the legacy traces list endpoint. The installed Pi plugin is `@langfuse/pi-observability-plugin` (Pi npm packages); v5 excluded it via `--no-extensions`.

### Langfuse plugin patch (verified 2026-10-07)

The 20,000-character clip is the plugin's own configurable default, not a Langfuse or Pi limit. Pi loads `src/index.ts` directly; the plugin has no compiled build.
- `src/index.ts:29` sets `MAX_CHARS = PI_LANGFUSE_MAX_CHARS ?? 20000`. `truncateText()` (146-158) applies it to prompts, outputs, tool arguments, tool results and summaries.
- Stock generation input is only a delta. The plugin's `before_provider_request` handler (`:657`) ignores the event, whose `payload` is the full provider-native request in Pi 1.0.4 (`pi-coding-agent/dist/core/extensions/types.d.ts:673-676`). It logs only the first prompt or the pending tool results.
- `:842` cut each pending tool result to 4,000 characters. This affected only that delta field; the tool span kept full output.
- OTel `attributeValueLengthLimit` defaults to Infinity, and `@langfuse/tracing` serializes with plain `JSON.stringify`. The `@langfuse/otel` exporter timeout defaults to 5 s (`LANGFUSE_TIMEOUT`). No server body limit is documented for OTel ingestion. A direct 2 MB input + 2 MB output span was ingested intact.

The patch is `packages/arena-pi/patches/langfuse-pi-observability-plugin-0.1.2-full-payload.patch` (sha256 `c6cd7f65…7625af`, 3 hunks, about 7 lines). It is currently applied to `~/.pi/agent/npm/node_modules/@langfuse/pi-observability-plugin`, and the original is backed up at `~/.pi/agent/patches/pi-observability-plugin.orig-0.1.2`. It changes three things:
- The generation input becomes `redactLangfuseKeys(event.payload)`. The redactor deep-copies the payload, so the sent request is not mutated.
- The old delta moves to `metadata.arena_delta`.
- The 4,000-character cut is removed.

`pi update` or a reinstall overwrites the patch.

The test was a real `qwen3.8-flash` run with the patched plugin and `PI_LANGFUSE_MAX_CHARS=100000000`; the model read a 41,035-character file. Readback through the v2 observations API found the following:
- The generation input was 73,981 characters: the full system prompt, 5 messages, 4 tools, `max_tokens` and thinking, with the start, middle and end markers intact.
- The tool span output was the full 41,035 characters.
- Usage and cost were present.

Pass `</dev/null` to `pi -p`, or it can hang waiting on stdin. A test observation named `big2mb-test` remains in Langfuse.

Watch two things:
- Pi runs `before_provider_request` handlers in load order, and a returned value replaces the payload for later handlers (`runner.js:1066-1095`). The plugin only sees changes made by extensions loaded before it.
- Each generation now stores the whole conversation, so trace volume grows quadratically with turns. Size the export timeout and preflight with a long-session payload.

## Version control (GitButler)

Your branch is **`hrushikesh/v6-01-traces`**, already created and stacked directly above `hrushikesh/harness-v6`. The whole v6 stack is applied in this checkout's `gitbutler/workspace`. The reviewing session reviews, restacks and merges; you must leave the stack exactly as you found it apart from new commits on your branch.

- Before starting, run `but status`. Confirm that `hrushikesh/v6-01-traces` exists, that every lower branch is present, and that no commit is `{conflicted}`. Also confirm that no other implementer has uncommitted changes in this checkout (only one implementer works here at a time). If anything differs, stop and report; do not repair it.
- Commit only your own changes, only to your branch: `but diff`, then `but commit -b hrushikesh/v6-01-traces -m "type(scope): summary" <ids>`. Use hunk IDs when a file also holds unrelated edits. You may `but amend`, `but reword`, `but squash` or `but uncommit` commits **on your own branch only**.
- Never run `but pull`, `but push`, `but pr`, `but merge`, `but move`, `but undo`, `but apply`, `but unapply`, `but branch new`, `but branch delete`, `but config`, `but setup` or `but teardown`. Never run `but discard` or `but resolve` on anything you did not create. Never run any git write command (`git add`, `commit`, `checkout`, `switch`, `reset`, `restore`, `rebase`, `merge`, `stash`, `cherry-pick`, `read-tree`, `worktree`, `branch`, `update-ref`, `push`). Read-only `git log`, `git show` and `git blame` are fine.
- If you need to change code that a lower ticket introduced, make the change in a commit on your own branch and call it out in the hand-back. Do not edit lower branches' commits. If `but commit` reports a dependency or conflict error, stop and report it rather than moving branches.
- Do not edit other tickets or `docs/SPEC-harness-v6.md`; put proposed spec changes in the hand-back.
- **Hand-back:** all your work is committed on `hrushikesh/v6-01-traces` and none of your edits are left uncommitted. Set this ticket's `**Status:**` to `needs-review` in that final commit. Report your commit IDs, the tests you ran with their results, any Langfuse trace or session IDs you used, deviations from the acceptance criteria and open questions. Do not mark the ticket done.
