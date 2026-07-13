# AGENTS.md

This repository is the canonical language-neutral contract for sibling Python
`vv-agent` and Rust `vv-agent-rs` implementations. Keep this file as a short
mandatory routing map; durable detail belongs in `docs/`.

## Required Reading

- Read `contract.json` and `support-matrix.json` before changing a contract.
- Read `docs/parity-contract.md` for normative observable behavior.
- Follow `docs/change-workflow.md` for contract authoring and adoption.
- Use `docs/compatibility-policy.md` before choosing a version bump.

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
  to `verified` only after both implementation revisions and the central
  cross-repository workflow pass.
- Preserve existing implementation worktrees. Contract synchronization is not
  permission to reset or overwrite unrelated changes.

## Required Commands

```bash
python3 scripts/contractctl.py validate
python3 -m unittest discover -s tests
python3 scripts/contractctl.py build --output-dir dist
```

## Completion

Every handoff must record the contract version/revision, Python and Rust
revisions or PRs, focused and full gate results, fixture-manifest digest,
allowed adaptations, open differences, and support-matrix status.
