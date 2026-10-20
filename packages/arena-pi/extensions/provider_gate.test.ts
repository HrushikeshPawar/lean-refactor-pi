import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DispatchDenied, guardProvider, installDispatchGate, pythonDispatch, readSharedSpend, settleProviderUsage, type SharedSpend } from "./provider_gate.ts";

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
  let crossing: SharedSpend | undefined;
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
      crossing = await settleProviderUsage(directory, identity, [requestId], { cost: { total: 0.1 } });
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
    assert.notEqual(guardProvider({
      providerId: "stub", api: "openai-completions", config, stream, open, identity: () => identity,
    }), guarded);
    const registrations: Record<string, unknown>[] = [];
    const installed = new Set<string>();
    const install = (session: string, installed: Set<string>) => installDispatchGate({
      register: (_name, config) => { registrations.push(config); },
      lookup: () => ({ streamSimple: stream }),
      providers: [{ name: "stub", api: "openai-completions" }],
      open, installed, identity: () => ({ ...identity, sessionId: session }),
    });
    install("first-session", installed);
    install("first-session", installed);
    install("second-session", new Set());
    assert.equal(registrations.length, 2);
    assert.notEqual(registrations[0], registrations[1]);
    assert.throws(() => installDispatchGate({
      register: () => {}, lookup: () => undefined,
      providers: [{ name: "missing", api: "missing" }],
      open, installed, identity: () => identity,
    }), /no stream adapter/);

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
    await settleProviderUsage(directory, identity, ["ordinary"], { cost: { total: 0.9 } });
    await run("context_recovery");
    await settleProviderUsage(directory, identity, ["context_recovery"], { cost: { total: 1 } });
    await run("compaction");
    await settleProviderUsage(directory, identity, ["compaction"], { cost: { total: 0.4 } });
    const below = await readSharedSpend(directory);
    assert.equal(below.stopped, false);
    assert.equal(below.total, "2.3");
    const zero = await settleProviderUsage(directory, identity, ["known-zero"], { cost: { total: 0 } });
    assert.equal(zero.accounting, "known");
    const unknown = await settleProviderUsage(directory, identity, ["missing-usage"], {});
    assert.equal(unknown.accounting, "unknown");
    const grouped = await settleProviderUsage(directory, identity, ["group-first", "group-last"], { cost: { total: 0.1 } });
    assert.equal(grouped.total, "2.4");
    await assert.rejects(settleProviderUsage(directory, identity, ["group-last"], { cost: { total: 1 } }), /operation_conflict/);

    let syncInvocations = 0;
    const recoveryDirectory = mkdtempSync(join(tmpdir(), "v8-dispatch-recovery-"));
    try {
      const recovering = pythonDispatch(recoveryDirectory);
      await assert.rejects(recovering({ ...identity, requestId: "lost-ack", attemptId: "lost-ack#1" }, () => {
        syncInvocations += 1;
        throw new Error("invocation acknowledgement failed");
      }), /invocation acknowledgement failed/);
      await assert.rejects(recovering({ ...identity, requestId: "retry-new-id", attemptId: "retry-new-id#1" }, async () => {
        syncInvocations += 1;
      }), (error: unknown) => {
        assert.ok(error instanceof DispatchDenied);
        assert.equal(error.category, "recovery_required");
        return true;
      });
      assert.equal(syncInvocations, 1);
    } finally {
      rmSync(recoveryDirectory, { recursive: true, force: true });
    }

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
    assert.equal(crossing?.stopped, true);
    assert.equal(crossing?.stop_reason, "spend_threshold");
    assert.equal(crossing?.total, "2.5");
    const replayed = await settleProviderUsage(directory, identity, ["retry"], { cost: { total: 0.1 } });
    assert.equal(replayed.total, "2.5");
    assert.equal((await readSharedSpend(directory)).stopped, true);
  } finally {
    globalThis.fetch = originalFetch;
    rmSync(directory, { recursive: true, force: true });
  }
});
