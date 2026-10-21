# Session kernel

Contract 27.0.0 defines one execution authority: the ordered session log and inbox.
MUST, MUST NOT and SHOULD are normative. Logical bytes, admission, authenticity,
fencing and delivery are public requirements. SQL tables, DDL, Redis keys, store
constructors, method signatures, connection ownership and thread layout are out of
scope. There is one current wire, with no historical decoder.

## Types and envelopes

| Notation | Exact meaning |
| --- | --- |
| `S`, `T` | JSON string; `T` has `minLength=1` (not a trim/nonblank requirement) |
| `N`, `P` | Integer ≥0 / ≥1, within I-JSON safe integer range; boolean and `1.0` are rejected as integer fields |
| `B`, `H` | Boolean; exactly 64 lowercase hexadecimal characters (full-match `^[0-9a-f]{64}$`; no trailing newline) |
| `J`, `V` | Explicit opaque JSON object / any I-JSON value, including null |
| `X?` | Optional member, omitted when absent; null is allowed only if its type permits it |
| `X\|null`, `[X]` | Required nullable value; array of X, empty permitted |
| `{...}` | Closed object; every listed member required unless marked `?` |

All listed envelopes and typed nested objects MUST reject unknown members.
Only `J`/`V` locations are extension/content boundaries; their contents MUST NOT
override kernel control fields. Array order is significant. Nonempty strings
and array elements are not implicitly normalized, trimmed, sorted or deduplicated.

| Envelope | Required fields (no other fields) |
| --- | --- |
| Record | `schema_version:integer const 1`, `record_id:T`, `kind:record enum`, `session_id:T`, `turn_id:T\|null`, `operation_id:T\|null`, `attempt:P\|null`, `payload:J` selected by kind |
| InboxItem | `schema_version:integer const 3`, `input_id:T`, `kind:inbox enum`, `target_turn_id:T\|null`, `generation:N\|null`, `available_ms:N`, `payload:J` selected by kind |

The logical record has no top-level sequence, receiving time, writer epoch or
digest member. Storage supplies ordered positions, timestamps and integrity
digests separately. `op_started.payload.epoch` is retained dispatch evidence,
not that excluded storage-envelope epoch. Nullable fields MUST be present.
`operation_id` and `attempt` MUST both be non-null exactly for `op_*` records and
null otherwise. `session_created.turn_id` MUST be null. All other record kinds
require a turn except `input_applied` and `usage_observed`, which permit null.

## Record payloads

| Kind | Closed payload fields |
| --- | --- |
| `session_created` | `principal:T`, `workspace:T`, `parent_session_id:T\|null`, `parent_operation_id:T\|null`, `attributes:J` |
| `turn_started` | `input_ids:[T]`, `definition:J`, `definition_digest:H`, `handler_version:T`, `budget:J`, `binding:T\|null`, `generation:N` |
| `input_applied` | `input:InboxItem`, `input_digest:H`, `disposition:applied/rejected/noop/queued`, `reason:T\|null`, `target_operation_id:T\|null`, `target_wait_id:T\|null`, `position:T`, `model_binding?:ModelBinding` |
| `op_planned` | `op_kind:model/tool/interaction`, `purpose:primary/compaction/session_memory/output_repair\|null`, `request:J`, `request_digest:H`, `context_version:T`, `dependencies:[T]`, `tool:J\|null`, `idempotency_key:T\|null`, `budget_admission:J`, `not_before_ms:N\|null`, `provider_binding:T\|null`, `consumed_unknowns:[ResultId]` |
| `op_prepared` | `request:J`, `request_digest:H`, `op_kind:tool/interaction`, `tool:J`, `provider_binding:T\|null`, `idempotency_key:T\|null`, `hook_result:V`, `shared_state:J` |
| `turn_parked` | `interaction_id:T`, `question:S`, `source_operation_id:T`, `source_attempt:P` |
| `op_started` | `dispatch_id:T`, `authorization_version:T`, `epoch:P`, `mode:sync/provider/managed`, `endpoint_id?:T` |
| `op_parked` | `phase:before_dispatch/after_dispatch`, `handle:Handle`, `poll_at_ms:N\|null`, `deadline_ms:N\|null`, `interaction_result?:J`, `delegation?:Delegation` |
| `op_completed` | `result:V`, `result_digest:H`, `usage:J`, `shared_state:J\|null`, `evidence:[T]`, `execution_started:B`, `context:normal/correction/audit`, `request_digest:H`, `provider_binding:T\|null` |
| `op_unknown` | `reason:T`, `dispatch_evidence:[T]`, `observation:J`, `retry:retry/stop/manual`, `retry_at_ms:N\|null`, `duplicate_cost_risk:B`, `measurement_missing:B` |
| `context_compacted` | `source_digest:H`, `prefix_ids:[T]`, `tail_ids:[T]`, `mode:micro/summary/emergency`, `summary_operation_id:T\|null`, `replacement:[V]`, `evidence_manifest:J`, `micro_usage?:{archived_count:N,reclaimed_tokens:N,artifact_failure_count:N}` |
| `boundary_recorded` | `boundary_id:T`, `stage:boundary enum`, `source_operation_id:T\|null`, `source_digest:H\|null`, `data:J` selected by stage |
| `usage_observed` | `meter_id:T`, `observation:P`, `mode:cumulative/correction`, `usage:J`, `source:T` |
| `turn_ended` | `status:completed/failed/cancelled/aborted`, `reason:T\|null`, `result:V`, `adopted_results:[ResultId]`, `budget:J`, `unconfirmed_operations:[T]` |

