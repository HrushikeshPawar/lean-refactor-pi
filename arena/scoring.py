"""Read-only adapter to the pinned Arena benchmark and leaderboard scorer."""

from __future__ import annotations

from arena import vendor

# The score of the reference proof itself: no reduction on either axis and full compatibility.
REFERENCE_SCORE = round(100 / 3, 2)


def reference(name: str) -> tuple[int, int]:
    """Published denominators (proof tokens, heartbeats) for one benchmark row."""
    module = vendor.benchmark()
    tokens, heartbeats = module.original_length(name), module.original_heartbeats(name)
    if not tokens or not heartbeats:
        raise ValueError(f"Published reference denominators are unavailable for {name}")
    return tokens, heartbeats


def local_proxy(name: str, tokens: int, heartbeats: int, compat: dict) -> float:
    Leaderboard = vendor.leaderboard()

    original_tokens, original_hb = reference(name)
    row = {
        "compiled": bool(next(iter(compat.values()))["passed"]),
        "length_reduction_pct": round((original_tokens - tokens) / original_tokens * 100, 2),
        "heartbeat_reduction_pct": round((original_hb - heartbeats) / original_hb * 100, 2),
        "compat": compat,
    }
    return Leaderboard.problem_score(row)


def exchange_rates(name: str, total_versions: int) -> dict:
    """What one unit of each axis is worth, from this row's pinned denominators.

    The score is the mean of three percentages, so each axis contributes one
    third of its own percentage.
    """
    tokens, heartbeats = reference(name)
    per_token = 100 / tokens / 3
    per_heartbeat = 100 / heartbeats / 3
    per_version = 100 / 3 / total_versions
    return {
        "points_per_token": round(per_token, 3),
        "points_per_100_heartbeats": round(per_heartbeat * 100, 3),
        "points_per_lost_version": round(per_version, 2),
        "heartbeats_per_token": round(per_token / per_heartbeat),
        "tokens_per_lost_version": round(per_version / per_token),
        "reference_tokens": tokens,
        "reference_heartbeats": heartbeats,
        "versions": total_versions,
    }


def metrics(
    name: str, tokens: int | None, heartbeats: int | None, compat: dict, mode: str, total_versions: int
) -> dict:
    """Score breakdown for one evaluation.

    Fast and probe evaluations check one toolchain, so their proxy is an
    estimate that assumes every unchecked version also compiles.
    """
    primary_passed = bool(compat) and bool(next(iter(compat.values())).get("passed"))
    block: dict = {
        "tokens": tokens,
        "heartbeats": heartbeats,
        "compat": {version: bool(item.get("passed")) for version, item in compat.items()},
        "compiled": primary_passed,
    }
    if not primary_passed or tokens is None or heartbeats is None:
        return block
    reference_tokens, reference_heartbeats = reference(name)
    token_pct = round((reference_tokens - tokens) / reference_tokens * 100, 2)
    heartbeat_pct = round((reference_heartbeats - heartbeats) / reference_heartbeats * 100, 2)
    full = mode == "full" and len(compat) == total_versions
    passed = sum(bool(item.get("passed")) for item in compat.values())
    compat_pct = round(passed / total_versions * 100, 2) if full else 100.0
    block["axes"] = {
        "tokens": {
            "value": tokens,
            "reference": reference_tokens,
            "reduction_pct": token_pct,
            "contribution": round(token_pct / 3, 2),
        },
        "heartbeats": {
            "value": heartbeats,
            "reference": reference_heartbeats,
            "reduction_pct": heartbeat_pct,
            "contribution": round(heartbeat_pct / 3, 2),
        },
        "compat": {
            "passed": passed if full else None,
            "checked": len(compat),
            "total": total_versions,
            "pct": compat_pct,
            "contribution": round(compat_pct / 3, 2),
        },
    }
    value = round((token_pct + heartbeat_pct + compat_pct) / 3, 2)
    reference_proxy = REFERENCE_SCORE
    if full:
        block["proxy"] = local_proxy(name, tokens, heartbeats, compat)
        block["deltas"] = {
            "vs_reference": {
                "tokens": tokens - reference_tokens,
                "heartbeats": heartbeats - reference_heartbeats,
                "proxy": round(block["proxy"] - reference_proxy, 2),
            }
        }
    else:
        block["estimated_proxy"] = value
        block["assumes_full_compat"] = True
        block["deltas"] = {
            "vs_reference": {
                "tokens": tokens - reference_tokens,
                "heartbeats": heartbeats - reference_heartbeats,
                "proxy": round(value - reference_proxy, 2),
            }
        }
    return block
