import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlowProvider,
} from 'reactflow';
import type { Edge as FlowEdge, Node as FlowNode, NodeProps, ReactFlowInstance } from 'reactflow';
import BoardLink from './BoardLink';
import { loadConversationProjectGraph } from '../services/canvasApi';
import type {
  ConversationProjectGraphEdge,
  ConversationProjectGraphNode,
  ConversationProjectGraphPayload,
} from '../services/canvasApi';

const BASE = (import.meta.env.BASE_URL || '/').endsWith('/')
  ? (import.meta.env.BASE_URL || '/')
  : `${import.meta.env.BASE_URL || '/'}/`;
const PRO_OPTIONS = { hideAttribution: true };
const TERMINAL = new Set(['completed', 'error', 'timeout', 'killed']);
type GraphScope = 'focused' | 'all';

interface GraphNodeData {
  entity: ConversationProjectGraphNode;
  taskPath: string;
  selected: boolean;
  onTextSelection: (selection: TextSelection) => void;
}

interface TextSelection {
  text: string;
  rect: DOMRect;
  entity: ConversationProjectGraphNode;
  taskPath: string;
}

function assertionLabel(assertion?: string) {
  if (assertion === 'ai_archived') return 'AI 归档';
  if (assertion === 'human_confirmed') return '人工确认';
  return '硬证据';
}

function typeLabel(type: string) {
  return {
    session_map: 'Session Map',
    archived_branch: '归档分支',
    branch_placeholder: '活动占位',
    task: '任务卡',
    document: 'Markdown',
  }[type] || type;
}

function GraphEntityNode({ data }: NodeProps<GraphNodeData>) {
  const entity = data.entity;
  const onMouseUp = (event: React.MouseEvent<HTMLDivElement>) => {
    const selection = window.getSelection();
    const text = String(selection?.toString() || '').trim();
    const anchorNode = selection?.anchorNode;
    if (!text || !selection?.rangeCount || !anchorNode || !event.currentTarget.contains(anchorNode)) return;
    data.onTextSelection({
      text: text.slice(0, 2000),
      rect: selection.getRangeAt(0).getBoundingClientRect(),
      entity,
      taskPath: data.taskPath,
    });
  };
  return (
    <article
      className={`project-graph-node nodrag nopan is-${entity.type}${data.selected ? ' is-selected' : ''}${entity.assertion === 'ai_archived' ? ' is-ai-archived' : ''}`}
      onMouseDown={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
      onMouseUp={onMouseUp}
    >
      <Handle position={Position.Left} type="target" />
      <header>
        <span>{typeLabel(entity.type)}</span>
        <em>{assertionLabel(entity.assertion)}</em>
      </header>
      <strong>{entity.title}</strong>
      {entity.summary && <p>{entity.summary}</p>}
      <footer>
        <span>{entity.archive_state || entity.status || ''}</span>
        {entity.drift?.state && <em>drift · {entity.drift.state}</em>}
        {data.taskPath && <small>可旁聊</small>}
      </footer>
      <Handle position={Position.Right} type="source" />
    </article>
  );
}

const nodeTypes = { projectEntity: GraphEntityNode };

function taskPathIndex(data: ConversationProjectGraphPayload) {
  const nodes = new Map(data.nodes.map((node) => [node.id, node]));
  const adjacentTasks = new Map<string, Set<string>>();
  data.edges.forEach((edge) => {
    const source = nodes.get(edge.source);
    const target = nodes.get(edge.target);
    if (source?.type === 'task' && source.live_ref?.path) {
      adjacentTasks.set(edge.target, new Set([...(adjacentTasks.get(edge.target) || []), source.live_ref.path]));
    }
    if (target?.type === 'task' && target.live_ref?.path) {
      adjacentTasks.set(edge.source, new Set([...(adjacentTasks.get(edge.source) || []), target.live_ref.path]));
    }
  });
  return new Map(data.nodes.map((node) => {
    if (node.type === 'task' && node.live_ref?.path) return [node.id, node.live_ref.path];
    const paths = [...(adjacentTasks.get(node.id) || [])];
    return [node.id, paths.length === 1 ? paths[0] : ''];
  }));
}

function nodeColumn(type: string) {
  if (type === 'session_map') return 0;
  if (type === 'archived_branch' || type === 'branch_placeholder') return 1;
  if (type === 'task') return 2;
  if (type === 'document') return 3;
  return 4;
}

function flowLayout(
  data: ConversationProjectGraphPayload,
  selectedId: string,
  onTextSelection: (selection: TextSelection) => void,
): FlowNode<GraphNodeData>[] {
  const taskPaths = taskPathIndex(data);
  const rowByColumn = new Map<number, number>();
  return data.nodes.map((entity) => {
    const column = nodeColumn(entity.type);
    const row = rowByColumn.get(column) || 0;
    rowByColumn.set(column, row + 1);
    return {
      id: entity.id,
      type: 'projectEntity',
      draggable: false,
      position: { x: column * 340, y: row * 170 },
      style: { width: 292 },
      data: {
        entity,
        taskPath: taskPaths.get(entity.id) || '',
        selected: entity.id === selectedId,
        onTextSelection,
      },
    };
  });
}

function flowEdges(edges: ConversationProjectGraphEdge[]): FlowEdge[] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: 'smoothstep',
    label: edge.relation,
    markerEnd: { type: MarkerType.ArrowClosed, color: edge.assertion === 'ai_archived' ? '#9a7a32' : '#5f5f5a' },
    animated: false,
    className: `project-graph-edge is-${edge.assertion || 'hard_evidence'} is-${edge.status || 'active'}`,
    style: {
      stroke: edge.assertion === 'ai_archived' ? '#9a7a32' : '#73736d',
      strokeDasharray: edge.assertion === 'ai_archived' ? '5 5' : undefined,
      opacity: edge.status === 'invalidated' ? 0.35 : 1,
    },
  }));
}

