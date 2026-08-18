// KAN-1671: mounted by main.js; dependencies arrive through ctx.renderDetailInternal.
export function setupRenderDetailActions(ctx) {
  const detail = ctx.renderDetailInternal;
  if (!detail) throw new Error('setupRenderDetail(ctx) must run first');
  const { uiState, ui } = ctx;
  const { detailProps, aiActivity, aiActivityList } = ctx.el;
  const { toast } = ui;
  const shouldRenderNextStepRelay = (...args) => detail.shouldRenderNextStepRelay(...args);
  const activitySourceHistoryModel = (...args) => detail.activitySourceHistoryModel(...args);
  const syncEditModeUI = (...args) => detail.syncEditModeUI(...args);
  const _detailSidebarState = (...args) => detail._detailSidebarState(...args);
  const setSidebarTab = (...args) => detail.setSidebarTab(...args);
  const setSidebarFolded = (...args) => detail.setSidebarFolded(...args);
  const _shortText = (...args) => detail._shortText(...args);
  const _safeExternalCommentUrl = (...args) => detail._safeExternalCommentUrl(...args);
  const _formatExternalCommentTime = (...args) => detail._formatExternalCommentTime(...args);
  const _externalCommentView = (...args) => detail._externalCommentView(...args);
  const _mergeConcurrentComment = (...args) => detail._mergeConcurrentComment(...args);
  const _externalEditButton = (...args) => detail._externalEditButton(...args);
  const _jumpToExternalCommentSource = (...args) => detail._jumpToExternalCommentSource(...args);
  const loadTaskComments = (...args) => detail.loadTaskComments(...args);
  const jumpToCommentAnchor = (...args) => detail.jumpToCommentAnchor(...args);
  const refreshCommentSidebarAvailability = (...args) => detail.refreshCommentSidebarAvailability(...args);
  const renderCommentSidebar = (...args) => detail.renderCommentSidebar(...args);
  const normalizeDuplicateCommentAnchors = (...args) => detail.normalizeDuplicateCommentAnchors(...args);
  const openCommentSidebar = (...args) => detail.openCommentSidebar(...args);
  const destroyDetailDuePicker = (...args) => detail.destroyDetailDuePicker(...args);
  const restoreCurrentTaskLocation = (...args) => detail.restoreCurrentTaskLocation(...args);
  const updateEditorStatus = (...args) => detail.updateEditorStatus(...args);
  const _blockTrailer = (...args) => detail._blockTrailer(...args);
  const _renderDetailBlock = (...args) => detail._renderDetailBlock(...args);
  const _renderTaskBodyBlocks = (...args) => detail._renderTaskBodyBlocks(...args);
  const _restoreInlineEditor = (...args) => detail._restoreInlineEditor(...args);
  const _persistInlineBody = (...args) => detail._persistInlineBody(...args);
  const commitInlineBlockEdit = (...args) => detail.commitInlineBlockEdit(...args);
  const deleteInlineBlock = (...args) => detail.deleteInlineBlock(...args);
  const _autosizeInlineEditor = (...args) => detail._autosizeInlineEditor(...args);
  const enterInlineBlockEdit = (...args) => detail.enterInlineBlockEdit(...args);
  const closeDetail = (...args) => detail.closeDetail(...args);
  const _openDetail = (...args) => detail._openDetail(...args);
  const openTaskDetail = (...args) => detail.openTaskDetail(...args);
  const openTaskDetailByCode = (...args) => detail.openTaskDetailByCode(...args);
  const updateDetailField = (...args) => detail.updateDetailField(...args);
  const archiveCurrentTask = (...args) => detail.archiveCurrentTask(...args);
  const openDetailDuePicker = (...args) => detail.openDetailDuePicker(...args);
  const extractAcceptanceSection = (...args) => detail.extractAcceptanceSection(...args);
  const stripAcceptanceSection = (...args) => detail.stripAcceptanceSection(...args);
  const parseAcceptanceChecks = (...args) => detail.parseAcceptanceChecks(...args);
  const refreshCurrentDetailTask = (...args) => detail.refreshCurrentDetailTask(...args);
  const bindAcceptanceCheckboxes = (...args) => detail.bindAcceptanceCheckboxes(...args);
  const renderAcceptanceEditor = (...args) => detail.renderAcceptanceEditor(...args);
  const prependAcceptanceBlock = (...args) => detail.prependAcceptanceBlock(...args);
  const stripCardNoteSection = (...args) => detail.stripCardNoteSection(...args);
  const prependCardNoteBlock = (...args) => detail.prependCardNoteBlock(...args);
  const enterEditMode = (...args) => detail.enterEditMode(...args);
  const exitEditMode = (...args) => detail.exitEditMode(...args);
  const saveBody = (...args) => detail.saveBody(...args);
  const checkHashAndOpenDetail = (...args) => detail.checkHashAndOpenDetail(...args);
  const bindEvents = (...args) => detail.bindEvents(...args);
  function teamHandoffInfo(task) {
    const promotedTo = String((task && task.promoted_to) || '').trim();
    const status = String((task && task.team_handoff_status) || '').trim();
    const url = String((task && task.team_handoff_url) || (task && task.remote_url) || '').trim();
    const source = String((task && task.source) || '').trim();
    const storedTeamPath = String((task && task.team_path) || '').trim();
    let urlTeamPath = '';
    if (url) {
      try {
        const parsed = new URL(url);
        const marker = '/blob/main/';
        const markerIndex = parsed.pathname.indexOf(marker);
        if (markerIndex >= 0) {
          urlTeamPath = decodeURIComponent(parsed.pathname.slice(markerIndex + marker.length));
        }
      } catch (e) {
        urlTeamPath = '';
      }
    }
    const teamPath = promotedTo.startsWith('team-workspace/')
      ? promotedTo.slice('team-workspace/'.length)
      : (promotedTo || storedTeamPath || urlTeamPath);
    return {
      status,
      promotedTo,
      teamPath,
      url,
      source,
      nextAction: String((task && task.next_action) || '').trim(),
      isPointer: source.startsWith('team-kanban/'),
      isComplete: ['pushed', 'written'].includes(status) && (Boolean(teamPath) || Boolean(url)),
    };
  }

  function handoffStatusLabel(status) {
    const labels = {
      pushed: '已推送团队远端',
      written: '已写入团队仓',
      draft: '已生成本地草稿',
      'publish-blocked': '发布阻塞',
    };
    return labels[status] || status || '未发起';
  }

  function appendTeamHandoffStatus(task) {
    const info = teamHandoffInfo(task);
    const shouldShow = info.status || info.promotedTo || info.url || info.isPointer;
    if (!shouldShow) return;
    const card = document.createElement('section');
    card.className = 'detail-handoff-status-card';

    const title = document.createElement('div');
    title.className = 'detail-handoff-title';
    title.textContent = info.isPointer ? '团队回流指针' : '团队交接状态';
    card.appendChild(title);

    const summary = document.createElement('div');
    summary.className = 'detail-handoff-summary';
    summary.textContent = info.isPointer
      ? '这是团队看板同步回来的只读指针，真实状态以团队卡为准。'
      : (info.isComplete
        ? '这张个人卡已经完成团队交接，后续不要重复推送。'
        : '这张个人卡已有团队交接记录，请根据状态继续处理。');
    card.appendChild(summary);

    const rows = [
      ['状态', info.isPointer ? (task.status || 'todo') : handoffStatusLabel(info.status)],
      [
        '团队卡位置',
        info.teamPath || (info.isPointer ? '未解析，请以远端链接和指针来源 ID 为准' : ''),
      ],
      [info.isPointer ? '指针来源 ID' : '来源', info.isPointer ? info.source : ''],
      ['远端链接', info.url || ''],
      ['下一步', info.nextAction || ''],
    ].filter(([, value]) => value);
    if (rows.length) {
      const meta = document.createElement('div');
      meta.className = 'detail-handoff-meta';
      rows.forEach(([label, value]) => {
        const item = document.createElement('span');
        item.textContent = label + ': ' + value;
        meta.appendChild(item);
      });
      card.appendChild(meta);
    }

    if (info.url) {
      const actions = document.createElement('div');
      actions.className = 'detail-handoff-actions';
      const link = document.createElement('a');
      link.className = 'detail-relay-btn primary detail-handoff-link-btn';
      link.href = info.url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = '打开团队卡';
      actions.appendChild(link);
      card.appendChild(actions);
    }
    detailProps.appendChild(card);
  }

  function isDateAfter(left, right) {
    const leftDate = new Date(left);
    const rightDate = new Date(right);
    if (Number.isNaN(leftDate.getTime()) || Number.isNaN(rightDate.getTime())) return false;
    return leftDate > rightDate;
  }

  function copyTextWithFallback(text, successMessage) {
    const value = String(text || '');
    if (!value) return;
    const fallback = () => {
      const ta = document.createElement('textarea');
      ta.value = value;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      toast(successMessage);
    };
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      navigator.clipboard.writeText(value).then(() => toast(successMessage)).catch(fallback);
    } else {
      fallback();
    }
  }

  function appendLandingPropRow(card, label, value, onOpen) {
    const row = document.createElement('div');
    row.className = 'detail-prop-row';
    const lbl = document.createElement('span');
    lbl.className = 'detail-prop-label';
    lbl.textContent = label;
    row.appendChild(lbl);
    const val = document.createElement('span');
    val.className = 'detail-prop-static';
    val.textContent = value || '-';
    if (onOpen && value) {
      val.className += ' detail-prop-clickable';
      val.title = '点击打开: ' + value;
      val.tabIndex = 0;
      val.onclick = onOpen;
      val.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
        }
      };
    }
    row.appendChild(val);
    card.appendChild(row);
  }

  function appendLandingAiPlaceholder(runId, task) {
    if (!ctx.ai || typeof ctx.ai.createThreadCard !== 'function') return;
    aiActivity.style.display = 'block';
    const entry = ctx.ai.createThreadCard({
      run_id: runId,
      tool: 'codex',
      path: task.path,
      status: 'queued',
      timestamp: new Date().toISOString().slice(0, 19),
      messages: []
    });
    aiActivityList.insertBefore(entry, aiActivityList.firstChild);
  }

  function appendLandingPageStatus(task) {
    const landingPage = String((task && task.landing_page) || '').trim();
    if (!landingPage) return;
    const card = document.createElement('section');
    card.className = 'detail-handoff-status-card detail-landing-status-card';

    const title = document.createElement('div');
    title.className = 'detail-handoff-title';
    title.textContent = '项目状态页';
    card.appendChild(title);

    appendLandingPropRow(card, '路径', landingPage, () => ctx.api.openInEditor(landingPage));
    appendLandingPropRow(card, '刷新', task.landing_updated || '', null);

    if (isDateAfter(task.updated, task.landing_updated)) {
      const warning = document.createElement('div');
      warning.className = 'detail-landing-warning';
      warning.textContent = '状态页落后于任务卡，可能需刷新';
      card.appendChild(warning);
    }

    const actions = document.createElement('div');
    actions.className = 'detail-handoff-actions';

    const openBtn = document.createElement('button');
    openBtn.type = 'button';
    openBtn.className = 'detail-relay-btn primary';
    openBtn.textContent = '打开';
    openBtn.onclick = () => ctx.api.openInEditor(landingPage);
    actions.appendChild(openBtn);

    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'detail-relay-btn';
    copyBtn.textContent = '复制路径';
    copyBtn.onclick = () => copyTextWithFallback(landingPage, '已复制路径');
    actions.appendChild(copyBtn);

    const reviewBtn = document.createElement('button');
    reviewBtn.type = 'button';
    reviewBtn.className = 'detail-relay-btn';
    reviewBtn.textContent = 'AI校验';
    reviewBtn.onclick = async () => {
      if (!ctx.hasApi) {
        toast('静态模式：请使用 --serve 启动交互服务器', true);
        return;
      }
      reviewBtn.disabled = true;
      reviewBtn.textContent = '校验中...';
      try {
        const { json } = await ctx.api.apiJson('/api/landing/review', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ path: task.path })
        });
        if (!json.ok) {
          reviewBtn.disabled = false;
          reviewBtn.textContent = 'AI校验';
          toast(json.error || '状态页校验失败', true);
          return;
        }
        const runId = json.run_id;
        toast('状态页校验已加入 Codex 队列');
        appendLandingAiPlaceholder(runId, task);
        if (ctx.ai && typeof ctx.ai.startQueueBadgePolling === 'function') ctx.ai.startQueueBadgePolling();
        if (ctx.ai && typeof ctx.ai.startPolling === 'function') {
          ctx.ai.startPolling(runId, task.path, {
            onDone: (entry) => {
              reviewBtn.disabled = false;
              reviewBtn.textContent = 'AI校验';
              if (entry.status === 'completed') {
                toast('状态页校验完成，请查看 AI 结果');
                return;
              }
              toast(entry.error || '状态页校验未完成', true);
            }
          });
        } else {
          reviewBtn.disabled = false;
          reviewBtn.textContent = 'AI校验';
        }
      } catch (e) {
        reviewBtn.disabled = false;
        reviewBtn.textContent = 'AI校验';
        toast('网络错误', true);
      }
    };
    actions.appendChild(reviewBtn);

    const refreshBtn = document.createElement('button');
    refreshBtn.type = 'button';
    refreshBtn.className = 'detail-relay-btn';
    refreshBtn.textContent = '更新';
    refreshBtn.onclick = async () => {
      if (!ctx.hasApi) {
        toast('静态模式：请使用 --serve 启动交互服务器', true);
        return;
      }
      refreshBtn.disabled = true;
      refreshBtn.textContent = '更新中...';
      try {
        const { json } = await ctx.api.apiJson('/api/landing/refresh', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ path: task.path })
        });
        if (!json.ok) {
          refreshBtn.disabled = false;
          refreshBtn.textContent = '更新';
          toast(json.error || '状态页刷新失败', true);
          return;
        }
        const runId = json.run_id;
        toast('状态页刷新已加入 Codex 队列');
        appendLandingAiPlaceholder(runId, task);
        if (ctx.ai && typeof ctx.ai.startQueueBadgePolling === 'function') ctx.ai.startQueueBadgePolling();
        if (ctx.ai && typeof ctx.ai.startPolling === 'function') {
          ctx.ai.startPolling(runId, task.path, {
            onDone: async (entry) => {
              if (entry.status === 'completed') {
                await refreshCurrentDetailTask(task.path);
                toast('状态页已更新');
                return;
              }
              refreshBtn.disabled = false;
              refreshBtn.textContent = '更新';
              toast(entry.error || '状态页刷新未完成', true);
            }
          });
        }
      } catch (e) {
        refreshBtn.disabled = false;
        refreshBtn.textContent = '更新';
        toast('网络错误', true);
      }
    };
    actions.appendChild(refreshBtn);

    card.appendChild(actions);
    detailProps.appendChild(card);
  }

  function lineageLabel(event) {
    const labels = {
      card_created: '建卡',
      frontmatter_changed: '字段变更',
      ai_run_queued: 'AI 派单',
      ai_fork_queued: '分叉派单',
      ai_comment_added: '评论',
      ai_run_completed: 'AI 完成',
      ai_run_finished: 'AI 结束',
      ai_session_captured: '会话记录',
      canvas_source_bound: '画布绑定',
      card_archived: '归档',
      pilot_backfill: '试点回填'
    };
    return labels[event] || event || '记录';
  }

  function factKindLabel(kind) {
    const labels = {
      canvas: '画布',
      lineage: '血缘',
      comment: '评论'
    };
    return labels[kind] || kind || '记录';
  }

  function lineageMeta(entry) {
    const parts = [];
    if (entry.ts) parts.push(entry.ts);
    if (entry.actor) parts.push(entry.actor);
    if (entry.kind) parts.push(factKindLabel(entry.kind));
    if (entry.field) parts.push(entry.field);
    if (entry.run_id) parts.push('run ' + entry.run_id);
    if (entry.session_id) parts.push('session ' + entry.session_id);
    if (entry.thread_id) parts.push('thread ' + entry.thread_id);
    if (entry.parent_entry_id) parts.push('parent ' + entry.parent_entry_id);
    return parts.join(' · ');
  }

  function appendActivitySourceHistory(task) {
    if (!task || !task.task_id || !ctx.hasApi) return;
    const history = document.createElement('details');
    history.className = 'detail-activity-history';
    history.hidden = true;

    const trigger = document.createElement('summary');
    trigger.className = 'detail-activity-history-trigger';
    const label = document.createElement('span');
    label.className = 'detail-activity-history-label';
    label.textContent = '活动与来源';
    trigger.appendChild(label);
    const countBadge = document.createElement('span');
    countBadge.className = 'detail-activity-history-count';
    trigger.appendChild(countBadge);
    const chevron = document.createElement('span');
    chevron.className = 'detail-activity-history-chevron';
    chevron.textContent = '⌄';
    chevron.setAttribute('aria-hidden', 'true');
    trigger.appendChild(chevron);
    history.appendChild(trigger);

    const body = document.createElement('div');
    body.className = 'detail-activity-history-body';
    const sourceSummary = document.createElement('div');
    sourceSummary.className = 'detail-activity-history-sources';
    body.appendChild(sourceSummary);

    const list = document.createElement('ul');
    list.className = 'detail-handoff-list detail-lineage-list';
    body.appendChild(list);
    history.appendChild(body);
    detailProps.appendChild(history);

    void (async () => {
      try {
        const { json } = await ctx.api.apiJson('/api/ledger/' + encodeURIComponent(task.task_id));
        const model = activitySourceHistoryModel(json);
        if (!model || !history.isConnected) return;
        countBadge.textContent = String(model.count);
        trigger.setAttribute('aria-label', '活动与来源，' + model.count + ' 条记录');
        sourceSummary.textContent = '画布 ' + model.sourceCounts.canvas
          + ' · 血缘 ' + model.sourceCounts.lineage
          + ' · 评论 ' + model.sourceCounts.comments;
        model.recent.forEach((entry) => {
          const item = document.createElement('li');
          const name = document.createElement('strong');
          name.textContent = factKindLabel(entry.kind) + ' · ' + lineageLabel(entry.event);
          item.appendChild(name);
          const meta = document.createElement('div');
          meta.className = 'detail-lineage-meta';
          meta.textContent = lineageMeta(entry.raw || entry);
          item.appendChild(meta);
          if (entry.summary) {
            const desc = document.createElement('div');
            desc.className = 'detail-lineage-meta';
            desc.textContent = entry.summary;
            item.appendChild(desc);
          }
          list.appendChild(item);
        });
        history.hidden = false;
      } catch (_) {
        // 审计入口是次级信息；读取失败时保持隐藏，不制造新的告警噪音。
      }
    })();
  }

  function projectFromTask(task) {
    if (task.project) return task.project;
    const parts = (task.path || '').split('/').filter(Boolean);
    return parts.length >= 2 ? parts[parts.length - 2] : '';
  }

  function childTaskBody(task) {
    const taskId = task.task_id || task.title || '当前任务';
    return `## 背景 / 来源
- 来源：基于 ${taskId} 派生
- 为什么现在做：补齐下一步可执行工作。

## 要做什么
（一句话目标 + 明确动作）

## 输入与材料
- workdir:
- 入口文件 / 链接:
- 约束 / 不要碰:

## 完成标准
- [ ] 输出物明确
- [ ] 验证方式明确
- [ ] 执行结果与验证证据已回填

## 执行结果
待回填。`;
  }

  async function deriveChildTask(task) {
    if (!ctx.hasApi) return;
    const project = projectFromTask(task);
    if (!project) {
      toast('无法识别当前项目', true);
      return;
    }
    const defaultTitle = (task.title || task.task_id || '任务') + ' - 子任务';
    const title = (prompt('请输入子任务标题', defaultTitle) || '').trim();
    if (!title) {
      toast('请输入子任务标题', true);
      return;
    }
    try {
      const { json } = await ctx.api.apiJson('/api/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          project,
          title,
          assignee: task.assignee || uiState.auth.currentUser || '',
          priority: task.priority || 'medium',
          body: childTaskBody(task),
          promoted_from: task.task_id || ''
        })
      });
      if (!json.ok) {
        toast(json.message || '创建子任务失败', true);
        return;
      }
      await ctx.api.refresh();
      if (json.task_id) {
        await openTaskDetailByCode(json.task_id);
      } else if (json.message) {
        await openTaskDetail(json.message);
      }
      toast('已创建子任务');
    } catch (e) {
      toast('网络错误', true);
    }
  }

  function appendNextStepRelay(task) {
    if (!shouldRenderNextStepRelay(task)) return;
    const relay = document.createElement('section');
    relay.className = 'detail-relay';
    const title = document.createElement('div');
    title.className = 'detail-relay-title';
    title.textContent = '下一步接力';
    relay.appendChild(title);

    const actions = document.createElement('div');
    actions.className = 'detail-relay-actions';

    const childBtn = document.createElement('button');
    childBtn.type = 'button';
    childBtn.className = 'detail-relay-btn primary';
    childBtn.textContent = '派生子任务';
    childBtn.onclick = () => deriveChildTask(task);
    actions.appendChild(childBtn);

    relay.appendChild(actions);

    detailProps.appendChild(relay);
  }

  function appendDangerZone(task) {
    const zone = document.createElement('div');
    zone.className = 'detail-danger-zone';
    const title = document.createElement('div');
    title.className = 'detail-danger-title';
    title.textContent = '危险区';
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'detail-delete-btn';
    deleteBtn.textContent = '删除任务卡';
    deleteBtn.title = '归档到所在项目 .archive/';
    deleteBtn.onclick = () => archiveCurrentTask(task, deleteBtn);
    zone.appendChild(title);
    zone.appendChild(deleteBtn);
    detailProps.appendChild(zone);
  }


  Object.assign(detail, { teamHandoffInfo, handoffStatusLabel, appendTeamHandoffStatus, isDateAfter, copyTextWithFallback, appendLandingPropRow, appendLandingAiPlaceholder, appendLandingPageStatus, lineageLabel, factKindLabel, lineageMeta, appendActivitySourceHistory, projectFromTask, childTaskBody, deriveChildTask, appendNextStepRelay, appendDangerZone });
  return detail;
}
