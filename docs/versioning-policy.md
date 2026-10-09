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

24.0.0 is major. Current wires are record/inbox schema 1, RunEvent v6, model-call
v2, task-token-usage v3, TokenUsage v1, App Server protocolVersion v2 and public API
v8. Execution is one ordered session log/inbox; records own recovery, same-turn
waits, provider acceptance, budget reservations and child delivery. Creation seed
and reserved vv_session objects define bootstrap/state boundaries. Storage layout
is not contracted. The consolidated behavior and fixture actions are in
[CHANGELOG](../CHANGELOG.md).

## Adoption states

Support-matrix schema 2 is mandatory. Top-level contract_version/status applies to
required implementations; every implementation has its own pinned contract_version.
Pending-adoption means adoption evidence is incomplete; in-progress means work
exists without all evidence; verified requires every required lock, real producer,
full gate and central cross-repository workflow. Frozen is implementation-only and
retains its own pinned version, package series and verified baseline.

Python alone is required and v24 remains pending-adoption until F3 and central CI
pass. Rust is frozen at verified 23.0.0 / 0.21.x. New Python verification cannot
claim newer Rust support. The complete frozen record must remain untouched.
Reactivation requires a new Maker decision and full current adoption; see
[change workflow](change-workflow.md#frozen-implementations).

A handoff includes exact revisions/PRs, gates, manifest digest, adaptations, open
differences and matrix status. v23 verification evidence remains in Git history
and CHANGELOG; publication alone never establishes implementation support.
