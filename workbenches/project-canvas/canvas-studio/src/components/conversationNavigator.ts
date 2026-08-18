import type { ConversationMapNode, ConversationMapPayload } from '../services/canvasApi';

export interface NavigatorNode {
  id: string;
  kind: 'node' | 'artifact_group';
  title: string;
  type: string;
  status: string;
  summary: string;
  card?: string;
  sourceNode?: ConversationMapNode;
  itemIds: string[];
  depth: number;
  order: number;
  collapsed?: boolean;
  childCount?: number;
}

export interface NavigatorEdge {
  id: string;
  source: string;
  target: string;
  relation: 'parent' | 'branch_from' | 'return_to' | 'next' | 'artifact_group';
}

export interface CursorTrail {
  currentId: string;
  currentTitle: string;
  branchFromId: string;
  branchFromTitle: string;
  returnToId: string;
  returnToTitle: string;
}

export interface NavigatorModel {
  nodes: NavigatorNode[];
  treeEdges: NavigatorEdge[];
  returnEdges: NavigatorEdge[];
  nextEdges: NavigatorEdge[];
  roots: string[];
  cursor: CursorTrail;
}

export const TYPE_ORDER = ['mainline', 'decision', 'next', 'artifact', 'question', 'branch', 'parked'];

function clean(value: unknown): string {
  return String(value || '').trim();
}

function nodeTitle(node: ConversationMapNode | undefined, fallback = ''): string {
  return clean(node?.title) || fallback || clean(node?.id) || 'unknown';
}

function nodeSortValue(node: ConversationMapNode, index: Map<string, number>): number {
  const type = clean(node.type);
  const rank = TYPE_ORDER.includes(type) ? TYPE_ORDER.indexOf(type) : 99;
  return rank * 1000 + (index.get(node.id) ?? 999);
}

function primaryParent(node: ConversationMapNode): string {
  return clean(node.parent) || clean(node.branch_from);
}

function artifactGroupKey(node: ConversationMapNode): string {
  if (clean(node.type) !== 'artifact' || !clean(node.card)) return '';
  return `${primaryParent(node)}::${clean(node.card)}`;
}

function descendantsOf(id: string, children: Map<string, ConversationMapNode[]>): string[] {
  const out: string[] = [];
  const walk = (nodeId: string) => {
    (children.get(nodeId) || []).forEach((child) => {
      out.push(child.id);
      walk(child.id);
    });
  };
  walk(id);
  return out;
}

function addEdge(
  edges: NavigatorEdge[],
  seen: Set<string>,
  source: string,
  target: string,
  relation: NavigatorEdge['relation'],
) {
  if (!source || !target || source === target) return;
  const id = `${relation}:${source}->${target}`;
  if (seen.has(id)) return;
  seen.add(id);
  edges.push({ id, source, target, relation });
}

export function groupNodesByType(nodes: ConversationMapNode[]) {
  const groups = new Map<string, ConversationMapNode[]>();
  nodes.forEach((node) => {
    const type = clean(node.type) || 'unknown';
    groups.set(type, [...(groups.get(type) || []), node]);
  });
  return Array.from(groups.entries()).sort((a, b) => {
    const ia = TYPE_ORDER.includes(a[0]) ? TYPE_ORDER.indexOf(a[0]) : 99;
    const ib = TYPE_ORDER.includes(b[0]) ? TYPE_ORDER.indexOf(b[0]) : 99;
    return ia - ib || a[0].localeCompare(b[0]);
  });
}

