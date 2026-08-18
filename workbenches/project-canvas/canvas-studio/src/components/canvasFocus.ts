import type { Node } from 'reactflow';

const DEFAULT_NODE_WIDTH = 320;
const DEFAULT_NODE_HEIGHT = 150;

export const FOCUS_ZOOM = 1.15;
export const FOCUS_DURATION_MS = 420;
export const FOCUS_RETRY_MS = 60;
export const FOCUS_MAX_ATTEMPTS = 12;

type FocusNodeInput = Pick<Node, 'id' | 'data' | 'position' | 'width' | 'height'>;
type FocusMatchInput = Pick<Node, 'id' | 'data'>;
type ShellRect = Pick<DOMRectReadOnly, 'width' | 'height'>;

function positiveNumber(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export function findFocusNode<T extends FocusMatchInput>(
  nodes: readonly T[] | null | undefined,
  focusTaskId: string,
): T | null {
  const needle = String(focusTaskId || '').trim().toLowerCase();
  if (!needle) return null;
  const expectedId = `card-${needle}`;
  return (nodes || []).find((node) => {
    const data = node.data as { source_ref?: { task_id?: string } };
    const taskId = String(data?.source_ref?.task_id || '').trim().toLowerCase();
    return taskId === needle || String(node.id || '').toLowerCase() === expectedId;
  }) || null;
}

export function focusNodeCenter(node: FocusNodeInput) {
  const data = node.data as { width?: unknown; height?: unknown };
  const measuredWidth = positiveNumber(node.width);
  const measuredHeight = positiveNumber(node.height);
  const width = measuredWidth || positiveNumber(data?.width) || DEFAULT_NODE_WIDTH;
  const height = measuredHeight || positiveNumber(data?.height) || DEFAULT_NODE_HEIGHT;
  return {
    x: Number(node.position?.x || 0) + width / 2,
    y: Number(node.position?.y || 0) + height / 2,
    width,
    height,
    measured: Boolean(measuredWidth && measuredHeight),
  };
}

export function focusCenterCall(node: FocusNodeInput) {
  const center = focusNodeCenter(node);
  return {
    x: center.x,
    y: center.y,
    measured: center.measured,
    options: {
      zoom: FOCUS_ZOOM,
      duration: FOCUS_DURATION_MS,
    },
  };
}

export function focusShellReady(rect: ShellRect | null | undefined): boolean {
  return Boolean(rect && positiveNumber(rect.width) && positiveNumber(rect.height));
}
