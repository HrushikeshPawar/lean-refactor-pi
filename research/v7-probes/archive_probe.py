#!/usr/bin/env python3
"""Archive cell-key probe on v6 runs (offline, read-only; no Lean, no models).
Writes archive_probe.json, archive-v6.md and archive-label-sheet.md beside this file.
Usage: python3 -I archive_probe.py
Keys: K0 v6 ledger route | K1 (route, depth bucket, closed/sketch) | K2 (route, closed/sketch)
      K3 K1 + leading score axis | K4 route only.   Route = route_replay 'mix' signature with hysteresis.
"""
import difflib, json, os, random, re, statistics, sys, collections, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, ROOT)
import route_replay as RR  # noqa: E402
from arena import goalstate  # noqa: E402
from arena.routes import proof_body  # noqa: E402
spec = importlib.util.spec_from_file_location("phase_replay", os.path.join(HERE, "phase_replay.py"))
PR = importlib.util.module_from_spec(spec); spec.loader.exec_module(PR)

BASE = os.path.join(ROOT, "runs", "pi-budget")
M_STALL = 12
KEYS = ["K0", "K1", "K2", "K3", "K4"]
RNG = random.Random(7)


def short(name):
    n = name.replace("-deepseek-v4.1-flash-r1", "-DS").replace("-gpt-6-luna-r1", "-Luna").replace("-qwen3.8-flash-r1", "-Qwen")
    n = re.sub(r"^v6(cov|ark2|ark|pilot)-", lambda m: {"cov": "cov:", "ark": "ark:", "ark2": "ark2:", "pilot": "pilot:"}[m.group(1)], n)
    return n[:44]


def dbucket(d):
    return 0 if d <= 2 else 1 if d <= 7 else 2 if d <= 15 else 3


def lines(p):
    return [" ".join(l.split()) for l in proof_body(p).splitlines() if l.strip() and l.strip() != "by"]


def ldiff(a, b):
    la, lb = lines(a), lines(b)
    if abs(len(la) - len(lb)) > 3:
        return 99
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for t, i1, i2, j1, j2 in sm.get_opcodes() if t != "equal")


def runs():
    out = []
    for r in sorted(os.listdir(BASE)):
        d = os.path.join(BASE, r)
        if re.match(r"v6(cov|ark2?|pilot)-", r) and r.endswith("-r1") and os.path.exists(d + "/ledger.jsonl") and os.path.isdir(d + "/proofs"):
            out.append((r, d))
    return out


def axis_points(res):
    ax = ((res or {}).get("metrics") or {}).get("axes") or {}
    g = lambda k: (ax.get(k) or {}).get("contribution")
    return {"tok": g("tokens"), "hb": g("heartbeats"), "ver": g("compat")}


def build(name, d):
    ids, proofs, par_rr, results, hb, v6 = RR.load(__import__("pathlib").Path(d))
    P = PR.load(d)
    order = [i for i in P["order"] if i in proofs]
    if len(order) < 8:
        return None
    nodes = P["nodes"]
    idx = {i: n for n, i in enumerate(order)}
    parent = {i: (nodes[i]["parent"] if nodes[i]["parent"] in idx else None) for i in order}
    depth = {}
    for i in order:
        n, p, seen = 0, parent[i], set()
        while p and p not in seen and n < 500:
            seen.add(p); n += 1; p = parent.get(p)
        depth[i] = n
    # routes (causal, arrival order)
    sigs = {i: (RR.skeleton(proofs[i]), RR.steps(proofs[i])) for i in order}
    sim = lambda a, b: 0.5 * RR.sim_skel(a[0], b[0]) + 0.5 * RR.sim_set(a[1], b[1])
    route = RR.cluster(order, sigs, sim, parent)
    closed = {i: bool(i in results and goalstate.closed(results[i])) for i in order}
    score = {i: nodes[i]["score"] for i in order if "score" in nodes[i]}
    keeps, best = [], 0.0
    for i in order:
        if i in score and score[i] > best:
            keeps.append(i); best = score[i]
    if not keeps:
        return None
    # quality for archive ranking: proxy if scored, 0 for other closed, negative sorry count for sketches
    q = {}
    for i in order:
        if i in score: q[i] = score[i]
        elif closed[i]: q[i] = 0.0
        else: q[i] = -1.0 - proofs[i].count("sorry")
    # leading axis (causal: position of each axis within the run's closed range so far, frozen at arrival)
    rng = {"tok": [None, None], "hb": [None, None], "ver": [None, None]}
    axis = {}
    for i in order:
        if not closed[i]:
            axis[i] = "-"; continue
        pts = axis_points(results.get(i))
        for a, v in pts.items():
            if v is None: continue
            lo, hi = rng[a]
            rng[a] = [v if lo is None else min(lo, v), v if hi is None else max(hi, v)]
        pos = {}
        for a, v in pts.items():
            lo, hi = rng[a]
            if v is not None and hi is not None and hi > lo:
                pos[a] = (v - lo) / (hi - lo)
        axis[i] = max(("tok", "hb", "ver"), key=lambda a: (pos.get(a, -1), -("tok", "hb", "ver").index(a))) if pos else "-"
    status = {i: "C" if closed[i] else "S" for i in order}
    cells = {
        "K1": {i: (route[i], dbucket(depth[i]), status[i]) for i in order},
        "K2": {i: (route[i], status[i]) for i in order},
        "K3": {i: (route[i], dbucket(depth[i]), status[i], axis[i]) for i in order},
        "K4": {i: (route[i],) for i in order},
        "K0": {i: (v6[i]["route"],) for i in order if i in v6},
    }
    # submission source
    sub_id = None
    try:
        sub_id = json.load(open(d + "/submission.json")).get("candidate_id")
    except Exception:
        pass
    if sub_id not in idx: sub_id = None
    return dict(name=name, order=order, idx=idx, parent=parent, depth=depth, proofs=proofs, route=route, q=q, score=score,
                keeps=keeps, cells=cells, axis=axis, status=status, sub=sub_id, final=keeps[-1], sigs=sigs, sim=sim)


