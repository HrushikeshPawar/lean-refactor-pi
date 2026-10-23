import { render } from "./text.ts";

type Reply = {
  ok?: boolean;
  error?: Record<string, unknown> | string | null;
  facts?: string[];
  items?: Array<Record<string, any>>;
  handles?: string[];
  stop?: boolean;
};

function listText(value: unknown): string {
  const items = Array.isArray(value) ? value.map(String).filter(Boolean) : [];
  return items.length ? items.join(", ") : "none";
}

/** Every Python error has the shape {code, input, valid, forms}; a bare string comes from a failed command. */
async function errorLine(error: unknown, validKeys: string[]): Promise<string | undefined> {
  if (!error || typeof error !== "object") return typeof error === "string" ? error : undefined;
  const value = error as Record<string, unknown>;
  if (value.code === "empty_arguments") {
    return render("messages/errors.empty_arguments", { valid: validKeys.join(", ") || "none" });
  }
  // The template ends the input with its own period, and an empty valid list is left out rather than shown as "none".
  const input = String(value.input ?? "").trim().replace(/\.+$/, "") || "none";
  const code = String(value.code ?? "error");
  const valid = Array.isArray(value.valid) ? value.valid.map(String).filter(Boolean) : [];
  if (!valid.length) return render("messages/errors.request_bare", { code, input, forms: listText(value.forms) });
  return render("messages/errors.request", { code, input, valid: valid.join(", "), forms: listText(value.forms) });
}

/** The call's own result as text. Ambient state (`context`) is sent separately, once per turn (context.ts). */
export async function renderReply(reply: Reply, validKeys: string[] = []) {
  const lines = [...(reply.facts ?? [])];
  for (const item of reply.items ?? []) {
    const itemLines = Array.isArray(item.lines) ? item.lines.filter((line): line is string => typeof line === "string" && Boolean(line)) : [];
    if (itemLines.length) lines.push(...itemLines);
    // A failed item keeps its error (code, valid values, forms) after its own lines.
    if (!itemLines.length || item.ok === false) {
      const line = await errorLine(item.error, validKeys);
      if (line) lines.push(line);
    }
  }
  if (reply.error) {
    const line = await errorLine(reply.error, validKeys);
    if (line) lines.push(line);
  }
  return {
    isError: reply.ok === false,
    content: [{ type: "text" as const, text: lines.join("\n") }],
    details: reply,
  };
}
