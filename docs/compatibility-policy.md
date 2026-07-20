# Compatibility Policy

## Versioning

The contract uses semantic versioning for observable behavior:

- **Major:** removes or renames a public capability, changes an existing wire
  meaning, rejects previously valid input, or otherwise requires callers to
  migrate.
- **Minor:** adds an optional capability, field, event, operation, tool, or
  behavior without changing existing valid behavior.
- **Patch:** corrects an inconsistency, tightens evidence, or clarifies wording
  without intentionally changing the supported public capability set.

Fixture movement alone does not determine the version bump. Classify the
observable behavior represented by the fixture.

## Adoption States

- `pending-adoption`: the immutable contract version exists, but one or both
  implementation branches do not yet pin it.
- `in-progress`: both adoption changes are known, but implementation or full
  gate evidence is incomplete.
- `verified`: both repositories pin the exact same contract revision and pass
  producer, full-repository, fixture, and cross-repository checks.
- `superseded`: a later verified contract version replaces this version.

Separate repositories cannot merge atomically. During adoption, one default
branch may briefly point to a newer contract. Release workflows must therefore
accept only a version recorded as `verified` in the central support matrix.

Before a newly introduced minor capability reaches its first `verified`
adoption, a patch may close a safety or producer-evidence defect in that
still-unsupported capability. This exception is limited to the same pending
minor line: the earlier artifact stays immutable, implementations must not ship
it as supported, the patch must document migration for experimental records,
and the latest patch must pass paired adoption. Once any version in the minor
line is `verified`, ordinary semantic-versioning compatibility applies without
this exception.

## 0.2 Token Usage Compatibility

Contract `0.2.x` adds `usage_source` and `cache_usage` without removing or
changing the existing numeric token fields. A `0.1.x` payload therefore
decodes as `accounting_missing` for the new observation while retaining its
legacy values. A `0.2.x` decoder must preserve `null` cache readings and must
not derive availability from legacy zero values.

Writers continue to emit `cached_tokens` and `cache_creation_tokens` during
the `0.x` compatibility period. Readers that require a reliable cache hit rate
must use `cache_usage.status` and the nullable typed readings; the legacy
projection alone cannot distinguish zero from unavailable accounting.

## 0.3 Completion Policy Compatibility

Contract `0.3.x` exposes the runtime's existing no-tool policy through public
Agent and RunConfig APIs. Omitting every policy layer remains equivalent to
`continue`, including the existing continuation hint and max-cycle behavior.
The runtime does not inspect assistant text to decide whether a task is done.

`completion_reason`, `partial_output`, and `completion_tool_name` are additive
result and protocol fields. A `0.3.x` reader accepts older payloads where they
are absent. New producers populate a typed reason for every terminal result;
`partial_output` is nullable and never replaces the compatibility
`final_answer`, `wait_reason`, `error`, or `final_output` fields.

The `budget_exhausted` reason is reserved by the enum for contract `0.4.x` and
must not be emitted before a configured budget actually terminates a run.

Patch-level `0.3.x` closure may tighten decoding of the additive completion
fields to their already declared string-or-null types and enum values. Unknown
top-level RunEvent fields remain forward compatible, but invalid values in a
known completion field are rejected instead of being silently dropped.

Approval resume keeps the existing public capability set while making
lifecycle ordering explicit: the resumed operation has a fresh run id in the
source trace and a full configured cycle budget, new input is rejected before
cancellation projection or the approval claim, and a pre-cancelled resume with
valid input emits a fresh cancelled terminal without side effects.
Output guardrail allow rewrites preserve the runtime-owned completion
observation. These are patch corrections because they close inconsistent
producer behavior for the `0.3.0` completion surface rather than introducing a
new control.

App Server continues to use its existing `completed`, `failed`, and
`interrupted` turn statuses. A waiting Agent maps to `interrupted` without an
error, while cancellation remains `failed`. The existing
`sub_task_wait_user` code is scoped to the synchronous parent-tool envelope;
internal waiting sub-agent outcomes retain null error fields.

Distributed workers retain the existing lease/CAS capability while closing
side-effect ordering gaps. A worker renews its claim once before entering a
cycle and keeps the heartbeat active through checkpoint commit. Initial or
periodic renewal failure cannot revive an expired owner, and all lease expiry
values are capped by the job deadline. This is a patch correction to the
existing distributed-runtime guarantee; it adds no wire field or scheduler
control.

## 0.4 Run Budget Compatibility

Contract `0.4.x` adds optional `budget_limits` and `host_cost_meter` controls.
Omitting them, or supplying an empty limits object, performs no budget
accounting, emits no budget events, and preserves the existing terminal and
event order. Per-run limits replace a configured Runner default as one object;
individual fields are not implicitly merged.

Budget usage and exhaustion are additive nullable result, event, checkpoint,
and App Server fields. Older payloads without them remain readable. A 0.4
producer emits `CompletionReason.budget_exhausted` only when a configured limit
or strict unavailable-metric policy stops the run. The Agent status remains
`failed`, so older status consumers do not mistake a resource stop for
business completion.

All wire counters and micro-unit amounts are bounded by the JSON-safe integer
maximum `9007199254740991`. A host cost unit or currency is never converted.
Missing token or cost accounting remains null and is never reconstructed from
legacy zero values.

