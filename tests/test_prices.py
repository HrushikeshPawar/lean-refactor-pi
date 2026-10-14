"""Pricing units and protocol behavior at the fake-campaign seam."""

import unittest
from unittest.mock import patch

from arena import campaign, prices, scoring
from arena.engine import _proof_length
from arena.graph import Graph, Node, changed_lines, effort_table
from arena.steps import split_steps
from tests.graph_support import FakeRunCase


class PriceUnitTests(unittest.TestCase):
    def test_rates_match_the_published_scoring_axes_without_rounding(self):
        for tokens, heartbeats, total_versions in ((400, 8000, 5), (1200, 30000, 3)):
            expected = {
                "points_per_token": 100 / 3 / tokens,
                "points_per_1k_hb": 100 / 3 / heartbeats * 1000,
                "points_per_version": 100 / 3 / total_versions,
            }
            self.assertEqual(prices.rates(tokens, heartbeats, total_versions), expected)
            with patch("arena.scoring.reference", return_value=(tokens, heartbeats)):
                rounded = scoring.exchange_rates("T", total_versions)
            self.assertEqual(round(expected["points_per_token"], 3), rounded["points_per_token"])
            self.assertEqual(round(expected["points_per_1k_hb"] / 10, 3), rounded["points_per_100_heartbeats"])
            self.assertEqual(round(expected["points_per_version"], 2), rounded["points_per_lost_version"])

    def test_formatters_keep_hb_scale_and_signed_minus(self):
        self.assertEqual(prices.fmt_hb(1234), "1.2K")
        self.assertEqual(prices.fmt_hb(999), "999")
        self.assertEqual(prices.fmt_hb(0), "0")
        self.assertEqual(prices.fmt_signed(4000), "+4.0K")
        self.assertEqual(prices.fmt_signed(-9), "−9")

    def test_step_table_attributes_tokens_and_uses_inclusive_heartbeat_cost(self):
        proof = "theorem t : True := by\n  first\n    nested\n  second\n"
        profile = {
            "token_attribution_available": True,
            "line_tokens": {"2": 2, "3": 3, "4": 1},
            "entries": [
                {"depth": 0, "proof_line": 2, "self_hb": 400, "hb": 1000},
                {"depth": 0, "proof_line": 4, "self_hb": 500, "hb": 2000},
            ],
        }
        table = prices.step_table(proof, profile, prices.rates(10, 10000, 2), 6, 3000, "1 of 2 checked")
        self.assertEqual([row["tokens"] for row in table["rows"]], [5, 1])
        self.assertEqual(sum(row["tokens"] for row in table["rows"]), sum(profile["line_tokens"].values()))
        self.assertEqual(table["rows"][0]["self_hb"], 400)
        self.assertEqual(table["rows"][0]["incl_hb"], 1000)
        self.assertEqual(table["rows"][0]["pts_if_gone"], round(5 * 100 / 30 + 1 * (100 / 30), 2))
        missing = prices.step_table(proof, None, prices.rates(10, 10000, 2), 6, 3000, None)
        self.assertIsNone(missing["rows"][0]["incl_hb"])
        fallback = prices.step_table(
            proof,
            {"token_attribution_available": False, "line_tokens": None, "entries": []},
            prices.rates(10, 10000, 2),
            6,
            None,
            None,
        )
        self.assertEqual(fallback["rows"][0]["tokens"], prices.snippet_tokens("first\n  nested"))
        self.assertEqual(fallback["rows"][0]["pts_if_gone"], round(fallback["rows"][0]["tokens"] * 100 / 30, 2))

    def test_changed_lines_counts_replacements_and_insertions(self):
        self.assertEqual(changed_lines("a\nb\nc\n", "a\nx\nc\ny\n"), 2)

    def test_changed_steps_reports_replacements_insertions_and_deletions(self):
        original = split_steps("theorem t := by\n  exact True.intro\n  rfl\n")
        replaced = split_steps("theorem t := by\n  trivial\n  rfl\n")
        inserted = split_steps("theorem t := by\n  exact True.intro\n  rfl\n  trivial\n")
        deleted = split_steps("theorem t := by\n  exact True.intro\n")
        self.assertEqual(len(prices.changed_steps(original, replaced)), 1)
        self.assertEqual(len(prices.changed_steps(original, inserted)), 1)
        self.assertEqual(len(prices.changed_steps(original, deleted)), 1)
        hb_change = prices.changed_steps(original, replaced, {"s1": 100, "s2": 200}, {"s1": 80, "s2": 250})
        self.assertEqual((hb_change[0]["old_hb"], hb_change[0]["new_hb"]), (100, 80))

    def test_effort_table_counts_variants_and_only_closed_one_for_one_gains(self):
        from arena.routes import signature

        def node(ident, proof, score, status="closed", origin="model", parent=None):
            return Node(
                id=ident,
                proof_id=ident,
                status=status,
                origin=origin,
                score=score,
                verified=False,
                tokens=10,
                heartbeats=100,
                versions={},
                edge={"from": [parent]} if parent else None,
                steps=split_steps(proof),
                depth=0,
                route="r1",
                signature=signature(proof),
                label=ident,
                holes=[],
                proof_text=proof,
            )

        original = "theorem t := by\n  alpha\n  omega\n"
        improved = "theorem t := by\n  long_variant\n  omega\n"
        broken = "theorem t := by\n  failed_variant\n  omega\n"
        reference = node("ref", original, 10, origin="reference")
        best = node("best", original, 20, parent="ref")
        variant = node("variant", improved, 15, parent="ref")
        failed = node("failed", broken, None, status="broken", parent="ref")
        graph = Graph([reference, best, variant, failed], None, [n.id for n in (reference, best, variant, failed)], [])
        table = {"best": {"rows": [{"pts_if_gone": 2.4}, {"pts_if_gone": 1.1}]}}
        rows = effort_table(graph, table)
        self.assertEqual(rows[0]["variants"], 2)
        self.assertEqual(rows[0]["best_dtok"], prices.snippet_tokens("long_variant") - prices.snippet_tokens("alpha"))
        self.assertEqual(rows[0]["last_gain"], 1)
        self.assertEqual(rows[0]["at_stake"], 2.4)
        self.assertEqual(rows[1]["variants"], 0)
        self.assertIsNone(rows[1]["last_gain"])


