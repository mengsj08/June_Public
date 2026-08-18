// source: upstream canvas project frontend/src/components/Canvas.tsx @ c7116ce
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useNodesInitialized,
  useReactFlow,
} from 'reactflow';
import type {
  Connection,
  EdgeChange,
  Node,
  NodeChange,
  OnConnect,
  ReactFlowInstance,
  XYPosition,
} from 'reactflow';
import 'reactflow/dist/style.css';
import './canvas-handles.css';
import './kan851.css';

import { useCanvasStore } from '../store/canvasStore';
import { loadNodeHistory, resolveCanvasSourceRef } from '../services/canvasApi';
import type { LedgerEntry } from '../services/canvasApi';
import { CARD_DRAG_MIME, FILE_REF_DRAG_MIME } from './dragTypes';
import NoteNode from './nodes/NoteNode';
import LinkNode from './nodes/LinkNode';
import RefNode from './nodes/RefNode';
import DialogueNode from './nodes/DialogueNode';
import {
  FOCUS_MAX_ATTEMPTS,
  FOCUS_RETRY_MS,
  findFocusNode,
  focusCenterCall,
  focusShellReady,
} from './canvasFocus';

const DELETE_KEY_CODE = ['Backspace', 'Delete'];
const PRO_OPTIONS = { hideAttribution: true };
const DEFAULT_VIEWPORT = { x: 0, y: 0, zoom: 0.65 };

// Owner 2026-07-03 拍板:Text/Markdown 合并为单一 note;text/markdown 是存量别名,新建一律 note
const nodeTypes = {
  note: NoteNode,
  text: NoteNode,
  markdown: NoteNode,
  link: LinkNode,
  ref: RefNode,
  dialogue: DialogueNode,
};

interface CanvasProps {
  onSave?: () => void | Promise<unknown>;
  focusTaskId?: string;
  onPositionResolver?: (resolver: (() => XYPosition) | null) => void;
}

