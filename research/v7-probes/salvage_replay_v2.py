#!/usr/bin/env python3
"""Salvage replay v2 over v1's 37-draft sample (analysis only; repo files are read-only).

python3 -I salvage_replay_v2.py          run (sequential cold Lean compiles)
python3 -I salvage_replay_v2.py --plan   check that v1's pool is reproduced, no Lean

Per draft, combined order S2 -> S3 -> S4, at most 6 compiles (1 + 5 replacement rounds):
  S2 finer: an error in the body of a nested step (or on a leaf tactic line) -> sorry that
     innermost step; a block header is kept when the step opens a block and the error is not in it.
  S3 header-aware: an error on a have/obtain/let line with a type -> `<head> := sorry` (the next
     compile checks T: if the error is still on that line, T did not elaborate). Without a type, or
     when the error stays on the written-sorry line, drop the step and sorry its parent block.
     Other header kinds (show, induction, cases, rcases, calc, ...) fall through to S4.
  S4 escalate: only when S2/S3 change nothing -> sorry the parent block of each erroring step.
     A top-level step has no block above it, so its own step is sorried. Sorrying every top-level
     step is a failure.
Attribution: a salvaged draft is credited to the strategies of its final replacement round
(final) and to any round of its chain (chain).

Reuses v1's pool (salvage-results.json draft list, text via load_drafts) and v1's compile_text.
Writes salvage-results-v2.json and salvage-v6-v2.md into this directory.
"""
import argparse
import difflib
import json
import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import salvage_replay as v1  # noqa: E402  (puts the repo root on sys.path, sets ARENA_LEAN_TIMEOUT)

MAX_COMPILES = 6
SMALL_CHARS = 300
BUCKETS = v1.BUCKETS
OPENER = v1.OPENER
SORRY_RE = re.compile(r"\bsorry\b")
HEAD_RE = re.compile(r"^(have|obtain|let)\b")
TYPE_RE = re.compile(r"^\s*(?:have|obtain|let)\b[^:]*:(.*):=\s*sorry\s*$")


def indent(s):
    return len(s) - len(s.lstrip())


class Node:
    def __init__(self, s, e, parent):
        self.s, self.e, self.parent, self.kids = s, e, parent, []


def hdr_index(lines):
    return next((i for i, l in enumerate(lines) if l.rstrip().endswith(":= by")), None)


def build(lines, lo, hi, parent):
    idx = [i for i in range(lo, hi) if lines[i].strip()]
    if not idx:
        return []
    base = min(indent(lines[i]) for i in idx)
    starts = [i for i in idx if indent(lines[i]) == base and not lines[i].lstrip().startswith("--")]
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else hi
        n = Node(s, e, parent)
        n.kids = build(lines, s + 1, e, n)
        out.append(n)
    return out


def parse(lines):
    """Top-level step tree of a proof, or None when there is no `:= by` header or no steps."""
    hdr = hdr_index(lines)
    if hdr is None:
        return None
    roots = build(lines, hdr + 1, len(lines), None)
    return roots or None


def hdr_end(n):
    return n.kids[0].s if n.kids else n.e


def deepest(nodes, i):
    for n in nodes:
        if n.s <= i < n.e:
            return deepest(n.kids, i) or n
    return None


def render(lines, nodes, lo, hi, act, errs):
    out, p = [], lo
    for n in nodes:
        out += lines[p:n.s]
        out += render_node(lines, n, act, errs)
        p = n.e
    return out + lines[p:hi]


def render_node(lines, n, act, errs):
    key = (n.s, n.e)
    if key in act["hdr"]:
        return [act["hdr"][key]]
    if key in act["sorry"]:
        first = lines[n.s]
        opens = bool(OPENER.search(first.rstrip())) or first.strip() == "·"
        keep = bool(n.kids) and opens and not any(n.s <= i < hdr_end(n) for i in errs)
        if keep:
            return [first, " " * indent(lines[n.kids[0].s]) + "sorry"]
        return [" " * indent(first) + "sorry"]
    return [lines[n.s]] + render(lines, n.kids, n.s + 1, n.e, act, errs)