`ResultId = {operation_id:T, attempt:P}`. `op_planned.purpose` MUST be non-null
exactly when `op_kind=model`. Payload validation alone does not impose a
model-request, ToolExecutionResult or budget schema on `J`/`V`; producer/consumer
validation and fold rules supply their existing typed boundaries.

## Inbox payloads

| Kind | Closed payload fields |
| --- | --- |
| `user` | `content:V` |
| `steer` | `content:V` |
| `follow_up` | `content:V` |
| `model_selection` | `selection:ModelSelection\|null` |
| `provider_result` | `operation_id:T`, `attempt:P`, `request_digest:H`, `provider_binding:T\|null`, `result:V`, `usage:J`, `evidence:[T]` |
| `approval_answer` | `operation_id:T`, `attempt:P`, `request_id:T`, `request_digest:H`, `decision:approve/deny/allow_session/timeout`, `scope:[T]`, `reason?:S`, `metadata?:J` |
| `child_result` | `session_id:T`, `turn_id:T`, `operation_id:T`, `attempt:P`, `result:V`, `status:completed/failed/cancelled/aborted`, `terminal_seq:P`, `terminal_digest:H` |
| `control` | `action:close/archive/suspend/resume/cancel/abort` |
| `provider_evidence` | `operation_id:T`, `attempt:P`, `request_digest:H`, `handle:Handle` |

User content remains opaque at the generic boundary. Kernel reply producers currently use
`{operation_id,interaction_id,text}` for ask_user and `{interaction_id,text}` for
turn-level waits; the target turn/generation is supplied in the envelope.

`provider_result.usage` MUST be a required JSON object, just like
`op_completed.usage`; `{}` means no observed usage. Missing, null, non-object
usage and unknown payload members MUST reject. Authentication MUST cover usage
as well as result and the attempt identity. An authenticated result MUST retain
usage unchanged in `op_completed.usage`, including normal, correction and audit
completions. Synchronous model returns and provider submit/query Definitive
outcomes MUST retain the same upstream usage bytes. Hosts MUST bill from the
canonical typed usage projections, including late audit attempts: the provider
call happened even when its result cannot affect execution. They MUST NOT decode
usage from opaque `result` content. Re-delivery for an already completed attempt
with a new input ID is a noop only when both result and usage have identical
RFC8785 bytes; differing result or usage MUST be rejected as a result conflict.
Replay MUST NOT create another completion or bill the attempt again.

## Nested values and attributes

