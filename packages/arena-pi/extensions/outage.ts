import type { AssistantMessage } from "@earendil-works/pi-ai";

export type FailureKind = "transport" | "model";

export function classifyFailure(message: AssistantMessage | undefined): FailureKind | undefined {
  if (!message || message.stopReason !== "error") return undefined;
  if (message.usage?.totalTokens || message.content.length > 0) return "model";
  return "transport";
}

export function nextWait(
  attempt: number,
  baseMs: number,
  startedAt: number,
  now: number,
  limitMs: number,
): { stop: true } | { stop: false; delayMs: number } {
  const elapsed = now - startedAt;
  if (elapsed >= limitMs) return { stop: true };
  const backoff = Math.min(30_000, baseMs * 2 ** (attempt - 1));
  return { stop: false, delayMs: Math.min(backoff, limitMs - elapsed) };
}
