# Typed event stream

Current RunEvent v6 is a closed typed projection of session records. Every event
requires the current version, identity, required session_id and a finite
nonnegative created_at timestamp. Missing/stale/unknown/malformed versions,
retired kinds and unknown fields reject without alternate decoding. Full variants
and strict negatives are in `run_events.jsonl` and `run_events_invalid.json`.

RunConfig.stream and RunHandle observe the same surface. SessionRunEventStore is
projection/replay capability and the JSONL event sink is a delivery adapter;
neither is a second execution/event ledger. Event/result projections read a
consistent retained prefix; old results stop at their original terminal prefix.
Observers do not decide model/tool policy, completion, budgets or cancellation.
Observer failure is isolated from execution.

## Identity and delivery

Record-projected event ID is `sk/{D([session_id,record_id])}/{slot}`, with D the RFC8785/SHA-256
digest and slot distinguishing event/agent/diagnostic/etc. Call ID is
`{operation_id}/{attempt}`; App Server item ID is `item_{event_id}`. Retained
identity and timestamp survive replay. Memory lifecycle events retain the identity
of their committed boundary data.event snapshot; opaque snapshots are not reidentified. External event delivery before cursor ACK
is at least once, so consumers deduplicate by stable identity. Whole commits and
transactional cursor rollback follow [session consumers](session-consumers.md).

Child admission/completion is owned by the parent run and carries explicit child
identity. Child waits remain intermediate and parent adoption requires authenticated
terminal evidence. Definitive tool/model events derive from admitted operations and
retained receipts; replay adds no new attempt or receipt. Cancellation commits a
durable terminal; its observation cannot assert that unknown effects stopped.

## Live adapter boundary

| Private adapter source | Current typed event |
| --- | --- |
| assistant_delta | assistant_delta |
| reasoning_delta | reasoning_delta |
| tool_call_started | model_tool_call_started |
| tool_call_progress | model_tool_call_progress |

The adapter validates and projects only these source variants. Unknown, invalid or
lifecycle-shaped payloads are dropped; provider values cannot override framework
identity, agent, parent or positive cycle index. Raw provider payloads are private.
Model tool generation is distinct from actual tool execution.

Assistant/reasoning deltas carry delta and optional cumulative chars/token estimates.
Model tool deltas carry nonempty tool_call_id/tool_name and optional index,
arguments_chars/estimated_tokens. Counters are nonnegative JSON-safe integers;
unavailable values are omitted, never fabricated as zero. Deltas are optional,
volatile and ordered within delivery; sink loss cannot affect definitive receipt
content, state or recovery. Reasoning and diagnostics are private by default.

Diagnostic has required level (debug/info/warning/error), nonempty code and JSON
object details. details is the explicit extension map; it cannot override identity
or carry state authority. Content-free model accounting is specified in
[model-call accounting](model-call-accounting.md). Approval and tool events keep
the closed current telemetry fields in [tool metadata](tool-metadata-and-telemetry.md).

Tracing uses a separate ACK-first cursor, at most once. A crash after ACK or
processor failure may lose telemetry. Ambient rollback-capable transactions are
rejected before delivery; processors receive detached data. `runner_trace.jsonl`,
`runner_trace_spans.json`, `event_store_replay.jsonl` and `session_projection.json`
provide canonical evidence.
