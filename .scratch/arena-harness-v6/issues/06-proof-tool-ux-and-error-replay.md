# 06: Proof-tool UX and error replay

**What to build:** Natural agent inputs for drafting, scoring and inspecting a proof work through the model-facing tools, while truly invalid data fails clearly. The valid-intent mistakes seen in v5 no longer waste provider turns.

**Blocked by:** 04: Declarations, search and source lookup; 05: Hotspots and live profiles.

**Status:** ready-for-agent

- [ ] Probe one to four drafts per call in the model's Lean lane. Normalize `by` and `:=` bodies against the exact benchmark statement and return one outcome per draft: fails, compiles with holes and goals, or complete and compiling with an automatically promoted candidate ID.
- [ ] Complete probes in a batch are candidates, and partial probes expose all actual hole goals. Stable probe/candidate IDs and parent lineage survive scoring, restoration and profiling.
- [ ] Evaluation accepts complete proof text or an unambiguous stable reference. Conflicting candidate/probe references are rejected or resolved explicitly; `sorry` sent to evaluation points to probing. Diagnostics and profiles label proof-relative and source-file lines accepted by goal lookup.
- [ ] Tool schemas match runtime-required fields. Malformed JSON never silently becomes an empty object; a misnamed tool suggests the nearest registered tool. Missing names, invalid ranges, Lean rejection and provider failure retain distinct typed outcomes.
- [ ] Add a small, sanitized replay fixture for the valid-intent inputs from all 14 v5 runs, independent of ignored local run logs. Classify the 32 historical error-returning calls and achieve zero preventable errors and zero mismatched line lookups on replay without turning genuine failures into success.
- [ ] Demonstrate the complete agent route from batched search or declaration lookup to source, probe, evaluation, profile and goal inspection on pinned Core and PhysLib rows.