def archive_series(R, key):
    """Causal archive: yields (t, archive dict cell->best id, visits dict) after each node."""
    cell = R["cells"][key]; q = R["q"]; arch, vis = {}, collections.Counter()
    snaps = []
    for t, i in enumerate(R["order"]):
        c = cell.get(i)
        if c is not None:
            vis[c] += 1
            if c not in arch or q[i] > q[arch[c]]:
                arch[c] = i
        snaps.append((dict(arch), dict(vis)))
    return snaps


def descends(R, a, b):
    """a is an ancestor of b (recorded parents)."""
    p, n = R["parent"].get(b), 0
    while p and n < 600:
        if p == a: return True
        p = R["parent"].get(p); n += 1
    return False


def fires(R, M_STALL=M_STALL):
    """Stall rule, m=12, scope = subtree of the last keep (counter resets on keep and on fire; history unchanged)."""
    order, keepset = R["order"], set(R["keeps"])
    out, root, cnt = [], order[0], 0
    for t, i in enumerate(order):
        if i in keepset:
            root, cnt = i, 0; continue
        if i != root and descends(R, root, i):
            cnt += 1
            if cnt >= M_STALL:
                out.append(t); cnt = 0
    return out


def closest_prev(R, k, cache):
    """Text-closest earlier node(s) to node k (line ratio, ties within .02)."""
    if k in cache: return cache[k]
    L = {i: lines(R["proofs"][i]) for i in R["order"][: R["idx"][k] + 1]}
    sc = []
    for i in R["order"][: R["idx"][k]]:
        sc.append((difflib.SequenceMatcher(None, L[k], L[i], autojunk=False).ratio(), i))
    m = max(s for s, _ in sc) if sc else 0
    cache[k] = {i for s, i in sc if s >= m - 0.02}
    return cache[k]


