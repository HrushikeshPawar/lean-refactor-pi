import assert from "node:assert/strict";
import { test } from "node:test";
import { classifyFailure, nextWait } from "./outage.ts";

test("classifies transport failures separately from billed model failures", () => {
  assert.equal(classifyFailure({ role: "assistant", content: [], stopReason: "error", usage: { totalTokens: 0 } } as any), "transport");
  assert.equal(classifyFailure({ role: "assistant", content: [], stopReason: "error", usage: { totalTokens: 1 } } as any), "model");
  assert.equal(classifyFailure({ role: "assistant", content: [{ type: "text", text: "failed" }], stopReason: "error" } as any), "model");
  assert.equal(classifyFailure({ role: "assistant", content: [], stopReason: "stop" } as any), undefined);
});

test("backs off exponentially and caps the wait at the outage deadline", () => {
  assert.deepEqual([1, 2, 3, 4, 5].map(attempt => nextWait(attempt, 2000, 100, 100, 600000)), [
    { stop: false, delayMs: 2000 }, { stop: false, delayMs: 4000 }, { stop: false, delayMs: 8000 },
    { stop: false, delayMs: 16000 }, { stop: false, delayMs: 30000 },
  ]);
  assert.deepEqual(nextWait(1, 2000, 100, 599900, 600000), { stop: false, delayMs: 200 });
  assert.deepEqual(nextWait(1, 2000, 100, 600100, 600000), { stop: true });
  assert.deepEqual(nextWait(1, 2000, 500, 500, 600000), { stop: false, delayMs: 2000 });
});
