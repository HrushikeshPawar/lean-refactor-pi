"""Small adapter for modules whose existing execution body still consumes argparse values."""

from __future__ import annotations

from dataclasses import fields
from typing import Any


def option_tokens(options: Any, *, repeated: frozenset[str] = frozenset()) -> list[str]:
    """Render a typed options dataclass as the old parser's argv during command migration."""
    tokens = []
    for item in fields(options):
        value = getattr(options, item.name)
        flag = item.metadata.get("flag", "--" + item.name.replace("_", "-"))
        if isinstance(value, bool):
            if value:
                tokens.append(flag)
        elif value is None:
            continue
        elif isinstance(value, list):
            if item.name in repeated:
                for entry in value:
                    tokens.extend((flag, str(entry)))
            elif value:
                tokens.extend((flag, *(str(entry) for entry in value)))
        else:
            tokens.extend((flag, str(value)))
    return tokens
