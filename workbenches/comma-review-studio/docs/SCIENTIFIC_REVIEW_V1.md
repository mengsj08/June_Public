# Scientific Review v1

> status: June-confirmed implementation specification · spec version: 1.1 · v1.0 confirmed 2026-07-19 · v1.1 adjudicated and confirmed 2026-07-19 · owner: Comma Review Studio host · related card: `SKL-87`

## v1.1 changelog

v1.1 merges the independent architecture review (Claude) and the red-team review (Codex), adjudicated by June on 2026-07-19. Where v1.1 conflicts with v1.0 text, v1.1 wins.

1. Comment state splits into two orthogonal dimensions: `lifecycle_state` (user-facing existence) and `finding_state` (review decision). Legacy `review_state: "withdrawn"` maps to finding-withdrawn, never to user deletion.
2. Audit truth is an append-only `CommentEvent` ledger; `comments.json` becomes a materialized view.
3. The first AI review still writes comments automatically, but as `finding_state: provisional`; provisional must never be presented as accepted.
4. Every later review — including continued-discussion writeback (`_continue_review`, currently auto-ready at `server.py:2013-2015`) — stops at preview. This is an explicit behavior change, not an addition.
5. Incremental re-review applies only to comment-only changes and low-risk local edits; abstract, methods, results, conclusion, references, and figure/table changes default to full re-review.
6. Review object model: Session = continuous review; Run = one model invocation; Lineage = finding identity across runs; Comment = presentation object.
7. Writeback is locked by document rev + comments rev + operation ids, all checked inside one mutation lock, with a pending operation journal for crash recovery and startup reconciliation.
8. Duplicate review requests with identical `(path, base_rev, comments_rev, mode)` return the same in-flight run.
9. Editor core gains generic `toolbarActions` and `commentActions` extension points, following the `selectionActions` precedent; scientific semantics are injected by the Review Studio host and capability-gated so document-only hosts render none of them.
10. `rev` and the new `comments_rev` are adapter-owned opaque strings. Core passes them through and compares strict equality only; it never interprets, truncates (except pure display), or regenerates a host revision.
11. Migration must handle the real production store under the external `COMMA_REVIEW_DATA_ROOT` (39 comments, 5 sessions as of 2026-07-19), including `kind: null` normalization for legacy AI-writeback records, dry-run on a copy, byte backup before the first real write, and legacy-read fallback on failure.
12. A dual-normalization migration table (host snake_case ↔ core camelCase, status enums, idempotency keys) is part of the deliverable.
13. Product claims must state what was not done: image pixels were not read, cited literature was not verified in full text, statistics were not recomputed.
14. Calendar estimates are removed by June's direction; slices define scope only.

## v1.1.1 changelog (red-team fixes, June-confirmed 2026-07-20)

Normative fixes from the independent red-team review of the Slice A–C implementation. Where v1.1.1 conflicts with earlier text, v1.1.1 wins.

