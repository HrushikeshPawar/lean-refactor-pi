# 02: Fixed request shape and spend gate

**What to build:** A proof run can use its allowance without the harness reshaping a request at the edge. The operator can see why a request was sent or refused and reconcile every charged attempt to the per-problem total.

**Blocked by:** 01: Exact traces and live preflight.

**Status:** ready-for-agent

- [ ] Keep output limit, thinking presence and thinking budget fixed from the first through the last request of a run, including continuations and retries. Never shrink or delete them to consume a small remaining balance.
- [ ] Check a conservative estimate before every provider send and continuation against the aggregate closed-track $3 per-problem ceiling. Decline an unaffordable request before transport; count retries and discarded candidates in the same ledger.
- [ ] Record the estimate, gate decision, actual settled cost, cache read/write, remaining allowance and overshoot for each attempt. The gate does not encode an unproven Qwen output-cap cache threshold.
- [ ] A fake-provider replay with a near-cap balance shows the final provider-bound request shape is identical to earlier attempts when sent, and no request is sent when the estimate is unaffordable. The journal and Langfuse observations agree with the ledger.
- [ ] The first refused request and a refused continuation end cleanly with the best verified candidate and a truthful stop reason; no partial candidate is presented as verified.

