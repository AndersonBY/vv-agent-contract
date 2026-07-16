# Durable Checkpoint And Resume Contract

This document defines the optional checkpoint v2 and durable-resume contract
introduced in `vv-agent-contract` 0.5.0. It is a task-neutral persistence and
recovery mechanism. It does not inspect prompts, answers, task categories, or
domain milestones, and it does not decide whether a task is semantically
complete.

The capability name is **durable resume with explicit ambiguity**. “Exact
resume” is not used as an unqualified guarantee because an external operation
can complete without its receipt becoming durable.

## Compatibility And Activation

Checkpoint v2 is opt-in through `CheckpointConfig`. Omitting the configuration
preserves the existing checkpoint v1, Runner, event, and terminal behavior.
Checkpoint-capable execution backends must reject an enabled v2 configuration
before the first model or tool operation when their state store or required
worker capabilities cannot support it.

V1 and v2 use independent durable namespaces. SQLite stores use an independent
`checkpoints_v2` table and Redis stores use an independent v2 key prefix. An
older binary can continue to read and write v1 without seeing or overwriting v2
state. V2 readers continue to decode v1 payloads for explicit migration, but an
enabled v2 run does not silently adopt an unrelated v1 record.

An explicit v1-to-v2 migration is allowed only for a durable v1 terminal. A
non-terminal v1 record cannot prove that no unjournaled external operation ran
after its last cycle commit, even when its lease has expired, and therefore
requires reconciliation instead of automatic migration. The caller supplies
the v2 checkpoint key and run identity. An active v1 claim cannot be migrated.

## Public Configuration

`CheckpointConfig` contains:

- `key`: a stable, non-empty UTF-8 string of at most 512 bytes, or null only
  when `new` asks the framework to generate and return one;
- `resume_policy`: `new`, `resume_if_present`, or `require_existing`;
- `ambiguous_model_policy`: `require_reconciliation` or
  `retry_with_duplicate_risk`;
- `ambiguous_tool_policy`: `require_reconciliation` or
  `retry_idempotent_only`;
- exactly one of `store` (a process-local checkpoint v2 store) or
  `store_ref` (a reconstructable distributed capability reference);
- `required_extension_namespaces`: unique, lexicographically serialized
  namespaces;
- `max_extension_state_bytes`: an integer in `0..9007199254740991`, defaulting
  to 262144 bytes.

The default resume policy is `new`. Both ambiguous-operation policies default
to `require_reconciliation`. Per-run checkpoint configuration replaces a
configured Runner default as one object; individual fields are not merged.

`new` requires a supplied v2 key to be absent, or generates a key when null.
`resume_if_present` and `require_existing` require an explicit key. The former
atomically loads or creates a compatible record; the latter fails when absent.
Existing terminal state is replayed without model or tool execution. A live,
unexpired claim remains owned by its worker and cannot be stolen by a new
resume attempt.

The framework computes and persists a `run_definition_digest` using lowercase
SHA-256 over canonical JSON. The definition covers root input, compiled prompt,
model and model settings, model-visible tool schemas, tool idempotency
declarations and policy, budgets, workspace/session capability references, and
extension codec versions. It excludes credential values, store location,
claims, leases, and event cursor. An existing key with a different digest fails
before model or tool execution. Resume never accepts new user input implicitly;
conversational and approval resume remain separate public capabilities.

## Checkpoint V2 Wire

`checkpoint_codec_v2.json` defines the canonical object. Required fields are:

- `schema_version`, exactly `vv-agent.checkpoint.v2`;
- `checkpoint_key`, `task_id`, `root_run_id`, `trace_id`, and
  `run_definition_digest`;
- `resume_attempt`, starting at one and increasing for each claimed recovery;
- `cycle_index`, `status`, `messages`, `cycles`, and `shared_state`;
- nullable `budget_usage`;
- `event_cursor` and `event_outbox`;
- `extension_state`;
- `model_call_journal` and `tool_journal`.

The existing additive `revision`, claim, lease, and `terminal_result` fields
retain their checkpoint v1 meanings. A claim tuple remains all-or-none, and a
terminal record cannot have an active claim.

