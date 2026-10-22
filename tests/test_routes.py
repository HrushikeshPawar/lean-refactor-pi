"""Offline tests for proof-shape routes and their stable ledger readers."""

import unittest

from arena import routes


class SignatureTests(unittest.TestCase):
    def test_signature_is_stable_under_hypothesis_renaming_and_small_edits(self):
        before = "theorem t : True := by\n  intro h1\n  exact h1\n"
        after = "theorem t : True := by\n  intro h2\n  exact h2\n"
        left, right = routes.signature(before), routes.signature(after)
        self.assertEqual(left["steps"], right["steps"])
        self.assertGreaterEqual(routes.similarity(left, right), routes.JOIN)

    def test_different_tactic_heads_and_steps_open_distance(self):
        left = routes.signature("theorem t : True := by\n  intro h\n  exact h\n")
        right = routes.signature("theorem t : True := by\n  omega\n  simp_all\n")
        self.assertLess(routes.similarity(left, right), routes.JOIN)

    def test_empty_proof_has_a_valid_signature(self):
        self.assertEqual(routes.signature("theorem t : True := by\n"), {"skeleton": [], "steps": []})


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.base = routes.signature("theorem t : True := by\n  intro h\n  exact h\n")
        self.near = routes.signature("theorem t : True := by\n  intro h2\n  exact h2\n")
        self.far = routes.signature("theorem t : True := by\n  omega\n")

    def test_first_route_join_and_single_link(self):
        first = routes.assign({}, self.base, None, None)
        self.assertEqual((first["route"], first["new"]), ("r1", True))
        direct_join = routes.assign({"r1": [self.base]}, self.near, None, None)
        self.assertGreaterEqual(direct_join["similarity"], routes.JOIN)
        members = {"r1": [self.base, self.far]}
        joined = routes.assign(members, self.near, "r1", 1)
        self.assertEqual((joined["route"], joined["new"]), ("r1", False))

    def test_far_proof_opens_route_and_small_edit_stays_with_parent(self):
        members = {"r1": [self.base]}
        self.assertEqual(routes.assign(members, self.far, "r1", 4)["route"], "r2")
        kept = routes.assign(members, self.far, "r1", routes.SMALL_EDIT_LINES)
        self.assertEqual((kept["route"], kept["new"]), ("r1", False))

    def test_dissimilar_complete_proof_opens_a_route_even_in_the_old_grey_band(self):
        sig = {"skeleton": ["a", "b", "c", "d"], "steps": ["a", "b"]}
        member = {"skeleton": ["a", "b", "x", "y"], "steps": ["a", "c"]}  # similarity about 0.4
        self.assertLess(routes.similarity(sig, member), routes.JOIN)
        result = routes.assign({"r1": [member]}, sig, None, None)
        self.assertEqual((result["route"], result["new"]), ("r2", True))

    def test_drafts_are_labelled_but_never_members(self):
        members = {"r1": [self.base], "r2": []}  # r2 has only drafts so far
        draft = routes.attach(members, self.far, "r2")
        self.assertEqual((draft["route"], draft["new"]), ("r2", False))
        # the first complete proof settles the draft-only route instead of opening r3
        settled = routes.assign(members, self.far, "r2", None)
        self.assertEqual(settled["route"], "r2")
        opened = routes.assign({"r1": [self.base], "r2": [self.near]}, self.far, None, None)
        self.assertEqual(opened["route"], "r3")

    def test_route_cap_joins_the_closest_route(self):
        members = {f"r{index}": [{"skeleton": [str(index), "route"], "steps": [str(index)]}] for index in range(1, 13)}
        result = routes.assign(members, {"skeleton": ["x", "y", "z"], "steps": ["new"]}, None, None)
        self.assertEqual((result["route"], result["new"]), ("r1", False))


class RouteTableTests(unittest.TestCase):
    def history(self):
        def candidate(identifier, origin):
            return {"kind": "candidate", "candidate_id": identifier, "origin": origin, "parents": []}

        def evaluation(identifier, proxy):
            return {
                "kind": "evaluation",
                "candidate_id": identifier,
                "mode": "fast",
                "result": {
                    "compat": {"v": {"passed": True}},
                    "metrics": {"estimated_proxy": proxy},
                },
            }

        def route(identifier, name, is_new, credited=False, holes=0):
            return {
                "kind": "route",
                "proof_id": identifier,
                "route": name,
                "new": is_new,
                "credited": credited,
                "assigned_by": "signature",
                "label": name,
                "short_label": name,
                "holes": holes,
            }

        return [
            candidate("ref", "reference"),
            route("ref", "r1", True),
            candidate("a", "model"),
            route("a", "r1", False),
            evaluation("a", 60),
            candidate("b", "model"),
            route("b", "r2", True, credited=True),
            evaluation("b", 80),
        ]

    def test_route_table_uses_event_credit_and_preserves_reader_shape(self):
        table = {row["route"]: row for row in routes.route_table(self.history())}
        self.assertTrue(table["r1"]["original"])
        self.assertFalse(table["r1"]["credited"])
        self.assertTrue(table["r2"]["credited"])
        self.assertFalse(table["r2"]["skeleton"])
        self.assertEqual(table["r1"]["best_candidate"], "#2")
        self.assertEqual(
            set(table["r1"]),
            {
                "route",
                "label",
                "short_label",
                "original",
                "attempts",
                "best_candidate",
                "best_proxy",
                "verified",
                "depth",
                "new_states",
                "min_holes",
                "stale_streak",
                "compiled",
                "explored",
                "stale",
                "credited",
                "skeleton",
            },
        )

    def test_route_detail_keeps_the_operator_format(self):
        table = routes.route_table(self.history())
        detail = routes.routes_detail_text(table)
        self.assertIn('r2 "r2": 1 attempt, 1 goal state, min holes 0, explored, credited, best proxy 80 (#3)', detail)


