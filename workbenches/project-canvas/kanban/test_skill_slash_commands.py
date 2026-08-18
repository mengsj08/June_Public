#!/usr/bin/env python3
"""
Tests for AI Activity slash commands and Skill loading.
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)
Handler = scan_mod.Handler


class ResponseCapture:
    def __init__(self):
        self.status_code = None
        self.headers = {}
        self.body = None

    @property
    def json(self):
        return json.loads(self.body.decode('utf-8')) if self.body else None


def make_handler(path):
    response = ResponseCapture()

    class TestHandler(Handler):
        def __init__(self):
            self.path = path
            self._response = response

        def send_response(self, code, message=None):
            response.status_code = code

        def send_header(self, key, value):
            response.headers[key] = value

        def end_headers(self):
            pass

        def _json(self, data, code=200):
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            response.status_code = code
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            response.headers['Content-Length'] = str(len(body))
            response.body = body

        def send_error(self, code, message=None):
            response.status_code = code
            response.body = json.dumps({'ok': False, 'error': message or 'Not Found'}).encode('utf-8')

    return TestHandler(), response


@pytest.fixture
def repo_with_skills(tmp_path):
    proj = tmp_path / 'project' / 'Hermes'
    proj.mkdir(parents=True)
    (proj / 'task.md').write_text('---\ntitle: Task\n---\nbody', encoding='utf-8')

    skills = tmp_path / '.claude' / 'skills'
    (skills / 'markdown-to-pdf').mkdir(parents=True)
    (skills / 'markdown-to-docx').mkdir(parents=True)
    (skills / 'skip-me').mkdir(parents=True)
    (skills / 'markdown-to-pdf' / 'SKILL.md').write_text(
        "---\nname: markdown-to-pdf\ndescription: PDF export\nargument-hint: input file\n---\nPDF skill $ARGUMENTS $0 $1",
        encoding='utf-8'
    )
    (skills / 'markdown-to-docx' / 'SKILL.md').write_text(
        "---\nname: markdown-to-docx\ndescription: DOCX export\n---\nDOCX skill",
        encoding='utf-8'
    )
    return tmp_path


def test_scan_skills_returns_top_level_only(repo_with_skills):
    with patch.object(scan_mod, 'REPO_ROOT', repo_with_skills):
        skills = scan_mod._scan_skills()
    assert [s['id'] for s in skills] == ['markdown-to-docx', 'markdown-to-pdf']
    assert skills[0]['description'] == 'DOCX export'
    assert skills[1]['argument_hint'] == 'input file'


def test_load_skill_rejects_escape(repo_with_skills):
    with patch.object(scan_mod, 'REPO_ROOT', repo_with_skills):
        assert scan_mod._load_skill('../escape') is None
        assert scan_mod._load_skill_content('../escape') is None


def test_replace_skill_arguments(repo_with_skills):
    out = scan_mod._replace_skill_arguments('x $ARGUMENTS y $0 z $1', 'skill-a', 'one two')
    assert out == 'x one two y skill-a z one'


def test_get_skills_endpoint(repo_with_skills):
    handler, resp = make_handler('/api/skills')
    with patch.object(scan_mod, 'REPO_ROOT', repo_with_skills):
        handler.do_GET()
    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert len(data['skills']) == 2


def test_ai_comment_keeps_original_history_and_uses_prompt(repo_with_skills):
    handler, resp = make_handler('/api/ai-comment')
    body = json.dumps({
        'run_id': 'r1',
        'comment': '/markdown-to-pdf report.md',
        'author': 'Tester',
        'skill_id': 'markdown-to-pdf',
    }).encode('utf-8')

    queue_entry = {
        'id': 'r1',
        'tool': 'claude',
        'status': 'completed',
        'session_id': 'sess-1',
        'session_valid': True,
        'workdir': 'project/Hermes/',
        'path': 'project/Hermes/task.md',
        'messages': [],
    }

    captured = {}

    def fake_queue_get_entry(run_id):
        return dict(queue_entry)

    def fake_queue_append_message(run_id, message):
        captured['message'] = message
        return True

    def fake_queue_update_entry(entry_id, updates, **kwargs):
        captured.setdefault('updates', {}).update(updates)
        return True

    class FakeThread:
        def __init__(self, *args, **kwargs):
            captured['thread_args'] = kwargs.get('args')
        def start(self):
            captured['thread_started'] = True

    with patch.object(scan_mod, 'REPO_ROOT', repo_with_skills), \
         patch.object(scan_mod.Handler, '_json', lambda self, data, code=200: None), \
         patch.object(scan_mod, '_queue_get_entry', side_effect=fake_queue_get_entry), \
         patch.object(scan_mod, '_queue_append_message', side_effect=fake_queue_append_message), \
         patch.object(scan_mod, '_queue_update_entry', side_effect=fake_queue_update_entry), \
         patch.object(scan_mod.threading, 'Thread', FakeThread), \
         patch.object(scan_mod, 'resolve_workdir', return_value=(repo_with_skills / 'project' / 'Hermes', None)), \
         patch.object(scan_mod, '_ai_semaphore') as sem:
        sem.acquire.return_value = True
        sem.release.return_value = None
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = __import__('io').BytesIO(body)
        handler.path = '/api/ai-comment'
        handler.do_POST()

    assert captured['message']['content'] == '/markdown-to-pdf report.md'
    assert captured['message']['skill_id'] == 'markdown-to-pdf'
    assert captured['updates']['prompt_length'] > 0
    assert captured['thread_started'] is True
