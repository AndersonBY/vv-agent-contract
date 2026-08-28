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

function syncCheckpointRunDefinition(runDefinition) {
  const fixturePath = path.join(ROOT, "fixtures", "checkpoint_codec.json");
  const checkpoint = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
  const minimal = runDefinition.golden_cases.find((entry) => entry.name === "minimal");
  if (!minimal) {
    fail("run_definition.json: missing minimal golden case");
  }

  const previousSchema = checkpoint.canonical_checkpoint.run_definition_schema;
  if (typeof previousSchema !== "string") {
    fail("checkpoint_codec.json: previous run definition schema is not a string");
  }
  const payloads = [
    checkpoint.canonical_checkpoint,
    ...checkpoint.valid_cases.map((entry) => entry.payload),
    ...checkpoint.invalid_cases.map((entry) => entry.payload),
  ].filter(
    (payload) =>
      payload?.run_definition_schema === previousSchema &&
      payload.run_definition,
  );
  const previousDefinition = checkpoint.canonical_checkpoint.run_definition;
  const previousCanonical = canonicalize(previousDefinition);
  for (const payload of payloads) {
    if (canonicalize(payload.run_definition) !== previousCanonical) {
      fail("checkpoint_codec.json: embedded current run definitions have drifted");
    }
  }

  const previousDigest = checkpoint.canonical_checkpoint.run_definition_digest;
  if (typeof previousDigest !== "string") {
    fail("checkpoint_codec.json: previous minimal definition digest is not a string");
  }
  const nextDigest = vectorValues(minimal.definition).sha256;
  for (const payload of payloads) {
    payload.run_definition_schema = runDefinition.schema_version;
    payload.run_definition = structuredClone(minimal.definition);
  }

  function replaceDigest(value) {
    if (Array.isArray(value)) {
      for (let index = 0; index < value.length; index += 1) {
        value[index] = replaceDigest(value[index]);
      }
      return value;
    }
    if (value && typeof value === "object") {
      for (const [key, item] of Object.entries(value)) {
        value[key] = replaceDigest(item);
      }
      return value;
    }
    return value === previousDigest ? nextDigest : value;
  }
  replaceDigest(checkpoint);
  fs.writeFileSync(fixturePath, `${JSON.stringify(checkpoint, null, 2)}\n`, "utf8");
}

function promptScenarioSections(scenario) {
  return scenario.output?.sections ?? [
      ...(scenario.input?.instruction_bundle?.sections ?? []),
      ...(scenario.input?.compiler_owned_sections ?? []),
      ...[...(scenario.input?.provider_fragments ?? [])]
        .sort((left, right) =>
          (left.priority ?? 100) - (right.priority ?? 100) ||
          Number(left.stable === false) - Number(right.stable === false) ||
          (left.id < right.id ? -1 : left.id > right.id ? 1 : 0),
        )
        .map(({ priority: _priority, ...section }) => section),
    ];
}

