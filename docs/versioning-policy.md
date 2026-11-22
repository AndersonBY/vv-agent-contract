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

### Feature levels inside one major

Within one storage major, a change MAY add an optional field, enum value or record
kind only when it is assigned a `feature_level` and the canonical fixture states
its absent/default behavior. A current reader MUST read unchanged old data without
conversion. A worker MUST NOT decode, claim or write a session whose required level
is above its advertised support set. New fields remain closed to old readers, so an
unknown field still rejects; a worker only accepts a high-level shape after
publishing that level. The default of every optional addition reproduces behavior
from before the addition. Changing the meaning, nullability, identity, digest input
or validation of an existing field still requires a new major. Allocating
`feature_level` in a canonical shape does not claim an implementation has adopted
it.

An envelope's `feature_level` is a format requirement; a nested
`SessionRequirements.level` is routing semantics and cannot lower it. A session's
format floor is the monotonic maximum of its persisted record and every currently
stored, unconsumed inbox envelope level, including future-unavailable or otherwise
non-ready items. A consumed item remains represented by its persisted
`input_applied` record; an unconsumed item remains part of the floor until consumed.
A level-2 container therefore remains level 2 even when its nested requirements
level is 1. The existing session routing-cache `level` records the maximum of this
format floor and applicable routing requirement levels in the same single column;
no second floor field, decoder or implementation profile is added.

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
`support-matrix.json` owns the current adoption status. Contract 41.0.1 refreshes
the S1 producer evidence for the 41.0.0 worker-routing and execution allocations.
Python adoption requires an exact release pin and the central producer and full
implementation gates.
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

## 36.0.0 context and quota classification correction

Time-window/quota errors previously matched generic context-size wording and
started compaction. They now reject with the existing retry/backoff policy;
explicit window-size phrases also gain recovery outside 429. This changes
published observable classifications. Under this policy it is major, even
though it corrects a specification defect: a patch may change only evidence/docs
without observable change. Record 1, inbox 3, SQL 3, RunEvent v6, App Server v5
and frozen definitions stay unchanged. There is no store boundary.

## 37.0.0 input protection and completion evidence

Changing summary planning and replay for declared sessions changes observable
behavior and therefore requires a major release. The optional closed seed
declaration gates old runtimes without changing the record/inbox/SQL versions.
Previously stored sessions without it retain their frozen compaction policy.

Completion evidence and the independent response_rejection creation declaration
shipped in the same 37.0.0 major; they do not require another version
bump or record/inbox/SQL change. Only Python adoption is required.

## 38.0.0 yieldable waits

The new optional closed record fields change an existing shape, and declared
waits change scheduling and completion semantics. This requires a major release,
even though undeclared waits keep their scheduling and declaration bytes. Strict old readers reject the
new fields without a global record/inbox discriminator bump. SQL layouts are
unchanged; hosts route sessions containing declarations to Python 0.35.0 or newer.
See [yieldable waits](yieldable-waits.md). Rust remains unsupported and frozen.

The 38.0.0 closed-shape extension also covers the optional literal-true
`provider_evidence.payload.yield_on_steer`. Hosts preserve and authenticate the
original acceptance declaration, including during recovery before park commit.
Older readers reject declared acceptance inbox values and records embedding
them, even before any park is saved. No discriminator or SQL layout change is
needed. Kernel long-body archive identities now include content SHA-256;
existing stored references remain authoritative and are never rewritten.

38.0.0 also fixes L1 lease lock ordering. Local App Server, Interactive and
Runner accept declarations but do not yield. Shared raw connections require
exclusive host use; concurrent native transactions are unsupported and detection
is not promised. L2–L5 remain unfixed. No admission/hook signature changes ship.

## 39.0.0 concise session-schema diagnostics

Replacing externally visible schema-error text with `invalid session schema`
changes existing public behavior, including text that can reach App Server
clients. This is a major release, not an evidence-only patch. Concrete
jsonschema exception causes and pretty-print formatting are unpromised
implementation details; preserving them does not justify a compatibility layer.

Acceptance/rejection, explicit semantic/parser/duplicate messages, canonical
bytes and IDs, fixed provider/model-selection codes and all execution semantics
are preserved. Record 1, inbox 3, SQL layouts, RunEvent v6, App Server v5, public
API inventory and frozen definitions do not change. There is no data/store
boundary, migration or host drain. Python P1 may remain in package series
0.36.x; contract and implementation package major numbers are independent.
Rust remains frozen at 23.0.0 / 0.21.x with its existing verified baseline.

39.0.0 includes a real Python diagnostic capture and its regenerated fixture
manifest. Required implementation full gates, immutable publication and central
adoption remain outstanding; this is not a verified 39.0.0 release. See [release notes](release-39.0.0.md).

## 40.0.0 trusted storage S1 allocation

This major replaces the session storage discriminators with `"S1"` and
`feature_level=1`. It changes the record and inbox envelopes, so record 1, inbox
3 and every earlier wire reject without a decoder. SQL table layout, PostgreSQL
RLS and Python symbol spelling remain outside the contract.

