# 04: Declarations, search and source lookup

**What to build:** An agent can pass several names at once, read complete pinned declarations where source exists, search for other helpers, and follow every returned handle to the right file and line without guessing path syntax.

**Blocked by:** 03: Certified kickoff dependencies.

**Status:** ready-for-agent

- [ ] Model-facing `arena_declarations` accepts several qualified names or returned handles and gives one result per input: complete human-readable source statement and body/proof, or a typed reason that a body is opaque, generated, private, external or unavailable. Local variables return scope/type instead of a fabricated global body. Replace the model-facing single-name `arena_declaration` rather than leaving two competing lookup paths.
- [ ] Long declarations page without losing content or silently dropping other requested names. Source bodies come from the pinned checkout; pretty-printed elaborated terms are not mislabeled as source proofs.
- [ ] Model-facing `arena_find` accepts several names or strings, counts distinct qualified declarations toward its limit, excludes scratch copies, and supplies useful qualified-name suggestions for misses. An unvalidated related-lemma ranking formula is not silently introduced.
- [ ] Every handle emitted by kickoff, search or declaration lookup round-trips through `arena_source`. Known project aliases and dependency roots resolve; results state pin, canonical path, file length and one-based file lines.
- [ ] Tests cover local, imported, private, generated, long and unavailable declarations, ambiguous names, bad ranges and returned-handle round trips on at least two theorem families. Genuine not-found results remain explicit errors.
