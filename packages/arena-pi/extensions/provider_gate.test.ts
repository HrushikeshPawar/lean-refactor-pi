import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { callRunControl, DispatchDenied, guardProvider, pythonDispatch } from "./provider_gate.ts";

const identity = {
  runId: "run-1",
  actorId: "sol",
  sessionId: "sol-session",
  jobId: "sol-job",
};

test("v8_dispatch_stop", async () => {
  const directory = mkdtempSync(join(tmpdir(), "v8-dispatch-"));
  const fetches: string[] = [];
  const payloads: unknown[] = [];
  const auths: string[] = [];
  let requestId = "";
  let crossing: { stopped?: boolean; total?: string; stop_reason?: string } = {};
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => {
    throw new Error("global fetch must not run");
  };
  try {
    const models = [{ id: "stub", name: "stub" }];
    const oauth = { getApiKey: () => "kept-secret" };
    const stream = async (_model: unknown, _context: unknown, options: Record<string, unknown> = {}) => {
      const path = String(options.path ?? "");
      payloads.push(await (options.onPayload as (payload: unknown) => unknown)({ path }));
      auths.push(oauth.getApiKey());
      const fetch = options.fetch as (input: string) => Promise<unknown>;
      if (path === "transport_error") {
        await fetch(path);
        return;
      }
      if (path !== "retry") {
        await fetch(path);
        return;
      }
      await fetch("retry-1");
      crossing = await callRunControl(directory, "settle_usage", settlement(requestId, "0.10", 0.1));
      payloads.push(await (options.onPayload as (payload: unknown) => unknown)({ path: "retry-2" }));
      auths.push(oauth.getApiKey());
      await fetch("retry-2");
    };
    const open = pythonDispatch(directory);
    const config = { api: "openai-completions", models, oauth, headers: { "X-Keep": "1" }, baseUrl: "http://stub" };
    const guarded = guardProvider({
      providerId: "stub",
      api: "openai-completions",
      config,
      stream,
      open,
      identity: () => ({ ...identity, requestId }),
    });
    assert.equal(guarded.models, models);
    assert.equal(guarded.oauth, oauth);
    assert.equal(guarded.headers, config.headers);
    assert.equal(guardProvider({
      providerId: "stub", api: "openai-completions", config, stream, open, identity: () => identity,
    }), guarded);

    const run = async (path: string) => {
      requestId = path;
      const fetch = async (input: string) => {
        fetches.push(input);
        if (input === "transport_error") throw new Error("socket reset");
        return { ok: true, input };
      };
      await (guarded.streamSimple as typeof stream)({}, {}, {
        path,
        fetch,
        onPayload: (payload: unknown) => payload,
      });
    };

    await run("ordinary");
    await callRunControl(directory, "settle_usage", settlement("ordinary", "1.00", 1));
    await run("context_recovery");
    await callRunControl(directory, "settle_usage", settlement("context_recovery", "1.00", 1));
    await run("compaction");
    await callRunControl(directory, "settle_usage", settlement("compaction", "0.40", 0.4));
    const below = await callRunControl(directory, "begin_dispatch", {
      request_id: "estimate-must-not-stop",
      attempt_id: "estimate-must-not-stop#1",
      run_id: identity.runId,
      actor_id: identity.actorId,
      session_id: identity.sessionId,
      job_id: identity.jobId,
      estimate_usd: "9.00",
    });
    assert.equal(below.admitted, true);
    assert.equal(below.sent, "uncertain");

    await assert.rejects(run("transport_error"), /socket reset/);
    await assert.rejects(run("retry"), (error: unknown) => {
      assert.ok(error instanceof DispatchDenied);
      assert.equal(error.category, "run_stopped");
      return true;
    });
    assert.deepEqual(fetches, ["ordinary", "context_recovery", "compaction", "transport_error", "retry-1"]);
    assert.deepEqual(auths, ["kept-secret", "kept-secret", "kept-secret", "kept-secret", "kept-secret", "kept-secret"]);
    assert.equal(payloads.length, auths.length);

    const rows = readFileSync(join(directory, "control.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    const dispatch = rows.filter((row) => row.kind === "dispatch");
    const started = dispatch.filter((row) => row.attempt_id === "transport_error#1")[0];
    assert.equal(started.status, "dispatch_started");
    assert.equal(started.sent, "uncertain");
    const denied = dispatch.filter((row) => row.attempt_id === "retry#2")[0];
    assert.equal(denied.status, "rejected_before_dispatch");
    assert.equal(denied.sent, "unsent");
    assert.equal(denied.reason, "run_stopped");
    assert.equal(crossing.stopped, true);
    assert.equal(crossing.stop_reason, "spend_threshold");
    assert.equal(crossing.total, "2.50");
  } finally {
    globalThis.fetch = originalFetch;
    rmSync(directory, { recursive: true, force: true });
  }
});

function settlement(requestId: string, amount: string, total: number) {
  return {
    settlement_id: `settle-${requestId}`,
    run_id: identity.runId,
    actor_id: identity.actorId,
    session_id: identity.sessionId,
    job_id: identity.jobId,
    covered_request_ids: [requestId],
    state: "known",
    amount,
    usage: { cost: { total } },
  };
}
