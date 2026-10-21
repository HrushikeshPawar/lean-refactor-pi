import assert from "node:assert/strict";
import test from "node:test";
import { callCost, limitReached, limitUsd, spendFooter } from "./spend.ts";

test("the limit defaults to fifty cents and anything above two and a half dollars is refused at startup", () => {
  assert.equal(limitUsd({}), 0.5);
  assert.equal(limitUsd({ ARENA_LIMIT_USD: "2.5" }), 2.5);
  assert.throws(() => limitUsd({ ARENA_LIMIT_USD: "2.51" }), /above the maximum/);
  assert.throws(() => limitUsd({ ARENA_LIMIT_USD: "0" }), /positive/);
  assert.throws(() => limitUsd({ ARENA_LIMIT_USD: "abc" }), /positive/);
});

test("the run stops exactly when spend reaches the limit, not before", () => {
  assert.equal(limitReached(0.4999, 0.5), false);
  assert.equal(limitReached(0.5, 0.5), true);
  assert.equal(limitReached(0.61, 0.5), true);
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
