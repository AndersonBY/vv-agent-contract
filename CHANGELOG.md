# Changelog

All notable language-neutral contract changes are recorded here. Contract
versions follow the compatibility policy in `docs/compatibility-policy.md`.

## 0.8.0 - 2026-07-20

- Add optional, closed `ToolMetadata` declarations for coarse side-effect
  class, idempotency, terminal capability, opaque capability tags, and opaque
  cost dimensions. Typed metadata remains host-visible and is never added to
  the model tool schema or inferred from generic metadata, names, or arguments.
- Add cumulative metadata denial fields to `ToolPolicy`. Every new field can
  only narrow existing name, argument, approval, and runtime policy; missing
  tool metadata preserves existing behavior.
- Add `tool_call_planned` and enrich executor `tool_call_started` /
  `tool_call_completed` events with normalized metadata and typed outcome
  telemetry. Planning is distinct from execution and is never projected by
  App Server as a started item.
- Freeze effective typed metadata and metadata denials in checkpoint v2 run
  definitions while retaining legacy checkpoint readers and the public
  `idempotency` alias. Exact 0.7.1 definitions and digests remain immutable;
  additive defaults are used only in a comparison copy during resume.
- Propagate metadata denials monotonically through configured sub-agents,
  agent-as-tool runs, handoffs, and distributed workers; metadata-only drift
  fails before claim.
- Freeze complete App Server started/completed JSON-RPC projections and the
  required/null rules for 0.8 completed events.
- Keep tool schemas, prompts, default policy, completion, budgets, approvals,
  and task-domain behavior unchanged when the capability is not declared.

## 0.7.1 - 2026-07-20

- Declare `content_delta` and `delta` as equivalent accepted source fields for
  assistant stream projection. Built-in adapters use `content_delta`, while
  the existing custom-model and configured-child callback surface also accepts
  `delta`.
- Preserve every 0.7.0 wire type, payload field, ordering rule, and safety
  boundary. Contract 0.7.0 did not reach verified adoption; implementations
  adopt 0.7.1 or later in this minor line.

## 0.7.0 - 2026-07-20

- Add typed top-level and child `reasoning_delta`,
  `model_tool_call_started`, and `model_tool_call_progress` RunEvents with
  framework-owned run, trace, session, agent, and cycle identity.
- Distinguish model tool-call generation from the existing executor
  `tool_call_started` lifecycle event and lock both meanings in producer
  evidence.
- Restrict untrusted raw stream projection to four declared source events;
  unknown and invalid source payloads remain available only to an explicit raw
  observer and cannot fabricate typed lifecycle or terminal events.
- Isolate raw observer failures, retain event-store fail-open/fail-closed
  semantics, and keep raw callbacks at-least-once rather than presenting them
  as durable delivery.
- Keep reasoning private in App Server projection and preserve task, prompt,
  tool, completion, budget, cancellation, and approval behavior.

## 0.6.0 - 2026-07-20

- Add an opt-in, typed after-cycle lifecycle hook with closed `continue`,
  `steer`, and `stop_non_success` decisions.
- Allow next-cycle user steering and monotonic tool denials without permitting
  hooks to expand permissions or fabricate a successful/waiting terminal.
- Define immutable snapshots, deterministic multi-hook composition, bounded
  inputs, fail-closed invalid decisions, and terminal precedence without task
  category or domain milestone fields.
- Persist cumulative tool denials across checkpoint v1/v2 and pair stateful
  hooks with the existing versioned checkpoint-extension state protocol.
- Add distributed after-cycle capability references resolved before claim and
  pinned in the immutable run definition. The capability remains
  `pending-adoption` until both implementations and cross-repository CI pass.

## 0.5.6 - 2026-07-19

- Define a non-empty `reasoning_content` value as valid runtime and resumable
  assistant history even when visible content and tool calls are empty.
- Require OpenAI-compatible adapters to project a reasoning-only assistant
  with an explicit empty `content` string instead of omitting both content and
  tool calls. Private reasoning is never promoted to visible assistant text.