| Type / location | Fields |
| --- | --- |
| Provider Handle | `kind:const provider`, `provider:T`, `job_id:T`, `operation_id:T`, `attempt:P`, `request_digest:H`, `evidence:T`, `query_ref:T\|null`, `cancel_ref:T\|null` |
| Approval Handle | `kind:const approval`, `request_id:T`, `request_digest:H`, `scope:[T]` |
| User Handle | `kind:const user`, `interaction_id:T`, `question:T` |
| Child Handle | `kind:const child`, `session_id:T`, `turn_id:T`, `generation:N`, `background:B`, `delivery_target:DeliveryTarget`, `siblings?:[ChildIdentity]` |
| DeliveryTarget | `session_id:T`, `turn_id:T`, `generation:N`, `operation_id:T`, `attempt:P` |
| ChildIdentity | `session_id:T`, `turn_id:T`, `generation:N` |
| Delegation | `mode:configured/agent_as_tool/background_task/handoff`, `agent_name:T`, `handoff_count:N`, `max_handoffs:N`, `metadata:J` |
| `attributes.seed` | `messages:[Message JSON]`, `shared_state:J`; both required, empty allowed |
| `attributes.app_server` | `agent_key:S`, `cwd:S\|null`, `metadata:J` |
| `attributes.child_admission` | `mode:configured/agent_as_tool/background_task/handoff`, `selector:T`, `definition:J`, `definition_digest:H`, `budget:J`, `handler_version:T`, `sub_config:SubConfig\|null`, `exclude_files_pattern:T\|null`, `handoff_count:N`, `max_handoffs:N`, `handoff_metadata:J` |
| SubConfig | `model:T`, `description:S`, `backend:S\|null`, `system_prompt:S\|null`, `max_cycles:N`, `session_memory_enabled:B`, `exclude_tools:[S]`, `metadata:J`, `denied_side_effects:[T]`, `denied_capability_tags:[T]`, `deny_terminal_tools:B`, `denied_cost_dimensions:[T]` |

Handle is exactly one of its four closed variants. `attributes` remains an explicit
extension object; `app_server`, `child_admission` and `seed` have additional closed codec validation. The producer retains `attributes.child_handle`;
the child reducer/authenticator validates that against admission. It MUST NOT be
described as a third codec-validated attributes schema without corresponding work.
The codec permits duplicate `siblings`; the fold MUST reject duplicate member
identities and mismatched creation/delivery targets.

## Boundary stages

| Stage | Closed `data` fields | Observable boundary |
| --- | --- | --- |
| `before_memory` | `messages:[J]`, `shared_state:J` | Retain hook replacement and source digest before compaction |
| `after_cycle` | `action:continue/steer/stop_non_success`, `steering_messages:[T]`, `disallow_tools:[T]`, `stop:{code:T,message:T}\|null`, `shared_state:J`, `error:T\|null` | Retain composed decision before another dispatch |
| `memory_started` | `event:J` | Retain MemoryProvider/lifecycle start observation |
| `memory_completed` | `event:J` | Retain completion and archive statistics |
| `session_memory_saved` | `state:MemoryState` | Structured memory precedes disposable file projection |
| `output_checked` | `status:completed/failed/repair`, `reason:T\|null`, `value:V`, `partial_output?:V` | Retain candidate, repair decision and final validation |
| `budget` | `usage:J`, `exhaustion:J\|null`, `tool_names:[T]` | Retain admission/accounting and exhaustion decision |

`MemoryState = {entries:[MemoryEntry], last_extracted_message_index:integer≥-1,
tokens_at_last_extraction:N, initialized:B}`.
`MemoryEntry = {category:user_intent/decision/file_change/error_fix/key_fact,
content:T, source_cycle:N, importance:integer in 1..10}`. Both are closed.
The generic codec does not replace the strict Message, event or budget readers
inside opaque boundary values.

## Identities, bytes and rejection

Let `D(x) = lowercase_hex(SHA256(RFC8785_JCS_UTF8(x)))`. Store sequence and
receiving time MUST NOT participate in logical identity or logical digest.
Replay compares canonical bytes, not Python equality (`true` differs from `1`).
Readers accept valid noncanonical JSON, validate it and retain its JCS encoding;
whitespace/key-order differences alone are not a conflict. Stored logical bytes
and any separately retained storage digest MUST agree.

| Kind | Exact `record_id` |
| --- | --- |
| `session_created` | `session/{session_id}/created` |
| `turn_started`, `turn_ended` | `turn/{turn_id}/started`, `turn/{turn_id}/ended` |
| `turn_parked` | `turn/{turn_id}/wait/{interaction_id}` |
| `input_applied` | `input/{input.input_id}/applied` |
| `op_planned`, `op_prepared`, `op_started`, `op_unknown` | `op/{operation_id}/{attempt}/planned`, `/prepared`, `/started`, `/unknown` |
| `op_parked` | `op/{operation_id}/{attempt}/parked/{phase}` |
| `op_completed` | `op/{operation_id}/{attempt}/result` |
| `boundary_recorded` | `turn/{turn_id}/boundary/{stage}/{boundary_id}` |
| `context_compacted` | `compact/{source_digest}/{mode}` when summary operation is null; otherwise `compact/{source_digest}/{mode}/{summary_operation_id}` |
| `usage_observed` | `usage/{meter_id}/{observation}` |

