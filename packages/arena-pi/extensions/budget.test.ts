import assert from "node:assert/strict";
import test from "node:test";
import "./testmodels.ts";
import { assessFinalPayload, compactionPayload, boundedPayload, budgetGate, softCapGate, catalogPriceProblem, cacheAlarm, budgetLimits, budgetFooter, cacheUtilization, finishAllowed, FINISH_ALLOWED_REMAINING_FRACTION, enforcedMaxTokens, maxRequestOutputTokens, MODELS, parseModelConfig, PROVIDER, requestShape, sessionEmbeddedCost, sessionSpend, usageCost, usageCostParts } from "./budget.ts";

const usage = { input: 1_000_000, output: 100_000, cacheRead: 0, cacheWrite: 0 };
const LUNA = MODELS["gpt-6-luna"], DEEPSEEK = MODELS["deepseek-v4.1-flash"], QWEN = MODELS["qwen3.8-flash"];
const cost = (price: { input: number; output: number; cacheRead: number; cacheWrite: number },
  u: { input: number; output: number; cacheRead: number; cacheWrite: number }) =>
  (u.input * price.input + u.output * price.output + u.cacheRead * price.cacheRead + u.cacheWrite * price.cacheWrite) / 1_000_000;
// One request of `usage` (1M input) is above Luna's tier threshold, so it bills at the high tier.
const usageHigh = cost(LUNA.highPrice!, usage);
const near = (a: number, b: number) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);

test("uses Luna's low tier until one request crosses its high-tier threshold", () => {
  const threshold = LUNA.highContextThreshold!;
  const below = { input: 0, output: 1000, cacheRead: threshold - 72_000, cacheWrite: 0 };
  const above = { ...below, cacheRead: threshold + 1000 };
  near(usageCost(below, "gpt-6-luna"), cost(LUNA.price, below));
  near(usageCost(above, "gpt-6-luna"), cost(LUNA.highPrice!, above));
  const atEdge = { ...below, cacheRead: threshold };  // the tier applies only above the threshold
  near(usageCost(atEdge, "gpt-6-luna"), cost(LUNA.price, atEdge));
  const entries = [below, above].map(u => ({ type: "message",
    message: { role: "assistant", provider: PROVIDER, model: "gpt-6-luna",
      usage: { ...u, totalTokens: u.cacheRead + 1000 } } }));
  near(sessionSpend(entries as never, "gpt-6-luna"), cost(LUNA.price, below) + cost(LUNA.highPrice!, above));
});

test("keeps Pi's embedded estimate separate from conservative ledger pricing", () => {
  const entries = [{ type: "message", message: { role: "assistant", provider: PROVIDER,
    model: "gpt-6-luna", usage: { ...usage, totalTokens: 1_100_000,
      cost: { total: 0.15 } } } }];
  near(sessionSpend(entries as never, "gpt-6-luna"), usageHigh);
  assert.deepEqual(sessionEmbeddedCost(entries as never),
    { usd: 0.15, priced_entries: 1, missing_entries: 0 });
  assert.deepEqual(usageCostParts(usage, "gpt-6-luna"),
    { input: LUNA.highPrice!.input, output: 100_000 * LUNA.highPrice!.output / 1_000_000, cacheRead: 0, cacheWrite: 0 });
});

test("counts all persisted paid usage, including abandoned branches and compaction", () => {
  const entries = [
    { type: "message", message: { role: "assistant", provider: PROVIDER,
      model: "gpt-6-luna", usage } },
    { type: "usage", provider: PROVIDER, model: "gpt-6-luna", usage },
    { type: "compaction", usage },
    { type: "message", message: { role: "toolResult", usage } },
  ];
  near(sessionSpend(entries as never, "gpt-6-luna"), 4 * usageHigh);
});

