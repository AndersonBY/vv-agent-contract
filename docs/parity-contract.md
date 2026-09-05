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

Local model settings have one canonical input shape, frozen in
`fixtures/model_settings.json`. Supported file extensions are `.py`, `.json`,
and `.toml`. A Python settings file must assign the literal mapping to
`LLM_SETTINGS`; JSON and TOML files contain that mapping directly. The root
must explicitly contain `VERSION = "2"`, an `endpoints` array, and a
`backends` object. Loaders do not unwrap another root object, accept alternate
assignment or field names, synthesize a version, or retry a different parser.

Model lookup is exact within the selected backend. A missing backend or model
is an error; one configured model key is never substituted for another.

Model resolution returns the selected backend/model plus declared model
capabilities such as context length and maximum output capacity. A capability
is not a request limit. The framework sends an output token limit only when the
caller explicitly sets `ModelSettings.max_tokens`; otherwise the provider's
default maximum applies.

Resolved context capacity is projected into task metadata for compaction. A
declared output capacity may inform memory reservation, but must never be copied
into request settings implicitly. Top-level and configured child runs use the
same explicit `ModelProvider`; child runtimes inherit that provider rather than
reconstructing one from settings paths or backend fields. A child resolves its
own model unless it can reuse the parent client under the canonical same-model
rule.

When neither task metadata nor the resolved model declares a context window,
the runtime derives a planning context after selecting the output reserve. Its
prompt capacity is the positive configured compaction threshold, or the
`250000` configured default when that threshold is zero; output reserve and the
auto-compaction buffer are then added with unsigned-64-bit saturation. The
default derived context is therefore `250000 + 16000 + 13000 = 279000`, so an
unknown model capacity does not silently lower the configured compaction
threshold. A provider prompt-too-long response may still force compaction.

Native provider request and response fields are decoded only at the provider
adapter boundary. They do not become alternate internal wire formats.

## CLI Projection

The direct-task CLI contract is frozen in `fixtures/cli_contract.json`. Both
implementations consume that one fixture for settings-file precedence, prompt
joining, argument projection, resolved-model capability projection, and process
outcomes. Language-specific default settings filenames are the only declared
adaptation.

CLI model capabilities remain observations rather than request limits. In
particular, `max_output_tokens` is copied into task metadata for capacity
planning but does not populate `ModelSettings.max_tokens`; an output limit is
sent only when the user explicitly supplies one.

There is no implementation-local CLI contract fixture or compatibility parser.
Current CLI producers must satisfy this shape directly.

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
`AgentStatus.deferred` is non-terminal checkpoint state; distributed and App
Server projections expose `deferred_pending` as an interrupted, resumable view
without completion reason or error.

## Token And Cache Usage

Each terminal model attempt carries one closed `TokenUsage` object with
`schema_version=vv-agent.token-usage.v1`:

- nullable `input_tokens`, `output_tokens`, `total_tokens`, and
  `reasoning_tokens`;
- `usage_source`;
- typed `cache_usage` with nullable `read_input_tokens`,
  `write_input_tokens`, and `uncached_input_tokens`;
- `provider_usage`, the only diagnostic location for native provider fields.

Task totals use the closed
`schema_version=vv-agent.task-token-usage.v2` object. Its `model_calls` array
contains every framework dispatch attempt admitted across the local provider
boundary, including Session Memory and full memory compaction. Each record
identifies the logical operation, dispatch attempt, cycle, actual backend/model,
terminal status, normalized usage, and a
content-free error code. Logical retries keep `operation_id` but receive a new
`call_id` and incremented attempt. A durable replay adds no record.
Provider usage is fixed before an `AfterLlm` hook or equivalent callback may
replace response content; a hook cannot rewrite accounting identity or totals.

An aggregate count is null when any dispatched attempt lacks that count;
unknown accounting is never fabricated as zero. Cache totals are available
only when every dispatched attempt provides the corresponding measurement.
An empty ledger has exact zero token totals and `accounting_missing` cache
status because no provider observation occurred.
`CycleRecord` does not duplicate token usage. The complete normative shape,
budget boundary, and checkpoint atomicity rules are in
`model-call-accounting.md`.
The low-level `CycleRunner` is not a current public export; public execution
goes through `Runner` so every terminal path can expose the complete ledger.