Identity construction uses direct string interpolation, with no escaping of delimiters.
Record IDs MUST match their semantic positions; they are session-scoped.
Caller-owned input and commit identities MUST be stable source/transaction IDs;
retries MUST NOT generate new ones. Creation reserves commit ID `session/create`.
The producer derives default turns as `{session_id}/turn/{input_id}`;
child initial input is `start`. Primary operations use
`{turn_id}/model/primary/{number}`, tools use
`{model_operation_id}/attempt/{model_attempt}/tool/{index}` (zero-based index),
and call/dispatch IDs use `{operation_id}/{attempt}`. New attempts retain the
operation ID and increment attempt; they MUST NOT reuse call IDs.
Child completion input ID is `child/{child_session_id}/{terminal_record_id}`.

| Digest | Covered value / validation |
| --- | --- |
| Record / InboxItem digest | Entire canonical logical envelope including payload and version |
| `turn_started.definition_digest` | `D(definition)`; codec compares, including child admission's definition digest |
| `op_planned` / `op_prepared.request_digest` | `D(request)`; codec compares the exact frozen/prepared request |
| `op_completed.result_digest` | `D(result)`; codec compares; usage/evidence remain covered by whole-record digest |
| `input_applied.input_digest` | `D(input)`; codec also validates the nested kind-specific inbox payload |
| `op_completed.request_digest`, provider/approval/input request digests | Binding/equality against the appropriate plan/preparation/handle; not a digest of completion payload |
| Compaction / boundary source digests | Source context and boundary evidence checked by fold/acceptance, not by the generic embedded-digest helper |
| `child_result.terminal_digest` | Whole original child terminal record; authenticate result/status/position and parent/generation |

JCS MUST use UTF-16 code-unit key ordering, standard string escaping, no Unicode
normalization, finite IEEE-754 numbers and integer values in
`-9007199254740991..9007199254740991`. Lone surrogates, non-string object keys,
nonfinite numbers and non-JSON host objects MUST be rejected at every nested
content boundary. JSON text MUST reject duplicate object members and non-object
envelopes. No version defaulting, historical dispatch or field filling is allowed.
Missing/stale/unknown/malformed versions, unknown kinds/fields/enums, incorrect
nullability, wrong identities and embedded digests MUST fail before append.
Cross-record order, dependencies, request/binding drift, authorization, stale
generation and terminal revival MUST fail at fold/admission, atomically.

## Creation seed and reserved metadata

A creation-time `session_created.attributes.seed` is a closed object with required
`messages` and `shared_state`. Messages use the strict current Message wire.
The seed projects before the first turn's context and initial shared state.
Session history, shared state and queues have no public mutation API after creation;
read-only projections and inbox admission are the current access paths.

Only kernel producers may write `task.metadata.vv_session`. User metadata containing
this reserved key MUST fail at compile time. The object is closed with optional
`host_binding_names:[T]`, `max_handoffs:N`, `handoff_targets:J`,
`input_messages:[Message JSON]`, `memory_initial_state:J`, and
`input_blocked:T`. Frozen multimodal Message values remain distinct from original
surface input. Required binding names are sorted; object references stay host-local.

Request metadata has one closed `vv_session` object with optional
`endpoint_order:[T]`, `endpoint_id:T`, `shared_state:J` and `cycle_index:N`.
Opaque surrounding metadata cannot override canonical fields. `op_completed.usage`
contains measurements only; its separate required-nullable `shared_state` retains
JSON state. Other explicitly opaque J/V locations keep their content boundaries.

## Admission and authority

