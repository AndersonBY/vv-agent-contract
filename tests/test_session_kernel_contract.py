from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contractctl
import session_validation as session


class SessionKernelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vectors = contractctl.load_json(ROOT / "fixtures/session_codec_vectors.json")
        cls.codec = session.Codec(ROOT, cls.vectors)

    def record(self, kind: str) -> dict:
        return copy.deepcopy(next(v["wire"] for v in self.vectors["vectors"]
                                  if v["type"] == "record" and v["wire"]["kind"] == kind))

    def test_all_new_schema_codec_and_layer_vectors_validate(self) -> None:
        report = session.validate_session_fixtures(ROOT)
        self.assertGreater(report["records"], 100)
        self.assertGreater(report["inbox_items"], 50)
        self.assertEqual(report["codec_vectors"], 77)
        self.assertEqual(report["invalid_vectors"], 47)

    def test_strict_versions_types_nullability_and_identity(self) -> None:
        sample = self.record("op_started")
        for field, value in [("schema_version", x) for x in [None, True, 1.0, "1", 0, 2]] + [
            ("attempt", None), ("operation_id", None), ("turn_id", None), ("record_id", "wrong"),
        ]:
            wire = sample | {field: value}
            with self.subTest(field=field, value=value), self.assertRaises(session.ValidationError):
                self.codec.validate(wire)
        for field in sample:
            wire = copy.deepcopy(sample)
            del wire[field]
            with self.subTest(missing=field), self.assertRaises(session.ValidationError):
                self.codec.validate(wire)

    def test_opaque_values_still_enforce_ijson(self) -> None:
        for value in [{1: "key"}, {"host": object()}, {"deep": [float("nan")]},
                      {"deep": ["\ud800"]}, {"large": 2**53}]:
            with self.subTest(value=repr(value)), self.assertRaises(session.ValidationError):
                session.json_value(value)
        session.json_value({"bool": True, "int": 1, "float": 1.5, "null": None,
                            "astral": "😀", "combining": "e\u0301"})

    def test_nested_hashes_and_reserved_maps_reject_drift(self) -> None:
        sample = self.record("op_planned")
        for digest in ["0" * 64, "A" * 64, sample["payload"]["request_digest"] + "\n"]:
            wire = copy.deepcopy(sample)
            wire["payload"]["request_digest"] = digest
            with self.subTest(digest=digest), self.assertRaises(session.ValidationError):
                self.codec.validate(wire)
        wire = copy.deepcopy(sample)
        wire["payload"]["request"]["metadata"]["vv_session"]["extra"] = True
        with self.assertRaises(session.ValidationError):
            self.codec.validate(wire)
        wire = self.record("turn_started")
        wire["payload"]["definition"]["task"]["metadata"]["vv_session"] = {"extra": True}
        with self.assertRaises(session.ValidationError):
            self.codec.validate(wire)

    def test_creation_seed_and_compaction_identity(self) -> None:
        records = [v["wire"] for v in self.vectors["vectors"] if v["type"] == "record"]
        seeds = [r["payload"]["attributes"]["seed"] for r in records
                 if r["kind"] == "session_created" and "seed" in r["payload"]["attributes"]]
        self.assertTrue(seeds)
        for seed in seeds:
            self.assertEqual(set(seed), {"messages", "shared_state"})
        compactions = [r for r in records if r["kind"] == "context_compacted"]
        self.assertEqual({r["payload"]["summary_operation_id"] is None for r in compactions}, {True, False})
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
        cases = {v["case"]: v for v in contractctl.load_json(ROOT / "fixtures/session_semantics.json")["cases"]}
        replay = cases["replay_conflict_fence_ack_rollback"]
        self.assertTrue(replay["same_input_receipt"])
        self.assertTrue(replay["stale_writer_rejected"])
        self.assertEqual(replay["new_log_writes"], 0)
        for name in ["user_wait", "turn_wait"]:
            self.assertTrue(cases[name]["same_turn"])
        cuts = {v["case"]: v for v in contractctl.load_json(ROOT / "fixtures/session_recovery.json")["cases"]}
        self.assertTrue({"op_planned", "op_prepared", "op_started", "op_completed", "accepted",
                         "parked", "tool_a_done_b_pending", "boundary_before_commit", "boundary_after_commit",
                         "summary_receipt", "rejected_receipt", "lost_wall_stop", "lost_wall_continue_and_mark"} <= set(cuts))
        self.assertEqual(cuts["tool_a_done_b_pending"]["effects"], ["a", "b"])
        self.assertEqual(cuts["summary_receipt"]["summary_dispatches"], 1)
        self.assertGreater(cuts["boundary_before_commit"]["callback_calls"], cuts["boundary_after_commit"]["callback_calls"])
        self.assertEqual(cuts["lost_wall_stop"]["status"], "failed")

    def test_projected_events_derive_stable_record_identity(self) -> None:
        projection = contractctl.load_json(ROOT / "fixtures/session_projection.json")
        for vector in projection["sessions"]:
            sid = vector["session_id"]
            source = projection["source_records"][sid]
            ids = {hashlib.sha256(json.dumps([sid, r["wire"]["record_id"]], ensure_ascii=False,
                   separators=(",", ":")).encode()).hexdigest() for r in source}
            retained_memory = {r["wire"]["payload"]["data"]["event"]["event_id"]
                               for r in source if r["wire"]["kind"] == "boundary_recorded"
                               and r["wire"]["payload"]["stage"] in {"memory_started", "memory_completed"}}
            for event in vector["events"]:
                self.assertEqual(event["version"], "v6")
                self.assertEqual(event["session_id"], sid)
                if event["type"] in {"memory_compact_started", "memory_compact_completed"}:
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
            fixture["vectors"][0].update(bytes_base64=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())
            contractctl.write_json(path, fixture)
            result = subprocess.run(["node", str(ROOT / "scripts/verify_jcs.mjs")],
                                    env={**os.environ, "CONTRACT_ROOT": str(root)}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical bytes mismatch", result.stderr)

    def test_schema_keyword_scope_is_explicit(self) -> None:
        with self.assertRaisesRegex(session.ValidationError, "unsupported schema"):
            session.check_schema_keywords({"type": "object", "unevaluatedProperties": False})
        schema = {"type": "object", "properties": {"kind": {}, "value": {}},
                  "allOf": [{"if": {"properties": {"kind": {"const": "typed"}}, "required": ["kind"]},
                             "then": {"properties": {"value": {"type": "integer"}}, "required": ["value"]}}]}
        session.validate_schema({"kind": "opaque", "value": True}, schema)
        with self.assertRaises(session.ValidationError):
            session.validate_schema({"kind": "typed", "value": True}, schema)

    def test_app_server_current_wire_owner_and_closed_boundary(self) -> None:
        app = contractctl.load_json(ROOT / "fixtures/app_server_protocol.json")
        self.assertEqual(app["protocol_version"], "v2")
        self.assertTrue(app["facts"]["observer_cannot_approve"])
        self.assertTrue(app["facts"]["timeout_at_absolute_deadline"])
        closed_methods = {transcript["request"]["method"] for transcript in app["transcripts"]
                          for response in transcript.get("responses", [])
                          if response.get("error") == {"code": -32602, "message": "Thread is closed"}}
        self.assertEqual(closed_methods, {"turn/start", "turn/resume", "thread/resume"})
        resumes = [transcript for transcript in app["transcripts"]
                   if transcript.get("request", {}).get("method") == "thread/resume"]
        closed_subscriptions = {transcript["request"]["params"].get("subscribe", "default")
                                for transcript in resumes
                                for response in transcript.get("responses", [])
                                if response.get("error") == {"code": -32602, "message": "Thread is closed"}}
        self.assertEqual(closed_subscriptions, {True, "default"})
        closed_snapshots = [response["result"] for transcript in resumes
                            for response in transcript.get("responses", [])
                            if transcript["request"]["params"].get("subscribe") is False
                            and "result" in response and response["result"]["thread"]["status"] == "closed"]
        self.assertTrue(closed_snapshots)

    def test_app_server_exports_use_one_status_and_current_optional_fields(self) -> None:
        app = contractctl.load_json(ROOT / "fixtures/app_server_protocol.json")
        expected = ["idle", "running", "interrupted", "archived", "closed"]
        schemas = {name: json.loads(value) for name, value in app["schemas"]["jsonSchema"].items()}
        self.assertEqual(schemas["AppThread"]["properties"]["status"]["enum"], expected)
        for name, schema in schemas.items():
            for node in session.walk(schema):
                if isinstance(node, dict) and "enum" in node and "archived" in node["enum"]:
                    self.assertEqual(node["enum"], expected, name)
        optional = contractctl.load_json(ROOT / "fixtures/app_server_observable.json")["terminal"]["optionalFieldsOmittedWhenAbsent"]
        self.assertEqual(set(optional), {"runId", "finalOutput", "completionReason", "completionToolName",
                                        "partialOutput", "waitReason", "error", "tokenUsage", "budgetUsage", "budgetExhaustion"})


if __name__ == "__main__":
    unittest.main()
