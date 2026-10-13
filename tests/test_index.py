import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from arena import engine, index, search
from tests.slow import slow

FIXTURES = Path(__file__).parent / "fixtures"
CORE_ROW = "Core.InitsUpdatesComm"


class IndexLoaderTests(unittest.TestCase):
    def test_build_log_appends_structured_events_beside_the_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "index.sqlite"
            index._log_build(database, "lean_started", timeout_seconds=900)
            index._log_build(database, "build_failed", error="example")
            records = [json.loads(line) for line in database.with_suffix(".log.jsonl").read_text().splitlines()]
            self.assertEqual([record["event"] for record in records], ["lean_started", "build_failed"])
            self.assertEqual(records[0]["timeout_seconds"], 900)
            self.assertEqual(records[1]["error"], "example")

    def test_loader_builds_search_indexes_and_idf_from_jsonl(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "index.sqlite"
            count = index.load_index(FIXTURES / "declaration_index.jsonl", database)
            with sqlite3.connect(database) as connection:
                self.assertEqual(count, 48)
                self.assertEqual(
                    connection.execute("SELECT name FROM declarations WHERE name = 'Nat.add_comm'").fetchone()[0],
                    "Nat.add_comm",
                )
                self.assertGreater(
                    connection.execute("SELECT count(*) FROM trigrams WHERE gram = 'add'").fetchone()[0], 1
                )
                self.assertIsNotNone(
                    connection.execute("SELECT value FROM idf WHERE constant = 'HAppend.hAppend'").fetchone()
                )

    def test_current_file_ranges_drop_only_the_inserted_wrapper_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            records = Path(temporary) / "ranges.jsonl"
            records.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in (
                        {"module": "(this file)", "line": 110, "end_line": 111},
                        {"module": "Imported.Module", "line": 110, "end_line": 111},
                    )
                )
                + "\n"
            )
            index._restore_current_file_lines(records, insertion_line=10, shift=100)
            restored = [json.loads(line) for line in records.read_text().splitlines()]
            self.assertEqual((restored[0]["line"], restored[0]["end_line"]), (10, 11))
            self.assertEqual((restored[1]["line"], restored[1]["end_line"]), (110, 111))


@slow
class LeanIndexTests(unittest.TestCase):
    def test_core_index_searches_imports_and_caches_the_second_build(self):
        result = index.build_index(CORE_ROW)
        self.assertGreater(result["declarations"], 10_000)
        with index.open_index(CORE_ROW) as connection:
            self.assertIsNotNone(
                connection.execute("SELECT 1 FROM declarations WHERE name = 'Nat.add_comm'").fetchone()
            )
            generated = connection.execute(
                "SELECT name FROM declarations WHERE generated = 1 AND name LIKE '%.casesOn' LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(generated)
        names = search.search(CORE_ROW, ["Nat.add_comm", generated[0]], kind="name")
        hits = [hit["name"] for item in names["queries"] for hit in item["hits"]]
        self.assertIn("Nat.add_comm", hits)
        self.assertNotIn(generated[0], hits)
        source = engine.problem(CORE_ROW)["file_path"]
        self.assertTrue(source)
        text_result = search.search(CORE_ROW, ["theorem InitStatesEmpty"], kind="text")
        self.assertTrue(text_result["queries"][0]["hits"])
        self.assertTrue(any(hit["file"] == source for hit in text_result["queries"][0]["hits"]))
        cached = index.build_index(CORE_ROW)
        self.assertTrue(cached["cached"])
