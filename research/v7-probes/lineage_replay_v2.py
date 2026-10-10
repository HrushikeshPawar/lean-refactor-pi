#!/usr/bin/env python3
"""Lineage replay v2 on v6 runs (read-only). Reuses lineage_replay.py parsing (load, steps_of, step_hash,
replay1, text_parents, depth, best_node).

Changes from v1:
  * weighted steps: weight = normalised length x IDF; generic (<15 chars or in >50% of nodes) = 0
  * measured parent = earlier node with max weighted overlap, ties to the most recent node
  * variant: difflib ratio on full text, pool = 20 most recent nodes + top-3 archive nodes
  * merge = a donor outside the parent's measured ancestry supplies >=25% of the node's non-generic weight,
    with at least one such step above the run's median step weight
  * paper test with cleaner regexes and the profile/cost/score/tokens/heartbeat exclusion
Usage: python3 lineage_replay_v2.py   (prints tables; writes lineage-v6-v2.md beside this file)
"""
import bisect, collections, difflib, glob, json, math, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lineage_replay as v1
from graph_audit import ROOT

MIN_LEN, MAX_DF, MERGE_FRAC, RECENT, ARCHIVE = 15, 0.5, 0.25, 20, 3
OUT_MD = os.path.join(HERE, "lineage-v6-v2.md")
EXCL = re.compile(r"profile|cost|score|tokens|heartbeat", re.I)
COMB = [
    re.compile(r"#(\d+)\s*\+\s*#(\d+)"),
    re.compile(r"\b(?:combin|merg|splic|hybrid)\w*\s+(?:(?:the|a)\s+)?(?:(?:draft|candidate|node|proof)\s+)?#(\d+)"
               r"\s*(?:,|and|with|\+|&|into|onto)\s*(?:the\s+)?(?:(?:draft|candidate|node|proof)\s+)?#(\d+)", re.I),
    re.compile(r"#(\d+)\s+(?:and|with)\s+#(\d+)[^.\n]{0,40}?\b(?:combin|merg|together)\w*", re.I),
]
FORK = re.compile(r"\b(?:based on|variants? of|fork(?:ed|ing)? from|start(?:ing)? from|build(?:ing)? (?:on|from)|"
                  r"modify(?:ing)?|back to|from)\s+(?:the\s+)?(?:(?:draft|candidate|node|proof)\s+)?#(\d+)\b", re.I)


def is_luna(d):
    return "-gpt-6-luna-r1" in os.path.basename(d)


def archive(ev, pos, k=ARCHIVE):
    """Top-k compat-passing evaluations by local_proxy (ties: most recent)."""
    rows = []
    for e in ev:
        r = e.get("result", {}); p = r.get("local_proxy"); c = r.get("compat", {})
        ok = next(iter(c.values()), {}).get("passed") if c else False
        if ok and p is not None and e.get("candidate_id") in pos:
            rows.append((p, pos[e["candidate_id"]], e["candidate_id"]))
    rows.sort(reverse=True)
    out = []
    for _, _, cid in rows:
        if cid not in out:
            out.append(cid)
        if len(out) == k:
            break
    return out


