"""Build a competition submission from a baseline directory plus the best cold-verified harness runs.

A directory holds `submission.jsonl` (`{"name","proof"}` per line) and `scores.json` (`{name: {"proxy","source"}}`),
so one build's output is the next build's baseline.
"""

from __future__ import annotations

import ast
import json
import re
from functools import cache
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs" / "pi-budget"
APP = ROOT / "vendor" / "arena-space" / "app.py"
COLD_TOLERANCE = 0.05
_FILTER_NAMES = {"_MAX_PROOF_BYTES", "_FORBIDDEN_PATTERNS", "_strip_lean_comments", "_check_forbidden"}


class SubmissionError(Exception):
    """The build cannot proceed; the message says why."""


@cache
def forbidden_filter() -> Callable[[str], Any]:
    """The official `_check_forbidden`, executed from app.py without importing gradio."""
    keep = []
    for node in ast.parse(APP.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef):
            if node.name in _FILTER_NAMES:
                keep.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(getattr(t, "id", None) in _FILTER_NAMES for t in targets):
                keep.append(node)
    namespace: dict[str, Any] = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "app_filter", "exec"), namespace)
    return namespace["_check_forbidden"]


def check(name: str, proof: str) -> list[str]:
    """Statement and official forbidden-content problems of one proof (empty when clean)."""
    from arena import engine

    problems = []
    try:
        engine.validate_proof(engine.problem(name), proof)
    except Exception as error:
        problems.append(f"validate: {error}")
    found = forbidden_filter()(proof)
    if found:
        problems.append(f"forbidden: {found}")
    return problems


