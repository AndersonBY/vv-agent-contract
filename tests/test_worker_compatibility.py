from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contractctl  # noqa: E402
import session_validation as session  # noqa: E402


class WorkerCompatibilityAllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = contractctl.load_json(
            ROOT / "fixtures/worker_compatibility.json"
        )
        cls.schema = contractctl.load_json(
            ROOT / "fixtures/worker_compatibility.schema.json"
        )

    @staticmethod
    def tag(prefix: str, value: dict) -> str:
        return prefix + session.jcs_digest(ROOT, value)

    @staticmethod
    def sorted_unique(values: list[str]) -> list[str]:
        session.require_sorted_unique(values, "capabilities")
        return values

    def expected_cache(self, case: dict) -> dict:
        if case["kind"] == "selection_handler_mismatch":
            return case["cache_before"]
        input_requirements = case["input_requirements"]
        if case["phase"] == "active":
            active = case["active_requirements"]
            capabilities = sorted(
                set(active["capabilities"]) | set(input_requirements["capabilities"])
            )
            return {
                "level": max(active["level"], input_requirements["level"]),
                "handler_version": active["handler_version"],
                "required_capabilities": capabilities,
                "active_turn_id": case["cache_before"]["active_turn_id"],
            }
        return {
            "level": input_requirements["level"],
            "handler_version": input_requirements["handler_version"],
            "required_capabilities": sorted(input_requirements["capabilities"]),
            "active_turn_id": None,
        }

    def test_allocation_fixture_is_non_adoption_evidence(self) -> None:
        session.validate_schema(self.fixture, self.schema, self.schema)
        self.assertEqual(self.fixture["contract_version"], "41.0.0")
        self.assertEqual(self.fixture["status"], "contract-allocation-only")
        self.assertFalse(self.fixture["provenance"]["producer_capture"])
        self.assertEqual(self.fixture["provenance"]["capture"], "none")
        self.assertFalse(self.fixture["provenance"]["adoption_evidence"])
        self.assertEqual(
            self.fixture["allocation"]["w3_execution"],
            "feature-level-3-command-identity-and-authenticated-lookup",
        )

    def test_level_two_worker_rejects_level_three_execution_record(self) -> None:
        cases = {
            case["name"]: case for case in self.fixture["level_three_cases"]
        }
        self.assertEqual(
            set(cases),
            {"level_two_worker_never_claims_level_three_execution_record"},
        )
        case = cases["level_two_worker_never_claims_level_three_execution_record"]
        self.assertEqual(case["session_bootstrap_feature_level"], 2)
        self.assertEqual(case["execution_record_feature_level"], 3)
        self.assertEqual(case["expected_cache"]["level"], 3)
        self.assertEqual(
            case["expected_cache"]["required_capabilities"], ["env:remote"]
        )
        self.assertFalse(case["level2_worker_accepted"])
        self.assertTrue(case["level3_worker_accepted"])
        self.assertFalse(case["level2_reader_accepted"])
        self.assertTrue(
            case["level3_reader_without_execution_supports_accepted"]
        )
        self.assertFalse(case["body_decoded"])
        self.assertFalse(case["epoch_granted"])

    def test_tool_and_model_tags_are_recomputed_from_the_same_facts(self) -> None:
        catalog = self.fixture["trusted_catalog"]
        for tool in catalog["tools"]:
            fact = {field: tool[field] for field in ("name", "schema", "metadata")}
            with self.subTest(tool=tool["tag"]):
                self.assertEqual(set(tool["schema"]), {"type", "function"})
                function = tool["schema"]["function"]
                self.assertEqual(
                    set(function), {"name", "description", "parameters", "strict"}
                )
                self.assertEqual(tool["schema"]["type"], "function")
                self.assertEqual(function["name"], tool["name"])
                self.assertEqual(function["parameters"]["type"], "object")
                self.assertIs(type(function["strict"]), bool)
                self.assertEqual(tool["tag"], self.tag("tool:", fact))
                parameters_only = {
                    "name": tool["name"],
                    "schema": function["parameters"],
                    "metadata": tool["metadata"],
                }
                self.assertNotEqual(tool["tag"], self.tag("tool:", parameters_only))
        for model in catalog["models"]:
            with self.subTest(model=model["tag"]):
                self.assertEqual(
                    set(model["identity"]),
                    {
                        "backend",
                        "model",
                        "context_length",
                        "max_output_tokens",
                    },
                )
                self.assertEqual(model["tag"], self.tag("model:", model["identity"]))

        tags = [tool["tag"] for tool in catalog["tools"]]
        self.assertEqual(len(tags), len(set(tags)))
        self.assertNotEqual(catalog["tools"][0]["tag"], catalog["tools"][1]["tag"])
        self.assertEqual(catalog["tools"][2]["metadata"], {})

    def test_model_tags_use_atomic_resolved_bindings(self) -> None:
        cases = {case["name"]: case for case in self.fixture["model_tag_cases"]}
        self.assertEqual(
            set(cases),
            {
                "endpoint_order_does_not_change_tag",
                "capacity_change_changes_tag",
                "internal_reuse_emits_unique_atomic_tags",
            },
        )
        identity_fields = {
            "backend",
            "model",
            "context_length",
            "max_output_tokens",
        }
        for case in cases.values():
            tags = []
            for item in case["bindings"]:
                binding = item["binding"]
                with self.subTest(case=case["name"], purpose=item["purpose"]):
                    self.assertEqual(
                        set(binding), identity_fields | {"endpoints"}
                    )
                    identity = {field: binding[field] for field in identity_fields}
                    tags.append(self.tag("model:", identity))
            self.assertEqual(tags, case["expected_tags"])

        endpoint_order = cases["endpoint_order_does_not_change_tag"]
        self.assertEqual(len(set(endpoint_order["expected_tags"])), 1)
        self.assertNotEqual(
            endpoint_order["bindings"][0]["binding"]["endpoints"],
            endpoint_order["bindings"][1]["binding"]["endpoints"],
        )

        capacity = cases["capacity_change_changes_tag"]
        self.assertEqual(len(set(capacity["expected_tags"])), 2)
        self.assertNotEqual(
            capacity["bindings"][0]["binding"]["context_length"],
            capacity["bindings"][1]["binding"]["context_length"],
        )

        internal = cases["internal_reuse_emits_unique_atomic_tags"]
        self.assertEqual(len(internal["expected_tags"]), 3)
        self.assertEqual(len(set(internal["expected_tags"])), 2)
        self.assertIn("internal.memory", {item["purpose"] for item in internal["bindings"]})
        self.assertIn("internal.summary", {item["purpose"] for item in internal["bindings"]})
        summary = next(
            item["binding"]
            for item in internal["bindings"]
            if item["purpose"] == "internal.summary"
        )
        self.assertIn("context_length", summary)
        self.assertIn("max_output_tokens", summary)
        self.assertIsNone(summary["context_length"])
        self.assertIsNone(summary["max_output_tokens"])

    def test_cache_recalculation_and_pre_epoch_rejection_calls(self) -> None:
        names = set()
        for case in self.fixture["cases"]:
            with self.subTest(case=case["name"]):
                names.add(case["kind"])
                expected = self.expected_cache(case)
                self.sorted_unique(expected["required_capabilities"])
                self.assertEqual(case["expected_cache"], expected)
                self.sorted_unique(case["supports"])
                self.sorted_unique(case["input_requirements"]["capabilities"])
                if case["active_requirements"] is not None:
                    self.sorted_unique(
                        case["active_requirements"]["capabilities"]
                    )

                compatible = set(expected["required_capabilities"]) <= set(
                    case["supports"]
                )
                if case["kind"] == "selection_handler_mismatch":
                    compatible = False
                self.assertEqual(case["expected_compatible"], compatible)
                if case["kind"] == "selection_handler_mismatch":
                    action = "reject_publication"
                elif case["kind"] == "cache_understatement":
                    action = "reject_ledger_integrity"
                elif not compatible:
                    action = "reject_unroutable"
                else:
                    action = "grant_lease"
                self.assertEqual(case["expected_action"], action)
                self.assertFalse(case["content_hydrated"])
                self.assertEqual(case["epoch_granted"], action == "grant_lease")

        self.assertEqual(
            names,
            {
                "tool_visible_subset",
                "tool_tag_mismatch",
                "active_model_union",
                "active_unsupported_model",
                "active_supported_model",
                "bootstrap_family",
                "selection_handler_mismatch",
                "cache_understatement",
            },
        )

    def test_active_model_union_and_understatement_order(self) -> None:
        cases = {case["kind"]: case for case in self.fixture["cases"]}
        active = cases["active_model_union"]
        self.assertEqual(
            active["expected_cache"]["required_capabilities"],
            sorted(
                active["active_requirements"]["capabilities"]
                + active["input_requirements"]["capabilities"]
            ),
        )
        self.assertEqual(active["expected_cache"]["active_turn_id"], "turn-active")

        understated = cases["cache_understatement"]
        self.assertTrue(understated["expected_compatible"])
        self.assertNotEqual(
            understated["cache_before"], understated["expected_cache"]
        )
        self.assertEqual(understated["expected_action"], "reject_ledger_integrity")
        self.assertFalse(understated["content_hydrated"])
        self.assertFalse(understated["epoch_granted"])

    def test_queued_and_ready_pending_follow_producer_admission_order(self) -> None:
        case = self.fixture["admission_order_cases"][0]
        queued = case["queued_inputs"]
        pending = sorted(
            case["ready_pending_inputs"], key=lambda item: item["input_seq"]
        )
        self.assertTrue(all(item["ready"] for item in queued + pending))
        self.assertEqual(
            [item["input_id"] for item in pending], case["expected_apply_order"]
        )

        # apply_input runs to exhaustion before start_turn. The latter performs a
        # stable sort on kind == follow_up, so a later user can precede queued h2.
        all_queued = queued + pending
        turn_order = sorted(all_queued, key=lambda item: item["kind"] == "follow_up")
        self.assertEqual(
            [item["input_id"] for item in turn_order],
            case["expected_turn_start_order"],
        )

        first = turn_order[0]
        expected_cache = {
            "level": first["requirements"]["level"],
            "handler_version": first["requirements"]["handler_version"],
            "required_capabilities": sorted(
                first["requirements"]["capabilities"]
            ),
            "active_turn_id": None,
        }
        self.assertEqual(case["expected_cache"], expected_cache)
        self.assertNotEqual(
            queued[0]["requirements"]["handler_version"],
            case["expected_cache"]["handler_version"],
        )
        self.assertFalse(
            set(case["expected_cache"]["required_capabilities"])
            <= set(case["current_worker_supports"])
        )
        self.assertEqual(
            case["expected_worker_disposition"], "defer_to_compatible_worker"
        )
        self.assertFalse(case["content_hydrated"])
        for item in all_queued:
            self.assertNotIn("payload", item)
            self.assertNotIn("content", item)

    def test_format_floor_does_not_follow_nested_requirements_level(self) -> None:
        case = next(
            item
            for item in self.fixture["format_floor_cases"]
            if item["name"] == "l2_bootstrap_inner_level_one_preserves_format_floor_after_turn_end"
        )
        format_floor = max(
            case["stored_record_feature_levels"]
            + case["activated_inbox_feature_levels"]
        )
        routing_level = max(
            case["bootstrap_requirements"]["level"],
            case["current_routing_requirements"]["level"],
        )
        self.assertEqual(case["boundary"], "turn_end_idle")
        self.assertEqual(case["bootstrap_container_feature_level"], 2)
        self.assertEqual(case["bootstrap_requirements"]["level"], 1)
        self.assertEqual(case["current_routing_requirements"]["level"], 1)
        self.assertEqual(format_floor, 2)
        self.assertEqual(
            case["expected_cache"]["level"], max(format_floor, routing_level)
        )
        self.assertEqual(
            case["expected_cache"],
            {
                "level": 2,
                "handler_version": "handler-h1",
                "required_capabilities": [],
                "active_turn_id": None,
            },
        )
        self.assertFalse(case["level1_executor_accepted"])
        self.assertTrue(case["level2_executor_accepted"])
        self.assertFalse(case["level1_reader_accepted"])
        self.assertTrue(
            case["level2_reader_without_execution_supports_accepted"]
        )
        self.assertFalse(case["content_hydrated"])
        self.assertEqual(
            self.fixture["allocation"]["cache"],
            "format-floor-plus-active-turn-or-combined-idle-admission-order",
        )

    def test_future_unconsumed_input_affects_format_floor_not_ready_route(self) -> None:
        case = next(
            item
            for item in self.fixture["format_floor_cases"]
            if item["name"]
            == "unconsumed_future_l2_input_contributes_format_floor_not_ready_route"
        )
        self.assertEqual(case["boundary"], "idle_before_first_turn")
        self.assertEqual(case["activated_inbox_feature_levels"], [2])
        self.assertEqual(case["current_routing_requirements"]["level"], 1)
        self.assertEqual(case["expected_cache"]["level"], 2)
        self.assertFalse(case["level1_executor_accepted"])
        self.assertTrue(case["level2_executor_accepted"])
        self.assertFalse(case["level1_reader_accepted"])
        self.assertTrue(
            case["level2_reader_without_execution_supports_accepted"]
        )
        self.assertFalse(case["content_hydrated"])
        self.assertEqual(
            self.fixture["allocation"]["cache_verification"],
            "complete-proof-projection-then-locked-now-before-epoch",
        )

    def test_level_one_input_in_l2_session_uses_bootstrap_routing(self) -> None:
        case = next(
            item
            for item in self.fixture["format_floor_cases"]
            if item["name"] == "l2_bootstrap_with_level_one_user_keeps_format_and_bootstrap_routing"
        )
        self.assertEqual(case["bootstrap_container_feature_level"], 2)
        self.assertEqual(case["activated_inbox_feature_levels"], [1])
        self.assertEqual(case["current_routing_requirements"], case["bootstrap_requirements"])
        self.assertEqual(
            case["expected_cache"],
            {
                "level": 2,
                "handler_version": "handler-h2",
                "required_capabilities": [
                    "tool:7a6d12a4fba729cddaedb154b126c4f1be55e7d25221f59cb5e3eb4a04fb8bde"
                ],
                "active_turn_id": None,
            },
        )
        self.assertFalse(case["content_hydrated"])

    def test_static_bound_and_compiled_actual_requirements(self) -> None:
        cases = {
            case["name"]: case for case in self.fixture["capability_bound_cases"]
        }
        self.assertEqual(
            set(cases),
            {
                "static_bound_allows_unused_candidate_without_precompile",
                "actual_exceeds_static_bound_fails_configuration",
            },
        )
        for case in cases.values():
            with self.subTest(case=case["name"]):
                bound = case["pre_admission_requirements"]
                actual = case["actual_turn_started_requirements"]
                bound_caps = set(bound["capabilities"])
                actual_caps = set(actual["capabilities"])
                self.sorted_unique(bound["capabilities"])
                self.sorted_unique(actual["capabilities"])
                self.assertEqual(actual["handler_version"], bound["handler_version"])
                self.assertGreaterEqual(actual["level"], bound["level"])
                relation = "subset" if actual_caps <= bound_caps else "exceeds"
                self.assertEqual(case["expected_capability_relation"], relation)

                # The static bound is derived without running compile or any of
                # compile's guardrail, instruction or context-provider effects.
                self.assertEqual(set(case["pre_admission_work"].values()), {0})
                self.assertEqual(case["turn_start_work"]["compile_invocations"], 1)
                self.assertEqual(
                    case["turn_start_work"]["guardrail_invocations"], 1
                )
                self.assertEqual(
                    case["turn_start_work"]["instruction_resolution_invocations"],
                    1,
                )
                self.assertEqual(
                    case["turn_start_work"]["context_provider_invocations"], 1
                )
                self.assertFalse(case["terminal_recorded"])
                self.assertFalse(case["input_bytes_mutated"])
                self.assertFalse(case["opaque_content_used_as_control"])

        success = cases["static_bound_allows_unused_candidate_without_precompile"]
        self.assertEqual(success["expected_action"], "route_after_turn_start")
        self.assertTrue(success["dispatch_started"])
        self.assertIsNone(success["bound_failure"])
        self.assertTrue(
            set(success["actual_turn_started_requirements"]["capabilities"])
            < set(success["pre_admission_requirements"]["capabilities"])
        )

        overflow = cases["actual_exceeds_static_bound_fails_configuration"]
        self.assertEqual(
            overflow["expected_action"],
            "fail_unsatisfiable_bound_configuration",
        )
        self.assertFalse(overflow["dispatch_started"])
        recovery = overflow["bound_failure"]
        self.assertTrue(recovery["configuration_error_exposed"])
        self.assertTrue(recovery["input_already_queued"])
        self.assertFalse(recovery["safe_discard_available"])
        self.assertTrue(recovery["requires_new_session"])
        self.assertFalse(recovery["replacement_input_published"])
        self.assertFalse(recovery["cancel_or_supersede_protocol_added"])
        self.assertFalse(recovery["automatic_retry_started"])
        self.assertTrue(
            set(overflow["actual_turn_started_requirements"]["capabilities"])
            - set(overflow["pre_admission_requirements"]["capabilities"])
        )


if __name__ == "__main__":
    unittest.main()
