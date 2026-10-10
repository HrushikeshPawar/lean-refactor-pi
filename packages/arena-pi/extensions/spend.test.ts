import assert from "node:assert/strict";
import test from "node:test";
import { callCost, finishAllowed, limitReached, limitUsd, spendFooter, toolsForSpend } from "./spend.ts";

test("the limit defaults to fifty cents and anything above two dollars is refused at startup", () => {
  assert.equal(limitUsd({}), 0.5);
  assert.equal(limitUsd({ ARENA_LIMIT_USD: "2" }), 2);
  assert.throws(() => limitUsd({ ARENA_LIMIT_USD: "2.01" }), /above the maximum/);
  assert.throws(() => limitUsd({ ARENA_LIMIT_USD: "0" }), /positive/);
  assert.throws(() => limitUsd({ ARENA_LIMIT_USD: "abc" }), /positive/);
});

test("the run stops exactly when spend reaches the limit, not before", () => {
  assert.equal(limitReached(0.4999, 0.5), false);
  assert.equal(limitReached(0.5, 0.5), true);
  assert.equal(limitReached(0.61, 0.5), true);
});

test("finish becomes available once ten percent or less of the limit is left", () => {
  assert.equal(finishAllowed(0.44, 0.5).allowed, false);
  assert.equal(finishAllowed(0.45, 0.5).allowed, true);
  assert.equal(finishAllowed(0.7, 0.5).remainingUsd, 0);
  assert.equal(finishAllowed(0, 2).allowed, false);
});

test("the finish tool is listed only when allowed, and never twice", () => {
  assert.deepEqual(toolsForSpend(["a", "arena_finish", "b"], "arena_finish", false), ["a", "b"]);
  assert.deepEqual(toolsForSpend(["a", "b"], "arena_finish", true), ["a", "b", "arena_finish"]);
  assert.deepEqual(toolsForSpend(["a", "arena_finish"], "arena_finish", true), ["a", "arena_finish"]);
});

test("a call without a usable cost adds nothing", () => {
  assert.equal(callCost({ cost: { total: 0.0123 } }), 0.0123);
  assert.equal(callCost(undefined), 0);
  assert.equal(callCost({ cost: { total: Number.NaN } }), 0);
  assert.equal(callCost({ cost: { total: -1 } }), 0);
});

test("the footer states spend and percent left", async () => {
  assert.ok((await spendFooter(0.125, 0.5)).startsWith("budget:"));
  assert.ok((await spendFooter(0.7, 0.5)).startsWith("budget:"));
});
