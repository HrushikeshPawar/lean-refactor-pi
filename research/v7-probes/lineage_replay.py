#!/usr/bin/env python3
"""Offline lineage replay for v6 candidate graphs (read-only).

Replay 1: step-hash provenance vs recorded parents and difflib text-closest parents.
Replay 2: paper test of reasoning mentions of combines/forks against the next node's origins.
Usage: python3 lineage_replay.py   (prints a summary; writes lineage-v6.md beside this file)
"""
import bisect, collections, difflib, glob, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from graph_audit import ROOT, lines_of  # reuse graph_audit's line normaliser

PREFIXES = ("v6cov", "v6ark", "v6pilot")  # "v6ark" also matches v6ark2
MIN_NODES = 3
OUT_MD = os.path.join(HERE, "lineage-v6.md")
SENS_MIN_CHARS = 40  # sensitivity: ignore steps shorter than this (normalised) in replay 1
COMBINE = [
    re.compile(r"#(\d+)\s*\+\s*#(\d+)"),
    re.compile(r"(?:combin|merg|splic|hybrid|togeth)\w*[^.\n]{0,80}?#(\d+)[^.\n]{0,60}?#(\d+)", re.I),
    re.compile(r"#(\d+)\s*(?:and|with)\s*#(\d+)[^.\n]{0,40}?(?:combin|merg|togeth)", re.I),
]
FORK = re.compile(r"\b(?:based on|variants? of|from|back to|fork(?:ing)? from|start(?:ing)? from|"
                  r"build(?:ing)? (?:on|from)|modify(?:ing)?)\s+(?:the\s+)?(?:(?:draft|candidate|node)\s+)?#(\d+)", re.I)


def load(d):
    nodes, order, ev = {}, [], []
    for e in (json.loads(l) for l in open(d + "/ledger.jsonl") if l.strip()):
        k = e.get("kind")
        if k == "candidate":
            i = e["candidate_id"]
            if i not in nodes:
                nodes[i] = dict(parents=list(e.get("parents") or []), ts=e["ts"], kind="cand"); order.append(i)
        elif k == "probe":
            i = e["proof_id"]
            if i not in nodes:
                nodes[i] = dict(parents=[e["parent"]] if e.get("parent") else [], ts=e["ts"], kind="probe"); order.append(i)
        elif k == "evaluation":
            ev.append(e)
    return nodes, order, ev


def read_text(d, i):
    p = f"{d}/proofs/{i}.lean"
    return open(p).read() if os.path.exists(p) else ""


def body_lines(text):
    """Tactic block = lines after the first `:= by` (statement-level `let x := ...` lines are skipped)."""
    lines = text.splitlines()
    for pat in (r":=\s*by\s*$", r":=\s*by\b"):
        for idx, l in enumerate(lines):
            m = re.search(pat, l)
            if m:
                rest = l[m.end():].strip()
                return ([rest] if rest else []) + lines[idx + 1:]
    return []


def steps_of(text):
    """Top-level steps: lines at the block's minimum indentation start a step; deeper lines join the step above."""
    body = [l for l in body_lines(text) if l.strip() and l.strip() not in ("by", "--") and not l.strip().startswith("--")]
    if not body:
        return []
    ind = lambda l: len(l) - len(l.lstrip())
    base = min(ind(l) for l in body)
    steps = []
    for l in body:
        if not steps or ind(l) <= base:
            steps.append([l])
        else:
            steps[-1].append(l)
    return ["\n".join(s) for s in steps]


def step_hash(step):
    return hashlib.sha256(" ".join(step.split()).encode()).hexdigest()[:24]  # strip + collapse whitespace


def replay1(d, nodes, order, min_chars=0):
    text = {i: read_text(d, i) for i in order}
    hs = {i: [step_hash(s) for s in steps_of(text[i]) if len(" ".join(s.split())) >= min_chars] for i in order}
    origin = {}
    for i in order:  # ledger order: first node containing a hash is its origin
        for x in hs[i]:
            origin.setdefault(x, i)
    pos = {i: n for n, i in enumerate(order)}
    info = {}
    for i in order:
        orig = [origin[x] for x in hs[i]]
        cnt = collections.Counter(o for o in orig if o != i)  # non-new steps
        mp = max(cnt, key=lambda o: (cnt[o], pos[o]), default=None)  # most steps, tie -> most recent
        info[i] = dict(origins=set(cnt), new=len(orig) - sum(cnt.values()), nsteps=len(orig), measured=mp)
    return text, info