| Boundary | Requirement |
| --- | --- |
| Input/record/commit replay | Same scoped ID and canonical bytes MUST return original receipt with zero new writes/effects. Different bytes MUST conflict with zero writes. Duplicate record IDs within one append MUST reject, even if equal. Persisted overlap MUST be byte-checked, not reinserted. |
| Commit identity | Ordered records and consumed input IDs define logical transaction content. Empty/all-overlap commits MUST retain original receipt/head. Expected head, inbox watermark and lease are admission conditions, not logical identity. Replay grants no execution authority. |
| Atomic append | Log append, input consumption, reservations and required related admission/projection writes MUST commit or roll back together. Caught validation/conflict errors MUST leave zero partial writes. Receipts inside an outer transaction remain provisional until that transaction commits. |
| Writer lease | A session has one current execution writer. New writes MUST fence owner, epoch, unexpired lease, expected head and any required inbox watermark. Ownership loss MUST prevent stale writes; a new epoch MUST NOT authorize an old owner. |
| External effects | Dispatch follows durable admission and current authorization. Epoch fencing does not stop an already admitted zombie request; only actual provider idempotency can constrain duplicate effects. |
| Consumer cursor | Each named consumer independently retains its acknowledged ordered prefix. A batch MUST retain whole commit boundaries, with inclusive first/last positions. Projection and ACK SHOULD share one host transaction; rollback MUST restore both. |
| Delivery | External sink delivery before ACK is at least once: a crash can duplicate delivery. Stable event/item/record IDs MUST support deduplication. An ACK proves consumption, not successful external notification or business finalization. |
| Scheduling | Wake is a hint. Scanning MUST recover due work, unconsumed/queued inputs, dependency changes and consumer lag, including unprojected terminal records. Consumer work does not require an execution lease. No-deadline user/approval waits and unresolved dependencies MUST NOT spin. |

## Operations, recovery and inputs

| State / input | Requirement |
| --- | --- |
| Planned / prepared | Resume MAY dispatch only after current policy/binding/budget checks. A retained prepared hook result MUST be reused. Frozen denials remain effective even if current policy becomes permissive. |
| Completed | Authentic retained model/tool/summary results MUST be reused; missing dependent tool plans MUST be reconstructed from the receipt, with no new model request. Model receipt, reservation and complete tool plans commit together. |
| Parked | Preserve the exact provider/approval/user/child handle and evidence. Recovery MUST query/reuse it, not repeat submission. Missing evidence references are not proof of provider acceptance. |
| Started, no authentic receipt/acceptance | Recheck inbox watermark before declaring unknown. Unknown MUST preserve dispatch evidence, unavailable measurements and duplicate-cost risk; it MUST NOT be fabricated success or confirmed failure/stop. |
| Model retry/fallback | Freeze endpoint order; one provider/transport attempt per logged attempt (`max_attempts=1`). The operation limit is `max(2, frozen endpoint count)`; fewer than two endpoints permit two attempts. Distinct attempt/call IDs and every attempt's accounting MUST remain visible. Required unavailable metrics can stop fallback. |
| Tool retry | Unknown tools MUST NOT auto-retry unless frozen metadata declares `idempotency=supported` and the actual provider supports that key. Ordinary tools permit one retry (two attempts total). Unsupported/unknown idempotency stops. The key is stable across attempts, currently `{session_id}/{operation_id}`. |
| Output repair | One logged tools-free `output_repair` operation. An unknown repair MUST never be automatically retried. Coercion/repair errors MUST become durable failed results with partial-output evidence. |
| Late result, unknown not consumed | A trusted result MAY be adopted normally. An earlier model receipt can supersede a planned, undispatched retry without inventing a result for that retry. |
| Late result, unknown consumed | Preserve the already delivered unknown message and append a correction, rather than rewrite history. `consumed_unknowns` MUST identify exactly the unknowns frozen into the successor request. |
| Late result, retry dispatched / turn ended / generation stale | Earlier model result is audit-only after retry dispatch. Ended/cancelled turns MUST NOT revive. Host adapters MUST reject stale business generations; authentic late evidence can remain audit-only. |
| Provider evidence | Host/provider authentication MUST precede application. Bind operation, attempt, request digest, provider binding and retained handle/evidence. A digest/evidence string alone is not proof of authenticity. |
| Steer / follow-up | Steer waits until the active frozen batch/retry closes and enters the next new request. Follow-up queues a new turn after the active turn ends. End admission MUST recheck inbox watermark so racing input is not lost. |
| User wait / approval | Reply to the exact interaction/turn/generation. Equal answer replays are noop; conflicting bytes reject even after completion. Approval binds prepared arguments and scope, uses an absolute deadline including provider-decision time, and derives allow_session only from applied answers. |
| Suspend / cancel / abort | Suspend preserves waits and permits durable incoming results without dispatch. Resume restores the same turn. Cancel/abort close undispatched work explicitly and dispatched work with confirmed-stop or unknown evidence; keep unconfirmed operation identities in the terminal. |
| Background Bash | Reattach only through the retained original owner and live process manager. OS/manager restart or missing handle is unknown; PID guessing MUST NOT authorize adoption or a confirmed stop. |

