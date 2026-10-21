import assert from "node:assert/strict";
import test from "node:test";
import { nearestToolName, normalizeToolArguments, requireToolArguments } from "./toolnames.ts";
import { render } from "./text.ts";

const registered = ["compile", "goal", "read", "search"];

test("suggests the nearest name from the five registered tools", () => {
  assert.equal(nearestToolName("compil", registered), "compile");
  assert.equal(nearestToolName("arena_compil", registered), "compile");
  assert.equal(nearestToolName("completely_different_thing", registered), undefined);
});

test("normalizes stringified arrays and the proof and draft aliases for compile", () => {
  const schema = { properties: { drafts: { type: "array" }, check: { type: "string" } } };
  assert.deepEqual(normalizeToolArguments({ draft: "by rfl", check: "" }, schema), { drafts: ["by rfl"] });
  assert.deepEqual(normalizeToolArguments({ proof: "by rfl" }, schema), { drafts: ["by rfl"] });
  assert.deepEqual(normalizeToolArguments({ drafts: "[\"by simp\", \"by rfl\"]" }, schema), { drafts: ["by simp", "by rfl"] });
  assert.deepEqual(normalizeToolArguments({ drafts: [""] }, schema), {});
  assert.deepEqual(normalizeToolArguments({ unknown: "value" }, schema), { unknown: "value" });
});

test("null and empty argument calls render the empty or malformed error with valid keys", async () => {
  const valid = "drafts, splice, fill, merge, base, from, note, check";
  const missing = await render("messages/errors.empty_arguments", { valid });
  assert.match(missing, /arrived empty or malformed/);
  assert.match(missing, /drafts, splice, fill, merge, base, from, note, check/);
  assert.throws(() => requireToolArguments(null, missing), new RegExp(missing));
  assert.deepEqual(normalizeToolArguments({}, { properties: {} }), {});
});
