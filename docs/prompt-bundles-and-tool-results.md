# Prompt Bundles And Bounded Tool Results

Contract `24.0.0` defines one resolved prompt representation, one sparse
bounded-result extension, and the current artifact-backed Message and
microcompaction behavior. These are task-neutral runtime capabilities. They do
not classify a task, choose an answer, decide completion, or change a model's
context/output limits. `.vv-agent/artifacts/` remains a logical,
workspace-relative recovery namespace, and model-facing recovery uses policy-checked `read_file` ranges or
`search_files` patterns through the effective `WorkspaceBackend`.

## Prompt Bundle

A `PromptBundle` is the only structured system-prompt value after instruction
resolution. It contains an ordered, non-empty `sections` array and a
`stable_hash`. Each `PromptSection` is closed and has:

- required `id`, `text`, and boolean `stable`;
- optional non-empty `source`, optional `cache_hint`, and optional object
  `metadata`;
- no empty section text, duplicate section ids, unknown fields, or synthetic
  metadata aliases.

The model-visible flat prompt is derived, never independently persisted: join
section text in array order with exactly `\n\n`. `stable=false` means that the
resolved text is not part of a stable request prefix. It does **not** mean that
a producer is executed per cycle. Instruction callbacks and context providers
are evaluated once while compiling a new run; the resulting immutable bundle is
used by every cycle of that run.

`stable_hash` is the lowercase SHA-256 digest of the RFC 8785 UTF-8 bytes of
the ordered array of stable section objects after omitting absent optional
fields. It is a diagnostic/cache-affinity key, not a provider cache directive.

An `Agent` instruction may resolve to a string or a `PromptBundle`. A string is
normalized to exactly one stable `agent_instructions` section. The compiler
keeps supplied bundle sections in their original order, then appends its own
and provider fragments by the ordering rule in `prompt_bundle.json`. It must
not flatten a bundle and recreate a synthetic `agent_instructions` section.

`AgentTask` and `LlmRequest` carry the bundle as an explicit field. The old
`system_prompt_sections` metadata transport is not a current protocol. Generic
metadata remains host data and cannot alter prompt structure.

## Provider Projection

The runtime records the complete bundle until the provider boundary.

- A provider with explicit system-section cache controls projects ordered text
  blocks and may place breakpoints only according to the canonical stable
  boundary rule.
- A provider without that capability receives one deterministic flattened
  system message. It does not receive invented cache-control fields.

Both projections contain identical concatenated system text. Source, metadata,
and local cache diagnostics are not sent as provider-specific control fields
unless that provider capability explicitly consumes them.

## Run Scope And Resume

Time and every other volatile section are resolved once when a new run is
compiled. They may differ between separately started runs. The opaque definition
in `turn_started.definition` stores `task.prompt_bundle`, not a second flattened
prompt string. Session reconstruction and resume reconstruct the task from that
frozen bundle and must neither invoke instruction/context producers nor read the
clock again.

The frozen logical definition is the object in `run_definition.json`, bound by
turn_started.definition_digest and the current record discriminator. Readers
reject missing, stale, malformed and unknown record versions. `compiled_prompt`, metadata section side channels, and their readers
are not current shapes.

## Bounded Tool Results

The current `vv-agent.tool-execution-result.v4` `ToolExecutionResult` remains
the minimal result with required
`tool_call_id`, `content`, `status_code`, and `directive`. Optional fields are
omitted when absent. A truncated result additionally has:

`status_code` accepts only the current completed-result values. Provider acceptance
retains a handle through op_parked and is not a completed ToolExecutionResult.

- `truncated: true`;
- `truncation_reason` (`output_limit` or `read_limit`);
- `original_bytes` and `visible_bytes`;
- optional `artifact` and optional `cursor`.

There is no empty wrapper and no duplicated `preview` field: `content` is the
bounded model-visible preview. For a truncated result the tool-message
projection appends a compact canonical recovery record containing only the
present truncation fields. This makes an artifact or cursor visible to the
model without expanding ordinary results.

Before recording any non-model completion, the kernel bounds previously
untruncated content to 12,000 Unicode scalar values. This includes product,
dynamic, MCP and built-in tools. A newly bounded preview keeps its first 6,000
characters, a recovery notice, and as many final characters as fit in the remaining
12,000-character budget. The notice has this exact form, including newlines:

