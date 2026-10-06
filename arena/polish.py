"""On-demand mechanical polish of a candidate: try small variants, report the ones that still compile.

Variants are generated mechanically (line deletion, `simp?` rewrites, closing-tactic
substitutions) and evaluated on the primary toolchain only. The model chooses which, if any,
to adopt; nothing here records a candidate.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor

from arena.engine import compile_version, problem, validate_proof, versions
from arena.scoring import metrics

MAX_DELETIONS = 30
MAX_SUBSTITUTIONS = 20
MAX_SIMP = 6
CONCURRENCY = 3
TIME_BUDGET_S = 240
KEEP = 8
CLOSERS = ("simp_all", "grind", "omega", "aesop", "simp", "assumption", "trivial", "rfl", "decide", "tauto")
_CLOSING_LINE = re.compile(r"^(\s*(?:[·.]\s*)?)(simp_all|simp|grind|omega|aesop|assumption|trivial|rfl|decide|tauto)\s*$")
_SIMP_LINE = re.compile(r"^(\s*(?:[·.]\s*)?)(simp_all|simp)\b(?!\s*only)(.*)$")
_TRY_THIS = re.compile(r"Try this:\s*(.+)", re.S)


def body_start(proof: str) -> int:
    """Index of the first line after the one containing the statement's `:=`."""
    for index, line in enumerate(proof.splitlines()):
        if ":=" in line and re.search(r":=\s*(by\b.*)?$", line):
            return index + 1
    return len(proof.splitlines())


def _has_children(lines: list[str], index: int) -> bool:
    """A line that opens a block (or has more-indented lines below) cannot be deleted alone."""
    if lines[index].rstrip().endswith(("with", "=>", ":= by", " by", " do")):
        return True
    indent = len(lines[index]) - len(lines[index].lstrip())
    for later in lines[index + 1:]:
        if later.strip():
            return len(later) - len(later.lstrip()) > indent
    return False


def line_variants(proof: str, max_deletions: int = MAX_DELETIONS,
                  max_substitutions: int = MAX_SUBSTITUTIONS) -> list[dict]:
    """Deletions and closing-tactic substitutions; the statement is never touched."""
    lines = proof.splitlines()
    out: list[dict] = []
    start = body_start(proof)
    deletable = [i for i in range(start, len(lines)) if lines[i].strip() and not _has_children(lines, i)]
    for index in reversed(deletable[max(0, len(deletable) - max_deletions):] if max_deletions > 0 else []):
        edited = lines[:index] + lines[index + 1:]
        out.append({"edit": f"delete line {index + 1}: {lines[index].strip()[:60]}", "proof": "\n".join(edited) + "\n"})
    substitutions = 0
    for index in range(start, len(lines)):
        match = _CLOSING_LINE.match(lines[index])
        if not match:
            continue
        for closer in CLOSERS:
            if closer != match[2] and substitutions < max_substitutions:
                substitutions += 1
                edited = lines[:index] + [f"{match[1]}{closer}"] + lines[index + 1:]
                out.append({"edit": f"line {index + 1}: {match[2]} → {closer}", "proof": "\n".join(edited) + "\n"})
    return out


def simp_lines(proof: str, limit: int = MAX_SIMP) -> list[int]:
    lines = proof.splitlines()
    return [i for i in range(body_start(proof), len(lines)) if _SIMP_LINE.match(lines[i])][:limit]


def suggestion(output: str) -> str | None:
    """The `simp only [...]` text from a `simp?` run, whitespace-normalised.

    Lean prints `Try this: simp only [...]`; newer versions put `[apply]` and the text on
    indented following lines. The suggestion ends at the first unindented line.
    """
    found = re.search(r"Try this:(.*)", output)
    if not found:
        return None
    text = [found[1]]
    for line in output[found.end():].splitlines()[1:]:
        if not line.startswith((" ", "\t")):
            break
        text.append(line)
    joined = " ".join(" ".join(text).split()).replace("[apply] ", "", 1)
    return joined if joined.startswith(("simp only", "simp_all only")) else None


def _measure(name: str, row: dict, version: str, commit: str, proof: str) -> dict | None:
    try:
        tokens = validate_proof(row, proof)
    except ValueError:
        return None
    result = compile_version(row, proof, version, commit, measure=True)
    if not result["passed"]:
        return None
    return {"tokens": tokens, "heartbeats": result["heartbeats"]}


def polish(name: str, proof: str, base_heartbeats: int | None = None, max_deletions: int = MAX_DELETIONS,
           max_substitutions: int = MAX_SUBSTITUTIONS, max_simp: int = MAX_SIMP,
           time_budget: float = TIME_BUDGET_S) -> dict:
    """Try mechanical variants of `proof`; return the passing ones that improve an axis."""
    started = time.monotonic()
    row = problem(name)
    version, commit = versions(row)[0]
    total_versions = len(versions(row))
    base = _measure(name, row, version, commit, proof)
    if base is None:
        raise ValueError("The candidate does not compile on the primary toolchain, so there is nothing to polish")
    if base_heartbeats is not None:
        base["heartbeats"] = base_heartbeats
    base_score = metrics(name, base["tokens"], base["heartbeats"], {version: {"passed": True}}, "fast", total_versions)
    candidates = line_variants(proof, max_deletions, max_substitutions)
    lines = proof.splitlines()
    for index in simp_lines(proof, max_simp):
        match = _SIMP_LINE.match(lines[index])
        probe = "\n".join(lines[:index] + [f"{match[1]}{match[2]}?{match[3]}"] + lines[index + 1:]) + "\n"
        ran = compile_version(row, probe, version, commit, measure=False)
        found = suggestion(ran.get("raw_output", ""))
        if found:
            edited = "\n".join(lines[:index] + [f"{match[1]}{found}"] + lines[index + 1:]) + "\n"
            candidates.append({"edit": f"line {index + 1}: {lines[index].strip()[:40]} → {found[:60]}", "proof": edited})
    seen = {proof.strip()}
    unique = []
    for variant in candidates:
        if variant["proof"].strip() not in seen:
            seen.add(variant["proof"].strip())
            unique.append(variant)
    tried, passing = 0, []

    def attempt(variant: dict) -> dict | None:
        if time.monotonic() - started > time_budget:
            return None
        measured = _measure(name, row, version, commit, variant["proof"])
        return {**variant, **measured} if measured else {"failed": True}

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        for outcome in pool.map(attempt, unique):
            if outcome is None:
                continue
            tried += 1
            if not outcome.get("failed"):
                passing.append(outcome)
    improving = []
    for item in passing:
        if item["tokens"] < base["tokens"] or item["heartbeats"] < base["heartbeats"] * 0.98:
            score = metrics(name, item["tokens"], item["heartbeats"], {version: {"passed": True}}, "fast", total_versions)
            item["estimated_proxy"] = score["estimated_proxy"]
            item["delta"] = {"tokens": item["tokens"] - base["tokens"],
                             "heartbeats": item["heartbeats"] - base["heartbeats"],
                             "proxy": round(score["estimated_proxy"] - base_score["estimated_proxy"], 2)}
            improving.append(item)
    improving.sort(key=lambda item: (-item["estimated_proxy"], item["tokens"]))
    return {"base": {**base, "estimated_proxy": base_score["estimated_proxy"]},
            "tried": tried, "generated": len(unique), "passing": len(passing), "improving": len(improving),
            "complete": tried == len(unique), "seconds": round(time.monotonic() - started, 1),
            "variants": improving[:KEEP]}
