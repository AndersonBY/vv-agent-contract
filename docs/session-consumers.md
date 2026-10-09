# Session consumers and projections

The [session kernel](session-kernel.md) owns execution truth. Named consumers
retain separate acknowledged ordered prefixes; a batch preserves entire commits
with inclusive first/last positions. A host transaction SHOULD commit projection
and ACK together, and rollback MUST restore both. Consumer work requires no
execution lease. Wake is a hint; scanning recovers due work, queued inputs,
dependency changes and consumer lag, including unprojected terminals. No-deadline
waits and unresolved dependencies MUST NOT spin.

External delivery before ACK is at least once. A crash may duplicate delivery;
stable record/event/item IDs provide deduplication. An ACK proves consumption,
not successful notification or business acceptance. Event stores are projection
and sink capabilities: SessionRunEventStore and a JSONL sink do not introduce a
second execution or event ledger.

Tracing retains a separate cursor and commits ACK before invoking nontransactional
processors. Delivery is at most once: an ACK-to-dispatch crash or processor failure
may lose telemetry. Ambient transactions that can roll back a delivered span MUST
be rejected. Detached span data never grants execution authority.

## Children, host state and projection requirements

| Area | Requirement |
| --- | --- |
| One delegation mechanism | create_sub_task, configured children, Agent.as_tool, BackgroundAgentTask and handoff MUST share atomic admission, independently scheduled child session and terminal delivery. No recursive Runner or child execution under the parent lease. |
| Admission | Child creation, frozen definition/input, parent started/parked records and background admission result MUST commit together with applicable host writes. Child principal inherits parent; policy/budget/workspace/model/prompt/JSON state freeze before admission. |
| Completion | Child terminal input and child_delivery ACK MUST be atomic. Authenticate original child session/turn/generation, parent delivery target, terminal position/digest/status/result. Same-ID same-byte delivery replays; altered bytes conflict. A blocking batch needs every authenticated sibling terminal. |
| WAIT_USER | Keep intermediate wait on the child. Host reply targets child session/turn/interaction; parent remains parked until authenticated terminal. A child's later continuation MUST NOT replace the original terminal named in the handle. |
| Background | Initial admission receipt is deterministically running. Poll/wait reads records; cancel writes inbox. Reconstructed handles read the same identity. Notification reaches the next safe model boundary; delivery after owning turn ends is audit-only and cannot start a new turn. |
| Cancellation | Parent closure MUST atomically enqueue stable targeted cancellation for live descendants, including background children; each child propagates it. No-start child cancels before dispatch. Unknown dispatched child effects stay unconfirmed until terminal evidence, then audit. |
| Handoff | Terminal child continuation; source does not resume model work. Use admission-derived count/maximum even after higher live configuration. Over-limit is durable failed result. Validate target execution/output, not the source's temporary transfer marker. |
| Host bindings | Durable shared_state/result state is JSON-only. Hosts re-supply required object references through Runtime.host_bindings. Missing names raise MissingHostBinding before execution; no shadowing durable keys, replacement/deletion, pickle or transaction rollback promise for object mutation. |
| Events/results | Pure projection of a consistent retained prefix; old results stop at their original terminal prefix. Events are at least once with stable IDs; child admission/completion belong to parent run and carry child identity. No second event or thread ledger. |
| Event identity | Current projection uses `sk/{D([session_id,record_id])}/{slot}`; slot distinguishes event/agent/diagnostic/etc. Memory lifecycle projections preserve the event identity retained in the committed memory boundary snapshot. Call ID is `{operation_id}/{attempt}`; App Server item ID is `item_{event_id}`. Replay preserves retained timestamp and identity. |
| Live streaming | Assistant/reasoning/tool deltas are volatile, optional and ordered within delivery. Sink loss MUST NOT affect definitive receipt content or recovery. |
| Tracing | Separate traces cursor MUST commit ACK before nontransactional processors. At most once; ACK-to-dispatch crash or processor failure may lose telemetry. Reject ambient transactions that could roll back an already delivered span. Stable spans and detached data do not grant state authority. |

Fixtures: `session_projection.json`, `session_semantics.json`,
`configured_sub_agent.json`, `configured_sub_agent_events.jsonl`,
`public_configured_sub_agent.json`, `manager_tool_envelope.json`,
`handoff_contract.json`, `runner_trace.jsonl` and `runner_trace_spans.json`.
