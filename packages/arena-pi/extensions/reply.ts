import { render } from "./text.ts";

type Reply = {
  ok?: boolean;
  error?: Record<string, unknown> | string | null;
  facts?: string[];
  items?: Array<Record<string, any>>;
  handles?: string[];
  map?: string[] | null;
  stop?: boolean;
};

function errorText(error: Reply["error"]): string | undefined {
  if (typeof error === "string") return error;
  if (!error) return undefined;
  return String(error.line ?? error.message ?? error.code ?? "");
}

async function itemError(error: unknown, validKeys: string[]): Promise<string | undefined> {
  if (!error || typeof error !== "object") return typeof error === "string" ? error : undefined;
  const value = error as Record<string, unknown>;
  if (value.code === "empty_arguments") {
    return render("messages/errors.empty_arguments", { valid: validKeys.join(", ") || "none" });
  }
  return errorText(value as Reply["error"]);
}

export async function renderReply(reply: Reply, footer: string, validKeys: string[] = []) {
  const lines = [...(reply.facts ?? [])];
  for (const item of reply.items ?? []) {
    const itemLines = Array.isArray(item.lines) ? item.lines.filter((line): line is string => typeof line === "string" && Boolean(line)) : [];
    if (itemLines.length) lines.push(...itemLines);
    else {
      const line = await itemError(item.error, validKeys);
      if (line) lines.push(line);
    }
  }
  if (Array.isArray(reply.map)) lines.push(...reply.map.filter((line): line is string => typeof line === "string"));
  if (reply.handles?.length) lines.push(`handles: ${reply.handles.join(", ")}`);
  if (reply.error) {
    const line = await itemError(reply.error, validKeys);
    if (line) lines.push(line);
  }
  if (footer) lines.push(footer);
  return {
    isError: reply.ok === false,
    content: [{ type: "text" as const, text: lines.join("\n") }],
    details: reply,
  };
}
