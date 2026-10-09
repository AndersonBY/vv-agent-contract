# Changelog

## 24.0.0 — major

One ordered session log/inbox kernel owns execution, recovery and projections.
Retire require_reconciliation, checkpoint, deferred, distributed and controller
surfaces, their configuration, readers and tests. Storage layout remains outside
the language-neutral contract. Python F3 adoption is pending; Rust is frozen at
23.0.0 / 0.21.x, verified baseline
00f4240786f1adea1dc0c4730da8ddd06a5ab8ac.

| Source / item | v23 behavior | 24.0.0 behavior | Owning doc / fixture |
| --- | --- | --- | --- |
| Maker: execution authority | Checkpoint/controller/distributed and transcript stores | One log/inbox kernel; no require_reconciliation | session-kernel.md / session_semantics.json, public_api.json |
| F2d-1 ask_user | Reply resumes a successor run | Reply completes original turn/op with one definitive receipt | session-kernel.md / completion_policy.json, runner_session_messages.jsonl |
| F2d-1 no-tool wait | Returned WAIT_USER; successor resume | Real turn_parked; same-turn user reply, no fabricated tool | session-kernel.md / completion_policy.json |
| F2d-1 approval deadline | Immediate provider decision can pass zero timeout | Absolute park deadline includes decision time; expired allow rejects | session-kernel.md / approval_tool_policy.json |
| F2d-1 cancel | Function/SDK path can throw CancelledError without terminal event | Durable cancelled terminal/event; confirmed stop versus unknown | stream-events.md / runner_terminal.json, run_events.jsonl |
| F2d-1 hooks | Process callbacks without unified boundary recovery | Committed result reused; precommit interruption may rerun | after-cycle-lifecycle.md / session_semantics.json |
| F2d-1 Bash | Process-local manager | Explicit original-owner/live-manager reattach limit; otherwise unknown | bash-process-management.md / session_semantics.json |
| F2d-2 boundary wire | No boundary_recorded | Seven closed stages retain callbacks/decisions | session-kernel.md / session_record.schema.json, session_records.jsonl |
| F2d-2 added fields | No kernel endpoint/interaction/archive/completion evidence fields | endpoint_id, interaction_result, micro_usage, child_result.status | session-kernel.md / session_record.schema.json, session_inbox.schema.json |
| F2d-2 tool budget | Preflight without durable whole-batch reservation | Atomic model receipt + reservation + plans; skipped reserved calls count | run-budgets.md / run_budget.json, budget_events.jsonl |
| F2d-2 internal tokens | Repair absent from public call ledger | All internal calls/attempts counted, including repair | model-call-accounting.md / token_usage.json |
| F2d-2 unavailable wall | Old process interval cannot be reconstructed uniformly | Lost interval unavailable; strict stop, no downtime estimate | run-budgets.md / run_budget.json |
| F2d-2 tracing | Immediate processor delivery | ACK-first at most once; possible telemetry loss | stream-events.md / runner_trace_spans.json |
| F2d-2 events | Immediate event/outbox paths | At-least-once projection; stable external deduplication IDs | stream-events.md / event_store_replay.jsonl |
| F2d-2 child event ownership | Configured lifecycle belongs to child run | Parent record/run owns admission/completion and carries child identity | session-consumers.md / configured_sub_agent_events.jsonl |
| F2d-2 endpoints | Internal client fallback/retry merged in ledger | Independent logged attempts; transport retry=1; max(2,endpoints) | model-call-accounting.md / token_usage.json, runner_events.jsonl |
| F2d-2 coercion/repair | Coercion may throw; no repair public enum | Durable failed output; budgeted logged repair, unknown never retried | output-validation.md / output_validation.json, public_api.json |
| F2d-2 rejected summary | Identical summary callback can repeat | Same source/mode/tail reuses receipt even if rejected | session-kernel.md / session_compaction.json, memory_lifecycle.json |
| F2d-3 delegation | Separate configured/SDK/background/handoff execution adapters | One atomic child mechanism | session-kernel.md / configured_sub_agent.json, public_configured_sub_agent.json |
| F2d-3 child wait | Intermediate child WAIT_USER can complete parent tool | Child keeps wait; parent adopts only terminal | session-consumers.md / manager_tool_envelope.json, session_semantics.json |
| F2d-3 background | Start snapshot races child execution; in-process handles | Start=running; read/control from records/inbox after reconstruction | session-consumers.md / public_api.json, session_semantics.json |
| F2d-3 handoff | Mutable live limit; over-limit RuntimeError; source marker guardrail | Admitted count/limit; durable failure; target validation only | session-kernel.md / handoff_contract.json |
| F2d-3 shared_state | Arbitrary Python objects in state | Durable JSON plus explicit host bindings; MissingHostBinding | session-kernel.md / result_public.json, public_api.json |
| F2d-3 Agent.as_tool cancel | Can throw CancelledError | Durable child cancelled terminal and failed/cancelled projection | session-kernel.md / public_configured_sub_agent.json |
| F2d-3 added fields | No admitted child descriptor/siblings/delegation/binding namespace | Exact closed and reserved fields in §§2.4, 2.7 | session-kernel.md / session_record.schema.json, run_definition.json |
| F2d-4 entrypoints | Old defaults; private selector only in F2 | Runner/interactive/CLI/App Server share kernel; selector deleted in F3 | parity-contract.md / public_api.json, cli_contract.json |
| F2d-4 thread metadata | Independent ThreadStore | Thread=session, turn=run; attributes.app_server sole metadata home | session-kernel.md / app_server_observable.json |
| F2d-4 multimodal | Input stored on old thread/run path | Original input + frozen vv_session.input_messages survive rebuild | session-kernel.md / app_server_observable.json, run_definition.json |
| F2d-4 wait projection | turn/completed interpreted as final attempt/run result | interrupted attempt is nonterminal; same turn continues, one turn_ended | session-kernel.md / app_server_observable.json |
| F2d-4 ask_user item | WAIT_RESPONSE tool item can appear before reply | Safe interaction projection until definitive tool receipt | session-kernel.md / app_server_observable.json |
| F2d-4 restart owner/status | stale running thread→idle | Preserve active turn and original approval owner; no repeat calls | session-kernel.md / app_server_observable.json |
| F2d-4 closed thread | Resume can reopen ephemeral closed status | Durable closed boundary; start fails -32602 Thread is closed | session-kernel.md / app_server_observable.json |
| F2d-4 history | Default App Server has no shared transcript session | Later turns use same session's full retained context projection | session-kernel.md / app_server_observable.json, runner_session_messages.jsonl |
| F2d-4 action | Controller receipt/revision/outbox-derived projection | Inbox admission; immediate accepted/running; no controller fields | session-kernel.md / app_server_observable.json |
| F2d-4 approval order | Relative requested/request order unspecified | approval/requested projection precedes owner approval/request | session-kernel.md / app_server_observable.json |
| F2d-4 resume wire | checkpointKey and summaries | Only threadId/turnId; records supply result, no summaries | session-kernel.md / app_server_observable.json |
| F2d-4 client cursor | thread/read cursor; thread/resume lacks schema field | thread/resume afterItemId, stable timeline replay | session-kernel.md / app_server_observable.json |
| F2d-4 interaction wire | Prompt-only sanitized status | Safe interaction identities and interactions[] | session-kernel.md / app_server_observable.json |
| F2d-4 item/model identities | Separately generated turn/run/call identities | turnId=runId; record-derived operation/call/item identities | session-kernel.md / app_server_observable.json, token_usage.json |

