"""Check the real Python producer evidence for the frozen creation policy."""

import json
import unittest
from pathlib import Path


class UnseenInputContractTests(unittest.TestCase):
    def test_callbacks_after_snapshots_reach_the_next_request(self):
        fixture = json.loads(
            (
                Path(__file__).parents[1] / "fixtures" / "unseen_input_protection.json"
            ).read_text()
        )
        cases = {case["case"]: case for case in fixture["cases"]}
        for reply in ("provider", "user", "deny", "timeout"):
            for prepend in (False, True):
                with self.subTest(reply=reply, prepend=prepend):
                    case = cases[f"snapshot_{reply}_{prepend}"]
                    marker = (
                        "PROVIDER-INPUT-ORIGINAL"
                        if reply == "provider"
                        else "CALLBACK-ORIGINAL"
                    )
                    messages = case["last_primary_request"]["messages"]
                    self.assertEqual(
                        sum(marker in str(m.get("content")) for m in messages), 1
                    )
                    group = next(
                        i for i, m in enumerate(messages) if m.get("tool_calls")
                    )
                    self.assertEqual(messages[group + 1]["tool_call_id"], "callback")
                    self.assertIn(marker, messages[group + 1]["content"])
                    self.assertEqual(messages[0]["content"] == "HOST", prepend)
                    self.assertEqual(case["input_ids"].count("callback-result"), 1)
                    self.assertIsNone(case["protected_start"])

    def test_primary_requests_keep_originals_once(self):
        fixture = json.loads(
            (
                Path(__file__).parents[1] / "fixtures" / "unseen_input_protection.json"
            ).read_text()
        )
        cases = {case["case"]: case for case in fixture["cases"]}
        for name, count in (
            ("steer", 1),
            ("twelve_steers", 12),
            ("child", 1),
            ("twelve_children", 12),
            ("user", 1),
        ):
            with self.subTest(case=name):
                case = cases[name]
                self.assertTrue(
                    case["creation"]["payload"]["attributes"]["seed"][
                        "unseen_input_protection"
                    ]
                )
                self.assertEqual(len(case["compactions"]), 1)
                messages = case["last_primary_request"]["messages"]
                inputs = [
                    m
                    for m in messages
                    if m["role"] == "user"
                    and (
                        "ORIGINAL" in m["content"]
                        or m["content"].startswith("Child completed: ")
                    )
                ]
                self.assertEqual(len(inputs), count)
                self.assertIsNone(case["protected_start"])
        self.assertIsNone(cases["capacity"]["last_primary_request"])
        self.assertEqual(cases["capacity"]["compactions"], [])
        self.assertEqual(
            cases["capacity"]["terminal_reasons"], ["unseen_input_capacity_exceeded"]
        )
        reply = cases["tool_user_reply"]["last_primary_request"]["messages"]
        self.assertEqual(sum(m.get("tool_call_id") == "question" for m in reply), 1)
        self.assertEqual(
            sum(
                any(call["id"] == "question" for call in m.get("tool_calls", []))
                for m in reply
            ),
            1,
        )
        for cut in ("planned", "receipt", "accepted"):
            case = cases["restart_" + cut]
            self.assertEqual(case["input_ids"].count("late"), 1)
            self.assertEqual(len(case["compactions"]), 1)

    def test_real_http_adapter_receipts_and_tool_callback(self):
        fixture = json.loads(
            (
                Path(__file__).parents[1] / "fixtures" / "unseen_input_protection.json"
            ).read_text()
        )
        cases = {case["case"]: case for case in fixture["cases"]}
        for mode in ("normal", "ptl", "retry", "unknown"):
            case = cases["http_" + mode]
            self.assertTrue(case["http_requests"])
            self.assertTrue(
                all(
                    call["path"].endswith("/chat/completions")
                    for call in case["http_requests"]
                )
            )
            self.assertEqual(
                case["creation"]["payload"]["attributes"]["seed"][
                    "unseen_input_protection"
                ],
                True,
            )
        self.assertIsNone(
            cases["http_normal"]["coverage_at_receipts"][-1]["protected_start"]
        )
        retry = cases["http_retry"]["coverage_at_receipts"]
        self.assertEqual(retry[0]["error_code"], "model_request_rejected")
        self.assertEqual(retry[0]["protected_start"], 1)
        self.assertIsNone(retry[-1]["protected_start"])
        unknown = cases["http_unknown"]
        self.assertEqual(unknown["protected_start"], 1)
        self.assertTrue(
            all(
                item["kind"] == "op_unknown" for item in unknown["coverage_at_receipts"]
            )
        )
        ptl = cases["http_ptl"]
        self.assertEqual(
            ptl["coverage_at_receipts"][1]["error_code"], "prompt_too_long"
        )
        self.assertIsNotNone(ptl["coverage_at_receipts"][2]["protected_start"])
        self.assertNotIn(
            "HTTP-ORIGINAL", json.dumps(ptl["http_requests"][2]["request"])
        )
        self.assertEqual(
            sum(
                m.get("content") == "HTTP-ORIGINAL"
                for m in ptl["http_requests"][3]["request"]["messages"]
            ),
            1,
        )
        self.assertIsNone(ptl["protected_start"])
        callback = cases["provider_callback"]
        messages = callback["last_primary_request"]["messages"]
        index = next(i for i, m in enumerate(messages) if m.get("tool_calls"))
        self.assertEqual(messages[index]["tool_calls"][0]["id"], "e")
        self.assertEqual(messages[index + 1]["tool_call_id"], "e")
        self.assertEqual(messages[index + 1]["content"], "PROVIDER-INPUT-ORIGINAL")
        self.assertNotIn(
            "PROVIDER-INPUT-ORIGINAL",
            json.dumps(callback["compactions"][0]["replacement"][1]),
        )
        correction = cases["provider_correction"]
        self.assertIsNone(correction["protected_start"])
        self.assertEqual(
            sum(
                str(m.get("content")).startswith("Correction for ")
                and "PROVIDER-INPUT-ORIGINAL" in m["content"]
                for m in correction["last_primary_request"]["messages"]
            ),
            1,
        )
        audit = cases["provider_audit"]
        self.assertIsNone(audit["protected_start"])
        self.assertNotIn("PROVIDER-INPUT-ORIGINAL", json.dumps(audit["final_context"]))
        for reply in ("user", "deny", "timeout"):
            case = cases["cancelled_" + reply]
            self.assertIsNone(case["protected_start"])
            self.assertNotIn("CANCELLED-ORIGINAL", json.dumps(case["final_context"]))
            self.assertEqual(case["terminal_reasons"], ["cancel_requested"])

        for decision in ("deny", "timeout"):
            case = cases["approval_" + decision]
            messages = case["last_primary_request"]["messages"]
            self.assertEqual(
                sum("APPROVAL-ORIGINAL" in str(m.get("content")) for m in messages), 1
            )
            self.assertEqual(len(case["compactions"]), 1)
