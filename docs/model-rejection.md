# Model requests rejected by the provider

These rules are normative. Request-level rejection applies at the model boundary,
before stream output. Response-level rejection below is a separate confirmed
conclusion after complete response consumption.
An adapter MAY raise an explicit rejection type asserting the provider received
and rejected the request without executing it. Its status MUST be integer
400..499 other than 408. Automatic recognition otherwise MUST require a real HTTP
response whose integer status matches the exception AND complete HTTP observation
for this logical invocation. An invocation is observable only when the runtime
owns the HTTP client passed into the adapter and records each physical send,
including vendor-internal retries and redirects. The candidate response MUST
belong to that same observation; evidence from an unrelated response cannot
certify an unobserved path. At least one send MUST exist;
EVERY send MUST have a received integer 4xx response other than 408, with the
entire raw response body read to EOF and successfully decoded. A received status
is pending until both conditions hold; unread or partially read bodies, early
close, decoder initialization errors and decoder finalization errors stay
incomplete. A timeout,
transport error, missing/incomplete response, 408, 5xx or other status anywhere
in that observation vetoes definitive rejection. Read failures after receiving
headers also veto it. HTTP decoding errors MUST participate in the complete
exception-graph veto for explicit rejection, automatic recognition and
prompt-too-long recovery. The last 400 alone cannot establish this condition.

An unobservable host client/adapter MUST stay Unknown for automatic HTTP
classification; only its explicit adapter rejection assertion can establish
rejection. This also gates HTTP-based prompt-too-long recovery: an unobservable
400 context error stays Unknown rather than being settled by compaction.
Known HTTP status exceptions exposing status only on the response
qualify when the observation requirement is met. Explicit causes MAY retain
positive evidence. Unrelated exception context, bare status fields, status text
and forged responses are insufficient.

Before accepting ANY positive evidence, including an explicit rejection, scan
the complete exception graph (cause, context, exception-valued arguments and
exception groups, in both wrapping directions) for uncertainty. Timeout,
transport/connection loss, stream interruption, non-4xx/408 responses or unsafe
HTTP observations veto rejection and prompt-too-long recovery throughout that
graph. Cancellation and observed stream output retain priority for exception-based request
rejection. Fully consumed response-level rejection is the observed-output exception:
it is a definite upstream conclusion, not transport uncertainty. Unrecognized
errors stay Unknown; a later rejection cannot erase an earlier uncertain send.

Native provider connection and timeout exceptions MUST participate in this veto
even when their lower-level HTTP cause was lost. Use the actual installed error
types, including subclasses; guessed class names or message text are not type
evidence. Each optional provider load MUST independently isolate ordinary import
and export failures, accept only actual exception types, and continue with other
providers. Failed lookups MUST NOT be negatively cached: recovery MUST restore
the veto on the next classification without manual invalidation. Cancellation
and process interrupts MUST propagate. Positive HTTP recognition remains independent of provider error
classes. A context-length message wrapped around a network failure MUST NOT
produce a definitive prompt-too-long receipt.

Each failure MUST be attributed to its own physical send, including concurrent
sends and redirect hops. An unindexed failure MUST set an uncertainty veto that
cannot be cleared by later responses in the same invocation. Observing traffic
MUST preserve the corresponding provider's default connection limits and socket
settings, including TCP keepalive, and the host's proxy and request-timeout
priority. Callback failure MUST explicitly close closable stream iterators and
retained response streams before their client is released.


Before rejection classification, prompt-too-long recognition MUST retain its
existing compaction semantics, including real HTTP 4xx responses other than 408.
Match explicit input-size patterns (`prompt is too long`, `prompt_too_long`,
`context_length_exceeded`, `maximum context length`, `context window exceeded`,
`model context window is`, and `too large for model with N maximum context length`,
where N is a numeric token limit) in exception text or selected provider
message/code/type fields, case-insensitively. A matching structured code/type does
not require matching message wording. On non-429 4xx these explicit patterns
qualify even when the same text also mentions quota.

