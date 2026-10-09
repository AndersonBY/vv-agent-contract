# After-cycle lifecycle

The task-neutral after-cycle hook observes a finalized primary cycle and may
continue, steer the next request or stop with non-success. The snapshot and
closed decisions, limits and producer cases are in `after_cycle_hook.json`.

A hook runs after the assistant response and the complete frozen tool batch have
results, including explicitly skipped calls. It runs before native completion
and before another dispatch. Incomplete batches, model failures, cancellation
and budget interruption do not invoke this boundary. The snapshot contains
copied messages/JSON state, cumulative TaskTokenUsageTotals, next tool visibility,
remaining cycles and the native outcome; mutation of a copy grants no authority.

Actions are continue, steer and stop_non_success. Continue preserves the native
outcome and can add denials. Steer adds bounded user messages and defers a steerable
completion. Stop produces failed, never completed or wait_user. Tool denials only
union; hooks cannot add tools, remove denial, change approval or alter schemas.
Planning and dispatch enforce the composed denials.

Runner-default hooks precede per-run hooks; all receive the same base snapshot.
Steering concatenates in registration order and denials union. First stop wins;
later hooks are skipped. The first exception or invalid decision fails durably.
Impossible steering fails with after_cycle_steer_unavailable; it cannot override
wait, max cycles, cancellation, budget exhaustion or execution failure.

The closed after_cycle boundary retains action, steering_messages, disallow_tools,
stop, shared_state and error before another dispatch. A committed boundary MUST be
reused without replaying callbacks. An interruption before commit permits callback
replay: hooks are at least once, so external effects require tool admission or a
host outbox. No hooks means no callback, decision state or lifecycle noise.

The JSON deny state under `_vv_agent_after_cycle_control` is created only for
nonempty denials. Required host references are explicit host bindings; callbacks
are not serialized. JSON state and denials survive reconstruction. These rules
use the [session kernel](session-kernel.md), including atomic commit and fencing.
