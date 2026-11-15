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
    }


def record_payload_defs() -> dict[str, Any]:
    return {
        "SessionCreatedPayload": obj(
            {
                "principal": ref("Principal"),
                "workspace": ref("ContentRef"),
                "parent_session_id": NULLABLE_TEXT,
                "parent_operation_id": NULLABLE_TEXT,
                "attributes": ref("ContentRef"),
            }
        ),
        "TurnStartedPayload": obj(
            {
                "input_ids": array(TEXT),
                "definition": ref("ContentRef"),
                "definition_digest": HASH,
                "handler_version": TEXT,
                "budget": ref("ContentRef"),
                "binding": NULLABLE_TEXT,
                "generation": NONNEGATIVE,
                "policy_digest": NULLABLE_HASH,
                "requirements": ref("Requirements"),
                "tokenizer_binding": ref("TokenizerBinding"),
                "environment": ref("EnvironmentBinding"),
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
        "OpPlannedPayload": obj(
            {
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
        "Requirements": requirements(),
        "EnvironmentBinding": environment_binding(),
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
                "stop": nullable(obj({"code": TEXT, "message": ref("ContentRef")})),
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
    return {"$schema": DRAFT, "oneOf": branches, "$defs": defs}


def inbox_schema_item(defs: dict[str, Any]) -> dict[str, Any]:
    envelope = obj(
        {
            "schema_version": {"const": "S1", "type": "string"},
            "feature_level": {"const": 1, "type": "integer"},
            "actor": ref("Principal"),
            "admission_proof": ref("AdmissionProof"),
            "input_id": TEXT,
            "kind": {"type": "string"},
            "target_turn_id": NULLABLE_TEXT,
            "generation": nullable(NONNEGATIVE),
            "available_ms": NONNEGATIVE,
            "payload": {"type": "object"},
        }
    )
    # Avoid recursive copying: the caller retains this definition and branches
    # add the discriminator and payload below.
    branches = []
    for kind, payload_name in inbox_kind_map().items():
        branches.append(
            {
                "allOf": [
                    envelope,
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
    defs["InboxEnvelope"] = envelope
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


def rendered() -> dict[Path, dict[str, Any]]:
    return {
        FIXTURES / "session_record.schema.json": record_schema(),
        FIXTURES / "session_inbox.schema.json": inbox_schema(),
        FIXTURES / "session_storage_envelope.schema.json": storage_envelope_schema(),
        FIXTURES / "session_storage_lifecycle.schema.json": lifecycle_schema(),
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
