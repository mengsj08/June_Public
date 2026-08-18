const ACTION_META = {
  needs_reply: { label: '需回复', tone: 'reply', order: 0 },
  needs_decision: { label: '需决策', tone: 'decision', order: 1 },
  needs_progress: { label: '需推进', tone: 'progress', order: 2 },
  no_action: { label: '暂无需动作', tone: 'quiet', order: 9 },
};
const LIFECYCLE_LABELS = { active: '进行中', paused: '暂停', completed: '已完成', archived: '已归档' };
const MILESTONE_LABELS = { verified: '已验证', in_progress: '进行中', waiting: '等待' };
const PROJECT_ROLE_LABELS = {
  execution: '执行',
  milestone: '里程碑',
  evidence: '证据',
  governance: '治理',
  delivery: '交付',
};
const PROJECT_ROLE_OPTIONS = Object.entries(PROJECT_ROLE_LABELS).map(([value, label]) => ({ value, label }));
export const LAST_REAL_PROJECT_KEY = 'kanban_last_real_project_ref';
const PROJECT_RAIL_COLLAPSED_KEY = 'kanban_project_rail_collapsed';

function text(value) {
  return String(value || '').trim();
}

export function defaultRealProjectRef(payload, preferred = '') {
  const projects = (Array.isArray(payload?.projects) ? payload.projects : [])
    .filter((project) => text(project?.lifecycle || 'active') !== 'archived');
  const wanted = text(preferred);
  if (wanted && projects.some((project) => text(project?.project_ref) === wanted)) return wanted;
  const active = projects.filter((project) => text(project?.lifecycle || 'active') === 'active');
  const ranked = active.slice().sort((a, b) => (
    Number(b?.tasks?.active_count || 0) - Number(a?.tasks?.active_count || 0)
  ));
  return text((ranked[0] || projects[0])?.project_ref);
}

function storedRealProjectRef() {
  try {
    return text(globalThis.localStorage?.getItem(LAST_REAL_PROJECT_KEY));
  } catch (_) {
    return '';
  }
}

function rememberRealProjectRef(projectRef) {
  const value = text(projectRef);
  if (!value) return;
  try {
    globalThis.localStorage?.setItem(LAST_REAL_PROJECT_KEY, value);
  } catch (_) {
    // Local storage is an optional UI convenience; project truth remains in the registry.
  }
}

function storedProjectRailCollapsed() {
  try {
    return globalThis.localStorage?.getItem(PROJECT_RAIL_COLLAPSED_KEY) === 'true';
  } catch (_) {
    return false;
  }
}

function rememberProjectRailCollapsed(collapsed) {
  try {
    globalThis.localStorage?.setItem(PROJECT_RAIL_COLLAPSED_KEY, String(Boolean(collapsed)));
  } catch (_) {
    // Layout preference only; project truth and Canvas state remain untouched.
  }
}

export function actionMeta(type) {
  return ACTION_META[text(type)] || ACTION_META.no_action;
}

export function replyPackActionNames(project) {
  const pack = project && project.reply_pack;
  if (!pack || text(project.primary_action?.type) !== 'needs_reply') return [];
  return ['copy_draft', 'open_source'];
}

export function projectActionControlNames(action) {
  return action?.bound_task ? ['open_task'] : [];
}

const TERMINAL_TASK_STATUSES = new Set(['done', 'completed', 'archived', 'cancelled', 'canceled']);

export function unassignedProjectTaskCandidates(tasks, query = '') {
  const needle = text(query).toLowerCase();
  return (Array.isArray(tasks) ? tasks : []).filter((task) => {
    if (text(task.project_ref)) return false;
    if (TERMINAL_TASK_STATUSES.has(text(task.status).toLowerCase())) return false;
    if (!needle) return true;
    return `${text(task.task_id)} ${text(task.title)} ${text(task.assignee)}`.toLowerCase().includes(needle);
  });
}

function projectWorkdir(project) {
  return text(project?.workdir || (Array.isArray(project?.fact_roots) ? project.fact_roots[0] : ''));
}

function slugFromTitle(value) {
  return text(value).toLowerCase().normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63);
}

function node(tag, className, value) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (value !== undefined && value !== null) el.textContent = String(value);
  return el;
}

function button(label, className, handler) {
  const el = node('button', className, label);
  el.type = 'button';
  if (handler) el.onclick = handler;
  return el;
}

function badge(value, className = '') {
  return node('span', `rp-badge ${className}`.trim(), value);
}

function projectRoleLabel(value) {
  return PROJECT_ROLE_LABELS[text(value).toLowerCase()] || PROJECT_ROLE_LABELS.execution;
}

function projectRoleSummary(roleCounts) {
  return Object.entries(PROJECT_ROLE_LABELS)
    .map(([role, label]) => Number(roleCounts?.[role] || 0) ? `${label} ${Number(roleCounts[role])}` : '')
    .filter(Boolean)
    .join(' · ');
}

function sectionTitle(kicker, title, meta = '') {
  const wrap = node('div', 'rp-section-head');
  const copy = node('div', 'rp-section-copy');
  copy.appendChild(node('span', 'rp-kicker', kicker));
  copy.appendChild(node('h3', '', title));
  wrap.appendChild(copy);
  if (meta) wrap.appendChild(node('span', 'rp-section-meta', meta));
  return wrap;
}

function formControl(labelText, control, hint = '') {
  const field = node('label', 'rp-form-field');
  field.appendChild(node('span', 'rp-form-label', labelText));
  field.appendChild(control);
  if (hint) field.appendChild(node('small', '', hint));
  return field;
}

function textInput(placeholder = '', type = 'text') {
  const input = node('input', 'rp-form-input');
  input.type = type;
  input.placeholder = placeholder;
  return input;
}

function textareaInput(placeholder = '', rows = 3) {
  const input = node('textarea', 'rp-form-input');
  input.placeholder = placeholder;
  input.rows = rows;
  return input;
}

function selectInput(options, selected = '') {
  const select = node('select', 'rp-form-input');
  (options || []).forEach((entry) => {
    const value = typeof entry === 'string' ? entry : entry.value;
    const label = typeof entry === 'string' ? entry : entry.label;
    const option = node('option', '', label);
    option.value = value;
    option.selected = value === selected;
    select.appendChild(option);
  });
  return select;
}

function composerHeader(kicker, title, onClose) {
  const head = node('div', 'rp-composer-head');
  head.appendChild(sectionTitle(kicker, title));
  head.appendChild(button('关闭', 'rp-btn rp-btn-quiet', onClose));
  return head;
}

