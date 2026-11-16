"""Strict current session fixture checks, independent of runtime implementation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import struct
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from contractctl import load_json, strict_json_loads

DRAFT = "https://json-schema.org/draft/2020-12/schema"
RECORD_KINDS = {
    "session_created",
    "turn_started",
    "input_applied",
    "op_planned",
    "op_prepared",
    "turn_parked",
    "op_started",
    "op_parked",
    "op_completed",
    "op_unknown",
    "context_compacted",
    "boundary_recorded",
    "usage_observed",
    "turn_ended",
}
INBOX_KINDS = {
    "user",
    "steer",
    "follow_up",
    "provider_result",
    "approval_answer",
    "child_result",
    "control",
    "provider_evidence",
    "model_selection",
}
BOUNDARY_STAGES = {
    "before_memory",
    "after_cycle",
    "memory_started",
    "memory_completed",
    "session_memory_saved",
    "output_checked",
    "budget",
}
HANDLE_VARIANTS = {"provider", "approval", "user", "child"}
HISTORICAL_SESSION_FIXTURES = {
    "host_summary_requests.json",
    "model_rejection.json",
    "session_projection.json",
    "unseen_input_protection.json",
    "yieldable_waits.json",
}
KEYWORDS = {
    "$schema",
    "$defs",
    "$ref",
    "type",
    "const",
    "enum",
    "oneOf",
    "anyOf",
    "allOf",
    "if",
    "then",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
}


class ValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def json_value(value: Any) -> None:
    """Enforce I-JSON even inside explicitly opaque content maps."""
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        require(abs(value) <= 9007199254740991, "unsafe integer")
    elif type(value) is float:
        require(math.isfinite(value), "nonfinite number")
    elif isinstance(value, str):
        require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value), "lone surrogate")
    elif isinstance(value, list):
        for item in value:
            json_value(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            require(isinstance(key, str), "non-string object key")
            json_value(key)
            json_value(item)
    else:
        raise ValidationError("non-JSON host object")


def check_schema_keywords(schema: dict[str, Any]) -> None:
    require(
        not set(schema) - KEYWORDS,
        f"unsupported schema keywords: {set(schema) - KEYWORDS}",
    )
    for key in ("oneOf", "anyOf", "allOf"):
        for child in schema.get(key, []):
            check_schema_keywords(child)
    for key in ("if", "then", "items"):
        if key in schema:
            check_schema_keywords(schema[key])
    for child in schema.get("properties", {}).values():
        check_schema_keywords(child)
    for child in schema.get("$defs", {}).values():
        check_schema_keywords(child)


def matches(value: Any, schema: dict[str, Any], root: dict[str, Any]) -> bool:
    try:
        validate_schema(value, schema, root)
    except ValidationError:
        return False
    return True


def validate_schema(
    value: Any, schema: dict[str, Any], root: dict[str, Any] | None = None
) -> None:
    """Draft 2020-12 keywords emitted here, with codec-strict integer types."""
    if root is None:
        root = schema
    if "$ref" in schema:
        reference = schema["$ref"]
        prefix = "#/$defs/"
        require(reference.startswith(prefix), "unsupported schema reference")
        name = reference[len(prefix) :]
        require(name in root.get("$defs", {}), f"missing schema definition: {name}")
        validate_schema(value, root["$defs"][name], root)
        return
    if "type" in schema:
        types = {
            "null": value is None,
            "boolean": type(value) is bool,
            "integer": type(value) is int,
            "number": type(value) in (int, float),
            "string": isinstance(value, str),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
        }
        require(types[schema["type"]], f"expected {schema['type']}")
    if "const" in schema:
        require(value == schema["const"], "const mismatch")
    if "enum" in schema:
        require(value in schema["enum"], "enum mismatch")
    for key in ("oneOf", "anyOf"):
        if key in schema:
            count = sum(matches(value, branch, root) for branch in schema[key])
            require(count == 1 if key == "oneOf" else count > 0, f"{key} mismatch")
    for child in schema.get("allOf", []):
        validate_schema(value, child, root)
    if "if" in schema and matches(value, schema["if"], root) and "then" in schema:
        validate_schema(value, schema["then"], root)
    if isinstance(value, dict):
        require(
            set(schema.get("required", [])) <= set(value), "missing required fields"
        )
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(set(value) <= set(properties), "unknown fields")
        if isinstance(schema.get("additionalProperties"), dict):
            for key in value.keys() - properties.keys():
                validate_schema(value[key], schema["additionalProperties"], root)
        for key in value.keys() & properties.keys():
            validate_schema(value[key], properties[key], root)
    if isinstance(value, list):
        if schema.get("uniqueItems") is True:
            encoded = [json_key(item) for item in value]
            require(len(encoded) == len(set(encoded)), "duplicate array item")
        if "items" in schema:
            for item in value:
                validate_schema(item, schema["items"], root)
    if isinstance(value, str):
        require(len(value) >= schema.get("minLength", 0), "short string")
        require(len(value) <= schema.get("maxLength", math.inf), "long string")
        if "pattern" in schema:
            require(re.search(schema["pattern"], value) is not None, "pattern mismatch")
    if type(value) in (int, float):
        require(value > schema.get("exclusiveMinimum", -math.inf), "exclusive minimum")
        require(
            schema.get("minimum", -math.inf)
            <= value
            <= schema.get("maximum", math.inf),
            "number bounds",
        )


def require_sorted_unique(value: list[str], label: str) -> None:
    require(len(value) == len(set(value)), f"{label} contains duplicate items")
    require(value == sorted(value), f"{label} is not sorted")


def validate_content_ref(value: dict[str, Any], label: str) -> None:
    source = value["labels"]["source"]
    source_order = {"system": 0, "user": 1, "internal": 2, "untrusted": 3}
    require(len(source) == len(set(source)), f"{label}.labels.source contains duplicate items")
    require(
        [source_order[item] for item in source] == sorted(source_order[item] for item in source),
        f"{label}.labels.source is not in source-kind order",
    )


def validate_content_refs(value: Any, label: str = "wire") -> None:
    for node in walk(value):
        if isinstance(node, dict) and set(node) == {
            "content_id",
            "mac",
            "size",
            "key_id",
            "labels",
        }:
            validate_content_ref(node, label)


def content_ref_entries(
    value: Any, path: tuple[str | int, ...] = ()
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if set(value) == {"content_id", "mac", "size", "key_id", "labels"}:
            return [{"path": list(path), **value}]
        for key, child in value.items():
            refs.extend(content_ref_entries(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            refs.extend(content_ref_entries(child, (*path, index)))
    return sorted(
        refs,
        key=lambda ref: json.dumps(
            ref["path"], ensure_ascii=True, separators=(",", ":")
        ),
    )


def validate_proof_signature(value: str, label: str) -> None:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValidationError(f"{label} is not canonical base64") from exc
    require(bool(raw), f"{label} is empty")
    require(base64.b64encode(raw).decode("ascii") == value, f"{label} is not canonical base64")


def record_id(wire: dict[str, Any]) -> str:
    kind, p = wire["kind"], wire["payload"]
    if kind == "session_created":
        return f"session/{wire['session_id']}/created"
    if kind in {"turn_started", "turn_ended"}:
        return f"turn/{wire['turn_id']}/{kind[5:]}"
    if kind == "turn_parked":
        return f"turn/{wire['turn_id']}/wait/{p['interaction_id']}"
    if kind == "input_applied":
        return f"input/{p['input']['input_id']}/applied"
    if kind.startswith("op_"):
        suffix = "result" if kind == "op_completed" else kind[3:]
        if kind == "op_parked":
            suffix += "/" + p["phase"]
        return f"op/{wire['operation_id']}/{wire['attempt']}/{suffix}"
    if kind == "boundary_recorded":
        return f"turn/{wire['turn_id']}/boundary/{p['stage']}/{p['boundary_id']}"
    if kind == "context_compacted":
        suffix = (
            "" if p["summary_operation_id"] is None else "/" + p["summary_operation_id"]
        )
        return f"compact/{p['source_digest']}/{p['mode']}{suffix}"
    return f"usage/{p['meter_id']}/{p['observation']}"


def walk(value: Any):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def json_key(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest_inputs(value: Any):
    for node in walk(value):
        if isinstance(node, dict):
            for field in ("request", "result", "definition", "input"):
                if field in node:
                    try:
                        json_value(node[field])
                    except ValidationError:
                        continue
                    yield node[field]


class Codec:
    def __init__(self, root: Path, documents: Any):
        self.record_schema = load_json(root / "fixtures/session_record.schema.json")
        self.inbox_schema = load_json(root / "fixtures/session_inbox.schema.json")
        for schema, kinds in (
            (self.record_schema, RECORD_KINDS),
            (self.inbox_schema, INBOX_KINDS),
        ):
            require(schema.get("$schema") == DRAFT, "schema draft mismatch")
            check_schema_keywords(schema)
            require(
                {
                    branch["allOf"][1]["properties"]["kind"]["const"]
                    for branch in schema["oneOf"]
                }
                == kinds,
                "schema kind coverage",
            )
        inputs = {json_key(v): v for v in digest_inputs(documents)}
        result = subprocess.run(
            ["node", str(root / "scripts/verify_jcs.mjs"), "--canonicalize"],
            input=json.dumps(list(inputs.values()), ensure_ascii=True, allow_nan=False),
            text=True,
            capture_output=True,
            check=False,
        )
        require(
            result.returncode == 0, f"canonical encoding failed: {result.stderr[:500]}"
        )
        canonical = json.loads(result.stdout)
        require(len(canonical) == len(inputs), "canonical encoding count mismatch")
        self.digests = {
            key: hashlib.sha256(base64.b64decode(raw, validate=True)).hexdigest()
            for key, raw in zip(inputs, canonical)
        }

    def digest(self, value: Any) -> str:
        return self.digests[json_key(value)]

    def validate(self, wire: Any, *, inbox: bool = False) -> None:
        json_value(wire)
        schema = self.inbox_schema if inbox else self.record_schema
        validate_schema(wire, schema, schema)
        require("chain_digest" not in wire, "chain_digest belongs to storage envelope")
        validate_content_refs(wire)
        if inbox:
            validate_content_ref(wire["actor"]["attributes"], "inbox.actor.attributes")
            proof = wire["admission_proof"]
            if proof is not None:
                validate_proof_signature(
                    proof["admission_signature"], "inbox.admission_signature"
                )
            if wire["kind"] == "model_selection":
                require(
                    wire["target_turn_id"] is None and wire["generation"] is None,
                    "model selection scope",
                )
            return
        kind, p = wire["kind"], wire["payload"]
        require(wire["record_id"] == record_id(wire), "wrong record identity")
        operation = kind.startswith("op_")
        require(
            (wire["operation_id"] is not None) == operation,
            "operation identity nullability",
        )
        require((wire["attempt"] is not None) == operation, "attempt nullability")
        if kind == "session_created":
            require(wire["turn_id"] is None, "creation turn must be null")
            validate_content_ref(p["principal"]["attributes"], "principal.attributes")
        elif kind not in {"input_applied", "usage_observed"}:
            require(wire["turn_id"] is not None, "turn required")
        if kind == "op_planned":
            require(
                (p["purpose"] is not None) == (p["op_kind"] == "model"),
                "purpose nullability",
            )
        if kind == "turn_started":
            requirements = p["requirements"]
            require_sorted_unique(
                requirements["capabilities"], "turn_started.requirements.capabilities"
            )
            environment = p["environment"]
            if environment is not None:
                validate_content_ref(environment["descriptor"], "turn_started.environment.descriptor")
                if environment["operational_policy"] is not None:
                    validate_content_ref(
                        environment["operational_policy"],
                        "turn_started.environment.operational_policy",
                    )
                require_sorted_unique(
                    environment["environment_capabilities"],
                    "turn_started.environment.environment_capabilities",
                )
        pair = {
            "turn_started": ("definition_digest", "definition"),
            "op_planned": ("request_digest", "request"),
            "op_prepared": ("request_digest", "request"),
            "op_completed": ("result_digest", "result"),
            "input_applied": ("input_digest", "input"),
        }.get(kind)
        if pair:
            require(p[pair[0]] == self.digest(p[pair[1]]), "embedded digest mismatch")
        if kind == "input_applied":
            self.validate(p["input"], inbox=True)
            proof = p["input_proof"]
            admission = p["input"]["admission_proof"]
            require(
                (proof is None) == (admission is None),
                "input proof admission mismatch",
            )
            if proof is not None and admission is not None:
                validate_proof_signature(
                    proof["signature"], "input_applied.input_proof.signature"
                )
                require(
                    proof["key_id"] == admission["admission_key_id"]
                    and proof["signature"] == admission["admission_signature"]
                    and proof["signed_ms"] == admission["admission_signed_ms"],
                    "input proof does not copy admission proof",
                )


def decode(vector: dict[str, Any]) -> bytes:
    raw = base64.b64decode(vector["bytes_base64"], validate=True)
    require(
        hashlib.sha256(raw).hexdigest() == vector["sha256"], "invalid vector byte hash"
    )
    return raw


def jcs_digest(root: Path, value: Any) -> str:
    result = subprocess.run(
        ["node", str(root / "scripts/verify_jcs.mjs"), "--canonicalize"],
        input=json.dumps([value], ensure_ascii=True, allow_nan=False),
        text=True,
        capture_output=True,
        check=False,
    )
    require(result.returncode == 0, f"canonical encoding failed: {result.stderr[:500]}")
    raw = base64.b64decode(json.loads(result.stdout)[0], validate=True)
    return hashlib.sha256(raw).hexdigest()


def frame_chain(previous: str, seq: int, record_digest: str) -> str:
    return hashlib.sha256(
        bytes.fromhex(previous) + struct.pack(">Q", seq) + bytes.fromhex(record_digest)
    ).hexdigest()


def initial_chain(tenant_id: str, session_id: str) -> str:
    def length_prefixed(value: str) -> bytes:
        raw = value.encode("utf-8")
        return struct.pack(">I", len(raw)) + raw

    return hashlib.sha256(
        b"vv-agent/S1" + length_prefixed(tenant_id) + length_prefixed(session_id)
    ).hexdigest()


def validate_storage_fixtures(
    root: Path, codec: Codec, documents: dict[str, Any]
) -> tuple[int, int]:
    fixtures = root / "fixtures"
    storage = documents["session_storage_envelope.json"]
    storage_schema = documents["session_storage_envelope.schema.json"]
    validate_schema(storage, storage_schema, storage_schema)
    require(storage["status"] == "contract-allocation-only", "storage provenance")

    created_tenants: dict[str, str] = {}
    for node in walk([documents, []]):
        if (
            isinstance(node, dict)
            and node.get("kind") == "session_created"
            and isinstance(node.get("payload"), dict)
            and isinstance(node["payload"].get("principal"), dict)
        ):
            created_tenants[node["session_id"]] = node["payload"]["principal"][
                "tenant_id"
            ]

    accepted_count = rejected_count = 0
    for case in storage["cases"]:
        logical = case["logical_record"]
        digest = jcs_digest(root, logical)
        require(digest == case["logical_record_digest"], "storage logical digest")
        codec.validate(logical)
        envelope = case["envelope"]
        expected_tenant = created_tenants.get(logical["session_id"])
        valid = (
            matches(envelope, storage_schema["$defs"]["Envelope"], storage_schema)
            and envelope.get("record_digest") == digest
            and envelope.get("session_id") == logical["session_id"]
            and envelope.get("tenant_id") == expected_tenant
            and envelope.get("chain_digest")
            == frame_chain(
                case["previous_chain_digest"],
                envelope.get("seq", 0),
                case["logical_record_digest"],
            )
        )
        if envelope.get("seq") == 1:
            valid = valid and case["previous_chain_digest"] == initial_chain(
                expected_tenant, logical["session_id"]
            )
        require(valid == case["accepted"], f"storage case outcome: {case['name']}")
        if case["accepted"]:
            accepted_count += 1
        else:
            rejected_count += 1
    return accepted_count, rejected_count


def validate_lifecycle_fixtures(
    root: Path,
    codec: Codec,
    documents: dict[str, Any],
    catalog: dict[str, Any],
) -> tuple[int, int, int]:
    fixtures = root / "fixtures"
    lifecycle = documents["session_storage_lifecycle.json"]
    schema = documents["session_storage_lifecycle.schema.json"]
    storage = documents["session_storage_envelope.json"]
    validate_schema(lifecycle, schema, schema)
    require(lifecycle["status"] == "contract-allocation-only", "lifecycle provenance")

    accepted_storage = [
        case
        for case in storage["cases"]
        if case["accepted"]
        and case["logical_record"]["session_id"]
        == lifecycle["key_capability"]["session_id"]
    ]
    storage_by_seq = {case["envelope"]["seq"]: case for case in accepted_storage}
    head_case = max(accepted_storage, key=lambda case: case["envelope"]["seq"])
    head = head_case["envelope"]
    key_id = lifecycle["key_capability"]["key_id"]
    require(
        key_id == head_case["logical_record"]["payload"]["workspace"]["key_id"],
        "key capability binding",
    )

    destroy_accepted = destroy_rejected = 0
    for case in lifecycle["destroy_cases"]:
        request = case["request"]
        valid = (
            request["domain"] == "vv-agent/S1/key-destroy"
            and request["tenant_id"] == lifecycle["key_capability"]["tenant_id"]
            and request["key_id"] == key_id
            and case["status"] in {"destroyed", "already_destroyed"}
            and case["evidence_id"] is not None
        )
        require(valid == case["accepted"], f"destroy case outcome: {case['name']}")
        if case["accepted"]:
            destroy_accepted += 1
        else:
            destroy_rejected += 1

    def tombstone_valid(tombstone: dict[str, Any]) -> bool:
        return (
            tombstone["tenant_id"] == head["tenant_id"]
            and tombstone["session_id"] == head["session_id"]
            and tombstone["final_seq"] == head["seq"]
            and tombstone["chain_digest"] == head["chain_digest"]
            and tombstone["key_id"] == key_id
            and tombstone["state"] == "complete"
            and tombstone["scope_root_session_id"] == head["session_id"]
        )

    require(tombstone_valid(lifecycle["forget_tombstone"]), "forget tombstone")
    forget_accepted = forget_rejected = 0
    for case in lifecycle["forget_verification_cases"]:
        require(
            tombstone_valid(case["tombstone"]) == case["accepted"],
            f"forget case outcome: {case['name']}",
        )
        if case["accepted"]:
            forget_accepted += 1
        else:
            forget_rejected += 1

    catalog_keys = {entry["key_id"]: entry for entry in catalog["keys"]}
    catalog_contents = catalog["contents"]

    def export_valid(case: dict[str, Any]) -> bool:
        header = case["header"]
        if not matches(header, schema["$defs"]["ExportHeader"], schema):
            return False
        if (
            header["tenant_id"] != head["tenant_id"]
            or header["session_id"] != head["session_id"]
            or header["head_seq"] != head["seq"]
            or header["chain_digest"] != head["chain_digest"]
        ):
            return False
        lines = case["lines"]
        if any(
            not matches(line, schema["$defs"]["ExportLine"], schema) for line in lines
        ):
            return False
        if header["content_mode"] == "skeleton" and any(
            line["line"] == "content" for line in lines
        ):
            return False
        records = [line for line in lines if line["line"] == "record"]
        inboxes = [line for line in lines if line["line"] == "inbox"]
        checkpoints = [line for line in lines if line["line"] == "checkpoint"]
        manifests = [line for line in lines if line["line"] == "manifest"]
        if len(manifests) != 1 or manifests[0]["head_seq"] != header["head_seq"]:
            return False
        if manifests[0]["record_lines"] != len(records):
            return False
        if manifests[0]["inbox_lines"] != len(inboxes):
            return False
        if manifests[0]["checkpoint_lines"] != len(checkpoints):
            return False
        for line in records:
            record = line["record"]
            envelope = line["storage_envelope"]
            codec.validate(record)
            expected = storage_by_seq.get(envelope["seq"])
            if expected is None:
                return False
            if (
                envelope["record_digest"] != jcs_digest(root, record)
                or envelope["session_id"] != record["session_id"]
                or envelope["chain_digest"] != expected["envelope"]["chain_digest"]
                or envelope["record_digest"] != expected["envelope"]["record_digest"]
            ):
                return False
        for line in inboxes:
            codec.validate(line["input"], inbox=True)
        for line in checkpoints:
            expected = storage_by_seq.get(line["seq"])
            if expected is None or line["chain_digest"] != expected["envelope"]["chain_digest"]:
                return False
        for line in lines:
            if line["line"] != "content":
                continue
            content = catalog_contents.get(line["content_id"])
            if (
                content is None
                or content["key_id"] != line["key_id"]
                or content["value"] != line["decoded_value"]
                or line["key_id"] not in catalog_keys
            ):
                return False
        return True

    export_accepted = export_rejected = 0
    for case in lifecycle["export_cases"]:
        require(export_valid(case) == case["accepted"], f"export case outcome: {case['name']}")
        if case["accepted"]:
            export_accepted += 1
        else:
            export_rejected += 1
    return destroy_accepted + destroy_rejected, forget_accepted + forget_rejected, export_accepted + export_rejected


def validate_trusted_storage(
    root: Path, codec: Codec, fixture: dict[str, Any]
) -> int:
    provenance = fixture["provenance"]
    require(fixture["status"] == "producer-captured", "trusted fixture status")
    require(provenance["producer_capture"] is True, "producer capture provenance")
    require(
        isinstance(provenance.get("source_revision"), str)
        and re.fullmatch(r"[0-9a-f]{40}", provenance["source_revision"]) is not None,
        "producer capture revision",
    )
    require(
        fixture.get("revision") == provenance["source_revision"],
        "trusted fixture revision",
    )
    require(
        isinstance(provenance.get("source_tree_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", provenance["source_tree_sha256"])
        is not None,
        "producer source tree digest",
    )
    require(fixture.get("record_schema_version") == "S1", "record schema capture")
    require(fixture.get("inbox_schema_version") == "S1", "inbox schema capture")
    accepted = {case["name"]: case for case in fixture["accepted_cases"]}
    for case in accepted.values():
        raw = decode(case)
        wire = strict_json_loads(raw.decode("utf-8"))
        require(wire == case["wire"], "trusted wire bytes")
        require(
            case["canonical_json_base64"] == case["bytes_base64"],
            "trusted canonical bytes",
        )
        require(case["canonical_json_utf8_bytes"] == len(raw), "trusted byte count")
        require(case["wire"]["schema_version"] == "S1", "trusted logical schema version")
        require(case["wire"]["feature_level"] == 1, "trusted logical feature level")
        require(
            case["content_refs"] == content_ref_entries(wire),
            f"trusted ContentRef evidence: {case['name']}",
        )
        require(bool(case["content_refs"]), f"trusted case has no ContentRef: {case['name']}")
        require(
            case["producer"].startswith("vv_agent.session.records.")
            and case["producer"].endswith(".encode"),
            f"trusted producer: {case['name']}",
        )
        codec.validate(case["wire"], inbox="record_id" not in case["wire"])
    for case in fixture["rejected_cases"]:
        wire = case_base = accepted[case["base"]]["wire"]
        wire = json.loads(json.dumps(case_base))
        for operation in case["patch"]:
            target: Any = wire
            for part in operation["path"][:-1]:
                target = target[part]
            if operation.get("delete"):
                del target[operation["path"][-1]]
            else:
                target[operation["path"][-1]] = operation["set"]
        try:
            codec.validate(wire, inbox="record_id" not in wire)
        except ValidationError:
            continue
        raise ValidationError(f"trusted negative accepted: {case['name']}")
    return len(fixture["rejected_cases"])


def validate_content_catalog(
    root: Path,
    documents: dict[str, Any],
    streams: dict[str, Any],
    catalog: dict[str, Any],
) -> None:
    require(catalog["status"] == "synthetic-contract-fixture", "content catalog provenance")
    keys = {entry["key_id"]: entry for entry in catalog["keys"]}
    items = sorted(catalog["contents"].items())
    canonical = subprocess.run(
        ["node", str(root / "scripts/verify_jcs.mjs"), "--canonicalize"],
        input=json.dumps([entry["value"] for _, entry in items], ensure_ascii=True, allow_nan=False),
        text=True,
        capture_output=True,
        check=False,
    )
    require(canonical.returncode == 0, f"content canonicalization: {canonical.stderr[:500]}")
    encoded_values = json.loads(canonical.stdout)
    require(len(encoded_values) == len(items), "content canonicalization count")
    refs_by_id: dict[str, list[dict[str, Any]]] = {}
    current_documents = {
        name: document
        for name, document in documents.items()
        if document.get("historical_contract_version") != "39.0.0"
        and name not in {"session_content_catalog.json", "trusted_storage_s1.json"}
    }
    for node in walk([current_documents, streams]):
        if (
            isinstance(node, dict)
            and set(node) == {"content_id", "mac", "size", "key_id", "labels"}
            and isinstance(node["content_id"], str)
        ):
            refs_by_id.setdefault(node["content_id"], []).append(node)
    require(
        set(refs_by_id) <= set(catalog["contents"]),
        f"unresolved content references: {sorted(set(refs_by_id) - set(catalog['contents']))[:5]}",
    )
    for (content_id, entry), encoded in zip(items, encoded_values):
        require(entry["key_id"] in keys, f"missing content key: {content_id}")
        plaintext = base64.b64decode(encoded, validate=True)
        expected = hmac.new(
            base64.b64decode(keys[entry["key_id"]]["key_base64"], validate=True),
            plaintext,
            hashlib.sha256,
        ).hexdigest()
        for reference in refs_by_id.get(content_id, []):
            require(reference["key_id"] == entry["key_id"], f"content key: {content_id}")
            require(reference["mac"] == expected, f"content MAC: {content_id}")
            require(reference["size"] == len(plaintext), f"content size: {content_id}")


def hydrate_content_refs(value: Any, catalog: dict[str, Any]) -> Any:
    contents = catalog["contents"]
    if (
        isinstance(value, dict)
        and set(value) == {"content_id", "mac", "size", "key_id", "labels"}
        and value.get("content_id") in contents
        and contents[value["content_id"]]["key_id"] == value.get("key_id")
    ):
        return hydrate_content_refs(contents[value["content_id"]]["value"], catalog)
    if isinstance(value, dict):
        return {key: hydrate_content_refs(item, catalog) for key, item in value.items()}
    if isinstance(value, list):
        return [hydrate_content_refs(item, catalog) for item in value]
    return value


def validate_session_fixtures(root: Path) -> dict[str, int]:
    fixtures = root / "fixtures"
    documents = {p.name: load_json(p) for p in fixtures.glob("*.json")}
    streams = {
        p.name: [strict_json_loads(line) for line in p.read_text().splitlines()]
        for p in fixtures.glob("*.jsonl")
    }
    invalid = documents["session_invalid.json"]["vectors"]
    decoded = []
    for vector in invalid:
        try:
            decoded.append(strict_json_loads(decode(vector).decode("utf-8")))
        except (ValueError, UnicodeError):
            pass
    codec = Codec(root, [documents, streams, decoded])
    catalog = documents["session_content_catalog.json"]
    counts = Counter()
    historical_documents = {
        name
        for name, document in documents.items()
        if document.get("historical_contract_version") == "39.0.0"
    }
    require(
        historical_documents == HISTORICAL_SESSION_FIXTURES,
        "historical session fixture inventory mismatch",
    )
    current_documents = {
        name: document
        for name, document in documents.items()
        if name not in historical_documents
    }
    validate_content_catalog(root, documents, streams, catalog)
    storage_cases = validate_storage_fixtures(root, codec, documents)
    lifecycle_cases = validate_lifecycle_fixtures(root, codec, documents, catalog)
    trusted_negatives = validate_trusted_storage(
        root, codec, documents["trusted_storage_s1.json"]
    )
    for node in walk([current_documents, streams]):
        if not isinstance(node, dict) or not isinstance(node.get("kind"), str):
            continue
        if "record_id" in node and "payload" in node:
            try:
                codec.validate(node)
            except ValidationError as exc:
                raise ValidationError(f"record {node['record_id']}: {exc}") from exc
            counts["records"] += 1
        elif "input_id" in node and "available_ms" in node:
            codec.validate(node, inbox=True)
            counts["inbox_items"] += 1
    vectors = documents["session_codec_vectors.json"]["vectors"]
    require(
        all(v["type"] in {"record", "inbox"} for v in vectors),
        "unknown codec vector type",
    )
    records = [v["wire"] for v in vectors if v["type"] == "record"]
    incoming = [v["wire"] for v in vectors if v["type"] == "inbox"]
    inventory = {
        "record_kinds": {r["kind"] for r in records},
        "inbox_kinds": {i["kind"] for i in incoming},
        "boundary_stages": {
            r["payload"]["stage"] for r in records if r["kind"] == "boundary_recorded"
        },
        "handle_variants": {
            r["payload"]["handle"]["kind"] for r in records if r["kind"] == "op_parked"
        },
    }
    coverage = documents["session_codec_vectors.json"]["coverage"]
    for key, expected in zip(
        inventory, (RECORD_KINDS, INBOX_KINDS, BOUNDARY_STAGES, HANDLE_VARIANTS)
    ):
        require(
            inventory[key] == expected == set(coverage[key]),
            f"incomplete coverage: {key}",
        )
        require(
            all(type(v) is int and v > 0 for v in coverage[key].values()),
            f"invalid coverage counts: {key}",
        )
    require(
        all(type(v) is int and v > 0 for v in coverage["optional_fields"].values()),
        "optional coverage",
    )
    classes = set()
    for vector in invalid:
        label, layer = vector["rejection_class"], vector["layer"]
        require(label not in classes, f"duplicate rejection class: {label}")
        classes.add(label)
        raw = decode(vector)
        if layer in {"fold", "admission", "input_conflict"}:
            require(
                bool(vector.get("reason")), f"missing {layer} rejection reason: {label}"
            )
            if layer == "fold":
                require(bool(vector.get("prefix_ids")), f"missing fold prefix: {label}")
                source_ids = {
                    r["record_id"]
                    for r in documents["session_invalid.json"]["source_records"]
                }
                require(
                    set(vector["prefix_ids"]) <= source_ids,
                    f"unretained fold prefix: {label}",
                )
            else:
                require(
                    bool(vector.get("audit_record_id")),
                    f"missing admission audit: {label}",
                )
                if layer == "input_conflict":
                    original = next(
                        r
                        for r in documents["session_invalid.json"]["source_records"]
                        if r["session_id"] == vector["session_id"]
                        and r["record_id"] == vector["audit_record_id"]
                    )
                    incoming = strict_json_loads(raw.decode("utf-8"))
                    require(
                        original["payload"]["input"]["input_id"]
                        == incoming["input_id"],
                        "conflict input identity",
                    )
                    require(
                        original["payload"]["input"] != incoming,
                        "conflict needs changed payload",
                    )
            continue
        require(
            layer in {"codec", "inbox_codec", "constructor"},
            f"unknown rejection layer: {layer}",
        )
        if layer == "constructor":
            require(
                vector.get("mutation") in {"non_string_key", "non_json_host_object"},
                f"unknown constructor mutation: {label}",
            )
        try:
            wire = strict_json_loads(raw.decode("utf-8"))
            if layer == "constructor":
                if vector.get("mutation") == "non_string_key":
                    wire["payload"]["request"][1] = "value"
                elif vector.get("mutation") == "non_json_host_object":
                    wire["payload"]["request"]["host"] = object()
            codec.validate(wire, inbox=layer == "inbox_codec")
        except (ValidationError, ValueError, UnicodeError):
            continue
        raise ValidationError(f"accepted invalid {layer} vector: {label}")
    require(
        {
            "missing_version",
            "stale_version",
            "unknown_version",
            "malformed_version",
            "float_integer",
            "boolean_integer",
            "duplicate_member",
            "embedded_digest",
            "wrong_identity",
            "trailing_newline_hash",
            "closed_reserved_metadata",
            "closed_task_metadata",
            "closed_child_task_metadata",
            "stale_inbox_version",
            "missing_provider_usage",
            "extra_provider_field",
            "null_provider_usage",
            "nonobject_provider_usage",
        }
        <= classes,
        "codec negative coverage",
    )
    for name in ("session_semantics.json", "session_recovery.json"):
        cases = documents[name]["cases"]
        require(bool(cases), f"empty {name}")
        require(
            len({c["case"] for c in cases}) == len(cases), f"duplicate case in {name}"
        )
    require(
        bool(documents["session_projection.json"]["sessions"]),
        "empty session projections",
    )
    require(
        bool(documents["session_compaction.json"]["vectors"]),
        "empty compaction vectors",
    )
    require(
        all(
            v["wire"]["kind"] == "context_compacted"
            for v in documents["session_compaction.json"]["vectors"]
        ),
        "invalid compaction vector kind",
    )
    app = documents["app_server_protocol.json"]
    require(app["protocol_version"] == "v5", "App Server version mismatch")
    require(bool(app["transcripts"]), "empty App Server transcripts")
    require(len(app["schemas"]["jsonSchema"]) == 26, "App Server JSON bundle coverage")
    require(
        len(app["schemas"]["typescript"]) == 25, "App Server TypeScript bundle coverage"
    )
    statuses = [
        "idle",
        "running",
        "provider_running",
        "child_running",
        "user_wait",
        "approval_wait",
        "retry_backoff",
        "suspended",
        "terminal",
        "archived",
        "closed",
    ]
    for source in app["schemas"]["jsonSchema"].values():
        for node in walk(strict_json_loads(source)):
            if isinstance(node, dict) and "enum" in node and "archived" in node["enum"]:
                require(node["enum"] == statuses, "inconsistent thread status enum")
    return {
        **counts,
        "codec_vectors": len(vectors),
        "invalid_vectors": len(invalid),
        "storage_envelope_cases": sum(storage_cases),
        "storage_lifecycle_cases": sum(lifecycle_cases),
        "trusted_negative_cases": trusted_negatives,
    }
