# Bash Process Management

## Inputs and clocks

`bash` has exactly `command`, `exec_dir`, `stdin`, `auto_confirm`,
`yield_time_ms`, and `timeout_seconds`. Only `command` is required.
`exec_dir` defaults to the workspace, `stdin` is optional text, and
`auto_confirm` defaults to false. Shell and environment configuration continue
to come from the existing host context.

`yield_time_ms` is an integer from 0 through 10000, default 1000. It bounds
the initial observation wait only. Zero requests an immediate management handle.
Expiry returns the handle and the captured output so far; it never kills the
process. `timeout_seconds` is an optional integer from 1 through 86400.
Omission means no execution deadline. Explicit null, booleans, strings,
fractional numbers, and values outside these ranges are rejected before spawn.
The removed `timeout` and `run_in_background` members are unknown fields, with
no aliases or fallback. Both query and stop accept exactly `session_id`.

One monotonic process-start observation establishes the execution deadline.
Preparing the shell precedes process start. Stdin delivery must not block the
initial yield or prevent deadline enforcement. Returning a handle, subscribing,
querying, and stopping cannot reset or extend the deadline. An explicit timeout
is enforced independently of whether a caller subsequently queries the handle.

## Receipts and process observations

A successful start or ongoing observation returns `ToolExecutionResult` with
`status_code=SUCCESS` and `directive=continue`. JSON content and bounded host
metadata include `status=running` and `session_id`. These are completed
management operations: they are recorded once by the normal checkpoint receipt
path and permit the next model cycle, including in a mixed tool batch. A later
process exit or listener callback cannot rewrite that receipt or its digest.
The generic `RUNNING` status and strict checkpoint/deferred result admission
remain unchanged for other uses.

Observed zero exit is success. Observed nonzero exit is `ERROR`, retaining the
real platform exit code and bounded stdout/stderr. A timeout is `ERROR` even
when the process handles termination by exiting zero. Stop requests report the
observed process result; signals must not be replaced by invented 130/137 or
other guessed exit codes. A stopped process may therefore return `ERROR` with
its real nonzero exit code.

Process states are `running`, `stopping`, `unknown`, `completed`, `failed`,
`timeout`, and `stopped`. `stopping` and `unknown` mean there is no confirmed
terminal observation. A management receipt for those observations is successful
with `continue`, has no exit code, and says that termination remains unconfirmed.
Querying a missing local record returns `ERROR` with `status=missing` and no
exit code. It does not assert that an external process has stopped. Process
launch or output retrieval errors remain ordinary tool errors.

## Ownership and process-tree stop

The existing process-local memory manager binds every session to the initiating
`task_id` and the effective workspace identity: the canonical local workspace
root in which the built-in shell executes. The execution directory may be a
subdirectory, but does not replace the workspace identity. Artifact backend,
task and call names are storage labels, not authorization. Query and stop validate that
binding before polling a process, reading logs, persisting artifacts, notifying
listeners, or sending a signal. A mismatched owner returns
`background_session_forbidden` with zero such effects. Session identifiers are
opaque handles and do not independently grant access.

`stop_background_command` requests termination of the process tree and returns
within the manager's bounded termination attempt. Terminal `stopped` or
`timeout` requires confirmation that the managed tree has no executing members,
not merely that its shell parent exited. Retry or query may observe `stopping`
or `unknown` until confirmation exists. The actual parent exit code is retained
once the tree is confirmed. An already-terminal session returns its retained
observation. Owner validation precedes even that lookup's output projection.
Existing interactive subscriptions remain available and notify only on confirmed
terminal observations.

## Output and lifetime

Running queries return the current bounded combined stdout/stderr head/tail
preview, preserving Unicode and tail changes. Complete oversized output uses
the existing private immutable workspace artifact mechanism, reachable through
policy-checked `read_file`. A running artifact freezes the exact captured prefix
observed by that query; later output cannot modify it. Terminal queries reuse
one terminal artifact. Storage errors never claim that truncated output is
recoverable. Captures remain recoverable across ordinary repeated queries.

The manager is process-local memory, with the existing capture and artifact
storage. Restarting it loses its session records. There is no distributed job
store, scheduler, remote-process recovery claim, or new shell backend.

## Required producer evidence

Both real registries and checkpointed Runners must exercise immediate yield,
yield expiry and running query, then call a ScriptedLLM for the next cycle.
Local real children and a loopback HTTP service establish execution and stop
behavior without external providers. Mixed tool batches retain the original
receipt after the child exits. Deadline tests cover original-start accounting
and query without extension. Other coverage includes schema boundaries,
zero-effect foreign owner queries/stops, missing manager records, unconfirmed
termination, process-tree stop, bounded live logs, Unicode head/tail output,
artifact recovery and repeated terminal queries.
