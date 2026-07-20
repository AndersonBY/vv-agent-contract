# Optional Output Validation And Repair

Contract `0.9.0` adds a host extension for validating a completed output and,
when the host explicitly supplies one, asking a separate repair callback for a
replacement value. It is deliberately outside the default agent loop.

## Defaults

The capability is disabled unless the host registers a validator and enables
it for the run. With no enabled validator, the runtime performs no additional
callback, emits no additional trace event, and keeps the existing terminal
observation and output behavior byte-for-byte compatible.

The host may set a repair callback and a maximum repair count, but the contract
currently permits at most one repair attempt. A repair request carries the
invalid value and typed validation details, plus an independently selected
model/config description. Its `tools` collection is always empty. The runtime
does not call the primary model again through this extension and does not
infer a task category, answer pattern, domain milestone, or stopping rule.

## Lifecycle

1. The normal runtime reaches its existing terminal candidate.
2. The host validator returns `valid` or a typed `invalid` result.
3. A valid value proceeds unchanged.
4. An invalid value without a repair callback becomes a typed
   `output_validation_failed` result.
5. With a repair callback, the runtime makes one explicit request and
   validates the returned value again.
6. A second invalid value, a callback exception, or an invalid repair response
   becomes the same typed failure; no second repair is attempted.

The validator and repair callback are observers/extensions. They cannot add
tools, expand an existing policy, fabricate a successful terminal, or replace
an earlier cancellation, budget exhaustion, reconciliation, or operator-abort
terminal. Hosts that need a domain-specific output format own that validator,
prompt, and scorer in their application or evaluation layer.

## Compatibility And Evidence

The canonical behavior is frozen in `fixtures/output_validation_v1.json`.
Implementations must provide disabled, pass, fail, one-repair, second-failure,
and provider-failure producer tests. The fixture is vendored by both language
repositories through `scripts/contract_snapshot.py sync`; it is never edited
in an implementation repository.
