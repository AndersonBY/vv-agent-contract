# Prompt Bundles And Bounded Tool Results

Contract `4.0.2` defines one resolved prompt representation and one sparse
bounded-result extension. Both are task-neutral runtime capabilities. They do
not classify a task, choose an answer, decide completion, or change a model's
context/output limits.

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
`vv-agent.run-definition.v3`. Readers reject every other run-definition
version. `compiled_prompt`, metadata section side channels, and their readers
are not current shapes.

## Bounded Tool Results

An ordinary `ToolExecutionResult` remains the minimal result with required
`tool_call_id`, `content`, `status_code`, and `directive`. Optional fields are
omitted when absent. A truncated result additionally has:

- `truncated: true`;
- `truncation_reason` (`output_limit` or `read_limit`);
- `original_bytes` and `visible_bytes`;
- optional `artifact` and optional `cursor`.

There is no empty wrapper and no duplicated `preview` field: `content` is the
bounded model-visible preview. For a truncated result the tool-message
projection appends a compact canonical recovery record containing only the
present truncation fields. This makes an artifact or cursor visible to the
model without expanding ordinary results.

An `artifact` is a closed object with workspace-relative `path`, `media_type`,
`encoding`, `size_bytes`, and lowercase SHA-256 `sha256`. It is written through
the effective `WorkspaceBackend` below the reserved `.vv-agent/artifacts/`
root after the originating tool has passed its normal policy/approval boundary.
The model never selects the artifact path. Recovery uses the existing
policy-checked `read_file` tool; there is no artifact bypass API.

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
5. no model-visible `compress_memory`, no `memory_notes`, and no `deferred`
   exposure value while internal compaction remains covered.
