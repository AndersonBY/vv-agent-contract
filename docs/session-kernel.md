# Session kernel

Contract 41.0.0 defines one execution authority: the ordered session log and inbox.
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
| `J`, `V` | Content-only opaque JSON object / any I-JSON value, including null |
| `C` | Closed `ContentRef` pointing to encrypted typed content |
| `X?` | Optional member, omitted when absent; null is allowed only if its type permits it |
| `X\|null`, `[X]` | Required nullable value; array of X, empty permitted |
| `{...}` | Closed object; every listed member required unless marked `?` |

All listed envelopes and typed nested objects MUST reject unknown members.
Only `J`/`V` locations are extension/content boundaries; their contents MUST NOT
override kernel control fields. Array order is significant. Nonempty strings
and array elements are not implicitly normalized, trimmed, sorted or deduplicated.

| Envelope | Required fields (no other fields) |
| --- | --- |
| Record | `schema_version:string const "S1"`, `feature_level:integer 1\|2`, `record_id:T`, `kind:record enum`, `session_id:T`, `turn_id:T\|null`, `operation_id:T\|null`, `attempt:P\|null`, `payload` closed by kind |
| InboxItem | `schema_version:string const "S1"`, `feature_level:integer 1\|2`, `actor:Principal`, `admission_proof:proof\|null`, `input_id:T`, `kind:inbox enum`, `target_turn_id:T\|null`, `generation:N\|null`, `available_ms:N`, optional `requirements:SessionRequirements`, `payload:J` selected by kind |

The logical record has no top-level sequence, receiving time, record digest, chain
digest, commit identity or writer epoch. Storage supplies ordered positions,
record/integrity digests and the chain envelope separately; `chain_digest` is not
part of logical record bytes or record identity. `op_started.payload.epoch` is
retained dispatch evidence, not the omitted storage-envelope writer epoch.
Nullable fields MUST be present.
Feature level 1 is the unchanged current level-1 byte and behavior shape: it has
no `session_created.bootstrap` and no `InboxItem.requirements`, and either added
field at level 1 rejects. Level 2 is allocated only for `session_created` with its
required `bootstrap`, and for `user`, `follow_up` and `model_selection` with their
required `requirements`. A level-2 shape for any other record or inbox kind, or a
level-2 control item missing its field, rejects. Existing level-1 fixtures and
producer bytes remain readable without inserting defaults into the logical value.
When a level-1 `user` or `follow_up` input activates in a level-2 session, its
bytes remain level 1 and the session's trusted `bootstrap` supplies that input's
pre-admission routing bound; the absent field MUST NOT be interpreted as a
`(1,null,[])` replacement for the bootstrap.
An envelope's `feature_level` is a format requirement and is independent of the
nested `SessionRequirements.level`. The format floor of a session is the maximum
`feature_level` of every persisted record and every currently stored, unconsumed
inbox item activated for that session, including an item whose `available_ms` is
still in the future or which is otherwise not ready for application. "Activated
inbox" does not mean only ready inputs. A consumed input remains represented by
its persisted `input_applied` record; an unconsumed item remains part of the floor
until it is consumed. The floor never decreases. In particular, a level-2
`session_created` remains a level-2 format even when its trusted `bootstrap.level`
is 1. Such an inner level does not make the level-2 record decodable or executable
by a level-1-only reader or worker. A session containing only level-1 envelopes
retains its original level-1 behavior and floor.
`operation_id` and `attempt` MUST both be non-null exactly for `op_*` records and
null otherwise. `session_created.turn_id` MUST be null. All other record kinds
require a turn except `input_applied` and `usage_observed`, which permit null.

## Record payloads

| Kind | Closed payload fields |
| --- | --- |
| `session_created` | `principal:Principal`, `workspace:C`, `parent_session_id:T\|null`, `parent_operation_id:T\|null`, `attributes:C`; level 2 also requires `bootstrap:SessionRequirements` |
| `turn_started` | `input_ids:[T]`, `definition:C`, `definition_digest:H`, `handler_version:T`, `budget:C`, `binding:T\|null`, `generation:N`, `policy_digest:H\|null`, `requirements:SessionRequirements`, `tokenizer_binding:TokenizerBinding\|null`, `environment:EnvironmentBinding\|null` |
| `input_applied` | `input:InboxItem`, `input_digest:H`, `input_proof:InputProof\|null`, `disposition:applied/rejected/noop/queued`, `reason:C\|null`, `target_operation_id:T\|null`, `target_wait_id:T\|null`, `position:T`, optional `model_binding:C` |
| `op_planned` | `op_kind:model/tool/interaction`, `purpose:primary/compaction/session_memory/output_repair\|null`, `request:C`, `request_digest:H`, `context_version:T`, `dependencies:[T]`, `tool:C\|null`, `idempotency_key:T\|null`, `budget_admission:C`, `not_before_ms:N\|null`, `provider_binding:T\|null`, `consumed_unknowns:[ResultId]`, `policy_decision:PolicyDecision\|null` |
| `op_prepared` | `request:C`, `request_digest:H`, `op_kind:tool/interaction`, `tool:C`, `provider_binding:T\|null`, `idempotency_key:T\|null`, `hook_result:C\|null`, `shared_state:C`, `policy_decision:PolicyDecision\|null` |
| `turn_parked` | `interaction_id:T`, `question:C`, `source_operation_id:T`, `source_attempt:P` |
| `op_started` | `dispatch_id:T`, `authorization_version:T`, `epoch:P`, `mode:sync/provider/managed`, `endpoint_id?:T` |
| `op_parked` | `phase:before_dispatch/after_dispatch`, `handle:Handle`, `poll_at_ms:N\|null`, `deadline_ms:N\|null`, optional `interaction_result:C`, optional `delegation:Delegation`, `yield_on_steer?:true`, `yieldable_children?:[T]` |
| `op_completed` | `result:C`, `result_digest:H`, `usage:C`, optional `usage_counts:UsageCounts`, `shared_state:C\|null`, `evidence:C`, `execution_started:B`, `context:normal/correction/audit`, `request_digest:H`, `provider_binding:T\|null`, optional `policy_decision:PolicyDecision`, `yielded_by?:T` |
| `op_unknown` | `reason:C`, `dispatch_evidence:C`, `observation:C`, `retry:retry/stop/manual`, `retry_at_ms:N\|null`, `duplicate_cost_risk:B`, `measurement_missing:B` |
| `context_compacted` | `source_digest:H`, `prefix_ids:[T]`, `tail_ids:[T]`, `mode:micro/summary/emergency`, `summary_operation_id:T\|null`, `replacement:[C]`, `evidence_manifest:C`, `micro_usage?:{archived_count:N,reclaimed_tokens:N,artifact_failure_count:N}` |
| `boundary_recorded` | `boundary_id:T`, `stage:boundary enum`, `source_operation_id:T\|null`, `source_digest:H\|null`, `data` closed by stage with C leaves |
| `usage_observed` | `meter_id:T`, `observation:P`, `mode:cumulative/correction`, `usage:C`, `source:C` |
| `turn_ended` | `status:completed/failed/cancelled/aborted`, `reason:C\|null`, `result:C\|null`, `adopted_results:[ResultId]`, `budget:C`, `unconfirmed_operations:[T]` |

