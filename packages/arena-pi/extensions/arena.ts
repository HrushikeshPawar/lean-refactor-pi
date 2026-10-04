import { execFile } from "node:child_process";
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve, relative, sep } from "node:path";
import { promisify } from "node:util";
import { Type } from "typebox";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { BUDGET_PROVIDER, budgetDecision, budgetLimits, isBudgetModel, MODELS, sessionSpend } from "./budget.ts";

const execFileAsync = promisify(execFile);
const root = resolve(import.meta.dirname, "../../..");
const workspaces = resolve(root, "workspaces");

function inside(path: string, parent: string): boolean {
  const rel = relative(parent, path);
  return rel === "" || (rel !== ".." && !rel.startsWith(`..${sep}`));
}

export default function arenaExtension(pi: ExtensionAPI) {
  // A factory invocation owns one Pi session. No active theorem is module-global.
  let active: string | undefined;
  const seeds: Array<{ proof: string; tokens: number; compat: Record<string, unknown> }> = [];
  let readEntries: (() => SessionEntry[]) | undefined;

  pi.on("session_start", (_event, ctx) => {
    active = undefined;
    seeds.length = 0;
    readEntries = () => ctx.sessionManager.getEntries();
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
        if (!physical) throw new Error(`OpenCode Go model unavailable: ${id}`);
        const limits = MODELS[id];
        if (physical.contextWindow > limits.contextWindow || physical.maxTokens > limits.maxTokens) {
          throw new Error(`Arena budget reservation is outdated for ${id}`);
        }
        if (request.failed && !request.failed.message.usage?.totalTokens) {
          throw new Error("Arena budget cannot price the failed provider request");
        }
        // Failed retries may be absent from the persisted branch. Counting one
        // twice is conservative; omitting a paid request would violate the cap.
        const retryCost = request.failed?.message.usage
          ? sessionSpend([{ type: "message", id: "retry", parentId: null, timestamp: "",
            message: request.failed.message }], id)
          : 0;
        const decision = budgetDecision(sessionSpend(readEntries(), id) + retryCost, id, budgetLimits());
        if (!decision.allowed) throw new Error(decision.reason);
        return { model: physical, thinkingLevel: request.thinkingLevel };
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

  function budgetStatus(ctx: ExtensionContext) {
    const model = ctx.model;
    if (model?.provider !== BUDGET_PROVIDER || !isBudgetModel(model.id)) return undefined;
    const spent = sessionSpend(ctx.sessionManager.getEntries(), model.id);
    const limits = budgetLimits();
    const decision = budgetDecision(spent, model.id, limits);
    return { spent_usd: spent, remaining_usd: limits.hardCapUsd - spent,
      next_request_reserve_usd: decision.reserve, can_continue: decision.allowed };
  }

  pi.on("session_shutdown", async (_event, ctx) => {
    const reportPath = process.env.ARENA_BUDGET_REPORT_PATH;
    if (!reportPath) return;
    const model = ctx.model;
    let report: Record<string, unknown> = { session_id: ctx.sessionManager.getSessionId(),
      theorem: active ?? null,
      price_basis: "OpenCode Go list prices, 2026-10-04; higher context/peak tiers" };
    try {
      const limits = budgetLimits();
      if (model?.provider !== BUDGET_PROVIDER || !isBudgetModel(model.id)) {
        throw new Error("Budgeted model was not selected");
      }
      report = { ...report, hard_cap_usd: limits.hardCapUsd, stop_target_usd: limits.stopUsd,
        provider: "opencode-go", model: model.id, ...budgetStatus(ctx) };
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
      seeds.length = 0;
      const first = Object.entries(row.version_info[0] ?? {})[0];
      if (first) {
        const [version] = first;
        pi.registerMcpServer("arena-lean", {
          command: "uvx",
          args: ["--from", "lean-lsp-mcp==0.31.0", "lean-lsp-mcp"],
          env: {
            LEAN_PROJECT_PATH: resolve(workspaces, `${row.source}-${version}`),
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
    description: "Return the selected theorem and its pinned benchmark metadata.",
    parameters: Type.Object({}),
    async execute() {
      if (!active) throw new Error("Select a theorem with /arena first");
      const rows = (await readFile(resolve(root, "benchmark/original/warmup.jsonl"), "utf8"))
        .split("\n").filter(Boolean).map((line) => JSON.parse(line));
      const row = rows.find((item) => item.name === active);
      const metadata = { name: row.name, statement: row.statement, source: row.source,
        file_path: row.file_path, version_info: row.version_info,
        reference_tokens: row.proof_length };
      return { content: [{ type: "text", text: JSON.stringify(metadata) }], details: metadata };
    },
  });

  pi.registerTool({
    name: "arena_evaluate",
    label: "Arena evaluate",
    description: "Compile a complete theorem against pinned source. Fast checks the primary version; full checks every version. Heartbeat scoring is pending worker calibration.",
    parameters: Type.Object({
      proof: Type.String({ description: "Complete theorem statement and replacement proof" }),
      mode: Type.Optional(Type.Union([Type.Literal("fast"), Type.Literal("full")])),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      if (!active) throw new Error("Select a theorem with /arena first");
      const directory = await mkdtemp(resolve(tmpdir(), "arena-proof-"));
      try {
        const file = resolve(directory, "proof.lean");
        await writeFile(file, params.proof, "utf8");
        let stdout: string;
        try {
          ({ stdout } = await execFileAsync("uv", ["run", "--no-project", "python", "-m",
            "tools.arena_eval", active, file, "--mode", params.mode ?? "fast"],
          { cwd: root, maxBuffer: 1_000_000, timeout: 700_000 }));
        } catch (error) {
          const output = String((error as { stdout?: string }).stdout ?? "").trim();
          const result = output ? JSON.parse(output) : { ok: false, error: String(error) };
          const reported = { ...result, budget: budgetStatus(ctx) };
          return { isError: true, content: [{ type: "text" as const, text: JSON.stringify(reported) }], details: reported };
        }
        const result = JSON.parse(stdout.trim());
        if (params.mode === "full" && Object.values(result.compat)[0]?.passed) {
          seeds.push({ proof: params.proof, tokens: result.tokens, compat: result.compat });
          seeds.sort((a, b) => a.tokens - b.tokens);
          seeds.splice(5);
        }
        const reported = { ...result, budget: budgetStatus(ctx) };
        return { content: [{ type: "text", text: JSON.stringify(reported) }], details: reported };
      } finally {
        await rm(directory, { recursive: true, force: true });
      }
    },
  });

  pi.registerTool({
    name: "arena_frontier",
    label: "Arena frontier",
    description: "List session-local full-evaluation mutation seeds, including partial transfers. No incumbent is promoted until server scoring is calibrated.",
    parameters: Type.Object({}),
    async execute() {
      const result = { name: active ?? null, seeds, incumbent: null,
        calibration: "pending official Arena worker comparison" };
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });
}
