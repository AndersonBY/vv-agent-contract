# Contract 41.0.0

Status: unreleased contract 41 producer allocation. Contract 41 has not been
released. Python remains the only required implementation and is still
`in-progress` with `verified_revision: null`. Rust remains frozen at Contract
23.0.0 / package series 0.21.x at verified revision
`00f4240786f1adea1dc0c4730da8ddd06a5ab8ac`.

## Public boundary

Storage remains S1, and the record/inbox discriminators and level-1 field shapes
stay in the same storage major without a migration or compatibility reader. The
candidate changes level-1 producer bytes: the refreshed capture moves ordinary
`ContentLabels.source` to the S1 default `[]` from the earlier local capture's
`["internal"]`, changing affected ContentRef MACs and dependent digests. The
principal-attributes case remains the explicit `["internal"]` case. Level 2
retains its allocated routing fields. Level 3 is an unpublished allocation for the
W3 execution-environment boundary and does not create a Contract 42 surface.

The public direct `drive` operation also accepts an optional keyword-only
`expected_head`, consisting of an independently retained final sequence and
chain digest. When supplied, the initial fold MUST verify it before model or tool
dispatch, and every append MUST also verify it before durable effects. A
successful commit advances the in-call anchor to the verified new head. A
mismatch rejects without changing the session. Omitting it preserves existing
behavior. This is a direct `drive` capability only; it does not add or claim a
wrapper API, storage or wire version, or the Contract 42 B5 source-authority
change.

Level 3 is limited to four existing shapes:

- `turn_started` carries a non-null `ExecutionEnvironmentBinding` with
  environment ID, generation, isolation/network, enforcement and persistence
  flags, sorted environment capability names, capability digest, nullable policy
  reference digests and encrypted operational-policy content.
- `op_planned` tool operations carry the stable `ExecutionIdentity` and proposal
  `command_digest`. The stable execution ID hashes the exact RFC 8785 object
  `{domain:"vv-agent/S1/execution-identity",framing_version:1,operation_key,
  tenant_id,environment_id}`. Attempt, request digest, dispatch ID and clocks are
  excluded.
- `op_prepared` tool operations carry the final request digest and session-HMAC
  command digest after `BeforeTool`, while inheriting execution identity and
  stable operation/provider binding from `op_planned`.
- `provider_evidence` carries one encrypted `provider_lookup:ContentRef`, whose
  typed content is the authenticated lookup result. Its four logical statuses
  reuse the existing public outcomes: `not_started -> null`, `running ->
  Accepted`, `exited -> Definitive`, `unknown -> Unknown`.

No record kind, inbox kind, SQL table, execution ledger, registry, HTTP proxy,
policy engine, outcome enum, compatibility decoder or release artifact is added.

## Command and recovery semantics

The proposal and final command digest use HMAC-SHA-256 under the session data key. A
`BeforeTool` mutation makes the final `op_prepared` digest authoritative. The preimage is
RFC 8785 JCS of the exact object
`{domain:"vv-agent/S1/command-digest",framing_version:1,purpose:"stable-command",
tenant_id,session_id,command_spec,environment,operational_policy}`. The
environment is `EnvironmentCapabilities.to_dict()` with nullable capability
digest; operational policy contains exactly the two policy digests. The session
key is never sent to the remote agent.

The lookup binding carries tenant, session, operation, attempt, final prepared request
digest, idempotency key, execution ID, final command digest, environment ID, generation
and provider ID. Stored lookup evidence is a single encrypted ContentRef; readback
validates its input owner, `provider_lookup` slot, logical binding and committed plan
before use. An authenticated `not_started` response is durably stored before at most
one new attempt using the same idempotency key and execution ID is sent.
`running` reuses the original execution; `exited` reconciles its definitive
result; `unknown` never permits a start retry. Transport or registry inability to
prove state maps to `unknown`. Binding or authorization mismatch rejects without
effects, and malformed results retain `provider_result_invalid` semantics. Existing
encrypted `op_parked`, `op_completed` and `op_unknown` evidence supports immediate
recovery without requiring a provider callback.

## Allocation and adoption

`fixtures/execution_worker_w3.json` is `contract-allocation-only` with
`producer_capture=false` and `adoption_evidence=false`. It supplies deterministic
identity, proposal/final command-HMAC, four-status logical lookup, retained
ContentRef, tamper/environment denial and bounded restart vectors.
`fixtures/worker_compatibility.json` records that a level-2
worker cannot claim a level-3 execution record while a level-3 thin reader can
decode without execution supports.

`fixtures/trusted_storage_s1.json` is separate real-producer evidence for the
level-1 storage shapes. It was captured twice from clean Python revision
`a5061281b95e92c528ea96c4b46dd57c28280b9b`. The fixture records that revision,
source-tree SHA-256
`393a1518ae2934e525403d0eebcae5b7e302bbe955ac6d389f1761cf11fc7d51`,
and 10 accepted plus 26 rejected cases. Both diagnostics and trusted captures were
byte-identical. The trusted fixture SHA-256 is
`47775bf5230a16c387388caaa912c788d446ff88c3fdaab3b776e9c402807f84`;
the generated `fixtures/SHA256SUMS` SHA-256 is
`ed0a1ffb0514c535437d856ee9c5d4d79abc8b5f7ad82e12de9e79278b50fabf`.
Ordinary content uses the S1 default `ContentLabels.source=[]`; principal
attributes are the explicit `["internal"]` case. The level-1 `provider_evidence`
capture retains the `handle.job_id`, `handle.evidence`, `handle.query_ref` and
`handle.cancel_ref` slots. It does not capture the level-3 `provider_lookup` slot.

The public API inventory records the direct `drive` parameter
`expected_head` with its keyword-only signature. That inventory is an API
authority, not a byte-level producer fixture and does not establish adoption.
Environment/provider adapters, W3 producer capture, durable W3 execution
storage, remote process supervision, complete SQLite/PostgreSQL gates,
immutable publication, Python lock/snapshot synchronization and the central
cross-repository workflow remain pending. The allocation fixtures are not
producer evidence and neither they nor this local S1 capture establish a
release URL or verified revision. Live repository state has no immutable
v40.0.0 or v41.0.0 tag/release and therefore no published artifact hash; local
deterministic build output is not a release artifact.

## Verification

The allocation requires `python3 scripts/contractctl.py validate`, the independent
Node JCS verifier, the complete repository unittest suite, generated-schema
byte-stability, a manifest rebuilt only with
`python3 scripts/contractctl.py manifest`, whitespace checks, and two
byte-identical builds written to temporary directories outside the repository.

