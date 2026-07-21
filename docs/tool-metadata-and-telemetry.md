# Tool Metadata And Execution Telemetry

Contract `1.0.1` defines one typed, task-neutral declaration for host policy and
execution telemetry. The framework does not inspect prompts, infer semantics
from tool names or arguments, or decide whether a business answer is complete.

## Typed Declaration

`ToolMetadata` is a closed object with five fields:

- `side_effect`: `unknown`, `none`, `read`, `write`, `execute`, `network`, or
  `external`;
- `idempotency`: `unknown`, `supported`, or `unsupported`;
- `terminal`: whether the tool may return `finish` or `wait_user`;
- `capability_tags`: opaque exact-match host labels;
- `cost_dimensions`: opaque exact-match resource names.

This declaration is the only source of typed idempotency. There is no separate
tool-level idempotency input or run-definition field. An omitted declaration
has neutral effective values: `unknown`, `unknown`, `false`, and empty lists.
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
handoff targets, and distributed workers inherit the effective parent denials
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
4. `tool_call_completed`, after a `ToolExecutionResult` exists

Invalid serialized arguments fail before planning. An unknown tool, policy
denial, or approval short-circuit emits planned plus completed without a
started event. Cancellation, process loss, or another exception after started
may leave no completed event; the checkpoint operation journal is authoritative
for ambiguity and recovery.

Planned and started events contain normalized arguments and optional typed
metadata. Completed events always contain status, directive, nullable error
code, `execution_started`, nullable `duration_ms`, and optional typed metadata.
The objects are closed. Missing required fields and unknown fields are rejected.

Status values are `success`, `error`, `wait_response`, `running`, and
`pending_compress`. Directive values are `continue`, `finish`, and `wait_user`.
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

## Checkpoint Projection

The current run definition freezes `tool_metadata` for every tool, using null
when no declaration exists, and freezes all four metadata policy fields. There
is no duplicate idempotency projection. Resume requires the exact current run
definition schema and compares the current declaration and policy with the
stored definition before claim or any external operation.

Checkpoint objects are closed. Missing fields, stale schemas, and unknown
fields fail before claim. The runtime does not default an older definition,
rewrite a stored digest, or run a migration.

## Required Producer Evidence

Both implementations must prove:

- normalization and limits through real public tool constructors;
- denial accumulation through Agent, Runner, per-run, distributed,
  configured-child, agent-as-tool, handoff, schema-planner, and executor paths;
- planned/started/completed ordering for success, denial, approval, unknown
  tool, error, timeout, and cancellation boundaries;
- strict event round-trip and App Server projection;
- current run-definition bytes and resume mismatch checks;
- neutral behavior when typed metadata is omitted.
