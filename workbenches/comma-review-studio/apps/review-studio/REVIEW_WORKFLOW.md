# Comma Review Studio — structured local review workflow

> status: local v0.3 reference host · verified: 2026-07-19 · host: `127.0.0.1:8891`

## What the AI Review button does

1. Reads the current Markdown revision without editing the document.
2. Queues a local asynchronous run for the selected subscription CLI (Codex by default; Claude optional) in a no-write mode.
3. Requires structured JSON findings: exact quote, issue, action, priority, decision, evidence requirement, and rationale.
4. Validates every quote against the current document. Unique exact matches become `ready`; missing or ambiguous matches are blocked from automatic writeback.
5. Writes accepted, ready findings to `<document>.comments.json` as native comment records.
6. Stores the review ledger, dialogue, decisions, and writeback receipts in `data/review-sessions/<id>.json`. The document body and raw model trace are not duplicated there.

The review drawer supports later discussion. A continuation turn can add, update, or withdraw findings. Re-syncing updates the same AI comment by `source_key`; it never creates a duplicate for the same session/finding. A withdrawn finding remains in the ledger and marks its previously written comment `withdrawn` rather than erasing the audit trail.

Review execution is background-capable, but not durable across host restarts.
The executor reports `queued`, `running`, `cancelling`, `cancelled`,
`completed`, and `failed`. User cancellation terminates the controlled provider
process tree and saves a receipt. Active queue/thread state is in memory; after
a restart, startup recovery marks persisted active runs failed with a
host-restart reason instead of pretending they can continue.

## API surface

Document persistence, recovery, and export:

- `GET/PUT /api/doc` — load or atomically save with `base_rev`; stale writes are retained as conflict drafts
- `GET /api/versions?path=<doc>` — current revision, newest-first timeline, and active conflict-draft summaries
- `POST /api/versions/checkpoints` — add a named checkpoint for the current revision
- `GET /api/versions/diff` — unified diff between a snapshot and current/another snapshot
- `POST /api/versions/<id>/restore` — restore as a new, revision-checked timeline entry
- `GET /api/drafts/<id>/diff` — compare a retained stale write with current Markdown
- `POST /api/drafts/<id>/restore` / `DELETE /api/drafts/<id>/dismiss` — recover or close a draft
- `GET /api/exports/capabilities` — truthful Markdown/ZIP/DOCX/PDF readiness
- `GET /api/export?format=markdown|reviewed-markdown|package|docx|pdf` — non-mutating download

- `GET /api/review-sessions?path=<doc>` — session history summaries
- `POST /api/review-sessions` — start a structured review
- `GET /api/review-sessions/<id>` — full session ledger
- `POST /api/review-sessions/<id>/messages` — continue the review and apply finding operations
- `PUT /api/review-sessions/<id>/findings` — accept, propose, or reject one finding
- `POST /api/review-sessions/<id>/writeback` — revision-locked, idempotent batch comment sync

Quote-scoped discussion is intentionally separate from the findings ledger:

- `GET /api/conversations?path=<doc>` — conversation history summaries
- `POST /api/conversations` — start from an exact quote snapshot and revision
- `GET /api/conversations/<id>` — read the complete parent-linked message tree
- `POST /api/conversations/<id>/messages` — continue or explicitly fork from an assistant message
- `POST /api/conversations/<id>/notes` — attach a human comment to an assistant message without invoking AI
- `POST /api/conversations/<id>/writeback` — edit and explicitly write one assistant response as an anchored native comment

Quick explanation continues to use the transient `/api/ai-run` path and is not
stored as a conversation by default. Conversation writeback is revision-locked
and idempotent by session/message identity. It never modifies Markdown.

All writeback requires `session.base_rev == current document rev`. If the document changes while the model is running or before a later sync, the session becomes `needs_rebase` and no stale comments are written.

## Lark/Feishu principles borrowed — without adding a Lark dependency

- Stable localization: exact quote plus revision, source offset, prefix, and suffix.
- Native object boundary: document, comment, review session, finding, and writeback receipt remain separate facts.
- Post-write verification: every batch returns created, updated, skipped, and blocked receipts.
- Idempotency: `<session_id>:<finding_id>` is the stable write key.

This local host does not call Lark CLI or Feishu APIs. A future Lark adapter can consume the same validated finding/writeback contract.

## Verification evidence

Current regression commands:

```bash
npm run check
CI=true python3 -m pytest apps/review-studio/ -q
```

Historical evidence from 2026-07-19:

- Deterministic public core/adapter tests and Review Studio API/orchestrator tests passed.
- Version/export contract: baseline and automatic snapshots, named checkpoints, unified diff, non-destructive restore, durable conflict-draft recovery, exact/reviewed Markdown, Review Package ZIP, and real local DOCX/PDF conversion passed on synthetic fixtures.
- Quote conversation contract: start, response comment, explicit fork, editable message writeback, idempotent repeat, and stale-revision rejection passed. One real Codex selection conversation completed with a nested branch and native comment writeback.
- Browser selection-action contract emitted the configured action ID, quote locator, and document revision; Chrome extension smoke remained green.
- Legacy renderer/anchor regression: 5/5 anchors resolved correctly; upstream edit retained 5/5; deliberately rewritten quote produced exactly 1 stale anchor; no console errors.
- Block-edit regression: source reconstruction and byte fidelity passed; a rewritten commented block changed `resolved: true -> false`; no console errors.
- Real Codex initial review on a de-identified four-paragraph fixture: 8 findings, 8 unique ready anchors; first sync created 8 comments; immediate second sync created 0 and skipped 8.
- Real Codex continuation: F001 withdrawn and F002 revised; next sync updated exactly 2 comments, skipped 6, left the total at 8, and preserved 1 withdrawn audit record.
- In-app browser: review drawer, ledger card, dialogue, history, and source jump rendered and worked; source jump closed the drawer and highlighted exactly one paragraph; console errors were empty.
- In-app browser: the bottom conversation workbench rendered one reply comment, one nested branch, and one written marker with zero horizontal overflow at 1280×720 and 700×900; console errors were empty.
- In-app browser: the 630 px version/export drawer rendered without horizontal overflow at 1280 px; the live document exposed one baseline version, five export formats, ready DOCX/PDF conversion, and no console errors.

Codex is the default because it completed both real structured runs in the current environment (about 66–85 seconds for the small fixture). Claude remains selectable, but the current local Claude CLI did not return during the exploratory health check, so it is not marked live-verified here.

## Current limits

- Background review and cancellation are supported, but active runs do not resume after host restart.
- Documents over 300,000 characters are rejected; chunked review is not implemented.
- Anchored comments are local sidecar objects. Publishing them to Feishu/Lark requires a separate adapter and destination authorization.
- DOCX/PDF preserve ordinary scientific Markdown structure, local images, tables, and code blocks; complex math and custom embedded HTML should be checked against the canonical Markdown.
