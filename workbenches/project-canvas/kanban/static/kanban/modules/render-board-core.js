// KAN-1600: mounted by main.js; dependencies arrive through ctx.renderBoardInternal.
export function setupRenderBoardCore(ctx) {
  const board = ctx.renderBoardInternal;
  if (!board) throw new Error("setupRenderBoard(ctx) must run first");
  const { dataState, uiState, dom, STATUS, SL, PL, isMobile, dueDateText, makeDd, makeMemberDd, toast, PRI_ORDER, VIEWS, TAB_VIEWS, VL, chainStageSelection, TASK_DOMAIN_LABELS, CHAIN_FLOW_NODE_MIN_WIDTH, CHAIN_FLOW_NODE_GAP } = board;
  const taskTagsText = (...args) => board.taskTagsText(...args);
  const normalizeFrontendChains = (...args) => board.normalizeFrontendChains(...args);
  const chainHealthScore = (...args) => board.chainHealthScore(...args);
  const buildChainStageBuckets = (...args) => board.buildChainStageBuckets(...args);
  const isConsoleReviewTask = (...args) => board.isConsoleReviewTask(...args);
  const governanceHealthcheckToastText = (...args) => board.governanceHealthcheckToastText(...args);
  const governanceHealthcheckScheduleItem = (...args) => board.governanceHealthcheckScheduleItem(...args);
  const governanceHealthcheckStatusText = (...args) => board.governanceHealthcheckStatusText(...args);
  const governanceHealthcheckStatusTone = (...args) => board.governanceHealthcheckStatusTone(...args);
  const governanceHealthcheckRunStatusText = (...args) => board.governanceHealthcheckRunStatusText(...args);
  const governanceHealthcheckRunStatusTone = (...args) => board.governanceHealthcheckRunStatusTone(...args);
  const governanceNoiseReviewStatusText = (...args) => board.governanceNoiseReviewStatusText(...args);
  const governanceNoiseReviewStatusTone = (...args) => board.governanceNoiseReviewStatusTone(...args);
  const governanceShortStamp = (...args) => board.governanceShortStamp(...args);
  const currentPerson = (...args) => board.currentPerson(...args);
  const currentBoardViews = (...args) => board.currentBoardViews(...args);
  const chainStateCached = (...args) => board.chainStateCached(...args);
  const requestChainState = (...args) => board.requestChainState(...args);
  const skillStateStageData = (...args) => board.skillStateStageData(...args);
  const makeSkillStateBlock = (...args) => board.makeSkillStateBlock(...args);
  const makeChainStagePanel = (...args) => board.makeChainStagePanel(...args);
  const renderGovernanceMatrix = (...args) => board.renderGovernanceMatrix(...args);
  const renderConsole = (...args) => board.renderConsole(...args);

  function sortTasks(tasks) {
    return [...tasks].sort((a, b) => {
      const pa = PRI_ORDER[a.priority] ?? 1;
      const pb = PRI_ORDER[b.priority] ?? 1;
      if (pa !== pb) return pa - pb;
      return (b.created || '').localeCompare(a.created || '');
    });
  }

  function getFilteredTasks() {
    let tasks = dataState.tasks || [];
    if (uiState.filters.mine && uiState.auth.currentUser) {
      tasks = tasks.filter((task) => task.assignee === uiState.auth.currentUser);
    }
    if (uiState.filters.hideDone) {
      tasks = tasks.filter((task) => task.status !== 'done');
    }
    return sortTasks(tasks);
  }

  function normalizeText(value) {
    return String(value || '').toLowerCase();
  }

  function textOfTask(task) {
    return normalizeText([
      task.title,
      task.display_title,
      task.task_id,
      task.project,
      task.workdir,
      task.path,
      task.next_action,
      task.scenario_slug,
      taskTagsText(task.tags),
    ].filter(Boolean).join(' '));
  }

  function inferTaskDomain(task) {
    if (task.domain) return task.domain;
    const text = textOfTask(task);
    const tags = normalizeText(taskTagsText(task.tags));
    if ((task.project || '') === '场景库运营' || task.scenario_slug || tags.includes('场景库') || tags.includes('scenario')) return 'scenario';
    if (text.includes('shape-of-thought') || text.includes('team-workspace') || text.includes('handoff-team')) return 'team';
    if (text.includes('knowledgemanagement') || text.includes('zotero') || text.includes('stork') || text.includes('sih') || tags.includes('km')) return 'knowledge';
    if (text.includes('researchlab') || text.includes('researchprojects') || tags.includes('research') || tags.includes('科研')) return 'research';
    if (tags.includes('governance') || tags.includes('security') || text.includes('治理') || text.includes('scan_governance')) return 'governance';
    return 'personal';
  }

  function updateBoardShellBrand() {
    const brand = document.querySelector('.hdr-brand-copy strong');
    if (brand) brand.textContent = 'Project Canvas';
  }

  function switchView(view) {
    const allowedViews = currentBoardViews();
    if (!VIEWS.includes(view) || !allowedViews.includes(view)) view = 'projects';
    updateBoardShellBrand();
    uiState.board.activeView = view;
    dom.tabs.querySelectorAll('.tab').forEach((tab) => {
      const visible = allowedViews.includes(tab.dataset.v);
      tab.hidden = !visible;
      tab.classList.toggle('on', visible && tab.dataset.v === view);
    });
    dom.views.querySelectorAll('.vw').forEach((panel) => {
      const panelView = String(panel.id || '').replace(/^vw-/, '');
      const visible = allowedViews.includes(panelView);
      panel.hidden = !visible;
      panel.classList.toggle('on', visible && panel.id === 'vw-' + view);
    });
    if (view === 'projects' && ctx.realProjects && typeof ctx.realProjects.render === 'function') {
      ctx.realProjects.render();
    }
    // KAN-998：治理视图由独立模块 render-governance.js 渲染（经 ctx 挂载，不跨模块 import）。
    if (view === 'governance' && ctx.renderGovernance && typeof ctx.renderGovernance.render === 'function') {
      ctx.renderGovernance.render();
    }
  }

  function initTabs() {
    const allowedViews = currentBoardViews();
    if (!allowedViews.includes(uiState.board.activeView)) uiState.board.activeView = 'projects';
    updateBoardShellBrand();
    dom.tabs.classList.toggle('is-single', TAB_VIEWS.length === 1);
    if (dom.tabs.dataset.ready === 'true') return;
    TAB_VIEWS.forEach((view) => {
      const tab = document.createElement('div');
      tab.className = 'tab' + (view === uiState.board.activeView ? ' on' : '');
      tab.textContent = VL[view];
      tab.dataset.v = view;
      tab.hidden = !allowedViews.includes(view);
      tab.onclick = () => switchView(view);
      dom.tabs.appendChild(tab);
    });
    VIEWS.forEach((view) => {
      const panel = document.createElement('div');
      panel.className = 'vw' + (view === uiState.board.activeView ? ' on' : '');
      panel.id = 'vw-' + view;
      panel.hidden = !allowedViews.includes(view);
      dom.views.appendChild(panel);
    });
    dom.tabs.dataset.ready = 'true';
  }

  function renderStats() {
    if (dom.overflowClock) {
      let clockText = '更新于 ' + (dataState.generated_at || '--');
      const version = dataState.server_version;
      if (version && typeof version === 'object') {
        const sha = String(version.git_sha || '').trim();
        if (sha) clockText += ' · ' + sha;
      }
      dom.overflowClock.textContent = clockText;
      const codeMtime = version && typeof version === 'object' ? String(version.code_mtime || '') : '';
      const startedAt = version && typeof version === 'object' ? String(version.started_at || '') : '';
      dom.overflowClock.title = `mtime=${codeMtime || '-'} started=${startedAt || '-'}`;
    }
    // KAN-203：顶栏删除「任务/项目/活跃」三个计数 pill（数字墙）。hdr-summary 清空不再渲染。
    if (dom.hdrSummary) dom.hdrSummary.innerHTML = '';
    dom.stats.innerHTML = '';
  }

  // KAN-200：验收人徽标（灰字，无彩色）+ 人闸打回标记。
  function appendAcceptanceBadges(task, meta) {
    const acceptedBy = String((task && task.accepted_by) || '').trim().toLowerCase();
    if (acceptedBy === 'owner' || acceptedBy === 'attention_gate') {
      const badge = document.createElement('span');
      badge.className = 'b b-accepted-by';
      badge.textContent = acceptedBy === 'owner' ? '✓ Owner 验收' : '✓ 人闸代收';
      const at = String((task && task.accepted_at) || '').trim();
      badge.title = (acceptedBy === 'owner' ? 'Owner 手动验收' : '人闸超时真 review 后代收')
        + (at ? '：' + at : '');
      meta.appendChild(badge);
    }
    const flag = String((task && task.acceptance_flag) || '').trim().toLowerCase();
    if (flag === 'attention_gate-rejected') {
      const rej = document.createElement('span');
      rej.className = 'b b-accept-rejected';
      rej.textContent = '⚑ 人闸打回';
      rej.title = '人闸真 review 未通过，留在 review 等 Owner（详情见卡片正文「人闸 review 意见」）';
      meta.appendChild(rej);
    }
  }

  function createCardEl(task) {
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('div');
    title.className = 't';
    title.textContent = task.display_title || task.title || task.issue || task.filename;
    title.style.cursor = 'pointer';
    title.onclick = (e) => {
      e.stopPropagation();
      ctx.renderDetail.openTaskDetail(task.path);
    };
    card.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'm';
    meta.appendChild(makeDd(PL, task.priority || 'medium', async (value) => {
      if (await ctx.api.apiUpdate(task.path, 'priority', value)) {
        task.priority = value;
        ctx.api.refresh();
      }
    }));
    if (task.project) {
      const proj = document.createElement('span');
      proj.className = 'b b-proj';
      proj.textContent = task.project;
      meta.appendChild(proj);
    }
    const domain = inferTaskDomain(task);
    if (domain && domain !== 'personal') {
      const domainBadge = document.createElement('span');
      domainBadge.className = 'b b-domain b-domain-' + domain;
      domainBadge.textContent = TASK_DOMAIN_LABELS[domain] || domain;
      meta.appendChild(domainBadge);
    }
    if (task.source) {
      const src = document.createElement('span');
      src.className = 'b b-source';
      src.textContent = '⇣ ' + String(task.source).split('/')[0];
      src.title = '来源 feeder: ' + task.source;
      meta.appendChild(src);
    }
    appendAcceptanceBadges(task, meta);
    if (task.scenario_slug) {
      const scen = document.createElement('a');
      scen.className = 'b b-scenario';
      scen.textContent = '↗ 场景';
      scen.title = '打开关联场景：' + task.scenario_slug;
      scen.href = 'http://localhost:3000/solutions/' + encodeURIComponent(task.scenario_slug);
      scen.target = '_blank';
      scen.rel = 'noopener';
      scen.style.cssText = 'text-decoration:none;cursor:pointer';
      scen.onclick = (e) => e.stopPropagation();
      meta.appendChild(scen);
    }
    meta.appendChild(makeMemberDd(task.assignee, dataState.all_members || dataState.members, async (value) => {
      if (await ctx.api.apiUpdate(task.path, 'assignee', value)) {
        task.assignee = value;
        ctx.api.refresh();
      }
    }));
    const dueMeta = dueDateText(task.due_date, task.status);
    if (dueMeta) {
      const due = document.createElement('span');
      due.className = 'due' + (dueMeta.overdue ? ' overdue' : '');
      due.textContent = dueMeta.text;
      meta.appendChild(due);
    }
    card.appendChild(meta);

    const path = document.createElement('div');
    path.className = 'p';
    path.textContent = task.path;
    path.onclick = () => ctx.api.openInEditor(task.path);
    card.appendChild(path);

    return card;
  }

  function renderKanban() {
    const el = document.getElementById('vw-kanban');
    el.innerHTML = '';
    const filtered = getFilteredTasks();
    const grouped = {};
    STATUS.forEach((status) => { grouped[status] = []; });
    filtered.forEach((task) => {
      const status = task.status || 'todo';
      if (!grouped[status]) grouped[status] = [];
      grouped[status].push(task);
    });

    if (isMobile()) {
      const filterBar = document.createElement('div');
      filterBar.className = 'mobile-filter-bar';
      STATUS.forEach((status) => {
        const pill = document.createElement('span');
        pill.className = 'mobile-filter-pill';
        const count = (grouped[status] || []).length;
        pill.innerHTML = SL[status] + ' <span style="font-family:var(--mono);font-size:10px">' + count + '</span>';
        pill.onclick = () => {
          const target = el.querySelector('[data-status="' + status + '"]');
          if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        };
        filterBar.appendChild(pill);
      });
      el.appendChild(filterBar);

      const board = document.createElement('div');
      board.className = 'board';
      STATUS.forEach((status) => {
        const items = grouped[status] || [];
        const col = document.createElement('div');
        col.className = 'col' + (items.length ? ' expanded' : '');
        col.dataset.status = status;
        const hd = document.createElement('div');
        hd.className = 'col-hd';
        const label = document.createElement('span');
        label.textContent = SL[status];
        const cnt = document.createElement('span');
        cnt.className = 'cnt';
        cnt.textContent = items.length;
        const ei = document.createElement('span');
        ei.className = 'expand-icon';
        ei.textContent = '\u25B6';
        hd.appendChild(label);
        hd.appendChild(cnt);
        hd.appendChild(ei);
        hd.onclick = () => col.classList.toggle('expanded');
        col.appendChild(hd);
        const bd = document.createElement('div');
        bd.className = 'col-bd';
        items.forEach((task) => bd.appendChild(createCardEl(task)));
        if (!items.length) {
          const empty = document.createElement('div');
          empty.style.cssText = 'color:var(--dim);font-size:12px;text-align:center;padding:20px';
          empty.textContent = '暂无';
          bd.appendChild(empty);
        }
        col.appendChild(bd);
        board.appendChild(col);
      });
      el.appendChild(board);
      return;
    }

    const board = document.createElement('div');
    board.className = 'board';
    STATUS.forEach((status) => {
      const items = grouped[status] || [];
      const col = document.createElement('div');
      col.className = 'col';
      const hd = document.createElement('div');
      hd.className = 'col-hd';
      const label = document.createElement('span');
      label.textContent = SL[status];
      const cnt = document.createElement('span');
      cnt.className = 'cnt';
      cnt.textContent = items.length;
      hd.appendChild(label);
      hd.appendChild(cnt);
      col.appendChild(hd);
      const bd = document.createElement('div');
      bd.className = 'col-bd';
      items.forEach((task) => bd.appendChild(createCardEl(task)));
      if (!items.length) {
        const empty = document.createElement('div');
        empty.style.cssText = 'color:var(--dim);font-size:12px;text-align:center;padding:20px';
        empty.textContent = '暂无';
        bd.appendChild(empty);
      }
      col.appendChild(bd);
      board.appendChild(col);
    });
    el.appendChild(board);
  }

  async function updateTaskStatus(task, value) {
    if (!ctx.hasApi) return;
    try {
      const { json } = await ctx.api.apiJson('/api/update', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ path: task.path, field: 'status', value })
      });
      if (json.ok) {
        task.status = value;
        if (ctx.ai) ctx.ai.syncCurrentTaskStatusForPath(task.path, value);
        ctx.api.refresh();
        if (json.killed_entries && json.killed_entries.length > 0) {
          toast('任务已完成，已自动终止 AI 进程');
        } else {
          toast('已更新: ' + SL[value]);
        }
      } else {
        toast(json.message || '更新失败', true);
      }
    } catch (e) {
      toast('网络错误', true);
    }
  }

  function statusCount(items, status) {
    return items.filter((task) => (task.status || 'todo') === status).length;
  }

  function consoleReviewCount(items, person = currentPerson()) {
    return items.filter((task) => isConsoleReviewTask(task, person)).length;
  }

  function makeOverviewMetric(value, label) {
    const item = document.createElement('div');
    item.className = 'proj-overview-metric';
    const n = document.createElement('div');
    n.className = 'proj-overview-n';
    n.textContent = value;
    const l = document.createElement('div');
    l.className = 'proj-overview-l';
    l.textContent = label;
    item.appendChild(n);
    item.appendChild(l);
    return item;
  }

  function makeOverviewSection(title, body) {
    const sec = document.createElement('div');
    sec.className = 'proj-overview-block';
    const h = document.createElement('div');
    h.className = 'proj-overview-block-title';
    h.textContent = title;
    const content = document.createElement('div');
    content.className = 'proj-overview-block-body';
    if (typeof body === 'string') {
      content.textContent = body;
    } else {
      content.appendChild(body);
    }
    sec.appendChild(h);
    sec.appendChild(content);
    return sec;
  }

  function makeProgressSummary(items) {
    const byAssignee = {};
    items.forEach((task) => {
      const assignee = task.assignee || '未分配';
      if (!byAssignee[assignee]) byAssignee[assignee] = { total: 0, doing: 0, review: 0, done: 0 };
      byAssignee[assignee].total += 1;
      if (task.status === 'in-progress') byAssignee[assignee].doing += 1;
      if (task.status === 'review') byAssignee[assignee].review += 1;
      if (task.status === 'done') byAssignee[assignee].done += 1;
    });
    const list = document.createElement('div');
    list.className = 'proj-progress-list';
    Object.entries(byAssignee).sort().forEach(([assignee, counts]) => {
      const row = document.createElement('div');
      row.className = 'proj-progress-row';
      const name = document.createElement('span');
      name.textContent = assignee;
      const meta = document.createElement('span');
      const parts = [];
      if (counts.doing) parts.push(counts.doing + ' 进行中');
      if (counts.review) parts.push(counts.review + ' 待验收');
      if (counts.done) parts.push(counts.done + ' 已完成');
      meta.textContent = parts.length ? parts.join(' / ') : counts.total + ' 待推进';
      row.appendChild(name);
      row.appendChild(meta);
      list.appendChild(row);
    });
    if (!list.childElementCount) list.textContent = '暂无团队进展';
    return list;
  }

  function makeCoordinationSummary(items) {
    const targets = sortTasks(items);
    if (!targets.length) return '暂无需要你对接的团队任务';
    const list = document.createElement('div');
    list.className = 'proj-coordinate-list';
    targets.slice(0, 5).forEach((task) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'proj-coordinate-row';
      row.onclick = () => ctx.renderDetail.openTaskDetail(task.path);
      const title = document.createElement('span');
      title.textContent = task.display_title || task.title || task.filename;
      const meta = document.createElement('span');
      meta.textContent = (SL[task.status || 'todo'] || task.status || '待办') + ' · ' + (task.assignee || '未分配');
      row.appendChild(title);
      row.appendChild(meta);
      list.appendChild(row);
    });
    if (targets.length > 5) {
      const more = document.createElement('div');
      more.className = 'proj-coordinate-more';
      more.textContent = '另有 ' + (targets.length - 5) + ' 项需要对接';
      list.appendChild(more);
    }
    return list;
  }

  function healthChains() {
    const byKey = new Map(normalizeFrontendChains(dataState.chains).map((chain) => [chain.key, chain]));
    return ['km', 'team', 'meeting', 'content', 'gov'].map((key) => byKey.get(key)).filter(Boolean);
  }

  // KAN-1000 指针：healthTierColor / makeHealthScoreRing 已退役——Owner 拍板「分数降低成断言，
  // 分数根本没啥用」：合成分（100−四种罚分）是不可核对的渲染数，UI 一律改可证伪断言
  // （等你动作 N / 卡死 N / AI 代收中 M / 真停滞 S / 堆叠 +K，每个数可经 refs 追到具体卡）。
  // chainHealthScore 仍返回 score/tier（内部兼容与测试），只是不再渲染给 Owner。定义保留供参考。
  function healthTierColor(tier) {
    if (tier === 'good') return '#2e7d4f';
    if (tier === 'warn') return '#b26a00';
    return '#bf3535';
  }

  function makeHealthScoreRing(health) {
    const color = healthTierColor(health.tier);
    const ring = document.createElement('span');
    ring.className = 'console-project-score';
    ring.style.cssText = [
      'display:inline-flex',
      'align-items:center',
      'justify-content:center',
      'width:34px',
      'height:34px',
      'border-radius:50%',
      'border:1px solid ' + color,
      'background:conic-gradient(' + color + ' ' + Math.max(0, Math.min(100, health.score)) + '%, var(--console-line-soft) 0)',
      'font-size:10px',
      'font-weight:900',
      'color:var(--console-ink)',
    ].join(';');
    const inner = document.createElement('span');
    inner.textContent = health.score;
    inner.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:25px;height:25px;border-radius:50%;background:var(--console-surface)';
    ring.appendChild(inner);
    return ring;
  }

  function chainBottleneckText(health) {
    const bottleneck = health && health.bottleneck;
    if (!bottleneck) return '暂无链路数据';
    if (!bottleneck.activeCount) return '全链暂无活跃卡';
    return '瓶颈在 ' + bottleneck.stageTitle + ' · ' + bottleneck.reason + ' · ' + bottleneck.activeCount + ' 活跃';
  }

  function chainDecisionSummaryText(health) {
    const signals = (health && health.signals) || {};
    const waiting = Number(signals.waitingDecision) || 0;
    const blocked = Number(signals.blocked) || 0;
    if (!waiting && !blocked) return '畅通';
    // KAN-999 文案消歧：旧「N 个决策…」措辞统一改「等你动作 N」（等你拍板/验收的卡数，与人闸台账的
    // 「待 Owner 决策」= DECISION_LOG 待追认队列语义不同，不再同名）。
    return '等你动作 ' + waiting + ' · ' + blocked + ' 卡死';
  }

  // KAN-1000：从 refs（卡路径）提取短卡号列表，供 hover title 一步核对「哪几张卡」。
  function chainRefShortIds(refs, limit = 6) {
    const ids = [];
    (Array.isArray(refs) ? refs : []).forEach((ref) => {
      const base = String(ref || '').split('/').pop();
      const match = base.match(/([A-Z]+-\d+)/i);
      const id = match ? match[1] : base.replace(/\.md$/, '');
      if (id && !ids.includes(id)) ids.push(id);
    });
    if (!ids.length) return '';
    const head = ids.slice(0, limit).join(', ');
    return ids.length > limit ? head + ' +' + (ids.length - limit) : head;
  }

  // KAN-1000：链行次要断言（灰阶，有则显示）：AI 代收中 M · 真停滞 S · 堆叠 +K。
  // 全部来自 chainHealthScore 既有 signals——每个数是事实陈述（Owner 自判），不做豁免工程。
  function chainSecondaryAssertionText(health) {
    const signals = (health && health.signals) || {};
    const parts = [];
    const aiProxy = Number(signals.aiProxyReview) || 0;
    const stalled = Number(signals.stalled) || 0;
    const stackOver = Number(signals.stackOver) || 0;
    if (aiProxy > 0) parts.push('AI 代收中 ' + aiProxy);
    if (stalled > 0) parts.push('真停滞 ' + stalled);
    if (stackOver > 0) parts.push('堆叠 +' + stackOver);
    return parts.join(' · ');
  }

  // KAN-1000：hover title = 断言摘要 + 每类断言的 refs 卡号——数字到卡一步可追。
  function chainAssertionRefsTitle(health) {
    const stats = Object.values((health && health.stageStats) || {});
    const collect = (key) => stats.reduce((acc, stat) => acc.concat(stat && stat[key] ? stat[key] : []), []);
    const lines = [chainDecisionSummaryText(health) + ' · ' + chainBottleneckText(health)];
    [
      ['等你动作', collect('waitingDecisionRefs')],
      ['卡死', collect('blockedRefs')],
      ['AI 代收中', collect('aiProxyReviewRefs')],
      ['真停滞', collect('stalledRefs')],
    ].forEach(([label, refs]) => {
      const ids = chainRefShortIds(refs);
      if (ids) lines.push(label + ': ' + ids);
    });
    return lines.join('\n');
  }

  function openChainFlow(chainKey, anchorId = 'chain-flow-detail') {
    uiState.board.activeChainFlow = chainKey;
    uiState.board.chainFlowExpanded = true;
    // KAN-1002：Flow 详情块已迁治理页「自治运行的」段（项目健康一览下方），链行点击=治理页内展开，
    // 不再切回调度台（同时解决 KAN-998 遗留的跨视图跳转尾巴）。switchView 自带治理页重渲染。
    switchView('governance');
    window.setTimeout(() => {
      const target = document.getElementById(anchorId);
      if (target) target.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }, 30);
  }

  function flowStageTone(stage, stat) {
    if (!stat || !stat.active) return 'neutral';
    if (stat.blockedCount > 0) return 'error';
    if (stat.waitingDecisionCount > 0) return 'warn';
    if (stat.stalledCount > 0 || stat.stackOver > 0) return 'warn';
    return 'neutral';
  }

  function makeChainFlowStageCard(stage, items, stat, selectedKey, onSelect) {
    const active = items.filter((task) => task.status !== 'done');
    const done = items.filter((task) => task.status === 'done');
    const responsibility = String(stage.responsibility || 'shared').replace(/[^a-z-]/g, '');
    const tone = flowStageTone(stage, stat);
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'chain-stage-card chain-flow-node is-' + responsibility + ' tone-' + tone + (stage.key === selectedKey ? ' is-active' : '');
    const w = CHAIN_FLOW_NODE_MIN_WIDTH;
    card.style.cssText = 'flex:0 0 ' + w + 'px;width:' + w + 'px;min-width:' + w + 'px;height:92px;display:flex;flex-direction:column;align-items:flex-start;gap:4px;padding:8px 9px;box-sizing:border-box;text-align:left;';
    card.onclick = onSelect;
    let accent = '';
    if (stat && stat.blockedCount > 0) accent = 'var(--red)';
    else if (stat && (stat.waitingDecisionCount > 0 || stat.stackOver > 0 || stat.stalledCount > 0)) accent = 'var(--yellow)';
    if (!active.length) {
      card.style.borderStyle = 'dashed';
      card.style.opacity = '0.66';
    } else if (accent) {
      card.style.borderColor = accent;
    }
    const title = document.createElement('div');
    title.className = 'chain-stage-title';
    title.textContent = stage.title;
    title.title = stage.title;
    title.style.cssText = 'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:11px;line-height:1.25;font-weight:500;color:var(--muted);width:100%;';
    const num = document.createElement('div');
    num.className = 'chain-stage-num';
    num.textContent = active.length;
    num.style.cssText = 'margin-top:auto;font-size:22px;font-weight:600;line-height:1;color:' + (active.length ? (accent || 'var(--text)') : 'var(--color-text-faint)') + ';';
    card.appendChild(title);
    card.appendChild(num);
    return card;
  }

  // KAN-1002：Flow 详情块从「桥接与入口」抽屉迁至治理页「自治运行的」段（经治理能力面取用）。
  // options.includeGovMatrix=false 供治理页调用——治理页已单独渲染巡检矩阵，避免 gov 链展开时重复。
  function makeChainFlowDetailBlock(options = {}) {
    const includeGovMatrix = options.includeGovMatrix !== false;
    const chains = healthChains();
    if (!chains.length) return null;
    if (!uiState.board.chainFlowExpanded) return null;
    if (!uiState.board.activeChainFlow || !chains.some((chain) => chain.key === uiState.board.activeChainFlow)) {
      uiState.board.activeChainFlow = chains[0].key;
    }
    const chain = chains.find((item) => item.key === uiState.board.activeChainFlow) || chains[0];
    const chainBuckets = buildChainStageBuckets(dataState.tasks || [], chains);
    const byStage = chainBuckets.byChain[chain.key] || {};
    const health = chainHealthScore(chain, dataState.tasks || [], Date.now(), currentPerson());
    const chainState = chainStateCached(chain.key);
    const stageStats = health.stageStats || {};
    const section = document.createElement('div');
    section.className = 'console-project-health chain-section';
    section.id = 'chain-flow-detail';

    const top = document.createElement('div');
    top.className = 'console-project-row-top';
    top.style.marginBottom = '10px';
    const title = document.createElement('div');
    title.className = 'console-box-title';
    title.textContent = 'Flow · ' + (chain.title || chain.key);
    // KAN-1000：Flow 详情头右侧「score · tier」合成数退役，改次要断言（灰阶，有则显示）。
    // KAN-979 颜色语法收敛保持：红只保留给「等 Owner 动作」。
    top.appendChild(title);
    const headSecondary = chainSecondaryAssertionText(health);
    if (headSecondary) {
      const headAssert = document.createElement('span');
      headAssert.className = 'console-project-meta';
      headAssert.textContent = headSecondary;
      top.appendChild(headAssert);
    }
    section.appendChild(top);

    const summary = document.createElement('div');
    summary.className = 'console-project-meta';
    summary.style.marginBottom = '10px';
    summary.textContent = chainDecisionSummaryText(health) + ' · ' + chainBottleneckText(health);
    summary.title = chainAssertionRefsTitle(health);
    section.appendChild(summary);

    const strip = document.createElement('div');
    strip.className = 'chain-stages chain-flow-strip';
    strip.style.cssText = 'display:flex;flex-wrap:nowrap;align-items:stretch;overflow-x:auto;gap:' + CHAIN_FLOW_NODE_GAP + 'px;padding-bottom:6px;';
    const panelMount = document.createElement('div');
    panelMount.className = 'chain-stage-panel-mount';
    let selectedKey = chainStageSelection[chain.key] || (health.bottleneck && health.bottleneck.stageKey) || ((chain.stages[0] || {}).key);
    if (!chain.stages.some((stage) => stage.key === selectedKey)) selectedKey = ((chain.stages[0] || {}).key);
    const renderPanel = () => {
      panelMount.innerHTML = '';
      const stage = chain.stages.find((item) => item.key === selectedKey);
      if (!stage) return;
      panelMount.appendChild(makeChainStagePanel(stage, byStage[stage.key] || [], skillStateStageData(chainState, chain, stage.key)));
      strip.querySelectorAll('.chain-stage-card').forEach((card) => {
        card.classList.toggle('is-active', card.dataset.stageKey === selectedKey);
      });
    };
    chain.stages.forEach((stage, index) => {
      const card = makeChainFlowStageCard(stage, byStage[stage.key] || [], stageStats[stage.key], selectedKey, () => {
        selectedKey = stage.key;
        chainStageSelection[chain.key] = stage.key;
        renderPanel();
      });
      card.dataset.stageKey = stage.key;
      strip.appendChild(card);
      if (index < chain.stages.length - 1) {
        const arrow = document.createElement('span');
        arrow.textContent = '→';
        arrow.style.cssText = 'flex:0 0 auto;display:flex;align-items:center;color:var(--color-text-faint);font-size:12px;line-height:1;';
        strip.appendChild(arrow);
      }
    });
    section.appendChild(strip);
    renderPanel();
    section.appendChild(panelMount);

    const stateMount = document.createElement('div');
    stateMount.className = 'skill-state-mount';
    if (chainState) {
      stateMount.appendChild(makeSkillStateBlock(chain, chainState));
    } else if (ctx.hasApi) {
      const loading = document.createElement('div');
      loading.className = 'console-bridge-empty';
      loading.textContent = 'skill-state 读取中...';
      stateMount.appendChild(loading);
      requestChainState(chain.key, () => renderConsole());
    }
    if (stateMount.childNodes.length) section.appendChild(stateMount);

    if (chain.key === 'gov' && includeGovMatrix) {
      const govMount = document.createElement('section');
      govMount.className = 'chain-section';
      govMount.id = 'chains-governance-matrix';
      govMount.style.marginTop = '18px';
      section.appendChild(govMount);
      renderGovernanceMatrix(govMount);
    }
    return section;
  }

  function makeGovernanceBurdenMetric(value, label) {
    const item = document.createElement('div');
    item.className = 'console-gov-metric';
    const n = document.createElement('div');
    n.className = 'console-gov-metric-n';
    n.textContent = value;
    const l = document.createElement('div');
    l.className = 'console-gov-metric-l';
    l.textContent = label;
    item.appendChild(n);
    item.appendChild(l);
    return item;
  }

  async function runGovernanceNoiseReview(button) {
    if (!ctx.api || !ctx.api.governanceNoiseReview) {
      toast('静态模式不可运行治理自检', true);
      return;
    }
    const label = button ? button.querySelector('span') : null;
    const originalLabel = label ? label.textContent : '自检';
    if (button) {
      button.disabled = true;
      button.classList.add('is-running');
    }
    if (label) label.textContent = '排队中';
    try {
      const result = await ctx.api.governanceNoiseReview();
      if (result && result.ok) {
        toast((result.message || '治理自检已交给 Codex CLI') + ' · 可在 AI 队列查看');
        if (ctx.ai && typeof ctx.ai.startQueueBadgePolling === 'function') ctx.ai.startQueueBadgePolling();
        if (ctx.ai && typeof ctx.ai.openQueueSidebar === 'function') ctx.ai.openQueueSidebar('running');
        if (typeof refreshGovernanceNoiseStatus === 'function') refreshGovernanceNoiseStatus();
      }
    } finally {
      if (label) label.textContent = originalLabel;
      if (button) {
        button.disabled = false;
        button.classList.remove('is-running');
      }
      if (typeof lucide !== 'undefined') requestAnimationFrame(() => lucide.createIcons());
    }
  }

  function makeGovernanceHealthcheckStatusBlock() {
    const wrap = document.createElement('div');
    wrap.className = 'console-gov-run-status tone-muted';

    const main = document.createElement('div');
    main.className = 'console-gov-run-main';
    const label = document.createElement('span');
    label.className = 'console-gov-run-label';
    label.textContent = '最近体检';
    const status = document.createElement('span');
    status.className = 'console-gov-run-pill';
    status.textContent = '读取中';
    main.appendChild(label);
    main.appendChild(status);
    wrap.appendChild(main);

    const meta = document.createElement('div');
    meta.className = 'console-gov-run-meta';
    meta.textContent = '读取 governance_scan 最近体检记录';
    wrap.appendChild(meta);

    const actions = document.createElement('div');
    actions.className = 'console-gov-run-actions';
    const reportBtn = document.createElement('button');
    reportBtn.type = 'button';
    reportBtn.textContent = '报告';
    reportBtn.disabled = true;
    const refreshBtn = document.createElement('button');
    refreshBtn.type = 'button';
    refreshBtn.textContent = '刷新';
    actions.appendChild(reportBtn);
    actions.appendChild(refreshBtn);
    wrap.appendChild(actions);

    const applyStatus = (schedule) => {
      const latest = schedule && schedule.latest;
      if (latest || (schedule && schedule.ok === false)) {
        const tone = governanceHealthcheckRunStatusTone(schedule);
        wrap.className = 'console-gov-run-status tone-' + tone;
        wrap.hidden = false;
        status.textContent = governanceHealthcheckRunStatusText(schedule);
        const pieces = [];
        if (latest) {
          if (latest.service_restart_required) {
            pieces.push('前端已更新，当前后端仍是旧进程');
            pieces.push('重启看板后读取体检报告');
          } else {
            // KAN-979 一行状态：只留 1-2 个关键数 + 时间，全量指标进「报告」。
            if (latest.signal_count !== undefined) pieces.push('信号 ' + latest.signal_count);
            if (Number(latest.failed_command_count || 0) > 0) {
              pieces.push('失败 ' + latest.failed_command_count + '/' + latest.command_count);
            }
            const stamp = governanceShortStamp(latest.generated_at);
            if (stamp) pieces.push(stamp);
          }
        } else {
          pieces.push(schedule && schedule.error ? schedule.error : '无法读取体检状态');
        }
        meta.textContent = pieces.join(' · ') || '状态已记录';
        const reportPath = latest && latest.report_path;
        reportBtn.disabled = !(reportPath && latest.report_exists);
        reportBtn.onclick = () => {
          if (reportPath && ctx.api && ctx.api.openInEditor) ctx.api.openInEditor(reportPath);
          else toast('体检报告不可打开', true);
        };
        return;
      }
      const tone = governanceHealthcheckStatusTone(schedule);
      wrap.className = 'console-gov-run-status tone-' + tone;
      wrap.hidden = false;
      status.textContent = governanceHealthcheckStatusText(schedule);
      const item = governanceHealthcheckScheduleItem(schedule);
      if (!item) {
        meta.textContent = schedule && schedule.ok === false ? '无法读取自动化档期' : '未找到 governance_scan 自动化';
        reportBtn.disabled = true;
        return;
      }
      const pieces = [];
      if (item.reason) pieces.push(item.reason);
      if (item.last_checked) pieces.push('上次 ' + String(item.last_checked).replace('T', ' ').slice(5, 16));
      else if (item.latest_session && item.latest_session.timestamp) pieces.push('上次 ' + String(item.latest_session.timestamp).replace('T', ' ').slice(5, 16));
      if (item.next_run_at) pieces.push('下次 ' + String(item.next_run_at).replace('T', ' ').slice(5, 16));
      if (item.last_run_md || item.last_run_json) pieces.push('有运行记录');
      meta.textContent = pieces.join(' · ') || (item.schedule_label || '状态已记录');
      reportBtn.disabled = true;
    };

    const load = async (force = false) => {
      if (!ctx.api) {
        applyStatus({ ok: false });
        return;
      }
      const result = ctx.api.governanceHealthcheckStatus
        ? await ctx.api.governanceHealthcheckStatus()
        : { ok: false };
      applyStatus(result);
    };
    refreshBtn.onclick = () => load(true);
    load();
    return wrap;
  }

  function makeGovernanceNoiseStatusBlock() {
    const wrap = document.createElement('div');
    wrap.className = 'console-gov-run-status tone-muted';

    const main = document.createElement('div');
    main.className = 'console-gov-run-main';
    const label = document.createElement('span');
    label.className = 'console-gov-run-label';
    label.textContent = '最近自检';
    const status = document.createElement('span');
    status.className = 'console-gov-run-pill';
    status.textContent = '读取中';
    main.appendChild(label);
    main.appendChild(status);
    wrap.appendChild(main);

    const meta = document.createElement('div');
    meta.className = 'console-gov-run-meta';
    meta.textContent = '自检结果会进入 AI 队列和 generated 样本账本';
    wrap.appendChild(meta);

    const actions = document.createElement('div');
    actions.className = 'console-gov-run-actions';
    const queueBtn = document.createElement('button');
    queueBtn.type = 'button';
    queueBtn.textContent = 'AI 队列';
    queueBtn.onclick = () => {
      if (ctx.ai && typeof ctx.ai.openQueueSidebar === 'function') ctx.ai.openQueueSidebar();
      else toast('AI 队列不可用', true);
    };
    const refreshBtn = document.createElement('button');
    refreshBtn.type = 'button';
    refreshBtn.textContent = '刷新';
    actions.appendChild(queueBtn);
    actions.appendChild(refreshBtn);
    wrap.appendChild(actions);

    const applyStatus = (result) => {
      const tone = governanceNoiseReviewStatusTone(result);
      wrap.className = 'console-gov-run-status tone-' + tone;
      wrap.hidden = false;
      status.textContent = governanceNoiseReviewStatusText(result);
      const latest = result && result.latest;
      if (!latest) {
        meta.textContent = '尚未从治理模块运行过自检';
        return;
      }
      // KAN-979 一行状态：只留 1-2 个关键数 + 时间，其余细节在 AI 队列可查。
      const pieces = [];
      const metrics = latest.metrics || {};
      const candidateTotal = latest.metadata && latest.metadata.candidate_total !== undefined
        ? latest.metadata.candidate_total
        : metrics.candidate_total;
      const visibleBefore = metrics.owner_visible_before !== undefined
        ? metrics.owner_visible_before
        : (latest.metadata && latest.metadata.owner_visible_before);
      if (visibleBefore !== undefined && metrics.owner_visible_after !== undefined) {
        pieces.push('Owner 可见 ' + visibleBefore + '→' + metrics.owner_visible_after);
      } else {
        if (candidateTotal !== undefined) pieces.push('候选 ' + candidateTotal);
        if (metrics.owner_visible_after !== undefined) pieces.push('Owner 可见 ' + metrics.owner_visible_after);
      }
      const stamp = latest.completed_at || latest.timestamp;
      const shortStamp = governanceShortStamp(stamp);
      if (shortStamp) pieces.push(shortStamp);
      if (latest.governance_noise_record_error || latest.parse_error) pieces.push('结果回收需检查');
      meta.textContent = pieces.join(' · ') || '状态已记录';
    };

    const load = async () => {
      if (!ctx.api || !ctx.api.governanceNoiseReviewStatus) {
        applyStatus({ latest: null });
        return;
      }
      const result = await ctx.api.governanceNoiseReviewStatus();
      if (!result || !result.ok) {
        wrap.className = 'console-gov-run-status tone-bad';
        wrap.hidden = false;
        status.textContent = '读取失败';
        meta.textContent = result && result.error ? result.error : '无法读取自检状态';
        return;
      }
      applyStatus(result);
    };
    refreshBtn.onclick = load;
    refreshGovernanceNoiseStatus = load;
    load();
    return wrap;
  }

