#!/usr/bin/env python3
"""Stage a manual Arena submission under runs/submission-staging/<name>/. Never uploads anything."""

from __future__ import annotations

import sys
from pathlib import Path
from string import Template

from arena import package


def execute(
    run_ids: list[str],
    name: str,
    commit: str = "HEAD",
    template_path: Path | None = None,
    discover: bool = False,
) -> int:
    template = Template(template_path.read_text()) if template_path else None
    try:
        out = package.stage(name, run_ids, commit=commit, template=template, discover=discover)
    except package.PackageError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    print(f"staged {out}\nUpload manually; nothing was sent anywhere.")
    return 0
