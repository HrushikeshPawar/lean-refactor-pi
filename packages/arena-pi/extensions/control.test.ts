import assert from "node:assert/strict";
import test from "node:test";
import { MAX_NO_WORK_TURNS, stopDecision, type StopInput } from "./control.ts";

const base: StopInput = { limitHit: false, finishConfirmed: false, providerUnreachable: false, errorLoop: false,
  continuations: 0, noWorkTurns: 0, plateau: 0, noWorkThisTurn: false, finishAllowed: false };

test("no work before the final tenth moves focus and does not stop", () => {
  assert.deepEqual(stopDecision({ ...base, continuations: 2, noWorkTurns: 2, noWorkThisTurn: true }), { stop: null, moveFocus: true });
});

test("a long run of no-work turns before the final tenth still stops, and continuation count alone does not", () => {
  assert.equal(stopDecision({ ...base, continuations: 5, noWorkTurns: MAX_NO_WORK_TURNS, noWorkThisTurn: true }).stop, "no_work_fallback");
  assert.equal(stopDecision({ ...base, continuations: 12, noWorkTurns: 1, noWorkThisTurn: true }).stop, null);
});

test("inside the final tenth the old stops apply and no focus move is requested", () => {
  const late = { ...base, finishAllowed: true };
  assert.deepEqual(stopDecision({ ...late, noWorkTurns: 2, noWorkThisTurn: true }), { stop: "no_work_fallback", moveFocus: false });
  assert.equal(stopDecision({ ...late, continuations: 12 }).stop, "continuation_limit");
});

test("plateau stops only inside the final tenth", () => {
  assert.equal(stopDecision({ ...base, continuations: 6, plateau: 5 }).stop, null);
  assert.equal(stopDecision({ ...base, continuations: 6, plateau: 5, finishAllowed: true }).stop, "plateau");
});

test("real failures and the spend limit stop at any spend", () => {
  assert.equal(stopDecision({ ...base, limitHit: true }).stop, "limit_reached");
  assert.equal(stopDecision({ ...base, errorLoop: true }).stop, "error_loop");
  assert.equal(stopDecision({ ...base, providerUnreachable: true }).stop, "provider_unreachable");
});
