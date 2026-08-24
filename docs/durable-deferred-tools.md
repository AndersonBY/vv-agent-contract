# Durable Deferred Tools

Contract `8.0.1` defines one task-neutral boundary for a tool whose external
effect may be accepted while its result is unavailable during the current
worker invocation. The framework owns the operation identity, checkpoint
journal, batch barrier, claim, and lifecycle events. A host/provider owns the
external acceptance and later callback; provider identifiers, job identifiers,
proof objects, and business payloads never enter the framework handle.

## Current closed wires

`ToolCallOutcome` is `vv-agent.tool-call-outcome.v2` and has exactly two
variants:

- `completed` contains one complete `ToolExecutionResult`;
- `deferred` contains one `DeferredToolHandle` and no tool result.

`ToolExecutionResult.status_code` has the current values `SUCCESS`, `ERROR`,
`WAIT_RESPONSE`, `RUNNING`, and `PENDING_COMPRESS`. Deferred is not a result
status. A completed outcome must not contain a deferred status; the only
deferred representation is `ToolCallOutcome.Deferred(handle)`. The runtime
still exposes `AgentStatus.deferred` for a checkpoint waiting behind a
deferred batch barrier.

`DeferredToolHandle` is `vv-agent.deferred-tool-handle.v2`. It is a closed wire
with a required `schema_version` discriminator plus exactly four identity
fields: `checkpoint_key`, `operation_id`, `attempt`, and `request_digest`.
Every canonical, batch, journal, checkpoint, event, and reconciliation example
contains all four identity fields and the discriminator. Missing, stale,
unknown, malformed, or future discriminators and unknown fields are rejected;
there is no historical decoder or field inference.

The request digest is the lowercase SHA-256 of the closed
`vv-agent.operation-request.v1` tool projection. The handle contains no
provider ID, job ID, polling instruction, callback, deadline, cancellation,
permission, billing, or business ID.

## Framework-owned construction seam

The executor does not construct checkpoint internals. The framework provides
`ToolContext.defer() -> ToolCallOutcome.Deferred`. The factory allocates the
framework identity from the active call and creates the handle before a tool
handler performs external acceptance. A handler may pass that opaque handle to
its provider out of band and return the outcome to the core; the provider
decision is not part of the core wire.

The factory fails closed with `deferred_requires_checkpoint` before any
external side effect when no durable checkpoint is active. A non-durable run
must never synthesize a handle. A checkpoint-enabled local store (in-memory,
SQLite, or Redis) is sufficient and uses exactly the same admission and
resolution CAS rules as a distributed checkpoint. An in-memory store is
durable for the active process only; a cross-process callback must use the same
process or a persistent local store such as SQLite/Redis. A process-local
executor cannot bypass the checkpoint boundary merely because it is local.
Ordinary local tool calls are unaffected: they still return their normal
completed outcomes. Only the `defer()` path requires the durable checkpoint;
on a non-durable run it returns `Completed(ERROR)` with the stable
`deferred_requires_checkpoint` code before the handler can perform an external
effect.

## One admission for one model-tool batch

The core keeps the active claim while it executes and collects every outcome in
the current model tool batch. It then calls one framework-owned
`admit_deferred_batch` CAS; a caller never loops over single-item admission.
The CAS compares the checkpoint key, expected revision, active claim token, and
claimed cycle. It atomically writes all completed journal receipts, all
deferred journal handles, all corresponding outbox events, the batch barrier,
and the claim/lease release, then increments the revision once.

The event outbox is lifecycle-bounded, not limited by a fixed entry or byte
cardinality. The framework knows the current model-tool batch size before the
first external tool effect and preflights durable storage for every possible
started event, completed `SUCCESS`/`ERROR` event, deferred-admission event, and
later deferred-resolution completion event. This applies to ordinary and
deferred tools; admission or resolution cannot fail with `outbox_full` after a
provider effect. A no-fixed-cap independent outbox is an equivalent design.

