import type { SessionEntry } from "@earendil-works/pi-coding-agent";

export const MAX_HARD_CAP_USD = 3;
export const BUDGET_PROVIDER = "arena-budget";
export type BudgetLimits = { hardCapUsd: number; stopUsd: number };

export function budgetLimits(env: NodeJS.ProcessEnv = process.env): BudgetLimits {
  const hardCapUsd = Number(env.ARENA_HARD_CAP_USD ?? "3");
  const stopUsd = Number(env.ARENA_STOP_USD ?? String(Math.min(2.5, hardCapUsd * 0.85)));
  if (!Number.isFinite(hardCapUsd) || hardCapUsd < 0.1 || hardCapUsd > MAX_HARD_CAP_USD
    || !Number.isFinite(stopUsd) || stopUsd <= 0 || stopUsd > hardCapUsd) {
    throw new Error("Arena budget limits must satisfy $0.10 <= hard cap <= $3 and 0 < stop <= hard cap");
  }
  return { hardCapUsd, stopUsd };
}

type Usage = { input: number; output: number; cacheRead: number; cacheWrite: number };
type Price = { input: number; output: number; cacheRead: number; cacheWrite: number };

// Published OpenCode Go prices per million tokens, using the most expensive
// context/time tier so the ledger stays conservative without clock or cache guesses.
export const MODELS = {
  "gpt-6-luna": {
    price: { input: 0.20, output: 0.75, cacheRead: 0.02, cacheWrite: 0.25 },
    contextWindow: 1_050_000,
    maxTokens: 128_000,
  },
  "deepseek-v4.1-flash": {
    price: { input: 0.30, output: 1.20, cacheRead: 0.006, cacheWrite: 0 },
    contextWindow: 1_000_000,
    maxTokens: 384_000,
  },
} as const;

export type BudgetModel = keyof typeof MODELS;

export function isBudgetModel(model: string): model is BudgetModel {
  return Object.hasOwn(MODELS, model);
}

export function usageCost(usage: Usage, model: BudgetModel): number {
  const price: Price = MODELS[model].price;
  let cost = 0;
  for (const category of ["input", "output", "cacheRead", "cacheWrite"] as const) {
    const tokens = usage[category];
    if (!Number.isFinite(tokens) || tokens < 0) throw new Error(`Invalid ${category} usage`);
    cost += tokens * price[category] / 1_000_000;
  }
  return cost;
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
          throw new Error("Arena budget cannot price a failed or aborted provider request");
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

export function maximumNextRequest(model: BudgetModel): number {
  const { price, contextWindow, maxTokens } = MODELS[model];
  return contextWindow * Math.max(price.input, price.cacheRead, price.cacheWrite) / 1_000_000
    + maxTokens * price.output / 1_000_000;
}

export function budgetDecision(spent: number, model: BudgetModel, limits: BudgetLimits): { allowed: boolean; reserve: number; reason: string } {
  if (!Number.isFinite(spent) || spent < 0) throw new Error("Invalid Arena spend");
  const reserve = maximumNextRequest(model);
  const allowed = spent < limits.stopUsd && spent + reserve <= limits.hardCapUsd;
  const reason = allowed ? "within budget"
    : `Arena budget stop: $${spent.toFixed(4)} spent; reserving $${reserve.toFixed(4)} for another request would exceed the $${limits.hardCapUsd.toFixed(2)} cap or $${limits.stopUsd.toFixed(2)} stop target`;
  return { allowed, reserve, reason };
}

// Responses API max_output_tokens includes reasoning tokens. Use the final
// serialized provider payload, after Pi has added its system prompt and tools.
export const MAX_REQUEST_OUTPUT_TOKENS = 16_000;

export function boundedPayload(payload: unknown, model: BudgetModel): { payload: Record<string, unknown>; reserve: number } {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("Unknown provider payload");
  const value = { ...payload as Record<string, unknown> };
  if (typeof value.max_output_tokens !== "number" || !Number.isFinite(value.max_output_tokens)) {
    throw new Error("Cannot enforce Arena output bound on provider payload");
  }
  value.max_output_tokens = Math.min(value.max_output_tokens, MAX_REQUEST_OUTPUT_TOKENS);
  const bytes = Buffer.byteLength(JSON.stringify(value), "utf8");
  // Text-only Responses payloads cannot tokenize into more tokens than their
  // UTF-8 bytes; allow a fixed margin for protocol framing outside the JSON.
  const inputBound = bytes + 4096;
  if (inputBound > MODELS[model].contextWindow) throw new Error("Arena context bound exceeds model window");
  const price = MODELS[model].price;
  const reserve = inputBound * Math.max(price.input, price.cacheRead, price.cacheWrite) / 1_000_000
    + Number(value.max_output_tokens) * price.output / 1_000_000;
  return { payload: value, reserve };
}

export function permitFinalPayload(payload: unknown, model: BudgetModel,
  state: { spent: number; charged: number }, limits: BudgetLimits) {
  const bounded = boundedPayload(payload, model);
  if (!Number.isFinite(state.spent) || !Number.isFinite(state.charged) ||
      state.spent < 0 || state.charged < state.spent ||
      state.spent >= limits.stopUsd || state.charged + bounded.reserve > limits.hardCapUsd) {
    throw new Error(`Arena budget stop: $${state.charged.toFixed(6)} charged, $${bounded.reserve.toFixed(6)} required, $${limits.hardCapUsd.toFixed(2)} cap`);
  }
  return bounded;
}
