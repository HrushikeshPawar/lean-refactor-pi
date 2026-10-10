"""The `arena` command line.

Commands that still live in `tools/` are thin pass-throughs: every argument after the command name goes to the
tool unchanged, so `arena run --help` prints the tool's own help. Ticket 04 moves the remaining tools in.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

ROOT = Path(__file__).resolve().parents[2]

app = App(name="arena", help="Lean Refactor Arena harness.", result_action="return_value")

Tokens = Annotated[str, Parameter(allow_leading_hyphen=True)]


def load_env(path: Path = ROOT / ".env") -> list[str]:
    """Export `KEY=value` lines from `path` that the shell has not already set; return the keys exported.

    Values are never printed. Blank lines and `#` comments are skipped; surrounding quotes are stripped.
    """
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    exported = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            exported.append(key)
    return exported


def _delegate(module: str, command: str, tokens: tuple[str, ...]) -> int:
    """Run `tools.<module>.main()` as if it had been started with `tokens` on its command line."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    main = importlib.import_module(f"tools.{module}").main
    argv = sys.argv
    sys.argv = [f"arena {command}", *tokens]
    try:
        return main() or 0
    except SystemExit as stop:  # argparse --help and usage errors
        return stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    finally:
        sys.argv = argv


@app.command(help_flags=[])
def run(*tokens: Tokens) -> int:
    """Run one budgeted proof session through Pi (loads .env first)."""
    load_env()
    return _delegate("run_pi_budgeted", "run", tokens)


@app.command(help_flags=[])
def campaign(*tokens: Tokens) -> int:
    """Run a campaign: rows x models x replicates, --jobs at a time (loads .env first)."""
    load_env()
    return _delegate("run_campaign", "campaign", tokens)


@app.command(help_flags=[])
def check(*tokens: Tokens) -> int:
    """Check one candidate file with the forbidden filter and the official checker."""
    return _delegate("arena_check", "check", tokens)


@app.command(name="eval", help_flags=[])
def eval_(*tokens: Tokens) -> int:
    """Evaluate one proof of a benchmark row and print its metrics."""
    return _delegate("arena_eval", "eval", tokens)


@app.command(show=False, help_flags=[])
def protocol(*tokens: Tokens) -> int:
    """JSON protocol between the Pi extension and one campaign (not for people)."""
    return _delegate("arena_campaign", "protocol", tokens)


def main() -> None:
    result = app()
    sys.exit(result if isinstance(result, int) else 0)
