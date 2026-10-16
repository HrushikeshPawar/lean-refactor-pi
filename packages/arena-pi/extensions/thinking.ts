export function applyToolTurnEffort(payload: unknown, effort: string | undefined): unknown {
  if (!effort || typeof payload !== "object" || payload === null || Array.isArray(payload)) return payload;
  const body = payload as Record<string, unknown>;
  const messages = body.messages;
  if (!Array.isArray(messages) || messages.at(-1)?.role !== "tool") return payload;
  return { ...body, reasoning_effort: effort };
}
