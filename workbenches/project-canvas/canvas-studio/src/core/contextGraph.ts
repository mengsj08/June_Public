import type { Canvas, CanvasNodeData, SourceRef } from '../types/canvas';

export const DEFAULT_CONTEXT_LIMIT = 10000;

export interface ContextGraphEntry {
  id: string;
  kind: string;
  title: string;
  summary: string;
  relation: string;
  path?: string;
  resolved_path?: string;
  status: string;
}

export interface UpstreamContextResult {
  count: number;
  entries: ContextGraphEntry[];
  unresolvedCount: number;
  truncated: boolean;
  originalLength: number;
}

function compactText(value: unknown, limit = 600): string {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 1)).trim()}…`;
}

function nodeContextEntry(node: Canvas['nodes'][number]): ContextGraphEntry {
  const data = (node.data || {}) as CanvasNodeData & Record<string, unknown>;
  const ref = (data.source_ref || undefined) as SourceRef | undefined;
  const kind = compactText(data.kind || ref?.kind || node?.type || 'node', 40);
  const title = compactText(data.title || data.label || ref?.label || node?.id || '未命名节点', 120);
  const summary = compactText(data.summary || data.text || data.content || data.url || '', 700);
  const relation = compactText(data.relation_note || ref?.reason || '', 360);
  return {
    id: node.id,
    kind,
    title,
    summary,
    relation,
    path: ref?.path,
    resolved_path: ref?.resolved_path,
    status: ref ? String(ref.status || 'missing') : 'resolved',
  };
}

export function buildUpstreamContext(
  canvas: Canvas | null,
  targetId: string,
  limit = DEFAULT_CONTEXT_LIMIT,
): UpstreamContextResult {
  if (!canvas) {
    return { count: 0, entries: [], unresolvedCount: 0, truncated: false, originalLength: 0 };
  }

  const nodesById = new Map((canvas.nodes || []).map((node) => [node.id, node]));
  const seen = new Set<string>();
  const entries: ContextGraphEntry[] = [];

  for (const edge of canvas.edges || []) {
    if (edge.target !== targetId || !edge.source || seen.has(edge.source)) continue;
    const sourceNode = nodesById.get(edge.source);
    if (!sourceNode) continue;
    seen.add(edge.source);
    entries.push(nodeContextEntry(sourceNode));
  }

  const originalLength = JSON.stringify(entries).length;
  let truncated = false;
  if (originalLength > limit) {
    truncated = true;
    while (entries.length > 0 && JSON.stringify(entries).length > limit) entries.pop();
  }

  const unresolvedCount = entries.filter(
    (entry) => !['resolved', 'corrected'].includes(String(entry.status)),
  ).length;

  return { count: entries.length, entries, unresolvedCount, truncated, originalLength };
}
