import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from arena import campaign
from arena.cli import run_report


class RuntimeEventTests(unittest.TestCase):
    def test_runtime_event_is_ledgered_and_never_printed_as_json(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()) as out:
            seen = []
            campaign.RUNTIME_SINK = lambda directory, event: seen.append(event["phase"])
            try:
                campaign._runtime_event(Path(tmp), {"kind": "phase", "phase": "model", "status": "start"})
            finally:
                campaign.RUNTIME_SINK = None
            self.assertTrue((Path(tmp) / "ledger.jsonl").read_text().strip())
        self.assertEqual((err.getvalue(), out.getvalue(), seen), ("", "", ["model"]))

    def test_phase_notes_are_human_lines(self):
        note = run_report.phase_note(Path("/nonexistent"), {"kind": "phase", "phase": "closing_drain", "status": "end", "seconds": 2.0, "remaining": 0})
        self.assertEqual(note, "closing drain done in 2.0 s; 0 left")
        self.assertIsNone(run_report.phase_note(Path("/nonexistent"), {"kind": "phase", "phase": "model", "status": "start"}))


if __name__ == "__main__":
    unittest.main()
