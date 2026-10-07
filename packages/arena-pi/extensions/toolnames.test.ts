import assert from "node:assert/strict";
import test from "node:test";
import { nearestToolName } from "./toolnames.ts";

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