`ResultId = {operation_id:T, attempt:P}`. `op_planned.purpose` MUST be non-null
exactly when `op_kind=model`. Payload validation alone does not impose a
model-request, ToolExecutionResult or budget schema on `ContentRef`; hydration
validates the original typed content boundary before execution.

## Inbox payloads

| Kind | Closed payload fields |
| --- | --- |
| `user` | `content:C` |
| `steer` | `content:C` |
| `follow_up` | `content:C` |
| `model_selection` | `selection:C\|null` |
| `provider_result` | `operation_id:T`, `attempt:P`, `request_digest:H`, `provider_binding:T\|null`, `result:C`, `usage:C`, `evidence:C` |
| `approval_answer` | `operation_id:T`, `attempt:P`, `request_id:T`, `request_digest:H`, `decision:approve/deny/allow_session/timeout`, `scope:C`, optional `reason:C`, `metadata:C`, `policy_digest:H`, `rule_id:T`, `expires_ms:N\|null` |
| `child_result` | `session_id:T`, `turn_id:T`, `operation_id:T`, `attempt:P`, `result:C\|null`, `status:completed/failed/cancelled/aborted`, `terminal_seq:P`, `terminal_digest:H` |
| `control` | `action:close/archive/suspend/resume/cancel/abort` |
| `provider_evidence` | `operation_id:T`, `attempt:P`, `request_digest:H`, `handle:Handle`, optional `yield_on_steer:true` |

User content remains opaque at the generic boundary. Kernel reply producers currently use
`{interaction_id,text}` (optionally operation_id) for ask_user and `{interaction_id,text}` for
turn-level waits; the target turn/generation is supplied in the envelope.

`provider_result.usage` MUST be a required `ContentRef`, just like
`op_completed.usage`; after hydration it MUST be a JSON object and `{}` means no
observed usage. Missing, null or plaintext usage, non-object hydrated usage and
unknown payload members MUST reject. Authentication MUST cover the encrypted usage
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

For an original long body, duplicate comparison MUST validate its UTF-8 SHA-256
and byte length against the selected persisted artifact, then project using that
saved reference. It MUST NOT derive a replacement filename or rewrite history.
All other result fields and usage remain part of the canonical comparison.

## Nested values and attributes

| Type / location | Fields |
| --- | --- |
| Provider Handle | `kind:const provider`, `provider:T`, `job_id:C`, `operation_id:T`, `attempt:P`, `request_digest:H`, `evidence:C`, `query_ref:C\|null`, `cancel_ref:C\|null` |
| Approval Handle | `kind:const approval`, `request_id:T`, `request_digest:H`, `scope:C` |
| User Handle | `kind:const user`, `interaction_id:T`, `question:C` |
| Child Handle | `kind:const child`, `session_id:T`, `turn_id:T`, `generation:N`, `background:B`, `delivery_target:DeliveryTarget`, `siblings?:[ChildIdentity]` |
| DeliveryTarget | `session_id:T`, `turn_id:T`, `generation:N`, `operation_id:T`, `attempt:P` |
| ChildIdentity | `session_id:T`, `turn_id:T`, `generation:N` |
| Delegation | `mode:configured/agent_as_tool/background_task/handoff`, `agent_name:C`, `handoff_count:N`, `max_handoffs:N`, `metadata:C` |
| `attributes.seed` | Optional `unseen_input_protection:B`, `response_rejection:B`; optional paired `messages:[Message JSON]`, `shared_state:J`; at least one declaration or the pair is required |
| `attributes.app_server` | `agent_key:S`, `cwd:S\|null`, `metadata:J` |
| `attributes.child_admission` | `mode:configured/agent_as_tool/background_task/handoff`, `selector:T`, `definition:J`, `definition_digest:H`, `budget:J`, `handler_version:T`, `sub_config:SubConfig\|null`, `exclude_files_pattern:T\|null`, `handoff_count:N`, `max_handoffs:N`, `handoff_metadata:J` |
| SubConfig | `model:T`, `description:S`, `backend:S\|null`, `system_prompt:S\|null`, `max_cycles:N`, `session_memory_enabled:B`, `exclude_tools:[S]`, `metadata:J`, `denied_side_effects:[T]`, `denied_capability_tags:[T]`, `deny_terminal_tools:B`, `denied_cost_dimensions:[T]` |

Handle is exactly one of its four closed variants. Logical `attributes` is a
`ContentRef`; its hydrated content remains an explicit extension object, while
`app_server`, `child_admission` and `seed` retain closed typed validation. The producer retains `attributes.child_handle`;
the child reducer/authenticator validates that against admission. It MUST NOT be
described as a third codec-validated attributes schema without corresponding work.
The codec permits duplicate `siblings`; the fold MUST reject duplicate member
identities and mismatched creation/delivery targets.

## Boundary stages

| Stage | Closed `data` fields | Observable boundary |
| --- | --- | --- |
| `before_memory` | `messages:[C]`, `shared_state:C` | Retain hook replacement and source digest before compaction |
| `after_cycle` | `action:continue/steer/stop_non_success`, `steering_messages:[C]`, `disallow_tools:[T]`, `stop:{code:AfterCycleStopCode,message:C}\|null`, `shared_state:C`, `error:C\|null` | Retain composed decision before another dispatch |
| `memory_started` | `event:C` | Retain MemoryProvider/lifecycle start observation |
| `memory_completed` | `event:C` | Retain completion and archive statistics |
| `session_memory_saved` | `state:MemoryState` | Structured memory precedes disposable file projection |
| `output_checked` | `status:completed/failed/repair`, `reason:C\|null`, `value:C`, `partial_output?:C` | Retain candidate, repair decision and final validation |
| `budget` | `usage:C`, `exhaustion:C\|null`, `tool_names:[T]` | Retain admission/accounting and exhaustion decision |

`AfterCycleStopCode = host.policy_stop/host_stop/hook_stop/stopped`. The public
hook decision accepts a bounded valid host code, but the ledger S value is closed.
At commit, a code outside the registered set is recorded as `host_stop`. The
original diagnostic `"original_code: message"` is stored in the encrypted `error`
C slot, and `stop.message` remains the message C slot. This applies only to the
current Python S1 boundary; Rust remains frozen at 23.0.0 and does not support it.

