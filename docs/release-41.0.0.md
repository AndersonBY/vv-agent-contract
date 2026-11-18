# Contract 41.0.0

Status: unreleased contract 41 producer allocation. Contract 41 has not been
released. Python remains the only required implementation and is still
`in-progress` with `verified_revision: null`. Rust remains frozen at Contract
23.0.0 / package series 0.21.x at verified revision
`00f4240786f1adea1dc0c4730da8ddd06a5ab8ac`.

## Public boundary

Storage remains S1. Existing level-1 and level-2 Wire shapes, defaults and
behavior remain unchanged. Level 3 is an unpublished allocation for the W3
execution-environment boundary and does not create a Contract 42 surface.

Level 3 is limited to three existing shapes:

- `turn_started` carries a non-null `ExecutionEnvironmentBinding` with
  environment ID, generation, isolation/network, enforcement and persistence
  flags, sorted environment capability names, capability digest, nullable policy
  reference digests and encrypted operational-policy content.
- `op_planned` tool operations carry the stable `ExecutionIdentity` and opaque
  `command_digest`. The stable execution ID hashes the exact RFC 8785 object
  `{domain:"vv-agent/S1/execution-identity",framing_version:1,operation_key,
  tenant_id,environment_id}`. Attempt, request digest, dispatch ID and clocks are
  excluded.
- `provider_evidence` carries an authenticated provider lookup result. Its four
  statuses reuse the existing public outcomes: `not_started -> null`,
  `running -> Accepted`, `exited -> Definitive`, `unknown -> Unknown`.

No record kind, inbox kind, SQL table, execution ledger, registry, HTTP proxy,
policy engine, outcome enum, compatibility decoder or release artifact is added.

## Command and recovery semantics

The command digest is HMAC-SHA-256 under the session data key. Its preimage is
RFC 8785 JCS of the exact object
`{domain:"vv-agent/S1/command-digest",framing_version:1,purpose:"stable-command",
tenant_id,session_id,command_spec,environment,operational_policy}`. The
environment is `EnvironmentCapabilities.to_dict()` with nullable capability
digest; operational policy contains exactly the two policy digests. The session
key is never sent to the remote agent.

The lookup binding carries tenant, session, operation, attempt, request digest,
idempotency key, execution ID, command digest, environment ID, generation and
provider ID. An authenticated `not_started` response logs evidence and permits
at most one new attempt using the same idempotency key and execution ID.
`running` reuses the original execution; `exited` reconciles its definitive
result; `unknown` never permits a start retry. Transport or registry inability to
prove state maps to `unknown`. Binding or authorization mismatch rejects without
effects, and malformed results retain `provider_result_invalid` semantics.

## Allocation and adoption

`fixtures/execution_worker_w3.json` is `contract-allocation-only` with
`producer_capture=false` and `adoption_evidence=false`. It supplies deterministic
identity, command-HMAC, four-status lookup, tamper/environment denial and bounded
restart vectors. `fixtures/worker_compatibility.json` records that a level-2
worker cannot claim a level-3 execution record while a level-3 thin reader can
decode without execution supports.

Python producer consumption, environment/provider adapters, durable W3 execution
storage, remote process supervision, SQLite/PostgreSQL integration, cross-repository
adoption and all implementation gates remain pending. These fixtures are not
producer evidence and do not establish a release URL.

## Verification

The allocation requires `python3 scripts/contractctl.py validate`, the independent
Node JCS verifier, the complete repository unittest suite, generated-schema
byte-stability, a manifest rebuilt only with
`python3 scripts/contractctl.py manifest`, whitespace checks, and two
byte-identical builds written to temporary directories outside the repository.

