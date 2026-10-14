import { finishAllowed, spendFooter } from "./spend.ts";
import { render } from "./text.ts";

type Metrics = { tokens?: number | null; heartbeats?: number | null } | null | undefined;

export function continuationKey(failed: boolean): "request_failed" | "turn_ended_with_text" {
  return failed ? "request_failed" : "turn_ended_with_text";
}

// Points not yet earned on one axis: a third of the percentage still missing against the reference.
function pointsLeft(reference: number | null | undefined, value: number | null | undefined): string {
  if (typeof reference !== "number" || reference <= 0 || typeof value !== "number") return "unknown";
  return ((100 * value / reference) / 3).toFixed(1);
}

// Spend and points left per axis. Finish availability is stated only once finish is offered, by the same
// predicate that puts the finish tool in the tool list.
export async function continuationFacts(spentUsd: number, limitUsd: number, baseline: Metrics, best: Metrics) {
  const facts = [await spendFooter(spentUsd, limitUsd), await render("messages/continuation.points_left", {
    tokens: pointsLeft(baseline?.tokens, best?.tokens ?? baseline?.tokens),
    heartbeats: pointsLeft(baseline?.heartbeats, best?.heartbeats ?? baseline?.heartbeats),
  })];
  if (finishAllowed(spentUsd, limitUsd).allowed) facts.push(await render("messages/continuation.finish_available"));
  return facts.join("\n");
}

export async function continuationPush(args: {
  failed: boolean; cause?: string; spentUsd: number; limitUsd: number; baseline: Metrics; best: Metrics;
}): Promise<string> {
  const facts = await continuationFacts(args.spentUsd, args.limitUsd, args.baseline, args.best);
  const values = { facts,
    ...(args.failed ? { cause_clause: args.cause ? await render("messages/continuation.cause_clause", { cause: args.cause }) : "" } : {}) };
  return render(`messages/continuation.${continuationKey(args.failed)}`, values);
}
