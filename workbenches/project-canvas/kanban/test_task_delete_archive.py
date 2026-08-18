#!/usr/bin/env python3
"""Tests for soft deleting task cards into .archive/."""

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


def _make_delete_handler(payload, headers=None):
    resp = _Resp()
    raw = json.dumps(payload).encode('utf-8')

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = '/api/task'
            self.headers = {'Host': 'localhost', 'Content-Length': str(len(raw))}
            if headers:
                self.headers.update(headers)
            self.rfile = io.BytesIO(raw)

        def send_response(self, code, message=None):
            resp.status_code = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

        def _json(self, data, code=200):
            resp.status_code = code
            resp.json = data

        def send_error(self, code, message=None):
            resp.status_code = code
            resp.json = {'ok': False, 'error': message or 'Not Found'}

    return TestHandler(), resp


def _write_task(repo, rel_path, status='todo'):
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: Delete Me
task_id: DEL-1
workdir: project/Delete/
created: 2026-06-01
updated: 2026-06-01
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


def test_delete_task_archives_card_and_removes_from_scan(tmp_path):
    src = _write_task(tmp_path, 'project/Delete/delete-me.md')
    handler, resp = _make_delete_handler({'path': 'project/Delete/delete-me.md'})

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project/Delete']), \
            patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Owner'}):
        handler.do_DELETE()
        remaining_paths = [doc['path'] for doc in scan_mod.scan_all()]

    archived = tmp_path / 'project' / 'Delete' / '.archive' / 'delete-me.md'
    assert resp.status_code == 200
    assert resp.json['ok'] is True
    assert resp.json['archived_path'] == 'project/Delete/.archive/delete-me.md'
    assert not src.exists()
    assert archived.exists()
    assert 'project/Delete/delete-me.md' not in remaining_paths


def test_delete_task_rejects_unauthorized_and_cross_origin(tmp_path):
    src = _write_task(tmp_path, 'project/Delete/delete-me.md')

    handler, resp = _make_delete_handler({'path': 'project/Delete/delete-me.md'})
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project/Delete']), \
            patch.object(scan_mod.Handler, '_get_session', return_value=None):
        handler.do_DELETE()

    assert resp.status_code == 401
    assert src.exists()

    handler, resp = _make_delete_handler(
        {'path': 'project/Delete/delete-me.md'},
        {'Origin': 'https://evil.example'},
    )
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project/Delete']), \
            patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Owner'}):
        handler.do_DELETE()

    assert resp.status_code == 403
    assert resp.json == {'ok': False, 'error': 'cross-origin blocked'}
    assert src.exists()


def test_delete_task_rejects_path_outside_scan_dirs(tmp_path):
    src = _write_task(tmp_path, 'project/Other/delete-me.md')
    _write_task(tmp_path, 'project/Delete/allowed.md')
    handler, resp = _make_delete_handler({'path': 'project/Other/delete-me.md'})

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project/Delete']), \
            patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Owner'}):
        handler.do_DELETE()

    assert resp.status_code == 403
    assert resp.json['ok'] is False
    assert 'scan_dirs' in resp.json['error']
    assert src.exists()
    assert not (tmp_path / 'project' / 'Other' / '.archive' / 'delete-me.md').exists()
