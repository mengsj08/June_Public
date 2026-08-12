import {
  HttpDocumentAdapter,
  normalizeConversationSession,
  normalizeReviewSession,
  registerCommaEditor,
} from '/comma-kit/comma-editor.js';

registerCommaEditor();

const DOC_PATH = new URLSearchParams(location.search).get('doc') || 'paper.md';
const DOCUMENT_SWITCH_TOAST_KEY = 'comma-review:document-switch-toast';
const DEFAULT_AI_TOOL = 'codex';
const $ = (id) => document.getElementById(id);
const editor = $('comma-editor');
const reviewState = {
  active: null, activeRun: null, sessions: [], running: false, preflight: null,
  acceptedOperationIds: new Set(), commentsById: new Map(),
};
const archiveState = { versions: [], drafts: [], currentRev: '', exportCapabilities: null, loading: false };
const overviewState = { summary: null, currentRev: '', loading: false };
const conversationState = {
  active: null, sessions: [], sourceQuote: null, running: false,
  composerMode: 'root', parentMessageId: '', writebackMessageId: '', quickSource: null,
};
const importState = { record: null, busy: false };
const documentMenuState = { documents: [], loading: false };
const evidenceState = { sources: [], selectedIds: new Set(), loading: false, uploading: false };
let editorActionState = null;
let runtimeCapabilities = null;
let runtimeLoading = null;
let toastTimer = null;
const CLI_UNAVAILABLE_GUIDE = '未检测到可用 AI provider，请启动并登录 BigApple 桌面应用，或安装并登录 Codex/Claude CLI';

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function toast(message, isError = false, duration = 2400) {
  let element = $('toast');
  if (!element) {
    element = document.createElement('div');
    element.id = 'toast';
    element.className = 'toast';
    document.body.appendChild(element);
  }
  element.textContent = message;
  element.classList.toggle('err', Boolean(isError));
  element.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove('on'), duration);
}

function userFacingApiError(json, fallback = '操作失败') {
  if (json?.code === 'cli_unavailable') return CLI_UNAVAILABLE_GUIDE;
  return json?.message || json?.error || fallback;
}

async function apiJson(url, init = {}) {
  const response = await fetch(url, init);
  let json = null;
  try { json = await response.json(); } catch { json = null; }
  return { response, json: json || { ok: false, error: `HTTP ${response.status}` } };
}

function setImportError(message = '') {
  const element = $('import-error');
  element.textContent = message;
  element.hidden = !message;
}

function setImportBusy(busy, message = '') {
  importState.busy = busy;
  $('import-choose').disabled = busy;
  $('import-another').disabled = busy;
  $('import-target').disabled = busy;
  $('import-commit').disabled = busy || !importState.record;
  if (message) $('import-progress').textContent = message;
}

function resetImportDialog() {
  importState.record = null;
  importState.busy = false;
  $('import-file').value = '';
  $('import-picker').hidden = false;
  $('import-preview').hidden = true;
  $('import-another').hidden = true;
  $('import-target').value = '';
  $('import-preview-content').textContent = '';
  $('import-normalizations').hidden = true;
  $('import-normalizations').textContent = '';
  $('import-progress').textContent = '选择文件后只会暂存和预览，不会立即创建主稿。';
  $('import-commit').disabled = true;
  setImportError('');
}

function openImportDialog() {
  resetImportDialog();
  $('import-modal').hidden = false;
  $('import-modal').setAttribute('aria-hidden', 'false');
  $('import-scrim').hidden = false;
  document.body.style.overflow = 'hidden';
}

async function discardStagedImport() {
  const record = importState.record;
  if (!record || record.status !== 'staged') return;
  await apiJson(`/api/imports/${encodeURIComponent(record.id)}`, { method: 'DELETE' });
  importState.record = null;
}

async function closeImportDialog() {
  if (importState.busy) return;
  await discardStagedImport();
  $('import-modal').hidden = true;
  $('import-modal').setAttribute('aria-hidden', 'true');
  $('import-scrim').hidden = true;
  document.body.style.overflow = '';
  resetImportDialog();
}

function renderStagedImport(record) {
  importState.record = record;
  $('import-picker').hidden = true;
  $('import-preview').hidden = false;
  $('import-another').hidden = false;
  $('import-source-name').textContent = record.source?.filename || '未命名文件';
  const kib = Math.max(1, Math.round((record.source?.byte_count || 0) / 1024));
  const hash = String(record.source?.sha256 || '').replace('sha256:', '').slice(0, 16);
  const components = record.converter?.components || {};
  const converter = Object.entries(components).filter(([, version]) => version)
    .map(([name, version]) => `${name.replaceAll('_', '-')} ${version}`).join(' · ');
  $('import-source-meta').textContent = `${kib} KB · sha256 ${hash}…${converter ? ` · ${converter}` : ''}`;
  $('import-stage-status').textContent = String(record.status || 'staged').toUpperCase();
  $('import-target').value = record.candidate?.suggested_target || '';
  $('import-preview-content').textContent = record.preview || '';
  const notes = [
    ...(Array.isArray(record.normalizations) ? record.normalizations.map((item) => `处理：${item}`) : []),
    ...(Array.isArray(record.warnings) ? record.warnings.map((item) => `复核：${item}`) : []),
  ];
  $('import-normalizations').hidden = !notes.length;
  $('import-normalizations').textContent = notes.join('；');
  $('import-progress').textContent = record.preview_truncated
    ? '预览已截断；确认时仍会创建完整 Markdown。'
    : '已暂存并完成 hash 校验；确认前尚未创建主稿。';
  $('import-commit').disabled = false;
}

async function stageImportFile(file) {
  if (!file || importState.busy) return;
  const extension = file.name.toLowerCase().split('.').pop();
  if (!['docx', 'md', 'markdown'].includes(extension)) {
    return setImportError('主稿导入只接受 .docx、.md 或 .markdown。');
  }
  if (importState.record?.status === 'staged') await discardStagedImport();
  setImportError('');
  setImportBusy(true, '正在隔离暂存、计算 hash 并生成预览…');
  const params = new URLSearchParams({ kind: 'manuscript', filename: file.name });
  try {
    const { response, json } = await apiJson(`/api/imports?${params}`, {
      method: 'POST', headers: { 'Content-Type': file.type || 'text/markdown' }, body: file,
    });
    if (!response.ok || !json.ok) throw new Error(json.error || `HTTP ${response.status}`);
    renderStagedImport(json.import);
  } catch (error) {
    importState.record = null;
    setImportError(error.message || '导入暂存失败');
    $('import-progress').textContent = '没有创建主稿；可修正文件后重试。';
  } finally {
    setImportBusy(false);
  }
}

async function commitStagedImport() {
  if (!importState.record || importState.busy) return;
  const targetName = $('import-target').value.trim();
  if (!targetName) return setImportError('请填写新的 Markdown 文件名。');
  setImportError('');
  setImportBusy(true, '正在校验来源与候选 hash，并原子创建新主稿…');
  const { response, json } = await apiJson(`/api/imports/${encodeURIComponent(importState.record.id)}/commit`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_name: targetName, actor: 'June' }),
  });
  if (!response.ok || !json.ok) {
    setImportBusy(false, '主稿尚未创建；请处理上方问题后重试。');
    return setImportError(json.message || json.error || `HTTP ${response.status}`);
  }
  importState.record = json.import;
  $('import-stage-status').textContent = 'COMMITTED';
  const previousDoc = DOC_PATH;
  const targetPath = json.import.target.path;
  const switchMessage = `已切换到新主稿；原文稿〈${previousDoc}〉及其批注、版本完好，可从文件名菜单随时切回。`;
  $('import-progress').textContent = json.reused
    ? `该导入已创建过，正在打开原目标。${switchMessage}`
    : `已创建主稿和首个版本，正在打开。${switchMessage}`;
  sessionStorage.setItem(DOCUMENT_SWITCH_TOAST_KEY, switchMessage);
  const next = new URL(location.href);
  next.searchParams.set('doc', targetPath);
  location.assign(next.toString());
}

function evidenceStatusLabel(source) {
  if (source.extraction_status === 'usable' && source.full_text_confirmed) return '全文 PDF · 文本可用';
  if (source.extraction_status === 'usable') return '文本可用 · 待确认全文';
  if (source.extraction_status === 'partial') return '部分文本可用';
  if (source.extraction_status === 'image_only') return '无可用文本层';
  return '提取失败';
}

function renderEvidenceSources() {
  const root = $('evidence-list');
  const evidenceCount = $('evidence-count');
  if (evidenceCount) evidenceCount.textContent = String(evidenceState.sources.length);
  const validIds = new Set(evidenceState.sources
    .filter((source) => ['usable', 'partial'].includes(source.extraction_status))
    .map((source) => source.id));
  evidenceState.selectedIds = new Set([...evidenceState.selectedIds].filter((id) => validIds.has(id)));
  if (!evidenceState.sources.length) {
    root.innerHTML = '<div class="evidence-empty">还没有参考资料。添加 PDF 不会改动当前 Markdown。</div>';
    return;
  }
  root.innerHTML = evidenceState.sources.map((source) => {
    const metrics = source.metrics || {};
    const selectable = ['usable', 'partial'].includes(source.extraction_status);
    const selected = evidenceState.selectedIds.has(source.id);
    const warnings = (source.warnings || []).slice(0, 2);
    const summary = (source.summaries || []).filter((item) => item.status === 'ready').at(-1);
    return `<article class="evidence-card ${esc(source.extraction_status)}" data-evidence-id="${esc(source.id)}">
      <header><div><h3>${esc(source.source?.filename || 'reference.pdf')}</h3><small>${esc(String(source.source?.sha256 || '').replace('sha256:', '').slice(0, 16))}…</small></div><span class="evidence-card-status">${esc(evidenceStatusLabel(source))}</span></header>
      <div class="evidence-metrics"><span>${Number(metrics.page_count || 0)} 页</span><span>${Number(metrics.total_non_whitespace_chars || 0).toLocaleString()} 字符</span><span>${Math.round(Number(metrics.text_usable_ratio || 0) * 100)}% 页可用</span></div>
      ${warnings.length ? `<div class="evidence-warning">${warnings.map(esc).join('<br>')}</div>` : ''}
      ${summary ? `<div class="evidence-summary"><strong>${esc(String(summary.tool || '').toUpperCase())} 摘要</strong><ol>${(summary.summary_3_6 || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ol></div>` : ''}
      <div class="evidence-card-actions">
        <a href="/api/evidence-sources/${encodeURIComponent(source.id)}/file?path=${encodeURIComponent(DOC_PATH)}" target="_blank" rel="noopener">打开 PDF</a>
        ${source.extraction_status === 'usable' && !source.full_text_confirmed ? '<button type="button" data-evidence-action="confirm">确认这是全文</button>' : ''}
        ${selectable ? `<button type="button" data-evidence-action="summary">${summary ? '重新查看摘要' : '生成摘要'}</button>` : ''}
        ${selectable ? `<label><input type="checkbox" data-evidence-action="select" ${selected ? 'checked' : ''}> 用于下一次讨论/评审</label>` : ''}
      </div>
    </article>`;
  }).join('');
}

async function loadEvidenceSources() {
  if (evidenceState.loading) return;
  evidenceState.loading = true;
  $('evidence-list').innerHTML = '<p class="archive-loading">正在读取参考资料…</p>';
  const { response, json } = await apiJson(`/api/evidence-sources?path=${encodeURIComponent(DOC_PATH)}`, { cache: 'no-store' });
  evidenceState.loading = false;
  if (!response.ok || !json.ok) {
    $('evidence-list').innerHTML = `<div class="evidence-empty">${esc(json.error || '参考资料读取失败')}</div>`;
    return;
  }
  evidenceState.sources = Array.isArray(json.sources) ? json.sources : [];
  renderEvidenceSources();
}

function openEvidenceDrawer() {
  $('evidence-drawer').classList.add('open');
  $('evidence-drawer').setAttribute('aria-hidden', 'false');
  $('evidence-scrim').hidden = false;
  loadEvidenceSources();
}

function closeEvidenceDrawer() {
  $('evidence-drawer').classList.remove('open');
  $('evidence-drawer').setAttribute('aria-hidden', 'true');
  $('evidence-scrim').hidden = true;
}

function setEvidenceUploadState(message = '', isError = false) {
  const element = $('evidence-upload-state');
  element.textContent = message;
  element.hidden = !message;
  element.classList.toggle('error', isError);
}

async function attachEvidenceFile(file) {
  if (!file || evidenceState.uploading) return;
  if (!file.name.toLowerCase().endsWith('.pdf')) return setEvidenceUploadState('参考资料只接受 PDF。', true);
  evidenceState.uploading = true;
  $('evidence-choose').disabled = true;
  setEvidenceUploadState('正在本地逐页提取文本并统计覆盖率；此步骤不会调用 AI。');
  const params = new URLSearchParams({ path: DOC_PATH, filename: file.name });
  const { response, json } = await apiJson(`/api/evidence-sources?${params}`, {
    method: 'POST', headers: { 'Content-Type': file.type || 'application/pdf' }, body: file,
  });
  evidenceState.uploading = false;
  $('evidence-choose').disabled = false;
  $('evidence-file').value = '';
  if (!response.ok || !json.ok) return setEvidenceUploadState(json.error || 'PDF 添加失败', true);
  setEvidenceUploadState(json.reused ? '这份 PDF 已经添加过，没有创建重复资料。' : `已添加：${evidenceStatusLabel(json.source)}。`);
  await loadEvidenceSources();
}

async function confirmEvidenceFullText(evidenceId) {
  const source = evidenceState.sources.find((item) => item.id === evidenceId);
  if (!source || !window.confirm(`确认“${source.source?.filename || '这份 PDF'}”是你认可的全文文件？\n\n这只确认文件身份；文本提取质量仍由独立指标表示。`)) return;
  const { response, json } = await apiJson(`/api/evidence-sources/${encodeURIComponent(evidenceId)}/confirm-full-text`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, confirmed: true, actor: 'June' }),
  });
  if (!response.ok || !json.ok) return toast(json.error || '全文确认失败', true);
  evidenceState.sources = evidenceState.sources.map((item) => item.id === evidenceId ? json.source : item);
  renderEvidenceSources();
}

