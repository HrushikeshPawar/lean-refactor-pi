#!/usr/bin/env python3
"""Salvage replay over failed v6 drafts (analysis only, read-only on the repo).

python3 -I salvage_replay.py          run the replay (sequential Lean compiles)
python3 -I salvage_replay.py --plan   list the failed-draft pool, no Lean

Compiles go through the harness's own path, arena.engine.compile_version, forced cold
(`lake env lean` per compile, no Lean session). Per draft: compile; map each error line to
its top-level step (steps start at the body's minimum indentation); replace each erroring step
with `sorry` (keep the leading line when the step opens a block and the error is in its body,
otherwise replace the whole step); recompile. At most 4 replacement rounds, so at most 5 compiles.

Writes salvage-results.json and salvage-v6.md into this directory.
"""
import argparse
import difflib
import json
import os
import random
import re
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
os.environ["ARENA_LEAN_TIMEOUT"] = "120"  # a compile over the 120 s gate is killed and treated as a skip

RUNS = ROOT / "runs" / "pi-budget"
MAX_ROUNDS = 4
GATE_S = 120
MIN_AVAIL_GB = 6.0
PER_BUCKET = 10
SEED = 20261010
BUCKETS = [("1-3", 1, 3), ("4-10", 4, 10), ("11-30", 11, 30), (">30", 31, 10**9)]
SORRY = re.compile(r"\b(sorry|admit)\b")
ERR = re.compile(r"^.*?:(\d+):\d+: error:? ?(.*)$", re.M)
OPENER = re.compile(r"(:= by|=>|\bby|\bwith|\bdo|\bthen|\belse)$")


def avail_gb():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024 / 1024
    return 0.0


def check_mem():
    if avail_gb() <= MIN_AVAIL_GB:
        raise SystemExit(f"stop: MemAvailable {avail_gb():.1f} GB <= {MIN_AVAIL_GB} GB")


def bucket_of(n):
    for name, lo, hi in BUCKETS:
        if lo <= n <= hi:
            return name
    return None


def changed_lines(a, b):
    la, lb = a.split("\n"), b.split("\n")
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")


def load_drafts():
    """Failed v6 probe drafts (compile errors on the run's primary version, no sorry in the text)."""
    drafts, refs, skipped = [], {}, {"no-text": 0, "has-sorry": 0, "no-change": 0, "unbucketed": 0}
    for d in sorted(RUNS.glob("v6*-r1")):
        ledger = d / "ledger.jsonl"
        if not ledger.exists():
            continue
        led = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
        init = next((e for e in led if e["kind"] == "init"), None)
        if init is None:
            continue
        version, commit, theorem = init["version"], init["commit"], init["theorem"]

        def text(pid, d=d):
            p = d / "proofs" / f"{pid}.lean"
            return p.read_text() if p.exists() else None

        ref_id = next((e["candidate_id"] for e in led if e["kind"] == "candidate" and e.get("origin") == "reference"), None)
        ref_text = text(ref_id) if ref_id else None
        if ref_text is None:
            continue
        refs[theorem] = dict(text=ref_text, version=version, commit=commit, run=d.name)
        nodes, failed, seen = [ref_text], [], set()
        for e in led:
            if e["kind"] != "probe" or e["proof_id"] in seen:
                continue
            seen.add(e["proof_id"])
            compat = ((e.get("result") or {}).get("compat")) or {}
            c = compat.get(version) or (next(iter(compat.values())) if compat else None)
            if not c:
                continue
            t = text(e["proof_id"])
            if t is None:
                skipped["no-text"] += 1
                continue
            errors = (c.get("diagnostic_counts") or {}).get("errors", 0)
            if c.get("passed") and errors == 0:
                nodes.append(t)
            elif errors > 0:
                failed.append((e["proof_id"], t))
        for pid, t in failed:
            if SORRY.search(t):
                skipped["has-sorry"] += 1
                continue
            change = min((changed_lines(n, t) for n in nodes if n != t), default=0)
            if change == 0:
                skipped["no-change"] += 1
                continue
            b = bucket_of(change)
            if b is None:
                skipped["unbucketed"] += 1
                continue
            drafts.append(dict(run=d.name, theorem=theorem, version=version, commit=commit, pid=pid,
                               text=t, change=change, bucket=b))
    return drafts, refs, skipped


def top_steps(lines):
    """(header_end, steps, base). steps are [start, end) line ranges; a step starts at a non-comment
    line at the body's minimum indentation. Returns None when the proof does not have that shape."""
    hdr = next((i for i, l in enumerate(lines) if l.rstrip().endswith(":= by")), None)
    if hdr is None:
        return None
    body = [i for i in range(hdr + 1, len(lines)) if lines[i].strip()]
    if not body:
        return None
    indent = lambda s: len(s) - len(s.lstrip())
    base = min(indent(lines[i]) for i in body)
    starts = []
    for i in body:
        if indent(lines[i]) < base:
            return None
        if indent(lines[i]) == base and not lines[i].lstrip().startswith("--"):
            starts.append(i)
    if not starts:
        return None
    steps = [(starts[k], starts[k + 1] if k + 1 < len(starts) else len(lines)) for k in range(len(starts))]
    steps[0] = (hdr + 1, steps[0][1])
    return hdr, steps, base


