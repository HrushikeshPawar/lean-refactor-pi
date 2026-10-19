# Full startup packet review, 2026-10-18

These are newly rendered **current baseline** inspection bundles for SKI, Core, and Fiberwise. They are not proposed orchestrator/worker prompts and do not claim that the planned parallel architecture is implemented. Existing cached theorem context and reference profiles were used. No Lean process, Pi session, provider request, campaign, or cache refresh was started.

| Theorem | Full inspection bundle | Exact task packet | Structured sections |
|---|---|---|---|
| SKI diamond | [01-ski.md](01-ski.md) | [01-ski.packet.txt](01-ski.packet.txt) | [01-ski.json](01-ski.json) |
| Core.InitsUpdatesComm | [02-core.md](02-core.md) | [02-core.packet.txt](02-core.packet.txt) | [02-core.json](02-core.json) |
| Binius Fiberwise | [03-fiberwise.md](03-fiberwise.md) | [03-fiberwise.packet.txt](03-fiberwise.packet.txt) | [03-fiberwise.json](03-fiberwise.json) |

## What is included

The Markdown bundles contain the current system prompt, appended Arena skill, tool descriptions and parameter documentation, and all sections emitted by the cache-only theorem renderer. The JSON files preserve those sections individually. The `.packet.txt` files are the exact theorem task packet, byte-matched to `arena.context.render_packet(theorem, cache_only=True)`.

No additional clipping or rewriting was applied to the renderer output. The renderer's normal section selection and packet fitting still apply. These exports are full current rendered packets, not the entire source library or unbounded context cache.

The inspection renderer is `arena text render --theorem`. Its tool documentation is not the provider's JSON tool schema, and the combined inspection bundle is not a captured HTTP request. It also emits a legacy `tools/finish` documentation section; the current Pi extension exposes `compile`, `goal`, `search`, `read`, and `scratch`, not that legacy tool. It is retained here to reproduce the inspection renderer faithfully and flag its drift for review.

No prior run is seeded, and no prior candidate graph, worker transcript, playbook, or cheatsheet is injected. Normal reference proof, goals, scoring, pins, source context, and cached profiles are present. The proposed Sol delegation ledger, shared-spend wording, worker packets, observations, and whiteboard are future design work.

## Review status and questions

The [content and tool-reply review](../reports/PACKET_CONTENT_AND_TOOL_REVIEW_2026-10-18.md) is now complete for these three exports. It identifies extraction/selection defects and proposes a packet/reply redesign. A [generic cheatsheet draft](GENERIC_CHEATSHEET_DRAFT.md) extracts reusable search methods without task-specific solutions. Neither document changes the live prompts or the immutable baseline bundles below. Implementation and controlled efficacy evaluation remain pending.

The [October 17 packet forensic audit](../reports/PACKET_FORENSIC_AUDIT_2026-10-17.md) completed request reconstruction, size, reported usage, cache share, and initial packet-presence checks. It did not establish section usefulness, fact retention after compaction, or a controlled benefit from packet redesign. This export supports that remaining content review.

Review the following points against the full text:

- Are the theorem, scope, reference proof, and score trade-offs clear before the supporting material?
- Which goals, definitions, dependencies, and earlier lemmas are useful immediately, and which could be retrieved on demand?
- Are expensive proof steps visible enough to guide a structural or local hypothesis?
- Does repeated tool documentation obscure information needed for this theorem?
- The skill currently says spend counts "only your own tokens" and "Lean checks are free." The first must change for shared accounting. The second concerns API spend but omits Lean resource use. Both are preserved as baseline evidence here.
- What should the Sol packet retain, and what smaller context must a step or whole-proof worker receive?

## Provenance and reproduction

The [manifest](manifest.json) records theorem names, hashes and sizes of each review/task packet, hashes of every section, and paths/hashes of the context and reference-profile caches consumed. Hashes refer to the rendered content and source caches, not provider-token estimates.

The bundles were generated with `arena.cli.text.render_template(theorem=..., json_output=True)` and formatted identically to its text output. During rendering, live context extraction, profiling, heartbeat-floor calculation, and Lean execution entry points were patched to raise on invocation. All three renders succeeded, and the recombined task sections matched the cache-only task renderer byte for byte.

To inspect the same renderer from the CLI, use:

```bash
.venv/bin/python -m arena.cli text render --theorem Cslib.SKI.parallelReduction_diamond
.venv/bin/python -m arena.cli text render --theorem Core.InitsUpdatesComm
.venv/bin/python -m arena.cli text render --theorem Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius
```

The theorem render command is cache-only and refuses missing context or profile data. Do not replace a refusal with a live context/profile build during packet-only inspection. Changed templates or source/cache versions can change future output; use the saved files and hashes for this review.
