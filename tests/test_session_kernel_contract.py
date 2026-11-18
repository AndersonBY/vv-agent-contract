from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contractctl  # noqa: E402 -- load the repository's script after adding its directory
import session_validation as session  # noqa: E402


class SessionKernelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vectors = contractctl.load_json(
            ROOT / "fixtures/session_codec_vectors.json"
        )
        cls.content_catalog = contractctl.load_json(
            ROOT / "fixtures/session_content_catalog.json"
        )
        cls.codec = session.Codec(ROOT, cls.vectors)

    def hydrate(self, value):
        return session.hydrate_content_refs(value, self.content_catalog)

    def record(self, kind: str) -> dict:
        return copy.deepcopy(
            next(
                v["wire"]
                for v in self.vectors["vectors"]
                if v["type"] == "record" and v["wire"]["kind"] == kind
            )
        )

    def test_all_new_schema_codec_and_layer_vectors_validate(self) -> None:
        report = session.validate_session_fixtures(ROOT)
        self.assertGreater(report["records"], 100)
        self.assertGreater(report["inbox_items"], 50)
        self.assertEqual(report["codec_vectors"], 85)
        self.assertEqual(report["invalid_vectors"], 88)
        self.assertEqual(report["storage_envelope_cases"], 6)
        self.assertEqual(report["storage_lifecycle_cases"], 11)
        self.assertEqual(report["trusted_negative_cases"], 26)
        self.assertEqual(report["w3_identity_vectors"], 1)
        self.assertEqual(report["w3_command_digest_vectors"], 1)
        self.assertEqual(report["w3_lookup_results"], 4)
        self.assertEqual(report["w3_invalid_cases"], 13)
        self.assertEqual(report["w3_recovery_cases"], 5)

    def test_level_three_execution_shapes_are_closed_and_level_two_rejects(self) -> None:
        turn = self.record("turn_started")
        turn["feature_level"] = 3
        environment = {
            "descriptor": turn["payload"]["definition"],
            "environment_id": "env-remote-1",
            "generation": 7,
            "isolation": "container",
            "network": "none",
            "enforces_network_policy": True,
            "enforces_resource_limits": True,
            "persistent": True,
            "environment_capabilities": [
                "command.execute",
                "filesystem.workspace",
                "network.deny",
            ],
            "capabilities_digest": "0" * 64,
            "network_policy_ref_digest": "1" * 64,
            "isolation_policy_ref_digest": "2" * 64,
            "operational_policy": turn["payload"]["budget"],
        }
        environment["capabilities_digest"] = session.environment_capabilities_digest(
            ROOT, environment
        )
        turn["payload"]["environment"] = environment
        self.codec.validate(turn)

        nullable_environment = copy.deepcopy(turn)
        nullable_environment["payload"]["environment"]["capabilities_digest"] = None
        self.codec.validate(nullable_environment)

        level_two_turn = copy.deepcopy(turn)
        level_two_turn["feature_level"] = 2
        with self.assertRaises(session.ValidationError):
            self.codec.validate(level_two_turn)

        plan = copy.deepcopy(
            next(
                vector["wire"]
                for vector in self.vectors["vectors"]
                if vector["type"] == "record"
                and vector["wire"]["kind"] == "op_planned"
                and vector["wire"]["payload"]["op_kind"] == "tool"
            )
        )
        plan["feature_level"] = 3
        identity = {
            "operation_key": f"{plan['session_id']}/{plan['operation_id']}",
            "tenant_id": "tenant-a",
            "environment_id": environment["environment_id"],
            "session_id": plan["session_id"],
            "operation_id": plan["operation_id"],
            "execution_id": "0" * 64,
        }
        identity["execution_id"] = session.execution_identity_digest(ROOT, identity)
        plan["payload"]["execution_identity"] = identity
        plan["payload"]["command_digest"] = "3" * 64
        self.codec.validate(plan)

        level_two_plan = copy.deepcopy(plan)
        level_two_plan["feature_level"] = 2
        with self.assertRaises(session.ValidationError):
            self.codec.validate(level_two_plan)

        evidence = copy.deepcopy(
            next(
                vector["wire"]
                for vector in self.vectors["vectors"]
                if vector["type"] == "inbox"
                and vector["wire"]["kind"] == "provider_evidence"
            )
        )
        evidence["feature_level"] = 3
        session_id = evidence["target_turn_id"] or "sess-1"
        lookup_identity = {
            "operation_key": f"{session_id}/{evidence['payload']['operation_id']}",
            "tenant_id": evidence["actor"]["tenant_id"],
            "environment_id": environment["environment_id"],
            "session_id": session_id,
            "operation_id": evidence["payload"]["operation_id"],
            "execution_id": "0" * 64,
        }
        lookup_identity["execution_id"] = session.execution_identity_digest(
            ROOT, lookup_identity
        )
        evidence["payload"] = {
            "operation_id": evidence["payload"]["operation_id"],
            "attempt": evidence["payload"]["attempt"],
            "request_digest": evidence["payload"]["request_digest"],
            "lookup": {
                "schema_version": "vv-agent.provider-lookup.v1",
                "status": "unknown",
                "binding": {
                    "tenant_id": lookup_identity["tenant_id"],
                    "environment_id": lookup_identity["environment_id"],
                    "session_id": lookup_identity["session_id"],
                    "operation_id": lookup_identity["operation_id"],
                    "execution_id": lookup_identity["execution_id"],
                    "attempt": evidence["payload"]["attempt"],
                    "request_digest": evidence["payload"]["request_digest"],
                    "idempotency_key": f"{lookup_identity['session_id']}/{lookup_identity['operation_id']}",
                    "command_digest": "3" * 64,
                    "provider_id": "provider-remote-1",
                    "generation": 7,
                },
                "outcome": {
                    "kind": "Unknown",
                    "reason": "registry unavailable",
                },
                "evidence": ["transport-or-registry:unavailable"],
            },
        }
        self.codec.validate(evidence, inbox=True)

        wrong_status = copy.deepcopy(evidence)
        wrong_status["payload"]["lookup"]["status"] = "running"
        with self.assertRaises(session.ValidationError):
            self.codec.validate(wrong_status, inbox=True)

    def test_feature_level_two_control_fields_are_strict(self) -> None:
        requirements = {
            "level": 2,
            "handler_version": "handler-h1",
            "capabilities": ["handler-family:demo", "tool:" + "1" * 64],
        }

        created = self.record("session_created")
        self.codec.validate(created)
        self.assertNotIn("bootstrap", created["payload"])
        l1_with_bootstrap = copy.deepcopy(created)
        l1_with_bootstrap["payload"]["bootstrap"] = requirements
        with self.assertRaises(session.ValidationError):
            self.codec.validate(l1_with_bootstrap)

        created_l2 = copy.deepcopy(created)
        created_l2["feature_level"] = 2
        created_l2["payload"]["bootstrap"] = requirements
        self.codec.validate(created_l2)
        missing_bootstrap = copy.deepcopy(created_l2)
        del missing_bootstrap["payload"]["bootstrap"]
        with self.assertRaises(session.ValidationError):
            self.codec.validate(missing_bootstrap)

        inbox = copy.deepcopy(
            next(
                vector["wire"]
                for vector in self.vectors["vectors"]
                if vector["type"] == "inbox" and vector["wire"]["kind"] == "user"
            )
        )
        self.codec.validate(inbox, inbox=True)
        l1_with_requirements = copy.deepcopy(inbox)
        l1_with_requirements["requirements"] = requirements
        with self.assertRaises(session.ValidationError):
            self.codec.validate(l1_with_requirements, inbox=True)

        for kind in ("user", "follow_up", "model_selection"):
            vector = copy.deepcopy(
                next(
                    item["wire"]
                    for item in self.vectors["vectors"]
                    if item["type"] == "inbox" and item["wire"]["kind"] == kind
                )
            )
            vector["feature_level"] = 2
            vector["requirements"] = requirements
            with self.subTest(kind=kind):
                self.codec.validate(vector, inbox=True)
                missing = copy.deepcopy(vector)
                del missing["requirements"]
                with self.assertRaises(session.ValidationError):
                    self.codec.validate(missing, inbox=True)

        steer = copy.deepcopy(
            next(
                item["wire"]
                for item in self.vectors["vectors"]
                if item["type"] == "inbox" and item["wire"]["kind"] == "steer"
            )
        )
        steer["feature_level"] = 2
        steer["requirements"] = requirements
        with self.assertRaises(session.ValidationError):
            self.codec.validate(steer, inbox=True)

        for target, inbox_value in (
            (created_l2, False),
            (l1_with_requirements, True),
        ):
            malformed = copy.deepcopy(target)
            location = malformed if inbox_value else malformed["payload"]
            control = location["requirements"] if inbox_value else location["bootstrap"]
            control["capabilities"] = [control["capabilities"][0]] * 2
            with self.assertRaises(session.ValidationError):
                self.codec.validate(malformed, inbox=inbox_value)
            control = copy.deepcopy(requirements)
            control["unknown"] = True
            unknown = copy.deepcopy(target)
            if inbox_value:
                unknown["requirements"] = control
            else:
                unknown["payload"]["bootstrap"] = control
            with self.assertRaises(session.ValidationError):
                self.codec.validate(unknown, inbox=inbox_value)

    def test_after_cycle_ledger_stop_codes_are_closed(self) -> None:
        record = self.record("boundary_recorded")
        content_ref = record["payload"]["data"]["shared_state"]
        record["payload"]["stage"] = "after_cycle"
        record["payload"]["data"] = {
            "action": "stop_non_success",
            "steering_messages": [],
            "disallow_tools": [],
            "stop": {
                "code": "host.policy_stop",
                "message": content_ref,
            },
            "shared_state": content_ref,
            "error": content_ref,
        }
        for code in ("host.policy_stop", "host_stop", "hook_stop", "stopped"):
            candidate = copy.deepcopy(record)
            candidate["payload"]["data"]["stop"]["code"] = code
            with self.subTest(code=code):
                self.codec.validate(candidate)

        classes = {
            vector["rejection_class"]
            for vector in contractctl.load_json(ROOT / "fixtures/session_invalid.json")[
                "vectors"
            ]
        }
        self.assertTrue(
            {
                "after_cycle_stop_code_unknown",
                "after_cycle_stop_code_whitespace",
                "after_cycle_stop_code_newline",
                "after_cycle_stop_code_overlong",
            }.issubset(classes)
        )


    def test_trusted_storage_s1_producer_capture(self) -> None:
        fixture = contractctl.load_json(ROOT / "fixtures/trusted_storage_s1.json")
        record_schema = contractctl.load_json(ROOT / "fixtures/session_record.schema.json")
        storage_schema = contractctl.load_json(
            ROOT / "fixtures/session_storage_envelope.schema.json"
        )
        lifecycle_schema = contractctl.load_json(
            ROOT / "fixtures/session_storage_lifecycle.schema.json"
        )
        self.assertEqual(fixture["schema_version"], "vv-agent.trusted-storage-s1.v1")
        self.assertEqual(fixture["status"], "producer-captured")
        self.assertTrue(fixture["provenance"]["producer_capture"])
        self.assertEqual(
            fixture["revision"], fixture["provenance"]["source_revision"]
        )
        self.assertRegex(fixture["revision"], r"^[0-9a-f]{40}$")
        self.assertEqual(fixture["record_schema_version"], "S1")
        self.assertEqual(fixture["inbox_schema_version"], "S1")
        self.assertEqual(fixture["storage_major"], "S1")
        self.assertEqual(fixture["feature_level"], 1)
        self.assertNotIn(
            "chain_digest",
            record_schema["$defs"]["RecordEnvelope"]["properties"],
        )
        self.assertEqual(
            set(storage_schema["$defs"]["Envelope"]["properties"]),
            {
                "schema_version",
                "tenant_id",
                "session_id",
                "seq",
                "record_digest",
                "chain_digest",
                "writer_epoch",
                "created_ms",
            },
        )
        self.assertEqual(
            record_schema["$defs"]["Principal"]["properties"]["subject_kind"]["enum"],
            ["user", "service", "agent"],
        )
        self.assertIn("Tombstone", lifecycle_schema["$defs"])
        self.assertIn("ExportLine", lifecycle_schema["$defs"])
        self.assertEqual(
            set(fixture["field_dispositions"]),
            {
                "session_record.envelope",
                "session_inbox.envelope",
                "session_created.payload.principal",
                "session_created.payload.workspace",
                "session_created.payload.attributes",
                "turn_started.payload.definition",
                "turn_started.payload.budget",
                "turn_started.payload.policy_digest",
                "turn_started.payload.requirements",
                "turn_started.payload.tokenizer_binding",
                "turn_started.payload.environment",
                "turn_started.payload.environment.operational_policy",
                "input_applied.payload.input_proof",
                "op_planned.payload.request_tool_budget_admission",
                "op_prepared.payload.request_tool_hook_shared_state",
                "op.policy_decision",
                "op_completed.payload.result_usage_evidence",
                "op_completed.payload.usage_counts",
                "approval_answer.payload.scope_reason_metadata",
                "approval_answer.policy_projection",
                "provider_handles.payload_fields",
                "boundary_recorded.payload.data",
                "session_storage_envelope",
                "session_storage_lifecycle",
                "ContentRef",
                "ContentLabels",
            },
        )
        accepted = {case["name"]: case for case in fixture["accepted_cases"]}
        codec = session.Codec(ROOT, [self.vectors, fixture])
        self.assertEqual(
            set(accepted),
            {
                "session_created_principal_and_content_ref",
                "turn_started_requirements_policy_and_environment",
                "signed_user_inbox_admission_proof",
                "input_applied_copied_input_proof",
                "policy_usage_and_tokenizer_projection",
                "op_planned_policy_projection",
                "op_prepared_policy_projection",
                "approval_answer_policy_projection",
                "provider_evidence_content_ref",
                "boundary_event_content_ref",
            },
        )
        for case in accepted.values():
            with self.subTest(case=case["name"]):
                self.assertEqual(case["wire"]["schema_version"], "S1")
                self.assertEqual(case["wire"]["feature_level"], 1)
                self.assertEqual(
                    hashlib.sha256(session.decode(case)).hexdigest(), case["sha256"]
                )
                codec.validate(case["wire"], inbox="record_id" not in case["wire"])

        for vector in fixture["rejected_cases"]:
            with self.subTest(case=vector["name"]):
                wire = copy.deepcopy(accepted[vector["base"]]["wire"])
                for operation in vector["patch"]:
                    target = wire
                    for part in operation["path"][:-1]:
                        target = target[part]
                    field = operation["path"][-1]
                    if operation.get("delete"):
                        del target[field]
                    else:
                        target[field] = operation["set"]
                with self.assertRaises(session.ValidationError):
                    codec.validate(wire, inbox="record_id" not in wire)

    def test_endpoint_routing_uses_host_order_and_closes_missing_attempt(self) -> None:
        cases = contractctl.load_json(ROOT / "fixtures/session_semantics.json")["cases"]
        case = next(c for c in cases if c["case"] == "endpoint_routing")
        self.assertEqual(case["calls"], ["B", "C"])
        self.assertEqual(case["preferences"], [None, "B", "B"])
        missing = self.hydrate(case["missing"]["payload"])
        self.assertEqual(missing["result"]["error_code"], "endpoint_unavailable")
        self.assertFalse(missing["execution_started"])
        self.assertEqual(missing["usage"], {})
        self.assertEqual(missing["evidence"], [])

    def test_model_selection_retains_retry_model_route_and_billing(self) -> None:
        cases = contractctl.load_json(ROOT / "fixtures/session_semantics.json")["cases"]
        case = next(
            c for c in cases if c["case"] == "model_selection_mid_session_retry"
        )
        codec = session.Codec(ROOT, [self.vectors, case])
        plans = [self.hydrate(plan) for plan in case["plans"]]
        self.assertEqual(
            [p["payload"]["request"]["model"] for p in plans], ["m", "m", "B"]
        )
        self.assertEqual(plans[0]["payload"]["request"], plans[1]["payload"]["request"])
        self.assertEqual(plans[0]["operation_id"], plans[1]["operation_id"])
        self.assertEqual([p["attempt"] for p in plans], [1, 2, 1])
        request = plans[2]["payload"]["request"]
        self.assertEqual(request["route"], {"backend_type": "anthropic"})
        self.assertEqual(request["model_settings"]["reasoning"], {"effort": "high"})
        self.assertEqual(
            request["metadata"]["vv_session"]["model_binding"]["backend"], "anthropic"
        )
        self.assertEqual([c["model"] for c in case["calls"]], ["m", "m", "B"])
        self.assertEqual(
            [c["backend"] for c in case["calls"]], ["scripted", "scripted", "anthropic"]
        )
        zero_capability = copy.deepcopy(case["selection_record"])
        model_binding = self.hydrate(zero_capability["payload"]["model_binding"])
        self.assertIn("max_output_tokens", model_binding)
        model_binding["max_output_tokens"] = 0
        codec.validate(zero_capability)
        item = case["selection_record"]["payload"]["input"]
        self.assertEqual(item["schema_version"], "S1")
        codec.validate(item, inbox=True)
        codec.validate(item | {"payload": {"selection": None}}, inbox=True)
        negatives = [
            {},
            {"model": "B"},
            {"model": "B", "route": []},
            {"model": "B", "route": {}, "extra": True},
            {"model": "B", "route": {}, "model_settings": {"timeout_seconds": 0}},
            {"model": "B", "route": {}, "model_settings": {"extra_headers": {"x": 1}}},
            {"model": "B", "route": {}, "model_settings": {"extra_body": None}},
        ]
        for selection in negatives:
            with (
                self.subTest(selection=selection),
                self.assertRaises(session.ValidationError),
            ):
                codec.validate(
                    item | {"payload": {"selection": selection}}, inbox=True
                )
        classes = {
            v["rejection_class"]
            for v in contractctl.load_json(ROOT / "fixtures/session_invalid.json")[
                "vectors"
            ]
        }
        self.assertIn("model_selection_input_id_conflict", classes)

    def test_authenticated_provider_usage_and_late_billing(self) -> None:
        inbox = copy.deepcopy(
            next(
                v["wire"]
                for v in self.vectors["vectors"]
                if v["type"] == "inbox" and v["wire"]["kind"] == "provider_result"
            )
        )
        self.assertEqual(inbox["schema_version"], "S1")
        usage_ref = inbox["payload"]["usage"]
        self.assertEqual(
            set(usage_ref), {"content_id", "mac", "size", "key_id", "labels"}
        )
        self.assertIsInstance(self.hydrate(usage_ref), dict)
        for usage in [
            {},
            {"prompt_tokens": 12000, "completion_tokens": 300},
            None,
            [],
            1,
            True,
            "usage",
        ]:
            with self.subTest(plaintext_usage=usage), self.assertRaises(
                session.ValidationError
            ):
                self.codec.validate(inbox | {"payload": inbox["payload"] | {"usage": usage}}, inbox=True)
        for payload in [
            {k: v for k, v in inbox["payload"].items() if k != "usage"},
            inbox["payload"] | {"extra": True},
        ]:
            with (
                self.subTest(payload=payload),
                self.assertRaises(session.ValidationError),
            ):
                self.codec.validate(inbox | {"payload": payload}, inbox=True)
        with self.assertRaises(session.ValidationError):
            self.codec.validate(inbox | {"schema_version": 1}, inbox=True)
        cases = {
            v["case"]: v
            for v in contractctl.load_json(ROOT / "fixtures/session_semantics.json")[
                "cases"
            ]
        }
        for context in ("normal", "audit"):
            case = cases["late_usage_" + context]
            self.assertEqual(case["context"], context)
            self.assertEqual(case["completion_count"], 1)
            self.assertEqual(case["replay_disposition"], "noop")
            usage = case["projected_usage"]
            self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (10, 5))
            self.assertEqual(usage["provider_usage"], case["usage"])
            self.assertEqual(usage["usage_source"], "provider_reported")
            self.assertEqual(usage["schema_version"], "vv-agent.token-usage.v1")

    def test_strict_versions_types_nullability_and_identity(self) -> None:
        sample = self.record("op_started")
        for field, value in [
            ("schema_version", x) for x in [None, True, 1.0, "1", 0, 2]
        ] + [
            ("attempt", None),
            ("operation_id", None),
            ("turn_id", None),
            ("record_id", "wrong"),
        ]:
            wire = sample | {field: value}
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(session.ValidationError),
            ):
                self.codec.validate(wire)
        for field in sample:
            wire = copy.deepcopy(sample)
            del wire[field]
            with (
                self.subTest(missing=field),
                self.assertRaises(session.ValidationError),
            ):
                self.codec.validate(wire)

    def test_opaque_values_still_enforce_ijson(self) -> None:
        for value in [
            {1: "key"},
            {"host": object()},
            {"deep": [float("nan")]},
            {"deep": ["\ud800"]},
            {"large": 2**53},
        ]:
            with (
                self.subTest(value=repr(value)),
                self.assertRaises(session.ValidationError),
            ):
                session.json_value(value)
        session.json_value(
            {
                "bool": True,
                "int": 1,
                "float": 1.5,
                "null": None,
                "astral": "😀",
                "combining": "e\u0301",
            }
        )

    def test_nested_hashes_and_reserved_maps_reject_drift(self) -> None:
        sample = self.record("op_planned")
        for digest in ["0" * 64, "A" * 64, sample["payload"]["request_digest"] + "\n"]:
            wire = copy.deepcopy(sample)
            wire["payload"]["request_digest"] = digest
            with (
                self.subTest(digest=digest),
                self.assertRaises(session.ValidationError),
            ):
                self.codec.validate(wire)
        wire = copy.deepcopy(sample)
        wire["payload"]["request"] = {
            "metadata": {"vv_session": {"extra": True}}
        }
        with self.assertRaises(session.ValidationError):
            self.codec.validate(wire)
        wire = self.record("turn_started")
        wire["payload"]["definition"] = {"task": {"metadata": {"extra": True}}}
        with self.assertRaises(session.ValidationError):
            self.codec.validate(wire)

    def test_creation_seed_and_compaction_identity(self) -> None:
        records = [v["wire"] for v in self.vectors["vectors"] if v["type"] == "record"]
        seeds = []
        for record in records:
            if record["kind"] != "session_created":
                continue
            attributes = self.hydrate(record["payload"]["attributes"])
            if isinstance(attributes, dict) and "seed" in attributes:
                seeds.append(attributes["seed"])
        self.assertTrue(seeds)
        for seed in seeds:
            self.assertIn(
                set(seed),
                (
                    {"messages", "shared_state"},
                    {"unseen_input_protection"},
                    {"messages", "shared_state", "unseen_input_protection"},
                    {"response_rejection"},
                    {"unseen_input_protection", "response_rejection"},
                    {"messages", "shared_state", "response_rejection"},
                    {
                        "messages",
                        "shared_state",
                        "unseen_input_protection",
                        "response_rejection",
                    },
                ),
            )
            for policy in ("unseen_input_protection", "response_rejection"):
                if policy in seed:
                    self.assertIs(type(seed[policy]), bool)
        compactions = [r for r in records if r["kind"] == "context_compacted"]
        self.assertEqual(
            {r["payload"]["summary_operation_id"] is None for r in compactions},
            {True, False},
        )
        for wire in compactions:
            p = wire["payload"]
            expected = f"compact/{p['source_digest']}/{p['mode']}"
            if p["summary_operation_id"] is not None:
                expected += "/" + p["summary_operation_id"]
            self.assertEqual(wire["record_id"], expected)
        for wire in records:
            if wire["kind"] == "op_completed":
                self.assertIn("shared_state", wire["payload"])

    def test_session_semantics_and_failure_cuts_retain_effect_assertions(self) -> None:
        cases = {
            v["case"]: v
            for v in contractctl.load_json(ROOT / "fixtures/session_semantics.json")[
                "cases"
            ]
        }
        replay = cases["replay_conflict_fence_ack_rollback"]
        self.assertTrue(replay["same_input_receipt"])
        self.assertTrue(replay["stale_writer_rejected"])
        self.assertEqual(replay["new_log_writes"], 0)
        for name in ["user_wait", "turn_wait"]:
            self.assertTrue(cases[name]["same_turn"])
        cuts = {
            v["case"]: v
            for v in contractctl.load_json(ROOT / "fixtures/session_recovery.json")[
                "cases"
            ]
        }
        self.assertTrue(
            {
                "op_planned",
                "op_prepared",
                "op_started",
                "op_completed",
                "accepted",
                "parked",
                "tool_a_done_b_pending",
                "boundary_before_commit",
                "boundary_after_commit",
                "summary_receipt",
                "rejected_receipt",
                "lost_wall_stop",
                "lost_wall_continue_and_mark",
            }
            <= set(cuts)
        )
        self.assertEqual(cuts["tool_a_done_b_pending"]["effects"], ["a", "b"])
        self.assertEqual(cuts["summary_receipt"]["summary_dispatches"], 1)
        self.assertGreater(
            cuts["boundary_before_commit"]["callback_calls"],
            cuts["boundary_after_commit"]["callback_calls"],
        )
        self.assertEqual(cuts["lost_wall_stop"]["status"], "failed")

    def test_projected_events_derive_stable_record_identity(self) -> None:
        projection = contractctl.load_json(ROOT / "fixtures/session_projection.json")
        for vector in projection["sessions"]:
            sid = vector["session_id"]
            source = projection["source_records"][sid]
            ids = {
                hashlib.sha256(
                    json.dumps(
                        [sid, r["wire"]["record_id"]],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                for r in source
            }
            retained_memory = {
                self.hydrate(r["wire"]["payload"]["data"]["event"])["event_id"]
                for r in source
                if r["wire"]["kind"] == "boundary_recorded"
                and r["wire"]["payload"]["stage"]
                in {"memory_started", "memory_completed"}
            }
            for event in vector["events"]:
                self.assertEqual(event["version"], "v6")
                self.assertEqual(event["session_id"], sid)
                if event["type"] in {
                    "memory_compact_started",
                    "memory_compact_completed",
                }:
                    self.assertIn(event["event_id"], retained_memory)
                    continue
                prefix, digest, slot = event["event_id"].split("/", 2)
                self.assertEqual(prefix, "sk")
                self.assertIn(digest, ids)
                self.assertTrue(slot)

    def test_node_detects_forged_canonical_bytes_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "fixtures", root / "fixtures")
            path = root / "fixtures/session_codec_vectors.json"
            fixture = contractctl.load_json(path)
            raw = base64.b64decode(fixture["vectors"][0]["bytes_base64"])
            raw = b" " + raw
            fixture["vectors"][0].update(
                bytes_base64=base64.b64encode(raw).decode(),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
            contractctl.write_json(path, fixture)
            result = subprocess.run(
                ["node", str(ROOT / "scripts/verify_jcs.mjs")],
                env={**os.environ, "CONTRACT_ROOT": str(root)},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical bytes mismatch", result.stderr)

    def test_schema_keyword_scope_is_explicit(self) -> None:
        with self.assertRaisesRegex(session.ValidationError, "unsupported schema"):
            session.check_schema_keywords(
                {"type": "object", "unevaluatedProperties": False}
            )
        schema = {
            "type": "object",
            "properties": {"kind": {}, "value": {}},
            "allOf": [
                {
                    "if": {
                        "properties": {"kind": {"const": "typed"}},
                        "required": ["kind"],
                    },
                    "then": {
                        "properties": {"value": {"type": "integer"}},
                        "required": ["value"],
                    },
                }
            ],
        }
        session.validate_schema({"kind": "opaque", "value": True}, schema)
        with self.assertRaises(session.ValidationError):
            session.validate_schema({"kind": "typed", "value": True}, schema)

    def test_app_server_current_wire_shared_control_and_closed_boundary(self) -> None:
        app = contractctl.load_json(ROOT / "fixtures/app_server_protocol.json")
        self.assertEqual(app["protocol_version"], "v5")
        self.assertTrue(app["facts"]["observer_can_approve"])
        self.assertTrue(app["facts"]["timeout_at_absolute_deadline"])
        closed_methods = {
            transcript["request"]["method"]
            for transcript in app["transcripts"]
            for response in transcript.get("responses", [])
            if response.get("error") == {"code": -32602, "message": "Thread is closed"}
        }
        self.assertEqual(closed_methods, {"turn/start", "turn/resume", "thread/resume"})
        resumes = [
            transcript
            for transcript in app["transcripts"]
            if transcript.get("request", {}).get("method") == "thread/resume"
        ]
        closed_subscriptions = {
            transcript["request"]["params"].get("subscribe", "default")
            for transcript in resumes
            for response in transcript.get("responses", [])
            if response.get("error") == {"code": -32602, "message": "Thread is closed"}
        }
        self.assertEqual(closed_subscriptions, {True, "default"})
        closed_snapshots = [
            response["result"]
            for transcript in resumes
            for response in transcript.get("responses", [])
            if transcript["request"]["params"].get("subscribe") is False
            and "result" in response
            and response["result"]["thread"]["status"] == "closed"
        ]
        self.assertTrue(closed_snapshots)

    def test_app_server_exports_use_one_status_and_current_optional_fields(
        self,
    ) -> None:
        app = contractctl.load_json(ROOT / "fixtures/app_server_protocol.json")
        expected = [
            "idle",
            "running",
            "provider_running",
            "child_running",
            "user_wait",
            "approval_wait",
            "retry_backoff",
            "suspended",
            "terminal",
            "archived",
            "closed",
        ]
        schemas = {
            name: json.loads(value)
            for name, value in app["schemas"]["jsonSchema"].items()
        }
        self.assertEqual(schemas["AppThread"]["properties"]["status"]["enum"], expected)
        for name, schema in schemas.items():
            for node in session.walk(schema):
                if (
                    isinstance(node, dict)
                    and "enum" in node
                    and "archived" in node["enum"]
                ):
                    self.assertEqual(node["enum"], expected, name)
        optional = contractctl.load_json(ROOT / "fixtures/app_server_observable.json")[
            "terminal"
        ]["optionalFieldsOmittedWhenAbsent"]
        self.assertEqual(
            set(optional),
            {
                "runId",
                "finalOutput",
                "completionReason",
                "completionToolName",
                "partialOutput",
                "waitReason",
                "error",
                "tokenUsage",
                "budgetUsage",
                "budgetExhaustion",
            },
        )


if __name__ == "__main__":
    unittest.main()
