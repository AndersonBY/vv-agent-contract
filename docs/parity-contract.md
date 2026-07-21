# Python/Rust Parity Contract

`vv-agent` and `vv-agent-rs` implement one current Agent SDK contract in two
languages. API spelling may follow language idioms; prompt, tool, state, event,
persistence, App Server, and wire semantics may not drift.

## Completion Definition

A domain is aligned only when all of the following are true:

1. The public capability exists in both implementations.
2. Accepted input, defaults, precedence, output, errors, side effects,
   cancellation, persistence, and terminal states are equivalent.
3. Model-visible prompt and tool content match after canonical JSON encoding.
4. Current wire objects are closed and require their exact discriminator.
5. Real producer tests pass in both languages; private builder tests are not
   sufficient by themselves.
6. Both locks select the same central revision and both vendored snapshots
   match its artifact.
7. Focused tests and both full repository quality gates pass.

`HEAD` contains one current shape. Missing, stale, unknown, malformed, or
future schema versions are rejected. Unknown fields are rejected unless the
contract explicitly defines a typed extension map. No decoder retries an older
shape, fills removed fields, or rewrites stored data.

## Model And Request Semantics

Model resolution returns the selected backend/model plus declared model
capabilities such as context length and maximum output capacity. A capability
is not a request limit. The framework sends an output token limit only when the
caller explicitly sets `ModelSettings.max_tokens`; otherwise the provider's
default maximum applies.

Resolved context capacity is projected into task metadata for compaction. A
declared output capacity may inform memory reservation, but must never be copied
into request settings implicitly. Configured children resolve their own model
and receive the same rules as top-level runs.

Native provider request and response fields are decoded only at the provider
adapter boundary. They do not become alternate internal wire formats.

## Prompt And Built-In Tools

The prompt bundle and built-in tool inventory are generated from the canonical
fixtures. Ordering, names, descriptions, JSON Schemas, defaults, and terminal
directives are model-visible contract surface.

The framework remains task-neutral. It provides control, observation,
workspace, memory, delegation, approval, and lifecycle mechanisms, but it does
not classify a task, infer semantic progress, rewrite a business answer, or
choose a task-specific stopping policy.

## Completion And Results

`NoToolPolicy` has exactly `continue`, `wait_user`, and `finish`. Effective
precedence is per-run config, Runner default config, Agent config, then the
framework default `continue`. The policy observes only the mechanical presence
or absence of tool calls; it never classifies assistant text.

Every terminal result has a typed completion observation. Current completion
reasons are `tool_finish`, `no_tool_finish`, `stop_on_first_tool`,
`stop_at_tool_name`, `wait_user`, `max_cycles`, `cancelled`, `failed`, and
`budget_exhausted`. `partial_output` carries the last completed assistant
output for non-success terminal states. `completion_tool_name` is present only
for a tool-driven terminal.

## Token And Cache Usage

Each model cycle emits one closed `TokenUsage` object with
`schema_version=vv-agent.token-usage.v1`:

- nullable `input_tokens`, `output_tokens`, `total_tokens`, and
  `reasoning_tokens`;
- `usage_source`;
- typed `cache_usage` with nullable `read_input_tokens`,
  `write_input_tokens`, and `uncached_input_tokens`;
- `provider_usage`, the only diagnostic location for native provider fields.

Task totals use the closed
`schema_version=vv-agent.task-token-usage.v1` object. Every model cycle appears
as `{cycle_index, usage}`. An aggregate count is null when any cycle lacks that
count; unknown accounting is never fabricated as zero. Cache totals are
available only when every cycle provides the corresponding measurement.

Anthropic canonical input includes native input, cache reads, and cache writes.
Its uncached input includes native input plus cache writes. OpenAI-compatible
and other provider field names remain inside adapter input and
`provider_usage`; evaluators may not infer canonical fields from that map.

## Events And Streaming

RunEvent v1 is a closed, typed wire. Every event requires `version=v1`,
identity, and a finite non-negative `created_at` in Unix seconds. Approval
resolution carries exactly one `action` value.

Memory compaction and tool lifecycle events require every current field.
Readers reject incomplete events. Stream deltas preserve order and use
JSON-safe counters.

