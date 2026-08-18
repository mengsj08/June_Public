export function setupAi(ctx) {
  const { dataState, uiState, ui, markdown } = ctx;
  const {
    aiActivity, aiActivityList, detailClaudeBtn, detailCodexBtn,
    btnQueue, queueOverlay, queueSidebar, queueCloseBtn,
    processedBadge, runningCount, queuedCount,
    queueTabProcessed, queueTabRunning, queueTabQueued,
    queueBadge, detailQueueBadge
  } = ctx.el;
  const { isMobile, toast } = ui;
  const CARD_CHAT_TOOL_KEY = 'kanban.card_chat.tool';
  const CARD_CHAT_DEFAULT_TOOL = 'codex';
  const PROFILE_KEYS = {
    quick: 'quick_explain',
    deep: { claude: 'deep_claude', codex: 'deep_codex' },
    review: { claude: 'review_claude', codex: 'review_codex' },
    execute: { claude: 'execute_claude', codex: 'execute_codex' },
  };
  const PROFILE_LABEL_FALLBACKS = {
    quick_explain: 'Codex Luna',
    deep_claude: 'Claude Sonnet 5',
    deep_codex: 'Codex GPT-5.6',
    review_claude: 'Claude Opus 关键复核',
    review_codex: 'Codex 关键复核',
    execute_claude: 'Claude 执行',
    execute_codex: 'Codex 执行',
  };
  const ACTIVE_RUN_STATUSES = new Set(['queued', 'running', 'orphaned-running']);
  const TERMINAL_RUN_STATUSES = new Set(['completed', 'error', 'timeout', 'killed', 'orphaned-unknown']);
  const pendingSourceQuotes = new WeakMap();
  const aiState = {
    cardChat: null,
    bodyQuoteMenu: null,
    messageQuoteMenu: null,
    pendingBodyQuote: null,
    editorCursorReady: false,
    selectionExplainPopover: null,
    selectionExplainPollTimer: null,
    selectionExplainRunId: '',
    selectionExplainTerminal: false,
  };
  const ai = {
    CARD_CHAT_TOOL_KEY, CARD_CHAT_DEFAULT_TOOL, PROFILE_KEYS, PROFILE_LABEL_FALLBACKS,
    ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES, pendingSourceQuotes, aiState,
  };
  ctx.aiInternal = ai;
  const ensureCardChatComposer = (...args) => ai.ensureCardChatComposer(...args);
  const resolveBranchCtx = (...args) => ai.resolveBranchCtx(...args);
  const buildThreadTree = (...args) => ai.buildThreadTree(...args);
  const createThreadEntryElement = (...args) => ai.createThreadEntryElement(...args);
  const killAiRun = (...args) => ai.killAiRun(...args);
  const deleteAiResult = (...args) => ai.deleteAiResult(...args);
  const copyAiResult = (...args) => ai.copyAiResult(...args);
  const resumeQueueBadgePolling = (...args) => ai.resumeQueueBadgePolling(...args);

  function normalizeAiTool(tool) {
    return tool === 'claude' ? 'claude' : 'codex';
  }

  function toolLabel(tool) {
    return normalizeAiTool(tool) === 'claude' ? 'Claude' : 'Codex';
  }

  function profileKey(tier, tool = 'codex') {
    const configured = PROFILE_KEYS[tier];
    if (typeof configured === 'string') return configured;
    return configured ? configured[normalizeAiTool(tool)] : '';
  }

  function profileLabel(name, fallback = '') {
    const configured = dataState.ai_profiles && dataState.ai_profiles[name];
    return String((configured && configured.label) || PROFILE_LABEL_FALLBACKS[name] || fallback || name);
  }

  function isTransientSelectionEntry(entry) {
    const dialogue = entry && entry.metadata && entry.metadata.dialogue;
    return Boolean(dialogue && dialogue.lifecycle === 'transient');
  }

  function durableDialogueResults(results) {
    return (Array.isArray(results) ? results : []).filter((entry) => !isTransientSelectionEntry(entry));
  }

  function currentTaskTitle() {
    const task = (dataState.tasks || []).find((item) => item.path === uiState.detail.currentTaskPath);
    return task ? (task.task_id ? '[' + task.task_id + '] ' : '') + (task.title || '当前任务') : '当前任务';
  }

  function currentTaskGoal() {
    const body = String(uiState.detail.currentTaskBody || '')
      .replace(/^---[\s\S]*?---\s*/m, '')
      .replace(/^#{1,6}\s+.*$/gm, '')
      .trim();
    const paragraph = body.split(/\n\s*\n/).find((item) => item.trim()) || '';
    return paragraph.replace(/\s+/g, ' ').trim().slice(0, 500);
  }

  function selectionQuickPrompt(sourceQuote) {
    const quote = sourceQuote || {};
    const context = quote.context || {};
    const surrounding = (String(context.prefix || '') + String(quote.quote_text || '') + String(context.suffix || ''))
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 1200);
    const lines = [
      '请用中文快速解释选中的这段话。',
      '先用一句白话给出核心意思，再列出必要的概念或隐含前提；不要扩展成任务方案。',
      '任务：' + currentTaskTitle(),
    ];
    const goal = currentTaskGoal();
    if (goal) lines.push('任务目标/背景：' + goal);
    if (quote.section) lines.push('所在章节：' + quote.section);
    if (surrounding) lines.push('所在段落上下文：' + surrounding);
    return lines.join('\n');
  }

  function quickExplanationText(entry) {
    const messages = (entry && entry.messages) || [];
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message && message.role === 'ai' && message.content) return String(message.content);
    }
    return String((entry && (entry.output || entry.error)) || '没有返回内容');
  }

  function clearSelectionExplainPolling() {
    if (aiState.selectionExplainPollTimer) clearInterval(aiState.selectionExplainPollTimer);
    aiState.selectionExplainPollTimer = null;
  }

  function discardSelectionExplanation() {
    const runId = aiState.selectionExplainRunId;
    clearSelectionExplainPolling();
    aiState.selectionExplainRunId = '';
    aiState.selectionExplainTerminal = false;
    if (aiState.selectionExplainPopover) aiState.selectionExplainPopover.hidden = true;
    if (!runId || !ctx.hasApi) return;
    fetch('/api/ai-result', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: runId, path: uiState.detail.currentTaskPath }),
    }).catch(() => {});
  }

  function ensureSelectionExplainPopover(rect, sourceQuote, tool, aiProfile = '') {
    if (!aiState.selectionExplainPopover) {
      const root = document.createElement('section');
      root.className = 'selection-explain-popover';
      root.hidden = true;
      root.innerHTML = '<header>'
        + '<div><strong class="selection-explain-title">快速解释</strong>'
        + '<span class="selection-explain-tool"></span></div>'
        + '<button type="button" class="selection-explain-close" aria-label="关闭临时解释">×</button>'
        + '</header>'
        + '<div class="selection-explain-body" aria-live="polite"></div>'
        + '<footer>'
        + '<span>临时结果 · 不进入 Conversation Map</span>'
        + '<button type="button" class="selection-explain-deepen">继续深入问答</button>'
        + '</footer>';
      root.querySelector('.selection-explain-close').addEventListener('click', discardSelectionExplanation);
      root.querySelector('.selection-explain-deepen').addEventListener('click', () => {
        const quote = root._sourceQuote;
        const selectedTool = root._tool;
        discardSelectionExplanation();
        startSelectionSideChat(quote, selectedTool);
      });
      document.body.appendChild(root);
      aiState.selectionExplainPopover = root;
    }
    aiState.selectionExplainPopover._sourceQuote = sourceQuote;
    aiState.selectionExplainPopover._tool = normalizeAiTool(tool);
    aiState.selectionExplainPopover._profile = aiProfile;
    aiState.selectionExplainPopover.querySelector('.selection-explain-tool').textContent = profileLabel(aiProfile, toolLabel(tool));
    const width = Math.min(480, window.innerWidth - 24);
    aiState.selectionExplainPopover.style.width = width + 'px';
    aiState.selectionExplainPopover.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)) + 'px';
    aiState.selectionExplainPopover.style.top = Math.max(12, rect.bottom + 8) + 'px';
    aiState.selectionExplainPopover.hidden = false;
    requestAnimationFrame(() => {
      if (!aiState.selectionExplainPopover || aiState.selectionExplainPopover.hidden) return;
      const height = aiState.selectionExplainPopover.offsetHeight || 0;
      const below = rect.bottom + 8;
      aiState.selectionExplainPopover.style.top = (below + height <= window.innerHeight - 12
        ? below
        : Math.max(12, rect.top - height - 8)) + 'px';
    });
    return aiState.selectionExplainPopover;
  }

  function pollSelectionExplanation(runId) {
    if (!runId || runId !== aiState.selectionExplainRunId) return;
    fetch('/api/ai-results?run_id=' + encodeURIComponent(runId))
      .then((response) => response.json())
      .then((data) => {
        if (!data.ok || runId !== aiState.selectionExplainRunId) return;
        const entry = (data.results || []).find((item) => item.run_id === runId);
        if (!entry) return;
        const body = aiState.selectionExplainPopover && aiState.selectionExplainPopover.querySelector('.selection-explain-body');
        if (!body) return;
        if (entry.status === 'queued') {
          body.textContent = '已入队，等待 ' + toolLabel(entry.tool) + '…';
          return;
        }
        if (entry.status === 'running') {
          body.textContent = toolLabel(entry.tool) + ' 正在解释…';
          return;
        }
        clearSelectionExplainPolling();
        aiState.selectionExplainTerminal = true;
        const content = quickExplanationText(entry);
        body.textContent = '';
        if (entry.status === 'completed' && markdown.looksLikeMarkdown(content)) {
          markdown.renderMarkdownEnhanced(body, content, uiState.detail.currentTaskPath || '');
        } else {
          body.textContent = content;
        }
        body.classList.toggle('is-error', entry.status !== 'completed');
      })
      .catch(() => {});
  }

  function runSelectionQuickExplain(sourceQuote, rect) {
    if (!ctx.hasApi || !uiState.detail.currentTaskPath) {
      toast('当前任务没有可用的 AI 接口', true);
      return;
    }
    if (aiState.selectionExplainRunId) discardSelectionExplanation();
    const tool = 'codex';
    const aiProfile = profileKey('quick', tool);
    const popover = ensureSelectionExplainPopover(rect, sourceQuote, tool, aiProfile);
    const body = popover.querySelector('.selection-explain-body');
    body.classList.remove('is-error');
    body.textContent = '正在交给 ' + toolLabel(tool) + '…';
    aiState.selectionExplainTerminal = false;
    fetch('/api/ai-run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: uiState.detail.currentTaskPath,
        tool,
        profile: aiProfile,
        prompt: selectionQuickPrompt(sourceQuote),
        display_message: '快速解释：' + normalizedQuoteText(sourceQuote.quote_text).slice(0, 160),
        author: uiState.auth.currentUser || '用户',
        origin: 'selection_quick_explain',
        source_quote: sourceQuote,
      }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.error || '快速解释启动失败');
        aiState.selectionExplainRunId = data.run_id;
        pollSelectionExplanation(data.run_id);
        clearSelectionExplainPolling();
        aiState.selectionExplainPollTimer = setInterval(() => pollSelectionExplanation(data.run_id), 2000);
        resumeQueueBadgePolling();
      })
      .catch((error) => {
        body.classList.add('is-error');
        body.textContent = error.message || '快速解释启动失败';
        aiState.selectionExplainTerminal = true;
      });
  }

  function startSelectionSideChat(sourceQuote, tool) {
    ensureCardChatComposer();
    setCardChatTool(tool);
    setSourceQuote(aiState.cardChat.textarea, sourceQuote);
    aiState.cardChat.textarea.placeholder = '围绕选中文字继续问 ' + toolLabel(tool) + '…';
    aiState.cardChat.textarea.focus();
    updateCardChatState();
    scrollCardChatToBottom();
    toast('已建立选区旁聊起点；发送后仍默认不进入 Conversation Map');
  }

  async function fetchSkills() {
    if (uiState.ai.cachedSkills !== null) return uiState.ai.cachedSkills;
    try {
      const response = await fetch('/api/skills');
      const data = await response.json();
      uiState.ai.cachedSkills = data.ok ? (data.skills || []) : [];
    } catch (e) {
      uiState.ai.cachedSkills = [];
    }
    return uiState.ai.cachedSkills;
  }

  function messageTimestamp(ts) {
    return ts ? ts.replace('T', ' ').slice(11, 16) : '';
  }

  function messageAuthorLabel(msg, entry) {
    if (msg && msg.role === 'user') return msg.author || uiState.auth.currentUser || '用户';
    if (entry && (entry.tool === 'claude' || entry.tool === 'codex')) return toolLabel(entry.tool);
    return (msg && msg.author) || 'AI';
  }

  function createMessageBubble(msg, entry, msgIdx) {
    const bubble = document.createElement('div');
    const role = msg.role === 'user' ? 'user' : 'ai';
    bubble.className = 'msg-bubble';
    if (entry && entry.run_id && msgIdx !== undefined && msgIdx !== null) {
      bubble.dataset.entryId = entry.run_id + '#' + msgIdx;
      bubble.dataset.runId = entry.run_id;
      bubble.dataset.messageIndex = String(msgIdx);
    }

    const card = document.createElement('div');
    card.className = 'msg-card ' + role;

    const head = document.createElement('div');
    head.className = 'msg-head';

    const author = document.createElement('span');
    author.className = 'msg-author';
    const authorLabel = messageAuthorLabel(msg, entry);
    author.textContent = authorLabel;
    bubble.dataset.quoteAuthor = authorLabel;
    head.appendChild(author);

    if (msg.timestamp) {
      const time = document.createElement('span');
      time.textContent = messageTimestamp(msg.timestamp);
      head.appendChild(time);
    }

    if (role === 'ai') {
      const meta = [];
      if (msg.model) meta.push(msg.model);
      if (msg.input_tokens || msg.output_tokens) meta.push((msg.input_tokens || 0) + '/' + (msg.output_tokens || 0) + ' tokens');
      if (msg.duration_ms) meta.push((msg.duration_ms / 1000).toFixed(1) + 's');
      if (meta.length) {
        const info = document.createElement('span');
        info.textContent = meta.join(' · ');
        head.appendChild(info);
      }
    }

    card.appendChild(head);

    if (msg && msg.source_quote) {
      card.appendChild(createSourceQuoteCard(msg.source_quote));
    }

    const content = document.createElement('div');
    content.className = 'msg-content';
    const text = msg.content || '';
    if (markdown.looksLikeMarkdown(text)) {
      markdown.renderMarkdownEnhanced(content, text, uiState.detail.currentTaskPath || '');
    } else {
      content.textContent = text;
    }
    card.appendChild(content);
    bubble.appendChild(card);
    return bubble;
  }

  function rememberAiResults(results, loaded = true) {
    uiState.ai.currentResults = Array.isArray(results) ? results : [];
    uiState.ai.threadTree = buildThreadTree(uiState.ai.currentResults);
    uiState.ai.quoteHistoryLoaded = Boolean(loaded);
    refreshQuoteBlocks();
  }

  function refreshQuoteBlocks() {
    if (markdown && typeof markdown.refreshCommentQuoteAvailability === 'function') {
      markdown.refreshCommentQuoteAvailability();
    }
  }

  function normalizedQuoteText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function bodyQuoteBlocks() {
    const root = ctx.el.detailMdContent;
    return root
      ? Array.from(root.querySelectorAll('p, li, blockquote, h1, h2, h3, h4, h5, h6, pre, td, th'))
        .filter((block) => !(block.closest && block.closest('.comment-quote-block')))
      : [];
  }

  function chooseSourceQuoteIndex(sourceQuote, bodyText, currentRev) {
    const quote = String(sourceQuote && sourceQuote.quote_text || '');
    const body = String(bodyText || '');
    if (!quote) return -1;
    const matches = [];
    let cursor = 0;
    while (cursor <= body.length - quote.length) {
      const found = body.indexOf(quote, cursor);
      if (found < 0) break;
      matches.push(found);
      cursor = found + Math.max(quote.length, 1);
    }
    if (!matches.length) return -1;
    if (matches.length === 1) return matches[0];
    const locator = sourceQuote.source_locator || {};
    const recorded = Number(locator.text_index);
    if (locator.body_rev && currentRev && locator.body_rev === currentRev && matches.includes(recorded)) return recorded;
    const context = sourceQuote.context || {};
    const prefix = String(locator.prefix || context.prefix || '').slice(-160);
    const suffix = String(locator.suffix || context.suffix || '').slice(0, 160);
    const scored = matches.map((index) => {
      let score = 0;
      if (prefix && body.slice(Math.max(0, index - prefix.length), index) === prefix) score += 2;
      if (suffix && body.slice(index + quote.length, index + quote.length + suffix.length) === suffix) score += 2;
      return { index, score };
    }).sort((a, b) => b.score - a.score);
    if (!scored[0].score || (scored[1] && scored[1].score === scored[0].score)) return -1;
    return scored[0].index;
  }

  function resolveBodyQuoteTarget(sourceQuote) {
    if (!sourceQuote || !ctx.el.detailMdContent) return null;
    const locator = sourceQuote.source_locator || {};
    if (locator.task_path && locator.task_path !== uiState.detail.currentTaskPath) return null;
    const needle = normalizedQuoteText(sourceQuote.quote_text);
    if (!needle) return null;
    const blocks = bodyQuoteBlocks();
    const rawIndex = chooseSourceQuoteIndex(
      sourceQuote,
      uiState.detail.currentTaskBody || '',
      uiState.detail.currentTaskRev || '',
    );
    const indexed = Number(locator.block_index);
    if (Number.isInteger(indexed) && indexed >= 0 && blocks[indexed]) {
      const text = normalizedQuoteText(blocks[indexed].textContent);
      if (text.includes(needle) || (needle.length > 32 && text.includes(needle.slice(0, 32)))) return blocks[indexed];
    }
    const candidates = blocks.filter((block) => {
      const text = normalizedQuoteText(block.textContent);
      return text.includes(needle) || (needle.length > 32 && text.includes(needle.slice(0, 32)));
    });
    const occurrence = Number(locator.occurrence_index);
    if (Number.isInteger(occurrence) && occurrence >= 0 && candidates[occurrence]) return candidates[occurrence];
    if (rawIndex < 0 && Number(locator.text_index) >= 0 && candidates.length !== 1) return null;
    return candidates.length === 1 ? candidates[0] : null;
  }

  function jumpToBodyQuote(sourceQuote) {
    const target = resolveBodyQuoteTarget(sourceQuote);
    if (!target) {
      toast('正文原位置已变化，保留引用快照', true);
      return false;
    }
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.add('body-quote-highlight');
    setTimeout(() => target.classList.remove('body-quote-highlight'), 2200);
    return true;
  }

  function createSourceQuoteCard(sourceQuote) {
    const quote = sourceQuote || {};
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'source-quote-card';
    const target = resolveBodyQuoteTarget(quote);
    if (!target) card.classList.add('is-stale');
    const eyebrow = document.createElement('span');
    eyebrow.className = 'source-quote-eyebrow';
    eyebrow.textContent = quote.section ? ('正文 · ' + quote.section) : '任务正文';
    const text = document.createElement('span');
    text.className = 'source-quote-text';
    text.textContent = quote.quote_text || '（空引用）';
    const status = document.createElement('span');
    status.className = 'source-quote-status';
    status.textContent = target ? '定位原文 ↗' : '原位置已变化';
    card.appendChild(eyebrow);
    card.appendChild(text);
    card.appendChild(status);
    card.addEventListener('click', () => jumpToBodyQuote(quote));
    return card;
  }

  function sourceQuoteFromSelection(selection, range) {
    const quoteText = String(selection || '').trim();
    const body = String(uiState.detail.currentTaskBody || '');
    let textIndex = body.indexOf(quoteText);
    if (textIndex < 0) {
      const compact = quoteText.replace(/\s+/g, ' ');
      textIndex = body.replace(/\s+/g, ' ').indexOf(compact);
    }
    let section = '';
    if (textIndex >= 0) {
      const headings = Array.from(body.slice(0, textIndex).matchAll(/^#{1,6}\s+(.+)$/gm));
      if (headings.length) section = String(headings[headings.length - 1][1] || '').trim();
    }
    const block = range && range.commonAncestorContainer
      ? (range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement)
      : null;
    const closest = block && block.closest ? block.closest('p, li, blockquote, h1, h2, h3, h4, h5, h6, pre') : null;
    const blocks = bodyQuoteBlocks();
    const blockIndex = closest ? blocks.indexOf(closest) : -1;
    const prefix = textIndex >= 0 ? body.slice(Math.max(0, textIndex - 160), textIndex) : '';
    const suffix = textIndex >= 0 ? body.slice(textIndex + quoteText.length, textIndex + quoteText.length + 160) : '';
    return {
      quote_text: quoteText,
      section,
      context: { prefix, suffix },
      source_locator: {
        task_path: uiState.detail.currentTaskPath || '',
        body_rev: uiState.detail.currentTaskRev || '',
        text_index: textIndex,
        prefix,
        suffix,
        block_index: blockIndex,
      },
    };
  }

  function removeSourceQuote(textarea) {
    pendingSourceQuotes.delete(textarea);
    const holder = textarea && textarea.parentElement;
    const chip = holder && holder.querySelector(':scope > .source-quote-chip');
    if (chip) chip.remove();
  }

  function setSourceQuote(textarea, sourceQuote) {
    if (!textarea || !sourceQuote) return;
    pendingSourceQuotes.set(textarea, sourceQuote);
    const holder = textarea.parentElement;
    let chip = holder.querySelector(':scope > .source-quote-chip');
    if (!chip) {
      chip = document.createElement('div');
      chip.className = 'source-quote-chip';
      holder.insertBefore(chip, textarea);
    }
    chip.textContent = '';
    const label = document.createElement('span');
    label.className = 'source-quote-chip-label';
    label.textContent = sourceQuote.section ? ('引用正文 · ' + sourceQuote.section) : '引用任务正文';
    const text = document.createElement('span');
    text.className = 'source-quote-chip-text';
    text.textContent = normalizedQuoteText(sourceQuote.quote_text);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'source-quote-chip-remove';
    remove.textContent = '×';
    remove.title = '移除正文引用';
    remove.addEventListener('click', () => removeSourceQuote(textarea));
    chip.appendChild(label);
    chip.appendChild(text);
    chip.appendChild(remove);
    textarea.focus();
    textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function quoteTargetLabel(textarea) {
    if (textarea.classList.contains('card-chat-input')) return '新对话 · ' + toolLabel(getCardChatTool());
    if (textarea.classList.contains('fork-input')) {
      const thread = textarea.closest('.ai-thread');
      return '新分支 · ' + toolLabel(thread && thread.dataset.tool);
    }
    const thread = textarea.closest('.ai-thread');
    const title = thread && thread.querySelector('.thread-title');
    return '回复 ' + toolLabel(thread && thread.dataset.tool) + (title && title.textContent ? (' · ' + title.textContent.slice(0, 24)) : '');
  }

  function availableQuoteTargets() {
    ensureCardChatComposer();
    return Array.from(aiActivity.querySelectorAll('.card-chat-input, .comment-input'))
      .filter((textarea) => !textarea.disabled && textarea.offsetParent !== null);
  }

  function hideBodyQuoteMenu() {
    if (aiState.bodyQuoteMenu) aiState.bodyQuoteMenu.hidden = true;
  }

  function positionBodyQuoteMenu(rect) {
    if (!aiState.bodyQuoteMenu) return;
    const width = Math.min(300, window.innerWidth - 24);
    aiState.bodyQuoteMenu.style.width = width + 'px';
    aiState.bodyQuoteMenu.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)) + 'px';
    aiState.bodyQuoteMenu.style.top = Math.max(12, rect.bottom + 8) + 'px';
    aiState.bodyQuoteMenu.hidden = false;
    requestAnimationFrame(() => {
      if (!aiState.bodyQuoteMenu || aiState.bodyQuoteMenu.hidden) return;
      const height = aiState.bodyQuoteMenu.offsetHeight || 0;
      const below = rect.bottom + 8;
      aiState.bodyQuoteMenu.style.top = (below + height <= window.innerHeight - 12
        ? below
        : Math.max(12, rect.top - height - 8)) + 'px';
    });
  }

  function makeBodyQuoteAction(label, onClick, className = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'body-quote-target' + (className ? (' ' + className) : '');
    button.textContent = label;
    button.addEventListener('mousedown', (event) => event.preventDefault());
    button.addEventListener('click', onClick);
    return button;
  }

  function appendSelectionToDocument(sourceQuote, documentRow) {
    if (!documentRow || !documentRow.writable) return;
    fetch('/api/task-documents/append', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: uiState.detail.currentTaskPath,
        document_path: documentRow.path,
        source_quote: sourceQuote,
      }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.error || '写入失败');
        toast('已追加到 ' + (documentRow.label || '关联 Markdown') + '，来源锚点已保留');
      })
      .catch((error) => toast(error.message || '写入关联 Markdown 失败', true));
  }

  function showLinkedDocumentPicker(sourceQuote, rect) {
    aiState.bodyQuoteMenu.textContent = '';
    const title = document.createElement('div');
    title.className = 'body-quote-menu-title';
    title.textContent = '添加到关联 Markdown';
    aiState.bodyQuoteMenu.appendChild(title);
    const loading = document.createElement('div');
    loading.className = 'body-quote-menu-note';
    loading.textContent = '正在读取任务卡白名单…';
    aiState.bodyQuoteMenu.appendChild(loading);
    const back = makeBodyQuoteAction('← 返回选区动作', () => showBodyQuoteMenu(sourceQuote, rect), 'body-quote-back');
    aiState.bodyQuoteMenu.appendChild(back);
    positionBodyQuoteMenu(rect);
    fetch('/api/task-documents?path=' + encodeURIComponent(uiState.detail.currentTaskPath || ''))
      .then((response) => response.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.error || '读取关联文档失败');
        const documents = data.documents || [];
        loading.remove();
        if (!documents.length) {
          const empty = document.createElement('div');
          empty.className = 'body-quote-menu-note';
          empty.textContent = '这张任务卡还没有关联 Markdown。请先在 related_paths 中关联文档。';
          aiState.bodyQuoteMenu.insertBefore(empty, back);
          positionBodyQuoteMenu(rect);
          return;
        }
        documents.forEach((row) => {
          const label = (row.is_default ? '默认 · ' : '') + (row.label || row.path);
          const button = makeBodyQuoteAction(label, () => {
            appendSelectionToDocument(sourceQuote, row);
            hideBodyQuoteMenu();
            window.getSelection()?.removeAllRanges();
          }, 'body-quote-document');
          button.title = row.reason || row.path;
          button.disabled = !row.writable;
          aiState.bodyQuoteMenu.insertBefore(button, back);
        });
        positionBodyQuoteMenu(rect);
      })
      .catch((error) => {
        loading.textContent = error.message || '读取关联文档失败';
        loading.classList.add('is-error');
      });
  }

  function showBodyQuoteMenu(sourceQuote, rect) {
    hideMessageQuoteMenu();
    if (!aiState.bodyQuoteMenu) {
      aiState.bodyQuoteMenu = document.createElement('div');
      aiState.bodyQuoteMenu.className = 'body-quote-menu';
      aiState.bodyQuoteMenu.hidden = true;
      document.body.appendChild(aiState.bodyQuoteMenu);
    }
    aiState.bodyQuoteMenu.textContent = '';
    const title = document.createElement('div');
    title.className = 'body-quote-menu-title';
    title.textContent = '理解与延伸';
    aiState.bodyQuoteMenu.appendChild(title);
    aiState.bodyQuoteMenu.appendChild(makeBodyQuoteAction('快速解释 · ' + profileLabel(profileKey('quick')), () => {
      runSelectionQuickExplain(sourceQuote, rect);
      hideBodyQuoteMenu();
      window.getSelection()?.removeAllRanges();
    }, 'body-quote-quick-explain'));
    ['claude', 'codex'].forEach((tool) => {
      const deepProfile = profileKey('deep', tool);
      aiState.bodyQuoteMenu.appendChild(makeBodyQuoteAction('深入问 · ' + profileLabel(deepProfile, toolLabel(tool)), () => {
        startSelectionSideChat(sourceQuote, tool);
        hideBodyQuoteMenu();
        window.getSelection()?.removeAllRanges();
      }, 'body-quote-deep-question'));
    });
    const archiveTitle = document.createElement('div');
    archiveTitle.className = 'body-quote-menu-title';
    archiveTitle.textContent = '引用与写入';
    aiState.bodyQuoteMenu.appendChild(archiveTitle);
    aiState.bodyQuoteMenu.appendChild(makeBodyQuoteAction('添加到关联 Markdown', () => {
      showLinkedDocumentPicker(sourceQuote, rect);
    }, 'body-quote-linked-document'));
    aiState.bodyQuoteMenu.appendChild(makeBodyQuoteAction('插入到任务正文', () => {
      requestBodyQuoteInsert({ ...sourceQuote, source: 'body' });
      hideBodyQuoteMenu();
      window.getSelection()?.removeAllRanges();
    }, 'body-quote-insert-body'));
    const commentTitle = document.createElement('div');
    commentTitle.className = 'body-quote-menu-title';
    commentTitle.textContent = '引用到评论';
    aiState.bodyQuoteMenu.appendChild(commentTitle);
    availableQuoteTargets().forEach((textarea) => {
      const button = makeBodyQuoteAction(quoteTargetLabel(textarea), () => {
        setSourceQuote(textarea, sourceQuote);
        hideBodyQuoteMenu();
        window.getSelection()?.removeAllRanges();
      });
      aiState.bodyQuoteMenu.appendChild(button);
    });
    positionBodyQuoteMenu(rect);
  }

  function offerBodySelectionQuote() {
    const root = ctx.el.detailMdContent;
    const selection = window.getSelection && window.getSelection();
    if (!root || !selection || selection.isCollapsed || !selection.rangeCount) {
      hideBodyQuoteMenu();
      return;
    }
    const range = selection.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) {
      hideBodyQuoteMenu();
      return;
    }
    const selected = String(selection.toString() || '').trim();
    if (!selected) {
      hideBodyQuoteMenu();
      return;
    }
    showBodyQuoteMenu(sourceQuoteFromSelection(selected.slice(0, 2000), range), range.getBoundingClientRect());
  }

  function _messageBubbleForSelectionNode(node) {
    const element = node && node.nodeType === 1 ? node : (node && node.parentElement);
    return element && typeof element.closest === 'function'
      ? element.closest('.msg-bubble[data-entry-id]')
      : null;
  }

  function messageQuoteFromSelection(selection) {
    if (!selection || selection.isCollapsed || !selection.rangeCount) return null;
    const anchorBubble = _messageBubbleForSelectionNode(selection.anchorNode);
    const focusBubble = _messageBubbleForSelectionNode(selection.focusNode);
    if (!anchorBubble || anchorBubble !== focusBubble) return null;
    const content = anchorBubble.querySelector && anchorBubble.querySelector('.msg-content');
    if (!content || !content.contains(selection.anchorNode) || !content.contains(selection.focusNode)) return null;
    const excerpt = String(selection.toString() || '').trim();
    const ref = String(anchorBubble.dataset && anchorBubble.dataset.entryId || '');
    const author = String(anchorBubble.dataset && anchorBubble.dataset.quoteAuthor || '').trim();
    if (!excerpt || !/^[^#\s"<>]+#[0-9]+$/.test(ref) || !author) return null;
    return { ref, author, excerpt };
  }

  function _commentQuoteAttrEscape(value) {
    return String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  }

  function createCommentQuoteToken(quote) {
    if (!quote || !quote.ref || !quote.author || !quote.excerpt) return '';
    return ':::comment-quote ref="' + _commentQuoteAttrEscape(quote.ref)
      + '" author="' + _commentQuoteAttrEscape(quote.author) + '"\n'
      + String(quote.excerpt).trim() + '\n:::';
  }

  function createBodyQuoteToken(sourceQuote) {
    if (!sourceQuote || !sourceQuote.quote_text) return '';
    let locator = '';
    try {
      locator = encodeURIComponent(JSON.stringify(sourceQuote.source_locator || {}));
    } catch (e) {
      locator = '';
    }
    return ':::comment-quote source="body" section="' + _commentQuoteAttrEscape(sourceQuote.section || '')
      + '" locator="' + _commentQuoteAttrEscape(locator) + '"\n'
      + String(sourceQuote.quote_text).trim() + '\n:::';
  }

  function createPersistentQuoteToken(quote) {
    if (quote && (quote.source === 'body' || quote.quote_text || quote.source_locator)) {
      return createBodyQuoteToken(quote);
    }
    return createCommentQuoteToken(quote);
  }

  function pendingQuoteText(quote) {
    return String((quote && (quote.excerpt || quote.quote_text)) || '').trim();
  }

  function _pendingBodyQuoteControl() {
    const editMode = ctx.el.detailEditMode;
    const editor = ctx.el.detailEditor;
    if (!editMode || !editor) return null;
    let control = editMode.querySelector('.pending-body-quote');
    if (control) return control;
    control = document.createElement('div');
    control.className = 'pending-body-quote';
    control.hidden = true;
    control.innerHTML = '<div class="pending-body-quote-copy">'
      + '<span class="pending-body-quote-label">待插入正文</span>'
      + '<span class="pending-body-quote-text"></span>'
      + '<span class="pending-body-quote-hint"></span>'
      + '</div>'
      + '<button type="button" class="pending-body-quote-insert">插入到光标</button>'
      + '<button type="button" class="pending-body-quote-cancel" aria-label="取消待插入引用">×</button>';
    control.querySelector('.pending-body-quote-insert').addEventListener('click', insertPendingBodyQuote);
    control.querySelector('.pending-body-quote-cancel').addEventListener('click', () => {
      aiState.pendingBodyQuote = null;
      renderPendingBodyQuote();
    });
    editMode.insertBefore(control, editor);
    return control;
  }

  function renderPendingBodyQuote() {
    const editMode = ctx.el.detailEditMode;
    const existing = editMode && editMode.querySelector
      ? editMode.querySelector('.pending-body-quote')
      : null;
    if (!aiState.pendingBodyQuote && !existing) return;
    const control = existing || _pendingBodyQuoteControl();
    if (!control) return;
    control.hidden = !aiState.pendingBodyQuote;
    if (!aiState.pendingBodyQuote) return;
    const taskPath = aiState.pendingBodyQuote.taskPath
      || (aiState.pendingBodyQuote.source_locator && aiState.pendingBodyQuote.source_locator.task_path)
      || '';
    const taskMatches = !taskPath || taskPath === uiState.detail.currentTaskPath;
    const canInsert = Boolean(uiState.detail.isEditMode && aiState.editorCursorReady && taskMatches);
    control.querySelector('.pending-body-quote-text').textContent = normalizedQuoteText(pendingQuoteText(aiState.pendingBodyQuote));
    control.querySelector('.pending-body-quote-hint').textContent = canInsert
      ? '光标位置已就绪'
      : (taskMatches ? '请先在下方正文中放置光标' : '引用来自另一张任务卡');
    control.querySelector('.pending-body-quote-insert').disabled = !canInsert;
  }

  function _insertCommentQuoteAtCursor(textarea, quote) {
    if (!textarea || !quote || !aiState.editorCursorReady || !uiState.detail.isEditMode) return false;
    if (quote.taskPath && quote.taskPath !== uiState.detail.currentTaskPath) return false;
    const token = createPersistentQuoteToken(quote);
    if (!token) return false;
    const cursor = Number(textarea.selectionStart);
    const selectionEnd = Number(textarea.selectionEnd);
    if (!Number.isInteger(cursor) || !Number.isInteger(selectionEnd)) return false;
    const before = textarea.value.slice(0, cursor);
    const after = textarea.value.slice(cursor);
    const leading = before && !before.endsWith('\n') ? '\n\n' : '';
    const trailing = after && !after.startsWith('\n') ? '\n\n' : '';
    const insertion = leading + token + trailing;
    textarea.setRangeText(insertion, cursor, cursor, 'end');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    textarea.focus();
    if (!(quote.source === 'body' || quote.quote_text || quote.source_locator)) {
      uiState.detail.openCommentsAfterSave = true;
    }
    return true;
  }

  function insertPendingBodyQuote() {
    if (!aiState.pendingBodyQuote || !_insertCommentQuoteAtCursor(ctx.el.detailEditor, aiState.pendingBodyQuote)) {
      toast('先进入正文编辑并放置光标', true);
      renderPendingBodyQuote();
      return false;
    }
    aiState.pendingBodyQuote = null;
    renderPendingBodyQuote();
    toast('引用已插入正文，保存后才会写入任务卡');
    return true;
  }

  function requestBodyQuoteInsert(quote) {
    if (!quote) return false;
    const scopedQuote = {
      ...quote,
      taskPath: quote.taskPath
        || (quote.source_locator && quote.source_locator.task_path)
        || uiState.detail.currentTaskPath
        || '',
    };
    if (_insertCommentQuoteAtCursor(ctx.el.detailEditor, scopedQuote)) {
      aiState.pendingBodyQuote = null;
      renderPendingBodyQuote();
      toast('引用已插入正文，保存后才会写入任务卡');
      return true;
    }
    aiState.pendingBodyQuote = scopedQuote;
    if (!uiState.detail.isEditMode && ctx.renderDetail && typeof ctx.renderDetail.enterEditMode === 'function') {
      ctx.renderDetail.enterEditMode();
      markEditorCursorReady();
      if (_insertCommentQuoteAtCursor(ctx.el.detailEditor, scopedQuote)) {
        aiState.pendingBodyQuote = null;
        renderPendingBodyQuote();
        toast('引用已插入正文，保存后才会写入任务卡');
        return true;
      }
    }
    aiState.editorCursorReady = false;
    renderPendingBodyQuote();
    toast('先进入正文编辑并放置光标', true);
    return false;
  }

  function hideMessageQuoteMenu() {
    if (aiState.messageQuoteMenu) aiState.messageQuoteMenu.hidden = true;
  }

  function showMessageQuoteMenu(quote, rect) {
    hideBodyQuoteMenu();
    if (!aiState.messageQuoteMenu) {
      aiState.messageQuoteMenu = document.createElement('div');
      aiState.messageQuoteMenu.className = 'message-quote-menu';
      aiState.messageQuoteMenu.hidden = true;
      document.body.appendChild(aiState.messageQuoteMenu);
    }
    aiState.messageQuoteMenu.textContent = '';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'message-quote-insert';
    button.textContent = '插入正文';
    button.addEventListener('mousedown', (event) => event.preventDefault());
    button.addEventListener('click', () => {
      requestBodyQuoteInsert(quote);
      hideMessageQuoteMenu();
      window.getSelection()?.removeAllRanges();
    });
    aiState.messageQuoteMenu.appendChild(button);
    aiState.messageQuoteMenu.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - 112)) + 'px';
    aiState.messageQuoteMenu.style.top = Math.max(12, rect.bottom + 7) + 'px';
    aiState.messageQuoteMenu.hidden = false;
  }

  function offerMessageSelectionQuote() {
    const selection = window.getSelection && window.getSelection();
    const quote = messageQuoteFromSelection(selection);
    if (!quote) {
      hideMessageQuoteMenu();
      return;
    }
    showMessageQuoteMenu(quote, selection.getRangeAt(0).getBoundingClientRect());
  }

  function markEditorCursorReady() {
    if (!uiState.detail.isEditMode) return;
    const editor = ctx.el.detailEditor;
    if (!editor || !Number.isInteger(Number(editor.selectionStart)) || !Number.isInteger(Number(editor.selectionEnd))) return;
    aiState.editorCursorReady = true;
    renderPendingBodyQuote();
  }

  function onDetailEditModeChange(isEditing) {
    aiState.editorCursorReady = false;
    if (!isEditing) hideMessageQuoteMenu();
    renderPendingBodyQuote();
  }

  function selectionSideChatSourceQuote(entry) {
    const dialogue = entry && entry.metadata && entry.metadata.dialogue;
    if (!dialogue || dialogue.origin !== 'selection_side_chat') return null;
    const message = (entry.messages || []).find((item) => item && item.role === 'user' && item.source_quote);
    return message && message.source_quote ? message.source_quote : null;
  }

  function stableSelectionId(sourceQuote) {
    const locator = (sourceQuote && sourceQuote.source_locator) || {};
    const raw = JSON.stringify({
      task_path: locator.task_path || uiState.detail.currentTaskPath || '',
      body_rev: locator.body_rev || '',
      text_index: Number(locator.text_index || 0),
      block_index: Number(locator.block_index || 0),
      quote_text: String((sourceQuote && sourceQuote.quote_text) || ''),
    });
    let hash = 2166136261;
    for (let index = 0; index < raw.length; index += 1) {
      hash ^= raw.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return 'selection:' + (hash >>> 0).toString(16).padStart(8, '0');
  }

  function promoteSelectionSideChat(entry, button) {
    const sourceQuote = selectionSideChatSourceQuote(entry);
    if (!sourceQuote || !entry || !entry.run_id) return;
    if (button) {
      button.disabled = true;
      button.textContent = '保留中…';
    }
    fetch('/api/conversation-relations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: { type: 'selection', id: stableSelectionId(sourceQuote) },
        to: { type: 'branch', id: 'run:' + entry.run_id },
        relation: 'branch_from',
        assertion: 'human_confirmed',
        confidence: 1,
        evidence: [{
          kind: 'explicit_keep_to_map',
          run_id: entry.run_id,
          task_path: uiState.detail.currentTaskPath || '',
          source_quote: sourceQuote,
          title: entry.title || '',
        }],
      }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.error || '保留失败');
        if (button) button.textContent = data.deduped ? '已在地图' : '已保留到地图';
        toast(data.deduped ? '这条旁聊已经在 Conversation Map' : '已保留到 Conversation Map，并记录 branch_from');
      })
      .catch((error) => {
        if (button) {
          button.disabled = false;
          button.textContent = '保留到地图';
        }
        toast(error.message || '保留到地图失败', true);
      });
  }

  function createThreadActions(entry) {
    const wrap = document.createElement('div');
    wrap.className = 'thread-actions';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'ai-action-btn';
    copyBtn.textContent = '复制';
    copyBtn.onclick = () => copyAiResult(entry.run_id);
    wrap.appendChild(copyBtn);

    if (selectionSideChatSourceQuote(entry)) {
      const keepBtn = document.createElement('button');
      keepBtn.className = 'ai-action-btn';
      keepBtn.textContent = '保留到地图';
      keepBtn.onclick = () => promoteSelectionSideChat(entry, keepBtn);
      wrap.appendChild(keepBtn);
    }

    if (entry.status !== 'orphaned-running') {
      const delBtn = document.createElement('button');
      delBtn.className = 'ai-action-btn';
      delBtn.textContent = '删除';
      delBtn.onclick = () => deleteAiResult(entry.run_id);
      wrap.appendChild(delBtn);
    }

    if (entry.status === 'running') {
      const killBtn = document.createElement('button');
      killBtn.className = 'ai-kill-btn';
      killBtn.textContent = '终止';
      killBtn.onclick = () => killAiRun(entry.run_id);
      wrap.appendChild(killBtn);
    }

    return wrap;
  }

  function createSessionExpiredNotice() {
    const box = document.createElement('div');
    box.className = 'session-expired';
    box.textContent = '会话已失效，无法继续评论。';
    return box;
  }

  function canComment(entry) {
    return (entry.tool === 'claude' || entry.tool === 'codex')
      && (entry.status === 'completed' || entry.status === 'error' || entry.status === 'killed')
      && entry.session_id
      && entry.session_valid !== false;
  }

  function canRetry(entry) {
    return entry.tool === 'claude'
      && (entry.status === 'killed' || entry.status === 'error')
      && (!entry.session_id || entry.session_valid === false);
  }

  function scrollToThread(runId) {
    const thread = aiActivityList.querySelector('[data-run-id="' + runId + '"]');
    if (!thread) return false;
    thread.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return true;
  }

  function syncQueueEntryDom(entry) {
    const el = aiActivityList.querySelector('[data-run-id="' + entry.run_id + '"]');
    const next = createThreadEntryElement(entry, resolveBranchCtx());
    if (el) el.replaceWith(next);
    else aiActivityList.appendChild(next);
  }

  function createSlashMenu(textarea, inputWrapper) {
    const menu = document.createElement('div');
    menu.className = 'slash-menu';
    const hint = document.createElement('div');
    hint.className = 'slash-hint';
    inputWrapper.appendChild(menu);
    inputWrapper.appendChild(hint);

    let skills = [];
    let filtered = [];
    let activeIndex = 0;
    let selectedSkill = null;
    let currentQuery = '';
    let openSeq = 0;

    const getFilterQuery = () => {
      const value = textarea.value;
      const pos = textarea.selectionStart || 0;
      const before = value.slice(0, pos);
      if (!before.startsWith('/')) return null;
      if (before.includes('\n')) return null;
      const spaceIndex = before.search(/\s/);
      if (spaceIndex !== -1) return null;
      return before.slice(1);
    };

    const renderHint = () => {
      if (!selectedSkill) {
        hint.classList.remove('on');
        hint.textContent = '';
        return;
      }
      hint.textContent = '';
      const skill = document.createElement('span');
      skill.className = 'slash-hint-skill';
      skill.textContent = '将应用 /' + selectedSkill.id;
      hint.appendChild(skill);
      if (selectedSkill.argument_hint) hint.appendChild(document.createTextNode(' ' + selectedSkill.argument_hint));
      hint.classList.add('on');
    };

    const clearSelectedSkill = () => {
      selectedSkill = null;
      renderHint();
    };

    const syncSelectedFromText = () => {
      if (!selectedSkill) return;
      const value = textarea.value.trim();
      const prefix = '/' + selectedSkill.id;
      if (!(value === prefix || value.startsWith(prefix + ' '))) clearSelectedSkill();
    };

    const syncManualSkillFromText = async () => {
      const value = textarea.value.trim();
      const match = value.match(/^\/([A-Za-z0-9_.-]+)(?:\s|$)/);
      if (!match) {
        clearSelectedSkill();
        return;
      }
      const all = await fetchSkills();
      const found = all.find((skill) => skill.id === match[1]);
      if (found) {
        selectedSkill = found;
        renderHint();
      } else {
        clearSelectedSkill();
      }
    };

    const scoreSkill = (skill, query) => {
      const q = query.toLowerCase();
      const id = (skill.id || '').toLowerCase();
      const name = (skill.name || '').toLowerCase();
      const desc = (skill.description || '').toLowerCase();
      if (!q) return 10;
      if (id.startsWith(q) || name.startsWith(q)) return 0;
      if (id.includes(q) || name.includes(q)) return 1;
      if (desc.includes(q)) return 2;
      return 99;
    };

    const renderMenu = () => {
      menu.textContent = '';
      if (!skills.length) {
        const empty = document.createElement('div');
        empty.className = 'slash-empty';
        empty.textContent = '暂无可用命令';
        menu.appendChild(empty);
        return;
      }
      if (!filtered.length) {
        const empty = document.createElement('div');
        empty.className = 'slash-empty';
        empty.textContent = '无匹配命令';
        menu.appendChild(empty);
        return;
      }
      filtered.forEach((skill, idx) => {
        const item = document.createElement('div');
        item.className = 'slash-item' + (idx === activeIndex ? ' active' : '');
        const name = document.createElement('span');
        name.className = 'slash-item-name';
        name.textContent = '/' + skill.id;
        const desc = document.createElement('span');
        desc.className = 'slash-item-desc';
        desc.textContent = skill.description || skill.name || '';
        item.appendChild(name);
        item.appendChild(desc);
        item.addEventListener('mousedown', (e) => {
          e.preventDefault();
          activeIndex = idx;
          selectSkill(skill);
        });
        menu.appendChild(item);
      });
    };

    const filter = (query) => {
      currentQuery = query || '';
      filtered = skills
        .map((skill) => ({ skill, score: scoreSkill(skill, currentQuery) }))
        .filter((item) => item.score < 99)
        .sort((a, b) => a.score - b.score || (a.skill.name || a.skill.id).localeCompare(b.skill.name || b.skill.id))
        .map((item) => item.skill);
      activeIndex = 0;
      renderMenu();
    };

    const open = async (query) => {
      const seq = ++openSeq;
      skills = await fetchSkills();
      if (seq !== openSeq) return;
      filter(query || '');
      menu.classList.add('on');
    };

    const close = () => {
      openSeq += 1;
      menu.classList.remove('on');
    };

    const selectSkill = (skill) => {
      const value = textarea.value;
      const pos = textarea.selectionStart || 0;
      const after = value.slice(pos);
      const replacement = '/' + skill.id + ' ';
      textarea.value = replacement + after;
      textarea.selectionStart = replacement.length;
      textarea.selectionEnd = replacement.length;
      selectedSkill = skill;
      close();
      renderHint();
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      textarea.focus();
    };

    const moveActive = (dir) => {
      if (!filtered.length) return;
      activeIndex = (activeIndex + dir + filtered.length) % filtered.length;
      renderMenu();
      const active = menu.querySelector('.slash-item.active');
      if (active) active.scrollIntoView({ block: 'nearest' });
    };

    const confirmActive = () => {
      if (!filtered.length) return false;
      selectSkill(filtered[activeIndex]);
      return true;
    };

    return {
      el: menu,
      open,
      close,
      isOpen: () => menu.classList.contains('on'),
      filter,
      moveActive,
      confirmActive,
      getSelectedSkill: () => selectedSkill,
      clearSelectedSkill,
      syncSelectedFromText,
      syncManualSkillFromText,
      getFilterQuery,
    };
  }

  function createNoOpSlashMenu() {
    return {
      el: null,
      open: () => {},
      close: () => {},
      isOpen: () => false,
      filter: () => {},
      moveActive: () => {},
      confirmActive: () => {},
      getSelectedSkill: () => null,
      clearSelectedSkill: () => {},
      syncSelectedFromText: () => {},
      syncManualSkillFromText: () => {},
      getFilterQuery: () => null,
    };
  }

  function getCardChatTool() {
    if (uiState.ai.cardChatTool) return normalizeAiTool(uiState.ai.cardChatTool);
    try {
      const saved = localStorage.getItem(CARD_CHAT_TOOL_KEY);
      uiState.ai.cardChatTool = (saved === 'claude' || saved === 'codex') ? saved : CARD_CHAT_DEFAULT_TOOL;
    } catch (e) {
      uiState.ai.cardChatTool = CARD_CHAT_DEFAULT_TOOL;
    }
    return normalizeAiTool(uiState.ai.cardChatTool);
  }

  function setCardChatTool(tool) {
    const next = normalizeAiTool(tool);
    uiState.ai.cardChatTool = next;
    try {
      localStorage.setItem(CARD_CHAT_TOOL_KEY, next);
    } catch (e) {}
    syncCardChatToolUi();
  }

  function resizeCardChatInput() {
    if (!aiState.cardChat) return;
    const textarea = aiState.cardChat.textarea;
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 160) + 'px';
  }

  function syncCardChatToolUi() {
    if (!aiState.cardChat) return;
    const tool = getCardChatTool();
    aiState.cardChat.toolButtons.forEach((btn) => {
      const on = btn.dataset.tool === tool;
      btn.classList.toggle('on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    aiState.cardChat.textarea.placeholder = '写给 ' + toolLabel(tool) + '...';
  }

  function cardChatActiveText() {
    const status = uiState.ai.cardChatActiveStatus || '';
    if (status === 'queued') return '已入队，等待 AI 接手。';
    if (status === 'running') return 'AI 正在处理，稍后可继续发送。';
    if (status === 'orphaned-running') return '服务已重启；进程仍在运行，但输出已断开。';
    return '';
  }

  function updateCardChatState() {
    if (!aiState.cardChat) return;
    const hasTaskPath = Boolean(uiState.detail.currentTaskPath);
    const isDone = uiState.detail.currentTaskStatus === 'done';
    const isSubmitting = Boolean(uiState.ai.cardChatSubmitting);
    const hasActiveRun = Boolean(uiState.ai.cardChatActiveRunId);
    const disabled = !ctx.hasApi || !hasTaskPath || isDone || isSubmitting || hasActiveRun;
    const hasText = Boolean(aiState.cardChat.textarea.value.trim());

    aiState.cardChat.textarea.disabled = disabled;
    aiState.cardChat.sendBtn.disabled = disabled || !hasText;
    aiState.cardChat.sendBtn.classList.toggle('is-busy', isSubmitting || hasActiveRun);
    aiState.cardChat.toolButtons.forEach((btn) => { btn.disabled = disabled; });

    let statusText = '';
    let statusClass = '';
    if (!ctx.hasApi) {
      statusText = '当前页面没有 API，无法派发。';
      statusClass = 'is-error';
    } else if (!hasTaskPath) {
      statusText = '当前不是任务卡。';
      statusClass = 'is-muted';
    } else if (isDone) {
      statusText = '任务已完成，不能再启动 AI。';
      statusClass = 'is-muted';
    } else if (isSubmitting) {
      statusText = '正在派发...';
      statusClass = 'is-active';
    } else if (hasActiveRun) {
      statusText = cardChatActiveText();
      statusClass = 'is-active';
    }
    aiState.cardChat.status.textContent = statusText;
    aiState.cardChat.status.className = 'card-chat-status ' + statusClass;
  }

  function syncCardChatActiveFromResults(results) {
    const active = durableDialogueResults(results).find((entry) => ACTIVE_RUN_STATUSES.has(entry.status));
    uiState.ai.cardChatActiveRunId = active ? active.run_id : '';
    uiState.ai.cardChatActiveStatus = active ? active.status : '';
    updateCardChatState();
  }

  function updateCardChatEmptyState(hasThreads) {
    if (!aiState.cardChat) return;
    aiState.cardChat.empty.hidden = Boolean(hasThreads);
  }

  function scrollCardChatToBottom() {
    if (!aiActivity || !aiActivity.scrollIntoView) return;
    requestAnimationFrame(() => {
      if (aiState.cardChat && aiState.cardChat.composer) {
        aiState.cardChat.composer.scrollIntoView({ behavior: 'smooth', block: 'end' });
      }
    });
  }


  Object.assign(ai, { normalizeAiTool, toolLabel, profileKey, profileLabel, isTransientSelectionEntry, durableDialogueResults, currentTaskTitle, currentTaskGoal, selectionQuickPrompt, quickExplanationText, clearSelectionExplainPolling, discardSelectionExplanation, ensureSelectionExplainPopover, pollSelectionExplanation, runSelectionQuickExplain, startSelectionSideChat, fetchSkills, messageTimestamp, messageAuthorLabel, createMessageBubble, rememberAiResults, refreshQuoteBlocks, normalizedQuoteText, bodyQuoteBlocks, chooseSourceQuoteIndex, resolveBodyQuoteTarget, jumpToBodyQuote, createSourceQuoteCard, sourceQuoteFromSelection, removeSourceQuote, setSourceQuote, quoteTargetLabel, availableQuoteTargets, hideBodyQuoteMenu, positionBodyQuoteMenu, makeBodyQuoteAction, appendSelectionToDocument, showLinkedDocumentPicker, showBodyQuoteMenu, offerBodySelectionQuote, _messageBubbleForSelectionNode, messageQuoteFromSelection, _commentQuoteAttrEscape, createCommentQuoteToken, createBodyQuoteToken, createPersistentQuoteToken, pendingQuoteText, _pendingBodyQuoteControl, renderPendingBodyQuote, _insertCommentQuoteAtCursor, insertPendingBodyQuote, requestBodyQuoteInsert, hideMessageQuoteMenu, showMessageQuoteMenu, offerMessageSelectionQuote, markEditorCursorReady, onDetailEditModeChange, selectionSideChatSourceQuote, stableSelectionId, promoteSelectionSideChat, createThreadActions, createSessionExpiredNotice, canComment, canRetry, scrollToThread, syncQueueEntryDom, createSlashMenu, createNoOpSlashMenu, getCardChatTool, setCardChatTool, resizeCardChatInput, syncCardChatToolUi, cardChatActiveText, updateCardChatState, syncCardChatActiveFromResults, updateCardChatEmptyState, scrollCardChatToBottom });
  return ai;
}
