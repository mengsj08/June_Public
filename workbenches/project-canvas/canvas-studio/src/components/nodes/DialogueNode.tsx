// Canvas Studio 核心节点(Claude 编写,KAN-110 阶段2 · B-lite)。
// DialogueNode = 画布上的 AI 对话框:发送走 kanban AI 队列(/api/ai-run + prompt),
// 消息真相在 kanban 队列/耐久台账(.comments/ledger.jsonl),本节点只是该记录的投影+布局。
// 分叉(fork_from_index,KAN-111)会在画布上长出新对话节点+连线——树直接空间化。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Handle, Position } from 'reactflow';
import type { NodeProps } from 'reactflow';
import { aiComment, aiResults, aiRun } from '../../services/canvasApi';
import { buildUpstreamContext, DEFAULT_CONTEXT_LIMIT } from '../../core/contextGraph';
import { useCanvasStore } from '../../store/canvasStore';

export interface DialogueNodeData {
  run_id?: string;
  tool?: 'claude' | 'codex';
  label?: string;
  forked_from?: string; // 父节点的 "run_id#idx",仅展示用
  width?: number;
  height?: number;
}

interface ThreadMessage {
  role?: string;
  content?: string;
  author?: string;
  timestamp?: string;
}

interface ThreadEntry {
  run_id?: string;
  id?: string;
  status?: string;
  error?: string;
  messages?: ThreadMessage[];
}