An absent `schema_version` is decoded strictly as checkpoint v1. A present,
unknown discriminator returns `checkpoint_schema_unsupported`; it never falls
back to v1. Unknown top-level v2 fields are preserved by a read-write cycle when the store
uses a whole-object representation. Known fields with invalid types or values
are rejected. Unknown extension namespaces are always preserved as opaque JSON
and are not restored into an unregistered extension.

Checkpoint journals contain only the active or not-yet-committed cycle. A
successful cycle commit incorporates its messages, cycle record, usage, and
state into the ordinary checkpoint fields and clears the committed journals.
This bounds checkpoint growth without discarding information needed to resume
an interrupted operation.

## Event Cursor

`event_cursor` contains a versioned `store_ref`, opaque JSON `value`, and
nullable `last_event_id`. Replay starts exclusively after that value.
Checkpoint lifecycle events carry a stable event id and payload digest.
`IdempotentRunEventStore.append_once(event_id, payload_digest, event)` returns
the original cursor for an identical duplicate and rejects the same event id
with a different digest. Re-emission after recovery therefore uses the same
identity and an idempotent consumer does not consume it twice.

The v2 checkpoint contains a bounded `event_outbox`. An event is first stored
as `pending`, then delivered with `append_once`, then marked `delivered` with
the returned cursor. Recovery redelivers pending entries with the same id and
digest. Delivered entries may be compacted after the enclosing cycle or
terminal acknowledgement becomes durable.

The cursor and outbox do not turn an arbitrary callback into a transactional
consumer. Checkpoint v2 provides accepted-once delivery only through an
`IdempotentRunEventStore`; raw stream callbacks remain at-least-once and must
deduplicate stable event ids. The contract must not describe this as universal
exactly-once event delivery.

## Extension State

A checkpoint extension has a stable lowercase reverse-DNS namespace and
task-neutral snapshot and restore operations. Namespace strings use lowercase
ASCII letters, digits, `.`, `_`, and `-`, begin with an alphanumeric character,
contain at least one `.`, and contain at most 128 bytes. The
`ai.vectorvein.vv-agent.*` prefix is reserved for framework-owned state. Each
entry is `{version, required, state}`. Snapshots must be JSON values. A compact
entry is limited to 65536 UTF-8 bytes and all entries together are counted
against `max_extension_state_bytes`, whose default is 262144 bytes.

Required extensions and the complete initial extension snapshot are validated
before the first model or tool operation. Snapshot or restore errors leave the
existing checkpoint untouched and fail closed. Missing required extensions
fail before side effects. Unknown, non-required namespaces are preserved but
not interpreted.

Distributed workers resolve extension and reconciliation providers through
the existing versioned capability registry. A process-local object is never
serialized into the distributed envelope.

## Operation Journal

`operation_journal_v1.json` defines model and tool entries. Every entry has a
stable `operation_id`, positive `cycle_index`, `attempt`, `state`, and lowercase
SHA-256 `request_digest`. States are:

1. `planned`: the request identity is durable and invocation has not started;
2. `started`: invocation may have reached the external provider or tool;
3. `succeeded`: a complete effective response or result is durable;
4. `failed`: a complete typed error receipt is durable;
5. `ambiguous`: recovery observed `started` without a durable receipt.

The runtime durably writes `planned`, then `started`, before invoking an
external operation. It writes `succeeded` or `failed` before downstream cycle
commit. Progress writes keep the active claim and do not release its lease.
Store implementations must prevent a heartbeat update from overwriting a
concurrent journal progress write.

A model entry carries a stable nullable `idempotency_key`, the effective model
response when succeeded, and a typed error when failed. A tool entry also
carries the model-provided tool call id, exact tool name, arguments,
`idempotency_key`, and declared idempotency support (`supported`, `unsupported`,
or `unknown`). The idempotency key is exposed through `ToolContext`; it is not
inserted into model-visible tool arguments. Function tools and tool specs expose
the declaration as `idempotency`; the default is `unknown`.

Replaying a durable response or tool result must not call the external model or
tool again. The reconstructed request digest must equal the durable digest;
mismatch requires reconciliation rather than silently using stale data.

## Ambiguity And Reconciliation

On recovery, `started` without a durable receipt becomes `ambiguous`. The
runtime exposes a typed `ResumeObservation` and asks an optional host
reconciliation provider for one of these decisions:

- `defer`: keep the operation ambiguous;
- `retry`: return it to `planned` using the same operation and idempotency keys;
- `replay_success`: supply the externally verified response or tool result;
- `record_failure`: supply a durable typed error;
- `abort`: end the run as an ordinary explicit failure.

Without a conclusive decision, the invocation returns the typed status
`reconciliation_required` and interruption reason
`resume_requires_reconciliation`. It has no completion reason and is not a
terminal checkpoint. The checkpoint remains resumable and retains the
ambiguous entry; it is not converted into a business completion or failure.

Tool retry is automatic only under `retry_idempotent_only` and explicit
`supported` idempotency. The same idempotency key is reused. The framework does
not infer safety from a tool name, arguments, task, or apparent read/write
behavior. Unsupported or unknown tools still require reconciliation.

Model retry under `retry_with_duplicate_risk` is explicit and emits a duplicate
request/cost risk observation. Provider-declared idempotency may eliminate the
duplicate effect, but absence of that declaration never becomes an implicit
guarantee.

## Budget And Time Resume

The complete `BudgetUsageSnapshot` is persisted at every journal progress
boundary when a budget is configured. Resume starts from that snapshot. Active
monotonic elapsed time never resets, while queue time, process downtime,
approval waits, and reconciliation waits are not fabricated as active run
time. Time between the last durable observation and a crash cannot be
reconstructed and is not guessed.

## Terminal And Observable Projection

`resume_requires_reconciliation` is a typed interruption reason with
`AgentStatus.reconciliation_required`. The result retains the last committed
messages, cycles, usage, budget, partial output, checkpoint key, and
`ResumeObservation`. A committed terminal is always authoritative. A live
claim remains an in-progress coordination result. An unresolved ambiguous
operation is projected before a new cancellation, budget, or business terminal
can hide its unknown external effect.

Run events expose checkpoint creation/resume, durable operation replay,
ambiguity, and reconciliation-required observations. App Server exposes a
dedicated `turn/resume` operation, maps reconciliation-required to turn status
`interrupted` without `completionReason` or `error`, and exposes optional
`checkpoint` and `interruption` summaries. It never exposes operation arguments,
responses, extension state, or idempotency keys. Omitting checkpoint v2
preserves the pre-0.5 result, event, and App Server shape.

A v2 terminal acknowledgement marks the checkpoint acknowledged but retains
the row and terminal receipt for redelivery. Deletion is an explicit host
retention operation after the host no longer needs replay.

## Safety Boundary

Checkpoint v2 provides these guarantees:

- committed cycle and operation receipts are replayed without re-execution;
- ambiguous non-idempotent operations are never silently retried;
- stable idempotency keys let a cooperating external service provide
  effect-level exactly-once behavior;
- unresolved ambiguity remains explicit and recoverable.

It does not make an arbitrary external API exactly-once, recover a model
response that was never durably received, make host hooks transactional, or
atomically commit an unrelated event store and state store. Those limitations
must remain visible in documentation and observations.

Checkpoint stores contain conversation state and may contain tool arguments,
receipts, model responses, and extension state. Authentication, authorization,
tenant isolation, encryption at rest, retention, and redaction are host
responsibilities. App Server projections intentionally expose only summaries.

## Canonical Evidence

- `checkpoint_codec_v2.json` defines the codec, migration, namespace, size,
  claim, and compatibility cases.
- `operation_journal_v1.json` defines valid entries, transitions,
  reconciliation decisions, replay, and retry boundaries.
- `checkpoint_config_v1.json` defines public defaults, precedence, key
  generation, collision, missing-key, and run-definition mismatch behavior.
- `checkpoint_store_v2.json` defines v2 create/load, claim-internal progress,
  lease, CAS, terminal, outbox, append-once, and namespace behavior.
- `checkpoint_resume_v1.json` contains executable public Runner and distributed
  recovery cases; boolean fixture claims are insufficient producer evidence.
- `resume_events_v1.jsonl` defines canonical event order and observation
  payloads.
- `distributed_run_envelope_v2.json` defines the worker wire and required
  extension/reconciliation capability references. The v1 envelope fixture
  remains byte-identical as a dual-read golden input.