async function generateEvidenceSummary(evidenceId) {
  const source = evidenceState.sources.find((item) => item.id === evidenceId);
  if (!source) return;
  const tool = $('evidence-summary-tool').value;
  const existing = (source.summaries || []).filter((item) => item.status === 'ready' && item.tool === tool).at(-1);
  if (existing) {
    toast(`${tool.toUpperCase()} 摘要已显示在资料卡中；同一来源会复用已有记录。`);
    return;
  }
  if (!await requireRuntimeTool(tool, 'structured_review')) return;
  const confirmed = window.confirm(
    `确认用 ${tool.toUpperCase()} 生成这份 PDF 的 3–6 句摘要？\n\n将发送：本地提取的逐页 PDF 文本与页码。\n不会发送：原始 PDF 二进制、其他未勾选资料或 Markdown 正文。`,
  );
  if (!confirmed) return;
  setEvidenceUploadState(`正在把这份 PDF 的提取文本交给 ${tool.toUpperCase()}；不会改动正文或批注。`);
  const { response, json } = await apiJson(`/api/evidence-sources/${encodeURIComponent(evidenceId)}/summary`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path: DOC_PATH, tool, confirmed_data_transfer: true, actor: 'June',
    }),
  });
  if (!response.ok || !json.ok) return setEvidenceUploadState(userFacingApiError(json, 'PDF 摘要生成失败'), true);
  evidenceState.sources = evidenceState.sources.map((item) => item.id === evidenceId ? json.source : item);
  setEvidenceUploadState(json.reused ? '已复用同一来源与 provider 的摘要。' : '摘要已记录；原 PDF 和页码级文本仍保留在本地 EvidenceSource。');
  renderEvidenceSources();
}

function normalizeHostConversationSession(raw) {
  return {
    ...normalizeConversationSession(raw),
    evidenceSources: Array.isArray(raw?.evidence_sources) ? raw.evidence_sources : [],
  };
}

function runtimeTool(tool) {
  return runtimeCapabilities?.tools?.find((item) => item.id === tool) || null;
}

function runtimeToolReady(tool, capability = '') {
  const item = runtimeTool(tool);
  return Boolean(item?.ready && (!capability || item.capabilities?.[capability] !== false));
}

function runtimeToolState(item) {
  if (item?.ready) return { className: 'ready', label: '已登录，可调用', tag: 'READY' };
  if (item?.auth_state === 'not_authenticated') return { className: 'needs-login', label: '需要登录', tag: 'SIGN IN' };
  if (item?.auth_state === 'check_failed') return { className: 'check-failed', label: '状态检测失败', tag: 'CHECK' };
  return { className: 'missing', label: '未找到命令', tag: 'MISSING' };
}

function renderRuntimePopover(loadError = false) {
  const root = $('cli-popover-list');
  if (loadError || !runtimeCapabilities) {
    root.innerHTML = '<p>本地 Gateway 未能返回 CLI 状态；请重新检测。</p>';
    return;
  }
  root.innerHTML = runtimeCapabilities.tools.map((item) => {
    const state = runtimeToolState(item);
    return `<div class="cli-tool-row ${state.className}"><i aria-hidden="true"></i><span><strong>${esc(item.label || item.id)}</strong><small>${esc(item.detail || state.label)}</small></span><b>${state.tag}</b></div>`;
  }).join('');
}

function syncRuntimeControls() {
  const reviewInputs = [...document.querySelectorAll('input[name="review-tool"]')];
  const readyReview = reviewInputs.find((input) => runtimeToolReady(input.value, 'structured_review'));
  const selectedReview = reviewInputs.find((input) => input.checked);
  if (readyReview && !runtimeToolReady(selectedReview?.value, 'structured_review') && !reviewState.running) readyReview.checked = true;
  reviewInputs.forEach((input) => {
    input.disabled = reviewState.running || !runtimeToolReady(input.value, 'structured_review');
    input.closest('label')?.classList.toggle('is-unavailable', !runtimeToolReady(input.value, 'structured_review'));
  });

  if (conversationState.active) syncConversationTool(conversationState.active.tool, true);
  else syncConversationTool(selectedConversationTool(), false);

  $('review-start').disabled = reviewState.running || !runtimeToolReady(selectedReviewTool(), 'structured_review');
  $('review-send').disabled = reviewState.running || Boolean(reviewState.active && !runtimeToolReady(reviewState.active.tool, 'structured_review'));
  const runAwaitingWriteback = reviewState.activeRun?.status === 'preview';
  $('review-writeback').disabled = reviewState.running
    || (Boolean(reviewState.activeRun) && (!runAwaitingWriteback || reviewState.acceptedOperationIds.size === 0));
  $('review-accept-all').disabled = reviewState.running || !runAwaitingWriteback;
  const summaryTool = $('overview-tool');
  if (summaryTool) {
    [...summaryTool.options].forEach((option) => {
      option.disabled = !runtimeToolReady(option.value, 'structured_review');
    });
    if (!runtimeToolReady(summaryTool.value, 'structured_review')) {
      const readyOption = [...summaryTool.options].find((option) => !option.disabled);
      if (readyOption) summaryTool.value = readyOption.value;
    }
    const summaryReady = runtimeToolReady(summaryTool.value, 'structured_review');
    $('overview-generate').disabled = overviewState.loading || !summaryReady;
    $('overview-regenerate').disabled = overviewState.loading || !summaryReady;
  }
  const conversationTool = conversationState.active?.tool || selectedConversationTool();
  const noteOnly = conversationState.composerMode === 'note';
  $('conversation-send').disabled = conversationState.running || (!noteOnly && !runtimeToolReady(conversationTool, 'conversation'));
  $('conversation-writeback-confirm').disabled = conversationState.running;
}

async function loadRuntimeCapabilities() {
  if (runtimeLoading) return runtimeLoading;
  const badge = $('cli-status');
  badge.className = 'cli-status checking';
  badge.querySelector('span').textContent = 'AI · 检测中';
  runtimeLoading = (async () => {
    try {
      const { response, json } = await apiJson('/api/runtime/capabilities', { cache: 'no-store' });
      if (!response.ok || !json.ok || !Array.isArray(json.tools)) throw new Error(json.error || `HTTP ${response.status}`);
      runtimeCapabilities = json;
      const readyCount = json.tools.filter((item) => item.ready).length;
      badge.className = `cli-status ${readyCount === json.tools.length ? 'ready' : readyCount ? 'partial' : 'offline'}`;
      badge.querySelector('span').textContent = `AI · ${readyCount} 可用`;
      badge.title = readyCount ? `${readyCount} 个 AI provider 已就绪` : CLI_UNAVAILABLE_GUIDE;
      renderRuntimePopover(false);
      syncRuntimeControls();
      return json;
    } catch (error) {
      runtimeCapabilities = null;
      badge.className = 'cli-status offline';
      badge.querySelector('span').textContent = 'AI · 未连接';
      badge.title = error.message || 'AI provider 状态检测失败';
      renderRuntimePopover(true);
      syncRuntimeControls();
      return null;
    } finally {
      runtimeLoading = null;
    }
  })();
  return runtimeLoading;
}

function openRuntimePopover() {
  $('cli-popover').hidden = false;
  $('cli-status').setAttribute('aria-expanded', 'true');
}

function closeRuntimePopover() {
  $('cli-popover').hidden = true;
  $('cli-status').setAttribute('aria-expanded', 'false');
}

async function requireRuntimeTool(tool, capability) {
  if (!runtimeCapabilities) await loadRuntimeCapabilities();
  if (runtimeToolReady(tool, capability)) return true;
  openRuntimePopover();
  toast(CLI_UNAVAILABLE_GUIDE, true, 5200);
  return false;
}

const adapter = new HttpDocumentAdapter({
  documentUrl: `/api/doc?path=${encodeURIComponent(DOC_PATH)}`,
  commentsUrl: `/api/comments?path=${encodeURIComponent(DOC_PATH)}`,
  commentsBatchUrl: `/api/comments/batch?path=${encodeURIComponent(DOC_PATH)}`,
  assetUrl: `/api/asset?doc=${encodeURIComponent(DOC_PATH)}`,
});

editor.adapter = adapter;
editor.selectionActions = [
  { id: 'quick-explain', label: '快速解释', title: '临时解释，不保存到讨论记录' },
  { id: 'discuss', label: '选区讨论', title: '围绕这段原文开始可分支的审阅对话' },
];

function configureEditorActions() {
  editor.toolbarActions = [
    { id: 'article-overview', label: '文章总览', slot: 'primary', appliesTo: 'document.load' },
    { id: 'ai-review', label: 'AI Review', slot: 'primary', appliesTo: { capability: 'document.load', requiresCleanDocument: true }, loading: reviewState.running },
    { id: 'import-manuscript', label: '导入', title: '从 Word 或 Markdown 创建新的评审主稿', slot: 'primary', appliesTo: 'document.load' },
    { id: 'evidence', label: '参考资料', title: '管理当前主稿的上下文资料', slot: 'primary', appliesTo: 'document.load' },
    { id: 'comments', label: '批注', slot: 'primary', appliesTo: 'comments.list', count: 'comments' },
    { id: 'overall-comment', label: '全文批注', slot: 'overflow', appliesTo: 'comments.create' },
    { id: 'source-edit', label: '源码编辑', slot: 'overflow', appliesTo: { capability: 'document.save', requiresWritable: true } },
    { id: 'accept-provisional', label: '接受全部暂定', slot: 'overflow', appliesTo: 'comments.update' },
    { id: 'show-withdrawn', label: editor.showWithdrawnComments ? '隐藏已撤回' : '显示已撤回', slot: 'overflow', appliesTo: 'comments.list' },
  ];
  editor.commentActions = [
    { id: 'reply', label: '回复', appliesTo: { capability: 'reply', target: 'comment', lifecycleStates: ['active'] } },
    { id: 'accept-finding', label: '确认接受', appliesTo: { capability: 'update', target: 'comment', lifecycleStates: ['active'], findingStates: ['provisional'] } },
    { id: 'edit', label: '编辑', appliesTo: { capability: 'update', target: 'comment', lifecycleStates: ['active'] } },
    { id: 'withdraw', label: '撤回', appliesTo: { capability: 'delete', target: 'comment', lifecycleStates: ['active'] } },
    { id: 'restore', label: '恢复', appliesTo: { capability: 'restore', target: 'comment', lifecycleStates: ['withdrawn'] } },
    { id: 'history', label: '查看修改记录', appliesTo: { capability: 'history', target: 'comment' } },
    { id: 'locate', label: '定位原文', appliesTo: { capability: 'list', target: 'comment', kinds: ['anchored'] } },
    { id: 'reply-edit', label: '编辑回复', appliesTo: { capability: 'reply', target: 'reply', states: ['active'] } },
    { id: 'reply-withdraw', label: '撤回回复', appliesTo: { capability: 'reply', target: 'reply', states: ['active'] } },
  ];
}

configureEditorActions();

const HEADER_PRIMARY_ACTION_IDS = ['article-overview', 'ai-review', 'import-manuscript', 'evidence', 'comments'];

function visibleHeaderPrimaryIds() {
  const width = window.innerWidth || 1440;
  if (width >= 980) return HEADER_PRIMARY_ACTION_IDS;
  if (width >= 760) return ['ai-review', 'comments'];
  return ['ai-review'];
}

function stateAction(actionId) {
  return editorActionState?.toolbar?.actions?.find((action) => action.id === actionId) || null;
}

function actionButton(action, className = '') {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.dataset.hostToolbarAction = action.id;
  if (action.id === 'import-manuscript') button.id = 'btn-import';
  if (action.id === 'evidence') button.id = 'btn-evidence';
  button.disabled = !action.enabled || action.loading;
  if (action.title) button.title = action.title;
  button.append(document.createTextNode(action.loading ? `${action.label}…` : action.label));
  if (Number.isFinite(action.count)) {
    const badge = document.createElement('span');
    badge.className = 'doc-action-count';
    badge.textContent = String(action.count);
    button.append(' ', badge);
  }
  return button;
}

function renderHostToolbar() {
  if (!editorActionState) return;
  const visibleIds = visibleHeaderPrimaryIds();
  const primary = HEADER_PRIMARY_ACTION_IDS
    .map(stateAction)
    .filter((action) => action && visibleIds.includes(action.id));
  const foldedPrimary = HEADER_PRIMARY_ACTION_IDS
    .map(stateAction)
    .filter((action) => action && !visibleIds.includes(action.id));
  $('doc-primary-actions').replaceChildren(...primary.map((action) => actionButton(action)));
  const editorOverflow = [
    ...foldedPrimary,
    ...(editorActionState.toolbar?.overflow || []),
  ];
  $('doc-more-editor-actions').replaceChildren(...editorOverflow.map((action) => actionButton(action)));
}

function closeAiToolsPopover() {
  const popover = $('ai-tools-popover');
  if (popover) popover.hidden = true;
}

function openAiToolsPopover() {
  const popover = $('ai-tools-popover');
  if (popover && popover.querySelector('button')) popover.hidden = false;
}

function toggleAiToolsPopover() {
  $('ai-tools-popover').hidden ? openAiToolsPopover() : closeAiToolsPopover();
}

function selectedSourceQuote() {
  return editor.selectionState || null;
}

function quickExplainFromToolbar() {
  const sourceQuote = selectedSourceQuote();
  if (!sourceQuote?.quoteText) return toast('请先在正文中选择一段原文，再运行快速解释。', true);
  closeAiToolsPopover();
  return quickExplain(sourceQuote);
}

function discussSelectionFromToolbar() {
  const sourceQuote = selectedSourceQuote();
  if (!sourceQuote?.quoteText) return toast('请先在正文中选择一段原文，再开始选区讨论。', true);
  closeAiToolsPopover();
  return openConversationForQuote(sourceQuote);
}

function formatDocumentTime(value) {
  if (!value) return '未记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function renderDocumentMenu() {
  const root = $('doc-file-list');
  if (!root) return;
  if (documentMenuState.loading) {
    root.innerHTML = '<p>正在读取主稿…</p>';
    return;
  }
  if (!documentMenuState.documents.length) {
    root.innerHTML = '<p>没有找到可切换的 Markdown 主稿。</p>';
    return;
  }
  root.innerHTML = documentMenuState.documents.map((doc) => `
    <button class="doc-file-item ${doc.current ? 'current' : ''}" type="button" data-doc-path="${esc(doc.path)}" ${doc.current ? 'aria-current="page"' : ''}>
      <span class="doc-file-check" aria-hidden="true">${doc.current ? '✓' : ''}</span>
      <span class="doc-file-title">${esc(doc.display_name || doc.path)}</span>
      <span class="doc-file-stats">${Number(doc.version_count || 0)} 版 · ${Number(doc.comment_count || 0)} 批注 · ${esc(formatDocumentTime(doc.last_opened_or_modified_at))}</span>
      <span class="doc-file-path">${esc(doc.path)}</span>
    </button>
  `).join('');
}

async function loadDocumentMenu() {
  if (documentMenuState.loading) return;
  documentMenuState.loading = true;
  renderDocumentMenu();
  const params = new URLSearchParams({ path: DOC_PATH });
  const { response, json } = await apiJson(`/api/documents?${params}`, { cache: 'no-store' });
  documentMenuState.loading = false;
  if (!response.ok || !json.ok) {
    $('doc-file-list').innerHTML = `<p>${esc(json.error || '主稿列表读取失败')}</p>`;
    return;
  }
  documentMenuState.documents = Array.isArray(json.documents) ? json.documents : [];
  renderDocumentMenu();
}

