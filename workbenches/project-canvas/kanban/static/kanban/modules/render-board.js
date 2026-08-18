export const TASK_DOMAIN_LABELS = {
  knowledge: '知识管理',
  research: '研究项目',
  governance: '治理',
  scenario: '场景库',
  team: '团队对接',
  personal: '个人调度',
};

// Project Canvas 是项目唯一工作面；调度台与治理实现保留为可召回的二级视图。
export const BOARD_VIEWS = ['projects', 'console', 'governance'];
export const BOARD_TAB_VIEWS = [];
export const BOARD_VIEW_LABELS = {
  projects: '项目画布',
  console: '调度台',
  governance: '治理',
};

export const CONSOLE_AUDIENCE_OWNER = 'owner';
export const CONSOLE_AUDIENCE_ATTENTION_GATE = 'attention_gate';
const CONSOLE_OWNER_DECISION_RE = /needs_decision|decision[_ -]?digest|decision[_ -]?log|待拍板|拍板|定调|决策|验收|审核|批准|授权|凭据|密钥|发布|删除|对外|外发|canonical|不可逆|pi-gated|PI\s*决策|gate|acceptance/i;

export function normalizeConsoleAudienceMode(value) {
  return String(value || '').trim() === CONSOLE_AUDIENCE_ATTENTION_GATE
    ? CONSOLE_AUDIENCE_ATTENTION_GATE
    : CONSOLE_AUDIENCE_OWNER;
}

export function isConsoleAttentionGateMode(value) {
  return normalizeConsoleAudienceMode(value) === CONSOLE_AUDIENCE_ATTENTION_GATE;
}

export function consoleAudienceAllows(mode, audience) {
  if (isConsoleAttentionGateMode(mode)) return true;
  return String(audience || CONSOLE_AUDIENCE_OWNER) !== CONSOLE_AUDIENCE_ATTENTION_GATE;
}

export function visibleBoardViewsForAudience(mode, views = BOARD_VIEWS) {
  return (Array.isArray(views) ? views : []);
}

const PROJECT_MAP_TASK_FAMILY_ALIASES = {
  kanban: 'kanban',
  board: 'kanban',
  '治理': 'governance',
  governance: 'governance',
  gov: 'governance',
  documents: 'documents',
  doc: 'documents',
  doctor: 'documents',
  skill: 'skill',
  skills: 'skill',
  skl: 'skill',
  knowledge: 'knowledge',
  km: 'knowledge',
  kmo: 'knowledge',
  infoops: 'knowledge',
  chain: 'chain',
  chains: 'chain',
  chn: 'chain',
  scenario: 'scenario',
  scene: 'scenario',
  scn: 'scenario',
  research: 'research',
  rsh: 'research',
  ops: 'ops',
  operation: 'ops',
};

const PROJECT_MAP_TASK_FAMILIES = new Set([
  'kanban',
  'governance',
  'documents',
  'skill',
  'knowledge',
  'chain',
  'scenario',
  'research',
  'ops',
]);

// KAN-199：类型泳道退役后卡片角落小标签的中文文案（domain 缺省时按 task_family 归一后取）。
const PROJECT_MAP_FAMILY_LABELS = {
  kanban: '看板',
  governance: '治理',
  documents: '文档',
  skill: '技能',
  knowledge: '知识管理',
  chain: '链路',
  scenario: '场景库',
  research: '研究项目',
  ops: '运维',
};

export function normalizeProjectMapFamily(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const normalized = PROJECT_MAP_TASK_FAMILY_ALIASES[raw.toLowerCase()] || PROJECT_MAP_TASK_FAMILY_ALIASES[raw] || raw.toLowerCase();
  return PROJECT_MAP_TASK_FAMILIES.has(normalized) ? normalized : '';
}

export function projectPostureModel(payload) {
  if (!payload || payload.ok !== true) return { ok: false, counts: {}, attention: [], projects: [] };
  const counts = payload.counts && typeof payload.counts === 'object' ? payload.counts : {};
  return {
    ok: true,
    counts: {
      total: Number(counts.total) || 0,
      needsOwner: Number(counts.needs_owner) || 0,
      quietActive: Number(counts.quiet_active) || 0,
      paused: Number(counts.paused) || 0,
      completed: Number(counts.completed) || 0,
      pendingChanges: Number(counts.pending_changes) || 0,
    },
    attention: Array.isArray(payload.attention) ? payload.attention : [],
    projects: Array.isArray(payload.projects) ? payload.projects : [],
  };
}

export function consoleProjectRailModel(payload) {
  const source = payload && payload.ok === true ? payload : { projects: [], attention: [] };
  const projects = Array.isArray(source.projects) ? source.projects : [];
  const attentionRefs = new Set((Array.isArray(source.attention) ? source.attention : [])
    .map((project) => String(project?.project_ref || '').trim())
    .filter(Boolean));
  const actionMeta = {
    needs_reply: { label: '需回复', tone: 'reply', order: 0 },
    needs_decision: { label: '需决策', tone: 'decision', order: 1 },
    needs_progress: { label: '需推进', tone: 'progress', order: 2 },
    no_action: { label: '安静运行', tone: 'quiet', order: 8 },
  };
  return projects.map((project) => {
    const projectRef = String(project?.project_ref || '').trim();
    const actionType = String(project?.primary_action?.type || 'no_action').trim();
    const gatedIds = (project?.attention_signals?.gated_card_ids || []).filter(Boolean);
    const lifecycle = String(project?.lifecycle || 'active').trim();
    const base = actionMeta[actionType] || actionMeta.no_action;
    const meta = gatedIds.length && actionType === 'no_action'
      ? { label: '有卡等你', tone: 'decision', order: 1 }
      : base;
    const completed = lifecycle === 'completed';
    return {
      projectRef,
      title: String(project?.title || projectRef || '未命名项目').trim(),
      label: completed ? '已完成' : meta.label,
      tone: completed ? 'complete' : meta.tone,
      order: completed ? 20 : (attentionRefs.has(projectRef) ? meta.order : meta.order + 6),
      activeTasks: Number(project?.tasks?.active_count) || 0,
    };
  }).filter((project) => project.projectRef).sort((a, b) => (
    a.order - b.order || a.title.localeCompare(b.title, 'zh-CN')
  ));
}

function normalizeTaskTags(value) {
  if (Array.isArray(value)) return value.map((tag) => String(tag || '').trim()).filter(Boolean);
  const text = String(value || '').trim();
  if (!text) return [];
  return text.split(',').map((tag) => tag.trim()).filter(Boolean);
}

function taskTagsText(value) {
  return normalizeTaskTags(value).join(' ');
}

export function dynamicProviderMatchesSurface(provider, surface) {
  const surfaces = provider && Array.isArray(provider.surfaces)
    ? provider.surfaces.map((item) => String(item || '').trim()).filter(Boolean)
    : [];
  // 兼容旧 provider：未声明 surfaces 时仍默认显示在调度台。
  if (!surfaces.length) return surface === 'console';
  return surfaces.includes(surface);
}

export function bridgeLaunchFeedback(status) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'already_running') {
    return { state: 'ready', metaLabel: '●已在运行', toastLabel: '已在运行', poll: false };
  }
  if (normalized === 'started') {
    return { state: 'ready', metaLabel: '●已就绪', toastLabel: '已就绪', poll: false };
  }
  if (normalized === 'starting') {
    return { state: 'pending', metaLabel: '◐启动中，检查端口', toastLabel: '已发起，正在确认', poll: true };
  }
  return { state: 'pending', metaLabel: '◐已发起，待确认', toastLabel: '已发起，待确认', poll: true };
}

function automationShortStamp(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  return text.replace('T', ' ').slice(5, 16);
}