function openSource(ctx, source) {
  const path = text(source?.path);
  const ref = text(source?.ref);
  if (path && ctx.api?.openInEditor) {
    ctx.api.openInEditor(path);
    return;
  }
  if (ref && ctx.renderDetail?.openTaskDetailByCode) {
    ctx.renderDetail.openTaskDetailByCode(ref);
    return;
  }
  ctx.ui.toast('这个证据暂时没有可打开的本地入口', true);
}

function renderEvidenceSources(ctx, fact) {
  const list = node('div', 'rp-evidence-sources');
  (Array.isArray(fact.sources) ? fact.sources : []).forEach((source) => {
    const item = button(text(source.label || source.ref || source.path || source.kind), 'rp-source', () => openSource(ctx, source));
    item.title = text(source.path || source.ref);
    list.appendChild(item);
  });
  return list;
}

function renderProjectCreateModal(ctx, state) {
  const backdrop = node('div', 'rp-project-modal-backdrop');
  backdrop.setAttribute('role', 'presentation');
  const dialog = node('section', 'rp-project-modal');
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-labelledby', 'rp-project-create-title');
  const head = node('div', 'rp-project-modal-head');
  const heading = node('div');
  heading.appendChild(node('span', 'rp-chain-label', 'NEW PROJECT'));
  const titleEl = node('h2', '', '建立真实项目');
  titleEl.id = 'rp-project-create-title';
  heading.appendChild(titleEl);
  head.appendChild(heading);
  head.appendChild(button('关闭', 'rp-project-modal-close', () => {
    state.creatingProject = false;
    render(ctx, state);
  }));
  dialog.appendChild(head);
  dialog.appendChild(node('p', 'rp-project-modal-intro', '登记一个已经由你确认的项目身份。目录只作为原始资料入口，不会被复制或移动。'));
  const form = node('form', 'rp-form-grid');
  const title = textInput('例如：Endoscopy-AI Workbench');
  const projectRef = textInput('例如：endoscopy-ai-workbench');
  const intent = textareaInput('这个项目最终要产生什么可验证结果？', 3);
  const workdir = textInput('/absolute/path/to/project');
  let refEdited = false;
  projectRef.addEventListener('input', () => { refEdited = true; });
  title.addEventListener('input', () => {
    if (!refEdited) projectRef.value = slugFromTitle(title.value);
  });
  form.appendChild(formControl('项目名称', title));
  form.appendChild(formControl('稳定项目 ID', projectRef, '英文小写、数字与连字符；建立后作为 project_ref 使用。'));
  const intentField = formControl('项目结果', intent);
  intentField.classList.add('rp-form-span');
  form.appendChild(intentField);
  const workdirField = formControl('已有项目目录（可选）', workdir, '只登记现有绝对路径；留空则建立纯项目身份。');
  workdirField.classList.add('rp-form-span');
  form.appendChild(workdirField);
  const error = node('p', 'rp-form-error');
  error.setAttribute('role', 'alert');
  const actions = node('div', 'rp-form-actions rp-form-span');
  const submit = button('确认建立项目', 'rp-btn primary');
  submit.type = 'submit';
  actions.appendChild(error);
  actions.appendChild(submit);
  form.appendChild(actions);
  form.onsubmit = async (event) => {
    event.preventDefault();
    error.textContent = '';
    submit.disabled = true;
    submit.textContent = '正在建立';
    try {
      const { json } = await ctx.api.apiJson('/api/real-projects/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.value.trim(),
          project_ref: projectRef.value.trim(),
          current_intent: intent.value.trim(),
          workdir: workdir.value.trim(),
        }),
      });
      if (!json.ok) {
        error.textContent = json.error || '建立项目失败';
        return;
      }
      state.selectedProjectRef = json.project.project_ref;
      state.lastProjectRef = json.project.project_ref;
      rememberRealProjectRef(json.project.project_ref);
      state.creatingProject = false;
      await ctx.api.refresh();
      ctx.ui.toast('真实项目已建立；现在可以创建或归入任务卡');
      render(ctx, state);
    } catch (err) {
      error.textContent = '网络错误，请稍后重试';
    } finally {
      submit.disabled = false;
      submit.textContent = '确认建立项目';
    }
  };
  dialog.appendChild(form);
  backdrop.appendChild(dialog);
  backdrop.onclick = (event) => {
    if (event.target !== backdrop) return;
    state.creatingProject = false;
    render(ctx, state);
  };
  return backdrop;
}

async function refreshProject(ctx, state, projectRef, control) {
  control.disabled = true;
  const original = control.textContent;
  control.textContent = '正在核对';
  try {
    const { json } = await ctx.api.apiJson('/api/real-projects/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_ref: projectRef }),
    });
    if (!json.ok) {
      ctx.ui.toast(json.error || '刷新失败', true);
      return;
    }
    const labels = {
      baseline_created: '已建立扫描基线，不生成项目事件',
      no_change: '没有变化，不生成记录',
      no_material_change: '只有排版或空白变化，项目侧保持静默',
      candidates: `发现 ${json.changes?.length || 0} 项待确认变化`,
    };
    ctx.ui.toast(labels[json.outcome] || '刷新完成');
    await ctx.api.refresh();
    render(ctx, state);
  } catch (error) {
    ctx.ui.toast('刷新失败', true);
  } finally {
    control.disabled = false;
    control.textContent = original;
  }
}

function renderReplyPack(ctx, project) {
  if (text(project.primary_action?.type) !== 'needs_reply' || !project.reply_pack) return null;
  const pack = project.reply_pack;
  const section = node('section', 'rp-panel rp-reply-pack');
  section.appendChild(sectionTitle('可审阅回复包', pack.goal || '回复目标', pack.channel || ''));
  const quote = node('blockquote', 'rp-quote', pack.latest_fact || pack.quote || '');
  section.appendChild(quote);
  const draft = node('div', 'rp-draft');
  draft.appendChild(node('span', 'rp-chain-label', '可编辑草稿'));
  draft.appendChild(node('p', '', pack.draft || ''));
  section.appendChild(draft);
  if (Array.isArray(pack.unknowns) && pack.unknowns.length) {
    section.appendChild(node('p', 'rp-unknown-inline', `未核实：${pack.unknowns.join('；')}`));
  }
  const actions = node('div', 'rp-button-row');
  actions.appendChild(button('复制草稿', 'rp-btn primary', () => {
    navigator.clipboard.writeText(text(pack.draft)).then(() => ctx.ui.toast('草稿已复制')).catch(() => ctx.ui.toast('复制失败', true));
  }));
  actions.appendChild(button('打开来源', 'rp-btn', () => openSource(ctx, pack.source || {})));
  section.appendChild(actions);
  return section;
}

