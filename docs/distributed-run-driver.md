# Nonblocking Distributed Run Driver

The distributed run driver is the host-facing scheduler boundary for cycle-level
execution. It reuses the current distributed envelope, worker response, and
checkpoint protocols; transports do not create a second run state machine.

## Driver Operations

`start` receives a prepared run whose checkpoint has already been created or
admitted by the framework. It reads that authoritative checkpoint, enqueues at
most the next required cycle, and returns a passive `DistributedRunHandle`.
It never waits for the cycle result.

The public `start_distributed_compiled` entrypoint accepts an already-compiled
`AgentTask` (or the language-equivalent prepared-run value). The framework
consumes that prepared value as-is and must not compile it again or re-run
compile-time instruction/context producers. Python and Rust must expose
equivalent language-level APIs for this input; names and calling conventions
may follow language idioms, but the existing `vv-agent.distributed-run.v5`
envelope and all other wire shapes remain unchanged.

`advance` receives the previous envelope plus either one closed worker response
or an out-of-band transport failure. The observation is never authoritative.
The driver reloads the checkpoint exactly once and returns one decision:

- `dispatch`: enqueue the enclosed next-cycle envelope immediately;
- `retry_at`: enqueue the enclosed recovery envelope no earlier than the given
  Unix-millisecond deadline;
- `wait`: do not enqueue work while reconciliation, a deferred batch barrier,
  a host interaction, or a suspension remains unresolved;
- `finalize_required`: run the framework terminal controller for the verified
  candidate while retaining the worker claim;
- `terminal_replay`: return the exact retained durable terminal without running
  terminal processing again.

`DistributedBackend.resolve_controller_command(command)` is the public control
operation; `command.handle` is the only handle input. It delegates admission
to `CheckpointStore.admit_controller_command(command)` and returns one closed
`ControllerCommandResolution`: response/resume receipts produce an enqueue-only
`wake_after_controller_command` decision for the retained logical cycle;
suspend/cancel/abort produce no wake. A same-id replay returns the retained
receipt without a second wake. The receipt, checkpoint revision, event marker,
and wake outbox are one CAS transaction; a reaper recovers a crash before
enqueue.

A duplicate or out-of-order callback whose delivery has already been overtaken
returns `wait(reason=superseded_delivery)`. It does not enqueue an older cycle,
adopt a newer claim, or repeat terminal work.

`Runner.finalize_distributed` consumes only a verified `finalize_required`
decision. It runs as a separate bounded framework finalizer and supports both a
claimed worker terminal candidate and the unclaimed `max_cycles` candidate
synthesized after the last permitted committed cycle. It never waits for a
child task.

One invocation performs no polling, sleeping, result-backend `get`, or recursive
dispatch loop. The cycle callback is one bounded `advance` controller invocation:
it may enqueue the returned envelope or a separate bounded framework terminal
finalizer, but it may not execute terminal work itself or wait for either task
to complete.

## Passive Handle

`DistributedRunHandle` contains only `checkpoint_key`, `run_id`, and `trace_id`.
It owns no thread, task, cancellation token, approval broker, callback, runtime,
or mutable result. Status and result reads always come from the shared
`CheckpointStore`.

## Authority And Idempotency

After every committed, pending, candidate, replay, timeout, or transport-error
observation, the driver compares the observation with the authoritative
checkpoint before deciding. Duplicate and out-of-order callbacks therefore
cannot advance the checkpoint twice. An unexpired claim produces `retry_at`;
an expired claim produces a recovery envelope, while
`reconciliation_required` stops dispatch with `wait`; a deferred tool batch
stops dispatch with `wait(reason=deferred_pending)` until every current-batch
deferred journal entry has a definitive receipt. `deferred` is not claimable;
only the last resolution CAS returns the checkpoint to unclaimed `running` and
returns `DeferredResolveDecision.AppliedReady(receipt)`.

