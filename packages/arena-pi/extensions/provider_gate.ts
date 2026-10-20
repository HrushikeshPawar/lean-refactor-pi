import { spawn } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../..");

export type DispatchAttempt = {
  requestId: string;
  attemptId: string;
  runId: string;
  actorId: string;
  sessionId: string;
  jobId?: string;
  generation?: string;
};

export type DispatchDecision = {
  ok: boolean;
  admitted: boolean;
  status: string;
  sent?: "unsent" | "uncertain";
  reason?: string | null;
  requestId?: string;
  attemptId?: string;
  reused?: boolean;
};

export class DispatchDenied extends Error {
  readonly category: string;
  readonly decision: DispatchDecision;

  constructor(decision: DispatchDecision) {
    super(decision.reason || decision.status);
    this.name = "DispatchDenied";
    this.category = decision.reason || decision.status;
    this.decision = decision;
  }
}

type Stream = (model: unknown, context: unknown, options?: Record<string, unknown>) => unknown;

export type GateIdentity = {
  runId: string;
  actorId: string;
  sessionId: string;
  requestId?: string;
  jobId?: string;
  generation?: string;
};

export type DispatchOpen = (
  attempt: DispatchAttempt,
  invoke: () => Promise<unknown>,
) => Promise<unknown>;

export function guardProvider(input: {
  providerId: string;
  api: string;
  config: Record<string, unknown>;
  stream: Stream;
  open: DispatchOpen;
  identity: () => GateIdentity;
}): Record<string, unknown> {
  const guarded: Record<string, unknown> = {
    ...input.config,
    api: input.api,
    streamSimple(model: unknown, context: unknown, options: Record<string, unknown> = {}) {
      let generated: string | undefined;
      let attempt = 0;
      const inner = (options.fetch as typeof fetch | undefined) ?? globalThis.fetch;
      const fetch = (request: Parameters<typeof globalThis.fetch>[0], init?: Parameters<typeof globalThis.fetch>[1]) => {
        // Read after onPayload. Pi assigns the journaled request id in before_provider_request,
        // which runs before fetch and after streamSimple starts.
        const current = input.identity();
        const requestId = current.requestId || (generated ??= `${Date.now()}-${Math.random().toString(36).slice(2)}`);
        attempt += 1;
        return input.open({
          requestId,
          attemptId: `${requestId}#${attempt}`,
          runId: current.runId,
          actorId: current.actorId,
          sessionId: current.sessionId,
          ...(current.jobId ? { jobId: current.jobId } : {}),
          ...(current.generation ? { generation: current.generation } : {}),
        }, () => inner(request, init));
      };
      return input.stream(model, context, { ...options, fetch });
    },
  };
  return guarded;
}

export function installDispatchGate(input: {
  register: (name: string, config: Record<string, unknown>) => void;
  lookup: (name: string) => { streamSimple?: Stream } | undefined;
  providers: Array<{ name: string; api?: string }>;
  open: DispatchOpen;
  identity: () => GateIdentity;
  installed: Set<string>;
}): void {
  for (const provider of input.providers) {
    if (!provider.api) throw new Error(`Selected provider ${provider.name} has no API`);
    const key = `${provider.name}/${provider.api}`;
    if (input.installed.has(key)) continue;
    const captured = input.lookup(provider.name);
    if (!captured?.streamSimple) throw new Error(`Selected provider ${provider.name} has no stream adapter`);
    input.register(provider.name, guardProvider({
      providerId: provider.name,
      api: provider.api,
      config: { api: provider.api },
      stream: captured.streamSimple.bind(captured),
      open: input.open,
      identity: input.identity,
    }));
    input.installed.add(key);
  }
}

export function callRunControl(directory: string, fn: string, payload?: Record<string, unknown>, cwd = root): Promise<Record<string, unknown>> {
  const code = [
    "import json, sys",
    "from pathlib import Path",
    "from arena import run_control",
    "args = [Path(sys.argv[2])] + ([json.loads(sys.argv[3])] if len(sys.argv) > 3 else [])",
    "print(json.dumps(getattr(run_control, sys.argv[1])(*args)))",
  ].join("\n");
  return new Promise((resolvePromise, reject) => {
    const child = spawn("uv", ["run", "--no-sync", "python", "-c", code, fn, directory, ...(payload === undefined ? [] : [JSON.stringify(payload)])], { cwd });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || stdout || `run_control ${fn} exited ${code}`));
        return;
      }
      try {
        const result: unknown = JSON.parse(stdout);
        if (!isRecord(result)) throw new Error(`Invalid run_control ${fn} response`);
        resolvePromise(result);
      } catch (error) {
        reject(error);
      }
    });
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type SharedSpend = {
  total: string;
  accounting: "known" | "unknown";
  stopped: boolean;
  stop_reason: string | null;
};

function sharedSpend(result: Record<string, unknown>): SharedSpend {
  if (result.ok !== true) throw new Error(`Shared spend ${String(result.status ?? "failed")}`);
  const { total, accounting, stopped, stop_reason } = result;
  if (typeof total !== "string" || !/^\d+(?:\.\d+)?$/.test(total)
    || (accounting !== "known" && accounting !== "unknown") || typeof stopped !== "boolean"
    || (stop_reason !== null && typeof stop_reason !== "string")) {
    throw new Error("Invalid shared spend response");
  }
  return { total, accounting, stopped, stop_reason };
}

