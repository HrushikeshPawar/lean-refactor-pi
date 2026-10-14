import ast
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from arena import text
from arena.cli.text import _budget_markdown, _budget_rows, _shown_for, render_template


class TextRendererTests(unittest.TestCase):
    def test_model_text_builders_have_no_long_literals(self):
        root = Path(__file__).parents[1]
        python_files = (
            "arena/context.py",
            "arena/memory.py",
            "arena/reply.py",
            "arena/tools.py",
            "arena/campaign.py",
            "arena/summary.py",
        )
        for name in python_files:
            source = (root / name).read_text()
            tree = ast.parse(source)
            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }
            parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if id(node) in docstrings or len(node.value) < 30 or " " not in node.value:
                    continue
                line = source.splitlines()[node.lineno - 1]
                if "# log" in line:
                    continue
                ancestors = []
                parent = parents.get(id(node))
                while parent and not isinstance(parent, (ast.FunctionDef, ast.Module)):
                    ancestors.append(parent)
                    parent = parents.get(id(parent))
                if any(isinstance(item, ast.Raise) for item in ancestors):
                    continue
                if any(
                    isinstance(item, ast.Call)
                    and isinstance(item.func, ast.Name)
                    and item.func.id in {"print", "logging"}
                    for item in ancestors
                ):
                    continue
                # Summary artifact descriptions are operator output, not model text.
                if name == "arena/summary.py":
                    continue
                self.fail(f"{name}:{node.lineno}: long model-facing literal")

        quoted = re.compile(r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`""")
        for name in ("arena.ts", "rules.ts", "trim.ts", "reply.ts", "spend.ts"):
            source = (root / "packages/arena-pi/extensions" / name).read_text()
            for number, line in enumerate(source.splitlines(), 1):
                if (
                    line.lstrip().startswith(("//", "*"))
                    or "// log" in line
                    or "console." in line
                    or "throw new Error" in line
                ):
                    continue
                for match in quoted.finditer(line):
                    literal = re.sub(r"\$\{.*\}", "", match.group()[1:-1])
                    if len(literal) >= 30 and " " in literal:
                        self.fail(f"packages/arena-pi/extensions/{name}:{number}: long model-facing literal")

    def test_rule_owners_and_numbers_are_registered_once(self):
        root = Path(__file__).parents[1] / "agent-text"
        rules = text._parse_yaml((root / "rules.yaml").read_text(), "rules")
        templates = {key: text.template(key) for key in text.keys()}  # noqa: SIM118
        for rule_id, rule in rules.items():
            with self.subTest(rule=rule_id):
                owner = rule["template"]
                marker = rule["marker"]
                self.assertIn(owner, templates)
                self.assertIn(marker, templates[owner])
                self.assertEqual([key for key, body in templates.items() if marker in body], [owner])
                for number in rule["numbers"].split(","):
                    if number in text.numbers():
                        self.assertIn("{" + number, templates[owner])

    def test_rendered_templates_avoid_proof_direction_terms(self):
        terms = (Path(__file__).parent / "fixtures/neutrality_terms.txt").read_text().splitlines()
        required = {
            "induction",
            "inductive",
            "recursion",
            "recursive",
            "lemma",
            "strategy",
            "route",
            "idea",
            "simp",
            "rw",
            "rewrite",
            "grind",
        }
        self.assertTrue(required <= set(terms))
        denied = re.compile(r"\b(?:" + "|".join(map(re.escape, terms)) + r")\b", re.I)
        for key in text.keys():  # noqa: SIM118
            with self.subTest(key=key):
                values = {
                    name: 1 if fmt else "X"
                    for name, fmt in text._check(key, text.template(key))
                    if name not in text.numbers()
                }
                rendered = text.render(key, **values)
                self.assertNotRegex(rendered, denied)

    def test_theorem_render_uses_cached_fixture_and_reports_parts(self):
        fixtures = Path(__file__).parent / "fixtures/agent_text"
        context = json.loads((fixtures / "core-context.json").read_text())
        profile = json.loads((fixtures / "core-profile.json").read_text())
        output = io.StringIO()
        with (
            patch("arena.context.cached_context", return_value=context),
            patch("arena.context.reference_profile", return_value=profile),
            patch("arena.context.lean_context", side_effect=AssertionError("Lean started")),
            redirect_stdout(output),
        ):
            self.assertEqual(render_template(theorem="Core.InitsUpdatesComm", json_output=True), 0)
        result = json.loads(output.getvalue())
        parts = result["parts"]
        self.assertEqual(result["theorem"], "Core.InitsUpdatesComm")
        self.assertEqual([part["part"] for part in parts[:3]], ["system prompt", "skill", "tools/compile"])
        self.assertEqual(
            [part["part"] for part in parts[3:7]], ["tools/goal", "tools/search", "tools/read", "tools/finish"]
        )
        self.assertTrue(any(part["part"].startswith("Pinned environment") for part in parts))
        for part in parts:
            self.assertEqual(part["chars"], len(part["text"]))
            self.assertEqual(part["words"], len(part["text"].split()))
        error = io.StringIO()
        with patch("arena.context.cached_context", return_value={}), redirect_stderr(error):
            self.assertNotEqual(render_template(theorem="Core.InitsUpdatesComm", json_output=True), 0)
        self.assertIn("cached context", error.getvalue().lower())
        error = io.StringIO()
        with (
            patch("arena.context.cached_context", return_value=context),
            patch("arena.context.reference_profile", return_value={}),
            redirect_stderr(error),
        ):
            self.assertNotEqual(render_template(theorem="Core.InitsUpdatesComm", json_output=True), 0)
        self.assertIn("cached reference profile", error.getvalue().lower())

    def test_every_template_has_budget_metadata(self):
        root = Path(__file__).parents[1] / "agent-text"
        files = {
            path.relative_to(root).with_suffix("").as_posix()
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix in {".yaml", ".md"}
            and path.name not in {"README.md", "numbers.yaml", "shown.yaml", "rules.yaml"}
        }
        for key in files:
            shown = _shown_for(key)
            self.assertTrue(shown["where"].strip())
            self.assertTrue(shown["per_run"].strip())
        for key in text.keys():  # noqa: SIM118
            self.assertTrue(_shown_for(key)["where"].strip())

    def test_repository_templates_parse_and_readme_budget_is_current(self):
        for key in text.keys():  # noqa: SIM118
            with self.subTest(key=key):
                text.template(key)
        readme = (Path(__file__).parents[1] / "agent-text" / "README.md").read_text()
        start, end = "<!-- budget:start -->", "<!-- budget:end -->"
        actual = readme.split(start, 1)[1].split(end, 1)[0].strip()
        self.assertEqual(actual, _budget_markdown(_budget_rows()))

    def test_word_budget_limits(self):
        from arena.cli.run import SYSTEM_PROMPT
        from arena.skill import skill_prompt

        numbers = text.numbers()
        tools = []
        for name in ("compile", "goal", "search", "read", "finish"):
            prefix = f"tools/{name}."
            tools.extend(text.render(key) for key in text.keys() if key.startswith(prefix))  # noqa: SIM118
        static_words = (
            len(SYSTEM_PROMPT.split()) + len(skill_prompt().split()) + sum(len(item.split()) for item in tools)
        )
        self.assertLessEqual(static_words, numbers["budget.static_words"])
        packet_keys = (
            "packet/task",
            "packet/scoring",
            "packet/library",
            "packet/price-table.legend",
            "packet/price-table.original_heading",
            "packet/sections.titles.goals",
            "packet/sections.titles.library",
        )
        packet_words = sum(len(text.template(key).split()) for key in packet_keys)
        self.assertLessEqual(packet_words, numbers["budget.packet_words"])
        for key in text.keys():  # noqa: SIM118
            if key.startswith(("replies/", "messages/")):
                self.assertLessEqual(len(text.template(key).split()), numbers["budget.reply_words"], key)

    def test_shared_renderer_cases(self):
        cases = json.loads((Path(__file__).parent / "fixtures" / "text-cases.json").read_text())
        for case in cases:
            with self.subTest(key=case["key"], files=case["files"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name, content in case["files"].items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                text._load.cache_clear()
                with patch.dict(os.environ, {"ARENA_TEXT_DIR": directory}):
                    if "error" in case:
                        with self.assertRaisesRegex(text.TextError, case["error"]):
                            text.render(case["key"], **case.get("values", {}))
                    else:
                        self.assertEqual(text.render(case["key"], **case.get("values", {})), case["expect"])
                text._load.cache_clear()

    def test_five_tool_descriptions_include_the_shared_limits(self):
        numbers = text.numbers()
        compile_description = text.render("tools/compile.description")
        finish_description = text.render("tools/finish.description")
        self.assertIn(str(numbers["compile_max_drafts"]), compile_description)
        self.assertIn(str(numbers["finish_remaining_pct"]), finish_description)
        for name in ("compile", "goal", "search", "read", "finish"):
            with self.subTest(tool=name):
                self.assertTrue(text.render(f"tools/{name}.description"))

    def test_template_rejects_a_missing_directory_key(self):
        with (
            self.assertRaisesRegex(text.TextError, "demo: unknown template key"),
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"ARENA_TEXT_DIR": directory}),
        ):
            text._load.cache_clear()
            text.template("demo")
        text._load.cache_clear()
