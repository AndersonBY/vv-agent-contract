# Tool Metadata And Execution Telemetry

Contract `24.0.0` defines one typed, task-neutral declaration for host policy,
tool-result retention, and
execution telemetry. The framework does not inspect prompts, infer semantics
from tool names or arguments, or decide whether a business answer is complete.

## Typed Declaration

`ToolMetadata` is a closed object with six fields:

- `side_effect`: `unknown`, `none`, `read`, `write`, `execute`, `network`, or
  `external`;
- `idempotency`: `unknown`, `supported`, or `unsupported`;
- `terminal`: whether the tool may return `finish` or `wait_user`;
- `result_retention`: `archive` allows archive-backed microcompaction and
  `preserve` keeps results inline during proactive microcompaction;
- `capability_tags`: opaque exact-match host labels;
- `cost_dimensions`: opaque exact-match resource names.

`result_retention` is task-neutral. The runtime never infers it from a tool
name, arguments, response format, or task description. Missing metadata uses
`archive`, so built-in and custom tools participate uniformly unless the tool
explicitly declares `preserve`. Preservation applies only to proactive
microcompaction; full summary and emergency recovery may replace history only
after an accepted summary includes every removed pair and retains its recovery
references. Failure preserves history.

This declaration is the only source of typed idempotency. There is no separate
tool-level idempotency input or run-definition field. An omitted declaration
has neutral effective values: `unknown`, `unknown`, `false`, `archive`, and
empty lists.
The declaration may remain omitted on event and persistence projections; its
effective behavior is still the neutral default.

Typed metadata is not model-visible. It cannot grant a capability, measure a
cost, or trigger a terminal transition. In particular, `terminal=true` does
not stop a run; only a tool result directive or the completion policy can do
that. Side-effect values have no hierarchy and are never inferred.

Generic `metadata` remains independent host data. Keys inside that map never
become typed declarations.

## Normalization And Limits

A present object fills omitted fields with neutral defaults and rejects fields
outside the closed set. Tags and cost dimensions are normalized identically in
both languages:

1. Trim U+0009, U+000A, U+000D, and U+0020 from both ends.
2. Reject an empty value after trimming.
3. Reject values longer than 128 Unicode code points.
4. Remove exact duplicates.
5. Sort by UTF-16 code units.
6. Reject more than 32 normalized entries in either collection.

The portable whitespace set avoids language-specific Unicode trim behavior.
Collection limits apply after trimming and deduplication.

## Denial-Only Policy

`ToolPolicy` has four metadata denial fields:

- `denied_side_effects`
- `denied_capability_tags`
- `deny_terminal_tools`
- `denied_cost_dimensions`

List fields use the same normalization rules. Across Agent, Runner default,
and per-run layers, lists form a set union and the boolean uses logical OR. A
later layer cannot remove a denial. Configured sub-agents, agent-as-tool runs,
handoff targets, and child sessions inherit the effective parent denials
and may only add more.

Schema planning and executor dispatch both enforce the effective policy. These
checks are combined with allowed names, denied names, argument predicates,
approval, budgets, and runtime checks. They never add a tool or bypass another
check. A denial returns `tool_not_allowed` with a typed policy source.

An omitted declaration does not match metadata denials. A present declaration
with `side_effect=unknown` can match an explicit denial of `unknown`. Tags and
cost dimensions remain exact opaque strings; there are no prefixes, wildcards,
task categories, prices, or inferred units.

## Executor Lifecycle

The event order for a normalized model tool call is:

1. `tool_call_planned`
2. zero or more approval events
3. `tool_call_started`, immediately before effects may occur
4. a retained parked handle when accepted without a definitive result
5. `tool_call_completed` after authentic definitive receipt

Invalid serialized arguments fail before planning. An unknown tool, policy
denial, or approval short-circuit emits planned plus completed without a
started event. A parked operation retains its provider/approval/user/child handle without
fabricating a completed result. Cancellation or process loss after started may
leave unknown effects; the session records are authoritative for recovery.

