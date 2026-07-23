# Model Call Accounting And Recovery

Contract `3.0.0` makes every framework-issued model attempt observable and
budgeted. The contract is task-neutral: it records which runtime mechanism
requested inference, but never infers a task category, semantic progress, or
answer quality.

## Explicit Session Memory

Persistent Session Memory is disabled unless the host explicitly enables it.
The top-level `RunConfig` and each configured sub-agent expose one boolean
`session_memory_enabled` control whose default is `false`. A parent does not
implicitly enable a child.

Current runtimes do not accept an `enable_session_memory` alias and do not
enable Session Memory merely because seed data, a storage path, extraction
settings, or an existing memory file is present. Runtime metadata cannot
override an explicit public control. Lower-level task construction may project
the same exact boolean, but omission still means disabled.

When the control is false or omitted, the runtime does not render supplied
Session Memory context, read or write the Session Memory store, or dispatch a
Session Memory model operation. A non-empty context, seed, or existing store is
ignored at this gate rather than becoming an alternate activation path.

Enabling Session Memory permits additional model calls and workspace writes.
Those calls follow the same accounting, event, budget, checkpoint, and failure
rules as the primary Agent cycle.

## Model Call Record

`TaskTokenUsage` uses
`schema_version=vv-agent.task-token-usage.v2`. Its `model_calls` array replaces
the cycle-only usage array. Every framework dispatch attempt admitted across
the local provider boundary eventually produces exactly one closed
`ModelCallRecord`, including failed or outcome-ambiguous attempts. Admission
means the provider may have received the request; it does not claim that remote
receipt can be proven after a crash.

Each record contains:

- `call_id`: stable identity for one dispatch attempt;
- `operation_id`: stable identity for the logical model operation;
- `attempt`: one-based dispatch-attempt number within that operation;
- `operation`: `agent_cycle`, `session_memory`, or `memory_compaction`;
- `cycle_index`: the positive Agent cycle associated with the call;
- `backend` and `model`: the actual resolved provider backend and model id;
- `status`: `completed`, `failed`, or `ambiguous`;
- `usage`: one complete `vv-agent.token-usage.v1` object;
- `error_code`: null for completed calls and a non-empty, content-free code for
  failed or ambiguous calls.

`call_id` is unique within a run. A logical retry keeps `operation_id`,
increments `attempt`, and receives a new `call_id`. Prompt-too-long recovery
that changes the effective request is a new logical operation. Replaying a
durable receipt creates neither a new attempt nor a second record.

Normalized usage is captured from the provider response before an `AfterLlm`
hook or equivalent host callback may replace response content or tool calls.
Such callbacks cannot rewrite the usage, backend, model, or identity retained
for the dispatch attempt.

The record never contains prompts, messages, model output, reasoning, provider
errors, credentials, or native response bodies. Native usage fields remain
only in `TokenUsage.provider_usage`.

## Aggregation

Task totals aggregate every `model_calls[*].usage`, not only
`agent_cycle` calls. A count is null if any dispatched attempt lacks that
count. Cache totals are available only when every dispatched attempt provides
the corresponding cache observation. A failed or ambiguous call with unknown
usage therefore makes the affected task total unavailable instead of silently
under-counting cost.

An empty ledger means no model dispatch occurred. Its input, output, total, and
reasoning token counts are exact zero; cache status remains
`accounting_missing` because no provider cache observation exists.

Agent `CycleRecord` no longer carries a second token-usage copy. The
`cycle_index` and `operation` on each model-call record provide the only usage
breakdown. This prevents a primary-cycle view and a run-total view from
diverging.

`CycleRunner` is an internal orchestration component in the current public
surface. Public callers use `Runner`, whose success, interruption, and failure
results all retain the run-level ledger. This avoids a low-level cycle return
shape that would lose failed attempts or internal calls.

## Events

The current `RunEvent` union replaces `llm_started` with three task-neutral
events:

- `model_call_started` marks durable local dispatch admission, after which the
  provider may or may not have received the request;
