export type ApiJson = Record<string, unknown>;
export interface CanvasContextEntry {
  id?: string;
  kind?: string;
  title?: string;
  summary?: string;
  relation?: string;
  path?: string;
  resolved_path?: string;
  status?: string;
}
export type CanvasTarget = {
  kind: 'card' | 'map' | 'convmap';
  value: string;
};

export type StudioRecentKind = CanvasTarget['kind'] | 'conv';

export interface ProjectMapSummary {
  scope: string;
  label?: string;
  active_count?: number;
  project?: string;
  exists?: boolean;
  canvas_ref?: string;
  canvas_rev?: string;
  updated_at?: string;
}

export interface ProjectMapVersion {
  id: string;
  created_at: string;
  node_count: number;
  edge_count: number;
  canvas_rev: string;
}

export interface ProjectMapVersionsPayload extends ApiJson {
  ok: boolean;
  canvas_ref: string;
  versions: ProjectMapVersion[];
}

export interface ProjectMapVersionPreviewPayload extends ApiJson {
  ok: boolean;
  canvas_ref: string;
  version: ProjectMapVersion;
  canvas: Record<string, unknown>;
}

export interface RealProjectSummary {
  project_ref: string;
  title?: string;
  lifecycle?: 'active' | 'paused' | 'completed' | 'archived' | string;
}

export interface AttentionQueueItem {
  task_id: string;
  title: string;
  next_action?: string;
  path: string;
  status: string;
  assignee?: string;
  updated?: string;
  project_ref?: string;
}

export interface AttentionQueuePayload extends ApiJson {
  ok: boolean;
  scope: 'global' | 'project';
  project?: string;
  counts: { needs_you: number; processing: number; planned: number; other_projects_needs_you: number };
  needs_you: AttentionQueueItem[];
  processing: AttentionQueueItem[];
  planned: AttentionQueueItem[];
}

export interface SystemAlertItem {
  key: 'chains' | 'governance' | 'nightly' | string;
  label: string;
  count: number;
  message: string;
}

export interface SystemAlertsPayload extends ApiJson {
  ok: boolean;
  has_anomaly: boolean;
  count: number;
  summary: string;
  items: SystemAlertItem[];
  checked_at?: string;
}

export interface ProjectMaterialAsset {
  role: 'manifest' | 'unexpanded' | 'rollout' | 'pointer';
  path: string;
  draggable: boolean;
}

export interface ProjectConversationMaterial {
  kind: 'codex' | 'claude-science';
  conversation_id: string;
  title: string;
  assets: ProjectMaterialAsset[];
}

export interface ProjectMaterialsPayload extends ApiJson {
  ok: boolean;
  project_ref: string;
  workdir: string;
  fact_roots: string[];
  conversations: ProjectConversationMaterial[];
}

export interface ConversationMapSummary {
  path: string;
  title?: string;
  thread_id?: string;
  status?: string;
  node_count?: number;
  updated_at?: string;
  error?: string;
  canvas_scope?: string;
  canvas_ref?: string;
  canvas_exists?: boolean;
  canvas_rev?: string;
  canvas_updated_at?: string;
}

export interface ConversationProjectGraphNode {
  id: string;
  type: string;
  title: string;
  assertion?: 'hard_evidence' | 'ai_archived' | 'human_confirmed' | string;
  status?: string;
  archive_state?: string;
  summary?: string;
  manifest_path?: string;
  task_id?: string;
  path?: string;
  live_ref?: { path?: string; title?: string; status?: string; updated?: string; sha256?: string } | null;
  snapshot_at_archive?: Record<string, unknown> | null;
  drift?: { state?: string; changed?: boolean | null };
  unresolved?: boolean;
}

export interface ConversationProjectGraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  assertion?: 'hard_evidence' | 'ai_archived' | 'human_confirmed' | string;
  status?: string;
  confidence?: number | null;
  evidence?: Array<Record<string, unknown>>;
}

