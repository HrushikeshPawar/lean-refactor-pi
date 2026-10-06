import { spawn } from "node:child_process";
import { appendFileSync, closeSync, fsyncSync, mkdirSync, openSync, readFileSync } from "node:fs";
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve, relative, sep } from "node:path";
import { Type } from "typebox";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { BUDGET_PROVIDER, budgetLimits, cacheUtilization, isBudgetModel, MAX_REQUEST_OUTPUT_TOKENS, MODELS, permitFinalPayload, sessionEmbeddedCost, sessionSpend, usageCost, usageCostParts } from "./budget.ts";

const root = resolve(import.meta.dirname, "../../..");
const workspaces = resolve(root, "workspaces");

function inside(path: string, parent: string): boolean {
  const rel = relative(parent, path);
  return rel === "" || (rel !== ".." && !rel.startsWith(`..${sep}`));
}

export default function arenaExtension(pi: ExtensionAPI) {
  // A factory invocation owns one Pi session. No active theorem is module-global.
  let active: string | undefined;
  const runId = process.env.ARENA_RUN_ID;
  const runDirectory = runId ? resolve(root, "runs", "pi-budget", runId) : undefined;
  const costJournal = runDirectory ? resolve(runDirectory, "cost-ledger.jsonl") : undefined;
  let pendingRequest: string | undefined;
  let continuations = 0;
  let plateau = 0;
  let previousProgress = "";
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
        : reject(new Error(Buffer.concat(errors).toString("utf8"))));
    });
    return JSON.parse(output.trim());
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
    for (const id of pending) appendCost({ kind: "release", id, reason: "unresolved_previous_process", usage_known: false });
    const latest = costEvents().filter(item => item.kind === "control").at(-1);
    continuations = Number(latest?.continuations ?? 0);
    plateau = Number(latest?.plateau ?? 0);
    previousProgress = String(latest?.progress ?? "");
  });

  // The guard provider owns the final transport callback. Extension hook errors
  // are swallowed by Pi, so a hook cannot enforce a hard dollar limit.
  pi.registerProvider("arena-guard", {
    name: "Arena guarded OpenCode Go",
    api: "openai-responses", baseUrl: "http://127.0.0.1/arena-guard-unused", apiKey: "guard-routing-only",
    models: Object.entries(MODELS).map(([id, limits]) => ({
      id, name: `Arena guarded ${id}`, reasoning: true, input: ["text"],
      cost: limits.price, contextWindow: limits.contextWindow, maxTokens: limits.maxTokens,
    })),
    streamSimple(model, context, options) {
      if (!isBudgetModel(model.id) || !active || !runDirectory) {
        throw new Error("Unpriced or unselected Arena model");
      }
      const runtime = modelRegistry;
      if (!runtime) throw new Error("Arena model registry is unavailable");
      const physical = runtime.find("opencode-go", model.id);
      if (!physical) throw new Error(`OpenCode Go model unavailable: ${model.id}`);
      if (physical.contextWindow > MODELS[model.id].contextWindow ||
          physical.maxTokens > MODELS[model.id].maxTokens) {
        throw new Error(`Arena budget reservation is outdated for ${model.id}`);
      }
      const { apiKey: _guardKey, headers: _guardHeaders, env: _guardEnv, ...rest } = options ?? {};
      return runtime.streamSimple(physical, context, {
        ...rest,
        maxTokens: Math.min(rest.maxTokens ?? MAX_REQUEST_OUTPUT_TOKENS, MAX_REQUEST_OUTPUT_TOKENS),
        onPayload: async payload => {
          const transformed = await options?.onPayload?.(payload, physical) ?? payload;
          const bounded = permitFinalPayload(transformed, model.id, costState(), budgetLimits());
          const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
          appendCost({ kind: "reserve", id, usd: bounded.reserve, model: model.id,
            bytes: Buffer.byteLength(JSON.stringify(bounded.payload)) });
          pendingRequest = id;
          return bounded.payload;
        },
      });
    },
  });

  for (const id of Object.keys(MODELS)) {
    if (!isBudgetModel(id)) continue;
    pi.registerVirtualModel({
      provider: BUDGET_PROVIDER,
      id,
      name: `Arena budgeted ${id}`,
      thinkingLevels: ["low", "medium", "high"],
      route(request, ctx) {
        if (!readEntries) throw new Error("Arena budget session has not started");
        const physical = ctx.modelRegistry.find("opencode-go", id);
        const guarded = ctx.modelRegistry.find("arena-guard", id);
        if (!physical || !guarded) throw new Error(`OpenCode Go or Arena guard unavailable: ${id}`);
        const limits = MODELS[id];
        if (physical.contextWindow > limits.contextWindow || physical.maxTokens > limits.maxTokens) {
          throw new Error(`Arena budget reservation is outdated for ${id}`);
        }
        return { model: guarded, thinkingLevel: request.thinkingLevel };
      },
    });
  }

  pi.on("before_agent_start", (_event, ctx) => {
    if (process.env.ARENA_BUDGET_REQUIRED !== "1") return;
    if (!active || ctx.model?.provider !== BUDGET_PROVIDER || !isBudgetModel(ctx.model.id)) {
      ctx.abort();
      if (ctx.hasUI) ctx.ui.notify("Select /arena and an arena-budget model before prompting.", "error");
    }
  });

  // Preserve earlier tool messages byte-for-byte. Rewriting them when a new
  // evaluation arrives invalidates the provider's cached prompt prefix.

  pi.on("message_end", event => {
    if (!pendingRequest || event.message.role !== "assistant") return;
    const model = process.env.ARENA_MODEL;
    if (!model || !isBudgetModel(model)) return;
    const state = costEvents().findLast(item => item.kind === "reserve" && item.id === pendingRequest);
    if (!state) throw new Error("Missing Arena reservation");
    let usd = 0;
    let boundViolation = false;
    if (event.message.usage?.totalTokens) {
      const usage = event.message.usage;
      usd = usageCost(usage, model);
      boundViolation = usd > Number(state.usd);
      appendCost({ kind: "settle", id: pendingRequest, usd, usage_known: true,
        bound_violation: boundViolation,
        tokens: { input: usage.input ?? 0, output: usage.output ?? 0,
          cache_read: usage.cacheRead ?? 0, cache_write: usage.cacheWrite ?? 0 },
        ledger_components_usd: usageCostParts(usage, model),
        pi_embedded_cost_usd: usage.cost?.total ?? null });
      console.error(`[arena-cost] settled $${usd.toFixed(6)}; cache read ${usage.cacheRead ?? 0}, write ${usage.cacheWrite ?? 0}; total $${(costState().spent).toFixed(6)}`);
    } else {
      appendCost({ kind: "release", id: pendingRequest, reason: event.message.stopReason ?? "no_usage", usage_known: false });
      console.error(`[arena-cost] released failed request ${pendingRequest}; no usage returned`);
    }
    pendingRequest = undefined;
  });

  function budgetStatus(ctx: ExtensionContext) {
    const model = ctx.model;
    if (model?.provider !== BUDGET_PROVIDER || !isBudgetModel(model.id)) return undefined;
    const state = costState();
    const limits = budgetLimits();
    return { spent_usd: state.spent, unresolved_usd: state.unresolved,
      remaining_usd: Math.max(0, limits.hardCapUsd - state.spent),
      can_continue: state.spent < limits.hardCapUsd,
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
      report = { ...report, hard_cap_usd: limits.hardCapUsd, stop_target_usd: limits.stopUsd,
        provider: "opencode-go", model: model.id, ...budgetStatus(ctx),
        price_method: "Observed usage priced per request using OpenCode Go list rates; Luna uses the >272K tier only when billed prompt tokens cross that threshold. Neither this nor Pi's embedded estimate is a provider invoice.",
        configured_usd_per_million_tokens: MODELS[model.id].price,
        configured_high_tier: model.id === "gpt-6-luna" ? {
          prompt_tokens_over: MODELS["gpt-6-luna"].highContextThreshold,
          usd_per_million_tokens: MODELS["gpt-6-luna"].highPrice } : null,
        pi_embedded_estimate: sessionEmbeddedCost(ctx.sessionManager.getEntries()),
        pi_session_spend_usd: sessionSpend(ctx.sessionManager.getEntries(), model.id),
        cache_utilization: cacheUtilization(ctx.sessionManager.getEntries(), model.id) };
    } catch (error) {
      report = { ...report, error: String(error) };
    }
    await mkdir(dirname(reportPath), { recursive: true });
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  });

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
      if (first) {
        const [version] = first;
        pi.registerMcpServer("arena-lean", {
          command: "uvx",
          args: ["--from", "lean-lsp-mcp==0.31.0", "lean-lsp-mcp"],
          env: {
            LEAN_PROJECT_PATH: runDirectory ? resolve(runDirectory, "scratch", "project") : resolve(workspaces, `${row.source}-${version}`),
            LEAN_LOG_LEVEL: "WARNING",
            LEAN_MCP_DISABLED_TOOLS: "lean_leansearch,lean_leanfinder,lean_loogle,lean_hammer_premise",
          },
          exposure: "codemode",
          toolExposure: {
            lean_diagnostic_messages: "direct",
            lean_goal: "direct",
            lean_multi_attempt: "direct",
            lean_local_search: "direct",
            "*": "codemode",
          },
        });
      }
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

  pi.registerTool({
    name: "arena_target",
    label: "Arena target",
    description: "Return the selected theorem, original proof, and pinned benchmark metadata.",
    parameters: Type.Object({}),
    async execute() {
      if (!active) throw new Error("Select a theorem with /arena first");
      const rows = (await readFile(resolve(root, "benchmark/original/warmup.jsonl"), "utf8"))
        .split("\n").filter(Boolean).map((line) => JSON.parse(line));
      const row = rows.find((item) => item.name === active);
      const metadata = { name: row.name, statement: row.statement, original_proof: row.src, source: row.source,
        file_path: row.file_path, version_info: row.version_info,
        reference_tokens: row.proof_length };
      return { content: [{ type: "text", text: JSON.stringify(metadata) }], details: metadata };
    },
  });

  pi.registerTool({
    name: "arena_evaluate",
    label: "Arena evaluate",
    description: "Compile and save a complete theorem in the scheduled idea lane. Supply idea_id and a parent #N from arena_frontier. Return complete Lean diagnostics and the candidate path. Fast checks primary; full checks all versions.",
    parameters: Type.Object({
      proof: Type.String({ description: "Complete theorem statement and replacement proof" }),
      mode: Type.Optional(Type.Union([Type.Literal("fast"), Type.Literal("full")])),
      parents: Type.Optional(Type.Array(Type.String())),
      hypothesis: Type.Optional(Type.String()),
      idea_id: Type.Optional(Type.String()),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      if (!active) throw new Error("Select a theorem with /arena first");
      const directory = await mkdtemp(resolve(tmpdir(), "arena-proof-"));
      try {
        const file = resolve(directory, "proof.lean");
        await writeFile(file, params.proof, "utf8");
        const argumentsList = ["--proof-file", file, "--mode", params.mode ?? "fast",
          ...((params.parents ?? []) as string[]).flatMap(parent => ["--parent", parent])];
        if (params.hypothesis) argumentsList.push("--hypothesis", params.hypothesis);
        if (params.idea_id) argumentsList.push("--idea-id", params.idea_id);
        const result = await campaign("evaluate", argumentsList);
        const state = await campaign("frontier");
        const reported = { ...result, budget: budgetStatus(ctx), next_experiment: state.next_experiments?.[0] ?? null };
        return { isError: result.ok === false, content: [{ type: "text", text: JSON.stringify(reported) }], details: reported };
      } finally {
        await rm(directory, { recursive: true, force: true });
      }
    },
  });

  pi.registerTool({
    name: "arena_probe", label: "Arena scratch probe",
    description: "Compile a complete or unfinished proof draft on the primary Lean version without creating a graph candidate. Return complete diagnostics and a shadow-project path for lean_goal. Use this to repair a structural idea before promotion.",
    parameters: Type.Object({ proof: Type.String(), idea_id: Type.String(), parent: Type.String() }),
    async execute(_id, params) {
      if (!active) throw new Error("Select a theorem with /arena first");
      const directory = await mkdtemp(resolve(tmpdir(), "arena-probe-"));
      try {
        const file = resolve(directory, "proof.lean");
        await writeFile(file, params.proof, "utf8");
        const result = await campaign("probe", ["--proof-file", file, "--idea-id", params.idea_id,
          "--parent", params.parent]);
        return { isError: result.ok === false, content: [{ type: "text", text: JSON.stringify(result) }], details: result };
      } finally { await rm(directory, { recursive: true, force: true }); }
    },
  });

  pi.registerTool({
    name: "arena_frontier",
    label: "Arena frontier",
    description: "Return the scheduled source-derived idea, an exact #N seed, its next action and alternative idea lanes; use the first idea for the next new fast candidate.",
    parameters: Type.Object({}),
    async execute() {
      const result = await campaign("frontier");
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });

  pi.registerTool({
    name: "arena_idea", label: "Record a proof idea",
    description: "Add a distinct structural strategy grounded in 1-20 exact pinned Lean source lines. The idea enters the scheduled portfolio; give an actionable goal, not a known optimized proof.",
    parameters: Type.Object({ title: Type.String(), goal: Type.String(), path: Type.String(),
      first: Type.Number(), last: Type.Number() }),
    async execute(_id, params) {
      const result = await campaign("idea", ["--title", params.title, "--goal", params.goal,
        "--path", params.path, "--first", String(params.first), "--last", String(params.last)]);
      return { isError: result.ok === false, content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });

  pi.registerTool({
    name: "arena_decision", label: "Arena node decision",
    description: "Record why a candidate remains open or is parked; parked nodes remain retrievable but leave active merge/frontier selection.",
    parameters: Type.Object({ candidate_id: Type.String(), decision: Type.Union([Type.Literal("pursue"), Type.Literal("park")]), reason: Type.String() }),
    async execute(_id, params) {
      const result = await campaign("decision", ["--candidate-id", params.candidate_id,
        "--decision", params.decision, "--reason", params.reason]);
      return { isError: result.ok === false, content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });

  pi.registerTool({
    name: "arena_candidate", label: "Arena candidate",
    description: "Restore a candidate into the Lean scratch project and return its exact proof and complete recorded evaluations.",
    parameters: Type.Object({ candidate_id: Type.String() }),
    async execute(_id, params) {
      const result = await campaign("candidate", ["--candidate-id", params.candidate_id]);
      return { isError: result.ok === false, content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });

  pi.registerTool({
    name: "arena_source", label: "Pinned Lean source",
    description: "Read an exact line range from the pinned source commit; maximum 120 lines.",
    parameters: Type.Object({ path: Type.String(), first: Type.Number(), last: Type.Number() }),
    async execute(_id, params) {
      const result = await campaign("source", ["--path", params.path, "--first", String(params.first), "--last", String(params.last)]);
      return { isError: result.ok === false, content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });

  pi.registerTool({
    name: "arena_declaration", label: "Pinned declaration",
    description: "Find a declaration's exact source signature and location in the pinned project.",
    parameters: Type.Object({ symbol: Type.String() }),
    async execute(_id, params) {
      const result = await campaign("declaration", ["--symbol", params.symbol]);
      return { isError: result.ok === false, content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });

  pi.on("agent_before_settle", async event => {
    if (process.env.ARENA_AUTOCONTINUE !== "1" || !active || !runId) return;
    const budget = costState();
    const limits = budgetLimits();
    const state = await campaign("frontier");
    const progress = JSON.stringify({ best: state.score_best, primary: state.primary_best });
    if (progress === previousProgress) plateau += 1;
    else plateau = 0;
    previousProgress = progress;
    const stop = budget.spent >= limits.hardCapUsd ? "actual_usage_cap"
      : continuations >= 12 ? "continuation_limit"
      : continuations >= 4 && plateau >= 4 ? "plateau" : null;
    if (stop) {
      appendCost({ kind: "control", continuations, plateau, progress, stop });
      return;
    }
    continuations += 1;
    appendCost({ kind: "control", continuations, plateau, progress, stop: null });
    const next = state.next_experiments?.[0];
    const content = `Continue proof optimization. Current best: ${progress}. Scheduled idea and #N seed: ${JSON.stringify(next ?? null)}. Remaining ledger-priced usage cap: $${Math.max(0, limits.hardCapUsd - budget.spent).toFixed(4)}. Restore the seed with arena_candidate; use arena_probe and Lean goals to repair a structural draft before arena_evaluate. Supply the scheduled idea_id and a parent #N. Full-check promising proofs. The merge worker combines disjoint edits.`;
    return { entries: [...event.entries, { type: "custom_message" as const, customType: "arena-continuation",
      content, display: false }], continue: true };
  });
}
