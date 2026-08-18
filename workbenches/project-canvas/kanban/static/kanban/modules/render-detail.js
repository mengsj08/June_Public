export function shouldRenderNextStepRelay(task) {
  return Boolean(task && task.path);
}

export function activitySourceHistoryModel(payload) {
  if (!payload || payload.ok === false) return null;
  const entries = Array.isArray(payload.entries) ? payload.entries : [];
  const explicitCount = Number(payload.count);
  const count = Math.max(
    Number.isFinite(explicitCount) ? Math.max(0, explicitCount) : 0,
    entries.length,
  );
  if (count === 0) return null;
  const sourceCounts = payload.source_counts || {};
  const safeCount = (value) => {
    const normalized = Number(value);
    return Number.isFinite(normalized) ? Math.max(0, normalized) : 0;
  };
  return {
    count,
    sourceCounts: {
      canvas: safeCount(sourceCounts.canvas),
      lineage: safeCount(sourceCounts.lineage),
      comments: safeCount(sourceCounts.comments),
    },
    recent: entries.slice(-12).reverse(),
  };
}

function _mergeRanges(ranges, sourceLength) {
  const normalized = (ranges || [])
    .map((range) => ({
      start: Math.max(0, Math.min(sourceLength, Number(range && range.start) || 0)),
      end: Math.max(0, Math.min(sourceLength, Number(range && range.end) || 0)),
    }))
    .filter((range) => range.end > range.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const merged = [];
  normalized.forEach((range) => {
    const previous = merged[merged.length - 1];
    if (!previous || range.start > previous.end) {
      merged.push({ ...range });
      return;
    }
    previous.end = Math.max(previous.end, range.end);
  });
  return merged;
}

function _taskBodySectionRanges(source) {
  const ranges = [];
  ['完成标准', '给 AI 的常驻说明'].forEach((heading) => {
    const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp('(^|\\n)##\\s+' + escaped + '\\s*\\n[\\s\\S]*?(?=\\n##\\s+|$)');
    const match = pattern.exec(source);
    if (!match) return;
    const start = match.index + (match[1] ? match[1].length : 0);
    ranges.push({ start, end: match.index + match[0].length });
  });
  return ranges;
}

function _commentQuoteRanges(source) {
  const ranges = [];
  const pattern = /(^|\n)(:::comment-quote\b[^\n]*\n[\s\S]*?\n:::[^\S\r\n]*(?:\n|$))/g;
  let match;
  while ((match = pattern.exec(source)) !== null) {
    const start = match.index + (match[1] ? match[1].length : 0);
    ranges.push({ start, end: start + match[2].length });
    if (!match[0].length) pattern.lastIndex += 1;
  }
  return ranges;
}

export function segmentEditableMarkdownBlocks(source, lexer, excludedRanges = []) {
  const body = String(source || '');
  const blocks = [];
  let nextIndex = 0;
  const exclusions = _mergeRanges(excludedRanges, body.length);
  const protectedRanges = _mergeRanges(_commentQuoteRanges(body), body.length);

  function addLexedRange(start, end) {
    if (end <= start) return;
    const chunk = body.slice(start, end);
    if (typeof lexer !== 'function') {
      if (chunk.trim()) blocks.push({ index: nextIndex++, start, end, raw: chunk, type: 'whole' });
      return;
    }
    const tokens = lexer(chunk) || [];
    let offset = start;
    tokens.forEach((token) => {
      const raw = String((token && token.raw) || '');
      const tokenStart = offset;
      offset += raw.length;
      if (!raw || (token && token.type === 'space')) return;
      blocks.push({
        index: nextIndex++,
        start: tokenStart,
        end: offset,
        raw,
        type: String((token && token.type) || 'block'),
      });
    });
    if (offset < end) {
      const remainder = body.slice(offset, end);
      if (remainder.trim()) blocks.push({ index: nextIndex++, start: offset, end, raw: remainder, type: 'remainder' });
    }
  }

  function addIncludedRange(start, end) {
    let cursor = start;
    protectedRanges.forEach((range) => {
      if (range.end <= cursor || range.start >= end) return;
      const protectedStart = Math.max(cursor, range.start);
      const protectedEnd = Math.min(end, range.end);
      addLexedRange(cursor, protectedStart);
      const raw = body.slice(protectedStart, protectedEnd);
      if (raw.trim()) {
        blocks.push({
          index: nextIndex++,
          start: protectedStart,
          end: protectedEnd,
          raw,
          type: 'comment-quote',
        });
      }
      cursor = protectedEnd;
    });
    addLexedRange(cursor, end);
  }

  let cursor = 0;
  exclusions.forEach((range) => {
    addIncludedRange(cursor, range.start);
    cursor = range.end;
  });
  addIncludedRange(cursor, body.length);
  return blocks;
}

export function setupRenderDetail(ctx) {
  const { dataState, uiState, ui, markdown } = ctx;
  const {
    detailOverlay, detailTitle, detailLoading, detailError, detailBodyArea, detailMdContent,
    detailProps, detailFilePath, detailCopyBtn, detailSidebar, detailStatusBar,
    detailEditor, detailViewMode, detailEditMode, editorStatus, detailEditBtn,
    aiActivity, aiActivityList, detailSidebarInfoTab, detailSidebarCommentsTab,
    detailSidebarCommentsBadge, detailSidebarFoldBtn, detailSidebarInfo, detailSidebarComments,
  } = ctx.el;
  const { SL, PL, FLATPICKR_LOCALE, isMobile, dueDateText, toast, makeDd, makeMemberDd } = ui;

  const hasFlatpickr = typeof window.flatpickr === 'function';
  const detailState = {
    detailBodyBlocks: [],
    activeDetailBlockEditor: null,
    inlineBlockSavePromise: null,
    currentDetailTask: null,
  };
  const detail = { detailState };
  ctx.renderDetailInternal = detail;
  const renderDetailContent = (...args) => detail.renderDetailContent(...args);

  function syncEditModeUI() {
    detailViewMode.style.display = uiState.detail.isEditMode ? 'none' : 'block';
    detailEditMode.style.display = uiState.detail.isEditMode ? 'block' : 'none';
    detailEditBtn.textContent = uiState.detail.isEditMode ? '查看' : '源码';
    detailEditBtn.title = uiState.detail.isEditMode ? '返回可点击编辑的阅读视图' : '编辑整篇 Markdown 源码';
  }

  function _detailSidebarState() {
    if (!uiState.detail.sidebarTab) uiState.detail.sidebarTab = 'info';
    if (typeof uiState.detail.sidebarFolded !== 'boolean') uiState.detail.sidebarFolded = false;
    if (!Array.isArray(uiState.detail.commentQuotes)) uiState.detail.commentQuotes = [];
    if (!Array.isArray(uiState.detail.bodyCommentQuotes)) uiState.detail.bodyCommentQuotes = [];
    if (!Array.isArray(uiState.detail.externalComments)) uiState.detail.externalComments = [];
    return uiState.detail;
  }

  function setSidebarTab(tab, persist = true) {
    const state = _detailSidebarState();
    const next = tab === 'comments' ? 'comments' : 'info';
    state.sidebarTab = next;
    detailSidebarInfoTab.classList.toggle('is-active', next === 'info');
    detailSidebarCommentsTab.classList.toggle('is-active', next === 'comments');
    detailSidebarInfoTab.setAttribute('aria-selected', next === 'info' ? 'true' : 'false');
    detailSidebarCommentsTab.setAttribute('aria-selected', next === 'comments' ? 'true' : 'false');
    detailSidebarInfo.classList.toggle('is-active', next === 'info');
    detailSidebarComments.classList.toggle('is-active', next === 'comments');
    detailSidebarInfo.hidden = next !== 'info';
    detailSidebarComments.hidden = next !== 'comments';
    if (persist) localStorage.setItem('kanban_detail_sidebar_tab', next);
  }

  function setSidebarFolded(folded, persist = true) {
    const state = _detailSidebarState();
    state.sidebarFolded = Boolean(folded);
    detailSidebar.classList.toggle('is-folded', state.sidebarFolded);
    if (!isMobile()) detailSidebar.classList.remove('collapsed');
    detailSidebarFoldBtn.textContent = state.sidebarFolded ? '‹' : '›';
    detailSidebarFoldBtn.setAttribute('aria-label', state.sidebarFolded ? '展开详情侧栏' : '折叠详情侧栏');
    detailSidebarFoldBtn.title = state.sidebarFolded ? '展开详情侧栏' : '折叠详情侧栏';
    if (persist) localStorage.setItem('kanban_detail_sidebar_folded', state.sidebarFolded ? 'true' : 'false');
  }

  function _shortText(value, maxLength) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    const limit = maxLength || 180;
    return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
  }

  function _safeExternalCommentUrl(value) {
    try {
      const url = new URL(String(value || ''));
      return url.protocol === 'https:' ? url.toString() : '';
    } catch (e) {
      return '';
    }
  }

  function _formatExternalCommentTime(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text;
    return date.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  }

  function _externalCommentView(thread, index) {
    const item = thread && typeof thread === 'object' ? thread : {};
    const origin = item.origin && typeof item.origin === 'object' ? item.origin : {};
    const sourceQuote = item.source_quote && typeof item.source_quote === 'object' ? item.source_quote : null;
    return {
      anchorKey: 'external-' + String(item.thread_id || item.entry_id || index).replace(/[^a-zA-Z0-9_-]/g, '-'),
      entryId: String(item.entry_id || ''),
      author: String(item.author || '未知作者'),
      quoteText: String(item.content || ''),
      source: 'external',
      sourceQuote,
      replies: Array.isArray(item.replies) ? item.replies : [],
      createdAt: item.ts || '',
      updatedAt: item.updated_at || '',
      resolved: Boolean(item.resolved),
      origin,
      heading: sourceQuote ? String(sourceQuote.section || '') : '',
      paragraph: sourceQuote ? String(sourceQuote.quote_text || '') : '',
    };
  }

  function _mergeConcurrentComment(baseValue, localValue, remoteValue) {
    const base = String(baseValue || '');
    const local = String(localValue || '');
    const remote = String(remoteValue || '');
    if (local === remote) return local;
    if (remote === base) return local;
    if (local === base) return remote;
    if (!base) return null;

    const remoteIndex = remote.indexOf(base);
    if (remoteIndex >= 0 && remote.indexOf(base, remoteIndex + base.length) < 0) {
      return remote.slice(0, remoteIndex) + local + remote.slice(remoteIndex + base.length);
    }
    const localIndex = local.indexOf(base);
    if (localIndex >= 0 && local.indexOf(base, localIndex + base.length) < 0) {
      return local.slice(0, localIndex) + remote + local.slice(localIndex + base.length);
    }
    return null;
  }

  function _externalEditButton(item, displayElement, holder) {
    const entryId = String((item && (item.entryId || item.entry_id)) || '');
    if (!entryId) return null;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'comment-sidebar-edit';
    button.textContent = '编辑';
    button.title = '编辑当前卡片中的本地持久批注；不会回写外部来源';
    button.onclick = () => {
      if (holder.querySelector && holder.querySelector('.comment-sidebar-editor')) return;
      const editor = document.createElement('div');
      editor.className = 'comment-sidebar-editor';
      const textarea = document.createElement('textarea');
      textarea.className = 'comment-sidebar-edit-input';
      textarea.rows = 6;
      textarea.value = String((item && (item.content != null ? item.content : item.quoteText)) || '');
      let baseContent = textarea.value;
      let expectedUpdatedAt = String((item && (item.updatedAt || item.updated_at)) || '');
      let requiresConflictReview = false;
      const conflict = document.createElement('div');
      conflict.className = 'comment-sidebar-edit-conflict';
      conflict.hidden = true;
      const conflictTitle = document.createElement('strong');
      conflictTitle.textContent = '批注在你编辑期间已更新';
      const conflictHelp = document.createElement('p');
      conflictHelp.textContent = '你的草稿仍保留在上方。下面是最新版本；请手动合并并再次编辑后保存。';
      const conflictLatest = document.createElement('pre');
      conflictLatest.className = 'comment-sidebar-edit-latest';
      conflict.appendChild(conflictTitle);
      conflict.appendChild(conflictHelp);
      conflict.appendChild(conflictLatest);
      const actions = document.createElement('div');
      actions.className = 'comment-sidebar-edit-actions';
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'comment-sidebar-edit-cancel';
      cancel.textContent = '取消';
      const save = document.createElement('button');
      save.type = 'button';
      save.className = 'comment-sidebar-edit-save';
      save.textContent = '保存';
      const closeEditor = () => {
        displayElement.hidden = false;
        button.disabled = false;
        if (typeof editor.remove === 'function') editor.remove();
      };
      cancel.onclick = closeEditor;
      const setBusy = (busy) => {
        save.disabled = busy || requiresConflictReview;
        cancel.disabled = busy;
        textarea.disabled = busy;
      };
      textarea.oninput = () => {
        if (!requiresConflictReview) return;
        requiresConflictReview = false;
        save.disabled = false;
        save.textContent = '合并后保存';
      };
      const submitSave = async (allowAutoMerge = true) => {
        const content = textarea.value.trim();
        if (!content) {
          toast('批注内容不能为空', true);
          return;
        }
        setBusy(true);
        try {
          const response = await fetch('/api/comments/edit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              path: uiState.detail.currentTaskPath,
              entry_id: entryId,
              content,
              expected_updated_at: expectedUpdatedAt,
            }),
          });
          const data = await response.json();
          if (response.status === 409 && data.current_updated_at) {
            let latestContent = typeof data.current_content === 'string' ? data.current_content : null;
            let latestUpdatedAt = String(data.current_updated_at || '');
            if (latestContent == null) {
              try {
                const latestResponse = await fetch(
                  '/api/task-comments?path=' + encodeURIComponent(uiState.detail.currentTaskPath),
                );
                const latestData = await latestResponse.json();
                const threads = Array.isArray(latestData.comments) ? latestData.comments : [];
                const candidates = threads.flatMap((thread) => [thread, ...((thread && thread.replies) || [])]);
                const latest = candidates.find((candidate) => String((candidate && candidate.entry_id) || '') === entryId);
                if (latest) {
                  latestContent = String(latest.content || '');
                  latestUpdatedAt = String(latest.updated_at || latestUpdatedAt);
                }
              } catch (_error) {
                latestContent = null;
              }
            }
            const merged = allowAutoMerge && latestContent != null
              ? _mergeConcurrentComment(baseContent, content, latestContent)
              : null;
            expectedUpdatedAt = latestUpdatedAt;
            if (latestContent != null) baseContent = latestContent;
            if (merged != null) {
              textarea.value = merged;
              setBusy(false);
              toast('检测到批注新版本，已安全合并你的草稿');
              return submitSave(false);
            }
            conflictLatest.textContent = latestContent == null
              ? '最新版本暂时无法载入；你的草稿未丢失。请重新打开卡片后再合并。'
              : latestContent;
            conflict.hidden = false;
            requiresConflictReview = true;
            save.textContent = '请先合并';
            setBusy(false);
            toast('批注已被更新；你的草稿已保留，请对照最新版本合并', true);
            return;
          }
          if (!data.ok) throw new Error(data.error || '保存批注失败');
          toast(data.changed ? '批注已保存（仅本地）' : '批注没有变化');
          await loadTaskComments(uiState.detail.currentTaskPath);
        } catch (error) {
          setBusy(false);
          toast(String(error && error.message || error || '保存批注失败'), true);
        }
      };
      save.onclick = () => submitSave(true);
      actions.appendChild(cancel);
      actions.appendChild(save);
      editor.appendChild(textarea);
      editor.appendChild(conflict);
      editor.appendChild(actions);
      displayElement.hidden = true;
      button.disabled = true;
      if (typeof displayElement.after === 'function') displayElement.after(editor);
      else holder.appendChild(editor);
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    };
    return button;
  }

  function _jumpToExternalCommentSource(comment) {
    const sourceQuote = comment && comment.sourceQuote;
    if (sourceQuote && ctx.ai && typeof ctx.ai.jumpToBodyQuote === 'function') {
      return ctx.ai.jumpToBodyQuote(sourceQuote);
    }
    if (detailMdContent && typeof detailMdContent.scrollIntoView === 'function') {
      detailMdContent.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return true;
    }
    return false;
  }

  function loadTaskComments(path) {
    const targetPath = String(path || '');
    const state = _detailSidebarState();
    state.externalComments = [];
    if (!ctx.hasApi || !targetPath) {
      renderCommentSidebar(state.bodyCommentQuotes);
      return Promise.resolve([]);
    }
    return fetch('/api/task-comments?path=' + encodeURIComponent(targetPath))
      .then((response) => response.json())
      .then((data) => {
        if (uiState.detail.currentTaskPath !== targetPath) return [];
        const threads = data && data.ok && Array.isArray(data.comments) ? data.comments : [];
        state.externalComments = threads.map(_externalCommentView);
        renderCommentSidebar([...(state.bodyCommentQuotes || []), ...state.externalComments]);
        return state.externalComments;
      })
      .catch(() => {
        if (uiState.detail.currentTaskPath === targetPath) {
          state.externalComments = [];
          renderCommentSidebar(state.bodyCommentQuotes || []);
        }
        return [];
      });
  }

  function jumpToCommentAnchor(anchorKey) {
    const key = String(anchorKey || '');
    const target = Array.from(detailMdContent.querySelectorAll('[data-comment-anchor]'))
      .find((node) => node.dataset.commentAnchor === key);
    if (!target) {
      toast('正文锚点已变化，批注快照仍保留', true);
      return false;
    }
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.add('is-located');
    setTimeout(() => target.classList.remove('is-located'), 1800);
    return true;
  }

  function refreshCommentSidebarAvailability() {
    if (!detailSidebarComments) return;
    const loaded = Boolean(uiState.ai && uiState.ai.quoteHistoryLoaded);
    detailSidebarComments.querySelectorAll('.comment-sidebar-original[data-comment-ref]').forEach((button) => {
      const ref = button.dataset.commentRef || '';
      const valid = button.dataset.commentRefStatus === 'ready';
      const target = valid && ref
        ? Array.from(document.querySelectorAll('[data-entry-id]')).find((node) => node.dataset.entryId === ref)
        : null;
      const missing = !valid || (loaded && !target);
      button.disabled = missing;
      button.textContent = missing ? '原评论不可达' : '定位原评论';
      button.title = missing ? '引用快照保留在任务正文中' : '跳转到原始评论';
    });
  }

  function renderCommentSidebar(quotes) {
    const list = Array.isArray(quotes) ? quotes : [];
    _detailSidebarState().commentQuotes = list;
    detailSidebarComments.textContent = '';
    detailSidebarCommentsBadge.hidden = list.length === 0;
    detailSidebarCommentsBadge.textContent = list.length ? String(list.length) : '';
    if (!list.length) {
      const empty = document.createElement('div');
      empty.className = 'comment-sidebar-empty';
      empty.textContent = '正文中还没有持久批注。';
      detailSidebarComments.appendChild(empty);
      return;
    }
    const listEl = document.createElement('div');
    listEl.className = 'comment-sidebar-list';
    list.forEach((quote, index) => {
      const card = document.createElement('article');
      card.className = 'comment-sidebar-card' + (quote.source === 'external' ? ' is-external' : '');
      card.dataset.commentAnchorCard = quote.anchorKey || '';
      const context = document.createElement('button');
      context.type = 'button';
      context.className = 'comment-sidebar-context';
      const heading = _shortText(quote.heading, 80);
      const paragraph = _shortText(quote.paragraph, 150);
      context.textContent = heading ? (heading + (paragraph ? ' · ' + paragraph : '')) : (paragraph || '正文中的批注锚点');
      context.title = '回到正文位置';
      context.onclick = quote.source === 'external'
        ? () => _jumpToExternalCommentSource(quote)
        : () => jumpToCommentAnchor(quote.anchorKey);
      card.appendChild(context);

      const excerpt = document.createElement('blockquote');
      excerpt.className = 'comment-sidebar-excerpt';
      excerpt.textContent = quote.quoteText || '（空引文）';

      const meta = document.createElement('div');
      meta.className = 'comment-sidebar-meta';
      const author = document.createElement('strong');
      author.textContent = quote.author || '未知作者';
      meta.appendChild(author);
      const order = document.createElement('span');
      order.textContent = quote.source === 'external'
        ? (_formatExternalCommentTime(quote.createdAt) || String(index + 1).padStart(2, '0'))
        : String(index + 1).padStart(2, '0');
      if (quote.source === 'external') {
        const controls = document.createElement('div');
        controls.className = 'comment-sidebar-meta-controls';
        controls.appendChild(order);
        const edit = _externalEditButton(quote, excerpt, card);
        if (edit) controls.appendChild(edit);
        meta.appendChild(controls);
      } else {
        meta.appendChild(order);
      }
      card.appendChild(meta);
      card.appendChild(excerpt);

      if (quote.source === 'external' && quote.replies.length) {
        const replies = document.createElement('div');
        replies.className = 'comment-sidebar-replies';
        quote.replies.forEach((reply) => {
          const replyEl = document.createElement('div');
          replyEl.className = 'comment-sidebar-reply';
          const replyMeta = document.createElement('div');
          replyMeta.className = 'comment-sidebar-reply-meta';
          const replyAuthor = document.createElement('strong');
          replyAuthor.textContent = String(reply.author || '未知作者');
          const replyTime = document.createElement('span');
          replyTime.textContent = _formatExternalCommentTime(reply.ts || reply.updated_at || '');
          replyMeta.appendChild(replyAuthor);
          const replyControls = document.createElement('div');
          replyControls.className = 'comment-sidebar-meta-controls';
          replyControls.appendChild(replyTime);
          const replyText = document.createElement('div');
          replyText.className = 'comment-sidebar-reply-text';
          replyText.textContent = String(reply.content || '');
          const replyEdit = _externalEditButton(reply, replyText, replyEl);
          if (replyEdit) replyControls.appendChild(replyEdit);
          replyMeta.appendChild(replyControls);
          replyEl.appendChild(replyMeta);
          replyEl.appendChild(replyText);
          replies.appendChild(replyEl);
        });
        card.appendChild(replies);
      }

      const footer = document.createElement('div');
      footer.className = 'comment-sidebar-footer';
      const ref = document.createElement('code');
      ref.textContent = quote.source === 'external'
        ? ((quote.origin && quote.origin.provider === 'feishu') ? '飞书原批注' : '外部原批注')
        : (quote.source === 'body'
          ? '正文来源快照'
          : (quote.ref || (quote.refStatus === 'invalid-ref' ? '非法 ref' : '缺少 ref')));
      footer.appendChild(ref);
      if (quote.source === 'external') {
        const sourceUrl = _safeExternalCommentUrl(quote.origin && quote.origin.url);
        if (sourceUrl) {
          const source = document.createElement('a');
          source.className = 'comment-sidebar-source';
          source.href = sourceUrl;
          source.target = '_blank';
          source.rel = 'noopener noreferrer';
          source.textContent = '打开飞书原文';
          footer.appendChild(source);
        } else {
          const snapshot = document.createElement('span');
          snapshot.className = 'comment-sidebar-snapshot';
          snapshot.textContent = '来源快照保留';
          footer.appendChild(snapshot);
        }
      } else if (quote.source === 'body') {
        const snapshot = document.createElement('span');
        snapshot.className = 'comment-sidebar-snapshot';
        snapshot.textContent = '快照保留';
        footer.appendChild(snapshot);
      } else {
        const original = document.createElement('button');
        original.type = 'button';
        original.className = 'comment-sidebar-original';
        original.dataset.commentRef = quote.ref || '';
        original.dataset.commentRefStatus = quote.refStatus || 'missing-ref';
        original.textContent = '定位原评论';
        original.onclick = () => markdown.jumpToCommentQuote(quote.ref || '');
        footer.appendChild(original);
      }
      card.appendChild(footer);
      listEl.appendChild(card);
    });
    detailSidebarComments.appendChild(listEl);
    refreshCommentSidebarAvailability();
  }

  function normalizeDuplicateCommentAnchors(quotes) {
    const list = Array.isArray(quotes) ? quotes : [];
    const quoteGroups = new Map();
    list.forEach((quote) => {
      const key = quote.anchorKey || '';
      if (!quoteGroups.has(key)) quoteGroups.set(key, []);
      quoteGroups.get(key).push(quote);
    });
    quoteGroups.forEach((group, baseKey) => {
      if (!baseKey || group.length < 2) return;
      group.forEach((quote, index) => { quote.anchorKey = baseKey + '-' + index; });
      const anchors = Array.from(detailMdContent.querySelectorAll('[data-comment-anchor]'))
        .filter((node) => node.dataset.commentAnchor === baseKey);
      anchors.forEach((anchor, index) => {
        anchor.dataset.commentAnchor = baseKey + '-' + Math.min(index, group.length - 1);
      });
    });
    return list;
  }

  function openCommentSidebar(anchorKey) {
    setSidebarTab('comments');
    setSidebarFolded(false);
    detailSidebar.classList.remove('collapsed');
    const key = String(anchorKey || '');
    if (!key) return true;
    const card = Array.from(detailSidebarComments.querySelectorAll('[data-comment-anchor-card]'))
      .find((node) => node.dataset.commentAnchorCard === key);
    if (!card) return false;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    card.classList.add('is-located');
    setTimeout(() => card.classList.remove('is-located'), 1800);
    return true;
  }

  function destroyDetailDuePicker() {
    if (uiState.detail.duePicker) {
      uiState.detail.duePicker.destroy();
      uiState.detail.duePicker = null;
    }
    if (uiState.detail.duePickerInput) {
      uiState.detail.duePickerInput.remove();
      uiState.detail.duePickerInput = null;
    }
  }

  function restoreCurrentTaskLocation() {
    history.pushState(null, '', uiState.detail.currentTaskHash || window.location.pathname);
  }

  function updateEditorStatus(cls, text) {
    editorStatus.className = 'editor-status ' + (cls || '');
    editorStatus.textContent = text || '';
  }

  function _blockTrailer(raw) {
    const match = /\n*$/.exec(String(raw || ''));
    return match ? match[0] : '';
  }

  function _renderDetailBlock(wrap, block, task) {
    wrap.innerHTML = '';
    wrap.classList.remove('is-editing', 'is-saving', 'has-error');
    markdown.renderMarkdownEnhanced(
      wrap,
      block.raw,
      (task && task.path) || uiState.detail.currentTaskPath || '',
      { mode: 'task-body' },
    );
  }

  function _renderTaskBodyBlocks(body, task) {
    detailState.activeDetailBlockEditor = null;
    detailState.inlineBlockSavePromise = null;
    uiState.detail.inlineEditing = false;
    uiState.detail.inlineSaving = false;
    uiState.detail.editorDirty = false;
    detailMdContent.innerHTML = '';
    const lexer = window.marked && typeof window.marked.lexer === 'function'
      ? window.marked.lexer.bind(window.marked)
      : null;
    detailState.detailBodyBlocks = segmentEditableMarkdownBlocks(body, lexer, _taskBodySectionRanges(body));
    detailState.detailBodyBlocks.forEach((block) => {
      const wrap = document.createElement('div');
      wrap.className = 'detail-doc-block';
      wrap.dataset.blockIndex = String(block.index);
      wrap.dataset.blockType = block.type;
      wrap.title = '点击编辑这一段';
      _renderDetailBlock(wrap, block, task);
      detailMdContent.appendChild(wrap);
    });
    if (!detailState.detailBodyBlocks.length) {
      const empty = document.createElement('p');
      empty.id = 'detail-empty-body';
      empty.textContent = '无正文内容';
      detailMdContent.appendChild(empty);
    }
    prependAcceptanceBlock(body, task);
    prependCardNoteBlock(task);
  }

  function _restoreInlineEditor(ed, message) {
    if (!ed || !ed.wrap || !ed.ta) return;
    detailState.activeDetailBlockEditor = ed;
    uiState.detail.inlineEditing = true;
    uiState.detail.inlineSaving = false;
    uiState.detail.editorDirty = ed.ta.value + ed.trailer !== ed.block.raw;
    ed.wrap.classList.remove('is-saving');
    ed.wrap.classList.add('is-editing', 'has-error');
    ed.ta.disabled = false;
    ed.ta.focus();
    if (message) toast(message, true);
  }

  async function _persistInlineBody(ed, newBody, baseBody) {
    if (!uiState.detail.currentTaskPath || uiState.detail.isSavingBody) {
      _restoreInlineEditor(ed, '正在保存其他内容，请稍后再试');
      return false;
    }
    uiState.detail.isSavingBody = true;
    uiState.detail.inlineSaving = true;
    ed.wrap.classList.add('is-saving');
    ed.ta.disabled = true;
    try {
      const { json } = await ctx.api.apiJson('/api/update-body', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: uiState.detail.currentTaskPath,
          body: newBody,
          base_rev: uiState.detail.currentTaskRev,
          base_body: baseBody,
        }),
      });
      if (json.ok) {
        uiState.detail.currentTaskBody = json.body || newBody;
        uiState.detail.savedBodyContent = json.body || newBody;
        uiState.detail.currentTaskRev = json.rev || uiState.detail.currentTaskRev;
        uiState.detail.editorDirty = false;
        uiState.detail.inlineEditing = false;
        uiState.sync.pendingRemoteRefresh = false;
        const taskJ = await ctx.api.fetchTaskByPath(uiState.detail.currentTaskPath);
        if (taskJ.ok) renderDetailContent(taskJ.task);
        ctx.api.refresh();
        toast(json.merged ? '段落已合并保存' : '段落已保存');
        return true;
      }
      if (json.conflict) {
        uiState.detail.currentTaskRev = json.rev || uiState.detail.currentTaskRev;
        detailEditor.value = json.body || newBody;
        uiState.detail.isEditMode = true;
        uiState.detail.inlineEditing = false;
        uiState.detail.editorDirty = true;
        syncEditModeUI();
        updateEditorStatus('dirty', '存在冲突，需手动处理');
        toast(json.message || '段落与磁盘版本冲突，已打开源码处理', true);
        return false;
      }
      _restoreInlineEditor(ed, json.message || '段落保存失败');
      return false;
    } catch (error) {
      _restoreInlineEditor(ed, '网络错误，段落尚未保存');
      return false;
    } finally {
      uiState.detail.isSavingBody = false;
      uiState.detail.inlineSaving = false;
    }
  }

  async function commitInlineBlockEdit(discard = false) {
    const ed = detailState.activeDetailBlockEditor;
    if (!ed) return true;
    detailState.activeDetailBlockEditor = null;
    uiState.detail.inlineEditing = false;
    if (discard) {
      uiState.detail.editorDirty = false;
      _renderDetailBlock(ed.wrap, ed.block, detailState.currentDetailTask);
      return true;
    }
    if (markdown._hasPendingUploads()) await markdown._waitForPendingUploads();
    const newRaw = ed.ta.value + ed.trailer;
    if (newRaw === ed.block.raw) {
      uiState.detail.editorDirty = false;
      _renderDetailBlock(ed.wrap, ed.block, detailState.currentDetailTask);
      return true;
    }
    const baseBody = uiState.detail.currentTaskBody;
    const newBody = baseBody.slice(0, ed.block.start) + newRaw + baseBody.slice(ed.block.end);
    detailState.inlineBlockSavePromise = _persistInlineBody(ed, newBody, baseBody);
    const saved = await detailState.inlineBlockSavePromise;
    detailState.inlineBlockSavePromise = null;
    return saved;
  }

  async function deleteInlineBlock() {
    const ed = detailState.activeDetailBlockEditor;
    if (!ed) return false;
    detailState.activeDetailBlockEditor = null;
    uiState.detail.inlineEditing = false;
    const baseBody = uiState.detail.currentTaskBody;
    const newBody = baseBody.slice(0, ed.block.start) + baseBody.slice(ed.block.end);
    detailState.inlineBlockSavePromise = _persistInlineBody(ed, newBody, baseBody);
    const saved = await detailState.inlineBlockSavePromise;
    detailState.inlineBlockSavePromise = null;
    return saved;
  }

  function _autosizeInlineEditor(textarea) {
    textarea.style.height = 'auto';
    const cap = Math.max(120, Math.floor(window.innerHeight * 0.8));
    textarea.style.height = Math.min(textarea.scrollHeight + 2, cap) + 'px';
  }

  async function enterInlineBlockEdit(wrap) {
    if (!wrap || uiState.detail.isEditMode || uiState.detail.inlineSaving) return;
    if (detailState.activeDetailBlockEditor) {
      const saved = await commitInlineBlockEdit(false);
      if (!saved) return;
    }
    const index = Number(wrap.dataset.blockIndex);
    const block = detailState.detailBodyBlocks.find((candidate) => candidate.index === index);
    if (!block) return;
    const trailer = _blockTrailer(block.raw);
    const textarea = document.createElement('textarea');
    textarea.className = 'detail-block-editor';
    textarea.spellcheck = false;
    textarea.value = block.raw.slice(0, block.raw.length - trailer.length);
    wrap.innerHTML = '';
    wrap.classList.add('is-editing');
    wrap.appendChild(textarea);
    detailState.activeDetailBlockEditor = { wrap, block, trailer, ta: textarea };
    uiState.detail.inlineEditing = true;
    uiState.detail.editorDirty = false;

    textarea.addEventListener('input', () => {
      uiState.detail.editorDirty = textarea.value + trailer !== block.raw;
      wrap.classList.toggle('is-dirty', uiState.detail.editorDirty);
      _autosizeInlineEditor(textarea);
    });
    textarea.addEventListener('blur', () => {
      if (detailState.activeDetailBlockEditor && detailState.activeDetailBlockEditor.ta === textarea) void commitInlineBlockEdit(false);
    });
    textarea.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        void commitInlineBlockEdit(true);
        return;
      }
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        event.stopPropagation();
        void commitInlineBlockEdit(false);
        return;
      }
      if (event.key === 'Backspace' && textarea.value === '' && textarea.selectionStart === 0) {
        event.preventDefault();
        event.stopPropagation();
        void deleteInlineBlock();
      }
    });
    textarea.addEventListener('paste', async (event) => {
      const files = Array.from((event.clipboardData && event.clipboardData.items) || [])
        .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
        .map((item) => item.getAsFile())
        .filter(Boolean);
      if (!files.length) return;
      event.preventDefault();
      await markdown.uploadImagesAndInsert(files, textarea);
    });
    textarea.addEventListener('dragover', (event) => {
      const hasImage = Array.from((event.dataTransfer && event.dataTransfer.items) || [])
        .some((item) => item.kind === 'file' && item.type.startsWith('image/'));
      if (!hasImage) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
    });
    textarea.addEventListener('drop', async (event) => {
      const files = Array.from((event.dataTransfer && event.dataTransfer.files) || [])
        .filter((file) => file.type.startsWith('image/'));
      if (!files.length) return;
      event.preventDefault();
      await markdown.uploadImagesAndInsert(files, textarea);
    });
    textarea.focus();
    _autosizeInlineEditor(textarea);
    requestAnimationFrame(() => _autosizeInlineEditor(textarea));
  }

  function closeDetail(options) {
    const force = options && options.force === true;
    if (!force && markdown._guardPendingUploads('关闭详情')) return;
    if (!force && (uiState.detail.editorDirty || uiState.detail.acceptanceDirty || uiState.detail.noteDirty) && !confirm('有未保存的更改，确定要关闭吗？')) return;
    destroyDetailDuePicker();
    uiState.detail.isEditMode = false;
    uiState.detail.editorDirty = false;
    uiState.detail.acceptanceDirty = false;
    uiState.detail.noteDirty = false;
    uiState.detail.inlineEditing = false;
    uiState.detail.inlineSaving = false;
    detailState.activeDetailBlockEditor = null;
    detailState.inlineBlockSavePromise = null;
    detailState.currentDetailTask = null;
    detailState.detailBodyBlocks = [];
    uiState.detail.savedBodyContent = '';
    uiState.detail.openCommentsAfterSave = false;
    uiState.detail.currentTaskHash = '';
    uiState.detail.currentTaskRev = '';
    uiState.sync.pendingRemoteRefresh = false;
    syncEditModeUI();
    updateEditorStatus('', '');
    detailOverlay.classList.remove('on');
    detailLoading.style.display = 'none';
    detailError.style.display = 'none';
    detailError.classList.remove('on');
    detailBodyArea.style.display = 'none';
    if (ctx.ai && typeof ctx.ai.resetDetailActivity === 'function') ctx.ai.resetDetailActivity();
    uiState.detail.currentTaskPath = '';
    uiState.detail.currentTaskStatus = '';
    if (ctx.ai && typeof ctx.ai.updateAiButtonsState === 'function') ctx.ai.updateAiButtonsState();
    history.pushState(null, '', window.location.pathname);
  }

  async function _openDetail(fetcher) {
    destroyDetailDuePicker();
    if (markdown._guardPendingUploads('切换任务')) return;
    detailOverlay.classList.add('on');
    detailTitle.textContent = '';
    detailLoading.style.display = 'flex';
    detailError.style.display = 'none';
    detailError.classList.remove('on');
    detailBodyArea.style.display = 'none';
    try {
      const data = await fetcher();
      detailLoading.style.display = 'none';
      if (!data.ok) {
        detailError.textContent = data.error || '加载失败';
        detailError.classList.add('on');
        detailError.style.display = 'block';
        return;
      }
      renderDetailContent(data.task);
    } catch (e) {
      console.error(e);
      detailLoading.style.display = 'none';
      detailError.textContent = '网络错误';
      detailError.classList.add('on');
      detailError.style.display = 'block';
    }
  }

  function openTaskDetail(path) {
    return _openDetail(() => ctx.api.fetchTaskByPath(path));
  }

  function openTaskDetailByCode(code) {
    return _openDetail(() => ctx.api.fetchTaskByCode(code));
  }

  async function updateDetailField(task, field, value) {
    const result = await ctx.api.apiUpdate(task.path, field, value);
    if (!result) return false;
    const nextPath = result.new_path || task.path;
    if (result.new_path) {
      task.path = result.new_path;
      uiState.detail.currentTaskPath = result.new_path;
    }
    await ctx.api.refresh();
    try {
      const j = await ctx.api.fetchTaskByPath(nextPath);
      if (j.ok) renderDetailContent(j.task);
    } catch (e) {
      return false;
    }
    return result;
  }

  async function archiveCurrentTask(task, button) {
    if (!task || !task.path || !ctx.api || !ctx.api.deleteTask) return;
    if (markdown._guardPendingUploads('删除任务')) return;
    const message = (uiState.detail.editorDirty || uiState.detail.acceptanceDirty || uiState.detail.noteDirty)
      ? '有未保存的更改，删除会丢弃这些更改。\n\n确定删除这张任务卡吗？\n\n它不会被硬删除，会归档到所在项目的 .archive/，可从 git 恢复。'
      : '确定删除这张任务卡吗？\n\n它不会被硬删除，会归档到所在项目的 .archive/，可从 git 恢复。';
    if (!confirm(message)) return;
    if (button) button.disabled = true;
    const result = await ctx.api.deleteTask(task.path);
    if (!result) {
      if (button) button.disabled = false;
      return;
    }
    closeDetail({ force: true });
    await ctx.api.refresh();
  }

  function openDetailDuePicker(anchorEl, task) {
    if (!ctx.hasApi || !task.path || !hasFlatpickr) return;
    destroyDetailDuePicker();
    const input = document.createElement('input');
    input.type = 'text';
    input.tabIndex = -1;
    input.setAttribute('aria-hidden', 'true');
    input.style.position = 'fixed';
    input.style.left = '-9999px';
    input.style.opacity = '0';
    input.style.pointerEvents = 'none';
    document.body.appendChild(input);
    uiState.detail.duePickerInput = input;
    uiState.detail.duePicker = flatpickr(input, {
      locale: FLATPICKR_LOCALE,
      dateFormat: 'Y-m-d',
      minDate: 'today',
      defaultDate: task.due_date || null,
      allowInput: false,
      clickOpens: false,
      disableMobile: true,
      positionElement: anchorEl,
      onChange: async (_selectedDates, dateStr, instance) => {
        if (!dateStr) return;
        instance.close();
        await updateDetailField(task, 'due_date', dateStr);
      },
      onClose: () => {
        setTimeout(destroyDetailDuePicker, 0);
      }
    });
    uiState.detail.duePicker.open();
  }

  function extractAcceptanceSection(body) {
    const match = (body || '').match(/(?:^|\n)##\s+完成标准\s*\n([\s\S]*?)(?=\n##\s+|$)/);
    return match ? match[1].trim() : '';
  }

  function stripAcceptanceSection(body) {
    return (body || '').replace(/(?:^|\n)##\s+完成标准\s*\n[\s\S]*?(?=\n##\s+|$)/, '');
  }

  function parseAcceptanceChecks(markdownText) {
    const checks = [];
    String(markdownText || '').split(/\r\n|\n|\r/).forEach((line) => {
      const match = line.match(/^\s*[-*+]\s+\[([ xX])\]\s*(.*)$/);
      if (!match) return;
      checks.push({
        checked: match[1].toLowerCase() === 'x',
        text: match[2].trim()
      });
    });
    return checks;
  }

  async function refreshCurrentDetailTask(path) {
    if (!path) return;
    await ctx.api.refresh();
    try {
      const fresh = await ctx.api.fetchTaskByPath(path);
      if (fresh.ok) renderDetailContent(fresh.task);
    } catch (e) {
      return null;
    }
  }

  function bindAcceptanceCheckboxes(content, acceptance, task) {
    const checks = parseAcceptanceChecks(acceptance);
    const inputs = Array.from(content.querySelectorAll('input[type="checkbox"]'));
    inputs.forEach((input, idx) => {
      const check = checks[idx];
      if (!check || !ctx.hasApi || !task.path) {
        input.disabled = true;
        return;
      }
      input.disabled = false;
      input.dataset.acceptanceIndex = String(idx);
      input.title = '更新完成标准状态';
      input.addEventListener('change', async () => {
        const nextChecked = input.checked;
        input.disabled = true;
        const result = await ctx.api.toggleAcceptanceCheck(task.path, idx, check.text, nextChecked);
        if (result && result.ok) {
          toast('完成标准已更新');
          await refreshCurrentDetailTask(task.path);
          return;
        }
        input.checked = !nextChecked;
        input.disabled = false;
      });
    });
  }

  function renderAcceptanceEditor(block, acceptance, task) {
    uiState.detail.acceptanceDirty = false;
    block.innerHTML = '';
    const title = document.createElement('div');
    title.className = 'detail-acceptance-title';
    const label = document.createElement('span');
    label.textContent = '完成标准';
    title.appendChild(label);
    const editor = document.createElement('textarea');
    editor.className = 'detail-acceptance-editor';
    editor.value = acceptance;
    editor.spellcheck = false;
    const toolbar = document.createElement('div');
    toolbar.className = 'detail-acceptance-toolbar';
    const status = document.createElement('span');
    status.className = 'detail-acceptance-status';
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'detail-acceptance-btn';
    cancelBtn.textContent = '取消';
    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'detail-acceptance-btn primary';
    saveBtn.textContent = '保存';
    toolbar.appendChild(status);
    toolbar.appendChild(cancelBtn);
    toolbar.appendChild(saveBtn);
    block.appendChild(title);
    block.appendChild(editor);
    block.appendChild(toolbar);

    function setStatus(cls, text) {
      status.className = 'detail-acceptance-status ' + (cls || '');
      status.textContent = text || '';
    }

    editor.addEventListener('input', () => {
      uiState.detail.acceptanceDirty = editor.value !== acceptance;
      setStatus(uiState.detail.acceptanceDirty ? 'dirty' : '', uiState.detail.acceptanceDirty ? '未保存' : '');
    });
    editor.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        saveBtn.click();
      }
    });
    cancelBtn.onclick = () => {
      if (uiState.detail.acceptanceDirty && !confirm('有未保存的完成标准更改，确定放弃吗？')) return;
      uiState.detail.acceptanceDirty = false;
      renderDetailContent(task);
    };
    saveBtn.onclick = async () => {
      if (!ctx.hasApi || !task.path || saveBtn.disabled) return;
      if (editor.value === acceptance) {
        toast('没有修改需要保存');
        uiState.detail.acceptanceDirty = false;
        renderDetailContent(task);
        return;
      }
      saveBtn.disabled = true;
      cancelBtn.disabled = true;
      setStatus('saving', '保存中...');
      const result = await ctx.api.updateAcceptanceSection(task.path, editor.value);
      if (result && result.ok) {
        uiState.detail.acceptanceDirty = false;
        setStatus('saved', '已保存');
        toast('完成标准已保存');
        await refreshCurrentDetailTask(task.path);
      } else {
        uiState.detail.acceptanceDirty = true;
        setStatus('dirty', '保存失败');
        saveBtn.disabled = false;
        cancelBtn.disabled = false;
      }
    };
    editor.focus();
  }

  function prependAcceptanceBlock(body, task) {
    const acceptance = extractAcceptanceSection(body);
    if (!acceptance) return;
    const block = document.createElement('section');
    block.className = 'detail-acceptance-block';
    const title = document.createElement('div');
    title.className = 'detail-acceptance-title';
    const label = document.createElement('span');
    label.textContent = '完成标准';
    title.appendChild(label);
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'detail-acceptance-edit-btn';
    editBtn.textContent = '编辑';
    editBtn.disabled = !ctx.hasApi || !task.path;
    editBtn.onclick = () => renderAcceptanceEditor(block, acceptance, task);
    title.appendChild(editBtn);
    const content = document.createElement('div');
    content.className = 'detail-acceptance-content';
    markdown.renderMarkdownEnhanced(content, acceptance, task.path || '', { mode: 'task-body' });
    bindAcceptanceCheckboxes(content, acceptance, task);
    block.appendChild(title);
    block.appendChild(content);
    detailMdContent.prepend(block);
  }

  function stripCardNoteSection(body) {
    return (body || '').replace(/(?:^|\n)##\s+给 AI 的常驻说明\s*\n[\s\S]*?(?=\n##\s+|$)/, '');
  }

  // 卡级「给 AI 的常驻说明」：写进卡 .md，每次执行后端自动提到 prompt 最前（支持 /skill）。
  // 折叠式：空时只一行很淡的触发条；有内容时紧凑显示 + 编辑；点开才出完整编辑框，不占顶部黄金位。
  function prependCardNoteBlock(task) {
    if (!task) return;
    let baseline = String(task.ai_note || '');
    const canEdit = !!(ctx.hasApi && task.path);
    const block = document.createElement('section');

    function renderCollapsed() {
      uiState.detail.noteDirty = false;
      block.innerHTML = '';
      if (!baseline) {
        block.className = 'detail-note-block is-empty';
        const trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'detail-note-add';
        trigger.textContent = '+ 给 AI 的常驻说明';
        trigger.disabled = !canEdit;
        trigger.onclick = renderEditor;
        block.appendChild(trigger);
        return;
      }
      block.className = 'detail-note-block has-note';
      const head = document.createElement('div');
      head.className = 'detail-note-head';
      const tag = document.createElement('span');
      tag.className = 'detail-note-tag';
      tag.textContent = '给 AI 的常驻说明';
      head.appendChild(tag);
      if (canEdit) {
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.className = 'detail-note-edit';
        edit.textContent = '编辑';
        edit.onclick = renderEditor;
        head.appendChild(edit);
      }
      const body = document.createElement('div');
      body.className = 'detail-note-text';
      body.textContent = baseline;
      block.appendChild(head);
      block.appendChild(body);
    }

    function renderEditor() {
      block.className = 'detail-note-block is-editing';
      block.innerHTML = '';
      const title = document.createElement('div');
      title.className = 'detail-note-title';
      const label = document.createElement('span');
      label.textContent = '给 AI 的常驻说明';
      const hint = document.createElement('span');
      hint.className = 'detail-note-hint';
      hint.textContent = '每次执行自动带上 · 支持 /skill';
      title.appendChild(label);
      title.appendChild(hint);

      const editor = document.createElement('textarea');
      editor.className = 'detail-note-editor';
      editor.rows = 3;
      editor.placeholder = '对整张卡的执行说明，例如：本次只改 X 不要动 Y；或 /skill <名字> ...';
      editor.value = baseline;

      const toolbar = document.createElement('div');
      toolbar.className = 'detail-note-toolbar';
      const status = document.createElement('span');
      status.className = 'detail-note-status';
      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'detail-note-btn';
      cancelBtn.textContent = '取消';
      const saveBtn = document.createElement('button');
      saveBtn.type = 'button';
      saveBtn.className = 'detail-note-btn primary';
      saveBtn.textContent = '保存';
      saveBtn.disabled = true;
      toolbar.appendChild(status);
      toolbar.appendChild(cancelBtn);
      toolbar.appendChild(saveBtn);

      const setStatus = (cls, text) => {
        status.className = 'detail-note-status ' + (cls || '');
        status.textContent = text || '';
      };
      editor.oninput = () => {
        const dirty = editor.value !== baseline;
        uiState.detail.noteDirty = dirty;
        saveBtn.disabled = !dirty;
        setStatus(dirty ? 'dirty' : '', dirty ? '未保存' : '');
      };
      cancelBtn.onclick = () => renderCollapsed();
      saveBtn.onclick = async () => {
        saveBtn.disabled = true;
        setStatus('', '保存中...');
        try {
          const { json } = await ctx.api.apiJson('/api/task-note', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: task.path, note: editor.value }),
          });
          if (!json.ok) {
            setStatus('error', json.message || json.error || '保存失败');
            saveBtn.disabled = false;
            return;
          }
          baseline = json.ai_note != null ? json.ai_note : editor.value;
          task.ai_note = baseline;
          uiState.detail.noteDirty = false;
          renderCollapsed();
          if (ctx.api && typeof ctx.api.refresh === 'function') ctx.api.refresh();
        } catch (e) {
          setStatus('error', '网络错误');
          saveBtn.disabled = false;
        }
      };

      block.appendChild(title);
      block.appendChild(editor);
      block.appendChild(toolbar);
      editor.focus();
    }

    renderCollapsed();
    detailMdContent.prepend(block);
  }


  Object.assign(detail, { shouldRenderNextStepRelay, activitySourceHistoryModel, syncEditModeUI, _detailSidebarState, setSidebarTab, setSidebarFolded, _shortText, _safeExternalCommentUrl, _formatExternalCommentTime, _externalCommentView, _mergeConcurrentComment, _externalEditButton, _jumpToExternalCommentSource, loadTaskComments, jumpToCommentAnchor, refreshCommentSidebarAvailability, renderCommentSidebar, normalizeDuplicateCommentAnchors, openCommentSidebar, destroyDetailDuePicker, restoreCurrentTaskLocation, updateEditorStatus, _blockTrailer, _renderDetailBlock, _renderTaskBodyBlocks, _restoreInlineEditor, _persistInlineBody, commitInlineBlockEdit, deleteInlineBlock, _autosizeInlineEditor, enterInlineBlockEdit, closeDetail, _openDetail, openTaskDetail, openTaskDetailByCode, updateDetailField, archiveCurrentTask, openDetailDuePicker, extractAcceptanceSection, stripAcceptanceSection, parseAcceptanceChecks, refreshCurrentDetailTask, bindAcceptanceCheckboxes, renderAcceptanceEditor, prependAcceptanceBlock, stripCardNoteSection, prependCardNoteBlock });
  return detail;
}
