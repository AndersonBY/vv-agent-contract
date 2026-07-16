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

Contract 0.5.1 writers add `run_definition_schema` with the fixed value
`vv-agent.run-definition.v1`. A checkpoint v2 record produced by the
never-verified 0.5.0 contract lacks that discriminator and cannot prove which
unspecified digest algorithm produced its hash. Missing or unknown values therefore fail with
`checkpoint_definition_schema_unsupported` before claim or external operations;
an explicit host migration must rebuild and attest the definition, validate the
journals, and atomically replace the schema, digest, and revision without a live
claim. Implementations never guess a 0.5.0 digest algorithm.

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
  to 262144 bytes;
- `credential_slots`: sorted unique RFC 6901 JSON Pointers into the unredacted
  run definition, defaulting to an empty list;
- `capability_refs`: explicit stable `{id, version}` references keyed by
  canonical behavior slot names such as `reconciliation_provider` or
  `runtime_hook:0`.

Local checkpoint runs never infer a reference from a Python object id, Rust
address, type name, or callable name. Every configured process-local capability
that can affect behavior needs a matching `capability_refs` entry; distributed
runs obtain the same references from their capability registry. Missing refs
fail with `checkpoint_definition_unstable` before checkpoint creation or any
external operation.

Invalid public configuration fails with the stable error code recorded beside
each invalid case in `checkpoint_config_v1.json`. Language-native exception or
error types may differ, but callers must be able to observe that code.

The default resume policy is `new`. Both ambiguous-operation policies default
to `require_reconciliation`. Per-run checkpoint configuration replaces a
configured Runner default as one object; individual fields are not merged.

`new` requires a supplied v2 key to be absent, or generates a key when null.
`resume_if_present` and `require_existing` require an explicit key. The former
atomically loads or creates a compatible record; the latter fails when absent.
Existing terminal state is replayed without model or tool execution. A live,
unexpired claim remains owned by its worker and cannot be stolen by a new
resume attempt.

`resume_attempt` is one on creation. It increases by exactly one only when a
recovery claim succeeds. A failed claim, live-claim rejection, definition
mismatch, and terminal replay leave it unchanged. `resume_if_present` creates
an absent record at one or increments an existing record only after its
recovery claim succeeds.

The store claim operation distinguishes `continue` from `recovery`. Initial
and ordinary next-cycle claims use `continue` and preserve the counter. Public
durable resume, expired-claim reclaim, and worker redelivery use `recovery`;
the successful claim atomically increments both revision and `resume_attempt`.
The store value is authoritative. A distributed envelope carries an
observation of that value plus explicit `claim_mode`, not permission to set the
counter directly. Celery and Apalis adapters promote a normal envelope to
`recovery` from transport retry/redelivery metadata; an expired stored claim or
`reconciliation_required` status also forces recovery. Two concurrent recovery
claims have one CAS winner and increment the counter exactly once.

The framework persists the complete credential-redacted `run_definition` and
computes `run_definition_digest` using lowercase SHA-256 over its canonical
JSON. The definition covers root input, compiled prompt,
model and model settings, model-visible tool schemas, tool idempotency
declarations and policy, budgets, workspace/session capability references, and
extension codec versions. It excludes credential values, store location,
claims, leases, and event cursor. An existing key with a different digest fails
before model or tool execution. Resume never accepts new user input implicitly;
conversational and approval resume remain separate public capabilities.

The embedded definition is immutable after create. Resume freezes its original
prompt, initial messages, initial shared state, metadata, and context reference
instead of re-reading a session or context provider that may already have
changed because of the interrupted run. Current tool/model schemas and stable
capability ids/versions are resolved and compared to that definition before new
external work. A digest without its definition is insufficient for 0.5.1.

### Run Definition Digest

`run_definition_v1.json` defines the exact digest input and two golden vectors.
The framework serializes the complete `vv-agent.run-definition.v1` object with
the RFC 8785 JSON Canonicalization Scheme, hashes the resulting UTF-8 bytes with
SHA-256, and stores lowercase hexadecimal. Implementations must use an RFC 8785
implementation rather than approximating it with ordinary sorted-key JSON.
Non-finite numbers, integers outside the I-JSON safe range, an unstable local
dynamic tool predicate, or any value that cannot enter the canonical object
fails before the first model or tool operation.