function parseAutomationOutputTail(value) {
  const text = String(value || '').trim();
  if (!text || !/^[{[]/.test(text)) return null;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (e) {
    return null;
  }
}

function pushAutomationLink(links, seen, label, path, kind = 'artifact') {
  const text = String(path || '').trim();
  if (!text || seen.has(text)) return;
  seen.add(text);
  links.push({ label, path: text, kind });
}

export function automationResultLinks(task, liveResult = null) {
  const source = liveResult && typeof liveResult === 'object' ? liveResult : {};
  const links = [];
  const seen = new Set();
  pushAutomationLink(links, seen, '报告', source.last_run_md || task?.last_run_md, 'report');
  pushAutomationLink(links, seen, 'JSON', source.last_run_json || task?.last_run_json, 'json');
  pushAutomationLink(links, seen, '待审', source.pending_json || task?.pending_json, 'pending');
  pushAutomationLink(links, seen, '旧报告', source.legacy_md, 'report');
  pushAutomationLink(links, seen, '旧JSON', source.legacy_json, 'json');
  const summaryResult = source.summary_result && typeof source.summary_result === 'object' ? source.summary_result : {};
  pushAutomationLink(links, seen, '摘要', summaryResult.review_output, 'report');
  (Array.isArray(source.output_links) ? source.output_links : []).forEach((link) => {
    if (!link || typeof link !== 'object') return;
    pushAutomationLink(links, seen, link.label || '产物', link.path, link.kind || 'artifact');
  });

  (Array.isArray(source.outputs) ? source.outputs : []).forEach((output) => {
    if (!output || typeof output !== 'object') return;
    pushAutomationLink(links, seen, '产物', output.path, 'artifact');
    const parsed = parseAutomationOutputTail(output.stdout_tail);
    if (!parsed) return;
    pushAutomationLink(links, seen, '结果', parsed.result_md || parsed.result_markdown, 'report');
    pushAutomationLink(links, seen, '结果', parsed.result_json || parsed.sync_result_json, 'json');
    pushAutomationLink(links, seen, 'Chat清单', parsed.analysis_manifest, 'json');
    pushAutomationLink(links, seen, 'Chat消息', parsed.merged_messages_path, 'json');
    pushAutomationLink(links, seen, '队列', parsed.queue_jsonl, 'json');
    pushAutomationLink(links, seen, '目录', parsed.output_dir || parsed.raw_dir, 'folder');
  });
  return links;
}

export function automationResultSummary(task, liveResult = null) {
  const source = liveResult && typeof liveResult === 'object' ? liveResult : {};
  const actions = source.actions && typeof source.actions === 'object' ? source.actions : {};
  const status = String(source.status || '').trim().toLowerCase();
  const health = String(source.health || task?.health || '').trim();
  const reason = String(source.reason || task?.reason || '').trim();
  const finishedAt = source.finished_at || task?.last_checked || task?.latest_session?.timestamp || '';
  const commandBits = (Array.isArray(source.outputs) ? source.outputs : [])
    .map((output) => {
      const label = String(output?.label || '').trim();
      if (!label) return '';
      const code = output.returncode;
      return code === undefined || code === null ? label : `${label}=${code}`;
    })
    .filter(Boolean);
  let tone = 'muted';
  let label = health || '暂无记录';
  if (source.ok === false || status === 'failed' || health === '异常') {
    tone = 'error';
    label = '异常';
  } else if (actions.needs_agent_summary || actions.needs_attention || health === '需确认') {
    tone = 'confirm';
    label = actions.needs_agent_summary ? '待生成摘要' : '需确认';
  } else if (source.ok === true || status === 'completed' || health === '正常') {
    tone = 'ok';
    label = actions.preflight ? '预检通过' : '正常';
  } else if (health === '部分完成') {
    tone = 'partial';
    label = '部分完成';
  }
  const meta = [
    finishedAt ? automationShortStamp(finishedAt) : '',
    reason,
  ].filter(Boolean).join(' · ');
  return {
    tone,
    label,
    meta: meta || (task?.last_run_md || task?.last_run_json ? '有运行记录' : '尚无运行记录'),
    commands: commandBits.join(' · '),
    hasResult: Boolean(finishedAt || reason || task?.last_run_md || task?.last_run_json || source.last_run_md || source.last_run_json),
  };
}

export function normalizeFrontendChains(rawChains) {
  if (!Array.isArray(rawChains)) return [];
  return rawChains.map((raw) => {
    if (!raw || typeof raw !== 'object') return null;
    const key = String(raw.key || '').trim();
    const stages = Array.isArray(raw.stages)
      ? raw.stages.filter((stage) => stage && stage.key)
      : [];
    if (!key || !stages.length) return null;
    return {
      ...raw,
      key,
      title: String(raw.title || key).trim(),
      mark: String(raw.mark || key.slice(0, 2).toUpperCase()).trim(),
      sub: String(raw.sub || '').trim(),
      provider: String(raw.provider || '').trim(),
      stages,
    };
  }).filter(Boolean);
}

const KM_STAGE_ALIASES = {
  'km/source_intake': 'km/intake_dispatch',
  'km/zotero_master': 'km/intake_dispatch',
  'km/facts': 'km/intake_dispatch',
  'km/weekly': 'km/triage_queue',
  'km/curate': 'km/card_reading',
  'km/dispatch': 'km/evidence',
  'km/ops': 'km/synthesis',
};

const TEAM_STAGE_ALIASES = {
  'team/ingest': 'team/curate',
  'team/digest': 'team/produce',
  'team/distribute': 'team/publish',
  'team/out_internal': 'team/publish',
  'team/out_showroom': 'team/publish',
  'meeting-chain/wiki-written': 'team/publish',
};

// TODO(Owner/Claude): 真跑后定 WIP 上限、真停滞阈值、各信号扣分权重和 tier 阈值。
export const CHAIN_HEALTH_WIP_LIMIT = 6;
export const CHAIN_HEALTH_STALLED_DAYS = 14;
export const CHAIN_HEALTH_BLOCKED_PENALTY = 40;
export const CHAIN_HEALTH_WAITING_DECISION_PENALTY = 8;
export const CHAIN_HEALTH_STALLED_PENALTY_PER_DAY = 6;
export const CHAIN_HEALTH_STACK_PENALTY = 2;
export const CHAIN_HEALTH_GOOD_SCORE = 90;
export const CHAIN_HEALTH_WARN_SCORE = 70;

// TODO(Owner/Claude): 真跑截图后定 flow 节点宽度与节点间留白。
export const CHAIN_FLOW_NODE_MIN_WIDTH = 78;
export const CHAIN_FLOW_NODE_GAP = 6;

const CHAIN_HEALTH_MS_PER_DAY = 86400000;

const GOV_STAGE_ALIASES = {
  'governance/sense': 'gov/sense',
  'governance/probe': 'gov/sense',
  'governance/lint': 'gov/sense',
  'governance/triage': 'gov/triage',
  'governance/naming-enforcement': 'gov/fix',
  'governance/diagnostics': 'gov/fix',
  'governance/repo-boundary': 'gov/fix',
  'governance/p2-hardening': 'gov/fix',
  'governance/fix': 'gov/fix',
  'security/hardening': 'gov/fix',
  'governance/acceptance-standard': 'gov/accept',
  'governance/accept': 'gov/accept',
  'security/acceptance': 'gov/accept',
  'infoops/closeout': 'gov/closeout',
  'governance/closeout': 'gov/closeout',
};

function normalizedStageKey(value) {
  return String(value || '').trim().toLowerCase();
}

function mapGovernanceStageKey(value) {
  const key = normalizedStageKey(value);
  if (!key) return '';
  return GOV_STAGE_ALIASES[key] || (key.startsWith('gov/') ? key : '');
}

function taskStageExists(stages, stageKey) {
  return stages.some((stage) => stage && stage.key === stageKey);
}

function resolveStageAlias(explicitRaw, stages, aliases) {
  const mapped = aliases[explicitRaw];
  return mapped && taskStageExists(stages, mapped) ? mapped : explicitRaw;
}

function isPersonalDispatchTask(task) {
  return String((task && task.project) || '').trim() === '个人调度'
    || String((task && task.path) || '').startsWith('project/个人调度/');
}

// KAN-999：显式治理卡无 gov/* 细分 stage 时的确定性映射（代替关键词猜）：
// review → gov/accept（等验收），其余 → gov/triage（待分流）；显式 stage 永远优先（在 chainStageOf 已判）。
function deterministicGovernanceStage(task, stages) {
  if (!isExplicitGovernanceTask(task)) return null;
  const key = consoleTaskStatus(task) === 'review' ? 'gov/accept' : 'gov/triage';
  return taskStageExists(stages, key) ? key : null;
}

// KAN-999 指针：inferGovernanceStage 已退役——首行 pi-gated→gov/accept 一刀切曾把北极星业务卡
// （KAN-209 见投资人、KAN-108 课程推进）吸进治理链计成治理债；其余分支是关键词猜测，违反
// 0703「只认显式字段」先例。gov 链归属改用 isExplicitGovernanceTask + deterministicGovernanceStage。
// 定义保留供参考/回退，勿在新代码中调用。
function inferGovernanceStage(task, stages) {
  if (!task) return null;
  const text = governanceTaskText(task).toLowerCase();
  const hasSignal = hasGovernanceSignal(task);
  if (String(task.responsibility || '').trim().toLowerCase() === 'pi-gated') return 'gov/accept';
  if (!hasSignal && !isPersonalDispatchTask(task)) return null;
  if (/infoops\/closeout|closeout|detect-compression|压缩|收口|闭环|归档/.test(text)) return 'gov/closeout';
  if (isGovernanceHumanGateTask(task) || /acceptance-standard|验收|定调|拍板|pi-gated|授权|canonical|凭据|删除|对外|发布/.test(text)) return 'gov/accept';
  if (isGovernanceMachineCheckableTask(task) || /scan_governance|--lint|lint|doc-health|探针|扫描|巡检|matrix\.probe/.test(text)) return 'gov/sense';
  if (/triage|分流|判断|delta|冒泡/.test(text)) return 'gov/triage';
  if (/naming-enforcement|diagnostics|repo-boundary|p2-hardening|整改|加固|修复|命名|边界/.test(text)) return 'gov/fix';
  const fallback = hasSignal ? 'gov/fix' : 'gov/triage';
  return taskStageExists(stages, fallback) ? fallback : null;
}

function chainTaskText(task) {
  const source = task || {};
  return String([
    source.title,
    source.display_title,
    source.task_id,
    source.project,
    source.workdir,
    source.path,
    source.next_action,
    source.scenario_slug,
    taskTagsText(source.tags),
  ].filter(Boolean).join(' ')).toLowerCase();
}

export function chainStageOf(task, chain) {
  // KAN-999：链归属只认显式 stage（含既有 alias 映射）。stage.kw 关键词兜底循环已删除——
  // 未标显式归属的卡不入任何链统计（调度台人闸视角「未归类·待确认」承接）。
  // 唯一例外：显式治理卡（isExplicitGovernanceTask）无细分 stage 时走确定性映射 review→gov/accept 其余→gov/triage。
  const stages = chain && Array.isArray(chain.stages) ? chain.stages : [];
  const explicitRaw = String((task && task.stage) || '').trim();
  const chainKey = String((chain && chain.key) || '').trim();
  if (chainKey === 'gov') {
    const govExplicit = mapGovernanceStageKey(explicitRaw);
    if (govExplicit) return taskStageExists(stages, govExplicit) ? govExplicit : null;
    // 显式标了别的链的 stage → 不入 gov；治理前缀但无已知细分（如 security/decision）→ 走确定性映射。
    if (explicitRaw && !isExplicitGovernanceTask(task)) return null;
    return deterministicGovernanceStage(task, stages);
  }
  let explicit = explicitRaw;
  if (chainKey === 'km') explicit = resolveStageAlias(explicitRaw, stages, KM_STAGE_ALIASES);
  if (chainKey === 'team') explicit = resolveStageAlias(explicitRaw, stages, TEAM_STAGE_ALIASES);
  if (explicit) {
    return taskStageExists(stages, explicit) ? explicit : null;
  }
  return null;
}

function statusChangedAgeDays(task, nowMs = Date.now()) {
  if (!task || task.status_changed_at_inferred === true || String(task.status_changed_at_inferred || '').toLowerCase() === 'true') return null;
  const raw = String(task.status_changed_at || '').trim();
  if (!raw) return null;
  const parsed = Date.parse(raw);
  if (Number.isNaN(parsed)) return null;
  return Math.max(0, Math.floor((nowMs - parsed) / CHAIN_HEALTH_MS_PER_DAY));
}

function healthTaskRef(task) {
  if (!task) return '';
  return String(task.path || task.task_id || task.legacy_id || task.title || '').trim();
}

function isBlockedHealthTask(task) {
  return consoleTaskStatus(task) === 'blocked';
}

// ── KAN-999「等 Owner 动作」一本账：全板唯一的 Owner 债判定 ─────────────────
// ownerActionNeeded = 显式人闸 ∧ status∈{todo, review} ∧ 非等待中。
// 配套派生（同函数族，不另立标准）：
//   isAiProxyReviewTask = review ∧ ai-owned =「AI 代收中」（0706 验收权已下放，不计 Owner 债、不进罚分）
//   isGateInFlightTask  = in-progress ∧ pi-gated =「gate 在途」（执行中，同样不计 Owner 债）
// chainHealthScore.waitingDecision 与 buildGovernanceBurdenModel.needsDecision 全部读此判定，双入口同源必然一致。
export function ownerActionNeeded(task, person = '') {
  if (!task || isConsoleRecordTask(task)) return false;
  if (isConsoleWaitingTask(task)) return false;
  const status = consoleNormalizedStatus(task);
  if (status !== 'todo' && status !== 'review') return false;
  return hasExplicitConsoleHumanGate(task);
}

export function isAiProxyReviewTask(task) {
  if (!task || isConsoleRecordTask(task)) return false;
  return consoleNormalizedStatus(task) === 'review'
    && String(task.responsibility || '').trim().toLowerCase() === 'ai-owned';
}

export function isGateInFlightTask(task) {
  if (!task) return false;
  return ['in-progress', 'in_progress', 'doing'].includes(consoleNormalizedStatus(task))
    && String(task.responsibility || '').trim().toLowerCase() === 'pi-gated';
}

// KAN-999 指针：isWaitingDecisionTask 已退役（旧「等你」= pi-gated ∨ 所有 review 卡，与人闸台账
// 同名不同义、且把 AI 代收中的 review 卡计成 Owner 债）。链健康计数改读 ownerActionNeeded。定义保留供参考。
function isWaitingDecisionTask(task, person = '') {
  if (!task || consoleTaskStatus(task) === 'done') return false;
  const responsibility = String(task.responsibility || '').trim().toLowerCase();
  if (responsibility === 'pi-gated') return true;
  return isConsoleReviewTask(task, person);
}

export function chainHealthScore(chain, tasks, nowMs = Date.now(), person = '') {
  const stages = chain && Array.isArray(chain.stages) ? chain.stages : [];
  const stageStats = Object.create(null);
  stages.forEach((stage) => {
    if (!stage || !stage.key) return;
    stageStats[stage.key] = {
      stageKey: stage.key,
      stageTitle: stage.title || stage.key,
      responsibility: stage.responsibility || 'shared',
      active: 0,
      done: 0,
      total: 0,
      wipLimit: CHAIN_HEALTH_WIP_LIMIT,
      stackOver: 0,
      blockedCount: 0,
      waitingDecisionCount: 0,
      aiProxyReviewCount: 0,
      stalledCount: 0,
      stalledOverDays: 0,
      refs: [],
      blockedRefs: [],
      waitingDecisionRefs: [],
      aiProxyReviewRefs: [],
      stalledRefs: [],
    };
  });

  (Array.isArray(tasks) ? tasks : []).forEach((task) => {
    if (!task || isTeamKanbanPointerTask(task)) return;
    const stageKey = chainStageOf(task, chain);
    const stat = stageStats[stageKey];
    if (!stat) return;
    stat.total += 1;
    const status = consoleTaskStatus(task);
    if (status === 'done') {
      stat.done += 1;
      return;
    }
    stat.active += 1;
    const ref = healthTaskRef(task);
    if (ref) stat.refs.push(ref);
    if (isBlockedHealthTask(task)) {
      stat.blockedCount += 1;
      if (ref) stat.blockedRefs.push(ref);
    }
    // KAN-999：等你 = ownerActionNeeded（pi-gated ∧ todo/review）一本账；AI 代收中单列不计 Owner 债。
    if (ownerActionNeeded(task, person)) {
      stat.waitingDecisionCount += 1;
      if (ref) stat.waitingDecisionRefs.push(ref);
    }
    if (isAiProxyReviewTask(task)) {
      stat.aiProxyReviewCount += 1;
      if (ref) stat.aiProxyReviewRefs.push(ref);
    }
    const statusAge = statusChangedAgeDays(task, nowMs);
    if (statusAge !== null && statusAge > CHAIN_HEALTH_STALLED_DAYS) {
      stat.stalledCount += 1;
      stat.stalledOverDays += statusAge - CHAIN_HEALTH_STALLED_DAYS;
      if (ref) stat.stalledRefs.push(ref);
    }
  });

  const stats = Object.values(stageStats);
  stats.forEach((stat) => {
    stat.stackOver = Math.max(0, stat.active - stat.wipLimit);
  });
  const blockedCount = stats.reduce((sum, stat) => sum + stat.blockedCount, 0);
  const waitingDecisionCount = stats.reduce((sum, stat) => sum + stat.waitingDecisionCount, 0);
  const aiProxyReviewCount = stats.reduce((sum, stat) => sum + stat.aiProxyReviewCount, 0);
  const stalledOverDays = stats.reduce((sum, stat) => sum + stat.stalledOverDays, 0);
  const stackedOver = stats.reduce((sum, stat) => sum + stat.stackOver, 0);
  const blockedPenalty = blockedCount * CHAIN_HEALTH_BLOCKED_PENALTY;
  const waitingPenalty = waitingDecisionCount * CHAIN_HEALTH_WAITING_DECISION_PENALTY;
  const stalledPenalty = stalledOverDays * CHAIN_HEALTH_STALLED_PENALTY_PER_DAY;
  const stackPenalty = stackedOver * CHAIN_HEALTH_STACK_PENALTY;
  const score = Math.max(0, Math.round(100 - blockedPenalty - waitingPenalty - stalledPenalty - stackPenalty));
  const tier = blockedCount > 0 ? 'bad' : (score >= CHAIN_HEALTH_GOOD_SCORE ? 'good' : (score >= CHAIN_HEALTH_WARN_SCORE ? 'warn' : 'bad'));

  const bottleneck = stats
    .map((stat) => {
      const blockedWeight = stat.blockedCount * CHAIN_HEALTH_BLOCKED_PENALTY;
      const waitingWeight = stat.waitingDecisionCount * CHAIN_HEALTH_WAITING_DECISION_PENALTY;
      const stalledWeight = stat.stalledOverDays * CHAIN_HEALTH_STALLED_PENALTY_PER_DAY;
      const stackWeight = stat.stackOver * CHAIN_HEALTH_STACK_PENALTY;
      let reason = '在途';
      if (stat.blockedCount > 0) reason = `卡死 ${stat.blockedCount}`;
      else if (stat.waitingDecisionCount > 0) reason = `等你 ${stat.waitingDecisionCount}`;
      else if (stat.stalledCount > 0) reason = `真停滞 ${stat.stalledCount}`;
      else if (stat.stackOver > 0) reason = `堆叠 +${stat.stackOver}`;
      const weight = Math.max(blockedWeight, waitingWeight, stalledWeight, stackWeight, stat.active > 0 ? 0.1 : 0);
      const refs = stat.blockedRefs.length ? stat.blockedRefs
        : (stat.waitingDecisionRefs.length ? stat.waitingDecisionRefs
          : (stat.stalledRefs.length ? stat.stalledRefs : stat.refs));
      return { ...stat, reason, weight, refs };
    })
    .sort((a, b) => {
      if (b.weight !== a.weight) return b.weight - a.weight;
      if (b.active !== a.active) return b.active - a.active;
      return String(a.stageKey).localeCompare(String(b.stageKey));
    })[0] || null;

  return {
    score,
    tier,
    bottleneck: bottleneck ? {
      stageKey: bottleneck.stageKey,
      stageTitle: bottleneck.stageTitle,
      reason: bottleneck.reason,
      activeCount: bottleneck.active,
      stackOver: bottleneck.stackOver,
      blockedCount: bottleneck.blockedCount,
      waitingDecisionCount: bottleneck.waitingDecisionCount,
      stalledCount: bottleneck.stalledCount,
      refs: bottleneck.refs,
    } : null,
    signals: {
      blocked: blockedCount,
      waitingDecision: waitingDecisionCount,
      // KAN-999：AI 代收中（review ∧ ai-owned）单列弱信号，不进罚分、不计 Owner 债。
      aiProxyReview: aiProxyReviewCount,
      stalled: stats.reduce((sum, stat) => sum + stat.stalledCount, 0),
      stackOver: stackedOver,
    },
    penalties: {
      blocked: blockedPenalty,
      waitingDecision: waitingPenalty,
      stalled: stalledPenalty,
      stack: stackPenalty,
    },
    stageStats,
  };
}

export function buildChainStageBuckets(tasks, chains) {
  const byChain = Object.create(null);
  const chainList = Array.isArray(chains) ? chains : [];
  chainList.forEach((chain) => {
    if (!chain || !chain.key) return;
    const byStage = Object.create(null);
    (Array.isArray(chain.stages) ? chain.stages : []).forEach((stage) => {
      if (stage && stage.key) byStage[stage.key] = [];
    });
    byChain[chain.key] = byStage;
  });

  const unassigned = [];
  (Array.isArray(tasks) ? tasks : []).forEach((task) => {
    const explicit = String((task && task.stage) || '').trim();
    if (!explicit && isTeamKanbanPointerTask(task)) return;
    let matched = false;
    for (const chain of chainList) {
      if (!chain || !chain.key) continue;
      const stageKey = chainStageOf(task, chain);
      if (!stageKey) continue;
      const byStage = byChain[chain.key];
      if (byStage) {
        if (!byStage[stageKey]) byStage[stageKey] = [];
        byStage[stageKey].push(task);
      }
      matched = true;
      if (!explicit) break;
    }
    if (!matched && String((task && task.status) || 'todo') !== 'done' && !isTeamKanbanPointerTask(task)) {
      unassigned.push(task);
    }
  });

  return { byChain, unassigned };
}

export function chainStatusTone(state, responsibility) {
  const normalized = String(state || '').trim().toLowerCase();
  const owner = String(responsibility || '').trim();
  if (normalized === 'failed' || normalized === 'failure' || normalized === 'drift') return 'error';
  if (normalized === 'pi-gated-waiting' || (normalized === 'waiting' && owner === 'pi-gated')) return 'pi-waiting';
  if (normalized === 'warn' || normalized === 'stale') return 'warn';
  if (normalized === 'ok' || normalized === 'fresh') return 'ok';
  return 'neutral';
}

export function chainStageTone(stage, stageData) {
  const responsibility = stage && stage.responsibility;
  const state = stageData && stageData.state;
  return chainStatusTone(state, responsibility);
}

export function normalizeConsoleAiMembers(rawMembers) {
  const members = rawMembers instanceof Set
    ? Array.from(rawMembers)
    : Array.isArray(rawMembers) ? rawMembers : [];
  return new Set(members.map((member) => String(member || '').trim()).filter(Boolean));
}

export function consoleTaskStatus(task) {
  return String((task && task.status) || 'todo').trim() || 'todo';
}

export function consoleTaskAssignee(task) {
  return String((task && task.assignee) || '').trim();
}

export function consoleAssigneeIsAi(task, aiMembers) {
  return normalizeConsoleAiMembers(aiMembers).has(consoleTaskAssignee(task));
}

const CONSOLE_HUMAN_SCOPES = new Set(['owner', 'human', 'decision', 'acceptance']);
const CONSOLE_TERMINAL_STATUSES = new Set(['done', 'archived', 'cancelled', 'canceled']);
const CONSOLE_WORK_STATUSES = new Set(['todo', 'in-progress', 'in_progress', 'doing']);
const CONSOLE_WAITING_STATUSES = new Set(['waiting', 'blocked', 'on-hold', 'on_hold', 'paused']);
const CONSOLE_PARKED_STATUSES = new Set(['backlog', 'parked', 'someday']);

function consoleNormalizedStatus(task) {
  return consoleTaskStatus(task).trim().toLowerCase();
}

function consoleTruthy(value) {
  return value === true || ['1', 'true', 'yes', 'y', 'on'].includes(String(value || '').trim().toLowerCase());
}

export function hasExplicitConsoleHumanGate(task) {
  if (!task) return false;
  const scope = String(task.attention_scope || task.audience || '').trim().toLowerCase();
  const responsibility = String(task.responsibility || '').trim().toLowerCase();
  return consoleTruthy(task.human_gate)
    || CONSOLE_HUMAN_SCOPES.has(scope)
    || responsibility === 'pi-gated';
}

export function isConsoleRecordTask(task) {
  if (!task) return false;
  if (hasExplicitConsoleHumanGate(task)) return false;
  if (String(task.doc_type || '').trim().toLowerCase() === 'record') return true;
  const kind = String(task.kind || '').trim().toLowerCase();
  if (kind === 'record') return true;
  const recordTag = normalizeTaskTags(task.tags).some((tag) => /^(record|record-card(-backfill)?|off-ledger-backfill|conversation-map-backfill|generated-record)$/i.test(tag));
  if (recordTag) return true;
  return /^(archive-map-watcher(?:\/|$)|conversation-map\/backfill|governance\/[^\s]*backfill)/i.test(String(task.source || '').trim());
}

export function isConsoleRecordExceptionTask(task) {
  if (!isConsoleRecordTask(task)) return false;
  const status = consoleTaskStatus(task).toLowerCase();
  if (['done', 'archived', 'cancelled', 'canceled'].includes(status)) return false;
  return Boolean(task && (
    task.failure_acknowledged_at
    || task.failure_at
    || task.failed_at
    || task.last_failure_at
    || ['failed', 'error', 'blocked'].includes(status)
  ));
}

function consoleHasWaitingSignal(task) {
  if (!task) return false;
  const waitingOn = task.waiting_on ?? task.blocked_by;
  if (Array.isArray(waitingOn)) return waitingOn.length > 0;
  const normalized = String(waitingOn || '').trim().toLowerCase();
  if (normalized && !['[]', 'none', 'null', 'false', 'no'].includes(normalized)) return true;
  return CONSOLE_WAITING_STATUSES.has(consoleNormalizedStatus(task));
}

export function isConsoleWaitingTask(task) {
  if (!task || isConsoleRecordTask(task)) return false;
  if (CONSOLE_TERMINAL_STATUSES.has(consoleNormalizedStatus(task))) return false;
  return consoleHasWaitingSignal(task);
}

function consoleTaskRoutingText(task) {
  if (!task) return '';
  const tags = taskTagsText(task.tags);
  return [
    task.next_action,
    task.title,
    task.display_title,
    task.task_id,
    task.source,
    tags,
  ].map((part) => String(part || '')).join(' ');
}

function consoleAudienceTaskText(task) {
  if (!task) return '';
  return [
    consoleTaskRoutingText(task),
    task.responsibility,
    task.safety,
    task.domain,
    task.stage,
    task.workdir,
    task.path,
  ].map((part) => String(part || '')).join(' ');
}

export function isConsoleOwnerDecisionTask(task, person = 'Owner') {
  if (!ownerActionNeeded(task, person)) return false;
  return consoleNormalizedStatus(task) === 'todo' || isConsolePreExecutionGateTask(task, person);
}

export function consoleInboxAudience(task, person = 'Owner') {
  return ownerActionNeeded(task, person) || consoleTaskAssignee(task).toLowerCase() === String(person || 'Owner').trim().toLowerCase()
    ? CONSOLE_AUDIENCE_OWNER
    : CONSOLE_AUDIENCE_ATTENTION_GATE;
}

export function isConsolePreExecutionGateTask(task, person) {
  if (isConsoleRecordTask(task)) return false;
  if (consoleNormalizedStatus(task) !== 'review') return false;
  if (!ownerActionNeeded(task, person)) return false;
  const text = consoleTaskRoutingText(task);
  return /通过后\s*派|通过后[^，。；;]*执行|待\s*PI\s*审核方案|重点拍板|PI\s*决策点|拍板[^，。；;]*执行|方案[^，。；;]*通过后/i.test(text);
}

export function isConsoleReviewTask(task, person = '') {
  return ownerActionNeeded(task, person)
    && consoleNormalizedStatus(task) === 'review'
    && !isConsolePreExecutionGateTask(task, person);
}

export function isConsoleInboxTask(task) {
  if (isConsoleRecordTask(task)) return false;
  if (consoleNormalizedStatus(task) !== 'todo' || !task || !task.source || consoleTaskAssignee(task)) return false;
  if (hasExplicitConsoleHumanGate(task)) return false;
  return !String(task.responsibility || '').trim();
}

export function isTeamKanbanPointerTask(task) {
  return String((task && task.source) || '').startsWith('team-kanban/');
}

export function isPinnedTeamKanbanPointerTask(task) {
  if (!isTeamKanbanPointerTask(task)) return false;
  const value = task && (
    task.pin_to_console ||
    task.console_pin ||
    task.show_in_console
  );
  return value === true || ['true', 'yes', '1', 'pinned'].includes(String(value || '').toLowerCase());
}

export function isConsolePendingAiDispatchTask(task, aiMembers) {
  if (isConsoleRecordTask(task)) return false;
  const responsibility = String(task.responsibility || '').trim().toLowerCase();
  return consoleNormalizedStatus(task) === 'todo'
    && (consoleAssigneeIsAi(task, aiMembers) || responsibility === 'ai-owned')
    && !ownerActionNeeded(task)
    && !isConsoleWaitingTask(task)
    && !isConsoleInboxTask(task)
    && !isTeamKanbanPointerTask(task);
}

export function consoleTaskRoutingLane(task, person = 'Owner', aiMembers = []) {
  if (!task) return 'unrouted';
  if (isConsoleRecordTask(task)) return 'record';
  const status = consoleNormalizedStatus(task);
  if (CONSOLE_TERMINAL_STATUSES.has(status)) return 'done';
  if (isTeamKanbanPointerTask(task)) return 'team';
  if (isConsoleWaitingTask(task)) return 'waiting';
  if (CONSOLE_PARKED_STATUSES.has(status)) return 'parked';
  if (isConsolePreExecutionGateTask(task, person) || isConsoleOwnerDecisionTask(task, person)) return 'decision';
  if (isConsoleReviewTask(task, person)) return 'review';

  const assignee = consoleTaskAssignee(task).toLowerCase();
  const current = String(person || 'Owner').trim().toLowerCase();
  if (current && assignee === current && CONSOLE_WORK_STATUSES.has(status)) return 'today';

  const responsibility = String(task.responsibility || '').trim().toLowerCase();
  const activeAiStatus = CONSOLE_WORK_STATUSES.has(status) || status === 'review';
  if (activeAiStatus && (consoleAssigneeIsAi(task, aiMembers) || responsibility === 'ai-owned')) return 'ai-work';
  if (isConsoleInboxTask(task)) return 'triage';
  return 'unrouted';
}

export function isConsoleGlobalDispatchTask(task, lane, options = {}) {
  if (!task) return false;
  if (!String(task.project_ref || '').trim()) return true;
  if (['decision', 'review', 'waiting'].includes(lane)) return true;
  if (lane === 'ai-work') return consoleNormalizedStatus(task) !== 'todo';
  if (lane === 'today') return Boolean(options.dueNow);
  return false;
}

export function isConsoleTodayTask(task, person, aiMembers = []) {
  return consoleTaskRoutingLane(task, person, aiMembers) === 'today';
}

export function isConsoleAiWorkTask(task, aiMembers, person = 'Owner') {
  return consoleTaskRoutingLane(task, person, aiMembers) === 'ai-work';
}

export function isConsoleCanvasTask(task) {
  if (isConsoleRecordTask(task)) return false;
  if (consoleTaskStatus(task) === 'done') return false;
  return Boolean(task && (String(task.canvas_ref || '').trim() || String(task.canvas_schema || '').trim()));
}

export function isConsoleUnroutedTask(task, person, aiMembers = []) {
  return consoleTaskRoutingLane(task, person, aiMembers) === 'unrouted';
}

export const CONSOLE_AI_DONE_RECENT_DAYS = 3;
const CONSOLE_MS_PER_DAY = 86400000;

function consoleRecentDoneStamp(task) {
  return String((task && (task.updated || task.status_changed_at || task.created)) || '').trim();
}

export function isConsoleRecentAiDoneTask(task, aiMembers, windowDays = CONSOLE_AI_DONE_RECENT_DAYS, nowMs = Date.now()) {
  if (isConsoleRecordTask(task)) return false;
  if (consoleTaskStatus(task) !== 'done') return false;
  if (!consoleAssigneeIsAi(task, aiMembers)) return false;
  if (isTeamKanbanPointerTask(task)) return false;
  const stamp = consoleRecentDoneStamp(task);
  if (!stamp) return false;
  const parsed = Date.parse(stamp);
  if (Number.isNaN(parsed)) return false;
  const days = Number.isFinite(Number(windowDays)) ? Number(windowDays) : CONSOLE_AI_DONE_RECENT_DAYS;
  const ageMs = nowMs - parsed;
  return ageMs >= 0 && ageMs <= Math.max(0, days) * CONSOLE_MS_PER_DAY;
}

export function consoleRecentAiDoneTasks(tasks, aiMembers, windowDays = CONSOLE_AI_DONE_RECENT_DAYS, nowMs = Date.now()) {
  return (Array.isArray(tasks) ? tasks : [])
    .filter((task) => isConsoleRecentAiDoneTask(task, aiMembers, windowDays, nowMs))
    .sort((a, b) => consoleRecentDoneStamp(b).localeCompare(consoleRecentDoneStamp(a)));
}

function landingDateKey(value) {
  return String(value || '').trim().slice(0, 10);
}

export function landingPageDriftState(task) {
  const updated = landingDateKey(task && task.updated);
  const landingUpdated = landingDateKey(task && task.landing_updated);
  const stale = Boolean(updated && (!landingUpdated || updated > landingUpdated));
  return {
    stale,
    updated,
    landingUpdated,
    label: stale ? '需刷新' : '已同步',
  };
}

export function landingPageTasks(tasks) {
  return (Array.isArray(tasks) ? tasks : [])
    .filter((task) => task && String(task.landing_page || '').trim())
    .slice()
    .sort((a, b) => {
      const driftDelta = Number(landingPageDriftState(b).stale) - Number(landingPageDriftState(a).stale);
      if (driftDelta) return driftDelta;
      const aDate = landingDateKey(a.landing_updated || a.updated || a.created);
      const bDate = landingDateKey(b.landing_updated || b.updated || b.created);
      if (aDate !== bDate) return bDate.localeCompare(aDate);
      return String(a.title || a.display_title || '').localeCompare(String(b.title || b.display_title || ''), 'zh-Hans-CN');
    });
}

const GOVERNANCE_TASK_FAMILIES = new Set(['governance', 'documents', 'skill']);
const GOVERNANCE_TASK_ID_RE = /^(GOV|DOC|SKL)-/i;
// KAN-999 指针：两张关键词网在路由路径已全部退役（0703 先例「家族治理只认显式字段」的收尾）。
// KANBAN_GOVERNANCE_RE 自 0703 起已不用于路由；GOVERNANCE_SIGNAL_RE 曾是 hasGovernanceSignal 的
// 文本兜底，治理域成员判定改为 isExplicitGovernanceTask（纯显式字段）后不再被路由调用。定义保留供参考。
const KANBAN_GOVERNANCE_RE = /治理|规则|调度台|看板|决策|验收|队列|gate|压缩|矩阵|探针|状态页|skill-state|needs_decision|decision_log|scan_governance|lint/i;
const GOVERNANCE_SIGNAL_RE = /治理|documents.?体检|doc-health|scan_governance|matrix\.probe|decision_log|decision log|skill-state|治理巡检|验收标准|凭据安全|密钥|secret|doc_type|工作区体检|压缩触发/i;
const HUMAN_GATE_RE = /needs_decision|待拍板|拍板|pi-gated|PI\s*决策|凭据|发布|删除|对外|轮换|授权|新\s*canonical|合并\s*canonical|不可逆/i;
const MACHINE_CHECK_RE = /scan_governance|matrix\.probe|--lint|lint|探针|扫描|检测|watchdog|看门狗|deterministic|自动验收|sweep-auto|infer-responsibility|detect-compression/i;

function governanceTaskText(task) {
  const source = task || {};
  return String([
    source.title,
    source.display_title,
    source.task_id,
    source.legacy_id,
    source.project,
    source.task_family,
    source.execution_profile,
    source.domain,
    source.stage,
    source.workdir,
    source.path,
    source.next_action,
    source.source,
    source.responsibility,
    source.safety,
    taskTagsText(source.tags),
  ].filter(Boolean).join(' '));
}

// KAN-999：治理域成员判定 = 纯显式字段，无任何关键词猜测。
// ① 有显式 stage 时 stage 说了算（显式 stage 永远优先）：治理前缀（gov/、governance/、security/，
//    含 GOV_STAGE_ALIASES 未收录的细分如 security/decision）→ 治理域；标了别的链的 stage
//    （km/、team/ 等）→ 不是治理域（哪怕 domain=governance）。
// ② 无显式 stage 时看其余显式字段：task_family∈{governance,documents,skill} ∨ task_id 前缀 GOV-/DOC-/SKL-
//    ∨ domain==='governance' ∨ tags 含 governance。
// 与 chainStageOf 的 gov 链归属同构——治理页计数与治理链健康行必然同一批卡。
export function isExplicitGovernanceTask(task) {
  if (!task) return false;
  const stage = normalizedStageKey(task.stage);
  if (stage) {
    return stage.startsWith('gov/')
      || stage.startsWith('governance/')
      || stage.startsWith('security/')
      || Boolean(GOV_STAGE_ALIASES[stage]);
  }
  const family = String(task.task_family || '').trim().toLowerCase();
  const id = String(task.task_id || task.legacy_id || '').trim();
  const domain = String(task.domain || '').trim().toLowerCase();
  const tags = normalizeTaskTags(task.tags).map((tag) => tag.toLowerCase());
  if (GOVERNANCE_TASK_FAMILIES.has(family)) return true;
  if (GOVERNANCE_TASK_ID_RE.test(id)) return true;
  if (domain === 'governance') return true;
  return tags.includes('governance');
}

// KAN-999 指针：hasGovernanceSignal 已退役于路由路径（旧行为 = 显式字段之外还吃
// GOVERNANCE_SIGNAL_RE 文本兜底 + source 前缀）。治理域成员判定改用 isExplicitGovernanceTask。
// 定义保留供参考/回退，勿在新代码中调用。
function hasGovernanceSignal(task) {
  if (!task) return false;
  const family = String(task.task_family || '').trim().toLowerCase();
  const id = String(task.task_id || task.legacy_id || '').trim();
  const domain = String(task.domain || '').trim().toLowerCase();
  const stage = String(task.stage || '').trim().toLowerCase();
  const source = String(task.source || '').trim().toLowerCase();
  const tags = normalizeTaskTags(task.tags).map((tag) => tag.toLowerCase());
  const text = governanceTaskText(task);
  if (GOVERNANCE_TASK_FAMILIES.has(family)) return true;
  if (GOVERNANCE_TASK_ID_RE.test(id)) return true;
  if (domain === 'governance' || tags.includes('governance') || tags.includes('security')) return true;
  if (stage.startsWith('governance/') || stage.startsWith('security/')) return true;
  if (source.startsWith('documents-doctor/') || source.startsWith('governance/')) return true;
  // Fix 2(2026-07-03,Owner 拍板):kanban 家族=产品线,不再吃关键词网。
  // 结构化治理信号(domain/tags/stage/GOV|DOC|SKL 前缀)已在上方分支判过;
  // 走到这里的 kanban/KAN-* 卡一律视为产品工作——分类靠显式字段,不猜标题。
  // (旧行为:KANBAN_GOVERNANCE_RE 命中「看板/调度台/验收/队列」即扫走,曾吞掉 44% 活跃卡)
  if (family === 'kanban' || /^KAN-/i.test(id)) return false;
  return GOVERNANCE_SIGNAL_RE.test(text);
}

export function isGovernanceBurdenTask(task) {
  // Fix 1 不变量(2026-07-03,Owner 拍板):status=review 无条件豁免治理分流——
  // 验收 gate 是人的决策面,任何分类器不得从「等我验收」抢卡;治理分流只作用于 todo/in-progress。
  // KAN-999:治理身份判定从 hasGovernanceSignal（含关键词兜底）收紧为 isExplicitGovernanceTask（纯显式）。
  const status = task ? consoleTaskStatus(task) : '';
  if (status === 'review') return false;
  return Boolean(task && status !== 'done' && isExplicitGovernanceTask(task));
}

export function isGovernanceConsoleHiddenTask(task) {
  // KAN-999:与 isGovernanceBurdenTask 同源，只认显式字段。
  return isExplicitGovernanceTask(task);
}

export function governanceBurdenBucket(task) {
  const family = String((task && task.task_family) || '').trim().toLowerCase();
  const id = String((task && (task.task_id || task.legacy_id)) || '').trim();
  const text = String([
    task && task.title,
    task && task.display_title,
    task && task.task_family,
    task && task.execution_profile,
    task && task.stage,
    task && task.next_action,
    task && task.source,
    taskTagsText(task && task.tags),
  ].filter(Boolean).join(' ')).toLowerCase();
  if (family === 'kanban' || /^KAN-/i.test(id) || /kanban|看板|调度台|队列|验收泳道|压缩触发/.test(text)) return 'kanban';
  if (family === 'skill' || /^SKL-/i.test(id) || /skill|技能|skill-state/.test(text)) return 'skills';
  return 'rules';
}

export function governanceHealthcheckToastText(result) {
  const source = result && typeof result === 'object' ? result : {};
  if (source.ok === false) {
    return source.error || source.reason || '治理体检运行失败';
  }
  const suffix = [source.health, source.reason].filter(Boolean).join(' · ');
  return suffix ? `治理体检完成：${suffix}` : '治理体检完成';
}

export function governanceHealthcheckScheduleItem(schedule, id = 'governance_scan') {
  if (!schedule || typeof schedule !== 'object') return null;
  const pools = []
    .concat(Array.isArray(schedule.active) ? schedule.active : [])
    .concat(Array.isArray(schedule.inactive) ? schedule.inactive : []);
  return pools.find((item) => item && String(item.id || '') === id) || null;
}

export function governanceHealthcheckStatusText(schedule) {
  if (!schedule) return '读取中';
  if (schedule.ok === false) return '读取失败';
  const item = governanceHealthcheckScheduleItem(schedule);
  if (!item) return '未配置';
  if (String(item.status || '').toUpperCase() !== 'ACTIVE') return '已停用';
  return item.health || '暂无记录';
}

export function governanceHealthcheckStatusTone(schedule) {
  if (!schedule) return 'muted';
  if (schedule.ok === false) return 'bad';
  const item = governanceHealthcheckScheduleItem(schedule);
  if (!item || String(item.status || '').toUpperCase() !== 'ACTIVE') return 'muted';
  if (item.health === '正常') return 'good';
  if (item.health === '异常') return 'bad';
  if (item.health === '需确认' || item.health === '部分完成') return 'running';
  return 'muted';
}

export function governanceHealthcheckRunStatusText(status) {
  if (!status) return '读取中';
  if (status.ok === false) return '读取失败';
  const latest = status.latest;
  if (!latest) return '尚未运行';
  return latest.health || '已记录';
}

export function governanceHealthcheckRunStatusTone(status) {
  if (!status) return 'muted';
  if (status.ok === false) return 'bad';
  const latest = status.latest;
  if (!latest) return 'muted';
  if (latest.service_restart_required || latest.health === '服务待重启') return 'running';
  if (latest.health === '异常' || Number(latest.failed_command_count || 0) > 0) return 'bad';
  if (latest.health === '有信号' || latest.health === '需确认' || latest.health === '部分完成') return 'running';
  if (latest.health === '正常') return 'good';
  return 'muted';
}

export function governanceNoiseReviewStatusText(status) {
  const latest = status && status.latest;
  if (!latest) return '尚未运行';
  const id = latest.id ? `#${String(latest.id).slice(0, 8)}` : '';
  const parts = [id].filter(Boolean).join(' · ');
  if (latest.status === 'queued') return parts ? `排队中 · ${parts}` : '排队中';
  if (latest.status === 'running') return parts ? `运行中 · ${parts}` : '运行中';
  if (latest.status === 'completed') {
    return parts ? `已完成 · ${parts}` : '已完成';
  }
  if (['error', 'timeout', 'killed'].includes(latest.status)) return parts ? `需查看 · ${parts}` : '需查看';
  return parts || '状态未知';
}

export function governanceNoiseReviewStatusTone(status) {
  const latest = status && status.latest;
  if (!latest) return 'muted';
  if (latest.status === 'completed' && !latest.parse_error && !latest.governance_noise_record_error) return 'good';
  if (latest.status === 'running' || latest.status === 'queued') return 'running';
  if (['error', 'timeout', 'killed'].includes(latest.status) || latest.parse_error || latest.governance_noise_record_error) return 'bad';
  return 'muted';
}

function governanceShortStamp(value) {
  if (!value) return '';
  return String(value).replace('T', ' ').slice(5, 16);
}

function governancePercent(value) {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'string') return value.includes('%') ? value : value;
  const pct = Number(value);
  if (!Number.isFinite(pct)) return '';
  const normalized = pct <= 1 ? pct * 100 : pct;
  return (Math.round(normalized * 10) / 10).toString().replace(/\.0$/, '') + '%';
}

export function isGovernanceHumanGateTask(task, person = '') {
  if (!task) return false;
  const responsibility = String(task.responsibility || '').trim().toLowerCase();
  const safety = String(task.safety || '').trim().toLowerCase();
  const assignee = consoleTaskAssignee(task);
  const current = String(person || '').trim();
  const reviewForPerson = consoleTaskStatus(task) === 'review' && (!assignee || !current || assignee === current);
  if (responsibility === 'pi-gated') return true;
  if (['mutating', 'external', 'irreversible'].includes(safety)) return true;
  if (reviewForPerson) return true;
  return HUMAN_GATE_RE.test(governanceTaskText(task));
}

export function isGovernanceMachineCheckableTask(task) {
  return Boolean(task && MACHINE_CHECK_RE.test(governanceTaskText(task)));
}

export function isGovernanceAiReducibleTask(task, aiMembers = [], person = '') {
  if (!task || isGovernanceHumanGateTask(task, person)) return false;
  const responsibility = String(task.responsibility || '').trim().toLowerCase();
  const safety = String(task.safety || '').trim().toLowerCase();
  return responsibility === 'ai-owned'
    || ['read-only', 'reversible'].includes(safety)
    || consoleAssigneeIsAi(task, aiMembers)
    || isGovernanceMachineCheckableTask(task);
}

export function buildGovernanceBurdenModel(tasks, aiMembers = [], person = '') {
  const bucketLabels = {
    kanban: '看板治理',
    skills: 'Skill治理',
    rules: '规则/账本',
  };
  // KAN-999：members = 治理域全部活跃卡（含 review，与 gov 链健康统计同一批）；
  // active = 其中占治理泳道位的（review 留在「等我验收」，Fix 1 不变量）。
  const members = (Array.isArray(tasks) ? tasks : [])
    .filter((task) => task && consoleTaskStatus(task) !== 'done' && isExplicitGovernanceTask(task));
  const active = members
    .filter((task) => consoleTaskStatus(task) !== 'review')
    .sort((a, b) => {
      const gateDelta = Number(isGovernanceHumanGateTask(b, person)) - Number(isGovernanceHumanGateTask(a, person));
      if (gateDelta) return gateDelta;
      return String(b.updated || b.created || '').localeCompare(String(a.updated || a.created || ''));
    });
  const buckets = Object.fromEntries(Object.entries(bucketLabels).map(([key, label]) => [key, {
    key,
    label,
    count: 0,
    humanGate: 0,
    aiReducible: 0,
    machineCheckable: 0,
    nextTask: null,
    tasks: [],
  }]));

  active.forEach((task) => {
    const key = governanceBurdenBucket(task);
    const bucket = buckets[key] || buckets.rules;
    bucket.count += 1;
    if (!bucket.nextTask) bucket.nextTask = task;
    bucket.tasks.push(task);
    if (isGovernanceHumanGateTask(task, person)) bucket.humanGate += 1;
    if (isGovernanceAiReducibleTask(task, aiMembers, person)) bucket.aiReducible += 1;
    if (isGovernanceMachineCheckableTask(task)) bucket.machineCheckable += 1;
  });

  // KAN-999：needsDecision 改读 ownerActionNeeded（pi-gated ∧ todo/review）一本账，
  // 与 chainHealthScore.waitingDecision 同源；AI 代收中 / gate 在途单列，不计 Owner 债。
  const ownerActionTasks = members
    .filter((task) => ownerActionNeeded(task, person))
    .sort((a, b) => {
      const statusDelta = Number(consoleTaskStatus(b) === 'review') - Number(consoleTaskStatus(a) === 'review');
      if (statusDelta) return statusDelta;
      return String(b.updated || b.created || '').localeCompare(String(a.updated || a.created || ''));
    });
  return {
    total: members.length,
    needsDecision: ownerActionTasks.length,
    ownerActionTasks,
    aiProxyReview: members.filter(isAiProxyReviewTask).length,
    gateInFlight: members.filter(isGateInFlightTask).length,
    aiReducible: active.filter((task) => isGovernanceAiReducibleTask(task, aiMembers, person)).length,
    machineCheckable: active.filter(isGovernanceMachineCheckableTask).length,
    buckets: Object.values(buckets).filter((bucket) => bucket.count > 0),
    topTasks: active.slice(0, 4),
  };
}

export function searchTasks(tasks, query, limit = 12) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return [];
  const terms = q.split(/\s+/).filter(Boolean);
  const scored = [];
  (tasks || []).forEach((task) => {
    if (!task) return;
    const id = String(task.task_id || '').toLowerCase();
    const legacyId = String(task.legacy_id || '').toLowerCase();
    const title = String(task.title || task.display_title || '').toLowerCase();
    const rest = [
      task.project, task.assignee, task.status, task.next_action,
      taskTagsText(task.tags), task.path, task.scenario_slug,
    ].map((v) => String(v || '').toLowerCase()).join(' ');
    const all = id + ' ' + legacyId + ' ' + title + ' ' + rest;
    if (!terms.every((t) => all.includes(t))) return;
    let score = 0;
    terms.forEach((t) => {
      if (id === t) score += 100;
      else if (id.startsWith(t)) score += 60;
      if (title.includes(t)) score += 30;
      if (rest.includes(t)) score += 5;
    });
    if (consoleTaskStatus(task) === 'done') score -= 10;
    scored.push([score, task]);
  });
  scored.sort((a, b) => b[0] - a[0]);
  return scored.slice(0, limit).map(([, task]) => task);
}

