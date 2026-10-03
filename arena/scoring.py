"""Read-only adapter to the pinned Arena benchmark and leaderboard scorer."""

from __future__ import annotations

import sys
from pathlib import Path


def local_proxy(name: str, tokens: int, heartbeats: int, compat: dict) -> float:
    vendor = Path(__file__).resolve().parents[1] / "vendor/arena-space"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    from benchmark import original_heartbeats, original_length
    from leaderboard import Leaderboard

    original_tokens = original_length(name)
    original_hb = original_heartbeats(name)
    if not original_tokens or not original_hb:
        raise ValueError(f"Published reference denominators are unavailable for {name}")
    row = {
        "compiled": bool(next(iter(compat.values()))["passed"]),
        "length_reduction_pct": round((original_tokens - tokens) / original_tokens * 100, 2),
        "heartbeat_reduction_pct": round((original_hb - heartbeats) / original_hb * 100, 2),
        "compat": compat,
    }
    return Leaderboard.problem_score(row)
