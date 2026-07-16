# Contract Change And Adoption Workflow

## 1. Classify The Change

First decide whether the implementation violates the current contract or the
shared contract itself must change.

- Fix implementation-only defects against the currently locked contract. Do
  not create a new contract version merely because one language drifted.
- Start public API, prompt, built-in tool, runtime, persistence, event, App
  Server, or wire changes in this repository.
- Treat uncertain changes as shared until real producer tests prove otherwise.

## 2. Author The Canonical Contract

Update the normative document, canonical fixture/schema, compatibility note,
and changelog together. Run:

```bash
node scripts/verify_jcs.mjs --write  # only after intentional JCS input changes
python3 scripts/contractctl.py manifest
python3 scripts/contractctl.py validate
node scripts/verify_jcs.mjs
python3 -m unittest discover -s tests
python3 scripts/contractctl.py build --output-dir dist
```

Review the semantic fixture diff. A digest change is evidence of changed bytes,
not proof that the new behavior is correct.

## 3. Publish An Immutable Version

Merge the reviewed contract, create tag `v<contract-version>`, and let the
release workflow publish the deterministic zip plus SHA-256 metadata. The
support matrix remains `pending-adoption` until both implementations pass.

## 4. Open Paired Adoption Pull Requests

Each implementation polls the latest contract release. Its adoption workflow
checks out that release into a temporary CI directory, runs the local snapshot
sync command, commits `contract.lock.json` plus the generated fixture snapshot,
and opens a `chore/vv-agent-contract-<version>` pull request.

The automated pull request may be red. Producer failures identify the exact
runtime work still needed; the bot must not fabricate implementation changes.

## 5. Implement Both Languages

Update public producers, consumers, focused behavior tests, examples, and local
mapping docs in both repositories. Do not edit vendored fixtures directly.
Run each repository's snapshot check, producer tests, and full quality gate.

## 6. Run Cross-Repository CI

Trigger `.github/workflows/cross-repository.yml` with the contract, Python, and
Rust refs under review. It verifies:

1. Both lock files point to the selected contract revision.
2. Both vendored snapshots match the canonical artifact and one another.
3. Real prompt, tool, public API, event, session, and App Server producers pass.
4. Both complete repository quality gates pass.

Record the successful run URL and exact implementation revisions in
`support-matrix.json`, then change the version state to `verified`.

## Codex Session Checklist

1. Read the local repository `AGENTS.md` and `contract.lock.json`.
2. Read this workflow and identify the owning canonical fixture.
3. Preserve dirty worktrees and note all three repository revisions.
4. Make shared observable changes here first.
5. Sync both vendored snapshots using the checked-in scripts.
6. Implement and test Python and Rust real producers.
7. Run both full gates and central cross-repository CI.
8. Leave a handoff containing all refs, checks, adaptations, and open debt.
