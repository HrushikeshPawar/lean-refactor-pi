"""Tool input schemas shared by Pi registration and inspection help.

Descriptions stay in agent-text templates. This module reads the schema
structure and renders help from that structure plus those templates.
"""

from __future__ import annotations

import json
import re
from functools import cache

from arena import text
from arena.engine import ROOT


class ToolInputError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.category = "invalid_input"
        self.reason = reason


@cache
def catalog() -> dict:
    return json.loads((ROOT / "agent-text" / "tool-schemas.json").read_text())


def registered_tools(role: str, registration: dict | None = None) -> list[dict]:
    source = catalog() if registration is None else registration
    try:
        names = source["roles"][role]
    except KeyError:
        raise ToolInputError(f"unknown actor role {role}") from None
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


def _fail(reason: str) -> None:
    raise ToolInputError(reason)


def _check_exclusive(schema: dict, request: dict) -> None:
    exclusive = list(schema.get("exclusive") or [])
    if not exclusive:
        return
    present = [key for key in exclusive if key in request]
    counted = schema.get("countsAs") or {}
    for name, keys in counted.items():
        if name not in present and all(key in request for key in keys):
            present.append(name)
    if schema.get("requireOne") and len(present) != 1:
        _fail("one of: " + " | ".join(exclusive))
    if len(present) > 1:
        _fail("one of: " + " | ".join(exclusive))


def _check_value(field: dict, value: object, path: str) -> None:
    kind = field["type"]
    if kind == "string":
        if not isinstance(value, str):
            _fail(f"{path} must be a string")
        allowed = set(field.get("enum") or [])
        pattern = field.get("pattern")
        if (allowed or pattern) and value not in allowed and not (pattern and re.search(pattern, value)):
            _fail(f"{path} is not an allowed value")
        limit = _bound(field, "maxLength")
        if limit is not None and len(value) > limit:
            _fail(f"{path} exceeds {limit} characters")
        return
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail(f"{path} must be a number")
        return
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(f"{path} must be an integer")
        return
    if kind == "array":
        if not isinstance(value, list):
            _fail(f"{path} must be an array")
        low = _bound(field, "minItems")
        high = _bound(field, "maxItems")
        if low is not None and len(value) < low:
            _fail(f"{path} needs at least {low} items")
        if high is not None and len(value) > high:
            _fail(f"{path} exceeds {high} items")
        for index, item in enumerate(value):
            _check_value(field["items"], item, f"{path}[{index}]")
        return
    if kind == "object":
        if not isinstance(value, dict):
            _fail(f"{path} must be an object")
        _check_object(field, value, path)
        return
    _fail(f"{path} has an unknown type")


def _check_modes(schema: dict, request: dict) -> None:
    modes = schema.get("modes")
    if not modes:
        return
    for mode in modes:
        required = mode.get("required") or []
        forbidden = mode.get("forbidden") or []
        if all(key in request for key in required) and not any(key in request for key in forbidden):
            return
    _fail("input does not match a documented alternative")


def _check_object(schema: dict, request: dict, path: str = "") -> None:
    properties = schema.get("properties") or {}
    unknown = sorted(set(request) - set(properties))
    if unknown:
        _fail(f"unknown input {unknown[0]}")
    _check_exclusive(schema, request)
    _check_modes(schema, request)
    for name, field in properties.items():
        if name not in request:
            if field.get("required"):
                _fail(f"{name} is required")
            continue
        _check_value(field, request[name], f"{path}.{name}".lstrip("."))


def accept_tool_input(name: str, request: object, registration: dict | None = None) -> dict:
    """Accept one documented tool input, or return invalid_input. Does not run the tool."""
    source = catalog() if registration is None else registration
    schema = source["tools"].get(name) if isinstance(source.get("tools"), dict) else None
    if schema is None:
        return {"ok": False, "category": "invalid_input", "reason": "unknown tool"}
    if not isinstance(request, dict):
        return {"ok": False, "category": "invalid_input", "reason": "request must be an object"}
    try:
        _check_object(schema, request)
    except ToolInputError as error:
        return {"ok": False, "category": error.category, "reason": error.reason}
    return {"ok": True, "accepted": True}
