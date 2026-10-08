import type { SessionEntry } from "@earendil-works/pi-coding-agent";

export const MAX_HARD_CAP_USD = 3;
export const BUDGET_PROVIDER = "arena-budget";
export type BudgetLimits = { hardCapUsd: number; stopUsd: number };

// The only hard cap is MAX_HARD_CAP_USD: the worst-case request estimate is gated against it alone.
// A configured cap below it (ARENA_HARD_CAP_USD, name kept for callers) is a soft cap checked
// against actual settled spend only; the request that crosses it may overshoot.
export function budgetLimits(env: NodeJS.ProcessEnv = process.env): BudgetLimits {
  const configured = Number(env.ARENA_HARD_CAP_USD ?? String(MAX_HARD_CAP_USD));
  if (!Number.isFinite(configured) || configured < 0.1 || configured > MAX_HARD_CAP_USD) {
    throw new Error("Arena spend cap must satisfy $0.10 <= cap <= $3");
  }
  return { hardCapUsd: MAX_HARD_CAP_USD, stopUsd: configured };
}

/** Soft-cap check on actual settled spend. No estimate is involved. */
export function softCapGate(settledUsd: number, limits: BudgetLimits) {
  if (!Number.isFinite(settledUsd) || settledUsd < 0) throw new Error("Invalid Arena settled spend");
  const reached = settledUsd >= limits.stopUsd;
  return { allowed: !reached, reached,
    remainingUsd: Math.max(0, limits.stopUsd - settledUsd),
    overshootUsd: Math.max(0, settledUsd - limits.stopUsd),
    // At the $3 hard cap the same condition is the historical actual_usage_cap stop.
    stop: reached ? (limits.stopUsd >= limits.hardCapUsd ? "actual_usage_cap" : "soft_cap_reached") : null };
}

type Usage = { input: number; output: number; cacheRead: number; cacheWrite: number };
type Price = { input: number; output: number; cacheRead: number; cacheWrite: number };

// OpenCode Go prices per million tokens, as Pi's opencode-go catalog bills them;
// `catalogPriceProblem` refuses a session when the two disagree. Luna's higher
// tier applies only when the billed prompt (new input plus cache read/write)
// exceeds 272K tokens; Pi's catalog has no tier, so the ledger stays conservative.
export const MODELS = {
  "gpt-6-luna": {
    price: { input: 0.10, output: 0.50, cacheRead: 0.01, cacheWrite: 0.125 },
    highPrice: { input: 0.20, output: 0.75, cacheRead: 0.02, cacheWrite: 0.25 },
    highContextThreshold: 272_000,
    contextWindow: 1_050_000,
    maxTokens: 128_000,
    requestOutputTokens: 16_000,
  },
  "qwen3.8-flash": {
    price: { input: 0.15, output: 0.47, cacheRead: 0.016, cacheWrite: 0.20 },
    contextWindow: 1_000_000,
    maxTokens: 131_072,
    requestOutputTokens: 16_000,
  },
  "deepseek-v4.1-flash": {
    price: { input: 0.15, output: 0.60, cacheRead: 0.003, cacheWrite: 0 },
    contextWindow: 1_000_000,
    maxTokens: 384_000,
    // DeepSeek's high thinking effort hit a 16K limit mid-thought in v6 runs (output includes thinking).
    requestOutputTokens: 32_000,
  },
} as const;

export type BudgetModel = keyof typeof MODELS;

export function isBudgetModel(model: string): model is BudgetModel {
  return Object.hasOwn(MODELS, model);
}

/** Why Pi's catalog price for `model` is not the ledger's base price, or undefined. */
export function catalogPriceProblem(model: BudgetModel, cost: Partial<Price> | undefined): string | undefined {
  const price = MODELS[model].price;
  const differs = (Object.keys(price) as Array<keyof Price>)
    .filter(key => typeof cost?.[key] !== "number" || Math.abs(cost[key]! - price[key]) > 1e-12);
  return differs.length
    ? `Arena price table differs from Pi's catalog for ${model}: ${differs.map(key => `${key} ${cost?.[key]} != ${price[key]}`).join(", ")}`
    : undefined;
}

export function usageCost(usage: Usage, model: BudgetModel): number {
  const price = priceForUsage(usage, model);
  let cost = 0;
  for (const category of ["input", "output", "cacheRead", "cacheWrite"] as const) {
    const tokens = usage[category];
    if (!Number.isFinite(tokens) || tokens < 0) throw new Error(`Invalid ${category} usage`);
    cost += tokens * price[category] / 1_000_000;
  }
  return cost;
}

export function usageCostParts(usage: Usage, model: BudgetModel) {
  const price = priceForUsage(usage, model);
  return Object.fromEntries((Object.keys(price) as Array<keyof Usage>)
    .map(category => [category, usage[category] * price[category] / 1_000_000])) as Record<keyof Usage, number>;
}