def evaluate(R):
    out = {}
    order, idx, q = R["order"], R["idx"], R["q"]
    N = len(order)
    pairs = [(i, R["parent"][i]) for i in order if R["parent"][i] and ldiff(R["proofs"][i], R["proofs"][R["parent"][i]]) <= 3]
    fires_cache = {12: fires(R, 12), 6: fires(R, 6)}
    fl = fires_cache[12]
    cache = {}
    later_keeps = lambda t: [k for k in R["keeps"] if idx[k] > t]
    lineage = [R["final"]]
    p = R["parent"][R["final"]]
    while p:
        lineage.append(p); p = R["parent"][p]
    for key in KEYS:
        cell = R["cells"][key]
        snaps = archive_series(R, key)
        arch_end, vis_end = snaps[-1]
        m = {}
        m["cells"] = len(arch_end)
        # stability on the pairs with both nodes keyed
        sp = [(a, b) for a, b in pairs if a in cell and b in cell]
        m["stab_pairs"] = len(sp)
        def diff_at(a, b, pos): return cell[a][pos] != cell[b][pos]
        m["stab_total"] = sum(cell[a] != cell[b] for a, b in sp)
        m["stab_route"] = sum(cell[a][0] != cell[b][0] for a, b in sp)
        if key in ("K1", "K2", "K3"):
            m["stab_depth"] = sum(cell[a][1] != cell[b][1] for a, b in sp) if key != "K2" else 0
            m["stab_status"] = sum(cell[a][2 if key != "K2" else 1] != cell[b][2 if key != "K2" else 1] for a, b in sp)
        if key == "K3":
            m["stab_axis"] = sum(cell[a][3] != cell[b][3] for a, b in sp)
        # retention
        keyed = [i for i in order if i in cell]
        m["final_in_archive"] = R["final"] in arch_end.values()
        m["sub_in_archive"] = None if R["sub"] is None else R["sub"] in arch_end.values()
        m["sub_is_final"] = None if R["sub"] is None else R["sub"] == R["final"]
        anyp, latest = [], []
        for t in range(N):
            created = [i for i in lineage if idx[i] <= t]
            if not created: continue
            members = set(snaps[t][0].values())
            anyp.append(any(i in members for i in created))
            latest.append(max(created, key=lambda i: idx[i]) in members)
        m["lineage_any"] = sum(anyp) / len(anyp) if anyp else None
        m["lineage_latest"] = sum(latest) / len(latest) if latest else None
        # stall moves (m=12 headline; m=6 sensitivity for more firings)
        for mm, tag in ((12, "stall"), (6, "stall6")):
            fl = fires_cache[mm]
            hit = dict(fires=0, with_later=0, desc=0, close=0, cellhit=0, nexthit=0, rdesc=0.0, rclose=0.0, rcell=0.0, rnext=0.0)
            for t in fl:
                arch, vis = snaps[t]
                if not arch: continue
                hit["fires"] += 1
                lk = later_keeps(t)
                if not lk: continue
                hit["with_later"] += 1
                cs = list(arch)
                pick = min(cs, key=lambda c: (vis[c], -q[arch[c]]))
                def test(c):
                    B = arch[c]
                    d = any(descends(R, B, k) for k in lk)
                    cl = any(B in closest_prev(R, k, cache) for k in lk)
                    ch = any(cell.get(k) == c for k in lk)
                    nx = cell.get(lk[0]) == c
                    return d, cl, ch, nx
                r0 = test(pick)
                for f, v in zip(("desc", "close", "cellhit", "nexthit"), r0): hit[f] += v
                acc = [0, 0, 0, 0]
                for _ in range(100):
                    for j, v in enumerate(test(RNG.choice(cs))): acc[j] += v
                for f, v in zip(("rdesc", "rclose", "rcell", "rnext"), acc): hit[f] += v / 100
            m[tag] = hit
        # diversity
        cnt = collections.Counter(cell[i] for i in keyed)
        m["visited"] = len(cnt)
        m["top_share"] = max(cnt.values()) / len(keyed) if keyed else None
        m["keyed"] = len(keyed)
        out[key] = m
    out["_meta"] = dict(nodes=N, keeps=len(R["keeps"]), fires=len(fl), pairs_le3=len(pairs), routes=len(set(R["route"].values())),
                        final_score=R["score"][R["final"]], final_depth=R["depth"][R["final"]], sub_is_final=(R["sub"] == R["final"]) if R["sub"] else None)
    return out


# ---------------------------------------------------------------- hand-label sheet
def pick_pairs(Rs):
    cand = []
    for R in Rs:
        n = R["name"]
        if not ("putnam_1964_b2" in n or "Core.InitsUpdatesComm" in n):
            continue
        order = R["order"][:160]
        for x in range(len(order)):
            for y in range(x + 1, len(order)):
                a, b = order[x], order[y]
                if R["parent"].get(b) == a or R["parent"].get(a) == b:
                    pass
                if not (R["proofs"][a].strip() and R["proofs"][b].strip()): continue
                s = R["sim"](R["sigs"][a], R["sigs"][b])
                if 0.30 <= s <= 0.70 and R["proofs"][a] != R["proofs"][b]:
                    cand.append((R, a, b, s, R["route"][a] == R["route"][b]))
    def choose(pred, target, k, used):
        pool = sorted([c for c in cand if pred(c)], key=lambda c: abs(c[3] - target))
        out, runs_cnt = [], collections.Counter()
        for c in pool:
            key = (c[0]["name"], c[1]); key2 = (c[0]["name"], c[2])
            if (key, key2) in used or (key2, key) in used or key in used: continue
            if runs_cnt[c[0]["name"]] >= 6: continue
            out.append(c); used.add((key, key2)); used.add(key); runs_cnt[c[0]["name"]] += 1
            if len(out) == k: break
        return out
    used = set()
    sel = (choose(lambda c: c[4] and 0.60 <= c[3] <= 0.70, 0.60, 5, used)
           + choose(lambda c: c[4] and 0.30 <= c[3] < 0.45, 0.35, 5, used)
           + choose(lambda c: not c[4] and 0.30 <= c[3] <= 0.45, 0.35, 5, used)
           + choose(lambda c: not c[4] and 0.45 < c[3] < 0.60, 0.59, 5, used))
    return sel