def analyse(d):
    nodes, order, ev = v1.load(d)
    if len(order) < v1.MIN_NODES:
        return None
    text, info1 = v1.replay1(d, nodes, order)
    N = len(order)
    pos = {i: k for k, i in enumerate(order)}
    ref = order[0]
    # ---- step sets and weights
    S, nlen = {}, {}
    for i in order:
        hs = set()
        for s in v1.steps_of(text[i]):
            h = v1.step_hash(s); hs.add(h); nlen.setdefault(h, len(" ".join(s.split())))
        S[i] = hs
    df = collections.Counter(h for i in order for h in S[i])
    W = {h: (0.0 if nlen[h] < MIN_LEN or c / N > MAX_DF else nlen[h] * math.log(N / c)) for h, c in df.items()}
    nongen = [w for w in W.values() if w > 0]
    med = statistics.median(nongen) if nongen else float("inf")
    generic_share = (sum(W[h] == 0 for h in W) / len(W)) if W else 0.0
    # ---- v2 weighted measured parent, merge flag, ancestry
    m2, mg, anc, contrib, tot = {}, {}, {}, {}, {}
    for n, i in enumerate(order):
        mine = [h for h in S[i] if W[h] > 0]
        tot[i] = sum(W[h] for h in mine)
        sc = {x: sum(W[h] for h in mine if h in S[x]) for x in order[:n]}
        contrib[i] = {x for x, s in sc.items() if s > 0}
        best, bs = None, 0.0
        for x in order[:n]:  # ascending; ">=" lets the most recent node win ties
            if sc[x] > 0 and round(sc[x], 9) >= round(bs, 9):
                best, bs = x, sc[x]
        m2[i] = best
        anc[i] = ({best} | anc[best]) if best else set()
        mg[i] = False
        if best is not None and tot[i] > 0:
            A = [h for h in mine if h not in S[best]]
            donors = [x for x in order[:n] if x != best and x not in anc[best]]
            covered = {h for x in donors for h in A if h in S[x]}
            if covered:
                wc = sum(W[h] for h in covered)
                mg[i] = wc / tot[i] >= MERGE_FRAC and max(W[h] for h in covered) > med
    # ---- difflib variant: full text (non-blank stripped lines), 20 most recent + archive bests
    full = {i: [l.strip() for l in text[i].splitlines() if l.strip()] for i in order}
    arch = archive(ev, pos)
    d2 = {ref: None}
    for n, i in enumerate(order[1:], 1):
        if not full[i]:
            d2[i] = None; continue
        pool = set(order[max(0, n - RECENT):n]) | {a for a in arch if pos[a] < n}
        scs = [(difflib.SequenceMatcher(None, full[i], full[x], autojunk=False).ratio(), x)
               for x in sorted(pool, key=lambda x: pos[x]) if full[x]]
        if not scs:
            d2[i] = None; continue
        m = max(r for r, _ in scs)
        d2[i] = [x for r, x in scs if round(r, 9) == round(m, 9)][-1]
    # ---- comparators
    _, am = v1.text_parents(order, nodes, text)  # graph_audit text-closest argmax
    rec = {i: (nodes[i]["parents"][0] if nodes[i]["parents"] else None) for i in order}
    meth = {"v1 step-hash": {i: info1[i]["measured"] for i in order},
            "v2 weighted": m2, "v2 difflib-recent": d2,
            "graph_audit argmax": {i: am.get(i) for i in order}}
    body = [i for i in order[1:] if S[i]]  # non-reference nodes with at least one step
    best = v1.best_node(ev)
    return dict(
        d=d, run=v1.short(os.path.basename(d)), luna=is_luna(d), order=order, N=N, nodes=nodes, rec=rec,
        meth=meth, m2=m2, mg=mg, contrib=contrib, anc=anc, body=body, generic=generic_share,
        v1_merge=sum(len(info1[i]["origins"]) >= 2 for i in order),
        v2_merge=sum(mg[i] for i in order), v2_newroot=sum(m2[i] is None for i in body),
        prev_chain=sum(1 for i in order[1:] if rec[i] == order[pos[i] - 1]),
        scorable=sum(1 for i in order[1:] if rec[i] is not None),
        depth=(v1.depth(best, rec), v1.depth(best, m2), v1.depth(best, d2)) if best else (None, None, None),
    )


def mentions2(text):
    out, spans = [], []

    def near(a, b):
        return EXCL.search(text[max(0, a - 20):b + 20]) is not None

    for rx in COMB:
        for m in rx.finditer(text):
            a, b = int(m.group(1)), int(m.group(2))
            if a == b or near(*m.span(1)) or near(*m.span(2)):
                continue
            out.append(("combine", tuple(sorted((a, b))))); spans.append(m.span())
    for m in FORK.finditer(text):
        if any(s <= m.start() and m.end() <= e for s, e in spans) or near(*m.span(1)):
            continue
        out.append(("fork", (int(m.group(1)),)))
    return out


