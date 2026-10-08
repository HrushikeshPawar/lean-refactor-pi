const PREFIXES = ["mcparenalean", "arena", "lean"];

/** Lowercase, drop separators, then drop each known prefix (`mcp__arena_lean__`, `arena_`, `lean_`) once, in order. */
export function toolCore(name: string): string {
  let core = name.toLowerCase().replace(/[^a-z0-9]/g, "");
  for (const prefix of PREFIXES) if (core.startsWith(prefix) && core.length > prefix.length) core = core.slice(prefix.length);
  return core;
}

function distance(left: string, right: string): number {
  const row = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let i = 1; i <= left.length; i++) {
    let diagonal = row[0];
    row[0] = i;
    for (let j = 1; j <= right.length; j++) {
      const above = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, diagonal + (left[i - 1] === right[j - 1] ? 0 : 1));
      diagonal = above;
    }
  }
  return row[right.length];
}

/** Nearest registered tool, comparing names modulo the known prefixes. Deterministic: ties go to the name that sorts first. */
export function nearestToolName(name: string, registered: readonly string[]): string | undefined {
  const core = toolCore(name);
  const ranked = [...new Set(registered)].filter(candidate => candidate !== name)
    .map(candidate => ({ candidate, score: distance(core, toolCore(candidate)) }))
    .sort((a, b) => a.score - b.score || (a.candidate < b.candidate ? -1 : a.candidate > b.candidate ? 1 : 0));
  return ranked[0] && ranked[0].score <= Math.max(2, Math.floor(core.length / 4)) ? ranked[0].candidate : undefined;
}

/** A list sent as text: JSON (`["a"]`) or Python-style (`['a', "b'"]`). Anything else is one item. */
function listFromText(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed.startsWith("[")) return [text];
  try {
    const parsed = JSON.parse(trimmed);
    if (Array.isArray(parsed)) return parsed.map(String);
  } catch { /* fall through to quoted items */ }
  const items = [...trimmed.matchAll(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g)].map(match => match[1] ?? match[2]);
  return items.length ? items : [text];
}

/**
 * Some models fill every optional field with an empty value ("", [""]) and send arrays as strings.
 * Treat empty values as absent and parse stringified arrays, using the tool's object schema.
 */
export function normalizeToolArguments<T>(params: T, schema: { properties?: Record<string, { type?: string }> }): T {
  if (!params || typeof params !== "object" || Array.isArray(params)) return params;
  const cleaned: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    let next: unknown = value;
    if (schema.properties?.[key]?.type === "array" && typeof next === "string") next = next.trim() ? listFromText(next) : [];
    // A validator may already have wrapped the text in a one-element array; unwrap it the same way.
    if (Array.isArray(next)) next = next.flatMap(item => typeof item === "string" && item.trim().startsWith("[")
      ? listFromText(item) : [item]).filter(item => !(typeof item === "string" && !item.trim()));
    const empty = next === null || next === undefined || (typeof next === "string" && !next.trim())
      || (Array.isArray(next) && next.length === 0);
    if (!empty) cleaned[key] = next;
  }
  return cleaned as T;
}
