"""Compile every card's before/after in a PutnamBench workspace (Mathlib) per toolchain; write verify.json.

One file per toolchain holds every example (each example is self-contained); errors are mapped to cards by line.
Run: uv run --no-sync python research/strategy-bank/verify_cards.py [toolchain ...]  (default 4.27.0 4.26.0 4.25.0)
"""
import json, re, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(__file__).parent
WS = HERE.parent.parent / "workspaces"
cards = json.loads((HERE / "cards.json").read_text())["cards"]

def check(tc):
    text, spans, line = "import Mathlib\n", [], 2
    for c in cards:
        for k in ("before", "after"):
            body = c[k].strip("\n") + "\n\n"
            spans.append((c["id"], k, line, line + body.count("\n") - 1)); text += body; line += body.count("\n")
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as f:
        f.write(text)
    r = subprocess.run(["lake", "env", "lean", f.name], cwd=WS / f"putnambench-v{tc}", capture_output=True, text=True, timeout=1800)
    Path(f.name).unlink(missing_ok=True)
    bad = {}
    for m in re.finditer(r"^[^\n:]*:(\d+):\d+: error: ([^\n]*)", r.stdout + r.stderr, re.M):
        ln = int(m.group(1))
        for cid, k, a, b in spans:
            if a <= ln <= b: bad.setdefault((cid, k), m.group(2))
    return {c["id"]: "pass" if not any((c["id"], k) in bad for k in ("before", "after")) else "fail" for c in cards}, bad

if __name__ == "__main__":
    tcs = sys.argv[1:] or ["4.27.0", "4.26.0", "4.25.0"]
    res = {}
    for tc in tcs:
        v, bad = check(tc); res[tc] = v
        print(tc, sum(x == "pass" for x in v.values()), "pass /", len(v))
        for (cid, k), msg in bad.items(): print("  FAIL", cid, k, msg[:110])
    (HERE / "verify.json").write_text(json.dumps(res, indent=1))