- Keep completely empty assistant turns removable and preserve the existing
  task-agnostic no-tool policy, token accounting, and reasoning stream
  telemetry. This patch closes a Python/Rust history and provider-wire
  inconsistency found by the P1H live coding canary.

## 0.5.5 - 2026-07-16

- Replace the last placeholder outbox payload digest in the canonical
  checkpoint and its claimed-cycle copy with the actual RFC 8785 event digest.
- Add repository validation that every canonical and valid checkpoint outbox
  entry has matching event bytes and payload digest. No wire field or runtime
  behavior changes.

## 0.5.4 - 2026-07-16

- Add `CheckpointConfig.credential_slots`, a sorted unique list of RFC 6901
  JSON Pointers into the unredacted run definition. This is the executable host
  declaration required before credential values can be replaced and the run
  definition can be canonicalized.
- Keep the default empty and preserve disabled checkpoint behavior. Providers
  may contribute their declared slots, but implementations must merge and
  validate the complete effective list instead of guessing secrets from key
  names.
- Preserve all 0.5.3 checkpoint and journal wire fields. This patch closes the
  last missing public producer input found before the 0.5 capability's first
  paired adoption.

## 0.5.3 - 2026-07-16

- Correct the checkpoint terminal order so the terminal event is first staged
  as pending, the active claim and terminal receipt are finalized atomically,
  delivery is recorded by CAS, and only then is the retained terminal
  acknowledged. The older runner fixture incorrectly placed delivery before
  finalization.
- Define append-once session persistence for checkpoint v2. A session used by
  an enabled checkpoint run must support a stable commit id plus RFC 8785
  payload digest, replay an identical commit without appending duplicate
  messages, and reject an identity/digest conflict before terminal finalize.
- Close approval-resume adoption semantics without retaining a planned journal
  in the source waiting terminal: the approved `RunState` carries the source
  operation seed, a configured Runner supplies a distinct explicit checkpoint
  key, approval consumption binds idempotently to that key, and the new
  checkpoint durably seeds the same tool-call id, request digest, and
  idempotency key before dispatch.
- Require event ids to be unique inside one checkpoint outbox. Re-enqueueing
  the same id and payload reuses the existing entry; a different payload is an
  `event_identity_conflict`.
- Preserve the 0.5.2 wire fields and disabled-by-default behavior. This patch
  closes lifecycle contradictions found before the 0.5 capability's first
  paired adoption.

## 0.5.2 - 2026-07-16

- Add `finalize_claimed_v2`, an atomic compare-revision-and-claim operation
  that writes a terminal result while clearing the active claim. This closes
  the executable path for definitive model/tool failures and other terminals
  reached before an active cycle can be committed.
- Add `record_event_delivery_v2`, an atomic CAS operation that verifies a
  pending outbox event identity, records its returned cursor, advances the
  checkpoint event cursor, and works for both running and retained terminal
  records.
- Require claimed terminal finalization to preserve explicit operator-abort
  ambiguity but clear ordinary active journals, and require event-delivery
  recording to preserve a live claim and immutable terminal receipt.
- Preserve all 0.5.1 wire fields and activation defaults. This patch closes
  store lifecycle operations that the 0.5.1 prose required but its executable
  store surface could not perform.

## 0.5.1 - 2026-07-16

- Define the complete run-definition object and lock RFC 8785 canonical bytes
  plus SHA-256 golden vectors across Unicode, floating-point settings, tools,
  policies, budgets, capability references, and extensions.
- Embed that credential-redacted definition beside its digest in checkpoint v2
  so resume freezes original prompt/session/context inputs instead of trying to
  reconstruct them from mutable host state.
- Define credential redaction before digesting and reject unstable local tool
  predicates or non-I-JSON values before external operations.
- Add the `vv-agent.run-definition.v1` discriminator to checkpoint and
  distributed v2 records so never-verified 0.5.0 unspecified digests cannot be
  silently resumed under the canonical algorithm.
