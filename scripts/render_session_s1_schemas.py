#!/usr/bin/env python3
"""Render the language-neutral S1 logical and storage schemas."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
DRAFT = "https://json-schema.org/draft/2020-12/schema"


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/$defs/{name}"}


def nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def array(schema: dict[str, Any], *, unique: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "array", "items": schema}
    if unique:
        result["uniqueItems"] = True
    return result


def obj(
    properties: dict[str, Any], *, required: tuple[str, ...] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties if required is None else required),
    }


def enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


TEXT = {"type": "string", "minLength": 1}
S_TEXT = {"type": "string"}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$", "maxLength": 64}
POSITIVE = {"type": "integer", "minimum": 1}
NONNEGATIVE = {"type": "integer", "minimum": 0}
NULLABLE_TEXT = nullable(TEXT)
NULLABLE_HASH = nullable(HASH)
NULLABLE_POSITIVE = nullable(POSITIVE)


def content_labels() -> dict[str, Any]:
    return obj(
        {
            "source": {
                "type": "array",
                "items": enum("system", "user", "internal", "untrusted"),
                "uniqueItems": True,
            },
            "classification": enum("public", "internal", "confidential", "restricted"),
        }
    )


def content_ref() -> dict[str, Any]:
    return obj(
        {
            "content_id": TEXT,
            "mac": HASH,
            "size": NONNEGATIVE,
            "key_id": TEXT,
            "labels": ref("ContentLabels"),
        }
    )


def principal() -> dict[str, Any]:
    return obj(
        {
            "tenant_id": TEXT,
            "subject_id": TEXT,
            "subject_kind": enum("user", "service", "agent"),
            "attributes": ref("ContentRef"),
        }
    )


def admission_proof() -> dict[str, Any]:
    signature = {
        "type": "string",
        "minLength": 4,
        "pattern": "^(?:[A-Za-z0-9+/]{4})+(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$",
    }
    return nullable(
        obj(
            {
                "admission_key_id": TEXT,
                "admission_signature": signature,
                "admission_signed_ms": NONNEGATIVE,
            }
        )
    )


def input_proof() -> dict[str, Any]:
    signature = {
        "type": "string",
        "minLength": 4,
        "pattern": "^(?:[A-Za-z0-9+/]{4})+(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$",
    }
    return nullable(
        obj(
            {
                "input_seq": POSITIVE,
                "received_ms": NONNEGATIVE,
                "key_id": TEXT,
                "signature": signature,
                "signed_ms": NONNEGATIVE,
            }
        )
    )


def policy_decision() -> dict[str, Any]:
    return nullable(
        obj(
            {
                "policy_digest": HASH,
                "rule_id": TEXT,
                "effect": enum("allow", "deny", "require_approval"),
            }
        )
    )


def tokenizer_binding() -> dict[str, Any]:
    return nullable(
        obj(
            {
                "model_identity": TEXT,
                "counting_method": enum("provider_reported", "tokenizer"),
                "implementation_id": TEXT,
                "asset_identity": TEXT,
                "normalization_id": TEXT,
            }
        )
    )


def cache_usage() -> dict[str, Any]:
    optional_count = nullable(NONNEGATIVE)
    return obj(
        {
            "status": enum("provider_reported", "accounting_missing", "unsupported"),
            "read_input_tokens": optional_count,
            "write_input_tokens": optional_count,
            "uncached_input_tokens": optional_count,
        }
    )


def token_counts() -> dict[str, Any]:
    optional_count = nullable(NONNEGATIVE)
    return obj(
        {
            "input_tokens": optional_count,
            "output_tokens": optional_count,
            "total_tokens": optional_count,
            "reasoning_tokens": optional_count,
            "usage_source": enum("provider_reported", "estimated", "accounting_missing"),
            "cache_usage": ref("CacheUsage"),
        }
    )


def budget_counts() -> dict[str, Any]:
    dimensions = enum(
        "total_tokens",
        "uncached_input_tokens",
        "tool_calls",
        "tool_calls_by_name",
        "wall_time",
        "host_cost",
    )
    reasons = enum(
        "accounting_missing",
        "usage_missing",
        "meter_missing",
        "meter_unavailable",
        "meter_error",
        "unit_mismatch",
        "currency_mismatch",
        "non_monotonic",
        "integer_overflow",
    )
    host_cost = nullable(
        obj(
            {
                "amount_microunits": NONNEGATIVE,
                "unit": ref("ContentRef"),
                "currency": nullable(ref("ContentRef")),
            }
        )
    )
    return obj(
        {
            "cycles": NONNEGATIVE,
            "tool_calls": NONNEGATIVE,
            "elapsed_ms": NONNEGATIVE,
            "total_tokens": nullable(NONNEGATIVE),
            "uncached_input_tokens": nullable(NONNEGATIVE),
            "tool_calls_by_name": {
                "type": "object",
                "additionalProperties": NONNEGATIVE,
            },
            "host_cost": host_cost,
            "unavailable_dimensions": array(
                obj({"dimension": dimensions, "reason": reasons})
            ),
        }
    )


def usage_counts() -> dict[str, Any]:
    return obj(
        {
            "tokens": nullable(ref("TokenCounts")),
            "budget": nullable(ref("BudgetCounts")),
        }
    )


def requirements() -> dict[str, Any]:
    return obj(
        {
            "level": POSITIVE,
            "handler_version": nullable(TEXT),
            "capabilities": array(TEXT, unique=True),
        }
    )


BOOTSTRAP_INBOX_KINDS = ("user", "follow_up", "model_selection")
AFTER_CYCLE_STOP_CODES = (
    "host.policy_stop",
    "host_stop",
    "hook_stop",
    "stopped",
)


def environment_binding() -> dict[str, Any]:
    return nullable(
        obj(
            {
                "descriptor": ref("ContentRef"),
                "environment_capabilities": array(TEXT, unique=True),
                "capabilities_digest": nullable(HASH),
                "network_policy_ref_digest": nullable(HASH),
                "isolation_policy_ref_digest": nullable(HASH),
                "operational_policy": nullable(ref("ContentRef")),
            }
        )
    )


def execution_environment_capability_fields() -> dict[str, Any]:
    return {
        "environment_id": TEXT,
        "generation": NONNEGATIVE,
        "isolation": enum("none", "container", "microvm"),
        "network": enum("open", "allowlist", "none"),
        "enforces_network_policy": {"type": "boolean"},
        "enforces_resource_limits": {"type": "boolean"},
        "persistent": {"type": "boolean"},
        "environment_capabilities": array(TEXT, unique=True),
        "capabilities_digest": NULLABLE_HASH,
        "network_policy_ref_digest": NULLABLE_HASH,
        "isolation_policy_ref_digest": NULLABLE_HASH,
    }


def execution_environment_binding() -> dict[str, Any]:
    return obj(
        {
            "descriptor": ref("ContentRef"),
            **execution_environment_capability_fields(),
            "operational_policy": ref("ContentRef"),
        }
    )


def execution_identity() -> dict[str, Any]:
    return obj(
        {
            "operation_key": TEXT,
            "tenant_id": TEXT,
            "environment_id": TEXT,
            "session_id": TEXT,
            "operation_id": TEXT,
            "execution_id": HASH,
        }
    )


def provider_lookup_defs() -> dict[str, Any]:
    handle = obj(
        {
            "kind": {"const": "provider", "type": "string"},
            "provider": TEXT,
            "job_id": TEXT,
            "operation_id": TEXT,
            "attempt": POSITIVE,
            "request_digest": HASH,
            "execution_id": HASH,
            "command_digest": HASH,
            "environment_id": TEXT,
            "generation": NONNEGATIVE,
            "evidence": array(TEXT),
            "query_ref": nullable(TEXT),
            "cancel_ref": nullable(TEXT),
        }
    )
    binding = obj(
        {
            "tenant_id": TEXT,
            "session_id": TEXT,
            "operation_id": TEXT,
            "attempt": POSITIVE,
            "request_digest": HASH,
            "idempotency_key": TEXT,
            "execution_id": HASH,
            "command_digest": HASH,
            "environment_id": TEXT,
            "generation": NONNEGATIVE,
            "provider_id": TEXT,
        }
    )
    accepted = obj(
        {
            "kind": {"const": "Accepted", "type": "string"},
            "handle": handle,
            "yield_on_steer": {"type": "boolean"},
        }
    )
    definitive = obj(
        {
            "kind": {"const": "Definitive", "type": "string"},
            "result": {"type": "object"},
            "usage": {"type": "object"},
            "shared_state": nullable({"type": "object"}),
            "evidence": array(TEXT),
        }
    )
    unknown = obj(
        {
            "kind": {"const": "Unknown", "type": "string"},
            "reason": TEXT,
        }
    )
    result = obj(
        {
            "schema_version": {
                "const": "vv-agent.provider-lookup.v1",
                "type": "string",
            },
            "status": enum("not_started", "running", "exited", "unknown"),
            "binding": binding,
            "outcome": {
                "anyOf": [
                    {"type": "null"},
                    accepted,
                    definitive,
                    unknown,
                ]
            },
            "evidence": array(TEXT),
        }
    )
    return {
        "ProviderExecutionHandle": handle,
        "ProviderLookupBinding": binding,
        "ProviderLookupAcceptedOutcome": accepted,
        "ProviderLookupDefinitiveOutcome": definitive,
        "ProviderLookupUnknownOutcome": unknown,
        "ProviderLookupResult": result,
    }


def result_id() -> dict[str, Any]:
    return obj({"operation_id": TEXT, "attempt": POSITIVE})


def delivery_target() -> dict[str, Any]:
    return obj(
        {
            "session_id": TEXT,
            "turn_id": TEXT,
            "generation": NONNEGATIVE,
            "operation_id": TEXT,
            "attempt": POSITIVE,
        }
    )


def child_identity() -> dict[str, Any]:
    return obj({"session_id": TEXT, "turn_id": TEXT, "generation": NONNEGATIVE})


def handle() -> dict[str, Any]:
    return {"oneOf": [ref(name) for name in ("ProviderHandle", "ApprovalHandle", "UserHandle", "ChildHandle")]}


def delegation() -> dict[str, Any]:
    return obj(
        {
            "mode": enum("configured", "agent_as_tool", "background_task", "handoff"),
            "agent_name": ref("ContentRef"),
            "handoff_count": NONNEGATIVE,
            "max_handoffs": NONNEGATIVE,
            "metadata": ref("ContentRef"),
        }
    )


def boundary_payloads() -> dict[str, Any]:
    shell = {
        "boundary_id": TEXT,
        "stage": {"type": "string"},
        "source_operation_id": NULLABLE_TEXT,
        "source_digest": NULLABLE_HASH,
        "data": {},
    }

    def branch(stage: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "allOf": [
                obj(shell),
                {
                    "type": "object",
                    "properties": {
                        "stage": {"const": stage},
                        "data": data,
                    },
                },
            ]
        }

    return {
        "oneOf": [
            branch("before_memory", ref("BeforeMemoryData")),
            branch("after_cycle", ref("AfterCycleData")),
            branch("memory_started", ref("MemoryEventData")),
            branch("memory_completed", ref("MemoryEventData")),
            branch("session_memory_saved", ref("SessionMemorySavedData")),
            branch("output_checked", ref("OutputCheckedData")),
            branch("budget", ref("BudgetBoundaryData")),
        ]
    }


def inbox_payload_defs() -> dict[str, Any]:
    provider_handle = obj(
        {
            "kind": {"const": "provider"},
            "provider": TEXT,
            "job_id": ref("ContentRef"),
            "operation_id": TEXT,
            "attempt": POSITIVE,
            "request_digest": HASH,
            "evidence": ref("ContentRef"),
            "query_ref": nullable(ref("ContentRef")),
            "cancel_ref": nullable(ref("ContentRef")),
        }
    )
    approval_handle = obj(
        {
            "kind": {"const": "approval"},
            "request_id": TEXT,
            "request_digest": HASH,
            "scope": ref("ContentRef"),
        }
    )
    user_handle = obj(
        {
            "kind": {"const": "user"},
            "interaction_id": TEXT,
            "question": ref("ContentRef"),
        }
    )
    child_handle = obj(
        {
            "kind": {"const": "child"},
            "session_id": TEXT,
            "turn_id": TEXT,
            "generation": NONNEGATIVE,
            "background": {"type": "boolean"},
            "delivery_target": ref("DeliveryTarget"),
            "siblings": array(ref("ChildIdentity")),
        },
        required=(
            "kind",
            "session_id",
            "turn_id",
            "generation",
            "background",
            "delivery_target",
        ),
    )
    approval = obj(
        {
            "operation_id": TEXT,
            "attempt": POSITIVE,
            "request_id": TEXT,
            "request_digest": HASH,
            "decision": enum(
                "allow_session",
                "approve",
                "deny",
                "timeout",
                "approve_once",
                "approve_for_session",
            ),
            "scope": ref("ContentRef"),
            "reason": nullable(ref("ContentRef")),
            "metadata": nullable(ref("ContentRef")),
            "policy_digest": NULLABLE_HASH,
            "rule_id": NULLABLE_TEXT,
            "expires_ms": nullable(NONNEGATIVE),
        },
        required=(
            "operation_id",
            "attempt",
            "request_id",
            "request_digest",
            "decision",
            "scope",
        ),
    )
    return {
        "ProviderHandle": provider_handle,
        "ApprovalHandle": approval_handle,
        "UserHandle": user_handle,
        "ChildHandle": child_handle,
        "DeliveryTarget": delivery_target(),
        "ChildIdentity": child_identity(),
        "Delegation": delegation(),
        "ModelSelectionPayload": obj({"selection": nullable(ref("ContentRef"))}),
        "ContentPayload": obj({"content": ref("ContentRef")}),
        "ProviderResultPayload": obj(
            {
                "operation_id": TEXT,
                "attempt": POSITIVE,
                "request_digest": HASH,
                "provider_binding": NULLABLE_TEXT,
                "result": nullable(ref("ContentRef")),
                "usage": ref("ContentRef"),
                "evidence": ref("ContentRef"),
            }
        ),
        "ApprovalAnswerPayload": approval,
        "ChildResultPayload": obj(
            {
                "session_id": TEXT,
                "turn_id": TEXT,
                "operation_id": TEXT,
                "attempt": POSITIVE,
                "status": enum("running", "completed", "failed", "cancelled", "aborted"),
                "result": nullable(ref("ContentRef")),
                "terminal_seq": nullable(POSITIVE),
                "terminal_digest": nullable(HASH),
            }
        ),
        "ControlPayload": obj({"action": enum("close", "archive", "suspend", "resume", "cancel", "abort")}),
        "ProviderEvidencePayload": obj(
            {
                "operation_id": TEXT,
                "attempt": POSITIVE,
                "request_digest": HASH,
                "handle": ref("ProviderHandle"),
                "yield_on_steer": {"const": True, "type": "boolean"},
            },
            required=("operation_id", "attempt", "request_digest", "handle"),
        ),
        "ProviderEvidencePayloadLevel3": obj(
            {
                "operation_id": TEXT,
                "attempt": POSITIVE,
                "request_digest": HASH,
                "provider_lookup": ref("ContentRef"),
            }
        ),
    }


def record_payload_defs() -> dict[str, Any]:
    session_created = {
        "principal": ref("Principal"),
        "workspace": ref("ContentRef"),
        "parent_session_id": NULLABLE_TEXT,
        "parent_operation_id": NULLABLE_TEXT,
        "attributes": ref("ContentRef"),
    }
    turn_started = {
        "input_ids": array(TEXT),
        "definition": ref("ContentRef"),
        "definition_digest": HASH,
        "handler_version": TEXT,
        "budget": ref("ContentRef"),
        "binding": NULLABLE_TEXT,
        "generation": NONNEGATIVE,
        "policy_digest": NULLABLE_HASH,
        "requirements": ref("SessionRequirements"),
        "tokenizer_binding": ref("TokenizerBinding"),
        "environment": ref("EnvironmentBinding"),
    }
    op_planned = {
        "op_kind": enum("model", "tool", "interaction"),
        "purpose": nullable(enum("primary", "compaction", "session_memory", "output_repair")),
        "request": ref("ContentRef"),
        "request_digest": HASH,
        "context_version": TEXT,
        "dependencies": array(TEXT),
        "tool": nullable(ref("ContentRef")),
        "idempotency_key": NULLABLE_TEXT,
        "budget_admission": ref("ContentRef"),
        "not_before_ms": nullable(NONNEGATIVE),
        "provider_binding": NULLABLE_TEXT,
        "consumed_unknowns": array(ref("ResultId")),
        "policy_decision": ref("PolicyDecision"),
    }
    return {
        "SessionCreatedPayload": obj(session_created),
        "SessionCreatedPayloadLevel2": obj(
            {**session_created, "bootstrap": ref("SessionRequirements")}
        ),
        "TurnStartedPayload": obj(turn_started),
        "TurnStartedPayloadLevel3": obj(
            {
                **turn_started,
                "environment": ref("ExecutionEnvironmentBinding"),
            }
        ),
        "InputAppliedPayload": obj(
            {
                "input": ref("InboxItem"),
                "input_digest": HASH,
                "input_proof": ref("InputProof"),
                "disposition": enum("applied", "rejected", "noop", "queued"),
                "reason": nullable(ref("ContentRef")),
                "target_operation_id": NULLABLE_TEXT,
                "target_wait_id": NULLABLE_TEXT,
                "position": TEXT,
                "model_binding": ref("ContentRef"),
            },
            required=(
                "input",
                "input_digest",
                "input_proof",
                "disposition",
                "reason",
                "target_operation_id",
                "target_wait_id",
                "position",
            ),
        ),
        "OpPlannedPayload": obj(op_planned),
        "OpPlannedPayloadLevel3": obj(
            {
                **op_planned,
                "execution_identity": ref("ExecutionIdentity"),
                "command_digest": HASH,
            }
        ),
        "OpPreparedPayloadLevel3": obj(
            {
                "request": ref("ContentRef"),
                "request_digest": HASH,
                "op_kind": {"const": "tool", "type": "string"},
                "tool": ref("ContentRef"),
                "provider_binding": TEXT,
                "idempotency_key": TEXT,
                "hook_result": nullable(ref("ContentRef")),
                "shared_state": ref("ContentRef"),
                "policy_decision": ref("PolicyDecision"),
                "command_digest": HASH,
            }
        ),
        "OpPreparedPayload": obj(
            {
                "request": ref("ContentRef"),
                "request_digest": HASH,
                "op_kind": enum("tool", "interaction"),
                "tool": ref("ContentRef"),
                "provider_binding": NULLABLE_TEXT,
                "idempotency_key": NULLABLE_TEXT,
                "hook_result": nullable(ref("ContentRef")),
                "shared_state": ref("ContentRef"),
                "policy_decision": ref("PolicyDecision"),
            }
        ),
        "TurnParkedPayload": obj(
            {
                "interaction_id": TEXT,
                "question": ref("ContentRef"),
                "source_operation_id": TEXT,
                "source_attempt": POSITIVE,
            }
        ),
        "OpStartedPayload": obj(
            {
                "dispatch_id": TEXT,
                "authorization_version": TEXT,
                "epoch": POSITIVE,
                "mode": enum("sync", "provider", "managed"),
                "endpoint_id": TEXT,
            },
            required=("dispatch_id", "authorization_version", "epoch", "mode"),
        ),
        "OpParkedPayload": obj(
            {
                "phase": enum("before_dispatch", "after_dispatch"),
                "handle": ref("Handle"),
                "poll_at_ms": nullable(NONNEGATIVE),
                "deadline_ms": nullable(NONNEGATIVE),
                "interaction_result": nullable(ref("ContentRef")),
                "delegation": ref("Delegation"),
                "yield_on_steer": {"const": True, "type": "boolean"},
                "yieldable_children": array(TEXT),
            },
            required=("phase", "handle", "poll_at_ms", "deadline_ms"),
        ),
        "OpCompletedPayload": obj(
            {
                "result": ref("ContentRef"),
                "result_digest": HASH,
                "usage": ref("ContentRef"),
                "usage_counts": ref("UsageCounts"),
                "shared_state": nullable(ref("ContentRef")),
                "evidence": ref("ContentRef"),
                "execution_started": {"type": "boolean"},
                "context": enum("normal", "correction", "audit"),
                "request_digest": HASH,
                "provider_binding": NULLABLE_TEXT,
                "policy_decision": ref("PolicyDecision"),
                "yielded_by": TEXT,
            },
            required=(
                "result",
                "result_digest",
                "usage",
                "shared_state",
                "evidence",
                "execution_started",
                "context",
                "request_digest",
                "provider_binding",
                "policy_decision",
            ),
        ),
        "OpUnknownPayload": obj(
            {
                "reason": ref("ContentRef"),
                "dispatch_evidence": ref("ContentRef"),
                "observation": ref("ContentRef"),
                "retry": enum("retry", "stop", "manual"),
                "retry_at_ms": nullable(NONNEGATIVE),
                "duplicate_cost_risk": {"type": "boolean"},
                "measurement_missing": {"type": "boolean"},
            }
        ),
        "ContextCompactedPayload": obj(
            {
                "source_digest": HASH,
                "prefix_ids": array(TEXT),
                "tail_ids": array(TEXT),
                "mode": enum("micro", "summary", "emergency"),
                "summary_operation_id": NULLABLE_TEXT,
                "replacement": array(ref("ContentRef")),
                "evidence_manifest": ref("ContentRef"),
                "micro_usage": obj(
                    {
                        "archived_count": NONNEGATIVE,
                        "reclaimed_tokens": NONNEGATIVE,
                        "artifact_failure_count": NONNEGATIVE,
                    }
                ),
            },
            required=(
                "source_digest",
                "prefix_ids",
                "tail_ids",
                "mode",
                "summary_operation_id",
                "replacement",
                "evidence_manifest",
            ),
        ),
        "BoundaryRecordedPayload": boundary_payloads(),
        "UsageObservedPayload": obj(
            {
                "meter_id": TEXT,
                "observation": POSITIVE,
                "mode": enum("cumulative", "correction"),
                "usage": ref("ContentRef"),
                "source": ref("ContentRef"),
            }
        ),
        "TurnEndedPayload": obj(
            {
                "status": enum("completed", "failed", "cancelled", "aborted"),
                "reason": nullable(ref("ContentRef")),
                "result": nullable(ref("ContentRef")),
                "adopted_results": array(ref("ResultId")),
                "budget": ref("ContentRef"),
                "unconfirmed_operations": array(TEXT),
            }
        ),
    }


def common_defs() -> dict[str, Any]:
    return {
        "ContentLabels": content_labels(),
        "ContentRef": content_ref(),
        "Principal": principal(),
        "AdmissionProof": admission_proof(),
        "InputProof": input_proof(),
        "PolicyDecision": policy_decision(),
        "TokenizerBinding": tokenizer_binding(),
        "CacheUsage": cache_usage(),
        "TokenCounts": token_counts(),
        "BudgetCounts": budget_counts(),
        "UsageCounts": usage_counts(),
        "SessionRequirements": requirements(),
        "EnvironmentBinding": environment_binding(),
        "ExecutionEnvironmentBinding": execution_environment_binding(),
        "ExecutionIdentity": execution_identity(),
        **provider_lookup_defs(),
        "ResultId": result_id(),
        **inbox_payload_defs(),
        "BeforeMemoryData": obj(
            {"messages": array(ref("ContentRef")), "shared_state": ref("ContentRef")}
        ),
        "AfterCycleData": obj(
            {
                "action": enum("continue", "steer", "stop_non_success"),
                "steering_messages": array(ref("ContentRef")),
                "disallow_tools": array(TEXT),
                "stop": nullable(
                    obj(
                        {
                            "code": enum(*AFTER_CYCLE_STOP_CODES),
                            "message": ref("ContentRef"),
                        }
                    )
                ),
                "shared_state": ref("ContentRef"),
                "error": nullable(ref("ContentRef")),
            }
        ),
        "MemoryEventData": obj({"event": ref("ContentRef")}),
        "SessionMemorySavedData": obj(
            {
                "state": obj(
                    {
                        "last_extracted_message_index": nullable(POSITIVE),
                        "tokens_at_last_extraction": NONNEGATIVE,
                        "initialized": {"type": "boolean"},
                        "entries": array(
                            obj(
                                {
                                    "category": TEXT,
                                    "source_cycle": NONNEGATIVE,
                                    "importance": NONNEGATIVE,
                                    "content": ref("ContentRef"),
                                }
                            )
                        ),
                    }
                )
            }
        ),
        "OutputCheckedData": obj(
            {
                "status": enum("completed", "repair", "failed"),
                "reason": nullable(ref("ContentRef")),
                "value": ref("ContentRef"),
                "partial_output": nullable(ref("ContentRef")),
            },
            required=("status", "reason", "value"),
        ),
        "BudgetBoundaryData": obj(
            {
                "tool_names": array(TEXT),
                "usage": ref("ContentRef"),
                "exhaustion": nullable(ref("ContentRef")),
            }
        ),
    }


def inbox_kind_map() -> dict[str, str]:
    return {
        "user": "ContentPayload",
        "steer": "ContentPayload",
        "follow_up": "ContentPayload",
        "provider_result": "ProviderResultPayload",
        "approval_answer": "ApprovalAnswerPayload",
        "child_result": "ChildResultPayload",
        "control": "ControlPayload",
        "provider_evidence": "ProviderEvidencePayload",
        "model_selection": "ModelSelectionPayload",
    }


def record_kind_map() -> dict[str, str]:
    return {
        "session_created": "SessionCreatedPayload",
        "turn_started": "TurnStartedPayload",
        "input_applied": "InputAppliedPayload",
        "op_planned": "OpPlannedPayload",
        "op_prepared": "OpPreparedPayload",
        "turn_parked": "TurnParkedPayload",
        "op_started": "OpStartedPayload",
        "op_parked": "OpParkedPayload",
        "op_completed": "OpCompletedPayload",
        "op_unknown": "OpUnknownPayload",
        "context_compacted": "ContextCompactedPayload",
        "boundary_recorded": "BoundaryRecordedPayload",
        "usage_observed": "UsageObservedPayload",
        "turn_ended": "TurnEndedPayload",
    }


def record_schema() -> dict[str, Any]:
    defs = common_defs()
    defs.update(record_payload_defs())
    defs["RecordEnvelope"] = obj(
        {
            "schema_version": {"const": "S1", "type": "string"},
            "feature_level": {"const": 1, "type": "integer"},
            "record_id": TEXT,
            "kind": {"type": "string"},
            "session_id": TEXT,
            "turn_id": NULLABLE_TEXT,
            "operation_id": NULLABLE_TEXT,
            "attempt": NULLABLE_POSITIVE,
            "payload": {"type": "object"},
        }
    )
    defs["RecordEnvelopeLevel2"] = obj(
        {
            "schema_version": {"const": "S1", "type": "string"},
            "feature_level": {"const": 2, "type": "integer"},
            "record_id": TEXT,
            "kind": {"type": "string"},
            "session_id": TEXT,
            "turn_id": NULLABLE_TEXT,
            "operation_id": NULLABLE_TEXT,
            "attempt": NULLABLE_POSITIVE,
            "payload": {"type": "object"},
        }
    )
    defs["RecordEnvelopeLevel3"] = obj(
        {
            "schema_version": {"const": "S1", "type": "string"},
            "feature_level": {"const": 3, "type": "integer"},
            "record_id": TEXT,
            "kind": {"type": "string"},
            "session_id": TEXT,
            "turn_id": NULLABLE_TEXT,
            "operation_id": NULLABLE_TEXT,
            "attempt": NULLABLE_POSITIVE,
            "payload": {"type": "object"},
        }
    )
    defs["InboxItem"] = inbox_schema_item(defs)
    defs["Handle"] = handle()
    branches = []
    for kind, payload_name in record_kind_map().items():
        branches.append(
            {
                "allOf": [
                    ref("RecordEnvelope"),
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"const": kind},
                            "payload": ref(payload_name),
                        },
                    },
                ]
            }
        )
    branches.append(
        {
            "allOf": [
                ref("RecordEnvelopeLevel2"),
                {
                    "type": "object",
                    "properties": {
                        "kind": {"const": "session_created"},
                        "payload": ref("SessionCreatedPayloadLevel2"),
                    },
                },
            ]
        }
    )
    for kind, payload_name in (
        ("turn_started", "TurnStartedPayloadLevel3"),
        ("op_planned", "OpPlannedPayloadLevel3"),
        ("op_prepared", "OpPreparedPayloadLevel3"),
    ):
        branches.append(
            {
                "allOf": [
                    ref("RecordEnvelopeLevel3"),
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"const": kind},
                            "payload": ref(payload_name),
                        },
                    },
                ]
            }
        )
    return {"$schema": DRAFT, "oneOf": branches, "$defs": defs}


def inbox_schema_item(defs: dict[str, Any]) -> dict[str, Any]:
    common = {
        "schema_version": {"const": "S1", "type": "string"},
        "actor": ref("Principal"),
        "admission_proof": ref("AdmissionProof"),
        "input_id": TEXT,
        "kind": {"type": "string"},
        "target_turn_id": NULLABLE_TEXT,
        "generation": nullable(NONNEGATIVE),
        "available_ms": NONNEGATIVE,
        "payload": {"type": "object"},
    }
    envelope = obj({"feature_level": {"const": 1, "type": "integer"}, **common})
    level2_envelope = obj(
        {
            "feature_level": {"const": 2, "type": "integer"},
            **common,
            "requirements": ref("SessionRequirements"),
        }
    )
    level3_envelope = obj(
        {
            "feature_level": {"const": 3, "type": "integer"},
            **common,
        }
    )
    branches = []
    for kind, payload_name in inbox_kind_map().items():
        branches.append(
            {
                "allOf": [
                    ref("InboxEnvelope"),
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"const": kind},
                            "payload": ref(payload_name),
                        },
                    },
                ]
            }
        )
    for kind in BOOTSTRAP_INBOX_KINDS:
        branches.append(
            {
                "allOf": [
                    ref("InboxEnvelopeLevel2"),
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"const": kind},
                            "payload": ref(inbox_kind_map()[kind]),
                        },
                    },
                ]
            }
        )
    branches.append(
        {
            "allOf": [
                ref("InboxEnvelopeLevel3"),
                {
                    "type": "object",
                    "properties": {
                        "kind": {"const": "provider_evidence"},
                        "payload": ref("ProviderEvidencePayloadLevel3"),
                    },
                },
            ]
        }
    )
    defs["InboxEnvelope"] = envelope
    defs["InboxEnvelopeLevel2"] = level2_envelope
    defs["InboxEnvelopeLevel3"] = level3_envelope
    return {"oneOf": branches}


def inbox_schema() -> dict[str, Any]:
    defs = common_defs()
    item = inbox_schema_item(defs)
    defs["InboxItem"] = item
    defs["Handle"] = handle()
    return {"$schema": DRAFT, "oneOf": item["oneOf"], "$defs": defs}


def storage_envelope_schema() -> dict[str, Any]:
    envelope = obj(
        {
            "schema_version": {"const": "S1", "type": "string"},
            "tenant_id": TEXT,
            "session_id": TEXT,
            "seq": POSITIVE,
            "record_digest": HASH,
            "chain_digest": HASH,
            "writer_epoch": NONNEGATIVE,
            "created_ms": NONNEGATIVE,
        }
    )
    case_fields = {
        "name": TEXT,
        "logical_record": {"type": "object"},
        "logical_record_digest": HASH,
        "previous_chain_digest": HASH,
        "reason": nullable(TEXT),
    }
    case = {
        "oneOf": [
            obj(
                {
                    **case_fields,
                    "accepted": {"const": True, "type": "boolean"},
                    "envelope": envelope,
                }
            ),
            obj(
                {
                    **case_fields,
                    "accepted": {"const": False, "type": "boolean"},
                    "envelope": {"type": "object"},
                    "reason": TEXT,
                }
            ),
        ]
    }
    return {
        "$schema": DRAFT,
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": "vv-agent.session-storage-envelope-cases.v1"},
            "status": {"const": "contract-allocation-only"},
            "framing": ref("Framing"),
            "cases": array(case),
        },
        "required": ["schema_version", "status", "framing", "cases"],
        "$defs": {
            "Framing": obj(
                {
                    "domain": {"const": "vv-agent/S1"},
                    "initial_formula": {
                        "const": "SHA256(UTF8(domain)||LP(tenant_id)||LP(session_id))"
                    },
                    "next_formula": {
                        "const": "SHA256(previous_chain||U64BE(seq)||HEX_DECODE(record_digest))"
                    },
                    "identifier_encoding": {"const": "UTF-8 with unsigned 32-bit big-endian byte length prefix"},
                    "identity_rule": {"const": "chain_digest is excluded from logical record bytes and record identity"},
                }
            ),
            "Envelope": envelope,
        },
    }


def lifecycle_schema() -> dict[str, Any]:
    signature = {
        "type": "string",
        "minLength": 4,
        "pattern": "^(?:[A-Za-z0-9+/]{4})+(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$",
    }
    key_capability = obj(
        {
            "tenant_id": TEXT,
            "session_id": TEXT,
            "key_id": TEXT,
            "provider_id": TEXT,
            "capability_id": TEXT,
            "state": enum("active", "destroying", "destroyed"),
        }
    )
    destroy_case = obj(
        {
            "name": TEXT,
            "request": obj(
                {
                    "domain": {"const": "vv-agent/S1/key-destroy"},
                    "tenant_id": TEXT,
                    "key_id": TEXT,
                }
            ),
            "accepted": {"type": "boolean"},
            "status": enum("destroyed", "already_destroyed", "key_unavailable", "binding_mismatch"),
            "evidence_id": nullable(TEXT),
            "reason": nullable(TEXT),
        }
    )
    tombstone = obj(
        {
            "tenant_id": TEXT,
            "session_id": TEXT,
            "final_seq": POSITIVE,
            "chain_digest": HASH,
            "deleted_ms": NONNEGATIVE,
            "actor": ref("Principal"),
            "key_id": TEXT,
            "signature": signature,
            "state": enum("pending", "complete"),
            "scope_root_session_id": TEXT,
        }
    )
    export_header = obj(
        {
            "line": {"const": "header"},
            "export_version": {"const": 1, "type": "integer"},
            "storage_major": {"const": "S1"},
            "tenant_id": TEXT,
            "session_id": TEXT,
            "head_seq": NONNEGATIVE,
            "chain_digest": HASH,
            "content_mode": enum("skeleton", "include-content"),
        }
    )
    export_lines = {
        "oneOf": [
            obj(
                {
                    "line": {"const": "record"},
                    "storage_envelope": ref("StorageEnvelope"),
                    "record": {"type": "object"},
                }
            ),
            obj(
                {
                    "line": {"const": "inbox"},
                    "input_seq": POSITIVE,
                    "received_ms": NONNEGATIVE,
                    "consumed_seq": nullable(NONNEGATIVE),
                    "input": {"type": "object"},
                }
            ),
            obj(
                {
                    "line": {"const": "content"},
                    "content_id": TEXT,
                    "key_id": TEXT,
                    "slot": TEXT,
                    "decoded_value": {},
                }
            ),
            obj(
                {
                    "line": {"const": "checkpoint"},
                    "seq": POSITIVE,
                    "chain_digest": HASH,
                    "key_id": TEXT,
                    "signature": signature,
                    "signed_ms": NONNEGATIVE,
                }
            ),
            obj(
                {
                    "line": {"const": "manifest"},
                    "record_lines": NONNEGATIVE,
                    "inbox_lines": NONNEGATIVE,
                    "checkpoint_lines": NONNEGATIVE,
                    "head_seq": NONNEGATIVE,
                    "chain_digest": HASH,
                }
            ),
        ]
    }
    export_case = {
        "oneOf": [
            obj(
                {
                    "name": TEXT,
                    "accepted": {"const": True, "type": "boolean"},
                    "header": ref("ExportHeader"),
                    "lines": array(ref("ExportLine")),
                    "reason": nullable(TEXT),
                }
            ),
            obj(
                {
                    "name": TEXT,
                    "accepted": {"const": False, "type": "boolean"},
                    "header": {"type": "object"},
                    "lines": array({"type": "object"}),
                    "reason": TEXT,
                }
            ),
        ]
    }
    forget_case = {
        "oneOf": [
            obj(
                {
                    "name": TEXT,
                    "tombstone": ref("Tombstone"),
                    "accepted": {"const": True, "type": "boolean"},
                    "reason": nullable(TEXT),
                }
            ),
            obj(
                {
                    "name": TEXT,
                    "tombstone": {"type": "object"},
                    "accepted": {"const": False, "type": "boolean"},
                    "reason": TEXT,
                }
            ),
        ]
    }
    return {
        "$schema": DRAFT,
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": "vv-agent.session-storage-lifecycle.v1"},
            "status": {"const": "contract-allocation-only"},
            "key_capability": key_capability,
            "destroy_cases": array(destroy_case),
            "forget_tombstone": tombstone,
            "forget_verification_cases": array(forget_case),
            "export_cases": array(export_case),
        },
        "required": [
            "schema_version",
            "status",
            "key_capability",
            "destroy_cases",
            "forget_tombstone",
            "forget_verification_cases",
            "export_cases",
        ],
        "$defs": {
            "Principal": principal(),
            "ContentRef": content_ref(),
            "ContentLabels": content_labels(),
            "StorageEnvelope": obj(
                {
                    "schema_version": {"const": "S1", "type": "string"},
                    "tenant_id": TEXT,
                    "session_id": TEXT,
                    "seq": POSITIVE,
                    "record_digest": HASH,
                    "chain_digest": HASH,
                    "writer_epoch": NONNEGATIVE,
                    "created_ms": NONNEGATIVE,
                }
            ),
            "Tombstone": tombstone,
            "ExportHeader": export_header,
            "ExportLine": export_lines,
        },
    }


def command_spec() -> dict[str, Any]:
    return obj(
        {
            "command_text": TEXT,
            "argv": array(TEXT),
            "cwd": TEXT,
            "stdin_base64": nullable(S_TEXT),
            "stdin_mode": enum("none", "provided", "pipe"),
            "secret_ref_names": array(TEXT, unique=True),
            "limits": obj(
                {
                    "wall_time_ms": POSITIVE,
                    "output_bytes": POSITIVE,
                }
            ),
        }
    )


def operational_policy() -> dict[str, Any]:
    return obj(
        {
            "network_policy_digest": HASH,
            "isolation_policy_digest": HASH,
        }
    )


def execution_worker_w3_schema() -> dict[str, Any]:
    environment_capabilities = obj(execution_environment_capability_fields())
    provider_lookup = provider_lookup_defs()
    identity_vector = obj(
        {
            "name": TEXT,
            "identity": ref("ExecutionIdentity"),
            "canonical_json_base64": S_TEXT,
            "canonical_json_utf8_bytes": NONNEGATIVE,
            "preimage_base64": S_TEXT,
            "execution_id": HASH,
            "excluded_context_variants": array(
                obj(
                    {
                        "attempt": POSITIVE,
                        "request_digest": HASH,
                        "dispatch_id": TEXT,
                        "clock_ms": NONNEGATIVE,
                    }
                )
            ),
        }
    )
    command_digest_vector = obj(
        {
            "name": TEXT,
            "tenant_id": TEXT,
            "session_id": TEXT,
            "session_data_key_id": TEXT,
            "session_data_key_base64": S_TEXT,
            "command_spec": ref("CommandSpec"),
            "environment": ref("EnvironmentCapabilityBinding"),
            "operational_policy": ref("OperationalPolicy"),
            "canonical_json_base64": S_TEXT,
            "canonical_json_utf8_bytes": NONNEGATIVE,
            "preimage_base64": S_TEXT,
            "command_digest": HASH,
        }
    )
    preparation_binding = obj(
        {
            "execution_identity_source": {"const": "op_planned"},
            "proposal_command_digest": HASH,
            "prepared_request_digest": HASH,
            "hook_patched_command_spec": ref("CommandSpec"),
            "prepared_command_digest": HASH,
            "retry_source": {
                "const": "first_op_prepared_request_digest_command_digest"
            },
            "retry_runs_before_tool_hooks": {"const": False, "type": "boolean"},
            "inherit_from_plan": {
                "const": [
                    "turn_id",
                    "operation_id",
                    "attempt",
                    "idempotency_key",
                    "provider_binding",
                    "execution_identity",
                ]
            },
        }
    )
    lookup_vector = obj(
        {
            "name": TEXT,
            "transport_available": {"type": "boolean"},
            "authenticated": {"type": "boolean"},
            "result": ref("ProviderLookupResult"),
            "expected_disposition": enum(
                "no_effects_and_retry_once",
                "reuse_running_execution",
                "reconcile_terminal_execution",
                "preserve_unknown",
            ),
            "retry_allowed": {"type": "boolean"},
        }
    )
    patch_operation = obj(
        {
            "path": array({"anyOf": [TEXT, NONNEGATIVE]}),
            "set": {},
            "delete": {"type": "boolean"},
        },
        required=("path", "set"),
    )
    invalid_lookup = obj(
        {
            "name": TEXT,
            "base_lookup": TEXT,
            "patch_target": enum("lookup", "environment", "operational_policy"),
            "patch": array(patch_operation),
            "authenticated": {"type": "boolean"},
            "transport_available": {"type": "boolean"},
            "expected_code": enum(
                "binding_mismatch",
                "authorization_mismatch",
                "environment_mismatch",
                "generation_mismatch",
                "isolation_downgrade",
                "network_policy_widening",
                "enforcement_downgrade",
                "capability_digest_mismatch",
                "policy_digest_mismatch",
                "command_mismatch",
                "provider_result_invalid",
            ),
        }
    )
    recovery_case = obj(
        {
            "name": TEXT,
            "lookup_status": enum("not_started", "running", "exited", "unknown"),
            "submitted_attempts": NONNEGATIVE,
            "expected_disposition": enum("start_new_attempt", "query_or_evidence"),
            "expected_next_attempt": NULLABLE_POSITIVE,
            "reuse_idempotency_key": {"type": "boolean"},
            "reuse_execution_id": {"type": "boolean"},
        }
    )
    framing = obj(
        {
            "execution_id": obj(
                {
                    "domain": {"const": "vv-agent/S1/execution-identity"},
                    "framing_version": {"const": 1, "type": "integer"},
                    "preimage_fields": {"const": ["domain", "framing_version", "operation_key", "tenant_id", "environment_id"]},
                    "canonicalization": {"const": "RFC8785_JCS"},
                    "preimage": {"const": "JCS({domain,framing_version,operation_key,tenant_id,environment_id})"},
                    "digest": {"const": "SHA256(preimage)"},
                    "excluded_fields": {"const": ["attempt", "request_digest", "dispatch_id", "clock_ms"]},
                }
            ),
            "capabilities_digest": obj(
                {
                    "preimage": {"const": "JCS({environment_id,generation,isolation,network,enforces_network_policy,enforces_resource_limits,persistent,environment_capabilities,network_policy_ref_digest,isolation_policy_ref_digest})"},
                    "digest": {"const": "SHA256(preimage)"},
                }
            ),
            "command_digest": obj(
                {
                    "domain": {"const": "vv-agent/S1/command-digest"},
                    "framing_version": {"const": 1, "type": "integer"},
                    "purpose": {"const": "stable-command"},
                    "canonicalization": {"const": "RFC8785_JCS"},
                    "preimage": {"const": "JCS({domain,framing_version,purpose,tenant_id,session_id,command_spec,environment,operational_policy})"},
                    "digest": {"const": "HMAC-SHA256(session_data_key,preimage)"},
                    "excluded_fields": {"const": ["attempt", "request_digest", "dispatch_id", "clock_ms", "transport_credentials"]},
                }
            ),
        }
    )
    lookup_content_owner = obj(
        {
            "kind": {"const": "inbox"},
            "input_id": TEXT,
            "tenant_id": TEXT,
            "session_id": TEXT,
        }
    )
    lookup_storage_boundary = obj(
        {
            "logical_source": {"const": "lookup_results[].result"},
            "content_owner": lookup_content_owner,
            "content_slot": {"const": "provider_lookup"},
            "read_order": {
                "const": [
                    "content_owner",
                    "content_slot",
                    "decrypt_and_verify_typed_content",
                    "provider_lookup_result",
                    "outer_binding_and_plan",
                ]
            },
            "retained_evidence": {"type": "object"},
            "content": obj(
                {
                    "logical_result": ref("ProviderLookupResult"),
                    "canonical_json_sha256": HASH,
                }
            ),
            "op_parked_projection": obj(
                {
                    "handle_fields": {
                        "const": [
                            "kind",
                            "provider",
                            "job_id",
                            "operation_id",
                            "attempt",
                            "request_digest",
                            "evidence",
                            "query_ref",
                            "cancel_ref",
                        ]
                    },
                    "content_fields": {
                        "const": ["job_id", "evidence", "query_ref", "cancel_ref"]
                    },
                    "identity_restored_from": {
                        "const": [
                            "op_planned.execution_identity",
                            "turn_started.environment",
                        ]
                    },
                }
            ),
            "immediate_recovery_slots": obj(
                {
                    "running": {"const": ["op_parked.handle.evidence"]},
                    "exited": {"const": ["op_completed.result", "op_completed.usage", "op_completed.evidence"]},
                    "unknown": {"const": ["op_unknown.reason", "op_unknown.dispatch_evidence", "op_unknown.observation"]},
                }
            ),
            "retry_guard": obj(
                {
                    "not_started_evidence_persisted_before_retry": {"const": True, "type": "boolean"},
                    "external_callback_required": {"const": False, "type": "boolean"},
                    "invalid_cases": array(
                        obj(
                            {
                                "name": TEXT,
                                "expected_code": enum(
                                    "content_owner_mismatch",
                                    "content_slot_mismatch",
                                    "binding_mismatch",
                                    "provider_lookup_not_content_ref",
                                    "not_started_evidence_not_persisted",
                                ),
                            }
                        )
                    ),
                }
            ),
        }
    )
    return {
        "$schema": DRAFT,
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": "vv-agent.execution-worker-w3.v1"},
            "contract_version": {"const": "41.0.0"},
            "status": {"const": "contract-allocation-only"},
            "feature_level": {"const": 3, "type": "integer"},
            "provenance": obj(
                {
                    "producer_capture": {"const": False, "type": "boolean"},
                    "capture": {"const": "none", "type": "string"},
                    "adoption_evidence": {"const": False, "type": "boolean"},
                    "note": TEXT,
                }
            ),
            "framing": framing,
            "idempotency": obj(
                {
                    "key_format": {"const": "{session_id}/{operation_id}"},
                    "deduplication_scope": {"const": "tenant_id,environment_id,idempotency_key"},
                    "stable_across_attempts": {"const": True, "type": "boolean"},
                }
            ),
            "provider_outcomes": obj(
                {
                    "not_started": {"type": "null"},
                    "running": {"const": "Accepted", "type": "string"},
                    "exited": {"const": "Definitive", "type": "string"},
                    "unknown": {"const": "Unknown", "type": "string"},
                }
            ),
            "environment": ref("EnvironmentCapabilityBinding"),
            "operational_policy": ref("OperationalPolicy"),
            "identity_vectors": array(identity_vector),
            "command_digest_vectors": array(command_digest_vector),
            "preparation_binding": preparation_binding,
            "lookup_binding": ref("ProviderLookupBinding"),
            "lookup_results": array(lookup_vector),
            "lookup_storage_boundary": lookup_storage_boundary,
            "invalid_lookup_cases": array(invalid_lookup),
            "recovery_cases": array(recovery_case),
        },
        "required": [
            "schema_version",
            "contract_version",
            "status",
            "feature_level",
            "provenance",
            "framing",
            "idempotency",
            "provider_outcomes",
            "environment",
            "operational_policy",
            "identity_vectors",
            "command_digest_vectors",
            "preparation_binding",
            "lookup_binding",
            "lookup_results",
            "lookup_storage_boundary",
            "invalid_lookup_cases",
            "recovery_cases",
        ],
        "$defs": {
            "ExecutionIdentity": execution_identity(),
            "EnvironmentCapabilityBinding": environment_capabilities,
            "CommandSpec": command_spec(),
            "OperationalPolicy": operational_policy(),
            "ContentRef": content_ref(),
            "ContentLabels": content_labels(),
            **provider_lookup,
        },
    }


def worker_compatibility_schema() -> dict[str, Any]:
    tool_schema = obj(
        {
            "type": {"const": "function", "type": "string"},
            "function": obj(
                {
                    "name": TEXT,
                    "description": TEXT,
                    "parameters": {"type": "object"},
                    "strict": {"type": "boolean"},
                }
            ),
        }
    )
    model_identity_properties = {
        "backend": TEXT,
        "model": TEXT,
        "context_length": NULLABLE_POSITIVE,
        "max_output_tokens": nullable(NONNEGATIVE),
    }
    model_identity = obj(model_identity_properties)
    model_binding_for_tag = obj(
        {
            **model_identity_properties,
            "endpoints": array(TEXT, unique=True),
        }
    )
    routing_cache = obj(
        {
            "level": POSITIVE,
            "handler_version": NULLABLE_TEXT,
            "required_capabilities": array(TEXT, unique=True),
            "active_turn_id": NULLABLE_TEXT,
        }
    )
    scenario = obj(
        {
            "name": TEXT,
            "kind": enum(
                "tool_visible_subset",
                "tool_tag_mismatch",
                "active_model_union",
                "active_unsupported_model",
                "active_supported_model",
                "bootstrap_family",
                "selection_handler_mismatch",
                "cache_understatement",
            ),
            "phase": enum("bootstrap", "idle", "active"),
            "active_handler_version": NULLABLE_TEXT,
            "input_handler_version": NULLABLE_TEXT,
            "bootstrap_handler_version": NULLABLE_TEXT,
            "active_requirements": nullable(ref("SessionRequirements")),
            "input_requirements": ref("SessionRequirements"),
            "supports": array(TEXT, unique=True),
            "cache_before": nullable(ref("RoutingCache")),
            "expected_cache": ref("RoutingCache"),
            "expected_action": enum(
                "grant_lease",
                "reject_unroutable",
                "reject_publication",
                "reject_ledger_integrity",
            ),
            "expected_compatible": {"type": "boolean"},
            "content_hydrated": {"type": "boolean"},
            "epoch_granted": {"type": "boolean"},
        }
    )
    admission_candidate = obj(
        {
            "input_id": TEXT,
            "kind": enum("user", "follow_up", "model_selection"),
            "input_seq": POSITIVE,
            "ready": {"type": "boolean"},
            "target_turn_id": NULLABLE_TEXT,
            "requirements": ref("SessionRequirements"),
        }
    )
    admission_order_case = obj(
        {
            "name": TEXT,
            "queued_inputs": array(admission_candidate),
            "ready_pending_inputs": array(admission_candidate),
            "expected_apply_order": array(TEXT),
            "expected_turn_start_order": array(TEXT),
            "current_worker_supports": array(TEXT, unique=True),
            "expected_cache": ref("RoutingCache"),
            "expected_worker_disposition": enum("defer_to_compatible_worker"),
            "content_hydrated": {"const": False, "type": "boolean"},
        }
    )
    format_floor_case = obj(
        {
            "name": TEXT,
            "boundary": enum("turn_end_idle", "idle_before_first_turn"),
            "bootstrap_container_feature_level": {"const": 2, "type": "integer"},
            "stored_record_feature_levels": {
                "type": "array",
                "items": {"type": "integer", "enum": [1, 2]},
                "minItems": 1,
            },
            "activated_inbox_feature_levels": array(
                {"type": "integer", "enum": [1, 2]},
                unique=True,
            ),
            "bootstrap_requirements": ref("SessionRequirements"),
            "current_routing_requirements": ref("SessionRequirements"),
            "expected_cache": ref("RoutingCache"),
            "level1_executor_accepted": {"type": "boolean"},
            "level2_executor_accepted": {"type": "boolean"},
            "level1_reader_accepted": {"type": "boolean"},
            "level2_reader_without_execution_supports_accepted": {"type": "boolean"},
            "content_hydrated": {"const": False, "type": "boolean"},
        }
    )
    level_three_case = obj(
        {
            "name": TEXT,
            "session_bootstrap_feature_level": {"const": 2, "type": "integer"},
            "execution_record_feature_level": {"const": 3, "type": "integer"},
            "routing_requirements": ref("SessionRequirements"),
            "expected_cache": ref("RoutingCache"),
            "level2_worker_accepted": {"const": False, "type": "boolean"},
            "level3_worker_accepted": {"const": True, "type": "boolean"},
            "level2_reader_accepted": {"const": False, "type": "boolean"},
            "level3_reader_without_execution_supports_accepted": {
                "const": True,
                "type": "boolean",
            },
            "body_decoded": {"const": False, "type": "boolean"},
            "epoch_granted": {"const": False, "type": "boolean"},
        }
    )
    capability_bound_case = obj(
        {
            "name": TEXT,
            "input_id": TEXT,
            "trusted_static_sources": array(
                enum(
                    "handler",
                    "model",
                    "base-tools",
                    "dynamic-potential-tools",
                    "custom-factory-declaration",
                ),
                unique=True,
            ),
            "pre_admission_requirements": ref("SessionRequirements"),
            "actual_turn_started_requirements": ref("SessionRequirements"),
            "pre_admission_work": obj(
                {
                    "compile_invocations": NONNEGATIVE,
                    "guardrail_invocations": NONNEGATIVE,
                    "instruction_resolution_invocations": NONNEGATIVE,
                    "context_provider_invocations": NONNEGATIVE,
                }
            ),
            "turn_start_work": obj(
                {
                    "compile_invocations": NONNEGATIVE,
                    "guardrail_invocations": NONNEGATIVE,
                    "instruction_resolution_invocations": NONNEGATIVE,
                    "context_provider_invocations": NONNEGATIVE,
                }
            ),
            "expected_capability_relation": enum("subset", "exceeds"),
            "expected_action": enum(
                "route_after_turn_start",
                "fail_unsatisfiable_bound_configuration",
            ),
            "dispatch_started": {"type": "boolean"},
            "terminal_recorded": {"type": "boolean"},
            "input_bytes_mutated": {"type": "boolean"},
            "opaque_content_used_as_control": {"type": "boolean"},
            "bound_failure": nullable(
                obj(
                    {
                        "configuration_error_exposed": {"type": "boolean"},
                        "input_already_queued": {"type": "boolean"},
                        "safe_discard_available": {"type": "boolean"},
                        "requires_new_session": {"type": "boolean"},
                        "replacement_input_published": {"type": "boolean"},
                        "cancel_or_supersede_protocol_added": {
                            "type": "boolean"
                        },
                        "automatic_retry_started": {"type": "boolean"},
                    }
                )
            ),
        }
    )
    model_tag_case = obj(
        {
            "name": TEXT,
            "bindings": array(
                obj(
                    {
                        "purpose": TEXT,
                        "binding": ref("ModelBindingForTag"),
                    }
                )
            ),
            "expected_tags": array(
                {"type": "string", "pattern": "^model:[0-9a-f]{64}$"}
            ),
        }
    )
    return {
        "$schema": DRAFT,
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": "vv-agent.worker-compatibility.v1"},
            "contract_version": {"const": "41.0.0"},
            "status": {"const": "contract-allocation-only"},
            "provenance": obj(
                {
                    "producer_capture": {"const": False, "type": "boolean"},
                    "capture": {"const": "none", "type": "string"},
                    "adoption_evidence": {"const": False, "type": "boolean"},
                    "note": TEXT,
                }
            ),
            "allocation": obj(
                {
                    "bootstrap_source": {
                        "const": "trusted-session-creation",
                        "type": "string",
                    },
                    "tool_requirements": {
                        "const": "trusted-static-conservative-bound",
                        "type": "string",
                    },
                    "turn_started_requirements": {
                        "const": "compiled-definition-exact-visible-subset",
                        "type": "string",
                    },
                    "tool_supports": {
                        "const": "trusted-complete-catalog",
                        "type": "string",
                    },
                    "model_source": {
                        "const": "trusted-resolved-model-binding",
                        "type": "string",
                    },
                    "cache": {
                        "const": "format-floor-plus-active-turn-or-combined-idle-admission-order",
                        "type": "string",
                    },
                    "cache_verification": {
                        "const": "complete-proof-projection-then-locked-now-before-epoch",
                        "type": "string",
                    },
                    "w3_execution": {
                        "const": "feature-level-3-command-identity-and-authenticated-lookup",
                        "type": "string",
                    },
                }
            ),
            "tagging": obj(
                {
                    "tool_fields": {
                        "type": "array",
                        "items": enum("name", "schema", "metadata"),
                        "uniqueItems": True,
                    },
                    "tool_identity": {
                        "const": "SHA256(JCS({name,schema,metadata}))",
                        "type": "string",
                    },
                    "model_fields": {
                        "type": "array",
                        "items": enum(
                            "backend",
                            "model",
                            "context_length",
                            "max_output_tokens",
                        ),
                        "uniqueItems": True,
                    },
                    "model_excluded_fields": {
                        "type": "array",
                        "items": enum(
                            "endpoints",
                            "internal",
                            "route",
                            "credentials",
                        ),
                        "uniqueItems": True,
                    },
                    "model_identity": {
                        "const": "SHA256(JCS({backend,model,context_length,max_output_tokens}))",
                        "type": "string",
                    },
                    "tool_prefix": {"const": "tool:", "type": "string"},
                    "model_prefix": {"const": "model:", "type": "string"},
                }
            ),
            "trusted_catalog": obj(
                {
                    "tools": array(
                        obj(
                            {
                                "name": TEXT,
                                "schema": ref("ToolSchema"),
                                "metadata": {"type": "object"},
                                "tag": {
                                    "type": "string",
                                    "pattern": "^tool:[0-9a-f]{64}$",
                                },
                            }
                        )
                    ),
                    "models": array(
                        obj(
                            {
                                "identity": ref("ModelIdentity"),
                                "tag": {
                                    "type": "string",
                                    "pattern": "^model:[0-9a-f]{64}$",
                                },
                            }
                        )
                    ),
                }
            ),
            "cases": array(scenario),
            "admission_order_cases": array(admission_order_case),
            "format_floor_cases": array(format_floor_case),
            "level_three_cases": array(level_three_case),
            "capability_bound_cases": array(capability_bound_case),
            "model_tag_cases": array(model_tag_case),
        },
        "required": [
            "schema_version",
            "contract_version",
            "status",
            "provenance",
            "allocation",
            "tagging",
            "trusted_catalog",
            "cases",
            "admission_order_cases",
            "format_floor_cases",
            "level_three_cases",
            "capability_bound_cases",
            "model_tag_cases",
        ],
        "$defs": {
            "SessionRequirements": requirements(),
            "RoutingCache": routing_cache,
            "ToolSchema": tool_schema,
            "ModelIdentity": model_identity,
            "ModelBindingForTag": model_binding_for_tag,
        },
    }


def rendered() -> dict[Path, dict[str, Any]]:
    return {
        FIXTURES / "session_record.schema.json": record_schema(),
        FIXTURES / "session_inbox.schema.json": inbox_schema(),
        FIXTURES / "session_storage_envelope.schema.json": storage_envelope_schema(),
        FIXTURES / "session_storage_lifecycle.schema.json": lifecycle_schema(),
        FIXTURES / "execution_worker_w3.schema.json": execution_worker_w3_schema(),
        FIXTURES / "worker_compatibility.schema.json": worker_compatibility_schema(),
    }


def write(root: Path) -> None:
    for relative, schema in rendered().items():
        target = root / relative.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    write(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