function ensureAttentionGateDutyLoaded() {
    const state = uiState.attention_gateDuty || (uiState.attention_gateDuty = {});
    if (state.loading || state.data || !ctx.api || typeof ctx.api.attention_gateDuty !== 'function') return;
    state.loading = true;
    ctx.api.attention_gateDuty().then((result) => {
      state.data = result && typeof result === 'object' ? result : { ok: false, error: 'empty response' };
      state.loadedAt = Date.now();
    }).catch(() => {
      state.data = { ok: false, error: 'network error' };
      state.loadedAt = Date.now();
    }).finally(() => {
      state.loading = false;
      if (uiState.board.activeView === 'console') renderConsole();
      // KAN-1001：值守数据也喂治理页（值守段+待追认线），数据到了刷新治理视图。
      else if (uiState.board.activeView === 'governance' && ctx.renderGovernance && typeof ctx.renderGovernance.render === 'function') {
        ctx.renderGovernance.render();
      }
    });
  }


  Object.assign(board, {
    sortTasks,
    getFilteredTasks,
    normalizeText,
    textOfTask,
    inferTaskDomain,
    updateBoardShellBrand,
    switchView,
    initTabs,
    renderStats,
    appendAcceptanceBadges,
    createCardEl,
    renderKanban,
    updateTaskStatus,
    statusCount,
    consoleReviewCount,
    makeOverviewMetric,
    makeOverviewSection,
    makeProgressSummary,
    makeCoordinationSummary,
    healthChains,
    healthTierColor,
    makeHealthScoreRing,
    chainBottleneckText,
    chainDecisionSummaryText,
    chainRefShortIds,
    chainSecondaryAssertionText,
    chainAssertionRefsTitle,
    openChainFlow,
    flowStageTone,
    makeChainFlowStageCard,
    makeChainFlowDetailBlock,
    makeGovernanceBurdenMetric,
    runGovernanceNoiseReview,
    makeGovernanceHealthcheckStatusBlock,
    makeGovernanceNoiseStatusBlock,
    ensureAttentionGateDutyLoaded
  });
  return board;
 }
