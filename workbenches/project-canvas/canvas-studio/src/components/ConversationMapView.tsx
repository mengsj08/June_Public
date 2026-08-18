import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { loadConversationMap, openSource } from '../services/canvasApi';
import type {
  ConversationMapEdge,
  ConversationMapNode,
  ConversationMapPayload,
  ConversationMapSourceCommand,
} from '../services/canvasApi';
import {
  buildConversationNavigator,
  groupNodesByType,
  type NavigatorEdge,
  type NavigatorNode,
} from './conversationNavigator';

interface ConversationMapViewProps {
  manifestPath: string;
}

interface FlowNodeData {
  navNode: NavigatorNode;
  isCursor: boolean;
  isSelected: boolean;
  onToggleArtifactGroup: (node: NavigatorNode) => void;
}

interface HiddenManifestNode {
  index: number;
  reason: string;
  value: unknown;
}

const FLOW_NODE_WIDTH = 250;
const FLOW_X_STEP = 292;
const FLOW_Y_STEP = 94;
const FLOW_QUESTION_Y_STEP = 68;
const PRO_OPTIONS = { hideAttribution: true };

function shortMeta(value: string | undefined, fallback = 'unknown') {
  return String(value || '').trim() || fallback;
}

function sourceLabel(commands: ConversationMapSourceCommand[] | undefined) {
  return (commands || []).map((item) => item.anchor).filter(Boolean).join(', ');
}

function relationLabel(relation: string) {
  return {
    parent: 'parent',
    next: 'next',
    return_to: 'return',
    branch_from: 'branch',
    artifact_group: 'artifacts',
  }[relation] || relation;
}

function normalizeId(value: string | undefined) {
  return String(value || '').trim();
}

function partitionManifestNodes(value: unknown): {
  nodes: ConversationMapNode[];
  hidden: HiddenManifestNode[];
} {
  if (!Array.isArray(value)) return { nodes: [], hidden: [] };

  const nodes: ConversationMapNode[] = [];
  const hidden: HiddenManifestNode[] = [];
  const seenIds = new Set<string>();

  value.forEach((candidate, index) => {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
      hidden.push({ index, reason: 'node is not an object', value: candidate });
      return;
    }

    const id = normalizeId((candidate as { id?: string }).id);
    if (!id) {
      hidden.push({ index, reason: 'node id is empty', value: candidate });
      return;
    }
    if (seenIds.has(id)) {
      hidden.push({ index, reason: `duplicate node id: ${id}`, value: candidate });
      return;
    }

    seenIds.add(id);
    nodes.push(candidate as ConversationMapNode);
  });

  return { nodes, hidden };
}

function artifactGroupKeyForNode(node: ConversationMapNode | undefined) {
  if (!node || shortMeta(node.type) !== 'artifact' || !normalizeId(node.card)) return '';
  return `${normalizeId(node.parent) || normalizeId(node.branch_from)}::${normalizeId(node.card)}`;
}

function mapMarkdownPath(data: ConversationMapPayload) {
  const manifest = data.manifest_abs_path || data.manifest_path || '';
  if (!manifest) return '';
  if (manifest.endsWith('/manifest.yaml')) return manifest.replace(/manifest\.yaml$/, 'map.md');
  if (manifest.endsWith('manifest.yaml')) return manifest.replace(/manifest\.yaml$/, 'map.md');
  return `${manifest.replace(/\/$/, '')}/map.md`;
}

function backfilledArtifactNodes(nodes: ConversationMapNode[]) {
  const seenCards = new Set<string>();
  return nodes.filter((node) => {
    if (shortMeta(node.type) !== 'artifact' || shortMeta(node.status) !== 'recorded' || !node.card) return false;
    if (seenCards.has(node.card)) return false;
    seenCards.add(node.card);
    return true;
  });
}

function InlineSourceAnchors({ commands }: { commands: ConversationMapSourceCommand[] | undefined }) {
  const [copied, setCopied] = useState('');
  const items = commands || [];
  if (!items.length) return <span className="conv-source-muted">source: none</span>;
  return (
    <div className="conv-inline-sources">
      {items.map((item) => (
        <button
          className="conv-source-chip"
          key={`${item.anchor}:${item.command}`}
          onClick={(event) => {
            event.stopPropagation();
            if (!item.command) return;
            void navigator.clipboard?.writeText(item.command).then(() => setCopied(item.anchor));
          }}
          title={item.command || item.anchor}
          type="button"
        >
          {item.anchor}
        </button>
      ))}
      {copied && <span className="conv-source-muted">copied {copied}</span>}
    </div>
  );
}

