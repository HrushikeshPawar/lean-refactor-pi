"""Replay candidate route signatures on stored v6 runs. Read-only; no Lean, no models.

Signatures (all computed from proof text or already-stored compile results):
  skel  (a) top-level tactic heads, arguments dropped, repeats collapsed; similarity = sequence ratio
  steps (c) normalized step lines (hypothesis names alpha-renamed); similarity = Jaccard of hash sets
  goal  (b') normalized goals/error classes from the stored compile result (per-step goals are NOT stored)
  v6        the ledger's own route events (kernel/text fingerprint, hard 0.5 exemplar rule)
Clustering: arrival order; a node's similarity to a route is the MAX over the route's members (single link),
so a chain of small edits stays together. Margin rule: join the best route if sim >= LO_JOIN; open a new route
only below LO_NEW. In the grey band [LO_NEW, HI) join the best route only when it also beats the runner-up by
MARGIN or is the parent's route; otherwise join the parent's route (sticky), else the best.
Usage: python3 route_replay.py [runs/pi-budget] > out.json
"""
import difflib, hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from arena.routes import proof_body, _heads  # noqa: E402
from arena import goalstate  # noqa: E402

HI, LO_NEW, MARGIN = 0.60, 0.35, 0.10
_NAME = re.compile(r"\b(h[A-Za-z0-9_'₀-₉]*|this|H[A-Za-z0-9_'₀-₉]*|ih[A-Za-z0-9_']*)\b")


def skeleton(proof):
    return _heads(proof_body(proof))


def steps(proof):
    out = set()
    for line in proof_body(proof).splitlines():
        s = " ".join(line.split())
        if not s or s in ("by",):
            continue
        s = _NAME.sub("_h", s)
        out.add(hashlib.sha1(s.encode()).hexdigest()[:10])
    return out


def sim_skel(a, b):
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def sim_set(a, b):
    u = a | b
    return 1.0 if not u else len(a & b) / len(u)


def cluster(nodes, sigs, sim, parents, hysteresis=True):
    """nodes: ids in arrival order. Returns {id: route index}."""
    route, members = {}, []
    for n in nodes:
        scores = [max(sim(sigs[n], sigs[m]) for m in ms) for ms in members]
        if not scores:
            route[n] = 0; members.append([n]); continue
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        best = order[0]; top = scores[best]; second = scores[order[1]] if len(order) > 1 else 0.0
        if not hysteresis:
            pick = best if top >= 0.5 else None
        elif top >= HI:
            pick = best
        elif top < LO_NEW:
            pick = None
        else:  # grey band
            pr = route.get(parents.get(n))
            pick = best if (top - second >= MARGIN or pr == best or pr is None) else pr
        if pick is None:
            pick = len(members); members.append([])
        members[pick].append(n); route[n] = pick
    return route


def load(run):
    led = [json.loads(l) for l in (run / "ledger.jsonl").read_text().splitlines() if l.strip()]
    proofs = {p.stem: p.read_text() for p in (run / "proofs").glob("*.lean")}
    order = {}   # first-seen time
    parents, results, closedhb = {}, {}, {}
    for e in led:
        k = e["kind"]
        if k == "candidate":
            order.setdefault(e["candidate_id"], e["ts"]); parents[e["candidate_id"]] = (e.get("parents") or [None])[0]
        elif k == "probe":
            order.setdefault(e["proof_id"], e["ts"]); parents[e["proof_id"]] = e.get("parent"); results[e["proof_id"]] = e["result"]
        elif k == "evaluation":
            order.setdefault(e["candidate_id"], e["ts"]); results[e["candidate_id"]] = e["result"]
            if goalstate.closed(e["result"]):
                hb = e["result"].get("heartbeat") or 10**9
                closedhb[e["candidate_id"]] = min(hb, closedhb.get(e["candidate_id"], 10**9))
    v6 = {e["proof_id"]: e for e in led if e["kind"] == "route"}
    ids = sorted((i for i in proofs if i in order), key=lambda i: order[i])
    return ids, proofs, parents, results, closedhb, v6


def goal_sig(result):
    g, c = goalstate.parts(result)
    return {"CLOSED"} if goalstate.closed(result) else set(g) | {"E:" + x for x in c}


def line_diff(a, b):
    la, lb = proof_body(a).splitlines(), proof_body(b).splitlines()
    if abs(len(la) - len(lb)) > 3:
        return 99
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for t, i1, i2, j1, j2 in sm.get_opcodes() if t != "equal")


def analyse(run):
    ids, proofs, parents, results, hb, v6 = load(run)
    if len(ids) < 3:
        return None
    sig = {"skel": ({i: skeleton(proofs[i]) for i in ids}, sim_skel),
           "steps": ({i: steps(proofs[i]) for i in ids}, sim_set),
           "mix": ({i: (skeleton(proofs[i]), steps(proofs[i])) for i in ids}, lambda a, b: 0.5 * sim_skel(a[0], b[0]) + 0.5 * sim_set(a[1], b[1])),
           "goal": ({i: goal_sig(results[i]) if i in results else set() for i in ids}, sim_set)}
    assign = {}
    for name, (s, f) in sig.items():
        assign[name] = cluster(ids, s, f, parents)
        assign[name + "_hard"] = cluster(ids, s, f, parents, hysteresis=False)
    vids = [i for i in ids if i in v6]
    names = sorted({v6[i]["route"] for i in vids})
    assign["v6"] = {i: v6[i]["route"] for i in vids}
    pairs = []
    cand = ids[:200]  # cap pair search for speed
    for x in range(len(cand)):
        for y in range(x + 1, len(cand)):
            if line_diff(proofs[cand[x]], proofs[cand[y]]) <= 3:
                pairs.append((cand[x], cand[y]))
    out = {"nodes": len(ids), "pairs_le3": len(pairs), "v6_events": len(vids)}
    # best node per v6 route (closed, lowest heartbeats)
    best = {}
    for i in vids:
        if i in hb and (v6[i]["route"] not in best or hb[i] < hb[best[v6[i]["route"]]]):
            best[v6[i]["route"]] = i
    bl = list(best.values())
    for name, a in assign.items():
        sub = [(x, y) for x, y in pairs if x in a and y in a]
        stab = (sum(a[x] == a[y] for x, y in sub) / len(sub)) if sub else None
        sep = [(a[x] != a[y]) for i, x in enumerate(bl) if x in a for y in bl[i + 1:] if y in a]
        out[name] = {"routes": len(set(a.values())), "stability": None if stab is None else round(stab, 3),
                     "stab_pairs": len(sub), "separation": None if not sep else round(sum(sep) / len(sep), 3),
                     "sep_pairs": len(sep)}
    out["v6_credited"] = sum(1 for e in v6.values() if e.get("new") and e.get("source") == "kernel")
    out["v6_text_events"] = sum(1 for e in v6.values() if e.get("source") == "text")
    out["v6_best_routes"] = len(bl)
    return out


if __name__ == "__main__":
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs" / "pi-budget"
    res = {}
    for run in sorted(base.iterdir()):
        if run.is_dir() and re.match(r"v6(cov|ark2?|pilot)-", run.name) and (run / "ledger.jsonl").exists() and (run / "proofs").exists():
            r = analyse(run)
            if r:
                res[run.name] = r
    json.dump(res, sys.stdout, indent=1)
