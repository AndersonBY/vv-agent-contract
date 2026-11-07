"""Independent checks on actual HTTP/adapter/kernel completion producer evidence."""

import json
import unittest
from pathlib import Path


class CompletionEvidenceTests(unittest.TestCase):
    def test_mapping_and_response_policy(self):
        fixture = json.loads(
            (
                Path(__file__).parents[1]
                / "fixtures"
                / "model_completion_evidence.json"
            ).read_text()
        )
        cases = {(case["case"], case["declared"]): case for case in fixture["cases"]}
        self.assertEqual(len(cases), 45)
        for (name, declared), case in cases.items():
            with self.subTest(case=name, declared=declared):
                if name == "eof":
                    self.assertEqual(len(case["unknown_reasons"]), 2)
                    self.assertEqual(case["results"], [])
                    self.assertEqual(case["protected_start"], 1)
                    continue
                self.assertEqual(len(case["results"]), 1)
                self.assertEqual(case["unknown_reasons"], [])
                result = case["results"][0]
                if declared is True and (
                    name.startswith("filter") or name.startswith("anthropic")
                ):
                    self.assertEqual(result["rejection"]["status_code"], 200)
                    self.assertFalse(result["rejection"]["retryable"])
                    self.assertEqual(case["terminal_reason"], "model_request_rejected")
                    self.assertEqual(case["protected_start"], 1)
                    self.assertNotIn("temporary filtered body", json.dumps(case))
                    self.assertNotIn("raw", result)
                else:
                    self.assertNotIn("error_code", result)
                    evidence = result["raw"]["completion_metadata"]
                    self.assertEqual(
                        set(evidence),
                        {
                            "finish_reason",
                            "finish_reason_normalized",
                            "refusal",
                            "stream_terminated",
                            "stream_exhausted",
                            "termination_signals",
                            "attributes",
                        },
                    )
                    if name.startswith("refusal"):
                        self.assertEqual(result["content"], evidence["refusal"])
                        self.assertTrue(result["content"])
                    if name == "degraded":
                        self.assertIsNone(evidence["stream_terminated"])
                        self.assertEqual(
                            evidence["attributes"],
                            {"openai_done_observer": "unsupported_decoder"},
                        )
                    elif name.endswith("nonstream"):
                        self.assertIsNone(evidence["stream_exhausted"])
                    else:
                        self.assertTrue(evidence["stream_exhausted"])
                        self.assertTrue(evidence["stream_terminated"])
