// The run-stop decision after a turn ends. A text-only turn, a plateau, turns without work, and any
// continuation count continue. Only the actual-cost limit and provider, usage, or error failures stop.

export type StopInput = {
  limitHit: boolean;
  providerUnreachable: boolean;
  errorLoop: boolean;
  usageLimit?: boolean;
};

export function stopDecision(input: StopInput): string | null {
  if (input.limitHit) return "limit_reached";
  if (input.usageLimit) return "usage_limit";
  if (input.providerUnreachable) return "provider_unreachable";
  if (input.errorLoop) return "error_loop";
  return null;
}
