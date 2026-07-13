# Compatibility Policy

## Versioning

The contract uses semantic versioning for observable behavior:

- **Major:** removes or renames a public capability, changes an existing wire
  meaning, rejects previously valid input, or otherwise requires callers to
  migrate.
- **Minor:** adds an optional capability, field, event, operation, tool, or
  behavior without changing existing valid behavior.
- **Patch:** corrects an inconsistency, tightens evidence, or clarifies wording
  without intentionally changing the supported public capability set.

Fixture movement alone does not determine the version bump. Classify the
observable behavior represented by the fixture.

## Adoption States

- `pending-adoption`: the immutable contract version exists, but one or both
  implementation branches do not yet pin it.
- `in-progress`: both adoption changes are known, but implementation or full
  gate evidence is incomplete.
- `verified`: both repositories pin the exact same contract revision and pass
  producer, full-repository, fixture, and cross-repository checks.
- `superseded`: a later verified contract version replaces this version.

Separate repositories cannot merge atomically. During adoption, one default
branch may briefly point to a newer contract. Release workflows must therefore
accept only a version recorded as `verified` in the central support matrix.

## Allowed Language Adaptations

Language-idiomatic names, builders, async forms, and type representations are
allowed when both implementations can express the same input, observe the same
output, and enforce the same safety and lifecycle boundaries. Every adaptation
must be recorded in the parity contract or an implementation mapping document.
