# 01: Exact traces and live preflight

**What to build:** When an Arena run sends a model request or invokes a tool, an operator can inspect the exact provider-bound request, delivered response, tool arguments/results, retry and settled cost through one run identity in Langfuse. A cheap preflight proves this works before paid evaluation.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Explicitly load the Langfuse integration in Arena runs while keeping the model extension allowlist deterministic; one run identity joins the Pi session, Langfuse session, local events and cost ledger, with distinct attempt and retry identities.
- [ ] Capture the final request **after** Arena's payload hooks and compare its serialized provider-bound body byte-for-byte with a fake provider's received body. Preserve complete system/messages/tool schemas, model/version, output and thinking settings, cache markers and timing.
- [ ] Preserve delivered response content, tool calls, provider usage/cache counters, complete tool inputs and outputs, retries and settled price entries. Provider-hidden reasoning is recorded only in the encrypted or redacted form actually delivered.
- [ ] A request, response and tool result longer than 20,000 characters survive Langfuse query/export without loss, directly or through a linked artifact whose content and hash can be read back. A hash or local-only journal is insufficient.
- [ ] Keep the local journal permission-restricted and exclude credentials and authentication headers from both stores. A missing, clipped or unjoinable observation fails preflight explicitly.
- [ ] Run a cheap real model request and harmless model-visible tool call for each selected provider; read back full input/output, tool span, usage and cost from Langfuse before allowing a paid matrix.

