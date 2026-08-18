// source: upstream canvas project frontend/src/types/canvas.ts @ c7116ce
import type { Edge, Node } from 'reactflow';

export const NodeType = {
  NOTE: 'note',
  TEXT: 'text',
  LINK: 'link',
  MARKDOWN: 'markdown',
  REF: 'ref',
  DIALOGUE: 'dialogue',
} as const;

export type NodeType = (typeof NodeType)[keyof typeof NodeType];

export interface TextNodeData {
  content: string;
  fontSize?: number;
  color?: string;
  backgroundColor?: string;
  width?: number;
  height?: number;
  hidden?: boolean;
  locked?: boolean;
}

export interface LinkNodeData {
  title: string;
  url: string;
  description?: string;
  favicon?: string;
  image?: string;
  status?: 'checking' | 'valid' | 'invalid';
  lastChecked?: string;
  width?: number;
  height?: number;
  hidden?: boolean;
  locked?: boolean;
}

export interface MarkdownNodeData {
  content: string;
  title?: string;
  editMode?: 'edit' | 'preview' | 'live';
  width?: number;
  height?: number;
  hidden?: boolean;
  locked?: boolean;
  isNew?: boolean;
  colorId?: string;
  useTextBackground?: boolean;
  blockBackgroundId?: string;
}

// 与 kanban 后端 _canvas_source_ref(scan-docs.py)的落盘 schema 对齐
export interface SourceRef {
  path?: string;
  label?: string;
  status?: 'resolved' | 'corrected' | 'pending' | 'missing' | 'forbidden' | 'ambiguous' | string;
  kind?: 'card' | 'comment' | 'file' | 'dir' | 'url' | string;
  resolved_path?: string;
  reason?: string;
  candidates?: string[];
  allowed_roots?: string[];
  searched_roots?: string[];
  task_id?: string;
  line?: number | null;
  run_id?: string;
  session_id?: string;
  thread_id?: string;
}

export interface RefNodeData {
  kind?: string;
  label?: string;
  title?: string;
  summary?: string;
  relation_note?: string;
  status_badge?: {
    label?: string;
    status?: string;
    tone?: string;
  };
  metadata?: Record<string, unknown>;
  origin?: string;
  source_ref?: SourceRef;
  width?: number;
  height?: number;
  hidden?: boolean;
  locked?: boolean;
}

export interface DialogueNodeData {
  run_id?: string;
  tool?: 'claude' | 'codex';
  label?: string;
  forked_from?: string;
  source_ref?: SourceRef;
  width?: number;
  height?: number;
  hidden?: boolean;
}

export type CanvasNodeData =
  | TextNodeData
  | LinkNodeData
  | MarkdownNodeData
  | RefNodeData
  | DialogueNodeData;

export interface CustomNode extends Node {
  type: NodeType;
  data: CanvasNodeData;
}

export interface Canvas {
  id: string;
  name: string;
  description?: string;
  nodes: CustomNode[];
  edges: Edge[];
  viewport: {
    x: number;
    y: number;
    zoom: number;
  };
  createdAt?: string;
  updatedAt?: string;
  schema?: string;
  metadata?: Record<string, unknown>;
  meta?: Record<string, unknown>;
}
