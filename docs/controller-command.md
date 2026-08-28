# Durable Controller Command Admission

Contract `8.1.0` defines one task-neutral, closed admission seam for durable
control of an in-progress distributed run. The deep module owns checkpoint
fences, state precedence, idempotency, SQLite/Redis CAS, receipts, and wake
recovery. Callers do not provide storage internals.

Two boundaries remain independent:

- `resolve_deferred(handle, result)` resolves a deferred effect and its
  receipt-first barrier. A deferred checkpoint cannot be changed by a
  controller command.
- terminal continuation creates a successor run. `wait_user` remains the
  existing terminal `ask_user` result; no controller command changes it.

## Closed command wire

The command discriminator is `vv-agent.controller-command.v1`. Its exact top
level fields are `schema_version`, `command_id`, `command_digest`, `handle`,
`resume_attempt`, `expected_revision`, and `command`. `handle` is exactly
`{checkpoint_key, run_id, trace_id}`. Unknown, omitted, null, or transport
fields are rejected before a store write.

`command_digest` is lowercase SHA-256 of the RFC 8785 canonical UTF-8 bytes of
the complete request with `command_digest` removed. `command_id`, each handle
identity, and each command identity string are capped at 512 UTF-8 bytes
(`request_digest` is a 64-byte lowercase SHA-256). For the App Server adapter,
the global command id is derived from `(threadId, turnId, actionId)` rather
than copied from the client action id. Its exact preimage is
`UTF8("vv-agent.controller-command-id.v1") || 0x00 || uint64_be(length(JCS_UTF8(payload))) || JCS_UTF8(payload)`,
where the closed payload is
`{schema_version, thread_id, turn_id, action_id}` with schema version
`vv-agent.controller-command-id.v1`; SHA-256 is emitted as 64 lowercase
hexadecimal bytes. The length prefix counts payload UTF-8 bytes. The action id
is stable only within the exact `(threadId, turnId)` scope, while the derived
command id is the global receipt/index key. The command id is stable across
transport retries and is the idempotency key.

`command` is a closed union with exactly these five variants:

| Variant | Exact payload | Effect |
| --- | --- | --- |
| `host_interaction_response` | `kind`, `interaction_id`, `logical_cycle`, `operation_id`, `tool_call_id`, `request_digest`, `response` | Respond to the exact persisted host interaction and wake same logical cycle. |
| `suspend` | `kind` | Persist a resumable suspension; it never wakes a worker. |
| `resume` | `kind` | Restore the persisted origin and wake same logical cycle; it accepts no new input. |
| `cancel` | `kind` | Write the cancelled terminal only after ambiguity/deferred/claim precedence. It never wakes a worker. |
| `abort` | `kind` | Only `reconciliation_required` may be operator-aborted; preserve the ambiguous journal. It never wakes a worker. |

The host response fields bind `checkpoint_key`, `run_id`, `trace_id`,
`resume_attempt`, `expected_revision`, `logical_cycle`, `interaction_id`,
`operation_id`, `tool_call_id`, and `request_digest`. Its response is a closed
user message with only `role=user` and `content`.

`cancel` is a terminal failed projection with
`terminal_result.completion_reason=cancelled`; its event outbox uses the
registered RunEvent v4 `run_cancelled` event (alongside `run_state_changed`),
not `run_failed`.

The wire has no `begin_host_interaction` variant. Framework code that needs a
non-terminal interaction uses the typed producer below; application code never
pretends that producer admission is a controller command.

## Framework-only host interaction producer

`HostInteractionRequest` (`vv-agent.host-interaction-request.v1`) has exactly
`schema_version`, `interaction_id`, `logical_cycle`, `operation_id`,
`tool_call_id`, `request_digest`, and a non-empty UTF-8 `prompt`.
`HostInteractionOutcome` (`vv-agent.host-interaction-outcome.v1`) has exactly
`schema_version`, `interaction_id`, `logical_cycle`, `checkpoint_revision`,
`status`, `outbox_state`, `record_id`, `notification_id`,
`notification_payload_digest`, `notification_outbox_action`, and
`notification_outbox_destination`.
The producer returns `outbox_state=pending`; it never reports notification
delivery from inside the admission transaction.

The producer must hold the active worker claim. In one checkpoint CAS it:

1. verifies `logical_cycle=claimed_cycle=cycle_index+1` and all operation/tool
   identity;
