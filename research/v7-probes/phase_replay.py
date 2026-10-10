"""Offline replay of v6 budget timelines: keeps, stall-rule gaps, phase timing.
Read-only. Usage: python3 -I phase_replay.py  (writes phase_replay.json and phase-v6.md here)."""
import json, glob, os, sys, bisect, importlib.util, collections

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("graph_audit", os.path.join(HERE, "graph_audit.py"))
GA = importlib.util.module_from_spec(spec); spec.loader.exec_module(GA)
ROOT, PREF = GA.ROOT, GA.PREF
MS = (5, 8, 12, 16, 24)


def pct(xs, q):
    if not xs: return None
    s = sorted(xs); k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def load(d):
    led = [json.loads(l) for l in open(d + "/ledger.jsonl") if l.strip()]
    # spend timeline: cumulative turn_end cost, sampled at each arena tool start (ts in event)
    starts_ts, starts_cum = [], []
    cum = 0.0
    for l in open(d + "/events.jsonl"):
        if l.startswith('{"type":"turn_end"'):
            u = json.loads(l)["message"].get("usage") or {}
            cum += float((u.get("cost") or {}).get("total") or 0.0)
        elif l.startswith('{"type":"tool_execution_start"'):
            j = json.loads(l)
            if "ts" in j:
                starts_ts.append(float(j["ts"])); starts_cum.append(cum)
    total = cum
    clock = "ts" if starts_ts else "node"  # node: no tool timestamps, spend is approximated by node index

    def spend_at(t):
        if clock == "node": return None
        i = bisect.bisect_right(starts_ts, t) - 1
        return starts_cum[i] if i >= 0 else 0.0

    nodes, order = {}, []
    for e in led:
        k = e.get("kind")
        if k == "candidate":
            i = e["candidate_id"]
            if i not in nodes:
                nodes[i] = dict(id=i, parent=(e.get("parents") or [None])[0], origin=e.get("origin"),
                                t_create=e["ts"], spend_create=spend_at(e["ts"]))
                order.append(i)
        elif k == "probe":
            i = e["proof_id"]
            if i not in nodes:
                nodes[i] = dict(id=i, parent=e.get("parent"), origin="probe",
                                t_create=e["ts"], spend_create=spend_at(e["ts"]))
                order.append(i)
    # scores: prefer full-mode local_proxy; fall back to fast estimated_proxy (assumes full compat)
    score = {}
    for e in led:
        if e.get("kind") != "evaluation": continue
        c = e["candidate_id"]; r = e.get("result") or {}; m = r.get("metrics") or {}
        comp = r.get("compat") or {}
        first_ok = next(iter(comp.values()), {}).get("passed") if comp else False
        if not (r.get("ok") and m.get("compiled") and first_ok): continue
        mode = e.get("mode")
        p = r.get("local_proxy") if mode == "full" else m.get("estimated_proxy")
        if p is None: continue
        rank = 1 if mode == "full" else 0
        cur = score.get(c)
        if cur is None or rank > cur["rank"] or (rank == cur["rank"] and p > cur["proxy"]):
            score[c] = dict(proxy=float(p), rank=rank, mode=mode, t=e["ts"], spend_score=spend_at(e["ts"]))
    if clock == "node":
        N = len(order)
        for n, i in enumerate(order):
            nodes[i]["spend_create"] = total * (n + 1) / N
    for i in order:
        if i in score:
            nodes[i]["score"] = score[i]["proxy"]; nodes[i]["mode"] = score[i]["mode"]
            nodes[i]["spend_score"] = score[i]["spend_score"] if clock == "ts" else nodes[i]["spend_create"]
    scored = [i for i in order if "score" in nodes[i]]
    return dict(led=led, nodes=nodes, order=order, scored=scored, total=total, clock=clock)


