# Session consumers and projections

The [session kernel](session-kernel.md) owns execution truth. Named consumers
retain separate acknowledged ordered prefixes; a batch preserves entire commits
with inclusive first/last positions. A host transaction SHOULD commit projection
and ACK together, and rollback MUST restore both. Consumer work requires no
execution lease. Wake is a hint; scanning recovers due work, queued inputs,
dependency changes and consumer lag, including unprojected terminals. No-deadline
waits and unresolved dependencies MUST NOT spin.

Host wake MUST take the turn lock and either mark an active handle or start normal
recovery/pumping. Only active execution is coalesced. An idle pump is allowed and
MUST NOT repeat model, tool or receipt effects. Predicting work from positions,
runnable flags or an enumerated descendant set MUST NOT gate correctness.
Input push MUST NOT create a new root execution: its interactive session,
App Server pump/recovery or host SQL scheduler owns run creation.

An active local handle retains a rerun-requested marker protected by scheduling
lock B. Before an exit pass it clears the marker under B, releases B and performs
one full idempotent tree drive, including retained independent children and
terminal delivery. It may mark done under B only if this whole pass made no
progress and the marker stayed clear. Driver steps and committed input/delivery
changes are progress; a deferred unchanged input is not. A live child worker owns
its subtree and retains the same handshake. Store-scheduled polls MUST run when
due and park at the next deadline after Accepted. No path holding B may acquire
a store connection or transaction lock S, resolve bindings or scan delivery.
Child registration validates worker identity under B after all store reads and
binding resolution outside B.
An exit pass bound to an ended turn MUST leave a queued successor immediately
schedulable. It MUST NOT admit that turn or apply an idle poll deferral to it.
Independent new-turn inputs belong to that successor; the ended turn may still
consume its late receipts and controls.
Each handle owns its root SID and records descendant SIDs under B immediately
before actually reading/driving them. A local child wake may mark that unfinished
observer when there is no direct child worker. This routing set never decides
whether recovery or an exit pass runs: an input before registration is seen by
the actual read, and an input after registration marks an active observer.

App Server admission and provider receipt wakes MUST occur after the outermost
transaction commits. When a handle has ended but its pump still owns completion,
that pump retains a wake marker under the turn lock and performs recovery before
releasing ownership. A later host wake starts ordinary recovery. Wake failures,
including corrupt data, MUST be reported as controlled errors with the target
session identity; they MUST NOT be swallowed or treated as absence of work.
An accepted wake during active execution also survives until completion can hand
remaining input to a new owner. Completion without such a wake automatically
continues follow-ups; independent user submissions retain their own host owner.

Admission within a nested or externally owned transaction MUST NOT synchronously
wait for the local turn owner. A host MAY coalesce a recovery hint until its
outer transaction has ended, then recover against committed state. Savepoint
release is not outer commit. Outer rollback, savepoint rollback and commit
failure MAY leave an empty recovery hint, but MUST NOT dispatch rolled-back
inputs or publish a successful terminal for them. A concurrent new host
transaction after the scheduling check MUST NOT expose its uncommitted state to
execution or notification projection. Deferred hints retain their root and target
session identities, work without subscribers, and remain independent of lease
expiry scheduling. Closing a node discards its local hints, not durable inputs;
another node or the host scheduler can recover committed work.
The commit fence MUST cover the actual admission transaction, including one on
a scoped callback connection; switching execution connections MUST NOT bypass
that transaction's visibility boundary.

Startup failure before a worker actually starts MUST retain the original error,
mark the unstarted handle done and notify its waiters under B/condition without
store reads or host callbacks. Cleanup MUST compare the published owner identity
and MUST NOT remove another handle. The completion consumer MUST exist before
worker execution can start; a started worker retains ordinary completion
ownership through failures and MUST NOT be marked done by startup cleanup.
Startup callback defects MUST escape once without recursive warning delivery or
a guessed failed business terminal.
If the request has already attempted its admission ACK, a later startup callback
defect MUST preserve the original exception without sending a second RPC response.

An asynchronous completion failure MUST release its local owner and report a
controlled error with the session identity. Once an execution/read error has
been reported, completion MUST NOT reread untrusted state to infer a failed
terminal or repeat the warning. Missing bindings and invalid provider results
retain their existing wait/error semantics. Only verified retained records may
supply terminal lifecycle notifications; independent observers can publish them
after storage recovers. Completion read/projection error boundaries MUST NOT
swallow notification callback defects.

Interactive idle steer starts through its session's own run lifecycle. Accepted
cancellation intent MUST identify the target turn; before initial admission it
binds only the reserved run. Publication MUST discard an intent for an ended
turn, never cancel a different turn or its token, and use the ordinary targeted
cancel path outside session/B locks. Pending cancellation remains owner work
while its target turn is active. Parent recovery scans terminal delivery even
when no child worker is needed, retaining atomic push and ACK deduplication.

