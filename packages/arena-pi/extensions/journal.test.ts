import assert from "node:assert/strict";
import test from "node:test";
import { applyDelta, DeltaChain, deltaBytes, KEYFRAME_EVERY } from "./journal.ts";

const body = (messages: string[], tail = '"max_tokens":16000') => Buffer.from(`{"messages":[${messages.map(m => JSON.stringify(m)).join(",")}],${tail}}`);

test("a growing payload stores only what was added, and the delta restores the exact bytes", () => {
  const first = body(["a".repeat(5000)]);
  const second = body(["a".repeat(5000), "b".repeat(300)]);
  const delta = deltaBytes(first, second);
  assert.ok(delta.middle.length < 400);
  assert.deepEqual(applyDelta(first, delta), second);
  assert.deepEqual(applyDelta(first, deltaBytes(first, first)), first);
});

test("deltas never cut a multi-byte character and survive shrinking and unrelated payloads", () => {
  const samples = [body(["héllo wörld ✓ 𝒳𝒴𝒵"]), body(["héllo wörld ✓ 𝒳𝒴"]), body(["héllo wörld ✓ 𝒳𝒴𝒵 more"], '"x":"é"'),
    Buffer.from("totally different"), Buffer.alloc(0), body(["𝒳"]), body(["𝒴"])];
  for (const previous of samples) for (const current of samples) {
    const delta = deltaBytes(previous, current);
    assert.equal(Buffer.from(delta.middle, "utf8").toString("utf8"), delta.middle);
    assert.deepEqual(applyDelta(previous, delta), current);
  }
});

test("a chain starts and restarts with a full keyframe", () => {
  const chain = new DeltaChain();
  const kinds: boolean[] = [];
  for (let index = 0; index < KEYFRAME_EVERY + 2; index++) kinds.push(chain.encode(body([`m${index}`])).delta === undefined);
  assert.equal(kinds[0], true);
  assert.equal(kinds[1], false);
  assert.equal(kinds[KEYFRAME_EVERY], true);
  assert.equal(kinds[KEYFRAME_EVERY + 1], false);
});
