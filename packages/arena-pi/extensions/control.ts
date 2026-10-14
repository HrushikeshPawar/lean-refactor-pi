// The run-stop decision after a turn ends, as one pure function so its order is testable.
// D42: before the final tenth of spend only real failures, the spend limit and a no-progress loop end a run.

/** Consecutive no-work turns tolerated before the final tenth. Each one moves focus to a new starting point,
 *  so six gives five fresh starts; each turn costs a request, so it also bounds money burned with no progress. */
export const MAX_NO_WORK_TURNS = 6;
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
    : input.noWorkTurns >= (input.finishAllowed ? 2 : MAX_NO_WORK_TURNS) ? "no_work_fallback"
    : input.continuations >= 4 && input.plateau >= 4 && input.finishAllowed ? "plateau" : null;
  return { stop, moveFocus: stop === null && input.noWorkThisTurn && !input.finishAllowed };
}