def text_parents(order, nodes, text):
    """graph_audit's difflib rule, verbatim: top-scoring earlier nodes within 0.02; the recorded parent wins if among them.
    Also returns the pure argmax (ties to the most recent) for comparison."""
    L = {i: lines_of(text[i]) for i in order}
    tp, am = {}, {}
    for n, i in enumerate(order[1:], 1):
        sc = [(difflib.SequenceMatcher(None, L[i], L[x], autojunk=False).ratio(), x) for x in order[:n] if L[x]]
        if not sc:
            continue
        m = max(s for s, _ in sc)
        tops = [x for s, x in sc if s >= m - 0.02]
        rec = nodes[i]["parents"][0] if nodes[i]["parents"] else None
        tp[i] = rec if rec in tops else tops[-1]
        am[i] = [x for s, x in sc if s == m][-1]
    return tp, am


def depth(i, par):
    n = 0
    while par.get(i) and n < 500:
        i = par[i]; n += 1
    return n


def best_node(ev):  # graph_audit's rule: best local_proxy among compat-passing evaluations
    best, bp = None, -1
    for e in ev:
        r = e.get("result", {}); p = r.get("local_proxy"); c = r.get("compat", {})
        ok = next(iter(c.values()), {}).get("passed") if c else False
        if ok and p is not None and p > bp:
            bp, best = p, e["candidate_id"]
    return best


def labels(nodes, order):
    lab, c, p = {}, 0, 0
    for i in order:
        if nodes[i]["kind"] == "cand":
            c += 1; lab[i] = f"#{c}"
        else:
            p += 1; lab[i] = f"q{p}"  # ledger-order probe index, not necessarily the arena's pN
    return lab


def mentions(text):
    out, spans = [], []
    snip = lambda m: text[max(0, m.start() - 70):m.end() + 30].replace("\n", " ")
    for rx in COMBINE:
        for m in rx.finditer(text):
            a, b = int(m.group(1)), int(m.group(2))
            if a != b:
                out.append(("combine", tuple(sorted((a, b))), snip(m))); spans.append(m.span())
    for m in FORK.finditer(text):
        if not any(s <= m.start() and m.end() <= e for s, e in spans):
            out.append(("fork", (int(m.group(1)),), snip(m)))
    return out


def paper(run, nodes, order, info, lab):
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
    rows, st, turn_start = [], collections.Counter(), None
    for k, j in enumerate(ev):
        if j.get("type") == "turn_start":
            turn_start = k; continue
        if j.get("type") != "turn_end" or turn_start is None:
            continue
        parts = j.get("message", {}).get("content", [])
        text = "\n".join((p.get("thinking") or p.get("text") or "") for p in parts
                         if isinstance(p, dict) and p.get("type") in ("thinking", "text"))
        found = mentions(text)
        if not found:
            continue
        # mention time = start of the turn's first tool call (reasoning precedes its calls); next node = first ledger node at/after it
        q = bisect.bisect_right(tool_idx, turn_start)
        kn = bisect.bisect_left(ts_list, tool_ts[q]) if q < len(tool_idx) else len(order)
        seen = set()
        for kind, ids, snip in found:
            if (kind, ids) in seen:
                continue
            seen.add((kind, ids)); st["mentions"] += 1; st["mentions_" + kind] += 1
            tgt = [cands[N - 1] if 1 <= N <= len(cands) and kn < len(order) and pos[cands[N - 1]] < kn else None for N in ids]
            if kn >= len(order) or None in tgt:
                st["unmapped"] += 1; continue
            node = order[kn]
            s_ok = all(t in info[node]["origins"] for t in tgt)
            r_ok = all(t in nodes[node]["parents"] for t in tgt)
            st["mapped"] += 1; st["mapped_" + kind] += 1; st["step_ok"] += s_ok; st["rec_ok"] += r_ok
            st["step_ok_" + kind] += s_ok
            n_c = sum(pos[c] < kn for c in cands)  # base rate: share of earlier candidates that are origins of the next node
            if n_c:
                st["base_sum"] += sum(nodes[o]["kind"] == "cand" for o in info[node]["origins"]) / n_c; st["base_n"] += 1
            st["rec_ok_" + kind] += r_ok
            rows.append(dict(kind=kind, mention=",".join(f"#{N}" for N in ids), turn=k, node=lab[node],
                             origins=",".join(sorted(lab[o] for o in info[node]["origins"])) or "-",
                             recorded=",".join(lab[p] for p in nodes[node]["parents"]) or "-",
                             step_ok=s_ok, rec_ok=r_ok, snip=snip.replace("|", "/")))
    return rows, st


