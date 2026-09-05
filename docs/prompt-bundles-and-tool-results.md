# Prompt Bundles And Bounded Tool Results

Contract `9.0.0` defines one resolved prompt representation, one sparse
bounded-result extension, and the current artifact-backed Message and
microcompaction behavior. These are task-neutral runtime capabilities. They do
not classify a task, choose an answer, decide completion, or change a model's
context/output limits. `.vv-agent/artifacts/` remains a logical,
workspace-relative recovery namespace, and the only model-facing recovery path
is the policy-checked `read_file` tool through the effective
`WorkspaceBackend`.

## Prompt Bundle

A `PromptBundle` is the only structured system-prompt value after instruction
resolution. It contains an ordered, non-empty `sections` array and a
`stable_hash`. Each `PromptSection` is closed and has:

- required `id`, `text`, and boolean `stable`;
- optional non-empty `source`, optional `cache_hint`, and optional object
  `metadata`;
- no empty section text, duplicate section ids, unknown fields, or synthetic
  metadata aliases.

The model-visible flat prompt is derived, never independently persisted: join
section text in array order with exactly `\n\n`. `stable=false` means that the
resolved text is not part of a stable request prefix. It does **not** mean that
a producer is executed per cycle. Instruction callbacks and context providers
are evaluated once while compiling a new run; the resulting immutable bundle is
used by every cycle of that run.

`stable_hash` is the lowercase SHA-256 digest of the RFC 8785 UTF-8 bytes of
the ordered array of stable section objects after omitting absent optional
fields. It is a diagnostic/cache-affinity key, not a provider cache directive.

An `Agent` instruction may resolve to a string or a `PromptBundle`. A string is
normalized to exactly one stable `agent_instructions` section. The compiler
keeps supplied bundle sections in their original order, then appends its own
and provider fragments by the ordering rule in `prompt_bundle.json`. It must
not flatten a bundle and recreate a synthetic `agent_instructions` section.

`AgentTask` and `LlmRequest` carry the bundle as an explicit field. The old
`system_prompt_sections` metadata transport is not a current protocol. Generic
metadata remains host data and cannot alter prompt structure.

## Provider Projection

The runtime records the complete bundle until the provider boundary.

- A provider with explicit system-section cache controls projects ordered text
  blocks and may place breakpoints only according to the canonical stable
  boundary rule.
- A provider without that capability receives one deterministic flattened
  system message. It does not receive invented cache-control fields.

Both projections contain identical concatenated system text. Source, metadata,
and local cache diagnostics are not sent as provider-specific control fields
unless that provider capability explicitly consumes them.

## Run Scope And Resume

Time and every other volatile section are resolved once when a new run is
compiled. They may differ between separately started runs. The run definition
stores `prompt_bundle`, not a second flattened prompt string. Checkpoint,
distributed execution, and resume reconstruct the task from that frozen bundle
and must neither invoke instruction/context producers nor read the clock again.

The current durable definition discriminator is
`vv-agent.run-definition.v5`. Readers reject every other run-definition
version. `compiled_prompt`, metadata section side channels, and their readers
are not current shapes.

## Bounded Tool Results

The current `vv-agent.tool-execution-result.v4` `ToolExecutionResult` remains
the minimal result with required
`tool_call_id`, `content`, `status_code`, and `directive`. Optional fields are
omitted when absent. A truncated result additionally has:

`status_code` accepts only the current completed-result values. Deferred is a
closed `ToolCallOutcome.Deferred(DeferredToolHandle)` variant and never a
`ToolExecutionResult` status; a completed result carrying deferred is rejected.

- `truncated: true`;
- `truncation_reason` (`output_limit` or `read_limit`);
- `original_bytes` and `visible_bytes`;
- optional `artifact` and optional `cursor`.

There is no empty wrapper and no duplicated `preview` field: `content` is the
bounded model-visible preview. For a truncated result the tool-message
projection appends a compact canonical recovery record containing only the
present truncation fields. This makes an artifact or cursor visible to the
model without expanding ordinary results.

An `artifact` is a closed object with a logical workspace-relative `path`,
`media_type`, `encoding`, `size_bytes`, and lowercase SHA-256 `sha256`. It is
written through the effective `WorkspaceBackend` below the reserved logical
`.vv-agent/artifacts/` root after the originating tool has passed its normal
policy/approval boundary. For a local adapter, that logical namespace maps to
private storage outside the agent shell's working directory; shell commands
cannot read, replace, delete, or mutate those bytes through a host path. The
model never selects the artifact path. Recovery uses the existing
policy-checked `read_file` tool, which resolves the logical path through the
backend; there is no artifact bypass API.

The canonical host `Message` may carry the same object as optional
`artifact_ref: ToolArtifactRef`. The field is omitted when absent and survives
session, result, checkpoint, run-definition, journal, and distributed
round-trips. It is host-only: every provider/model message projection removes
`artifact_ref` without changing `content`.

