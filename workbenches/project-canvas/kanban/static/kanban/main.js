import { setupUi } from './modules/ui.js?v=20260806-canvas-soft-unbind-v1';
import { setupApi } from './modules/api.js';
import { setupAuth } from './modules/auth.js';
import { setupRenderBoard } from './modules/render-board.js?v=20260818-kan-1758-v1';
import { setupRenderBoardCore } from './modules/render-board-core.js?v=20260814-kan-1600-v1';
import { setupRenderBoardDuty } from './modules/render-board-duty.js?v=20260814-kan-1600-v1';
import { setupRenderBoardConsoleCards } from './modules/render-board-console-cards.js?v=20260814-kan-1600-v1';
import { setupRenderBoardConsoleRuntime } from './modules/render-board-console-runtime.js?v=20260814-kan-1600-v1';
import { setupRenderBoardConsole } from './modules/render-board-console.js?v=20260817-kan-1744-v1';
import { defaultRealProjectRef, LAST_REAL_PROJECT_KEY, setupRenderProjects } from './modules/render-projects.js?v=20260810-project-entry-v9';
import { setupRenderDetail } from './modules/render-detail.js?v=20260815-kan-1671-v2';
import { setupRenderDetailActions } from './modules/render-detail-actions.js?v=20260815-kan-1671-v2';
import { setupRenderDetailView } from './modules/render-detail-view.js?v=20260817-mario-retired-v1';
import { setupMarkdown } from './modules/markdown.js?v=20260710-comment-sidebar';
import { setupAi } from './modules/ai.js?v=20260815-kan-1671-v1';
import { setupAiThreads } from './modules/ai-threads.js?v=20260815-kan-1671-v1';
import { setupAiQueue } from './modules/ai-queue.js?v=20260815-kan-1671-v1';
import { setupReviewCycle } from './modules/review-cycle.js?v=20260719-isolated-review-v1';
import { setupHeaderStatus } from './modules/header-status.js?v=20260811-kan-1456-v4';

const dataState = window.__KANBAN_BOOTSTRAP__ || {};
let preferredStartupProjectRef = '';
try {
  preferredStartupProjectRef = localStorage.getItem(LAST_REAL_PROJECT_KEY) || '';
} catch (_) {
  preferredStartupProjectRef = '';
}
const startupProjectRef = defaultRealProjectRef(dataState.real_projects, preferredStartupProjectRef);
const DEFAULT_TASK_BODY_TEMPLATE = `## 背景 / 来源
- 来源：
- 为什么现在做：

## 要做什么
（一句话目标 + 明确动作）

## 输入与材料
- workdir:
- 入口文件 / 链接:
- 约束 / 不要碰:

## 完成标准
- [ ] 输出物明确
- [ ] 验证方式明确
- [ ] 执行结果已回填，必要时交接到团队板 / 场景库

## 执行结果
待回填。`;

const uiState = {
  auth: {
    authMode: 'token',
    currentUser: '',
    sessionValid: false,
    quizToken: '',
    quizTimer: null,
    quizDeadline: 0,
    loginMembersRendered: false,
    quizRefreshSeq: 0,
  },
  filters: {
    mine: false,
    hideDone: localStorage.getItem('kanban_filter_done') === 'true',
  },
  board: {
    activeView: 'projects',
    startupProjectRef,
    audienceMode: 'owner',
  },
  sync: {
    state: dataState.git_sync || null,
    eventSource: null,
    pendingRemoteRefresh: false,
  },
  detail: {
    currentTaskRaw: '',
    currentTaskPath: '',
    currentTaskBody: '',
    currentTaskStatus: '',
    currentTaskHash: '',
    currentTaskRev: '',
    isEditMode: false,
    inlineEditing: false,
    inlineSaving: false,
    editorDirty: false,
    acceptanceDirty: false,
    savedBodyContent: '',
    duePicker: null,
    duePickerInput: null,
    isSavingBody: false,
    sidebarTab: localStorage.getItem('kanban_detail_sidebar_tab') === 'comments' ? 'comments' : 'info',
    sidebarFolded: localStorage.getItem('kanban_detail_sidebar_folded') === 'true',
    commentQuotes: [],
    openCommentsAfterSave: false,
  },
  ai: {
    pollTimers: {},
    cachedSkills: null,
    threadTree: null,
  },
  queue: {
    data: null,
    pollTimer: null,
    badgeTimer: null,
    activeTab: 'processed',
    consecutiveIdle: 0,
  },
  attention_gateDuty: {
    data: null,
    loading: false,
    loadedAt: 0,
  },
  fileMention: {
    visible: false,
    textarea: null,
    query: '',
    triggerStart: -1,
    activeTab: 'all',
    activeIndex: 0,
    results: [],
    allResults: [],
    debounceTimer: null,
    offset: 0,
    limit: 50,
    total: 0,
    allTotal: 0,
    categoryCounts: {},
    hasMore: false,
    loading: false,
    error: '',
    requestSeq: 0,
    project: '',
    extCode: {},
    extImage: {},
    extDocument: {},
    icons: {},
  },
  timers: {
    toast: null,
    resize: null,
  },
  pendingUploadTasks: new Set(),
  fetch: {
    original: window.fetch.bind(window),
  },
  newTask: {
    isSubmitting: false,
  },
};

