import assert from "node:assert/strict";
import { test } from "node:test";
import { applyToolTurnEffort } from "./thinking.ts";

test("sets configured effort only after tool results without mutating payload", () => {
  const input = { messages: [{ role: "tool", content: "result" }], other: true };
  assert.deepEqual(applyToolTurnEffort(input, "none"), { ...input, reasoning_effort: "none" });
  assert.equal("reasoning_effort" in input, false);
  const user = { messages: [{ role: "user", content: "next" }] };
  assert.equal(applyToolTurnEffort(user, "none"), user);
  assert.equal(applyToolTurnEffort(input, undefined), input);
  assert.equal(applyToolTurnEffort(null, "none"), null);
  assert.equal(applyToolTurnEffort("payload", "none"), "payload");
});

import { requestDetailedSummary } from "./thinking.ts";

test("requestDetailedSummary sets summary on Responses payloads only", () => {
  assert.deepEqual(requestDetailedSummary({ reasoning: { effort: "high", summary: "auto" } }),
    { reasoning: { effort: "high", summary: "detailed" } });
  const chat = { messages: [] };
  assert.equal(requestDetailedSummary(chat), chat);
});