def rebuild(lines, steps, base, targets):
    out = list(lines[:steps[0][0]])
    for k, (s, e) in enumerate(steps):
        if k not in targets:
            out.extend(lines[s:e])
            continue
        first = lines[s]
        cont = [i for i in range(s + 1, e) if lines[i].strip()]
        opener = bool(OPENER.search(first.rstrip())) or first.strip() == "·"
        if opener and cont and s not in targets[k]:
            ind = len(lines[cont[0]]) - len(lines[cont[0]].lstrip())
            out += [first, " " * ind + "sorry"]
        else:
            out.append(" " * base + "sorry")
    return "\n".join(out)


def compile_text(row, text, version, commit):
    """One cold compile through the harness. Returns (info, seconds, error)."""
    from arena import engine

    check_mem()
    start_line = engine.candidate_file(row, text, version, commit)["start_line"]
    t0 = time.monotonic()
    with engine.force_cold():
        res = engine.compile_version(row, text, version, commit)
    secs = time.monotonic() - t0
    if "exit_code" not in res:
        return None, secs, str(res.get("error"))
    errs = [(int(m.group(1)) - start_line + 1, m.group(2)[:120]) for m in ERR.finditer(res["raw_output"])]
    info = dict(clean=res["exit_code"] == 0 and not errs, errlines=sorted({e[0] for e in errs}),
                first=errs[0] if errs else None, unlocated=res["exit_code"] != 0 and not errs)
    return info, secs, None


def salvage(row, text0, version, commit):
    text = text0
    parsed0 = top_steps(text.split("\n"))
    if parsed0 is None:
        return dict(status="unparseable", steps=0, holes=0, kept=None, rounds=[], lean_s=0.0, compiles=0)
    total = len(parsed0[1])
    replaced, rounds, lean_s, compiles, first, status = set(), [], 0.0, 0, None, None
    for rnd in range(MAX_ROUNDS + 1):
        info, secs, err = compile_text(row, text, version, commit)
        compiles += 1
        lean_s += secs
        if info is None:
            status = f"unavailable: {err[:80]}"
            break
        if rnd == 0:
            first = info["first"]
        if info["clean"]:
            status = "salvaged" if rnd > 0 else "clean-as-is"
            break
        if rnd == MAX_ROUNDS:
            status = "broken-pass-limit"
            break
        if info["unlocated"] or not info["errlines"]:
            status = "broken-unlocated"
            break
        lines = text.split("\n")
        parsed = top_steps(lines)
        if parsed is None:
            status = "broken-unparseable"
            break
        hdr, steps, base = parsed
        targets, unmapped = {}, 0
        for pl in info["errlines"]:
            idx = pl - 1
            k = next((k for k, (s, e) in enumerate(steps) if s <= idx < e), None)
            if k is None:
                unmapped += 1
                continue
            targets.setdefault(k, set()).add(idx)
        rounds.append(dict(round=rnd, errors=len(info["errlines"]), steps_hit=len(targets),
                           unmapped=unmapped, lean_s=round(secs, 2)))
        if not targets:
            status = "broken-outside-steps"
            break
        new_text = rebuild(lines, steps, base, targets)
        if new_text == text:
            status = "broken-no-progress"
            break
        replaced |= set(targets)
        text = new_text
    holes = len(replaced)
    return dict(status=status, steps=total, holes=holes, kept=(total - holes) / total,
                rounds=rounds, lean_s=round(lean_s, 2), compiles=compiles, first_error=first,
                final_text=text if status == "salvaged" else None)


def gate_rows(drafts, refs):
    """One cold compile of each theorem's reference proof; a row is usable only if it compiles within GATE_S."""
    from arena import engine

    gate = {}
    for theorem in sorted({d["theorem"] for d in drafts}):
        ref = refs[theorem]
        try:
            row = engine.problem(theorem)
        except ValueError:
            gate[theorem] = dict(ok=False, note="not in benchmark")
            continue
        info, secs, err = compile_text(row, ref["text"], ref["version"], ref["commit"])
        ok = info is not None and info["clean"] and secs <= GATE_S
        gate[theorem] = dict(ok=ok, seconds=round(secs, 2), note=err or ("clean" if ok else "not clean or over gate"))
        print(f"gate {theorem}: {gate[theorem]}", flush=True)
    return gate