function writePromptBundleHashes(promptBundle) {
  const fixturePath = path.join(ROOT, "fixtures", "prompt_bundle.json");
  const scenarios = new Map(promptBundle.scenarios.map((scenario) => [scenario.id, scenario]));
  for (const scenario of promptBundle.scenarios) {
    const sections = promptScenarioSections(scenario);
    const sectionIds = sections.map((section) => section.id);
    const flatPrompt = sections.map((section) => section.text).join("\n\n");
    if (scenario.output.section_ids && canonicalize(scenario.output.section_ids) !== canonicalize(sectionIds)) {
      fail(`prompt_bundle/${scenario.id}: section_ids mismatch`);
    }
    if (scenario.output.flat_prompt !== flatPrompt) {
      fail(`prompt_bundle/${scenario.id}: flat_prompt mismatch`);
    }
    const stableSections = sections.filter((section) => section.stable);
    const hash = vectorValues(stableSections).sha256;
    if (WRITE) {
      scenario.output.stable_hash = hash;
    } else if (scenario.output.stable_hash !== hash) {
      fail(`prompt_bundle/${scenario.id}: stable_hash mismatch`);
    }
  }

  for (const vector of promptBundle.stable_hash_vectors) {
    const scenario = scenarios.get(vector.scenario_ref);
    if (!scenario) {
      fail(`prompt_bundle: unknown stable-hash scenario ${vector.scenario_ref}`);
    }
    const stableSections = promptScenarioSections(scenario).filter((section) => section.stable);
    const values = vectorValues(stableSections);
    for (const [field, value] of Object.entries(values)) {
      if (WRITE) {
        vector[field] = value;
      } else if (vector[field] !== value) {
        fail(`prompt_bundle/${vector.scenario_ref}: ${field} mismatch`);
      }
    }
  }

  for (const projection of promptBundle.provider_projection.projection_cases) {
    const scenario = scenarios.get(projection.scenario_ref);
    if (!scenario) {
      fail(`prompt_bundle: unknown projection scenario ${projection.scenario_ref}`);
    }
    const sections = promptScenarioSections(scenario);
    const flatPrompt = sections.map((section) => section.text).join("\n\n");
    let expected;
    if (projection.mode === "flatten_only") {
      expected = {
        system_message: { role: "system", content: flatPrompt },
        cache_control_fields: [],
      };
    } else if (projection.mode === "explicit_section_cache") {
      let leadingStableCount = 0;
      while (leadingStableCount < sections.length && sections[leadingStableCount].stable) {
        leadingStableCount += 1;
      }
      const boundary = leadingStableCount > 0 ? leadingStableCount - 1 : null;
      expected = {
        system_blocks: sections.map((section, index) => ({
          type: "text",
          text: `${section.text}${index + 1 < sections.length ? "\n\n" : ""}`,
          ...(index === boundary ? { cache_control: { type: "ephemeral" } } : {}),
        })),
        cache_boundary_block_index: boundary,
      };
    } else {
      fail(`prompt_bundle/${projection.name}: unknown projection mode ${projection.mode}`);
    }
    if (WRITE) {
      projection.expected = expected;
    } else if (canonicalize(projection.expected) !== canonicalize(expected)) {
      fail(`prompt_bundle/${projection.name}: provider projection mismatch`);
    }
  }
  if (WRITE) {
    fs.writeFileSync(fixturePath, `${JSON.stringify(promptBundle, null, 2)}\n`, "utf8");
  }
}

function writeRunDefinitionPromptBundleHashes(runDefinition) {
  for (const vector of runDefinition.golden_cases) {
    const bundle = vector.definition?.prompt_bundle;
    if (!bundle || !Array.isArray(bundle.sections) || bundle.sections.length === 0) {
      fail(`run_definition/${vector.name}: missing non-empty prompt bundle`);
    }
    const hash = vectorValues(
      bundle.sections.filter((section) => section.stable === true),
    ).sha256;
    if (WRITE) {
      bundle.stable_hash = hash;
    } else if (bundle.stable_hash !== hash) {
      fail(`run_definition/${vector.name}: prompt bundle stable_hash mismatch`);
    }
  }
  if (WRITE) {
    fs.writeFileSync(
      path.join(ROOT, "fixtures", "run_definition.json"),
      `${JSON.stringify(runDefinition, null, 2)}\n`,
      "utf8",
    );
  }
}

