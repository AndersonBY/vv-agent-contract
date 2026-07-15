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

## Allowed Language Adaptations

Language-idiomatic names, builders, async forms, and type representations are
allowed when both implementations can express the same input, observe the same
output, and enforce the same safety and lifecycle boundaries. Every adaptation
must be recorded in the parity contract or an implementation mapping document.
