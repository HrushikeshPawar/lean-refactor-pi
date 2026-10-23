import assert from "node:assert/strict";
import { test } from "node:test";
import { messageSize, StreamWatchdog } from "./watchdog.ts";

test("messageSize sums text, thinking and tool arguments and survives odd shapes", () => {
  assert.equal(messageSize(undefined), 0);
  assert.equal(messageSize({ content: "x" }), 0);
  assert.equal(messageSize({ content: [null, 3, { type: "text", text: "abc" }, { thinking: "de" }] }), 5);
  assert.equal(messageSize({ content: [{ type: "toolCall", partialJson: '{"a":', arguments: {} }] }), 5);
  assert.equal(messageSize({ content: [{ type: "toolCall", arguments: { a: 1 } }] }), 7);
  assert.ok(messageSize({ content: [{ text: "abcd" }] }) > messageSize({ content: [{ text: "abc" }] }));
});

function fake() {
  let time = 0;
  const pending: { at: number; fn: () => void }[] = [];
  return {
    timers: {
      now: () => time,
      setTimeout: (fn: () => void, ms: number) => { const item = { at: time + ms, fn }; pending.push(item); return item; },
      clearTimeout: (handle: unknown) => { const i = pending.indexOf(handle as any); if (i >= 0) pending.splice(i, 1); },
    },
    advance(ms: number) {
      const end = time + ms;
      for (;;) {
        pending.sort((a, b) => a.at - b.at);
        const next = pending[0];
        if (!next || next.at > end) break;
        pending.shift();
        time = next.at;
        next.fn();
      }
      time = end;
    },
    pending,
  };
}

test("fires once after the idle window without progress", () => {
  const clock = fake();
  const calls: number[] = [];
  const dog = new StreamWatchdog(180_000, seconds => calls.push(seconds), clock.timers);
  dog.arm();
  clock.advance(179_000);
  assert.deepEqual(calls, []);
  clock.advance(2_000);
  assert.deepEqual(calls, [180]);
  clock.advance(600_000);
  assert.deepEqual(calls, [180]);
});

test("progress postpones the abort", () => {
  const clock = fake();
  const calls: number[] = [];
  const dog = new StreamWatchdog(100_000, seconds => calls.push(seconds), clock.timers);
  dog.arm();
  clock.advance(90_000);
  dog.touch();
  clock.advance(90_000);
  assert.deepEqual(calls, []);
  clock.advance(10_000);
  assert.deepEqual(calls, [100]);
});

test("clear cancels and leaves no timer; a disabled watchdog never arms", () => {
  const clock = fake();
  const calls: number[] = [];
  const dog = new StreamWatchdog(100_000, seconds => calls.push(seconds), clock.timers);
  dog.arm();
  dog.clear();
  assert.equal(clock.pending.length, 0);
  clock.advance(500_000);
  assert.deepEqual(calls, []);
  const off = new StreamWatchdog(0, seconds => calls.push(seconds), clock.timers);
  off.arm();
  assert.equal(clock.pending.length, 0);
});

test("re-arming for a new request replaces the old timer", () => {
  const clock = fake();
  const calls: number[] = [];
  const dog = new StreamWatchdog(100_000, seconds => calls.push(seconds), clock.timers);
  dog.arm();
  clock.advance(50_000);
  dog.arm();
  assert.equal(clock.pending.length, 1);
  clock.advance(60_000);
  assert.deepEqual(calls, []);
  clock.advance(40_000);
  assert.deepEqual(calls, [100]);
});
