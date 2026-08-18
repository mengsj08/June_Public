// KAN-1600: mounted by main.js; dependencies arrive through ctx.renderBoardInternal.
export function setupRenderBoardConsoleCards(ctx) {
  const board = ctx.renderBoardInternal;
  if (!board) throw new Error("setupRenderBoard(ctx) must run first");
  const { dataState, uiState, SL, dueDateText, toast, VIEWS, TASK_DOMAIN_LABELS, CONSOLE_AUDIENCE_OWNER, CONSOLE_AUDIENCE_ATTENTION_GATE, PROJECT_MAP_FAMILY_LABELS } = board;
  const normalizeConsoleAudienceMode = (...args) => board.normalizeConsoleAudienceMode(...args);
  const isConsoleAttentionGateMode = (...args) => board.isConsoleAttentionGateMode(...args);
  const visibleBoardViewsForAudience = (...args) => board.visibleBoardViewsForAudience(...args);
  const normalizeProjectMapFamily = (...args) => board.normalizeProjectMapFamily(...args);
  const normalizeConsoleAiMembers = (...args) => board.normalizeConsoleAiMembers(...args);
  const consoleTaskAssignee = (...args) => board.consoleTaskAssignee(...args);
  const consoleAssigneeIsAi = (...args) => board.consoleAssigneeIsAi(...args);
  const consoleNormalizedStatus = (...args) => board.consoleNormalizedStatus(...args);
  const isConsoleWaitingTask = (...args) => board.isConsoleWaitingTask(...args);
  const isConsoleReviewTask = (...args) => board.isConsoleReviewTask(...args);
  const isConsolePendingAiDispatchTask = (...args) => board.isConsolePendingAiDispatchTask(...args);
  const landingPageDriftState = (...args) => board.landingPageDriftState(...args);
  const teamDigestTypeLabel = (...args) => board.teamDigestTypeLabel(...args);
  const isTeamDigestStale = (...args) => board.isTeamDigestStale(...args);
  const consoleTeamDigestEntries = (...args) => board.consoleTeamDigestEntries(...args);
  const teamDigestStillText = (...args) => board.teamDigestStillText(...args);
  const sortTasks = (...args) => board.sortTasks(...args);
  const createCardEl = (...args) => board.createCardEl(...args);
  const updateTaskStatus = (...args) => board.updateTaskStatus(...args);

  function consoleAiSet() {
    return normalizeConsoleAiMembers(dataState.ai_members);
  }

  function currentPerson() {
    return uiState.auth.currentUser || (dataState.login_members && dataState.login_members[0]) || 'Owner';
  }

  function consoleAudienceMode() {
    return normalizeConsoleAudienceMode(uiState.board && uiState.board.audienceMode);
  }

  function consoleAudienceIsAttentionGate() {
    return isConsoleAttentionGateMode(consoleAudienceMode());
  }

  function currentBoardViews() {
    return visibleBoardViewsForAudience(consoleAudienceMode(), VIEWS);
  }

  function markConsoleAudience(node, audience) {
    if (!node) return node;
    const normalized = audience === CONSOLE_AUDIENCE_ATTENTION_GATE
      ? CONSOLE_AUDIENCE_ATTENTION_GATE
      : CONSOLE_AUDIENCE_OWNER;
    node.dataset.audience = normalized;
    node.classList.add('console-audience-' + normalized);
    return node;
  }

  function appendIfNode(parent, node) {
    if (parent && node) parent.appendChild(node);
    return node;
  }

  function dutySourcePath(ref) {
    return String(ref && ref.path ? ref.path : '').trim();
  }

  function openDutySource(ref) {
    const path = dutySourcePath(ref);
    if (!path || !ctx.api || typeof ctx.api.openInEditor !== 'function') return;
    ctx.api.openInEditor(path);
  }

  function markDutySource(node, ref) {
    const path = dutySourcePath(ref);
    if (!node || !path) return node;
    node.dataset.sourcePath = path;
    if (ref && ref.line) node.dataset.sourceLine = String(ref.line);
    return node;
  }

  function makeDutySourceButton(ref) {
    const path = dutySourcePath(ref);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'console-duty-source';
    btn.title = path ? '打开源文件: ' + path : '无源文件';
    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', 'file-text');
    const label = document.createElement('span');
    label.textContent = path || '无源文件';
    btn.appendChild(icon);
    btn.appendChild(label);
    btn.onclick = (e) => {
      e.stopPropagation();
      openDutySource(ref);
    };
    markDutySource(btn, ref);
    return btn;
  }

  function dutyShortStamp(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    return text.replace('T', ' ').slice(0, 19);
  }

  function dutyText(value, fallback = '') {
    const text = String(value || '').trim();
    return text || fallback;
  }

  function decorateConsoleCard(task, card, withReview, options = {}) {
    card.classList.add('console-card');
    if (withReview) card.classList.add('is-review');
    const unrouted = Boolean(options.unrouted);
    if (unrouted) {
      card.classList.add('is-console-unrouted');
      card.dataset.consoleUnrouted = 'true';
    }
    const pendingAiDispatch = isConsolePendingAiDispatchTask(task, consoleAiSet());
    if (pendingAiDispatch) {
      card.classList.add('is-pending-ai-dispatch');
      card.dataset.consolePendingAi = 'true';
    }
    const meta = card.querySelector('.m');
    if (meta) {
      const statusChip = document.createElement('span');
      const status = task.status || 'todo';
      statusChip.className = 'b console-chip-status';
      statusChip.textContent = SL[status] || status || '待办';
      if (status === 'review') statusChip.classList.add('console-chip-warn');
      else if (status === 'in-progress') statusChip.classList.add('console-chip-info');
      else if (status === 'todo') statusChip.classList.add('console-chip-todo');
      meta.insertBefore(statusChip, meta.firstChild);
      if (pendingAiDispatch) {
        const pendingChip = document.createElement('span');
        pendingChip.className = 'b console-chip-pending-ai';
        pendingChip.textContent = '待派 AI';
        pendingChip.title = 'AI 责任卡，等待进入执行队列';
        meta.insertBefore(pendingChip, statusChip.nextSibling);
      }
      if (isConsoleWaitingTask(task)) {
        const waitingChip = document.createElement('span');
        waitingChip.className = 'b console-chip-mute';
        waitingChip.textContent = '等待中';
        const waitingOn = Array.isArray(task.waiting_on) ? task.waiting_on.join('、') : String(task.waiting_on || task.blocked_by || '').trim();
        waitingChip.title = waitingOn ? '等待：' + waitingOn : '等待外部或前置依赖';
        meta.insertBefore(waitingChip, statusChip.nextSibling);
      }
      if (unrouted) {
        const unroutedChip = document.createElement('span');
        unroutedChip.className = 'b console-chip-unrouted';
        unroutedChip.textContent = '未归类';
        unroutedChip.title = '未匹配调度台主泳道，需确认归属';
        meta.insertBefore(unroutedChip, statusChip.nextSibling);
      }
    }
    if (isDueNow(task)) {
      card.classList.add('is-due-now');
      card.querySelectorAll('.due').forEach((dueEl) => dueEl.classList.add('console-due-now'));
    }
    card.querySelectorAll('.b-who').forEach((badgeEl) => {
      if (consoleAssigneeIsAi(task, consoleAiSet())) badgeEl.classList.add('console-chip-ai');
      else badgeEl.classList.add('console-chip-mute');
    });
    card.querySelectorAll('.b-proj').forEach((badgeEl) => badgeEl.classList.add('console-chip-mute'));
    card.querySelectorAll('.b-scenario').forEach((badgeEl) => badgeEl.classList.add('console-chip-scene'));
    card.querySelectorAll('.b-source').forEach((badgeEl) => badgeEl.classList.add('console-chip-mute'));
    // 类型泳道退役后（KAN-199），类型降级为卡片角落灰色小标签：domain 优先，回退 task_family。
    // 灰色小字不用彩色，不加框（Owner 审美红线）。
    if (meta) {
      const typeText = consoleCardTypeLabel(task);
      if (typeText) {
        const typeChip = document.createElement('span');
        typeChip.className = 'b console-chip-type';
        typeChip.textContent = typeText;
        typeChip.title = '类型：' + typeText;
        meta.appendChild(typeChip);
      }
    }
  }

  function consoleCardTypeLabel(task) {
    const domain = String((task && task.domain) || '').trim();
    if (domain && domain !== 'personal') return TASK_DOMAIN_LABELS[domain] || domain;
    const family = String((task && task.task_family) || '').trim();
    if (family) {
      const canonical = normalizeProjectMapFamily(family);
      return (canonical && PROJECT_MAP_FAMILY_LABELS[canonical]) || family;
    }
    return '';
  }

  function appendConsoleTaskCard(lane, task, withReview, options = {}) {
    const card = createCardEl(task);
    decorateConsoleCard(task, card, withReview, options);
    if (withReview && isConsoleReviewTask(task, currentPerson())) {
      const bar = document.createElement('div');
      bar.className = 'console-review-actions';
      const ok = document.createElement('button');
      ok.textContent = '✓ 验收';
      ok.className = 'console-ok';
      ok.onclick = (ev) => { ev.stopPropagation(); updateTaskStatus(task, 'done'); };
      const back = document.createElement('button');
      back.textContent = '↩ 打回';
      back.className = 'console-reject';
      back.onclick = (ev) => { ev.stopPropagation(); updateTaskStatus(task, 'todo'); };
      bar.appendChild(ok); bar.appendChild(back);
      card.appendChild(bar);
    }
    lane.appendChild(card);
  }

  function appendConsoleLaneAfter(lane, after) {
    const appendices = Array.isArray(after) ? after : (after ? [after] : []);
    appendices.filter(Boolean).forEach((node) => lane.appendChild(node));
  }

  function makeConsoleLane(title, items, tone, withReview, options = {}) {
    const lane = document.createElement('div');
    lane.className = 'console-lane console-lane-' + tone;
    if (options.anchorId) lane.id = options.anchorId;
    markConsoleAudience(lane, options.audience || CONSOLE_AUDIENCE_OWNER);
    const hd = document.createElement('div');
    hd.className = 'console-lane-hd';
    const lbl = document.createElement('span');
    lbl.textContent = title;
    const cnt = document.createElement('span');
    cnt.textContent = items.length;
    cnt.className = 'console-lane-count';
    hd.appendChild(lbl); hd.appendChild(cnt);
    lane.appendChild(hd);
    const after = options.after;
    if (!items.length) {
      // 空泳道折叠成一行（标题 + 状态同行），不占首屏黄金位。
      if (!after) lane.classList.add('is-empty');
      const e = document.createElement('div');
      e.className = 'console-empty';
      e.textContent = tone === 'attention' ? '✓ 已全部验收' : '暂无';
      lane.appendChild(e);
      appendConsoleLaneAfter(lane, after);
      return lane;
    }
    // 类型泳道分组已退役（KAN-199,Owner 2026-07-06 拍板）：类型轴分组是「写给 ARIS 看的标题」，
    // 不符合 Owner 看法习惯。主列改为纯动作序单流，类型降级为卡片角落灰色小标签（见 decorateConsoleCard）。
    // 「等我验收」超过 fold 阈值时尾部折叠成「其余 N 张」展开，不占首屏黄金位。
    const fold = Number.isFinite(options.foldAfter) ? options.foldAfter : 0;
    if (fold > 0 && items.length > fold + 1) {
      const head = items.slice(0, fold);
      const tail = items.slice(fold);
      head.forEach((task) => appendConsoleTaskCard(lane, task, withReview, options));
      const details = document.createElement('details');
      details.className = 'console-lane-fold';
      markConsoleAudience(details, options.audience || CONSOLE_AUDIENCE_OWNER);
      const summary = document.createElement('summary');
      summary.className = 'console-lane-fold-summary';
      summary.textContent = '其余 ' + tail.length + ' 张';
      details.appendChild(summary);
      tail.forEach((task) => appendConsoleTaskCard(details, task, withReview, options));
      lane.appendChild(details);
      appendConsoleLaneAfter(lane, after);
      return lane;
    }
    items.forEach((task) => appendConsoleTaskCard(lane, task, withReview, options));
    appendConsoleLaneAfter(lane, after);
    return lane;
  }

  function makeConsoleFoldedTaskSection(title, items, options = {}) {
    const details = document.createElement('details');
    details.className = 'console-gov-background console-lane-donelog';
    markConsoleAudience(details, options.audience || CONSOLE_AUDIENCE_ATTENTION_GATE);
    const summary = document.createElement('summary');
    summary.textContent = title + ' ' + items.length + ' 项';
    details.appendChild(summary);
    items.forEach((task) => appendConsoleTaskCard(details, task, Boolean(options.withReview), options.cardOptions || {}));
    return details;
  }

  // KAN-199 盘面条（cursor 条）：顶栏下一条单行状态条，回答「Owner 现在要做什么动作」。
  // 前三段（拍板/验收/必做）点击滚动到主列对应区；后两段（灰，AI 在办 / 收件箱）点击展开抽屉，平时不占版面。
  function makeConsoleCursorBar(segments) {
    const bar = document.createElement('div');
    bar.className = 'console-cursor-bar';
    markConsoleAudience(bar, CONSOLE_AUDIENCE_OWNER);
    const primary = document.createElement('div');
    primary.className = 'console-cursor-group console-cursor-primary';
    const secondary = document.createElement('div');
    secondary.className = 'console-cursor-group console-cursor-secondary';
    let renderedSecondary = 0;
    segments.forEach((seg) => {
      if (seg.tone === 'muted' && !seg.count) return; // 收件箱等为 0 时该段隐藏
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'console-cursor-seg' + (seg.tone === 'muted' ? ' is-muted' : '');
      const label = document.createElement('span');
      label.className = 'console-cursor-seg-label';
      label.textContent = seg.label;
      const count = document.createElement('span');
      count.className = 'console-cursor-seg-count';
      count.textContent = seg.count;
      chip.appendChild(label);
      chip.appendChild(count);
      chip.onclick = seg.onClick || (() => {});
      if (seg.tone === 'muted') { secondary.appendChild(chip); renderedSecondary += 1; }
      else primary.appendChild(chip);
    });
    bar.appendChild(primary);
    if (renderedSecondary) {
      const sep = document.createElement('span');
      sep.className = 'console-cursor-sep';
      sep.textContent = '';
      bar.appendChild(sep);
      bar.appendChild(secondary);
    }
    return bar;
  }

  function scrollConsoleSectionIntoView(anchorId) {
    const node = document.getElementById(anchorId);
    if (!node) return;
    if (typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    node.classList.add('console-section-flash');
    setTimeout(() => node.classList.remove('console-section-flash'), 1200);
  }

  function openConsoleDrawer(drawerId) {
    const node = document.getElementById(drawerId);
    if (!node) return;
    if ('open' in node) node.open = true;
    scrollConsoleSectionIntoView(drawerId);
  }

  // KAN-199 抽屉：AI 在办 / 收件箱等「不需要 Owner 动作」的内容收进折叠区，平时不占主列。
  function makeConsoleDrawer(id, title, items, options = {}) {
    const details = document.createElement('details');
    details.className = 'console-drawer';
    details.id = id;
    markConsoleAudience(details, options.audience || CONSOLE_AUDIENCE_OWNER);
    const summary = document.createElement('summary');
    summary.className = 'console-drawer-summary';
    const lbl = document.createElement('span');
    lbl.className = 'console-drawer-title';
    lbl.textContent = title;
    const cnt = document.createElement('span');
    cnt.className = 'console-lane-count';
    cnt.textContent = Number.isFinite(options.countOverride) ? options.countOverride : items.length;
    summary.appendChild(lbl);
    summary.appendChild(cnt);
    details.appendChild(summary);
    const body = document.createElement('div');
    body.className = 'console-drawer-body';
    if (options.content) {
      body.appendChild(options.content);
    } else if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'console-empty';
      empty.textContent = '暂无';
      body.appendChild(empty);
    } else {
      items.forEach((task) => appendConsoleTaskCard(body, task, Boolean(options.withReview), options.cardOptions || {}));
    }
    if (options.after) {
      const appendices = Array.isArray(options.after) ? options.after : [options.after];
      appendices.filter(Boolean).forEach((node) => body.appendChild(node));
    }
    details.appendChild(body);
    return details;
  }

  function makeConsoleAgentWorkContent(items) {
    const wrap = document.createElement('div');
    wrap.className = 'console-agent-groups';
    const groups = new Map();
    items.forEach((task) => {
      const owner = consoleTaskAssignee(task) || '未指定 Agent';
      if (!groups.has(owner)) groups.set(owner, []);
      groups.get(owner).push(task);
    });
    Array.from(groups.entries())
      .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0], 'zh-CN'))
      .forEach(([owner, tasks]) => {
        const group = document.createElement('details');
        group.className = 'console-agent-group';
        const summary = document.createElement('summary');
        summary.className = 'console-agent-group-summary';
        const identity = document.createElement('span');
        identity.className = 'console-agent-identity';
        const name = document.createElement('strong');
        name.textContent = owner;
        const statuses = Array.from(new Set(tasks.map((task) => consoleNormalizedStatus(task)))).join(' · ');
        const meta = document.createElement('small');
        meta.textContent = statuses || '执行中';
        identity.appendChild(name);
        identity.appendChild(meta);
        const count = document.createElement('span');
        count.className = 'console-lane-count';
        count.textContent = String(tasks.length);
        summary.appendChild(identity);
        summary.appendChild(count);
        const body = document.createElement('div');
        body.className = 'console-agent-group-body';
        tasks.forEach((task) => appendConsoleTaskCard(body, task, false, {}));
        group.appendChild(summary);
        group.appendChild(body);
        wrap.appendChild(group);
      });
    return wrap;
  }

  function isDueNow(task) {
    const dueMeta = dueDateText(task.due_date, task.status);
    return Boolean(dueMeta && (dueMeta.overdue || dueMeta.text === '今天到期'));
  }

  function sortConsoleTodayTasks(tasks) {
    return sortTasks(tasks).sort((a, b) => Number(isDueNow(b)) - Number(isDueNow(a)));
  }

  function makeConsoleSummaryLane(title, items, tone, content, countOverride, options = {}) {
    const lane = document.createElement('div');
    lane.className = 'console-lane console-lane-' + tone;
    markConsoleAudience(lane, options.audience || CONSOLE_AUDIENCE_OWNER);
    const hd = document.createElement('div');
    hd.className = 'console-lane-hd';
    const lbl = document.createElement('span');
    lbl.textContent = title;
    const cnt = document.createElement('span');
    cnt.textContent = Number.isFinite(countOverride) ? countOverride : items.length;
    cnt.className = 'console-lane-count';
    hd.appendChild(lbl); hd.appendChild(cnt);
    lane.appendChild(hd);
    if (typeof content === 'string') {
      const e = document.createElement('div');
      e.className = 'console-empty';
      e.textContent = content;
      lane.appendChild(e);
    } else {
      lane.appendChild(content);
    }
    return lane;
  }

  function teamKanbanBaseUrl() {
    return dataState.team_kanban_url || 'http://localhost:8899/';
  }

  function teamKanbanAutologinUrl() {
    const base = teamKanbanBaseUrl();
    try {
      const url = new URL(base, window.location.href);
      url.searchParams.set('autologin', '1');
      return url.toString();
    } catch (e) {
      const sep = String(base).includes('?') ? '&' : '?';
      return String(base || 'http://localhost:8899/') + sep + 'autologin=1';
    }
  }

  function openTeamKanbanUrl(url) {
    window.open(url || teamKanbanAutologinUrl(), '_blank', 'noopener');
  }

  function makeTeamDigestDegraded(digest) {
    const box = document.createElement('div');
    box.className = 'console-team-degraded';
    const text = document.createElement('span');
    text.textContent = teamDigestStillText(digest);
    box.appendChild(text);
    return box;
  }

  function makeTeamDigestEntry(entry) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'console-team-digest-row';
    const label = document.createElement('span');
    label.className = 'console-team-digest-type';
    label.textContent = teamDigestTypeLabel(entry.type);
    const main = document.createElement('span');
    main.className = 'console-team-digest-main';
    const title = document.createElement('span');
    title.className = 'console-team-digest-title';
    title.textContent = entry.title || '未命名团队卡';
    const meta = document.createElement('span');
    meta.className = 'console-team-digest-meta';
    const parts = [];
    if (entry.status) parts.push(SL[entry.status] || entry.status);
    if (entry.assignee) parts.push(entry.assignee);
    if (entry.due_date) parts.push(entry.due_date);
    meta.textContent = parts.join(' · ') || '团队看板';
    main.appendChild(title);
    main.appendChild(meta);
    row.appendChild(label);
    row.appendChild(main);
    row.onclick = () => openTeamKanbanUrl(entry.remote_url);
    return row;
  }

  function makeTeamDigestBlock(digest) {
    const block = document.createElement('div');
    block.className = 'console-team-block';
    const title = document.createElement('div');
    title.className = 'console-team-section-title';
    title.textContent = '团队动态';
    block.appendChild(title);
    const entries = consoleTeamDigestEntries(digest, 8);
    if (isTeamDigestStale(digest, 3) || !entries.length) {
      block.appendChild(makeTeamDigestDegraded(digest));
      return block;
    }
    const list = document.createElement('div');
    list.className = 'console-team-digest-list';
    entries.forEach((entry) => list.appendChild(makeTeamDigestEntry(entry)));
    block.appendChild(list);
    return block;
  }

  function makeTeamPointerBlock(items) {
    const block = document.createElement('div');
    block.className = 'console-team-block console-team-pointers';
    const title = document.createElement('div');
    title.className = 'console-team-section-title';
    title.textContent = '本地指针卡';
    block.appendChild(title);
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'console-empty';
      empty.textContent = '暂无团队看板指针卡';
      block.appendChild(empty);
      return block;
    }
    items.forEach((task) => appendConsoleTaskCard(block, task, false));
    return block;
  }

  function makeTeamCoordinationPanel(digest, pointerTasks) {
    const panel = document.createElement('div');
    panel.className = 'console-team-panel';
    panel.appendChild(makeTeamDigestBlock(digest));
    panel.appendChild(makeTeamPointerBlock(pointerTasks));
    return panel;
  }

  function copyTextToClipboard(text, label) {
      const value = String(text || '');
      if (!value) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(() => toast(label || '已复制')).catch(() => toast('复制失败', true));
        return;
      }
      const area = document.createElement('textarea');
      area.value = value;
      area.style.position = 'fixed';
      area.style.left = '-9999px';
      document.body.appendChild(area);
      area.focus();
      area.select();
      try {
        document.execCommand('copy');
        toast(label || '已复制');
      } catch (e) {
        toast('复制失败', true);
      }
      area.remove();
    }

  function openConsoleLandingTask(task) {
      if (ctx.renderDetail && typeof ctx.renderDetail.openTaskDetail === 'function') {
        ctx.renderDetail.openTaskDetail(task.path);
        return;
      }
      if (task && task.task_id) window.location.hash = '#' + task.task_id;
    }

  async function queueLandingAction(task, mode, button) {
      if (!task || !task.path) {
        toast('缺少任务卡路径', true);
        return;
      }
      if (!ctx.hasApi || !ctx.api || !ctx.api.apiJson) {
        toast('静态模式不可触发 Landing 动作', true);
        return;
      }
      const endpoint = mode === 'review' ? '/api/landing/review' : '/api/landing/refresh';
      const runningText = mode === 'review' ? '校验中' : '更新中';
      const doneText = mode === 'review' ? 'AI 校验已入队' : 'Landing 更新已入队';
      const originalText = button ? button.textContent : '';
      if (button) {
        button.disabled = true;
        button.textContent = runningText;
      }
      try {
        const { json } = await ctx.api.apiJson(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: task.path }),
        });
        if (!json.ok) {
          toast(json.error || json.message || 'Landing 动作失败', true);
          return;
        }
        toast(json.message || doneText);
        if (ctx.ai && typeof ctx.ai.startQueueBadgePolling === 'function') ctx.ai.startQueueBadgePolling();
        if (ctx.ai && typeof ctx.ai.openQueueSidebar === 'function') ctx.ai.openQueueSidebar('running');
      } catch (e) {
        toast('网络错误', true);
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = originalText;
        }
      }
    }

  function makeConsoleLandingRow(task) {
      const drift = landingPageDriftState(task);
      const row = document.createElement('div');
      row.className = 'console-landing-row' + (drift.stale ? ' is-stale' : '');
      const top = document.createElement('div');
      top.className = 'console-landing-top';
      const title = document.createElement('button');
      title.type = 'button';
      title.className = 'console-landing-title';
      title.textContent = `#${task.task_id || 'NO-ID'} · ${task.title || task.display_title || '未命名状态页'}`;
      title.onclick = () => openConsoleLandingTask(task);
      const status = document.createElement('span');
      status.className = 'console-landing-status';
      status.textContent = drift.label;
      top.appendChild(title);
      top.appendChild(status);
      row.appendChild(top);

      const meta = document.createElement('div');
      meta.className = 'console-landing-meta';
      meta.textContent = [
        task.landing_page,
        drift.landingUpdated ? `状态页 ${drift.landingUpdated}` : '未记录刷新日期',
        drift.updated ? `卡片 ${drift.updated}` : '',
      ].filter(Boolean).join(' · ');
      row.appendChild(meta);

      const actions = document.createElement('div');
      actions.className = 'console-landing-actions';
      const open = document.createElement('button');
      open.type = 'button';
      open.className = 'console-landing-btn primary';
      open.textContent = '打开页面';
      open.onclick = () => ctx.api && ctx.api.openInEditor ? ctx.api.openInEditor(task.landing_page) : toast('静态模式不可打开文件', true);
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'console-landing-btn';
      card.textContent = '任务卡';
      card.onclick = () => openConsoleLandingTask(task);
      const review = document.createElement('button');
      review.type = 'button';
      review.className = 'console-landing-btn';
      review.textContent = 'AI校验';
      review.onclick = () => queueLandingAction(task, 'review', review);
      const refresh = document.createElement('button');
      refresh.type = 'button';
      refresh.className = 'console-landing-btn';
      refresh.textContent = '更新';
      refresh.onclick = () => queueLandingAction(task, 'refresh', refresh);
      actions.appendChild(open);
      actions.appendChild(card);
      actions.appendChild(review);
      actions.appendChild(refresh);
      row.appendChild(actions);
      return row;
    }

  function makeConsoleLandingPanel(items) {
      const panel = document.createElement('div');
      panel.className = 'console-landing-panel';
      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'console-empty';
        empty.textContent = '暂无绑定 Landing 的任务卡';
        panel.appendChild(empty);
        return panel;
      }
      items.slice(0, 6).forEach((task) => panel.appendChild(makeConsoleLandingRow(task)));
      if (items.length > 6) {
        const more = document.createElement('div');
        more.className = 'console-landing-more';
        more.textContent = `还有 ${items.length - 6} 个状态页未显示`;
        panel.appendChild(more);
      }
      return panel;
    }

  function dynamicPromptFor(provider) {
      const id = provider && provider.id;
      const surfaces = provider && Array.isArray(provider.surfaces) ? provider.surfaces : [];
      if (id === 'governance-probe' || surfaces.includes('governance')) {
        return [
          '请作为 Claude 评审者，读取 kanban-personal 的正式治理矩阵和探针结果：',
          '- shared/toolkit/governance/matrix.json',
          '- shared/toolkit/governance/matrix.probe.json',
          '',
          '请只做代码/治理评审，不直接修改正式 matrix.json。重点判断 G5/G6 的 evidence 是否足以改变正式格子，G2/G4/G7 是否需要人工补充证据，并输出建议 patch 范围。'
        ].join('\n');
      }
      const artifacts = provider && provider.artifacts ? provider.artifacts : {};
      return [
        `请复核动态状态页：${provider && provider.title ? provider.title : id || 'unknown provider'}`,
        `state: ${artifacts.state_path || '未配置'}`,
        `output: ${artifacts.output_path || '未配置'}`,
        '',
        '先确认 owning workspace 与当前状态。若 provider 已归档，只做只读复核，不运行生成命令或写入归档目录。'
      ].join('\n');
    }

  function formatDynamicStamp(provider) {
      if (!provider || !provider.generated_at) return '尚未生成';
      const age = typeof provider.age_days === 'number' ? ` · ${provider.age_days}d` : '';
      return provider.generated_at + age;
    }

  function dynamicTone(provider) {
      if (!provider || provider.running) return 'running';
      if (provider.last_error) return 'error';
      if (provider.is_stale) return 'stale';
      if (provider.generated_at) return 'fresh';
      return 'empty';
    }

  // KAN-979：证据不裸奔——绝对路径不整段进正文，压成行内小链接（打开 + hover 全量 + 复制）。
  function makeDynamicSourceRef(name, pathValue) {
      const wrap = document.createElement('span');
      wrap.className = 'console-dynamic-source-ref';
      const open = document.createElement('button');
      open.type = 'button';
      open.className = 'console-dynamic-source-link';
      open.textContent = name;
      open.title = '打开: ' + pathValue;
      open.onclick = () => {
        if (ctx.api && ctx.api.openInEditor) ctx.api.openInEditor(pathValue);
        else toast('静态模式不可打开文件', true);
      };
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'console-dynamic-source-copy';
      copy.textContent = '⧉';
      copy.title = '复制路径: ' + pathValue;
      copy.onclick = () => copyTextToClipboard(pathValue, name + ' 路径已复制');
      wrap.appendChild(open);
      wrap.appendChild(copy);
      return wrap;
    }

  function makeDynamicProviderCard(provider, onRefreshDone, options) {
      const opts = options || {};
      const card = document.createElement('div');
      card.className = 'console-dynamic-card tone-' + dynamicTone(provider);
      const top = document.createElement('div');
      top.className = 'console-dynamic-top';
      const title = document.createElement('div');
      title.className = 'console-dynamic-title';
      title.textContent = provider.title || provider.id || 'Dynamic provider';
      // KAN-979：「过期 · N d」合并为右上一个 muted 徽章（状态 + 数据龄同一枚）。
      const status = document.createElement('span');
      status.className = 'console-badge '
        + (provider.last_error ? 'tone-ink' : provider.generated_at && !provider.is_stale && !provider.running ? 'tone-ok' : 'tone-muted');
      const ageText = typeof provider.age_days === 'number' ? ' · ' + provider.age_days.toFixed(1) + 'd' : '';
      status.textContent = provider.running ? '运行中'
        : provider.last_error ? '失败'
        : provider.is_stale ? '过期' + ageText
        : provider.generated_at ? '新鲜'
        : '未生成';
      status.title = formatDynamicStamp(provider);
      top.appendChild(title);
      top.appendChild(status);
      card.appendChild(top);

      // 数据龄已并入右上徽章，meta 行只留生成时间。
      const meta = document.createElement('div');
      meta.className = 'console-dynamic-meta';
      meta.textContent = provider.generated_at || '尚未生成';
      card.appendChild(meta);

      if (provider.summary) {
        const summary = document.createElement('div');
        summary.className = 'console-dynamic-summary';
        summary.textContent = provider.summary;
        card.appendChild(summary);
      }
      const sources = Array.isArray(provider.sources) ? provider.sources.filter((source) => source && source.name) : [];
      if (sources.length) {
        const sourceLine = document.createElement('div');
        sourceLine.className = 'console-dynamic-sources';
        let firstText = true;
        sources.slice(0, 4).forEach((source) => {
          const asOf = String(source.as_of || 'unknown');
          if (asOf.startsWith('/')) {
            sourceLine.appendChild(makeDynamicSourceRef(source.name, asOf));
          } else {
            const text = document.createElement('span');
            text.textContent = (firstText ? '' : ' · ') + source.name + ': ' + asOf;
            sourceLine.appendChild(text);
            firstText = false;
          }
        });
        card.appendChild(sourceLine);
      }
      if (provider.last_error) {
        const error = document.createElement('div');
        error.className = 'console-dynamic-error';
        error.textContent = provider.last_error;
        card.appendChild(error);
      }

      const actions = document.createElement('div');
      actions.className = 'console-dynamic-actions';
      const refreshProvider = opts.refreshProvider || provider;
      const refresh = document.createElement('button');
      refresh.type = 'button';
      refresh.className = 'console-dynamic-btn';
      refresh.textContent = provider.running ? '运行中' : '刷新';
      refresh.disabled = provider.running || !ctx.hasApi;
      refresh.title = refreshProvider.title || refreshProvider.id || '刷新';
      refresh.onclick = async () => {
        refresh.disabled = true;
        refresh.textContent = '刷新中';
        const result = ctx.api && ctx.api.runDynamicBoard ? await ctx.api.runDynamicBoard(refreshProvider.id) : { ok: false };
        if (result.ok) {
          toast((refreshProvider.title || refreshProvider.id) + ' 已刷新');
          if (ctx.api && ctx.api.refresh) await ctx.api.refresh();
        }
        if (onRefreshDone) onRefreshDone();
      };
      const open = document.createElement('button');
      open.type = 'button';
      open.className = 'console-dynamic-btn';
      open.textContent = '打开';
      open.disabled = !(provider.artifacts && provider.artifacts.output_exists && provider.artifacts.output_path);
      open.onclick = () => ctx.api.openInEditor(provider.artifacts.output_path);
      actions.appendChild(refresh);
      actions.appendChild(open);
      if (opts.showCopy !== false) {
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'console-dynamic-btn';
        copyBtn.textContent = provider.id === 'governance-probe' ? '复制评审' : '复制 skill';
        copyBtn.onclick = () => copyTextToClipboard(dynamicPromptFor(provider), copyBtn.textContent + '指令已复制');
        actions.appendChild(copyBtn);
      }
      card.appendChild(actions);
      return card;
    }

  // KAN-979：内容逐字相同的 provider 卡合并为一张（同 summary+generated_at+sources）。
  // 纯展示合并：合并后仍是一份数据源信息 + 一行动作；「刷新」指向组内生成器（id 含 today），
  // 数据端点与 provider 语义不变。
  function dedupeDynamicProviders(providers) {
      const groups = [];
      const byKey = new Map();
      providers.forEach((provider) => {
        const key = JSON.stringify([
          provider.summary || '',
          provider.generated_at || '',
          provider.sources || [],
        ]);
        if (byKey.has(key)) {
          byKey.get(key).members.push(provider);
          return;
        }
        const group = { primary: provider, members: [provider] };
        byKey.set(key, group);
        groups.push(group);
      });
      return groups.map((group) => ({
        primary: group.primary,
        refreshProvider: group.members.find((p) => /today|generate/i.test(String(p.id || ''))) || group.primary,
      }));
    }

  Object.assign(board, {
    consoleAiSet,
    currentPerson,
    consoleAudienceMode,
    consoleAudienceIsAttentionGate,
    currentBoardViews,
    markConsoleAudience,
    appendIfNode,
    dutySourcePath,
    openDutySource,
    markDutySource,
    makeDutySourceButton,
    dutyShortStamp,
    dutyText,
    decorateConsoleCard,
    consoleCardTypeLabel,
    appendConsoleTaskCard,
    appendConsoleLaneAfter,
    makeConsoleLane,
    makeConsoleFoldedTaskSection,
    makeConsoleCursorBar,
    scrollConsoleSectionIntoView,
    openConsoleDrawer,
    makeConsoleDrawer,
    makeConsoleAgentWorkContent,
    isDueNow,
    sortConsoleTodayTasks,
    makeConsoleSummaryLane,
    teamKanbanBaseUrl,
    teamKanbanAutologinUrl,
    openTeamKanbanUrl,
    makeTeamDigestDegraded,
    makeTeamDigestEntry,
    makeTeamDigestBlock,
    makeTeamPointerBlock,
    makeTeamCoordinationPanel,
    copyTextToClipboard,
    openConsoleLandingTask,
    queueLandingAction,
    makeConsoleLandingRow,
    makeConsoleLandingPanel,
    dynamicPromptFor,
    formatDynamicStamp,
    dynamicTone,
    makeDynamicSourceRef,
    makeDynamicProviderCard,
    dedupeDynamicProviders
  });
  return board;
 }