1. **Export truthfulness.** `_reviewed_markdown` (and any distributable review rendition) must read `lifecycle_state` and `finding_state` and render three distinct groups: confirmed comments; provisional comments marked `AI 暂定 · 未经人工确认`; withdrawn comments in a separate labeled section with reason. The export header carries a status count line. Withdrawn items stay in the export (per Migration rules) but never render as live review opinions.
2. **Acceptance display and action.** UI counts and highlights derive from the comment's real `finding_state`, never from the model's self-reported `decision` field. Model-proposed findings display as `AI 建议`; "已接受"-class wording is reserved for human-confirmed state. Add the explicit acceptance action: per-comment `确认接受` (provisional → accepted via comment_version-locked mutation + CommentEvent) and a bulk `接受全部暂定` with confirmation.
3. **Protected-section routing hardening.** Section classification uses a heading stack: a subsection inherits its ancestors' protection (e.g. `### Statistical analysis` under `## Methods` is protected). Default direction inverts: sections that cannot be classified (headingless documents, pre-heading content, unrecognized structure) are treated as protected and route to full re-review; incremental is recommended only for an explicit low-risk allowlist (acknowledgements, discussion-local prose, wording-level edits). CN/EN keyword tables expand (statistical analysis / participants / study design / sample size / outcome / cohort / findings / 统计 / 样本量 / 纳入排除 etc.) as a fallback layer. The `仍按增量复审` escape hatch remains.
4. **Legacy route closure.** `POST /api/review-sessions` returns 409 (pointing to preflight/review-runs) when a completed review already exists for the document; first review keeps current behavior (provisional writes). `POST /api/review-sessions/<id>/writeback` is closed (409); all post-first-review mutations go only through the journaled, triple-locked run writeback. `_writeback_session`'s decision-downgrade branch gains the same `human_edited` guard as the content-update branch.
5. **Stale-run recovery.** Startup reconciliation sweeps runs persisted as `queued`, `running`, or `cancelling` to `failed` with a host-restart reason. Provider execution is handled by the local asynchronous executor, but queue/thread state is in memory, so a reboot proves no live call can be resumed. The active-run registry backs the in-flight idempotency check so a crashed run cannot permanently occupy a revision key.
6. **Comment-creation hardening.** `POST /api/comments` ignores caller-supplied privileged fields (`id`, `source_key`, `applied_signature`, `applied_operation_id`, `finding_state`, `human_edited`); the server assigns them.
7. **Journal reconciliation refinement.** When the document rev changed after comments landed but before receipt finalization, reconciliation verifies landed operations by op id/source_key/applied_signature and finalizes the receipt (marked recovered) instead of reporting a false inconsistency.
8. **DocumentSummary implementation.** Section 3 is implemented as specified (generation via the existing CLI invocation chain, revision-bound persistence, stale marking, drawer rendering, export ledger inclusion), replacing the static shell.
9. **Dual-normalization completion.** Core `normalizeComment` adds aliases for `review_run_id`, `applied_signature`, `applied_operation_id`.

## Outcome

Turn Comma Review Studio from a capable Markdown review host into a professional scientific-manuscript review surface without moving provider, filesystem, or evidence-source responsibilities into editor-core.

The first delivery contains three vertical slices:

1. a truthful comment lifecycle: edit, reply, withdraw, restore, and audit;
2. review preflight plus incremental re-review, change preview, and confirmed writeback;
3. a version-bound article overview that replaces `Source` as the primary top-level action while keeping source editing in the overflow menu.

Literature import is the next phase. This specification reserves its host boundary but does not add a fake `+` button before a traceable evidence-source model exists.

## Product language

The current controls describe implementation details rather than user intent. Scientific Review v1 uses:

| Current label | v1 label / location | Meaning |
| --- | --- | --- |
| `Source` | `文章总览` | Read a version-bound structured summary of the manuscript. |
| `Source` editor | overflow menu → `源码编辑` | Edit canonical Markdown directly; this capability is retained. |
| `AI review` | `AI Review` | Start the first review or preflight a later re-review. |
| `Overall note` | `全文批注` | Create an unanchored comment about the whole manuscript. |
| `Comments 39` | `批注 39` | Toggle the one native comment surface and show its effective count. |
| `Margin notes` | `批注` | Heading for the same comment collection; not a second comment type. |

The comment count excludes withdrawn comments by default — both lifecycle-withdrawn and finding-withdrawn. The panel can opt into `显示已撤回`, which shows both, labeled distinctly. The header count and the anchor badges must use the same exclusion rule.

## Boundary

### Editor core owns

- rendering and canonical Markdown block editing;
- anchored and overall comment presentation;
- generic `toolbarActions` and `commentActions` extension points (declared by the host, rendered by core, emitted back as composed events);
- selection events and anchor resolution;
- generic adapter capability discovery.

### Review Studio host owns

- local Codex/Claude execution and CLI capability status;
- comment persistence, the `CommentEvent` audit ledger, and reply threads;
- review preflight, review runs, finding lineage, operation journal, and writeback receipts;
- article-summary generation and persistence;
- future literature-source resolution and evidence extraction.