class ProfileLaneTests(unittest.TestCase):
    def test_profile_passes_the_selected_lane_to_instrumentation(self):
        from arena import profile as profile_module

        proof = "theorem t := by\n  trivial"
        record = {
            "file_line": 1,
            "column": 1,
            "depth": 0,
            "end_file_line": 1,
            "end_proof_line": 1,
            "proof_line": 1,
            "hb": 10,
            "self_hb": 10,
            "calls": 1,
        }
        built = {"text": proof, "start_line": 1}
        with (
            patch.object(profile_module, "problem", return_value={"name": "T", "statement": "theorem t"}),
            patch.object(profile_module, "measure_version", return_value=("v1", "commit")),
            patch.object(profile_module, "versions", return_value=[("v1", "commit")]),
            patch.object(
                profile_module, "exchange_rates", return_value={"reference_tokens": 1, "reference_heartbeats": 1}
            ),
            patch.object(profile_module, "_line_token_counts", return_value=None),
            patch.object(
                profile_module, "_instrumented", return_value=([record.copy()], 10, built, "")
            ) as instrumented,
        ):
            profile_module.profile("T", proof, measured=10, lane="background")
        self.assertEqual(instrumented.call_args.args[-1], "background")


class QuoteTests(unittest.TestCase):
    def test_quotes_drafts_and_snippets_per_item_without_lean(self):
        statement = "theorem t : True"
        complete = statement + " := by\n  trivial"
        with (
            patch.object(campaign, "problem", return_value={"name": "T", "statement": statement}),
            patch("arena.engine.evaluate", side_effect=AssertionError("Lean path used")),
            patch("arena.campaign.subprocess", side_effect=AssertionError("subprocess used")),
        ):
            reply = prices.quote_tokens("T", ["trivial", "by\n  trivial", 17, "exact True.intro"], statement=statement)
            self.assertEqual(
                reply["items"][0],
                {"index": 0, "kind": "snippet", "tokens": _proof_length("theorem x : True := trivial"), "delta": None},
            )
            self.assertEqual(reply["items"][1]["kind"], "draft")
            self.assertEqual(
                reply["items"][1]["tokens"], _proof_length(campaign.normalize_draft("T", "by\n  trivial"), statement)
            )
            self.assertEqual(
                _proof_length(complete, statement), _proof_length(campaign.normalize_draft("T", complete), statement)
            )
        self.assertEqual(reply["items"][2]["error"], "item 2 is not text (got int); pass a list of strings")
        self.assertEqual(reply["items"][3]["kind"], "snippet")

    def test_snippet_delta_compares_with_the_supplied_step_text(self):
        against = "exact True.intro"
        result = prices.quote_tokens("T", ["trivial"], {"text": against}, "theorem t : True")
        self.assertEqual(result["items"][0]["delta"], prices.snippet_tokens("trivial") - prices.snippet_tokens(against))