export function teamDigestTypeLabel(type) {
  const labels = {
    new_card: '新建',
    status_changed: '状态',
    assignee_changed: '指派',
    due_soon: '到期',
    overdue: '逾期',
  };
  return labels[String(type || '')] || '动态';
}

export function teamDigestEntryTimestamp(entry) {
  return String((entry && (entry.timestamp || entry.generated_at)) || '');
}

export function sortTeamDigestEntries(entries) {
  if (!Array.isArray(entries)) return [];
  return entries.slice().sort((a, b) => {
    const at = Date.parse(teamDigestEntryTimestamp(a)) || 0;
    const bt = Date.parse(teamDigestEntryTimestamp(b)) || 0;
    if (bt !== at) return bt - at;
    return String((a && a.title) || '').localeCompare(String((b && b.title) || ''), 'zh-Hans-CN');
  });
}

export function isTeamDigestStale(digest, fallbackDays = 3) {
  if (!digest || digest.ok === false) return true;
  if (digest.is_stale === true) return true;
  const generatedAt = String(digest.generated_at || '').trim();
  if (!generatedAt) return true;
  const parsed = Date.parse(generatedAt);
  if (!Number.isFinite(parsed)) return true;
  const configuredDays = Number(digest.stale_days);
  const fallback = Number(fallbackDays);
  const maxDays = Number.isFinite(configuredDays)
    ? configuredDays
    : (Number.isFinite(fallback) ? fallback : 3);
  return Date.now() - parsed > Math.max(0, maxDays) * 86400000;
}

