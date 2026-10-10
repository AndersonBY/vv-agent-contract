# Contract authoring and adoption

Shared observable changes start with canonical fixtures and normative documents
here. Implementation defects are fixed against their pinned contract. Inspect
real producers and preserve unrelated implementation worktrees. One current shape
replaces all superseded active readers, aliases, fixtures and documentation; Git
is history. See [version policy](versioning-policy.md).

## Canonical authoring

Update normative behavior, fixtures/schemas and release notes together. Fixtures
must come from real producers with deterministic doubles and independent byte,
identity and transition assertions. Never edit vendored snapshots or generator
facts. If generator output is defective, stop that file and report the defect.
The current record/inbox ownership is [session kernel](session-kernel.md), with
[consumers](session-consumers.md) and [App Server](session-kernel.md#app-server) projections.
Storage layouts and constructor/method signature catalogs are outside contract.

Run independent Node JCS checks, rebuild SHA256SUMS with contractctl manifest,
validate, repository unittest and two byte-identical builds. Review semantic diffs;
a digest proves bytes, not behavior. Canonical producer gates cover all 14 record
kinds, eight inbox kinds, seven boundaries and four handles, codec negatives,
admission/fencing, failure cuts, cursors, children, compaction and JSON-RPC exports.

```bash
node scripts/verify_jcs.mjs
python3 scripts/contractctl.py manifest
python3 scripts/contractctl.py validate
python3 -m unittest discover -s tests
python3 scripts/contractctl.py build --output-dir dist-a
python3 scripts/contractctl.py build --output-dir dist-b
diff -r dist-a dist-b
```

## Publication and required adoption

Reviewed releases are immutable v<version> tags with deterministic artifact and
SHA-256 metadata. Publication remains pending-adoption. Python is the only required
implementation; it must pin the immutable current revision/artifact, synchronize
its snapshot with checked-in tooling and update the actual default public producers.
Adapt existing producer tests instead of retaining parallel fixture branches.
Retire replaced execution loops, selectors, wires and writable history surfaces.

Python's focused producer suite and full pytest/ruff/ty gates must pass. Applicable
SQLite memory/file and real PostgreSQL transaction, concurrency and integrity
semantics must pass; process-kill evidence applies to durable stores. Real broker
integration remains part of the central gate. Optional live providers do not
replace deterministic failure-cut evidence.

Cross-repository CI accepts contract/Python review refs. It validates canonical
fixtures, independent JCS, deterministic bundles, exact lock/artifact/manifest
selection and real Python producers plus full gates with PostgreSQL.
Do not weaken the workflow to accept pending implementation differences.
Recording adoption requires contract and Python main refs. record_adoption.py
records the exact Python revision/run URL and preserves the entire frozen Rust
entry. Only then may the support matrix become verified.

## Frozen implementations

Support-matrix schema 2 explicitly lists required implementations and per-entry
contract_version. Schema 1 rejects. Rust remains frozen at 23.0.0 / 0.21.x, baseline
00f4240786f1adea1dc0c4730da8ddd06a5ab8ac. Its lock/fixtures do not follow the current
contract and it does not participate in active central CI. Security, data integrity, v23 correctness
and nonbehavioral dependency/build upkeep are the maintenance scope. Reactivation
requires a new Maker decision, full adoption of the then-current contract, all
producer/full/central gates and restoring required status and CI/adoption tooling.

## Handoff

Record contract version/revision, required implementation revisions or PRs, frozen
baseline, focused/full gates, fixture manifest digest, allowed adaptations, open
differences and support-matrix status. Publishing alone is never adoption proof.
