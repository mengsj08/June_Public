# Data source contracts

All adapters return the same pre-normalization envelope: `source_id`, `status`, `items`, `checks`, and a sanitized `error`. Each item should provide as many of these public fields as the upstream supports: title, URL, publication date, summary, authors, tags, PMID, DOI, or arXiv ID.

## Public and scholarly sources

- `pubmed` and `pubmed_journals` use NCBI ESearch followed by ESummary. A topic query or journal list is required.
- `arxiv` uses the public Atom endpoint.
- `rss` accepts an explicit HTTP(S) RSS or Atom URL.
- `hacker_news` is a community-signal adapter, not a scholarly source.
- `openalex_author` watches public OpenAlex author identifiers. A real watchlist is private configuration.

These adapters are disabled unless the source is enabled in configuration and the CLI receives `--live`.

## Account and local-export sources

- `email_directory` parses user-exported `.eml` files locally.
- `imap` opens an SSL connection, selects a mailbox read-only, and reads credentials only from named environment variables.
- `feishu_export` accepts a normalized JSON list or `{ "records": [...] }` export. It does not embed organization IDs, Base tokens, or recipients.
- `stork_inbox` accepts JSONL or CSV exported by the user.
- `browser_snapshot` accepts normalized JSON exported after a user-controlled authenticated browsing session. It never opens a browser profile or reads cookies.

## Legacy compatibility

`legacy_jsonl` reads JSONL or CSV with an explicit `field_map`. It marks each record `legacy-compat`; the ordinary freshness and incremental gates still apply. This is intentionally a boundary adapter, not an invitation to publish every private historical fetcher.

## Stable identity

Identity priority is PMID, DOI, arXiv ID, canonical HTTP(S) URL, then a stable source/title digest. Deduplication preserves `observed_in_sources` lineage and keeps the richest normalized record.

The full disabled-by-default catalog is [`../config/sources.example.json`](../config/sources.example.json).