function feedbackComposer(ctx, state, project, outcome, host) {
  host.innerHTML = '';
  const form = node('form', 'rp-feedback-form');
  const labels = {
    progress: ['有新进展', '粘贴新事实、原话或附件路径'],
    no_progress: ['暂无进展', '可补一句原因（可选）'],
    handled: ['我已直接处理', '补一句你实际做了什么'],
  };
  form.appendChild(node('strong', '', labels[outcome][0]));
  const textarea = node('textarea', 'rp-feedback-input');
  textarea.placeholder = labels[outcome][1];
  textarea.rows = 3;
  form.appendChild(textarea);
  let nextCheck = null;
  if (outcome === 'no_progress') {
    nextCheck = node('input', 'rp-feedback-date');
    nextCheck.type = 'date';
    const tomorrow = new Date(Date.now() + 86400000 * 7);
    nextCheck.value = tomorrow.toISOString().slice(0, 10);
    form.appendChild(nextCheck);
  }
  const actions = node('div', 'rp-button-row');
  const submit = button('确认记录', 'rp-btn primary');
  const cancel = button('取消', 'rp-btn', () => { host.innerHTML = ''; });
  actions.appendChild(submit);
  actions.appendChild(cancel);
  form.appendChild(actions);
  form.onsubmit = async (event) => {
    event.preventDefault();
    submit.disabled = true;
    const payload = {
      project_ref: project.project_ref,
      outcome,
      note: textarea.value.trim(),
      next_check: nextCheck ? nextCheck.value : '',
    };
    try {
      const { json } = await ctx.api.apiJson('/api/real-projects/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!json.ok) {
        ctx.ui.toast(json.error || '记录失败', true);
        submit.disabled = false;
        return;
      }
      ctx.ui.toast('新事实已记录，项目投影已刷新');
      await ctx.api.refresh();
      render(ctx, state);
    } catch (error) {
      ctx.ui.toast('记录失败', true);
      submit.disabled = false;
    }
  };
  host.appendChild(form);
  textarea.focus();
}

function renderCheckpoint(ctx, state, project) {
  if (text(project.primary_action?.type) !== 'needs_progress') return null;
  const section = node('section', 'rp-panel rp-checkpoint');
  section.appendChild(sectionTitle('项目检查点', project.checkpoint?.expected_change || '等待新的现实反馈', project.checkpoint?.due_at || '未设固定日期'));
  section.appendChild(node('p', 'rp-panel-lead', project.checkpoint?.reason || project.primary_action?.reason || '请补充最新事实后再刷新项目判断。'));
  const actions = node('div', 'rp-checkpoint-actions');
  const composer = node('div', 'rp-feedback-host');
  actions.appendChild(button('有新进展', 'rp-choice progress', () => feedbackComposer(ctx, state, project, 'progress', composer)));
  actions.appendChild(button('暂无进展', 'rp-choice waiting', () => feedbackComposer(ctx, state, project, 'no_progress', composer)));
  actions.appendChild(button('我已直接处理', 'rp-choice handled', () => feedbackComposer(ctx, state, project, 'handled', composer)));
  section.appendChild(actions);
  section.appendChild(composer);
  return section;
}

function renderFacts(ctx, project) {
  const section = node('section', 'rp-panel');
  section.appendChild(sectionTitle('证据化事实', '同一事实只出现一次', `${project.facts?.length || 0} 项`));
  const list = node('div', 'rp-fact-list');
  (project.facts || []).forEach((fact) => {
    const row = node('article', `rp-fact${fact.conflict ? ' has-conflict' : ''}`);
    const top = node('div', 'rp-fact-top');
    top.appendChild(node('strong', '', fact.summary));
    top.appendChild(badge(fact.conflict ? '来源冲突' : (fact.certainty || 'confirmed'), fact.conflict ? 'tone-decision' : ''));
    row.appendChild(top);
    if (fact.impact) row.appendChild(node('p', '', fact.impact));
    row.appendChild(renderEvidenceSources(ctx, fact));
    list.appendChild(row);
  });
  section.appendChild(list);
  return section;
}

function renderMilestones(project) {
  const section = node('section', 'rp-panel');
  section.appendChild(sectionTitle('可核验进展', '不用任务百分比', `${project.milestones?.length || 0} 个里程碑`));
  const timeline = node('div', 'rp-milestones');
  (project.milestones || []).forEach((item) => {
    const row = node('div', `rp-milestone state-${item.state || 'waiting'}`);
    row.appendChild(node('span', 'rp-milestone-dot'));
    const copy = node('div', 'rp-milestone-copy');
    copy.appendChild(node('strong', '', item.label));
    copy.appendChild(node('span', '', `${MILESTONE_LABELS[item.state] || item.state || '等待'}${item.receipt ? ` · ${item.receipt}` : ''}`));
    row.appendChild(copy);
    timeline.appendChild(row);
  });
  section.appendChild(timeline);
  return section;
}

function renderManagedTaskRow(ctx, task) {
  const row = button('', 'rp-managed-task', () => {
    if (ctx.renderDetail?.openTaskDetail) ctx.renderDetail.openTaskDetail(task.path);
  });
  const copy = node('div', 'rp-managed-task-copy');
  copy.appendChild(node('span', 'rp-task-code', task.task_id || '未编号'));
  copy.appendChild(node('strong', '', task.title || task.path || '未命名任务'));
  const meta = [projectRoleLabel(task.project_role), task.assignee, task.due_date ? `截止 ${task.due_date}` : ''].filter(Boolean).join(' · ');
  if (meta) copy.appendChild(node('small', '', meta));
  row.appendChild(copy);
  row.appendChild(badge(task.status || 'todo'));
  return row;
}