RFC 8785 object keys use UTF-16 code-unit ordering. Strings are not trimmed or
Unicode-normalized, and array order is preserved unless a field-specific rule
below declares set normalization. Golden numbers lock `1.0` as `1`, `-0.0` as
`0`, `1e-6` as `0.000001`, `1e-7` as `1e-7`, and `1e20` as
`100000000000000000000`.

The canonical definition contains:

- effective Agent name/type, root input, compiled prompt, caller/session-supplied
  initial messages, initial shared state, public behavior-affecting run metadata,
  and a stable context reference when a process-local context is present;
- resolved backend, model id, and effective model settings;
- runtime controls that change cycle, completion, memory, multimodal, or tool
  stopping behavior;
- model-visible tool schemas in their exact request order and each tool's
  declared idempotency, timeout, and static or referenced approval policy;
- normalized tool/checkpoint policy, budget limits, output schema, stable
  workspace/session and other behavior capability references, and extension
  namespace/version/required declarations.

Tool schemas and initial messages preserve order. Tool-policy name sets are
sorted and deduplicated by UTF-16 code units, and extensions are sorted by
namespace with the same ordering. Workspace,
session, and predicate references use the ordinary `{id, version}` capability
shape. A process-local dynamic predicate without a stable reference cannot be
used with checkpoint v2.

The run-definition top level is closed: unknown fields are rejected instead of
being ignored by one implementation. Every process-local capability that can
change model input, tool behavior, approval, guardrails, hooks, memory,
context, cost enforcement, reconciliation, or behavior-affecting run metadata
must have a stable `{id, version}` reference. Pure observers and event sinks may
remain outside the digest because they do not control the run. A missing stable
reference fails with `checkpoint_definition_unstable` before external work.

Credential values do not enter the definition. Providers or hosts declare a
sorted, unique list of RFC 6901 JSON Pointer `credential_slots`; host entries
come from `CheckpointConfig.credential_slots` and provider-declared entries are
merged before validation. Only values at those exact paths are replaced with
`<credential-redacted>`. Header names are
ASCII-lowercased, but non-credential values such as feature flags remain in the
definition. Credential rotation therefore preserves the digest while a
semantic header or body change does not. An unclassified sensitive provider
value fails closed before external operations instead of being guessed from a
key name.
Credential pointers are sorted by UTF-16 code units, accept only RFC 6901
`~0`/`~1` escapes, and must resolve exactly. Header names that collide after
ASCII lowercasing fail with `checkpoint_definition_header_collision`; they are
never merged or resolved by last-write-wins.
The selected store, checkpoint/run/trace/task identities, claims, leases, and
event cursor remain excluded.

## Checkpoint V2 Wire

`checkpoint_codec_v2.json` defines the canonical object. Required fields are:

- `schema_version`, exactly `vv-agent.checkpoint.v2`;
- `run_definition_schema`, exactly `vv-agent.run-definition.v1`;
- the complete credential-redacted `run_definition`, whose RFC 8785 digest must
  equal `run_definition_digest`;
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
`reconciliation_required` requires at least one ambiguous journal entry and no
claim. A running checkpoint may retain an ambiguous entry only while a recovery
claim is actively resolving it. Terminal records have no active journals except
an explicit operator-abort terminal, which retains its ambiguous evidence.

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

Journal progress preserves the active claim. A resumable interruption uses the
separate atomic `suspend_v2` operation: it writes
`reconciliation_required`, preserves ambiguous journals and the current cycle,
increments revision, and clears the claim tuple. A later recovery claim accepts
that status, atomically increments `resume_attempt`, and sets the working status
back to `running`. Cycle commit is never used merely to release an interrupted
claim because it would discard the evidence needed for reconciliation.

A terminal reached while the current cycle still has a live claim uses
`finalize_claimed_v2`. The store compares both revision and claim token, writes
the terminal receipt, and clears the claim atomically. Ordinary terminals clear
the active journals because the terminal receipt is authoritative. An explicit
operator-abort terminal preserves its ambiguous journal and
`ResumeObservation`. A runtime must not clear a claim locally and then call the
unclaimed `finalize_v2`; that loses ownership proof between the two writes.

## Event Cursor

