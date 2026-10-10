from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import shutil
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


def validate_strict_tool_execution_result(
    result: dict[str, object],
    fixture: dict[str, object],
) -> None:
    result_contract = fixture["result_contract"]
    required = set(result_contract["required_fields"])
    optional = set(result_contract["optional_fields"])
    truncation_fields = {
        "truncated",
        "truncation_reason",
        "original_bytes",
        "visible_bytes",
        "artifact",
        "cursor",
    }
    artifact_pattern = re.compile(fixture["artifact_contract"]["path"]["pattern"])
    keys = set(result)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise ValueError("shape")
    if any(result[key] is None for key in keys & optional):
        raise ValueError("null optional")
    if "error_code" in result and not isinstance(result["error_code"], str):
        raise ValueError("error code")
    if result.get("status_code") == "SUCCESS" and result.get("error_code") is not None:
        raise ValueError("success error code")
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


class ContractRepositoryTests(unittest.TestCase):
    def test_cross_repository_checkout_keeps_contract_history(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")
        contract_checkout = workflow.split("- name: Checkout contract", maxsplit=1)[1].split(
            "- name: Checkout Python implementation", maxsplit=1
        )[0]

        self.assertIn("fetch-depth: 0", contract_checkout)

    def test_cross_repository_gate_uses_required_python_only(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")
        self.assertIn("path: vv-agent\n", workflow)
        for removed in ("rust_ref", "vv-agent-rs", "cargo ", "cross-language", "CROSS_RUNTIME", "CROSS_HOST", "CROSS_HISTORY"):
            self.assertNotIn(removed, workflow)
        for command in ("uv run pytest", "uv run ruff check .", "uv run ty check"):
            self.assertIn(command, workflow)
        self.assertIn("check --source contract", workflow)
        self.assertIn("check --artifact", workflow)
        self.assertIn('contract/scripts/contractctl.py --root contract build', workflow)

    def test_record_verified_requires_all_default_branches(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")
        recording_step = workflow.split("- name: Update verified support matrix", maxsplit=1)[1].split(
            "- name: Commit verified support matrix", maxsplit=1
        )[0]

        for input_name in ("contract_ref", "python_ref"):
            self.assertIn(f'test "${{{{ inputs.{input_name} }}}}" = "main"', recording_step)

    def test_validate_workflow_supports_manual_dispatch(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:\n", workflow)
        self.assertIn("node scripts/verify_jcs.mjs", workflow)

    def test_release_workflow_runs_jcs_gate(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

        self.assertIn("node scripts/verify_jcs.mjs", workflow)

    def test_cross_repository_workflow_runs_canonical_jcs_gate(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")

        self.assertIn("node contract/scripts/verify_jcs.mjs", workflow)

    def test_cross_repository_workflow_provisions_real_databases(self) -> None:
        workflow = (ROOT / ".github/workflows/cross-repository.yml").read_text(encoding="utf-8")
        for required in (
            "image: postgres:", "pg_isready", "psql -Atc 'SELECT 1'",
            "VV_AGENT_TEST_POSTGRES_DSN:", "job.services.postgres.ports['5432']",
        ):
            self.assertIn(required, workflow)
        # Python has no Redis store or Redis tests after the session-kernel cut-over.
        self.assertNotIn("redis", workflow.lower())

    def test_live_contract_validates(self) -> None:
        report = contractctl.validate_contract(ROOT)
        matrix = json.loads((ROOT / "support-matrix.json").read_text(encoding="utf-8"))

        self.assertEqual(report["version"], "26.0.0")
        self.assertEqual(report["domains"], 18)
        self.assertEqual(report["fixture_files"], 54)
        self.assertEqual(report["manifest_entries"], 53)
        self.assertEqual(report["adoption_status"], matrix["status"])

    def test_json_duplicate_object_keys_are_rejected(self) -> None:
        duplicate = '{"revision_rules":{"admit_deferred_batch_deferred_only":true,"admit_deferred_batch_deferred_only":false}}'
        with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
            contractctl.strict_json_loads(duplicate)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(contractctl.ContractError, "cannot read valid JSON"):
                contractctl.load_json(path)
            path.unlink()
            jsonl = Path(temporary) / "duplicate.jsonl"
            jsonl.write_text(duplicate + "\n", encoding="utf-8")
            with self.assertRaisesRegex(contractctl.ContractError, "invalid JSONL record"):
                contractctl.validate_fixture_syntax(Path(temporary), {})

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
                "transcript_authority",
                "same_turn_wait_producer",
            },
        )
        self.assertEqual(fixture["version"], 2)
        self.assertEqual(
            {case["name"] for case in fixture["canonical_cases"]},
            {
                "plain_message_uses_current_wire",
                "openai_function_tool_call_is_canonicalized",
                "microcompacted_tool_message_round_trips",
                "summary_evidence_round_trips",
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
        self.assertEqual(session_memory["control_outcomes_propagate"],
                         ["cancellation", "budget_exhaustion", "lost_ownership"])

    def test_prompt_bundle_requires_explicit_session_memory_enablement(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/prompt_bundle.json").read_text(encoding="utf-8")
        )
        self.assertEqual(fixture["schema_version"], "vv-agent.prompt-bundle.v2")
        self.assertEqual(
            fixture["run_scope"]["session_resume"],
            "reuse_frozen_definition_without_reinvoking_producers",
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
            }.issubset(invalid_names)
        )

    def test_bounded_tool_result_is_sparse_and_recoverable(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/bounded_tool_result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            fixture["schema_version"], "vv-agent.tool-execution-result.v4"
        )
        self.assertEqual(
            fixture["result_contract"]["canonical_writer_normalization"],
            {
                "writer": "strict ToolExecutionResult typed writer",
                "omit_empty_optional_fields": ["metadata"],
                "include_present_optional_fields_after_normalization": True,
            },
        )
        self.assertEqual(
            fixture["result_contract"]["metadata"]["retryable"],
            "boolean when present and retained in the canonical result",
        )
        ordinary = fixture["canonical_results"]["ordinary"]
        self.assertEqual(
            set(ordinary),
            {"tool_call_id", "content", "status_code", "directive"},
        )
        truncated = fixture["canonical_results"]["truncated_bash"]
        self.assertTrue(truncated["truncated"])
        self.assertTrue(truncated["artifact"]["path"].startswith(".vv-agent/artifacts/"))
        truncated_error = fixture["canonical_results"]["truncated_error"]
        self.assertEqual(truncated_error["status_code"], "ERROR")
        self.assertEqual(truncated_error["directive"], "wait_user")
        self.assertEqual(truncated_error["metadata"]["provider"], "gateway")
        self.assertTrue(truncated_error["truncated"])
        self.assertIn("artifact", truncated_error)
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
        self.assertIn(
            "success_result_has_non_null_error_code",
            {case["name"] for case in fixture["invalid_cases"]},
        )
        for result in fixture["canonical_results"].values():
            validate_strict_tool_execution_result(result, fixture)

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
                    validate_strict_tool_execution_result(candidate, fixture)


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
            "evt_tool_receipt_1",
            "evt_deferred_call_a_completed",
            "evt_deferred_call_c_failed",
            "evt_deferred_resolved",
            "evt_deferred_resolved_1",
            "evt_deferred_error_completed",
        ]
        for value in forbidden:
            self.assertNotIn(value, text)


    def test_current_builtin_surface_is_compact_and_has_only_real_exposure(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/builtin_tools.json").read_text(encoding="utf-8")
        )
        tools = {tool["name"]: tool for tool in fixture["tools"]}
        self.assertEqual(fixture["schema_version"], 4)
        self.assertEqual(
            set(tools),
            {
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
                "stop_background_command",
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
        parameters = tools["bash"]["parameters"]
        self.assertEqual(set(parameters["properties"]), {
            "command", "exec_dir", "stdin", "auto_confirm", "yield_time_ms", "timeout_seconds",
        })
        self.assertEqual(parameters["required"], ["command"])
        self.assertFalse(parameters["additionalProperties"])
        self.assertEqual(parameters["properties"]["yield_time_ms"]["default"], 1000)
        for name, minimum, maximum in (("yield_time_ms", 0, 10000), ("timeout_seconds", 1, 86400)):
            self.assertEqual(parameters["properties"][name]["type"], "integer")
            self.assertEqual(parameters["properties"][name]["minimum"], minimum)
            self.assertEqual(parameters["properties"][name]["maximum"], maximum)
        for name in ("check_background_command", "stop_background_command"):
            self.assertEqual(set(tools[name]["parameters"]["properties"]), {"session_id"})
            self.assertEqual(tools[name]["parameters"]["required"], ["session_id"])
            self.assertFalse(tools[name]["parameters"]["additionalProperties"])
        management = json.loads((ROOT / "fixtures/bash_process_management.json").read_text(encoding="utf-8"))
        self.assertEqual(management["running_receipt"]["status_code"], "SUCCESS")
        self.assertEqual(management["owner_binding"], ["task_id", "canonical_workspace_root"])
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
        self.assertNotIn("task_finish", tools)
        self.assertIn("cursor", tools["read_file"]["parameters"]["properties"])
        for path in sorted((ROOT / "fixtures").glob("*.json")):
            self.assertNotIn("memory_notes", path.read_text(encoding="utf-8"), path.name)

        public_api = json.loads(
            (ROOT / "fixtures/public_api.json").read_text(encoding="utf-8")
        )
        self.assertEqual(public_api["contract"], "vv-agent-public-api-v10")
        self.assertEqual(public_api["schema_version"], 10)
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

    def test_task_token_usage_v3_has_strict_negative_cases(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/token_usage.json").read_text(encoding="utf-8")
        )
        rules = fixture["task_usage_rules"]
        cases = {case["name"]: case for case in fixture["invalid_task_wire_cases"]}

        self.assertEqual(rules["schema_version"], "vv-agent.task-token-usage.v3")
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
                        value.get("schema_version") == "vv-agent.task-token-usage.v3"
                        and "model_calls" in value
                    ):
                        self.assertEqual(set(value), set(rules["required_fields"]), path.name)
                        model_calls = value.get("model_calls")
                        self.assertIsInstance(model_calls, list, path.name)
                        for model_call in model_calls:
                            self.assertEqual(
                                set(model_call),
                                {
                                    "schema_version",
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


    def test_after_cycle_contract_is_closed_task_neutral_and_non_success_only(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures/after_cycle_hook.json").read_text(encoding="utf-8")
        )

        self.assertEqual(fixture["schema_version"], "vv-agent.after-cycle-hook.v2")
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
        self.assertTrue(fixture["durability"]["committed_boundary_reuses_decision"])
        self.assertTrue(fixture["durability"]["precommit_may_rerun"])
        self.assertFalse(
            set(fixture["snapshot"]["task_domain_fields_forbidden"])
            & set(fixture["snapshot"]["required_fields"])
        )
        cases = {case["name"]: case for case in fixture["runner_cases"]}
        self.assertEqual(cases["stop_cannot_be_projected_as_success"]["expected"]["status"], "failed")
        self.assertEqual(
            cases["steer_at_max_cycles_fails_closed"]["expected"]["error_code"],
            "agent_failed",
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
            [mappings[source]["wire_type"] for source in ["assistant_delta", "reasoning_delta", "tool_call_started", "tool_call_progress"]],
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
            [mappings[source]["wire_type"] for source in ["assistant_delta", "reasoning_delta", "tool_call_started", "tool_call_progress"]],
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
        event_types.update(event["type"] for event in fixture["synthetic_top_level"]["expected_wire_events"])
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
        self.assertTrue(fixture["definition_binding"]["retained_on_resume"])
        self.assertFalse(
            fixture["task_independence"]["terminal_declaration_automatically_finishes"]
        )
        self.assertEqual(
            fixture["telemetry_contract"]["completed_status_values"],
            ["success", "error", "wait_response", "running", "pending_compress"],
        )


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


    def test_app_server_tool_lifecycle_projection_is_fully_frozen(self) -> None:
        fixture = contractctl.load_json(ROOT / "fixtures/app_server_observable.json")["toolLifecycle"]
        planned = fixture["plannedHasNoNotification"]
        self.assertEqual(planned["notifications"], [])
        self.assertIsNone(planned["persistedItem"])
        self.assertTrue(planned["argumentsAvailableToApprovalRouting"])
        self.assertFalse(planned["presentedAsExecution"])
        for notification in fixture["executed"]["startedNotifications"]:
            self.assertEqual(notification["method"], "item/started")
        for notification in fixture["executed"]["completedNotifications"]:
            payload = notification["params"]["payload"]
            self.assertTrue({"directive", "errorCode", "executionStarted", "durationMs"} <= set(payload))
            if not payload["executionStarted"]:
                self.assertIsNone(payload["durationMs"])
        denial = fixture["policyDenial"]
        self.assertEqual(denial["startedNotifications"], [])
        payload = denial["completedNotifications"][0]["params"]["payload"]
        self.assertFalse(payload["executionStarted"])
        self.assertIsNone(payload["durationMs"])
        self.assertEqual(payload["errorCode"], "tool_not_allowed")

    def test_app_server_model_lifecycle_and_task_usage_v3_are_frozen(self) -> None:
        fixture = contractctl.load_json(ROOT / "fixtures/app_server_observable.json")
        lifecycle = fixture["modelLifecycle"]
        self.assertEqual(lifecycle["itemType"], "modelCall")
        identities = {"callId", "operationId", "attempt", "operation", "cycleIndex", "backend", "model"}
        self.assertEqual(set(lifecycle["identityFields"]), identities)
        for key, method in [("startedNotifications", "item/started"), ("completedNotifications", "item/completed"), ("failedNotifications", "item/completed")]:
            for notification in lifecycle[key]:
                self.assertEqual(notification["method"], method)
                params = notification["params"]
                self.assertEqual(params["type"], "modelCall")
                self.assertTrue(identities <= set(params["payload"]))
                self.assertTrue(set(lifecycle["forbiddenPayloadFields"]).isdisjoint(params["payload"]))
        projection = fixture["terminal"]["tokenUsageProjection"]
        self.assertEqual(projection["sourceSchemaVersion"], "vv-agent.task-token-usage.v3")
        self.assertEqual(projection["value"]["schemaVersion"], "vv-agent.task-token-usage.v3")
        for call in projection["value"]["modelCalls"]:
            self.assertEqual(call["schemaVersion"], "vv-agent.model-call.v2")
            self.assertEqual(call["usage"]["schemaVersion"], "vv-agent.token-usage.v1")
            self.assertNotIn("promptTokens", call["usage"]["providerUsage"])

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
        records = [json.loads(line) for line in (ROOT / "fixtures/budget_events.jsonl").read_text().splitlines()]
        self.assertEqual([r["type"] for r in records],
                         ["budget_snapshot", "budget_snapshot", "budget_exhausted", "run_failed"])
        self.assertEqual(records[-1]["status"], "failed")
        self.assertEqual(records[-2]["budget_usage"]["total_tokens"], 15)
        self.assertEqual(records[-2]["budget_exhaustion"]["dimension"], "total_tokens")


    def test_completion_policy_is_task_agnostic(self) -> None:
        fixture = json.loads((ROOT / "fixtures/completion_policy.json").read_text(encoding="utf-8"))

        self.assertEqual(fixture["policy_values"], ["continue", "wait_user", "finish"])
        self.assertEqual(fixture["framework_default"], "finish")
        self.assertEqual(
            fixture["precedence"],
            ["run_config", "runner_default_run_config", "agent", "framework_default"],
        )
        self.assertTrue(fixture["rules"]["assistant_text_is_not_classified"])
        self.assertTrue(fixture["rules"]["completion_policy_does_not_change_tool_availability"])
        self.assertTrue(fixture["rules"]["budget_exhausted_is_defined_by_run_budget"])
        self.assertTrue(fixture["rules"]["approval_resume_preserves_resource_budget"])
        self.assertTrue(fixture["rules"]["guardrail_allow_preserves_completion_observation"])
        self.assertTrue(fixture["rules"]["ordinary_llm_failure_is_typed_terminal"])


    def test_completion_closure_locks_same_turn_guardrail_and_llm_failure(self) -> None:
        fixture = contractctl.load_json(ROOT / "fixtures/completion_policy.json")
        self.assertEqual(fixture["output_guardrail_allow"]["preserved_fields"],
                         ["status", "completion_reason", "completion_tool_name", "partial_output"])
        self.assertEqual(fixture["output_guardrail_allow"]["case"]["expected_output"], "Redacted question")
        self.assertEqual(fixture["ordinary_llm_failure"]["runner_outcome"], "typed_result")
        self.assertEqual(fixture["ordinary_llm_failure"]["terminal_count"], 1)
        cases = {c["case"]: c for c in contractctl.load_json(ROOT / "fixtures/session_semantics.json")["cases"]}
        for name in ["user_wait", "turn_wait"]:
            self.assertTrue(cases[name]["same_turn"])

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
        domains = {domain["id"]: domain for domain in fixture["domains"]}
        self.assertEqual(
            {item["id"] for item in domains["runtime_backend"]["capabilities"]},
            {
                "runtime_backend.host_interaction_request",
                "runtime_backend.host_interaction_outcome",
            },
        )
        for item in domains["runtime_backend"]["capabilities"]:
            value = "request" if item["python"].endswith("Request") else "outcome"
            self.assertEqual(item["wire"], f"fixtures/app_server_protocol.json#/host_interaction_values/{value}")
        session_names = {
            "Record", "InboxItem", "SessionSpec", "SessionStore", "SessionTx",
            "SQLiteStore", "PostgresStore", "Conflict", "LeaseLost", "MissingHostBinding",
            "Definitive", "Accepted", "Unknown", "SessionRunEventStore",
            "ChildSession", "InvalidChildBatch", "Runtime", "RuntimeNotReady",
        }
        self.assertEqual(
            {item["id"] for item in domains["session"]["capabilities"]},
            {f"session.{name}" for name in session_names} | {"drive", "tick", "child_delivery"},
        )
        self.assertIn("export.JsonlRunEventStore", capabilities)
        retired_symbols = {
            "RunState", "ApprovalSnapshot", "CheckpointConfig", "CheckpointExtension",
            "ReconciliationProvider", "ResumeObservation", "DeferredToolHandle",
            "AcceptDeferredDecision", "DeferredResolveDecision", "DeferredResolutionReceipt",
            "DeferredResolutionConflict", "DeferredResolutionStale", "DeferredCheckpointClaimed",
            "DeferredHandleError", "DeferredResolutionError", "DeferredResolutionResultInvalid",
            "ToolCallOutcome", "ExecutionBackend", "InlineBackend", "ThreadBackend", "CeleryBackend",
            "DistributedRunHandle", "DistributedDeliveryOutcome", "DistributedAdvanceDecision",
            "DistributedWaitReason", "DistributedRunEnvelope", "DistributedCapabilityRegistry",
            "CapabilityRef", "RuntimeRecipe", "Checkpoint", "CheckpointStore",
            "InMemoryCheckpointStore", "SqliteCheckpointStore", "RedisCheckpointStore",
            "OperationJournalEntry", "ControllerCommand", "ControllerCommandReceipt",
            "ControllerCommandResolution", "CheckpointCreatedEvent", "CheckpointResumedEvent",
            "ReconciliationRequiredEvent", "ReconciliationResolvedEvent", "ToolCallDeferredEvent",
            "AgentRuntime", "ToolCallRunner", "RunEventStore", "IdempotentRunEventStore",
        }
        public_symbols = {item["python"].rsplit(".", 1)[-1]
                          for domain in fixture["domains"] for item in domain["capabilities"]}
        public_symbols.update(surface["python_target"].rsplit(".", 1)[-1] for surface in fixture["surfaces"])
        self.assertTrue(retired_symbols.isdisjoint(public_symbols), retired_symbols & public_symbols)
        self.assertIn("tools.message", capabilities)
        self.assertNotIn("runtime_backend.cycle_runner", capabilities)
        self.assertIn("agent.sub_agent_config", capabilities)

        surfaces = {surface["id"]: surface for surface in fixture["surfaces"]}
        self.assertEqual(
            {member["id"] for member in surfaces["runner"]["members"]},
            {"run", "start", "stream", "resume", "configured"},
        )
        resume = next(member for member in surfaces["runner"]["members"] if member["id"] == "resume")
        self.assertEqual(
            [parameter["name"] for parameter in resume["python"]["signature"]["parameters"]],
            ["session_id", "turn_id"],
        )
        self.assertEqual(
            {member["id"] for member in surfaces["interactive_session"]["members"]},
            {"messages", "shared_state", "latest_run", "running", "closed", "active_run_handle",
             "subscribe", "close", "steer", "follow_up", "cancel", "approve", "prompt",
             "continue_run", "query", "state"},
        )
        self.assertEqual(surfaces["tool_context"]["members"], [])
        for name in session_names:
            surface = surfaces[f"session_{name}"]
            capability = next(c for c in domains["session"]["capabilities"] if c["id"] == f"session.{name}")
            self.assertEqual(surface["python_target"], capability["python"])
            self.assertTrue(surface["behavior"])
            if name == "SessionStore":
                self.assertEqual({m["id"] for m in surface["members"]}, {"defer_drive", "defer_projection"})
            elif name == "Runtime":
                self.assertEqual([m["id"] for m in surface["members"]], ["children"])
            else:
                self.assertTrue({"members", "protocol_operations", "supporting_operations"}.isdisjoint(surface))
        self.assertTrue(
            {"execution_backend", "checkpoint_config", "checkpoint_extensions", "reconciliation_provider",
             "sub_task_manager", "session"}.isdisjoint(
                {member["id"] for member in surfaces["run_config"]["members"]}
            )
        )
        self.assertEqual(
            {member["id"] for member in surfaces["run_result"]["members"]},
            {"input", "new_items", "final_output", "status", "completion_reason", "completion_tool_name",
             "partial_output", "budget_usage", "budget_exhaustion", "raw_result", "events", "token_usage",
             "trace_id", "run_id", "metadata", "agent_name", "resolved_model", "to_dict"},
        )
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
        fixture = contractctl.load_json(ROOT / "fixtures/manager_tool_envelope.json")
        failed = fixture["sync_failed_outcome"]["expected"]
        self.assertEqual(failed["completion_reason"], "failed")
        self.assertEqual(failed["partial_output"], "last child draft")
        self.assertFalse(fixture["sync_wait_outcome"]["parent_adopts_intermediate_wait"])
        self.assertTrue(fixture["sync_wait_outcome"]["same_turn_reply"])

    def test_completion_event_and_app_server_closure_is_explicit(self) -> None:
        invalid = contractctl.load_json(ROOT / "fixtures/run_events_invalid.json")
        rejected = {case["id"] for case in invalid["reject"]}
        self.assertTrue({"missing_version", "unknown_top_level_field", "session_id_required"} <= rejected)
        app = contractctl.load_json(ROOT / "fixtures/app_server_observable.json")
        projections = {case["name"]: case for case in app["terminal"]["agentStatusProjection"]}
        self.assertEqual(projections["wait_user_is_interrupted_without_error"]["turnStatus"], "interrupted")
        self.assertEqual(projections["wait_user_is_interrupted_without_error"]["errorField"], "omitted")
        self.assertEqual(projections["cancelled_failure_stays_failed"]["turnStatus"], "failed")
        self.assertEqual(projections["budget_exhaustion_is_failed_with_typed_observation"]["completionReason"], "budget_exhausted")


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

    def test_run_definition_has_rfc8785_golden_bytes_and_digests(self) -> None:
        fixture = contractctl.load_json(ROOT / "fixtures/run_definition.json")
        self.assertEqual(fixture["canonicalization"]["algorithm"], "RFC 8785 JSON Canonicalization Scheme")
        self.assertEqual(fixture["reserved_task_metadata"], "vv_session")
        for case in fixture["golden_cases"]:
            raw = base64.b64decode(case["bytes_base64"], validate=True)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), case["sha256"])
            self.assertEqual(case["definition_digest"], case["sha256"])
            self.assertEqual(json.loads(raw), case["definition"])
            self.assertEqual(set(case["definition"]), set(fixture["required_fields"]))
        self.assertFalse(fixture["top_level_field_policy"]["closed"])
        self.assertEqual(fixture["top_level_field_policy"]["validation_owner"], "opaque J in turn_started.definition")
        self.assertEqual({case["expected_digest_relation"] for case in fixture["producer_cases"]
                          if "expected_digest_relation" in case}, {"equal", "different"})
        subprocess.run(["node", str(ROOT / "scripts/verify_jcs.mjs")], check=True, capture_output=True)

    def test_rfc8785_vectors_match_ecmascript_reference_serialization(self) -> None:
        subprocess.run(
            ["node", str(ROOT / "scripts/verify_jcs.mjs")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )


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

            self.assertEqual(synced["fixture_files"], 54)
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
                "https://github.com/AndersonBY/vv-agent-contract/actions/runs/123",
                verified_at="2026-07-13T12:00:00Z",
            )
            self.assertEqual(matrix["status"], "verified")
            self.assertEqual(
                matrix["adoption_note"],
                f"v{matrix['contract_version']} passed the required implementation snapshots "
                "and cross-repository producer gates.",
            )
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
