# Language-neutral parity contract

Contract 24.0.0 has one execution authority: the [session kernel](session-kernel.md)
log/inbox. Observable public behavior is language-neutral; symbol spellings are
adaptation mappings. Python is the only required implementation. Rust remains
frozen at its verified contract 23.0.0 / 0.21.x baseline and does not adopt v24.
Matching schemas or fixture bytes alone do not establish real-producer parity.

## Domains

The current domain IDs in contract.json are system-prompt,
built-in-tool-specification, agent-and-model-resolution,
function-tool-and-agent-as-tool, background-agent-task, handoff, workspace,
session-kernel, configured-sub-agents, run-handle-and-live-control,
events-and-tracing, tool-orchestrator, memory-and-compaction,
guardrails-hooks-results, app-server, token-usage-and-cache-accounting,
cli-examples-and-docs and public-evidence-closure.

Public execution through Runner, configured/interactive facades, CLI and App Server
uses the same kernel. Runner.resume selects explicit session_id/turn_id or an
AgentSession; there is no independent execution-state wrapper or public second
engine. Public names and behavior are in `public_api.json`; store constructor and
transaction signatures are implementation-local. Importing the SDK cannot require
optional PostgreSQL client dependencies.

## Tools, content and completion

The built-in manifest has 15 direct tools. ToolExposure is direct/hidden. Names,
descriptions, order, schemas and exact behavioral inputs/results in
`builtin_tools.json` and `builtin_tool_behavior.json` are canonical. Successful
edit_file returns exactly ok/path/replaced_count and changed_files/operation/
line_ending metadata. Exact matching, baseline refresh, explicit replace_all,
UTF-8 BOM and CRLF preservation apply to partial reads and consecutive large-file
edits; no diff generation is required.

Opaque user text, prompts, arguments, results and explicit JSON content maps are
preserved. No field-name or credential-like-text classification rewrites content.
Platform credentials stay configuration-only. Size limits, authorization, strict
schemas, digests and fencing remain independent checks.

NoToolPolicy is continue/wait_user/finish with precedence per-run, Runner default,
Agent then framework finish. It observes mechanical tool presence only. Normal
no-tool completion preserves assistant content, subject to hooks/output validation.
Same-turn user/approval waits are nonterminal; replies target retained interaction
and generation. Cancellation and abort commit durable closure with concrete
unconfirmed operation evidence. Typed completion reasons and sparse terminal
fields remain in `completion_policy.json` and `result_public.json`; business
acceptance remains a host decision.

All tool arguments pass Draft 2020-12 parameter validation before predicates,
approval, dispatch and effects. Closed results retain one typed status_code.
A parked provider handle is not a completed result. Every completed result,
including ERROR, retains its complete strict wire and digest. Tool timeout warns
that side effects may continue and is retryable=false; it cannot assert confirmed
stop. Sparse artifacts/cursors and policy-checked read_file recovery follow
[prompt bundles and tool results](prompt-bundles-and-tool-results.md).

## Execution, budgets and observability

Frozen definitions bind prompts, model endpoints, policies, budgets, host names
and child descriptors before admission. Prepared and completed receipts are reused
without callbacks, model calls or effects. Unknown outcomes retain evidence;
provider authenticity precedes adoption and ended turns never revive. Whole-batch
reservation, all primary/internal attempt accounting and unavailable active wall
intervals follow [run budgets](run-budgets.md) and
[model-call accounting](model-call-accounting.md).

Delegation uses one child-session admission/delivery mechanism, including configured
children, Agent.as_tool, background tasks and handoff. Child WAIT_USER cannot
complete a parent; parent adoption requires authenticated original terminal.
Handoff limits come from admitted records. Durable state is JSON; required
host-local objects are explicitly re-supplied and MissingHostBinding fails before
execution. Creation seed is the sole bootstrap history/state mechanism.

