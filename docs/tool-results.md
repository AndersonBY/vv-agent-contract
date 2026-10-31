# Replayable tool results

App Server v5 exposes one bounded projection of each immutable tool
`op_completed` record. The public API remains v15, RunEvent v6, record 1,
inbox 3 and SQL layout 3. This change does not require a store boundary.

Completed `toolCall` items carry `operationId`, `attempt` and `result`.
The same result descriptor appears in `RunEvent.metadata.tool_result` and
in `DiagnosticEvent(code="tool_result").details`. The diagnostic MUST NOT
contain the raw body, arbitrary metadata or private resource locators.
Live delivery, event replay, thread snapshots and result reads MUST use the
same pure projection. Every completion context (`normal`, `correction`,
`audit`) remains independently addressable.

The descriptor has `kind` (`text/json/image/file/error`), `context`, `preview`,
`byteLength`, `truncated`, `ref`, `resources` and optionally a small `value`
and a read-file `cursor`. Output kind comes from the producer's reserved
`output_type`, never from guessing whether text resembles JSON. Structured
output serialization overwrites caller-supplied reserved type/resource metadata.

A truncated JSON/error result can contain a non-JSON preview. Its original
document belongs to the full-text artifact resource; it MUST NOT be rejected
for having a partial preview, or advertised as an inline full value.
JSON body bytes can also preserve large integer values. Only an inline `value`
must fit the portable canonical JSON number bounds; otherwise it is omitted.

`ref` contains `sessionId`, `turnId`, `operationId`, `attempt`, `toolCallId`,
`seq` and `recordDigest`. The digest is SHA-256 of the record's canonical
encoded bytes. A read MUST verify every field against that exact record.
An admitted child is readable through its root thread only after verifying
the original parent child handle, child creation identity and delivery target.
The host MUST authorize the child as well as the outer thread.
Resource dependency reconstruction MUST use the original admitting root turn's
metadata, including for child results; a later turn's workspace cannot replace
the recorded binding. Current host authorization still applies.

## Limits

| Field | Fixed bound |
| --- | --- |
| Preview | 2,048 UTF-8 bytes, ending at a character boundary |
| Inline value | 8,192 canonical JSON bytes |
| Descriptor | 16,384 canonical JSON bytes |
| Resources | 8 per result |
| Resource name and media type | 256 UTF-8 bytes each |
| Data page | Integer `limit` in 1..65,536; at most 87,384 base64 bytes |
| Response | 98,304 UTF-8 JSON bytes including JSON-RPC envelope |
| Offset and byte counts | JSON-safe nonnegative integer, at most 2^53-1 |
| Resource stream chunk | At most 65,536 bytes; page buffer at most `limit` |

`thread/toolResult/read` takes exactly `threadId`, `ref`, `part`, `offset`
and `limit`. `part` is `content` or an advertised resource ID (`resource:0`,
etc.). It returns `ref`, `kind`, `context`, `part`, `encoding="base64"`,
`data`, `offset`, `nextOffset`, `totalBytes`, `sha256`, `eof`.
Offset equal to the length returns an empty final page; offset beyond it
is invalid. Pages split bytes, including within UTF-8 characters.
File/image content is the public descriptor of its resources, without paths
or remote URLs. Text, JSON and error content is the original recorded body.
An artifact is an explicitly labelled full-text resource; truncated content
is still only the recorded preview. Reads never submit tools or models.

## Workspace retention capability

Retention is opt-in on the workspace backend:
`retain_output(path, expected) -> resource reference | null`,
`open_retained(reference) -> bounded byte chunks`, and
`retained_workspace_id` identify the capability. `expected` binds the owner
(digest of session, turn, operation, attempt), optional expected digest/size,
media type and display name. The private reference stores this owner, workspace
identity, opaque backend locator, digest, byte length, media type and name.
It is persisted in `ToolExecutionResult.metadata.app_server_resources`;
wire resources expose only an ID, status, name, media type, byte length and
digest. Client-supplied paths or locators are never accepted.

Only typed file/image outputs and existing text artifacts are candidates.
The kernel MUST NOT copy arbitrary written files or invent a fallback copy.
Missing capability or a null result gives `not_retained`; preparation failure
gives `unavailable`, preserving the original tool outcome without retrying it.
URL-only images are `not_retained`; the server does not fetch URLs.
Historical file paths without retained metadata are never reopened as snapshots.

Local, Memory and S3 backends implement streamed private exclusive copies
under `.vv-agent/resources/`. Existing immutable text artifacts can be named
directly using their expected digest/size. A versioned backend SHOULD return
its existing immutable version, with no object read or copy at completion.
It MUST pin that version against garbage collection for the receipt lifetime.
Opening a reference MUST reject another workspace/owner and verify the
retained digest and size before returning page bytes. Mutable backends scan
and hash the entire stream while keeping only this page; immutable backends
may use trustworthy version checks. A database alone cannot preserve bytes
held by an ephemeral workspace.

## Authorization and failures

Every page calls `AppServerHost.authorize` for the method and outer thread,
and for the child when applicable. Resource pages also call
`authorize_tool_result_resource` with the verified connection, outer thread,
result reference, workspace backend, owner and retained resource. The default
host permits only that backend's own workspace and the verified owner.
Authorization precedes opening the resource or revealing byte existence.
Refs are locators, never permissions.

| Failure | Code / `data.reason` |
| --- | --- |
| Thread, child or resource denied | -32027 / `permission_denied` |
| Wrong identity, digest, owner or resource ID | -32602 / `invalid_result_ref` |
| Invalid offset or limit | -32602 / `invalid_range` |
| Missing completion record | -32602 / `result_not_found` |
| Retained bytes deleted | -32602 / `resource_missing` |
| Retained size or digest changed | -32602 / `stale_reference` |
| Resource not retained / unavailable | -32602 / `resource_not_retained` |

Absolute paths, parent traversal, symlink escape and references outside the
backend's private area MUST be rejected. A failed retention attempt cannot
grant a read of the current source file.

Producer fixture: `fixtures/app_server_tool_results.json`.