| Reviewer versions | RunEvent v5, model-call v1, task-token-usage v2, App Server v1, API v7 | RunEvent v6, model-call v2 with output_repair, task-token-usage v3, protocolVersion v2, public API v8; TokenUsage v1 retained | stream-events.md / token_usage.json, public_api.json |
| Reviewer Q2 | Null summary ID stringified | compact/{source_digest}/{mode} omits final segment; non-null appends summary_operation_id | session-kernel.md / session_compaction.json |
| Reviewer Q3 | Separate session_* reserved task/request keys; shared state inside usage | One closed vv_session per metadata map; compile rejects user vv_session; op_completed.shared_state separate from measurements | session-kernel.md / session_record.schema.json |
| Reviewer Q5 | Thread snapshot/status have different enums | One idle/running/interrupted/archived/closed enum and projection everywhere | session-kernel.md / app_server_protocol.json |
| Reviewer Q6/Q7 | Closed resume and disconnected owner behavior | All closed execution resumes -32602 Thread is closed; original approval owner retained, observer cannot approve; unanswered approval resolves at absolute deadline via timeoutDecision | session-kernel.md / approval_tool_policy.json |
| Reviewer Q9 | Hash anchors could accept newline | Exactly 64 lowercase hex characters; full-match with trailing-newline negative | session-kernel.md / session_invalid.json |
| Reviewer Q10 / v-claw | replace_messages hydration, replace_shared_state retry reset, clear_queues and writable session access | Creation-time closed attributes.seed={messages,shared_state}, both required; projects before first context/state; v-claw seeds a new durable session; no mid-session mutation | session-kernel.md / session_semantics.json |
| Reviewer inbox | deferred_result | provider_result; provider authentication and retained evidence binding | session-kernel.md / session_inbox.schema.json |

### Fixture actions

