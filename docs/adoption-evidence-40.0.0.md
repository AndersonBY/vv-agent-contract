# Contract 40 producer capture evidence

Status: local producer capture; central adoption remains pending.

This evidence is for canonical contract 40.0.0 producer fixtures. It does not
verify a published release or change the frozen Rust baseline.

## Producer source

| Fact | Value |
| --- | --- |
| Python repository | `https://github.com/AndersonBY/vv-agent` |
| Python branch | `feat/trusted-storage-s1-python` |
| Python `HEAD` | `3f4d87374ce27d2abf3fc23421f20f766aee16a5` |
| Worktree state | dirty; uncommitted implementation is required for the capture |
| Relevant source-tree SHA-256 | `8127023fa691ba1c6a8416d80d4aba0b1bf9253d27593bed0c161607f058bc14` |
| Capture command | `uv run python scripts/record_codec_fixtures.py --output <diagnostics.json> --trusted-output <trusted_storage_s1.json>` |
| Capture determinism | two independent runs produced byte-identical diagnostics and trusted fixtures |

The source-tree digest covers `src/vv_agent`,
`scripts/record_codec_fixtures.py`, and `scripts/s1_fixture_values.py`.
The recorded revision is provenance, not an immutable adoption revision, because
the producer worktree remains dirty.

## Byte evidence

`fixtures/trusted_storage_s1.json` was decoded and re-encoded through the current
Python producers. Every accepted case carries the logical wire value, canonical
bytes, SHA-256, byte count, producer symbol and every ContentRef path. Contract
validation independently checks those facts and rejects the 26 negative cases.

| Case | Kind | Bytes | SHA-256 | ContentRefs |
| --- | --- | ---: | --- | ---: |
| `session_created_principal_and_content_ref` | `session_created` | 1184 | `a70b4eb83c368e3e35be4d236f95d042c217e19b9755567adb651cffa1603e61` | 3 |
| `turn_started_requirements_policy_and_environment` | `turn_started` | 2288 | `b21df63619d93cebd6d356455d9bbe25fba330138e05ab7659498dc819cf66fb` | 4 |
| `signed_user_inbox_admission_proof` | `user` | 923 | `1c3e817803479786e65db0e3773a58207ce7607705b5f796cacdefc7e9fe18ff` | 2 |
| `input_applied_copied_input_proof` | `input_applied` | 1470 | `e0fa0911eae7c778a3279ee549cc654dc23a6dee317d83bcb724b84af2ce367d` | 2 |
| `policy_usage_and_tokenizer_projection` | `op_completed` | 1936 | `f994e1b44d9bc1b078bb8bc27d27214cfd305654900854a8ab29930828010b59` | 3 |
| `op_planned_policy_projection` | `op_planned` | 1266 | `694d299671a6006833afa3a0503f09f471ecb62098b537bb344a534b7e9773e5` | 2 |
| `op_prepared_policy_projection` | `op_prepared` | 1472 | `f3470953fd32fec994d9a571cbecc382abf029eb0d9180905fd2fab45089bac9` | 3 |
| `approval_answer_policy_projection` | `approval_answer` | 1779 | `729588020fdfe045c41b39db06d851d8260b41a047c7dd31464da718f86872b5` | 4 |
| `provider_evidence_content_ref` | `provider_evidence` | 2067 | `c9c183bb44cd417826c17a670d48836d062e924e0c87ce4fe28de6b7827f4c60` | 5 |
| `boundary_event_content_ref` | `boundary_recorded` | 647 | `022ee897c920ce2ff076228e738c06a958ecb28ee99859da43be3c6cf891ef88` | 1 |

The trusted fixture SHA-256 is
`b0b0a53286cca9907051430f445894e5a0113b72130adb515798e389dd125f34`.
The generated fixture manifest SHA-256 is
`5d9f3059ce0a5e6c21ea67ac4adcf84a3bc799ea0bd407673a3a9ce81cfe29b0`.

## Gate evidence

The following checks passed on this local evidence:

- `python3 scripts/contractctl.py manifest`
- `python3 scripts/contractctl.py validate`
- `node scripts/verify_jcs.mjs`
- `python3 -m unittest discover -s tests` (112 tests)
- two deterministic contract builds with byte-identical output
- focused Python producer, schema and S1 content tests (102 tests)
- Python ruff check/format and repository contract checks

The immutable published snapshot lock still points to the allocation-only fixture
hash, and `support-matrix.json` remains `pending-adoption`. Those checks must stay
closed until the review commits are immutable, the contract release artifact is
published, the Python lock and vendored snapshot are synchronized to that
artifact, and the cross-repository GitHub workflow records the exact producer
revision.