const ctx = {
  dataState,
  uiState,
  hasApi: Boolean(window.__KANBAN_HAS_API__),
  runtime: {},
};

setupUi(ctx);
setupAuth(ctx);
setupMarkdown(ctx);
setupApi(ctx);
setupHeaderStatus(ctx);
setupRenderProjects(ctx);
setupRenderBoard(ctx);
setupRenderBoardCore(ctx);
setupRenderBoardDuty(ctx);
setupRenderBoardConsoleCards(ctx);
setupRenderBoardConsoleRuntime(ctx);
setupRenderBoardConsole(ctx);
setupRenderDetail(ctx);
setupRenderDetailActions(ctx);
setupRenderDetailView(ctx);
setupAi(ctx);
setupAiThreads(ctx);
setupAiQueue(ctx);
setupReviewCycle(ctx);

window.openTaskDetail = ctx.renderDetail.openTaskDetail;
window.openTaskDetailByCode = ctx.renderDetail.openTaskDetailByCode;
window.closeDetail = ctx.renderDetail.closeDetail;
window.enterEditMode = ctx.renderDetail.enterEditMode;
window.exitEditMode = ctx.renderDetail.exitEditMode;
window.saveBody = ctx.renderDetail.saveBody;
window.uploadImageAndInsert = ctx.markdown.uploadImageAndInsert;
window.uploadImagesAndInsert = ctx.markdown.uploadImagesAndInsert;

const {
  dom,
  FLATPICKR_LOCALE,
  toast,
} = ctx.ui;

function syncUiState(sync) {
  const raw = (sync && sync.state) || 'disabled';
  if (raw === 'disabled') return 'disabled';
  if (raw === 'syncing') return 'syncing';
  if (raw === 'error') return 'error';
  if (raw === 'warning') return 'warning';
  if (raw.startsWith('paused')) return 'warning';
  if (raw === 'pending') return 'warning';
  return 'idle';
}

function syncManagers(sync) {
  const fallback = sync || {};
  const managers = fallback.managers || {};
  const git = managers.git || fallback || { enabled: false, mode: 'desktop', state: 'disabled' };
  return { git };
}

function activeSyncStatus(sync) {
  const managers = syncManagers(sync);
  return { target: 'git', status: managers.git };
}

function renderOneSyncSwitch(target, status) {
  const sw = dom.swSyncGit;
  const chk = dom.chkSyncGit;
  const overflowChk = dom.overflowChkSyncGit;
  if (!sw && !chk && !overflowChk) return;

  const enabled = Boolean(status && status.enabled);
  const state = enabled ? syncUiState(status) : 'disabled';
  if (chk) chk.checked = enabled;
  if (overflowChk) overflowChk.checked = enabled;

  if (sw) {
    sw.className = 'sync-switch';
    if (enabled) sw.classList.add('on');
    if (state !== 'disabled') sw.classList.add('state-' + state);
  }
}

function renderSyncSwitches(sync) {
  const managers = syncManagers(sync);
  renderOneSyncSwitch('git', managers.git);
}

