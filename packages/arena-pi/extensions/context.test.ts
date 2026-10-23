import assert from "node:assert/strict";
import test from "node:test";
import { turnContext } from "./context.ts";

test("parallel tool calls merge into one message: sections by header in first-seen order, identical lines once", () => {
  const first = { sections: [["## Updates", "update a", "update b"], ["## Cards", "card 1"]], kinds: ["updates", "cards"] };
  const second = { sections: [["## Updates", "update b", "update c"], ["## Map", "best n1"]], kinds: ["updates", "map"] };
  const message = turnContext([first, second]);
  assert.deepEqual(message, {
    content: "## Updates\nupdate a\nupdate b\nupdate c\n## Cards\ncard 1\n## Map\nbest n1",
    kinds: ["updates", "cards", "map"],
  });
});

test("the spend line comes last, after a blank line, and is recorded as a kind", () => {
  const message = turnContext([{ sections: [["", "Plan missing."]], kinds: ["plan_missing"] }], "budget: $0.10 of $2.50");
  assert.deepEqual(message, { content: "Plan missing.\n\nbudget: $0.10 of $2.50", kinds: ["plan_missing", "spend"] });
});

test("a turn with nothing new and no spend line sends nothing", () => {
  assert.equal(turnContext([]), undefined);
  assert.equal(turnContext([{ sections: [["## Cards"]], kinds: [] }]), undefined);
  assert.equal(turnContext([{}], ""), undefined);
});

test("spend alone is a message", () => {
  assert.deepEqual(turnContext([], "budget: x"), { content: "budget: x", kinds: ["spend"] });
});
