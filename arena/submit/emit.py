"""Write the submission directory. A blocked file gets `blocked.json` and nothing else."""

from __future__ import annotations

import json
from pathlib import Path

from arena.package import sha256_text


def _dump(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def blocked(directory: Path, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _dump(directory / "blocked.json", rows)


def manifest_document(
    name: str,
    run_ids: list[str],
    rows: list[dict],
    problems: dict[str, dict],
    rejected: list[dict],
    missing: list[str],
    rejected_runs: list[dict] | None = None,
    hybrid_attempts: list[dict] | None = None,
) -> dict:
    attempts_by_name = {item["name"]: item["attempts"] for item in hybrid_attempts or []}
    described = []
    for row in rows:
        problem = problems[row["name"]]
        entry = {
            "name": row["name"],
            "source": row["source"],
            "run_id": row.get("run_id"),
            "candidate_id": row.get("candidate_id"),
            "graph_id": row.get("graph_id"),
            "label": row.get("label"),
            "proxy": row.get("proxy"),
            "recorded_proxy": row.get("recorded_proxy"),
            "axes": row.get("axes") or {},
            "tokens": row.get("tokens"),
            "heartbeats": row.get("heartbeats"),
            "cold": row.get("passed") or {},
            "spend_usd": problem["spend_usd"],
            "contributing_runs": problem["run_ids"],
        }
        if "code" in problem:
            entry["code"] = problem["code"]
        if row.get("origin") == "submit_merge":
            entry["origin"] = "submit_merge"
            entry["hybrid_id"] = row.get("hybrid_id")
            entry["merged_from"] = row.get("merged_from") or []
        if hybrid_attempts is not None:
            entry["hybrid_attempts"] = attempts_by_name.get(row["name"], [])
        described.append(entry)
    return {
        "name": name,
        "runs": run_ids,
        "rows": described,
        "rejected": rejected,
        "rejected_runs": rejected_runs or [],
        "missing": missing,
    }


def _markdown(document: dict) -> str:
    lines = [f"# Submission {document['name']}", "", "Runs: " + (", ".join(document["runs"]) or "none"), ""]
    for row in document["rows"]:
        axes = row.get("axes") or {}
        parts = ", ".join(f"{key} {value}" for key, value in axes.items()) or "unrecorded"
        cold = ", ".join(f"{version} {'pass' if ok else 'fail'}" for version, ok in (row.get("cold") or {}).items())
        code = row["code"]["commit"] if isinstance(row.get("code"), dict) and row["code"].get("commit") else "absent"
        lines.extend(
            [
                f"## {row['name']}",
                "",
                f"- source: {row['source']} run `{row.get('run_id')}` candidate `{row.get('graph_id')}` ({row.get('label')})",
                f"- candidate id: `{row.get('candidate_id')}`",
                f"- proxy: {row.get('proxy')} (recorded {row.get('recorded_proxy')}; {parts})",
                f"- tokens: {row.get('tokens')}; heartbeats: {row.get('heartbeats')}",
                f"- cold: {cold or 'unrecorded'}",
                f"- spend: ${row.get('spend_usd')} across {', '.join(row.get('contributing_runs') or []) or 'no runs'}",
                f"- code: {code}",
            ]
        )
        if row.get("origin") == "submit_merge":
            lines.append(f"- hybrid: `{row.get('hybrid_id')}`")
            lines.extend(
                f"- merged from: `{item.get('run')}` / `{item.get('node')}` / `{item.get('step')}`"
                for item in row.get("merged_from") or []
            )
        if "hybrid_attempts" in row:
            attempts = row.get("hybrid_attempts") or []
            if not attempts:
                lines.append("- hybrid attempts: none")
            for index, attempt in enumerate(attempts, 1):
                reasons = "; ".join((attempt.get("gate_result") or {}).get("reasons") or []) or "passed"
                lines.append(
                    f"- hybrid attempt {index}: base `{attempt.get('base_node')}`, donor run "
                    f"`{attempt.get('donor_run')}` node `{attempt.get('donor_node')}` step "
                    f"{attempt.get('step_index')}, saving {attempt.get('token_saving')} tokens; "
                    f"gate {reasons}; proxy {attempt.get('settled_proxy')}; "
                    f"{attempt.get('reason')}"
                )
        lines.append("")
    lines.extend(["## Rejected candidates", ""])
    if document["rejected"]:
        lines.extend(
            f"- {item.get('row')} {item.get('candidate')}: {'; '.join(item.get('reasons') or [])}"
            for item in document["rejected"]
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Rejected runs", ""])
    if document.get("rejected_runs"):
        lines.extend(
            f"- {item.get('run_id')}: {'; '.join(item.get('reasons') or [])}" for item in document["rejected_runs"]
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Missing", ""])
    lines.extend(f"- {name}" for name in document["missing"])
    if not document["missing"]:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write(
    directory: Path,
    rows: list[dict],
    manifest: dict,
    provenance: dict,
    diff: dict,
    no_hybrids: list[dict] | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    proofs = [
        json.dumps({"name": row["name"], "proof": row["proof"]}, ensure_ascii=False)
        for row in sorted(rows, key=lambda row: row["name"])
    ]
    (directory / "proofs.jsonl").write_text(("\n".join(proofs) + "\n") if proofs else "", encoding="utf-8")
    if no_hybrids is not None:
        baseline = [
            json.dumps({"name": row["name"], "proof": row["proof"]}, ensure_ascii=False)
            for row in sorted(no_hybrids, key=lambda row: row["name"])
        ]
        (directory / "proofs-no-hybrids.jsonl").write_text(
            ("\n".join(baseline) + "\n") if baseline else "", encoding="utf-8"
        )
    for row in rows:
        if row.get("origin") == "submit_merge":
            hybrids = directory / "hybrids"
            hybrids.mkdir(exist_ok=True)
            accepted = row.get("accepted_hybrids") or [
                {"hybrid_id": row.get("hybrid_id") or row["name"], "proof": row["proof"]}
            ]
            for hybrid in accepted:
                (hybrids / f"{hybrid['hybrid_id']}.lean").write_text(hybrid["proof"], encoding="utf-8")
    for line in (directory / "proofs.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        provenance["problems"][row["name"]]["proof_sha256"] = sha256_text(row["proof"])
    _dump(directory / "manifest.json", manifest)
    (directory / "MANIFEST.md").write_text(_markdown(manifest), encoding="utf-8")
    _dump(directory / "provenance.json", provenance)
    _dump(directory / "diff.json", {key: value for key, value in diff.items() if key != "text"})
    (directory / "diff.md").write_text(diff["text"], encoding="utf-8")