function renderSyncIndicator() {
  const sync = uiState.sync.state || {};
  renderSyncSwitches(sync);
  const managers = syncManagers(sync);
  const active = activeSyncStatus(sync);
  const activeStatus = active.status || {};
  const anyEnabled = Boolean(managers.git && managers.git.enabled);
  if (ctx.headerStatus && typeof ctx.headerStatus.updateSync === 'function') ctx.headerStatus.updateSync(activeStatus);
  const indicator = dom.syncIndicator;
  if (!indicator) return;
  const label = dom.syncLabel;
  const line1 = dom.syncPopLine1;
  const line2 = dom.syncPopLine2;
  const line3 = dom.syncPopLine3;
  const state = anyEnabled ? syncUiState(activeStatus) : 'disabled';
  const rawState = String(activeStatus.state || '');
  indicator.className = 'sync-indicator state-' + state + (indicator.classList.contains('open') ? ' open' : '');
  // 安全暂停不是运行错误：人工 Git 闸门必须显示为待处理，而不是红色故障。
  if (state === 'disabled') label.textContent = '同步关闭';
  else if (state === 'syncing') label.textContent = '同步中';
  else if (state === 'error') label.textContent = '同步异常';
  else if (rawState === 'paused_manual_git') label.textContent = '待人工发布';
  else if (rawState.startsWith('paused')) label.textContent = '同步待处理';
  else if (rawState === 'pending') label.textContent = '等待同步';
  else if (state === 'warning') label.textContent = '同步待处理';
  else label.textContent = '同步正常';
  const when = activeStatus.last_sync_at || activeStatus.last_push?.at || activeStatus.last_pull?.at || activeStatus.last_commit?.at || activeStatus.updated_at || '-';
  line1.textContent = `${anyEnabled ? active.target : '-'} · ${label.textContent} · ${activeStatus.branch || '无分支'}`;
  line2.textContent = `本地超前 ${activeStatus.ahead || 0} · 落后远端 ${activeStatus.behind || 0} · Git ${managers.git?.enabled ? '开启' : '关闭'}`;
  line3.textContent = activeStatus.last_error || activeStatus.last_warning || `last activity ${when}`;
}

function applySyncEvent(sync, eventType) {
  if (sync) {
    const current = uiState.sync.state || {};
    const managers = { ...syncManagers(current) };
    managers.git = sync;
    const active = managers.git;
    uiState.sync.state = {
      ...(active || {}),
      active_mode: 'git',
      managers,
    };
  }
  renderSyncIndicator();
  if (eventType === 'pulled') {
    if (uiState.detail.isEditMode || uiState.detail.inlineEditing || uiState.detail.inlineSaving) {
      uiState.sync.pendingRemoteRefresh = true;
      ctx.renderDetail.updateEditorStatus('dirty', '检测到远端更新，保存后刷新');
    } else {
      ctx.api.refresh();
      if (uiState.detail.currentTaskPath) {
        fetch('/api/task?path=' + encodeURIComponent(uiState.detail.currentTaskPath))
          .then((r) => r.json())
          .then((j) => { if (j.ok) ctx.renderDetail.renderDetailContent(j.task); })
          .catch(() => {});
      }
    }
  }
}

function initSyncEvents() {
  if (!ctx.hasApi || !window.EventSource) return;
  renderSyncIndicator();
  uiState.sync.eventSource = new EventSource('/api/sync/events');
  ['status', 'pulled', 'pushed', 'paused', 'error'].forEach((type) => {
    uiState.sync.eventSource.addEventListener(type, (ev) => {
      try {
        const data = JSON.parse(ev.data);
        applySyncEvent(data.status, type);
      } catch (e) {
        return null;
      }
      return null;
    });
  });
  uiState.sync.eventSource.onerror = () => {};
}

function syncMemberSelects() {
  const members = dataState.all_members || [];
  const loginMembers = dataState.login_members || ['Owner'];
  if (dom.newAssignee) {
    dom.newAssignee.innerHTML = '';
    members.forEach((member) => {
      const opt = document.createElement('option');
      opt.value = member;
      opt.textContent = member;
      dom.newAssignee.appendChild(opt);
    });
    syncNewTaskAssignee();
  }
  if (dom.settingsUser) {
    dom.settingsUser.innerHTML = '';
    loginMembers.forEach((member) => {
      const opt = document.createElement('option');
      opt.value = member;
      opt.textContent = member;
      dom.settingsUser.appendChild(opt);
    });
    if (uiState.auth.currentUser && loginMembers.includes(uiState.auth.currentUser)) {
      dom.settingsUser.value = uiState.auth.currentUser;
    } else if (loginMembers.length) {
      dom.settingsUser.value = loginMembers[0];
    }
  }
}