`event_cursor` contains a versioned `store_ref`, opaque JSON `value`, and
nullable `last_event_id`. Replay starts exclusively after that value.
Checkpoint lifecycle events carry a stable event id and payload digest.
The payload digest is lowercase SHA-256 over RFC 8785 canonical UTF-8 bytes of
the complete event object.
`IdempotentRunEventStore.append_once(event_id, payload_digest, event)` returns
the original cursor for an identical duplicate and rejects the same event id
with a different digest. Re-emission after recovery therefore uses the same
identity and an idempotent consumer does not consume it twice.

The v2 checkpoint contains a bounded `event_outbox`. An event is first stored
as `pending`, then delivered with `append_once`, then marked `delivered` with
the returned cursor. Recovery redelivers pending entries with the same id and
digest. Delivered entries may be compacted after the enclosing cycle or
terminal acknowledgement becomes durable.

Event ids are unique within one checkpoint outbox. Enqueueing an id that is
already present with the identical payload digest reuses that entry instead of
appending a duplicate. Reusing an id with different payload bytes fails with
`event_identity_conflict`. This rule lets repeated reconciliation attempts
observe the same stable lifecycle event without making the checkpoint itself
undeliverable.

The delivery transition uses `record_event_delivery_v2`. It compares the
checkpoint revision, verifies the pending event id and payload digest, records
the exact returned cursor in both the outbox entry and `event_cursor`, and
increments revision. A running checkpoint keeps its claim and requires the
matching claim token; an unclaimed or terminal checkpoint requires a null claim
token. The operation never rewrites the terminal receipt. This separate CAS is
required because terminal event delivery occurs after terminal finalization.

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
entry is `{version, required, state}`. Snapshots must be JSON values. The RFC
8785 canonical UTF-8 bytes of the complete entry, excluding its namespace map
key, are limited to 65536 bytes. The sum of those complete entry byte lengths
is counted against `max_extension_state_bytes`, whose default is 262144 bytes.
`checkpoint_codec_v2.json` gives generated exact-limit and one-byte-over cases
so string quoting and entry metadata cannot be omitted from the calculation.

Required extensions and the complete initial extension snapshot are validated
before the first model or tool operation. Snapshot or restore errors leave the
existing checkpoint untouched and fail closed. Missing required extensions
fail before side effects. Unknown, non-required namespaces are preserved but
not interpreted.

Distributed workers resolve required extensions and any configured
reconciliation provider through the existing versioned capability registry. A
process-local object is never serialized into the distributed envelope.

## Operation Journal

`operation_journal_v1.json` defines model and tool entries. Every entry has a
stable `operation_id`, positive `cycle_index`, `attempt`, `state`, and lowercase
SHA-256 `request_digest`. States are:

1. `planned`: the request identity is durable and invocation has not started;
2. `started`: invocation may have reached the external provider or tool;
3. `succeeded`: a complete effective response or result is durable;
4. `failed`: a complete typed error receipt is durable;
5. `ambiguous`: recovery observed `started` without a durable receipt.

Invalid journal entries fail with the stable error code recorded beside each
invalid case in `operation_journal_v1.json`; a parser message alone is not the
cross-language contract.

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

`request_digest` is lowercase SHA-256 over the RFC 8785 UTF-8 bytes of a closed
`vv-agent.operation-request.v1` projection. A model projection contains the
complete effective credential-redacted provider request. A tool projection
contains tool call id, exact tool name, arguments, and framework idempotency
key. Operation id, cycle, and attempt are journal coordinates and do not enter
the request digest. Retrying the same logical request increments `attempt`
while preserving operation id, request digest, and idempotency key; a changed
effective request creates a new journal entry.

`failed` is allowed only for a definitive outcome. A local failure before
dispatch may move `planned` to `failed`, and an explicit provider/tool
rejection may move `started` to `failed`. A timeout, cancellation, connection
loss, or non-cooperative blocking-tool timeout after `started` is ambiguous
unless the adapter can prove a definitive external outcome. Returning from a
timeout wrapper does not prove that a worker thread or process stopped creating
side effects.

Approval, policy, and before-hook short circuits never write `started`.
Approval-pending work may remain `planned`. The ordinary source `wait_user`
terminal clears its active journal like every non-abort terminal; it does not
retain a second executable copy of the planned call. Before that terminal is
finalized, the in-memory `RunState` resume context captures the source tool
call id, request digest, idempotency key, idempotency declaration, and effective
request needed to seed an approved resume.

