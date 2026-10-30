# Versioning and forward-only policy

HEAD defines one current shape for public APIs, prompts, tools, session records,
inbox values, events and wire protocols. A changed shape updates canonical docs,
fixtures and active consumers together and deletes replaced readers, writers,
aliases, shims, migrations, tests and documentation. Git is the archive.

Discriminators are strict validation boundaries. Readers require current versions
and reject missing, stale, unknown, malformed and future values without historical
dispatch or defaulting. Objects are closed except explicitly typed extension maps;
opaque content cannot override control fields. Hashes require exactly 64 lowercase
hexadecimal characters without trailing newline. Logical bytes use RFC8785 and
I-JSON as specified in [session kernel](session-kernel.md).

## Releases and current version

Major releases remove/rename/change public behavior or wire shape. Minor releases
add public capability without changing an existing shape. Patch releases correct
evidence/docs without observable change. These labels do not promise old-wire
reading. Each implementation pins an exact version/revision/artifact and manifest;
consumers needing an older behavior pin its release.

30.0.0 replaces the closed model/list response and selects App Server v4. New
context/read and compact/start methods alone would be minor additions. There is
no record, inbox or SQL store boundary.

29.1.0 adds host-requested compaction and summary-dependent child admission through
existing metadata extension maps. Record, inbox, event and App Server versions stay unchanged.

29.0.0 is major: endpoint routing no longer participates in identity checks,
and missing endpoints have a definitive undispatched result. Existing record
and inbox versions remain readable; there is no SQL store boundary.

28.0.0 is major: App Server v3 replaces submission, replay, control and status
wire shapes and adds public API inventory v12; it introduces no record, inbox or SQL store boundary.

27.0.0 introduced: closed model_selection inbox kind and durable selection log semantics.
Inbox schema 3 rejects all earlier versions; record schema 1 embeds current inbox values
and resolved selection binding. Public API inventory v11 includes the selection resolver.
That release used RunEvent v6, model-call v2,
task-token-usage v3, TokenUsage v1 and App Server protocolVersion v2.
Execution is one ordered session log/inbox; records own recovery, same-turn
waits, provider acceptance, budget reservations and child delivery. Creation seed
and reserved vv_session objects define bootstrap/state boundaries. Storage layout
is not contracted. The consolidated behavior and fixture actions are in
[CHANGELOG](../CHANGELOG.md).

30.1.0 adds the independent thread/fork method and optional lineage on fork context
reads. Existing thread metadata carries lineage/workspace; no existing response
is replaced. This is a minor release, with no store or protocol boundary.

32.0.0 selects App Server v5 and public API inventory v15. Named tool provider
registration and strict result acceptance share the existing record schema 1,
inbox schema 3, SQLite user_version 3 and RunEvent v6. No store boundary is
introduced. Results/resources and structured interactions belong to the same
release and remain pending.

## Adoption states

Support-matrix schema 2 is mandatory. Top-level contract_version/status applies to
required implementations; every implementation has its own pinned contract_version.
Pending-adoption means adoption evidence is incomplete; in-progress means work
exists without all evidence; verified requires every required lock, real producer,
full gate and central cross-repository workflow. Frozen is implementation-only and
retains its own pinned version, package series and verified baseline.

31.0.0 changes the existing factory lease lifetime and requires renewal-safe
captured-prefix reads. It is a major behavior release without a record, inbox,
SQL, public API inventory or wire version change.

Python alone is required. Contract 31.0.0 was verified for Python 0.30.0;
`support-matrix.json` owns the current adoption status. Contract 32.0.0 is in
progress and is not yet released or verified. Rust is frozen at verified 23.0.0 / 0.21.x.
New Python verification cannot claim newer Rust support. The complete frozen
record must remain untouched.
Reactivation requires a new Maker decision and full current adoption; see
[change workflow](change-workflow.md#frozen-implementations).

A handoff includes exact revisions/PRs, gates, manifest digest, adaptations, open
differences and matrix status. v23 verification evidence remains in Git history
and CHANGELOG; publication alone never establishes implementation support.