export interface ConversationProjectGraphPayload extends ApiJson {
  ok: boolean;
  schema: string;
  generated_at?: string;
  nodes: ConversationProjectGraphNode[];
  edges: ConversationProjectGraphEdge[];
  counts?: Record<string, number>;
  ledger_path?: string;
}

export interface TaskCanvasSummary {
  path: string;
  task_id?: string;
  title?: string;
  status?: string;
  updated?: string;
  project?: string;
  canvas_ref?: string;
  canvas_rev?: string;
  canvas_updated_at?: string;
  updated_at?: string;
}

export interface CanvasSeedIntentPayload extends ApiJson {
  ok?: boolean;
  available?: boolean;
  demo_mode?: boolean;
  message?: string;
  path?: string;
  intent?: string;
  draft?: string;
  provider?: string;
  execution_brief?: CanvasExecutionBrief;
}

export interface CanvasExecutionBrief {
  understanding?: string;
  goal?: string;
  sources?: string[] | string;
  source_summary?: Array<{ role?: string; path?: string; summary?: string }>;
  actions?: string[];
  delivery?: string;
  deliverable?: string;
  completion_gate?: string[] | string;
  recipe?: string;
}

export interface CanvasSeedRunPayload extends ApiJson {
  ok?: boolean;
  available?: boolean;
  demo_mode?: boolean;
  message?: string;
  run_id?: string;
  path?: string;
  intent?: string;
  recipe?: string;
  queue?: string;
  stage?: string;
  stage_label?: string;
  canvas_ref?: string;
  canvas_rev?: string;
  execution_brief?: CanvasExecutionBrief;
  usable?: boolean;
  quality_passed?: boolean;
  quality_gate?: { passed?: boolean; usable?: boolean } & ApiJson;
  summary_counts?: {
    total?: number;
    pending?: number;
    done?: number;
    skipped?: number;
    failed?: number;
  };
}

export interface ProjectCanvasReorganizeRunPayload extends ApiJson {
  ok: boolean;
  run_id: string;
  status: string;
  project_ref: string;
  queue: 'ai-run';
  deduplicated?: boolean;
}

export interface AiQueueEntry extends ApiJson {
  id: string;
  status: string;
  path?: string;
  dedupe_key?: string;
  metadata?: Record<string, unknown>;
}

export function findActiveProjectCanvasReorganize(
  entries: AiQueueEntry[],
  projectRef: string,
): AiQueueEntry | null {
  const activeEntries = entries.filter((entry) => ['queued', 'running'].includes(String(entry.status || '')));
  const dedupeKey = `project-canvas-explorer:${projectRef}`;
  const exactMatch = activeEntries.find((entry) => String(entry.dedupe_key || '') === dedupeKey);
  if (exactMatch) return exactMatch;
  return activeEntries.find((entry) => {
    const metadata = entry.metadata && typeof entry.metadata === 'object' ? entry.metadata : {};
    const isExplorerRun = String(metadata.kind || '') === 'project_canvas_explorer'
      || String(metadata.skill || '') === 'project-canvas-explorer'
      || String(entry.path || '') === 'skills/project-canvas-explorer/SKILL.md';
    return isExplorerRun && String(metadata.project_ref || '') === projectRef;
  }) || null;
}

export interface LedgerEntry {
  kind: string;
  event: string;
  ts?: string;
  actor?: string;
  summary?: string;
  raw?: ApiJson;
  source?: ApiJson;
}

export interface LedgerPayload extends ApiJson {
  ok?: boolean;
  task_id?: string;
  path?: string;
  count?: number;
  source_counts?: Record<string, number>;
  entries?: LedgerEntry[];
}

export interface ConversationMapSourceCommand {
  anchor: string;
  command: string;
}

export interface ConversationMapNode {
  id: string;
  type: string;
  title: string;
  status?: string;
  summary?: string;
  source?: string[];
  source_commands?: ConversationMapSourceCommand[];
  parent?: string;
  return_to?: string;
  branch_from?: string;
  next_nodes?: string[];
  card?: string;
}

