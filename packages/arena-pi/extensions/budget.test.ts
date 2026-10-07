import assert from "node:assert/strict";
import test from "node:test";
import { boundedPayload, budgetDecision, catalogPriceProblem, cacheAlarm, MIN_REQUEST_OUTPUT_TOKENS, outputBudget, budgetLimits, cacheUtilization, maximumNextRequest, permitFinalPayload, sessionEmbeddedCost, sessionSpend, usageCost, usageCostParts } from "./budget.ts";

const usage = { input: 1_000_000, output: 100_000, cacheRead: 0, cacheWrite: 0 };

test("prices OpenCode Go usage at the expensive tier", () => {
  assert.equal(usageCost(usage, "gpt-6-luna"), 0.275);
  assert.equal(usageCost(usage, "deepseek-v4.1-flash"), 0.21);
  assert.equal(usageCost({ input: 1_000_000, output: 0, cacheRead: 0, cacheWrite: 0 }, "qwen3.8-flash"), 0.15);
});

test("uses Luna's low tier until one request crosses 272K prompt tokens", () => {
  const low = { input: 264, output: 71807, cacheRead: 5780683, cacheWrite: 129347 };
  assert.equal(usageCost({ input: 0, output: 1000, cacheRead: 200_000, cacheWrite: 0 }, "gpt-6-luna"), 0.0025);
  assert.ok(Math.abs(usageCost({ input: 0, output: 1000, cacheRead: 273_000, cacheWrite: 0 }, "gpt-6-luna") - 0.00621) < 1e-12);
  assert.ok(Math.abs((low.input * 0.1 + low.output * 0.5 + low.cacheRead * 0.01
    + low.cacheWrite * 0.125) / 1_000_000 - 0.109905105) < 1e-10);
  const entries = [200_000, 273_000].map(cacheRead => ({ type: "message",
    message: { role: "assistant", provider: "opencode-go", model: "gpt-6-luna",
      usage: { input: 0, output: 1000, cacheRead, cacheWrite: 0, totalTokens: cacheRead + 1000 } } }));
  assert.ok(Math.abs(sessionSpend(entries as never, "gpt-6-luna") - 0.00871) < 1e-12);
});

