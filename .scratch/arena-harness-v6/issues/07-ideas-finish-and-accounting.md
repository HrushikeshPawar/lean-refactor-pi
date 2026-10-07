# 07: Ideas, finish and run accounting

**What to build:** The agent records a structural route once, sees its attempts and outcomes without repeated bookkeeping, and can end a run after one bounded review. The run summary tells the operator what was tried, what improved and what was spent.

**Blocked by:** 02: Fixed request shape and spend gate; 06: Proof-tool UX and error replay.

**Status:** ready-for-agent

- [ ] One short `arena_idea` creation sets the current strategy. Later probes, evaluations and candidates inherit it unless explicitly overridden; append-only events derive attempts, failures, candidates and best result. A directly promoted complete probe counts as an attempt even without a separate probe event.
- [ ] An agent can revise or abandon an idea with a short reason and can start another without erasing earlier lineage. `arena_state` and status responses are concise, show the verified baseline truthfully and never demand repeated title/hypothesis text.
- [ ] The first argument-free `arena_finish` returns one factual review of the best verified candidate and current idea. At most one reminder is issued for a current idea with no linked proof attempt; the agent can probe or abandon it. A later finish confirms stop, and new ideas cannot reset review/reminder limits.
- [ ] Two consecutive completed turns with no new proof attempt, verified improvement or substantive context result trigger a no-work fallback. A distinct newly returned declaration, goal or source span counts as discovery; repeated reads, idea-only and state-only turns do not reset it. The first finish-review turn is excluded so the agent gets a full decision turn; a confirmed finish sends no further provider request and the spend gate still takes precedence.
- [ ] Sanitized turn-boundary replays preserve the later best candidates after Luna r2's and Qwen CSLib's first finals, then stop after confirmation. Replay Qwen's 16–19-turn search-first discovery without premature fallback and prove repeated identical reads cannot prolong a stalled run. A single failed skeleton does not automatically close an idea.
- [ ] The live log and run/matrix summaries count requests separately from tool results, classify bookkeeping and rejected spend correctly, report retries, cache prefix reuse, overshoot, post-best spend and zero-attempt ideas, and use the **same** candidate for score, tokens and heartbeats.
