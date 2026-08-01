# Nonblocking Distributed Run Driver

The distributed run driver is the host-facing scheduler boundary for cycle-level
execution. It reuses the current distributed envelope, worker response, and
checkpoint protocols; transports do not create a second run state machine.

## Driver Operations

`start` receives a prepared run whose checkpoint has already been created or
admitted by the framework. It reads that authoritative checkpoint, enqueues at
most the next required cycle, and returns a passive `DistributedRunHandle`.
It never waits for the cycle result.

`advance` receives the previous envelope plus either one closed worker response
or an out-of-band transport failure. The observation is never authoritative.
The driver reloads the checkpoint exactly once and returns one decision:

- `dispatch`: enqueue the enclosed next-cycle envelope immediately;
- `retry_at`: enqueue the enclosed recovery envelope no earlier than the given
  Unix-millisecond deadline;
- `wait`: do not enqueue work while reconciliation or a host-owned interaction
  remains unresolved;
- `finalize_required`: run the framework terminal controller for the verified
  candidate while retaining the worker claim;
- `terminal_replay`: return the exact retained durable terminal without running
  terminal processing again.

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
`reconciliation_required` stops dispatch with `wait`.

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
