import assert from "node:assert/strict";
import test from "node:test";
import { stopDecision, type StopInput } from "./control.ts";

const base: StopInput = { limitHit: false, finishTurn: false, providerUnreachable: false, errorLoop: false,
  continuations: 0, noWorkTurns: 0, plateau: 0, stallUsd: 0, limitUsd: 0.5, remainingFraction: 1,
  noWorkThisTurn: false, finishAllowed: false, doneTurn: false };

test("no work before the final tenth moves focus and does not stop", () => {
  assert.deepEqual(stopDecision({ ...base, continuations: 2, noWorkTurns: 1, noWorkThisTurn: true }), { stop: null, moveFocus: true, restart: false, island: false });
});

test("no run of no-work turns ends the run before the final tenth (D42)", () => {
  assert.deepEqual(stopDecision({ ...base, continuations: 40, noWorkTurns: 40, noWorkThisTurn: true }), { stop: null, moveFocus: false, restart: true, island: false });
  assert.equal(stopDecision({ ...base, continuations: 12, noWorkTurns: 1, noWorkThisTurn: true }).stop, null);
});

test("inside the final tenth the old stops apply and no focus move is requested", () => {
  const late = { ...base, finishAllowed: true };
  assert.deepEqual(stopDecision({ ...late, noWorkTurns: 2, noWorkThisTurn: true }), { stop: "no_work_fallback", moveFocus: false, restart: false, island: false });
  assert.equal(stopDecision({ ...late, continuations: 12 }).stop, "continuation_limit");
});

test("plateau stops only inside the final tenth and restarts before it", () => {
  assert.equal(stopDecision({ ...base, continuations: 6, plateau: 5 }).stop, null);
  assert.deepEqual(stopDecision({ ...base, continuations: 8, plateau: 6, stallUsd: 0.06 }), { stop: null, moveFocus: false, restart: true, island: false });
  assert.equal(stopDecision({ ...base, continuations: 8, plateau: 6, stallUsd: 0 }).restart, false);
  assert.equal(stopDecision({ ...base, continuations: 6, plateau: 5, finishAllowed: true }).stop, "plateau");
});

test("real failures and the spend limit stop at any spend", () => {
  assert.equal(stopDecision({ ...base, limitHit: true }).stop, "limit_reached");
  assert.equal(stopDecision({ ...base, errorLoop: true }).stop, "error_loop");
  assert.equal(stopDecision({ ...base, providerUnreachable: true }).stop, "provider_unreachable");
});

test("a turn ending in text opens a new island before the final tenth and finishes inside it", () => {
  assert.deepEqual(stopDecision({ ...base, doneTurn: true, noWorkThisTurn: true, noWorkTurns: 1 }),
    { stop: null, moveFocus: false, restart: true, island: true });
  assert.equal(stopDecision({ ...base, doneTurn: true, finishTurn: true, finishAllowed: true }).stop, "finished");
  // Under a fifth of the limit left, no island opens.
  assert.equal(stopDecision({ ...base, doneTurn: true, remainingFraction: 0.15 }).island, false);
});