function projectGraphSubset(data: ConversationProjectGraphPayload, scope: GraphScope, query: string): ConversationProjectGraphPayload {
  const needle = query.trim().toLowerCase();
  if (scope === 'all' && !needle) return data;
  const nodeById = new Map(data.nodes.map((node) => [node.id, node]));
  const selected = new Set<string>();
  if (needle) {
    data.nodes.forEach((node) => {
      const haystack = [node.id, node.title, node.summary, node.task_id, node.path]
        .map((value) => String(value || '').toLowerCase())
        .join(' ');
      if (haystack.includes(needle)) selected.add(node.id);
    });
  } else {
    const tasksWithDocuments = new Set<string>();
    data.edges.forEach((edge) => {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (source?.type === 'task' && target?.type === 'document') tasksWithDocuments.add(source.id);
      if (target?.type === 'task' && source?.type === 'document') tasksWithDocuments.add(target.id);
    });
    data.nodes.forEach((node) => {
      const liveStatus = String(node.live_ref?.status || node.status || '').toLowerCase();
      if ((node.type === 'task' && tasksWithDocuments.has(node.id) && liveStatus !== 'done')
          || node.archive_state === 'active_placeholder'
          || node.assertion === 'ai_archived'
          || node.drift?.state === 'changed') {
        selected.add(node.id);
      }
    });
    data.edges.forEach((edge) => {
      if (edge.assertion === 'ai_archived') {
        selected.add(edge.source);
        selected.add(edge.target);
      }
    });
  }
  const expansionRounds = needle ? 1 : 2;
  for (let round = 0; round < expansionRounds; round += 1) {
    const frontier = new Set(selected);
    data.edges.forEach((edge) => {
      if (frontier.has(edge.source)) selected.add(edge.target);
      if (frontier.has(edge.target)) selected.add(edge.source);
    });
  }
  const focusRank: Record<string, number> = {
    task: 0,
    document: 1,
    branch_placeholder: 2,
    archived_branch: 3,
    session_map: 4,
  };
  const orderedNodes = data.nodes
    .filter((node) => selected.has(node.id))
    .sort((a, b) => (focusRank[a.type] ?? 9) - (focusRank[b.type] ?? 9) || a.title.localeCompare(b.title));
  const visibleNodes = needle ? orderedNodes.slice(0, 80) : [
    ...orderedNodes.filter((node) => node.type === 'task').slice(0, 10),
    ...orderedNodes.filter((node) => node.type === 'document').slice(0, 10),
    ...orderedNodes.filter((node) => node.type === 'branch_placeholder').slice(0, 4),
    ...orderedNodes.filter((node) => node.type === 'archived_branch').slice(0, 8),
    ...orderedNodes.filter((node) => node.type === 'session_map').slice(0, 4),
  ];
  const orderedIds = visibleNodes.map((node) => node.id);
  const visible = new Set(orderedIds);
  return {
    ...data,
    nodes: orderedIds.map((id) => nodeById.get(id)).filter(Boolean) as ConversationProjectGraphNode[],
    edges: data.edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)),
  };
}

