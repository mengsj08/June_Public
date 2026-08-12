import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { marked } from 'marked';
import {
  createSourceLocator,
  findQuoteMatches,
  normalizeQuoteText,
  resolveQuote,
} from '../src/core/anchors.js';
import { replaceBlock, segmentMarkdown } from '../src/core/blocks.js';
import { previewCommentBatch } from '../src/core/comment-batch.js';
import { buildSectionIndex, sectionForBlock } from '../src/core/section-index.js';
import { stabilizeImageLabelBackticks } from '../src/element/markdown-renderer.js';
import { buildCommaActionState } from '../src/element/action-state.js';
import { revisionOf } from '../src/core/revision.js';
import {
  isCommentVisible,
  normalizeComment,
  normalizeFinding,
  normalizeConversationSession,
  normalizeReviewSession,
  normalizeWritebackReceipt,
} from '../src/core/models.js';
import { assertDocumentAdapter, resolveAdapterCapabilities } from '../src/core/adapter-contract.js';

test('revision is deterministic and content-sensitive', async () => {
  assert.equal(await revisionOf('alpha'), await revisionOf('alpha'));
  assert.notEqual(await revisionOf('alpha'), await revisionOf('beta'));
});

test('conversation models preserve quote scope, branch lineage, notes, and writeback identity', () => {
  const session = normalizeConversationSession({
    id: 'conversation-1', doc_path: 'paper.md', base_rev: 'r1',
    source_quote: { quote_text: 'Exact passage.', source_locator: { text_index: 14 } },
    messages: [{
      id: 'm2', role: 'assistant', content: 'Scoped answer', parent_id: 'm1',
      branch_id: 'branch-a', branch_from_message_id: 'm0', writeback_comment_id: 'c-1',
    }, { id: 'n1', role: 'note', content: 'PI note', note_for_message_id: 'm2' }],
  });
  assert.equal(session.documentId, 'paper.md');
  assert.equal(session.sourceQuote.quoteText, 'Exact passage.');
  assert.equal(session.messages[0].parentId, 'm1');
  assert.equal(session.messages[0].branchFromMessageId, 'm0');
  assert.equal(session.messages[0].writebackCommentId, 'c-1');
  assert.equal(session.messages[1].noteForMessageId, 'm2');
});

test('block segmentation reconstructs source byte-for-byte', () => {
  const source = '# Title\n\nParagraph with $x$.\n\n```js\nconst a = 1;\n```\n';
  const blocks = segmentMarkdown(marked.lexer, source);
  assert.ok(blocks.length >= 3);
  for (const block of blocks) assert.equal(source.slice(block.start, block.end), block.raw);
  const target = blocks.find((block) => block.type === 'paragraph');
  const changed = replaceBlock(source, target, target.raw.replace('Paragraph', 'Edited paragraph'));
  assert.equal(changed, source.slice(0, target.start) + target.raw.replace('Paragraph', 'Edited paragraph') + source.slice(target.end));
});

test('section index derives deterministic heading ranges without semantic guessing', () => {
  const source = '# Abstract\n\nIntro.\n\n## Method\n\nA.\n\nA repeated phrase.\n\n## Method\n\nB.\n';
  const blocks = segmentMarkdown(marked.lexer, source);
  const sections = buildSectionIndex(blocks);
  assert.deepEqual(sections.map((section) => section.id), ['sec-abstract', 'sec-method', 'sec-method-2']);
  assert.deepEqual(sections.map((section) => [section.startBlockIndex, section.endBlockIndex]), [[0, 1], [2, 4], [5, 6]]);
  assert.equal(sectionForBlock(sections, 3).id, 'sec-method');
  assert.equal(sectionForBlock(sections, 6).id, 'sec-method-2');
});

