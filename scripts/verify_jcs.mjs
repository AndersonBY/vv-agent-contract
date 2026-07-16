#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const WRITE = process.argv.includes("--write");

function fail(message) {
  throw new Error(message);
}

function canonicalize(value) {
  if (value === null || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      fail("JCS does not allow non-finite numbers");
    }
    return JSON.stringify(value);
  }
  if (typeof value === "string") {
    for (let index = 0; index < value.length; index += 1) {
      const code = value.charCodeAt(index);
      if (code >= 0xd800 && code <= 0xdbff) {
        const next = value.charCodeAt(index + 1);
        if (!(next >= 0xdc00 && next <= 0xdfff)) {
          fail("JCS does not allow unpaired UTF-16 surrogates");
        }
        index += 1;
      } else if (code >= 0xdc00 && code <= 0xdfff) {
        fail("JCS does not allow unpaired UTF-16 surrogates");
      }
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalize).join(",")}]`;
  }
  if (typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${canonicalize(key)}:${canonicalize(value[key])}`)
      .join(",")}}`;
  }
  fail(`JCS does not allow ${typeof value}`);
}

function verifyVector(label, value, vector) {
  const actual = vectorValues(value);
  if (WRITE) {
    return;
  }
  for (const [field, observed] of Object.entries(actual)) {
    if (vector[field] !== observed) {
      fail(`${label}: ${field} mismatch: expected ${vector[field]}, observed ${observed}`);
    }
  }
}

function vectorValues(value) {
  const bytes = Buffer.from(canonicalize(value), "utf8");
  return {
    canonical_json_base64: bytes.toString("base64"),
    canonical_json_utf8_bytes: bytes.length,
    sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
  };
}

function readFixture(name) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, "fixtures", name), "utf8"));
}

function writeGeneratedFields(name, vectors, valueField) {
  const fixturePath = path.join(ROOT, "fixtures", name);
  let source = fs.readFileSync(fixturePath, "utf8");
  let cursor = 0;
  for (const vector of vectors) {
    const values = vectorValues(vector[valueField]);
    for (const [field, value] of Object.entries(values)) {
      const marker = `\"${field}\":`;
      const start = source.indexOf(marker, cursor);
      if (start < 0) {
        fail(`${name}: cannot locate generated field ${field}`);
      }
      const end = source.indexOf("\n", start);
      const oldLine = source.slice(start, end);
      const comma = oldLine.endsWith(",") ? "," : "";
      const newLine = `${marker} ${JSON.stringify(value)}${comma}`;
      source = `${source.slice(0, start)}${newLine}${source.slice(end)}`;
      cursor = start + newLine.length;
    }
  }
  fs.writeFileSync(fixturePath, source, "utf8");
}

const runDefinition = readFixture("run_definition_v1.json");
for (const vector of runDefinition.golden_cases) {
  verifyVector(`run_definition/${vector.name}`, vector.definition, vector);
}

const operationJournal = readFixture("operation_journal_v1.json");
for (const vector of operationJournal.request_digest.golden_cases) {
  verifyVector(`operation_request/${vector.name}`, vector.request, vector);
}

const checkpoint = readFixture("checkpoint_codec_v2.json");
for (const vector of checkpoint.extension_limits.canonicalization_vectors) {
  verifyVector(`checkpoint_extension/${vector.name}`, vector.entry, vector);
}
const checkpointPayloads = [
  ["canonical_checkpoint", checkpoint.canonical_checkpoint],
  ...checkpoint.valid_cases.map((entry) => [`valid_case/${entry.name}`, entry.payload]),
];
for (const [label, payload] of checkpointPayloads) {
  for (const entry of payload.event_outbox) {
    const actual = vectorValues(entry.event).sha256;
    if (actual !== entry.payload_digest) {
      fail(`${label}/${entry.event_id}: outbox payload digest mismatch`);
    }
  }
}

const checkpointStore = readFixture("checkpoint_store_v2.json");
for (const vector of checkpointStore.event_payload_digest.golden_cases) {
  verifyVector(`checkpoint_event/${vector.name}`, vector.event, vector);
}

const checkpointResume = readFixture("checkpoint_resume_v1.json");
verifyVector(
  "checkpoint_session_commit/golden_case",
  checkpointResume.session_persistence.golden_case.payload,
  checkpointResume.session_persistence.golden_case,
);

if (WRITE) {
  writeGeneratedFields("run_definition_v1.json", runDefinition.golden_cases, "definition");
  writeGeneratedFields(
    "operation_journal_v1.json",
    operationJournal.request_digest.golden_cases,
    "request",
  );
  writeGeneratedFields(
    "checkpoint_codec_v2.json",
    checkpoint.extension_limits.canonicalization_vectors,
    "entry",
  );
  writeGeneratedFields(
    "checkpoint_store_v2.json",
    checkpointStore.event_payload_digest.golden_cases,
    "event",
  );
  writeGeneratedFields(
    "checkpoint_resume_v1.json",
    [checkpointResume.session_persistence.golden_case],
    "payload",
  );
  console.log("RFC 8785 generated fields updated");
  process.exit(0);
}

console.log("RFC 8785 golden vectors verified");
