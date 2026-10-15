import { AsyncLocalStorage } from "node:async_hooks";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, chmodSync, closeSync, fsyncSync, mkdirSync, openSync, readFileSync } from "node:fs";
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve, relative, sep } from "node:path";
import { Type } from "typebox";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { nearestToolName, normalizeToolArguments, requireToolArguments } from "./toolnames.ts";
import { BlobStore, DeltaChain, splitRequest, stampRecord } from "./journal.ts";
import { nothingToSummarize, objectToolArguments, ResultTrimmer } from "./trim.ts";
import { stopDecision } from "./control.ts";
import { continuationFacts, continuationPush } from "./rules.ts";
import { cacheAlarm, cacheHitPct, callCost, finishAllowed, limitReached, limitUsd, spendFooter } from "./spend.ts";
import { numbers as textNumbers, render as renderText } from "./text.ts";
import { classifyFailure, nextWait } from "./outage.ts";
import { applyToolTurnEffort } from "./thinking.ts";
import { renderReply } from "./reply.ts";

const root = resolve(import.meta.dirname, "../../..");
const workspaces = resolve(root, "workspaces");
const MAX_ERROR_STREAK = 3;
const ARENA_TOOLS = new Set(["compile", "goal", "search", "read", "scratch"]);

function validObjectJson(raw: string | undefined): boolean {
  if (raw === undefined) return false;
  try {
    const value: unknown = JSON.parse(raw);
    return value !== null && typeof value === "object" && !Array.isArray(value);
  } catch {
    return false;
  }
}

/** The raw argument JSON of each streamed tool call, in the order Pi's stream delivered it. */
class RawArguments {
  private raw = new Map<number, string>();
  reset() { this.raw.clear(); }
  start(index: number, partialJson: string | undefined) { if (partialJson !== undefined) this.raw.set(index, partialJson); }
  delta(index: number, text: string) { this.raw.set(index, (this.raw.get(index) ?? "") + text); }
  get(index: number) { return this.raw.get(index); }
}

/**
 * Pi parses failed JSON as {} before tool validation. A tool call whose streamed arguments were not an
 * object gets `null` arguments instead (`null` is deliberately not an object, so even argument-free tools
 * fail validation instead of running with invented defaults). Returns the repaired message, or undefined
 * when every tool call was fine.
 */
function repairMalformedToolArguments(message: AssistantMessage, raw: RawArguments): AssistantMessage | undefined {
  let changed = false;
  const content = message.content.map((block, index) => {
    if (block.type !== "toolCall" || validObjectJson(raw.get(index))) return block;
    changed = true;
    return { ...block, arguments: null } as unknown as typeof block;
  });
  return changed ? { ...message, content } : undefined;
}

