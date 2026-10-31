"""Independent checks on the canonical typed interaction producer facts."""

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TypedInteractions(unittest.TestCase):
    def test_forms_and_reply_labels_are_closed_and_bound(self):
        fixture = json.loads((ROOT / "fixtures/app_server_interactions.json").read_text())
        self.assertEqual(fixture["protocolVersion"], "v5")
        self.assertEqual(
            fixture["limits"],
            {"promptBytes": 16384, "options": 64, "optionBytes": 1024, "formBytes": 65536, "answerBytes": 65536},
        )
        self.assertEqual([c["name"] for c in fixture["cases"]], ["text", "single", "multi", "custom", "choice-free-text"])
        for case in fixture["cases"]:
            form = case["form"]
            self.assertEqual(
                set(form),
                {
                    "kind",
                    "sessionId",
                    "turnId",
                    "generation",
                    "interactionId",
                    "operationId",
                    "attempt",
                    "requestDigest",
                    "prompt",
                    "answerSpec",
                },
            )
            self.assertEqual(form["kind"], "user")
            unsigned = {k: v for k, v in form.items() if k not in {"kind", "requestDigest"}}
            # All form keys are ASCII and numbers are integers: stdlib ordering is independent JCS here.
            encoded = json.dumps(unsigned, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
            self.assertEqual(hashlib.sha256(encoded).hexdigest(), form["requestDigest"])
            self.assertEqual(case["invalidAnswer"]["code"], -32602)
            self.assertEqual(case["conflict"]["code"], -32024)
            self.assertEqual(case["modelCalls"], 2)
            result = case["modelResult"]
            if case["answer"]["kind"] == "text":
                self.assertEqual(set(result), {"reply_mode", "text"})
                self.assertEqual(result["reply_mode"], "free_text")
            else:
                self.assertEqual(set(result), {"reply_mode", "selection_type", "selected", "custom"})
                self.assertEqual(result["reply_mode"], "selection")
        choice = fixture["cases"][-1]
        self.assertFalse(choice["form"]["answerSpec"]["allowCustomOptions"])
        self.assertEqual(choice["modelResult"], {"reply_mode": "free_text", "text": "NOT_AN_OPTION"})

    def test_tool_contract_and_public_api_cover_host_adoption(self):
        behavior = json.loads((ROOT / "fixtures/builtin_tool_behavior.json").read_text())["canonical"]["user_interactions"]
        self.assertEqual(behavior["oversize_error"], "interaction_form_too_large")
        self.assertEqual(behavior["reply_shapes"]["text"]["reply_mode"], "free_text")
        api = json.loads((ROOT / "fixtures/public_api.json").read_text())
        targets = {s["python_target"] for s in api["surfaces"]}
        for name in (
            "AppServerUserInteraction",
            "InteractionAnswer",
            "InteractionAnswerSpec",
            "InteractionReplyTarget",
            "HeartbeatStopped",
        ):
            self.assertIn("vv_agent." + name, targets)