Event ids and timestamps are created once by the producer and remain identical
through provider callbacks, runtime journals, event stores, child forwarding,
and App Server projection.

## Tool Metadata And Policy

`ToolMetadata` contains side effect, idempotency, terminal capability,
capability tags, and cost dimensions. Omitted metadata has neutral effective
defaults.

Metadata policy is denial-only. Denials union across Agent, Runner, run,
configured-child, agent-as-tool, handoff, and distributed layers. They are
enforced both while planning the model-visible schema and at dispatch. The
framework does not infer metadata from names, arguments, or generic metadata.

Tool lifecycle order is planned, optional approval, started, then completed.
Started marks the external-effect boundary. A denial or approval short-circuit
has no started event. Completed events always include directive, nullable error
code, execution-start flag, and nullable monotonic duration.

## Sessions And Message History

Session items use one canonical current wire and one current SQLite schema.
Stores reject any other schema. Message roles, tool-call structure, metadata
types, and session item variants are validated strictly.

Continuation sanitization keeps only complete assistant tool-call/result
blocks in matching order. Orphan, duplicate, empty-id, or mismatched blocks are
excluded before a resumed request. Reasoning-only assistant messages remain
valid history; completely empty assistant messages are removed.

## Durable Checkpoint And Distributed Runtime

Checkpoint records require `vv-agent.checkpoint.v2` and embed an exact
`vv-agent.run-definition.v1` plus its RFC 8785 SHA-256 digest. Top-level records
are closed. SQLite uses `checkpoints`; Redis uses the single current hashed key
namespace. Readers reject any other table, prefix, or record shape.

Claims, leases, progress CAS, operation journals, event outboxes,
reconciliation, terminal retention, and acknowledgement have the same atomic
semantics in both languages. Unknown operation outcomes remain ambiguous until
the host defers, retries under policy, supplies a verified receipt, records a
typed failure, or explicitly aborts.

Distributed workers accept only
`schema_version=vv-agent.distributed-run.v2`. Capabilities and the frozen run
definition are resolved and compared before claim. Heartbeats update only the
lease; progress updates preserve the claim; terminal commit precedes scheduler
acknowledgement. Redelivery replays a durable terminal without executing the
model or tools again.

## Configured And Background Agents

Configured and dynamic children receive explicit model, prompt, tool policy,
workspace, memory, budget, identity, lineage, and cancellation projection.
Framework-owned identity metadata cannot be overwritten by user metadata.
Children never inherit a parent's durable checkpoint key implicitly.

Synchronous and asynchronous child lifecycle events use the same typed result,
completion, token usage, and error shapes. Background task start, message,
wait, status, cancel, and cleanup behavior must match across languages.

## App Server

JSON-RPC 2.0 ids, requests, responses, notifications, thread/turn state,
approval routing, replay, and durable resume are shared observable contract.
Terminal token usage mirrors the complete TaskTokenUsage object, including
cycle detail. Optional fields are omitted only where the App Server schema says
they are optional; current nested objects remain closed.

## Allowed Language Adaptations

Allowed adaptations are limited to ordinary language conventions:

- snake_case versus Rust method/type naming;
- Python `Path` versus Rust `PathBuf`;
- Python exceptions versus Rust error enums/results;
- Python sync/async facade spelling versus Rust async traits;
- provider construction that is idiomatic for each language, provided both
  expose the same resolved model and request behavior.

An adaptation is not allowed to add a capability, default, fallback, decoder,
or observation that the other implementation lacks.

## Required Evidence

Every shared change must include:

- canonical fixture and normative documentation;
- real Python and Rust producer tests;
- strict reader tests for missing, stale, unknown, and malformed input;
- snapshot checks against the same central artifact;
- focused tests for the changed domain;
- full Python and Rust quality gates;
- a successful central cross-repository CI run before `verified` status.

## Not Allowed

- Task-specific stop or synthesis logic in the framework core.
- Silent zeroes for unknown usage.
- Provider-field guessing outside adapters.
- Duplicate public fields representing the same fact.
- Historical readers, aliases, shims, migrations, fixtures, reports, or
  baselines in `HEAD`.
- Declaring parity from matching fixture bytes without real producer evidence.
