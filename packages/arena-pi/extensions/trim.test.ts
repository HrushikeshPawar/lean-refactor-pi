import assert from "node:assert/strict";
import test from "node:test";
import { render } from "./text.ts";
import { nothingToSummarize, objectToolArguments, ResultTrimmer } from "./trim.ts";

const context = "# Pinned source\n".repeat(40);

test("repeated identical search and read results become stubs until compaction", async () => {
  const trimmer = new ResultTrimmer();
  const stub = await render("messages/trim.result_stub");
  assert.equal(await trimmer.trim("search", { queries: ["Core.a"] }, context), context);
  assert.equal(await trimmer.trim("search", { queries: ["Core.a"] }, context), stub);
  assert.equal(await trimmer.trim("read", { node: "n1" }, context), context);
  assert.equal(await trimmer.trim("read", { node: "n1" }, context), stub);
  assert.doesNotMatch(stub, /[{}]/);
  trimmer.forget();
  assert.equal(await trimmer.trim("read", { node: "n1" }, context), context);
});

test("compile and goal results are never stubbed", async () => {
  const trimmer = new ResultTrimmer();
  for (const name of ["compile", "goal", "finish"]) {
    await trimmer.trim(name, {}, context);
    assert.equal(await trimmer.trim(name, {}, context), context);
  }
});

test("tool calls with unparsed arguments get an object before compaction", () => {
  const messages = [{ role: "user", content: "x" },
    { role: "assistant", content: [{ type: "toolCall", name: "compile", arguments: null }, { type: "text", text: "t" },
      { type: "toolCall", name: "read", arguments: { node: "n1" } }] }];
  assert.equal(objectToolArguments(messages), 1);
  assert.deepEqual((messages[1].content as Array<{ arguments?: unknown }>).map(block => block.arguments), [{}, undefined, { node: "n1" }]);
  assert.equal(objectToolArguments(undefined), 0);
});

test("a compaction with no history to summarize is skipped", () => {
  assert.equal(nothingToSummarize({ messagesToSummarize: [], turnPrefixMessages: [] }), true);
  assert.equal(nothingToSummarize({ messagesToSummarize: [{ role: "user" }], turnPrefixMessages: [] }), false);
  assert.equal(nothingToSummarize({ messagesToSummarize: [], turnPrefixMessages: [{ role: "assistant" }] }), false);
  assert.equal(nothingToSummarize({}), true);
});