test('scientific layout CSS preserves the SKL-100 breakpoint and breakout contract', () => {
  const componentCss = readFileSync(new URL('../src/element/comma-editor.css', import.meta.url), 'utf8');
  const hostCss = readFileSync(new URL('../apps/review-studio/static/editor.css', import.meta.url), 'utf8');
  assert.match(componentCss, /@media \(min-width: 1600px\)/);
  assert.match(componentCss, /\.ce-shell\.outline-open\[data-outline-mode="expanded"\] \.ce-grid[\s\S]*grid-template-columns:\s*clamp\(180px,\s*11vw,\s*240px\)\s+minmax\(0,\s*1fr\)\s+clamp\(360px,\s*20vw,\s*420px\)/);
  assert.match(componentCss, /@media \(min-width: 1900px\)[\s\S]*\.ce-shell\.outline-open\[data-outline-mode="expanded"\] \.ce-grid[\s\S]*grid-template-columns:\s*180px\s+minmax\(0,\s*1fr\)\s+clamp\(360px,\s*20vw,\s*420px\)/);
  assert.match(componentCss, /@media \(min-width: 1100px\) and \(max-width: 1599px\)/);
  assert.match(componentCss, /@media \(min-width: 821px\) and \(max-width: 1099px\)/);
  assert.match(componentCss, /@media \(max-width: 820px\)/);
  assert.match(componentCss, /\.ce-shell\.outline-open\[data-outline-mode="collapsed"\] \.ce-outline[\s\S]*display:\s*block/);
  assert.match(componentCss, /\.ce-shell\.outline-open\[data-outline-mode="drawer"\] \.ce-outline[\s\S]*display:\s*block/);
  assert.doesNotMatch(componentCss, /\.ce-outline-toggle\s*\{[^}]*display:\s*none/);
  assert.match(componentCss, /\.ce-outline-item/);
  assert.match(componentCss, /\.ce-block\.ce-breakout[\s\S]*width:\s*min\(1300px,\s*100cqi\)/);
  assert.match(componentCss, /\.ce-table-scroll[\s\S]*overflow-x:\s*auto/);
  assert.match(componentCss, /\.ce-code-copy/);
  assert.match(componentCss, /\.ce-image-fallback/);
  assert.match(componentCss, /:host\(\[embedded-chrome\]\) \.ce-shell[\s\S]*box-shadow:\s*none/);
  assert.match(hostCss, /overflow-x:\s*clip/);
  assert.match(hostCss, /\.doc-header[\s\S]*grid-template-columns:\s*auto minmax\(190px,\s*1fr\) auto auto/);
  assert.match(hostCss, /@media \(min-width: 761px\) and \(max-width: 1099px\)[\s\S]*\.doc-header[\s\S]*grid-template-columns:\s*auto minmax\(180px,\s*1fr\) auto auto/);
  assert.match(hostCss, /width:\s*min\(1792px,\s*calc\(100% - 64px\)\)/);
});

test('review studio AI surfaces keep Slice C placeholders disciplined', () => {
  const html = readFileSync(new URL('../apps/review-studio/static/editor.html', import.meta.url), 'utf8');
  const script = readFileSync(new URL('../apps/review-studio/static/app.js', import.meta.url), 'utf8');
  const header = html.match(/<header class="doc-header">[\s\S]*?<\/header>/)?.[0] || '';
  const aiTools = html.match(/<aside id="ai-tools-popover"[\s\S]*?<\/aside>/)?.[0] || '';
  const reviewLauncher = html.match(/<div class="review-launcher">[\s\S]*?<div id="review-run-state"/)?.[0] || '';
  assert.deepEqual([...aiTools.matchAll(/<button id="([^"]+)"/g)].map((match) => match[1]), []);
  assert.match(aiTools, /data-disabled-until="SKL-101"/);
  assert.match(script, /id:\s*'import-manuscript'[\s\S]*label:\s*'导入'/);
  assert.match(script, /id:\s*'evidence'[\s\S]*label:\s*'参考资料'/);
  assert.doesNotMatch(script, /id:\s*'ai-tools'[\s\S]*label:\s*'AI 工具'/);
  assert.doesNotMatch(aiTools, /Zotero|Obsidian|改写|生成摘要|新建评审Agent/i);
  assert.doesNotMatch(header, /btn-import|btn-evidence|btn-quick-explain|btn-selection-discuss/);
  assert.doesNotMatch(header, /Zotero|Obsidian/i);
  assert.deepEqual([...reviewLauncher.matchAll(/name="review-tool" value="([^"]+)"/g)].map((match) => match[1]), [
    'bigapple',
    'codex',
    'claude',
  ]);
  assert.match(reviewLauncher, /name="review-tool" value="codex" checked/);
  assert.match(reviewLauncher, /<strong>APR<\/strong>/);
});

