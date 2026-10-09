import copy
import json
import unittest

from arena import models

GOOD = models.load()


class ModelConfigTests(unittest.TestCase):
    def broken(self, edit):
        config = copy.deepcopy(GOOD)
        edit(config)
        with self.assertRaises(models.ModelConfigError):
            models.validate(config)

    def test_repo_file_loads_with_every_model_complete(self):
        self.assertEqual(models.models(), ("gpt-6-luna", "qwen3.8-flash", "deepseek-v4.1-flash"))
        for row in GOOD["models"].values():
            self.assertLess(row["compaction"]["at_tokens"], row["context_window"])
        self.assertLessEqual(GOOD["models"]["gpt-6-luna"]["compaction"]["at_tokens"],
                             GOOD["models"]["gpt-6-luna"]["high_context_threshold"])

    def test_pi_max_tokens_is_the_enforced_output_limit(self):
        # Pi compacts on a `length` stop below the maxTokens it knows; arena.ts advertises the enforced limit.
        for name, row in GOOD["models"].items():
            self.assertLessEqual(row["request_output_tokens"], row["max_tokens"], name)
            self.assertEqual(json.loads(models.pi_json())["models"][name]["requestOutputTokens"],
                             row["request_output_tokens"], name)
        self.assertEqual(GOOD["models"]["deepseek-v4.1-flash"]["request_output_tokens"], 64000)

    def test_deepseek_compaction_leaves_room_for_summary_and_output_turn(self):
        row = GOOD["models"]["deepseek-v4.1-flash"]
        self.assertEqual(row["compaction"]["at_tokens"], 850000)
        reserve = row["context_window"] - row["compaction"]["at_tokens"]  # Pi: compact when context > window - reserve
        overshoot = 25000  # one turn of tool results past the trigger
        summary_cap = int(0.8 * reserve)  # Pi caps the summary output at 0.8 * reserveTokens
        self.assertLess(row["compaction"]["at_tokens"] + overshoot + summary_cap, row["context_window"])
        self.assertLess(row["compaction"]["at_tokens"] + overshoot + row["request_output_tokens"], row["context_window"])

    def test_required_keys_and_positive_numbers(self):
        luna = lambda config: config["models"]["gpt-6-luna"]
        self.broken(lambda c: c.pop("provider"))
        self.broken(lambda c: luna(c).pop("price"))
        self.broken(lambda c: luna(c).pop("context_window"))
        self.broken(lambda c: luna(c).update(max_tokens=0))
        self.broken(lambda c: luna(c).update(request_output_tokens=-1))
        self.broken(lambda c: luna(c)["price"].update(input=-0.1))
        self.broken(lambda c: luna(c)["price"].pop("cache_read"))
        self.broken(lambda c: luna(c).pop("high_context_threshold"))
        self.broken(lambda c: luna(c)["compaction"].update(at_tokens=luna(c)["context_window"]))
        self.broken(lambda c: luna(c).pop("compaction"))
        self.broken(lambda c: c["thinking"].update(default="extreme"))
        self.broken(lambda c: c["presets"]["v6-matrix"]["models"].append("nope"))

    def test_parser_subset(self):
        text = "a: 10\nb:\n  c: [x, 'y, z']  # comment\n  d: {e: 0.5, f: true}\n"
        self.assertEqual(models.parse(text),
                         {"a": 10, "b": {"c": ["x", "y, z"], "d": {"e": 0.5, "f": True}}})
        with self.assertRaises(models.ModelConfigError):
            models.parse("just text")

    def test_pi_json_uses_camel_case_keys(self):
        luna = json.loads(models.pi_json())["models"]["gpt-6-luna"]
        self.assertEqual(luna["highPrice"]["cacheRead"], GOOD["models"]["gpt-6-luna"]["high_price"]["cache_read"])
        self.assertEqual(luna["compaction"]["atTokens"], GOOD["models"]["gpt-6-luna"]["compaction"]["at_tokens"])


if __name__ == "__main__":
    unittest.main()