async function switchDocument(path) {
  if (!path || path === DOC_PATH) {
    $('doc-file-menu').open = false;
    return;
  }
  try {
    await editor.save();
  } catch (error) {
    return toast(error.message || '切换前保存失败；请先处理当前文稿状态。', true, 5200);
  }
  const next = new URL(location.href);
  next.searchParams.set('doc', path);
  location.assign(next.toString());
}

function consumePendingDocumentToast() {
  const message = sessionStorage.getItem(DOCUMENT_SWITCH_TOAST_KEY);
  if (!message) return;
  sessionStorage.removeItem(DOCUMENT_SWITCH_TOAST_KEY);
  toast(message, false, 8200);
}

function syncDocumentMeta(documentState) {
  const body = String(documentState?.body || '');
  $('doc-name').textContent = documentState?.title || DOC_PATH;
  $('doc-meta').textContent = `${body.split('\n').length} 行 · rev ${String(documentState?.rev || '').slice(0, 16)}`;
}

function syncDocumentMetaFromActionState(state) {
  if (!state?.document) return;
  editorActionState = state;
  const saveLabel = state.status?.kind === 'saving'
    ? '保存中'
    : state.document.dirty ? '未保存' : state.status?.kind === 'error' ? '需处理' : '已保存';
  $('doc-name').textContent = state.document.title || DOC_PATH;
  $('doc-meta').textContent = `${state.document.lineCount} 行 · ${saveLabel} · rev ${state.document.shortRev || '—'}`;
  renderHostToolbar();
}

editor.subscribeActionState(syncDocumentMetaFromActionState);

function summaryListHtml(rows, empty = '未提供') {
  const values = Array.isArray(rows) ? rows.filter(Boolean) : [];
  return values.length ? values.map((item) => `<li>${esc(item)}</li>`).join('') : `<li>${esc(empty)}</li>`;
}

function renderDocumentSummary(summary) {
  overviewState.summary = summary || null;
  const state = $('overview-state');
  const content = $('overview-content');
  const title = $('overview-state-title');
  const copy = $('overview-state-copy');
  const generate = $('overview-generate');
  if (!summary) {
    state.hidden = false;
    content.hidden = true;
    title.textContent = '此版本尚无结构化总览';
    copy.textContent = '点击后将完整阅读当前 Markdown，生成 3–6 句速览、核心论点、证据范围、主要结论、限制与待核查来源。不会改动正文或批注。';
    generate.textContent = '生成此版本总览';
    syncRuntimeControls();
    return;
  }
  const stale = summary.status === 'stale';
  const failed = summary.status === 'failed';
  state.hidden = !(stale || failed);
  content.hidden = failed;
  if (stale) {
    title.textContent = '此总览已过期';
    copy.textContent = '下方内容绑定旧 revision，仅供回看；必须显式生成为当前版本，不能视为当前稿件总览。';
    generate.textContent = '生成当前版本总览';
  } else if (failed) {
    title.textContent = '此版本的总览生成失败';
    copy.textContent = '失败记录已进入 summary 台账；可在 CLI 就绪后显式重试。';
    generate.textContent = '重新生成此版本';
  }
  if (!failed) {
    $('overview-status').textContent = stale ? 'STALE · 已过期' : 'READY · 当前版本';
    $('overview-status').classList.toggle('stale', stale);
    $('overview-created-at').textContent = summary.created_at || '';
    $('overview-summary-list').innerHTML = summaryListHtml(summary.summary_3_6);
    $('overview-thesis').textContent = summary.thesis || '未提供';
    $('overview-evidence-scope').innerHTML = summaryListHtml(summary.evidence_scope);
    $('overview-conclusions').innerHTML = summaryListHtml(summary.major_conclusions);
    $('overview-limitations').innerHTML = summaryListHtml(summary.limitations);
    $('overview-source-targets').innerHTML = summaryListHtml(summary.source_check_targets, '未列出');
    $('overview-regenerate').textContent = stale ? '生成当前版本总览' : '重新生成当前版本';
  }
  syncRuntimeControls();
}

function renderOverviewReviewThreads() {
  const section = $('overview-muted-review');
  const root = $('overview-muted-list');
  if (!section || !root) return;
  const comments = arrayField(editor._comments).filter((comment) => (
    reviewWorkflowState(comment) === 'muted_by_user'
  ));
  section.hidden = comments.length === 0;
  root.innerHTML = comments.map((comment) => `
    <article class="overview-review-item" data-comment-id="${esc(comment.id || '')}">
      <header>${reviewBadgeHtml(comment)}<strong>${esc(comment.finding_id || comment.findingId || comment.id || 'AI 建议')}</strong></header>
      <p>${esc((comment.content || '').slice(0, 220))}</p>
      <button type="button" data-lineage-restore="${esc(comment.id || '')}">恢复提示</button>
    </article>`).join('');
}

async function loadDocumentSummary() {
  const { response, json } = await apiJson(`/api/document-summary?path=${encodeURIComponent(DOC_PATH)}`, { cache: 'no-store' });
  if (!response.ok || !json.ok) {
    $('overview-state').hidden = false;
    $('overview-content').hidden = true;
    $('overview-state-title').textContent = '总览台账读取失败';
    $('overview-state-copy').textContent = json.error || `HTTP ${response.status}`;
    return;
  }
  overviewState.currentRev = json.current_rev || editor.documentState.rev || '';
  renderDocumentSummary(json.summary || null);
  renderOverviewReviewThreads();
}

async function generateDocumentSummary(regenerate = false) {
  if (overviewState.loading) return;
  const tool = $('overview-tool').value || DEFAULT_AI_TOOL;
  if (!await requireRuntimeTool(tool, 'structured_review')) return;
  overviewState.loading = true;
  $('overview-state').hidden = false;
  $('overview-state-title').textContent = '正在生成当前版本总览';
  $('overview-state-copy').textContent = '完整 Markdown 正在通过既有本机 CLI 链路读取；不会修改正文或批注。';
  syncRuntimeControls();
  const { response, json } = await apiJson('/api/document-summary', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path: DOC_PATH,
      base_rev: editor.documentState.rev,
      tool,
      regenerate,
    }),
  });
  overviewState.loading = false;
  if (!response.ok || !json.ok) {
    if (response.status === 409) await editor.load();
    await loadDocumentSummary();
    toast(userFacingApiError(json, '文章总览生成失败'), true);
    return;
  }
  overviewState.currentRev = json.current_rev || editor.documentState.rev;
  renderDocumentSummary(json.summary);
}

async function openOverview() {
  const documentState = editor.documentState;
  const body = String(documentState?.body || '');
  $('overview-doc-name').textContent = documentState?.title || DOC_PATH;
  $('overview-rev').textContent = String(documentState?.rev || '—');
  $('overview-stats').textContent = `${body ? body.split('\n').length : 0} 行 · ${body.length.toLocaleString('zh-CN')} 字符`;
  $('overview-drawer').classList.add('open');
  $('overview-drawer').setAttribute('aria-hidden', 'false');
  $('overview-scrim').hidden = false;
  $('overview-state').hidden = false;
  $('overview-content').hidden = true;
  $('overview-state-title').textContent = '正在核对此版本的结构化总览';
  $('overview-state-copy').textContent = '这里只读取本地 summary 台账，不会自动调用 CLI。';
  renderOverviewReviewThreads();
  await loadDocumentSummary();
}

function closeOverview() {
  $('overview-drawer').classList.remove('open');
  $('overview-drawer').setAttribute('aria-hidden', 'true');
  $('overview-scrim').hidden = true;
}

function setReviewCommentTruth(comments) {
  reviewState.commentsById = new Map((comments || []).map((comment) => [comment.id, comment]));
}

async function acceptAllProvisionalComments() {
  const provisional = [...reviewState.commentsById.values()].filter((comment) => (
    comment.lifecycleState === 'active' && comment.findingState === 'provisional'
  ));
  if (!provisional.length) return toast('当前没有可接受的 provisional 批注。');
  if (!window.confirm(`确认接受全部 ${provisional.length} 条 AI 暂定批注？此动作会逐条写入 finding-update 审计事件。`)) return;
  const { response, json } = await apiJson('/api/comments/accept-provisional', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, comments_rev: editor.commentsRev, actor: 'June' }),
  });
  if (!response.ok || !json.ok) {
    await refreshEditorComments();
    return toast(json.message || json.error || '批量接受失败', true);
  }
  await refreshEditorComments();
  toast(`已确认接受 ${json.accepted_comment_ids?.length || 0} 条暂定批注。`);
}

editor.addEventListener('comma-ready', (event) => {
  syncDocumentMeta(event.detail.document);
  setReviewCommentTruth(event.detail.comments || []);
});
editor.addEventListener('comma-save', (event) => {
  syncDocumentMeta(event.detail.document);
  loadVersions();
  if ($('overview-drawer').classList.contains('open')) loadDocumentSummary();
});
editor.addEventListener('comma-conflict', async (event) => {
  const draft = event.detail?.error?.draft;
  toast(draft ? '磁盘版本已变化；刚才的修改已保留为冲突草稿。' : '磁盘版本已变化，已重新载入最新内容。', true);
  openArchive('versions');
  await loadVersions();
});
editor.addEventListener('comma-error', (event) => toast(event.detail?.error?.message || '编辑器操作失败', true));
editor.addEventListener('comma-ai-request', (event) => {
  if (event.detail?.mode === 'comment-batch') {
    startReview();
  }
});
editor.addEventListener('comma-selection-action', (event) => {
  const sourceQuote = {
    quoteText: event.detail?.quoteText || '',
    sourceLocator: event.detail?.sourceLocator || null,
    section: event.detail?.section || '',
  };
  if (event.detail?.actionId === 'quick-explain') quickExplain(sourceQuote);
  if (event.detail?.actionId === 'discuss') openConversationForQuote(sourceQuote);
});

function runEditorToolbarAction(action) {
  if (action === 'article-overview') openOverview();
  if (action === 'ai-review') editor.requestAiReview();
  if (action === 'import-manuscript') openImportDialog();
  if (action === 'evidence') openEvidenceDrawer();
  if (action === 'ai-tools') return;
  if (action === 'overall-comment') editor.openOverallCommentComposer();
  if (action === 'comments') editor.toggleComments();
  if (action === 'source-edit') editor.openSourceEditor();
  if (action === 'accept-provisional') acceptAllProvisionalComments();
  if (action === 'show-withdrawn') {
    editor.showWithdrawnComments = !editor.showWithdrawnComments;
    configureEditorActions();
  }
}

editor.addEventListener('comma-toolbar-action', (event) => {
  runEditorToolbarAction(event.detail?.actionId);
});

editor.addEventListener('comma-comment-action', async (event) => {
  const detail = event.detail || {};
  const comment = detail.comment;
  try {
    if (detail.phase === 'activate') {
      if (detail.actionId === 'edit') {
        editor.openCommentAction(detail.commentId, {
          actionId: 'edit', label: '编辑批注', submitLabel: '保存修改', initialValue: comment.content,
        });
      }
      if (detail.actionId === 'reply') {
        editor.openCommentAction(detail.commentId, {
          actionId: 'reply', label: '回复批注', submitLabel: '添加回复', initialValue: '',
          placeholder: '围绕这条批注继续讨论',
        });
      }
      if (detail.actionId === 'reply-edit') {
        editor.openCommentAction(detail.commentId, {
          actionId: 'reply-edit', replyId: detail.replyId, label: '编辑回复',
          submitLabel: '保存回复', initialValue: detail.reply?.content || '',
        });
      }
      if (detail.actionId === 'withdraw') {
        if (!window.confirm('撤回后默认列表与计数将隐藏这条批注，但记录会保留。继续吗？')) return;
        await adapter.deleteComment(detail.commentId, {
          baseCommentVersion: detail.baseCommentVersion, actor: 'June', reason: 'user-withdrawn',
        });
        await refreshEditorComments();
      }
      if (detail.actionId === 'restore') {
        await adapter.restoreComment(detail.commentId, {
          baseCommentVersion: detail.baseCommentVersion, actor: 'June',
        });
        await refreshEditorComments();
      }
      if (detail.actionId === 'accept-finding') {
        const { response, json } = await apiJson(`/api/comments/${encodeURIComponent(detail.commentId)}/accept`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            path: DOC_PATH,
            base_comment_version: detail.baseCommentVersion,
            actor: 'June',
          }),
        });
        if (!response.ok || !json.ok) {
          await refreshEditorComments();
          return toast(json.message || json.error || '确认接受失败', true);
        }
        await refreshEditorComments();
        toast('该 finding 已由人工确认接受。');
      }
      if (detail.actionId === 'reply-withdraw') {
        if (!window.confirm('撤回这条回复？审计记录会保留。')) return;
        await adapter.deleteCommentReply(detail.commentId, detail.replyId, {
          baseCommentVersion: detail.baseCommentVersion, actor: 'June',
        });
        await refreshEditorComments();
      }
      if (detail.actionId === 'history') {
        const events = await adapter.listCommentEvents(detail.commentId);
        editor.showCommentDetails(detail.commentId, { label: '修改记录', items: events });
      }
      if (detail.actionId === 'locate') editor.jumpToComment(detail.commentId);
      return;
    }
    if (detail.phase === 'submit' && detail.actionId === 'edit') {
      await adapter.updateComment(detail.commentId, {
        baseCommentVersion: detail.baseCommentVersion, actor: 'June', content: detail.content,
      });
      await refreshEditorComments();
    }
    if (detail.phase === 'submit' && detail.actionId === 'reply') {
      await adapter.createCommentReply(detail.commentId, {
        baseCommentVersion: detail.baseCommentVersion, actor: 'June', content: detail.content,
      });
      await refreshEditorComments();
    }
    if (detail.phase === 'submit' && detail.actionId === 'reply-edit') {
      await adapter.updateCommentReply(detail.commentId, detail.replyId, {
        baseCommentVersion: detail.baseCommentVersion, actor: 'June', content: detail.content,
      });
      await refreshEditorComments();
    }
  } catch (error) {
    if (error?.code === 'COMMENT_VERSION_CONFLICT') {
      await refreshEditorComments();
      toast('这条批注已在别处更新；已载入当前版本，请重新操作。', true);
    } else {
      toast(error.message || '批注操作失败', true);
    }
  }
});

const REVIEW_STATUS = {
  queued: '排队中', running: '评审中', cancelling: '取消中',
  ready: '操作预览', preview: '操作预览', completed: '已完成',
  cancelled: '已取消', needs_attention: '部分需确认', needs_rebase: '原文已变化', failed: '运行失败',
};

function openReviewDrawer() {
  $('review-drawer').classList.add('open');
  $('review-drawer').setAttribute('aria-hidden', 'false');
  $('review-scrim').hidden = false;
}

function closeReviewDrawer() {
  $('review-drawer').classList.remove('open');
  $('review-drawer').setAttribute('aria-hidden', 'true');
  $('review-scrim').hidden = true;
}

