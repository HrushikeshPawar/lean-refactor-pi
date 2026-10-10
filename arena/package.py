"""Stage a manual Arena submission from finished v6 runs. Nothing here uploads anything.

`stage` selects, per benchmark problem, the best complete, cold-verified, model-produced v6 candidate,
and writes `proofs.jsonl` (official warm-up schema), `provenance.json` (every charged API attempt),
`report.md`, a pinned code archive and `REPRODUCE.md` under one staging directory. Selection is strict:
anything with unknown provenance is rejected, and a budget or model-eligibility violation refuses staging.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from arena.cli.run import MODELS
from arena.engine import ROOT, validate_proof
from arena.summary import ledger_spend, session_spend

ELIGIBLE_MODELS = tuple(MODELS)  # closed-track models the competitor has confirmed eligible
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


def audit_run(run_id: str, runs_root: Path = RUNS) -> dict:
    """Facts about one run directory, and the reasons (if any) it cannot supply a submitted proof."""
    directory = runs_root / run_id
    config = _json(directory / "run-config.json")
    answer = _json(directory / "submission.json")
    ledger = _jsonl(directory / "ledger.jsonl")
    spend = attempts(directory)
    init = next((e for e in ledger if e.get("kind") == "init"), {})
    info = {
        "run_id": run_id,
        "directory": str(directory),
        "theorem": config.get("theorem") or init.get("theorem"),
        "model": config.get("model"),
        "config": config,
        "spend": spend,
        "answer": answer,
        "init": init,
        "ledger": ledger,
        "reasons": [],
    }
    why = info["reasons"]
    if not directory.is_dir():
        why.append("run directory does not exist")
        return info
    if not config:
        why.append("unknown provenance: no run-config.json")
    if not (directory / "trace-journal.jsonl").exists() or not spend["journal_requests"]:
        why.append("not a v6 run: no trace journal with requests (v5 or legacy run)")
    if config.get("hybrid") or config.get("harness") not in (None, "v6"):
        why.append("hybrid or non-v6 source run")
    if info["model"] not in ELIGIBLE_MODELS:
        why.append(f"ineligible model {info['model']!r}")
    candidate_id = answer.get("candidate_id")
    if not answer.get("candidate") or not candidate_id:
        why.append("no candidate: the run kept the original proof")
        return info
    if not str(answer.get("verified_by", "")).startswith("cold compile"):
        why.append("not cold verified")
    cold = [e for e in ledger if e.get("kind") == "cold_verification" and e.get("candidate_id") == candidate_id]
    if cold and not cold[-1].get("confirmed"):
        why.append("cold verification did not confirm the candidate")
    event = next((e for e in ledger if e.get("kind") == "candidate" and e.get("candidate_id") == candidate_id), None)
    if event is None:
        why.append("unknown provenance: candidate has no ledger event")
    elif event.get("origin") != "model":
        why.append(f"origin {event.get('origin')!r} is not model-produced")
    elif not event.get("source_versions"):
        why.append("unknown provenance: candidate lacks pinned source versions")
    info["candidate_event"] = event or {}
    full = [
        e
        for e in ledger
        if e.get("kind") == "evaluation" and e.get("candidate_id") == candidate_id and e.get("mode") == "full"
    ]
    passed_all = [
        e
        for e in full
        if (e.get("result") or {}).get("compat") and all(c.get("passed") for c in e["result"]["compat"].values())
    ]
    if not passed_all:
        why.append("no full evaluation passing every toolchain")
    info["evaluation"] = (
        max(passed_all, key=lambda e: (e["result"].get("metrics") or {}).get("score") or 0, default=None)
        if passed_all
        else None
    )
    try:
        info["proof"] = (directory / answer.get("proof_file", "submission.lean")).read_text()
    except OSError:
        why.append("submission proof file is missing")
    return info


def check_candidate(info: dict, manifest: dict[str, dict]) -> list[str]:
    """Rejection reasons that need the manifest: names, statements, hashes, prohibited constructs."""
    why = []
    row = manifest.get(info["theorem"])
    if row is None:
        return [f"{info['theorem']!r} is not in the official manifest"]
    proof = info.get("proof")
    if proof is None:
        return []
    try:
        validate_proof({"statement": row["statement"]}, proof)
    except ValueError as error:
        why.append(str(error).split(":")[0] + ": " + str(error)[:160])
    # sorry/admit/axiom etc. are already part of validate_proof's FORBIDDEN list.
    candidate_id = info["answer"]["candidate_id"]
    if sha256_text(info["theorem"] + "\0" + proof) != candidate_id:
        why.append("proof text does not hash to its candidate ID (tampered or mismatched file)")
    snapshot = Path(info["directory"]) / "proofs" / f"{candidate_id}.lean"
    if snapshot.exists() and snapshot.read_text() != proof:
        why.append("submission.lean differs from the recorded candidate snapshot")
    return why


def select(run_ids: list[str], manifest: dict[str, dict], runs_root: Path = RUNS) -> dict:
    """Best acceptable candidate per problem, with every rejection and its reasons."""
    audits = [audit_run(run_id, runs_root) for run_id in run_ids]
    chosen: dict[str, dict] = {}
    rejected = []
    for info in audits:
        reasons = list(info["reasons"])
        if not reasons:
            reasons = check_candidate(info, manifest)
        if reasons:
            rejected.append({"run_id": info["run_id"], "theorem": info["theorem"], "reasons": reasons})
            continue
        score = info["answer"].get("proxy")
        score = float(score) if score is not None else float("-inf")
        best = chosen.get(info["theorem"])
        if best is None or score > best["_score"]:
            chosen[info["theorem"]] = info | {"_score": score}
    return {"audits": audits, "selected": chosen, "rejected": rejected}


# ---- budget and eligibility ------------------------------------------------------------------------


def discover_runs(theorems: set[str], runs_root: Path = RUNS) -> list[str]:
    """Every run directory of these problems, so the ceiling counts calls the operator did not list."""
    return [
        config.parent.name
        for config in sorted(runs_root.glob("*/run-config.json"))
        if _json(config).get("theorem") in theorems
    ]


def budget_by_problem(audits: list[dict]) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for info in audits:
        row = table.setdefault(info["theorem"], {"usd": 0.0, "calls": 0, "runs": {}, "models": set()})
        row["usd"] += info["spend"]["total_usd"]
        row["calls"] += len(info["spend"]["settles"])
        row["runs"][info["run_id"]] = info["spend"]["total_usd"]
        row["models"].add(info["model"])
    return table


def violations(audits: list[dict], budget: dict[str, dict]) -> list[str]:
    problems = []
    for name, row in sorted(budget.items()):
        if row["usd"] > CEILING_USD + 1e-9:
            problems.append(
                f"{name}: ${row['usd']:.4f} across {len(row['runs'])} run(s) exceeds the ${CEILING_USD:.2f} ceiling"
            )
    for info in audits:
        if info["model"] not in ELIGIBLE_MODELS and info["spend"]["settles"]:
            problems.extend(
                [f"{info['run_id']}: model {info['model']!r} is not in the eligibility list {ELIGIBLE_MODELS}"]
            )
    return problems


# ---- provenance ledger -----------------------------------------------------------------------------


def provenance(selection: dict, budget: dict[str, dict]) -> dict:
    rows = {}
    for name, info in sorted(selection["selected"].items()):
        proof = info["proof"]
        evaluation = (info.get("evaluation") or {}).get("result", {})
        versions = info["candidate_event"].get("source_versions") or info["init"].get("versions") or []
        same_problem = [a for a in selection["audits"] if a["theorem"] == name]
        config = info["config"]
        rows[name] = {
            "proof_sha256": sha256_text(proof),
            "candidate_id": info["answer"]["candidate_id"],
            "candidate": info["answer"]["candidate"],
            "run_id": info["run_id"],
            "model": {
                "name": info["model"],
                "provider": config.get("provider"),
                "version": config.get("model_version"),
                "thinking": config.get("thinking"),
                "response_models": sorted(
                    {s["response_model"] for s in info["spend"]["settles"] if s["response_model"]}
                ),
            },
            "pinned_sources": [list(v) for v in versions],
            "toolchains": [v[0] for v in versions],
            "evaluator_sha256": info["candidate_event"].get("evaluator_sha256"),
            "packet_sha256": config.get("packet_sha256"),
            "skill": config.get("skill"),
            "local_verification": {
                "verified_by": info["answer"].get("verified_by"),
                "proxy": info["answer"].get("proxy"),
                "tokens": info["answer"].get("tokens"),
                "heartbeats": info["answer"].get("heartbeats"),
                "lean_paths": {
                    v: (c.get("lean") or {}).get("path") for v, c in (evaluation.get("compat") or {}).items()
                },
            },
            "langfuse": {"session_id": info["run_id"], "trace_ids": trace_ids(Path(info["directory"]), config)},
            "ledger_paths": {
                k: str(Path(info["directory"]) / k)
                for k in ("ledger.jsonl", "cost-ledger.jsonl", "trace-journal.jsonl", "submission.json")
            },
            "spend_usd": round(budget[name]["usd"], 6),
            "ceiling_usd": CEILING_USD,
            "calls": [
                {
                    "run_id": a["run_id"],
                    "model": a["model"],
                    "selected_run": a["run_id"] == info["run_id"],
                    "discarded": a["run_id"] != info["run_id"],
                    "total_usd": round(a["spend"]["total_usd"], 6),
                    "retries": a["spend"]["retries"],
                    "attempts": a["spend"]["settles"],
                }
                for a in same_problem
            ],
        }
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "ceiling_usd": CEILING_USD,
        "eligible_models": list(ELIGIBLE_MODELS),
        "problems": rows,
        "rejected": selection["rejected"],
        "budget": {
            n: {"usd": round(r["usd"], 6), "calls": r["calls"], "runs": r["runs"]} for n, r in sorted(budget.items())
        },
    }


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
- Pi extension and Langfuse patch: `packages/arena-pi/`. Eligible models: {", ".join(ELIGIBLE_MODELS)}.

## Regenerate `proofs.jsonl`

1. Provision the pinned workspaces (`arena provision`) for each benchmark row.
2. Re-run each problem with `arena run` or `arena campaign`, or reuse the recorded run
   directories listed in `provenance.json`.
3. Package: `uv run arena package {runs} --name {name}`

`provenance.json` joins each proof's sha256 to its run, candidate, model and every charged API attempt.
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


# ---- staging ---------------------------------------------------------------------------------------


def stage(
    name: str,
    run_ids: list[str],
    runs_root: Path = RUNS,
    manifest_path: Path = MANIFEST,
    output_root: Path | None = None,
    repo: Path = ROOT,
    commit: str = "HEAD",
    template: Template | None = None,
    discover: bool = False,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise PackageError("invalid staging name")
    manifest = load_manifest(manifest_path)
    selection = select(run_ids, manifest, runs_root)
    theorems = {i["theorem"] for i in selection["audits"] if i["theorem"]}
    audits = list(selection["audits"])
    if discover:
        known = set(run_ids)
        audits += [audit_run(r, runs_root) for r in discover_runs(theorems, runs_root) if r not in known]
    budget = budget_by_problem([a for a in audits if a["theorem"]])
    problems = violations(audits, budget)
    if problems:
        raise PackageError("; ".join(problems))
    if not selection["selected"]:
        raise PackageError("no acceptable candidate; rejections: " + json.dumps(selection["rejected"]))
    selection = selection | {"audits": audits}
    prov = provenance(selection, budget)
    out = (output_root or ROOT / "runs" / "submission-staging") / name
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for theorem, info in sorted(selection["selected"].items()):
        lines.append(json.dumps({"name": theorem, "proof": info["proof"]}, ensure_ascii=False))
    (out / "proofs.jsonl").write_text("\n".join(lines) + "\n")
    # Recompute from the file just written, so the ledger describes the bytes that would be uploaded.
    for row in map(json.loads, (out / "proofs.jsonl").read_text().splitlines()):
        prov["problems"][row["name"]]["proof_sha256"] = sha256_text(row["proof"])
    toolchains = [t for r in prov["problems"].values() for t in r["toolchains"]]
    resolved = _git(repo, "rev-parse", commit).strip()
    reproduce = reproduce_text(resolved, run_ids, submodule_pins(repo, resolved), toolchains, name)
    archive = build_archive(repo, resolved, out / "code.tar.gz", {"REPRODUCE.md": reproduce})
    prov["code_archive"] = archive
    (out / "provenance.json").write_text(json.dumps(prov, indent=2, ensure_ascii=False) + "\n")
    (out / "report.md").write_text(report(prov, resolved, name, template))
    (out / "REPRODUCE.md").write_text(reproduce)
    return out
