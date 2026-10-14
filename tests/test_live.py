"""Live progress view: state from Pi events, figures from a fixture run directory, rendering, plain fallback."""

import importlib
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rich.console import Console

from arena.cli import live

run_module = importlib.import_module("arena.cli.run")


def assistant(output=10, cache_read=0, cache_write=0, input_tokens=5, error=None, stop="toolUse"):
    usage = {"input": input_tokens, "output": output, "cacheRead": cache_read, "cacheWrite": cache_write}
    usage["totalTokens"] = sum(usage.values())
    message = {"role": "assistant", "stopReason": stop, "usage": usage}
    if error:
        message["errorMessage"] = error
    return {"type": "message_end", "message": message}


EVENTS = [
    {"type": "message_end", "message": {"role": "user"}},
    {
        "type": "tool_execution_start",
        "toolName": "compile",
        "toolCallId": "c1",
        "args": {"drafts": ["a"], "base": "n1"},
    },
    assistant(output=100, cache_read=900, cache_write=50, input_tokens=50),
    {"type": "tool_execution_end", "toolName": "compile", "toolCallId": "c1", "result": {"content": [{"text": "ok"}]}},
    {"type": "auto_retry_start", "attempt": 1, "maxAttempts": 3, "errorMessage": "overloaded"},
    {"type": "compaction_start"},
    assistant(output=20, cache_read=100, cache_write=0, input_tokens=0, stop="stop"),
    {"type": "tool_execution_end", "toolName": "search", "toolCallId": "s1"},
    {"type": "agent_settled"},
]


def result(proxy, tokens, heartbeats, passed=True):
    return {
        "compat": {"v1": {"passed": passed}},
        "metrics": {"proxy": proxy},
        "tokens": tokens,
        "heartbeat": heartbeats,
    }


def write_run(directory: Path) -> None:
    """Reference n1 (score 10), n2 from n1 verified at 42.5, n3 from n2 broken."""
    (directory / "proofs").mkdir(parents=True)
    (directory / "run-config.json").write_text(
        json.dumps({"theorem": "Fixture.thm", "model": "fixture-model", "limit_usd": 0.5})
    )
    (directory / "cost-ledger.jsonl").write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"kind": "reserve", "usd": 0.3},
                {"kind": "settle", "usd": 0.1, "usage_known": True},
                {"kind": "settle", "usd": 0.025, "usage_known": True},
                {"kind": "settle", "usd": 9.0, "usage_known": False},
                {"kind": "control", "stop": None},
            )
        )
        + "\n"
    )
    ledger = [
        {"kind": "init", "theorem": "Fixture.thm", "versions": ["v1"], "ts": 1},
        {"kind": "candidate", "candidate_id": "ref", "origin": "reference"},
        {"kind": "evaluation", "candidate_id": "ref", "mode": "full", "result": result(10.0, 900, 5000)},
        {"kind": "candidate", "candidate_id": "aaa", "origin": "model"},
        {"kind": "edge", "proof_id": "aaa", "from": ["ref"], "type": "edited_from"},
        {"kind": "evaluation", "candidate_id": "aaa", "mode": "full", "result": result(42.5, 410, 1234)},
        {"kind": "candidate", "candidate_id": "bbb", "origin": "model"},
        {"kind": "edge", "proof_id": "bbb", "from": ["aaa"], "type": "edited_from"},
        {"kind": "evaluation", "candidate_id": "bbb", "mode": "fast", "result": result(None, 300, 900, passed=False)},
    ]
    (directory / "ledger.jsonl").write_text("\n".join(json.dumps(row) for row in ledger) + "\n")
    for ident in ("ref", "aaa", "bbb"):
        (directory / "proofs" / f"{ident}.lean").write_text("theorem t : True := by\n  trivial\n")