function PlanList({
  title,
  label,
  items,
  selectedId,
  onSelect,
}: {
  title: string;
  label: string;
  items: ConversationMapNode[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="conv-plan-list">
      <div className="conv-plan-title">
        <span>{title}</span>
        <em>{label}</em>
      </div>
      {items.length ? items.map((node) => (
        <button
          className={`conv-plan-item${selectedId === node.id ? ' is-selected' : ''}`}
          key={node.id}
          onClick={() => onSelect(node.id)}
          type="button"
        >
          <div className="conv-plan-main">
            <strong>{node.title}</strong>
            <span>{shortMeta(node.type)} · {shortMeta(node.status)}{node.card ? ` · ${node.card}` : ''}</span>
          </div>
          <p>{node.summary || '无 summary'}</p>
          <InlineSourceAnchors commands={node.source_commands} />
        </button>
      )) : (
        <div className="conv-empty">暂无条目</div>
      )}
    </section>
  );
}

function SourceCommands({ commands }: { commands: ConversationMapSourceCommand[] | undefined }) {
  const [copied, setCopied] = useState('');
  const items = commands || [];
  if (!items.length) return <div className="conv-empty">无 source anchor</div>;
  return (
    <div className="conv-source-list">
      {items.map((item) => (
        <button
          className="conv-source-command"
          key={`${item.anchor}:${item.command}`}
          onClick={() => {
            if (!item.command) return;
            void navigator.clipboard?.writeText(item.command).then(() => setCopied(item.anchor));
          }}
          type="button"
        >
          <span>{item.anchor}</span>
          <code>{item.command || '无法生成 sed 命令'}</code>
        </button>
      ))}
      {copied && <div className="conv-copied">copied {copied}</div>}
    </div>
  );
}

function NodeDetail({
  navNode,
  sourceNode,
  onSelect,
}: {
  navNode: NavigatorNode | null;
  sourceNode: ConversationMapNode | null;
  onSelect: (id: string) => void;
}) {
  if (navNode?.kind === 'artifact_group') {
    return (
      <aside className="conv-detail">
        <div className="conv-section-title">Inspector</div>
        <div className="conv-detail-head">
          <span>artifact group</span>
          <em>{navNode.childCount || navNode.itemIds.length} items</em>
        </div>
        <h2>{navNode.title}</h2>
        <p>{navNode.summary || '同卡执行 artifact 已折叠。点击节点可展开到单个 artifact。'}</p>
        <dl className="conv-node-meta">
          {navNode.card && (
            <div>
              <dt>card</dt>
              <dd>{navNode.card}</dd>
            </div>
          )}
          <div>
            <dt>items</dt>
            <dd>{navNode.itemIds.join(', ')}</dd>
          </div>
        </dl>
        <div className="conv-section-title">展开后选择</div>
        <div className="conv-artifact-list">
          {navNode.itemIds.map((id) => (
            <button key={id} onClick={() => onSelect(id)} type="button">{id}</button>
          ))}
        </div>
      </aside>
    );
  }

  if (!sourceNode) {
    return (
      <aside className="conv-detail">
        <div className="conv-section-title">Inspector</div>
        <div className="conv-empty">选择一个节点</div>
      </aside>
    );
  }
  return (
    <aside className="conv-detail">
      <div className="conv-section-title">Inspector</div>
      <div className="conv-detail-head">
        <span>{shortMeta(sourceNode.type)}</span>
        <em>{shortMeta(sourceNode.status)}</em>
      </div>
      <h2>{sourceNode.title}</h2>
      <p>{sourceNode.summary || '无 summary'}</p>
      <dl className="conv-node-meta">
        <div>
          <dt>id</dt>
          <dd>{sourceNode.id}</dd>
        </div>
        {sourceNode.card && (
          <div>
            <dt>card</dt>
            <dd>{sourceNode.card}</dd>
          </div>
        )}
        {sourceNode.parent && (
          <div>
            <dt>parent</dt>
            <dd>{sourceNode.parent}</dd>
          </div>
        )}
        {sourceNode.branch_from && (
          <div>
            <dt>branch_from</dt>
            <dd>{sourceNode.branch_from}</dd>
          </div>
        )}
        {sourceNode.return_to && (
          <div>
            <dt>return_to</dt>
            <dd>{sourceNode.return_to}</dd>
          </div>
        )}
      </dl>
      <div className="conv-section-title">source</div>
      <SourceCommands commands={sourceNode.source_commands} />
    </aside>
  );
}

function EdgeList({ edges, nodeById }: { edges: ConversationMapEdge[]; nodeById: Map<string, ConversationMapNode> }) {
  if (!edges.length) return <div className="conv-empty">暂无边</div>;
  return (
    <div className="conv-edge-list">
      {edges.map((edge) => (
        <div className={`conv-edge conv-edge-${edge.relation}`} key={edge.id}>
          <span>{nodeById.get(edge.source)?.title || edge.source}</span>
          <em>{relationLabel(edge.relation)}</em>
          <span>{nodeById.get(edge.target)?.title || edge.target}</span>
        </div>
      ))}
    </div>
  );
}

function ConversationFlowNode({ data }: NodeProps<FlowNodeData>) {
  const nav = data.navNode;
  const foldedQuestion = nav.type === 'question' && nav.status === 'folded';
  return (
    <div
      className={[
        'conv-flow-node',
        `type-${nav.type}`,
        nav.kind === 'artifact_group' ? 'is-artifact-group' : '',
        foldedQuestion ? 'is-folded-question' : '',
        data.isCursor ? 'is-cursor' : '',
        data.isSelected ? 'is-selected' : '',
      ].filter(Boolean).join(' ')}
    >
      <Handle className="conv-flow-handle" position={Position.Left} type="target" />
      <div className="conv-flow-meta">
        <span>{nav.kind === 'artifact_group' ? 'artifact' : nav.type}</span>
        <em>{nav.status || 'unknown'}</em>
      </div>
      <strong>{nav.title}</strong>
      {!foldedQuestion && <p>{nav.summary || '无 summary'}</p>}
      <div className="conv-flow-foot">
        {nav.card && <span>{nav.card}</span>}
        {data.isCursor && <em>你在这里</em>}
        {nav.kind === 'artifact_group' && (
          <button
            className="conv-artifact-expand nodrag"
            onClick={(event) => {
              event.stopPropagation();
              data.onToggleArtifactGroup(nav);
            }}
            type="button"
          >
            展开 {nav.childCount || nav.itemIds.length}
          </button>
        )}
      </div>
      <Handle className="conv-flow-handle" position={Position.Right} type="source" />
    </div>
  );
}

const nodeTypes = { conversation: ConversationFlowNode };

function toFlowEdge(edge: NavigatorEdge, selectedId: string): FlowEdge {
  const isReturn = edge.relation === 'return_to';
  const isBranch = edge.relation === 'branch_from';
  const isNext = edge.relation === 'next';
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    animated: false,
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#2a2a28' },
    label: edge.relation === 'parent' ? undefined : relationLabel(edge.relation),
    className: [
      'conv-flow-edge',
      `is-${edge.relation}`,
      selectedId && (edge.source === selectedId || edge.target === selectedId) ? 'is-adjacent' : '',
    ].filter(Boolean).join(' '),
    style: {
      stroke: selectedId && (edge.source === selectedId || edge.target === selectedId) ? '#111111' : '#7a7a74',
      strokeDasharray: isReturn ? '6 5' : isBranch || isNext ? '3 4' : undefined,
      strokeWidth: selectedId && (edge.source === selectedId || edge.target === selectedId) ? 1.8 : 1.1,
    },
  };
}