function writeBoundedToolResultProjections(fixture) {
  const fixturePath = path.join(ROOT, "fixtures", "bounded_tool_result.json");
  const recoveryFields = fixture.tool_message_projection.recovery_fields;
  for (const [name, result] of Object.entries(fixture.canonical_results)) {
    if (result.truncated === true) {
      if (Buffer.byteLength(result.content, "utf8") !== result.visible_bytes) {
        fail(`bounded_tool_result/${name}: visible_bytes mismatch`);
      }
      if (result.visible_bytes > result.original_bytes) {
        fail(`bounded_tool_result/${name}: visible_bytes exceeds original_bytes`);
      }
    }
  }
  const artifactPattern = new RegExp(fixture.artifact_contract.path.pattern);
  for (const [name, result] of Object.entries(fixture.canonical_results)) {
    if (result.artifact && !artifactPattern.test(result.artifact.path)) {
      fail(`bounded_tool_result/${name}: unsafe canonical artifact path`);
    }
  }
  const markerChars = Array.from(fixture.bash_contract.omission_marker).length;
  if (
    fixture.bash_contract.head_chars +
      markerChars +
      fixture.bash_contract.tail_chars !==
    fixture.bash_contract.preview_limit_chars
  ) {
    fail("bounded_tool_result: bash preview allocation does not equal limit");
  }
  for (const projection of fixture.tool_message_projection.cases) {
    const result = fixture.canonical_results[projection.result_ref];
    if (!result) {
      fail(`bounded_tool_result/${projection.name}: unknown result ref`);
    }
    const recovery = Object.fromEntries(
      recoveryFields.filter((field) => field in result).map((field) => [field, result[field]]),
    );
    const expected = result.truncated === true
      ? `${result.content}\n${canonicalize({ vv_agent_recovery: recovery })}`
      : result.content;
    if (WRITE) {
      projection.expected_message = expected;
    } else if (projection.expected_message !== expected) {
      fail(`bounded_tool_result/${projection.name}: tool-message projection mismatch`);
    }
  }
  if (WRITE) {
    fs.writeFileSync(fixturePath, `${JSON.stringify(fixture, null, 2)}\n`, "utf8");
  }
}

const runDefinition = readFixture("run_definition.json");
writeRunDefinitionPromptBundleHashes(runDefinition);
for (const vector of runDefinition.golden_cases) {
  verifyVector(`run_definition/${vector.name}`, vector.definition, vector);
}

const promptBundle = readFixture("prompt_bundle.json");
writePromptBundleHashes(promptBundle);

const distributedRun = readFixture("distributed_run_envelope.json");
const distributedPromptBundle = distributedRun.canonical_envelope?.task?.prompt_bundle;
if (!distributedPromptBundle || !Array.isArray(distributedPromptBundle.sections) || distributedPromptBundle.sections.length === 0) {
  fail("distributed_run_envelope: task is missing a non-empty prompt bundle");
}
const distributedStableHash = vectorValues(
  distributedPromptBundle.sections.filter((section) => section.stable === true),
).sha256;
if (WRITE) {
  const fixturePath = path.join(ROOT, "fixtures", "distributed_run_envelope.json");
  let source = fs.readFileSync(fixturePath, "utf8");
  const taskStart = source.indexOf('"task": {');
  const hashStart = source.indexOf('"stable_hash":', taskStart);
  if (taskStart < 0 || hashStart < 0) {
    fail("distributed_run_envelope: cannot locate task prompt bundle stable_hash");
  }
  const hashEnd = source.indexOf("\n", hashStart);
  const oldLine = source.slice(hashStart, hashEnd);
  const comma = oldLine.endsWith(",") ? "," : "";
  const nextLine = `"stable_hash": ${JSON.stringify(distributedStableHash)}${comma}`;
  source = `${source.slice(0, hashStart)}${nextLine}${source.slice(hashEnd)}`;
  fs.writeFileSync(fixturePath, source, "utf8");
} else if (distributedPromptBundle.stable_hash !== distributedStableHash) {
  fail("distributed_run_envelope: task prompt bundle stable_hash mismatch");
}

const boundedToolResult = readFixture("bounded_tool_result.json");
writeBoundedToolResultProjections(boundedToolResult);

if (WRITE) {
  syncCheckpointRunDefinition(runDefinition);
}