def analyse(run, min_chars=0):
    nodes, order, ev = load(run)
    text, info = replay1(run, nodes, order, min_chars)
    tp, am = text_parents(order, nodes, text)
    rec = {i: (nodes[i]["parents"][0] if nodes[i]["parents"] else None) for i in order}
    mp = {i: info[i]["measured"] for i in order}
    nonref = [i for i in order[1:] if info[i]["nsteps"] > 0]
    best = best_node(ev)
    lab = labels(nodes, order)
    rows, st = paper(run, nodes, order, info, lab)
    r1 = dict(
        run=os.path.basename(run), nodes=len(order),
        merge=sum(len(info[i]["origins"]) >= 2 for i in order),
        ag_rec=(sum(mp[i] == rec[i] for i in order if rec[i] and mp[i]), sum(1 for i in order if rec[i] and mp[i])),
        ag_tp=(sum(mp[i] == tp[i] for i in tp if mp[i]), sum(1 for i in tp if mp[i])),
        ag_am=(sum(mp[i] == am[i] for i in am if mp[i]), sum(1 for i in am if mp[i])),
        newroot=(sum(not info[i]["origins"] for i in nonref), len(nonref)),
        empty=sum(info[i]["nsteps"] == 0 for i in order),
        depth=(depth(best, rec), depth(best, tp), depth(best, mp)) if best else (None, None, None),
    )
    return r1, rows, st


def short(name):
    for a, b in (("-deepseek-v4.1-flash-r1", "-DS"), ("-gpt-6-luna-r1", "-Luna"), ("-qwen3.8-flash-r1", "-Qwen"), ("-r1", "")):
        name = name.replace(a, b)
    return name


