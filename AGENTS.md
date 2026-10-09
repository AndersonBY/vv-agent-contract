# AGENTS.md

This repository is the canonical language-neutral contract for sibling Python
`vv-agent` and Rust `vv-agent-rs` implementations. Keep this file as a short
mandatory routing map; durable detail belongs in `docs/`.

## Required Reading

- Read `contract.json` and `support-matrix.json` before changing a contract.
- Read `docs/parity-contract.md` for normative observable behavior.
- Read `docs/session-kernel.md` for records, inbox and execution semantics;
  `docs/session-consumers.md` owns projections; App Server wire is in the kernel doc.
- Follow `docs/change-workflow.md` for contract authoring and adoption.
- Read `docs/versioning-policy.md` before changing any schema, protocol, or
  public behavior.

## Contract Rules

- Change canonical fixtures here first. Never treat vendored copies in an
  implementation repository as the source of truth.
- Keep the contract language-neutral. Python and Rust symbol spelling belongs
  in explicit adaptation mappings, not in divergent behavior.
- A declared field or capability must be consumed by each real producer.
  Schema-only parity is insufficient.
- Rebuild `fixtures/SHA256SUMS` with `contractctl.py manifest` after an
  intentional fixture change; do not edit digests by hand.
- Publishing a version does not mark it adopted. Update `support-matrix.json`
  to `verified` only after all required implementation revisions and the central
  cross-repository workflow pass.
- `support-matrix.json` schema 2 lists required implementations explicitly.
  Python is required; Rust is frozen at contract 23.0.0 / 0.21.x for maintenance
  only. Preserve its own version and verified baseline when Python adopts a
  newer contract. Reactivation requires a new Maker decision and full adoption
  of the then-current contract; see `docs/change-workflow.md`.
- Preserve existing implementation worktrees. Contract synchronization is not
  permission to reset or overwrite unrelated changes.
- Keep `HEAD` forward-only. It contains exactly one current canonical shape for
  each public API, prompt, tool, runtime record, event, session,
  and wire protocol. Delete replaced readers, aliases, shims, migrations,
  fixtures, and documentation in the same change; Git is the history.
- Backward compatibility is not a contract goal. Prefer a breaking replacement
  when it produces a clearer current design; update active consumers together,
  while consumers that require old behavior must pin an old release.
- Keep schema and protocol discriminators only as strict validation boundaries.
  Current readers must reject missing, stale, unknown, and malformed versions;
  they must not dispatch to historical decoders.
- Unknown fields are rejected unless the canonical contract explicitly defines
  an extension map at that location.

## Required Commands

```bash
python3 scripts/contractctl.py validate
node scripts/verify_jcs.mjs
python3 -m unittest discover -s tests
python3 scripts/contractctl.py build --output-dir dist
```

## Completion

Every handoff must record the contract version/revision, required implementation
revisions or PRs and frozen baseline revisions, focused and full gate results,
fixture-manifest digest,
allowed adaptations, open differences, and support-matrix status.
