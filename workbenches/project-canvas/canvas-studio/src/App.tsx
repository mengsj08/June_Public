import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import type { XYPosition } from 'reactflow';
import BoardLink from './components/BoardLink';
import SystemAlertBadge from './components/SystemAlertBadge';
import Canvas from './components/Canvas';
import ConversationMapView from './components/ConversationMapView';
import ConversationProjectGraphView from './components/ConversationProjectGraphView';
import CanvasRail from './components/CanvasRail';
import type { CanvasRailTab } from './components/CanvasRail';
import { aiResults, listConversationMaps, listProjectMaps, listProjectMapVersions, listRealProjects, listTaskCanvases, loadActiveProjectCanvasReorganize, loadAiRunResult, loadAttentionQueue, loadLedger, previewProjectMapVersion, restoreProjectMapVersion, seedIntent, seedRun, startProjectCanvasReorganize } from './services/canvasApi';
import { useCanvasStore } from './store/canvasStore';
import type { AttentionQueuePayload, CanvasExecutionBrief, CanvasTarget, ConversationMapSummary, LedgerEntry, ProjectMapSummary, ProjectMapVersion, StudioRecentKind, TaskCanvasSummary } from './services/canvasApi';
import { buildDialoguePointerPackage, copyTextWithFallback } from './core/dialoguePointer';

const createId = (prefix: string) => `${prefix}_${Date.now().toString(36)}`;
const RECENT_KEY = 'canvas-studio.recent-targets';
const COUNT_KEY = 'canvas-studio.target-counts';
const APP_BASE = (import.meta.env.BASE_URL || '/').endsWith('/')
  ? (import.meta.env.BASE_URL || '/')
  : `${import.meta.env.BASE_URL || '/'}/`;

type StudioTarget = CanvasTarget | { kind: 'conv'; value: string };

interface RecentTarget {
  kind: StudioRecentKind;
  value: string;
  label: string;
  ts: number;
}

interface TargetRecord extends RecentTarget {
  count: number;
}

interface HomeTarget extends RecentTarget {
  meta: string;
  detail: string;
}

function targetHref(target: StudioTarget | RecentTarget): string {
  const key = target.kind === 'map'
    ? 'map'
    : target.kind === 'convmap'
      ? 'convmap'
      : target.kind === 'conv'
        ? 'conv'
        : 'path';
  return `${APP_BASE}?${key}=${encodeURIComponent(target.value)}`;
}

function targetStorageKey(target: Pick<RecentTarget, 'kind' | 'value'>): string {
  return `${target.kind}:${target.value}`;
}

function targetKindLabel(kind: StudioRecentKind): string {
  if (kind === 'map') return '项目图';
  if (kind === 'conv') return '对话阅读';
  if (kind === 'convmap') return '对话画布';
  return '任务画布';
}

function canvasSeedIntent(canvas: { metadata?: Record<string, unknown>; meta?: Record<string, unknown> } | null): string {
  if (!canvas) return '';
  const metadataIntent = typeof canvas.metadata?.seed_intent === 'string' ? canvas.metadata.seed_intent : '';
  const metaIntent = typeof canvas.meta?.seed_intent === 'string' ? canvas.meta.seed_intent : '';
  return (metadataIntent || metaIntent || '').trim();
}

function canvasSeedSummaryCounts(canvas: { nodes?: unknown[] } | null): { total: number; pending: number; done: number; skipped: number; failed: number } {
  const counts = { total: 0, pending: 0, done: 0, skipped: 0, failed: 0 };
  (canvas?.nodes || []).forEach((node) => {
    if (!node || typeof node !== 'object') return;
    const data = (node as { data?: unknown }).data;
    if (!data || typeof data !== 'object') return;
    const metadata = (data as { metadata?: unknown }).metadata;
    if (!metadata || typeof metadata !== 'object') return;
    if (!(metadata as { local_summary_required?: unknown }).local_summary_required) return;
    counts.total += 1;
    const status = String((metadata as { local_summary_status?: unknown }).local_summary_status || 'pending');
    if (status === 'done') counts.done += 1;
    else if (status === 'skipped') counts.skipped += 1;
    else if (status === 'failed') counts.failed += 1;
    else counts.pending += 1;
  });
  return counts;
}

function runIsUsable(run?: Record<string, unknown>): boolean {
  if (!run) return false;
  const qualityGate = run.quality_gate && typeof run.quality_gate === 'object'
    ? run.quality_gate as Record<string, unknown>
    : {};
  return run.usable === true || run.quality_passed === true || qualityGate.usable === true || qualityGate.passed === true;
}

function seedStageLabel(canvas: { nodes?: unknown[] } | null, runStatus = '', usable = false): string {
  const counts = canvasSeedSummaryCounts(canvas);
  const parts = ['骨架已出'];
  if (['error', 'timeout', 'killed'].includes(runStatus)) {
    return `生成失败（${runStatus}） → 当前仅骨架，不可作为完成结果`;
  }
  if (runStatus && runStatus !== 'completed') {
    parts.push('组织判断中');
  } else if (runStatus === 'completed') {
    parts.push(usable ? '质量门通过 · 可用' : '运行已结束 · 质量门未通过，当前仅骨架');
  }
  if (counts.total > 0) {
    const finished = counts.done + counts.skipped + counts.failed;
    parts.push(finished >= counts.total ? `摘要补全完成 ${finished}/${counts.total}` : `摘要补全中 ${finished}/${counts.total}`);
  }
  return parts.join(' → ');
}

function seedOutcomeFor(runStatus: string, usable: boolean): 'neutral' | 'failed' | 'usable' | 'skeleton' {
  if (['error', 'timeout', 'killed'].includes(runStatus)) return 'failed';
  if (runStatus !== 'completed') return 'neutral';
  return usable ? 'usable' : 'skeleton';
}

function asBriefList(value?: string[] | string): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  return value ? [String(value)] : [];
}

function briefSources(brief: CanvasExecutionBrief | null): string[] {
  const explicit = asBriefList(brief?.sources);
  if (explicit.length) return explicit;
  return (brief?.source_summary || []).map((item) => {
    const value = item.path || item.summary || '';
    return [item.role, value].filter(Boolean).join(': ');
  }).filter(Boolean);
}

function groupLedgerByActor(entries: LedgerEntry[]): Array<[string, LedgerEntry[]]> {
  const grouped = entries.reduce<Record<string, LedgerEntry[]>>((acc, entry) => {
    const actor = entry.actor || 'unknown';
    acc[actor] = [...(acc[actor] || []), entry];
    return acc;
  }, {});
  return Object.entries(grouped).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
}

