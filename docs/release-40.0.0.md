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

Records require `chain_digest`. Creation records carry a closed tenant-scoped
`principal`; inbox items carry the same closed Principal shape as `actor`.
Admission proofs and consumed-input proofs are either null for explicit unsigned
local mode or closed signed objects. `turn_started` carries a nullable
`policy_digest`, closed `requirements`, and a nullable closed environment binding
with capability and policy-reference digest slots.

`ContentRef` is the closed reference
`{content_id,mac,size,key_id,labels}`. `labels` is the closed
`{source,classification}` object. Source arrays are sorted and duplicate-free;
the P2 default is `source=[]`, `classification="internal"`. The first allocation
uses ContentRef in Principal attributes and the environment descriptor. Migration
of every existing encrypted content slot is part of later implementation work.

The focused fixture `fixtures/trusted_storage_s1.json` supplies accepted S1
shapes and deterministic rejection cases. `session_record.schema.json`,
`session_inbox.schema.json`, codec vectors and current record/inbox streams reject
unknown fields, old discriminators and unsupported feature levels. The
39.0.0 real-producer capture remains historical 39 evidence: its bytes were not
rewritten and it is not evidence that Python emits S1.

## Deferred implementation work

P3/P4 retain worker support-set claim filtering, complete execution-environment
and provider lookup behavior, command start/query semantics, W6 policy evaluation,
W7 source-label propagation, all remaining typed content-slot allocations, Python
producer/storage adoption, SQLite/PostgreSQL DDL, PostgreSQL RLS and the Python
`KeyProvider`. These are not implied by the nullable or reference slots allocated
here. Contract fixtures do not prescribe SQL table layout, RLS or Python symbol
spellings.

## Verification

This allocation requires the canonical Node JCS verifier, contract validation,
the repository unit suite, deterministic double build and whitespace checks.
`fixtures/SHA256SUMS` is generated only with `python3 scripts/contractctl.py
manifest`. The support matrix stays pending until a real Python producer and the
full adoption gates provide pinned evidence.