function activateReviewSession(rawSession, rawRun = null) {
  const previousRunId = reviewState.activeRun?.id || '';
  const nextRun = rawRun || rawSession?.run || null;
  reviewState.active = rawSession ? normalizeReviewSession(rawSession) : null;
  reviewState.activeRun = nextRun;
  if (!nextRun || nextRun.id !== previousRunId || nextRun.status === 'completed') {
    reviewState.acceptedOperationIds = new Set(nextRun?.accepted_operation_ids || []);
  }
}

function reviewRunActive(run) {
  return ['queued', 'running', 'cancelling'].includes(run?.status || '');
}

function openReviewPreflight() {
  $('review-preflight-modal').hidden = false;
  $('review-preflight-modal').setAttribute('aria-hidden', 'false');
  $('review-preflight-scrim').hidden = false;
}

function closeReviewPreflight() {
  $('review-preflight-modal').hidden = true;
  $('review-preflight-modal').setAttribute('aria-hidden', 'true');
  $('review-preflight-scrim').hidden = true;
}

const PREFLIGHT_ROUTE = {
  initial: { code: 'FIRST PASS', title: '当前稿件尚无完成评审', scope: '首次完整阅读；可靠 finding 将以 provisional 写入批注' },
  'view-latest': { code: 'NO DELTA', title: '正文与批注均未变化', scope: '默认查看最近评审；不会调用本机 CLI' },
  incremental: { code: 'LOCAL DELTA', title: '变化限定在低风险局部范围', scope: '建议只复审变更块、局部上下文与受影响批注' },
  full: { code: 'GLOBAL RISK', title: '变化命中保护章节', scope: '摘要、方法、结果、结论、引用或图表变化默认全文复审' },
};

function renderReviewPreflight(preflight) {
  reviewState.preflight = preflight;
  const documentDelta = preflight.document || {};
  const commentDelta = preflight.comments || {};
  const anchors = preflight.anchors || {};
  const route = { ...(PREFLIGHT_ROUTE[preflight.recommended_mode] || PREFLIGHT_ROUTE.full) };
  const comparisonIncomplete = (documentDelta.change_state === 'changed' && !documentDelta.baseline_body_available)
    || commentDelta.comparison_state === 'unknown';
  if (preflight.recommended_mode === 'full' && comparisonIncomplete) {
    route.title = '历史基线不足以安全缩小范围';
    route.scope = '缺少可核对的正文或批注基线快照，保守推荐全文复审';
  }
  const counts = ['added', 'edited', 'withdrawn', 'restored', 'replied']
    .map((key) => [key, Array.isArray(commentDelta[key]) ? commentDelta[key].length : 0]);
  const commentCount = counts.reduce((sum, row) => sum + row[1], 0);
  const sectionNames = (documentDelta.affected_sections || []).filter(Boolean);
  const missing = (anchors.missing || []).length;
  const ambiguous = (anchors.ambiguous || []).length;
  $('review-preflight-route-code').textContent = route.code;
  $('review-preflight-route').textContent = route.title;
  $('review-preflight-scope').textContent = route.scope;
  $('review-preflight-document').textContent = documentDelta.change_state === 'no-baseline'
    ? '无基线' : documentDelta.change_state === 'unchanged' ? '未变化' : `${(documentDelta.changed_blocks || []).length} 个块`;
  $('review-preflight-sections').textContent = sectionNames.length
    ? `影响章节：${sectionNames.join('、')}`
    : documentDelta.change_state === 'changed' && !documentDelta.baseline_body_available
      ? '基线正文快照不可用，无法安全缩小范围。'
      : '未检测到正文块级变化。';
  $('review-preflight-comments').textContent = commentCount ? `${commentCount} 项变化` : '未变化';
  $('review-preflight-comment-detail').textContent = [
    `新增 ${counts[0][1]}`, `人工编辑 ${counts[1][1]}`, `撤回 ${counts[2][1]}`,
    `恢复 ${counts[3][1]}`, `回复 ${counts[4][1]}`,
  ].join(' · ');
  $('review-preflight-anchors').textContent = missing || ambiguous ? `${missing + ambiguous} 项需处理` : `${Number(anchors.ready || 0)} 项可靠`;
  $('review-preflight-anchor-detail').textContent = `ready ${Number(anchors.ready || 0)} · missing ${missing} · ambiguous ${ambiguous}`;
  $('review-preflight-baseline').textContent = preflight.baseline_session
    ? `${preflight.baseline_session.id} · ${preflight.baseline_session.completed_at || '完成时间未知'}`
    : '无已完成评审；将建立首个 session';
  const protectedNames = documentDelta.protected_sections || [];
  $('review-preflight-reason').textContent = protectedNames.length
    ? `保护类别命中：${protectedNames.join('、')}。增量复审仍可手动选择，但属于明确降级。`
    : comparisonIncomplete
      ? '历史 session 缺少完整的 revision 快照；未把未知状态误报为“无变化”，因此保守路由到全文复审。'
      : preflight.recommended_mode === 'incremental'
      ? '变化仅限非保护章节或批注层；changed_blocks 只用于路由，不声称已判断语义影响。'
      : preflight.recommended_mode === 'view-latest'
        ? 'document rev 与 comments_rev 均等于基线；默认动作不会产生模型调用。'
        : '首次评审读取当前完整 Markdown；写入项保持 provisional，不能显示为已接受。';

  const primary = $('review-preflight-primary');
  const view = $('review-preflight-view');
  const incremental = $('review-preflight-incremental');
  const force = $('review-preflight-force');
  primary.disabled = false;
  view.hidden = !preflight.baseline_session || preflight.recommended_mode === 'view-latest';
  incremental.hidden = preflight.recommended_mode !== 'full';
  force.hidden = !preflight.baseline_session || preflight.recommended_mode === 'full';
  if (preflight.recommended_mode === 'initial') {
    primary.dataset.mode = 'initial'; primary.textContent = '开始首次评审';
  } else if (preflight.recommended_mode === 'view-latest') {
    primary.dataset.mode = 'view-latest'; primary.textContent = '查看最近评审';
  } else if (preflight.recommended_mode === 'incremental') {
    primary.dataset.mode = 'incremental'; primary.textContent = '增量复审';
  } else {
    primary.dataset.mode = 'forced-full'; primary.textContent = '全文复审';
  }
}

async function viewLatestReview() {
  const id = reviewState.preflight?.baseline_session?.id;
  if (!id) return;
  closeReviewPreflight();
  openReviewDrawer();
  await loadReviewSession(id);
}

const VERSION_KIND = {
  baseline: '初始版本', auto: '自动保存', checkpoint: '命名版本',
  restore: '历史恢复', recovery: '草稿恢复', external: '外部变更',
};

function formatArchiveTime(value) {
  const text = String(value || '');
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? text.replace('T', ' ') : date.toLocaleString('zh-CN', { hour12: false });
}

function setArchiveTab(tab) {
  const selected = tab === 'exports' ? 'exports' : 'versions';
  $('archive-tab-versions').classList.toggle('active', selected === 'versions');
  $('archive-tab-exports').classList.toggle('active', selected === 'exports');
  $('archive-versions').hidden = selected !== 'versions';
  $('archive-exports').hidden = selected !== 'exports';
  if (selected === 'exports') loadExportCapabilities();
}

function openArchive(tab = 'versions') {
  closeRuntimePopover();
  setArchiveTab(tab);
  $('archive-drawer').classList.add('open');
  $('archive-drawer').setAttribute('aria-hidden', 'false');
  $('archive-scrim').hidden = false;
  if (tab === 'versions') loadVersions();
}

function closeArchive() {
  $('archive-drawer').classList.remove('open');
  $('archive-drawer').setAttribute('aria-hidden', 'true');
  $('archive-scrim').hidden = true;
}

function renderDrafts() {
  const root = $('draft-list');
  $('draft-section').hidden = archiveState.drafts.length === 0;
  root.innerHTML = archiveState.drafts.map((draft) => `
    <article class="draft-card" data-draft-id="${esc(draft.id)}">
      <header><strong>${esc(draft.id)}</strong><time>${esc(formatArchiveTime(draft.created_at))}</time></header>
      <p>编辑冲突时保留 · ${Number(draft.line_count || 0)} 行 · ${Number(draft.char_count || 0)} 字符</p>
      <div class="draft-actions">
        <button type="button" data-draft-action="diff">与当前版本比较</button>
        <button class="primary" type="button" data-draft-action="restore">恢复为新版本</button>
        <button type="button" data-draft-action="dismiss">忽略草稿</button>
      </div>
    </article>`).join('');
}

function renderVersions() {
  const root = $('version-list');
  $('archive-current-rev').textContent = archiveState.currentRev || '—';
  $('version-count').textContent = String(archiveState.versions.length);
  renderDrafts();
  if (!archiveState.versions.length) {
    root.innerHTML = '<p class="archive-loading">还没有版本记录。</p>';
    return;
  }
  root.innerHTML = archiveState.versions.map((version) => {
    const current = version.rev === archiveState.currentRev && version === archiveState.versions[0];
    const label = version.label || VERSION_KIND[version.kind] || version.kind || '版本';
    return `<article class="version-card ${esc(version.kind || '')} ${current ? 'current' : ''}" data-version-id="${esc(version.id)}">
      <header><h4>${esc(label)}</h4><time>${esc(formatArchiveTime(version.created_at))}</time></header>
      <div class="version-meta"><span class="version-kind">${esc(VERSION_KIND[version.kind] || version.kind || 'snapshot')}</span><span>rev ${esc(String(version.rev || '').slice(0, 10))}</span><span>${Number(version.line_count || 0)} lines</span><span>${esc(version.actor || '')}</span></div>
      <div class="version-actions">
        <button type="button" data-version-action="diff">与当前比较</button>
        ${current ? '<button type="button" disabled>当前版本</button>' : '<button class="restore" type="button" data-version-action="restore">恢复为新版本</button>'}
      </div>
    </article>`;
  }).join('');
}

async function loadVersions(showError = false) {
  if (archiveState.loading) return;
  archiveState.loading = true;
  try {
    const { response, json } = await apiJson(`/api/versions?path=${encodeURIComponent(DOC_PATH)}`, { cache: 'no-store' });
    if (!response.ok || !json.ok) throw new Error(json.error || '版本读取失败');
    archiveState.versions = Array.isArray(json.versions) ? json.versions : [];
    archiveState.drafts = Array.isArray(json.drafts) ? json.drafts : [];
    archiveState.currentRev = json.current_rev || editor.documentState.rev || '';
    renderVersions();
  } catch (error) {
    if (showError) toast(error.message || '版本读取失败', true);
    $('version-list').innerHTML = '<p class="archive-loading">版本服务暂不可用。</p>';
  } finally {
    archiveState.loading = false;
  }
}

async function createCheckpoint() {
  const label = $('checkpoint-label').value.trim();
  if (!label) return toast('请先填写命名版本的名称。', true);
  const { response, json } = await apiJson('/api/versions/checkpoints', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, label, base_rev: editor.documentState.rev, actor: 'June' }),
  });
  if (!response.ok || !json.ok) return toast(json.message || json.error || '命名版本保存失败', true);
  $('checkpoint-label').value = '';
  toast('命名版本已保存。');
  await loadVersions(true);
}

async function showVersionDiff(versionId) {
  const { response, json } = await apiJson(`/api/versions/diff?path=${encodeURIComponent(DOC_PATH)}&from=${encodeURIComponent(versionId)}&to=current`, { cache: 'no-store' });
  if (!response.ok || !json.ok) return toast(json.error || '版本比较失败', true);
  $('diff-title').textContent = `${json.changed_lines || 0} 行变化 · 与当前版本比较`;
  $('diff-output').textContent = json.diff || '两个版本内容相同。';
  $('version-diff').hidden = false;
  $('version-diff').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function showDraftDiff(draftId) {
  const { response, json } = await apiJson(`/api/drafts/${encodeURIComponent(draftId)}/diff?path=${encodeURIComponent(DOC_PATH)}`, { cache: 'no-store' });
  if (!response.ok || !json.ok) return toast(json.error || '草稿比较失败', true);
  $('diff-title').textContent = `${json.changed_lines || 0} 行变化 · 冲突草稿与当前版本`;
  $('diff-output').textContent = json.diff || '草稿与当前版本内容相同。';
  $('version-diff').hidden = false;
  $('version-diff').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function restoreVersion(versionId) {
  if (!window.confirm('恢复会把该快照写成一个新的当前版本，现有历史不会删除。继续吗？')) return;
  const { response, json } = await apiJson(`/api/versions/${encodeURIComponent(versionId)}/restore`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, base_rev: editor.documentState.rev, actor: 'June' }),
  });
  if (!response.ok || !json.ok) return toast(json.message || json.error || '版本恢复失败', true);
  await editor.load();
  await loadVersions(true);
  toast('历史快照已恢复为新的当前版本。');
}

async function restoreDraft(draftId) {
  if (!window.confirm('将冲突草稿恢复为新的当前版本？当前版本仍会保留在历史中。')) return;
  const { response, json } = await apiJson(`/api/drafts/${encodeURIComponent(draftId)}/restore`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, base_rev: editor.documentState.rev, actor: 'June' }),
  });
  if (!response.ok || !json.ok) return toast(json.message || json.error || '草稿恢复失败', true);
  await editor.load();
  await loadVersions(true);
  toast('冲突草稿已恢复为新的当前版本。');
}

async function dismissDraft(draftId) {
  const { response, json } = await apiJson(`/api/drafts/${encodeURIComponent(draftId)}/dismiss`, {
    method: 'DELETE', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, actor: 'June' }),
  });
  if (!response.ok || !json.ok) return toast(json.error || '草稿处理失败', true);
  await loadVersions(true);
}

async function loadExportCapabilities() {
  const { response, json } = await apiJson('/api/exports/capabilities', { cache: 'no-store' });
  if (!response.ok || !json.ok) return toast(json.error || '导出能力检测失败', true);
  archiveState.exportCapabilities = json;
  ['docx', 'pdf'].forEach((format) => {
    const capability = json.formats?.[format];
    const button = document.querySelector(`[data-export-format="${format}"]`);
    const detail = document.querySelector(`[data-export-detail="${format}"]`);
    button.disabled = !capability?.ready;
    detail.textContent = capability?.ready ? `${capability.engine} 已就绪` : (capability?.detail || '本机转换器未就绪');
  });
}

