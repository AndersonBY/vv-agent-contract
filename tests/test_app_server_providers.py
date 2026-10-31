"""Observable provider vectors authored by the Python App Server producer."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProviderContractTests(unittest.TestCase):
    def test_recovery_reuses_the_accepted_job(self):
        value = json.loads((ROOT / "fixtures/app_server_providers.json").read_text())
        self.assertEqual(value["protocol_version"], "v5")
        self.assertEqual(value["accepted"]["status"], "provider_running")
        handle = value["accepted"]["handle"]
        self.assertEqual(handle["provider"], "work")
        self.assertEqual(handle["attempt"], 1)
        self.assertRegex(handle["request_digest"], r"^[0-9a-f]{64}$")
        result = value["recovered"]
        self.assertEqual(result["result"]["tool_call_id"], "business-call")
        self.assertIn(handle["evidence"], result["evidence"])
        self.assertEqual((result["submit_count"], result["effect_count"]), (1, 1))
        self.assertEqual(result["context"], "normal")
        self.assertEqual(result["status"], "terminal")

    def test_bad_results_keep_waits_and_cancel_does_not_forge_confirmation(self):
        value = json.loads((ROOT / "fixtures/app_server_providers.json").read_text())
        self.assertEqual(
            {case["case"] for case in value["strict_results"]},
            {"call", "status", "evidence", "empty_evidence", "ambiguous", "fields"},
        )
        for case in value["strict_results"]:
            self.assertEqual(case["state"], "parked")
            self.assertTrue(case["handle_retained"])
            self.assertFalse(case["turn_ended"])
            self.assertEqual(case["warning"], "provider_result_invalid")
            self.assertEqual((case["submit_count"], case["effect_count"]), (1, 1))
        for case in value["cancellation"]:
            self.assertTrue(case["requested"])
            self.assertEqual(case["turn_status"], "cancelled")
            confirmed = case["provider_return"] == "confirmed"
            self.assertEqual(case["unconfirmed_count"], 0 if confirmed else 1)
            self.assertEqual(case["completion_context"], "audit" if confirmed else None)
            self.assertEqual(
                case["business_state"], "stopped" if case["provider_return"] in {"confirmed", "invalid"} else "running"
            )

    def test_api_inventory_includes_provider_registration_and_exports(self):
        api = json.loads((ROOT / "fixtures/public_api.json").read_text())
        exports = next(domain for domain in api["domains"] if domain["id"] == "exports")
        self.assertTrue(
            {"vv_agent.Provider", "vv_agent.Accepted", "vv_agent.Definitive", "vv_agent.Unknown"}
            <= {item["python"] for item in exports["capabilities"]}
        )
        config = next(surface for surface in api["surfaces"] if surface["id"] == "run_config")
        self.assertIn("tool_providers", {member["id"] for member in config["members"]})


if __name__ == "__main__":
    unittest.main()