export interface ConversationMapEdge {
  id: string;
  source: string;
  target: string;
  relation: 'parent' | 'next' | 'return_to' | 'branch_from' | string;
}

export interface ConversationMapPayload {
  ok: boolean;
  canvas_scope?: string;
  canvas_ref?: string;
  manifest_path: string;
  manifest_abs_path?: string;
  manifest_schema?: string;
  manifest_version?: number;
  status?: string;
  generated_at?: string;
  updated_at?: string;
  thread?: {
    id?: string;
    title?: string;
    raw_rollout?: string;
    raw_rollout_sha256?: string;
  } & Record<string, unknown>;
  current_cursor?: {
    node?: string;
    why?: string;
    return_to_if_resuming_prior_work?: string;
    source?: string[];
    source_commands?: ConversationMapSourceCommand[];
  };
  plan?: {
    premises?: string[];
    steps?: string[];
    premise_nodes?: ConversationMapNode[];
    step_nodes?: ConversationMapNode[];
  };
  nodes?: ConversationMapNode[];
  edges?: ConversationMapEdge[];
  node_count?: number;
}

async function readJson(response: Response): Promise<ApiJson> {
  try {
    return await response.json() as ApiJson;
  } catch {
    return {};
  }
}

export class CanvasConflictError extends Error {
  payload: ApiJson;

  constructor(payload: ApiJson) {
    super(String(payload.message || payload.error || 'canvas conflict'));
    this.name = 'CanvasConflictError';
    this.payload = payload;
  }
}

function targetQuery(target: CanvasTarget): string {
  const key = target.kind === 'map' ? 'map' : target.kind === 'convmap' ? 'convmap' : 'path';
  return `${key}=${encodeURIComponent(target.value)}`;
}

function targetBody(target: CanvasTarget): Record<string, string> {
  if (target.kind === 'map') return { map: target.value };
  if (target.kind === 'convmap') return { convmap: target.value };
  return { path: target.value };
}

export async function load(target: CanvasTarget): Promise<ApiJson> {
  const response = await fetch(`/api/canvas?${targetQuery(target)}`);
  if (!response.ok) {
    throw new Error(`load failed: ${response.status}`);
  }
  return readJson(response);
}

export async function save(target: CanvasTarget, canvas: unknown, baseRev?: string | null): Promise<ApiJson> {
  const response = await fetch('/api/canvas', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    // Interactive saves are attributed from the authenticated server session.
    body: JSON.stringify({ ...targetBody(target), canvas, base_rev: baseRev || undefined }),
  });
  if (response.status === 409) {
    throw new CanvasConflictError(await readJson(response));
  }
  if (!response.ok) {
    throw new Error(`save failed: ${response.status}`);
  }
  return readJson(response);
}

export async function saveNode(
  target: CanvasTarget,
  nodeId: string,
  node: unknown,
  baseNode: unknown,
  baseRev?: string | null,
): Promise<ApiJson> {
  if (target.kind !== 'card') {
    throw new Error('node save only supports task canvases');
  }
  const response = await fetch('/api/canvas/node', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path: target.value,
      node_id: nodeId,
      node,
      base_node: baseNode || undefined,
      base_rev: baseRev || undefined,
    }),
  });
  if (response.status === 409) {
    throw new CanvasConflictError(await readJson(response));
  }
  if (!response.ok) {
    throw new Error(`node save failed: ${response.status}`);
  }
  return readJson(response);
}

export async function generate(target: CanvasTarget, force?: boolean, baseRev?: string | null): Promise<ApiJson> {
  const response = await fetch('/api/canvas/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...targetBody(target), force, base_rev: baseRev || undefined }),
  });
  if (response.status === 409) {
    throw new CanvasConflictError(await readJson(response));
  }
  if (!response.ok) {
    throw new Error(`generate failed: ${response.status}`);
  }
  return readJson(response);
}

