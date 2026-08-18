// KAN-1671: mounted by main.js; dependencies arrive through ctx.aiInternal.
export function setupAiQueue(ctx) {
  const ai = ctx.aiInternal;
  if (!ai) throw new Error('setupAi(ctx) must run first');
  const { dataState, uiState, ui, markdown } = ctx;
  const {
    aiActivity, aiActivityList, detailClaudeBtn, detailCodexBtn,
    btnQueue, queueOverlay, queueSidebar, queueCloseBtn,
    processedBadge, runningCount, queuedCount,
    queueTabProcessed, queueTabRunning, queueTabQueued,
    queueBadge, detailQueueBadge
  } = ctx.el;
  const { isMobile, toast } = ui;
  const { CARD_CHAT_TOOL_KEY, CARD_CHAT_DEFAULT_TOOL, ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES, pendingSourceQuotes, aiState } = ai;
  const normalizeAiTool = (...args) => ai.normalizeAiTool(...args);
  const toolLabel = (...args) => ai.toolLabel(...args);
  const profileKey = (...args) => ai.profileKey(...args);
  const profileLabel = (...args) => ai.profileLabel(...args);
  const isTransientSelectionEntry = (...args) => ai.isTransientSelectionEntry(...args);
  const durableDialogueResults = (...args) => ai.durableDialogueResults(...args);
  const currentTaskTitle = (...args) => ai.currentTaskTitle(...args);
  const currentTaskGoal = (...args) => ai.currentTaskGoal(...args);
  const selectionQuickPrompt = (...args) => ai.selectionQuickPrompt(...args);
  const quickExplanationText = (...args) => ai.quickExplanationText(...args);
  const clearSelectionExplainPolling = (...args) => ai.clearSelectionExplainPolling(...args);
  const discardSelectionExplanation = (...args) => ai.discardSelectionExplanation(...args);
  const ensureSelectionExplainPopover = (...args) => ai.ensureSelectionExplainPopover(...args);
  const pollSelectionExplanation = (...args) => ai.pollSelectionExplanation(...args);
  const runSelectionQuickExplain = (...args) => ai.runSelectionQuickExplain(...args);
  const startSelectionSideChat = (...args) => ai.startSelectionSideChat(...args);
  const fetchSkills = (...args) => ai.fetchSkills(...args);
  const messageTimestamp = (...args) => ai.messageTimestamp(...args);
  const messageAuthorLabel = (...args) => ai.messageAuthorLabel(...args);
  const createMessageBubble = (...args) => ai.createMessageBubble(...args);
  const rememberAiResults = (...args) => ai.rememberAiResults(...args);
  const refreshQuoteBlocks = (...args) => ai.refreshQuoteBlocks(...args);
  const normalizedQuoteText = (...args) => ai.normalizedQuoteText(...args);
  const bodyQuoteBlocks = (...args) => ai.bodyQuoteBlocks(...args);
  const chooseSourceQuoteIndex = (...args) => ai.chooseSourceQuoteIndex(...args);
  const resolveBodyQuoteTarget = (...args) => ai.resolveBodyQuoteTarget(...args);
  const jumpToBodyQuote = (...args) => ai.jumpToBodyQuote(...args);
  const createSourceQuoteCard = (...args) => ai.createSourceQuoteCard(...args);
  const sourceQuoteFromSelection = (...args) => ai.sourceQuoteFromSelection(...args);
  const removeSourceQuote = (...args) => ai.removeSourceQuote(...args);
  const setSourceQuote = (...args) => ai.setSourceQuote(...args);
  const quoteTargetLabel = (...args) => ai.quoteTargetLabel(...args);
  const availableQuoteTargets = (...args) => ai.availableQuoteTargets(...args);
  const hideBodyQuoteMenu = (...args) => ai.hideBodyQuoteMenu(...args);
  const positionBodyQuoteMenu = (...args) => ai.positionBodyQuoteMenu(...args);
  const makeBodyQuoteAction = (...args) => ai.makeBodyQuoteAction(...args);
  const appendSelectionToDocument = (...args) => ai.appendSelectionToDocument(...args);
  const showLinkedDocumentPicker = (...args) => ai.showLinkedDocumentPicker(...args);
  const showBodyQuoteMenu = (...args) => ai.showBodyQuoteMenu(...args);
  const offerBodySelectionQuote = (...args) => ai.offerBodySelectionQuote(...args);
  const _messageBubbleForSelectionNode = (...args) => ai._messageBubbleForSelectionNode(...args);
  const messageQuoteFromSelection = (...args) => ai.messageQuoteFromSelection(...args);
  const _commentQuoteAttrEscape = (...args) => ai._commentQuoteAttrEscape(...args);
  const createCommentQuoteToken = (...args) => ai.createCommentQuoteToken(...args);
  const createBodyQuoteToken = (...args) => ai.createBodyQuoteToken(...args);
  const createPersistentQuoteToken = (...args) => ai.createPersistentQuoteToken(...args);
  const pendingQuoteText = (...args) => ai.pendingQuoteText(...args);
  const _pendingBodyQuoteControl = (...args) => ai._pendingBodyQuoteControl(...args);
  const renderPendingBodyQuote = (...args) => ai.renderPendingBodyQuote(...args);
  const _insertCommentQuoteAtCursor = (...args) => ai._insertCommentQuoteAtCursor(...args);
  const insertPendingBodyQuote = (...args) => ai.insertPendingBodyQuote(...args);
  const requestBodyQuoteInsert = (...args) => ai.requestBodyQuoteInsert(...args);
  const hideMessageQuoteMenu = (...args) => ai.hideMessageQuoteMenu(...args);
  const showMessageQuoteMenu = (...args) => ai.showMessageQuoteMenu(...args);
  const offerMessageSelectionQuote = (...args) => ai.offerMessageSelectionQuote(...args);
  const markEditorCursorReady = (...args) => ai.markEditorCursorReady(...args);
  const onDetailEditModeChange = (...args) => ai.onDetailEditModeChange(...args);
  const selectionSideChatSourceQuote = (...args) => ai.selectionSideChatSourceQuote(...args);
  const stableSelectionId = (...args) => ai.stableSelectionId(...args);
  const promoteSelectionSideChat = (...args) => ai.promoteSelectionSideChat(...args);
  const createThreadActions = (...args) => ai.createThreadActions(...args);
  const createSessionExpiredNotice = (...args) => ai.createSessionExpiredNotice(...args);
  const canComment = (...args) => ai.canComment(...args);
  const canRetry = (...args) => ai.canRetry(...args);
  const scrollToThread = (...args) => ai.scrollToThread(...args);
  const syncQueueEntryDom = (...args) => ai.syncQueueEntryDom(...args);
  const createSlashMenu = (...args) => ai.createSlashMenu(...args);
  const createNoOpSlashMenu = (...args) => ai.createNoOpSlashMenu(...args);
  const getCardChatTool = (...args) => ai.getCardChatTool(...args);
  const setCardChatTool = (...args) => ai.setCardChatTool(...args);
  const resizeCardChatInput = (...args) => ai.resizeCardChatInput(...args);
  const syncCardChatToolUi = (...args) => ai.syncCardChatToolUi(...args);
  const cardChatActiveText = (...args) => ai.cardChatActiveText(...args);
  const updateCardChatState = (...args) => ai.updateCardChatState(...args);
  const syncCardChatActiveFromResults = (...args) => ai.syncCardChatActiveFromResults(...args);
  const updateCardChatEmptyState = (...args) => ai.updateCardChatEmptyState(...args);
  const scrollCardChatToBottom = (...args) => ai.scrollCardChatToBottom(...args);
  const ensureCardChatComposer = (...args) => ai.ensureCardChatComposer(...args);
  const submitCardChat = (...args) => ai.submitCardChat(...args);
  const createCommentInput = (...args) => ai.createCommentInput(...args);
  const createForkAffordance = (...args) => ai.createForkAffordance(...args);
  const resolveBranchCtx = (...args) => ai.resolveBranchCtx(...args);
  const entryDepth = (...args) => ai.entryDepth(...args);
  const buildThreadTree = (...args) => ai.buildThreadTree(...args);
  const branchMainline = (...args) => ai.branchMainline(...args);
  const hasRenderableParent = (...args) => ai.hasRenderableParent(...args);
  const isBranchExpanded = (...args) => ai.isBranchExpanded(...args);
  const setBranchCollapsed = (...args) => ai.setBranchCollapsed(...args);
  const createBranchSummary = (...args) => ai.createBranchSummary(...args);
  const createBranchNode = (...args) => ai.createBranchNode(...args);
  const createBranchGroup = (...args) => ai.createBranchGroup(...args);
  const createThreadEntryElement = (...args) => ai.createThreadEntryElement(...args);
  const createThreadCard = (...args) => ai.createThreadCard(...args);
  const loadAiHistory = (...args) => ai.loadAiHistory(...args);
  const composerHasDraft = (...args) => ai.composerHasDraft(...args);
  const scheduleIdleReconcile = (...args) => ai.scheduleIdleReconcile(...args);
  const reconcileAiHistory = (...args) => ai.reconcileAiHistory(...args);
  const updateAiButtonsState = (...args) => ai.updateAiButtonsState(...args);
  const syncCurrentTaskStatusForPath = (...args) => ai.syncCurrentTaskStatusForPath(...args);
  const syncAiButtonLoadingState = (...args) => ai.syncAiButtonLoadingState(...args);
  const setAiRunLoading = (...args) => ai.setAiRunLoading(...args);
  const runAiTool = (...args) => ai.runAiTool(...args);
  const startPolling = (...args) => ai.startPolling(...args);
  const stopPolling = (...args) => ai.stopPolling(...args);
  const killAiRun = (...args) => ai.killAiRun(...args);
  const deleteAiResult = (...args) => ai.deleteAiResult(...args);
  const copyAiResult = (...args) => ai.copyAiResult(...args);
  const submitComment = (...args) => ai.submitComment(...args);
  const getThreadEntry = (...args) => ai.getThreadEntry(...args);
  const startCommentPolling = (...args) => ai.startCommentPolling(...args);
  function taskToast(task, headerLabel) {
    const stack = ctx.el.taskToastStack;
    const el = document.createElement('div');
    el.className = 'task-toast';

    const hdr = document.createElement('div');
    hdr.className = 'tt-hdr';
    const label = document.createElement('span');
    label.className = 'tt-hdr-label';
    label.textContent = headerLabel || '新任务';
    const closeBtn = document.createElement('button');
    closeBtn.className = 'tt-close';
    closeBtn.innerHTML = '&times;';
    hdr.appendChild(label);
    hdr.appendChild(closeBtn);
    el.appendChild(hdr);

    const c = document.createElement('div');
    c.className = 'card';
    const title = document.createElement('div');
    title.className = 't';
    title.style.cursor = 'pointer';
    title.textContent = task.display_title || task.title || task.issue || task.filename;
    c.appendChild(title);
    const meta = document.createElement('div');
    meta.className = 'm';
    const pv = task.priority || 'medium';
    const pi = [['high', '高'], ['medium', '中'], ['low', '低']].find((p) => p[0] === pv);
    const pBadge = document.createElement('span');
    pBadge.className = 'b b-' + pv;
    pBadge.textContent = pi ? pi[1] : pv;
    meta.appendChild(pBadge);
    if (task.project) {
      const projB = document.createElement('span');
      projB.className = 'b b-proj';
      projB.textContent = task.project;
      meta.appendChild(projB);
    }
    if (task.assignee) {
      const whoB = document.createElement('span');
      whoB.className = 'b b-who';
      whoB.textContent = task.assignee;
      meta.appendChild(whoB);
    }
    c.appendChild(meta);
    el.appendChild(c);

    stack.appendChild(el);
    requestAnimationFrame(() => el.classList.add('on'));

    const DURATION = 60000;
    const state = { timer: null, startTime: Date.now(), remaining: DURATION };

    function dismiss() {
      clearTimeout(state.timer);
      el.classList.remove('on');
      const rm = () => { if (el.parentNode) el.remove(); };
      el.addEventListener('transitionend', rm, { once: true });
      setTimeout(rm, 500);
    }

    function startTimer() {
      clearTimeout(state.timer);
      state.timer = setTimeout(dismiss, state.remaining);
      state.startTime = Date.now();
    }

    startTimer();
    closeBtn.onclick = dismiss;
    title.onclick = () => { dismiss(); ctx.renderDetail.openTaskDetail(task.path); };

    el.addEventListener('mouseenter', () => {
      clearTimeout(state.timer);
      state.remaining -= (Date.now() - state.startTime);
      if (state.remaining < 0) state.remaining = 0;
    });
    el.addEventListener('mouseleave', () => {
      if (state.remaining <= 0) {
        dismiss();
        return;
      }
      startTimer();
    });
  }

  function _hasActiveEntries() {
    const entries = (uiState.queue.data && uiState.queue.data.entries) || [];
    return entries.some(e => ACTIVE_RUN_STATUSES.has(e.status));
  }

  function _adjustBadgePolling() {
    if (_hasActiveEntries()) {
      uiState.queue.consecutiveIdle = 0;
    } else {
      uiState.queue.consecutiveIdle = (uiState.queue.consecutiveIdle || 0) + 1;
    }
    if (uiState.queue.consecutiveIdle >= 2 && uiState.queue.badgeTimer) {
      clearInterval(uiState.queue.badgeTimer);
      uiState.queue.badgeTimer = null;
    }
  }

  function fetchQueue() {
    if (!ctx.hasApi || !uiState.auth.sessionValid) return Promise.resolve();
    return fetch('/api/queue')
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) return;
        uiState.queue.data = data.queue;
        renderQueueSidebar();
        updateQueueBadge();
        _adjustBadgePolling();
      })
      .catch(() => {});
  }

  function updateQueueBadge() {
    if (!uiState.queue.data) return;
    const livePaths = new Set((dataState.tasks || []).map((t) => t.path));
    const donePaths = new Set((dataState.tasks || []).filter((t) => t.status === 'done').map((t) => t.path));
    const hasUnread = uiState.queue.data.entries.some((e) =>
      !isTransientSelectionEntry(e)
      &&
      (livePaths.has(e.path) || qIsSystemEntry(e))
      && (!donePaths.has(e.path) || qIsSystemEntry(e))
      && TERMINAL_RUN_STATUSES.has(e.status)
      && !e.read
    );
    if (queueBadge) queueBadge.classList.toggle('on', hasUnread);
    if (detailQueueBadge) detailQueueBadge.classList.toggle('on', hasUnread);
  }

  function activateQueueTab(tabName) {
    const target = ['processed', 'running', 'queued'].includes(tabName) ? tabName : uiState.queue.activeTab;
    if (target) uiState.queue.activeTab = target;
    document.querySelectorAll('.queue-tab').forEach((tab) => {
      tab.classList.toggle('on', tab.dataset.tab === uiState.queue.activeTab);
    });
    document.querySelectorAll('.queue-tab-content').forEach((content) => {
      content.classList.toggle('on', content.id === 'queue-tab-' + uiState.queue.activeTab);
    });
  }

  function openQueueSidebar(tabName) {
    queueOverlay.classList.add('on');
    queueSidebar.classList.add('on');
    if (isMobile()) document.body.style.overflow = 'hidden';
    if (tabName) activateQueueTab(tabName);
    fetchQueue();
    if (!uiState.queue.pollTimer) uiState.queue.pollTimer = setInterval(fetchQueue, 10000);
  }

  function closeQueueSidebar() {
    queueOverlay.classList.remove('on');
    queueSidebar.classList.remove('on');
    document.body.style.overflow = '';
    if (uiState.queue.pollTimer) {
      clearInterval(uiState.queue.pollTimer);
      uiState.queue.pollTimer = null;
    }
  }

  function startQueueBadgePolling() {
    if (!ctx.hasApi || uiState.queue.badgeTimer) return;
    uiState.queue.consecutiveIdle = 0;
    fetchQueue().then(() => {
      if (_hasActiveEntries() && !uiState.queue.badgeTimer) {
        uiState.queue.badgeTimer = setInterval(fetchQueue, 10000);
      }
    });
  }

  function resumeQueueBadgePolling() {
    if (!ctx.hasApi) return;
    uiState.queue.consecutiveIdle = 0;
    if (!uiState.queue.badgeTimer) {
      fetchQueue();
      uiState.queue.badgeTimer = setInterval(fetchQueue, 10000);
    }
  }

  function qTaskTitle(path) {
    if (!path) return 'AI 对话';
    const safePath = String(path);
    const task = (dataState.tasks || []).find((t) => t.path === safePath);
    return task ? (task.task_id ? '[' + task.task_id + '] ' : '') + task.title : safePath.split('/').pop().replace('.md', '');
  }

  function qThreadTitle(entry) {
    if (qIsSystemEntry(entry)) {
      const title = entry.title || '';
      return title ? qSystemTitle(entry) + ' · ' + title : qSystemTitle(entry);
    }
    const base = qTaskTitle(entry.path);
    const title = entry.title || '';
    return title ? base + ' · ' + title : base;
  }

  function qCommentCount(entry) {
    const messages = entry.messages || [];
    return messages.filter((m) => m && m.role === 'user').length;
  }

  function qLatestSnippet(entry) {
    const messages = entry.messages || [];
    const last = messages.length ? messages[messages.length - 1] : null;
    const prefix = last ? ((last.role === 'user' ? (last.author || '用户') : 'AI') + ': ') : '';
    const text = last && last.content ? String(last.content).trim().replace(/\s+/g, ' ') : (entry.error || entry.output || '');
    return (prefix + text).slice(0, 80);
  }

  function qFormatTime(entry) {
    if ((entry.status === 'running' || entry.status === 'orphaned-running') && entry.elapsed_ms) return (entry.elapsed_ms / 1000).toFixed(0) + 's';
    if (entry.duration_ms) {
      const s = entry.duration_ms / 1000;
      return s >= 60 ? Math.floor(s / 60) + 'm' + Math.floor(s % 60) + 's' : s.toFixed(1) + 's';
    }
    if (entry.timestamp) return entry.timestamp.replace('T', ' ').slice(5, 16);
    return '';
  }

  function qMakeToolBadge(tool) {
    const span = document.createElement('span');
    span.className = 'qcard-tool ' + (tool === 'claude' ? 'qcard-tool-claude' : 'qcard-tool-codex');
    span.textContent = tool === 'claude' ? 'Claude' : 'Codex';
    return span;
  }

  function qMakeStatusDot(status) {
    const span = document.createElement('span');
    const s = (status === 'timeout' || status === 'killed' || status === 'orphaned-unknown') ? 'error' : status;
    span.className = 'qcard-status qcard-status-' + s;
    return span;
  }

  function qMakeTimeEl(text) {
    const span = document.createElement('span');
    span.className = 'qcard-time';
    span.textContent = text;
    return span;
  }

  function qEmptyMsg(container, msg) {
    container.textContent = '';
    const d = document.createElement('div');
    d.className = 'qcard-empty';
    d.textContent = msg;
    container.appendChild(d);
  }

  function qIsSystemEntry(entry) {
    return !!(entry && entry.metadata && entry.metadata.kind);
  }

  function qSystemTitle(entry) {
    const metadata = entry && entry.metadata;
    const label = metadata && metadata.label;
    if (label) return String(label);
    const kind = metadata && metadata.kind;
    if (kind === 'governance_noise_review') return '治理自检';
    return '系统任务';
  }

  function qSystemOutput(entry) {
    const messages = (entry && entry.messages) || [];
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const msg = messages[i];
      if (msg && msg.role === 'ai' && msg.content) return String(msg.content);
    }
    return String((entry && (entry.output || entry.error)) || '');
  }

  function qMarkRead(entry, refresh = true) {
    if (!entry || entry.read) return Promise.resolve();
    return fetch('/api/queue/mark-read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: entry.id }),
    }).then(() => {
      entry.read = true;
      if (refresh) return fetchQueue();
      updateQueueBadge();
      return null;
    });
  }

  function qToggleSystemOutput(card, entry) {
    const existing = card.querySelector('.qcard-full');
    if (existing) {
      existing.remove();
      return;
    }
    const content = qSystemOutput(entry);
    if (!content) {
      toast('自检还没有输出');
      return;
    }
    const full = document.createElement('div');
    full.className = 'qcard-full';
    if (markdown && markdown.looksLikeMarkdown(content)) {
      markdown.renderMarkdownEnhanced(full, content, entry.path || '');
    } else {
      full.textContent = content;
    }
    card.appendChild(full);
  }

  function renderProcessedTab(entries) {
    const container = queueTabProcessed;
    container.textContent = '';
    if (!entries.length) {
      qEmptyMsg(container, '暂无已处理任务');
      return;
    }
    const sorted = [...entries].sort((a, b) => (a.read === b.read ? 0 : a.read ? 1 : -1));
    sorted.forEach((entry) => {
      const card = document.createElement('div');
      card.className = 'qcard' + (entry.read ? '' : ' qcard-unread');
      const title = document.createElement('div');
      title.className = 'qcard-title';
      title.textContent = qThreadTitle(entry);
      card.appendChild(title);
      const meta = document.createElement('div');
      meta.className = 'qcard-meta';
      meta.appendChild(qMakeToolBadge(entry.tool));
      meta.appendChild(qMakeStatusDot(entry.status));
      meta.appendChild(qMakeTimeEl(qFormatTime(entry)));
      if (qCommentCount(entry)) meta.appendChild(qMakeTimeEl('评论 ' + qCommentCount(entry)));
      card.appendChild(meta);
      const snippet = qLatestSnippet(entry);
      if (snippet) {
        const err = document.createElement('div');
        err.className = 'qcard-error';
        err.textContent = snippet;
        card.appendChild(err);
      }
      card.onclick = () => {
        if (qIsSystemEntry(entry)) {
          qToggleSystemOutput(card, entry);
          qMarkRead(entry, false).then(() => card.classList.remove('qcard-unread')).catch(() => {});
          return;
        }
        if (!entry.read) qMarkRead(entry);
        ctx.renderDetail.openTaskDetail(entry.path);
      };
      if (entry.tool === 'claude' && (entry.status === 'killed' || entry.status === 'error')) {
        const retryBtn = document.createElement('button');
        retryBtn.className = 'qcard-action-btn';
        retryBtn.textContent = '继续';
        retryBtn.onclick = (e) => {
          e.stopPropagation();
          closeQueueSidebar();
          Promise.resolve(ctx.renderDetail.openTaskDetail(entry.path))
            .then(() => loadAiHistory(entry.path))
            .then(() => scrollToThread(entry.id));
        };
        const actions = document.createElement('div');
        actions.className = 'qcard-actions';
        actions.appendChild(retryBtn);
        card.appendChild(actions);
      }
      container.appendChild(card);
    });
  }

  function renderRunningTab(entries) {
    const container = queueTabRunning;
    container.textContent = '';
    if (!entries.length) {
      qEmptyMsg(container, '暂无运行中任务');
      return;
    }
    entries.forEach((entry) => {
      const card = document.createElement('div');
      card.className = 'qcard';
      const title = document.createElement('div');
      title.className = 'qcard-title';
      title.textContent = qThreadTitle(entry);
      card.appendChild(title);
      const meta = document.createElement('div');
      meta.className = 'qcard-meta';
      const spinner = document.createElement('span');
      spinner.className = entry.status === 'orphaned-running' ? 'qcard-status qcard-status-orphaned-running' : 'qcard-spinner';
      meta.appendChild(spinner);
      meta.appendChild(qMakeToolBadge(entry.tool));
      if (entry.status === 'orphaned-running') meta.appendChild(qMakeTimeEl('孤儿进程 · 输出已断'));
      meta.appendChild(qMakeTimeEl(qFormatTime(entry)));
      card.appendChild(meta);
      if (entry.status === 'running') {
        const actions = document.createElement('div');
        actions.className = 'qcard-actions';
        const killBtn = document.createElement('button');
        killBtn.className = 'qcard-action-btn danger';
        killBtn.textContent = '终止';
        killBtn.onclick = (e) => { e.stopPropagation(); killAiRun(entry.id); fetchQueue(); };
        actions.appendChild(killBtn);
        card.appendChild(actions);
      }
      card.onclick = () => {
        if (!qIsSystemEntry(entry)) ctx.renderDetail.openTaskDetail(entry.path);
      };
      container.appendChild(card);
    });
  }

  function renderQueuedTab(entries) {
    const container = queueTabQueued;
    container.textContent = '';
    if (!entries.length) {
      qEmptyMsg(container, '队列为空');
      return;
    }
    entries.forEach((entry, idx) => {
      const card = document.createElement('div');
      card.className = 'qcard';
      card.draggable = !isMobile();
      card.dataset.entryId = entry.id;
      const title = document.createElement('div');
      title.className = 'qcard-title';
      title.textContent = qThreadTitle(entry);
      card.appendChild(title);
      const meta = document.createElement('div');
      meta.className = 'qcard-meta';
      meta.appendChild(qMakeToolBadge(entry.tool));
      meta.appendChild(qMakeStatusDot('queued'));
      meta.appendChild(qMakeTimeEl('#' + (idx + 1)));
      card.appendChild(meta);
      const actions = document.createElement('div');
      actions.className = 'qcard-actions';
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'qcard-action-btn danger';
      cancelBtn.textContent = '取消';
      cancelBtn.onclick = (e) => {
        e.stopPropagation();
        fetch('/api/queue/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: entry.id }),
        }).then((r) => r.json()).then((data) => {
          if (data.ok) fetchQueue();
          else toast(data.error || '取消失败', true);
        });
      };
      actions.appendChild(cancelBtn);
      card.appendChild(actions);
      card.onclick = () => {
        if (!qIsSystemEntry(entry)) ctx.renderDetail.openTaskDetail(entry.path);
      };

      if (!isMobile()) {
        card.addEventListener('dragstart', (e) => {
          e.dataTransfer.setData('text/plain', entry.id);
          e.dataTransfer.effectAllowed = 'move';
          setTimeout(() => card.classList.add('qcard-dragging'), 0);
        });
        card.addEventListener('dragend', () => card.classList.remove('qcard-dragging'));
        card.addEventListener('dragover', (e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          card.style.borderTopColor = 'var(--accent)';
        });
        card.addEventListener('dragleave', () => { card.style.borderTopColor = ''; });
        card.addEventListener('drop', (e) => {
          e.preventDefault();
          card.style.borderTopColor = '';
          const draggedId = e.dataTransfer.getData('text/plain');
          const targetId = entry.id;
          if (draggedId === targetId) return;
          const ids = entries.map((en) => en.id);
          const dragIdx = ids.indexOf(draggedId);
          if (dragIdx !== -1) ids.splice(dragIdx, 1);
          const newTargetIdx = ids.indexOf(targetId);
          ids.splice(newTargetIdx, 0, draggedId);
          fetch('/api/queue/reorder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order: ids }),
          }).then(() => fetchQueue());
        });
      }

      container.appendChild(card);
    });
  }

  function renderQueueSidebar() {
    if (!uiState.queue.data) return;
    const entries = uiState.queue.data.entries || [];
    const livePaths = new Set((dataState.tasks || []).map((t) => t.path));
    const donePaths = new Set((dataState.tasks || []).filter((t) => t.status === 'done').map((t) => t.path));
    const taskAssigneeMap = {};
    (dataState.tasks || []).forEach((t) => { taskAssigneeMap[t.path] = t.assignee; });
    const visibleEntry = (e) => !isTransientSelectionEntry(e) && (livePaths.has(e.path) || qIsSystemEntry(e));
    const activeEntry = (e) => !donePaths.has(e.path) || qIsSystemEntry(e);
    const mineFilter = (e) => !uiState.filters.mine || !uiState.auth.currentUser || qIsSystemEntry(e) || taskAssigneeMap[e.path] === uiState.auth.currentUser;

    const processed = entries.filter((e) =>
      visibleEntry(e)
      && activeEntry(e)
      && TERMINAL_RUN_STATUSES.has(e.status)
      && mineFilter(e)
    );
    const running = entries.filter((e) => (e.status === 'running' || e.status === 'orphaned-running') && visibleEntry(e));
    const queued = entries
      .filter((e) => e.status === 'queued' && visibleEntry(e) && mineFilter(e))
      .sort((a, b) => (a.order || 0) - (b.order || 0));

    processedBadge.classList.toggle('on', processed.some((e) => !e.read));
    runningCount.textContent = running.length ? running.length : '';
    queuedCount.textContent = queued.length ? queued.length : '';

    renderProcessedTab(processed);
    renderRunningTab(running);
    renderQueuedTab(queued);
  }

  function resetDetailActivity() {
    Object.values(uiState.ai.pollTimers).forEach((timer) => clearInterval(timer));
    uiState.ai.pollTimers = {};
    uiState.ai.cachedSkills = null;
    uiState.ai.cardChatSubmitting = false;
    uiState.ai.cardChatActiveRunId = '';
    uiState.ai.cardChatActiveStatus = '';
    uiState.ai.threadTree = null;
    if (uiState.ai.reconcileTimer) clearTimeout(uiState.ai.reconcileTimer);
    uiState.ai.reconcileTimer = null;
    hideBodyQuoteMenu();
    hideMessageQuoteMenu();
    if (aiState.selectionExplainRunId || (aiState.selectionExplainPopover && !aiState.selectionExplainPopover.hidden)) {
      discardSelectionExplanation();
    }
    aiState.pendingBodyQuote = null;
    aiState.editorCursorReady = false;
    renderPendingBodyQuote();
    rememberAiResults([], false);
    aiActivity.style.display = 'none';
    aiActivityList.textContent = '';
    if (aiState.cardChat) {
      aiState.cardChat.textarea.value = '';
      resizeCardChatInput();
      updateCardChatEmptyState(false);
      updateCardChatState();
    }
    if (detailClaudeBtn) detailClaudeBtn.classList.remove('loading');
    if (detailCodexBtn) detailCodexBtn.classList.remove('loading');
  }

  function bindEvents() {
    if (detailClaudeBtn) detailClaudeBtn.onclick = () => runAiTool('claude', { profile: profileKey('execute', 'claude') });
    if (detailCodexBtn) detailCodexBtn.onclick = () => runAiTool('codex', { profile: profileKey('execute', 'codex') });
    btnQueue.onclick = openQueueSidebar;
    queueCloseBtn.onclick = closeQueueSidebar;
    queueOverlay.onclick = closeQueueSidebar;
    document.querySelectorAll('.queue-tab').forEach((tab) => {
      tab.onclick = () => {
        uiState.queue.activeTab = tab.dataset.tab;
        activateQueueTab(uiState.queue.activeTab);
      };
    });
    if (ctx.el.detailMdContent) {
      ctx.el.detailMdContent.addEventListener('mouseup', () => setTimeout(offerBodySelectionQuote, 0));
      ctx.el.detailMdContent.addEventListener('keyup', () => setTimeout(offerBodySelectionQuote, 0));
      ctx.el.detailMdContent.addEventListener('touchend', () => setTimeout(offerBodySelectionQuote, 0));
    }
    if (aiActivity) {
      aiActivity.addEventListener('mouseup', () => setTimeout(offerMessageSelectionQuote, 0));
      aiActivity.addEventListener('keyup', () => setTimeout(offerMessageSelectionQuote, 0));
      aiActivity.addEventListener('touchend', () => setTimeout(offerMessageSelectionQuote, 0));
    }
    if (ctx.el.detailEditor) {
      ctx.el.detailEditor.addEventListener('pointerup', markEditorCursorReady);
      ctx.el.detailEditor.addEventListener('keyup', markEditorCursorReady);
      ctx.el.detailEditor.addEventListener('select', markEditorCursorReady);
    }
    document.addEventListener('mousedown', (event) => {
      if (aiState.bodyQuoteMenu && !aiState.bodyQuoteMenu.hidden && !aiState.bodyQuoteMenu.contains(event.target)
        && !(ctx.el.detailMdContent && ctx.el.detailMdContent.contains(event.target))) {
        hideBodyQuoteMenu();
      }
      if (aiState.messageQuoteMenu && !aiState.messageQuoteMenu.hidden && !aiState.messageQuoteMenu.contains(event.target)
        && !(aiActivity && aiActivity.contains(event.target))) {
        hideMessageQuoteMenu();
      }
    });
  }

  async function startAiRunForTask(taskPath, tool) {
    try {
      const aiRes = await fetch('/api/ai-run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          path: taskPath,
          tool,
          profile: profileKey('execute', tool),
          create_workdir: true,
        })
      });
      const aiData = await aiRes.json();
      if (aiData.ok) { resumeQueueBadgePolling(); return { ok: true }; }
      return { ok: false, error: '任务已创建，但 AI 启动失败: ' + (aiData.error || '未知错误') };
    } catch (e) {
      return { ok: false, error: '任务已创建，但 AI 启动失败: 网络错误' };
    }
  }

  Object.assign(ai, { taskToast, _hasActiveEntries, _adjustBadgePolling, fetchQueue, updateQueueBadge, activateQueueTab, openQueueSidebar, closeQueueSidebar, startQueueBadgePolling, resumeQueueBadgePolling, qTaskTitle, qThreadTitle, qCommentCount, qLatestSnippet, qFormatTime, qMakeToolBadge, qMakeStatusDot, qMakeTimeEl, qEmptyMsg, qIsSystemEntry, qSystemTitle, qSystemOutput, qMarkRead, qToggleSystemOutput, renderProcessedTab, renderRunningTab, renderQueuedTab, renderQueueSidebar, resetDetailActivity, bindEvents, startAiRunForTask });

  ctx.ai = {
    fetchSkills,
    createMessageBubble,
    createThreadCard,
    loadAiHistory,
    updateAiButtonsState,
    syncCurrentTaskStatusForPath,
    runAiTool,
    startPolling,
    stopPolling,
    killAiRun,
    deleteAiResult,
    copyAiResult,
    submitComment,
    getThreadEntry,
    taskToast,
    fetchQueue,
    updateQueueBadge,
    openQueueSidebar,
    closeQueueSidebar,
    startQueueBadgePolling,
    renderQueueSidebar,
    resetDetailActivity,
    bindEvents,
    onDetailEditModeChange,
    startAiRunForTask,
    resolveBodyQuoteTarget,
    jumpToBodyQuote,
    qTaskTitle,
    qThreadTitle,
    qCommentCount,
    qLatestSnippet,
    qFormatTime,
    syncQueueEntryDom,
    _test: {
      buildThreadTree,
      branchMainline,
      hasRenderableParent,
      normalizedQuoteText,
      isTransientSelectionEntry,
      durableDialogueResults,
      selectionQuickPrompt,
      profileKey,
      profileLabel,
      stableSelectionId,
      selectionSideChatSourceQuote,
      chooseSourceQuoteIndex,
      sourceQuoteFromSelection,
      messageAuthorLabel,
      messageQuoteFromSelection,
      createCommentQuoteToken,
      createBodyQuoteToken,
      markEditorCursorReady,
      insertCommentQuoteAtCursor: _insertCommentQuoteAtCursor,
      requestBodyQuoteInsert,
    },
  };

  return ctx.ai;
}
