import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Node } from 'reactflow';
import { linkProjectConversation, loadAttentionQueue, loadLedger, loadProjectMaterials, openProjectMaterial, openSource, unlinkProjectConversation } from '../services/canvasApi';
import type { AttentionQueuePayload } from '../services/canvasApi';
import type { LedgerEntry, ProjectConversationMaterial } from '../services/canvasApi';
import { useCanvasStore } from '../store/canvasStore';
import { CARD_DRAG_MIME, FILE_REF_DRAG_MIME } from './dragTypes';
import { deriveRefDisplayTitle, refHoverTitle } from './refDisplay';

export type CanvasRailTab = 'nodes' | 'files' | 'cards';

interface CanvasRailProps {
  tab: CanvasRailTab;
  onCollapse: () => void;
  onPersist: () => Promise<unknown>;
  disabled?: boolean;
  projectRef?: string;
}

interface CanvasTaskRecord {
  task_id?: string;
  title?: string;
  project?: string;
  project_ref?: string;
  status?: string;
  path?: string;
  workdir?: string;
  source_path?: string;
  landing_page?: string;
  related_paths?: unknown;
  frontmatter?: Record<string, unknown>;
}

interface SearchCard {
  task_id: string;
  title: string;
  path: string;
  project: string;
  project_ref: string;
  status: string;
}

interface FileLibraryEntry {
  id: string;
  kind: string;
  path: string;
  title: string;
  summary: string;
  source: string;
}

interface ConversationDraft {
  kind: ProjectConversationMaterial['kind'];
  conversationId: string;
  title: string;
  path: string;
  role: 'manifest' | 'unexpanded' | 'rollout' | 'pointer';
}

const EMPTY_CONVERSATION_DRAFT: ConversationDraft = {
  kind: 'codex',
  conversationId: '',
  title: '',
  path: '',
  role: 'rollout',
};

function draftFromConversation(conversation: ProjectConversationMaterial): ConversationDraft {
  const asset = conversation.assets[0];
  return {
    kind: conversation.kind,
    conversationId: conversation.conversation_id,
    title: conversation.title,
    path: asset?.path || '',
    role: conversation.kind === 'claude-science' ? 'pointer' : asset?.role || 'rollout',
  };
}

const GROUP_ORDER = ['manual', 'generated', 'reference', 'ai_material', 'other'] as const;
type RailGroupKey = (typeof GROUP_ORDER)[number];

const GROUP_LABEL: Record<RailGroupKey, string> = {
  manual: '我放的',
  generated: 'AI 生成',
  reference: '引用',
  ai_material: 'AI 材料',
  other: '其它',
};

function nodeData(node: Node): Record<string, unknown> {
  return node.data && typeof node.data === 'object' ? node.data as Record<string, unknown> : {};
}

function sourceRef(node: Node): Record<string, unknown> | null {
  const ref = nodeData(node).source_ref;
  return ref && typeof ref === 'object' ? ref as Record<string, unknown> : null;
}

function nodeHidden(node: Node): boolean {
  return Boolean(node.hidden || nodeData(node).hidden);
}

function nodeTitle(node: Node): string {
  const data = nodeData(node);
  if (node.type === 'ref') return deriveRefDisplayTitle(data, node.id);
  const raw = data.title || data.label || data.content || data.url || node.id;
  return String(raw || node.id).replace(/\s+/g, ' ').trim() || node.id;
}

function nodeHoverTitle(node: Node): string {
  const data = nodeData(node);
  if (node.type === 'ref') return refHoverTitle(data, nodeTitle(node));
  return nodeTitle(node);
}

function nodeSummary(node: Node): string {
  const data = nodeData(node);
  const ref = sourceRef(node);
  const raw = node.type === 'ref'
    ? data.summary || data.relation_note || data.content || ''
    : data.summary || data.relation_note || ref?.path || ref?.resolved_path || data.content || '';
  return String(raw || '').replace(/\s+/g, ' ').trim();
}

function nodeTypeLabel(node: Node): string {
  if (node.type === 'ref') return '引用';
  if (node.type === 'dialogue') return '对话';
  if (node.type === 'link') return '链接';
  return '笔记';
}