function syncProjectDropdown() {
  renderProjectDropdown(dataState.project_names || []);
}

function syncRuntimeUI() {
  syncMemberSelects();
  syncProjectDropdown();
  if (dom.settingsClaude) {
    dom.settingsClaude.placeholder = dataState.default_tools?.claude || 'claude --print --dangerously-skip-permissions';
    if (!dom.modalSettings.classList.contains('on')) dom.settingsClaude.value = dataState.user_tool_overrides?.claude || '';
  }
  if (dom.settingsCodex) {
    dom.settingsCodex.placeholder = dataState.default_tools?.codex || 'codex --yolo exec';
    if (!dom.modalSettings.classList.contains('on')) dom.settingsCodex.value = dataState.user_tool_overrides?.codex || '';
  }
}

ctx.runtime.renderSyncIndicator = renderSyncIndicator;
ctx.runtime.initSyncEvents = initSyncEvents;
ctx.runtime.syncRuntimeUI = syncRuntimeUI;
function syncNewTaskAssignee() {
  if (uiState.auth.currentUser) dom.newAssignee.value = uiState.auth.currentUser;
}

const hasFlatpickr = typeof window.flatpickr === 'function';
if (hasFlatpickr && dom.newDueDate) {
  flatpickr(dom.newDueDate, {
    locale: FLATPICKR_LOCALE,
    dateFormat: 'Y-m-d',
    minDate: 'today',
    allowInput: false,
    disableMobile: true,
  });
}

function resetNewTaskModal() {
  dom.modalNew.classList.remove('on');
  dom.newProject.value = '';
  dom.newProjectErr.textContent = '';
  dom.newProject.classList.remove('input-err');
  dom.aiTitleCb.checked = true;
  dom.titleInputWrap.classList.remove('show');
  dom.newTitle.value = '';
  dom.newBody.value = '';
  if (dom.newDueDate._flatpickr) dom.newDueDate._flatpickr.clear();
}

function renderProjectDropdown(items) {
  dom.projDropdown.innerHTML = '';
  items.forEach((project) => {
    const item = document.createElement('div');
    item.className = 'proj-dd-item';
    item.textContent = project;
    item.onclick = () => {
      dom.newProject.value = project;
      dom.projDropdown.classList.remove('on');
      validateProjectInput();
    };
    dom.projDropdown.appendChild(item);
  });
}

function validateProjectInput() {
  const raw = dom.newProject.value;
  const trimmed = raw.trim();
  dom.newProject.value = trimmed;
  dom.newProjectErr.textContent = '';
  dom.newProject.classList.remove('input-err');
  if (!trimmed) {
    dom.newProjectErr.textContent = '请输入项目名称';
    dom.newProject.classList.add('input-err');
    return null;
  }
  if (trimmed.length < 2) {
    dom.newProjectErr.textContent = '项目名称至少2个字符';
    dom.newProject.classList.add('input-err');
    return null;
  }
  if (trimmed.length > 50) {
    dom.newProjectErr.textContent = '项目名称不能超过50个字符';
    dom.newProject.classList.add('input-err');
    return null;
  }
  if (!/^[\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9\-_]+$/.test(trimmed)) {
    dom.newProjectErr.textContent = '仅支持中英文、数字、连字符和下划线';
    dom.newProject.classList.add('input-err');
    return null;
  }
  const existing = (dataState.project_names || []).find((p) => p.toLowerCase() === trimmed.toLowerCase());
  return existing || trimmed;
}

function setNewTaskSubmitState(isBusy, loadingBtn) {
  [dom.btnCreate, dom.btnAiCreate, dom.btnAiArrow].forEach((btn) => {
    btn.disabled = isBusy;
    btn.classList.remove('btn-loading');
  });
  if (isBusy && loadingBtn) loadingBtn.classList.add('btn-loading');
}

async function withNewTaskSubmitLock(loadingBtn, fn) {
  if (uiState.newTask.isSubmitting) return null;
  uiState.newTask.isSubmitting = true;
  setNewTaskSubmitState(true, loadingBtn);
  try {
    return await fn();
  } finally {
    uiState.newTask.isSubmitting = false;
    setNewTaskSubmitState(false);
  }
}

function findTaskByPath(taskPath) {
  return (dataState.tasks || []).find((task) => task.path === taskPath);
}

