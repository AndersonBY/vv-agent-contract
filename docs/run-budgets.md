# Run Budget Contract

This document defines the current language-neutral resource budget contract.
Budgets control resource admission and accounting. They do not decide whether
an Agent has answered a task correctly or whether a task is semantically
complete.

## Public Configuration

`RunBudgetLimits` contains only optional limits:

- `max_total_tokens`
- `max_uncached_input_tokens`
- `max_tool_calls`
- `max_tool_calls_by_name`
- `max_wall_time_ms`
- `max_host_cost`
- `unavailable_metric_policy`

Every integer is in the inclusive range `0..9007199254740991`. Boolean values
are not integers. Tool names and host units are non-empty strings. Currency is
optional and, when present, is a non-empty string. An absent limit is unlimited;
an absent or empty `RunBudgetLimits` has no runtime effect. The unavailable
metric policy defaults to `continue_and_mark`; `stop` is opt-in.

Arithmetic that cannot be represented in this wire-safe range makes the
affected cumulative metric unavailable with reason `integer_overflow`; it is
never wrapped, truncated, or coerced to zero.

Per-run limits replace, rather than merge with, configured Runner defaults.
The same precedence applies to the optional host cost meter. Agents do not
define implicit budgets.

An object that sets only `unavailable_metric_policy` has no configured
dimension and is therefore unlimited. Wire objects are closed: decoders reject
unknown fields and invalid values. Exact-name maps serialize in lexicographic
key order.

## Usage And Availability

`BudgetUsageSnapshot` contains:

- started Agent `cycles`;
- nullable `total_tokens` and `uncached_input_tokens`;
- admitted `tool_calls` and exact-name `tool_calls_by_name`;
- monotonic active `elapsed_ms`;
- nullable cumulative `host_cost`;
- latched `unavailable_dimensions` observations.

Token totals are available only when every dispatched framework model attempt
has the corresponding accounting. This includes `agent_cycle`,
`session_memory`, `memory_compaction`, and `output_repair`; opaque host callbacks are not
fabricated. Missing usage is never zero. Tool counts include
every invocation admitted for execution, regardless of success, tool error,
timeout, approval interruption, or directive. A rejected batch is not admitted
and does not increment the counters.

Provider-reported and explicitly estimated total token usage are available for
`total_tokens`; `accounting_missing` is unavailable. Uncached input is
available only from the typed cache observation's non-null
`uncached_input_tokens`, including explicit zero. Native fields inside
`provider_usage` do not make that metric available to the budget layer.

Elapsed time uses observed monotonic active intervals; parked intervals are
excluded. Completed intervals survive reconstruction. A lost active interval is
unavailable, never inferred from process downtime; strict stop policy must stop.
End-to-end scheduling deadlines are separate controls.

Elapsed nanoseconds are floored to whole milliseconds. Cumulative elapsed time
never decreases. Overflow beyond the wire-safe integer range is latched as
`integer_overflow` rather than saturated or wrapped.

An unavailable dimension is latched for the rest of the run. Later readings do
not convert an incomplete accounting history into a complete one. Only
configured dimensions can make a run stop because of unavailability.

Unavailable observations are unique by dimension and serialize in the stable
dimension precedence order. Once a dimension is latched unavailable, the
framework does not keep polling or recomputing it during that run.

## Host Cost Meter

`HostCostMeter.read()` returns a cumulative `HostCost` reading for a scope
chosen by the host, returns no reading when accounting is unavailable, or
reports an error. The framework contains no price table and never converts
units or currencies.

`HostCost` contains a host-defined `unit`, optional `currency`, and integer
`amount_microunits`. The reading must use the exact unit and currency configured
by `max_host_cost` and must never decrease. A missing meter, unavailable
reading, meter error, unit mismatch, currency mismatch, or non-monotonic reading
makes `host_cost` unavailable. Error text is not copied into the stable wire
shape.

The meter reading is already scoped cumulative usage; the framework does not
subtract an implicit baseline. A host that wants a shared parent/child budget
passes the same scoped meter explicitly to both runs. Framework-created child
runs otherwise receive fresh counters and do not implicitly aggregate parent
or sibling usage.

The meter is sampled at every applicable enforcement boundary so a shared
scope can change between local operations. A deterministic test meter returns
its final scripted reading again after the script is exhausted.

Hosts re-supply process-local meter references through required host bindings.
Missing bindings fail before execution; a missing/error meter remains typed metric
unavailability. Frozen limits and durable measurements survive reconstruction.

