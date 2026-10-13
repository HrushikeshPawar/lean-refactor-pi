#!/usr/bin/env python3
"""Provision the Lean workspaces a benchmark row needs, one per pinned (version, commit).

For each version the row lists: a shared clone `workspaces/<source>-repo` gets a detached worktree
`workspaces/<source>-<version>` at the pinned commit, Mathlib's prebuilt cache is fetched, and the
row's own module is built so its imports have object files. Standalone rows (no file in a
repository, e.g. PutnamBench) pin Mathlib itself; their header only imports Mathlib, so the cache
is all they need. The environment registry finds the worktrees by their git HEAD.

    python arena provision --row "Cslib.CCS.bisimilarity_congr_choice"
    python arena provision --row putnam_1964_b2 --dry-run
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from rich.console import Console
from rich.table import Table

from arena import scheduler
from arena.engine import ROOT

WORKSPACES = ROOT / "workspaces"
LOGS = ROOT / "runs" / "provision"
MATHLIB = "https://github.com/leanprover-community/mathlib4"


def row_for(name: str) -> dict:
    for line in (ROOT / "benchmark/original/warmup.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["name"] == name:
            return row
    raise SystemExit(f"Unknown benchmark row: {name}")


def plan(row: dict) -> list[dict]:
    """One step list per pinned version; the URL falls back to Mathlib for standalone rows."""
    url = row.get("url") or MATHLIB
    repo = WORKSPACES / f"{row['source']}-repo"
    module = row["file_path"][: -len(".lean")].replace("/", ".") if row.get("file_path") else None
    steps = []
    for pair in row["version_info"]:
        for version, commit in pair.items():
            steps.append(
                {
                    "version": version,
                    "commit": commit,
                    "url": url,
                    "repo": repo,
                    "worktree": WORKSPACES / f"{row['source']}-{version}",
                    "module": module,
                }
            )
    return steps


def run(command: list[str], cwd: Path, log, timeout: int) -> None:
    log.write(f"\n$ {' '.join(command)}  (in {cwd})\n")
    log.flush()
    started = time.monotonic()
    done = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    log.write(f"[exit {done.returncode} after {time.monotonic() - started:.0f}s]\n")
    log.flush()
    if done.returncode:
        raise RuntimeError(f"{' '.join(command[:3])} failed with exit {done.returncode}; see {log.name}")


def head(path: Path) -> str | None:
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, text=True, capture_output=True)
    return done.stdout.strip() if done.returncode == 0 else None


def provision(step: dict, log, build_timeout: int, minimal_cache: bool = True, full_fallback: bool = False) -> None:
    repo, worktree, commit = step["repo"], step["worktree"], step["commit"]
    if not (repo / ".git").exists():
        run(["git", "clone", "--no-checkout", "--filter=blob:none", step["url"], str(repo)], WORKSPACES, log, 3600)
    if worktree.exists():
        if head(worktree) != commit:
            raise RuntimeError(f"{worktree} exists at another commit; move it aside first")
    else:
        run(["git", "fetch", "--quiet", "origin", commit], repo, log, 1800)
        run(["git", "worktree", "add", "--detach", str(worktree), commit], repo, log, 600)
    seed_mathlib(worktree, log)
    # Every corpus here builds on Mathlib; its prebuilt cache saves hours of compilation. On a
    # metered link fetch only the files the target module imports (and their dependencies).
    wanted = mathlib_entry_files(worktree, step["module"]) if step["module"] and minimal_cache else []
    try:
        run(["lake", "exe", "cache", "get", *wanted], worktree, log, 3600)
    except RuntimeError:
        if not wanted or not full_fallback:
            raise
        log.write("[selective cache get failed; fetching the full cache]\n")
        run(["lake", "exe", "cache", "get"], worktree, log, 3600)
    if step["module"]:
        run(["lake", "build", step["module"]], worktree, log, build_timeout)


def mathlib_clone() -> Path | None:
    """A local Mathlib clone under workspaces/ (e.g. the PutnamBench repo), to seed packages from."""
    for repo in sorted(WORKSPACES.glob("*-repo")):
        done = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, text=True, capture_output=True)
        if done.stdout.strip().rstrip("/").removesuffix(".git").endswith("leanprover-community/mathlib4"):
            return repo
    return None


def seed_mathlib(worktree: Path, log) -> None:
    """Give the workspace its Mathlib package as a worktree of the local clone at the pinned revision,
    so Lake does not download Mathlib's whole history. The worktree carries the manifest's exact URL,
    because Lake re-clones a package whose remote URL differs."""
    manifest = json.loads((worktree / "lake-manifest.json").read_text())
    package = next((p for p in manifest["packages"] if p["name"] == "mathlib"), None)
    target = worktree / ".lake" / "packages" / "mathlib"
    source = mathlib_clone()
    if package is None or source is None or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "fetch", "--quiet", "origin", package["rev"]], source, log, 1800)
    run(["git", "config", "extensions.worktreeConfig", "true"], source, log, 60)
    run(["git", "worktree", "add", "--detach", str(target), package["rev"]], source, log, 1800)
    run(["git", "config", "--worktree", "remote.origin.url", package["url"]], target, log, 60)


def mathlib_entry_files(worktree: Path, module: str) -> list[str]:
    """Mathlib modules the target module's local import closure imports directly."""
    pattern = re.compile(r"^\s*(?:public\s+|private\s+)?(?:meta\s+)?import\s+(?:all\s+)?([\w.«»]+)", re.M)
    local = module.split(".")[0]
    seen: set[str] = set()
    entries: set[str] = set()
    todo = [module]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = worktree / (name.replace(".", "/") + ".lean")
        if not path.exists():
            continue
        for imported in pattern.findall(path.read_text(errors="ignore")):
            if imported.split(".")[0] == local:
                todo.append(imported)
            elif imported.startswith("Mathlib"):
                # Module names, not file paths: the cache tool resolves paths from the
                # downstream project's root, where Mathlib's files do not exist.
                entries.add(imported)
    return sorted(entries)


