import { create } from 'zustand';
import type { Edge, Node, XYPosition } from 'reactflow';
import * as canvasApi from '../services/canvasApi';
import type { Canvas, SourceRef } from '../types/canvas';
import type { CanvasTarget } from '../services/canvasApi';

const emptyCanvas = (path: string): Canvas => ({
  id: path || 'local',
  name: path ? path.split('/').pop() || path : 'Canvas',
  schema: 'kanban.canvas/v1',
  nodes: [],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 0.65 },
});

const normalizeCanvas = (payload: unknown, path: string): Canvas => {
  const wrapper = payload && typeof payload === 'object' ? payload as { canvas?: unknown } : {};
  const rawValue = wrapper.canvas ?? payload;
  const raw = rawValue && typeof rawValue === 'object' ? rawValue as Partial<Canvas> & Record<string, unknown> : {};
  return {
    ...emptyCanvas(path),
    ...raw,
    id: typeof raw.id === 'string' ? raw.id : path,
    name: typeof raw.name === 'string'
      ? raw.name
      : typeof raw.title === 'string'
        ? raw.title
        : emptyCanvas(path).name,
    nodes: Array.isArray(raw.nodes) ? raw.nodes as Canvas['nodes'] : [],
    edges: Array.isArray(raw.edges) ? raw.edges as Canvas['edges'] : [],
    viewport: raw.viewport && typeof raw.viewport === 'object'
      ? raw.viewport as Canvas['viewport']
      : { x: 0, y: 0, zoom: 0.65 },
  };
};

const canvasRevFromPayload = (payload: unknown): string => {
  if (!payload || typeof payload !== 'object') return '';
  const record = payload as { canvas_rev?: unknown; rev?: unknown };
  return typeof record.canvas_rev === 'string'
    ? record.canvas_rev
    : typeof record.rev === 'string'
      ? record.rev
      : '';
};

const CONFLICT_RELOAD_MESSAGE = '画布已被其它会话保存，已重拉服务端最新版本；请基于最新画布重新操作。';
const CONFLICT_KEEP_LOCAL_MESSAGE = '画布已被其它会话或 AI 更新；本地未保存构图已保留，自动保存已暂停，请人工核对后再决定。';
const AUTO_SAVE_DELAY_MS = 900;

export type CanvasSaveStatus = 'saved' | 'saving' | 'failed' | 'conflict';

let autoSaveTimer: number | null = null;
let activeSave: Promise<boolean> | null = null;

function clearAutoSaveTimer() {
  if (autoSaveTimer !== null) {
    window.clearTimeout(autoSaveTimer);
    autoSaveTimer = null;
  }
}

async function latestPayloadAfterConflict(target: CanvasTarget, payload: canvasApi.ApiJson): Promise<canvasApi.ApiJson> {
  if (payload.canvas && typeof payload.canvas === 'object') return payload;
  return canvasApi.load(target);
}

function stableNodeKey(node: Node | null | undefined): string {
  const volatileKeys = new Set(['selected', 'dragging', 'resizing', 'positionAbsolute']);
  const stable = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(stable);
    if (value && typeof value === 'object') {
      return Object.keys(value as Record<string, unknown>)
        .filter((key) => !volatileKeys.has(key))
        .sort()
        .reduce<Record<string, unknown>>((acc, key) => {
          acc[key] = stable((value as Record<string, unknown>)[key]);
          return acc;
        }, {});
    }
    return value;
  };
  try {
    return JSON.stringify(stable(node || null));
  } catch {
    return JSON.stringify(node || null);
  }
}

function stableEdgeKey(edge: Edge | null | undefined): string {
  if (!edge) return 'null';
  const stable = { ...edge };
  delete stable.selected;
  return JSON.stringify(stable);
}

function cloneNodeMap(nodes: Node[]): Record<string, Node> {
  return nodes.reduce<Record<string, Node>>((acc, node) => {
    acc[node.id] = JSON.parse(JSON.stringify(node));
    return acc;
  }, {});
}