- Close extension-size boundaries by counting the canonical UTF-8 bytes of the
  complete `{version, required, state}` entry and providing executable exact
  and one-byte-over generators.
- Lock operation request digests to RFC 8785, distinguish continuation claims
  from atomic recovery claims, and classify post-start timeout/cancellation as
  ambiguous unless an adapter proves a definitive external outcome.
- Add an atomic resumable-interruption suspend operation that preserves
  ambiguous journals while releasing the active claim.
- Keep reconciliation providers optional, prevent checkpoint-key inheritance
  into child runs, and fail closed for handoffs until active-agent state and the
  complete handoff graph are contractual.
- Add explicit local behavior capability references, distributed claim-mode
  evidence, and complete `turn/resume` JSON-RPC lifecycle fixtures.
- Lock resume-attempt increments, typed invalid-config/journal error codes, and
  split resume event excerpts into coherent independent scenarios.
- Fix the documented legacy Redis namespace to the existing
  `vv_agent:checkpoint:` bytes and lock the safe App Server checkpoint and
  interruption summary fields.
- Preserve the 0.5.0 safety goals while closing unsafe or underspecified wire
  behavior before the 0.5 capability's first paired adoption.

## 0.5.0 - 2026-07-16

- Add opt-in checkpoint v2 with stable checkpoint keys, run-definition
  digests, explicit resume policies, independent SQLite/Redis namespaces, and
  retained terminal replay.
- Add model and tool operation journals with durable intent/receipt ordering,
  stable tool idempotency keys, replay of committed receipts, and explicit
  ambiguity when an external effect cannot be proven.
- Add host checkpoint extensions, reconciliation decisions, cumulative budget
  resume, event cursors, checkpoint outboxes, and idempotent event-store
  delivery without claiming transactional callbacks or arbitrary exactly-once
  external APIs.
- Add `turn/resume` App Server projection and typed
  `reconciliation_required` interruption behavior. Checkpoint v2 remains
  disabled when no `CheckpointConfig` is supplied.
- Preserve checkpoint v1 and distributed envelope v1 bytes and readers. The
  0.5.0 capability is published as `pending-adoption` until both real
  implementations and central cross-repository CI pass.

## 0.4.1 - 2026-07-16

- Define JSON-safe cumulative arithmetic overflow as an unavailable metric
  instead of permitting Python/Rust wire divergence, truncation, or wrapping.
- Close host-meter sampling, token-source, monotonic rounding, unavailable
  ordering, and budget snapshot event rules without changing the optional
  0.4.0 capability set.
- Clarify that distributed hosts resolve a worker-local host meter through the
  existing capability registry and that policy-only limits remain unlimited.

## 0.4.0 - 2026-07-16

- Add optional run budgets for total tokens, uncached input tokens, total and
  exact-name tool calls, monotonic active wall time, and host-reported cost.
- Add typed budget usage, unavailable observations, exhaustion causes,
  enforcement boundaries, and `budget_exhausted` terminal projection across
  results, events, App Server, and durable distributed state.
- Require whole-batch tool preflight, one-atomic-operation token/cost
  overshoot reporting, missing-not-zero accounting, and deterministic terminal
  precedence without inspecting task content.
- Add a task-agnostic cumulative host cost meter protocol. The framework does
  not contain prices, convert units, or implicitly combine parent and child
  budgets.
- Add executable public Runner and evaluator cases in `run_budget_v1.json` and
  canonical event records in `budget_events_v1.jsonl`.

## 0.3.6 - 2026-07-15

- Require a successful claim renewal before a distributed worker invokes the
  runtime cycle, preventing model or tool side effects when heartbeat
  infrastructure is already unavailable.
- Keep heartbeat renewal active through checkpoint commit and stop it on
  operation unwind, closing the post-cycle lease window without weakening CAS.
- Cap initial and renewed leases at the job deadline and require the heartbeat
  interval to remain below every accepted positive lease duration.