Approval resume is a distinct run and never reuses the immutable source waiting
checkpoint key. The host supplies a distinct checkpoint configuration through
the configured Runner used to resume the approved `RunState`. Approval resume
requires an explicit key and `resume_if_present`. The approval-consumption
record is bound to that target key: repeating the claim with the same key is
idempotent, while a different key is rejected. This closes the crash window
between approval consumption and checkpoint creation without allowing two
resume runs to execute the approved effect.

The bound approval is claimed before the new checkpoint is atomically created
or loaded. Creation durably seeds a `planned` tool journal entry with the
captured source identity before `started`; an existing compatible checkpoint
continues through the ordinary claim CAS. That seeded entry is the
checkpoint-v2 durable approval boundary.
The new operation id is stable within the resume run, while the source tool
call id, request digest, and idempotency key remain unchanged. A crash after
the seed is durable therefore resumes the approved planned call without asking
the model or consuming the approval again. A crash after the bound claim but
before creation retries the same target key and is allowed to finish creation.

The source checkpoint alone is not a serialization of the process-local
`RunState` approval capability. A host that needs approval across process
restart must durably retain and authenticate that existing approval resume
context; terminal replay does not invent it from tool arguments. Memory
compaction and PTL recovery calls to an LLM are model operations and use the
same journal protocol.

Replaying a durable response or tool result must not call the external model or
tool again. The reconstructed request digest must equal the durable digest;
mismatch is checkpoint/journal integrity failure, not evidence that the
external outcome is ambiguous. It returns
`checkpoint_journal_integrity_mismatch` before claim without mutating the
journal or replaying stale data. Explicit host repair/migration is required.

## Ambiguity And Reconciliation

On recovery, `started` without a durable receipt becomes `ambiguous`. The
runtime exposes a typed `ResumeObservation` and asks an optional host
reconciliation provider for one of these decisions:

- `defer`: keep the operation ambiguous;
- `retry`: return it to `planned` using the same operation and idempotency keys;
- `replay_success`: supply the externally verified response or tool result;
- `record_failure`: supply a durable typed error;
- `abort`: explicitly accept that the external outcome is unknown and end the
  run as a typed operator failure while preserving the ambiguous journal and
  `ResumeObservation` in the retained terminal checkpoint.

Without a conclusive decision, the invocation returns the typed status
`reconciliation_required` and interruption reason
`resume_requires_reconciliation`. It has no completion reason and is not a
terminal checkpoint. The checkpoint remains resumable and retains the
ambiguous entry; it is not converted into a business completion or failure.
Only the explicit `abort` decision makes that checkpoint terminal, and it does
not rewrite the operation as a definitive `failed` receipt. `finalize_v2`
retains the ambiguous journal and observation for this terminal instead of
clearing the unknown external outcome.

Tool retry is automatic only under `retry_idempotent_only` and explicit
`supported` idempotency. The same idempotency key is reused. The framework does
not infer safety from a tool name, arguments, task, or apparent read/write
behavior. Unsupported or unknown tools still require reconciliation.

Model retry under `retry_with_duplicate_risk` is explicit and emits a duplicate
request/cost risk observation. Provider-declared idempotency may eliminate the
duplicate effect, but absence of that declaration never becomes an implicit
guarantee.

The reconciliation provider is optional. Without one, the runtime applies
`defer`, returns `reconciliation_required`, and leaves the durable ambiguity
untouched. A distributed envelope resolves a reconciliation capability only
when a reference is present.

## Budget And Time Resume

The complete `BudgetUsageSnapshot` is persisted at every journal progress
boundary when a budget is configured. Resume starts from that snapshot. Active
monotonic elapsed time never resets, while queue time, process downtime,
approval waits, and reconciliation waits are not fabricated as active run
time. Time between the last durable observation and a crash cannot be
reconstructed and is not guessed.

## Session Persistence

Checkpoint v2 cannot make a separate session store transactional with the
checkpoint store. When a configured run also uses a session, the session must
therefore implement append-once persistence. The framework computes:

- commit id: `vv-agent:checkpoint-v2:session:` followed by lowercase SHA-256
  of the checkpoint key UTF-8 bytes;