function ledgerActorsByNode(entries: LedgerEntry[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  entries.forEach((entry) => {
    const raw = entry.raw && typeof entry.raw === 'object' ? entry.raw as Record<string, unknown> : {};
    const nodeId = String(raw.node_id || '').trim();
    const actor = String(entry.actor || raw.actor || '').trim().toLowerCase();
    if (!nodeId || !actor) return;
    map.set(nodeId, [...(map.get(nodeId) || []), actor]);
  });
  return map;
}

function includesAny(value: string, needles: string[]): boolean {
  return needles.some((needle) => value.includes(needle));
}

function isAtomicMaterialPath(value: unknown): boolean {
  const path = String(value || '');
  return path.includes('/facts/fact-ledger.jsonl') || path.endsWith('facts/fact-ledger.jsonl');
}

function isAtomicMaterialNode(node: Node): boolean {
  const data = nodeData(node);
  const ref = sourceRef(node);
  const role = data.metadata && typeof data.metadata === 'object'
    ? String((data.metadata as Record<string, unknown>).role || '')
    : '';
  return (
    String(node.id || '').startsWith('fact-') ||
    role === 'fact' ||
    isAtomicMaterialPath(ref?.path) ||
    isAtomicMaterialPath(ref?.resolved_path)
  );
}

function classifyNode(node: Node, actors: string[]): RailGroupKey {
  if (isAtomicMaterialNode(node)) return 'ai_material';
  const data = nodeData(node);
  const origin = String(data.origin || data.actor || data.created_by || '').trim().toLowerCase();
  const actorText = actors.join(' ');
  const hasRef = Boolean(sourceRef(node));
  const hasDialoguePointer = Boolean(data.run_id || data.forked_from);
  if (hasRef || hasDialoguePointer) return 'reference';
  if (includesAny(`${origin} ${actorText}`, ['manual', 'owner', 'user'])) return 'manual';
  if (includesAny(`${origin} ${actorText}`, ['generate', 'generated', 'seed', 'ai', 'claude', 'codex'])) return 'generated';
  return 'other';
}

function basename(value: string): string {
  const text = value.trim().replace(/\/+$/, '');
  if (!text) return '';
  if (/^https?:\/\//i.test(text)) {
    try {
      const url = new URL(text);
      return decodeURIComponent(url.pathname.split('/').filter(Boolean).pop() || url.hostname);
    } catch {
      return text.replace(/^https?:\/\//i, '').split('/')[0] || text;
    }
  }
  return text.split('/').filter(Boolean).pop() || text;
}

function kindForPath(path: string, preferred = ''): string {
  const cleanPreferred = preferred.trim();
  if (cleanPreferred) return cleanPreferred;
  if (/^https?:\/\//i.test(path)) return 'url';
  if (path.endsWith('/')) return 'dir';
  return 'file';
}

function kindLabel(kind: string): string {
  if (kind === 'dir') return '目录';
  if (kind === 'url') return '链接';
  if (kind === 'card') return '卡片';
  return '文件';
}

function normalizePath(path: string): string {
  return path.trim().replace(/\/+$/, '');
}

function entryKey(entry: Pick<FileLibraryEntry, 'kind' | 'path'>): string {
  return `${entry.kind}:${normalizePath(entry.path)}`;
}

function makeEntry(pathValue: unknown, source: string, options: Partial<FileLibraryEntry> = {}): FileLibraryEntry | null {
  const path = String(pathValue || '').trim();
  if (!path || isAtomicMaterialPath(path)) return null;
  const kind = kindForPath(path, String(options.kind || ''));
  if (!['file', 'dir', 'url'].includes(kind)) return null;
  const title = basename(path);
  const entry: FileLibraryEntry = {
    id: String(options.id || `${kind}:${normalizePath(path)}`),
    kind,
    path,
    title: title || String(options.title || path),
    summary: String(options.summary || '').replace(/\s+/g, ' ').trim(),
    source,
  };
  return entry;
}

function frontmatterList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item || '').trim()).filter(Boolean);
  if (typeof value === 'string' && value.trim()) return [value.trim()];
  return [];
}

function metadataFileLibrary(canvas: ReturnType<typeof useCanvasStore.getState>['canvas']): FileLibraryEntry[] {
  const raw = canvas?.metadata && typeof canvas.metadata === 'object'
    ? (canvas.metadata as Record<string, unknown>).file_library
    : null;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => {
      if (!item || typeof item !== 'object') return null;
      const record = item as Record<string, unknown>;
      return makeEntry(record.path, String(record.source || 'rail'), {
        id: String(record.id || ''),
        kind: String(record.kind || ''),
        title: String(record.title || ''),
        summary: String(record.summary || ''),
      });
    })
    .filter((entry): entry is FileLibraryEntry => Boolean(entry));
}

function dedupeEntries(entries: FileLibraryEntry[]): FileLibraryEntry[] {
  const byKey = new Map<string, FileLibraryEntry>();
  entries.forEach((entry) => {
    const key = entryKey(entry);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, entry);
      return;
    }
    byKey.set(key, {
      ...existing,
      summary: existing.summary || entry.summary,
      source: existing.source.includes(entry.source) ? existing.source : `${existing.source}, ${entry.source}`,
    });
  });
  return Array.from(byKey.values()).sort((a, b) => a.title.localeCompare(b.title, 'zh-Hans-CN'));
}

function serializableFileLibrary(entries: FileLibraryEntry[]): Record<string, unknown>[] {
  return entries.map((entry) => ({
    id: entry.id,
    kind: entry.kind,
    path: entry.path,
    title: entry.title,
    summary: entry.summary,
    source: entry.source,
  }));
}

function fileEntriesFromTask(task: CanvasTaskRecord | null): FileLibraryEntry[] {
  if (!task) return [];
  const fm = task.frontmatter && typeof task.frontmatter === 'object' ? task.frontmatter : {};
  const related = frontmatterList(task.related_paths || fm.related_paths);
  return [
    makeEntry(task.workdir || fm.workdir, 'workdir', { kind: 'dir' }),
    makeEntry(task.source_path || fm.source_path, 'source_path'),
    makeEntry(task.landing_page || fm.landing_page, 'landing_page'),
    ...related.map((path, idx) => makeEntry(path, 'related_paths', { id: `related:${idx}:${path}` })),
  ].filter((entry): entry is FileLibraryEntry => Boolean(entry));
}

