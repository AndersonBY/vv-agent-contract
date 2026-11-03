"""Independent byte, source and projection checks for kernel-produced S1 vectors."""

import errno
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "\n... output omitted; full text in artifact ...\n"


class ToolResultArtifactTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / "fixtures/tool_result_artifact.json").read_text())

    def test_bounded_existing_captures_have_operation_bound_provenance(self):
        bounded = json.loads((ROOT / "fixtures/bounded_tool_result.json").read_text())
        reference_fields = {"path", "media_type", "encoding", "size_bytes", "sha256"}
        for name, call_id in (("truncated_bash", "call-bash"), ("truncated_error", "call-error")):
            with self.subTest(name=name):
                result = bounded["canonical_results"][name]
                artifact = result["artifact"]
                self.assertEqual(set(artifact), reference_fields)
                entry = result["metadata"]["vv_artifact"]
                self.assertEqual(set(entry), reference_fields | {
                    "source", "source_complete", "capture_incomplete_reason",
                })
                self.assertEqual({key: entry[key] for key in reference_fields}, artifact)
                self.assertIs(entry["source_complete"], False)
                self.assertEqual(entry["capture_incomplete_reason"], "capture_completeness_unverified")
                self.assertEqual(result["tool_call_id"], call_id)
                self.assertEqual(entry["source"], {
                    "operation_id": f"c1c/bounded_{name}/turn/initial/model/primary/1/attempt/1/tool/0",
                    "attempt": 1,
                    "tool_call_id": call_id,
                    "arguments_sha256": hashlib.sha256(b"{}").hexdigest(),
                })
                self.assertIs(type(entry["source"]["attempt"]), int)

    def test_short_result_and_three_projection_cases(self):
        cases = self.fixture["cases"]
        self.assertEqual(cases["short"]["result"], {
            "tool_call_id": "call-s1", "content": "ok", "status_code": "SUCCESS", "directive": "continue",
        })
        bounded = json.loads((ROOT / "fixtures/bounded_tool_result.json").read_text())["unified_projection"]
        self.assertEqual(bounded["ordinary_unchanged"], cases["short"])
        self.assertEqual(bounded["newly_truncated"], cases["long_ascii"])
        self.assertEqual(bounded["already_truncated"], cases["already_truncated"])
        self.assertEqual(bounded["marker"], {
            "source_character_count_excludes_notice": True,
            "includes_artifact_path": True,
            "read_range": "read_file(start_line, end_line)",
            "search_regex": "search_files(pattern)",
            "head_chars": 6000,
            "tail_chars": "12000 - head_chars - marker_chars",
            "already_truncated": "preserve_producer_marker_and_recovery",
        })

    def test_original_utf8_digest_and_preview_are_independently_reconstructed(self):
        for name, case in self.fixture["cases"].items():
            if name == "short":
                continue
            with self.subTest(name=name):
                text = case["input"]["unit"] * case["input"]["repeat"]
                result = case["result"]
                if name == "already_truncated":
                    marker = MARKER
                else:
                    start = result["content"].index("\n... ", 6000)
                    end = result["content"].index(" ...\n", start) + len(" ...\n")
                    marker = result["content"][start:end]
                    shown = 12000 - len(marker)
                    self.assertEqual(marker, (
                        f"\n... {shown} of {len(text)} source characters shown; full text in {result['artifact']['path']}; "
                        "read a range with read_file(start_line, end_line) or search with search_files(pattern) ...\n"
                    ))
                tail = 12000 - 6000 - len(marker)
                self.assertEqual(result["content"], text[:6000] + marker + text[-tail:])
                self.assertEqual(len(result["content"]), 12000)
                self.assertEqual(result["original_bytes"], len(text.encode()))
                self.assertEqual(result["visible_bytes"], len(result["content"].encode()))
                artifact = result["artifact"]
                self.assertTrue(artifact["path"].startswith(".vv-agent/artifacts/"))
                self.assertEqual(artifact["sha256"], hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(artifact["size_bytes"], len(text.encode()))
                if name == "archive_unavailable":
                    self.assertNotIn("vv_artifact", result["metadata"])
                    self.assertEqual(result["metadata"]["app_server_resources"][0]["status"], "unavailable")
                    self.assertEqual(result["status_code"], "SUCCESS")
                    continue
                entry = result["metadata"]["vv_artifact"]
                self.assertEqual({key: entry[key] for key in artifact}, artifact)
                self.assertEqual(entry["source"], {
                    **case["source"], "tool_call_id": "call-s1", "arguments_sha256": hashlib.sha256(b"{}").hexdigest(),
                })
                complete = name != "already_truncated"
                self.assertEqual(entry["source_complete"], complete)
                self.assertEqual(entry["capture_incomplete_reason"], None if complete else "capture_completeness_unverified")
                canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                self.assertEqual(hashlib.sha256(canonical).hexdigest(), case["result_sha256"])

    def test_conflict_and_actual_digest_failure_are_fail_closed(self):
        self.assertEqual(self.fixture["integrity"]["same_identity_different_bytes"], {
            "errno": errno.EIO, "retained_text": "first", "writes": 1,
        })
        self.assertEqual(self.fixture["integrity"]["digest_mismatch"], {
            "status": "SUCCESS", "artifact_status": "unavailable", "vv_artifact_present": False,
        })
        names = {case["name"] for case in self.fixture["invalid_cases"]}
        self.assertTrue({"producer_forged_namespace", "digest_mismatch", "size_mismatch",
                         "invalid_path", "false_without_reason", "true_with_reason"}.issubset(names))
        self.assertTrue(all("forbidden_" + key in names for key in ("content", "output", "stdout", "stderr", "instructions")))