RunEvent v6, model-call v2, task-token-usage v3 and TokenUsage v1 are current strict
wires. Events/results/transcripts are consistent-prefix projections. Events are
at least once with stable identity; deltas are volatile and trace is ACK-first,
at most once. [Session consumers](session-consumers.md) and
[typed events](stream-events.md) own these boundaries. JSON-RPC v2, unified thread
status, retained approval owner/deadline, safe interaction projection and closed
execution rejection are defined in [App Server](session-kernel.md#app-server).

## History-Preserving Compaction



Contract `24.0.0` permits one archive-backed microcompaction pass and then an
accepted summary of a complete historical prefix. Without an accepted summary,
no content-bearing message, image, reasoning, or tool-call/result skeleton may
be removed. Only a completely empty assistant may be filtered. Microcompaction
replaces eligible result bodies after verified persistence and preserves call
ids, arguments, result associations and typed references. Its age is relative
to assistant turns in the current transcript, excluding framework summaries;
an absolute runtime cycle cannot make a retained recent turn old. There is no
second pruner, processed-image stripping, orphan cleanup, or assistant collapse
in the compaction pipeline. Resume sanitization remains a separate boundary.

`keep_recent_messages` (default 10, including the existing
`memory_keep_recent_messages` runtime projection) counts raw messages after
excluding system messages and framework summaries. A cut inside an assistant
`tool_calls` plus its immediately following results moves left to that
assistant. All results must occur exactly once, in call order, within that
block; ids may be reused in a later block. Non-tool messages after the result
batch, including image notifications and steering messages, are independent
messages. An incomplete final block (no results or only the ordered initial
subset) stays in the raw tail as-is; move the cut left to its assistant if needed.
Missing results in the middle, duplicates and out-of-order results still abort
compaction without deleting or repairing messages. Preserve system messages verbatim and
in order. The selected raw tail is protected from pruning in a planned summary;
force goes directly to summarization. Below-threshold returns may retain safe
microcompaction changes, but never discard pairs without a summary.

The summary input has separate `Previous Summary` and `Conversation Prefix`
sections. The latter contains every removed raw message, complete calls,
arguments, and results (including valid compact markers). Old summaries and
manifests stay until replacement is accepted. No event limit truncates this
input; archived originals are not automatically rehydrated. An image message in
the prefix is projected as text with content exactly
`[image omitted from summary input: <content or image>]`: use its verbatim
nonempty content, or the literal `image` when empty, and omit `image_url`.
Never send image payloads to the text-only summary route (`summary_accepts_images`
remains false). Images do not move the cut; raw-tail images stay unchanged.
Original prefix image messages leave context only when that summary is accepted;
rejection retains them with their payloads.
An input window too small fails without chunking or dropping input.

The localized `zh-CN` and `en-US` prompt templates in
`memory_local.json#summary_compaction.prompt_templates` are canonical. Preserve
the production instruction text, full JSON schema, analysis instruction,
JSON-only rule, verbatim-original-request rule and progress event bound. Only
the history section changes to the two sections above. Render their payloads
as JCS and substitute the three declared placeholders in one pass: literal
placeholder text inside history must never be reinterpreted. Preserve the
trailing newline, clamp `event_limit` to at least one, default to `zh-CN`, and
use `en-US` for other language values. The `old_tool_pairs_rendered_prompt`
case fixes the complete rendered bytes in both languages.

Model output is untrusted text to extract and normalize, not a strict stored
wire object. Strip an outer code fence and case-insensitive `<analysis>`
blocks, unwrap a supported `<summary>` wrapper, then scan for the first JSON
object using raw decoding; surrounding prose is tolerated. Apply these rules
before deciding whether the model provided effective content:

- Drop unknown top-level and nested record fields.
- Fill each missing or wrong-typed top-level field with its canonical empty
  value (`[]` or `""`), without coercing numbers or other values to strings.
  A string-list field containing any non-string element becomes `[]`.
- Always write `summary_version="2.0"`, ignoring the model's version or its
  absence. `summary_required_fields`, field types and
  `written_summary_objects_closed` describe framework output only.
- A non-array record field becomes `[]`. Within an array, discard malformed
  records individually. File records require a nonblank string `path` and an
  `action` from the existing enum; error/fix records require a string `error`.
  Missing or wrong-typed descriptive strings (`summary`, `fix`, `file`) become
  `""`. Drop unknown nested fields and preserve the order of surviving records
  and the original bytes of valid string values. Do not discard other records
  because one record is malformed.
- The normalized object has effective content only if at least one of
  `original_user_messages`, `decisions`, `files_examined_or_modified`,
  `errors_and_fixes`, `progress`, `key_facts`, `open_issues`, `next_steps` is
  nonempty, or `current_work_state` is nonempty. `user_constraints` alone and
  the version do not qualify. Evaluate this before framework file-path and
  evidence merging so those deterministic additions cannot authorize a lossy
  fallback.

No extractable object, a raised/absent callback, or no effective normalized
content keeps the safely pruned complete history. The existing structural
checks still apply: invalid blocks, input-window limits, manifest/context budget, final recovery-surface availability and an
actual token reduction. Harmless unknown fields, incomplete schemas, wrong
field types or a wrong model-supplied version do not by themselves reject a
summary. Local helpers cannot authorize replacement. Cancellation, budget
exhaustion, unknown-operation control and integrity errors propagate. Strict stored
Message, evidence-manifest and record validation is unchanged.

An accepted result is original system messages, one
`user(name="memory_summary")`, then the unchanged raw tail. The summary content
contains `Original User Request`, `Compressed Agent Memory`, and
`Persisted Artifacts` sections in that order, as frozen by the exact examples.
The first section joins original requests with two newlines; the second is
RFC 8785 JSON. The evidence section exists even when empty. A valid summary
must cover all removed pairs by input inclusion, acceptance, and deterministic
reference preservation; no per-tool semantic coverage protocol is implied.

`Message.metadata._vv_agent_compaction` is a reserved closed object with both
`artifacts` and `cursors` arrays, even when empty. Closed records contain
`tool_call_id`, `tool_name`, RFC 8785 object-string `arguments`, and respectively
`artifact_ref: ToolArtifactRef` or `cursor: ToolResultCursor`. Reuse current
strict nested shapes. Collect ordinary typed artifact references as well as
validated recovery envelopes. Merge previous manifests first, then removed
prefix blocks in transcript order; deduplicate complete canonical records
within each list, retaining the first occurrence. Never deduplicate by call id
alone and never truncate references to fit a budget.

The model-visible evidence section renders the fixture's path/argument lines;
hashes and byte counts stay in metadata. A cursor line exposes path and offset,
while the complete validated cursor survives for host recovery. It introduces
no new tool input or automatic cursor injection: models can use the normal
policy-checked `read_file` path. Ordinary provider projection removes this
reserved metadata item, omits an empty metadata container, and preserves
unrelated metadata under its existing projection rules. Strict host/session
readers validate the reserved object. The final recovery-surface
check after `before_llm` includes summary evidence, not only tool markers.

File references use `files_examined_or_modified`, merging known file operations
from the removed prefix by path in first-seen order. Accepted-summary entries
come first, then prior-summary entries, then known prefix file operations;
append unseen paths without overwriting earlier entries. The exact tool/action
mapping and description templates are in `summary_compaction.file_path_collection`. Do not perform automatic exists/stat/read calls
or inject current file contents. `restore_key_files`,
`PostCompactRestoreConfig`, their exports, and MemoryManager fields
`tool_result_compact_threshold`, `tool_result_keep_last`,
`tool_calls_keep_last`, `assistant_no_tool_keep_last`, and `workspace` are
removed, including runtime metadata readers; there are no aliases. Session
Memory's own storage configuration remains independent. The standalone local
summary and JSON extraction helper fixtures do not prove manager acceptance.

Emergency compaction uses the same process with tail target
`max(1, floor(keep_recent_messages * (1 - clamp(drop_ratio, 0, 0.95))))`.
Further-removed raw messages enter the new summary input alongside the prior
summary. No successful shrink means unchanged history and the existing
`CompactionExhaustedError` at the PTL exhaustion boundary. `structural` events
mean only information-preserving cleanup/warnings; `summary` and `emergency`
mean accepted summaries with normal and smaller tail targets. Session Memory
`on_compaction` runs only after accepted replacement; its token baseline
includes the new summary and tail, while the running system prompt stays
frozen. `result_retention=preserve` blocks pruning but permits accepted summary
replacement. Public compact/emergency/microcompact method signatures and the
four-field MicrocompactionPolicy remain unchanged.


## Messages and sessions

Message roles, tool-call association, metadata and artifact_ref are strict current
wire values in `session_codec.json`. artifact_ref is host-only and survives record,
result and frozen-definition projection; provider projection removes it. Complete
assistant tool-call/result blocks are kept in matching order. Orphan, duplicate,
empty-ID or mismatched blocks are excluded before a request. Reasoning-only
assistant messages are valid; fully empty assistants are removed.
Transcript items are read-only record projections, not append-once execution
storage. History and JSON state bootstrap via attributes.seed before the first
turn; admitted inbox items own subsequent changes. Original terminal results stop
at their original prefix even after later turns.

## Allowed adaptations and evidence

Allowed adaptations are symbol naming, Python Path versus Rust PathBuf,
exceptions versus typed errors, sync/async facade spelling and idiomatic provider
construction. They cannot add defaults, fallback, readers or capabilities. SQL,
connections, caches, threads and store signatures remain implementation-local.

Required adoption proves strict readers, real producers, snapshot locks, focused
and full quality gates, applicable SQLite and PostgreSQL failure cuts and central
cross-repository CI. Frozen Rust evidence remains scoped to its pinned release.
Publishing is pending adoption until those gates pass; see
[change workflow](change-workflow.md) and [version policy](versioning-policy.md).