```text
\n... {shown} of {total} source characters shown; full text in {path}; read a range with read_file(start_line, end_line) or search with search_files(pattern) ...\n
```

`total` counts the original Unicode scalar values; `shown` counts retained source
characters, excluding the notice. Determine the immutable expected path before
projection, then solve `shown = 12000 - len(notice)` and set
`tail = shown - 6000`. Use decimal counts without separators. For valid artifact
paths the digit count stabilizes deterministically; identical receipt identities
and content produce identical UTF-8 preview bytes. The notice counts toward the
budget. Existing producer-truncated results, including terminal capture previews,
keep their original marker exactly; their appended `vv_agent_recovery` still
provides the typed path. Do not infer truncation from text or insert another marker.
UTF-8 byte counts describe the original and visible text; decode invalid input bytes with
replacement before projection. Already-truncated results keep their preview and
recovery fields. Short results keep exactly their original result bytes with no
new fields.

Every newly bounded result first streams its full text into exclusive immutable
workspace storage. Repeating the same completion uses the same path and verifies
existing size and digest; a different body candidate for the same operation uses a different immutable
path. Kernel receipt archives bind session/turn/operation/attempt AND the source
content SHA-256. For kernel receipt archives the existing owner digest is
SHA-256 of canonical JSON `[session_id, turn_id, operation_id, attempt]`; the
filename suffix is SHA-256 of the UTF-8 string `owner_hex/content_sha256_hex`.
Commit retries and crashes may leave unselected objects; only
the final committed receipt selects a recovery reference. A collision with
invalid bytes is an integrity failure and never replaces the object. General content-digest reuse likewise
verifies the existing bytes. Only after persistence and verification may the
kernel put a successful reference into `op_completed` and compute its result
digest. For a fresh exclusive write, the source already determines expected size
and digest: require the writer's returned byte count to match and, where file
metadata is available, require a file of the same size. Do not reread the newly
written body. A pre-existing object or producer-truncated artifact still requires
a full streaming UTF-8, size and digest check. Storage failure preserves status,
directive and error code: it cannot retry an already completed external effect. The required recovery pointer names
the expected object, while `app_server_resources` marks it `unavailable`; there
is no successful `vv_artifact` entry for a missing or corrupt object.

`metadata.vv_artifact` is reserved for the kernel. Discard or reject producer
values before using them. A successful entry contains exactly the five
`ToolArtifactRef` fields plus `source`, `source_complete` and
`capture_incomplete_reason`. The closed source object contains `operation_id`,
positive integer `attempt`, `tool_call_id` and lowercase `arguments_sha256`
(SHA-256 of canonical JSON arguments). The reference must match the result's
typed artifact, the source must match the admitted operation, and the kernel
must establish the storage evidence described above; existing objects require
actual UTF-8 byte validation against size and digest.
`source_complete=true` requires a null reason; false requires a nonempty reason.
Newly archived receipt text is complete relative to the text received by the
kernel. For an existing producer capture without trusted capture-completeness
evidence, report false with `capture_completeness_unverified`. This includes
terminal captures whose upstream logging may have been capped. A preview limit
alone says nothing about missing source bytes; `output_truncated` must never
stand in for a provider capture-loss signal.

An `artifact` is a closed object with a logical workspace-relative `path`,
`media_type`, `encoding`, `size_bytes`, and lowercase SHA-256 `sha256`. It is
written through the effective `WorkspaceBackend` below the reserved logical
`.vv-agent/artifacts/` root after the originating tool has passed its normal
policy/approval boundary. For a local adapter, that logical namespace maps to
private storage outside the agent shell's working directory; shell commands
cannot read, replace, delete, or mutate those bytes through a host path. The
model never selects the artifact path. Recovery uses the existing
policy-checked `read_file` and `search_files` tools, which resolve the logical
path through the backend; there is no artifact bypass API.

The canonical host `Message` may carry the same object as optional
`artifact_ref: ToolArtifactRef`. The field is omitted when absent and survives
session record, result and frozen-definition round-trips. It is host-only: every provider/model message projection removes
`artifact_ref` without changing `content`.

