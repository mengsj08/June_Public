export function setupReviewCycle(ctx) {
  const { dataState, uiState } = ctx;
  const toast = ctx.ui.toast;
  const header = document.querySelector('#detail-overlay .detail-header');
  const copyButton = document.getElementById('detail-copy-btn');
  const detailProps = document.getElementById('detail-props');
  if (!header || !copyButton || !detailProps || !ctx.ai) return;

  const ACTIVE_STATES = new Set(['reviewing', 'repairing', 'rechecking']);
  const BLOCK_START_STATES = new Set([...ACTIVE_STATES, 'revision_required']);
  const STATE_LABELS = {
    idle: '尚未复核',
    reviewing: '独立 reviewer 复核中',
    revision_required: '发现可修订问题',
    repairing: '原 producer 修订中',
    rechecking: '原 reviewer 复核修订',
    resolved: '复核已闭合',
    needs_owner: '需要 Owner 裁决',
    stale: '产物已变化，结果未采纳',
    system_blocked: '评审运行受阻',
  };
  const SEVERITY_LABELS = { blocker: '阻断', major: '重要', minor: '次要', note: '提示' };

  let currentState = { exists: false, state: 'idle', findings: [] };
  let statusTimer = null;
  let refreshSeq = 0;

  const reviewerSelect = document.createElement('select');
  reviewerSelect.id = 'detail-reviewer-profile';
  reviewerSelect.className = 'btn';
  reviewerSelect.title = '选择独立 reviewer；每次使用全新隔离 session';
  reviewerSelect.setAttribute('aria-label', '独立评审模型');

  const reviewButton = document.createElement('button');
  reviewButton.id = 'detail-review-cycle-btn';
  reviewButton.className = 'btn';
  reviewButton.type = 'button';
  reviewButton.textContent = '独立复核';
  reviewButton.title = '用隔离上下文启动另一个模型做只读红队评审';

  header.insertBefore(reviewerSelect, copyButton);
  header.insertBefore(reviewButton, copyButton);

  function reviewProfiles() {
    const profiles = dataState.ai_profiles || {};
    return ['review_claude', 'review_codex']
      .map((name) => ({ name, ...(profiles[name] || {}) }))
      .filter((profile) => profile.tool === 'claude' || profile.tool === 'codex');
  }

  function populateProfiles() {
    const previous = reviewerSelect.value;
    reviewerSelect.textContent = '';
    reviewProfiles().forEach((profile) => {
      const option = document.createElement('option');
      option.value = profile.tool;
      option.textContent = profile.label || profile.name;
      reviewerSelect.appendChild(option);
    });
    if (previous && Array.from(reviewerSelect.options).some((option) => option.value === previous)) {
      reviewerSelect.value = previous;
    } else if (Array.from(reviewerSelect.options).some((option) => option.value === 'claude')) {
      reviewerSelect.value = 'claude';
    }
  }

  function stopStatusPolling() {
    if (statusTimer) clearTimeout(statusTimer);
    statusTimer = null;
  }

  function scheduleStatusPolling(path) {
    stopStatusPolling();
    if (!ACTIVE_STATES.has(currentState.state) || path !== uiState.detail.currentTaskPath) return;
    statusTimer = setTimeout(() => refresh(path), 2200);
  }

  function statusPanel() {
    let panel = document.getElementById('detail-review-cycle-panel');
    if (panel && panel.parentNode !== detailProps) panel.remove();
    if (!panel) {
      panel = document.createElement('section');
      panel.id = 'detail-review-cycle-panel';
      panel.className = 'detail-handoff-status-card';
      detailProps.appendChild(panel);
    }
    return panel;
  }

  function appendMeta(panel, label, value) {
    if (!value) return;
    const row = document.createElement('div');
    row.className = 'detail-handoff-meta';
    const item = document.createElement('span');
    item.textContent = label + ': ' + value;
    row.appendChild(item);
    panel.appendChild(row);
  }

  function findingText(finding) {
    const refs = Array.isArray(finding.evidence_refs) && finding.evidence_refs.length
      ? ' · ' + finding.evidence_refs.join(', ')
      : '';
    return `[${SEVERITY_LABELS[finding.severity] || finding.severity || '问题'}] ${finding.claim || ''}${refs}`;
  }

  function renderState(state) {
    currentState = state || { exists: false, state: 'idle', findings: [] };
    const panel = statusPanel();
    panel.textContent = '';

    const title = document.createElement('div');
    title.className = 'detail-handoff-title';
    title.textContent = '独立评审 · ' + (STATE_LABELS[currentState.state] || currentState.state || '未知');
    panel.appendChild(title);

    const summary = document.createElement('div');
    summary.className = 'detail-handoff-summary';
    summary.textContent = currentState.summary
      || (currentState.exists
        ? '各 Agent 使用独立 session，只通过 canonical artifact、hash 和结构化 findings 交接。'
        : '尚未启动。Reviewer 不读取 producer 的聊天记录或隐藏推理。');
    panel.appendChild(summary);

    if (currentState.exists) {
      appendMeta(panel, 'Reviewer', `${currentState.reviewer_profile || currentState.reviewer_tool || '-'} · 隔离上下文`);
      appendMeta(panel, 'Producer', currentState.producer_profile || currentState.producer_tool || '-');
      appendMeta(panel, 'Artifact', currentState.artifact?.fingerprint?.slice(0, 12));
    }

    const findings = Array.isArray(currentState.findings) ? currentState.findings : [];
    if (findings.length) {
      const list = document.createElement('ul');
      list.className = 'detail-handoff-rules';
      findings.slice(0, 8).forEach((finding) => {
        const item = document.createElement('li');
        item.textContent = findingText(finding);
        list.appendChild(item);
      });
      panel.appendChild(list);
    }

    if (currentState.state === 'revision_required') {
      const actions = document.createElement('div');
      actions.className = 'detail-handoff-actions';
      const repairButton = document.createElement('button');
      repairButton.type = 'button';
      repairButton.className = 'detail-relay-btn primary';
      repairButton.textContent = '按 findings 修订';
      repairButton.disabled = uiState.detail.currentTaskStatus === 'done';
      repairButton.title = repairButton.disabled ? '已完成任务需先重新打开' : '调用原 producer 修订一次，完成后自动交回同一 reviewer 复核';
      repairButton.onclick = () => startRepair(repairButton);
      actions.appendChild(repairButton);
      panel.appendChild(actions);
    }

    updateControls();
  }

  function updateControls() {
    const hasPath = Boolean(uiState.detail.currentTaskPath);
    const blocked = BLOCK_START_STATES.has(currentState.state);
    const noProfiles = reviewerSelect.options.length === 0;
    reviewerSelect.disabled = !hasPath || blocked || noProfiles;
    reviewButton.disabled = !hasPath || blocked || noProfiles;
    reviewButton.textContent = ACTIVE_STATES.has(currentState.state)
      ? (STATE_LABELS[currentState.state] || '评审中')
      : (currentState.state === 'revision_required' ? '等待修订' : '独立复核');
  }

  async function refresh(path = uiState.detail.currentTaskPath) {
    if (!ctx.hasApi || !path) {
      stopStatusPolling();
      renderState({ exists: false, state: 'idle', findings: [] });
      return;
    }
    const seq = ++refreshSeq;
    try {
      const response = await fetch('/api/review-cycle?path=' + encodeURIComponent(path), { cache: 'no-store' });
      const payload = await response.json();
      if (seq !== refreshSeq || path !== uiState.detail.currentTaskPath) return;
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      renderState(payload.review_cycle);
      const runId = payload.review_cycle?.last_run_id;
      if (runId && ACTIVE_STATES.has(payload.review_cycle?.state)) {
        ctx.ai.startPolling(runId, path, { onDone: () => refresh(path) });
      }
      scheduleStatusPolling(path);
    } catch (error) {
      if (seq !== refreshSeq || path !== uiState.detail.currentTaskPath) return;
      renderState({ exists: false, state: 'system_blocked', summary: error.message, findings: [] });
      stopStatusPolling();
    }
  }

  async function startReview() {
    const path = uiState.detail.currentTaskPath;
    const reviewerTool = reviewerSelect.value;
    if (!path || !reviewerTool) return;
    const label = reviewerSelect.options[reviewerSelect.selectedIndex]?.textContent || reviewerTool;
    const confirmed = confirm(
      `用 ${label} 发起独立复核？\n\nReviewer 将使用全新只读 session，只接收当前任务契约、artifact hash 和可核查文件，不接收 producer 的聊天记录。`
    );
    if (!confirmed) return;
    reviewButton.disabled = true;
    try {
      const response = await fetch('/api/review-cycle/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, reviewer_tool: reviewerTool }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      toast('独立 reviewer 已进入 AI 队列');
      ctx.ai.loadAiHistory(path);
      ctx.ai.startPolling(payload.run_id, path, { onDone: () => refresh(path) });
      renderState(payload.review_cycle);
      scheduleStatusPolling(path);
    } catch (error) {
      toast(error.message || '独立复核启动失败', true);
      updateControls();
    }
  }

  async function startRepair(button) {
    const path = uiState.detail.currentTaskPath;
    if (!path) return;
    if (!confirm('调用原 producer 按 open findings 修订一次？\n\n这是写操作；任务目标不可改变。修订完成后会自动交回同一 reviewer 复核。')) return;
    button.disabled = true;
    try {
      const response = await fetch('/api/review-cycle/repair', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      toast('原 producer 已按 findings 进入修订队列');
      ctx.ai.loadAiHistory(path);
      ctx.ai.startPolling(payload.run_id, path, { onDone: () => refresh(path) });
      renderState(payload.review_cycle);
      scheduleStatusPolling(path);
    } catch (error) {
      toast(error.message || '修订启动失败', true);
      button.disabled = false;
    }
  }

  populateProfiles();
  reviewButton.onclick = startReview;

  const originalLoadAiHistory = ctx.ai.loadAiHistory.bind(ctx.ai);
  ctx.ai.loadAiHistory = function loadAiHistoryWithReview(path) {
    const result = originalLoadAiHistory(path);
    refresh(path);
    return result;
  };

  const originalResetDetailActivity = ctx.ai.resetDetailActivity.bind(ctx.ai);
  ctx.ai.resetDetailActivity = function resetDetailActivityWithReview() {
    stopStatusPolling();
    refreshSeq += 1;
    currentState = { exists: false, state: 'idle', findings: [] };
    const panel = document.getElementById('detail-review-cycle-panel');
    if (panel) panel.remove();
    originalResetDetailActivity();
    updateControls();
  };

  ctx.reviewCycle = { refresh, renderState, startReview };
  updateControls();
}
