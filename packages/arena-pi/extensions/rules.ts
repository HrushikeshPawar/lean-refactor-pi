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

export type ProbePlan = { ok: true; proof?: string; drafts?: string[]; note?: string } | { ok: false; detail: string };

/** A draft that is only a hole placeholder (`sorry`, `by sorry`, `:= by sorry`) carries no attempt. */
function placeholder(draft: string): boolean {
  return /^(:=\s*)?(by\s+)?sorry$/.test(draft.trim());
}

/**
 * Some models fill both `proof` and `drafts`. Drop placeholder drafts; probe the proof alone when
 * nothing else remains, otherwise batch the proof with the real drafts (at most four in total).
 */
export function planProbe(params: { proof?: string; drafts?: string[] }): ProbePlan {
  const { proof, drafts } = params;
  if (proof === undefined && drafts === undefined) return { ok: false, detail: "Pass proof or drafts." };
  if (proof === undefined) return { ok: true, drafts };
  if (drafts === undefined) return { ok: true, proof };
  const real = drafts.filter(draft => !placeholder(draft));
  if (!real.length) return { ok: true, proof, note: "Placeholder drafts were ignored because proof was given." };
  if (real.length + 1 > 4) return { ok: false, detail: "Pass proof or up to four drafts, not both." };
  return { ok: true, drafts: [proof, ...real], note: "proof was probed as draft 1 together with drafts." };
}

type Metrics = { candidate?: string; tokens?: number | null; heartbeats?: number | null; proxy?: number | null } | null | undefined;
/** A route as the harness fingerprints it from compiled proofs (see arena/routes.py). */
export interface RouteRow {
  route: string; label?: string; original?: boolean; attempts?: number; best_proxy?: number | null; best_candidate?: string | null;
  /** Goal-state depth, from the ledger: distinct goal states, fewest open holes, stale streak, explored or opened, credited. */
  depth?: number; new_states?: number; min_holes?: number | null; stale_streak?: number; stale?: boolean; explored?: boolean; credited?: boolean;
}

/** The routes that carry model attempts, as neutral facts only: no label, so nothing names or frames a strategy. */
export function routesText(routes: RouteRow[]): string {
  const rows = routes.filter(row => (row.attempts ?? 0) > 0);
  return rows.length ? rows.map(row => {
    const tag = row.original ? " (original's route)" : row.credited ? " (credited)" : row.credited === false || row.depth !== undefined ? " (not credited)" : "";
    const states = row.depth === undefined ? "" : ` \u00b7 ${row.depth} goal state${row.depth === 1 ? "" : "s"}`;
    const best = row.best_proxy != null ? `best proxy ${row.best_proxy}${row.best_candidate ? ` (${row.best_candidate})` : ""}` : "no scored proof";
    return `${row.route}${tag} \u00b7 ${row.attempts} attempt${row.attempts === 1 ? "" : "s"}${states} \u00b7 ${best}`;
  }).join("; ") : "none";
}

/** What changed on the routes since the last refusal: attempts made, attempts that left a goal state new to their route, credited routes opened. */
export interface SinceRefusal { attempts: number; newStates: number; creditedOpened: number }
export type RouteStats = Record<string, { attempts: number; new_states: number }>;

export function sinceRefusal(rows: RouteRow[], previous: RouteStats, previousCredited: Set<string>): SinceRefusal {
  let attempts = 0, newStates = 0, creditedOpened = 0;
  for (const row of rows) {
    const before = previous[row.route] ?? { attempts: 0, new_states: 0 };
    attempts += Math.max(0, (row.attempts ?? 0) - before.attempts);
    newStates += Math.max(0, (row.new_states ?? 0) - before.new_states);
    if (row.credited && (row.attempts ?? 0) > 0 && !previousCredited.has(row.route)) creditedOpened += 1;
  }
  return { attempts, newStates, creditedOpened };
}

