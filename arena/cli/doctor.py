"""Check local pins and generated data before spending on a run."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from arena import models, traces
from arena.engine import BENCHMARK, ROOT, problem, validate_proof, versions

Status = tuple[str, str, str]


def _git(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False, timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _pin_pi_version() -> str:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return str(config["tool"]["arena"]["pins"]["pi_version"])


def _vendor_details(name: str) -> tuple[str, bool]:
    path = ROOT / "vendor" / name
    if not path.is_dir():
        raise RuntimeError("submodule directory is missing")
    actual = _git("-C", str(path), "rev-parse", "HEAD")
    tree = _git("ls-tree", "HEAD", f"vendor/{name}")
    expected = tree.split()[2] if tree else ""
    dirty = bool(_git("-C", str(path), "status", "--porcelain"))
    detail = f"{actual[:7]} (recorded {expected[:7] or 'missing'})"
    if actual != expected:
        detail += "; checkout differs from recorded gitlink"
    if dirty:
        detail += "; working tree is dirty"
    return detail, actual == expected and not dirty


def _check_pins() -> Status:
    pinned = _pin_pi_version()
    from arena.provenance import code_version

    actual = code_version().get("pi_version")
    if actual is None:
        return "Pins", "warn", f"Pi is not installed (pinned {pinned})"
    status = "ok" if actual == pinned else "fail"
    return "Pins", status, f"Pi {actual} (pinned {pinned})"


def _check_langfuse_pin() -> Status:
    return "Langfuse plugin version", "ok", traces.PLUGIN_VERSION


def _check_vendors() -> Status:
    details, ok = [], True
    for name in ("arena-space", "lean-refactor"):
        try:
            detail, clean = _vendor_details(name)
            details.append(f"{name}: {detail}")
            ok &= clean
        except Exception as error:
            details.append(f"{name}: {error}")
            ok = False
    return "Vendor submodules", "ok" if ok else "fail", "; ".join(details)


def _check_benchmark_hash() -> Status:
    sums = ROOT / "benchmark/SHA256SUMS"
    target = ROOT / "benchmark/original/warmup.jsonl"
    try:
        expected = next(
            line.split()[0]
            for line in sums.read_text().splitlines()
            if line.strip().endswith("benchmark/original/warmup.jsonl")
        )
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
    except (OSError, StopIteration, IndexError) as error:
        return "Benchmark hash", "fail", f"missing hash entry or benchmark file: {error}"
    ok = actual == expected
    return "Benchmark hash", "ok" if ok else "fail", f"{actual} (expected {expected})"


def _check_token_counter() -> Status:
    mismatches = []
    try:
        rows = [json.loads(line) for line in BENCHMARK.read_text().splitlines() if line.strip()]
        for row in rows:
            try:
                actual = validate_proof(row, row["src"])
            except Exception as error:
                mismatches.append(f"{row.get('name', '?')}: {error}")
                continue
            if actual != row["proof_length"]:
                mismatches.append(f"{row['name']}: {actual} != {row['proof_length']}")
    except Exception as error:
        return "Official token counter", "fail", str(error)
    return "Official token counter", "fail" if mismatches else "ok", "; ".join(mismatches) or f"{len(rows)} rows match"


def _check_prices() -> Status:
    try:
        problems = models.catalog_price_problems()
    except Exception as error:
        return "Model price table", "fail", str(error)
    return "Model price table", "fail" if problems else "ok", "\n".join(problems) or "Pi catalog prices match"


def _check_plugin() -> Status:
    if not traces.INSTALLED_PLUGIN.exists():
        return "Langfuse plugin", "warn", "Langfuse plugin not installed (optional)"
    try:
        problems = traces.plugin_problems()
    except Exception as error:
        return "Langfuse plugin", "warn", str(error)
    return "Langfuse plugin", "warn" if problems else "ok", "; ".join(problems) or "patched plugin matches"


def _check_measure_versions() -> Status:
    path = ROOT / "benchmark/derived/measure-versions.json"
    if not path.exists():
        return "Measure versions", "ok", "no overrides"
    try:
        overrides = json.loads(path.read_text())
        for name, version in overrides.items():
            row = problem(name)
            row_versions = [item[0] for item in versions(row)]
            if version not in row_versions:
                return "Measure versions", "fail", f"{name}: {version} is not one of {row_versions}"
    except Exception as error:
        return "Measure versions", "fail", str(error)
    return "Measure versions", "ok", f"{len(overrides)} overrides are valid"


def checks() -> list[Status]:
    """Return the seven health checks; machine-dependent helpers remain replaceable in tests."""
    result = []
    for check in (
        _check_pins,
        _check_langfuse_pin,
        _check_vendors,
        _check_benchmark_hash,
        _check_token_counter,
        _check_prices,
        _check_plugin,
        _check_measure_versions,
    ):
        try:
            result.append(check())
        except Exception as error:
            result.append((check.__name__.removeprefix("_check_").replace("_", " ").title(), "fail", str(error)))
    return result


@dataclass(frozen=True)
class DoctorOptions:
    """Options for local health checks."""

    json: bool = False
    apply_langfuse_plugin: bool = False


def execute(options: DoctorOptions) -> int:
    if options.apply_langfuse_plugin:
        try:
            traces.apply_plugin()
        except Exception as error:
            results = [("Langfuse plugin", "warn", f"patch not applied: {error}")]
            results.extend(checks())
        else:
            results = checks()
    else:
        results = checks()
    ok = all(status != "fail" for _, status, _ in results)
    if options.json:
        print(
            json.dumps(
                {
                    "checks": [{"name": name, "status": status, "detail": detail} for name, status, detail in results],
                    "ok": ok,
                }
            )
        )
    else:
        table = Table(title="Arena doctor")
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Detail")
        for name, status, detail in results:
            table.add_row(name, status, detail)
        Console().print(table)
    return 0 if ok else 1