class EventStateTests(unittest.TestCase):
    def test_counters_follow_the_event_sequence(self):
        view = live.RunView("r1", Path("/nonexistent"))
        for event in EVENTS:
            view.on_event(event)
        self.assertEqual((view.requests, view.tool_calls, view.retries, view.compactions), (2, 2, 1, 1))
        self.assertEqual((view.tokens_in, view.tokens_out, view.cache_read), (1100, 120, 1000))

    def test_recent_events_keep_only_the_newest(self):
        view = live.RunView("r1", Path("/nonexistent"))
        for index in range(live.RECENT_EVENTS + 5):
            view.add_line(f"line {index}")
        self.assertEqual(len(view.lines), live.RECENT_EVENTS)
        self.assertEqual(view.lines[-1], f"line {live.RECENT_EVENTS + 4}")


class RunDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / "run"
        write_run(self.directory)

    def tearDown(self):
        self.tmp.cleanup()

    def test_spend_limit_and_nodes_come_from_the_run_files(self):
        figures = live.RunDirPoller(self.directory).poll()
        self.assertEqual((figures.theorem, figures.model, figures.limit_usd), ("Fixture.thm", "fixture-model", 0.5))
        self.assertAlmostEqual(figures.spent_usd, 0.125)
        self.assertEqual([node.id for node in figures.nodes], ["n1", "n2", "n3"])
        self.assertEqual([node.parent for node in figures.nodes], [None, "n1", "n2"])
        best = figures.best
        assert best is not None and figures.reference is not None
        self.assertEqual((best.id, best.score, best.tokens, best.heartbeats), ("n2", 42.5, 410, 1234))
        self.assertEqual(figures.reference.id, "n1")

    def test_unchanged_files_are_not_parsed_again(self):
        poller = live.RunDirPoller(self.directory)
        poller.poll()
        with mock.patch.object(poller.ledger, "load", side_effect=AssertionError("re-read")):
            poller.poll()
        with (self.directory / "ledger.jsonl").open("a") as handle:
            handle.write(json.dumps({"kind": "focus", "proof_id": "aaa"}) + "\n")
        with self.assertRaises(AssertionError), mock.patch.object(poller.ledger, "load", side_effect=AssertionError):
            poller.poll()

    def test_missing_directory_gives_empty_figures(self):
        figures = live.RunDirPoller(self.directory / "absent").poll()
        self.assertEqual((figures.spent_usd, figures.nodes, figures.best), (0.0, [], None))

    def render(self, width: int) -> str:
        view = live.RunView("fixture-run", self.directory, lean="session leased")
        for event in EVENTS:
            view.on_event(event)
        view.add_line("[12:00:00] Pi agent settled")
        view.poll()
        console = Console(record=True, width=width, color_system=None)
        console.print(view.render(width))
        return console.export_text()

    def test_render_shows_the_key_figures_at_wide_and_narrow_widths(self):
        for width in (60, 140):
            with self.subTest(width=width):
                frame = self.render(width)
                for figure in ("Fixture.thm", "fixture-run", "$0.1250", "25.0%", "42.50", "+32.50", "n2", "n3", "410"):
                    self.assertIn(figure, frame)
                self.assertIn("Pi agent settled", frame)
                self.assertTrue(all(len(line) <= width for line in frame.splitlines()))

    def test_spend_colour_moves_from_green_to_red(self):
        self.assertEqual(live.spend_colour(0.0), "#008000")
        self.assertEqual(live.spend_colour(1.0), "#800000")
        self.assertNotIn(live.spend_colour(0.5), (live.spend_colour(0.0), live.spend_colour(1.0)))


class CampaignViewTests(unittest.TestCase):
    def test_board_tracks_status_and_polled_figures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs = [
                {"row": "Fixture.thm", "model": "m", "replicate": 1, "run_id": "run"},
                {"row": "Other.thm", "model": "m", "replicate": 1, "run_id": "other"},
            ]
            write_run(root / "run")
            view = live.CampaignView("pfx", specs, root, 0.5)
            view.run_started(specs[0])
            view.poll()
            console = Console(record=True, width=100, color_system=None)
            console.print(view.render(100))
            frame = console.export_text()
            self.assertIn("running", frame)
            self.assertIn("queued", frame)
            self.assertIn("n2 42.50", frame)
            self.assertIn("$0.1250", frame)
            view.run_finished(specs[0], 1)
            self.assertEqual((view.by_id["run"].status, view.by_id["run"].exit_code), ("failed", 1))


