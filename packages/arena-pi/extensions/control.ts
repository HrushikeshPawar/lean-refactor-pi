// The run-stop decision after a turn ends, as one pure function so its order is testable.
// D42 (owner): before the final tenth of spend only real failures and the spend limit end a run.
// A turn without work then moves the focus to a new starting point; the spend limit bounds the cost.

export const MAX_CONTINUATIONS = 12;

export type StopInput = {
  limitHit: boolean; finishConfirmed: boolean; providerUnreachable: boolean; errorLoop: boolean;
  continuations: number; noWorkTurns: number; plateau: number;
  noWorkThisTurn: boolean; finishAllowed: boolean;
};

export function stopDecision(input: StopInput): { stop: string | null; moveFocus: boolean } {
  const stop = input.limitHit ? "limit_reached"
    : input.finishConfirmed ? "finished"
    : input.providerUnreachable ? "provider_unreachable"
    : input.errorLoop ? "error_loop"
    : input.finishAllowed && input.continuations >= MAX_CONTINUATIONS ? "continuation_limit"
    : input.finishAllowed && input.noWorkTurns >= 2 ? "no_work_fallback"
    : input.continuations >= 4 && input.plateau >= 4 && input.finishAllowed ? "plateau" : null;
  return { stop, moveFocus: stop === null && input.noWorkThisTurn && !input.finishAllowed };
}