Anthropic canonical input includes native input, cache reads, and cache writes.
Its uncached input includes native input plus cache writes. OpenAI-compatible
and other provider field names remain inside adapter input and
`provider_usage`; evaluators may not infer canonical fields from that map.

## Events And Streaming

RunEvent v5 is a closed, typed wire. Every event requires `version=v5`,
identity, and a finite non-negative `created_at` in Unix seconds. Approval
resolution carries exactly one `action` value.
The live-claim cancellation transition is represented only by the top-level
typed field `cancel_requested: {from: false, to: true}` on its complete
`run_state_changed` event; metadata carriers and unknown members are rejected.

`model_call_started`, `model_call_completed`, and `model_call_failed` expose
the task-neutral model-operation lifecycle. They replace `llm_started` and
identify the dispatch attempt, logical operation, cycle, backend, and model.
Terminal model events carry normalized usage; failures contain no provider
error body. Durable replay preserves the original event identity and does not
emit a second started event.
Completed events map to completed records, definitive failed events map to
failed records, and ambiguous failed events map to ambiguous records.

The public runtime exposes only this typed event surface. Provider stream
payloads stay private to the LLM adapter, and public runtime-log/provider
callbacks do not exist. Runtime producers create semantic lifecycle events
directly; child forwarding preserves their identity rather than converting
through an untyped payload.

Memory compaction and tool lifecycle events require every current field.
Readers reject incomplete events. Stream deltas preserve order and use
JSON-safe counters.

Task-neutral internal observations use `diagnostic` with required `level`,
non-empty `code`, and JSON-object `details`. `details` is an explicit extension
map, but diagnostics have no state authority and cannot replace lifecycle,
tool, approval, budget, cancellation, or terminal events.

Event ids and timestamps are created once by the producer and remain identical
through provider callbacks, runtime journals, event stores, child forwarding,
and App Server projection.

## Tool Metadata And Policy

`ToolMetadata` contains side effect, idempotency, terminal capability,
tool-result retention, capability tags, and cost dimensions. Omitted metadata
uses `result_retention=archive`, so custom and built-in tools are equally
eligible for archive-backed microcompaction. `result_retention=preserve`
excludes a result from proactive microcompaction without preventing full or
emergency compaction.

`MicrocompactionPolicy` is a public closed value with `trigger_ratio`,
`target_ratio`, `keep_recent_cycles`, and `min_result_chars`. `RunConfig`
selects it, `AgentTask` carries it explicitly, and run-definition schema v5
freezes it under `runtime_controls.microcompaction_policy`. Implementations
must not encode this policy in generic task or run metadata.
Both ratios are finite numbers in `(0, 1]`, with
`target_ratio < trigger_ratio`. `keep_recent_cycles` is an integer in
`0..4294967295`; `min_result_chars` is an integer in `1..4294967295`.
Booleans, null, float-encoded integers, missing fields, unknown fields,
non-finite host values, and out-of-range values are rejected.

`ToolExecutionResult` uses the closed `vv-agent.tool-execution-result.v4` wire
and has one status field: the required typed `status_code`.
The current wire values are `SUCCESS`, `ERROR`, `WAIT_RESPONSE`, `RUNNING`,
and `PENDING_COMPRESS`. `PENDING_COMPRESS` is emitted only by framework-owned
automatic compaction; it is not a tool exposure, tool name, or model-callable
state transition. Deferred is represented only by
`ToolCallOutcome.Deferred(DeferredToolHandle)` and never by a completed result.
Unknown fields are rejected, and no reader derives another status vocabulary
from `status_code`.

