"""Prepare a competition submission. The owner uploads the files; nothing here contacts the network."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from arena.engine import ROOT
from arena.package import (
    CEILING_USD,
    MANIFEST,
    RUNS,
    _git,
    build_archive,
    load_manifest,
    reproduce_text,
    submodule_pins,
)
from arena.submit import ledger
from arena.submit.diff import diff_submissions
from arena.submit.emit import blocked, manifest_document, write
from arena.submit.gates import cold_check as default_cold_check
from arena.submit.recombine import recombine
from arena.submit.select import SubmitError, load_previous, load_runs, resolve_runs, select_rows

__all__ = ["SubmissionResult", "SubmitError", "build_submission"]

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass
class SubmissionResult:
    directory: Path
    code: int
    worse: list[str] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)


def _replace(directory: Path, overwrite: bool) -> None:
    if directory.exists():
        if not overwrite:
            raise SubmitError(f"{directory} already exists")
        shutil.rmtree(directory)
    directory.mkdir(parents=True)


def build_submission(
    name: str,
    runs: list[str],
    previous: str | None = None,
    max_cold: int = 5,
    hybrids: bool = True,
    max_hybrids: int = 20,
    ceiling_usd: float = CEILING_USD,
    discover: bool = False,
    archive: bool = False,
    overwrite: bool = False,
    cold_check=None,
    memory_reader=None,
    runs_root: Path = RUNS,
    output_root: Path | None = None,
    manifest_path: Path = MANIFEST,
    repo: Path = ROOT,
    progress: Callable[[dict], None] | None = None,
) -> SubmissionResult:
    """Select, gate and write `runs/submission/<name>/`. Exit code 0 passes; 1 is blocked.

    `cold_check` and `memory_reader` are injection points. The default cold check runs Lean,
    one proof at a time. A blocked submission writes only `blocked.json`, beside the files of
    an existing submission of the same name when there is one (it is left intact).
    """
    if not _NAME.fullmatch(name):
        raise SubmitError("invalid submission name")
    if max_cold < 1:
        raise SubmitError("max_cold must be at least 1")
    if max_hybrids < 0:
        raise SubmitError("max_hybrids cannot be negative")
    destination_root = output_root or (ROOT / "runs" / "submission")
    destination = destination_root / name
    if destination.exists() and not overwrite:
        raise SubmitError(f"{destination} already exists")
    manifest = load_manifest(manifest_path)
    run_ids = resolve_runs(list(runs), runs_root)
    previous_rows: dict[str, dict] = {}
    previous_dir = None
    if previous is not None:
        previous_dir = destination_root / previous
        if not previous_dir.is_dir():
            raise SubmitError(f"no previous submission {previous}")
        previous_rows = load_previous(previous_dir)
    checker = cold_check or (lambda theorem, proof: default_cold_check(theorem, proof, memory_reader=memory_reader))
    loaded, rejected_runs = load_runs(run_ids, runs_root)
    selection = select_rows(manifest, loaded, checker, max_cold, previous_rows, progress)
    hybrid_attempts = None
    if hybrids:
        chosen, hybrid_attempts = recombine(selection.rows, manifest, loaded, max_hybrids, checker)
    else:
        chosen = selection.rows
    named = set(run_ids)
    problems, spend_blocks = ledger.build(chosen, runs_root, ceiling_usd, discover, named)
    blocked_rows = list(selection.blocked) + spend_blocks
    # Unknown provenance rejects the run from the pool. It is reported on the file that gets
    # written, and it blocks the file only when a row is already blocked.
    if blocked_rows:
        for item in rejected_runs:
            blocked_rows.append(
                {
                    "row": None,
                    "candidate": None,
                    "reasons": [f"{item['run_id']}: {reason}" for reason in item["reasons"]],
                }
            )
    if blocked_rows:
        # A blocked build never removes an earlier good submission: `blocked.json` goes beside
        # its files, and the next passing build replaces the whole directory.
        blocked(destination, blocked_rows)
        return SubmissionResult(destination, 1, [], blocked_rows, selection.missing, [])
    provenance = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "ceiling_usd": ceiling_usd,
        "runs": run_ids,
        "problems": problems,
        "missing": selection.missing,
        "rejected": selection.rejected,
        "rejected_runs": rejected_runs,
    }
    document = manifest_document(
        name, run_ids, chosen, problems, selection.rejected, selection.missing, rejected_runs, hybrid_attempts
    )
    diff = diff_submissions(chosen, previous_dir)
    _replace(destination, overwrite)
    baseline_rows = selection.rows if any(row.get("origin") == "submit_merge" for row in chosen) else None
    write(destination, chosen, document, provenance, diff, baseline_rows)
    if archive:
        commit = _git(repo, "rev-parse", "HEAD").strip()
        toolchains = [
            version
            for row in chosen
            for pair in row.get("source_versions") or []
            for version in pair[:1]
            if isinstance(version, str)
        ]
        text = reproduce_text(commit, run_ids, submodule_pins(repo, commit), toolchains, name)
        (destination / "REPRODUCE.md").write_text(text, encoding="utf-8")
        build_archive(repo, commit, destination / "code.tar.gz", {"REPRODUCE.md": text})
    return SubmissionResult(destination, 0, diff["worse"], [], selection.missing, chosen)