class CampaignPriceTests(FakeRunCase):
    def test_compiled_reply_carries_a_price_row_from_the_filing_parent(self):
        result = self.evaluate("theorem t := by\n  exact True.intro")
        self.assertTrue(result["ok"])
        self.assertIn("price_row", result)
        self.assertIn("n2 from n1", result["price_row"])
        self.assertIn("versions 1 of 2 checked", result["price_row"])

    def test_price_row_filing_parent_and_named_parent_metrics_keep_distinct_deltas(self):
        values = {
            "two": (90, 900, 85.0),
            "three": (95, 850, 83.0),
        }

        def evaluate(_name, proof, mode, known=None):
            tokens, heartbeats, score = values["three" if "three" in proof else "two"]
            checked = 2 if mode == "full" else 1
            compat = {
                "v1": {"passed": True, "diagnostics": []},
            }
            if mode == "full":
                compat["v2"] = {"passed": True, "diagnostics": []}
            return {
                "ok": True,
                "mode": mode,
                "tokens": tokens,
                "heartbeat": heartbeats,
                "compat": compat,
                "metrics": {
                    "tokens": tokens,
                    "heartbeats": heartbeats,
                    "compiled": True,
                    "axes": {
                        "tokens": {"value": tokens},
                        "heartbeats": {"value": heartbeats},
                        "compat": {"passed": checked, "checked": checked, "total": 2},
                    },
                    "estimated_proxy": score,
                    "proxy": score if mode == "full" else None,
                    "deltas": {},
                },
            }

        with patch.object(campaign, "evaluate", side_effect=evaluate):
            self.evaluate("theorem t := by\n  two", parents=["#1"])
            third = self.evaluate("theorem t := by\n  two\n  three", parents=["#1"])
            full = self.evaluate("theorem t := by\n  two\n  three", mode="full", parents=["#1"])

        self.assertEqual(third["candidate"], "#3")
        self.assertIn("n3 from n2", third["price_row"])
        self.assertIn("tokens 95 (+5 vs n2)", third["price_row"])
        self.assertIn("heartbeats 850 (−50)", third["price_row"])
        self.assertIn("score -2.0 vs best", third["price_row"])
        self.assertIn("versions 1 of 2 checked", third["price_row"])
        self.assertEqual(third["metrics"]["axes"]["tokens"]["value"], third["tokens"])
        self.assertEqual(third["metrics"]["axes"]["heartbeats"]["value"], third["heartbeat"])
        self.assertEqual(third["metrics"]["axes"]["compat"], {"passed": 1, "checked": 1, "total": 2})

        vs_best = third["metrics"]["deltas"]["vs_best"]
        self.assertEqual(vs_best["candidate"], "#2")
        self.assertEqual(vs_best["tokens"], 5)
        self.assertEqual(vs_best["heartbeats"], -50)
        self.assertEqual(vs_best["proxy"], -2.0)
        vs_parent = third["metrics"]["deltas"]["vs_parent"]
        self.assertEqual(vs_parent["candidate"], "#1")
        reference = campaign._summaries(campaign.events(campaign.run_dir("logic")))[0]
        self.assertEqual(vs_parent["tokens"], third["tokens"] - reference["tokens"])
        self.assertEqual(vs_parent["heartbeats"], third["heartbeat"] - reference["heartbeats"])
        self.assertEqual(vs_parent["proxy"], third["metrics"]["estimated_proxy"] - reference["score"])
        self.assertIn("versions 2/2", full["price_row"])
        self.assertEqual(full["metrics"]["axes"]["compat"], {"passed": 2, "checked": 2, "total": 2})

    def test_prices_reads_cached_data_and_quote_does_not_append_events(self):
        self.evaluate("theorem t := by\n  exact True.intro")
        with (
            patch("arena.scoring.reference", return_value=(10, 10000)),
            patch("arena.engine.evaluate", side_effect=AssertionError("Lean evaluation used")),
            patch.object(campaign, "profile", side_effect=AssertionError("profile compile used")),
        ):
            table = campaign.price_table("T", "logic")
        self.assertFalse(table["profiled"])
        self.assertIn("total", table["text"])
        self.assertTrue(all(row["incl_hb"] is None for row in table["rows"]))
        before = len(campaign.events(campaign.run_dir("logic")))
        response = prices.quote_tokens("T", ["trivial"], statement="theorem t : True")
        self.assertEqual(response["items"][0]["kind"], "snippet")
        self.assertEqual(len(campaign.events(campaign.run_dir("logic"))), before)

    def test_map_contains_effort_rows_from_the_existing_graph_projection(self):
        self.evaluate("theorem t := by\n  x")
        with patch("arena.scoring.reference", return_value=(10, 10000)):
            result = campaign.map_view("logic")
        self.assertEqual(len(result["effort"]), len(split_steps("theorem t := by\n  x")))
        self.assertIn("at_stake", result["effort"][0])

    def test_autocheck_profiles_archive_best_in_background_once(self):
        self.evaluate("theorem t := by\n  x")
        with (
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
            patch.object(campaign, "profile", return_value={"entries": [], "ok": True}) as profile,
            patch.object(campaign, "_autocheck_jobs", return_value=[]),
            patch.object(campaign, "_step_goal_jobs", return_value=[]),
        ):
            campaign.autocheck("T", "logic")
            self.assertEqual(profile.call_count, 1)
            self.assertEqual(profile.call_args.kwargs["lane"], "background")
            campaign.autocheck("T", "logic")
            self.assertEqual(profile.call_count, 1)
            with patch("arena.scoring.reference", return_value=(10, 10000)):
                self.assertTrue(campaign.price_table("T", "logic")["profiled"])

    def test_profile_failure_is_recorded_and_not_retried(self):
        self.evaluate("theorem t := by\n  x")
        with (
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
            patch.object(campaign, "profile", side_effect=ValueError("profile failed")) as profile,
            patch.object(campaign, "_autocheck_jobs", return_value=[]),
            patch.object(campaign, "_step_goal_jobs", return_value=[]),
        ):
            campaign.autocheck("T", "logic")
            campaign.autocheck("T", "logic")
        self.assertEqual(profile.call_count, 1)
        self.assertTrue(
            any(event.get("kind") == "profile_error" for event in campaign.events(campaign.run_dir("logic")))
        )
        self.assertEqual(profile.call_count, 1)

    def test_closing_drain_skips_profiles(self):
        self.evaluate("theorem t := by\n  x")
        with (
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
            patch.object(campaign, "profile", side_effect=AssertionError("profile compile used")) as profile,
            patch.object(campaign, "_autocheck_jobs", return_value=[]),
        ):
            campaign.autocheck("T", "logic", closing=True)
        self.assertEqual(profile.call_count, 0)
        kinds = {event.get("kind") for event in campaign.events(campaign.run_dir("logic"))}
        self.assertFalse(kinds & {"profile", "profile_error"})

    def test_profile_os_error_is_recorded_and_not_retried(self):
        self.evaluate("theorem t := by\n  x")
        with (
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
            patch.object(campaign, "profile", side_effect=OSError("disk gone")) as profile,
            patch.object(campaign, "_autocheck_jobs", return_value=[]),
            patch.object(campaign, "_step_goal_jobs", return_value=[]),
        ):
            self.assertTrue(campaign.autocheck("T", "logic")["ok"])
            self.assertTrue(campaign.autocheck("T", "logic")["ok"])
        self.assertEqual(profile.call_count, 1)
        errors = [event for event in campaign.events(campaign.run_dir("logic")) if event.get("kind") == "profile_error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("disk gone", errors[0]["error"])
        self.assertIn("seconds", errors[0])


if __name__ == "__main__":
    unittest.main()
