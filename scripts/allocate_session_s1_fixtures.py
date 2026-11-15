#!/usr/bin/env python3
"""Allocate synthetic S1 reference-form fixtures without claiming adoption."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import json
import struct
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
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
ACTIVE_JSON = (
    "session_codec_vectors.json",
    "session_compaction.json",
    "session_invalid.json",
    "session_projection.json",
    "session_recovery.json",
    "session_semantics.json",
)
ACTIVE_JSONL = ("session_inbox.jsonl", "session_records.jsonl")


def canonical(value: Any) -> bytes:
    # Escape lone surrogates so intentionally invalid content can still be
    # allocated as a sealed negative fixture instead of crashing the encoder.
    source = json.dumps([value], ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    result = subprocess.run(
        ["node", str(ROOT / "scripts/verify_jcs.mjs"), "--canonicalize"],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return base64.b64decode(json.loads(result.stdout)[0], validate=True)


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def safe_sha(value: Any, fallback: str) -> str:
    try:
        return sha256(value)
    except (RuntimeError, TypeError, ValueError):
        return fallback


def is_ref(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {
        "content_id",
        "mac",
        "size",
        "key_id",
        "labels",
    }


class Allocator:
    def __init__(self) -> None:
        self.keys: dict[str, dict[str, str]] = {}
        self.contents: dict[str, dict[str, Any]] = {}
        self.used: set[str] = set()

    def _key(self, session_id: str) -> tuple[str, bytes]:
        key_id = f"key/{hashlib.sha256(session_id.encode()).hexdigest()[:16]}"
        raw = hashlib.sha256(f"fixture-content-key:{session_id}".encode()).digest()
        self.keys.setdefault(
            key_id,
            {"key_id": key_id, "key_base64": base64.b64encode(raw).decode("ascii")},
        )
        return key_id, raw

    def alloc(
        self,
        value: Any,
        session_id: str,
        slot: str,
        boundary: str,
        *,
        force: bool = False,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if is_ref(value) and not force:
            if value["content_id"] in self.contents:
                self.used.add(value["content_id"])
            return value
        key_id, key = self._key(session_id)
        base_id = "content/" + hashlib.sha256(
            f"fixture-slot:{session_id}\0{slot}".encode()
        ).hexdigest()[:24]
        content_id = base_id
        suffix = 1
        try:
            payload = canonical(value)
        except (RuntimeError, TypeError, ValueError):
            # Keep deliberately invalid content in the negative wire so the
            # closed ContentRef slot rejects it before it can enter storage.
            return value
        while content_id in self.contents and canonical(
            self.contents[content_id]["value"]
        ) != payload:
            suffix += 1
            content_id = f"{base_id}-{suffix}"
        self.contents[content_id] = {
            "session_id": session_id,
            "key_id": key_id,
            "boundary": boundary,
            "value": value,
        }
        self.used.add(content_id)
        return {
            "content_id": content_id,
            "mac": hmac.new(key, payload, hashlib.sha256).hexdigest(),
            "size": len(payload),
            "key_id": key_id,
            "labels": {"source": [], "classification": "internal"},
        }

    def catalog(self) -> dict[str, Any]:
        used_contents = {
            key: self.contents[key] for key in sorted(self.used) if key in self.contents
        }
        return {
            "schema_version": "vv-agent.session-content-doubles.v1",
            "status": "synthetic-contract-fixture",
            "note": "Content objects are separate from logical record/inbox bytes and are never producer-adoption evidence.",
            "keys": [
                self.keys[key]
                for key in sorted(
                    {entry["key_id"] for entry in used_contents.values()}
                )
            ],
            "contents": used_contents,
        }

    def load_catalog(self, path: Path) -> None:
        if not path.is_file():
            return
        fixture = json.loads(path.read_text(encoding="utf-8"))
        self.keys = {item["key_id"]: item for item in fixture.get("keys", [])}
        self.contents = fixture.get("contents", {})


def transform_principal(value: dict[str, Any], *, session_id: str, slot: str, alloc: Allocator) -> None:
    subject_kind = value.get("subject_kind")
    value["subject_kind"] = "agent" if subject_kind == "system" else subject_kind
    attributes = value.get("attributes", {})
    known_ref = is_ref(attributes) and attributes["content_id"] in alloc.contents
    value["attributes"] = alloc.alloc(
        attributes if known_ref else {},
        session_id,
        f"{slot}.attributes",
        "principal_attributes",
        force=not known_ref,
    )


def transform_handle(value: dict[str, Any], *, session_id: str, slot: str, alloc: Allocator) -> None:
    kind = value["kind"]
    if kind == "provider":
        for field in ("job_id", "evidence", "query_ref", "cancel_ref"):
            value[field] = alloc.alloc(
                value.get(field), session_id, f"{slot}.{field}", f"provider_handle_{field}"
            )
    elif kind == "approval":
        value["scope"] = alloc.alloc(
            value["scope"], session_id, f"{slot}.scope", "approval_scope"
        )
    elif kind == "user":
        value["question"] = alloc.alloc(
            value["question"], session_id, f"{slot}.question", "user_question"
        )


def transform_delegation(value: dict[str, Any], *, session_id: str, slot: str, alloc: Allocator) -> None:
    for field in ("agent_name", "metadata"):
        value[field] = alloc.alloc(
            value[field], session_id, f"{slot}.{field}", f"delegation_{field}"
        )


def transform_inbox(value: dict[str, Any], *, session_id: str, slot: str, alloc: Allocator) -> None:
    if isinstance(value.get("actor"), dict):
        transform_principal(value["actor"], session_id=session_id, slot=f"{slot}.actor", alloc=alloc)
    kind = value.get("kind")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        return
    if kind in {"user", "steer", "follow_up"}:
        payload["content"] = alloc.alloc(
            payload["content"], session_id, f"{slot}.content", "inbox_content"
        )
    elif kind == "model_selection":
        payload["selection"] = alloc.alloc(
            payload.get("selection"), session_id, f"{slot}.selection", "model_selection"
        )
    elif kind == "provider_result":
        for field in ("result", "usage", "evidence"):
            if field in payload:
                payload[field] = alloc.alloc(
                    payload[field], session_id, f"{slot}.{field}", f"provider_result_{field}"
                )
    elif kind == "approval_answer":
        if "scope" in payload:
            payload["scope"] = alloc.alloc(
                payload["scope"], session_id, f"{slot}.scope", "approval_scope"
            )
        for field in ("reason", "metadata"):
            payload[field] = alloc.alloc(
                payload.get(field), session_id, f"{slot}.{field}", f"approval_{field}"
            )
        payload.setdefault("policy_digest", None)
        payload.setdefault("rule_id", None)
        payload.setdefault("expires_ms", None)
    elif kind == "child_result":
        if "result" in payload:
            payload["result"] = alloc.alloc(
                payload["result"], session_id, f"{slot}.result", "child_result"
            )
    elif kind == "provider_evidence":
        if "handle" in payload:
            transform_handle(
                payload["handle"], session_id=session_id, slot=f"{slot}.handle", alloc=alloc
            )


def transform_record(value: dict[str, Any], *, slot: str, alloc: Allocator) -> None:
    value.pop("chain_digest", None)
    session_id = value.get("session_id") or "fixture-session"
    kind = value["kind"]
    payload = value["payload"]
    if kind == "session_created":
        if isinstance(payload.get("principal"), dict):
            transform_principal(
                payload["principal"], session_id=session_id, slot=f"{slot}.principal", alloc=alloc
            )
        payload["workspace"] = alloc.alloc(
            payload["workspace"], session_id, f"{slot}.workspace", "workspace"
        )
        payload["attributes"] = alloc.alloc(
            payload["attributes"], session_id, f"{slot}.attributes", "session_attributes"
        )
    elif kind == "turn_started":
        payload["definition"] = alloc.alloc(
            payload["definition"], session_id, f"{slot}.definition", "definition"
        )
        payload["budget"] = alloc.alloc(
            payload["budget"], session_id, f"{slot}.budget", "budget"
        )
        payload["definition_digest"] = safe_sha(payload["definition"], payload["definition_digest"])
        payload.setdefault("tokenizer_binding", None)
        environment = payload.get("environment")
        if environment is not None:
            environment["descriptor"] = alloc.alloc(
                environment["descriptor"],
                session_id,
                f"{slot}.environment.descriptor",
                "environment_descriptor",
            )
            environment["operational_policy"] = alloc.alloc(
                environment.get("operational_policy"),
                session_id,
                f"{slot}.environment.operational_policy",
                "operational_policy",
            )
    elif kind == "input_applied":
        transform_inbox(
            payload["input"], session_id=session_id, slot=f"{slot}.input", alloc=alloc
        )
        payload["input_digest"] = safe_sha(payload["input"], payload["input_digest"])
        payload["reason"] = alloc.alloc(
            payload.get("reason"), session_id, f"{slot}.reason", "input_reason"
        )
        if "model_binding" in payload:
            payload["model_binding"] = alloc.alloc(
                payload["model_binding"], session_id, f"{slot}.model_binding", "model_binding"
            )
    elif kind == "op_planned":
        for field, boundary in (
            ("request", "request"),
            ("tool", "tool"),
            ("budget_admission", "budget_admission"),
        ):
            payload[field] = alloc.alloc(
                payload.get(field), session_id, f"{slot}.{field}", boundary
            )
        payload["request_digest"] = safe_sha(payload["request"], payload["request_digest"])
        payload.setdefault("policy_decision", None)
    elif kind == "op_prepared":
        for field in ("request", "tool", "hook_result", "shared_state"):
            payload[field] = alloc.alloc(
                payload.get(field), session_id, f"{slot}.{field}", field
            )
        payload["request_digest"] = safe_sha(payload["request"], payload["request_digest"])
        payload.setdefault("policy_decision", None)
    elif kind == "turn_parked":
        payload["question"] = alloc.alloc(
            payload.get("question"), session_id, f"{slot}.question", "turn_question"
        )
    elif kind == "op_parked":
        transform_handle(
            payload["handle"], session_id=session_id, slot=f"{slot}.handle", alloc=alloc
        )
        if "interaction_result" in payload:
            payload["interaction_result"] = alloc.alloc(
                payload.get("interaction_result"),
                session_id,
                f"{slot}.interaction_result",
                "interaction_result",
            )
        if "delegation" in payload:
            transform_delegation(
                payload["delegation"],
                session_id=session_id,
                slot=f"{slot}.delegation",
                alloc=alloc,
            )
    elif kind == "op_completed":
        for field, boundary in (
            ("result", "result"),
            ("usage", "usage"),
            ("shared_state", "shared_state"),
            ("evidence", "evidence"),
        ):
            payload[field] = alloc.alloc(
                payload.get(field), session_id, f"{slot}.{field}", boundary
            )
        payload["result_digest"] = safe_sha(payload["result"], payload["result_digest"])
        payload.setdefault("policy_decision", None)
    elif kind == "op_unknown":
        for field in ("reason", "dispatch_evidence", "observation"):
            payload[field] = alloc.alloc(
                payload.get(field), session_id, f"{slot}.{field}", f"op_unknown_{field}"
            )
    elif kind == "context_compacted":
        payload["replacement"] = [
            alloc.alloc(item, session_id, f"{slot}.replacement[{index}]", "message")
            for index, item in enumerate(payload["replacement"])
        ]
        payload["evidence_manifest"] = alloc.alloc(
            payload["evidence_manifest"],
            session_id,
            f"{slot}.evidence_manifest",
            "evidence_manifest",
        )
    elif kind == "boundary_recorded":
        stage = payload["stage"]
        data = payload["data"]
        if stage == "before_memory":
            data["messages"] = [
                alloc.alloc(item, session_id, f"{slot}.messages[{index}]", "message")
                for index, item in enumerate(data["messages"])
            ]
            data["shared_state"] = alloc.alloc(
                data["shared_state"], session_id, f"{slot}.shared_state", "shared_state"
            )
        elif stage == "after_cycle":
            data["steering_messages"] = [
                alloc.alloc(item, session_id, f"{slot}.steering[{index}]", "message")
                for index, item in enumerate(data["steering_messages"])
            ]
            data["shared_state"] = alloc.alloc(
                data["shared_state"], session_id, f"{slot}.shared_state", "shared_state"
            )
            data["error"] = alloc.alloc(
                data.get("error"), session_id, f"{slot}.error", "boundary_error"
            )
            if data.get("stop") is not None:
                data["stop"]["message"] = alloc.alloc(
                    data["stop"]["message"],
                    session_id,
                    f"{slot}.stop.message",
                    "stop_message",
                )
        elif stage in {"memory_started", "memory_completed"}:
            data["event"] = alloc.alloc(
                data["event"], session_id, f"{slot}.event", "memory_event"
            )
        elif stage == "session_memory_saved":
            for index, entry in enumerate(data["state"]["entries"]):
                entry["content"] = alloc.alloc(
                    entry["content"],
                    session_id,
                    f"{slot}.state.entries[{index}].content",
                    "session_memory_content",
                )
        elif stage == "output_checked":
            data["reason"] = alloc.alloc(
                data.get("reason"), session_id, f"{slot}.reason", "output_reason"
            )
            data["value"] = alloc.alloc(
                data["value"], session_id, f"{slot}.value", "output_value"
            )
            if "partial_output" in data:
                data["partial_output"] = alloc.alloc(
                    data.get("partial_output"),
                    session_id,
                    f"{slot}.partial_output",
                    "partial_output",
                )
        elif stage == "budget":
            data["usage"] = alloc.alloc(
                data["usage"], session_id, f"{slot}.usage", "budget_usage"
            )
            data["exhaustion"] = alloc.alloc(
                data.get("exhaustion"), session_id, f"{slot}.exhaustion", "budget_exhaustion"
            )
    elif kind == "usage_observed":
        payload["usage"] = alloc.alloc(
            payload["usage"], session_id, f"{slot}.usage", "usage"
        )
        payload["source"] = alloc.alloc(
            payload["source"], session_id, f"{slot}.source", "usage_source"
        )
    elif kind == "turn_ended":
        for field in ("reason", "result", "budget"):
            payload[field] = alloc.alloc(
                payload.get(field), session_id, f"{slot}.{field}", f"turn_ended_{field}"
            )


def looks_record(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("kind") in RECORD_KINDS
        and isinstance(value.get("payload"), dict)
        and ("record_id" in value or value.get("schema_version") in {1, "S1"})
    )


def looks_inbox(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("kind") in INBOX_KINDS
        and isinstance(value.get("payload"), dict)
        and ("actor" in value or "input_id" in value)
    )


def walk(value: Any, *, path: str, alloc: Allocator) -> Any:
    if looks_record(value):
        transform_record(value, slot=path, alloc=alloc)
        return value
    if looks_inbox(value):
        transform_inbox(value, session_id=f"inbox/{value.get('input_id', 'item')}", slot=path, alloc=alloc)
        return value
    if isinstance(value, dict):
        decoded_document: Any = None
        if "wire" in value and isinstance(value["wire"], dict):
            if looks_record(value["wire"]):
                transform_record(value["wire"], slot=f"{path}.wire", alloc=alloc)
            elif looks_inbox(value["wire"]):
                transform_inbox(
                    value["wire"],
                    session_id=f"inbox/{value['wire'].get('input_id', 'item')}",
                    slot=f"{path}.wire",
                    alloc=alloc,
                )
            if "bytes_base64" in value:
                update_bytes(value, value["wire"], path)
        elif "bytes_base64" in value:
            try:
                raw = base64.b64decode(value["bytes_base64"], validate=True)
                decoded = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                pass
            else:
                decoded_document = decoded
                if looks_record(decoded):
                    transform_record(decoded, slot=f"{path}.bytes", alloc=alloc)
                    digest_fields = (
                        "definition_digest",
                        "request_digest",
                        "result_digest",
                        "input_digest",
                    )
                    for digest_field in digest_fields:
                        if digest_field in decoded["payload"]:
                            if value.get("rejection_class") == "embedded_digest":
                                decoded["payload"][digest_field] = "0" * 64
                            elif value.get("rejection_class") == "trailing_newline_hash":
                                decoded["payload"][digest_field] += "\n"
                            elif value.get("rejection_class") == "uppercase_hash":
                                decoded["payload"][digest_field] = decoded["payload"][
                                    digest_field
                                ].upper()
                    update_bytes(value, decoded, path)
                    preserve_content_boundary_negative(value, decoded, path)
                    if value.get("rejection_class") == "duplicate_member":
                        raw = base64.b64decode(value["bytes_base64"], validate=True)
                        raw = (
                            raw[:-1]
                            + b',"duplicate_member":0,"duplicate_member":1}'
                        )
                        value["bytes_base64"] = base64.b64encode(raw).decode("ascii")
                        value["sha256"] = hashlib.sha256(raw).hexdigest()
                elif looks_inbox(decoded):
                    transform_inbox(
                        decoded,
                        session_id=f"inbox/{decoded.get('input_id', 'item')}",
                        slot=f"{path}.bytes",
                        alloc=alloc,
                    )
                    update_bytes(value, decoded, path)
                    preserve_content_boundary_negative(value, decoded, path)
        for key, child in list(value.items()):
            if key in {"wire", "bytes_base64", "sha256"}:
                continue
            walk(child, path=f"{path}.{key}", alloc=alloc)
        if decoded_document is not None and not (
            looks_record(decoded_document) or looks_inbox(decoded_document)
        ):
            rebuilt = {key: value[key] for key in decoded_document if key in value}
            update_bytes(value, rebuilt, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk(child, path=f"{path}[{index}]", alloc=alloc)
    return value


def collect_content_refs(value: Any, result: set[str]) -> None:
    if isinstance(value, dict):
        if set(value) == {"content_id", "mac", "size", "key_id", "labels"}:
            result.add(value["content_id"])
            return
        for child in value.values():
            collect_content_refs(child, result)
    elif isinstance(value, list):
        for child in value:
            collect_content_refs(child, result)


def update_bytes(holder: dict[str, Any], wire: Any, path: str) -> None:
    try:
        raw = canonical(wire)
    except (RuntimeError, TypeError, ValueError):
        # This is already an intentionally non-canonical negative case. Keep
        # its rejection cause while ensuring the old storage field is absent.
        raw = json.dumps(
            wire,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=True,
        ).encode("utf-8")
    holder["bytes_base64"] = base64.b64encode(raw).decode("ascii")
    holder["sha256"] = hashlib.sha256(raw).hexdigest()
    if isinstance(wire, dict) and wire.get("record_id"):
        holder["record_id"] = wire["record_id"]


def preserve_content_boundary_negative(
    holder: dict[str, Any], wire: dict[str, Any], path: str
) -> None:
    rejection_class = holder.get("rejection_class")
    content_slot = None
    if rejection_class == "closed_reserved_metadata":
        content_slot = ("payload", "request")
    elif rejection_class == "closed_task_metadata":
        content_slot = ("payload", "definition")
    elif rejection_class == "closed_child_task_metadata":
        content_slot = ("payload", "attributes")
    elif str(rejection_class).startswith("selection_"):
        content_slot = ("payload", "selection")
    elif rejection_class == "nonobject_provider_usage":
        content_slot = ("payload", "usage")
    if content_slot is not None:
        wire[content_slot[0]][content_slot[1]] = {
            "plaintext_content_rejected": rejection_class
        }
        update_bytes(holder, wire, path)


def transform_file(path: Path, alloc: Allocator) -> Any:
    document = json.loads(path.read_text(encoding="utf-8"))
    return walk(document, path=f"file:{path.name}", alloc=alloc)


def transform_jsonl(path: Path, alloc: Allocator) -> list[Any]:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        values.append(walk(value, path=f"file:{path.name}", alloc=alloc))
    return values


def transform_stream_paths(values: Iterable[dict[str, Any]]) -> None:
    for value in values:
        path = value.get("bytes_base64")
        if path is not None:
            update_bytes(value, value.get("wire") or json.loads(base64.b64decode(path, validate=True)), "stream")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def vector_bytes(value: Any) -> tuple[str, str]:
    raw = canonical(value)
    return base64.b64encode(raw).decode("ascii"), hashlib.sha256(raw).hexdigest()


def chain_digest(previous: str, seq: int, record_digest: str) -> str:
    return hashlib.sha256(
        bytes.fromhex(previous) + struct.pack(">Q", seq) + bytes.fromhex(record_digest)
    ).hexdigest()


def lp(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack(">I", len(raw)) + raw


def initial_chain(tenant_id: str, session_id: str) -> str:
    return hashlib.sha256(b"vv-agent/S1" + lp(tenant_id) + lp(session_id)).hexdigest()


def patch_wire(base: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    wire = copy.deepcopy(base)
    for operation in patches:
        target: Any = wire
        for part in operation["path"][:-1]:
            try:
                target = target[part]
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"patch path prefix is not traversable: {operation['path']}"
                ) from exc
        field = operation["path"][-1]
        try:
            if operation.get("delete"):
                del target[field]
            else:
                target[field] = operation["set"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"patch path is not writable: {operation['path']}") from exc
    return wire


def write_auxiliary_fixtures(root: Path, alloc: Allocator) -> None:
    fixtures = root / "fixtures"
    vectors = json.loads((fixtures / "session_codec_vectors.json").read_text(encoding="utf-8"))["vectors"]
    inboxes = [item["wire"] for item in vectors if item["type"] == "inbox"]
    records = [item["wire"] for item in vectors if item["type"] == "record"]
    session_created = next(item for item in records if item["kind"] == "session_created")
    turn_started = next(item for item in records if item["kind"] == "turn_started")
    op_planned = next(item for item in records if item["kind"] == "op_planned")
    op_prepared = next(item for item in records if item["kind"] == "op_prepared")
    op_completed = next(item for item in records if item["kind"] == "op_completed")
    boundary = next(
        item
        for item in records
        if item["kind"] == "boundary_recorded"
        and item["payload"]["stage"] in {"memory_started", "memory_completed"}
    )
    user_inbox = next(item for item in inboxes if item["kind"] == "user")
    provider_evidence = next(item for item in inboxes if item["kind"] == "provider_evidence")
    approval_answer = next(item for item in inboxes if item["kind"] == "approval_answer")

    record_digest = sha256(session_created)
    tenant_id = session_created["payload"]["principal"]["tenant_id"]
    session_id = session_created["session_id"]
    previous_chain = initial_chain(tenant_id, session_id)
    current_chain = chain_digest(previous_chain, 1, record_digest)
    envelope = {
        "schema_version": "S1",
        "tenant_id": tenant_id,
        "session_id": session_id,
        "seq": 1,
        "record_digest": record_digest,
        "chain_digest": current_chain,
        "writer_epoch": 7,
        "created_ms": 1800000000000,
    }
    bad_uppercase = copy.deepcopy(envelope)
    bad_uppercase["chain_digest"] = "A" * 64
    bad_seq = copy.deepcopy(envelope)
    bad_seq["seq"] = 0
    storage_created = next(
        item
        for item in records
        if item["kind"] == "session_created" and item["session_id"] == "micro"
    )
    storage_next = next(
        item
        for item in records
        if item["session_id"] == "micro" and item["kind"] == "boundary_recorded"
    )
    storage_tenant = storage_created["payload"]["principal"]["tenant_id"]
    storage_session = storage_created["session_id"]
    storage_initial = initial_chain(storage_tenant, storage_session)
    storage_record_1 = sha256(storage_created)
    storage_record_2 = sha256(storage_next)
    storage_chain_1 = chain_digest(storage_initial, 1, storage_record_1)
    storage_chain_2 = chain_digest(storage_chain_1, 2, storage_record_2)
    next_envelope = {
        "schema_version": "S1",
        "tenant_id": storage_tenant,
        "session_id": storage_session,
        "seq": 2,
        "record_digest": storage_record_2,
        "chain_digest": storage_chain_2,
        "writer_epoch": 7,
        "created_ms": 1800000000002,
    }
    stale_chain = copy.deepcopy(next_envelope)
    stale_chain["chain_digest"] = storage_chain_1
    wrong_session = copy.deepcopy(next_envelope)
    wrong_session["session_id"] = "other"
    storage_cases = {
        "schema_version": "vv-agent.session-storage-envelope-cases.v1",
        "status": "contract-allocation-only",
        "framing": {
            "domain": "vv-agent/S1",
            "initial_formula": "SHA256(UTF8(domain)||LP(tenant_id)||LP(session_id))",
            "next_formula": "SHA256(previous_chain||U64BE(seq)||HEX_DECODE(record_digest))",
            "identifier_encoding": "UTF-8 with unsigned 32-bit big-endian byte length prefix",
            "identity_rule": "chain_digest is excluded from logical record bytes and record identity",
        },
        "cases": [
            {
                "name": "accepted_initial_record_envelope",
                "accepted": True,
                "envelope": envelope,
                "logical_record": session_created,
                "logical_record_digest": record_digest,
                "previous_chain_digest": previous_chain,
                "reason": None,
            },
            {
                "name": "accepted_next_record_envelope",
                "accepted": True,
                "envelope": next_envelope,
                "logical_record": storage_next,
                "logical_record_digest": storage_record_2,
                "previous_chain_digest": storage_chain_1,
                "reason": None,
            },
            {
                "name": "uppercase_chain_digest",
                "accepted": False,
                "envelope": bad_uppercase,
                "logical_record": session_created,
                "logical_record_digest": record_digest,
                "previous_chain_digest": previous_chain,
                "reason": "Hashes require lowercase hexadecimal.",
            },
            {
                "name": "zero_sequence",
                "accepted": False,
                "envelope": bad_seq,
                "logical_record": session_created,
                "logical_record_digest": record_digest,
                "previous_chain_digest": previous_chain,
                "reason": "Record sequence starts at one.",
            },
            {
                "name": "stale_chain",
                "accepted": False,
                "envelope": stale_chain,
                "logical_record": storage_next,
                "logical_record_digest": storage_record_2,
                "previous_chain_digest": storage_chain_1,
                "reason": "The chain digest does not frame its predecessor and sequence.",
            },
            {
                "name": "logical_session_mismatch",
                "accepted": False,
                "envelope": wrong_session,
                "logical_record": storage_next,
                "logical_record_digest": storage_record_2,
                "previous_chain_digest": storage_chain_1,
                "reason": "The storage session identity must match the logical record.",
            },
        ],
    }
    write_json(fixtures / "session_storage_envelope.json", storage_cases)

    principal = session_created["payload"]["principal"]
    lifecycle = {
        "schema_version": "vv-agent.session-storage-lifecycle.v1",
        "status": "contract-allocation-only",
        "key_capability": {
            "tenant_id": tenant_id,
            "session_id": session_id,
            "key_id": session_created["payload"]["workspace"]["key_id"],
            "provider_id": "provider/local-fixture",
            "capability_id": "capability/session-key-1",
            "state": "active",
        },
        "destroy_cases": [
            {
                "name": "destroy_active_capability",
                "request": {"domain": "vv-agent/S1/key-destroy", "tenant_id": tenant_id, "key_id": session_created["payload"]["workspace"]["key_id"]},
                "accepted": True,
                "status": "destroyed",
                "evidence_id": "destroy/evidence/1",
                "reason": None,
            },
            {
                "name": "destroy_is_idempotent",
                "request": {"domain": "vv-agent/S1/key-destroy", "tenant_id": tenant_id, "key_id": session_created["payload"]["workspace"]["key_id"]},
                "accepted": True,
                "status": "already_destroyed",
                "evidence_id": "destroy/evidence/2",
                "reason": None,
            },
            {
                "name": "tenant_identity_mismatch",
                "request": {"domain": "vv-agent/S1/key-destroy", "tenant_id": "other", "key_id": session_created["payload"]["workspace"]["key_id"]},
                "accepted": False,
                "status": "binding_mismatch",
                "evidence_id": None,
                "reason": "Capability identity includes tenant.",
            },
        ],
        "forget_tombstone": {
            "tenant_id": tenant_id,
            "session_id": session_id,
            "final_seq": 1,
            "chain_digest": current_chain,
            "deleted_ms": 1800000000100,
            "actor": principal,
            "key_id": session_created["payload"]["workspace"]["key_id"],
            "signature": "AAECAwQ=",
            "state": "complete",
            "scope_root_session_id": session_id,
        },
        "forget_verification_cases": [],
        "export_cases": [],
    }
    header = {
        "line": "header",
        "export_version": 1,
        "storage_major": "S1",
        "tenant_id": tenant_id,
        "session_id": session_id,
        "head_seq": 1,
        "chain_digest": current_chain,
        "content_mode": "skeleton",
    }
    export_record = {"line": "record", "storage_envelope": envelope, "record": session_created}
    export_inbox = {"line": "inbox", "input_seq": 1, "received_ms": 1800000000001, "consumed_seq": None, "input": user_inbox}
    checkpoint = {"line": "checkpoint", "seq": 1, "chain_digest": current_chain, "key_id": "ledger/key-1", "signature": "AAECAwQ=", "signed_ms": 1800000000000}
    manifest = {"line": "manifest", "record_lines": 1, "inbox_lines": 1, "checkpoint_lines": 1, "head_seq": 1, "chain_digest": current_chain}
    lifecycle["export_cases"].append(
        {
            "name": "skeleton_export",
            "accepted": True,
            "header": header,
            "lines": [export_record, export_inbox, checkpoint, manifest],
            "reason": None,
        }
    )
    content_id = session_created["payload"]["workspace"]["content_id"]
    content_entry = alloc.contents[content_id]
    include_header = {**header, "content_mode": "include-content"}
    content_line = {
        "line": "content",
        "content_id": content_id,
        "key_id": content_entry["key_id"],
        "slot": "fixture.content",
        "decoded_value": content_entry["value"],
    }
    lifecycle["export_cases"].append(
        {
            "name": "explicit_content_export",
            "accepted": True,
            "header": include_header,
            "lines": [export_record, export_inbox, content_line, checkpoint, manifest],
            "reason": None,
        }
    )
    bad_header = {**header, "content_mode": "body"}
    lifecycle["export_cases"].append(
        {
            "name": "unknown_content_mode",
            "accepted": False,
            "header": bad_header,
            "lines": [manifest],
            "reason": "content_mode is closed.",
        }
    )
    lifecycle["export_cases"].append(
        {
            "name": "skeleton_export_contains_content",
            "accepted": False,
            "header": header,
            "lines": [export_record, content_line, checkpoint, manifest],
            "reason": "skeleton content_mode excludes content lines.",
        }
    )
    unsupported_header = {**header, "export_version": 2}
    lifecycle["export_cases"].append(
        {
            "name": "unsupported_export_version",
            "accepted": False,
            "header": unsupported_header,
            "lines": [manifest],
            "reason": "Only export_version 1 is current.",
        }
    )
    lifecycle["forget_verification_cases"] = [
        {
            "name": "verified_complete_tombstone",
            "tombstone": copy.deepcopy(lifecycle["forget_tombstone"]),
            "accepted": True,
            "reason": None,
        },
        {
            "name": "tombstone_head_mismatch",
            "tombstone": {
                **copy.deepcopy(lifecycle["forget_tombstone"]),
                "chain_digest": "0" * 64,
            },
            "accepted": False,
            "reason": "The tombstone head must match the retained final record.",
        },
        {
            "name": "tombstone_session_reuse",
            "tombstone": {
                **copy.deepcopy(lifecycle["forget_tombstone"]),
                "scope_root_session_id": "other",
            },
            "accepted": False,
            "reason": "A forgotten session identity cannot be reused.",
        },
    ]
    write_json(fixtures / "session_storage_lifecycle.json", lifecycle)

    enriched_turn = copy.deepcopy(turn_started)
    enriched_turn["payload"]["environment"] = {
        "descriptor": copy.deepcopy(turn_started["payload"]["definition"]),
        "environment_capabilities": ["command.execute", "network.deny"],
        "capabilities_digest": "2" * 64,
        "network_policy_ref_digest": "3" * 64,
        "isolation_policy_ref_digest": "4" * 64,
        "operational_policy": copy.deepcopy(turn_started["payload"]["budget"]),
    }
    enriched_turn["payload"]["tokenizer_binding"] = {
        "model_identity": "model-binding/fixture",
        "counting_method": "tokenizer",
        "implementation_id": "tokenizer/qwen-fixture",
        "asset_identity": "asset/qwen-fixture-v1",
        "normalization_id": "normalization/none",
    }
    enriched_completion = copy.deepcopy(op_completed)
    enriched_completion["payload"]["policy_decision"] = {
        "policy_digest": "1" * 64,
        "rule_id": "rule/allow-fixture",
        "effect": "allow",
    }
    enriched_completion["payload"]["usage_counts"] = {
        "tokens": {
            "input_tokens": 3,
            "output_tokens": 2,
            "total_tokens": 5,
            "reasoning_tokens": None,
            "usage_source": "provider_reported",
            "cache_usage": {
                "status": "provider_reported",
                "read_input_tokens": 1,
                "write_input_tokens": 0,
                "uncached_input_tokens": 2,
            },
        },
        "budget": {
            "cycles": 1,
            "tool_calls": 0,
            "elapsed_ms": 10,
            "total_tokens": 5,
            "uncached_input_tokens": 2,
            "tool_calls_by_name": {},
            "host_cost": {
                "amount_microunits": 7,
                "unit": session_created["payload"]["workspace"],
                "currency": session_created["payload"]["workspace"],
            },
            "unavailable_dimensions": [],
        },
    }
    enriched_plan = copy.deepcopy(op_planned)
    enriched_plan["payload"]["policy_decision"] = {
        "policy_digest": "1" * 64,
        "rule_id": "rule/plan-fixture",
        "effect": "allow",
    }
    enriched_preparation = copy.deepcopy(op_prepared)
    enriched_preparation["payload"]["policy_decision"] = {
        "policy_digest": "1" * 64,
        "rule_id": "rule/prepare-fixture",
        "effect": "require_approval",
    }
    enriched_approval = copy.deepcopy(approval_answer)
    enriched_approval["payload"]["policy_digest"] = "1" * 64
    enriched_approval["payload"]["rule_id"] = "rule/approval-fixture"
    enriched_approval["payload"]["expires_ms"] = 1800000060000
    signed_inbox = copy.deepcopy(user_inbox)
    signed_inbox["admission_proof"] = {
        "admission_key_id": "ledger/key-1",
        "admission_signature": "AAECAwQ=",
        "admission_signed_ms": 1800000000000,
    }
    signed_input = copy.deepcopy(op_completed)
    signed_input = copy.deepcopy(
        next(item for item in records if item["kind"] == "input_applied")
    )
    signed_input["payload"]["input"] = copy.deepcopy(user_inbox)
    signed_input["payload"]["input"]["admission_proof"] = copy.deepcopy(signed_inbox["admission_proof"])
    signed_input["record_id"] = (
        f"input/{signed_input['payload']['input']['input_id']}/applied"
    )
    signed_input["payload"]["input_proof"] = {
        "input_seq": 1,
        "received_ms": 1800000000001,
        "key_id": "ledger/key-1",
        "signature": "AAECAwQ=",
        "signed_ms": 1800000000000,
    }
    signed_input["payload"]["input_digest"] = sha256(signed_input["payload"]["input"])


    def accepted(name: str, wire: dict[str, Any]) -> dict[str, Any]:
        encoded, digest = vector_bytes(wire)
        return {
            "name": name,
            "bytes_base64": encoded,
            "canonical_json_base64": encoded,
            "canonical_json_utf8_bytes": len(base64.b64decode(encoded)),
            "sha256": digest,
            "wire": wire,
        }

    accepted_cases = {
        "session_created_principal_and_content_ref": accepted(
            "session_created_principal_and_content_ref", session_created
        ),
        "turn_started_requirements_policy_and_environment": accepted(
            "turn_started_requirements_policy_and_environment", enriched_turn
        ),
        "signed_user_inbox_admission_proof": accepted(
            "signed_user_inbox_admission_proof", signed_inbox
        ),
        "input_applied_copied_input_proof": accepted(
            "input_applied_copied_input_proof", signed_input
        ),
        "policy_usage_and_tokenizer_projection": accepted(
            "policy_usage_and_tokenizer_projection", enriched_completion
        ),
        "op_planned_policy_projection": accepted(
            "op_planned_policy_projection", enriched_plan
        ),
        "op_prepared_policy_projection": accepted(
            "op_prepared_policy_projection", enriched_preparation
        ),
        "approval_answer_policy_projection": accepted(
            "approval_answer_policy_projection", enriched_approval
        ),
        "provider_evidence_content_ref": accepted(
            "provider_evidence_content_ref", provider_evidence
        ),
        "boundary_event_content_ref": accepted(
            "boundary_event_content_ref", boundary
        ),
    }
    rejected = [
        ("legacy_record_discriminator", "session_created_principal_and_content_ref", [{"path": ["schema_version"], "set": 1}], "record schema_version must be S1"),
        ("legacy_inbox_discriminator", "signed_user_inbox_admission_proof", [{"path": ["schema_version"], "set": 3}], "inbox schema_version must be S1"),
        ("unsupported_feature_level", "session_created_principal_and_content_ref", [{"path": ["feature_level"], "set": 2}], "unknown feature levels reject"),
        ("logical_chain_digest_rejected", "session_created_principal_and_content_ref", [{"path": ["chain_digest"], "set": "0" * 64}], "chain fields belong to the storage envelope"),
        ("principal_unknown_field", "session_created_principal_and_content_ref", [{"path": ["payload", "principal", "extra"], "set": True}], "principal is closed"),
        ("invalid_subject_kind", "signed_user_inbox_admission_proof", [{"path": ["actor", "subject_kind"], "set": "system"}], "subject kinds are closed"),
        ("raw_workspace_text_rejected", "session_created_principal_and_content_ref", [{"path": ["payload", "workspace"], "set": "/plaintext"}], "workspace is a ContentRef"),
        ("raw_inbox_content_rejected", "signed_user_inbox_admission_proof", [{"path": ["payload", "content"], "set": "go"}], "inbox content is a ContentRef"),
        ("operational_policy_digests_are_encrypted", "turn_started_requirements_policy_and_environment", [{"path": ["payload", "environment", "operational_policy"], "set": {"network_policy_digest": "1" * 64, "isolation_policy_digest": "2" * 64}}], "operational_policy is a ContentRef"),
        ("tokenizer_binding_unknown_field", "turn_started_requirements_policy_and_environment", [{"path": ["payload", "tokenizer_binding", "extra"], "set": True}], "tokenizer binding is closed"),
        ("policy_decision_invalid_effect", "policy_usage_and_tokenizer_projection", [{"path": ["payload", "policy_decision", "effect"], "set": "maybe"}], "policy decision effects are closed"),
        ("usage_counts_unknown_field", "policy_usage_and_tokenizer_projection", [{"path": ["payload", "usage_counts", "extra"], "set": 1}], "usage projection is closed"),
        ("content_ref_unknown_field", "session_created_principal_and_content_ref", [{"path": ["payload", "workspace", "extra"], "set": True}], "ContentRef is closed"),
        ("content_label_source_unsorted", "turn_started_requirements_policy_and_environment", [{"path": ["payload", "environment", "descriptor", "labels", "source"], "set": ["untrusted", "user"]}], "ContentLabels.source is in source-kind order"),
        ("content_label_source_duplicate", "turn_started_requirements_policy_and_environment", [{"path": ["payload", "environment", "descriptor", "labels", "source"], "set": ["user", "user"]}], "ContentLabels.source is duplicate-free"),
        ("requirements_capabilities_unsorted", "turn_started_requirements_policy_and_environment", [{"path": ["payload", "requirements", "capabilities"], "set": ["z", "a"]}], "requirements capabilities are sorted"),
        ("requirements_capabilities_duplicate", "turn_started_requirements_policy_and_environment", [{"path": ["payload", "requirements", "capabilities"], "set": ["a", "a"]}], "requirements capabilities are duplicate-free"),
        ("admission_proof_partial", "signed_user_inbox_admission_proof", [{"path": ["admission_proof", "admission_signed_ms"], "delete": True}], "admission proof fields are all present"),
        ("admission_proof_unknown_field", "signed_user_inbox_admission_proof", [{"path": ["admission_proof", "extra"], "set": True}], "admission proof is closed"),
        ("admission_signature_noncanonical_base64", "signed_user_inbox_admission_proof", [{"path": ["admission_proof", "admission_signature"], "set": "AAECAwQ"}], "signature bytes use canonical base64"),
        ("raw_request_text_rejected", "op_planned_policy_projection", [{"path": ["payload", "request"], "set": {"model": "plaintext"}}], "request is a ContentRef"),
        ("raw_result_text_rejected", "policy_usage_and_tokenizer_projection", [{"path": ["payload", "result"], "set": {"content": "plaintext"}}], "result is a ContentRef"),
        ("raw_usage_text_rejected", "policy_usage_and_tokenizer_projection", [{"path": ["payload", "usage"], "set": {"prompt_tokens": 1}}], "usage is a ContentRef"),
        ("raw_approval_scope_rejected", "approval_answer_policy_projection", [{"path": ["payload", "scope"], "set": {"tool": "echo"}}], "approval scope is a ContentRef"),
        ("raw_provider_evidence_rejected", "provider_evidence_content_ref", [{"path": ["payload", "handle", "evidence"], "set": {"raw": True}}], "provider evidence is a ContentRef"),
        ("raw_boundary_event_rejected", "boundary_event_content_ref", [{"path": ["payload", "data", "event"], "set": {"raw": True}}], "boundary event is a ContentRef"),
    ]
    rejected_cases = [
        {
            "name": name,
            "base": base_name,
            "patch": patch,
            "reason": reason,
        }
        for name, base_name, patch, reason in rejected
    ]
    # Ensure the generated patches resolve against their selected base now,
    # rather than relying on the test to discover a broken path later.
    bases = {case["name"]: case["wire"] for case in accepted_cases.values()}
    for case in rejected_cases:
        patch_wire(bases[case["base"]], case["patch"])
    trusted = {
        "schema_version": "vv-agent.trusted-storage-s1.v1",
        "status": "contract-allocation-only",
        "storage_major": "S1",
        "feature_level": 1,
        "provenance": {
            "producer_capture": False,
            "note": "Synthetic allocation fixtures only; real Python S1 producer evidence remains pending.",
            "historical_capture": "fixtures/session_record_diagnostics.json",
        },
        "field_dispositions": {
            "session_record.envelope": {"schema_version": "const S1", "feature_level": "const 1", "closed": True},
            "session_inbox.envelope": {"schema_version": "const S1", "feature_level": "const 1", "actor": "Principal", "admission_proof": "closed|null", "closed": True},
            "session_created.payload.principal": {"shape": "{tenant_id,subject_id,subject_kind,attributes:ContentRef}", "closed": True},
            "session_created.payload.workspace": {"shape": "ContentRef", "closed": True},
            "session_created.payload.attributes": {"shape": "ContentRef", "closed": True},
            "turn_started.payload.definition": {"shape": "ContentRef", "closed": True},
            "turn_started.payload.budget": {"shape": "ContentRef", "closed": True},
            "turn_started.payload.policy_digest": {"shape": "H|null"},
            "turn_started.payload.requirements": {"shape": "{level,handler_version,capabilities}", "closed": True},
            "turn_started.payload.tokenizer_binding": {"shape": "closed|null"},
            "turn_started.payload.environment": {"shape": "closed|null", "operational_policy": "ContentRef|null"},
            "turn_started.payload.environment.operational_policy": {"shape": "ContentRef|null", "hydrated": "{network_policy_digest,isolation_policy_digest}", "closed": True},
            "input_applied.payload.input_proof": {"shape": "null|{input_seq,received_ms,key_id,signature,signed_ms}", "closed": True},
            "op_planned.payload.request_tool_budget_admission": {"shape": "ContentRef|ContentRef|null|ContentRef", "closed": True},
            "op_prepared.payload.request_tool_hook_shared_state": {"shape": "ContentRef|ContentRef|ContentRef|null|ContentRef", "closed": True},
            "op_completed.payload.result_usage_evidence": {"shape": "ContentRef", "closed": True},
            "op.policy_decision": {"shape": "null|{policy_digest,rule_id,effect}", "closed": True},
            "op_completed.payload.usage_counts": {"shape": "closed usage projection", "closed": True},
            "approval_answer.payload.scope_reason_metadata": {"shape": "ContentRef|ContentRef|null|ContentRef|null", "closed": True},
            "approval_answer.policy_projection": {"shape": "policy_digest:H|null,rule_id:T|null,expires_ms:N|null", "closed": True},
            "provider_handles.payload_fields": {"shape": "ContentRef|ContentRef|null", "closed": True},
            "boundary_recorded.payload.data": {"shape": "stage-specific ContentRef leaves", "closed": True},
            "session_storage_envelope": {"fixture": "fixtures/session_storage_envelope.json", "chain_excluded_from_record_identity": True},
            "session_storage_lifecycle": {"fixture": "fixtures/session_storage_lifecycle.json", "key_destroy_forget_export": True},
            "ContentRef": {"shape": "{content_id,mac,size,key_id,labels}", "closed": True},
            "ContentLabels": {"P2_default": "source=[] and classification=internal", "closed": True},
        },
        "accepted_cases": list(accepted_cases.values()),
        "rejected_cases": rejected_cases,
    }
    write_json(fixtures / "trusted_storage_s1.json", trusted)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--aux-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    fixtures = root / "fixtures"
    alloc = Allocator()
    alloc.load_catalog(fixtures / "session_content_catalog.json")
    referenced_content: set[str] = set()
    if not args.aux_only:
        for name in ACTIVE_JSON:
            path = fixtures / name
            transformed = transform_file(path, alloc)
            collect_content_refs(transformed, referenced_content)
            write_json(path, transformed)
        for name in ACTIVE_JSONL:
            values = transform_jsonl(fixtures / name, alloc)
            collect_content_refs(values, referenced_content)
            (fixtures / name).write_text(
                "\n".join(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) for value in values) + "\n",
                encoding="utf-8",
            )
        alloc.used = referenced_content
        write_json(fixtures / "session_content_catalog.json", alloc.catalog())
    write_auxiliary_fixtures(root, alloc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
