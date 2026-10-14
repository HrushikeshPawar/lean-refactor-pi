import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from arena import text
from arena.cli.text import _budget_markdown, _budget_rows, _shown_for, render_template


class TextRendererTests(unittest.TestCase):
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
            and path.name not in {"README.md", "numbers.yaml", "shown.yaml"}
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
