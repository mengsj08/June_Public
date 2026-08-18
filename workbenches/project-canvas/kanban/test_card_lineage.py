#!/usr/bin/env python3
"""Tests for card lineage sidecars and hooks."""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


class _Resp:
    def __init__(self):
        self.status_code = None
        self.json = None


def _write_task(repo, rel_path, task_id='LIN-1', title='Lineage Task', status='todo'):
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: {title}
task_id: {task_id}
workdir: project/Lineage/
created: 2026-07-01
updated: 2026-07-01
assignee: Owner
priority: medium
status: {status}
tags: []
---

Body.
""",
        encoding='utf-8',
    )
    return path


def _lineage_events(repo, rel_path):
    lineage = repo / scan_mod._lineage_rel_for_task(rel_path)
    if not lineage.exists():
        return []
    return [json.loads(line) for line in lineage.read_text(encoding='utf-8').splitlines() if line.strip()]


def _make_get_handler(path):
    resp = _Resp()

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {'Host': 'localhost'}
            self.rfile = io.BytesIO(b'')

        def _json(self, data, code=200):
            resp.status_code = code
            resp.json = data

        def _get_session(self):
            return {'user': 'Owner'}

        def send_error(self, code, message=None):
            resp.status_code = code
            resp.json = {'ok': False, 'error': message or 'Not Found'}

    return TestHandler(), resp


def test_lineage_path_jail_and_dedupe(tmp_path):
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        assert scan_mod._lineage_rel_for_task('project/Lineage/task.md') == 'project/Lineage/.lineage/task/ledger.jsonl'
        assert scan_mod._lineage_rel_for_task('../outside.md') is None
        event = scan_mod._lineage_base_event(
            'project/Lineage/task.md',
            'unit',
            event_id='fixed-event',
        )
        assert scan_mod._lineage_append_events('project/Lineage/task.md', [event]) == 1
        assert scan_mod._lineage_append_events('project/Lineage/task.md', [event]) == 0
        events, err = scan_mod._lineage_read_events('project/Lineage/task.md')

    assert err == ''
    assert len(events) == 1
    assert events[0]['schema'] == scan_mod.CARD_LINEAGE_SCHEMA
    assert events[0]['sensitivity'] == 'metadata_only'


def test_comments_and_lineage_sidecars_follow_demo_scan_dirs(tmp_path):
    rel_path = 'demo/projects/literature-review/DEMO-001.md'
    _write_task(tmp_path, rel_path, task_id='DEMO-001', title='Demo card')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['demo/projects/literature-review']):
        comments_rel = scan_mod._ledger_rel_for_task(rel_path)
        lineage_rel = scan_mod._lineage_rel_for_task(rel_path)
        assert scan_mod._ledger_append_events(rel_path, [{'event': 'demo-comment'}]) is True
        assert scan_mod._lineage_record_event(rel_path, 'demo-created') is True

    assert comments_rel == 'demo/projects/literature-review/.comments/DEMO-001/ledger.jsonl'
    assert lineage_rel == 'demo/projects/literature-review/.lineage/DEMO-001/ledger.jsonl'
    assert (tmp_path / comments_rel).is_file()
    assert (tmp_path / lineage_rel).is_file()


def test_frontmatter_status_change_records_lineage(tmp_path):
    _write_task(tmp_path, 'project/Lineage/task.md')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        ok, msg = scan_mod.update_frontmatter_field(
            'project/Lineage/task.md',
            'status',
            'in-progress',
            _suppress_decision_log=True,
        )

    assert ok, msg
    events = _lineage_events(tmp_path, 'project/Lineage/task.md')
    change = [e for e in events if e.get('event') == 'frontmatter_changed']
    assert change
    assert change[-1]['field'] == 'status'
    assert change[-1]['old_value'] == 'todo'
    assert change[-1]['new_value'] == 'in-progress'


def test_queue_records_codex_thread_and_fork_parent(tmp_path):
    _write_task(tmp_path, 'project/Lineage/task.md')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        run_id = scan_mod._queue_add_entry('codex', 'project/Lineage/task.md', 'project/Lineage/')
        scan_mod._queue_update_entry(run_id, {
            'status': 'completed',
            'session_id': 'codex-thread-123',
            'session_valid': True,
            'duration_ms': 12,
            'output_length': 34,
            'completed_at': '2026-07-04T10:00:00',
        })
        fork_id = scan_mod._queue_add_entry(
            'claude',
            'project/Lineage/task.md',
            'project/Lineage/',
            metadata={'fork': {'parent_run_id': run_id, 'parent_entry_id': f'{run_id}#0', 'parent_index': 0}},
        )

    events = _lineage_events(tmp_path, 'project/Lineage/task.md')
    queued = [e for e in events if e.get('event') == 'ai_run_queued' and e.get('run_id') == run_id]
    completed = [e for e in events if e.get('event') == 'ai_run_completed' and e.get('run_id') == run_id]
    forked = [e for e in events if e.get('event') == 'ai_fork_queued' and e.get('run_id') == fork_id]
    assert queued
    assert completed
    assert completed[-1]['thread_id'] == 'codex-thread-123'
    assert completed[-1]['tool_session_kind'] == 'codex_thread'
    assert 'session_id' not in completed[-1]
    assert forked[-1]['parent_entry_id'] == f'{run_id}#0'


def test_canvas_source_ref_and_archive_record_lineage(tmp_path):
    _write_task(tmp_path, 'project/Lineage/task.md')
    canvas = {
        'schema': scan_mod.CANVAS_SCHEMA,
        'id': 'lineage',
        'name': 'Lineage',
        'nodes': [{
            'id': 'ref_run',
            'type': 'ref',
            'position': {'x': 10, 'y': 20},
            'data': {
                'label': 'codex run',
                'source_ref': {
                    'kind': 'comment',
                    'path': 'project/Lineage/task.md',
                    'run_id': 'run-1',
                },
            },
        }],
        'edges': [],
        'viewport': {'x': 0, 'y': 0, 'zoom': 1},
    }

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project/Lineage']):
        result, status = scan_mod._save_canvas_for_task('project/Lineage/task.md', canvas, actor='codex')
        archived, archive_status = scan_mod.archive_task_card('project/Lineage/task.md')

    assert status == 200
    assert result['ok'] is True
    assert archive_status == 200
    assert archived['ok'] is True
    events = _lineage_events(tmp_path, 'project/Lineage/task.md')
    assert any(e.get('event') == 'canvas_source_bound' and e.get('run_id') == 'run-1' for e in events)
    assert any(e.get('event') == 'card_archived' for e in events)


def test_card_lineage_api_and_pilot_backfill(tmp_path):
    _write_task(tmp_path, 'project/Lineage/KAN-109_demo.md', task_id='KAN-109', title='KAN 109')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project/Lineage']):
        dry = scan_mod.backfill_card_lineage(task_ids=['KAN-109'], dry_run=True)
        assert dry['targets'][0]['status'] == 'would_write'
        assert not (tmp_path / 'project' / 'Lineage' / '.lineage').exists()

        written = scan_mod.backfill_card_lineage(task_ids=['KAN-109'], dry_run=False)
        assert written['targets'][0]['status'] == 'written'

        handler, resp = _make_get_handler('/api/card-lineage?path=project/Lineage/KAN-109_demo.md')
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    assert resp.json['schema'] == scan_mod.CARD_LINEAGE_SCHEMA
    assert resp.json['count'] == 1
    assert resp.json['entries'][0]['event'] == 'pilot_backfill'
