function healthTone(part) {
  const health = part && part.health;
  return health === 'bad' ? 'bad' : health === 'warn' ? 'warn' : 'normal';
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

export function networkRollup(status) {
  if (!status || !status.ok) return { tone: 'bad', label: '状态不可达' };
  if (status.doctor && status.doctor.available === false) return { tone: 'bad', label: '脚本不可用' };
  const parts = [
    status.profiles && status.profiles.verge_tun_global,
    status.verge_core,
    status.verge_service,
    status.tun,
    status.system_proxy,
    status.checks && status.checks.github,
    status.checks && status.checks.feishu,
    status.checks && status.checks.imap_163,
  ];
  const tones = parts.map(healthTone);
  if (tones.includes('bad')) return { tone: 'bad', label: '需修复' };
  if (tones.includes('warn')) return { tone: 'warn', label: '需调整' };
  return { tone: 'normal', label: '轻量状态正常' };
}

export function syncStatusTone(sync) {
  if (!sync || sync.enabled === false || sync.state === 'disabled' || sync.watcher_status === 'disabled') return 'info';
  if (sync.last_error || sync.state === 'error' || sync.watcher_status === 'error') return 'bad';
  if (sync.watcher_status && !['running', 'idle', 'watching'].includes(sync.watcher_status)) return 'warn';
  return 'normal';
}

export function localStatusRollup(status, cli, sync) {
  const network = networkRollup(status);
  const tools = (cli && cli.tools) || [];
  const cliTone = tools.length > 0 && tools.every((tool) => tool.available) ? 'normal' : 'bad';
  const tones = [network.tone, cliTone, syncStatusTone(sync)];
  const tone = tones.includes('bad') ? 'bad' : tones.includes('warn') ? 'warn' : 'normal';
  return { tone, label: tone === 'normal' ? '本机状态正常' : tone === 'warn' ? '本机状态需调整' : '本机状态需处理' };
}

export function doctorConfirmation(action, confirmFn) {
  if (action === 'diagnose') return true;
  const prompt = action === 'emergency'
    ? '断网急救会重启或调整 Clash Verge、恢复 global+TUN，并测试/切换异常节点。继续吗？'
    : '一键修复会调整本机网络状态，并在节点异常时测试和切换节点。继续吗？';
  return confirmFn(prompt) === true;
}

export function setupHeaderStatus(ctx) {
  const root = document.getElementById('hdr-local-status');
  if (!root) return;
  const trigger = document.getElementById('hdr-network-trigger');
  const panel = document.getElementById('hdr-network-panel');
  const cli = ctx.dataState.cli_status || {};
  let sync = ctx.uiState.sync.state || ctx.dataState.git_sync || {};
  let latestStatus = null;
  let busy = false;
  panel.innerHTML = `
    <div class="hdr-network-head">
      <div><div class="hdr-network-title">本机状态</div><div class="hdr-network-summary" id="hdr-network-summary">轻量状态只看入口；节点健康需运行深度检查</div></div>
    </div>
    <div class="hdr-status-group"><div class="hdr-status-group-title">网络</div><div class="hdr-network-facts" id="hdr-network-facts"></div></div>
    <div class="hdr-status-group"><div class="hdr-status-group-title">CLI</div><div class="hdr-network-facts" id="hdr-cli-facts"></div></div>
    <div class="hdr-status-group"><div class="hdr-status-group-title">同步</div><div class="hdr-network-facts" id="hdr-sync-facts"></div><div class="hdr-status-hint">开关位在右上角溢出菜单「Git 自动同步」</div></div>
    <div class="hdr-network-actions">
      <button type="button" class="hdr-network-action" data-doctor-action="diagnose">检查网络</button>
      <button type="button" class="hdr-network-action" data-doctor-action="fix">一键修复</button>
      <button type="button" class="hdr-network-action" data-doctor-action="emergency">断网急救</button>
    </div>`;
  const summary = panel.querySelector('#hdr-network-summary');
  const facts = panel.querySelector('#hdr-network-facts');
  const cliFacts = panel.querySelector('#hdr-cli-facts');
  const syncFacts = panel.querySelector('#hdr-sync-facts');
  const buttons = Array.from(panel.querySelectorAll('[data-doctor-action]'));

  function setBusy(next) {
    busy = next;
    trigger.classList.toggle('is-loading', next);
    buttons.forEach((button) => { button.disabled = next || !ctx.hasApi; });
  }

  function fact(label, part) {
    const tone = healthTone(part);
    const text = (part && (part.label || part.summary)) || '未检测';
    return `<div class="hdr-network-fact is-${tone}"><span class="hdr-status-dot"></span><span>${escapeHtml(label)} · ${escapeHtml(text)}</span></div>`;
  }

  function renderStatus(status) {
    latestStatus = status;
    const rollup = localStatusRollup(status, cli, sync);
    trigger.classList.remove('is-bad', 'is-warn');
    if (rollup.tone !== 'normal') trigger.classList.add(`is-${rollup.tone}`);
    trigger.title = `本机状态 · ${rollup.label}`;
    const checks = (status && status.checks) || {};
    facts.innerHTML = [
      fact('Verge core', status && status.verge_core), fact('Verge service', status && status.verge_service),
      fact('GitHub', checks.github), fact('飞书', checks.feishu),
    ].join('');
    cliFacts.innerHTML = (cli.tools || []).map((tool) => fact(tool.name, {
      health: tool.available ? 'normal' : 'bad', label: tool.available ? '可用' : '不可用',
    })).join('') || fact('CLI', { health: 'bad', label: '未配置' });
    const syncTone = syncStatusTone(sync);
    const lastActivity = sync.last_sync_at || (sync.last_push && sync.last_push.at) || (sync.last_pull && sync.last_pull.at) || (sync.last_commit && sync.last_commit.at) || sync.updated_at;
    let syncLabel = sync.enabled === false || syncTone === 'info' ? '已关闭' : sync.state === 'syncing' ? '同步中' : '运行中';
    if (sync.last_error) syncLabel = `异常 · ${sync.last_error}`;
    else if (syncTone === 'warn') syncLabel = `异常 · ${sync.watcher_status || sync.state || 'watcher 状态未知'}`;
    else if (lastActivity && sync.enabled !== false) syncLabel += ` · 最近 ${lastActivity}`;
    syncFacts.innerHTML = fact('Git 自动同步', { health: syncTone, label: syncLabel });
    summary.textContent = rollup.label;
  }

  function updateSync(nextSync) {
    sync = nextSync || {};
    if (latestStatus) renderStatus(latestStatus);
  }

  async function loadStatus() {
    if (!ctx.api || !ctx.api.networkStatus) return renderStatus({ ok: false });
    setBusy(true);
    const status = await ctx.api.networkStatus();
    setBusy(false);
    renderStatus(status);
  }

  async function runDoctor(action) {
    if (busy || !ctx.api || !ctx.api.networkDoctor) return;
    const confirmed = action === 'diagnose' ? false : doctorConfirmation(action, window.confirm.bind(window));
    if (action !== 'diagnose' && !confirmed) return;
    setBusy(true);
    summary.textContent = '网络医生执行中…';
    const result = await ctx.api.networkDoctor(action, confirmed);
    if (result && result.ok) {
      const diagnosis = result.diagnosis || {};
      summary.textContent = diagnosis.conclusion || '网络医生已完成';
    }
    setBusy(false);
    await loadStatus();
  }

  trigger.addEventListener('click', () => {
    const opening = panel.hidden;
    panel.hidden = !opening;
    trigger.setAttribute('aria-expanded', String(opening));
    if (opening && !latestStatus) loadStatus();
  });
  panel.addEventListener('click', (event) => {
    const button = event.target.closest('[data-doctor-action]');
    if (button) runDoctor(button.dataset.doctorAction);
  });
  document.addEventListener('click', (event) => {
    if (!root.contains(event.target)) {
      panel.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    }
  });
  ctx.headerStatus = { updateSync };
  loadStatus();
}