function resultText(entry: Record<string, unknown>) {
  const messages = Array.isArray(entry.messages) ? entry.messages as Array<Record<string, unknown>> : [];
  for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
    if (messages[idx]?.role === 'ai' && messages[idx]?.content) return String(messages[idx].content);
  }
  return String(entry.output || entry.error || '没有返回内容');
}

export default function ConversationProjectGraphView() {
  const [data, setData] = useState<ConversationProjectGraphPayload | null>(null);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [selection, setSelection] = useState<TextSelection | null>(null);
  const [actionText, setActionText] = useState('');
  const [actionRunId, setActionRunId] = useState('');
  const [actionKind, setActionKind] = useState<'quick' | 'deep' | ''>('');
  const [actionDone, setActionDone] = useState(false);
  const [scope, setScope] = useState<GraphScope>('focused');
  const [query, setQuery] = useState('');
  const actionPath = useRef('');
  const flowInstance = useRef<ReactFlowInstance | null>(null);

  useEffect(() => {
    let alive = true;
    loadConversationProjectGraph()
      .then((payload) => {
        if (!alive) return;
        setData(payload);
        setSelectedId(payload.nodes[0]?.id || '');
      })
      .catch((err) => alive && setError(err instanceof Error ? err.message : String(err)));
    return () => { alive = false; };
  }, []);

  const handleTextSelection = useCallback((next: TextSelection) => {
    setSelection(next);
    setSelectedId(next.entity.id);
    setActionText('');
  }, []);

  const visibleData = useMemo(() => data ? projectGraphSubset(data, scope, query) : null, [data, query, scope]);
  const nodes = useMemo(() => visibleData ? flowLayout(visibleData, selectedId, handleTextSelection) : [], [handleTextSelection, selectedId, visibleData]);
  const edges = useMemo(() => visibleData ? flowEdges(visibleData.edges) : [], [visibleData]);
  const selected = visibleData?.nodes.find((node) => node.id === selectedId) || null;

  useEffect(() => {
    if (!visibleData?.nodes.length) return;
    if (!visibleData.nodes.some((node) => node.id === selectedId)) setSelectedId(visibleData.nodes[0].id);
  }, [selectedId, visibleData]);

  const closeAction = useCallback(() => {
    if (actionKind === 'quick' && actionRunId) {
      void fetch('/api/ai-result', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: actionRunId, path: actionPath.current }),
      });
    }
    setActionRunId('');
    setActionKind('');
    setActionDone(false);
    setActionText('');
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  }, [actionKind, actionRunId]);

  const launchSelectionAction = useCallback(async (tool: 'claude' | 'codex', kind: 'quick' | 'deep') => {
    if (!selection?.taskPath) return;
    setActionText(kind === 'quick' ? `${tool} 正在快速解释…` : `${tool} 正在建立深入旁聊…`);
    setActionKind(kind);
    setActionDone(false);
    actionPath.current = selection.taskPath;
    const prompt = [
      kind === 'quick'
        ? '请用中文快速解释选中的文字：一句白话核心意思，加必要概念或隐含前提。'
        : '请围绕选中文字做深入问答的第一轮：解释其含义、指出值得追问的地方，并提出下一步问题。',
      `来源：Conversation Project Graph 节点 ${selection.entity.id}（${selection.entity.type}）`,
      `选中文字：${selection.text}`,
      '不要把图谱投影当作原始会话事实；需要事实时回查任务卡或 Session Map。',
    ].join('\n');
    try {
      const response = await fetch('/api/ai-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: selection.taskPath,
          tool,
          prompt,
          display_message: `${kind === 'quick' ? '快速解释' : '深入问答'}：${selection.text.slice(0, 160)}`,
          origin: kind === 'quick' ? 'selection_quick_explain' : 'selection_side_chat',
        }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(String(payload.error || 'AI 启动失败'));
      setActionRunId(String(payload.run_id));
    } catch (err) {
      setActionText(err instanceof Error ? err.message : String(err));
    }
  }, [selection]);

  useEffect(() => {
    if (!actionRunId || actionDone) return undefined;
    let alive = true;
    const poll = async () => {
      try {
        const response = await fetch(`/api/ai-results?run_id=${encodeURIComponent(actionRunId)}`);
        const payload = await response.json();
        const entry = Array.isArray(payload.results)
          ? payload.results.find((item: Record<string, unknown>) => String(item.run_id || '') === actionRunId)
          : null;
        if (!alive || !entry) return;
        const status = String(entry.status || '');
        if (status === 'queued' || status === 'running') {
          setActionText(`${String(entry.tool || 'AI')} · ${status === 'queued' ? '排队中' : '处理中'}…`);
          return;
        }
        setActionText(resultText(entry));
        if (TERMINAL.has(status)) setActionDone(true);
      } catch {
        /* next poll can recover */
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [actionDone, actionRunId]);

  const onInit = useCallback((instance: ReactFlowInstance) => {
    flowInstance.current = instance;
    window.setTimeout(() => instance.fitView({ padding: 0.08, duration: 220 }), 100);
  }, []);

  useEffect(() => {
    if (!flowInstance.current || !nodes.length) return;
    const timer = window.setTimeout(() => flowInstance.current?.fitView({ padding: 0.16, duration: 220 }), 80);
    return () => window.clearTimeout(timer);
  }, [nodes.length, query, scope]);

  if (error) return <div className="conv-status">Project Graph load failed: {error}</div>;
  if (!data) return <div className="conv-status">Loading Conversation Project Graph…</div>;

  return (
    <main className="project-graph-app">
      <header className="project-graph-head">
        <div>
          <span>Conversation Map · aggregate projection</span>
          <h1>项目对话图谱</h1>
          <p>Session Map 保持独立；这里只连接分支、任务卡和 Markdown。</p>
        </div>
        <div className="project-graph-head-tools">
          <BoardLink />
          <div className="project-graph-filters">
            <button className={scope === 'focused' ? 'is-active' : ''} onClick={() => setScope('focused')} type="button">重点关联</button>
            <button className={scope === 'all' ? 'is-active' : ''} onClick={() => setScope('all')} type="button">全部</button>
            <input aria-label="筛选项目图" onChange={(event) => setQuery(event.target.value)} placeholder="任务卡 / 会话 / 文档" value={query} />
          </div>
          <dl>
          <div><dt>nodes</dt><dd>{visibleData?.nodes.length || 0}/{data.counts?.nodes || data.nodes.length}</dd></div>
          <div><dt>AI 归档</dt><dd>{data.counts?.ai_archived || 0}</dd></div>
          <div><dt>活动分支</dt><dd>{data.counts?.active_placeholders || 0}</dd></div>
          </dl>
        </div>
      </header>
      <section className="project-graph-stage">
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            fitView
            minZoom={0.08}
            maxZoom={1.8}
            onInit={onInit}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            proOptions={PRO_OPTIONS}
          >
            <Background color="#d7d7d2" gap={22} size={1} variant={BackgroundVariant.Dots} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeColor="#d8d8d3" />
          </ReactFlow>
        </ReactFlowProvider>
        {selected && (
          <aside className="project-graph-inspector">
            <span>{typeLabel(selected.type)} · {assertionLabel(selected.assertion)}</span>
            <strong>{selected.title}</strong>
            {selected.summary && <p>{selected.summary}</p>}
            {selected.manifest_path && <a href={`${BASE}?conv=${encodeURIComponent(selected.manifest_path)}`}>打开 Session Map</a>}
            {selected.live_ref?.path && <a href={`${BASE}?path=${encodeURIComponent(selected.live_ref.path)}`}>打开任务卡画布</a>}
            {selected.path && <code>{selected.path}</code>}
            {selected.drift?.state && <em>snapshot ↔ live：{selected.drift.state}</em>}
          </aside>
        )}
      </section>
      {selection && (
        <section
          className="project-graph-selection"
          style={{ left: Math.max(12, Math.min(selection.rect.left, window.innerWidth - 330)), top: Math.max(12, selection.rect.bottom + 8) }}
        >
          <header><strong>使用选中文字</strong><button type="button" onClick={closeAction}>×</button></header>
          <p>{selection.text}</p>
          {!selection.taskPath && <em>该节点没有唯一任务卡关联；先回到 Session Map 选择具体任务分支。</em>}
          {selection.taskPath && !actionText && (
            <div>
              <button type="button" onClick={() => void launchSelectionAction('codex', 'quick')}>快速解释 · Codex</button>
              <button type="button" onClick={() => void launchSelectionAction('claude', 'deep')}>深入问 Claude</button>
              <button type="button" onClick={() => void launchSelectionAction('codex', 'deep')}>深入问 Codex</button>
            </div>
          )}
          {actionText && <pre>{actionText}</pre>}
          {actionKind === 'deep' && selection.taskPath && <a href={`${BASE}?path=${encodeURIComponent(selection.taskPath)}`}>打开任务卡继续问答</a>}
        </section>
      )}
    </main>
  );
}
