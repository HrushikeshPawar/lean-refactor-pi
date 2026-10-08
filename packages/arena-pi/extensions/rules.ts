import { realpath } from "node:fs/promises";
import { dirname, relative, resolve, sep } from "node:path";

export interface EvaluateReferences {
  proof?: string; candidate?: string; from_probe?: string; parents?: string[];
}

export type EvaluatePlan =
  | { ok: false; detail: string }
  | { ok: true; proof?: string; candidate?: string; fromProbe?: string; parents: string[]; note?: string };

/** Decide what arena_evaluate scores. A proof wins over a stray candidate or probe, which becomes the parent. */
export function planEvaluate(params: EvaluateReferences): EvaluatePlan {
  const proof = params.proof?.trim() ? params.proof : undefined;
  const parents = params.parents ?? [];
  if (proof) {
    const reference = params.candidate || params.from_probe;
    if (!reference) return { ok: true, proof, parents };
    return { ok: true, proof, parents: parents.length ? parents : [reference],
      note: parents.length
        ? `${reference} was ignored because proof was given; the proof is scored with your parents.`
        : `${reference} was treated as the parent of the proof, because proof was given.` };
  }
  if ([params.candidate, params.from_probe].filter(Boolean).length !== 1) {
    return { ok: false, detail: "Pass exactly one of complete proof text, candidate (#N), or from_probe (pN)." };
  }
  return { ok: true, candidate: params.candidate || undefined, fromProbe: params.from_probe || undefined, parents };
}

function inside(path: string, parent: string): boolean {
  const rel = relative(parent, path);
  return rel === "" || (rel !== ".." && !rel.startsWith(`..${sep}`));
}

/** A reason to block a Lean MCP call whose file lies outside the run's scratch project, else undefined. */
export async function leanPathViolation(input: { file_path?: unknown; path?: unknown } | undefined,
                                        project: string): Promise<string | undefined> {
  const given = [input?.file_path, input?.path].find(value => typeof value === "string" && value !== "") as string | undefined;
  if (given === undefined) return undefined;
  const canonicalize = async (path: string) => realpath(path).catch(async () => {
    const parent = await realpath(dirname(path)).catch(() => dirname(path));
    return resolve(parent, path.split(sep).at(-1)!);
  });
  const root = await canonicalize(project);
  const candidate = resolve(project, given);
  if (inside(candidate, project) && inside(await canonicalize(candidate), root)) return undefined;
  return `Lean tools only read files inside this run's project (${project}); ${given} is outside it. Use a path relative to the project, such as the theorem's file_path.`;
}

export type InlineIdea = { ok: true; idea_id?: string; created?: boolean } | { ok: false; error: Record<string, any> };

/** Create the idea named by `idea` (a one-line route title) unless `idea_id` already names one. */
export async function resolveInlineIdea(params: { idea?: string; idea_id?: string },
                                        create: (title: string) => Promise<Record<string, any>>): Promise<InlineIdea> {
  if (params.idea_id) return { ok: true, idea_id: params.idea_id };
  const title = params.idea?.trim();
  if (!title) return { ok: true };
  const made = await create(title);
  if (made.ok === false || !made.id) return { ok: false, error: made.ok === false ? made : { ok: false, error: "idea was not created" } };
  return { ok: true, idea_id: made.id, created: true };
}