Tool calls use the closed `ToolCallOutcome` with exactly `completed` or
`deferred` variants. `deferred` carries only the closed
`DeferredToolHandle` (required discriminator plus four identity fields); it
never produces a model-visible tool result. The
durable admission, resolution CAS, batch barrier, recovery decision, and
distributed wait semantics are defined in `docs/durable-deferred-tools.md`.
The resolver's closed typed errors are `deferred_resolution_conflict`,
`deferred_resolution_stale`, `deferred_resolution_result_invalid`, and
`deferred_checkpoint_claimed`; none is a `DeferredResolveDecision` variant.

Contract `10.0.0` applies the sparse bounded-result rules in
`prompt-bundles-and-tool-results.md`. Ordinary results do not carry truncation
fields. Truncated results preserve their recovery pointer through model
projection, results, journals, checkpoints, and distributed execution.

Microcompaction is candidate-aware and performs one plan/application pass per
cycle. Every replaced result is first persisted under
`.vv-agent/artifacts/`; persistence failure preserves the inline result. The
model-visible marker contains only tool name, artifact path, retrieval hint,
and a bounded excerpt. Byte counts, character counts, and hashes remain
outside model context.
An existing artifact may be reused only after reading its persisted content
through the effective workspace backend and verifying both the UTF-8 byte
length against `size_bytes` and lowercase SHA-256 against `sha256`. Any read,
size, or digest failure preserves the original message. The application pass
measures each successful replacement using the actual original-message token
count minus the actual replacement-message token count and stops only when
actual post-replacement usage reaches the target or candidates are exhausted;
planner estimates never satisfy the target by themselves.

`ToolExposure` has exactly `direct` and `hidden`. The model-visible
`compress_memory` tool and its unconsumed `memory_notes` state do not exist;
automatic framework compaction remains internal.

Metadata policy is denial-only. Denials union across Agent, Runner, run,
configured-child, agent-as-tool, handoff, and distributed layers. They are
enforced both while planning the model-visible schema and at dispatch. The
framework does not infer metadata from names, arguments, or generic metadata.

Tool lifecycle order is planned, optional approval, started, then completed.
Started marks the external-effect boundary. A denial or approval short-circuit
has no started event. Ordinary definitive results are persisted immediately by
`record_tool_receipt`, which atomically writes the journal receipt and
`tool_call_completed` event while retaining the active claim. Completed events
always include directive, nullable error code, execution-start flag, and
nullable monotonic duration.

Every tool call is validated against its declared JSON Schema Draft 2020-12
parameter schema after the planned event and before policy predicates,
approval, the started event, or handler execution. Invalid arguments return
`invalid_tool_arguments`, a stable list of `instance_path`, `schema_path`, and
`rule` issues, and `execution_started=false`. Issue ordering is lexical by those
three fields. Object schemas are closed by default: registration adds
`additionalProperties=false` whenever an object schema does not state an
explicit policy. This rule applies equally to built-ins, function tools,
handoffs, agent tools, and host-registered custom tools; it does not inspect or
infer task semantics. Validation is atomic for the complete argument object: an
invalid nested array item rejects the tool call, and handlers never partially
execute a schema-invalid batch.

## Sessions And Message History

Session items use one canonical current wire and one current SQLite schema.
Stores reject any other schema. Message roles, tool-call structure, metadata
types, and session item variants are validated strictly.

`Message` has an optional typed `artifact_ref: ToolArtifactRef`. It is omitted
when absent and preserved by host APIs, sessions, results, journals,
checkpoints, run definitions, and distributed wires. Its object is closed and
uses the same normalized artifact path, UTF-8 byte size, and lowercase SHA-256
contract as tool results. Provider/model projection always removes
`artifact_ref`; recovery remains available through the marker's
`artifact_path` and the policy-checked `read_file` tool.

Continuation sanitization keeps only complete assistant tool-call/result
blocks in matching order. Orphan, duplicate, empty-id, or mismatched blocks are
excluded before a resumed request. Reasoning-only assistant messages remain
valid history; completely empty assistant messages are removed.

## Durable Checkpoint And Distributed Runtime

Checkpoint records require `vv-agent.checkpoint.v9` and embed an exact
`vv-agent.run-definition.v5` plus its RFC 8785 SHA-256 digest. Top-level records
are closed. SQLite uses `checkpoints`; Redis uses the single current hashed key
namespace. Readers reject any other table, prefix, or record shape.

