"""Shared submission helpers: hashes, the manifest, charged attempts, the code archive and report text.

`arena submit` prepares the upload. Nothing here uploads anything.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from arena.engine import ROOT
from arena.summary import ledger_spend, session_spend

CEILING_USD = 3.0  # closed-track per-problem ceiling over every call of every run of that problem
MANIFEST = ROOT / "benchmark" / "original" / "warmup.jsonl"
RUNS = ROOT / "runs" / "pi-budget"
DEPENDENCY_FILES = (
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "packages/arena-pi/package.json",
    "packages/arena-pi/package-lock.json",
    "packages/arena-pi/pnpm-lock.yaml",
    "packages/arena-pi/bun.lock",
    ".gitmodules",
)


class PackageError(Exception):
    """Staging must stop: budget, eligibility or input problems the operator has to resolve."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def load_manifest(path: Path = MANIFEST) -> dict[str, dict]:
    rows = _jsonl(path)
    if not rows:
        raise PackageError(f"manifest {path} is missing or empty")
    return {row["name"]: row for row in rows}


# ---- per-run audit -------------------------------------------------------------------------------


def attempts(directory: Path) -> dict:
    """Every charged API attempt of one run, joined to the trace journal."""
    cost = _jsonl(directory / "cost-ledger.jsonl")
    journal = _jsonl(directory / "trace-journal.jsonl")
    requests = {row.get("id"): row for row in journal if row.get("kind") == "request"}
    responses = {row.get("id"): row for row in journal if row.get("kind") == "response"}
    rows, spent = [], 0.0
    for event in cost:
        key = str(event.get("id"))
        if event.get("kind") == "settle":
            usd = float(event.get("usd") or 0)
            spent += usd
            request = requests.get(event.get("id")) or {}
            response = responses.get(event.get("id")) or {}
            rows.append(
                {
                    "id": key,
                    "ts": event.get("ts"),
                    "usd": usd,
                    "usage_known": event.get("usage_known") is not False,
                    "tokens": event.get("tokens"),
                    "retry_of": request.get("retry_of"),
                    "journaled": bool(request),
                    "model": request.get("model"),
                    "response_id": response.get("response_id"),
                    "response_model": response.get("response_model"),
                    "stop_reason": response.get("stop_reason"),
                }
            )
    # Never report less than Pi's own session total.
    session = session_spend(directory)
    recon = ledger_spend(cost, session["usd"] if session else None)
    spent = max(spent, recon["spent_usd"])
    return {
        "settles": rows,
        "spent_usd": spent,
        "unsettled_usd": recon["gap_usd"],
        "reconciliation": recon,
        "total_usd": spent,
        "retries": sum(1 for r in rows if r["retry_of"]),
        "journal_requests": len(requests),
    }


def trace_ids(directory: Path, config: dict) -> list[str]:
    """Langfuse trace IDs recorded locally; the live lookup only runs under ARENA_LIVE_LANGFUSE=1."""
    found = set(config.get("trace_ids") or [])
    for row in _jsonl(directory / "trace-journal.jsonl"):
        for key in ("trace_id", "traceId"):
            if row.get(key):
                found.add(row[key])
    if os.environ.get("ARENA_LIVE_LANGFUSE") == "1":  # pragma: no cover - needs the network
        from arena.traces import list_observations

        started = datetime.fromtimestamp((_jsonl(directory / "ledger.jsonl") or [{"ts": 0}])[0]["ts"], UTC)
        found |= {row["traceId"] for row in list_observations(directory.name, started) if row.get("traceId")}
    return sorted(found)


# ---- code archive ----------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def reproduce_text(commit: str, run_ids: list[str], submodules: list[str], toolchains: list[str], name: str) -> str:
    runs = " ".join(run_ids)
    modules = "\n".join(f"- `{line}`" for line in submodules) or "- none recorded"
    return f"""# Reproduce the submission

Archive of harness commit `{commit}` (`git archive`, read-only). Staging name: `{name}`.

## Pinned inputs

- Lean toolchains used by the submitted proofs: {", ".join(sorted(set(toolchains))) or "see provenance.json"}
- Submodule revisions (not contained in the archive; fetch them at exactly these commits):
{modules}
- Dependency files from the repository root are included unchanged (`.gitmodules`, `packages/arena-pi/package.json`
  and any lock files present at the commit).
- Pi extension: `packages/arena-pi/`.

## Regenerate `proofs.jsonl`

1. Provision the pinned workspaces (`arena provision`) for each benchmark row.
2. Re-run each problem with `arena run` or `arena campaign`, or reuse the recorded run
   directories listed in `provenance.json`.
3. Prepare the files: `uv run arena submit --name {name} --runs {runs}`

This prepares files only. The owner uploads. `provenance.json` joins each proof's sha256 to its run,
candidate, model and every charged API attempt.
"""


