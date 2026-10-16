// The run-stop decision after a turn ends, as one pure function so its order is testable.
// D42 (owner): before the final tenth of spend only real failures and the spend limit end a run.
// A turn without work then moves the focus to a new starting point; the spend limit bounds the cost.

export const MAX_CONTINUATIONS = 12;
// A stalled run restarts at its next pause once the spend since the best last changed reaches this fraction of
// the limit (ski5: the best stood still from turn 39 and the no-work restart came at 53, with a fifth of the spend left).
export const STALL_RESTART_FRACTION = 0.12;
// No restart and no focus move once less than this fraction of the limit is left.
export const RESTART_MIN_REMAINING_FRACTION = 0.2;

export type StopInput = {
  limitHit: boolean; finishTurn: boolean; providerUnreachable: boolean; errorLoop: boolean;
  // The provider refused for a spent subscription window; the campaign moves the row to its fallback model.
  usageLimit?: boolean;
  continuations: number; noWorkTurns: number; plateau: number;
  // Spend since the best last changed (the run's whole spend before the first best).
  stallUsd: number; limitUsd: number;
  remainingFraction: number;
  noWorkThisTurn: boolean; finishAllowed: boolean;
  // The turn completed with visible text and no tool call: before the final tenth it opens a new island.
  doneTurn: boolean;
  // Harness-side: more tries after a stall nudge on the same route, no new best.
  stallDue?: boolean;
};

// A first turn without work moves the focus; a second one in a row, or a best that has not changed for
// STALL_RESTART_FRACTION of the limit, restarts the conversation from a packet.
export function stopDecision(input: StopInput): { stop: string | null; moveFocus: boolean; restart: boolean; island: boolean } {
  const stop = input.limitHit ? "limit_reached"
    : input.usageLimit ? "usage_limit"
    : input.finishTurn ? "finished"
    : input.providerUnreachable ? "provider_unreachable"
    : input.errorLoop ? "error_loop"
    : input.finishAllowed && input.continuations >= MAX_CONTINUATIONS ? "continuation_limit"
    : input.finishAllowed && input.noWorkTurns >= 2 ? "no_work_fallback"
    : input.continuations >= 4 && input.plateau >= 4 && input.finishAllowed ? "plateau" : null;
  const early = stop === null && !input.finishAllowed && input.remainingFraction >= RESTART_MIN_REMAINING_FRACTION;
  const island = early && input.doneTurn;
  const restart = early && (island || (input.noWorkThisTurn && input.noWorkTurns >= 2)
    || input.stallUsd >= STALL_RESTART_FRACTION * input.limitUsd || input.stallDue === true);
  return { stop, moveFocus: early && input.noWorkThisTurn && input.noWorkTurns < 2 && !restart, restart, island };
}