test('renderer preserves image syntax when alt text contains TeX-style backticks', () => {
  const source = "![An example `making'.](assets/vis/making.png)\n\n```md\n![Code `sample'.](x.png)\n```";
  const stable = stabilizeImageLabelBackticks(source);
  assert.ok(stable.includes("![An example \\`making'.](assets/vis/making.png)"));
  assert.ok(stable.includes("```md\n![Code `sample'.](x.png)\n```"));
  const tokens = marked.lexer(stable);
  assert.equal(tokens[0].tokens[0].type, 'image');
  assert.equal(tokens[0].tokens[0].href, 'assets/vis/making.png');
});

test('anchors resolve unique, contextual, ambiguous, and missing quotes', () => {
  const body = 'First repeated phrase.\n\nMiddle.\n\nSecond repeated phrase.';
  const quote = 'repeated phrase';
  assert.deepEqual(findQuoteMatches(body, quote).length, 2);
  const locator = createSourceLocator(body, quote, { rev: 'old' });
  locator.prefix = 'First ';
  locator.suffix = '.\n\nMiddle';
  assert.equal(resolveQuote(body, quote, locator, 'new').state, 'context');
  assert.equal(resolveQuote(body, quote, {}, 'new').state, 'ambiguous');
  assert.equal(resolveQuote(body, 'Middle', {}, 'new').state, 'unique');
  assert.equal(resolveQuote(body, 'absent', {}, 'new').state, 'missing');
  assert.equal(normalizeQuoteText(' a\n  b '), 'a b');
});

test('selection locators disambiguate repeated quotes through the selected source block', () => {
  const body = 'Repeated phrase.\n\nMiddle.\n\nRepeated phrase.';
  const secondStart = body.lastIndexOf('Repeated phrase.');
  const locator = createSourceLocator(body, 'Repeated phrase.', {
    rev: 'same', blockIndex: 2, blockStart: secondStart, blockEnd: body.length,
  });
  assert.equal(locator.textIndex, secondStart);
  assert.equal(locator.occurrenceIndex, 1);
  assert.equal(locator.endBlockIndex, 2);
  assert.equal(resolveQuote(body, 'Repeated phrase.', locator, 'same').index, secondStart);
});

test('selection locators retain multi-block range boundaries', () => {
  const body = 'First paragraph.\n\nSecond paragraph.';
  const locator = createSourceLocator(body, body, {
    rev: 'same', blockIndex: 0, endBlockIndex: 1, blockStart: 0, blockEnd: body.length,
  });
  assert.equal(locator.blockIndex, 0);
  assert.equal(locator.endBlockIndex, 1);
  assert.equal(locator.textIndex, 0);
});

test('comment batch preview separates ready, ambiguous, missing, and invalid proposals', () => {
  const body = '# Review\n\nUnique sentence.\n\nRepeated phrase.\n\nRepeated phrase.\n';
  const preview = previewCommentBatch({
    body,
    rev: 'sha256-current',
    comments: [
      { quote_text: 'Unique sentence.', content: 'Add evidence.', priority: 'p0' },
      { quote_text: 'Repeated phrase.', content: 'Clarify this.' },
      { quote_text: 'Absent sentence.', content: 'Cannot anchor.' },
      { quote_text: 'Unique sentence.', content: '' },
      { kind: 'overall', content: 'Strengthen the central thesis.' },
    ],
  });
  assert.deepEqual(preview.counts, { total: 5, ready: 2, ambiguous: 1, missing: 1, invalid: 1 });
  const anchored = preview.items[0];
  assert.equal(anchored.status, 'ready');
  assert.equal(anchored.comment.priority, 'P0');
  assert.equal(anchored.comment.sourceLocator.textIndex, body.indexOf('Unique sentence.'));
  assert.equal(preview.items[1].matches.length, 2);
  assert.equal(preview.items[4].comment.kind, 'overall');
});