export async function refreshProjectMap(scope: string, force?: boolean, baseRev?: string | null): Promise<ApiJson> {
  const response = await fetch('/api/canvas/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ map: scope, force, base_rev: baseRev || undefined }),
  });
  if (response.status === 409) {
    throw new CanvasConflictError(await readJson(response));
  }
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.error || `refresh failed: ${response.status}`));
  }
  return payload;
}

export async function listProjectMapVersions(scope: string): Promise<ProjectMapVersionsPayload> {
  const response = await fetch(`/api/canvas/versions?map=${encodeURIComponent(scope)}`);
  const payload = await readJson(response) as ProjectMapVersionsPayload;
  if (!response.ok) {
    throw new Error(String(payload.error || `canvas versions failed: ${response.status}`));
  }
  return payload;
}

export async function previewProjectMapVersion(scope: string, version: string): Promise<ProjectMapVersionPreviewPayload> {
  const params = new URLSearchParams({ map: scope, version });
  const response = await fetch(`/api/canvas/versions?${params.toString()}`);
  const payload = await readJson(response) as ProjectMapVersionPreviewPayload;
  if (!response.ok) {
    throw new Error(String(payload.error || `canvas version preview failed: ${response.status}`));
  }
  return payload;
}

export async function restoreProjectMapVersion(
  scope: string,
  version: string,
  baseRev?: string | null,
): Promise<ApiJson> {
  const response = await fetch('/api/canvas/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ map: scope, version, base_rev: baseRev || undefined }),
  });
  if (response.status === 409) {
    throw new CanvasConflictError(await readJson(response));
  }
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.error || `canvas restore failed: ${response.status}`));
  }
  return payload;
}

export async function loadAttentionQueue(project = ''): Promise<AttentionQueuePayload> {
  const query = project ? `?project=${encodeURIComponent(project)}` : '';
  const response = await fetch(`/api/attention-queue${query}`);
  const payload = await readJson(response) as AttentionQueuePayload;
  if (!response.ok) {
    throw new Error(String(payload.error || `attention queue failed: ${response.status}`));
  }
  if (project && (payload.scope !== 'project' || payload.project !== project)) {
    throw new Error('attention queue did not honor project scope');
  }
  return payload;
}

export async function loadSystemAlerts(): Promise<SystemAlertsPayload> {
  const response = await fetch('/api/system-alerts');
  const payload = await readJson(response) as SystemAlertsPayload;
  if (!response.ok || payload.ok !== true) {
    throw new Error(String(payload.error || `system alerts failed: ${response.status}`));
  }
  return payload;
}

export async function loadLedger(taskIdOrPath: string, since = ''): Promise<LedgerPayload> {
  const query = since ? `?since=${encodeURIComponent(since)}` : '';
  const response = await fetch(`/api/ledger/${encodeURIComponent(taskIdOrPath)}${query}`);
  const payload = await readJson(response) as LedgerPayload;
  if (!response.ok) {
    throw new Error(String(payload.error || `ledger failed: ${response.status}`));
  }
  return payload;
}

export async function loadNodeHistory(taskIdOrPath: string, nodeId: string, since = ''): Promise<LedgerPayload> {
  const params = new URLSearchParams({ task_id: taskIdOrPath, node_id: nodeId });
  if (since) params.set('since', since);
  const response = await fetch(`/api/canvas/node-history?${params.toString()}`);
  const payload = await readJson(response) as LedgerPayload;
  if (!response.ok) {
    throw new Error(String(payload.error || `node history failed: ${response.status}`));
  }
  return payload;
}

