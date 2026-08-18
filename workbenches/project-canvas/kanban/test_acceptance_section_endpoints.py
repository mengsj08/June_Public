#!/usr/bin/env python3
"""Tests for completion criteria checkbox and section update endpoints."""

import io
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import importlib.util

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


class _Resp:
    def __init__(self):
        self.status_code = None
        self.json = None


def _make_handler(path, payload):
    resp = _Resp()
    raw = json.dumps(payload).encode('utf-8')

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {'Host': 'localhost', 'Content-Length': str(len(raw))}
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


def _write_task(repo, rel_path='project/Hermes/acceptance.md', body=None):
    task_path = repo / rel_path
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(
        """---
title: Acceptance Task
task_id: ACC-1
workdir: project/Hermes/
created: 2026-06-01
updated: 2026-06-01
assignee: Alice
priority: high
status: todo
tags: []
---

"""
        + (body if body is not None else """## 要做什么
Ship acceptance criteria editing.

## 完成标准
- [ ] First criterion
- [x] Second criterion

## 执行结果
<!-- 结果追加到这里 -->
"""),
        encoding='utf-8',
    )
    return task_path


def _call_put(repo, path, payload, user='Alice'):
    handler, resp = _make_handler(path, payload)
    with patch.object(scan_mod, 'REPO_ROOT', repo), \
         patch.object(scan_mod.Handler, '_get_session', return_value={'user': user}):
        handler.do_PUT()
    return resp


def test_toggle_check_updates_acceptance_checkbox(tmp_path):
    task_path = _write_task(tmp_path)
    resp = _call_put(tmp_path, '/api/toggle-check', {
        'path': 'project/Hermes/acceptance.md',
        'index': 0,
        'expected_text': 'First criterion',
        'checked': True,
    })

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    saved = task_path.read_text(encoding='utf-8')
    assert '- [x] First criterion' in saved
    assert '- [x] Second criterion' in saved
    assert f"updated: {datetime.now().strftime('%Y-%m-%d')}" in saved


def test_toggle_check_out_of_range_returns_400_and_keeps_disk(tmp_path):
    task_path = _write_task(tmp_path)
    before = task_path.read_text(encoding='utf-8')
    resp = _call_put(tmp_path, '/api/toggle-check', {
        'path': 'project/Hermes/acceptance.md',
        'index': 9,
        'expected_text': 'Missing criterion',
        'checked': True,
    })

    assert resp.status_code == 400
    assert resp.json['ok'] is False
    assert task_path.read_text(encoding='utf-8') == before


def test_toggle_check_expected_text_mismatch_returns_409(tmp_path):
    task_path = _write_task(tmp_path)
    before = task_path.read_text(encoding='utf-8')
    resp = _call_put(tmp_path, '/api/toggle-check', {
        'path': 'project/Hermes/acceptance.md',
        'index': 0,
        'expected_text': 'Stale criterion',
        'checked': True,
    })

    assert resp.status_code == 409
    assert resp.json['ok'] is False
    assert '刷新后重试' in resp.json['message']
    assert task_path.read_text(encoding='utf-8') == before


def test_update_section_replaces_acceptance_and_appends_trace(tmp_path):
    task_path = _write_task(tmp_path, body="""## 要做什么
Ship acceptance criteria editing.

## 完成标准
- [ ] Old criterion

## 执行结果
<!-- 结果追加到这里 -->
""")

    resp = _call_put(tmp_path, '/api/update-section', {
        'path': 'project/Hermes/acceptance.md',
        'section': '完成标准',
        'body': '- [ ] New criterion\n- [x] Reviewed criterion',
    }, user='PI')

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    saved = task_path.read_text(encoding='utf-8')
    assert '- [ ] Old criterion' not in saved
    assert '## 完成标准\n- [ ] New criterion\n- [x] Reviewed criterion\n\n## 执行结果' in saved
    assert f"- 标准修订:{datetime.now().strftime('%Y-%m-%d')} by PI" in saved


def test_update_section_without_acceptance_returns_404_and_keeps_disk(tmp_path):
    task_path = _write_task(tmp_path, body="""## 要做什么
No completion section here.

## 执行结果
<!-- 结果追加到这里 -->
""")
    before = task_path.read_text(encoding='utf-8')

    resp = _call_put(tmp_path, '/api/update-section', {
        'path': 'project/Hermes/acceptance.md',
        'section': '完成标准',
        'body': '- [ ] New criterion',
    })

    assert resp.status_code == 404
    assert resp.json['ok'] is False
    assert task_path.read_text(encoding='utf-8') == before