No provider, filesystem, DOI/PMID, PDF, or literature-specific behavior enters `src/core/` or `src/element/`.

### Core extension points (new in v1.1)

The header actions (`Source`, `AI review`, `Overall note`, `Comments N`) and the per-card comment actions are currently hardcoded in `src/element/comma-editor.js`. v1.1 replaces the hardcoding with two declarative host inputs, modeled on the existing `selectionActions` setter:

- `toolbarActions`: ordered list of `{id, label, slot: "primary" | "overflow"}`; activation emits a composed event. The scientific labels above are Review Studio's injection, not core defaults.
- `commentActions`: per-card `···` menu items `{id, label, appliesTo}`; activation emits a composed event carrying the comment id. Core renders the menu only when the adapter declares the matching comment capabilities.

A document-only host (for example the kanban adapter with comments disabled) must render no comment actions and no comment count. This is verified by a capability-boundary test.

### Revision opacity rule (new in v1.1)

`rev` (document) and `comments_rev` (comment collection) are opaque strings owned by the adapter/host that produced them. Review Studio keeps its internal `sha256[:16]` server format; other hosts keep theirs. Core and all shared code compare them with strict equality only. Display-layer truncation is allowed; logical truncation, parsing, or regeneration of a host-provided revision is not.

## 1. Comment lifecycle

### Comment record (materialized view)

Existing `comma-comment/v1` records remain readable. New fields are additive and normalize to safe defaults:

```json
{
  "id": "c-...",
  "kind": "anchored",
  "content": "...",
  "lifecycle_state": "active",
  "finding_state": "provisional",
  "comment_version": 3,
  "human_edited": true,
  "origin_signature": "sha256:...",
  "withdrawn_at": "",
  "withdrawn_by": "",
  "withdraw_reason": "",
  "replies": [
    {
      "id": "reply-...",
      "author": "June",
      "content": "...",
      "created_at": "...",
      "updated_at": "...",
      "state": "active"
    }
  ]
}
```

### CommentEvent ledger (audit truth)

Per document, append-only JSONL sidecar (for example `<doc>.md.comment-events.jsonl`):

```json
{
  "event_id": "ce-...",
  "comment_id": "c-...",
  "action": "create|edit|withdraw|restore|reply|reply-edit|reply-withdraw|finding-update|migrate",
  "actor": "June",
  "from_version": 2,
  "to_version": 3,
  "content_before_hash": "sha256:...",
  "content_after_hash": "sha256:...",
  "at": "..."
}
```

- The ledger records hashes and mutation metadata; it never duplicates manuscript body text.
- `comments.json` is the materialized view; on inconsistency the ledger is authoritative for audit questions, the view for display.
- `查看修改记录` reads from the ledger.

### Rules

- `lifecycle_state` is `active | withdrawn` and expresses user-facing existence. Delete becomes withdraw; physical deletion is reserved for malformed local data maintenance, not the normal UI.
- `finding_state` is `provisional | accepted | pending | withdrawn` and carries the review decision. It exists only for comments with finding provenance; plain human comments omit it.
- Legacy `review_state` maps into `finding_state`: `active → accepted`, `pending → pending`, `withdrawn → withdrawn`. It is never interpreted as user deletion.
- Legacy AI-writeback records with `kind: null` (the real store contains 38 such records) normalize by inference: a usable `source_locator`/`quote_text` → `anchored`, otherwise `overall`.
- Editing an AI-origin comment sets `human_edited: true`; later review must not silently overwrite it. `human_edited` does not by itself change `finding_state`; acceptance of a provisional finding is an explicit action (single or bulk).
- Replies are discussion on a native comment. They do not modify `content` and are not counted as additional manuscript comments.
- Every mutation is protected by `comment_version`; a stale mutation returns `409` with the current comment.
- Every mutation appends exactly one `CommentEvent`.

### API

Keep the existing comment routes as compatibility aliases. Add explicit item routes:

```text
PATCH /api/comments/<comment_id>
  { path, base_comment_version, content, actor }

DELETE /api/comments/<comment_id>
  { path, base_comment_version, actor, reason }

POST /api/comments/<comment_id>/restore
  { path, base_comment_version, actor }

POST /api/comments/<comment_id>/replies
  { path, base_comment_version, actor, content }

PATCH /api/comments/<comment_id>/replies/<reply_id>
DELETE /api/comments/<comment_id>/replies/<reply_id>

GET /api/comments/<comment_id>/events
```

All mutating responses return the mutated comment, its new `comment_version`, the new `comments_rev`, and an event receipt.

### Card interaction

Each comment card exposes a compact `···` menu (host-injected via `commentActions`):

- `回复`
- `编辑`
- `撤回` or `恢复`
- `查看修改记录`
- `定位原文` for anchored comments

Withdraw requires a lightweight confirmation. Editing and replying remain inline in the card; they must not open the full review drawer.

## 2. Review preflight and re-review

### Required behavior

#### First review

- No completed review exists for the document.
- The current full-document review remains available.
- Findings that pass validation (accepted by the model, uniquely anchored) are written as comments automatically, but with `finding_state: provisional`. Provisional comments are visibly marked and are never presented as confirmed review conclusions. Explicit acceptance (single or bulk) promotes them to `accepted`.

#### Later AI Review click

The button first runs deterministic preflight. It does not invoke a model yet.

```text
latest completed review
        + current document revision
        + current comments_rev
        + anchor health
                ↓
          ReviewPreflight
                ↓
unchanged → view / continue / force full review
changed   → incremental or full re-review proposal
```

The modal reports:

- document revision changed or unchanged;
- changed block count and affected sections;
- comments added, human-edited, withdrawn, restored, or replied to since the baseline;
- missing or ambiguous anchors;
- recommended mode and estimated review scope.

Default actions:

- no changes: `查看最近评审` is primary; no CLI call;
- changes present and low-risk: `增量复审` is primary;
- changes touching abstract, methods, results, conclusion, references, or figures/tables: `全文复审` is primary and incremental is a deliberate downgrade;
- explicit escape hatch: `强制全文复审`.

Every later review — incremental or full, including continued-discussion writeback — stops at preview. No later-review path writes comments directly after the model returns. The existing `_continue_review` auto-ready behavior is removed.

### Incremental scope restriction

Incremental re-review is only recommended when the delta since baseline is limited to:

- comment changes (add, edit, withdraw, restore, reply), or
- low-risk local manuscript edits (wording, local discussion passages) that do not touch abstract, methods, results, conclusion, references, or figures/tables.

Any change in those protected sections defaults the recommendation to full re-review, because a local change there can alter the paper's global thesis or evidence interpretation. This keeps `changed_blocks` a routing signal, not a claimed semantic impact analysis.

### ReviewPreflight response

```json
{
  "schema_version": "comma-review-preflight/v1",
  "document": {
    "path": "paper.md",
    "current_rev": "...",
    "baseline_rev": "...",
    "change_state": "unchanged|changed|no-baseline",
    "changed_blocks": [],
    "affected_sections": [],
    "protected_sections_touched": false
  },
  "baseline_session": {
    "id": "review-...",
    "completed_at": "..."
  },
  "comments": {
    "comments_rev": "...",
    "baseline_comments_rev": "...",
    "added": [],
    "edited": [],
    "withdrawn": [],
    "restored": [],
    "replied": []
  },
  "anchors": {
    "ready": 0,
    "missing": [],
    "ambiguous": []
  },
  "recommended_mode": "initial|incremental|full|view-latest",
  "allowed_modes": ["incremental", "forced-full"]
}
```

`changed_blocks` contains locators and hashes, not duplicated manuscript text. The model request is assembled from the current authorized document only after the user starts re-review.

### API