/** One harness line for routes whose stale streak is newly at its limit; `noticed` keeps routes already told, until the streak breaks. */
export function staleNotice(rows: RouteRow[], noticed: Set<string>): string | undefined {
  const lines: string[] = [];
  for (const row of rows) {
    if (!row.stale) { noticed.delete(row.route); continue; }
    if (noticed.has(row.route)) continue;
    noticed.add(row.route);
    lines.push(`[arena] ${row.route}: the last ${row.stale_streak} attempts left goal states already seen on this route.`);
  }
  return lines.length ? lines.join(" ") : undefined;
}

export interface FinishPushInput {
  usedPct: number; remainingUsd: number; capUsd: number;
  baseline: Metrics; best: Metrics; top?: Metrics[];
  ideas: Array<{ id: string; title?: string; status?: string; attempts?: number; best?: Metrics }>;
  refusals: number;
  /** An idea absent at the previous refusal now has proof attempts. */
  newIdeaProbed: boolean;
  /** Harness route fingerprints; when present they replace the model's ideas as the record of what was tried. */
  routes?: RouteRow[];
  /** A route absent at the previous refusal now has proof attempts. */
  newRouteProbed?: boolean;
  /** Goal-state progress since the last refusal; when present it replaces newRouteProbed. */
  sinceRefusal?: SinceRefusal;
}

const saved = (reference: number | null | undefined, value: number | null | undefined) =>
  typeof reference === "number" && reference > 0 && typeof value === "number"
    ? Math.round(100 * (1 - value / reference)) : null;

/** Per-axis headroom against the original proof and against the lowest value seen on any candidate. */
export function axisHeadroom(baseline: Metrics, best: Metrics, top: Metrics[] = []) {
  const all = [best, ...top].filter(Boolean) as NonNullable<Metrics>[];
  const lowest = (key: "tokens" | "heartbeats") =>
    all.reduce<number | null>((low, item) => typeof item[key] === "number" && (low === null || item[key]! < low) ? item[key]! : low, null);
  const lowTokens = lowest("tokens"), lowHeartbeats = lowest("heartbeats");
  return {
    tokens_saved_pct: saved(baseline?.tokens, best?.tokens),
    heartbeats_saved_pct: saved(baseline?.heartbeats, best?.heartbeats),
    tokens_vs_lowest_seen: lowTokens, heartbeats_vs_lowest_seen: lowHeartbeats,
  };
}

/** Spend, the 10% rule and per-axis points left: the facts shared by the finish refusal and the plain-text continuation. */
function allowanceFacts(usedPct: number, remainingUsd: number, capUsd: number, headroom: ReturnType<typeof axisHeadroom>) {
  const pct = (value: number | null) => value === null ? "unknown" : `${value}%`;
  const spentPct = Math.min(100, Math.max(0, usedPct));
  // The left share comes from the unrounded remainder, to one decimal, so it matches the gate (10.7% never reads as 11%).
  const leftPct = capUsd > 0 ? Math.min(100, Math.max(0, 100 * remainingUsd / capUsd)) : 0;
  const spend = `$${(capUsd * spentPct / 100).toFixed(2)} of $${capUsd} spent, $${remainingUsd.toFixed(2)} (${leftPct.toFixed(1)}%) left. ` +
    `Stop condition: arena_finish is accepted when $${(capUsd * 0.1).toFixed(2)} (10%) or less of the allowance remains.`;
  // Each axis is a third of the score: points not yet earned = (100 - saved%) / 3.
  const left = (value: number | null) => value === null ? "unknown" : `${((100 - value) / 3).toFixed(1)}`;
  const axes = `Current best, saving vs the original and score points not yet earned per axis: tokens ${pct(headroom.tokens_saved_pct)} saved, ${left(headroom.tokens_saved_pct)} pts left; ` +
    `heartbeats ${pct(headroom.heartbeats_saved_pct)} saved, ${left(headroom.heartbeats_saved_pct)} pts left.`;
  return { spend, axes, head: `Stop refused: ${spend}` };
}

