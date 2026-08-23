from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
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

    def test_cross_repository_gate_runs_bidirectional_sqlite_probe(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")

        self.assertIn("Verify cross-language SQLite checkpoint", workflow)
        self.assertEqual(workflow.count("VV_AGENT_CROSS_RUNTIME_MODE="), 4)
        for mode in ("write_python", "read_python", "write_rust", "read_rust"):
            self.assertIn(f"VV_AGENT_CROSS_RUNTIME_MODE={mode}", workflow)

    def test_record_verified_requires_all_default_branches(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")
        recording_step = workflow.split("- name: Update verified support matrix", maxsplit=1)[1].split(
            "- name: Commit verified support matrix", maxsplit=1
        )[0]

        for input_name in ("contract_ref", "python_ref", "rust_ref"):
            self.assertIn(f'test "${{{{ inputs.{input_name} }}}}" = "main"', recording_step)

    def test_validate_workflow_supports_manual_dispatch(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:\n", workflow)

    def test_live_contract_validates(self) -> None:
        report = contractctl.validate_contract(ROOT)
        matrix = json.loads((ROOT / "support-matrix.json").read_text(encoding="utf-8"))

        self.assertEqual(report["version"], "7.0.0")
        self.assertEqual(report["domains"], 20)
        self.assertEqual(report["fixture_files"], 53)
        self.assertEqual(report["manifest_entries"], 52)
        self.assertEqual(report["adoption_status"], matrix["status"])

    def test_model_settings_fixture_has_one_explicit_current_shape(self) -> None:
        fixture = json.loads((ROOT / "fixtures/model_settings.json").read_text(encoding="utf-8"))

        self.assertEqual(fixture["schema_version"], "vv-agent.model-settings.v1")
        self.assertEqual(fixture["file_contract"]["extensions"], [".py", ".json", ".toml"])
        self.assertEqual(fixture["file_contract"]["python_assignment"], "LLM_SETTINGS")
        self.assertTrue(fixture["file_contract"]["direct_root"])
        self.assertFalse(fixture["file_contract"]["parser_retry"])
        self.assertFalse(fixture["root_contract"]["default_synthesis"])
        self.assertEqual(
            {case["name"] for case in fixture["invalid_settings"]},
            {
                "missing_version",
                "wrong_version",
                "missing_backends",
                "missing_endpoints",
                "backends_wrong_type",
                "endpoints_wrong_type",
            },
        )
        self.assertTrue(fixture["resolution_contract"]["exact_backend_key"])
        self.assertTrue(fixture["resolution_contract"]["exact_model_key"])
        self.assertFalse(fixture["resolution_contract"]["implicit_output_limit"])

    def test_session_codec_has_one_closed_current_wire(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/session_codec.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            set(fixture),
            {
                "version",
                "message_contract",
                "model_projection",
                "canonical_cases",
                "invalid_cases",
            },
        )
        self.assertEqual(fixture["version"], 2)
        self.assertEqual(
            {case["name"] for case in fixture["canonical_cases"]},
            {
                "plain_message_uses_current_wire",
                "openai_function_tool_call_is_canonicalized",
                "microcompacted_tool_message_round_trips",
            },
        )

        message_fields = {
            "role",
            "content",
            "name",
            "tool_call_id",
            "tool_calls",
            "reasoning_content",
            "image_url",
            "metadata",
            "artifact_ref",
        }
        for case in fixture["canonical_cases"]:
            for key in ("input", "canonical"):
                message = case[key]
                self.assertTrue({"role", "content"}.issubset(message))
                self.assertTrue(set(message).issubset(message_fields))
                for tool_call in message.get("tool_calls", []):
                    self.assertTrue(
                        {"id", "type", "function"}.issubset(tool_call)
                    )
                    self.assertTrue(
                        set(tool_call).issubset(
                            {"id", "type", "function", "extra_content"}
                        )
                    )
                    self.assertEqual(tool_call["type"], "function")
                    self.assertEqual(set(tool_call["function"]), {"name", "arguments"})
                    arguments = tool_call["function"]["arguments"]
                    self.assertIsInstance(arguments, str)
                    self.assertIsInstance(json.loads(arguments), dict)
                artifact_ref = message.get("artifact_ref")
                if artifact_ref is not None:
                    self.assertEqual(
                        set(artifact_ref),
                        {"path", "media_type", "encoding", "size_bytes", "sha256"},
                    )

        compacted = next(
            case
            for case in fixture["canonical_cases"]
            if case["name"] == "microcompacted_tool_message_round_trips"
        )
        self.assertEqual(compacted["input"], compacted["canonical"])
        self.assertIn("artifact_ref", compacted["canonical"])
        self.assertNotIn("artifact_ref", compacted["model_projection"])
        self.assertEqual(
            compacted["model_projection"]["content"],
            compacted["canonical"]["content"],
        )
        self.assertEqual(fixture["model_projection"]["strip_host_only_fields"], ["artifact_ref"])
        self.assertTrue(fixture["message_contract"]["artifact_ref_omitted_when_absent"])

        invalid_names = {case["name"] for case in fixture["invalid_cases"]}
        self.assertTrue(
            {
                "content_is_required",
                "unknown_message_field_is_rejected",
                "tool_call_unknown_field_is_rejected",
                "tool_function_unknown_field_is_rejected",
                "message_missing_content_is_rejected",
                "tool_arguments_must_be_a_json_string",
                "tool_call_requires_function_envelope",
                "message_requires_role_field",
                "artifact_ref_bad_path_is_rejected",
                "artifact_ref_bad_hash_is_rejected",
                "artifact_ref_missing_field_is_rejected",
                "artifact_ref_unknown_field_is_rejected",
            }.issubset(invalid_names)
        )

    def test_checkpoint_outbox_embeds_a_complete_current_run_event(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/checkpoint_codec.json").read_text(encoding="utf-8")
        )
        entry = fixture["canonical_checkpoint"]["event_outbox"][0]
        event = entry["event"]

        self.assertEqual(
            set(entry),
            {"event_id", "payload_digest", "state", "event", "cursor"},
        )
        self.assertEqual(entry["event_id"], event["event_id"])
        self.assertEqual(event["version"], "v4")
        self.assertTrue(
            {"version", "type", "event_id", "run_id", "trace_id", "created_at"}.issubset(
                event
            )
        )
        outbox_contract = fixture["event_outbox_contract"]
        self.assertEqual(outbox_contract["bound_kind"], "lifecycle_bounded")
        self.assertFalse(outbox_contract["fixed_cardinality_or_bytes_cap"])
        self.assertTrue(outbox_contract["preflight_before_first_external_tool_effect"])
        self.assertFalse(outbox_contract["capacity_failure_after_external_effect"])
        self.assertFalse(outbox_contract["admission_or_resolution_rejects_for_capacity"])

    def test_all_current_run_event_fixtures_use_v4_only(self) -> None:
        for name in (
            "run_events.jsonl",
            "budget_events.jsonl",
            "configured_sub_agent_events.jsonl",
            "resume_events.jsonl",
            "runner_events.jsonl",
        ):
            records = [
                json.loads(line)
                for line in (ROOT / "fixtures" / name)
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertTrue(records, name)
            self.assertEqual({record["version"] for record in records}, {"v4"}, name)

        invalid = json.loads(
            (ROOT / "fixtures/run_events_invalid.json").read_text(encoding="utf-8")
        )
        self.assertEqual(invalid["rules"]["version"], "v4")
        rejected = {case["id"]: case["input"] for case in invalid["reject"]}
        self.assertEqual(rejected["stale_version"]["version"], "v3")
        self.assertEqual(rejected["unknown_version"]["version"], "v5")
        self.assertEqual(rejected["future_version"]["version"], "v5")

        configured = json.loads(
            (ROOT / "fixtures/configured_sub_agent.json").read_text(encoding="utf-8")
        )
        self.assertEqual(configured["version"], "v2")
        configured_events = [
            json.loads(line)
            for line in (ROOT / "fixtures/configured_sub_agent_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual({event["version"] for event in configured_events}, {"v4"})

    def test_memory_capacity_contract_locks_default_clamp_and_observability(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures" / "memory_lifecycle.json").read_text(encoding="utf-8")
        )
        capacity = fixture["capacity_contract"]

        self.assertEqual(capacity["configured_default_threshold"], 250_000)
        self.assertEqual(capacity["microcompact_trigger_ratio_default"], 0.75)
        self.assertEqual(capacity["microcompact_target_ratio_default"], 0.6)
        self.assertEqual(
            capacity["reserved_output_precedence"],
            [
                "effective_model_settings.max_tokens",
                "task_metadata.reserved_output_tokens",
                "framework_fallback",
            ],
        )
        cases = {case["name"]: case for case in capacity["cases"]}
        self.assertEqual(
            cases["kimi_k3_uses_full_configured_ceiling"]["expected"]
            ["effective_threshold"],
            250_000,
        )
        self.assertEqual(
            cases["known_zero_capacity_stays_zero"]["expected"]
            ["effective_threshold"],
            0,
        )
        self.assertEqual(
            cases[
                "explicit_request_limit_is_not_capped_by_smaller_model_capability"
            ]["expected"]["reserved_output_tokens"],
            24_000,
        )
        self.assertEqual(
            cases[
                "explicit_host_reserve_is_not_capped_by_smaller_model_capability"
            ]["expected"]["reserved_output_tokens"],
            24_000,
        )

        context_cases = {
            case["name"]: case
            for case in capacity["context_window_resolution"]["cases"]
        }
        self.assertTrue(
            capacity["context_window_resolution"]
            ["non_positive_task_metadata_is_absent"]
        )
        self.assertEqual(
            context_cases["zero_metadata_uses_resolved_capability"]
            ["expected_model_context_window"],
            64_000,
        )
        self.assertEqual(
            context_cases[
                "zero_metadata_without_resolved_capability_uses_derived_planning_context"
            ]["expected_model_context_window"],
            279_000,
        )
        self.assertEqual(
            capacity["unknown_context_window_strategy"]["default_model_context_window"],
            279_000,
        )

        lifecycle = fixture["compaction_events"]
        self.assertEqual(
            lifecycle["started"]["trigger_values"],
            ["micro_threshold", "full_threshold", "prompt_too_long"],
        )
        self.assertEqual(
            lifecycle["completed"]["mode_values"],
            ["none", "micro", "structural", "summary", "emergency"],
        )
        self.assertEqual(
            lifecycle["started"]["producer_fields"],
            [
                "trigger",
                "configured_threshold",
                "effective_threshold",
                "microcompact_threshold",
                "microcompact_target",
                "candidate_count",
                "estimated_reclaimable_tokens",
                "model_context_window",
                "model_max_output_tokens",
                "reserved_output_tokens",
                "reserved_output_source",
                "autocompact_buffer_tokens",
            ],
        )
        self.assertEqual(
            lifecycle["completed"]["producer_fields"],
            [
                "mode",
                "changed",
                "archived_count",
                "reclaimed_tokens",
                "artifact_failure_count",
            ],
        )
        planning = lifecycle["microcompact_planning"]
        self.assertTrue(planning["single_plan_and_apply_pass_per_cycle"])
        self.assertTrue(planning["candidate_required_for_micro_threshold_trigger"])
        self.assertEqual(planning["micro_threshold_without_candidate_event_count"], 0)
        self.assertTrue(
            planning["full_or_prompt_too_long_trigger_may_start_without_micro_candidate"]
        )
        self.assertTrue(planning["archive_failure_does_not_stop_later_candidates"])
        self.assertEqual(
            lifecycle["simultaneous_warning_and_microcompact"]["order"],
            [
                "microcompact_eligible_old_tool_results",
                "recalculate_effective_length",
                "append_memory_warning_only_if_post_microcompact_length_remains_eligible",
            ],
        )
        self.assertEqual(
            lifecycle["provider_and_journal_share_event_identity"],
            ["event_id", "created_at"],
        )
        self.assertTrue(lifecycle["missing_or_unknown_fields_are_rejected"])

        events = [
            json.loads(line)
            for line in (ROOT / "fixtures/run_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        started = next(event for event in events if event["type"] == "memory_compact_started")
        completed = next(event for event in events if event["type"] == "memory_compact_completed")
        self.assertTrue(
            {
                "microcompact_target",
                "candidate_count",
                "estimated_reclaimable_tokens",
            }.issubset(started)
        )
        self.assertTrue(
            {
                "archived_count",
                "reclaimed_tokens",
                "artifact_failure_count",
            }.issubset(completed)
        )
        invalid_events = json.loads(
            (ROOT / "fixtures/run_events_invalid.json").read_text(encoding="utf-8")
        )
        rejected = {case["id"] for case in invalid_events["reject"]}
        self.assertTrue(
            {
                "memory_compact_target_is_negative",
                "memory_compact_candidate_count_is_negative",
                "memory_compact_estimated_reclaimable_tokens_is_negative",
                "memory_compact_archived_count_is_negative",
                "memory_compact_reclaimed_tokens_is_negative",
                "memory_compact_artifact_failure_count_is_negative",
                "memory_compact_started_missing_plan_counter",
                "memory_compact_completed_missing_result_counter",
            }.issubset(rejected)
        )

        session_memory = fixture["session_memory"]
        self.assertFalse(session_memory["enabled_by_default"])
        self.assertEqual(session_memory["accepted_aliases"], [])
        gate_cases = {case["name"]: case for case in session_memory["gate_cases"]}
        for name in (
            "explicitly_disabled_ignores_all_memory_inputs",
            "omitted_control_uses_disabled_default",
        ):
            expected = gate_cases[name]["expected"]
            self.assertEqual(expected["context_sections_rendered"], 0)
            self.assertEqual(expected["storage_read_count"], 0)
            self.assertEqual(expected["storage_write_count"], 0)
            self.assertEqual(expected["session_memory_model_dispatch_count"], 0)
        child = gate_cases["child_does_not_inherit_enabled_parent"]["expected"]
        self.assertFalse(child["child_effective_control"])
        self.assertEqual(child["child_storage_read_count"], 0)
        self.assertEqual(child["child_storage_write_count"], 0)
        self.assertEqual(child["child_session_memory_model_dispatch_count"], 0)
        replay = session_memory["checkpoint_receipt_replay"]
        self.assertEqual(replay["new_model_dispatches"], 0)
        self.assertEqual(replay["new_model_call_records"], 0)
        self.assertTrue(replay["replay_is_idempotent"])

    def test_microcompaction_is_archive_backed_and_model_marker_is_minimal(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures" / "memory_local.json").read_text(encoding="utf-8")
        )["microcompact"]

        self.assertEqual(fixture["schema_version"], "vv-agent.microcompaction.v3")
        self.assertEqual(fixture["trigger_ratio_default"], 0.75)
        self.assertEqual(fixture["target_ratio_default"], 0.6)
        self.assertEqual(fixture["keep_recent_cycles_default"], 3)
        self.assertEqual(fixture["min_result_chars_default"], 500)
        self.assertEqual(
            fixture["policy_wire"]["transport"],
            [
                "RunConfig.microcompaction_policy",
                "AgentTask.microcompaction_policy",
                "run_definition.runtime_controls.microcompaction_policy",
            ],
        )
        self.assertFalse(fixture["policy_wire"]["generic_metadata_transport"])
        contracts = fixture["policy_wire"]["field_contracts"]
        self.assertEqual(contracts["trigger_ratio"]["type"], "finite_number")
        self.assertEqual(contracts["target_ratio"]["must_be_less_than"], "trigger_ratio")
        self.assertEqual(contracts["keep_recent_cycles"]["minimum"], 0)
        self.assertEqual(contracts["keep_recent_cycles"]["maximum"], 4_294_967_295)
        self.assertEqual(contracts["min_result_chars"]["minimum"], 1)
        self.assertEqual(contracts["min_result_chars"]["maximum"], 4_294_967_295)
        self.assertFalse(contracts["keep_recent_cycles"]["boolean_is_integer"])
        self.assertFalse(contracts["keep_recent_cycles"]["float_integer_is_integer"])
        invalid_policy_names = {
            case["name"] for case in fixture["policy_wire"]["invalid_cases"]
        }
        self.assertTrue(
            {
                "missing_trigger_ratio",
                "missing_target_ratio",
                "missing_keep_recent_cycles",
                "missing_min_result_chars",
                "unknown_field",
                "trigger_ratio_is_null",
                "trigger_ratio_is_boolean",
                "trigger_ratio_is_non_finite",
                "trigger_ratio_is_zero",
                "trigger_ratio_exceeds_one",
                "target_ratio_is_null",
                "target_ratio_is_boolean",
                "target_ratio_is_non_finite",
                "target_ratio_is_zero",
                "target_ratio_exceeds_one",
                "target_ratio_not_below_trigger",
                "keep_recent_cycles_is_null",
                "keep_recent_cycles_is_boolean",
                "keep_recent_cycles_is_float_integer",
                "keep_recent_cycles_is_negative",
                "keep_recent_cycles_exceeds_u32",
                "min_result_chars_is_null",
                "min_result_chars_is_boolean",
                "min_result_chars_is_float_integer",
                "min_result_chars_is_zero",
                "min_result_chars_exceeds_u32",
            }.issubset(invalid_policy_names)
        )
        self.assertFalse(fixture["tool_name_allowlist"])
        self.assertEqual(fixture["result_retention"]["default"], "archive")
        self.assertTrue(fixture["archive"]["required_before_replacement"])
        self.assertEqual(
            fixture["archive"]["logical_path_prefix"],
            ".vv-agent/artifacts/",
        )
        reuse = fixture["archive"]["existing_artifact"]
        self.assertTrue(reuse["reuse_only_after_validation"])
        self.assertIn("UTF8", reuse["size_check"])
        self.assertIn("sha256", reuse["digest_check"])
        self.assertEqual(reuse["validation_failure"], "preserve_original_message")
        application = fixture["application"]
        self.assertTrue(application["planned_estimates_do_not_satisfy_target"])
        self.assertTrue(application["recalculate_after_each_successful_replacement"])

        marker = fixture["model_visible_marker"]
        self.assertEqual(
            marker["field_order"],
            ["tool_name", "artifact_path", "retrieval_hint", "excerpt"],
        )
        self.assertEqual(
            marker["retrieval_hint"],
            "use read_file on artifact_path if needed",
        )
        for forbidden in marker["forbidden_fields"]:
            self.assertNotIn(f"{forbidden}:", marker["example"])

        cases = {case["name"]: case for case in fixture["cases"]}
        self.assertTrue(
            cases["custom_tool_archived"]["replaced_with_compact_marker"]
        )
        self.assertFalse(
            cases["preserved_tool_remains_inline"]["replaced_with_compact_marker"]
        )
        self.assertFalse(
            cases["archive_failure_remains_inline"]["replaced_with_compact_marker"]
        )
        self.assertTrue(
            cases["validated_existing_artifact_is_reused"]["replaced_with_compact_marker"]
        )
        for name in (
            "existing_artifact_size_mismatch_remains_inline",
            "existing_artifact_sha256_mismatch_remains_inline",
        ):
            self.assertFalse(cases[name]["replaced_with_compact_marker"])
            self.assertTrue(cases[name]["original_message_preserved"])
        actual_target = cases["actual_replacement_delta_reaches_target"]
        self.assertGreater(
            sum(actual_target["planned_candidate_reclaim_tokens"]),
            actual_target["tokens_before_application"] - actual_target["target_tokens"],
        )
        self.assertLessEqual(
            actual_target["tokens_after_application"],
            actual_target["target_tokens"],
        )
        configured = json.loads(
            (ROOT / "fixtures/configured_sub_agent.json").read_text(encoding="utf-8")
        )
        configured_invalid = {
            case["name"]
            for case in configured["task_projection_validation"]["invalid_cases"]
        }
        self.assertIn("agent_task_missing_microcompaction_policy", configured_invalid)
        distributed = json.loads(
            (ROOT / "fixtures/distributed_run_envelope.json").read_text(encoding="utf-8")
        )
        distributed_invalid = {case["name"] for case in distributed["invalid_cases"]}
        self.assertIn("task_missing_microcompaction_policy", distributed_invalid)

    def test_prompt_bundle_requires_explicit_session_memory_enablement(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/prompt_bundle.json").read_text(encoding="utf-8")
        )
        self.assertEqual(fixture["schema_version"], "vv-agent.prompt-bundle.v2")
        self.assertEqual(
            fixture["run_scope"]["checkpoint_resume"],
            "restore_frozen_bundle_without_producer_or_clock_access",
        )
        self.assertIn(
            "system_prompt_sections_metadata_transport",
            fixture["compiler_contract"]["forbidden"],
        )
        scenarios = {case["id"]: case for case in fixture["scenarios"]}
        self.assertTrue({"en-US-full", "zh-CN-full", "en-US-minimal"}.issubset(scenarios))
        for scenario_id in ("en-US-full", "zh-CN-full", "en-US-minimal"):
            resolved = scenarios[scenario_id]["output"]
            self.assertEqual(
                resolved["flat_prompt"],
                "\n\n".join(section["text"] for section in resolved["sections"]),
            )
            self.assertEqual(len(resolved["stable_hash"]), 64)
        minimal = scenarios["en-US-minimal"]["output"]
        self.assertNotIn("session_memory", {section["id"] for section in minimal["sections"]})
        gate_cases = {case["name"]: case for case in fixture["session_memory_gate"]["probe_cases"]}
        self.assertEqual(
            set(gate_cases),
            {
                "explicit_false_ignores_nonempty_context",
                "omitted_control_ignores_nonempty_context",
            },
        )
        for case in gate_cases.values():
            self.assertEqual(case["expected_session_memory_section_count"], 0)
            self.assertEqual(case["expected_storage_reads"], 0)
            self.assertEqual(case["expected_storage_writes"], 0)
        compiler = scenarios["compiler-preserves-instruction-sections"]["output"]
        self.assertEqual(
            compiler["section_ids"][:2],
            ["identity", "run_data"],
        )
        run_scope_cases = {
            case["name"]: case for case in fixture["run_scope"]["conformance_cases"]
        }
        self.assertEqual(run_scope_cases["three_cycles_reuse_one_resolution"]["expected_clock_reads"], 1)
        resumed = run_scope_cases["checkpoint_resume_uses_frozen_bundle"]
        self.assertEqual(resumed["expected_resume_instruction_producer_calls"], 0)
        self.assertEqual(resumed["expected_resume_context_provider_calls"], 0)
        self.assertEqual(resumed["expected_resume_clock_reads"], 0)

        projections = {
            case["name"]: case
            for case in fixture["provider_projection"]["projection_cases"]
        }
        cached = projections["section_cache_en_US_full"]["expected"]
        self.assertEqual(cached["cache_boundary_block_index"], 2)
        self.assertEqual(
            "".join(block["text"] for block in cached["system_blocks"]),
            scenarios["en-US-full"]["output"]["flat_prompt"],
        )
        self.assertEqual(
            [index for index, block in enumerate(cached["system_blocks"]) if "cache_control" in block],
            [2],
        )
        no_prefix = projections["section_cache_no_leading_stable_prefix"]["expected"]
        self.assertIsNone(no_prefix["cache_boundary_block_index"])
        self.assertTrue(all("cache_control" not in block for block in no_prefix["system_blocks"]))
        invalid_names = {case["name"] for case in fixture["invalid_cases"]}
        self.assertTrue(
            {
                "missing_stable_hash",
                "stable_hash_mismatch",
                "unknown_bundle_field",
                "unknown_section_field",
                "metadata_section_side_channel",
                "stale_run_definition_schema",
            }.issubset(invalid_names)
        )

    def test_bounded_tool_result_is_sparse_and_recoverable(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/bounded_tool_result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            fixture["schema_version"], "vv-agent.tool-execution-result.v4"
        )
        ordinary = fixture["canonical_results"]["ordinary"]
        self.assertEqual(
            set(ordinary),
            {"tool_call_id", "content", "status_code", "directive"},
        )
        truncated = fixture["canonical_results"]["truncated_bash"]
        self.assertTrue(truncated["truncated"])
        self.assertTrue(truncated["artifact"]["path"].startswith(".vv-agent/artifacts/"))
        self.assertEqual(fixture["read_file_contract"]["content_null"], False)
        self.assertEqual(
            fixture["cursor_contract"]["changed_source_error_code"], "stale_cursor"
        )
        self.assertIn("path", fixture["cursor_contract"]["required_fields"])
        self.assertEqual(
            len(fixture["bash_contract"]["omission_marker"])
            + fixture["bash_contract"]["head_chars"]
            + fixture["bash_contract"]["tail_chars"],
            fixture["bash_contract"]["preview_limit_chars"],
        )
        self.assertIn("streaming_write", fixture["artifact_contract"])
        self.assertIn("without_full_output_materialization", fixture["bash_contract"]["above_limit_persistence"])

        required = set(fixture["result_contract"]["required_fields"])
        optional = set(fixture["result_contract"]["optional_fields"])
        truncation_fields = {
            "truncated",
            "truncation_reason",
            "original_bytes",
            "visible_bytes",
            "artifact",
            "cursor",
        }
        artifact_pattern = re.compile(fixture["artifact_contract"]["path"]["pattern"])

        def validate_result(result: dict[str, object]) -> None:
            keys = set(result)
            if not required.issubset(keys) or not keys.issubset(required | optional):
                raise ValueError("shape")
            if any(result[key] is None for key in keys & optional):
                raise ValueError("null optional")
            if result.get("truncated") is not True:
                if keys & truncation_fields:
                    raise ValueError("ordinary recovery fields")
                return
            for key in ("truncation_reason", "original_bytes", "visible_bytes"):
                if key not in result:
                    raise ValueError("missing truncation field")
            if result["visible_bytes"] != len(str(result["content"]).encode("utf-8")):
                raise ValueError("visible bytes")
            if int(result["visible_bytes"]) > int(result["original_bytes"]):
                raise ValueError("size order")
            reason = result["truncation_reason"]
            if reason == "output_limit":
                if "artifact" not in result or "cursor" in result:
                    raise ValueError("output recovery")
                artifact = result["artifact"]
                if not isinstance(artifact, dict) or not artifact_pattern.fullmatch(str(artifact["path"])):
                    raise ValueError("artifact path")
            elif reason == "read_limit":
                if "cursor" not in result or "artifact" in result:
                    raise ValueError("read recovery")
                cursor = result["cursor"]
                if not isinstance(cursor, dict) or set(cursor) != {
                    "kind",
                    "path",
                    "offset_chars",
                    "sha256",
                }:
                    raise ValueError("cursor shape")
            else:
                raise ValueError("reason")

        for result in fixture["canonical_results"].values():
            validate_result(result)

        def mutate(base: dict[str, object], mutation: dict[str, object]) -> dict[str, object]:
            result = copy.deepcopy(base)
            for operation in ("remove", "replace", "add"):
                value = mutation.get(operation)
                if value is None:
                    continue
                entries = [value] if operation == "remove" else list(value.items())
                for entry in entries:
                    path, replacement = (entry, None) if operation == "remove" else entry
                    parts = str(path).split(".")
                    target = result
                    for part in parts[:-1]:
                        target = target[part]  # type: ignore[assignment,index]
                    if operation == "remove":
                        target.pop(parts[-1], None)  # type: ignore[union-attr]
                    else:
                        target[parts[-1]] = replacement  # type: ignore[index]
            return result

        static_invalid = [
            case
            for case in fixture["invalid_cases"]
            if "base" in case and "mutation" in case and case["name"] not in {
                "cursor_path_mismatch",
                "cursor_source_changed",
                "cursor_offset_past_end",
            }
        ]
        for case in static_invalid:
            with self.subTest(case=case["name"]):
                candidate = mutate(fixture["canonical_results"][case["base"]], case["mutation"])
                with self.assertRaises(ValueError):
                    validate_result(candidate)

    def test_durable_deferred_tool_contract_is_closed_and_cas_recoverable(self) -> None:
        fixture = json.loads((ROOT / "fixtures/deferred_tool.json").read_text(encoding="utf-8"))

        self.assertEqual(fixture["schema_version"], "vv-agent.durable-deferred-tool.v2")
        self.assertEqual(fixture["contract_version"], "7.0.0")
        self.assertEqual(
            fixture["status_domains"]["agent_status"],
            [
                "pending",
                "running",
                "deferred",
                "reconciliation_required",
                "wait_user",
                "completed",
                "failed",
                "max_cycles",
            ],
        )
        self.assertEqual(
            fixture["handle"]["required_fields"],
            ["schema_version", "checkpoint_key", "operation_id", "attempt", "request_digest"],
        )
        self.assertEqual(
            fixture["handle"]["identity_fields"],
            ["checkpoint_key", "operation_id", "attempt", "request_digest"],
        )
        self.assertEqual(
            fixture["handle"]["discriminator"]["required_value"],
            "vv-agent.deferred-tool-handle.v2",
        )
        self.assertTrue(fixture["handle"]["framework_identity_only"])
        self.assertTrue(
            {
                "provider_id",
                "job_id",
                "poll",
                "callback",
                "deadline",
                "cancel",
                "billing",
                "business_id",
            }.issubset(fixture["handle"]["forbidden_fields"])
        )

        variants = fixture["outcome"]["variants"]
        self.assertEqual(set(variants), {"completed", "deferred"})
        self.assertTrue(variants["deferred"]["model_visible_tool_result"] is False)
        self.assertTrue(fixture["outcome"]["closed_objects"])
        self.assertTrue(fixture["outcome"]["exactly_one_variant"])

        self.assertEqual(
            fixture["journal"]["states"],
            ["planned", "started", "deferred", "succeeded", "failed", "ambiguous"],
        )
        self.assertEqual(
            fixture["journal"]["admission_transitions"] + fixture["journal"]["resolution_transitions"],
            [
                ["started", "deferred"],
                ["ambiguous", "deferred"],
                ["deferred", "succeeded"],
                ["deferred", "failed"],
            ],
        )
        self.assertEqual(fixture["batch"]["admission_operation"], "admit_deferred_batch")
        self.assertTrue(fixture["batch"]["admission_cas"]["atomic"])
        self.assertTrue(fixture["batch"]["mixed_completed_and_deferred"]["all_or_none"])
        self.assertTrue(fixture["batch"]["mixed_completed_and_deferred"]["claim_release"].startswith("one"))
        self.assertEqual(
            fixture["batch"]["mixed_completed_and_deferred"]["completed_status_mapping"]["SUCCESS"]["journal_state"],
            "succeeded",
        )
        self.assertEqual(
            fixture["batch"]["mixed_completed_and_deferred"]["completed_status_mapping"]["ERROR"]["journal_state"],
            "failed",
        )
        self.assertEqual(
            fixture["batch"]["error_completed_batch"]["completed_journal_state"],
            "failed",
        )
        outbox = fixture["batch"]["outbox_preflight"]
        self.assertEqual(outbox["bound_kind"], "lifecycle_bounded")
        self.assertFalse(outbox["fixed_cardinality_or_bytes_cap"])
        self.assertTrue(outbox["before_first_external_tool_effect"])
        self.assertFalse(outbox["admission_capacity_rejection"])
        self.assertFalse(outbox["resolution_capacity_rejection"])
        self.assertEqual(outbox["post_effect_outbox_full"], "forbidden")
        outbox_invalids = {
            case["name"]
            for case in fixture["invalid_cases"]
            if case.get("expected_error") == "outbox_preflight_contract_invalid"
        }
        self.assertEqual(
            outbox_invalids,
            {
                "outbox_full_after_external_effect_is_forbidden",
                "deferred_resolution_capacity_failure_after_provider_effect_is_forbidden",
            },
        )
        self.assertEqual(fixture["reconciliation"]["new_decision"], "accept_deferred")

        resolve = fixture["resolution"]
        self.assertEqual(resolve["scenario_id"], "deferred_resolution_call_b_then_call_a.v1")
        self.assertEqual(resolve["source"], "fixtures/deferred_tool.json#resolution")
        self.assertEqual(resolve["public_signature"], "resolve_deferred(handle, result)")
        self.assertEqual(resolve["return"], "DeferredResolveDecision")
        decision_variants = resolve["decision_type"]["variants"]
        self.assertEqual(
            set(decision_variants),
            {"applied_ready", "applied_waiting", "replayed", "not_admitted", "reconciliation_required"},
        )
        for name in ("applied_ready", "applied_waiting", "replayed"):
            self.assertTrue(decision_variants[name]["receipt_required"])
        self.assertTrue(decision_variants["not_admitted"]["receipt_forbidden"])
        self.assertTrue(decision_variants["reconciliation_required"]["receipt_forbidden"])
        self.assertNotIn("deferred_resolution_stale", resolve["decision_type"]["variants"])
        self.assertNotIn("deferred_resolution_conflict", resolve["decision_type"]["variants"])
        decision_invalids = {
            case["name"]
            for case in fixture["invalid_cases"]
            if case.get("expected_error") == "deferred_resolve_decision_invalid"
        }
        self.assertEqual(
            decision_invalids,
            {
                "applied_ready_without_receipt_is_invalid",
                "not_admitted_with_receipt_is_invalid",
                "resolve_decision_unknown_field_is_invalid",
            },
        )
        self.assertTrue(resolve["cas"]["claim_must_be_null"])
        self.assertTrue(resolve["cas"]["external_tool_is_never_called"])
        self.assertEqual(resolve["same_replay"]["different_result_after_resolution"], "reject_deferred_resolution_conflict")
        self.assertIn(
            "reject_deferred_resolution_stale",
            resolve["same_replay"]["different_handle"],
        )

        batch = fixture["batch"]
        self.assertTrue(batch["barrier"]["cycle_commit_blocked"])
        self.assertTrue(batch["barrier"]["next_model_call_blocked"])
        self.assertEqual(batch["example"]["scenario_id"], "deferred_batch_mixed_call_a_b_c.v1")
        self.assertEqual(batch["example"]["source"], "fixtures/deferred_tool.json#batch.example")
        self.assertEqual(batch["example"]["resolution_order"], ["call_c", "call_a"])
        self.assertEqual(batch["example"]["merged_tool_result_order"], ["call_a", "call_b", "call_c"])
        self.assertTrue(batch["example"]["single_admission_call"])
        self.assertTrue(batch["example"]["single_claim_release"])
        self.assertTrue(batch["barrier"]["claimable_statuses_exclude_deferred"])
        self.assertEqual(fixture["events_and_outbox"]["run_event_schema_version"], "v4")
        self.assertEqual(fixture["distributed"]["driver_wait_reason"], "deferred_pending")
        self.assertFalse(fixture["distributed"]["new_worker_response_variant"])
        self.assertEqual(fixture["distributed"]["pending_semantics"], "no cycle commit and no response result were returned by this delivery attempt")
        self.assertEqual(fixture["resolution"]["public_signature"], "resolve_deferred(handle, result)")
        self.assertTrue(fixture["resolution"]["receipt_index"]["retained_after_terminal"])
        self.assertFalse(fixture["resolution"]["receipt_index"]["bounded"])
        self.assertTrue(fixture["resolution"]["receipt_index"]["arbitrary_cardinality"])
        self.assertTrue(fixture["resolution"]["receipt_index"]["lifecycle_bounded"])
        self.assertFalse(fixture["resolution"]["receipt_index"]["fixed_cardinality_or_bytes_cap"])
        self.assertIsNone(fixture["resolution"]["receipt_index"]["checkpoint_field"])
        self.assertEqual(fixture["resolution"]["cas"]["write"][0], "active journal deferred -> succeeded or failed")
        self.assertTrue(fixture["reconciliation"]["batch_rules"]["aggregate_current_batch_decisions"])
        self.assertIn(
            "exact_handle_already_deferred",
            fixture["reconciliation"]["batch_rules"]["replay_rules"],
        )
        self.assertTrue(fixture["reconciliation"]["batch_rules"]["cas"]["atomic"])
        self.assertEqual(fixture["reconciliation"]["batch_rules"]["cas"]["revision_increment"], 1)
        self.assertTrue(
            fixture["tool_context"]["checkpoint_requirement"]["non_durable_run"][
                "factory_returns_error_before_provider_call"
            ]
        )

        invalid_errors = {case["expected_error"] for case in fixture["invalid_cases"] if "expected_error" in case}
        self.assertTrue(
            {
                "deferred_handle_unknown_field",
                "tool_call_outcome_invalid",
                "deferred_resolution_result_invalid",
                "deferred_resolution_stale",
                "deferred_resolution_conflict",
                "checkpoint_status_invalid",
            }.issubset(invalid_errors)
        )
        self.assertEqual(fixture["producer_evidence"]["python"]["status"], "pending-adoption")
        self.assertEqual(fixture["producer_evidence"]["rust"]["status"], "pending-adoption")

    def test_durable_deferred_wire_and_state_machine_are_strict(self) -> None:
        """Exercise the current central wire/state rules, not just fixture labels."""
        fixture = json.loads((ROOT / "fixtures/deferred_tool.json").read_text(encoding="utf-8"))
        handle = fixture["canonical_cases"][1]["outcome"]["handle"]
        handle_keys = set(handle)
        self.assertEqual(
            handle_keys,
            set(fixture["handle"]["required_fields"]),
        )
        self.assertEqual(
            handle["schema_version"],
            fixture["handle"]["discriminator"]["required_value"],
        )
        self.assertEqual(
            set(handle) - {"schema_version"},
            set(fixture["handle"]["identity_fields"]),
        )
        self.assertRegex(handle["request_digest"], r"^[0-9a-f]{64}$")

        completed = fixture["canonical_cases"][0]["outcome"]
        deferred = fixture["canonical_cases"][1]["outcome"]
        self.assertEqual(set(completed), {"kind", "result"})
        self.assertEqual(set(deferred), {"kind", "handle"})
        self.assertNotIn("result", deferred)
        self.assertNotIn("deferred", fixture["tool_result_status_contract"]["allowed_values"])

        transitions = set(map(tuple, fixture["journal"]["resolution_transitions"]))
        self.assertEqual(transitions, {("deferred", "succeeded"), ("deferred", "failed")})
        cas_writes = fixture["resolution"]["cas"]["write"]
        self.assertTrue(any("receipt" in item for item in cas_writes))
        self.assertTrue(any("outbox" in item for item in cas_writes))
        self.assertTrue(any("barrier" in item for item in cas_writes))

        receipt_fields = set(fixture["resolution"]["receipt_index"]["tombstone_entry_required_fields"])
        self.assertEqual(
            receipt_fields,
            {
                "handle_key",
                "handle",
                "result",
                "result_digest",
                "event_id",
                "event_payload_digest",
                "receipt_status",
            },
        )
        self.assertTrue(fixture["batch"]["admission_cas"]["atomic"])
        self.assertEqual(fixture["batch"]["admission_cas"]["revision_increment"], 1)
        self.assertEqual(fixture["batch"]["example"]["outcomes"], ["deferred", "completed", "deferred"])
        self.assertEqual(fixture["batch"]["example"]["single_claim_release"], True)
        self.assertEqual(
            fixture["events_and_outbox"]["normal_resolution_event_types"],
            ["tool_call_completed"],
        )
        self.assertNotIn("reconciliation_resolved", fixture["events_and_outbox"]["normal_resolution_event_types"])

    def test_deferred_handles_receipts_and_events_use_current_closed_shapes(self) -> None:
        deferred = json.loads((ROOT / "fixtures/deferred_tool.json").read_text(encoding="utf-8"))
        operation_journal = json.loads(
            (ROOT / "fixtures/operation_journal.json").read_text(encoding="utf-8")
        )
        request_vectors = {
            case["name"]: case["sha256"]
            for case in operation_journal["request_digest"]["golden_cases"]
        }
        provenance = deferred["handle"]["request_digest_provenance"]
        self.assertEqual(
            provenance["source_fixture"],
            "operation_journal.json#request_digest.golden_cases",
        )
        provenance_by_operation = {}
        for case in provenance["cases"]:
            self.assertIn(case["request_golden_case"], request_vectors)
            self.assertEqual(case["request_digest"], request_vectors[case["request_golden_case"]])
            provenance_by_operation[case["operation_id"]] = case["request_digest"]
        expected_handle_keys = {
            "schema_version",
            "checkpoint_key",
            "operation_id",
            "attempt",
            "request_digest",
        }

        def assert_handle(value: object) -> None:
            self.assertIsInstance(value, dict)
            handle = value  # type: ignore[assignment]
            self.assertEqual(set(handle), expected_handle_keys)
            self.assertEqual(handle["schema_version"], "vv-agent.deferred-tool-handle.v2")
            self.assertRegex(handle["request_digest"], r"^[0-9a-f]{64}$")
            if "operation_id" in handle:
                self.assertEqual(
                    handle["request_digest"],
                    provenance_by_operation[handle["operation_id"]],
                )

        assert_handle(deferred["canonical_cases"][1]["outcome"]["handle"])
        for batch_handle in deferred["batch"]["example"]["handles"]:
            assert_handle(batch_handle)
        for name in ("canonical_entry", "canonical_failed_entry"):
            receipt = deferred["resolution"]["receipt_index"][name]
            self.assertEqual(
                set(receipt),
                set(deferred["resolution"]["receipt_index"]["tombstone_entry_required_fields"]),
            )
            self.assertRegex(receipt["handle_key"], r"^[0-9a-f]{64}$")
            assert_handle(receipt["handle"])
            handle_key = hashlib.sha256(
                json.dumps(
                    receipt["handle"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(receipt["handle_key"], handle_key)
            self.assertIn(receipt["result"]["status_code"], {"SUCCESS", "ERROR"})
            self.assertRegex(receipt["result_digest"], r"^[0-9a-f]{64}$")
            self.assertRegex(receipt["event_payload_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                receipt["receipt_status"],
                "succeeded" if receipt["result"]["status_code"] == "SUCCESS" else "failed",
            )

        digest_vectors = deferred["resolution"]["receipt_index"]["golden_digest_vectors"]
        for vector in digest_vectors:
            canonical = json.dumps(
                vector["value"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), vector["rfc8785_sha256"])
        by_name = {vector["name"]: vector for vector in digest_vectors}
        self.assertEqual(
            deferred["resolution"]["receipt_index"]["canonical_entry"]["result_digest"],
            by_name["success_result"]["rfc8785_sha256"],
        )
        self.assertEqual(
            deferred["resolution"]["receipt_index"]["canonical_failed_entry"]["result_digest"],
            by_name["failed_result"]["rfc8785_sha256"],
        )
        self.assertEqual(
            deferred["resolution"]["receipt_index"]["canonical_entry"]["event_payload_digest"],
            by_name["success_event_payload"]["rfc8785_sha256"],
        )
        self.assertEqual(
            deferred["resolution"]["receipt_index"]["canonical_failed_entry"]["event_payload_digest"],
            by_name["failed_event_payload"]["rfc8785_sha256"],
        )

        def walk(value: object) -> None:
            if isinstance(value, dict):
                if "deferred_handle" in value:
                    assert_handle(value["deferred_handle"])
                    if "operation_id" in value:
                        self.assertEqual(value["operation_id"], value["deferred_handle"]["operation_id"])
                    if "attempt" in value:
                        self.assertEqual(value["attempt"], value["deferred_handle"]["attempt"])
                    if "request_digest" in value:
                        self.assertEqual(value["request_digest"], value["deferred_handle"]["request_digest"])
                if (
                    isinstance(value.get("handle"), dict)
                    and value["handle"].get("schema_version") == "vv-agent.deferred-tool-handle.v2"
                ):
                    assert_handle(value["handle"])
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)

        for name in ("checkpoint_store.json", "operation_journal.json", "checkpoint_codec.json"):
            walk(json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8")))

        store = json.loads((ROOT / "fixtures" / "checkpoint_store.json").read_text(encoding="utf-8"))
        terminal_replay = next(
            case
            for case in store["deferred_cases"]
            if case["name"] == "terminal_checkpoint_replays_retained_deferred_receipt"
        )
        self.assertEqual(terminal_replay["initial"]["status"], "completed")
        self.assertIn("receipt_index", terminal_replay["initial"])
        self.assertNotIn("deferred_resolution_receipts", terminal_replay["initial"])
        self.assertEqual(terminal_replay["expected"]["decision_kind"], "replayed")
        self.assertTrue(terminal_replay["expected"]["receipt_present"])
        self.assertEqual(terminal_replay["expected"]["revision_increment"], 0)

        event_records = []
        for name in ("run_events.jsonl", "resume_events.jsonl"):
            event_records.extend(
                json.loads(line)
                for line in (ROOT / "fixtures" / name).read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        deferred_events = [record for record in event_records if record["type"] == "tool_call_deferred"]
        self.assertGreaterEqual(len(deferred_events), 2)
        for event in deferred_events:
            assert_handle(event["handle"])
            self.assertEqual(event["operation_id"], event["handle"]["operation_id"])
            self.assertEqual(event["attempt"], event["handle"]["attempt"])
            self.assertTrue(event["execution_started"])
            self.assertIsNone(event["duration_ms"])
            self.assertNotIn("result", event)
        resolved = [
            record
            for record in event_records
            if record["run_id"] == "run_deferred" and record["type"] == "tool_call_completed"
        ]
        self.assertGreaterEqual(len(resolved), 1)
        self.assertEqual(
            {record["event_id"] for record in resolved},
            {"evt_deferred_resolved", "evt_deferred_resolved_1"},
        )
        for record in resolved:
            self.assertTrue(record["execution_started"])
            self.assertIsNone(record["duration_ms"])
        failed_resolved = [
            record
            for record in event_records
            if record["run_id"] == "run_deferred_error" and record["type"] == "tool_call_completed"
        ]
        self.assertEqual(len(failed_resolved), 1)
        self.assertEqual(failed_resolved[0]["status"], "error")
        self.assertEqual(failed_resolved[0]["error_code"], "provider_rejected")

    def test_no_duplicate_deferred_tool_result_status_or_old_reader(self) -> None:
        current_files = [
            *ROOT.glob("docs/*.md"),
            *ROOT.glob("fixtures/*.json"),
            *ROOT.glob("fixtures/*.jsonl"),
            ROOT / "README.md",
            ROOT / "README_ZH.md",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in current_files)
        forbidden = [
            "ToolResultStatus." + "DE" + "FERRED",
            "ToolResultStatus::" + "Deferred",
            "AgentStatus." + "DE" + "FERRED",
            "AgentStatus::" + "Deferred",
            '"' + "DE" + "FERRED" + '"',
            "vv-agent.deferred-tool-handle." + "v1",
            "vv-agent.tool-execution-result." + "v3",
        ]
        for value in forbidden:
            self.assertNotIn(value, text)

    def test_truncated_tool_result_is_preserved_across_all_durable_wires(self) -> None:
        bounded = json.loads(
            (ROOT / "fixtures/bounded_tool_result.json").read_text(encoding="utf-8")
        )
        expected = bounded["canonical_results"]["truncated_bash"]
        expected_bytes = json.dumps(
            expected,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        result_required = {"tool_call_id", "content", "status_code", "directive"}
        optional_fields = set(bounded["result_contract"]["optional_fields"])

        def walk(value: object):
            yield value
            if isinstance(value, dict):
                for nested in value.values():
                    yield from walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from walk(nested)

        for name in (
            "result_public.json",
            "operation_journal.json",
            "checkpoint_codec.json",
            "checkpoint_resume.json",
            "distributed_worker_response.json",
        ):
            fixture = json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))
            values = list(walk(fixture))
            serialized = [
                json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                for value in values
                if isinstance(value, dict)
            ]
            self.assertIn(expected_bytes, serialized, name)
            for value in values:
                if isinstance(value, dict) and result_required.issubset(value):
                    self.assertFalse(
                        any(value.get(field) is None for field in optional_fields if field in value),
                        f"{name}: optional ToolExecutionResult fields must be omitted",
                    )

        journal = json.loads(
            (ROOT / "fixtures/operation_journal.json").read_text(encoding="utf-8")
        )
        recovery = {case["name"]: case for case in journal["recovery_cases"]}
        replay = recovery["durable_truncated_tool_result_is_replayed"]["expected"]
        self.assertEqual(replay["tool_calls"], 0)
        self.assertEqual(replay["artifact_rewrites"], 0)
        self.assertTrue(replay["result_bytes_preserved"])
        request_vectors = {
            case["name"]: case
            for case in journal["request_digest"]["golden_cases"]
        }
        bash_request = request_vectors["tool_bash_large_output"]
        checkpoint = json.loads(
            (ROOT / "fixtures/checkpoint_codec.json").read_text(encoding="utf-8")
        )
        journal_entry = next(
            case["entry"]
            for case in journal["valid_entries"]
            if case["name"] == "tool_succeeded_truncated_bash"
        )
        self.assertEqual(journal_entry["request_digest"], bash_request["sha256"])
        self.assertEqual(journal_entry["tool_call_id"], expected["tool_call_id"])
        self.assertEqual(journal_entry["arguments"], bash_request["request"]["request"]["arguments"])
        committed_result = checkpoint["canonical_checkpoint"]["cycles"][0]["tool_results"][0]
        self.assertEqual(committed_result, expected)

    def test_current_builtin_surface_is_compact_and_has_only_real_exposure(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/builtin_tools.json").read_text(encoding="utf-8")
        )
        tools = {tool["name"]: tool for tool in fixture["tools"]}
        self.assertEqual(fixture["schema_version"], 2)
        self.assertEqual(
            set(tools),
            {
                "task_finish",
                "ask_user",
                "activate_skill",
                "todo_write",
                "find_files",
                "file_info",
                "read_file",
                "write_file",
                "edit_file",
                "search_files",
                "bash",
                "check_background_command",
                "create_sub_task",
                "sub_task_status",
                "read_image",
            },
        )
        self.assertNotIn("compress_memory", tools)
        self.assertEqual({tool["exposure"] for tool in tools.values()}, {"direct"})
        self.assertEqual(
            fixture["exposure_contract"]["allowed_values"],
            ["direct", "hidden"],
        )
        self.assertNotIn("deferred", fixture["exposure_contract"]["allowed_values"])
        behavior = json.loads(
            (ROOT / "fixtures/builtin_tool_behavior.json").read_text(encoding="utf-8")
        )
        bash_non_zero = behavior["tools"]["bash"]["non_zero"]["result"]
        self.assertEqual(bash_non_zero["content"], "fixture-output\n")
        self.assertEqual(bash_non_zero["error_code"], "command_failed")
        self.assertEqual(bash_non_zero["metadata"]["exit_code"], 7)
        self.assertNotIn("output", bash_non_zero["metadata"])
        self.assertEqual(
            behavior["canonical"]["structured_error_content_required_keys"],
            ["ok", "error", "error_code"],
        )
        exposure_cases = {case["value"]: case for case in behavior["registry"]["exposure_cases"]}
        self.assertEqual(
            {value for value, case in exposure_cases.items() if case["valid"]},
            {"direct", "hidden"},
        )
        self.assertFalse(exposure_cases["deferred"]["valid"])
        self.assertTrue(all(len(tool["description"]) < 500 for tool in tools.values()))
        self.assertIn("optional", tools["task_finish"]["description"])
        self.assertIn("cursor", tools["read_file"]["parameters"]["properties"])
        for path in sorted((ROOT / "fixtures").glob("*.json")):
            self.assertNotIn("memory_notes", path.read_text(encoding="utf-8"), path.name)

        public_api = json.loads(
            (ROOT / "fixtures/public_api.json").read_text(encoding="utf-8")
        )
        self.assertEqual(public_api["contract"], "vv-agent-public-api-v4")
        self.assertEqual(public_api["schema_version"], 4)
        capabilities = {
            item["id"]
            for domain in public_api["domains"]
            for item in domain["capabilities"]
        }
        self.assertTrue(
            {
                "agent.prompt_bundle",
                "agent.prompt_section",
                "tools.execution_result",
                "tools.artifact_ref",
                "tools.result_cursor",
            }.issubset(capabilities)
        )
        surfaces = {surface["id"]: surface for surface in public_api["surfaces"]}
        expected_tool_members = {
            "tool_execution_result": {
                "tool_call_id",
                "content",
                "status_code",
                "directive",
                "error_code",
                "metadata",
                "image_url",
                "image_path",
                "truncated",
                "truncation_reason",
                "original_bytes",
                "visible_bytes",
                "artifact",
                "cursor",
            },
            "tool_artifact_ref": {
                "path",
                "media_type",
                "encoding",
                "size_bytes",
                "sha256",
            },
            "tool_result_cursor": {"kind", "path", "offset_chars", "sha256"},
        }
        for surface_id, members in expected_tool_members.items():
            self.assertEqual(
                {member["id"] for member in surfaces[surface_id]["members"]},
                members,
            )
        llm_request = surfaces["llm_request"]
        self.assertIn("prompt_bundle", {member["id"] for member in llm_request["members"]})
        llm_client = surfaces["llm_client"]
        complete = next(member for member in llm_client["members"] if member["id"] == "complete")
        self.assertEqual(
            [parameter["name"] for parameter in complete["python"]["signature"]["parameters"]],
            ["self", "request"],
        )

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
            (ROOT / "fixtures" / "assistant_reasoning_history.json").read_text(
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
            path = fixtures / "model_ref.json"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesRegex(contractctl.ContractError, "fixture digest mismatch"):
                contractctl.parse_manifest(fixtures)

    def test_token_usage_contract_preserves_zero_missing_and_unsupported(self) -> None:
        fixture = json.loads((ROOT / "fixtures/token_usage.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case for case in fixture["normalization_cases"]}

        explicit_zero = cases["openai_cached_explicit_zero"]["expected"]["cache_usage"]
        missing = cases["provider_usage_without_cache_details"]["expected"]["cache_usage"]
        unsupported = cases["adapter_declares_cache_unsupported"]["expected"]["cache_usage"]
        invalid = cases["invalid_cache_numbers_are_not_zero"]["expected"]["cache_usage"]

        self.assertEqual(explicit_zero["status"], "provider_reported")
        self.assertEqual(explicit_zero["read_input_tokens"], 0)
        self.assertEqual(missing["status"], "accounting_missing")
        self.assertIsNone(missing["read_input_tokens"])
        self.assertEqual(unsupported["status"], "unsupported")
        self.assertIsNone(unsupported["read_input_tokens"])
        self.assertEqual(invalid, missing)
        self.assertTrue(
            fixture["model_call_rules"]["provider_usage_captured_before_after_model_hook"]
        )

    def test_token_usage_aggregation_never_exposes_partial_total(self) -> None:
        fixture = json.loads((ROOT / "fixtures/token_usage.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case for case in fixture["aggregation_cases"]}
        task_cases = {case["name"]: case for case in fixture["task_aggregation_cases"]}

        complete = cases["complete_provider_cache_observations"]["expected"]
        partial = cases["partial_observation_is_not_a_partial_total"]["expected"]

        self.assertEqual(complete["read_input_tokens"], 640)
        self.assertEqual(complete["uncached_input_tokens"], 1360)
        self.assertEqual(partial["status"], "accounting_missing")
        self.assertIsNone(partial["read_input_tokens"])
        self.assertIsNone(partial["uncached_input_tokens"])
        empty = task_cases["no_dispatched_calls_are_exact_zero"]["expected"]
        self.assertEqual(
            {empty[name] for name in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens")},
            {0},
        )
        self.assertEqual(empty["cache_usage"]["status"], "accounting_missing")

    def test_task_token_usage_v2_has_strict_negative_cases(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/token_usage.json").read_text(encoding="utf-8")
        )
        rules = fixture["task_usage_rules"]
        cases = {case["name"]: case for case in fixture["invalid_task_wire_cases"]}

        self.assertEqual(rules["schema_version"], "vv-agent.task-token-usage.v2")
        self.assertTrue(rules["unknown_fields_rejected"])
        self.assertTrue(rules["aggregate_fields_must_equal_model_calls"])
        self.assertTrue(rules["duplicate_call_ids_rejected"])
        self.assertEqual(
            set(cases),
            {
                "missing_schema_version",
                "unsupported_schema_version",
                "unknown_field",
                "missing_model_calls",
                "model_calls_not_array",
                "negative_total_tokens",
                "aggregate_does_not_match_model_calls",
                "duplicate_model_call_id",
            },
        )
        unsupported = cases["unsupported_schema_version"]["mutation"]["replace"]
        self.assertNotEqual(unsupported["schema_version"], rules["schema_version"])

        for path in sorted((ROOT / "fixtures").glob("*.json")):
            stack = [json.loads(path.read_text(encoding="utf-8"))]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    if (
                        value.get("schema_version") == "vv-agent.task-token-usage.v2"
                        and "model_calls" in value
                    ):
                        self.assertEqual(set(value), set(rules["required_fields"]), path.name)
                        model_calls = value.get("model_calls")
                        self.assertIsInstance(model_calls, list, path.name)
                        for model_call in model_calls:
                            self.assertEqual(
                                set(model_call),
                                {
                                    "call_id",
                                    "operation_id",
                                    "attempt",
                                    "operation",
                                    "cycle_index",
                                    "backend",
                                    "model",
                                    "status",
                                    "usage",
                                    "error_code",
                                },
                                path.name,
                            )
                        for field in (
                            "input_tokens",
                            "output_tokens",
                            "total_tokens",
                            "reasoning_tokens",
                        ):
                            observations = [call["usage"][field] for call in model_calls]
                            expected = (
                                None
                                if any(observation is None for observation in observations)
                                else sum(observations)
                            )
                            self.assertEqual(value[field], expected, f"{path.name}:{field}")
                        if model_calls == []:
                            self.assertEqual(
                                {
                                    value.get("input_tokens"),
                                    value.get("output_tokens"),
                                    value.get("total_tokens"),
                                    value.get("reasoning_tokens"),
                                },
                                {0},
                                path.name,
                            )
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)

    def test_canonical_usage_projections_use_strict_nested_shape(self) -> None:
        token_keys = {
            "schema_version",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "reasoning_tokens",
            "usage_source",
            "cache_usage",
            "provider_usage",
        }
        task_keys = {
            "schema_version",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "reasoning_tokens",
            "cache_usage",
            "model_calls",
        }
        cache_keys = {
            "status",
            "read_input_tokens",
            "write_input_tokens",
            "uncached_input_tokens",
            "source",
        }

        public_result = json.loads(
            (ROOT / "fixtures/result_public.json").read_text(encoding="utf-8")
        )["agent_result"]
        task_usage = public_result["token_usage"]
        self.assertNotIn("token_usage", public_result["cycles"][0])
        self.assertEqual(set(task_usage), task_keys)
        self.assertEqual(task_usage["schema_version"], "vv-agent.task-token-usage.v2")
        model_call = task_usage["model_calls"][0]
        self.assertEqual(
            set(model_call),
            {
                "call_id",
                "operation_id",
                "attempt",
                "operation",
                "cycle_index",
                "backend",
                "model",
                "status",
                "usage",
                "error_code",
            },
        )
        self.assertEqual(set(model_call["usage"]), token_keys)
        self.assertEqual(set(model_call["usage"]["cache_usage"]), cache_keys)

        journal = json.loads(
            (ROOT / "fixtures/operation_journal.json").read_text(encoding="utf-8")
        )
        model_success = next(
            case for case in journal["valid_entries"] if case["name"] == "model_succeeded"
        )
        self.assertEqual(set(model_success["entry"]["response"]["token_usage"]), token_keys)

        completed_event = json.loads(
            (ROOT / "fixtures/configured_sub_agent_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[1]
        )
        self.assertEqual(set(completed_event["token_usage"]), task_keys)
        self.assertEqual(
            completed_event["token_usage"]["model_calls"][0]["usage"]["usage_source"],
            "accounting_missing",
        )

    def test_public_agent_result_has_one_closed_current_wire(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/result_public.json").read_text(encoding="utf-8")
        )
        wire = fixture["agent_result_wire"]
        required = {
            "status",
            "completion_reason",
            "completion_tool_name",
            "partial_output",
            "messages",
            "cycles",
            "final_answer",
            "wait_reason",
            "error",
            "shared_state",
            "token_usage",
            "checkpoint_key",
            "resume_observation",
        }
        optional = {"budget_usage", "budget_exhaustion", "error_code"}

        self.assertEqual(set(wire["required_fields"]), required)
        self.assertEqual(set(wire["optional_fields"]), optional)
        self.assertTrue(wire["optional_fields_omitted_when_absent"])
        self.assertTrue(wire["optional_fields_reject_null"])
        self.assertEqual(wire["unknown_fields"], "reject")
        self.assertEqual(
            wire["statuses"],
            [
                "pending",
                "running",
                "deferred",
                "reconciliation_required",
                "wait_user",
                "completed",
                "failed",
                "max_cycles",
            ],
        )
        deferred_semantics = wire["deferred_status_semantics"]
        self.assertTrue(deferred_semantics["non_terminal"])
        self.assertEqual(deferred_semantics["wait_reason"], "deferred_pending")
        self.assertEqual(deferred_semantics["turn_status"], "interrupted")
        self.assertIsNone(deferred_semantics["completion_reason"])
        self.assertIsNone(fixture["deferred_pending_result"]["completion_reason"])
        self.assertEqual(fixture["deferred_pending_result"]["wait_reason"], "deferred_pending")
        self.assertEqual(set(fixture["agent_result"]), required)
        self.assertTrue(optional.isdisjoint(fixture["agent_result"]))

        checkpoint_fixture = json.loads(
            (ROOT / "fixtures/checkpoint_codec.json").read_text(encoding="utf-8")
        )
        retained_results: list[dict[str, object]] = []

        def collect_retained_results(value: object) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    if key == "terminal_result" and isinstance(nested, dict):
                        retained_results.append(nested)
                    collect_retained_results(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect_retained_results(nested)

        collect_retained_results(checkpoint_fixture)
        self.assertGreaterEqual(len(retained_results), 2)
        for result in retained_results:
            self.assertEqual(set(result), required)
            self.assertTrue(optional.isdisjoint(result))

    def test_public_api_inventories_token_usage_types(self) -> None:
        fixture = json.loads((ROOT / "fixtures/public_api.json").read_text(encoding="utf-8"))
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
                "result.model_call_operation",
                "result.model_call_status",
                "result.model_call_record",
                "result.task_token_usage",
            }.issubset(capabilities)
        )

    def test_tool_execution_result_has_one_typed_status_field(self) -> None:
        behavior = json.loads(
            (ROOT / "fixtures/builtin_tool_behavior.json").read_text(encoding="utf-8")
        )["tool_execution_result_projection"]
        canonical = behavior["canonical"]

        self.assertEqual(
            behavior["required_fields"],
            ["tool_call_id", "content", "status_code", "directive"],
        )
        self.assertEqual(behavior["unknown_fields"], "reject")
        self.assertEqual(canonical["status_code"], "ERROR")
        self.assertNotIn("status", canonical)

        for fixture_name in (
            "builtin_tool_behavior.json",
            "checkpoint_resume.json",
            "operation_journal.json",
            "result_public.json",
        ):
            root = json.loads((ROOT / "fixtures" / fixture_name).read_text(encoding="utf-8"))
            stack = [root]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    if "status_code" in value:
                        self.assertNotIn("status", value, fixture_name)
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)

    def test_after_cycle_contract_is_closed_task_neutral_and_non_success_only(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/after_cycle_hook.json").read_text(encoding="utf-8")
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
        fixture = json.loads((ROOT / "fixtures/run_budget.json").read_text(encoding="utf-8"))

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

    def test_llm_stream_projection_is_private_typed_and_untrusted(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/llm_stream_projection.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            fixture["schema_version"],
            "vv-agent.llm-stream-projection.v1",
        )
        self.assertEqual(fixture["adapter_boundary"]["visibility"], "private")
        self.assertFalse(fixture["adapter_boundary"]["public_raw_callback"])
        mappings = fixture["mappings"]
        self.assertEqual(
            mappings["assistant_delta"]["required_source_field_alternatives"],
            [["content_delta", "delta"]],
        )
        self.assertEqual(
            [mappings[source]["wire_type"] for source in mappings],
            [
                "assistant_delta",
                "reasoning_delta",
                "model_tool_call_started",
                "model_tool_call_progress",
            ],
        )
        synthetic = fixture["synthetic_top_level"]
        self.assertEqual(
            len(synthetic["expected_wire_events"]),
            synthetic["typed_event_count"],
        )
        self.assertEqual(
            [event["type"] for event in synthetic["expected_wire_events"]],
            [mappings[source]["wire_type"] for source in mappings],
        )
        self.assertEqual(synthetic["provider_payloads"][-1]["event"], "run_completed")
        self.assertEqual(synthetic["dropped_provider_payload_indexes"], [4])
        self.assertNotIn(
            "run_completed",
            {event["type"] for event in synthetic["expected_wire_events"]},
        )
        self.assertEqual(synthetic["execution_event_type"], "tool_call_started")
        self.assertFalse(fixture["public_event_surface"]["raw_runtime_observer"])
        self.assertFalse(fixture["public_event_surface"]["raw_provider_observer"])
        self.assertEqual(fixture["public_event_surface"]["observer_payload"], "RunEvent")
        self.assertEqual(fixture["diagnostic_event"]["wire_type"], "diagnostic")
        self.assertFalse(fixture["diagnostic_event"]["state_authority"])
        self.assertFalse(
            fixture["consumer_policy"]["observer_configuration_changes_runtime_decisions"]
        )

        child = json.loads(
            (ROOT / "fixtures/configured_sub_agent.json").read_text(encoding="utf-8")
        )["stream_forwarding"]
        self.assertFalse(child["raw_callback"])
        self.assertEqual(
            child["provider_adapter_wire_types"],
            {source: mapping["wire_type"] for source, mapping in mappings.items()},
        )
        self.assertTrue(child["same_typed_projection_as_top_level"])

        event_types = {
            json.loads(line)["type"]
            for line in (ROOT / "fixtures/run_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        }
        self.assertTrue(set(child["provider_adapter_wire_types"].values()).issubset(event_types))
        self.assertIn("diagnostic", event_types)
        invalid = json.loads(
            (ROOT / "fixtures/run_events_invalid.json").read_text(encoding="utf-8")
        )
        rejected = {case["id"] for case in invalid["reject"]}
        self.assertTrue(
            {
                "reasoning_delta_is_not_a_string",
                "model_tool_call_id_is_empty",
                "model_tool_name_is_empty",
                "stream_counter_is_negative",
                "stream_counter_exceeds_json_safe_maximum",
                "diagnostic_level_is_unknown",
                "diagnostic_code_is_empty",
                "diagnostic_details_is_not_an_object",
            }.issubset(rejected)
        )

    def test_tool_metadata_contract_is_closed_task_neutral_and_observable(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/tool_metadata.json").read_text(encoding="utf-8")
        )

        self.assertEqual(fixture["schema_version"], "vv-agent.tool-metadata.v3")
        metadata = fixture["metadata_contract"]
        self.assertEqual(
            metadata["closed_fields"],
            [
                "side_effect",
                "idempotency",
                "terminal",
                "result_retention",
                "capability_tags",
                "cost_dimensions",
            ],
        )
        self.assertEqual(metadata["defaults"]["result_retention"], "archive")
        self.assertEqual(metadata["result_retention_values"], ["archive", "preserve"])
        self.assertTrue(metadata["result_retention_is_not_inferred"])
        self.assertFalse(metadata["model_visible"])
        self.assertTrue(metadata["generic_metadata_is_not_a_declaration"])
        self.assertTrue(metadata["absent_metadata_uses_neutral_defaults"])
        self.assertEqual(
            fixture["collection_normalization"]["portable_whitespace_code_points"],
            ["U+0009", "U+000A", "U+000D", "U+0020"],
        )

        normalized = fixture["normalization_cases"][0]["expected"]
        self.assertEqual(normalized["capability_tags"], ["filesystem.read", "source.inspect"])
        self.assertEqual(
            normalized["cost_dimensions"],
            ["host.cpu_ms", "workspace.bytes_read"],
        )
        invalid_names = {case["name"] for case in fixture["invalid_cases"]}
        self.assertIn("unknown_field", invalid_names)
        self.assertIn("unknown_result_retention", invalid_names)
        self.assertTrue(
            fixture["telemetry_contract"]["missing_required_completed_fields_are_rejected"]
        )
        self.assertTrue(fixture["public_construction"]["generic_metadata_remains_separate"])

        policy = fixture["policy_contract"]
        self.assertFalse(policy["can_expand_permissions"])
        self.assertFalse(policy["can_infer_from_tool_name_or_arguments"])
        self.assertEqual(policy["list_merge"], "set_union_then_utf16_sort")
        self.assertIn("parent_effective_policy", policy["layers"])
        self.assertEqual(policy["enforcement_points"], ["schema_planner", "executor"])
        policy_cases = {case["name"]: case for case in fixture["policy_cases"]}
        self.assertTrue(policy_cases["missing_metadata_preserves_behavior"]["allowed"])
        self.assertFalse(policy_cases["declared_side_effect_is_denied"]["allowed"])

        telemetry = fixture["telemetry_contract"]
        self.assertEqual(
            telemetry["event_order"],
            [
                "tool_call_planned",
                "approval_if_required",
                "tool_call_started_if_execution_begins",
                "tool_call_deferred_when_admission_is_durable",
                "tool_call_completed_when_a_result_exists",
            ],
        )
        self.assertFalse(telemetry["telemetry_changes_runtime_decisions"])
        producer_cases = {case["name"]: case for case in fixture["producer_cases"]}
        self.assertEqual(
            producer_cases["metadata_policy_denial_has_no_execution_start"][
                "expected_event_types"
            ],
            ["tool_call_planned", "tool_call_completed"],
        )
        self.assertEqual(fixture["app_server_projection"]["tool_call_planned"], "no_notification")
        self.assertTrue(fixture["checkpoint"]["policy_fields_are_frozen"])
        self.assertFalse(
            fixture["task_independence"]["terminal_declaration_automatically_finishes"]
        )
        self.assertEqual(
            fixture["telemetry_contract"]["completed_status_values"],
            ["success", "error", "wait_response", "running", "pending_compress"],
        )
        self.assertTrue(fixture["telemetry_contract"]["completed_never_accepts_deferred"])

        event_types = {
            json.loads(line)["type"]
            for line in (ROOT / "fixtures/run_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        }
        self.assertIn("tool_call_planned", event_types)
        invalid_events = json.loads(
            (ROOT / "fixtures/run_events_invalid.json").read_text(encoding="utf-8")
        )
        rejected = {case["id"] for case in invalid_events["reject"]}
        self.assertTrue(
            {
                "planned_arguments_are_not_an_object",
                "tool_metadata_has_unknown_field",
                "tool_completed_directive_is_unknown",
                "tool_completed_execution_started_is_not_boolean",
                "tool_completed_duration_is_negative",
                "tool_completed_not_started_cannot_have_duration",
                "deferred_event_handle_missing_discriminator",
                "deferred_event_handle_unknown_field",
                "deferred_event_cross_process_duration_must_be_null",
            }.issubset(rejected)
        )

    def test_output_validation_contract_is_opt_in_tools_free_and_bounded(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/output_validation.json").read_text(encoding="utf-8")
        )

        self.assertEqual(fixture["schema_version"], "vv-agent.output-validation.v1")
        self.assertFalse(fixture["defaults"]["enabled"])
        self.assertEqual(fixture["defaults"]["max_repairs"], 1)
        self.assertTrue(fixture["repair"]["tools_are_always_empty"])
        self.assertTrue(fixture["repair"]["model_and_settings_are_independent_from_primary_run"])
        self.assertTrue(fixture["repair"]["framework_does_not_classify_task_or_rewrite_business_answer"])
        self.assertEqual(fixture["repair"]["maximum_attempts"], 1)
        self.assertTrue(fixture["terminal_rules"]["disabled_preserves_trace_and_terminal_observation"])
        self.assertTrue(fixture["terminal_rules"]["repair_success_revalidates_before_success"])

        cases = {case["name"]: case for case in fixture["runner_cases"]}
        self.assertEqual(cases["disabled"]["expected"]["validator_calls"], 0)
        self.assertEqual(cases["one_repair_then_valid"]["expected"]["repair_calls"], 1)
        self.assertFalse(cases["repair_result_still_invalid"]["expected"]["second_repair_attempted"])
        self.assertEqual(
            cases["repair_provider_failure"]["expected"]["error_code"],
            "output_validation_failed",
        )
        self.assertIn("task_category", fixture["task_independence"]["forbidden_framework_fields"])
        self.assertTrue(fixture["task_independence"]["prompt_and_tool_schema_unchanged"])

    def test_metadata_denials_propagate_to_children_and_distributed_workers(self) -> None:
        child_fixture = json.loads(
            (ROOT / "fixtures/configured_sub_agent.json").read_text(encoding="utf-8")
        )
        child = child_fixture["tool_policy_projection"]
        public_child = json.loads(
            (ROOT / "fixtures/public_configured_sub_agent.json").read_text(encoding="utf-8")
        )
        handoff = json.loads(
            (ROOT / "fixtures/handoff_contract.json").read_text(encoding="utf-8")
        )["tool_policy_projection"]
        distributed = json.loads(
            (ROOT / "fixtures/distributed_run_envelope.json").read_text(encoding="utf-8")
        )

        for field in (
            "denied_side_effects",
            "denied_capability_tags",
            "deny_terminal_tools",
            "denied_cost_dimensions",
        ):
            self.assertIn(field, child["inherited"])
        self.assertEqual(
            {
                field: child_fixture["validation"]["wire_defaults"][field]
                for field in (
                    "denied_side_effects",
                    "denied_capability_tags",
                    "deny_terminal_tools",
                    "denied_cost_dimensions",
                )
            },
            {
                "denied_side_effects": [],
                "denied_capability_tags": [],
                "deny_terminal_tools": False,
                "denied_cost_dimensions": [],
            },
        )
        researcher = public_child["normalization"]["raw_entries"][0]["config"]
        self.assertEqual(
            child["metadata_denial_merge_case"]["child"],
            {
                field: researcher[field]
                for field in (
                    "denied_side_effects",
                    "denied_capability_tags",
                    "deny_terminal_tools",
                    "denied_cost_dimensions",
                )
            },
        )
        self.assertEqual(
            public_child["normalization"]["retained_researcher_config"],
            researcher,
        )
        self.assertEqual(
            child["metadata_denial_merge_case"]["enforced_at"],
            ["schema_planner", "executor"],
        )
        self.assertTrue(handoff["target_inherits_source_effective_metadata_denials"])
        drift = {case["name"]: case for case in distributed["capability_resolution_cases"]}
        mismatch = drift["tool_metadata_drift_fails_before_claim"]
        self.assertTrue(mismatch["model_visible_schema_digest_unchanged"])
        self.assertEqual(mismatch["expected"]["error_code"], "checkpoint_definition_mismatch")
        self.assertEqual(mismatch["expected"]["claim_count"], 0)

    def test_app_server_tool_lifecycle_projection_is_fully_frozen(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/app_server_observable.json").read_text(encoding="utf-8")
        )["toolLifecycle"]

        planned = fixture["plannedHasNoNotification"]
        self.assertEqual(planned["notifications"], [])
        self.assertIsNone(planned["persistedItem"])
        self.assertTrue(planned["argumentsAvailableToApprovalRouting"])
        self.assertFalse(planned["presentedAsExecution"])

        started = fixture["executed"]["startedNotifications"]
        completed = fixture["executed"]["completedNotifications"]
        self.assertEqual([item["method"] for item in started], ["item/started", "item/toolCall/delta"])
        payload = completed[0]["params"]["payload"]
        self.assertEqual(payload["directive"], "continue")
        self.assertIsNone(payload["errorCode"])
        self.assertTrue(payload["executionStarted"])
        self.assertEqual(payload["durationMs"], 7)
        self.assertEqual(payload["toolMetadata"]["sideEffect"], "read")

        denial = fixture["policyDenial"]
        self.assertEqual(denial["startedNotifications"], [])
        denial_payload = denial["completedNotifications"][0]["params"]["payload"]
        self.assertFalse(denial_payload["executionStarted"])
        self.assertIsNone(denial_payload["durationMs"])
        self.assertEqual(denial_payload["errorCode"], "tool_not_allowed")

    def test_app_server_model_lifecycle_and_task_usage_v2_are_frozen(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/app_server_observable.json").read_text(encoding="utf-8")
        )
        lifecycle = fixture["modelLifecycle"]
        identity_fields = set(lifecycle["identityFields"])

        self.assertEqual(lifecycle["itemType"], "modelCall")
        started = lifecycle["startedNotifications"][0]
        completed = lifecycle["completedNotifications"][0]
        failed = lifecycle["failedNotifications"][0]
        self.assertEqual(started["method"], "item/started")
        self.assertEqual(completed["method"], "item/completed")
        self.assertEqual(failed["method"], "item/completed")
        for notification in (started, completed, failed):
            params = notification["params"]
            self.assertEqual(params["type"], "modelCall")
            self.assertTrue(identity_fields.issubset(params["payload"]))
            self.assertTrue(
                set(lifecycle["forbiddenPayloadFields"]).isdisjoint(params["payload"])
            )
        self.assertEqual(
            completed["params"]["payload"]["usage"]["schemaVersion"],
            "vv-agent.token-usage.v1",
        )
        self.assertEqual(failed["params"]["payload"]["outcome"], "definitive")
        self.assertEqual(failed["params"]["payload"]["errorCode"], "provider_rejected")

        projection = fixture["terminal"]["tokenUsageProjection"]
        value = projection["value"]
        self.assertEqual(projection["sourceSchemaVersion"], "vv-agent.task-token-usage.v2")
        self.assertEqual(value["schemaVersion"], "vv-agent.task-token-usage.v2")
        self.assertEqual(len(value["modelCalls"]), 1)
        self.assertEqual(value["modelCalls"][0]["usage"]["schemaVersion"], "vv-agent.token-usage.v1")
        provider_usage = value["modelCalls"][0]["usage"]["providerUsage"]
        self.assertIn("prompt_tokens", provider_usage)
        self.assertNotIn("promptTokens", provider_usage)

    def test_run_budget_runner_cases_are_executable_inputs_not_boolean_claims(self) -> None:
        fixture = json.loads((ROOT / "fixtures/run_budget.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case for case in fixture["runner_cases"]}

        required = {
            "no_limits_uses_normal_terminal_flow",
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
            for line in (ROOT / "fixtures/budget_events.jsonl").read_text(encoding="utf-8").splitlines()
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
        distributed = json.loads(
            (ROOT / "fixtures/distributed_run_envelope.json").read_text(encoding="utf-8")
        )
        envelope = distributed["canonical_envelope"]
        checkpoint = json.loads(
            (ROOT / "fixtures/checkpoint_codec.json").read_text(encoding="utf-8")
        )
        public_api = json.loads(
            (ROOT / "fixtures/public_api.json").read_text(encoding="utf-8")
        )

        self.assertEqual(envelope["budget_limits"]["max_total_tokens"], 5000)
        self.assertEqual(
            envelope["recipe"]["capabilities"]["host_cost_meter_ref"],
            {"id": "cost.tenant-run", "version": "1"},
        )
        self.assertEqual(checkpoint["canonical_checkpoint"]["budget_usage"]["elapsed_ms"], 125)
        task = envelope["task"]
        self.assertIn("prompt_bundle", task)
        self.assertNotIn("system_prompt", task)
        agent_task_surface = next(
            surface for surface in public_api["surfaces"] if surface["id"] == "agent_task"
        )
        self.assertTrue(
            {member["id"] for member in agent_task_surface["members"]}.issubset(task)
        )
        self.assertEqual(
            task["prompt_bundle"]["sections"],
            [
                {
                    "id": "agent_instructions",
                    "text": "system",
                    "stable": True,
                    "source": "agent.instructions",
                }
            ],
        )
        self.assertEqual(len(task["prompt_bundle"]["stable_hash"]), 64)

    def test_completion_policy_is_task_agnostic(self) -> None:
        fixture = json.loads((ROOT / "fixtures/completion_policy.json").read_text(encoding="utf-8"))

        self.assertEqual(fixture["policy_values"], ["continue", "wait_user", "finish"])
        self.assertEqual(fixture["framework_default"], "continue")
        self.assertEqual(
            fixture["precedence"],
            ["run_config", "runner_default_run_config", "agent", "framework_default"],
        )
        self.assertTrue(fixture["rules"]["assistant_text_is_not_classified"])
        self.assertTrue(fixture["rules"]["completion_policy_does_not_change_tool_availability"])
        self.assertTrue(fixture["rules"]["budget_exhausted_is_defined_by_run_budget"])
        self.assertTrue(fixture["rules"]["approval_resume_uses_fresh_cycle_budget"])
        self.assertTrue(fixture["rules"]["approval_resume_preserves_resource_budget"])
        self.assertTrue(fixture["rules"]["approved_resume_rejects_input_before_claim"])
        self.assertTrue(fixture["rules"]["pre_cancelled_approval_resume_skips_side_effects"])
        self.assertTrue(fixture["rules"]["guardrail_allow_preserves_completion_observation"])
        self.assertTrue(fixture["rules"]["ordinary_llm_failure_is_typed_terminal"])

    def test_distributed_lease_lifecycle_closes_side_effect_windows(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/distributed_run_envelope.json").read_text(encoding="utf-8")
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
        fixture = json.loads((ROOT / "fixtures/completion_policy.json").read_text(encoding="utf-8"))
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
        fixture = json.loads((ROOT / "fixtures/completion_policy.json").read_text(encoding="utf-8"))
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
        budget_fixture = json.loads((ROOT / "fixtures/run_budget.json").read_text(encoding="utf-8"))
        budget_reasons = {case["expected"]["completion_reason"] for case in budget_fixture["runner_cases"]}
        self.assertIn("budget_exhausted", budget_reasons)

    def test_public_api_inventories_completion_controls_and_observation(self) -> None:
        fixture = json.loads((ROOT / "fixtures/public_api.json").read_text(encoding="utf-8"))
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
        self.assertEqual(len(capabilities), 169)
        self.assertIn("tools.message", capabilities)
        self.assertNotIn("runtime_backend.cycle_runner", capabilities)
        self.assertIn("agent.sub_agent_config", capabilities)
        self.assertIn("checkpoint_config.capability_refs", capabilities)
        self.assertIn("checkpoint_config.credential_slots", capabilities)
        self.assertIn("tools.context_defer", capabilities)

        surfaces = {surface["id"]: surface for surface in fixture["surfaces"]}
        surface_member_count = sum(
            len(surface.get("members", []))
            + len(surface.get("protocol_operations", []))
            + len(surface.get("supporting_operations", []))
            for surface in fixture["surfaces"]
        )
        self.assertEqual(surface_member_count, 306)
        self.assertIn("no_tool_policy", {member["id"] for member in surfaces["agent"]["members"]})
        self.assertIn("no_tool_policy", {member["id"] for member in surfaces["run_config"]["members"]})
        self.assertIn("session_memory_enabled", {member["id"] for member in surfaces["run_config"]["members"]})
        self.assertIn(
            "microcompaction_policy",
            {member["id"] for member in surfaces["run_config"]["members"]},
        )
        self.assertIn(
            "microcompaction_policy",
            {member["id"] for member in surfaces["agent_task"]["members"]},
        )
        self.assertEqual(
            {member["id"] for member in surfaces["microcompaction_policy"]["members"]},
            {
                "trigger_ratio",
                "target_ratio",
                "keep_recent_cycles",
                "min_result_chars",
            },
        )
        self.assertEqual(
            {member["id"] for member in surfaces["message"]["members"]},
            {
                "role",
                "content",
                "name",
                "tool_call_id",
                "tool_calls",
                "reasoning_content",
                "image_url",
                "metadata",
                "artifact_ref",
            },
        )
        self.assertIn(
            "session_memory_enabled",
            {member["id"] for member in surfaces["sub_agent_config"]["members"]},
        )
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
            {"settings_file", "default_backend", "llm_builder", "timeout_seconds"}.isdisjoint(
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
        self.assertIn("tool_metadata", {member["id"] for member in surfaces["tool"]["members"]})
        self.assertEqual(
            {member["id"] for member in surfaces["tool_metadata"]["members"]},
            {
                "side_effect",
                "idempotency",
                "terminal",
                "result_retention",
                "capability_tags",
                "cost_dimensions",
            },
        )
        self.assertEqual(
            {member["id"] for member in surfaces["tool_policy"]["members"]},
            {
                "allowed_tools",
                "disallowed_tools",
                "approval",
                "can_use_tool",
                "denied_side_effects",
                "denied_capability_tags",
                "deny_terminal_tools",
                "denied_cost_dimensions",
            },
        )
        self.assertEqual(
            {member["id"] for member in surfaces["sub_agent_config"]["members"]},
            {
                "model",
                "description",
                "backend",
                "system_prompt",
                "max_cycles",
                "session_memory_enabled",
                "exclude_tools",
                "metadata",
                "denied_side_effects",
                "denied_capability_tags",
                "deny_terminal_tools",
                "denied_cost_dimensions",
            },
        )

    def test_manager_outcomes_preserve_completion_observation(self) -> None:
        fixture = json.loads((ROOT / "fixtures/manager_tool_envelope.json").read_text(encoding="utf-8"))

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
        invalid = json.loads((ROOT / "fixtures/run_events_invalid.json").read_text(encoding="utf-8"))
        rejected = {case["id"] for case in invalid["reject"]}
        self.assertNotIn("canonicalize", invalid)
        self.assertEqual(invalid["rules"]["unknown_top_level_fields"], "reject")
        self.assertTrue(
            {
                "approval_approved_field_is_rejected",
                "approval_action_is_missing",
                "approval_action_is_unknown",
                "legacy_llm_started_is_rejected",
                "unknown_completion_reason",
                "completion_reason_is_not_a_string_or_null",
                "completion_tool_name_is_not_a_string_or_null",
                "partial_output_is_not_a_string_or_null",
                "budget_usage_is_not_an_object_or_null",
                "budget_exhaustion_unknown_dimension",
            }.issubset(rejected)
        )

        app_server = json.loads(
            (ROOT / "fixtures/app_server_observable.json").read_text(encoding="utf-8")
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
        fixture = json.loads((ROOT / "fixtures/public_api.json").read_text(encoding="utf-8"))

        properties = [
            member["python"]
            for surface in fixture["surfaces"]
            for group in ("members", "protocol_operations", "supporting_operations")
            for member in surface.get(group, [])
            if member["python"]["kind"] == "property"
        ]
        self.assertTrue(properties)
        self.assertTrue(all("signature" in property_member for property_member in properties))

    def test_public_api_deferred_methods_define_factory_and_resolution_contracts(self) -> None:
        fixture = json.loads((ROOT / "fixtures/public_api.json").read_text(encoding="utf-8"))
        surfaces = {surface["id"]: surface for surface in fixture["surfaces"]}
        context = next(surface for surface in surfaces.values() if surface["id"] == "tool_context")
        defer = context["members"][0]
        self.assertEqual(defer["id"], "defer")
        self.assertEqual(defer["python"]["signature"]["return"], "ToolCallOutcome.Deferred")
        self.assertTrue(defer["requires_durable_checkpoint"])
        self.assertTrue(defer["without_checkpoint"]["before_external_side_effect"])
        self.assertIn("normal local tools", defer["ordinary_outcome_without_checkpoint"])
        self.assertEqual(defer["errors"], ["deferred_requires_checkpoint"])

        runtime = next(domain for domain in fixture["domains"] if domain["id"] == "runtime_backend")
        resolve = next(
            capability
            for capability in runtime["capabilities"]
            if capability["id"] == "runtime_backend.resolve_deferred"
        )
        self.assertEqual(resolve["signature"], "resolve_deferred(handle, result)")
        self.assertEqual(resolve["return"], "DeferredResolveDecision")
        variants = resolve["closed_return_variants"]["variants"]
        self.assertEqual(set(variants), {
            "applied_ready",
            "applied_waiting",
            "replayed",
            "not_admitted",
            "reconciliation_required",
        })
        for name in ("applied_ready", "applied_waiting", "replayed"):
            self.assertIn("receipt", variants[name]["required"])
        self.assertIn("receipt", variants["not_admitted"]["forbidden"])
        self.assertIn("receipt", variants["reconciliation_required"]["forbidden"])
        self.assertEqual(resolve["decision_error_codes"], ["deferred_resolution_not_admitted"])
        self.assertEqual(resolve["retryable_decision_error_codes"], ["deferred_resolution_not_admitted"])
        self.assertEqual(
            resolve["errors"],
            [
                "deferred_resolution_conflict",
                "deferred_resolution_stale",
                "deferred_resolution_result_invalid",
            ],
        )

    def test_checkpoint_config_uses_real_keys_and_explicit_stores(self) -> None:
        fixture = json.loads((ROOT / "fixtures/checkpoint_config.json").read_text(encoding="utf-8"))
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
        fixture = json.loads((ROOT / "fixtures/run_definition.json").read_text(encoding="utf-8"))

        self.assertEqual(
            fixture["canonicalization"]["algorithm"],
            "RFC 8785 JSON Canonicalization Scheme",
        )
        self.assertEqual(len(fixture["golden_cases"]), 3)
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
        self.assertEqual(
            full["prompt_bundle"]["sections"][0]["text"],
            "Use tools carefully.\nDo not guess.",
        )
        self.assertEqual(len(full["prompt_bundle"]["stable_hash"]), 64)
        self.assertNotIn("compiled_prompt", full)
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
        self.assertEqual(full["tools"][0]["tool_metadata"]["side_effect"], "write")
        self.assertNotIn("tool_metadata", full["tools"][0]["schema"])
        self.assertEqual(
            full["tool_policy"]["denied_capability_tags"],
            sorted(
                full["tool_policy"]["denied_capability_tags"],
                key=lambda value: value.encode("utf-16-be"),
            ),
        )
        self.assertEqual(
            fixture["golden_cases"][0]["definition"]["tool_policy"][
                "denied_side_effects"
            ],
            [],
        )
        self.assertEqual(
            fixture["golden_cases"][0]["definition"]["runtime_controls"][
                "microcompaction_policy"
            ],
            {
                "trigger_ratio": 0.75,
                "target_ratio": 0.6,
                "keep_recent_cycles": 3,
                "min_result_chars": 500,
            },
        )
        self.assertTrue(
            all(field in fixture["golden_cases"][0]["definition"] for field in fixture["required_fields"])
        )
        self.assertTrue(fixture["top_level_field_policy"]["closed"])
        for case in fixture["golden_cases"]:
            self.assertEqual(set(case["definition"]), set(fixture["required_fields"]))
        nested_policy = fixture["nested_field_policy"]
        self.assertEqual(
            nested_policy["rule"],
            "Unknown fields are rejected in every closed object. Open maps accept application, provider, or JSON Schema keys only at the listed path.",
        )
        self.assertTrue(
            {
                "/agent",
                "/prompt_bundle",
                "/prompt_bundle/sections/*",
                "/model",
                "/model/settings",
                "/runtime_controls",
                "/runtime_controls/microcompaction_policy",
                "/tools/*",
                "/tools/*/schema",
                "/tools/*/schema/function",
                "/tools/*/tool_metadata",
                "/tools/*/approval",
                "/tool_policy",
                "/checkpoint_policy",
                "/budget_limits",
                "/budget_limits/max_host_cost",
                "/extensions/*",
                "/capability_refs/*",
            }.issubset(nested_policy["closed_objects"])
        )
        self.assertTrue(
            {
                "/initial_shared_state",
                "/run_metadata",
                "/model/settings/extra_body",
                "/tools/*/schema/function/parameters",
                "/output_schema",
            }.issubset(nested_policy["open_maps"])
        )
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
        invalid_names = {case["name"] for case in fixture["invalid_cases"]}
        self.assertTrue(
            {
                "agent_unknown_field",
                "agent_missing_name",
                "initial_message_unknown_field",
                "initial_message_missing_content",
                "model_unknown_field",
                "model_missing_backend",
                "model_settings_unknown_field",
                "model_retry_unknown_field",
                "runtime_controls_unknown_field",
                "runtime_controls_missing_max_cycles",
                "runtime_controls_missing_microcompaction_policy",
                "microcompaction_policy_unknown_field",
                "microcompaction_policy_target_not_below_trigger",
                "microcompaction_policy_zero_min_result_chars",
                "tool_unknown_field",
                "tool_missing_approval",
                "tool_schema_unknown_field",
                "tool_function_unknown_field",
                "tool_metadata_unknown_field",
                "tool_approval_unknown_field",
                "tool_policy_unknown_field",
                "tool_policy_missing_allowed_tools",
                "checkpoint_policy_unknown_field",
                "checkpoint_policy_missing_ambiguous_model_policy",
                "budget_limits_unknown_field",
                "budget_limits_missing_max_total_tokens",
                "host_cost_unknown_field",
                "host_cost_missing_currency",
                "extension_unknown_field",
                "extension_missing_version",
                "capability_ref_unknown_field",
                "capability_ref_missing_version",
                "legacy_compiled_prompt_field",
                "prompt_bundle_missing_sections",
                "prompt_bundle_empty_sections",
                "prompt_bundle_unknown_field",
                "prompt_section_missing_stable",
                "prompt_section_unknown_field",
                "prompt_section_duplicate_id",
                "prompt_bundle_stable_hash_mismatch",
            }.issubset(invalid_names)
        )

    def test_rfc8785_vectors_match_ecmascript_reference_serialization(self) -> None:
        subprocess.run(
            ["node", str(ROOT / "scripts/verify_jcs.mjs")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_checkpoint_is_strict_and_extensions_are_explicit(self) -> None:
        fixture = json.loads((ROOT / "fixtures/checkpoint_codec.json").read_text(encoding="utf-8"))
        canonical = fixture["canonical_checkpoint"]
        run_definition_fixture = json.loads(
            (ROOT / "fixtures/run_definition.json").read_text(encoding="utf-8")
        )
        minimal_definition = run_definition_fixture["golden_cases"][0]

        self.assertEqual(canonical["schema_version"], "vv-agent.checkpoint.v7")
        self.assertEqual(canonical["run_definition_schema"], "vv-agent.run-definition.v5")
        self.assertEqual(canonical["run_definition"], minimal_definition["definition"])
        self.assertEqual(canonical["run_definition_digest"], minimal_definition["sha256"])
        self.assertNotIn("deferred_resolution_receipts", fixture["required_fields"])
        self.assertNotIn("deferred_resolution_receipts", canonical)
        self.assertTrue(fixture["deferred_receipt_index"]["independent"])
        self.assertFalse(fixture["deferred_receipt_index"]["bounded"])
        self.assertTrue(fixture["deferred_receipt_index"]["same_store_transaction"])
        self.assertEqual(canonical["claimed_cycle"], canonical["cycle_index"] + 1)
        for journal_name in ("model_call_journal", "tool_journal"):
            for entry in canonical[journal_name]:
                self.assertEqual(entry["cycle_index"], canonical["claimed_cycle"])
        self.assertEqual(len(canonical["run_definition_digest"]), 64)
        self.assertEqual(
            fixture["discriminator"],
            {
                "required_value": "vv-agent.checkpoint.v7",
                "missing_or_unknown_error": "checkpoint_schema_unsupported",
            },
        )
        self.assertEqual(
            fixture["run_definition_schema_rules"],
            {
                "required_value": "vv-agent.run-definition.v5",
                "missing_or_unknown_error": "checkpoint_definition_schema_unsupported",
                "failure_boundary": "before_claim_model_or_tool",
            },
        )
        self.assertEqual(fixture["unknown_field_policy"]["top_level_whole_object_store"], "reject")
        self.assertEqual(fixture["unknown_field_policy"]["extension_required"], "block_resume")
        self.assertIn(
            "unknown_top_level_is_rejected",
            {case["name"] for case in fixture["invalid_cases"]},
        )
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
        self.assertTrue(fixture["status_rules"]["model_call_ids_are_unique"])
        self.assertTrue(fixture["status_rules"]["model_journal_records_actual_backend_and_model"])
        self.assertEqual(
            fixture["status_rules"]["model_journal_event_and_ledger_identity_fields_match_exactly"],
            [
                "call_id",
                "operation_id",
                "attempt",
                "operation",
                "cycle_index",
                "backend",
                "model",
            ],
        )
        self.assertTrue(fixture["status_rules"]["model_started_journal_and_started_event_are_atomic"])
        self.assertTrue(
            fixture["status_rules"][
                "ambiguous_model_journal_attempt_has_exactly_one_ambiguous_model_call_record"
            ]
        )
        active_journal = canonical["model_call_journal"][0]
        started_event = canonical["event_outbox"][0]["event"]
        self.assertEqual(active_journal["backend"], "test")
        self.assertEqual(active_journal["model"], "test-model")
        for field in ("call_id", "operation_id", "attempt", "cycle_index", "backend", "model"):
            self.assertEqual(active_journal[field], started_event[field])
        self.assertEqual(active_journal["model_operation"], started_event["operation"])
        self.assertTrue(
            fixture["status_rules"]
            ["terminal_model_event_precedes_budget_observation_in_outbox"]
        )
        self.assertTrue(
            fixture["status_rules"]
            ["terminal_result_task_usage_model_calls_equal_checkpoint_ledger"]
        )
        for case in [*fixture["valid_cases"], *fixture["invalid_cases"]]:
            payload = case["payload"]
            terminal_result = payload.get("terminal_result")
            if terminal_result is not None:
                self.assertEqual(
                    terminal_result["token_usage"]["model_calls"],
                    payload["model_calls"],
                    case["name"],
                )
        self.assertEqual(canonical["model_calls"][0]["operation"], "agent_cycle")
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
        codec_deferred_cases = {case["name"]: case for case in fixture["deferred_cases"]}
        self.assertEqual(
            codec_deferred_cases["resolved_last_deferred_returns_to_running"]["expected"]["resolution_decision"],
            "applied_ready",
        )
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
        unknown_definition_schema = next(
            case
            for case in definition_schema_cases
            if case["name"] == "unknown_definition_schema_fails_closed"
        )["mutation"]["replace"]["run_definition_schema"]
        self.assertNotEqual(
            unknown_definition_schema,
            fixture["run_definition_schema_rules"]["required_value"],
        )
        unknown_embedded_schema = next(
            case
            for case in run_definition_fixture["invalid_cases"]
            if case["name"] == "unknown_schema"
        )["mutation"]["value"]
        self.assertNotEqual(
            unknown_embedded_schema,
            run_definition_fixture["schema_version"],
        )
        unknown_checkpoint_schema = next(
            case["payload"]["schema_version"]
            for case in fixture["invalid_cases"]
            if case["name"] == "unknown_schema"
        )
        self.assertNotEqual(
            unknown_checkpoint_schema,
            fixture["discriminator"]["required_value"],
        )
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
        fixture = json.loads((ROOT / "fixtures/operation_journal.json").read_text(encoding="utf-8"))
        recovery = {case["name"]: case for case in fixture["recovery_cases"]}
        request_vectors = {
            case["name"]: case for case in fixture["request_digest"]["golden_cases"]
        }

        self.assertEqual(
            fixture["enums"]["states"],
            ["planned", "started", "deferred", "succeeded", "failed", "ambiguous"],
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
        model_entries = [
            case["entry"]
            for case in valid_entries.values()
            if case["entry"]["kind"] == "model"
        ]
        self.assertTrue(model_entries)
        self.assertTrue(
            all(entry["backend"] == "test" and entry["model"] == "test-model" for entry in model_entries)
        )

        accounting = fixture["model_call_accounting"]
        identity = accounting["identity_contract"]
        self.assertEqual(
            identity["fields"],
            [
                "call_id",
                "operation_id",
                "attempt",
                "operation",
                "cycle_index",
                "backend",
                "model",
            ],
        )
        completed = accounting["completed_attempt"]
        journal_identity = dict(completed["journal"])
        journal_identity["operation"] = journal_identity.pop("model_operation")
        for record_name in ("started_event", "ledger", "terminal_event"):
            record = completed[record_name]
            for field in identity["fields"]:
                self.assertEqual(record[field], journal_identity[field], record_name)
        self.assertNotEqual(
            {
                "backend": completed["journal"]["backend"],
                "model": completed["journal"]["model"],
            },
            completed["root_run_definition_model"],
        )
        self.assertEqual(
            {case["name"] for case in accounting["invalid_identity_cases"]},
            {
                "call_id_mismatch",
                "operation_id_mismatch",
                "attempt_mismatch",
                "operation_mismatch",
                "cycle_index_mismatch",
                "backend_mismatch",
                "model_mismatch",
                "journal_backend_missing",
                "journal_model_missing",
            },
        )
        atomic_cases = {case["name"]: case for case in accounting["atomic_outbox_cases"]}
        self.assertEqual(
            atomic_cases["terminal_with_budget_snapshot"]["appended_event_types"],
            ["model_call_completed", "budget_snapshot"],
        )
        self.assertEqual(
            atomic_cases["terminal_with_budget_exhaustion"]["appended_event_types"],
            ["model_call_completed", "budget_exhausted"],
        )
        self.assertTrue(
            accounting["atomic_outbox_rules"]["events_are_appended_contiguously_in_listed_order"]
        )
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
        invalid_entries = {case["name"]: case for case in fixture["invalid_entries"]}
        for name in (
            "model_backend_missing",
            "model_backend_empty",
            "model_name_missing",
            "model_name_empty",
        ):
            self.assertEqual(invalid_entries[name]["error_code"], "model_identity_invalid")

    def test_checkpoint_store_progress_and_terminal_retention_are_locked(self) -> None:
        fixture = json.loads((ROOT / "fixtures/checkpoint_store.json").read_text(encoding="utf-8"))
        cases = {case["name"]: case for case in fixture["store_cases"]}
        deferred_cases = {case["name"]: case for case in fixture["deferred_cases"]}

        self.assertTrue(fixture["revision_rules"]["progress_preserves_claim"])
        self.assertFalse(fixture["revision_rules"]["heartbeat_requires_revision"])
        self.assertTrue(fixture["revision_rules"]["outbox_bounded_by_lifecycle_not_fixed_cardinality_or_bytes"])
        self.assertTrue(fixture["revision_rules"]["outbox_preflight_before_first_external_tool_effect"])
        self.assertTrue(fixture["revision_rules"]["outbox_no_post_effect_capacity_failure"])
        self.assertEqual(cases["progress_keeps_claim"]["expected"]["claim_token"], "owner-b")
        self.assertEqual(
            cases["progress_keeps_claim"]["expected"]["outbox_event_types"],
            ["model_call_started"],
        )
        terminal_progress = cases[
            "terminal_model_progress_updates_ledger_budget_and_outbox"
        ]["expected"]
        self.assertEqual(terminal_progress["model_call_count"], 1)
        self.assertEqual(terminal_progress["budget_total_tokens"], 20)
        self.assertEqual(
            terminal_progress["outbox_event_types"],
            ["model_call_started", "model_call_completed", "budget_snapshot"],
        )
        self.assertEqual(
            fixture["revision_rules"]["terminal_model_outbox_order"],
            [
                "model_terminal_event",
                "budget_snapshot_or_budget_exhausted_if_configured",
            ],
        )
        self.assertEqual(
            cases["heartbeat_after_progress_updates_lease_only"]["expected"]["journal_state"],
            "started",
        )
        self.assertTrue(cases["terminal_ack_is_retained"]["expected"]["row_present"])
        self.assertTrue(fixture["redis_rules"]["whole_json_heartbeat_forbidden"])
        self.assertEqual(fixture["namespaces"]["sqlite_table"], "checkpoints")
        self.assertEqual(fixture["namespaces"]["redis_key_prefix"], "vv-agent:checkpoint:")
        self.assertEqual(
            fixture["namespaces"]["deferred_receipt_sqlite_table"],
            "deferred_resolution_receipts",
        )
        self.assertEqual(
            fixture["namespaces"]["deferred_receipt_redis_key_prefix"],
            "vv-agent:deferred-receipt:",
        )
        self.assertEqual(
            fixture["namespaces"]["deferred_receipt_checkpoint_set_prefix"],
            "vv-agent:deferred-receipts-by-checkpoint:",
        )
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
        self.assertIn(
            "accept_deferred_batch",
            {operation["name"] for operation in fixture["operations"]},
        )
        mixed_batch = deferred_cases["admit_deferred_batch_mixed_outcomes_releases_claim_once"]
        self.assertEqual(mixed_batch["scenario_id"], "deferred_batch_mixed_call_a_b_c.v1")
        self.assertEqual(mixed_batch["source"], "fixtures/deferred_tool.json#batch.example")
        mixed_error = deferred_cases["admit_deferred_batch_mixed_error_marks_failed_journal"]
        self.assertEqual(mixed_error["scenario_id"], "deferred_batch_mixed_error_call_a_b_c.v1")
        first = deferred_cases["resolve_deferred_call_b_first"]
        last = deferred_cases["resolve_deferred_call_a_last"]
        self.assertEqual(first["scenario_id"], "deferred_resolution_call_b_then_call_a.v1")
        self.assertEqual(last["scenario_id"], first["scenario_id"])
        self.assertEqual(first["source"], "fixtures/deferred_tool.json#resolution")
        self.assertNotIn("handles", first["operation"])
        self.assertEqual(first["expected"]["decision_kind"], "applied_waiting")
        self.assertEqual(first["expected"]["status"], "deferred")
        self.assertEqual(first["expected"]["revision"], 6)
        self.assertEqual(last["expected"]["decision_kind"], "applied_ready")
        self.assertEqual(last["expected"]["status"], "running")
        self.assertEqual(last["expected"]["revision"], 7)
        loser = deferred_cases["resolve_deferred_concurrent_loser_reloads_receipt"]
        self.assertEqual(loser["scenario_id"], first["scenario_id"])
        self.assertEqual(loser["expected"]["decision_kind"], "replayed")
        self.assertEqual(loser["expected"]["revision_increment"], 0)
        self.assertEqual(
            deferred_cases["resolve_deferred_started_before_batch_admission_is_not_admitted"]["expected"]["retryable_error"],
            "deferred_resolution_not_admitted",
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
            self.assertEqual(vector["data_key"], f"vv-agent:checkpoint:{digest}")
            self.assertEqual(vector["lease_key"], f"{vector['data_key']}:lease")
        for vector in fixture["deferred_receipt_key_vectors"]:
            self.assertEqual(
                vector["data_key"],
                f"vv-agent:deferred-receipt:{vector['handle_key']}",
            )
            self.assertTrue(vector["checkpoint_set_key"].startswith("vv-agent:deferred-receipts-by-checkpoint:"))
        event_vector = fixture["event_payload_digest"]["golden_cases"][0]
        event_bytes = base64.b64decode(event_vector["canonical_json_base64"], validate=True)
        self.assertEqual(hashlib.sha256(event_bytes).hexdigest(), event_vector["sha256"])
        self.assertEqual(
            cases["create_absent"]["expected"]["resume_attempt"],
            1,
        )
        error_admission = deferred_cases["admit_deferred_batch_mixed_error_marks_failed_journal"]
        self.assertEqual(error_admission["expected"]["completed_journal_state"], "failed")
        self.assertEqual(error_admission["expected"]["completed_error_code"], "provider_rejected")

    def test_checkpoint_resume_fixture_covers_all_fault_boundaries(self) -> None:
        fixture = json.loads((ROOT / "fixtures/checkpoint_resume.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["version"], 7)
        self.assertEqual(fixture["checkpoint_schema"], "vv-agent.checkpoint.v7")
        self.assertIn("deferred", fixture["checkpoint_states"])
        self.assertEqual(
            fixture["deferred_pending_semantics"],
            "no cycle commit and no response result were returned by this delivery attempt",
        )
        cases = {case["name"]: case for case in fixture["runner_cases"]}
        matrix = fixture["fault_matrix"]

        self.assertEqual([case["id"] for case in matrix], [f"F{index}" for index in range(1, 10)])
        self.assertEqual(matrix[3]["resume"], "replay_receipt_without_usage_or_budget_increment")
        self.assertEqual(
            cases["started_model_requires_reconciliation"]["expected"]["completion_reason"],
            None,
        )
        self.assertEqual(
            cases["started_model_requires_reconciliation"]["expected"]["model_call_records"],
            1,
        )
        self.assertEqual(
            cases["started_model_can_retry_only_with_explicit_risk_policy"]["expected"][
                "model_call_records"
            ],
            2,
        )
        self.assertFalse(
            cases["started_model_can_retry_only_with_explicit_risk_policy"]["expected"][
                "aggregate_usage_available"
            ]
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

        frozen = cases["frozen_prompt_bundle_resume_does_not_reinvoke_producers"]
        bundle = frozen["run"]["frozen_prompt_bundle"]
        self.assertEqual(
            [section["id"] for section in bundle["sections"]],
            ["agent_instructions", "session_memory", "current_time", "callback_context"],
        )
        self.assertEqual(len(bundle["stable_hash"]), 64)
        for producer in frozen["run"]["resume_producers"].values():
            self.assertEqual(producer["behavior"], "poison")
            self.assertEqual(producer["expected_calls"], 0)
        self.assertEqual(frozen["expected"]["instruction_callback_calls"], 0)
        self.assertEqual(frozen["expected"]["context_provider_calls"], 0)
        self.assertEqual(frozen["expected"]["clock_reads"], 0)
        self.assertEqual(frozen["expected"]["prompt_bundle_relation"], "byte_equal")

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
        deferred_cases = {case["name"]: case for case in fixture["deferred_cases"]}
        directive_case = deferred_cases["deferred_resolution_directive_waits_for_normal_cycle_processing"]
        self.assertEqual(directive_case["resolution_directives"], ["finish", "wait_user"])
        self.assertTrue(directive_case["expected"]["receipt_persisted_before_directive_processing"])
        self.assertTrue(directive_case["expected"]["resumed_cycle_owns_finish_or_wait_user_directive"])
        resolution = deferred_cases["all_deferred_resolved_releases_batch_barrier"]
        self.assertEqual(resolution["scenario_id"], "deferred_resolution_call_b_then_call_a.v1")
        self.assertEqual(resolution["source"], "fixtures/deferred_tool.json#resolution")
        self.assertEqual(
            [operation["handle_ref"] for operation in resolution["operations"]],
            ["call_b", "call_a"],
        )
        self.assertEqual(resolution["operations"][0]["expected"]["decision_kind"], "applied_waiting")
        self.assertEqual(resolution["operations"][1]["expected"]["decision_kind"], "applied_ready")
        early = deferred_cases["early_callback_before_admission_is_retryable_not_admitted"]
        self.assertEqual(early["expected"]["retryable_error"], "deferred_resolution_not_admitted")
        self.assertTrue(early["expected"]["retryable"])
        self.assertFalse(early["expected"]["receipt_index_write"])
        loser = deferred_cases["out_of_order_resolution_concurrent_loser_replays_receipt"]
        self.assertEqual(loser["expected"]["loser_decision"], "replayed")
        self.assertEqual(loser["expected"]["loser_revision_increment"], 0)
        invalid_running = deferred_cases["running_with_unresolved_deferred_barrier_is_invalid"]
        self.assertFalse(invalid_running["expected"]["valid"])
        self.assertEqual(invalid_running["expected"]["error"], "checkpoint_status_invalid")

    def test_checkpoint_terminal_order_finalizes_before_event_delivery(self) -> None:
        runner = json.loads((ROOT / "fixtures/runner_terminal.json").read_text(encoding="utf-8"))
        distributed = json.loads(
            (ROOT / "fixtures/distributed_run_envelope.json").read_text(encoding="utf-8")
        )
        runner_order = runner["checkpoint_terminal_order"]["order"]
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
        codec = json.loads((ROOT / "fixtures/checkpoint_codec.json").read_text(encoding="utf-8"))
        store = json.loads((ROOT / "fixtures/checkpoint_store.json").read_text(encoding="utf-8"))

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
            for line in (ROOT / "fixtures/resume_events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        app = json.loads((ROOT / "fixtures/app_server_observable.json").read_text(encoding="utf-8"))
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
                "run_deferred": ["tool_call_deferred", "tool_call_completed"],
                "run_deferred_error": ["tool_call_deferred", "tool_call_completed"],
                "run_deferred_acceptance": ["reconciliation_resolved", "tool_call_deferred"],
            },
        )
        for scenario in grouped.values():
            self.assertEqual(len({record["run_id"] for record in scenario}), 1)
            self.assertEqual(len({record["trace_id"] for record in scenario}), 1)
        reconciliation = projections["reconciliation_required_is_interrupted_without_error"]
        self.assertEqual(reconciliation["turnStatus"], "interrupted")
        self.assertIsNone(reconciliation["completionReason"])
        self.assertEqual(reconciliation["errorField"], "omitted")
        deferred_projection = projections["deferred_pending_is_interrupted_and_resumable"]
        self.assertEqual(deferred_projection["turnStatus"], "interrupted")
        self.assertIsNone(deferred_projection["completionReason"])
        self.assertEqual(deferred_projection["waitReason"], "deferred_pending")
        self.assertFalse(deferred_projection["terminal"])
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
        deferred_protocol = protocol_cases["deferred_pending_resume_is_interrupted_not_terminal"]
        self.assertEqual(
            deferred_protocol["notifications"][-1]["params"]["waitReason"],
            "deferred_pending",
        )
        self.assertFalse(deferred_protocol["terminal"])
        live_claim = protocol_cases["live_claim_keeps_existing_owner"]
        self.assertFalse(live_claim["newRunCreated"])
        self.assertEqual(live_claim["notifications"], [])
        terminal_replay = protocol_cases["terminal_replay_is_response_only"]
        self.assertEqual(terminal_replay["response"]["result"]["status"], "completed")
        self.assertEqual(terminal_replay["externalCalls"], 0)

    def test_distributed_resolves_checkpoint_capabilities_strictly(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/distributed_run_envelope.json").read_text(encoding="utf-8")
        )
        envelope = fixture["canonical_envelope"]
        capabilities = envelope["recipe"]["capabilities"]

        self.assertEqual(envelope["schema_version"], "vv-agent.distributed-run.v5")
        self.assertEqual(envelope["run_definition_schema"], "vv-agent.run-definition.v5")
        unsupported_definition_schema = next(
            case
            for case in fixture["invalid_cases"]
            if case["name"] == "unsupported_run_definition_schema"
        )["value"]
        self.assertNotEqual(
            unsupported_definition_schema,
            fixture["run_definition_schema_rules"]["writer_value"],
        )
        self.assertEqual(capabilities["checkpoint_store_ref"]["version"], "2")
        self.assertEqual(
            capabilities["toolset_ref"]["schema_digest"],
            "d266963bff5d4dc90f4fd4c9897381aa589375078f0c08c23af474e27f6b0269",
        )
        self.assertEqual(
            capabilities["after_cycle_hook_refs"],
            [{"id": "lifecycle.policy", "version": "1"}],
        )
        self.assertEqual(
            capabilities["tool_policy"]["denied_side_effects"],
            ["execute"],
        )
        missing = next(
            case
            for case in fixture["capability_resolution_cases"]
            if case["name"] == "unknown_capability_fails_before_claim"
        )
        self.assertEqual(missing["expected"]["claim_count"], 0)
        self.assertEqual(missing["expected"]["model_calls"], 0)
        self.assertEqual(
            capabilities["tool_policy"]["denied_capability_tags"],
            ["filesystem.delete"],
        )
        self.assertFalse(capabilities["tool_policy"]["deny_terminal_tools"])
        self.assertEqual(
            capabilities["tool_policy"]["denied_cost_dimensions"],
            ["gpu.second"],
        )
        self.assertEqual(fixture["worker_rules"]["apalis_blocking_runtime"], "tokio_spawn_blocking")
        self.assertTrue(fixture["worker_rules"]["after_cycle_hook_resolution_before_claim"])
        self.assertTrue(
            fixture["worker_rules"]["metadata_tool_policy_fields_are_serialized_before_claim"]
        )
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

    def test_distributed_worker_response_has_one_closed_tagged_wire(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/distributed_worker_response.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            fixture["schema_version"],
            "vv-agent.distributed-worker-response.v3",
        )
        rules = fixture["wire_rules"]
        self.assertEqual(rules["discriminator"], "type")
        self.assertTrue(rules["closed_objects"])
        self.assertTrue(rules["boolean_is_not_an_integer"])
        self.assertEqual(rules["json_safe_integer_maximum"], 9_007_199_254_740_991)
        self.assertEqual(rules["checkpoint_revision_minimum"], 0)
        self.assertEqual(rules["committed_cycle_minimum"], 1)
        self.assertEqual(
            rules["terminal_candidate_statuses"],
            [
                "reconciliation_required",
                "wait_user",
                "completed",
                "failed",
                "max_cycles",
            ],
        )
        self.assertEqual(
            rules["terminal_replay_statuses"],
            ["wait_user", "completed", "failed", "max_cycles"],
        )
        self.assertTrue(rules["scheduler_must_verify_authoritative_checkpoint"])
        self.assertFalse(rules["transport_failure_is_response_variant"])
        self.assertTrue(rules["legacy_boolean_wire_is_rejected"])
        self.assertEqual(
            rules["pending_semantics"],
            "no cycle commit and no response result were returned by this delivery attempt",
        )

        result_wire = fixture["agent_result_wire"]
        required_result_fields = {
            "status",
            "completion_reason",
            "completion_tool_name",
            "partial_output",
            "messages",
            "cycles",
            "final_answer",
            "wait_reason",
            "error",
            "shared_state",
            "token_usage",
            "checkpoint_key",
            "resume_observation",
        }
        optional_result_fields = {"budget_usage", "budget_exhaustion", "error_code"}
        self.assertEqual(set(result_wire["required_fields"]), required_result_fields)
        self.assertEqual(set(result_wire["optional_fields"]), optional_result_fields)
        self.assertTrue(result_wire["optional_fields_omitted_when_absent"])
        self.assertTrue(result_wire["optional_fields_reject_null"])
        self.assertEqual(result_wire["unknown_fields"], "reject")

        status_matrix = {
            case["type"]: case["accepted_statuses"]
            for case in fixture["status_matrix_cases"]
        }
        self.assertEqual(status_matrix["terminal_candidate"], rules["terminal_candidate_statuses"])
        self.assertEqual(status_matrix["terminal_replay"], rules["terminal_replay_statuses"])
        self.assertIsNone(fixture["transport_failure"]["worker_response_type"])
        self.assertEqual(
            fixture["transport_failure"]["representation"],
            "out_of_band_dispatch_error",
        )
        self.assertEqual(
            fixture["legacy_wire_fields"],
            ["finished", "terminal_candidate", "terminal_replay"],
        )

        valid = {case["name"]: case["response"] for case in fixture["valid_cases"]}
        self.assertEqual(
            set(valid),
            {"pending", "committed", "terminal_candidate", "terminal_replay"},
        )
        self.assertEqual(set(valid["pending"]), {"schema_version", "type"})
        self.assertEqual(
            set(valid["committed"]),
            {"schema_version", "type", "checkpoint_revision", "committed_cycle"},
        )
        for name in ("terminal_candidate", "terminal_replay"):
            response = valid[name]
            self.assertEqual(
                set(response),
                {"schema_version", "type", "checkpoint_revision", "result"},
            )
            self.assertEqual(response["result"]["status"], "completed")
            self.assertEqual(response["result"]["completion_reason"], "no_tool_finish")
            self.assertIsNone(response["result"]["completion_tool_name"])
            self.assertEqual(
                set(response["result"]),
                required_result_fields,
            )

        self.assertEqual(
            {case["name"] for case in fixture["invalid_cases"]},
            {
                "payload_is_not_an_object",
                "payload_is_null",
                "payload_is_boolean",
                "payload_is_number",
                "missing_schema_version",
                "null_schema_version",
                "boolean_schema_version",
                "number_schema_version",
                "stale_schema_version",
                "unknown_schema_version",
                "missing_type",
                "null_type",
                "boolean_type",
                "number_type",
                "unknown_type",
                "legacy_finished_discriminator",
                "current_schema_with_legacy_finished_field",
                "current_schema_with_terminal_candidate_boolean",
                "current_schema_with_terminal_replay_boolean",
                "pending_unknown_field",
                "committed_missing_revision",
                "committed_missing_cycle",
                "committed_boolean_revision",
                "committed_negative_revision",
                "committed_float_revision",
                "committed_revision_above_wire_maximum",
                "committed_boolean_cycle",
                "committed_negative_cycle",
                "committed_float_cycle",
                "committed_zero_cycle",
                "committed_cycle_above_wire_maximum",
                "committed_mixed_with_result",
                "terminal_candidate_missing_revision",
                "terminal_candidate_missing_result",
                "terminal_candidate_boolean_revision",
                "terminal_candidate_negative_revision",
                "terminal_candidate_float_revision",
                "terminal_candidate_revision_above_wire_maximum",
                "terminal_candidate_mixed_with_committed_cycle",
                "terminal_candidate_unknown_field",
                "terminal_candidate_invalid_result",
                "terminal_result_is_null",
                "terminal_result_is_list",
                "terminal_result_missing_required_field",
                "terminal_result_unknown_field",
                "terminal_result_optional_budget_usage_is_null",
                "terminal_result_optional_budget_exhaustion_is_null",
                "terminal_result_optional_error_code_is_null",
                "terminal_candidate_pending_result",
                "terminal_candidate_running_result",
                "terminal_replay_mixed_with_committed_cycle",
                "terminal_replay_unknown_field",
                "terminal_replay_reconciliation_required_result",
            },
        )
        unknown_version = next(
            case["response"]["schema_version"]
            for case in fixture["invalid_cases"]
            if case["name"] == "unknown_schema_version"
        )
        self.assertNotEqual(unknown_version, fixture["schema_version"])

        valid_by_name = {case["name"]: case["response"] for case in fixture["valid_cases"]}
        for case in fixture["invalid_cases"]:
            if "response" in case:
                self.assertNotIn("mutation", case)
                continue
            self.assertIn(case["base_valid_case"], valid_by_name)
            mutation = case["mutation"]
            self.assertIn(mutation["operation"], {"add", "replace", "remove"})
            self.assertGreaterEqual(len(mutation["path"]), 1)
            if mutation["operation"] == "remove":
                self.assertNotIn("value", mutation)
            else:
                self.assertIn("value", mutation)

    def test_distributed_run_driver_is_enqueue_only_and_checkpoint_authoritative(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/distributed_run_driver.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            fixture["schema_version"],
            "vv-agent.distributed-run-driver.v2",
        )
        self.assertTrue(fixture["handle"]["passive"])
        self.assertEqual(
            fixture["handle"]["fields"],
            ["checkpoint_key", "run_id", "trace_id"],
        )
        self.assertEqual(
            fixture["handle"]["status_source"],
            "authoritative_checkpoint_store",
        )
        self.assertFalse(fixture["operations"]["start"]["waits_for_completion"])
        self.assertEqual(fixture["operations"]["start"]["maximum_envelopes_enqueued"], 1)
        self.assertEqual(fixture["operations"]["advance"]["authoritative_checkpoint_reads"], 1)
        self.assertEqual(fixture["operations"]["advance"]["maximum_envelopes_enqueued"], 1)
        self.assertFalse(fixture["operations"]["advance"]["polls"])
        self.assertFalse(fixture["operations"]["advance"]["sleeps"])
        self.assertFalse(fixture["operations"]["advance"]["waits_for_completion"])
        self.assertEqual(
            fixture["operations"]["finalize"]["consumes_decision"],
            "finalize_required",
        )
        self.assertTrue(fixture["operations"]["finalize"]["bounded_task"])
        self.assertTrue(fixture["operations"]["finalize"]["accepts_claimed_worker_candidate"])
        self.assertTrue(fixture["operations"]["finalize"]["accepts_unclaimed_max_cycles_candidate"])
        self.assertFalse(fixture["operations"]["finalize"]["waits_for_child_task"])
        self.assertEqual(
            set(fixture["decisions"]),
            {"dispatch", "retry_at", "wait", "finalize_required", "terminal_replay"},
        )
        self.assertEqual(set(fixture["decision_fields"]), set(fixture["decisions"]))
        self.assertTrue(fixture["rules"]["worker_response_is_observation"])
        self.assertTrue(fixture["rules"]["cycle_callback_is_bounded_advance"])
        self.assertFalse(fixture["rules"]["advance_executes_terminal_work"])
        self.assertTrue(fixture["rules"]["terminal_finalizer_is_separate_bounded_task"])
        self.assertTrue(fixture["rules"]["terminal_candidate_requires_controller_finalization"])
        self.assertTrue(fixture["rules"]["celery_async_result_get_forbidden"])
        self.assertTrue(fixture["rules"]["apalis_wait_for_completion_forbidden"])
        self.assertTrue(fixture["rules"]["lost_callback_recovered_by_late_ack_or_reconciler"])
        self.assertTrue(fixture["rules"]["last_resolution_returns_unclaimed_running"])
        self.assertTrue(fixture["rules"]["deferred_pending_wait_is_not_host_interaction"])
        self.assertTrue(fixture["rules"]["deferred_status_is_not_claimable"])
        transitions = {case["name"]: case for case in fixture["transition_cases"]}
        self.assertEqual(transitions["start"]["cycle_index"], 1)
        self.assertEqual(transitions["committed_cycle"]["claim_mode"], "continue")
        self.assertEqual(transitions["expired_claim"]["claim_mode"], "recovery")
        self.assertEqual(transitions["terminal_candidate"]["decision"], "finalize_required")
        self.assertEqual(transitions["max_cycles_after_commit"]["result_status"], "max_cycles")
        self.assertEqual(transitions["superseded_delivery"]["reason"], "superseded_delivery")
        self.assertEqual(transitions["reconciliation"]["decision"], "wait")
        self.assertEqual(transitions["deferred_pending"]["reason"], "deferred_pending")
        self.assertEqual(transitions["deferred_batch_ready"]["decision"], "dispatch")
        self.assertEqual(transitions["deferred_batch_ready"]["resolve_decision"], "applied_ready")
        self.assertEqual(transitions["deferred_batch_ready"]["claim_mode"], "recovery")

        public_api = json.loads(
            (ROOT / "fixtures/public_api.json").read_text(encoding="utf-8")
        )
        runtime_capabilities = {
            capability["id"]: capability
            for domain in public_api["domains"]
            if domain["id"] == "runtime_backend"
            for capability in domain["capabilities"]
        }
        self.assertEqual(
            runtime_capabilities["runtime_backend.distributed_run_handle"],
            {
                "id": "runtime_backend.distributed_run_handle",
                "python": "vv_agent.runtime.backends.distributed.DistributedRunHandle",
                "rust": "vv_agent::DistributedRunHandle",
            },
        )
        self.assertEqual(
            runtime_capabilities["runtime_backend.distributed_delivery_outcome"]["python"],
            "vv_agent.runtime.backends.distributed.DistributedDeliveryOutcome",
        )
        self.assertEqual(
            runtime_capabilities["runtime_backend.distributed_delivery_outcome"]["rust"],
            "vv_agent::DistributedDeliveryOutcome",
        )
        self.assertEqual(
            runtime_capabilities["runtime_backend.distributed_advance_decision"]["python"],
            "vv_agent.runtime.backends.distributed.DistributedAdvanceDecision",
        )
        self.assertEqual(
            runtime_capabilities["runtime_backend.distributed_advance_decision"]["rust"],
            "vv_agent::DistributedAdvanceDecision",
        )
        self.assertEqual(
            runtime_capabilities["runtime_backend.distributed_start"]["python"],
            "vv_agent.runtime.backends.celery.CeleryBackend.start",
        )
        self.assertEqual(
            runtime_capabilities["runtime_backend.distributed_start"]["rust"],
            "vv_agent::DistributedBackend::start",
        )
        self.assertEqual(
            runtime_capabilities["runtime_backend.distributed_advance"]["python"],
            "vv_agent.runtime.backends.celery.CeleryBackend.advance",
        )
        self.assertEqual(
            runtime_capabilities["runtime_backend.distributed_advance"]["rust"],
            "vv_agent::DistributedBackend::advance",
        )
        runner_surface = next(
            surface for surface in public_api["surfaces"] if surface["id"] == "runner"
        )
        runner_members = {member["id"]: member for member in runner_surface["members"]}
        self.assertEqual(
            runner_members["start_distributed"]["python"]["name"],
            "start_distributed",
        )
        self.assertEqual(
            runner_members["start_distributed"]["rust"]["name"],
            "start_distributed",
        )
        self.assertEqual(
            runner_members["finalize_distributed"]["python"]["name"],
            "finalize_distributed",
        )
        self.assertEqual(
            runner_members["finalize_distributed"]["rust"]["name"],
            "finalize_distributed",
        )

    def test_checkpoint_sqlite_has_checkpoint_and_independent_receipt_tables(self) -> None:
        sql = (ROOT / "fixtures/checkpoint_sqlite_canonical.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS checkpoints (", sql)
        self.assertIn("run_definition_schema TEXT NOT NULL", sql)
        self.assertIn("run_definition TEXT NOT NULL", sql)
        self.assertIn("terminal_acknowledged", sql)
        self.assertIn("model_call_journal", sql)
        self.assertNotIn("deferred_resolution_receipts" + " TEXT NOT NULL", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS deferred_resolution_receipts (", sql)
        self.assertIn("handle_key TEXT PRIMARY KEY", sql)
        self.assertIn("FOREIGN KEY (checkpoint_key) REFERENCES checkpoints(checkpoint_key) ON DELETE CASCADE", sql)
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(sql)
            connection.execute(
                """
                INSERT INTO checkpoints (
                    checkpoint_key, schema_version, run_definition_schema, run_definition, task_id,
                    root_run_id, trace_id, run_definition_digest, resume_attempt,
                    cycle_index, status, messages, cycles, model_calls, shared_state, budget_usage,
                    event_cursor, event_outbox, extension_state, model_call_journal,
                    tool_journal, revision, claim_token, claimed_cycle,
                    lease_expires_at_ms, terminal_result, terminal_acknowledged
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "checkpoint-key",
                    "vv-agent.checkpoint.v7",
                    "vv-agent.run-definition.v5",
                    "{}",
                    "task-1",
                    "run-1",
                    "trace-1",
                    "c" * 64,
                    1,
                    0,
                    "running",
                    "[]",
                    "[]",
                    "[]",
                    "{}",
                    None,
                    None,
                    "[]",
                    "{}",
                    "[]",
                    "[]",
                    0,
                    None,
                    None,
                    None,
                    None,
                    0,
                ),
            )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertEqual(tables, {"checkpoints", "deferred_resolution_receipts"})
            connection.execute(
                """
                INSERT INTO deferred_resolution_receipts (
                    handle_key, checkpoint_key, handle, result, result_digest,
                    event_id, event_payload_digest, receipt_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "h" * 64,
                    "checkpoint-key",
                    "{}",
                    '{"status_code":"SUCCESS"}',
                    "r" * 64,
                    "event-1",
                    "e" * 64,
                    "succeeded",
                ),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT handle_key, receipt_status FROM deferred_resolution_receipts WHERE checkpoint_key = ?",
                    ("checkpoint-key",),
                ).fetchone(),
                ("h" * 64, "succeeded"),
            )
            connection.execute(
                "DELETE FROM checkpoints WHERE checkpoint_key = ?",
                ("checkpoint-key",),
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT handle_key FROM deferred_resolution_receipts WHERE checkpoint_key = ?",
                    ("checkpoint-key",),
                ).fetchone()
            )
            self.assertEqual(
                connection.execute(
                    "SELECT run_definition_schema FROM checkpoints WHERE checkpoint_key = ?",
                    ("checkpoint-key",),
                ).fetchone(),
                None,
            )
        finally:
            connection.close()

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
                    "v3.0.0/vv-agent-contract-3.0.0.zip"
                ),
                snapshot_path="tests/fixtures/parity",
            )

            synced = contract_snapshot.sync_snapshot(args)
            checked = contract_snapshot.check_lock(implementation, "contract.lock.json")

            self.assertEqual(synced["fixture_files"], 53)
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
                    artifact_url="https://example.invalid/vv-agent-contract-0.9.0.zip",
                    snapshot_path="fixtures",
                )
            )
            fixture = implementation / "fixtures/model_ref.json"
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
                    artifact_url="https://example.invalid/vv-agent-contract-0.8.1.zip",
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