function renderTaskComposer(ctx, state, project) {
  const section = node('section', 'rp-composer');
  section.appendChild(composerHeader('NEW TASK', `在“${project.title}”中建立任务`, () => {
    state.composer = '';
    render(ctx, state);
  }));
  const form = node('form', 'rp-form-grid');
  const title = textInput('清楚描述要完成并验收的结果');
  const members = Array.from(new Set([
    text(ctx.uiState?.auth?.currentUser) || 'Owner',
    ...(Array.isArray(ctx.dataState.all_members) ? ctx.dataState.all_members.map(text) : []),
  ].filter(Boolean)));
  const assignee = selectInput(members, text(ctx.uiState?.auth?.currentUser) || 'Owner');
  const priority = selectInput([
    { value: 'high', label: '高' },
    { value: 'medium', label: '中' },
    { value: 'low', label: '低' },
  ], 'medium');
  const projectRole = selectInput(PROJECT_ROLE_OPTIONS, 'execution');
  const dueDate = textInput('', 'date');
  const body = textareaInput('可选：补充背景、输入材料和完成标准；留空时使用标准任务模板。', 5);
  const titleField = formControl('任务标题', title);
  titleField.classList.add('rp-form-span');
  form.appendChild(titleField);
  form.appendChild(formControl('负责人', assignee));
  form.appendChild(formControl('优先级', priority));
  form.appendChild(formControl('项目角色', projectRole, '执行和交付进入中央画布；其余角色保留在项目任务清单。'));
  form.appendChild(formControl('截止日期（可选）', dueDate));
  form.appendChild(formControl('项目目录', Object.assign(textInput(), {
    value: projectWorkdir(project),
    readOnly: true,
  }), '任务仍写入个人调度队列；这里仅决定执行边界。'));
  const bodyField = formControl('任务说明（可选）', body);
  bodyField.classList.add('rp-form-span');
  form.appendChild(bodyField);
  const error = node('p', 'rp-form-error');
  error.setAttribute('role', 'alert');
  const actions = node('div', 'rp-form-actions rp-form-span');
  const submit = button('建立任务卡', 'rp-btn primary');
  actions.appendChild(error);
  actions.appendChild(submit);
  form.appendChild(actions);
  form.onsubmit = async (event) => {
    event.preventDefault();
    error.textContent = '';
    submit.disabled = true;
    submit.textContent = '正在建卡';
    try {
      const { json } = await ctx.api.apiJson('/api/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project: '个人调度',
          project_ref: project.project_ref,
          project_role: projectRole.value,
          title: title.value.trim(),
          assignee: assignee.value,
          priority: priority.value,
          due_date: dueDate.value,
          workdir: projectWorkdir(project) || undefined,
          body: body.value,
        }),
      });
      if (!json.ok) {
        error.textContent = json.message || json.error || '任务创建失败';
        return;
      }
      state.composer = '';
      await ctx.api.refresh();
      ctx.ui.toast(`${json.task_id} 已建立并归入项目`);
      render(ctx, state);
    } catch (err) {
      error.textContent = '网络错误，请稍后重试';
    } finally {
      submit.disabled = false;
      submit.textContent = '建立任务卡';
    }
  };
  section.appendChild(form);
  return section;
}

function renderAssignTaskComposer(ctx, state, project) {
  const section = node('section', 'rp-composer');
  section.appendChild(composerHeader('LINK EXISTING TASK', '把已有任务归入项目', () => {
    state.composer = '';
    state.taskQuery = '';
    render(ctx, state);
  }));
  section.appendChild(node('p', 'rp-composer-intro', '只显示尚未归属且未完成的任务。归入操作会在原卡写入 project_ref 与 project_role，不移动文件。'));
  const projectRole = selectInput(PROJECT_ROLE_OPTIONS, 'execution');
  section.appendChild(formControl('项目角色', projectRole, '选择这张卡在项目中的职责，而不是它所属的看板域。'));
  const search = textInput('搜索任务编号、标题或负责人');
  search.value = state.taskQuery || '';
  section.appendChild(formControl('查找任务', search));
  const results = node('div', 'rp-assign-results');
  const draw = () => {
    results.innerHTML = '';
    const candidates = unassignedProjectTaskCandidates(ctx.dataState.tasks, search.value);
    const meta = node('div', 'rp-assign-meta', `${candidates.length} 张可归属任务`);
    results.appendChild(meta);
    candidates.slice(0, 40).forEach((task) => {
      const row = node('article', 'rp-assign-row');
      const copy = node('div', 'rp-managed-task-copy');
      copy.appendChild(node('span', 'rp-task-code', task.task_id || '未编号'));
      copy.appendChild(node('strong', '', task.title || task.path));
      copy.appendChild(node('small', '', [task.assignee, task.status].filter(Boolean).join(' · ')));
      row.appendChild(copy);
      const link = button('归入项目', 'rp-btn', async () => {
        link.disabled = true;
        link.textContent = '正在归入';
        try {
          const { json } = await ctx.api.apiJson('/api/real-projects/assign-task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_ref: project.project_ref, project_role: projectRole.value, path: task.path }),
          });
          if (!json.ok) {
            ctx.ui.toast(json.error || '归属失败', true);
            return;
          }
          await ctx.api.refresh();
          ctx.ui.toast(`${task.task_id || '任务'} 已归入项目`);
          render(ctx, state);
        } catch (err) {
          ctx.ui.toast('网络错误，归属失败', true);
        } finally {
          link.disabled = false;
          link.textContent = '归入项目';
        }
      });
      row.appendChild(link);
      results.appendChild(row);
    });
    if (!candidates.length) results.appendChild(node('p', 'rp-empty-inline', '没有符合条件的未归属任务。'));
  };
  search.addEventListener('input', () => {
    state.taskQuery = search.value;
    draw();
  });
  draw();
  section.appendChild(results);
  return section;
}