test("reports measured cache reuse, including a recent window", () => {
  const entries = [
    { type: "message", message: { role: "assistant", provider: PROVIDER, model: "gpt-6-luna",
      usage: { input: 0, output: 1, cacheRead: 0, cacheWrite: 100, totalTokens: 101 } } },
    { type: "message", message: { role: "assistant", provider: PROVIDER, model: "gpt-6-luna",
      usage: { input: 0, output: 1, cacheRead: 990, cacheWrite: 10, totalTokens: 1001 } } },
  ];
  const result = cacheUtilization(entries as never, "gpt-6-luna");
  assert.equal(result.all.read_tokens, 990);
  assert.equal(result.all.write_tokens, 110);
  assert.equal(result.all.reuse_pct, 90);
});

test("fails closed on unpriced models or invalid usage", () => {
  assert.deepEqual(budgetLimits({ ARENA_HARD_CAP_USD: "1" }), { hardCapUsd: 3, stopUsd: 1 });
  assert.throws(() => budgetLimits({ ARENA_HARD_CAP_USD: "3.01" }));
  assert.throws(() => sessionSpend([{ type: "message", message: { role: "assistant",
    provider: "other", model: "gpt-6-luna", usage } }] as never, "gpt-6-luna"));
  assert.throws(() => usageCost({ ...usage, output: Number.NaN }, "gpt-6-luna"));
});

test("undispatched zero-token errors do not poison exact session resume", () => {
  const entries = [
    { type: "message", message: { role: "assistant", provider: "arena-guard",
      model: "gpt-6-luna", stopReason: "error", usage: { input: 0, output: 0,
        cacheRead: 0, cacheWrite: 0, totalTokens: 0 } } },
    { type: "message", message: { role: "assistant", provider: PROVIDER,
      model: "gpt-6-luna", stopReason: "stop", usage } },
  ];
  near(sessionSpend(entries as never, "gpt-6-luna"), usageHigh);
});

test("a bounded final payload permits a ten-cent experiment", () => {
  const { payload, reserve } = boundedPayload({ input: "reference proof", max_output_tokens: 128_000 }, "gpt-6-luna");
  assert.equal(payload.max_output_tokens, LUNA.requestOutputTokens);
  assert.ok(reserve < 0.1);
  assert.throws(() => boundedPayload({ input: "x" }, "gpt-6-luna"));
  assert.throws(() => budgetLimits({ ARENA_HARD_CAP_USD: "0.09" }));
});

test("caps Qwen's Anthropic Messages payload before dispatch", () => {
  const { payload, reserve } = boundedPayload({ messages: [{ role: "user", content: "proof" }],
    max_tokens: QWEN.maxTokens }, "qwen3.8-flash");
  assert.equal(payload.max_tokens, QWEN.requestOutputTokens);
  assert.ok(reserve < 0.1);
});

test("fixes the Anthropic output and thinking shape independently of remaining allowance", () => {
  // Normalize Pi's initial provider shape once; a smaller balance must not create a new cache key.
  const high = boundedPayload({ messages: [], max_tokens: 32_384,
    thinking: { type: "enabled", budget_tokens: 16_384 } }, "qwen3.8-flash").payload as any;
  assert.equal(high.max_tokens, QWEN.requestOutputTokens);
  assert.equal(high.thinking.budget_tokens, QWEN.requestOutputTokens - 1024);
  const nearCap = boundedPayload({ messages: [], max_tokens: 32_384,
    thinking: { type: "enabled", budget_tokens: 16_384 } }, "qwen3.8-flash").payload as any;
  assert.deepEqual(nearCap, high);
  const low = boundedPayload({ messages: [], max_tokens: 24_192,
    thinking: { type: "enabled", budget_tokens: 8_192 } }, "qwen3.8-flash").payload as any;
  assert.equal(low.max_tokens, QWEN.requestOutputTokens);
  assert.equal(low.thinking.budget_tokens, 8_192);
});

