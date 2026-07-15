# vv-agent-contract

`vv-agent-contract` is the language-neutral source of truth shared by the
Python [`vv-agent`](https://github.com/AndersonBY/vv-agent) and Rust
[`vv-agent-rs`](https://github.com/AndersonBY/vv-agent-rs) implementations.

The repository owns observable SDK semantics, canonical fixtures, wire
schemas, compatibility rules, and adoption evidence. It does not contain either
runtime implementation.

## How Implementations Consume It

Each implementation pins an exact contract version, Git revision, release
artifact digest, and fixture-manifest digest in `contract.lock.json`. Canonical
fixtures are committed into the implementation repository as a generated
vendored snapshot so local tests remain deterministic and offline.

Vendored fixtures are never edited directly. A contract change begins here,
then each implementation runs its snapshot sync command and updates its real
producers until conformance tests pass.

## Local Validation

```bash
python3 scripts/contractctl.py validate
python3 -m unittest discover -s tests
python3 scripts/contractctl.py build --output-dir dist
```

## Adoption State

`support-matrix.json` records whether the current contract version has passed
both implementation gates. Publishing a contract version and adopting it are
separate operations. A version is not cross-language verified until both
implementation revisions and the central cross-repository run are recorded.

See `docs/change-workflow.md` for the complete workflow.
The optional resource budget semantics are defined in `docs/run-budgets.md`.
