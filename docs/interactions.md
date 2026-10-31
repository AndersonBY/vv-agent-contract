# Typed user interactions

The retained wait and its prepared plan are the only source of a question. Never
rerun ask_user or consult current host configuration to reconstruct its form.

A user form is closed and contains kind=user, sessionId, turnId, generation,
interactionId, operationId, attempt, requestDigest, prompt and answerSpec. The
last two identity fields are null for a turn-level no-tool wait. answerSpec is
`{kind:"text"|"single"|"multi",options:[string],allowCustomOptions:boolean}`;
no options means text with options=[] and allowCustomOptions=false.
requestDigest is SHA256 of JCS of the entire public normalized form excluding
kind and requestDigest. It covers the retained identity as well as the prompt
and answerSpec. The HostInteractionRequest v1 prompt digest remains independent.

ask_user trims and deduplicates options using the existing portable normalization.
Before opening a wait it rejects a prompt above 16 KiB UTF-8, more than 64 options,
an option above 1 KiB or a public form above 64 KiB. It returns a definitive ERROR
with error_code=interaction_form_too_large and directive=continue. Historical
oversize forms produce interaction_form_too_large while keeping the original wait.
No projection truncates options to invent an answerable form.

thread/status, thread/status/changed, snapshot state in thread/read and
thread/resume, HostInteractionRequestedEvent.metadata.interaction and the
turn-level RunStateChangedEvent.metadata.interaction use the same builder.
Only one pendingInteraction is exposed: approval first, then stable session and
operation order. Answering one sibling exposes the next. All child waits remain
on their original sessions; only authenticated terminal results reach the parent.

turn/action respond is exactly `{kind:"respond",target,answer}`. target contains
sessionId, turnId, generation, interactionId, operationId, attempt, requestDigest.
The replaced message parser does not exist. An answer is exactly one of:

- `{kind:"text",text:string}`: nonblank, at most 64 KiB UTF-8, legal for every form.
- `{kind:"single",selected:[string],custom:[string]}`: exactly one total entry.
- `{kind:"multi",selected:[string],custom:[string]}`: 1..64 total entries.

Selection kind must match the form. selected entries match exact options; no
value may repeat. custom entries require allowCustomOptions=true, are portable
trimmed, nonblank, each at most 1 KiB, distinct and absent from existing options.
The entire canonical answer is at most 64 KiB. Text is always a free-text reply,
including to a choice form with allowCustomOptions=false. A single selection of
NOT_AN_OPTION with custom disabled rejects; text containing it is accepted.

The model-visible ask_user result content is JSON with exactly
`{reply_mode:"free_text",text:string}` for text, or
`{reply_mode:"selection",selection_type:"single"|"multi",selected:[string],custom:[string]}`
for selections. The runtime generates this content, so free text cannot be
misrepresented as an option selection. A turn-level reply stays a user message.

The original user inbox content is `{interaction_id,operation_id,text,metadata}`;
metadata.interaction_response is the closed extension `{target,answer}`. text is
generated from answer, and the kernel checks equality. Both admission and kernel
application validate every target field and answer against the retained form.
Direct typed InboxItems receive the identical checks. Direct host free-text
`{text,interaction_id}` remains legal, bound by envelope target turn and generation;
if operation_id is supplied it must match. It never chooses a unique wait.
Requiring a new digest/attempt from this host path would break hosts that already
hold the original interaction id; that id identifies the retained operation, and
turn plus generation fences the response. The result is explicitly free_text.

Child targeting follows the admitted child graph, including nested children.
The server authorizes both root and target before admission. String prefixes
never establish ownership. Failed admission pushes no inbox item; failed kernel
application completes no operation and preserves the wait. Cancelled or finished
targets reject. Repeated actionId with identical target/answer replays its retained
receipt before checking the current wait; changed bytes return -32024
submission_conflict. Wrong root/child turn returns -32025; authorization failure
returns -32027. Other invalid identities return -32602 reason=stale_interaction;
invalid answers return -32602 reason=invalid_interaction_answer.

Ordinary child message APIs enqueue steering, not a guessed user answer. Parents process their admitted descendants' queued cancellation controls even after the parent turn ends. Background children can expose user waits while their owning parent turn remains active.
