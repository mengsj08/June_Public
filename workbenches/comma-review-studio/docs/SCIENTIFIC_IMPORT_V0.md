# Scientific Import v0

> status: implemented host contract; Gate 2 product update pending implementation · 2026-07-20 · owner: Comma Review Studio · related card: `SKL-98`

## Product decisions

- **Gate 1 — confirmed by June:** DOCX/Markdown is a one-time intake source. After confirmation, the created Markdown is the sole working manuscript. The source file remains immutable and hash-linked.
- **Gate 2 — confirmed by June, implementation pending:** tracked revisions and Word comments are separate choices. The recommended body policy imports the latest revised text (accept insertions, exclude deletions); Word comments may be imported as provisional `word-import` comments or retained only with the immutable source. Missing/ambiguous comment anchors enter a pending-location queue and do not block the manuscript. The current hard block is only a temporary protection until this decision UI and revision ledger are implemented.
- **Gate 3 — opt-in evidence:** a PDF is an `EvidenceSource`, never manuscript content. Upload and page extraction are local. It enters a conversation or AI Review only when the user checks that source for the next run. AI summary requires a separate provider choice and data-transfer confirmation.
- **Gate 4 — intentionally separate:** importing a later Word revision creates another document in v0. Comment migration, same-manuscript matching, and bidirectional Word sync are not implemented.

## Host boundary

| Layer | Owns |
| --- | --- |
| `editor-core` | Markdown rendering/editing, selection, generic comments, anchor resolution, adapter capabilities |
| Review Studio host | file intake, filesystem storage, DOCX/PDF parsing, macOS sandbox, ImportReceipt, EvidenceSource, provider invocation |

No DOCX, PDF, filesystem, Mammoth, PDF.js, or provider assumption was added to `src/core/` or `src/element/`.

## Manuscript intake

The UI action is `导入主稿`.

```text
local .md/.docx
      ↓
isolated staging + source sha256
      ↓
format-specific validation/conversion
      ↓ when revisions/comments exist
explicit body + comment policy choice
      ↓
preview + ImportReceipt
      ↓ explicit confirmation
atomic no-overwrite Markdown creation
      ↓
initial version snapshot (kind=import)
```

Routes:

```text
GET    /api/imports/capabilities
POST   /api/imports?kind=manuscript&filename=...
GET    /api/imports/<import-id>
DELETE /api/imports/<import-id>                 # staged only
POST   /api/imports/<import-id>/commit
```

`commit` is idempotent for the same import and same target. It never replaces an existing Markdown file. A staged source or candidate hash drift returns `409`; a failed commit removes any document, version, or asset material created by that attempt. Closing an unconfirmed UI flow discards its staged private source.

### Markdown

- accepts UTF-8 `.md` and `.markdown`, maximum 10 MB;
- preserves the exact source bytes in the immutable archive;
- canonical text removes a UTF-8 BOM and normalizes CRLF/CR to LF, with both transformations recorded;
- reports local image references that were not imported by the standalone-file flow;
- does not guess or fetch missing assets.

### DOCX

Pinned conversion chain:

```text
OOXML safety probe
  → Mammoth 1.12.0 semantic HTML
  → sanitize-html 2.17.6 allowlist
  → Turndown 7.2.4 + turndown-plugin-gfm 1.0.2
  → canonical Markdown + controlled image assets
```

The conversion runs through macOS `sandbox-exec` with `deny network*`. If Node.js, the script, or the sandbox is unavailable, DOCX intake reports unavailable and does not fall back to LibreOffice.

Pre-conversion checks include:

- OOXML ZIP entry count, entry size, total expansion, compression ratio, encryption, symlink, and canonical path;
- required `[Content_Types].xml` and `word/document.xml` parts;
- standard DOCX main content type (macro-enabled/renamed `.docm` rejected);
- macro, ActiveX, OLE, and embedded-object parts;
- XML DTD/entity declarations;
- non-hyperlink external relationships and `INCLUDEPICTURE` fields;
- tracked-change elements and Word comments (detected and reported, not treated as security threats).

### Tracked revisions and Word comments

The target Gate 2 intake contract is:

- body policy: `latest-revised-text` (recommended) or cancel and return to Word;
- comment policy: `import-provisional` (recommended) or `archive-only`;
- revision provenance: always retain a `revision-ledger.json` with insertion/deletion/move counts, available author/time metadata, source hash, and selected body policy;
- imported comments retain Word author, time, content, source id, and `source=word-import`; they begin as provisional and require normal Comma acceptance/editing;
- a uniquely mapped quote becomes an anchored comment; missing/ambiguous mappings enter a pending-location queue without guessing and without blocking the canonical Markdown;
- hard blocking remains for unsafe OOXML, conversion failure, empty output, or a revision structure whose latest text cannot be determined safely.

The current server still rejects any DOCX with tracked changes or Word comments before conversion. That behavior is an implementation gap, not the approved product behavior, and its old regression must be replaced by fixtures covering the choices above.

The synthetic regression covers headings, bold/italic text, hyperlinks, a bullet list, GFM table conversion, an embedded PNG, and a figure caption. Footnotes, endnotes, equations, and text boxes are detected and disclosed as verification warnings; they are not claimed as publication-faithful conversion.

## PDF EvidenceSource

The UI action is `参考资料`, also reachable from the quote-discussion dock.

Routes:

```text
GET  /api/evidence-sources/capabilities
GET  /api/evidence-sources?path=<doc>
POST /api/evidence-sources?path=<doc>&filename=...
GET  /api/evidence-sources/<id>?path=<doc>&include_text=1
GET  /api/evidence-sources/<id>/file?path=<doc>
POST /api/evidence-sources/<id>/confirm-full-text
POST /api/evidence-sources/<id>/summary
```

PDF.js 6.1.200 extracts page text in the same no-network sandbox. The source PDF is immutable; page text is stored separately with explicit page numbers.

Two independent facts are recorded:

- `access_level = uploaded_pdf` says what file the user supplied;
- `extraction_status = usable | partial | image_only | failed` says how much text was locally extracted.

The v0 heuristic is fixed and versioned:

- a page is text-usable at `>=200` non-whitespace characters;
- `<200` total characters and zero text-usable pages → `image_only`;
- `>=2000` total characters and `>=60%` text-usable pages → `usable`;
- all other non-empty extraction → `partial`;
- encryption or parser failure → `failed`.

`usable` does not mean “complete paper”. The label `全文 PDF · 文本可用` appears only when extraction is usable **and** the user separately confirms the file is the full text. OCR is outside v0.

### Provider boundary

- Upload never invokes Codex or Claude.
- `生成摘要` shows the exact transfer boundary and requires confirmation; only extracted PDF text plus page labels is sent, not the PDF binary or manuscript Markdown.
- Summary receipts store provider, time, source hash, extraction status, and 3–6 sentences.
- Checking `用于下一次讨论/评审` adds only those EvidenceSource ids to that newly created run. Unchecked sources are absent from the prompt.
- Authorized evidence is delimited as untrusted content and retains `[PDF page N]` provenance. A local 120,000-character context limit prevents an unbounded evidence prompt.

## Durable storage and export

```text
data/.comma-review/imports/<import-id>/
  receipt.json
  source/original.bin
  candidate.md
  candidate-assets/*

data/.comma-review/evidence-sources/<doc-key>/<evidence-id>/
  record.json
  source.pdf
  pages.json
```

Review Package ZIP includes the matching ImportReceipt, immutable intake source, EvidenceSource record, page text, and source PDF. Raw AI traces and the global event ledger remain excluded.

## Known remaining work

- Gate 2 implementation: revision/comment decision UI, deterministic latest-text conversion, provisional Word-comment import, pending-location queue, revision ledger, and replacement regression fixtures;
- Gate 4 same-manuscript re-import, block mapping, and comment-anchor migration;
- Markdown directory/ZIP intake with local assets;
- OCR and publication-faithful Word formulas/text boxes/complex footnotes;
- browser acceptance against a user-chosen non-private Word/PDF sample after synthetic regression passes.

## Verification

Synthetic fixtures are created in tests and contain no private manuscript text:

- `test_review_import.py`: staged commit/idempotency, no-overwrite, hash drift, source disposal, Markdown missing assets, DOCX formatting/images, zip slip/bomb, DTD/entity, macro, external relationship, current temporary tracked-change/comment hard block, and portable provenance export. Gate 2 implementation must replace the temporary-block assertions with decision, ledger, provisional-comment, and pending-location cases;
- `test_review_evidence.py`: page thresholds, usable/image-only extraction, full-text confirmation, deduplication, explicit conversation/review inclusion, explicit provider summary, and portable evidence export.

Run:

```bash
npm run test:review
npm test
npm run build:chrome
npm run validate:chrome
```