function nodeY(nav: NavigatorNode) {
  return nav.order * (nav.type === 'question' && nav.status === 'folded' ? FLOW_QUESTION_Y_STEP : FLOW_Y_STEP);
}

function RawPanel({
  data,
  selectedId,
  nodeById,
  onSelect,
}: {
  data: ConversationMapPayload;
  selectedId: string;
  nodeById: Map<string, ConversationMapNode>;
  onSelect: (id: string) => void;
}) {
  const groups = groupNodesByType(data.nodes || []);
  return (
    <section className="conv-raw">
      <div className="conv-raw-groups">
        {groups.map(([type, items]) => (
          <section className="conv-group" key={type}>
            <header>
              <span>{type}</span>
              <em>{items.length}</em>
            </header>
            {items.map((node) => (
              <button
                className={`conv-node${selectedId === node.id ? ' is-selected' : ''}${data.current_cursor?.node === node.id ? ' is-cursor' : ''}`}
                key={node.id}
                onClick={() => onSelect(node.id)}
                type="button"
              >
                <span>{shortMeta(node.status)}</span>
                <strong>{node.title}</strong>
                <em>{sourceLabel(node.source_commands)}</em>
              </button>
            ))}
          </section>
        ))}
      </div>
      <div className="conv-section-title">边</div>
      <EdgeList edges={data.edges || []} nodeById={nodeById} />
      <div className="conv-section-title">manifest JSON</div>
      <pre className="conv-json">{JSON.stringify(data, null, 2)}</pre>
    </section>
  );
}