For a mixed batch, completed outcomes become `succeeded` journal entries and
ordinary `tool_call_completed` events in that same CAS. Deferred outcomes
become `deferred` journal entries and `tool_call_deferred` events in that same
CAS. If at least one outcome is deferred, checkpoint status is `deferred`; the
claim is released exactly once after the all-or-none write. Completed outcomes
are retained in original model tool-call order, but they do not release the
deferred barrier. If the CAS fails or the process crashes before it, every
started entry not covered by the durable CAS is treated as ambiguous; neither
a generated completed result nor a generated handle is silently assumed.

The admission CAS is the only place that releases the claim for the batch. A
partial journal/event write is invalid. A post-CAS crash replays the exact
handles and outbox identities without invoking any external operation.

## Barrier and recovery

The current-batch barrier remains `deferred` while any batch journal entry is
deferred. Cycle commit and the next model call are blocked. Generic recovery
claim selection excludes `deferred`; a deferred checkpoint cannot be claimed
just to run the model again. This prevents a resolver and a worker from racing
through the same unresolved tool call.

Resolution of the last entry atomically changes the checkpoint status to
unclaimed `running`, empties the barrier, and makes it schedulable through the
ordinary recovery claim path. If entries remain unresolved, status remains
`deferred`. Resolutions can arrive in any order; resumed model input merges
results in original model tool-call order, never callback order.

## Resolution and durable receipts

The public operation remains deliberately small:

```text
resolve_deferred(handle, result)
```

It returns the closed `DeferredResolveDecision` type with exactly one variant:
`AppliedReady(receipt)`, `AppliedWaiting(receipt)`, `Replayed(receipt)`,
`NotAdmitted` (no receipt), or `ReconciliationRequired` (no receipt). The
first three variants require the exact receipt; the last two forbid one.
`NotAdmitted` carries retryable code `deferred_resolution_not_admitted`.
Callers never pass an expected revision. The typed public errors are
`deferred_resolution_conflict`, `deferred_resolution_stale`,
`deferred_resolution_result_invalid`, and `deferred_checkpoint_claimed`; they
are errors, not decision variants.

Callers do not pass an expected revision. The store reloads the authoritative
checkpoint and uses an internal revision-CAS retry loop. It first searches the
independent durable deferred-receipt index by the exact handle key. An exact
handle with the same canonical definitive result is an idempotent replay and
returns the existing receipt without a checkpoint revision or side effect. The
same handle with a different result is `deferred_resolution_conflict`. Only
when no receipt matches does it validate the active journal handle and state.
An active `started` entry that has not reached batch admission returns the
retryable `deferred_resolution_not_admitted` decision without writing anything;
the host must durably retain the result and retry after admission. An
`ambiguous` entry remains `reconciliation_required`. Only a true identity
mismatch or an active entry with no retained receipt is
`deferred_resolution_stale`. If the exact active deferred handle matches but the
checkpoint has a non-null claim, the resolver raises
`deferred_checkpoint_claimed` without writing a journal, receipt, barrier,
outbox, or revision; this invariant error is not a decision variant.

Only `SUCCESS` and `ERROR` results are definitive. Both are valid transitions:
`deferred -> succeeded` and `deferred -> failed`. `WAIT_RESPONSE`, `RUNNING`,
and `PENDING_COMPRESS` are rejected as resolution results. Resolution never
calls the external tool and requires no worker claim.

One resolution CAS atomically updates the journal, inserts the exact receipt
tombstone into the independent durable index, stages one
`tool_call_completed` outbox event, releases that handle's barrier item,
updates status/barrier, and increments the revision in the same store
transaction/Lua/CAS. The receipt contains the exact handle, canonical
definitive result, result digest, stable completion event ID, event payload
digest, and `succeeded` or `failed` receipt status. The index has no arbitrary
cardinality cap: each handle key is retained for exactly the checkpoint's
retention lifetime, including retained terminal state, and is deleted together
with explicit checkpoint cleanup. Capacity cannot first fail after the
external effect because the receipt index write is part of the same atomic
resolution transaction and has no post-effect bounded receipt-index capacity
admission.

`duration_ms` is `null` for a cross-process resolution and
`execution_started=true`; it measures no resolver-side execution. A normal
resolution emits only `tool_call_completed`, never
`reconciliation_resolved`. A result whose directive is `finish` or `wait_user`
is persisted as data; the ordinary resumed cycle processes that directive.
The resolver never fabricates a terminal checkpoint directly.

