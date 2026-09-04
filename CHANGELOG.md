# Changelog

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
