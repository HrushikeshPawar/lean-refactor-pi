import assert from "node:assert/strict";
import test from "node:test";
import { RawArguments, repairMalformedToolArguments } from "./rawargs.ts";

function message(args: unknown) {
  return { role: "assistant", content: [{ type: "toolCall", id: "c1", name: "compile", arguments: args }] } as never;
}

test("pi's non-empty parse is kept even when the re-assembled stream text is not valid JSON", () => {
  const raw = new RawArguments();
  raw.start(0, "");
  raw.delta(0, '{"drafts": ["by simp"]}{"drafts": ["by simp"]}'); // a duplicated stream, as v7-sol-ski1 saw
  assert.equal(repairMalformedToolArguments(message({ drafts: ["by simp"] }), raw), undefined);
});

test("a failed parse ({}) with invalid stream text becomes null so the call fails validation", () => {
  const raw = new RawArguments();
  raw.start(0, "");
  raw.delta(0, '{"drafts": ["by simp"');
  const repaired = repairMalformedToolArguments(message({}), raw) as unknown as { content: Array<{ arguments: unknown }> };
  assert.equal(repaired.content[0].arguments, null);
});

test("an argument-free call with valid {} stream text is left alone", () => {
  const raw = new RawArguments();
  raw.start(0, "");
  raw.delta(0, "{}");
  assert.equal(repairMalformedToolArguments(message({}), raw), undefined);
});