function readRecentTargets(): RecentTarget[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(RECENT_KEY) || '[]') as RecentTarget[];
    return Array.isArray(parsed) ? parsed.filter((item) => item && item.kind && item.value).slice(0, 8) : [];
  } catch {
    return [];
  }
}

function readTargetCounts(): TargetRecord[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(COUNT_KEY) || '{}') as Record<string, TargetRecord> | TargetRecord[];
    const records = Array.isArray(parsed) ? parsed : Object.values(parsed || {});
    return records
      .filter((item) => item && item.kind && item.value)
      .map((item) => ({
        kind: item.kind,
        value: item.value,
        label: item.label || item.value,
        ts: Number(item.ts || 0),
        count: Math.max(0, Number(item.count || 0)),
      }))
      .filter((item) => item.count > 0);
  } catch {
    return [];
  }
}

function rememberTarget(target: StudioTarget, label: string) {
  try {
    const current = readRecentTargets().filter((item) => item.kind !== target.kind || item.value !== target.value);
    const next = [{ kind: target.kind, value: target.value, label, ts: Date.now() }, ...current].slice(0, 8);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));

    const countKey = targetStorageKey(target);
    const counts = readTargetCounts().filter((item) => targetStorageKey(item) !== countKey);
    const existing = readTargetCounts().find((item) => targetStorageKey(item) === countKey);
    const counted: TargetRecord = {
      kind: target.kind,
      value: target.value,
      label,
      ts: Date.now(),
      count: (existing?.count || 0) + 1,
    };
    const countMap = [counted, ...counts].reduce<Record<string, TargetRecord>>((acc, item) => {
      acc[targetStorageKey(item)] = item;
      return acc;
    }, {});
    window.localStorage.setItem(COUNT_KEY, JSON.stringify(countMap));
  } catch {
    /* localStorage can be unavailable in private contexts */
  }
}

