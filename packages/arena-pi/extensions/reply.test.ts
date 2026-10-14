import assert from "node:assert/strict";
import test from "node:test";
import { renderReply } from "./reply.ts";

test("renders facts, ordered item lines, map, handles and footer while retaining the payload", async () => {
  const reply = { ok: true, facts: ["fact"], items: [
    { ref: "n1", lines: ["first", "second"] },
    { ref: "n2", ok: false, lines: [], error: { code: "invalid_draft", input: "7", valid: ["nonempty string"], forms: ["drafts[1..N]"] } },
  ], map: ["best", "recent"], handles: ["decl:Core.a"] };
  const result = await renderReply(reply, "budget footer");
  assert.deepEqual(result.content.map(part => part.text), ["fact\nfirst\nsecond\ninvalid_draft: 7. Valid values: nonempty string. Forms: drafts[1..N].\nbest\nrecent\nhandles: decl:Core.a\nbudget footer"]);
  assert.equal(result.details, reply);
  assert.equal(result.isError, false);
});

test("omits an empty handles line and marks only a top-level failure as an error", async () => {
  const itemFailure = await renderReply({ ok: true, facts: [], items: [{ ok: false, lines: [], error: { code: "bad" } }] }, "");
  assert.equal(itemFailure.content[0]?.text, "bad: none. Forms: none.");
  assert.equal(itemFailure.isError, false);
  const failure = await renderReply({ ok: false, error: { code: "bad" }, facts: [], items: [] }, "");
  assert.equal(failure.isError, true);
});

test("renders a top-level error with its valid values and forms", async () => {
  const result = await renderReply({ ok: false, facts: [], items: [], error: { code: "bad_target", input: "none",
    valid: ["one of handle, node, hole"], forms: ["handle:decl:<name>", "node:nN"] } }, "");
  const text = result.content[0]?.text ?? "";
  assert.match(text, /^bad_target: none\./);
  assert.match(text, /Valid values: one of handle, node, hole\./);
  assert.match(text, /Forms: handle:decl:<name>, node:nN\./);
});

test("renders empty-argument replies with the tool's valid keys", async () => {
  const result = await renderReply({ ok: false, error: { code: "empty_arguments" }, facts: [], items: [] }, "", ["drafts", "check"]);
  assert.match(result.content[0]?.text ?? "", /arrived empty or malformed/);
  assert.match(result.content[0]?.text ?? "", /drafts, check/);
});

test("an error input never doubles the template's period and an empty valid list is left out", async () => {
  const result = await renderReply({ ok: false, facts: [], items: [], error: { code: "unknown_handle",
    input: "X is not a declaration of the pinned project.", valid: [], forms: ["node:nN"] } }, "");
  assert.equal(result.content[0]?.text, "unknown_handle: X is not a declaration of the pinned project. Forms: node:nN.");
});