def paper2(R):
    run, nodes, order = R["d"], R["nodes"], R["order"]
    cands = [i for i in order if nodes[i]["kind"] == "cand"]
    pos = {i: k for k, i in enumerate(order)}
    ts_list = [nodes[i]["ts"] for i in order]
    ev = []
    for l in open(run + "/events.jsonl"):
        try:
            ev.append(json.loads(l))
        except ValueError:
            ev.append({})
    tool_idx = [k for k, j in enumerate(ev) if j.get("type") == "tool_execution_start"]
    tool_ts = [ev[k].get("ts", 0) for k in tool_idx]
    st, turn_start = collections.Counter(), None
    for k, j in enumerate(ev):
        if j.get("type") == "turn_start":
            turn_start = k; continue
        if j.get("type") != "turn_end" or turn_start is None:
            continue
        parts = j.get("message", {}).get("content", [])
        txt = "\n".join((p.get("thinking") or p.get("text") or "") for p in parts
                        if isinstance(p, dict) and p.get("type") in ("thinking", "text"))
        found = mentions2(txt)
        if not found:
            continue
        q = bisect.bisect_right(tool_idx, turn_start)
        kn = bisect.bisect_left(ts_list, tool_ts[q]) if q < len(tool_idx) else len(order)
        for kind, ids in set(found):
            st["mentions_" + kind] += 1
            tgt = [cands[M - 1] if 1 <= M <= len(cands) and kn < len(order) and pos[cands[M - 1]] < kn else None for M in ids]
            if kn >= len(order) or None in tgt:
                st["unmapped"] += 1; continue
            node = order[kn]
            n_c = sum(pos[c] < kn for c in cands)
            share = sum(1 for c in cands if pos[c] < kn and c in R["contrib"][node]) / n_c if n_c else 0.0
            st["mapped_" + kind] += 1
            if kind == "fork":
                st["fork_ok"] += R["m2"][node] == tgt[0]
                st["fork_contrib"] += tgt[0] in R["contrib"][node]
                st["fork_base"] += 1 / n_c if n_c else 0
                st["fork_base_n"] += 1
            else:
                st["comb_ok"] += bool(R["mg"][node] and all(t in R["contrib"][node] for t in tgt))
                st["comb_contrib"] += all(t in R["contrib"][node] for t in tgt)
                st["comb_base_share"] += share ** 2
                st["comb_base_n"] += 1
                st["comb_flagged"] += bool(R["mg"][node])
    return st


def agree(R_list, meth):
    ok = n = ab = 0
    for R in R_list:
        for i in R["order"][1:]:
            t = R["rec"][i]
            if t is None:
                continue
            n += 1
            p = R["meth"][meth][i]
            if p is None:
                ab += 1
            elif p == t:
                ok += 1
    return ok, n, ab


