from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "clients"))

import contract_snapshot  # noqa: E402
import contractctl  # noqa: E402
import record_adoption  # noqa: E402


class ContractRepositoryTests(unittest.TestCase):
    def test_cross_repository_checkout_keeps_contract_history(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")
        contract_checkout = workflow.split("- name: Checkout contract", maxsplit=1)[1].split(
            "- name: Checkout Python implementation", maxsplit=1
        )[0]

        self.assertIn("fetch-depth: 0", contract_checkout)

    def test_cross_repository_checkout_preserves_sibling_repository_names(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")
        python_checkout = workflow.split("- name: Checkout Python implementation", maxsplit=1)[1].split(
            "- name: Checkout Rust implementation", maxsplit=1
        )[0]
        rust_checkout = workflow.split("- name: Checkout Rust implementation", maxsplit=1)[1].split(
            "- name: Set up Python", maxsplit=1
        )[0]

        self.assertIn("path: vv-agent\n", python_checkout)
        self.assertIn("path: vv-agent-rs\n", rust_checkout)

    def test_cross_repository_gate_runs_bidirectional_sqlite_v2_probe(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")

        self.assertIn("Verify cross-language SQLite checkpoint v2", workflow)
        self.assertEqual(workflow.count("VV_AGENT_CROSS_RUNTIME_V2_MODE="), 4)
        for mode in ("write_python", "read_python", "write_rust", "read_rust"):
            self.assertIn(f"VV_AGENT_CROSS_RUNTIME_V2_MODE={mode}", workflow)

    def test_validate_workflow_supports_manual_dispatch(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:\n", workflow)

    def test_live_contract_validates(self) -> None:
        report = contractctl.validate_contract(ROOT)
        matrix = json.loads((ROOT / "support-matrix.json").read_text(encoding="utf-8"))

        self.assertEqual(report["version"], "0.6.0")
        self.assertEqual(report["domains"], 19)
        self.assertEqual(report["fixture_files"], 49)
        self.assertEqual(report["manifest_entries"], 48)
        self.assertEqual(report["adoption_status"], matrix["status"])

    def test_release_bundle_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_report = contractctl.build_bundle(ROOT, Path(first), revision="a" * 40)
            second_report = contractctl.build_bundle(ROOT, Path(second), revision="a" * 40)

            self.assertEqual(first_report["artifact_sha256"], second_report["artifact_sha256"])
            self.assertEqual(
                Path(first_report["artifact"]).read_bytes(),
                Path(second_report["artifact"]).read_bytes(),
            )
            metadata = json.loads(Path(first_report["release_metadata"]).read_text(encoding="utf-8"))
            self.assertEqual(metadata["contract_revision"], "a" * 40)
            self.assertEqual(metadata["artifact_sha256"], first_report["artifact_sha256"])

    def test_reasoning_history_fixture_locks_valid_assistant_projection(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures" / "assistant_reasoning_history_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(fixture["version"], 1)
        self.assertTrue(fixture["rules"]["non_empty_reasoning_is_resumable_history"])
        self.assertTrue(fixture["rules"]["fully_empty_assistant_turn_is_removed"])
        self.assertTrue(
            fixture["rules"][
                "openai_compatible_reasoning_only_content_is_explicit_empty_string"
            ]
        )
        cases = {case["name"]: case for case in fixture["cases"]}
        reasoning_only = cases["reasoning_only_assistant_is_preserved"]
        self.assertTrue(reasoning_only["expected"]["retain_in_resumable_history"])
        self.assertEqual(
            reasoning_only["expected"]["openai_compatible_projection"],
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "private reasoning chain",
            },
        )
        self.assertFalse(
            cases["fully_empty_assistant_is_removed"]["expected"]
            ["retain_in_resumable_history"]
        )
        self.assertEqual(
            fixture["runtime_case"]["expected"]
            ["next_model_request_visible_content"],
            "",
        )

    def test_manifest_detects_fixture_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixtures = Path(temporary) / "fixtures"
            shutil.copytree(ROOT / "fixtures", fixtures)
            path = fixtures / "model_ref_v1.json"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesRegex(contractctl.ContractError, "fixture digest mismatch"):
                contractctl.parse_manifest(fixtures)

    def test_token_usage_contract_preserves_zero_missing_and_unsupported(self) -> None:
        fixture = json.loads((ROOT / "fixtures/token_usage_v1.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case for case in fixture["normalization_cases"]}

        explicit_zero = cases["openai_cached_explicit_zero"]["expected"]["cache_usage"]
        missing = cases["provider_usage_without_cache_details"]["expected"]["cache_usage"]
        unsupported = cases["adapter_declares_cache_unsupported"]["expected"]["cache_usage"]
        invalid = cases["invalid_cache_numbers_are_not_zero"]["expected"]["cache_usage"]

        self.assertEqual(explicit_zero["status"], "provider_reported")
        self.assertEqual(explicit_zero["read_tokens"], 0)
        self.assertEqual(missing["status"], "accounting_missing")
        self.assertIsNone(missing["read_tokens"])
        self.assertEqual(unsupported["status"], "unsupported")
        self.assertIsNone(unsupported["read_tokens"])
        self.assertEqual(invalid, missing)

    def test_token_usage_aggregation_never_exposes_partial_total(self) -> None:
        fixture = json.loads((ROOT / "fixtures/token_usage_v1.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case for case in fixture["aggregation_cases"]}

        complete = cases["complete_provider_cache_observations"]["expected"]
        partial = cases["partial_observation_is_not_a_partial_total"]["expected"]

        self.assertEqual(complete["read_tokens"], 640)
        self.assertEqual(complete["uncached_input_tokens"], 1360)
        self.assertEqual(partial["status"], "accounting_missing")
        self.assertIsNone(partial["read_tokens"])
        self.assertIsNone(partial["uncached_input_tokens"])

    def test_public_api_inventories_token_usage_types(self) -> None:
        fixture = json.loads((ROOT / "fixtures/public_api_v1.json").read_text(encoding="utf-8"))
        capabilities = {
            item["id"]
            for domain in fixture["domains"]
            for item in domain["capabilities"]
        }
        self.assertTrue(
            {
                "result.usage_source",
                "result.cache_usage_status",
                "result.cache_usage",
                "result.token_usage",
                "result.task_token_usage",
            }.issubset(capabilities)
        )

    def test_after_cycle_contract_is_closed_task_neutral_and_non_success_only(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/after_cycle_hook_v1.json").read_text(encoding="utf-8")
        )

        self.assertEqual(fixture["schema_version"], "vv-agent.after-cycle-hook.v1")
        self.assertEqual(
            fixture["decision"]["action_values"],
            ["continue", "steer", "stop_non_success"],
        )
        self.assertTrue(
            fixture["decision"]["rules"]["completed_status_cannot_be_returned_by_hook"]
        )
        self.assertTrue(
            fixture["decision"]["rules"]["permission_expansion_fields_do_not_exist"]
        )
        self.assertEqual(
            fixture["permission_state"]["reserved_shared_state_key"],
            "_vv_agent_after_cycle_control",
        )
        self.assertTrue(fixture["distributed"]["resolved_before_claim"])
        self.assertFalse(
            set(fixture["snapshot"]["task_domain_fields_forbidden"])
            & set(fixture["snapshot"]["required_fields"])
        )
        cases = {case["name"]: case for case in fixture["runner_cases"]}
        self.assertEqual(cases["stop_cannot_be_projected_as_success"]["expected"]["status"], "failed")
        self.assertEqual(
            cases["steer_at_max_cycles_fails_closed"]["expected"]["error_code"],
            "after_cycle_steer_unavailable",
        )
        self.assertEqual(
            fixture["decision"]["error_codes"]["control_state_invalid"],
            "after_cycle_control_state_invalid",
        )
        invalid = {case["name"]: case for case in fixture["invalid_decisions"]}
        self.assertIn("permission_expansion_field", invalid)
        self.assertTrue(
            all(case["error_code"] == "after_cycle_decision_invalid" for case in invalid.values())
        )

    def test_run_budget_contract_locks_bounds_dimensions_and_defaults(self) -> None:
        fixture = json.loads((ROOT / "fixtures/run_budget_v1.json").read_text(encoding="utf-8"))

        self.assertEqual(fixture["integer_bounds"], {"minimum": 0, "maximum": (1 << 53) - 1})
        self.assertEqual(fixture["defaults"]["unavailable_metric_policy"], "continue_and_mark")
        self.assertTrue(fixture["defaults"]["empty_limits_are_unlimited"])
        self.assertEqual(
            fixture["dimension_precedence"],
            [
                "wall_time",
                "total_tokens",
                "uncached_input_tokens",
                "host_cost",
                "tool_calls",
                "tool_calls_by_name",
            ],
        )
        self.assertEqual(
            fixture["enums"]["unavailable_metric_policies"],
            ["continue_and_mark", "stop"],
        )
        self.assertIn("integer_overflow", fixture["enums"]["unavailable_reasons"])
        overflow = next(
            case for case in fixture["evaluator_cases"] if case["name"] == "token_sum_wire_overflow_is_typed_unavailable"
        )
        self.assertEqual(overflow["expected"]["unavailable_reason"], "integer_overflow")
        self.assertIsNone(overflow["expected"]["total_tokens"])

    def test_run_budget_runner_cases_are_executable_inputs_not_boolean_claims(self) -> None:
        fixture = json.loads((ROOT / "fixtures/run_budget_v1.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case for case in fixture["runner_cases"]}

        required = {
            "no_limits_preserve_legacy_terminal",
            "total_tokens_equal_limit_can_finish",
            "total_tokens_atomic_overshoot",
            "token_limit_reached_blocks_next_llm",
            "uncached_usage_missing_continues_and_marks",
            "uncached_usage_missing_strict_stops",
            "uncached_explicit_zero_is_available",
            "tool_batch_total_preflight_is_all_or_none",
            "named_tool_preflight_matches_exact_name",
            "zero_wall_time_stops_before_llm",
            "host_cost_atomic_overshoot",
            "host_cost_unit_mismatch_strict_stops",
            "pre_cancelled_run_precedes_zero_budget",
        }
        self.assertEqual(set(cases), required)
        for case in cases.values():
            self.assertIn("limits", case)
            self.assertIn("steps", case)
            self.assertIn("expected", case)
            self.assertIn("status", case["expected"])
            self.assertIn("completion_reason", case["expected"])

        batch = cases["tool_batch_total_preflight_is_all_or_none"]
        self.assertEqual(len(batch["steps"][0]["tool_calls"]), 2)
        self.assertEqual(batch["expected"]["tool_execution_count"], 0)
        self.assertEqual(batch["expected"]["budget_exhaustion"]["attempted_increment"], 2)
        self.assertEqual(cases["uncached_explicit_zero_is_available"]["expected"]["uncached_input_tokens"], 0)

    def test_budget_events_lock_snapshot_exhaustion_and_terminal_order(self) -> None:
        records = [
            json.loads(line)
            for line in (ROOT / "fixtures/budget_events_v1.jsonl").read_text(encoding="utf-8").splitlines()
        ]

        self.assertEqual(
            [record["type"] for record in records],
            ["budget_snapshot", "budget_exhausted", "run_failed", "run_completed"],
        )
        exhaustion = records[1]["budget_exhaustion"]
        self.assertEqual(exhaustion["reason"], "limit_exceeded")
        self.assertEqual(exhaustion["overshoot"], 2)
        self.assertEqual(records[2]["completion_reason"], "budget_exhausted")
        self.assertEqual(records[2]["budget_usage"], records[1]["budget_usage"])

    def test_distributed_contract_carries_limits_meter_reference_and_budget_state(self) -> None:
        envelope = json.loads(
            (ROOT / "fixtures/distributed_run_envelope_v1.json").read_text(encoding="utf-8")
        )["canonical_envelope"]
        checkpoint = json.loads((ROOT / "fixtures/checkpoint_codec_v1.json").read_text(encoding="utf-8"))

        self.assertEqual(envelope["budget_limits"]["max_total_tokens"], 5000)
        self.assertEqual(
            envelope["recipe"]["capabilities"]["host_cost_meter_ref"],
            {"id": "cost.tenant-run", "version": "1"},
        )
        running = next(case for case in checkpoint["valid_cases"] if case["name"] == "running_with_budget_state")
        self.assertEqual(running["payload"]["budget_usage"]["elapsed_ms"], 50)

    def test_completion_policy_is_task_agnostic_and_backward_compatible(self) -> None:
        fixture = json.loads((ROOT / "fixtures/completion_policy_v1.json").read_text(encoding="utf-8"))

        self.assertEqual(fixture["policy_values"], ["continue", "wait_user", "finish"])
        self.assertEqual(fixture["framework_default"], "continue")
        self.assertEqual(
            fixture["precedence"],
            ["run_config", "runner_default_run_config", "agent", "framework_default"],
        )
        self.assertTrue(fixture["rules"]["assistant_text_is_not_classified"])
        self.assertTrue(fixture["rules"]["completion_policy_does_not_change_tool_availability"])
        self.assertTrue(fixture["rules"]["budget_exhausted_is_defined_by_run_budget_v1"])
        self.assertTrue(fixture["rules"]["approval_resume_uses_fresh_cycle_budget"])
        self.assertTrue(fixture["rules"]["approval_resume_preserves_resource_budget"])
        self.assertTrue(fixture["rules"]["approved_resume_rejects_input_before_claim"])
        self.assertTrue(fixture["rules"]["pre_cancelled_approval_resume_skips_side_effects"])
        self.assertTrue(fixture["rules"]["guardrail_allow_preserves_completion_observation"])
        self.assertTrue(fixture["rules"]["ordinary_llm_failure_is_typed_terminal"])

    def test_distributed_lease_lifecycle_closes_side_effect_windows(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/distributed_run_envelope_v1.json").read_text(encoding="utf-8")
        )
        lifecycle = fixture["lease_lifecycle"]
        rules = lifecycle["rules"]

        self.assertTrue(rules["initial_expiry_capped_by_deadline"])
        self.assertTrue(rules["renewed_expiry_capped_by_deadline"])
        self.assertTrue(rules["initial_renewal_required_before_cycle"])
        self.assertFalse(rules["initial_renewal_failure_starts_cycle"])
        self.assertTrue(rules["heartbeat_active_through_commit"])
        self.assertTrue(rules["operation_unwind_stops_heartbeat"])
        self.assertFalse(rules["expired_owner_can_renew"])
        self.assertTrue(rules["expired_claim_can_be_reclaimed"])
        self.assertTrue(rules["heartbeat_interval_less_than_positive_lease"])
        self.assertTrue(rules["successful_commit_precedes_concurrent_renewal_error"])

        expiry_cases = {case["name"]: case for case in lifecycle["expiry_cases"]}
        self.assertEqual(
            expiry_cases["deadline_clamps_before_u64_addition"]["expected_expiry_ms"],
            1050,
        )
        self.assertEqual(
            expiry_cases["unbounded_u64_addition_overflows"]["expected_error"],
            "checkpoint lease overflow",
        )
        self.assertEqual(lifecycle["interval_lease_ms_cases"][0], 1)
        self.assertEqual(lifecycle["interval_lease_ms_cases"][-1], (1 << 64) - 1)

        worker_cases = {case["name"]: case for case in lifecycle["worker_cases"]}
        self.assertEqual(
            worker_cases["initial_renewal_precedes_operation"]["expected"]["event_order"],
            ["claim", "renew", "operation_start", "commit", "heartbeat_stop"],
        )
        self.assertEqual(
            worker_cases["initial_renewal_failure_has_no_side_effects"]["expected"]["model_calls"],
            0,
        )
        self.assertGreaterEqual(
            worker_cases["commit_barrier_keeps_heartbeat_active"]["expected"][
                "periodic_renewals_during_commit_min"
            ],
            1,
        )
        self.assertTrue(
            worker_cases["successful_commit_beats_inflight_renewal_rejection"]["expected"][
                "heartbeat_error_suppressed"
            ]
        )

    def test_completion_closure_locks_resume_guardrail_and_llm_failure(self) -> None:
        fixture = json.loads((ROOT / "fixtures/completion_policy_v1.json").read_text(encoding="utf-8"))
        resume = fixture["approval_resume"]
        cases = {case["name"]: case for case in resume["cases"]}

        self.assertEqual(resume["rules"]["run_identity"], "fresh")
        self.assertEqual(resume["rules"]["trace_id_relation"], "same_as_source")
        self.assertEqual(resume["rules"]["cycle_budget"], "full_configured_max_cycles")
        self.assertFalse(resume["rules"]["prior_interrupted_cycles_reduce_resume_budget"])
        self.assertEqual(resume["rules"]["new_input"], "reject_before_claim")
        self.assertEqual(
            resume["rules"]["admission_precedence"],
            ["reject_new_input", "observe_cancellation", "claim_approval"],
        )
        self.assertEqual(
            resume["rules"]["pre_cancelled_forbidden_actions"],
            ["claim_approval", "execute_tool", "run_output_guardrail"],
        )
        self.assertFalse(
            cases["approved_resume_rejects_input_before_claim"]["expected"]["approval_claim_consumed"]
        )
        self.assertEqual(
            cases["pre_cancelled_approved_resume_with_input_rejects_before_cancellation"]["expected"][
                "terminal_count"
            ],
            0,
        )
        self.assertEqual(
            cases["pre_cancelled_approved_resume_has_no_side_effects"]["expected"]["terminal_event"],
            "run_cancelled",
        )
        self.assertEqual(
            fixture["output_guardrail_allow"]["preserved_fields"],
            ["status", "completion_reason", "completion_tool_name", "partial_output"],
        )
        self.assertEqual(
            fixture["output_guardrail_allow"]["case"]["expected_output"],
            "Redacted question",
        )
        self.assertEqual(fixture["ordinary_llm_failure"]["runner_outcome"], "typed_result")
        self.assertEqual(fixture["ordinary_llm_failure"]["terminal_count"], 1)

    def test_completion_cases_cover_every_current_terminal_reason(self) -> None:
        fixture = json.loads((ROOT / "fixtures/completion_policy_v1.json").read_text(encoding="utf-8"))
        case_reasons = {case["expected"]["completion_reason"] for case in fixture["cases"]}
        precedence_reasons = {case["expected_reason"] for case in fixture["terminal_precedence_cases"]}

        self.assertTrue(
            {
                "tool_finish",
                "no_tool_finish",
                "stop_on_first_tool",
                "stop_at_tool_name",
                "wait_user",
                "max_cycles",
                "cancelled",
                "failed",
            }.issubset(case_reasons | precedence_reasons)
        )
        budget_fixture = json.loads((ROOT / "fixtures/run_budget_v1.json").read_text(encoding="utf-8"))
        budget_reasons = {case["expected"]["completion_reason"] for case in budget_fixture["runner_cases"]}
        self.assertIn("budget_exhausted", budget_reasons)

    def test_public_api_inventories_completion_controls_and_observation(self) -> None:
        fixture = json.loads((ROOT / "fixtures/public_api_v1.json").read_text(encoding="utf-8"))
        capabilities = {
            item["id"]
            for domain in fixture["domains"]
            for item in domain["capabilities"]
        }

        self.assertTrue(
            {
                "agent.no_tool_policy",
                "run_config.no_tool_policy",
                "result.completion_reason",
            }.issubset(capabilities)
        )
        self.assertEqual(len(capabilities), 147)
        self.assertIn("checkpoint_config.capability_refs", capabilities)
        self.assertIn("checkpoint_config.credential_slots", capabilities)

        surfaces = {surface["id"]: surface for surface in fixture["surfaces"]}
        surface_member_count = sum(
            len(surface.get("members", []))
            + len(surface.get("protocol_operations", []))
            + len(surface.get("supporting_operations", []))
            for surface in fixture["surfaces"]
        )
        self.assertEqual(surface_member_count, 229)
        self.assertIn("no_tool_policy", {member["id"] for member in surfaces["agent"]["members"]})
        self.assertIn("no_tool_policy", {member["id"] for member in surfaces["run_config"]["members"]})
        self.assertTrue(
            {"completion_reason", "completion_tool_name", "partial_output"}.issubset(
                {member["id"] for member in surfaces["run_result"]["members"]}
            )
        )
        self.assertTrue(
            {"budget_limits", "host_cost_meter"}.issubset(
                {member["id"] for member in surfaces["run_config"]["members"]}
            )
        )
        self.assertIn(
            "after_cycle_hooks",
            {member["id"] for member in surfaces["run_config"]["members"]},
        )
        self.assertTrue(
            {"budget_usage", "budget_exhaustion"}.issubset(
                {member["id"] for member in surfaces["run_result"]["members"]}
            )
        )
        self.assertEqual([member["id"] for member in surfaces["host_cost_meter"]["members"]], ["read"])

    def test_manager_outcomes_preserve_completion_observation(self) -> None:
        fixture = json.loads((ROOT / "fixtures/manager_tool_envelope_v1.json").read_text(encoding="utf-8"))

        failed = fixture["sync_failed_outcome"]["expected"]
        self.assertEqual(failed["completion_reason"], "failed")
        self.assertEqual(failed["partial_output"], "last child draft")

        waiting = fixture["sync_wait_outcome"]["expected"]
        self.assertEqual(waiting["completion_reason"], "wait_user")
        self.assertEqual(waiting["completion_tool_name"], "dangerous")
        self.assertEqual(waiting["partial_output"], "proposed change")
        self.assertEqual(waiting["error_code"], "sub_task_wait_user")
        self.assertIsNone(fixture["sync_wait_outcome"]["internal_error_code"])
        self.assertEqual(fixture["sync_wait_outcome"]["manager_status_error_code_field"], "omitted")
        self.assertEqual(fixture["sync_wait_outcome"]["sub_run_event_error_code_field"], "omitted")
        self.assertEqual(fixture["sync_wait_outcome"]["sync_single_tool_envelope_error_code"], "sub_task_wait_user")

    def test_completion_event_and_app_server_closure_is_explicit(self) -> None:
        invalid = json.loads((ROOT / "fixtures/run_events_v1_invalid.json").read_text(encoding="utf-8"))
        rejected = {case["id"] for case in invalid["reject"]}
        self.assertTrue(
            {
                "unknown_completion_reason",
                "completion_reason_is_not_a_string_or_null",
                "completion_tool_name_is_not_a_string_or_null",
                "partial_output_is_not_a_string_or_null",
                "budget_usage_is_not_an_object_or_null",
                "budget_exhaustion_unknown_dimension",
            }.issubset(rejected)
        )

        app_server = json.loads(
            (ROOT / "fixtures/app_server_observable_v1.json").read_text(encoding="utf-8")
        )
        projections = {
            case["name"]: case for case in app_server["terminal"]["agentStatusProjection"]
        }
        self.assertEqual(projections["wait_user_is_interrupted_without_error"]["turnStatus"], "interrupted")
        self.assertEqual(projections["wait_user_is_interrupted_without_error"]["errorField"], "omitted")
        self.assertEqual(projections["cancelled_failure_stays_failed"]["turnStatus"], "failed")
        budget = projections["budget_exhaustion_is_failed_with_typed_observation"]
        self.assertEqual(budget["turnStatus"], "failed")
        self.assertEqual(budget["completionReason"], "budget_exhausted")
        self.assertEqual(budget["budgetUsageField"], "present")

    def test_public_api_properties_include_canonical_signatures(self) -> None:
        fixture = json.loads((ROOT / "fixtures/public_api_v1.json").read_text(encoding="utf-8"))

        properties = [
            member["python"]
            for surface in fixture["surfaces"]
            for group in ("members", "protocol_operations", "supporting_operations")
            for member in surface.get(group, [])
            if member["python"]["kind"] == "property"
        ]
        self.assertTrue(properties)
        self.assertTrue(all("signature" in property_member for property_member in properties))

    def test_checkpoint_config_uses_real_keys_and_explicit_stores(self) -> None:
        fixture = json.loads((ROOT / "fixtures/checkpoint_config_v1.json").read_text(encoding="utf-8"))
        invalid = {case["name"]: case["config"] for case in fixture["invalid_cases"]}
        valid = {case["name"]: case["config"] for case in fixture["valid_cases"]}

        self.assertEqual(len(invalid["key_too_large"]["key"].encode("utf-8")), 513)
        self.assertNotIn("key_utf8_bytes", invalid["key_too_large"])
        self.assertEqual(valid["generated_new_key"]["store"], {"kind": "in_memory"})
        self.assertEqual(
            valid["require_existing_distributed"]["store_ref"],
            {"id": "checkpoint.tenant", "version": "1"},
        )
        self.assertTrue(fixture["store_selection"]["exactly_one_required_when_enabled"])
        self.assertTrue(all(case.get("error_code") for case in fixture["invalid_cases"]))
        self.assertEqual(fixture["defaults"]["capability_refs"], {})
        self.assertEqual(fixture["defaults"]["credential_slots"], [])
        self.assertEqual(
            valid["named_new_key"]["capability_refs"]["reconciliation_provider"],
            {"id": "reconcile.local", "version": "1"},
        )
        self.assertEqual(
            valid["named_new_key"]["credential_slots"],
            [
                "/model/settings/extra_body/api_key",
                "/model/settings/extra_headers/authorization",
            ],
        )
        self.assertEqual(
            {
                case["error_code"]
                for case in fixture["invalid_cases"]
                if case["name"].startswith("credential_slot")
            },
            {"checkpoint_credential_slots_invalid"},
        )
        attempts = fixture["resume_attempt_rules"]
        self.assertEqual(attempts["successful_recovery_claim"], "previous_plus_one")
        self.assertEqual(attempts["terminal_replay"], "unchanged")
        runner_cases = {case["name"]: case for case in fixture["runner_cases"]}
        self.assertEqual(
            runner_cases["definition_mismatch_fails_before_operations"]["expected"][
                "resume_attempt"
            ],
            2,
        )
        self.assertFalse(fixture["run_scope"]["agent_as_tool_child_inherits_parent_checkpoint_config"])
        self.assertEqual(
            fixture["run_scope"]["handoff_error_code"],
            "checkpoint_handoff_unsupported",
        )
        self.assertEqual(
            runner_cases["local_reconciliation_provider_requires_explicit_stable_ref"][
                "expected"
            ]["failure_code"],
            "checkpoint_definition_unstable",
        )

    def test_run_definition_has_rfc8785_golden_bytes_and_digests(self) -> None:
        fixture = json.loads((ROOT / "fixtures/run_definition_v1.json").read_text(encoding="utf-8"))

        self.assertEqual(
            fixture["canonicalization"]["algorithm"],
            "RFC 8785 JSON Canonicalization Scheme",
        )
        self.assertEqual(len(fixture["golden_cases"]), 2)
        for case in fixture["golden_cases"]:
            canonical = base64.b64decode(case["canonical_json_base64"], validate=True)
            self.assertEqual(len(canonical), case["canonical_json_utf8_bytes"])
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), case["sha256"])
            self.assertEqual(json.loads(canonical), case["definition"])
        full = fixture["golden_cases"][1]["definition"]
        full_canonical = base64.b64decode(
            fixture["golden_cases"][1]["canonical_json_base64"],
            validate=True,
        )
        ordinary_sorted_json = json.dumps(
            full,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertNotEqual(full_canonical, ordinary_sorted_json)
        for expected_number in (
            b'"temperature":1',
            b'"top_p":1e-7',
            b'"backoff_seconds":0.000001',
            b'"negative_zero":0',
            b'"large_number":100000000000000000000',
        ):
            self.assertIn(expected_number, full_canonical)
        self.assertEqual(full["root_input"], "核对 café 订单 42。")
        headers = full["model"]["settings"]["extra_headers"]
        self.assertEqual(headers["authorization"], "<credential-redacted>")
        self.assertEqual(headers["x-feature"], "reasoning-v2")
        self.assertEqual(full["credential_slots"], sorted(full["credential_slots"]))
        self.assertEqual(len(full["credential_slots"]), len(set(full["credential_slots"])))
        for pointer in full["credential_slots"]:
            value = full
            for token in pointer.removeprefix("/").split("/"):
                value = value[token.replace("~1", "/").replace("~0", "~")]
            self.assertEqual(value, "<credential-redacted>")
        self.assertEqual(
            [tool["schema"]["function"]["name"] for tool in full["tools"]],
            ["write_record", "read_record"],
        )
        self.assertEqual(full["tool_policy"]["allowed_tools"], ["read_record", "write_record"])
        self.assertTrue(
            all(field in fixture["golden_cases"][0]["definition"] for field in fixture["required_fields"])
        )
        self.assertTrue(fixture["top_level_field_policy"]["closed"])
        for case in fixture["golden_cases"]:
            self.assertEqual(set(case["definition"]), set(fixture["required_fields"]))
        digest_relations = {
            case["expected_digest_relation"]
            for case in fixture["producer_cases"]
            if "expected_digest_relation" in case
        }
        self.assertEqual(digest_relations, {"equal", "different"})
        producer_cases = {case["name"]: case for case in fixture["producer_cases"]}
        utf16 = producer_cases["credential_slots_use_utf16_code_unit_order"]["generated_input"]
        self.assertEqual(
            utf16["expected_sorted"],
            sorted(utf16["unsorted"], key=lambda value: value.encode("utf-16-be")),
        )
        invalid_codes = {case["error_code"] for case in fixture["invalid_cases"]}
        self.assertTrue(
            {
                "checkpoint_definition_header_collision",
                "checkpoint_definition_invalid",
                "checkpoint_definition_unstable",
            }.issubset(invalid_codes)
        )
        self.assertTrue(all(case.get("error_code") for case in fixture["invalid_cases"]))

    def test_rfc8785_vectors_match_ecmascript_reference_serialization(self) -> None:
        subprocess.run(
            ["node", str(ROOT / "scripts/verify_jcs.mjs")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_checkpoint_v2_discriminator_extensions_and_migration_are_explicit(self) -> None:
        fixture = json.loads((ROOT / "fixtures/checkpoint_codec_v2.json").read_text(encoding="utf-8"))
        canonical = fixture["canonical_checkpoint"]
        migrations = {case["name"]: case for case in fixture["migration_cases"]}
        run_definition_fixture = json.loads(
            (ROOT / "fixtures/run_definition_v1.json").read_text(encoding="utf-8")
        )
        minimal_definition = run_definition_fixture["golden_cases"][0]

        self.assertEqual(canonical["schema_version"], "vv-agent.checkpoint.v2")
        self.assertEqual(canonical["run_definition_schema"], "vv-agent.run-definition.v1")
        self.assertEqual(canonical["run_definition"], minimal_definition["definition"])
        self.assertEqual(canonical["run_definition_digest"], minimal_definition["sha256"])
        self.assertEqual(canonical["claimed_cycle"], canonical["cycle_index"] + 1)
        self.assertEqual(len(canonical["run_definition_digest"]), 64)
        self.assertTrue(fixture["discriminator"]["v1_when_field_absent"])
        self.assertEqual(
            fixture["discriminator"]["unknown_present_value_error"],
            "checkpoint_schema_unsupported",
        )
        self.assertFalse(migrations["running_v1_requires_reconciliation"]["expected"]["allowed"])
        self.assertEqual(
            migrations["running_v1_requires_reconciliation"]["expected"]["status"],
            "reconciliation_required",
        )
        self.assertEqual(fixture["unknown_field_policy"]["extension_required"], "block_resume")
        valid_cases = {case["name"]: case["payload"] for case in fixture["valid_cases"]}
        for payload in valid_cases.values():
            self.assertEqual(payload["run_definition"], minimal_definition["definition"])
            self.assertEqual(payload["run_definition_digest"], minimal_definition["sha256"])
        self.assertTrue(
            all(
                "run_definition" in case["payload"]
                for case in fixture["invalid_cases"]
                if case["name"] != "unknown_schema"
            )
        )
        suspended = valid_cases["reconciliation_required_retains_ambiguous_journal"]
        self.assertIsNone(suspended["claim_token"])
        self.assertEqual(suspended["tool_journal"][0]["state"], "ambiguous")
        self.assertTrue(fixture["status_rules"]["reconciliation_required_requires_ambiguous_journal"])
        self.assertEqual(
            {case["error_code"] for case in fixture["status_cases"] if "error_code" in case},
            {"checkpoint_status_invalid"},
        )
        abort_case = next(
            case
            for case in fixture["status_cases"]
            if case["name"] == "operator_abort_terminal_preserves_unknown_outcome"
        )
        self.assertTrue(abort_case["expected"]["ambiguous_journal_preserved"])
        self.assertTrue(fixture["run_definition_rules"]["embedded_credential_redacted_definition_required"])
        self.assertEqual(
            {
                case.get("error_code")
                for case in fixture["run_definition_cases"]
                if not case.get("valid")
            },
            {"checkpoint_definition_invalid", "checkpoint_definition_mismatch"},
        )
        definition_schema_cases = fixture["run_definition_schema_cases"]
        self.assertEqual(
            {case["expected_error_code"] for case in definition_schema_cases},
            {"checkpoint_definition_schema_unsupported"},
        )
        for case in definition_schema_cases:
            self.assertEqual(
                case["expected"],
                {
                    "capability_resolution_count": 0,
                    "claim_count": 0,
                    "model_calls": 0,
                    "tool_calls": 0,
                },
            )
        migration_050 = migrations["checkpoint_0_5_0_v2_requires_explicit_definition_migration"]
        self.assertFalse(migration_050["automatic_resume"]["allowed"])
        source_050 = migration_050["source_payload"]
        self.assertNotIn("run_definition_schema", source_050)
        self.assertNotIn("run_definition", source_050)
        self.assertEqual(source_050["run_definition_digest"], "c" * 64)
        self.assertFalse(
            migration_050["explicit_host_migration"]["implicit_guess_of_0_5_0_digest_algorithm"]
        )
        self.assertEqual(
            migration_050["explicit_host_migration"]["target_run_definition_digest"],
            "a630a668985d2157f7f8570a1871b320a1df229d40807d019682a0caf3bda1b3",
        )
        self.assertEqual(
            migration_050["explicit_host_migration"]["atomic_fields"],
            [
                "run_definition_schema",
                "run_definition",
                "run_definition_digest",
                "revision",
            ],
        )
        for name in ("absent_discriminator_reads_v1", "terminal_v1_explicit_migration"):
            terminal = migrations[name]["source"]["terminal_result"]
            self.assertNotIn("checkpoint_key", terminal)
            self.assertNotIn("resume_observation", terminal)
        limits = fixture["extension_limits"]
        generated = {case["name"]: case for case in limits["generated_boundary_cases"]}
        complex_vector = limits["canonicalization_vectors"][0]
        complex_canonical = base64.b64decode(
            complex_vector["canonical_json_base64"],
            validate=True,
        )
        self.assertEqual(len(complex_canonical), complex_vector["canonical_json_utf8_bytes"])
        self.assertEqual(hashlib.sha256(complex_canonical).hexdigest(), complex_vector["sha256"])
        self.assertNotEqual(
            complex_canonical,
            json.dumps(
                complex_vector["entry"],
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8"),
        )

        def entry_bytes(state: str, *, version: str = "1", required: bool = False) -> int:
            entry = {"version": version, "required": required, "state": state}
            return len(
                json.dumps(
                    entry,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )

        for name in ("entry_exact_limit", "entry_over_limit"):
            case = generated[name]
            generation = case["entry_generation"]
            size = entry_bytes(
                generation["state_character"] * generation["state_utf8_repetitions"],
                version=generation["version"],
                required=generation["required"],
            )
            self.assertEqual(size, case["canonical_entry_utf8_bytes"])

        utf8_case = generated["entry_exact_limit_utf8"]
        utf8_generation = utf8_case["entry_generation"]
        utf8_state = "".join(
            segment["character"] * segment["repetitions"]
            for segment in utf8_generation["state_segments"]
        )
        self.assertEqual(len(utf8_state.encode("utf-8")), utf8_case["state_utf8_bytes"])
        self.assertEqual(entry_bytes(utf8_state), utf8_case["canonical_entry_utf8_bytes"])

        for name, expected_total in (("total_exact_limit", 262144), ("total_over_limit", 262145)):
            case = generated[name]
            generation = case["entries_generation"]
            sizes = [
                entry_bytes(
                    generation["state_character"] * repetitions,
                    version=generation["version"],
                    required=generation["required"],
                )
                for repetitions in generation["state_utf8_repetitions"]
            ]
            self.assertEqual(sizes, case["canonical_entry_utf8_bytes"])
            self.assertTrue(all(size <= limits["entry_max_utf8_bytes"] for size in sizes))
            self.assertEqual(sum(sizes), expected_total)
            self.assertEqual(case["canonical_total_entries_utf8_bytes"], expected_total)

    def test_operation_journal_never_silently_retries_unknown_effects(self) -> None:
        fixture = json.loads((ROOT / "fixtures/operation_journal_v1.json").read_text(encoding="utf-8"))
        recovery = {case["name"]: case for case in fixture["recovery_cases"]}
        request_vectors = {
            case["name"]: case for case in fixture["request_digest"]["golden_cases"]
        }

        self.assertEqual(
            fixture["enums"]["states"],
            ["planned", "started", "succeeded", "failed", "ambiguous"],
        )
        self.assertEqual(
            recovery["started_unknown_tool_is_not_retried"]["expected"]["status"],
            "reconciliation_required",
        )
        self.assertEqual(
            recovery["started_unknown_tool_is_not_retried"]["expected"]["tool_calls"],
            0,
        )
        self.assertTrue(
            recovery["started_supported_tool_retries_same_key"]["expected"]["same_idempotency_key"]
        )
        self.assertEqual(
            recovery["started_supported_tool_retries_same_key"]["expected"]["attempt"],
            2,
        )
        valid_entries = {case["name"]: case for case in fixture["valid_entries"]}
        for case in valid_entries.values():
            vector_name = case["request_golden_case"]
            self.assertEqual(case["entry"]["request_digest"], request_vectors[vector_name]["sha256"])
        self.assertIn(["planned", "failed"], fixture["transition_rules"]["allowed"])
        self.assertEqual(
            fixture["outcome_classification"]["timeout_after_started"],
            "ambiguous_unless_the_adapter_proves_a_definitive_outcome",
        )
        self.assertFalse(
            recovery["blocking_tool_timeout_after_started_is_ambiguous"]["expected"][
                "tool_process_assumed_stopped"
            ]
        )
        digest_mismatch = recovery["request_digest_mismatch_never_replays"]["expected"]
        self.assertEqual(digest_mismatch["failure_code"], "checkpoint_journal_integrity_mismatch")
        self.assertEqual(digest_mismatch["claim_count"], 0)
        self.assertFalse(digest_mismatch["checkpoint_mutated"])
        abort = next(
            case
            for case in fixture["reconciliation_cases"]
            if case["name"] == "abort_is_explicit_terminal_failure"
        )["expected"]
        self.assertEqual(abort["state"], "ambiguous")
        self.assertTrue(abort["ambiguity_preserved"])
        self.assertTrue(
            fixture["pre_start_rules"][
                "approval_resume_uses_source_tool_call_id_request_digest_and_idempotency_key"
            ]
        )
        self.assertFalse(fixture["tool_context"]["model_visible_argument"])
        self.assertTrue(all(case.get("error_code") for case in fixture["invalid_entries"]))

    def test_checkpoint_store_progress_and_terminal_retention_are_locked(self) -> None:
        fixture = json.loads((ROOT / "fixtures/checkpoint_store_v2.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case for case in fixture["store_cases"]}

        self.assertTrue(fixture["revision_rules"]["progress_preserves_claim"])
        self.assertFalse(fixture["revision_rules"]["heartbeat_requires_revision"])
        self.assertEqual(cases["progress_keeps_claim"]["expected"]["claim_token"], "owner-b")
        self.assertEqual(
            cases["heartbeat_after_progress_updates_lease_only"]["expected"]["journal_state"],
            "started",
        )
        self.assertTrue(cases["terminal_ack_is_retained"]["expected"]["row_present"])
        self.assertTrue(fixture["redis_rules"]["whole_json_heartbeat_forbidden"])
        self.assertEqual(fixture["namespaces"]["v1_redis_prefix"], "vv_agent:checkpoint:")
        self.assertEqual(cases["claim_next_cycle"]["expected"]["resume_attempt"], 1)
        self.assertEqual(cases["expired_claim_can_be_reclaimed"]["expected"]["resume_attempt"], 2)
        self.assertEqual(
            cases["live_claim_cannot_be_stolen"]["expected"]["resume_attempt"],
            1,
        )
        self.assertEqual(
            cases["terminal_replay_does_not_claim_or_increment_resume_attempt"]["expected"][
                "resume_attempt"
            ],
            2,
        )
        suspended = cases["reconciliation_suspend_preserves_journal_and_releases_claim"][
            "expected"
        ]
        self.assertEqual(suspended["status"], "reconciliation_required")
        self.assertIsNone(suspended["claim_token"])
        self.assertEqual(suspended["tool_journal_state"], "ambiguous")
        self.assertEqual(
            cases["claim_suspended_reconciliation_for_resolution"]["expected"][
                "resume_attempt"
            ],
            3,
        )
        concurrent_claim = cases["concurrent_recovery_claims_increment_once"]["expected"]
        self.assertEqual(concurrent_claim["success_count"], 1)
        self.assertEqual(concurrent_claim["resume_attempt"], 2)
        operator_abort = cases["operator_abort_terminal_retains_unknown_outcome"]["expected"]
        self.assertEqual(operator_abort["tool_journal_state"], "ambiguous")
        self.assertTrue(operator_abort["resume_observation_present"])
        claimed_failure = cases["definitive_failure_finalizes_active_claim"]["expected"]
        self.assertIsNone(claimed_failure["claim_token"])
        self.assertEqual(claimed_failure["model_journal_count"], 0)
        claimed_abort = cases["claimed_operator_abort_retains_unknown_outcome"]["expected"]
        self.assertEqual(claimed_abort["tool_journal_state"], "ambiguous")
        running_delivery = cases["running_outbox_delivery_preserves_claim"]["expected"]
        self.assertEqual(running_delivery["claim_token"], "owner-events")
        terminal_delivery = cases["terminal_outbox_delivery_preserves_receipt"]["expected"]
        self.assertTrue(terminal_delivery["terminal_result_present"])
        self.assertEqual(terminal_delivery["outbox_state"], "delivered")
        for vector in fixture["redis_key_vectors"]:
            digest = hashlib.sha256(vector["checkpoint_key"].encode("utf-8")).hexdigest()
            self.assertEqual(digest, vector["checkpoint_key_utf8_sha256"])
            self.assertEqual(vector["v2_data_key"], f"vv-agent:checkpoint:v2:{digest}")
            self.assertEqual(vector["v2_lease_key"], f"{vector['v2_data_key']}:lease")
            self.assertNotEqual(vector["v1_data_key"], vector["v2_data_key"])
        event_vector = fixture["event_payload_digest"]["golden_cases"][0]
        event_bytes = base64.b64decode(event_vector["canonical_json_base64"], validate=True)
        self.assertEqual(hashlib.sha256(event_bytes).hexdigest(), event_vector["sha256"])
        self.assertEqual(
            cases["create_absent"]["expected"]["resume_attempt"],
            1,
        )

    def test_checkpoint_resume_fixture_covers_all_fault_boundaries(self) -> None:
        fixture = json.loads((ROOT / "fixtures/checkpoint_resume_v1.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case for case in fixture["runner_cases"]}
        matrix = fixture["fault_matrix"]

        self.assertEqual([case["id"] for case in matrix], [f"F{index}" for index in range(1, 9)])
        self.assertEqual(
            cases["started_model_requires_reconciliation"]["expected"]["completion_reason"],
            None,
        )
        self.assertEqual(
            cases["ambiguous_non_idempotent_tool_stops"]["expected"]["silent_retries"],
            0,
        )
        self.assertEqual(
            cases["ambiguous_idempotent_tool_retries_same_key"]["expected"]["effects_total"],
            1,
        )
        self.assertEqual(
            cases["budget_elapsed_continues_from_snapshot"]["expected"]["downtime_ms_counted"],
            0,
        )
        approval = cases["approval_resume_reenters_tool_journal"]
        self.assertEqual(
            approval["run"]["durable_order"],
            [
                "source_tool_planned",
                "source_waiting_terminal_clears_journal",
                "approval_claim_bound_to_resume_checkpoint_key",
                "resume_checkpoint_created_or_loaded",
                "resume_tool_planned_with_source_identity",
                "resume_tool_started",
                "tool_invoked",
                "resume_tool_succeeded",
            ],
        )
        self.assertTrue(approval["expected"]["same_idempotency_key"])
        self.assertTrue(approval["expected"]["distinct_checkpoint_key"])
        self.assertEqual(approval["expected"]["source_terminal_journal_count"], 0)
        self.assertEqual(approval["run"]["resume_api"]["runner"], "configured")
        self.assertEqual(
            approval["run"]["approval_resume_run_config"]["checkpoint_config"]["resume_policy"],
            "resume_if_present",
        )
        self.assertTrue(approval["expected"]["approval_claim_same_key_is_idempotent"])
        self.assertTrue(approval["expected"]["approval_claim_different_key_is_rejected"])

        session = fixture["session_persistence"]
        vector = session["golden_case"]
        checkpoint_digest = hashlib.sha256(vector["checkpoint_key"].encode("utf-8")).hexdigest()
        self.assertEqual(checkpoint_digest, vector["checkpoint_key_utf8_sha256"])
        self.assertEqual(
            vector["commit_id"],
            f"{session['commit_id_prefix']}{checkpoint_digest}",
        )
        canonical = base64.b64decode(vector["canonical_json_base64"], validate=True)
        self.assertEqual(len(canonical), vector["canonical_json_utf8_bytes"])
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), vector["sha256"])
        self.assertEqual(json.loads(canonical), vector["payload"])
        session_cases = {case["name"]: case for case in session["cases"]}
        self.assertEqual(
            session_cases["identical_replay_does_not_append"]["expected"]["items_appended"],
            0,
        )
        self.assertEqual(
            session_cases["same_identity_different_payload_fails"]["expected"]["error_code"],
            "session_commit_identity_conflict",
        )
        self.assertFalse(fixture["fault_test_requirements"]["sleep_only_fault_timing"])

    def test_checkpoint_terminal_order_finalizes_before_event_delivery(self) -> None:
        runner = json.loads((ROOT / "fixtures/runner_terminal_v1.json").read_text(encoding="utf-8"))
        distributed = json.loads(
            (ROOT / "fixtures/distributed_run_envelope_v2.json").read_text(encoding="utf-8")
        )
        runner_order = runner["checkpoint_v2_terminal_order"]["order"]
        distributed_order = distributed["worker_rules"]["terminal_commit_order"]

        self.assertLess(
            runner_order.index("terminal_event_outbox_pending"),
            runner_order.index("checkpoint_terminal_finalize"),
        )
        self.assertLess(
            runner_order.index("checkpoint_terminal_finalize"),
            runner_order.index("terminal_event_outbox_delivered"),
        )
        self.assertLess(
            runner_order.index("terminal_event_outbox_delivered"),
            runner_order.index("terminal_event_delivery_recorded"),
        )
        self.assertEqual(distributed_order[-1], "scheduler_acknowledgement")
        self.assertLess(
            distributed_order.index("checkpoint_terminal_finalize"),
            distributed_order.index("terminal_event_delivery"),
        )

    def test_checkpoint_outbox_event_identity_is_unique(self) -> None:
        codec = json.loads((ROOT / "fixtures/checkpoint_codec_v2.json").read_text(encoding="utf-8"))
        store = json.loads((ROOT / "fixtures/checkpoint_store_v2.json").read_text(encoding="utf-8"))

        self.assertTrue(codec["status_rules"]["event_outbox_event_ids_are_unique"])
        self.assertEqual(
            codec["status_rules"]["duplicate_event_id_error"],
            "event_identity_conflict",
        )
        self.assertTrue(store["revision_rules"]["outbox_event_ids_unique"])
        self.assertTrue(store["revision_rules"]["identical_event_enqueue_reuses_existing_entry"])

    def test_resume_events_and_app_server_projection_remain_interruptions(self) -> None:
        records = [
            json.loads(line)
            for line in (ROOT / "fixtures/resume_events_v1.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        app = json.loads((ROOT / "fixtures/app_server_observable_v1.json").read_text(encoding="utf-8"))
        projections = {case["name"]: case for case in app["terminal"]["agentStatusProjection"]}

        grouped: dict[str, list[dict[str, object]]] = {}
        for record in records:
            self.assertNotIn("scenario_id", record)
            grouped.setdefault(record["run_id"], []).append(record)
        self.assertEqual(
            {name: [record["type"] for record in scenario] for name, scenario in grouped.items()},
            {
                "run_checkpoint_create": ["checkpoint_created"],
                "run_receipt_replay": ["checkpoint_resumed", "operation_replayed"],
                "run_reconciliation_required": ["operation_ambiguous", "reconciliation_required"],
                "run_model_retry": ["operation_ambiguous", "model_retry_duplicate_risk"],
                "run_reconciliation_resolved": [
                    "operation_ambiguous",
                    "reconciliation_required",
                    "reconciliation_resolved",
                ],
            },
        )
        for scenario in grouped.values():
            self.assertEqual(len({record["run_id"] for record in scenario}), 1)
            self.assertEqual(len({record["trace_id"] for record in scenario}), 1)
        reconciliation = projections["reconciliation_required_is_interrupted_without_error"]
        self.assertEqual(reconciliation["turnStatus"], "interrupted")
        self.assertIsNone(reconciliation["completionReason"])
        self.assertEqual(reconciliation["errorField"], "omitted")
        self.assertEqual(app["durableResume"]["method"], "turn/resume")
        self.assertFalse(app["durableResume"]["newInputAllowed"])
        self.assertEqual(
            app["durableResume"]["checkpointSummary"]["fields"],
            ["key", "resumeAttempt", "cycleIndex", "status", "terminalAcknowledged"],
        )
        self.assertEqual(
            app["durableResume"]["interruptionSummary"]["fields"],
            ["reason", "operationId", "operationKind", "cycleIndex", "risk", "idempotencySupport"],
        )
        self.assertIn("AgentStatus", app["durableResume"]["checkpointSummary"]["statusDomain"])
        projection_cases = {
            case["name"]: case for case in app["durableResume"]["projectionCases"]
        }
        self.assertEqual(projection_cases["reconciliation_required"]["turnStatus"], "interrupted")
        self.assertEqual(projection_cases["live_claim"]["checkpoint"]["status"], "running")
        self.assertEqual(projection_cases["terminal_replay"]["externalCalls"], 0)
        self.assertTrue(
            {"runDefinition", "runDefinitionDigest"}.issubset(
                app["durableResume"]["sensitiveFieldsNeverProjected"]
            )
        )
        protocol_cases = {
            case["name"]: case for case in app["durableResume"]["protocolCases"]
        }
        reconciliation_protocol = protocol_cases["resume_reaches_reconciliation_interruption"]
        self.assertEqual(reconciliation_protocol["request"]["method"], "turn/resume")
        self.assertEqual(
            reconciliation_protocol["notificationOrder"],
            [
                "thread/status/changed:running",
                "turn/started",
                "thread/status/changed:idle",
                "turn/completed:interrupted",
            ],
        )
        terminal_params = reconciliation_protocol["notifications"][-1]["params"]
        self.assertNotIn("completionReason", terminal_params)
        self.assertNotIn("error", terminal_params)
        self.assertEqual(terminal_params["status"], "interrupted")
        live_claim = protocol_cases["live_claim_keeps_existing_owner"]
        self.assertFalse(live_claim["newRunCreated"])
        self.assertEqual(live_claim["notifications"], [])
        terminal_replay = protocol_cases["terminal_replay_is_response_only"]
        self.assertEqual(terminal_replay["response"]["result"]["status"], "completed")
        self.assertEqual(terminal_replay["externalCalls"], 0)

    def test_distributed_v2_preserves_v1_and_resolves_checkpoint_capabilities(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/distributed_run_envelope_v2.json").read_text(encoding="utf-8")
        )
        envelope = fixture["canonical_envelope"]
        capabilities = envelope["recipe"]["capabilities"]

        self.assertTrue(fixture["compatibility"]["v1_bytes_must_remain_unchanged"])
        self.assertEqual(envelope["schema_version"], "vv-agent.distributed-run.v2")
        self.assertEqual(envelope["run_definition_schema"], "vv-agent.run-definition.v1")
        self.assertEqual(capabilities["checkpoint_store_ref"]["version"], "2")
        self.assertEqual(
            capabilities["after_cycle_hook_refs"],
            [{"id": "lifecycle.policy", "version": "1"}],
        )
        self.assertEqual(fixture["worker_rules"]["apalis_blocking_runtime"], "tokio_spawn_blocking")
        self.assertTrue(fixture["worker_rules"]["after_cycle_hook_resolution_before_claim"])
        self.assertTrue(fixture["worker_rules"]["heartbeat_cannot_overwrite_journal"])
        self.assertTrue(fixture["worker_rules"]["reconciliation_provider_is_optional"])
        self.assertEqual(
            fixture["worker_rules"]["terminal_commit_order"][-1],
            "scheduler_acknowledgement",
        )
        self.assertTrue(fixture["resume_attempt_rules"]["checkpoint_store_is_authoritative"])
        self.assertEqual(envelope["claim_mode"], "recovery")
        self.assertEqual(
            envelope["checkpoint_config"]["credential_slots"],
            ["/model/settings/extra_headers/authorization"],
        )
        self.assertTrue(
            fixture["claim_mode_rules"]["transport_redelivery_metadata_promotes_continue_to_recovery"]
        )
        schema_errors = {
            case["name"]: case["error"]
            for case in fixture["invalid_cases"]
            if "run_definition_schema" in case["name"]
        }
        self.assertEqual(
            set(schema_errors.values()),
            {"checkpoint_definition_schema_unsupported"},
        )
        invalid = {case["name"]: case for case in fixture["invalid_cases"]}
        self.assertNotIn("missing_reconciliation_provider", invalid)
        self.assertEqual(
            invalid["resume_attempt_mismatch"]["error"],
            "checkpoint_resume_attempt_mismatch",
        )
        self.assertEqual(
            {invalid[name]["error"] for name in ("missing_claim_mode", "unknown_claim_mode")},
            {"checkpoint_claim_mode_invalid"},
        )

    def test_checkpoint_sqlite_v2_is_isolated_from_v1(self) -> None:
        sql = (ROOT / "fixtures/checkpoint_sqlite_canonical_v2.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS checkpoints_v2", sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS checkpoints (", sql)
        self.assertIn("run_definition_schema TEXT NOT NULL", sql)
        self.assertIn("run_definition TEXT NOT NULL", sql)
        self.assertIn("terminal_acknowledged", sql)
        self.assertIn("model_call_journal", sql)
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(sql)
            connection.execute(
                "CREATE TABLE checkpoints (task_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                """
                INSERT INTO checkpoints_v2 (
                    checkpoint_key, schema_version, run_definition_schema, run_definition, task_id,
                    root_run_id, trace_id, run_definition_digest, resume_attempt,
                    cycle_index, status, messages, cycles, shared_state, budget_usage,
                    event_cursor, event_outbox, extension_state, model_call_journal,
                    tool_journal, unknown_fields, revision, claim_token, claimed_cycle,
                    lease_expires_at_ms, terminal_result, terminal_acknowledged
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "key-v2",
                    "vv-agent.checkpoint.v2",
                    "vv-agent.run-definition.v1",
                    "{}",
                    "task-v2",
                    "run-v2",
                    "trace-v2",
                    "c" * 64,
                    1,
                    0,
                    "running",
                    "[]",
                    "[]",
                    "{}",
                    None,
                    None,
                    "[]",
                    "{}",
                    "[]",
                    "[]",
                    "{}",
                    0,
                    None,
                    None,
                    None,
                    None,
                    0,
                ),
            )
            connection.execute(
                "INSERT INTO checkpoints (task_id, payload) VALUES (?, ?)",
                ("task-v1", "{}"),
            )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertTrue({"checkpoints", "checkpoints_v2"}.issubset(tables))
            self.assertEqual(
                connection.execute(
                    "SELECT run_definition_schema FROM checkpoints_v2 WHERE checkpoint_key = ?",
                    ("key-v2",),
                ).fetchone(),
                ("vv-agent.run-definition.v1",),
            )
        finally:
            connection.close()

    def test_checkpoint_and_distributed_v1_golden_bytes_are_unchanged(self) -> None:
        expected = {
            "checkpoint_codec_v1.json": "e7be2cfafca7f741d32b4537cb003f0179f69162171432c17cd746a0ff2119cf",
            "distributed_run_envelope_v1.json": "c1eb11591c93e8ac880fd4688cf06e0fe60a8b4522f7707ea13e1cccf40208e0",
        }
        for filename, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / "fixtures" / filename).read_bytes()).hexdigest(), digest)

    def test_snapshot_sync_and_offline_check(self) -> None:
        revision = "b" * 40
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            dist = temporary_path / "dist"
            build = contractctl.build_bundle(ROOT, dist, revision=revision)
            implementation = temporary_path / "implementation"
            implementation.mkdir()
            args = SimpleNamespace(
                repo_root=implementation,
                lock="contract.lock.json",
                source=ROOT,
                revision=revision,
                artifact=build["artifact"],
                artifact_url=(
                    "https://github.com/AndersonBY/vv-agent-contract/releases/download/"
                    "v0.6.0/vv-agent-contract-0.6.0.zip"
                ),
                snapshot_path="tests/fixtures/parity",
            )

            synced = contract_snapshot.sync_snapshot(args)
            checked = contract_snapshot.check_lock(implementation, "contract.lock.json")

            self.assertEqual(synced["fixture_files"], 49)
            self.assertEqual(checked["contract_revision"], revision)
            contract_snapshot.compare_trees(ROOT / "fixtures", implementation / "tests/fixtures/parity")

    def test_snapshot_check_rejects_manual_edit(self) -> None:
        revision = "c" * 40
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            build = contractctl.build_bundle(ROOT, temporary_path / "dist", revision=revision)
            implementation = temporary_path / "implementation"
            implementation.mkdir()
            contract_snapshot.sync_snapshot(
                SimpleNamespace(
                    repo_root=implementation,
                    lock="contract.lock.json",
                    source=ROOT,
                    revision=revision,
                    artifact=build["artifact"],
                    artifact_url="https://example.invalid/vv-agent-contract-0.6.0.zip",
                    snapshot_path="fixtures",
                )
            )
            fixture = implementation / "fixtures/model_ref_v1.json"
            fixture.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(contract_snapshot.SnapshotError, "fixture digest mismatch"):
                contract_snapshot.check_lock(implementation, "contract.lock.json")

    def test_verified_adoption_is_structured_and_enforced(self) -> None:
        revision = "d" * 40
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            contract_root = temporary_path / "contract"
            contract_root.mkdir()
            shutil.copy2(ROOT / "contract.json", contract_root / "contract.json")
            shutil.copy2(ROOT / "support-matrix.json", contract_root / "support-matrix.json")
            matrix = record_adoption.record_adoption(
                contract_root,
                revision,
                "e" * 40,
                "https://github.com/AndersonBY/vv-agent-contract/actions/runs/123",
                verified_at="2026-07-13T12:00:00Z",
            )
            self.assertEqual(matrix["status"], "verified")
            self.assertEqual(matrix["implementations"]["python"]["verified_revision"], revision)

            build = contractctl.build_bundle(ROOT, temporary_path / "dist", revision=revision)
            implementation = temporary_path / "implementation"
            implementation.mkdir()
            contract_snapshot.sync_snapshot(
                SimpleNamespace(
                    repo_root=implementation,
                    lock="contract.lock.json",
                    source=ROOT,
                    revision=revision,
                    artifact=build["artifact"],
                    artifact_url="https://example.invalid/vv-agent-contract-0.6.0.zip",
                    snapshot_path="fixtures",
                )
            )
            report = contract_snapshot.verify_adoption(
                implementation,
                "contract.lock.json",
                "python",
                str(contract_root / "support-matrix.json"),
            )
            self.assertEqual(report["verified_revision"], revision)


if __name__ == "__main__":
    unittest.main()