export function buildConversationNavigator(
  payload: Pick<ConversationMapPayload, 'nodes' | 'current_cursor'>,
  expandedArtifactGroups: ReadonlySet<string> = new Set(),
): NavigatorModel {
  const sourceNodes = payload.nodes || [];
  const byId = new Map(sourceNodes.map((node) => [node.id, node]));
  const originalIndex = new Map(sourceNodes.map((node, idx) => [node.id, idx]));
  const children = new Map<string, ConversationMapNode[]>();
  const childIds = new Set<string>();

  sourceNodes.forEach((node) => {
    const parentId = primaryParent(node);
    if (!parentId || !byId.has(parentId)) return;
    childIds.add(node.id);
    children.set(parentId, [...(children.get(parentId) || []), node]);
  });

  children.forEach((items, key) => {
    children.set(key, items.slice().sort((a, b) => nodeSortValue(a, originalIndex) - nodeSortValue(b, originalIndex)));
  });

  const roots = sourceNodes
    .filter((node) => !childIds.has(node.id))
    .sort((a, b) => nodeSortValue(a, originalIndex) - nodeSortValue(b, originalIndex))
    .map((node) => node.id);

  const treeNodes: NavigatorNode[] = [];
  const treeEdges: NavigatorEdge[] = [];
  const returnEdges: NavigatorEdge[] = [];
  const nextEdges: NavigatorEdge[] = [];
  const seenEdges = new Set<string>();
  const groupedArtifacts = new Map<string, ConversationMapNode[]>();

  sourceNodes.forEach((node) => {
    const key = artifactGroupKey(node);
    if (key) groupedArtifacts.set(key, [...(groupedArtifacts.get(key) || []), node]);
  });

  const hiddenByCollapsed = new Set<string>();
  groupedArtifacts.forEach((items, key) => {
    if (items.length < 2 || expandedArtifactGroups.has(key)) return;
    items.forEach((item) => {
      hiddenByCollapsed.add(item.id);
      descendantsOf(item.id, children).forEach((childId) => hiddenByCollapsed.add(childId));
    });
  });

  const visit = (node: ConversationMapNode, depth: number) => {
    if (hiddenByCollapsed.has(node.id)) return;
    const parentId = primaryParent(node);
    const grouped = new Set<string>();
    treeNodes.push({
      id: node.id,
      kind: 'node',
      title: nodeTitle(node),
      type: clean(node.type) || 'unknown',
      status: clean(node.status),
      summary: clean(node.summary),
      card: clean(node.card) || undefined,
      sourceNode: node,
      itemIds: [node.id],
      depth,
      order: treeNodes.length,
      childCount: (children.get(node.id) || []).length,
    });
    if (parentId && byId.has(parentId)) {
      addEdge(treeEdges, seenEdges, parentId, node.id, clean(node.parent) ? 'parent' : 'branch_from');
    }
    (children.get(node.id) || []).forEach((child) => {
      const key = artifactGroupKey(child);
      const artifacts = key ? groupedArtifacts.get(key) || [] : [];
      if (key && artifacts.length > 1 && !expandedArtifactGroups.has(key)) {
        if (grouped.has(key)) return;
        grouped.add(key);
        const card = clean(child.card);
        const groupId = `artifact-group:${key}`;
        treeNodes.push({
          id: groupId,
          kind: 'artifact_group',
          title: `${card} execution artifacts`,
          type: 'artifact',
          status: 'collapsed',
          summary: artifacts.map((item) => nodeTitle(item)).join(' / '),
          card,
          itemIds: artifacts.map((item) => item.id),
          depth: depth + 1,
          order: treeNodes.length,
          collapsed: true,
          childCount: artifacts.length,
        });
        addEdge(treeEdges, seenEdges, node.id, groupId, 'artifact_group');
        return;
      }
      visit(child, depth + 1);
    });
  };

  roots.forEach((rootId) => {
    const root = byId.get(rootId);
    if (root) visit(root, 0);
  });

  sourceNodes.forEach((node) => {
    const branch = clean(node.branch_from);
    if (branch && byId.has(branch) && branch !== primaryParent(node) && !hiddenByCollapsed.has(node.id)) {
      addEdge(treeEdges, seenEdges, branch, node.id, 'branch_from');
    }
    const ret = clean(node.return_to);
    if (ret && byId.has(ret) && !hiddenByCollapsed.has(node.id)) {
      addEdge(returnEdges, seenEdges, node.id, ret, 'return_to');
    }
    (node.next_nodes || []).forEach((target) => {
      if (byId.has(target) && primaryParent(byId.get(target) as ConversationMapNode) !== node.id) {
        addEdge(nextEdges, seenEdges, node.id, target, 'next');
      }
    });
  });

  const cursorId = clean(payload.current_cursor?.node);
  const cursorNode = byId.get(cursorId);
  const branchNode = cursorNode?.branch_from ? byId.get(cursorNode.branch_from) : undefined;
  const returnNode = cursorNode?.return_to
    ? byId.get(cursorNode.return_to)
    : payload.current_cursor?.return_to_if_resuming_prior_work
      ? byId.get(payload.current_cursor.return_to_if_resuming_prior_work)
      : undefined;
  return {
    nodes: treeNodes,
    treeEdges,
    returnEdges,
    nextEdges,
    roots,
    cursor: {
      currentId: cursorId,
      currentTitle: nodeTitle(cursorNode, cursorId || 'none'),
      branchFromId: clean(cursorNode?.branch_from),
      branchFromTitle: nodeTitle(branchNode, clean(cursorNode?.branch_from) || 'none'),
      returnToId: clean(cursorNode?.return_to || payload.current_cursor?.return_to_if_resuming_prior_work),
      returnToTitle: nodeTitle(returnNode, clean(cursorNode?.return_to || payload.current_cursor?.return_to_if_resuming_prior_work) || 'none'),
    },
  };
}
