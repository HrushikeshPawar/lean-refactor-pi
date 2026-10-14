import copy
import json
import tempfile
import unittest
from pathlib import Path

from arena import models

GOOD = models.load()


class ModelConfigTests(unittest.TestCase):
    def broken(self, edit):
        config = copy.deepcopy(GOOD)
        edit(config)
        with self.assertRaises(models.ModelConfigError):
            models.validate(config)

    def test_pi_max_tokens_is_the_enforced_output_limit(self):
        # Pi compacts on a `length` stop below the maxTokens it knows; arena.ts advertises the enforced limit.
        for name, row in GOOD["models"].items():
            self.assertLessEqual(row["request_output_tokens"], row["max_tokens"], name)
            self.assertEqual(
                json.loads(models.pi_json())["models"][name]["requestOutputTokens"], row["request_output_tokens"], name
            )

    def test_deepseek_compaction_leaves_room_for_summary_and_output_turn(self):
        row = GOOD["models"]["deepseek-v4.1-flash"]
        reserve = row["context_window"] - row["compaction"]["at_tokens"]  # Pi: compact when context > window - reserve
        overshoot = 25000  # one turn of tool results past the trigger
        summary_cap = int(0.8 * reserve)  # Pi caps the summary output at 0.8 * reserveTokens
        self.assertLess(row["compaction"]["at_tokens"] + overshoot + summary_cap, row["context_window"])
        self.assertLess(
            row["compaction"]["at_tokens"] + overshoot + row["request_output_tokens"], row["context_window"]
        )

    def test_required_keys_and_positive_numbers(self):
        def model(config):
            return config["models"]["deepseek-v4.1-flash"]

        self.broken(lambda c: c.pop("provider"))
        self.broken(lambda c: model(c).pop("price"))
        self.broken(lambda c: model(c).pop("context_window"))
        self.broken(lambda c: model(c).update(max_tokens=0))
        self.broken(lambda c: model(c).update(request_output_tokens=-1))
        self.broken(lambda c: model(c)["price"].update(input=-0.1))
        self.broken(lambda c: model(c)["price"].pop("cache_read"))
        self.broken(lambda c: model(c)["compaction"].update(at_tokens=model(c)["context_window"]))
        self.broken(lambda c: model(c).pop("compaction"))
        self.broken(lambda c: c["thinking"].update(default="extreme"))
        self.broken(lambda c: c["presets"]["v6-matrix"]["models"].append("nope"))

    def test_parser_subset(self):
        text = "a: 10\nb:\n  c: [x, 'y, z']  # comment\n  d: {e: 0.5, f: true}\n"
        self.assertEqual(models.parse(text), {"a": 10, "b": {"c": ["x", "y, z"], "d": {"e": 0.5, "f": True}}})
        with self.assertRaises(models.ModelConfigError):
            models.parse("just text")

    def test_pi_json_uses_camel_case_keys(self):
        row = json.loads(models.pi_json())["models"]["deepseek-v4.1-flash"]
        self.assertEqual(
            row["compaction"]["atTokens"], GOOD["models"]["deepseek-v4.1-flash"]["compaction"]["at_tokens"]
        )

    def test_retry_and_optional_tool_turn_effort_are_validated_and_exported(self):
        self.assertEqual(GOOD["retry"], {"max_retries": 3, "base_delay_ms": 2000, "max_delay_ms": 60000})
        self.assertEqual(json.loads(models.pi_json())["models"]["mimo-v2.6-pro"]["toolTurnReasoningEffort"], "high")
        self.broken(lambda config: config["models"]["mimo-v2.6-pro"].update(tool_turn_reasoning_effort=""))
        self.broken(lambda config: config["retry"].update(base_delay_ms=0))


if __name__ == "__main__":
    unittest.main()


class ProviderTests(unittest.TestCase):
    def test_registered_providers_carry_the_key_by_name_and_price_from_models_yaml(self):
        registered = models.pi_providers(GOOD)["primalabs"]
        self.assertEqual(registered["apiKey"], "$PL_API_KEY")  # Pi interpolates it; the value never enters the config
        (mimo,) = registered["models"]
        self.assertEqual(mimo["id"], "primalabs-ai/MiMo-V2.6-Pro")
        self.assertEqual(mimo["cost"]["cacheRead"], GOOD["models"]["mimo-v2.6-pro"]["price"]["cache_read"])
        self.assertEqual(models.pi_model("mimo-v2.6-pro", GOOD), "primalabs/primalabs-ai/MiMo-V2.6-Pro")

    def test_a_model_must_name_a_known_provider(self):
        config = copy.deepcopy(GOOD)
        config["models"]["mimo-v2.6-pro"]["provider"] = "nowhere"
        with self.assertRaises(models.ModelConfigError):
            models.validate(config)

    def test_catalog_drift_is_reported_and_registered_providers_are_exempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            install = home / ".pi/agent/install"
            data = install / "releases/9.9.9/node_modules/@earendil-works/pi-ai/dist/providers/data"
            data.mkdir(parents=True)
            (install / "current-version").write_text("9.9.9\n")
            price = {"input": 0.15, "output": 0.60, "cacheRead": 0.003, "cacheWrite": 0}
            row = {"id": "deepseek-v4.1-flash", "cost": price}
            (data / "opencode-go.json").write_text(json.dumps({"openai-completions": {"chat:x": row}}))
            self.assertEqual(models.catalog_price_problems(GOOD, home), [])
            row["cost"] = {**price, "output": 0.30}
            (data / "opencode-go.json").write_text(json.dumps({"openai-completions": {"chat:x": row}}))
            (problem,) = models.catalog_price_problems(GOOD, home)
            self.assertIn("deepseek-v4.1-flash", problem)

    def test_no_installed_pi_means_no_price_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(models.catalog_price_problems(GOOD, Path(temporary)), [])