## Enforcement Boundaries

The stable boundaries are:

1. `run_start`
2. `cycle_start`
3. `model_call_complete`
4. `tool_batch_preflight`
5. `tool_batch_complete`
6. `terminal`

Cancellation already visible at an admission boundary is observed before the
budget. Before a model call, an observed token or cost value equal to its limit
has no remaining capacity and stops admission. A model call admitted below a
limit is atomic: provider usage and host cost are observed after it terminates,
and either may exceed its limit by that one attempt. The updated budget is
checked before another internal or primary model call is dispatched.

Tool batches are preflighted as a whole. Total calls are checked first, then
exact-name limits in lexicographic tool-name order. A batch that would exceed
any limit executes no tools. A passing batch atomically reserves every total and named call with the model
receipt and complete ordered plans before any tool effect. A shortfall rejects the
whole batch with zero effects. Reserved calls skipped by finish or wait still
count; replay and retry cannot reserve twice. Dynamic wall/host checks still apply
before each dispatch.

Limits are inclusive. A natural terminal reached with an observed value equal
to the limit remains valid. A post-operation value greater than the limit is
`limit_exceeded`; an admission denied because no capacity remains is
`limit_reached`. `overshoot` is zero for a reached limit, the positive observed
excess after an atomic operation, or the positive projected excess for a tool
batch preflight.

When several dimensions fail at one boundary, the stable selection order is
`wall_time`, `total_tokens`, `uncached_input_tokens`, `host_cost`, `tool_calls`,
then exact-name tool calls sorted by name. All observed values remain in the
snapshot even though one `BudgetExhaustion` is selected as the terminal cause.

## Missing Metrics

With `continue_and_mark`, an unavailable dimension is recorded and execution
continues without enforcing that dimension. Other dimensions remain enforced.
With `stop`, the first configured unavailable dimension produces a
`metric_unavailable` exhaustion at the boundary where it becomes unavailable.

Token usage may become unavailable only after an atomic LLM call. Host cost can
be unavailable at `run_start`. Explicit provider-reported zero remains zero and
is enforceable.

## Terminal Precedence And Observation

Budget termination uses `AgentStatus.failed` with
`CompletionReason.budget_exhausted`. It is a typed non-success result, never a
business completion. `completion_tool_name`, `final_answer`, and `wait_reason`
are null; `error` is `Run budget exhausted.`; `partial_output` remains the last
non-empty assistant response from a completed LLM cycle.

An operation error that has already occurred remains `failed`; budget
accounting does not hide it. Cancellation observed before terminal projection
remains `cancelled`. Otherwise budget exhaustion precedes tool finish/wait,
no-tool policy, output guardrails, and max-cycles projection. A budget stop
emits one `budget_exhausted` event followed by the ordinary `run_failed`
terminal. Both carry the final snapshot and exhaustion. Non-exhausted terminal
events carry the final snapshot when a budget was configured.

`budget_snapshot` events are emitted only for configured budgets and only when
accounting state changes at an enforcement boundary. Runs without limits emit
no budget events and preserve canonical event order. These are current
`RunEvent` records and therefore require `version=v6`.

For a configured budget, `run_started` remains first. A non-terminal
`run_start` observation emits the initial snapshot, each completed LLM
accounting update emits a snapshot, and a passing tool preflight emits the
post-reservation snapshot. Later boundary observations emit a snapshot only
when a value or unavailable latch changes. An exhausting boundary emits
`budget_exhausted` instead of a snapshot for that boundary. The ordinary
terminal follows and carries the same final objects.

App Server projects a budget stop as turn status `failed` and exposes optional
`budgetUsage` and `budgetExhaustion`. Result, event, App Server, and durable
terminal projections use the same wire objects.

## Same-turn recovery

User and approval replies resume the same turn and preserve its frozen limits,
cycle allowance and accumulated usage. Receipts determine accounting rather than
re-admission. Fresh turns get fresh counters unless the host explicitly supplies
a shared scoped meter. Primary cycles exclude extraction, summary, repair and
prompt-too-long recovery. An arbitrary external effect is not made exactly once
by durable accounting. See [session kernel](session-kernel.md).

## Canonical Evidence

`run_budget.json` contains executable evaluator and public Runner inputs.
Required implementations must drive every `runner_cases` record through the public
Runner and real runtime/tool producer path. `budget_events.jsonl` contains
canonical event wire records that required event producers and decoders must
rebuild. Assertions that merely compare fixture-owned booleans are not
sufficient adoption evidence.
