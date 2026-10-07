# 05: Hotspots and live profiles

**What to build:** The kickoff points an agent to the ten most costly starting lines in the reference proof, and the same agent can request an honest heartbeat and token profile after compiling a new candidate.

**Blocked by:** 03: Certified kickoff dependencies.

**Status:** ready-for-agent

- [ ] Derive the top-ten ranking from all raw tactic records before detailed-output truncation. Attribute nested tactic **self** heartbeats to their starting proof line, combine that baseline cost with proof-line tokens using the row's score exchange rates, and display both axes with proof/file coordinates and tactic spans.
- [ ] Count tokens with the competition's proof tokenizer and maintain a source map through comment and blank-line removal. Per-line counts reconcile to the whole-proof token total; otherwise mark token attribution unavailable rather than inventing numbers.
- [ ] The kickoff distinguishes measured whole-proof heartbeats, attributed tactic coverage, statement floor and unattributed remainder. It labels the ranking as baseline cost, not predicted savings, and remains deterministic for a pinned row.
- [ ] `arena_profile` accepts the original or any complete compiling candidate and returns a full source-ordered heartbeat/token profile with both line coordinate systems. `arena_evaluate` reports whole-proof totals; repeat profiling of identical proof text uses a valid cache.
- [ ] Instrument only a scratch copy, on the row-selected measurement toolchain, with synchronous elaboration and no heartbeat limit. Insert wrappers before attached doc comments/attributes and preserve name resolution inside the theorem's scope. Never require instrumentation in a submitted proof.
- [ ] Pinned Core and PhysLib tests cover nested/multi-line tactics, top-ten order, no inclusive-cost double counting, token reconciliation, measured-versus-profile coverage, line mapping and a clearly labeled coarse fallback when fine instrumentation fails. No fabricated zero-cost table passes certification.

