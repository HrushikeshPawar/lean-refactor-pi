// One turn's ambient context: the sections each tool reply carries in `context` (arena/reply.py add_context), merged
// across the turn's tool calls and sent as one hidden message with the spend line last.

/** A reply's ambient context. A section is [header, ...lines]; header "" has none. */
export type ToolContext = { sections?: string[][]; kinds?: string[] };

/**
 * The text of one turn's hidden context message, or undefined when there is nothing new to say.
 * Sections with the same header merge in first-seen order, and identical lines appear once. The spend line, when
 * given, comes last, after a blank line.
 */
export function turnContext(contexts: ToolContext[], spend?: string): { content: string; kinds: string[] } | undefined {
  const groups = new Map<string, Set<string>>();
  const kinds = new Set<string>();
  for (const context of contexts) {
    for (const kind of context.kinds ?? []) kinds.add(kind);
    for (const [header = "", ...lines] of context.sections ?? []) {
      const group = groups.get(header) ?? new Set<string>();
      for (const line of lines) group.add(String(line));
      groups.set(header, group);
    }
  }
  const body: string[] = [];
  for (const [header, lines] of groups) {
    if (!lines.size) continue;
    if (header) body.push(header);
    body.push(...lines);
  }
  if (spend) kinds.add("spend");
  const content = [body.join("\n"), spend ?? ""].filter(Boolean).join("\n\n");
  if (!content) return undefined;
  return { content, kinds: [...kinds] };
}
