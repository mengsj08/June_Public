import { ChromeStorageDocumentAdapter } from './dist/comma-editor.js';

const adapter = new ChromeStorageDocumentAdapter({
  key: 'comma-editor-chrome-document-v1',
  seed: {
    title: 'captured-page.md',
    body: '# Comma Editor\n\nClick **Capture page** to explicitly copy readable text from the active tab into this local Chrome profile.',
  },
});

const editor = document.querySelector('#editor');
const captureButton = document.querySelector('#capture');
const status = document.querySelector('#chrome-status');
editor.adapter = adapter;
editor.toolbarActions = [
  { id: 'source', label: 'Source', slot: 'primary', appliesTo: 'document.save' },
  { id: 'ai-review', label: 'AI review', slot: 'primary', appliesTo: { capability: 'document.load', requiresCleanDocument: true } },
  { id: 'overall-comment', label: 'Overall note', slot: 'overflow', appliesTo: 'comments.create' },
  { id: 'comments', label: 'Comments', slot: 'overflow', appliesTo: 'comments.list', count: 'comments' },
];

editor.addEventListener('comma-toolbar-action', (event) => {
  if (event.detail.actionId === 'source') editor.openSourceEditor();
  if (event.detail.actionId === 'ai-review') editor.requestAiReview();
  if (event.detail.actionId === 'overall-comment') editor.openOverallCommentComposer();
  if (event.detail.actionId === 'comments') editor.toggleComments();
});

function captureReadablePage() {
  const root = document.querySelector('article, main, [role="main"]') || document.body;
  const parts = [`# ${document.title || 'Captured page'}`, '', `> Source: ${location.href}`, ''];
  const nodes = root.querySelectorAll('h1, h2, h3, h4, p, li, blockquote, pre');
  for (const node of nodes) {
    if (node.closest('nav, header, footer, aside, script, style, noscript')) continue;
    const text = (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
    if (!text || text.length < 2) continue;
    const tag = node.tagName.toLowerCase();
    if (/^h[1-4]$/.test(tag)) parts.push(`${'#'.repeat(Number(tag[1]) + 1)} ${text}`, '');
    else if (tag === 'li') parts.push(`- ${text}`);
    else if (tag === 'blockquote') parts.push(`> ${text}`, '');
    else if (tag === 'pre') parts.push('```', text, '```', '');
    else parts.push(text, '');
    if (parts.join('\n').length > 180000) break;
  }
  return {
    title: `${document.title || 'captured-page'}.md`.replace(/[\\/:*?"<>|]+/g, '-'),
    body: parts.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n',
    url: location.href,
  };
}

captureButton.addEventListener('click', async () => {
  captureButton.disabled = true;
  status.textContent = 'Reading the active tab after your explicit request…';
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !/^https?:/.test(tab.url || '')) throw new Error('Open a normal web page before capturing.');
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: captureReadablePage });
    if (!result?.body) throw new Error('No readable page text found.');
    await editor.replaceDocument({ title: result.title, body: result.body, actor: 'chrome-capture' });
    status.textContent = `Captured ${result.body.length.toLocaleString()} characters from ${new URL(result.url).hostname}.`;
  } catch (error) {
    status.textContent = error.message || 'Capture failed.';
  } finally {
    captureButton.disabled = false;
  }
});

editor.addEventListener('comma-ai-request', (event) => {
  status.textContent = event.detail.mode === 'comment-batch'
    ? 'Structured review requested. Connect a Codex or Claude host and return comments through detail.accept(response).'
    : 'AI request emitted. Install a host adapter to connect Codex or Claude.';
});
