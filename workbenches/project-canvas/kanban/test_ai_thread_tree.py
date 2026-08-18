#!/usr/bin/env python3
"""Tests for AI thread tree rendering helpers."""

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_AI_MODULE = _HERE / 'static' / 'kanban' / 'modules' / 'ai.js'
_AI_THREADS_MODULE = _HERE / 'static' / 'kanban' / 'modules' / 'ai-threads.js'
_AI_QUEUE_MODULE = _HERE / 'static' / 'kanban' / 'modules' / 'ai-queue.js'
_AI_MODULES = (_AI_MODULE, _AI_THREADS_MODULE, _AI_QUEUE_MODULE)


def test_ai_thread_tree_keeps_orphan_forks_renderable():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ setupAi }} from {str(_AI_MODULE.as_uri())!r};
      import {{ setupAiThreads }} from {str(_AI_THREADS_MODULE.as_uri())!r};
      import {{ setupAiQueue }} from {str(_AI_QUEUE_MODULE.as_uri())!r};

      const ctx = {{
        dataState: {{}},
        uiState: {{
          ai: {{ cachedSkills: null, threadTree: null, pollTimers: {{}} }},
          auth: {{ currentUser: '' }},
          detail: {{
            currentTaskPath: 'project/X/card.md',
            currentTaskStatus: '',
            currentTaskBody: '# Title\\n\\n## Methods\\n\\nbefore quoted phrase after',
            currentTaskRev: 'rev-1',
            isEditMode: true,
          }},
          queue: {{}},
        }},
        ui: {{ isMobile: () => false, toast: () => {{}} }},
        markdown: {{
          looksLikeMarkdown: () => false,
          renderMarkdownEnhanced: () => {{}},
          _fmHandleInput: () => {{}},
          _fmHandleKeydown: () => {{}},
          _fmHide: () => {{}},
        }},
        el: {{
          aiActivity: {{}},
          aiActivityList: {{}},
          detailClaudeBtn: null,
          detailCodexBtn: null,
          btnQueue: {{}},
          queueOverlay: {{}},
          queueSidebar: {{}},
          queueCloseBtn: {{}},
          processedBadge: {{}},
          runningCount: {{}},
          queuedCount: {{}},
          queueTabProcessed: {{}},
          queueTabRunning: {{}},
          queueTabQueued: {{}},
          queueBadge: {{}},
          detailQueueBadge: {{}},
          detailMdContent: {{ querySelectorAll: () => [] }},
          detailEditMode: null,
          detailEditor: null,
        }},
        hasApi: false,
      }};
      setupAi(ctx);
      setupAiThreads(ctx);
      setupAiQueue(ctx);

      const results = [
        {{ run_id: 'parent', timestamp: '2026-07-08T10:00:00', messages: [] }},
        {{
          run_id: 'child',
          timestamp: '2026-07-08T10:01:00',
          metadata: {{ fork: {{ parent_run_id: 'parent', parent_index: 0 }} }},
          messages: [],
        }},
        {{
          run_id: 'orphan',
          timestamp: '2026-07-08T10:02:00',
          metadata: {{ fork: {{ parent_run_id: 'missing-parent', parent_index: 0 }} }},
          messages: [],
        }},
      ];
      const tree = ctx.ai._test.buildThreadTree(results);
      const mainlineIDs = ctx.ai._test.branchMainline(results, tree.byRunId).map((entry) => entry.run_id);
      if (JSON.stringify(mainlineIDs) !== JSON.stringify(['parent', 'orphan'])) {{
        throw new Error(`expected missing-parent fork to remain visible, got ${{mainlineIDs.join(',')}}`);
      }}
      const childIDs = tree.childrenOf.get('parent').get('0').map((entry) => entry.run_id);
      if (JSON.stringify(childIDs) !== JSON.stringify(['child'])) {{
        throw new Error(`expected real child to remain nested, got ${{childIDs.join(',')}}`);
      }}
      const branchCtx = {{ childrenOf: tree.childrenOf, byRunId: tree.byRunId, depth: 0 }};
      if (!ctx.ai._test.hasRenderableParent(results[1], branchCtx)) {{
        throw new Error('expected real child to be replaced as a branch node during polling');
      }}
      if (ctx.ai._test.hasRenderableParent(results[2], branchCtx)) {{
        throw new Error('expected orphan child to be replaced as a top-level thread during polling');
      }}

      const block = {{}};
      ctx.el.detailMdContent.querySelectorAll = () => [block];
      const sourceQuote = ctx.ai._test.sourceQuoteFromSelection('quoted phrase', {{
        commonAncestorContainer: {{ nodeType: 1, closest: () => block }},
      }});
      if (sourceQuote.quote_text !== 'quoted phrase' || sourceQuote.section !== 'Methods') {{
        throw new Error('selection did not capture quote text and section');
      }}
      if (sourceQuote.source_locator.task_path !== 'project/X/card.md'
          || sourceQuote.source_locator.text_index < 0
          || sourceQuote.source_locator.block_index !== 0) {{
        throw new Error('selection locator is incomplete');
      }}
      if (!sourceQuote.context.prefix.endsWith('before ') || !sourceQuote.context.suffix.startsWith(' after')) {{
        throw new Error('selection context is incomplete');
      }}
      const quickPrompt = ctx.ai._test.selectionQuickPrompt(sourceQuote);
      if (!quickPrompt.includes('快速解释') || !quickPrompt.includes('所在章节：Methods')
          || !quickPrompt.includes('before quoted phrase after')) {{
        throw new Error('quick explanation prompt did not preserve task and paragraph context');
      }}
      if (ctx.ai._test.profileKey('quick') !== 'quick_explain') {{
        throw new Error('quick explanation profile is not pinned');
      }}
      if (ctx.ai._test.profileKey('deep', 'claude') !== 'deep_claude'
          || ctx.ai._test.profileKey('deep', 'codex') !== 'deep_codex') {{
        throw new Error('deep chat profiles are not routed by tool');
      }}
      if (ctx.ai._test.profileKey('execute', 'claude') !== 'execute_claude'
          || ctx.ai._test.profileKey('execute', 'codex') !== 'execute_codex') {{
        throw new Error('execute profiles are not routed by tool');
      }}
      if (ctx.ai._test.profileLabel('quick_explain') !== 'Codex Luna') {{
        throw new Error('quick explanation label is not exposed');
      }}
      const durableOnly = ctx.ai._test.durableDialogueResults([
        {{ run_id: 'temporary', metadata: {{ dialogue: {{ lifecycle: 'transient' }} }} }},
        {{ run_id: 'side-chat', metadata: {{ dialogue: {{ lifecycle: 'durable_on_promotion' }} }} }},
      ]).map((entry) => entry.run_id);
      if (JSON.stringify(durableOnly) !== JSON.stringify(['side-chat'])) {{
        throw new Error('transient selection explanation leaked into durable dialogue history');
      }}
      const sideChatEntry = {{
        run_id: 'run-side',
        metadata: {{ dialogue: {{ origin: 'selection_side_chat', lifecycle: 'durable_on_promotion' }} }},
        messages: [{{ role: 'user', source_quote: sourceQuote }}],
      }};
      if (ctx.ai._test.selectionSideChatSourceQuote(sideChatEntry) !== sourceQuote) {{
        throw new Error('selection side chat did not preserve its promotion anchor');
      }}
      const selectionIdA = ctx.ai._test.stableSelectionId(sourceQuote);
      const selectionIdB = ctx.ai._test.stableSelectionId({{ ...sourceQuote }});
      if (!selectionIdA.startsWith('selection:') || selectionIdA !== selectionIdB) {{
        throw new Error('selection promotion id is not deterministic');
      }}

      const duplicated = 'A quote here. B quote here.';
      const resolved = ctx.ai._test.chooseSourceQuoteIndex({{
        quote_text: 'quote here',
        context: {{ prefix: 'A ', suffix: '. B ' }},
        source_locator: {{ text_index: 2, body_rev: 'old' }},
      }}, duplicated, 'new');
      if (resolved !== 2) throw new Error('context did not disambiguate duplicate quote');
      const stale = ctx.ai._test.chooseSourceQuoteIndex({{
        quote_text: 'quote here',
        context: {{ prefix: '', suffix: '' }},
        source_locator: {{ text_index: 2, body_rev: 'old' }},
      }}, duplicated, 'new');
      if (stale !== -1) throw new Error('ambiguous changed quote must be stale');

      if (ctx.ai._test.messageAuthorLabel({{ role: 'user', author: 'Owner' }}, {{ tool: 'codex' }}) !== 'Owner') {{
        throw new Error('Owner comment author was not preserved');
      }}
      if (ctx.ai._test.messageAuthorLabel({{ role: 'ai' }}, {{ tool: 'claude' }}) !== 'Claude') {{
        throw new Error('Claude message author was not derived from entry tool');
      }}
      if (ctx.ai._test.messageAuthorLabel({{ role: 'ai' }}, {{ tool: 'codex' }}) !== 'Codex') {{
        throw new Error('Codex message author was not derived from entry tool');
      }}

      const anchor = {{ nodeType: 3 }};
      const focus = {{ nodeType: 3 }};
      const contentA = {{ contains: (node) => node === anchor || node === focus }};
      const bubbleA = {{
        dataset: {{ entryId: 'run_a#2', quoteAuthor: 'Claude' }},
        querySelector: (selector) => selector === '.msg-content' ? contentA : null,
      }};
      const bubbleB = {{
        dataset: {{ entryId: 'run_b#0', quoteAuthor: 'Codex' }},
        querySelector: () => ({{ contains: () => true }}),
      }};
      anchor.parentElement = {{ closest: () => bubbleA }};
      focus.parentElement = {{ closest: () => bubbleA }};
      const selectedQuote = ctx.ai._test.messageQuoteFromSelection({{
        isCollapsed: false,
        rangeCount: 1,
        anchorNode: anchor,
        focusNode: focus,
        toString: () => '  only this excerpt  ',
      }});
      if (!selectedQuote || selectedQuote.ref !== 'run_a#2'
          || selectedQuote.author !== 'Claude' || selectedQuote.excerpt !== 'only this excerpt') {{
        throw new Error('single-message selection did not preserve ref, author, and excerpt');
      }}
      focus.parentElement = {{ closest: () => bubbleB }};
      const crossMessage = ctx.ai._test.messageQuoteFromSelection({{
        isCollapsed: false,
        rangeCount: 1,
        anchorNode: anchor,
        focusNode: focus,
        toString: () => 'cross message',
      }});
      if (crossMessage !== null) throw new Error('cross-message selection must be rejected');

      const editor = {{
        value: 'alphaOMEGAomega',
        selectionStart: 5,
        selectionEnd: 10,
        inputEvents: 0,
        setRangeText(text, start, end) {{
          this.value = this.value.slice(0, start) + text + this.value.slice(end);
          this.selectionStart = start + text.length;
          this.selectionEnd = this.selectionStart;
        }},
        dispatchEvent() {{ this.inputEvents += 1; }},
        focus() {{}},
      }};
      ctx.el.detailEditor = editor;
      ctx.ai._test.markEditorCursorReady();
      const persistentQuote = {{ ref: 'run_c#1', author: 'Codex', excerpt: 'selected words' }};
      const token = ctx.ai._test.createCommentQuoteToken(persistentQuote);
      const inserted = ctx.ai._test.insertCommentQuoteAtCursor(editor, persistentQuote);
      const expectedInsertion = '\\n\\n' + token + '\\n\\n';
      if (!inserted) throw new Error('comment quote was not inserted at a ready editor cursor');
      if (editor.value !== 'alpha' + expectedInsertion + 'OMEGAomega') {{
        throw new Error('cursor insertion must not delete an existing body selection');
      }}
      if (!editor.value.includes(':::comment-quote ref="run_c#1" author="Codex"\\nselected words\\n:::')) {{
        throw new Error('persistent quote token shape is wrong');
      }}
      if (editor.selectionStart !== 5 + expectedInsertion.length || editor.selectionEnd !== editor.selectionStart) {{
        throw new Error('cursor did not land after the complete inserted quote block');
      }}
      if (editor.inputEvents !== 1) throw new Error('quote insertion must dispatch input for dirty tracking');

      editor.value = 'alphaomega';
      editor.selectionStart = 5;
      editor.selectionEnd = 5;
      editor.inputEvents = 0;
      const bodyQuote = {{
        source: 'body',
        quote_text: 'quoted phrase',
        section: 'Methods',
        source_locator: {{
          task_path: 'project/X/card.md',
          body_rev: 'rev-1',
          text_index: 27,
          prefix: 'before ',
          suffix: ' after',
          block_index: 0,
        }},
      }};
      const bodyToken = ctx.ai._test.createBodyQuoteToken(bodyQuote);
      if (!bodyToken.includes('source="body"') || !bodyToken.includes('section="Methods"')
          || !bodyToken.includes('quoted phrase')) {{
        throw new Error('body quote token shape is wrong');
      }}
      const bodyInserted = ctx.ai._test.insertCommentQuoteAtCursor(editor, bodyQuote);
      if (!bodyInserted) throw new Error('body quote was not inserted at a ready editor cursor');
      if (!editor.value.includes(':::comment-quote source="body" section="Methods" locator="')) {{
        throw new Error('body quote insert did not persist a body-source token');
      }}
      if (editor.value.includes('ref="')) {{
        throw new Error('body quote token must not pretend to be a comment ref');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_reverse_comment_quote_entrypoints_are_removed():
    ai_source = '\n'.join(path.read_text(encoding='utf-8') for path in _AI_MODULES)
    html_source = (_HERE / 'kanban.html').read_text(encoding='utf-8')
    assert 'openCommentQuotePicker' not in ai_source
    assert 'editor-quote-comment-btn' not in html_source
