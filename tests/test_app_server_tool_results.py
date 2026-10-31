"""Independent checks of real App Server tool-result producer facts."""

import base64
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ToolResultsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / "fixtures/app_server_tool_results.json").read_text())
        self.cases = {c["name"]: c for c in self.fixture["cases"]}

    def test_output_kinds_resources_and_no_storage_copy(self):
        self.assertEqual(self.fixture["protocolVersion"], "v5")
        self.assertEqual([self.cases[k]["summary"]["kind"] for k in ("text", "json", "image", "file", "error")],
                         ["text", "json", "image", "file", "error"])
        self.assertEqual(self.fixture["effects"], {"toolExecutions": 9, "copies": 0})
        self.assertEqual(self.fixture["storageCallsAtCompletion"], ["put_version"])
        self.assertEqual(base64.b64decode(self.cases["text"]["firstPage"]["data"]), b"plain text")
        self.assertEqual(self.cases["json"]["summary"]["value"], {"answer": 42, "汉字": "🙂"})
        expected = bytes(range(256)) * 4097
        resource = self.cases["file"]["resources"][0]
        self.assertEqual(resource["bytes"], len(expected))
        self.assertEqual(resource["sha256"], hashlib.sha256(expected).hexdigest())
        image = base64.b64decode(self.cases["image"]["resources"][0]["firstPage"]["data"])
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(image[16:20], "big"), 1)
        self.assertEqual(int.from_bytes(image[20:24], "big"), 1)
        unicode = ("开头🙂漢字\n" * 20_000).encode()
        self.assertEqual(self.cases["unicode"]["firstPage"]["totalBytes"], len(unicode))
        self.assertEqual(self.cases["unicode"]["contentSha256"], hashlib.sha256(unicode).hexdigest())
        self.assertEqual(self.cases["artifact"]["resources"][0]["sha256"], hashlib.sha256(unicode).hexdigest())
        self.assertTrue(self.cases["artifact"]["summary"]["resources"][0]["fullText"])
        self.assertEqual(self.cases["url"]["summary"]["resources"][0]["status"], "not_retained")
        self.assertEqual(self.cases["cursor"]["summary"]["cursor"]["offsetChars"], 3)

    def test_bounds_exact_refs_and_private_locators_absent(self):
        self.assertEqual(self.fixture["limits"], {
            "previewBytes": 2048, "inlineBytes": 8192, "descriptorBytes": 16384,
            "resources": 8, "labelBytes": 256, "pageBytes": 65536,
            "responseBytes": 98304, "chunkBytes": 65536,
        })
        for case in self.cases.values():
            summary = case["summary"]
            self.assertLessEqual(len(summary["preview"].encode()), 2048)
            self.assertLessEqual(len(json.dumps(summary, ensure_ascii=False).encode()), 16384)
            self.assertEqual(set(summary["ref"]), {
                "sessionId", "turnId", "operationId", "attempt", "toolCallId", "seq", "recordDigest",
            })
            self.assertEqual(case["firstPage"]["ref"], summary["ref"])
            self.assertEqual(case["firstPage"]["context"], "normal")
            self.assertTrue(case["lastPage"]["eof"])
            for page in (case["firstPage"], case["lastPage"]):
                self.assertLessEqual(len(base64.b64decode(page["data"], validate=True)), 65536)
                self.assertEqual(page["encoding"], "base64")
        public = json.dumps([case["summary"] for case in self.cases.values()])
        for private in ("locator", "workspace_id", "version:", ".vv-agent", "private.invalid", "private-metadata"):
            self.assertNotIn(private, public)

    def test_error_table_is_from_wire(self):
        errors = self.fixture["negativeCases"]
        for name, value in errors.items():
            reason = "invalid_result_ref" if name == "forged_resource" else name
            self.assertEqual(value["code"], -32027 if name == "permission_denied" else -32602)
            self.assertEqual(value["data"]["reason"], reason)
