import assert from "node:assert/strict";
import test from "node:test";
import { boundedPayload, budgetDecision, budgetLimits, maximumNextRequest, permitFinalPayload, sessionSpend, usageCost } from "./budget.ts";

const usage = { input: 1_000_000, output: 100_000, cacheRead: 0, cacheWrite: 0 };

test("prices OpenCode Go usage at the expensive tier", () => {
  assert.equal(usageCost(usage, "gpt-6-luna"), 0.275);
  assert.equal(usageCost(usage, "deepseek-v4.1-flash"), 0.42);
});

test("counts all persisted paid usage, including abandoned branches and compaction", () => {
  const entries = [
    { type: "message", message: { role: "assistant", provider: "opencode-go",
      model: "gpt-6-luna", usage } },
    { type: "usage", provider: "opencode-go", model: "gpt-6-luna", usage },
    { type: "compaction", usage },
    { type: "message", message: { role: "toolResult", usage } },
  ];
  assert.equal(sessionSpend(entries as never, "gpt-6-luna"), 1.1);
});

test("reserves the full next model response before the hard cap", () => {
  assert.ok(Math.abs(maximumNextRequest("gpt-6-luna") - 0.3585) < 1e-10);
  assert.ok(Math.abs(maximumNextRequest("deepseek-v4.1-flash") - 0.7608) < 1e-10);
  const limits = budgetLimits({ ARENA_HARD_CAP_USD: "3", ARENA_STOP_USD: "2.5" });
  assert.equal(budgetDecision(2.5, "gpt-6-luna", limits).allowed, false);
  assert.equal(budgetDecision(2.4, "deepseek-v4.1-flash", limits).allowed, false);
  assert.equal(budgetDecision(2, "deepseek-v4.1-flash", limits).allowed, true);
});

test("a $1 cap is enforced before the next request", () => {
  const limits = budgetLimits({ ARENA_HARD_CAP_USD: "1" });
  assert.equal(limits.stopUsd, 0.85);
  assert.equal(budgetDecision(0.60, "gpt-6-luna", limits).allowed, true);
  assert.equal(budgetDecision(0.65, "gpt-6-luna", limits).allowed, false);
  assert.throws(() => budgetLimits({ ARENA_HARD_CAP_USD: "3.01" }));
  assert.throws(() => budgetLimits({ ARENA_HARD_CAP_USD: "1", ARENA_STOP_USD: "1.01" }));
});

test("fails closed on unpriced models or invalid usage", () => {
  assert.throws(() => sessionSpend([{ type: "message", message: { role: "assistant",
    provider: "other", model: "gpt-6-luna", usage } }] as never, "gpt-6-luna"));
  assert.throws(() => usageCost({ ...usage, output: Number.NaN }, "gpt-6-luna"));
  assert.throws(() => sessionSpend([{ type: "message", message: { role: "assistant",
    provider: "opencode-go", model: "gpt-6-luna", stopReason: "error",
    usage: { ...usage, totalTokens: 0 } } }] as never, "gpt-6-luna"));
});

test("a bounded final payload permits a ten-cent experiment", () => {
  const { payload, reserve } = boundedPayload({ input: "reference proof", max_output_tokens: 128_000 }, "gpt-6-luna");
  assert.equal(payload.max_output_tokens, 16_000);
  assert.ok(reserve < 0.1);
  assert.throws(() => boundedPayload({ input: "x" }, "gpt-6-luna"));
  assert.throws(() => budgetLimits({ ARENA_HARD_CAP_USD: "0.09" }));
});

test("large serialized text fits the model when its byte token upper bound fits", () => {
  const payload = { max_output_tokens: 16000, input: "x".repeat(600_000) };
  assert.ok(boundedPayload(payload, "gpt-6-luna").reserve > 0);
});

test("final transport guard denies a request that would exceed each cap", () => {
  const payload = { max_output_tokens: 16000, input: "proof" };
  for (const hardCap of [0.1, 1, 3]) {
    const limits = budgetLimits({ ARENA_HARD_CAP_USD: String(hardCap) });
    const reserve = boundedPayload(payload, "gpt-6-luna").reserve;
    assert.doesNotThrow(() => permitFinalPayload(payload, "gpt-6-luna",
      { spent: 0, charged: hardCap - reserve - 0.001 }, limits));
    assert.throws(() => permitFinalPayload(payload, "gpt-6-luna",
      { spent: 0, charged: hardCap - reserve + 0.001 }, limits), /Arena budget stop/);
  }
});