function renderTasks(ctx, state, project) {
  const tasks = project.tasks || { linked: [], active: [], active_count: 0, done_count: 0 };
  const section = node('section', 'rp-panel rp-task-workspace');
  const head = node('div', 'rp-task-workspace-head');
  const roleSummary = projectRoleSummary(tasks.role_counts);
  head.appendChild(sectionTitle(
    'TASKS',
    '任务工作台',
    `${tasks.active_count || 0} 进行中 · ${tasks.done_count || 0} 已完成${roleSummary ? ` · ${roleSummary}` : ''}`,
  ));
  const actions = node('div', 'rp-button-row');
  actions.appendChild(button('＋ 新建任务', 'rp-btn primary', () => {
    state.composer = state.composer === 'new-task' ? '' : 'new-task';
    render(ctx, state);
  }));
  actions.appendChild(button('归入已有任务', 'rp-btn', () => {
    state.composer = state.composer === 'assign-task' ? '' : 'assign-task';
    render(ctx, state);
  }));
  head.appendChild(actions);
  section.appendChild(head);
  if (state.composer === 'new-task') section.appendChild(renderTaskComposer(ctx, state, project));
  if (state.composer === 'assign-task') section.appendChild(renderAssignTaskComposer(ctx, state, project));
  const active = Array.isArray(tasks.active) ? tasks.active : [];
  const done = (Array.isArray(tasks.linked) ? tasks.linked : []).filter((task) => {
    return TERMINAL_TASK_STATUSES.has(text(task.status).toLowerCase());
  });
  if (active.length) {
    const list = node('div', 'rp-managed-task-list');
    active.forEach((task) => list.appendChild(renderManagedTaskRow(ctx, task)));
    section.appendChild(list);
  } else {
    const empty = node('div', 'rp-task-empty');
    empty.appendChild(node('strong', '', '这个项目还没有进行中的任务'));
    empty.appendChild(node('p', '', '建立新卡，或把调度台里的已有卡显式归入项目。'));
    section.appendChild(empty);
  }
  if (done.length) {
    const archive = node('details', 'rp-done-tasks');
    archive.appendChild(node('summary', '', `已完成任务 · ${done.length}`));
    const list = node('div', 'rp-managed-task-list');
    done.forEach((task) => list.appendChild(renderManagedTaskRow(ctx, task)));
    archive.appendChild(list);
    section.appendChild(archive);
  }
  return section;
}

function renderPending(project) {
  if (!Array.isArray(project.pending_changes) || !project.pending_changes.length) return null;
  const section = node('section', 'rp-panel rp-pending');
  section.appendChild(sectionTitle('待确认变化', '确认前不影响项目判断', `${project.pending_changes.length} 项`));
  project.pending_changes.slice(0, 8).forEach((change) => {
    const row = node('div', 'rp-pending-row');
    row.appendChild(badge(change.kind || 'changed', 'tone-decision'));
    row.appendChild(node('span', '', change.relative_path || change.path));
    section.appendChild(row);
  });
  return section;
}

function renderBackstageActions(ctx, project) {
  if (!Array.isArray(project.backstage_actions) || !project.backstage_actions.length) return null;
  const section = node('section', 'rp-panel rp-project-actions');
  section.appendChild(sectionTitle('项目行动路由', '缺口先复用既有任务', `${project.backstage_actions.length} 项`));
  project.backstage_actions.forEach((action) => {
    const row = node('article', 'rp-fact');
    const top = node('div', 'rp-fact-top');
    top.appendChild(node('strong', '', action.trigger?.summary || '项目事实缺口'));
    const routeLabel = action.routing_status === 'ready_backstage'
      ? '后台可执行'
      : (action.routing_status === 'requires_owner' ? '复用现有人闸' : '尚未绑定');
    top.appendChild(badge(routeLabel, action.routing_status === 'requires_owner' ? 'tone-decision' : ''));
    row.appendChild(top);
    row.appendChild(node('p', '', action.reason || ''));
    if (projectActionControlNames(action).includes('open_task')) {
      const task = action.bound_task;
      const actions = node('div', 'rp-button-row');
      actions.appendChild(button(`打开 ${task.task_id || '既有任务'}`, 'rp-btn', () => {
        if (ctx.renderDetail?.openTaskDetail) ctx.renderDetail.openTaskDetail(task.path);
      }));
      if (action.next_action) actions.appendChild(node('span', 'rp-section-meta', action.next_action));
      row.appendChild(actions);
    }
    section.appendChild(row);
  });
  return section;
}