## Boundaries, budgets and compaction

| Area | Requirement |
| --- | --- |
| Hooks/decisions | Committed `boundary_recorded` / operation receipts MUST prevent callback replay. Interruption before their commit permits another invocation: hooks are at least once, not exactly once. JSON state and composed denials/steering MUST survive restart. |
| Tool budget | Reserve the entire ordered model batch atomically with model receipt and plans. Any total/per-name shortfall rejects the whole batch with zero effects. Reserved calls subsequently skipped by FINISH/wait still count. Replay/retry MUST NOT reserve twice; dynamic wall/host checks still apply per dispatch. |
| Token budget | Count primary, compaction, session_memory and output_repair attempts, including failures/unknown usage. Unknown counts MUST remain unavailable, never zero. Limits and unavailable policies remain frozen per turn. |
| Wall/host budget | Count observed active intervals, exclude parked intervals, and mark lost active intervals unavailable. MUST NOT infer them from process downtime. Strict policy stops. Host meter failures, unit/currency mismatch, decreasing readings and unavailable latches survive reconstruction. |
| Logical cycles | Summary/extraction/repair and prompt-too-long recovery do not spend extra primary cycles. Adopted receipts, rather than re-admission, determine accounting. |
| Compaction | Preserve complete-prefix / atomic-tail, images, reasoning, call/result association, normalized effective summary, artifacts and cursors. Micro replacement requires verified artifact persistence. Failed/rejected summary keeps history. No second pruner or automatic restoration. |
| Compaction receipt | Log summary as tools-free `purpose=compaction`; reuse saved receipts, including rejected same-source/mode/tail requests. Verify source/prefix/tail, acceptance, exact replacement and evidence manifest before applying `context_compacted`. Raw records remain immutable. |
| Prompt-too-long | Retain definitive failed attempt; first forced summary uses configured tail, subsequent emergency retries shrink it. Preserve the three-retry recovery limit and end with CompactionExhaustedError without silent history loss.  |
| Session Memory | Disabled unless explicitly enabled. Log tools-free extraction and structured state before file projection. The file is disposable and MUST be recoverable before next-turn compile/reload. Accepted compaction notification uses its record ID and consumer deduplication, not a raw summary receipt. |



Child delivery and projections are defined in [session consumers](session-consumers.md);
JSON-RPC behavior is defined below.

## App Server

JSON-RPC 2.0 uses initialized `protocolVersion=v3`. Objects are closed.
Thread identity equals session identity; turnId equals runId. The session log
and inbox own execution; connections are subscribers, never execution owners.
The host authenticates connections. Before every thread read or action, including
creation and listing, the processor calls `authorize(connection_id, method, params)`.
A refusal returns -32027 `permission_denied` without reading or changing the thread.
The local single-user DefaultAppServerHost allows everything; distributed hosts
MUST implement the hook and apply their account and thread permissions.

### Submission and control

`thread/start` requires `inputId`, with optional agentKey, cwd and metadata.
The host supplies a globally unique stable inputId; it is also the threadId.
For creation authorization, the host maps params.inputId directly to threadId.
Creation uses the atomic session creation receipt, without listing sessions.
Client inputId and actionId values match `^[A-Za-z0-9._:-]{1,128}$` (ASCII,
no slash or whitespace). Internal session/input identities contain `/` and cannot
be submitted as client identities. Invalid client IDs return -32602 before admission.
The result has threadId, agentKey, cwd, current status, accepted and replayed.
Identical creation retries return the creation receipt with current status. Changed creation bytes
return -32024 `submission_conflict`.

`turn/start` requires threadId, inputId, expectedTurnId (null for the first
turn, otherwise the last admitted turn), and input; metadata is optional.
`turn/steer` and `turn/followUp` require threadId, inputId, expectedTurnId and
input. The expected turn must match the active turn for steering and the last
admitted turn for follow-up. Input IDs are session-scoped and stored unchanged
in the inbox. No connection or JSON-RPC request identity enters submission bytes.
Expected turn and submission kind are retained in opaque input content.
Admission and fencing are one store transaction. Identical retries are checked
before current execution state and return the original threadId, turnId, inputId,
inputSeq, accepted=true and replayed=true. Initial receipts use replayed=false.
Changed bytes return -32024 `submission_conflict`; a stale expected turn returns
-32025 `turn_mismatch`. Reconnect and lost replies cannot admit another turn.

