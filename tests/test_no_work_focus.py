import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign


class NoWorkFocusTests(unittest.TestCase):
    def test_focus_moves_to_best_cell_of_another_route_else_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "proofs").mkdir()
            history: list[dict] = [{"kind": "candidate", "candidate_id": "ref", "origin": "reference"}]
            for ident, route, parent in (("a", "r1", "ref"), ("b", "r2", None)):
                (directory / "proofs" / f"{ident}.lean").write_text("theorem t : True := by\n  exact True.intro\n")
                history += [
                    {"kind": "candidate", "candidate_id": ident, "origin": "model"},
                    {
                        "kind": "evaluation",
                        "candidate_id": ident,
                        "mode": "fast",
                        "result": {"compat": {"v": {"passed": True}}, "metrics": {"estimated_proxy": 50}},
                    },
                    {"kind": "edge", "proof_id": ident, "from": [parent] if parent else []},
                    {"kind": "route", "proof_id": ident, "route": route},
                ]
            history.append({"kind": "focus", "proof_id": "a", "reason": "start"})
            appended = []
            with (
                patch.object(campaign, "run_dir", return_value=directory),
                patch.object(campaign, "events", side_effect=lambda _: history + appended),
                patch.object(campaign, "_append", side_effect=lambda _d, event: appended.append(event)),
            ):
                result = campaign.no_work_focus("run")
                self.assertTrue(result["moved"])
                self.assertEqual(appended[-1], {"kind": "focus", "proof_id": "b", "reason": "no_work"})
                self.assertEqual(campaign.no_work_focus("run")["moved"], True)
                self.assertEqual(appended[-1]["proof_id"], "a")
                history[:] = [*history[:1], {"kind": "focus", "proof_id": "ref", "reason": "start"}]
                appended.clear()
                self.assertEqual(campaign.no_work_focus("run"), {"moved": False})
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