- `model_call_completed` carries the normalized `TokenUsage`;
- `model_call_failed` carries normalized usage, a content-free error code, and
  whether the external outcome is definitive or ambiguous.

The event-to-ledger mapping is exact: `model_call_completed` maps to
`status=completed`; `model_call_failed(outcome=definitive)` maps to
`status=failed`; and `model_call_failed(outcome=ambiguous)` maps to
`status=ambiguous`.

All three include `call_id`, `operation_id`, `attempt`, `operation`,
`cycle_index`, `backend`, and `model`. A replay does not emit a new started
event. Durable event delivery reuses the original event identity and payload.
Model stream deltas remain associated with the same cycle and are emitted only
for the `agent_cycle` operation.

## Budgets

The token-budget enforcement boundary is `model_call_complete`. Every terminal
model-call record is observed exactly once by the budget controller before the
runtime dispatches another model call or tool. Missing usage follows the
configured unavailable-metric policy. An internal call can therefore exhaust a
run budget before the primary cycle call begins.

Host-owned callbacks that independently call a model are outside automatic
accounting. A host must route such inference through a future explicit metered
operation API before claiming it is included. In particular, the framework
does not fabricate usage for an opaque output-repair callback.

## Checkpoint Atomicity

Checkpoint `vv-agent.checkpoint.v3` stores the run-level model-call ledger. A
model journal entry records its operation and the actual effective `backend`
and `model`; internal calls must not copy these values from the root run
definition. Before provider dispatch,
the `started` journal transition and pending `model_call_started` outbox entry
become durable in one compare-and-swap progress update. Recovery therefore
treats that attempt as ambiguous even if a crash occurred before the provider
actually received the request.

For each dispatched attempt, the following terminal facts become durable in one
compare-and-swap progress update:

1. the terminal journal state and response or content-free error;
2. the corresponding `ModelCallRecord`;
3. the post-call budget snapshot;
4. the completed or failed event in the durable outbox.

The journal, started event, terminal event, and ledger record must agree on
`call_id`, `operation_id`, `attempt`, operation, `cycle_index`, `backend`, and
`model`. A missing or mismatched identity makes the checkpoint invalid.

The terminal CAS appends the terminal model event first. When a budget is
configured and accounting changed, `budget_snapshot` follows it. If that
boundary exhausts a limit, `budget_exhausted`, which carries the final snapshot,
replaces `budget_snapshot` for the same boundary. These entries are contiguous
and become durable in the same CAS. Runs without a configured budget append no
budget event.

If that atomic update is not confirmed after dispatch, the operation becomes
ambiguous and requires the existing reconciliation policy. On resume, the
budget controller and public usage ledger initialize from the checkpoint.
Turning a retained `started` attempt into `ambiguous` atomically appends its
ambiguous model-call record, latches unavailable usage in the budget snapshot,
and stages `model_call_failed(outcome=ambiguous)` before the runtime suspends or
admits a duplicate-risk retry.
Replaying a succeeded or failed receipt does not append usage or charge the
budget again. Retrying an ambiguous operation appends a new dispatch attempt,
while the first ambiguous attempt remains visible and keeps unknown totals
unknown.

Replaying a successful internal-call receipt may deterministically reapply the
derived memory mutation, but it does not dispatch a model or append accounting.
Session Memory merges by its canonical entry key before advancing its extraction
baseline; compaction reapplies the retained summary to the same frozen message
input. These derived mutations must be idempotent across a crash and replay.

Completed cycle commits may clear active operation journals, but they do not
remove model-call records. Terminal replay returns the retained ledger without
model dispatch.

## Session Memory Diagnostics

Session Memory output parsing is fail-soft but not silent. Invalid extraction
output emits a `diagnostic` event with code
`session_memory_output_invalid`. Details may contain cycle, backend, model, and
a closed reason enum, but never the extraction prompt or model output.

Ordinary optional extraction failure may emit a content-free diagnostic and
continue. Cancellation, budget exhaustion, checkpoint ambiguity, and durable
integrity failures are control outcomes and must propagate; Session Memory may
not swallow them.
