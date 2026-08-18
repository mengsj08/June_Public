"""Read-only task canvas inventory for Canvas Studio home."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def _canvas_updated_at(canvas_path: Path, canvas: dict | None) -> str:
    if isinstance(canvas, dict):
        timestamps = canvas.get('timestamps') if isinstance(canvas.get('timestamps'), dict) else {}
        updated = str(timestamps.get('updatedAt') or '').strip()
        if updated:
            return updated
    try:
        return datetime.fromtimestamp(canvas_path.stat().st_mtime).replace(microsecond=0).isoformat()
    except OSError:
        return ''


def list_task_canvases(deps):
    repo_root = Path(deps['repo_root'])
    canvases = []
    for doc in deps['scan_all']():
        rel_path = str(doc.get('path') or '').strip()
        if not rel_path.endswith('.md'):
            continue
        canvas_rel, err = deps['canvas_rel_for_task'](rel_path, doc)
        if err or not canvas_rel:
            continue
        canvas_path = (repo_root / canvas_rel).resolve()
        if not canvas_path.exists():
            continue
        canvas, load_err = deps['read_existing_canvas'](canvas_path)
        if load_err or not canvas:
            continue
        updated_at = _canvas_updated_at(canvas_path, canvas)
        canvases.append({
            'path': rel_path,
            'task_id': str(doc.get('task_id') or Path(rel_path).stem),
            'title': str(doc.get('title') or doc.get('task_id') or Path(rel_path).stem),
            'status': str(doc.get('status') or ''),
            'updated': str(doc.get('updated') or ''),
            'project': str(doc.get('project') or ''),
            'canvas_ref': canvas_rel,
            'canvas_rev': deps['canvas_rev'](canvas),
            'canvas_updated_at': updated_at,
            'updated_at': updated_at,
        })

    canvases.sort(key=lambda item: (item.get('updated_at') or '', item.get('task_id') or ''), reverse=True)
    return {
        'ok': True,
        'generated_at': datetime.now().replace(microsecond=0).isoformat(),
        'canvases': canvases,
    }, 200