const POLL_MS = 5000;
export default function DialogueNode({ id, data, selected }: NodeProps<DialogueNodeData>) {
  const cardPath = useCanvasStore((s) => s.path);
  const canvas = useCanvasStore((s) => s.canvas);
  const [draft, setDraft] = useState('');
  const [tool, setTool] = useState<'claude' | 'codex'>(data.tool || 'codex');
  const [entry, setEntry] = useState<ThreadEntry | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [allowUnresolved, setAllowUnresolved] = useState(false);
  const [forkAt, setForkAt] = useState<number | null>(null);
  const [forkDraft, setForkDraft] = useState('');
  const pollRef = useRef<number | null>(null);

  const runId = data.run_id || '';
  const upstream = useMemo(() => buildUpstreamContext(canvas, id), [canvas, id]);

  const bindRun = useCallback(
    (newRunId: string, chosenTool: string) => {
      // run_id 是节点与真相记录的绑定,必须持久化——立即写回 data 并保存画布
      const store = useCanvasStore.getState();
      store.setNodes((nodes) =>
        nodes.map((n) =>
          n.id === id
            ? {
                ...n,
                data: {
                  ...n.data,
                  run_id: newRunId,
                  tool: chosenTool,
                  source_ref: { kind: 'comment', run_id: newRunId, path: cardPath },
                },
              }
            : n,
        ),
      );
      void store.saveToApi();
    },
    [id, cardPath],
  );

  const refresh = useCallback(async () => {
    if (!runId || !cardPath) return;
    try {
      const payload = await aiResults(cardPath);
      const results: ThreadEntry[] = Array.isArray(payload.results) ? payload.results as ThreadEntry[] : [];
      const found = results.find((r) => (r.run_id || r.id) === runId) || null;
      setEntry(found);
    } catch {
      /* 轮询失败静默,下轮再试 */
    }
  }, [runId, cardPath]);

  // 有会话时轮询;完成后停(状态还会因续聊/分叉重新变 running)
  useEffect(() => {
    if (!runId) return undefined;
    void refresh();
    pollRef.current = window.setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [runId, refresh]);

  const startDialogue = async () => {
    const prompt = draft.trim();
    if (!prompt || !cardPath) return;
    if (upstream.unresolvedCount > 0 && !allowUnresolved) {
      setErr(`有 ${upstream.unresolvedCount} 个上游引用未解析，已默认阻止发送。`);
      return;
    }
    setBusy(true);
    setErr('');
    try {
      const resp = await aiRun(cardPath, tool, prompt, prompt, upstream.entries, allowUnresolved);
      if (!resp.ok) throw new Error(String(resp.error || '启动失败'));
      const newRunId = String(resp.run_id || '').trim();
      if (!newRunId) throw new Error('启动失败: 缺少 run_id');
      bindRun(newRunId, tool);
      setDraft('');
      setAllowUnresolved(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const sendComment = async () => {
    const comment = draft.trim();
    if (!comment || !runId) return;
    setBusy(true);
    setErr('');
    try {
      const resp = await aiComment(runId, comment);
      if (!resp.ok) throw new Error(String(resp.error || '发送失败'));
      setDraft('');
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const forkBranch = async () => {
    const comment = forkDraft.trim();
    if (comment === '' || forkAt === null || !runId) return;
    setBusy(true);
    setErr('');
    try {
      const resp = await aiComment(runId, comment, forkAt);
      if (!resp.ok) throw new Error(String(resp.error || '分叉失败'));
      const newRunId = String(resp.run_id || '').trim();
      if (!newRunId) throw new Error('分叉失败: 缺少 run_id');
      // 树长在画布上:新支线=新对话节点+一条边(从本节点引出)
      const store = useCanvasStore.getState();
      const self = store.canvas?.nodes.find((n) => n.id === id);
      const base = self?.position || { x: 0, y: 0 };
      const newId = `dialogue_${newRunId}`;
      store.addNode({
        id: newId,
        type: 'dialogue',
        position: { x: base.x + 380, y: base.y + 120 },
        data: {
          run_id: newRunId,
          tool,
          forked_from: String(resp.forked_from || ''),
          source_ref: { kind: 'comment', run_id: newRunId, path: cardPath },
        },
      });
      store.setEdges((edges) => [
        ...edges,
        { id: `e_${id}_${newId}`, source: id, target: newId, label: `⑂ #${forkAt}` },
      ]);
      void store.saveToApi();
      setForkAt(null);
      setForkDraft('');
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const messages = entry?.messages || [];
  const status = entry?.status || (runId ? '载入中' : '');
  const running = status === 'running' || status === 'queued';
  const visibleEntryError = entry?.error && ['error', 'timeout', 'killed'].includes(String(status))
    ? entry.error
    : '';

  return (
    <div className={`node-card dialogue-node ${selected ? 'is-selected' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <div className="dialogue-header">
        <span className="dialogue-kind">对话</span>
        <strong>{data.label || (runId ? `${data.tool || tool} · ${runId.slice(0, 6)}` : '新对话')}</strong>
        {upstream.count > 0 && <span className="dialogue-context-mark">上游 {upstream.count}</span>}
        {upstream.truncated && <span className="dialogue-context-warning">上下文截断</span>}
        {data.forked_from && <span className="dialogue-fork-mark">⑂ {data.forked_from}</span>}
        {status && <span className={`dialogue-status${running ? ' is-running' : ''}`}>{running ? '执行中…' : status}</span>}
      </div>
      {upstream.truncated && (
        <div className="dialogue-warning">
          上游上下文 {upstream.originalLength.toLocaleString()} 字符，发送时已截断到 {DEFAULT_CONTEXT_LIMIT.toLocaleString()} 字符。
        </div>
      )}
      {upstream.unresolvedCount > 0 && (
        <div className="dialogue-unresolved-warning" role="alert">
          <strong>{upstream.unresolvedCount} 个上游未解析，AI 将读不到内容。</strong>
          <span>默认已阻止发送；先修复断链，或显式确认仅把“未解析，内容不可用”标记发给 AI。</span>
          <label>
            <input
              type="checkbox"
              checked={allowUnresolved}
              onChange={(event) => setAllowUnresolved(event.target.checked)}
            />
            我确认仍要发送
          </label>
        </div>
      )}

      {runId ? (
        <div className="dialogue-messages nodrag nowheel">
          {messages.length === 0 && <div className="dialogue-empty">{running ? 'AI 正在处理…' : '暂无消息'}</div>}
          {messages.map((m, idx) => (
            <div key={idx} className={`dialogue-msg role-${m.role === 'ai' ? 'ai' : 'user'}`}>
              <div className="dialogue-msg-meta">
                <span>{m.role === 'ai' ? 'AI' : m.author || '我'}</span>
                {m.role === 'ai' && !running && (
                  <button
                    type="button"
                    className="dialogue-fork-btn"
                    title="以这条消息为分叉点,在画布上长出新支线节点"
                    onClick={() => {
                      setForkAt(forkAt === idx ? null : idx);
                      setForkDraft('');
                    }}
                  >
                    ⑂
                  </button>
                )}
              </div>
              <div className="dialogue-msg-body">{m.content || ''}</div>
              {forkAt === idx && (
                <div className="dialogue-input-row">
                  <textarea
                    className="nodrag"
                    rows={2}
                    placeholder={`分叉自 #${idx} · 新支线的第一条指令`}
                    value={forkDraft}
                    onChange={(e) => setForkDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        void forkBranch();
                      }
                    }}
                  />
                  <button type="button" disabled={busy} onClick={() => void forkBranch()}>
                    开支线
                  </button>
                </div>
              )}
            </div>
          ))}
          {visibleEntryError && <div className="dialogue-error">{visibleEntryError}</div>}
        </div>
      ) : (
        <div className="dialogue-tool-row">
          <label>
            工具
            <select className="nodrag" value={tool} onChange={(e) => setTool(e.target.value as 'claude' | 'codex')}>
              <option value="codex">codex</option>
              <option value="claude">claude</option>
            </select>
          </label>
        </div>
      )}

      {(!runId || (!running && messages.length > 0)) && (
        <div className="dialogue-input-row">
          <textarea
            className="nodrag"
            rows={2}
            placeholder={runId ? '继续这条支线(Enter 发送)' : '第一条指令——发送即接入 CLI(Enter 发送)'}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void (runId ? sendComment() : startDialogue());
              }
            }}
          />
          <button
            type="button"
            disabled={busy || (!runId && upstream.unresolvedCount > 0 && !allowUnresolved)}
            onClick={() => void (runId ? sendComment() : startDialogue())}
          >
            {runId ? '发送' : '开始'}
          </button>
        </div>
      )}
      {err && <div className="dialogue-error">{err}</div>}
    </div>
  );
}
