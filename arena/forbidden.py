"""The forbidden-construct filter the official Space applies to every submitted proof."""

from __future__ import annotations

import ast
import functools
import re
from collections.abc import Callable
from pathlib import Path
from typing import cast

_APP = Path(__file__).resolve().parents[1] / "vendor" / "arena-space" / "app.py"
_WANTED = ("_MAX_PROOF_BYTES", "_FORBIDDEN_PATTERNS", "_strip_lean_comments", "_check_forbidden")

# Synced from pinned Lean Refactor Arena Space app.py.
FORBIDDEN = [
    ("#eval", re.compile(r"#\s*eval\b")),
    ("#reduce", re.compile(r"#\s*reduce\b")),
    ("IO.", re.compile(r"\bIO\.")),
    ("unsafe def/fun/theorem", re.compile(r"\bunsafe\s+(def|fun|theorem|lemma)\b")),
    ("extern", re.compile(r"\bextern\b")),
    ("initialize", re.compile(r"\binitialize\b")),
    ("@[implemented_by]", re.compile(r"@\[\s*implemented[_]?[Bb]y\b")),
    ("@[extern]", re.compile(r"@\[\s*extern\b")),
    ("sorry", re.compile(r"\bsorry\b")),
    ("sorryAx", re.compile(r"\bsorryAx\b")),
    ("admit", re.compile(r"\badmit\b")),
    ("axiom", re.compile(r"\baxiom\b")),
    ("native_decide", re.compile(r"\bnative_decide\b")),
    ("ofReduceBool", re.compile(r"\bofReduceBool\b")),
    ("ofReduceNat", re.compile(r"\bofReduceNat\b")),
    ("run_cmd", re.compile(r"\brun_cmd\b")),
    ("run_elab", re.compile(r"\brun_elab\b")),
    ("#exit", re.compile(r"#\s*exit\b")),
    ("#count_heartbeats", re.compile(r"#\s*count_heartbeats\b")),
    ("attribute command", re.compile(r"(?m)^\s*attribute\b")),
    (
        "macro/elab/notation",
        re.compile(r"\b(macro|macro_rules|elab|elab_rules|notation|syntax)\b"),
    ),
    ("deriving instance", re.compile(r"\bderiving\s+instance\b")),
    (
        "auxiliary declaration",
        re.compile(r"(?m)^\s*(def|abbrev|instance|structure|inductive|class|opaque)\b"),
    ),
]


def remove_comments(text: str) -> str:
    out = []
    i = 0
    n = len(text)

    while i < n:
        if text[i] == '"':
            out.append(text[i])
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue

        if text.startswith("/-", i):
            depth = 1
            i += 2
            while i < n and depth:
                if text.startswith("/-", i):
                    depth += 1
                    i += 2
                elif text.startswith("-/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            out.append(" ")
            continue

        if text.startswith("--", i):
            while i < n and text[i] != "\n":
                i += 1
            continue

        out.append(text[i])
        i += 1

    return "".join(out)


def _assigned_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.FunctionDef):
        return node.name
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None


def _load_official(path: Path) -> Callable[[str], str | None]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    defined: dict[str, ast.AST] = {}
    for node in tree.body:
        name = _assigned_name(node)
        if name:
            defined[name] = node
    missing = next((name for name in _WANTED if name not in defined), None)
    if missing is not None:
        raise RuntimeError(f"{missing} is missing from {path}")
    needed: set[str] = set()
    pending = list(_WANTED)
    while pending:
        name = pending.pop()
        if name in needed or name not in defined:
            continue
        needed.add(name)
        pending.extend(
            ref.id
            for ref in ast.walk(defined[name])
            if isinstance(ref, ast.Name) and ref.id in defined and ref.id not in needed
        )
    body: list[ast.stmt] = []
    for name, node in defined.items():
        if name in needed and isinstance(node, ast.stmt):
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {"re": re}
    exec(compile(module, str(path), "exec"), namespace, namespace)
    checker = namespace["_check_forbidden"]
    if not callable(checker):
        raise RuntimeError(f"_check_forbidden is missing from {path}")
    return cast(Callable[[str], str | None], checker)


@functools.cache
def official_filter() -> Callable[[str], str | None]:
    """The Space app's `_check_forbidden`, loaded without importing gradio.

    The app module imports gradio at load time. This reads the file as source, keeps the four
    filter names and any top-level assignment or function they reference, and executes that
    fragment with `re` in a fresh namespace.
    """
    return _load_official(_APP)