test('comment batch preview rejects duplicate proposals without guessing', () => {
  const input = { quote_text: 'One.', content: 'Check.' };
  const preview = previewCommentBatch({ body: 'One.', rev: 'r1', comments: [input, input] });
  assert.equal(preview.counts.ready, 1);
  assert.equal(preview.counts.invalid, 1);
  assert.match(preview.items[1].reason, /Duplicate/);
});

test('comment lifecycle and finding state normalize as orthogonal dimensions', () => {
  const legacyFinding = normalizeComment({
    id: 'c-legacy', kind: null, quote_text: 'Exact quote.', source_locator: { text_index: 4 },
    review_state: 'withdrawn', comment_version: 7, human_edited: true,
    review_run_id: 'run-1', applied_signature: 'sig-1', applied_operation_id: 'op-1',
    replies: [{ id: 'reply-1', author: 'June', content: 'Follow-up.', state: 'active' }],
  });
  assert.equal(legacyFinding.kind, 'anchored');
  assert.equal(legacyFinding.lifecycleState, 'active');
  assert.equal(legacyFinding.findingState, 'withdrawn');
  assert.equal(legacyFinding.commentVersion, 7);
  assert.equal(legacyFinding.humanEdited, true);
  assert.equal(legacyFinding.reviewRunId, 'run-1');
  assert.equal(legacyFinding.appliedSignature, 'sig-1');
  assert.equal(legacyFinding.appliedOperationId, 'op-1');
  assert.equal(legacyFinding.replies[0].actor, 'June');
  assert.equal(isCommentVisible(legacyFinding), false);

  const camelMarkers = normalizeComment({
    content: 'Camel aliases.', reviewRunId: 'run-2',
    appliedSignature: 'sig-2', appliedOperationId: 'op-2',
  });
  assert.equal(camelMarkers.reviewRunId, 'run-2');
  assert.equal(camelMarkers.appliedSignature, 'sig-2');
  assert.equal(camelMarkers.appliedOperationId, 'op-2');

  const userWithdrawn = normalizeComment({
    content: 'Manual note.', lifecycle_state: 'withdrawn', finding_state: 'accepted',
  });
  assert.equal(userWithdrawn.lifecycleState, 'withdrawn');
  assert.equal(userWithdrawn.findingState, 'accepted');
  assert.equal(isCommentVisible(userWithdrawn), false);
  assert.equal(isCommentVisible(userWithdrawn, { showWithdrawn: true }), true);
});

test('review models normalize legacy snake_case without losing writeback identity', () => {
  const finding = normalizeFinding({
    id: 'F001', quote_text: 'Exact quote.', evidence_requirement: 'PMID',
    anchor_state: 'ready', applied_comment_id: 'c-1', decision: 'accepted',
  });
  assert.equal(finding.quoteText, 'Exact quote.');
  assert.equal(finding.appliedCommentId, 'c-1');
  const receipt = normalizeWritebackReceipt({ base_rev: 'r1', created: ['c-1'], skipped: ['F002'] });
  assert.equal(receipt.baseRev, 'r1');
  const session = normalizeReviewSession({
    id: 'review-1', doc_path: 'paper.md', base_rev: 'r1', findings: [finding],
    writeback_receipts: [receipt],
  });
  assert.equal(session.documentId, 'paper.md');
  assert.equal(session.findings[0].id, 'F001');
  assert.equal(session.writebackReceipts.length, 1);
});