function Home() {
  const [maps, setMaps] = useState<ProjectMapSummary[]>([]);
  const [taskCanvases, setTaskCanvases] = useState<TaskCanvasSummary[]>([]);
  const [conversationMaps, setConversationMaps] = useState<ConversationMapSummary[]>([]);
  const [archivedProjectRefs, setArchivedProjectRefs] = useState<Set<string>>(() => new Set());
  const [recent, setRecent] = useState<RecentTarget[]>(() => readRecentTargets());
  const [counts, setCounts] = useState<TargetRecord[]>(() => readTargetCounts());
  const [manualQuery, setManualQuery] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    Promise.allSettled([listProjectMaps(), listTaskCanvases(), listConversationMaps(), listRealProjects(true)])
      .then(([projectResult, taskCanvasResult, conversationResult, realProjectResult]) => {
        if (!alive) return;
        if (projectResult.status === 'fulfilled') {
          setMaps(projectResult.value);
        } else {
            setError(projectResult.reason instanceof Error ? projectResult.reason.message : String(projectResult.reason));
        }
        if (taskCanvasResult.status === 'fulfilled') {
          setTaskCanvases(taskCanvasResult.value);
        } else {
          setError(taskCanvasResult.reason instanceof Error ? taskCanvasResult.reason.message : String(taskCanvasResult.reason));
        }
        if (conversationResult.status === 'fulfilled') {
          setConversationMaps(conversationResult.value);
        } else {
          setError(conversationResult.reason instanceof Error ? conversationResult.reason.message : String(conversationResult.reason));
        }
        if (realProjectResult.status === 'fulfilled') {
          setArchivedProjectRefs(new Set(realProjectResult.value
            .filter((project) => project.lifecycle === 'archived')
            .map((project) => project.project_ref)));
        } else {
          setError(realProjectResult.reason instanceof Error ? realProjectResult.reason.message : String(realProjectResult.reason));
        }
      });
    setRecent(readRecentTargets());
    setCounts(readTargetCounts());
    return () => {
      alive = false;
    };
  }, []);

  const projectTargets = useMemo<HomeTarget[]>(() => maps
    .filter((item) => !archivedProjectRefs.has(item.scope.replace(/^project:/, '')))
    .map((item) => ({
    kind: 'map',
    value: item.scope,
    label: item.label || item.scope,
    ts: 0,
    meta: '项目图',
    detail: `${Number(item.active_count || 0)} active`,
  })), [maps, archivedProjectRefs]);

  const archivedProjectTargets = useMemo<HomeTarget[]>(() => maps
    .filter((item) => archivedProjectRefs.has(item.scope.replace(/^project:/, '')))
    .map((item) => ({
      kind: 'map',
      value: item.scope,
      label: item.label || item.scope,
      ts: 0,
      meta: '已归档项目图',
      detail: `${Number(item.active_count || 0)} active`,
    })), [maps, archivedProjectRefs]);

  const conversationTargets = useMemo<HomeTarget[]>(() => conversationMaps.flatMap((item) => {
    const title = item.title || item.path;
    const canvasValue = item.canvas_scope || item.path;
    const nodes = `${Number(item.node_count || 0)} nodes`;
    return [
      {
        kind: 'conv' as const,
        value: item.path,
        label: title,
        ts: 0,
        meta: '对话阅读',
        detail: nodes,
      },
      {
        kind: 'convmap' as const,
        value: canvasValue,
        label: `${title} · 画布`,
        ts: 0,
        meta: '对话画布',
        detail: item.canvas_exists ? (item.canvas_updated_at || 'has canvas') : 'will generate',
      },
    ];
  }), [conversationMaps]);

  const taskCanvasTargets = useMemo<HomeTarget[]>(() => taskCanvases.map((item) => ({
    kind: 'card',
    value: item.path,
    label: item.task_id ? `${item.task_id} ${item.title || ''}`.trim() : (item.title || item.path),
    ts: 0,
    meta: item.status ? `任务画布 · ${item.status}` : '任务画布',
    detail: item.canvas_updated_at || item.updated_at || item.updated || '',
  })), [taskCanvases]);

  const allInventoryTargets = useMemo(
    () => [...projectTargets, ...conversationTargets, ...taskCanvasTargets],
    [projectTargets, conversationTargets, taskCanvasTargets],
  );

  const inventoryByKey = useMemo(() => {
    const map = new Map<string, HomeTarget>();
    allInventoryTargets.forEach((item) => {
      map.set(targetStorageKey(item), item);
    });
    return map;
  }, [allInventoryTargets]);

  const enrichRecent = useCallback((item: RecentTarget): HomeTarget => {
    const inventory = inventoryByKey.get(targetStorageKey(item));
    return {
      ...item,
      label: inventory?.label || item.label || item.value,
      meta: inventory?.meta || targetKindLabel(item.kind),
      detail: item.ts ? new Date(item.ts).toLocaleString() : (inventory?.detail || ''),
    };
  }, [inventoryByKey]);

  const isArchivedProjectTarget = useCallback((item: Pick<RecentTarget, 'kind' | 'value'>) => (
    item.kind === 'map' && archivedProjectRefs.has(item.value.replace(/^project:/, ''))
  ), [archivedProjectRefs]);
  const resumeTargets = useMemo(() => recent
    .filter((item) => !isArchivedProjectTarget(item))
    .slice(0, 2).map(enrichRecent), [recent, enrichRecent, isArchivedProjectTarget]);
  const frequentTargets = useMemo(() => counts
    .filter((item) => !isArchivedProjectTarget(item))
    .map((item) => {
      const inventory = inventoryByKey.get(targetStorageKey(item));
      return {
        ...item,
        label: inventory?.label || item.label || item.value,
        meta: inventory?.meta || targetKindLabel(item.kind),
        detail: `${item.count} 次`,
      };
    })
    .sort((a, b) => (b.count - a.count) || (b.ts - a.ts))
    .slice(0, 4), [counts, inventoryByKey, isArchivedProjectTarget]);
  const manualMatch = useMemo(() => {
    const query = manualQuery.trim().toLowerCase();
    if (!query) return null;
    return allInventoryTargets.find((item) => [
      item.value,
      item.label,
      item.meta,
      item.detail,
    ].some((part) => String(part || '').toLowerCase().includes(query))) || null;
  }, [allInventoryTargets, manualQuery]);
  const manualHref = useMemo(() => {
    const query = manualQuery.trim();
    if (!query) return '';
    if (manualMatch) return targetHref(manualMatch);
    if (query.includes('/') || query.endsWith('.md')) return targetHref({ kind: 'card', value: query });
    return '';
  }, [manualMatch, manualQuery]);
  const openManualTarget = useCallback((event: FormEvent) => {
    event.preventDefault();
    if (manualHref) window.location.href = manualHref;
  }, [manualHref]);

  const renderRow = (item: HomeTarget, className = '') => (
    <a className={`home-row ${className}`.trim()} href={targetHref(item)} key={targetStorageKey(item)}>
      <strong>{item.label || item.value}</strong>
      <span>{item.meta}</span>
      <em>{item.detail}</em>
    </a>
  );

  return (
    <main className="app-home">
      <section className="home-shell">
        <header className="home-head">
          <div>
            <span className="home-kicker">Canvas Studio</span>
            <h1>按需工作台</h1>
            <p>只在需要空间判断时打开。</p>
          </div>
          <div className="home-head-side">
            <BoardLink />
            <span>on demand</span>
          </div>
        </header>
        {error && <div className="home-error">{error}</div>}
        <section className="home-launch">
          <div className="home-launch-copy">
            <span>Open</span>
            <h2>打开任务工作台</h2>
            <p>输入任务卡号或路径；没有现成画布时再进入生成。</p>
          </div>
          <form className="home-launch-form" onSubmit={openManualTarget}>
            <input
              value={manualQuery}
              onChange={(event) => setManualQuery(event.target.value)}
              placeholder="任务卡路径 / KMO-47 / KAN-109"
            />
            <button type="submit" disabled={!manualHref}>打开</button>
          </form>
          {manualQuery.trim() && !manualHref && (
            <div className="home-muted home-launch-hint">没有匹配到已有投影；粘贴任务卡路径可直接打开。</div>
          )}
        </section>
        <section className="home-activity-grid">
          <section className="home-section home-project-graph-entry">
            <div className="home-section-title">跨会话项目图</div>
            <a className="home-row home-row-quick" href={`${APP_BASE}?graph=1`}>
              <strong>Conversation Project Graph</strong>
              <span>分支 · 任务 · Markdown</span>
              <em>硬证据 / AI 归档分层</em>
            </a>
          </section>
          <section className="home-section home-resume">
            <div className="home-section-title">继续上次</div>
            <div className="home-list">
              {resumeTargets.length ? resumeTargets.map((item) => renderRow(item)) : (
                <div className="home-muted">暂无最近记录</div>
              )}
            </div>
          </section>
          <section className="home-section">
            <div className="home-section-title">常用直达</div>
            <div className="home-list">
              {frequentTargets.length ? frequentTargets.map((item) => renderRow(item, 'home-row-quick')) : (
                <div className="home-muted">暂无常用记录</div>
              )}
            </div>
          </section>
        </section>
        <section className="home-section home-section-all">
          <details className="home-fold home-fold-advanced">
            <summary>
              <span>高级：全部投影</span>
              <em>{allInventoryTargets.length}</em>
            </summary>
            <div className="home-advanced-body">
              <details className="home-fold">
                <summary>
                  <span>项目图</span>
                  <em>{projectTargets.length}</em>
                </summary>
                <div className="home-list">
                  {projectTargets.length ? projectTargets.map((item) => renderRow(item)) : (
                    <div className="home-muted">暂无 active task_family</div>
                  )}
                </div>
              </details>
              {archivedProjectTargets.length > 0 && <details className="home-fold">
                <summary>
                  <span>已归档项目</span>
                  <em>{archivedProjectTargets.length}</em>
                </summary>
                <div className="home-list">
                  {archivedProjectTargets.map((item) => renderRow(item))}
                </div>
              </details>}
              <details className="home-fold">
                <summary>
                  <span>对话地图</span>
                  <em>{conversationMaps.length}</em>
                </summary>
                <div className="home-list">
                  {conversationTargets.length ? conversationTargets.map((item) => renderRow(item)) : (
                    <div className="home-muted">暂无 conversation manifest</div>
                  )}
                </div>
              </details>
              <details className="home-fold">
                <summary>
                  <span>任务画布</span>
                  <em>{taskCanvasTargets.length}</em>
                </summary>
                <div className="home-list">
                  {taskCanvasTargets.length ? taskCanvasTargets.map((item) => renderRow(item)) : (
                    <div className="home-muted">暂无任务画布</div>
                  )}
                </div>
              </details>
            </div>
          </details>
        </section>
      </section>
    </main>
  );
}