`MemoryState = {entries:[MemoryEntry], last_extracted_message_index:integer≥-1,
tokens_at_last_extraction:N, initialized:B}`.
`MemoryEntry = {category:user_intent/decision/file_change/error_fix/key_fact,
content:C, source_cycle:N, importance:integer in 1..10}`. Both are closed. The
generic codec does not replace the strict Message, event or budget readers after
hydrating their typed content.

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

## Closed-schema rejection diagnostic

Contract 39.0.0 replaces the diagnostic for a failed closed session-schema check
with exactly `invalid session schema`. This includes record/inbox envelopes,
kind-specific payloads, reserved metadata, typed handles, model bindings and child
admission shapes. The same accepted and rejected values, validation order and
canonical bytes MUST be preserved. This rule does not change the handling of a
value that fails a different check first.

The schema-rejection diagnostic MUST NOT contain customer input, an offending
value excerpt, a schema dump or a validator's pretty-printed trace. When an
existing host or App Server path exposes this rejection, it MUST expose the
concise diagnostic within its existing error envelope. Existing contextual
wrappers MUST NOT restore those dumps. Concrete third-party validator exception
causes, their attributes and object identities are not a compatibility surface;
implementations MUST NOT retain a schema-validator cause that reintroduces the
excluded input or schema dumps. A failed Boolean schema check does not require
an artificial underlying exception.

This replaces only closed-schema diagnostics. Existing specific semantic errors,
including identity and embedded-digest mismatches, and existing parser and
duplicate-member errors MUST retain their messages and rejection behavior.
Additional ModelSettings semantic validation is unchanged. Provider rejection
mapping MUST retain `provider_result_invalid`; rejected model selections MUST
retain `model_selection_unresolvable`. Execution, admission and retry behavior
are unchanged. Opaque customer content is not rewritten.

This is a public diagnostic replacement, not a persistence boundary. Release 39
recorded the replacement against the then-current record 1 / inbox 3 formats while
leaving SQL layouts, canonical IDs/digests, stored bytes, RunEvent v6, App Server
v5 and the public API inventory unchanged. Those format references are release
history. Current Contract 41 uses the S1 formats above and rejects record 1 /
inbox 3 without conversion or compatibility mode. See
[39.0.0 release notes](release-39.0.0.md).


## S1 storage allocation

`Principal` is the closed
`{tenant_id:T,subject_id:T,subject_kind:user|service|agent,attributes:C}` object.
Creation principal identity is immutable; an inbox actor's tenant MUST equal the
owning session tenant. A single-tenant host uses `tenant_id="default"` explicitly.

`ContentRef` is closed `{content_id:T,mac:H,size:N,key_id:T,labels:ContentLabels}`.
`ContentLabels` is closed `{source:[system|user|internal|untrusted],classification:public|internal|confidential|restricted}`. Source order is the listed enum order, duplicates reject, and the inactive P2 default is `source=[]`,
`classification="internal"`. ContentRef is not a path, URL or plaintext digest.

`InboxAdmissionProof` is null in explicit unsigned local mode or the closed
`{admission_key_id:T,admission_signature:S,admission_signed_ms:N}` object.
`InputProof` is null in that mode or the closed
`{input_seq:P,received_ms:N,key_id:T,signature:S,signed_ms:N}` object copied from
the original inbox admission. Key ID, signature and signing time MUST equal the
embedded admission proof; mismatches reject. Signature strings use canonical
base64; an empty or noncanonical value rejects. Signed deployment configuration
cannot downgrade a missing proof to unsigned mode.

`SessionRequirements` is closed `{level:P,handler_version:T|null,capabilities:[T]}`.
The initial level is 1. At level 2 it is the typed control value for
`session_created.bootstrap` and for the three pre-turn inbox kinds. Missing level-1
control fields retain the existing default behavior: no bootstrap requirements and
the runtime's existing level-1 cache default. No default field is materialized in
old logical bytes, and the `definition.digest` input is unchanged.

Capability IDs are opaque, sorted and duplicate-free with no wildcard or numeric
ordering. User content, opaque creation or task attributes, executor class names
and agent names MUST NOT supply or override these values. A non-null trusted
`handler_version` identifies the handler family directly. A null bootstrap handler
is permitted only when the host's trusted bootstrap declares an explicit family
capability in `capabilities`; absence of that capability rejects before routing.
The runtime's trusted configuration supplies the declared value. It MUST NOT infer
it from opaque attributes or prompt content.

Level-2 `user`, `follow_up` and `model_selection` requirements are a pre-admission
capability bound published in the same transaction as the inbox item. They come
from trusted static declarations and already-frozen handler/model configuration:
the configured base tools, all potential dynamic tools that may become model-visible
for that turn, and any explicit trusted host declaration for a custom factory whose
candidates cannot be enumerated without side effects. A bound MUST cover every tool
that the eventual turn can enable, and MAY include tools that the compiled turn does
not use. The publisher MUST NOT run compile to make the bound precise.

`turn_started.requirements` is separate and exact: after the normal single turn
compile, its stable tags describe the actual model-visible tool subset in the frozen
definition. The tools metadata map and whole-tool-set digest remain invalid
substitutes. The actual set MUST be a subset of the pre-admission bound; capabilities
MUST NOT be lowered in level, and a non-null handler MUST equal the bound handler.
The clear frozen definition remains in `turn_started.definition`; opaque C content
cannot carry or override either control value.

`model_selection.requirements` contains model tags only and its non-null handler
MUST equal the current routing handler (the active turn handler, or the idle cache
handler); a different handler rejects publication before the input is stored.
`steer`, provider/result evidence, control and other
inbox kinds remain level 1 and do not add a control requirement.
`turn_started.tokenizer_binding` is null or closed
`{model_identity:T,counting_method:provider_reported|tokenizer,implementation_id:T,
asset_identity:T,normalization_id:T}`. A replayable counting capability freezes this
binding and matching worker capability IDs before dispatch.

`turn_started.policy_digest` is `H|null`. `environment` is null or the closed
`{descriptor:ContentRef,environment_capabilities:[T],capabilities_digest:H|null,
network_policy_ref_digest:H|null,isolation_policy_ref_digest:H|null,operational_policy:C|null}`
binding. Environment capabilities are sorted and duplicate-free and remain a
separate namespace from worker requirements. `operational_policy` MUST be
`ContentRef|null`; it never places the clear closed C object
`{network_policy_digest:H,isolation_policy_digest:H}` in the skeleton. Hydration
validates that object and its operational digests.