test('adapter capabilities distinguish a valid document-only host', () => {
  const adapter = { async load() { return {}; }, async save() { return {}; } };
  const capabilities = assertDocumentAdapter(adapter, { writable: true });
  assert.equal(capabilities.document.save, true);
  assert.equal(capabilities.comments.create, false);
  assert.equal(capabilities.assets.resolve, false);
  assert.equal(capabilities.savePolicy, 'explicit');
  assert.equal(resolveAdapterCapabilities({ capabilities: { comments: { create: true } } }).comments.create, false);
});

test('adapter capabilities expose asset resolution only when implemented', () => {
  const adapter = {
    async load() { return {}; },
    resolveAsset({ src }) { return `/asset?source=${encodeURIComponent(src)}`; },
    capabilities: { assets: { resolve: true } },
  };
  assert.equal(resolveAdapterCapabilities(adapter).assets.resolve, true);
  assert.equal(resolveAdapterCapabilities({ capabilities: { assets: { resolve: true } } }).assets.resolve, false);
});

test('comma action state projects toolbar availability and comment counts from one source', () => {
  const state = buildCommaActionState({
    document: { title: 'paper.md', body: '# Title\n\nBody.', rev: 'sha256-abcdef123456' },
    dirty: true,
    readonly: false,
    savePolicy: 'immediate',
    capabilities: {
      document: { load: true, save: true },
      comments: { list: true, create: true, update: false },
    },
    toolbarActions: [
      { id: 'overview', label: '文章总览', slot: 'primary', appliesTo: 'document.load' },
      { id: 'ai-review', label: 'AI Review', slot: 'primary', appliesTo: { capability: 'document.load', requiresCleanDocument: true }, loading: true },
      { id: 'comments', label: '批注', slot: 'primary', appliesTo: 'comments.list', count: 'comments' },
      { id: 'accept-provisional', label: '接受暂定', slot: 'overflow', appliesTo: 'comments.update' },
    ],
    comments: [
      normalizeComment({ id: 'c1', content: 'Visible.' }),
      normalizeComment({ id: 'c2', content: 'Hidden.', lifecycle_state: 'withdrawn' }),
    ],
    commentsRev: 'comments-2',
    outlineOpen: true,
    outlineMode: 'expanded',
    outlinePreference: 'open',
    sectionIndex: [{ id: 'sec-title', title: 'Title' }],
    activeSectionId: 'sec-title',
    status: { kind: 'saving', text: 'Saving' },
  });
  assert.equal(state.schemaVersion, 'comma-action-state/v1');
  assert.equal(state.document.shortRev, 'abcdef12');
  assert.equal(state.document.lineCount, 3);
  assert.equal(state.comments.count, 1);
  assert.deepEqual(state.outline, {
    open: true,
    mode: 'expanded',
    preference: 'open',
    sectionCount: 1,
    activeSectionId: 'sec-title',
    activeSectionTitle: 'Title',
  });
  assert.deepEqual(state.toolbar.primary.map((action) => action.id), ['overview', 'ai-review', 'comments']);
  assert.equal(state.toolbar.primary.find((action) => action.id === 'comments').count, 1);
  assert.equal(state.toolbar.primary.find((action) => action.id === 'ai-review').enabled, false);
  assert.equal(state.toolbar.primary.find((action) => action.id === 'ai-review').reason, 'dirty');
  assert.equal(state.toolbar.actions.some((action) => action.id === 'accept-provisional'), false);
});

test('comment lifecycle capabilities require the declared adapter methods', () => {
  const adapter = {
    async load() { return {}; },
    async listComments() { return []; },
    async restoreComment() {},
    async createCommentReply() {},
    async updateCommentReply() {},
    async deleteCommentReply() {},
    async listCommentEvents() { return []; },
    capabilities: {
      comments: { list: true, restore: true, reply: true, history: true },
    },
  };
  const capabilities = resolveAdapterCapabilities(adapter);
  assert.equal(capabilities.comments.restore, true);
  assert.equal(capabilities.comments.reply, true);
  assert.equal(capabilities.comments.history, true);
  assert.equal(resolveAdapterCapabilities({
    ...adapter,
    deleteCommentReply: undefined,
  }).comments.reply, false);
});
