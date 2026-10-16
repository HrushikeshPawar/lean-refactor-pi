"""Codex usage-limit reader: temp rollout files and a fake `codex app-server`, no network or model."""

import json
import stat
import tempfile
import time
import unittest
from pathlib import Path

from arena import codex_limits as cl

SNAP = {"primary": {"used_percent": 23.0, "window_minutes": 300, "resets_at": 4102444800},
        "secondary": {"used_percent": 34.0, "window_minutes": 10080, "resets_at": 4102444900}}


def rollout(home: Path, snapshot, name="rollout-a.jsonl", stamp="2026-10-15T05:15:53.438Z"):
    folder = home / "sessions" / "2026" / "10" / "15"
    folder.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "rate_limits": snapshot}}
    path = folder / name
    path.write_text(json.dumps({"type": "x"}) + "\n" + json.dumps(event) + "\n" + "junk\n")
    return path


class RolloutTests(unittest.TestCase):
    def test_reads_newest_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            rollout(Path(tmp), SNAP)
            got = cl.read_limits(Path(tmp), command=None)
        self.assertEqual((got.five_hour_pct, got.weekly_pct, got.source), (23.0, 34.0, "rollout"))
        self.assertEqual(got.weekly_resets_at, 4102444900)

    def test_reset_window_reads_zero(self):
        old = {"primary": {**SNAP["primary"], "resets_at": 1000}, "secondary": SNAP["secondary"]}
        with tempfile.TemporaryDirectory() as tmp:
            rollout(Path(tmp), old)
            got = cl.read_limits(Path(tmp), command=None)
        self.assertEqual((got.five_hour_pct, got.weekly_pct), (0.0, 34.0))

    def test_missing_or_unusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(cl.read_limits(Path(tmp) / "none", command=None))
            rollout(Path(tmp), {"primary": None, "secondary": None})
            self.assertIsNone(cl.read_limits(Path(tmp), command=None))


class AppServerTests(unittest.TestCase):
    def fake(self, directory: Path, reply: str) -> str:
        script = directory / "fakecodex"
        script.write_text(
            "#!/usr/bin/env python3\nimport sys, json\n"
            "for line in sys.stdin:\n    m = json.loads(line)\n"
            "    if m.get('id') == 2:\n        print(json.dumps({'id': 2, 'result': " + reply + "}), flush=True)\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return str(script)

    def test_live_reading_preferred(self):
        snap = {"rateLimits": {"primary": {"usedPercent": 31, "resetsAt": 5}, "secondary": {"usedPercent": 5, "resetsAt": None}}}
        with tempfile.TemporaryDirectory() as tmp:
            rollout(Path(tmp), SNAP)
            got = cl.read_limits(Path(tmp), command=self.fake(Path(tmp), repr(snap)), timeout=10)
        self.assertEqual((got.five_hour_pct, got.weekly_pct, got.source), (31.0, 5.0, "app-server"))
        self.assertIsNone(got.weekly_resets_at)
        self.assertLess(abs(got.observed_at - time.time()), 30)

    def test_bad_server_falls_back_to_rollout(self):
        with tempfile.TemporaryDirectory() as tmp:
            rollout(Path(tmp), SNAP)
            got = cl.read_limits(Path(tmp), command=self.fake(Path(tmp), "{}"), timeout=10)
            gone = cl.read_limits(Path(tmp), command=str(Path(tmp) / "absent"), timeout=10)
        self.assertEqual(got.source, "rollout")
        self.assertEqual(gone.source, "rollout")


if __name__ == "__main__":
    unittest.main()