const operationJournal = readFixture("operation_journal.json");
const operationRequestVectors = new Map();
for (const vector of operationJournal.request_digest.golden_cases) {
  const values = vectorValues(vector.request);
  operationRequestVectors.set(vector.name, values);
  if (WRITE) {
    Object.assign(vector, values);
  } else {
    verifyVector(`operation_request/${vector.name}`, vector.request, vector);
  }
}
for (const entryCase of operationJournal.valid_entries) {
  const vector = operationRequestVectors.get(entryCase.request_golden_case);
  if (!vector) {
    fail(`operation_journal/${entryCase.name}: unknown request golden case`);
  }
  if (WRITE) {
    entryCase.entry.request_digest = vector.sha256;
  } else if (entryCase.entry.request_digest !== vector.sha256) {
    fail(`operation_journal/${entryCase.name}: request_digest mismatch`);
  }
}
if (WRITE) {
  fs.writeFileSync(
    path.join(ROOT, "fixtures", "operation_journal.json"),
    `${JSON.stringify(operationJournal, null, 2)}\n`,
    "utf8",
  );
}

const checkpoint = readFixture("checkpoint_codec.json");
for (const vector of checkpoint.extension_limits.canonicalization_vectors) {
  verifyVector(`checkpoint_extension/${vector.name}`, vector.entry, vector);
}
const checkpointPayloads = [
  ["canonical_checkpoint", checkpoint.canonical_checkpoint],
  ...checkpoint.valid_cases.map((entry) => [`valid_case/${entry.name}`, entry.payload]),
];
let checkpointOutboxChanged = false;
for (const [label, payload] of checkpointPayloads) {
  for (const entry of payload.event_outbox) {
    const actual = vectorValues(entry.event).sha256;
    if (actual !== entry.payload_digest) {
      if (!WRITE) {
        fail(`${label}/${entry.event_id}: outbox payload digest mismatch`);
      }
      entry.payload_digest = actual;
      checkpointOutboxChanged = true;
    }
  }
}
if (checkpointOutboxChanged) {
  fs.writeFileSync(
    path.join(ROOT, "fixtures", "checkpoint_codec.json"),
    `${JSON.stringify(checkpoint, null, 2)}\n`,
    "utf8",
  );
}

const checkpointStore = readFixture("checkpoint_store.json");
for (const vector of checkpointStore.event_payload_digest.golden_cases) {
  verifyVector(`checkpoint_event/${vector.name}`, vector.event, vector);
}

const deferredTool = readFixture("deferred_tool.json");
const deferredDigestVectors = deferredTool.resolution?.receipt_index?.golden_digest_vectors;
if (!Array.isArray(deferredDigestVectors) || deferredDigestVectors.length === 0) {
  fail("deferred_tool.json: missing receipt golden digest vectors");
}
for (const vector of deferredDigestVectors) {
  const actual = vectorValues(vector.value);
  if (WRITE) {
    vector.rfc8785_sha256 = actual.sha256;
  } else if (vector.rfc8785_sha256 !== actual.sha256) {
    fail(`deferred_tool/${vector.name}: receipt digest mismatch`);
  }
}
const requestProvenance = deferredTool.handle?.request_digest_provenance;
if (!requestProvenance || requestProvenance.source_fixture !== "operation_journal.json#request_digest.golden_cases") {
  fail("deferred_tool: missing operation-request digest provenance");
}
const provenanceByOperation = new Map();
for (const provenance of requestProvenance.cases ?? []) {
  const source = operationRequestVectors.get(provenance.request_golden_case);
  if (!source) {
    fail(`deferred_tool/${provenance.operation_id}: unknown request golden case`);
  }
  if (WRITE) {
    provenance.request_digest = source.sha256;
  } else if (provenance.request_digest !== source.sha256) {
    fail(`deferred_tool/${provenance.operation_id}: request digest provenance mismatch`);
  }
  provenanceByOperation.set(provenance.operation_id, provenance);
}
function verifyDeferredHandleProvenance(value) {
  if (Array.isArray(value)) {
    for (const item of value) verifyDeferredHandleProvenance(item);
    return;
  }
  if (!value || typeof value !== "object") return;
  if (value.schema_version === "vv-agent.deferred-tool-handle.v2" && value.operation_id) {
    const provenance = provenanceByOperation.get(value.operation_id);
    if (!provenance) {
      fail(`deferred_tool/${value.operation_id}: missing request digest provenance`);
    }
    if (value.request_digest !== provenance.request_digest) {
      fail(`deferred_tool/${value.operation_id}: handle request digest mismatch`);
    }
  }
  for (const item of Object.values(value)) verifyDeferredHandleProvenance(item);
}
verifyDeferredHandleProvenance(deferredTool);
if (WRITE) {
  fs.writeFileSync(
    path.join(ROOT, "fixtures", "deferred_tool.json"),
    `${JSON.stringify(deferredTool, null, 2)}\n`,
    "utf8",
  );
}