For terminal output, `WorkspaceBackend.write_text_chunks_exclusive` is the
current producer boundary. It consumes normalized UTF-8 text chunks, performs
an atomic exclusive write, and returns the written UTF-8 byte count. A terminal
producer first derives its bounded preview, then streams the complete capture
through this boundary only when truncation occurred; it does not materialize
the complete terminal output in application memory. Local adapters map the
logical artifact path to private storage, while other backends provide the same
exclusive streaming semantics in their own storage domain.

A `cursor` is a closed object with `kind`, `path`, `offset_chars`, and source
`sha256`. `read_file` accepts the same cursor together with its required path,
verifies the digest before reading, and returns the next bounded slice. The
offset unit is Unicode scalar values. A changed source fails with the stable
`stale_cursor` error rather than returning a mixed-version slice.

`bash` preserves the complete terminal output as an artifact when it exceeds
the 12,000-character preview limit. The preview is deterministic head/tail
text, not a first-only slice. `read_file` returns a bounded slice plus cursor
instead of `content: null`; a single oversized line is therefore recoverable.
All sparse result fields survive tool messages, cycle records, AgentResult,
operation receipts, terminal projections and strict readers.

## Searching a retained artifact

At the built-in `search_files` entry point, recognize the reserved artifact
namespace before validating directory options or choosing a workspace discovery
backend. An explicit artifact target searches that one object; `glob`, `type`,
hidden-file and ignored-directory discovery settings cannot exclude it. Do not
list the artifact directory or run a subprocess against a host/container path.

Accept only a canonical relative single-file reference produced in that namespace:
one task segment and one text object filename. Reject directories, wildcards,
parent traversal, aliases such as `./`, backslashes, extra path segments and other
suffixes with `artifact_search_denied`. The task segment must equal either the current task's canonical artifact segment
or the canonical segment of `session/<current session id>/<current SDK task id>`,
not a prefix. The latter is the logical scope used by compaction. Other sessions
and tasks remain denied. The trusted runtime supplies both session and SDK task
identity; a host task id does not replace the SDK task inside a compaction scope.
Apply this same rule to model-facing read_file and file_info before storage access.
It does not authorize inherited artifacts from another turn or session. Use the same trusted task identity
as completion storage: a host-scoped backend task_id when supplied, otherwise
the execution context task_id (the SDK turn identity). The model cannot select
that identity.
Reject another task before storage access. Missing objects, unreadable objects
and invalid UTF-8 fail with `artifact_unavailable`. Host authorization still runs
through the effective backend; a matching task segment does not grant account or
organization permission.

### Task-scope identity encoding

