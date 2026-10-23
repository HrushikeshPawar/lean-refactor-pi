import assert from "node:assert/strict";
import test from "node:test";
import { MAX_UNKNOWN_USAGE_STREAK, stopDecision, type StopInput } from "./control.ts";

const open: StopInput = { limitHit: false, providerUnreachable: false, errorLoop: false, usageLimit: false };

test("a text-only turn, plateau, no-work turns and many continuations do not stop below the limit", () => {
  assert.equal(stopDecision(open), null);
});

test("the actual-cost limit and provider, usage and error failures each stop with their own reason", () => {
  assert.equal(stopDecision({ ...open, limitHit: true, usageLimit: true, providerUnreachable: true, errorLoop: true }), "limit_reached");
  assert.equal(stopDecision({ ...open, usageLimit: true, providerUnreachable: true, errorLoop: true }), "usage_limit");
  assert.equal(stopDecision({ ...open, providerUnreachable: true, errorLoop: true }), "provider_unreachable");
  assert.equal(stopDecision({ ...open, errorLoop: true }), "error_loop");
});

test("a short streak of unknown-usage settles stops as accounting_unknown, below the cost limit", () => {
  assert.equal(stopDecision({ ...open, unknownUsageStreak: MAX_UNKNOWN_USAGE_STREAK - 1 }), null);
  assert.equal(stopDecision({ ...open, unknownUsageStreak: MAX_UNKNOWN_USAGE_STREAK }), "accounting_unknown");
  assert.equal(stopDecision({ ...open, unknownUsageStreak: MAX_UNKNOWN_USAGE_STREAK, limitHit: true }), "limit_reached");
});
