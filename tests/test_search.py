import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import engine, index, search

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_ROOT = FIXTURES / "index_sources"
ROW_NAME = "Core.InitsUpdatesComm"
ROW = {
    "name": ROW_NAME,
    "source": "fixture",
    "file_path": "Core.lean",
    "src": "theorem Core.InitsUpdatesComm : True := by trivial",
    "statement": "theorem Core.InitsUpdatesComm : 𝔽q",
    "version_info": [{"v4.29.1": "fixture-commit"}],
}


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "index.sqlite"
        index.load_index(FIXTURES / "declaration_index.jsonl", self.database)
        self.patches = [
            patch.object(index, "index_path", return_value=self.database),
            patch.object(index, "open_index", side_effect=self._open_index),
            patch.object(engine, "problem", return_value=ROW),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def _open_index(self, _theorem, _version=None):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def test_name_order_keeps_exact_suffix_prefix_and_fuzzy_classes_separate(self):
        result = search.search(ROW_NAME, ["add_comm"])["queries"][0]
        hits = result["hits"]
        self.assertEqual(
            [(hit["name"], hit["why"]) for hit in hits[:5]],
            [
                ("add_comm", "exact"),
                ("Nat.add_comm", "suffix"),
                ("Other.add_comm", "suffix"),
                ("add_comm_extra", "prefix"),
                ("Extra.add_commute", "prefix"),
            ],
        )
        self.assertIn(("Nat.ad_comm", "fuzzy"), [(hit["name"], hit["why"]) for hit in hits])

    def test_generated_and_private_declarations_are_filtered_from_name_type_and_text(self):
        name_result = search.search(ROW_NAME, ["Foo.casesOn"], kind="name")["queries"][0]
        type_result = search.search(ROW_NAME, ["Foo.casesOn"], kind="type")["queries"][0]
        self.assertFalse(any(hit["name"] == "Foo.casesOn" for hit in name_result["hits"]))
        self.assertEqual(type_result["error"]["code"], "no_constants")
        self._enable_fixture_text()
        hidden = search.search(ROW_NAME, ["arena-private-proof-marker"], kind="text")["queries"][0]
        self.assertEqual(hidden["hits"], [])
        self.assertEqual(hidden["dropped"], 1)

    def test_confusable_returns_lookalike_and_codepoint_hint(self):
        exact = search.search(ROW_NAME, ["ℱq"])["queries"][0]
        self.assertEqual(exact["hits"][0]["name"], "ℱq")
        self.assertEqual(exact["hits"][0]["why"], "exact")
        result = search.search(ROW_NAME, ["Fq"])["queries"][0]
        self.assertEqual(
            [(hit["name"], hit["why"]) for hit in result["hits"][:2]],
            [("Foo.Fq", "suffix"), ("𝔽q", "confusable")],
        )
        self.assertEqual(result["hint"]["name"], "𝔽q")
        self.assertIn(ord("F"), result["hint"]["query_char_codes"])

    def test_type_overlap_ranks_the_combined_length_and_append_declaration_first(self):
        result = search.search(ROW_NAME, ["List.length HAppend.hAppend"], kind="type")["queries"][0]
        self.assertEqual(result["hits"][0]["name"], "List.length_append")
        self.assertEqual(result["hits"][0]["why"], "type")

    @unittest.skipUnless(shutil.which("rg"), "rg is required for source text search")
    def test_text_maps_source_lines_to_declarations_and_drops_private_lines(self):
        self._enable_fixture_text()
        result = search.search(ROW_NAME, ["arena-index-proof-marker"], kind="text")["queries"][0]
        self.assertEqual([hit["handle"] for hit in result["hits"]], ["decl:Nat.add_comm"])
        self.assertEqual(result["hits"][0]["why"], "text")

    def test_completions_are_one_namespace_level_and_shortest_first(self):
        result = search.search(ROW_NAME, ["add"], after="Nat")["queries"][0]
        self.assertEqual([hit["name"] for hit in result["hits"]], ["Nat.add_comm", "Nat.add_assoc"])
        self.assertTrue(all(hit["why"] == "completion" for hit in result["hits"]))

    def test_batch_keeps_one_empty_query_error_and_the_next_query_hits(self):
        result = search.search(ROW_NAME, ["", "Nat.add_comm"])
        self.assertEqual(result["queries"][0]["error"]["code"], "empty_query")
        self.assertEqual(result["queries"][1]["hits"][0]["name"], "Nat.add_comm")

    def test_empty_query_error_is_preserved_when_the_index_is_missing(self):
        with patch.object(index, "index_path", return_value=None):
            result = search.search(ROW_NAME, ["", "Nat.add_comm"])
        self.assertEqual(result["queries"][0]["error"]["code"], "empty_query")
        self.assertEqual(result["queries"][1]["error"]["code"], "no_index")

    def test_decl_handle_resolves_generated_and_private_names_for_read(self):
        generated = search.resolve_handle(ROW_NAME, "decl:Foo.casesOn")
        private = search.resolve_handle(ROW_NAME, "decl:Private.hidden")
        assert generated is not None
        assert private is not None
        self.assertTrue(generated["generated"])
        self.assertTrue(private["private"])
        self.assertEqual(search.resolve_handle(ROW_NAME, "source:Nat.add_comm"), None)

    def _enable_fixture_text(self):
        self.addCleanup(patch.stopall)
        patch.object(engine, "workspace", return_value=SOURCE_ROOT).start()
        patch.object(search.campaign, "_roots", return_value=[(SOURCE_ROOT, "fixture-commit", "")]).start()
        patch.object(search.Path, "home", return_value=Path(self.temporary.name)).start()
