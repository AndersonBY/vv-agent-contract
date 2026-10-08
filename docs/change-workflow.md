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

Update the normative document, canonical fixture/schema, and versioning note
together. Replace the current shape in place and remove every replaced
reader, alias, shim, migration, fixture, and documentation reference in the
same change across the contract and required implementations. Run:

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
support matrix remains `pending-adoption` until all required implementations pass.

## 4. Open Required Implementation Adoption Pull Requests

Each required implementation polls the latest contract release. Its adoption workflow
checks out that release into a temporary CI directory, runs the local snapshot
sync command, commits `contract.lock.json` plus the generated fixture snapshot,
and opens a `chore/vv-agent-contract-<version>` pull request.

The automated pull request may be red. Producer failures identify the exact
runtime work still needed; the bot must not fabricate implementation changes.

## 5. Implement Required Implementations

Update public producers, consumers, focused behavior tests, examples, and local
mapping docs in each required repository. Do not edit vendored fixtures directly.
Run each repository's snapshot check, producer tests, and full quality gate.

## 6. Run Cross-Repository CI

Trigger `.github/workflows/cross-repository.yml` with the contract and Python
refs under review. Python is currently the only required implementation. It verifies:

1. Canonical fixtures, JCS vectors and deterministic artifact construction.
2. The Python lock selects the release revision and matches its artifact and
   fixture digests; the canonical checkout contains that revision.
3. Real prompt, tool, public API, event, session and App Server producers pass.
4. The Python full gate passes (`pytest`, `ruff`, `ty`), with a real Redis service.
   PostgreSQL is provisioned and probed now; kernel tests can consume
   `VV_AGENT_TEST_POSTGRES_DSN` when adopted.

Record the successful run URL and required implementation revisions in
`support-matrix.json`, then change the version state to `verified`. A recording
run must use `main` for the contract and Python refs; feature branches may be
used only for non-recording review runs. `record_adoption.py` updates Python
and preserves the complete frozen Rust record.

## Frozen Implementations

Schema 2 lists `required_implementations` explicitly and gives every implementation
its own `contract_version`. Schema 1 is rejected. Only required implementations
must be verified for the current contract to be verified. Release tooling must
use the schema 2 reader from `clients/contract_snapshot.py`; refreshing the
fixture snapshot alone does not update a vendored client script.

Rust is frozen at contract 23.0.0 / package series 0.21.x, with its verified
baseline revision retained. Its lock and fixtures stay pinned to v23; it does
not follow later releases and does not participate in the active central CI.
The global contract version or verification run never establishes newer Rust
support. v23 remains the current verified release; this process change does not
bump the contract version or alter fixtures or prior verification evidence.

Maintenance permits security, data integrity, v23 correctness fixes, and
non-behavioral dependency/build upkeep. No new kernel, wire or public behavior.
See the [approved plan §3 and reviewer decision](../../../docs/vv-agent-session-kernel-replacement-plan-2026-10.md).
Reactivation requires a new Maker decision and full adoption of the then-current
contract: update the lock, fixtures, real producers and tests, pass full gates
and central CI, and only then record verified adoption. Restore Rust as a
required implementation and its central CI/adoption tooling as part of that work.

## Codex Session Checklist

1. Read the local repository `AGENTS.md` and `contract.lock.json`.
2. Read this workflow and identify the owning canonical fixture.
3. Preserve dirty worktrees and record required revisions and frozen baselines.
4. Make shared observable changes here first.
5. Sync required implementations' vendored snapshots using checked-in scripts.
6. Implement and test each required implementation's real producers.
7. Run required full gates and central cross-repository CI.
8. Leave a handoff containing all refs, checks, adaptations, and open debt.
9. Confirm active repositories contain no replaced decoder or fixture. Frozen
   implementations keep the canonical shape of their own pinned release.