def build_archive(repo: Path, commit: str, destination: Path, extra: dict[str, str]) -> dict:
    """`git archive <commit>` plus top-level files (REPRODUCE.md) appended; the repository is not modified."""
    commit = _git(repo, "rev-parse", "--verify", commit + "^{commit}").strip()
    raw = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", commit], check=True, capture_output=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as source:
        existing = set(source.getnames())
    present = [p for p in DEPENDENCY_FILES if p in existing]
    buffer = io.BytesIO(raw)
    with tarfile.open(fileobj=buffer, mode="a") as tar:
        for path, text in extra.items():
            data = text.encode()
            member = tarfile.TarInfo(path)
            member.size = len(data)
            member.mtime = 0
            tar.addfile(member, io.BytesIO(data))
    with tarfile.open(destination, "w:gz") as out, tarfile.open(fileobj=io.BytesIO(buffer.getvalue())) as tar:
        for member in tar:
            out.addfile(member, tar.extractfile(member) if member.isfile() else None)
    return {
        "commit": commit,
        "path": str(destination),
        "dependency_files": present,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }


def submodule_pins(repo: Path, commit: str) -> list[str]:
    try:
        tree = _git(repo, "ls-tree", "-r", commit)
    except (subprocess.CalledProcessError, OSError):
        return []
    return [f"{line.split()[3]} @ {line.split()[2]}" for line in tree.splitlines() if line.startswith("160000")]


# ---- report ----------------------------------------------------------------------------------------

DEFAULT_TEMPLATE = Template("""# $title

## Approach

$approach

## Models

$models

## Budget accounting

$budget

## Reproduction

$reproduction
""")


def report(prov: dict, commit: str, name: str, template: Template | None = None) -> str:
    """Markdown report with the four mandatory sections, filled from run data. The official LaTeX
    bundle is not in the repository, so `template` (a string.Template with the same placeholders) is pluggable."""
    problems = prov["problems"]
    models: dict[str, set] = {}
    for row in problems.values():
        info = row["model"]
        models.setdefault(info["name"], set()).update(info["response_models"])
    approach = (
        "A Pi agent loop with the arena tools proposes, evaluates and refines Lean proofs per problem; "
        "each candidate is compiled on every pinned toolchain and the best cold-verified model "
        f"candidate is submitted. {len(problems)} problem(s) are submitted; "
        f"{len(prov['rejected'])} run(s) were rejected during selection."
    )
    model_lines = "\n".join(
        f"- {n} (eligible: {'yes' if n in prov['eligible_models'] else 'NO'}; "
        f"provider response models: {', '.join(sorted(r)) or 'unrecorded'})"
        for n, r in sorted(models.items())
    )
    rows = ["| Problem | Run | Spend (USD) | Calls | Retries | Ceiling |", "|---|---|---:|---:|---:|---:|"]
    spends = []
    for n, row in sorted(problems.items()):
        calls = sum(len(c["attempts"]) for c in row["calls"])
        retries = sum(c["retries"] for c in row["calls"])
        spends.append(row["spend_usd"])
        rows.append(
            f"| {n} | {row['run_id']} | {row['spend_usd']:.4f} | {calls} | {retries} | ${row['ceiling_usd']:.2f} |"
        )
    total = sum(spends)
    summary = (
        f"Total ${total:.4f}, mean ${total / len(spends):.4f}, max ${max(spends):.4f} per problem "
        f"(ceiling ${prov['ceiling_usd']:.2f}); spend includes retries and discarded runs."
        if spends
        else "No problems submitted."
    )
    reproduction = (
        f"Code archive from commit `{commit}`; see the top-level `REPRODUCE.md` in the archive "
        f"and `provenance.json` for the run, candidate and hash of every submitted proof "
        f"(staging name `{name}`)."
    )
    return (template or DEFAULT_TEMPLATE).safe_substitute(
        title=f"Arena submission report: {name}",
        approach=approach,
        models=model_lines or "No models.",
        budget=summary + "\n\n" + "\n".join(rows),
        reproduction=reproduction,
    )
