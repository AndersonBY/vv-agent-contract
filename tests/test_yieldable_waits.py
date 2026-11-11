"""Independent assertions on Python-produced observation receipts and closed shapes."""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from session_validation import validate_schema, ValidationError


class YieldableWaitsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / "fixtures/yieldable_waits.json").read_text())
        self.schema = json.loads((ROOT / "fixtures/session_record.schema.json").read_text())

    def test_real_producer_receipts_and_model_order(self):
        self.assertEqual(self.fixture["schema_version"], 1)
        self.assertEqual([c["name"] for c in self.fixture["cases"]], [
            "single_child", "child_batch", "provider", "terminal_before_steer",
            "provider_recovered", "completed_and_waiting",
        ])
        for case in self.fixture["cases"]:
            with self.subTest(case=case["name"]):
                for record in case["records"]:
                    validate_schema(record, self.schema)
                completions = [r for r in case["records"] if r["kind"] == "op_completed"]
                self.assertEqual(len(completions), 1)
                self.assertEqual(case["completed_events"], ["tool_call_completed"])
                messages = case["next_messages"]
                tool_index = next(i for i, m in enumerate(messages) if m["role"] == "tool")
                steer_index = next(i for i, m in enumerate(messages) if m["content"] == "Change direction now")
                self.assertLess(tool_index, steer_index)
                if case["name"] == "terminal_before_steer":
                    self.assertNotIn("yielded_by", completions[0]["payload"])
                    self.assertEqual(case["child_running_at_yield"], [])
                    self.assertFalse(case["atomic_yield"])
                else:
                    self.assertTrue(case["atomic_yield"])
                    self.assertEqual(completions[0]["payload"]["yielded_by"], "steer")
                    self.assertIn("steer/steer", completions[0]["payload"]["evidence"])
                    self.assertEqual(completions[0]["payload"]["context"], "normal")
                if case["name"] in {"single_child", "child_batch"}:
                    self.assertIn("observed work has not been stopped", messages[tool_index]["content"])
                    self.assertIn("running_children", messages[tool_index]["content"])
                    notices = [r for r in case["records"] if r["payload"].get("reason") == "background child notification"]
                    self.assertEqual(len(notices), len(case["child_running_at_yield"]))

    def test_new_declarations_are_strict_and_optional(self):
        park = next(r for r in self.fixture["cases"][0]["records"] if r["kind"] == "op_parked")
        for value in (False, 1, "true", None):
            bad = copy.deepcopy(park)
            bad["payload"]["yield_on_steer"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_schema(bad, self.schema)
        old = copy.deepcopy(park)
        old["payload"].pop("yield_on_steer")
        old["payload"].pop("yieldable_children")
        validate_schema(old, self.schema)
        bad = copy.deepcopy(park)
        bad["payload"]["unknown_yield_field"] = True
        with self.assertRaises(ValidationError):
            validate_schema(bad, self.schema)

    def test_recovered_acceptance_and_terminal_callback_facts(self):
        cases = {c["name"]: c for c in self.fixture["cases"]}
        recovered = cases["provider_recovered"]
        item = recovered["recovery_input"]
        inbox_schema = json.loads((ROOT / "fixtures/session_inbox.schema.json").read_text())
        validate_schema(item, inbox_schema)
        self.assertIs(item["payload"]["yield_on_steer"], True)
        for value in (False, 1, None, "true"):
            bad = copy.deepcopy(item)
            bad["payload"]["yield_on_steer"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_schema(bad, inbox_schema)
        park = next(r for r in recovered["records"] if r["kind"] == "op_parked")
        self.assertIs(park["payload"]["yield_on_steer"], True)
        observed = cases["completed_and_waiting"]["callback_handles"]
        self.assertEqual(observed[0]["status"], "completed")
        self.assertEqual(observed[0]["result"], "yield-child-0 done")
        self.assertGreater(observed[0]["terminal_seq"], 0)
        self.assertRegex(observed[0]["terminal_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(observed[1]["status"], "running")
        self.assertNotIn("result", observed[1])