function downloadExport(format) {
  const capability = archiveState.exportCapabilities?.formats?.[format];
  if (capability && capability.ready === false) return toast(capability.detail || '该导出格式未就绪', true);
  const anchor = document.createElement('a');
  anchor.href = `/api/export?path=${encodeURIComponent(DOC_PATH)}&format=${encodeURIComponent(format)}&version=current`;
  anchor.download = '';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function selectedReviewTool() {
  return document.querySelector('input[name="review-tool"]:checked')?.value || DEFAULT_AI_TOOL;
}

function selectedReviewAgentIdentity() {
  return {
    adapter_id: 'academic-paper-review',
    adapter_version: 'internal-gate3',
    profile_id: 'primary',
    rubric_version: 'sha256:3b247cac76feb8508445cb3b1eaa8d68f4bbb57a8eed74f47e4c512185352a48',
    output_schema_version: 'academic-paper-review-result/v1',
  };
}

function isAcademicPaperReviewRun(run) {
  return run?.adapter_id === 'academic-paper-review';
}

function setReviewRunning(running, message = '', isError = false) {
  reviewState.running = Boolean(running);
  const stateElement = $('review-run-state');
  stateElement.hidden = !message;
  stateElement.textContent = message;
  stateElement.classList.toggle('error', Boolean(isError));
  configureEditorActions();
  syncRuntimeControls();
}

async function refreshEditorComments() {
  try {
    const comments = await editor.refreshComments();
    setReviewCommentTruth(comments);
    if (reviewState.active) renderReviewSession();
    if ($('overview-drawer').classList.contains('open')) renderOverviewReviewThreads();
    return comments;
  } catch (error) {
    toast(error.message || '批注刷新失败', true);
    return [];
  }
}

function findingComment(finding) {
  const commentId = finding?.appliedCommentId || finding?.applied_comment_id || '';
  return commentId ? reviewState.commentsById.get(commentId) || null : null;
}

function trueFindingState(finding) {
  return findingComment(finding)?.findingState || '';
}

function findingStateLabel(state) {
  if (state === 'accepted') return '已接受';
  if (state === 'provisional') return 'AI 暂定 · 未经人工确认';
  if (state === 'pending') return '待议 · 未经人工确认';
  if (state === 'withdrawn') return '已撤回';
  return 'AI 建议';
}

async function loadReviewSessions(loadLatest = false) {
  const { json } = await apiJson(`/api/review-sessions?path=${encodeURIComponent(DOC_PATH)}`);
  reviewState.sessions = json.ok && Array.isArray(json.sessions) ? json.sessions : [];
  renderReviewHistory();
  if (loadLatest && !reviewState.active && reviewState.sessions.length) {
    await loadReviewSession(reviewState.sessions[0].id);
  }
}

async function loadReviewSession(id) {
  const { json } = await apiJson(`/api/review-sessions/${encodeURIComponent(id)}`);
  if (!json.ok) return toast(json.error || '评审记录读取失败', true);
  activateReviewSession(json.session);
  renderReviewSession();
}

async function pollReviewRun(runId, mode = '') {
  while (reviewState.activeRun?.id === runId && reviewRunActive(reviewState.activeRun)) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const { json } = await apiJson(`/api/review-runs/${encodeURIComponent(runId)}`, { cache: 'no-store' });
    if (!json.ok) {
      setReviewRunning(false, json.error || '评审状态读取失败', true);
      return;
    }
    activateReviewSession(json.session, json.run);
    renderReviewSession();
  }
  const run = reviewState.activeRun;
  if (!run || run.id !== runId) return;
  if (mode === 'initial' && run.status === 'completed') {
    await refreshEditorComments();
    setReviewRunning(false, '首评完成：唯一可靠的 findings 已作为 provisional 批注写入，尚未视为已接受。');
  } else if (run.status === 'preview' && isAcademicPaperReviewRun(run)) {
    setReviewRunning(false, 'Academic Paper Review 已生成预览；勾选后可加入主评审。');
  } else if (run.status === 'preview') {
    setReviewRunning(false, '复审完成：操作停在 preview，批注未发生写入。');
  } else if (run.status === 'needs_rebase') {
    setReviewRunning(false, '模型运行期间正文或批注发生变化；操作已保留，但需要重新预检。', true);
  } else if (run.status === 'cancelled') {
    setReviewRunning(false, '评审已取消。', true);
  } else if (run.status === 'failed') {
    setReviewRunning(false, run.error || '评审运行失败。', true);
  } else {
    setReviewRunning(false, REVIEW_STATUS[run.status] || '评审状态已更新。');
  }
  await loadReviewSessions(false);
}

function renderReviewHistory() {
  const root = $('review-history');
  root.textContent = '';
  if (!reviewState.sessions.length) {
    root.innerHTML = '<div class="history-empty">还没有评审记录。</div>';
    return;
  }
  reviewState.sessions.slice(0, 8).forEach((session) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'history-row';
    row.innerHTML = `<strong>${esc((session.summary || '未命名评审').slice(0, 52))}</strong>
      <span>${esc(REVIEW_STATUS[session.status] || session.status || '')}</span>
      <span>${esc(`${String(session.tool || '').toUpperCase()} · ${session.updated_at || ''}`)}</span>
      <span>${Number(session.finding_count || 0)} 条</span>`;
    row.onclick = () => loadReviewSession(session.id);
    root.appendChild(row);
  });
}

function renderReviewSession() {
  const session = reviewState.active;
  const run = reviewState.activeRun;
  $('review-empty').hidden = Boolean(session);
  $('review-session').hidden = !session;
  if (!session) {
    updateOperationSelectionControls();
    return;
  }
  const findings = session.findings || [];
  const accepted = findings.filter((finding) => trueFindingState(finding) === 'accepted').length;
  const ready = findings.filter((finding) => finding.anchorState === 'ready').length;
  const applied = findings.filter((finding) => Boolean(findingComment(finding))).length;
  const blocked = findings.filter((finding) => finding.anchorState !== 'ready').length;
  const status = $('review-status');
  status.className = `review-status ${session.status || ''}`;
  status.textContent = REVIEW_STATUS[session.status] || session.status || '未知';
  $('review-session-meta').textContent = `${session.tool.toUpperCase()} · ${run?.mode || 'legacy'} · ${session.id} · rev ${session.baseRev}`;
  $('review-summary').textContent = session.summary || '本轮未提供总评。';
  const operationCounts = (run?.operations || []).reduce((counts, operation) => {
    counts[operation.action] = (counts[operation.action] || 0) + 1;
    return counts;
  }, {});
  const attention = run
    ? reviewAttentionSummary(run.operations || [], 'operation')
    : reviewAttentionSummary(findings, 'finding');
  $('review-stats').innerHTML = [
    `<span class="review-stat">${findings.length} 条 findings</span>`,
    `<span class="review-stat">${accepted} 条人工确认接受</span>`,
    `<span class="review-stat">${applied} 条已写回</span>`,
    `<span class="review-stat">待处理 ${attention.pending || 0}</span>`,
    `<span class="review-stat">待确认已解决 ${attention.candidate_resolved || 0}</span>`,
    (attention.system_conflict || 0) ? `<span class="review-stat conflict">系统冲突 ${attention.system_conflict}</span>` : '',
    `<span class="review-stat">更多 ${attention.more || 0}</span>`,
    run ? `<span class="review-stat">操作：新增 ${operationCounts.create || 0} · 修改 ${operationCounts.update || 0} · 撤回 ${operationCounts.withdraw || 0} · 续接 ${operationCounts.keep || 0} · 冲突 ${operationCounts.blocked || 0}</span>` : '',
  ].join('');
  $('review-ledger-eyebrow').textContent = run ? 'OPERATION PREVIEW' : 'FINDINGS LEDGER';
  $('review-ledger-title').textContent = run ? '操作预览' : '评审清单';
  if (run) renderOperationPreview(run);
  else renderFindings(findings);
  updateOperationSelectionControls();
  renderReviewMessages(session.messages || []);
}

const REVIEW_ATTENTION_GROUPS = [
  { state: 'pending', label: '待处理', code: 'PENDING' },
  { state: 'candidate_resolved', label: '待确认已解决', code: 'RESOLVED?' },
  { state: 'system_conflict', label: '系统冲突', code: 'CONFLICT', prominent: true },
  { state: 'more', label: '更多', code: 'MORE' },
];

const MORE_STATE_LABEL = {
  evidence_unverified: '待证建议',
  muted: '已屏蔽',
  resolved: '已解决',
  audit: '审计记录',
};

const OPERATION_ACTION_LABEL = {
  create: '新增', update: '修改', withdraw: '撤回',
  keep: '续接', blocked: '系统冲突', candidate_resolved: '可能解决',
};

const KEEP_REVERIFICATION_DISCLAIMER = '不变（表示本轮未改动，不代表 AI 重新逐条核验）';

function operationField(operation, camel, snake) {
  return operation?.[camel] ?? operation?.[snake] ?? '';
}

function arrayField(value) {
  return Array.isArray(value) ? value : [];
}

function proposedComment(operation) {
  return operation?.proposed_comment || operation?.proposedComment || {};
}

function reviewWorkflowState(record) {
  return (record?.workflow || {}).state || record?.workflow_state || '';
}

function reviewPlacementScope(record) {
  const placement = record?.placement || {};
  if (placement.scope) return placement.scope;
  if (record?.anchorState === 'ready' || record?.anchor_state === 'ready') return 'quote';
  if (record?.kind === 'overall') return 'document';
  return 'quote';
}

function sourceBadgeLabel(record, operation = null) {
  const origin = record?.origin || operation?.origin || {};
  const actorType = origin.actor_type || record?.actor_type || '';
  const source = record?.source || operation?.source || '';
  if (actorType === 'human' || source === 'manual') return '人工';
  if (actorType === 'ai' || source === 'ai-review' || source === 'selection-conversation') return 'AI';
  return operation ? 'AI' : '人工';
}

function placementBadgeLabel(record) {
  const scope = reviewPlacementScope(record);
  if (scope === 'quote') return '原文';
  if (scope === 'section') return '本节';
  if (scope === 'document') return '全文';
  if (scope === 'evidence_unverified') return '待证';
  return '原文';
}

function reviewItemAttentionState(item, kind = 'finding') {
  const record = kind === 'operation' ? proposedComment(item) : item;
  const workflow = reviewWorkflowState(record);
  const reason = String(item?.reason || '').toLowerCase();
  const scope = reviewPlacementScope(record);
  if (kind === 'operation' && item.action === 'blocked') return 'system_conflict';
  if (kind === 'operation' && item.action === 'candidate_resolved') return 'candidate_resolved';
  if (workflow === 'candidate_resolved') return 'candidate_resolved';
  if (workflow === 'muted_by_user') return 'muted';
  if (workflow === 'resolved') return 'resolved';
  if (scope === 'evidence_unverified' || workflow === 'evidence_unverified' || reason === 'evidence_unverified') {
    return 'evidence_unverified';
  }
  if (kind === 'finding' && (item.anchorState || item.anchor_state) === 'missing') return 'evidence_unverified';
  return 'pending';
}

function groupReviewItems(items, kind = 'finding') {
  const groups = REVIEW_ATTENTION_GROUPS.map((group) => ({ ...group, items: [] }));
  const byState = Object.fromEntries(groups.map((group) => [group.state, group]));
  items.forEach((item) => {
    const state = reviewItemAttentionState(item, kind);
    if (state === 'pending' || state === 'candidate_resolved' || state === 'system_conflict') {
      byState[state].items.push(item);
    } else {
      byState.more.items.push({ ...item, _moreState: state });
    }
  });
  return groups.filter((group) => !(group.state === 'system_conflict' && !group.items.length));
}

function reviewAttentionSummary(items, kind = 'finding') {
  return groupReviewItems(items, kind).reduce((counts, group) => {
    counts[group.state] = group.items.length;
    return counts;
  }, { pending: 0, candidate_resolved: 0, system_conflict: 0, more: 0 });
}

function evidenceProgress(record) {
  const occurrences = arrayField(record?.evidence_occurrences || record?.evidenceOccurrences);
  if (!occurrences.length) return null;
  const done = occurrences.filter((item) => ['handled', 'not_applicable'].includes(item.progress_state)).length;
  return { done, total: occurrences.length, label: `${done}/${occurrences.length}` };
}

function locatorPayload(locator) {
  try {
    return encodeURIComponent(JSON.stringify(locator || {}));
  } catch {
    return '';
  }
}

function decodeLocatorPayload(value) {
  try {
    return JSON.parse(decodeURIComponent(value || ''));
  } catch {
    return {};
  }
}

function reviewBadgeHtml(record, operation = null) {
  const source = sourceBadgeLabel(record, operation);
  const placement = placementBadgeLabel(record);
  return `<span class="review-badge source">${esc(source)}</span><span class="review-badge placement">${esc(placement)}</span>`;
}

function evidenceProgressHtml(record, commentId = '') {
  const progress = evidenceProgress(record);
  const occurrences = arrayField(record?.evidence_occurrences || record?.evidenceOccurrences);
  if (!progress || !occurrences.length) return '';
  const rows = occurrences.map((occurrence, index) => {
    const checked = occurrence.progress_state === 'handled';
    const locator = occurrence.source_locator || occurrence.sourceLocator || {};
    const quote = record.quote_text || record.quoteText || '';
    const disabled = commentId ? '' : 'disabled';
    return `<li>
      <button type="button" data-occurrence-jump data-quote="${esc(quote)}" data-source-locator="${locatorPayload(locator)}">跳转 ${index + 1}</button>
      <label><input type="checkbox" data-occurrence-progress="${esc(occurrence.id || '')}" data-comment-id="${esc(commentId)}" ${checked ? 'checked' : ''} ${disabled}> 已处理</label>
      <span>${esc(occurrence.section_title || occurrence.sectionTitle || '未标章节')}</span>
    </li>`;
  }).join('');
  return `<details class="occurrence-details">
    <summary>证据进度 ${esc(progress.label)}</summary>
    <ol>${rows}</ol>
  </details>`;
}

function locationDetailsHtml(record, operation = null) {
  const evidence = record?.evidence || {};
  const placementDetail = record?.placement_detail || record?.placementDetail || {};
  const placement = record?.placement || {};
  const candidates = [
    ...arrayField(placementDetail.candidates),
    ...arrayField(evidence.candidates),
  ];
  const matchCount = evidence.match_count ?? record?.anchor_matches ?? record?.anchorMatches ?? '';
  const fallbackReason = placementDetail.downgrade_reason
    || evidence.fallback_reason
    || placement.state
    || operation?.reason
    || '';
  const rows = [];
  if (fallbackReason) rows.push(`<p><span class="finding-label">原因</span>${esc(fallbackReason)}</p>`);
  if (matchCount !== '') rows.push(`<p><span class="finding-label">match count</span>${esc(String(matchCount))}</p>`);
  if (candidates.length) {
    rows.push(`<ol>${candidates.slice(0, 8).map((candidate, index) => (
      `<li>${index + 1}. ${esc(candidate.section_title || candidate.sectionTitle || candidate.section_id || candidate.sectionId || '候选位置')} · block ${esc(String(candidate.block_index ?? candidate.blockIndex ?? ''))}</li>`
    )).join('')}</ol>`);
  }
  if (!rows.length) return '';
  return `<details class="location-details"><summary>定位详情</summary>${rows.join('')}</details>`;
}