2. writes `status=host_interaction`, the complete strict
   `active_host_interaction` request (including the credential-redacted
   prompt), an independent `host_interaction_record`, the interaction event
   marker, and a UI notification outbox row;
3. clears `claim_token`, `claimed_cycle`, and `lease_expires_at_ms`, and bumps
   the revision.

The claim release is part of that CAS. Provider calls, model calls, callbacks,
and queue publication occur after commit. The producer notification is not a
worker wake. A crash reloads the persisted request, interaction record, and
notification outbox before replaying. The producer accepts no checkpoint/run
fence, credential, locator, or secret from its caller. Repeating the same
interaction identity plus request digest after claim release returns a
zero-write replay; a different digest or binding is a conflict.

The producer admission transaction is deliberately scoped: it contains the
checkpoint active interaction, full interaction record,
`host_interaction_requested` RunEvent outbox row, UI notification outbox row,
claim release, and checkpoint revision. It does not contain a controller
command receipt, a recovery wake, or any notification claim, delivery, or
reconciliation lifecycle.

The UI notification is a separate durable outbox row, not a controller receipt
or recovery wake. Its strict sanitized payload includes
`wait_reason=host_interaction` and is delivered through `thread/status` and
`thread/status/changed`; it has its own stable `notification_id`, RFC 8785
payload digest, pending/claimed/delivered/ambiguous/aborted state,
owner-attempt lease CAS, and reaper. Delivery is at-least-once: an uncertain
callback is ambiguous, and observers must deduplicate by `notification_id` plus
payload digest. `reconcile_host_interaction_notification` is the only
ambiguity resolver: `delivered` records observer confirmation, `retry` returns
the row to pending with the same identity and digest, and `abort` records an
explicit terminal abort reason. Pending or expired claimed rows may be retried
by the reaper; ambiguous rows are routed to reconciliation and are never
blind-retried. A same-id same-digest replay is zero-write; a different digest
is `notification_conflict`. A later suspend emits a separate complete
`run_state_changed` notification with `wait_reason=suspended`; it never
mutates the host-interaction notification.

`HostInteractionRequest.prompt` is a closed credential-redacted string capped
at 65,536 UTF-8 bytes. The strict codec rejects credentials, external
locators, transport metadata, unknown fields, and over-limit content before
the CAS. The event is canonical RunEvent v4 `host_interaction_requested` and
the producer outbox action is `host_interaction_notification` to the observer,
never `recovery_dispatch`.

## Checkpoint state and cycle terminology

The v8 checkpoint discriminator is `vv-agent.checkpoint.v8`; no v7 reader,
namespace probe, or migration fallback exists. A checkpoint always persists
the complete strict `active_host_interaction` request (including prompt and
schema discriminator) and `suspended_origin`, both closed objects or null:

- `host_interaction` requires the active identity object and null origin;
- `suspended` requires null active identity and a `{status,
  active_host_interaction}` origin object. Resuming a running origin wakes the
  worker; resuming a host-interaction origin without a resolved response only
  restores the wait. A pending resolved response changes that resume into one
  recovery wake;
- every other state requires both null.

`cycle_index` means the last committed cycle. A live claim names
`claimed_cycle=cycle_index+1`. `logical_cycle` is that same in-flight cycle
identity after the producer releases the claim. A response or resume preserves
`cycle_index` and reacquires the same logical cycle; it does not create a new
cycle or use the ambiguous phrase “same cycle” without this distinction.

The states are `pending`, `running`, `host_interaction`, `suspended`,
`deferred`, `reconciliation_required`, `wait_user`, `completed`, `failed`,
and `max_cycles`. Host interaction and suspended are non-terminal.

## Admission and receipt CAS

`DistributedBackend.resolve_controller_command(command)` is the public driver
seam. The handle is embedded in the closed command envelope; it is not a
duplicate parameter. The method delegates to the machine-checkable store API
`CheckpointStore.admit_controller_command(command)`, returning a closed
`ControllerCommandResolution` containing a receipt and a wake/no-wake
decision. Controller response/admission executes one immediate SQLite
transaction (or equivalent Redis CAS):

1. strict-decode and recompute the digest;
2. replay the retained command id, or reject a different digest as conflict;
3. load the authoritative checkpoint and compare every handle/fence;
4. apply precedence and the variant state rule;
5. write checkpoint state, event outbox, receipt, recovery wake outbox, and—when
   this is a host response—the full resolved interaction record together;
