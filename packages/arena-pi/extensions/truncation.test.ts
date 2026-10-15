import assert from "node:assert/strict";
import { test } from "node:test";
import { buildTurnCutLine } from "./truncation.ts";
import { clearCache, render } from "./text.ts";

test("renders the cut-turn line from the shared message template", async () => {
  clearCache();
  const template = await render("messages/errors.turn_cut", { tokens: "{tokens}" });
  assert.equal(buildTurnCutLine(64000, template), "The last turn was cut at 64000 output tokens before any tool call. The next turn should call a tool before long reasoning.");
});