/** The reply to an arena_finish confirm that is refused because too much allowance is left. */
export function finishPush(input: FinishPushInput) {
  const headroom = axisHeadroom(input.baseline, input.best, input.top);
  const byRoute = input.routes !== undefined;
  const tried: Array<Record<string, any>> = byRoute
    ? input.routes!.filter(row => (row.attempts ?? 0) > 0).map(row => ({ id: row.route, status: row.original ? "original route" : "tried",
      attempts: row.attempts ?? 0, best_proxy: row.best_proxy ?? null,
      ...(row.depth === undefined ? {} : { goal_states: row.depth, min_holes: row.min_holes ?? null, explored: Boolean(row.explored), credited: Boolean(row.credited) }) }))
    : input.ideas.map(idea => ({ id: idea.id, title: idea.title, status: idea.status,
      attempts: idea.attempts ?? 0, best_proxy: idea.best?.proxy ?? null }));
  const triedText = byRoute ? routesText(input.routes!) : tried.length
    ? tried.map(item => `${item.id} "${item.title ?? ""}" (${item.attempts} attempt${item.attempts === 1 ? "" : "s"}, best proxy ${item.best_proxy ?? "none"})`).join("; ")
    : "none recorded";
  const { head, axes } = allowanceFacts(input.usedPct, input.remainingUsd, input.capUsd, headroom);
  const routesLine = byRoute ? `Routes tried: ${triedText}.` : `Ideas tried: ${triedText}.`;
  const message = `${head} ${routesLine} ${axes}`;
  return { headroom, tried, message: message.length > FINISH_MESSAGE_MAX ? `${message.slice(0, FINISH_MESSAGE_MAX - 1)}\u2026` : message };
}

/** The refusal never grows with the run: it states a handful of facts. */
export const FINISH_MESSAGE_MAX = 1500;

/** Continuation text when a turn ends with a plain answer while more than 10% of the allowance remains: facts only, same pieces as the finish refusal. */
export function continuationPush(args: { usedPct: number; remainingUsd: number; capUsd: number; baseline: Metrics; best: Metrics; top?: Metrics[]; routes?: RouteRow[] }): string {
  const { spend, axes } = allowanceFacts(args.usedPct, args.remainingUsd, args.capUsd, axisHeadroom(args.baseline, args.best, args.top));
  const routes = args.routes ? ` Routes tried: ${routesText(args.routes)}.` : "";
  const message = `The turn ended with text and no tool call. ${spend}${routes} ${axes}`;
  return message.length > FINISH_MESSAGE_MAX ? `${message.slice(0, FINISH_MESSAGE_MAX - 1)}\u2026` : message;
}

export const PROFILE_MODEL_ENTRIES = 12;

/** Model-facing arena_profile result: totals, hotspots and the top entries and lines; the full profile stays in the run ledger. */
export function trimProfile(result: Record<string, any>, limit = PROFILE_MODEL_ENTRIES): Record<string, any> {
  if (result.ok === false) return result;
  const top = (rows: any, key: string): { rows: any[]; omitted: number } => {
    if (!Array.isArray(rows) || rows.length <= limit) return { rows: rows ?? [], omitted: 0 };
    const keep = new Set(rows.map((row, index) => [index, Number(row?.[key] ?? 0)] as const)
      .sort((a, b) => b[1] - a[1] || a[0] - b[0]).slice(0, limit).map(([index]) => index));
    return { rows: rows.filter((_, index) => keep.has(index)), omitted: rows.length - limit };
  };
  const entries = top(result.entries, "hb"), lines = top(result.line_profile, "self_hb");
  const omitted = (result.omitted_entries ?? 0) + entries.omitted;
  const trimmed = { ...result, entries: entries.rows, omitted_entries: omitted, line_profile: lines.rows };
  if (entries.omitted || lines.omitted) {
    trimmed.trimmed_for_model = `Showing the top ${limit} entries and lines by cost; ${entries.omitted} entries and ${lines.omitted} lines are omitted here (the full profile is stored with the run).`;
  }
  return trimmed;
}
