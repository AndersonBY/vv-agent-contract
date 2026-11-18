# Contract 42 B5 compaction source authority proposal

Status: proposed for the next major contract. This document is not a Contract 41
shape, implementation claim or producer-capture claim.

## Decision

B5 cannot enter Contract 41.0.0. Contract 41 explicitly keeps level-1 bytes and
defaults unchanged. B5 replaces both the preimage of the existing
`context_compacted.source_digest` and the identity semantics of the existing
`prefix_ids` and `tail_ids`. The version policy says that changing the meaning,
identity, digest input or validation of an existing field requires a new major.

The Contract 24 through Contract 41 compaction vectors retain the same seven
`source_digest`, `prefix_ids` and `tail_ids` values. Contract 40 changed the
record envelope to S1, but did not replace those compaction identities. The
current references are `<decimal-position>/<D(message)>`; they already reject a
same-length content change. Replacing them with `s1-message/{index}` or hashing
only ordered positions would weaken the boundary and is rejected.

## Contract 42 authority

Let `S` be the exact session ID in the containing S1 record, `M[i]` be normalized
model-visible source Message JSON at zero-based position `i`, and `D(x)` be the
RFC8785 JCS plus SHA-256 definition in the session kernel.

Message references use the closed string form:

```text
m1/<position>/<message_digest>
```

`message_digest = D({domain,message,position,session_id})`, with exactly:

```json
{
  "domain": "vv-agent/context-compaction-message.v1",
  "message": "<M[position]>",
  "position": 0,
  "session_id": "<S>"
}
```

The position is decimal with no sign or leading zero except `0`, and
`message_digest` is 64 lowercase hexadecimal characters. The same Message bytes
in another session, another position or under another domain produce a different
reference. Identical messages at two positions also remain distinct while each
reference still commits to the message bytes.

For source messages `M[0..n-1]`, form `message_ids` in source order and compute:

```text
source_digest = D({
  "domain": "vv-agent/context-compaction-source.v1",
  "message_ids": ["m1/0/...", "...", "m1/{n-1}/..."],
  "session_id": S
})
```

The source digest commits to the session, complete ordered source length, every
message position and every message's canonical content. It is a content binding,
not an authenticity token. Record authentication remains the existing
ContentRef, signed proof and storage-chain responsibility.

`prefix_ids` and `tail_ids` remain arrays in the existing `context_compacted`
fields. Contract 42 changes their item schema to:

```json
{
  "type": "string",
  "pattern": "^m1/(0|[1-9][0-9]*)/[0-9a-f]{64}$"
}
```

Both arrays are ordered by ascending source position. Their union MUST equal the
complete source reference list exactly once. Prefix and tail references MAY be
non-contiguous for microcompaction, but neither array may contain duplicates.
The summary plan still determines which prefix references are removed. A record
MUST reject if any reference, position, message digest, array partition or
`source_digest` differs from the actual source projection.

The summary request metadata, `summary_operation_id`, `record_id` and same-source
receipt reuse continue to use `source_digest`. No source digest copy, second
ledger, position-only ID, plaintext payload digest or compatibility field is
introduced.

## Canonical vectors

The positive vector below uses these source Messages:

```json
[
  {"content":"alpha","role":"user"},
  {"content":"beta","role":"assistant"},
  {"content":"charlie","role":"user"},
  {"content":"delta","role":"assistant"}
]
```

For session `session-a`, its canonical summary vector is:

```json
{
  "session_id": "session-a",
  "source_digest": "3283897fb1738a4ad902145ed426ec1ad421a46fbc7449ef70efc09f2b1d64b5",
  "prefix_ids": [
    "m1/0/03b52dca7404e65b913c32ea92855438e331301dbbd0f7530bffcb183850278c",
    "m1/1/86be7456d059e8f18d851f818c7665722ae5ba7b9a31ef7ce3e2f71511940add"
  ],
  "tail_ids": [
    "m1/2/631dba396f206ff1bc6e28206772524cdae08adeed111f7e8fe21f34321d8ffd",
    "m1/3/cca661b8df0228c822d91c00ca29dbcef8db6e07ca9b5391c5fe9111d9bc4e8e"
  ]
}
```

The canonical microcompaction vector uses session `session-micro` and source
Messages `alpha/user`, `beta/assistant`, `charlie-result/tool`, `delta/user`,
`echo/assistant`:

```json
{
  "session_id": "session-micro",
  "source_digest": "d3f6e4612a4b230184946b7555d18d8382f65344c25f366b413d006c5a4ed184",
  "prefix_ids": [
    "m1/2/e47849e0eca01807a3e78521f60ca968cc9097320be0e2997c649e69a63abf7c"
  ],
  "tail_ids": [
    "m1/0/8d7a96d579ff1b91ae6b5a98d18c5cb3bbbfd0a301ff14c4042613b3c766a",
    "m1/1/1c122d5f96dbb10e2e89fe084380f4a42fac41aeb651bd95cd2dea5a0f7d4a4b",
    "m1/3/5c111c8a2151396e930b2f85966a3a8842e167ae9f852cf271730639c3baecc8",
    "m1/4/8b7b170f009ab4a53b9715a5661fa3711f1a45fd201c41d5525ee8d0ed386bda"
  ]
}
```