def write_sheet(sel, path):
    RNG2 = random.Random(11)
    order = list(range(len(sel))); RNG2.shuffle(order)
    L = ["# Archive label sheet: same approach? (20 pairs)", "",
         "For each pair, read the two proofs (unified diff of the proof bodies, A to B) and answer **Y** if the two take the same proof approach "
         "(same shape of argument, differing only in lemma choice, naming, small fixes), **N** if they are different approaches. "
         "Pairs are shuffled. The route verdict and similarity at the end of this file are hidden until you finish; the similarity shown "
         "per pair is the 50/50 mix (skeleton ratio + step-hash Jaccard).", ""]
    for n, i in enumerate(order, 1):
        R, a, b, s, same = sel[i]
        A, B = R["proofs"][a], R["proofs"][b]
        diff = list(difflib.unified_diff(proof_body(A).splitlines(), proof_body(B).splitlines(), "A", "B", lineterm="", n=2))
        shown = diff[:70]
        L += [f"## Pair {n}", f"Run `{short(R['name'])}`, A = node #{R['idx'][a]} ({a[:8]}), B = node #{R['idx'][b]} ({b[:8]}); "
              f"mix similarity {s:.3f}; body lines A/B = {len(lines(A))}/{len(lines(B))}", "", "```diff", *shown]
        if len(diff) > 70: L.append(f"... ({len(diff) - 70} more diff lines)")
        L += ["```", "", "| same approach? Y/N | notes |", "|---|---|", "|  |  |", ""]
    L += ["---", "## Answer key (do not read before labelling)", "", "| pair | run | A | B | sim | K1 route call |", "|---|---|---|---|---|---|"]
    for n, i in enumerate(order, 1):
        R, a, b, s, same = sel[i]
        L.append(f"| {n} | {short(R['name'])} | {R['idx'][a]} | {R['idx'][b]} | {s:.3f} | {'same' if same else 'different'} |")
    open(path, "w").write("\n".join(L) + "\n")


# ---------------------------------------------------------------- report
def agg(res, key, f):
    return [f(r[key]) for r in res.values() if key in r]


