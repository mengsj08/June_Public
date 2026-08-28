# Selection pipeline

The selection layer decides reading attention, not scientific truth.

1. Normalize text, dates, identifiers and HTTP(S) URLs.
2. Compare a stable fingerprint with local state to label `new`, `updated`, or `seen`.
3. Merge duplicate identities while preserving source lineage.
4. Apply a configurable freshness window.
5. Add weighted topic matches and source-kind weights, capped to `0..1`.
6. Count configured novelty hints such as `benchmark`, `atlas`, `framework`, or `protocol`.
7. Assign `must_read`, `skim`, `collapsed`, or `archive` from explicit thresholds.

The example profile is deliberately generic and synthetic. A real profile should live outside the public repository and must not contain private author watchlists, projects, reading history, collaborators, clients, or recipient information.

## Optional LLM triage

LLM triage requires both `llm.enabled: true` in private runtime configuration and the `--llm` CLI flag. It makes a separate OpenAI-compatible classification call. The response is validated against four decisions: `prioritize`, `skim`, `hold`, and `exclude`. It is stored under `llm_triage` with confidence, reason, and model name.

The LLM does not change deterministic `reading_tier`, source provenance, publication date, or identity. If the model call fails, deterministic output remains available and the day becomes `complete_with_warning` when source intake otherwise completed.
