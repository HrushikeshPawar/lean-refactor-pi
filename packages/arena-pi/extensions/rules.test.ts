import assert from "node:assert/strict";
import test from "node:test";
import { continuationKey, continuationPush } from "./rules.ts";
import { keys, numbers, render } from "./text.ts";

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
  assert.doesNotMatch(failed, /points left/i);
});


test("continuation facts never name finishing, at any remaining fraction", async () => {
  const metrics = { baseline: { tokens: 224, heartbeats: 4251 }, best: { tokens: 188, heartbeats: 339 } };
  const stopText = /\b(?:finish\w*|stop\w*|threshold\w*|tenth|ends? the run)\b/i;
  const pct = (await numbers()).finish_remaining_pct;
  const limitUsd = 0.1;
  for (const failed of [true, false]) {
    for (const spentUsd of [0, 0.04, 0.095, limitUsd]) {
      const rendered = await continuationPush({ ...metrics, failed, spentUsd, limitUsd });
      assert.doesNotMatch(rendered, stopText, rendered);
      assert.doesNotMatch(rendered, new RegExp(`(?<![\\d.])(?:${pct}|${100 - pct})(?![\\d]|\\.\\d)`), rendered);
    }
  }
});

test("no finish text exists: Pi offers no finish tool", async () => {
  const all = await keys();
  assert.deepEqual(all.filter(key => key.startsWith("tools/finish")), []);
  for (const key of all.filter(key => key.startsWith("replies/") || key.startsWith("messages/") || key.startsWith("tools/"))) {
    let rendered: string;
    try { rendered = await render(key); } catch { continue; }  // a template that needs values cannot be rendered bare
    assert.doesNotMatch(rendered, /\bfinish/i, key);
  }
});
