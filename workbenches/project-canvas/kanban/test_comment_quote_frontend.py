#!/usr/bin/env python3
"""Comment-quote renderer remains safe and does not expose the removed large picker."""

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MARKDOWN_MODULE = _HERE / 'static' / 'kanban' / 'modules' / 'markdown.js'
_DETAIL_MODULE = _HERE / 'static' / 'kanban' / 'modules' / 'render-detail.js'
_DETAIL_ACTIONS_MODULE = _HERE / 'static' / 'kanban' / 'modules' / 'render-detail-actions.js'
_DETAIL_VIEW_MODULE = _HERE / 'static' / 'kanban' / 'modules' / 'render-detail-view.js'
_HTML = _HERE / 'kanban.html'


def test_comment_quote_renderer_is_safe_without_large_picker_api():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ setupMarkdown }} from {str(_MARKDOWN_MODULE.as_uri())!r};

      globalThis.window = {{ marked: null, mermaid: null }};
      globalThis.document = {{
        addEventListener: () => {{}},
        querySelectorAll: () => [],
      }};

      const stubEl = {{
        addEventListener: () => {{}},
        classList: {{ add: () => {{}}, remove: () => {{}} }},
      }};
      const escapeHtml = (value) => String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
      const ctx = {{
        hasApi: false,
        dataState: {{ tasks: [] }},
        ui: {{ esc: escapeHtml, toast: () => {{}} }},
        uiState: {{
          auth: {{ currentUser: 'Owner' }},
          detail: {{ currentTaskPath: 'project/X/card.md' }},
          ai: {{
            currentResults: [
              {{
                run_id: 'run_a',
                tool: 'claude',
                messages: [
                  {{ role: 'user', author: 'Owner', content: '用户评论第一句。\\n第二句。' }},
                  {{ role: 'ai', content: 'AI answer with <tag>' }},
                ],
              }},
              {{
                run_id: 'run_b',
                tool: 'codex',
                messages: [{{ role: 'ai', content: 'Codex answer' }}],
              }},
            ],
            quoteHistoryLoaded: true,
          }},
          fileMention: {{
            visible: false,
            hasMore: false,
            loading: false,
            requestSeq: 0,
            debounceTimer: null,
            extCode: {{}},
            extImage: {{}},
            extDocument: {{}},
            icons: {{}},
          }},
          pendingUploadTasks: new Set(),
        }},
        el: {{
          lightboxOverlay: stubEl,
          lightboxImage: {{}},
          lightboxCaption: {{}},
          fmResults: stubEl,
          fmTabs: stubEl,
          fileMentionDd: stubEl,
        }},
      }};
      setupMarkdown(ctx);

      if (ctx.markdown.getCommentQuoteCandidates || ctx.markdown.openCommentQuotePicker) {{
        throw new Error('removed large quote picker API must stay disabled');
      }}
      const token = ':::comment-quote ref="run_a#1" author="Claude"\\nquoted <text>\\n:::';
      const html = ctx.markdown._test._renderCommentQuoteTokens(token);
      if (!html.includes('class="comment-quote-block"')) throw new Error('quote token did not render as block');
      if (!html.includes('data-comment-ref="run_a#1"')) throw new Error('rendered ref missing');
      if (!html.includes('quoted &lt;text&gt;')) throw new Error('quote text was not escaped');

      const fenced = '```\\n:::comment-quote ref="run_a#1" author="Claude"\\nno render\\n:::';
      const fencedHtml = ctx.markdown._test._renderCommentQuoteTokens(fenced);
      if (fencedHtml.includes('comment-quote-block')) throw new Error('fenced token should not render');

      const locator = encodeURIComponent(JSON.stringify({{
        task_path: 'project/X/card.md',
        text_index: 12,
        prefix: 'before ',
        suffix: ' after',
        block_index: 0,
      }}));
      const bodyToken = ':::comment-quote source="body" section="Methods" locator="' + locator + '"\\nquoted body\\n:::';
      const bodyHtml = ctx.markdown._test._renderCommentQuoteTokens(bodyToken);
      if (!bodyHtml.includes('data-source="body"')) throw new Error('body quote source marker missing');
      if (!bodyHtml.includes('引用正文 · Methods')) throw new Error('body quote label missing');
      if (!bodyHtml.includes('↩ 跳到正文原位')) throw new Error('body quote jump action missing');
      if (bodyHtml.includes('原评论不可达')) throw new Error('body quote must not render as an unreachable comment');

      const taskBody = [
        '# Background',
        'Paragraph before.',
        token,
        ':::comment-quote ref="run_a#1" author="Codex"',
        'second quote',
        ':::',
        ':::comment-quote author="No ref"',
        '<unsafe>',
        ':::',
        ':::comment-quote ref="bad ref" author="Bad ref"',
        'invalid',
        ':::',
      ].join('\\n');
      const prepared = ctx.markdown._test._prepareCommentQuoteTokens(taskBody, {{ mode: 'task-body' }});
      if (prepared.markdown.includes('comment-quote-block')) throw new Error('task body preview must not render large quote blocks');
      if ((prepared.markdown.match(/comment-quote-anchor/g) || []).length !== 4) throw new Error('task body anchors missing');
      if (prepared.commentQuotes.length !== 4) throw new Error('sidebar data count must equal token count');
      if (prepared.commentQuotes[0].heading !== 'Background') throw new Error('preceding heading context missing');
      if (prepared.commentQuotes[0].paragraph !== 'Paragraph before.') throw new Error('preceding paragraph context missing');
      if (prepared.commentQuotes[2].refStatus !== 'missing-ref') throw new Error('missing ref status not preserved');
      if (prepared.commentQuotes[3].refStatus !== 'invalid-ref') throw new Error('invalid ref status not preserved');
      if (prepared.markdown.includes('<unsafe>')) throw new Error('quote HTML must not leak into task body anchor');
      if (prepared.commentQuotes[2].quoteText !== '<unsafe>') throw new Error('escaped snapshot source text missing');

      const following = ctx.markdown._test._prepareCommentQuoteTokens(
        ':::comment-quote ref="run_b#0" author="Owner"\\nquote\\n:::\\n## Following\\nParagraph after.',
        {{ mode: 'task-body' }},
      ).commentQuotes[0];
      if (following.heading !== 'Following' || following.paragraph !== 'Paragraph after.') {{
        throw new Error('following heading/paragraph fallback missing');
      }}

      const bodyPrepared = ctx.markdown._test._prepareCommentQuoteTokens(bodyToken, {{ mode: 'task-body' }});
      if (bodyPrepared.markdown.includes('body-quote-block') || !bodyPrepared.markdown.includes('comment-quote-anchor')) {{
        throw new Error('source=body token must also be compact in task body preview');
      }}
      if (bodyPrepared.commentQuotes[0].source !== 'body') throw new Error('body source type missing from sidebar data');

      const duplicatePrepared = ctx.markdown._test._prepareCommentQuoteTokens(token + '\\n' + token, {{ mode: 'task-body' }});
      if (duplicatePrepared.commentQuotes[0].anchorKey !== duplicatePrepared.commentQuotes[1].anchorKey) {{
        throw new Error('exact duplicate base keys should be normalized by the detail DOM pass');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_comment_sidebar_dom_state_and_information_panel_contract():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ setupRenderDetail }} from {str(_DETAIL_MODULE.as_uri())!r};
      import {{ setupRenderDetailActions }} from {str(_DETAIL_ACTIONS_MODULE.as_uri())!r};
      import {{ setupRenderDetailView }} from {str(_DETAIL_VIEW_MODULE.as_uri())!r};

      class MiniClassList {{
        constructor(owner) {{ this.owner = owner; this.values = new Set(); }}
        _sync() {{ this.owner._className = [...this.values].join(' '); }}
        fromText(value) {{ this.values = new Set(String(value || '').split(/\\s+/).filter(Boolean)); this._sync(); }}
        add(...names) {{ names.forEach((name) => this.values.add(name)); this._sync(); }}
        remove(...names) {{ names.forEach((name) => this.values.delete(name)); this._sync(); }}
        contains(name) {{ return this.values.has(name); }}
        toggle(name, force) {{
          const next = force === undefined ? !this.values.has(name) : Boolean(force);
          if (next) this.values.add(name); else this.values.delete(name);
          this._sync();
          return next;
        }}
      }}
      class MiniElement {{
        constructor(tag = 'div') {{
          this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {{}}; this.attributes = {{}};
          this.classList = new MiniClassList(this); this._className = ''; this._text = ''; this.hidden = false;
          this.scrolls = 0; this.style = {{}};
        }}
        set className(value) {{ this.classList.fromText(value); }}
        get className() {{ return this._className; }}
        set textContent(value) {{ this._text = String(value || ''); this.children = []; }}
        get textContent() {{ return this._text + this.children.map((child) => child.textContent).join(''); }}
        appendChild(child) {{ this.children.push(child); child.parentElement = this; return child; }}
        prepend(child) {{ this.children.unshift(child); child.parentElement = this; return child; }}
        setAttribute(name, value) {{ this.attributes[name] = String(value); }}
        scrollIntoView() {{ this.scrolls += 1; }}
        querySelectorAll(selector) {{
          const all = [];
          const visit = (node) => {{ node.children.forEach((child) => {{ all.push(child); visit(child); }}); }};
          visit(this);
          return all.filter((node) => {{
            if (selector === '[data-comment-anchor]') return node.dataset.commentAnchor !== undefined;
            if (selector === '[data-comment-anchor-card]') return node.dataset.commentAnchorCard !== undefined;
            if (selector === '.comment-sidebar-original[data-comment-ref]') return node.classList.contains('comment-sidebar-original') && node.dataset.commentRef !== undefined;
            if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
            return false;
          }});
        }}
      }}

      const local = new Map();
      globalThis.localStorage = {{ setItem: (key, value) => local.set(key, value), getItem: (key) => local.get(key) || null }};
      globalThis.window = {{ flatpickr: null, matchMedia: () => ({{ matches: false }}) }};
      globalThis.document = {{ createElement: (tag) => new MiniElement(tag), querySelectorAll: () => [] }};
      globalThis.setTimeout = () => 0;
      const el = new Proxy({{}}, {{ get(target, key) {{ if (!target[key]) target[key] = new MiniElement(); return target[key]; }} }});
      const ctx = {{
        hasApi: false,
        api: {{
          fetchTaskByCode: async () => ({{
            ok: true,
            task: {{ path: 'project/X/card.md', title: 'Detail smoke', body: '', status: 'todo', priority: 'medium', tags: [] }},
          }}),
        }},
        dataState: {{}},
        uiState: {{ detail: {{ sidebarTab: 'info', sidebarFolded: false, commentQuotes: [] }}, ai: {{ quoteHistoryLoaded: true }} }},
        ui: {{ SL: {{}}, PL: {{}}, FLATPICKR_LOCALE: 'zh', isMobile: () => false, dueDateText: () => null, toast: () => {{}}, makeDd: () => new MiniElement(), makeMemberDd: () => new MiniElement() }},
        markdown: {{
          jumpToCommentQuote: () => true,
          extractCommentQuotes: () => [],
          _guardPendingUploads: () => false,
        }},
        el,
      }};
      setupRenderDetail(ctx);
      setupRenderDetailActions(ctx);
      setupRenderDetailView(ctx);
      await ctx.renderDetail.openTaskDetailByCode('KAN-1671');
      if (el.detailBodyArea.style.display !== 'flex') throw new Error('detail content runtime smoke did not open the body');
      if (el.detailError.classList.contains('on')) throw new Error('detail content runtime smoke fell into the error branch');
      const mergedComment = ctx.renderDetail._test.mergeConcurrentComment(
        'base text', 'base text\\n\\nlocal appendix', '【学习备注】base text',
      );
      if (mergedComment !== '【学习备注】base text\\n\\nlocal appendix') throw new Error('disjoint comment edits must merge safely');
      const overlappingComment = ctx.renderDetail._test.mergeConcurrentComment(
        'base text', 'local rewrite', 'remote rewrite',
      );
      if (overlappingComment !== null) throw new Error('overlapping comment edits must require review');
      const anchor = new MiniElement('button'); anchor.dataset.commentAnchor = 'cq-a';
      el.detailMdContent.appendChild(anchor);
      const dupeAnchorA = new MiniElement('button'); dupeAnchorA.dataset.commentAnchor = 'cq-dupe';
      const dupeAnchorB = new MiniElement('button'); dupeAnchorB.dataset.commentAnchor = 'cq-dupe';
      el.detailMdContent.appendChild(dupeAnchorA); el.detailMdContent.appendChild(dupeAnchorB);
      const normalizedDupes = ctx.renderDetail.normalizeDuplicateCommentAnchors([
        {{ anchorKey: 'cq-dupe' }}, {{ anchorKey: 'cq-dupe' }},
      ]);
      if (normalizedDupes[0].anchorKey !== 'cq-dupe-0' || normalizedDupes[1].anchorKey !== 'cq-dupe-1') throw new Error('duplicate sidebar keys not normalized');
      if (dupeAnchorA.dataset.commentAnchor !== 'cq-dupe-0' || dupeAnchorB.dataset.commentAnchor !== 'cq-dupe-1') throw new Error('duplicate body anchors not normalized');
      ctx.renderDetail.renderCommentSidebar([
        {{ anchorKey: 'cq-a', author: '<Owner>', quoteText: '<b>safe</b>', ref: 'run#0', refStatus: 'ready', source: 'comment', heading: 'H', paragraph: 'P' }},
        {{ anchorKey: 'cq-b', author: 'Codex', quoteText: 'second', ref: '', refStatus: 'missing-ref', source: 'comment', heading: '', paragraph: '' }},
        {{
          anchorKey: 'external-feishu-1', entryId: 'ext-root', author: 'Owner', quoteText: '<external safe>', source: 'external',
          sourceQuote: {{ quote_text: 'source paragraph', section: 'Abstract', source_locator: {{ task_path: 'project/X/card.md', text_index: 12 }} }},
          replies: [{{ entry_id: 'ext-reply', author: 'Owner', ts: '2026-07-09T22:00:00+08:00', content: '保留的飞书回复' }}],
          createdAt: '2026-06-21T17:33:00+08:00',
          origin: {{ provider: 'feishu', url: 'https://concept-x-lab.feishu.cn/docx/source' }},
        }},
      ]);
      if (el.detailSidebarCommentsBadge.textContent !== '3') throw new Error('badge must show combined comment count');
      if (el.detailSidebarComments.querySelectorAll('.comment-sidebar-card').length !== 3) throw new Error('sidebar cards missing');
      if (!el.detailSidebarComments.textContent.includes('<b>safe</b>')) throw new Error('quote snapshot text missing');
      if (!el.detailSidebarComments.textContent.includes('<external safe>')) throw new Error('external comment text missing');
      if (!el.detailSidebarComments.textContent.includes('保留的飞书回复')) throw new Error('external reply tree missing');
      if (!el.detailSidebarComments.textContent.includes('飞书原批注')) throw new Error('external source label missing');
      const sourceLinks = el.detailSidebarComments.querySelectorAll('.comment-sidebar-source');
      if (sourceLinks.length !== 1 || !String(sourceLinks[0].href || '').startsWith('https://')) throw new Error('safe Feishu source link missing');
      if (el.detailSidebarComments.querySelectorAll('.comment-sidebar-edit').length !== 2) throw new Error('root comment and reply must both expose edit actions');
      ctx.renderDetail.openCommentSidebar('cq-a');
      if (!el.detailSidebarCommentsTab.classList.contains('is-active')) throw new Error('anchor must open comments tab');
      if (el.detailSidebar.classList.contains('is-folded')) throw new Error('anchor must unfold sidebar');
      if (!ctx.renderDetail.jumpToCommentAnchor('cq-a') || anchor.scrolls !== 1) throw new Error('sidebar card must locate body anchor');
      ctx.renderDetail.setSidebarTab('info');
      if (!el.detailSidebarInfo.classList.contains('is-active')) throw new Error('information panel must remain available');
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)

    html = _HTML.read_text(encoding='utf-8')
    assert 'id="detail-sidebar-info"' in html
    assert 'id="detail-props"' in html
    assert 'id="detail-file-path"' in html