export default function App() {
  const embedded = useMemo(() => new URLSearchParams(window.location.search).get('embedded') === '1', []);
  const embeddedProjectTitle = useMemo(() => new URLSearchParams(window.location.search).get('project_title')?.trim() || '', []);
  const showProjectGraph = useMemo(() => {
    return new URLSearchParams(window.location.search).get('graph') === '1';
  }, []);
  const convPath = useMemo(() => {
    return new URLSearchParams(window.location.search).get('conv')?.trim() || '';
  }, []);
  const target = useMemo<CanvasTarget | null>(() => {
    const params = new URLSearchParams(window.location.search);
    const map = params.get('map')?.trim();
    if (map) return { kind: 'map', value: map };
    const convmap = params.get('convmap')?.trim();
    if (convmap) return { kind: 'convmap', value: convmap };
    const path = params.get('path')?.trim();
    if (path) return { kind: 'card', value: path };
    return null;
  }, []);
  const targetLabel = target
    ? target.kind === 'map'
      ? target.value.startsWith('project:')
        ? `项目画布 · ${embeddedProjectTitle || target.value.slice('project:'.length)}`
        : `Project Map · ${target.value}`
      : target.kind === 'convmap'
        ? `Conversation Canvas · ${target.value}`
      : target.value
    : '';
  const isProjectMap = target?.kind === 'map';
  const isRealProjectMap = target?.kind === 'map' && target.value.startsWith('project:');
  const isConversationCanvas = target?.kind === 'convmap';
  const focusTaskId = useMemo(() => {
    return new URLSearchParams(window.location.search).get('focus')?.trim() || '';
  }, []);

  const canvas = useCanvasStore((state) => state.canvas);
  const canvasExists = useCanvasStore((state) => state.canvasExists);
  const loading = useCanvasStore((state) => state.loading);
  const dirty = useCanvasStore((state) => state.dirty);
  const saveStatus = useCanvasStore((state) => state.saveStatus);
  const saveError = useCanvasStore((state) => state.saveError);
  const error = useCanvasStore((state) => state.error);
  const loadFromApi = useCanvasStore((state) => state.loadFromApi);
  const saveToApi = useCanvasStore((state) => state.saveToApi);
  const generateFromApi = useCanvasStore((state) => state.generateFromApi);
  const refreshProjectMapFromApi = useCanvasStore((state) => state.refreshProjectMapFromApi);
  const addNode = useCanvasStore((state) => state.addNode);
  const [seedPanelOpen, setSeedPanelOpen] = useState(false);
  const [seedDraft, setSeedDraft] = useState('');
  const [seedBusy, setSeedBusy] = useState(false);
  const [seedStatus, setSeedStatus] = useState('');
  const [seedRunId, setSeedRunId] = useState('');
  const [executionBrief, setExecutionBrief] = useState<CanvasExecutionBrief | null>(null);
  const [seedOutcome, setSeedOutcome] = useState<'neutral' | 'failed' | 'usable' | 'skeleton'>('neutral');
  const [openedAt, setOpenedAt] = useState('');
  const [deltaOpen, setDeltaOpen] = useState(false);
  const [deltaBusy, setDeltaBusy] = useState(false);
  const [deltaError, setDeltaError] = useState('');
  const [deltaEntries, setDeltaEntries] = useState<LedgerEntry[]>([]);
  const [attentionCount, setAttentionCount] = useState(0);
  const [attention, setAttention] = useState<AttentionQueuePayload | null>(null);
  const [dialogueToast, setDialogueToast] = useState('');
  const [moreOpen, setMoreOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [versions, setVersions] = useState<ProjectMapVersion[]>([]);
  const [previewVersion, setPreviewVersion] = useState<ProjectMapVersion | null>(null);
  const [previewCanvas, setPreviewCanvas] = useState<Record<string, unknown> | null>(null);
  const [refreshSummary, setRefreshSummary] = useState('');
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [reorganizeRunId, setReorganizeRunId] = useState('');
  const [reorganizeStatus, setReorganizeStatus] = useState('');
  const [conflictOpen, setConflictOpen] = useState(false);
  const moreMenuRef = useRef<HTMLDivElement>(null);
  const moreMenuTriggerRef = useRef<HTMLButtonElement>(null);
  const dialoguePositionResolver = useRef<(() => XYPosition) | null>(null);
  const projectRef = isRealProjectMap ? (target?.value || '').slice('project:'.length) : '';

  useEffect(() => {
    if (!isRealProjectMap) return;
    void loadAttentionQueue(projectRef).then((payload) => {
      setAttention(payload);
      setAttentionCount(payload.counts.needs_you);
    }).catch(() => {
      setAttention(null);
      setAttentionCount(0);
    });
  }, [isRealProjectMap, projectRef]);

  useEffect(() => {
    if (target) {
      rememberTarget(target, targetLabel);
      setOpenedAt(new Date().toISOString());
      setDeltaOpen(false);
      setDeltaEntries([]);
      setDeltaError('');
      void loadFromApi(target);
    }
  }, [loadFromApi, target, targetLabel]);

  useEffect(() => {
    setSeedPanelOpen(false);
    setSeedDraft('');
    setSeedStatus('');
    setSeedRunId('');
    setExecutionBrief(null);
    setSeedOutcome('neutral');
    setReorganizeRunId('');
    setReorganizeStatus('');
  }, [target?.kind, target?.value]);

  useEffect(() => {
    if (!moreOpen) return undefined;

    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !moreMenuRef.current?.contains(event.target)) {
        setMoreOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setMoreOpen(false);
      moreMenuTriggerRef.current?.focus();
    };

    document.addEventListener('pointerdown', closeOnOutsidePointer);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [moreOpen]);

  useEffect(() => {
    if (!isRealProjectMap || !projectRef) return undefined;
    let cancelled = false;
    void loadActiveProjectCanvasReorganize(projectRef).then((run) => {
      if (cancelled || !run) return;
      setReorganizeRunId(String(run.id || ''));
      setReorganizeStatus(String(run.status || 'running'));
    }).catch(() => {
      // Queue visibility is supplementary; a transient read failure must not block manual reorganization.
    });
    return () => {
      cancelled = true;
    };
  }, [isRealProjectMap, projectRef]);

  const requestSeedIntent = useCallback(async (fallbackIntent = '') => {
    if (!target || target.kind !== 'card') return;
    setSeedPanelOpen(true);
    setSeedBusy(true);
    setSeedStatus(fallbackIntent ? '' : '意图推断中…');
    if (fallbackIntent) {
      setSeedDraft(fallbackIntent);
      setSeedBusy(false);
      return;
    }
    try {
      const payload = await seedIntent(target.value);
      if (payload.available === false) {
        setSeedDraft('');
        setExecutionBrief(null);
        setSeedStatus(String(payload.message || 'Demo 模式未配置 AI provider；此动作不可用。'));
        return;
      }
      const draft = String(payload.intent || payload.draft || '').trim();
      setSeedDraft(draft);
      setExecutionBrief(payload.execution_brief || null);
      setSeedStatus('');
    } catch (err) {
      setSeedStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setSeedBusy(false);
    }
  }, [target]);

  useEffect(() => {
    if (!target || target.kind !== 'card' || loading || !canvas || canvasExists) return;
    if (seedPanelOpen || seedDraft || seedBusy) return;
    void requestSeedIntent();
  }, [canvas, canvasExists, loading, requestSeedIntent, seedBusy, seedDraft, seedPanelOpen, target]);

  useEffect(() => {
    if (convPath) {
      rememberTarget({ kind: 'conv', value: convPath }, `Conversation Map · ${convPath}`);
    }
  }, [convPath]);

  const handleGenerate = useCallback(async () => {
    if (!target) return;
    if (target.kind === 'map') {
      await generateFromApi();
      await loadFromApi(target);
      return;
    }
    if (target.kind === 'card') {
      const existingIntent = canvasSeedIntent(canvas);
      if (existingIntent) {
        setSeedBusy(true);
        setSeedStatus('正在投递 merge seed…');
        try {
          const payload = await seedRun(target.value, existingIntent, 'codex');
          if (payload.available === false) {
            setSeedOutcome('neutral');
            setSeedStatus(String(payload.message || 'Demo 模式未配置 AI provider；此动作不可用。'));
            return;
          }
          setSeedRunId(String(payload.run_id || ''));
          setExecutionBrief(payload.execution_brief || null);
          const runStatus = String(payload.stage || 'running');
          const usable = runStatus === 'completed' && runIsUsable(payload);
          setSeedStatus(seedStageLabel(canvas, runStatus, usable));
          setSeedOutcome(seedOutcomeFor(runStatus, usable));
          await loadFromApi(target);
        } catch (err) {
          setSeedOutcome('failed');
          setSeedStatus(`生成失败（${err instanceof Error ? err.message : String(err)}） → 当前仅骨架，不可作为完成结果`);
        } finally {
          setSeedBusy(false);
        }
        return;
      }
    }
    await generateFromApi();
  }, [canvas, generateFromApi, loadFromApi, target]);

  const handleProjectRefresh = useCallback(async () => {
    if (!target || target.kind !== 'map') return;
    setRefreshBusy(true);
    try {
      const payload = await refreshProjectMapFromApi();
      if (!payload) return;
      const delta = payload.delta_summary && typeof payload.delta_summary === 'object'
        ? payload.delta_summary as Record<string, unknown>
        : {};
      const added = Number(delta.added_cards || 0);
      const removed = Number(delta.removed_cards || 0);
      setRefreshSummary(payload.unchanged === true
        ? '项目图已核对：任务卡无变化，已留更新前快照。'
        : `项目图已更新：新增 ${added} 张，移除 ${removed} 张。`);
    } finally {
      setRefreshBusy(false);
    }
  }, [refreshProjectMapFromApi, target]);

  const handleProjectReorganize = useCallback(async () => {
    if (!isRealProjectMap || !projectRef) return;
    setReorganizeStatus('starting');
    setRefreshSummary('');
    try {
      const payload = await startProjectCanvasReorganize(projectRef);
      setReorganizeRunId(String(payload.run_id || ''));
      setReorganizeStatus(String(payload.status || 'queued'));
    } catch (err) {
      setReorganizeRunId('');
      setReorganizeStatus('failed');
      setRefreshSummary(`重整失败：${err instanceof Error ? err.message : String(err)}。可重试。`);
    }
  }, [isRealProjectMap, projectRef]);

  useEffect(() => {
    if (!reorganizeRunId) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const run = await loadAiRunResult(reorganizeRunId);
        if (cancelled || !run) return;
        const status = String(run.status || 'running');
        setReorganizeStatus(status);
        if (status === 'completed') {
          setReorganizeRunId('');
          setRefreshSummary('重整完成，点击更新项目图查看');
        } else if (['error', 'timeout', 'killed'].includes(status)) {
          const detail = String(run.error || status);
          setReorganizeRunId('');
          setRefreshSummary(`重整失败：${detail}。可重试。`);
        }
      } catch (err) {
        if (!cancelled) {
          setReorganizeRunId('');
          setReorganizeStatus('failed');
          setRefreshSummary(`重整状态读取失败：${err instanceof Error ? err.message : String(err)}。可重试。`);
        }
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [reorganizeRunId]);

  const openHistory = useCallback(async () => {
    if (!target || target.kind !== 'map') return;
    setMoreOpen(false);
    setHistoryOpen(true);
    setHistoryBusy(true);
    setHistoryError('');
    setPreviewVersion(null);
    setPreviewCanvas(null);
    try {
      const payload = await listProjectMapVersions(target.value);
      setVersions(Array.isArray(payload.versions) ? payload.versions : []);
    } catch (err) {
      setVersions([]);
      setHistoryError(err instanceof Error ? err.message : String(err));
    } finally {
      setHistoryBusy(false);
    }
  }, [target]);

  const previewHistory = useCallback(async (version: ProjectMapVersion) => {
    if (!target || target.kind !== 'map') return;
    setHistoryBusy(true);
    setHistoryError('');
    try {
      const payload = await previewProjectMapVersion(target.value, version.id);
      setPreviewVersion(payload.version);
      setPreviewCanvas(payload.canvas);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : String(err));
    } finally {
      setHistoryBusy(false);
    }
  }, [target]);

  const restoreHistory = useCallback(async () => {
    if (!target || target.kind !== 'map' || !previewVersion) return;
    setHistoryBusy(true);
    setHistoryError('');
    try {
      const baseRev = useCanvasStore.getState().baseRev;
      await restoreProjectMapVersion(target.value, previewVersion.id, baseRev);
      await loadFromApi(target);
      setHistoryOpen(false);
      setDialogueToast('历史版本已恢复；恢复前状态也已留快照');
      window.setTimeout(() => setDialogueToast(''), 3500);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : String(err));
    } finally {
      setHistoryBusy(false);
    }
  }, [loadFromApi, previewVersion, target]);

  const exportCanvas = useCallback(() => {
    if (!canvas) return;
    const blob = new Blob([`${JSON.stringify(canvas, null, 2)}\n`], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${canvas.id || 'canvas'}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setMoreOpen(false);
  }, [canvas]);

  const handleSeedRun = useCallback(async () => {
    if (!target || target.kind !== 'card') return;
    const intent = seedDraft.trim();
    if (!intent) {
      setSeedStatus('请先确认一句意图');
      return;
    }
    setSeedBusy(true);
    setSeedStatus('正在投递 AI 队列…');
    try {
      const payload = await seedRun(target.value, intent, 'codex');
      if (payload.available === false) {
        setSeedOutcome('neutral');
        setSeedStatus(String(payload.message || 'Demo 模式未配置 AI provider；此动作不可用。'));
        return;
      }
      setSeedRunId(String(payload.run_id || ''));
      setExecutionBrief(payload.execution_brief || executionBrief);
      const runStatus = String(payload.stage || 'running');
      const usable = runStatus === 'completed' && runIsUsable(payload);
      setSeedStatus(seedStageLabel(canvas, runStatus, usable));
      setSeedOutcome(seedOutcomeFor(runStatus, usable));
      await loadFromApi(target);
    } catch (err) {
      setSeedOutcome('failed');
      setSeedStatus(`生成失败（${err instanceof Error ? err.message : String(err)}） → 当前仅骨架，不可作为完成结果`);
    } finally {
      setSeedBusy(false);
    }
  }, [canvas, executionBrief, loadFromApi, seedDraft, target]);

  useEffect(() => {
    if (!target || target.kind !== 'card' || !seedRunId) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const payload = await aiResults(target.value);
        const results = Array.isArray(payload.results) ? payload.results as Array<Record<string, unknown>> : [];
        const run = results.find((item) => String(item.run_id || '') === seedRunId);
        const runStatus = String(run?.status || 'running');
        const usable = runStatus === 'completed' && runIsUsable(run);
        await loadFromApi(target);
        if (cancelled) return;
        const latestCanvas = useCanvasStore.getState().canvas;
        const label = seedStageLabel(latestCanvas, runStatus, usable);
        setSeedStatus(label);
        setSeedOutcome(seedOutcomeFor(runStatus, usable));
        const counts = canvasSeedSummaryCounts(latestCanvas);
        const summaryDone = counts.total === 0 || counts.pending === 0;
        if (summaryDone && ['completed', 'error', 'timeout', 'killed'].includes(runStatus)) {
          setSeedRunId('');
        }
      } catch (err) {
        if (!cancelled) setSeedStatus(err instanceof Error ? err.message : String(err));
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadFromApi, seedRunId, target]);

  const handleEmptyCanvas = useCallback(async () => {
    await saveToApi();
    setSeedPanelOpen(false);
    setSeedStatus('');
  }, [saveToApi]);

  const openDeltaPanel = useCallback(async () => {
    if (!target || target.kind !== 'card') return;
    const nextOpen = !deltaOpen;
    setDeltaOpen(nextOpen);
    if (!nextOpen) return;
    setDeltaBusy(true);
    setDeltaError('');
    try {
      const payload = await loadLedger(target.value, openedAt);
      setDeltaEntries(Array.isArray(payload.entries) ? payload.entries : []);
    } catch (err) {
      setDeltaEntries([]);
      setDeltaError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeltaBusy(false);
    }
  }, [deltaOpen, openedAt, target]);

  const [railTab, setRailTab] = useState<CanvasRailTab | null>(isRealProjectMap ? 'cards' : null);
  const [lastRailTab, setLastRailTab] = useState<CanvasRailTab>('cards');

  const toggleRailTab = useCallback((tab: CanvasRailTab) => {
    setLastRailTab(tab);
    setRailTab((current) => current === tab ? null : tab);
  }, []);

  const toggleRailCollapsed = useCallback(() => {
    setRailTab((current) => current ? null : lastRailTab);
  }, [lastRailTab]);

  const openAttention = useCallback(() => {
    setLastRailTab('cards');
    setRailTab('cards');
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        document.querySelector('[data-attention-section="true"]')?.scrollIntoView({ block: 'start' });
      });
    });
  }, []);

  const addNoteNode = useCallback(() => {
    addNode({
      id: createId('note'),
      type: 'note',
      position: { x: 140, y: 140 },
      data: { content: '', isNew: true },
    });
  }, [addNode]);

  const addLinkNode = useCallback(() => {
    addNode({
      id: createId('link'),
      type: 'link',
      position: { x: 240, y: 240 },
      data: { title: 'example.com', url: 'https://example.com', status: 'valid' },
    });
  }, [addNode]);

  const addDialogueNode = useCallback(async () => {
    if (!canvas || !isRealProjectMap) return;
    const activeCards = attention
      ? [...attention.needs_you, ...attention.processing, ...attention.planned]
      : [];
    const pointerPackage = buildDialoguePointerPackage({
      projectRef,
      projectTitle: embeddedProjectTitle || projectRef,
      canvas,
      activeCards,
    });
    try {
      await copyTextWithFallback(pointerPackage);
    } catch {
      setDialogueToast('复制失败，请检查剪贴板权限');
      return;
    }
    const existing = canvas.nodes || [];
    let position = dialoguePositionResolver.current?.() || { x: 140, y: 140 };
    while (existing.some((node) => (
      Math.abs(Number(node.position?.x || 0) - position.x) < 120
      && Math.abs(Number(node.position?.y || 0) - position.y) < 90
    ))) {
      position = { x: position.x + 36, y: position.y + 36 };
    }
    addNode({
      id: createId('dialogue-note'),
      type: 'note',
      position,
      data: {
        label: '对话·待接续',
        dialogue_status: '对话·待接续',
        dialogue_created_at: new Date().toISOString(),
        conversation_id: '',
        dialogue_outcome: '',
      },
    });
    await saveToApi();
    setDialogueToast('已复制，去 Codex/Claude 开聊');
    window.setTimeout(() => setDialogueToast(''), 3000);
  }, [addNode, attention, canvas, embeddedProjectTitle, isRealProjectMap, projectRef, saveToApi]);

  const projectMapEmpty = isProjectMap && !canvasExists;
  const projectMapActionLabel = projectMapEmpty ? '生成画布' : '更新项目图';
  const saveStatusLabel = saveStatus === 'saving'
    ? '保存中…'
    : saveStatus === 'failed'
      ? '保存失败 · 点击重试'
      : saveStatus === 'conflict'
        ? '存在版本冲突'
        : '已保存';
  const reorganizeRunning = Boolean(reorganizeRunId) || reorganizeStatus === 'starting';
  const projectStatusLabel = reorganizeRunning
    ? `重整中… · ${saveStatusLabel}`
    : `${saveStatusLabel}${dirty && saveStatus === 'saved' ? ' · 待保存' : ''}`;

  if (showProjectGraph) {
    return <ConversationProjectGraphView />;
  }

  if (convPath) {
    return <ConversationMapView manifestPath={convPath} />;
  }

  if (!target) {
    return <Home />;
  }

  return (
    <main className={`app${embedded ? ' app-embedded' : ''}`}>
      <header className={`topbar${isProjectMap ? ' topbar-project' : ''}`}>
        <div className="topbar-title">
          <strong>{isRealProjectMap ? 'Project Canvas' : 'Canvas Studio'}</strong>
          <span>{targetLabel}</span>
        </div>
        <nav className="topbar-actions" aria-label="内容与注意力工具">
          {!embedded && <BoardLink />}
          {isRealProjectMap && <button
            type="button"
            className={`attention-badge${attentionCount > 0 ? ' has-attention' : ''}`}
            onClick={openAttention}
          >
            需要你 {attentionCount}
          </button>}
          {isRealProjectMap && <SystemAlertBadge />}
          {isRealProjectMap && <a className="dispatch-link" href="/?new_task=1" target="_top">＋ 派活</a>}
          {isRealProjectMap && <span className="topbar-divider" aria-hidden="true" />}
          {(['cards', 'files', 'nodes'] as CanvasRailTab[]).map((tab) => (
            <button
              type="button"
              className={`rail-tab-toggle${railTab === tab ? ' is-active' : ''}`}
              aria-pressed={railTab === tab}
              onClick={() => toggleRailTab(tab)}
              disabled={!canvas || loading || projectMapEmpty}
              key={tab}
            >
              {tab === 'cards' ? '卡片' : tab === 'files' ? '文件' : '节点'}
            </button>
          ))}
          <span className="topbar-divider" aria-hidden="true" />
          <button type="button" onClick={addNoteNode} disabled={!canvas || loading || projectMapEmpty}>
            笔记
          </button>
          <button type="button" onClick={addLinkNode} disabled={!canvas || loading || projectMapEmpty}>
            Link
          </button>
          <button
            type="button"
            onClick={() => void addDialogueNode()}
            disabled={!canvas || loading || !isRealProjectMap || isConversationCanvas}
            title={isConversationCanvas ? '对话节点暂不支持：Conversation Map 节点锚定协议另议' : undefined}
          >
            对话
          </button>
          {!embedded && <button
            type="button"
            onClick={() => void requestSeedIntent(canvasSeedIntent(canvas))}
            disabled={!canvas || loading || isProjectMap || isConversationCanvas || seedBusy}
          >
            按意图生成
          </button>}
          {!embedded && <button type="button" onClick={() => void openDeltaPanel()} disabled={!canvas || loading || target.kind !== 'card'}>
            变更{deltaOpen ? ' ◂' : ''}
          </button>}
          {!isProjectMap && <button
            type="button"
            className={`save-status save-status-${saveStatus}`}
            onClick={saveStatus === 'failed' ? () => void saveToApi() : saveStatus === 'conflict' ? () => setConflictOpen(true) : undefined}
            disabled={!['failed', 'conflict'].includes(saveStatus)}
            title={saveStatus === 'conflict' ? saveError || '本地改动已保留；需人工处理版本冲突。' : undefined}
            aria-live="polite"
          >
            {saveStatusLabel}{dirty && saveStatus === 'saved' ? ' · 待保存' : ''}
          </button>}
          {!embedded && !isProjectMap && <button type="button" onClick={() => void handleGenerate()} disabled={loading}>
            补全生成
          </button>}
        </nav>
        {isProjectMap && <div className="canvas-action-group" role="group" aria-label="全画布动作">
          <button
            type="button"
            className={`save-status save-status-${saveStatus}`}
            onClick={saveStatus === 'failed' ? () => void saveToApi() : saveStatus === 'conflict' ? () => setConflictOpen(true) : undefined}
            disabled={!['failed', 'conflict'].includes(saveStatus)}
            title={saveStatus === 'conflict' ? saveError || '本地改动已保留；需人工处理版本冲突。' : undefined}
            aria-live="polite"
          >
            {projectStatusLabel}
          </button>
          <div className="more-menu-shell" ref={moreMenuRef}>
            <button
              type="button"
              ref={moreMenuTriggerRef}
              className="more-menu-trigger"
              aria-label="更多画布操作"
              aria-haspopup="menu"
              aria-expanded={moreOpen}
              aria-controls={moreOpen ? 'canvas-more-menu' : undefined}
              onClick={() => setMoreOpen((value) => !value)}
            >⋯</button>
            {moreOpen && <div className="more-menu" id="canvas-more-menu" role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMoreOpen(false);
                  void (projectMapEmpty ? handleGenerate() : handleProjectRefresh());
                }}
                disabled={loading || refreshBusy || saveStatus === 'conflict'}
              >
                {projectMapActionLabel}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMoreOpen(false);
                  void handleProjectReorganize();
                }}
                disabled={!isRealProjectMap || !projectRef || loading || reorganizeRunning}
                title={isRealProjectMap && projectRef ? '运行探索树重整（分钟级 AI 运行）' : '仅真实项目图支持 AI 重整'}
              >
                AI 重整
              </button>
              <div className="more-menu-separator" role="separator" />
              <button type="button" role="menuitem" onClick={() => { setMoreOpen(false); setRefreshSummary((value) => value || '尚未执行本次更新。'); }}>查看更新内容</button>
              <button type="button" role="menuitem" onClick={() => void openHistory()}>恢复历史版本</button>
              <button type="button" role="menuitem" onClick={() => { setMoreOpen(false); void handleProjectRefresh(); }}>仅同步任务卡</button>
              <button type="button" role="menuitem" onClick={exportCanvas}>导出画布</button>
            </div>}
          </div>
        </div>}
      </header>
      {dialogueToast && <div className="dialogue-toast" role="status">{dialogueToast}</div>}
      {refreshSummary && <div className="refresh-summary" role="status">
        <span>{refreshSummary}</span>
        <button type="button" aria-label="关闭更新摘要" onClick={() => setRefreshSummary('')}>×</button>
      </div>}
      {error && <div className="error-banner">{error}</div>}
      {conflictOpen && <div className="history-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setConflictOpen(false); }}>
        <section className="conflict-dialog" role="dialog" aria-modal="true" aria-label="画布版本冲突">
          <span>LOCAL CHANGES PAUSED</span>
          <h2>存在版本冲突</h2>
          <p>{saveError || '服务端画布已经变化。你的本地构图仍留在当前页面，自动保存不会继续覆盖。'}</p>
          <div>
            <button type="button" onClick={exportCanvas}>导出本地副本</button>
            <button type="button" className="danger-confirm" onClick={() => { setConflictOpen(false); void loadFromApi(target); }}>放弃本地并重载</button>
            <button type="button" onClick={() => setConflictOpen(false)}>暂不处理</button>
          </div>
        </section>
      </div>}
      {historyOpen && isProjectMap && <div className="history-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setHistoryOpen(false); }}>
        <section className="history-dialog" role="dialog" aria-modal="true" aria-label="恢复历史版本">
          <header>
            <div><span>PROJECT CANVAS / VERSIONS</span><h2>恢复历史版本</h2></div>
            <button type="button" aria-label="关闭" onClick={() => setHistoryOpen(false)}>×</button>
          </header>
          <div className="history-body">
            <ol className="history-version-list">
              {historyBusy && versions.length === 0 && <li className="history-empty">读取中…</li>}
              {!historyBusy && versions.length === 0 && <li className="history-empty">暂无历史快照</li>}
              {versions.map((version) => <li key={version.id}>
                <button type="button" className={previewVersion?.id === version.id ? 'is-active' : ''} onClick={() => void previewHistory(version)}>
                  <strong>{new Date(version.created_at).toLocaleString('zh-CN', { hour12: false })}</strong>
                  <span>{version.node_count} 节点 · {version.edge_count} 连线</span>
                </button>
              </li>)}
            </ol>
            <div className="history-preview">
              {historyError && <p className="history-error">{historyError}</p>}
              {!previewVersion && !historyError && <div className="history-empty">选择左侧版本查看预览</div>}
              {previewVersion && <>
                <div className="history-preview-head"><strong>{previewVersion.node_count} 节点 / {previewVersion.edge_count} 连线</strong><code>{previewVersion.canvas_rev.slice(0, 10)}</code></div>
                <ul>
                  {((previewCanvas?.nodes as Array<Record<string, unknown>> | undefined) || []).slice(0, 12).map((node) => {
                    const data = node.data && typeof node.data === 'object' ? node.data as Record<string, unknown> : {};
                    return <li key={String(node.id)}><span>{String(node.type || 'node')}</span>{String(data.title || data.label || data.text || node.id)}</li>;
                  })}
                </ul>
                <button type="button" className="history-restore" disabled={historyBusy} onClick={() => void restoreHistory()}>{historyBusy ? '恢复中…' : '恢复这个版本'}</button>
              </>}
            </div>
          </div>
        </section>
      </div>}
      {deltaOpen && target.kind === 'card' && (
        <section className="delta-panel" aria-label="Changes since open">
          <div className="delta-panel-head">
            <strong>自本次打开以来</strong>
            <span>{openedAt || 'unknown'}</span>
          </div>
          {deltaBusy && <div className="delta-empty">读取中...</div>}
          {deltaError && <div className="delta-empty">{deltaError}</div>}
          {!deltaBusy && !deltaError && deltaEntries.length === 0 && <div className="delta-empty">暂无新记录</div>}
          {!deltaBusy && !deltaError && groupLedgerByActor(deltaEntries).map(([actor, entries]) => (
            <div className="delta-actor" key={actor}>
              <div className="delta-actor-title">{actor} · {entries.length}</div>
              <ol>
                {entries.slice(-6).reverse().map((entry, idx) => (
                  <li key={`${actor}:${entry.ts || ''}:${entry.event}:${idx}`}>
                    <strong>{entry.event || entry.kind || 'event'}</strong>
                    <span>{entry.ts || ''}</span>
                    {entry.summary && <em>{entry.summary}</em>}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </section>
      )}
      {target.kind === 'card' && seedPanelOpen && (
        <section className={`seed-intent-bar seed-outcome-${seedOutcome}`} aria-label="Canvas seed intent">
          <div className="seed-raw-intent">
            <label htmlFor="seed-raw-intent">你的意图（执行时原样保存）</label>
            <textarea
              id="seed-raw-intent"
              value={seedDraft}
              onChange={(event) => setSeedDraft(event.target.value)}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') void handleSeedRun();
                if (event.key === 'Escape' && canvasExists) setSeedPanelOpen(false);
              }}
              placeholder={seedBusy ? '意图推断中…' : '写下这张画布真正要解决什么'}
            />
          </div>
          <div className="seed-execution-brief" aria-label="系统执行理解">
            <div><strong>系统执行理解</strong><p>{executionBrief?.understanding || executionBrief?.goal || '等待系统形成执行理解；不会用改写覆盖你的原话。'}</p></div>
            <div><strong>来源</strong><p>{briefSources(executionBrief).join(' · ') || '待确认'}</p></div>
            <div><strong>动作</strong><p>{asBriefList(executionBrief?.actions).join(' · ') || '待确认'}</p></div>
            <div><strong>交付</strong><p>{executionBrief?.delivery || executionBrief?.deliverable || '待确认'}</p></div>
            <div><strong>完成门</strong><p>{asBriefList(executionBrief?.completion_gate).join(' · ') || '必须运行 completed 且质量/usable 明确通过'}</p></div>
          </div>
          <div className="seed-actions">
            <button type="button" onClick={() => void handleSeedRun()} disabled={seedBusy || !seedDraft.trim()}>按此执行</button>
            <button type="button" onClick={() => void handleEmptyCanvas()} disabled={seedBusy || loading || canvasExists}>空画布</button>
            {canvasExists && <button type="button" onClick={() => setSeedPanelOpen(false)} disabled={seedBusy}>收起</button>}
          </div>
          {seedStatus && (
            <div className="seed-stage-badges" aria-label="Seed stages">
              {seedStatus.split(' → ').map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          )}
        </section>
      )}
      <section className={`stage${railTab ? ' stage-rail-open' : ''}`}>
        {canvas && !projectMapEmpty && !railTab && isRealProjectMap && (
          <button type="button" className="rail-expand-handle" aria-label="展开右栏" title="展开右栏" onClick={toggleRailCollapsed}>‹</button>
        )}
        {loading && !canvas ? <div className="loading">Loading...</div> : projectMapEmpty ? (
          <div className="project-map-empty">
            <div>
              <span>Project Canvas</span>
              <h1>这张项目画布尚未生成</h1>
              <p>{targetLabel} 目前只有纯读空态；点击生成后才会写入 kanban 画布投影。</p>
            </div>
            <button type="button" onClick={() => void handleGenerate()} disabled={loading}>
              {loading ? '生成中...' : '生成画布'}
            </button>
          </div>
        ) : <Canvas
          onSave={saveToApi}
          focusTaskId={focusTaskId}
          onPositionResolver={(resolver) => { dialoguePositionResolver.current = resolver; }}
        />}
        {canvas && !projectMapEmpty && railTab && (
          <CanvasRail
            tab={railTab}
            onCollapse={toggleRailCollapsed}
            onPersist={saveToApi}
            disabled={loading}
            projectRef={projectRef}
          />
        )}
      </section>
    </main>
  );
}
