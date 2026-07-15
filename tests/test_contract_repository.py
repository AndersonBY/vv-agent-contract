from __future__ import annotations

import json
import shutil
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

    def test_validate_workflow_supports_manual_dispatch(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:\n", workflow)

    def test_live_contract_validates(self) -> None:
        report = contractctl.validate_contract(ROOT)
        matrix = json.loads((ROOT / "support-matrix.json").read_text(encoding="utf-8"))

        self.assertEqual(report["version"], "0.4.0")
        self.assertEqual(report["domains"], 19)
        self.assertEqual(report["fixture_files"], 38)
        self.assertEqual(report["manifest_entries"], 37)
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
        self.assertEqual(len(capabilities), 128)

        surfaces = {surface["id"]: surface for surface in fixture["surfaces"]}
        surface_member_count = sum(
            len(surface.get("members", []))
            + len(surface.get("protocol_operations", []))
            + len(surface.get("supporting_operations", []))
            for surface in fixture["surfaces"]
        )
        self.assertEqual(surface_member_count, 221)
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
                    "v0.4.0/vv-agent-contract-0.4.0.zip"
                ),
                snapshot_path="tests/fixtures/parity",
            )

            synced = contract_snapshot.sync_snapshot(args)
            checked = contract_snapshot.check_lock(implementation, "contract.lock.json")

            self.assertEqual(synced["fixture_files"], 38)
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
                    artifact_url="https://example.invalid/vv-agent-contract-0.4.0.zip",
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
                    artifact_url="https://example.invalid/vv-agent-contract-0.4.0.zip",
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