export async function seedIntent(path: string): Promise<CanvasSeedIntentPayload> {
  const response = await fetch('/api/canvas/seed-intent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  const payload = await readJson(response) as CanvasSeedIntentPayload;
  if (!response.ok) {
    throw new Error(String(payload.error || `seed intent failed: ${response.status}`));
  }
  return payload;
}

export async function seedRun(path: string, intent: string, tool = 'codex'): Promise<CanvasSeedRunPayload> {
  const response = await fetch('/api/canvas/seed-run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, intent, tool }),
  });
  const payload = await readJson(response) as CanvasSeedRunPayload;
  if (!response.ok) {
    throw new Error(String(payload.error || `seed run failed: ${response.status}`));
  }
  return payload;
}

export async function startProjectCanvasReorganize(projectRef: string): Promise<ProjectCanvasReorganizeRunPayload> {
  const response = await fetch('/api/canvas/reorganize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_ref: projectRef }),
  });
  const payload = await readJson(response) as ProjectCanvasReorganizeRunPayload;
  if (!response.ok || payload.ok === false) {
    throw new Error(String(payload.error || `project canvas reorganize failed: ${response.status}`));
  }
  return payload;
}

export async function loadActiveProjectCanvasReorganize(projectRef: string): Promise<AiQueueEntry | null> {
  const response = await fetch('/api/queue');
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.error || `AI queue failed: ${response.status}`));
  }
  const queue = payload.queue && typeof payload.queue === 'object'
    ? payload.queue as Record<string, unknown>
    : {};
  const entries = Array.isArray(queue.entries) ? queue.entries as AiQueueEntry[] : [];
  return findActiveProjectCanvasReorganize(entries, projectRef);
}

export async function loadAiRunResult(runId: string): Promise<Record<string, unknown> | null> {
  const response = await fetch(`/api/ai-results?run_id=${encodeURIComponent(runId)}`);
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.error || `ai run status failed: ${response.status}`));
  }
  const results = Array.isArray(payload.results) ? payload.results as Array<Record<string, unknown>> : [];
  return results.find((entry) => String(entry.run_id || '') === runId) || null;
}

export async function listProjectMaps(): Promise<ProjectMapSummary[]> {
  const response = await fetch('/api/project-maps');
  if (!response.ok) {
    throw new Error(`project maps failed: ${response.status}`);
  }
  const payload = await readJson(response);
  return Array.isArray(payload.maps) ? payload.maps as ProjectMapSummary[] : [];
}

export async function listRealProjects(includeArchived = false): Promise<RealProjectSummary[]> {
  const suffix = includeArchived ? '?include_archived=1' : '';
  const response = await fetch(`/api/real-projects${suffix}`);
  if (!response.ok) throw new Error(`real projects failed: ${response.status}`);
  const payload = await readJson(response);
  return Array.isArray(payload.projects) ? payload.projects as RealProjectSummary[] : [];
}

export async function loadProjectMaterials(projectRef: string): Promise<ProjectMaterialsPayload> {
  const response = await fetch(`/api/project-materials?project_ref=${encodeURIComponent(projectRef)}`);
  const payload = await readJson(response);
  if (!response.ok) throw new Error(String(payload.error || `project materials failed: ${response.status}`));
  return payload as unknown as ProjectMaterialsPayload;
}

export async function linkProjectConversation(
  projectRef: string,
  conversation: ProjectConversationMaterial,
): Promise<ProjectConversationMaterial> {
  const response = await fetch('/api/real-projects/link-conversation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_ref: projectRef, conversation }),
  });
  const payload = await readJson(response);
  if (!response.ok || payload.ok === false) {
    throw new Error(String(payload.error || `link conversation failed: ${response.status}`));
  }
  return payload.conversation as ProjectConversationMaterial;
}

export async function unlinkProjectConversation(
  projectRef: string,
  conversationId: string,
): Promise<ProjectConversationMaterial> {
  const response = await fetch('/api/real-projects/unlink-conversation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_ref: projectRef, conversation_id: conversationId }),
  });
  const payload = await readJson(response);
  if (!response.ok || payload.ok === false) {
    throw new Error(String(payload.error || `unlink conversation failed: ${response.status}`));
  }
  return payload.conversation as ProjectConversationMaterial;
}

