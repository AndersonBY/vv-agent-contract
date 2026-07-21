# After-Cycle Lifecycle Hooks

Contract `0.6.x` adds an optional, task-neutral host control point after a
complete Agent cycle. It exists so a host can observe a committed unit of work,
add a bounded user steering message for the next cycle, narrow tool access, or
stop with a non-success result. It does not classify tasks or decide whether a
research, coding, browsing, or other domain-specific milestone is complete.

The executable shape and limits are canonical in
`fixtures/after_cycle_hook_v1.json`.

## Invocation Boundary

An after-cycle hook runs only after the assistant response and every planned
tool call in that cycle has a terminal result, including framework-generated
skipped results. It runs before native completion/wait projection and before
the cycle checkpoint is committed. A model failure, incomplete tool batch,
cancellation, or budget stop that interrupts the cycle before this boundary
does not invoke the hook.

The snapshot contains the finalized cycle, copied messages and shared state,
cumulative token usage, next-cycle tool visibility, remaining cycles, and the
runtime's native outcome candidate. It contains no task-category, research
phase, coding phase, milestone, answer-confidence, or lease-policy field.
Mutating a Python snapshot copy cannot mutate runtime state; Rust exposes
borrowed immutable values.

## Closed Decisions

The only actions are:

- `continue`: preserve the native outcome, optionally adding tool denials.
- `steer`: add one or more bounded user messages for the next cycle and defer a
  steerable native completion candidate.
- `stop_non_success`: return `failed` with completion reason `failed`; it can
  never produce `completed` or `wait_user`.

Tool policy changes are monotonic. A hook may only add exact tool names to the
effective deny set. It cannot add an allowed tool, remove an existing denial,
change approval requirements, replace a predicate, or modify a model-visible
tool schema. Denials apply both to planning and dispatch so an unadvertised
call cannot bypass the decision.

Steering is allowed for an ordinary continue candidate and for a candidate
completion. It is not allowed to override wait-for-user, max-cycles,
cancellation, budget exhaustion, or an execution failure. An impossible steer
fails closed with `after_cycle_steer_unavailable` rather than being silently
ignored.

## Composition And Failure

Runner-default hooks run before per-run hooks. All hooks receive the same base
snapshot. Steering messages concatenate in registration order and tool denials
form a union. The first `stop_non_success` wins and later hooks are not called.
The first exception or invalid decision fails the run with a typed runtime log
code and completion reason `failed`.

No hooks means the native runtime path: there is no callback invocation, no
control state, no lifecycle log, no checkpoint extension, and no change to the
default continuation hint or terminal result.

## Durability

The framework persists its cumulative deny set under the reserved shared-state
key `_vv_agent_after_cycle_control` using the closed
`vv-agent.after-cycle-control.v1` shape. The key is created only after a
non-empty denial, so enabled observer-only hooks do not change result or
checkpoint bytes beyond their explicitly configured extension state.

A stateful hook uses the existing `CheckpointExtension` protocol. The host may
register one concrete object as both the after-cycle hook and checkpoint
extension. Its namespace/version are pinned in the immutable run definition;
its snapshot is captured after the decision and before cycle commit, and it is
restored before the first resumed cycle. A committed cycle's hook is not called
again on resume.

The hook callback is not an external-operation journal. It must not perform an
unjournaled remote side effect, and a decision for the same snapshot must be
deterministic or idempotent. External effects belong in tools or a host outbox.

## Distributed Execution

Distributed v2 adds `recipe.capabilities.after_cycle_hook_refs`. Every
reference is resolved before checkpoint claim, model invocation, or tool
dispatch and is pinned as `after_cycle_hook:<index>` in the run definition.
Stateful hooks additionally use the existing `checkpoint_extension_refs`
descriptor. Missing behavior or required state capabilities fail before a
worker can acquire the run.

Python may express hooks as protocols and immutable dataclasses. Rust may use
traits and enums/builders. These are allowed adaptations only when the closed
snapshot, decision, ordering, limits, permission monotonicity, terminal
precedence, and durability behavior remain identical.
