"""Canonical host-summary facts come from real kernel producers."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HostSummaryTests(unittest.TestCase):
    def test_summary_operations_and_child_input(self):
        fixture = json.loads((ROOT / "fixtures/host_summary_requests.json").read_text())
        self.assertEqual(fixture["record_schema_version"], 1)
        self.assertEqual(fixture["inbox_schema_version"], 3)
        self.assertFalse(fixture["parent_replaced_for_child"])
        self.assertEqual(len(fixture["vectors"]), 2)
        manual, child = (v["wire"] for v in fixture["vectors"])
        for case in (manual, child):
            plan = case["summary_plan"]
            self.assertEqual(plan["kind"], "op_planned")
            self.assertEqual(plan["payload"]["purpose"], "compaction")
            self.assertEqual(plan["payload"]["request"]["tools"], [])
            self.assertRegex(plan["payload"]["request"]["metadata"]["source_digest"], r"^[a-f0-9]{64}$")
            self.assertEqual(case["summary_usage"]["prompt_tokens"], 12000)
        self.assertTrue(manual["tool_result"]["metadata"]["request_compaction"])
        self.assertIn("compaction_source", manual["tool_result"]["metadata"])
        self.assertEqual(len(manual["context_replacements"]), 1)
        self.assertEqual(child["context_replacements"], [])
        self.assertEqual(child["summary_plan"]["payload"]["request"]["metadata"]["mode"], "child_summary")
        self.assertIn("Compressed Agent Memory", child["child_input"])
        self.assertIn("Continue the task", child["child_input"])
