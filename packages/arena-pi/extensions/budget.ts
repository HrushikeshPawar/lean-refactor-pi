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

export type Price = { input: number; output: number; cacheRead: number; cacheWrite: number };
export type ModelSpec = {
  price: Price;
  /** Higher tier applied when the billed prompt exceeds highContextThreshold; Pi's catalog has no tier. */
  highPrice?: Price;
  highContextThreshold?: number;
  contextWindow: number;
  maxTokens: number;
  requestOutputTokens: number;
  compaction: { atTokens: number; keepRecentTokens: number };
};
export type ModelConfig = { provider: string; models: Record<string, ModelSpec> };

// All per-model facts live in models.yaml. tools/run_pi_budgeted.py loads and validates it and passes
// it here as JSON, so this side needs no YAML parser and holds no second copy.
export const MODELS_ENV = "ARENA_MODELS_JSON";

export function parseModelConfig(raw: string | undefined): ModelConfig {
  if (!raw) throw new Error(`${MODELS_ENV} is not set; Arena models come from models.yaml, so start Pi through tools/run_pi_budgeted.py`);
  let config: any;
  try { config = JSON.parse(raw); }
  catch { throw new Error(`${MODELS_ENV} is not valid JSON`); }
  const bad = (what: string): never => { throw new Error(`${MODELS_ENV}: ${what}`); };
  const positive = (where: string, value: unknown, allowZero = false) => {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || (!allowZero && value === 0)) {
      bad(`${where} must be a ${allowZero ? "non-negative" : "positive"} number, got ${JSON.stringify(value)}`);
    }
  };
  const price = (where: string, value: any) => {
    for (const key of ["input", "output", "cacheRead", "cacheWrite"]) positive(`${where}.${key}`, value?.[key], true);
  };
  if (typeof config?.provider !== "string" || !config.provider) bad("provider is missing");
  if (!config.models || typeof config.models !== "object" || !Object.keys(config.models).length) bad("models is empty");
  for (const [id, spec] of Object.entries<any>(config.models)) {
    price(`${id}.price`, spec?.price);
    for (const key of ["contextWindow", "maxTokens", "requestOutputTokens"]) positive(`${id}.${key}`, spec[key]);
    if (spec.highPrice !== undefined) { price(`${id}.highPrice`, spec.highPrice); positive(`${id}.highContextThreshold`, spec.highContextThreshold); }
    positive(`${id}.compaction.atTokens`, spec.compaction?.atTokens);
    positive(`${id}.compaction.keepRecentTokens`, spec.compaction?.keepRecentTokens);
  }
  return config as ModelConfig;
}

const CONFIG = parseModelConfig(process.env[MODELS_ENV]);
export const PROVIDER = CONFIG.provider;
export const MODELS: Readonly<Record<string, ModelSpec>> = CONFIG.models;

export type BudgetModel = string;

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
  if (specification.highPrice &&
      usage.input + usage.cacheRead + usage.cacheWrite > specification.highContextThreshold!) {
    return specification.highPrice;
  }
  return specification.price;
}

function pricedModel(provider: string, model: string, expected: BudgetModel): BudgetModel {
  if (provider !== PROVIDER || model !== expected) {
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
    && entry.message.provider === PROVIDER
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

/**
 * Pi treats a `length` stop below `model.maxTokens` as context pressure and compacts (isRecoverableLength).
 * Our own per-request limit ends turns below the physical limit, so Pi's models must advertise the limit we
 * enforce. Messages carry the physical provider, so Pi resolves its maxTokens from that catalog model.
 */
export function enforcedMaxTokens(model: { maxTokens: number }, id: BudgetModel): void {
  model.maxTokens = Math.min(model.maxTokens, maxRequestOutputTokens(id));
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

// The last settled request: its payload size and the input tokens the provider counted for it.
export type PriorRequest = { bytes: number; inputTokens: number };

export function boundedPayload(payload: unknown, model: BudgetModel, prior?: PriorRequest,
    skipWindowCheck = false): { payload: Record<string, unknown>; reserve: number } {
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
  // A grown payload repeats the prior one, so its tokens are at most the provider's count for that
  // prefix plus one per added byte. This matters for encrypted reasoning blobs, which are byte-heavy
  // but token-light: a pure byte bound passed the window at ~180K real tokens, before Pi compacts.
  const byteBound = bytes + 4096;
  const inputBound = prior && prior.inputTokens > 0 && bytes >= prior.bytes
    ? Math.min(byteBound, prior.inputTokens + (bytes - prior.bytes) + 4096) : byteBound;
  // Worded so Pi recognises a context overflow and compacts, then retries, instead of failing the turn.
  if (!skipWindowCheck && inputBound > MODELS[model].contextWindow) throw new Error("Arena context bound exceeds the context window");
  const price = MODELS[model].highPrice ?? MODELS[model].price;
  const reserve = inputBound * Math.max(price.input, price.cacheRead, price.cacheWrite) / 1_000_000
    + Number(value[outputField]) * price.output / 1_000_000;
  return { payload: value, reserve };
}

// Compaction summary requests are always within budget: no window check, no gate, and they never
// refuse. This only yields the ledger reserve, a pure byte-bound estimate (the summary payload is not
// a growth of any prior request, so no token count applies). Output is clamped to the run-wide limit
// when the payload carries one; a payload shape the bound cannot normalize is passed through as is.
export function compactionPayload(payload: unknown, model: BudgetModel): { payload: unknown; reserve: number } {
  let value = payload, output = maxRequestOutputTokens(model);
  try {
    const bounded = boundedPayload(payload, model, undefined, true);
    value = bounded.payload;
    return { payload: value, reserve: bounded.reserve };
  } catch { /* not normalizable; estimate from its size below */ }
  const bytes = Buffer.byteLength(JSON.stringify(value ?? null), "utf8");
  const price = MODELS[model].highPrice ?? MODELS[model].price;
  return { payload: value, reserve: (bytes + 4096) * Math.max(price.input, price.cacheRead, price.cacheWrite) / 1_000_000
    + output * price.output / 1_000_000 };
}

export function assessFinalPayload(payload: unknown, model: BudgetModel,
  state: { spent: number; unresolved?: number }, limits: BudgetLimits, prior?: PriorRequest) {
  const bounded = boundedPayload(payload, model, prior);
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

/** One factual footer line: settled spend against the allowance. No advice. */
export function budgetFooter(settledUsd: number, limits: BudgetLimits): string {
  const left = limits.stopUsd > 0 ? Math.max(0, Math.round(100 * (1 - settledUsd / limits.stopUsd))) : 0;
  return `budget: $${settledUsd.toFixed(2)} of $${limits.stopUsd.toFixed(2)} spent \u00b7 ${left}% left`;
}