export function priceForUsage(usage: Usage, model: BudgetModel): Price {
  const specification = MODELS[model];
  if (model === "gpt-6-luna" &&
      usage.input + usage.cacheRead + usage.cacheWrite > MODELS["gpt-6-luna"].highContextThreshold) {
    return MODELS["gpt-6-luna"].highPrice;
  }
  return specification.price;
}

function pricedModel(provider: string, model: string, expected: BudgetModel): BudgetModel {
  if (provider !== "opencode-go" || model !== expected) {
    throw new Error(`Unpriced model in Arena budget session: ${provider}/${model}`);
  }
  return expected;
}

// getEntries() includes abandoned branches. They still consumed paid API usage.
export function sessionSpend(entries: readonly SessionEntry[], sessionModel: BudgetModel): number {
  let spend = 0;
  for (const entry of entries) {
    if (entry.type === "message") {
      if (entry.message.role === "assistant") {
        if ((entry.message.stopReason === "error" || entry.message.stopReason === "aborted")
          && !entry.message.usage?.totalTokens) {
          // A failure before transport has no session usage. Any request that
          // did reserve funds is charged by the separate durable cost journal.
          continue;
        }
        spend += usageCost(entry.message.usage,
          pricedModel(entry.message.provider, entry.message.model, sessionModel));
      } else if (entry.message.role === "toolResult" && entry.message.usage) {
        spend += usageCost(entry.message.usage, sessionModel);
      }
    } else if (entry.type === "usage") {
      spend += usageCost(entry.usage, pricedModel(entry.provider, entry.model, sessionModel));
    } else if ((entry.type === "compaction" || entry.type === "branch_summary") && entry.usage) {
      spend += usageCost(entry.usage, sessionModel);
    }
  }
  return spend;
}

export function sessionEmbeddedCost(entries: readonly SessionEntry[]): { usd: number; priced_entries: number; missing_entries: number } {
  let usd = 0, priced_entries = 0, missing_entries = 0;
  for (const entry of entries) {
    const usage = entry.type === "message" && (entry.message.role === "assistant" || entry.message.role === "toolResult")
      ? entry.message.usage : (entry.type === "usage" || entry.type === "compaction" || entry.type === "branch_summary")
        ? entry.usage : undefined;
    if (!usage?.totalTokens) continue;
    const cost = usage.cost?.total;
    if (typeof cost === "number" && Number.isFinite(cost)) { usd += cost; priced_entries += 1; }
    else missing_entries += 1;
  }
  return { usd, priced_entries, missing_entries };
}

// Cache hit rate in the provider-standard sense: cache_read over every prompt token
// (input + cache_read + cache_write). Savings compare the input-side bill with billing
// every prompt token at the uncached input rate.
export function cacheHitPct(usage: { input?: number; cacheRead?: number; cacheWrite?: number }): number | null {
  const read = usage.cacheRead ?? 0;
  const prompt = (usage.input ?? 0) + read + (usage.cacheWrite ?? 0);
  return prompt ? 100 * read / prompt : null;
}

export function cacheUtilization(entries: readonly SessionEntry[], sessionModel: BudgetModel) {
  const usages = entries.flatMap(entry => entry.type === "message"
    && entry.message.role === "assistant"
    && entry.message.provider === "opencode-go"
    && entry.message.model === sessionModel
    && entry.message.usage?.totalTokens ? [entry.message.usage] : []);
  const summarize = (items: typeof usages) => {
    const sum = (key: "input" | "cacheRead" | "cacheWrite") => items.reduce((total, usage) => total + (usage[key] ?? 0), 0);
    const read = sum("cacheRead"), write = sum("cacheWrite"), input = sum("input");
    let actual = 0, uncached = 0;
    for (const usage of items) {
      const price = priceForUsage(usage, sessionModel);
      actual += ((usage.input ?? 0) * price.input + (usage.cacheRead ?? 0) * price.cacheRead
        + (usage.cacheWrite ?? 0) * price.cacheWrite) / 1_000_000;
      uncached += ((usage.input ?? 0) + (usage.cacheRead ?? 0) + (usage.cacheWrite ?? 0)) * price.input / 1_000_000;
    }
    return { read_tokens: read, write_tokens: write, input_tokens: input,
      reuse_pct: cacheHitPct({ input, cacheRead: read, cacheWrite: write }),
      savings_pct: uncached ? 100 * (1 - actual / uncached) : null };
  };
  return { all: summarize(usages), recent_ten: summarize(usages.slice(-10)) };
}

// A request that wrote more cache than it read after warm-up means the stable prefix was not reused.
export const CACHE_WARMUP_REQUESTS = 2;
export function cacheAlarm(usage: { cacheRead?: number; cacheWrite?: number }, settledRequests: number):
    { request: number; read: number; write: number } | undefined {
  const read = usage.cacheRead ?? 0, write = usage.cacheWrite ?? 0;
  return settledRequests > CACHE_WARMUP_REQUESTS && write > read ? { request: settledRequests, read, write } : undefined;
}

