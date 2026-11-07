# Contract 37.0.0

Input protection changes compaction and replay behavior, so this is a major
release under the observable-behavior version policy. New session creation
freezes the choice in the closed seed object. Old sessions without it retain
their prior behavior. Python 0.33.3 rejects new declarations when decoding creation, reading from the
start or restoring sessions. Hosts must route paged, inbox and raw JSON readers
themselves. An undeclared old parent that creates a new-format child (including
false) must keep both sides of execution, cancellation and result delivery on the
new runtime; rollback cannot inspect the parent creation record alone. Record 1, inbox 3, SQL 3, events and App Server v5
remain unchanged; there is no store-wide schema boundary.

The rules, errors and producer evidence are described in
[input protection](unseen-input-protection.md) and
[model completion](model-completion.md). Python adoption targets 0.34.0;
publication, lock/snapshot synchronization, full implementation gates and
central adoption remain pending. Rust stays frozen and unsupported for this
feature at its verified 23.0.0 / 0.21.x baseline.

Model completion now uses final vv-llm >=0.10.1 evidence. New sessions freeze
`response_rejection=true`: content filtering and refusal without answer text
fail with HTTP 200 model_request_rejected and a safe descriptor. Hosts must close
or replace temporary streamed text; rejected partial output is not history.
Refusal text with no content becomes the assistant answer. Missing termination
EOF is Unknown with existing retries; degraded observation preserves behavior.
Old sessions remain readable and continuable by 0.33.3; declared sessions and
derived dependents stay on the new runtime. No store schema bump.

Declared input protection uses one committed-prefix message projection, including
normal callbacks after snapshots. Retained original tool groups preserve their
operation provenance through replacement regardless of current protection.
App Server creation races reuse the frozen baseline through transaction replay.
Native child correction remains a generic receipt rule that normal native-child
execution currently cannot reach; provider correction evidence is separate.