const controllerCommand = readFixture("controller_command.json");
const producerDigest = controllerCommand.host_interaction_producer?.request_wire?.request_digest?.golden;
if (!producerDigest) {
  fail("controller_command: missing host interaction producer digest vector");
}
if (WRITE) {
  Object.assign(producerDigest, vectorValues(producerDigest.request_without_digest));
} else {
  verifyVector(
    "controller_command/host_interaction_producer/request_digest",
    producerDigest.request_without_digest,
    producerDigest,
  );
}
for (const vector of controllerCommand.jcs_vectors ?? []) {
  if (WRITE) {
    Object.assign(vector, vectorValues(vector.value));
  } else {
    verifyVector(`controller_command/jcs/${vector.name}`, vector.value, vector);
  }
}
for (const vector of controllerCommand.digest_vectors ?? []) {
  const digestInput = vector.command_digest_input ?? vector.response_digest_input;
  const actual = vectorValues(digestInput);
  if (WRITE) {
    Object.assign(vector, actual);
  } else {
    if (vector.sha256 !== actual.sha256) {
      fail(`controller_command/${vector.name}: digest mismatch`);
    }
    if (vector.canonical_json_utf8_bytes !== actual.canonical_json_utf8_bytes) {
      fail(`controller_command/${vector.name}: byte length mismatch`);
    }
  }
}
if (WRITE) {
  fs.writeFileSync(
    path.join(ROOT, "fixtures", "controller_command.json"),
    `${JSON.stringify(controllerCommand, null, 2)}\n`,
    "utf8",
  );
}

const checkpointResume = readFixture("checkpoint_resume.json");
const frozenPromptResume = checkpointResume.runner_cases.find(
  (entry) => entry.name === "frozen_prompt_bundle_resume_does_not_reinvoke_producers",
);
if (!frozenPromptResume) {
  fail("checkpoint_resume.json: missing frozen prompt bundle resume case");
}
const frozenPromptBundle = frozenPromptResume.run?.frozen_prompt_bundle;
if (!frozenPromptBundle || !Array.isArray(frozenPromptBundle.sections)) {
  fail("checkpoint_resume.json: frozen prompt bundle resume case is malformed");
}
const frozenStableHash = vectorValues(
  frozenPromptBundle.sections.filter((section) => section.stable === true),
).sha256;
if (WRITE) {
  frozenPromptBundle.stable_hash = frozenStableHash;
  fs.writeFileSync(
    path.join(ROOT, "fixtures", "checkpoint_resume.json"),
    `${JSON.stringify(checkpointResume, null, 2)}\n`,
    "utf8",
  );
} else if (frozenPromptBundle.stable_hash !== frozenStableHash) {
  fail("checkpoint_resume/frozen_prompt_bundle: stable_hash mismatch");
}
verifyVector(
  "checkpoint_session_commit/golden_case",
  checkpointResume.session_persistence.golden_case.payload,
  checkpointResume.session_persistence.golden_case,
);

if (WRITE) {
  writeGeneratedFields("run_definition.json", runDefinition.golden_cases, "definition");
  writeGeneratedFields(
    "checkpoint_codec.json",
    checkpoint.extension_limits.canonicalization_vectors,
    "entry",
  );
  writeGeneratedFields(
    "checkpoint_store.json",
    checkpointStore.event_payload_digest.golden_cases,
    "event",
  );
  writeGeneratedFields(
    "checkpoint_resume.json",
    [checkpointResume.session_persistence.golden_case],
    "payload",
  );
  console.log("RFC 8785 generated fields updated");
  process.exit(0);
}

console.log("RFC 8785 golden vectors verified");
