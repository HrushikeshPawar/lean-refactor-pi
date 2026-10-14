import { createHash } from "node:crypto";
import { render } from "./text.ts";

/** Read-only context tools whose identical repeat can be replaced by a stub; compile and goal results never are. */
export const STUBBABLE_TOOLS = new Set(["search", "read"]);
const STUB_MIN_CHARS = 200;

/**
 * A repeated identical context result becomes a stub. Call `forget` when Pi compacts because the earlier text is gone.
 */
export class ResultTrimmer {
  private seen = new Map<string, string>();

  forget() { this.seen.clear(); }

  /** The text to show the model for one successful tool result. */
  async trim(toolName: string, input: unknown, text: string): Promise<string> {
    if (STUBBABLE_TOOLS.has(toolName) && text.length >= STUB_MIN_CHARS) {
      const key = `${toolName}:${JSON.stringify(input ?? {})}`;
      const digest = createHash("sha256").update(text).digest("hex");
      if (this.seen.get(key) === digest) {
        return JSON.stringify({ ok: true, unchanged: true, note: await render("messages/trim.result_stub") });
      }
      this.seen.set(key, digest);
    }
    return text;
  }
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

/** True when a compaction would summarize nothing: its summary request is skipped. */
export function nothingToSummarize(preparation: { messagesToSummarize?: readonly unknown[]; turnPrefixMessages?: readonly unknown[] }): boolean {
  return !preparation.messagesToSummarize?.length && !preparation.turnPrefixMessages?.length;
}