function changedExistingNodeIds(prev: Node[], next: Node[], saved: Record<string, Node>): string[] {
  const prevById = new Map(prev.map((node) => [node.id, node]));
  const ids = new Set<string>();
  next.forEach((node) => {
    if (!saved[node.id] || !prevById.has(node.id)) return;
    if (stableNodeKey(prevById.get(node.id)) !== stableNodeKey(node)) ids.add(node.id);
  });
  return Array.from(ids);
}

interface CanvasStoreState {
  target: CanvasTarget | null;
  path: string;
  targetKind: '' | CanvasTarget['kind'];
  canvas: Canvas | null;
  canvasExists: boolean;
  baseRev: string;
  savedNodesById: Record<string, Node>;
  dirtyNodeIds: string[];
  requiresFullSave: boolean;
  loading: boolean;
  dirty: boolean;
  saveStatus: CanvasSaveStatus;
  saveError: string | null;
  changeVersion: number;
  error: string | null;
  loadFromApi: (target: CanvasTarget) => Promise<void>;
  saveToApi: () => Promise<boolean>;
  generateFromApi: () => Promise<void>;
  refreshProjectMapFromApi: () => Promise<canvasApi.ApiJson | null>;
  setNodes: (nodes: Node[] | ((nodes: Node[]) => Node[])) => void;
  setNodesSilently: (nodes: Node[] | ((nodes: Node[]) => Node[])) => void;
  setEdges: (edges: Edge[] | ((edges: Edge[]) => Edge[])) => void;
  updateNodePosition: (id: string, position: XYPosition) => void;
  addNode: (node: Node) => void;
  deleteNode: (id: string) => void;
  setNodeHidden: (id: string, hidden: boolean) => void;
  setFileLibrary: (entries: Record<string, unknown>[]) => void;
  updateRefSourceRef: (id: string, sourceRef: SourceRef) => void;
  markDirty: () => void;
}