6. commit, then publish the wake.

That controller response/admission transaction contains the checkpoint state,
full resolved interaction record when responding, controller command receipt,
canonical event outbox row, and recovery wake outbox row. It excludes every UI
notification claim, delivery, and reconciliation transition. Those notification
lifecycle operations are independent transactions over the notification row.

The recovery worker has a separate machine-checkable public seam,
`DistributedBackend.claim_and_consume_host_interaction_response(envelope)`,
backed by `CheckpointStore.claim_and_consume_host_interaction_response(envelope)`.
Its envelope carries the checkpoint/record identity, `claim_mode=recovery`, the
authoritative pre-claim `resume_attempt`, and admission revision; there is no
duplicate handle parameter. Ordinary advance/continue cannot claim either
resolved state directly.

For a host response this commit is the admission snapshot at
`admission_revision = expected_revision + 1` (8 -> 9 is an example): the record
is `resolved_pending`, the complete response and command receipt are durable,
and the recovery wake is pending. It does not write
`host_interaction_response_consumed`, `consumed_revision`, or an injected model
message. `resolved_pending` and `resolved_claimed` are hard recovery barriers;
ordinary continue/claim rejects or routes to the dedicated
`claim_and_consume_host_interaction_response(envelope)` operation. That
operation locks the checkpoint and record together, validates every fence,
obtains the checkpoint execution claim with `claimed_cycle=cycle_index+1`,
performs the transient `resolved_claimed` phase, injects the exact response,
appends the complete RunEvent v4 `host_interaction_response_consumed`, marks
the record consumed, increments to
`consume_revision = admission_revision + 1` (9 -> 10 is an example), releases
the record claim, and retains the checkpoint execution claim for the next
model/tool step in the same transaction. Model/tool execution is allowed only
after that CAS commits. A crash before commit rolls back both claims and the
injection; a crash after commit replays the consumed marker under the retained
claim without a second injection. The successful recovery claim increments
`resume_attempt` exactly once (2 -> 3 in the canonical example); the
`host_interaction_response_consumed` event and next recovery envelope carry 3.
Stale, failed, and consumed-replay paths preserve their authoritative value.
No durable record-only claim exists.

The `ControllerCommandReceipt` is a framework-public closed wire. It includes the
command identity, resulting revision/status, and outbox action/destination,
state, and attempt. `recovery_dispatch` to `distributed_advance` is created
only for response and resume. Suspend, cancel, and abort use
`outbox_action=none`, `outbox_destination=null`, and do not enqueue a worker.
The App Server never returns this framework receipt directly; it projects only
the sanitized public fields `actionId`, `accepted`, `status`, and `waitReason`.

Outbox rows have `pending`, `claimed`, `delivered`, or `ambiguous` state plus a
stable `outbox_id`, owner token, lease, attempt, delivery timestamp, and last
error. Claim and completion are CAS-fenced by owner token and attempt. A
reaper retries pending or expired claimed rows with the same `command_id`;
uncertain external publication becomes `ambiguous` and is reconciled rather
than blindly duplicated. A byte-identical replay returns the retained receipt,
does not increment revision, and does not create a second wake.

Errors are strict and observable: `controller_command_digest_invalid`,
`controller_command_conflict`, `controller_command_stale`,
`controller_command_claim_active`, `controller_command_invalid_state`,
`controller_command_deferred_pending`,
`controller_command_ambiguity_requires_reconciliation`, and
`controller_command_terminal`. The framework producer additionally rejects
`host_interaction_conflict`, `host_interaction_fields_invalid`,
`host_interaction_content_too_large`, and `host_interaction_response_missing`.

Precedence is: committed terminal, live claim, unresolved ambiguity,
unresolved deferred barrier, command state rule, ordinary cancellation.

## Worker observation and wake recovery

`vv-agent.distributed-worker-response.v3` remains unchanged. `pending` means
only that this delivery returned no committed observation/result; it is not an
authoritative transition. The driver reads the checkpoint once and maps the
authoritative status to separate `deferred`, `host_interaction`,
`suspended`, or `reconciliation_required` wait cases. It does not fabricate a
run event, poll, sleep, or call a provider to discover command status.