- Delete (13): `checkpoint_codec.json`, `checkpoint_config.json`, `checkpoint_resume.json`, `checkpoint_sqlite_canonical.sql`, `checkpoint_store.json`, `controller_command.json`, `deferred_tool.json`, `distributed_run_driver.json`, `distributed_run_envelope.json`, `distributed_worker_response.json`, `operation_journal.json`, `resume_events.jsonl`, `session_sqlite_canonical.sql`.
- Replace (34): `after_cycle_hook.json`, `app_server_observable.json`, `approval_tool_policy.json`, `bounded_tool_result.json`, `budget_events.jsonl`, `completion_policy.json`, `configured_sub_agent.json`, `configured_sub_agent_events.jsonl`, `event_store_replay.jsonl`, `handoff_contract.json`, `llm_stream_projection.json`, `manager_tool_envelope.json`, `memory_lifecycle.json`, `memory_local.json`, `output_validation.json`, `prompt_bundle.json`, `public_api.json`, `public_configured_sub_agent.json`, `result_public.json`, `run_budget.json`, `run_config_controls.json`, `run_definition.json`, `run_events.jsonl`, `run_events_invalid.json`, `run_handle.json`, `runner_events.jsonl`, `runner_session_messages.jsonl`, `runner_terminal.json`, `runner_trace.jsonl`, `runner_trace_spans.json`, `session_codec.json`, `session_items.jsonl`, `token_usage.json`, `tool_metadata.json`.
- New (11): `app_server_protocol.json`, `session_codec_vectors.json`, `session_compaction.json`, `session_inbox.jsonl`, `session_inbox.schema.json`, `session_invalid.json`, `session_projection.json`, `session_record.schema.json`, `session_records.jsonl`, `session_recovery.json`, `session_semantics.json`.
- Keep (7): `assistant_reasoning_history.json`, `bash_process_management.json`, `builtin_tool_behavior.json`, `builtin_tools.json`, `cli_contract.json`, `model_ref.json`, `model_settings.json`.

Five action-ID golden vectors move byte-for-byte in identity value to
app_server_observable.json actionAdmission.commandIdCases; app_server_protocol.json
retains real child-reply identity evidence. Rendered prompts, summaries, artifacts,
cursors and provider deltas preserve their independent content rules.

v23 verification evidence: Python 951ffc4be155321c535d7bbb9cce1eb788b2c27e,
Rust 00f4240786f1adea1dc0c4730da8ddd06a5ab8ac, central run
https://github.com/AndersonBY/vv-agent-contract/actions/runs/37561132745,
2026-10-07T02:32:42Z. This evidence verifies v23 only.


## 23.0.0 — adoption in progress

- Replace history only after an accepted complete-prefix summary; retain an
  atomic raw tail and preserve safely pruned history on failure.
- Preserve the complete localized summary prompts and normalize harmless model
  formatting/schema variations before checking effective summary content.
- Keep typed artifact/cursor evidence in closed summary metadata through
  recompression, session serialization and deterministic receipt replay.
- Re-summarize for emergency recovery or exhaust without dropping history.
- Remove automatic file restoration, duplicate pruning, image stripping and
  obsolete MemoryManager controls; keep current unrelated discriminators.
- Contract authoring is in progress; paired implementation adoption and central
  verification are outstanding.

## 21.0.0

- Separate Bash initial wait (`yield_time_ms`, default 1000, range 0..10000)
  from an optional execution deadline (`timeout_seconds`, range 1..86400).
- Start and running-query receipts are definitive successes that permit the
  next model cycle under a durable checkpoint.
- Add owner-scoped process-tree stop, bounded live output, immutable artifacts,
  and explicit missing/unknown observations without invented exit codes.
- Advance the built-in tool manifest and capability to version 4; remove the
  replaced Bash controls. Paired adoption is pending.

## 20.0.0

- Add an optional first-delivery admission callback to distributed start. A
  false callback result transfers first-delivery ownership to the caller's
  transactional outbox without creating a framework transport receipt.

## 19.0.0

- Workspace edits return a compact replacement receipt and file identity metadata.
- Consecutive edits retain current baseline validation, exact matching, and UTF-8/CRLF preservation.

## 14.0.0

- Distributed recipes accept an empty settings-file path when a registered
  LLM client reference supplies the model client.
- File-backed recipes still require a non-blank path. Missing client
  references fail before execution without file fallback.
- Current closed wire shapes and backend/model/workspace identities remain
  unchanged.

## 13.0.0 — adoption in progress

- Host interaction prompts and response messages retain their original UTF-8
  content across persistence, recovery, notifications, and App Server reads.
- Content digests bind the original payload. Business text and JSON values
  are opaque to the framework, including credential-like examples and URLs.
- Closed schemas, UTF-8 limits, identity checks, CAS, and explicit platform
  credential slots retain their existing boundaries. Wire shapes are unchanged.

Paired implementation and cross-repository verification remain required
before this contract can be marked verified.

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