export async function openProjectMaterial(projectRef: string, path: string): Promise<void> {
  const response = await fetch('/api/project-materials/open', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_ref: projectRef, path }),
  });
  if (!response.ok) throw new Error(`open project material failed: ${response.status}`);
}

export async function listTaskCanvases(): Promise<TaskCanvasSummary[]> {
  const response = await fetch('/api/task-canvases');
  if (!response.ok) {
    throw new Error(`task canvases failed: ${response.status}`);
  }
  const payload = await readJson(response);
  return Array.isArray(payload.canvases) ? payload.canvases as TaskCanvasSummary[] : [];
}

export async function listConversationMaps(): Promise<ConversationMapSummary[]> {
  const response = await fetch('/api/conversation-maps');
  if (!response.ok) {
    throw new Error(`conversation maps failed: ${response.status}`);
  }
  const payload = await readJson(response);
  return Array.isArray(payload.maps) ? payload.maps as ConversationMapSummary[] : [];
}

export async function loadConversationMap(path: string): Promise<ConversationMapPayload> {
  const response = await fetch(`/api/conversation-map?path=${encodeURIComponent(path)}`);
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.error || `conversation map failed: ${response.status}`));
  }
  return payload as unknown as ConversationMapPayload;
}

export async function loadConversationProjectGraph(): Promise<ConversationProjectGraphPayload> {
  const response = await fetch('/api/conversation-project-graph');
  const payload = await readJson(response);
  if (!response.ok) {
    throw new Error(String(payload.error || `conversation project graph failed: ${response.status}`));
  }
  return payload as unknown as ConversationProjectGraphPayload;
}

export async function openSource(path: string): Promise<void> {
  const response = await fetch('/api/open', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!response.ok) {
    throw new Error(`open failed: ${response.status}`);
  }
}

export async function dispatchTaskToAgent(path: string, tool: 'codex' | 'claude'): Promise<ApiJson> {
  const response = await fetch('/api/ai-run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path,
      tool,
      prompt: '',
      profile: `execute_${tool}`,
      create_workdir: false,
    }),
  });
  const payload = await readJson(response);
  if (!response.ok || payload.ok === false) {
    const detail = payload.error === 'workdir_not_found'
      ? '任务工作目录不存在，请先打开卡片确认 workdir'
      : String(payload.error || `dispatch failed: ${response.status}`);
    throw new Error(detail);
  }
  return payload;
}

// ---- KAN-110 阶段2(Claude):对话节点接 kanban AI 队列 ----
export async function aiRun(
  path: string,
  tool: string,
  prompt: string,
  displayMessage?: string,
  canvasContext: CanvasContextEntry[] = [],
  allowUnresolvedContext = false,
): Promise<ApiJson> {
  const response = await fetch('/api/ai-run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path,
      tool,
      prompt,
      display_message: displayMessage,
      canvas_context: canvasContext,
      allow_unresolved_context: allowUnresolvedContext,
    }),
  });
  return response.json();
}

export async function resolveCanvasSourceRef(
  path: string,
  sourcePath: string,
  kind = 'file',
): Promise<ApiJson> {
  const response = await fetch('/api/canvas/resolve-ref', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, source_path: sourcePath, kind }),
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(String(payload.error || `resolve-ref failed: ${response.status}`));
  }
  return payload;
}

export async function aiComment(runId: string, comment: string, forkFromIndex?: number): Promise<ApiJson> {
  const body: Record<string, unknown> = { run_id: runId, comment };
  if (forkFromIndex !== undefined && forkFromIndex !== null) body.fork_from_index = forkFromIndex;
  const response = await fetch('/api/ai-comment', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return response.json();
}

export async function aiResults(path: string): Promise<ApiJson> {
  const response = await fetch(`/api/ai-results?path=${encodeURIComponent(path)}`);
  if (!response.ok) throw new Error(`ai-results failed: ${response.status}`);
  return response.json();
}
