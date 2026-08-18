// Canvas Studio 核心节点(Claude 编写;Owner 2026-07-03 拍板〔owner-confirmed〕:
// Text/Markdown 合并为单一「笔记」节点——纯文本是合法 Markdown 的子集,两个类型=一次多余的选择)。
// 设计:默认轻便签(双击即改、纯 textarea、无工具栏按钮);展示按 Markdown 渲染。
// 兼容三种存量:后端 seed 的 note(label+text)/旧 text(content|label)/旧 markdown(content)。
import { useEffect, useRef, useState } from 'react';
import { Handle, Position } from 'reactflow';
import type { NodeProps } from 'reactflow';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useCanvasStore } from '../../store/canvasStore';

export interface NoteNodeData {
  content?: string;
  label?: string; // 后端 seed / 旧 text
  text?: string; // 后端 seed
  title?: string; // 旧 markdown
  isNew?: boolean;
  canvas_native?: boolean;
  width?: number;
  height?: number;
  dialogue_status?: string;
  dialogue_created_at?: string;
  conversation_id?: string;
  dialogue_outcome?: string;
}

function noteText(data: NoteNodeData): string {
  if (typeof data.content === 'string' && data.content !== '') return data.content;
  const parts: string[] = [];
  const label = String(data.label || data.title || '').trim();
  const body = String(data.text || '').trim();
  if (label) parts.push(`**${label}**`);
  if (body) parts.push(body);
  return parts.join('\n\n');
}

export default function NoteNode({ id, data, selected }: NodeProps<NoteNodeData>) {
  const [editing, setEditing] = useState(Boolean(data.isNew));
  const [draft, setDraft] = useState(() => noteText(data));
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing) areaRef.current?.focus();
  }, [editing]);

  const commit = () => {
    const store = useCanvasStore.getState();
    store.setNodes((nodes) =>
      nodes.map((n) =>
        n.id === id
          ? {
              ...n,
              data: {
                ...n.data,
                content: draft,
                // 编辑后 content 成为唯一正文,清掉 seed 的分列字段避免双源
                label: undefined,
                text: undefined,
                title: undefined,
                isNew: undefined,
              },
            }
          : n,
      ),
    );
    setEditing(false);
  };

  const cancel = () => {
    setDraft(noteText(data));
    setEditing(false);
  };

  return (
    <div
      className={`node-card note-node ${selected ? 'is-selected' : ''}`}
      onDoubleClick={() => {
        setDraft(noteText(data));
        setEditing(true);
      }}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      {editing ? (
        <div className="note-edit nodrag nowheel">
          <textarea
            ref={areaRef}
            rows={6}
            value={draft}
            placeholder="随手记,支持 Markdown 也可纯文字(⌘Enter 或点外面保存 · Esc 取消)"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.preventDefault();
                cancel();
              }
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                commit();
              }
            }}
            onBlur={commit}
          />
        </div>
      ) : (
        <div className="note-body">
          {data.dialogue_status && (
            <div className="note-dialogue-meta">
              <small>对话</small>
              <strong>{data.dialogue_status}</strong>
              <span>{data.dialogue_created_at ? new Date(data.dialogue_created_at).toLocaleString() : ''}</span>
              {data.conversation_id && <span>ID · {data.conversation_id}</span>}
              {data.dialogue_outcome && <span>结局 · {data.dialogue_outcome}</span>}
            </div>
          )}
          {!data.dialogue_status && noteText(data).trim() ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{noteText(data)}</ReactMarkdown>
          ) : !data.dialogue_status ? (
            <span className="note-empty">双击输入…</span>
          ) : null}
        </div>
      )}
    </div>
  );
}