The additive budget state in checkpoint v1 supports cumulative distributed
enforcement. It does not promise checkpoint v2, exact resume, event outbox
delivery, or exactly-once external side effects.

Patch-level `0.4.x` closure may add typed unavailability for arithmetic that
cannot fit the already declared JSON-safe range and may fix sampling/order
wording without changing the limit fields or default behavior. Implementations
adopt the latest immutable patch before marking the 0.4 capability verified.

## 0.5 Durable Resume Compatibility

Contract `0.5.x` adds checkpoint v2 only when a `CheckpointConfig` is
supplied. Omitting it preserves checkpoint v1, Runner, event, terminal, and
App Server behavior. V2 uses an independent SQLite table and Redis key
namespace; an older binary therefore cannot overwrite an enabled v2 run.

An absent checkpoint schema discriminator continues to mean v1. A present
unknown discriminator is rejected and never retried as v1. A v1 non-terminal
record cannot be migrated automatically because it cannot prove that no
external operation ran after the last cycle commit. V1 terminal migration is
explicit and replay-only.

Checkpoint v2 has a separate `run_definition_schema` discriminator. Contract
0.5.1 fixes it to `vv-agent.run-definition.v1`, embeds the credential-redacted
definition, and uses RFC 8785 JCS. A 0.5.0 v2 record without that field and
embedded definition, or a record with an unknown value, requires
explicit host migration and fails closed before claim or external operations.
Contract 0.5.0 never reached `verified`; 0.5.1 is the first eligible adoption
target for the 0.5 capability.

Contract 0.5.2 adds two store operations without changing checkpoint wire
fields: claimed terminal finalization and durable outbox-delivery recording.
They close lifecycle paths required by 0.5.1 but not executable through its
store protocol. Implementations adopting checkpoint v2 must target 0.5.2 or a
later compatible patch; 0.5.1 remains immutable and unverified.

Contract 0.5.3 corrects the previously contradictory terminal-order fixture,
requires append-once session persistence when checkpoint v2 and a session are
combined, and closes the already-declared approval-resume producer path. It
also makes checkpoint outbox event identities unique. These are patch-level
closures because no 0.5 version has reached verified adoption and the 0.5.0
surface already required durable session, approval, and outbox behavior.

Contract 0.5.4 exposes the missing `credential_slots` producer input already
required by the 0.5.1 run-definition rules. Its empty default changes no
existing request. The pending 0.5 capability must adopt 0.5.4 or later rather
than inferring credential locations from key names.

Contract 0.5.5 corrects a placeholder payload digest in the canonical
checkpoint fixture. Implementations must adopt it so strict outbox-integrity
validation can run against canonical bytes.

Contract 0.5.6 closes an existing reasoning-history inconsistency. A non-empty
private reasoning field already exists in the shared Message and session wire
shape; the patch makes both runtimes retain it consistently and requires a
provider-valid OpenAI-compatible projection when visible content is empty. It
adds no task policy, retry policy, public control, or wire field.

`reconciliation_required` is a resumable interruption, not a business failure
or completion. It has no `completion_reason`. Public result fields are
additive and null when checkpoint v2 is disabled; checkpoint v1 bytes remain
unchanged, and absent App Server checkpoint summaries are omitted.

Stable idempotency keys allow a cooperating tool or provider to deduplicate an
effect. The framework does not infer idempotency from names or arguments and
does not claim arbitrary exactly-once semantics. A committed receipt is
replayed; a started operation without a receipt becomes ambiguous and follows
the explicit retry or reconciliation policy.

Checkpoint lifecycle events are accepted once only through an
`IdempotentRunEventStore`. Existing callbacks and ordinary event stores remain
at-least-once. Terminal acknowledgement marks the v2 record acknowledged but
does not delete it; retention cleanup is an explicit host operation.

## 0.6 After-Cycle Lifecycle Compatibility

Contract `0.6.x` adds after-cycle hooks only when a Runner default or per-run
hook is explicitly supplied. With no configured hook, runtimes do not invoke a
callback, create lifecycle control state, emit lifecycle logs, alter tool
policy, replace the existing continuation hint, or change native terminal
projection.

Hook decisions are a closed additive control surface. They can append bounded
user steering for a next cycle, add exact tool names to an effective deny set,
or stop with the existing failed status/reason. They cannot return completed or
waiting, expand permissions, remove a denial, change approval policy, or
override cancellation, budget exhaustion, execution failure, wait-for-user,
or max-cycles boundaries.

The reserved `_vv_agent_after_cycle_control` shared-state value is absent until
a hook first narrows permissions. Readers that do not know the key already
preserve unknown shared state. Checkpoint v1/v2 therefore retain the deny set
without changing their wire schemas. Stateful host logic uses the existing
checkpoint-extension protocol and its version/size/required-state rules.

Distributed v2 adds `after_cycle_hook_refs` to the existing capabilities
object. Distributed v1 rejects the field as a v2-only capability. Missing
references fail during capability resolution before a claim or external
operation. Existing envelopes without the field decode to an empty list.

## Allowed Language Adaptations

Language-idiomatic names, builders, async forms, and type representations are
allowed when both implementations can express the same input, observe the same
output, and enforce the same safety and lifecycle boundaries. Every adaptation
must be recorded in the parity contract or an implementation mapping document.
