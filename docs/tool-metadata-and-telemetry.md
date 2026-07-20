# Tool Metadata And Execution Telemetry

Contract `0.8.x` defines optional host-visible tool declarations, policy fields
that can only deny declared capabilities, and an executor lifecycle that
distinguishes planning from actual effects. The capability is task-neutral. It
does not inspect prompts, infer semantics from names or arguments, or decide
whether an answer is complete.

## Typed Declaration

`ToolMetadata` is a closed object with five fields:

- `side_effect`: one coarse value from `unknown`, `none`, `read`, `write`,
  `execute`, `network`, or `external`.
- `idempotency`: `unknown`, `supported`, or `unsupported`.
- `terminal`: whether the tool may return `finish` or `wait_user`.
- `capability_tags`: opaque exact-match host labels.
- `cost_dimensions`: opaque exact-match names of resources the tool may
  consume.

The declaration is not part of the model-visible function schema. It does not
measure cost, grant a capability, or cause a terminal transition. In
particular, `terminal=true` never ends a run by itself; only the existing tool
result directive and completion policy can do that.

The side-effect values have no built-in hierarchy. The framework does not
promote `network` to `external`, derive `write` from an argument, or guess a
value from a tool name. Hosts that need more than one orthogonal label use
opaque capability tags.

Generic `metadata` remains an independent compatibility field. Keys such as
`side_effect`, `terminal`, or `capability_tags` inside that mapping never become
a typed declaration.

## Normalization And Limits

An omitted declaration stays absent. A present object fills omitted fields
with `unknown`, `false`, and empty lists. Fields outside the closed set are
rejected.

Tags and cost dimensions are normalized identically in both languages:

1. Trim only U+0009, U+000A, U+000D, and U+0020 from both ends.
2. Reject an empty value after trimming.
3. Reject values longer than 128 Unicode code points.
4. Remove exact duplicates.
5. Sort by UTF-16 code units.
6. Reject more than 32 normalized entries in either collection.

The explicit portable whitespace set avoids depending on language-specific
Unicode `trim` behavior. Collection limits apply after trimming and
deduplication.

The existing public `idempotency` input remains a compatibility alias. If the
typed declaration is absent, the legacy value remains effective but no typed
metadata object is fabricated for events. If a typed object is present and its
idempotency is `unknown`, a non-`unknown` legacy value becomes the normalized
effective value. If both inputs declare different non-`unknown` values,
construction fails before any model or tool operation.

When a typed object inherits the legacy value, its normalized typed
`idempotency` field is replaced with that effective value. The same effective
value is used by the executor, event metadata, and both run-definition
projections. Re-normalizing the result is byte-stable. When typed metadata is
absent, only the legacy run-definition field is written and event metadata
remains absent.

## Denial-Only Policy

`ToolPolicy` adds four fields:

- `denied_side_effects`
- `denied_capability_tags`
- `deny_terminal_tools`
- `denied_cost_dimensions`

List fields use the same trim, deduplication, limit, and UTF-16 sorting rules;
side-effect values must be from the closed enum. Across Agent, Runner default,
and per-run layers, lists form a set union and the boolean uses logical OR. A
later layer cannot remove a denial. Configured sub-agents, agent-as-tool runs,
and handoff targets inherit the effective parent denials and may only add more.
Both schema planning and executor dispatch enforce the resulting policy.
Distributed execution serializes the already effective policy rather than
creating a new permission layer.

The new checks are logically ANDed with existing allowed names, denied names,
argument predicates, approval, planned-name, budget, and runtime checks. They
never add a tool or bypass an existing check. Existing denial precedence is
preserved; metadata checks then use side effect, terminal, capability tag, and
cost dimension order. A metadata denial returns the existing
`tool_not_allowed` code and a typed policy source.

An absent typed declaration does not match any metadata denial. A present
declaration with `side_effect=unknown` can match an explicit denial of
`unknown`. Tags and cost dimensions are exact opaque strings; the SDK does not
interpret prefixes, wildcards, task categories, prices, or units.

## Executor Lifecycle

The typed event order for a normalized model tool call is:

1. `tool_call_planned`
2. zero or more existing approval events
3. `tool_call_started`, only immediately before the executor may cause effects
4. `tool_call_completed`, after a `ToolExecutionResult` exists

Invalid serialized arguments fail before planning and emit none of these
events. A valid call to an unknown tool is still planned and then completed
with `execution_started=false` and `tool_not_found`. Policy and approval
short-circuits likewise emit planned plus completed, with no started event.

Cancellation, process loss, or another exception after the started boundary
may leave a started event without a completed event. Checkpoint v2 operation
journals remain authoritative for ambiguity and recovery; telemetry does not
claim exactly-once execution.

Planned and started events contain normalized arguments and optionally the
normalized typed declaration. Completed events contain the lower-case tool
status, directive, nullable error code, `execution_started`, nullable
`duration_ms`, and optional declaration. Status values are `success`, `error`,
`wait_response`, `running`, and `pending_compress`; directive values are
`continue`, `finish`, and `wait_user`.

Contract 0.8 writers always include `directive`, `error_code`,
`execution_started`, and `duration_ms` on a completed event. Successful results
write `error_code=null`; calls that never crossed the started boundary write
`duration_ms=null`. Typed metadata remains omitted when it was not declared.
Legacy readers may accept completed events without the additive fields but may
not fabricate values for them.

Duration uses a monotonic clock from the started boundary to result creation,
floored to milliseconds and bounded by the JSON-safe integer maximum. It is
null when execution did not start. Event observation never changes the tool
result, policy, approval, completion, or event-store failure mode.

## App Server Projection

Planning intentionally has no App Server item notification and can never be
presented as execution. The App Server may retain planned arguments internally
for a later approval request, but it does not persist or publish a planned item.
Existing started/completed item notifications retain their lifecycle. Additive
fields live inside the tool-call item payload: `toolMetadata` on started and
completed items, plus `directive`, `errorCode`, `executionStarted`, and
`durationMs` on completed items. A denial has only a failed completed item; a
legacy completed event keeps the legacy payload without fabricated fields.
Older clients may ignore the additions.

## Checkpoint V2

New run-definition writers freeze `tool_metadata` for every tool, using null
when no typed declaration exists, and freeze all four metadata policy fields.
They continue to retain the legacy `idempotency` projection. Resume compares
the current effective declaration and policy with the stored definition before
external operations.

Older checkpoint v2 definitions without these additive nested fields remain
readable with absent/empty/false defaults. A reader first verifies the digest
against the stored definition, adds defaults only to an in-memory comparison
copy, and compares that copy with the current effective definition. The stored
definition and digest are never rewritten. Non-default current metadata or
policy still causes `checkpoint_definition_mismatch` before claim or external
operations. Generic tool metadata is never promoted during resume.

## Required Producer Evidence

Both implementations must prove:

- normalization, limits, alias fallback, and conflict rejection through their
  real public tool constructors;
- cumulative denial-only policy through Agent, Runner, per-run, distributed,
  configured-child, agent-as-tool, handoff, and executor paths;
- planned/started/completed ordering for success, denial, approval, unknown
  tool, error, timeout, and cancellation boundaries;
- event round-trip and App Server projection without presenting planning as
  execution;
- run-definition canonical bytes and resume mismatch checks with typed
  declarations and metadata denials, including exact 0.7.1 legacy bytes and
  digest preservation;
- unchanged model-visible schemas and unchanged behavior when metadata and new
  policy fields are absent.
