# Versioning And Forward-Only Policy

## One Current Contract

The repository is forward-only. `HEAD` defines exactly one current canonical
shape for every public API, model-visible prompt, built-in tool, runtime record,
event, session, checkpoint, App Server message, and wire payload.

When a shape changes, the same change must:

1. update the canonical documentation and fixture;
2. update both real implementations and their producer tests;
3. update every current caller and evaluation adapter;
4. delete the replaced reader, writer, alias, shim, migration, fixture, test,
   and documentation path.

Git history is the only archive. Runtime packages and the contract release do
not carry historical records or conversion logic.

## Strict Version Boundaries

Schema and protocol versions are validation boundaries, not compatibility
dispatchers. A current reader must require the current discriminator and reject
missing, stale, unknown, malformed, or future values. It must not retry another
decoder or fill fields that belonged to an older shape.

Canonical objects are closed by default. Unknown fields are rejected unless a
specific contract location defines a typed extension map. An extension map does
not permit callers to override canonical fields or behavior.

## Contract Releases

The contract uses semantic version numbers to identify immutable releases and
to communicate change size:

- **Major:** removes, renames, or changes public behavior or a wire shape.
- **Minor:** adds a public capability without changing an existing shape.
- **Patch:** corrects implementation evidence or documentation without changing
  observable behavior.

These labels do not promise that a runtime reads records from older releases.
Each implementation pins one exact contract version and revision. New releases
replace the supported contract after paired adoption; applications that need an
older runtime use the corresponding Git tag and package release.

## Adoption States

- `pending-adoption`: the immutable contract release exists, but one or both
  implementations do not yet pin it.
- `in-progress`: paired implementation work exists, but complete evidence is
  not yet available.
- `verified`: both repositories pin the same contract revision and pass real
  producer, full repository, fixture, and cross-repository checks.

Separate repositories cannot merge atomically. Until both implementations and
the central cross-repository workflow pass, the current change remains
`pending-adoption` or `in-progress` and must not be reported as shared support.

## Release Note: 8.0.0

`8.0.0` is a major forward-only release. It adds the task-neutral
`vv-agent.controller-command.v1` admission and its durable receipt without
merging it with deferred resolution or terminal successor continuation:

- `host_interaction_response`, `suspend`, `resume`, `cancel`, and explicit
  `abort` are the only closed command variants sharing one
  command id, RFC 8785 digest, passive run handle, resume-attempt fence, and
  checkpoint revision CAS;
- the App Server derives the global command id from `(threadId, turnId,
  actionId)` using a length-prefixed RFC 8785 JCS UTF-8 payload and SHA-256;
  `actionId` is stable only within its exact thread/turn scope, while the
  derived id keys receipts, replay, and conflict detection;
- the checkpoint discriminator is `vv-agent.checkpoint.v8` with no v7 reader;
  `active_host_interaction` and `suspended_origin` are persisted for crash
  recovery;
- framework-only typed `HostInteractionRequest`/`HostInteractionOutcome`
  admission holds the active claim and releases it in the same CAS; it is not
  a controller variant;
- the checkpoint revision, event outbox, command receipt, and controller wake
  outbox marker are committed together. Replays return the retained receipt,
  digest conflicts and stale fences write nothing, and an uncertain
  publication remains ambiguous until the scheduler reconciles it;
- producer admission and controller response admission have separate explicit
  same-transaction sets; notification claim, delivery, and reconciliation are
  independent row-level lifecycle transactions and never join either wake
  transaction;
- the framework-only host-interaction producer persists the complete strict
  request (including credential-redacted prompt) in both the checkpoint and an
  independent interaction record. It writes only a v4
  `host_interaction_requested` event and an independent durable UI notification
  outbox, never a worker wake. Same identity plus digest replays with zero
  writes; a different binding or digest is a conflict;
- a response command admission persists the complete closed user message,
  response digest, command id, resolved-pending record, receipt, and recovery
  wake at `admission_revision=expected_revision+1` (8 -> 9 is an example) before
  returning; it does not append the consumed event. `resolved_pending` and
  `resolved_claimed` are hard recovery barriers. A recovery worker calls the
  combined `claim_and_consume_host_interaction_response(envelope)` operation,
  which obtains the checkpoint execution claim and record phase together,
  injects the response once, appends `host_interaction_response_consumed`, and
  records `consumed_revision=admission_revision+1` (9 -> 10 is an example)
  before model/tool work. A crash before commit rolls back both claims; a
  consumed replay does not duplicate injection. The host UI notification is a
  separate at-least-once outbox with stable observer deduplication;
- `resume` wakes only a suspended running origin or a suspended host
  interaction with a pending response. A host-origin suspension without a
  response restores the wait and does not dispatch a worker;
- the distributed worker response remains v3: a pending observation plus the
  authoritative checkpoint status yields the host-interaction or suspended
  wait reason. No synthetic worker or run-event variant is introduced;
- the public API inventory is v5, the nonblocking distributed driver is v3,
  and the App Server observable projection is v3 to expose narrow `turn/action`
  plus the two non-terminal wait projections;
- `wait_user` remains the existing terminal `ask_user` behavior. New input
  after a terminal still requires the separate successor-run continuation
  protocol;
- SQLite and Redis receipt/interaction indexes are canonical. SQLite enforces
  scalar state, lease, and foreign-key relations; the strict v8 codec validates
  closed nested request/response JSON, RFC 8785 digests, forbidden fields, and
  UTF-8 limits before CAS. Receipt payloads remain free of provider-specific
  data, secrets, and application business fields.

The support matrix is `pending-adoption` until both implementations pin the
same v8 revision and pass real producer, full repository, and cross-language
gates.

## Release Note: 8.1.0

`8.1.0` is a minor release. It adds a task-neutral compiled distributed-start
capability: both implementations accept an already-compiled `AgentTask`,
preserve its prepared runtime fields, and do not re-run compile-time
instruction or context producers. The capability remains enqueue-only and
returns a passive handle; the existing distributed envelope, worker response,
checkpoint, and driver decision wire shapes are unchanged. The cross-repository
workflow also provisions and probes Redis for the Rust persistence gate. The
support matrix remains `pending-adoption` until both implementations adopt and
pass the paired gates.

## Release Note: 8.0.1

`8.0.1` is a patch release with no wire or runtime behavior change. It removes
an accidental top-level `vendor_future` member from the `claimed_active_cycle`
checkpoint valid fixture. Checkpoint objects remain closed: unknown top-level
fields are rejected, while vendor extension data is valid only in the explicit
`extension_state` map. The current checkpoint/controller valid and invalid cases
and all controller-command digest vectors were audited; their semantics remain
unchanged. The support matrix remains `pending-adoption` until both
implementations adopt and pass the paired gates.

## Completion Evidence

A forward-only contract change is complete only when:

- both locks pin the same exact contract release and revision;
- both vendored snapshots match the canonical artifact;
- both real writer and strict reader tests pass;
- stale, missing, malformed, and unknown versions are rejected in both
  languages;
- repository-wide searches find no old reader, alias, migration, fixture, or
  active documentation reference;
- the central cross-repository workflow records both exact implementation
  revisions.