```text
GET /api/review-preflight?path=<doc>

POST /api/review-runs
  {
    path,
    base_rev,
    baseline_session_id,
    comments_rev,
    mode: "initial|incremental|forced-full",
    tool,
    rubric,
    instruction
  }

GET /api/review-runs/<run_id>

POST /api/review-runs/<run_id>/writeback
  {
    base_rev,
    comments_rev,
    accepted_operation_ids
  }
```

The current `/api/review-sessions` routes remain available during migration. A review run may initially be persisted in the existing session file, but its input snapshot and lineage are immutable.

### In-flight idempotency

`POST /api/review-runs` with the same `(path, base_rev, comments_rev, mode)` as a currently running run returns that run's id instead of starting a second model invocation. This is the double-click guard; it is keyed on revisions, not on wall-clock debouncing.

### ReviewRun

```json
{
  "schema_version": "comma-review-run/v1",
  "id": "run-...",
  "session_id": "review-...",
  "parent_session_id": "review-...",
  "mode": "incremental",
  "input": {
    "document_rev": "...",
    "comments_rev": "...",
    "changed_block_ids": [],
    "affected_comment_ids": []
  },
  "operations": [
    {
      "id": "op-...",
      "action": "create|update|withdraw|keep|blocked",
      "finding_id": "F...",
      "supersedes_finding_id": "F...",
      "target_comment_id": "c-...",
      "reason": "...",
      "proposed_comment": {}
    }
  ],
  "model_receipt": {},
  "writeback_receipt_id": "",
  "status": "running|preview|completed|needs_rebase|failed"
}
```

Object model: a Session is the continuous review of one manuscript; a Run is one model invocation inside it; Lineage (`finding_id` / `supersedes_finding_id`) is the identity of a problem across runs; a Comment is the presentation object a finding materializes into. Legacy sessions whose status is `ready` read as `preview` (see the dual-normalization table).

### Writeback safety

- A later review never writes directly after the model returns. It stops at `preview`.
- Preview groups operations as `新增 / 修改 / 撤回 / 不变 / 阻断`.
- The user can accept individual operations or accept all non-blocked operations.
- Writeback requires the same document rev, the same `comments_rev`, and explicit operation ids. All three checks and the write itself happen inside one mutation lock.
- A document or comment change between preview and writeback returns `409`; no partial write occurs.
- An update targeting `human_edited: true` is visually called out and requires explicit acceptance.
- Missing or ambiguous anchors remain blocked; the model is never allowed to guess a location.
- Re-running writeback with the same operation ids is idempotent. Operation ids map onto the existing `source_key` (`session_id:finding_id`) plus `applied_signature` dedupe so legacy idempotency keeps working.

### Crash recovery (operation journal)