`PolicyDecision` is null or `{policy_digest:H,rule_id:T,effect:allow|deny|require_approval}`
at operation plan, preparation and completion. `approval_answer` may carry
`policy_digest`, `rule_id` and `expires_ms`; approval scope and prose remain C.
`UsageCounts` is the optional closed `{tokens:TokenCounts|null,budget:BudgetCounts|null}`
projection. It contains numeric/enumerated accounting and C unit/currency refs;
the raw upstream usage remains authoritative C. No missing metric is filled with
zero.

Storage framing is separate from every logical record. The language-neutral
`fixtures/session_storage_envelope.json` and its schema define the closed envelope
`{schema_version:"S1",tenant_id,session_id,seq,record_digest,chain_digest,writer_epoch,created_ms}`.
The initial chain hashes `UTF8("vv-agent/S1")`, then length-prefixed tenant/session
IDs; each next digest frames the previous 32-byte digest, `U64BE(seq)` and decoded
`record_digest`. `chain_digest` is excluded from logical record bytes and identity.
It is storage integrity metadata, not a second execution record and not SQL DDL.

`fixtures/session_storage_lifecycle.json` allocates the independently destroyable
session-key capability, idempotent destroy outcomes, complete/pending tombstone
verification, and the versioned JSONL export header. Export version 1 supports
closed `skeleton` and explicit `include-content` modes with record, inbox, content,
checkpoint and manifest lines. Skeleton export rejects content lines.

Every envelope and nested S1 object rejects unknown members. Plaintext objects in
C slots, including workspace, request/tool, results, inbox bodies, provider
handles/evidence and operational policy, reject at the logical boundary. Old record 1, inbox
3, SQL schema 1 and unsupported feature levels reject; there is no historical
decoder, alias or dual-format path. SQL DDL, PostgreSQL RLS and Python symbol
spellings are not canonical wire fields.

## Creation seed and reserved metadata

A creation-time `session_created.attributes.seed` is a closed object with an optional
`unseen_input_protection` and `response_rejection` Boolean declaration and an optional paired `messages` /
`shared_state` bootstrap. At least one declaration or the pair is required. Both declarations independently default to true on first creation, inherit from the source (absence becomes explicit false), and preserve original bytes on transaction creation replay.
See [input protection](unseen-input-protection.md) and [completion evidence](model-completion.md). Messages use the strict current Message wire.
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

## Worker requirements and routing cache

Stable capability tags replace whole-tool-set identities:

```text
tool:<lowerhex SHA256(RFC8785_JCS({name,schema,metadata}))>
model:<lowerhex SHA256(RFC8785_JCS({backend,model,context_length,max_output_tokens}))>
```

`schema` is the complete normalized OpenAI function tool object returned by
`ToolRegistry.get_schema`/`list_openai_schemas`: outer `{type:"function",function}`
with the actual `function.name`, `description`, `parameters`, `strict` and any
provider-supported function fields. The `name` member of the tag fact MUST equal
`schema.function.name`. A parameters schema alone is not the tool schema and
produces a different tag. `metadata` is normalized `ToolMetadata.to_dict()`, or
`{}` when absent. A pre-admission bound contains tags
for the configured base tools and the trusted host-declared potential dynamic/tool
factory set. It is deliberately conservative and is not an enumeration of all 2^n
runtime subsets. `definition.capabilities` is a tool-name-to-metadata lookup and is
never itself a capability list.

The exact `turn_started.requirements` tool tags are computed only from the
model-visible subset in the actual compiled definition. Hosts MUST derive the bound
from trusted static declarations without running input guardrails,
`is_enabled` callbacks, instruction resolution, context providers, file reads or any
other compile effect. When a custom factory cannot be enumerated without those
effects, the existing trusted host configuration declares its complete potential
capability bound explicitly; the implementation MUST NOT infer it from runtime
class, agent name or opaque attributes.

A worker's supports are computed from the trusted complete tool registry, including
host-declared dynamic agent tools, plus its trusted model configuration. Extra
catalog tools do not make a worker incompatible. A schema or normalized metadata
change produces a different tag.

Tool, model and handler supports are execution capabilities. They are not tenant
content-read authorization and MUST NOT become a generic record, inbox, projection,
replay or consumer-ACK gate. Tenant identity, Principal checks, RLS and content-label
authorization retain their existing rules unchanged. After those checks, an
authenticated thin client, gateway or projection consumer may read and decode the
current S1 records and inbox values it is authorized to access even when its host
has no executor, model or tool capability tags. It MUST still satisfy the same
format level as an executor; only tool, model and handler execution supports are
waived for a thin reader.

Such a reader still validates the S1 discriminator, its reader format level against
the record/feature level, and the existing chain, input-proof, cursor or projection
read dependencies before decoding or projecting. An unknown/future feature level
rejects before unsafe decode; a level-1-only reader cannot project a level-2 value.
Those format and dependency checks are distinct from worker support. A projection
read acquires no execution lease and grants no claim, drive or dispatch authority.

An execution worker claiming or driving a session MUST still fully match the current
routing cache before it reads run bodies for execution: level, handler, pre-admission
bound, active actual requirements and applicable model-selection tags. Worker
acceptance is therefore an execution-side condition, never a requirement imposed on
every store reader. This boundary adds no reader registry, read capability field or
alternate permission protocol; implementation wiring MUST remove generic-read use of
worker acceptance while preserving the existing tenant/Principal/RLS controls.

The model tag fact is the exact four-field atomic resolved model identity
`{backend,model,context_length,max_output_tokens}`. All four members are present,
including explicit null capacity limits. Resolved `model_binding.endpoints` is
removed before identity and endpoint order therefore does not affect the tag.
Route, credentials and other host-routing data are not tag inputs. A capacity
change produces a new tag.

When frozen `definition.model_binding` contains `internal`, the primary binding and
each internal purpose binding are separate atomic model capabilities. Hash each
binding with the same four-field identity; never hash the `internal` object as one
model tag. Reusing the same binding across primary/internal purposes emits one
deduplicated capability tag in the requirements set. A logged `model_selection`
remains the effective application source; its requirements carry the same trusted
atomic tag so routing can be checked structurally. Supports come from trusted model
configuration/catalog. No executor identity is guessed from a runtime class, agent
name or opaque metadata.

The only persisted routing cache is the existing `sk_session` group
`{level,handler_version,required_capabilities,active_turn_id}`. It is derived, not
another execution authority, and adds no active/next row, source sequence/digest
copy, profile object, registry or SQL major. Recompute it under the session row lock:

The existing `level` column is the maximum of the session's monotonic format floor
and every routing requirement level applicable to the expected post-boundary cache.
The format floor is the maximum envelope `feature_level` of all persisted records and
all currently stored, unconsumed inbox items, including future-unavailable and
otherwise non-ready inputs. The routing contribution comes from the trusted
bootstrap, active turn and applicable queued or ready pending inputs under the
ordering below. Thus an unconsumed future item can raise the format floor without
being ready to route yet. A level-2 creation or input therefore keeps
`sk_session.level` at least 2 when idle or after turn end, even if its nested
requirements level is 1. A level-1-only session keeps the unchanged level-1 default.
This is the same single cache column: there is no second format-floor column, DDL,
decoder or persisted active/next state.

| Boundary | Expected cache |
| --- | --- |
| Session creation | Copy the trusted level-2 `session_created.bootstrap` initially, or retain existing level-1 defaults when absent. |
| Turn start | Compile normally once. Before committing `turn_started`, verify the actual requirements are a capability subset of the pre-admission bound, use the same non-null handler and do not lower the level. On success commit the exact actual requirements and `active_turn_id` in that transaction; on failure start no dispatch and record no fabricated terminal. |
| Input publication, idle | Derive the next route from both existing queued inputs and currently ready pending `user`/`follow_up`/`model_selection` inputs using the complete `apply_input` then `start_turn` order below, then apply effective model-selection model tags. With no eligible input, use bootstrap or the existing level-1 default. |
| Input publication, active | Keep the active handler and all initial turn requirements. Union model tags from valid applied and pending `model_selection` inputs for this turn. User/follow-up requirements stay pending and do not replace the active route. |
| Turn end | Commit `turn_ended` and recompute the idle cache from the same combined queued-plus-ready-pending derivation, otherwise bootstrap or the level-1 default, in the same transaction. Preserve the monotonic format floor; level-2 history never falls back to cache level 1. |

Idle routing simulation has two phases. First, process currently ready pending
inputs in `peek_inbox` `input_seq` order with `apply_input`, repeating until no
input can be applied. Each applied `user` or `follow_up` becomes queued using its
typed `requirements`; a `model_selection` follows its existing position and the
existing pending-batch rule. Only then, sort all queued but unadmitted new-turn
inputs with `start_turn`'s stable key `kind == "follow_up"`: users precede
follow-ups while application order is retained within each kind. Therefore an
existing queued follow-up does not win merely because it is already queued. If an
h2 follow-up is queued and a later ready h3 user is published, the cache must route
for h3; the producer first admits h3 as queued across the normal `step()` calls,
then `start_turn` selects h3 before h2. A cache derived only from the old queued
row is invalid.

The same derivation uses only inbox order, target/generation metadata and typed
requirements for this routing decision. It MUST NOT hydrate a pending user or
model-selection body to decide worker support. If the current worker lacks a ready
pending item's requirements, it leaves that item pending and does not claim merely
to process an older queued row; a compatible worker performs the existing
application. Model selections cannot be moved ahead of or behind their existing
pending application position.

The relation at turn start is `actual_required ⊆ pre_admission_bound`, never the
reverse. Input publication and worker routing use the bound and MUST NOT invoke
compile, guardrails, `is_enabled`, instruction resolution, context providers or
file reads to make it exact. The selected worker then performs the normal compile
once. If the resulting actual tags exceed the bound, handler differs or level is
lower, it MUST NOT dispatch or fabricate a terminal record. It releases the claim
and exposes a clear unsatisfiable pre-admission-bound configuration error, then
stops without an automatic retry. The existing producer has already recorded the
input as `queued` before `start_turn` compiles it, and the current control surface
cannot safely discard that queued item: cancel/abort require a turn while
close/archive do not supersede one input. The original inbox bytes MUST remain
immutable, and publishing another input does not remove the queued item or its
place in the normal apply-to-exhaustion and stable `start_turn` order. With the
current flow, correcting the trusted declaration therefore requires a new session.
Hosts MUST NOT describe a replacement input as recovering this session, replace
the cache with an unproved value, or treat the cache as a second ledger.
Recompiling the same input merely to discover a different answer, an automatic
retry loop, and a new cancel, supersede, input-discard or replacement-input
protocol are prohibited.

Active selection retains the old model tag while an old-model batch can still be
queried and adds the new model tag through the existing model-selection boundary.
It is effective in the current turn at that boundary, not merely in a later turn.
A worker supporting both models may finish the old batch and apply the selection; a
worker lacking either tag cannot decode/apply the selection or dispatch against it.
A handler mismatch rejects publication. There is no second user queue and no
change to model-selection replay, pending-batch delay or target rules.

The cache may be a valid time projection after the last authenticated boundary of
the complete captured proof source; it need not equal the source cut's recorded
time. Before incrementing the writer epoch or granting/renewing an execution lease,
under the session lock, the host first validates the existing cache as such a
projection of the complete raw record chain/checkpoints and inbox admission/input
proofs, using only their structural requirements. Only after that validation does it
refresh the clock and recompute the expected four-column cache for that same source.
No C body hydration is needed or permitted for this routing decision. The captured
source must include the bootstrap and every other item needed for the claimed
projection; a cut before bootstrap/source publication is incomplete and cannot be
used to hide understated requirements.

In signed mode, the authenticated capture time used for a projection is never
earlier than `max(checkpoint.signed_ms, each captured input admission_signed_ms or
received_ms that contributes to the source)`. An unsigned `created_ms` is not proof
of the lower time bound. In the explicit weaker no-signature mode, the durable SQL
metadata rows and their ordering are the trusted source, with the same structural
completeness and lower-bound projection rules. Weak mode does not make a future
`available_ms` input ready and does not permit ignoring its stored format floor.