export function consoleTeamDigestEntries(digest, limit = 8) {
  if (isTeamDigestStale(digest, 3)) return [];
  const entries = sortTeamDigestEntries(digest && digest.entries);
  const maxItems = Number(limit);
  if (!Number.isFinite(maxItems) || maxItems <= 0) return entries;
  return entries.slice(0, maxItems);
}

export function teamDigestLatestDateLabel(digest) {
  const candidates = [];
  const push = (value) => {
    const raw = String(value || '').trim();
    const parsed = Date.parse(raw);
    if (raw && Number.isFinite(parsed)) candidates.push({ raw, parsed });
  };
  push(digest && digest.generated_at);
  push(digest && digest.updated_at);
  push(digest && digest.latest_at);
  if (digest && Array.isArray(digest.entries)) {
    digest.entries.forEach((entry) => push(teamDigestEntryTimestamp(entry)));
  }
  candidates.sort((a, b) => b.parsed - a.parsed);
  if (!candidates.length) return '未知日期';
  const match = candidates[0].raw.match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : new Date(candidates[0].parsed).toISOString().slice(0, 10);
}

export function teamDigestStillText(digest) {
  return '团队数据源静止（最近 ' + teamDigestLatestDateLabel(digest) + '）';
}


// KAN-1600: render-board 子模块只经 ctx 共享能力，不互相 import。
export function setupRenderBoard(ctx) {
  const { dataState, uiState, ui } = ctx;
  const { dom, STATUS, SL, PL, isMobile, dueDateText, makeDd, makeMemberDd, toast } = ui;
  const board = {
    ctx, dataState, uiState, ui, dom, STATUS, SL, PL, isMobile, dueDateText, makeDd, makeMemberDd, toast,
    PRI_ORDER: { high: 0, medium: 1, low: 2 },
    VIEWS: BOARD_VIEWS,
    TAB_VIEWS: BOARD_TAB_VIEWS,
    VL: BOARD_VIEW_LABELS,
    chainStageSelection: {},
    chainStateCache: {},
    TASK_DOMAIN_LABELS,
    BOARD_VIEWS,
    BOARD_TAB_VIEWS,
    BOARD_VIEW_LABELS,
    CONSOLE_AUDIENCE_OWNER,
    CONSOLE_AUDIENCE_ATTENTION_GATE,
    CONSOLE_OWNER_DECISION_RE,
    normalizeConsoleAudienceMode,
    isConsoleAttentionGateMode,
    consoleAudienceAllows,
    visibleBoardViewsForAudience,
    PROJECT_MAP_TASK_FAMILY_ALIASES,
    PROJECT_MAP_TASK_FAMILIES,
    PROJECT_MAP_FAMILY_LABELS,
    normalizeProjectMapFamily,
    projectPostureModel,
    consoleProjectRailModel,
    normalizeTaskTags,
    taskTagsText,
    dynamicProviderMatchesSurface,
    bridgeLaunchFeedback,
    automationShortStamp,
    parseAutomationOutputTail,
    pushAutomationLink,
    automationResultLinks,
    automationResultSummary,
    normalizeFrontendChains,
    KM_STAGE_ALIASES,
    TEAM_STAGE_ALIASES,
    CHAIN_HEALTH_WIP_LIMIT,
    CHAIN_HEALTH_STALLED_DAYS,
    CHAIN_HEALTH_BLOCKED_PENALTY,
    CHAIN_HEALTH_WAITING_DECISION_PENALTY,
    CHAIN_HEALTH_STALLED_PENALTY_PER_DAY,
    CHAIN_HEALTH_STACK_PENALTY,
    CHAIN_HEALTH_GOOD_SCORE,
    CHAIN_HEALTH_WARN_SCORE,
    CHAIN_FLOW_NODE_MIN_WIDTH,
    CHAIN_FLOW_NODE_GAP,
    CHAIN_HEALTH_MS_PER_DAY,
    GOV_STAGE_ALIASES,
    normalizedStageKey,
    mapGovernanceStageKey,
    taskStageExists,
    resolveStageAlias,
    isPersonalDispatchTask,
    deterministicGovernanceStage,
    inferGovernanceStage,
    chainTaskText,
    chainStageOf,
    statusChangedAgeDays,
    healthTaskRef,
    isBlockedHealthTask,
    ownerActionNeeded,
    isAiProxyReviewTask,
    isGateInFlightTask,
    isWaitingDecisionTask,
    chainHealthScore,
    buildChainStageBuckets,
    chainStatusTone,
    chainStageTone,
    normalizeConsoleAiMembers,
    consoleTaskStatus,
    consoleTaskAssignee,
    consoleAssigneeIsAi,
    CONSOLE_HUMAN_SCOPES,
    CONSOLE_TERMINAL_STATUSES,
    CONSOLE_WORK_STATUSES,
    CONSOLE_WAITING_STATUSES,
    CONSOLE_PARKED_STATUSES,
    consoleNormalizedStatus,
    consoleTruthy,
    hasExplicitConsoleHumanGate,
    isConsoleRecordTask,
    isConsoleRecordExceptionTask,
    consoleHasWaitingSignal,
    isConsoleWaitingTask,
    consoleTaskRoutingText,
    consoleAudienceTaskText,
    isConsoleOwnerDecisionTask,
    consoleInboxAudience,
    isConsolePreExecutionGateTask,
    isConsoleReviewTask,
    isConsoleInboxTask,
    isTeamKanbanPointerTask,
    isPinnedTeamKanbanPointerTask,
    isConsolePendingAiDispatchTask,
    consoleTaskRoutingLane,
    isConsoleGlobalDispatchTask,
    isConsoleTodayTask,
    isConsoleAiWorkTask,
    isConsoleCanvasTask,
    isConsoleUnroutedTask,
    CONSOLE_AI_DONE_RECENT_DAYS,
    CONSOLE_MS_PER_DAY,
    consoleRecentDoneStamp,
    isConsoleRecentAiDoneTask,
    consoleRecentAiDoneTasks,
    landingDateKey,
    landingPageDriftState,
    landingPageTasks,
    GOVERNANCE_TASK_FAMILIES,
    GOVERNANCE_TASK_ID_RE,
    KANBAN_GOVERNANCE_RE,
    GOVERNANCE_SIGNAL_RE,
    HUMAN_GATE_RE,
    MACHINE_CHECK_RE,
    governanceTaskText,
    isExplicitGovernanceTask,
    hasGovernanceSignal,
    isGovernanceBurdenTask,
    isGovernanceConsoleHiddenTask,
    governanceBurdenBucket,
    governanceHealthcheckToastText,
    governanceHealthcheckScheduleItem,
    governanceHealthcheckStatusText,
    governanceHealthcheckStatusTone,
    governanceHealthcheckRunStatusText,
    governanceHealthcheckRunStatusTone,
    governanceNoiseReviewStatusText,
    governanceNoiseReviewStatusTone,
    governanceShortStamp,
    governancePercent,
    isGovernanceHumanGateTask,
    isGovernanceMachineCheckableTask,
    isGovernanceAiReducibleTask,
    buildGovernanceBurdenModel,
    searchTasks,
    teamDigestTypeLabel,
    teamDigestEntryTimestamp,
    sortTeamDigestEntries,
    isTeamDigestStale,
    consoleTeamDigestEntries,
    teamDigestLatestDateLabel,
    teamDigestStillText
  };
  ctx.renderBoardInternal = board;
  return board;
}
