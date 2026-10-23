#!/usr/bin/env python3
"""Reproduction CLI; Pi extension is the model-facing interface."""

import json
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.table import Table

from arena.engine import evaluate


def execute(name: str, proof_file: Path, mode: Literal["fast", "full"] = "fast", json_output: bool = False) -> int:
    try:
        result = evaluate(
            name, proof_file.read_text(), mode, request_class="full_check" if mode == "full" else "sol_foreground"
        )
    except (ValueError, FileNotFoundError) as exc:
        failure = {"ok": False, "name": name, "mode": mode, "error": str(exc)}
        if json_output:
            print(json.dumps(failure, ensure_ascii=False))
        else:
            Console(stderr=True).print(f"[red]{name}: {exc}[/red]")
        return 2
    if json_output:
        print(json.dumps(result, ensure_ascii=False))
    else:
        table = Table(title=f"Evaluation: {name} ({mode})")
        table.add_column("Metric")
        table.add_column("Value")
        for key, value in result.items():
            table.add_row(
                str(key), json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            )
        Console().print(table)
    return 0