async function createTaskCommon(loadingBtn, afterCreate) {
  const project = validateProjectInput();
  if (!project) {
    dom.newProject.focus();
    return;
  }
  const assignee = dom.newAssignee.value;
  const priority = dom.newPriority.value;
  const body = dom.newBody.value;
  const dueDate = dom.newDueDate.value;
  if (dom.aiTitleCb.checked && !body.trim()) {
    toast('请输入正文内容', true);
    return;
  }
  if (!dom.aiTitleCb.checked && !dom.newTitle.value.trim()) {
    toast('请输入任务标题', true);
    return;
  }
  await withNewTaskSubmitLock(loadingBtn, async () => {
    let title = '';
    if (dom.aiTitleCb.checked) {
      const result = await ctx.api.apiGenerateTitle(body);
      if (result.ok) {
        title = result.title;
      } else {
        toast(result.message || 'AI 标题生成失败，请手动输入', true);
        dom.aiTitleCb.checked = false;
        dom.titleInputWrap.classList.add('show');
        dom.newTitle.focus();
        return;
      }
    } else {
      title = dom.newTitle.value.trim();
      if (!title) {
        toast('请输入任务标题', true);
        return;
      }
    }
    const createResult = await ctx.api.apiCreate(project, title, assignee, priority, body, dueDate);
    if (!createResult) return;
    await afterCreate(createResult.message);
  });
}

async function createAndRunAi(tool) {
  await createTaskCommon(dom.btnAiCreate, async (taskPath) => {
    const aiResult = await ctx.ai.startAiRunForTask(taskPath, tool);
    resetNewTaskModal();
    ctx.api.refresh().then(() => {
      syncProjectDropdown();
      const task = findTaskByPath(taskPath);
      if (task) ctx.ai.taskToast(task, aiResult.ok ? '新任务，AI处理中' : undefined);
    });
    if (!aiResult.ok) toast(aiResult.error, true);
  });
}

function openNewTaskModal() {
  syncNewTaskAssignee();
  if (!dom.newBody.value) dom.newBody.value = DEFAULT_TASK_BODY_TEMPLATE;
  dom.modalNew.classList.add('on');
}

function bindNewTaskUi() {
  ctx.openNewTaskModal = openNewTaskModal;
  dom.btnCancel.onclick = resetNewTaskModal;
  dom.modalNew.onclick = (e) => { if (e.target === dom.modalNew) resetNewTaskModal(); };
  dom.aiTitleCb.onchange = () => { dom.titleInputWrap.classList.toggle('show', !dom.aiTitleCb.checked); };
  dom.newProject.addEventListener('input', validateProjectInput);
  dom.newProject.addEventListener('focus', () => { dom.projDropdown.classList.add('on'); });
  dom.newProject.addEventListener('blur', () => { setTimeout(() => dom.projDropdown.classList.remove('on'), 150); });
  dom.btnCreate.onclick = async () => {
    await createTaskCommon(dom.btnCreate, async (taskPath) => {
      resetNewTaskModal();
      ctx.api.refresh().then(() => {
        syncProjectDropdown();
        const task = findTaskByPath(taskPath);
        if (task) ctx.ai.taskToast(task);
      });
    });
  };
  dom.btnAiArrow.addEventListener('click', (e) => {
    e.stopPropagation();
    ctx.ui.closeAllDd();
    dom.aiToolDd.classList.toggle('on');
    dom.btnAiSplit.classList.toggle('open', dom.aiToolDd.classList.contains('on'));
  });
  dom.aiToolDd.querySelectorAll('.dd-item').forEach((item) => {
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      ctx.ui.closeAllDd();
      createAndRunAi(item.dataset.tool);
    });
  });
  dom.btnAiCreate.addEventListener('click', () => createAndRunAi('claude'));
  if (dom.newBody) {
    dom.newBody.addEventListener('input', ctx.markdown._fmHandleInput);
    dom.newBody.addEventListener('keydown', ctx.markdown._fmHandleKeydown, true);
    dom.newBody.addEventListener('blur', () => setTimeout(() => { if (uiState.fileMention.visible) ctx.markdown._fmHide(); }, 200));
  }
}

function updateUsernameDisplay() {
  ctx.auth.updateUserUI();
}

