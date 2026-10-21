import assert from "node:assert/strict";
import test from "node:test";
import { stopDecision, type StopInput } from "./control.ts";

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
