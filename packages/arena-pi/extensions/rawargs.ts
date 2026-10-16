// Tool-call argument guard: re-assembles each streamed call's raw JSON and nulls calls Pi failed to parse.
import type { AssistantMessage } from "@earendil-works/pi-ai";

export function validObjectJson(raw: string | undefined): boolean {
  if (raw === undefined) return false;
  try {
    const value: unknown = JSON.parse(raw);
    return value !== null && typeof value === "object" && !Array.isArray(value);
  } catch {
    return false;
  }
}

function parsedObject(value: unknown): boolean {
  return !!value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0;
}

/** The raw argument JSON of each streamed tool call, in the order Pi's stream delivered it. */
export class RawArguments {
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
 *
 * Pi's own parse is trusted when it produced a non-empty object: a failed parse only ever yields {}. The
 * re-assembled stream text is consulted only for {}; on the OpenAI Responses stream it was unreliable and
 * nulled 19 of 61 valid GPT-6.1 Sol calls (v7-sol-ski1), identical text kept one time and nulled the next.
 */
export function repairMalformedToolArguments(message: AssistantMessage, raw: RawArguments): AssistantMessage | undefined {
  let changed = false;
  const content = message.content.map((block, index) => {
    if (block.type !== "toolCall" || parsedObject(block.arguments) || validObjectJson(raw.get(index))) return block;
    changed = true;
    return { ...block, arguments: null } as unknown as typeof block;
  });
  return changed ? { ...message, content } : undefined;
}