function renderProjectOverviewDrawer(ctx, state, project, onClose) {
  const drawer = node('aside', 'rp-project-overview-drawer');
  drawer.setAttribute('aria-label', '项目概况');
  const head = node('header', 'rp-project-overview-head');
  const headCopy = node('div', '');
  headCopy.appendChild(node('span', 'rp-eyebrow', 'PROJECT BRIEF'));
  headCopy.appendChild(node('h2', '', project.title));
  const lifecycle = text(project.lifecycle || 'active');
  const status = node('div', 'rp-project-overview-status');
  status.appendChild(node('span', `rp-project-dot health-${text(project.health || 'normal')}`));
  status.appendChild(node('span', '', LIFECYCLE_LABELS[lifecycle] || lifecycle));
  if (text(project.origin?.type) === 'conversation') {
    status.appendChild(node('span', 'rp-project-overview-status-separator', '·'));
    status.appendChild(node('span', 'rp-project-overview-origin', `来源对话 · ${text(project.origin.provider) || 'conversation'} · ${text(project.origin.thread_id) || 'unknown thread'}`));
  }
  headCopy.appendChild(status);
  head.appendChild(headCopy);
  const close = button('×', 'rp-project-overview-close', onClose);
  close.setAttribute('aria-label', '关闭项目概况');
  head.appendChild(close);
  drawer.appendChild(head);

  const body = node('div', 'rp-project-overview-body');
  const milestones = Array.isArray(project.milestones) ? project.milestones : [];
  const verifiedCount = milestones.filter((item) => text(item?.state) === 'verified').length;
  const facts = Array.isArray(project.facts) ? project.facts : [];
  const unknowns = Array.isArray(project.unknowns) ? project.unknowns : [];
  const posture = node('section', 'rp-project-brief-posture');
  const stage = node('div', 'rp-project-brief-property');
  stage.appendChild(node('span', 'rp-project-brief-label', '当前阶段'));
  stage.appendChild(node('strong', '', `${LIFECYCLE_LABELS[lifecycle] || lifecycle} · ${text(project.health || 'normal') === 'normal' ? '状态正常' : text(project.health || '未核实')}`));
  posture.appendChild(stage);
  const verification = node('div', 'rp-project-brief-property');
  verification.appendChild(node('span', 'rp-project-brief-label', '验证状态'));
  verification.appendChild(node('strong', '', milestones.length ? `${verifiedCount}/${milestones.length} 里程碑已验证` : `${facts.length} 项事实已登记`));
  posture.appendChild(verification);
  const roleMix = node('div', 'rp-project-brief-property');
  roleMix.appendChild(node('span', 'rp-project-brief-label', '项目卡角色'));
  roleMix.appendChild(node('strong', '', projectRoleSummary(project.tasks?.role_counts) || '尚未分类'));
  posture.appendChild(roleMix);
  const canvasWork = node('div', 'rp-project-brief-property');
  canvasWork.appendChild(node('span', 'rp-project-brief-label', '中央画布'));
  canvasWork.appendChild(node('strong', '', `${Number(project.tasks?.canvas_count || 0)} 张执行/交付 · ${Number(project.tasks?.active_count || 0)} 张非终态`));
  posture.appendChild(canvasWork);
  body.appendChild(posture);

  const actionMetaValue = actionMeta(project.primary_action?.type);
  const primary = node('section', `rp-project-brief-action tone-${actionMetaValue.tone}`);
  const primaryHead = node('div', 'rp-project-brief-section-head');
  primaryHead.appendChild(node('span', 'rp-project-brief-label', '当前行动'));
  primaryHead.appendChild(node('span', 'rp-project-brief-action-type', actionMetaValue.label));
  primary.appendChild(primaryHead);
  primary.appendChild(node('h3', '', project.primary_action?.summary || '暂无需动作'));
  primary.appendChild(node('p', '', project.primary_action?.reason || project.recommendation || ''));
  const primaryFoot = node('div', 'rp-project-brief-action-foot');
  const owner = text(project.primary_action?.bound_task?.assignee);
  if (owner) primaryFoot.appendChild(badge(owner, 'rp-project-brief-owner'));
  const humanGate = ['needs_reply', 'needs_decision'].includes(text(project.primary_action?.type));
  if (humanGate) {
    const gate = node('span', 'rp-project-brief-gate');
    gate.appendChild(node('i'));
    gate.appendChild(node('span', '', 'Owner 人闸'));
    primaryFoot.appendChild(gate);
  }
  const actionTime = text(project.primary_action?.due_at || project.checkpoint?.due_at);
  if (actionTime) primaryFoot.appendChild(node('span', 'rp-project-brief-time', actionTime));
  if (primaryFoot.childNodes.length) primary.appendChild(primaryFoot);
  body.appendChild(primary);

  const context = node('section', 'rp-project-brief-context');
  const latest = node('div', 'rp-project-brief-context-row');
  latest.appendChild(node('span', 'rp-project-brief-label', '最近变化'));
  latest.appendChild(node('p', '', project.latest_update || '尚无已确认变化'));
  context.appendChild(latest);
  const nextGate = node('div', 'rp-project-brief-context-row');
  nextGate.appendChild(node('span', 'rp-project-brief-label', '下一闸门'));
  nextGate.appendChild(node('p', '', project.checkpoint?.expected_change || project.recommendation || '尚未定义下一闸门'));
  const gateTime = text(project.checkpoint?.due_at || project.time_window);
  if (gateTime) nextGate.appendChild(node('small', '', gateTime));
  context.appendChild(nextGate);
  body.appendChild(context);

  const appendDisclosure = (label, items, className, itemText) => {
    const details = document.createElement('details');
    details.className = `rp-project-brief-disclosure ${className}`;
    const summary = document.createElement('summary');
    summary.appendChild(node('span', '', label));
    summary.appendChild(node('span', 'rp-project-brief-count', String(items.length)));
    details.appendChild(summary);
    const list = node('ul');
    if (items.length) items.forEach((item) => list.appendChild(node('li', '', itemText(item))));
    else list.appendChild(node('li', 'rp-project-brief-empty', '暂无记录'));
    details.appendChild(list);
    body.appendChild(details);
  };
  appendDisclosure('已确认事实', facts, 'is-facts', (item) => text(item?.summary || item));
  appendDisclosure('未知项', unknowns, 'is-unknowns', (item) => text(item));
  drawer.appendChild(body);
  return drawer;
}

