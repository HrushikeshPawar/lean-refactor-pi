import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, chmodSync, closeSync, fsyncSync, mkdirSync, openSync, readFileSync } from "node:fs";
import { mkdir, mkdtemp, readdir, readFile, realpath, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve, relative, sep } from "node:path";
import { Type } from "typebox";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";
import type { AssistantMessage, AssistantMessageEventStream } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import type { BudgetModel, PriorRequest } from "./budget.ts";
import { nearestToolName, normalizeToolArguments, requireToolArguments } from "./toolnames.ts";
import { DeltaChain } from "./journal.ts";
import { objectToolArguments, ResultTrimmer } from "./trim.ts";
import { continuationPush, finishPush, routesText, trimProfile, leanPathViolation, planEvaluate, resolveInlineIdea, planProbe, sinceRefusal, staleNotice } from "./rules.ts";
import type { RouteStats } from "./rules.ts";
import { assessFinalPayload, compactionPayload, BUDGET_PROVIDER, budgetLimits, softCapGate, cacheAlarm, catalogPriceProblem, cacheUtilization, finishAllowed, budgetFooter, enforcedMaxTokens, isBudgetModel, maxRequestOutputTokens, MODELS, PROVIDER, priceForUsage, requestShape, sessionEmbeddedCost, sessionSpend, usageCost, usageCostParts } from "./budget.ts";

const root = resolve(import.meta.dirname, "../../..");
const workspaces = resolve(root, "workspaces");
const SKILL_READ_LIMIT = 24_000;
const MAX_ERROR_STREAK = 3;
export const LEAN_DIRECT_TOOLS = ["lean_goal", "lean_diagnostic_messages", "lean_multi_attempt",
  "lean_local_search", "lean_hover_info"];
const LEAN_DISABLED_TOOLS = ["lean_build", "lean_code_actions", "lean_completions", "lean_declaration_file",
  "lean_file_outline", "lean_get_widgets", "lean_get_widget_source", "lean_hammer_premise", "lean_leanfinder",
  "lean_leansearch", "lean_loogle", "lean_minimal_hypotheses", "lean_profile_proof", "lean_references",
  "lean_run_code", "lean_term_goal", "lean_verify"];

function validObjectJson(raw: string | undefined): boolean {
  if (raw === undefined) return false;
  try {
    const value: unknown = JSON.parse(raw);
    return value !== null && typeof value === "object" && !Array.isArray(value);
  } catch {
    return false;
  }
}

function guardMalformedToolArguments(source: AssistantMessageEventStream,
    onFinal?: (message: AssistantMessage) => void): AssistantMessageEventStream {
  const guarded = createAssistantMessageEventStream();
  void (async () => {
    const rawByIndex = new Map<number, string>();
    const invalidIds = new Set<string>();
    try {
      for await (const event of source) {
        if (event.type === "start") rawByIndex.clear();
        if (event.type === "toolcall_start") {
          const block = event.partial.content[event.contentIndex] as unknown as { partialJson?: string } | undefined;
          if (block?.partialJson !== undefined) rawByIndex.set(event.contentIndex, block.partialJson);
        }
        if (event.type === "toolcall_delta") {
          rawByIndex.set(event.contentIndex, (rawByIndex.get(event.contentIndex) ?? "") + event.delta);
        }
        if (event.type === "toolcall_end") {
          const block = event.partial.content[event.contentIndex] as unknown as { partialJson?: string } | undefined;
          const raw = rawByIndex.get(event.contentIndex) ?? block?.partialJson;
          if (!validObjectJson(raw)) {
            // Pi parses failed JSON as {} before tool validation. `null` is deliberately not an object,
            // so even argument-free tools fail validation instead of running with invented defaults.
            (event.toolCall as unknown as { arguments: unknown }).arguments = null;
            if (block && "arguments" in block) (block as { arguments?: unknown }).arguments = null;
            invalidIds.add(event.toolCall.id);
          }
        }
        if (event.type === "done" && invalidIds.size) {
          for (const block of event.message.content) {
            if (block.type === "toolCall" && invalidIds.has(block.id)) {
              (block as unknown as { arguments: unknown }).arguments = null;
            }
          }
        }
        if (event.type === "done") onFinal?.(event.message);
        if (event.type === "error") onFinal?.(event.error);
        guarded.push(event);
      }
      guarded.end(await source.result());
    } catch {
      const result = await source.result();
      onFinal?.(result);
      guarded.push({ type: "error", reason: result.stopReason === "aborted" ? "aborted" : "error", error: result });
    }
  })();
  return guarded;
}

function inside(path: string, parent: string): boolean {
  const rel = relative(parent, path);
  return rel === "" || (rel !== ".." && !rel.startsWith(`..${sep}`));
}

async function consumeBody(body: BodyInit): Promise<{ bytes: Uint8Array; replacement?: BodyInit }> {
  if (typeof body === "string") return { bytes: Buffer.from(body) };
  if (body instanceof URLSearchParams) return { bytes: Buffer.from(body.toString()) };
  if (body instanceof Uint8Array) return { bytes: body };
  if (body instanceof ArrayBuffer) return { bytes: new Uint8Array(body) };
  if (typeof Blob !== "undefined" && body instanceof Blob) {
    const bytes = new Uint8Array(await body.arrayBuffer());
    return { bytes, replacement: bytes };
  }
  if (typeof body === "object" && Symbol.asyncIterator in body) {
    const chunks: Uint8Array[] = [];
    for await (const chunk of body as AsyncIterable<Uint8Array>) {
      chunks.push(chunk instanceof Uint8Array ? chunk : Buffer.from(chunk));
    }
    const bytes = Buffer.concat(chunks);
    return { bytes, replacement: bytes };
  }
  // An unread body would leave the request without its byte-exact journal row.
  throw new Error(`Arena cannot journal a provider request body of type ${Object.prototype.toString.call(body)}`);
}

async function readRequestBody(input: RequestInfo | URL, init?: RequestInit): Promise<{ bytes: Uint8Array; input: RequestInfo | URL; init?: RequestInit }> {
  if (init?.body != null) {
    const read = await consumeBody(init.body);
    return read.replacement === undefined
      ? { bytes: read.bytes, input, init }
      : { bytes: read.bytes, input, init: { ...init, body: read.replacement } };
  }
  if (typeof Request !== "undefined" && input instanceof Request) {
    return { bytes: new Uint8Array(await input.clone().arrayBuffer()), input, init };
  }
  return { bytes: new Uint8Array(), input, init };
}

function deliveredBlocks(content: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(content)) return [];
  return content.map(block => {
    if (!block || typeof block !== "object") return { type: "unknown" };
    const item = block as Record<string, unknown>;
    if (item.type === "text") return { type: "text", text: item.text ?? "" };
    if (item.type === "toolCall") return { type: "toolCall", id: item.id, name: item.name, arguments: item.arguments };
    if (item.type === "thinking") {
      const delivered: Record<string, unknown> = { type: "thinking", thinking: item.thinking,
        thinkingSignature: item.thinkingSignature };
      if (item.redacted) delivered.redacted = true;
      return delivered;
    }
    return { type: item.type };
  });
}

