# Yieldable waits

Contract 38.0.0 covers yieldable waits in the SQL session kernel and L1 lease
lock ordering. Python 0.35.0 local App Server, Interactive and Runner entry
points accept and retain declarations but do not yield: they wait for the real
child/provider result, keep steer queued, and do not call on_yield. The rules
below describe SQL kernel execution and host scheduling that implements yielding.

A wait observes work; yielding the wait does not stop that work. A host MAY opt
in at admission for each foreground child, or at the first Accepted return for
a tool provider. Absent declarations MUST retain the previous wait scheduling and declaration
bytes. The shared long-result archive identity correction applies to all newly
prepared long results, declared or undeclared; existing stored references and
record bytes MUST NOT be rewritten.
Replaying or restoring an operation MUST use its recorded declaration, never a
new host default. Model calls, approvals and user waits cannot declare this policy.

## Records

Record schema 1 and inbox schema 3 add optional closed fields:

- `provider_evidence.payload.yield_on_steer`: literal `true` from the original
  acceptance, absent for an undeclared acceptance. Hosts MUST persist this with
  acceptance evidence and authenticate the complete payload including this field;
  adding or removing it changes the canonical inbox bytes and digest.
- `op_parked.payload.yield_on_steer`: literal `true` when declared, absent otherwise.
- `op_parked.payload.yieldable_children`: nonempty unique child session IDs,
  present exactly for a declared foreground child wait. Every ID MUST belong to
  the immutable handle. Undeclared siblings may finish before the rest can yield.
- `op_completed.payload.yielded_by`: the applied steer input ID, present only for
  a yielded observation. It MUST reference an applied steer for the same active
  turn and generation in the same commit. Its evidence includes `steer/<inputId>`
  and, for providers, the original acceptance evidence.

Direct Accepted returns and recovered acceptance evidence MUST construct the
same park. The first accepted park fixes the handle and declaration. Identical
acceptance attachments are idempotent; an authenticated attachment changing the
declaration MUST be rejected with `acceptance declaration conflict`, without
changing the park. A query Accepted return changing the handle or declaration
MUST fail with `provider_result_invalid`; it cannot upgrade or downgrade policy.
Missing declaration means undeclared, never a current host default.

These fields do not change child records or handles. Old strict readers reject
them. There is no record/inbox discriminator bump and no SQL layout migration.
Sessions without declarations retain their original readable format.

## Admission and ordering

A steer for the active turn (explicit target or omitted target resolved to the
current turn) MAY end the pending batch only when every
remaining unfinished operation is a declared parked observation and every
unfinished child in each such operation is declared yieldable. Here unfinished
uses the existing pending-batch scheduling rule: non-retrying Unknown receipts
are already outside that batch. Yielding MUST NOT settle, cancel or replace
those receipts. Verified completed
siblings no longer block. Planned work, executing commands, retrying Unknown attempts,
approvals and user waits block yielding. Model selection retains its ordinary
batch deferral. Stale turns/generations cannot yield work. Suspended or cancelled
turns do not yield.

At a captured inbox watermark, child terminal inputs are verified and consumed
before considering steer when a declared pending wait exists, independently of
inbox arrival order. Existing child verification, duplicate and audit rules still
apply. A complete child batch returns its real result; no yield occurs. Otherwise
eligible waits yield in operation plan order. Steering inputs retain inbox order.
Later arrivals cause the normal guarded append retry. The completion receipts,
applied steer and inbox consumption MUST commit atomically. Model projection
places tool results before the steering message; the next model request sees both.
A crash before commit retains the wait and steer input; a crash after commit
retains both outcomes and MUST NOT re-invoke the yield callback.

## Results and host callbacks

The binding MAY supply a callback taking the original execution plan, copied
child handles (or original provider handle), and the reason `steer`. Each child
copy includes `status`: the verified terminal status, or `running` when no
terminal input has been verified at this watermark. Verified members also carry
`result`, `terminal_seq` and `terminal_digest` from that authenticated terminal
input: the same terminal data used by normal child-result assembly, with a
stable reference to the exact terminal record. Unverified members omit these
fields. These copies do not mutate records. `running` is not a live business
status; hosts MAY read their own status or questions during the callback.

Callbacks MUST be read-only observers: no writes, file publication, retention,
messages, cancellation or other side effects. A guarded commit retry MAY invoke
the callback again and return different observations; the final committed result
is authoritative. After commit, replay and recovery MUST read the recorded
result without invoking the callback. Files MUST NOT transfer during yielding;
completed child file delivery remains on the host's existing path, such as a
later status-tool call. There is no prepare-yield phase.

The callback returns a normal completed tool result with the original tool call
ID and continue directive. The kernel MUST NOT invoke ordinary tool execution
or cancellation to yield. Callback bodies MUST pass the ordinary tool-result
validation, including declared JSON/file/image/error bodies, before the ordinary
bounded result projection. Long-body candidate identity includes the operation
owner and content SHA-256. Different candidates cannot occupy each other's
paths; exclusive writes never replace a committed object. Only the selected
candidate's reference is recorded. Storage/integrity failure is explicitly
unavailable under the ordinary artifact rule, never a successful recovery claim.

Without a callback, the default SUCCESS/continue result starts exactly with:
`Wait interrupted by new input; observed work has not been stopped.`
Its metadata includes `yield_reason: "steer"`; child waits also include
`children` (objects with `session_id` and `status`, in admission order) and
`running_children` (IDs without a verified terminal input). For child waits, the
content appends a newline and the RFC8785 object containing these same two keys
so that the model sees the statuses and IDs. Provider defaults have no suffix. Callback exceptions or invalid
results fall back to this default with `yield_callback_failed: true`; exception
messages are not retained. The callback cannot prevent steering from applying.
Results are recorded once; recovery reuses them.

## Later work and other entry points

Yielding MUST NOT cancel, pause or mutate children. Their later verified results
follow background delivery rules: notify the model while their original turn is
active and executable at a batch boundary; ended/cancelled turns only audit them.
The ended observation result MUST NOT be rewritten. Ordinary later parent
cancellation retains the existing descendant cancellation rules.

A yielded provider handle is closed. Later authenticated provider results and
acceptance evidence are retained as audit-only inputs, never result corrections.
The kernel MUST NOT query or cancel that handle after yielding, including when
the parent is later cancelled. Work at the provider is outside this observation.

Forks/clones copy only context at an ended boundary, not pending operations or
callbacks. New waits require fresh declarations. Child runtimes retain ordinary
bindings; the parent observation declaration is not a child creation policy.
SQL hosts schedule child work independently and recover committed inputs by
scanning durable state; a wake is only a hint. Parked waits MUST NOT spin or
repeat effects. The local entry points listed above do not provide the yielding
scheduler/owner handoff described in [session consumers](session-consumers.md).
After-cycle hook steering remains a completed-cycle decision,
not inbox steering.
Compaction sees ordinary tool completion plus protected input. App Server
projection of a retained SQL-produced yield shows the tool as completed and
retains the steering input normally; this does not enable local App Server yielding.

Contract 38.0.0 is major because it extends closed record shapes and changes
observable scheduling for declared waits. Python 0.35.0 is required. Frozen Rust
23.0.0 / 0.21.x does not support yieldable waits; its baseline is unchanged.
