import assert from "node:assert/strict";
import test from "node:test";
import { continuationKey, continuationPush } from "./rules.ts";

test("a failed request selects its own continuation fact", () => {
  assert.equal(continuationKey(true), "request_failed");
  assert.equal(continuationKey(false), "turn_ended_with_text");
});

test("failure and completed continuations share spend and axis facts", async () => {
  const facts = { usedPct: 40, remainingUsd: 0.06, capUsd: 0.1,
    baseline: { tokens: 224, heartbeats: 4251 }, best: { tokens: 188, heartbeats: 339 } };
  const failed = await continuationPush({ ...facts, failed: true, cause: "Provider timeout" });
  const completed = await continuationPush({ ...facts, failed: false });
  assert.match(failed, /request failed: Provider timeout/i);
  assert.doesNotMatch(failed, /turn ended with text/i);
  assert.match(completed, /turn ended with text/i);
  assert.doesNotMatch(failed, /Best node:/);
  assert.equal(failed.slice(failed.indexOf("$0.04")), completed.slice(completed.indexOf("$0.04")));
  assert.match(failed, /16% saved/);
  assert.match(failed, /92% saved/);
});
