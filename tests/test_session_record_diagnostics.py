"""Structural checks on actual Python Record/Inbox/runtime diagnostic evidence."""

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from contractctl import load_json  # noqa: E402
from session_validation import record_id  # noqa: E402


class SessionRecordDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_json(ROOT / "fixtures/session_record_diagnostics.json")

    def test_closed_schema_and_propagated_diagnostics(self):
        self.assertEqual(self.fixture["version"], 1)
        self.assertEqual(self.fixture["producer_contract_version"], "39.0.0")
        self.assertTrue(self.fixture["historical_capture"])
        cases = self.fixture["schema_diagnostics"]
        self.assertEqual(len(cases), 4)
        self.assertEqual(
            {case["case"] for case in cases},
            {"record_version", "record_payload", "inbox_envelope", "reserved_metadata"},
        )
        for case in cases:
            # RecordError is the Python error category, not a third-party cause.
            self.assertEqual(
                case["error"],
                {"type": "RecordError", "message": "invalid session schema"},
            )
        self.assertEqual(
            self.fixture["app_server_error"],
            {"code": -32603, "message": "invalid session schema"},
        )
        self.assertEqual(self.fixture["provider_reason"], "provider_result_invalid")
        self.assertEqual(
            self.fixture["model_selection_reason"], "model_selection_unresolvable"
        )
        for excluded in (
            "CUSTOMER_CONTENT", "additionalProperties", "Failed validating", '"properties"'
        ):
            self.assertNotIn(excluded, json.dumps(self.fixture))

    def test_explicit_diagnostics_are_preserved(self):
        expected = {
            "record_identity": "record_id does not match semantic position",
            "embedded_digest": "input digest mismatch",
            "duplicate_field": "duplicate field: a",
            "nonobject": "expected object",
            # Current required Python producer evidence, not universal parser text.
            "malformed_json": "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
            "model_settings": "named tool_choice requires a non-empty function name",
        }
        cases = self.fixture["preserved_diagnostics"]
        self.assertEqual(len(cases), len(expected))
        self.assertEqual(
            {case["case"]: case["error"] for case in cases},
            {name: {"type": "RecordError", "message": text} for name, text in expected.items()},
        )

    def test_historical_canonical_capture_bytes_and_identity(self):
        for kind, old_version in (("record", 1), ("inbox", 3)):
            with self.subTest(kind=kind):
                body = self.fixture["canonical"][f"{kind}_utf8"].encode()
                value = json.loads(body)
                self.assertEqual(value["schema_version"], old_version)
                canonical = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
                self.assertEqual(body, canonical)
                self.assertEqual(
                    hashlib.sha256(body).hexdigest(),
                    self.fixture["canonical"][f"{kind}_sha256"],
                )
                if kind == "record":
                    self.assertEqual(value["record_id"], record_id(value))