def pct(a, b):
    return "n/a" if not b else f"{100 * a / b:.1f}%"


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    R1, SENS, ROWS, ST = [], [], [], collections.Counter()
    for d in sorted(glob.glob(ROOT + "/v6*")):
        b = os.path.basename(d)
        if not b.startswith(PREFIXES) or not all(os.path.exists(f"{d}/{f}") for f in ("ledger.jsonl", "events.jsonl")):
            continue
        if sum(1 for l in open(d + "/ledger.jsonl") if '"kind":"candidate"' in l or '"kind":"probe"' in l) < MIN_NODES:
            print("skip (fewer than 3 nodes)", b); continue
        r1, rows, st = analyse(d)
        R1.append(r1); ROWS += [dict(r, run=short(b)) for r in rows]; ST.update(st)
        SENS.append(analyse(d, SENS_MIN_CHARS)[0])
        print("done", short(b), r1["nodes"], flush=True)
    t1 = []
    for r in R1:
        t1.append([short(r["run"]), r["nodes"], pct(r["merge"], r["nodes"]), f'{r["ag_rec"][0]}/{r["ag_rec"][1]}',
                   f'{r["ag_tp"][0]}/{r["ag_tp"][1]}', f'{r["ag_am"][0]}/{r["ag_am"][1]}',
                   "/".join("-" if x is None else str(x) for x in r["depth"]), pct(*r["newroot"])])
    tot = lambda k: (sum(r[k][0] for r in R1), sum(r[k][1] for r in R1))
    n_all = sum(r["nodes"] for r in R1)
    t1.append(["TOTAL", n_all, pct(sum(r["merge"] for r in R1), n_all), *[f"{a}/{b}" for a, b in (tot("ag_rec"), tot("ag_tp"), tot("ag_am"))],
               "", pct(*tot("newroot"))])
    h1 = ["run", "nodes", "% merges (>=2 origins)", "agree recorded", "agree text (graph_audit)", "agree text (argmax)",
          "best depth rec/text/prov", "% new roots"]
    p_rows = [[k, ST[f"mentions_{k}"] if f"mentions_{k}" in ST else 0, ST[f"mapped_{k}"], pct(ST[f"step_ok_{k}"], ST[f"mapped_{k}"]),
               pct(ST[f"rec_ok_{k}"], ST[f"mapped_{k}"])] for k in ("combine", "fork")]
    p_rows.append(["ALL", ST["mentions"], ST["mapped"], pct(ST["step_ok"], ST["mapped"]), pct(ST["rec_ok"], ST["mapped"])])
    base = f'{100 * ST["base_sum"] / ST["base_n"]:.1f}%' if ST["base_n"] else "n/a"
    ts = lambda rs: (sum(r["merge"] for r in rs), sum(r["nodes"] for r in rs),
                     sum(r["ag_rec"][0] for r in rs), sum(r["ag_rec"][1] for r in rs),
                     sum(r["ag_tp"][0] for r in rs), sum(r["ag_tp"][1] for r in rs),
                     sum(r["newroot"][0] for r in rs), sum(r["newroot"][1] for r in rs))
    m0, m1 = ts(R1), ts(SENS)
    t3 = [[f"min_chars={c}", f"{pct(m[0], m[1])}", f"{m[2]}/{m[3]}", f"{m[4]}/{m[5]}", pct(m[6], m[7])]
          for c, m in ((0, m0), (SENS_MIN_CHARS, m1))]
    h3 = ["setting", "% merges", "agree recorded", "agree text (graph_audit)", "% new roots"]
    h2 = ["kind", "mentions", "mapped to a next node", "% step origins confirm", "% recorded parent confirms"]
    ex_yes = [r for r in ROWS if r["step_ok"]][:5]
    ex_no = [r for r in ROWS if not r["step_ok"]][:5]
    hx = ["run", "events line", "kind", "mention", "next node", "step origins", "recorded parents", "step ok", "rec ok", "context"]
    ex = lambda rs: [[r["run"], r["turn"], r["kind"], r["mention"], r["node"], r["origins"], r["recorded"],
                      r["step_ok"], r["rec_ok"], r["snip"][:160]] for r in rs]
    print(table(h1, t1)); print(); print(table(h3, t3)); print(); print(table(h2, p_rows))
    md = f"""# Lineage replay on v6 runs (lineage-v6)

Generated by `lineage_replay.py` (read-only; reads `runs/pi-budget/v6*/ledger.jsonl`, `proofs/*.lean`, `events.jsonl`).
Runs: {len(R1)} with at least 3 nodes, {n_all} nodes in total.

## Replay 1: step-hash provenance

{table(h1, t1)}

Definitions: nodes are candidate and probe ledger events in ledger order (as in graph_audit). A step is a top-level
tactic line group at the block's minimum indentation (blank, `by`-only and comment lines dropped). Step hash = SHA-256 of the
whitespace-normalised step text. Origin = earliest node containing that hash. Measured parent = origin contributing most non-new
steps (tie: most recent). "% merges" uses all nodes. "% new roots" uses non-reference nodes that have at least one step.
Empty proof files: {sum(r["empty"] for r in R1)} nodes with no steps (counted in neither denominator for new roots, counted as nodes).
Recorded parent = first entry of `parents` (or the probe's `parent`), as in graph_audit.
"agree text (graph_audit)" uses graph_audit's rule verbatim, which takes the recorded parent whenever it lies within 0.02 of the best
difflib ratio, so it is biased toward agreement with the recorded parent. "agree text (argmax)" is the pure best-ratio node (ties: most recent).
Best node = graph_audit's rule (highest local_proxy among compat-passing evaluations). Depth = parent hops to the reference.

Sensitivity (steps under {SENS_MIN_CHARS} normalised characters ignored; generic lines such as `ring` or `intro a` otherwise match across unrelated nodes):

{table(h3, t3)}

## Replay 2: paper test

Events line = line index in events.jsonl of the turn_end event. Mention = combine (`#A + #B`, `combine/merge ... #A ... #B`, `#A and #B` near a combine word) or fork (`based on|variants of|from|back to|
fork from|start from|build on|modify #N`) in a turn's thinking or text. `#N` maps to the N-th candidate node in ledger order
(verified on the SKI run: the best node reported as "#30" is the 30th candidate event). `qN` probes and `pN` ids are not mapped.
Time mapping: the mention is timed at the first tool call of its turn (reasoning precedes the calls it leads to). The next node is the
first ledger node at or after that time, so a node created by the same turn's tool calls counts as "next". A mention is unmapped if no
node follows it or an id does not exist before that node.
Confirmation: step test passes if every mentioned id is in the next node's non-new step origins; recorded test passes if every
mentioned id is in its recorded parents.

{table(h2, p_rows)}

Base rate for the step test: on average {base} of the earlier candidates are origins of the mapped next node, so an unrelated
mention would also pass about that often. Recorded-parent rows are the stricter check.

### Examples: step origins confirm (first 5)

{table(hx, ex(ex_yes))}

### Examples: step origins do not confirm (first 5)

{table(hx, ex(ex_no))}

## Caveats

- Step-provenance origins are exact-match only; a reworded or re-indented step with the same tokens counts as new, which biases toward new roots and fewer merges.
- Sub-step edits inside a step are invisible, so an origin match means the whole step text was reused.
- Replay 2 ids: `#N` numbering assumes the arena numbers candidates by ledger order. It is checked on one run only.
- Text-closest parents are quadratic in node count, and graph_audit's tie rule favours the recorded parent (see above).
- The fork regex also catches profile or cost references such as "from #22's profile", which are not forks. Those rows are kept and count against the fork numbers.
- The paper test covers only `#N` mentions. Probe mentions (`pN`) and "back to" mentions that name no id are not counted.
"""
    open(OUT_MD, "w").write(md)
    print("wrote", OUT_MD)


if __name__ == "__main__":
    main()