function fileEntriesFromNodes(nodes: Node[]): FileLibraryEntry[] {
  return nodes
    .filter((node) => node.type === 'ref' && !isAtomicMaterialNode(node))
    .map((node) => {
      const ref = sourceRef(node);
      if (!ref) return null;
      const data = nodeData(node);
      const path = String(ref.path || ref.resolved_path || '').trim();
      return makeEntry(path, 'canvas_ref', {
        id: `node:${node.id}`,
        kind: String(ref.kind || data.kind || ''),
        summary: String(data.summary || ''),
      });
    })
    .filter((entry): entry is FileLibraryEntry => Boolean(entry));
}

function extractDroppedPaths(event: React.DragEvent): FileLibraryEntry[] {
  const entries: FileLibraryEntry[] = [];
  const text = [
    event.dataTransfer.getData('text/uri-list'),
    event.dataTransfer.getData('text/plain'),
  ].join('\n');
  text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
    .forEach((line) => {
      if (line.startsWith('/') || line.startsWith('~/') || /^https?:\/\//i.test(line)) {
        const entry = makeEntry(line, 'rail');
        if (entry) entries.push(entry);
      }
    });

  Array.from(event.dataTransfer.items || []).forEach((item) => {
    if (item.kind !== 'file') return;
    const file = item.getAsFile();
    if (!file) return;
    const withEntry = item as DataTransferItem & {
      webkitGetAsEntry?: () => { isDirectory?: boolean } | null;
    };
    const entry = makeEntry(file.name, 'rail', { kind: withEntry.webkitGetAsEntry?.()?.isDirectory ? 'dir' : 'file' });
    if (entry) entries.push(entry);
  });
  return dedupeEntries(entries);
}

function cardMatchesProject(card: SearchCard, projectRef: string): boolean {
  const target = projectRef.trim().toLowerCase();
  return Boolean(target) && [card.project_ref, card.project].some((value) => value.trim().toLowerCase() === target);
}

function cardDragStart(event: React.DragEvent, card: SearchCard) {
  event.dataTransfer.setData(CARD_DRAG_MIME, JSON.stringify(card));
  event.dataTransfer.effectAllowed = 'copy';
}

function cardRow(card: SearchCard, cardsOnCanvas: Set<string>) {
  const isOnCanvas = cardsOnCanvas.has(card.path);
  return (
    <div
      className={`rail-card-result${isOnCanvas ? ' is-on-canvas' : ''}`}
      key={card.path}
      title={card.path}
      draggable
      onDragStart={(event) => cardDragStart(event, card)}
    >
      <b>{card.task_id}</b>
      <span>{card.title}</span>
      <em className="rail-card-status">{card.status || '未知状态'}</em>
      {isOnCanvas && <i className="rail-card-on-canvas">已入图</i>}
    </div>
  );
}

function CardSearch({ children, projectRef }: { children: React.ReactNode; projectRef: string }) {
  const canvas = useCanvasStore((state) => state.canvas);
  const [query, setQuery] = useState('');
  const [cards, setCards] = useState<SearchCard[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    fetch('/api/data')
      .then((response) => {
        if (!response.ok) throw new Error(`搜索加载失败 (${response.status})`);
        return response.json();
      })
      .then((payload) => {
        if (!alive) return;
        const tasks = Array.isArray(payload?.tasks) ? payload.tasks as CanvasTaskRecord[] : [];
        setCards(tasks
          .filter((task) => task.task_id && task.path)
          .map((task) => ({
            task_id: String(task.task_id),
            title: String(task.title || task.task_id),
            path: String(task.path),
            project: String(task.project || ''),
            project_ref: String(task.project_ref || ''),
            status: String(task.status || ''),
          })));
      })
      .catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { alive = false; };
  }, []);

  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const results = useMemo(() => {
    if (!terms.length) return [];
    return cards
      .filter((card) => {
        const text = [card.task_id, card.title, card.project, card.project_ref, card.status].join(' ').toLowerCase();
        return terms.every((term) => text.includes(term));
      })
      .sort((left, right) => {
        const exact = Number(right.task_id.toLowerCase() === query.trim().toLowerCase())
          - Number(left.task_id.toLowerCase() === query.trim().toLowerCase());
        return exact || left.task_id.localeCompare(right.task_id, undefined, { numeric: true });
      })
      .slice(0, 40);
  }, [cards, query, terms]);
  const projectCards = useMemo(() => cards
    .filter((card) => cardMatchesProject(card, projectRef))
    .sort((left, right) => left.task_id.localeCompare(right.task_id, undefined, { numeric: true })), [cards, projectRef]);
  const closedCards = projectCards.filter((card) => ['done', 'archived'].includes(card.status.toLowerCase()));
  const openCards = projectCards.filter((card) => !['done', 'archived'].includes(card.status.toLowerCase()));
  const cardsOnCanvas = useMemo(() => new Set((canvas?.nodes || []).flatMap((node) => {
    const ref = sourceRef(node);
    return ref?.kind === 'card' && ref.path ? [String(ref.path)] : [];
  })), [canvas?.nodes]);

  return (
    <section className="rail-card-search" aria-label="全局卡片搜索">
      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="全局搜索卡号或标题…"
        aria-label="全局搜索卡片"
      />
      {!terms.length ? <>
        {children}
        <section className="project-all-cards" aria-label="全部卡片">
          <details className="project-card-section" open>
            <summary><strong>全部卡片</strong><span>{openCards.length} 张</span></summary>
            <div>{openCards.map((card) => cardRow(card, cardsOnCanvas))}</div>
          </details>
          <details className="project-card-section project-closed-cards">
            <summary><strong>已收口({closedCards.length})</strong></summary>
            <div>{closedCards.map((card) => cardRow(card, cardsOnCanvas))}</div>
          </details>
        </section>
      </> : (
        <div className="rail-card-results" aria-live="polite">
          {error && <div className="rail-empty">{error}</div>}
          {results.map((card) => cardRow(card, cardsOnCanvas))}
          {!error && !results.length && <div className="rail-empty">无匹配卡片</div>}
        </div>
      )}
    </section>
  );
}