The allocation adds Principal/actor, admission and input proof slots, frozen
session requirements, policy/environment/usage/tokenizer binding slots, and closed
ContentRef labels. Logical records contain reference-form C fields; record chaining
is allocated separately as a storage envelope excluded from record identity.
Unknown fields still reject. Null signed-proof slots mean explicit unsigned local
mode, not silent fallback in signed deployment.

No Python S1 producer, storage implementation or adoption is claimed. The frozen
Rust entry remains 23.0.0 / 0.21.x. Worker support filtering, full policy/label
propagation, execution-environment adoption, remaining producer/storage work and
SQLite/PostgreSQL implementation remain later work. This repository contains
synthetic allocation fixtures, not a Python S1 producer capture or adoption claim.
See [release notes](release-40.0.0.md).

## 41.0.0 W4 worker routing and W3 execution allocation

This is a major behavior replacement, not an optional compatibility layer. Storage
remains S1 with the existing set of columns and state machines: there is no DDL
replacement, second drain, historical decoder, alias or shim. Feature level 1 keeps
its current bytes and defaults. Level 2 adds a required typed
`session_created.bootstrap` and required `requirements` on `user`, `follow_up` and
`model_selection` inbox items. Those fields reject at level 1, and level 2 rejects
for kinds outside that closed allocation.

Level 3 is limited to existing `turn_started`, `op_planned`, `op_prepared` and
`provider_evidence` shapes. It adds the frozen environment capability binding,
stable execution identity, proposal/final command digests, and an encrypted
authenticated provider lookup result
defined in the [session kernel](session-kernel.md#w3-execution-identity-and-lookup).
Level-1 and level-2 bytes remain unchanged. A level-2 worker or reader rejects a
level-3 body before decode; a level-3 thin reader may decode without execution
supports but cannot claim or dispatch. The synthetic W3 allocation does not add a
record kind, storage layout, registry, proxy, ledger or parallel outcome enum.

The existing `sk_session` routing group is recomputed at creation, turn start,
input publication and turn end in the same transaction. Active turns use the frozen
turn requirements plus applied/pending model-selection tags; idle turns use the
complete queued-plus-ready-pending admission/start order, otherwise bootstrap or
existing level-1 defaults.
No active/next row, source sequence/digest copy, profile, registry or new queue is
introduced. Workers are still filtered by the complete trusted supports catalog;
the cache first records the trusted static conservative bound from immutable typed
input and later the exact tags frozen by `turn_started`. Actual requirements must be
a subset of that bound, use the same handler and not lower the level; overflow keeps
the immutable bytes unchanged and exposes an unsatisfiable-bound configuration
error without dispatch, a fabricated terminal or automatic retry. The producer has
already queued the input before compilation, and existing controls cannot safely
discard it; correcting the declaration requires a new session. No cancellation,
supersession or replacement-input protocol is introduced. The cache may be a legal
time projection after the last authenticated boundary of the complete captured
proof source. Before epoch or lease grant, the locked claim validates that existing
projection, then refreshes its clock and recomputes it. Signed capture time cannot
precede `max(checkpoint.signed_ms, contributing input admission_signed_ms/received_ms)`;
unsigned `created_ms` is not a lower-bound proof. The explicit weak no-signature mode
trusts durable SQL metadata and ordering,
but applies the same completeness, structural projection and future-availability
rules. A source cut before bootstrap/source publication is incomplete. Any
understatement or invalid pre-refresh projection rejects before epoch; no new
persisted time, source or active/next field is introduced.
Tool identities hash the complete registry-returned OpenAI function object rather
than its parameters alone. Model identities hash each atomic resolved four-field
binding and exclude endpoint lists; internal bindings are decomposed and reused
model tags are deduplicated.
Worker supports grant execution eligibility only. Authorized S1/level-compatible
gateway, thin-client and projection readers do not need executor/model/tool supports;
their existing tenant/Principal/RLS authorization and read-dependency gates remain
unchanged. No reader registry or second permission protocol is introduced.

The after-cycle hook accepts a bounded valid host-defined stop code for diagnosis,
but the persisted S1 `stop.code` is closed to `host.policy_stop`, `host_stop`,
`hook_stop` and `stopped`. A custom code is recorded as `host_stop`; the original
`"code: message"` remains in the encrypted `error` C slot. This tightens an
existing allocation without a new storage discriminator, migration or v42 release.
No Rust support is claimed for the current boundary.

`fixtures/worker_compatibility.json` and `fixtures/execution_worker_w3.json` are
contract-allocation-only. They have no producer capture and are excluded from
adoption evidence. Python producer capture and all implementation gates remain
pending. Rust remains frozen at 23.0.0 / 0.21.x. See the
[41.0.0 release allocation](release-41.0.0.md); Contract 41 is unreleased.

B5 compaction source authority is deferred from 41.0.0. It would replace the
preimage and validation of existing `context_compacted.source_digest` and
`prefix_ids`/`tail_ids`; changing an existing field's digest input or validation
requires a new major under this policy. The proposed replacement is specified for
Contract 42 in [the B5 source authority proposal](contract-42-b5-source-authority.md).
It is not a feature level, optional 41 shape or current producer requirement.
