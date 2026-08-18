// Canvas Studio 核心组件(Claude 编写;Owner 2026-07-03 需求:
// 「我不能完全假定它生成的是正确的——AI 可以建议,但拖进来的是我」)。
// 血统语义:自动生成/AI 建议 = ai-draft(初稿);Owner 亲手拖入 = 她确认的构图动作。
// 拖入的节点标 data.origin='manual',与生成节点(origin 缺省=generated)区分,可审计。
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useCanvasStore } from '../store/canvasStore';
import { CARD_DRAG_MIME } from './dragTypes';

export interface PaletteCard {
  task_id: string;
  title: string;
  path: string;
  project: string;
  project_ref?: string;
  status: string;
  updated?: string;
}

function cardsOnCanvas(canvas: ReturnType<typeof useCanvasStore.getState>['canvas']): Set<string> {
  const set = new Set<string>();
  (canvas?.nodes || []).forEach((n) => {
    const ref = (n.data as { source_ref?: { kind?: string; path?: string } })?.source_ref;
    if (ref?.kind === 'card' && ref.path) set.add(ref.path);
  });
  return set;
}

export default function CardPalette({ onClose, embedded = false }: { onClose?: () => void; embedded?: boolean }) {
  const currentPath = useCanvasStore((s) => s.path);
  const canvas = useCanvasStore((s) => s.canvas);
  const [cards, setCards] = useState<PaletteCard[]>([]);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/data')
      .then((r) => r.json())
      .then((d) => {
        const tasks: PaletteCard[] = (d?.tasks || [])
          .filter((t: PaletteCard) => t.task_id && t.path)
          .map((t: PaletteCard) => ({
            task_id: t.task_id,
            title: t.title || t.task_id,
            path: t.path,
            project: t.project || '',
            project_ref: t.project_ref || '',
            status: t.status || '',
            updated: t.updated,
          }));
        setCards(tasks);
      })
      .catch((e) => setError(String(e?.message || e)));
  }, []);

  const onCanvasSet = useMemo(() => cardsOnCanvas(canvas), [canvas]);
  const currentProject = (currentPath.split('/')[1] || '').trim();
  const target = useCanvasStore((s) => s.target);
  const realProjectRef = target?.kind === 'map' && target.value.startsWith('project:')
    ? target.value.slice('project:'.length)
    : '';

  const kw = filter.trim().toLowerCase();
  const matches = useCallback(
    (c: PaletteCard) =>
      !kw || c.task_id.toLowerCase().includes(kw) || c.title.toLowerCase().includes(kw),
    [kw],
  );

  // 建议 = ai-draft:同项目·活跃·非本卡,按 updated 新旧排,top 8。只是排序,不替 Owner 选。
  const suggested = useMemo(
    () =>
      cards
        .filter(
          (c) =>
            (realProjectRef ? c.project_ref === realProjectRef : c.project === currentProject) &&
            c.path !== currentPath &&
            c.status !== 'done' &&
            matches(c),
        )
        .sort((a, b) => String(b.updated || '').localeCompare(String(a.updated || '')))
        .slice(0, 8),
    [cards, currentProject, currentPath, matches, realProjectRef],
  );
  const suggestedPaths = useMemo(() => new Set(suggested.map((c) => c.path)), [suggested]);

  const rest = useMemo(
    () => cards.filter((c) => (
      c.path !== currentPath &&
      !suggestedPaths.has(c.path) &&
      (!realProjectRef || c.project_ref === realProjectRef) &&
      matches(c)
    )),
    [cards, currentPath, suggestedPaths, matches, realProjectRef],
  );

  const renderItem = (c: PaletteCard, tag?: string) => {
    const onCanvas = onCanvasSet.has(c.path);
    return (
      <div
        key={c.path}
        className={`palette-item${onCanvas ? ' is-on-canvas' : ''}`}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData(CARD_DRAG_MIME, JSON.stringify(c));
          e.dataTransfer.effectAllowed = 'copy';
        }}
        title={c.path}
      >
        <span className="palette-id">{c.task_id}</span>
        <span className="palette-title">{c.title}</span>
        {tag && <span className="palette-tag">{tag}</span>}
        {onCanvas && <span className="palette-tag">已入图</span>}
      </div>
    );
  };

  return (
    <section className={`card-palette${embedded ? ' card-palette-embedded' : ''}`}>
      {!embedded && (
        <div className="palette-header">
          <strong>卡片</strong>
          <span className="palette-hint">拖到画布上=你确认的关系</span>
          <button type="button" onClick={onClose}>
            收起
          </button>
        </div>
      )}
      {embedded && <div className="palette-hint">拖到画布上=你确认的关系</div>}
      <input
        className="palette-filter"
        placeholder="筛卡(编号/标题)…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      {error && <div className="palette-error">{error}</div>}
      {suggested.length > 0 && (
        <div className="palette-group">
          <div className="palette-group-title">建议(AI 排的,仅供拖)</div>
          {suggested.map((c) => renderItem(c, '建议'))}
        </div>
      )}
      <div className="palette-group">
        <div className="palette-group-title">{realProjectRef ? '本项目任务' : '全部'}</div>
        {rest.map((c) => renderItem(c))}
      </div>
    </section>
  );
}
