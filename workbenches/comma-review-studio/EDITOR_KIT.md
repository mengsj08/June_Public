# Comma Editor Kit

> Status: public workbench snapshot of Comma Editor Kit v0.3. The source commit and export boundary are recorded in `PROVENANCE.md`.

Comma Editor Kit is a local-first Markdown review and revision component. It turns the proven editor kernel from `md-collab-editor-spike` into one host-neutral source that can run in a workbench, a normal web page, or a Chrome Side Panel. The repository also contains Comma Review Studio as the feature-complete reference host for structured AI review and native comment writeback.

The editor is **not** an MCP server and **not** a Skill. It exposes a document adapter contract. A future MCP or Skill can be a thin consumer of the same contract.

## Delivered surfaces

- `src/core/`: revision, block mapping, comment-anchor, and model contracts.
- `src/element/`: the `<comma-editor>` Web Component.
- `src/adapters/`: memory, browser storage, and HTTP host adapters.
- `apps/review-studio/`: local Python reference host with staged Word/Markdown intake, page-provenanced PDF EvidenceSources, multi-turn structured AI review, revision-locked comment writeback, recoverable document history, and Markdown/ZIP/DOCX/PDF exports.
- `standalone/`: a real local demo using browser local storage.
- `chrome-extension/`: Manifest V3 Side Panel wrapper with explicit current-page capture.
- `release/chrome-extension/`: generated installable unpacked-extension directory after `npm run build:chrome`.

## Run

```bash
npm ci
npm run check
npm run dev -- --port 4178
```

Open `http://127.0.0.1:4178/standalone/`.

Run the complete Review Studio host:

```bash
cd apps/review-studio
COMMA_REVIEW_PORT=8891 python3 server.py
```

Its default `data/` directory contains only a deterministic synthetic fixture. Point `COMMA_REVIEW_DATA_ROOT` at an explicit local directory to review private documents; documents, comments, review sessions, events, and model traces are ignored by Git.

## Embed

```js
import {
  LocalStorageDocumentAdapter,
  registerCommaEditor,
} from '@june/comma-editor-kit';

registerCommaEditor();

const editor = document.querySelector('comma-editor');
editor.adapter = new LocalStorageDocumentAdapter({
  key: 'paper-draft',
  seed: {
    title: 'paper.md',
    body: '# Draft\n\nStart writing.',
  },
});
await editor.load();
```

```html
<comma-editor actor="june" theme="scientific"></comma-editor>
```

The component dispatches host-level events instead of binding to a particular AI provider:

- `comma-ready`
- `comma-change` (an explicit-save draft changed but has not reached the adapter)
- `comma-save`
- `comma-conflict`
- `comma-comment-create`
- `comma-comment-batch-preview`
- `comma-comment-batch-create`
- `comma-ai-request`
- `comma-selection-action`
- `comma-toolbar-action`
- `comma-comment-action`

Hosts can replace the default one-shot selection action without putting a
provider inside the component:

```js
editor.selectionActions = [
  { id: 'quick-explain', label: '快速解释' },
  { id: 'discuss', label: '深入讨论' },
];

editor.addEventListener('comma-selection-action', (event) => {
  // actionId + quoteText + sourceLocator + revision-locked document snapshot
  routeSelectionAction(event.detail);
});
```

The native `Add note` action remains editor-owned. Host actions receive the
same quote snapshot and stable locator but cannot silently mutate Markdown.

Header and per-comment commands are also host-declared. The component filters
them against adapter capabilities and emits composed events; labels and
provider behavior stay in the host:

```js
editor.toolbarActions = [
  { id: 'document-info', label: 'Document info', slot: 'primary', appliesTo: 'document.load' },
  { id: 'comments', label: 'Comments', slot: 'primary', appliesTo: 'comments.list', count: 'comments' },
];
editor.commentActions = [
  { id: 'edit', label: 'Edit', appliesTo: { capability: 'update', target: 'comment' } },
];
```

A document-only adapter renders neither comment actions nor a comment count.

Rendered Markdown stays in reading mode during clicks and drag selections.
Writable hosts expose an explicit per-block `Edit block` affordance instead of
turning every manuscript click into a textarea; `lang="zh-CN"` localizes that
control and its edit footer. This keeps selection commands and editing from
competing for the same pointer gesture.

## Structured AI comments

`AI review` emits a host-neutral `comma-ai-request` with `mode: "comment-batch"`, the current Markdown revision, an output schema, and an `accept(response)` callback. The host may use Codex, Claude, or another reviewer and return structured proposals without giving the component provider credentials:

```js
editor.addEventListener('comma-ai-request', async (event) => {
  if (event.detail.mode !== 'comment-batch') return;
  const response = await myReviewer(event.detail.document, event.detail.outputSchema);
  event.detail.accept(response, { actor: 'codex', source: 'manuscript-review' });
});
```

The component checks every exact quote against the current Markdown source and opens a confirmation queue. Only `ready` comments are selectable. `ambiguous`, `missing`, duplicate, or invalid proposals are shown but never guessed or written. Confirmation calls the adapter's atomic, revision-guarded batch method:

```text
createComments({ comments, baseRev, actor, source }) -> { comments, rev }
```

For programmatic hosts, `editor.previewCommentBatch(response)` opens the same queue directly. HTTP hosts provide a separate `commentsBatchUrl`; the endpoint receives `comments`, `base_rev`, `actor`, and `source`.

## Adapter contract

An adapter declares the operations it can actually honor. Missing methods are
not simulated by the component:

```js
adapter.capabilities = {
  savePolicy: 'explicit', // or 'immediate'
  document: { load: true, save: true, replace: false },
  comments: { list: true, create: true, batch: true, update: true, delete: true },
  events: { list: true },
  assets: { resolve: true },
};
```

The safe default is `explicit`. Built-in memory, browser-storage, and generic
HTTP adapters opt into `immediate`. ResearchLab uses `explicit`; its draft stays
in the browser until the user presses Save. An adapter may implement these
asynchronous methods:

```text
load() -> { title, body, rev }
save({ body, baseRev, actor }) -> { title, body, rev }
listComments() -> Comment[]
createComment(comment) -> Comment
createComments({ comments, baseRev, actor, source }) -> { comments, rev }
updateComment(id, patch) -> Comment
deleteComment(id) -> void
listEvents() -> EditEvent[]
resolveAsset({ src, document }) -> URL string
```

`theme="scientific"` selects the white, figure-safe manuscript surface used by
Review Studio. The component adds image captions from Markdown alt text, a
lightbox, explicit load-failure fallbacks, horizontally scrollable wide tables,
and adapter-mediated local asset URLs. Hosts retain filesystem and network
authority; the component never opens a local path directly.

`save` must reject stale `baseRev` values with `RevisionConflictError`. The component never owns filesystem, Chrome, or AI permissions.

The HTTP adapter preserves host-supplied conflict-draft metadata on
`RevisionConflictError`; Review Studio uses that generic error field to open
its recovery center. Snapshot storage, diff/restore, and export remain host
services and are intentionally not added to editor-core.

`apps/review-studio/` now consumes this public component for rendering, source
and block editing, comments, anchors, and AI comment batches. The host retains
review history, multi-turn finding decisions, provider selection, and
idempotent writeback. It no longer ships copied `markdown.js` or `anchor.js`.

Review Studio also composes a separate quote-scoped conversation surface. A
selection can receive a transient quick explanation or start a persistent
Codex/Claude discussion with reply comments and branch lineage. Each assistant
message offers an explicit, editable `write back as comment` gate. Conversation
history is not document history and stays in the host under
`data/conversations/`; editor-core only emits the selected quote contract.

Review Studio's `导入主稿` action stages a local UTF-8 Markdown or DOCX, shows
the conversion receipt, and creates a new no-overwrite canonical Markdown only
after confirmation. DOCX conversion is a pinned Mammoth → sanitized HTML →
Turndown/GFM pipeline inside a no-network macOS sandbox. `参考资料` stores a PDF
as a separate page-provenanced EvidenceSource; it enters a new discussion or AI
Review only when explicitly checked. See
[docs/SCIENTIFIC_IMPORT_V0.md](docs/SCIENTIFIC_IMPORT_V0.md) for the threat
model, storage contract, extraction thresholds, and remaining product gates.

## Chrome extension

Build the wrapper:

```bash
npm run build:chrome
```

Then load `release/chrome-extension/` as an unpacked extension in `chrome://extensions`.

The extension requests only `sidePanel`, `storage`, `activeTab`, and `scripting`. Page capture occurs only after the user clicks **Capture page**. It has no persistent host permissions and does not read cookies or browser profiles.

## Product boundary

The editor-core boundary deliberately excludes:

- bundled Codex or Claude execution inside the reusable component (the optional Review Studio host provides a guarded local CLI integration);
- background access to arbitrary pages;
- local filesystem access without a host adapter;
- CRDT/multi-cursor real-time collaboration;
- MCP transport.

Those are integrations around the document service, not editor-core responsibilities.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [PROVENANCE.md](PROVENANCE.md).
