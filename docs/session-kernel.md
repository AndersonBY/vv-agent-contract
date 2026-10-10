# Session kernel

Contract 25.0.0 defines one execution authority: the ordered session log and inbox.
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
| InboxItem | `schema_version:integer const 1`, `input_id:T`, `kind:inbox enum`, `target_turn_id:T\|null`, `generation:N\|null`, `available_ms:N`, `payload:J` selected by kind |

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
| `input_applied` | `input:InboxItem`, `input_digest:H`, `disposition:applied/rejected/noop/queued`, `reason:T\|null`, `target_operation_id:T\|null`, `target_wait_id:T\|null`, `position:T` |
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
| `provider_result` | `operation_id:T`, `attempt:P`, `request_digest:H`, `provider_binding:T\|null`, `result:V`, `evidence:[T]` |
| `approval_answer` | `operation_id:T`, `attempt:P`, `request_id:T`, `request_digest:H`, `decision:approve/deny/allow_session/timeout`, `scope:[T]`, `reason?:S`, `metadata?:J` |
| `child_result` | `session_id:T`, `turn_id:T`, `operation_id:T`, `attempt:P`, `result:V`, `status:completed/failed/cancelled/aborted`, `terminal_seq:P`, `terminal_digest:H` |
| `control` | `action:close/archive/suspend/resume/cancel/abort` |
| `provider_evidence` | `operation_id:T`, `attempt:P`, `request_digest:H`, `handle:Handle` |

User content remains opaque at the generic boundary. Kernel reply producers currently use
`{operation_id,interaction_id,text}` for ask_user and `{interaction_id,text}` for
turn-level waits; the target turn/generation is supplied in the envelope.

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

JSON-RPC 2.0 uses initialized `protocolVersion=v2`. Params, results and notifications
are closed and reject unknown fields. Thread identity equals session identity;
turnId equals runId. `attributes.app_server` is the sole durable thread metadata
home. There is no independent thread or transcript ledger.

### Requests and results

| Surface | Current shape and behavior |
| --- | --- |
| turn/resume params | Exactly `{threadId:T,turnId:T}`; missing/extra fields return -32602 `turn/resume requires exactly threadId and turnId`. No new input. |
| turn/resume result | Required threadId, turnId, runId, status (`running/completed/failed/interrupted`); optional finalOutput, completionReason, completionToolName, partialOutput, waitReason, error, tokenUsage, budgetUsage, budgetExhaustion. |
| thread/resume params | `{threadId:T,subscribe?:B,afterItemId?:S}`; subscribe defaults true. |
| thread/resume result | `{thread:AppThread,turns:[AppTurn],items:[AppItem]}` with cursor-filtered items. |
| turn/action params | Exactly threadId, turnId, actionId, action. action is a closed respond/suspend/resume/cancel/abort variant; respond carries the current strict user Message. |
| turn/action result | Exactly `{threadId,turnId,actionId,accepted:true,status:'running'}`; identical retry returns retained admission outcome even after state advances; different bytes conflict. |
| thread/status and thread/status/changed | Required threadId/status; optional waitReason, prompt, interactionId, sessionId, childTurnId, interactions. |
| Interaction | Exactly `{sessionId:T,turnId:T,prompt?:S,interactionId?:T}`. |
| turn/completed | Required threadId/turnId/status; optional runId, finalOutput, completionReason, completionToolName, partialOutput, waitReason, error, tokenUsage, budgetUsage, budgetExhaustion. Interrupted describes an attempt; only turn_ended is terminal. |

T is a nonempty string, S a string, B a boolean. Optional members are omitted,
never filled with null. Strict accounting objects retain their canonical
camel-cased shape, including output_repair and complete modelCalls; native keys
inside providerUsage remain opaque. Identity strings have the existing 512-byte
limits; response content keeps the 65536-byte limit.

### Status and recovery

One projection function computes the single thread status enum
`idle/running/interrupted/archived/closed` for AppThread.status, thread/status and
thread/status/changed. AppTurn.status is pending/running/interrupted/completed/failed.
Parked or suspended work is interrupted. Cancellation and abort project failed
with their retained observation. Restart preserves the active turn and wait;
it cannot infer a terminal or replay a completed model/tool call.

Execution on a closed thread through turn/start, turn/resume or thread/resume with
execution subscription (`subscribe=true` or omitted) returns -32602 `Thread is closed`.
`thread/resume` with `subscribe=false` remains a read-only snapshot; read/list remain
available. Archive retains the existing THREAD_ARCHIVED error. Resume subscribes
before future events, reuses a local handle, honors the live lease after restart,
and returns a terminal's original retained result without driving.

Original non-text input survives read/resume. Later turns use full same-session
projected history after accepted compaction. WAIT_USER replies continue the same
turn and operation with one definitive receipt. ask_user has no tool item before
that receipt; safe interaction projection comes first. A child wait retains the
parent wire turn, with childTurnId naming the actual child wait. Reply targeting
comes from retained evidence. Interactions expose no operation/request digest,
arguments, lease or handle.

Normal completion projects idle status before turn/completed. Interrupted-attempt
ordering is retained, followed by interrupted status with safe interactions;
stable IDs and subsequent status reads recover the parked fact. Tool lifecycle
notifications remain under toolLifecycle.executed. Model identity has exactly
callId, operationId, attempt, operation, cycleIndex, backend and model. App item
identity is `item_{event_id}` and retained timeline replay uses afterItemId.

### Approval and action identity

Commit and project approval/requested before sending approval/request to the
original authenticated owner. Observers cannot approve and disconnect does not
transfer ownership. Resume preserves that owner. Every unanswered approval
resolves at its original absolute deadline using timeoutDecision, including time
spent obtaining the provider decision; a vanished owner cannot block forever.
The four case-sensitive decisions remain approve/deny/allow_session/timeout.

Action identity preserves this algorithm: JCS canonical object
`{schema_version:'vv-agent.controller-command-id.v1',thread_id,turn_id,action_id}`;
SHA-256 over UTF-8 domain `vv-agent.controller-command-id.v1`, NUL, unsigned
64-bit big-endian JCS byte length, then JCS bytes. The domain string defines
identity only. Action IDs are scoped to the exact thread and turn. Inbox turn and
generation fences are server-owned. Immediate accepted/running means admission.
Five golden vectors are in `app_server_observable.json#actionAdmission.commandIdCases`;
`app_server_protocol.json#facts.child_reply_command_id` binds a real child reply.

### Exports and evidence

Schema export is self-contained and strict. Its jsonSchema values are JSON strings.
Keep the 19 JSON and 18 TypeScript bundle names listed in
`app_server_observable.json#schema`; embed current Interaction/status definitions
in reachable $defs and the existing bundles. InitializeResponse requires v2.
No retired summaries or alternate protocol definitions remain. Model/list filtering,
model summaries, timestamps, request IDs, channels and non-text validation retain
their canonical behavior.

`app_server_observable.json` is the expectations inventory;
`app_server_protocol.json` contains real request/result/notification transcripts,
schema exports and `#/host_interaction_values` for HostInteractionRequest and
HostInteractionOutcome wires. Both fixtures describe one protocol.