`turn/action` retains its strict threadId, turnId, actionId, action shape and
controller command digest algorithm; the inbox ID is `controller/` followed by
that digest, outside the client-ID grammar. Actions are respond (strict user Message),
suspend, resume, cancel and abort. Any authorized connection can submit them.
`turn/interrupt` requires exactly threadId, expectedTurnId and actionId;
it submits durable cancel even without a local handle. Its result is
the turn/action admission receipt. Resume uses durable execution state, preserves
lease fencing and reuses an available local handle. It never requires the
original connection. Terminal resume returns the retained result without driving.
Closed and archived sessions reject execution as before.
All stable submissions, including approval answers, model selections and actions,
return -32024 `submission_conflict` for an identical ID with different bytes.
Each request receives exactly one JSON-RPC response. Failures after an admission
receipt are notifications, never another response for that request.

A non-holder attempts the lease once and schedules an automatic retry
at the observed holder's lease expiry, for root and foreground child sessions.
If the holder renewed or another epoch took over, the retry waits for the new
expiry without acquiring. Record progress does not cancel recovery: that writer
may also die. An acquisition that still fails after expiry emits a typed
error/warning with code lease_retry_exhausted. Embedded hosts call the public
AppServer.wake(thread_id) after an inbox commit or from their scheduler; it is
a trusted host entry point, not a client authorization bypass on the wire.
Child completion delivery wakes the parent after the inbox transaction commits.
Wake and expiry retries use a currently registered local subscriber, or drive
without subscribing when none exists. Approvals then remain durably parked for
approval/resolve from any authorized connection, subject to their retained deadline.
Lease waits use bounded backoff. Local start-or-attach is atomic
per thread; completion clears only its own handle. Lifecycle notifications derive
turn identity from committed records. Every subscribed node observes turn/started
and turn/completed for each turn, including queued follow-ups, through record
tailing or host wake delivery. Notification observers never acquire execution leases.
Each session has its own 50 ms to 1 s idle/error backoff; an observer reads only
due sessions in bounded pages without session-row locks. Transient failures warn
at a bounded rate and keep observing. Projection and transport writes happen
outside store transactions and connection locks. On the last local unsubscribe
or disconnect, discard that session's notification position. A first subscriber
starts at the current head, or immediately before an active turn's start; history
belongs to thread/events/list, not live notifications.

`approval/resolve` accepts threadId, turnId, requestId, decision, optional reason
and metadata from any authorized connection. The server resolves the pending
request to its retained operation, attempt, scope and request digest, and pushes
an approval_answer inbox input. It never accepts caller-selected binding fields.
The original absolute deadline and timeoutDecision remain authoritative.

### Replay

`thread/read` and `thread/resume` return the complete snapshot; afterItemId is
removed. Resume optionally accepts subscribe (default true).
`thread/events/list` requires threadId and limit (integer 1..256), with optional
afterCursor and throughCursor. A cursor is the closed object
`{threadId,seq,offset,recordDigest}`. seq is a positive durable record sequence;
offset is the number of events already consumed in that record (zero is the
boundary before its first event); recordDigest is the SHA-256 of the canonical record bytes.
Several events from one record have distinct offsets and stable event IDs.
The fixed throughCursor is inclusive and defaults to the head record's final
event boundary captured at request start. Return `{events,nextCursor,
throughCursor,more}`. Each event is `{cursor,event}` with the canonical RunEvent
wire. Empty pages still advance nextCursor across non-event records. A page
reads at most limit records and emits at most limit events, plus indexed
projection dependencies and cursor validation reads. It never folds a full log.
The returned throughCursor is reused across pages for a fixed replay window.
Unknown, out-of-range, cross-thread, stale or malformed cursors return -32026
`invalid_cursor`; they never restart replay. Clients deduplicate by event_id and
persist the last cursor. Live deltas are volatile and have no durable cursor;
final durable events/items replace their accumulated display via callId or
toolCallId. App item identity remains `item_{event_id}`.

### Status