def pct(a, b):
    return "n/a" if not b else f"{100 * a / b:.1f}%"


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    runs = []
    for d in sorted(glob.glob(ROOT + "/v6*")):
        b = os.path.basename(d)
        if not b.startswith(v1.PREFIXES) or not all(os.path.exists(f"{d}/{f}") for f in ("ledger.jsonl", "events.jsonl")):
            continue
        R = analyse(d)
        if R is None:
            print("skip", b); continue
        runs.append(R); print("done", R["run"], R["N"], flush=True)
    # per-run table
    t1 = []
    for R in runs:
        nb = len(R["body"])
        t1.append([R["run"], R["N"], R["luna"] and "Luna" or "other", pct(R["v1_merge"], R["N"]), pct(R["v2_merge"], nb),
                   pct(R["v2_newroot"], nb), f"{100 * R['generic']:.1f}%", pct(R["prev_chain"], R["scorable"]),
                   "/".join("-" if x is None else str(x) for x in R["depth"])])
    tot = lambda f: sum(f(R) for R in runs)
    t1.append(["TOTAL", tot(lambda R: R["N"]), "", pct(tot(lambda R: R["v1_merge"]), tot(lambda R: R["N"])),
               pct(tot(lambda R: R["v2_merge"]), tot(lambda R: len(R["body"]))),
               pct(tot(lambda R: R["v2_newroot"]), tot(lambda R: len(R["body"]))), "", pct(tot(lambda R: R["prev_chain"]), tot(lambda R: R["scorable"])), ""])
    h1 = ["run", "nodes", "set", "v1 merge % (all nodes)", "v2 merge % (nodes with steps)", "v2 new-root %",
          "generic share of distinct steps", "recorded = previous node %", "best depth rec / v2w / v2d"]
    # agreement tables
    luna = [R for R in runs if R["luna"]]
    nonl = [R for R in runs if not R["luna"]]
    methods = ["v1 step-hash", "v2 weighted", "v2 difflib-recent", "graph_audit argmax"]
    fmt = lambda t: f"{t[0]}/{t[1]} ({pct(t[0], t[1])}), abstain {t[2]}"
    t2 = [[m, fmt(agree(runs, m)), fmt(agree(nonl, m)), fmt(agree(luna, m))] for m in methods]
    h2 = ["method", "all runs (vs recorded)", "non-Luna runs (vs recorded)", "Luna runs (vs named parent = ground truth)"]
    t2b = []
    for R in luna:
        row = [R["run"], R["scorable"]]
        row += [pct(*agree([R], m)[:2]) if agree([R], m)[1] else "n/a" for m in methods]
        t2b.append(row)
    h2b = ["Luna run", "named-parent nodes"] + methods
    # merge vs declared two-parent nodes (only signal available for merges)
    dec = [(R["mg"][i], len(R["nodes"][i]["parents"]) > 1) for R in runs for i in R["order"][1:]]
    dn = sum(1 for _, x in dec if x)
    decflag = sum(1 for f, x in dec if x and f)
    # paper test
    ST = collections.Counter()
    for R in runs:
        ST.update(paper2(R))
    mrate = tot(lambda R: R["v2_merge"]) / max(1, tot(lambda R: len(R["body"])))
    t3 = [["fork (parent named = #N)", ST["mentions_fork"], ST["mapped_fork"], pct(ST["fork_ok"], ST["mapped_fork"]),
           pct(ST["fork_contrib"], ST["mapped_fork"]), pct(ST["fork_base"], ST["fork_base_n"])],
          ["combine (merge flagged, both ids contribute)", ST["mentions_combine"], ST["mapped_combine"],
           pct(ST["comb_ok"], ST["mapped_combine"]), pct(ST["comb_contrib"], ST["mapped_combine"]),
           pct(mrate * ST["comb_base_share"], ST["comb_base_n"])]]
    h3 = ["kind", "mentions", "mapped", "v2 confirms (parent / merge)", "ids contribute to next node", "base rate"]
    # best-node depth
    dep_lines = [f"{R['run']}: rec {R['depth'][0]}, v2w {R['depth'][1]}, v2d {R['depth'][2]}" for R in runs if R["depth"][0] is not None]
    md = f"""# Lineage replay v2 on v6 runs (lineage-v6-v2)

Generated by `lineage_replay_v2.py` (read-only). Reuses `lineage_replay.py` parsing. Runs: {len(runs)}, nodes: {sum(R['N'] for R in runs)}.

## Method

- Step = top-level tactic group (as v1). Weight = normalised length (chars) x ln(N / df), N = nodes in run, df = nodes containing the step.
  Weight 0 (generic) if the normalised length is under {MIN_LEN} or df > {int(MAX_DF*100)}% of N.
- v2 weighted parent = earlier node with the largest sum of weights of the node's steps it also contains; ties go to the most recent node.
  A node with no shared non-generic step has no parent (new root).
- v2 difflib-recent = `SequenceMatcher` ratio over the full text (non-blank lines, whitespace-stripped), pool = last {RECENT} earlier nodes plus top-{ARCHIVE}
  compat-passing archive nodes by local_proxy that precede the node. Ties go to the most recent. Full text is compared at line level (character level was too slow).
- v2 merge = the measured parent is P. Donors are earlier nodes that are not P and not in P's measured ancestry. The merge flag requires that
  steps absent from P and present in donors carry >= {int(MERGE_FRAC*100)}% of the node's non-generic weight, and that at least one such step weighs more than the run's median non-generic step weight.
- Ground truth: Luna runs. Every probe and candidate in all 20 runs has an explicit `parent` field (checked), so the recorded field is not a
  harness default. Luna probes name a parent other than the current node in 31 of 52 probes (the other 21 name the current node), so the named field carries choice information. The Luna table scores against it.
- Paper test: `#N` mentions with the window exclusion (profile, cost, score, tokens, heartbeat within 20 characters of the id).

## Per-run summary

{table(h1, t1)}

## Agreement

Agreement is among non-reference nodes that have a recorded parent. "abstain" counts nodes where the method returned no parent.

{table(h2, t2)}

Per Luna run (named parent as truth):

{table(h2b, t2b)}

Declared two-parent nodes: {dn} nodes list two parents; the v2 merge flag fires on {decflag} of them.

## Paper test (v2 cleaned mentions)

{table(h3, t3)}

Base rate for the parent test is the mean of 1/(earlier candidates) across mapped fork mentions. For merges it is the v2 merge rate times the mean
squared share of earlier candidates that contribute to the next node (independence approximation).

## Best-node depth under the parent maps

{chr(10).join('- ' + x for x in dep_lines)}
"""
    open(OUT_MD, "w").write(md)
    print(table(h1, t1)); print(); print(table(h2, t2)); print(); print(table(h2b, t2b)); print()
    print(table(h3, t3)); print("\n".join(dep_lines)); print("wrote", OUT_MD)


if __name__ == "__main__":
    main()