def analyse(name, d):
    R = load(d); nodes, order, scored, total = R["nodes"], R["order"], R["scored"], R["total"]
    clock = R["clock"]
    if len(scored) < 5: return None
    idx = {i: n for n, i in enumerate(order)}
    # keeps: strict improvement over best so far (baseline 0 = unscored reference), creation order
    keeps, best = [], 0.0
    for i in order:
        if "score" in nodes[i] and nodes[i]["score"] > best:
            keeps.append(i); best = nodes[i]["score"]
    keepset = set(keeps)
    final = best; final_id = keeps[-1] if keeps else None
    # keep gaps in nodes and $ (anchor = reference, index 0, spend 0)
    anchor = order[0]
    seq = [anchor] + keeps
    gap_nodes, gap_usd = [], []
    cut_any = {m: [] for m in MS}; cut_lin = {m: [] for m in MS}
    for a, b in zip(seq, seq[1:]):
        g = idx[b] - idx[a] - 1
        gap_nodes.append(g)
        gap_usd.append(nodes[b]["spend_create"] - nodes[a]["spend_create"])
    # lineage gap per keep: non-keep recorded ancestors back to nearest keep ancestor or root
    lin_gap = {}
    for k in keeps:
        n = 0; p = nodes[k]["parent"]; seen = set()
        while p and p in nodes and p not in keepset and p not in seen:
            seen.add(p); n += 1; p = nodes[p]["parent"]
        lin_gap[k] = n
    # per-m cut-off keeps and stall simulation (counter resets on keep and on fire)
    prev_keep_idx = idx[anchor]
    any_gap = {}
    for k, g in zip(keeps, gap_nodes):
        any_gap[k] = g
    stall = {}
    for m in MS:
        cnt = 0; fires = []
        for n, i in enumerate(order):
            if i in keepset: cnt = 0; continue
            cnt += 1
            if cnt >= m:
                fires.append(nodes[i]["spend_create"]); cnt = 0
        ca = [k for k in keeps if any_gap[k] >= m]
        cl = [k for k in keeps if lin_gap[k] >= m]
        def gain(ks):
            out = 0.0
            for k in ks: out += nodes[k]["score"] - (nodes[keeps[keeps.index(k) - 1]]["score"] if keeps.index(k) else 0.0)
            return out
        first_fire = fires[0] if fires else None
        stall[m] = dict(fires=len(fires), first_fire_usd=first_fire,
                        first_fire_pct=(100 * first_fire / total if first_fire is not None and total else None),
                        after_first_usd=(total - first_fire if first_fire is not None else 0.0),
                        after_first_pct=(100 * (total - first_fire) / total if first_fire is not None and total else 0.0),
                        cut_any=len(ca), cut_lin=len(cl),
                        cut_any_gain_pct=(100 * gain(ca) / final if final else 0.0),
                        cut_lin_gain_pct=(100 * gain(cl) / final if final else 0.0),
                        final_from_cut_any=(final_id in ca), final_from_cut_lin=(final_id in cl),
                        cut_any_ids=ca, cut_lin_ids=cl)
    # best-so-far by spend fraction (score time) and timing of final best / last keep
    def best_by(frac):
        b = 0.0
        for i in scored:
            if nodes[i]["spend_score"] <= frac * total and nodes[i]["score"] > b: b = nodes[i]["score"]
        return b
    final_first = next(i for i in order if "score" in nodes[i] and nodes[i]["score"] == final)
    last_keep = keeps[-1]
    def depth(i):
        n = 0; p = nodes[i]["parent"]
        while p and p in nodes and n < 500: n += 1; p = nodes[p]["parent"]
        return n
    pct_of = lambda usd: 100 * usd / total if total else 0.0
    return dict(run=name, clock=clock, nodes=len(order), scored=len(scored), keeps=len(keeps), total_usd=total,
                final=final, final_depth=depth(final_id), final_node_idx=idx[final_id],
                final_found_pct=pct_of(nodes[final_first]["spend_score"]),
                last_keep_pct=pct_of(nodes[last_keep]["spend_score"]), last_keep_idx=idx[last_keep],
                gap_nodes=gap_nodes, gap_usd=gap_usd, stall=stall,
                p30=best_by(0.30), p75=best_by(0.75), p90=best_by(0.90),
                keep_list=[(idx[k], round(nodes[k]["score"], 2), round(pct_of(nodes[k]["spend_score"]), 1), any_gap[k], lin_gap[k]) for k in keeps])


