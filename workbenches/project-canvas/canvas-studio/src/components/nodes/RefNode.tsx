// Canvas Studio 核心节点(Claude 编写,KAN-110)。
// RefNode = 只读投影节点:事实一律来自 source_ref 指回的真实记录(卡/评论/文件/目录/URL),
// 本组件绝不提供编辑事实的入口——canvas 只拥有布局与批注,这是整个设计的命门。
import { useState } from 'react';
import { Handle, Position } from 'reactflow';
import type { NodeProps } from 'reactflow';
import { dispatchTaskToAgent, openSource } from '../../services/canvasApi';
import { useCanvasStore } from '../../store/canvasStore';
import type { RefNodeData } from '../../types/canvas';
import { deriveRefDisplayTitle, refHoverTitle } from '../refDisplay';

const KIND_LABELS: Record<string, string> = {
  card: '任务卡',
  comment: '评论',
  file: '文件',
  dir: '目录',
  url: '链接',
  conversation: '对话',
};

// 健康状态保持安静(近黑白);只有断链/越权/歧义才发声——必要告警,不是装饰色。
const STATUS_META: Record<string, { label: string; broken: boolean }> = {
  resolved: { label: '', broken: false },
  corrected: { label: '已纠', broken: false },
  pending: { label: '待校', broken: false },
  missing: { label: '断链', broken: true },
  ambiguous: { label: '歧义', broken: true },
  forbidden: { label: '越权', broken: true },
};

interface SourceCommand {
  anchor?: string;
  command?: string;
}

interface ProjectCardMetadata {
  scope_type?: string;
  task_id?: string;
  task_title?: string;
  assignee?: string;
  next_action?: string;
  priority?: string;
  due_date?: string;
}

function summaryField(summary: string, label: string): string {
  const parts = summary.split('；').map((item) => item.trim()).filter(Boolean);
  const prefix = `${label}:`;
  const match = parts.find((item) => item.startsWith(prefix));
  return match ? match.slice(prefix.length).trim() : '';
}

function projectCardFields(summary: string, metadata: ProjectCardMetadata, fallback: string) {
  const factTitle = summaryField(summary, '当前任务事实源');
  const assigneePart = summary.split('；').find((item) => item.trim().startsWith('负责人 ')) || '';
  return {
    taskId: String(metadata.task_id || '').trim(),
    title: String(metadata.task_title || factTitle || fallback).trim(),
    assignee: String(metadata.assignee || assigneePart.trim().slice(4)).trim(),
    nextAction: String(metadata.next_action || summaryField(summary, '下一步')).trim(),
    priority: String(metadata.priority || '').trim(),
    dueDate: String(metadata.due_date || '').trim(),
  };
}

function sourceCommandsFromMetadata(metadata: Record<string, unknown> | undefined): SourceCommand[] {
  const conversationMap = metadata?.conversation_map;
  if (!conversationMap || typeof conversationMap !== 'object') return [];
  const commands = (conversationMap as { source_commands?: unknown }).source_commands;
  if (!Array.isArray(commands)) return [];
  return commands
    .map((item) => (item && typeof item === 'object' ? item as SourceCommand : null))
    .filter((item): item is SourceCommand => Boolean(item?.command));
}

