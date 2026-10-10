import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import text
from arena.cli.text import _budget_markdown, _budget_rows


class TextRendererTests(unittest.TestCase):
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

    def test_template_rejects_a_missing_directory_key(self):
        with (
            self.assertRaisesRegex(text.TextError, "demo: unknown template key"),
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"ARENA_TEXT_DIR": directory}),
        ):
            text._load.cache_clear()
            text.template("demo")
        text._load.cache_clear()