A cache that understates the required handler, tool or model tags or the computed
format-and-routing level fails integrity before support filtering and before any
epoch/lease grant. If the locked pre-refresh validation fails, the host MUST reject
before epoch; refreshing `now` or rewriting the cache first would conceal the bad
projection. Only after that proof does the trusted full support set route the
requester. A later hydrated definition or selection is still validated by its own
typed reader; the cache is not a substitute for that validation. Existing signatures
and chain are the source proof; no second digest/source state is copied into the
cache.

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
| Model retry/fallback | Freeze endpoint order; one logical adapter invocation per logged attempt (`max_attempts=1`); vendor SDK retries may issue multiple physical HTTP requests, all subject to the observation rules in [model rejection](model-rejection.md). The operation limit is `max(2, frozen endpoint count)`; fewer than two endpoints permit two attempts. Distinct attempt/call IDs and every attempt's accounting MUST remain visible. Required unavailable metrics can stop fallback. |
| Model request rejected | An explicit adapter assertion or a complete owned-client observation where every physical request received 4xx other than 408, before stream output and without uncertainty anywhere in the exception graph, is a definitive failed receipt. Content rejections MUST NOT retry; 401/403/404 retry only with multiple frozen endpoints, without delay. 429 retains backoff and a single-endpoint retry. Explicit adapter retryability overrides defaults; all retries use the same frozen limit. See [model rejection](model-rejection.md). Each rejection remains completed without `op_unknown` or duplicate-cost risk. Primary exhaustion ends as `failed / model_request_rejected` with the last safe rejection and no unconfirmed operation from those rejected attempts. |
| Model response rejected | After complete normal consumption, declared `response_rejection=true` sessions classify content_filter or refusal reason without refusal text as HTTP 200 definitive rejection, even after temporary output. No retry, endpoint change, partial-output history/evidence or input-coverage advance. Absence/false keeps 0.33.3 behavior. Refusal text with empty content becomes ordinary assistant body unless content_filter. Missing-termination EOF is Unknown with existing retries; degraded observation retains null termination and the diagnostic. See [completion evidence](model-completion.md). |
| Tool retry | Unknown tools MUST NOT auto-retry unless frozen metadata declares `idempotency=supported` and the actual provider supports that key. Ordinary tools permit one retry (two attempts total). Unsupported/unknown idempotency stops. The key is stable across attempts, currently `{session_id}/{operation_id}`. |
| Output repair | One logged tools-free `output_repair` operation. An unknown repair MUST never be automatically retried. Coercion/repair errors MUST become durable failed results with partial-output evidence; rejected response text is excluded under the response-rejection rule. |
| Late result, unknown not consumed | A trusted result MAY be adopted normally. An earlier model receipt can supersede a planned, undispatched retry without inventing a result for that retry. |
| Late result, unknown consumed | Preserve the already delivered unknown message and append a correction, rather than rewrite history. `consumed_unknowns` MUST identify exactly the unknowns frozen into the successor request. |
| Late result, retry dispatched / turn ended / generation stale | Earlier model result is audit-only after retry dispatch. Ended/cancelled turns MUST NOT revive. Host adapters MUST reject stale business generations; authentic late evidence can remain audit-only. |
| Provider evidence | Host/provider authentication MUST precede application. Bind operation, attempt, request digest, provider binding and retained handle/evidence. A digest/evidence string alone is not proof of authenticity. |
| Steer / follow-up | Steer waits until the active frozen batch/retry closes and enters the next new request. Declared observations MAY close early through [yieldable waits](yieldable-waits.md); other pending work still blocks steering. Follow-up queues a new turn after the active turn ends. End admission MUST recheck inbox watermark so racing input is not lost. |
| User wait / approval | Reply to the exact interaction/turn/generation. Equal answer replays are noop; conflicting bytes reject even after completion. Approval binds prepared arguments and scope, uses an absolute deadline including provider-decision time, and derives allow_session only from applied answers. |
| Suspend / cancel / abort | Suspend preserves waits and permits durable incoming results without dispatch. Resume restores the same turn. Cancel/abort close undispatched work explicitly and dispatched work with confirmed-stop or unknown evidence; keep unconfirmed operation identities in the terminal. |
| Background Bash | Reattach only through the retained original owner and live process manager. OS/manager restart or missing handle is unknown; PID guessing MUST NOT authorize adoption or a confirmed stop. |

## Boundaries, budgets and compaction

