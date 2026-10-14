"""Strict, dependency-free renderer for the shared agent text templates."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)(?::(d|\.\df|g))?\}")
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")


class TextError(ValueError):
    """Invalid template, placeholder, or supplied render value."""


def _directory() -> Path:
    return Path(os.environ.get("ARENA_TEXT_DIR", ROOT / "agent-text"))


def _parse_yaml(text: str, key: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-2, root)]
    i = 0
    source_lines = text.splitlines()
    while i < len(source_lines):
        raw_line = source_lines[i]
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            i += 1
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent % 2 or ":" not in line:
            raise TextError(f"{key}: invalid YAML line {line!r}")
        name, raw = line.split(":", 1)
        if not _NAME.fullmatch(name):
            raise TextError(f"{key}: invalid YAML key {name!r}")
        while stack[-1][0] >= indent:
            stack.pop()
        if indent != stack[-1][0] + 2:
            raise TextError(f"{key}: invalid YAML indentation")
        parent = stack[-1][1]
        raw = raw.strip()
        if not raw:
            value: dict = {}
            parent[name] = value
            stack.append((indent, value))
        elif raw in ("|", "|-"):
            block_lines = []
            i += 1
            while i < len(source_lines):
                block_line = source_lines[i]
                block_indent = len(block_line) - len(block_line.lstrip(" "))
                if block_line.strip() and block_indent <= indent:
                    break
                block_lines.append(block_line[indent + 2 :] if block_line.strip() else "")
                i += 1
            parent[name] = "\n".join(block_lines) + ("\n" if raw == "|" else "")
            continue
        elif raw.startswith('"'):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as error:
                raise TextError(f"{key}: invalid quoted scalar {raw!r}") from error
            if not isinstance(value, str):
                raise TextError(f"{key}: quoted scalar must be a string")
            parent[name] = value
        else:
            parent[name] = raw
        i += 1
    return root


def _flatten(value: dict, prefix: str = "") -> dict[str, str]:
    result = {}
    for name, item in value.items():
        full = f"{prefix}.{name}" if prefix else name
        if isinstance(item, dict):
            result.update(_flatten(item, full))
        else:
            result[full] = item
    return result


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, str], dict[str, int | float]]:
    directory = _directory()
    templates = {
        path.relative_to(directory).with_suffix("").as_posix(): path.read_text()
        for path in directory.rglob("*.md")
        if path.relative_to(directory).as_posix() != "README.md"
    }
    numbers_path = directory / "numbers.yaml"
    for path in directory.rglob("*.yaml"):
        if path == numbers_path or path.name in {"shown.yaml", "rules.yaml"}:
            continue
        prefix = path.relative_to(directory).with_suffix("").as_posix()
        templates.update(
            {f"{prefix}.{name}": value for name, value in _flatten(_parse_yaml(path.read_text(), prefix)).items()}
        )
    numbers_raw = _flatten(_parse_yaml(numbers_path.read_text(), "numbers")) if numbers_path.exists() else {}
    numbers: dict[str, int | float] = {}
    for name, raw in numbers_raw.items():
        try:
            numbers[name] = int(raw) if re.fullmatch(r"[+-]?\d+", raw) else float(raw)
        except ValueError as error:
            raise TextError(f"numbers: {name} must be numeric") from error
    return templates, numbers


def _check(key: str, raw: str) -> list[tuple[str, str | None]]:
    placeholders = []
    i = 0
    while i < len(raw):
        if raw.startswith("{{", i) or raw.startswith("}}", i):
            i += 2
        elif raw[i] == "{":
            match = _PLACEHOLDER.match(raw, i)
            if not match:
                raise TextError(f"{key}: invalid placeholder near {raw[i : i + 20]!r}")
            placeholders.append((match.group(1), match.group(2)))
            i = match.end()
        elif raw[i] == "}":
            raise TextError(f"{key}: unmatched closing brace")
        else:
            i += 1
    return placeholders


def keys() -> list[str]:
    templates, _ = _load()
    return sorted(templates)


def template(key: str) -> str:
    templates, _ = _load()
    try:
        raw = templates[key]
    except KeyError as error:
        raise TextError(f"{key}: unknown template key") from error
    _check(key, raw)
    return raw


def numbers() -> dict[str, int | float]:
    return dict(_load()[1])


@lru_cache(maxsize=1)
def shown() -> dict[str, dict[str, str]]:
    """Read per-template display metadata, kept outside the renderable message catalog."""
    path = _directory() / "shown.yaml"
    if not path.exists():
        return {}
    raw = _flatten(_parse_yaml(path.read_text(), "shown"))
    result: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if key.endswith(".where"):
            result.setdefault(key[:-6], {})["where"] = value
        elif key.endswith(".per_run"):
            result.setdefault(key[:-8], {})["per_run"] = value
    return result


def render(key: str, **values: object) -> str:
    raw = template(key)
    counts = _check(key, raw)
    constants = numbers()
    collision = set(values) & constants.keys()
    if collision:
        name = sorted(collision)[0]
        raise TextError(f"{key}: value {name!r} collides with numbers.yaml")
    needed = {name for name, _ in counts}
    missing = needed - values.keys() - constants.keys()
    if missing:
        name = sorted(missing)[0]
        raise TextError(f"{key}: missing placeholder {name!r}")
    unused = values.keys() - needed
    if unused:
        name = sorted(unused)[0]
        raise TextError(f"{key}: unused value {name!r}")

    def replace(match: re.Match) -> str:
        name, spec = match.group(1), match.group(2)
        value = values[name] if name in values else constants[name]
        if spec is None:
            return str(value)
        try:
            return format(value, spec)
        except (TypeError, ValueError) as error:
            raise TextError(f"{key}: cannot format placeholder {name!r} with {spec!r}") from error

    # Escapes are protected before substitution so their braces stay literal.
    protected = raw.replace("{{", "\0OPEN\0").replace("}}", "\0CLOSE\0")
    rendered = _PLACEHOLDER.sub(replace, protected)
    return rendered.replace("\0OPEN\0", "{").replace("\0CLOSE\0", "}")
