# Contract 39.0.0

Status: unpublished normative authoring checkpoint; pending adoption. Python is
the only required implementation. No 39.0.0 implementation revision, producer
capture or central verification is claimed. Python P1 may remain in package
series 0.36.x. Rust remains frozen at contract 23.0.0 / package series 0.21.x,
verified revision `00f4240786f1adea1dc0c4730da8ddd06a5ab8ac`.

## Public change and data boundary

A failed closed session-schema check reports exactly `invalid session schema`.
It does not expose customer input or schema dumps. Concrete jsonschema
ValidationError causes and pretty-print/schema/path identity are not retained
as compatibility requirements. The [session-kernel rule](session-kernel.md#closed-schema-rejection-diagnostic)
owns the scope and error precedence.

Existing explicit semantic, parser and duplicate-member diagnostics remain.
Provider and model-selection paths retain `provider_result_invalid` and
`model_selection_unresolvable`. Accepted/rejected values and validation order,
canonical bytes and IDs/digests, execution, admission and retry behavior remain.

The diagnostic can reach App Server clients, so this is a major public behavior
replacement. It is not a record, inbox or SQL boundary: record schema 1, inbox
schema 3, SQL layouts, RunEvent v6, App Server v5, public API inventory and frozen
definitions stay unchanged. Existing stored sessions need no migration, store
drain, decoder selection or byte rewriting.

## Outstanding producer evidence and gates

This checkpoint changes normative docs and version/adoption metadata only.
Existing fixture bytes and SHA256SUMS remain unchanged. No fixture may be
handwritten to stand in for a real producer, and this checkpoint is not ready
for publication or adoption verification.

After SDK implementation, capture the actual Record/Inbox codec failures and
real App Server propagation using deterministic local producers. Evidence must
cover representative closed-envelope/payload/nested-schema failures, the exact
concise diagnostic and absence of input/schema dumps, preserved acceptance and
JCS identity, explicit semantic/parser/duplicate messages, ModelSettings
semantic validation, and unchanged provider/model-selection codes. Do not
freeze concrete third-party causes or reproduce a schema-validator formatter.

Add or extend the appropriate canonical fixture only from that producer and
review the semantic diff. Then regenerate SHA256SUMS with contractctl manifest;
run contract validation, independent Node JCS, repository unittests and two
byte-identical bundle builds. Python must pass focused real-producer and full
pytest/ruff/ty gates, applicable SQLite memory/file and real PostgreSQL gates,
and required central cross-repository checks. Keep adoption pending until the
required immutable pins and successful default-branch revisions/run are
recorded through the normal adoption workflow.

Immutable publication is a separate approval step. Implementation locks and
vendored snapshots remain untouched at this authoring checkpoint; synchronize
them only through the approved publication/adoption workflow. The frozen Rust
entry and its pinned contract are preserved throughout.
