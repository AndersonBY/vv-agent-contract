# Changelog

All notable language-neutral contract changes are recorded here. Contract
versions follow the compatibility policy in `docs/compatibility-policy.md`.

## 0.3.0 - 2026-07-15

- Promote the existing runtime no-tool behavior to public Agent and RunConfig
  controls with `continue` as the backward-compatible default.
- Define exact per-run, Runner-default, Agent, and framework precedence without
  inspecting assistant text or task semantics.
- Add typed completion reasons, partial assistant output, and completion tool
  identity to results, terminal events, persisted results, and App Server turn
  completion notifications.
- Lock deterministic completion cases for natural no-tool finish/wait, explicit
  finish tools, tool-use stop policies, max cycles, cancellation, and failure.

## 0.2.1 - 2026-07-15

- Complete the token-usage wire closure by adding the typed cache observation
  to the canonical successful sub-run event payload.
- Keep `0.2.0` immutable; implementations adopt this patch release so result,
  checkpoint, App Server, and sub-run event projections all use one shape.

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
