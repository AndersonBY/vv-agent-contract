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
introduced. Results/resources and structured interactions belong to this same release.
Local implementation does not replace the required immutable release and central adoption gates.

32.1.0 combines the task-scoped artifact search capability with unified completion
projection, retained-result provenance and recovery notices. This is a minor
capability release using the existing result extension maps, App Server v5,
record schema 1, inbox schema 3 and SQL schema 3; it introduces no store boundary.
The artifact work is a single release rather than a mutation of published 32.0.0.

32.1.1 corrects the released bounded-result fixture's missing provenance entries
and gives the whole file one generator. This is an evidence-only patch:
32.1.0 behavior, normative rules and schema versions remain unchanged.
Implementations must re-sync their pinned snapshot.

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
`support-matrix.json` owns the current adoption status. The current contract is
35.0.0; Python lock/snapshot synchronization and central adoption are pending.
Contract 32.1.1 was published and adopted on 2026-11-03 (PRs #46 and #47).
Rust is frozen at verified 23.0.0 / 0.21.x.
New Python verification cannot claim newer Rust support. The complete frozen
record must remain untouched.
Reactivation requires a new Maker decision and full current adoption; see
[change workflow](change-workflow.md#frozen-implementations).

A handoff includes exact revisions/PRs, gates, manifest digest, adaptations, open
differences and matrix status. v23 verification evidence remains in Git history
and CHANGELOG; publication alone never establishes implementation support.

## 33.0.0 artifact reread changes

33.0.0 is a major release because artifact task-scope encoding, search and terminal
failure behavior replace existing behavior. The new read_file parameters use its existing
closed tool argument object; recovery uses existing typed artifacts/cursors and
metadata maps. There is no record, inbox, SQL or App Server schema bump. Historical
records remain decodable; old ambiguous lossy artifact scopes require a host
transition decision and are not silently authorized.

An active turn with the previous frozen read_file tool schema does not match the
new runtime. Its existing definition guard rejects continuation before dispatch.
Hosts finish those turns with the old runtime or create new sessions from their
own history/state; this does not require rewriting old record bytes.

## 34.0.0 search budget correction

The 250 ms cumulative budget in 33.0.0 was a design error: ordinary large scans
could stop before a late match. Replacing it with a 10 s request thread CPU limit
and a separate 250 ms limit per engine invocation changes existing observable
behavior. Under this policy it is major, rather than a minor capability addition
or an evidence-only patch. No tool schema, frozen definition, record, inbox, SQL,
event or App Server shape changes; existing 33.0.0 turns need no new guard or
historical decoder branch for this handler correction.

## 35.0.0 definitive model rejection

Classifying a received provider rejection as confirmed failure replaces the old
Unknown/retry behavior and introduces a terminal reason. Under this policy that
is a major behavior release. The rejection descriptor uses the existing model
result and event metadata maps; terminal reasons are already text. Record 1,
inbox 3, SQL 3, RunEvent v6, App Server v5 and frozen definitions do not change.
There is no store boundary or old-record decoder. Existing Unknown receipts keep
their original uncertainty; this release does not settle historical calls.