Concurrent resolutions are linearized by the store CAS loop: one wins, and
losers reload to return the identical receipt, a conflict, or a stale error
without overwriting the winner. A losing CAS reloads the receipt index before
retrying; no caller supplies a revision.

## Recovery acceptance

If a crash happened after an external acceptance but before admission CAS, the
started journal entry is recovered as `ambiguous` and the checkpoint reports
`reconciliation_required`. It is never inferred to be deferred. A trusted
reconciliation provider can return the closed decision
`accept_deferred` containing only the exact handle. The authenticated decision
itself is authority evidence; the framework does not accept provider IDs, job
IDs, proof/business objects, or an external tool call in the decision.

The controller must hold an active recovery claim, aggregate decisions for the
current model-tool batch, verify exact handle identity, and perform one
all-or-none `accept_deferred_batch` CAS. That CAS changes the matching
`ambiguous` entries to `deferred`, stages a `reconciliation_resolved` audit and
`tool_call_deferred` event for each accepted handle, sets the deferred barrier,
and releases the claim once. It never calls the external tool. Repeating the
same accepted decision while its exact handle is already `deferred` is an
idempotent replay of the existing audit/deferred event identities: it writes no
new revision, does not require a second claim, and never calls the external
tool. A new acceptance still requires the active recovery claim. Missing
authority, a missing recovery claim for a new acceptance, a handle outside the
current batch, or incomplete batch decisions keeps the operation ambiguous and
returns `reconciliation_required`.

## Early callbacks and adapters

A callback may arrive before the worker's admission CAS. If the active journal
entry is still `started` and its handle identity matches exactly,
`resolve_deferred` returns `DeferredResolveDecision.NotAdmitted` with retryable
code `deferred_resolution_not_admitted`; it does not mutate the journal,
receipt index, barrier, status, outbox, or revision. The callback receiver must
durably retain the exact result and retry until the admission CAS creates the
deferred journal entry. An `ambiguous` entry is not an early callback: it stays
under `reconciliation_required` and must use the reconciliation path. A
different handle is stale only when no retained receipt and no active matching
journal identity exists.

Remote CI callbacks, transcoding workers, MCP adapters, and other transport
bridges carry only the closed handle and definitive result. They must preserve
the result across `not_admitted`, retry the same public call, and never invent a
provider/job/proof field or call an external tool again. The remote adapter's
retry queue is its durability obligation; the framework index begins only at
the successful admission/resolution CAS.

## Distributed and App Server projection

The worker response wire is unchanged (`vv-agent.distributed-worker-response.v3`).
Admission uses the existing `pending` response: no cycle commit and no response
result were returned by this delivery attempt. The nonblocking driver reads
the authoritative checkpoint and returns `wait(reason=deferred_pending)` while
the barrier is non-empty. This is not host interaction, reconciliation, or a
terminal result. Once the last receipt releases the barrier, resolution returns
`DeferredResolveDecision.AppliedReady(receipt)`; the host reuses the retained previous envelope and
pending observation with the existing driver `advance`, or the
running-checkpoint reconciler performs that existing dispatch. Nothing polls or
waits for a worker, and no worker variant or scheduler state is added.

Public `AgentResult`/App Server projection maps `AgentStatus.deferred` to a
non-terminal interrupted/deferred-pending view: `turnStatus=interrupted`,
`waitReason=deferred_pending`, no completion reason, and no error. The resume
operation remains available. It must not report a terminal completed or failed
turn merely because the worker returned `pending`.

The canonical shape, invalid cases, receipt vectors, batch state transitions,
and producer evidence are frozen in `fixtures/deferred_tool.json`.
For `claimed_checkpoint_resolution_case`, each language must run its real
resolver producer against the exact active deferred handle while the
checkpoint claim is non-null. The producer evidence must show the exact typed
error `deferred_checkpoint_claimed`, zero journal/receipt/barrier/outbox/revision
writes, and no `DeferredResolveDecision` variant; fixture labels alone do not
satisfy this requirement.