AppThread.status, thread/status and thread/status/changed use one projection:
idle, running, provider_running, child_running, user_wait, approval_wait,
retry_backoff, suspended, terminal, archived, closed. Terminal means the last
turn ended and there is no queued next turn; idle means no turn yet.
thread/status and thread/status/changed contain exactly threadId, status, phase,
waitKind (nullable provider/child/user/approval/retry), nextDriveAt (nullable
Unix milliseconds), pendingInteraction (nullable Interaction), unconfirmedCount
and projectionWatermark (last record seq). unconfirmedCount covers only the current
turn (the latest turn when terminal), using its unconfirmed_operations rule.
thread/unsubscribe returns only threadId and subscribed; there is no thread/closed
notification. TurnActionResponse has no waitReason.
Interaction contains exactly
sessionId, turnId, optional prompt, interactionId and approval requestId. Approval has precedence
over user, then child, then provider; suspended and terminal take precedence.
Retry backoff is retained future retry scheduling; provider/child waits are
machine work, never user interruption. Pending interactions may come from a
child. No job handles, credentials, arguments or request digests are exposed.
AppTurn.status remains pending/running/interrupted/completed/failed;
interrupted denotes a parked attempt, and only turn_ended is terminal.

### Resolver and exports

The App Server host supplies a deterministic, non-submitting model resolver
returning client and resolved config for the exact selected model ID. The default
filters its configured backend before matching the resolved model_id, including
the first endpoint's model_id override, and rejects nonempty routes.
Zero or multiple matching entries within that effective backend reject with
model_selection_unresolvable. model/list advertises these same selectable IDs.
The frozen model with empty route always reuses its frozen client/config before
any host hook. CLI and interactive use the same default provider resolver through
SessionDriver; the App Server additionally binds its host hook.
Primary call usage and billing identify the actual retained model/backend.
Record schema 1, inbox schema 3 and SQL schemas are unchanged.

Schema export is self-contained and strict. jsonSchema values are JSON strings;
current JSON/TypeScript bundle names are listed in app_server_observable.json.
InitializeResponse requires v3. Accounting and host interaction wires retain
their current shapes. app_server_protocol.json contains real producer transcripts
and exports; app_server_observable.json inventories their expectations.

## Per-session model selection

`ModelSelection = {model:T, model_settings?:ModelSettings, route:J}` is closed.
ModelSettings uses its existing canonical fields (fixture `model_settings.json`);
reasoning effort belongs in `reasoning:{effort:...}`, not route. Omitted settings
mean empty settings for the new model, with one transport attempt per logged
attempt. The explicitly opaque route carries host routing such as backend_type.
Both target_turn_id and generation MUST be null. Selection targets this session
only; it MUST NOT propagate to child sessions.

The holder MUST consume selections in inbox order at a new-cycle boundary after
the active operation batch and retries close, or while idle. It MUST resolve the
selection without provider submission. Unresolvable/unauthorized selections MUST
be logged rejected with reason `model_selection_unresolvable`, leaving the prior
selection intact. Later valid inputs MUST remain admissible. Latest accepted
selection persists across turns until replaced; null restores the frozen task
model/settings. Input IDs have ordinary identical-byte replay / conflicting-byte
rejection semantics, including after consumption.

Accepted non-null inputs MUST retain `model_binding` on input_applied:
`ModelBinding = {backend:T, model:T, endpoints:[T], context_length:P|null,
max_output_tokens:N|null}`. Each new primary request MUST carry model, route,
canonical model_settings and metadata.vv_session.model_binding. Resolution and
execution MUST use the retained request alone and reject binding drift.
Primary endpoint order MUST match the retained request binding, including retries, rather
than the turn's frozen default endpoints.
Resolver failure after planning uses ordinary model attempt failure/unknown handling.
Retries, recovery, replay, projection and late provider_result MUST preserve the
original plan and accounting identity. Already in-flight work is unaffected.
Compaction/context budgeting MUST follow the selected model capacity and output
reserve; internal summary/extraction models keep their independently frozen routes.
Prompt-too-long recovery retains one receipt/accounting entry per call and does
not spend another logical primary cycle. Events/usage MUST use each plan's model
and backend, including late audit usage, rather than the current selection.

App Server `thread/model/select` params are exactly `{threadId:T,inputId:T,
selection:ModelSelection|null}`; result is exactly `{threadId:T,inputId:T,
accepted:true}`. It submits the same inbox input, with inputId unchanged. This is
admission acknowledgement, not selection validation; conflicting inputId returns
-32024. Schema exports retain closed params and the current ModelSettings shape.
Canonical evidence: `session_semantics.json` case
`model_selection_mid_session_retry`, `session_codec_vectors.json`,
`session_invalid.json` and `app_server_protocol.json`.
