# 03: Certified kickoff dependencies

**What to build:** An agent opening a pinned theorem sees the names the original declaration actually uses, plus additional direct theorem and lemma dependencies from its elaborated proof, and can tell whether the inventory is complete.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Inventory every resolvable source-named declaration in the original theorem declaration. Preserve occurrences and distinguish first appearance in the statement from appearances in the proof without claiming those sets are exclusive.
- [ ] Separately identify additional theorem and lemma constants directly used by the elaborated original proof term. Keep the complete constant index queryable by name, kind and origin; generated tactic and typeclass entries are not presented as source-authored lemmas.
- [ ] The kickoff gives each required name a qualified form, kind, origin and usable source handle; local variables have scope/type. It identifies the pinned revision/toolchain, available tactic imports and original proof as candidate #1.
- [ ] Show a bounded signature preview with inventory/shown/unavailable counts. No required name disappears silently during packet fitting, and a deterministic section manifest fails certification when an expected section is absent.
- [ ] Repeated builds for the same pin have identical packet bytes. Pinned Core and PhysLib fixtures account for every known source name and extra direct theorem/lemma dependency; provisioned rows certify or fail before a paid run.
- [ ] Kickoff guidance asks the agent to survey the supplied references before recording a route; it does not impose a three-ideas-at-start quota.