ASCII task ids matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` stay literal unless
they start with reserved `s-`. Every other task id is encoded as `s-` plus the
first 62 lowercase SHA-256 hex characters of canonical JSON `["task", id]`.
Compaction uses the same prefix and digest length with canonical JSON
`["session", session_id, SDK_task_id]`. The type tag separates identity domains;
JSON preserves component boundaries. Tool-call filename sanitization is unchanged.
Producers and authorization use the same rule. Old lossy compaction paths are
not authorized; stored references and objects are not rewritten.

The host-facing scope predicate accepts a path and trusted task_id, with optional
session_id and session_task_id when the SDK task differs from the host task.
It checks scope and canonical filename; host ACLs, availability and integrity
checks remain required.

Decode byte chunks incrementally so UTF-8 characters split across reads remain
whole. Match complete logical lines, carrying unfinished lines across chunks;
strip a terminal CR before LF. Regexes match individual lines, including the last
line without LF. Preserve smart-case, explicit case and literal options, and the
content/files_with_matches/count output modes. `multiline=true` and malformed
regexes return `invalid_arguments`. Content results always identify real artifact
line numbers, regardless of a preview marker or the display flag. End every
successful response with exactly:

```text
Artifact line numbers can be used directly with read_file start_line/end_line.
```

Use the existing search budgets of 500 rendered lines and 30,000 characters,
including notices. Scan long logical lines in windows of 30,000 characters with
4,096 characters of overlap. Never discard a whole line without matching it.
Report one-based line numbers and zero-based Unicode character columns. Keep
only bounded match-centered excerpts (at most 200 source characters each), window
state and a bounded result page. A column is directly usable as read_file
start_char at the same start_line. Do not count overlap matches twice.

Report windowed scanning explicitly: identify the first oversized line and the
4,096-character overlap limit; wider matches and boundary-sensitive lookaround
can be incomplete. Never interpret an internal window edge as a real line start
or end for ordinary ^/$ patterns. The result is incomplete even when it contains
hits, and must not claim an exhaustive no-match result. Output limits likewise
suggest narrowing the pattern or paginating with offset/head_limit; offset counts matches, including multiple hits on one line. A zero
head_limit removes that optional limit, not the hard budgets. Context-line
expansion is not part of artifact search.

All model-controlled matching must be forcibly interruptible: content regexes,
file globs and child workspace exclude_files_pattern. Each regex engine call
(finditer, match or search over one line, window or whole text) has its own
250 ms interruptible engine timeout. A finditer invocation shares that timeout
across its iteration; yielding another match does not reset it. Independently,
share a cumulative 10 s thread CPU budget across file enumeration and all matching
within a request, including nested globs and exclusion filters. Storage I/O wait
is not charged as thread CPU. Check the shared deadline inside enumeration loops,
including empty pages/directories, before advancing traversal. Each engine call
receives the smaller of 250 ms and the remaining request budget.
Exhaustion is an explicit error or incomplete result, never an ordinary empty list
or no-match result. A content search retains earlier hits and the stopping
line/character position. A single slow engine invocation reports
"Regular expression too slow; aborted"; total CPU exhaustion reports
"Search total CPU limit exceeded (10 s); aborted". Discovery errors identify file
enumeration. The same rules apply to Local, Memory and S3 workspaces, artifact
search, find_files/globs and child exclusion filters. Reject reverse
matching modes explicitly. Literal, smart-case and inline (?i) remain available.
Word matching includes combining marks: \w+ matches all of `a\u0301b`, \b has
boundaries only at its ends, and \W does not match the combining mark. Under
case-insensitive matching, `i` does not match dotless `ı`. These rules apply to
artifact search and the portable workspace content matcher. Native search
backends keep their documented engine semantics.

read_file accepts start_char (default 0) within start_line alongside a line
range. Each page reads at most 12,000 characters, including displayed line
numbers. start_char and line ranges cannot accompany a cursor. Scan and validate
the source as a stream even when skipping a very long prefix; memory must not
grow with line length. Whenever another selected character remains, return
metadata.read_page with next_line and next_start_char, including cursor-based
calls. Put the next-page notice in the result body before computing visible_bytes
and original_bytes. Projecting a tool message must preserve that body verbatim.
Continue with the returned digest-bound cursor; manual positioning uses both
next_line and next_start_char. Columns and offsets count Unicode characters,
not UTF-8 bytes; exclude a leading BOM in both search and read coordinates.
A partial read cannot establish a full edit baseline.

Searching does not mutate the source, write storage objects or issue recovery
references. Its ordinary textual result still goes through the same completion
projection as every tool: a result longer than 12,000 characters is retained and
bounded there. There is no search-specific projection exemption. Backends must
supply chunk reads to establish a storage-level memory bound; a legacy whole-byte
read fallback is not proof of streaming behavior for that backend.

## Archive-Backed Microcompaction

Proactive microcompaction operates on old tool-result messages without
inspecting the task or parsing the result body. Every built-in and custom tool
uses the same default `result_retention=archive`; a tool may explicitly declare
`preserve` when its result must remain inline until full or emergency
compaction.

`MicrocompactionPolicy` is a public, closed value with
`trigger_ratio`, `target_ratio`, `keep_recent_cycles`, and
`min_result_chars`. It is configured through `RunConfig`, copied explicitly to
`AgentTask`, and frozen in the task runtime controls in the
frozen run definition. Generic metadata is not a policy transport. The default
policy is `0.75`, `0.60`, `3`, and `500`; `0 < target_ratio < trigger_ratio <=
1`. Ratios must be finite numbers. `keep_recent_cycles` is an integer in
`0..4294967295`, while `min_result_chars` is an integer in
`1..4294967295`. Booleans, null, float-encoded integers, missing or unknown
fields, non-finite host values, and out-of-range values are invalid.

Microcompaction is planned before it mutates messages. For a
`micro_threshold` trigger, it starts only when effective prompt usage crosses
the configured trigger and at least one old result passes the age,
minimum-size, and retention controls. The planner processes oldest candidates
as one ordered eligibility pool. Planner estimates select work but never
satisfy the target. After each successful replacement, the application pass
subtracts the actual replacement-message token count from the actual original
message token count, recalculates post-replacement usage, and stops only when
that usage is at or below the configured target or eligible candidates are
exhausted. Keeping later eligible candidates in the same plan lets persistence
failure fall through to another candidate without planning twice. A cycle
performs one planning/application pass. A
micro-threshold crossing with no eligible candidate does not emit
`memory_compact_started` or `memory_compact_completed`; full-threshold and
prompt-too-long compaction may still start without a micro candidate.

Before replacement, complete result text is persisted through the effective
`WorkspaceBackend` under the immutable logical `.vv-agent/artifacts/`
namespace. Persistence failure leaves the original message unchanged and does
not prevent later selected candidates from being attempted.
Already-truncated results reuse their existing artifact when one is available.
Reuse first reads the persisted content through the effective workspace
backend and verifies its UTF-8 byte length against `size_bytes` and lowercase
SHA-256 against `sha256`. A read, size, or hash mismatch leaves the original
message unchanged, as does a new persistence failure. The replacement is
intentionally small and model-visible:

```text
<Tool Result Compact>
tool_name: web_search
artifact_path: .vv-agent/artifacts/run/call.txt
retrieval_hint: use read_file on artifact_path if needed
excerpt:
...
</Tool Result Compact>
```

The marker must not expose byte counts, character counts, hashes, storage
metadata, or other bookkeeping. Integrity metadata remains on the typed
artifact reference outside the model projection. `read_file` and `search_files` are the model-facing recovery tools.

## Summary And Recovery Projection

Contract `24.0.0` uses the history-preserving pipeline in
`parity-contract.md#history-preserving-compaction`. Microcompaction is the only
pruner. Relative transcript age and an atomic raw tail protect recent calls;
no image or tool-call skeleton is stripped to fit a threshold. Summary input
contains the complete removed prefix and the prior summary; acceptance is the
only boundary that permits their replacement. Exact messages and projections
are in `memory_local.json#summary_compaction` and `session_codec.json`.