async function saveProjectUpdate(ctx, state, payload, options = {}) {
  const { json } = await ctx.api.apiJson('/api/real-projects/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!json.ok) throw new Error(json.error || '修改项目失败');
  await ctx.api.refresh();
  if (options.leaveArchived && text(payload.lifecycle) === 'archived') {
    state.selectedProjectRef = defaultRealProjectRef(ctx.dataState.real_projects, '');
    state.lastProjectRef = state.selectedProjectRef;
    rememberRealProjectRef(state.selectedProjectRef);
  }
  state.projectMenuRef = '';
  state.editingProjectRef = '';
  render(ctx, state);
  return json;
}

function renderProjectEditModal(ctx, state, project) {
  const backdrop = node('div', 'rp-project-modal-backdrop');
  backdrop.setAttribute('role', 'presentation');
  const dialog = node('section', 'rp-project-modal');
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-labelledby', 'rp-project-edit-title');
  const head = node('div', 'rp-project-modal-head');
  const heading = node('div');
  heading.appendChild(node('span', 'rp-chain-label', 'PROJECT SETTINGS'));
  const titleEl = node('h2', '', '编辑项目');
  titleEl.id = 'rp-project-edit-title';
  heading.appendChild(titleEl);
  head.appendChild(heading);
  const close = button('关闭', 'rp-project-modal-close', () => {
    state.editingProjectRef = '';
    render(ctx, state);
  });
  head.appendChild(close);
  dialog.appendChild(head);

  const form = node('form', 'rp-form-grid rp-project-edit-form');
  const projectRef = textInput();
  projectRef.value = text(project.project_ref);
  projectRef.readOnly = true;
  const title = textInput();
  title.value = text(project.title);
  const intent = textareaInput('', 4);
  intent.value = text(project.current_intent);
  const workdir = textInput('/absolute/path/to/project');
  workdir.value = projectWorkdir(project);
  const lifecycle = selectInput([
    { value: 'active', label: '进行中' },
    { value: 'paused', label: '暂停' },
    { value: 'completed', label: '已完成' },
    { value: 'archived', label: '已归档（退出项目区）' },
  ], text(project.lifecycle || 'active'));
  form.appendChild(formControl('稳定项目 ID', projectRef, '项目 ID 建立后不可修改。'));
  form.appendChild(formControl('项目状态', lifecycle));
  const titleField = formControl('项目名称', title);
  titleField.classList.add('rp-form-span');
  form.appendChild(titleField);
  const intentField = formControl('项目结果', intent);
  intentField.classList.add('rp-form-span');
  form.appendChild(intentField);
  const workdirField = formControl('项目目录（可选）', workdir, '修改目录只改变项目事实入口，不移动任何文件。');
  workdirField.classList.add('rp-form-span');
  form.appendChild(workdirField);
  const error = node('p', 'rp-form-error');
  error.setAttribute('role', 'alert');
  const actions = node('div', 'rp-form-actions rp-form-span');
  actions.appendChild(error);
  const submit = button('保存修改', 'rp-btn primary');
  actions.appendChild(submit);
  form.appendChild(actions);
  form.onsubmit = async (event) => {
    event.preventDefault();
    error.textContent = '';
    submit.disabled = true;
    submit.textContent = '正在保存';
    try {
      await saveProjectUpdate(ctx, state, {
        project_ref: project.project_ref,
        title: title.value.trim(),
        current_intent: intent.value.trim(),
        workdir: workdir.value.trim(),
        lifecycle: lifecycle.value,
      }, { leaveArchived: true });
      ctx.ui.toast('项目设置已保存');
    } catch (err) {
      error.textContent = err?.message || '保存项目失败';
      submit.disabled = false;
      submit.textContent = '保存修改';
    }
  };
  dialog.appendChild(form);
  backdrop.appendChild(dialog);
  backdrop.onclick = (event) => {
    if (event.target !== backdrop) return;
    state.editingProjectRef = '';
    render(ctx, state);
  };
  return backdrop;
}

function renderProjectCanvasWorkbench(ctx, state, project, projects) {
  const shell = node('section', `rp-canvas-workbench${state.projectRailCollapsed ? ' is-project-rail-collapsed' : ''}`);
  const projectRail = node('aside', 'rp-canvas-project-rail');
  projectRail.setAttribute('aria-label', '项目区');
  const railHead = node('div', 'rp-canvas-project-head');
  const railHeadCopy = node('div', 'rp-canvas-project-head-copy');
  railHeadCopy.appendChild(node('span', 'rp-chain-label', 'PROJECTS'));
  railHeadCopy.appendChild(node('strong', '', '项目区'));
  railHead.appendChild(railHeadCopy);
  const railToggle = button(state.projectRailCollapsed ? '›' : '‹', 'rp-canvas-project-collapse', () => {
    const collapsed = !state.projectRailCollapsed;
    state.projectRailCollapsed = collapsed;
    rememberProjectRailCollapsed(collapsed);
    shell.classList.toggle('is-project-rail-collapsed', collapsed);
    railToggle.textContent = collapsed ? '›' : '‹';
    railToggle.setAttribute('aria-expanded', String(!collapsed));
    railToggle.setAttribute('aria-label', collapsed ? '展开项目区' : '收起项目区');
    railToggle.title = collapsed ? '展开项目区' : '收起项目区';
  });
  railToggle.setAttribute('aria-expanded', String(!state.projectRailCollapsed));
  railToggle.setAttribute('aria-label', state.projectRailCollapsed ? '展开项目区' : '收起项目区');
  railToggle.title = state.projectRailCollapsed ? '展开项目区' : '收起项目区';
  railHead.appendChild(railToggle);
  projectRail.appendChild(railHead);

  const create = button('＋ 新建项目', 'rp-canvas-project-create', () => ctx.realProjects?.openCreate());
  projectRail.appendChild(create);
  const list = node('nav', 'rp-canvas-project-list');
  list.setAttribute('aria-label', '切换项目');
  const visibleProjects = (Array.isArray(projects) ? projects : []).filter((item) => (
    state.showArchived || text(item.lifecycle || 'active') !== 'archived'
  ));
  visibleProjects.forEach((item) => {
    const wrap = node('div', `rp-canvas-project-row-wrap${item.project_ref === project.project_ref ? ' is-active' : ''}`);
    const row = button('', `rp-canvas-project-row${item.project_ref === project.project_ref ? ' is-active' : ''}`, () => {
      state.selectedProjectRef = text(item.project_ref);
      state.lastProjectRef = text(item.project_ref);
      rememberRealProjectRef(item.project_ref);
      state.composer = '';
      state.taskQuery = '';
      render(ctx, state);
    });
    const copy = node('span', 'rp-canvas-project-copy');
    copy.appendChild(node('strong', '', item.title || item.project_ref));
    const lifecycleLabel = LIFECYCLE_LABELS[text(item.lifecycle || 'active')] || text(item.lifecycle);
    copy.appendChild(node('small', '', `${Number(item.tasks?.active_count || 0)} 个进行中任务 · ${lifecycleLabel}`));
    row.appendChild(copy);
    row.appendChild(node('i', `rp-project-dot health-${item.health || 'normal'}`));
    wrap.appendChild(row);
    const more = button('•••', 'rp-canvas-project-more', (event) => {
      event.stopPropagation();
      state.projectMenuRef = state.projectMenuRef === item.project_ref ? '' : item.project_ref;
      render(ctx, state);
    });
    more.setAttribute('aria-label', `更多操作：${item.title || item.project_ref}`);
    more.setAttribute('aria-expanded', String(state.projectMenuRef === item.project_ref));
    wrap.appendChild(more);
    if (state.projectMenuRef === item.project_ref) {
      const menu = node('div', 'rp-canvas-project-menu');
      menu.setAttribute('role', 'menu');
      menu.appendChild(button('编辑项目', 'rp-canvas-project-menu-item', () => {
        state.projectMenuRef = '';
        state.editingProjectRef = item.project_ref;
        render(ctx, state);
      }));
      const lifecycle = text(item.lifecycle || 'active');
      const resumable = lifecycle === 'paused' || lifecycle === 'completed' || lifecycle === 'archived';
      menu.appendChild(button(resumable ? '恢复项目' : '暂停项目', 'rp-canvas-project-menu-item', async () => {
        try {
          await saveProjectUpdate(ctx, state, {
            project_ref: item.project_ref,
            lifecycle: resumable ? 'active' : 'paused',
          });
          ctx.ui.toast(resumable ? '项目已恢复' : '项目已暂停');
        } catch (err) {
          ctx.ui.toast(err?.message || '修改项目失败');
        }
      }));
      if (lifecycle !== 'archived') {
        menu.appendChild(button('归档项目…', 'rp-canvas-project-menu-item is-danger', async () => {
          const confirmed = globalThis.confirm?.(`归档“${item.title || item.project_ref}”？\n\n任务卡、文件和项目记录都不会删除；项目将退出左侧项目区，可从已归档视图恢复。`);
          if (!confirmed) return;
          try {
            await saveProjectUpdate(ctx, state, {
              project_ref: item.project_ref,
              lifecycle: 'archived',
            }, { leaveArchived: true });
            ctx.ui.toast('项目已归档；任务卡与文件均保留');
          } catch (err) {
            ctx.ui.toast(err?.message || '归档项目失败');
          }
        }));
      }
      wrap.appendChild(menu);
    }
    list.appendChild(wrap);
  });
  projectRail.appendChild(list);
  const railFoot = node('div', 'rp-canvas-project-foot');
  const overviewButton = button('项目概况', 'rp-canvas-project-foot-button is-primary', () => {});
  const archivedCount = (Array.isArray(projects) ? projects : []).filter((item) => text(item.lifecycle) === 'archived').length;
  if (archivedCount) railFoot.appendChild(button(state.showArchived ? '隐藏已归档' : `已归档项目 ${archivedCount}`, 'rp-canvas-project-foot-button', () => {
    state.showArchived = !state.showArchived;
    render(ctx, state);
  }));
  railFoot.appendChild(button('返回调度台', 'rp-canvas-project-foot-button', () => ctx.renderBoard?.switchView('console')));
  railFoot.prepend(overviewButton);
  projectRail.appendChild(railFoot);

  const studio = node('div', 'rp-canvas-studio');
  const frame = document.createElement('iframe');
  frame.className = 'rp-canvas-frame';
  frame.title = `${project.title || project.project_ref} Canvas Studio`;
  frame.loading = 'eager';
  frame.src = `/canvas/?map=${encodeURIComponent(`project:${project.project_ref}`)}&embedded=1&project_title=${encodeURIComponent(project.title || project.project_ref)}`;
  studio.appendChild(frame);
  shell.appendChild(projectRail);
  shell.appendChild(studio);
  const closeOverview = () => {
    shell.classList.remove('is-overview-open');
    overviewButton.setAttribute('aria-expanded', 'false');
  };
  const overviewDrawer = renderProjectOverviewDrawer(ctx, state, project, closeOverview);
  overviewButton.setAttribute('aria-expanded', 'false');
  overviewButton.onclick = () => {
    const open = !shell.classList.contains('is-overview-open');
    shell.classList.toggle('is-overview-open', open);
    overviewButton.setAttribute('aria-expanded', String(open));
  };
  shell.appendChild(overviewDrawer);
  const editingProject = (Array.isArray(projects) ? projects : []).find((item) => (
    item.project_ref === state.editingProjectRef
  ));
  if (editingProject) shell.appendChild(renderProjectEditModal(ctx, state, editingProject));
  if (state.creatingProject) shell.appendChild(renderProjectCreateModal(ctx, state));
  return shell;
}

function renderEmptyProjectWorkbench(ctx, root, state) {
  const app = node('div', 'rp-app rp-project-entry');
  const shell = node('section', 'rp-canvas-workbench rp-canvas-workbench-empty');
  const rail = node('aside', 'rp-canvas-project-rail');
  const head = node('div', 'rp-canvas-project-head');
  head.appendChild(node('span', 'rp-chain-label', 'PROJECTS'));
  head.appendChild(node('strong', '', '项目区'));
  rail.appendChild(head);
  rail.appendChild(button('＋ 新建项目', 'rp-canvas-project-create', () => ctx.realProjects?.openCreate()));
  const foot = node('div', 'rp-canvas-project-foot');
  foot.appendChild(button('返回调度台', 'rp-canvas-project-foot-button', () => ctx.renderBoard?.switchView('console')));
  rail.appendChild(foot);
  const empty = node('main', 'rp-canvas-project-empty');
  empty.appendChild(node('span', 'rp-chain-label', 'PROJECT CANVAS'));
  empty.appendChild(node('h2', '', '先建立第一个项目'));
  empty.appendChild(node('p', '', '项目建立后会直接进入画布，并在左侧项目区持续可见。'));
  empty.appendChild(button('＋ 新建项目', 'rp-btn primary', () => ctx.realProjects?.openCreate()));
  shell.appendChild(rail);
  shell.appendChild(empty);
  if (state.creatingProject) shell.appendChild(renderProjectCreateModal(ctx, state));
  app.appendChild(shell);
  root.classList.add('is-project-workbench');
  root.appendChild(app);
}

function renderDetail(ctx, root, state, project, projects) {
  const app = node('div', 'rp-app rp-project-entry');
  app.appendChild(renderProjectCanvasWorkbench(ctx, state, project, projects));
  root.appendChild(app);
}

function render(ctx, state) {
  const root = document.getElementById('vw-projects');
  if (!root) return;
  root.className = 'vw real-projects-shell' + (ctx.uiState.board.activeView === 'projects' ? ' on' : '');
  root.innerHTML = '';
  const payload = ctx.dataState.real_projects;
  if (!payload || !payload.ok) {
    const error = node('div', 'rp-app rp-empty');
    error.appendChild(node('h3', '', '真实项目注册表不可用'));
    error.appendChild(node('p', '', payload?.error || '未读取到已确认项目'));
    root.appendChild(error);
    return;
  }
  const projects = payload.projects || [];
  const selectableProjects = projects.filter((row) => state.showArchived || text(row.lifecycle || 'active') !== 'archived');
  let project = selectableProjects.find((row) => row.project_ref === state.selectedProjectRef);
  if (!project) {
    const fallbackRef = defaultRealProjectRef(payload, '');
    project = projects.find((row) => row.project_ref === fallbackRef);
    if (project) {
      state.selectedProjectRef = project.project_ref;
      state.lastProjectRef = project.project_ref;
      rememberRealProjectRef(project.project_ref);
    }
  }
  if (project) {
    root.classList.add('is-project-workbench');
    renderDetail(ctx, root, state, project, projects);
  }
  else renderEmptyProjectWorkbench(ctx, root, state);
}

export function setupRenderProjects(ctx) {
  const initialProjectRef = defaultRealProjectRef(ctx.dataState.real_projects, storedRealProjectRef());
  rememberRealProjectRef(initialProjectRef);
  const state = {
    selectedProjectRef: initialProjectRef,
    lastProjectRef: initialProjectRef,
    composer: '',
    taskQuery: '',
    projectMenuRef: '',
    editingProjectRef: '',
    creatingProject: false,
    projectRailCollapsed: storedProjectRailCollapsed(),
    showArchived: false,
  };
  ctx.realProjects = {
    render: () => render(ctx, state),
    openCreate: () => {
      state.creatingProject = true;
      state.taskQuery = '';
      ctx.renderBoard?.switchView('projects');
      render(ctx, state);
    },
    open: (projectRef) => {
      state.selectedProjectRef = text(projectRef);
      state.lastProjectRef = state.selectedProjectRef;
      rememberRealProjectRef(state.selectedProjectRef);
      state.composer = '';
      state.creatingProject = false;
      state.taskQuery = '';
      ctx.renderBoard?.switchView('projects');
      render(ctx, state);
    },
    state,
  };
}