The run definition stores the resolved `PromptBundle`. Its flat system text is
derived from ordered sections, and resume never reevaluates instruction/context
producers or the run clock. `AgentTask` and `LlmRequest` carry the same explicit
bundle; generic message/request metadata is not a prompt-section transport.

Claims, leases, progress CAS, model-call ledgers, operation journals, event outboxes,
reconciliation, terminal retention, and acknowledgement have the same atomic
semantics in both languages. Lease renewal returns the closed typed outcome
`renewed`, `cancel_requested`, or `claim_lost`; a live cancel sets the required
checkpoint `cancel_requested` signal, while expired-claim cancel/suspend
reclaims and applies control atomically. Unknown operation outcomes remain ambiguous until
the host defers, retries under policy, supplies a verified receipt, records a
typed failure, or explicitly aborts.

Definitive ordinary tool receipts use the same stable identity tuple
`(checkpoint_key, operation_id, attempt, tool_call_id, request_digest)`. The
stored `result_digest` is the RFC 8785 SHA-256 of the complete strict
`vv-agent.tool-execution-result.v4` after canonical typed-writer
normalization; empty optional `metadata` is omitted and every optional field
present after normalization is included. Receipt lookup uses only the identity key and precedes the active
claim/revision fence: a stale replay with the same identity and digest is a
zero-write replay, while a different digest is the typed
`tool_receipt_conflict` with zero writes. Ordinary receipt mutations are
serialized; the parity contract does not introduce a parallel CAS-retry
abstraction. Identity and digest come from the journal receipt itself; no
ordinary receipt scan API is part of the wire. `admit_deferred_batch` admits only outcomes that are still
deferred and never rewrites an already receipted result.

`cycle_aborted` is the durable lifecycle close for `cancelled`, `lease_lost`,
and `operator_abort`. It carries the `logical_cycle`, closes any unclosed tool
journals with `tool_cancelled` plus a concrete `resume_observation` object, and
retains the observations in the sorted unique `terminal_result.resume_observations`
list. Lease-loss closure reuses the existing recovery claim and
`finalize_claimed` operation with revision and cycle fences; a stale owner writes
nothing and an identical `cycle_aborted` event replay writes nothing. The
close does not claim that an unknown external effect succeeded.

An ordinary unclaimed `finalize` with no cycle to close writes a terminal result
with `resume_observations=[]` and no `cycle_aborted`. An unclaimed control
finalization that still has an unclosed logical cycle must provide a positive
`logical_cycle` and perform the tool closures and `cycle_aborted` write before
the terminal lifecycle; claimed control closure uses `finalize_claimed`.

The v9 `ControllerCommand` admission is also one task-neutral seam in both
languages. Its closed command and receipt wires use the same handle,
resume-attempt, and revision fences; `host_interaction` and `suspended` remain
non-terminal and recover the same logical cycle while preserving the last
committed cycle index. The framework-only producer persists a complete strict
host request (including a redacted prompt) and writes only the v4
`host_interaction_requested` event/UI notification outbox. A response command
persists the complete response in the independent interaction record before a
recovery worker injects it once and records
`host_interaction_response_consumed`; response replay is zero-write. Resume of
a running suspended origin wakes, while resume of a host-interaction origin
without a pending response only restores the wait. The controller
receipt/outbox CAS is separate from deferred resolution, while terminal
continuation remains a successor-run operation. `ask_user` continues to
produce terminal `wait_user`.

Distributed workers accept only
`schema_version=vv-agent.distributed-run.v5`. Capabilities and the frozen run
definition are resolved and compared before claim. The envelope `task` is the
current `AgentTask` wire and carries `prompt_bundle`; it has no separate
`system_prompt` field. Heartbeats update only the
lease; progress updates preserve the claim; terminal commit precedes scheduler
acknowledgement. Redelivery replays a durable terminal without executing the
model or tools again.

The worker response is a separate closed wire with
`schema_version=vv-agent.distributed-worker-response.v4` and one required
`type` discriminator. Exactly four variants exist:

- `pending` has no state fields and means that no cycle commit and no response
  result were returned by this delivery attempt;
- `committed` has exactly `checkpoint_revision` and `committed_cycle`;
- `terminal_candidate` has exactly `checkpoint_revision` and a complete
  current `AgentResult` wire object that still requires controller-side durable
  finalization;
- `terminal_replay` has exactly `checkpoint_revision` and the retained complete
  current `AgentResult` already authoritative in the checkpoint store.

The response object and nested current `AgentResult` are closed. Revisions are
integers in `0..9007199254740991`; committed cycle indexes are integers in
`1..9007199254740991`; booleans are not integers.
Candidates accept `reconciliation_required`, `wait_user`, `completed`, `failed`,
or `max_cycles`. Replays accept only `wait_user`, `completed`, `failed`, or
`max_cycles`; both reject `pending` and `running`, and a replay additionally
rejects `reconciliation_required`. Optional `AgentResult` fields are omitted
when absent and reject explicit null. Every scheduler outcome, including a
transport error, is reconciled against the authoritative checkpoint before the
controller acknowledges, finalizes, waits, or redispatches. Transport failure
is out of band and is not a fifth response type. The replaced `finished`,
`terminal_candidate`, and `terminal_replay` boolean combination is not a
compatibility input and must be rejected rather than inferred.

The public nonblocking driver uses the same envelope and response wires. Its
`start` and `advance` operations enqueue at most one cycle and return without
polling, sleeping, or waiting on a transport result. Every advance decision is
derived from one fresh authoritative checkpoint read. A verified terminal
candidate routes to framework-owned terminal finalization; it is never treated
as a durable terminal by the callback. `Runner.finalize_distributed` consumes
the verified decision in a separate bounded finalizer, including the unclaimed
`max_cycles` candidate produced after the last committed cycle. Duplicate or
out-of-order callbacks stop with `superseded_delivery`. Both implementations
also expose `start_distributed_compiled`, which accepts an already-compiled
`AgentTask`, preserves its prepared runtime fields, and does not re-run
compile-time instruction or context producers. See `distributed-run-driver.md`.

Deferred admission reuses the `pending` worker response because no cycle
commit and no response result were returned by this delivery attempt. While any current-batch deferred
journal entry lacks a definitive receipt, the driver returns
`wait(reason=deferred_pending)`; this is a non-terminal interrupted projection.
After the batch barrier is released it dispatches the resumed cycle through
the existing recovery claim path. This adds no worker response variant or
polling loop. The complete admission, resolution, and ordering contract is in
`durable-deferred-tools.md`.

## Configured And Background Agents

Configured and dynamic children receive explicit model, prompt, tool policy,
workspace, memory, budget, identity, lineage, and cancellation projection.
Framework-owned identity metadata cannot be overwritten by user metadata.
Children never inherit a parent's durable checkpoint key implicitly.

Session Memory defaults to disabled for top-level and child runs. It is enabled
only by the exact public `session_memory_enabled=true` control. There is no
legacy alias, seed-triggered activation, existing-file activation, or implicit
parent-to-child inheritance. When false or omitted, supplied memory context is
not rendered, stores are not read or written, and Session Memory inference is
not dispatched.

Synchronous and asynchronous child lifecycle events use the same typed result,
completion, token usage, and error shapes. Background task start, message,
wait, status, cancel, and cleanup behavior must match across languages.

## App Server

JSON-RPC 2.0 ids, requests, responses, notifications, thread/turn state,
approval routing, replay, and durable resume are shared observable contract.
`model_call_started`, `model_call_completed`, and `model_call_failed` project
to `modelCall` items with the same seven identity fields and content-free
terminal accounting. Terminal `tokenUsage` is the recursively camel-cased
projection of the complete `vv-agent.task-token-usage.v2` object, including
`modelCalls`; opaque native keys inside `providerUsage` remain unchanged. No
cycle-only usage projection remains. Optional fields are
omitted only where the App Server schema says they are optional; current nested
objects remain closed.

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