function resolutionReviewHtml(operation) {
  const review = operation?.resolution_review || operation?.resolutionReview || {};
  if (!review.before_text && !review.after_text && !review.new_evidence) return '';
  return `<details class="ai-interpretation"><summary>AI 推测：解决复核依据</summary>
    ${review.before_text ? `<p><span class="finding-label">修改前</span>${esc(review.before_text)}</p>` : ''}
    ${review.after_text ? `<p><span class="finding-label">修改后</span>${esc(review.after_text)}</p>` : ''}
    ${review.new_evidence ? `<p><span class="finding-label">新文本依据</span>${esc(review.new_evidence)}</p>` : ''}
  </details>`;
}

function operationSelectable(operation) {
  const state = reviewItemAttentionState(operation, 'operation');
  return !['system_conflict', 'evidence_unverified', 'muted', 'resolved', 'audit'].includes(state);
}

function updateOperationSelectionControls() {
  const run = reviewState.activeRun;
  const selection = $('review-operation-selection');
  const confirm = $('review-writeback');
  const acceptAll = $('review-accept-all');
  if (!run) {
    selection.hidden = true;
    acceptAll.hidden = true;
    confirm.hidden = false;
    confirm.textContent = '同步已接受批注';
    syncRuntimeControls();
    return;
  }
  const operations = run.operations || [];
  const humanPending = operations.filter((operation) => (
    operation.action === 'update'
    && Boolean(operationField(operation, 'humanEditedTarget', 'human_edited_target'))
    && !reviewState.acceptedOperationIds.has(operation.id)
  )).length;
  selection.hidden = false;
  if (run.status === 'completed') {
    selection.textContent = `写回已完成 · receipt ${run.writeback_receipt_id || '已记录'} · ${reviewState.acceptedOperationIds.size} 项操作`;
  } else {
    selection.textContent = `已选择 ${reviewState.acceptedOperationIds.size} 项。${humanPending ? `${humanPending} 条人工编辑目标未纳入批量接受，必须逐条显式勾选。` : '提交时再次校验 document rev、comments_rev 与 operation ids。'}`;
  }
  acceptAll.hidden = run.status !== 'preview';
  confirm.hidden = run.status !== 'preview';
  confirm.textContent = isAcademicPaperReviewRun(run) ? '加入主评审已选项' : '确认写回已选操作';
  syncRuntimeControls();
}

function renderOperationPreview(run) {
  const root = $('review-findings');
  root.textContent = '';
  root.className = 'review-findings operation-preview';
  const operations = run.operations || [];
  groupReviewItems(operations, 'operation').forEach((group) => {
    const section = document.createElement('section');
    section.className = `operation-group operation-group-${group.state}${group.prominent && group.items.length ? ' prominent' : ''}`;
    section.dataset.operationGroup = group.state.replace(/_/g, '-');
    const candidateTargets = group.items
      .filter((operation) => operation.action === 'candidate_resolved')
      .map((operation) => operationField(operation, 'targetCommentId', 'target_comment_id'))
      .filter(Boolean);
    const bulkResolved = group.state === 'candidate_resolved' && run.status === 'completed' && candidateTargets.length
      ? `<div class="operation-group-actions">
          <button type="button" data-candidate-resolved-confirm="${esc(candidateTargets.join(','))}">批量确认已解决</button>
          <button type="button" data-candidate-resolved-restore="${esc(candidateTargets.join(','))}">恢复为待处理</button>
        </div>` : '';
    section.innerHTML = `<header><span>${group.code}</span><h4>${group.label}</h4><b>${group.items.length}</b></header>${bulkResolved}<div class="operation-group-list"></div>`;
    const list = section.querySelector('.operation-group-list');
    if (!group.items.length) {
      list.innerHTML = '<div class="history-empty">本组无操作。</div>';
    }
    group.items.forEach((operation) => {
      const proposed = proposedComment(operation);
      const appliedState = trueFindingState(proposed);
      const humanEdited = operation.action === 'update'
        && Boolean(operationField(operation, 'humanEditedTarget', 'human_edited_target'));
      const blocked = operation.action === 'blocked';
      const selectable = operationSelectable(operation);
      const checked = reviewState.acceptedOperationIds.has(operation.id);
      const card = document.createElement('article');
      card.className = `operation-card${humanEdited ? ' human-edited' : ''}`;
      card.dataset.operationId = operation.id;
      card.dataset.operationAction = operation.action;
      card.dataset.attentionState = reviewItemAttentionState(operation, 'operation').replace(/_/g, '-');
      if (humanEdited) card.dataset.humanEdited = 'true';
      const targetId = operationField(operation, 'targetCommentId', 'target_comment_id');
      const findingId = operationField(operation, 'findingId', 'finding_id');
      const quote = proposed.quote_text || proposed.quoteText || '';
      const issue = proposed.issue || '';
      const action = proposed.action || '';
      const reason = operation.reason || (blocked ? '未提供阻断原因' : '');
      const resurfacing = operation.resurfacing_notice || operation.resurfacingNotice || {};
      const moreLabel = operation._moreState ? MORE_STATE_LABEL[operation._moreState] || '审计记录' : '';
      const progress = evidenceProgress(proposed);
      card.innerHTML = `<div class="operation-card-head">
          <span class="operation-id">${esc(operation.id)}</span>
          <span class="operation-finding">${esc(findingId || '无 finding id')}</span>
          <span class="operation-action">${esc(OPERATION_ACTION_LABEL[operation.action] || operation.action || '操作')}</span>
          ${moreLabel ? `<span class="operation-action more">${esc(moreLabel)}</span>` : ''}
          ${reviewBadgeHtml(proposed, operation)}
          ${progress ? `<span class="evidence-progress">证据 ${esc(progress.label)}</span>` : ''}
          <span class="finding-state ${esc(appliedState || 'suggested')}">${esc(findingStateLabel(appliedState))}</span>
          ${targetId ? `<span class="operation-target">target ${esc(targetId)}</span>` : ''}
        </div>
        <div class="operation-copy">
          ${quote ? `<p class="operation-quote">「${esc(quote.slice(0, 260))}」</p>` : ''}
          ${issue ? `<p><span class="finding-label">问题</span>${esc(issue)}</p>` : ''}
          ${action ? `<p><span class="finding-label">建议</span>${esc(action)}</p>` : ''}
          ${reason ? `<p class="operation-reason"><span class="finding-label">原因</span>${esc(reason)}</p>` : ''}
        </div>
        ${resurfacing.message ? `<p class="resurfacing-notice">${esc(resurfacing.message)}</p>` : ''}
        ${operation.action === 'keep' ? `<p class="operation-keep-disclaimer">${KEEP_REVERIFICATION_DISCLAIMER}</p>` : ''}
        ${resurfacing.mute_available && targetId ? `<button class="lineage-mute" type="button" data-lineage-mute="${esc(targetId)}">不再提示本问题</button>` : ''}
        ${resolutionReviewHtml(operation)}
        ${evidenceProgressHtml(proposed, targetId)}
        ${locationDetailsHtml(proposed, operation)}
        ${humanEdited ? '<p class="human-edit-warning">该目标批注含人工编辑。批量接受不会选中此项；只有本项复选框的显式确认才允许覆盖。</p>' : ''}
        <label class="operation-accept${!selectable ? ' blocked' : ''}">
          <input type="checkbox" data-operation-accept="${esc(operation.id)}" ${checked ? 'checked' : ''} ${!selectable || run.status !== 'preview' ? 'disabled' : ''}>
          <span>${!selectable ? '不进入正常评审区' : humanEdited ? '显式接受这次覆盖' : operation.action === 'candidate_resolved' ? '提交为待确认已解决' : '接受此项'}</span>
        </label>`;
      const checkbox = card.querySelector('[data-operation-accept]');
      if (selectable && run.status === 'preview') {
        checkbox.onchange = () => {
          if (checkbox.checked) reviewState.acceptedOperationIds.add(operation.id);
          else reviewState.acceptedOperationIds.delete(operation.id);
          updateOperationSelectionControls();
        };
      }
      list.appendChild(card);
    });
    root.appendChild(section);
  });
}

function acceptAllNonBlockedOperations() {
  const operations = reviewState.activeRun?.operations || [];
  reviewState.acceptedOperationIds = new Set(operations.filter((operation) => (
    operationSelectable(operation)
    && !(operation.action === 'update'
      && Boolean(operationField(operation, 'humanEditedTarget', 'human_edited_target')))
  )).map((operation) => operation.id));
  renderOperationPreview(reviewState.activeRun);
  updateOperationSelectionControls();
}

function renderFindings(findings) {
  const root = $('review-findings');
  root.textContent = '';
  root.className = 'review-findings';
  if (!findings.length) {
    root.innerHTML = '<div class="history-empty">这一轮没有生成可锚定的 findings。</div>';
    return;
  }
  groupReviewItems(findings, 'finding').forEach((group) => {
    const section = document.createElement('section');
    section.className = `operation-group finding-group-${group.state}${group.prominent && group.items.length ? ' prominent' : ''}`;
    section.dataset.operationGroup = group.state.replace(/_/g, '-');
    section.innerHTML = `<header><span>${group.code}</span><h4>${group.label}</h4><b>${group.items.length}</b></header><div class="operation-group-list"></div>`;
    const list = section.querySelector('.operation-group-list');
    if (!group.items.length) list.innerHTML = '<div class="history-empty">本组无记录。</div>';
    group.items.forEach((finding) => {
      const state = trueFindingState(finding);
      const card = document.createElement('article');
      card.className = `finding-card priority-${esc(finding.priority || 'P2')}${state === 'withdrawn' ? ' rejected' : ''}`;
      card.dataset.attentionState = reviewItemAttentionState(finding, 'finding').replace(/_/g, '-');
      const anchorText = finding.anchorState === 'ready' ? '锚点可靠' : finding.anchorState === 'ambiguous' ? '锚点重复' : '锚点缺失';
      const progress = evidenceProgress(finding);
      const comment = findingComment(finding);
      card.innerHTML = `<div class="finding-head">
          <span class="finding-id">${esc(finding.id)}</span>
          <span class="finding-priority">${esc(finding.priority)}</span>
          <span class="finding-section">${esc(finding.section || '未标章节')}</span>
          ${reviewBadgeHtml(finding)}
          ${progress ? `<span class="evidence-progress">证据 ${esc(progress.label)}</span>` : ''}
          <span class="anchor-chip ${esc(finding.anchorState)}">${anchorText}</span>
          <span class="finding-state ${esc(state || 'suggested')}">${esc(findingStateLabel(state))}</span>
        </div>
        <button type="button" class="finding-quote">「${esc((finding.quoteText || finding.quote_text || '').slice(0, 220))}」</button>
        <p class="finding-issue"><span class="finding-label">问题</span>${esc(finding.issue)}</p>
        <details class="ai-interpretation"><summary>AI 推测：解读与建议</summary>
          <p class="finding-action"><span class="finding-label">建议</span>${esc(finding.action)}</p>
          ${finding.evidenceRequirement ? `<p class="finding-action"><span class="finding-label">证据</span>${esc(finding.evidenceRequirement)}</p>` : ''}
        </details>
        ${evidenceProgressHtml(finding, comment?.id || '')}
        ${locationDetailsHtml(finding)}
        <div class="finding-actions">
          ${comment ? '<span class="finding-applied">✓ 已写回批注</span>' : '<span class="finding-applied">模型建议尚未成为批注</span>'}
        </div>`;
      card.querySelector('.finding-quote').onclick = () => {
        editor.jumpToQuote(finding.quoteText || finding.quote_text || '', finding.sourceLocator || finding.source_locator || {});
        closeReviewDrawer();
      };
      list.appendChild(card);
    });
    root.appendChild(section);
  });
}

function renderReviewMessages(messages) {
  const root = $('review-messages');
  root.textContent = '';
  messages.forEach((message) => {
    const item = document.createElement('div');
    item.className = `review-message ${message.role === 'user' ? 'user' : 'assistant'}`;
    item.textContent = message.content || '';
    root.appendChild(item);
  });
  root.scrollTop = root.scrollHeight;
}

async function startReview() {
  if (reviewState.running) return;
  if (editor.dirty) return toast('请先保存正文，再启动评审。', true);
  openReviewPreflight();
  reviewState.preflight = null;
  $('review-preflight-primary').disabled = true;
  $('review-preflight-route-code').textContent = 'CHECKING';
  $('review-preflight-route').textContent = '正在核对 revision、批注与锚点';
  $('review-preflight-scope').textContent = '确定性预检不会调用模型';
  // Endpoint prefix kept stable for host smoke checks: /api/review-preflight?path=
  const params = new URLSearchParams({ path: DOC_PATH, ...selectedReviewAgentIdentity() });
  const { response, json } = await apiJson(`/api/review-preflight?${params.toString()}`, { cache: 'no-store' });
  if (!response.ok || !json.ok || !json.preflight) {
    $('review-preflight-route-code').textContent = 'FAILED';
    $('review-preflight-route').textContent = '预检失败';
    $('review-preflight-scope').textContent = json.error || `HTTP ${response.status}`;
    return;
  }
  if (json.preflight.document?.current_rev !== editor.documentState.rev) {
    await editor.load();
    toast('磁盘 revision 已变化；编辑器已载入当前版本。', true);
  }
  renderReviewPreflight(json.preflight);
}

async function runReview(mode) {
  const preflight = reviewState.preflight;
  if (!preflight || reviewState.running) return;
  const tool = selectedReviewTool();
  if (!await requireRuntimeTool(tool, 'structured_review')) return;
  closeReviewPreflight();
  openReviewDrawer();
  const modeLabel = mode === 'initial' ? '首次完整评审' : mode === 'incremental' ? '增量复审' : '强制全文复审';
  setReviewRunning(true, `${tool.toUpperCase()} 正在执行${modeLabel}；模型返回后会先校验锚点并生成操作。`);
  const { json } = await apiJson('/api/review-runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path: DOC_PATH,
      base_rev: preflight.document.current_rev,
      baseline_session_id: preflight.baseline_session?.id || '',
      comments_rev: preflight.comments.comments_rev,
      mode,
      tool,
      ...selectedReviewAgentIdentity(),
      instruction: $('review-instruction').value.trim(),
      evidence_source_ids: [...evidenceState.selectedIds],
    }),
  });
  if (!json.ok) return setReviewRunning(false, userFacingApiError(json, `${modeLabel}失败`), true);
  activateReviewSession(json.session, json.run);
  if (reviewRunActive(json.run)) {
    setReviewRunning(true, json.idempotent
      ? '相同 revision 的评审已在运行；已复用该 run，不会重复调用模型。'
      : `${tool.toUpperCase()} 已进入后台执行；完成后会自动刷新结果。`);
    renderReviewSession();
    pollReviewRun(json.run.id, mode);
  } else if (mode === 'initial' && json.writeback?.ok) {
    setReviewRunning(false, '首评完成：唯一可靠的 findings 已作为 provisional 批注写入，尚未视为已接受。');
  } else if (json.run?.status === 'preview' && isAcademicPaperReviewRun(json.run)) {
    setReviewRunning(false, 'Academic Paper Review 已生成预览；勾选后可加入主评审。');
  } else if (json.run?.status === 'needs_rebase') {
    setReviewRunning(false, '模型运行期间正文或批注发生变化；操作已保留，但需要重新预检。', true);
  } else {
    setReviewRunning(false, '复审完成：操作停在 preview，批注未发生写入。');
  }
  renderReviewSession();
  if (mode === 'initial') await refreshEditorComments();
  await loadReviewSessions(false);
}