Single-file atomic writes are not transaction atomicity across `comments.json`, the event ledger, and the session/run receipt (the current gap sits between `_save_comments` at `server.py:1244` and the caller's `_save_session`). v1.1 adds a pending operation journal:

1. Before mutating, persist a journal entry: `run_id`, accepted operation ids, target `base_rev` and `comments_rev`.
2. Apply the comment mutations (atomic view write + ledger append).
3. Finalize the receipt into the session/run record.
4. Clear the journal entry.

On startup, an unfinalized journal entry triggers reconciliation: using operation ids, `source_key`, and `applied_signature`, the host determines which operations landed, completes the missing receipt or reports the inconsistency, and never presents a half-applied writeback as complete.

### Incremental model scope

The model receives:

- the review rubric and the latest accepted findings;
- changed manuscript blocks plus enough section context;
- affected comments and their human changes;
- exact source locators needed to propose safe operations.

Unchanged full sections are not sent merely to imitate a full review. `forced-full` remains explicit for cases where a local change alters the paper's global thesis or evidence interpretation.

## 3. Article overview

`文章总览` is a host analysis artifact, not a comment and not a rewrite of Markdown.

### DocumentSummary

```json
{
  "schema_version": "comma-document-summary/v1",
  "id": "summary-...",
  "doc_path": "paper.md",
  "base_rev": "...",
  "status": "ready|stale|failed",
  "reading_scope": "full-document",
  "summary_3_6": ["..."],
  "thesis": "...",
  "evidence_scope": ["..."],
  "major_conclusions": ["..."],
  "limitations": ["..."],
  "source_check_targets": ["..."],
  "tool": "codex",
  "model_meta": {},
  "created_at": "..."
}
```

### API and UI

```text
GET /api/document-summary?path=<doc>
POST /api/document-summary
  { path, base_rev, tool, regenerate: false }
```

- Opening `文章总览` returns the matching summary for the current revision when one exists.
- If none exists, the drawer explains what will be generated before invoking the selected available CLI.
- A summary from an older revision is shown as `已过期`, never as current.
- Regeneration is explicit and produces a new summary record; it does not overwrite history.
- Source editing remains available at `··· → 源码编辑`.
- The summary does not change the native comment count or create an overall comment.

### Honest capability claims

The overview and review surfaces must state, in plain product language, what the AI pass did not do:

- image and figure pixels were not read (text, captions, and references only);
- cited literature was not fetched or verified in full text;
- statistics were not recomputed.

These statements ship with v1 and are removed only when the corresponding capability actually exists.

## Professional scientific-review order

Prompts and UI grouping use this order:

1. thesis, novelty, and internal logic;
2. evidence boundary, source-check needs, and clinical overclaim;
3. methods, cohorts, statistics, and reproducibility;
4. figures, tables, legends, and cross-reference consistency;
5. discussion, limitations, and conclusion calibration;
6. wording and presentation.

Sentence polish must not crowd out validity, evidence, or structural findings.

## Migration

1. Read legacy comments as `lifecycle_state=active`, `comment_version=1`, empty replies; the event ledger starts at each comment's first post-migration mutation (plus one `migrate` event when a record is rewritten).
2. Map legacy `review_state` into `finding_state` (`active → accepted`, `pending → pending`, `withdrawn → withdrawn`); preserve all existing `source_key` values and `finding_id`s.
3. Normalize legacy `kind: null` AI-writeback records by locator inference (anchored vs overall).
4. The real production store lives under the external `COMMA_REVIEW_DATA_ROOT` (`server.py:68-69`), currently 39 comments (38 ai-review, 1 selection-conversation) and 5 review sessions (2 completed, 3 failed). Before any real write: run the migration as a dry-run against a copy of the sidecar, keep a byte backup of the originals, and verify zero loss — 39/39 comments, 5/5 sessions, every `finding_id` and `source_key` intact. If migration fails, the host keeps reading the legacy schema; broken half-migrated state is not acceptable.
5. Change the normal delete route into withdraw; retain the old physical-delete helper only for maintenance and tests that explicitly request purge.
6. Keep current sessions readable. New runs may reference old sessions as `parent_session_id` without rewriting them; legacy `ready` status reads as `preview`.
7. Existing version/export packages include the expanded comment fields, the `CommentEvent` ledger, and new review-run/summary ledgers, while still excluding raw model traces.

## Dual-normalization migration table

Two normalization layers exist today (host `_comment_record()` in `server.py`, core `normalizeComment()` in `src/core/models.js`). Every new field must land in both, or round-trips drop it. The binding rules:

| Concern | Host (Review Studio) | Core | Rule |
| --- | --- | --- | --- |
| Field casing | snake_case on disk and API | camelCase in memory | `first()`-style aliases accept both; disk format stays snake_case |
| Author identity | `author` | `actor` | normalize both keys to one identity; new lifecycle fields follow the same aliasing |
| Document rev | `sha256[:16]`, no prefix | opaque passthrough (`revisionOf` is adapter-only fallback) | never regenerate, parse, or logically truncate; strict equality only |
| Comments rev | host-generated over the normalized comment collection | opaque passthrough | same opacity rule as document rev |
| Run/session status | legacy `ready` | — | new code uses `preview`; migration maps `ready → preview` on read |
| Writeback idempotency | `source_key` (`session_id:finding_id`) + `applied_signature` | — | operation ids map onto both; the journal is keyed by operation id |

## Delivery slices

Scope only; no calendar estimates (removed by June's direction).

| Slice | Scope |
| --- | --- |
| A | product labels, article-overview shell, `toolbarActions`/`commentActions` extension points, comment lifecycle (edit/reply/withdraw/restore), `CommentEvent` ledger, migration including real-store dry-run |
| B | deterministic preflight, in-flight idempotency, review-run lineage, incremental routing restriction and prompt |
| C | operation preview, journaled atomic confirmed writeback, crash-recovery reconciliation, regression and real-manuscript acceptance |

Literature import remains a separate follow-up phase.

## Acceptance criteria

### Comment lifecycle

- [ ] A user can edit an anchored or overall comment inline; refresh preserves the result.
- [ ] Editing an AI comment marks it human-edited and appends a ledger event.
- [ ] A reply is visible under the comment and does not alter the manuscript comment count.
- [ ] Withdraw hides the comment from the default list but retains it in the ledger and export package.
- [ ] Restore returns the same comment ID; no duplicate is created.
- [ ] A stale `comment_version` mutation returns `409` and does not overwrite newer work.
- [ ] Every mutation appends exactly one `CommentEvent`; `查看修改记录` renders from the ledger.
- [ ] Header count and anchor badges exclude withdrawn (both dimensions) with one shared rule.

### Re-review

- [ ] With no earlier completed review, AI Review runs the full first-review path and writes findings as `provisional`, visibly marked, never presented as accepted.
- [ ] Explicit acceptance (single and bulk) promotes provisional findings to accepted.
- [ ] With the same document revision and unchanged `comments_rev`, AI Review performs no CLI call by default.
- [ ] A document edit, comment edit, reply, withdraw, or restore appears in preflight counts.
- [ ] Changes touching abstract/methods/results/conclusion/references/figures-tables produce a full-review recommendation, not incremental.
- [ ] Incremental re-review returns a preview containing create/update/withdraw/keep/blocked operations.
- [ ] No later review operation reaches comments before explicit confirmation — including the continued-discussion path (`_continue_review`).
- [ ] Two concurrent identical review requests share one run (in-flight idempotency).
- [ ] Writeback is atomic and locked by document rev + `comments_rev` + operation ids inside one mutation lock.
- [ ] A repeated confirmed writeback is idempotent.
- [ ] Killing the host between the comment write and receipt finalization leaves a journal entry that startup reconciliation resolves without loss or duplication.
- [ ] Human-edited AI comments cannot be silently overwritten.
- [ ] Missing and ambiguous anchors remain blocked.

### Migration

- [ ] Dry-run migration against a copy of the real sidecar passes: 39/39 comments, 5/5 sessions, all `finding_id`/`source_key` preserved, `kind: null` records normalized by locator inference.
- [ ] A byte backup of the original sidecar and sessions exists before the first real write.
- [ ] On migration failure the host continues reading the legacy schema.

### Article overview, boundaries, and regression

- [ ] `文章总览` produces a structured summary bound to the current revision without editing Markdown or comments.
- [ ] Editing the document marks the old summary stale.
- [ ] `源码编辑` remains reachable from the overflow menu.
- [ ] The honest capability claims (no image pixels, no literature verification, no statistics recomputation) are visible in the overview/review surface.
- [ ] A document-only host fixture (comments capability off) renders no comment actions and no comment count.
- [ ] CLI status, versions, exports, block editing, selection actions, quote discussions, and comment source jumps remain functional.
- [ ] The scientific long-document layout has no horizontal overflow at the existing desktop and narrow regression sizes.
- [ ] Tests and fixtures contain no private manuscript body, credentials, raw AI trace, or browser profile.

## Next phase: literature evidence intake

The future discussion-dock `+` menu will be owned by Review Studio and will create traceable `EvidenceSource` and `EvidenceTable` objects. It must distinguish full text, abstract-only, and metadata-only access and must preserve DOI/PMID identity plus exact quote/page provenance. Until those contracts exist, the UI must not claim that a paper was read in full.
