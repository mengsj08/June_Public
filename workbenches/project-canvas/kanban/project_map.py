"""Generated project-map canvases for kanban task-family scopes.

This module is intentionally a process-in library: scan-docs.py owns HTTP,
auth, and the low-level canvas helpers; this file owns the project-map
projection and merge policy.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


SCOPE_TYPE = 'task_family'
REAL_PROJECT_SCOPE_TYPE = 'project'
PROJECT_MAP_GENERATOR = 'kanban-project-map-v1'
PROJECT_MAP_DIR = '_project_maps'
PROJECT_MAP_VERSIONS_DIR = 'versions'
DEFAULT_STAGE = '未分期'
STATUS_LABELS = {
    'todo': 'todo',
    'in-progress': 'in progress',
    'review': 'review',
}
STATUS_RANK = {
    'in-progress': 0,
    'review': 1,
    'todo': 2,
}
FALLBACK_TASK_FAMILIES = {
    'kanban',
    'governance',
    'documents',
    'skill',
    'knowledge',
    'chain',
    'scenario',
    'research',
    'ops',
}
COL_WIDTH = 380
ROW_HEIGHT = 190
HEADER_Y = 0
CARD_Y = 120
PROJECT_ROLES = {'execution', 'milestone', 'evidence', 'governance', 'delivery'}
DEFAULT_PROJECT_ROLE = 'execution'
CANVAS_PROJECT_ROLES = {'execution', 'delivery'}
TERMINAL_TASK_STATUSES = {'done', 'completed', 'archived', 'cancelled', 'canceled'}


def _slug(value: object, fallback: str = 'scope') -> str:
    text = str(value or '').strip().lower() or fallback
    text = re.sub(r'[^a-z0-9_.-]+', '-', text).strip('-._')
    return text or fallback


def _short_text(value: object, limit: int = 260) -> str:
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + '...'


def _known_task_families(deps=None):
    prefixes = (deps or {}).get('task_family_prefixes') if isinstance(deps, dict) else None
    if isinstance(prefixes, dict) and prefixes:
        return {str(key) for key in prefixes.keys() if str(key) != 'legacy'}
    return set(FALLBACK_TASK_FAMILIES)


def _normalize_task_family(value: object, deps=None) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    normalizer = (deps or {}).get('normalize_task_family') if isinstance(deps, dict) else None
    normalized = normalizer(raw) if callable(normalizer) else raw.lower()
    normalized = str(normalized or '').strip().lower()
    if normalized not in _known_task_families(deps):
        return ''
    return normalized


def _normalize_project_role(value: object) -> str:
    role = str(value or '').strip().lower()
    return role if role in PROJECT_ROLES else DEFAULT_PROJECT_ROLE


def _normalize_scope(scope: object, deps=None):
    value = str(scope or '').strip()
    if not value:
        return None, 'map scope 不能为空', 400
    if ':' in value:
        prefix, raw = value.split(':', 1)
        prefix = prefix.strip()
        if prefix == REAL_PROJECT_SCOPE_TYPE:
            project_ref = raw.strip().lower()
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,62}', project_ref):
                return None, 'project_ref 格式无效', 400
            loader = (deps or {}).get('list_real_projects') if isinstance(deps, dict) else None
            if callable(loader):
                payload, load_status = loader()
                known = {
                    str(row.get('project_ref') or '').strip()
                    for row in (payload.get('projects') or [])
                    if isinstance(row, dict)
                } if isinstance(payload, dict) else set()
                if load_status != 200 or project_ref not in known:
                    return None, f'unknown project_ref: {project_ref}', 404
            return {
                'type': REAL_PROJECT_SCOPE_TYPE,
                'value': project_ref,
                'key': project_ref,
                'slug': _slug(project_ref, 'project'),
            }, '', 200
        if prefix and prefix != SCOPE_TYPE:
            return None, '只支持 task_family 或 project scope', 400
        value = raw.strip()
    if not value:
        return None, 'task_family 不能为空', 400
    normalized = _normalize_task_family(value, deps)
    if not normalized:
        return None, f'unknown task_family: {value}', 400
    return {
        'type': SCOPE_TYPE,
        'value': normalized,
        'key': normalized,
        'slug': _slug(normalized, 'task-family'),
    }, '', 200


def _active_docs_for_scope(scope_info, deps):
    docs = []
    for doc in deps['scan_all']():
        status = str(doc.get('status') or '').strip().lower()
        if status in TERMINAL_TASK_STATUSES:
            continue
        if scope_info['type'] == REAL_PROJECT_SCOPE_TYPE:
            if str(doc.get('project_ref') or '').strip() != scope_info['key']:
                continue
            if _normalize_project_role(doc.get('project_role')) not in CANVAS_PROJECT_ROLES:
                continue
        else:
            family = _normalize_task_family(doc.get('task_family'), deps)
            if family != scope_info['key']:
                continue
        docs.append(doc)
    docs.sort(key=lambda d: (
        str(d.get('project') or ''),
        str(d.get('stage') or ''),
        STATUS_RANK.get(str(d.get('status') or '').strip().lower(), 9),
        str(d.get('task_id') or ''),
        str(d.get('path') or ''),
    ))
    return docs


def _project_map_rel(project, scope_info):
    safe_project = str(project or '').strip()
    if not safe_project or '/' in safe_project or safe_project.startswith('.'):
        return None, '非法项目名'
    return str(Path('project') / safe_project / '.canvas' / PROJECT_MAP_DIR / scope_info['type'] / scope_info['slug'] / 'main.canvas.json'), ''


def _find_existing_project_map(scope_info, deps):
    repo_root = Path(deps['repo_root'])
    base = repo_root / 'project'
    if not base.exists():
        return None, ''
    pattern = Path('.canvas') / PROJECT_MAP_DIR / scope_info['type'] / scope_info['slug'] / 'main.canvas.json'
    matches = []
    for project_dir in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith('.')):
        candidate = project_dir / pattern
        if candidate.exists():
            matches.append(candidate)
    if not matches:
        return None, ''
    rel = str(matches[0].relative_to(repo_root))
    return matches[0], rel


def _majority_project(docs):
    counts = Counter(str(doc.get('project') or '').strip() for doc in docs if doc.get('project'))
    if not counts:
        return ''
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _resolve_map_path(scope_info, docs, deps):
    existing_path, existing_rel = _find_existing_project_map(scope_info, deps)
    if existing_path:
        parts = Path(existing_rel).parts
        project = parts[1] if len(parts) > 1 else ''
        return existing_path, existing_rel, project, '', 200
    project = '个人调度' if scope_info['type'] == REAL_PROJECT_SCOPE_TYPE else _majority_project(docs)
    if not project:
        return None, '', '', 'scope 内没有活跃任务', 404
    rel, err = _project_map_rel(project, scope_info)
    if err:
        return None, '', '', err, 400
    target = (Path(deps['repo_root']) / rel).resolve()
    try:
        target.relative_to(Path(deps['repo_root']).resolve())
    except ValueError:
        return None, '', '', '非法 project map 路径', 400
    return target, rel, project, '', 200


def _stage_key(doc):
    stage = str(doc.get('stage') or '').strip()
    return stage or DEFAULT_STAGE


def _stage_sort_key(stage):
    return (1 if stage == DEFAULT_STAGE else 0, stage)


def _node_id_for_doc(doc, deps):
    task_id = str(doc.get('task_id') or '').strip()
    base = task_id or str(doc.get('path') or '').strip() or 'card'
    return 'card-' + deps['canvas_slug'](base, 'card')


def _status_badge(status):
    raw = str(status or '').strip()
    key = raw.lower()
    return {
        'label': STATUS_LABELS.get(key, raw or 'unknown'),
        'status': key or 'unknown',
        'tone': {
            'in-progress': 'dark',
            'review': 'mid',
            'todo': 'light',
        }.get(key, 'plain'),
    }


def _project_map_metadata(scope_info, project, doc=None, *, generated=True):
    metadata = {
        'project_map_generated': generated,
        'project_map': {
            'scope_type': scope_info['type'],
            'scope_value': scope_info['value'],
            'project': project,
            'generated': generated,
        },
    }
    if doc:
        metadata['project_map'].update({
            'task_id': str(doc.get('task_id') or ''),
            'task_title': str(doc.get('title') or ''),
            'stage': _stage_key(doc),
            'status': str(doc.get('status') or ''),
            'assignee': str(doc.get('assignee') or ''),
            'next_action': str(doc.get('next_action') or ''),
            'priority': str(doc.get('priority') or ''),
            'due_date': str(doc.get('due_date') or ''),
            'project_role': _normalize_project_role(doc.get('project_role')),
        })
    return metadata


def _stage_header_node(stage, count, col, x, scope_info, project, deps):
    label = stage or DEFAULT_STAGE
    return {
        'id': f'stage-{col}-' + deps['canvas_slug'](label, 'stage'),
        'type': 'note',
        'position': {'x': int(x), 'y': HEADER_Y},
        'data': {
            'label': label,
            'text': f'{count} active cards',
            'canvas_native': True,
            'readonly': True,
            'metadata': _project_map_metadata(scope_info, project),
        },
    }


def _card_node(doc, x, y, scope_info, project, deps):
    rel_path = str(doc.get('path') or '').strip()
    task_abs = (Path(deps['repo_root']) / rel_path).resolve()
    fm = dict(doc)
    source_ref = {
        'kind': 'card',
        'path': rel_path,
        'resolved_path': str(task_abs) if task_abs.exists() else '',
        'status': 'resolved' if task_abs.exists() else 'missing',
        'task_id': str(doc.get('task_id') or ''),
        'line': 1,
    }
    display = deps['canvas_ref_display'](
        'card',
        rel_path,
        task_abs,
        fm,
        source_ref,
        role='card',
        label=str(doc.get('title') or ''),
    )
    stage = _stage_key(doc)
    scope_field = 'project_ref' if scope_info['type'] == REAL_PROJECT_SCOPE_TYPE else 'task_family'
    role = _normalize_project_role(doc.get('project_role'))
    relation = (
        f'{scope_field}={scope_info["value"]} 的当前工作；project_role={role}；'
        f'stage={stage}；项目图按 stage 分列、按 status 排序。'
    )
    metadata = _project_map_metadata(scope_info, project, doc)
    source_ref.setdefault('label', display.get('title') or str(doc.get('title') or rel_path))
    return {
        'id': _node_id_for_doc(doc, deps),
        'type': 'ref',
        'position': {'x': int(x), 'y': int(y)},
        'data': {
            'kind': 'card',
            'label': display.get('title') or str(doc.get('title') or rel_path),
            'title': display.get('title') or str(doc.get('title') or rel_path),
            'summary': display.get('summary') or '',
            'relation_note': relation,
            'readonly': True,
            'source_ref': source_ref,
            'status_badge': _status_badge(doc.get('status')),
            'metadata': metadata,
        },
    }


def _is_generated_project_map_node(node):
    data = node.get('data') if isinstance(node, dict) and isinstance(node.get('data'), dict) else {}
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    project_map = metadata.get('project_map') if isinstance(metadata.get('project_map'), dict) else {}
    return bool(metadata.get('project_map_generated') or project_map.get('generated'))


def _is_generated_project_map_edge(edge):
    data = edge.get('data') if isinstance(edge, dict) and isinstance(edge.get('data'), dict) else {}
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    project_map = metadata.get('project_map') if isinstance(metadata.get('project_map'), dict) else {}
    return bool(metadata.get('project_map_generated') or project_map.get('generated'))


def _generated_layer_signature(canvas):
    """Compare generated facts only; ignore timestamps, viewport, manual layer, and layout."""
    if not isinstance(canvas, dict):
        return None

    def _node_payload(node):
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        ref = data.get('source_ref') if isinstance(data.get('source_ref'), dict) else {}
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
        project_meta = metadata.get('project_map') if isinstance(metadata.get('project_map'), dict) else {}
        return {
            'id': str(node.get('id') or ''),
            'type': str(node.get('type') or ''),
            'kind': data.get('kind'),
            'label': data.get('label'),
            'title': data.get('title'),
            'summary': data.get('summary'),
            'relation_note': data.get('relation_note'),
            'status_badge': data.get('status_badge'),
            'text': data.get('text'),
            'source_ref': {
                'kind': ref.get('kind'),
                'path': ref.get('path'),
                'status': ref.get('status'),
                'task_id': ref.get('task_id'),
                'label': ref.get('label'),
            },
            'project_map': project_meta,
        }

    generated_nodes = [
        _node_payload(node)
        for node in (canvas.get('nodes') or [])
        if isinstance(node, dict) and _is_generated_project_map_node(node)
    ]
    generated_edges = [
        {
            'id': str(edge.get('id') or ''),
            'source': str(edge.get('source') or ''),
            'target': str(edge.get('target') or ''),
            'label': edge.get('label'),
        }
        for edge in (canvas.get('edges') or [])
        if isinstance(edge, dict) and _is_generated_project_map_edge(edge)
    ]
    generated_nodes.sort(key=lambda item: item['id'])
    generated_edges.sort(key=lambda item: item['id'])
    metadata = canvas.get('metadata') if isinstance(canvas.get('metadata'), dict) else {}
    scope = canvas.get('scope') if isinstance(canvas.get('scope'), dict) else {}
    return {
        'scope': {
            'type': scope.get('type'),
            'value': scope.get('value'),
            'project': scope.get('project'),
        },
        'nodes': generated_nodes,
        'edges': generated_edges,
        'active_count': metadata.get('active_count'),
        'stage_counts': metadata.get('stage_counts') or {},
        'status_counts': metadata.get('status_counts') or {},
        'role_counts': metadata.get('role_counts') or {},
    }


def _existing_positions(existing_canvas):
    positions = {}
    for node in (existing_canvas or {}).get('nodes') or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get('id') or '').strip()
        pos = node.get('position')
        if node_id and isinstance(pos, dict):
            positions[node_id] = {
                'x': int(float(pos.get('x') or 0)),
                'y': int(float(pos.get('y') or 0)),
            }
    return positions


def _merge_project_map(generated_nodes, generated_edges, existing_canvas):
    if not existing_canvas:
        return generated_nodes, generated_edges
    positions = _existing_positions(existing_canvas)
    for node in generated_nodes:
        pos = positions.get(str(node.get('id') or ''))
        if pos:
            node['position'] = pos

    generated_ids = {str(node.get('id') or '') for node in generated_nodes}
    nodes = list(generated_nodes)
    for node in (existing_canvas or {}).get('nodes') or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get('id') or '').strip()
        if not node_id or node_id in generated_ids or _is_generated_project_map_node(node):
            continue
        nodes.append(node)

    seen_edges = set()
    edges = []
    for edge in generated_edges:
        key = str(edge.get('id') or f"{edge.get('source')}->{edge.get('target')}")
        seen_edges.add(key)
        edges.append(edge)
    for edge in (existing_canvas or {}).get('edges') or []:
        if not isinstance(edge, dict) or _is_generated_project_map_edge(edge):
            continue
        source = str(edge.get('source') or '')
        target = str(edge.get('target') or '')
        key = str(edge.get('id') or f'{source}->{target}')
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append(edge)
    return nodes, edges


def _generated_task_ids(canvas):
    task_ids = set()
    for node in (canvas or {}).get('nodes') or []:
        if not isinstance(node, dict) or not _is_generated_project_map_node(node):
            continue
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
        project_meta = metadata.get('project_map') if isinstance(metadata.get('project_map'), dict) else {}
        task_id = str(project_meta.get('task_id') or '').strip()
        if task_id:
            task_ids.add(task_id)
    return task_ids


def _refresh_delta(previous_canvas, next_canvas):
    previous_ids = _generated_task_ids(previous_canvas)
    next_ids = _generated_task_ids(next_canvas)
    return {
        'added_cards': len(next_ids - previous_ids),
        'removed_cards': len(previous_ids - next_ids),
        'before_cards': len(previous_ids),
        'after_cards': len(next_ids),
    }


def _file_library_index(canvas):
    metadata = (canvas or {}).get('metadata')
    if not isinstance(metadata, dict):
        return {}
    library = metadata.get('file_library')
    if not isinstance(library, list):
        return {}
    entries = {}
    for raw in library:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get('kind') or '').strip()
        path = str(raw.get('path') or '').strip().rstrip('/')
        if not kind or not path:
            continue
        entries[f'{kind}:{path}'] = raw
    return entries


def _file_library_diff_events(previous_canvas, next_canvas, actor, audit_event):
    previous = _file_library_index(previous_canvas)
    current = _file_library_index(next_canvas)
    events = []
    for key in sorted(current.keys() - previous.keys()):
        entry = current[key]
        events.append(audit_event(
            actor,
            'file_added',
            file_id=str(entry.get('id') or key),
            file_kind=str(entry.get('kind') or ''),
            path=str(entry.get('path') or ''),
            title=str(entry.get('title') or '')[:120],
            source=str(entry.get('source') or '')[:120],
        ))
    for key in sorted(previous.keys() - current.keys()):
        entry = previous[key]
        events.append(audit_event(
            actor,
            'file_removed',
            file_id=str(entry.get('id') or key),
            file_kind=str(entry.get('kind') or ''),
            path=str(entry.get('path') or ''),
            title=str(entry.get('title') or '')[:120],
            source=str(entry.get('source') or '')[:120],
        ))
    return events


def _snapshot_timestamp():
    return datetime.now().astimezone().isoformat(timespec='microseconds').replace(':', '-')


def _snapshot_canvas(canvas_path, canvas, deps):
    if not isinstance(canvas, dict):
        return '', '当前画布不存在，无法建立快照'
    versions_dir = Path(canvas_path).parent / PROJECT_MAP_VERSIONS_DIR
    version_id = _snapshot_timestamp() + '.json'
    version_path = versions_dir / version_id
    try:
        versions_dir.mkdir(parents=True, exist_ok=True)
        deps['atomic_write_text'](version_path, json.dumps(canvas, ensure_ascii=False, indent=2) + '\n')
    except Exception as exc:
        return '', f'画布快照写入失败: {exc}'
    return version_id, ''


def _safe_version_path(canvas_path, version_id):
    value = str(version_id or '').strip()
    if not value or Path(value).name != value or not value.endswith('.json'):
        return None
    if not re.fullmatch(r'[0-9T.+-]+\.json', value):
        return None
    return Path(canvas_path).parent / PROJECT_MAP_VERSIONS_DIR / value


def _version_summary(version_path, canvas, deps):
    try:
        created_at = datetime.fromtimestamp(version_path.stat().st_mtime).astimezone().isoformat(timespec='seconds')
    except OSError:
        created_at = ''
    return {
        'id': version_path.name,
        'created_at': created_at,
        'node_count': len(canvas.get('nodes') or []) if isinstance(canvas, dict) else 0,
        'edge_count': len(canvas.get('edges') or []) if isinstance(canvas, dict) else 0,
        'canvas_rev': deps['canvas_rev'](canvas),
    }


def build_project_map_canvas(scope, deps, existing_canvas=None, *, force=False):
    scope_info, err, status = _normalize_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    docs = _active_docs_for_scope(scope_info, deps)
    canvas_path, canvas_rel, project, err, status = _resolve_map_path(scope_info, docs, deps)
    if err:
        return {'ok': False, 'error': err}, status

    stages = defaultdict(list)
    for doc in docs:
        stages[_stage_key(doc)].append(doc)
    stage_names = sorted(stages.keys(), key=_stage_sort_key)
    nodes = []
    edges = []
    if scope_info['type'] == REAL_PROJECT_SCOPE_TYPE:
        rows = sorted(docs, key=lambda d: (
            STATUS_RANK.get(str(d.get('status') or '').strip().lower(), 9),
            str(d.get('task_id') or ''),
            str(d.get('path') or ''),
        ))
        nodes.append(_stage_header_node('进行中的任务', len(rows), 0, 20, scope_info, project, deps))
        for row, doc in enumerate(rows):
            col = row % 2
            grid_row = row // 2
            nodes.append(_card_node(doc, 20 + col * 410, CARD_Y + grid_row * 250, scope_info, project, deps))
    else:
        for col, stage in enumerate(stage_names):
            x = col * COL_WIDTH
            rows = sorted(stages[stage], key=lambda d: (
                STATUS_RANK.get(str(d.get('status') or '').strip().lower(), 9),
                str(d.get('task_id') or ''),
                str(d.get('path') or ''),
            ))
            nodes.append(_stage_header_node(stage, len(rows), col, x, scope_info, project, deps))
            for row, doc in enumerate(rows):
                nodes.append(_card_node(doc, x, CARD_Y + row * ROW_HEIGHT, scope_info, project, deps))

    if existing_canvas and not force:
        nodes, edges = _merge_project_map(nodes, edges, existing_canvas)

    now = datetime.now().replace(microsecond=0).isoformat()
    status_counts = Counter(str(doc.get('status') or '').strip() or 'unknown' for doc in docs)
    role_counts = Counter(_normalize_project_role(doc.get('project_role')) for doc in docs)
    stage_counts = {stage: len(stages[stage]) for stage in stage_names}
    canvas = {
        'schema': deps['canvas_schema'],
        'id': 'project-map-' + scope_info['slug'],
        'name': f'Project Map: {scope_info["value"]}',
        'scope': {
            'type': scope_info['type'],
            'value': scope_info['value'],
            'project': project,
            'canvas_ref': canvas_rel,
        },
        'nodes': nodes,
        'edges': edges,
        'viewport': (existing_canvas or {}).get('viewport') or {'x': 0, 'y': 0, 'zoom': 0.65},
        'metadata': {
            'generator': PROJECT_MAP_GENERATOR,
            'generated_at': now,
            'source': 'scan_all_active_execution_and_delivery_cards',
            'active_count': len(docs),
            'stage_counts': stage_counts,
            'status_counts': dict(status_counts),
            'role_counts': dict(role_counts),
            'path_status_counts': deps['canvas_status_counts']({'nodes': nodes}),
            'merge_policy': 'refresh project-map generated layer; preserve manual nodes and edges',
        },
        'timestamps': {
            'createdAt': ((existing_canvas or {}).get('timestamps') or {}).get('createdAt') or now,
            'updatedAt': now,
        },
    }
    return {
        'ok': True,
        'canvas': canvas,
        'canvas_ref': canvas_rel,
        'scope': canvas['scope'],
        'active_count': len(docs),
    }, 200


def _validate_project_map_payload(canvas, canvas_path, deps):
    if not isinstance(canvas, dict):
        return 'canvas 必须是对象'
    encoded = json.dumps(canvas, ensure_ascii=False)
    if len(encoded.encode('utf-8')) > deps['canvas_max_bytes']:
        return 'canvas 超过大小限制'
    if canvas.get('schema') != deps['canvas_schema']:
        return f'canvas schema 必须是 {deps["canvas_schema"]}'
    if 'userId' in canvas:
        return 'canvas 不允许包含 userId'
    nodes = canvas.get('nodes')
    edges = canvas.get('edges', [])
    if not isinstance(nodes, list) or len(nodes) > 300:
        return 'nodes 必须是长度不超过 300 的数组'
    if not isinstance(edges, list) or len(edges) > 600:
        return 'edges 必须是长度不超过 600 的数组'
    context_path = Path(canvas_path)
    for node in nodes:
        if not isinstance(node, dict):
            return 'node 必须是对象'
        pos = node.get('position')
        if not isinstance(pos, dict) or 'x' not in pos or 'y' not in pos:
            return 'node.position 必须包含 x/y'
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        ref = data.get('source_ref')
        if node.get('type') != 'ref':
            continue
        if not isinstance(ref, dict):
            return 'ref 节点必须带 source_ref'
        resolved = deps['resolve_canvas_source_ref'](
            ref.get('path'),
            context_path,
            {},
            kind=ref.get('kind') or 'file',
        )
        if resolved.get('status') == 'forbidden':
            return 'source_ref 不在允许根内'
        ref['status'] = resolved.get('status') or 'missing'
        ref['resolved_path'] = resolved.get('resolved_path') or ''
        if resolved.get('reason'):
            ref['reason'] = resolved['reason']
        if resolved.get('candidates'):
            ref['candidates'] = resolved['candidates']
    return ''


def _save_project_map(
    scope,
    canvas,
    deps,
    *,
    actor='owner',
    base_rev=None,
    refresh_event=False,
    snapshot_before=False,
):
    scope_info, err, status = _normalize_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    docs = _active_docs_for_scope(scope_info, deps)
    canvas_path, canvas_rel, project, err, status = _resolve_map_path(scope_info, docs, deps)
    if err:
        return {'ok': False, 'error': err}, status

    expected_rev = str(base_rev or '').strip()
    with deps['canvas_write_lock']:
        prev_canvas, load_err = deps['read_existing_canvas'](canvas_path)
        if load_err:
            return {'ok': False, 'error': load_err, 'canvas_ref': canvas_rel}, 400
        current_rev = deps['canvas_rev'](prev_canvas)
        if expected_rev and expected_rev != current_rev:
            event = deps['canvas_audit_event'](
                actor,
                'canvas_save_rejected',
                reason='base_rev_mismatch',
                conflict=True,
                base_rev=expected_rev,
                current_rev=current_rev,
                canvas_ref=canvas_rel,
            )
            deps['canvas_events_append'](canvas_path, [event])
            return {
                'ok': False,
                'error': 'canvas 基线已过期',
                'message': 'canvas 基线已过期，请重拉最新画布后再保存',
                'conflict': True,
                'base_rev': expected_rev,
                'current_rev': current_rev,
                'canvas_rev': current_rev,
                'rev': current_rev,
                'canvas_ref': canvas_rel,
                'canvas_updated': '',
                'canvas': prev_canvas,
                'path_status_counts': deps['canvas_status_counts'](prev_canvas),
            }, 409
        validation_err = _validate_project_map_payload(canvas, canvas_path, deps)
        if validation_err:
            return {'ok': False, 'error': validation_err}, 400
        snapshot_id = ''
        if snapshot_before and prev_canvas:
            snapshot_id, snapshot_err = _snapshot_canvas(canvas_path, prev_canvas, deps)
            if snapshot_err:
                return {'ok': False, 'error': snapshot_err, 'canvas_ref': canvas_rel}, 500
        refresh_delta = _refresh_delta(prev_canvas, canvas) if refresh_event else None
        if refresh_event and prev_canvas and _generated_layer_signature(prev_canvas) == _generated_layer_signature(canvas):
            return {
                'ok': True,
                'unchanged': True,
                'refreshed': False,
                'canvas_ref': canvas_rel,
                'canvas_updated': '',
                'canvas_rev': current_rev,
                'rev': current_rev,
                'canvas': prev_canvas,
                'snapshot_id': snapshot_id,
                'delta_summary': refresh_delta,
                'scope': {
                    'type': scope_info['type'],
                    'value': scope_info['value'],
                    'project': project,
                    'canvas_ref': canvas_rel,
                },
                'path_status_counts': deps['canvas_status_counts'](prev_canvas),
            }, 200
        now = datetime.now().replace(microsecond=0).isoformat()
        metadata = canvas.get('metadata')
        if not isinstance(metadata, dict):
            metadata = {}
            canvas['metadata'] = metadata
        metadata['path_status_counts'] = deps['canvas_status_counts'](canvas)
        metadata.setdefault('generator', PROJECT_MAP_GENERATOR)
        timestamps = canvas.get('timestamps')
        if not isinstance(timestamps, dict):
            timestamps = {}
            canvas['timestamps'] = timestamps
        timestamps.setdefault('createdAt', now)
        timestamps['updatedAt'] = now
        canvas_path.parent.mkdir(parents=True, exist_ok=True)
        deps['atomic_write_text'](canvas_path, json.dumps(canvas, ensure_ascii=False, indent=2) + '\n')
        new_rev = deps['canvas_rev'](canvas)
        if refresh_event:
            canvas_events = [deps['canvas_audit_event'](
                actor,
                'project_map_refreshed',
                canvas_rev=new_rev,
                previous_rev=current_rev,
                canvas_ref=canvas_rel,
                active_count=metadata.get('active_count'),
                stage_counts=metadata.get('stage_counts') or {},
                status_counts=metadata.get('status_counts') or {},
            )]
        else:
            canvas_events = deps['canvas_diff_events'](prev_canvas, canvas, actor)
        canvas_events.extend(_file_library_diff_events(
            prev_canvas,
            canvas,
            actor,
            deps['canvas_audit_event'],
        ))
        if not expected_rev and not refresh_event:
            canvas_events.insert(0, deps['canvas_audit_event'](
                actor,
                'canvas_saved',
                no_base=True,
                reason='missing_base_rev',
                current_rev=current_rev,
                canvas_rev=new_rev,
                canvas_ref=canvas_rel,
            ))
        if not deps['canvas_events_append'](canvas_path, canvas_events):
            return deps['canvas_event_append_failure'](canvas_rel, new_rev, canvas), 500
        today = datetime.now().strftime('%Y-%m-%d')
        return {
            'ok': True,
            'canvas_ref': canvas_rel,
            'canvas_updated': today,
            'canvas_rev': new_rev,
            'rev': new_rev,
            'refreshed': bool(refresh_event),
            'unchanged': False,
            'canvas': canvas,
            'snapshot_id': snapshot_id,
            'delta_summary': refresh_delta,
            'scope': {
                'type': scope_info['type'],
                'value': scope_info['value'],
                'project': project,
                'canvas_ref': canvas_rel,
            },
            'path_status_counts': deps['canvas_status_counts'](canvas),
        }, 200


def get_project_map(scope, deps):
    scope_info, err, status = _normalize_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    docs = _active_docs_for_scope(scope_info, deps)
    canvas_path, canvas_rel, project, err, status = _resolve_map_path(scope_info, docs, deps)
    if err:
        return {'ok': False, 'error': err}, status
    canvas, load_err = deps['read_existing_canvas'](canvas_path)
    if load_err:
        return {'ok': False, 'error': load_err, 'canvas_ref': canvas_rel}, 400
    scope_payload = {
        'type': scope_info['type'],
        'value': scope_info['value'],
        'project': project,
        'canvas_ref': canvas_rel,
    }
    if not canvas:
        return {
            'ok': True,
            'exists': False,
            'canvas_ref': canvas_rel,
            'canvas_schema': deps['canvas_schema'],
            'canvas_updated': '',
            'canvas_rev': '',
            'rev': '',
            'scope': scope_payload,
            'active_count': len(docs),
        }, 200
    rev = deps['canvas_rev'](canvas)
    return {
        'ok': True,
        'exists': True,
        'canvas_ref': canvas_rel,
        'canvas_updated': '',
        'canvas_rev': rev,
        'rev': rev,
        'canvas': canvas,
        'scope': canvas.get('scope') or scope_payload,
        'active_count': len(docs),
        'path_status_counts': deps['canvas_status_counts'](canvas),
    }, 200


def generate_project_map(scope, deps, *, force=False, base_rev=None):
    scope_info, err, status = _normalize_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    docs = _active_docs_for_scope(scope_info, deps)
    canvas_path, _canvas_rel, _project, err, status = _resolve_map_path(scope_info, docs, deps)
    if err:
        return {'ok': False, 'error': err}, status
    existing_canvas = None
    if canvas_path.exists() and not force:
        existing_canvas, load_err = deps['read_existing_canvas'](canvas_path)
        if load_err:
            return {'ok': False, 'error': load_err}, 400
    canonical_scope = f"{scope_info['type']}:{scope_info['value']}"
    generated, gen_status = build_project_map_canvas(canonical_scope, deps, existing_canvas, force=force)
    if not generated.get('ok'):
        return generated, gen_status
    return _save_project_map(
        canonical_scope,
        generated['canvas'],
        deps,
        actor='generate',
        base_rev=base_rev,
        refresh_event=True,
        snapshot_before=True,
    )


def put_project_map(scope, canvas, deps, *, actor='owner', base_rev=None):
    return _save_project_map(scope, canvas, deps, actor=actor, base_rev=base_rev)


def get_project_map_events(scope, deps):
    scope_info, err, status = _normalize_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    docs = _active_docs_for_scope(scope_info, deps)
    canvas_path, canvas_rel, _project, err, status = _resolve_map_path(scope_info, docs, deps)
    if err:
        return {'ok': False, 'error': err}, status
    report = deps['canvas_events_read_report'](canvas_path)
    events = report['events']
    return {
        'ok': True,
        'schema': deps['canvas_events_schema'],
        'canvas_ref': canvas_rel,
        'count': len(events),
        'malformed_lines': report['malformed_lines'],
        'events': events,
    }, 200


def list_project_map_versions(scope, deps, *, version_id=''):
    scope_info, err, status = _normalize_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    docs = _active_docs_for_scope(scope_info, deps)
    canvas_path, canvas_rel, _project, err, status = _resolve_map_path(scope_info, docs, deps)
    if err:
        return {'ok': False, 'error': err}, status
    versions_dir = Path(canvas_path).parent / PROJECT_MAP_VERSIONS_DIR
    if version_id:
        version_path = _safe_version_path(canvas_path, version_id)
        if version_path is None:
            return {'ok': False, 'error': 'version 格式无效'}, 400
        canvas, load_err = deps['read_existing_canvas'](version_path)
        if load_err or not canvas:
            return {'ok': False, 'error': load_err or '历史版本不存在'}, 404
        return {
            'ok': True,
            'canvas_ref': canvas_rel,
            'version': _version_summary(version_path, canvas, deps),
            'canvas': canvas,
        }, 200
    versions = []
    if versions_dir.exists():
        for version_path in sorted(versions_dir.glob('*.json'), reverse=True):
            canvas, load_err = deps['read_existing_canvas'](version_path)
            if load_err or not canvas:
                continue
            versions.append(_version_summary(version_path, canvas, deps))
    return {
        'ok': True,
        'canvas_ref': canvas_rel,
        'versions': versions,
    }, 200


def restore_project_map_version(scope, version_id, deps, *, actor='owner', base_rev=None):
    scope_info, err, status = _normalize_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    docs = _active_docs_for_scope(scope_info, deps)
    canvas_path, canvas_rel, project, err, status = _resolve_map_path(scope_info, docs, deps)
    if err:
        return {'ok': False, 'error': err}, status
    version_path = _safe_version_path(canvas_path, version_id)
    if version_path is None:
        return {'ok': False, 'error': 'version 格式无效'}, 400
    expected_rev = str(base_rev or '').strip()
    with deps['canvas_write_lock']:
        current_canvas, load_err = deps['read_existing_canvas'](canvas_path)
        if load_err or not current_canvas:
            return {'ok': False, 'error': load_err or '当前画布不存在', 'canvas_ref': canvas_rel}, 404
        current_rev = deps['canvas_rev'](current_canvas)
        if expected_rev and expected_rev != current_rev:
            return {
                'ok': False,
                'error': 'canvas 基线已过期',
                'message': 'canvas 基线已过期，请重拉最新画布后再恢复',
                'conflict': True,
                'base_rev': expected_rev,
                'current_rev': current_rev,
                'canvas_rev': current_rev,
                'rev': current_rev,
                'canvas_ref': canvas_rel,
                'canvas': current_canvas,
            }, 409
        restored_canvas, version_err = deps['read_existing_canvas'](version_path)
        if version_err or not restored_canvas:
            return {'ok': False, 'error': version_err or '历史版本不存在'}, 404
        validation_err = _validate_project_map_payload(restored_canvas, canvas_path, deps)
        if validation_err:
            return {'ok': False, 'error': f'历史版本无效: {validation_err}'}, 400
        snapshot_id, snapshot_err = _snapshot_canvas(canvas_path, current_canvas, deps)
        if snapshot_err:
            return {'ok': False, 'error': snapshot_err, 'canvas_ref': canvas_rel}, 500
        deps['atomic_write_text'](canvas_path, json.dumps(restored_canvas, ensure_ascii=False, indent=2) + '\n')
        new_rev = deps['canvas_rev'](restored_canvas)
        event = deps['canvas_audit_event'](
            actor,
            'project_map_restored',
            canvas_rev=new_rev,
            previous_rev=current_rev,
            version_id=version_path.name,
            snapshot_id=snapshot_id,
            canvas_ref=canvas_rel,
        )
        if not deps['canvas_events_append'](canvas_path, [event]):
            return deps['canvas_event_append_failure'](canvas_rel, new_rev, restored_canvas), 500
    return {
        'ok': True,
        'restored': True,
        'version_id': version_path.name,
        'snapshot_id': snapshot_id,
        'canvas_ref': canvas_rel,
        'canvas_rev': new_rev,
        'rev': new_rev,
        'canvas': restored_canvas,
        'scope': {
            'type': scope_info['type'],
            'value': scope_info['value'],
            'project': project,
            'canvas_ref': canvas_rel,
        },
        'path_status_counts': deps['canvas_status_counts'](restored_canvas),
    }, 200


def list_project_maps(deps):
    by_family = defaultdict(list)
    for doc in deps['scan_all']():
        if str(doc.get('status') or '').strip().lower() == 'done':
            continue
        family = _normalize_task_family(doc.get('task_family'), deps)
        if family:
            by_family[family].append(doc)

    maps = []
    for key in sorted(by_family.keys()):
        docs = sorted(by_family[key], key=lambda d: str(d.get('path') or ''))
        scope_info = {
            'type': SCOPE_TYPE,
            'value': key,
            'key': key,
            'slug': _slug(key, 'task-family'),
        }
        canvas_path, canvas_rel, project, _err, _status = _resolve_map_path(scope_info, docs, deps)
        canvas = None
        updated_at = ''
        rev = ''
        exists = False
        if canvas_path:
            canvas, _load_err = deps['read_existing_canvas'](canvas_path)
            exists = bool(canvas)
            if canvas:
                rev = deps['canvas_rev'](canvas)
                timestamps = canvas.get('timestamps') if isinstance(canvas.get('timestamps'), dict) else {}
                updated_at = str(timestamps.get('updatedAt') or '')
        maps.append({
            'scope_type': SCOPE_TYPE,
            'scope': key,
            'label': key,
            'active_count': len(docs),
            'project': project or _majority_project(docs),
            'exists': exists,
            'canvas_ref': canvas_rel,
            'canvas_rev': rev,
            'updated_at': updated_at,
        })

    return {
        'ok': True,
        'scope_type': SCOPE_TYPE,
        'generated_at': datetime.now().replace(microsecond=0).isoformat(),
        'maps': maps,
    }, 200
