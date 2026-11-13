# Contract 39.0.0

Status: unpublished with local real-producer evidence; pending adoption. Python
is the only required implementation. No verified 39.0.0 implementation revision
or central adoption is claimed. Python P1 may remain in package
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

## Producer evidence and outstanding gates

`fixtures/session_record_diagnostics.json` is copied unchanged from the real
Python producer `vv-agent/scripts/record_codec_fixtures.py`. It exercises closed
record/inbox envelopes, payloads and reserved metadata; retained identity,
embedded-digest, duplicate-member, non-object, parser and ModelSettings errors;
real App Server error propagation; provider acceptance and model-selection codes;
and unchanged canonical Record/Inbox bytes and SHA-256 identities.

The captured `RecordError` label denotes the error category and Python adaptation
(`RecordError(ValueError)`), not a required third-party exception cause. The
malformed-JSON message is current required Python implementation evidence; it
does not prescribe a universal parser formatter or jsonschema cause identity.
No customer input or schema dump is included in the capture. The Python producer
tests also check the actual App Server rejection's exception chain for those
excluded values.

`tests/test_session_record_diagnostics.py` checks the captured structure and
validates its logical Record/Inbox objects with the independent canonical codec.
`scripts/verify_jcs.mjs` independently checks their canonical bytes, hashes and
record identity. Python's
`tests/test_kernel_record_codec.py::test_real_diagnostic_producer_matches_canonical_fixture`
compares a fresh real producer capture byte for byte through the existing
`VV_AGENT_CONTRACT_SOURCE` local-source resolver. The fixture manifest is rebuilt
with `contractctl.py manifest`.

Required local canonical gates are contract validation, independent Node JCS,
repository unittests and two byte-identical bundle builds. Python must pass
focused real-producer and full pytest/ruff/ty gates, applicable SQLite memory/file
and real PostgreSQL gates, and required central cross-repository checks. Keep
adoption pending until the required immutable pins and successful default-branch
revisions/run are recorded through the normal adoption workflow.

Immutable publication is a separate approval step. Implementation locks and
vendored snapshots remain untouched; synchronize them only through the approved
publication/adoption workflow. The entire frozen Rust entry and its pinned
contract are preserved throughout.
