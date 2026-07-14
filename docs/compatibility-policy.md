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

## 0.2 Token Usage Compatibility

Contract `0.2.0` adds `usage_source` and `cache_usage` without removing or
changing the existing numeric token fields. A `0.1.x` payload therefore
decodes as `accounting_missing` for the new observation while retaining its
legacy values. A `0.2.x` decoder must preserve `null` cache readings and must
not derive availability from legacy zero values.

Writers continue to emit `cached_tokens` and `cache_creation_tokens` during
the `0.x` compatibility period. Readers that require a reliable cache hit rate
must use `cache_usage.status` and the nullable typed readings; the legacy
projection alone cannot distinguish zero from unavailable accounting.

## Allowed Language Adaptations

Language-idiomatic names, builders, async forms, and type representations are
allowed when both implementations can express the same input, observe the same
output, and enforce the same safety and lifecycle boundaries. Every adaptation
must be recorded in the parity contract or an implementation mapping document.