The canonical localized templates preserve their full production schema and
rules, replacing only the history section with JCS previous-summary and prefix
payloads. Model JSON is tolerantly extracted and normalized before its effective
content is checked; closed summary fields constrain framework writes, while
host evidence and persistence integrity boundaries remain strict.

Summary metadata retains complete typed artifacts and cursors across repeated
summaries. Its path list is deterministic, requires the policy-checked recovery
surface, and does not perform automatic file restoration. Session record
projection preserves that metadata, while provider projection strips the reserved
`_vv_agent_compaction` item. Hashes and byte counts are not rendered into summary
text. This does not change ordinary bounded tool-result recovery envelopes.

## Tool Surface

Only `direct` and `hidden` are current `ToolExposure` values. `direct` is
eligible for the model-visible schema subject to normal policy; `hidden` is
not model-visible but may be invoked by trusted host/runtime code.
The model-visible `compress_memory` tool and its `memory_notes` state are also
removed. Framework-owned proactive, micro, summary, and recovery compaction
remain internal behavior and do not expose a replacement model tool.

## Required Producer Evidence

Required implementations must prove real producer paths for:

1. bundle order, stable hash, flattening, and explicit provider projection;
2. one run's fixed time, a new run's independently resolved time, and unchanged
   time after session resume;
3. strict rejection of stale prompt/record wires and no metadata
   section side channel;
4. bounded foreground/background bash recovery, read-file cursor recovery,
   stale-cursor rejection, and session record serialization;
5. candidate-aware archive-backed microcompaction for built-in and custom
   tools, `preserve` retention, persistence and artifact-integrity failure
   safety, actual-token target application, compact marker shape, and one pass
   per cycle;
6. no model-visible `compress_memory`, no `memory_notes`, and no `deferred`
   exposure value while internal compaction remains covered.

## Terminal retention failure

When output reading or storage fails after a command has run, preserve its
confirmed process status, exit code, tool status, directive and bounded preview.
Return metadata.retention = {"status":"unavailable",
"reason":"artifact_persist_failed"} and a bounded notice that complete text
could not be saved. Include no artifact or cursor recovery pointer and no
successful vv_artifact provenance for missing output. Never turn output
unavailability into a command error or repeat the command. A later check may
retry retaining the existing capture. Existing partial objects remain immutable.