export default function RefNode({ id, data, selected }: NodeProps<RefNodeData>) {
  const [copiedCommand, setCopiedCommand] = useState('');
  const [dispatchState, setDispatchState] = useState<'idle' | 'sending' | 'queued' | 'error'>('idle');
  const [dispatchMessage, setDispatchMessage] = useState('');
  const updateRefSourceRef = useCanvasStore((state) => state.updateRefSourceRef);
  const ref = data.source_ref;
  const kind = (data.kind || ref?.kind || 'file') as string;
  const label = deriveRefDisplayTitle(data);
  const summary = String(data.summary || '').trim();
  const relationNote = String(data.relation_note || ref?.reason || '').trim();
  const sourcePath = ref?.resolved_path || ref?.path || '';
  const hoverTitle = refHoverTitle(data, label);
  const status = STATUS_META[ref?.status || 'pending'] || STATUS_META.pending;
  const taskStatus = data.status_badge;
  const sourceCommands = sourceCommandsFromMetadata(data.metadata);
  const projectMapMetadata = data.metadata?.project_map;
  const compactProjectCard = Boolean(
    projectMapMetadata &&
    typeof projectMapMetadata === 'object' &&
    (projectMapMetadata as { scope_type?: string }).scope_type === 'project'
  );
  const projectFields = projectCardFields(
    summary,
    (projectMapMetadata && typeof projectMapMetadata === 'object'
      ? projectMapMetadata
      : {}) as ProjectCardMetadata,
    label,
  );
  const preferredAgent: 'codex' | 'claude' = projectFields.assignee.toLowerCase().includes('claude')
    ? 'claude'
    : 'codex';

  const openCard = () => {
    const cardPath = ref?.path;
    if (!cardPath) return;
    const origin = window.location.port === '5173' ? 'http://localhost:8890' : window.location.origin;
    window.open(`${origin}/#${encodeURIComponent(cardPath)}`, '_blank', 'noopener');
  };

  const openTarget = () => {
    if (!ref) return;
    if (kind === 'card') {
      openCard();
      return;
    }
    if (kind === 'url') {
      const url = ref.path || ref.resolved_path;
      if (url) window.open(url, '_blank', 'noopener');
      return;
    }
    // 打开走 kanban /api/open(自带 open_allowed_roots jail + 可执行类型黑名单);
    // 优先 resolved_path(服务端已校验),回退原始 path 交服务端再裁决。
    const target = ref.resolved_path || ref.path;
    if (target) void openSource(target);
  };

  const copyCommand = (command: string) => {
    if (!command || !navigator.clipboard) return;
    void navigator.clipboard.writeText(command).then(() => {
      setCopiedCommand(command);
      window.setTimeout(() => setCopiedCommand((current) => (current === command ? '' : current)), 1200);
    });
  };

  const chooseCandidate = (candidate: string) => {
    if (!ref || !candidate) return;
    updateRefSourceRef(id, {
      ...ref,
      path: candidate,
      resolved_path: candidate,
      status: 'resolved',
      candidates: [candidate],
      reason: 'user_selected_candidate',
    });
  };

  const dispatchTask = async () => {
    const cardPath = ref?.path;
    if (!cardPath || dispatchState === 'sending' || dispatchState === 'queued') return;
    setDispatchState('sending');
    setDispatchMessage('');
    try {
      await dispatchTaskToAgent(cardPath, preferredAgent);
      setDispatchState('queued');
      setDispatchMessage(`已进入 ${preferredAgent === 'claude' ? 'Claude' : 'Codex'} 执行队列`);
    } catch (error) {
      setDispatchState('error');
      setDispatchMessage(error instanceof Error ? error.message : '派工失败');
    }
  };

  return (
    <div
      className={[
        'node-card',
        'ref-node',
        compactProjectCard ? 'ref-node-compact' : '',
        selected ? 'is-selected' : '',
        status.broken ? 'ref-broken' : '',
      ].filter(Boolean).join(' ')}
      onDoubleClick={openTarget}
      title={hoverTitle}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <div className="ref-node-header">
        {compactProjectCard ? (
          <span className="ref-node-task-id">{projectFields.taskId || '任务卡'}</span>
        ) : (
          <>
            <span className="ref-node-kind">{KIND_LABELS[kind] || kind}</span>
            <strong className="ref-node-label">{label}</strong>
          </>
        )}
        {taskStatus?.label && (
          <span className={`ref-node-task-status tone-${taskStatus.tone || 'plain'}`}>
            {taskStatus.label}
          </span>
        )}
        {status.label && (
          <span className={`ref-node-status${status.broken ? ' is-broken' : ''}`}>
            {status.label}
          </span>
        )}
      </div>
      {compactProjectCard && <strong className="ref-node-project-title">{projectFields.title}</strong>}
      {compactProjectCard && projectFields.nextAction && (
        <div className="ref-node-project-next">
          <span>下一步</span>
          <p>{projectFields.nextAction}</p>
        </div>
      )}
      {compactProjectCard && (
        <div className="ref-node-project-meta">
          <span>{projectFields.assignee || '未分配'}</span>
          {projectFields.priority && <span>优先级 {projectFields.priority}</span>}
          {projectFields.dueDate && <span>截至 {projectFields.dueDate}</span>}
        </div>
      )}
      {!compactProjectCard && summary && <div className="ref-node-summary">{summary}</div>}
      {!compactProjectCard && relationNote && <div className="ref-node-relation">{relationNote}</div>}
      {!compactProjectCard && sourcePath && <div className="ref-node-path">{sourcePath}</div>}
      {status.broken && (
        <div className="ref-node-repair-hint">
          <strong>AI 读不到这个来源。</strong>
          <span>
            已搜索：{(ref?.searched_roots?.length ? ref.searched_roots : ref?.allowed_roots || []).join('、') || '卡片 workdir / 配置的允许根'}
          </span>
          <span>把文件放进允许根或卡 workdir 后重新加载，或换用能“打开来源”的已解析引用。</span>
        </div>
      )}
      {ref?.status === 'ambiguous' && Array.isArray(ref.candidates) && ref.candidates.length > 0 && (
        <div className="ref-node-candidates" aria-label="ambiguous source candidates">
          {ref.candidates.map((candidate) => (
            <button type="button" key={candidate} onClick={() => chooseCandidate(candidate)} title={candidate}>
              {candidate.split('/').filter(Boolean).pop() || candidate}
            </button>
          ))}
        </div>
      )}
      {sourceCommands.length > 0 && (
        <div className="ref-node-sources" aria-label="source commands">
          {sourceCommands.map((item) => {
            const command = String(item.command || '');
            return (
              <div className="ref-node-source-command" key={`${item.anchor || ''}:${command}`}>
                <code>{command}</code>
                <button type="button" onClick={() => copyCommand(command)}>
                  {copiedCommand === command ? '已复制' : '复制'}
                </button>
              </div>
            );
          })}
        </div>
      )}
      {ref && (
        <div className="ref-node-actions">
          <button type="button" onClick={openTarget}>
            {kind === 'card' ? '打开卡片' : '打开来源'}
          </button>
          {compactProjectCard && kind === 'card' && (
            <button
              type="button"
              className="ref-node-dispatch"
              disabled={dispatchState === 'sending' || dispatchState === 'queued'}
              onClick={(event) => {
                event.stopPropagation();
                void dispatchTask();
              }}
              title="读取完整任务卡并进入既有 AI 执行队列；不会改变卡片负责人"
            >
              {dispatchState === 'sending'
                ? '派工中…'
                : dispatchState === 'queued'
                  ? '已入队'
                  : `派给 ${preferredAgent === 'claude' ? 'Claude' : 'Codex'}`}
            </button>
          )}
        </div>
      )}
      {compactProjectCard && dispatchMessage && (
        <div className={`ref-node-dispatch-message is-${dispatchState}`} role="status">
          {dispatchMessage}
        </div>
      )}
    </div>
  );
}
