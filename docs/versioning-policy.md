# Versioning And Forward-Only Policy

## One Current Contract

The repository is forward-only. `HEAD` defines exactly one current canonical
shape for every public API, model-visible prompt, built-in tool, runtime record,
event, session, checkpoint, App Server message, and wire payload.

When a shape changes, the same change must:

1. update the canonical documentation and fixture;
2. update both real implementations and their producer tests;
3. update every current caller and evaluation adapter;
4. delete the replaced reader, writer, alias, shim, migration, fixture, test,
   and documentation path.

Git history is the only archive. Runtime packages and the contract release do
not carry historical records or conversion logic.

## Strict Version Boundaries

Schema and protocol versions are validation boundaries, not compatibility
dispatchers. A current reader must require the current discriminator and reject
missing, stale, unknown, malformed, or future values. It must not retry another
decoder or fill fields that belonged to an older shape.

Canonical objects are closed by default. Unknown fields are rejected unless a
specific contract location defines a typed extension map. An extension map does
not permit callers to override canonical fields or behavior.

## Contract Releases

The contract uses semantic version numbers to identify immutable releases and
to communicate change size:

- **Major:** removes, renames, or changes public behavior or a wire shape.
- **Minor:** adds a public capability without changing an existing shape.
- **Patch:** corrects implementation evidence or documentation without changing
  observable behavior.

These labels do not promise that a runtime reads records from older releases.
Each implementation pins one exact contract version and revision. New releases
replace the supported contract after paired adoption; applications that need an
older runtime use the corresponding Git tag and package release.

## Adoption States

- `pending-adoption`: the immutable contract release exists, but one or both
  implementations do not yet pin it.
- `in-progress`: paired implementation work exists, but complete evidence is
  not yet available.
- `verified`: both repositories pin the same contract revision and pass real
  producer, full repository, fixture, and cross-repository checks.

Separate repositories cannot merge atomically. Until both implementations and
the central cross-repository workflow pass, the current change remains
`pending-adoption` or `in-progress` and must not be reported as shared support.

## Completion Evidence

A forward-only contract change is complete only when:

- both locks pin the same exact contract release and revision;
- both vendored snapshots match the canonical artifact;
- both real writer and strict reader tests pass;
- stale, missing, malformed, and unknown versions are rejected in both
  languages;
- repository-wide searches find no old reader, alias, migration, fixture, or
  active documentation reference;
- the central cross-repository workflow records both exact implementation
  revisions.
