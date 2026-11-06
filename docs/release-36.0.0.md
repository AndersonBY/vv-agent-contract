# Contract 36.0.0

The provider saying “wait for a token quota” must not start context compaction.
Generic input-size wording now checks for time windows and quota in the same
text. A 429 needs an explicit context marker from the narrower allowlist.
Explicit non-429 context-size errors still compact even when quota is mentioned.
The complete rules and examples live in [model rejection](model-rejection.md).

The previous published classifier returned different receipts and retry paths.
The [version policy](versioning-policy.md#3600-context-and-quota-classification-correction)
therefore requires 36.0.0 rather than an evidence-only 35.0.1 patch.

Record 1, inbox 3, SQL 3, RunEvent v6, App Server v5 and frozen definitions
are unchanged. No store conversion is needed and old receipts are not rewritten.
Hosts should drain drivers before switching classifiers so all workers use the
same retry rules. This change does not settle historical Unknown outcomes.

Python 0.33.3 implements the new rules. Until publication, local producer gates
select this checkout using VV_AGENT_CONTRACT_SOURCE; they do not establish
immutable snapshot adoption or central verification. The matrix remains
pending-adoption. Rust retains its entire frozen 23.0.0 / 0.21.x baseline.