test("fixed request shape distinguishes absent thinking from explicit null", () => {
  const base = { max_tokens: 16000 };
  assert.notEqual(requestShape(base), requestShape({ ...base, thinking: null }));
  assert.notEqual(requestShape(base), requestShape({ ...base, reasoning: null }));
});

test("large serialized text fits the model when its byte token upper bound fits", () => {
  const payload = { max_output_tokens: 16000, input: "x".repeat(600_000) };
  assert.ok(boundedPayload(payload, "gpt-6-luna").reserve > 0);
});

test("the worst-case estimate is gated against the $3 hard cap only, whatever the configured cap", () => {
  const payload = { max_output_tokens: 16000, input: "proof" };
  for (const configured of [0.1, 1, 3]) {
    const limits = budgetLimits({ ARENA_HARD_CAP_USD: String(configured) });
    assert.equal(limits.hardCapUsd, 3);
    const estimate = assessFinalPayload(payload, "gpt-6-luna", { spent: 0, unresolved: 0 }, limits).estimateUsd;
    assert.equal(assessFinalPayload(payload, "gpt-6-luna",
      { spent: 3 - estimate - 1e-10, unresolved: 0 }, limits).allowed, true);
    assert.equal(assessFinalPayload(payload, "gpt-6-luna",
      { spent: 3 - estimate / 2, unresolved: 0 }, limits).allowed, false);
  }
});

test("a cap below $3 is a soft cap on actual settled spend and ignores the estimate", () => {
  const limits = budgetLimits({ ARENA_HARD_CAP_USD: "0.10" });
  // spent 0.03 with a 0.08 reserve: the estimate alone would exceed 0.10, but only $3 gates it.
  assert.equal(budgetGate(0.08, 0.03, 0, limits).allowed, true);
  assert.equal(softCapGate(0.03, limits).allowed, true);
  assert.ok(Math.abs(softCapGate(0.03, limits).remainingUsd - 0.07) < 1e-12);
  const reached = softCapGate(0.10, limits);
  assert.equal(reached.allowed, false);
  assert.equal(reached.stop, "soft_cap_reached");
  assert.equal(softCapGate(0.12, limits).overshootUsd > 0.0199, true);
  // At the $3 cap soft equals hard and keeps the historical stop name.
  assert.equal(softCapGate(3, budgetLimits({})).stop, "actual_usage_cap");
  assert.equal(softCapGate(2.99, budgetLimits({})).stop, null);
});

test("gate includes outstanding reservations and never reshapes a request to fit", () => {
  const limits = { hardCapUsd: 0.1, stopUsd: 0.1 };  // the gate itself only reads hardCapUsd
  const affordable = budgetGate(0.03, 0.04, 0.02, limits);
  assert.equal(affordable.allowed, true);
  assert.ok(Math.abs(affordable.remainingUsd - 0.04) < 1e-12);
  assert.equal(affordable.reason, "estimate fits remaining allowance");
  const unaffordable = budgetGate(0.05, 0.04, 0.02, limits);
  assert.equal(unaffordable.allowed, false);
  assert.ok(Math.abs(unaffordable.remainingUsd - 0.04) < 1e-12);
  assert.ok(Math.abs(unaffordable.overshootUsd - 0.01) < 1e-12);
  assert.equal(unaffordable.reason, "estimated request exceeds remaining allowance");
  const payload = { model: "x", input: [], max_output_tokens: 128_000 };
  const first = assessFinalPayload(payload, "gpt-6-luna", { spent: 0, unresolved: 0 }, limits);
  const last = assessFinalPayload(payload, "gpt-6-luna", { spent: 0.099, unresolved: 0 }, limits);
  assert.deepEqual(first.payload, last.payload);
  assert.equal(last.allowed, false);
  assert.equal(first.payload.max_output_tokens, LUNA.requestOutputTokens);
});

