"""Guard agent-facing source modules against inline prose."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
PYTHON_FILES = (
    "arena/campaign.py",
    "arena/context.py",
    "arena/memory.py",
    "arena/engine.py",
    "arena/routes.py",
    "arena/profile.py",
    "arena/merges.py",
    "arena/goalstate.py",
    "arena/skill.py",
)
TS_FILES = (
    "packages/arena-pi/extensions/arena.ts",
    "packages/arena-pi/extensions/rules.ts",
    "packages/arena-pi/extensions/trim.ts",
    "packages/arena-pi/extensions/spend.ts",
)


def _long_enough(value: str) -> bool:
    return len(re.findall(r"\S+", value)) >= 4


def _python_issues(source: str) -> list[str]:
    lines = source.splitlines()
    return [
        f"{line}: {value!r}"
        for line, value in _python_literals(source)
        if _long_enough(value)
        and not any("# not-model-facing" in lines[index - 1] for index in (line, line - 1) if 0 < index <= len(lines))
    ]


def _typescript_issues(source: str) -> list[str]:
    lines = source.splitlines()
    return [
        f"{line}: {value!r}"
        for line, value in _ts_literals(source)
        if _long_enough(value) and (line > len(lines) or "// not-model-facing" not in lines[line - 1])
    ]


def _python_literals(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    results = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", [])
            for index, child in enumerate(body):
                if (
                    index == 0
                    and isinstance(child, ast.Expr)
                    and isinstance(child.value, (ast.Constant, ast.JoinedStr))
                ):
                    continue
                visit(child)
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            results.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            results.append(
                (
                    node.lineno,
                    "".join(
                        part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else ""
                        for part in node.values
                    ),
                )
            )
        for child in ast.iter_child_nodes(node):
            if not isinstance(node, ast.JoinedStr):
                visit(child)

    visit(tree)
    return results


def _ts_literals(source: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    i = 0
    line = 1
    while i < len(source):
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            chunk = source[i : len(source) if end < 0 else end + 2]
            line += chunk.count("\n")
            i += len(chunk)
            continue
        if source[i] not in "\"'`":
            line += source[i] == "\n"
            i += 1
            continue
        quote, start_line = source[i], line
        i += 1
        chars = []
        interpolation_depth = 0
        while i < len(source):
            char = source[i]
            if char == "\\" and i + 1 < len(source):
                if source[i + 1] == "n":
                    chars.append("\n")
                elif source[i + 1] == "t":
                    chars.append("\t")
                else:
                    chars.append(source[i + 1])
                line += source[i : i + 2].count("\n")
                i += 2
                continue
            if quote == "`" and source.startswith("${", i):
                interpolation_depth = 1
                chars.append(" ")
                i += 2
                while i < len(source) and interpolation_depth:
                    if source[i] == "{":
                        interpolation_depth += 1
                    elif source[i] == "}":
                        interpolation_depth -= 1
                    line += source[i] == "\n"
                    i += 1
                continue
            if char == quote:
                i += 1
                break
            chars.append(char)
            line += char == "\n"
            i += 1
        out.append((start_line, "".join(chars)))
    return out


def _scan() -> list[str]:
    issues = []
    for relative in PYTHON_FILES:
        source = (ROOT / relative).read_text()
        issues.extend(f"{relative}:{issue}" for issue in _python_issues(source))
    for relative in TS_FILES:
        source = (ROOT / relative).read_text()
        issues.extend(f"{relative}:{issue}" for issue in _typescript_issues(source))
    return issues


class AgentTextLintTests(unittest.TestCase):
    def test_python_scanner_cases(self):
        self.assertTrue(_python_issues('value = "unmarked sentence should report"'))
        self.assertFalse(_python_issues('value = "marked sentence should report"  # not-model-facing'))
        self.assertFalse(_python_issues('"""module documentation has several words"""'))
        self.assertFalse(_python_issues('value = "three words only"'))
        self.assertTrue(_python_issues('value = f"alpha beta {x} gamma delta"'))

    def test_typescript_scanner_cases(self):
        self.assertTrue(_typescript_issues("const value = `alpha beta ${name} gamma delta`;"))
        self.assertFalse(_typescript_issues("const value = `alpha beta ${name} gamma delta`; // not-model-facing"))
        self.assertFalse(_typescript_issues('const url = "https://example.test/a";'))

    def test_model_facing_modules_have_no_inline_prose(self):
        self.assertEqual([], _scan())
