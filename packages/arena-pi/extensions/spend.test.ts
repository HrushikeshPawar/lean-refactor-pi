import assert from "node:assert/strict";
import test from "node:test";
import { callCost, inPeak, limitReached, limitUsd, peakPriced, spendFooter } from "./spend.ts";

const PEAK = { multiplier: 2, weekdays: ["mon", "tue", "wed", "thu", "fri"], utc: ["01:00-04:00", "06:00-10:00"] };

test("peak windows are weekday UTC windows, start inclusive and end exclusive", () => {
  const at = (iso: string) => inPeak(PEAK, new Date(iso));
  assert.equal(at("2026-10-26T01:00:00Z"), true); // Monday 01:00
  assert.equal(at("2026-10-26T00:59:59Z"), false);
  assert.equal(at("2026-10-26T03:59:59Z"), true);
  assert.equal(at("2026-10-26T04:00:00Z"), false);
  assert.equal(at("2026-10-23T09:59:00Z"), true); // Friday 09:59
  assert.equal(at("2026-10-23T10:00:00Z"), false);
  assert.equal(at("2026-10-24T07:00:00Z"), false); // Saturday
  assert.equal(at("2026-10-25T02:00:00Z"), false); // Sunday
  assert.equal(inPeak(undefined, new Date("2026-10-26T02:00:00Z")), false);
});

test("a call sent at peak has every cost component scaled; off-peak calls are unchanged", () => {
  const usage = { input: 10, cost: { input: 0.001, output: 0.002, cacheRead: 0.0001, cacheWrite: 0, total: 0.0031 } };
  const atPeak = peakPriced(usage, PEAK, new Date("2026-10-26T02:00:00Z"));
  assert.equal(atPeak.multiplier, 2);
  assert.deepEqual(atPeak.usage?.cost, { input: 0.002, output: 0.004, cacheRead: 0.0002, cacheWrite: 0, total: 0.0062 });
  assert.equal(atPeak.usage?.input, 10);
  const offPeak = peakPriced(usage, PEAK, new Date("2026-10-24T02:00:00Z"));
  assert.equal(offPeak.multiplier, 1);
  assert.equal(offPeak.usage, usage);
  assert.equal(peakPriced(undefined, PEAK, new Date("2026-10-26T02:00:00Z")).usage, undefined);
});

test("the limit defaults to fifty cents and anything above two and a half dollars is refused at startup", () => {
  assert.equal(limitUsd({}), 2.5);
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
