// The run-stop decision after a turn ends. A text-only turn, a plateau, turns without work, and any
// continuation count continue. Only the actual-cost limit and provider, usage, or error failures stop.

// Consecutive completed Sol turns whose usage is unknown. Unknown is never zero, so the shared total cannot
// grow and the actual-cost stop would never arrive; this many in a row is an accounting failure.
export const MAX_UNKNOWN_USAGE_STREAK = 3;

export type StopInput = {
  limitHit: boolean;
  providerUnreachable: boolean;
  errorLoop: boolean;
  usageLimit?: boolean;
  unknownUsageStreak?: number;
};

export function stopDecision(input: StopInput): string | null {
  if (input.limitHit) return "limit_reached";
  if (input.usageLimit) return "usage_limit";
  if (input.providerUnreachable) return "provider_unreachable";
  if (input.errorLoop) return "error_loop";
  if ((input.unknownUsageStreak ?? 0) >= MAX_UNKNOWN_USAGE_STREAK) return "accounting_unknown";
  return null;
}