Planned and started events contain normalized arguments and optional typed
metadata. Completed events always contain status, directive, nullable error
code, `execution_started`, nullable `duration_ms`, and optional typed metadata.
The objects are closed. Missing required fields and unknown fields are rejected.

Completed status values are `success`, `error`, `wait_response`, `running`,
and `pending_compress`. Parked handles are not completed results. pending_compress remains internal automatic
compaction. Hosts may expose a tool that returns the compaction intent described below. Directive values are `continue`, `finish`, and `wait_user`.
Successful results use `error_code=null`; calls that did not cross the started
boundary use `duration_ms=null`.

Duration uses a monotonic clock from the started boundary to result creation,
is floored to milliseconds, and is bounded by the JSON-safe integer maximum.
Telemetry never changes a tool result, policy, approval, completion decision,
or event-store failure mode.

## App Server Projection

Planning has no App Server item notification and is never presented as
execution. Started and completed item notifications use the current closed
payload. `toolMetadata` is present when declared; completed payloads also carry
`directive`, `errorCode`, `executionStarted`, and `durationMs`.

A denial therefore has only a failed completed item. The App Server does not
decode an older reduced payload or fabricate missing fields.

## Frozen policy and recovery

The logical definition freezes each tool declaration (null if absent) and every
metadata policy field. Resume rechecks current authorization without relaxing
frozen denial. Typed idempotency is the only declaration: unknown tools auto-retry
only with supported frozen metadata and actual provider support for the stable
`{session_id}/{operation_id}` key. Ordinary tools allow one retry. Prepared hook
results are reused; committed receipts cannot be rewritten or charged twice.
See [session kernel](session-kernel.md).

## Required Producer Evidence

Required implementations must prove:

- normalization and limits through real public tool constructors;
- denial accumulation through Agent, Runner, per-run, kernel,
  configured-child, agent-as-tool, handoff, schema-planner, and executor paths;
- planned/started/completed ordering for success, denial, approval, unknown
  tool, error, timeout, and cancellation boundaries;
- strict event round-trip and App Server projection;
- current run-definition bytes and resume mismatch checks;
- neutral behavior when typed metadata is omitted.


## Host-requested summaries

A successful tool completion may set `metadata.request_compaction` to `true`.
The kernel adds `metadata.compaction_source` with the tool operation ID and
context digest. The receipt records intent, not a summary or a paid call.
After the batch completes, the driver runs an ordinary tools-free compaction
operation, then accepts `context_compacted` and completes memory telemetry
before the next primary cycle. Requests in one batch coalesce. A threshold
trigger in that cycle shares the same operation. Finish and wait-user take
precedence: no summary runs before the turn ends or parks. Finish discards
remaining intent; wait-user defers it until a valid reply resumes the same turn.

Empty or ineligible history, a rejected summary, or an exhausted failed summary
keeps the context and consumes the request. A committed source request is never
replanned after restart. Unknown tools retain their existing fences.

A host child binding may require a fresh summary before admission. The driver
freezes the source history and digest in a tools-free `purpose=compaction`
operation with `metadata.mode=child_summary`. It includes the full parent
history available before that tool's admission, including the recent tail.
It does not replace parent context or consume the parent's unresolved tool outcomes.
The child callback receives the accepted
summary text and reads no provider. Admission and host child input commit in
one transaction. If the summary is invalid, cannot fit, fails, or exhausts
Unknown retries, the tool fails with `child_summary_unavailable`; no child is
admitted. Every real request follows the existing endpoint attempt, accounting
and Unknown rules. A saved receipt is reused after a crash.

Both paths use existing record schema 1 and inbox schema 3. Request metadata and
tool result metadata are extension maps; no new record kind or directive is
needed. A 0.26 reader can load these records, but ignores the new tool intent
and does not enforce the new child dependency. Hosts must use the new runtime
for these capabilities and must not downgrade a session with pending intent.