function bindSettingsUi() {
  syncRuntimeUI();
  updateUsernameDisplay();
  // KAN-203：顶栏「设置」按钮已收进汉堡菜单（overflow-settings），顶级按钮可缺省，故 null-safe。
  if (dom.btnSettings) dom.btnSettings.onclick = () => dom.modalSettings.classList.add('on');
  dom.hdrUsername.onclick = () => {
    if (uiState.auth.sessionValid) ctx.auth.showLogin('user');
    else dom.modalSettings.classList.add('on');
  };
  dom.btnSettingsCancel.onclick = () => dom.modalSettings.classList.remove('on');
  dom.modalSettings.onclick = (e) => { if (e.target === dom.modalSettings) dom.modalSettings.classList.remove('on'); };
  dom.btnSettingsSave.onclick = async () => {
    const user = dom.settingsUser.value;
    if (!user) {
      toast('请选择你的名字', true);
      return;
    }
    const prevClaudeCmd = dataState.user_tool_overrides?.claude || '';
    const prevCodexCmd = dataState.user_tool_overrides?.codex || '';
    uiState.auth.currentUser = user;
    await fetch('/api/select-user', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ user }),
      credentials: 'same-origin'
    });
    updateUsernameDisplay();
    syncNewTaskAssignee();
    const cfg = {};
    const claudeCmd = dom.settingsClaude.value.trim();
    const codexCmd = dom.settingsCodex.value.trim();
    const toolsChanged = claudeCmd !== prevClaudeCmd || codexCmd !== prevCodexCmd;
    if (toolsChanged) {
      cfg.tools = {};
      if (claudeCmd) cfg.tools.claude = { command: claudeCmd };
      if (codexCmd) cfg.tools.codex = { command: codexCmd };
    }
    try {
      if (ctx.hasApi) {
        const response = await fetch('/api/save-user-config', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(cfg)
        });
        const json = await response.json();
        if (!json.ok) {
          toast(json.error || '工具配置保存失败', true);
          return;
        }
      }
      if (toolsChanged) {
        dataState.user_tool_overrides = {};
        if (claudeCmd) dataState.user_tool_overrides.claude = claudeCmd;
        if (codexCmd) dataState.user_tool_overrides.codex = codexCmd;
      }
      dom.modalSettings.classList.remove('on');
      toast('个人设置已保存');
      ctx.renderBoard.renderAll();
    } catch (e) {
      toast('网络错误', true);
    }
  };
}

function bindOverflowMenu() {
  if (!dom.btnOverflow || !dom.hdrOverflowMenu) return;
  dom.btnOverflow.onclick = (e) => {
    e.stopPropagation();
    dom.hdrOverflowMenu.classList.toggle('on');
  };
  document.addEventListener('click', () => dom.hdrOverflowMenu.classList.remove('on'));
  dom.hdrOverflowMenu.addEventListener('click', (e) => e.stopPropagation());
  if (dom.overflowSettings) dom.overflowSettings.onclick = () => {
    dom.modalSettings.classList.add('on');
    dom.hdrOverflowMenu.classList.remove('on');
  };
  const syncOverflowCheckboxes = () => {
    if (dom.overflowChkMine) dom.overflowChkMine.checked = dom.chkMine.checked;
    if (dom.overflowChkDone) dom.overflowChkDone.checked = dom.chkDone.checked;
  };
  setTimeout(syncOverflowCheckboxes, 0);
  dom.btnOverflow.addEventListener('click', syncOverflowCheckboxes);
  dom.chkMine.addEventListener('change', syncOverflowCheckboxes);
  dom.chkDone.addEventListener('change', syncOverflowCheckboxes);
  dom.overflowFilterMine.onclick = () => {
    dom.chkMine.checked = !dom.chkMine.checked;
    if (dom.chkMine.onchange) dom.chkMine.onchange();
    syncOverflowCheckboxes();
  };
  dom.overflowFilterDone.onclick = () => {
    dom.chkDone.checked = !dom.chkDone.checked;
    if (dom.chkDone.onchange) dom.chkDone.onchange();
    syncOverflowCheckboxes();
  };
}

function bindProjectEntryButtons() {
  if (dom.btnNewProject) dom.btnNewProject.onclick = () => ctx.realProjects?.openCreate();
}