def main():
    Rs, res = [], {}
    for name, d in runs():
        R = build(name, d)
        if not R: continue
        Rs.append(R); res[name] = evaluate(R)
        print("done", short(name), res[name]["_meta"], file=sys.stderr)
    json.dump(res, open(os.path.join(HERE, "archive_probe.json"), "w"), indent=1, default=str)
    sel = pick_pairs(Rs)
    write_sheet(sel, os.path.join(HERE, "archive-label-sheet.md"))

    def S(key, f): return sum(f(r[key]) for r in res.values())
    L = ["# Archive cell keys on v6 runs", "",
         f"`archive_probe.py`; {len(res)} runs with >=8 nodes and a keep ({sum(r['_meta']['nodes'] for r in res.values())} nodes). "
         "Route = mix signature with hysteresis (route_replay.py), assigned causally in arrival order. Archive = best node per cell "
         "(proxy; closed with no proxy = 0; sketches ranked by fewer `sorry`). Depth = recorded-parent depth. "
         "K0 only covers nodes that have a v6 route event.", ""]
    L += ["## Per-key summary (pooled over runs)", "",
          "| key | cells median / mean / max | runs with <=12 cells | stability: diff-cell share of <=3-line pairs (total / route / depth / status / axis) | final best in archive | final-best lineage in archive (any / latest, mean over time) | cells visited mean | top-cell share mean / max |",
          "|---|---|---|---|---|---|---|---|"]
    for k in KEYS:
        cells = agg(res, k, lambda m: m["cells"])
        sp = S(k, lambda m: m["stab_pairs"])
        fr = lambda f: S(k, lambda m: m.get(f, 0)) / sp if sp else float("nan")
        parts = [f"{fr('stab_total'):.3f}", f"{fr('stab_route'):.3f}",
                 f"{fr('stab_depth'):.3f}" if k in ("K1", "K3") else "-",
                 f"{fr('stab_status'):.3f}" if k in ("K1", "K2", "K3") else "-",
                 f"{fr('stab_axis'):.3f}" if k == "K3" else "-"]
        fin = sum(m[k]["final_in_archive"] for m in res.values()); fin_n = len(res)
        la = statistics.mean(m[k]["lineage_any"] for m in res.values() if m[k]["lineage_any"] is not None)
        ll = statistics.mean(m[k]["lineage_latest"] for m in res.values() if m[k]["lineage_latest"] is not None)
        vis = agg(res, k, lambda m: m["visited"]); ts = [m[k]["top_share"] for m in res.values() if m[k]["top_share"] is not None]
        L.append(f"| {k} | {statistics.median(cells):.0f} / {statistics.mean(cells):.1f} / {max(cells)} | {sum(c <= 12 for c in cells)}/{len(cells)} | "
                 f"{' / '.join(parts)} (n={sp}) | {fin}/{fin_n} | {la:.2f} / {ll:.2f} | {statistics.mean(vis):.1f} | {statistics.mean(ts):.2f} / {max(ts):.2f} |")
    for mm, tag in ((12, "stall"), (6, "stall6")):
        L += ["", f"## Stall-move usefulness (m={mm}, lineage scope; firings pooled){' (headline)' if mm == 12 else ' (sensitivity, more firings)'}", "",
              "Descend = some LATER keep descends from the picked cell's best node (recorded lineage). Closest = the best node is among the text-closest earlier nodes of some later keep. "
              "Cell = some later keep is filed in the picked cell. Next = the very next keep is filed in the picked cell. Random = mean over 100 random non-empty cells per firing. "
              "Only firings with at least one later keep count.", "",
              "| key | firings (with later keep) | descend: key / random | closest: key / random | cell: key / random | next keep cell: key / random |",
              "|---|---|---|---|---|---|"]
        for k in KEYS:
            n = S(k, lambda m: m[tag]["with_later"])
            g = lambda f: S(k, lambda m: m[tag][f])
            pct = lambda a, b: f"{100 * a / n:.1f}% / {100 * b / n:.1f}%" if n else "-"
            L.append(f"| {k} | {n} | {pct(g('desc'), g('rdesc'))} | {pct(g('close'), g('rclose'))} | {pct(g('cellhit'), g('rcell'))} | {pct(g('nexthit'), g('rnext'))} |")
    L += ["", "## Per run", "",
          "| run | nodes | keeps | fires | v6 routes in ledger? | mix routes | final depth | sub=final | " + " | ".join(f"{k} cells / topshare" for k in KEYS) + " | K1 stab diff-cell | K1 lineage any/latest | K1 stall hit (desc/close of n) | K1 random |",
          "|" + "---|" * (8 + len(KEYS) + 4)]
    for name, r in res.items():
        m = r["_meta"]; k1 = r["K1"]; st = k1["stall"]; n = st["with_later"]
        sp = k1["stab_pairs"]
        L.append(f"| {short(name)} | {m['nodes']} | {m['keeps']} | {m['fires']} | {r['K0']['keyed']} | {m['routes']} | {m['final_depth']} | {m['sub_is_final']} | "
                 + " | ".join(f"{r[k]['cells']} / {r[k]['top_share'] if r[k]['top_share'] is None else round(r[k]['top_share'], 2)}" for k in KEYS)
                 + f" | {k1['stab_total']}/{sp} | {k1['lineage_any']:.2f}/{k1['lineage_latest']:.2f} | {st['desc']}/{st['close']} of {n} | {st['rdesc']:.1f}/{st['rclose']:.1f} |")
    sub = [(short(n), r["K1"]["sub_in_archive"], r["_meta"]["sub_is_final"]) for n, r in res.items() if r["K1"]["sub_in_archive"] is not None]
    L += ["", f"Submission source node (run's own submission.json candidate) is in the K1 archive at the end in {sum(1 for s in sub if s[1])}/{len(sub)} runs; "
          f"it equals the proxy-final-best in {sum(1 for s in sub if s[2])}/{len(sub)}.", ""]
    open(os.path.join(HERE, "archive-v6.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
