import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { applyDelta, BlobStore, DeltaChain, deltaBytes, KEYFRAME_EVERY, splitRequest, stampRecord } from "./journal.ts";

const fixtureDir = resolve(import.meta.dirname, "../../../tests/fixtures/replay");

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

test("splitRequest matches the shared request fixture", () => {
  const payload = JSON.parse(readFileSync(resolve(fixtureDir, "request-payload.json"), "utf8"));
  const expected = JSON.parse(readFileSync(resolve(fixtureDir, "request-split.json"), "utf8"));
  const parts = splitRequest(payload);
  assert.equal(parts.system, expected.system);
  assert.equal(parts.skill, expected.skill);
  assert.equal(parts.tools, expected.tools);
  assert.equal(parts.packet, expected.packet);
  assert.deepEqual(parts.messages, expected.messages);
  for (const key of ["system", "skill", "tools", "packet"] as const) {
    assert.equal(createHash("sha256").update(parts[key]).digest("hex"), expected.sha256[key]);
  }
});

test("splitRequest returns empty parts when the payload is not an OpenAI chat body", () => {
  assert.deepEqual(splitRequest(null), { system: "", skill: "", tools: "", packet: "", messages: [] });
  assert.deepEqual(splitRequest({ messages: [{ role: "user", content: "only" }] }), {
    system: "", skill: "", tools: "", packet: "only", messages: [{ role: "user", content: "only" }],
  });
});

test("stampRecord adds the turn and request id without overriding existing keys", () => {
  assert.deepEqual(stampRecord({ kind: "settle" }, 0), { kind: "settle", turn: 0 });
  assert.deepEqual(stampRecord({ kind: "request", id: "r" }, 2, "r"),
    { kind: "request", id: "r", turn: 2, request_id: "r" });
  assert.deepEqual(stampRecord({ turn: 4, request_id: "kept" }, 9, "other"), { turn: 4, request_id: "kept" });
});

test("BlobStore.put returns the sha256 and does not rewrite an existing blob", () => {
  const directory = mkdtempSync(resolve(tmpdir(), "arena-blobs-"));
  try {
    const store = new BlobStore(directory);
    const hash = store.put("same text");
    assert.equal(hash, createHash("sha256").update("same text").digest("hex"));
    assert.equal(store.put("same text"), hash);
    const target = resolve(directory, hash);
    writeFileSync(target, "corrupted");
    assert.equal(store.put("same text"), hash);
    assert.equal(readFileSync(target, "utf8"), "corrupted");
  } finally {
    rmSync(directory, { recursive: true, force: true });
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
