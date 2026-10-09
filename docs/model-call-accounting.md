# Model-call accounting

Every framework-issued attempt is observable and budgeted. Current closed wires
are model-call v2 and task-token-usage v3; TokenUsage remains v1. Exact cases and
negative vectors are in `token_usage.json`. No task category or answer quality is
inferred.

A ModelCallRecord identifies call_id, operation_id, attempt, operation,
cycle_index, backend, model, status, usage and error_code under its current
schema discriminator. Operations are agent_cycle, memory_compaction,
session_memory and output_repair. Status is completed/failed/ambiguous. A completed
call has null error_code; other statuses retain a nonempty content-free code.
The record carries no prompt/output/provider error body. Native measurements stay
in TokenUsage.provider_usage.

Call ID is `{operation_id}/{attempt}`. Retry preserves operation ID, increments
attempt and creates a distinct call ID. Changed effective requests have their own
logical identity. Frozen endpoint order selects each actual backend/model;
transport retries are one per logged attempt. Ordinary model operation capacity
is max(2, endpoint count), including two attempts for fewer than two endpoints.
Required unavailable metrics can stop fallback. Unknown output repair never retries.

Usage is captured before an after-model callback can change content. Hooks cannot
change normalized usage or provider identity. All attempts, including failures and
unknowns, contribute to task totals. A count is null if any dispatched attempt
lacks it. Cache aggregation requires complete corresponding observations. Unknown
usage is never zero. An empty ledger has exact zero token totals and
accounting_missing cache status. Cycle records do not duplicate this ledger.

Before provider effects, a durably admitted op_started retains dispatch identity,
authorization and endpoint evidence. Terminal operation/result, accounting and
budget changes commit together; model receipt, whole tool-batch reservation and
all plans are atomic. Retained receipts MUST be reused, with no call, record or
budget duplication. Recovery of a started operation without authentic acceptance
or result records unknown evidence and unavailable usage; a duplicate-risk retry
has its own retained accounting. [Session kernel](session-kernel.md) owns these
fences and late-result rules.

RunEvent v6 projects model_call_started/completed/failed with exactly the same
seven identity fields: call_id, operation_id, attempt, operation, cycle_index,
backend, model. Completed maps to completed; definitive failure to failed;
ambiguous failure to ambiguous. Terminal model observation precedes any budget
snapshot/exhaustion. Live primary stream deltas remain optional telemetry.

Every new internal or primary dispatch checks current budgets. Internal inference
does not consume extra primary cycles. Compaction uses tools-free logged operations;
a rejected summary still counts if dispatched. Same-source/mode/tail receipt reuse
adds no usage. Accepted replacement has its own context_compacted record.
Session Memory extraction is also tools-free and logged; structured state commits
before disposable file projection. Session Memory is disabled unless the exact
public session_memory_enabled boolean is true for that run or child; seed,
existing file or parent enablement cannot implicitly activate it.

Content-free session_memory_output_invalid diagnostics may accompany fail-soft
optional extraction errors. Cancellation, budget exhaustion and integrity errors
propagate. Independently issued host model calls are outside automatic accounting;
the framework does not invent measurements for them.
