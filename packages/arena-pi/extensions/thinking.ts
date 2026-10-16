export function applyToolTurnEffort(payload: unknown, effort: string | undefined): unknown {
  if (!effort || typeof payload !== "object" || payload === null || Array.isArray(payload)) return payload;
  const body = payload as Record<string, unknown>;
  const messages = body.messages;
  if (!Array.isArray(messages) || messages.at(-1)?.role !== "tool") return payload;
  return { ...body, reasoning_effort: effort };
}

// Responses-API payloads (OpenAI, Codex) carry `reasoning: {effort, summary}`; Pi defaults the summary to "auto".
export function requestDetailedSummary(payload: unknown): unknown {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return payload;
  const body = payload as Record<string, unknown>;
  const reasoning = body.reasoning;
  if (typeof reasoning !== "object" || reasoning === null || !("effort" in reasoning)) return payload;
  return { ...body, reasoning: { ...(reasoning as Record<string, unknown>), summary: "detailed" } };
}