function bindFilterSwitches() {
  uiState.filters.mine = false;
  localStorage.setItem('kanban_filter_mine', 'false');
  dom.chkMine.checked = false;
  dom.chkDone.checked = uiState.filters.hideDone;
  dom.swMine.classList.remove('on');
  dom.swDone.classList.toggle('on', uiState.filters.hideDone);

  dom.chkMine.onchange = () => {
    uiState.filters.mine = false;
    dom.chkMine.checked = false;
    localStorage.setItem('kanban_filter_mine', 'false');
    dom.swMine.classList.remove('on');
    ctx.renderBoard.renderAll();
  };

  dom.chkDone.onchange = () => {
    uiState.filters.hideDone = dom.chkDone.checked;
    localStorage.setItem('kanban_filter_done', uiState.filters.hideDone);
    dom.swDone.classList.toggle('on', uiState.filters.hideDone);
    ctx.renderBoard.renderAll();
  };
}

function bindSyncIndicatorUi() {
  document.addEventListener('click', (e) => {
    if (!dom.syncIndicator) return;
    if (dom.syncIndicator.contains(e.target)) return;
    dom.syncIndicator.classList.remove('open');
  });
  if (dom.syncIndicator) {
    dom.syncIndicator.addEventListener('click', (e) => {
      e.stopPropagation();
      dom.syncIndicator.classList.toggle('open');
    });
  }
}

function bindSyncSwitch() {
  const bindOne = (target, chk, overflowChk, overflowWrap) => {
    if (!chk && !overflowChk) return;
    const setChecked = (enabled) => {
      if (chk) chk.checked = enabled;
      if (overflowChk) overflowChk.checked = enabled;
    };
    const toggle = (enabled) => {
      fetch('/api/sync/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target, enabled }),
      })
        .then((r) => r.json())
        .then((j) => {
          if (j.ok && j.status) {
            uiState.sync.state = j.status;
            renderSyncIndicator();
          } else {
            ctx.ui.toast(j.error || 'Sync toggle failed', true);
            setChecked(!enabled);
          }
        })
        .catch(() => {
          ctx.ui.toast('Network error', true);
          setChecked(!enabled);
        });
    };

    if (chk) {
      chk.addEventListener('change', () => {
        toggle(chk.checked);
      });
    }

    if (overflowChk) {
      overflowChk.addEventListener('change', (e) => {
        e.stopPropagation();
        setChecked(overflowChk.checked);
        toggle(overflowChk.checked);
      });
    }
    if (overflowWrap) {
      overflowWrap.addEventListener('click', (e) => {
        e.stopPropagation();
      });
    }
  };

  bindOne('git', dom.chkSyncGit, dom.overflowChkSyncGit, dom.overflowSwSyncGit);
}

function syncAudienceButton() {
  const btn = dom.overflowBtnAudience;
  if (!btn) return;
  const attention_gate = uiState.board.audienceMode === 'attention_gate';
  btn.classList.toggle('on', attention_gate);
  btn.setAttribute('aria-pressed', attention_gate ? 'true' : 'false');
  btn.title = attention_gate ? '切回 Owner 视角' : '切到人闸视角';
  // KAN-203：顶栏 brand 副题显示当前视角（灰）。
  if (dom.hdrAudienceLabel) dom.hdrAudienceLabel.textContent = attention_gate ? '人闸 · 视角' : 'Owner · 视角';
  const icon = btn.querySelector('i');
  if (icon) icon.setAttribute('data-lucide', attention_gate ? 'toggle-right' : 'toggle-left');
  if (typeof lucide !== 'undefined') requestAnimationFrame(() => lucide.createIcons());
}

function bindAudienceButton() {
  syncAudienceButton();
  const btn = dom.overflowBtnAudience;
  if (!btn) return;
  const toggleAudience = () => {
    uiState.board.audienceMode = uiState.board.audienceMode === 'attention_gate' ? 'owner' : 'attention_gate';
    localStorage.setItem('kanban_console_audience', uiState.board.audienceMode);
    syncAudienceButton();
    if (ctx.renderBoard) ctx.renderBoard.renderAll();
  };
  btn.onclick = (e) => {
    e.stopPropagation();
    toggleAudience();
  };
  btn.onkeydown = (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    e.stopPropagation();
    toggleAudience();
  };
}