- payload: the closed `vv-agent.session-commit.v1` object containing the exact
  ordered session items;
- payload digest: lowercase SHA-256 over the RFC 8785 canonical UTF-8 bytes of
  that payload.

`add_items_once(commit_id, payload_digest, items)` appends and records an
absent identity, returns the original success without appending for an
identical replay, and rejects the same id with a different digest as
`session_commit_identity_conflict`. A checkpoint-enabled run whose session
does not provide this capability fails with
`checkpoint_session_idempotency_unsupported` before the first model or tool
operation. Runs without checkpoint v2 keep the existing `add_items` behavior.

Terminal ordering is output guardrail, append-once session persistence,
durable `session_persisted` observation, terminal event staged as pending,
atomic claimed terminal finalization, terminal event delivery, durable
delivery recording, retained terminal acknowledgement, and only then host or
scheduler acknowledgement. A crash at any boundary reuses the same session
commit and outbox identities.

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
`checkpoint` and `interruption` summaries. Their exact camelCase field sets and
safe examples are defined in `app_server_observable_v1.json`. It never exposes
the run definition or digest, operation arguments, responses, extension state,
or idempotency keys. Public
`AgentResult` serialization uses the additive null fields defined by
`result_public_v1.json`; checkpoint v1 bytes strip them, and App Server omits
absent summaries. Omitting checkpoint v2 otherwise preserves pre-0.5 behavior.

App Server `checkpoint.status` is the persisted `AgentStatus`; it is distinct
from App Server `TurnStatus`. For example, durable
`reconciliation_required` projects to turn status `interrupted`, while a live
checkpoint `running` claim projects to turn status `running`.
`app_server_observable_v1.json` contains complete JSON-RPC request, immediate
response, and notification sequences. A newly claimed resume responds
`running` before `turn/started`; reconciliation later ends with
`turn/completed:interrupted` and omits completion/error fields. A live claim
returns its existing owner without a new run or notifications. A retained
terminal is replayed in the response without new external calls or duplicate
terminal notifications.

A v2 terminal acknowledgement marks the checkpoint acknowledged but retains
the row and terminal receipt for redelivery. Deletion is an explicit host
retention operation after the host no longer needs replay.

Terminal finalization follows the executable distributed ordering fixture:
output guardrail, append-once session persistence, durable session observation,
pending terminal event in the checkpoint outbox, checkpoint terminal finalize,
event delivery, durable outbox-delivery recording, retained terminal
acknowledgement, then scheduler acknowledgement. A terminal is never made
durable before output guardrail or session finalization and later rewritten.

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

Checkpoint configuration belongs to one root run definition. Agent-as-tool and
background children do not implicitly inherit the parent's checkpoint key; a
host may provide a distinct child key explicitly. Contract 0.5.1 fails closed
with `checkpoint_handoff_unsupported` when checkpoint v2 is combined with a
handoff, because the complete handoff graph and active-agent state are not yet
part of the v2 wire. This restriction is explicit rather than silently
resuming under the wrong agent definition.

## Canonical Evidence

- `checkpoint_codec_v2.json` defines the codec, migration, namespace, size,
  claim, and compatibility cases.
- `operation_journal_v1.json` defines valid entries, transitions,
  reconciliation decisions, replay, and retry boundaries.
- `checkpoint_config_v1.json` defines public defaults, precedence, key
  generation, collision, missing-key, and run-definition mismatch behavior.
- `run_definition_v1.json` defines the RFC 8785 digest input, credential
  redaction, canonical bytes, and SHA-256 golden vectors.
- `checkpoint_store_v2.json` defines v2 create/load, claim-internal progress,
  lease, CAS, terminal, outbox, append-once, and namespace behavior.
- `checkpoint_resume_v1.json` contains executable public Runner and distributed
  recovery cases; boolean fixture claims are insufficient producer evidence.
- `resume_events_v1.jsonl` is a catalog of canonical scenario excerpts, not one
  continuous run. Records sharing a run id and trace id define required local
  order; different identity pairs are independent fixture groups. Grouping
  metadata is not inserted into the formal RunEvent payload.
- `distributed_run_envelope_v2.json` defines the worker wire, required
  extension references, and optional reconciliation capability reference. The v1 envelope fixture
  remains byte-identical as a dual-read golden input.