async function continueReview() {
  const session = reviewState.active;
  const message = $('review-message').value.trim();
  if (!session || !message || reviewState.running) return;
  if (!await requireRuntimeTool(session.tool, 'structured_review')) return;
  setReviewRunning(true, '正在结合你的意见更新 findings，并重新核验当前原文…');
  const { json } = await apiJson(`/api/review-sessions/${encodeURIComponent(session.id)}/messages`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message }),
  });
  if (!json.ok) return setReviewRunning(false, userFacingApiError(json, '更新评审失败'), true);
  $('review-message').value = '';
  activateReviewSession(json.session, reviewState.activeRun);
  setReviewRunning(false, '评审清单已更新并停在 preview；批注未发生写入。');
  renderReviewSession();
  await refreshEditorComments();
  await loadReviewSessions(false);
}

async function syncReview() {
  const session = reviewState.active;
  if (!session || reviewState.running) return;
  const run = reviewState.activeRun;
  if (run) {
    const acceptedOperationIds = (run.operations || [])
      .filter((operation) => reviewState.acceptedOperationIds.has(operation.id))
      .map((operation) => operation.id);
    if (!acceptedOperationIds.length) return toast('请先选择至少一项非阻断操作。', true);
    setReviewRunning(true, '正在同一 mutation lock 内校验 document rev、comments_rev 与 operation ids…');
    const { response, json } = await apiJson(`/api/review-runs/${encodeURIComponent(run.id)}/writeback`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_rev: run.input?.document_rev,
        comments_rev: run.input?.comments_rev,
        accepted_operation_ids: acceptedOperationIds,
      }),
    });
    if (!response.ok || !json.ok) {
      setReviewRunning(false, json.message || json.error || '操作写回失败；未写入任何部分结果。', true);
      renderReviewSession();
      return;
    }
    activateReviewSession(json.session, json.run);
    const receipt = json.writeback || {};
    setReviewRunning(false, `写回完成：新增 ${(receipt.created || []).length}，修改 ${(receipt.updated || []).length}，撤回 ${(receipt.withdrawn || []).length}，不变 ${(receipt.kept || []).length}。`);
    renderReviewSession();
    await refreshEditorComments();
    await loadReviewSessions(false);
    return;
  }
  toast('旧 session 不能直接写回；请重新预检并通过 review run 操作预览确认。');
  return startReview();
}

async function decideFinding(findingId, decision) {
  const session = reviewState.active;
  if (!session || reviewState.running) return;
  const { json } = await apiJson(`/api/review-sessions/${encodeURIComponent(session.id)}/findings`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ finding_id: findingId, decision }),
  });
  if (!json.ok) return toast(json.error || '更新 finding 失败', true);
  activateReviewSession(json.session);
  renderReviewSession();
}

async function muteFindingLineage(commentId) {
  if (!commentId) return;
  const { response, json } = await apiJson(`/api/comments/${encodeURIComponent(commentId)}/lineage-mute`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, actor: 'June' }),
  });
  if (!response.ok || !json.ok) return toast(json.error || json.message || '屏蔽失败', true);
  await refreshEditorComments();
  toast('本问题后续不再提示；可在文章总览恢复。');
}

async function restoreFindingLineage(commentId) {
  if (!commentId) return;
  const { response, json } = await apiJson(`/api/comments/${encodeURIComponent(commentId)}/lineage-restore`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, actor: 'June' }),
  });
  if (!response.ok || !json.ok) return toast(json.error || json.message || '恢复失败', true);
  await refreshEditorComments();
  toast('该问题已恢复到正常提示。');
}

async function confirmCandidateResolved(commentIds) {
  const ids = commentIds.filter(Boolean);
  if (!ids.length) return;
  const { response, json } = await apiJson('/api/comments/candidate-resolved/confirm', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, comment_ids: ids, actor: 'June' }),
  });
  if (!response.ok || !json.ok) return toast(json.error || json.message || '确认已解决失败', true);
  await refreshEditorComments();
  toast(`已确认 ${ids.length} 条 finding 已解决。`);
}

async function restoreCandidateResolved(commentIds) {
  const ids = commentIds.filter(Boolean);
  if (!ids.length) return;
  const { response, json } = await apiJson('/api/comments/candidate-resolved/restore', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: DOC_PATH, comment_ids: ids, actor: 'June' }),
  });
  if (!response.ok || !json.ok) return toast(json.error || json.message || '恢复待处理失败', true);
  await refreshEditorComments();
  toast(`已恢复 ${ids.length} 条 finding 到待处理。`);
}

async function setOccurrenceProgress(commentId, occurrenceId, state) {
  if (!commentId || !occurrenceId) return;
  const { response, json } = await apiJson(
    `/api/comments/${encodeURIComponent(commentId)}/evidence-occurrences/${encodeURIComponent(occurrenceId)}/progress`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: DOC_PATH, state, actor: 'June' }),
    },
  );
  if (!response.ok || !json.ok) return toast(json.error || json.message || '证据进度更新失败', true);
  await refreshEditorComments();
}

function resetReviewComposer() {
  reviewState.active = null;
  reviewState.activeRun = null;
  reviewState.acceptedOperationIds = new Set();
  $('review-instruction').value = '';
  setReviewRunning(false, '当前视图已清空；点击“重新预检”后再选择评审范围。');
  renderReviewSession();
}

function selectedConversationTool() {
  return document.querySelector('input[name="conversation-tool"]:checked')?.value || DEFAULT_AI_TOOL;
}

function sourceQuotePayload(sourceQuote) {
  return {
    quote_text: sourceQuote?.quoteText || '',
    section: sourceQuote?.section || '',
    source_locator: sourceQuote?.sourceLocator || null,
  };
}

function openConversationDock() {
  $('conversation-dock').hidden = false;
  $('conversation-dock').classList.remove('collapsed');
  $('conversation-collapse').textContent = '⌄';
}

function closeConversationDock() {
  $('conversation-dock').hidden = true;
}

function setConversationRunning(running, message = '') {
  conversationState.running = Boolean(running);
  if (message) $('conversation-status').textContent = message;
  syncRuntimeControls();
}

function syncConversationTool(tool, locked = false) {
  const selected = document.querySelector(`input[name="conversation-tool"][value="${tool}"]`);
  if (selected) selected.checked = true;
  const inputs = [...document.querySelectorAll('input[name="conversation-tool"]')];
  const ready = inputs.find((input) => runtimeToolReady(input.value, 'conversation'));
  if (!locked && ready && !runtimeToolReady(inputs.find((input) => input.checked)?.value, 'conversation')) ready.checked = true;
  inputs.forEach((input) => {
    const unavailable = !runtimeToolReady(input.value, 'conversation');
    input.disabled = locked || conversationState.running || unavailable;
    input.closest('label')?.classList.toggle('is-unavailable', unavailable);
  });
  document.querySelector('.conversation-tool-switch').classList.toggle('is-locked', locked);
}

function setConversationSource(sourceQuote) {
  conversationState.sourceQuote = sourceQuote?.quoteText ? sourceQuote : null;
  const source = $('conversation-source');
  source.hidden = !conversationState.sourceQuote;
  $('conversation-quote').textContent = conversationState.sourceQuote?.quoteText || '';
}

async function loadConversationSessions(loadLatest = false) {
  const { json } = await apiJson(`/api/conversations?path=${encodeURIComponent(DOC_PATH)}`);
  conversationState.sessions = json.ok && Array.isArray(json.sessions) ? json.sessions : [];
  $('conversation-count').textContent = String(conversationState.sessions.length);
  renderConversationHistory();
  if (loadLatest && !conversationState.active && conversationState.sessions.length) {
    await loadConversationSession(conversationState.sessions[0].id);
  }
}

async function loadConversationSession(id) {
  const { json } = await apiJson(`/api/conversations/${encodeURIComponent(id)}`);
  if (!json.ok) return toast(json.error || '讨论记录读取失败', true);
  conversationState.active = normalizeHostConversationSession(json.session);
  setConversationSource(conversationState.active.sourceQuote);
  syncConversationTool(conversationState.active.tool, true);
  conversationState.composerMode = 'followup';
  conversationState.parentMessageId = lastAssistantMessage()?.id || '';
  openConversationDock();
  renderConversation();
}

function renderConversationHistory() {
  const root = $('conversation-history');
  root.textContent = '';
  conversationState.sessions.slice(0, 8).forEach((session) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = session.id === conversationState.active?.id ? 'active' : '';
    button.textContent = `“${String(session.source_quote?.quote_text || '').slice(0, 34)}”`;
    button.title = session.last_response || '';
    button.onclick = () => loadConversationSession(session.id);
    root.appendChild(button);
  });
}

function lastAssistantMessage() {
  return (conversationState.active?.messages || []).filter((message) => message.role === 'assistant').at(-1) || null;
}

function openConversationForQuote(sourceQuote) {
  conversationState.active = null;
  conversationState.composerMode = 'root';
  conversationState.parentMessageId = '';
  syncConversationTool(selectedConversationTool(), false);
  setConversationSource(sourceQuote);
  $('quick-explain').hidden = true;
  openConversationDock();
  renderConversation();
  $('conversation-message').value = '';
  $('conversation-message').focus();
}

async function quickExplain(sourceQuote) {
  conversationState.quickSource = sourceQuote;
  $('quick-quote').textContent = sourceQuote.quoteText;
  $('quick-output').textContent = '正在生成临时解释…';
  $('quick-explain').hidden = false;
  const tool = selectedConversationTool();
  if (!await requireRuntimeTool(tool, 'quick_explain')) {
    $('quick-output').textContent = CLI_UNAVAILABLE_GUIDE;
    return;
  }
  const { json } = await apiJson('/api/ai-run', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path: DOC_PATH, tool, selection: sourceQuote.quoteText,
      prompt: '请用简明中文解释这段内容：它在论证中做了什么、证据边界在哪里、阅读时最需要注意什么。不要改写原文。',
    }),
  });
  $('quick-output').textContent = json.ok
    ? (json.output || '（没有返回内容）')
    : `解释失败：${userFacingApiError(json, '未知错误')}`;
  if (!json.ok && json.code === 'cli_unavailable') await loadRuntimeCapabilities();
}

function configureConversationComposer(mode = 'followup', parentMessageId = '') {
  conversationState.composerMode = mode;
  conversationState.parentMessageId = parentMessageId;
  const labels = {
    root: '开始一段引用式讨论', followup: '继续当前讨论',
    fork: '将从这条 AI 回复建立新分支', note: '给这条 AI 回复留下评论',
  };
  $('conversation-context').textContent = labels[mode] || labels.followup;
  $('conversation-context-cancel').hidden = mode === 'root' || mode === 'followup';
  $('conversation-message').placeholder = mode === 'note'
    ? '记录你对这条回复的判断，不会调用 AI…'
    : mode === 'fork' ? '从这里换一个假设、角度或证据路径…' : '继续追问这段原文…';
  $('conversation-send').textContent = mode === 'root' ? '开始讨论' : mode === 'note' ? '添加评论' : mode === 'fork' ? '创建分支' : '发送';
  $('conversation-message').value = '';
  $('conversation-message').focus();
  syncRuntimeControls();
}

function assistantMessageElement(message, notes) {
  const item = document.createElement('article');
  item.className = 'conversation-message assistant';
  item.innerHTML = `<div class="conversation-message-meta"><span>${esc(message.author || conversationState.active?.tool || 'AI')}</span><time>${esc(message.at || '')}</time></div>
    <div class="conversation-message-body">${esc(message.content)}</div>
    <div class="conversation-message-actions">
      <button type="button" data-conversation-action="followup" data-message-id="${esc(message.id)}">继续追问</button>
      <button type="button" data-conversation-action="note" data-message-id="${esc(message.id)}">评论</button>
      <button type="button" data-conversation-action="fork" data-message-id="${esc(message.id)}">⑂ 从此分叉</button>
      <button type="button" data-conversation-action="writeback" data-message-id="${esc(message.id)}">写回批注</button>
      ${message.writebackCommentId ? '<span class="written">✓ 已写回</span>' : ''}
    </div>`;
  for (const note of notes) {
    const noteElement = document.createElement('div');
    noteElement.className = 'conversation-note';
    noteElement.textContent = note.content;
    item.appendChild(noteElement);
  }
  return item;
}

function renderConversationBranch(branchId, container, branchStarts, notesByMessage, depth = 0) {
  if (depth > 8) return;
  const messages = (conversationState.active?.messages || []).filter(
    (message) => message.role !== 'note' && (message.branchId || 'main') === branchId,
  );
  for (const message of messages) {
    let item;
    if (message.role === 'user') {
      item = document.createElement('div');
      item.className = 'conversation-message user';
      item.textContent = message.content;
    } else {
      item = assistantMessageElement(message, notesByMessage.get(message.id) || []);
    }
    container.appendChild(item);
    for (const childBranchId of branchStarts.get(message.id) || []) {
      const branch = document.createElement('section');
      branch.className = 'conversation-branch';
      renderConversationBranch(childBranchId, branch, branchStarts, notesByMessage, depth + 1);
      container.appendChild(branch);
    }
  }
}

function renderConversation() {
  const session = conversationState.active;
  const hasScope = Boolean(conversationState.sourceQuote?.quoteText);
  $('conversation-empty').hidden = hasScope;
  $('conversation-tree').hidden = !session;
  $('conversation-composer').hidden = !hasScope;
  $('conversation-writeback-editor').hidden = true;
  if (!session) {
    $('conversation-tree').textContent = '';
    syncConversationTool(selectedConversationTool(), false);
    configureConversationComposer('root');
    $('conversation-status').textContent = hasScope ? '引用已固定；输入问题后建立讨论记录' : '围绕原文展开，不直接改稿';
    renderConversationHistory();
    return;
  }
  syncConversationTool(session.tool, true);
  const evidenceLabel = session.evidenceSources?.length ? ` · ${session.evidenceSources.length} 份参考资料` : '';
  $('conversation-status').textContent = `${session.tool.toUpperCase()} · ${session.messages.length} 条消息${evidenceLabel} · rev ${session.baseRev}`;
  const notesByMessage = new Map();
  const branchStarts = new Map();
  for (const message of session.messages) {
    if (message.role === 'note' && message.noteForMessageId) {
      if (!notesByMessage.has(message.noteForMessageId)) notesByMessage.set(message.noteForMessageId, []);
      notesByMessage.get(message.noteForMessageId).push(message);
    }
    if (message.branchFromMessageId && message.branchId) {
      if (!branchStarts.has(message.branchFromMessageId)) branchStarts.set(message.branchFromMessageId, []);
      if (!branchStarts.get(message.branchFromMessageId).includes(message.branchId)) {
        branchStarts.get(message.branchFromMessageId).push(message.branchId);
      }
    }
  }
  const tree = $('conversation-tree');
  tree.textContent = '';
  renderConversationBranch('main', tree, branchStarts, notesByMessage);
  configureConversationComposer('followup', lastAssistantMessage()?.id || '');
  tree.scrollTop = tree.scrollHeight;
  renderConversationHistory();
}