export async function readSharedSpend(directory: string): Promise<SharedSpend> {
  return sharedSpend(await callRunControl(directory, "read_state"));
}

export async function settleProviderUsage(
  directory: string, identity: GateIdentity, coveredRequestIds: string[], usage: unknown,
): Promise<SharedSpend> {
  if (coveredRequestIds.length === 0 || coveredRequestIds.some((id) => !id)) {
    throw new Error("Settlement needs covered request IDs");
  }
  const attribution = {
    run_id: identity.runId,
    actor_id: identity.actorId,
    session_id: identity.sessionId,
    ...(identity.jobId ? { job_id: identity.jobId } : {}),
  };
  for (const requestId of coveredRequestIds) {
    const prepared = await callRunControl(directory, "prepare_request", { ...attribution, request_id: requestId });
    if (prepared.ok !== true) throw new Error(`Prepare request ${String(prepared.status ?? "failed")}`);
  }
  const cost = isRecord(usage) && isRecord(usage.cost) ? usage.cost.total : undefined;
  const amount = typeof cost === "number" && Number.isFinite(cost) && cost >= 0 ? String(cost)
    : typeof cost === "string" && /^\d+(?:\.\d+)?$/.test(cost) ? cost : null;
  return sharedSpend(await callRunControl(directory, "settle_usage", {
    ...attribution,
    settlement_id: `settle:${coveredRequestIds.at(-1)}`,
    covered_request_ids: coveredRequestIds,
    state: amount === null ? "unknown" : "known",
    ...(amount === null ? {} : { amount }),
    usage: usage ?? null,
  }));
}

function attemptRecord(attempt: DispatchAttempt): Record<string, unknown> {
  return {
    request_id: attempt.requestId,
    attempt_id: attempt.attemptId,
    run_id: attempt.runId,
    actor_id: attempt.actorId,
    session_id: attempt.sessionId,
    ...(attempt.jobId ? { job_id: attempt.jobId } : {}),
    ...(attempt.generation ? { generation: attempt.generation } : {}),
  };
}

const serveDispatch = [
  "import json, sys",
  "from pathlib import Path",
  "from arena.run_control import serve_dispatch",
  "def acknowledge():",
  "    sys.stdout.write(json.dumps({'ready': True}) + '\\n')",
  "    sys.stdout.flush()",
  "    return sys.stdin.readline().strip()",
  "result = serve_dispatch(Path(sys.argv[1]), json.loads(sys.argv[2]), acknowledge)",
  "sys.stdout.write(json.dumps(result) + '\\n')",
  "sys.stdout.flush()",
].join("\n");

export function pythonDispatch(directory: string, cwd = root): DispatchOpen {
  return (attempt, invoke) => new Promise((resolvePromise, reject) => {
    const child = spawn("uv", ["run", "--no-sync", "python", "-c", serveDispatch, directory, JSON.stringify(attemptRecord(attempt))], { cwd });
    let buffer = "";
    let stderr = "";
    let pending: Promise<unknown> | undefined;
    let settled = false;
    const finish = (error?: Error, value?: unknown) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolvePromise(value);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish(new Error("dispatch guard timed out"));
    }, 30_000);
    const take = (line: string) => {
      const message: unknown = JSON.parse(line);
      if (!isRecord(message)) throw new Error("Invalid dispatch guard response");
      if (message.ready === true) {
        try {
          pending = Promise.resolve(invoke());
          pending.catch(() => undefined);
        } catch (error) {
          child.stdin.write("abort\n");
          finish(error instanceof Error ? error : new Error(String(error)));
          return;
        }
        child.stdin.write("invoked\n");
        return;
      }
      if (!message.admitted) {
        child.stdin.end();
        if (typeof message.status !== "string" || typeof message.ok !== "boolean" || typeof message.admitted !== "boolean") {
          throw new Error("Invalid dispatch decision");
        }
        finish(new DispatchDenied({
          ok: message.ok, admitted: message.admitted, status: message.status,
          reason: typeof message.reason === "string" ? message.reason : null,
        }));
        return;
      }
      if (!pending) throw new Error("Dispatch receipt arrived before transport invocation");
      finish(undefined, pending);
    };
    child.stdout.on("data", (chunk) => {
      buffer += chunk;
      let nl = buffer.indexOf("\n");
      while (nl >= 0) {
        const line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 1);
        if (line.trim()) {
          try { take(line); } catch (error) {
            child.kill();
            finish(error instanceof Error ? error : new Error(String(error)));
            return;
          }
        }
        nl = buffer.indexOf("\n");
      }
    });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.stdin.on("error", (error) => { child.kill(); finish(error); });
    child.on("error", (error) => finish(error));
    child.on("close", (code) => {
      if (!settled) finish(new Error(stderr || `dispatch guard exited ${code}`));
    });
  });
}
