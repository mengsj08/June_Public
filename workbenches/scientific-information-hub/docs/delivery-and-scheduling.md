# Delivery and scheduling

Every ordinary run is local-only. It creates one fact pool and four projections:

- `daily_items.jsonl`: positive-allowlist content records;
- `source_health.json`: per-source manifests and day-level health;
- `daily_briefing.md`: Markdown reading view;
- `site/index.html`: self-contained interactive reading view;
- `public_content_candidates.jsonl`: high-priority source cards awaiting human review.

Public-content candidates are not platform drafts and are never automatically published. They contain only the source item, a generic angle hint, and `needs_human_review` status.

## Network delivery gate

Webhook delivery requires all three conditions:

1. `delivery.enabled` is `true` in a private runtime configuration;
2. the command includes `--publish`;
3. `delivery.endpoint_env` names an environment variable containing an HTTPS endpoint.

`--live`, `--llm`, and `--publish` are independent. Enabling one does not enable the other two.

## Scheduling

Examples in [`../automation/`](../automation/) intentionally use placeholders. Copy one outside the repository, replace paths locally, and keep secrets in the operating system's credential/environment mechanism. First schedule the command without `--publish`; promote delivery only after several observed dry runs.
