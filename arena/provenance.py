"""What code produced a run: recorded in run-config.json so a result can be traced to the harness that made it."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _branch_with_tree(tree: str | None) -> dict:
    """The local branch whose tip has exactly this tree; the newest such tip when several do."""
    listing = _git(
        "for-each-ref", "--sort=-committerdate", "--format=%(refname:short) %(objectname) %(tree)", "refs/heads"
    )
    for line in (listing or "").splitlines():
        name, commit, branch_tree = line.split()
        if tree and branch_tree == tree and not name.startswith("gitbutler/"):
            return {"branch": name, "branch_commit": commit}
    return {"branch": None, "branch_commit": None}


def code_version(home: Path | None = None) -> dict:
    """The commit, whether tracked files differ from it, the models.yaml hash and the installed Pi version."""
    home = home or Path.home()
    status = _git("status", "--porcelain", "--untracked-files=no")
    try:
        pi_version = (home / ".pi/agent/install/current-version").read_text().strip()
    except OSError:
        pi_version = None
    head, tree = _git("rev-parse", "HEAD"), _git("rev-parse", "HEAD^{tree}")
    return {
        # With GitButler, HEAD is a synthetic workspace commit rebuilt whenever a branch changes; `branch` and
        # `branch_commit` name the real commit with the same tree (the top of the applied stack), and `tree` is the
        # content hash either way.
        "commit": head,
        "tree": tree,
        **_branch_with_tree(tree),
        "dirty": None if status is None else bool(status),
        "models_sha256": hashlib.sha256((ROOT / "models.yaml").read_bytes()).hexdigest(),
        "pi_version": pi_version,
    }
