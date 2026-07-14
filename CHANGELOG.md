# Changelog

All notable language-neutral contract changes are recorded here. Contract
versions follow the compatibility policy in `docs/compatibility-policy.md`.

## 0.2.0 - 2026-07-15

- Add a provider-neutral cache-usage observation to token accounting while
  preserving the existing numeric token fields as compatibility projections.
- Distinguish provider-reported zero cache reads from missing accounting and
  explicit adapter-declared lack of cache support.
- Mark token totals as provider-reported, estimated, or unavailable, and
  define conservative aggregation that never presents a partial cache total
  as complete.
- Add canonical normalization and aggregation cases for OpenAI-compatible,
  Anthropic, normalized provider bridges, estimated, missing, unsupported,
  explicit-zero, and invalid cache usage.

## 0.1.0 - 2026-07-13

- Establish the first independent canonical contract for `vv-agent` and
  `vv-agent-rs`.
- Import 34 canonical fixtures covering prompts, built-in tools, public SDK
  capabilities, runtime events, sessions, delegation, App Server, memory, and
  distributed execution.
- Add deterministic validation, release bundles, implementation lock files,
  vendored snapshot checks, adoption automation, and cross-repository gates.
