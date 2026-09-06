# Changelog

## 12.0.0 — pending adoption

- Ordinary definitive `ERROR` tool receipts persist the complete canonical
  `ToolExecutionResult` with `status_code=ERROR` in the existing journal
  `result` field; `result_digest` covers that exact result.
- Retained `OperationError` values are normalized diagnostic projections of
  the result. Checkpoint and session recovery verify the digest and construct
  `Message` directly from `journal.result`, preserving metadata, directive,
  and legal truncation pointers without inference.
- Synthetic terminal `tool_cancelled` closures remain the independent
  resultless exception with no definitive `result_digest`; model-visible
  `tool_outcome_unknown` receipts persist the complete `ERROR` result, digest,
  and `resume_observation` evidence.
- Advanced the operation-journal schema to v5 and checkpoint codec to v10;
  public API, result-public, event, and distributed response shapes are
  unchanged. No new projection, digest, table, index, API, compatibility
  reader, or migration is introduced.

This release remains `pending-adoption` until both language implementations
pin the same contract revision and pass their real producer and cross-language
quality gates.

## 11.0.0 — pending adoption

- Defined one canonical definitive tool receipt event identity for ordinary
  and deferred `tool_call_completed` receipts: `evt_receipt_` followed by the
  shared receipt `identity_key`.
- Reused the closed RFC 8785 receipt identity object
  `{attempt, checkpoint_key, operation_id, request_digest, tool_call_id}`;
  status, result digest, suffixes, and version markers do not affect the
  event ID.
- Required same-identity same-result replays to retain and reuse the event
  ID with zero writes, while same-identity different-result calls remain
  `tool_receipt_conflict` with zero writes.
- Scoped controller wake reaping to
  `CheckpointStore.reap_controller_command_wakes(checkpoint_key, now_ms)` with
  stable `(expected_revision, command_id)` ordering and explicit ambiguous-wake
  reconciliation.

This release remains `pending-adoption` until both language implementations
pin the same contract revision and pass their real producer and cross-language
quality gates.

## 10.0.0 — pending adoption

- Advanced the closed RunEvent discriminator to v5 and the public API
  inventory to `vv-agent-public-api-v7`/schema 7. The AgentResult/result-public
  wire remains v6 and the distributed worker response remains v4.
- Required live-claim cancellation to emit a complete top-level typed
  `run_state_changed` transition with
  `cancel_requested: {from: false, to: true}`.
- Defined a distinct repeated live-cancel command as an atomic applied no-op
  receipt: checkpoint revision, claim, lease, event outbox, and wake outbox
  remain unchanged, with zero-write same-command replay and no duplicate
  state event.
- Standardized completed-outcome rejection at `admit_deferred_batch` on
  `deferred_admission_completed_outcome_invalid`; definitive receipts are not
  rewritten by deferred admission.

This release remains `pending-adoption` until both language implementations
pin the same contract revision and pass their real producer and cross-language
quality gates.

## 9.0.0 — pending adoption

- Added durable per-tool receipts that persist the journal entry and
  `tool_call_completed` event immediately while retaining the active claim.
- Restricted `admit_deferred_batch` to deferred barrier admission and atomic
  claim release; definitive ordinary receipts are never written twice.
- Defined ordinary receipt identity as the sole `identity_key` lookup key;
  `result_digest` is the stored RFC 8785/SHA-256 digest of the complete strict
  `ToolExecutionResult` after canonical typed-writer normalization (empty
  optional metadata is omitted) and drives replay versus typed conflict.
- Upgraded checkpoints to `vv-agent.checkpoint.v9` with `cancel_requested`,
  typed renewal outcomes, expired-claim control recovery, and durable
  `cycle_aborted` lifecycle closure.
- Reserved `commit_cycle` for successful cycle commits; claimed cancellation,
  operator abort, and lease-loss closure use `finalize_claimed`, while an
  unclaimed operator abort uses the existing `finalize` operation.
- Replaced the terminal `resume_observation` field with the breaking v9
  `resume_observations` list, sorted and deduplicated by operation identity;
  each item is projected from the authoritative closed tool journal.
- Bumped the public result wire to version 6, the public API inventory to
  `vv-agent-public-api-v6`/schema 6, and the distributed worker response to
  `vv-agent.distributed-worker-response.v4`; the prior singular result member
  is not accepted by the current readers.
