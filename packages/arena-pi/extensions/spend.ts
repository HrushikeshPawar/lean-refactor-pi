// The spend rule: after every LLM call the call's actual cost (Pi's `usage.cost.total`) is added to the
// run total. At or above the limit the agent stops. No estimates, no reservations; the call that crosses
// the limit may overshoot it, and that is accepted.
import { render } from "./text.ts";

export const DEFAULT_LIMIT_USD = 0.5;
export const MAX_LIMIT_USD = 2.5;

export function limitUsd(env: NodeJS.ProcessEnv = process.env): number {
  const limit = Number(env.ARENA_LIMIT_USD ?? String(DEFAULT_LIMIT_USD));
  // not-model-facing: extension startup rejects invalid operator configuration.
  if (!Number.isFinite(limit) || limit <= 0) throw new Error(`Arena spend limit must be a positive number of dollars, got ${env.ARENA_LIMIT_USD}`); // not-model-facing: extension startup rejects invalid operator configuration.
  // not-model-facing: extension startup rejects invalid operator configuration.
  if (limit > MAX_LIMIT_USD) throw new Error(`Arena spend limit $${limit} is above the maximum of $${MAX_LIMIT_USD}`); // not-model-facing: extension startup rejects invalid operator configuration.
  return limit;
}

/** The cost Pi reported for one call; a missing or invalid figure counts as zero. */
export function callCost(usage: { cost?: { total?: number } } | undefined): number {
  const total = usage?.cost?.total;
  return typeof total === "number" && Number.isFinite(total) && total > 0 ? total : 0;
}

export function limitReached(spentUsd: number, limit: number): boolean {
  return spentUsd >= limit;
}

/** One factual footer line: spend against the limit. No advice. */
export async function spendFooter(spentUsd: number, limit: number): Promise<string> {
  const left = limit > 0 ? Math.max(0, Math.round(100 * (1 - spentUsd / limit))) : 0;
  return render("messages/footer", { spent: spentUsd.toFixed(2), limit: limit.toFixed(2), left });
}

// Cache hit rate in the provider-standard sense: cache_read over every prompt token
// (input + cache_read + cache_write).
export function cacheHitPct(usage: { input?: number; cacheRead?: number; cacheWrite?: number }): number | null {
  const read = usage.cacheRead ?? 0;
  const prompt = (usage.input ?? 0) + read + (usage.cacheWrite ?? 0);
  return prompt ? 100 * read / prompt : null;
}

// After warm-up, a request that wrote more cache than it read, or paid more than this for uncached input,
// means the stable prefix was not reused.
export const CACHE_WARMUP_REQUESTS = 2;
export const UNCACHED_INPUT_ALARM_USD = 0.03;
export function cacheAlarm(usage: { cacheRead?: number; cacheWrite?: number }, settledRequests: number, inputUsd: number):
    { request: number; read: number; write: number; input_usd: number; reason: string } | undefined {
  const read = usage.cacheRead ?? 0, write = usage.cacheWrite ?? 0;
  if (settledRequests <= CACHE_WARMUP_REQUESTS) return undefined;
  const alarm = { request: settledRequests, read, write, input_usd: inputUsd };
  if (write > read) return { ...alarm, reason: "cache_write_over_read" };
  return inputUsd > UNCACHED_INPUT_ALARM_USD ? { ...alarm, reason: "uncached_input" } : undefined;
}
