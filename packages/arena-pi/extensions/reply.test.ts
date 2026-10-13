import assert from "node:assert/strict";
import test from "node:test";
import { renderReply } from "./reply.ts";

test("renders facts, ordered item lines, map, handles and footer while retaining the payload", async () => {
  const reply = { ok: true, facts: ["fact"], items: [
    { ref: "n1", lines: ["first", "second"] },
    { ref: "n2", ok: false, lines: [], error: { code: "invalid" } },
  ], map: ["best", "recent"], handles: ["decl:Core.a"] };
  const result = await renderReply(reply, "budget footer");
  assert.deepEqual(result.content.map(part => part.text), ["fact\nfirst\nsecond\ninvalid\nbest\nrecent\nhandles: decl:Core.a\nbudget footer"]);
  assert.equal(result.details, reply);
  assert.equal(result.isError, false);
});

test("omits an empty handles line and marks only a top-level failure as an error", async () => {
  const itemFailure = await renderReply({ ok: true, facts: [], items: [{ ok: false, lines: [], error: { code: "bad" } }] }, "");
  assert.equal(itemFailure.content[0]?.text, "bad");
  assert.equal(itemFailure.isError, false);
  const failure = await renderReply({ ok: false, error: { code: "bad" }, facts: [], items: [] }, "");
  assert.equal(failure.isError, true);
});

test("renders empty-argument replies with the tool's valid keys", async () => {
  const result = await renderReply({ ok: false, error: { code: "empty_arguments" }, facts: [], items: [] }, "", ["drafts", "check"]);
  assert.match(result.content[0]?.text ?? "", /arrived empty or malformed/);
  assert.match(result.content[0]?.text ?? "", /drafts, check/);
});