def fmt(x, nd=1):
    return "-" if x is None else (f"{x:.{nd}f}")


def main():
    runs = []
    for d in sorted(glob.glob(ROOT + "/*")):
        b = os.path.basename(d)
        if not b.startswith(PREF) or not os.path.exists(d + "/ledger.jsonl") or not os.path.exists(d + "/events.jsonl"): continue
        try:
            r = analyse(b, d)
        except Exception as ex:
            print("ERR", b, ex, file=sys.stderr); continue
        if r: runs.append(r)
    L = []
    P = L.append
    P(f"# Phase replay, v6 runs ({len(runs)} runs with >=5 scored nodes)\n")
    P("Clock: ts = spend mapped from tool-start timestamps; node = run has no tool timestamps (pilot runs), spend is linear in node index (approximate).\n")
    P("Generated by runs/analysis/experiments/phase_replay.py. Spend = sum of turn_end costs, mapped to ledger rows via tool-start timestamps. Score = full-mode local_proxy, else fast estimated_proxy (first compat version must pass). Keep = strict improvement over best-so-far (baseline 0), in creation order. Node = unique candidate or probe id.\n")
    P("## Run overview\n")
    P("| run | nodes | scored | keeps | $ total | final proxy | final depth | final found % | last keep % |")
    P("|---|---|---|---|---|---|---|---|---|")
    for r in runs:
        P(f"| {r['run']} ({r['clock']}) | {r['nodes']} | {r['scored']} | {r['keeps']} | {r['total_usd']:.3f} | {r['final']:.2f} | {r['final_depth']} | {fmt(r['final_found_pct'])} | {fmt(r['last_keep_pct'])} |")
    P("\n## 2. Gap between consecutive keeps (anchor = reference node)\n")
    P("| scope | n gaps | median | p75 | p90 | max |")
    P("|---|---|---|---|---|---|")
    pooled_n = [g for r in runs for g in r["gap_nodes"]]
    pooled_u = [g for r in runs if r["clock"] == "ts" for g in r["gap_usd"]]
    def row(lbl, xs, nd):
        P(f"| {lbl} | {len(xs)} | {fmt(pct(xs,.5),nd)} | {fmt(pct(xs,.75),nd)} | {fmt(pct(xs,.9),nd)} | {fmt(max(xs) if xs else None,nd)} |")
    row("POOLED nodes (all runs)", pooled_n, 0); row("POOLED $ (ts runs only)", pooled_u, 3)
    for r in runs:
        row(f"{r['run'][:60]} nodes", r["gap_nodes"], 0)
    P("\nPer-run $ gaps (median / max):\n")
    P("| run | median $ | max $ |"); P("|---|---|---|")
    for r in runs: P(f"| {r['run'][:60]} ({r['clock']}) | {fmt(pct(r['gap_usd'],.5),3)} | {fmt(max(r['gap_usd']) if r['gap_usd'] else None,3)} |")
    P("\n## 3. Stall rule m (any-node = gap in creation order; lineage = non-keep recorded ancestors)\n")
    P("| m | runs firing | fires/run (mean) | median spend after 1st fire % | pooled cut-off keeps any / lineage | cut-off gain % of final (pooled any / lineage) | runs whose final best is a cut-off keep (any / lineage) |")
    P("|---|---|---|---|---|---|---|")
    summary3 = {}
    for m in MS:
        fire_runs = sum(1 for r in runs if r["stall"][m]["fires"])
        mean_f = sum(r["stall"][m]["fires"] for r in runs) / len(runs)
        med_after = pct([r["stall"][m]["after_first_pct"] for r in runs if r["stall"][m]["fires"]], .5)
        ca = sum(r["stall"][m]["cut_any"] for r in runs); cl = sum(r["stall"][m]["cut_lin"] for r in runs)
        num_a = sum(r["stall"][m]["cut_any_gain_pct"] * r["final"] for r in runs) / 100
        num_l = sum(r["stall"][m]["cut_lin_gain_pct"] * r["final"] for r in runs) / 100
        den = sum(r["final"] for r in runs)
        fa = sum(r["stall"][m]["final_from_cut_any"] for r in runs); fl = sum(r["stall"][m]["final_from_cut_lin"] for r in runs)
        summary3[m] = dict(runs_firing=fire_runs, fires_mean=mean_f, cut_any=ca, cut_lin=cl, gain_any_pct=100*num_a/den, gain_lin_pct=100*num_l/den, final_cut_any=fa, final_cut_lin=fl)
        P(f"| {m} | {fire_runs}/{len(runs)} | {mean_f:.1f} | {fmt(med_after)} | {ca} / {cl} | {100*num_a/den:.1f} / {100*num_l/den:.1f} | {fa} / {fl} |")
    P("\nPer run, m=8 and m=16 (fires / first-fire % / cut-any / cut-lin / gain% any / gain% lin):\n")
    P("| run | m=8 | m=16 |"); P("|---|---|---|")
    for r in runs:
        c = []
        for m in (8, 16):
            s = r["stall"][m]
            c.append(f"{s['fires']} / {fmt(s['first_fire_pct'])} / {s['cut_any']} / {s['cut_lin']} / {s['cut_any_gain_pct']:.1f} / {s['cut_lin_gain_pct']:.1f}")
        P(f"| {r['run'][:60]} | {c[0]} | {c[1]} |")
    P("\n## 4. Budget position of final best and last keep (10% bins, count of runs)\n")
    bins_f = [0]*10; bins_l = [0]*10
    ts_runs = [r for r in runs if r["clock"] == "ts"]
    for r in ts_runs:
        if r["final_found_pct"] is not None: bins_f[min(9, int(r["final_found_pct"] // 10))] += 1
        bins_l[min(9, int(r["last_keep_pct"] // 10))] += 1
    P(f"(pooled over the {len(ts_runs)} runs with tool timestamps; node-clock runs excluded)\n")
    P("| bin | 0-10 | 10-20 | 20-30 | 30-40 | 40-50 | 50-60 | 60-70 | 70-80 | 80-90 | 90-100 |")
    P("|---|" + "---|"*10)
    P("| final best found | " + " | ".join(str(x) for x in bins_f) + " |")
    P("| last keep | " + " | ".join(str(x) for x in bins_l) + " |")
    P("\n## 5. Best proxy by spend fraction vs final\n")
    P("| run (clock) | final | @30% | @75% | @90% | @30 / final | @75 / final | @90 / final |")
    P("|---|---|---|---|---|---|---|---|")
    rat = {30: [], 75: [], 90: []}
    for r in runs:
        f = r["final"] or 1
        if r["clock"] == "ts":
            for k in (30, 75, 90):
                rat[k].append(r[f"p{k}"] / f)
        P(f"| {r['run'][:60]} ({r['clock']}) | {r['final']:.2f} | {r['p30']:.2f} | {r['p75']:.2f} | {r['p90']:.2f} | {100*r['p30']/f:.0f}% | {100*r['p75']/f:.0f}% | {100*r['p90']/f:.0f}% |")
    P(f"\nMedian ratio to final over ts runs ({len(rat[30])}): 30% {100*pct(rat[30],.5):.0f}%, 75% {100*pct(rat[75],.5):.0f}%, 90% {100*pct(rat[90],.5):.0f}%. Node-clock runs are approximate (spend linear in node index) and are listed for reference only.")
    txt = "\n".join(L) + "\n"
    open(os.path.join(HERE, "phase-v6.md"), "w").write(txt)
    slim = [{k: v for k, v in r.items() if k != "stall"} | {"stall": {m: {kk: vv for kk, vv in s.items() if not kk.endswith("_ids")} for m, s in r["stall"].items()}} for r in runs]
    json.dump(dict(runs=slim, summary3=summary3), open(os.path.join(HERE, "phase_replay.json"), "w"), indent=1, default=str)
    print(txt)


if __name__ == "__main__":
    main()
