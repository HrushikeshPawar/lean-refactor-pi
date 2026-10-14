// The run-stop decision after a turn ends, as one pure function so its order is testable.
// D42 (owner): before the final tenth of spend only real failures and the spend limit end a run.
// A turn without work then moves the focus to a new starting point; the spend limit bounds the cost.

export const MAX_CONTINUATIONS = 12;
// Model turns without a change in the best before a stalled run restarts at its next pause (ski5: the best stood
// still from turn 39 and the no-work restart came at 53, with a fifth of the spend left).
export const STALL_RESTART = 8;

export type StopInput = {
  limitHit: boolean; finishConfirmed: boolean; providerUnreachable: boolean; errorLoop: boolean;
  continuations: number; noWorkTurns: number; plateau: number;
  // Model turns since the best changed, counted only once a best exists (0 before the first scored proof).
  bestPlateau: number;
  noWorkThisTurn: boolean; finishAllowed: boolean;
};

// A first turn without work moves the focus; a second one in a row, or a best that has not changed for
// STALL_RESTART model turns, restarts the conversation from a packet.
export function stopDecision(input: StopInput): { stop: string | null; moveFocus: boolean; restart: boolean } {
  const stop = input.limitHit ? "limit_reached"
    : input.finishConfirmed ? "finished"
    : input.providerUnreachable ? "provider_unreachable"
    : input.errorLoop ? "error_loop"
    : input.finishAllowed && input.continuations >= MAX_CONTINUATIONS ? "continuation_limit"
    : input.finishAllowed && input.noWorkTurns >= 2 ? "no_work_fallback"
    : input.continuations >= 4 && input.plateau >= 4 && input.finishAllowed ? "plateau" : null;
  const early = stop === null && !input.finishAllowed;
  const restart = early && ((input.noWorkThisTurn && input.noWorkTurns >= 2) || input.bestPlateau >= STALL_RESTART);
  return { stop, moveFocus: early && input.noWorkThisTurn && input.noWorkTurns < 2 && !restart, restart };
}
