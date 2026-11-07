"""Independent semantics of real artifact-search producer vectors."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HINT = "Artifact line numbers can be used directly with read_file start_line/end_line."


class ArtifactSearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / "fixtures/artifact_search.json").read_text())

    def test_separate_engine_and_request_budgets(self):
        self.assertEqual(
            self.fixture["rules"]["regex_budget"],
            "250ms_per_engine_call_10s_cumulative_thread_cpu_engine_interrupt",
        )

    def test_matching_and_original_line_numbers(self):
        cases = self.fixture["cases"]
        for name, line, expected in [
            ("hit", 2, "needle here"),
            ("cjk", 2, "找到汉字"),
            ("emoji", 2, "🙂🚀"),
            ("crlf", 2, "needle"),
            ("line_numbers", 3001, "needle"),
        ]:
            with self.subTest(name=name):
                result = cases[name]["result"]
                self.assertEqual(result["status_code"], "SUCCESS")
                column = result["metadata"]["artifact_search"]["matches"][0]["column"]
                self.assertIn(f"\n{line}:{column}: {expected}\n", result["content"])
                self.assertTrue(result["content"].endswith(HINT))
                self.assertNotIn("artifact", result)
                self.assertNotIn("truncated", result)
        empty = cases["no_hit"]["result"]["metadata"]["artifact_search"]
        self.assertEqual(empty["matched_lines"], 0)
        self.assertFalse(empty["truncated"])

    def test_denials_and_unavailability(self):
        for name, code in [
            ("denied", "artifact_search_denied"),
            ("other_session", "artifact_search_denied"),
            ("missing", "artifact_unavailable"),
            ("invalid_path", "artifact_search_denied"),
            ("invalid_regex", "invalid_arguments"),
        ]:
            result = self.fixture["cases"][name]["result"]
            self.assertEqual(result["status_code"], "ERROR")
            self.assertEqual(result["error_code"], code)
            self.assertNotIn("artifact", result)

    def test_hard_budgets_and_explicitly_incomplete_oversized_line(self):
        for name in ("long_line", "budget_lines", "budget_chars"):
            result = self.fixture["cases"][name]["result"]
            self.assertLessEqual(len(result["content"]), 30000)
            self.assertLessEqual(len(result["content"].splitlines()), 500)
            self.assertTrue(result["metadata"]["artifact_search"]["truncated"])
            self.assertIn("Search truncated", result["content"])
            self.assertIn("read_file", result["content"])
        oversized = self.fixture["cases"]["long_line"]["result"]
        self.assertEqual(oversized["metadata"]["artifact_search"]["oversized_line"], 1)
        self.assertEqual(oversized["metadata"]["artifact_search"]["matched_lines"], 1)
        self.assertIn("4096-character overlap", oversized["content"])
        self.assertGreater(
            len(self.fixture["cases"]["budget_chars"]["result"]["content"]), 12000
        )

    def test_late_keyword_readback_and_current_compaction_scope(self):
        hit = self.fixture["cases"]["late_keyword"]["result"]["metadata"][
            "artifact_search"
        ]["matches"][0]
        self.assertEqual((hit["line"], hit["column"]), (1, 40000))
        page = self.fixture["readback"]
        self.assertEqual(page["arguments"]["start_char"], hit["column"])
        self.assertTrue(page["result"]["content"].startswith("needle end"))
        self.assertEqual(
            page["result"]["visible_bytes"],
            len(page["result"]["content"].encode("utf-8")),
        )
        self.assertGreaterEqual(
            page["result"]["original_bytes"], page["result"]["visible_bytes"]
        )
        self.assertEqual(
            page["model_message"].rpartition("\n")[0], page["result"]["content"]
        )
        self.assertEqual(page["result"]["cursor"]["offset_chars"], 52000)
        self.assertEqual(
            page["result"]["metadata"]["read_page"],
            {"next_line": 1, "next_start_char": 52000},
        )
        self.assertIn("start_char=52000", page["model_message"])
        self.assertEqual(
            self.fixture["cases"]["compaction"]["result"]["status_code"], "SUCCESS"
        )
