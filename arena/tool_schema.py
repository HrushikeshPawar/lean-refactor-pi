"""Tool input schemas shared by Pi registration and inspection help.

Descriptions stay in agent-text templates. This module reads the schema
structure and renders help from that structure plus those templates.
Input checks stay in the live tool handlers.
"""

from __future__ import annotations

import json
from functools import cache

from arena import text
from arena.engine import ROOT


@cache
def catalog() -> dict:
    return json.loads((ROOT / "agent-text" / "tool-schemas.json").read_text())


def registered_tools(role: str, registration: dict | None = None) -> list[dict]:
    source = catalog() if registration is None else registration
    try:
        names = source["roles"][role]
    except KeyError:
        raise ValueError(f"unknown actor role {role}") from None
    return [{"name": name, **source["tools"][name]} for name in names]


def _bound(field: dict, key: str) -> int | None:
    if key in field:
        return int(field[key])
    source = field.get(f"{key}From")
    if source is None:
        return None
    return int(text.numbers()[source])


def _sentence(tool: str, field: dict) -> str:
    suffix = field.get("description")
    if not suffix:
        return ""
    return text.render(f"tools/{tool}.params.{suffix}")


def _array_span(field: dict) -> str | None:
    if field.get("type") != "array":
        return None
    low = _bound(field, "minItems")
    high = _bound(field, "maxItems")
    if low is None and high is None:
        return None
    return f"{0 if low is None else low}..{'' if high is None else high}"


def _field_lines(tool: str, properties: dict, depth: int) -> list[str]:
    lines = []
    pad = "  " * depth
    for name, field in properties.items():
        bits = [field["type"], "required" if field.get("required") else "optional"]
        span = _array_span(field)
        if span is not None:
            bits.append(span)
        length = _bound(field, "maxLength")
        if length is not None:
            bits.append(f"max {length} characters")
        if field.get("enum"):
            bits.append("values " + "|".join(field["enum"]))
        if field.get("pattern"):
            bits.append(f"pattern {field['pattern']}")
        if field.get("default") is not None:
            bits.append(f"default {field['default']}")
        line = f"{pad}{name}: {', '.join(bits)}"
        sentence = _sentence(tool, field)
        if sentence:
            line += f". {sentence}"
        lines.append(line)
        if field.get("exclusive"):
            lines.append(f"{pad}  one of: " + " | ".join(field["exclusive"]))
        if field.get("properties"):
            lines.extend(_field_lines(tool, field["properties"], depth + 1))
        items = field.get("items") or {}
        if items.get("properties"):
            lines.extend(_field_lines(tool, items["properties"], depth + 1))
    return lines


def render_tool_sections(tools: list[dict]) -> list[tuple[str, str]]:
    sections = []
    for tool in tools:
        lines = [text.render(f"tools/{tool['name']}.description")]
        if tool.get("exclusive"):
            lines.append("one of: " + " | ".join(tool["exclusive"]))
        lines.extend(_field_lines(tool["name"], tool.get("properties") or {}, 0))
        sections.append((tool["name"], "\n".join(lines)))
    return sections