async function sendConversationMessage() {
  const content = $('conversation-message').value.trim();
  if (!content || conversationState.running) return;
  const mode = conversationState.composerMode;
  const tool = conversationState.active?.tool || selectedConversationTool();
  if (mode !== 'note' && !await requireRuntimeTool(tool, 'conversation')) return;
  setConversationRunning(true, mode === 'note' ? '正在记录评论…' : mode === 'fork' ? '正在生成分支回复…' : 'AI 正在围绕引用回复…');
  let url = '/api/conversations';
  let body;
  if (mode === 'root') {
    body = {
      path: DOC_PATH, base_rev: editor.documentState.rev, tool: selectedConversationTool(),
      source_quote: sourceQuotePayload(conversationState.sourceQuote), message: content,
      evidence_source_ids: [...evidenceState.selectedIds],
    };
  } else if (mode === 'note') {
    url = `/api/conversations/${encodeURIComponent(conversationState.active.id)}/notes`;
    body = { parent_message_id: conversationState.parentMessageId, content };
  } else {
    url = `/api/conversations/${encodeURIComponent(conversationState.active.id)}/messages`;
    body = { parent_message_id: conversationState.parentMessageId, message: content, mode };
  }
  const { json } = await apiJson(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!json.ok) {
    const message = userFacingApiError(json, '讨论失败');
    setConversationRunning(false, message);
    return toast(message, true);
  }
  conversationState.active = normalizeHostConversationSession(json.session);
  setConversationSource(conversationState.active.sourceQuote);
  $('conversation-message').value = '';
  setConversationRunning(false, json.branch_created ? '新分支已建立' : mode === 'note' ? '评论已记录' : '回复完成');
  renderConversation();
  await loadConversationSessions(false);
}

function openConversationWriteback(messageId) {
  const message = conversationState.active?.messages.find((item) => item.id === messageId && item.role === 'assistant');
  if (!message) return;
  conversationState.writebackMessageId = messageId;
  $('conversation-writeback-content').value = message.content;
  $('conversation-writeback-editor').hidden = false;
  $('conversation-composer').hidden = true;
  $('conversation-writeback-content').focus();
}

async function writebackConversationMessage() {
  const session = conversationState.active;
  const content = $('conversation-writeback-content').value.trim();
  if (!session || !content || conversationState.running) return;
  setConversationRunning(true, '正在核对原文版本并写回批注…');
  const { json } = await apiJson(`/api/conversations/${encodeURIComponent(session.id)}/writeback`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: conversationState.writebackMessageId, content }),
  });
  if (!json.ok) {
    setConversationRunning(false, json.message || json.error || '写回失败');
    return toast(json.message || json.error || '写回失败', true);
  }
  conversationState.active = normalizeHostConversationSession(json.session);
  setConversationRunning(false, json.action === 'created' ? '已写回为原文批注' : json.action === 'updated' ? '批注已更新' : '这条回复已经写回');
  await refreshEditorComments();
  renderConversation();
}

$('btn-review-history').onclick = async () => { openReviewDrawer(); if (!reviewState.active) await loadReviewSessions(true); };
$('btn-quick-explain')?.addEventListener('click', quickExplainFromToolbar);
$('btn-selection-discuss')?.addEventListener('click', discussSelectionFromToolbar);
$('doc-primary-actions').onclick = (event) => {
  const button = event.target.closest('[data-host-toolbar-action]');
  if (!button || button.disabled) return;
  runEditorToolbarAction(button.dataset.hostToolbarAction);
};
$('doc-more-editor-actions').onclick = (event) => {
  const button = event.target.closest('[data-host-toolbar-action]');
  if (!button || button.disabled) return;
  $('doc-more-menu').open = false;
  runEditorToolbarAction(button.dataset.hostToolbarAction);
};
$('conversation-evidence-open').onclick = openEvidenceDrawer;
$('evidence-close').onclick = closeEvidenceDrawer;
$('evidence-scrim').onclick = closeEvidenceDrawer;
$('evidence-choose').onclick = () => $('evidence-file').click();
$('evidence-file').onchange = () => attachEvidenceFile($('evidence-file').files?.[0]);
$('evidence-list').onclick = (event) => {
  const button = event.target.closest('button[data-evidence-action]');
  if (!button) return;
  const evidenceId = button.closest('[data-evidence-id]')?.dataset.evidenceId;
  if (button.dataset.evidenceAction === 'confirm') confirmEvidenceFullText(evidenceId);
  if (button.dataset.evidenceAction === 'summary') generateEvidenceSummary(evidenceId);
};
$('evidence-list').onchange = (event) => {
  const checkbox = event.target.closest('input[data-evidence-action="select"]');
  if (!checkbox) return;
  const evidenceId = checkbox.closest('[data-evidence-id]')?.dataset.evidenceId;
  if (!evidenceId) return;
  if (checkbox.checked) evidenceState.selectedIds.add(evidenceId);
  else evidenceState.selectedIds.delete(evidenceId);
  const count = evidenceState.selectedIds.size;
  setEvidenceUploadState(count ? `已选择 ${count} 份资料；只会用于下一次新建的讨论或评审。` : '当前没有资料会进入下一次讨论或评审。');
};
$('import-close').onclick = closeImportDialog;
$('import-scrim').onclick = closeImportDialog;
$('import-choose').onclick = () => $('import-file').click();
$('import-another').onclick = async () => {
  if (importState.busy) return;
  await discardStagedImport();
  resetImportDialog();
  $('import-file').click();
};
$('import-file').onchange = () => stageImportFile($('import-file').files?.[0]);
$('import-commit').onclick = commitStagedImport;
$('doc-file-menu').addEventListener('toggle', () => {
  if ($('doc-file-menu').open) loadDocumentMenu();
});
$('doc-file-list').onclick = (event) => {
  const item = event.target.closest('[data-doc-path]');
  if (!item) return;
  switchDocument(item.dataset.docPath || '');
};
$('overview-close').onclick = closeOverview;
$('overview-scrim').onclick = closeOverview;
$('overview-muted-list').onclick = (event) => {
  const restore = event.target.closest('[data-lineage-restore]');
  if (restore) restoreFindingLineage(restore.dataset.lineageRestore);
};
$('overview-generate').onclick = () => generateDocumentSummary(false);
$('overview-regenerate').onclick = () => {
  const current = overviewState.summary?.base_rev === editor.documentState.rev;
  if (current && !window.confirm('确认重新生成当前 revision 的文章总览？旧记录会保留在 summary 台账中。')) return;
  generateDocumentSummary(current);
};
$('overview-tool').onchange = syncRuntimeControls;
$('btn-versions').onclick = () => openArchive('versions');
$('btn-export').onclick = () => openArchive('exports');
$('archive-close').onclick = closeArchive;
$('archive-scrim').onclick = closeArchive;
document.querySelectorAll('[data-archive-tab]').forEach((button) => {
  button.onclick = () => setArchiveTab(button.dataset.archiveTab);
});
$('checkpoint-create').onclick = createCheckpoint;
$('checkpoint-label').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') { event.preventDefault(); createCheckpoint(); }
});
$('version-list').onclick = (event) => {
  const button = event.target.closest('[data-version-action]');
  if (!button) return;
  const versionId = button.closest('[data-version-id]')?.dataset.versionId;
  if (button.dataset.versionAction === 'diff') showVersionDiff(versionId);
  if (button.dataset.versionAction === 'restore') restoreVersion(versionId);
};
$('draft-list').onclick = (event) => {
  const button = event.target.closest('[data-draft-action]');
  if (!button) return;
  const draftId = button.closest('[data-draft-id]')?.dataset.draftId;
  if (button.dataset.draftAction === 'diff') showDraftDiff(draftId);
  if (button.dataset.draftAction === 'restore') restoreDraft(draftId);
  if (button.dataset.draftAction === 'dismiss') dismissDraft(draftId);
};
$('diff-close').onclick = () => { $('version-diff').hidden = true; };
$('export-list').onclick = (event) => {
  const button = event.target.closest('[data-export-format]');
  if (button && !button.disabled) downloadExport(button.dataset.exportFormat);
};
$('review-close').onclick = closeReviewDrawer;
$('review-scrim').onclick = closeReviewDrawer;
$('review-start').onclick = startReview;
$('review-preflight-close').onclick = closeReviewPreflight;
$('review-preflight-cancel').onclick = closeReviewPreflight;
$('review-preflight-scrim').onclick = closeReviewPreflight;
$('review-preflight-view').onclick = viewLatestReview;
$('review-preflight-incremental').onclick = () => runReview('incremental');
$('review-preflight-force').onclick = () => runReview('forced-full');
$('review-preflight-primary').onclick = () => {
  const mode = $('review-preflight-primary').dataset.mode;
  if (mode === 'view-latest') return viewLatestReview();
  return runReview(mode);
};
$('review-new').onclick = resetReviewComposer;
$('review-accept-all').onclick = acceptAllNonBlockedOperations;
$('review-writeback').onclick = syncReview;
$('review-send').onclick = continueReview;
$('review-findings').onclick = (event) => {
  const mute = event.target.closest('[data-lineage-mute]');
  if (mute) return muteFindingLineage(mute.dataset.lineageMute);
  const restore = event.target.closest('[data-lineage-restore]');
  if (restore) return restoreFindingLineage(restore.dataset.lineageRestore);
  const confirm = event.target.closest('[data-candidate-resolved-confirm]');
  if (confirm) return confirmCandidateResolved(confirm.dataset.candidateResolvedConfirm.split(','));
  const restoreResolved = event.target.closest('[data-candidate-resolved-restore]');
  if (restoreResolved) return restoreCandidateResolved(restoreResolved.dataset.candidateResolvedRestore.split(','));
  const jump = event.target.closest('[data-occurrence-jump]');
  if (jump) {
    editor.jumpToQuote(jump.dataset.quote || '', decodeLocatorPayload(jump.dataset.sourceLocator || ''));
    closeReviewDrawer();
  }
};
$('review-findings').onchange = (event) => {
  const checkbox = event.target.closest('[data-occurrence-progress]');
  if (!checkbox) return;
  setOccurrenceProgress(
    checkbox.dataset.commentId,
    checkbox.dataset.occurrenceProgress,
    checkbox.checked ? 'handled' : 'open',
  );
};
$('review-message').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); continueReview(); }
});
$('btn-conversations').onclick = async () => { openConversationDock(); await loadConversationSessions(!conversationState.active); renderConversation(); };
$('conversation-close').onclick = closeConversationDock;
$('conversation-collapse').onclick = () => {
  const collapsed = $('conversation-dock').classList.toggle('collapsed');
  $('conversation-collapse').textContent = collapsed ? '⌃' : '⌄';
};
$('conversation-source').onclick = () => {
  if (conversationState.sourceQuote) editor.jumpToQuote(
    conversationState.sourceQuote.quoteText, conversationState.sourceQuote.sourceLocator || {},
  );
};
$('conversation-send').onclick = sendConversationMessage;
$('conversation-message').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); sendConversationMessage(); }
});
$('conversation-context-cancel').onclick = () => configureConversationComposer('followup', lastAssistantMessage()?.id || '');
$('conversation-tree').onclick = (event) => {
  const button = event.target.closest('[data-conversation-action]');
  if (!button) return;
  const action = button.dataset.conversationAction;
  const messageId = button.dataset.messageId;
  if (action === 'writeback') return openConversationWriteback(messageId);
  configureConversationComposer(action, messageId);
};
$('conversation-writeback-cancel').onclick = () => {
  $('conversation-writeback-editor').hidden = true;
  $('conversation-composer').hidden = false;
};
$('conversation-writeback-confirm').onclick = writebackConversationMessage;
$('quick-close').onclick = () => { $('quick-explain').hidden = true; };
$('quick-deepen').onclick = () => {
  if (conversationState.quickSource) openConversationForQuote(conversationState.quickSource);
};
$('cli-status').onclick = () => {
  if ($('cli-popover').hidden) openRuntimePopover();
  else closeRuntimePopover();
};
$('cli-redetect').onclick = async () => {
  await loadRuntimeCapabilities();
  openRuntimePopover();
};
document.addEventListener('click', (event) => {
  if (!event.target.closest('.cli-status-wrap')) closeRuntimePopover();
  if (!event.target.closest('#ai-tools-popover') && !event.target.closest('[data-host-toolbar-action="ai-tools"]')) closeAiToolsPopover();
  if (!event.target.closest('#doc-file-menu')) $('doc-file-menu').open = false;
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !$('import-modal').hidden) closeImportDialog();
  if (event.key === 'Escape') {
    closeAiToolsPopover();
    $('doc-more-menu').open = false;
    $('doc-file-menu').open = false;
  }
});
window.addEventListener('resize', renderHostToolbar, { passive: true });
document.querySelectorAll('input[name="review-tool"], input[name="conversation-tool"]').forEach((input) => {
  input.addEventListener('change', syncRuntimeControls);
});

window.__COMMA_REVIEW__ = {
  editor, adapter, reviewState, startReview, runReview, continueReview, syncReview,
  openReviewDrawer, closeReviewDrawer, loadReviewSession, loadReviewSessions,
  conversationState, loadConversationSession,
  loadConversationSessions, openConversationForQuote, sendConversationMessage,
  loadRuntimeCapabilities, runtimeToolReady, archiveState, loadVersions,
  openArchive, closeArchive, createCheckpoint, restoreVersion, restoreDraft,
  openOverview, closeOverview, renderReviewPreflight, closeReviewPreflight,
  overviewState, loadDocumentSummary, generateDocumentSummary, acceptAllProvisionalComments,
  importState, openImportDialog, closeImportDialog, stageImportFile, commitStagedImport,
  documentMenuState, loadDocumentMenu, switchDocument,
  evidenceState, openEvidenceDrawer, closeEvidenceDrawer, loadEvidenceSources, attachEvidenceFile,
  reviewItemAttentionState, groupReviewItems, reviewAttentionSummary,
  muteFindingLineage, restoreFindingLineage, confirmCandidateResolved, restoreCandidateResolved,
};
window.__SPIKE__ = window.__COMMA_REVIEW__;

loadRuntimeCapabilities();
consumePendingDocumentToast();
loadDocumentMenu();
loadVersions();
loadReviewSessions(false);
loadConversationSessions(false);
loadEvidenceSources();