For terminal output, `WorkspaceBackend.write_text_chunks_exclusive` is the
current producer boundary. It consumes normalized UTF-8 text chunks, performs
an atomic exclusive write, and returns the written UTF-8 byte count. A terminal
producer first derives its bounded preview, then streams the complete capture
through this boundary only when truncation occurred; it does not materialize
the complete terminal output in application memory. Local adapters map the
logical artifact path to private storage, while other backends provide the same
exclusive streaming semantics in their own storage domain.

A `cursor` is a closed object with `kind`, `offset_chars`, and source
`sha256`. `read_file` accepts the same cursor together with its required path,
verifies the digest before reading, and returns the next bounded slice. The
offset unit is Unicode scalar values. A changed source fails with the stable
`stale_cursor` error rather than returning a mixed-version slice.

`bash` preserves the complete terminal output as an artifact when it exceeds
the 12,000-character preview limit. The preview is deterministic head/tail
text, not a first-only slice. `read_file` returns a bounded slice plus cursor
instead of `content: null`; a single oversized line is therefore recoverable.
All sparse result fields survive tool messages, cycle records, AgentResult,
operation journals, checkpoints, distributed responses, and strict readers.

## Archive-Backed Microcompaction

Proactive microcompaction operates on old tool-result messages without
inspecting the task or parsing the result body. Every built-in and custom tool
uses the same default `result_retention=archive`; a tool may explicitly declare
`preserve` when its result must remain inline until full or emergency
compaction.

`MicrocompactionPolicy` is a public, closed value with
`trigger_ratio`, `target_ratio`, `keep_recent_cycles`, and
`min_result_chars`. It is configured through `RunConfig`, copied explicitly to
`AgentTask`, and frozen as `runtime_controls.microcompaction_policy` in the
current run definition. Generic metadata is not a policy transport. The default
policy is `0.75`, `0.60`, `3`, and `500`; `0 < target_ratio < trigger_ratio <=
1`. Ratios must be finite numbers. `keep_recent_cycles` is an integer in
`0..4294967295`, while `min_result_chars` is an integer in
`1..4294967295`. Booleans, null, float-encoded integers, missing or unknown
fields, non-finite host values, and out-of-range values are invalid.

Microcompaction is planned before it mutates messages. For a
`micro_threshold` trigger, it starts only when effective prompt usage crosses
the configured trigger and at least one old result passes the age,
minimum-size, and retention controls. The planner processes oldest candidates
as one ordered eligibility pool. Planner estimates select work but never
satisfy the target. After each successful replacement, the application pass
subtracts the actual replacement-message token count from the actual original
message token count, recalculates post-replacement usage, and stops only when
that usage is at or below the configured target or eligible candidates are
exhausted. Keeping later eligible candidates in the same plan lets persistence
failure fall through to another candidate without planning twice. A cycle
performs one planning/application pass. A
micro-threshold crossing with no eligible candidate does not emit
`memory_compact_started` or `memory_compact_completed`; full-threshold and
prompt-too-long compaction may still start without a micro candidate.

Before replacement, complete result text is persisted through the effective
`WorkspaceBackend` under the immutable logical `.vv-agent/artifacts/`
namespace. Persistence failure leaves the original message unchanged and does
not prevent later selected candidates from being attempted.
Already-truncated results reuse their existing artifact when one is available.
Reuse first reads the persisted content through the effective workspace
backend and verifies its UTF-8 byte length against `size_bytes` and lowercase
SHA-256 against `sha256`. A read, size, or hash mismatch leaves the original
message unchanged, as does a new persistence failure. The replacement is
intentionally small and model-visible:

```text
<Tool Result Compact>
tool_name: web_search
artifact_path: .vv-agent/artifacts/run/call.txt
retrieval_hint: use read_file on artifact_path if needed
excerpt:
...
</Tool Result Compact>
```

The marker must not expose byte counts, character counts, hashes, storage
metadata, or other bookkeeping. Integrity metadata remains on the typed
artifact reference outside the model projection. `read_file` is the only
model-facing recovery path.

## Tool Surface

Only `direct` and `hidden` are current `ToolExposure` values. `direct` is
eligible for the model-visible schema subject to normal policy; `hidden` is
not model-visible but may be invoked by trusted host/runtime code. The former
`deferred` value had no discovery or execution semantics and is removed rather
than being represented as a misleading capability.

The model-visible `compress_memory` tool and its `memory_notes` state are also
removed. Framework-owned proactive, micro, summary, and recovery compaction
remain internal behavior and do not expose a replacement model tool.

## Required Producer Evidence

Both implementations must prove real producer paths for:

1. bundle order, stable hash, flattening, and explicit provider projection;
2. one run's fixed time, a new run's independently resolved time, and unchanged
   time after checkpoint resume;
3. strict rejection of stale prompt/run-definition wires and no metadata
   section side channel;
4. bounded foreground/background bash recovery, read-file cursor recovery,
   stale-cursor rejection, and checkpoint/distributed serialization;
5. candidate-aware archive-backed microcompaction for built-in and custom
   tools, `preserve` retention, persistence and artifact-integrity failure
   safety, actual-token target application, compact marker shape, and one pass
   per cycle;
6. no model-visible `compress_memory`, no `memory_notes`, and no `deferred`
   exposure value while internal compaction remains covered.
