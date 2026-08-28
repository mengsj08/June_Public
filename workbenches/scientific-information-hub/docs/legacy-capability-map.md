# Full capability map

The public package represents the full SIH capability surface without publishing private operating state.

| Capability | Public reusable object | Private boundary |
|---|---|---|
| LLM filtering | validated triage contract, prompt boundary, opt-in provider adapter | API key, endpoint policy, model traces |
| Email | `.eml` and read-only IMAP adapters | mailbox, credentials, messages |
| Feishu/Lark | normalized JSON export adapter | tenant IDs, Base tokens, recipients |
| Stork | JSONL/CSV inbox adapter | saved items and account state |
| Author tracking | OpenAlex author query contract | real watchlist and identity decisions |
| Browser login capture | normalized snapshot adapter | profile, cookies, session, raw browsing history |
| External push | three-gate HTTPS webhook | endpoint, credentials, recipient routing |
| Personal profile | weighted profile schema and deterministic algorithm | real interests, projects, reading behavior |
| Public-content automation | review-candidate package | publication ledger, platform credentials, final posting |
| Legacy fetchers | explicit field-map compatibility adapter | private old code, runtime data, obsolete credentials |

This distinction is the de-identification strategy: publish behavior and contracts; keep identity, account state, data and receipts local.
