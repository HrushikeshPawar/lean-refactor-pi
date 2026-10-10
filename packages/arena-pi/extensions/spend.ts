// The spend rule: after every LLM call the call's actual cost (Pi's `usage.cost.total`) is added to the
// run total. At or above the limit the agent stops. No estimates, no reservations; the call that crosses
// the limit may overshoot it, and that is accepted.
export const DEFAULT_LIMIT_USD = 0.5;
export const MAX_LIMIT_USD = 2;
// The model may finish only when at most this fraction of the limit is left. Before that the finish tool
// is not offered at all.
export const FINISH_REMAINING_FRACTION = 0.10;

export function limitUsd(env: NodeJS.ProcessEnv = process.env): number {
  const limit = Number(env.ARENA_LIMIT_USD ?? String(DEFAULT_LIMIT_USD));
  if (!Number.isFinite(limit) || limit <= 0) throw new Error(`Arena spend limit must be a positive number of dollars, got ${env.ARENA_LIMIT_USD}`);
  if (limit > MAX_LIMIT_USD) throw new Error(`Arena spend limit $${limit} is above the maximum of $${MAX_LIMIT_USD}`);
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

export function finishAllowed(spentUsd: number, limit: number) {
  const remainingUsd = Math.max(0, limit - spentUsd);
  const remainingFraction = limit > 0 ? remainingUsd / limit : 0;
  return { allowed: remainingFraction <= FINISH_REMAINING_FRACTION + 1e-12, remainingUsd, remainingFraction };
}

/** One factual footer line: spend against the limit. No advice. */
export function spendFooter(spentUsd: number, limit: number): string {
  const left = limit > 0 ? Math.max(0, Math.round(100 * (1 - spentUsd / limit))) : 0;
  return `budget: $${spentUsd.toFixed(2)} of $${limit.toFixed(2)} spent · ${left}% left`;
}

/** The tool list with `finish` offered only when the finish rule allows it. */
export function toolsForSpend(active: readonly string[], finish: string, allowed: boolean): string[] {
  const rest = active.filter(name => name !== finish);
  return allowed ? [...rest, finish] : rest;
}

// Cache hit rate in the provider-standard sense: cache_read over every prompt token
// (input + cache_read + cache_write).
export function cacheHitPct(usage: { input?: number; cacheRead?: number; cacheWrite?: number }): number | null {
  const read = usage.cacheRead ?? 0;
  const prompt = (usage.input ?? 0) + read + (usage.cacheWrite ?? 0);
  return prompt ? 100 * read / prompt : null;
}

// A request that wrote more cache than it read after warm-up means the stable prefix was not reused.
export const CACHE_WARMUP_REQUESTS = 2;
export function cacheAlarm(usage: { cacheRead?: number; cacheWrite?: number }, settledRequests: number):
    { request: number; read: number; write: number } | undefined {
  const read = usage.cacheRead ?? 0, write = usage.cacheWrite ?? 0;
  return settledRequests > CACHE_WARMUP_REQUESTS && write > read ? { request: settledRequests, read, write } : undefined;
}
