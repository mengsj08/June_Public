// KAN-1671: mounted by main.js; dependencies arrive through ctx.aiInternal.
export function setupAiThreads(ctx) {
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
  const taskToast = (...args) => ai.taskToast(...args);
  const _hasActiveEntries = (...args) => ai._hasActiveEntries(...args);
  const _adjustBadgePolling = (...args) => ai._adjustBadgePolling(...args);
  const fetchQueue = (...args) => ai.fetchQueue(...args);
  const updateQueueBadge = (...args) => ai.updateQueueBadge(...args);
  const activateQueueTab = (...args) => ai.activateQueueTab(...args);
  const openQueueSidebar = (...args) => ai.openQueueSidebar(...args);
  const closeQueueSidebar = (...args) => ai.closeQueueSidebar(...args);
  const startQueueBadgePolling = (...args) => ai.startQueueBadgePolling(...args);
  const resumeQueueBadgePolling = (...args) => ai.resumeQueueBadgePolling(...args);
  const qTaskTitle = (...args) => ai.qTaskTitle(...args);
  const qThreadTitle = (...args) => ai.qThreadTitle(...args);
  const qCommentCount = (...args) => ai.qCommentCount(...args);
  const qLatestSnippet = (...args) => ai.qLatestSnippet(...args);
  const qFormatTime = (...args) => ai.qFormatTime(...args);
  const qMakeToolBadge = (...args) => ai.qMakeToolBadge(...args);
  const qMakeStatusDot = (...args) => ai.qMakeStatusDot(...args);
  const qMakeTimeEl = (...args) => ai.qMakeTimeEl(...args);
  const qEmptyMsg = (...args) => ai.qEmptyMsg(...args);
  const qIsSystemEntry = (...args) => ai.qIsSystemEntry(...args);
  const qSystemTitle = (...args) => ai.qSystemTitle(...args);
  const qSystemOutput = (...args) => ai.qSystemOutput(...args);
  const qMarkRead = (...args) => ai.qMarkRead(...args);
  const qToggleSystemOutput = (...args) => ai.qToggleSystemOutput(...args);
  const renderProcessedTab = (...args) => ai.renderProcessedTab(...args);
  const renderRunningTab = (...args) => ai.renderRunningTab(...args);
  const renderQueuedTab = (...args) => ai.renderQueuedTab(...args);
  const renderQueueSidebar = (...args) => ai.renderQueueSidebar(...args);
  const resetDetailActivity = (...args) => ai.resetDetailActivity(...args);
  const bindEvents = (...args) => ai.bindEvents(...args);
  const startAiRunForTask = (...args) => ai.startAiRunForTask(...args);
  function ensureCardChatComposer() {
    aiActivity.classList.add('card-chat-shell');
    const title = aiActivity.querySelector('.ai-activity-title');
    if (title) title.textContent = '对话';
    if (aiState.cardChat) {
      syncCardChatToolUi();
      updateCardChatState();
      return aiState.cardChat;
    }

    const empty = document.createElement('div');
    empty.className = 'card-chat-empty';
    empty.textContent = '还没有对话。';
    aiActivity.insertBefore(empty, aiActivityList);

    const status = document.createElement('div');
    status.className = 'card-chat-status';
    status.setAttribute('aria-live', 'polite');

    const composer = document.createElement('div');
    composer.className = 'card-chat-composer';

    const box = document.createElement('div');
    box.className = 'card-chat-box';

    const toolSwitch = document.createElement('div');
    toolSwitch.className = 'card-chat-tool-switch';
    toolSwitch.setAttribute('role', 'group');
    toolSwitch.setAttribute('aria-label', '选择 AI 工具');
    const toolButtons = ['claude', 'codex'].map((tool) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'card-chat-tool-btn';
      btn.dataset.tool = tool;
      btn.textContent = toolLabel(tool);
      btn.title = profileLabel(profileKey('deep', tool), toolLabel(tool));
      btn.addEventListener('click', () => setCardChatTool(tool));
      toolSwitch.appendChild(btn);
      return btn;
    });

    const textarea = document.createElement('textarea');
    textarea.className = 'card-chat-input';
    textarea.rows = 1;
    textarea.spellcheck = false;
    textarea.title = 'Enter 发送，Shift+Enter 换行';

    const sendBtn = document.createElement('button');
    sendBtn.type = 'button';
    sendBtn.className = 'card-chat-send';
    sendBtn.title = '发送';
    sendBtn.innerHTML = '<i data-lucide="send-horizontal"></i><span>发送</span>';
    textarea.addEventListener('input', () => {
      resizeCardChatInput();
      updateCardChatState();
    });
    textarea.addEventListener('input', markdown._fmHandleInput);
    textarea.addEventListener('keydown', markdown._fmHandleKeydown, true);
    textarea.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitCardChat();
      }
    });
    textarea.addEventListener('blur', () => setTimeout(() => { if (uiState.fileMention.visible) markdown._fmHide(); }, 200));
    sendBtn.addEventListener('click', submitCardChat);

    box.appendChild(toolSwitch);
    box.appendChild(textarea);
    box.appendChild(sendBtn);
    composer.appendChild(box);
    aiActivity.appendChild(status);
    aiActivity.appendChild(composer);

    aiState.cardChat = { empty, status, composer, textarea, sendBtn, toolButtons };
    syncCardChatToolUi();
    resizeCardChatInput();
    updateCardChatState();
    if (typeof lucide !== 'undefined') requestAnimationFrame(() => lucide.createIcons());
    return aiState.cardChat;
  }

  function submitCardChat() {
    ensureCardChatComposer();
    if (!aiState.cardChat || aiState.cardChat.sendBtn.disabled) return;
    const message = aiState.cardChat.textarea.value.trim();
    if (!message) return;
    const rawValue = aiState.cardChat.textarea.value;
    const sourceQuote = pendingSourceQuotes.get(aiState.cardChat.textarea) || null;
    const tool = getCardChatTool();
    runAiTool(tool, {
      source: 'card_chat',
      profile: profileKey('deep', tool),
      prompt: message,
      displayMessage: message,
      sourceQuote,
      origin: sourceQuote ? 'selection_side_chat' : 'card_chat',
      onQueued: () => {
        aiState.cardChat.textarea.value = '';
        removeSourceQuote(aiState.cardChat.textarea);
        resizeCardChatInput();
        updateCardChatState();
      },
    }).then((data) => {
      if (!data || data.ok) return;
      aiState.cardChat.textarea.value = rawValue;
      resizeCardChatInput();
      updateCardChatState();
    });
  }

  function createCommentInput(entry, mode) {
    const isRetry = mode === 'retry';
    const idleLabel = isRetry ? '继续' : '发送';
    const wrap = document.createElement('div');
    wrap.className = 'comment-input-wrapper';
    const textarea = document.createElement('textarea');
    textarea.className = 'comment-input';
    textarea.placeholder = isRetry ? '继续会话...' : '输入评论继续对话...';
    textarea.rows = 1;
    const sendBtn = document.createElement('button');
    sendBtn.className = 'comment-send-btn';
    sendBtn.textContent = idleLabel;
    sendBtn.dataset.idleLabel = idleLabel;
    sendBtn.disabled = true;
    const slashMenu = entry.tool === 'codex' ? createNoOpSlashMenu() : createSlashMenu(textarea, wrap);

    const update = () => {
      sendBtn.disabled = !textarea.value.trim();
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
      slashMenu.syncSelectedFromText();
      const query = slashMenu.getFilterQuery();
      if (query !== null) {
        slashMenu.open(query);
      } else {
        slashMenu.close();
        slashMenu.syncManualSkillFromText();
      }
    };

    textarea.addEventListener('input', update);
    textarea.addEventListener('input', markdown._fmHandleInput);
    textarea.addEventListener('keydown', markdown._fmHandleKeydown, true);
    textarea.addEventListener('keydown', (e) => {
      if (slashMenu.isOpen()) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          slashMenu.moveActive(1);
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          slashMenu.moveActive(-1);
          return;
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          slashMenu.confirmActive();
          return;
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          slashMenu.close();
          return;
        }
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (textarea.value.trim()) submitComment(entry.run_id, textarea.value.trim(), wrap, slashMenu.getSelectedSkill()?.id, slashMenu);
      }
    });
    textarea.addEventListener('blur', () => setTimeout(() => slashMenu.close(), 150));
    textarea.addEventListener('blur', () => setTimeout(() => { if (uiState.fileMention.visible) markdown._fmHide(); }, 200));
    sendBtn.addEventListener('click', () => {
      if (textarea.value.trim()) submitComment(entry.run_id, textarea.value.trim(), wrap, slashMenu.getSelectedSkill()?.id, slashMenu);
    });

    wrap.appendChild(textarea);
    wrap.appendChild(sendBtn);
    return wrap;
  }

  // 评论分支(KAN-111):在某条 AI 消息下开分叉输入,提交 fork_from_index 产生新支线
  function createForkAffordance(entry, msgIdx) {
    const row = document.createElement('div');
    row.className = 'msg-fork-row';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'msg-fork-btn';
    btn.textContent = '⑂ 从此分叉';
    btn.title = '以这条消息为分叉点,开一条新支线(原支线不受影响)';
    row.appendChild(btn);
    btn.addEventListener('click', () => {
      const existing = row.querySelector('.fork-input-wrap');
      if (existing) { existing.remove(); return; }
      const wrap = document.createElement('div');
      wrap.className = 'fork-input-wrap';
      const textarea = document.createElement('textarea');
      textarea.className = 'comment-input fork-input';
      textarea.rows = 2;
      textarea.placeholder = `分叉自第 ${msgIdx} 条 · 新支线的第一条指令(Enter 发送)`;
      const send = document.createElement('button');
      send.type = 'button';
      send.className = 'comment-send-btn';
      send.textContent = '开支线';
      const doFork = () => {
        const comment = textarea.value.trim();
        if (!comment) return;
        const sourceQuote = pendingSourceQuotes.get(textarea) || null;
        send.disabled = true;
        textarea.disabled = true;
        fetch('/api/ai-comment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            run_id: entry.run_id,
            comment,
            author: uiState.auth.currentUser,
            fork_from_index: msgIdx,
            source_quote: sourceQuote,
          }),
        })
          .then((r) => r.json())
          .then((data) => {
            if (!data.ok) throw new Error(data.error || '分叉失败');
            wrap.remove();
            if (uiState.detail.currentTaskPath) loadAiHistory(uiState.detail.currentTaskPath);
          })
          .catch((e) => {
            send.disabled = false;
            textarea.disabled = false;
            textarea.placeholder = String(e.message || e);
          });
      };
      textarea.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); doFork(); }
      });
      send.addEventListener('click', doFork);
      wrap.appendChild(textarea);
      wrap.appendChild(send);
      row.appendChild(wrap);
      textarea.focus();
    });
    return row;
  }

  // ---- KAN-213 树状渲染辅助 ----
  // 树上下文: { childrenOf: Map<parent_run_id, Map<parent_index, [entry]>>, byRunId, depth }
  // 主线=无 metadata.fork; 分支=有 fork.parent_run_id 指向父 run_id、fork.parent_index 指向父消息序号
  const BRANCH_COLLAPSE_KEY = 'kanban.thread.collapsed.';
  function resolveBranchCtx() {
    const tree = uiState.ai.threadTree;
    if (!tree) return { childrenOf: new Map(), byRunId: new Map(), depth: 0 };
    return { childrenOf: tree.childrenOf, byRunId: tree.byRunId, depth: 0 };
  }
  function entryDepth(entry) {
    const fork = entry && entry.metadata && entry.metadata.fork;
    if (!fork || !fork.parent_run_id) return 0;
    const tree = uiState.ai.threadTree;
    if (!tree || !tree.byRunId) return 1;
    // 通过向上追溯父链来确定深度
    let depth = 1;
    let cur = tree.byRunId.get(fork.parent_run_id);
    let guard = 0;
    while (cur && (cur.metadata && cur.metadata.fork && cur.metadata.fork.parent_run_id) && guard < 100) {
      depth += 1;
      cur = tree.byRunId.get(cur.metadata.fork.parent_run_id);
      guard += 1;
    }
    return depth;
  }

  function buildThreadTree(results) {
    const byRunId = new Map();
    const childrenOf = new Map();
    results.forEach((entry) => {
      if (!entry || !entry.run_id) return;
      byRunId.set(entry.run_id, entry);
      const fork = entry.metadata && entry.metadata.fork;
      if (fork && fork.parent_run_id) {
        if (!childrenOf.has(fork.parent_run_id)) childrenOf.set(fork.parent_run_id, new Map());
        const idxMap = childrenOf.get(fork.parent_run_id);
        const idxKey = String(fork.parent_index != null ? fork.parent_index : -1);
        if (!idxMap.has(idxKey)) idxMap.set(idxKey, []);
        idxMap.get(idxKey).push(entry);
      }
    });
    return { byRunId, childrenOf };
  }

  function branchMainline(results, byRunId) {
    return results.filter((e) => {
      const parentRunId = e && e.metadata && e.metadata.fork && e.metadata.fork.parent_run_id;
      return !parentRunId || !byRunId || !byRunId.has(parentRunId);
    })
      .sort((a, b) => String(a.timestamp || '').localeCompare(String(b.timestamp || '')));
  }

  function hasRenderableParent(entry, branchCtx) {
    const parentRunId = entry && entry.metadata && entry.metadata.fork && entry.metadata.fork.parent_run_id;
    return Boolean(parentRunId && branchCtx && branchCtx.byRunId && branchCtx.byRunId.has(parentRunId));
  }

  function isBranchExpanded(runId, entry, isMainline) {
    if (isMainline) return true;
    if (entry && ACTIVE_RUN_STATUSES.has(entry.status)) return true;
    try {
      const v = localStorage.getItem(BRANCH_COLLAPSE_KEY + runId);
      if (v === '1') return false;
      if (v === '0') return true;
    } catch (e) {}
    return false; // 默认折叠
  }

  function setBranchCollapsed(runId, collapse) {
    try { localStorage.setItem(BRANCH_COLLAPSE_KEY + runId, collapse ? '1' : '0'); } catch (e) {}
  }

  function createBranchSummary(entry) {
    const row = document.createElement('div');
    row.className = 'thread-branch-summary';
    const tool = document.createElement('span');
    tool.className = 'thread-branch-tool ' + (entry.tool === 'claude' ? 'thread-claude' : 'thread-codex');
    tool.textContent = entry.tool === 'claude' ? 'Claude' : 'Codex';
    row.appendChild(tool);
    const msgs = entry.messages || [];
    let firstSentence = '';
    for (const m of msgs) {
      if (m.role !== 'user') continue;
      const t = String(m.content || '').trim();
      if (t) { firstSentence = t.replace(/\s+/g, ' ').slice(0, 80); break; }
    }
    if (!firstSentence) firstSentence = String(entry.output || entry.error || '').replace(/\s+/g, ' ').slice(0, 80);
    const text = document.createElement('span');
    text.className = 'thread-branch-text';
    text.textContent = firstSentence + (firstSentence.length >= 80 ? '…' : '');
    row.appendChild(text);
    const status = document.createElement('span');
    status.className = 'thread-branch-status status-' + String(entry.status || 'completed');
    status.textContent = entry.status === 'running' ? '处理中'
      : entry.status === 'queued' ? '排队中'
      : entry.status === 'orphaned-running' ? '孤儿进程仍在运行'
      : entry.status === 'orphaned-unknown' ? '孤儿结果未知'
      : entry.status === 'error' ? '失败'
      : entry.status === 'timeout' ? '已超时'
      : entry.status === 'killed' ? '已终止'
      : '已完成';
    row.appendChild(status);
    const cnt = document.createElement('span');
    cnt.className = 'thread-branch-count';
    cnt.textContent = msgs.length + ' 条';
    row.appendChild(cnt);
    return row;
  }

  // 递归: 为一个分支条目创建可折叠节点(头=摘要+toggle, 体=完整 thread card)
  function createBranchNode(entry, branchCtx, depth) {
    const expanded = isBranchExpanded(entry.run_id, entry, false);
    const node = document.createElement('div');
    node.className = 'thread-branch' + (expanded ? ' is-expanded' : ' is-collapsed');
    node.dataset.runId = entry.run_id;
    node.dataset.branchDepth = depth;

    const head = document.createElement('div');
    head.className = 'thread-branch-head';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'thread-branch-toggle';
    toggle.textContent = expanded ? '▿' : '▸';
    toggle.title = expanded ? '收起分支' : '展开分支';
    toggle.addEventListener('click', () => {
      const now = node.classList.contains('is-expanded');
      const next = !now;
      node.classList.toggle('is-expanded', next);
      node.classList.toggle('is-collapsed', !next);
      toggle.textContent = next ? '▿' : '▸';
      setBranchCollapsed(entry.run_id, !next);
      const body = node.querySelector(':scope > .thread-branch-body');
      if (body) body.style.display = next ? '' : 'none';
      const summary = node.querySelector(':scope > .thread-branch-summary');
      if (summary) summary.style.display = next ? 'none' : '';
    });
    head.appendChild(toggle);
    head.appendChild(createBranchSummary(entry));
    node.appendChild(head);

    const body = document.createElement('div');
    body.className = 'thread-branch-body';
    body.style.display = expanded ? '' : 'none';
    const childCtx = { childrenOf: branchCtx.childrenOf, byRunId: branchCtx.byRunId, depth: depth };
    const inner = createThreadCard(entry, childCtx, depth);
    inner.classList.add('thread-branch-inner');
    body.appendChild(inner);
    node.appendChild(body);

    const summary = head.querySelector('.thread-branch-summary');
    if (summary) summary.style.display = expanded ? 'none' : '';
    return node;
  }

  // 在分叉点消息下方插入分支组
  function createBranchGroup(parentEntry, msgIdx, branchCtx, depth) {
    const map = branchCtx.childrenOf.get(parentEntry.run_id);
    if (!map) return null;
    const idxKey = String(msgIdx);
    const children = map.get(idxKey);
    if (!children || !children.length) return null;
    const group = document.createElement('div');
    group.className = 'thread-branch-group';
    children.sort((a, b) => String(a.timestamp || '').localeCompare(String(b.timestamp || '')));
    children.forEach((child) => {
      group.appendChild(createBranchNode(child, branchCtx, depth));
    });
    return group;
  }

  function createThreadEntryElement(entry, branchCtx) {
    const ctxForBranch = branchCtx || resolveBranchCtx();
    if (hasRenderableParent(entry, ctxForBranch)) {
      return createBranchNode(entry, ctxForBranch, entryDepth(entry));
    }
    return createThreadCard(entry, ctxForBranch, 0);
  }

  function createThreadCard(entry, branchCtx, depth) {
    depth = depth || 0;
    branchCtx = branchCtx || { childrenOf: new Map(), byRunId: new Map(), depth: 0 };
    const isMainline = depth === 0 || !(entry.metadata && entry.metadata.fork && entry.metadata.fork.parent_run_id);
    const card = document.createElement('div');
    card.className = 'ai-thread ' + (entry.tool === 'claude' ? 'thread-claude' : 'thread-codex');
    card.dataset.runId = entry.run_id;
    card.dataset.status = entry.status || '';
    card.dataset.tool = entry.tool || '';

    const header = document.createElement('div');
    header.className = 'thread-header';
    const badge = document.createElement('span');
    badge.className = 'thread-badge ' + (entry.tool === 'claude' ? 'thread-claude' : 'thread-codex');
    badge.textContent = entry.tool === 'claude' ? 'Claude' : 'Codex';
    header.appendChild(badge);

    const forkMeta = entry.metadata && entry.metadata.fork;
    if (forkMeta) {
      const marker = document.createElement('span');
      marker.className = 'thread-fork-marker';
      const parentLabel = (forkMeta.parent_title || String(forkMeta.parent_run_id || '').slice(0, 8));
      marker.textContent = `⑂ 分支自「${parentLabel}」#${forkMeta.parent_index}`;
      marker.title = `父线程 ${forkMeta.parent_run_id} 的第 ${forkMeta.parent_index} 条消息`;
      header.appendChild(marker);
    }

    const title = document.createElement('div');
    title.className = 'thread-title';
    title.textContent = entry.title || qTaskTitle(entry.path) || 'AI 对话';
    header.appendChild(title);

    const count = document.createElement('span');
    count.className = 'thread-count';
    count.textContent = (entry.messages || []).length ? (entry.messages.length + ' 条消息') : '';
    header.appendChild(count);
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'thread-body';

    const metaRow = document.createElement('div');
    metaRow.className = 'thread-meta';
    const meta = [];
    if (entry.status === 'running') meta.push('处理中');
    else if (entry.status === 'queued') meta.push('排队中');
    else if (entry.status === 'orphaned-running') meta.push('服务重启后进程仍存活 · 输出已断，无法续接');
    else if (entry.status === 'orphaned-unknown') meta.push(entry.error || '孤儿进程已退出 · 最终结果未知');
    else if (entry.status === 'error') meta.push(entry.error || '执行失败');
    else if (entry.status === 'timeout') meta.push('执行超时');
    else if (entry.status === 'killed') meta.push('已终止');
    else if (entry.duration_ms) meta.push((entry.duration_ms / 1000).toFixed(1) + 's');
    if (entry.timestamp) meta.push(entry.timestamp.replace('T', ' ').slice(0, 16));
    metaRow.textContent = meta.join(' · ');
    body.appendChild(metaRow);

    const messages = document.createElement('div');
    messages.className = 'thread-messages';
    const history = (entry.messages && entry.messages.length) ? entry.messages : (entry.output ? [{
      role: 'ai',
      content: entry.output,
      timestamp: entry.timestamp,
      duration_ms: entry.duration_ms,
      model: entry.model,
      input_tokens: entry.input_tokens,
      output_tokens: entry.output_tokens,
      author: 'AI',
    }] : []);
    const forkable = Array.isArray(entry.messages) && entry.messages.length > 0
      && !ACTIVE_RUN_STATUSES.has(entry.status) && entry.status !== 'orphaned-unknown'
      && (entry.tool === 'claude' || entry.tool === 'codex');
    history.forEach((msg, msgIdx) => {
      const bubble = createMessageBubble(msg, entry, msgIdx);
      if (forkable && msg.role === 'ai') bubble.appendChild(createForkAffordance(entry, msgIdx));
      messages.appendChild(bubble);
      // KAN-213: 在此分叉点消息下方插入分支组(若有子分支)
      const group = createBranchGroup(entry, msgIdx, branchCtx, depth + 1);
      if (group) messages.appendChild(group);
    });

    if (entry.status === 'running') {
      const spinner = document.createElement('div');
      spinner.className = 'thread-spinner';
      spinner.textContent = 'AI 正在处理...';
      messages.appendChild(spinner);
    } else if (entry.status === 'orphaned-running') {
      const orphan = document.createElement('div');
      orphan.className = 'thread-spinner thread-orphan-warning';
      orphan.textContent = '进程仍在运行，但服务重启已使输出管道断开；这里只追踪 PID 存活状态。';
      messages.appendChild(orphan);
    } else if (entry.status === 'queued') {
      const queued = document.createElement('div');
      queued.className = 'thread-spinner';
      queued.textContent = '排队中...';
      messages.appendChild(queued);
    }

    body.appendChild(messages);

    if (canComment(entry)) {
      body.appendChild(createCommentInput(entry, 'comment'));
    } else if (canRetry(entry)) {
      body.appendChild(createCommentInput(entry, 'retry'));
    } else if (entry.session_valid === false && (entry.tool === 'claude' || entry.tool === 'codex')
      && !ACTIVE_RUN_STATUSES.has(entry.status) && entry.status !== 'orphaned-unknown') {
      body.appendChild(createSessionExpiredNotice(entry));
    }

    body.appendChild(createThreadActions(entry));
    card.appendChild(body);
    return card;
  }

  function loadAiHistory(path) {
    if (!ctx.hasApi) return Promise.resolve();
    ensureCardChatComposer();
    aiActivity.style.display = 'flex';
    return fetch('/api/ai-results?path=' + encodeURIComponent(path))
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) return;
        const results = durableDialogueResults(data.results || []);
        aiActivity.style.display = 'flex';
        reconcileAiHistory(results);
        updateCardChatEmptyState(results.length > 0);
        syncCardChatActiveFromResults(results);
        results.forEach((result) => {
          if (ACTIVE_RUN_STATUSES.has(result.status)) startPolling(result.run_id, uiState.detail.currentTaskPath);
        });
      })
      .catch(() => {});
  }

  function composerHasDraft() {
    if (!aiActivity) return false;
    if (aiActivity.querySelector('.fork-input-wrap')) return true;
    return Array.from(aiActivity.querySelectorAll('textarea')).some((textarea) => (
      String(textarea.value || '').trim()
      || pendingSourceQuotes.has(textarea)
    ));
  }

  function scheduleIdleReconcile(results, path) {
    if (uiState.ai.reconcileTimer) clearTimeout(uiState.ai.reconcileTimer);
    uiState.ai.reconcileTimer = setTimeout(() => {
      uiState.ai.reconcileTimer = null;
      if (path !== uiState.detail.currentTaskPath) return;
      if (composerHasDraft()) {
        scheduleIdleReconcile(results, path);
        return;
      }
      reconcileAiHistory(results);
    }, 700);
  }

  function reconcileAiHistory(results, options = {}) {
    const list = durableDialogueResults(results);
    rememberAiResults(list, true);
    if (options.deferIfBusy && composerHasDraft()) {
      scheduleIdleReconcile(list, uiState.detail.currentTaskPath);
      return false;
    }
    if (uiState.ai.reconcileTimer) {
      clearTimeout(uiState.ai.reconcileTimer);
      uiState.ai.reconcileTimer = null;
    }
    const tree = uiState.ai.threadTree || buildThreadTree(list);
    const mainline = branchMainline(list, tree.byRunId);
    const branchCtx = { childrenOf: tree.childrenOf, byRunId: tree.byRunId, depth: 0 };
    aiActivityList.textContent = '';
    mainline.forEach((result) => aiActivityList.appendChild(createThreadCard(result, branchCtx, 0)));
    refreshQuoteBlocks();
    return true;
  }

  function updateAiButtonsState() {
    const isDone = uiState.detail.currentTaskStatus === 'done';
    const hasTaskPath = Boolean(uiState.detail.currentTaskPath);
    const disabled = isDone || !hasTaskPath;
    if (detailClaudeBtn) detailClaudeBtn.disabled = disabled;
    if (detailCodexBtn) detailCodexBtn.disabled = disabled;
    const title = isDone
      ? '任务已完成，无法启动 AI'
      : (!hasTaskPath ? '当前不是可执行任务卡' : '');
    if (detailClaudeBtn) detailClaudeBtn.title = title;
    if (detailCodexBtn) detailCodexBtn.title = title;
    updateCardChatState();
  }

  function syncCurrentTaskStatusForPath(path, status) {
    const targetPath = path || uiState.detail.currentTaskPath;
    if (!targetPath) return;
    if (path && targetPath !== uiState.detail.currentTaskPath) return;
    if (typeof status === 'string') {
      uiState.detail.currentTaskStatus = status || 'todo';
      updateAiButtonsState();
      return;
    }
    const task = (dataState.tasks || []).find((item) => item.path === targetPath);
    if (!task) return;
    uiState.detail.currentTaskStatus = task.status || 'todo';
    updateAiButtonsState();
  }

  function syncAiButtonLoadingState(btn) {
    if (!btn) return;
    btn.classList.remove('loading');
    btn.disabled = uiState.detail.currentTaskStatus === 'done' || !uiState.detail.currentTaskPath;
  }

  function setAiRunLoading(tool, isLoading, options, btn) {
    const source = options && options.source;
    if (source === 'card_chat') {
      uiState.ai.cardChatSubmitting = Boolean(isLoading);
      updateCardChatState();
      return;
    }
    if (!btn) return;
    btn.classList.toggle('loading', Boolean(isLoading));
    btn.disabled = Boolean(isLoading) || uiState.detail.currentTaskStatus === 'done' || !uiState.detail.currentTaskPath;
  }

  function runAiTool(tool, options = {}) {
    const normalizedTool = normalizeAiTool(tool);
    if (!uiState.detail.currentTaskPath || !ctx.hasApi) return Promise.resolve({ ok: false, error: '当前不是可执行任务卡' });
    if (options.source === 'card_chat' && (uiState.ai.cardChatSubmitting || uiState.ai.cardChatActiveRunId)) {
      return Promise.resolve({ ok: false, error: '已有 AI 正在处理' });
    }
    const btn = normalizedTool === 'claude' ? detailClaudeBtn : detailCodexBtn;
    setAiRunLoading(normalizedTool, true, options, btn);

    const submit = (createWorkdir) => {
      const payload = {
        path: uiState.detail.currentTaskPath,
        tool: normalizedTool,
        create_workdir: createWorkdir,
      };
      if (options.profile) payload.profile = String(options.profile);
      const prompt = String(options.prompt || '').trim();
      if (prompt) {
        payload.prompt = prompt;
        payload.display_message = String(options.displayMessage || prompt).trim();
        payload.author = uiState.auth.currentUser || '用户';
        if (options.origin) payload.origin = options.origin;
        if (options.sourceQuote) payload.source_quote = options.sourceQuote;
      }
      return fetch('/api/ai-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then((r) => r.json());
    };

    return submit(false)
      .then((data) => {
        if (!data.ok && data.error === 'workdir_not_found') {
          setAiRunLoading(normalizedTool, false, options, btn);
          const ok = confirm(`工作目录不存在:\n${data.workdir}\n\n是否自动创建目录并继续执行？`);
          if (!ok) return { ok: false, cancelled: true };
          setAiRunLoading(normalizedTool, true, options, btn);
          return submit(true);
        }
        return data;
      })
      .then((data) => {
        if (!data) return null;
        setAiRunLoading(normalizedTool, false, options, btn);
        if (!data.ok) {
          if (!data.cancelled) toast(data.error || '提交失败', true);
          return data;
        }
        const runId = data.run_id;
        ensureCardChatComposer();
        aiActivity.style.display = 'flex';
        const now = new Date().toISOString().slice(0, 19);
        const displayMessage = String(options.displayMessage || options.prompt || '').trim();
        const messages = displayMessage ? [{
          role: 'user',
          content: displayMessage,
          timestamp: now,
          author: uiState.auth.currentUser || '用户',
          ...(options.sourceQuote ? { source_quote: options.sourceQuote } : {}),
        }] : [];
        const entry = createThreadCard({
          run_id: runId,
          tool: normalizedTool,
          ai_profile: options.profile || '',
          path: uiState.detail.currentTaskPath,
          status: 'queued',
          timestamp: now,
          messages
        }, resolveBranchCtx(), 0);
        if (options.source === 'card_chat') {
          aiActivityList.appendChild(entry);
          updateCardChatEmptyState(true);
          uiState.ai.cardChatActiveRunId = runId;
          uiState.ai.cardChatActiveStatus = 'queued';
          if (typeof options.onQueued === 'function') options.onQueued(runId);
          updateCardChatState();
          scrollCardChatToBottom();
        } else {
          aiActivityList.insertBefore(entry, aiActivityList.firstChild);
        }
        toast(profileLabel(options.profile || '', toolLabel(normalizedTool)) + ' 任务已创建，已加入 AI 队列');
        resumeQueueBadgePolling();
        startPolling(runId, uiState.detail.currentTaskPath);
        return data;
      })
      .catch((e) => {
        setAiRunLoading(normalizedTool, false, options, btn);
        toast('网络错误: ' + e.message, true);
        return { ok: false, error: e.message || '网络错误' };
      });
  }

  function startPolling(runId, path, options = {}) {
    if (uiState.ai.pollTimers[runId]) return;
    const onDone = options && typeof options.onDone === 'function' ? options.onDone : null;
    uiState.ai.pollTimers[runId] = setInterval(() => {
      fetch('/api/ai-results?path=' + encodeURIComponent(path))
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) {
            stopPolling(runId);
            return;
          }
          const all = data.results || [];
          const entry = all.find((item) => item.run_id === runId);
          if (!entry) return;
          if (uiState.ai.cardChatActiveRunId === runId && ACTIVE_RUN_STATUSES.has(entry.status)) {
            uiState.ai.cardChatActiveStatus = entry.status;
            updateCardChatState();
          }
          reconcileAiHistory(all, { deferIfBusy: true });
          if (TERMINAL_RUN_STATUSES.has(entry.status)) {
            stopPolling(runId);
            toast(entry.tool + ' 执行完成');
            if (uiState.ai.cardChatActiveRunId === runId) {
              uiState.ai.cardChatActiveRunId = '';
              uiState.ai.cardChatActiveStatus = '';
              updateCardChatState();
            }
            if (onDone) onDone(entry);
          }
        })
        .catch(() => {});
    }, 10000);
  }

  function stopPolling(runId) {
    if (uiState.ai.pollTimers[runId]) {
      clearInterval(uiState.ai.pollTimers[runId]);
      delete uiState.ai.pollTimers[runId];
    }
  }

  function killAiRun(runId) {
    fetch('/api/ai-kill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: runId }),
    })
      .then((r) => r.json())
      .then((data) => {
        toast(data.ok ? '已终止' : (data.error || '终止失败'));
        stopPolling(runId);
        if (uiState.ai.cardChatActiveRunId === runId) {
          uiState.ai.cardChatActiveRunId = '';
          uiState.ai.cardChatActiveStatus = '';
          updateCardChatState();
        }
        if (uiState.detail.currentTaskPath) {
          const el = aiActivityList.querySelector('[data-run-id="' + runId + '"]');
          if (el) {
            const existingEntry = uiState.ai.threadTree && uiState.ai.threadTree.byRunId
              ? uiState.ai.threadTree.byRunId.get(runId)
              : null;
            const killedEntry = {
              ...(existingEntry || {}),
              run_id: runId,
              tool: (existingEntry && existingEntry.tool) || (el.classList.contains('thread-claude') ? 'claude' : 'codex'),
              status: 'killed',
              error: '用户终止',
              messages: (existingEntry && existingEntry.messages) || [],
            };
            const newEl = createThreadEntryElement(killedEntry, resolveBranchCtx());
            el.replaceWith(newEl);
            refreshQuoteBlocks();
          }
        }
      })
      .catch(() => toast('网络错误', true));
  }

  function deleteAiResult(runId) {
    if (!confirm('确定删除该对话记录？此操作不可撤销。')) return;
    stopPolling(runId);
    fetch('/api/ai-result', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: runId, path: uiState.detail.currentTaskPath }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.ok) {
          const el = aiActivityList.querySelector('[data-run-id="' + runId + '"]');
          if (el) el.remove();
          rememberAiResults((uiState.ai.currentResults || []).filter((entry) => entry.run_id !== runId), true);
          updateCardChatEmptyState(!aiActivityList.children.length ? false : true);
          if (uiState.ai.cardChatActiveRunId === runId) {
            uiState.ai.cardChatActiveRunId = '';
            uiState.ai.cardChatActiveStatus = '';
            updateCardChatState();
          }
        } else {
          toast(data.error || '删除失败');
        }
      })
      .catch(() => toast('网络错误', true));
  }

  function copyAiResult(runId) {
    const el = aiActivityList.querySelector('[data-run-id="' + runId + '"]');
    if (!el) return;
    const output = Array.from(el.querySelectorAll('.msg-card.ai .msg-content')).map((n) => n.textContent || n.innerText || '').join('\n\n');
    navigator.clipboard.writeText(output).then(() => toast('已复制结果')).catch(() => {
      const ta = document.createElement('textarea');
      ta.value = output;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      toast('已复制结果');
    });
  }

  function submitComment(runId, comment, inputWrapper, skillId, slashMenu) {
    const textarea = inputWrapper.querySelector('.comment-input');
    const sendBtn = inputWrapper.querySelector('.comment-send-btn');
    const card = inputWrapper.closest('.ai-thread');
    const sourceQuote = pendingSourceQuotes.get(textarea) || null;
    textarea.disabled = true;
    sendBtn.disabled = true;
    sendBtn.textContent = '发送中...';
    fetch('/api/ai-comment', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        run_id: runId,
        comment,
        author: uiState.auth.currentUser,
        skill_id: skillId || '',
        source_quote: sourceQuote,
      }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) {
          toast(data.error || '发送失败', true);
          textarea.disabled = false;
          sendBtn.disabled = false;
          sendBtn.textContent = sendBtn.dataset.idleLabel || '发送';
          if (data.session_valid === false) {
            const el = aiActivityList.querySelector('[data-run-id="' + runId + '"]');
            if (el) {
              const toolFromCard = el.dataset.tool || 'claude';
              const errEntry = { run_id: runId, tool: toolFromCard, status: 'error', session_valid: false, messages: [] };
              const fresh = createThreadCard(errEntry, resolveBranchCtx(), entryDepth(errEntry));
              el.replaceWith(fresh);
            }
          }
          return;
        }
        if (card) {
          const messages = card.querySelector('.thread-messages');
          if (messages) {
            const userBubble = document.createElement('div');
            userBubble.className = 'msg-bubble';
            const userCard = document.createElement('div');
            userCard.className = 'msg-card user';
            const head = document.createElement('div');
            head.className = 'msg-head';
            const author = document.createElement('span');
            author.className = 'msg-author';
            author.textContent = uiState.auth.currentUser || '用户';
            head.appendChild(author);
            const time = document.createElement('span');
            time.textContent = new Date().toISOString().slice(11, 16);
            head.appendChild(time);
            userCard.appendChild(head);
            if (sourceQuote) userCard.appendChild(createSourceQuoteCard(sourceQuote));
            const content = document.createElement('div');
            content.className = 'msg-content';
            if (markdown.looksLikeMarkdown(comment)) {
              markdown.renderMarkdownEnhanced(content, comment, uiState.detail.currentTaskPath || '');
            } else {
              content.textContent = comment;
            }
            userCard.appendChild(content);
            userBubble.appendChild(userCard);
            messages.appendChild(userBubble);
            const spinner = document.createElement('div');
            spinner.className = 'thread-spinner';
            spinner.textContent = 'AI 正在处理...';
            messages.appendChild(spinner);
          }
        }
        textarea.value = '';
        removeSourceQuote(textarea);
        if (slashMenu) slashMenu.clearSelectedSkill();
        textarea.disabled = false;
        sendBtn.textContent = sendBtn.dataset.idleLabel || '发送';
        sendBtn.disabled = true;
        startCommentPolling(runId);
      })
      .catch(() => {
        textarea.disabled = false;
        sendBtn.disabled = false;
        sendBtn.textContent = sendBtn.dataset.idleLabel || '发送';
        toast('网络错误', true);
      });
  }

  function getThreadEntry(runId) {
    if (!ctx.hasApi) return null;
    const entries = (uiState.queue.data && uiState.queue.data.entries) || [];
    return entries.find((entry) => entry.id === runId) || null;
  }

  function startCommentPolling(runId) {
    startPolling(runId, uiState.detail.currentTaskPath);
  }


  Object.assign(ai, { ensureCardChatComposer, submitCardChat, createCommentInput, createForkAffordance, resolveBranchCtx, entryDepth, buildThreadTree, branchMainline, hasRenderableParent, isBranchExpanded, setBranchCollapsed, createBranchSummary, createBranchNode, createBranchGroup, createThreadEntryElement, createThreadCard, loadAiHistory, composerHasDraft, scheduleIdleReconcile, reconcileAiHistory, updateAiButtonsState, syncCurrentTaskStatusForPath, syncAiButtonLoadingState, setAiRunLoading, runAiTool, startPolling, stopPolling, killAiRun, deleteAiResult, copyAiResult, submitComment, getThreadEntry, startCommentPolling });
  return ai;
}