export default function arenaExtension(pi: ExtensionAPI) {
  // Every Arena tool sees cleaned arguments: empty optional fields are absent, text arrays are parsed.
  const registerTool = ((tool: any) => pi.registerTool({ ...tool, prepareArguments: requireToolArguments,
    execute: (id: string, params: any, ...rest: any[]) =>
      tool.execute(id, normalizeToolArguments(params, tool.parameters), ...rest) })) as typeof pi.registerTool;
  // A factory invocation owns one Pi session. No active theorem is module-global.
  let active: string | undefined;
  const runId = process.env.ARENA_RUN_ID;
  const runDirectory = runId ? resolve(root, "runs", "pi-budget", runId) : undefined;
  const costJournal = runDirectory ? resolve(runDirectory, "cost-ledger.jsonl") : undefined;
  const traceJournal = runDirectory ? resolve(runDirectory, "trace-journal.jsonl") : undefined;
  let pendingRequest: string | undefined;
  // Final provider message of each request as the guard stream delivered it. Requests Pi sends
  // outside an agent turn (compaction summaries) never reach message_end; this is their usage.
  const finalMessages = new Map<string, AssistantMessage>();
  let openAttempt: string | undefined;
  let previousFailed: string | undefined;
  // Payload bytes per open request, and the last settled one, for the context bound.
  const requestBytes = new Map<string, number>();
  let priorRequest: PriorRequest | undefined;
  // True from session_before_compact until session_compact / session_compact_failed. Compaction is a
  // necessary step and always within budget: its summary requests skip the window check and every gate
  // but are still reserved and settled, so spend stays exact. Agent turns are never affected.
  let compacting = false;
  const compactionRequests = new Set<string>();
  let fixedRequestShape: string | undefined;
  let gateStopReason: string | undefined;
  let gateStopCode: "soft_cap_reached" | "actual_usage_cap" | "estimated_request_unaffordable" | undefined;
  let wireIndex = 0;
  let continuations = 0;
  let plateau = 0;
  let errorStreak = 0;
  let previousProgress = "";
  let finishReviewIssued = false;
  let finishReminderIssued = false;
  let finishConfirmed = false;
  let finishRefusals = 0;
  let refusalIdeaIds = new Set<string>();
  let refusalRouteStats: RouteStats = {};
  let refusalCredited = new Set<string>();
  const staleNoticed = new Set<string>();
  let finishReviewTurn = false;
  let noWorkTurns = 0;
  let turnHadProofAttempt = false;
  let turnHadNovelContext = false;
  let turnHadVerifiedImprovement = false;
  let previousVerified: Record<string, any> | null | undefined;
  const discoveries = new Set<string>();
  // Model-facing trimming of tool results; its record of what the model has seen resets on compaction.
  const trimmer = new ResultTrimmer();
  let readEntries: (() => SessionEntry[]) | undefined;
  let modelRegistry: ExtensionContext["modelRegistry"] | undefined;

  async function campaign(action: string, args: string[] = []): Promise<Record<string, any>> {
    if (!active || !runId) throw new Error("Arena run is not selected");
    const command = ["run", "--no-project", "python", "-m", "tools.arena_campaign", action,
      "--theorem", active, "--run-id", runId, ...args];
    const output = await new Promise<string>((accept, reject) => {
      const child = spawn("uv", command, { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
      const chunks: Buffer[] = [];
      const errors: Buffer[] = [];
      child.stdout.on("data", (chunk: Buffer) => chunks.push(chunk));
      child.stderr.on("data", (chunk: Buffer) => errors.push(chunk));
      child.on("error", reject);
      child.on("close", code => code === 0 || chunks.length
        ? accept(Buffer.concat(chunks).toString("utf8"))
        : accept(JSON.stringify({ ok: false, error: (Buffer.concat(errors).toString("utf8").trim().split("\n").at(-1) ?? "Arena command failed").replace(/^\w*(Error|Exception): /, "") })));
    });
    try { return JSON.parse(output.trim().split("\n").at(-1) ?? ""); }
    catch { return { ok: false, error: `Arena command returned no result: ${output.trim().slice(0, 200)}` }; }
  }

  // Full checks on the other toolchains run in a background checker the harness starts
  // itself. One checker at a time; a kick while it runs makes it go round once more.
  let checker: ReturnType<typeof spawn> | undefined;
  let kickAgain = false;
  function kickAutocheck() {
    if (!active || !runId) return;
    if (checker) { kickAgain = true; return; }
    kickAgain = false;
    checker = spawn("uv", ["run", "--no-project", "python", "-m", "tools.arena_campaign", "autocheck",
      "--theorem", active, "--run-id", runId], { cwd: root, stdio: "ignore" });
    const done = () => { checker = undefined; if (kickAgain) kickAutocheck(); };
    checker.on("close", done);
    checker.on("error", done);
  }

  // The model learns about harness results from a short line appended to whichever tool
  // result comes next. It is added once, when the tool result is created, and only when
  // something changed, so history stays append-only and the cached prefix is untouched.
  let deliveredSeq = -1;
  let deliveredBest = "";
  function readState(): Record<string, any> | undefined {
    if (!runDirectory) return undefined;
    try { return JSON.parse(readFileSync(resolve(runDirectory, "state.json"), "utf8")); }
    catch { return undefined; }
  }
  function briefText(item: Record<string, any> | null | undefined): string {
    if (!item) return "none";
    const score = item.proxy !== undefined ? `proxy ${item.proxy}` : `est. ${item.estimated_proxy}`;
    return `${item.candidate} ${score} (${item.tokens} tok, ${item.heartbeats} HB)`;
  }
  function payloadFromToolResult(result: any): Record<string, any> | undefined {
    // The JSON payload is the first text part; a later `[arena]` status part must not hide it.
    const text = result?.content?.find((part: any) => part?.type === "text")?.text;
    if (!text) return undefined;
    try {
      const payload = JSON.parse(text);
      return payload && typeof payload === "object" ? payload : undefined;
    } catch { return undefined; }
  }
  function discoveryKeys(toolName: string, payload: Record<string, any> | undefined): string[] {
    if (!payload || payload.ok === false) return [];
    const keys: string[] = [];
    if (toolName === "arena_declarations") {
      const rows = payload.items ?? payload.declarations ?? payload.results ?? [];
      for (const row of rows) if (row && ["declaration", "local"].includes(row.kind) &&
        (row.name || row.handle || row.input)) {
        keys.push(`decl:${row.name ?? row.handle ?? row.input}:${row.source ?? row.body ?? row.type ?? ""}`);
      }
    } else if (toolName === "arena_find") {
      for (const row of payload.results ?? []) if (row && (row.name || row.handle)) keys.push(`decl:${row.name ?? row.handle}:${row.signature ?? ""}`);
    } else if (toolName === "arena_source") {
      keys.push(`source:${payload.handle ?? payload.path ?? ""}:${payload.first ?? ""}:${payload.last ?? ""}:${payload.text ?? payload.source ?? ""}`);
    } else if (toolName.endsWith("lean_goal")) {
      keys.push(`goal:${JSON.stringify(payload.goals ?? payload)}`);
    }
    return keys;
  }
  function verifiedImproved(current: Record<string, any> | null | undefined,
                            previous: Record<string, any> | null | undefined): boolean {
    if (!current) return false;
    // undefined: nothing observed yet this session; null: no verified candidate before this turn.
    if (previous === undefined) return false;
    if (previous === null) return true;
    const scoreBetter = current.proxy != null && (previous.proxy == null || current.proxy > previous.proxy);
    const tokensBetter = current.tokens != null && (previous.tokens == null || current.tokens < previous.tokens);
    const heartbeatsBetter = current.heartbeats != null && (previous.heartbeats == null || current.heartbeats < previous.heartbeats);
    return scoreBetter || tokensBetter || heartbeatsBetter;
  }
  function stateLine(state: Record<string, any>, force = false): string | undefined {
    const updates = (state.updates ?? []).filter((item: any) => item.seq > deliveredSeq);
    const best = JSON.stringify([state.best ?? null, state.leading_unverified ?? null]);
    if (!force && !updates.length && best === deliveredBest) return undefined;
    deliveredSeq = Math.max(deliveredSeq, ...(state.updates ?? []).map((item: any) => item.seq));
    deliveredBest = best;
    const parts = updates.map((item: any) => item.text);
    parts.push(`best verified: ${briefText(state.best)}`);
    if (state.leading_unverified) {
      const pending = (state.checking ?? []).includes(state.leading_unverified.candidate) ? "being checked" : "not yet checked";
      parts.push(`leading unverified: ${briefText(state.leading_unverified)}, ${pending}`);
    }
    return `[arena] ${parts.join(" · ")}`;
  }

  function costEvents(): Array<Record<string, unknown>> {
    if (!costJournal) return [];
    try { return readFileSync(costJournal, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line)); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
  }
  function appendCost(event: Record<string, unknown>) {
    if (!costJournal) throw new Error("Arena cost journal is unavailable");
    mkdirSync(dirname(costJournal), { recursive: true });
    const fd = openSync(costJournal, "a", 0o600);
    try { appendFileSync(fd, `${JSON.stringify({ ts: Date.now(), ...event })}\n`); fsyncSync(fd); }
    finally { closeSync(fd); }
  }
  function appendTrace(event: Record<string, unknown>) {
    if (!traceJournal) throw new Error("Arena trace journal is unavailable");
    mkdirSync(dirname(traceJournal), { recursive: true });
    const fd = openSync(traceJournal, "a", 0o600);
    try { appendFileSync(fd, `${JSON.stringify({ ts: Date.now(), ...event })}\n`); fsyncSync(fd); }
    finally { closeSync(fd); }
    chmodSync(traceJournal, 0o600);
  }
  // The wire body and the post-hook payload are each stored as a delta against the previous one (see journal.ts),
  // so the journal grows with what each request adds, not with the whole context every time. Fields that
  // describe the encoding come before the heavy `body` / `post_hook`, which stay last in the row.
  const wireChain = new DeltaChain();
  const hookChain = new DeltaChain();
  function recordWire(bytes: Uint8Array) {
    if (!pendingRequest || !bytes.byteLength) return;
    const buffer = Buffer.from(bytes);
    const { sha256, delta } = wireChain.encode(buffer);
    appendTrace({ kind: "wire", id: pendingRequest, retry_index: wireIndex, sha256,
      ...(delta ? { encoding: "delta", prefix: delta.prefix, suffix: delta.suffix } : {}),
      body: delta ? delta.middle : buffer.toString("utf8") });
    wireIndex += 1;
  }
  function hookFields(published: unknown) {
    const text = Buffer.from(JSON.stringify(published));
    const { sha256, delta } = hookChain.encode(text);
    return { post_hook_sha256: sha256, post_hook_encoding: delta ? "delta" : "text",
      ...(delta ? { post_hook_prefix: delta.prefix, post_hook_suffix: delta.suffix } : {}),
      post_hook: delta ? delta.middle : text.toString("utf8") };
  }
  function costState() {
    const reservations = new Map<string, number>();
    let spent = 0;
    for (const event of costEvents()) {
      if (event.kind === "reserve") reservations.set(String(event.id), Number(event.usd));
      if (event.kind === "settle" || event.kind === "release") {
        if (!reservations.has(String(event.id))) throw new Error("Unmatched Arena settlement");
        reservations.delete(String(event.id));
        // Older journals settled zero-usage transport errors at the reserved
        // amount. Interpret those as releases without rewriting their history.
        if (event.kind === "settle" && event.usage_known !== false) spent += Number(event.usd);
        // Reservations are estimates for audit and crash recovery, not a cap.
      }
    }
    const unresolved = [...reservations.values()].reduce((sum, amount) => sum + amount, 0);
    const model = process.env.ARENA_MODEL;
    // Pi can record compaction or direct-call usage outside this provider's
    // request journal. Its persisted session total is the other audit source.
    const sessionObserved = readEntries && model && isBudgetModel(model)
      ? sessionSpend(readEntries(), model) : 0;
    return { spent: Math.max(spent, sessionObserved), unresolved };
  }

  pi.on("session_start", (_event, ctx) => {
    active = undefined;
    readEntries = () => ctx.sessionManager.getEntries();
    modelRegistry = ctx.modelRegistry;
    const pending = new Set<string>();
    for (const item of costEvents()) {
      if (item.kind === "reserve") pending.add(String(item.id));
      if (item.kind === "settle" || item.kind === "release") pending.delete(String(item.id));
    }
    for (const id of pending) {
      if (!costEvents().some(item => item.kind === "unknown" && String(item.id) === id)) {
        appendCost({ kind: "unknown", id, reason: "previous_process_ended_before_settlement", usage_known: false });
      }
    }
    const latest = costEvents().filter(item => item.kind === "control").at(-1);
    continuations = Number(latest?.continuations ?? 0);
    plateau = Number(latest?.plateau ?? 0);
    errorStreak = Number(latest?.error_streak ?? 0);
    previousProgress = String(latest?.progress ?? "");
    const finishEvents = costEvents().filter(item => item.kind === "finish");
    finishReviewIssued = finishEvents.some(item => item.phase === "review" || item.phase === "reminder");
    finishReminderIssued = finishEvents.some(item => item.phase === "reminder");
    finishConfirmed = finishEvents.some(item => item.phase === "confirmed");
    const refused = finishEvents.filter(item => item.phase === "refused");
    finishRefusals = refused.length;
    refusalIdeaIds = new Set(((refused.at(-1)?.idea_ids as string[] | undefined) ?? []).map(String));
    refusalRouteStats = (refused.at(-1)?.route_stats as RouteStats | undefined) ?? {};
    refusalCredited = new Set(((refused.at(-1)?.credited_ids as string[] | undefined) ?? []).map(String));
    noWorkTurns = Number(latest?.no_work_turns ?? 0);
    finishReviewTurn = false;
    turnHadProofAttempt = false;
    turnHadNovelContext = false;
    turnHadVerifiedImprovement = false;
    previousVerified = undefined;
    discoveries.clear();
    trimmer.forget();
    for (const item of costEvents()) if (item.kind === "discovery" && typeof item.signature === "string") {
      discoveries.add(item.signature);
    }
    fixedRequestShape = undefined;
    gateStopReason = undefined;
    gateStopCode = undefined;
  });

  // The guard provider owns the final transport callback. Extension hook errors
  // are swallowed by Pi, so a hook cannot enforce a hard dollar limit.
  pi.registerProvider("arena-guard", {
    name: "Arena guarded OpenCode Go",
    api: "openai-responses", baseUrl: "http://127.0.0.1/arena-guard-unused", apiKey: "guard-routing-only",
    models: Object.entries(MODELS).map(([id, limits]) => ({
      id, name: `Arena guarded ${id}`, reasoning: true, input: ["text"],
      cost: limits.price, contextWindow: limits.contextWindow, maxTokens: limits.requestOutputTokens,
    })),
    streamSimple(model, context, options) {
      if (!isBudgetModel(model.id) || !active || !runDirectory) {
        throw new Error("Unpriced or unselected Arena model");
      }
      const runtime = modelRegistry;
      if (!runtime) throw new Error("Arena model registry is unavailable");
      const physical = runtime.find(PROVIDER, model.id);
      if (!physical) throw new Error(`OpenCode Go model unavailable: ${model.id}`);
      if (physical.contextWindow > MODELS[model.id].contextWindow ||
          physical.maxTokens > MODELS[model.id].maxTokens) {
        throw new Error(`Arena budget reservation is outdated for ${model.id}`);
      }
      enforcedMaxTokens(physical, model.id);
      const priceProblem = catalogPriceProblem(model.id, physical.cost);
      if (priceProblem) throw new Error(priceProblem);
      if (!compacting && (finishConfirmed || (process.env.ARENA_AUTOCONTINUE === "1" && noWorkTurns >= 2))) {
        const stopped = createAssistantMessageEventStream();
        const zeroCost = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 };
        const message = { role: "assistant" as const, content: [], api: model.api,
          provider: physical.provider, model: physical.id,
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: zeroCost },
          stopReason: "stop" as const, timestamp: Date.now() };
        stopped.push({ type: "start", partial: { ...message, content: [] } });
        stopped.push({ type: "done", reason: "stop", message });
        stopped.end();
        return stopped;
      }
      const { apiKey: _guardKey, headers: _guardHeaders, env: _guardEnv, ...rest } = options ?? {};
      const innerFetch = rest.fetch ?? globalThis.fetch;
      return guardMalformedToolArguments(runtime.streamSimple(physical, context, {
        ...rest,
        maxTokens: Math.min(rest.maxTokens ?? maxRequestOutputTokens(model.id), maxRequestOutputTokens(model.id)),
        fetch: async (input, init) => {
          if (gateStopReason && !compacting) {
            throw new Error(`Arena budget stop: ${gateStopReason}`);
          }
          // Headers stay on the request. Only the body is journaled, after the SDK
          // has added stream flags the hook never saw.
          const captured = await readRequestBody(input, init);
          recordWire(captured.bytes);
          return innerFetch(captured.input, captured.init);
        },
        onPayload: async payload => {
          // A request still open here was sent outside an agent turn. When Pi compacts in the middle of a turn
          // it makes two sequential summary requests (history, then the turn prefix; compaction.js `compact`);
          // the first is still open when the second starts. Both are real, billed and needed, so this is
          // bookkeeping of the first one, not a duplicate request. The second closes on session_compact.
          closeRequest(undefined, "superseded_by_next_request");
          if (compacting) {
            // No check and no gate. Reserve a byte-based estimate for the ledger only; actual usage settles on close.
            const summary = compactionPayload(payload, model.id as BudgetModel);
            const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const published = await options?.onPayload?.(summary.payload, physical) ?? summary.payload;
            const bytes = Buffer.byteLength(JSON.stringify(published ?? null));
            appendCost({ kind: "reserve", id, usd: summary.reserve, estimate_usd: summary.reserve, gate: "allow",
              reason: "compaction summary bypasses the budget guard", purpose: "compaction", model: model.id, bytes });
            requestBytes.set(id, bytes);
            compactionRequests.add(id);
            pendingRequest = id;
            openAttempt = id;
            wireIndex = 0;
            appendTrace({ kind: "request", id, run_id: runId, retry_of: null, model: model.id,
              estimate_usd: summary.reserve, gate_decision: "bypass_compaction", ...hookFields(published) });
            return published;
          }
          if (gateStopReason) throw new Error(`Arena budget stop: ${gateStopReason}`);
          // Normalize at a fixed run-wide output limit; never use the remaining
          // dollars to rewrite the provider request.
          const softLimits = budgetLimits();
          const soft = softCapGate(costState().spent, softLimits);
          if (!soft.allowed) {
            gateStopCode = soft.stop as typeof gateStopCode;
            gateStopReason = `settled spend $${costState().spent.toFixed(6)} reached the $${softLimits.stopUsd} cap`;
            appendCost({ kind: "gate", id: `${Date.now()}-soft`, model: model.id, decision: "refuse",
              reason: gateStopReason, stop: soft.stop, spent_usd: costState().spent,
              reserved_usd: costState().unresolved, soft_remaining_usd: 0, soft_overshoot_usd: soft.overshootUsd });
            appendTrace({ kind: "gate_refusal", run_id: runId, model: model.id, reason: gateStopReason,
              stop: soft.stop, soft_overshoot_usd: soft.overshootUsd });
            throw new Error(`Arena budget stop: ${gateStopReason}`);
          }
          const bounded = assessFinalPayload(payload, model.id as BudgetModel, costState(), softLimits, priorRequest);
          const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
          const retryOf = previousFailed ?? null;
          const shape = requestShape(bounded.payload);
          if (fixedRequestShape === undefined) fixedRequestShape = shape;
          const shapeChanged = shape !== fixedRequestShape;
          const decision = shapeChanged ? {
            allowed: false, estimateUsd: bounded.reserve, remainingUsd: bounded.remainingUsd,
            overshootUsd: Math.max(0, bounded.reserve - bounded.remainingUsd),
            reason: "provider request shape changed during run",
          } : bounded;
          const attempt = { kind: "gate", id, model: model.id, estimate_usd: decision.estimateUsd,
            decision: decision.allowed ? "allow" : "refuse", reason: decision.reason,
            spent_usd: costState().spent, reserved_usd: costState().unresolved,
            remaining_usd: decision.remainingUsd, overshoot_usd: decision.overshootUsd,
            bytes: Buffer.byteLength(JSON.stringify(bounded.payload)) };
          if (!decision.allowed) {
            appendCost(attempt);
            gateStopReason = decision.reason;
            gateStopCode = "estimated_request_unaffordable";
            appendTrace({ kind: "gate_refusal", id, run_id: runId, model: model.id,
              estimate_usd: decision.estimateUsd, reason: decision.reason,
              remaining_usd: decision.remainingUsd, overshoot_usd: decision.overshootUsd,
              request_shape: shape });
            throw new Error(`Arena budget stop: ${decision.reason}; estimated $${decision.estimateUsd.toFixed(6)}, `
              + `$${decision.remainingUsd.toFixed(6)} remains`);
          }

          const published = await options?.onPayload?.(bounded.payload, physical) ?? bounded.payload;
          const publishedShape = requestShape(published as Record<string, unknown>);
          if (publishedShape !== fixedRequestShape) {
            gateStopReason = "provider hook changed the fixed request shape";
            gateStopCode = "estimated_request_unaffordable";
            appendCost({ ...attempt, decision: "refuse", reason: gateStopReason });
            appendTrace({ kind: "gate_refusal", id, run_id: runId, model: model.id,
              estimate_usd: decision.estimateUsd, reason: gateStopReason,
              remaining_usd: decision.remainingUsd, overshoot_usd: decision.overshootUsd,
              request_shape: publishedShape });
            throw new Error(`Arena budget stop: ${gateStopReason}`);
          }
          appendCost(attempt);
          previousFailed = undefined;
          appendCost({ kind: "reserve", id, usd: bounded.reserve, estimate_usd: decision.estimateUsd,
            gate: "allow", reason: decision.reason, remaining_usd: decision.remainingUsd,
            overshoot_usd: decision.overshootUsd, model: model.id,
            bytes: Buffer.byteLength(JSON.stringify(published)) });
          requestBytes.set(id, Buffer.byteLength(JSON.stringify(bounded.payload), "utf8"));
          pendingRequest = id;
          openAttempt = id;
          wireIndex = 0;
          appendTrace({ kind: "request", id, run_id: runId, retry_of: retryOf, model: model.id,
            estimate_usd: decision.estimateUsd, gate_decision: "allow",
            remaining_allowance_usd: decision.remainingUsd, ...hookFields(published) });
          return published;
        },
      }), message => { if (pendingRequest) finalMessages.set(pendingRequest, message); });
    },
  });

  for (const id of Object.keys(MODELS)) {
    if (!isBudgetModel(id)) continue;
    pi.registerVirtualModel({
      provider: BUDGET_PROVIDER,
      id,
      name: `Arena budgeted ${id}`,
      thinkingLevels: ["off", "low", "medium", "high"],
      route(request, ctx) {
        if (!readEntries) throw new Error("Arena budget session has not started");
        const physical = ctx.modelRegistry.find(PROVIDER, id);
        const guarded = ctx.modelRegistry.find("arena-guard", id);
        if (!physical || !guarded) throw new Error(`OpenCode Go or Arena guard unavailable: ${id}`);
        const limits = MODELS[id];
        if (physical.contextWindow > limits.contextWindow || physical.maxTokens > limits.maxTokens) {
          throw new Error(`Arena budget reservation is outdated for ${id}`);
        }
        // Pi resolves each reply's model from the physical catalog (messages carry its provider), so that
        // entry's maxTokens must be the enforced per-request limit, not the physical one.
        enforcedMaxTokens(physical, id);
        const priceProblem = catalogPriceProblem(id, physical.cost);
        if (priceProblem) throw new Error(priceProblem);
        return { model: guarded, thinkingLevel: request.thinkingLevel };
      },
    });
  }

  pi.on("before_agent_start", (_event, ctx) => {
    compacting = false;  // safety: an agent turn never inherits the bypass
    if (process.env.ARENA_BUDGET_REQUIRED !== "1") return;
    if (!active || ctx.model?.provider !== BUDGET_PROVIDER || !isBudgetModel(ctx.model.id)) {
      ctx.abort();
      if (ctx.hasUI) ctx.ui.notify("Select /arena and an arena-budget model before prompting.", "error");
    }
  });

  // Preserve earlier tool messages byte-for-byte. Rewriting them when a new
  // evaluation arrives invalidates the provider's cached prompt prefix.

  // Close the open request in the ledger: settle with real usage, else unknown/release.
  // `message` is the agent's assistant message (message_end); without it the request was not an
  // agent message (compaction summary) and its usage is whatever the guard stream delivered.
  function closeRequest(agentMessage: AssistantMessage | undefined, orphanReason: string) {
    if (!pendingRequest) return;
    const orphan = agentMessage === undefined;
    const message = agentMessage ?? finalMessages.get(pendingRequest);
    const event = { message: message ?? ({ role: "assistant", content: [], stopReason: "error",
      errorMessage: orphanReason, usage: undefined } as unknown as AssistantMessage) };
    const model = process.env.ARENA_MODEL;
    if (!model || !isBudgetModel(model)) return;
    const state = costEvents().findLast(item => item.kind === "reserve" && item.id === pendingRequest);
    if (!state) throw new Error("Missing Arena reservation");
    const blocks = deliveredBlocks(event.message.content);
    const text = blocks.filter(block => block.type === "text").map(block => String(block.text ?? "")).join("");
    const delivered = { kind: "response", id: pendingRequest, content: blocks, text,
      stop_reason: event.message.stopReason, response_id: event.message.responseId ?? null,
      response_model: event.message.responseModel ?? event.message.model,
      error_message: event.message.errorMessage ?? null,
      ...(orphan ? { source: "orphan_stream", orphan_reason: orphanReason } : {}) };
    let usd = 0;
    let boundViolation = false;
    if (event.message.usage?.totalTokens) {
      const usage = event.message.usage;
      usd = usageCost(usage, model);
      const bytes = requestBytes.get(pendingRequest);
      const inputTokens = (usage.input ?? 0) + (usage.cacheRead ?? 0) + (usage.cacheWrite ?? 0);
      // A summary request is not a prefix of the next agent request, so it must not seed the context bound.
      if (bytes !== undefined && inputTokens > 0 && !compactionRequests.has(pendingRequest)) priorRequest = { bytes, inputTokens };
      boundViolation = usd > Number(state.usd);
      const limits = budgetLimits();
          const ledgerSettled = costEvents().filter(item => item.kind === "settle" && item.usage_known !== false)
        .reduce((sum, item) => sum + Number(item.usd), 0) + usd;
      const settledSpend = Math.max(costState().spent, ledgerSettled);
      const unresolvedAfter = Math.max(0, costState().unresolved - Number(state.usd));
      const remainingAllowanceUsd = Math.max(0, limits.hardCapUsd - settledSpend - unresolvedAfter);
      const overshootUsd = Math.max(0, settledSpend - limits.hardCapUsd);
      const soft = softCapGate(settledSpend, limits);
      appendCost({ kind: "settle", id: pendingRequest, usd, usage_known: true,
        ...(orphan ? { source: "orphan_stream", orphan_reason: orphanReason, stop_reason: event.message.stopReason } : {}),
        bound_violation: boundViolation,
        estimate_usd: Number(state.usd), remaining_usd: remainingAllowanceUsd,
        overshoot_usd: overshootUsd,
        soft_remaining_usd: soft.remainingUsd, soft_overshoot_usd: soft.overshootUsd,
        tokens: { input: usage.input ?? 0, output: usage.output ?? 0,
          cache_read: usage.cacheRead ?? 0, cache_write: usage.cacheWrite ?? 0 },
        ledger_components_usd: usageCostParts(usage, model),
        pi_embedded_cost_usd: usage.cost?.total ?? null });
      // Pi prices the same usage from its catalog, which `catalogPriceProblem` keeps equal to
      // the ledger, except Luna's conservative high tier, which only the ledger applies.
      const priceTier = MODELS[model].highPrice && priceForUsage(usage, model) === MODELS[model].highPrice ? "high" : "base";
      appendTrace({ ...delivered, settled_usd: usd, price_tier: priceTier, pi_cost_usd: usage.cost?.total ?? null,
        estimate_usd: Number(state.usd), remaining_allowance_usd: remainingAllowanceUsd,
        overshoot_usd: overshootUsd,
        soft_remaining_usd: soft.remainingUsd, soft_overshoot_usd: soft.overshootUsd,
        usage: { input: usage.input ?? 0, output: usage.output ?? 0,
          cache_read: usage.cacheRead ?? 0, cache_write: usage.cacheWrite ?? 0 } });
      const alarm = cacheAlarm(usage, costEvents().filter(item => item.kind === "settle" && item.usage_known === true).length);
      if (alarm) {
        appendCost({ kind: "cache_alarm", id: pendingRequest, ...alarm });
        console.error(`[arena-cache-alarm] request ${alarm.request}: wrote ${alarm.write} cache tokens but read ${alarm.read}; the stable prefix was not reused`);
      }
      console.error(`[arena-cost] settled $${usd.toFixed(6)}; cache read ${usage.cacheRead ?? 0}, write ${usage.cacheWrite ?? 0}; total $${(costState().spent).toFixed(6)}`);
    } else {
      const limits = budgetLimits();
      const spent = costState().spent;
      const sent = wireIndex > 0;
      const unresolvedAfter = Math.max(0, costState().unresolved - (sent ? 0 : Number(state.usd)));
      appendCost({ kind: sent ? "unknown" : "release", id: pendingRequest,
        reason: sent ? (orphan ? `orphan_request_without_usage:${orphanReason}` : "provider_attempt_without_settled_usage") : event.message.stopReason ?? "not_sent",
        usage_known: false, estimate_usd: Number(state.usd), remaining_usd: Math.max(0, limits.hardCapUsd - spent - unresolvedAfter),
        overshoot_usd: Math.max(0, spent - limits.hardCapUsd),
        soft_remaining_usd: softCapGate(spent, limits).remainingUsd,
        soft_overshoot_usd: softCapGate(spent, limits).overshootUsd, cache_read_tokens: 0, cache_write_tokens: 0 });
      appendTrace({ ...delivered, settled_usd: null, pi_cost_usd: null });
      if (!orphan) previousFailed = pendingRequest;
      console.error(`[arena-cost] released failed request ${pendingRequest}; no usage returned`);
    }
    finalMessages.delete(pendingRequest);
    requestBytes.delete(pendingRequest);
    compactionRequests.delete(pendingRequest);
    pendingRequest = undefined;
  }
  pi.on("message_end", event => {
    if (event.message.role === "assistant") closeRequest(event.message, "");
  });
  // Compaction summaries are provider requests with no agent message_end.
  pi.on("session_compact", () => {
    compacting = false;
    closeRequest(undefined, "compaction_summary");
    trimmer.forget();
    void injectMemory();
  });
  pi.on("session_compact_failed", () => { compacting = false; closeRequest(undefined, "compaction_failed"); });
  pi.on("session_before_compact", event => {
    compacting = true;
    const fixed = objectToolArguments(event.preparation.messagesToSummarize) + objectToolArguments(event.preparation.turnPrefixMessages);
    if (fixed) appendTrace({ kind: "compaction_repair", null_tool_arguments: fixed });
  });

  // After a compaction the harness restates its own record of the run (best verified candidate, routes,
  // ideas, latest failures, allowance) as one hidden message. Built from the ledger, never by the model,
  // and sent only here, so it is not repeated every turn. Pi queues it behind the turn's tool results.
  async function injectMemory() {
    if (!active || !runId) return;
    try {
      const limits = budgetLimits();
      const result = await campaign("memory", ["--spent-usd", String(costState().spent), "--cap-usd", String(limits.stopUsd)]);
      if (result.ok === false || typeof result.text !== "string") return;
      appendCost({ kind: "memory", chars: result.text.length });
      pi.sendMessage({ customType: "arena-memory", content: result.text, display: false }, { triggerTurn: false });
    } catch (error) { console.error(`[arena-memory] not injected: ${error}`); }
  }

  function budgetStatus(ctx: ExtensionContext) {
    const model = ctx.model;
    if (model?.provider !== BUDGET_PROVIDER || !isBudgetModel(model.id)) return undefined;
    const state = costState();
    const limits = budgetLimits();
    const soft = softCapGate(state.spent, limits);
    return { spent_usd: state.spent, unresolved_usd: state.unresolved,
      remaining_usd: soft.remainingUsd,
      hard_remaining_usd: Math.max(0, limits.hardCapUsd - state.spent - state.unresolved),
      overshoot_usd: soft.overshootUsd,
      hard_overshoot_usd: Math.max(0, state.spent - limits.hardCapUsd),
      can_continue: soft.allowed,
      cap_is_actual_usage_only: true };
  }

  pi.on("session_shutdown", async (_event, ctx) => {
    const reportPath = process.env.ARENA_BUDGET_REPORT_PATH;
    if (!reportPath) return;
    const model = ctx.model;
    let report: Record<string, unknown> = { session_id: ctx.sessionManager.getSessionId(),
      theorem: active ?? null,
      price_basis: "OpenCode Go list prices checked 2026-10-06; Luna tier chosen from billed prompt tokens" };
    try {
      const limits = budgetLimits();
      if (model?.provider !== BUDGET_PROVIDER || !isBudgetModel(model.id)) {
        throw new Error("Budgeted model was not selected");
      }
      report = { ...report, hard_cap_usd: limits.hardCapUsd, soft_cap_usd: limits.stopUsd, stop_target_usd: limits.stopUsd,
        provider: PROVIDER, model: model.id, ...budgetStatus(ctx),
        price_method: "Observed usage priced per request using OpenCode Go list rates; Luna uses the >272K tier only when billed prompt tokens cross that threshold. Neither this nor Pi's embedded estimate is a provider invoice.",
        configured_usd_per_million_tokens: MODELS[model.id].price,
        configured_high_tier: MODELS[model.id].highPrice ? {
          prompt_tokens_over: MODELS[model.id].highContextThreshold,
          usd_per_million_tokens: MODELS[model.id].highPrice } : null,
        pi_embedded_estimate: sessionEmbeddedCost(ctx.sessionManager.getEntries()),
        pi_session_spend_usd: sessionSpend(ctx.sessionManager.getEntries(), model.id),
        cache_utilization: cacheUtilization(ctx.sessionManager.getEntries(), model.id) };
    } catch (error) {
      report = { ...report, error: String(error) };
    }
    await mkdir(dirname(reportPath), { recursive: true });
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  });

  let leanProject: string | undefined;

  pi.registerCommand("arena", {
    description: "Select a benchmark theorem: /arena Core.InitsUpdatesComm",
    handler: async (name, ctx) => {
      const wanted = name.trim();
      const rows = (await readFile(resolve(root, "benchmark/original/warmup.jsonl"), "utf8"))
        .split("\n").filter(Boolean).map((line) => JSON.parse(line));
      const row = rows.find((item) => item.name === wanted);
      if (!row) {
        ctx.ui.notify(`Unknown benchmark theorem: ${wanted}`, "error");
        return;
      }
      active = wanted;
      const first = Object.entries(row.version_info[0] ?? {})[0];
      if (first && process.env.ARENA_NO_MCP !== "1") {
        const [version] = first;
        leanProject = runDirectory ? resolve(runDirectory, "scratch", "project") : resolve(workspaces, `${row.source}-${version}`);
        pi.registerMcpServer("arena-lean", {
          command: "uvx",
          args: ["--from", "lean-lsp-mcp==0.31.0", "lean-lsp-mcp"],
          env: {
            LEAN_PROJECT_PATH: leanProject,
            LEAN_LOG_LEVEL: "WARNING",
            // Elaborate the candidate file as soon as the server starts, so the model's first
            // lean_goal does not wait for Mathlib-sized imports and everything above the theorem.
            ...(row.file_path ? { LEAN_MCP_PREWARM_FILES: row.file_path } : {}),
            // Only the five tools below are served. Everything else is off: network search,
            // builds and arbitrary code runs would bypass the harness, and scoring already has
            // arena_evaluate / arena_profile.
            LEAN_MCP_DISABLED_TOOLS: LEAN_DISABLED_TOOLS.join(","),
          },
          // Declared directly so the tool list is fixed from the first request (cache prefix).
          // "hidden" for everything else keeps Pi's codemode sandbox from activating.
          // A cold first query on a Mathlib project can exceed Pi's 60 s default.
          timeout: 180,
          exposure: "hidden",
          toolExposure: Object.fromEntries(LEAN_DIRECT_TOOLS.map(name => [name, "direct"])),
        });
      }
      kickAutocheck();
      ctx.ui.notify(`Arena target: ${wanted}`, "info");
    },
  });

  pi.on("tool_call", async (event, ctx) => {
    if (!active) return;
    // Arbitrary shell syntax cannot be safely classified as read-only.
    // Lean context comes from MCP; candidate evaluation comes from arena_evaluate.
    if (event.toolName === "bash" || event.toolName === "powershell") {
      return { block: true, reason: "Bash is disabled while an Arena target is active; use Lean MCP or arena_evaluate." };
    }
    if (event.toolName.startsWith("mcp__arena_lean__") && leanProject) {
      const reason = await leanPathViolation(event.input as { file_path?: unknown; path?: unknown }, leanProject);
      if (reason) return { block: true, reason };
    }
    if (event.toolName === "write" || event.toolName === "edit") {
      const input = event.input as { path?: string };
      if (input.path) {
        const candidate = resolve(ctx.cwd, input.path);
        const canonical = await realpath(candidate).catch(async () => {
          const parent = await realpath(dirname(candidate)).catch(() => dirname(candidate));
          return resolve(parent, candidate.split(sep).at(-1)!);
        });
        if (inside(candidate, workspaces) || inside(canonical, workspaces)) {
          return { block: true, reason: "Arena workspaces are read-only semantic context." };
        }
      }
    }
  });

  pi.on("tool_execution_start", event => {
    if (!openAttempt) return;
    appendTrace({ kind: "tool_call", id: openAttempt, tool_call_id: event.toolCallId,
      name: event.toolName, args: event.args });
  });

  const untrimmed = new Map<string, string>();
  pi.on("tool_execution_end", event => {
    const result = event.result as { content?: Array<{ type?: string; text?: string }> } | undefined;
    const payload = payloadFromToolResult(result);
    if (event.toolName === "arena_probe" || event.toolName === "arena_evaluate") {
      const attempted = (item: any) => Boolean(item && item.ok !== false &&
        (item.candidate || item.probe || item.candidate_id || item.compat));
      turnHadProofAttempt ||= Boolean(payload && payload.ok !== false &&
        (attempted(payload) || (payload.drafts ?? []).some(attempted)));
    }
    // A repeated identical result reaches here as the trimmer's `unchanged` stub: nothing new was read.
    const keys = payload?.unchanged === true ? [] : discoveryKeys(event.toolName, payload);
    if (event.toolName.endsWith("lean_goal") && !payload) {
      const goalText = (result?.content ?? []).filter(part => part?.type === "text")
        .map(part => part.text ?? "").join("\n").trim();
      if (goalText) keys.push(`goal:${goalText}`);
    }
    for (const key of keys) {
      const signature = createHash("sha256").update(key).digest("hex");
      if (discoveries.has(signature)) continue;
      turnHadNovelContext = true;
      discoveries.add(signature);
      appendCost({ kind: "discovery", signature, tool: event.toolName });
    }
    if (!openAttempt) return;
    const text = Array.isArray(result?.content)
      ? result.content.filter(part => part?.type === "text" && part.text).map(part => part.text).join("\n")
      : "";
    // `tool_result` runs before this event, so the trace takes the untrimmed text it stashed.
    const full = untrimmed.get(event.toolCallId);
    untrimmed.delete(event.toolCallId);
    appendTrace({ kind: "tool_result", id: openAttempt, tool_call_id: event.toolCallId,
      name: event.toolName, result: event.result, text: full ?? text, ...(full !== undefined ? { trimmed: true } : {}),
      is_error: event.isError });
  });

  pi.on("tool_result", event => {
    if (!active) return;
    // Errors reach the model untouched; only successful results are trimmed (the trace keeps the full text).
    const content = event.isError ? event.content : event.content.map(part => {
      if (part.type !== "text" || !part.text) return part;
      const text = trimmer.trim(event.toolName, event.input, part.text);
      return text === part.text ? part : { ...part, text };
    });
    const changed = content.some((part, index) => part !== event.content[index]);
    if (changed) untrimmed.set(event.toolCallId, event.content.filter(part => part.type === "text" && part.text)
      .map(part => (part as { text: string }).text).join("\n"));
    const state = readState();
    const stateText = state && stateLine(state);
    let spend = "";
    try { spend = budgetFooter(costState().spent, budgetLimits()); } catch { /* the footer is best effort */ }
    const line = spend ? (stateText ? `${stateText} \u00b7 ${spend}` : `[arena] ${spend}`) : stateText;
    if (!line && !changed) return;
    return { content: line ? [...content, { type: "text" as const, text: line }] : content,
      details: event.details, isError: event.isError };
  });

  pi.on("context", event => {
    let changed = false;
    const messages = event.messages.map(message => {
      if (message.role !== "toolResult" || !message.isError) return message;
      const first = message.content.find(part => part.type === "text") as { text?: string } | undefined;
      const name = first?.text?.trim().match(/^Tool (\S+) not found$/)?.[1];
      const suggestion = name && nearestToolName(name, pi.getActiveTools());
      if (!suggestion) return message;
      changed = true;
      return { ...message, content: [...message.content, { type: "text" as const,
        text: `Closest registered tool: ${suggestion}.` }] };
    });
    return changed ? { messages } : undefined;
  });

  const dropEmpty = <T extends Record<string, any>>(value: T): T => Object.fromEntries(Object.entries(value)
    .filter(([, item]) => item !== undefined && item !== null && !(Array.isArray(item) && !item.length))) as T;

  const reply = (result: Record<string, any>) =>
    ({ isError: result.ok === false, content: [{ type: "text" as const, text: JSON.stringify(result) }], details: result });

  // One harness line when a route's attempts keep leaving goal states it already had. Route fingerprints are filed in the
  // background, so a streak can surface on the call after the attempt that completed it.
  async function withStaleNotice(result: ReturnType<typeof reply>) {
    const notice = staleNotice((await campaign("frontier")).routes ?? [], staleNoticed);
    return notice ? { ...result, content: [...result.content, { type: "text" as const, text: notice }] } : result;
  }

  // Write the proof to a scratch file so the campaign CLI never sees it on argv.
  async function withProofFile<T>(proof: string | undefined, run: (file?: string) => Promise<T>): Promise<T> {
    // Models often fill optional string fields with "" next to `candidate`; that is no proof.
    if (proof === undefined || !proof.trim()) return run(undefined);
    const directory = await mkdtemp(resolve(tmpdir(), "arena-proof-"));
    try {
      const file = resolve(directory, "proof.lean");
      await writeFile(file, proof, "utf8");
      return await run(file);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  }

  async function withProofFiles<T>(proofs: string[], run: (files: string[]) => Promise<T>): Promise<T> {
    const directory = await mkdtemp(resolve(tmpdir(), "arena-proofs-"));
    try {
      const files = await Promise.all(proofs.map(async (proof, index) => {
        const file = resolve(directory, `draft-${index + 1}.lean`);
        await writeFile(file, proof, "utf8");
        return file;
      }));
      return await run(files);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  }

  // Declaring a new idea closes the idea that was current, from outcomes the harness already knows: it
  // succeeded when it produced the best candidate so far, was abandoned when it made attempts without that,
  // and was parked when nothing was attempted. The reason is recorded; an explicit arena_idea status still wins.
  async function createIdea(args: string[], knownId?: string) {
    const before = await campaign("frontier");
    const previous = before.ok === false ? undefined : before.current_idea;
    if (knownId && (before.ideas ?? []).some((row: any) => row.id === knownId)) return { result: await campaign("idea", args), closed: [] };
    const result = await campaign("idea", args);
    const closed: string[] = [];
    if (result.ok !== false && result.id && previous && previous.id !== result.id && previous.status === "active") {
      const attempts = Number(previous.attempts ?? 0);
      const produced = previous.best?.candidate && previous.best.candidate === before.best?.candidate;
      const [status, reason] = produced
        ? ["succeeded", `auto: produced the best candidate so far (${briefText(previous.best)}); superseded by ${result.id}`]
        : attempts > 0
          ? ["abandoned", `auto: ${attempts} attempt${attempts === 1 ? "" : "s"} did not produce the best candidate${previous.best ? ` (best ${briefText(previous.best)})` : ""}; superseded by ${result.id}`]
          : ["parked", `auto: no attempt was made before ${result.id} was declared`];
      const update = await campaign("idea", ["--idea-id", previous.id, "--status", status, "--reason", reason]);
      if (update.ok !== false) closed.push(`${previous.id} ${status}`);
    }
    return { result, closed };
  }

  const inlineIdea = (params: { idea?: string; idea_id?: string }) =>
    resolveInlineIdea(params, async title => (await createIdea(["--title", title])).result);

  registerTool({
    name: "arena_evaluate",
    label: "Arena evaluate",
    description: "Score a complete theorem (statement + proof) on the primary toolchain. Give `proof`, or an existing node with `candidate` (\"#N\"), or a probe with `from_probe` (\"pN\"). If it compiles, the harness checks the other toolchains in the background and reports the outcome in a later tool result; you never need to request it. `parents`, `idea_id`, `idea` (a one-line route title that creates the idea) and `hypothesis` are optional labels; the current candidate is the default parent. If `proof` comes with `candidate`, the proof is scored and that candidate becomes its parent. Returns tokens, heartbeats, per-axis contribution, estimated proxy, deltas, and diagnostics whose file_line matches the candidate file lean_goal reads.",
    parameters: Type.Object({
      proof: Type.Optional(Type.String({ description: "Complete theorem statement and replacement proof" })),
      candidate: Type.Optional(Type.String({ description: "Existing node such as #4" })),
      from_probe: Type.Optional(Type.String({ description: "Probe id such as p2" })),
      parents: Type.Optional(Type.Array(Type.String())),
      hypothesis: Type.Optional(Type.String()),
      idea_id: Type.Optional(Type.String()),
      idea: Type.Optional(Type.String({ description: "One-line route title; creates the idea and links this attempt to it" })),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      if (!active) throw new Error("Select a theorem with /arena first");
      const plan = planEvaluate(params);
      if (!plan.ok) return reply({ ok: false, error: "usage_error", detail: plan.detail });
      const idea = await inlineIdea(params);
      if (!idea.ok) return reply(idea.error);
      const result = await withProofFile(plan.proof, file => {
        const args = ["--mode", "fast"];
        if (file) args.push("--proof-file", file);
        if (plan.candidate) args.push("--candidate", plan.candidate);
        if (plan.fromProbe) args.push("--from-probe", plan.fromProbe);
        for (const parent of plan.parents) args.push("--parent", parent);
        if (params.hypothesis) args.push("--hypothesis", params.hypothesis);
        if (idea.idea_id) args.push("--idea-id", idea.idea_id);
        return campaign("evaluate", args);
      });
      kickAutocheck();
      return withStaleNotice(reply({ ...result, ...(idea.created ? { idea_id: idea.idea_id } : {}), ...(plan.note ? { note: plan.note } : {}), remaining_usd: Number(budgetStatus(ctx)?.remaining_usd?.toFixed(4)) }));
    },
  });

  registerTool({
    name: "arena_probe", label: "Arena probe",
    description: "Compile one proof draft or one to four drafts on the primary toolchain. Each may be a complete theorem, a `by` proof body, or a `:=` proof body; the exact benchmark statement is supplied for proof bodies. `sorry` is allowed and each incomplete draft returns its actual hole goals and stable pN ID. A draft with `sorry` holes that elaborates is fingerprinted and opens a route; filling the holes later stays on that route. A probe takes several drafts at once (two or three is typical). A complete compiling draft is automatically promoted to a candidate. `idea` (a one-line route title) creates an idea and links the attempt to it.",
    parameters: Type.Object({ proof: Type.Optional(Type.String()),
      drafts: Type.Optional(Type.Array(Type.String(), { minItems: 1, maxItems: 4 })),
      idea_id: Type.Optional(Type.String()), parent: Type.Optional(Type.String()),
      idea: Type.Optional(Type.String({ description: "One-line route title; creates the idea and links this attempt to it" })) }),
    async execute(_id, params) {
      if (!active) throw new Error("Select a theorem with /arena first");
      const plan = planProbe(params);
      if (!plan.ok) return reply({ ok: false, error: "usage_error", detail: plan.detail });
      const idea = await inlineIdea(params);
      if (!idea.ok) return reply(idea.error);
      const withIdea = (result: Record<string, any>) => withStaleNotice(reply({ ...result,
        ...(idea.created ? { idea_id: idea.idea_id } : {}), ...(plan.note ? { note: plan.note } : {}) }));
      if (plan.proof !== undefined) {
        const result = await withProofFile(plan.proof, file => {
          const args = ["--proof-file", file!];
          if (idea.idea_id) args.push("--idea-id", idea.idea_id);
          if (params.parent) args.push("--parent", params.parent);
          return campaign("probe", args);
        });
        if (result.candidate) kickAutocheck();
        return withIdea(result);
      }
      const result = await withProofFiles(plan.drafts!, files => {
        const args: string[] = [];
        for (const file of files) args.push("--draft-file", file);
        if (idea.idea_id) args.push("--idea-id", idea.idea_id);
        if (params.parent) args.push("--parent", params.parent);
        return campaign("probe", args);
      });
      if (result.drafts?.some((draft: any) => draft.candidate)) kickAutocheck();
      return withIdea(result);
    },
  });

  registerTool({
    name: "arena_profile", label: "Arena heartbeat profile",
    description: "Per-tactic heartbeat profile of a compiling proof: heartbeats per proof line or tactic block (inclusive and self), share of the total, nesting, the top self costs with cumulative share, and how the profiled total relates to the measured whole-proof heartbeats. Give `candidate` (\"#N\" or probe \"pN\"), `proof`, or nothing for the current candidate. Informational only; it makes no recommendation.",
    parameters: Type.Object({ candidate: Type.Optional(Type.String()), proof: Type.Optional(Type.String()) }),
    async execute(_id, params) {
      if (!active) throw new Error("Select a theorem with /arena first");
      return reply(trimProfile(await withProofFile(params.proof, file => {
        const args: string[] = [];
        if (file) args.push("--proof-file", file);
        if (params.candidate) args.push("--candidate", params.candidate);
        return campaign("profile", args);
      })));
    },
  });

  registerTool({
    name: "arena_idea", label: "Record or update an idea",
    description: "Create an idea (title, hypothesis, region such as proof lines \"12-30\", expected_effect per axis), optionally naming it yourself with idea_id; or update an existing idea by idea_id: set status active, parked, succeeded or abandoned with a reason. Ideas are yours; the harness only records them. Declaring a new idea closes the one that was current from the harness's own outcomes (succeeded if it produced the best candidate so far, abandoned if it made attempts without doing so, parked if it had none) and records that reason, so a separate status call is only needed to override it. The reply is a one-line acknowledgement.",
    parameters: Type.Object({
      idea_id: Type.Optional(Type.String()), title: Type.Optional(Type.String()),
      hypothesis: Type.Optional(Type.String()), region: Type.Optional(Type.String()),
      expected_effect: Type.Optional(Type.Object({ tokens: Type.Optional(Type.String()),
        heartbeats: Type.Optional(Type.String()), compat: Type.Optional(Type.String()) })),
      status: Type.Optional(Type.Union([Type.Literal("active"), Type.Literal("parked"),
        Type.Literal("succeeded"), Type.Literal("abandoned")])),
      reason: Type.Optional(Type.String()),
    }),
    async execute(_id, params) {
      const args: string[] = [];
      if (params.idea_id) args.push("--idea-id", params.idea_id);
      if (params.title) args.push("--title", params.title);
      if (params.hypothesis) args.push("--hypothesis", params.hypothesis);
      if (params.region) args.push("--region", params.region);
      if (params.expected_effect) args.push("--expected-effect", JSON.stringify(params.expected_effect));
      if (params.status) args.push("--status", params.status);
      if (params.reason) args.push("--reason", params.reason);
      // One-line acknowledgement: the idea's text is already in the model's own call.
      const { result, closed } = params.title ? await createIdea(args, params.idea_id) : { result: await campaign("idea", args), closed: [] as string[] };
      if (result.ok === false) return reply(result);
      return reply({ ok: true, id: result.id, status: result.status, ...(closed.length ? { closed } : {}) });
    },
  });

  registerTool({
    name: "arena_state", label: "Arena run state",
    description: "Show the best verified candidate, pinned original baseline, leading unchecked result, active idea with attempt count, and recent failures. Read-only and concise; no title or hypothesis is needed.",
    parameters: Type.Object({}),
    async execute() {
      const [checks, portfolio] = await Promise.all([campaign("state"), campaign("frontier")]);
      if (checks.ok === false) return reply(checks);
      if (portfolio.ok === false) return reply(portfolio);
      // Compact: only fields the model acts on; the baseline is in the packet and history is in the ledger.
      const idea = portfolio.current_idea;
      return reply(dropEmpty({ ok: true, best_verified: checks.best ?? "none", leading_unverified: checks.leading_unverified,
        checking: checks.checking?.length ? checks.checking : undefined,
        current_idea: idea ? { id: idea.id, title: idea.title, attempts: idea.attempts } : undefined,
        recent_failures: (portfolio.recent_failures ?? []).map((row: any) => ({ ref: row.ref, error: String(row.error ?? "").slice(0, 160) })),
        routes: (portfolio.routes ?? []).filter((row: any) => row.attempts > 0 || row.original).map((row: any) => dropEmpty({ route: row.route,
          original: row.original || undefined, attempts: row.attempts, goal_states: row.depth, min_holes: row.min_holes,
          stale_streak: row.stale_streak || undefined, status: row.explored ? "explored" : "opened", credited: row.credited || undefined,
          best_proxy: row.best_proxy })) }));
    },
  });

  registerTool({
    name: "arena_finish", label: "Review and finish the Arena run",
    description: "Request to stop the run. A confirm is accepted once 10% or less of the spend allowance remains. Before that, the call is refused with the amount spent and left, the routes tried and the current best's saving per score axis (compat, tokens, heartbeats). With 10% or less left, the first call returns one factual review (with at most one reminder if the current idea has no proof attempt) and a second call after the decision turn confirms the stop; finishing is final for this run.",
    parameters: Type.Object({}),
    async execute() {
      if (finishConfirmed) return reply({ ok: true, phase: "confirmed", stop: true });
      const [checks, portfolio, answer] = await Promise.all([
        campaign("state"), campaign("frontier"), campaign("submission"),
      ]);
      if (checks.ok === false) return reply(checks);
      if (portfolio.ok === false) return reply(portfolio);
      const limits = budgetLimits();
      const spent = costState().spent;
      const room = finishAllowed(spent, limits);
      const idea = portfolio.current_idea ?? null;
      const bestVerified = answer.candidate ? { candidate: answer.candidate, tokens: answer.tokens,
        heartbeats: answer.heartbeats, proxy: answer.proxy, status: "cold verified" } : checks.best;
      // Facts the stop decision depends on: how much of the allowance is left and which routes were tried.
      const budget = { spent_usd: Number(spent.toFixed(4)), cap_usd: limits.stopUsd,
        remaining_usd: Number(room.remainingUsd.toFixed(4)), used_pct: Math.round(100 * spent / limits.stopUsd) };
      const ideaRows: any[] = portfolio.ideas ?? [];
      const firstReview = !finishReviewIssued;
      let reminder = false;
      if (firstReview) {
        finishReviewIssued = true;
        finishReviewTurn = true;
        reminder = Boolean(idea && idea.attempts === 0 && !finishReminderIssued);
        if (reminder) finishReminderIssued = true;
        appendCost({ kind: "finish", phase: "review", current_idea_id: idea?.id ?? null,
          reminder_issued: reminder, remaining_fraction: Number(room.remainingFraction.toFixed(4)) });
        if (reminder) appendCost({ kind: "finish", phase: "reminder", current_idea_id: idea.id });
      }
      const reminderText = reminder ? `Idea ${idea.id} has no linked proof attempt; probe it or abandon it before finishing.` : null;
      if (!room.allowed) {
        // More than 10% of the allowance is left: refuse, stating the facts.
        const newIdeaProbed = ideaRows.some(row => row.attempts > 0 && !refusalIdeaIds.has(String(row.id)));
        const routeRows: any[] = portfolio.routes ?? [];
        const since = sinceRefusal(routeRows, refusalRouteStats, refusalCredited);
        const push = finishPush({ usedPct: budget.used_pct, remainingUsd: room.remainingUsd, capUsd: limits.stopUsd,
          baseline: checks.baseline, best: bestVerified, top: portfolio.top, ideas: ideaRows,
          refusals: finishRefusals, newIdeaProbed, routes: portfolio.routes, sinceRefusal: since });
        finishRefusals += 1;
        refusalIdeaIds = new Set(ideaRows.map(row => String(row.id)));
        refusalRouteStats = Object.fromEntries(routeRows.map(row => [String(row.route), { attempts: row.attempts ?? 0, new_states: row.new_states ?? 0 }]));
        refusalCredited = new Set(routeRows.filter(row => row.credited).map(row => String(row.route)));
        appendCost({ kind: "finish", phase: "refused", refusals: finishRefusals, idea_ids: [...refusalIdeaIds], route_stats: refusalRouteStats, credited_ids: [...refusalCredited],
          new_idea_probed: newIdeaProbed, since_refusal: since, remaining_fraction: Number(room.remainingFraction.toFixed(4)) });
        // `next` already carries the spend, the routes tried and the headroom; nothing is echoed twice.
        return reply(dropEmpty({ ok: true, phase: firstReview ? "review" : "refused", stop: false, refused: true,
          remaining_usd: budget.remaining_usd, reminder: reminderText, next: push.message }));
      }
      if (firstReview) {
        return reply(dropEmpty({ ok: true, phase: "review", best_verified: bestVerified ?? "none", reminder: reminderText,
          remaining_usd: budget.remaining_usd, used_pct: budget.used_pct,
          routes_tried: routesText(portfolio.routes ?? []),
          next: `${budget.used_pct}% of the $${limits.stopUsd} allowance is spent ($${budget.remaining_usd} left, within the final 10%). ` +
            "Use this decision turn to try another route if one is worth it, then call arena_finish again to confirm stop." }));
      }
      finishConfirmed = true;
      appendCost({ kind: "finish", phase: "confirmed" });
      const stop = gateStopReason ? gateStopCode ?? "estimated_request_unaffordable"
        : softCapGate(costState().spent, budgetLimits()).stop ?? "finished";
      appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
        error_streak: errorStreak, progress: previousProgress, stop,
        ...(gateStopReason ? { gate_stop_reason: gateStopReason } : {}) });
      return reply({ ok: true, phase: "confirmed", stop: true, best_verified: bestVerified });
    },
  });

  registerTool({
    name: "arena_candidate", label: "Restore a candidate or probe",
    description: "Restore node \"#N\" or probe \"pN\" into the Lean scratch project (so lean_goal reads it) and return its exact proof and recorded results.",
    parameters: Type.Object({ candidate: Type.String({ description: "#N or pN" }) }),
    async execute(_id, params) { return reply(await campaign("candidate", ["--candidate", params.candidate])); },
  });

  registerTool({
    name: "arena_skill_read", label: "Read Arena skill reference",
    description: "Read a file from the Arena Lean skill (for example references/proof-golfing.md). Without `path`, list the available files. Read-only and scoped to the skill directory.",
    parameters: Type.Object({ path: Type.Optional(Type.String()), offset: Type.Optional(Type.Number()) }),
    async execute(_id, params) {
      const base = process.env.ARENA_SKILL_DIR;
      if (!base) return reply({ ok: false, error: "No Arena skill is loaded for this run" });
      const skillRoot = await realpath(base);
      if (!params.path) {
        const files: string[] = [];
        for (const entry of await readdir(skillRoot, { recursive: true, withFileTypes: true })) {
          if (entry.isFile()) files.push(relative(skillRoot, resolve(entry.parentPath, entry.name)));
        }
        return reply({ ok: true, files: files.sort() });
      }
      const target = await realpath(resolve(skillRoot, params.path)).catch(() => undefined);
      if (!target || !inside(target, skillRoot)) {
        return reply({ ok: false, error: `${params.path} is not a file of the Arena skill; call without path to list files` });
      }
      if (!(await stat(target)).isFile()) return reply({ ok: false, error: `${params.path} is a directory` });
      const text = await readFile(target, "utf8");
      const start = Math.max(0, params.offset ?? 0);
      const slice = text.slice(start, start + SKILL_READ_LIMIT);
      return reply({ ok: true, path: relative(skillRoot, target), offset: start, total_chars: text.length,
        next_offset: start + SKILL_READ_LIMIT < text.length ? start + SKILL_READ_LIMIT : null, text: slice });
    },
  });

  registerTool({
    name: "arena_source", label: "Pinned Lean source",
    description: "Read pinned source by a decl:<qualified-name> handle or a project/dependency path alias (up to 400 lines per call; next_first continues; a decl: handle without first starts at its declaration). Reports the pin, canonical path and file length.",
    parameters: Type.Object({ handle: Type.String(), first: Type.Optional(Type.Number()), last: Type.Optional(Type.Number()) }),
    async execute(_id, params) {
      const args = ["--handle", params.handle];
      if (params.first !== undefined) args.push("--first", String(params.first));
      if (params.last !== undefined) args.push("--last", String(params.last));
      return reply(await campaign("source", args));
    },
  });

  registerTool({
    name: "arena_declarations", label: "Pinned declarations",
    description: "Read several declarations by qualified name or decl: handle. Returns full pinned source bodies, typed unavailable reasons, local scope/type, or per-name misses. Use next_cursor to continue a long batch.",
    // One object schema: providers reject a top-level anyOf. Exactly one of the two fields is used.
    parameters: Type.Object({ items: Type.Optional(Type.Array(Type.String())), cursor: Type.Optional(Type.String()) }),
    async execute(_id, params) {
      if ((params.items === undefined) === (params.cursor === undefined)) {
        return reply({ ok: false, error: "usage_error",
          detail: "Pass exactly one of items (a nonempty list of names or decl: handles) or cursor (next_cursor from a previous page)." });
      }
      const args = [];
      if (params.items !== undefined) args.push("--items", JSON.stringify(params.items));
      if (params.cursor !== undefined) args.push("--cursor", params.cursor);
      return reply(await campaign("declarations", args));
    },
  });

  registerTool({
    name: "arena_find", label: "Search pinned declarations",
    description: "Search pinned source by several names or text queries. Results are distinct qualified declarations with name, decl: handle, path, line and signature (not the body; read bodies with arena_declarations), counted toward limit; at most 30 files are scanned per query and files_truncated reports more. Misses include qualified-name suggestions.",
    parameters: Type.Object({ queries: Type.Array(Type.String()), limit: Type.Optional(Type.Number()) }),
    async execute(_id, params) {
      const args = ["--queries", JSON.stringify(params.queries)];
      if (params.limit !== undefined) args.push("--limit", String(params.limit));
      return reply(await campaign("find", args));
    },
  });

  pi.on("agent_before_settle", async event => {
    if (process.env.ARENA_AUTOCONTINUE !== "1" || !active || !runId) return;
    const budget = costState();
    const limits = budgetLimits();
    const state = await campaign("frontier");
    const progress = JSON.stringify(state.best ?? null);
    // Only a turn that produced a real model response counts as work. Provider or extension
    // errors back off and eventually stop the run instead of burning continuations.
    const failed = event.outcome !== "completed";
    errorStreak = failed ? errorStreak + 1 : 0;
    let activity = { proof_attempt: turnHadProofAttempt, novel_context: turnHadNovelContext,
      verified_improvement: turnHadVerifiedImprovement, finish_review: finishReviewTurn };
    if (!failed) {
      if (progress === previousProgress) plateau += 1;
      else plateau = 0;
      previousProgress = progress;
      const reviewTurn = finishReviewTurn;
      finishReviewTurn = false;
      turnHadVerifiedImprovement ||= verifiedImproved(state.best, previousVerified);
      activity = { proof_attempt: turnHadProofAttempt, novel_context: turnHadNovelContext,
        verified_improvement: turnHadVerifiedImprovement, finish_review: reviewTurn };
      previousVerified = state.best ?? null;
      if (reviewTurn) noWorkTurns = 0;
      else if (turnHadProofAttempt || turnHadNovelContext || turnHadVerifiedImprovement) noWorkTurns = 0;
      else noWorkTurns += 1;
    }
    const softStop = softCapGate(budget.spent, limits).stop;
    const stop = gateStopReason ? gateStopCode ?? "estimated_request_unaffordable"
      : softStop ? softStop
      : finishConfirmed ? "finished"
      : errorStreak >= MAX_ERROR_STREAK ? "error_loop"
      : continuations >= 12 ? "continuation_limit"
      : noWorkTurns >= 2 ? "no_work_fallback"
      // A plateau only ends the run inside the final 10%; earlier the model must try a new route.
      : continuations >= 4 && plateau >= 4 && finishAllowed(budget.spent, limits).allowed ? "plateau" : null;
    turnHadProofAttempt = false;
    turnHadNovelContext = false;
    turnHadVerifiedImprovement = false;
    if (stop) {
      const latestControl = costEvents().filter(item => item.kind === "control").at(-1);
      if (latestControl?.stop !== stop) {
        appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
          error_streak: errorStreak, progress, ...activity, stop,
          ...(gateStopReason ? { gate_stop_reason: gateStopReason } : {}) });
      }
      return { continue: false };
    }
    if (failed) {
      const delay = Math.min(30_000, Number(process.env.ARENA_BACKOFF_MS ?? 2000) * 2 ** (errorStreak - 1));
      appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
        error_streak: errorStreak, progress, ...activity, stop: null, backoff_ms: delay });
      await new Promise(done => setTimeout(done, delay));
    } else {
      continuations += 1;
      appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
        error_streak: errorStreak, progress, ...activity, stop: null });
    }
    const ideas = (state.ideas ?? []).filter((idea: any) => idea.status === "active")
      .map((idea: any) => `${idea.id} ${idea.title}`);
    const current = readState();
    const status = current ? stateLine(current, true) : `[arena] best verified: ${briefText(state.best)}`;
    const room = finishAllowed(budget.spent, limits);
    const content = !room.allowed
      ? continuationPush({ status, ideas, remainingUsd: room.remainingUsd, capUsd: limits.stopUsd, routes: state.routes })
      : `Continue proof optimization. ${status}. Active ideas: ${ideas.length ? ideas.join("; ") : "none recorded"}. Remaining on the $${limits.stopUsd} cap (actual settled spend): $${softCapGate(budget.spent, limits).remainingUsd.toFixed(4)}.`;
    return { entries: [...event.entries, { type: "custom_message" as const, customType: "arena-continuation",
      content, display: false }], continue: true };
  });
}
