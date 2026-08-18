import type { AttentionQueueItem } from '../services/canvasApi';
import type { Canvas } from '../types/canvas';

export const DIALOGUE_CLOSEOUT_INSTRUCTION = '本对话收尾时请回报：对话 ID、一句结局（出卡/收枝/仍开放），由当班 AI 登记回画布对话节点与新到区';

export interface DialoguePointerInput {
  projectRef: string;
  projectTitle: string;
  canvas: Canvas;
  activeCards: AttentionQueueItem[];
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function cursorText(canvas: Canvas): string {
  const metadata = canvas.metadata || {};
  const meta = canvas.meta || {};
  return text(metadata.main_cursor_text)
    || text(metadata.current_cursor_text)
    || text(metadata.cursor_text)
    || text(meta.main_cursor_text)
    || text(meta.current_cursor_text)
    || text(meta.cursor_text)
    || '未标注';
}

function selectedNodeLine(canvas: Canvas): string {
  const node = canvas.nodes.find((item) => item.selected);
  if (!node) return '无';
  const data = node.data as Record<string, unknown>;
  const sourceRef = data.source_ref && typeof data.source_ref === 'object'
    ? data.source_ref as Record<string, unknown>
    : {};
  const title = text(data.title) || text(data.label) || text(data.content).split('\n')[0] || node.id;
  const anchor = text(sourceRef.path)
    || text(sourceRef.task_id)
    || text(sourceRef.run_id)
    || text(sourceRef.session_id)
    || '无 source_ref';
  return `${title}｜${anchor}`;
}

export function buildDialoguePointerPackage(input: DialoguePointerInput): string {
  const project = `${input.projectRef}${input.projectTitle && input.projectTitle !== input.projectRef ? `｜${input.projectTitle}` : ''}`;
  const cards = input.activeCards.length
    ? input.activeCards.map((card) => `- ${card.task_id}｜${card.title}｜${card.path}`).join('\n')
    : '- 无';
  return [
    '# 画布对话指针包',
    `项目：${project}`,
    `画布：${input.canvas.name || input.canvas.id}`,
    `主线游标：${cursorText(input.canvas)}`,
    `选中节点：${selectedNodeLine(input.canvas)}`,
    '活跃卡：',
    cards,
    '',
    DIALOGUE_CLOSEOUT_INSTRUCTION,
  ].join('\n');
}

export async function copyTextWithFallback(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // 非安全上下文或权限拒绝时走兼容回退。
    }
  }
  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('clipboard copy failed');
}