class PlainPathTests(unittest.TestCase):
    def test_enabled_needs_a_tty_and_no_opt_out(self):
        tty = SimpleNamespace(isatty=lambda: True)
        with mock.patch.dict(os.environ, {live.PLAIN_ENV: ""}):
            self.assertTrue(live.enabled(stream=tty))
            self.assertFalse(live.enabled(plain=True, stream=tty))
            self.assertFalse(live.enabled(stream=io.StringIO()))
        with mock.patch.dict(os.environ, {live.PLAIN_ENV: "1"}):
            self.assertFalse(live.enabled(stream=tty))
        self.assertIsNone(live.start_run("r", Path("."), plain=True))

    def test_log_event_output_is_unchanged_without_a_view(self):
        self.assertIsNone(run_module._LIVE)
        run_module._request_count = run_module._tool_result_count = run_module._retry_count = 0
        run_module._tool_started.clear()
        output = io.StringIO()
        with redirect_stdout(output):
            for event in EVENTS:
                run_module.log_event(event)
        lines = [re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", line) for line in output.getvalue().splitlines()]
        self.assertTrue(all(re.match(r"^\[\d\d:\d\d:\d\d\] ", line) for line in output.getvalue().splitlines()))
        self.assertEqual(
            lines,
            [
                "compile started drafts=1 base=n1",
                "provider response #1 model toolUse output=100 cache-read=900 cache-write=50; tool-results=0; retries=0",
                "compile in 0.0s: ok",
                "provider retry 1/3: overloaded",
                "provider response #2 model stop output=20 cache-read=100 cache-write=0; tool-results=1; retries=1",
                "tool result #2 search ok",
                "Pi agent settled",
            ],
        )

    def test_log_event_feeds_an_active_view_instead_of_printing(self):
        view = live.RunView("r", Path("/nonexistent"))
        display = live.RunDisplay(view, Console(file=io.StringIO()))
        display.active = True
        output = io.StringIO()
        with mock.patch.object(run_module, "_LIVE", display), redirect_stdout(output):
            run_module.log_event({"type": "agent_settled"})
            run_module.log_event({"type": "tool_execution_end", "toolName": "search"})
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(view.tool_calls, 1)
        self.assertTrue(view.lines[0].endswith("Pi agent settled"))

    def test_a_polling_error_turns_the_view_off_and_lines_print_plainly(self):
        view = live.RunView("r", Path("/nonexistent"))
        display = live.RunDisplay(view, Console(file=io.StringIO(), width=80), refresh_s=0.01, poll_s=0.0)
        errors = io.StringIO()
        with redirect_stderr(errors), mock.patch.object(view.poller, "poll", side_effect=OSError("disk gone")):
            self.assertIs(display.start(), None)
        self.assertFalse(display.active)
        self.assertIn("disk gone", errors.getvalue())
        output = io.StringIO()
        with mock.patch.object(run_module, "_LIVE", display), redirect_stdout(output):
            run_module.log_event({"type": "agent_settled"})
        self.assertTrue(output.getvalue().endswith("Pi agent settled\n"))

    def test_an_error_after_start_stops_the_view_without_raising(self):
        view = live.RunView("r", Path("/nonexistent"))
        display = live.RunDisplay(view, Console(file=io.StringIO(), width=80), refresh_s=0.01, poll_s=0.0)
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertIs(display.start(), display)
            with mock.patch.object(view.poller, "poll", side_effect=ValueError("bad ledger")):
                assert display.thread is not None
                display.thread.join(2)
            self.assertFalse(display.active)
            self.assertFalse(display.line("after"))
            display.stop()
        self.assertIn("bad ledger", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