- Require both implementations to replace sub-second wall-clock sleep
  assertions with executable, state-driven lease lifecycle evidence.

## 0.3.5 - 2026-07-15

- Close approval resume ordering: a fresh run in the source trace receives the
  full configured cycle budget, rejects extra input before cancellation or
  approval claim, and observes valid pre-cancellation before claims, tool
  effects, or output guardrails.
- Preserve runtime-owned completion observation across output-guardrail allow
  rewrites and require ordinary model-call failures to produce one typed failed
  terminal.
- Reject invalid completion fields in RunEvent v1, while retaining unknown
  top-level-field compatibility.
- Lock App Server wait/cancel status projection and scope
  `sub_task_wait_user` to the synchronous parent-tool envelope instead of
  internal waiting outcomes.

## 0.3.4 - 2026-07-15

- Complete the synchronous waiting sub-task tool envelope with the existing
  `sub_task_wait_user` error code emitted by both language implementations.
- Keep completion behavior unchanged while making the canonical expected
  payload directly executable by paired producer tests before adoption.

## 0.3.3 - 2026-07-15

- Add the canonical Python property signatures for the three RunResult
  completion-observation members introduced in the public surface inventory.
- Require every property member in the public API fixture to carry a signature,
  closing the last implementation-producer verification gap without changing
  completion behavior or wire fields.

## 0.3.2 - 2026-07-15

- Complete the public surface inventory for the Agent and RunConfig no-tool
  controls and the RunResult completion observation fields.
- Add canonical synchronous sub-task outcome evidence for failed and waiting
  child runs so completion reason, tool identity, and partial output survive
  the manager-tool envelope.
- Keep the `0.3.0` behavior unchanged; this patch closes producer evidence
  required before paired implementation adoption.

## 0.3.1 - 2026-07-15

- Restore canonical sorted ordering for the public RunResult projection-key
  inventory after adding completion observation fields in `0.3.0`.
- Keep the `0.3.0` behavior and wire fields unchanged; paired implementations
  adopt this fixture-closure patch.

## 0.3.0 - 2026-07-15

- Promote the existing runtime no-tool behavior to public Agent and RunConfig
  controls with `continue` as the backward-compatible default.
- Define exact per-run, Runner-default, Agent, and framework precedence without
  inspecting assistant text or task semantics.
- Add typed completion reasons, partial assistant output, and completion tool
  identity to results, terminal events, persisted results, and App Server turn
  completion notifications.
- Lock deterministic completion cases for natural no-tool finish/wait, explicit
  finish tools, tool-use stop policies, max cycles, cancellation, and failure.

## 0.2.1 - 2026-07-15

- Complete the token-usage wire closure by adding the typed cache observation
  to the canonical successful sub-run event payload.
- Keep `0.2.0` immutable; implementations adopt this patch release so result,
  checkpoint, App Server, and sub-run event projections all use one shape.

## 0.2.0 - 2026-07-15

- Add a provider-neutral cache-usage observation to token accounting while
  preserving the existing numeric token fields as compatibility projections.
- Distinguish provider-reported zero cache reads from missing accounting and
  explicit adapter-declared lack of cache support.
- Mark token totals as provider-reported, estimated, or unavailable, and
  define conservative aggregation that never presents a partial cache total
  as complete.
- Add canonical normalization and aggregation cases for OpenAI-compatible,
  Anthropic, normalized provider bridges, estimated, missing, unsupported,
  explicit-zero, and invalid cache usage.

## 0.1.0 - 2026-07-13

- Establish the first independent canonical contract for `vv-agent` and
  `vv-agent-rs`.
- Import 34 canonical fixtures covering prompts, built-in tools, public SDK
  capabilities, runtime events, sessions, delegation, App Server, memory, and
  distributed execution.
- Add deterministic validation, release bundles, implementation lock files,
  vendored snapshot checks, adoption automation, and cross-repository gates.