The generic patterns `request too large` and `too many tokens` qualify only if
the same text source has no time-window or quota signal. Evaluate exception text
and selected provider message/code/type text separately; an unrelated graph node
MUST NOT veto a match. Signals are case-insensitive, word-bounded `per
(day|hour|minute|min|second|sec|month)`, `tokens per min`, `TPM`, `TPD`, `RPM`,
`quota`, `rate limit`, `rate_limit`, and `insufficient_quota` (whitespace between
words MAY vary). Substrings such as `per minimum`, `quotable`, or `TPMs` MUST NOT
match these signals. `too many tokens per request` therefore still qualifies
outside HTTP 429.

HTTP 429 MUST qualify only through `context_length_exceeded`, `prompt is too
long`, `prompt_too_long`, `maximum context length`, or the content-specific
`string_above_max_length` rule below. Generic patterns and the additional window
phrases alone MUST NOT qualify on 429, including text-only wrappers around a 429.
Other 429 errors use the existing rejection retry/backoff policy, without
compaction. Explicit adapter rejection flags MUST use these same rules against
their original message/code/type before safe diagnostic replacement.
HTTP 413 at the model boundary means the input payload must shrink, even without
matching text. `string_above_max_length` qualifies only when `param` identifies
`prompt`, `input`, or `messages[N].content` / `input[N].content` (including
`.content[N].text`). A tool name or other string-field limit alone does not qualify.
Preserve recognition through exception cause/context/exception arguments, but
timeout, transport/connection loss, stream interruption and actual HTTP statuses
outside 4xx or equal to 408 veto text/structured matches throughout that graph.
Cancellation and observed stream output MUST be checked before either exception
classifier. Response-level rejection is checked after normal consumption, before
after-LLM hooks and adoption into history.

Recognized oversized input MUST produce the existing `prompt_too_long` result,
not `model_request_rejected`. The primary then uses the existing bounded emergency
compaction/retry and `CompactionExhaustedError` boundary. Only other 4xx responses
enter definitive rejection classification. Failed oversized summary requests keep
history; a required child summary remains unavailable. Neither path accepts error
text as a summary. Output-repair callbacks retain `repair_provider_error`.

The existing `op_completed.result` JSON object contains `error_code` equal to
`model_request_rejected`, safe `content` with the HTTP status/message, empty
`tool_calls`, and `rejection` with exactly these fields:

| Field | Value |
| --- | --- |
| status_code | Integer 400..499 excluding 408 for request rejection; 200 for declared response rejection |
| provider_code, provider_type | Safe provider identifier or null |
| message | Generic safe explanation, at most 500 Unicode code points |
| retryable | Boolean resolved against the frozen endpoint count: true for 429, or 401/403/404 with multiple endpoints; an explicit adapter boolean overrides these defaults |

Only status and safe provider code/type may be copied. Arbitrary provider prose
MUST be replaced by a generic explanation; it may contain bare credentials or
unmarked private input. Code/type MUST reject credential markers (API key, token,
secret, authorization, credential, bearer, sk-) and assignments, including colon
assignments. No request fields or credential prefixes may survive truncation.
The same safe diagnostic construction applies to output_repair errors while
preserving repair_provider_error, one repair, and output_validation_failed. A definitive outcome does not invent
zero token usage: absent accounting stays unavailable.
Existing canonical projections MUST reproduce that same safe repair diagnostic;
new rejection fixtures alone do not establish consistency of existing producers.

A permitted retry is planned atomically with the rejected receipt. It keeps the
frozen request/context/purpose/provider, advances the attempt number and clears
the selected attempt until the successor completes. `not_before_ms` retains a
delay of 2 seconds times the rejected attempt number for 429 and other explicitly
retryable statuses. 401/403/404 retries use zero delay. Restart MUST retain that
receipt and due time without redispatching the rejected attempt. The operation
limit remains `max(2, frozen endpoint count)`; cancellation and budget admission
still apply. Output repair gains no automatic retries.