export default function ConversationMapView({ manifestPath }: ConversationMapViewProps) {
  const [data, setData] = useState<ConversationMapPayload | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [expandedArtifactGroups, setExpandedArtifactGroups] = useState<Set<string>>(() => new Set());
  const [activeTab, setActiveTab] = useState<'map' | 'raw'>('map');
  const [error, setError] = useState('');
  const [openError, setOpenError] = useState('');

  useEffect(() => {
    let alive = true;
    setError('');
    setOpenError('');
    setData(null);
    setExpandedArtifactGroups(new Set());
    loadConversationMap(manifestPath)
      .then((payload) => {
        if (!alive) return;
        setData(payload);
        setSelectedId(String(payload.current_cursor?.node || payload.plan?.steps?.[0] || payload.nodes?.[0]?.id || ''));
      })
      .catch((err) => {
        if (!alive) return;
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, [manifestPath]);

  const nodePartition = useMemo(() => partitionManifestNodes(data?.nodes), [data?.nodes]);
  const nodes = nodePartition.nodes;
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const navigatorData = useMemo(() => (
    data ? { ...data, nodes } : null
  ), [data, nodes]);
  const model = useMemo(() => (
    navigatorData ? buildConversationNavigator(navigatorData, expandedArtifactGroups) : null
  ), [expandedArtifactGroups, navigatorData]);
  const navNodeById = useMemo(() => new Map((model?.nodes || []).map((node) => [node.id, node])), [model]);

  useEffect(() => {
    if (!data || !nodePartition.hidden.length) return;
    console.warn(
      `[ConversationMapView] 已隐藏 ${nodePartition.hidden.length} 个无法解析的节点`,
      nodePartition.hidden,
    );
  }, [data, nodePartition.hidden]);

  const revealNode = useCallback((id: string) => {
    const sourceNode = nodeById.get(id);
    const groupKey = artifactGroupKeyForNode(sourceNode);
    if (groupKey) {
      setExpandedArtifactGroups((previous) => {
        const next = new Set(previous);
        next.add(groupKey);
        return next;
      });
    }
    setSelectedId(id);
  }, [nodeById]);

  const toggleArtifactGroup = useCallback((nav: NavigatorNode) => {
    const key = nav.id.replace(/^artifact-group:/, '');
    setExpandedArtifactGroups((previous) => {
      const next = new Set(previous);
      next.add(key);
      return next;
    });
    setSelectedId(nav.itemIds[0] || nav.id);
  }, []);

  const selectedNav = selectedId ? navNodeById.get(selectedId) || null : null;
  const selectedSource = selectedNav?.sourceNode || nodeById.get(selectedId) || null;
  const currentCursorId = normalizeId(data?.current_cursor?.node);

  const flowNodes = useMemo<FlowNode<FlowNodeData>[]>(() => {
    if (!model) return [];
    return model.nodes.map((nav) => ({
      id: nav.id,
      type: 'conversation',
      data: {
        navNode: nav,
        isCursor: nav.id === currentCursorId,
        isSelected: nav.id === selectedId,
        onToggleArtifactGroup: toggleArtifactGroup,
      },
      draggable: false,
      position: {
        x: nav.depth * FLOW_X_STEP,
        y: nodeY(nav),
      },
      style: {
        width: FLOW_NODE_WIDTH,
      },
    }));
  }, [currentCursorId, model, selectedId, toggleArtifactGroup]);

  const flowEdges = useMemo<FlowEdge[]>(() => {
    if (!model) return [];
    return [
      ...model.treeEdges.map((edge) => toFlowEdge(edge, selectedId)),
      ...model.nextEdges.map((edge) => toFlowEdge(edge, selectedId)),
      ...model.returnEdges.map((edge) => toFlowEdge(edge, selectedId)),
    ];
  }, [model, selectedId]);

  const onFlowInit = useCallback((instance: ReactFlowInstance) => {
    window.requestAnimationFrame(() => {
      window.setTimeout(() => {
        instance.fitView({ padding: 0.08, duration: 220 });
      }, 80);
    });
  }, []);

  if (error) {
    return <div className="conv-status">Conversation Map load failed: {error}</div>;
  }
  if (!data || !navigatorData || !model) {
    return <div className="conv-status">Loading conversation map...</div>;
  }

  const mapPath = mapMarkdownPath(data);
  const backfilled = backfilledArtifactNodes(nodes);
  const canvasScope = data.canvas_scope || data.thread?.id || manifestPath;
  const canvasHref = `${import.meta.env.BASE_URL}?convmap=${encodeURIComponent(canvasScope)}`;

  return (
    <main className="conv-app">
      <header className="conv-cursor-bar">
        <div className="conv-cursor-title">
          <span>Conversation Map · read only</span>
          <h1>{data.thread?.title || manifestPath}</h1>
          <a className="conv-canvas-link" href={canvasHref}>
            在画布中打开
          </a>
          <BoardLink className="conv-canvas-link" />
        </div>
        <div className="conv-cursor-links">
          <button onClick={() => revealNode(model.cursor.currentId)} type="button">
            <span>当前在</span>
            <strong>{model.cursor.currentTitle}</strong>
          </button>
          <button disabled={!model.cursor.branchFromId} onClick={() => revealNode(model.cursor.branchFromId)} type="button">
            <span>从哪分支</span>
            <strong>{model.cursor.branchFromTitle}</strong>
          </button>
          <button disabled={!model.cursor.returnToId} onClick={() => revealNode(model.cursor.returnToId)} type="button">
            <span>若回主线</span>
            <strong>{model.cursor.returnToTitle}</strong>
          </button>
        </div>
        <p>{data.current_cursor?.why || 'Derived navigation view. Source anchors point back to raw rollout lines.'}</p>
      </header>

      <nav className="conv-tabs" aria-label="Conversation map views">
        <button className={activeTab === 'map' ? 'is-active' : ''} onClick={() => setActiveTab('map')} type="button">
          Plan+Map
        </button>
        <button className={activeTab === 'raw' ? 'is-active' : ''} onClick={() => setActiveTab('raw')} type="button">
          Raw
        </button>
        <span>{data.node_count || nodes.length} nodes · {data.manifest_path}</span>
        {nodePartition.hidden.length > 0 && (
          <span role="status">已隐藏 {nodePartition.hidden.length} 个无法解析的节点</span>
        )}
      </nav>

      {activeTab === 'map' ? (
        <section className="conv-main-grid">
          <aside className="conv-plan-column">
            <PlanList
              title="前提"
              label="decisions"
              items={data.plan?.premise_nodes || []}
              selectedId={selectedId}
              onSelect={revealNode}
            />
            <PlanList
              title="下一步"
              label="next"
              items={data.plan?.step_nodes || []}
              selectedId={selectedId}
              onSelect={revealNode}
            />
            <PlanList
              title="已补账卡"
              label="recorded artifacts"
              items={backfilled}
              selectedId={selectedId}
              onSelect={revealNode}
            />
          </aside>
          <section className="conv-map-panel">
            <div className="conv-section-title">Map</div>
            <div className="conv-flow-shell">
              <ReactFlowProvider>
                <ReactFlow
                  edges={flowEdges}
                  edgesFocusable={false}
                  elementsSelectable
                  fitView
                  fitViewOptions={{ padding: 0.08 }}
                  maxZoom={1.25}
                  minZoom={0.1}
                  nodes={flowNodes}
                  nodesConnectable={false}
                  nodesDraggable={false}
                  nodeTypes={nodeTypes}
                  onInit={onFlowInit}
                  onNodeClick={(_, node) => setSelectedId(node.id)}
                  panOnDrag
                  proOptions={PRO_OPTIONS}
                  zoomOnDoubleClick={false}
                >
                  <Background color="#d6d6d2" gap={24} variant={BackgroundVariant.Dots} />
                  <MiniMap
                    maskColor="rgba(243, 243, 241, 0.72)"
                    nodeBorderRadius={0}
                    nodeColor={(node) => (node.data?.isCursor ? '#111111' : '#fbfbfa')}
                    nodeStrokeColor="#6d6d68"
                    pannable
                    zoomable
                  />
                  <Controls showInteractive={false} />
                </ReactFlow>
              </ReactFlowProvider>
            </div>
          </section>
          <NodeDetail navNode={selectedNav} sourceNode={selectedSource} onSelect={revealNode} />
        </section>
      ) : (
        <RawPanel data={navigatorData} selectedId={selectedId} nodeById={nodeById} onSelect={revealNode} />
      )}

      <footer className="conv-footer">
        <button
          disabled={!mapPath}
          onClick={() => {
            setOpenError('');
            if (mapPath) void openSource(mapPath).catch((err) => setOpenError(err instanceof Error ? err.message : String(err)));
          }}
          type="button"
        >
          打开 map.md
        </button>
        {openError && <span>{openError}</span>}
      </footer>
    </main>
  );
}