Required negative vectors:

| Name | Mutation | Required result |
| --- | --- | --- |
| same_length_content | Change message 1 from `beta` to `gamma`; retain all stored references and digest | Reject; expected message ref ends `59e5d520127e009f27069ef013a4410b26343b0cfc4a2995e9e9fff558757778`, expected source digest `458d2c665210f64546fa41f4d889bd887c0cd50f4b18b15469d97dc4c7459f88` |
| other_session | Reuse `session-a` messages and references under `session-b` | Reject; expected source digest `0fec1537f0ffcee8aaa6a0c6c1e2d7dafb7ab7fe38a2e7f04baee5dd959f0ab3` |
| position_only | Replace an item with `m1/1` or `s1-message/1` | Reject schema before fold |
| duplicate_reference | Repeat one reference in prefix or tail | Reject identity partition |
| missing_reference | Omit one source position from both arrays | Reject identity partition |
| wrong_partition | Move a reference between prefix and tail without a matching compaction plan | Reject prefix/tail validation |
| stale_boundary | Reuse a captured source digest after same-length content changes | Reject source mismatch before applying replacement |
| source_only_digest | Hash only the prefix, position list or old message-index list | Reject because it differs from the full domain-separated source authority |

These vectors MUST be regenerated from the real Python producer and copied into
the central canonical fixture in the Contract 42 release. The values above are a
serialization design vector, not producer evidence or adoption proof.

## Contract 42 fixture allocation

The approved release adds `fixtures/compaction_source_authority.json` with a
closed top-level shape:

```text
schema_version
contract_version
status
provenance
digest_domains
vectors
invalid_vectors
```

`digest_domains.message` and `digest_domains.source` repeat the two domain
constants above. Each positive `vectors` case contains `name`, `session_id`,
`source_messages`, `message_ids`, `prefix_ids`, `tail_ids`, `source_digest` and
`semantic` (`summary` or `micro`). Each `invalid_vectors` case contains `name`,
the complete input under test and a closed rejection reason. The negative names
are the eight names in the table above.

The fixture is excluded from adoption evidence until its provenance identifies an
immutable Python revision and its values are captured from the real record and
reducer producers. `contract-allocation-only` synthetic values may diagnose the
shape but MUST NOT be presented as state, session, boundary or producer
acceptance. Only after that capture may `fixtures/SHA256SUMS`, the manifest,
contract lock and support matrix change in the normal release sequence.

## Compatibility and adoption

Contract 42 is a major boundary. It has no absent/default mode, feature level,
dual decoder, alias, in-place rewrite or compatibility shim. A 41 reader and a
42 reader each pin their release and reject a source identity produced by the
other algorithm. Hosts must avoid mixed-version claims and drains for one session
and follow the release handoff for active sessions. S1 columns do not need to
change solely for B5.

Python must replace its position-only experiment with the exact algorithms above,
update every producer and every reducer validation path, and emit a real fixture
from an immutable revision. Rust remains frozen at contract 23.0.0 / 0.21.x;
B5 MUST NOT change its frozen entry or claim verified support. The support matrix
stays `in-progress` until publication, immutable Python lock/snapshot,
cross-repository gates and recorded adoption all exist.

The public `drive` and `tick` signatures in `fixtures/public_api.json` are outside
B5. The expected-head, inbox-watermark and lease checks belong to store admission
and writer fencing. Adding new public `expected_head` or `tick` parameters would be
a separate public API change and is not approved by this proposal.

## Python handoff

Required producer changes after Contract 42 approval:

- In `src/vv_agent/session/context.py`, replace the position-only experiment with
  session-aware Message reference construction from exact normalized Message JSON.
- In `src/vv_agent/session/compaction.py`, compute prefix/tail references and the
  domain-separated source digest from the same immutable source projection.
- In `src/vv_agent/session/kernel.py`, `memory.py`, `summary_requests.py` and
  `reducer.py`, use the same helper for summary metadata, receipt reuse, fold
  validation and protection updates.
- In `src/vv_agent/session/records.py`, retain the 64-character hash schema and
  validate the new reference syntax and semantic partition.
- Add focused tests for same-length content changes, session separation, reorder,
  duplicate messages, cross-session references, missing/duplicate references,
  wrong prefix/tail partition, microcompaction and summary receipt reuse.

Python MUST NOT retain `s1-message/{index}` as authority, accept old and new
identities in one reader, rewrite persisted history, or update its lock/snapshot
until Contract 42 is published and its artifact and manifest are immutable.