class DepthTests(unittest.TestCase):
    def ledger(self, attempts):
        rows, opened = [], set()
        for index, (identifier, route, goal, holes) in enumerate(attempts):
            origin = "reference" if index == 0 else "model"
            rows.append({"kind": "candidate", "candidate_id": identifier, "origin": origin, "parents": []})
            passed = goal is None
            diagnostics = [] if passed else [{"severity": "error", "message": "unsolved goals\n" + goal}]
            result = {
                "compat": {"v": {"passed": passed, "diagnostics": diagnostics, "goals": []}},
                "contains_sorry": False,
            }
            rows.append({"kind": "evaluation", "candidate_id": identifier, "mode": "fast", "result": result})
            new = route not in opened
            rows.append(
                {
                    "kind": "route",
                    "proof_id": identifier,
                    "route": route,
                    "new": new,
                    "credited": new and origin == "model",
                    "assigned_by": "signature",
                    "label": route,
                    "short_label": route,
                    "holes": holes,
                }
            )
            opened.add(route)
        return rows

    def goal(self, target):
        return f"P : Prop\n⊢ {target}"

    def test_attempts_track_depth_and_stale_states_for_the_new_event_shape(self):
        rows = self.ledger(
            [
                ("ref", "r1", None, 0),
                ("b", "r2", self.goal("A"), 2),
                ("c", "r2", self.goal("A"), 2),
                ("d", "r2", self.goal("A  "), 2),
                ("e", "r2", self.goal("B"), 1),
                ("f", "r2", self.goal("B"), 1),
            ]
        )
        row = {item["route"]: item for item in routes.route_table(rows)}["r2"]
        self.assertEqual(
            (row["attempts"], row["depth"], row["new_states"], row["stale_streak"], row["min_holes"]), (5, 2, 2, 1, 1)
        )
        self.assertFalse(row["explored"])
        self.assertFalse(row["credited"])
        self.assertFalse(row["skeleton"])

    def test_route_exploration_and_credit_still_use_goal_states_and_compilation(self):
        deep = self.ledger(
            [
                ("ref", "r1", None, 0),
                ("b", "r2", self.goal("A"), 1),
                ("c", "r2", self.goal("B"), 1),
                ("d", "r2", self.goal("C"), 1),
            ]
        )
        self.assertTrue({row["route"]: row for row in routes.route_table(deep)}["r2"]["explored"])
        done = self.ledger([("ref", "r1", None, 0), ("b", "r2", self.goal("A"), 1), ("c", "r2", None, 0)])
        row = {item["route"]: item for item in routes.route_table(done)}["r2"]
        self.assertEqual((row["compiled"], row["explored"], row["depth"], row["min_holes"]), (True, True, 2, 0))
        self.assertFalse(row["credited"])

    def test_reference_route_and_original_credit_rules_are_stable(self):
        rows = self.ledger([("ref", "r1", None, 0), ("b", "r1", None, 0)])
        row = routes.route_table(rows)[0]
        self.assertEqual(
            (row["original"], row["credited"], row["attempts"], row["depth"], row["stale_streak"]),
            (True, False, 1, 0, 1),
        )

    def test_stale_limit_and_new_goal_state_reset_the_streak(self):
        same = [(f"x{index}", "r2", self.goal("A"), 1) for index in range(routes.STALE_STREAK + 1)]
        rows = self.ledger([("ref", "r1", None, 0), *same])
        row = {item["route"]: item for item in routes.route_table(rows)}["r2"]
        self.assertEqual((row["depth"], row["stale_streak"], row["stale"]), (1, routes.STALE_STREAK, True))
        rows = self.ledger([("ref", "r1", None, 0), *same, ("y", "r2", self.goal("Z"), 1)])
        row = {item["route"]: item for item in routes.route_table(rows)}["r2"]
        self.assertEqual((row["stale_streak"], row["stale"]), (0, False))

    def test_progress_uses_filed_credit_and_new_goal_states(self):
        rows = self.ledger(
            [
                ("ref", "r1", None, 0),
                ("b", "r2", self.goal("A"), 1),
                ("c", "r2", self.goal("A"), 1),
                ("d", "r2", self.goal("B"), 1),
            ]
        )
        table = routes.route_table(rows)
        self.assertEqual(
            routes.progress(table),
            {"credited_routes": 0, "explored_routes": 0, "new_state_attempts": 2, "new_state_share": round(2 / 3, 3)},
        )
        rows = self.ledger([("ref", "r1", None, 0), ("b", "r2", None, 0)])
        self.assertEqual(routes.progress(routes.route_table(rows))["credited_routes"], 1)
        self.assertIsNone(routes.progress([])["new_state_share"])

    def test_failed_candidates_cannot_earn_legacy_event_credit(self):
        rows = self.ledger([("ref", "r1", None, 0), ("b", "r2", self.goal("A"), 2)])
        rows[-1]["credited"] = True
        self.assertFalse({item["route"]: item for item in routes.route_table(rows)}["r2"]["credited"])


if __name__ == "__main__":
    unittest.main()
