// source: upstream canvas project frontend/src/components/nodes/LinkNode.tsx @ c7116ce
import { useCallback, useState } from 'react';
import { Handle, Position } from 'reactflow';
import type { NodeProps } from 'reactflow';
import { useCanvasStore } from '../../store/canvasStore';
import { useTranslation } from '../../shims/i18n';
import type { LinkNodeData } from '../../types/canvas';

const domainFromUrl = (url: string): string => {
  try {
    const parsed = new URL(url.startsWith('http') ? url : `https://${url}`);
    return parsed.hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
};

export default function LinkNode({ id, data, selected }: NodeProps<LinkNodeData>) {
  const { t } = useTranslation();
  const setNodes = useCanvasStore((state) => state.setNodes);
  const deleteNode = useCanvasStore((state) => state.deleteNode);
  const [isEditing, setIsEditing] = useState(!data.url);
  const [editUrl, setEditUrl] = useState(data.url || '');

  const updateData = useCallback(
    (patch: Partial<LinkNodeData>) => {
      setNodes((nodes) =>
        nodes.map((node) =>
          node.id === id ? { ...node, data: { ...node.data, ...patch } } : node,
        ),
      );
    },
    [id, setNodes],
  );

  const saveUrl = useCallback(() => {
    const url = editUrl.trim();
    if (!url) {
      deleteNode(id);
      return;
    }
    const normalized = url.startsWith('http') ? url : `https://${url}`;
    updateData({
      url: normalized,
      title: data.title || domainFromUrl(normalized),
      status: 'valid',
    });
    setIsEditing(false);
  }, [data.title, deleteNode, editUrl, id, updateData]);

  const openLink = useCallback(() => {
    if (data.url) {
      window.open(data.url, '_blank', 'noopener,noreferrer');
    }
  }, [data.url]);

  return (
    <div className={`node-card link-node ${selected ? 'is-selected' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />

      {isEditing ? (
        <div className="node-edit">
          <label>{t('nodes.link.linkAddress', '链接地址')}</label>
          <input
            value={editUrl}
            onChange={(event) => setEditUrl(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') saveUrl();
              if (event.key === 'Escape') setIsEditing(false);
            }}
            placeholder={t('nodes.link.editPlaceholder', 'https://example.com')}
            autoFocus
          />
          <div className="node-actions">
            <button type="button" onClick={() => setIsEditing(false)}>
              {t('nodes.link.cancel', '取消')}
            </button>
            <button type="button" onClick={saveUrl}>
              {t('nodes.link.confirm', '确认')}
            </button>
          </div>
        </div>
      ) : (
        <div className="link-read">
          <button type="button" className="link-title" onClick={openLink}>
            {data.title || domainFromUrl(data.url || '')}
          </button>
          {data.description && <p>{data.description}</p>}
          <button type="button" className="link-url" onClick={openLink}>
            {data.url}
          </button>
          {selected && (
            <div className="node-actions">
              <button type="button" onClick={() => setIsEditing(true)}>
                {t('nodes.link.editLink', '编辑')}
              </button>
              <button type="button" onClick={() => deleteNode(id)}>
                {t('nodes.link.delete', '删除')}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
