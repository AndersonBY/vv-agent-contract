# Inputs awaiting a primary model response

These rules are normative for contract 37.0.0.

`session_created.attributes.seed.unseen_input_protection` freezes a Boolean
choice. New sessions default to true. Absence in a previously stored creation
record means the existing compaction behavior, byte for byte. Continuation and idempotent transaction creation replay MUST
NOT add the declaration. At the public transaction creation boundary, an omitted
choice reuses the existing creation bytes and rule. Only first creation defaults
to true. Explicitly different choices, any other creation field or consumer set
MUST still conflict. The same creation, replay and inheritance rules independently apply to
`response_rejection`. A seed may contain either or both declarations, the existing
`messages` and `shared_state` pair, or that pair plus either or both declarations. It remains
closed; malformed values and unknown fields MUST reject. Declaration-only seeds
do not override host-provided bootstrap history or state. Explicit false selects
the previous policy and permits descendants to inherit it. Children and App
Server forks inherit the source choice (absence becomes false on new descendants).
No generic clone surface is required. Python 0.33.3 rejects the additional seed
field at its existing closed codec boundary; top-level attributes alone provide
no such gate. There is no contract-version field in session creation records.

A successful primary is an adopted, normal-context Definitive model response
committed to history, with no result error code and purpose `primary`. Rejected
requests (including `prompt_too_long`), endpoint retries, Unknown, compaction,
child summaries, Session Memory and other model purposes MUST NOT advance
coverage. Completion evidence follows [model completion](model-completion.md).
Response-level rejection and missing-termination EOF do not advance coverage;
refusal text adopted as an ordinary answer does. Undeclared/false response policy
retains the previous definitive content-filter behavior.

Coverage is the maximum `context_version` of those successful primary plans in
the committed log prefix. For declared sessions a primary's context version is
the canonical positive decimal sequence of an existing captured log prefix;
malformed or future references MUST reject at plan admission. Retries retain the
original request and captured version, even when later inputs have arrived.
Use the plan's captured source version, not the receipt
position: an input arriving while a request is in flight was not in that request.
Both execution and replay MUST use the same incremental projection state derived
from committed kernel records. Coverage and source positions are disposable
prefix caches, never a second persisted coverage ledger. Processing new records
MUST NOT replay or decode obsolete replacement snapshots merely to locate the
protected suffix. A receipt or a host claim alone MUST NOT mark later inputs seen.

There is one committed-prefix message projection for declared sessions. Normal
provider callbacks, approval denial/timeout and tool interaction replies that
arrive after a before-memory snapshot MUST update the retained original tool
group in that projection. The next primary request, replacement validation and
cold replay MUST all contain that actual result, rather than the snapshot's old
placeholder. A replacement MUST retain the operation/record provenance and new
position of every original group preserved verbatim, even when no input is
currently protected. Removed groups lose that provenance. Reused tool-call IDs
do not identify a source group. Undeclared/false sessions retain their previous
snapshot projection byte for byte.

The first input projected from a source record after coverage starts a protected
suffix. Inputs include ordinary turn input, same-turn user replies, steer,
native background child notifications, after-cycle steering and corrections.
External provider results adopted as normal tool results, like blocking child
results, trace back to and protect their original assistant tool group. Model
callbacks use the primary receipt rule; they do not become extra user messages.
Bootstrap messages without earlier primary evidence are protected too. The
boundary rolls back to the assistant tool call when it falls inside a contiguous
call/result batch. The complete suffix MUST remain verbatim and in order as one
contiguous sequence; a replacement may add content before or after it.

Summary planning and acceptance, emergency shortening, microcompaction, context
projection and reducer replay MUST enforce that same boundary. Protected content
MUST NOT enter summary prefixes, previous-summary inputs or archive candidates.
Full-history summarization for child admission reads the parent context to
prepare child input. It does not replace the parent context or establish primary
coverage.

Before-memory replacements, before-LLM messages and turn bootstrap replacements
MUST preserve the suffix. A violation fails as `unseen_input_removed` before the
replacement boundary or model plan commits. Invalid replay plans MUST reject.
Python maps this error to `UnseenInputError` (a ValueError with `code`).