function CanvasFlow({ onSave, focusTaskId, onPositionResolver }: CanvasProps) {
  const canvas = useCanvasStore((state) => state.canvas);
  const target = useCanvasStore((state) => state.target);
  const cardPath = useCanvasStore((state) => state.path);
  const setNodes = useCanvasStore((state) => state.setNodes);
  const setNodesSilently = useCanvasStore((state) => state.setNodesSilently);
  const setEdges = useCanvasStore((state) => state.setEdges);
  const deleteNode = useCanvasStore((state) => state.deleteNode);
  const addNode = useCanvasStore((state) => state.addNode);
  const { screenToFlowPosition } = useReactFlow();
  const nodesInitialized = useNodesInitialized({ includeHiddenNodes: false });
  const shellRef = useRef<HTMLDivElement | null>(null);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [nodeHistory, setNodeHistory] = useState<LedgerEntry[]>([]);
  const [nodeHistoryStatus, setNodeHistoryStatus] = useState('');
  const [dropNotice, setDropNotice] = useState('');

  useEffect(() => {
    if (!onPositionResolver) return undefined;
    const resolveViewportCenter = () => {
      const bounds = shellRef.current?.getBoundingClientRect();
      if (!bounds) return { x: 140, y: 140 };
      return screenToFlowPosition({
        x: bounds.left + bounds.width / 2,
        y: bounds.top + bounds.height / 2,
      });
    };
    onPositionResolver(resolveViewportCenter);
    return () => onPositionResolver(null);
  }, [onPositionResolver, screenToFlowPosition]);

  // 拖入语义(Owner 2026-07-03):AI 只建议,拖进来的是她——入图节点一律 origin:'manual'。
  // 本地材料=指针不搬家(ref 节点指原路径,不上传不拷贝);
  // 浏览器安全模型不给本地文件绝对路径,故拖文件本体只能按名寻径(pending→保存时后端裁决)。
  const onDragOver = useCallback((event: React.DragEvent) => {
    const types = event.dataTransfer.types;
    if (
      types.includes(CARD_DRAG_MIME) ||
      types.includes(FILE_REF_DRAG_MIME) ||
      types.includes('Files') ||
      types.includes('text/plain')
    ) {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
    }
  }, []);

  const dropRefNode = useCallback(
    (
      idBase: string,
      label: string,
      sourceRef: Record<string, unknown>,
      x: number,
      y: number,
      extras: Record<string, unknown> = {},
    ) => {
      const store = useCanvasStore.getState();
      const dup = (store.canvas?.nodes || []).find((n) => {
        const ref = (n.data as { source_ref?: { kind?: string; path?: string } })?.source_ref;
        return ref?.path === sourceRef.path && ref?.kind === sourceRef.kind;
      });
      if (dup) return;
      const taken = new Set((store.canvas?.nodes || []).map((n) => n.id));
      let id = idBase;
      let i = 2;
      while (taken.has(id)) id = `${idBase}-${i++}`;
      addNode({
        id,
        type: 'ref',
        position: screenToFlowPosition({ x, y }),
        data: {
          kind: sourceRef.kind,
          label,
          title: label,
          origin: 'manual',
          source_ref: sourceRef,
          ...extras,
        },
      });
    },
    [addNode, screenToFlowPosition],
  );

  const resolveAndDropRef = useCallback(async (
    idBase: string,
    label: string,
    path: string,
    kind: string,
    x: number,
    y: number,
    extras: Record<string, unknown> = {},
  ) => {
    let sourceRef: Record<string, unknown> = { kind, path, status: 'pending' };
    if (cardPath) {
      try {
        const payload = await resolveCanvasSourceRef(cardPath, path, kind);
        const resolved = payload.source_ref;
        if (resolved && typeof resolved === 'object') sourceRef = resolved as Record<string, unknown>;
      } catch (error) {
        setDropNotice(error instanceof Error ? error.message : String(error));
      }
    }
    const status = String(sourceRef.status || 'pending');
    if (!['resolved', 'corrected'].includes(status)) {
      const roots = Array.isArray(sourceRef.searched_roots) && sourceRef.searched_roots.length
        ? sourceRef.searched_roots
        : Array.isArray(sourceRef.allowed_roots) ? sourceRef.allowed_roots : [];
      const rootsText = roots.map(String).join('、') || '卡片 workdir / 配置的允许根';
      setDropNotice(
        `“${label}”未解析（${status}）。已搜索：${rootsText}。把文件放进允许根或卡 workdir 后重新加载；或换用能“打开来源”的已解析引用。`,
      );
    } else {
      setDropNotice('');
    }
    dropRefNode(idBase, label, sourceRef, x, y, extras);
  }, [cardPath, dropRefNode]);

  const onDrop = useCallback(
    async (event: React.DragEvent) => {
      // ① 看板卡(来自 CardPalette)
      const raw = event.dataTransfer.getData(CARD_DRAG_MIME);
      if (raw) {
        event.preventDefault();
        try {
          const card = JSON.parse(raw) as { task_id: string; title: string; path: string };
          dropRefNode(
            `card-${card.task_id}`,
            `${card.task_id} ${card.title}`,
            { kind: 'card', task_id: card.task_id, path: card.path },
            event.clientX,
            event.clientY,
            {
              summary: `任务卡: ${card.title}`,
              relation_note: '从卡片面板手动拖入；表示它可以作为当前图的上下文材料。',
            },
          );
          onSave?.();
        } catch {
          /* 非法负载忽略 */
        }
        return;
      }
      // ② rail 文件库:文件/目录/链接指针 → REF 节点
      const rawFileRef = event.dataTransfer.getData(FILE_REF_DRAG_MIME);
      if (rawFileRef) {
        event.preventDefault();
        try {
          const item = JSON.parse(rawFileRef) as {
            id?: string;
            kind?: string;
            path?: string;
            title?: string;
            summary?: string;
          };
          const path = String(item.path || '').trim();
          if (!path) return;
          const title = String(item.title || path.split('/').filter(Boolean).pop() || path).trim();
          const kind = String(item.kind || (/^https?:\/\//i.test(path) ? 'url' : 'file')).trim();
          await resolveAndDropRef(
            `${kind}-${title.replace(/[^A-Za-z0-9_.-]+/g, '-')}`,
            title,
            path,
            kind,
            event.clientX,
            event.clientY,
            {
              summary: String(item.summary || '').trim(),
              relation_note: '从文件页签手动拖入；表示它可以作为当前图的上下文材料。',
            },
          );
        } catch {
          /* 非法负载忽略 */
        }
        return;
      }
      // ③ 拖入文本:绝对路径 → 文件指针;http(s) → Link 节点
      const text = (event.dataTransfer.getData('text/plain') || '').trim();
      if (text && (text.startsWith('/') || text.startsWith('~/'))) {
        event.preventDefault();
        const base = text.split('/').filter(Boolean).pop() || text;
        await resolveAndDropRef(
          `file-${base.replace(/[^A-Za-z0-9_.-]+/g, '-')}`,
          base,
          text,
          'file',
          event.clientX,
          event.clientY,
          {
            summary: '',
            relation_note: '从外部手动拖入；保存时由 kanban 后端校验来源是否可打开。',
          },
        );
        return;
      }
      if (text && /^https?:\/\//i.test(text)) {
        event.preventDefault();
        const store = useCanvasStore.getState();
        const taken = new Set((store.canvas?.nodes || []).map((n) => n.id));
        let id = 'link-drop';
        let i = 2;
        while (taken.has(id)) id = `link-drop-${i++}`;
        addNode({
          id,
          type: 'link',
          position: screenToFlowPosition({ x: event.clientX, y: event.clientY }),
          data: { title: text.replace(/^https?:\/\//i, '').slice(0, 60), url: text, origin: 'manual' },
        });
        return;
      }
      // ④ 拖入文件本体:只拿得到文件名(浏览器不给路径)→ 按名建 pending 指针,保存时后端寻径
      const files = Array.from(event.dataTransfer.files || []).slice(0, 5);
      if (files.length) {
        event.preventDefault();
        for (const [idx, f] of files.entries()) {
          await resolveAndDropRef(
            `file-${f.name.replace(/[^A-Za-z0-9_.-]+/g, '-')}`,
            f.name,
            f.name,
            'file',
            event.clientX + idx * 36,
            event.clientY + idx * 36,
            {
              summary: '',
              relation_note: '从浏览器拖入；按文件名在允许根内定位,内容以「来源」路径为准。',
            },
          );
        }
      }
    },
    [addNode, dropRefNode, onSave, resolveAndDropRef, screenToFlowPosition],
  );

  const focusNode = useMemo(() => findFocusNode(canvas?.nodes || [], focusTaskId || ''), [canvas?.nodes, focusTaskId]);
  const focusNodeId = focusNode?.id || '';

  const nodes = useMemo(() => {
    const rawNodes = canvas?.nodes ?? [];
    if (!focusNodeId) return rawNodes;
    return rawNodes.map((node) => {
      if (node.id !== focusNodeId) return node;
      return {
        ...node,
        className: [node.className, 'is-focus-target'].filter(Boolean).join(' '),
      };
    });
  }, [canvas?.nodes, focusNodeId]);
  const edges = useMemo(
    () => {
      const hiddenNodeIds = new Set(
        (canvas?.nodes ?? [])
          .filter((node) => Boolean(node.hidden || (node.data as { hidden?: boolean } | undefined)?.hidden))
          .map((node) => node.id),
      );
      return (canvas?.edges ?? []).map((edge) => ({
        ...edge,
        animated: true,
        hidden: Boolean(edge.hidden || hiddenNodeIds.has(edge.source) || hiddenNodeIds.has(edge.target)),
      }));
    },
    [canvas?.edges, canvas?.nodes],
  );

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.contentEditable === 'true'
      ) {
        return;
      }

      if ((event.ctrlKey || event.metaKey) && event.key === 's') {
        event.preventDefault();
        onSave?.();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onSave]);

  useEffect(() => {
    if (!focusNodeId || !focusTaskId || !flowInstance || !nodesInitialized) return;
    let cancelled = false;
    let retryTimer = 0;
    let settleTimer = 0;
    let frameOne = 0;
    let frameTwo = 0;

    const centerFocusedNode = (attempt = 0) => {
      if (cancelled) return;
      const latestNode = findFocusNode(useCanvasStore.getState().canvas?.nodes || [], focusTaskId);
      if (!latestNode) return;
      const call = focusCenterCall(latestNode);
      const shellReady = focusShellReady(shellRef.current?.getBoundingClientRect());
      if ((!shellReady || !call.measured) && attempt < FOCUS_MAX_ATTEMPTS) {
        retryTimer = window.setTimeout(() => centerFocusedNode(attempt + 1), FOCUS_RETRY_MS);
        return;
      }
      flowInstance.setCenter(call.x, call.y, call.options);
      settleTimer = window.setTimeout(() => {
        if (cancelled || !focusShellReady(shellRef.current?.getBoundingClientRect())) return;
        const freshNode = findFocusNode(useCanvasStore.getState().canvas?.nodes || [], focusTaskId);
        if (!freshNode) return;
        const freshCall = focusCenterCall(freshNode);
        flowInstance.setCenter(freshCall.x, freshCall.y, { ...freshCall.options, duration: 180 });
      }, 120);
    };

    frameOne = window.requestAnimationFrame(() => {
      frameTwo = window.requestAnimationFrame(() => centerFocusedNode());
    });
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frameOne);
      window.cancelAnimationFrame(frameTwo);
      window.clearTimeout(retryTimer);
      window.clearTimeout(settleTimer);
    };
  }, [flowInstance, focusNodeId, focusTaskId, nodesInitialized]);

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const semantic = changes.some((change) =>
        change.type === 'position' || change.type === 'remove' || change.type === 'add',
      );
      const update = (currentNodes: Node[]) => applyNodeChanges(changes, currentNodes);
      if (semantic) {
        setNodes(update);
      } else {
        setNodesSilently(update);
      }
    },
    [setNodes, setNodesSilently],
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setEdges((currentEdges) => applyEdgeChanges(changes, currentEdges));
    },
    [setEdges],
  );

  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      if (!params.source || !params.target) return;
      setEdges((currentEdges) =>
        addEdge(
          {
            ...params,
            type: 'default',
            animated: true,
            style: { stroke: '#111111', strokeWidth: 1.5 },
          },
          currentEdges,
        ),
      );
    },
    [setEdges],
  );

  const onNodesDelete = useCallback(
    (nodesToDelete: Node[]) => {
      nodesToDelete.forEach((node) => deleteNode(node.id));
    },
    [deleteNode],
  );

  const onInit = useCallback(
    (instance: ReactFlowInstance) => {
      setFlowInstance(instance);
      if (canvas?.viewport) {
        instance.setViewport(canvas.viewport);
      }
    },
    [canvas?.viewport],
  );

  const isValidConnection = useCallback((connection: Connection) => {
    return Boolean(connection.source && connection.target && connection.source !== connection.target);
  }, []);

  useEffect(() => {
    if (!selectedNodeId || !target || target.kind !== 'card') {
      setNodeHistory([]);
      setNodeHistoryStatus('');
      return;
    }
    let alive = true;
    setNodeHistoryStatus('读取中...');
    loadNodeHistory(target.value, selectedNodeId)
      .then((payload) => {
        if (!alive) return;
        setNodeHistory(Array.isArray(payload.entries) ? payload.entries : []);
        setNodeHistoryStatus('');
      })
      .catch((err) => {
        if (!alive) return;
        setNodeHistory([]);
        setNodeHistoryStatus(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, [selectedNodeId, target]);

  if (!canvas) {
    return (
      <div className="canvas-empty">
        <h2>Canvas is not loaded</h2>
      </div>
    );
  }

  return (
    <div className="canvas-shell" ref={shellRef}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onNodesDelete={onNodesDelete}
        onConnect={onConnect}
        onNodeClick={(_, node) => setSelectedNodeId(node.id)}
        onPaneClick={() => setSelectedNodeId('')}
        isValidConnection={isValidConnection}
        onInit={onInit}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={nodeTypes}
        deleteKeyCode={DELETE_KEY_CODE}
        proOptions={PRO_OPTIONS}
        minZoom={0.1}
        maxZoom={10}
        defaultViewport={DEFAULT_VIEWPORT}
      >
        <Background
          color="#d8d8d8"
          gap={24}
          size={1}
          variant={BackgroundVariant.Dots}
        />
        <Controls position="top-left" />
        <MiniMap
          position="bottom-right"
          zoomable
          pannable
          nodeColor="#111111"
          maskColor="rgba(255,255,255,0.72)"
        />
      </ReactFlow>
      {dropNotice && (
        <div className="canvas-drop-notice" role="alert">
          <span>{dropNotice}</span>
          <button type="button" onClick={() => setDropNotice('')}>知道了</button>
        </div>
      )}
      {selectedNodeId && target?.kind === 'card' && (
        <aside className="node-history-panel" aria-label="Node history">
          <div className="node-history-head">
            <strong>{selectedNodeId}</strong>
            <button type="button" onClick={() => setSelectedNodeId('')}>收起</button>
          </div>
          {nodeHistoryStatus && <div className="node-history-status">{nodeHistoryStatus}</div>}
          {!nodeHistoryStatus && nodeHistory.length === 0 && (
            <div className="node-history-status">暂无节点事件</div>
          )}
          <ol className="node-history-list">
            {nodeHistory.slice(-8).reverse().map((entry, idx) => (
              <li key={`${entry.ts || ''}:${entry.event}:${idx}`}>
                <strong>{entry.event || 'event'}</strong>
                <span>{[entry.ts, entry.actor].filter(Boolean).join(' · ')}</span>
                {entry.summary && <em>{entry.summary}</em>}
              </li>
            ))}
          </ol>
        </aside>
      )}
    </div>
  );
}

export default function Canvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasFlow {...props} />
    </ReactFlowProvider>
  );
}
