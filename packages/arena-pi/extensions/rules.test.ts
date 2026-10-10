import assert from "node:assert/strict";
import { mkdtemp, mkdir, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { axisHeadroom, continuationPush, finishPush, routesText, leanPathViolation, trimProfile, planEvaluate, planProbe, resolveInlineIdea, sinceRefusal, staleNotice } from "./rules.ts";

test("a proof wins over candidate or probe, which becomes the default parent", async () => {
  const candidate = await planEvaluate({ proof: "x", candidate: "#2" });
  assert.equal(candidate.ok && candidate.note, "#2 was treated as the parent of the proof, because proof was given.");
  const probe = await planEvaluate({ proof: "x", from_probe: "p3" });
  assert.ok(probe.ok && probe.parents[0] === "p3" && probe.note);
  const explicit = await planEvaluate({ proof: "x", candidate: "#2", parents: ["#1"] });
  assert.ok(explicit.ok && explicit.parents[0] === "#1" && explicit.note);
  assert.deepEqual(await planEvaluate({ proof: "x" }), { ok: true, proof: "x", parents: [] });
});

test("without a proof exactly one of candidate and from_probe is required", async () => {
  assert.equal((await planEvaluate({ candidate: "#2", from_probe: "p1" })).ok, false);
  assert.equal((await planEvaluate({ proof: "  " })).ok, false);
  assert.deepEqual(await planEvaluate({ candidate: "#2", proof: "" }), { ok: true, candidate: "#2", fromProbe: undefined, parents: [] });
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

test("probe keeps a real proof when drafts hold only placeholders, and batches real drafts with it", async () => {
  const placeholder = await planProbe({ proof: "by simp", drafts: ["sorry"] });
  assert.ok(placeholder.ok && placeholder.note);
  const combined = await planProbe({ proof: "by simp", drafts: [":= by sorry", "by omega"] });
  assert.ok(combined.ok && combined.drafts?.length === 2 && combined.note);
  assert.equal((await planProbe({ proof: "a", drafts: ["b", "c", "d", "e"] })).ok, false);
  assert.deepEqual(await planProbe({ drafts: ["by rfl"] }), { ok: true, drafts: ["by rfl"] });
  assert.equal((await planProbe({})).ok, false);
});

const base = { usedPct: 40, remainingUsd: 0.06, capUsd: 0.1,
  baseline: { tokens: 224, heartbeats: 4251 }, best: { candidate: "#6", tokens: 188, heartbeats: 339, proxy: 69.37 },
  top: [{ candidate: "#5", tokens: 190, heartbeats: 400 }],
  ideas: [{ id: "i1", title: "induction", status: "succeeded", attempts: 5, best: { proxy: 67.2 } },
          { id: "i2", title: "token-golf", status: "active", attempts: 1, best: null }],
  refusals: 0, newIdeaProbed: false };

test("headroom reports the per-axis saving against the original", () => {
  const headroom = axisHeadroom(base.baseline, base.best, base.top);
  assert.equal(headroom.tokens_saved_pct, 16);
  assert.equal(headroom.heartbeats_saved_pct, 92);
  assert.equal(headroom.tokens_vs_lowest_seen, 188);
});

test("a refused finish states spend, the 10% rule and per-axis points left, with no directions", async () => {
  const push = await finishPush(base);
  assert.ok(push.message.startsWith("Stop refused:"));
  assert.ok(push.message.includes("$0.06 (60.0%) left."));
  for (const banned of ["credited", "micro-golf", "structurally", "NEW", "must", "should", "before calling arena_finish again", "no value"]) {
    assert.ok(!push.message.includes(banned), `unexpected: ${banned}`);
  }
});

test("a repeat refusal is the same facts, and its size is capped", async () => {
  assert.equal((await finishPush({ ...base, refusals: 3, newIdeaProbed: false })).message, (await finishPush(base)).message);
  const many = Array.from({ length: 400 }, (_, i) => ({ route: `r${i}`, label: "x", attempts: 3, best_proxy: 50.5, best_candidate: `#${i}` }));
  const big = await finishPush({ ...base, routes: many });
  assert.ok(big.message.length <= 1500, String(big.message.length));
  assert.ok(big.message.startsWith("Stop refused: $0.04 of $0.1 spent"));
});

test("the plain-answer continuation states the same facts as the refusal, with no directions", async () => {
  const input = { usedPct: 40, remainingUsd: 0.06, capUsd: 0.1, baseline: base.baseline, best: base.best, top: base.top };
  const text = await continuationPush(input);
  assert.ok(text.startsWith("The turn ended with text"));
  assert.ok(text.includes("$0.06 (60.0%) left."));
  const withRoutes = await continuationPush({ ...input, routes: [{ route: "r1", label: "x", original: true, attempts: 4, best_proxy: 69.1, best_candidate: "#7" }] });
  assert.ok(withRoutes.includes("Routes tried: r1 (original's route)"));
  const banned = ["credit", "Do not stop", "no value", "opens", "must", "should", "Make a tool call", "induction", "lemma", "recursion", "sorry", "Active ideas"];
  for (const word of banned) assert.ok(!withRoutes.toLowerCase().includes(word.toLowerCase()), `unexpected: ${word}`);
  const many = Array.from({ length: 400 }, (_, i) => ({ route: `r${i}`, label: "x", attempts: 3, best_proxy: 50.5, best_candidate: `#${i}` }));
  assert.ok((await continuationPush({ ...input, routes: many })).length <= 1500);
});

test("the model-facing profile keeps the top twelve entries and lines plus totals", async () => {
  const entries = Array.from({ length: 30 }, (_, i) => ({ lines: String(i), hb: i }));
  const lines = Array.from({ length: 30 }, (_, i) => ({ proof_line: i + 1, self_hb: (i * 7) % 30 }));
  const trimmed = await trimProfile({ ok: true, profiled_total: 99, entries, omitted_entries: 2, line_profile: lines });
  assert.equal(trimmed.entries.length, 12);
  assert.equal(trimmed.line_profile.length, 12);
  assert.equal(trimmed.profiled_total, 99);
  assert.equal(trimmed.omitted_entries, 20);
  assert.ok(Math.min(...trimmed.entries.map((e: any) => e.hb)) >= 18);
  assert.ok(trimmed.trimmed_for_model);
  const small = { ok: true, entries: entries.slice(0, 3), line_profile: [] };
  assert.deepEqual(await trimProfile(small), { ...small, omitted_entries: 0 });
});

const routes = [
  { route: "r1", label: "induction: InitStatesSomeMonotone", original: true, attempts: 4, best_proxy: 69.1, best_candidate: "#7" },
  { route: "r2", label: "no induction: updatedStatesComm", attempts: 0, best_proxy: null },
];

test("routes come from the harness fingerprint, not from idea titles", async () => {
  assert.ok((await routesText(routes)).includes("r1"));
  assert.equal(await routesText([]), "none");
  const push = await finishPush({ ...base, ideas: [{ id: "i9", title: "brand new idea", status: "active", attempts: 3 }], routes, refusals: 0, newIdeaProbed: true });
  assert.ok(push.message.includes("Routes tried: r1"));
  assert.ok(!push.message.includes("brand new idea"));
  assert.ok(!push.message.includes("InitStatesSomeMonotone"));
  assert.equal(push.tried.length, 1);
});

const deep = [
  { route: "r1", label: "original", original: true, attempts: 1, best_proxy: 33.5, best_candidate: "#2", depth: 0, new_states: 0, min_holes: null, explored: true, credited: false },
  { route: "r2", label: "recursion: none", attempts: 34, best_proxy: 86.07, best_candidate: "#34", depth: 7, new_states: 7, min_holes: 0, stale_streak: 2, explored: true, credited: true },
  { route: "r3", label: "other", attempts: 1, best_proxy: null, depth: 1, new_states: 1, min_holes: 2, explored: false, credited: true },
];

test("the per-route line shows attempts, distinct goal states, min holes, explored or opened and best proxy", async () => {
  const text = await routesText(deep);
  assert.ok(text.includes("r2 (credited) \u00b7 34 attempts \u00b7 7 goal states \u00b7 best proxy 86.07 (#34)"), text);
  assert.ok(text.includes("r3 (credited) \u00b7 1 attempt \u00b7 1 goal state \u00b7 no scored proof"), text);
  assert.ok(!text.includes("recursion: none") && !text.includes("other"), text);
});

test("since the last refusal: attempts, goal states new to their route and credited routes opened are measured from route stats", () => {
  const before = { r1: { attempts: 1, new_states: 0 }, r2: { attempts: 30, new_states: 7 } };
  assert.deepEqual(sinceRefusal(deep, before, new Set(["r2"])), { attempts: 5, newStates: 1, creditedOpened: 1 });
  assert.deepEqual(sinceRefusal(deep, { r1: { attempts: 1, new_states: 0 }, r2: { attempts: 34, new_states: 7 }, r3: { attempts: 1, new_states: 1 } }, new Set(["r2", "r3"])),
    { attempts: 0, newStates: 0, creditedOpened: 0 });
});

test("a stale notice is one factual line, once per streak", async () => {
  const noticed = new Set<string>();
  const row = (stale_streak: number) => [{ route: "r2", stale_streak, stale: stale_streak >= 5 }];
  assert.equal(await staleNotice(row(4), noticed), undefined);
  assert.ok(await staleNotice(row(5), noticed));
  assert.equal(await staleNotice(row(6), noticed), undefined);
  assert.equal(await staleNotice(row(9), noticed), undefined);
  assert.equal(await staleNotice(row(0), noticed), undefined);  // a new goal state breaks the streak
  assert.ok(await staleNotice(row(5), noticed));
});


test("the left share is the unrounded remainder to one decimal, matching the gate", async () => {
  const text = await continuationPush({ usedPct: 89, remainingUsd: 0.0535, capUsd: 0.5, baseline: null, best: null });
  assert.ok(text.includes("$0.05 (10.7%) left."), text);
  assert.ok(text.includes("accepted when $0.05 (10%) or less"), text);
});