function bindGlobalSearch() {
  const SL = { todo: '待办', 'in-progress': '进行中', review: '评审中', done: '已完成' };
  const overlay = document.createElement('div');
  overlay.className = 'search-overlay';
  const box = document.createElement('div');
  box.className = 'search-box';
  const input = document.createElement('input');
  input.id = 'global-search-input';
  input.placeholder = '搜索任务：编号 / 标题 / 标签 / 项目 / 负责人…';
  input.autocomplete = 'off';
  const resultsEl = document.createElement('div');
  resultsEl.className = 'search-results';
  const hint = document.createElement('div');
  hint.className = 'search-hint';
  hint.innerHTML = '<span>↑↓ 选择</span><span>Enter 打开</span><span>Esc 关闭</span>';
  box.appendChild(input); box.appendChild(resultsEl); box.appendChild(hint);
  overlay.appendChild(box);
  document.body.appendChild(overlay);

  let results = [];
  let active = 0;

  function close() {
    overlay.classList.remove('on');
    input.value = '';
    resultsEl.innerHTML = '';
    results = [];
    active = 0;
  }

  function openTask(task) {
    close();
    if (task && task.path && window.openTaskDetail) window.openTaskDetail(task.path);
  }

  function renderResults() {
    results = ctx.renderBoard ? ctx.renderBoard.searchTasks(dataState.tasks || [], input.value) : [];
    if (active >= results.length) active = Math.max(0, results.length - 1);
    resultsEl.innerHTML = '';
    if (input.value.trim() && !results.length) {
      const empty = document.createElement('div');
      empty.className = 'search-empty';
      empty.textContent = '无匹配任务';
      resultsEl.appendChild(empty);
      return;
    }
    results.forEach((task, i) => {
      const row = document.createElement('div');
      row.className = 'search-item' + (i === active ? ' on' : '');
      const code = document.createElement('span');
      code.className = 'search-item-code';
      code.textContent = task.task_id || '—';
      const title = document.createElement('span');
      title.className = 'search-item-title';
      title.textContent = task.title || task.display_title || '未命名';
      const meta = document.createElement('span');
      meta.className = 'search-item-meta';
      meta.textContent = [task.project, task.assignee, SL[task.status] || task.status].filter(Boolean).join(' · ');
      row.appendChild(code); row.appendChild(title); row.appendChild(meta);
      row.onmouseenter = () => {
        if (active === i) return;
        active = i;
        resultsEl.querySelectorAll('.search-item').forEach((el, j) => el.classList.toggle('on', j === active));
      };
      row.onclick = () => openTask(task);
      resultsEl.appendChild(row);
    });
  }

  function open() {
    overlay.classList.add('on');
    input.focus();
    renderResults();
  }

  input.addEventListener('input', () => { active = 0; renderResults(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, Math.max(0, results.length - 1)); renderResults(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); renderResults(); }
    else if (e.key === 'Enter') { e.preventDefault(); openTask(results[active]); }
    else if (e.key === 'Escape') { e.preventDefault(); close(); }
  });
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && String(e.key).toLowerCase() === 'k') {
      e.preventDefault();
      if (overlay.classList.contains('on')) close(); else open();
    }
  });
  if (dom.btnSearch) dom.btnSearch.onclick = open;
}

function init() {
  ctx.auth.bindEvents();
  ctx.renderDetail.bindEvents();
  ctx.ai.bindEvents();
  bindSyncIndicatorUi();
  bindSyncSwitch();
  bindAudienceButton();
  bindNewTaskUi();
  if (new URLSearchParams(window.location.search).get('new_task') === '1') openNewTaskModal();
  bindSettingsUi();
  bindGlobalSearch();
  bindProjectEntryButtons();
  bindOverflowMenu();
  bindFilterSwitches();
  syncRuntimeUI();
  const requestedView = new URLSearchParams(window.location.search).get('view');
  if (requestedView === 'console') uiState.board.activeView = 'console';
  ctx.auth.init();
  ctx.renderBoard.renderAll();
  renderSyncIndicator();
  if (typeof lucide !== 'undefined') lucide.createIcons();
  ctx.ai.startQueueBadgePolling();
  initSyncEvents();
  ctx.renderDetail.checkHashAndOpenDetail();
  window.matchMedia('(max-width:768px)').addEventListener('change', () => {
    clearTimeout(uiState.timers.resize);
    uiState.timers.resize = setTimeout(() => ctx.renderBoard.renderAll(), 150);
  });
}

init();
