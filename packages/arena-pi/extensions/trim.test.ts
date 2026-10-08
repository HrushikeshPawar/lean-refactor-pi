import assert from "node:assert/strict";
import test from "node:test";
import { compactDiagnostics, ResultTrimmer } from "./trim.ts";

const skill = "# Proof golfing\n".repeat(40);

test("a repeated read of the same skill file becomes a stub, a changed one does not", () => {
  const trimmer = new ResultTrimmer();
  assert.equal(trimmer.trim("arena_skill_read", { path: "SKILL.md" }, skill), skill);
  const again = trimmer.trim("arena_skill_read", { path: "SKILL.md" }, skill);
  assert.match(again, /already loaded earlier in this run; unchanged/);
  assert.ok(again.length < skill.length);
  assert.equal(trimmer.trim("arena_skill_read", { path: "SKILL.md" }, skill + "edit"), skill + "edit");
  assert.equal(trimmer.trim("arena_skill_read", { path: "other.md" }, skill), skill);
});

test("a compaction makes the earlier text unavailable, so the next read is full again", () => {
  const trimmer = new ResultTrimmer();
  trimmer.trim("arena_source", { handle: "h" }, skill);
  trimmer.forget();
  assert.equal(trimmer.trim("arena_source", { handle: "h" }, skill), skill);
});

test("proof-bearing and goal results are never stubbed", () => {
  const trimmer = new ResultTrimmer();
  trimmer.trim("arena_probe", { proof: "x" }, skill);
  assert.equal(trimmer.trim("arena_probe", { proof: "x" }, skill), skill);
  trimmer.trim("mcp__arena_lean__lean_goal", { line: 3 }, skill);
  assert.equal(trimmer.trim("mcp__arena_lean__lean_goal", { line: 3 }, skill), skill);
});

const longError = "unsolved goals\n" + "h : x = y\n".repeat(30) + "⊢ False";

test("Lean diagnostics: compact JSON, repeated messages pointed back, errors kept in full", () => {
  const raw = JSON.stringify({ items: [
    { snippet: "a", diagnostics: [{ severity: "error", message: longError, line: 9, column: 2, lean_tags: null, category: "diagnostic", hint: null }] },
    { snippet: "b", diagnostics: [{ severity: "error", message: longError, line: 9, column: 2, lean_tags: null, category: "diagnostic", hint: null },
      { severity: "error", message: "unknown identifier 'foo'", line: 11, column: 4 }] },
  ] }, null, 2);
  const out = compactDiagnostics(raw);
  const parsed = JSON.parse(out);
  assert.ok(out.length < raw.length);
  assert.equal(parsed.items[0].diagnostics[0].message, longError);
  assert.equal(parsed.items[1].diagnostics[0].message, "same message as the error at 9:2");
  assert.equal(parsed.items[1].diagnostics[1].message, "unknown identifier 'foo'");
  assert.ok(!("hint" in parsed.items[0].diagnostics[0]));
});

test("only long non-error messages are cut", () => {
  const long = "linter says ".repeat(120);
  const out = JSON.parse(compactDiagnostics(JSON.stringify({ diagnostics: [
    { severity: "warning", message: long, line: 1, column: 1 }, { severity: "error", message: long, line: 2, column: 1 }] }, null, 1)));
  assert.match(out.diagnostics[0].message, /more characters of this warning omitted/);
  assert.equal(out.diagnostics[1].message, long);
});

test("text that is not JSON is untouched", () => {
  assert.equal(compactDiagnostics("plain goal text"), "plain goal text");
});
