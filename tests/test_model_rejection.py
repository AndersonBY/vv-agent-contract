"""Independent checks of real model rejection producer facts."""

import base64
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ModelRejectionTests(unittest.TestCase):
    def test_definitive_and_ambiguous_attempts_are_distinct(self):
        fixture = json.loads((ROOT / "fixtures/model_rejection.json").read_text())
        self.assertEqual(fixture["record_schema_version"], 1)
        self.assertEqual(fixture["inbox_schema_version"], 3)
        cases = {}
        for vector in fixture["vectors"]:
            wire = vector["wire"]
            cases[wire["id"]] = wire
            raw = base64.b64decode(vector["bytes_base64"], validate=True)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), vector["sha256"])
            self.assertEqual(json.loads(raw), wire)
        for name in (
            "bad_request",
            "rate_limit_exhausted",
            "rate_limit_success",
            "temporary_rejection",
            "summary_rejected",
        ):
            case = cases[name]
            self.assertEqual(case["unknowns"], [])
            self.assertEqual(case["terminal"]["unconfirmed_operations"], [])
            self.assertEqual(
                case["receipts"][0]["result"]["error_code"], "model_request_rejected"
            )
            self.assertTrue(case["receipts"][0]["execution_started"])
        self.assertEqual(cases["bad_request"]["rejected_calls"], 1)
        self.assertEqual(
            cases["bad_request"]["terminal"]["reason"], "model_request_rejected"
        )
        for name in (
            "rate_limit_success",
            "rate_limit_exhausted",
            "temporary_rejection",
        ):
            self.assertEqual([p["attempt"] for p in cases[name]["plans"]], [1, 2])
        self.assertEqual(cases["rate_limit_success"]["terminal"]["status"], "completed")
        self.assertEqual(
            cases["rate_limit_exhausted"]["terminal"]["reason"],
            "model_request_rejected",
        )
        self.assertEqual(cases["summary_rejected"]["terminal"]["status"], "completed")
        self.assertEqual(cases["summary_rejected"]["context_compacted"], 0)
        for name in (
            "provider_internal",
            "request_timeout",
            "timeout",
            "connection_lost",
            "ordinary_exception",
        ):
            case = cases[name]
            self.assertEqual(case["rejected_calls"], 2)
            self.assertEqual(len(case["unknowns"]), 2)
            self.assertTrue(all(u["duplicate_cost_risk"] for u in case["unknowns"]))
            self.assertEqual(case["terminal"]["reason"], "model_outcome_unknown")
        for name in (
            "context_openai",
            "context_openai_wrapped",
            "context_typed",
            "context_anthropic",
            "context_moonshot",
            "context_payload",
            "context_content_string",
        ):
            case = cases[name]
            self.assertEqual(case["rejected_calls"], 1)
            self.assertEqual(
                case["receipts"][0]["result"]["error_code"], "prompt_too_long"
            )
            self.assertFalse(
                any(
                    r["result"].get("error_code") == "model_request_rejected"
                    for r in case["receipts"]
                )
            )
            self.assertEqual(
                [p["purpose"] for p in case["plans"]],
                ["primary", "compaction", "primary"],
            )
            self.assertEqual(case["context_compacted"], 1)
            self.assertEqual(case["unknowns"], [])
            self.assertEqual(case["terminal"]["status"], "completed")
            self.assertEqual(case["terminal"]["unconfirmed_operations"], [])
            self.assertFalse(
                any(e["type"] == "model_retry_duplicate_risk" for e in case["events"])
            )
        self.assertEqual(
            cases["tool_string_rejected"]["terminal"]["reason"],
            "model_request_rejected",
        )
        for status in (400, 401, 403, 404, 429):
            for mode in ("single", "success", "exhausted"):
                case = cases[f"endpoint_{status}_{mode}"]
                order = case["endpoint_order"]
                retryable = status == 429 or (
                    status in (401, 403, 404) and len(order) > 1
                )
                success = mode == "success" and retryable
                expected_calls = (
                    ["a", "b"]
                    if success
                    else (
                        [order[i % len(order)] for i in range(max(2, len(order)))]
                        if retryable
                        else ["a"]
                    )
                )
                self.assertEqual(case["endpoint_calls"], expected_calls)
                self.assertEqual(case["unknowns"], [])
                self.assertEqual(case["terminal"]["unconfirmed_operations"], [])
                self.assertFalse(
                    any(
                        e["type"] == "model_retry_duplicate_risk"
                        for e in case["events"]
                    )
                )
                self.assertEqual(
                    case["receipts"][0]["result"]["rejection"]["retryable"], retryable
                )
                self.assertEqual(
                    case["terminal"]["status"], "completed" if success else "failed"
                )
                if status in (401, 403, 404):
                    self.assertTrue(
                        all(p["not_before_ms"] == 0 for p in case["plans"][1:])
                    )
                if not success:
                    self.assertEqual(
                        case["terminal"]["reason"], "model_request_rejected"
                    )
                    self.assertIn(
                        f"HTTP {status}: Model provider request failed.",
                        case["terminal"]["result"],
                    )
                    self.assertNotIn("sk-secret", json.dumps(case))
        for status, override, expected in (
            (401, False, ["a"]),
            (401, True, ["a", "a"]),
            (429, False, ["a"]),
        ):
            case = cases[f"endpoint_override_{status}_{override}"]
            self.assertEqual(case["endpoint_calls"], expected)
            self.assertEqual(
                case["receipts"][0]["result"]["rejection"]["retryable"], override
            )
            self.assertEqual(
                case["terminal"]["status"], "completed" if override else "failed"
            )
            self.assertEqual(case["unknowns"], [])
            self.assertEqual(case["terminal"]["unconfirmed_operations"], [])

    def test_physical_transport_and_safety_producer_evidence(self):
        fixture = json.loads((ROOT / "fixtures/model_rejection.json").read_text())
        cases = {vector["wire"]["id"]: vector["wire"] for vector in fixture["vectors"]}
        self.assertGreaterEqual(len(cases), 54)
        for provider in ("openai", "anthropic"):
            for name in (
                "timeout_then_400",
                "500_then_400",
                "always_429",
                "single_400",
            ):
                case = cases[f"transport_{provider}_{name}"]
                unknown = name in ("timeout_then_400", "500_then_400")
                self.assertEqual(
                    case["physical_http_requests"],
                    4 if unknown else 6 if name == "always_429" else 1,
                )
                self.assertEqual(
                    len(case["plans"]), 2 if unknown or name == "always_429" else 1
                )
                self.assertEqual(len(case["unknowns"]), 2 if unknown else 0)
                self.assertEqual(
                    case["terminal"]["reason"],
                    "model_outcome_unknown" if unknown else "model_request_rejected",
                )
                self.assertEqual(
                    bool(case["terminal"]["unconfirmed_operations"]), unknown
                )
                self.assertTrue(
                    all(item["duplicate_cost_risk"] for item in case["unknowns"])
                )
        for name, case in cases.items():
            if name.startswith("mixed_") or name.startswith("unobservable_http"):
                self.assertEqual(len(case["unknowns"]), 2)
                self.assertTrue(case["terminal"]["unconfirmed_operations"])
                self.assertTrue(
                    all(item["duplicate_cost_risk"] for item in case["unknowns"])
                )
                self.assertEqual(case["terminal"]["reason"], "model_outcome_unknown")
        for name in ("private_diagnostic", "repair_private_diagnostic"):
            case = cases[name]
            self.assertNotIn("SYNTHETIC", json.dumps(case))
            self.assertNotIn("provided: SY", json.dumps(case))
            self.assertEqual(
                case["terminal"]["reason"],
                "output_validation_failed"
                if name.startswith("repair_")
                else "model_request_rejected",
            )

    def test_native_connection_failures_cannot_be_settled(self):
        fixture = json.loads((ROOT / "fixtures/model_rejection.json").read_text())
        cases = {vector["wire"]["id"]: vector["wire"] for vector in fixture["vectors"]}
        for provider in ("openai", "anthropic"):
            for name in ("APIConnectionError", "APITimeoutError"):
                for mode in ("explicit", "automatic", "context"):
                    case = cases[f"native_{provider}_{name}_{mode}"]
                    self.assertEqual(case["receipts"], [])
                    self.assertEqual(case["context_compacted"], 0)
                    self.assertEqual(len(case["unknowns"]), 2)
                    self.assertTrue(
                        all(item["duplicate_cost_risk"] for item in case["unknowns"])
                    )
                    self.assertTrue(case["terminal"]["unconfirmed_operations"])
                    self.assertEqual(
                        case["terminal"]["reason"], "model_outcome_unknown"
                    )

    def test_response_body_completion_is_required(self):
        fixture = json.loads((ROOT / "fixtures/model_rejection.json").read_text())
        cases = {vector["wire"]["id"]: vector["wire"] for vector in fixture["vectors"]}
        for provider in ("openai", "anthropic"):
            for name in ("pre_raw", "flush", "mid_body", "closed_unread"):
                case = cases[f"body_{provider}_{name}_413"]
                self.assertEqual(case["receipts"], [])
                self.assertEqual(case["context_compacted"], 0)
                self.assertEqual(case["physical_http_requests"], 2)
                self.assertEqual(len(case["unknowns"]), 2)
                self.assertTrue(
                    all(item["duplicate_cost_risk"] for item in case["unknowns"])
                )
                self.assertTrue(case["terminal"]["unconfirmed_operations"])
                self.assertEqual(case["terminal"]["reason"], "model_outcome_unknown")
            for status in (400, 429):
                case = cases[f"body_{provider}_gzip_complete_{status}"]
                self.assertEqual(
                    case["physical_http_requests"], 6 if status == 429 else 1
                )
                self.assertEqual(case["unknowns"], [])
                self.assertEqual(case["terminal"]["unconfirmed_operations"], [])
                self.assertEqual(case["terminal"]["reason"], "model_request_rejected")
            success = cases[f"body_{provider}_success_{provider}_200"]
            self.assertEqual(success["physical_http_requests"], 1)
            self.assertEqual(success["unknowns"], [])
            self.assertEqual(success["terminal"]["unconfirmed_operations"], [])
            self.assertEqual(success["terminal"]["status"], "completed")

    def test_vendor_retry_controls_and_incomplete_bounds(self):
        fixture = json.loads((ROOT / "fixtures/model_rejection.json").read_text())
        cases = {v["wire"]["id"]: v["wire"] for v in fixture["vectors"]}
        for provider in ("openai", "anthropic"):
            for label, physical, status, sleeps in (
                ("conflict", 3, 409, 2),
                ("retry_after", 6, 429, 4),
                ("retry_true_400", 3, 400, 2),
            ):
                case = cases[f"retry_{provider}_{label}"]
                self.assertEqual(case["physical_http_requests"], physical)
                self.assertEqual(case["unknowns"], [])
                self.assertEqual(case["terminal"]["reason"], "model_request_rejected")
                self.assertEqual(case["terminal"]["unconfirmed_operations"], [])
                self.assertEqual(len(case["vendor_retry_sleeps"]), sleeps)
                self.assertTrue(
                    all(s["status_code"] == status for s in case["vendor_retry_sleeps"])
                )
                if label == "retry_after":
                    self.assertTrue(
                        all(
                            s["delay_seconds"] == 7 for s in case["vendor_retry_sleeps"]
                        )
                    )
            for label, physical, sleep_count in (
                ("retry_after_timeout", 6, 4),
                ("retry_false_timeout", 2, 0),
                ("oversized", 2, 0),
            ):
                case = cases[f"retry_{provider}_{label}"]
                self.assertEqual(case["physical_http_requests"], physical)
                self.assertEqual(len(case["unknowns"]), 2)
                self.assertTrue(all(u["duplicate_cost_risk"] for u in case["unknowns"]))
                self.assertEqual(case["receipts"], [])
                self.assertEqual(case["terminal"]["reason"], "model_outcome_unknown")
                self.assertTrue(case["terminal"]["unconfirmed_operations"])
                self.assertEqual(len(case["vendor_retry_sleeps"]), sleep_count)
                self.assertTrue(
                    all(
                        s["status_code"] == 429 and s["delay_seconds"] == 7
                        for s in case["vendor_retry_sleeps"]
                    )
                )