def sample(pool):
    rng = random.Random(SEED)
    chosen = []
    for name, _, _ in BUCKETS:
        cands = [d for d in pool if d["bucket"] == name]
        rng.shuffle(cands)
        by_row = {}
        for d in cands:
            by_row.setdefault(d["theorem"], []).append(d)
        picked, rows = [], sorted(by_row)
        while len(picked) < PER_BUCKET and any(by_row.values()):
            for r in rows:
                if by_row[r] and len(picked) < PER_BUCKET:
                    picked.append(by_row[r].pop())
        chosen += picked
    return chosen


def summary_table(results):
    out = ["| change bucket (lines) | n | % salvaged | median holes (salvaged) | median % steps kept (salvaged) | median Lean s per salvage |",
           "|---|---|---|---|---|---|"]
    for name, _, _ in BUCKETS:
        g = [r for r in results if r["bucket"] == name]
        if not g:
            out.append(f"| {name} | 0 | - | - | - | - |")
            continue
        s = [r for r in g if r["status"] == "salvaged"]
        pct = 100 * len(s) / len(g)
        holes = f"{st.median([r['holes'] for r in s]):.1f}" if s else "-"
        kept = f"{st.median([100 * r['kept'] for r in s]):.0f}" if s else "-"
        secs = f"{st.median([r['lean_s'] for r in s]):.1f}" if s else "-"
        out.append(f"| {name} | {len(g)} | {pct:.0f} | {holes} | {kept} | {secs} |")
    return "\n".join(out)


def write_outputs(results, gate, skipped, pool_size, total_lean):
    (HERE / "salvage-results.json").write_text(json.dumps(
        dict(gate=gate, skipped=skipped, pool_size=pool_size, lean_seconds=round(total_lean, 1), drafts=results),
        indent=1, ensure_ascii=False))
    lines = ["# Salvage replay, v6 failed drafts", "",
             "Each failed draft is compiled through `arena.engine.compile_version` (cold `lake env lean`). "
             "Error lines map to top-level steps; erroring steps are replaced by `sorry` (leading line kept when "
             "the step opens a block and the error is inside it); recompile. Max 4 replacement rounds. "
             "Change size = changed lines against the nearest clean node of the same run.", "",
             f"Failed-draft pool: {pool_size} (skipped: {skipped}). Sample: {len(results)} drafts, "
             f"total Lean time {total_lean:.0f} s.", "", "## By change size", "", summary_table(results), "",
             "## Row gate (reference compile, cold, must be clean and <= 120 s)", "",
             "| theorem | ok | seconds | note |", "|---|---|---|---|"]
    for th, g in gate.items():
        lines.append(f"| {th} | {g['ok']} | {g.get('seconds', '-')} | {g['note']} |")
    lines += ["", "## Per draft", "", "| run | theorem | change | status | rounds | holes | % kept | Lean s | first error |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        kept = "-" if r["kept"] is None else f"{100 * r['kept']:.0f}"
        first = (r["first_error"] or [None, ""])
        msg = (f"L{first[0]}: {first[1]}" if first[0] else "-").replace("|", "/")
        lines.append(f"| {r['run']} | {r['theorem']} | {r['change']} | {r['status']} | {len(r['rounds'])} | "
                     f"{r['holes']} | {kept} | {r['lean_s']} | {msg} |")
    (HERE / "salvage-v6.md").write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args()
    drafts, refs, skipped = load_drafts()
    counts = {b: sum(d["bucket"] == b for d in drafts) for b, _, _ in BUCKETS}
    print(f"failed-draft pool: {len(drafts)} across {len({d['theorem'] for d in drafts})} theorems; buckets {counts}; skipped {skipped}")
    if args.plan:
        return
    check_mem()
    gate = gate_rows(drafts, refs)
    pool = [d for d in drafts if gate.get(d["theorem"], {}).get("ok")]
    chosen = sample(pool)
    print(f"pool after gate: {len(pool)}; sampled {len(chosen)} across {len({d['theorem'] for d in chosen})} rows", flush=True)
    results, total = [], 0.0
    for d in chosen:
        row = __import__("arena.engine", fromlist=["engine"]).problem(d["theorem"])
        res = salvage(row, d["text"], d["version"], d["commit"])
        res.pop("final_text", None)
        total += res["lean_s"]
        results.append(dict(run=d["run"], pid=d["pid"], theorem=d["theorem"], change=d["change"],
                            bucket=d["bucket"], **res))
        print(f"{d['bucket']:>5} {d['theorem'][:40]:40} change={d['change']:3} -> {res['status']} "
              f"rounds={len(res['rounds'])} holes={res['holes']} lean={res['lean_s']}s", flush=True)
        write_outputs(results, gate, skipped, len(drafts), total)
    write_outputs(results, gate, skipped, len(drafts), total)


if __name__ == "__main__":
    main()
