import { createHash } from "node:crypto";

/** Read-only context tools whose identical repeat can be replaced by a stub; proof results never are. */
export const STUBBABLE_TOOLS = new Set(["arena_source", "arena_declarations", "arena_find", "arena_candidate",
  "arena_skill_read", "mcp__arena_lean__lean_local_search", "mcp__arena_lean__lean_hover_info"]);
const STUB_MIN_CHARS = 200;
const WARNING_LIMIT = 600;
const REPEATED_MESSAGE_MIN = 120;

/**
 * Model-facing trimming of tool results. Errors are never shortened and nothing a proof needs is removed:
 * a repeat of an earlier identical read becomes a stub, JSON is written compactly without empty fields,
 * a diagnostic message that repeats earlier in the same result points back to it, and only long
 * non-error messages (warnings, infos) are cut. Call `forget` when Pi compacts, since the earlier text is then gone.
 */
export class ResultTrimmer {
  private seen = new Map<string, string>();

  forget() { this.seen.clear(); }

  /** The text to show the model for one successful tool result. */
  trim(toolName: string, input: unknown, text: string): string {
    if (STUBBABLE_TOOLS.has(toolName) && text.length >= STUB_MIN_CHARS) {
      const key = `${toolName}:${JSON.stringify(input ?? {})}`;
      const digest = createHash("sha256").update(text).digest("hex");
      if (this.seen.get(key) === digest) {
        return JSON.stringify({ ok: true, unchanged: true,
          note: `${toolName === "arena_skill_read" ? "This skill file was" : "This result was"} already loaded earlier in this run; unchanged. Use the earlier text.` });
      }
      this.seen.set(key, digest);
    }
    return toolName.startsWith("mcp__arena_lean__") ? compactDiagnostics(text) : text;
  }
}

const isDiagnostic = (value: any) => value && typeof value === "object" && typeof value.severity === "string" && typeof value.message === "string";

/** Compact JSON from a Lean tool: no indentation or null fields, repeated long messages pointed back, long warnings cut. */
export function compactDiagnostics(text: string): string {
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { return text; }
  const messages = new Map<string, string>();
  const walk = (value: any): any => {
    if (Array.isArray(value)) return value.map(walk);
    if (!value || typeof value !== "object") return value;
    const out: Record<string, any> = {};
    for (const [key, item] of Object.entries(value)) {
      if (item === null || (key === "category" && item === "diagnostic")) continue;
      out[key] = walk(item);
    }
    if (isDiagnostic(value)) {
      const where = `${value.line ?? "?"}:${value.column ?? "?"}`;
      const signature = `${value.severity}\u0000${value.message}`;
      const earlier = messages.get(signature);
      if (value.message.length >= REPEATED_MESSAGE_MIN && earlier !== undefined) {
        out.message = `same message as the ${value.severity} at ${earlier}`;
      } else {
        messages.set(signature, where);
        if (value.severity !== "error" && value.message.length > WARNING_LIMIT) {
          out.message = `${value.message.slice(0, WARNING_LIMIT)} ... [${value.message.length - WARNING_LIMIT} more characters of this ${value.severity} omitted]`;
        }
      }
    }
    return out;
  };
  const compact = JSON.stringify(walk(parsed));
  return compact.length < text.length ? compact : text;
}

/**
 * Give every tool call an object for its arguments. A provider can return a call whose arguments do not parse
 * (stored as null), and Pi's compaction serializer runs Object.entries on each one: a single such call made every
 * later compaction of the run fail, so the context only grew. Mutates in place; returns how many were replaced.
 */
export function objectToolArguments(messages: readonly unknown[] | undefined): number {
  let fixed = 0;
  for (const message of messages ?? []) {
    const content = (message as { role?: string; content?: unknown }).content;
    if ((message as { role?: string }).role !== "assistant" || !Array.isArray(content)) continue;
    for (const block of content as Array<Record<string, unknown>>) {
      if (block?.type !== "toolCall" || (block.arguments && typeof block.arguments === "object")) continue;
      block.arguments = {};
      fixed += 1;
    }
  }
  return fixed;
}
