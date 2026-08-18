// KAN-1600: mounted by main.js; dependencies arrive through ctx.renderBoardInternal.
export function setupRenderBoardConsoleRuntime(ctx) {
  const board = ctx.renderBoardInternal;
  if (!board) throw new Error("setupRenderBoard(ctx) must run first");
  const { dataState, toast, chainStateCache, CONSOLE_AUDIENCE_OWNER, KM_STAGE_ALIASES } = board;
  const dynamicProviderMatchesSurface = (...args) => board.dynamicProviderMatchesSurface(...args);
  const chainStageTone = (...args) => board.chainStageTone(...args);
  const makeDomainCard = (...args) => board.makeDomainCard(...args);
  const markConsoleAudience = (...args) => board.markConsoleAudience(...args);
  const sortConsoleTodayTasks = (...args) => board.sortConsoleTodayTasks(...args);
  const copyTextToClipboard = (...args) => board.copyTextToClipboard(...args);
  const dynamicPromptFor = (...args) => board.dynamicPromptFor(...args);
  const makeDynamicProviderCard = (...args) => board.makeDynamicProviderCard(...args);
  const renderConsole = (...args) => board.renderConsole(...args);

  function makeNetworkStatusBlock() {
    const clash = dataState.clash || dataState.network_clash || (dataState.network && dataState.network.clash);
    if (dataState.ui_features?.network_doctor !== true) return null;
    if (!ctx.hasApi && dataState.clash_configured !== true && !(clash && clash.open_script)) return null;

    const section = document.createElement('div');
    section.className = 'console-network is-collapsed';

    // 折叠摘要条：默认只显示这一行小状态灯，点开才展开完整明细。
    const summary = document.createElement('div');
    summary.className = 'console-network-summary';
    const sumTitle = document.createElement('span');
    sumTitle.className = 'console-network-sum-title';
    sumTitle.textContent = '网络医生';
    const dots = document.createElement('div');
    dots.className = 'console-network-sumdots';
    const rollup = document.createElement('span');
    rollup.className = 'console-network-rollup tone-muted';
    rollup.textContent = '检测中';
    const refresh = document.createElement('button');
    refresh.type = 'button';
    refresh.className = 'console-network-refresh';
    refresh.title = '刷新网络状态';
    refresh.setAttribute('aria-label', '刷新网络状态');
    refresh.innerHTML = '<i data-lucide="refresh-cw"></i>';
    const chevron = document.createElement('span');
    chevron.className = 'console-network-chevron';
    chevron.textContent = '⌄';
    summary.appendChild(sumTitle);
    summary.appendChild(dots);
    summary.appendChild(rollup);
    summary.appendChild(refresh);
    summary.appendChild(chevron);
    summary.onclick = (e) => {
      if (e.target === refresh || refresh.contains(e.target)) return;
      const collapsed = section.classList.toggle('is-collapsed');
      chevron.textContent = collapsed ? '⌄' : '⌃';
    };
    section.appendChild(summary);

    const details = document.createElement('div');
    details.className = 'console-network-details';
    const actionBar = document.createElement('div');
    actionBar.className = 'console-network-actions';
    details.appendChild(actionBar);

    const doctorSummary = document.createElement('div');
    doctorSummary.className = 'console-network-doctor-summary tone-muted';
    const doctorConclusion = document.createElement('strong');
    doctorConclusion.textContent = '尚未运行深度检查';
    const doctorMeta = document.createElement('span');
    doctorMeta.textContent = '轻量状态只看入口；节点假活必须运行网络医生才能发现';
    doctorSummary.appendChild(doctorConclusion);
    doctorSummary.appendChild(doctorMeta);
    details.appendChild(doctorSummary);

    const grid = document.createElement('div');
    grid.className = 'console-network-grid';
    details.appendChild(grid);
    section.appendChild(details);

    const controls = {};
    const groups = [
      {
        title: '本机代理',
        items: [
          ['verge_profile', 'Verge TUN 全局'],
          ['verge_core', 'Verge core'],
          ['verge_service', 'Verge service'],
          ['tun', 'TUN'],
          ['system_proxy', '系统代理'],
        ],
      },
      {
        title: '外部连通',
        items: [
          ['github', 'GitHub'],
          ['feishu', '飞书'],
          ['imap_163', 'IMAP 163'],
        ],
      },
    ];

    function makeItem(key, label) {
      const item = document.createElement('div');
      item.className = 'console-network-item tone-muted';
      const main = document.createElement('div');
      main.className = 'console-network-main';
      const dot = document.createElement('span');
      dot.className = 'console-network-dot';
      const labelEl = document.createElement('span');
      labelEl.className = 'console-network-label';
      labelEl.textContent = label;
      main.appendChild(dot);
      main.appendChild(labelEl);
      const status = document.createElement('span');
      status.className = 'console-network-status';
      status.textContent = '未检测';
      const port = document.createElement('span');
      port.className = 'console-network-port';
      port.hidden = true;
      const detail = document.createElement('span');
      detail.className = 'console-network-detail';
      item.appendChild(main);
      item.appendChild(status);
      item.appendChild(port);
      item.appendChild(detail);
      const sumDot = document.createElement('span');
      sumDot.className = 'console-network-sumdot tone-muted';
      sumDot.title = label;
      dots.appendChild(sumDot);
      controls[key] = { item, status, detail, port, sumDot, label };
      return item;
    }

    groups.forEach((group) => {
      const card = document.createElement('div');
      card.className = 'console-network-card';
      const cardTitle = document.createElement('div');
      cardTitle.className = 'console-network-card-title';
      cardTitle.textContent = group.title;
      const list = document.createElement('div');
      list.className = 'console-network-list';
      group.items.forEach(([key, label]) => list.appendChild(makeItem(key, label)));
      card.appendChild(cardTitle);
      card.appendChild(list);
      grid.appendChild(card);
    });

    function setItem(key, tone, statusText, detailText, portText) {
      const control = controls[key];
      if (!control) return;
      control.item.className = 'console-network-item tone-' + tone;
      control.status.textContent = statusText || '需确认';
      control.detail.textContent = detailText || '';
      const portValue = portText ? String(portText) : '';
      control.port.textContent = portValue;
      control.port.hidden = !portValue;
      if (control.sumDot) {
        control.sumDot.className = 'console-network-sumdot tone-' + tone;
        control.sumDot.title = control.label + (statusText ? ' · ' + statusText : '');
      }
      refreshRollup();
    }

    let latestDoctorHealth = '';
    function refreshRollup() {
      const tones = Object.values(controls).map((c) => (c.sumDot && (c.sumDot.className.match(/tone-(\w+)/) || [])[1]) || 'muted');
      let cls = 'good';
      let label = '正常';
      if (latestDoctorHealth === 'bad' || tones.includes('bad')) { cls = 'bad'; label = '需修复'; }
      else if (latestDoctorHealth === 'warn') { cls = 'warn'; label = '有警告'; }
      else if (tones.includes('warn')) { cls = 'warn'; label = '需调整'; }
      else if (tones.every((t) => t === 'muted' || t === 'loading')) { cls = 'muted'; label = tones.includes('loading') ? '检测中' : '未检测'; }
      rollup.className = 'console-network-rollup tone-' + cls;
      rollup.textContent = label;
    }

    function toneOf(part) {
      const health = part && part.health;
      if (health === 'good') return 'good';
      if (health === 'warn') return 'warn';
      if (health === 'bad') return 'bad';
      return 'muted';
    }

    function latencyText(part) {
      if (!part || typeof part.latency_ms !== 'number') return '';
      return `${part.latency_ms}毫秒`;
    }

    function wait(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }

    const actionButtons = [];
    function makeAction(label, action, titleText) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'console-network-action';
      btn.textContent = label;
      btn.title = titleText || label;
      btn.onclick = () => runDoctor(action, btn, label);
      actionBar.appendChild(btn);
      actionButtons.push(btn);
      return btn;
    }

    function setLoading(isLoading) {
      refresh.disabled = isLoading || !ctx.hasApi;
      refresh.classList.toggle('is-loading', isLoading);
      actionButtons.forEach((button) => { button.disabled = isLoading || !ctx.hasApi; });
      if (isLoading) {
        Object.keys(controls).forEach((key) => setItem(key, 'loading', '检测中', '', ''));
      }
    }

    async function loadNetworkStatus(manual) {
      if (!ctx.api || !ctx.api.networkStatus) {
        Object.keys(controls).forEach((key) => setItem(key, 'muted', '静态模式', '', ''));
        return;
      }
      setLoading(true);
      const result = await ctx.api.networkStatus();
      setLoading(false);
      if (!result || !result.ok) {
        Object.keys(controls).forEach((key) => setItem(key, 'bad', '需确认', '', ''));
        if (manual) toast('网络状态检测失败', true);
        return;
      }
      if (result.doctor && result.doctor.available === false) {
        doctorSummary.className = 'console-network-doctor-summary tone-bad';
        doctorConclusion.textContent = '网络医生脚本不可用';
        doctorMeta.textContent = result.doctor.error || '请检查 net-doctor.sh';
        actionButtons.forEach((button) => { button.disabled = true; });
      }
      const vergeProfile = (result.profiles || {}).verge_tun_global || {};
      setItem('verge_profile', toneOf(vergeProfile), vergeProfile.label, vergeProfile.summary, '');
      setItem('verge_core', toneOf(result.verge_core), result.verge_core?.label, '', '');
      setItem('verge_service', toneOf(result.verge_service), result.verge_service?.label, '', '');
      const tun = result.tun || {};
      setItem('tun', toneOf(tun), tun.label, tun.summary, tun.interface);
      const proxy = result.system_proxy || {};
      const portText = proxy.primary_port || (Array.isArray(proxy.ports) && proxy.ports.length ? proxy.ports.join('/') : '');
      setItem('system_proxy', toneOf(proxy), proxy.label, proxy.summary, portText);
      const checks = result.checks || {};
      setItem('github', toneOf(checks.github), checks.github?.label, latencyText(checks.github), '');
      setItem('feishu', toneOf(checks.feishu), checks.feishu?.label, latencyText(checks.feishu), '');
      setItem('imap_163', toneOf(checks.imap_163), checks.imap_163?.label, latencyText(checks.imap_163), '');
      return result;
    }

    function doctorTone(health) {
      if (health === 'good') return 'good';
      if (health === 'warn') return 'warn';
      if (health === 'bad') return 'bad';
      return 'muted';
    }

    function renderDoctorResult(diagnosis) {
      diagnosis = diagnosis || {};
      latestDoctorHealth = doctorTone(diagnosis.health);
      doctorSummary.className = 'console-network-doctor-summary tone-' + latestDoctorHealth;
      doctorConclusion.textContent = diagnosis.conclusion || '深度检查已完成';
      const node = diagnosis.node || {};
      const nodeBits = [];
      if (diagnosis.mode) nodeBits.push(diagnosis.mode);
      if (node.current) nodeBits.push(node.current);
      if (node.health === 'healthy') nodeBits.push(`节点健康${typeof node.delay_ms === 'number' ? ` ${node.delay_ms}毫秒` : ''}`);
      else if (node.health === 'fake_alive') nodeBits.push('节点假活');
      else if (node.health === 'down') nodeBits.push('节点不可用');
      nodeBits.push(`${diagnosis.warnings || 0}警告 / ${diagnosis.failures || 0}故障`);
      doctorMeta.textContent = nodeBits.join(' · ');
      refreshRollup();
    }

    async function runDoctor(action, btn, label) {
      if (!ctx.api || !ctx.api.networkDoctor) {
        toast('静态模式不可运行网络医生', true);
        return;
      }
      let confirmed = false;
      if (action !== 'diagnose') {
        const prompt = action === 'emergency'
          ? '断网急救会重启或调整 Clash Verge、恢复 global+TUN、关闭系统代理，并测试/切换异常节点。继续吗？'
          : '一键修复会调整本机网络状态，并在节点异常时测试和切换节点。继续吗？';
        confirmed = window.confirm(prompt);
        if (!confirmed) return;
      }
      setLoading(true);
      btn.textContent = '执行中…';
      const result = await ctx.api.networkDoctor(action, confirmed);
      if (result && result.ok) {
        renderDoctorResult(result.diagnosis);
        toast((result.diagnosis && result.diagnosis.conclusion) || '网络医生已完成');
      }
      btn.textContent = label;
      setLoading(false);
      await loadNetworkStatus(false);
    }

    makeAction('检查网络', 'diagnose', '只读深度检查：包含节点延迟与实际数据传输');
    makeAction('一键修复', 'fix', '修复冲突、global、TUN、系统代理与异常节点');
    makeAction('断网急救', 'emergency', '快速修复并强制选择健康节点');
    refresh.onclick = () => loadNetworkStatus(true);
    loadNetworkStatus(false);
    if (typeof lucide !== 'undefined') requestAnimationFrame(() => lucide.createIcons());
    return section;
  }