# Stages in order, with the share of total time each usually takes.
STAGES = [
    ("clone", "git clone", 0.05),
    ("checkout", "git worktree add --detach", 0.05),
    ("seed Mathlib", "remote.origin.url", 0.05),
    ("Mathlib cache", "lake exe cache get", 0.35),
    ("build", "lake build", 0.50),
]
DEFAULT = ["cslib-v4.33.0-rc2", "cslib-v4.32.0", "cslib-v4.31.0", "physlib-v4.32.0"]
BAR = 28


def status(name: str) -> tuple[float, str, bool, bool]:
    """(fraction done, what is happening, finished, failed) for one environment."""
    log = LOGS / f"{name}.log"
    if not log.exists():
        return 0.0, "waiting to start", False, False
    text = log.read_text(errors="ignore")
    # Only the latest attempt counts; earlier, interrupted attempts stay in the log above it.
    text = text[text.rfind("=== provisioning") :] if "=== provisioning" in text else text
    commands = list(re.finditer(r"^\$ (.*)$", text, re.M))
    if not commands:
        return 0.0, "starting", False, False
    last = commands[-1]
    tail = text[last.end() :]
    stage_index = max((i for i, (_, marker, _) in enumerate(STAGES) if marker in last[1]), default=0)
    done_share = sum(share for _, _, share in STAGES[:stage_index])
    share = STAGES[stage_index][2]
    exit_code = re.search(r"\[exit (\d+) after (\d+)s\]", tail)
    if exit_code and exit_code[1] != "0":
        return done_share, f"FAILED at {STAGES[stage_index][0]} (see {log.name})", True, True
    if exit_code and STAGES[stage_index][0] == "build":
        return 1.0, f"done (build {exit_code[2]}s)", True, False
    inner, detail = 0.0, ""
    if STAGES[stage_index][0] == "build":
        steps = re.findall(r"\[(\d+)/(\d+)\]", tail)
        if steps:
            current, total = map(int, steps[-1])
            inner, detail = current / total, f" {current}/{total} modules"
    elif STAGES[stage_index][0] == "Mathlib cache":
        if "downloading https://releases.lean-lang.org" in tail and "installing" not in tail:
            detail = " (downloading Lean toolchain)"
        elif "cloning" in tail and "Built Cache" not in tail:
            detail = " (fetching small dependencies)"
        elif "Decompress" in tail or "unpack" in tail.lower():
            inner, detail = 0.8, " (unpacking)"
        else:
            inner, detail = 0.4, " (downloading cache files)"
    elif exit_code:
        inner = 1.0
    return done_share + share * inner, f"{STAGES[stage_index][0]}{detail}", False, False