Host-requested compaction and pre-admission child summaries use the existing
model operation ledger. See [tool summary requests](tool-metadata-and-telemetry.md#host-requested-summaries).


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

JSON-RPC 2.0 uses initialized `protocolVersion=v5`. Objects are closed.
Thread identity equals session identity; turnId equals runId. The session log
and inbox own execution; connections are subscribers, never execution owners.
The host authenticates connections. Before every thread read or action, including
creation and listing, the processor calls `authorize(connection_id, method, params)`.
A refusal returns -32027 `permission_denied` without reading or changing the thread.
The local single-user DefaultAppServerHost allows everything; distributed hosts
MUST implement the hook and apply their account and thread permissions.

### Host tool providers

The host registers trusted adapters by exact tool name. Registration does not
create a tool schema. It rejects empty or normalized names, incomplete adapters,
and conflicts with model, interaction or child-delegation bindings. Effective
configuration merges defaults with explicit bindings; explicit names win.
Each runtime copies the map. Children inherit it on creation and reconstruction;
their tool policy can only restrict the parent's permissions.

App Server start and recovery rebuild these bindings through the host's existing
run-configuration builder. Building bindings, reading resources and replaying
history do not submit work. Python maps this to `RunConfig.tool_providers`,
`AppServerHost.build_run_config` and `SessionDriver.runtime`. `Provider`,
`Accepted`, `Definitive` and `Unknown` are public SDK exports.

Name, arguments, policy, approval and budget checks precede submission. Once an
acceptance handle is committed, every wake, resume and reconnect queries that
same handle. Only the explicit `function` binding selects the synchronous
function provider. A missing named binding raises `MissingHostBinding`, reports
`missing_host_binding` and keeps the wait; it cannot invoke a synchronous tool.

Before a provider submit, query, cancel or authenticated callback becomes an
`op_completed`, the kernel validates the result. Tool results must parse as the
current `ToolExecutionResult`, have a definitive SUCCESS or ERROR status, and
match the prepared request's tool call ID. Ambiguous transport, timeout and stop
errors need `metadata.definitive_outcome=true`. Evidence must be nonempty for
dispatched work and contain the original acceptance evidence when a handle was
retained. Provider handles and callbacks must bind the original provider,
operation, attempt and prepared request digest. Callbacks also bind the turn and
generation; authentication covers result and usage together.

Invalid submit, query and callback results report `provider_result_invalid`.
Query and cancel keep the
original handle and wait. Invalid submit results without a retainable handle
become Unknown with dispatch evidence and MUST NOT trigger automatic retry,
even when the tool normally supports idempotency. Callback rejection is retained
in the applied-input receipt. Invalid submit, invalid cancellation on a turn
marked cancelled, and rejected callback facts
project a `DiagnosticEvent(code="provider_result_invalid")` and App Server
`error/warning` from existing records; invalid query warnings leave no new
completion record. No invalid result becomes a business failure or
proof of a stop.

Cancellation has three meanings. An accepted control receipt means requested.
A valid Definitive result confirms the original operation's terminal outcome;
it does not claim every successful result was stopped by that request. Accepted,
Unknown, exceptions, timeout and invalid cancellation replies cannot confirm the
stop. A guard closure (schema/handler version mismatch, budget or hook failure)
preserves the original provider wait when the turn has not been marked cancelled;
it does not create an `op_unknown`. The failed terminal lists that operation in
`unconfirmed_operations`. The unknown transition is allowed only for a started
attempt, or a parked attempt that was dispatched and whose turn is marked
cancelled. For user cancel/abort, a non-Definitive cancellation reply records
`op_unknown` with the closure reason; an invalid Definitive reply records
`op_unknown(provider_result_invalid)`. The original acceptance evidence and
terminal unconfirmed identity remain retained. Late trusted results are
audit-only and cannot revive that turn or cause a new submission.

There is an accept-before-record crash window: the external service may accept
work before the kernel records its handle. Only a provider that actually dedupes
and recovers by the stable `context.idempotency_key` may declare
`ToolMetadata.idempotency="supported"`. Retries reuse that key across attempts.
Otherwise the outcome stays Unknown until trusted evidence reconciles it.
There is no unconditional exactly-once guarantee.

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
that digest, outside the client-ID grammar. Actions are respond (typed target and answer),
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

Completed tool results and `thread/toolResult/read` follow
[the tool result contract](tool-results.md). Resource retention belongs to
the workspace backend; immutable backends can name existing versions without
copying output objects. The raw diagnostic body is replaced by the same bounded
descriptor used by items and event replay.

### Status

The current App Server v5 AppThread.status, thread/status and thread/status/changed
use one projection:
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
a closed union: approval `{kind:"approval",sessionId,turnId,requestId}` or the
user form specified in [typed interactions](interactions.md). Approval has precedence;
remaining waits sort by session and operation identity. Snapshot `state` in thread/read
and thread/resume contains this same status object at the captured log cut.
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
This resolver behavior uses the current S1 record and inbox envelopes and
introduces no SQL layout migration or store boundary.

Schema export is self-contained and strict. jsonSchema values are JSON strings;
current JSON/TypeScript bundle names are listed in app_server_observable.json.
InitializeResponse requires v5. Accounting and host interaction wires retain
their current shapes. app_server_protocol.json contains real producer transcripts
and exports; app_server_observable.json inventories their expectations.

## Per-session model selection

`ModelSelection = {model:T, model_settings?:ModelSettings, route:J}` is closed.
ModelSettings uses its existing canonical fields (fixture `model_settings.json`);
reasoning effort belongs in `reasoning:{effort:...}`, not route. Omitted settings
mean empty settings for the new model, with one logical adapter invocation per logged
attempt; vendor SDK physical retries remain subject to complete HTTP observation. The explicitly opaque route carries host routing such as backend_type.
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
`ModelBinding = {backend:T, model:T, context_length:P|null,
max_output_tokens:N|null, endpoints:[T]}`. The required `endpoints` field retains
routing evidence, not model identity. Its schema and type stay unchanged.
Identity checks MUST compare backend, model and both limits, excluding endpoints.
Each new primary request MUST carry model, route, canonical model_settings and
metadata.vv_session.model_binding. Resolution and execution use that retained
logical model; changing endpoint IDs MUST NOT cause binding drift.

Runtime definitions MUST exclude endpoint IDs, including internal model routes.
Current S1 definitions retain both model limits and reject endpoint-bearing model
bindings as unknown fields. Endpoint IDs in `op_started.endpoint_id`, request
`endpoint_order` and retained `input_applied.model_binding` are routing evidence;
they MUST NOT be treated as runtime-definition fields or compared as model
identity.

Every new model plan MUST resolve the current client for its purpose. Primary
plans, including retained selections, use the runtime resolver. Compaction,
session memory and output repair keep their own routes. The client's
`ordered_targets(preferred_endpoint_id)` is the single ordering policy. Freeze
its nonempty, unique endpoint IDs in `endpoint_order` for this operation only.
The kernel MUST NOT promote a preferred ID itself. An ID absent from the current
client is ignored. The order need not match any historical binding endpoints.

Before starting an attempt, prepare its current client and select exactly the
endpoint at `(attempt - 1) % len(endpoint_order)`. If it is absent, complete the
attempt definitively with `error_code=endpoint_unavailable`, empty usage,
`execution_started=false`, and no dispatch or provider I/O. Close that operation;
a new primary cycle can plan with current routing. This result MUST NOT carry
unknown-outcome or duplicate-cost risk and MUST NOT extend the retry limit.
It MUST NOT observe provider token usage or mark a token budget unavailable.
Already-started attempts retain their original dispatch endpoint and evidence,
including during crash recovery and late receipt replay.
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


### App Server context management

`thread/context/read` is a pure projection. It MUST NOT acquire a lease, drive,
write, acknowledge inputs or call a provider. It returns a SHA-256 contextVersion
of durable model-visible messages, tools, effective model binding/settings and
ordered accepted pending inputs, including future-available inputs. Availability
uses the stored timestamp, not a wall-time filter. Operational records alone do
not change it.
Reads from different nodes at the same durable cut return the same version.
Private reasoning, encrypted reasoning and provider blobs MUST NOT be returned.
New App Server sessions retain an initial compiled definition in the existing
attributes.app_server_context JSON extension. Reads use it before the first
turn, then the latest admitted turn definition. Existing sessions without a
definition report unknown parts until admission. This is a projection baseline,
not an execution plan; it cannot dispatch work. Baseline compilation and
compaction-only turns MUST NOT run input guardrails or context providers for an
empty synthetic prompt. Compaction-only completion MUST NOT run final-output
guardrails or output repair. Unknown token parts make the total unknown.
Token counts are estimates: instructions, tools, history, active summary and
pending input are separate. Counts distinguish logged raw history from the
visible projection. Model limits are nullable; runtime policy values use the
same memory-settings resolver as execution, including its explicit fallback.
Host callbacks that have not run cannot be predicted; the projection names that
boundary rather than invoking callbacks during a read.

On creation races, the winning transaction freezes this baseline. A conflicting
node retries transaction creation with the original app_server_context (or keeps
it absent when originally absent) and the current client creation fields. The
transaction's ordinary creation-byte, omitted seed-policy and consumer-set
checks decide replay; App Server MUST NOT maintain a separate attribute
comparison that bypasses those checks. Both seed declarations follow this rule.

`thread/compact/start` takes threadId, stable actionId and optional
expectedContextVersion. Admission locks the session, checks retained identity
before the version, and commits one authenticated intent. Equal params replay
the original requestId/inputSeq; different params conflict (-32024). A stale
version returns context_version_mismatch (-32028) without a write. The intent
uses the existing user-content JSON extension, with metadata.request_compaction
and a closed app_server_compaction params object. It is control intent, never
model input or an answer to a parked user interaction. It cannot be supplied
through App Server turn input. No inbox or record schema changes are needed.

The holder consumes this intent at the next safe boundary and feeds its input
identity into the existing requested_by summary path. While idle it admits a
compaction-only turn using existing turn records; that turn makes no primary
call and adds no user message. While a turn is running it waits for its batch;
while suspended or waiting for a person it waits for resume/reply. Cancel wins.
The intent uses the existing `user` input kind and `input_id`. `apply_input`
records it as `disposition=queued` both while idle and while a turn is active:
host compaction enters the existing compaction work queue rather than being a
reply to a parked user wait. It adds no ordinary user text, is consumed once
under its original input id, and requires no new kind, field, inbox identity or
storage boundary. Producer evidence MUST include the host-compaction
`input_applied` record.

The holder MUST preserve concurrently accepted input and cancel. Summary source
is an immutable prefix; acceptance precedes later context-changing input, so a
replacement cannot overwrite it. Logged same-source summary receipts are reused.

Existing memory lifecycle RunEvents carry requested_by identities and a reserved
nullable compaction_error. Host callback metadata cannot override that outcome. App Server
maps them to contextCompaction/started, /completed and /failed, with a stable
requestId and eventId. Completion with no eligible history is a successful no-op;
summary failure or cancellation is failed and leaves history intact. Terminal
records project failure for requests without a completion, so events/list can
replay interruption even if no summary started. No new event schema is introduced.

`model/list` uses the provider catalog and resolved limits used for execution.
contextLength, maxOutputTokens, supportsTools, supportsVision, inputModalities,
supportsReasoning, supportedReasoningEfforts, defaultReasoningEffort,
supportsPromptCache and supportsContinuation are required nullable fields.
Null means the catalog does not know; false and [] mean known unsupported.
Never infer support from a model name or provider name. Selection remains only
thread/model/select.

### App Server completed-boundary forks

`thread/fork` requires threadId and stable forkId (the client-ID grammar).
Optional throughTurnId and beforeTurnId are mutually exclusive nonempty turn IDs.
Optional workspace is an opaque JSON object. No other fields are accepted.
An unknown cut turn or a turn without turn_ended returns -32602 with a clear
reason. Missing source returns the ordinary thread-not-found error. A cut with
neither a retained turn definition nor a creation baseline returns -32602; the
producer cannot reconstruct a past effective model from current host settings.
Neither cut selects the last retained turn_ended, excluding a running suffix.
Through includes the named ended turn; before selects the preceding ended turn.
Before the first turn, or with no ended turns, the cut is creation (seq 1).
Failed/cancelled turns with a retained turn_ended are ended boundaries too.

The new identity is `fork/` plus lowercase SHA-256 of RFC8785 `[threadId,forkId]`.
Atomic session creation retains the original request and receipt. Retries on any
node check that request before reading the source again: equal params return
the retained threadId/lineage with accepted=true and replayed=true; changed
params return -32024 submission_conflict, even if a changed cut is invalid.
Omission differs from explicit workspace={}, and cut selectors are request facts.
Only the first creator fixes the cut. No source lease or source mutation is needed.

The result contains exactly threadId, accepted=true, replayed and lineage.
Lineage contains sourceThreadId, nullable cutTurnId, sourceRecordSeq,
sourceRecordDigest (SHA-256 of the cut record bytes), and contextDigest (SHA-256
of RFC8785 of the copied Message dictionaries). Copy the context/read projection
at that immutable prefix: visible history and accepted active summary, never raw
records or pending inputs. Copy no controls, requests, attempts, interactions,
approvals, compaction intents or unfinished work. Existing attributes.seed remains
exactly {messages,shared_state}; shared_state is empty, not a copied execution state.
The attributes extension app_server_fork retains params, lineage, effective_model
and last_compaction. app_server_context retains the cut definition. The effective
model (model, settings, route and binding) becomes the fork's frozen default;
later thread/model/select changes only the fork. Clearing it restores that default.

Thread read/list expose lineage in the existing thread.metadata.lineage map.
Context/read optionally returns lineage for forked sessions, and returns the
inherited lastCompaction until a newer accepted summary replaces it. workspace,
when supplied, is retained in thread.metadata.workspace and returned to both
host binding callbacks in their metadata. It is never interpreted as a path.
Authorization precedes all reads and creation and covers the source, derived
identity and requested workspace through thread/fork params.

Artifacts keep their existing relative paths and digests; artifact_scope only
names future writes. Copying evidence does not by itself grant model-facing
artifact read access in another session/task. Built-in reads enforce the current
scope rule in prompt-bundles-and-tool-results.md; inherited cross-task read grants
require a separate host integration and are not inferred from byte availability. The host prepares the business workspace, then calls fork.
The producer resolves source and destination artifact backends through host
bindings. Shared references are reused. Missing destination artifacts are copied
with the existing exclusive immutable write API at the same relative path. Both
source bytes and destination bytes are checked against length and SHA-256.
Existing corrupt artifacts are never overwritten. Unavailable or corrupt
evidence returns -32602 before session creation. A concurrent identical copy
reuses the winning bytes after verification. A failed session creation may leave
only reusable immutable artifact bytes; it never leaves a partial session. It never copies business
files, snapshots a directory, or creates a worktree. Source artifact retention is
host-owned and must include surviving forks. Source and fork then admit independent
turns. This uses current App Server protocolVersion v5 and the S1 record and inbox
envelopes, with no SQL layout migration, store boundary or parallel session format.


Typed user answers and free-text host replies follow [interactions](interactions.md).
They use the current JSON content extension, App Server v5, RunEvent v6 and S1
record and inbox envelopes; no SQL layout migration or new store boundary is
introduced. Hosts may catch the public
heartbeat-stopped signal before lease-loss errors when intentionally stopping a
renewal worker; it never certifies ownership for further execution.

## Unseen input protection

Contract 37.0.0 freezes the creation policy and preserves the protected input
suffix across compaction, hooks and replay. See [the normative rule](unseen-input-protection.md).

## Yieldable waits

Contract 38.0.0 introduced the optional `yield_on_steer`, `yieldable_children`
park fields and `yielded_by` completion evidence. Current Contract 41 applies them
to S1/W4. The complete normative rule, including atomicity, ordering, callbacks and
late work, is [yieldable waits](yieldable-waits.md).

## L1 lease lock ordering

The heading preserves the historical Contract 38 anchor. Its process-local
renewal lock, lease-value lock, commit lock and same-thread reentry exception are
replaced by current S1/W4 rules and are not current correctness requirements.
Under W4, one process-level LeaseKeeper thread uses its own connection to renew
only lease rows. The worker coordinator and its single bounded drive slot each use
their own store/connection. Session writes commit only when the transaction has
verified the database lease owner, epoch and unexpired deadline; a renewal affects
liveness, while that database fence prevents a stale owner from writing. Hosts
still exclusively own the shared raw connection for atomic admission; the SDK
does not promise concurrent native transactions on that connection.
