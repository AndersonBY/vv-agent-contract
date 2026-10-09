# Output validation and repair

Validation is opt-in. Without an enabled host validator, native terminal behavior
performs no extra callback. Exact inputs and outputs are in `output_validation.json`.

At a normal completion candidate, validate the value. A valid candidate proceeds
unchanged. Invalid output without repair ends with output_validation_failed.
An enabled repair makes at most one explicit tools-free, budgeted and logged
output_repair operation carrying the invalid value and typed validation details.
Validate its returned value again; a second invalid value, provider failure,
coercion exception or invalid repair response becomes a durable failed result
with partial-output evidence. Unknown repair is never automatically retried.

An output_checked boundary retains completed/failed/repair status, reason, value
and optional partial_output before finalization or another dispatch. Committed
checks and repair receipts MUST be reused on recovery. Precommit callback
interruption permits repetition. Output validation cannot add tools, broaden
policy or override cancellation, abort or budget exhaustion. Handoff validates
the target's executed output, not the source's temporary transfer marker.

[Model-call accounting](model-call-accounting.md) owns repair measurement;
[session kernel](session-kernel.md) owns durable boundaries and terminal evidence.
Task-specific formats, prompts and acceptance scorers remain host responsibilities.
