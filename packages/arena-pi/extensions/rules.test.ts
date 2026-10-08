import assert from "node:assert/strict";
import { mkdtemp, mkdir, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { axisHeadroom, continuationPush, finishPush, routesText, leanPathViolation, trimProfile, planEvaluate, planProbe, resolveInlineIdea, sinceRefusal, staleNotice } from "./rules.ts";

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

test("a refused finish lists routes tried, headroom and demands a structurally new idea", () => {
  const push = finishPush(base);
  for (const text of ["60% of the $0.1 allowance", "no value", "10% or less", "i1", "5 attempts", "best proxy 67.2",
    "tokens saved 16%", "heartbeats saved 92%", "structurally NEW idea",
    "before calling arena_finish again"]) {
    assert.ok(push.message.includes(text), `missing: ${text}`);
  }
  assert.ok(!push.message.includes("without probing any new idea"));
  assert.ok(finishPush({ ...base, refusals: 1, newIdeaProbed: false }).message.includes("without probing any new idea"));
  assert.ok(!finishPush({ ...base, refusals: 1, newIdeaProbed: true }).message.includes("without probing any new idea"));
});

test("the plain-answer continuation pushes a new structural route", () => {
  const text = continuationPush({ status: "[arena] best verified: #6", ideas: ["i2 token-golf"], remainingUsd: 0.06, capUsd: 0.1 });
  for (const part of ["Do not stop", "no value", "opens a credited route", "sorry holes", "i2 token-golf"]) assert.ok(text.includes(part), part);
});

test("the model-facing profile keeps the top twelve entries and lines plus totals", () => {
  const entries = Array.from({ length: 30 }, (_, i) => ({ lines: String(i), hb: i }));
  const lines = Array.from({ length: 30 }, (_, i) => ({ proof_line: i + 1, self_hb: (i * 7) % 30 }));
  const trimmed = trimProfile({ ok: true, profiled_total: 99, entries, omitted_entries: 2, line_profile: lines });
  assert.equal(trimmed.entries.length, 12);
  assert.equal(trimmed.line_profile.length, 12);
  assert.equal(trimmed.profiled_total, 99);
  assert.equal(trimmed.omitted_entries, 20);
  assert.ok(Math.min(...trimmed.entries.map((e: any) => e.hb)) >= 18);
  assert.ok(trimmed.trimmed_for_model);
  const small = { ok: true, entries: entries.slice(0, 3), line_profile: [] };
  assert.deepEqual(trimProfile(small), { ...small, omitted_entries: 0 });
});

const routes = [
  { route: "r1", label: "induction: InitStatesSomeMonotone", original: true, attempts: 4, best_proxy: 69.1, best_candidate: "#7" },
  { route: "r2", label: "no induction: updatedStatesComm", attempts: 0, best_proxy: null },
];

test("routes come from the harness fingerprint, not from idea titles", () => {
  assert.equal(routesText(routes), 'r1 "induction: InitStatesSomeMonotone" [the original proof\'s route]: 4 attempts, best proxy 69.1 (#7)');
  assert.equal(routesText([]), "none");
  const push = finishPush({ ...base, ideas: [{ id: "i9", title: "brand new idea", status: "active", attempts: 3 }], routes, refusals: 0, newIdeaProbed: true });
  assert.ok(push.message.includes("Routes tried: r1"));
  assert.ok(push.message.includes("Only one route has been tried so far"));
  assert.ok(!push.message.includes("brand new idea"));
  assert.equal(push.tried.length, 1);
});

test("a repeat finish without a compiled proof on a new route is called out", () => {
  const repeat = finishPush({ ...base, routes, refusals: 1, newIdeaProbed: true, newRouteProbed: false });
  assert.ok(repeat.message.includes("renaming or re-labelling an idea does not count"));
  const fresh = finishPush({ ...base, routes, refusals: 1, newIdeaProbed: false, newRouteProbed: true });
  assert.ok(!fresh.message.includes("renaming or re-labelling"));
});

test("the continuation push lists the routes tried", () => {
  const text = continuationPush({ status: "[arena] best", ideas: [], remainingUsd: 0.5, capUsd: 1, routes });
  assert.ok(text.includes("Routes tried (harness fingerprint): r1"));
});

const deep = [
  { route: "r1", label: "original", original: true, attempts: 1, best_proxy: 33.5, best_candidate: "#2", depth: 0, new_states: 0, min_holes: null, explored: true, credited: false },
  { route: "r2", label: "recursion: none", attempts: 34, best_proxy: 86.07, best_candidate: "#34", depth: 7, new_states: 7, min_holes: 0, stale_streak: 2, explored: true, credited: true },
  { route: "r3", label: "other", attempts: 1, best_proxy: null, depth: 1, new_states: 1, min_holes: 2, explored: false, credited: true },
];

test("the per-route line shows attempts, distinct goal states, min holes, explored or opened and best proxy", () => {
  const text = routesText(deep);
  assert.ok(text.includes('r2 "recursion: none": 34 attempts, 7 distinct goal states, min holes 0, explored, best proxy 86.07 (#34)'), text);
  assert.ok(text.includes('r3 "other": 1 attempt, 1 distinct goal state, min holes 2, opened, no scored proof'), text);
});

test("since the last refusal: attempts, goal states new to their route and credited routes opened are measured from route stats", () => {
  const before = { r1: { attempts: 1, new_states: 0 }, r2: { attempts: 30, new_states: 7 } };
  assert.deepEqual(sinceRefusal(deep, before, new Set(["r2"])), { attempts: 5, newStates: 1, creditedOpened: 1 });
  assert.deepEqual(sinceRefusal(deep, { r1: { attempts: 1, new_states: 0 }, r2: { attempts: 34, new_states: 7 }, r3: { attempts: 1, new_states: 1 } }, new Set(["r2", "r3"])),
    { attempts: 0, newStates: 0, creditedOpened: 0 });
});

test("a repeat refusal states the measured fact when nothing new was reached, and says nothing when something was", () => {
  const stalled = finishPush({ ...base, routes: deep, refusals: 1, newIdeaProbed: true, sinceRefusal: { attempts: 4, newStates: 0, creditedOpened: 0 } });
  assert.ok(stalled.message.includes("4 attempts since the last refusal produced no goal state new to their route"), stalled.message);
  assert.ok(stalled.message.includes("edits that leave the same goals do not count"));
  assert.ok(stalled.message.includes("7 distinct goal states"));
  assert.ok(!stalled.message.includes("structurally NEW idea"));
  const single = finishPush({ ...base, routes: deep, refusals: 1, newIdeaProbed: true, sinceRefusal: { attempts: 1, newStates: 0, creditedOpened: 0 } });
  assert.ok(single.message.includes("1 attempt since the last refusal produced no goal state new to its route"));
  assert.ok(finishPush({ ...base, routes: deep, refusals: 1, newIdeaProbed: false, sinceRefusal: { attempts: 0, newStates: 0, creditedOpened: 0 } })
    .message.includes("No attempt was made since the last refusal"));
  for (const progress of [{ attempts: 1, newStates: 1, creditedOpened: 0 }, { attempts: 1, newStates: 0, creditedOpened: 1 }]) {
    const moved = finishPush({ ...base, routes: deep, refusals: 1, newIdeaProbed: false, sinceRefusal: progress });
    assert.ok(!moved.message.includes("do not count") && !moved.message.includes("No attempt was made"), moved.message);
  }
  // The first refusal never carries the repeat sentence.
  assert.ok(!finishPush({ ...base, routes: deep, refusals: 0, newIdeaProbed: false, sinceRefusal: { attempts: 0, newStates: 0, creditedOpened: 0 } }).message.includes("since the last refusal"));
});

test("a stale notice is one factual line, once per streak", () => {
  const noticed = new Set<string>();
  const row = (stale_streak: number) => [{ route: "r2", stale_streak, stale: stale_streak >= 5 }];
  assert.equal(staleNotice(row(4), noticed), undefined);
  assert.equal(staleNotice(row(5), noticed), "[arena] r2: the last 5 attempts left goal states already seen on this route.");
  assert.equal(staleNotice(row(6), noticed), undefined);
  assert.equal(staleNotice(row(9), noticed), undefined);
  assert.equal(staleNotice(row(0), noticed), undefined);  // a new goal state breaks the streak
  assert.equal(staleNotice(row(5), noticed), "[arena] r2: the last 5 attempts left goal states already seen on this route.");
});
