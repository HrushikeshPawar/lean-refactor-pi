import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { continuationPush, finishPush, leanPathViolation, planEvaluate, planProbe, routesText, staleNotice, trimProfile } from "./rules.ts";
import { spendFooter } from "./spend.ts";
import { compactDiagnostics, ResultTrimmer } from "./trim.ts";

const routes = [{ route: "r2", attempts: 5, stale: true, stale_streak: 5, best_proxy: 69.1, best_candidate: "#7" }];
const metrics = { tokens: 224, heartbeats: 4251 };
const best = { candidate: "#6", tokens: 188, heartbeats: 339, proxy: 69.37 };
const finishInput = { usedPct: 40, remainingUsd: 0.06, capUsd: 0.1, baseline: metrics, best,
  top: [{ candidate: "#5", tokens: 190, heartbeats: 400 }], ideas: [], refusals: 0, newIdeaProbed: false };

async function outputs() {
  const trimmer = new ResultTrimmer();
  const source = "# Proof information\n".repeat(20);
  trimmer.trim("arena_skill_read", { path: "SKILL.md" }, source);
  const stub = trimmer.trim("arena_skill_read", { path: "SKILL.md" }, source);
  const warning = "a".repeat(610);
  const diagnostics = JSON.stringify({ items: [
    { diagnostics: [{ severity: "warning", message: warning, line: 2, column: 1 }] },
    { diagnostics: [{ severity: "warning", message: warning, line: 3, column: 1 }] },
  ] }, null, 2);
  const profile = trimProfile({ ok: true, entries: [{ hb: 10 }, { hb: 20 }], line_profile: [], profiled_total: 30 }, 1);
  return {
    finishPush: finishPush(finishInput).message,
    continuationPush: continuationPush({ ...finishInput, routes }),
    routesText: routesText(routes),
    staleNotice: staleNotice(routes, new Set()),
    planEvaluateCandidateNote: planEvaluate({ proof: "x", candidate: "#2" }),
    planEvaluateExplicitParentsNote: planEvaluate({ proof: "x", candidate: "#2", parents: ["#1"] }),
    planProbePlaceholderNote: planProbe({ proof: "x", drafts: ["sorry"] }),
    planProbeBatchNote: planProbe({ proof: "x", drafts: ["by rfl"] }),
    planProbeLimit: planProbe({ proof: "x", drafts: ["a", "b", "c", "d"] }),
    leanPathViolation: await leanPathViolation({ path: "../secret.lean" }, "/tmp/arena-text-golden"),
    trimProfile: profile.trimmed_for_model,
    spendFooter: spendFooter(0.125, 0.5),
    resultTrimmerStub: stub,
    compactDiagnostics: compactDiagnostics(diagnostics),
  };
}

test("agent messages and pure helper outputs match the captured pre-move bytes", async () => {
  const cases = JSON.parse(await readFile(fileURLToPath(new URL("./agent-text-golden.json", import.meta.url)), "utf8"));
  assert.deepEqual(await outputs(), Object.fromEntries(cases.map((item: { id: string; expected: unknown }) => [item.id, item.expected])));
});
