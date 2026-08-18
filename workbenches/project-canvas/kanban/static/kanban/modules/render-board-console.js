// KAN-1600: mounted by main.js; dependencies arrive through ctx.renderBoardInternal.
export function setupRenderBoardConsole(ctx) {
  const board = ctx.renderBoardInternal;
  if (!board) throw new Error("setupRenderBoard(ctx) must run first");
  const { dataState, uiState, toast, PRI_ORDER, VIEWS, VL, CONSOLE_AUDIENCE_OWNER, CONSOLE_AUDIENCE_ATTENTION_GATE } = board;
  const projectPostureModel = (...args) => board.projectPostureModel(...args);
  const consoleProjectRailModel = (...args) => board.consoleProjectRailModel(...args);
  const automationResultLinks = (...args) => board.automationResultLinks(...args);
  const automationResultSummary = (...args) => board.automationResultSummary(...args);
  const ownerActionNeeded = (...args) => board.ownerActionNeeded(...args);
  const isAiProxyReviewTask = (...args) => board.isAiProxyReviewTask(...args);
  const isGateInFlightTask = (...args) => board.isGateInFlightTask(...args);
  const consoleTaskStatus = (...args) => board.consoleTaskStatus(...args);
  const isConsoleRecordTask = (...args) => board.isConsoleRecordTask(...args);
  const isConsoleRecordExceptionTask = (...args) => board.isConsoleRecordExceptionTask(...args);
  const isConsoleOwnerDecisionTask = (...args) => board.isConsoleOwnerDecisionTask(...args);
  const isTeamKanbanPointerTask = (...args) => board.isTeamKanbanPointerTask(...args);
  const isPinnedTeamKanbanPointerTask = (...args) => board.isPinnedTeamKanbanPointerTask(...args);
  const consoleTaskRoutingLane = (...args) => board.consoleTaskRoutingLane(...args);
  const isConsoleGlobalDispatchTask = (...args) => board.isConsoleGlobalDispatchTask(...args);
  const isConsoleCanvasTask = (...args) => board.isConsoleCanvasTask(...args);
  const consoleRecentAiDoneTasks = (...args) => board.consoleRecentAiDoneTasks(...args);
  const isGovernanceBurdenTask = (...args) => board.isGovernanceBurdenTask(...args);
  const isGovernanceConsoleHiddenTask = (...args) => board.isGovernanceConsoleHiddenTask(...args);
  const isGovernanceHumanGateTask = (...args) => board.isGovernanceHumanGateTask(...args);
  const isGovernanceMachineCheckableTask = (...args) => board.isGovernanceMachineCheckableTask(...args);
  const isGovernanceAiReducibleTask = (...args) => board.isGovernanceAiReducibleTask(...args);
  const buildGovernanceBurdenModel = (...args) => board.buildGovernanceBurdenModel(...args);
  const searchTasks = (...args) => board.searchTasks(...args);
  const consoleTeamDigestEntries = (...args) => board.consoleTeamDigestEntries(...args);
  const sortTasks = (...args) => board.sortTasks(...args);
  const getFilteredTasks = (...args) => board.getFilteredTasks(...args);
  const switchView = (...args) => board.switchView(...args);
  const initTabs = (...args) => board.initTabs(...args);
  const renderStats = (...args) => board.renderStats(...args);
  const createCardEl = (...args) => board.createCardEl(...args);
  const renderKanban = (...args) => board.renderKanban(...args);
  const openChainFlow = (...args) => board.openChainFlow(...args);
  const makeChainFlowDetailBlock = (...args) => board.makeChainFlowDetailBlock(...args);
  const runGovernanceNoiseReview = (...args) => board.runGovernanceNoiseReview(...args);
  const makeGovernanceHealthcheckStatusBlock = (...args) => board.makeGovernanceHealthcheckStatusBlock(...args);
  const makeGovernanceNoiseStatusBlock = (...args) => board.makeGovernanceNoiseStatusBlock(...args);
  const ensureAttentionGateDutyLoaded = (...args) => board.ensureAttentionGateDutyLoaded(...args);
  const makeAttentionGateDutyPanel = (...args) => board.makeAttentionGateDutyPanel(...args);
  const renderTeam = (...args) => board.renderTeam(...args);
  const renderPipeline = (...args) => board.renderPipeline(...args);
  const consoleAiSet = (...args) => board.consoleAiSet(...args);
  const currentPerson = (...args) => board.currentPerson(...args);
  const consoleAudienceIsAttentionGate = (...args) => board.consoleAudienceIsAttentionGate(...args);
  const markConsoleAudience = (...args) => board.markConsoleAudience(...args);
  const makeDutySourceButton = (...args) => board.makeDutySourceButton(...args);
  const makeConsoleLane = (...args) => board.makeConsoleLane(...args);
  const makeConsoleCursorBar = (...args) => board.makeConsoleCursorBar(...args);
  const scrollConsoleSectionIntoView = (...args) => board.scrollConsoleSectionIntoView(...args);
  const openConsoleDrawer = (...args) => board.openConsoleDrawer(...args);
  const makeConsoleDrawer = (...args) => board.makeConsoleDrawer(...args);
  const makeConsoleAgentWorkContent = (...args) => board.makeConsoleAgentWorkContent(...args);
  const isDueNow = (...args) => board.isDueNow(...args);
  const sortConsoleTodayTasks = (...args) => board.sortConsoleTodayTasks(...args);
  const makeTeamCoordinationPanel = (...args) => board.makeTeamCoordinationPanel(...args);
  const makeSkillStateDecisionLane = (...args) => board.makeSkillStateDecisionLane(...args);
  const renderGovernanceMatrix = (...args) => board.renderGovernanceMatrix(...args);

  function makeProjectPostureStrip() {
    const model = projectPostureModel(dataState.project_posture);
    if (!model.ok) return null;

    const section = document.createElement('section');
    section.className = 'console-project-posture';
    section.setAttribute('aria-label', '项目态势');

    const lead = document.createElement('div');
    lead.className = 'console-project-posture-lead';
    const kicker = document.createElement('span');
    kicker.className = 'console-project-posture-kicker';
    kicker.textContent = '项目态势';
    const headline = document.createElement('strong');
    headline.textContent = model.counts.needsOwner
      ? `${model.counts.needsOwner} 个项目需要你介入`
      : '当前没有项目需要你介入';
    const summary = document.createElement('span');
    summary.className = 'console-project-posture-summary';
    const summaryParts = [
      `${model.counts.quietActive} 个静默运行`,
      model.counts.paused ? `${model.counts.paused} 个暂停` : '',
      `${model.counts.completed} 个已完成`,
    ].filter(Boolean);
    summary.textContent = summaryParts.join(' · ');
    lead.appendChild(kicker);
    lead.appendChild(headline);
    lead.appendChild(summary);

    const metrics = document.createElement('div');
    metrics.className = 'console-project-posture-metrics';
    [
      ['需介入', model.counts.needsOwner, model.counts.needsOwner ? 'attention' : ''],
      ['静默运行', model.counts.quietActive, ''],
      ['已完成', model.counts.completed, ''],
    ].forEach(([label, count, tone]) => {
      const metric = document.createElement('div');
      metric.className = 'console-project-posture-metric' + (tone ? ` is-${tone}` : '');
      const value = document.createElement('strong');
      value.textContent = count;
      const name = document.createElement('span');
      name.textContent = label;
      metric.appendChild(value);
      metric.appendChild(name);
      metrics.appendChild(metric);
    });

    section.appendChild(lead);
    section.appendChild(metrics);

    if (model.counts.pendingChanges) {
      const pending = document.createElement('span');
      pending.className = 'console-project-posture-pending';
      pending.textContent = `${model.counts.pendingChanges} 项事实变化待确认`;
      section.appendChild(pending);
    }

    if (model.attention.length) {
      const list = document.createElement('div');
      list.className = 'console-project-attention-list';
      model.attention.forEach((project) => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'console-project-attention-item';
        const copy = document.createElement('span');
        copy.className = 'console-project-attention-copy';
        const title = document.createElement('strong');
        title.textContent = project.title || project.project_ref || '未命名项目';
        const gatedIds = (project.attention_signals && project.attention_signals.gated_card_ids) || [];
        const actionSummary = String((project.primary_action && project.primary_action.summary) || '').trim();
        const reason = document.createElement('span');
        reason.textContent = gatedIds.length
          ? `有卡等你 · ${gatedIds.join('/')}`
          : (actionSummary || '需要你介入');
        copy.appendChild(title);
        copy.appendChild(reason);
        const cue = document.createElement('span');
        cue.className = 'console-project-attention-cue';
        cue.textContent = '打开项目 →';
        item.appendChild(copy);
        item.appendChild(cue);
        item.onclick = () => {
          if (ctx.realProjects && typeof ctx.realProjects.open === 'function') ctx.realProjects.open(project.project_ref);
        };
        list.appendChild(item);
      });
      section.appendChild(list);
    }

    return section;
  }

  function renderConsole() {
    const el = document.getElementById('vw-console');
    if (!el) return;
    el.innerHTML = '';
    el.classList.add('console-shell');
    const recordExceptions = sortTasks((dataState.tasks || []).filter((task) => isConsoleRecordExceptionTask(task)));
    const active = (dataState.tasks || []).filter((t) => t.status !== 'done' && !isConsoleRecordTask(t));
    const person = currentPerson();
    const attention_gateMode = consoleAudienceIsAttentionGate();
    const teamPointers = sortTasks(active.filter((task) => isTeamKanbanPointerTask(task)));
    const consoleActive = active.filter((task) => {
      const governanceBurden = isGovernanceBurdenTask(task);
      const ownerDecision = isConsoleOwnerDecisionTask(task, person);
      return (
        (!governanceBurden || (!attention_gateMode && ownerDecision))
        && (!isTeamKanbanPointerTask(task) || isPinnedTeamKanbanPointerTask(task))
      );
    });
    const aiMembers = consoleAiSet();
    const routingLane = (task) => consoleTaskRoutingLane(task, person, aiMembers);
    const globalConsoleActive = consoleActive.filter((task) => {
      const lane = routingLane(task);
      return isConsoleGlobalDispatchTask(task, lane, { dueNow: isDueNow(task) });
    });
    const inbox = sortConsoleTodayTasks(globalConsoleActive.filter((task) => routingLane(task) === 'triage'));
    const decisions = sortConsoleTodayTasks(globalConsoleActive.filter((task) => routingLane(task) === 'decision'));
    const needsMe = sortTasks(globalConsoleActive.filter((task) => routingLane(task) === 'review'));
    const canvasTasks = sortTasks(active.filter((task) => isConsoleCanvasTask(task)));
    const today = sortConsoleTodayTasks(globalConsoleActive.filter((task) => routingLane(task) === 'today'));
    const aiWork = sortTasks(globalConsoleActive.filter((task) => routingLane(task) === 'ai-work'));
    const waiting = sortConsoleTodayTasks(globalConsoleActive.filter((task) => routingLane(task) === 'waiting'));
    const parked = sortTasks(globalConsoleActive.filter((task) => routingLane(task) === 'parked'));
    const recentAiDone = uiState.filters.hideDone ? [] : consoleRecentAiDoneTasks(dataState.tasks || [], aiMembers)
      .filter((task) => !isGovernanceConsoleHiddenTask(task));
    const recentAiDoneSet = new Set(recentAiDone);
    const unrouted = sortConsoleTodayTasks(globalConsoleActive.filter((task) => routingLane(task) === 'unrouted'));
    const recentDone = (dataState.tasks || [])
      .filter((task) => (
        consoleTaskStatus(task) === 'done'
        && !isConsoleRecordTask(task)
        && !isTeamKanbanPointerTask(task)
        && !isGovernanceConsoleHiddenTask(task)
        && !recentAiDoneSet.has(task)
      ))
      .sort((a, b) => String(b.updated || '').localeCompare(String(a.updated || '')))
      .slice(0, 6);
    const teamDigestEntries = consoleTeamDigestEntries(dataState.team_digest, 8);

    const app = document.createElement('div');
    app.className = 'console-app';

    const makeProjectRail = () => {
      const rail = document.createElement('aside');
      rail.className = 'console-project-rail';
      rail.setAttribute('aria-label', '项目');
      const head = document.createElement('div');
      head.className = 'console-project-rail-head';
      const heading = document.createElement('strong');
      heading.textContent = '项目';
      const model = consoleProjectRailModel(dataState.real_projects);
      const count = document.createElement('span');
      count.textContent = String(model.length);
      head.appendChild(heading);
      head.appendChild(count);
      rail.appendChild(head);

      const create = document.createElement('button');
      create.type = 'button';
      create.className = 'console-project-create';
      create.textContent = '＋ 新建项目';
      create.onclick = () => ctx.realProjects?.openCreate();
      rail.appendChild(create);

      const list = document.createElement('nav');
      list.className = 'console-project-list';
      list.setAttribute('aria-label', '已登记项目');
      if (!dataState.real_projects?.ok) {
        const empty = document.createElement('p');
        empty.className = 'console-project-empty';
        empty.textContent = '项目注册表暂不可用';
        list.appendChild(empty);
      } else if (!model.length) {
        const empty = document.createElement('p');
        empty.className = 'console-project-empty';
        empty.textContent = '还没有项目';
        list.appendChild(empty);
      } else {
        model.forEach((project) => {
          const row = document.createElement('button');
          row.type = 'button';
          row.className = `console-project-row tone-${project.tone}`;
          row.onclick = () => ctx.realProjects?.open(project.projectRef);
          const dot = document.createElement('span');
          dot.className = 'console-project-dot';
          dot.setAttribute('aria-hidden', 'true');
          const copy = document.createElement('span');
          copy.className = 'console-project-copy';
          const title = document.createElement('strong');
          title.textContent = project.title;
          const meta = document.createElement('small');
          meta.textContent = `${project.label}${project.activeTasks ? ` · ${project.activeTasks} 项进行中` : ''}`;
          copy.appendChild(title);
          copy.appendChild(meta);
          row.appendChild(dot);
          row.appendChild(copy);
          list.appendChild(row);
        });
      }
      rail.appendChild(list);

      return rail;
    };

    const workspace = document.createElement('div');
    workspace.className = 'console-workspace';
    const dispatchSurface = document.createElement('div');
    dispatchSurface.className = 'console-dispatch-surface';
    // KAN-203 头部收敛：删「我的调度台」大标题块及副题行、大黑「+派活」按钮；
    // 内容区第一行 = 盘面条（左）+「+派活」描边小按钮（右）；身份/视角移交顶栏。
    const dispatch = document.createElement('button');
    dispatch.type = 'button';
    dispatch.className = 'console-dispatch-btn';
    dispatch.textContent = '+ 派活';
    markConsoleAudience(dispatch, CONSOLE_AUDIENCE_OWNER);
    dispatch.onclick = () => {
      if (ctx.openNewTaskModal) ctx.openNewTaskModal();
    };

    // KAN-199 主列 = 动作序单流。Owner 视角只显示显式人闸；人闸视角只显示真正缺归属的待分流卡。
    // source、标题关键词、safety 与空 assignee 都不能单独制造 Owner 债。
    const decisionDigest = attention_gateMode ? inbox : decisions;
    const drawerInbox = attention_gateMode ? [] : inbox;

    // 极简盘面条只保留四个动作入口；等待、异常和其他索引留在下方折叠区。
    const pendingCount = decisionDigest.length + drawerInbox.length;
    const cursorBar = makeConsoleCursorBar([
      { label: '待分流', count: pendingCount, onClick: () => decisionDigest.length ? scrollConsoleSectionIntoView('console-sec-decide') : openConsoleDrawer('console-drawer-inbox') },
      { label: '我现在做', count: today.length, onClick: () => scrollConsoleSectionIntoView('console-sec-today') },
      { label: 'Agent 执行', count: aiWork.length, onClick: () => openConsoleDrawer('console-drawer-aiwork') },
      { label: '等我验收', count: needsMe.length, onClick: () => scrollConsoleSectionIntoView('console-sec-review') },
    ]);
    // 「+派活」描边小按钮并入盘面条右侧（内容区第一行）。
    const dispatchWrap = document.createElement('div');
    dispatchWrap.className = 'console-cursor-actions';
    dispatchWrap.appendChild(dispatch);
    cursorBar.appendChild(dispatchWrap);

    const wrap = document.createElement('div');
    wrap.className = 'console-grid is-minimal';
    const main = document.createElement('div');
    main.className = 'console-main';
    wrap.appendChild(main);
    dispatchSurface.appendChild(cursorBar);
    dispatchSurface.appendChild(wrap);
    workspace.appendChild(makeProjectRail());
    workspace.appendChild(dispatchSurface);
    app.appendChild(workspace);
    el.appendChild(app);

    // ── 主列：动作序单流（拍板 → 验收 → 必做），无类型泳道分组标题 ──
    if (decisionDigest.length) {
      main.appendChild(makeConsoleLane(
        attention_gateMode ? '待分流 · 责任未定' : '待分流 / 待拍板',
        decisionDigest,
        'inbox',
        false,
        { audience: attention_gateMode ? CONSOLE_AUDIENCE_ATTENTION_GATE : CONSOLE_AUDIENCE_OWNER, anchorId: 'console-sec-decide', foldAfter: 4 }
      ));
    }
    main.appendChild(makeSkillStateDecisionLane());
    main.appendChild(makeConsoleLane('我现在做', today, 'today', false, {
      audience: CONSOLE_AUDIENCE_OWNER,
      anchorId: 'console-sec-today',
      foldAfter: 4,
    }));
    // 「等我验收」超过 3 张时尾部折叠成「其余 N 张」展开。
    main.appendChild(makeConsoleLane('等我验收', needsMe, 'attention', true, {
      audience: CONSOLE_AUDIENCE_OWNER,
      anchorId: 'console-sec-review',
      foldAfter: 3,
    }));
    // KAN-1001：值守面板搬进治理页「人闸值守」段（断言主干+折叠明细），调度台主列不再渲染。

    // ── 后台区：执行状态、异常、索引三层分开，禁止把功能标签伪装成任务泳道 ──
    const drawerWrap = document.createElement('section');
    drawerWrap.className = 'console-backstage';
    const makeBackstageCluster = (title, description, tone = '') => {
      const section = document.createElement('section');
      section.className = 'console-backstage-cluster' + (tone ? ` is-${tone}` : '');
      const head = document.createElement('div');
      head.className = 'console-backstage-head';
      const heading = document.createElement('h3');
      heading.textContent = title;
      const hint = document.createElement('p');
      hint.textContent = description;
      head.appendChild(heading);
      head.appendChild(hint);
      const grid = document.createElement('div');
      grid.className = 'console-backstage-grid';
      section.appendChild(head);
      section.appendChild(grid);
      drawerWrap.appendChild(section);
      return { section, head, grid };
    };
    const addBackstageDrawer = (cluster, drawer, variant = '') => {
      if (!drawer) return;
      if (variant) drawer.classList.add(`is-${variant}`);
      cluster.grid.appendChild(drawer);
    };

    const executionCluster = (aiWork.length || waiting.length)
      ? makeBackstageCluster('Agent 协作', '按执行者查看进行中工作；阻塞与外部等待单独显示')
      : null;
    if (executionCluster && aiWork.length) {
      addBackstageDrawer(executionCluster, makeConsoleDrawer('console-drawer-aiwork', '按 Agent 查看', aiWork, {
        audience: CONSOLE_AUDIENCE_OWNER,
        content: makeConsoleAgentWorkContent(aiWork),
      }), 'execution');
    }
    if (executionCluster && waiting.length) {
      addBackstageDrawer(executionCluster, makeConsoleDrawer('console-drawer-waiting', '等待外部 / 前置依赖', waiting, {
        audience: CONSOLE_AUDIENCE_OWNER,
      }), 'waiting');
    }

    const drawerInboxItems = attention_gateMode ? [] : drawerInbox;
    const exceptionCluster = (recordExceptions.length || drawerInboxItems.length || unrouted.length)
      ? makeBackstageCluster('后台异常', '只有责任或运行状态不完整的卡才进入这里', 'alert')
      : null;
    if (recordExceptions.length) {
      const exceptionDrawer = makeConsoleDrawer(
        'console-drawer-record-errors',
        '记录异常',
        recordExceptions,
        { audience: CONSOLE_AUDIENCE_ATTENTION_GATE }
      );
      exceptionDrawer.open = true;
      addBackstageDrawer(exceptionCluster, exceptionDrawer, 'alert');
    }
    if (drawerInboxItems.length) {
      addBackstageDrawer(exceptionCluster, makeConsoleDrawer('console-drawer-inbox', '责任待分流', drawerInboxItems, {
        audience: CONSOLE_AUDIENCE_OWNER,
      }), 'alert');
    }
    if (attention_gateMode && unrouted.length) {
      addBackstageDrawer(exceptionCluster, makeConsoleDrawer('console-drawer-unrouted', '路由异常', unrouted, {
        audience: CONSOLE_AUDIENCE_ATTENTION_GATE,
        cardOptions: { unrouted: true },
      }), 'alert');
    }

    const recentHistory = [...recentAiDone, ...recentDone]
      .sort((a, b) => String(b.updated || '').localeCompare(String(a.updated || '')))
      .slice(0, 6);
    const divertedGov = active.filter((task) => isGovernanceBurdenTask(task)).length;
    const recordCount = (dataState.tasks || []).filter((t) => t.status !== 'done' && isConsoleRecordTask(t)).length;
    const pointerCount = teamPointers.length;
    const hasReferenceItems = (
      (attention_gateMode && canvasTasks.length)
      || (attention_gateMode && parked.length)
      || teamPointers.length
      || teamDigestEntries.length
      || (attention_gateMode && !uiState.filters.hideDone && recentHistory.length)
      || (attention_gateMode && (divertedGov || recordCount || pointerCount))
    );
    const referenceCluster = hasReferenceItems
      ? makeBackstageCluster('索引与回看', '功能标记、停放项和历史只作检索，不重复计算工作量', 'reference')
      : null;
    if (referenceCluster && attention_gateMode && canvasTasks.length) {
      addBackstageDrawer(referenceCluster, makeConsoleDrawer('console-drawer-canvas', '画布标记', canvasTasks, {
        audience: CONSOLE_AUDIENCE_ATTENTION_GATE,
      }), 'reference');
    }
    if (referenceCluster && attention_gateMode && parked.length) {
      addBackstageDrawer(referenceCluster, makeConsoleDrawer('console-drawer-parked', '稍后 / 停放', parked, {
        audience: CONSOLE_AUDIENCE_ATTENTION_GATE,
      }), 'reference');
    }
    if (teamPointers.length || teamDigestEntries.length) {
      addBackstageDrawer(referenceCluster, makeConsoleDrawer('console-drawer-team', '团队来源', teamPointers, {
        audience: CONSOLE_AUDIENCE_OWNER,
        countOverride: teamDigestEntries.length + teamPointers.length,
        content: makeTeamCoordinationPanel(dataState.team_digest, teamPointers),
      }), 'reference');
    }
    if (referenceCluster && attention_gateMode && !uiState.filters.hideDone && recentHistory.length) {
      addBackstageDrawer(referenceCluster, makeConsoleDrawer('console-drawer-donelog', '最近完成', recentHistory, {
        audience: CONSOLE_AUDIENCE_ATTENTION_GATE,
      }), 'reference');
    }
    if (referenceCluster && attention_gateMode && (divertedGov || recordCount || pointerCount)) {
        const note = document.createElement('div');
        note.className = 'console-diversion-note';
        markConsoleAudience(note, CONSOLE_AUDIENCE_ATTENTION_GATE);
        const prefix = document.createElement('span');
        prefix.textContent = '分流账';
        note.appendChild(prefix);
        if (divertedGov) {
          const govCount = document.createElement('span');
          govCount.textContent = `治理 ${divertedGov}`;
          note.appendChild(govCount);
        }
        if (recordCount) {
          const records = document.createElement('span');
          records.textContent = `记录 ${recordCount}`;
          note.appendChild(records);
        }
        if (pointerCount) {
          const pointers = document.createElement('span');
          pointers.textContent = `团队指针 ${pointerCount}`;
          note.appendChild(pointers);
        }
        referenceCluster.section.appendChild(note);
    }
    if (drawerWrap.childElementCount) main.appendChild(drawerWrap);

  }

  function renderAll() {
    switchView(uiState.board.activeView);
    renderStats();
    if (uiState.board.activeView === 'projects' && ctx.realProjects && typeof ctx.realProjects.render === 'function') {
      ctx.realProjects.render();
    }
    renderConsole();
    if (ctx.ai && uiState.queue.data) {
      ctx.ai.renderQueueSidebar();
      ctx.ai.updateQueueBadge();
    }
  }

  Object.assign(board, {
    makeProjectPostureStrip,
    renderConsole,
    renderAll
  });

  initTabs();

  ctx.renderBoard = {
    PRI_ORDER,
    VIEWS,
    VL,
    automationResultLinks,
    automationResultSummary,
    sortTasks,
    getFilteredTasks,
    switchView,
    renderStats,
    createCardEl,
    renderConsole,
    searchTasks,
    renderKanban,
    renderTeam,
    renderPipeline,
    openChainFlow,
    renderAll,
    // KAN-998：治理顶层视图（render-governance.js）经 ctx 取用的能力面——不跨模块 import，
    // 分类器/统计/运行状态/矩阵/维护动作全在此暴露，render-governance 只负责决策流排版。
    governance: {
      model: () => buildGovernanceBurdenModel(dataState.tasks || [], Array.from(consoleAiSet()), currentPerson()),
      activeTasks: () => (dataState.tasks || [])
        .filter(isGovernanceBurdenTask)
        .sort((a, b) => {
          const gateDelta = Number(isGovernanceHumanGateTask(b, currentPerson())) - Number(isGovernanceHumanGateTask(a, currentPerson()));
          if (gateDelta) return gateDelta;
          return String(b.updated || b.created || '').localeCompare(String(a.updated || a.created || ''));
        }),
      // KAN-999：「等 Owner 动作」一本账判定族，治理视图顶段直接消费。
      ownerActionNeeded: (task) => ownerActionNeeded(task, currentPerson()),
      isAiProxyReview: (task) => isAiProxyReviewTask(task),
      isGateInFlight: (task) => isGateInFlightTask(task),
      isHumanGate: (task) => isGovernanceHumanGateTask(task, currentPerson()),
      isMachineCheckable: (task) => isGovernanceMachineCheckableTask(task),
      isAiReducible: (task) => isGovernanceAiReducibleTask(task, Array.from(consoleAiSet()), currentPerson()),
      makeHealthcheckStatusBlock: () => makeGovernanceHealthcheckStatusBlock(),
      makeNoiseStatusBlock: () => makeGovernanceNoiseStatusBlock(),
      runNoiseReview: (button) => runGovernanceNoiseReview(button),
      renderMatrix: (mount) => renderGovernanceMatrix(mount),
      // KAN-1002：Flow 详情块迁治理页，链行点击=页内展开（治理页已单独渲染矩阵，故关掉 gov 链内嵌矩阵）。
      makeChainFlowDetailBlock: () => makeChainFlowDetailBlock({ includeGovMatrix: false }),
      // KAN-1001：人闸值守并入治理页——数据管线与原四块渲染整体复用，主干断言由 render-governance 收口。
      dutyState: () => uiState.attention_gateDuty || {},
      ensureDutyLoaded: () => ensureAttentionGateDutyLoaded(),
      makeDutyPanel: () => makeAttentionGateDutyPanel(),
      makeDutySourceButton: (ref) => makeDutySourceButton(ref),
      openDecisionLog: () => {
        if (ctx.api && ctx.api.openInEditor) ctx.api.openInEditor('shared/toolkit/governance/DECISION_LOG.md');
        else toast('静态模式不可打开文件', true);
      },
      openTaskDetail: (path) => {
        if (ctx.renderDetail && ctx.renderDetail.openTaskDetail) ctx.renderDetail.openTaskDetail(path);
      },
    },
  };

  return ctx.renderBoard;
 }
