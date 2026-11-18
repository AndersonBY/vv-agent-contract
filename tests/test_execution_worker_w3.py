from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contractctl  # noqa: E402
import session_validation as session  # noqa: E402


class ExecutionWorkerW3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = contractctl.load_json(
            ROOT / "fixtures/execution_worker_w3.json"
        )
        cls.schema = contractctl.load_json(
            ROOT / "fixtures/execution_worker_w3.schema.json"
        )

    def test_allocation_is_synthetic_and_has_closed_outcome_mapping(self) -> None:
        session.validate_schema(self.fixture, self.schema, self.schema)
        self.assertEqual(self.fixture["contract_version"], "41.0.0")
        self.assertEqual(self.fixture["feature_level"], 3)
        self.assertEqual(self.fixture["status"], "contract-allocation-only")
        self.assertFalse(self.fixture["provenance"]["producer_capture"])
        self.assertFalse(self.fixture["provenance"]["adoption_evidence"])
        self.assertEqual(
            self.fixture["provider_outcomes"],
            {
                "not_started": None,
                "running": "Accepted",
                "exited": "Definitive",
                "unknown": "Unknown",
            },
        )

    def test_execution_identity_is_stable_across_attempt_context(self) -> None:
        vector = self.fixture["identity_vectors"][0]
        identity = vector["identity"]
        fact = {
            "domain": self.fixture["framing"]["execution_id"]["domain"],
            "framing_version": self.fixture["framing"]["execution_id"]["framing_version"],
            "operation_key": identity["operation_key"],
            "tenant_id": identity["tenant_id"],
            "environment_id": identity["environment_id"],
        }
        canonical = session.jcs_bytes(ROOT, fact)
        self.assertEqual(
            fact,
            {
                "domain": "vv-agent/S1/execution-identity",
                "framing_version": 1,
                "operation_key": "sess-1/op-bg-1",
                "tenant_id": "tenant-a",
                "environment_id": "env-remote-1",
            },
        )
        self.assertEqual(canonical, base64.b64decode(vector["preimage_base64"]))
        self.assertTrue(canonical.startswith(b"{"))
        self.assertEqual(vector["canonical_json_utf8_bytes"], 151)
        self.assertEqual(len(canonical), 151)
        expected = "1a80b8b1f02b7de88c875ad1c6d49ffe13e11a919fbcb7d04faa93ba9b4b511f"
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected)
        self.assertEqual(identity["execution_id"], expected)
        for variant in vector["excluded_context_variants"]:
            self.assertEqual(
                session.execution_identity_digest(ROOT, {**identity, **variant}),
                expected,
            )

    def test_command_digest_uses_session_hmac_and_frozen_policy(self) -> None:
        vector = self.fixture["command_digest_vectors"][0]
        fact = {
            "domain": self.fixture["framing"]["command_digest"]["domain"],
            "framing_version": self.fixture["framing"]["command_digest"]["framing_version"],
            "purpose": self.fixture["framing"]["command_digest"]["purpose"],
            "tenant_id": vector["tenant_id"],
            "session_id": vector["session_id"],
            "command_spec": vector["command_spec"],
            "environment": vector["environment"],
            "operational_policy": vector["operational_policy"],
        }
        canonical = session.jcs_bytes(ROOT, fact)
        self.assertEqual(
            set(fact),
            {
                "domain",
                "framing_version",
                "purpose",
                "tenant_id",
                "session_id",
                "command_spec",
                "environment",
                "operational_policy",
            },
        )
        self.assertEqual(canonical, base64.b64decode(vector["preimage_base64"]))
        self.assertTrue(canonical.startswith(b"{"))
        self.assertEqual(vector["canonical_json_utf8_bytes"], 1100)
        self.assertEqual(len(canonical), 1100)
        digest = hmac.new(
            base64.b64decode(vector["session_data_key_base64"], validate=True),
            canonical,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(vector["command_digest"], digest)
        self.assertEqual(
            digest,
            "deeca65af1fe1caceba1cf85d1a4bb731112db4394d43b4d22db08afa08f967c",
        )
        self.assertEqual(
            vector["environment"]["capabilities_digest"],
            session.environment_capabilities_digest(ROOT, vector["environment"]),
        )

    def test_lookup_statuses_reuse_provider_outcomes(self) -> None:
        expected = {
            "not_started": (None, "no_effects_and_retry_once", True),
            "running": ("Accepted", "reuse_running_execution", False),
            "exited": ("Definitive", "reconcile_terminal_execution", False),
            "unknown": ("Unknown", "preserve_unknown", False),
        }
        for vector in self.fixture["lookup_results"]:
            result = vector["result"]
            with self.subTest(status=result["status"]):
                outcome_kind, disposition, retry = expected[result["status"]]
                self.assertEqual(
                    result["outcome"]["kind"] if result["outcome"] else None,
                    outcome_kind,
                )
                self.assertEqual(vector["expected_disposition"], disposition)
                self.assertEqual(vector["retry_allowed"], retry)
                session.validate_provider_lookup_result(ROOT, result)
        unknown = next(
            vector
            for vector in self.fixture["lookup_results"]
            if vector["result"]["status"] == "unknown"
        )
        self.assertFalse(unknown["transport_available"])
        self.assertEqual(
            unknown["result"]["outcome"]["kind"],
            "Unknown",
        )
        running = next(
            vector
            for vector in self.fixture["lookup_results"]
            if vector["result"]["status"] == "running"
        )
        self.assertIs(
            type(running["result"]["outcome"]["yield_on_steer"]), bool
        )
        self.assertEqual(
            set(running["result"]["outcome"]),
            {"kind", "handle", "yield_on_steer"},
        )

    def test_nullable_capabilities_digest_matches_python_value_layer(self) -> None:
        environment = copy.deepcopy(self.fixture["environment"])
        environment["capabilities_digest"] = None
        session.validate_schema(
            environment,
            self.schema["$defs"]["EnvironmentCapabilityBinding"],
            self.schema,
        )
        self.assertIsNone(environment["capabilities_digest"])

    def test_tamper_and_recovery_cases_have_deterministic_dispositions(self) -> None:
        session.validate_execution_worker_w3(ROOT)
        cases = {case["name"]: case for case in self.fixture["invalid_lookup_cases"]}
        self.assertEqual(
            set(cases),
            {
                "binding_tenant_tamper",
                "bindings_returned_environment_identity_tamper",
                "environment_id_tamper",
                "generation_tamper",
                "command_digest_tamper",
                "isolation_downgrade",
                "network_scope_widening",
                "network_enforcement_downgrade",
                "capability_digest_mismatch",
                "policy_reference_digest_mismatch",
                "operational_policy_digest_mismatch",
                "authorization_mismatch",
                "malformed_provider_result",
            },
        )
        self.assertEqual(cases["command_digest_tamper"]["expected_code"], "command_mismatch")
        self.assertEqual(
            cases["malformed_provider_result"]["expected_code"],
            "provider_result_invalid",
        )
        recovery = {case["name"]: case for case in self.fixture["recovery_cases"]}
        retry = recovery["authenticated_not_started_allows_one_new_attempt"]
        self.assertEqual(retry["expected_next_attempt"], 2)
        self.assertTrue(retry["reuse_idempotency_key"])
        self.assertTrue(retry["reuse_execution_id"])
        exhausted = recovery["after_second_submission_not_started_is_query_only"]
        self.assertIsNone(exhausted["expected_next_attempt"])
        self.assertEqual(exhausted["expected_disposition"], "query_or_evidence")

    def test_transport_unknown_never_becomes_not_started(self) -> None:
        vector = next(
            item
            for item in self.fixture["lookup_results"]
            if item["result"]["status"] == "unknown"
        )
        self.assertFalse(vector["transport_available"])
        self.assertFalse(vector["authenticated"])
        self.assertFalse(vector["retry_allowed"])
        self.assertEqual(
            session.lookup_rejection_code(
                ROOT,
                self.fixture["lookup_binding"],
                self.fixture["environment"],
                self.fixture["operational_policy"],
                vector["result"],
                self.fixture["environment"],
                self.fixture["operational_policy"],
                authenticated=False,
                transport_available=False,
            ),
            "unknown_transport",
        )


if __name__ == "__main__":
    unittest.main()
