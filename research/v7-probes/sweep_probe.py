#!/usr/bin/env python3
"""Pre-run sweep probe over the 15 warm-up rows (analysis only, read-only on the repo).

python3 -I sweep_probe.py --plan              list the cuts per row, no Lean
python3 -I sweep_probe.py [--only NAME]       run gate, sweep and verify per row (sequential Lean)

Per row, PRIMARY toolchain only (version_info[0]):
  gate    one batch file: the original proof, plain and with the harness heartbeat wrapper.
  sweep   up to 12 cuts (tail, subproof, branch) of the original; per cut, one theorem per engine
          (exact?, simp?, aesop?, omega, decide, simp_all, grind, rw?) with the hole filled by that
          engine, all in ONE batch file with set_option maxHeartbeats 400000. Each variant is preceded
          by a `#eval IO.println "ARENA_VARIANT <id>"` marker so unpositioned `Try this:` lines map to a
          variant; positioned errors map by line range.
  verify  every suggestion, and every engine that closed its hole with no suggestion, rebuilt as a full
          proof (cut prefix with the hole replaced). One batch file per row: plain (default options)
          and counted (harness heartbeat wrapper) for each candidate, plus the original.

Lean runs through arena.engine._run_cold (cold `lake env lean`, the harness's own timeout and kill).
Per-row timeout 180 s; a row whose gate, sweep or verify batch hits it is recorded as skipped.
Writes sweep-results.json and sweep-probe.md into this directory.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import salvage_replay as sr  # reuse top_steps and check_mem (its import sets a 120 s env; overridden below)
from arena import engine  # noqa: E402

os.environ["ARENA_LEAN_TIMEOUT"] = "180"
ROW_TIMEOUT = 180
MAX_CUTS = 12
SWEEP_HB = 400000
ENGINES = [("exact?", "exact"), ("simp?", "simp"), ("aesop?", "aesop"), ("omega", "omega"),
           ("decide", "decide"), ("simp_all", "simp_all"), ("grind", "grind"), ("rw?", "rw")]
MARK_RE = re.compile(r"ARENA_VARIANT (\S+)")
HB_RE = re.compile(r"ARENA_HEARTBEATS (\d+)")
POS = re.compile(r"^(?P<f>\S+?):(?P<l>\d+):(?P<c>\d+): (?P<s>error|warning|info)\b:?\s?(?P<m>.*)$")
WRAPPER_DEF = engine.HEARTBEAT_WRAPPER.rsplit("arena_measure_heartbeats", 1)[0]
NAME_RE = re.compile(r"^(\s*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+)?(?:theorem|lemma)\s+)[^\s:(\[{]+")


def indent(s):
    return len(s) - len(s.lstrip(" "))


def blank(s):
    return not s.strip()


def ntok(lines):
    return len(" ".join(lines).split())


def block_end(lines, i, ind):
    """Index one past the last non-blank line deeper than `ind` that follows line i."""
    last, j = i, i + 1
    while j < len(lines):
        if blank(lines[j]):
            j += 1
            continue
        if indent(lines[j]) > ind:
            last = j
            j += 1
            continue
        break
    return last + 1


def hdr_index(lines):
    return next((i for i, l in enumerate(lines) if l.rstrip().endswith(":= by")), None)


def top_steps(lines):
    """Like salvage_replay.top_steps, but the base indent comes from non-comment body lines (some rows
    put comments at a shallower indent than their tactics)."""
    hdr = hdr_index(lines)
    if hdr is None:
        return None
    body = [i for i in range(hdr + 1, len(lines))
            if lines[i].strip() and not lines[i].lstrip().startswith("--")]
    if not body:
        return None
    base = min(indent(lines[i]) for i in body)
    starts = [i for i in body if indent(lines[i]) == base]
    steps = [(starts[k], starts[k + 1] if k + 1 < len(starts) else len(lines)) for k in range(len(starts))]
    steps[0] = (hdr + 1, steps[0][1])
    return hdr, steps, base


def make_cuts(lines):
    """All candidate cuts of the original (list of lines). Each: kind, desc, lines (cut text), hole (index), removed."""
    parsed = top_steps(lines)
    if parsed is None:
        return []
    hdr, steps, base = parsed
    out = []
    for k, (s, _) in enumerate(steps):
        new = lines[:s] + [" " * base + "sorry"]
        out.append(dict(kind="tail", desc=f"tail from step {k + 1}/{len(steps)}", lines=new, hole=s,
                        removed=ntok(lines[s:])))
    for i in range(hdr + 1, len(lines)):
        l = lines[i]
        if blank(l):
            continue
        if l.rstrip().endswith(":= by"):
            ind = indent(l)
            end = block_end(lines, i, ind)
            body = [x for x in lines[i + 1:end] if not blank(x)]
            if not body:
                continue
            bind = indent(body[0])
            new = lines[:i + 1] + [" " * bind + "sorry"] + lines[end:]
            out.append(dict(kind="subproof", desc=f"have body at line {i + 1}", lines=new, hole=i + 1,
                            removed=ntok(lines[i + 1:end])))
            continue
        s = l.strip()
        ind = indent(l)
        head = inline = None
        if s.startswith("·"):
            head, inline = "·", s[1:].strip()
        elif re.match(r"(case|next)\b", s) and "=>" in s:
            cut_at = s.index("=>") + 2
            head, inline = s[:cut_at], s[cut_at:].strip()
        if head is None:
            continue
        end = block_end(lines, i, ind)
        body = [x for x in lines[i + 1:end] if not blank(x)]
        if not inline and not body:
            continue
        new = lines[:i] + [" " * ind + head + " sorry"] + lines[end:]
        out.append(dict(kind="branch", desc=f"branch at line {i + 1}", lines=new, hole=i,
                        removed=ntok(lines[i:end])))
    seen, uniq = set(), []
    for c in out:
        key = "\n".join(c["lines"])
        if key in seen or key.count("sorry") != 1 or c["lines"][c["hole"]].count("sorry") != 1:
            continue
        seen.add(key)
        uniq.append(c)
    uniq.sort(key=lambda c: -c["removed"])
    return uniq[:MAX_CUTS]


def fill(cut, tactic_lines):
    """Cut lines with the hole replaced by tactic_lines (first line keeps the hole's prefix)."""
    new = list(cut["lines"])
    h = cut["hole"]
    hole = new[h]
    ind = " " * indent(hole)
    rep = [hole.replace("sorry", tactic_lines[0], 1)] + [ind + t for t in tactic_lines[1:]]
    return new[:h] + rep + new[h + 1:]


def renamed(lines, vid):
    """Declaration becomes an `example` (same statement, no name), so earlier variants never enter the environment
    that exact?/simp? search. The variant id lives in the marker line, not the name."""
    out, done = [], False
    for l in lines:
        if not done:
            m = NAME_RE.match(l)
            if m:
                l = m.group(1).split("theorem")[0].split("lemma")[0] + "example" + l[m.end():]
                done = True
        out.append(l)
    return out


def assemble(pre, variants):
    """variants: (vid, lines, mode). mode plain | sweep | counted. Returns (text, ranges)."""
    out = pre.rstrip("\n").split("\n") + ["", "set_option maxErrors 1000000", ""] + WRAPPER_DEF.rstrip("\n").split("\n") + [""]
    ranges = {}
    for vid, lines, mode in variants:
        start = len(out) + 1
        out.append(f'#eval IO.println "ARENA_VARIANT {vid}"')
        if mode == "counted":
            out.append("arena_measure_heartbeats")
        if mode == "sweep":
            out.append(f"set_option maxHeartbeats {SWEEP_HB} in")
        out += renamed(lines, vid)
        out.append("")
        ranges[vid] = (start, len(out))
    return "\n".join(out) + "\n", ranges


def parse(out, ranges):
    errs, sugs, hb, glob = defaultdict(list), defaultdict(list), {}, []
    lines = out.split("\n")

    def owner_at(L):
        return next((v for v, (a, b) in ranges.items() if a <= L <= b), None)

    cur, i, cur_seen = None, 0, set()
    while i < len(lines):
        line = lines[i]
        i += 1
        m = MARK_RE.search(line)
        if m:
            cur = m.group(1)
            cur_seen.add(cur)
            continue
        m = HB_RE.search(line)
        if m and cur:
            hb[cur] = int(m.group(1))
            continue
        pm = POS.match(line)
        if pm:
            owner, sev, msg = owner_at(int(pm.group("l"))), pm.group("s"), pm.group("m")
            if owner is None:
                if sev == "error":
                    glob.append(msg)
                continue
        else:
            owner, sev, msg = cur, None, line
        if sev == "error":
            errs[owner].append(msg)
        if "Try this:" in msg and owner is not None:
            # First line only: Lean prints `[apply] <tactic>`; following indented lines are goal comments
            # (rw?) or trace text, not part of the tactic. Verification checks whatever is kept.
            first = msg.split("Try this:", 1)[1].strip()
            if not first and i < len(lines):
                first = lines[i].strip()
            first = re.sub(r"^\[apply\]\s*", "", first).strip()
            if first:
                sugs[owner].append(first)
    return errs, sugs, hb, glob, cur_seen


def dump(name, stage, out):
    d = HERE / "sweep-raw"
    d.mkdir(exist_ok=True)
    (d / f"{name}-{stage}.out").write_text(out)


def norm_suggestion(text):
    return [l.rstrip() for l in text.split("\n") if l.strip()]


def tokens(text, stmt):
    try:
        return engine._proof_length(text, stmt)
    except Exception:
        return None


def run_cold(row, project, text, timeout):
    """engine._run_cold, plus `-DmaxErrors` on the command line (a file-level set_option does not lift Lean's
    100-error cap for the batch). Candidate file lives in a temp dir under this experiments folder."""
    direct = engine._lean_command(str(project))
    if direct is None:
        return engine._run_cold(row, project, text, timeout)
    name = Path(engine.source_path(row)).name
    with tempfile.TemporaryDirectory(prefix="lean-tmp-", dir=HERE) as d:
        cand = Path(d) / name
        cand.write_text(text, encoding="utf-8")
        proc = subprocess.Popen([direct[0], "-DmaxErrors=1000000", str(cand)], cwd=project, text=True,
                                env={**os.environ, **direct[1]}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            return None
    return proc.returncode, (out + err).replace(str(cand), engine.source_path(row)).strip()


def lean(row, project, text):
    sr.check_mem()
    t0 = time.monotonic()
    res = run_cold(row, project, text, ROW_TIMEOUT)
    return res, round(time.monotonic() - t0, 1)


def known_best():
    path = ROOT / "runs/analysis/submission-v3/submission.jsonl"
    out = {}
    if path.exists():
        for l in path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                out[r["name"]] = r["proof"]
    return out


def process_row(row, results, args):
    name = row["name"]
    version, commit = engine.versions(row)[0]
    rec = dict(name=name, toolchain=version, status="running", lean_s=0.0, gate_s=None, cuts=[], engines={},
               candidates=[], verified=[], note="")
    results[name] = rec
    built = engine.candidate_file(row, row["src"], version, commit)
    pre, project = built["text"][:built["offset"]], built["path"]
    src = row["src"].rstrip("\n")
    src_lines = src.split("\n")
    stmt = row["statement"]
    orig_tok = tokens(src, stmt)
    rec["orig_tokens"] = orig_tok
    rec["orig_proof_length_field"] = row.get("proof_length")

    # gate
    text, ranges = assemble(pre, [("orig", src_lines, "plain"), ("orig_hb", src_lines, "counted")])
    res, secs = lean(row, project, text)
    rec["lean_s"] += secs
    rec["gate_s"] = secs
    if res is None:
        rec.update(status="skipped", note=f"gate compile exceeded {ROW_TIMEOUT} s")
        return
    errs, sugs, hb, glob, seen = parse(res[1], ranges)
    if glob or errs["orig"] or errs["orig_hb"]:
        rec.update(status="skipped", note="original does not compile in batch: "
                   + str((glob + errs["orig"] + errs["orig_hb"])[:1])[:200])
        return
    rec["orig_heartbeats"] = hb.get("orig_hb")
    dump(name, "gate", res[1])
    print(f"[{name}] gate {secs}s hb={hb.get('orig_hb')} tokens={orig_tok}", flush=True)
    if args.gate_only:
        rec.update(status="gate-only")
        return

    # sweep
    cuts = make_cuts(src_lines)
    rec["cuts"] = [dict(id=f"c{ci}", kind=c["kind"], desc=c["desc"], removed_tokens=c["removed"],
                        hole_line=c["hole"] + 1) for ci, c in enumerate(cuts)]
    variants, meta = [], {}
    for ci, c in enumerate(cuts):
        for eng, short in ENGINES:
            vid = f"sweep_c{ci}_{short}"
            lines = fill(c, [eng])
            variants.append((vid, lines, "sweep"))
            meta[vid] = (ci, eng)
    if not variants:
        rec.update(status="skipped", note="no cuts (unparseable shape)")
        return
    text, ranges = assemble(pre, variants)
    res, secs = lean(row, project, text)
    rec["lean_s"] += secs
    if res is None:
        rec.update(status="skipped", note=f"sweep batch exceeded {ROW_TIMEOUT} s ({len(variants)} variants)",
                   sweep_s=secs)
        return
    errs, sugs, hb, glob, seen = parse(res[1], ranges)
    dump(name, "sweep", res[1])
    rec["sweep_s"] = secs
    rec["sweep_global_errors"] = glob[:3]
    cand_pool = []
    for vid, (ci, eng) in meta.items():
        c = cuts[ci]
        errl = errs.get(vid, [])
        unavail = any("unknown" in e and "tactic" in e for e in errl)
        if vid not in seen:
            status = "not-run"
        else:
            status = "unavailable" if unavail else ("closed" if not errl else "fail")
        s_list = [norm_suggestion(t) for t in sugs.get(vid, [])]
        sug = s_list[0] if s_list else None
        rec["engines"].setdefault(eng, dict(closed=0, fail=0, unavailable=0, suggestion=0, **{"not-run": 0}))
        rec["engines"][eng][status if status != "closed" else "closed"] += 1
        if sug:
            rec["engines"][eng]["suggestion"] += 1
        rec["cuts"][ci].setdefault("results", {})[eng] = dict(status=status, suggestion=sug,
                                                              first_error=(errl[0][:160] if errl else None))
        for one in s_list:
            cand_pool.append((ci, eng, "suggestion", one))
        if not s_list and status == "closed":
            cand_pool.append((ci, eng, "engine", [eng]))

    # verify
    seen, cands = set(), []
    for ci, eng, source, tl in cand_pool:
        full = fill(cuts[ci], tl)
        key = "\n".join(full)
        if key in seen:
            continue
        seen.add(key)
        cands.append(dict(cut=f"c{ci}", engine=eng, source=source, lines=full))
    rec["candidates"] = [dict(cut=c["cut"], engine=c["engine"], source=c["source"]) for c in cands]
    if not cands:
        rec.update(status="done", note="no suggestions and no engine closed a hole")
        return
    vlist = [("orig", src_lines, "plain"), ("orig_hb", src_lines, "counted")]
    for k, c in enumerate(cands):
        vlist += [(f"ver{k}", c["lines"], "plain"), (f"ver{k}_hb", c["lines"], "counted")]
    text, ranges = assemble(pre, vlist)
    res, secs = lean(row, project, text)
    rec["lean_s"] += secs
    if res is None:
        rec.update(status="done", note=f"verify batch exceeded {ROW_TIMEOUT} s", verify_s=secs)
        return
    errs, _, hb2, glob2, seen2 = parse(res[1], ranges)
    dump(name, "verify", res[1])
    rec["verify_s"] = secs
    for k, c in enumerate(cands):
        full_text = "\n".join(c["lines"])
        tok = tokens(full_text, stmt)
        ok = f"ver{k}" in seen2 and f"ver{k}_hb" in seen2 and not errs.get(f"ver{k}") and not glob2
        rec["verified"].append(dict(cut=c["cut"], engine=c["engine"], source=c["source"], compiles=ok,
                                    tokens=tok, d_tokens=None if tok is None or orig_tok is None else tok - orig_tok,
                                    heartbeats=hb2.get(f"ver{k}_hb"),
                                    d_heartbeats=None if hb2.get(f"ver{k}_hb") is None or hb.get("orig_hb") is None
                                    else hb2[f"ver{k}_hb"] - hb["orig_hb"],
                                    first_error=(errs.get(f"ver{k}") or [None])[0],
                                    proof=full_text if ok and tok is not None and orig_tok and tok < orig_tok else None))
    rec["status"] = "done"


def write_outputs(results, plan_only=False):
    (HERE / "sweep-results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str))
    kb = known_best()
    L = ["# Pre-run sweep probe (warm-up rows, primary toolchain)", "",
         "The sweep cuts the VALID original proof (tail, subproof and branch cuts, at most 12 per row), asks each",
         "engine (exact?, simp?, aesop?, omega, decide, simp_all, grind, rw?) to close the hole, and verifies every",
         "suggestion or closing engine as a full proof. `d_tok` is against the original proof (negative is shorter).",
         "Heartbeats are measured the harness way (counted wrapper, maxHeartbeats 0); the sweep itself runs with",
         f"maxHeartbeats {SWEEP_HB}. Lean runs cold, one process at a time, 180 s cap per batch file.", "",
         "## Per row", "",
         "| row | toolchain | status | cuts | engine hits (closed / suggest) | verified replacements | compiles | best d_tok | best d_hb (same) | orig tok | known-best tok | Lean s | note |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    tot_s, shorter_rows, best_gain = 0.0, [], []
    for name, r in results.items():
        cuts = len(r.get("cuts", []))
        closed = sum(e.get("closed", 0) for e in r.get("engines", {}).values())
        sugg = sum(e.get("suggestion", 0) for e in r.get("engines", {}).values())
        ver = r.get("verified", [])
        okc = [v for v in ver if v["compiles"]]
        short = [v for v in okc if v["d_tokens"] is not None and v["d_tokens"] < 0]
        bt = min(short, key=lambda v: v["d_tokens"]) if short else None
        row_obj = next(x for x in ROWS if x["name"] == name)
        kt = tokens(kb[name], row_obj["statement"]) if name in kb else None
        tot_s += r.get("lean_s", 0.0) or 0.0
        if bt:
            shorter_rows.append(name)
            best_gain.append((name, bt["d_tokens"], bt.get("d_heartbeats")))
        L.append(f"| {name} | {r.get('toolchain')} | {r.get('status')} | {cuts} | {closed} / {sugg} | {len(ver)} "
                 f"tried, {len(okc)} compile | {len(okc)} | {bt['d_tokens'] if bt else '-'} | "
                 f"{bt['d_heartbeats'] if bt else '-'} | {r.get('orig_tokens')} | {kt if kt is not None else '-'} | "
                 f"{r.get('lean_s', 0):.0f} | {(r.get('note') or '-').replace('|', '/')[:120]} |")
    L += ["", "## Engine totals", "", "| engine | closed | suggestion | unavailable |", "|---|---|---|---|"]
    agg = defaultdict(lambda: defaultdict(int))
    for r in results.values():
        for eng, e in r.get("engines", {}).items():
            for k, v in e.items():
                agg[eng][k] += v
    for eng, _ in ENGINES:
        e = agg.get(eng, {})
        L.append(f"| {eng} | {e.get('closed', 0)} | {e.get('suggestion', 0)} | {e.get('unavailable', 0)} |")
    L += ["", f"Rows with at least one verified shorter replacement: {len(shorter_rows)} "
          f"({', '.join(shorter_rows) or 'none'}).", f"Total Lean seconds (all batches): {tot_s:.0f}.", ""]
    (HERE / "sweep-probe.md").write_text("\n".join(L) + "\n")


ROWS = []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--gate-only", action="store_true")
    args = ap.parse_args()
    global ROWS
    ROWS = [json.loads(l) for l in (ROOT / "benchmark/original/warmup.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in ROWS if args.only is None or r["name"] == args.only]
    if args.plan:
        for r in rows:
            v, c = engine.versions(r)[0]
            cuts = make_cuts(r["src"].rstrip("\n").split("\n"))
            print(f"{r['name']} [{v}] cuts={len(cuts)} " + " ".join(f"{c['kind'][0]}{c['removed']}" for c in cuts))
        return
    results = {}
    for r in rows:
        sr.check_mem()
        try:
            process_row(r, results, args)
        except Exception as exc:  # keep the sweep going; record the row
            results[r["name"]] = dict(name=r["name"], status="error", note=f"{type(exc).__name__}: {str(exc)[:200]}",
                                      lean_s=0.0, cuts=[], engines={}, verified=[], candidates=[], toolchain=None)
        write_outputs(results)
        print(f"done {r['name']}: {results[r['name']]['status']} {results[r['name']].get('note', '')}", flush=True)
    write_outputs(results)


if __name__ == "__main__":
    main()
