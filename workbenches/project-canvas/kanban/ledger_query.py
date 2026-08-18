"""Canvas/card ledger query helpers and node-granular canvas writes.

This module is intentionally dependency-injected by scan-docs.py. It reads the
existing JSONL sidecars and writes only through the kanban canvas write contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


NODE_HISTORY_EVENTS = {
    'node_added',
    'node_content_changed',
    'node_summary_changed',
    'node_summary_status_changed',
    'node_moved',
    'node_hidden',
    'node_shown',
    'node_removed',
    'node_bound',
    'node_source_ref_changed',
}


def _safe_task_key(value: str) -> str:
    key = re.sub(r'[^A-Za-z0-9_.-]+', '-', str(value or '')).strip('-._')
    return key or 'item'


def _task_id_from_rel_path(task_rel_path: str) -> str:
    stem = Path(str(task_rel_path or '')).stem
    match = re.match(r'^([A-Za-z]+-\d+)', stem)
    return match.group(1) if match else stem


def _task_id_for_task(task_rel_path: str, task_file: dict[str, Any] | None) -> str:
    fm = (task_file or {}).get('frontmatter') if isinstance(task_file, dict) else {}
    if isinstance(fm, dict) and str(fm.get('task_id') or '').strip():
        return str(fm.get('task_id')).strip()
    return _task_id_from_rel_path(task_rel_path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except OSError:
        return rows
    return rows


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            'w',
            encoding='utf-8',
            dir=str(path.parent),
            prefix=f'.{path.name}.',
            suffix='.tmp',
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _iso_key(value: Any) -> str:
    return str(value or '').strip()


def _parse_iso(value: str) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None


def _after_since(ts: str, since: str) -> bool:
    if not since:
        return True
    left = _parse_iso(ts)
    right = _parse_iso(since)
    if not left or not right:
        return str(ts or '') >= str(since or '')
    if left.tzinfo and not right.tzinfo:
        right = right.replace(tzinfo=left.tzinfo)
    if right.tzinfo and not left.tzinfo:
        left = left.replace(tzinfo=right.tzinfo)
    return left >= right


def _event_label(event: str) -> str:
    labels = {
        'node_added': '节点新增',
        'node_removed': '节点移除',
        'node_content_changed': '节点内容变更',
        'node_moved': '节点移动',
        'node_hidden': '节点隐藏',
        'node_shown': '节点放回',
        'layout_moved': '布局移动',
        'edge_added': '连线新增',
        'edge_removed': '连线移除',
        'node_bound': '节点绑定',
        'node_source_ref_changed': '引用变更',
        'canvas_saved': '画布保存',
        'canvas_save_rejected': '画布保存冲突',
        'pilot_backfill': '试点回填',
        'frontmatter_changed': '字段变更',
        'canvas_source_bound': '画布来源绑定',
        'ai_run_queued': 'AI 派单',
        'ai_run_completed': 'AI 完成',
        'ai_run_finished': 'AI 结束',
        'ai_comment_added': 'AI 评论',
        'prompt_audit': 'Prompt 审计',
    }
    return labels.get(event) or event or '记录'


def _short(value: Any, limit: int = 120) -> str:
    text = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
    return text[:limit]


def _summary(kind: str, event: dict[str, Any]) -> str:
    event_name = str(event.get('event') or event.get('type') or '')
    label = _event_label(event_name)
    parts = [label]
    if event.get('node_id'):
        parts.append(str(event.get('node_id')))
    if event.get('field'):
        parts.append(f"{event.get('field')}: {_short(event.get('old_value'), 40)} -> {_short(event.get('new_value'), 40)}")
    if event.get('source') and event.get('target'):
        parts.append(f"{event.get('source')} -> {event.get('target')}")
    if event.get('summary'):
        parts.append(_short(event.get('summary'), 160))
    if event.get('label') and not event.get('summary'):
        parts.append(_short(event.get('label'), 100))
    if kind == 'comments' and event.get('entry_id'):
        parts.append(str(event.get('entry_id')))
    return ' · '.join([part for part in parts if part])


def _scan_task_by_id(deps: dict[str, Any], value: str) -> tuple[str, dict[str, Any] | None, str, int]:
    needle = str(value or '').strip()
    if not needle:
        return '', None, '缺少 task_id', 400
    candidate = Path(needle)
    if candidate.suffix.lower() == '.md':
        if candidate.is_absolute() or '..' in candidate.parts:
            return '', None, '非法任务卡路径', 400
        repo_root = Path(deps['repo_root']).resolve()
        candidate_path = (repo_root / candidate).resolve(strict=False)
        try:
            rel_path = str(candidate_path.relative_to(repo_root))
        except ValueError:
            return '', None, '非法任务卡路径', 400
        task_file, err = deps['read_task_file'](rel_path)
        if not task_file:
            return '', None, err or '任务卡不存在', 404
        return rel_path, task_file, '', 200
    for doc in deps['scan_all']():
        task_id = str(doc.get('task_id') or _task_id_from_rel_path(str(doc.get('path') or ''))).strip()
        path = str(doc.get('path') or '').strip()
        if task_id == needle or Path(path).stem == needle:
            task_file, err = deps['read_task_file'](path)
            if not task_file:
                return '', None, err or '任务卡不存在', 404
            return path, task_file, '', 200
    return '', None, f'找不到任务卡: {needle}', 404


def _ledger_paths(deps: dict[str, Any], task_rel_path: str, task_file: dict[str, Any]) -> tuple[dict[str, str], dict[str, Path], str, int]:
    repo_root = Path(deps['repo_root'])
    fm = task_file.get('frontmatter') or {}
    canvas_path, canvas_rel, ref_err, status = deps['resolve_canvas_ref'](task_rel_path, fm)
    if ref_err:
        return {}, {}, ref_err, status
    task_path = Path(task_rel_path)
    task_id = _safe_task_key(_task_id_from_rel_path(task_rel_path))
    rels = {
        'canvas': str(Path(canvas_rel).parent / 'events.jsonl'),
        'lineage': str(task_path.parent / '.lineage' / task_id / 'ledger.jsonl'),
        'comments': str(task_path.parent / '.comments' / task_id / 'ledger.jsonl'),
    }
    paths = {
        'canvas': Path(canvas_path).parent / 'events.jsonl',
        'lineage': repo_root / rels['lineage'],
        'comments': repo_root / rels['comments'],
    }
    return rels, paths, '', 200


def _timeline_entry(source: str, rel_path: str, event: dict[str, Any], ordinal: int) -> dict[str, Any]:
    kind = source
    if source == 'canvas':
        kind = 'canvas'
    elif source == 'lineage':
        kind = 'lineage'
    elif source == 'comments':
        kind = 'comment'
    ts = _iso_key(event.get('ts') or event.get('timestamp') or event.get('created_at'))
    return {
        'kind': kind,
        'event': str(event.get('event') or event.get('type') or ''),
        'ts': ts,
        'actor': str(event.get('actor') or event.get('author') or ''),
        'summary': _summary(source, event),
        'source': {
            'ledger': source,
            'path': rel_path,
            'ordinal': ordinal,
            'event_id': event.get('event_id') or event.get('entry_id') or '',
        },
        'raw': event,
    }


def query_task_ledger(deps: dict[str, Any], task_id: str, *, since: str = '', kind: str = '') -> tuple[dict[str, Any], int]:
    task_rel_path, task_file, err, status = _scan_task_by_id(deps, task_id)
    if err:
        return {'ok': False, 'error': err}, status
    rels, paths, err, status = _ledger_paths(deps, task_rel_path, task_file or {})
    if err:
        return {'ok': False, 'error': err}, status
    allowed_kind = str(kind or '').strip().lower()
    entries: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for source in ('canvas', 'lineage', 'comments'):
        if allowed_kind and allowed_kind not in {source, 'comment' if source == 'comments' else source}:
            continue
        rows = _read_jsonl(paths[source])
        counts[source] = len(rows)
        for idx, row in enumerate(rows):
            entry = _timeline_entry(source, rels[source], row, idx)
            if _after_since(entry['ts'], since):
                entries.append(entry)
    entries.sort(key=lambda item: (item.get('ts') or '', item['source']['ledger'], item['source']['ordinal']))
    return {
        'ok': True,
        'task_id': _task_id_for_task(task_rel_path, task_file),
        'path': task_rel_path,
        'since': since,
        'kind': allowed_kind,
        'ledger_refs': rels,
        'source_counts': counts,
        'count': len(entries),
        'entries': entries,
    }, 200


def get_node_history(deps: dict[str, Any], task_id: str, node_id: str, *, since: str = '') -> tuple[dict[str, Any], int]:
    node_key = str(node_id or '').strip()
    if not node_key:
        return {'ok': False, 'error': '缺少 node_id'}, 400
    task_rel_path, task_file, err, status = _scan_task_by_id(deps, task_id)
    if err:
        return {'ok': False, 'error': err}, status
    rels, paths, err, status = _ledger_paths(deps, task_rel_path, task_file or {})
    if err:
        return {'ok': False, 'error': err}, status
    entries: list[dict[str, Any]] = []
    for idx, row in enumerate(_read_jsonl(paths['canvas'])):
        event_name = str(row.get('event') or '')
        if event_name not in NODE_HISTORY_EVENTS:
            continue
        if str(row.get('node_id') or '') != node_key:
            continue
        entry = _timeline_entry('canvas', rels['canvas'], row, idx)
        if _after_since(entry['ts'], since):
            entries.append(entry)
    entries.sort(key=lambda item: (item.get('ts') or '', item['source']['ordinal']))
    return {
        'ok': True,
        'task_id': _task_id_for_task(task_rel_path, task_file),
        'path': task_rel_path,
        'node_id': node_key,
        'ledger_ref': rels['canvas'],
        'count': len(entries),
        'entries': entries,
    }, 200


def _node_by_id(canvas: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    for node in canvas.get('nodes') or []:
        if isinstance(node, dict) and str(node.get('id') or '') == node_id:
            return node
    return None


def _node_changed_event(actor: str, old_node: dict[str, Any] | None, new_node: dict[str, Any]) -> list[dict[str, Any]]:
    if not old_node:
        return []
    events: list[dict[str, Any]] = []
    base = {
        'v': 1,
        'schema': 'kanban.canvas-events/v1',
        'ts': datetime.now().replace(microsecond=0).isoformat(),
        'actor': str(actor or 'unspecified'),
        'node_id': str(new_node.get('id') or ''),
        'node_type': str(new_node.get('type') or ''),
    }
    if old_node.get('position') != new_node.get('position'):
        events.append(dict(base, event='node_moved', position=new_node.get('position') or {}))
    old_data = old_node.get('data') if isinstance(old_node.get('data'), dict) else {}
    new_data = new_node.get('data') if isinstance(new_node.get('data'), dict) else {}
    old_hidden = bool(old_node.get('hidden') or old_data.get('hidden'))
    new_hidden = bool(new_node.get('hidden') or new_data.get('hidden'))
    if old_hidden != new_hidden:
        events.append(dict(base, event='node_hidden' if new_hidden else 'node_shown', hidden=new_hidden))
    return events


def put_canvas_node(deps: dict[str, Any], body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    path = str(body.get('path') or body.get('task_id') or '').strip()
    node_id = str(body.get('node_id') or '').strip()
    actor = str(body.get('actor') or 'unspecified')[:40]
    node = body.get('node')
    if not path:
        return {'ok': False, 'error': '缺少 path'}, 400
    if not node_id:
        return {'ok': False, 'error': '缺少 node_id'}, 400
    if not isinstance(node, dict):
        return {'ok': False, 'error': 'node 必须是对象'}, 400
    if str(node.get('id') or '') != node_id:
        return {'ok': False, 'error': 'node.id 必须等于 node_id'}, 400
    task_rel_path, task_file, err, status = _scan_task_by_id(deps, path)
    if err:
        return {'ok': False, 'error': err}, status

    expected_rev = str(body.get('base_rev') or body.get('base_canvas_rev') or '').strip()
    base_node = body.get('base_node') if isinstance(body.get('base_node'), dict) else None
    with deps['canvas_write_lock']:
        fm = (task_file or {}).get('frontmatter') or {}
        canvas_path, canvas_rel, ref_err, status = deps['resolve_canvas_ref'](task_rel_path, fm)
        if ref_err:
            return {'ok': False, 'error': ref_err}, status
        prev_canvas, load_err = deps['read_existing_canvas'](canvas_path)
        if load_err:
            return {'ok': False, 'error': load_err}, 400
        if not isinstance(prev_canvas, dict):
            return {'ok': False, 'error': 'canvas 不存在，节点级保存需要已有画布'}, 404
        current_rev = deps['canvas_rev'](prev_canvas)
        current_node = _node_by_id(prev_canvas, node_id)
        if not current_node:
            return {'ok': False, 'error': f'找不到节点: {node_id}'}, 404
        if expected_rev and expected_rev != current_rev and base_node is not None:
            if _stable_json_hash(current_node) != _stable_json_hash(base_node):
                event = deps['canvas_audit_event'](
                    actor,
                    'canvas_node_save_rejected',
                    reason='node_base_mismatch',
                    conflict=True,
                    node_id=node_id,
                    base_rev=expected_rev,
                    current_rev=current_rev,
                    canvas_ref=canvas_rel,
                )
                deps['canvas_events_append'](canvas_path, [event])
                return {
                    'ok': False,
                    'error': '节点基线已过期',
                    'message': '该节点已被其它会话修改，请重拉后合并',
                    'conflict': True,
                    'node_conflict': True,
                    'node_id': node_id,
                    'base_rev': expected_rev,
                    'current_rev': current_rev,
                    'canvas_rev': current_rev,
                    'rev': current_rev,
                    'canvas_ref': canvas_rel,
                    'canvas': prev_canvas,
                }, 409
        next_canvas = json.loads(json.dumps(prev_canvas, ensure_ascii=False))
        next_nodes = []
        replaced = False
        for item in next_canvas.get('nodes') or []:
            if isinstance(item, dict) and str(item.get('id') or '') == node_id:
                next_nodes.append(node)
                replaced = True
            else:
                next_nodes.append(item)
        if not replaced:
            return {'ok': False, 'error': f'找不到节点: {node_id}'}, 404
        next_canvas['nodes'] = next_nodes
        validation_err = deps['validate_canvas_payload'](next_canvas, task_rel_path)
        if validation_err:
            return {'ok': False, 'error': validation_err}, 400
        now = datetime.now().replace(microsecond=0).isoformat()
        metadata = next_canvas.get('metadata') if isinstance(next_canvas.get('metadata'), dict) else {}
        next_canvas['metadata'] = metadata
        metadata['path_status_counts'] = deps['canvas_status_counts'](next_canvas)
        timestamps = next_canvas.get('timestamps') if isinstance(next_canvas.get('timestamps'), dict) else {}
        next_canvas['timestamps'] = timestamps
        timestamps.setdefault('createdAt', now)
        timestamps['updatedAt'] = now
        _atomic_write_text(Path(canvas_path), json.dumps(next_canvas, ensure_ascii=False, indent=2) + '\n')
        new_rev = deps['canvas_rev'](next_canvas)
        events = deps['canvas_diff_events'](prev_canvas, next_canvas, actor)
        existing_event_keys = {
            (str(event.get('event') or ''), str(event.get('node_id') or ''))
            for event in events
            if isinstance(event, dict)
        }
        for event in _node_changed_event(actor, current_node, node):
            event_key = (str(event.get('event') or ''), str(event.get('node_id') or ''))
            if event_key not in existing_event_keys:
                events.append(event)
                existing_event_keys.add(event_key)
        if not deps['canvas_events_append'](canvas_path, events):
            return deps['canvas_event_append_failure'](canvas_rel, new_rev, next_canvas), 500
        lineage_ok = deps['lineage_record_canvas_events'](task_rel_path, events, canvas_rel, actor=actor)
        today = datetime.now().strftime('%Y-%m-%d')
        for field, value in (
            ('canvas_ref', canvas_rel),
            ('canvas_schema', deps['canvas_schema']),
            ('canvas_updated', today),
        ):
            ok, msg = deps['update_frontmatter_field'](task_rel_path, field, value)[:2]
            if not ok:
                return {'ok': False, 'error': f'{field} 回写失败: {msg}'}, 500
        result = {
            'ok': True,
            'mode': 'node_merge',
            'node_id': node_id,
            'merged_from_stale_base': bool(expected_rev and expected_rev != current_rev),
            'canvas_ref': canvas_rel,
            'canvas_updated': today,
            'canvas_rev': new_rev,
            'rev': new_rev,
            'canvas': next_canvas,
            'path_status_counts': deps['canvas_status_counts'](next_canvas),
        }
        if not lineage_ok:
            result['lineage_warning'] = '血缘台账写入失败'
        return result, 200


def lint_text_copies_for_task(deps: dict[str, Any], task_id: str) -> tuple[dict[str, Any], int]:
    task_rel_path, task_file, err, status = _scan_task_by_id(deps, task_id)
    if err:
        return {'ok': False, 'error': err}, status
    fm = (task_file or {}).get('frontmatter') or {}
    canvas_path, canvas_rel, ref_err, status = deps['resolve_canvas_ref'](task_rel_path, fm)
    if ref_err:
        return {'ok': False, 'error': ref_err}, status
    canvas, load_err = deps['read_existing_canvas'](canvas_path)
    if load_err:
        return {'ok': False, 'error': load_err}, 400
    if not canvas:
        return {'ok': True, 'task_id': _task_id_for_task(task_rel_path, task_file), 'canvas_ref': canvas_rel, 'findings': [], 'count': 0}, 200
    body = str((task_file or {}).get('body') or '')
    title = str(fm.get('title') or '')
    haystack = f'{title}\n{body}'
    findings = []
    for node in canvas.get('nodes') or []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get('type') or '')
        if node_type not in {'text', 'markdown', 'note'}:
            continue
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        if isinstance(data.get('source_ref'), dict):
            continue
        text = str(data.get('content') or data.get('text') or data.get('label') or data.get('title') or '').strip()
        if len(text) < 80:
            continue
        reason = 'long_text_without_ref'
        if text in haystack:
            reason = 'copies_task_card_text'
        findings.append({
            'node_id': str(node.get('id') or ''),
            'node_type': node_type,
            'reason': reason,
            'text_len': len(text),
            'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()[:16],
            'recommendation': '改为 ref 节点或缩短为画布原生备注',
        })
    return {
        'ok': True,
        'task_id': _task_id_for_task(task_rel_path, task_file),
        'path': task_rel_path,
        'canvas_ref': canvas_rel,
        'count': len(findings),
        'findings': findings,
    }, 200


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith('---\n'):
        return {}, text
    end = text.find('\n---', 4)
    if end < 0:
        return {}, text
    fm: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        fm[key.strip()] = value.strip().strip('"\'')
    return fm, text[end + 4:].lstrip('\n')


def _cli_deps(repo_root: Path) -> dict[str, Any]:
    def scan_all():
        docs = []
        for path in (repo_root / 'project').glob('*/*.md'):
            if '/.' in str(path.relative_to(repo_root)):
                continue
            fm, body = _parse_frontmatter(path.read_text(encoding='utf-8'))
            rel = str(path.relative_to(repo_root))
            docs.append({'path': rel, **fm, 'body': body})
        return docs

    def read_task_file(rel_path):
        path = repo_root / rel_path
        if not path.exists():
            return None, '文件不存在'
        fm, body = _parse_frontmatter(path.read_text(encoding='utf-8'))
        return {'frontmatter': fm, 'body': body}, ''

    def resolve_canvas_ref(rel_path, fm):
        task_path = Path(rel_path)
        task_id = _safe_task_key(fm.get('task_id') or _task_id_from_rel_path(rel_path))
        rel = str(task_path.parent / '.canvas' / task_id / 'main.canvas.json')
        return repo_root / rel, rel, '', 200

    def read_existing_canvas(path):
        if not Path(path).exists():
            return None, ''
        return json.loads(Path(path).read_text(encoding='utf-8')), ''

    return {
        'repo_root': repo_root,
        'scan_all': scan_all,
        'read_task_file': read_task_file,
        'resolve_canvas_ref': resolve_canvas_ref,
        'read_existing_canvas': read_existing_canvas,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Kanban canvas ledger query helpers')
    parser.add_argument('--repo-root', default=str(Path.cwd()))
    sub = parser.add_subparsers(dest='command', required=True)
    lint = sub.add_parser('lint-text', help='report text/note nodes that look like copied facts')
    lint.add_argument('task_id')
    args = parser.parse_args(argv)
    deps = _cli_deps(Path(args.repo_root).resolve())
    if args.command == 'lint-text':
        payload, status = lint_text_copies_for_task(deps, args.task_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if status < 400 else 1
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