- Made fail-forward ambiguity the default: bounded model retry with duplicate
  risk and model-visible unknown tool outcomes; reconciliation remains explicit.
- Classified post-start timeout and `tool_execution_failed` outcomes as
  ambiguous unless an adapter proves a definitive result.

This major release remains `pending-adoption` until both language
implementations pin the same contract revision and pass their real producer
and cross-language quality gates. Python and Rust producers must adopt these
breaking v9 result, receipt, finalization, and terminal-observation shapes.

## 8.1.2 — pending adoption

- Added canonical invalid coverage requiring `ToolExecutionResult` values with
  `status_code=SUCCESS` and a non-null `error_code` to be rejected.
- Kept wire and runtime behavior unchanged.

This patch remains `pending-adoption` until both language implementations pin
the same contract revision and pass their real producer and cross-language
quality gates.

## 8.1.1 — pending adoption

- Recorded Redis checkpoint atomicity as implementation-neutral
  compare-and-swap transaction semantics. Lua, WATCH/MULTI/EXEC, and
  equivalent transactions satisfy the contract when they preserve the
  required revision, claim, lease, and pending-event fences.
- Kept all wire and runtime behavior unchanged.

This patch remains `pending-adoption` until both language implementations pin
the same contract revision and pass their real producer and cross-language
quality gates.

## 8.1.0 — pending adoption

- Added a task-neutral compiled distributed-start capability. Callers may pass
  an already-compiled `AgentTask`; the framework preserves that prepared task,
  does not re-run compile-time producers, and still returns a passive handle
  without waiting for cycle completion.
- Kept the existing distributed envelope, worker response, checkpoint, and
  driver decision wire shapes unchanged.
- Hardened cross-repository conformance with an isolated Redis service,
  dynamic service-port discovery, and an explicit health probe.

This minor release remains `pending-adoption` until both language
implementations pin the same revision and pass their real producer and
cross-language quality gates.

## 8.0.1 — pending adoption

- Corrected the `claimed_active_cycle` checkpoint fixture by removing an
  accidental top-level `vendor_future` member. Current checkpoint objects stay
  closed; vendor extension data remains valid only under `extension_state`.
- Audited all current checkpoint valid/invalid cases and controller-command
  digest vectors; no digest or state-metadata changes are introduced by this
  patch.

This patch remains `pending-adoption` until both language implementations pin
the same revision and pass their real producer and cross-language quality gates.

## 8.0.0 — pending adoption

- Added the task-neutral `vv-agent.controller-command.v1` closed command wire
  and `vv-agent.controller-command-receipt.v1` durable receipt.
- Added framework-produced host interaction admission with complete strict
  request persistence, an independent full request/response interaction
  record, notification-only `host_interaction_requested` event outbox,
  response-consumed marker, same-logical-cycle recovery, strict CAS fences,
  replay/conflict/stale behavior, and crash-after-commit recovery.
- Kept deferred resolution, terminal successor continuation, and terminal
  `ask_user`/`wait_user` semantics as independent protocols.
- Added canonical SQLite/Redis receipt and interaction indexes, strict UTF-8
  and invalid cases, worker observation mappings, stable App Server `actionId`
  admission/message schema, and concrete C1-C17 fault evidence.
- Aligned host-response recovery with the canonical `recovery` claim mode:
  successful combined recovery increments `resume_attempt` once and propagates
  the new value through the consumed event and next envelope.
- Separated UI notification ambiguity reconciliation from controller wakes;
  notifications now have explicit delivered/retry/abort resolution and an
  `aborted` terminal state.
- Corrected C16 to emit `run_cancelled` with terminal
  `completion_reason=cancelled` and removed the UI notification action from the
  controller receipt outbox protocol.
- Defined the global App Server `command_id` as the length-prefixed
  RFC 8785/JCS UTF-8 SHA-256 derivation of `(threadId, turnId, actionId)`;
  `actionId` remains scope-local while receipts, indexes, replay, and conflict
  checks use the derived id.
- Made producer admission, controller response admission, and notification
  claim/delivery/reconciliation transaction boundaries explicit across the
  SQLite, checkpoint-store, and codec metadata; synchronized aborted
  notification columns with the canonical SQL schema.

This release remains `pending-adoption` until both language implementations
pin the same contract revision and pass their real producer and cross-language
quality gates.