// The Responses API uses max_output_tokens; Anthropic Messages uses max_tokens.
// Both include generated thinking tokens in the output limit. The limit is fixed per model
// for the whole run (the request shape must not change within a run).
export function maxRequestOutputTokens(model: BudgetModel): number {
  return MODELS[model].requestOutputTokens;
}

export function requestShape(payload: Record<string, unknown>): string {
  const hasThinking = Object.hasOwn(payload, "thinking");
  const hasReasoning = Object.hasOwn(payload, "reasoning");
  return JSON.stringify({
    output_field: typeof payload.max_output_tokens === "number" ? "max_output_tokens" : "max_tokens",
    output_limit: payload.max_output_tokens ?? payload.max_tokens,
    thinking_present: hasThinking,
    thinking: hasThinking ? payload.thinking : null,
    reasoning_present: hasReasoning,
    reasoning: hasReasoning ? payload.reasoning : null,
  });
}

// This limit is selected once for all requests in a run and is independent of allowance remaining.
const MIN_THINKING_BUDGET_TOKENS = 1024;
const THINKING_ANSWER_TOKENS = 1024;

export function boundedPayload(payload: unknown, model: BudgetModel): { payload: Record<string, unknown>; reserve: number } {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("Unknown provider payload");
  const value = { ...payload as Record<string, unknown> };
  const outputField = typeof value.max_output_tokens === "number" ? "max_output_tokens"
    : typeof value.max_tokens === "number" ? "max_tokens" : null;
  if (!outputField || !Number.isFinite(value[outputField]) || Number(value[outputField]) <= 0) {
    throw new Error("Cannot enforce Arena output bound on provider payload");
  }
  value[outputField] = Math.min(Number(value[outputField]), maxRequestOutputTokens(model));
  // Anthropic Messages requires budget_tokens < max_tokens. Normalize a too-large initial budget
  // once to leave room for an answer; this does not depend on remaining allowance.
  const thinking = value.thinking as { type?: string; budget_tokens?: number } | undefined;
  if (outputField === "max_tokens" && thinking?.type === "enabled" && typeof thinking.budget_tokens === "number") {
    const room = Number(value.max_tokens) - THINKING_ANSWER_TOKENS;
    if (room < MIN_THINKING_BUDGET_TOKENS) throw new Error("Fixed Arena output limit cannot fit the requested thinking budget");
    if (thinking.budget_tokens > room) value.thinking = { ...thinking, budget_tokens: room };
  }
  const bytes = Buffer.byteLength(JSON.stringify(value), "utf8");
  // Text-only Responses payloads cannot tokenize into more tokens than their
  // UTF-8 bytes; allow a fixed margin for protocol framing outside the JSON.
  const inputBound = bytes + 4096;
  if (inputBound > MODELS[model].contextWindow) throw new Error("Arena context bound exceeds model window");
  const price = model === "gpt-6-luna" ? MODELS[model].highPrice : MODELS[model].price;
  const reserve = inputBound * Math.max(price.input, price.cacheRead, price.cacheWrite) / 1_000_000
    + Number(value[outputField]) * price.output / 1_000_000;
  return { payload: value, reserve };
}

export function assessFinalPayload(payload: unknown, model: BudgetModel,
  state: { spent: number; unresolved?: number }, limits: BudgetLimits) {
  const bounded = boundedPayload(payload, model);
  const gate = budgetGate(bounded.reserve, state.spent, state.unresolved ?? 0, limits);
  return { ...bounded, ...gate };
}

export function budgetGate(estimateUsd: number, spentUsd: number, unresolvedUsd: number, limits: BudgetLimits) {
  if (![estimateUsd, spentUsd, unresolvedUsd].every(Number.isFinite)
    || estimateUsd < 0 || spentUsd < 0 || unresolvedUsd < 0) throw new Error("Invalid Arena budget estimate");
  const remainingUsd = Math.max(0, limits.hardCapUsd - spentUsd - unresolvedUsd);
  const allowed = estimateUsd <= remainingUsd;
  return { allowed, estimateUsd, remainingUsd,
    overshootUsd: Math.max(0, estimateUsd - remainingUsd),
    reason: allowed ? "estimate fits remaining allowance" : "estimated request exceeds remaining allowance" };
}

// The model may stop on its own only when at most this fraction of the soft cap is left.
// Unspent allowance has no value; safety stops (soft cap, $3 estimate gate, error loop,
// continuation limit, no-work fallback) are independent of this rule.
export const FINISH_ALLOWED_REMAINING_FRACTION = 0.10;

export function finishAllowed(settledUsd: number, limits: BudgetLimits) {
  const remainingUsd = softCapGate(settledUsd, limits).remainingUsd;
  const remainingFraction = limits.stopUsd > 0 ? remainingUsd / limits.stopUsd : 0;
  return { allowed: remainingFraction <= FINISH_ALLOWED_REMAINING_FRACTION + 1e-12, remainingUsd, remainingFraction };
}