An applied response or eligible resume receipt yields one
`wake_after_controller_command` decision with recovery claim mode and the
retained `logical_cycle`. The response admission snapshot is
`admission_revision=expected_revision+1` (8 -> 9 is an example):
`resolved_pending` plus a full response record, receipt, and recovery wake;
there is no consumed event or marker yet. The recovery worker calls the
dedicated combined operation with the admission revision fence. It obtains a
checkpoint execution claim and record phase together, injects the exact
message once, appends the complete RunEvent v4
`host_interaction_response_consumed`, and commits
`consume_revision=admission_revision+1` before any model/tool operation. The
record claim is released while the checkpoint execution claim remains held
until the next progress CAS. The consumed marker is retained through the next
cycle commit or terminal acknowledgement. A crash before commit rolls back to
`resolved_pending`; a crash/replay after commit performs no second injection.
Deferred resolution
uses its own resolver and wake protocol; terminal continuation uses its own
successor protocol.

A response submitted while the interaction is held in a suspended
`host_interaction` origin is admitted into the full interaction record but
keeps the checkpoint suspended and emits no worker wake. The subsequent
`resume` is the single recovery wake. A suspended `running` origin resumes
directly with a wake; a host origin with no response remains a wait.

## App Server boundary

The App Server exposes a narrow `turn/action` adapter with `threadId`,
`turnId`, a stable retry-safe `actionId` (each identity capped at 512 UTF-8
bytes), and a closed public action
(`respond`, `suspend`, `resume`, `cancel`, or `abort`). It derives
checkpoint/run/fence/command/digest/operation identity
from server state. It does not accept `checkpointKey`, an internal command,
digest, revision, run id, trace id, or operation arguments. Its public receipt
is sanitized to `actionId`, `accepted`, `status`, and `waitReason`; lease,
command, digest, checkpoint, and revision fields never cross this boundary.
`respond` accepts only `{kind, message:{role:"user", content}}`, with a
65,536-byte UTF-8 content cap and no unknown fields. The server validates
`actionId`, then derives `command_id` from the exact `(threadId, turnId,
actionId)` tuple using the length-prefixed JCS/SHA-256 algorithm above. A
replay in the same scope reuses the command id; the same action id in another
thread or turn derives a different command id. The server derives the command
digest from the closed command plus authoritative turn binding. The projected
host prompt is sanitized credential-redacted text; its
operation/tool/checkpoint/lease/request digest fields are never public.
`turn/resume` still disallows new input, and `ask_user` remains terminal.

## SQLite, Redis, and fault evidence

The canonical `checkpoints` table stores the complete
`active_host_interaction` request and `suspended_origin`.
`host_interaction_records` independently stores the full request and full
resolved response, response/command digests, claim lease/attempt, and the
consumed marker. `controller_command_receipts` stores the closed command and
receipt plus `outbox_id`, action, destination, state, claim token, lease,
attempt, delivery timestamp, and retry error. Checkpoint revision, event
outbox, interaction record, receipt, and controller wake outbox are one
controller-response-admission transaction and cascade on deletion. Producer
admission has its own transaction containing the checkpoint, interaction
record, request event, UI notification row, claim release, and revision; it
deliberately does not create a controller receipt or recovery wake. The
independent
`host_interaction_notification_outbox` stores only the strict sanitized UI
payload and its stable id/digest, with its own claim/lease/delivery/retry/
reconcile protocol. Delivery is at-least-once and observer deduplication is
required; an uncertain callback is ambiguous, not exactly-once. The reaper
routes ambiguous rows to explicit delivered/retry/abort reconciliation and
never blind-retries them. It is never reused as a recovery wake. SQLite only enforces scalar
lifecycle relations; strict v8 codec validation owns nested JSON shape and
UTF-8/digest limits.
Redis must expose equivalent replay, conflict, stale, lease, and ambiguity
semantics.

Canonical fixtures cover Unicode/number RFC 8785 vectors; missing/old/unknown
checkpoint and command discriminators; stale run/trace/resume/revision and
interaction/operation/tool/request identity; active-claim producer races;
deferred, external-effect, cancel, terminal, and wake races; replay after a
revision advance; and crash before commit, after CAS before enqueue, and after
uncertain enqueue. Python and Rust implementation evidence remains
`pending-adoption` until both strict readers, real CAS tests, and cross-runtime
SQLite tests pass.
