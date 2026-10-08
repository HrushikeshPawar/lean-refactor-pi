import assert from "node:assert/strict";
import { mkdtemp, mkdir, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { leanPathViolation, planEvaluate, planProbe, resolveInlineIdea } from "./rules.ts";

test("a proof wins over candidate or probe, which becomes the default parent", () => {
  assert.deepEqual(planEvaluate({ proof: "theorem t", candidate: "#2" }),
    { ok: true, proof: "theorem t", parents: ["#2"], note: "#2 was treated as the parent of the proof, because proof was given." });
  const probe = planEvaluate({ proof: "x", from_probe: "p3" });
  assert.ok(probe.ok && probe.parents[0] === "p3" && probe.note);
  const explicit = planEvaluate({ proof: "x", candidate: "#2", parents: ["#1"] });
  assert.ok(explicit.ok && explicit.parents[0] === "#1" && explicit.note);
  assert.deepEqual(planEvaluate({ proof: "x" }), { ok: true, proof: "x", parents: [] });
});

test("without a proof exactly one of candidate and from_probe is required", () => {
  assert.equal(planEvaluate({ candidate: "#2", from_probe: "p1" }).ok, false);
  assert.equal(planEvaluate({ proof: "  " }).ok, false);
  assert.deepEqual(planEvaluate({ candidate: "#2", proof: "" }), { ok: true, candidate: "#2", fromProbe: undefined, parents: [] });
});

test("Lean file paths are confined to the run project", async () => {
  const base = await mkdtemp(join(tmpdir(), "arena-rules-"));
  const project = join(base, "project");
  await mkdir(join(project, "Strata"), { recursive: true });
  await writeFile(join(base, "secret.lean"), "x");
  await symlink(base, join(project, "escape"));
  assert.equal(await leanPathViolation({ file_path: "Strata/Target.lean" }, project), undefined);
  assert.equal(await leanPathViolation({ file_path: join(project, "Strata/Target.lean") }, project), undefined);
  assert.equal(await leanPathViolation({}, project), undefined);
  assert.match(String(await leanPathViolation({ file_path: join(base, "secret.lean") }, project)), /outside/);
  assert.match(String(await leanPathViolation({ file_path: "../secret.lean" }, project)), /outside/);
  assert.match(String(await leanPathViolation({ path: "escape/secret.lean" }, project)), /outside/);
});

test("an inline idea title creates the idea once and yields its id", async () => {
  const titles: string[] = [];
  const create = async (title: string) => { titles.push(title); return { ok: true, id: "i1" }; };
  assert.deepEqual(await resolveInlineIdea({ idea: " try omega " }, create), { ok: true, idea_id: "i1", created: true });
  assert.deepEqual(titles, ["try omega"]);
  assert.deepEqual(await resolveInlineIdea({ idea: "x", idea_id: "i0" }, create), { ok: true, idea_id: "i0" });
  assert.deepEqual(await resolveInlineIdea({ idea: "" }, create), { ok: true });
  assert.deepEqual(titles, ["try omega"]);
  const failed = await resolveInlineIdea({ idea: "x" }, async () => ({ ok: false, error: "bad" }));
  assert.deepEqual(failed, { ok: false, error: { ok: false, error: "bad" } });
});

test("probe keeps a real proof when drafts hold only placeholders, and batches real drafts with it", () => {
  assert.deepEqual(planProbe({ proof: "by simp", drafts: ["sorry"] }),
    { ok: true, proof: "by simp", note: "Placeholder drafts were ignored because proof was given." });
  assert.deepEqual(planProbe({ proof: "by simp", drafts: [":= by sorry", "by omega"] }),
    { ok: true, drafts: ["by simp", "by omega"], note: "proof was probed as draft 1 together with drafts." });
  assert.equal(planProbe({ proof: "a", drafts: ["b", "c", "d", "e"] }).ok, false);
  assert.deepEqual(planProbe({ drafts: ["by rfl"] }), { ok: true, drafts: ["by rfl"] });
  assert.equal(planProbe({}).ok, false);
});
