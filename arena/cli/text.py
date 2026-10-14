"""Render and budget the agent-facing text templates."""

from __future__ import annotations

import json
import re
import sys
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.table import Table

from arena import text
from arena.engine import ROOT

app = App(name="text", help="Inspect agent-facing text templates.")
_MARKERS = ("<!-- budget:start -->", "<!-- budget:end -->")


def _shown_for(key: str) -> dict[str, str]:
    normalized = key.replace("/", ".").replace("-", "_").lower()
    matches = [prefix for prefix in text.shown() if normalized == prefix or normalized.startswith(prefix + ".")]
    if not matches:
        raise ValueError(f"No shown.yaml entry for {key}")
    return text.shown()[max(matches, key=len)]


def _budget_rows() -> list[tuple[str, int, str, str]]:
    return [
        (
            key,
            len(text.template(key).split()),
            _shown_for(key)["where"],
            _shown_for(key)["per_run"],
        )
        for key in text.keys()  # noqa: SIM118
    ]


def _budget_markdown(rows: list[tuple[str, int, str, str]]) -> str:
    return "\n".join(
        [
            "| Template | Words | Where shown | Per run |",
            "| --- | ---: | --- | --- |",
            *(f"| `{key}` | {words} | {where} | {per_run} |" for key, words, where, per_run in rows),
        ]
    )


def _write_budget(rows: list[tuple[str, int, str, str]]) -> None:
    path = ROOT / "agent-text" / "README.md"
    readme = path.read_text()
    start, end = (_MARKERS[0], _MARKERS[1])
    if readme.count(start) != 1 or readme.count(end) != 1 or readme.index(start) >= readme.index(end):
        raise ValueError("agent-text/README.md must contain one ordered pair of budget markers")
    path.write_text(
        readme[: readme.index(start) + len(start)] + "\n" + _budget_markdown(rows) + "\n" + readme[readme.index(end) :]
    )


@app.command(name="render")
def render_template(
    key: str | None = None,
    var: Annotated[list[str] | None, Parameter(name="var")] = None,
    json_output: Annotated[bool, Parameter(name="json")] = False,
    list_keys: Annotated[bool, Parameter(name="list")] = False,
    skill: bool = False,
    theorem: str | None = None,
) -> int:
    try:
        if theorem is not None:
            if key is not None or list_keys or skill or var:
                raise text.TextError("--theorem cannot be combined with KEY, --list, --skill, or --var")
            from arena.cli.run import SYSTEM_PROMPT
            from arena.context import packet_sections
            from arena.skill import skill_prompt

            parts = [("system prompt", SYSTEM_PROMPT), ("skill", skill_prompt())]
            for name in ("compile", "goal", "search", "read", "finish", "scratch"):
                prefix = f"tools/{name}.params."
                descriptions = [text.render(f"tools/{name}.description")]
                descriptions.extend(
                    f"{part.removeprefix(prefix)}: {text.render(part)}"
                    for part in text.keys()  # noqa: SIM118
                    if part.startswith(prefix)
                )
                parts.append((f"tools/{name}", "\n".join(descriptions)))
            parts.extend((title or "Task", content) for title, content in packet_sections(theorem, cache_only=True))
            result = {
                "theorem": theorem,
                "parts": [
                    {"part": part, "chars": len(content), "words": len(content.split()), "text": content}
                    for part, content in parts
                ],
            }
            if json_output:
                print(json.dumps(result, ensure_ascii=False))
            else:
                for item in result["parts"]:
                    print(f"## {item['part']} ({item['chars']} chars, {item['words']} words)\n{item['text']}\n")
            return 0
        if list_keys:
            result: object = text.keys()
            if json_output:
                print(json.dumps(result))
            else:
                print("\n".join(result))
            return 0
        if skill:
            from arena.skill import skill_prompt

            rendered = skill_prompt()
            if json_output:
                print(json.dumps({"key": "skill/SKILL", "text": rendered}, ensure_ascii=False))
            else:
                print(rendered, end="")
            return 0
        if key is None:
            raise text.TextError("render requires KEY, --list, or --skill")
        values = {}
        for entry in var or []:
            if "=" not in entry:
                raise text.TextError(f"{key}: --var must be NAME=VALUE")
            name, value = entry.split("=", 1)
            if name in values:
                raise text.TextError(f"{key}: duplicate --var {name!r}")
            values[name] = (
                int(value)
                if re.fullmatch(r"-?\d+", value)
                else float(value)
                if re.fullmatch(r"-?\d+\.\d+", value)
                else value
            )
        rendered = text.render(key, **values)
        if json_output:
            print(json.dumps({"key": key, "text": rendered}, ensure_ascii=False))
        else:
            print(rendered, end="")
        return 0
    except (text.TextError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


@app.command(name="budget")
def budget(json_output: Annotated[bool, Parameter(name="json")] = False, write: bool = False) -> int:
    rows = _budget_rows()
    if write:
        _write_budget(rows)
    if json_output:
        print(
            json.dumps(
                [
                    {"template": key, "words": words, "where": where, "per_run": per_run}
                    for key, words, where, per_run in rows
                ]
            )
        )
    else:
        table = Table("Template", "Words", "Where shown", "Per run")
        for key, words, where, per_run in rows:
            table.add_row(key, str(words), where, per_run)
        Console().print(table)
    return 0
