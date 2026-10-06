#!/usr/bin/env python3
"""Provision the Lean workspaces a benchmark row needs, one per pinned (version, commit).

For each version the row lists: a shared clone `workspaces/<source>-repo` gets a detached worktree
`workspaces/<source>-<version>` at the pinned commit, Mathlib's prebuilt cache is fetched, and the
row's own module is built so its imports have object files. Standalone rows (no file in a
repository, e.g. PutnamBench) pin Mathlib itself; their header only imports Mathlib, so the cache
is all they need. The environment registry finds the worktrees by their git HEAD.

    python tools/provision_workspace.py --row "Cslib.CCS.bisimilarity_congr_choice"
    python tools/provision_workspace.py --row putnam_1964_b2 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
    module = row["file_path"][:-len(".lean")].replace("/", ".") if row.get("file_path") else None
    steps = []
    for pair in row["version_info"]:
        for version, commit in pair.items():
            steps.append({"version": version, "commit": commit, "url": url, "repo": repo,
                          "worktree": WORKSPACES / f"{row['source']}-{version}", "module": module})
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--row", required=True, help="Benchmark row name")
    parser.add_argument("--build-timeout", type=int, default=4 * 3600, help="Seconds allowed for one lake build")
    parser.add_argument("--full-cache", action="store_true", help="Fetch the whole Mathlib cache, not only the imports")
    parser.add_argument("--allow-full-fallback", action="store_true",
                        help="If the selective cache fetch fails, fetch the whole cache (large download)")
    parser.add_argument("--version", action="append", help="Only these versions (default: every listed one)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    row = row_for(args.row)
    steps = [step for step in plan(row) if not args.version or step["version"] in args.version]
    for step in steps:
        print(f"{row['source']} {step['version']} {step['commit'][:12]} -> {step['worktree'].relative_to(ROOT)}"
              f"  build {step['module'] or '(Mathlib cache only)'}")
    if args.dry_run:
        return 0
    LOGS.mkdir(parents=True, exist_ok=True)
    failed = 0
    for step in steps:
        log_path = LOGS / f"{row['source']}-{step['version']}.log"
        with log_path.open("a") as log:
            log.write(f"\n=== provisioning {step['worktree'].name} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            try:
                provision(step, log, args.build_timeout, not args.full_cache, args.allow_full_fallback)
                print(f"ok      {step['worktree'].name}", flush=True)
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                failed += 1
                print(f"FAILED  {step['worktree'].name}: {error}", file=sys.stderr, flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
