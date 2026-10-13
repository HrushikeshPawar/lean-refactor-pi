import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, chmodSync, closeSync, fsyncSync, mkdirSync, openSync, readFileSync } from "node:fs";
import { mkdir, mkdtemp, readdir, readFile, realpath, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve, relative, sep } from "node:path";
import { Type } from "typebox";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { nearestToolName, normalizeToolArguments, requireToolArguments } from "./toolnames.ts";
import { DeltaChain } from "./journal.ts";
import { objectToolArguments, ResultTrimmer } from "./trim.ts";
import { continuationPush, finishPush, routesText, trimProfile, leanPathViolation, planEvaluate, resolveInlineIdea, planProbe, sinceRefusal, staleNotice } from "./rules.ts";
import type { RouteStats } from "./rules.ts";
import { cacheAlarm, cacheHitPct, callCost, finishAllowed, limitReached, limitUsd, spendFooter, toolsForSpend } from "./spend.ts";
import { numbers as textNumbers, render as renderText } from "./text.ts";
import { classifyFailure, nextWait } from "./outage.ts";
import { applyToolTurnEffort } from "./thinking.ts";
import { buildTurnCutLine } from "./truncation.ts";

const root = resolve(import.meta.dirname, "../../..");
const workspaces = resolve(root, "workspaces");
const SKILL_READ_LIMIT = 24_000;
const MAX_ERROR_STREAK = 3;
const FINISH_TOOL = "arena_finish";
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
  const draftLimitWord = ({ 1: "one", 2: "two", 3: "three", 4: "four" } as Record<number, string>)[sharedNumbers.max_drafts]
    ?? String(sharedNumbers.max_drafts);
  // Every Arena tool sees cleaned arguments: empty optional fields are absent, text arrays are parsed.
  const registerTool = ((tool: any) => pi.registerTool({ ...tool, prepareArguments: requireToolArguments,
    execute: (id: string, params: any, ...rest: any[]) =>
      tool.execute(id, normalizeToolArguments(params, tool.parameters), ...rest) })) as typeof pi.registerTool;
  // Providers Pi does not ship (models.yaml `providers`) are registered here; Pi prices their calls from these models.
  const configuredModels = JSON.parse(process.env.ARENA_MODELS_JSON ?? "{}");
  for (const [name, config] of Object.entries(configuredModels.providers ?? {})) pi.registerProvider(name, config as any);
  // A factory invocation owns one Pi session. No active theorem is module-global.
  let active: string | undefined;
  const runId = process.env.ARENA_RUN_ID;
  const runDirectory = runId ? resolve(root, "runs", "pi-budget", runId) : undefined;
  const costJournal = runDirectory ? resolve(runDirectory, "cost-ledger.jsonl") : undefined;
  const traceJournal = runDirectory ? resolve(runDirectory, "trace-journal.jsonl") : undefined;
  // The one spend rule (spend.ts): each call's actual cost is added once, the run stops at the limit.
  const limit = limitUsd();
  const outputLimit = Number(process.env.ARENA_REQUEST_OUTPUT_TOKENS ?? 0);
  let spentUsd = 0;
  let settledCalls = 0;
  let limitHit = false;
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

  async function campaign(action: string, args: string[] = []): Promise<Record<string, any>> {
    if (!active || !runId) throw new Error("Arena run is not selected"); // not-model-facing: internal extension state invariant.
    const command = ["run", "--no-sync", "arena", "protocol", action,
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
  async function briefText(item: Record<string, any> | null | undefined): Promise<string> {
    if (!item) return renderText("messages/arena-line.none");
    const score = item.proxy !== undefined
      ? await renderText("messages/arena-line.brief_proxy", { proxy: item.proxy })
      : await renderText("messages/arena-line.brief_estimated", { estimated_proxy: item.estimated_proxy });
    return renderText("messages/arena-line.brief", {
      candidate: item.candidate, score, tokens: item.tokens, heartbeats: item.heartbeats,
    });
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
      keys.push(`source:${payload.handle ?? payload.path ?? ""}:${payload.first ?? ""}:${payload.last ?? ""}:${payload.text ?? payload.source ?? ""}`); // not-model-facing: internal novelty-detection key.
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
  async function stateLine(state: Record<string, any>, force = false): Promise<string | undefined> {
    const updates = (state.updates ?? []).filter((item: any) => item.seq > deliveredSeq);
    const best = JSON.stringify([state.best ?? null, state.leading_unverified ?? null]);
    if (!force && !updates.length && best === deliveredBest) return undefined;
    deliveredSeq = Math.max(deliveredSeq, ...(state.updates ?? []).map((item: any) => item.seq));
    deliveredBest = best;
    const parts = updates.map((item: any) => item.text);
    parts.push(await renderText("messages/arena-line.best_verified", { best: await briefText(state.best) }));
    if (state.leading_unverified) {
      const pending = await renderText((state.checking ?? []).includes(state.leading_unverified.candidate)
        ? "messages/arena-line.being_checked" : "messages/arena-line.not_yet_checked");
      parts.push(await renderText("messages/arena-line.leading_unverified", {
        best: await briefText(state.leading_unverified), pending,
      }));
    }
    return renderText("messages/arena-line", { parts: parts.join(" · ") });
  }

  function costEvents(): Array<Record<string, unknown>> {
    if (!costJournal) return [];
    try { return readFileSync(costJournal, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line)); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
  }
  function appendCost(event: Record<string, unknown>) {
    if (!costJournal) throw new Error("Arena cost journal is unavailable"); // not-model-facing: internal cost ledger invariant.
    mkdirSync(dirname(costJournal), { recursive: true });
    const fd = openSync(costJournal, "a", 0o600);
    try { appendFileSync(fd, `${JSON.stringify({ ts: Date.now(), ...event })}\n`); fsyncSync(fd); }
    finally { closeSync(fd); }
  }
  function appendTrace(event: Record<string, unknown>) {
    if (!traceJournal) throw new Error("Arena trace journal is unavailable"); // not-model-facing: internal trace ledger invariant.
    mkdirSync(dirname(traceJournal), { recursive: true });
    const fd = openSync(traceJournal, "a", 0o600);
    try { appendFileSync(fd, `${JSON.stringify({ ts: Date.now(), ...event })}\n`); fsyncSync(fd); }
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
  // The finish tool is offered to the model only inside the final FINISH_REMAINING_FRACTION of the limit.
  function applyFinishGate() {
    const offered = toolsForSpend(pi.getActiveTools(), FINISH_TOOL, finishAllowed(spentUsd, limit).allowed);
    const current = pi.getActiveTools();
    if (offered.length !== current.length || offered.some((name, index) => name !== current[index])) pi.setActiveTools(offered);
  }

  pi.on("session_start", (_event, ctx) => {
    active = undefined;
    // The run total is the sum of the ledger's settle rows, so a resumed run continues from its spend.
    const settled = costEvents().filter(item => item.kind === "settle" && item.usage_known !== false);
    spentUsd = settled.reduce((sum, item) => sum + Number(item.usd), 0);
    settledCalls = settled.length;
    limitHit = limitReached(spentUsd, limit);
    pendingRequest = undefined;
    previousFailed = undefined;
    const latest = costEvents().filter(item => item.kind === "control").at(-1);
    continuations = Number(latest?.continuations ?? 0);
    plateau = Number(latest?.plateau ?? 0);
    errorStreak = Number(latest?.error_streak ?? 0);
    outageStartedAt = typeof latest?.outage_started_at === "number" ? latest.outage_started_at : undefined;
    outageAttempt = Number(latest?.outage_attempt ?? 0);
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
    applyFinishGate();
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
    appendTrace({ kind: "request", id, run_id: runId, retry_of: previousFailed ?? null,
      model: ctx.model?.id ?? process.env.ARENA_MODEL ?? null, ...hookFields(payload) });
    return payload === event.payload ? undefined : payload;
  });
  pi.on("after_provider_response", event => {
    if (pendingRequest && traceJournal) appendTrace({ kind: "http_response", id: pendingRequest, status: event.status });
  });

  pi.on("before_agent_start", (_event, ctx) => {
    applyFinishGate();
    if (process.env.ARENA_BUDGET_REQUIRED !== "1") return;
    if (!active || limitHit || ctx.model?.id !== (process.env.ARENA_PI_MODEL_ID ?? process.env.ARENA_MODEL)) {
      ctx.abort();
      if (ctx.hasUI) ctx.ui.notify(limitHit ? "The spend limit is already reached." : "Select /arena and the run's model before prompting.", "error"); // not-model-facing: operator UI notification.
    }
  });

  // Preserve earlier tool messages byte-for-byte. Rewriting them when a new
  // evaluation arrives invalidates the provider's cached prompt prefix.

  // Add one call's actual cost to the run total and write its settle row. The one place spend changes.
  // A call with no usage (a request that failed before the provider counted tokens) settles at zero.
  function settle(id: string, usage: AssistantMessage["usage"] | undefined, extra: Record<string, unknown>, ctx: ExtensionContext) {
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
      const alarm = cacheAlarm(usage, settledCalls);
      if (alarm) {
        appendCost({ kind: "cache_alarm", id, ...alarm });
        console.error(`[arena-cache-alarm] request ${alarm.request}: wrote ${alarm.write} cache tokens but read ${alarm.read}; the stable prefix was not reused`); // not-model-facing: operator diagnostic log.
      }
    }
    if (known) console.error(`[arena-cost] settled $${usd.toFixed(6)}; cache read ${usage?.cacheRead ?? 0}, write ${usage?.cacheWrite ?? 0}; total $${spentUsd.toFixed(6)}`); // not-model-facing: operator diagnostic log.
    applyFinishGate();
    // Stop the agent at once: no further provider request, no further tool batch. The turn that follows is
    // closed in agent_before_settle with the limit as the stop reason.
    if (limitReached(spentUsd, limit) && !limitHit) {
      limitHit = true;
      // Recorded here because an aborted run may never reach agent_before_settle.
      appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
        error_streak: errorStreak, progress: previousProgress, stop: "limit_reached",
        outage_started_at: outageStartedAt ?? null, outage_attempt: outageAttempt });
      ctx.abort();
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
    settle(id, message.usage, {}, ctx);
    appendTrace({ ...delivered, settled_usd: known ? callCost(message.usage) : null,
      usage: { input: message.usage?.input ?? 0, output: message.usage?.output ?? 0,
        cache_read: message.usage?.cacheRead ?? 0, cache_write: message.usage?.cacheWrite ?? 0 } });
    // The next request of a failed one is its retry.
    previousFailed = known ? undefined : id;
    if (!known) console.error(`[arena-cost] request ${id} returned no usage`); // not-model-facing: operator diagnostic log.
    return repaired ? { message: repaired } : undefined;
  });
  // A compaction's summary requests have no message_end; Pi records their combined usage on the entry.
  pi.on("session_compact", (event, ctx) => {
    settle(pendingRequest ?? `${Date.now()}-compaction`, event.compactionEntry.usage, { source: "compaction" }, ctx);
    pendingRequest = undefined;
    trimmer.forget();
    void injectMemory();
  });
  pi.on("session_compact_failed", () => { pendingRequest = undefined; });
  pi.on("session_before_compact", event => {
    const fixed = objectToolArguments(event.preparation.messagesToSummarize) + objectToolArguments(event.preparation.turnPrefixMessages);
    if (fixed) appendTrace({ kind: "compaction_repair", null_tool_arguments: fixed });
  });

  // After a compaction the harness restates its own record of the run (best verified candidate, routes,
  // ideas, latest failures, allowance) as one hidden message. Built from the ledger, never by the model,
  // and sent only here, so it is not repeated every turn. Pi queues it behind the turn's tool results.
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

  let leanProject: string | undefined;

  pi.registerCommand("arena", {
    description: "Select a benchmark theorem: /arena Core.InitsUpdatesComm", // not-model-facing: slash-command help shown in the UI.
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
      return { block: true, reason: await renderText("messages/notices.block_shell") };
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
          return { block: true, reason: await renderText("messages/notices.block_workspace") };
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
  pi.on("tool_execution_end", (event, ctx) => {
    // A confirmed finish ends the run: no provider request follows the tool result.
    if (event.toolName === FINISH_TOOL && finishConfirmed) ctx.abort();
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

  pi.on("tool_result", async event => {
    if (!active) return;
    // Errors reach the model untouched; only successful results are trimmed (the trace keeps the full text).
    const content = event.isError ? event.content : await Promise.all(event.content.map(async part => {
      if (part.type !== "text" || !part.text) return part;
      const text = await trimmer.trim(event.toolName, event.input, part.text);
      return text === part.text ? part : { ...part, text };
    }));
    const changed = content.some((part, index) => part !== event.content[index]);
    if (changed) untrimmed.set(event.toolCallId, event.content.filter(part => part.type === "text" && part.text)
      .map(part => (part as { text: string }).text).join("\n"));
    const state = readState();
      const stateText = state && await stateLine(state);
    let spend = "";
    try { spend = await spendFooter(spentUsd, limit); } catch { /* the footer is best effort */ }
    const line = spend ? (stateText
      ? await renderText("messages/arena-line.join", { state: stateText, spend })
      : await renderText("messages/arena-line.only_spend", { spend })) : stateText;
    if (!line && !changed) return;
    return { content: line ? [...content, { type: "text" as const, text: line }] : content,
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

  const dropEmpty = <T extends Record<string, any>>(value: T): T => Object.fromEntries(Object.entries(value)
    .filter(([, item]) => item !== undefined && item !== null && !(Array.isArray(item) && !item.length))) as T;

  const reply = (result: Record<string, any>) =>
    ({ isError: result.ok === false, content: [{ type: "text" as const, text: JSON.stringify(result) }], details: result });

  // One harness line when a route's attempts keep leaving goal states it already had. Route fingerprints are filed in the
  // background, so a streak can surface on the call after the attempt that completed it.
  async function withStaleNotice(result: ReturnType<typeof reply>) {
    const notice = await staleNotice((await campaign("frontier")).routes ?? [], staleNoticed);
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
        ? ["succeeded", await renderText("messages/notices.auto_idea_succeeded", { best: await briefText(previous.best), idea: result.id })]
        : attempts > 0
          ? ["abandoned", await renderText("messages/notices.auto_idea_abandoned", {
            attempts, plural: attempts === 1 ? "" : "s",
            best_text: previous.best ? ` (best ${await briefText(previous.best)})` : "", idea: result.id,
          })]
          : ["parked", await renderText("messages/notices.auto_idea_parked", { idea: result.id })];
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
    description: await renderText("tools/arena_evaluate.description"),
    parameters: Type.Object({
      proof: Type.Optional(Type.String({ description: await renderText("tools/arena_evaluate.params.proof") })),
      candidate: Type.Optional(Type.String({ description: await renderText("tools/arena_evaluate.params.candidate") })),
      from_probe: Type.Optional(Type.String({ description: await renderText("tools/arena_evaluate.params.from_probe") })),
      parents: Type.Optional(Type.Array(Type.String())),
      hypothesis: Type.Optional(Type.String()),
      idea_id: Type.Optional(Type.String()),
      idea: Type.Optional(Type.String({ description: await renderText("tools/arena_evaluate.params.idea") })),
    }),
    async execute(_id, params) {
      if (!active) throw new Error(await renderText("messages/errors.select_target"));
      const plan = await planEvaluate(params);
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
      return withStaleNotice(reply({ ...result, ...(idea.created ? { idea_id: idea.idea_id } : {}), ...(plan.note ? { note: plan.note } : {}), remaining_usd: Number(Math.max(0, limit - spentUsd).toFixed(4)) }));
    },
  });

  registerTool({
    name: "arena_probe", label: "Arena probe",
    description: await renderText("tools/arena_probe.description", { draft_limit_word: draftLimitWord }),
    parameters: Type.Object({ proof: Type.Optional(Type.String()),
      drafts: Type.Optional(Type.Array(Type.String(), { minItems: 1, maxItems: sharedNumbers.max_drafts })),
      idea_id: Type.Optional(Type.String()), parent: Type.Optional(Type.String()),
      idea: Type.Optional(Type.String({ description: await renderText("tools/arena_probe.params.idea") })) }),
    async execute(_id, params) {
      if (!active) throw new Error(await renderText("messages/errors.select_target"));
      const plan = await planProbe(params);
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
        kickAutocheck();
        return withIdea(result);
      }
      const result = await withProofFiles(plan.drafts!, files => {
        const args: string[] = [];
        for (const file of files) args.push("--draft-file", file);
        if (idea.idea_id) args.push("--idea-id", idea.idea_id);
        if (params.parent) args.push("--parent", params.parent);
        return campaign("probe", args);
      });
      kickAutocheck();
      return withIdea(result);
    },
  });

  registerTool({
    name: "arena_profile", label: "Arena heartbeat profile",
    description: await renderText("tools/arena_profile.description"),
    parameters: Type.Object({ candidate: Type.Optional(Type.String()), proof: Type.Optional(Type.String()) }),
    async execute(_id, params) {
      if (!active) throw new Error(await renderText("messages/errors.select_target"));
      return reply(await trimProfile(await withProofFile(params.proof, file => {
        const args: string[] = [];
        if (file) args.push("--proof-file", file);
        if (params.candidate) args.push("--candidate", params.candidate);
        return campaign("profile", args);
      })));
    },
  });

  registerTool({
    name: "arena_idea", label: "Record or update an idea", // not-model-facing: tool label shown in the UI.
    description: await renderText("tools/arena_idea.description"),
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
    description: await renderText("tools/arena_state.description"),
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
    name: "arena_finish", label: "Review and finish the Arena run", // not-model-facing: tool label shown in the UI.
    description: await renderText("tools/arena_finish.description"),
    parameters: Type.Object({}),
    async execute() {
      if (finishConfirmed) return reply({ ok: true, phase: "confirmed", stop: true });
      const [checks, portfolio, answer] = await Promise.all([
        campaign("state"), campaign("frontier"), campaign("submission"),
      ]);
      if (checks.ok === false) return reply(checks);
      if (portfolio.ok === false) return reply(portfolio);
      const spent = spentUsd;
      const room = finishAllowed(spent, limit);
      const idea = portfolio.current_idea ?? null;
      const bestVerified = answer.candidate ? { candidate: answer.candidate, tokens: answer.tokens,
        heartbeats: answer.heartbeats, proxy: answer.proxy, status: "cold verified" } : checks.best;
      // Facts the stop decision depends on: how much of the allowance is left and which routes were tried.
      const budget = { spent_usd: Number(spent.toFixed(4)), cap_usd: limit,
        remaining_usd: Number(room.remainingUsd.toFixed(4)), used_pct: Math.round(100 * spent / limit) };
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
      const reminderText = reminder ? await renderText("messages/notices.finish_reminder", { id: idea.id }) : null;
      if (!room.allowed) {
        // More than 10% of the allowance is left: refuse, stating the facts.
        const newIdeaProbed = ideaRows.some(row => row.attempts > 0 && !refusalIdeaIds.has(String(row.id)));
        const routeRows: any[] = portfolio.routes ?? [];
        const since = sinceRefusal(routeRows, refusalRouteStats, refusalCredited);
        const push = await finishPush({ usedPct: budget.used_pct, remainingUsd: room.remainingUsd, capUsd: limit,
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
          routes_tried: await routesText(portfolio.routes ?? []),
          next: await renderText("messages/notices.finish_review", {
            used_pct: budget.used_pct, limit, remaining: budget.remaining_usd,
            action: await renderText("messages/notices.finish_review_action"),
          }) }));
      }
      finishConfirmed = true;
      appendCost({ kind: "finish", phase: "confirmed" });
      const stop = limitHit ? "limit_reached" : "finished";
      appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
        error_streak: errorStreak, progress: previousProgress, stop });
      return reply({ ok: true, phase: "confirmed", stop: true, best_verified: bestVerified });
    },
  });

  registerTool({
    name: "arena_candidate", label: "Restore a candidate or probe", // not-model-facing: tool label shown in the UI.
    description: await renderText("tools/arena_candidate.description"),
    parameters: Type.Object({ candidate: Type.String({ description: await renderText("tools/arena_candidate.params.candidate") }) }),
    async execute(_id, params) { return reply(await campaign("candidate", ["--candidate", params.candidate])); },
  });

  registerTool({
    name: "arena_skill_read", label: "Read Arena skill reference", // not-model-facing: tool label shown in the UI.
    description: await renderText("tools/arena_skill_read.description"),
    parameters: Type.Object({ path: Type.Optional(Type.String()), offset: Type.Optional(Type.Number()) }),
    async execute(_id, params) {
      const base = process.env.ARENA_SKILL_DIR;
      if (!base) return reply({ ok: false, error: await renderText("messages/errors.skill_missing") });
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
        return reply({ ok: false, error: await renderText("messages/errors.skill_path", { path: params.path }) });
      }
      if (!(await stat(target)).isFile()) return reply({ ok: false, error: await renderText("messages/errors.skill_directory", { path: params.path }) });
      const source = await readFile(target, "utf8");
      let text = target.endsWith(".md")
        ? await renderText(relative(resolve(skillRoot, ".."), target).replaceAll(sep, "/").replace(/\.md$/, ""))
        : source;
      if (target.endsWith("/SKILL.md") && text.startsWith("---")) text = text.split("---", 3)[2].trim();
      const start = Math.max(0, params.offset ?? 0);
      const slice = text.slice(start, start + SKILL_READ_LIMIT);
      return reply({ ok: true, path: relative(skillRoot, target), offset: start, total_chars: text.length,
        next_offset: start + SKILL_READ_LIMIT < text.length ? start + SKILL_READ_LIMIT : null, text: slice });
    },
  });

  registerTool({
    name: "arena_source", label: "Pinned Lean source",
    description: await renderText("tools/arena_source.description"),
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
    description: await renderText("tools/arena_declarations.description"),
    // One object schema: providers reject a top-level anyOf. Exactly one of the two fields is used.
    parameters: Type.Object({ items: Type.Optional(Type.Array(Type.String())), cursor: Type.Optional(Type.String()) }),
    async execute(_id, params) {
      if ((params.items === undefined) === (params.cursor === undefined)) {
        return reply({ ok: false, error: "usage_error",
          detail: await renderText("messages/errors.declarations_usage") });
      }
      const args = [];
      if (params.items !== undefined) args.push("--items", JSON.stringify(params.items));
      if (params.cursor !== undefined) args.push("--cursor", params.cursor);
      return reply(await campaign("declarations", args));
    },
  });

  registerTool({
    name: "arena_find", label: "Search pinned declarations",
    description: await renderText("tools/arena_find.description"),
    parameters: Type.Object({ queries: Type.Array(Type.String()), limit: Type.Optional(Type.Number()) }),
    async execute(_id, params) {
      const args = ["--queries", JSON.stringify(params.queries)];
      if (params.limit !== undefined) args.push("--limit", String(params.limit));
      return reply(await campaign("find", args));
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
    const stop = limitHit ? "limit_reached"
      : finishConfirmed ? "finished"
      : failure === "transport" && outageStartedAt !== undefined && nextWait(outageAttempt, Number(process.env.ARENA_BACKOFF_MS ?? 2000), outageStartedAt, Date.now(), Number(process.env.ARENA_OUTAGE_LIMIT_MS ?? 600000)).stop ? "provider_unreachable"
      : failure === "model" && errorStreak >= MAX_ERROR_STREAK ? "error_loop"
      : continuations >= 12 ? "continuation_limit"
      : noWorkTurns >= 2 ? "no_work_fallback"
      // A plateau only ends the run inside the final 10%; earlier the model must try a new route.
      : continuations >= 4 && plateau >= 4 && finishAllowed(spentUsd, limit).allowed ? "plateau" : null;
    turnHadProofAttempt = false;
    turnHadNovelContext = false;
    turnHadVerifiedImprovement = false;
    if (stop) {
      const latestControl = costEvents().filter(item => item.kind === "control").at(-1);
      if (latestControl?.stop !== stop) {
        appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
          error_streak: errorStreak, progress, ...activity, stop,
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
        error_streak: errorStreak, progress, ...activity, stop: null, backoff_ms: delay,
        ...(failure ? { error_message: (lastAssistant?.errorMessage ?? "").slice(0, 300), failure } : {}),
        outage_started_at: outageStartedAt ?? null, outage_attempt: outageAttempt,
        ...(failure === "transport" ? { outage_ms: Date.now() - outageStartedAt! } : {}) });
      if (delay > 0) await new Promise(done => setTimeout(done, delay));
    } else {
      continuations += 1;
      appendCost({ kind: "control", continuations, plateau, no_work_turns: noWorkTurns,
        error_streak: errorStreak, progress, ...activity, stop: null,
        outage_started_at: null, outage_attempt: 0 });
    }
    const ideas = (state.ideas ?? []).filter((idea: any) => idea.status === "active")
      .map((idea: any) => `${idea.id} ${idea.title}`);
    const current = readState();
    const status = current ? await stateLine(current, true) : await renderText("messages/arena-line.best_verified", { best: await briefText(state.best) })
      .then(value => renderText("messages/arena-line", { parts: value }));
    const room = finishAllowed(spentUsd, limit);
    const checks = !room.allowed ? await campaign("state") : undefined;
    const content = !room.allowed
      ? await continuationPush({ usedPct: Math.round(100 * spentUsd / limit), remainingUsd: room.remainingUsd, capUsd: limit,
        baseline: checks?.baseline, best: checks?.best, top: state.top, routes: state.routes })
      : await renderText("messages/continuation", {
        status, ideas: ideas.length ? ideas.join("; ") : await renderText("messages/refusals.none_recorded"),
        limit, remaining: room.remainingUsd.toFixed(4),
      });
    const cutLine = cutTokens === undefined ? undefined
      : buildTurnCutLine(cutTokens, await renderText("messages/errors.turn_cut", { tokens: "{tokens}" }));
    const nextText = cutLine === undefined ? content : `${content}\n${cutLine}`;
    return { entries: [...event.entries, { type: "custom_message" as const, customType: "arena-continuation",
      content: nextText, display: false }], continue: true };
  });
}
