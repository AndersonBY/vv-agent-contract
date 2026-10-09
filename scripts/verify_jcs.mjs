#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(process.env.CONTRACT_ROOT ?? path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."));

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

function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}
function readFixture(name) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, "fixtures", name), "utf8"));
}
function decode(vector, label) {
  const bytes = Buffer.from(vector.bytes_base64, "base64");
  if (bytes.toString("base64") !== vector.bytes_base64 || sha256(bytes) !== vector.sha256) {
    fail(`${label}: invalid base64 or byte hash`);
  }
  return bytes;
}
function recordId(wire) {
  const p = wire.payload;
  switch (wire.kind) {
    case "session_created": return `session/${wire.session_id}/created`;
    case "turn_started": return `turn/${wire.turn_id}/started`;
    case "turn_ended": return `turn/${wire.turn_id}/ended`;
    case "turn_parked": return `turn/${wire.turn_id}/wait/${p.interaction_id}`;
    case "input_applied": return `input/${p.input.input_id}/applied`;
    case "boundary_recorded": return `turn/${wire.turn_id}/boundary/${p.stage}/${p.boundary_id}`;
    case "context_compacted": return `compact/${p.source_digest}/${p.mode}${p.summary_operation_id === null ? "" : `/${p.summary_operation_id}`}`;
    case "usage_observed": return `usage/${p.meter_id}/${p.observation}`;
    default: {
      const suffix = wire.kind === "op_completed" ? "result" : wire.kind.slice(3);
      return `op/${wire.operation_id}/${wire.attempt}/${suffix}${wire.kind === "op_parked" ? `/${p.phase}` : ""}`;
    }
  }
}
function nestedDigests(wire, label) {
  const p = wire.payload;
  const pairs = {
    turn_started: [[p.definition_digest, p.definition]],
    op_planned: [[p.request_digest, p.request]],
    op_prepared: [[p.request_digest, p.request]],
    op_completed: [[p.result_digest, p.result]],
    input_applied: [[p.input_digest, p.input]],
  }[wire.kind] ?? [];
  const child = p.attributes?.child_admission;
  if (child) pairs.push([child.definition_digest, child.definition]);
  for (const [expected, value] of pairs) {
    if (vectorValues(value).sha256 !== expected) fail(`${label}: nested digest mismatch`);
  }
}
function verifyFact(vector, label, value) {
  const bytes = decode(vector, label);
  if (!bytes.equals(Buffer.from(canonicalize(value), "utf8"))) fail(`${label}: canonical bytes mismatch`);
  if (value?.record_id !== undefined) {
    const id = recordId(value);
    if (value.record_id !== id || (vector.record_id !== undefined && vector.record_id !== id)) {
      fail(`${label}: record_id mismatch`);
    }
    nestedDigests(value, label);
  }
}
function walk(value, visit, label = "root") {
  visit(value, label);
  if (Array.isArray(value)) value.forEach((child, index) => walk(child, visit, `${label}[${index}]`));
  else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) walk(child, visit, `${label}.${key}`);
  }
}
function verifyFacts(fixture, name) {
  walk(fixture, (v, label) => {
    if (!v || typeof v !== "object" || !v.bytes_base64) return;
    const bytes = decode(v, `${name}/${label}`);
    if (label.endsWith(".artifact")) return;
    const decoded = JSON.parse(bytes.toString("utf8"));
    let value = v.wire ?? v.definition;
    if (value === undefined) {
      value = label.endsWith(".rejected_request") ? decoded : Object.fromEntries(Object.keys(decoded).map(key => [key, v[key]]));
    }
    verifyFact(v, `${name}/${label}`, value);
  });
}
function verifyPrompts() {
  const fixture = readFixture("prompt_bundle.json");
  const scenarios = new Map();
  for (const scenario of fixture.scenarios) {
    const sections = scenario.output.sections ?? [
      ...(scenario.input.instruction_bundle?.sections ?? []),
      ...(scenario.input.compiler_owned_sections ?? []),
      ...(scenario.input.provider_fragments ?? []).toSorted((a,b) =>
        (a.priority ?? 100) - (b.priority ?? 100) ||
        Number(a.stable === false) - Number(b.stable === false) ||
        (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)).map(({priority, ...section}) => section),
    ];
    scenarios.set(scenario.id, sections);
    if (scenario.output.flat_prompt !== sections.map(x => x.text).join("\n\n")) fail(`prompt/${scenario.id}: flat text`);
    if (scenario.output.stable_hash !== vectorValues(sections.filter(x => x.stable)).sha256) fail(`prompt/${scenario.id}: stable hash`);
    if (scenario.output.section_ids && canonicalize(scenario.output.section_ids) !== canonicalize(sections.map(x => x.id))) fail(`prompt/${scenario.id}: section order`);
  }
  for (const vector of fixture.stable_hash_vectors) {
    verifyVector(`prompt/${vector.scenario_ref}`, scenarios.get(vector.scenario_ref).filter(x => x.stable), vector);
  }
  for (const projection of fixture.provider_projection.projection_cases) {
    const sections = scenarios.get(projection.scenario_ref);
    let boundary = 0;
    while (boundary < sections.length && sections[boundary].stable) boundary++;
    boundary = boundary > 0 ? boundary - 1 : null;
    const expected = projection.mode === "flatten_only"
      ? {system_message: {role:"system", content:sections.map(x => x.text).join("\n\n")}, cache_control_fields:[]}
      : {system_blocks:sections.map((x,i) => ({type:"text",text:x.text + (i+1 < sections.length ? "\n\n" : ""), ...(i===boundary ? {cache_control:{type:"ephemeral"}} : {})})), cache_boundary_block_index:boundary};
    if (canonicalize(expected) !== canonicalize(projection.expected)) fail(`prompt/${projection.name}: provider projection`);
  }
  const definition = readFixture("run_definition.json");
  for (const vector of definition.golden_cases) {
    verifyFact(vector, `definition/${vector.name}`, vector.definition);
    if (vector.definition_digest !== vector.sha256) fail(`definition/${vector.name}: digest`);
  }
  walk(definition, value => {
    if (!value?.sections || !value.stable_hash) return;
    if (value.stable_hash !== vectorValues(value.sections.filter(x => x.stable)).sha256) fail("definition: prompt hash");
  });
}
function verifyToolResults() {
  const fixture = readFixture("bounded_tool_result.json");
  for (const result of Object.values(fixture.canonical_results)) {
    if (result.truncated && (Buffer.byteLength(result.content, "utf8") !== result.visible_bytes || result.visible_bytes > result.original_bytes)) fail("tool result: preview bytes");
    if (result.artifact && !new RegExp(fixture.artifact_contract.path.pattern).test(result.artifact.path)) fail("tool result: artifact path");
  }
  if (fixture.bash_contract.head_chars + Array.from(fixture.bash_contract.omission_marker).length + fixture.bash_contract.tail_chars !== fixture.bash_contract.preview_limit_chars) fail("tool result: preview allocation");
  for (const projection of fixture.tool_message_projection.cases) {
    const result = fixture.canonical_results[projection.result_ref];
    const recovery = Object.fromEntries(fixture.tool_message_projection.recovery_fields.filter(key => key in result).map(key => [key, result[key]]));
    const expected = result.truncated ? `${result.content}\n${canonicalize({vv_agent_recovery:recovery})}` : result.content;
    if (projection.expected_message !== expected) fail(`tool result/${projection.name}: recovery projection`);
  }
}
if (process.argv.includes("--write")) fail("Producer fixtures are immutable here; regenerate them at source");
if (process.argv.includes("--canonicalize")) {
  let source = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) source += chunk;
  const values = JSON.parse(source);
  process.stdout.write(JSON.stringify(values.map(value => Buffer.from(canonicalize(value), "utf8").toString("base64"))));
} else {
  const codec = readFixture("session_codec_vectors.json");
  for (const [index, vector] of codec.vectors.entries()) verifyFact(vector, `codec/${index}`, vector.wire);
  for (const [index, vector] of readFixture("session_invalid.json").vectors.entries()) decode(vector, `invalid/${index}`);
  for (const name of ["session_semantics.json", "session_recovery.json", "session_projection.json", "session_compaction.json", "app_server_protocol.json"]) verifyFacts(readFixture(name), name);
  for (const vector of readFixture("app_server_observable.json").actionAdmission.commandIdCases) {
    const value = {schema_version:"vv-agent.controller-command-id.v1", thread_id:vector.threadId, turn_id:vector.turnId, action_id:vector.actionId};
    verifyFact(vector, `action/${vector.name}`, value);
    const bytes = Buffer.from(canonicalize(value), "utf8");
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(bytes.length));
    const actual = sha256(Buffer.concat([Buffer.from(value.schema_version), Buffer.from([0]), length, bytes]));
    if (vector.expectedCommandId !== actual) fail(`action/${vector.name}: action identity`);
  }
  const app = readFixture("app_server_protocol.json");
  const reply = app.transcripts.find(x => x.request?.method === "turn/action");
  const params = reply.request.params;
  const value = {schema_version:"vv-agent.controller-command-id.v1", thread_id:params.threadId, turn_id:params.turnId, action_id:params.actionId};
  const bytes = Buffer.from(canonicalize(value), "utf8");
  const length = Buffer.alloc(8); length.writeBigUInt64BE(BigInt(bytes.length));
  if (sha256(Buffer.concat([Buffer.from(value.schema_version), Buffer.from([0]), length, bytes])) !== app.facts.child_reply_command_id) fail("app: child reply identity");
  verifyPrompts();
  verifyToolResults();
  process.stdout.write(`JCS verified: ${codec.vectors.length} session vectors, invalid byte hashes, nested digests, action identities, projections and prompts\n`);
}