def plan(lines, roots, errs):
    """One replacement round. Returns (new_lines, strategies used, reason). reason is set on failure."""
    mapped = []
    for i in sorted(errs):
        n = deepest(roots, i)
        if n is not None:
            mapped.append((i, n))
    if not mapped:
        return None, set(), "broken-outside-steps"
    act = {"sorry": set(), "hdr": {}}
    used = set()
    for i, n in mapped:
        raw = lines[n.s]
        head = raw.strip()
        joined = " ".join(x.strip() for x in lines[n.s:hdr_end(n)])  # the node's header, across its lines
        is_have = bool(HEAD_RE.match(head)) and ":=" in joined
        if n.kids and i >= hdr_end(n):
            act["sorry"].add((n.s, n.e))  # S2: innermost erroring body
            used.add("S2")
        elif not n.kids and not is_have:
            act["sorry"].add((n.s, n.e))  # S2: leaf tactic line
            used.add("S2")
        elif is_have:  # S3: header of a have/obtain/let
            used.add("S3")
            tgt = n.parent or n
            pre = joined[:joined.index(":=")]
            if not n.kids and joined.endswith(":= sorry"):
                act["sorry"].add((tgt.s, tgt.e))  # T did not elaborate: drop, sorry the parent
            elif ":" in pre:
                act["hdr"][(n.s, n.e)] = " " * indent(raw) + pre.rstrip() + " := sorry"  # T checked next compile
            else:
                act["sorry"].add((tgt.s, tgt.e))  # no type to check: drop, sorry the parent
    if used:
        new = render(lines, roots, 0, len(lines), act, errs)
        if new != lines:
            return new, used, None
    # S4: no progress from S2/S3, so sorry the parent block of each erroring step
    act4 = {"sorry": set(), "hdr": {}}
    for _, n in mapped:
        tgt = n.parent or n
        act4["sorry"].add((tgt.s, tgt.e))
    new4 = render(lines, roots, 0, len(lines), act4, errs)
    if new4 == lines:
        return None, used, "broken-no-progress"
    return new4, used | {"S4"}, None


def whole_sorry(text):
    lines = text.split("\n")
    roots = parse(lines)
    return roots is not None and all(not r.kids and lines[r.s].strip() == "sorry" for r in roots)


def hole_goals(orig, final):
    """One entry per changed region that holds a sorry: the stated type T for a `have/obtain ... : T := sorry`
    line, else the original text the region replaced (proxy: the goal is not extracted from Lean)."""
    sm = difflib.SequenceMatcher(None, orig, final, autojunk=False)
    goals = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        sor = [l for l in final[j1:j2] if SORRY_RE.search(l)]
        if not sor:
            continue
        m = TYPE_RE.match(sor[0])
        goals.append(m.group(1).strip() if m else "\n".join(orig[i1:i2]).strip())
    return goals


