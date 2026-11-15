# Contract 40.0.0

Status: unpublished contract-first S1 allocation; adoption pending. Python is the
only required implementation. No Python 40.0.0 revision, real S1 producer capture,
storage implementation or central adoption is claimed. Rust remains frozen at
contract 23.0.0 / package series 0.21.x, verified revision
`00f4240786f1adea1dc0c4730da8ddd06a5ab8ac`.

## Public boundary

Record and inbox envelopes use the string discriminator `"S1"` and
`feature_level=1`. Record `1`, inbox `3` and SQL schema `1` are replaced. A
reader for one of those values, an alias, a legacy decoder, a dual-format path or
a compatibility shim is not part of this contract.

Creation records carry a closed tenant-scoped `principal`; inbox items carry the
same closed Principal shape as `actor`, with `subject_kind` closed to
`user|service|agent`.
Admission proofs and consumed-input proofs are either null for explicit unsigned
local mode or closed signed objects. `turn_started` carries a nullable
`policy_digest`, closed `requirements`, and a nullable closed environment binding
with capability and policy-reference digest slots. Its `operational_policy` slot
is `ContentRef|null`; the closed operational object and its private digests remain
inside encrypted content.

`ContentRef` is the closed reference
`{content_id,mac,size,key_id,labels}`. `labels` is the closed
`{source,classification}` object. Source arrays follow the declared source-kind
order and are duplicate-free; the P2 default is `source=[]`,
`classification="internal"`. Logical records and inboxes use ContentRef for
workspace, attributes/seed, definition, budget, request/tool/hook/shared state,
result/usage, questions/interactions, provider handles/evidence, inbox
bodies/results/approval scope/reasons, and boundary data. Plaintext C objects
reject.

Record chaining is not a logical identity field. The separate closed
`fixtures/session_storage_envelope.json` fixture and schema allocate
`{schema_version,tenant_id,session_id,seq,record_digest,chain_digest,writer_epoch,created_ms}`,
the initial/next framing bytes and negative cases. `chain_digest` is excluded from
logical bytes and identity; this is store input, not SQL DDL or a second execution
ledger.

P2 slots cover `policy_decision` on operation plan/preparation/completion,
approval `policy_digest/rule_id/expires_ms`, closed `usage_counts` with unavailable
dimensions, and a frozen tokenizer/counting binding.
`fixtures/session_storage_lifecycle.json` allocates key-capability destroy
semantics, forget tombstones, and versioned JSONL skeleton/include-content export
with deterministic accepted/rejected cases.

The focused fixture `fixtures/trusted_storage_s1.json` supplies accepted S1
shapes and deterministic rejection cases. `session_record.schema.json`,
`session_inbox.schema.json`, codec vectors and current record/inbox streams reject
unknown fields, old discriminators and unsupported feature levels. The
`fixtures/session_record_diagnostics.json` and other marked producer captures
remain historical 39 evidence: their canonical producer bytes were not rewritten
and they are not evidence that Python emits S1. Every S1 fixture here is synthetic
allocation material until a pinned Python producer runs the adoption gates.

## Deferred implementation work

P3 retains worker support-set claim filtering, complete execution-environment and
provider lookup behavior, command start/query semantics, and composition of the
allocated typed references with real content stores. P4 retains W6 policy
evaluation/activation, W7 source-label propagation, and security-baseline
activation. Python producer/storage adoption, SQLite/PostgreSQL DDL, PostgreSQL
RLS, and the Python `KeyProvider` remain implementation work. These slots are not
delivered features. Contract fixtures do not prescribe SQL table layout, RLS or
Python symbol spellings.

## Verification

This allocation requires the canonical Node JCS verifier, contract validation,
the repository unit suite, deterministic double build and whitespace checks.
`fixtures/SHA256SUMS` is generated only with `python3 scripts/contractctl.py
manifest`. The support matrix stays pending until a real Python producer and the
full adoption gates provide pinned evidence.
