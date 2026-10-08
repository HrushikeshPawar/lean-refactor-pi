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
