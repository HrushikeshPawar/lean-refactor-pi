import { numbers, render } from "./text.ts";

type Metrics = { tokens?: number | null; heartbeats?: number | null } | null | undefined;

export function continuationKey(failed: boolean): "request_failed" | "turn_ended_with_text" {
  return failed ? "request_failed" : "turn_ended_with_text";
}

function saved(reference: number | null | undefined, value: number | null | undefined): number | null {
  return typeof reference === "number" && reference > 0 && typeof value === "number"
    ? Math.round(100 * (1 - value / reference)) : null;
}

async function allowanceFacts(usedPct: number, remainingUsd: number, capUsd: number, baseline: Metrics, best: Metrics) {
  const left = (value: number | null) => value === null ? "unknown" : `${((100 - value) / 3).toFixed(1)}`;
  const tokensSaved = saved(baseline?.tokens, best?.tokens);
  const heartbeatsSaved = saved(baseline?.heartbeats, best?.heartbeats);
  const remainingPct = capUsd > 0 ? Math.min(100, Math.max(0, 100 * remainingUsd / capUsd)) : 0;
  const finishFraction = (await numbers()).finish_remaining_pct / 100;
  const spend = await render("messages/refusals.allowance", {
    spent: (capUsd * Math.min(100, Math.max(0, usedPct)) / 100).toFixed(2), cap: capUsd,
    remaining: remainingUsd.toFixed(2), left: remainingPct.toFixed(1),
    finish_amount: (capUsd * finishFraction).toFixed(2),
  });
  const axes = await render("messages/refusals.axes", {
    tokens_saved: tokensSaved === null ? "unknown" : `${tokensSaved}%`, tokens_left: left(tokensSaved),
    heartbeats_saved: heartbeatsSaved === null ? "unknown" : `${heartbeatsSaved}%`, heartbeats_left: left(heartbeatsSaved),
  });
  return `${spend} ${axes}`;
}

export async function continuationPush(args: {
  failed: boolean; cause?: string; usedPct: number; remainingUsd: number; capUsd: number;
  baseline: Metrics; best: Metrics; bestNode: string;
}): Promise<string> {
  const facts = await allowanceFacts(args.usedPct, args.remainingUsd, args.capUsd, args.baseline, args.best);
  const values = { facts, best_node: args.bestNode || "none",
    ...(args.failed ? { cause_clause: args.cause ? await render("messages/continuation.cause_clause", { cause: args.cause }) : "" } : {}) };
  return render(`messages/continuation.${continuationKey(args.failed)}`, values);
}