test("keeps Pi's embedded estimate separate from conservative ledger pricing", () => {
  const entries = [{ type: "message", message: { role: "assistant", provider: "opencode-go",
    model: "gpt-6-luna", usage: { ...usage, totalTokens: 1_100_000,
      cost: { total: 0.15 } } } }];
  assert.equal(sessionSpend(entries as never, "gpt-6-luna"), 0.275);
  assert.deepEqual(sessionEmbeddedCost(entries as never),
    { usd: 0.15, priced_entries: 1, missing_entries: 0 });
  assert.deepEqual(usageCostParts(usage, "gpt-6-luna"),
    { input: 0.2, output: 0.075, cacheRead: 0, cacheWrite: 0 });
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

test("reports measured cache reuse, including a recent window", () => {
  const entries = [
    { type: "message", message: { role: "assistant", provider: "opencode-go", model: "gpt-6-luna",
      usage: { input: 0, output: 1, cacheRead: 0, cacheWrite: 100, totalTokens: 101 } } },
    { type: "message", message: { role: "assistant", provider: "opencode-go", model: "gpt-6-luna",
      usage: { input: 0, output: 1, cacheRead: 990, cacheWrite: 10, totalTokens: 1001 } } },
  ];
  const result = cacheUtilization(entries as never, "gpt-6-luna");
  assert.equal(result.all.read_tokens, 990);
  assert.equal(result.all.write_tokens, 110);
  assert.equal(result.all.reuse_pct, 90);
});

test("records a next-request exposure estimate without using it as a stop", () => {
  assert.ok(Math.abs(maximumNextRequest("gpt-6-luna") - 0.3585) < 1e-10);
  assert.ok(Math.abs(maximumNextRequest("deepseek-v4.1-flash") - 0.3804) < 1e-10);
  const limits = budgetLimits({ ARENA_HARD_CAP_USD: "3" });
  assert.equal(budgetDecision(2.5, "gpt-6-luna", limits).allowed, true);
  assert.equal(budgetDecision(3, "gpt-6-luna", limits).allowed, false);
  assert.equal(budgetDecision(2.4, "deepseek-v4.1-flash", limits).allowed, true);
  assert.equal(budgetDecision(2, "deepseek-v4.1-flash", limits).allowed, true);
});

test("a $1 cap stops after observed usage reaches $1", () => {
  const limits = budgetLimits({ ARENA_HARD_CAP_USD: "1" });
  assert.equal(limits.stopUsd, 1);
  assert.equal(budgetDecision(0.60, "gpt-6-luna", limits).allowed, true);
  assert.equal(budgetDecision(0.99, "gpt-6-luna", limits).allowed, true);
  assert.equal(budgetDecision(1, "gpt-6-luna", limits).allowed, false);
  assert.throws(() => budgetLimits({ ARENA_HARD_CAP_USD: "3.01" }));
  assert.throws(() => budgetLimits({ ARENA_HARD_CAP_USD: "1", ARENA_STOP_USD: "0.85" }));
});

test("fails closed on unpriced models or invalid usage", () => {
  assert.throws(() => sessionSpend([{ type: "message", message: { role: "assistant",
    provider: "other", model: "gpt-6-luna", usage } }] as never, "gpt-6-luna"));
  assert.throws(() => usageCost({ ...usage, output: Number.NaN }, "gpt-6-luna"));
});

test("undispatched zero-token errors do not poison exact session resume", () => {
  const entries = [
    { type: "message", message: { role: "assistant", provider: "arena-guard",
      model: "gpt-6-luna", stopReason: "error", usage: { input: 0, output: 0,
        cacheRead: 0, cacheWrite: 0, totalTokens: 0 } } },
    { type: "message", message: { role: "assistant", provider: "opencode-go",
      model: "gpt-6-luna", stopReason: "stop", usage } },
  ];
  assert.equal(sessionSpend(entries as never, "gpt-6-luna"), 0.275);
});

test("a bounded final payload permits a ten-cent experiment", () => {
  const { payload, reserve } = boundedPayload({ input: "reference proof", max_output_tokens: 128_000 }, "gpt-6-luna");
  assert.equal(payload.max_output_tokens, 16_000);
  assert.ok(reserve < 0.1);
  assert.throws(() => boundedPayload({ input: "x" }, "gpt-6-luna"));
  assert.throws(() => budgetLimits({ ARENA_HARD_CAP_USD: "0.09" }));
});

test("caps Qwen's Anthropic Messages payload before dispatch", () => {
  const { payload, reserve } = boundedPayload({ messages: [{ role: "user", content: "proof" }],
    max_tokens: 131_072 }, "qwen3.8-flash");
  assert.equal(payload.max_tokens, 16_000);
  assert.ok(reserve < 0.1);
});

test("keeps an Anthropic thinking budget below the bounded max_tokens", () => {
  // Pi sends high thinking as budget_tokens 16384 with max_tokens 32384; the API rejects
  // budget_tokens >= max_tokens with a 400, so cutting max_tokens must shrink the budget too.
  const high = boundedPayload({ messages: [], max_tokens: 32_384,
    thinking: { type: "enabled", budget_tokens: 16_384 } }, "qwen3.8-flash").payload as any;
  assert.equal(high.max_tokens, 16_000);
  assert.equal(high.thinking.budget_tokens, 14_976);
  const medium = boundedPayload({ messages: [], max_tokens: 24_192,
    thinking: { type: "enabled", budget_tokens: 8_192 } }, "qwen3.8-flash").payload as any;
  assert.equal(medium.thinking.budget_tokens, 8_192);
  // Near the cap the output allowance can fall below the 1024-token thinking minimum.
  const last = boundedPayload({ messages: [], max_tokens: 24_192,
    thinking: { type: "enabled", budget_tokens: 8_192 } }, "qwen3.8-flash", 0.0002).payload as any;
  assert.ok(last.max_tokens < 2048);
  assert.equal(last.thinking, undefined);
});

test("large serialized text fits the model when its byte token upper bound fits", () => {
  const payload = { max_output_tokens: 16000, input: "x".repeat(600_000) };
  assert.ok(boundedPayload(payload, "gpt-6-luna").reserve > 0);
});

test("final transport guard admits requests until observed usage reaches each cap", () => {
  const payload = { max_output_tokens: 16000, input: "proof" };
  for (const hardCap of [0.1, 1, 3]) {
    const limits = budgetLimits({ ARENA_HARD_CAP_USD: String(hardCap) });
    assert.doesNotThrow(() => permitFinalPayload(payload, "gpt-6-luna",
      { spent: hardCap - 0.001 }, limits));
    assert.throws(() => permitFinalPayload(payload, "gpt-6-luna",
      { spent: hardCap }, limits), /Arena budget stop/);
  }
});

test("the last allowed request is bounded by what remains of the cap", () => {
  const payload = { model: "x", input: [], max_output_tokens: 128_000 };
  const luna = (remaining: number) => (permitFinalPayload(payload, "gpt-6-luna",
    { spent: 0.1 - remaining }, { hardCapUsd: 0.1, stopUsd: 0.1 }).payload as { max_output_tokens: number }).max_output_tokens;
  assert.equal(luna(0.1), 16_000);
  assert.equal(luna(0.003), 4_000);           // $0.003 at $0.75 per million output tokens
  assert.equal(luna(0.00001), MIN_REQUEST_OUTPUT_TOKENS);
  assert.equal(outputBudget(5, "qwen3.8-flash"), 16_000);
  assert.throws(() => luna(0), /Arena budget stop/);
});

test("cache alarm fires only after warm-up, when a request writes more than it reads", () => {
  assert.equal(cacheAlarm({ cacheRead: 0, cacheWrite: 9000 }, 1), undefined);
  assert.equal(cacheAlarm({ cacheRead: 0, cacheWrite: 9000 }, 2), undefined);
  assert.deepEqual(cacheAlarm({ cacheRead: 1000, cacheWrite: 9000 }, 3), { request: 3, read: 1000, write: 9000 });
  assert.equal(cacheAlarm({ cacheRead: 9000, cacheWrite: 900 }, 7), undefined);
  assert.equal(cacheAlarm({}, 7), undefined);
});

test("refuses a ledger price that differs from Pi's catalog", () => {
  assert.equal(catalogPriceProblem("deepseek-v4.1-flash", { input: 0.15, output: 0.6, cacheRead: 0.003, cacheWrite: 0 }), undefined);
  const problem = catalogPriceProblem("deepseek-v4.1-flash", { input: 0.30, output: 1.20, cacheRead: 0.006, cacheWrite: 0 });
  assert.match(problem ?? "", /input 0.3 != 0.15/);
  assert.match(catalogPriceProblem("qwen3.8-flash", undefined) ?? "", /qwen3.8-flash/);
});
