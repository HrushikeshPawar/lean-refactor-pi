import { spendFooter } from "./spend.ts";
import { render } from "./text.ts";

type Metrics = { tokens?: number | null; heartbeats?: number | null } | null | undefined;

// The campaign's `state` skeleton: how the recent attempts relate to the best proof's skeleton.
export type Skeleton = { attempts?: number; same_route?: number; top_step?: string; top_share_pct?: number } | null | undefined;

export function continuationKey(failed: boolean, cut = false): "request_failed" | "turn_cut" | "turn_ended_with_text" {
  return failed ? "request_failed" : cut ? "turn_cut" : "turn_ended_with_text";
}

// One neutral fact, only when the last attempts all kept the best proof's skeleton. No advice.
async function skeletonFact(skeleton: Skeleton): Promise<string | undefined> {
  const attempts = skeleton?.attempts;
  const step = skeleton?.top_step;
  const share = skeleton?.top_share_pct;
  if (typeof attempts !== "number" || attempts < 6 || skeleton?.same_route !== attempts) return undefined;
  if (typeof step !== "string" || typeof share !== "number") return undefined;
  return render("messages/continuation.skeleton", { attempts: String(attempts), top_step: step, top_share_pct: String(Math.round(share)) });
}

// Spend, then the skeleton fact when present.
export async function continuationFacts(spentUsd: number, limitUsd: number, _baseline: Metrics, _best: Metrics, skeleton?: Skeleton) {
  const facts = [await spendFooter(spentUsd, limitUsd)];
  const fact = await skeletonFact(skeleton);
  if (fact) facts.push(fact);
  return facts.join("\n");
}

export async function continuationPush(args: {
  failed: boolean; cause?: string; cutTokens?: number; skeleton?: Skeleton;
  spentUsd: number; limitUsd: number; baseline: Metrics; best: Metrics;
}): Promise<string> {
  const key = continuationKey(args.failed, args.cutTokens !== undefined);
  const facts = await continuationFacts(args.spentUsd, args.limitUsd, args.baseline, args.best, args.skeleton);
  const values: Record<string, string> = { facts };
  if (key === "request_failed") values.cause_clause = args.cause ? await render("messages/continuation.cause_clause", { cause: args.cause }) : "";
  if (key === "turn_cut") values.cut = await render("messages/errors.turn_cut", { tokens: String(args.cutTokens) });
  return render(`messages/continuation.${key}`, values);
}