def kept_frac(orig, final):
    ho, hf = hdr_index(orig), hdr_index(final)
    a = [l for l in orig[ho + 1:] if l.strip()]
    b = [l for l in final[hf + 1:] if l.strip()]
    m = sum(bl.size for bl in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return m / len(a) if a else 0.0


def salvage2(row, text0, version, commit):
    orig = text0.split("\n")
    roots0 = parse(orig)
    if roots0 is None:
        return dict(status="unparseable", steps=0, compiles=0, lean_s=0.0, compile_secs=[], first_error=None,
                    rounds=[], holes=None, kept=None, chain=[], final=[], small=False, goal_lengths=[])
    text, rounds, secs_all, first, status = text0, [], [], None, None
    for rnd in range(MAX_COMPILES):
        info, secs, err = v1.compile_text(row, text, version, commit)
        secs_all.append(secs)
        if info is None:
            status = f"unavailable: {str(err)[:80]}"
            break
        if rnd == 0:
            first = info["first"]
        if info["clean"]:
            status = "salvaged" if rnd else "clean-as-is"
            break
        if rnd == MAX_COMPILES - 1:
            status = "broken-pass-limit"
            break
        if info["unlocated"] or not info["errlines"]:
            status = "broken-unlocated"
            break
        lines = text.split("\n")
        roots = parse(lines)
        if roots is None:
            status = "broken-unparseable"
            break
        errs = {pl - 1 for pl in info["errlines"]}
        new, used, reason = plan(lines, roots, errs)
        if reason:
            status = reason
            break
        if whole_sorry("\n".join(new)):
            status = "broken-whole-proof-sorried"
            break
        rounds.append(dict(round=rnd, errors=len(info["errlines"]), strategies=sorted(used), lean_s=round(secs, 2)))
        text = "\n".join(new)
    res = dict(status=status, steps=len(roots0), compiles=len(secs_all), lean_s=round(sum(secs_all), 2),
               compile_secs=[round(s, 2) for s in secs_all], first_error=first, rounds=rounds,
               holes=None, kept=None, chain=[], final=[], small=False, goal_lengths=[])
    if status == "salvaged":
        final = text.split("\n")
        goals = hole_goals(orig, final)
        res.update(
            holes=sum(len(SORRY_RE.findall(l)) for l in final),
            kept=kept_frac(orig, final),
            chain=sorted({s for r in rounds for s in r["strategies"]}),
            final=rounds[-1]["strategies"],
            small=bool(goals) and all(len(g) < SMALL_CHARS for g in goals),
            goal_lengths=[len(g) for g in goals],
            final_text=text,
        )
    return res


def med(xs):
    return st.median(xs) if xs else None


def fmt(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


def stat_row(label, sel, base):
    n, N = len(sel), len(base)
    cells = []
    for b, _, _ in BUCKETS:
        tot = sum(1 for r in base if r["bucket"] == b)
        k = sum(1 for r in sel if r["bucket"] == b)
        cells.append(f"{100 * k / tot:.0f} ({k}/{tot})" if tot else "-")
    holes = med([r["holes"] for r in sel])
    kept = med([100 * r["kept"] for r in sel])
    lean = med([r["lean_s"] for r in sel])
    return (f"| {label} | {100 * n / N:.0f} ({n}/{N}) | " + " | ".join(cells) +
            f" | {fmt(holes)} | {fmt(kept, 0)} | {fmt(lean)} |")


def write_outputs(results, pool_size, v1res, total_lean, compile_secs):
    (HERE / "salvage-results-v2.json").write_text(json.dumps(
        dict(pool_size=pool_size, lean_seconds=round(total_lean, 1), compiles=len(compile_secs), drafts=results),
        indent=1, ensure_ascii=False))
    salv = [r for r in results if r["status"] == "salvaged"]
    v1salv = [r for r in v1res if r["status"] == "salvaged"]
    L = ["# Salvage replay v2, v6 failed drafts", "",
         "Escalation per draft in the order S2 (innermost erroring body or leaf) -> S3 (have/obtain/let header: "
         "`:= sorry` with the type checked by the next compile, else drop and sorry the parent) -> S4 (on no progress, "
         "sorry the parent block). At most 6 compiles per draft (1 + 5 replacement rounds). Sorrying every top-level step "
         "is a failure. Same 37 drafts as v1 (`salvage-results.json`).", "",
         f"Pool reproduced: {pool_size}. Total Lean time {total_lean:.0f} s over {len(compile_secs)} cold compiles "
         f"(median {fmt(med(compile_secs), 1)} s per compile).", "",
         "## Salvage rate by strategy", "",
         "Chain = the draft's salvaging chain used this strategy in any round. Final = the strategy of the round "
         "that produced the clean compile. Holes = sorry sites in the final sketch. Kept = share of the original "
         "non-blank body lines kept verbatim (line-based). Lean s = median per draft (all compiles).", "",
         "| strategy | overall % (n/37) | 1-3 | 4-10 | 11-30 | >30 | median holes | median % kept | median Lean s |",
         "|---|---|---|---|---|---|---|---|---|",
         stat_row("S1 v1 baseline (not re-run)", v1salv, v1res)]
    for s in ("S2", "S3", "S4"):
        L.append(stat_row(f"{s} (chain)", [r for r in salv if s in r["chain"]], results))
    L.append(stat_row("**Combined S2→S4**", salv, results))
    L += ["", "Final-round attribution (count of salvaged drafts whose last round used the strategy): "
          + ", ".join(f"{s} {sum(1 for r in salv if s in r['final'])}" for s in ("S2", "S3", "S4")) + ".", "",
          "## Hole goals (SMALL = goal text under 300 chars)", ""]
    goal_lens = [g for r in salv for g in r["goal_lengths"]]
    all_small = sum(1 for r in salv if r["small"])
    small_holes = sum(1 for g in goal_lens if g < SMALL_CHARS)
    L += [f"- Salvaged sketches with every hole under 300 chars: {all_small}/{len(salv)} "
          f"({100 * all_small / len(salv):.0f}%)." if salv else "- No salvaged sketches.",
          f"- Holes under 300 chars: {small_holes}/{len(goal_lens)} ({100 * small_holes / len(goal_lens):.0f}%)."
          if goal_lens else "", "",
          "Goal text is a proxy: a `have/obtain : T := sorry` hole uses T; other holes use the original text they "
          "replaced, since Lean's goal state is not extracted.", "",
          "## Status counts", "", "| status | n |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in Counter(r["status"] for r in results).most_common()]
    L += ["", "## Per draft", "",
          "| run | theorem | bucket | change | status | rounds | chain | holes | % kept | Lean s | SMALL | first error |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        kept = "-" if r["kept"] is None else f"{100 * r['kept']:.0f}"
        small = "-" if r["status"] != "salvaged" else ("yes" if r["small"] else "no")
        first = r["first_error"] or [None, ""]
        msg = (f"L{first[0]}: {first[1]}" if first[0] else "-").replace("|", "/")
        chain = ",".join(r["chain"]) or "-"
        L.append(f"| {r['run']} | {r['theorem']} | {r['bucket']} | {r['change']} | {r['status']} | "
                 f"{len(r['rounds'])} | {chain} | {'-' if r['holes'] is None else r['holes']} | {kept} | "
                 f"{r['lean_s']} | {small} | {msg} |")
    (HERE / "salvage-v6-v2.md").write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()
    drafts, _refs, _skipped = v1.load_drafts()
    v1res = json.loads((HERE / "salvage-results.json").read_text())["drafts"]
    by = {(d["run"], d["pid"]): d for d in drafts}
    pool = [by[(r["run"], r["pid"])] for r in v1res if (r["run"], r["pid"]) in by]
    counts = {b: sum(d["bucket"] == b for d in pool) for b, _, _ in BUCKETS}
    print(f"v1 pool reproduced: {len(pool)} of {len(v1res)}; buckets {counts}", flush=True)
    if args.plan:
        return
    v1.check_mem()
    from arena import engine
    results, compile_secs, total = [], [], 0.0
    for d in pool:
        row = engine.problem(d["theorem"])
        res = salvage2(row, d["text"], d["version"], d["commit"])
        compile_secs += res["compile_secs"]
        total += res["lean_s"]
        results.append(dict(run=d["run"], pid=d["pid"], theorem=d["theorem"], change=d["change"],
                            bucket=d["bucket"], **res))
        print(f"{d['bucket']:>5} {d['theorem'][:40]:40} change={d['change']:3} -> {res['status']} "
              f"rounds={len(res['rounds'])} chain={res['chain']} holes={res['holes']} lean={res['lean_s']}s",
              flush=True)
        write_outputs(results, len(pool), v1res, total, compile_secs)
    write_outputs(results, len(pool), v1res, total, compile_secs)


if __name__ == "__main__":
    main()