test("cache alarm fires only after warm-up, when a request writes more than it reads", () => {
  assert.equal(cacheAlarm({ cacheRead: 0, cacheWrite: 9000 }, 1), undefined);
  assert.equal(cacheAlarm({ cacheRead: 0, cacheWrite: 9000 }, 2), undefined);
  assert.deepEqual(cacheAlarm({ cacheRead: 1000, cacheWrite: 9000 }, 3), { request: 3, read: 1000, write: 9000 });
  assert.equal(cacheAlarm({ cacheRead: 9000, cacheWrite: 900 }, 7), undefined);
  assert.equal(cacheAlarm({}, 7), undefined);
});

test("refuses a ledger price that differs from Pi's catalog", () => {
  assert.equal(catalogPriceProblem("deepseek-v4.1-flash", { ...DEEPSEEK.price }), undefined);
  const problem = catalogPriceProblem("deepseek-v4.1-flash", { ...DEEPSEEK.price, input: DEEPSEEK.price.input * 2 });
  assert.match(problem ?? "", new RegExp(`input ${DEEPSEEK.price.input * 2} != ${DEEPSEEK.price.input}`));
  assert.match(catalogPriceProblem("qwen3.8-flash", undefined) ?? "", /qwen3.8-flash/);
});

test("cache hit rate is cache_read over all prompt tokens and savings compare with uncached billing", () => {
  // DeepSeek reports no cache writes, so a read/(read+write) rate would read 100%.
  const entries = [{ type: "message", message: { role: "assistant", provider: PROVIDER, model: "deepseek-v4.1-flash",
    usage: { input: 2100, output: 10, cacheRead: 7900, cacheWrite: 0, totalTokens: 10010 } } }];
  const { all } = cacheUtilization(entries as never, "deepseek-v4.1-flash");
  assert.equal(all.reuse_pct, 79);
  assert.equal(all.input_tokens, 2100);
  const p = DEEPSEEK.price;  // actual: 2100 input + 7900 cache read; uncached: 10000 input
  assert.ok(Math.abs(all.savings_pct! - 100 * (1 - (2100 * p.input + 7900 * p.cacheRead) / (10_000 * p.input))) < 1e-9);
  assert.equal(cacheUtilization([] as never, "gpt-6-luna").all.reuse_pct, null);
});

test("each model gets its own output limit from models.yaml", () => {
  for (const [id, spec] of Object.entries(MODELS)) assert.equal(maxRequestOutputTokens(id), spec.requestOutputTokens);
  const ds = boundedPayload({ messages: [], max_tokens: DEEPSEEK.maxTokens }, "deepseek-v4.1-flash");
  assert.equal(ds.payload.max_tokens, DEEPSEEK.requestOutputTokens);
  assert.ok(ds.reserve < 0.1);
  const again = boundedPayload({ messages: [], max_tokens: DEEPSEEK.maxTokens }, "deepseek-v4.1-flash");
  assert.equal(requestShape(again.payload), requestShape(ds.payload));
  const thinking = boundedPayload({ messages: [], max_tokens: 2 * DEEPSEEK.requestOutputTokens,
    thinking: { type: "enabled", budget_tokens: 2 * DEEPSEEK.requestOutputTokens } }, "deepseek-v4.1-flash").payload as any;
  assert.equal(thinking.thinking.budget_tokens, DEEPSEEK.requestOutputTokens - 1024);
});

test("Pi's maxTokens for every model is the enforced output limit, not the physical one", () => {
  for (const [id, spec] of Object.entries(MODELS)) {
    assert.ok(spec.requestOutputTokens <= spec.maxTokens);
    const physical = { maxTokens: spec.maxTokens };
    enforcedMaxTokens(physical, id);
    assert.equal(physical.maxTokens, spec.requestOutputTokens);
    enforcedMaxTokens(physical, id);
    assert.equal(physical.maxTokens, spec.requestOutputTokens);
  }
});

