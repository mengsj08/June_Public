import { LocalStorageDocumentAdapter } from '../src/index.js';

const SAMPLE = `# A document should remember why it changed

Comma Editor treats **Markdown as the source of truth**. The rendered page is an interface, not a second document format.

## The small contract

1. Use the explicit Edit block control to edit Markdown in place.
2. Select a sentence to attach a durable margin note.
3. Open **Source** when a whole-document edit is clearer.
4. Every save carries a revision, so stale work cannot overwrite a newer draft.

> A mature component is defined by its boundary, not by the number of buttons it contains.

Inline mathematics remains source faithful: $C = \\sum_i p_i \\cdot u_i$.

| Surface | Responsibility |
| --- | --- |
| Web Component | Human editing interface |
| Adapter | Storage and revision boundary |
| Chrome wrapper | Explicit page capture and browser storage |
| Future MCP | Semantic agent operations |

\`\`\`mermaid
flowchart LR
  A[Host] --> B[Comma Editor]
  B --> C[Document Adapter]
  C --> D[(Markdown)]
\`\`\`
`;

const adapter = new LocalStorageDocumentAdapter({
  key: 'comma-editor-standalone-v1',
  seed: { title: 'comma-principles.md', body: SAMPLE },
});

const editor = document.querySelector('#editor');
const hostState = document.querySelector('#host-state');
editor.adapter = adapter;
editor.toolbarActions = [
  { id: 'source', label: 'Source', slot: 'primary', appliesTo: 'document.save' },
  { id: 'ai-review', label: 'AI review', slot: 'primary', appliesTo: { capability: 'document.load', requiresCleanDocument: true } },
  { id: 'overall-comment', label: 'Overall note', slot: 'primary', appliesTo: 'comments.create' },
  { id: 'comments', label: 'Comments', slot: 'primary', appliesTo: 'comments.list', count: 'comments' },
];

editor.addEventListener('comma-toolbar-action', (event) => {
  if (event.detail.actionId === 'source') editor.openSourceEditor();
  if (event.detail.actionId === 'ai-review') editor.requestAiReview();
  if (event.detail.actionId === 'overall-comment') editor.openOverallCommentComposer();
  if (event.detail.actionId === 'comments') editor.toggleComments();
});

editor.addEventListener('comma-save', () => { hostState.textContent = 'host saw save'; });
editor.addEventListener('comma-comment-create', () => { hostState.textContent = 'host saw note'; });
editor.addEventListener('comma-ai-request', (event) => {
  if (event.detail.mode === 'comment-batch') {
    hostState.textContent = `host received review request · rev ${event.detail.document.rev.replace('sha256-', '').slice(0, 8)}`;
  } else {
    hostState.textContent = `AI request emitted · ${event.detail.quoteText.length} chars`;
  }
});
editor.addEventListener('comma-comment-batch-create', (event) => {
  hostState.textContent = `host wrote ${event.detail.comments.length} reviewed note${event.detail.comments.length === 1 ? '' : 's'}`;
});

document.querySelector('#reset').addEventListener('click', async () => {
  await adapter.replace({ title: 'comma-principles.md', body: SAMPLE, actor: 'system' });
  await editor.load();
  hostState.textContent = 'sample reset';
});
