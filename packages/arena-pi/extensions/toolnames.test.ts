import assert from "node:assert/strict";
import test from "node:test";
import { nearestToolName, normalizeToolArguments } from "./toolnames.ts";

const registered = ["read", "bash", "arena_candidate", "arena_declarations", "arena_evaluate", "arena_find", "arena_probe",
  "arena_profile", "arena_source", "arena_state", "arena_finish", "mcp__arena_lean__lean_goal",
  "mcp__arena_lean__lean_diagnostic_messages", "mcp__arena_lean__lean_hover_info"];

test("suggests the nearest registered tool across prefix mistakes", () => {
  assert.equal(nearestToolName("probe", registered), "arena_probe");
  assert.equal(nearestToolName("arenaprobe", registered), "arena_probe");
  assert.equal(nearestToolName("arena_declaraton", registered), "arena_declarations");
  assert.equal(nearestToolName("lean_goal", registered), "mcp__arena_lean__lean_goal");
  assert.equal(nearestToolName("mcp__arena_lean__goal", registered), "mcp__arena_lean__lean_goal");
  assert.equal(nearestToolName("mcp__arena_lean__lean_declaration", registered), "arena_declarations");
  assert.equal(nearestToolName("arena_finnish", registered), "arena_finish");
  assert.equal(nearestToolName("arena_stat", registered), "arena_state");
});

test("suggests nothing for unrelated names and is order independent", () => {
  assert.equal(nearestToolName("completely_different_thing", registered), undefined);
  assert.equal(nearestToolName("arena_evalute", registered), nearestToolName("arena_evalute", [...registered].reverse()));
  assert.equal(nearestToolName("probe", []), undefined);
});

test("treats empty optional fields as absent and parses arrays sent as text", () => {
  const schema = { properties: { proof: { type: "string" }, drafts: { type: "array" }, items: { type: "array" },
    cursor: { type: "string" }, first: { type: "number" } } };
  assert.deepEqual(normalizeToolArguments({ proof: "", drafts: ["by rfl"], cursor: "" }, schema), { drafts: ["by rfl"] });
  assert.deepEqual(normalizeToolArguments({ proof: "by rfl", drafts: [""] }, schema), { proof: "by rfl" });
  assert.deepEqual(normalizeToolArguments({ drafts: "[\"by\\n  simp\", \"by rfl\"]" }, schema), { drafts: ["by\n  simp", "by rfl"] });
  assert.deepEqual(normalizeToolArguments({ items: "['Core.a', \"Core.b'\"]" }, schema), { items: ["Core.a", "Core.b'"] });
  assert.deepEqual(normalizeToolArguments({ items: "Core.a" }, schema), { items: ["Core.a"] });
  assert.deepEqual(normalizeToolArguments({ items: ["['Core.a', 'Core.b']"] }, schema), { items: ["Core.a", "Core.b"] });
  assert.deepEqual(normalizeToolArguments({ first: 0, proof: "  " }, schema), { first: 0 });
});

test("an unknown argument key maps to the schema field it stands for, never over a given field", () => {
  const probe = { properties: { proof: { type: "string" }, drafts: { type: "array" }, label: { type: "string" } } };
  assert.deepEqual(normalizeToolArguments({ draft: "by simp" }, probe), { drafts: ["by simp"] });
  assert.deepEqual(normalizeToolArguments({ code: "by rfl" }, probe), { proof: "by rfl" });
  assert.deepEqual(normalizeToolArguments({ proof: "by rfl", code: "by simp" }, probe), { proof: "by rfl", code: "by simp" });
  const idea = { properties: { title: { type: "string" }, status: { type: "string" } } };
  assert.deepEqual(normalizeToolArguments({ idea: "equational route" }, idea), { title: "equational route" });
  assert.deepEqual(normalizeToolArguments({ project: "x" }, idea), { project: "x" });
});
