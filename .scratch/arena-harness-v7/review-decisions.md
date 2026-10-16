# Ticket review decisions (owner-approved 2026-10-10) — for the editing agents

## Final stack (one straight stack; each branch stacked on the previous row)
| NN | Branch | File | Title | Blocked by (real dependencies) |
|---|---|---|---|---|
| 04 | v7/04-cli-tools | 04-cli-tools.md | Move the remaining tools into the CLI; arena doctor | 03 |
| 05a | v7/05a-agent-text | 05a-agent-text.md | Agent text: format, renderers, numbers.yaml, skill/packet/memory moved verbatim, `arena text` | 04 |
| 05b | v7/05b-agent-messages | 05b-agent-messages.md | Agent text: campaign/engine/TS messages moved verbatim, literal lint | 05a |
| 06 | v7/06-run-fixes | 06-run-fixes.md | Run-control fixes | 02, 04, 05b |
| 07 | v7/07-lean-gate | 07-lean-gate.md | Lean speed baseline and gate | 04, 06 |
| 08a | v7/08a-lean-service | 08a-lean-service.md | Machine-wide Lean service process | 07 |
| 08b | v7/08b-lean-lanes | 08b-lean-lanes.md | Lean service lanes, memory, goals/snippets on the LSP lane | 08a |
| 08c | v7/08c-lean-callers | 08c-lean-callers.md | Lean service callers, tests, speed gate | 08b |
| 08d | v7/08d-repl-pool | 08d-repl-pool.md | REPL pool and v4.32 header trial | 08c |
| 09 | v7/09-scheduler | 09-scheduler.md | Campaign scheduler | 08c |
| 10a | v7/10a-graph-core | 10a-graph-core.md | Graph core: steps, edges, focus, operations | 04, 05b |
| 10b | v7/10b-step-goals | 10b-step-goals.md | Per-step goals pipeline | 10a, 08c |
| 11 | v7/11-routes | 11-routes.md | Routes, K1 archive, map, stall (drops LLM route extraction) | 10a |
| 12 | v7/12-salvage | 12-salvage.md | Salvage chain and auto-assembly | 10a, 08c |
| 13 | v7/13-prices | 13-prices.md | Price engine and instant token quotes | 10b, 11, 08c |
| 14 | v7/14-search | 14-search.md | Declaration index and search | 04, 05a |
| 15a | v7/15a-tool-handlers | 15a-tool-handlers.md | Five-tool Python handlers + reply schema beside the old tools | 05b, 11, 12, 13, 14 |
| 15b | v7/15b-tool-surface | 15b-tool-surface.md | TS five-tool surface, MCP server removed | 02, 15a |
| 15c | v7/15c-old-tools-out | 15c-old-tools-out.md | Delete old tools, ideas, v6-shape tests | 15b |
| 16 | v7/16-text | 16-text.md | Full text rewrite, compaction memory, packet | 15c |
| 17 | v7/17-replay | 17-replay.md | Replay blob store and `arena replay` | 05b, 10a |
| 18 | v7/18-viewer | 18-viewer.md | Viewer "Reasoning & calls" tab | 17 |
| 19a | v7/19a-submit | 19a-submit.md | `arena submit`: selection, gates, outputs, filter parity | 10a, 13 |
| 19b | v7/19b-recombine | 19b-recombine.md | Cross-run recombination; `auto_merge` exclusion removed | 19a |
| 20 | v7/20-campaign | 20-campaign.md | Owner's paid campaign (owner-only) | 16, 06 |
The lower branch of each row is the previous row (04's lower is v7/03-cli).

## Decisions to apply in the tickets
1. Splits as above. Each part is its own ticket file with the full format; each part must leave the fast suite
   green and be finishable on its own. Move checkboxes, context, Do NOT, Acceptance, Verify, Stop-and-report items
   to the part they belong to; add any glue a part needs so it stands alone (e.g. 15a builds new handlers beside the
   old ones so nothing breaks; 15c deletes).
2. Library token-cost column is DROPPED everywhere (packet, search results, price engine, map). Reason: the official
   counter scores any identifier as one token (verified: `Nat.add_comm_of_very_long_name_here`, `𝔽q`,
   `Nat.add_comm` each count 1). The ranked top-60 library stays (D34). Remove any checkbox that builds
   `library_token_costs` / name token cost; do not replace it.
3. Health gate (revised): the model starts as soon as the PRIMARY toolchain's reference proof passes. The reference
   checks on every other listed toolchain still run, in the background, during the run; if any fails, the run is
   marked unhealthy and stopped before further spend (truthful stop reason). Final verification at close-out still
   cold-compiles the best proof on every listed toolchain, and `arena submit` still requires every toolchain green.
   (Lives in 08b/08c where the gate is changed.)
4. Speed gate noise floor 0.25 s: a figure fails only if it exceeds BOTH the relative tolerance (+10% p50, +20% p95)
   AND 0.25 s absolute. The gate (ticket 07's `arena lean bench` + slow gate test against
   `benchmark/derived/lean-baseline.json`) is run once at the end of every ticket that touches Lean machinery:
   08a, 08b, 08c, 08d, 10b, 12. Never part of the fast suite.
5. #35 truncated turns (06): set Pi's maxTokens to the run's output ceiling via a supported Pi mechanism; if none
   exists, stop and report.
6. Finish is ONE call that stops at once (no confirm step; it is already hidden until <=10% remains).
7. `arena submit` keeps the $3.00 per-problem total, summed over all contributing runs, as a reported gate
   (`--ceiling-usd`, default 3.0).
8. Stall target default `best_other_cell` (env switch for the A/B); route 13+ joins the best-scoring route (routes
   stay frozen once filed); filing similarity threshold 0.50 (do not tune).
9. REPL pool adopted only if: 0 pass/fail disagreements on every compared row, heartbeats within 5%, batch p50
   within +10% of LSP background p50, and either header load <= half a fresh open or PSS per process below an LSP
   worker's; otherwise ships disabled (`REPL_ENABLED = False`), ticket still complete.
10. `arena text budget` counts WORDS (not the Lean token counter).
11. The lean-lsp-mcp server is REMOVED in 15b (D40). 08b must provide on the LSP lane: goals at a position/hole and
    running a snippet at a hole (`goal try`). Remove any text saying MCP becomes a hidden backend.
12. Spec stories 28 and 29 go into 08b: cross-version checks only for candidates that could become the best verified
    (plus close-out); probe timeout ~3x warm p95 instead of 180 s (with partial messages on timeout).
13. "All errors at once, each with its goal" (#9, plan §5f) goes into 15a.
14. #26 (factual continuation text after a failed request) and #27 (malformed/null tool arguments) go into 15b.
15. Test budget (owner rule): Verify lists only targeted test files; fast suite once at the end; a slow file only when
    the ticket changes Lean/Pi behaviour; never `ARENA_SLOW_TESTS=1` over all of tests/.

## Mechanics
- Every ticket's header `**Blocked by:**`, `**Branch:**` (with "stacked on <lower>") must match the table.
- Every implementer ticket ends with the CURRENT `.scratch/arena-harness-v7/issues/_common.md` content (below its
  comment block) with <NN>, <BRANCH>, <LOWER> replaced. Re-paste it; do not keep an older copy.
- Cross-references between tickets use the new ids (e.g. "ticket 08c", "15a").
- Delete the old files you replace (e.g. 05-agent-text.md after writing 05a/05b) with `rm`.
- Edit only the files assigned to you. No VCS commands. Foreground commands only.