function inside(path: string, parent: string): boolean {
  const rel = relative(parent, path);
  return rel === "" || (rel !== ".." && !rel.startsWith(`..${sep}`));
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

export default async function arenaExtension(pi: ExtensionAPI) {
  const sharedNumbers = await textNumbers();
  // One store for the tool call that is executing. campaign() reads it when it spawns the Python child.
  const toolContext = new AsyncLocalStorage<{ toolCallId: string; requestId?: string; turn: number }>();
  let requestId: string | undefined;
  let turn = 0;
  // Every tool uses its schema keys for malformed-argument errors and cleaned arguments.
  const registerTool = async (tool: any) => {
    const validKeys = Object.keys(tool.parameters.properties ?? {});
    const missingError = await renderText("messages/errors.empty_arguments", { valid: validKeys.join(", ") || "none" });
    // Normalized before Pi's schema validation, so an empty optional enum ("view": "") or a stringified list passes.
    return pi.registerTool({ ...tool,
    prepareArguments: (args: unknown) => normalizeToolArguments(requireToolArguments(args, missingError), tool.parameters),
    execute: (id: string, params: any, ...rest: any[]) => toolContext.run(
      { toolCallId: id, requestId, turn },
      () => tool.execute(id, normalizeToolArguments(params, tool.parameters), ...rest)) });
  };
  // Providers Pi does not ship (models.yaml `providers`) are registered here; Pi prices their calls from these models.
  const configuredModels = JSON.parse(process.env.ARENA_MODELS_JSON ?? "{}");
  for (const [name, config] of Object.entries(configuredModels.providers ?? {})) pi.registerProvider(name, config as any);
  // A factory invocation owns one Pi session. No active theorem is module-global.
  let active: string | undefined;
  const runId = process.env.ARENA_RUN_ID;
  const runDirectory = runId ? resolve(root, "runs", "pi-budget", runId) : undefined;
  const costJournal = runDirectory ? resolve(runDirectory, "cost-ledger.jsonl") : undefined;
  const traceJournal = runDirectory ? resolve(runDirectory, "trace-journal.jsonl") : undefined;
  const blobs = runDirectory ? new BlobStore(resolve(runDirectory, "blobs")) : undefined;
  // The one spend rule (spend.ts): each call's actual cost is added once, the run stops at the limit.
  const limit = limitUsd();
  const outputLimit = Number(process.env.ARENA_REQUEST_OUTPUT_TOKENS ?? 0);
  let spentUsd = 0;
  let settledCalls = 0;
  let limitHit = false;
  // Tool calls of the message that crossed the limit still running; the run aborts when the last one ends.
  let limitToolsLeft = 0;
  // The provider request currently open: opened in before_provider_request, closed by the call's settle row.
  let pendingRequest: string | undefined;
  let openAttempt: string | undefined;
  let previousFailed: string | undefined;
  const rawArguments = new RawArguments();
  let continuations = 0;
  let plateau = 0;
  let errorStreak = 0;
  let outageStartedAt: number | undefined;
  let outageAttempt = 0;
  let previousProgress = "";
  let noWorkTurns = 0;
  // Spend when the best last changed; the stall restart counts the spend since then.
  let spentAtBestChange = 0;
  let turnHadProofAttempt = false;
  let turnHadNovelContext = false;
  let turnHadVerifiedImprovement = false;
  let previousVerified: Record<string, any> | null | undefined;
  const discoveries = new Set<string>();
  // Model-facing trimming of tool results; its record of what the model has seen resets on compaction.
  const trimmer = new ResultTrimmer();

  async function campaign(action: string, args: string[] = []): Promise<Record<string, any>> {
    if (!active || !runId) throw new Error("Arena run is not selected"); // not-model-facing: internal extension state invariant.
    const commandFailed = await renderText("messages/errors.command_failed");
    const command = ["run", "--no-sync", "arena", "protocol", action,
      "--theorem", active, "--run-id", runId, ...args];
    const output = await new Promise<string>((accept, reject) => {
      const env = { ...process.env };
      delete env.ARENA_TOOL_CALL_ID;
      delete env.ARENA_REQUEST_ID;
      delete env.ARENA_TURN;
      const store = toolContext.getStore();
      if (store) {
        env.ARENA_TOOL_CALL_ID = store.toolCallId;
        if (store.requestId !== undefined) env.ARENA_REQUEST_ID = store.requestId;
        env.ARENA_TURN = String(store.turn);
      }
      const child = spawn("uv", command, { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });
      const chunks: Buffer[] = [];
      const errors: Buffer[] = [];
      child.stdout.on("data", (chunk: Buffer) => chunks.push(chunk));
      child.stderr.on("data", (chunk: Buffer) => errors.push(chunk));
      child.on("error", reject);
      child.on("close", code => code === 0 || chunks.length
        ? accept(Buffer.concat(chunks).toString("utf8"))
        : accept(JSON.stringify({ ok: false, error: (Buffer.concat(errors).toString("utf8").trim().split("\n").at(-1) || commandFailed).replace(/^\w*(Error|Exception): /, "") })));
    });
    try { return JSON.parse(output.trim().split("\n").at(-1) ?? ""); }
    catch { return { ok: false, error: await renderText("messages/errors.command_no_result", { output: output.trim().slice(0, 200) }) }; }
  }

  // Full checks on the other toolchains run in a background checker the harness starts
  // itself. One checker at a time; a kick while it runs makes it go round once more.
  let checker: ReturnType<typeof spawn> | undefined;
  let kickAgain = false;
  function kickAutocheck() {
    if (!active || !runId) return;
    if (checker) { kickAgain = true; return; }
    kickAgain = false;
    checker = spawn("uv", ["run", "--no-sync", "arena", "protocol", "autocheck",
      "--theorem", active, "--run-id", runId], { cwd: root, stdio: "ignore" });
    const done = () => { checker = undefined; if (kickAgain) kickAutocheck(); };
    checker.on("close", done);
    checker.on("error", done);
  }

  function payloadFromToolResult(result: any): Record<string, any> | undefined {
    return result?.details && typeof result.details === "object" ? result.details : undefined;
  }
  function discoveryKeys(toolName: string, payload: Record<string, any> | undefined): string[] {
    if (!payload || payload.ok === false) return [];
    const keys: string[] = [];
    const items = payload.items ?? [];
    if (toolName === "search") {
      for (const item of items) for (const hit of item.hits ?? []) {
        keys.push(JSON.stringify([toolName, hit.handle ?? hit.name ?? "", hit.signature ?? "",
          hit.module ?? "", hit.line ?? ""]));
      }
    } else if (toolName === "read") {
      for (const item of items) {
        keys.push(JSON.stringify([toolName, item.ref ?? "", item.first ?? "", item.last ?? "",
          item.source ?? item.prices ?? item.diff ?? item.steps ?? item.hole ?? item]));
      }
    } else if (toolName === "goal") {
      for (const item of items) keys.push(JSON.stringify([toolName, item.goals ?? item.goal ?? item.lines ?? item]));
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
  function costEvents(): Array<Record<string, unknown>> {
    if (!costJournal) return [];
    try { return readFileSync(costJournal, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line)); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
  }
  function traceEvents(): Array<Record<string, unknown>> {
    if (!traceJournal) return [];
    try { return readFileSync(traceJournal, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line)); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
  }
  function appendCost(event: Record<string, unknown>) {
    if (!costJournal) throw new Error("Arena cost journal is unavailable"); // not-model-facing: internal cost ledger invariant.
    mkdirSync(dirname(costJournal), { recursive: true });
    const fd = openSync(costJournal, "a", 0o600);
    try { appendFileSync(fd, `${JSON.stringify(stampRecord({ ts: Date.now(), ...event }, turn, requestId))}\n`); fsyncSync(fd); } // log: durable cost journal row.
    finally { closeSync(fd); }
  }
  function appendTrace(event: Record<string, unknown>) {
    if (!traceJournal) throw new Error("Arena trace journal is unavailable"); // not-model-facing: internal trace ledger invariant.
    mkdirSync(dirname(traceJournal), { recursive: true });
    const fd = openSync(traceJournal, "a", 0o600);
    try { appendFileSync(fd, `${JSON.stringify(stampRecord({ ts: Date.now(), ...event }, turn, requestId))}\n`); fsyncSync(fd); } // log: durable trace journal row.
    finally { closeSync(fd); }
    chmodSync(traceJournal, 0o600);
  }
  // The post-hook payload is stored as a delta against the previous one (see journal.ts), so the journal grows
  // with what each request adds, not with the whole context every time. Fields that describe the encoding come
  // before the heavy `post_hook`, which stays last in the row.
  const hookChain = new DeltaChain();
  function hookFields(published: unknown) {
    const text = Buffer.from(JSON.stringify(published));
    const { sha256, delta } = hookChain.encode(text);
    return { post_hook_sha256: sha256, post_hook_encoding: delta ? "delta" : "text",
      ...(delta ? { post_hook_prefix: delta.prefix, post_hook_suffix: delta.suffix } : {}),
      post_hook: delta ? delta.middle : text.toString("utf8") };
  }
  pi.on("session_start", (_event, ctx) => {
    active = undefined;
    // The run total is the sum of the ledger's settle rows, so a resumed run continues from its spend.
    const settled = costEvents().filter(item => item.kind === "settle" && item.usage_known !== false);
    spentUsd = settled.reduce((sum, item) => sum + Number(item.usd), 0);
    settledCalls = settled.length;
    limitHit = limitReached(spentUsd, limit);
    limitToolsLeft = 0;
    pendingRequest = undefined;
    previousFailed = undefined;
    const latest = costEvents().filter(item => item.kind === "control").at(-1);
    continuations = Number(latest?.continuations ?? 0);
    plateau = Number(latest?.plateau ?? 0);
    errorStreak = Number(latest?.error_streak ?? 0);
    outageStartedAt = typeof latest?.outage_started_at === "number" ? latest.outage_started_at : undefined;
    outageAttempt = Number(latest?.outage_attempt ?? 0);
    previousProgress = String(latest?.progress ?? "");
    noWorkTurns = Number(latest?.no_work_turns ?? 0);
    // A ledger without the field (written before it existed) starts its stall count at the current spend.
    spentAtBestChange = Number(latest?.spent_at_best_change ?? spentUsd);
    turnHadProofAttempt = false;
    turnHadNovelContext = false;
    turnHadVerifiedImprovement = false;
    previousVerified = undefined;
    discoveries.clear();
    trimmer.forget();
    // A resumed session continues the turn count. Rows written before the first request stay at turn 0.
    requestId = undefined;
    turn = traceEvents().filter(item => item.kind === "request").length;
    for (const item of costEvents()) if (item.kind === "discovery" && typeof item.signature === "string") {
      discoveries.add(item.signature);
    }
  });

  // Every provider request is journaled here. Pi runs extension hook errors to completion without failing
  // the request, so nothing in these two hooks can block a call; the spend limit is enforced after the call.
  pi.on("before_provider_request", (event, ctx) => {
    if (!active || !runDirectory) return;
    let payload = event.payload;
    const configuredModel = configuredModels.models?.[process.env.ARENA_MODEL ?? ""];
    payload = applyToolTurnEffort(payload, configuredModel?.toolTurnReasoningEffort);
    // A fixed per-request output ceiling for the whole run (models.yaml request_output_tokens).
    if (outputLimit > 0 && payload && typeof payload === "object" && !Array.isArray(payload)) {
      const body = payload as Record<string, unknown>;
      const field = typeof body.max_output_tokens === "number" ? "max_output_tokens"
        : typeof body.max_tokens === "number" ? "max_tokens" : undefined;
      if (field && Number(body[field]) > outputLimit) payload = { ...body, [field]: outputLimit };
    }
    // A request still open here was sent outside an agent turn: when Pi compacts in the middle of a turn it
    // makes two sequential summary requests and the first never gets a message_end. The compaction settle row
    // (session_compact) carries the cost of both, under the id of the last.
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    pendingRequest = id;
    openAttempt = id;
    turn += 1;
    requestId = id;
    const stored: Record<string, string> = {};
    if (blobs) {
      const parts = splitRequest(payload);
      for (const key of ["system", "skill", "tools", "packet"] as const) {
        if (parts[key]) stored[key] = blobs.put(parts[key]);
      }
    }
    appendTrace({ kind: "request", id, run_id: runId, retry_of: previousFailed ?? null,
      model: ctx.model?.id ?? process.env.ARENA_MODEL ?? null,
      ...(Object.keys(stored).length ? { blobs: stored } : {}), ...hookFields(payload) });
    return payload === event.payload ? undefined : payload;
  });
  pi.on("after_provider_response", event => {
    if (pendingRequest && traceJournal) appendTrace({ kind: "http_response", id: pendingRequest, status: event.status });
  });

  pi.on("before_agent_start", (_event, ctx) => {
    if (process.env.ARENA_BUDGET_REQUIRED !== "1") return;
    if (!active || limitHit || ctx.model?.id !== (process.env.ARENA_PI_MODEL_ID ?? process.env.ARENA_MODEL)) {
      ctx.abort();
      if (ctx.hasUI) ctx.ui.notify(limitHit ? "The spend limit is already reached." : "Select /arena and the run's model before prompting.", "error"); // log: operator UI notification. // not-model-facing
    }
  });

  // Preserve earlier tool messages byte-for-byte. Rewriting them when a new
  // evaluation arrives invalidates the provider's cached prompt prefix.

  // Add one call's actual cost to the run total and write its settle row. The one place spend changes.
  // A call with no usage (a request that failed before the provider counted tokens) settles at zero.
  // `toolCalls` is the number of tool calls in the message being settled; they still run when the limit is crossed.
  function settle(id: string, usage: AssistantMessage["usage"] | undefined, extra: Record<string, unknown>, ctx: ExtensionContext, toolCalls = 0) {
    const known = Boolean(usage?.totalTokens);
    const usd = known ? callCost(usage) : 0;
    spentUsd += usd;
    const cost = usage?.cost;
    appendCost({ kind: "settle", id, usd, usage_known: known, spent_usd: spentUsd, limit_usd: limit,
      tokens: { input: usage?.input ?? 0, output: usage?.output ?? 0,
        cache_read: usage?.cacheRead ?? 0, cache_write: usage?.cacheWrite ?? 0 },
      ledger_components_usd: { input: cost?.input ?? 0, output: cost?.output ?? 0,
        cacheRead: cost?.cacheRead ?? 0, cacheWrite: cost?.cacheWrite ?? 0 },
      ...extra });
    if (known) settledCalls += 1;
    if (known && usage && extra.source !== "compaction") {
      const alarm = cacheAlarm(usage, settledCalls, cost?.input ?? 0);
      if (alarm) {
        appendCost({ kind: "cache_alarm", id, ...alarm });
        if (alarm.reason === "uncached_input") console.error(`[arena-cache-alarm] request ${alarm.request}: $${alarm.input_usd.toFixed(4)} of uncached input; the stable prefix was not reused`); // not-model-facing: operator diagnostic log.
        else console.error(`[arena-cache-alarm] request ${alarm.request}: wrote ${alarm.write} cache tokens but read ${alarm.read}; the stable prefix was not reused`); // not-model-facing: operator diagnostic log.
      }
    }
    if (known) console.error(`[arena-cost] settled $${usd.toFixed(6)}; cache read ${usage?.cacheRead ?? 0}, write ${usage?.cacheWrite ?? 0}; total $${spentUsd.toFixed(6)}`); // not-model-facing: operator diagnostic log.
    // Stop the agent: no further provider request. A message with tool calls keeps its batch, so the run aborts
    // when the last of those calls ends (tool_execution_end). The turn that follows is closed in agent_before_settle
    // with the limit as the stop reason.
    if (limitReached(spentUsd, limit) && !limitHit) {
      limitHit = true;
      // Recorded here because an aborted run may never reach agent_before_settle.
      appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
        error_streak: errorStreak, progress: previousProgress, stop: "limit_reached",
        outage_started_at: outageStartedAt ?? null, outage_attempt: outageAttempt,
        spent_at_best_change: spentAtBestChange });
      if (toolCalls > 0) limitToolsLeft = toolCalls;
      else ctx.abort();
    }
  }

  pi.on("message_start", event => { if (event.message.role === "assistant") rawArguments.reset(); });
  pi.on("message_update", event => {
    const update = event.assistantMessageEvent;
    if (update.type === "toolcall_start") {
      rawArguments.start(update.contentIndex, (update.partial.content[update.contentIndex] as unknown as { partialJson?: string } | undefined)?.partialJson);
    } else if (update.type === "toolcall_delta") rawArguments.delta(update.contentIndex, update.delta);
  });
  pi.on("message_end", (event, ctx) => {
    if (event.message.role !== "assistant") return;
    const repaired = repairMalformedToolArguments(event.message, rawArguments);
    const message = repaired ?? event.message;
    rawArguments.reset();
    const id = pendingRequest ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    pendingRequest = undefined;
    const blocks = deliveredBlocks(message.content);
    const delivered = { kind: "response", id, content: blocks,
      text: blocks.filter(block => block.type === "text").map(block => String(block.text ?? "")).join(""),
      stop_reason: message.stopReason, response_id: message.responseId ?? null,
      response_model: message.responseModel ?? message.model, error_message: message.errorMessage ?? null };
    const known = Boolean(message.usage?.totalTokens);
    settle(id, message.usage, {}, ctx, blocks.filter(block => block.type === "toolCall").length);
    appendTrace({ ...delivered, settled_usd: known ? callCost(message.usage) : null,
      usage: { input: message.usage?.input ?? 0, output: message.usage?.output ?? 0,
        cache_read: message.usage?.cacheRead ?? 0, cache_write: message.usage?.cacheWrite ?? 0 } });
    // The next request of a failed one is its retry.
    previousFailed = known ? undefined : id;
    if (!known) console.error(`[arena-cost] request ${id} returned no usage`); // not-model-facing: operator diagnostic log.
    return repaired ? { message: repaired } : undefined;
  });
  // A compaction's summary requests have no message_end; Pi records their combined usage on the entry.
  pi.on("session_compact", async (event, ctx) => {
    settle(pendingRequest ?? `${Date.now()}-compaction`, event.compactionEntry.usage, { source: "compaction" }, ctx);
    pendingRequest = undefined;
    if (active && runId) await campaign("reset_delivered");
    trimmer.forget();
    void injectMemory();
  });
  pi.on("session_compact_failed", event => {
    pendingRequest = undefined;
    // A cancelled compaction (the empty-history skip in session_before_compact, or an abort) is not a failure.
    if (event.aborted) return;
    if (costJournal) appendCost({ kind: "compaction_failed" });
    console.error("[arena-compaction-alarm] Compaction failed; context was not replaced."); // log: operator alarm. // not-model-facing
  });
  pi.on("session_before_compact", event => {
    // Nothing to summarize: no summary request is sent, and the skip is logged with an alarm line.
    if (nothingToSummarize(event.preparation)) {
      if (costJournal) appendCost({ kind: "compaction_skipped", reason: "empty_history" });
      console.error("[arena-compaction-alarm] Compaction skipped: no messages to summarize."); // log: operator alarm. // not-model-facing
      return { cancel: true };
    }
    const fixed = objectToolArguments(event.preparation.messagesToSummarize) + objectToolArguments(event.preparation.turnPrefixMessages);
    if (fixed) appendTrace({ kind: "compaction_repair", null_tool_arguments: fixed });
  });

  // After a compaction the harness restates its own record of the run (best node with its price, the map,
  // declarations the best node uses, what was read, open holes) as one hidden message. Built from the ledger,
  // never by the model, and sent only here, so it is not repeated every turn. Pi queues it behind the turn's
  // tool results.
  async function injectMemory() {
    if (!active || !runId) return;
    try {
      const result = await campaign("memory", ["--spent-usd", String(spentUsd), "--cap-usd", String(limit)]);
      if (result.ok === false || typeof result.text !== "string") return;
      appendCost({ kind: "memory", chars: result.text.length });
      pi.sendMessage({ customType: "arena-memory", content: result.text, display: false }, { triggerTurn: false });
    } catch (error) { console.error(`[arena-memory] not injected: ${error}`); }
  }

  // Cache reuse over the agent's assistant messages in the session (compaction summaries excluded).
  function cacheUtilization(entries: readonly SessionEntry[]) {
    const usages = entries.flatMap(entry => entry.type === "message" && entry.message.role === "assistant"
      && entry.message.usage?.totalTokens ? [entry.message.usage] : []);
    const summarize = (items: typeof usages) => {
      const sum = (key: "input" | "cacheRead" | "cacheWrite") => items.reduce((total, usage) => total + (usage[key] ?? 0), 0);
      const read = sum("cacheRead"), write = sum("cacheWrite"), input = sum("input");
      return { read_tokens: read, write_tokens: write, input_tokens: input,
        reuse_pct: cacheHitPct({ input, cacheRead: read, cacheWrite: write }) };
    };
    return { all: summarize(usages), recent_ten: summarize(usages.slice(-10)) };
  }

  pi.on("session_shutdown", async (_event, ctx) => {
    const reportPath = process.env.ARENA_BUDGET_REPORT_PATH;
    if (!reportPath) return;
    const model = ctx.model;
    const report = { session_id: ctx.sessionManager.getSessionId(), theorem: active ?? null,
      limit_usd: limit, provider: model?.provider ?? null, model: model?.id ?? null,
      spent_usd: spentUsd, remaining_usd: Math.max(0, limit - spentUsd),
      overshoot_usd: Math.max(0, spentUsd - limit), can_continue: !limitHit,
      cache_utilization: cacheUtilization(ctx.sessionManager.getEntries()) };
    await mkdir(dirname(reportPath), { recursive: true });
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  });

  pi.registerCommand("arena", {
    description: "Select a benchmark theorem: /arena Core.InitsUpdatesComm", // log: slash-command help shown only in the operator UI. // not-model-facing
    handler: async (name, ctx) => {
      const wanted = name.trim();
      const rows = (await readFile(resolve(root, "benchmark/original/warmup.jsonl"), "utf8"))
        .split("\n").filter(Boolean).map((line) => JSON.parse(line));
      const row = rows.find((item) => item.name === wanted);
      if (!row) {
        // not-model-facing: slash-command error shown to the operator.
        ctx.ui.notify(`Unknown benchmark theorem: ${wanted}`, "error");
        return;
      }
      active = wanted;
      kickAutocheck();
      ctx.ui.notify(`Arena target: ${wanted}`, "info");
    },
  });

  pi.on("tool_call", async (event, ctx) => {
    if (!active) return;
    // Arbitrary shell syntax cannot be safely classified as read-only.
    // The five harness tools provide context and compilation results.
    if (event.toolName === "bash" || event.toolName === "powershell") {
      return { block: true, reason: await renderText("messages/notices.block_shell") };
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
          return { block: true, reason: await renderText("messages/notices.block_workspace") };
        }
      }
    }
  });

  // Pi's tool_execution_end event carries no arguments, so each compile's check is kept from its start.
  const compileChecks = new Map<string, string>();
  pi.on("tool_execution_start", event => {
    // A missing check means a Lean check, as in arena/tools.py.
    if (event.toolName === "compile") compileChecks.set(event.toolCallId, String(event.args?.check ?? "lean"));
    if (!openAttempt) return;
    appendTrace({ kind: "tool_call", id: openAttempt, tool_call_id: event.toolCallId,
      name: event.toolName, args: event.args });
  });

  const untrimmed = new Map<string, string>();
  const footers = new Map<string, string>();
  function textOf(content: unknown): string {
    if (!Array.isArray(content)) return "";
    return content.filter(part => part && typeof part === "object" && part.type === "text" && part.text)
      .map(part => String(part.text)).join("\n");
  }
  function stripFooter(delivered: string, footer: string | undefined): string {
    if (!footer) return delivered;
    if (delivered === footer) return "";
    const suffix = `\n${footer}`;
    return delivered.endsWith(suffix) ? delivered.slice(0, -suffix.length) : delivered;
  }
  pi.on("tool_execution_end", (event, ctx) => {
    // The batch of the message that crossed the limit ends here; after its last result no provider request follows.
    if (limitToolsLeft > 0 && --limitToolsLeft === 0) ctx.abort();
    const result = event.result as { content?: Array<{ type?: string; text?: string }> } | undefined;
    const payload = payloadFromToolResult(result);
    const check = compileChecks.get(event.toolCallId);
    compileChecks.delete(event.toolCallId);
    // Every draft the harness filed as a node (with holes or errors too) carries `node`; a rejected one does not.
    if (event.toolName === "compile" && check === "lean") {
      turnHadProofAttempt ||= Boolean(
        payload?.ok !== false && (payload?.items ?? []).some((item: any) => item?.node && item?.repeat !== true),
      );
    }
    // A scratch run that is not a repeat is work: it tests an idea without filing a node.
    if (event.toolName === "scratch") {
      turnHadNovelContext ||= Boolean(payload?.ok !== false && (payload?.items ?? []).some((item: any) => item?.repeat === false));
    }
    // The trimmer only shortens the model-facing text; `details` keep the full payload, so a repeated identical
    // result yields signatures already in `discoveries` and does not count as novel context.
    const keys = discoveryKeys(event.toolName, payload);
    for (const key of keys) {
      const signature = createHash("sha256").update(key).digest("hex");
      if (discoveries.has(signature)) continue;
      turnHadNovelContext = true;
      discoveries.add(signature);
      appendCost({ kind: "discovery", signature, tool: event.toolName });
    }
    // Taken before the early return so a result outside an open attempt does not leave its footer behind.
    const footer = footers.get(event.toolCallId);
    footers.delete(event.toolCallId);
    if (!openAttempt) return;
    const deliveredText = textOf(result?.content);
    // `tool_result` runs before this event, so the trace takes the untrimmed text and footer it stashed.
    const full = untrimmed.get(event.toolCallId);
    untrimmed.delete(event.toolCallId);
    const withoutFooter = stripFooter(deliveredText, footer);
    // `text` keeps its v6 meaning: the untrimmed text when trimmed, else the delivered text with its footer.
    appendTrace({ kind: "tool_result", id: openAttempt, tool_call_id: event.toolCallId,
      name: event.toolName, result: event.result, text: full ?? deliveredText, delivered_text: withoutFooter,
      ...(footer ? { footer } : {}), ...(full !== undefined ? { trimmed: true } : {}),
      is_error: event.isError });
  });

  pi.on("tool_result", async event => {
    if (!active || !ARENA_TOOLS.has(event.toolName)) return;
    // Errors reach the model untouched; only successful results are trimmed (the trace keeps the full text).
    const content = event.isError ? event.content : await Promise.all(event.content.map(async part => {
      if (part.type !== "text" || !part.text) return part;
      const text = await trimmer.trim(event.toolName, event.input, part.text);
      return text === part.text ? part : { ...part, text };
    }));
    const changed = content.some((part, index) => part !== event.content[index]);
    if (changed) untrimmed.set(event.toolCallId, event.content.filter(part => part.type === "text" && part.text)
      .map(part => (part as { text: string }).text).join("\n"));
    let spend = "";
    try { spend = await spendFooter(spentUsd, limit); } catch { /* the footer is best effort */ }
    if (spend) footers.set(event.toolCallId, spend);
    if (!spend && !changed) return;
    return { content: spend ? [...content, { type: "text" as const, text: spend }] : content,
      details: event.details, isError: event.isError };
  });

  pi.on("context", async event => {
    let changed = false;
    let cutTokens: number | undefined;
    const messages = await Promise.all(event.messages.map(async message => {
      if (message.role === "assistant") {
        cutTokens = message.stopReason === "length" ? message.usage.output : undefined;
        return message;
      }
      if (message.role !== "toolResult" || !message.isError) return message;
      if (cutTokens !== undefined) {
        const notice = await renderText("messages/errors.turn_cut", { tokens: String(cutTokens) });
        changed = true;
        message = { ...message, content: [...message.content, { type: "text" as const, text: notice }] };
      }
      const first = message.content.find(part => part.type === "text") as { text?: string } | undefined;
      const name = first?.text?.trim().match(/^Tool (\S+) not found$/)?.[1];
      const suggestion = name && nearestToolName(name, pi.getActiveTools());
      if (!suggestion) return message;
      changed = true;
      return { ...message, content: [...message.content, { type: "text" as const,
        text: await renderText("messages/notices.closest_tool", { suggestion }) }] };
    }));
    return changed ? { messages } : undefined;
  });

  async function invokeTool(name: string, params: Record<string, unknown>, validKeys: string[]) {
    const directory = await mkdtemp(resolve(tmpdir(), "arena-request-"));
    try {
      const file = resolve(directory, "request.json");
      await writeFile(file, JSON.stringify(params), "utf8");
      return await renderReply(await campaign(name, ["--request-file", file]), "", validKeys);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  }

  const compileParams = Type.Object({
    drafts: Type.Optional(Type.Array(Type.String(), { minItems: 1, maxItems: sharedNumbers.compile_max_drafts,
      description: await renderText("tools/compile.params.drafts") })),
    splice: Type.Optional(Type.Object({
      base: Type.Optional(Type.String({ description: await renderText("tools/compile.params.splice_base") })),
      steps: Type.String({ description: await renderText("tools/compile.params.splice_steps") }),
      text: Type.String({ description: await renderText("tools/compile.params.splice_text") }),
    }, { description: await renderText("tools/compile.params.splice") })),
    fill: Type.Optional(Type.Object({
      hole: Type.String({ description: await renderText("tools/compile.params.fill_hole") }),
      text: Type.String({ description: await renderText("tools/compile.params.fill_text") }),
    }, { description: await renderText("tools/compile.params.fill") })),
    merge: Type.Optional(Type.Object({
      base: Type.Optional(Type.String({ description: await renderText("tools/compile.params.merge_base") })),
      take: Type.Array(Type.Object({
        from: Type.String({ description: await renderText("tools/compile.params.merge_from") }),
        step: Type.String({ description: await renderText("tools/compile.params.merge_step") }),
      }), { description: await renderText("tools/compile.params.merge_take") }),
    }, { description: await renderText("tools/compile.params.merge") })),
    base: Type.Optional(Type.String({ description: await renderText("tools/compile.params.base") })),
    from: Type.Optional(Type.String({ description: await renderText("tools/compile.params.from") })),
    note: Type.Optional(Type.String({ description: await renderText("tools/compile.params.note") })),
    check: Type.Optional(Type.Union([Type.Literal("tokens"), Type.Literal("lean")],
      { description: await renderText("tools/compile.params.check") })),
  });
  await registerTool({
    name: "compile", label: "compile",
    description: await renderText("tools/compile.description"), parameters: compileParams,
    async execute(_id: string, params: Record<string, unknown>) {
      const result = await invokeTool("compile", params, Object.keys(compileParams.properties));
      // Every compile may file a node that still needs its full check on the other toolchains.
      kickAutocheck();
      return result;
    },
  });

  const goalParams = Type.Object({
    node: Type.Optional(Type.String({ description: await renderText("tools/goal.params.node") })),
    hole: Type.Optional(Type.String({ description: await renderText("tools/goal.params.hole") })),
    line: Type.Optional(Type.Number({ description: await renderText("tools/goal.params.line") })),
    try: Type.Optional(Type.Array(Type.String(), { maxItems: sharedNumbers.goal_try_max,
      description: await renderText("tools/goal.params.try") })),
  });
  await registerTool({ name: "goal", label: "Read a goal",
    description: await renderText("tools/goal.description"), parameters: goalParams,
    async execute(_id: string, params: Record<string, unknown>) {
      return invokeTool("goal", params, Object.keys(goalParams.properties));
    },
  });

  const searchParams = Type.Object({
    queries: Type.Optional(Type.Array(Type.String(), { minItems: 1,
      description: await renderText("tools/search.params.queries") })),
    kind: Type.Optional(Type.Union([Type.Literal("name"), Type.Literal("type"), Type.Literal("text")],
      { description: await renderText("tools/search.params.kind") })),
    after: Type.Optional(Type.String({ description: await renderText("tools/search.params.after") })),
  });
  await registerTool({ name: "search", label: "Search declarations",
    description: await renderText("tools/search.description"), parameters: searchParams,
    async execute(_id: string, params: Record<string, unknown>) {
      return invokeTool("search", params, Object.keys(searchParams.properties));
    },
  });

  const readParams = Type.Object({
    handle: Type.Optional(Type.String({ description: await renderText("tools/read.params.handle") })),
    node: Type.Optional(Type.String({ description: await renderText("tools/read.params.node") })),
    hole: Type.Optional(Type.String({ description: await renderText("tools/read.params.hole") })),
    view: Type.Optional(Type.Union([Type.Literal("source"), Type.Literal("prices"), Type.Literal("diff"),
      Type.Literal("outline"), Type.Literal("map")], { description: await renderText("tools/read.params.view") })),
    against: Type.Optional(Type.String({ description: await renderText("tools/read.params.against") })),
  });
  await registerTool({ name: "read", label: "Read pinned context",
    description: await renderText("tools/read.description"), parameters: readParams,
    async execute(_id: string, params: Record<string, unknown>) {
      return invokeTool("read", params, Object.keys(readParams.properties));
    },
  });

  const scratchParams = Type.Object({
    code: Type.String({ description: await renderText("tools/scratch.params.code") }),
  });
  await registerTool({ name: "scratch", label: "Scratch Lean commands",
    description: await renderText("tools/scratch.description"), parameters: scratchParams,
    async execute(_id: string, params: Record<string, unknown>) {
      return invokeTool("scratch", params, Object.keys(scratchParams.properties));
    },
  });

  pi.on("agent_before_settle", async event => {
    if (process.env.ARENA_AUTOCONTINUE !== "1" || !active || !runId) return;
    const state = await campaign("frontier");
    const progress = JSON.stringify(state.best ?? null);
    // Only a turn that produced a real model response counts as work. Provider or extension
    // errors back off and eventually stop the run instead of burning continuations.
    const failed = event.outcome !== "completed";
    const lastAssistant = [...event.context.contextMessages].reverse().find(message => message.role === "assistant") as AssistantMessage | undefined;
    // Keep every failed outcome inside one retry budget. Pi's error outcomes normally include an
    // assistant error message; if one is absent, fail closed as model-side instead of retrying forever.
    const failure = failed ? classifyFailure(lastAssistant) ?? "model" : undefined;
    if (!failed) {
      outageStartedAt = undefined;
      outageAttempt = 0;
      errorStreak = 0;
    } else if (failure === "model") errorStreak += 1;
    const cutTokens = lastAssistant?.stopReason === "length" ? lastAssistant.usage.output : undefined;
    let activity = { proof_attempt: turnHadProofAttempt, novel_context: turnHadNovelContext,
      verified_improvement: turnHadVerifiedImprovement };
    if (!failed) {
      if (progress === previousProgress) plateau += 1;
      else { plateau = 0; spentAtBestChange = spentUsd; }
      previousProgress = progress;
      turnHadVerifiedImprovement ||= verifiedImproved(state.best, previousVerified);
      activity = { proof_attempt: turnHadProofAttempt, novel_context: turnHadNovelContext,
        verified_improvement: turnHadVerifiedImprovement };
      previousVerified = state.best ?? null;
      if (turnHadProofAttempt || turnHadNovelContext || turnHadVerifiedImprovement) noWorkTurns = 0;
      else noWorkTurns += 1;
    }
    const noWorkThisTurn = !failed && !(turnHadProofAttempt || turnHadNovelContext || turnHadVerifiedImprovement);
    // A finish: a turn that completed, stopped on its own (not cut by the length limit), wrote visible text and
    // asked for no tool, once the finish rule allows it.
    const remaining = finishAllowed(spentUsd, limit);
    const finishTurn = remaining.allowed && !failed && lastAssistant?.stopReason === "stop"
      && (lastAssistant.content ?? []).some(block => block.type === "text" && block.text.trim() !== "")
      && !(lastAssistant.content ?? []).some(block => block.type === "toolCall");
    const { stop, moveFocus, restart } = stopDecision({ limitHit, finishTurn, noWorkThisTurn,
      providerUnreachable: failure === "transport" && outageStartedAt !== undefined && nextWait(outageAttempt, Number(process.env.ARENA_BACKOFF_MS ?? 2000), outageStartedAt, Date.now(), Number(process.env.ARENA_OUTAGE_LIMIT_MS ?? 600000)).stop,
      errorLoop: failure === "model" && errorStreak >= MAX_ERROR_STREAK,
      continuations, noWorkTurns, plateau, stallUsd: spentUsd - spentAtBestChange, limitUsd: limit,
      remainingFraction: remaining.remainingFraction, finishAllowed: remaining.allowed });
    turnHadProofAttempt = false;
    turnHadNovelContext = false;
    turnHadVerifiedImprovement = false;
    if (stop) {
      const latestControl = costEvents().filter(item => item.kind === "control").at(-1);
      if (latestControl?.stop !== stop) {
        appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
          error_streak: errorStreak, progress, ...activity, stop, spent_at_best_change: spentAtBestChange,
          ...(failed ? { error_message: (lastAssistant?.errorMessage ?? "").slice(0, 300), failure } : {}),
          outage_started_at: outageStartedAt ?? null, outage_attempt: outageAttempt,
          ...(failure === "transport" ? { outage_ms: Date.now() - (outageStartedAt ?? Date.now()) } : {}) });
      }
      return { continue: false };
    }
    if (failed) {
      let delay: number;
      if (failure === "transport") {
        const now = Date.now();
        outageStartedAt ??= now;
        outageAttempt += 1;
        const wait = nextWait(outageAttempt, Number(process.env.ARENA_BACKOFF_MS ?? 2000), outageStartedAt, now, Number(process.env.ARENA_OUTAGE_LIMIT_MS ?? 600000));
        delay = wait.stop ? 0 : wait.delayMs;
      } else delay = Math.min(30_000, Number(process.env.ARENA_BACKOFF_MS ?? 2000) * 2 ** (errorStreak - 1));
      appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
        error_streak: errorStreak, progress, ...activity, stop: null, backoff_ms: delay, spent_at_best_change: spentAtBestChange,
        ...(failure ? { error_message: (lastAssistant?.errorMessage ?? "").slice(0, 300), failure } : {}),
        outage_started_at: outageStartedAt ?? null, outage_attempt: outageAttempt,
        ...(failure === "transport" ? { outage_ms: Date.now() - outageStartedAt! } : {}) });
      if (delay > 0) await new Promise(done => setTimeout(done, delay));
    } else {
      continuations += 1;
      appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
        error_streak: errorStreak, progress, ...activity, stop: null, spent_at_best_change: spentAtBestChange,
        outage_started_at: null, outage_attempt: 0 });
    }
    const checks = await campaign("state");
    const cause = failed ? String((event as any).errorMessage ?? lastAssistant?.errorMessage ?? "") : undefined;
    const content = await continuationPush({ failed, cause, cutTokens, skeleton: checks?.skeleton, spentUsd,
      limitUsd: limit, baseline: checks?.baseline, best: checks?.best ?? state.best });
    // Second no-work turn in a row, before the final tenth: the run restarts from a packet at the next starting
    // point. The compaction draft keeps nothing before it, so the old reasoning leaves the model's context.
    if (restart) {
      const restarted = await campaign("restart_packet");
      if (restarted.ok === true && typeof restarted.text === "string") {
        await campaign("reset_delivered");
        trimmer.forget();
        noWorkTurns = 0;
        plateau = 0;
        spentAtBestChange = spentUsd;
        appendCost({ kind: "restart", continuations, restart: restarted.restart, label: restarted.label, chars: restarted.text.length });
        const facts = await continuationFacts(spentUsd, limit, checks?.baseline, checks?.best ?? state.best, checks?.skeleton);
        return { entries: [...event.entries,
          { type: "compaction" as const, summary: restarted.text, firstKeptEntryId: null },
          { type: "custom_message" as const, customType: "arena-continuation",
            content: await renderText("messages/continuation.restart", { facts }), display: false }], continue: true };
      }
      console.error(`[arena-restart] not restarted: ${restarted.error ?? "no packet"}`); // log: operator diagnostic. // not-model-facing
    }
    // No work before the final tenth: focus moves to a different starting point, stated as one fact line and the
    // starting point's proof and costliest steps.
    const moved = moveFocus ? await campaign("no_work_focus") : undefined;
    const focusLine = moved?.moved ? await renderText("messages/continuation.focus_moved", { label: moved.label }) : undefined;
    const focusMaterial = moved?.moved ? await renderText("messages/continuation.focus_material",
      { label: moved.label, proof: moved.proof, prices: moved.prices }) : undefined;
    const nextText = [content, focusLine, focusMaterial].filter(line => line !== undefined).join("\n");
    return { entries: [...event.entries, { type: "custom_message" as const, customType: "arena-continuation",
      content: nextText, display: false }], continue: true };
  });
}
