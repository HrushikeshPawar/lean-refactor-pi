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

LINT_PYTHON = (
    "arena/context.py",
    "arena/memory.py",
    "arena/reply.py",
    "arena/tools.py",
    "arena/campaign.py",
    "arena/summary.py",
)
LINT_TYPESCRIPT = ("arena.ts", "rules.ts", "trim.ts", "reply.ts", "spend.ts")
LOG_CALLS = {"logging", "logger", "log", "LOG"}


def _long(value: str) -> bool:
    return len(value) >= 30 and " " in value


def _python_literal_lines(path: Path) -> list[int]:
    """Lines with a long literal outside docstrings, raise, logging, stderr prints and `# log` lines."""
    source = path.read_text()
    lines = source.splitlines()
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

    def allowed(node: ast.expr) -> bool:
        if any(re.search(r"# log\b", lines[n - 1]) for n in range(node.lineno, (node.end_lineno or node.lineno) + 1)):
            return True
        parent = parents.get(id(node))
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            if isinstance(parent, ast.Raise):
                return True
            if isinstance(parent, ast.Call):
                func = parent.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in LOG_CALLS:
                    return True
                if isinstance(func, ast.Name) and func.id == "print":
                    return any(
                        item.arg == "file" and ast.unparse(item.value) == "sys.stderr" for item in parent.keywords
                    )
            parent = parents.get(id(parent))
        return False

    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            value = "".join(
                part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if isinstance(parents.get(id(node)), ast.JoinedStr):
                continue
            value = node.value
        else:
            continue
        if _long(value) and not allowed(node):
            found.add(node.lineno)
    return sorted(found)


def _typescript_literal_lines(path: Path) -> list[int]:
    """Lines with a long quoted literal outside comments, throw, console.error/warn, journal keys and `// log`."""
    quoted = re.compile(r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`""")
    found = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if line.lstrip().startswith(("//", "*", "/*")) or re.search(r"// log\b", line):
            continue
        if re.search(r"\bthrow new \w*Error\(|console\.(?:error|warn)\(|\bappend(?:Trace|Cost)\(", line):
            continue
        code = line.split(" // ", 1)[0]
        if any(_long(re.sub(r"\$\{[^}]*\}", "", match.group()[1:-1])) for match in quoted.finditer(code)):
            found.append(number)
    return found


class TextRendererTests(unittest.TestCase):
    def test_model_text_builders_have_no_long_literals(self):
        """Literals of 30+ characters with a space belong in agent-text/ unless they are log or error output."""
        root = Path(__file__).parents[1]
        findings = [f"{name}:{line}" for name in LINT_PYTHON for line in _python_literal_lines(root / name)]
        findings += [
            f"packages/arena-pi/extensions/{name}:{line}"
            for name in LINT_TYPESCRIPT
            for line in _typescript_literal_lines(root / "packages/arena-pi/extensions" / name)
        ]
        self.assertEqual(findings, [], "long model-facing literals: move them to agent-text/ or mark the line # log")

    def test_literal_lint_allows_only_marked_logs_errors_and_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_text(
                "import sys\n"
                "a = 'this sentence is model facing text'\n"
                "b = 'this sentence is operator log text'  # log: summary line\n"
                "print('this sentence goes to the standard error', file=sys.stderr)\n"
                "print('this sentence goes to the standard output')\n"
                "raise ValueError('this sentence explains a failure')\n"
                "c = f'this sentence has {a} a placeholder inside'\n"
            )
            self.assertEqual(_python_literal_lines(path), [2, 5, 7])
            script = Path(directory) / "sample.ts"
            script.write_text(
                'const a = "this sentence is model facing text";\n'
                'const b = "this sentence is operator log text"; // log: alarm\n'
                'console.error("this sentence goes to the standard error");\n'
                'console.log("this sentence goes to the standard output");\n'
                'appendCost({ kind: "compaction skipped because empty" });\n'
                'throw new Error("this sentence explains a failure");\n'
            )
            self.assertEqual(_typescript_literal_lines(script), [1, 4])

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
        for name in ("compile", "goal", "search", "read", "scratch"):
            prefix = f"tools/{name}."
            tools.extend(text.render(key) for key in text.keys() if key.startswith(prefix))  # noqa: SIM118
        static_words = (
            len(SYSTEM_PROMPT.split()) + len(skill_prompt().split()) + sum(len(item.split()) for item in tools)
        )
        self.assertLessEqual(static_words, numbers["budget.static_words"])
        packet_keys = (
            "packet/task",
            "packet/scoring",
            "packet/price-table",
            "packet/price-table.legend",
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


FIXTURES = Path(__file__).parent / "fixtures/agent_text"
ROWS = {"core": "Core.InitsUpdatesComm", "ski": "Cslib.SKI.parallelReduction_diamond"}
# Before the final tenth of the spend nothing the model reads may mention ending the run (plan D42).
STOP_TEXT = re.compile(r"\b(?:finish\w*|stop\w*|threshold\w*|tenth|end(?:s|ing)? the run)\b", re.I)


def _fixture(stem: str) -> tuple[dict, dict]:
    return (
        json.loads((FIXTURES / f"{stem}-context.json").read_text()),
        json.loads((FIXTURES / f"{stem}-profile.json").read_text()),
    )


def _sections(stem: str, inventory: dict | None = None) -> list[tuple[str, str]]:
    """The packet of a fixture row, built from its cached context and profile without Lean."""
    from arena import context

    cached, measured = _fixture(stem)
    with (
        patch.object(context, "cached_context", return_value=inventory if inventory is not None else cached),
        patch.object(context, "reference_profile", return_value=measured),
        patch.object(context, "lean_context", side_effect=AssertionError("Lean started")),
    ):
        return context.packet_sections(ROWS[stem], cache_only=True)


def _packet(stem: str) -> str:
    return "\n\n".join(content for _title, content in _sections(stem)) + "\n"


def _dummies(key: str) -> dict:
    """A neutral value for every placeholder the caller supplies (numbers.yaml values are filled by the renderer)."""
    constants = text.numbers()
    return {name: 1 if spec else "X" for name, spec in text._check(key, text.template(key)) if name not in constants}


def _rendered(prefix: str) -> dict[str, str]:
    return {key: text.render(key, **_dummies(key)) for key in text.keys() if key.startswith(prefix)}  # noqa: SIM118


def _number_pattern(value: object) -> re.Pattern:
    return re.compile(rf"(?<![\d.]){re.escape(str(value))}(?!\d|\.\d)")


def _section(sections: list[tuple[str, str]], title: str) -> list[str]:
    return next((body.splitlines()[1:] for name, body in sections if name.startswith(title)), [])


def _rates(stem: str) -> dict:
    from arena.engine import problem, versions
    from arena.scoring import exchange_rates

    return exchange_rates(ROWS[stem], len(versions(problem(ROWS[stem]))))


class HiddenStopTests(unittest.TestCase):
    """D42: before the final tenth no model-facing text names finishing, stopping or the threshold."""

    def before_threshold(self) -> dict[str, str]:
        from arena.cli.run import SYSTEM_PROMPT
        from arena.skill import skill_prompt

        texts = {"system prompt": SYSTEM_PROMPT, "skill": skill_prompt()}
        for tool in ("compile", "goal", "search", "read"):
            texts.update(_rendered(f"tools/{tool}."))
        texts.update(_rendered("messages/footer"))
        texts.update(_rendered("messages/compaction-memory."))
        continuation = _rendered("messages/continuation.")
        continuation.pop("messages/continuation.finish_available")
        texts.update(continuation)
        return texts

    def test_text_before_the_threshold_never_mentions_ending_the_run(self):
        pct = text.numbers()["finish_remaining_pct"]
        digits = [_number_pattern(value) for value in (pct, 100 - pct, f"{pct / 100:g}")]
        for name, rendered in self.before_threshold().items():
            with self.subTest(text=name):
                self.assertNotRegex(rendered, STOP_TEXT)
                for pattern in digits:
                    self.assertNotRegex(rendered, pattern)
        for stem in ROWS:
            with self.subTest(packet=stem):
                packet = _packet(stem)
                self.assertNotRegex(packet, STOP_TEXT)
                # Rank and line numbers may be any integer; a percentage or fraction of the limit may not.
                self.assertNotRegex(packet, rf"(?<![\d.])(?:{pct}|{100 - pct})\s*%")

    def test_finish_is_named_only_by_the_texts_shown_once_it_is_offered(self):
        pct = text.numbers()["finish_remaining_pct"]
        templates = {**_rendered("messages/"), **_rendered("replies/"), **_rendered("tools/")}
        naming = sorted(key for key, rendered in templates.items() if re.search(r"\bfinish", rendered, re.I))
        self.assertEqual(
            [key for key in naming if not key.startswith("tools/finish.")], ["messages/continuation.finish_available"]
        )
        self.assertRegex(text.render("tools/finish.description"), _number_pattern(pct))


class PlaceholderTests(unittest.TestCase):
    """Checkbox 16: templates parse, renderers supply exactly the placeholders, nothing conditional."""

    def test_templates_have_no_conditional_or_plural_syntax(self):
        conditional = re.compile(r"\{[^{}]*[|?%#][^{}]*\}|\{\s*(?:if|else|endif|for)\s|\w\((?:s|es)\)")
        for key in text.keys():  # noqa: SIM118
            with self.subTest(key=key):
                raw = text.template(key).replace("{{", "").replace("}}", "")
                self.assertNotRegex(raw, conditional)

    def test_conditional_and_plural_placeholders_do_not_parse(self):
        for body in ("{count|s}", "{count?nodes}", "{% if x %}"):
            with self.subTest(body=body), self.assertRaises(text.TextError):
                text._check("demo", body)

    def test_a_missing_or_unused_value_raises(self):
        key = "messages/continuation.focus_material"
        values = _dummies(key)
        self.assertTrue(values)
        missing = dict(values)
        missing.pop(sorted(values)[0])
        with self.assertRaisesRegex(text.TextError, "missing placeholder"):
            text.render(key, **missing)
        with self.assertRaisesRegex(text.TextError, "unused value"):
            text.render(key, **values, extra="X")

    def test_every_render_call_supplies_exactly_the_template_placeholders(self):
        constants = text.numbers()
        needed = {
            key: {name for name, _ in text._check(key, text.template(key))} - constants.keys()
            for key in text.keys()  # noqa: SIM118
        }
        calls = [*_python_render_calls(), *_typescript_render_calls()]
        checked = 0
        for where, key, supplied in calls:
            with self.subTest(call=where, key=key):
                self.assertIn(key, needed, f"{where}: unknown template key")
                if supplied is None:
                    continue
                self.assertEqual(supplied, needed[key], where)
                checked += 1
        # Guard against a scanner that silently finds nothing.
        self.assertGreater(checked, 80)
        self.assertGreater(sum(where.endswith(".ts") or ".ts:" in where for where, _, _ in calls), 20)


def _python_render_calls() -> list[tuple[str, str, set[str] | None]]:
    """Each literal-key call of the Python renderers: (file:line, key, keyword names or None when dynamic)."""
    root = Path(__file__).parents[1]
    calls = []
    for path in sorted((root / "arena").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            first = node.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            if name in {"render", "render_text"} and "/" in first.value:
                key = first.value
            elif name == "_render" and path.name == "tools.py":
                key = f"replies/tools.{first.value}"
            else:
                continue
            dynamic = len(node.args) > 1 or any(item.arg is None for item in node.keywords)
            supplied = None if dynamic else {item.arg for item in node.keywords if item.arg}
            calls.append((f"{path.relative_to(root)}:{node.lineno}", key, supplied))
    return calls


def _typescript_render_calls() -> list[tuple[str, str, set[str] | None]]:
    root = Path(__file__).parents[1] / "packages/arena-pi/extensions"
    call = re.compile(r"\b(?:render|renderText)\(\s*([\"'`])([a-z][^\"'`$]*)\1\s*([,)])")
    calls = []
    for path in sorted(root.glob("*.ts")):
        if path.name.endswith(".test.ts") or path.name == "text.ts":
            continue
        source = path.read_text()
        for match in call.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            supplied: set[str] | None = set()
            if match.group(3) == ",":
                supplied = _object_keys(source, match.end())
            calls.append((f"{path.name}:{line}", match.group(2), supplied))
    return calls


def _object_keys(source: str, start: int) -> set[str] | None:
    """Top-level keys of the object literal that follows; None when it is not a plain literal."""
    index = start
    while source[index].isspace():
        index += 1
    if source[index] != "{":
        return None
    depth, quote, item, items = 0, "", "", []
    for char in source[index:]:
        if quote:
            item += char if depth == 1 else ""
            quote = "" if char == quote and item[-2:-1] != "\\" else quote
            continue
        if char in "\"'`":
            quote = char
        elif char in "{([":
            depth += 1
            if depth == 1:
                continue
        elif char in "})]":
            depth -= 1
            if depth == 0:
                items.append(item)
                break
        if depth == 1 and char == ",":
            items.append(item)
            item = ""
        elif depth == 1:
            item += char
    keys = set()
    for entry in (part.strip() for part in items):
        if not entry:
            continue
        if entry.startswith("..."):
            return None
        match = re.match(r"([A-Za-z_$][\w$]*)\s*(?::|$)", entry)
        if not match:
            return None
        keys.add(match.group(1))
    return keys


class RuleConsistencyTests(unittest.TestCase):
    """Checkbox 17: one rule, one place, one set of digits."""

    def corpus(self, stem: str) -> dict[str, str]:
        from arena.skill import skill_prompt

        texts = {"skill": skill_prompt(), "packet": _packet(stem)}
        for prefix in ("tools/", "replies/", "messages/"):
            texts.update(_rendered(prefix))
        return texts

    def test_each_rule_sentence_is_rendered_by_its_owner_only(self):
        rules = text._parse_yaml((Path(__file__).parents[1] / "agent-text/rules.yaml").read_text(), "rules")
        for stem in ROWS:
            corpus = self.corpus(stem)
            for rule_id, rule in rules.items():
                with self.subTest(row=stem, rule=rule_id):
                    owner = rule["template"]
                    self.assertIn(owner, text.keys())
                    where = (
                        "skill" if owner.startswith("skill/") else "packet" if owner.startswith("packet/") else owner
                    )
                    counts = {name: body.count(rule["marker"]) for name, body in corpus.items()}
                    self.assertEqual({name: n for name, n in counts.items() if n}, {where: 1})

    def test_numbers_yaml_values_are_never_written_as_literals(self):
        constants = text.numbers()
        used = {
            name
            for key in text.keys()  # noqa: SIM118
            for name, _ in text._check(key, text.template(key))
            if name in constants
        }
        literal = {name: _number_pattern(constants[name]) for name in used if len(str(constants[name])) >= 2}
        self.assertTrue(literal)
        for key in text.keys():  # noqa: SIM118
            raw = re.sub(r"\{[^{}]*\}", "", text.template(key))
            for name, pattern in literal.items():
                with self.subTest(key=key, number=name):
                    self.assertNotRegex(raw, pattern)

    def test_per_theorem_numbers_differ_while_numbers_yaml_lines_do_not(self):
        from arena.prices import snippet_tokens

        constants = text.numbers()
        packets = {stem: _packet(stem) for stem in ROWS}
        rates = {stem: _rates(stem) for stem in ROWS}
        for field in ("points_per_token", "points_per_100_heartbeats", "points_per_lost_version", "reference_tokens"):
            with self.subTest(field=field):
                self.assertNotEqual(rates["core"][field], rates["ski"][field])
                for stem, packet in packets.items():
                    self.assertRegex(packet, _number_pattern(rates[stem][field]))
        # The token examples are counted at build time by the pinned counter; their snippets are fixed text.
        for stem, packet in packets.items():
            for snippet in ("exact foo", "⟨a, b⟩"):
                self.assertRegex(packet, rf"`{re.escape(snippet)}` = {snippet_tokens(snippet)}\b", stem)
        # Every packet template line whose only placeholders are numbers.yaml keys renders identically for both rows.
        fixed_lines = []
        for key in (key for key in text.keys() if key.startswith("packet/")):  # noqa: SIM118
            for line in text.template(key).splitlines():
                names = [name for name, _ in text._check(key, line)]
                if names and all(name in constants for name in names):
                    fixed_lines.append(
                        text._PLACEHOLDER.sub(
                            lambda m: format(constants[m.group(1)], m.group(2) or ""), line.replace("{{", "{")
                        )
                    )
        self.assertTrue(fixed_lines)
        for line in fixed_lines:
            for stem, packet in packets.items():
                self.assertIn(line, packet, stem)


class PacketBehaviourTests(unittest.TestCase):
    """Checkbox 18 (a)-(c), from fixture contexts; no Lean."""

    def test_packet_order_rates_price_rows_goals_and_library_format(self):
        from arena import context

        goal_prefix = text.template("packet/sections.fixed.goal").split("{")[0]
        for stem, name in ROWS.items():
            with self.subTest(row=stem):
                sections = _sections(stem)
                packet = "\n\n".join(body for _title, body in sections)
                rates = _rates(stem)
                self.assertIn(name, sections[0][1])
                rate_lines = [line for line in packet.splitlines() if str(rates["points_per_100_heartbeats"]) in line]
                self.assertEqual(len(rate_lines), 1, rate_lines)
                for field in ("points_per_token", "points_per_lost_version"):
                    self.assertRegex(rate_lines[0], _number_pattern(rates[field]))
                    self.assertEqual(len(_number_pattern(rates[field]).findall(packet)), 1, field)
                self.assertIn(rate_lines[0], sections[1][1])
                titles = [title for title, _ in sections]
                reference = next(i for i, t in enumerate(titles) if t.startswith(context.REQUIRED_SECTIONS[-1]))
                goals = titles.index(text.template("packet/sections.titles.goals").strip())
                library = titles.index(context.LIBRARY_TITLE)
                self.assertLess(1, reference)
                self.assertLess(reference, goals)
                self.assertLess(goals, library)
                rows = [
                    line.split("|")[1].strip()
                    for line in sections[reference][1].splitlines()
                    if re.match(r"\| s\d+ \|", line)
                ]
                self.assertEqual(rows, [f"s{i}" for i in range(1, len(rows) + 1)])
                steps = [
                    line[len(goal_prefix) :].split(":")[0]
                    for line in sections[goals][1].splitlines()
                    if line.startswith(goal_prefix)
                ]
                self.assertTrue(steps)
                self.assertLessEqual(set(steps), set(rows))
                self.assertEqual(steps, sorted(steps, key=lambda step: int(step[1:])))
                lines = _section(sections, context.LIBRARY_TITLE)
                self.assertTrue(lines)
                for rank, line in enumerate(lines, 1):
                    match = re.fullmatch(r"(\d+)\. (decl:\S+) · (\S+) · (.+)", line)
                    self.assertIsNotNone(match, line)
                    assert match is not None
                    self.assertEqual(int(match.group(1)), rank)
                    self.assertNotIn("token", line.lower())

    def test_the_library_skips_names_the_original_already_uses_and_stays_in_budget(self):
        from arena import context

        inventory, _ = _fixture("core")
        used = inventory["source"][0]["name"]
        inventory["library"] = [{**inventory["library"][0], "name": used}, *inventory["library"]]
        lines = _section(_sections("core", inventory), context.LIBRARY_TITLE)
        handles = {line.split(" · ")[0].split(" ", 1)[1] for line in lines}
        known = {item["name"] for item in inventory["source"] + inventory["dependency"]}
        self.assertNotIn(f"decl:{used}", handles)
        self.assertFalse({f"decl:{name}" for name in known} & handles)
        self.assertLessEqual(len(lines), context.LIMITS["library"])
        self.assertLessEqual(sum(len(line) + 1 for line in lines), context.LIMITS["library_budget"])

    def test_an_over_limit_packet_sheds_every_local_line_before_any_library_line(self):
        from arena import context

        inventory, _ = _fixture("core")
        library = len(_section(_sections("core"), context.LIBRARY_TITLE))
        self.assertGreater(library, 0)
        # Many locals with long types, as in the row whose packet overflowed (fiberwise).
        inventory["local"] = [
            {**inventory["local"][0], "name": f"h{i}", "type": "T " * 150, "proof_line": i} for i in range(400)
        ]
        with patch.object(context, "MAX_PACKET_CHARS", 10**7):
            full = _sections("core", inventory)
        self.assertGreater(len("\n\n".join(body for _title, body in full)), context.MAX_PACKET_CHARS)
        sections = _sections("core", inventory)
        packet = "\n\n".join(body for _title, body in sections)
        self.assertLessEqual(len(packet), context.MAX_PACKET_CHARS)
        self.assertEqual(len(_section(sections, context.LIBRARY_TITLE)), library)
        self.assertLess(len(_section(sections, context.LOCAL_TITLE)), len(_section(full, context.LOCAL_TITLE)))
        self.assertEqual(_section(sections, context.EARLIER_TITLE), [])
        # A tighter limit forces library lines out: by then no local line is left.
        without = [(title, body) for title, body in full if not title.startswith(context.LOCAL_TITLE)]
        without = [(t, b) for t, b in without if not t.startswith(context.EARLIER_TITLE)]
        limit = len("\n\n".join(body for _title, body in without)) - 2000
        with patch.object(context, "MAX_PACKET_CHARS", limit):
            tight = _sections("core", inventory)
        self.assertLessEqual(len("\n\n".join(body for _title, body in tight)), limit)
        self.assertEqual(_section(tight, context.LOCAL_TITLE), [])
        self.assertLess(len(_section(tight, context.LIBRARY_TITLE)), library)
        self.assertGreater(len(_section(tight, context.LIBRARY_TITLE)), 0)