An ordinary definitive tool result is persisted immediately by the
`record_tool_receipt` mutation while retaining the worker claim. Admission of a
model-tool batch then uses one `admit_deferred_batch` CAS only for still-deferred
outcomes and releases the claim once; completed outcomes are rejected there as
already receipted. A worker response of `pending` means no cycle commit and no
response result were returned by this delivery attempt, not a terminal result. A
`DeferredResolveDecision.AppliedReady(receipt)` resolution does not poll or
wait for a worker:
the host reuses the retained previous envelope and pending observation in the
existing `advance` operation, or the running-checkpoint reconciler performs
that existing dispatch through the ordinary recovery claim path.

The same observation rule applies to `host_interaction` and `suspended`:
`distributed-worker-response.v4` remains `pending`—only an uncommitted
observation, never a result—while one authoritative
checkpoint read maps the status to `wait(reason=host_interaction)` or
`wait(reason=suspended)`. A successful controller command emits an enqueue-only
recovery decision for the same logical cycle while preserving the last
committed cycle index; it does not poll, sleep, or fabricate a run event. Host
response admission persists the full resolved interaction record, receipt, and
recovery wake at `admission_revision=expected_revision+1` (8 -> 9 is an
example), but no consumed marker. `resolved_pending` and `resolved_claimed`
are hard recovery barriers. One recovery worker calls
`claim_and_consume_host_interaction_response(envelope)`, which locks the
checkpoint and record together with `claim_mode=recovery` and the authoritative
pre-claim `resume_attempt`, obtains the checkpoint execution claim,
injects the message, records the complete RunEvent v4
`host_interaction_response_consumed`, and commits
`consume_revision=admission_revision+1` (9 -> 10 is an example) before model or
tool work. The combined CAS releases the transient record claim while retaining
the checkpoint execution claim for model/tool ownership; a crash before commit
rolls back to `resolved_pending`, while replay after commit returns the marker
without a second injection or wake. The successful recovery claim increments
`resume_attempt` exactly once (2 -> 3 in the canonical example), and the
consumed event plus next recovery envelope carry 3; stale, failed, and replay
paths preserve their authoritative value. A record-only claim is invalid. The
producer's `host_interaction_requested` notification is UI/event-only and uses
the separate durable UI notification outbox with `wait_reason=host_interaction`.
Its delivery is at-least-once and observers deduplicate stable notification
identities. An uncertain notification callback is reconciled explicitly to
delivered, retry, or abort; the reaper retries pending/expired claims but never
blind-retries ambiguous rows. A suspended running origin
resumes with a wake, while a host-interaction origin resumes to wait unless a
response is pending.
The closed command, receipt, precedence, and crash matrix are in
`controller-command.md`.

Cycle, advance, and terminal-finalizer transport tasks use late acknowledgement
and reject-on-worker-loss semantics. A delivery that commits and then dies before
publishing its callback is redelivered; the worker returns committed progress or
terminal replay from the checkpoint without repeating model or tool effects.
Hosts must also run a reconciler for running checkpoints so a lost callback or
broker publication failure cannot strand an admitted run.

## Terminal Ownership

A `terminal_candidate` never becomes terminal inside `advance`. The framework
terminal controller preserves this order:

1. output guardrail and optional validation;
2. append-once session persistence;
3. durable `session_persisted` observation;
4. terminal event staged in the checkpoint outbox;
5. atomic terminal finalization, claim-bound for a worker candidate and
   revision-bound for an unclaimed `max_cycles` candidate;
6. terminal event delivery and durable delivery recording;
7. retained terminal acknowledgement;
8. host or scheduler acknowledgement.

The controller process must resolve every terminal capability declared by the
frozen run definition. Missing session, guardrail, validator, repair, event, or
other required terminal capability fails before the first cycle is enqueued.

## Interaction Boundary

`wait_user` remains a durable terminal and stops dispatch. A brokered approval
provider that can block is not accepted by the nonblocking driver. Durable
cross-process approval continuation requires a separate current checkpoint
state and CAS resume protocol; a process-local approval broker or `RunState`
must never be presented as durable distributed approval.

## Transport Adaptations

Python maps the enqueue boundary to Celery. Rust maps it to an enqueue-only
Apalis adapter. Celery `AsyncResult.get`, Apalis `WaitForCompletion`, and
equivalent completion waits are forbidden inside nonblocking driver tasks.