Default endpoint policy, after prompt-too-long recovery has been checked:

| Response | Multiple frozen endpoints | Single endpoint | Delay |
| --- | --- | --- | --- |
| 401 / 403 / 404 | Retry the next endpoint in frozen order, within `max(2, frozen endpoint count)` attempts | Stop after one call | Zero |
| 429 | Retry in frozen order within the same limit | Retry once | 2 seconds times rejected attempt |
| Other 4xx except 408 | Stop after one call | Stop after one call | None |

Request-content rejection, including non-context 400/422, MUST NOT try another
endpoint. Oversized input, including 413, retains compaction as specified above.
401/403/404 indicate endpoint authentication, permission or model availability;
retrying the same single endpoint adds no value. An explicit adapter
`retryable=true` or `retryable=false` MUST override the default, including the
single-endpoint rule; an omitted value follows the table. Each permitted retry
retains a definitive receipt without Unknown or duplicate-cost risk. Exhaustion
ends as definitive failure with the last rejection's safe status/message.
Truly Unknown failures keep their existing endpoint retries and risk accounting.

`ModelCallFailed` has `outcome=definitive`, the new error code and the safe
descriptor at `metadata.model_rejection`. A failed primary terminal uses reason
`model_request_rejected` and a result containing the safe HTTP status/message.
`RunFailed.error` includes reason and safe message so App Server users see the
cause. Existing result/error projections use the same terminal. Earlier truly
unknown attempts remain unresolved and retain their duplicate-cost risk.

A rejected ordinary compaction summary follows existing summary failure behavior:
keep the complete old context and continue the primary call after any permitted
retries. Provider error text MUST NOT be accepted as a summary. Child admission
that requires a fresh summary still fails without one. Output-repair callbacks
keep their existing failure semantics.

Session Memory extraction is a separate logged model purpose. Its permanent
rejection terminates the turn with `model_request_rejected`, replacing the old
Unknown retries and eventual `model_outcome_unknown`. Its recognized oversized
input keeps the prior empty extraction result behavior; no error text becomes
stored memory. Truly Unknown extraction failures retain their existing retries
and eventual failure.

Python adapters use `vv_agent.llm.errors.ModelRequestRejected(status_code,
message, provider_code=..., provider_type=..., retryable=...)`. Recognition accepts
real installed `httpx`/`httpx2` responses used by OpenAI, Anthropic and vv-llm
only with complete owned-client HTTP observation, without depending on a
provider-specific exception class. Python's vv-llm adapter passes an observed
httpx2 client through the existing http_client argument and closes it after the
logical invocation. It neither patches nor releases vv-llm. Vendor SDK retries
remain enabled and are observed, so one ledger attempt can contain several
physical HTTP requests (three 429s in one attempt with current SDK defaults).
The observer MUST pre-read and decode every non-408 4xx before vendor retry code
can discard it. This probe has a total wall-clock deadline equal to the smaller
of the request read timeout and 10 seconds (10 seconds if unset), and a 1 MiB
limit on both total raw and total decoded bytes. Continuous trickling MUST NOT
extend that deadline. Complete decoded bodies are cached for vendor consumption.
Read, transport or decoding failures and either exceeded bound MUST leave the
send incomplete, hence the logical invocation Unknown. The hook MUST NOT throw
ordinary pre-read failures: preserve and rethrow the original error on body
consumption. For size/deadline exhaustion, replay the buffered raw prefix and
remaining original stream without loss; later successful consumption MUST NOT
upgrade this incomplete observation. Pre-reading MUST run synchronously in the
response hook without creating observation threads. Before starting the raw body
iterator, copy the request's timeout extension and set read to the smaller of
its original value (unset means infinite) and the observation deadline. Check
the total wall-clock deadline between chunks and after EOF/decoder flush. An
in-flight recv may finish after the deadline, so maximum extra network wait is
the deadline plus one recv timeout, at most 20 seconds. Remaining raw body reads
MUST retain the shortened per-recv timeout, including after size/deadline
exhaustion. A recv timeout leaves timeout/incomplete evidence and MUST be saved
and rethrown on vendor body consumption.
Status codes, response headers, Retry-After, x-should-retry, vendor retry decisions,
physical retry counts and backoff calculations MUST match the native default
client. Pre-reading may add bounded observation latency before those decisions;
only the read timeout is shortened as specified above. Complete intermediate
409s, retry-enabled 400s and all-429 invocations therefore still qualify.
The attempt limit is NOT an HTTP request limit. Per-request observation is
transient evidence, not additional ledger attempts or token usage. A timeout
then 400 or 5xx then 400 remains Unknown; three 429s or a single 400 can reject.
Unobservable adapters must use the explicit type to confirm rejection.