// ── 调度台 Flow（复杂项目按流程阶段观察，泳道 = 阶段而不是状态）──────────
  // 卡片归属：frontmatter `stage`（如 km/card_reading）显式指定优先，否则按关键词推断；
  // 无显式 stage 的卡按 config.chains 顺序只归入第一条命中的链，避免跨链重复计数；
  // done 卡计入阶段完成度但不再占泳道位。
  // 层语义头（role/question）和 responsibility 来自 config.chains；
  function chainResponsibilityLabel(responsibility) {
    if (responsibility === 'ai-owned') return 'AI负责';
    if (responsibility === 'pi-gated') return '提醒 PI';
    return '协作';
  }

  function makeChainResponsibilityBadge(stage) {
    const badge = document.createElement('span');
    const responsibility = stage.responsibility || 'shared';
    badge.className = 'chain-resp-badge is-' + responsibility.replace(/[^a-z-]/g, '');
    badge.textContent = chainResponsibilityLabel(responsibility);
    return badge;
  }

  function chainStageCardRef(stageData) {
    if (!stageData || typeof stageData !== 'object') return null;
    const raw = stageData.kanban_card || stageData.kanban || stageData.card || stageData.task || stageData.task_ref;
    if (raw && typeof raw === 'object') return raw;
    const path = stageData.kanban_path || stageData.task_path || stageData.card_path || stageData.path || (typeof raw === 'string' ? raw : '');
    const taskId = stageData.task_id || stageData.kanban_task_id || stageData.code || '';
    if (!path && !taskId) return null;
    return { path, task_id: taskId, title: stageData.card_title || stageData.task_title || stageData.title || '' };
  }

  function findTaskForStageRef(ref) {
    if (!ref || typeof ref !== 'object') return null;
    const path = String(ref.path || '').trim();
    const taskId = String(ref.task_id || ref.code || '').trim();
    return (dataState.tasks || []).find((task) => (
      (path && task.path === path) || (taskId && task.task_id === taskId)
    )) || null;
  }

  function makeChainStageLink(ref) {
    const task = findTaskForStageRef(ref);
    const path = String((task && task.path) || ref.path || '').trim();
    if (!task && !path) return null;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chain-stage-link';
    btn.textContent = String(ref.title || (task && task.title) || ref.task_id || '提醒卡').trim();
    btn.onclick = () => {
      if (task && ctx.renderDetail && ctx.renderDetail.openTaskDetail) {
        ctx.renderDetail.openTaskDetail(task.path);
      } else if (path && ctx.api && ctx.api.openInEditor) {
        ctx.api.openInEditor(path);
      }
    };
    return btn;
  }

  // 记住每条链当前展开的阶段，数据刷新重渲染后不丢选中态。
  // Selection/cache live on the shared ctx capability surface (KAN-1600).


  function chainStateCached(chainKey) {
    const entry = chainStateCache[String(chainKey || '')];
    return entry && entry.ok ? entry.data : null;
  }

  function requestChainState(chainKey, onDone) {
    const key = String(chainKey || '').trim();
    if (!key || !ctx.hasApi || !ctx.api || !ctx.api.apiJson) return;
    const cached = chainStateCache[key];
    if (cached && (cached.loading || cached.ok || cached.data)) return;
    chainStateCache[key] = { loading: true, ok: false, data: null };
    ctx.api.apiJson('/api/chains/' + encodeURIComponent(key)).then(({ json }) => {
      chainStateCache[key] = { loading: false, ok: Boolean(json && json.ok), data: json || null };
      if (onDone) onDone(json || null);
    }).catch(() => {
      chainStateCache[key] = { loading: false, ok: false, data: { ok: false, error: '读取失败' } };
      if (onDone) onDone(null);
    });
  }

  function skillStateHealthTone(state) {
    const value = String(state || '').toLowerCase();
    if (value === 'ok' || value === 'pass' || value === 'good') return 'good';
    if (value === 'warn' || value === 'warning' || value === 'pi-gated-waiting') return 'warn';
    if (value === 'drift' || value === 'error' || value === 'failed') return 'bad';
    return 'muted';
  }

  function skillStateStageMap(state) {
    if (!state || typeof state !== 'object') return {};
    if (state.stage_map && typeof state.stage_map === 'object') return state.stage_map;
    const raw = state.stages;
    const out = {};
    if (Array.isArray(raw)) {
      raw.forEach((stage) => {
        if (stage && stage.key) out[stage.key] = stage;
      });
      return out;
    }
    return raw && typeof raw === 'object' ? raw : {};
  }

  function mergeSkillStageData(entries) {
    const items = entries.filter((entry) => entry && typeof entry === 'object');
    if (!items.length) return {};
    if (items.length === 1) return items[0];
    const rank = { ok: 0, pass: 0, warn: 1, 'pi-gated-waiting': 2, drift: 3, error: 4, failed: 4 };
    const worst = items.reduce((best, item) => (
      (rank[String(item.state || '').toLowerCase()] || 0) > (rank[String(best.state || '').toLowerCase()] || 0) ? item : best
    ), items[0]);
    const summary = items.map((item) => String(item.summary || '').trim()).filter(Boolean).join(' · ');
    const metrics = items.flatMap((item) => Array.isArray(item.metrics) ? item.metrics : []);
    return { ...worst, summary: summary || worst.summary || '', metrics };
  }

  function skillStateStageData(state, chain, stageKey) {
    const map = skillStateStageMap(state);
    const key = String(stageKey || '').trim();
    const keys = [key];
    if (chain && chain.key === 'km') {
      Object.entries(KM_STAGE_ALIASES).forEach(([legacy, canonical]) => {
        if (canonical === key) keys.push(legacy);
      });
    }
    return mergeSkillStageData([...new Set(keys)].map((candidate) => map[candidate]));
  }

  function skillDecisionCardRef(decision) {
    if (!decision || typeof decision !== 'object') return null;
    const raw = decision.card || decision.kanban_card || decision.task || decision.task_ref;
    if (raw && typeof raw === 'object') return raw;
    const path = String(decision.path || decision.card_path || '').trim();
    const taskId = String(decision.task_id || '').trim();
    return path || taskId ? { path, task_id: taskId, title: decision.title || decision.question || '' } : null;
  }

  function makeSkillDecisionItem(decision) {
    const item = document.createElement('div');
    item.className = 'skill-state-decision';
    const top = document.createElement('div');
    top.className = 'skill-state-decision-top';
    const sev = document.createElement('span');
    sev.className = 'skill-state-severity';
    sev.textContent = decision.severity || '待拍板';
    const q = document.createElement('strong');
    q.textContent = decision.question || decision.id || '未命名决策';
    top.appendChild(sev);
    top.appendChild(q);
    item.appendChild(top);
    if (decision.why) {
      const why = document.createElement('div');
      why.className = 'skill-state-decision-why';
      why.textContent = decision.why;
      item.appendChild(why);
    }
    const evidence = Array.isArray(decision.evidence) ? decision.evidence.filter(Boolean) : [];
    if (evidence.length) {
      const ev = document.createElement('div');
      ev.className = 'skill-state-decision-evidence';
      ev.textContent = evidence.slice(0, 3).join(' · ');
      item.appendChild(ev);
    }
    const ref = skillDecisionCardRef(decision);
    const link = ref ? makeChainStageLink(ref) : null;
    if (link) {
      link.textContent = '打开关联卡';
      item.appendChild(link);
    } else {
      const pending = document.createElement('span');
      pending.className = 'skill-state-card-pending';
      pending.textContent = '待生成 PI 卡';
      item.appendChild(pending);
    }
    return item;
  }

  function invocationNeedsConfirm(invocation) {
    const responsibility = String(invocation.responsibility || '').toLowerCase();
    const safety = String(invocation.safety || '').toLowerCase();
    const risky = ['mutating', 'external', 'irreversible'].includes(safety);
    const direct = responsibility === 'ai-owned'
      && (safety === 'read-only' || invocation.idempotent === true)
      && invocation.idempotent !== false
      && !risky;
    return !direct || responsibility === 'pi-gated' || risky;
  }

  async function runSkillInvocation(invocation, button) {
    const mechanism = String(invocation.mechanism || '').trim();
    const label = String(invocation.label || invocation.id || '动作').trim();
    if (invocationNeedsConfirm(invocation)) {
      const ok = confirm(label + '\n\n该动作需要人工确认后再触发。是否继续？');
      if (!ok) return;
    }
    if (button) button.disabled = true;
    try {
      if (mechanism === 'skill') {
        const { json } = await ctx.api.apiJson('/api/skill-invocation', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ invocation }),
        });
        toast((json && (json.message || json.error)) || 'skill invocation 失败', !(json && json.ok));
        if (json && json.outcome === 'stale') renderConsole();
        return;
      }
      if (mechanism === 'bridge') {
        const target = String(invocation.target || '').trim();
        if (!target || !ctx.api || !ctx.api.launchBridge) {
          toast('缺少 bridge target', true);
          return;
        }
        const result = await ctx.api.launchBridge(target);
        if (result && result.ok) toast(label + ' 已触发');
        return;
      }
      if (mechanism === 'ai-run') {
        const card = invocation.card || invocation.task || {};
        const path = String(invocation.path || card.path || '').trim();
        if (!path || !ctx.api || !ctx.api.apiJson) {
          toast('ai-run 需要绑定任务卡 path', true);
          return;
        }
        const tool = String(invocation.tool || invocation.agent || 'codex').trim();
        const prompt = String(invocation.prompt || invocation.command || '').trim();
        const { json } = await ctx.api.apiJson('/api/ai-run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, tool, prompt, origin: 'skill-state', display_message: label }),
        });
        if (!json || !json.ok) {
          toast((json && json.error) || 'ai-run 提交失败', true);
          return;
        }
        toast(label + ' 已入队');
        if (ctx.ai && typeof ctx.ai.openQueueSidebar === 'function') ctx.ai.openQueueSidebar('running');
        return;
      }
      if (mechanism === 'cli' || mechanism === 'scheduled') {
        const command = String(invocation.command || invocation.target || '').trim();
        if (!command) {
          toast('没有可复制的命令', true);
          return;
        }
        copyTextToClipboard(command, label + ' 命令已复制');
        return;
      }
      toast('暂不支持机制：' + (mechanism || '未声明'), true);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function makeSkillInvocationButton(invocation) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'skill-state-action';
    if (invocationNeedsConfirm(invocation)) btn.classList.add('needs-confirm');
    btn.textContent = invocation.label || invocation.id || '运行';
    btn.title = [
      invocation.mechanism ? 'mechanism: ' + invocation.mechanism : '',
      invocation.safety ? 'safety: ' + invocation.safety : '',
      invocation.produces || '',
    ].filter(Boolean).join('\n');
    btn.onclick = () => runSkillInvocation(invocation, btn);
    return btn;
  }

  function makeSkillStateBlock(chain, state) {
    const box = document.createElement('div');
    box.className = 'skill-state-block';
    const health = state && typeof state.health === 'object' ? state.health : {};
    const head = document.createElement('div');
    head.className = 'skill-state-head';
    const title = document.createElement('div');
    title.className = 'skill-state-title';
    title.textContent = (state.title || chain.title || chain.key) + ' · ' + (state.schema_version || 'state');
    const tone = skillStateHealthTone(health.state || state.state);
    const badge = document.createElement('span');
    badge.className = 'skill-state-badge tone-' + tone;
    badge.textContent = health.state || state.state || 'unknown';
    head.appendChild(title);
    head.appendChild(badge);
    box.appendChild(head);
    const summary = document.createElement('div');
    summary.className = 'skill-state-summary';
    summary.textContent = [health.summary || state.summary || '', state.generated_at ? '生成于 ' + state.generated_at : ''].filter(Boolean).join(' · ');
    box.appendChild(summary);

    const kpis = Array.isArray(health.kpis) ? health.kpis : (Array.isArray(state.kpis) ? state.kpis : []);
    if (kpis.length) {
      const row = document.createElement('div');
      row.className = 'skill-state-kpis';
      kpis.slice(0, 6).forEach((kpi) => {
        const item = document.createElement('div');
        item.className = 'skill-state-kpi tone-' + skillStateHealthTone(kpi.state);
        const v = document.createElement('strong');
        v.textContent = kpi.value;
        const l = document.createElement('span');
        l.textContent = kpi.label || '';
        item.appendChild(v);
        item.appendChild(l);
        row.appendChild(item);
      });
      box.appendChild(row);
    }

    const pending = Array.isArray(state.pending) ? state.pending.filter(Boolean) : [];
    if (pending.length) {
      const list = document.createElement('div');
      list.className = 'skill-state-pending';
      pending.slice(0, 5).forEach((item) => {
        const row = document.createElement('div');
        row.textContent = item.title || item.summary || item.id || String(item);
        list.appendChild(row);
      });
      box.appendChild(list);
    }

    const invocations = Array.isArray(state.invocations) ? state.invocations.filter((item) => item && item.id) : [];
    if (invocations.length) {
      const actions = document.createElement('div');
      actions.className = 'skill-state-actions';
      invocations.forEach((invocation) => actions.appendChild(makeSkillInvocationButton(invocation)));
      box.appendChild(actions);
    }

    const decisions = Array.isArray(state.needs_decision) ? state.needs_decision.filter(Boolean) : [];
    if (decisions.length) {
      const decisionsBox = document.createElement('div');
      decisionsBox.className = 'skill-state-decisions-inline';
      decisions.forEach((decision) => decisionsBox.appendChild(makeSkillDecisionItem(decision)));
      box.appendChild(decisionsBox);
    }
    return box;
  }

  function makeSkillStateDecisionLane() {
    const mount = document.createElement('div');
    mount.className = 'skill-state-decision-lane';
    const cached = chainStateCached('km');
    if (cached && Array.isArray(cached.needs_decision) && cached.needs_decision.length) {
      const lane = document.createElement('div');
      lane.className = 'console-lane console-lane-inbox';
      markConsoleAudience(lane, CONSOLE_AUDIENCE_OWNER);
      const hd = document.createElement('div');
      hd.className = 'console-lane-hd';
      const lbl = document.createElement('span');
      lbl.textContent = '待拍板 · skill-state';
      const cnt = document.createElement('span');
      cnt.textContent = cached.needs_decision.length;
      cnt.className = 'console-lane-count';
      hd.appendChild(lbl);
      hd.appendChild(cnt);
      lane.appendChild(hd);
      cached.needs_decision.forEach((decision) => lane.appendChild(makeSkillDecisionItem(decision)));
      mount.appendChild(lane);
      return mount;
    }
    requestChainState('km', () => renderConsole());
    return mount;
  }

  function makeChainStagePanel(stage, items, stageData) {
    const active = sortConsoleTodayTasks(items.filter((task) => task.status !== 'done'));
    const done = items.filter((task) => task.status === 'done');
    const panel = document.createElement('div');
    const responsibility = String(stage.responsibility || 'shared').replace(/[^a-z-]/g, '');
    panel.className = 'chain-stage-panel is-' + responsibility;
    const hd = document.createElement('div');
    hd.className = 'chain-stage-panel-hd';
    const title = document.createElement('span');
    title.className = 'chain-stage-panel-title';
    title.textContent = stage.title;
    hd.appendChild(title);
    hd.appendChild(makeChainResponsibilityBadge(stage));
    const meta = document.createElement('span');
    meta.className = 'chain-stage-meta';
    meta.textContent = done.length + ' 已闭环' + (active.length ? ' · ' + active.length + ' 在途' : '');
    hd.appendChild(meta);
    const tone = chainStageTone(stage, stageData);
    const metrics = document.createElement('span');
    metrics.className = 'chain-stage-panel-metrics tone-' + tone;
    metrics.textContent = stageData && stageData.summary ? stageData.summary : '';
    hd.appendChild(metrics);
    if (tone === 'pi-waiting') {
      const link = makeChainStageLink(chainStageCardRef(stageData));
      if (link) hd.appendChild(link);
    }
    panel.appendChild(hd);
    if (stage.role || stage.question) {
      const desc = document.createElement('div');
      desc.className = 'chain-stage-panel-desc';
      if (stage.role) {
        const role = document.createElement('div');
        role.className = 'chain-role';
        role.textContent = stage.role;
        desc.appendChild(role);
      }
      if (stage.question) {
        const q = document.createElement('div');
        q.className = 'chain-question';
        q.textContent = stage.question;
        desc.appendChild(q);
      }
      panel.appendChild(desc);
    }
    const cards = document.createElement('div');
    cards.className = 'chain-lane-cards';
    if (!active.length) {
      const empty = document.createElement('div');
      empty.className = 'domain-empty chain-lane-empty';
      empty.textContent = done.length ? '本阶段已闭环' : '暂无任务卡';
      cards.appendChild(empty);
    } else {
      active.forEach((task) => cards.appendChild(makeDomainCard(task)));
    }
    panel.appendChild(cards);
    return panel;
  }

  function renderGovernanceMatrix(mount) {
    // ④ 治理矩阵表：G1-G7 × 活跃工作区。数据由 /api/governance/matrix 提供。
    if (!ctx.hasApi || !ctx.api || !ctx.api.apiJson) return;
    function copyReviewPrompt() {
      copyTextToClipboard(dynamicPromptFor({ id: 'governance-probe', surfaces: ['governance'] }), '治理评审指令已复制');
    }
    function renderGovernanceProviders() {
      if (!ctx.api || !ctx.api.dynamicBoards) return;
      ctx.api.dynamicBoards().then((result) => {
        const providers = (result && Array.isArray(result.providers) ? result.providers : [])
          .filter((provider) => dynamicProviderMatchesSurface(provider, 'governance'));
        if (!providers.length) return;
        const wrap = document.createElement('div');
        wrap.className = 'gov-dynamic-list';
        providers.forEach((provider) => {
          wrap.appendChild(makeDynamicProviderCard(provider, () => renderGovernanceMatrix(mount), { showCopy: false }));
        });
        mount.appendChild(wrap);
      }).catch(() => {});
    }
    function renderProbeSummary(probe) {
      const section = document.createElement('div');
      section.className = 'gov-probe';
      const title = document.createElement('div');
      title.className = 'gov-probe-title';
      title.textContent = '探针状态（生成态）';
      const meta = document.createElement('div');
      meta.className = 'gov-probe-meta';
      meta.textContent = probe && probe.ok ? `生成于 ${probe.generated_at || '未知'} · 不覆盖正式矩阵` : (probe && probe.error ? probe.error : '尚未生成 matrix.probe.json');
      section.appendChild(title);
      section.appendChild(meta);
      if (probe && probe.ok && Array.isArray(probe.rules)) {
        const list = document.createElement('div');
        list.className = 'gov-probe-list';
        probe.rules.forEach((rule) => {
          const row = document.createElement('div');
          row.className = 'gov-probe-row';
          const label = document.createElement('span');
          label.textContent = `${rule.key} ${rule.title || ''}`;
          const states = {};
          Object.values(rule.cells || {}).forEach((cell) => {
            const key = cell && cell.state ? cell.state : 'unknown';
            states[key] = (states[key] || 0) + 1;
          });
          const value = document.createElement('b');
          value.textContent = Object.entries(states).map(([key, count]) => `${key}:${count}`).join(' · ');
          row.appendChild(label);
          row.appendChild(value);
          list.appendChild(row);
        });
        section.appendChild(list);
      }
      mount.appendChild(section);
    }
    ctx.api.apiJson('/api/governance/matrix').then(({ json }) => {
      if (!json || !json.ok || !Array.isArray(json.rules) || !json.rules.length) return;
      mount.innerHTML = '';
      const top = document.createElement('div');
      top.className = 'domain-top';
      const mark = document.createElement('div');
      mark.className = 'domain-mark';
      mark.textContent = 'GV';
      const copy = document.createElement('div');
      copy.className = 'domain-copy';
      const h = document.createElement('h2');
      h.textContent = '治理巡检矩阵';
      const sub = document.createElement('div');
      sub.className = 'domain-sub';
      sub.textContent = 'G1-G7 × 活跃工作区 · 核验于 ' + (json.verified_at || '未知');
      copy.appendChild(h);
      copy.appendChild(sub);
      top.appendChild(mark);
      top.appendChild(copy);
      const side = document.createElement('div');
      side.className = 'chain-top-side';
      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'chain-open-dashboard';
      copyBtn.textContent = '复制评审';
      copyBtn.onclick = copyReviewPrompt;
      side.appendChild(copyBtn);
      top.appendChild(side);
      mount.appendChild(top);

      const table = document.createElement('table');
      table.className = 'gov-matrix';
      const thead = document.createElement('thead');
      const headRow = document.createElement('tr');
      const corner = document.createElement('th');
      corner.textContent = '不变式';
      headRow.appendChild(corner);
      (json.workspaces || []).forEach((ws) => {
        const th = document.createElement('th');
        th.textContent = ws;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);
      const tbody = document.createElement('tbody');
      json.rules.forEach((rule) => {
        const tr = document.createElement('tr');
        const name = document.createElement('th');
        name.textContent = rule.key + ' ' + (rule.title || '');
        name.title = rule.title || '';
        tr.appendChild(name);
        (json.workspaces || []).forEach((ws) => {
          const cell = (rule.cells || {})[ws] || {};
          const td = document.createElement('td');
          td.className = 'gov-cell gov-cell-' + (cell.state || 'unknown');
          td.textContent = cell.label || { pass: '✓', warn: '⚠', drift: '漂移', unknown: '—' }[cell.state || 'unknown'] || '—';
          if (cell.note) td.title = cell.note;
          if (cell.card) {
            td.classList.add('gov-cell-link');
            td.onclick = () => ctx.renderDetail.openTaskDetail(cell.card);
          }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      mount.appendChild(table);
      if (ctx.api && ctx.api.governanceProbe) {
        ctx.api.governanceProbe().then(renderProbeSummary).catch(() => {});
      }
      renderGovernanceProviders();
    }).catch(() => {});
  }

  // 调度台只投影组合态势；完整事实、反馈和项目切换统一留在 Project Canvas。

  Object.assign(board, {
    makeNetworkStatusBlock,
    chainResponsibilityLabel,
    makeChainResponsibilityBadge,
    chainStageCardRef,
    findTaskForStageRef,
    makeChainStageLink,
    chainStateCached,
    requestChainState,
    skillStateHealthTone,
    skillStateStageMap,
    mergeSkillStageData,
    skillStateStageData,
    skillDecisionCardRef,
    makeSkillDecisionItem,
    invocationNeedsConfirm,
    runSkillInvocation,
    makeSkillInvocationButton,
    makeSkillStateBlock,
    makeSkillStateDecisionLane,
    makeChainStagePanel,
    renderGovernanceMatrix
  });
  return board;
 }