Tool completions use the bounded [tool result projection](tool-results.md).
Raw result bodies and private resource locators MUST NOT travel in the
`tool_result` diagnostic. Reprojection changes event bytes under stable IDs;
hosts with immutable materialized events must account for their own projection
version boundary, independently of kernel record schema versions.

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
| Completion | Child terminal input and child_delivery ACK MUST be atomic. Authenticate original child session/turn/generation, parent delivery target, terminal position/digest/status/result. Same-ID same-byte delivery replays; altered bytes conflict. A blocking batch needs every authenticated sibling terminal for its real completion result; a [declared observation](yieldable-waits.md) MAY instead yield to steer without ending the children. |
| WAIT_USER | Keep intermediate wait on the child. Host reply targets child session/turn/interaction; parent remains parked until authenticated terminal or the declared observation yields. Yielding does not answer the child. A child's later continuation MUST NOT replace the original terminal named in the handle. |
| Background | Initial admission receipt is deterministically running. Poll/wait reads records; cancel writes inbox. Reconstructed handles read the same identity. Notification reaches the next safe model boundary; delivery after owning turn ends is audit-only and cannot start a new turn. |
| Cancellation | Parent cancellation, abort or failure MUST atomically enqueue stable targeted cancellation for live descendants, including background children; each child propagates it. No-start child cancels before dispatch. Unknown dispatched child effects stay unconfirmed until terminal evidence, then audit. |
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

## Custom child batches

A custom child callback MAY return one child specification or a nonempty sequence.
Every member MUST be a child specification with the same background flag. Empty,
invalid-member and mixed-background batches raise a typed invalid-batch error
before child creation or parent park. Callback host SQL writes, every child and
initial input, parent started/parked records and background result MUST commit
in one transaction or roll back together. Nontransactional effects inside the
callback have no rollback guarantee and MUST NOT be used for admission. Custom
and delegated batches use the same siblings, completion, cancellation and
late/duplicate evidence rules.

## Isolated supervision and retry

A scan MUST handle later items after any individual runtime factory, drive,
projection or dispatch exception and MUST surface all failures after the scan.
The host MAY supply dispatch(session identity) instead of inline execution. In
dispatch mode the scanner MUST NOT construct runtimes or execute drives. Scan
time is independent of drive duration; SQL, dispatch and inline projection
callbacks MUST have host-enforced bounded I/O timeouts. Inline execution remains
the default for in-process hosts and cannot bound scan time independently of
drives. No thread pool or cancellation of arbitrary host code is implied.

Scheduled execution resolves the runtime factory under a lease. Lease renewal
MUST start before calling the factory and continue through preparation until
execution's heartbeat takes over. The starting TTL is explicit and documented;
it is a renewable ownership interval, not a preparation deadline. The returned
runtime's TTL MUST apply at handoff. Renewal uses an independent store connection
(or the memory store's serialized connection). If renewal fails or the epoch is
fenced, the factory result MUST NOT grant execution authority. Every factory
exit MUST stop and join its renewal worker; exception and not-ready deferral and
release MUST use the most recently renewed lease, with normal fencing checks.
Host callbacks and SQL still require bounded I/O; arbitrary factory code cannot
be forcibly cancelled and MUST NOT dispatch execution effects during preparation.

State reads MUST capture one committed record head, inbox watermark and lease
epoch, then read, validate and fold the immutable prefix without holding the
session row lock. Record sequences MUST be bounded by the captured head;
consumed inputs MUST be bounded by that head and the captured inbox watermark.
Later appends, inputs or consumption cannot enter that result. Digest, gap and
reducer validation remain required. Snapshot copying, projections and scans
MUST NOT hold the session row while doing history-sized read work. Mutations
that prepare from history MUST recheck their captured position under the write
lock before committing. Transactional admission and new-record validation keep
their atomicity and fencing requirements.

A typed
not-ready exception with positive integer retry_after_ms MUST defer admission or
the existing turn without a failed terminal or consuming pending input. Other
factory/driver exceptions back off and re-raise. A retry gate MUST cover ready
inbox, due schedules, direct wakes and duplicate lease acquisition. A stale or
expired lease MUST NOT defer work. Deferral MUST preserve every newer execution
schedule and MUST NOT rewrite the log. Consumer failure backoff is independent
of execution leases and other consumers. Backoff expires using database time;
work MUST become discoverable again without a new external signal.

Dispatch itself is at least once, not a queue claim. Hosts MUST bound queued
not-yet-leased duplicate messages with expiry no longer than the scan interval,
or equivalent coalescing, including wake deliveries; bound prefetched/reserved
work too. Lost/expired messages remain runnable for the next scan. Host queue
latency, callback/SQL timeouts and inline-mode drive time are separate from the
beat interval. Fixtures: session_supervision.json; real producer acceptance
requires the Python batch, supervisor and fake transport suites on both stores.

Model selection is session-local durable execution state. Consumers MUST attribute
model-call usage/backend/model from the original planned request, including late
receipts and replay; current selection is never a billing source. Child sessions
retain their own selection state and do not inherit later parent inputs.

User questions project the same retained form in status, snapshot state and event metadata.interaction. See [interactions](interactions.md). Ordinary child messages enqueue steering and cannot infer a human-wait target. Parent terminal driving must process its descendants' queued cancellation controls; a WAIT_USER child never supplies a terminal parent result.
