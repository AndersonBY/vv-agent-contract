"""Strict current session fixture checks, independent of runtime implementation."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from contractctl import load_json, strict_json_loads

DRAFT = "https://json-schema.org/draft/2020-12/schema"
RECORD_KINDS = {
    "session_created", "turn_started", "input_applied", "op_planned",
    "op_prepared", "turn_parked", "op_started", "op_parked", "op_completed",
    "op_unknown", "context_compacted", "boundary_recorded", "usage_observed", "turn_ended",
}
INBOX_KINDS = {
    "user", "steer", "follow_up", "provider_result", "approval_answer",
    "child_result", "control", "provider_evidence",
}
BOUNDARY_STAGES = {
    "before_memory", "after_cycle", "memory_started", "memory_completed",
    "session_memory_saved", "output_checked", "budget",
}
HANDLE_VARIANTS = {"provider", "approval", "user", "child"}
KEYWORDS = {
    "$schema", "type", "const", "enum", "oneOf", "anyOf", "allOf", "if", "then",
    "properties", "required", "additionalProperties", "items", "minLength",
    "maxLength", "pattern", "minimum", "maximum",
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
    require(not set(schema) - KEYWORDS, f"unsupported schema keywords: {set(schema) - KEYWORDS}")
    for key in ("oneOf", "anyOf", "allOf"):
        for child in schema.get(key, []):
            check_schema_keywords(child)
    for key in ("if", "then", "items"):
        if key in schema:
            check_schema_keywords(schema[key])
    for child in schema.get("properties", {}).values():
        check_schema_keywords(child)


def matches(value: Any, schema: dict[str, Any]) -> bool:
    try:
        validate_schema(value, schema)
    except ValidationError:
        return False
    return True


def validate_schema(value: Any, schema: dict[str, Any]) -> None:
    """Draft 2020-12 keywords emitted here, with codec-strict integer types."""
    if "type" in schema:
        types = {
            "null": value is None, "boolean": type(value) is bool,
            "integer": type(value) is int, "number": type(value) in (int, float),
            "string": isinstance(value, str), "array": isinstance(value, list),
            "object": isinstance(value, dict),
        }
        require(types[schema["type"]], f"expected {schema['type']}")
    if "const" in schema:
        require(value == schema["const"], "const mismatch")
    if "enum" in schema:
        require(value in schema["enum"], "enum mismatch")
    for key in ("oneOf", "anyOf"):
        if key in schema:
            count = sum(matches(value, branch) for branch in schema[key])
            require(count == 1 if key == "oneOf" else count > 0, f"{key} mismatch")
    for child in schema.get("allOf", []):
        validate_schema(value, child)
    if "if" in schema and matches(value, schema["if"]) and "then" in schema:
        validate_schema(value, schema["then"])
    if isinstance(value, dict):
        require(set(schema.get("required", [])) <= set(value), "missing required fields")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(set(value) <= set(properties), "unknown fields")
        for key in value.keys() & properties.keys():
            validate_schema(value[key], properties[key])
    if isinstance(value, list) and "items" in schema:
        for item in value:
            validate_schema(item, schema["items"])
    if isinstance(value, str):
        require(len(value) >= schema.get("minLength", 0), "short string")
        require(len(value) <= schema.get("maxLength", math.inf), "long string")
        if "pattern" in schema:
            require(re.search(schema["pattern"], value) is not None, "pattern mismatch")
    if type(value) in (int, float):
        require(schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf), "number bounds")


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
        suffix = "" if p["summary_operation_id"] is None else "/" + p["summary_operation_id"]
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
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


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
        for schema, kinds in ((self.record_schema, RECORD_KINDS), (self.inbox_schema, INBOX_KINDS)):
            require(schema.get("$schema") == DRAFT, "schema draft mismatch")
            check_schema_keywords(schema)
            require({s["properties"]["kind"]["const"] for s in schema["oneOf"]} == kinds, "schema kind coverage")
        inputs = {json_key(v): v for v in digest_inputs(documents)}
        result = subprocess.run(
            ["node", str(root / "scripts/verify_jcs.mjs"), "--canonicalize"],
            input=json.dumps(list(inputs.values()), ensure_ascii=True, allow_nan=False),
            text=True, capture_output=True, check=False,
        )
        require(result.returncode == 0, f"canonical encoding failed: {result.stderr[:500]}")
        canonical = json.loads(result.stdout)
        require(len(canonical) == len(inputs), "canonical encoding count mismatch")
        self.digests = {key: hashlib.sha256(base64.b64decode(raw, validate=True)).hexdigest()
                        for key, raw in zip(inputs, canonical)}

    def digest(self, value: Any) -> str:
        return self.digests[json_key(value)]

    def validate(self, wire: Any, *, inbox: bool = False) -> None:
        json_value(wire)
        validate_schema(wire, self.inbox_schema if inbox else self.record_schema)
        if inbox:
            return
        kind, p = wire["kind"], wire["payload"]
        require(wire["record_id"] == record_id(wire), "wrong record identity")
        operation = kind.startswith("op_")
        require((wire["operation_id"] is not None) == operation, "operation identity nullability")
        require((wire["attempt"] is not None) == operation, "attempt nullability")
        if kind == "session_created":
            require(wire["turn_id"] is None, "creation turn must be null")
        elif kind not in {"input_applied", "usage_observed"}:
            require(wire["turn_id"] is not None, "turn required")
        if kind == "op_planned":
            require((p["purpose"] is not None) == (p["op_kind"] == "model"), "purpose nullability")
        pair = {
            "turn_started": ("definition_digest", "definition"),
            "op_planned": ("request_digest", "request"),
            "op_prepared": ("request_digest", "request"),
            "op_completed": ("result_digest", "result"),
            "input_applied": ("input_digest", "input"),
        }.get(kind)
        if pair:
            require(p[pair[0]] == self.digest(p[pair[1]]), "embedded digest mismatch")
        child = p.get("attributes", {}).get("child_admission")
        if child:
            require(child["definition_digest"] == self.digest(child["definition"]), "child definition digest")
        if kind == "input_applied":
            self.validate(p["input"], inbox=True)


def decode(vector: dict[str, Any]) -> bytes:
    raw = base64.b64decode(vector["bytes_base64"], validate=True)
    require(hashlib.sha256(raw).hexdigest() == vector["sha256"], "invalid vector byte hash")
    return raw


def validate_session_fixtures(root: Path) -> dict[str, int]:
    fixtures = root / "fixtures"
    documents = {p.name: load_json(p) for p in fixtures.glob("*.json")}
    streams = {p.name: [strict_json_loads(line) for line in p.read_text().splitlines()]
               for p in fixtures.glob("*.jsonl")}
    invalid = documents["session_invalid.json"]["vectors"]
    decoded = []
    for vector in invalid:
        try:
            decoded.append(strict_json_loads(decode(vector).decode("utf-8")))
        except (ValueError, UnicodeError):
            pass
    codec = Codec(root, [documents, streams, decoded])
    counts = Counter()
    for node in walk([documents, streams]):
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
    require(all(v["type"] in {"record", "inbox"} for v in vectors), "unknown codec vector type")
    records = [v["wire"] for v in vectors if v["type"] == "record"]
    incoming = [v["wire"] for v in vectors if v["type"] == "inbox"]
    inventory = {
        "record_kinds": {r["kind"] for r in records},
        "inbox_kinds": {i["kind"] for i in incoming},
        "boundary_stages": {r["payload"]["stage"] for r in records if r["kind"] == "boundary_recorded"},
        "handle_variants": {r["payload"]["handle"]["kind"] for r in records if r["kind"] == "op_parked"},
    }
    coverage = documents["session_codec_vectors.json"]["coverage"]
    for key, expected in zip(inventory, (RECORD_KINDS, INBOX_KINDS, BOUNDARY_STAGES, HANDLE_VARIANTS)):
        require(inventory[key] == expected == set(coverage[key]), f"incomplete coverage: {key}")
        require(all(type(v) is int and v > 0 for v in coverage[key].values()), f"invalid coverage counts: {key}")
    require(all(type(v) is int and v > 0 for v in coverage["optional_fields"].values()), "optional coverage")
    classes = set()
    for vector in invalid:
        label, layer = vector["rejection_class"], vector["layer"]
        require(label not in classes, f"duplicate rejection class: {label}")
        classes.add(label)
        raw = decode(vector)
        if layer in {"fold", "admission"}:
            require(bool(vector.get("reason")), f"missing {layer} rejection reason: {label}")
            if layer == "fold":
                require(bool(vector.get("prefix_ids")), f"missing fold prefix: {label}")
                source_ids = {r["record_id"] for r in documents["session_invalid.json"]["source_records"]}
                require(set(vector["prefix_ids"]) <= source_ids, f"unretained fold prefix: {label}")
            else:
                require(bool(vector.get("audit_record_id")), f"missing admission audit: {label}")
            continue
        require(layer in {"codec", "inbox_codec", "constructor"}, f"unknown rejection layer: {layer}")
        if layer == "constructor":
            require(vector.get("mutation") in {"non_string_key", "non_json_host_object"},
                    f"unknown constructor mutation: {label}")
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
    require({"missing_version", "stale_version", "unknown_version", "malformed_version",
             "float_integer", "boolean_integer", "duplicate_member", "embedded_digest",
             "wrong_identity", "trailing_newline_hash", "closed_reserved_metadata",
             "closed_task_metadata", "closed_child_task_metadata"} <= classes, "codec negative coverage")
    for name in ("session_semantics.json", "session_recovery.json"):
        cases = documents[name]["cases"]
        require(bool(cases), f"empty {name}")
        require(len({c["case"] for c in cases}) == len(cases), f"duplicate case in {name}")
    require(bool(documents["session_projection.json"]["sessions"]), "empty session projections")
    require(bool(documents["session_compaction.json"]["vectors"]), "empty compaction vectors")
    require(all(v["wire"]["kind"] == "context_compacted"
                for v in documents["session_compaction.json"]["vectors"]), "invalid compaction vector kind")
    app = documents["app_server_protocol.json"]
    require(app["protocol_version"] == "v2", "App Server version mismatch")
    require(bool(app["transcripts"]), "empty App Server transcripts")
    require(len(app["schemas"]["jsonSchema"]) == 19, "App Server JSON bundle coverage")
    require(len(app["schemas"]["typescript"]) == 18, "App Server TypeScript bundle coverage")
    statuses = ["idle", "running", "interrupted", "archived", "closed"]
    for source in app["schemas"]["jsonSchema"].values():
        for node in walk(strict_json_loads(source)):
            if isinstance(node, dict) and "enum" in node and "archived" in node["enum"]:
                require(node["enum"] == statuses, "inconsistent thread status enum")
    return {**counts, "codec_vectors": len(vectors), "invalid_vectors": len(invalid)}