def render(names: list[str]) -> tuple[str, bool]:
    lines, overall, finished = [], 0.0, True
    for name in names:
        fraction, what, done, failed = status(name)
        overall += fraction
        finished &= done
        filled = int(BAR * fraction)
        mark = "✗" if failed else "✓" if done else "…"
        lines.append(f"{mark} {name:20} [{'█' * filled}{'·' * (BAR - filled)}] {100 * fraction:3.0f}%  {what}")
    overall /= max(1, len(names))
    filled = int(BAR * overall)
    lines.append(
        f"\n  {'overall':20} [{'█' * filled}{'·' * (BAR - filled)}] {100 * overall:3.0f}%  "
        f"({time.strftime('%H:%M:%S')})"
    )
    return "\n".join(lines), finished


@dataclass(frozen=True)
class ProvisionOptions:
    row: str | None = None
    build_timeout: int = 4 * 3600
    full_cache: bool = False
    allow_full_fallback: bool = False
    version: list[str] = field(default_factory=list)
    dry_run: bool = False
    progress: bool = False
    watch: bool = False
    only: list[str] = field(default_factory=list)
    json_output: Annotated[bool, Parameter(name="json")] = field(default=False, metadata={"flag": "--json"})


def execute(options: ProvisionOptions) -> int:
    if options.dry_run:
        return _execute(options)
    active = scheduler.holder()
    if active is not None:
        _campaign_lock_error(active)
        return 1
    lock = scheduler.CampaignLock()
    try:
        lock.acquire({"prefix": f"provision:{options.row or 'progress'}", "argv": sys.argv})
    except scheduler.CampaignLocked:
        _campaign_lock_error(scheduler.holder() or {})
        return 1
    try:
        return _execute(options)
    finally:
        lock.release()


def _campaign_lock_error(campaign: dict) -> None:
    print(
        f"a campaign (pid {campaign.get('pid', '?')}, prefix {campaign.get('prefix', '?')}, "
        f"started {campaign.get('started', '?')}) holds the lock; provisioning is refused",
        file=sys.stderr,
    )


def _execute(options: ProvisionOptions) -> int:
    if options.progress:
        names = options.only or DEFAULT
        console = Console()
        while True:
            readings = [(name, *status(name)) for name in names]
            finished = all(item[3] for item in readings)
            if options.json_output:
                if not options.watch or finished:
                    print(
                        json.dumps(
                            {
                                "items": [
                                    {
                                        "name": name,
                                        "fraction": fraction,
                                        "detail": detail,
                                        "finished": done,
                                        "failed": failed,
                                    }
                                    for name, fraction, detail, done, failed in readings
                                ],
                                "finished": finished,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            else:
                if options.watch:
                    console.clear()
                table = Table(title="Workspace provisioning")
                table.add_column("Environment")
                table.add_column("Progress", justify="right")
                table.add_column("Status")
                for name, fraction, detail, done, failed in readings:
                    table.add_row(
                        name, f"{100 * fraction:.0f}%", ("FAILED · " if failed else "done · " if done else "") + detail
                    )
                console.print(table)
            if not options.watch or finished:
                return 0
            time.sleep(3)
    if not options.row:
        print("--row is required unless --progress is set", file=sys.stderr)
        return 2
    row = row_for(options.row)
    steps = [step for step in plan(row) if not options.version or step["version"] in options.version]
    for step in steps:
        print(
            f"{row['source']} {step['version']} {step['commit'][:12]} -> {step['worktree'].relative_to(ROOT)}"
            f"  build {step['module'] or '(Mathlib cache only)'}"
        )
    if options.dry_run:
        return 0
    LOGS.mkdir(parents=True, exist_ok=True)
    failed = 0
    for step in steps:
        log_path = LOGS / f"{row['source']}-{step['version']}.log"
        with log_path.open("a") as log:
            log.write(f"\n=== provisioning {step['worktree'].name} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            try:
                provision(
                    step,
                    log,
                    options.build_timeout,
                    not options.full_cache,
                    options.allow_full_fallback,
                )
                print(f"ok      {step['worktree'].name}", flush=True)
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                failed += 1
                print(f"FAILED  {step['worktree'].name}: {error}", file=sys.stderr, flush=True)
    return 1 if failed else 0


cli_execute = execute
