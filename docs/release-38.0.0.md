# Contract 38.0.0

This unpublished major release covers yieldable observations in the SQL session
kernel and L1 lease lock ordering. Python 0.35.0 is the required implementation;
publication, immutable lock/snapshot and central adoption remain pending.

A host may declare foreground child or Accepted provider waits yieldable on
steer. Eligible receipts, steering and inbox consumption commit atomically.
Children continue and later terminals follow background notification rules.
Yielded provider handles close without query/cancel; later authenticated inputs
are audit-only. Read-only yield callbacks may observe host state; verified child
terminal results and references are provided. Invalid results fall back to the
marked default; replay reuses the committed receipt. Files stay on the host's
existing delivery path. See [yieldable waits](yieldable-waits.md).

Optional closed fields extend op_parked, op_completed and provider_evidence.
Old strict readers reject those fields, including embedded acceptance inputs
before park commit. Record 1, inbox 3, SQL layouts, RunEvent v6 and App Server v5
remain unchanged. Existing undeclared sessions remain readable. Route sessions
containing new fields, including finished sessions, to Python 0.35.0 or newer;
do not strip retained fields to downgrade. No SQL migration is required.

New long-result candidates bind operation owner and content SHA-256; only the
committed candidate is selected. Existing references and receipt bytes remain
authoritative. The real producers generate yield, codec, event, archive and
App Server evidence; fixture bytes alone do not establish adoption.

L1 serializes lease renewal/publication and rejects same-latch, same-thread
synchronous poll reentry across commit/renewal lock ownership. It introduces no
connection checkout, transaction borrowing or new admission/hook signature.

## Known limitations

- Local App Server, Interactive and Runner accept declarations but do not yield.
  They await real results, defer steer and do not invoke on_yield. App Server can
  project retained SQL-produced yields without implementing local yielding.
- Each admission atomic unit and its host writes must share one real transaction.
  Hosts exclusively own a shared raw connection. Concurrent native transactions
  on that connection are unsupported and detection is not promised.
- A whole drive/poll must not run inside a host outer write transaction.
- L2–L5 remain unfixed: cleanup evidence/full handoff after stop, control-token
  lifetime, opaque deadline start, and SQLite busy classification.
- Frozen Rust 23.0.0 / 0.21.x does not support yielding; its verified baseline
  00f4240786f1adea1dc0c4730da8ddd06a5ab8ac is unchanged.