export const useCanvasStore = create<CanvasStoreState>((set, get) => ({
  target: null,
  path: '',
  targetKind: '',
  canvas: null,
  canvasExists: false,
  baseRev: '',
  savedNodesById: {},
  dirtyNodeIds: [],
  requiresFullSave: false,
  loading: false,
  dirty: false,
  saveStatus: 'saved',
  saveError: null,
  changeVersion: 0,
  error: null,

  loadFromApi: async (target: CanvasTarget) => {
    clearAutoSaveTimer();
    const path = target.kind === 'card' ? target.value : '';
    set({ target, path, targetKind: target.kind, loading: true, error: null, saveError: null });
    try {
      const payload = await canvasApi.load(target);
      if (payload.exists === false) {
        set({
          canvas: emptyCanvas(target.value),
          canvasExists: false,
          baseRev: '',
          savedNodesById: {},
          dirtyNodeIds: [],
          requiresFullSave: false,
          loading: false,
          dirty: false,
          saveStatus: 'saved',
          changeVersion: 0,
        });
        return;
      }
      const loadedCanvas = normalizeCanvas(payload, target.value);
      set({
        canvas: loadedCanvas,
        canvasExists: payload.exists !== false,
        baseRev: canvasRevFromPayload(payload),
        savedNodesById: cloneNodeMap(loadedCanvas.nodes),
        dirtyNodeIds: [],
        requiresFullSave: false,
        loading: false,
        dirty: false,
        saveStatus: 'saved',
        changeVersion: 0,
      });
    } catch (error) {
      set({
        canvas: emptyCanvas(target.value),
        canvasExists: false,
        baseRev: '',
        savedNodesById: {},
        dirtyNodeIds: [],
        requiresFullSave: false,
        loading: false,
        dirty: false,
        saveStatus: 'failed',
        saveError: error instanceof Error ? error.message : String(error),
        error: error instanceof Error ? error.message : String(error),
      });
    }
  },

  saveToApi: async () => {
    if (activeSave) return activeSave;
    const run = async (): Promise<boolean> => {
      const { target, canvas, baseRev, dirtyNodeIds, requiresFullSave, savedNodesById, changeVersion } = get();
      if (!target || !canvas) return false;
      if (get().saveStatus === 'conflict') return false;
      clearAutoSaveTimer();
      set({ saveStatus: 'saving', saveError: null, error: null });
      try {
      let payload: canvasApi.ApiJson | null = null;
      if (target.kind === 'card' && !requiresFullSave && dirtyNodeIds.length > 0) {
        const localNodesById = cloneNodeMap(canvas.nodes);
        let nextBaseRev = baseRev;
        for (const nodeId of dirtyNodeIds) {
          const currentNode = localNodesById[nodeId];
          const baseNode = savedNodesById[nodeId];
          if (!currentNode || !baseNode) continue;
          payload = await canvasApi.saveNode(
            target,
            nodeId,
            currentNode,
            baseNode,
            nextBaseRev,
          );
          nextBaseRev = canvasRevFromPayload(payload);
        }
      } else {
        payload = await canvasApi.save(target, canvas, baseRev);
      }
      if (!payload) {
        set({ dirty: false, dirtyNodeIds: [], requiresFullSave: false, saveStatus: 'saved' });
        return true;
      }
      const savedCanvas = normalizeCanvas(payload?.canvas ?? canvas, target.value);
      set((state) => ({
        canvas: state.changeVersion === changeVersion ? savedCanvas : state.canvas,
        canvasExists: true,
        baseRev: canvasRevFromPayload(payload),
        savedNodesById: cloneNodeMap(savedCanvas.nodes),
        dirtyNodeIds: state.changeVersion === changeVersion ? [] : state.dirtyNodeIds,
        requiresFullSave: state.changeVersion === changeVersion ? false : state.requiresFullSave,
        dirty: state.changeVersion !== changeVersion,
        saveStatus: state.changeVersion === changeVersion ? 'saved' : 'saving',
        saveError: null,
      }));
      return true;
      } catch (error) {
        if (error instanceof canvasApi.CanvasConflictError) {
          set({
            canvasExists: true,
            dirty: true,
            saveStatus: 'conflict',
            saveError: CONFLICT_KEEP_LOCAL_MESSAGE,
            error: CONFLICT_KEEP_LOCAL_MESSAGE,
          });
          return false;
        }
        const message = error instanceof Error ? error.message : String(error);
        set({
          saveStatus: 'failed',
          saveError: message,
          error: message,
        });
        return false;
      }
    };
    activeSave = run().finally(() => { activeSave = null; });
    return activeSave;
  },

  generateFromApi: async () => {
    const { target, baseRev } = get();
    if (!target) return;
    set({ loading: true, error: null });
    try {
      const payload = target.kind === 'map'
        ? await canvasApi.refreshProjectMap(target.value, false, baseRev)
        : await canvasApi.generate(target, false, baseRev);
      if (payload.available === false) {
        set({
          loading: false,
          error: String(payload.message || '当前模式未配置 AI provider；此动作不可用。'),
        });
        return;
      }
      const loadedCanvas = normalizeCanvas(payload, target.value);
      set({
        canvas: loadedCanvas,
        canvasExists: true,
        baseRev: canvasRevFromPayload(payload),
        savedNodesById: cloneNodeMap(loadedCanvas.nodes),
        dirtyNodeIds: [],
        requiresFullSave: false,
        loading: false,
        dirty: false,
        saveStatus: 'saved',
        saveError: null,
      });
    } catch (error) {
      if (error instanceof canvasApi.CanvasConflictError) {
        const payload = await latestPayloadAfterConflict(target, error.payload);
        const loadedCanvas = normalizeCanvas(payload, target.value);
        set({
          canvas: loadedCanvas,
          canvasExists: true,
          baseRev: canvasRevFromPayload(payload),
          savedNodesById: cloneNodeMap(loadedCanvas.nodes),
          dirtyNodeIds: [],
          requiresFullSave: false,
          loading: false,
          dirty: false,
          saveStatus: 'saved',
          saveError: null,
          error: CONFLICT_RELOAD_MESSAGE,
        });
        return;
      }
      set({
        loading: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  },

  refreshProjectMapFromApi: async () => {
    const state = get();
    if (!state.target || state.target.kind !== 'map') return null;
    if (state.dirty && !(await state.saveToApi())) return null;
    const latest = get();
    set({ loading: true, error: null });
    try {
      const payload = await canvasApi.refreshProjectMap(latest.target!.value, false, latest.baseRev);
      const loadedCanvas = normalizeCanvas(payload, latest.target!.value);
      set({
        canvas: loadedCanvas,
        canvasExists: true,
        baseRev: canvasRevFromPayload(payload),
        savedNodesById: cloneNodeMap(loadedCanvas.nodes),
        dirtyNodeIds: [],
        requiresFullSave: false,
        loading: false,
        dirty: false,
        saveStatus: 'saved',
        saveError: null,
      });
      return payload;
    } catch (error) {
      if (error instanceof canvasApi.CanvasConflictError) {
        set({
          loading: false,
          saveStatus: 'conflict',
          saveError: CONFLICT_KEEP_LOCAL_MESSAGE,
          error: CONFLICT_KEEP_LOCAL_MESSAGE,
        });
        return null;
      }
      const message = error instanceof Error ? error.message : String(error);
      set({ loading: false, error: message });
      return null;
    }
  },

  setNodes: (nodesOrUpdater) => {
    set((state) => {
      if (!state.canvas) return state;
      const next =
        typeof nodesOrUpdater === 'function'
          ? nodesOrUpdater(state.canvas.nodes)
          : nodesOrUpdater;
      // 命门守护(Claude,KAN-110):ref 节点是投影,事实字段(source_ref)客户端只读——
      // UI 操作只能改布局(position/尺寸/显隐),不能改指回记录的指针。
      // 服务端保存时还会重算 ref status(双保险),这里挡客户端侧的意外 clobber。
      const prevRefFacts = new Map(
        state.canvas.nodes
          .filter((n) => n.type === 'ref')
          .map((n) => [n.id, (n.data as { source_ref?: unknown })?.source_ref]),
      );
      const nodes = next.map((n) => {
        if (n.type !== 'ref' || !prevRefFacts.has(n.id)) return n;
        const prevRef = prevRefFacts.get(n.id);
        if (!prevRef) return n;
        return { ...n, data: { ...(n.data as object), source_ref: prevRef } };
      });
      const changed = changedExistingNodeIds(state.canvas.nodes, nodes as Node[], state.savedNodesById);
      if (changed.length === 0) {
        return { canvas: { ...state.canvas, nodes: nodes as Canvas['nodes'] } };
      }
      const dirtyNodeIds = Array.from(new Set([...(state.dirtyNodeIds || []), ...changed]));
      return {
        canvas: { ...state.canvas, nodes: nodes as Canvas['nodes'] },
        dirtyNodeIds,
        dirty: true,
        saveStatus: state.saveStatus === 'conflict' ? 'conflict' : 'saving',
        changeVersion: state.changeVersion + 1,
      };
    });
  },

  setNodesSilently: (nodesOrUpdater) => {
    set((state) => {
      if (!state.canvas) return state;
      const next =
        typeof nodesOrUpdater === 'function'
          ? nodesOrUpdater(state.canvas.nodes)
          : nodesOrUpdater;
      return {
        canvas: { ...state.canvas, nodes: next as Canvas['nodes'] },
      };
    });
  },

  setEdges: (edgesOrUpdater) => {
    set((state) => {
      if (!state.canvas) return state;
      const edges =
        typeof edgesOrUpdater === 'function'
          ? edgesOrUpdater(state.canvas.edges)
          : edgesOrUpdater;
      const edgesChanged = state.canvas.edges.length !== edges.length
        || state.canvas.edges.some((edge, index) => stableEdgeKey(edge) !== stableEdgeKey(edges[index]));
      if (!edgesChanged) {
        return { canvas: { ...state.canvas, edges } };
      }
      return {
        canvas: { ...state.canvas, edges },
        requiresFullSave: true,
        dirty: true,
        saveStatus: state.saveStatus === 'conflict' ? 'conflict' : 'saving',
        changeVersion: state.changeVersion + 1,
      };
    });
  },

  updateNodePosition: (id, position) => {
    get().setNodes((nodes) =>
      nodes.map((node) => (node.id === id ? { ...node, position } : node)),
    );
  },

  addNode: (node) => {
    set((state) => {
      if (!state.canvas) return state;
      return {
        canvas: { ...state.canvas, nodes: [...state.canvas.nodes, node] as Canvas['nodes'] },
        requiresFullSave: true,
        dirty: true,
        saveStatus: state.saveStatus === 'conflict' ? 'conflict' : 'saving',
        changeVersion: state.changeVersion + 1,
      };
    });
  },

  deleteNode: (id) => {
    set((state) => {
      if (!state.canvas) return state;
      return {
        canvas: {
          ...state.canvas,
          nodes: state.canvas.nodes.filter((node) => node.id !== id),
          edges: state.canvas.edges.filter(
            (edge) => edge.source !== id && edge.target !== id,
          ),
        },
        requiresFullSave: true,
        dirty: true,
        saveStatus: state.saveStatus === 'conflict' ? 'conflict' : 'saving',
        changeVersion: state.changeVersion + 1,
      };
    });
  },

  setNodeHidden: (id, hidden) => {
    get().setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id !== id) return node;
        const data = node.data && typeof node.data === 'object'
          ? { ...(node.data as Record<string, unknown>), hidden }
          : { hidden };
        return { ...node, hidden, data };
      }),
    );
  },

  setFileLibrary: (entries) => {
    set((state) => {
      if (!state.canvas) return state;
      const metadata = {
        ...((state.canvas.metadata && typeof state.canvas.metadata === 'object') ? state.canvas.metadata : {}),
        file_library: entries,
      };
      return {
        canvas: { ...state.canvas, metadata },
        requiresFullSave: true,
        dirty: true,
        saveStatus: state.saveStatus === 'conflict' ? 'conflict' : 'saving',
        changeVersion: state.changeVersion + 1,
      };
    });
  },

  updateRefSourceRef: (id, sourceRef) => {
    set((state) => {
      if (!state.canvas) return state;
      return {
        canvas: {
          ...state.canvas,
          nodes: state.canvas.nodes.map((node) => {
            if (node.id !== id || node.type !== 'ref') return node;
            return {
              ...node,
              data: {
                ...(node.data as object),
                source_ref: sourceRef,
              },
            };
          }),
        },
        dirtyNodeIds: Array.from(new Set([...(state.dirtyNodeIds || []), id])),
        dirty: true,
        saveStatus: state.saveStatus === 'conflict' ? 'conflict' : 'saving',
        changeVersion: state.changeVersion + 1,
      };
    });
  },

  markDirty: () => set((state) => ({
    dirty: true,
    saveStatus: state.saveStatus === 'conflict' ? 'conflict' : 'saving',
    changeVersion: state.changeVersion + 1,
  })),
}));

useCanvasStore.subscribe((state) => {
  if (!state.dirty || state.saveStatus !== 'saving') {
    clearAutoSaveTimer();
    return;
  }
  clearAutoSaveTimer();
  autoSaveTimer = window.setTimeout(() => {
    autoSaveTimer = null;
    void useCanvasStore.getState().saveToApi();
  }, AUTO_SAVE_DELAY_MS);
});