def load_baseline(directory: Path) -> dict[str, dict]:
    """Rows of `directory/submission.jsonl` with their proxy and source from `scores.json`."""
    directory = Path(directory)
    scores = json.loads((directory / "scores.json").read_text(encoding="utf-8"))
    rows = {}
    for line in (directory / "submission.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            score = scores[row["name"]]
            rows[row["name"]] = {"proof": row["proof"], "proxy": float(score["proxy"]), "source": score["source"]}
    return rows


def run_results(root: Path = RUNS, names: set[str] | list[str] | None = None) -> dict[str, list[dict]]:
    """Every cold-verified finished run per theorem; unreadable runs are skipped."""
    found: dict[str, list[dict]] = {}
    for path in sorted(Path(root).glob("*/summary.json")):
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
            sub = summary["submission"]
            if not sub.get("ok") or sub.get("verified_by") != "cold compile":
                continue
            theorem = summary["theorem"]
            if names is not None and theorem not in names:
                continue
            found.setdefault(theorem, []).append(
                {
                    "run_id": path.parent.name,
                    "model": summary.get("model"),
                    "proxy": float(sub["proxy"]),
                    "tokens": sub.get("tokens"),
                    "heartbeats": sub.get("heartbeats"),
                    "spent_usd": (summary.get("cost") or {}).get("spent_usd"),
                    "proof": (path.parent / sub["proof_file"]).read_text(encoding="utf-8"),
                }
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return found


def choose(baseline: dict[str, dict], results: dict[str, list[dict]]) -> dict[str, dict]:
    """Per row the best run when it scores above the baseline at all, else the baseline; with source and delta."""
    chosen = {}
    for name, base in baseline.items():
        best = max(results.get(name, []), key=lambda run: run["proxy"], default=None)
        if best is not None and best["proxy"] > base["proxy"]:
            chosen[name] = {
                **best,
                "source": f"{best['run_id']} ({best['model']})",
                "delta": round(best["proxy"] - base["proxy"], 2),
                "changed": True,
            }
        else:
            chosen[name] = {**base, "delta": 0.0, "changed": False}
    return chosen


def gain_order(names: list[str], baseline: dict[str, dict], results: dict[str, list[dict]]) -> list[str]:
    """Rows by headroom (100 minus the best known proxy), largest first."""

    def headroom(name: str) -> float:
        known = [baseline[name]["proxy"]] if name in baseline else []
        known += [run["proxy"] for run in results.get(name, [])]
        return 100 - max(known, default=0.0)

    return sorted(names, key=headroom, reverse=True)


def _cold_check(name: str, proof: str, expected: float) -> None:
    from arena import engine

    with engine.force_cold():
        result = engine.evaluate(name, proof, "full", request_class="full_check")
    failed = [v for v, info in result.get("compat", {}).items() if not info.get("passed")]
    if failed:
        raise SubmissionError(f"cold compile failed for {name} on {', '.join(failed)}")
    cold = result["local_proxy"]
    if cold is None or abs(cold - expected) > COLD_TOLERANCE:
        raise SubmissionError(f"cold proxy {cold} differs from the run's {expected} for {name}")


def _manifest(rows: dict[str, dict], total: float, count: int) -> str:
    def cell(row: dict, key: str, fmt: str = "{}") -> str:
        return fmt.format(row[key]) if row.get(key) is not None else "-"

    ordered = sorted(rows.items(), key=lambda item: not item[1]["changed"])
    lines = [
        "# Submission manifest",
        "",
        f"Projected mean: {total / count:.2f} (sum {total:.2f} over {count} rows). "
        f"{sum(r['changed'] for r in rows.values())} row(s) changed from the baseline, listed first.",
        "",
        "| Row | Source | Proxy | Delta | Tokens | HB | Spent |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, row in ordered:
        source = row["source"] if row["changed"] else "baseline"
        spent = cell(row, "spent_usd", "${:.3f}")
        lines.append(
            f"| {name} | {source} | {row['proxy']:.2f} | {row['delta']:+.2f} | {cell(row, 'tokens')} "
            f"| {cell(row, 'heartbeats')} | {spent} |"
        )
    spends = [r["spent_usd"] for r in rows.values() if r.get("spent_usd") is not None]
    lines += [
        "",
        "Spend per row: changed rows show the settled spend of their one run; baseline rows show `-` "
        "(their runs are in the earlier manifests). Each row's total across all contributing runs must stay "
        f"under the track limit. Spend listed here: ${sum(spends):.3f}.",
        "",
    ]
    return "\n".join(lines)


def build(out: Path, baseline_dir: Path, root: Path = RUNS, cold: bool = False) -> dict:
    """Write `out/{submission.jsonl,scores.json,MANIFEST.md}`; refuse on any row problem or existing `out`."""
    out = Path(out)
    if out.exists():
        raise SubmissionError(f"refusing to overwrite {out}")
    baseline = load_baseline(baseline_dir)
    chosen = choose(baseline, run_results(root, set(baseline)))
    problems = {name: found for name, row in chosen.items() if (found := check(name, row["proof"]))}
    if problems:
        raise SubmissionError("; ".join(f"{name}: {found}" for name, found in problems.items()))
    if cold:
        for name, row in chosen.items():
            if row["changed"]:
                _cold_check(name, row["proof"], row["proxy"])
    total = round(sum(row["proxy"] for row in chosen.values()), 2)
    out.mkdir(parents=True)
    (out / "submission.jsonl").write_text(
        "".join(json.dumps({"name": n, "proof": r["proof"]}, ensure_ascii=False) + "\n" for n, r in chosen.items()),
        encoding="utf-8",
    )
    scores = {n: {"proxy": r["proxy"], "source": r["source"]} for n, r in chosen.items()}
    (out / "scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest = _manifest(chosen, total, len(chosen))
    (out / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    return {
        "out": str(out),
        "rows": len(chosen),
        "changed": [n for n, r in chosen.items() if r["changed"]],
        "total": total,
        "mean": round(total / len(chosen), 2),
        "manifest": manifest,
    }


def cli_execute(baseline: Path, out: Path, cold: bool = False) -> int:
    try:
        result = build(out, baseline, cold=cold)
    except (SubmissionError, OSError, ValueError, KeyError) as error:
        print(f"submission: {error}")
        return 2
    print(result["manifest"])
    print(f"wrote {result['out']}: {result['rows']} rows, {len(result['changed'])} changed, mean {result['mean']}")
    return 0
