"""Conversation Map manifest projection and generated canvas sidecars.

Conversation Map facts come from manifest.yaml. The work canvas uses the same
two-layer policy as project maps: refresh the generated manifest projection and
preserve Owner's manual notes, links, and edges.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from collections import Counter
from datetime import date, datetime
from pathlib import Path


DEFAULT_CONVERSATION_MAPS_DIR = ''
MANIFEST_NAME = 'manifest.yaml'
API_SCHEMA = 'kanban.conversation-map/v0'
CONVERSATION_CANVAS_GENERATOR = 'kanban-conversation-map-canvas-v1'
CONVERSATION_CANVAS_DIR = '_conversation_maps'
CONVERSATION_CANVAS_PROJECT = '个人调度'
ANCHOR_RE = re.compile(r'^L(?P<start>\d+)(?:\.\.L?(?P<end>\d+))?$')
TYPE_ORDER = ['mainline', 'decision', 'next', 'artifact', 'question', 'branch', 'parked']
TYPE_RANK = {kind: idx for idx, kind in enumerate(TYPE_ORDER)}
NODE_WIDTH = 300
X_STEP = 360
Y_STEP = 150
FOLDED_QUESTION_Y_STEP = 90


def _load_yaml_module():
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError('PyYAML 未安装，无法解析 Conversation Map manifest') from exc
    return yaml


def _sanitize_for_json(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            _sanitize_json_key(key): _sanitize_for_json(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_for_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sanitize_json_key(value):
    sanitized = _sanitize_for_json(value)
    if sanitized is None or isinstance(sanitized, (str, int, float, bool)):
        return sanitized
    return str(sanitized)


def _config(deps):
    loader = deps.get('load_config') if isinstance(deps, dict) else None
    if callable(loader):
        cfg = loader()
        return cfg if isinstance(cfg, dict) else {}
    return {}


def _maps_root(deps):
    cfg = _config(deps)
    raw = (
        cfg.get('conversation_maps_dir')
        or (deps or {}).get('default_conversation_maps_dir')
        or DEFAULT_CONVERSATION_MAPS_DIR
    )
    raw = str(raw or '').strip()
    if not raw:
        return None
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = Path((deps or {}).get('repo_root') or Path.cwd()) / candidate
    return candidate.resolve()


def _manifest_rel(path, root):
    return path.resolve().relative_to(root).as_posix()


def _resolve_manifest_path(path_value, deps):
    root = _maps_root(deps)
    if root is None:
        return None, '', 'conversation maps 集成未配置', 404
    raw = str(path_value or MANIFEST_NAME).strip() or MANIFEST_NAME
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None, '', 'manifest 路径越界', 403
    if resolved.name != MANIFEST_NAME:
        return None, '', '只允许读取 manifest.yaml', 400
    if not resolved.exists():
        return None, rel.as_posix(), 'manifest 不存在', 404
    if not resolved.is_file():
        return None, rel.as_posix(), 'manifest 不是文件', 400
    return resolved, rel.as_posix(), '', 200


def _read_manifest(path):
    yaml = _load_yaml_module()
    try:
        with path.open(encoding='utf-8') as f:
            data = _sanitize_for_json(yaml.safe_load(f) or {})
    except OSError as exc:
        return None, f'读取 manifest 失败: {exc}'
    except Exception as exc:
        return None, f'解析 manifest 失败: {exc}'
    if not isinstance(data, dict):
        return None, 'manifest 顶层必须是对象'
    return data, ''


def _string_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or '').strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _line_expr(anchor):
    text = str(anchor or '').strip()
    if '#' in text:
        _path, text = text.rsplit('#', 1)
    match = ANCHOR_RE.match(text)
    if not match:
        return ''
    start = match.group('start')
    end = match.group('end')
    return f'{start},{end}p' if end else f'{start}p'


def _anchor_path(anchor, default_rollout):
    text = str(anchor or '').strip()
    if '#' not in text:
        return str(default_rollout or '').strip()
    raw_path, _line = text.rsplit('#', 1)
    return raw_path.strip() or str(default_rollout or '').strip()


def _source_views(sources, default_rollout):
    views = []
    for anchor in _string_list(sources):
        line_expr = _line_expr(anchor)
        rollout_path = _anchor_path(anchor, default_rollout)
        command = ''
        if line_expr and rollout_path:
            command = f"sed -n '{line_expr}' {shlex.quote(rollout_path)}"
        views.append({
            'anchor': anchor,
            'command': command,
        })
    return views


def _slug(value: object, fallback: str = 'conversation-map') -> str:
    text = str(value or '').strip().lower() or fallback
    text = re.sub(r'[^a-z0-9_.-]+', '-', text).strip('-._')
    return text or fallback


def _short_text(value: object, limit: int = 260) -> str:
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + '...'


def _normalize_node(raw, default_rollout):
    node = dict(raw) if isinstance(raw, dict) else {}
    node['id'] = str(node.get('id') or '').strip()
    node['type'] = str(node.get('type') or 'unknown').strip() or 'unknown'
    node['title'] = str(node.get('title') or node['id'] or '(untitled)').strip()
    node['status'] = str(node.get('status') or '').strip()
    node['summary'] = str(node.get('summary') or '').strip()
    node['source'] = _string_list(node.get('source'))
    node['source_commands'] = _source_views(node['source'], default_rollout)
    node['next_nodes'] = _string_list(node.get('next_nodes'))
    for key in ('parent', 'return_to', 'branch_from', 'card'):
        if key in node and node.get(key) is not None:
            node[key] = str(node.get(key) or '').strip()
    return node


def _node_sort_value(node, index):
    kind = str(node.get('type') or '').strip()
    return TYPE_RANK.get(kind, 99) * 1000 + index.get(str(node.get('id') or ''), 9999)


def _primary_parent(node):
    return str(node.get('parent') or node.get('branch_from') or '').strip()


def _edge(edge_id, source, target, relation):
    return {
        'id': edge_id,
        'source': source,
        'target': target,
        'relation': relation,
    }


def _derive_edges(nodes):
    edges = []
    seen = set()

    def add(source, target, relation):
        source = str(source or '').strip()
        target = str(target or '').strip()
        if not source or not target or source == target:
            return
        key = (source, target, relation)
        if key in seen:
            return
        seen.add(key)
        edges.append(_edge(f'{relation}:{source}->{target}', source, target, relation))

    for node in nodes:
        node_id = node.get('id')
        add(node.get('parent'), node_id, 'parent')
        add(node.get('branch_from'), node_id, 'branch_from')
        add(node_id, node.get('return_to'), 'return_to')
        for target in _string_list(node.get('next_nodes')):
            add(node_id, target, 'next')
    return edges


def _map_id_from_manifest(data, rel):
    thread = data.get('thread') if isinstance(data.get('thread'), dict) else {}
    thread_id = str(thread.get('id') or '').strip()
    if thread_id:
        return _slug(thread_id, 'conversation-map')
    rel_text = str(rel or '').strip()
    if rel_text.endswith('/' + MANIFEST_NAME):
        rel_text = rel_text[:-(len(MANIFEST_NAME) + 1)]
    elif rel_text == MANIFEST_NAME:
        rel_text = ''
    rel_text = rel_text or str(thread.get('title') or data.get('title') or '').strip()
    return _slug(rel_text.replace('/', '-'), 'conversation-map')


def _conversation_canvas_rel(map_id):
    safe_id = _slug(map_id, 'conversation-map')
    return str(
        Path('project')
        / CONVERSATION_CANVAS_PROJECT
        / '.canvas'
        / CONVERSATION_CANVAS_DIR
        / safe_id
        / 'main.canvas.json'
    )


def _resolve_conversation_canvas_path(map_id, deps):
    rel = _conversation_canvas_rel(map_id)
    repo_root = Path(deps['repo_root']).resolve()
    target = (repo_root / rel).resolve()
    try:
        target.relative_to(repo_root)
    except ValueError:
        return None, rel, '非法 conversation map canvas 路径', 400
    return target, rel, '', 200


def _manifest_payload_for_path(path, rel):
    data, err = _read_manifest(path)
    if err:
        return None, err
    thread = data.get('thread') if isinstance(data.get('thread'), dict) else {}
    raw_rollout = str(thread.get('raw_rollout') or '').strip()
    raw_nodes = data.get('nodes') if isinstance(data.get('nodes'), list) else []
    nodes = [_normalize_node(node, raw_rollout) for node in raw_nodes]
    node_by_id = {node['id']: node for node in nodes if node.get('id')}
    plan = data.get('plan') if isinstance(data.get('plan'), dict) else {}
    premise_ids = _string_list(plan.get('premises'))
    step_ids = _string_list(plan.get('steps'))
    current_cursor = data.get('current_cursor') if isinstance(data.get('current_cursor'), dict) else {}
    current_cursor = dict(current_cursor)
    current_cursor['source'] = _string_list(current_cursor.get('source'))
    current_cursor['source_commands'] = _source_views(current_cursor.get('source'), raw_rollout)
    map_id = _map_id_from_manifest(data, rel)
    canvas_ref = _conversation_canvas_rel(map_id)
    return {
        'ok': True,
        'schema': API_SCHEMA,
        'canvas_scope': map_id,
        'canvas_ref': canvas_ref,
        'manifest_path': rel,
        'manifest_abs_path': str(path),
        'manifest_schema': data.get('schema') or '',
        'manifest_version': data.get('manifest_version'),
        'status': data.get('status') or '',
        'generated_at': data.get('generated_at') or '',
        'updated_at': _updated_at(path),
        'thread': thread,
        'current_cursor': current_cursor,
        'plan': {
            'premises': premise_ids,
            'steps': step_ids,
            'premise_nodes': [node_by_id[item] for item in premise_ids if item in node_by_id],
            'step_nodes': [node_by_id[item] for item in step_ids if item in node_by_id],
        },
        'nodes': nodes,
        'edges': _derive_edges(nodes),
        'node_count': len(nodes),
    }, ''


def _resolve_manifest_by_canvas_scope(scope, deps):
    root = _maps_root(deps)
    if root is None:
        return None, 'conversation maps 集成未配置', 404
    raw = str(scope or MANIFEST_NAME).strip() or MANIFEST_NAME
    path, rel, err, status = _resolve_manifest_path(raw, deps)
    if not err:
        payload, payload_err = _manifest_payload_for_path(path, rel)
        if payload_err:
            return None, payload_err, 400
        return payload, '', 200
    manifests = sorted(path for path in root.rglob(MANIFEST_NAME) if path.is_file()) if root.exists() else []
    for manifest in manifests:
        rel = _manifest_rel(manifest, root)
        payload, payload_err = _manifest_payload_for_path(manifest, rel)
        if payload_err:
            continue
        if payload.get('canvas_scope') == _slug(raw, 'conversation-map'):
            return payload, '', 200
    return None, f'conversation map 不存在: {raw}', 404


def _updated_at(path):
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat()
    except OSError:
        return ''


def _manifest_summary(path, root):
    data, err = _read_manifest(path)
    if err:
        rel = _manifest_rel(path, root)
        return {
            'path': rel,
            'title': path.stem,
            'error': err,
            'node_count': 0,
            'updated_at': _updated_at(path),
            'canvas_scope': _slug(rel.replace('/', '-'), 'conversation-map'),
            'canvas_ref': _conversation_canvas_rel(_slug(rel.replace('/', '-'), 'conversation-map')),
        }
    thread = data.get('thread') if isinstance(data.get('thread'), dict) else {}
    nodes = data.get('nodes') if isinstance(data.get('nodes'), list) else []
    canvas_scope = _map_id_from_manifest(data, _manifest_rel(path, root))
    canvas_ref = _conversation_canvas_rel(canvas_scope)
    return {
        'path': _manifest_rel(path, root),
        'title': str(thread.get('title') or data.get('title') or path.parent.name or path.stem),
        'thread_id': str(thread.get('id') or ''),
        'status': str(data.get('status') or ''),
        'node_count': len(nodes),
        'updated_at': _updated_at(path),
        'canvas_scope': canvas_scope,
        'canvas_ref': canvas_ref,
    }


def list_conversation_maps(deps):
    root = _maps_root(deps)
    if root is None:
        return {
            'ok': True,
            'schema': API_SCHEMA,
            'maps_dir': '',
            'maps': [],
        }, 200
    if not root.exists():
        return {
            'ok': True,
            'schema': API_SCHEMA,
            'maps_dir': str(root),
            'maps': [],
        }, 200
    manifests = sorted(path for path in root.rglob(MANIFEST_NAME) if path.is_file())
    maps = [_manifest_summary(path, root) for path in manifests]
    if isinstance(deps, dict) and deps.get('repo_root') and callable(deps.get('read_existing_canvas')):
        for item in maps:
            canvas_path, _rel, err, _status = _resolve_conversation_canvas_path(item.get('canvas_scope'), deps)
            canvas = None
            if canvas_path and not err:
                canvas, _load_err = deps['read_existing_canvas'](canvas_path)
            item['canvas_exists'] = bool(canvas)
            item['canvas_rev'] = deps['canvas_rev'](canvas) if canvas and callable(deps.get('canvas_rev')) else ''
            timestamps = canvas.get('timestamps') if isinstance(canvas, dict) and isinstance(canvas.get('timestamps'), dict) else {}
            if timestamps.get('updatedAt'):
                item['canvas_updated_at'] = str(timestamps.get('updatedAt') or '')
    return {
        'ok': True,
        'schema': API_SCHEMA,
        'maps_dir': str(root),
        'maps': maps,
    }, 200


def get_conversation_map(path_value, deps):
    path, rel, err, status = _resolve_manifest_path(path_value, deps)
    if err:
        return {'ok': False, 'error': err, 'path': rel}, status
    payload, payload_err = _manifest_payload_for_path(path, rel)
    if payload_err:
        return {'ok': False, 'error': payload_err, 'path': rel}, 400
    return payload, 200


def _conversation_node_id(node_id):
    return 'conv-node-' + _slug(node_id, 'node')


def _edge_relation_style(relation):
    if relation == 'return_to':
        return {'stroke': '#6b7280', 'strokeDasharray': '6 5'}
    return {'stroke': '#4b5563'}


def _line_start_from_node(node):
    for anchor in node.get('source') or []:
        text = str(anchor or '').strip()
        if '#' in text:
            _path, text = text.rsplit('#', 1)
        match = ANCHOR_RE.match(text)
        if match:
            try:
                return int(match.group('start') or 1)
            except ValueError:
                return 1
    return 1


def _conversation_canvas_metadata(payload, node=None, *, generated=True):
    metadata = {
        'conversation_map_generated': generated,
        'conversation_map': {
            'generated': generated,
            'canvas_scope': payload.get('canvas_scope') or '',
            'manifest_path': payload.get('manifest_path') or '',
            'thread_id': str((payload.get('thread') or {}).get('id') or ''),
        },
    }
    if node:
        metadata['conversation_map'].update({
            'node_id': str(node.get('id') or ''),
            'node_type': str(node.get('type') or ''),
            'status': str(node.get('status') or ''),
            'source': list(node.get('source') or []),
            'source_commands': list(node.get('source_commands') or []),
            'parent': str(node.get('parent') or ''),
            'branch_from': str(node.get('branch_from') or ''),
            'return_to': str(node.get('return_to') or ''),
            'card': str(node.get('card') or ''),
        })
    return metadata


def _conversation_relation_note(node):
    parts = [f"type={str(node.get('type') or 'unknown')}"]
    if node.get('status'):
        parts.append(f"status={node.get('status')}")
    if node.get('parent'):
        parts.append(f"parent={node.get('parent')}")
    if node.get('branch_from'):
        parts.append(f"branch_from={node.get('branch_from')}")
    if node.get('return_to'):
        parts.append(f"return_to={node.get('return_to')}")
    return ' · '.join(parts)


def _conversation_node(node, x, y, payload):
    manifest_path = str(payload.get('manifest_path') or '')
    manifest_abs = str(payload.get('manifest_abs_path') or '')
    title = str(node.get('title') or node.get('id') or 'Conversation node').strip()
    summary = _short_text(node.get('summary') or ' / '.join(node.get('source') or []), 280)
    node_type = str(node.get('type') or 'unknown').strip() or 'unknown'
    source_ref = {
        'kind': 'conversation',
        'path': manifest_path,
        'resolved_path': manifest_abs,
        'status': 'resolved',
        'label': title,
        'node_id': str(node.get('id') or ''),
        'line': _line_start_from_node(node),
    }
    return {
        'id': _conversation_node_id(node.get('id')),
        'type': 'ref',
        'position': {'x': int(x), 'y': int(y)},
        'data': {
            'kind': 'conversation',
            'label': title,
            'title': title,
            'summary': summary,
            'relation_note': _conversation_relation_note(node),
            'readonly': True,
            'source_ref': source_ref,
            'status_badge': {
                'label': node_type,
                'status': node_type,
                'tone': 'plain',
            },
            'metadata': _conversation_canvas_metadata(payload, node),
        },
    }


def _conversation_edge(edge, payload):
    relation = str(edge.get('relation') or 'link')
    return {
        'id': 'conv-edge-' + _slug(f"{relation}-{edge.get('source')}-{edge.get('target')}", 'edge'),
        'source': _conversation_node_id(edge.get('source')),
        'target': _conversation_node_id(edge.get('target')),
        'label': relation,
        'type': 'smoothstep',
        'style': _edge_relation_style(relation),
        'data': {
            'readonly': True,
            'metadata': _conversation_canvas_metadata(payload),
        },
    }


def _conversation_layout(nodes):
    index = {str(node.get('id') or ''): idx for idx, node in enumerate(nodes)}
    by_id = {str(node.get('id') or ''): node for node in nodes if node.get('id')}
    children = {node_id: [] for node_id in by_id}
    roots = []
    for node in nodes:
        node_id = str(node.get('id') or '')
        parent = _primary_parent(node)
        if parent and parent in by_id and parent != node_id:
            children.setdefault(parent, []).append(node)
        else:
            roots.append(node)
    for child_list in children.values():
        child_list.sort(key=lambda item: _node_sort_value(item, index))
    roots.sort(key=lambda item: _node_sort_value(item, index))

    positions = {}
    visited = set()
    row = 0

    def visit(node, depth):
        nonlocal row
        node_id = str(node.get('id') or '')
        if not node_id or node_id in visited:
            return
        visited.add(node_id)
        positions[node_id] = {
            'x': depth * X_STEP,
            'y': row * Y_STEP,
        }
        row += 1
        for child in children.get(node_id) or []:
            visit(child, depth + 1)

    for root in roots:
        visit(root, 0)
    for node in nodes:
        visit(node, 0)
    return positions


def _is_generated_conversation_node(node):
    data = node.get('data') if isinstance(node, dict) and isinstance(node.get('data'), dict) else {}
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    conv_meta = metadata.get('conversation_map') if isinstance(metadata.get('conversation_map'), dict) else {}
    return bool(metadata.get('conversation_map_generated') or conv_meta.get('generated'))


def _is_generated_conversation_edge(edge):
    data = edge.get('data') if isinstance(edge, dict) and isinstance(edge.get('data'), dict) else {}
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    conv_meta = metadata.get('conversation_map') if isinstance(metadata.get('conversation_map'), dict) else {}
    return bool(metadata.get('conversation_map_generated') or conv_meta.get('generated'))


def _conversation_generated_signature(canvas):
    """Compare generated manifest facts only; ignore layout, viewport, timestamps, and manual layer."""
    if not isinstance(canvas, dict):
        return None

    def _node_payload(node):
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        ref = data.get('source_ref') if isinstance(data.get('source_ref'), dict) else {}
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
        conv_meta = metadata.get('conversation_map') if isinstance(metadata.get('conversation_map'), dict) else {}
        return {
            'id': str(node.get('id') or ''),
            'type': str(node.get('type') or ''),
            'kind': data.get('kind'),
            'label': data.get('label'),
            'title': data.get('title'),
            'summary': data.get('summary'),
            'relation_note': data.get('relation_note'),
            'status_badge': data.get('status_badge'),
            'source_ref': {
                'kind': ref.get('kind'),
                'path': ref.get('path'),
                'node_id': ref.get('node_id'),
                'line': ref.get('line'),
                'label': ref.get('label'),
            },
            'conversation_map': conv_meta,
        }

    generated_nodes = [
        _node_payload(node)
        for node in (canvas.get('nodes') or [])
        if isinstance(node, dict) and _is_generated_conversation_node(node)
    ]
    generated_edges = [
        {
            'id': str(edge.get('id') or ''),
            'source': str(edge.get('source') or ''),
            'target': str(edge.get('target') or ''),
            'label': edge.get('label'),
            'style': edge.get('style') if isinstance(edge.get('style'), dict) else {},
        }
        for edge in (canvas.get('edges') or [])
        if isinstance(edge, dict) and _is_generated_conversation_edge(edge)
    ]
    generated_nodes.sort(key=lambda item: item['id'])
    generated_edges.sort(key=lambda item: item['id'])
    metadata = canvas.get('metadata') if isinstance(canvas.get('metadata'), dict) else {}
    scope = canvas.get('scope') if isinstance(canvas.get('scope'), dict) else {}
    return {
        'scope': {
            'type': scope.get('type'),
            'value': scope.get('value'),
            'manifest_path': scope.get('manifest_path'),
        },
        'nodes': generated_nodes,
        'edges': generated_edges,
        'node_count': metadata.get('node_count'),
        'type_counts': metadata.get('type_counts') or {},
        'status_counts': metadata.get('status_counts') or {},
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


def _merge_conversation_canvas(generated_nodes, generated_edges, existing_canvas):
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
        if not node_id or node_id in generated_ids or _is_generated_conversation_node(node):
            continue
        nodes.append(node)

    seen_edges = set()
    edges = []
    for edge in generated_edges:
        key = str(edge.get('id') or f"{edge.get('source')}->{edge.get('target')}")
        seen_edges.add(key)
        edges.append(edge)
    for edge in (existing_canvas or {}).get('edges') or []:
        if not isinstance(edge, dict) or _is_generated_conversation_edge(edge):
            continue
        source = str(edge.get('source') or '')
        target = str(edge.get('target') or '')
        key = str(edge.get('id') or f'{source}->{target}')
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append(edge)
    return nodes, edges


def build_conversation_map_canvas(scope, deps, existing_canvas=None, *, force=False):
    payload, err, status = _resolve_manifest_by_canvas_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    canvas_path, canvas_rel, err, status = _resolve_conversation_canvas_path(payload.get('canvas_scope'), deps)
    if err:
        return {'ok': False, 'error': err}, status

    manifest_nodes = [node for node in payload.get('nodes') or [] if node.get('id')]
    positions = _conversation_layout(manifest_nodes)
    nodes = [
        _conversation_node(node, positions.get(node['id'], {}).get('x', 0), positions.get(node['id'], {}).get('y', 0), payload)
        for node in manifest_nodes
    ]
    node_ids = {node.get('id') for node in manifest_nodes}
    edges = [
        _conversation_edge(edge, payload)
        for edge in payload.get('edges') or []
        if edge.get('source') in node_ids and edge.get('target') in node_ids
    ]
    nodes, edges = _merge_conversation_canvas(nodes, edges, existing_canvas)

    now = datetime.now().replace(microsecond=0).isoformat()
    type_counts = Counter(str(node.get('type') or 'unknown') for node in manifest_nodes)
    status_counts = Counter(str(node.get('status') or '').strip() or 'unknown' for node in manifest_nodes)
    thread = payload.get('thread') if isinstance(payload.get('thread'), dict) else {}
    title = str(thread.get('title') or payload.get('manifest_path') or payload.get('canvas_scope') or 'Conversation Map')
    canvas = {
        'schema': deps['canvas_schema'],
        'id': 'conversation-map-' + _slug(payload.get('canvas_scope'), 'conversation-map'),
        'name': f'Conversation Map: {title}',
        'scope': {
            'type': 'conversation_map',
            'value': payload.get('canvas_scope') or '',
            'manifest_path': payload.get('manifest_path') or '',
            'canvas_ref': canvas_rel,
        },
        'nodes': nodes,
        'edges': edges,
        'viewport': (existing_canvas or {}).get('viewport') or {'x': 0, 'y': 0, 'zoom': 0.72},
        'metadata': {
            'generator': CONVERSATION_CANVAS_GENERATOR,
            'generated_at': now,
            'source': 'conversation_map_manifest',
            'manifest_path': payload.get('manifest_path') or '',
            'manifest_abs_path': payload.get('manifest_abs_path') or '',
            'thread_id': str(thread.get('id') or ''),
            'node_count': len(manifest_nodes),
            'type_counts': dict(type_counts),
            'status_counts': dict(status_counts),
            'path_status_counts': deps['canvas_status_counts']({'nodes': nodes}),
            'merge_policy': 'refresh conversation-map generated layer; preserve manual notes, links, and edges',
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
        'node_count': len(manifest_nodes),
    }, 200


def _validate_conversation_canvas_payload(canvas, canvas_path, deps):
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
    if not isinstance(nodes, list) or len(nodes) > 500:
        return 'nodes 必须是长度不超过 500 的数组'
    if not isinstance(edges, list) or len(edges) > 1000:
        return 'edges 必须是长度不超过 1000 的数组'
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
        if _is_generated_conversation_node(node) and ref.get('kind') == 'conversation':
            continue
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


def _save_conversation_map(scope, canvas, deps, *, actor='owner', base_rev=None, refresh_event=False, enforce_generated=False):
    payload, err, status = _resolve_manifest_by_canvas_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    canvas_path, canvas_rel, err, status = _resolve_conversation_canvas_path(payload.get('canvas_scope'), deps)
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
                'scope': {
                    'type': 'conversation_map',
                    'value': payload.get('canvas_scope') or '',
                    'manifest_path': payload.get('manifest_path') or '',
                    'canvas_ref': canvas_rel,
                },
                'path_status_counts': deps['canvas_status_counts'](prev_canvas),
            }, 409

        canvas_to_save = canvas
        if enforce_generated:
            generated, gen_status = build_conversation_map_canvas(
                payload.get('canvas_scope'),
                deps,
                canvas if isinstance(canvas, dict) else prev_canvas,
            )
            if not generated.get('ok'):
                return generated, gen_status
            canvas_to_save = generated['canvas']

        validation_err = _validate_conversation_canvas_payload(canvas_to_save, canvas_path, deps)
        if validation_err:
            return {'ok': False, 'error': validation_err}, 400
        if refresh_event and prev_canvas and _conversation_generated_signature(prev_canvas) == _conversation_generated_signature(canvas_to_save):
            return {
                'ok': True,
                'unchanged': True,
                'refreshed': False,
                'canvas_ref': canvas_rel,
                'canvas_updated': '',
                'canvas_rev': current_rev,
                'rev': current_rev,
                'canvas': prev_canvas,
                'scope': {
                    'type': 'conversation_map',
                    'value': payload.get('canvas_scope') or '',
                    'manifest_path': payload.get('manifest_path') or '',
                    'canvas_ref': canvas_rel,
                },
                'path_status_counts': deps['canvas_status_counts'](prev_canvas),
            }, 200

        now = datetime.now().replace(microsecond=0).isoformat()
        metadata = canvas_to_save.get('metadata')
        if not isinstance(metadata, dict):
            metadata = {}
            canvas_to_save['metadata'] = metadata
        metadata['path_status_counts'] = deps['canvas_status_counts'](canvas_to_save)
        metadata.setdefault('generator', CONVERSATION_CANVAS_GENERATOR)
        timestamps = canvas_to_save.get('timestamps')
        if not isinstance(timestamps, dict):
            timestamps = {}
            canvas_to_save['timestamps'] = timestamps
        timestamps.setdefault('createdAt', now)
        timestamps['updatedAt'] = now
        canvas_path.parent.mkdir(parents=True, exist_ok=True)
        deps['atomic_write_text'](canvas_path, json.dumps(canvas_to_save, ensure_ascii=False, indent=2) + '\n')
        new_rev = deps['canvas_rev'](canvas_to_save)
        if refresh_event:
            canvas_events = [deps['canvas_audit_event'](
                actor,
                'conversation_map_refreshed',
                canvas_rev=new_rev,
                previous_rev=current_rev,
                canvas_ref=canvas_rel,
                node_count=metadata.get('node_count'),
                type_counts=metadata.get('type_counts') or {},
                status_counts=metadata.get('status_counts') or {},
            )]
        else:
            canvas_events = deps['canvas_diff_events'](prev_canvas, canvas_to_save, actor)
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
            return deps['canvas_event_append_failure'](canvas_rel, new_rev, canvas_to_save), 500
        today = datetime.now().strftime('%Y-%m-%d')
        return {
            'ok': True,
            'canvas_ref': canvas_rel,
            'canvas_updated': today,
            'canvas_rev': new_rev,
            'rev': new_rev,
            'refreshed': bool(refresh_event),
            'unchanged': False,
            'canvas': canvas_to_save,
            'scope': {
                'type': 'conversation_map',
                'value': payload.get('canvas_scope') or '',
                'manifest_path': payload.get('manifest_path') or '',
                'canvas_ref': canvas_rel,
            },
            'path_status_counts': deps['canvas_status_counts'](canvas_to_save),
        }, 200


def get_conversation_map_canvas(scope, deps):
    return generate_conversation_map_canvas(scope, deps)


def generate_conversation_map_canvas(scope, deps, *, force=False, base_rev=None):
    payload, err, status = _resolve_manifest_by_canvas_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    canvas_path, _canvas_rel, err, status = _resolve_conversation_canvas_path(payload.get('canvas_scope'), deps)
    if err:
        return {'ok': False, 'error': err}, status
    existing_canvas = None
    if canvas_path.exists():
        existing_canvas, load_err = deps['read_existing_canvas'](canvas_path)
        if load_err:
            return {'ok': False, 'error': load_err}, 400
    generated, gen_status = build_conversation_map_canvas(payload.get('canvas_scope'), deps, existing_canvas, force=force)
    if not generated.get('ok'):
        return generated, gen_status
    return _save_conversation_map(
        payload.get('canvas_scope'),
        generated['canvas'],
        deps,
        actor='generate',
        base_rev=base_rev,
        refresh_event=True,
    )


def put_conversation_map_canvas(scope, canvas, deps, *, actor='owner', base_rev=None):
    return _save_conversation_map(
        scope,
        canvas,
        deps,
        actor=actor,
        base_rev=base_rev,
        enforce_generated=True,
    )


def get_conversation_map_events(scope, deps):
    payload, err, status = _resolve_manifest_by_canvas_scope(scope, deps)
    if err:
        return {'ok': False, 'error': err}, status
    canvas_path, canvas_rel, err, status = _resolve_conversation_canvas_path(payload.get('canvas_scope'), deps)
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