If the protected suffix plus retained system messages exceeds the message window
after reserved output, or a prompt-too-long response leaves no eligible prefix,
the turn fails with `unseen_input_capacity_exceeded`. No summary request or
additional primary retry may be planned for that exhausted context. Python uses
`UnseenInputCapacityError.code` as the retained terminal reason. Compression
MUST NOT silently consume the suffix or retry forever.

Summary planning and acceptance use the immutable original context prefix.
Restart before the summary receipt reuses its operation identity; restart after
the receipt accepts that receipt once; restart after replacement retains the
same inputs without charging them into the history again.

`fixtures/unseen_input_protection.json` is produced by Python's real kernel via
`scripts/unseen_input_fixtures.py`, including actual primary requests, native
child completion, capacity and restart facts. Rust remains frozen at 23.0.0 /
0.21.x and does not support this capability.


## Complete inbox classification

Only applied content that actually enters the normal model context requires a
protected message. Rejected/noop records and audit-only results add no model text.

| Inbox kind | Model history and protection |
| --- | --- |
| `user` | Initial/queued input enters at `turn_started`; same-turn no-tool replies append user text at `input_applied`. Normal tool interaction replies update a tool result and protect the original assistant group. Audit-only replies after cancellation add no protection. Host compaction requests alone add no text. |
| `steer` | Appends user/typed messages; protect from their committed source position. |
| `follow_up` | Queues for the next turn; protect when `turn_started` actually inserts it. |
| `child_result` | Background completion appends `Child completed: ...` and protects from that notice. A normal blocking completion updates the waiting tool result and protects the entire original assistant group. Generic non-model correction receipts protect only their appended correction text; the normal native child flow currently cannot reach that correction branch. An audit result adds no text or protection. |
| `provider_result` | An authenticated normal tool callback updates its tool result; protect the original assistant group, including without any simultaneous steer. A model callback is covered only by an adopted primary receipt at its captured version. A correction appends protected correction text; audit results add no normal model text. |
| `provider_evidence` | Attaches acceptance/handle evidence; no model text by itself. Any later correction text is protected at its receipt. |
| `approval_answer` | Approval/allow-session decisions change authorization without adding text. A normal denial/timeout reason becomes tool-result content; protect the entire original assistant group at the applied answer. Audit-only answers after cancellation add no protection. Correction text is protected at its receipt. |
| `control` | Changes lifecycle only; no model text. |
| `model_selection` | Changes model routing only; no model text. |

After-cycle steering and non-model correction receipts also introduce protected
text at their own committed source sequence. Correction and audit callbacks MUST
NOT re-protect the original tool group: cancelled/ended/inactive turns or a later
started attempt make the receipt audit-only, and an already-consumed Unknown
produces correction text instead of replacing the original result.
Synchronous ordinary handler results
remain subject to the existing tool retention rules, rather than becoming inbox
callbacks.

Native child correction is a generic receipt-branch rule, not an independently
verified reachable native-child scenario. Native delivery authenticates an
admitted child's retained terminal; ordinary native execution does not currently
produce the consumed-Unknown path needed for such a correction. Provider
correction producer evidence must not be described as native-child evidence.

Hosts MUST retain protected messages verbatim in before-memory/before-LLM hooks.
Put required enrichment in the tool result when it is produced, or retain the
original messages and append separate host information. Editing an original tool
message in place violates the rule.

The old codec rejects when it decodes the creation record, reads from the start,
or resumes a declared session. Paged record reads, inbox reads and raw JSON reads
can bypass that decoder; hosts MUST route these entry points by supported version
before reading. A previously undeclared parent that creates a declared child
(including explicit false) on the new runtime must keep its dependent execution,
cancellation and result delivery on that runtime too. Rollback cannot be decided
from the parent's creation record alone.

The producer also exercises local HTTP through the real `VvLlmClient` and kernel:
normal primary submission, prompt-too-long recovery, endpoint retry and Unknown.
The server port and clocks are frozen before record production. Two independent
generations must produce identical bytes; generated records are not scrubbed to
hide nondeterminism.