`fixtures/model_rejection.json` comes from the Python real-kernel producer
`scripts/model_rejection_fixtures.py`; rebuild its manifest with `contractctl.py
manifest`. Record 1, inbox 3, SQL 3, RunEvent v6, App Server v5 and frozen tool
definitions stay unchanged. Historical Unknown receipts are not rewritten.

Upgrade without changing handler_version or record/schema versions requires a
global stop of ALL drivers and API entry points, upgrading both machines, then
restarting. A session driven by 0.33.2 MUST NOT return to 0.33.1. Rollback MUST
isolate data by host-maintained version ownership, including ended sessions and
recovery readers. A rejection receipt without turn_ended can be misdriven by
0.33.1; rejection retry histories cannot be replayed by its reducer. A read-only
history precheck is supplementary and cannot prove that an unmarked session was
never driven by the newer runtime. Never delete receipts or replay uncertain
calls to make rollback possible.

## Response-level rejection

Only sessions whose closed creation seed declares `response_rejection=true` use
this category. New creations default to true. Absence/false retains 0.33.3
content-filter/refusal-reason behavior. Creation replay preserves original bytes;
children/forks inherit the source choice, with absence becoming explicit false.
0.33.3 rejects either Boolean declaration at seed decoding, even false.

After normal complete consumption, `finish_reason_normalized=content_filter`,
or `refusal` without nonempty refusal text, is a definitive response rejection.
The HTTP response is 200 and may have yielded temporary output. It uses the same
`model_request_rejected` result, terminal reason, ModelCallFailed event and
`metadata.model_rejection` projection as request rejection, with descriptor:

| Field | Value |
| --- | --- |
| status_code | 200 |
| provider_code | `content_filter` or `refusal` |
| provider_type | Original finish_reason, subject to the same safe identifier rules; null when unsafe/missing |
| message | Generic `Model provider response was rejected.`, at most 500 Unicode code points |
| retryable | false |

Output-repair callbacks retain `repair_provider_error` / `output_validation_failed`
and discard the rejected repair text, with no automatic repair retry.
No automatic retry or endpoint switch occurs. Already streamed partial content,
reasoning, tool deltas, refusal prose and raw provider payload MUST NOT enter the
rejection receipt, evidence, terminal or normal model history. Only the safe
descriptor and independently available usage are retained. It does not advance
input protection coverage. Hosts retire or replace their temporary displayed
answer when the failed event/terminal arrives. The transport's earlier output
veto applies to exception classification; it MUST NOT override this definite
upstream response conclusion. Missing-termination EOF has priority over a finish
verdict; cancellation and interrupted consumption retain existing error paths.

[Completion mapping](model-completion.md) specifies refusal-text answers, EOF,
unknown observation and the evidence fields. The existing retry rules still
apply to request rejection and Unknown. This addition changes no record, inbox,
SQL, event or App Server version; old sessions use only representations readable
and continuable by 0.33.3. Declared sessions and their derived dependents must
remain routed to the newer runtime.
