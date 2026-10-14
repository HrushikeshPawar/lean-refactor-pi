import assert from "node:assert/strict";
import test from "node:test";
import { continuationKey, continuationPush } from "./rules.ts";
import { numbers, render } from "./text.ts";

test("a failed request selects its own continuation fact", () => {
  assert.equal(continuationKey(true), "request_failed");
  assert.equal(continuationKey(false), "turn_ended_with_text");
});

test("failure and completed continuations share spend and points-left facts", async () => {
  const facts = { spentUsd: 0.04, limitUsd: 0.1,
    baseline: { tokens: 224, heartbeats: 4251 }, best: { tokens: 188, heartbeats: 339 } };
  const failed = await continuationPush({ ...facts, failed: true, cause: "Provider timeout" });
  const completed = await continuationPush({ ...facts, failed: false });
  assert.match(failed, /request failed: Provider timeout/i);
  assert.doesNotMatch(failed, /turn ended with text/i);
  assert.match(completed, /turn ended with text/i);
  assert.equal(failed.slice(failed.indexOf("$0.04")), completed.slice(completed.indexOf("$0.04")));
  assert.match(failed, /tokens 28\.0/);
  assert.match(failed, /heartbeats 2\.7/);
});


test("finish is named only once the final tenth of the limit is reached, and then once", async () => {
  const metrics = { baseline: { tokens: 224, heartbeats: 4251 }, best: { tokens: 188, heartbeats: 339 } };
  const stopText = /\b(?:finish\w*|stop\w*|threshold\w*|tenth)\b/i;
  const pct = (await numbers()).finish_remaining_pct;
  const limitUsd = 0.1;
  const edge = limitUsd * (1 - pct / 100);
  for (const failed of [true, false]) {
    for (const spentUsd of [0, 0.04, edge - 0.001]) {
      const before = await continuationPush({ ...metrics, failed, spentUsd, limitUsd });
      assert.doesNotMatch(before, stopText, before);
      assert.doesNotMatch(before, new RegExp(`(?<![\\d.])(?:${pct}|${100 - pct})(?![\\d]|\\.\\d)`), before);
    }
    const finishLine = await render("messages/continuation.finish_available");
    for (const spentUsd of [edge, 0.095, limitUsd]) {
      const after = await continuationPush({ ...metrics, failed, spentUsd, limitUsd });
      assert.equal(after.split("\n").filter(line => line === finishLine).length, 1, after);
      assert.equal(after.split("\n").filter(line => stopText.test(line)).length, 1, after);
    }
  }
});