export default function CanvasRail({
  tab,
  onCollapse,
  onPersist,
  disabled = false,
  projectRef = '',
}: CanvasRailProps) {
  const canvas = useCanvasStore((state) => state.canvas);
  const target = useCanvasStore((state) => state.target);
  const setNodeHidden = useCanvasStore((state) => state.setNodeHidden);
  const setFileLibrary = useCanvasStore((state) => state.setFileLibrary);
  const [ledgerEntries, setLedgerEntries] = useState<LedgerEntry[]>([]);
  const [taskRecord, setTaskRecord] = useState<CanvasTaskRecord | null>(null);
  const [savingNodeId, setSavingNodeId] = useState('');
  const [status, setStatus] = useState('');
  const [newPath, setNewPath] = useState('');
  const [attention, setAttention] = useState<AttentionQueuePayload | null>(null);
  const [projectWorkdir, setProjectWorkdir] = useState('');
  const [projectFactRoots, setProjectFactRoots] = useState<string[]>([]);
  const [projectConversations, setProjectConversations] = useState<ProjectConversationMaterial[]>([]);
  const [conversationFormOpen, setConversationFormOpen] = useState(false);
  const [conversationDraft, setConversationDraft] = useState<ConversationDraft>(EMPTY_CONVERSATION_DRAFT);
  const [conversationBusy, setConversationBusy] = useState('');

  const currentPath = target?.kind === 'card' ? target.value : '';

  useEffect(() => {
    if (!projectRef) {
      setAttention(null);
      setProjectWorkdir('');
      setProjectFactRoots([]);
      setProjectConversations([]);
      return;
    }
    let alive = true;
    loadAttentionQueue(projectRef)
      .then((payload) => { if (alive) setAttention(payload); })
      .catch(() => { if (alive) setAttention(null); });
    return () => { alive = false; };
  }, [projectRef]);

  useEffect(() => {
    if (!projectRef) return;
    let alive = true;
    loadProjectMaterials(projectRef)
      .then((payload) => {
        if (!alive) return;
        setProjectWorkdir(payload.workdir || '');
        setProjectFactRoots(Array.isArray(payload.fact_roots) ? payload.fact_roots : []);
        setProjectConversations(Array.isArray(payload.conversations) ? payload.conversations : []);
      })
      .catch(() => {
        if (!alive) return;
        setProjectWorkdir('');
        setProjectFactRoots([]);
        setProjectConversations([]);
      });
    return () => { alive = false; };
  }, [projectRef]);

  useEffect(() => {
    if (!currentPath) {
      setLedgerEntries([]);
      return;
    }
    let alive = true;
    loadLedger(currentPath)
      .then((payload) => {
        if (!alive) return;
        setLedgerEntries(Array.isArray(payload.entries) ? payload.entries : []);
      })
      .catch(() => {
        if (!alive) return;
        setLedgerEntries([]);
      });
    return () => {
      alive = false;
    };
  }, [currentPath]);

  useEffect(() => {
    if (!currentPath) {
      setTaskRecord(null);
      return;
    }
    let alive = true;
    fetch('/api/data')
      .then((response) => response.json())
      .then((payload) => {
        if (!alive) return;
        const tasks = Array.isArray(payload?.tasks) ? payload.tasks as CanvasTaskRecord[] : [];
        setTaskRecord(tasks.find((task) => task.path === currentPath) || null);
      })
      .catch(() => {
        if (!alive) return;
        setTaskRecord(null);
      });
    return () => {
      alive = false;
    };
  }, [currentPath]);

  const actorsByNode = useMemo(() => ledgerActorsByNode(ledgerEntries), [ledgerEntries]);
  const groupedNodes = useMemo(() => {
    const groups = GROUP_ORDER.reduce<Record<RailGroupKey, Node[]>>((acc, key) => {
      acc[key] = [];
      return acc;
    }, {} as Record<RailGroupKey, Node[]>);
    (canvas?.nodes || []).forEach((node) => {
      groups[classifyNode(node, actorsByNode.get(node.id) || [])].push(node);
    });
    return groups;
  }, [actorsByNode, canvas?.nodes]);

  const fileEntries = useMemo(
    () => dedupeEntries([
      ...fileEntriesFromTask(taskRecord),
      ...fileEntriesFromNodes(canvas?.nodes || []),
      ...metadataFileLibrary(canvas),
    ]),
    [canvas, taskRecord],
  );
  const projectPaths = useMemo(() => dedupeEntries([
    makeEntry(projectWorkdir, 'workdir', { kind: 'dir', summary: '项目工作目录' }),
    ...projectFactRoots.map((path) => makeEntry(path, 'fact_root', { kind: 'dir', summary: '注册表事实根 · 只读' })),
  ].filter((entry): entry is FileLibraryEntry => Boolean(entry))), [projectFactRoots, projectWorkdir]);
  const removableFileKeys = useMemo(
    () => new Set(metadataFileLibrary(canvas).map(entryKey)),
    [canvas],
  );

  const totalNodes = canvas?.nodes.length || 0;
  const aiMaterialNodes = groupedNodes.ai_material.length;

  const persistFileLibrary = useCallback(async (entries: FileLibraryEntry[]) => {
    if (disabled || !canvas) return;
    const metadataEntries = dedupeEntries([...metadataFileLibrary(canvas), ...entries]);
    setFileLibrary(serializableFileLibrary(metadataEntries));
    setStatus('保存文件清单...');
    try {
      await onPersist();
      setStatus('文件清单已保存');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, [canvas, disabled, onPersist, setFileLibrary]);

  const addPath = useCallback(async () => {
    const entries = dedupeEntries(
      newPath
        .split(/\r?\n/)
        .map((line) => makeEntry(line, 'rail'))
        .filter((entry): entry is FileLibraryEntry => Boolean(entry)),
    );
    if (!entries.length) {
      setStatus('请输入绝对路径或 URL');
      return;
    }
    setNewPath('');
    await persistFileLibrary(entries);
  }, [newPath, persistFileLibrary]);

  const removeFileEntry = useCallback(async (entry: FileLibraryEntry) => {
    if (disabled || !canvas || !removableFileKeys.has(entryKey(entry))) return;
    if (!window.confirm(`从文件栏移除“${entry.title}”？\n\n这不会删除磁盘文件，但会写入画布事件账。`)) return;
    const remaining = metadataFileLibrary(canvas).filter((item) => entryKey(item) !== entryKey(entry));
    setFileLibrary(serializableFileLibrary(remaining));
    setStatus('移除中...');
    try {
      await onPersist();
      setStatus('已从文件栏移除');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, [canvas, disabled, onPersist, removableFileKeys, setFileLibrary]);

  const onFileDrop = useCallback(async (event: React.DragEvent) => {
    const entries = extractDroppedPaths(event);
    if (!entries.length) return;
    event.preventDefault();
    await persistFileLibrary(entries);
  }, [persistFileLibrary]);

  const toggleNode = useCallback(async (node: Node) => {
    if (disabled || savingNodeId) return;
    const nextHidden = !nodeHidden(node);
    setNodeHidden(node.id, nextHidden);
    setSavingNodeId(node.id);
    setStatus(nextHidden ? '隐藏中...' : '放回中...');
    try {
      await onPersist();
      setStatus(nextHidden ? '已隐藏' : '已放回');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingNodeId('');
    }
  }, [disabled, onPersist, savingNodeId, setNodeHidden]);

  const openEntry = useCallback(async (entry: FileLibraryEntry) => {
    if (entry.kind === 'url') {
      window.open(entry.path, '_blank', 'noopener,noreferrer');
      return;
    }
    setStatus('打开中...');
    try {
      await openSource(entry.path);
      setStatus('已打开');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const openConversationAsset = useCallback(async (path: string) => {
    if (!projectRef) return;
    setStatus('打开中...');
    try {
      await openProjectMaterial(projectRef, path);
      setStatus('已打开');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    }
  }, [projectRef]);

  const addConversation = useCallback(async () => {
    if (!projectRef || disabled || conversationBusy) return;
    const conversationId = conversationDraft.conversationId.trim();
    const kind = conversationDraft.kind;
    const explicitPath = conversationDraft.path.trim();
    if (!conversationId || (kind === 'codex' && !explicitPath.startsWith('/'))) {
      setStatus(kind === 'codex' ? '请填写会话标识与材料绝对路径' : '请填写 Claude Science 会话标识');
      return;
    }
    if (kind === 'claude-science' && !conversationId.startsWith('proj_')) {
      setStatus('Claude Science 会话标识应以 proj_ 开头');
      return;
    }
    const path = kind === 'claude-science'
      ? explicitPath || `claude-science:${conversationId}`
      : explicitPath;
    const role = kind === 'claude-science' ? 'pointer' : conversationDraft.role;
    setConversationBusy('link');
    setStatus('添加归属中...');
    try {
      const linked = await linkProjectConversation(projectRef, {
        kind,
        conversation_id: conversationId,
        title: conversationDraft.title.trim() || conversationId,
        assets: [{ role, path, draggable: kind === 'codex' }],
      });
      setProjectConversations((rows) => [
        ...rows.filter((row) => row.conversation_id !== linked.conversation_id),
        linked,
      ]);
      setConversationDraft(EMPTY_CONVERSATION_DRAFT);
      setConversationFormOpen(false);
      setStatus('对话归属已添加');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setConversationBusy('');
    }
  }, [conversationBusy, conversationDraft, disabled, projectRef]);

  const removeConversation = useCallback(async (conversation: ProjectConversationMaterial) => {
    if (!projectRef || disabled || conversationBusy) return;
    if (!window.confirm(`移除“${conversation.title}”的项目归属？\n\n只删除归属记录，不会删除对话或任何材料。`)) return;
    setConversationBusy(conversation.conversation_id);
    setStatus('移除归属中...');
    try {
      const removed = await unlinkProjectConversation(projectRef, conversation.conversation_id);
      setProjectConversations((rows) => rows.filter((row) => row.conversation_id !== conversation.conversation_id));
      setConversationDraft(draftFromConversation(removed));
      setConversationFormOpen(true);
      setStatus('归属已移除；添加表单已预填，可随时挂回');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setConversationBusy('');
    }
  }, [conversationBusy, disabled, projectRef]);

  return (
    <aside className="canvas-rail" aria-label="画布信息栏">
      <button type="button" className="rail-collapse-handle" aria-label="收起右栏" title="收起右栏" onClick={onCollapse}>›</button>
      <header className="rail-head">
        <strong>{tab === 'cards' ? '卡片' : tab === 'files' ? '文件' : '节点'}</strong>
      </header>
      {tab === 'nodes' ? (
        <section className="rail-section" aria-label="节点显示">
          {status && <div className="rail-status">{status}</div>}
          {GROUP_ORDER.map((group) => {
            const nodes = groupedNodes[group];
            if (!nodes.length) return null;
            return (
              <details className="rail-group" key={group} open={group !== 'ai_material'}>
                <summary className="rail-group-title">
                  <span>{GROUP_LABEL[group]}</span>
                  <em>{nodes.length}</em>
                </summary>
                <div className="rail-node-list">
                  {nodes.map((node) => {
                    const hidden = nodeHidden(node);
                    const summary = nodeSummary(node);
                    const title = nodeTitle(node);
                    return (
                      <div className={`rail-node${hidden ? ' is-hidden' : ''}`} key={node.id}>
                        <div className="rail-node-text">
                          <strong title={nodeHoverTitle(node)}>{title}</strong>
                          <span>{nodeTypeLabel(node)} · {node.id}</span>
                          {summary && <em title={summary}>{summary}</em>}
                        </div>
                        <label
                          className="rail-toggle"
                        >
                          <input type="checkbox" checked={!hidden} disabled={disabled || Boolean(savingNodeId)} onChange={() => void toggleNode(node)} />
                          {hidden ? '放回' : '显示'}
                        </label>
                      </div>
                    );
                  })}
                </div>
              </details>
            );
          })}
          {aiMaterialNodes > 0 && <div className="rail-empty">AI 材料默认收起，数据仍在画布与事件账中。</div>}
          {!totalNodes && <div className="rail-empty">暂无节点</div>}
        </section>
      ) : tab === 'files' ? (
        <section
          className="rail-section rail-file-section"
          aria-label="文件库"
          onDragOver={(event) => {
            if (event.dataTransfer.types.includes('Files') || event.dataTransfer.types.includes('text/plain')) {
              event.preventDefault();
              event.dataTransfer.dropEffect = 'copy';
            }
          }}
          onDrop={(event) => void onFileDrop(event)}
        >
          {status && <div className="rail-status">{status}</div>}
          {projectRef && projectPaths.length > 0 && (
            <section className="rail-project-paths" aria-label="项目路径">
              <header>
                <strong>项目路径</strong>
                <span>注册表只读</span>
              </header>
              {projectPaths.map((entry) => (
                <div
                  className="rail-project-path"
                  key={entryKey(entry)}
                  title={entry.path}
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.setData(FILE_REF_DRAG_MIME, JSON.stringify(entry));
                    event.dataTransfer.effectAllowed = 'copy';
                  }}
                >
                  <div className="rail-node-text">
                    <strong>{entry.title}</strong>
                    <span>{entry.source.includes('workdir') ? 'workdir' : 'fact root'} · {entry.path}</span>
                  </div>
                  <button type="button" className="rail-open" onClick={() => void openEntry(entry)}>打开</button>
                </div>
              ))}
            </section>
          )}
          <form className="rail-file-add" onSubmit={(event) => { event.preventDefault(); void addPath(); }}>
            <textarea
              value={newPath}
              placeholder="粘贴绝对路径或 URL"
              onChange={(event) => setNewPath(event.target.value)}
              rows={3}
            />
            <input type="submit" value="添加" disabled={disabled || !newPath.trim()} />
          </form>
          <div className="rail-file-drop">拖入 Finder 文件/文件夹，或把下方条目拖到画布生成 REF</div>
          <div className="rail-node-list">
            {fileEntries.map((entry) => (
              <div
                className="rail-file"
                key={entryKey(entry)}
                title={entry.path}
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.setData(FILE_REF_DRAG_MIME, JSON.stringify(entry));
                  event.dataTransfer.effectAllowed = 'copy';
                }}
              >
                <div className="rail-node-text">
                  <strong>{entry.title}</strong>
                  <span>{kindLabel(entry.kind)} · {entry.source}</span>
                  {entry.summary && <em title={entry.summary}>{entry.summary}</em>}
                </div>
                <div className="rail-row-actions">
                  <button type="button" className="rail-open" onClick={() => void openEntry(entry)}>打开</button>
                  {removableFileKeys.has(entryKey(entry)) && (
                    <button type="button" className="rail-remove" disabled={disabled} onClick={() => void removeFileEntry(entry)}>移除</button>
                  )}
                </div>
              </div>
            ))}
          </div>
          {projectRef && (
            <div className="rail-conversation-list" aria-label="归属对话">
              <header className="rail-conversation-head">
                <div><strong>归属对话</strong><span>{projectConversations.length} 条</span></div>
                <button
                  type="button"
                  aria-expanded={conversationFormOpen}
                  onClick={() => setConversationFormOpen((value) => !value)}
                >{conversationFormOpen ? '收起' : '添加对话'}</button>
              </header>
              {conversationFormOpen && (
                <form className="rail-conversation-form" onSubmit={(event) => { event.preventDefault(); void addConversation(); }}>
                  <label>
                    <span>来源</span>
                    <select
                      value={conversationDraft.kind}
                      onChange={(event) => {
                        const kind = event.target.value as ConversationDraft['kind'];
                        setConversationDraft((draft) => ({ ...draft, kind, role: kind === 'claude-science' ? 'pointer' : draft.role === 'pointer' ? 'rollout' : draft.role }));
                      }}
                    >
                      <option value="codex">Codex rollout / manifest</option>
                      <option value="claude-science">Claude Science</option>
                    </select>
                  </label>
                  <label>
                    <span>会话标识</span>
                    <input
                      value={conversationDraft.conversationId}
                      placeholder={conversationDraft.kind === 'claude-science' ? 'proj_…' : 'rollout / thread id'}
                      onChange={(event) => setConversationDraft((draft) => ({ ...draft, conversationId: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span>标题 <em>可选</em></span>
                    <input
                      value={conversationDraft.title}
                      placeholder="默认使用会话标识"
                      onChange={(event) => setConversationDraft((draft) => ({ ...draft, title: event.target.value }))}
                    />
                  </label>
                  {conversationDraft.kind === 'codex' && (
                    <label>
                      <span>材料类型</span>
                      <select
                        value={conversationDraft.role}
                        onChange={(event) => setConversationDraft((draft) => ({ ...draft, role: event.target.value as ConversationDraft['role'] }))}
                      >
                        <option value="rollout">rollout</option>
                        <option value="manifest">manifest</option>
                        <option value="unexpanded">未展开清单</option>
                      </select>
                    </label>
                  )}
                  {conversationDraft.kind === 'codex' ? (
                    <label className="rail-conversation-path">
                      <span>rollout / manifest 绝对路径</span>
                      <textarea
                        rows={2}
                        value={conversationDraft.path}
                        placeholder="/Users/…"
                        onChange={(event) => setConversationDraft((draft) => ({ ...draft, path: event.target.value }))}
                      />
                    </label>
                  ) : (
                    <p className="rail-conversation-pointer-note">只登记会话标识；不扫描 Claude Science 内部目录，也不生成可拖拽文件引用。</p>
                  )}
                  <div className="rail-conversation-form-actions">
                    <span>显式归属，不扫描目录</span>
                    <button type="submit" disabled={disabled || Boolean(conversationBusy) || !conversationDraft.conversationId.trim() || (conversationDraft.kind === 'codex' && !conversationDraft.path.trim())}>确认添加</button>
                  </div>
                </form>
              )}
              {projectConversations.map((conversation) => (
                <div className="rail-conversation" key={conversation.conversation_id}>
                  <div className="rail-conversation-title">
                    <div className="rail-node-text">
                      <strong title={conversation.title}>{conversation.title}</strong>
                      <span>{conversation.kind === 'claude-science' ? 'Claude Science' : conversation.conversation_id.slice(0, 8)}</span>
                    </div>
                    <button
                      type="button"
                      className="rail-remove"
                      disabled={disabled || Boolean(conversationBusy)}
                      onClick={() => void removeConversation(conversation)}
                    >{conversationBusy === conversation.conversation_id ? '移除中' : '移除'}</button>
                  </div>
                  <div className="rail-material-badges">
                    {conversation.assets.map((asset) => {
                      const label = asset.role === 'manifest' ? '图' : asset.role === 'unexpanded' ? '清单' : asset.role === 'rollout' ? 'rollout' : '指针';
                      const entry = makeEntry(asset.path, `conversation ${asset.role}`, { summary: conversation.title });
                      const openable = asset.path.startsWith('/');
                      return (
                        <span
                          role={openable ? 'link' : undefined}
                          tabIndex={openable ? 0 : undefined}
                          className="rail-material-badge"
                          key={`${conversation.conversation_id}:${asset.role}`}
                          draggable={asset.draggable}
                          title={asset.draggable ? `${asset.path} · 可拖入画布生成 REF` : openable ? `${asset.path} · 仅展示与打开` : `${asset.path} · 只读归属标识`}
                          onDragStart={(event) => {
                            if (!asset.draggable || !entry) return;
                            event.dataTransfer.setData(FILE_REF_DRAG_MIME, JSON.stringify(entry));
                            event.dataTransfer.effectAllowed = 'copy';
                          }}
                          onClick={openable ? () => void openConversationAsset(asset.path) : undefined}
                          onKeyDown={openable ? (event) => { if (event.key === 'Enter') void openConversationAsset(asset.path); } : undefined}
                        >
                          {label}{asset.draggable ? '' : openable ? ' · 只读' : ' · 标识'}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))}
              {!projectConversations.length && !conversationFormOpen && <div className="rail-empty">暂无归属对话</div>}
            </div>
          )}
          {!fileEntries.length && !projectPaths.length && !projectConversations.length && <div className="rail-empty">暂无文件</div>}
        </section>
      ) : (
        <>
          {attention && attention.needs_you.length > 0 && (
            <section className="project-attention-banner" aria-label="需要你·本项目" data-attention-section="true">
              <header><strong>需要你·本项目</strong><span>{attention.counts.needs_you}</span></header>
              {attention.needs_you.map((item) => (
                <a href={`/#${encodeURIComponent(item.task_id || item.path)}`} key={item.path} target="_top">
                  <b>{item.task_id}</b><span>{item.title}</span>
                </a>
              ))}
            </section>
          )}
          <CardSearch projectRef={projectRef}>
            {projectRef && attention ? (
              <ProjectCards attention={attention} projectRef={projectRef} />
            ) : <div className="rail-empty">当前画布没有项目卡片分段</div>}
          </CardSearch>
          {projectRef && attention && (
            <a className="project-dispatch-footer" href="/" target="_top">
              其他项目需要你 {attention.counts.other_projects_needs_you} · 去调度台
            </a>
          )}
        </>
      )}
    </aside>
  );
}

// 收尾期项目的里程碑区默认展开;公开版不内置私有项目清单,置空由使用者按需填own project_ref
const CLOSING_PROJECTS = new Set<string>([]);

function assigneeSummary(items: AttentionQueuePayload['processing']): string {
  const counts = new Map<string, number>();
  items.forEach((item) => {
    const name = item.assignee?.trim() || '未分配';
    counts.set(name, (counts.get(name) || 0) + 1);
  });
  return Array.from(counts).map(([name, count]) => `${name} ${count}`).join(' · ');
}

function compactCard(item: AttentionQueuePayload['processing'][number], onCanvas: Set<string>) {
  return <a className={`project-card-row${onCanvas.has(item.path) ? ' is-on-canvas' : ''}`} href={`/#${encodeURIComponent(item.task_id || item.path)}`} key={item.path} target="_top"><b>{item.task_id}</b><span>{item.title}</span><em>{item.assignee || '未分配'}</em>{onCanvas.has(item.path) && <i className="rail-card-on-canvas">已入图</i>}</a>;
}

function ProjectCards({ attention, projectRef }: { attention: AttentionQueuePayload; projectRef: string }) {
  const canvas = useCanvasStore((state) => state.canvas);
  const onCanvas = useMemo(() => new Set((canvas?.nodes || []).flatMap((node) => {
    const ref = sourceRef(node);
    return ref?.kind === 'card' && ref.path ? [String(ref.path)] : [];
  })), [canvas?.nodes]);
  const milestones = [...attention.needs_you, ...attention.processing, ...attention.planned]
    .sort((a, b) => String(b.updated || '').localeCompare(String(a.updated || '')))
    .slice(0, 5);
  const activeCount = attention.needs_you.length + attention.processing.length + attention.planned.length;
  return (
    <section className="project-card-sections" aria-label="本项目卡片分段">
      <details className="project-card-section project-milestones" open={CLOSING_PROJECTS.has(projectRef)}>
        <summary><strong>关键节点</strong><span>{milestones.length}</span></summary>
        <p className="project-current-state">当前态 · {attention.needs_you.length} 待确认 / {attention.processing.length} 进行中 / {attention.planned.length} 待编排</p>
        <div>{milestones.map((item) => compactCard(item, onCanvas))}</div>
        <p className="project-closing-rule">收场判据 · {activeCount ? `剩余 ${activeCount} 张活跃卡全部闭环` : '活跃卡已清零'}</p>
      </details>
      <details className="project-card-section">
        <summary><strong>进行中</strong><span>{attention.processing.length} 张 · {assigneeSummary(attention.processing) || '无人执行'}</span></summary>
        <div>{attention.processing.map((item) => compactCard(item, onCanvas))}</div>
      </details>
      <details className="project-card-section">
        <summary><strong>todo / planned</strong><span>{attention.planned.length} 张</span></summary>
        <div>{attention.planned.map((item) => compactCard(item, onCanvas))}</div>
      </details>
    </section>
  );
}