test("every model compacts below its context window, DeepSeek later than Luna", () => {
  for (const spec of Object.values(MODELS)) assert.ok(spec.compaction.atTokens < spec.contextWindow);
  assert.ok(LUNA.compaction.atTokens <= LUNA.highContextThreshold!);
  assert.ok(DEEPSEEK.compaction.atTokens > LUNA.compaction.atTokens);
});

test("the model may finish only with at most 10% of the soft cap left", () => {
  const limits = budgetLimits({ ARENA_HARD_CAP_USD: "0.1" });
  assert.equal(FINISH_ALLOWED_REMAINING_FRACTION, 0.1);
  assert.equal(finishAllowed(0.0, limits).allowed, false);
  assert.equal(finishAllowed(0.089, limits).allowed, false);
  assert.equal(finishAllowed(0.09, limits).allowed, true);
  assert.equal(finishAllowed(0.095, limits).allowed, true);
  assert.equal(finishAllowed(0.2, limits).allowed, true);
});

test("the context bound uses the provider's prior token count, and an overflow reads as one to Pi", () => {
  // ~1.1 MB of encrypted reasoning that the provider counted as ~180K tokens.
  const big = { input: [{ type: "reasoning", encrypted_content: "x".repeat(1_100_000) }], max_output_tokens: 16_000 };
  const bytes = Buffer.byteLength(JSON.stringify(big), "utf8");
  assert.throws(() => boundedPayload(big, "gpt-6-luna"), /exceeds the context window/);
  const grown = { ...big, input: [...big.input, { type: "message", content: "y".repeat(2_000) }] };
  assert.ok(boundedPayload(grown, "gpt-6-luna", { bytes, inputTokens: 180_000 }).reserve < 0.1);
  // A payload smaller than the prior one (after compaction) falls back to its own bytes.
  assert.throws(() => boundedPayload(big, "gpt-6-luna", { bytes: bytes + 10, inputTokens: 180_000 }), /context window/);
});

test("a missing or invalid model config fails with a clear error", () => {
  assert.throws(() => parseModelConfig(undefined), /ARENA_MODELS_JSON is not set.*models\.yaml/);
  assert.throws(() => parseModelConfig("{"), /not valid JSON/);
  const good = JSON.parse(process.env.ARENA_MODELS_JSON!);
  parseModelConfig(JSON.stringify(good));
  const broken = structuredClone(good);
  broken.models["gpt-6-luna"].contextWindow = 0;
  assert.throws(() => parseModelConfig(JSON.stringify(broken)), /gpt-6-luna\.contextWindow must be a positive number/);
});

test("compaction summary payloads bypass the window check and never refuse, only reserve", () => {
  const big = { model: "deepseek-v4.1-flash", max_tokens: 64_000,
    messages: [{ role: "user", content: "x".repeat(DEEPSEEK.contextWindow + 10) }] };
  // The agent-turn check is unchanged.
  assert.throws(() => boundedPayload(big, "deepseek-v4.1-flash"), /exceeds the context window/);
  const summary = compactionPayload(big, "deepseek-v4.1-flash");
  assert.ok(summary.reserve > 0 && Number.isFinite(summary.reserve));
  assert.equal((summary.payload as { max_tokens: number }).max_tokens, Math.min(64_000, maxRequestOutputTokens("deepseek-v4.1-flash")));
  // A payload the bound cannot normalize (no output field) is passed through with a byte estimate.
  const odd = compactionPayload({ model: "x", input: "y".repeat(1000) }, "deepseek-v4.1-flash");
  assert.ok(odd.reserve > 0);
  assert.throws(() => boundedPayload({ model: "x" }, "deepseek-v4.1-flash"), /Cannot enforce/);
});

test("the footer line states settled spend against the allowance", () => {
  const limits = { stopUsd: 0.5 } as any;
  assert.equal(budgetFooter(0.21, limits), "budget: $0.21 of $0.50 spent \u00b7 58% left");
  assert.equal(budgetFooter(0.6, limits), "budget: $0.60 of $0.50 spent \u00b7 0% left");
});
