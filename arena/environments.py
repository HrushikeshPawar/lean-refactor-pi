"""Environment registry: which provisioned workspace holds a benchmark row's source at a pinned commit.

A row names its environment by (source, version, commit). Resolution does not depend on how a
workspace directory is named:

1. `workspaces/registry.json` may map "source@version@commit" to a directory (for copies that are not
   git checkouts);
2. otherwise any directory under `workspaces/` whose git HEAD is the commit qualifies, preferring one
   named `<source>-<version>`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACES = ROOT / "workspaces"
REGISTRY_FILE = "registry.json"


def _head(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, text=True, capture_output=True)
    return done.stdout.strip() if done.returncode == 0 else None


def discover(root: Path | None = None) -> dict[str, list[Path]]:
    """Map git commit -> workspace directories that are checked out at it."""
    root = root or WORKSPACES
    found: dict[str, list[Path]] = {}
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        if path.is_dir():
            head = _head(path)
            if head:
                found.setdefault(head, []).append(path)
    return found


def key(source: str, version: str, commit: str) -> str:
    return f"{source}@{version}@{commit}"


def resolve(source: str, version: str, commit: str, root: Path | None = None) -> Path:
    root = root or WORKSPACES
    registry_path = root / REGISTRY_FILE
    if registry_path.exists():
        mapped = json.loads(registry_path.read_text()).get(key(source, version, commit))
        if mapped and (root / mapped).is_dir():
            return root / mapped
    # The conventional directory almost always is the one: one `git rev-parse` instead of one per workspace.
    named = root / f"{source}-{version}"
    if named.is_dir() and _head(named) == commit:
        return named
    candidates = discover(root).get(commit, [])
    if candidates:
        preferred = [path for path in candidates if path.name == f"{source}-{version}"]
        return (preferred or candidates)[0]
    raise FileNotFoundError(
        f"Environment is not provisioned: {source} {version} at {commit[:12]}. Provide a checkout of that "
        f"commit under {root} (or list it in {REGISTRY_FILE}); see benchmark/derived/workspaces.tsv")


def provisioned(row: dict, root: Path | None = None) -> list[tuple[str, str, Path | None]]:
    """Every (version, commit, path-or-None) a row lists, for reporting what is missing."""
    out = []
    for pair in row["version_info"]:
        for version, commit in pair.items():
            try:
                out.append((version, commit, resolve(row["source"], version, commit, root)))
            except FileNotFoundError:
                out.append((version, commit, None))
    return out
