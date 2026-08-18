#!/usr/bin/env python3
"""
Tests for GET /api/task endpoint.

Run with: CI=true python3 -m pytest shared/toolkit/kanban/test_task_endpoint.py -v
"""

import json
import os
import sys
import tempfile
import shutil
import io
import base64
import hmac
import hashlib
import inspect
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the module — file is scan-docs.py (dash, not underscore)
_HERE = Path(__file__).resolve().parent
import importlib.util
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)
Handler = scan_mod.Handler
extract_frontmatter = scan_mod.extract_frontmatter


# ── Test fixture helpers ──────────────────────────────────

class MockRequest:
    """Minimal mock for BaseHTTPRequestHandler test harness."""
    def __init__(self, method, path, body=None):
        self.method = method
        self.path = path
        self._body = body or b''

    def makefile(self, mode, buffering=None):
        import io
        content = f"{self.method} {self.path} HTTP/1.1\r\nHost: localhost\r\n"
        if self._body:
            content += f"Content-Length: {len(self._body)}\r\n"
        content += "\r\n"
        content = content.encode('utf-8')
        if self._body:
            content += self._body
        return io.BytesIO(content)


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repo structure with sample task files."""
    # Create project dir
    proj_dir = tmp_path / "project" / "Hermes"
    proj_dir.mkdir(parents=True)

    # Create a sample task file with frontmatter + body
    task_content = """---
title: Sample Task
task_id: HER-1
workdir: project/Hermes/
created: 2026-05-01
updated: 2026-05-02
assignee: Alice
priority: high
status: todo
tags: [backend, api]
---

# Sample Task

This is the markdown body of the task.

## Subsection

- Item 1
- Item 2
"""
    (proj_dir / "sample-task.md").write_text(task_content, encoding='utf-8')

    # Create another task for code resolution testing
    task2_content = """---
title: Second Task
task_id: HER-2
workdir: project/Hermes/
created: 2026-05-03
updated: 2026-05-03
assignee: Bob
priority: medium
status: in-progress
tags: []
---

Body of second task.
"""
    (proj_dir / "second-task.md").write_text(task2_content, encoding='utf-8')

    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z7xQAAAAASUVORK5CYII="
    )
    (proj_dir / "local-image.png").write_bytes(png_bytes)

    return tmp_path


class ResponseCapture:
    """Captures response data from Handler."""
    def __init__(self):
        self.status_code = None
        self.headers = {}
        self.body = None

    @property
    def json(self):
        if self.body:
            return json.loads(self.body.decode('utf-8'))
        return None


def make_handler(path, temp_repo):
    """Create a Handler instance that routes to our temp repo, capture response."""
    response = ResponseCapture()

    class TestHandler(Handler):
        def __init__(self):
            # Skip parent __init__ — we just need the method
            self.path = path
            self._response = response
            self._test_repo = temp_repo

        def send_response(self, code, message=None):
            response.status_code = code

        def send_header(self, key, value):
            response.headers[key] = value

        def end_headers(self):
            pass

        def wfile_write(self, data):
            # We override _json to capture instead of writing to wfile
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


def _minimal_canvas(rel_path, node_id='card', label='card'):
    return {
        'schema': scan_mod.CANVAS_SCHEMA,
        'id': 'HER-1',
        'name': 'Manual canvas',
        'nodes': [
            {
                'id': node_id,
                'type': 'ref',
                'position': {'x': 0, 'y': 0},
                'data': {
                    'label': label,
                    'source_ref': {'kind': 'card', 'path': rel_path},
                },
            },
        ],
        'edges': [],
        'viewport': {'x': 0, 'y': 0, 'zoom': 1},
    }


def _note_node(node_id, text):
    return {
        'id': node_id,
        'type': 'note',
        'position': {'x': 120, 'y': 120},
        'data': {'label': text, 'text': text, 'canvas_native': True},
    }


def _clone_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _put_canvas_api(temp_repo, payload):
    handler, resp = make_handler('/api/canvas', temp_repo)
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = io.BytesIO(body)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_PUT()
    return resp


def _put_canvas_node_api(temp_repo, payload):
    handler, resp = make_handler('/api/canvas/node', temp_repo)
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = io.BytesIO(body)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_PUT()
    return resp


def _post_canvas_refresh_api(temp_repo, payload):
    handler, resp = make_handler('/api/canvas/refresh', temp_repo)
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = io.BytesIO(body)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_POST()
    return resp


def _json_api_request(method, path, temp_repo, payload=None):
    handler, resp = make_handler(path, temp_repo)
    body = json.dumps(payload or {}, ensure_ascii=False).encode('utf-8') if payload is not None else b''
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = io.BytesIO(body)
    getattr(handler, f'do_{method}')()
    return resp


def _canvas_events(temp_repo, canvas_ref):
    events_path = temp_repo / Path(canvas_ref).parent / 'events.jsonl'
    if not events_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]


# ── Test: GET /api/task?path=<valid> → 200 ──────────────────

def test_attention_queue_endpoint_forwards_project_scope(temp_repo):
    handler, resp = make_handler('/api/attention-queue?project=research-alpha', temp_repo)
    captured = {}

    def build_queue(tasks, classifier, **kwargs):
        captured.update(tasks=tasks, classifier=classifier, kwargs=kwargs)
        return {'ok': True, 'scope': 'project', 'project': kwargs['project']}

    docs = [{'task_id': 'RSH-1', 'project_ref': 'research-alpha'}]
    with patch.object(handler, '_state_change_guard', return_value=True), \
         patch.object(scan_mod, 'scan_all', return_value=docs), \
         patch.object(scan_mod.attention_queue, 'build_attention_queue', side_effect=build_queue):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json == {'ok': True, 'scope': 'project', 'project': 'research-alpha'}
    assert captured['tasks'] == docs
    assert captured['classifier'] is scan_mod.requires_owner_action
    assert captured['kwargs'] == {
        'project': 'research-alpha',
        'record_classifier': scan_mod.attention_gate.is_backstage_record,
    }


def test_system_alerts_endpoint_is_thin_and_guarded(temp_repo):
    if scan_mod.system_alerts is None:
        pytest.skip('missing optional source path: kanban/system_alerts.py')
    handler, resp = make_handler('/api/system-alerts', temp_repo)
    docs = [{'task_id': 'KMO-1', 'status': 'blocked', 'stage': 'km/triage_queue'}]
    chains = [{'key': 'km', 'stages': [{'key': 'km/triage_queue'}]}]
    expected = {'ok': True, 'has_anomaly': True, 'count': 1, 'items': []}

    with patch.object(handler, '_state_change_guard', return_value=True) as guard, \
         patch.object(scan_mod, 'scan_all', return_value=docs), \
         patch.object(scan_mod, 'configured_chains', return_value=chains), \
         patch.object(scan_mod, 'get_governance_healthcheck_status', return_value={'ok': True, 'latest': None}), \
         patch.object(scan_mod, 'get_governance_noise_review_status', return_value={'ok': True, 'latest': None}), \
         patch.object(scan_mod.system_alerts, 'build_system_alerts', return_value=expected) as build:
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json == expected
    guard.assert_called_once_with('/api/system-alerts')
    build.assert_called_once_with(
        docs,
        chains,
        {'ok': True, 'latest': None},
        {'ok': True, 'latest': None},
    )


def test_get_task_by_path_returns_200(temp_repo):
    """GET /api/task?path=project/Hermes/sample-task.md returns 200 with full task data."""
    handler, resp = make_handler('/api/task?path=project/Hermes/sample-task.md', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    task = data['task']
    assert task['path'] == 'project/Hermes/sample-task.md'
    assert task['filename'] == 'sample-task.md'
    assert task['project'] == 'Hermes'
    assert task['title'] == 'Sample Task'
    assert task['workdir'] == 'project/Hermes/'
    assert task['status'] == 'todo'
    assert task['priority'] == 'high'
    assert task['assignee'] == 'Alice'
    assert task['created'] == '2026-05-01'
    assert task['updated'] == '2026-05-02'
    assert task['tags'] == ['backend', 'api']
    assert 'task_id' in task
    # Body should contain markdown after frontmatter, no --- delimiters
    assert '# Sample Task' in task['body']
    assert '---' not in task['body']
    # Raw should contain complete file including frontmatter
    assert '---' in task['raw']
    assert 'title: Sample Task' in task['raw']
    assert '# Sample Task' in task['raw']


# ── Test: GET /api/task?code=<code> → 200 ──────────────────

def test_get_task_by_code_returns_200(temp_repo):
    """GET /api/task?code=HER-1 resolves to correct task."""
    handler, resp = make_handler('/api/task?code=HER-1', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    task = data['task']
    assert task['task_id'] == 'HER-1'
    assert task['title'] == 'Sample Task'
    assert task['path'] == 'project/Hermes/sample-task.md'
    assert task['workdir'] == 'project/Hermes/'


def test_get_task_detail_includes_team_handoff_tracking_fields(temp_repo):
    task_path = temp_repo / 'project' / 'Hermes' / 'handoff.md'
    task_path.write_text("""---
title: Handoff Task
task_id: HER-3
workdir: project/Hermes/
created: 2026-06-13
updated: 2026-06-13
assignee: Alice
priority: medium
status: todo
tags: [team]
source: team-kanban/TK-1
stage: team/publish
remote_url: https://kb.example.test/card/TK-1
team_path: project/Alpha/card.md
promoted_to: team-workspace/project/Alpha/card.md
team_handoff_status: pushed
team_handoff_url: https://github.com/example-org/team-workspace/blob/main/project/Alpha/card.md
next_action: handoff-team-published
---

Body.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        result, status = scan_mod.get_task_detail(path='project/Hermes/handoff.md')

    assert status == 200
    task = result['task']
    assert task['source'] == 'team-kanban/TK-1'
    assert task['stage'] == 'team/publish'
    assert task['remote_url'] == 'https://kb.example.test/card/TK-1'
    assert task['team_path'] == 'project/Alpha/card.md'
    assert task['promoted_to'] == 'team-workspace/project/Alpha/card.md'
    assert task['team_handoff_status'] == 'pushed'
    assert task['team_handoff_url'] == 'https://github.com/example-org/team-workspace/blob/main/project/Alpha/card.md'
    assert task['next_action'] == 'handoff-team-published'


# ── Test: GET /api/task?code=INVALID-999 → 404 ──────────────

def test_get_task_by_unknown_code_returns_404(temp_repo):
    """GET /api/task?code=INVALID-999 returns 404."""
    handler, resp = make_handler('/api/task?code=INVALID-999', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 404
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == '文件不存在'


# ── Test: GET /api/task?path=../etc/passwd → 400 ─────────────

def test_get_task_path_traversal_returns_400(temp_repo):
    """GET /api/task?path=../etc/passwd returns 400 with 非法路径."""
    handler, resp = make_handler('/api/task?path=../etc/passwd', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 400
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == '非法路径'


# ── Test: GET /api/task?path=/absolute/path → 400 ────────────

def test_get_task_absolute_path_returns_400(temp_repo):
    """GET /api/task?path=/absolute/path returns 400 with 非法路径."""
    handler, resp = make_handler('/api/task?path=/absolute/path', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 400
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == '非法路径'


# ── Test: GET /api/task?path=nonexistent/file.md → 404 ──────

def test_get_task_nonexistent_file_returns_404(temp_repo):
    """GET /api/task?path=nonexistent/file.md returns 404."""
    handler, resp = make_handler('/api/task?path=nonexistent/file.md', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 404
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == '文件不存在'


# ── Test: GET /api/task with no params → 400 ────────────────

def test_get_task_no_params_returns_400(temp_repo):
    """GET /api/task with no path or code param returns 400 with 缺少参数."""
    handler, resp = make_handler('/api/task', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 400
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == '缺少参数'


# ── Test: Response body field format ────────────────────────

def test_response_body_field_format(temp_repo):
    """Body field contains markdown after frontmatter, not including --- delimiters."""
    handler, resp = make_handler('/api/task?path=project/Hermes/sample-task.md', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 200
    body = resp.json['task']['body']
    # Body should NOT contain frontmatter delimiters
    assert '---' not in body
    # Body should NOT contain frontmatter fields
    assert 'title:' not in body
    assert 'assignee:' not in body
    # Body should contain actual markdown content
    assert '# Sample Task' in body
    assert '- Item 1' in body


# ── Test: Response raw field format ─────────────────────────

def test_response_raw_field_format(temp_repo):
    """Raw field contains complete file content including frontmatter."""
    handler, resp = make_handler('/api/task?path=project/Hermes/sample-task.md', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 200
    raw = resp.json['task']['raw']
    # Raw should contain frontmatter delimiters
    assert '---' in raw
    # Raw should contain frontmatter fields
    assert 'title: Sample Task' in raw
    assert 'assignee: Alice' in raw
    # Raw should also contain body
    assert '# Sample Task' in raw
    assert '- Item 1' in raw


# ── Test: Response includes task_id ───────────────────────

def test_response_includes_task_id(temp_repo):
    """Response includes task_id field matching the project code."""
    handler, resp = make_handler('/api/task?path=project/Hermes/sample-task.md', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 200
    task = resp.json['task']
    assert task['task_id'] == 'HER-1'


def test_task_detail_can_resolve_legacy_id(temp_repo):
    task_path = temp_repo / 'project' / 'Hermes' / 'sample-task.md'
    content = task_path.read_text(encoding='utf-8').replace(
        'task_id: HER-1',
        'task_id: GOV-2\nlegacy_id: XXX-25',
    )
    task_path.write_text(content, encoding='utf-8')
    handler, resp = make_handler('/api/task?code=XXX-25', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 200
    task = resp.json['task']
    assert task['task_id'] == 'GOV-2'
    assert task['legacy_id'] == 'XXX-25'


def test_response_includes_rev(temp_repo):
    handler, resp = make_handler('/api/task?path=project/Hermes/sample-task.md', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 200
    task = resp.json['task']
    assert task['rev']
    assert len(task['rev']) == 64


def test_update_body_with_outdated_rev_merges_cleanly(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        original, _ = scan_mod.get_task_detail(path=rel_path)
    base_rev = original['task']['rev']
    base_body = original['task']['body']

    task_file = temp_repo / rel_path
    raw = task_file.read_text(encoding='utf-8')
    task_file.write_text(raw.replace('This is the markdown body of the task.\n', 'This is the markdown body of the task.\nRemote line.\n'), encoding='utf-8')

    handler, resp = make_handler('/api/update-body', temp_repo)
    merged_body = base_body + '\nLocal line.\n'
    payload = json.dumps({
        'path': rel_path,
        'body': merged_body,
        'base_rev': base_rev,
        'base_body': base_body,
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_PUT()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['merged'] is True
    saved = task_file.read_text(encoding='utf-8')
    assert 'Remote line.' in saved
    assert 'Local line.' in saved


def test_update_body_conflict_returns_409_and_keeps_disk(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        original, _ = scan_mod.get_task_detail(path=rel_path)
    base_rev = original['task']['rev']
    base_body = original['task']['body']

    task_file = temp_repo / rel_path
    raw = task_file.read_text(encoding='utf-8')
    task_file.write_text(raw.replace('This is the markdown body of the task.', 'Remote rewrite line.'), encoding='utf-8')

    handler, resp = make_handler('/api/update-body', temp_repo)
    payload = json.dumps({
        'path': rel_path,
        'body': base_body.replace('This is the markdown body of the task.', 'Local rewrite line.'),
        'base_rev': base_rev,
        'base_body': base_body,
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_PUT()

    assert resp.status_code == 409
    data = resp.json
    assert data['ok'] is False
    assert data['conflict'] is True
    assert '<<<<<<<' in data['body']
    saved = task_file.read_text(encoding='utf-8')
    assert 'Remote rewrite line.' in saved
    assert 'Local rewrite line.' not in saved


def test_ai_run_missing_workdir_returns_400(temp_repo):
    """POST /api/ai-run returns workdir_not_found when workdir does not exist."""
    proj_dir = temp_repo / "project" / "Hermes"
    task_path = proj_dir / "missing-workdir.md"
    task_path.write_text("""---
title: Missing Workdir
task_id: HER-3
workdir: project/Does-Not-Exist/
created: 2026-05-04
updated: 2026-05-04
assignee: Alice
priority: medium
status: todo
tags: []
---

Body.
""", encoding='utf-8')

    handler, resp = make_handler('/api/ai-run', temp_repo)
    payload = json.dumps({'path': 'project/Hermes/missing-workdir.md', 'tool': 'claude'}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_POST()

    assert resp.status_code == 400
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == 'workdir_not_found'
    assert data['workdir'].endswith('project/Does-Not-Exist')


def test_ai_run_canvas_context_prompt_keeps_display_message_clean(temp_repo):
    handler, resp = make_handler('/api/ai-run', temp_repo)
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'tool': 'codex',
        'prompt': '<canvas_upstream_context>upstream facts</canvas_upstream_context>\n\nDo the work',
        'display_message': 'Do the work',
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod.canvas_seed, 'start_local_summary_backfill', return_value=None), \
         patch.object(scan_mod, '_queue_consume_next', return_value=None):
        handler.do_POST()
        queue = scan_mod._queue_load()

    assert resp.status_code == 200
    entry = queue['entries'][0]
    assert '<canvas_upstream_context>upstream facts' in entry['prompt_override']
    assert entry['messages'][0]['content'] == 'Do the work'
    assert 'raw_prompt' not in entry['messages'][0]


def test_ai_run_card_chat_prompt_records_card_chat_origin(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    handler, resp = make_handler('/api/ai-run', temp_repo)
    payload = json.dumps({
        'path': rel_path,
        'tool': 'codex',
        'prompt': 'Ping from card chat',
        'display_message': 'Ping from card chat',
        'origin': 'card_chat',
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next', return_value=None):
        handler.do_POST()
        queue = scan_mod._queue_load()
        lineage_events, lineage_err = scan_mod._lineage_read_events(rel_path)

    assert resp.status_code == 200
    entry = queue['entries'][0]
    assert entry['metadata']['dialogue']['origin'] == 'card_chat'
    assert entry['ai_profile'] == 'deep_codex'
    assert entry['messages'][0]['content'] == 'Ping from card chat'
    assert lineage_err == ''
    queued_events = [e for e in lineage_events if e.get('event') == 'ai_run_queued']
    assert queued_events[-1]['run_id'] == entry['id']
    assert queued_events[-1]['origin'] == 'card_chat'


def test_ai_run_persists_source_quote_without_polluting_display_message(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    source_quote = {
        'quote_text': 'This is the markdown body of the task.',
        'section': '背景',
        'context': {'prefix': 'before ', 'suffix': ' after'},
        'source_locator': {
            'task_path': rel_path,
            'body_rev': 'rev-1',
            'text_index': 12,
            'prefix': 'before ',
            'suffix': ' after',
            'block_index': 0,
        },
    }
    handler, resp = make_handler('/api/ai-run', temp_repo)
    payload = json.dumps({
        'path': rel_path,
        'tool': 'codex',
        'prompt': '请检查这里',
        'display_message': '请检查这里',
        'origin': 'card_chat',
        'source_quote': source_quote,
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next', return_value=None):
        handler.do_POST()
        queue = scan_mod._queue_load()

    assert resp.status_code == 200
    entry = queue['entries'][0]
    assert entry['messages'][0]['content'] == '请检查这里'
    assert entry['messages'][0]['source_quote']['quote_text'] == source_quote['quote_text']
    assert entry['messages'][0]['source_quote']['source_locator']['task_path'] == rel_path
    assert '【任务正文引用（章节：背景）】' in entry['prompt_override']
    assert source_quote['quote_text'] in entry['prompt_override']


def test_source_quote_rejects_cross_task_locator():
    quote, error = scan_mod._normalize_source_quote({
        'quote_text': 'quoted',
        'source_locator': {'task_path': 'project/Other/card.md'},
    }, 'project/Hermes/sample-task.md')
    assert quote is None
    assert error == '正文引用不属于当前任务卡'


def test_ai_run_canvas_context_prompt_is_durable_in_comments_ledger(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    raw_prompt = (
        '<canvas_upstream_context>upstream facts</canvas_upstream_context>\n\n'
        '<user_request>Do the work</user_request>'
    )
    handler, resp = make_handler('/api/ai-run', temp_repo)
    payload = json.dumps({
        'path': rel_path,
        'tool': 'codex',
        'prompt': raw_prompt,
        'display_message': 'Do the work',
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next', return_value=None):
        handler.do_POST()
        events, ledger_err = scan_mod._ledger_read_events(rel_path)

    assert resp.status_code == 200
    assert ledger_err == ''
    assert len(events) == 1
    event = events[0]
    assert event['event'] == 'message'
    assert event['role'] == 'user'
    assert event['content'] == 'Do the work'
    assert event['content_truncated'] is False
    assert event['prompt_audit_version'] == scan_mod.COMMENTS_PROMPT_AUDIT_VERSION
    assert event['prompt_source'] == 'prompt_override'
    assert '<canvas_upstream_context>upstream facts</canvas_upstream_context>' in event['raw_prompt']
    assert '<user_request>Do the work</user_request>' in event['raw_prompt']
    assert f'本对话挂在任务卡 {rel_path}' in event['raw_prompt']
    assert event['raw_prompt_len'] == len(event['raw_prompt'])
    assert event['raw_prompt_sha256'] == scan_mod.hashlib.sha256(
        event['raw_prompt'].encode('utf-8')
    ).hexdigest()[:16]


def test_ai_run_without_custom_prompt_does_not_add_prompt_audit_ledger(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    handler, resp = make_handler('/api/ai-run', temp_repo)
    payload = json.dumps({'path': rel_path, 'tool': 'codex'}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next', return_value=None):
        handler.do_POST()
        queue = scan_mod._queue_load()
        events, ledger_err = scan_mod._ledger_read_events(rel_path)

    assert resp.status_code == 200
    assert queue['entries'][0].get('prompt_override') is None
    assert queue['entries'][0]['messages'] == []
    assert ledger_err == ''
    assert events == []


def test_landing_refresh_missing_landing_page_returns_400(temp_repo):
    handler, resp = make_handler('/api/landing/refresh', temp_repo)
    payload = json.dumps({'path': 'project/Hermes/sample-task.md'}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}):
        handler.do_POST()

    assert resp.status_code == 400
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == '缺少 landing_page'


def test_landing_refresh_enqueues_codex_and_stamps_on_success(temp_repo):
    landing_dir = temp_repo / 'landing'
    landing_dir.mkdir()
    (landing_dir / 'status.html').write_text('<!doctype html><title>Old</title>', encoding='utf-8')
    task_path = temp_repo / 'project' / 'Hermes' / 'landing-task.md'
    task_path.write_text("""---
title: Landing Task
task_id: HER-9
workdir: .
created: 2026-06-13
updated: 2026-06-14
assignee: Alice
priority: medium
status: in-progress
tags: []
landing_page: landing/status.html
landing_updated: 2026-06-13
---

Body for landing refresh.
""", encoding='utf-8')

    handler, resp = make_handler('/api/landing/refresh', temp_repo)
    payload = json.dumps({'path': 'project/Hermes/landing-task.md'}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    def fake_consume_next():
        queue_data = scan_mod._queue_load()
        entry = queue_data['entries'][0]
        assert entry['tool'] == 'codex'
        assert entry['path'] == 'project/Hermes/landing-task.md'
        assert '任务卡 = 事实源' in entry['prompt_override']
        assert 'landing/status.html' in entry['prompt_override']
        assert '<!doctype html><title>Old</title>' in entry['prompt_override']
        assert '.env' in entry['prompt_override']
        err = scan_mod._queue_apply_success_frontmatter_update(entry)
        assert err is None
        scan_mod._queue_update_entry(entry['id'], {'status': 'completed'})

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next', side_effect=fake_consume_next):
        handler.do_POST()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['run_id']
    saved = task_path.read_text(encoding='utf-8')
    today = scan_mod.datetime.now().strftime('%Y-%m-%d')
    assert f'landing_updated: {today}' in saved


def test_landing_review_missing_landing_page_returns_400(temp_repo):
    handler, resp = make_handler('/api/landing/review', temp_repo)
    payload = json.dumps({'path': 'project/Hermes/sample-task.md'}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}):
        handler.do_POST()

    assert resp.status_code == 400
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == '缺少 landing_page'


def test_landing_review_enqueues_prompt_without_success_stamp(temp_repo):
    landing_dir = temp_repo / 'landing'
    landing_dir.mkdir()
    (landing_dir / 'status.html').write_text(
        '<!doctype html><title>Sample Landing</title><h1>Sample Landing</h1>',
        encoding='utf-8'
    )
    task_path = temp_repo / 'project' / 'Hermes' / 'landing-review-task.md'
    task_path.write_text("""---
title: Landing Review Task
task_id: HER-11
workdir: .
created: 2026-06-13
updated: 2026-06-14
assignee: Alice
priority: medium
status: review
tags: []
landing_page: landing/status.html
landing_updated: 2026-06-13
---

Body for landing review.
""", encoding='utf-8')

    handler, resp = make_handler('/api/landing/review', temp_repo)
    payload = json.dumps({'path': 'project/Hermes/landing-review-task.md'}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    def fake_consume_next():
        queue_data = scan_mod._queue_load()
        entry = queue_data['entries'][0]
        assert entry['tool'] == 'codex'
        assert entry['path'] == 'project/Hermes/landing-review-task.md'
        assert 'Landing page 归属校验 Agent' in entry['prompt_override']
        assert '绿灯 / 黄灯 / 红灯' in entry['prompt_override']
        assert '只审查，不修改任何文件' in entry['prompt_override']
        assert 'Sample Landing' in entry['prompt_override']
        assert 'post_success_frontmatter' not in entry
        scan_mod._queue_update_entry(entry['id'], {'status': 'completed'})

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next', side_effect=fake_consume_next):
        handler.do_POST()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['run_id']
    saved = task_path.read_text(encoding='utf-8')
    assert 'landing_updated: 2026-06-13' in saved


def test_canvas_generate_writes_sidecar_and_stamps_frontmatter(temp_repo):
    related = temp_repo / 'project' / 'Hermes' / 'notes.md'
    related.write_text('# Notes\n', encoding='utf-8')
    task_path = temp_repo / 'project' / 'Hermes' / 'canvas-task.md'
    task_path.write_text("""---
title: Canvas Task
task_id: HER-10
workdir: project/Hermes/
created: 2026-07-02
updated: 2026-07-02
assignee: Alice
priority: medium
status: todo
tags: [canvas]
related_paths:
  - project/Hermes/notes.md
---

Body for canvas.
""", encoding='utf-8')

    handler, resp = make_handler('/api/canvas/generate', temp_repo)
    payload = json.dumps({'path': 'project/Hermes/canvas-task.md'}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_POST()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['canvas_ref'] == 'project/Hermes/.canvas/HER-10/main.canvas.json'
    sidecar = temp_repo / data['canvas_ref']
    assert sidecar.exists()
    canvas = json.loads(sidecar.read_text(encoding='utf-8'))
    assert canvas['schema'] == scan_mod.CANVAS_SCHEMA
    related_nodes = [
        node for node in canvas['nodes']
        if node['data'].get('metadata', {}).get('role') == 'related_path'
    ]
    assert related_nodes
    assert related_nodes[0]['data']['title'] == 'Notes'
    assert 'Markdown 文档' in related_nodes[0]['data']['summary']
    assert 'related_paths' in related_nodes[0]['data']['relation_note']
    assert any(edge['source'] == 'card' and edge['target'] == related_nodes[0]['id'] for edge in canvas['edges'])
    assert data['path_status_counts']['resolved'] >= 2
    saved = task_path.read_text(encoding='utf-8')
    today = scan_mod.datetime.now().strftime('%Y-%m-%d')
    assert 'canvas_ref: project/Hermes/.canvas/HER-10/main.canvas.json' in saved
    assert f'canvas_updated: {today}' in saved

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        scanned_paths = [doc['path'] for doc in scan_mod.scan_all()]
    assert 'project/Hermes/.canvas/HER-10/main.canvas.json' not in scanned_paths


def test_canvas_generate_default_recipe_uses_ref_nodes_not_atomic_facts(temp_repo):
    fact_ledger = temp_repo / 'project' / 'Hermes' / 'facts' / 'fact-ledger.jsonl'
    fact_ledger.parent.mkdir(parents=True, exist_ok=True)
    fact_ledger.write_text(
        json.dumps({'fact_id': 'fact-001', 'text': 'Atomic fact should stay AI material'}, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    task_path = temp_repo / 'project' / 'Hermes' / 'file-seed-task.md'
    task_path.write_text("""---
title: File Seed Task
task_id: HER-11
workdir: project/Hermes/
created: 2026-07-08
updated: 2026-07-08
assignee: Alice
priority: medium
status: todo
related_paths:
  - project/Hermes/facts/fact-ledger.jsonl
---

This body should not become a canvas note by default.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        data, status = scan_mod.generate_canvas_for_task('project/Hermes/file-seed-task.md')

    assert status == 200
    nodes = data['canvas']['nodes']
    assert nodes
    assert {node['type'] for node in nodes} == {'ref'}
    assert not any(str(node['id']).startswith('fact-') for node in nodes)
    assert not any(node['id'] == 'card-body-note' for node in nodes)
    assert any(
        node['data']['source_ref']['path'] == 'project/Hermes/facts/fact-ledger.jsonl'
        for node in nodes
    )


def test_canvas_generate_preserves_manual_nodes_and_edges(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        first, status = scan_mod.generate_canvas_for_task(rel_path)
    assert status == 200
    sidecar = temp_repo / first['canvas_ref']
    canvas = json.loads(sidecar.read_text(encoding='utf-8'))
    canvas['nodes'].append({
        'id': 'dialogue_keep',
        'type': 'dialogue',
        'position': {'x': 900, 'y': 120},
        'data': {'label': 'manual dialogue'},
    })
    canvas['edges'].append({
        'id': 'manual-card-dialogue',
        'source': 'card',
        'target': 'dialogue_keep',
        'label': 'manual',
    })
    sidecar.write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        second, status = scan_mod.generate_canvas_for_task(rel_path)

    assert status == 200
    saved = json.loads(sidecar.read_text(encoding='utf-8'))
    assert any(node['id'] == 'dialogue_keep' for node in saved['nodes'])
    assert any(edge['id'] == 'manual-card-dialogue' for edge in saved['edges'])
    assert second['canvas']['metadata']['generator'] == scan_mod.CANVAS_GENERATOR


def test_canvas_seed_intent_context_keeps_workdir_at_filename_layer(temp_repo):
    secret_file = temp_repo / 'project' / 'Hermes' / 'strategy.md'
    secret_file.write_text('# Strategy\nDO_NOT_READ_WORKDIR_CONTENT\n', encoding='utf-8')
    captured = {}

    def fake_llm(provider, messages, max_tokens=1024, temperature=0.7):
        captured['messages'] = messages
        return True, '把任务材料按可验收证据和执行判断组织成工作台画布'

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)], 'ai_provider': 'deepseek'}), \
         patch.object(scan_mod, '_llm_chat', side_effect=fake_llm):
        result, status = scan_mod.infer_canvas_seed_intent('project/Hermes/sample-task.md')

    assert status == 200
    assert result['ok'] is True
    prompt = captured['messages'][-1]['content']
    assert 'project/Hermes/strategy.md' in prompt
    assert 'DO_NOT_READ_WORKDIR_CONTENT' not in prompt


def test_demo_canvas_ai_endpoints_degrade_without_provider(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    config = {
        'open_allowed_roots': [str(temp_repo)],
        'demo_mode': True,
        'canvas_ai': {'enabled': False},
    }
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod, '_llm_chat') as llm_chat, \
         patch.object(scan_mod, '_queue_add_entry') as queue_add:
        seed_get = _json_api_request(
            'GET',
            f'/api/canvas/seed-intent?path={rel_path}',
            temp_repo,
        )
        seed_post = _json_api_request(
            'POST',
            '/api/canvas/seed-intent',
            temp_repo,
            {'path': rel_path},
        )
        seed_run = _json_api_request(
            'POST',
            '/api/canvas/seed-run',
            temp_repo,
            {'path': rel_path, 'intent': '补全画布', 'tool': 'codex'},
        )
        generate = _json_api_request(
            'POST',
            '/api/canvas/generate',
            temp_repo,
            {'path': rel_path},
        )
        versions = _json_api_request(
            'GET',
            f'/api/canvas/versions?map=card:{rel_path}',
            temp_repo,
        )

    for response in (seed_get, seed_post, seed_run, generate, versions):
        assert response.status_code == 200
        assert response.json['ok'] is True
        assert response.json['available'] is False
    assert 'Demo 模式未配置 AI provider' in seed_get.json['message']
    assert generate.json['exists'] is False
    assert versions.json['versions'] == []
    assert '变更' in versions.json['message']
    llm_chat.assert_not_called()
    queue_add.assert_not_called()


def test_demo_card_canvas_contract_load_save_refs_and_per_card_sidecars(tmp_path):
    source_demo = _HERE.parent / 'demo'
    shutil.copytree(source_demo, tmp_path / 'demo')
    config = {
        'paths': {'repo_root': '.', 'workspace_root': '.', 'data_root': 'demo'},
        'open_allowed_roots': [str(tmp_path), str(tmp_path / 'demo')],
        'scan_dirs': [
            'demo/projects/literature-review',
            'demo/projects/data-analysis',
        ],
        'demo_mode': True,
        'canvas_ai': {'enabled': False},
    }
    card_paths = sorted(
        str(path.relative_to(tmp_path))
        for path in (tmp_path / 'demo' / 'projects').glob('*/*.md')
    )

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', config['scan_dirs']), \
         patch.object(scan_mod, 'load_config', return_value=config):
        sidecars = []
        for card_path in card_paths:
            task_file, read_err = scan_mod._read_task_file(card_path)
            assert read_err is None
            _canvas_path, canvas_rel, ref_err, status = scan_mod._resolve_canvas_ref(
                card_path,
                task_file['frontmatter'],
            )
            assert status == 200
            assert ref_err == ''
            sidecars.append(canvas_rel)

        loaded, load_status = scan_mod.get_canvas_for_task(
            'demo/projects/literature-review/DEMO-001.md'
        )
        saved, save_status = scan_mod.put_canvas_for_task(
            'demo/projects/literature-review/DEMO-001.md',
            loaded['canvas'],
            actor='contract-test',
            base_rev=loaded['canvas_rev'],
        )

    assert len(sidecars) == len(set(sidecars)) == 8
    assert all('/.canvas/' in path and path.endswith('/main.canvas.json') for path in sidecars)
    assert load_status == 200
    assert loaded['exists'] is True
    assert loaded['canvas']['schema'] == scan_mod.CANVAS_SCHEMA
    refs = [node['data']['source_ref'] for node in loaded['canvas']['nodes'] if node['type'] == 'ref']
    assert len(refs) == 4
    assert all(isinstance(ref, dict) for ref in refs)
    assert all(ref['kind'] == 'card' and ref['status'] == 'resolved' for ref in refs)
    assert loaded['path_status_counts']['missing'] == 0
    assert save_status == 200
    assert saved['ok'] is True
    persisted = json.loads((tmp_path / saved['canvas_ref']).read_text(encoding='utf-8'))
    assert persisted['schema'] == scan_mod.CANVAS_SCHEMA
    assert persisted['metadata']['path_status_counts']['resolved'] == 4


def test_canvas_seed_skeleton_preserves_raw_intent_and_builds_execution_brief(temp_repo):
    raw_intent = '先和我商量两种做法，\n再把材料组织成可以继续判断的工作台。'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        result, status = scan_mod.canvas_seed.build_seed_skeleton(
            scan_mod._canvas_seed_deps(),
            'project/Hermes/sample-task.md',
            raw_intent,
        )

    assert status == 200
    metadata = result['canvas']['metadata']
    assert metadata['raw_intent'] == raw_intent
    assert metadata['execution_brief']['goal'] == raw_intent
    assert metadata['execution_brief']['recipe'] == 'consultation'
    assert metadata['execution_brief']['source_summary'][0] == {
        'role': 'card',
        'path': 'project/Hermes/sample-task.md',
    }
    assert metadata['execution_brief']['actions']
    assert metadata['execution_brief']['deliverable']
    assert metadata['execution_brief']['completion_gate']


def test_canvas_seed_recipe_defaults_to_general_and_supports_common_modes():
    choose = scan_mod.canvas_seed.choose_seed_recipe
    assert choose('把这些内容整理成一个能继续工作的空间') == 'general'
    assert choose('我想先和你商量下一步') == 'consultation'
    assert choose('探索这些证据之间的关系和假设') == 'research-thinking'
    assert choose('生成一份可编辑方案') == 'composition'
    assert choose('盘点风险并复核材料') == 'triage'


def test_canvas_seed_quality_gate_never_marks_failed_ai_run_usable():
    canvas = {
        'nodes': [{
            'id': 'actionable', 'type': 'note',
            'data': {'text': '这是模型实际生成、可供继续判断的行动结果。'},
        }],
        'metadata': {
            'raw_intent': '组织任务材料',
            'execution_brief': {
                'goal': '组织任务材料',
                'source_summary': [{'role': 'card', 'path': 'task.md'}],
                'actions': ['读取材料'],
                'deliverable': '工作台画布',
                'completion_gate': ['AI 运行成功'],
            },
        },
    }

    failed = scan_mod.canvas_seed.minimum_seed_quality(canvas, ai_run_succeeded=False)
    passed = scan_mod.canvas_seed.minimum_seed_quality(canvas, ai_run_succeeded=True)

    assert failed == {
        'passed': False,
        'stage': 'failed',
        'ai_run_succeeded': False,
        'missing': [],
    }
    assert passed['passed'] is True
    assert passed['stage'] == 'usable'


def test_canvas_seed_run_queues_existing_ai_run_with_contract(temp_repo):
    handler, resp = make_handler('/api/canvas/seed-run', temp_repo)
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'intent': '把任务材料按可验收证据和执行判断组织成工作台画布',
        'tool': 'codex',
    }, ensure_ascii=False).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next', return_value=None):
        handler.do_POST()
        queue = scan_mod._queue_load()

    assert resp.status_code == 200
    assert resp.json['queue'] == 'ai-run'
    entry = queue['entries'][0]
    assert entry['tool'] == 'codex'
    assert entry['metadata']['canvas_seed']['recipe'] == 'triage'
    assert entry['metadata']['canvas_seed']['prompt_version'] == scan_mod.canvas_seed.CANVAS_SEED_V2_PROMPT_VERSION
    assert 'PUT /api/canvas' in entry['prompt_override']
    assert 'actor: "codex"' in entry['prompt_override']
    assert 'data.origin 为 "manual" 或 "owner" 的节点必须原样保留' in entry['prompt_override']
    assert '目标不是整理骨架' in entry['prompt_override']
    assert '执行 brief:' in entry['prompt_override']
    assert '禁止角色扮演冒充真实会商' in entry['prompt_override']
    assert resp.json['stage'] == 'skeleton_ready'
    assert resp.json['canvas']['metadata']['seed_prompt_version'] == scan_mod.canvas_seed.CANVAS_SEED_V2_PROMPT_VERSION


def test_canvas_seed_run_deduplicates_same_active_intent(temp_repo):
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'intent': '把材料组织成可以继续执行的工作台',
        'tool': 'codex',
    }, ensure_ascii=False).encode('utf-8')

    def invoke():
        handler, resp = make_handler('/api/canvas/seed-run', temp_repo)
        handler.headers = {'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.do_POST()
        return resp

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod.canvas_seed, 'start_local_summary_backfill', return_value=None), \
         patch.object(scan_mod, '_queue_consume_next', return_value=None):
        first = invoke()
        second = invoke()
        queue = scan_mod._queue_load()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json['run_id'] == second.json['run_id']
    assert second.json['deduplicated'] is True
    assert len(queue['entries']) == 1
    assert len(queue['entries'][0]['messages']) == 1


def test_canvas_seed_public_result_requires_successful_agent_canvas_write(temp_repo):
    intent = '把材料组织成可以继续执行的工作台'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        prepared, status = scan_mod.canvas_seed.build_seed_skeleton(
            scan_mod._canvas_seed_deps(), 'project/Hermes/sample-task.md', intent,
        )
        assert status == 200
        saved, save_status = scan_mod.put_canvas_for_task(
            'project/Hermes/sample-task.md', prepared['canvas'], actor='generate',
        )
        assert save_status == 200
        entry = {
            'id': 'seed-quality',
            'path': 'project/Hermes/sample-task.md',
            'tool': 'codex',
            'status': 'completed',
            'metadata': {'canvas_seed': {
                'raw_intent': intent,
                'execution_brief': prepared['execution_brief'],
                'queued_at': '2000-01-01T00:00:00',
                'skeleton_rev': saved['canvas_rev'],
            }},
        }
        before = scan_mod._queue_public_entry(entry)
        latest, latest_status = scan_mod.get_canvas_for_task('project/Hermes/sample-task.md')
        assert latest_status == 200
        changed_canvas = latest['canvas']
        changed_canvas['nodes'].append({
            'id': 'agent-judgment', 'type': 'note', 'position': {'x': 900, 'y': 0},
            'data': {'label': '执行判断', 'text': '这是可继续执行并且能够接受验收的判断结果。', 'origin': 'generated'},
        })
        changed, changed_status = scan_mod.put_canvas_for_task(
            'project/Hermes/sample-task.md', changed_canvas, actor='codex', base_rev=latest['canvas_rev'],
        )
        assert changed_status == 200
        after = scan_mod._queue_public_entry(entry)

    assert before['usable'] is False
    assert 'agent_canvas_change' in before['quality_gate']['missing']
    assert after['usable'] is True
    assert after['quality_gate']['canvas_changed'] is True


def test_canvas_seed_v02_skeleton_uses_registry_without_llm(temp_repo):
    source_dir = temp_repo / 'project' / 'Hermes' / 'sources'
    source_dir.mkdir(parents=True, exist_ok=True)
    material = temp_repo / 'project' / 'Hermes' / 'brief.md'
    material.write_text('# Brief\nThis is registered material.\n', encoding='utf-8')
    (source_dir / 'source-registry.jsonl').write_text(
        json.dumps({'source_path': str(material), 'purpose': '已登记用途：演示材料'}, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )

    handler, resp = make_handler('/api/canvas/seed-run', temp_repo)
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'intent': '把任务材料按可验收证据和执行判断组织成工作台画布',
        'tool': 'codex',
    }, ensure_ascii=False).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_llm_chat', side_effect=AssertionError('skeleton must not call model')), \
         patch.object(scan_mod.canvas_seed, 'start_local_summary_backfill', return_value=None), \
         patch.object(scan_mod, '_queue_consume_next', return_value=None):
        handler.do_POST()

    assert resp.status_code == 200
    nodes = resp.json['canvas']['nodes']
    registry_nodes = [
        node for node in nodes
        if node['data'].get('metadata', {}).get('role') == 'source_registry'
    ]
    assert len(registry_nodes) == 1
    assert registry_nodes[0]['data']['summary'] == '已登记用途：演示材料'
    assert registry_nodes[0]['data']['metadata']['registered_usage'] is True
    assert registry_nodes[0]['data']['metadata']['local_summary_required'] is False
    assert not any(str(node['id']).startswith('fact-') for node in nodes)


def test_canvas_seed_v02_local_summary_degrades_without_key(temp_repo):
    with patch.object(scan_mod.canvas_seed, '_local_summarizer_settings', return_value=None):
        result = scan_mod.canvas_seed.run_local_summary_backfill({}, 'project/Hermes/sample-task.md')
    assert result == {'ok': True, 'skipped': True, 'reason': 'local_summarizer_unconfigured'}


def test_canvas_seed_v02_local_summary_uses_node_api_and_events(temp_repo):
    source_dir = temp_repo / 'project' / 'Hermes' / 'sources'
    source_dir.mkdir(parents=True, exist_ok=True)
    material = temp_repo / 'project' / 'Hermes' / 'unregistered.md'
    material.write_text('# Local Material\nThis file explains the local summary path.\n', encoding='utf-8')
    (source_dir / 'source-registry.jsonl').write_text(
        json.dumps({'source_path': str(material)}, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        prepared, status = scan_mod.canvas_seed.build_seed_skeleton(
            scan_mod._canvas_seed_deps(),
            'project/Hermes/sample-task.md',
            '把任务材料按可验收证据和执行判断组织成工作台画布',
        )
        assert status == 200
        saved, save_status = scan_mod.put_canvas_for_task('project/Hermes/sample-task.md', prepared['canvas'], actor='generate')
        assert save_status == 200

    fake_summary = f'用于验证本地摘要节点级回填 {material}:1'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod.canvas_seed, '_local_summarizer_settings', return_value={'url': 'http://127.0.0.1/v1/chat/completions', 'key': 'test', 'model': 'GLM-5.2'}), \
         patch.object(scan_mod.canvas_seed, '_call_local_summary_model', return_value=(True, fake_summary)):
        result = scan_mod.canvas_seed.run_local_summary_backfill(
            scan_mod._canvas_seed_deps(),
            'project/Hermes/sample-task.md',
        )
        latest, latest_status = scan_mod.get_canvas_for_task('project/Hermes/sample-task.md')

    assert result['done'] == 1
    assert latest_status == 200
    registry_node = next(
        node for node in latest['canvas']['nodes']
        if node['data'].get('metadata', {}).get('role') == 'source_registry'
    )
    assert registry_node['data']['summary'] == fake_summary
    assert registry_node['data']['metadata']['local_summary_status'] == 'done'
    events_path = temp_repo / latest['canvas_ref']
    events = [
        json.loads(line)
        for line in (events_path.parent / 'events.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert any(event.get('actor') == 'local-summarizer' and event.get('event') == 'node_summary_changed' for event in events)


def test_canvas_seed_v02_local_summary_falls_back_to_deepseek_after_xaio_empty(temp_repo):
    source_dir = temp_repo / 'project' / 'Hermes' / 'sources'
    source_dir.mkdir(parents=True, exist_ok=True)
    material = temp_repo / 'project' / 'Hermes' / 'unregistered.md'
    material.write_text('# Local Material\nThis file explains the fallback summary path.\n', encoding='utf-8')
    (source_dir / 'source-registry.jsonl').write_text(
        json.dumps({'source_path': str(material)}, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        prepared, status = scan_mod.canvas_seed.build_seed_skeleton(
            scan_mod._canvas_seed_deps(),
            'project/Hermes/sample-task.md',
            '把任务材料按可验收证据和执行判断组织成工作台画布',
        )
        assert status == 200
        saved, save_status = scan_mod.put_canvas_for_task('project/Hermes/sample-task.md', prepared['canvas'], actor='generate')
        assert save_status == 200

    calls = []
    fake_summary = f'用于验证 deepseek 后备摘要 {material}:1'

    def fake_call(settings, title, snippet, *, llm_chat=None):
        calls.append(settings.get('provider'))
        if settings.get('provider') == 'x-aio':
            return False, 'empty', 'x-aio:GLM-5.2'
        return True, fake_summary, 'deepseek'

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={
             'open_allowed_roots': [str(temp_repo)],
             'integrations': {'summarizers': {'deepseek': {'enabled': True, 'api_key': 'configured'}}},
         }), \
         patch.object(scan_mod.canvas_seed, '_local_summarizer_settings', return_value={'provider': 'x-aio', 'url': 'http://127.0.0.1/v1/chat/completions', 'key': 'test', 'model': 'GLM-5.2'}), \
         patch.object(scan_mod.canvas_seed, '_call_local_summary_model', side_effect=fake_call):
        result = scan_mod.canvas_seed.run_local_summary_backfill(
            scan_mod._canvas_seed_deps(),
            'project/Hermes/sample-task.md',
        )
        latest, latest_status = scan_mod.get_canvas_for_task('project/Hermes/sample-task.md')

    assert calls == ['x-aio', 'x-aio', 'deepseek']
    assert result['done'] == 1
    assert latest_status == 200
    registry_node = next(
        node for node in latest['canvas']['nodes']
        if node['data'].get('metadata', {}).get('role') == 'source_registry'
    )
    assert registry_node['data']['summary'] == fake_summary
    assert registry_node['data']['metadata']['local_summary_status'] == 'done'
    assert registry_node['data']['metadata']['local_summary_provider'] == 'deepseek'
    events_path = temp_repo / latest['canvas_ref']
    events = [
        json.loads(line)
        for line in (events_path.parent / 'events.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert any(
        event.get('actor') == 'local-summarizer'
        and event.get('event') == 'node_summary_changed'
        and event.get('provider') == 'deepseek'
        for event in events
    )


def test_canvas_seed_v02_local_summary_all_chain_failure_keeps_empty_summary(temp_repo):
    source_dir = temp_repo / 'project' / 'Hermes' / 'sources'
    source_dir.mkdir(parents=True, exist_ok=True)
    material = temp_repo / 'project' / 'Hermes' / 'unregistered.md'
    material.write_text('# Local Material\nThis file explains the failed summary path.\n', encoding='utf-8')
    (source_dir / 'source-registry.jsonl').write_text(
        json.dumps({'source_path': str(material)}, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        prepared, status = scan_mod.canvas_seed.build_seed_skeleton(
            scan_mod._canvas_seed_deps(),
            'project/Hermes/sample-task.md',
            '把任务材料按可验收证据和执行判断组织成工作台画布',
        )
        assert status == 200
        saved, save_status = scan_mod.put_canvas_for_task('project/Hermes/sample-task.md', prepared['canvas'], actor='generate')
        assert save_status == 200

    def fake_call(settings, title, snippet, *, llm_chat=None):
        if settings.get('provider') == 'x-aio':
            return False, 'empty', 'x-aio:GLM-5.2'
        return False, 'missing_anchor', 'deepseek'

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={
             'open_allowed_roots': [str(temp_repo)],
             'integrations': {'summarizers': {'deepseek': {'enabled': True, 'api_key': 'configured'}}},
         }), \
         patch.object(scan_mod.canvas_seed, '_local_summarizer_settings', return_value={'provider': 'x-aio', 'url': 'http://127.0.0.1/v1/chat/completions', 'key': 'test', 'model': 'GLM-5.2'}), \
         patch.object(scan_mod.canvas_seed, '_call_local_summary_model', side_effect=fake_call):
        result = scan_mod.canvas_seed.run_local_summary_backfill(
            scan_mod._canvas_seed_deps(),
            'project/Hermes/sample-task.md',
        )
        latest, latest_status = scan_mod.get_canvas_for_task('project/Hermes/sample-task.md')

    assert result['failed'] == 1
    assert result['done'] == 0
    assert result['failure_details'][0]['failures'][0]['attempts'] == 2
    assert latest_status == 200
    registry_node = next(
        node for node in latest['canvas']['nodes']
        if node['data'].get('metadata', {}).get('role') == 'source_registry'
    )
    assert registry_node['data']['summary'] == ''
    assert registry_node['data']['metadata']['local_summary_status'] == 'failed'
    assert registry_node['data']['metadata']['local_summary_provider'] == 'x-aio:GLM-5.2>deepseek'


def test_canvas_generate_routes_seeded_canvas_to_seed_queue(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    canvas = _minimal_canvas(rel_path)
    canvas['metadata'] = {
        'seed_intent': '把任务材料按可验收证据和执行判断组织成工作台画布',
        'seed_recipe': 'triage',
    }
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        saved, save_status = scan_mod.put_canvas_for_task(rel_path, canvas, actor='codex')
    assert save_status == 200

    handler, resp = make_handler('/api/canvas/generate', temp_repo)
    payload = json.dumps({'path': rel_path}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod.canvas_seed, 'start_local_summary_backfill', return_value=None), \
         patch.object(scan_mod, '_queue_consume_next', return_value=None):
        handler.do_POST()
        queue = scan_mod._queue_load()

    assert saved['canvas_rev']
    assert resp.status_code == 200
    assert resp.json['routed_from'] == '/api/canvas/generate'
    assert resp.json['run_id'] == queue['entries'][0]['id']
    assert queue['entries'][0]['metadata']['canvas_seed']['intent'] == canvas['metadata']['seed_intent']


def test_canvas_seed_manual_lineage_check_detects_loss():
    before = {
        'nodes': [
            {'id': 'manual-note', 'type': 'note', 'position': {'x': 1, 'y': 2}, 'data': {'origin': 'manual', 'text': 'keep'}},
            {'id': 'owner-ref', 'type': 'ref', 'position': {'x': 3, 'y': 4}, 'data': {'origin': 'owner', 'label': 'judgment'}},
        ],
        'edges': [
            {'id': 'manual-edge', 'source': 'manual-note', 'target': 'owner-ref', 'data': {'origin': 'manual'}},
        ],
    }
    after_ok = _clone_json(before)
    after_bad = {'nodes': [before['nodes'][0]], 'edges': []}

    ok_report = scan_mod.canvas_seed.check_manual_lineage_preserved(before, after_ok)
    bad_report = scan_mod.canvas_seed.check_manual_lineage_preserved(before, after_bad)

    assert ok_report['ok'] is True
    assert bad_report['ok'] is False
    assert bad_report['missing_nodes'] == ['owner-ref']
    assert bad_report['missing_edges'] == ['manual-edge']


def test_canvas_generate_preserves_existing_node_positions(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        first, status = scan_mod.generate_canvas_for_task(rel_path)
    assert status == 200
    sidecar = temp_repo / first['canvas_ref']
    canvas = json.loads(sidecar.read_text(encoding='utf-8'))
    canvas['nodes'][0]['position'] = {'x': 1234, 'y': 567}
    sidecar.write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        _second, status = scan_mod.generate_canvas_for_task(rel_path)

    assert status == 200
    saved = json.loads(sidecar.read_text(encoding='utf-8'))
    assert saved['nodes'][0]['position'] == {'x': 1234, 'y': 567}


def test_canvas_get_reports_missing_then_existing_canvas(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    handler, resp = make_handler('/api/canvas?path=project/Hermes/sample-task.md', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()
    assert resp.status_code == 200
    first = resp.json
    assert first['ok'] is True
    assert first['exists'] is False
    assert first['canvas_ref'] == 'project/Hermes/.canvas/HER-1/main.canvas.json'

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        generated, status = scan_mod.generate_canvas_for_task(rel_path)
    assert status == 200

    handler, resp = make_handler('/api/canvas?path=project/Hermes/sample-task.md', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()
    assert resp.status_code == 200
    second = resp.json
    assert second['ok'] is True
    assert second['exists'] is True
    assert second['canvas']['schema'] == scan_mod.CANVAS_SCHEMA
    assert second['canvas_ref'] == generated['canvas_ref']
    assert second['canvas_rev'] == generated['canvas_rev']


def test_canvas_put_rejects_stale_base_rev_without_overwriting(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    first = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': _minimal_canvas(rel_path),
        'actor': 'owner',
    })
    assert first.status_code == 200
    base_rev = first.json['canvas_rev']

    b_canvas = _clone_json(first.json['canvas'])
    b_canvas['nodes'].append(_note_node('note-b', 'B saved first'))
    second = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': b_canvas,
        'actor': 'codex',
        'base_rev': base_rev,
    })
    assert second.status_code == 200
    sidecar = temp_repo / second.json['canvas_ref']
    before_reject = sidecar.read_text(encoding='utf-8')

    stale_canvas = _clone_json(first.json['canvas'])
    stale_canvas['nodes'].append(_note_node('note-a', 'A stale save'))
    rejected = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': stale_canvas,
        'actor': 'owner',
        'base_rev': base_rev,
    })

    assert rejected.status_code == 409
    assert rejected.json['conflict'] is True
    assert rejected.json['canvas_rev'] == second.json['canvas_rev']
    assert sidecar.read_text(encoding='utf-8') == before_reject
    saved = json.loads(before_reject)
    saved_ids = {node['id'] for node in saved['nodes']}
    assert 'note-b' in saved_ids
    assert 'note-a' not in saved_ids
    events = _canvas_events(temp_repo, second.json['canvas_ref'])
    assert any(
        event.get('event') == 'canvas_save_rejected'
        and event.get('actor') == 'owner'
        and event.get('reason') == 'base_rev_mismatch'
        for event in events
    )


def test_canvas_put_without_base_rev_remains_compatible_and_marks_event(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    resp = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': _minimal_canvas(rel_path),
        'actor': 'codex',
    })

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    assert resp.json['canvas_rev']
    events = _canvas_events(temp_repo, resp.json['canvas_ref'])
    assert any(
        event.get('event') == 'canvas_saved'
        and event.get('actor') == 'codex'
        and event.get('no_base') is True
        for event in events
    )


def test_canvas_events_get_skips_and_reports_malformed_middle_line(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    saved = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': _minimal_canvas(rel_path),
        'actor': 'codex',
    })
    assert saved.status_code == 200
    events_path = temp_repo / Path(saved.json['canvas_ref']).parent / 'events.jsonl'
    valid_lines = events_path.read_text(encoding='utf-8').splitlines()
    assert len(valid_lines) >= 2
    events_path.write_text(
        '\n'.join([valid_lines[0], '{broken-middle', *valid_lines[1:]]) + '\n',
        encoding='utf-8',
    )

    handler, resp = make_handler(f'/api/canvas/events?path={rel_path}', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['count'] == len(valid_lines)
    assert resp.json['malformed_lines'] == 1
    assert len(resp.json['events']) == len(valid_lines)


def test_canvas_events_get_skips_and_reports_malformed_tail_line(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    saved = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': _minimal_canvas(rel_path),
        'actor': 'codex',
    })
    assert saved.status_code == 200
    events_path = temp_repo / Path(saved.json['canvas_ref']).parent / 'events.jsonl'
    valid_lines = events_path.read_text(encoding='utf-8').splitlines()
    with open(events_path, 'a', encoding='utf-8') as fh:
        fh.write('{half-written-tail')

    handler, resp = make_handler(f'/api/canvas/events?path={rel_path}', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['count'] == len(valid_lines)
    assert resp.json['malformed_lines'] == 1
    assert len(resp.json['events']) == len(valid_lines)


def test_canvas_put_reports_partial_save_when_event_append_fails(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    canvas = _minimal_canvas(rel_path)
    with patch.object(scan_mod, '_canvas_events_append', return_value=False):
        failed = _put_canvas_api(temp_repo, {
            'path': rel_path,
            'canvas': canvas,
            'actor': 'codex',
        })

    assert failed.status_code == 500
    assert failed.json['ok'] is False
    assert failed.json['error'] == 'canvas_event_append_failed'
    assert failed.json['message'] == '画布已保存但事件未入账，请重新 GET 对账'
    assert failed.json['partial_save'] is True
    assert failed.json['canvas_saved'] is True
    assert failed.json['events_recorded'] is False

    sidecar = temp_repo / failed.json['canvas_ref']
    assert sidecar.exists()
    persisted = json.loads(sidecar.read_text(encoding='utf-8'))
    assert persisted['nodes'][0]['id'] == 'card'
    assert failed.json['canvas_rev'] == scan_mod._canvas_rev(persisted)

    handler, resp = make_handler(f'/api/canvas?path={rel_path}', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()
    assert resp.status_code == 200
    assert resp.json['exists'] is True
    assert resp.json['canvas_rev'] == failed.json['canvas_rev']


def test_ledger_query_merges_canvas_lineage_and_comments(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    first = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': _minimal_canvas(rel_path),
        'actor': 'codex',
    })
    assert first.status_code == 200
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        assert scan_mod._lineage_record_event(rel_path, 'frontmatter_changed', actor='kanban', field='status', old_value='todo', new_value='review')
        assert scan_mod._ledger_append_events(rel_path, [{
            'schema': scan_mod.COMMENTS_LEDGER_SCHEMA,
            'event': 'ai_comment_added',
            'entry_id': 'run-1#0',
            'ts': '2026-07-08T10:00:00',
            'actor': 'Owner',
            'role': 'user',
        }]) is True
        handler, resp = make_handler('/api/ledger/HER-1', temp_repo)
        handler.headers = {'Host': 'localhost'}
        handler.do_GET()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['task_id'] == 'HER-1'
    assert data['source_counts']['canvas'] > 0
    assert data['source_counts']['lineage'] > 0
    assert data['source_counts']['comments'] == 1
    kinds = {entry['kind'] for entry in data['entries']}
    assert {'canvas', 'lineage', 'comment'} <= kinds
    assert any(entry['source']['path'].endswith('.canvas/HER-1/events.jsonl') for entry in data['entries'])


def test_ledger_query_accepts_demo_card_id_and_repo_relative_path(temp_repo):
    demo_dir = temp_repo / 'demo' / 'projects' / 'literature-review'
    demo_dir.mkdir(parents=True)
    demo_path = 'demo/projects/literature-review/DEMO-001.md'
    (temp_repo / demo_path).write_text(
        """---
title: Demo card
task_id: DEMO-001
workdir: demo/projects/literature-review/
status: done
---

Demo body.
""",
        encoding='utf-8',
    )
    config = {
        'paths': {'repo_root': '.', 'workspace_root': '.', 'data_root': 'demo'},
        'open_allowed_roots': [str(temp_repo), str(temp_repo / 'demo')],
        'scan_dirs': ['demo/projects/literature-review'],
    }

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'SCAN_DIRS', config['scan_dirs']), \
         patch.object(scan_mod, 'load_config', return_value=config):
        id_handler, id_response = make_handler('/api/ledger/DEMO-001', temp_repo)
        id_handler.headers = {'Host': 'localhost'}
        id_handler.do_GET()

        path_handler, path_response = make_handler(
            '/api/ledger/demo%2Fprojects%2Fliterature-review%2FDEMO-001.md',
            temp_repo,
        )
        path_handler.headers = {'Host': 'localhost'}
        path_handler.do_GET()

        traversal_handler, traversal_response = make_handler(
            '/api/ledger/..%2Foutside.md',
            temp_repo,
        )
        traversal_handler.headers = {'Host': 'localhost'}
        traversal_handler.do_GET()

    assert id_response.status_code == 200
    assert path_response.status_code == 200
    assert path_response.json == id_response.json
    assert path_response.json['task_id'] == 'DEMO-001'
    assert path_response.json['path'] == demo_path
    assert traversal_response.status_code == 400
    assert traversal_response.json['error'] == '非法任务卡路径'


def test_canvas_node_history_filters_node_events(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    canvas = _minimal_canvas(rel_path)
    canvas['nodes'].append(_note_node('note-a', 'A note'))
    first = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': canvas,
        'actor': 'codex',
    })
    assert first.status_code == 200
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler, resp = make_handler('/api/canvas/node-history?task_id=HER-1&node_id=note-a', temp_repo)
        handler.headers = {'Host': 'localhost'}
        handler.do_GET()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['node_id'] == 'note-a'
    assert data['count'] >= 1
    assert all(entry['raw'].get('node_id') == 'note-a' for entry in data['entries'])


def test_canvas_node_put_merges_stale_different_node_and_rejects_same_node(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    canvas = _minimal_canvas(rel_path)
    canvas['nodes'].append(_note_node('note-a', 'A note'))
    canvas['nodes'].append(_note_node('note-b', 'B note'))
    first = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': canvas,
        'actor': 'owner',
    })
    assert first.status_code == 200
    base_rev = first.json['canvas_rev']
    base_by_id = {node['id']: node for node in first.json['canvas']['nodes']}

    node_a = _clone_json(base_by_id['note-a'])
    node_a['position'] = {'x': 200, 'y': 200}
    saved_a = _put_canvas_node_api(temp_repo, {
        'path': rel_path,
        'node_id': 'note-a',
        'node': node_a,
        'base_node': base_by_id['note-a'],
        'base_rev': base_rev,
        'actor': 'codex',
    })
    assert saved_a.status_code == 200

    node_b = _clone_json(base_by_id['note-b'])
    node_b['position'] = {'x': 300, 'y': 300}
    saved_b = _put_canvas_node_api(temp_repo, {
        'path': rel_path,
        'node_id': 'note-b',
        'node': node_b,
        'base_node': base_by_id['note-b'],
        'base_rev': base_rev,
        'actor': 'claude',
    })
    assert saved_b.status_code == 200
    assert saved_b.json['merged_from_stale_base'] is True
    saved_by_id = {node['id']: node for node in saved_b.json['canvas']['nodes']}
    assert saved_by_id['note-a']['position'] == {'x': 200, 'y': 200}
    assert saved_by_id['note-b']['position'] == {'x': 300, 'y': 300}

    stale_node_a = _clone_json(base_by_id['note-a'])
    stale_node_a['position'] = {'x': 500, 'y': 500}
    rejected = _put_canvas_node_api(temp_repo, {
        'path': rel_path,
        'node_id': 'note-a',
        'node': stale_node_a,
        'base_node': base_by_id['note-a'],
        'base_rev': base_rev,
        'actor': 'owner',
    })
    assert rejected.status_code == 409
    assert rejected.json['node_conflict'] is True
    events = _canvas_events(temp_repo, saved_b.json['canvas_ref'])
    assert any(event.get('event') == 'node_moved' and event.get('node_id') == 'note-a' and event.get('actor') == 'codex' for event in events)
    assert any(event.get('event') == 'node_moved' and event.get('node_id') == 'note-b' and event.get('actor') == 'claude' for event in events)


def test_canvas_node_put_records_hidden_and_shown_events(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    canvas = _minimal_canvas(rel_path)
    canvas['nodes'].append(_note_node('note-a', 'A note'))
    first = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': canvas,
        'actor': 'owner',
    })
    assert first.status_code == 200
    base_rev = first.json['canvas_rev']
    base_by_id = {node['id']: node for node in first.json['canvas']['nodes']}

    hidden_node = _clone_json(base_by_id['note-a'])
    hidden_node['hidden'] = True
    hidden_node['data']['hidden'] = True
    hidden = _put_canvas_node_api(temp_repo, {
        'path': rel_path,
        'node_id': 'note-a',
        'node': hidden_node,
        'base_node': base_by_id['note-a'],
        'base_rev': base_rev,
        'actor': 'codex',
    })
    assert hidden.status_code == 200
    hidden_rev = hidden.json['canvas_rev']
    hidden_by_id = {node['id']: node for node in hidden.json['canvas']['nodes']}

    shown_node = _clone_json(hidden_by_id['note-a'])
    shown_node['hidden'] = False
    shown_node['data']['hidden'] = False
    shown = _put_canvas_node_api(temp_repo, {
        'path': rel_path,
        'node_id': 'note-a',
        'node': shown_node,
        'base_node': hidden_by_id['note-a'],
        'base_rev': hidden_rev,
        'actor': 'codex',
    })
    assert shown.status_code == 200

    events = _canvas_events(temp_repo, shown.json['canvas_ref'])
    assert any(event.get('event') == 'node_hidden' and event.get('node_id') == 'note-a' and event.get('actor') == 'codex' for event in events)
    assert any(event.get('event') == 'node_shown' and event.get('node_id') == 'note-a' and event.get('actor') == 'codex' for event in events)


def test_canvas_text_copy_lint_reports_long_unreferenced_text(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    copied_text = '# Sample Task\n\nThis is the markdown body of the task.\n\n## Subsection\n\n- Item 1\n- Item 2'
    canvas = _minimal_canvas(rel_path)
    canvas['nodes'].append({
        'id': 'copied-note',
        'type': 'note',
        'position': {'x': 200, 'y': 200},
        'data': {'content': copied_text},
    })
    canvas['nodes'].append({
        'id': 'referenced-note',
        'type': 'note',
        'position': {'x': 300, 'y': 300},
        'data': {
            'content': copied_text,
            'source_ref': {'kind': 'card', 'path': rel_path},
        },
    })
    saved = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': canvas,
        'actor': 'codex',
    })
    assert saved.status_code == 200

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        data, status = scan_mod.ledger_query.lint_text_copies_for_task(
            scan_mod._ledger_query_deps(),
            'HER-1',
        )

    assert status == 200
    assert data['count'] == 1
    assert data['findings'][0]['node_id'] == 'copied-note'
    assert data['findings'][0]['reason'] == 'copies_task_card_text'


def test_canvas_put_after_conflict_can_reload_rev_and_save(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    first = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': _minimal_canvas(rel_path),
        'actor': 'owner',
    })
    assert first.status_code == 200
    base_rev = first.json['canvas_rev']

    server_canvas = _clone_json(first.json['canvas'])
    server_canvas['nodes'].append(_note_node('note-server', 'server update'))
    server_write = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': server_canvas,
        'actor': 'codex',
        'base_rev': base_rev,
    })
    assert server_write.status_code == 200

    stale_canvas = _clone_json(first.json['canvas'])
    stale_canvas['nodes'].append(_note_node('note-stale', 'stale update'))
    rejected = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': stale_canvas,
        'actor': 'owner',
        'base_rev': base_rev,
    })
    assert rejected.status_code == 409

    latest_canvas = _clone_json(rejected.json['canvas'])
    latest_canvas['nodes'].append(_note_node('note-retry', 'retry after reload'))
    retry = _put_canvas_api(temp_repo, {
        'path': rel_path,
        'canvas': latest_canvas,
        'actor': 'owner',
        'base_rev': rejected.json['canvas_rev'],
    })

    assert retry.status_code == 200
    saved = json.loads((temp_repo / retry.json['canvas_ref']).read_text(encoding='utf-8'))
    saved_ids = {node['id'] for node in saved['nodes']}
    assert {'note-server', 'note-retry'} <= saved_ids
    assert 'note-stale' not in saved_ids


def test_canvas_put_saves_valid_payload_and_rejects_user_id(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    canvas = {
        'schema': scan_mod.CANVAS_SCHEMA,
        'id': 'HER-1',
        'name': 'Manual canvas',
        'nodes': [
            {
                'id': 'card',
                'type': 'ref',
                'position': {'x': 0, 'y': 0},
                'data': {
                    'label': 'card',
                    'source_ref': {'kind': 'card', 'path': rel_path},
                },
            },
        ],
        'edges': [],
        'viewport': {'x': 0, 'y': 0, 'zoom': 1},
    }
    handler, resp = make_handler('/api/canvas', temp_repo)
    payload = json.dumps({'path': rel_path, 'canvas': canvas}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_PUT()
    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    saved = json.loads((temp_repo / data['canvas_ref']).read_text(encoding='utf-8'))
    assert saved['nodes'][0]['data']['source_ref']['status'] == 'resolved'

    bad = dict(canvas)
    bad['userId'] = 'someone'
    handler, resp = make_handler('/api/canvas', temp_repo)
    payload = json.dumps({'path': rel_path, 'canvas': bad}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_PUT()
    assert resp.status_code == 400
    assert resp.json['error'] == 'canvas 不允许包含 userId'


def test_canvas_put_preserves_manual_note_ref_and_layout_metadata(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    notes_path = temp_repo / 'project' / 'Hermes' / 'notes.md'
    notes_path.write_text('# Notes\n', encoding='utf-8')
    canvas = {
        'schema': scan_mod.CANVAS_SCHEMA,
        'id': 'HER-1',
        'name': 'Editable canvas',
        'nodes': [
            {
                'id': 'card',
                'type': 'ref',
                'position': {'x': 640, 'y': 320},
                'data': {
                    'label': 'card',
                    'source_ref': {'kind': 'card', 'path': rel_path},
                },
            },
            {
                'id': 'note-manual',
                'type': 'note',
                'position': {'x': 900, 'y': 460},
                'data': {
                    'label': '手动批注',
                    'text': '只保存布局和批注，不成为事实源。',
                    'canvas_native': True,
                    'editable': True,
                },
            },
            {
                'id': 'ref-manual',
                'type': 'ref',
                'position': {'x': 1180, 'y': 460},
                'data': {
                    'label': '来源分支',
                    'source_ref': {'kind': 'file', 'path': 'project/Hermes/notes.md'},
                },
            },
        ],
        'edges': [{'id': 'edge-card-ref', 'source': 'card', 'target': 'ref-manual'}],
        'viewport': {'x': 0, 'y': 0, 'zoom': 1},
    }

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        data, status = scan_mod.put_canvas_for_task(rel_path, canvas)

    assert status == 200
    assert data['ok'] is True
    saved = json.loads((temp_repo / data['canvas_ref']).read_text(encoding='utf-8'))
    by_id = {node['id']: node for node in saved['nodes']}
    assert by_id['card']['position'] == {'x': 640, 'y': 320}
    assert by_id['note-manual']['data']['canvas_native'] is True
    assert by_id['note-manual']['data']['text'] == '只保存布局和批注，不成为事实源。'
    assert by_id['ref-manual']['data']['source_ref']['status'] == 'resolved'
    assert by_id['ref-manual']['data']['source_ref']['resolved_path'] == str(notes_path)
    assert saved['metadata']['path_status_counts']['resolved'] == 2
    assert saved['timestamps']['updatedAt']


def test_canvas_source_ref_known_path_rewrite_marks_corrected(temp_repo):
    new_root = temp_repo / 'MixedTeamSpace' / 'example-org' / 'upstream-canvas'
    new_root.mkdir(parents=True)
    task_abs = temp_repo / 'project' / 'Hermes' / 'sample-task.md'
    old = '/Users/example/workspace/_projects/Example'
    new = str(new_root)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={
             'open_allowed_roots': [str(temp_repo)],
             'canvas_path_rewrites': [[old, new]],
         }):
        result = scan_mod.resolve_canvas_source_ref(old, task_abs, {'workdir': 'project/Hermes/'}, kind='dir')

    assert result['status'] == 'corrected'
    assert result['resolved_path'] == str(new_root)


def _project_map_task(temp_repo, filename, *, title, task_id, family='kanban', stage='', status='todo'):
    stage_line = f"stage: {stage}\n" if stage else ''
    body = f"""---
title: {title}
task_id: {task_id}
task_family: {family}
workdir: project/Hermes/
created: 2026-07-04
updated: 2026-07-04
assignee: Alice
priority: medium
status: {status}
{stage_line}tags: [canvas]
---

## 要做什么
{title}
"""
    path = temp_repo / 'project' / 'Hermes' / filename
    path.write_text(body, encoding='utf-8')
    return path


def test_project_map_generate_groups_task_family_by_stage_and_preserves_manual_layer(temp_repo):
    _project_map_task(temp_repo, 'kanban-plan.md', title='Plan map', task_id='KAN-201', stage='plan')
    _project_map_task(temp_repo, 'kanban-build.md', title='Build map', task_id='KAN-202', stage='build', status='in-progress')
    _project_map_task(temp_repo, 'kanban-done.md', title='Done map', task_id='KAN-203', stage='build', status='done')
    _project_map_task(temp_repo, 'other-family.md', title='Other family', task_id='KMO-201', family='knowledge', stage='plan')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        first, status = scan_mod.generate_project_map_canvas('kanban')

    assert status == 200
    assert first['canvas_ref'] == 'project/Hermes/.canvas/_project_maps/task_family/kanban/main.canvas.json'
    canvas = first['canvas']
    assert canvas['scope']['type'] == 'task_family'
    assert canvas['metadata']['active_count'] == 2
    by_id = {node['id']: node for node in canvas['nodes']}
    assert 'card-KAN-201' in by_id
    assert 'card-KAN-202' in by_id
    assert 'card-KAN-203' not in by_id
    assert 'card-KMO-201' not in by_id
    assert by_id['card-KAN-201']['position']['x'] != by_id['card-KAN-202']['position']['x']
    assert by_id['card-KAN-202']['data']['status_badge']['label'] == 'in progress'
    assert 'Plan map' in by_id['card-KAN-201']['data']['summary']
    assert 'task_family=kanban' in by_id['card-KAN-201']['data']['relation_note']

    editable = _clone_json(canvas)
    editable['nodes'][0]['position'] = {'x': 999, 'y': 111}
    editable['nodes'].append(_note_node('manual-note', 'Owner note'))
    editable['edges'].append({'id': 'manual-link', 'source': 'card-KAN-201', 'target': 'manual-note'})
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        saved, save_status = scan_mod.put_project_map_canvas(
            'kanban',
            editable,
            actor='owner',
            base_rev=first['canvas_rev'],
        )
        assert save_status == 200
        ok, _msg = scan_mod.update_frontmatter_field(
            'project/Hermes/kanban-plan.md',
            'status',
            'done',
            _suppress_decision_log=True,
        )[:2]
        assert ok
        second, regen_status = scan_mod.generate_project_map_canvas(
            'kanban',
            base_rev=saved['canvas_rev'],
        )

    assert regen_status == 200
    saved_canvas = second['canvas']
    saved_by_id = {node['id']: node for node in saved_canvas['nodes']}
    assert 'card-KAN-201' not in saved_by_id
    assert 'card-KAN-202' in saved_by_id
    assert 'manual-note' in saved_by_id
    assert any(edge['id'] == 'manual-link' for edge in saved_canvas['edges'])


def test_project_map_canvas_endpoints_write_events_and_reject_stale_rev(temp_repo):
    _project_map_task(temp_repo, 'kanban-plan.md', title='Plan map', task_id='KAN-201', stage='plan')

    resp = _post_canvas_refresh_api(temp_repo, {'map': 'kanban'})
    assert resp.status_code == 200
    generated = resp.json
    assert generated['ok'] is True
    assert generated['refreshed'] is True
    assert generated['canvas_ref'] == 'project/Hermes/.canvas/_project_maps/task_family/kanban/main.canvas.json'
    base_rev = generated['canvas_rev']

    server_canvas = _clone_json(generated['canvas'])
    server_canvas['nodes'].append(_note_node('server-note', 'server update'))
    server_write = _put_canvas_api(temp_repo, {
        'map': 'kanban',
        'canvas': server_canvas,
        'actor': 'codex',
        'base_rev': base_rev,
    })
    assert server_write.status_code == 200

    stale_canvas = _clone_json(generated['canvas'])
    stale_canvas['nodes'].append(_note_node('stale-note', 'stale update'))
    rejected = _put_canvas_api(temp_repo, {
        'map': 'kanban',
        'canvas': stale_canvas,
        'actor': 'owner',
        'base_rev': base_rev,
    })

    assert rejected.status_code == 409
    assert rejected.json['conflict'] is True
    saved = json.loads((temp_repo / generated['canvas_ref']).read_text(encoding='utf-8'))
    saved_ids = {node['id'] for node in saved['nodes']}
    assert 'server-note' in saved_ids
    assert 'stale-note' not in saved_ids
    events = _canvas_events(temp_repo, generated['canvas_ref'])
    assert any(event.get('event') == 'node_added' and event.get('actor') == 'codex' for event in events)
    assert any(
        event.get('event') == 'canvas_save_rejected'
        and event.get('actor') == 'owner'
        and event.get('reason') == 'base_rev_mismatch'
        for event in events
    )


def test_project_map_get_is_read_only_when_missing_and_after_source_changes(temp_repo):
    _project_map_task(temp_repo, 'kanban-plan.md', title='Plan map', task_id='KAN-201', stage='plan')

    handler, resp = make_handler('/api/canvas?map=kanban', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()
    assert resp.status_code == 200
    missing = resp.json
    assert missing['ok'] is True
    assert missing['exists'] is False
    canvas_ref = missing['canvas_ref']
    canvas_path = temp_repo / canvas_ref
    assert not canvas_path.exists()
    assert _canvas_events(temp_repo, canvas_ref) == []

    refreshed = _post_canvas_refresh_api(temp_repo, {'map': 'kanban'})
    assert refreshed.status_code == 200
    first = refreshed.json
    canvas_path = temp_repo / canvas_ref
    first_mtime = canvas_path.stat().st_mtime_ns
    first_events = _canvas_events(temp_repo, canvas_ref)
    assert len(first_events) == 1
    assert first_events[0]['event'] == 'project_map_refreshed'
    assert first_events[0]['actor'] == 'generate'

    handler, resp = make_handler('/api/canvas?map=kanban', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()
    assert resp.status_code == 200
    second = resp.json
    assert second['exists'] is True
    assert second['canvas_rev'] == first['canvas_rev']
    assert canvas_path.stat().st_mtime_ns == first_mtime
    assert len(_canvas_events(temp_repo, canvas_ref)) == len(first_events)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        ok, _msg = scan_mod.update_frontmatter_field(
            'project/Hermes/kanban-plan.md',
            'status',
            'review',
            _suppress_decision_log=True,
        )[:2]
    assert ok

    handler, resp = make_handler('/api/canvas?map=kanban', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()
    assert resp.status_code == 200
    third = resp.json
    assert third['exists'] is True
    assert third['canvas_rev'] == first['canvas_rev']
    assert canvas_path.stat().st_mtime_ns == first_mtime
    assert len(_canvas_events(temp_repo, canvas_ref)) == len(first_events)

    refreshed = _post_canvas_refresh_api(temp_repo, {
        'map': 'kanban',
        'base_rev': third['canvas_rev'],
    })
    assert refreshed.status_code == 200
    third = refreshed.json
    assert third['refreshed'] is True
    assert third['canvas_rev'] != first['canvas_rev']
    by_id = {node['id']: node for node in third['canvas']['nodes']}
    assert by_id['card-KAN-201']['data']['status_badge']['label'] == 'review'
    events = _canvas_events(temp_repo, canvas_ref)
    assert len(events) == len(first_events) + 1
    assert events[-1]['event'] == 'project_map_refreshed'
    assert events[-1]['actor'] == 'generate'


def test_do_get_canvas_branches_do_not_call_canvas_writers():
    source = inspect.getsource(scan_mod.Handler.do_GET)
    for forbidden in ('generate_', '_save_project_map', 'put_project_map'):
        assert forbidden not in source


def test_project_maps_list_reports_task_family_active_counts(temp_repo):
    _project_map_task(temp_repo, 'kanban-plan.md', title='Plan map', task_id='KAN-201', family='kanban')
    _project_map_task(temp_repo, 'kanban-done.md', title='Done map', task_id='KAN-202', family='kanban', status='done')
    _project_map_task(temp_repo, 'knowledge-plan.md', title='Knowledge map', task_id='KMO-201', family='knowledge')

    handler, resp = make_handler('/api/project-maps', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    by_scope = {item['scope']: item for item in data['maps']}
    assert by_scope['kanban']['active_count'] == 1
    assert by_scope['knowledge']['active_count'] == 1
    assert by_scope['kanban']['canvas_ref'] == 'project/Hermes/.canvas/_project_maps/task_family/kanban/main.canvas.json'


def test_project_map_normalizes_known_task_family_aliases_and_filters_unknown(temp_repo):
    _project_map_task(temp_repo, 'skill-plan.md', title='Skill map', task_id='SKL-301', family='SKL')
    _project_map_task(temp_repo, 'bad-family.md', title='Bad family', task_id='BAD-1', family='bad-family')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        generated, gen_status = scan_mod.generate_project_map_canvas('SKL')
        unknown, unknown_status = scan_mod.generate_project_map_canvas('bad-family')

    assert gen_status == 200
    assert generated['scope']['value'] == 'skill'
    assert generated['canvas_ref'] == 'project/Hermes/.canvas/_project_maps/task_family/skill/main.canvas.json'
    by_id = {node['id']: node for node in generated['canvas']['nodes']}
    assert 'card-SKL-301' in by_id
    assert 'card-BAD-1' not in by_id
    assert unknown_status == 400
    assert 'unknown task_family' in unknown['error']

    handler, resp = make_handler('/api/project-maps', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()

    assert resp.status_code == 200
    scopes = {item['scope']: item for item in resp.json['maps']}
    assert scopes['skill']['active_count'] == 1
    assert 'SKL' not in scopes
    assert 'skl' not in scopes
    assert 'bad-family' not in scopes


def test_comments_ledger_paths_and_task_id_rules():
    assert scan_mod._task_id_from_rel_path('project/个人调度/KAN-111_看板评论.md') == 'KAN-111'
    assert scan_mod._task_id_from_rel_path('project/Hermes/plain-note.md') == 'plain-note'

    assert scan_mod._ledger_rel_for_task('project/个人调度/KAN-111_看板评论.md') == (
        'project/个人调度/.comments/KAN-111/ledger.jsonl'
    )
    assert scan_mod._ledger_rel_for_task('project/Hermes/plain note.md') == (
        'project/Hermes/.comments/plain-note/ledger.jsonl'
    )
    assert scan_mod._ledger_rel_for_task('notes.md') is None
    assert scan_mod._ledger_rel_for_task('project/Hermes/not-task.txt') is None
    assert scan_mod._ledger_rel_for_task('/tmp/project/Hermes/KAN-1.md') is None


def test_comments_ledger_append_read_roundtrip_skips_bad_lines(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    events = [
        {'event': 'message', 'entry_id': 'r1#0', 'role': 'user'},
        {'event': 'message', 'entry_id': 'r1#1', 'role': 'ai'},
    ]

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        assert scan_mod._ledger_append_events(rel_path, events) is True
        ledger_path = temp_repo / scan_mod._ledger_rel_for_task(rel_path)
        with open(ledger_path, 'a', encoding='utf-8') as fh:
            fh.write('not-json\n')
            fh.write(json.dumps({'event': 'message', 'entry_id': 'r2#0'}, ensure_ascii=False) + '\n')
        read_events, err = scan_mod._ledger_read_events(rel_path)

    assert err == ''
    assert [event['entry_id'] for event in read_events] == ['r1#0', 'r1#1', 'r2#0']


def test_comments_ledger_content_fields_user_full_ai_digest():
    cfg = {'comments_ledger': {'enabled': True, 'ai_content': 'digest', 'digest_chars': 200}}
    user_text = 'u' * 260
    ai_text = 'a' * 260

    user_fields = scan_mod._ledger_content_fields('user', user_text, cfg)
    ai_fields = scan_mod._ledger_content_fields('ai', ai_text, cfg)

    assert user_fields['content'] == user_text
    assert user_fields['content_len'] == 260
    assert user_fields['content_truncated'] is False
    assert user_fields['content_sha256'] == hashlib.sha256(user_text.encode('utf-8')).hexdigest()[:16]

    assert ai_fields['content'] == ai_text[:200]
    assert ai_fields['content_len'] == 260
    assert ai_fields['content_truncated'] is True
    assert ai_fields['content_sha256'] == hashlib.sha256(ai_text.encode('utf-8')).hexdigest()[:16]


def test_build_fork_replay_truncates_and_drops_oldest():
    parent = {
        'messages': [
            {'role': 'user', 'content': 'first'},
            {'role': 'ai', 'content': 'second'},
            {'role': 'user', 'content': 'third'},
        ],
    }
    truncated = scan_mod._build_fork_replay(
        {'messages': [{'role': 'ai', 'content': 'x' * 40}]},
        0,
        per_msg_cap=10,
        total_cap=1000,
    )
    assert '[0] AI: ' + ('x' * 10) in truncated
    assert '此条截断,原长 40 字符' in truncated

    replay = scan_mod._build_fork_replay(parent, 2, per_msg_cap=100, total_cap=34)
    assert '最早 1 条已因长度省略' in replay
    assert '[0] 用户: first' not in replay
    assert '[1] AI: second' in replay
    assert '[2] 用户: third' in replay


def test_handle_ai_fork_validation_and_success_without_cli():
    parent = {
        'id': 'parent1',
        'tool': 'codex',
        'path': 'project/Hermes/sample-task.md',
        'workdir': 'project/Hermes/',
        'title': 'Parent title',
        'messages': [
            {'role': 'user', 'content': 'root question'},
            {'role': 'ai', 'content': 'root answer'},
        ],
    }

    with patch.object(scan_mod, '_queue_get_entry', return_value=None):
        assert scan_mod._handle_ai_fork('', 0, '继续')['error'] == '父线程不存在'
    with patch.object(scan_mod, '_queue_get_entry', return_value={**parent, 'tool': 'opencode'}):
        assert '不支持分叉' in scan_mod._handle_ai_fork('parent1', 0, '继续')['error']
    with patch.object(scan_mod, '_queue_get_entry', return_value=parent):
        assert scan_mod._handle_ai_fork('parent1', 0, '  ')['error'] == '评论不能为空'
        assert scan_mod._handle_ai_fork('parent1', 'x', '继续')['error'] == 'fork_from_index 必须是整数'
        assert '分叉点越界' in scan_mod._handle_ai_fork('parent1', 3, '继续')['error']

    with patch.object(scan_mod, '_queue_get_entry', return_value=parent), \
         patch.object(scan_mod, '_queue_add_entry', return_value='fork1') as add_entry, \
         patch.object(scan_mod, '_queue_append_message', return_value=True) as append_message, \
         patch.object(scan_mod, '_queue_consume_next') as consume_next:
        source_quote = {
            'quote_text': '正文摘录',
            'section': '背景',
            'context': {'prefix': '', 'suffix': ''},
            'source_locator': {'task_path': parent['path'], 'text_index': 0},
        }
        result = scan_mod._handle_ai_fork(
            'parent1', 1, '新支线', author='Owner', source_quote=source_quote,
        )

    assert result == {'ok': True, 'run_id': 'fork1', 'forked_from': 'parent1#1', 'queued': True}
    add_entry.assert_called_once()
    args, kwargs = add_entry.call_args
    assert args[:3] == ('codex', 'project/Hermes/sample-task.md', 'project/Hermes/')
    assert 'root question' in kwargs['prompt_override']
    assert '【新支线的第一条指令】' in kwargs['prompt_override']
    assert '正文摘录' in kwargs['prompt_override']
    assert kwargs['metadata']['fork']['parent_entry_id'] == 'parent1#1'
    append_message.assert_called_once()
    assert append_message.call_args.args[1]['content'] == '新支线'
    assert append_message.call_args.args[1]['forked_from'] == 'parent1#1'
    assert append_message.call_args.args[1]['source_quote'] == source_quote
    consume_next.assert_called_once()


def test_get_task_ledger_returns_events_and_rejects_bad_path(temp_repo):
    rel_path = 'project/Hermes/sample-task.md'
    event = {'event': 'message', 'entry_id': 'r1#0'}
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        assert scan_mod._ledger_append_events(rel_path, [event]) is True

    handler, resp = make_handler('/api/task-ledger?path=project/Hermes/sample-task.md', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project/Hermes']):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    assert resp.json['ledger_ref'] == scan_mod._ledger_rel_for_task(rel_path)
    assert resp.json['entries'][0]['entry_id'] == 'r1#0'

    handler, resp = make_handler('/api/task-ledger?path=../bad.md', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project/Hermes']):
        handler.do_GET()

    assert resp.status_code == 400
    assert resp.json['ok'] is False


def test_ai_comment_fork_route_rejects_skill_and_routes_to_fork(temp_repo):
    handler, resp = make_handler('/api/ai-comment', temp_repo)
    payload = json.dumps({
        'run_id': 'parent1',
        'comment': '/skill arg',
        'skill_id': 'skill',
        'fork_from_index': 0,
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_POST()

    assert resp.status_code == 400
    assert resp.json['ok'] is False
    assert '分叉暂不支持 skill 命令' in resp.json['error']

    handler, resp = make_handler('/api/ai-comment', temp_repo)
    payload = json.dumps({
        'run_id': 'parent1',
        'comment': '从这里另开一支',
        'author': 'Owner',
        'fork_from_index': 1,
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, '_handle_ai_fork', return_value={
             'ok': True,
             'run_id': 'fork1',
             'forked_from': 'parent1#1',
             'queued': True,
         }) as handle_fork:
        handler.do_POST()

    assert resp.status_code == 200
    assert resp.json['run_id'] == 'fork1'
    handle_fork.assert_called_once_with(
        'parent1', 1, '从这里另开一支', 'Owner', source_quote=None,
    )


def test_ai_comment_fork_route_returns_400_for_fork_validation_error(temp_repo):
    handler, resp = make_handler('/api/ai-comment', temp_repo)
    payload = json.dumps({
        'run_id': 'parent1',
        'comment': '继续',
        'fork_from_index': 'bad',
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, '_handle_ai_fork', return_value={
             'ok': False,
             'error': 'fork_from_index 必须是整数',
         }):
        handler.do_POST()

    assert resp.status_code == 400
    assert resp.json['ok'] is False
    assert resp.json['error'] == 'fork_from_index 必须是整数'


def test_governance_noise_review_enqueues_codex_prompt(temp_repo):
    prompt_dir = temp_repo / 'shared' / 'toolkit' / 'governance' / 'prompts'
    prompt_dir.mkdir(parents=True)
    (prompt_dir / 'governance-noise-review.md').write_text("""---
title: Governance noise review CLI prompt
doc_type: prompt
status: todo
workdir: .
---

# 治理噪音自检 Agent

不要重新全量扫描 Documents。
""", encoding='utf-8')

    gov_task = temp_repo / 'project' / 'Hermes' / 'gov-task.md'
    gov_task.write_text("""---
title: Documents 体检假阳性收口
task_id: GOV-1
task_family: governance
status: todo
responsibility: ai-owned
safety: read-only
source: governance/test
---

需要判断是否应继续打扰 Owner。
""", encoding='utf-8')
    packet_path = temp_repo / 'self-check-input.generated.json'
    ledger_path = temp_repo / 'self-check.generated.jsonl'

    handler, resp = make_handler('/api/governance/noise-review', temp_repo)
    handler.headers = {'Content-Length': '0'}
    handler.rfile = io.BytesIO(b'')

    def fake_consume_next():
        queue_data = scan_mod._queue_load()
        entry = queue_data['entries'][0]
        assert entry['tool'] == 'codex'
        assert entry['path'] == scan_mod.GOVERNANCE_NOISE_REVIEW_PROMPT_REL
        assert entry['workdir'] == '.'
        assert entry['metadata']['kind'] == 'governance_noise_review'
        assert entry['metadata']['candidate_total'] == 1
        prompt = entry['prompt_override']
        assert '治理噪音自检 Agent' in prompt
        assert '不要重新全量扫描 Documents' in prompt
        assert 'cron → agent → human 成本级联' in prompt
        assert 'P(wrong) × cost-to-undo > cost-to-interrupt' in prompt
        assert '自检输入快照' in prompt
        assert '自检样本账本' in prompt
        assert '后端会自动回收到 generated JSONL 样本账本' in prompt
        assert 'owner_visible_before' in prompt
        assert 'owner_visible_after' in prompt
        assert 'confidence' in prompt
        assert 'p_wrong' in prompt
        assert 'cost_to_undo' in prompt
        assert 'cost_to_interrupt' in prompt
        assert '当前治理模块候选项' in prompt
        assert 'project/Hermes/gov-task.md' in prompt
        assert 'keep-visible' in prompt
        packet = json.loads(packet_path.read_text(encoding='utf-8'))
        assert packet['schema'] == 'workspace_governance_self_check_input/v1'
        assert packet['summary']['candidate_total'] == 1
        assert packet['summary']['owner_visible_before'] == 1
        assert packet['candidates'][0]['candidate_signals'] == ['task_family:governance', 'task_id_prefix', 'source', 'keyword']
        request_record = json.loads(ledger_path.read_text(encoding='utf-8').strip())
        assert request_record['event'] == 'request'
        assert request_record['run_id'] == entry['id']
        scan_mod._queue_update_entry(entry['id'], {'status': 'completed'})

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project/Hermes']), \
         patch.object(scan_mod, 'GOVERNANCE_NOISE_REVIEW_REPORTS', []), \
         patch.object(scan_mod, 'GOVERNANCE_NOISE_REVIEW_PACKET', packet_path), \
         patch.object(scan_mod, 'GOVERNANCE_NOISE_REVIEW_LEDGER', ledger_path), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next', side_effect=fake_consume_next):
        handler.do_POST()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['tool'] == 'codex'
    assert data['run_id']
    assert data['candidate_total'] == 1
    assert data['packet_path'] == str(packet_path)
    assert data['ledger_path'] == str(ledger_path)
    assert data['message'] == '治理自检已交给 Codex CLI · 候选 1 项'


def test_governance_healthcheck_status_reads_generated_json(tmp_path):
    json_path = tmp_path / 'WORKSPACE_GOVERNANCE_HEALTHCHECK.generated.json'
    report_path = tmp_path / 'WORKSPACE_GOVERNANCE_HEALTHCHECK.generated.md'
    report_path.write_text('# Documents 治理自治链路运行报告\n', encoding='utf-8')
    json_path.write_text(json.dumps({
        'generated_at': '2026-06-21T11:47:48+08:00',
        'parsed': {
            'status_signals': {
                'status': 'signals',
                'count': 6,
                'lines': ['- 试验工具残留 42 项'],
            },
            'probe': {'cells': 28, 'states': {'warn': 5, 'needs_review': 4}},
            'responsibility': {'ai_owned': 3, 'pi_gated': 8, 'left_blank': 34},
            'auto_accept_count': 0,
            'compression_count': 1,
        },
        'commands': [
            {'label': 'scan_governance', 'returncode': 0},
            {'label': 'governance_probe', 'returncode': 0},
        ],
    }, ensure_ascii=False), encoding='utf-8')

    with patch.object(scan_mod, 'GOVERNANCE_HEALTHCHECK_JSON', json_path), \
         patch.object(scan_mod, 'GOVERNANCE_HEALTHCHECK_REPORT', report_path):
        result = scan_mod.get_governance_healthcheck_status()

    assert result['ok'] is True
    assert result['latest']['health'] == '有信号'
    assert result['latest']['signal_count'] == 6
    assert result['latest']['responsibility']['pi_gated'] == 8
    assert result['latest']['probe']['states']['needs_review'] == 4
    assert result['latest']['command_count'] == 2
    assert result['latest']['failed_command_count'] == 0
    assert result['latest']['report_exists'] is True


def test_governance_noise_review_result_records_machine_metrics(temp_repo):
    ledger_path = temp_repo / 'self-check.generated.jsonl'
    ai_content = """## 机器可读指标
```json
{
  "candidate_total": 1,
  "owner_visible_before": 1,
  "owner_visible_after": 0,
  "reduced_count": 1,
  "reduction_rate": "100%",
  "bucket_counts": {"background": 1},
  "low_confidence_count": 0,
  "items": [
    {
      "object": "project/Hermes/gov-task.md",
      "route": "background",
      "confidence": 0.82,
      "p_wrong": 0.18,
      "cost_to_undo": 1,
      "cost_to_interrupt": 3,
      "reversibility": "reversible",
      "evidence_strength": "medium",
      "needs_owner_feedback": false
    }
  ]
}
```
"""
    entry = {
        'metadata': {
            'kind': 'governance_noise_review',
            'prompt_version': 'governance-noise-review/v2',
            'packet_path': str(temp_repo / 'packet.json'),
            'packet_hash': 'abc123',
            'candidate_total': 1,
        }
    }
    with patch.object(scan_mod, 'GOVERNANCE_NOISE_REVIEW_LEDGER', ledger_path):
        err = scan_mod._record_governance_noise_review_result(
            'run-1',
            entry,
            ai_content,
            {'model': 'codex-test', 'input_tokens': 11, 'output_tokens': 22},
            1234,
        )
    assert err is None
    record = json.loads(ledger_path.read_text(encoding='utf-8').strip())
    assert record['event'] == 'result'
    assert record['run_id'] == 'run-1'
    assert record['metrics']['candidate_total'] == 1
    assert record['metrics']['bucket_counts']['background'] == 1
    assert record['metrics']['items'][0]['route'] == 'background'


def test_governance_noise_review_status_reports_latest_queue_entry(temp_repo):
    prompt_path = temp_repo / scan_mod.GOVERNANCE_NOISE_REVIEW_PROMPT_REL
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("""---
title: Governance noise review CLI prompt
workdir: .
---

# 治理噪音自检 Agent
""", encoding='utf-8')
    packet_path = temp_repo / 'self-check-input.generated.json'
    ledger_path = temp_repo / 'self-check.generated.jsonl'
    packet_path.write_text('{"ok": true}\n', encoding='utf-8')
    ledger_path.write_text('\n'.join([
        json.dumps({
            'event': 'request',
            'run_id': 'run-old',
            'candidate_total': 2,
        }, ensure_ascii=False),
        json.dumps({
            'event': 'result',
            'run_id': 'run-new',
            'metrics': {
                'candidate_total': 3,
                'owner_visible_before': 3,
                'owner_visible_after': 1,
                'reduced_count': 2,
                'reduction_rate': '67%',
                'bucket_counts': {'background': 2, 'owner-gate': 1},
                'low_confidence_count': 0,
                'items': [],
            },
            'parse_error': None,
        }, ensure_ascii=False),
    ]) + '\n', encoding='utf-8')
    queue = {
        'concurrency': 3,
        'entries': [
            {
                'id': 'run-old',
                'tool': 'codex',
                'path': scan_mod.GOVERNANCE_NOISE_REVIEW_PROMPT_REL,
                'workdir': '.',
                'status': 'completed',
                'timestamp': '2026-06-18T20:00:00',
                'read': False,
                'metadata': {'kind': 'governance_noise_review', 'candidate_total': 2},
                'output': 'old',
            },
            {
                'id': 'run-new',
                'tool': 'codex',
                'path': scan_mod.GOVERNANCE_NOISE_REVIEW_PROMPT_REL,
                'workdir': '.',
                'status': 'completed',
                'timestamp': '2026-06-18T21:00:00',
                'read': False,
                'metadata': {'kind': 'governance_noise_review', 'candidate_total': 3},
                'output': 'new output',
            },
        ],
    }
    (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')
    handler, resp = make_handler('/api/governance/noise-review/status', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'GOVERNANCE_NOISE_REVIEW_PACKET', packet_path), \
         patch.object(scan_mod, 'GOVERNANCE_NOISE_REVIEW_LEDGER', ledger_path):
        handler.do_GET()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['latest']['id'] == 'run-new'
    assert data['latest']['metadata']['candidate_total'] == 3
    assert data['latest']['metrics']['owner_visible_after'] == 1
    assert data['packet_exists'] is True
    assert data['ledger_exists'] is True


def test_get_task_detail_passes_through_landing_frontmatter(temp_repo):
    task_path = temp_repo / 'project' / 'Hermes' / 'landing-detail.md'
    task_path.write_text("""---
title: Landing Detail
task_id: HER-10
workdir: project/Hermes/
created: 2026-06-13
updated: 2026-06-14
assignee: Alice
priority: medium
status: todo
tags: []
landing_page: landing/status.html
landing_updated: 2026-06-13
---

Body.
""", encoding='utf-8')
    handler, resp = make_handler('/api/task?path=project/Hermes/landing-detail.md', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 200
    task = resp.json['task']
    assert task['landing_page'] == 'landing/status.html'
    assert task['landing_updated'] == '2026-06-13'


def test_ai_results_include_thread_fields(temp_repo):
    queue = {
        'concurrency': 3,
        'entries': [{
            'id': 'thread1',
            'tool': 'claude',
            'path': 'project/Hermes/sample-task.md',
            'workdir': 'project/Hermes/',
            'status': 'completed',
            'read': False,
            'order': 0,
            'pid': None,
            'timestamp': '2026-05-08T10:00:00',
            'started_at': '2026-05-08T09:59:00',
            'completed_at': '2026-05-08T10:00:10',
            'duration_ms': 10000,
            'output': 'done',
            'error': None,
            'session_id': 'sess-1',
            'session_valid': True,
            'messages': [
                {'role': 'ai', 'content': 'done', 'timestamp': '2026-05-08T10:00:10', 'duration_ms': 10000}
            ],
            'title': 'done',
            'prompt_length': 12,
            'output_length': 4,
        }]
    }
    (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')

    handler, resp = make_handler('/api/ai-results?path=project/Hermes/sample-task.md', temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    result = data['results'][0]
    assert result['session_id'] == 'sess-1'
    assert result['session_valid'] is True
    assert result['messages'][0]['role'] == 'ai'
    assert result['title'] == 'done'


def test_ai_comment_rejected_without_session(temp_repo):
    """Without session, ai-comment now falls back to fresh run instead of rejecting."""
    queue = {
        'concurrency': 3,
        'entries': [{
            'id': 'thread1',
            'tool': 'claude',
            'path': 'project/Hermes/sample-task.md',
            'workdir': 'project/Hermes/',
            'status': 'completed',
            'read': False,
            'order': 0,
            'pid': None,
            'timestamp': '2026-05-08T10:00:00',
            'started_at': None,
            'completed_at': '2026-05-08T10:00:10',
            'duration_ms': 10000,
            'output': 'done',
            'error': None,
            'session_id': None,
            'session_valid': False,
            'messages': [],
            'title': 'done',
            'prompt_length': 12,
            'output_length': 4,
        }]
    }
    (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')

    handler, resp = make_handler('/api/ai-comment', temp_repo)
    payload = json.dumps({'run_id': 'thread1', 'comment': '继续'}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, '_ai_semaphore') as mock_sem, \
         patch('threading.Thread') as MockThread:
        mock_sem.acquire.return_value = True
        mock_thread = MagicMock()
        MockThread.return_value = mock_thread
        handler.do_POST()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    MockThread.assert_called_once()
    target_fn = MockThread.call_args.kwargs.get('target') or MockThread.call_args.args[0]
    assert target_fn is scan_mod._run_cli


def test_queue_migration_adds_thread_fields(temp_repo):
    queue = {
        'concurrency': 3,
        'entries': [{
            'id': 'legacy1',
            'tool': 'claude',
            'path': 'project/Hermes/sample-task.md',
            'workdir': 'project/Hermes/',
            'status': 'completed',
            'read': True,
            'order': 0,
            'pid': None,
            'timestamp': '2026-05-08T10:00:00',
            'started_at': None,
            'completed_at': '2026-05-08T10:00:10',
            'duration_ms': 10000,
            'output': 'legacy output',
            'error': None,
            'prompt_length': 12,
            'output_length': 13,
        }]
    }
    (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        loaded = scan_mod._queue_load()

    entry = loaded['entries'][0]
    assert entry['session_id'] is None
    assert entry['session_valid'] is False
    assert entry['messages'][0]['content'] == 'legacy output'


def test_queue_migration_clears_stale_error_on_completed_entry(temp_repo):
    entry = _make_queue_entry('done-with-error', 'completed', session_id='sess-1', session_valid=True)
    entry['error'] = '服务重启，运行已丢失'
    queue = {'concurrency': 3, 'entries': [entry]}
    (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        loaded = scan_mod._queue_load()

    assert loaded['entries'][0]['status'] == 'completed'
    assert loaded['entries'][0]['error'] is None


def test_recover_queue_keeps_running_entry_completed_when_ai_message_exists(temp_repo):
    entry = _make_queue_entry('run-after-message', 'running', session_id='sess-1', session_valid=True)
    entry.update({
        'output': None,
        'error': None,
        'completed_at': None,
        'messages': [
            {'role': 'user', 'content': '请总结', 'timestamp': '2026-05-08T10:00:00'},
            {'role': 'ai', 'content': '已经完成的总结', 'timestamp': '2026-05-08T10:00:12', 'duration_ms': 12000},
        ],
    })
    queue = {'concurrency': 3, 'entries': [entry]}
    (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, '_queue_consume_next'):
        scan_mod._recover_queue()

    recovered = json.loads((temp_repo / '.ai-queue.json').read_text(encoding='utf-8'))['entries'][0]
    assert recovered['status'] == 'completed'
    assert recovered['error'] is None
    assert recovered['output'] == '已经完成的总结'
    assert recovered['completed_at'] == '2026-05-08T10:00:12'
    assert recovered['output_length'] == len('已经完成的总结')


def test_queue_claim_serializes_runs_with_same_workdir(temp_repo):
    other_dir = temp_repo / 'project' / 'Other'
    other_dir.mkdir(parents=True)
    (other_dir / 'other-task.md').write_text("""---
title: Other Task
task_id: OTH-1
workdir: project/Other/
created: 2026-06-18
updated: 2026-06-18
assignee: Alice
priority: medium
status: todo
tags: []
---

Body.
""", encoding='utf-8')
    queue = {
        'concurrency': 3,
        'entries': [
            {
                'id': 'run-a',
                'tool': 'claude',
                'path': 'project/Hermes/sample-task.md',
                'workdir': 'project/Hermes/',
                'status': 'running',
                'read': False,
                'order': 0,
                'pid': 123,
                'timestamp': '2026-06-18T10:00:00',
                'started_at': '2026-06-18T10:00:00',
                'completed_at': None,
                'duration_ms': None,
                'output': None,
                'error': None,
                'prompt_length': 0,
                'output_length': 0,
            },
            {
                'id': 'run-b',
                'tool': 'claude',
                'path': 'project/Hermes/second-task.md',
                'workdir': 'project/Hermes/',
                'status': 'queued',
                'read': False,
                'order': 1,
                'pid': None,
                'timestamp': '2026-06-18T10:01:00',
                'started_at': None,
                'completed_at': None,
                'duration_ms': None,
                'output': None,
                'error': None,
                'prompt_length': 0,
                'output_length': 0,
            },
            {
                'id': 'run-c',
                'tool': 'claude',
                'path': 'project/Other/other-task.md',
                'workdir': 'project/Other/',
                'status': 'queued',
                'read': False,
                'order': 2,
                'pid': None,
                'timestamp': '2026-06-18T10:02:00',
                'started_at': None,
                'completed_at': None,
                'duration_ms': None,
                'output': None,
                'error': None,
                'prompt_length': 0,
                'output_length': 0,
            },
        ],
    }
    (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        claimed = scan_mod._queue_claim_next()
        assert claimed['id'] == 'run-c'
        queue_after_first_claim = scan_mod._queue_load()
        by_id = {entry['id']: entry for entry in queue_after_first_claim['entries']}
        assert by_id['run-b']['status'] == 'queued'
        assert by_id['run-c']['status'] == 'running'

        scan_mod._queue_update_entry('run-a', {'status': 'completed'})
        claimed_after_hermes_finishes = scan_mod._queue_claim_next()

    assert claimed_after_hermes_finishes['id'] == 'run-b'


def test_get_file_serves_project_image(temp_repo):
    handler, resp = make_handler('/api/file?path=project/Hermes/local-image.png', temp_repo)

    class FileHandler(handler.__class__):
        def __init__(self):
            super().__init__()
            self.wfile = io.BytesIO()
            self._response = resp

        def send_response(self, code, message=None):
            resp.status_code = code

        def send_header(self, key, value):
            resp.headers[key] = str(value)

        def end_headers(self):
            pass

    file_handler = FileHandler()
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        file_handler.do_GET()
    body = file_handler.wfile.getvalue()
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'image/png'
    assert resp.headers['Cache-Control'] == 'no-store, no-cache, must-revalidate'
    assert resp.headers['Pragma'] == 'no-cache'
    assert resp.headers['Expires'] == '0'
    assert body.startswith(b'\x89PNG')


def test_get_file_rejects_paths_outside_scan_dirs(temp_repo):
    outside = temp_repo / 'outside.png'
    outside.write_bytes(b'not-real')
    handler, resp = make_handler('/api/file?path=outside.png', temp_repo)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_GET()

    assert resp.status_code == 400
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == '仅支持 scan_dirs 目录下的图片'


def test_prepare_upload_returns_presigned_post_contract(temp_repo, monkeypatch):
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'filename': 'screenshot.png',
        'content_type': 'image/png',
    }).encode('utf-8')
    handler, resp = make_handler('/api/prepare-upload', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    monkeypatch.setenv('KANBAN_S3_BUCKET', 'kanban-bucket')
    monkeypatch.setenv('KANBAN_S3_REGION', 'ap-southeast-1')
    monkeypatch.setenv('KANBAN_S3_ACCESS_KEY_ID', 'AKIATEST')
    monkeypatch.setenv('KANBAN_S3_SECRET_ACCESS_KEY', 'secret-key')
    monkeypatch.setenv('KANBAN_S3_PUBLIC_BASE_URL', 'https://cdn.example.com')
    monkeypatch.setenv('KANBAN_S3_UPLOAD_URL', 'https://upload.example.com')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_POST()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['method'] == 'POST'
    assert data['upload_url'] == 'https://upload.example.com'
    assert data['final_url'].startswith('https://cdn.example.com/kanban/Hermes/markdown-images/')
    assert data['fields']['Content-Type'] == 'image/png'
    assert data['fields']['key'] == data['key']


def test_prepare_upload_reads_s3_settings_from_config(temp_repo, monkeypatch):
    config_path = temp_repo / '.kanban.config.json'
    config_path.write_text(json.dumps({
        's3': {
            'bucket': 'config-bucket',
            'region': 'ap-guangzhou',
            'access_key_id': 'AKIDCONFIG',
            'secret_access_key': 'config-secret',
            'public_base_url': 'https://cdn.config.example.com/',
            'upload_url': 'https://config-bucket.cos.ap-guangzhou.myqcloud.com/',
        }
    }, ensure_ascii=False), encoding='utf-8')
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'filename': 'diagram.png',
        'content_type': 'image/png',
    }).encode('utf-8')
    handler, resp = make_handler('/api/prepare-upload', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    for env_name in (
        'KANBAN_S3_BUCKET',
        'KANBAN_S3_REGION',
        'KANBAN_S3_ACCESS_KEY_ID',
        'KANBAN_S3_SECRET_ACCESS_KEY',
        'KANBAN_S3_PUBLIC_BASE_URL',
        'KANBAN_S3_UPLOAD_URL',
    ):
        monkeypatch.delenv(env_name, raising=False)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        prev_s3 = scan_mod.S3_CONFIG
        try:
            scan_mod.S3_CONFIG = scan_mod.load_config().get('s3', {})
            handler.do_POST()
        finally:
            scan_mod.S3_CONFIG = prev_s3

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['upload_url'] == 'https://config-bucket.cos.ap-guangzhou.myqcloud.com'
    assert data['final_url'].startswith('https://cdn.config.example.com/kanban/Hermes/markdown-images/')


def test_prepare_upload_rejects_non_image_content_type(temp_repo):
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'filename': 'notes.txt',
        'content_type': 'text/plain',
    }).encode('utf-8')
    handler, resp = make_handler('/api/prepare-upload', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_POST()

    assert resp.status_code == 400
    data = resp.json
    assert data['ok'] is False
    assert data['error'] == '仅支持图片文件'


def test_load_config_normalizes_invalid_feishu_member_open_ids(temp_repo):
    config_path = temp_repo / '.kanban.config.json'
    config_path.write_text(json.dumps({
        'feishu': {
            'app_id': 'cli_app',
            'app_secret': 'cli_secret',
            'kanban_base_url': 'https://kanban.example.com/',
            'member_open_ids': 'invalid',
        }
    }, ensure_ascii=False), encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        config = scan_mod.load_config()

    assert config['feishu']['app_id'] == 'cli_app'
    assert config['feishu']['app_secret'] == 'cli_secret'
    assert config['feishu']['kanban_base_url'] == 'https://kanban.example.com'
    assert config['feishu']['member_open_ids'] == {}


def test_create_skips_feishu_when_not_configured(temp_repo):
    payload = json.dumps({
        'project': 'Hermes',
        'title': 'Created Task',
        'assignee': 'Alice',
        'priority': 'high',
        'body': 'task body',
        'due_date': '2026-05-20',
    }).encode('utf-8')
    handler, resp = make_handler('/api/create', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', temp_repo / '.kanban-state.json'), \
         patch.object(scan_mod, 'FEISHU_CONFIG', {
             'app_id': '',
             'app_secret': '',
             'kanban_base_url': '',
             'member_open_ids': {},
         }):
        scan_mod.feishu_notify.set_config(scan_mod.FEISHU_CONFIG)
        handler.do_POST()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert 'feishu_warning' not in data


def test_create_derived_task_stays_in_configured_demo_project(temp_repo):
    demo_project = temp_repo / 'demo' / 'projects' / 'literature-review'
    demo_project.mkdir(parents=True)
    payload = json.dumps({
        'project': 'literature-review',
        'title': 'Derived demo task',
        'assignee': 'Demo Owner',
        'priority': 'medium',
        'body': 'child body',
        'promoted_from': 'DEMO-001',
    }).encode('utf-8')
    handler, resp = make_handler('/api/create', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'SCAN_DIRS', ['demo/projects/literature-review']), \
         patch.object(scan_mod, 'STATE_FILE', temp_repo / '.kanban-state.json'), \
         patch.object(scan_mod, 'FEISHU_CONFIG', {
             'app_id': '', 'app_secret': '', 'kanban_base_url': '', 'member_open_ids': {},
         }):
        scan_mod.feishu_notify.set_config(scan_mod.FEISHU_CONFIG)
        handler.do_POST()

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    card = next(demo_project.glob(f"{resp.json['task_id']}_*.md"))
    content = card.read_text(encoding='utf-8')
    assert 'workdir: demo/projects/literature-review/' in content
    assert 'promoted_from: DEMO-001' in content
    assert not (temp_repo / 'project' / 'literature-review').exists()


def test_create_accepts_task_family_and_execution_profile(temp_repo):
    payload = json.dumps({
        'project': '个人调度',
        'title': '制定个人看板任务卡命名规则',
        'assignee': 'Owner',
        'priority': 'medium',
        'body': '治理规则',
        'workdir': '/Users/example/workspace/kanban',
        'task_family': 'governance',
        'execution_profile': 'kanban',
        'legacy_id': 'XXX-25',
    }).encode('utf-8')
    handler, resp = make_handler('/api/create', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', temp_repo / '.kanban-state.json'), \
         patch.object(scan_mod, 'FEISHU_CONFIG', {
             'app_id': '',
             'app_secret': '',
             'kanban_base_url': '',
             'member_open_ids': {},
         }):
        scan_mod.feishu_notify.set_config(scan_mod.FEISHU_CONFIG)
        handler.do_POST()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['task_id'] == 'GOV-1'
    content = (temp_repo / 'project' / '个人调度' / 'GOV-1_制定个人看板任务卡命名规则.md').read_text(encoding='utf-8')
    assert 'legacy_id: XXX-25' in content
    assert 'task_family: governance' in content
    assert 'execution_profile: kanban' in content


def test_create_real_project_task_writes_explicit_project_role(temp_repo):
    registry = temp_repo / 'project' / '个人调度' / '.real-projects' / 'projects.json'
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({
        'schema': 'kanban-real-projects/v1',
        'projects': [{
            'project_ref': 'project-alpha',
            'title': 'Project Alpha',
            'confirmed_by': 'owner',
            'confirmed_at': '2026-08-11',
            'lifecycle': 'active',
            'health': 'normal',
            'current_intent': 'Ship the project',
            'primary_action': {'type': 'no_action'},
            'facts': [],
            'fact_roots': [],
        }],
    }), encoding='utf-8')
    payload = json.dumps({
        'project': '个人调度',
        'project_ref': 'project-alpha',
        'project_role': 'delivery',
        'title': 'Prepare customer delivery',
        'assignee': 'Owner',
        'priority': 'high',
        'body': 'delivery brief',
    }).encode('utf-8')
    handler, resp = make_handler('/api/create', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', temp_repo / '.kanban-state.json'), \
         patch.object(scan_mod, 'FEISHU_CONFIG', {
             'app_id': '', 'app_secret': '', 'kanban_base_url': '', 'member_open_ids': {},
         }):
        scan_mod.feishu_notify.set_config(scan_mod.FEISHU_CONFIG)
        handler.do_POST()

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    card = next((temp_repo / 'project' / '个人调度').glob(f"{resp.json['task_id']}_*.md"))
    content = card.read_text(encoding='utf-8')
    assert 'project_ref: project-alpha' in content
    assert 'project_role: delivery' in content


def test_update_assignee_skips_feishu_when_not_configured(temp_repo):
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'field': 'assignee',
        'value': 'Bob',
    }).encode('utf-8')
    handler, resp = make_handler('/api/update', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'FEISHU_CONFIG', {
             'app_id': '',
             'app_secret': '',
             'kanban_base_url': '',
             'member_open_ids': {},
         }):
        scan_mod.feishu_notify.set_config(scan_mod.FEISHU_CONFIG)
        handler.do_PUT()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert 'feishu_warning' not in data
    content = (temp_repo / 'project' / 'Hermes' / 'sample-task.md').read_text(encoding='utf-8')
    assert 'assignee: Bob' in content


def test_update_title_returns_new_path_and_updates_references(temp_repo):
    ref_path = temp_repo / 'project' / 'Hermes' / 'second-task.md'
    ref_path.write_text(ref_path.read_text(encoding='utf-8') + '\nSee [[project/Hermes/sample-task.md]].\n', encoding='utf-8')
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'field': 'title',
        'value': 'Renamed Task',
    }).encode('utf-8')
    handler, resp = make_handler('/api/update', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'FEISHU_CONFIG', {
             'app_id': '',
             'app_secret': '',
             'kanban_base_url': '',
             'member_open_ids': {},
         }):
        scan_mod.feishu_notify.set_config(scan_mod.FEISHU_CONFIG)
        handler.do_PUT()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['new_path'] == 'project/Hermes/HER-1_Renamed-Task.md'
    assert not (temp_repo / 'project' / 'Hermes' / 'sample-task.md').exists()
    assert (temp_repo / data['new_path']).exists()
    assert '[[project/Hermes/HER-1_Renamed-Task.md]]' in ref_path.read_text(encoding='utf-8')


def test_create_returns_feishu_warning_when_enabled_but_member_not_mapped(temp_repo):
    payload = json.dumps({
        'project': 'Hermes',
        'title': 'Need Notify',
        'assignee': 'Alice',
        'priority': 'high',
        'body': 'task body',
    }).encode('utf-8')
    handler, resp = make_handler('/api/create', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', temp_repo / '.kanban-state.json'), \
         patch.object(scan_mod, 'FEISHU_CONFIG', {
             'app_id': 'app',
             'app_secret': 'secret',
             'kanban_base_url': '',
             'member_open_ids': {},
         }):
        scan_mod.feishu_notify.set_config(scan_mod.FEISHU_CONFIG)
        handler.do_POST()

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    assert data['feishu_warning'] == "成员 'Alice' 未配置飞书 open_id"


def test_save_user_config_rejects_feishu_without_writing(temp_repo):
    payload = json.dumps({
        'feishu': {
            'app_id': 'new_app',
            'app_secret': 'new_secret',
            'kanban_base_url': 'https://kanban.example.com/',
            'member_open_ids': {'Alice': 'ou_123'},
        }
    }).encode('utf-8')
    handler, resp = make_handler('/api/save-user-config', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    user_cfg_path = temp_repo / '.kanban.user.config.json'

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_POST()

    assert resp.status_code == 400
    data = resp.json
    assert data['ok'] is False
    assert 'feishu' in data['error']
    assert not user_cfg_path.exists()


# ── Tests: ai-comment retry/fallback logic ──────────────────

def _make_queue_entry(entry_id, status, session_id=None, session_valid=None, tool='claude'):
    """Helper to build a queue entry for ai-comment tests."""
    entry = {
        'id': entry_id,
        'tool': tool,
        'path': 'project/Hermes/sample-task.md',
        'workdir': 'project/Hermes/',
        'status': status,
        'read': False,
        'order': 0,
        'pid': None,
        'timestamp': '2026-05-08T10:00:00',
        'started_at': None,
        'completed_at': '2026-05-08T10:00:10',
        'duration_ms': 10000,
        'output': 'done',
        'error': None,
        'messages': [],
        'title': 'done',
        'prompt_length': 12,
        'output_length': 4,
    }
    if session_id is not None:
        entry['session_id'] = session_id
    if session_valid is not None:
        entry['session_valid'] = session_valid
    return entry


def _setup_queue_and_call(temp_repo, entry, comment='继续', skill_id='', source_quote=None):
    """Write queue file, create handler, and call /api/ai-comment with threading patched."""
    queue = {'concurrency': 3, 'entries': [entry]}
    (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')

    handler, resp = make_handler('/api/ai-comment', temp_repo)
    body = {'run_id': entry['id'], 'comment': comment}
    if skill_id:
        body['skill_id'] = skill_id
    if source_quote:
        body['source_quote'] = source_quote
    payload = json.dumps(body).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, '_ai_semaphore') as mock_sem, \
         patch('threading.Thread') as MockThread:
        mock_sem.acquire.return_value = True
        mock_thread = MagicMock()
        MockThread.return_value = mock_thread
        handler.do_POST()

    return resp, MockThread


def test_ai_comment_killed_with_valid_session_uses_resume(temp_repo):
    """Killed entry with valid session should use _run_cli_resume."""
    entry = _make_queue_entry('retry1', 'killed', session_id='sess-abc', session_valid=True)
    resp, MockThread = _setup_queue_and_call(temp_repo, entry)

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    MockThread.assert_called_once()
    target_fn = MockThread.call_args.kwargs.get('target') or MockThread.call_args.args[0]
    assert target_fn is scan_mod._run_cli_resume


def test_ai_comment_persists_source_quote_and_augments_resume_prompt(temp_repo):
    entry = _make_queue_entry('quote-reply', 'completed', session_id='sess-quote', session_valid=True)
    source_quote = {
        'quote_text': '正文中的关键结论',
        'section': '结果',
        'context': {'prefix': '前文', 'suffix': '后文'},
        'source_locator': {
            'task_path': entry['path'],
            'body_rev': 'rev-a',
            'text_index': 18,
            'prefix': '前文',
            'suffix': '后文',
            'block_index': 2,
        },
    }
    resp, MockThread = _setup_queue_and_call(
        temp_repo, entry, comment='请据此补充', source_quote=source_quote,
    )

    assert resp.status_code == 200
    saved = json.loads((temp_repo / '.ai-queue.json').read_text(encoding='utf-8'))['entries'][0]
    assert saved['messages'][0]['content'] == '请据此补充'
    assert saved['messages'][0]['source_quote']['quote_text'] == '正文中的关键结论'
    thread_args = MockThread.call_args.kwargs.get('args') or ()
    assert '正文中的关键结论' in thread_args[3]
    assert '请据此补充' in thread_args[3]


def test_ai_comment_error_without_session_falls_back_to_fresh_run(temp_repo):
    """Error entry without session should fallback to _run_cli."""
    entry = _make_queue_entry('retry2', 'error', session_id=None, session_valid=False)
    resp, MockThread = _setup_queue_and_call(temp_repo, entry)

    assert resp.status_code == 200
    data = resp.json
    assert data['ok'] is True
    MockThread.assert_called_once()
    target_fn = MockThread.call_args.kwargs.get('target') or MockThread.call_args.args[0]
    assert target_fn is scan_mod._run_cli
    # Verify prompt includes task file content
    thread_args = MockThread.call_args.kwargs.get('args') or ()
    prompt_body = thread_args[3] if len(thread_args) > 3 else ''
    assert '继续' in prompt_body
    assert 'Sample Task' in prompt_body


def test_ai_comment_fallback_uses_skill_augmented_prompt_and_keeps_raw_message(temp_repo):
    """Fallback should send skill-enhanced prompt to Claude while preserving raw UI history."""
    skill_dir = temp_repo / '.claude' / 'skills' / 'retry-skill'
    skill_dir.mkdir(parents=True)
    (skill_dir / 'SKILL.md').write_text("""---
name: Retry Skill
description: Test skill for retry prompt enhancement
argument-hint: TOPIC
---

增强指令: $ARGUMENTS
第一个参数: $1
""", encoding='utf-8')

    entry = _make_queue_entry('retry-skill-run', 'killed', session_id='old-sess', session_valid=False)
    raw_comment = '/retry-skill 修复输入'
    resp, MockThread = _setup_queue_and_call(temp_repo, entry, comment=raw_comment)

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    target_fn = MockThread.call_args.kwargs.get('target') or MockThread.call_args.args[0]
    assert target_fn is scan_mod._run_cli
    thread_args = MockThread.call_args.kwargs.get('args') or ()
    prompt_body = thread_args[3]
    assert '<skill_instructions id="retry-skill">' in prompt_body
    assert '增强指令: 修复输入' in prompt_body
    assert '<user_comment>' in prompt_body
    assert raw_comment in prompt_body
    assert 'Sample Task' in prompt_body

    queue_data = json.loads((temp_repo / '.ai-queue.json').read_text(encoding='utf-8'))
    user_message = queue_data['entries'][0]['messages'][0]
    assert user_message['content'] == raw_comment
    assert user_message['skill_id'] == 'retry-skill'
    assert user_message['skill_args'] == '修复输入'


def test_ai_comment_unsupported_tool_rejected(temp_repo):
    """Unsupported tools should be rejected."""
    entry = _make_queue_entry('unsupported1', 'killed', tool='opencode')
    queue = {'concurrency': 3, 'entries': [entry]}
    (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')

    handler, resp = make_handler('/api/ai-comment', temp_repo)
    payload = json.dumps({'run_id': 'unsupported1', 'comment': '继续'}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_POST()

    assert resp.status_code == 400
    assert resp.json['ok'] is False


def test_ai_comment_disallowed_status_rejected(temp_repo):
    """queued and timeout statuses should be rejected."""
    for status in ('queued', 'timeout', 'running'):
        entry = _make_queue_entry('s1', status, session_id='sess-abc', session_valid=True)
        queue = {'concurrency': 3, 'entries': [entry]}
        (temp_repo / '.ai-queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')

        handler, resp = make_handler('/api/ai-comment', temp_repo)
        payload = json.dumps({'run_id': 's1', 'comment': '继续'}).encode('utf-8')
        handler.headers = {'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)

        with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
            handler.do_POST()

        assert resp.status_code == 400, f'status={status} should be rejected'
        assert resp.json['ok'] is False


def test_ai_comment_fallback_resets_session(temp_repo):
    """Fallback branch should reset session_id to None and session_valid to True."""
    entry = _make_queue_entry('retry3', 'killed', session_id='old-sess', session_valid=False)
    resp, MockThread = _setup_queue_and_call(temp_repo, entry)

    assert resp.status_code == 200
    # Read the queue file to verify session was reset
    queue_data = json.loads((temp_repo / '.ai-queue.json').read_text(encoding='utf-8'))
    updated = queue_data['entries'][0]
    assert updated['session_id'] is None
    assert updated['session_valid'] is True
    assert updated['status'] == 'running'


def test_task_documents_endpoint_lists_and_appends_only_linked_markdown(temp_repo):
    task_path = 'project/Hermes/sample-task.md'
    task_file = temp_repo / task_path
    linked = temp_repo / 'linked-context.md'
    linked.write_text('# Context\n', encoding='utf-8')
    raw = task_file.read_text(encoding='utf-8')
    raw = raw.replace(
        'tags: [backend, api]\n',
        'tags: [backend, api]\n'
        f'related_paths:\n  - {linked}\n'
        f'default_context_doc: {linked}\n',
    )
    task_file.write_text(raw, encoding='utf-8')

    handler, resp = make_handler('/api/task-documents?path=' + task_path, temp_repo)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    assert resp.json['documents'][0]['path'] == str(linked)
    assert resp.json['documents'][0]['is_default'] is True

    payload = json.dumps({
        'path': task_path,
        'document_path': str(linked),
        'source_quote': {
            'quote_text': 'This is the markdown body of the task.',
            'section': 'Sample Task',
            'context': {'prefix': '', 'suffix': ''},
            'source_locator': {
                'task_path': task_path,
                'body_rev': 'rev-1',
                'text_index': 15,
                'block_index': 1,
            },
        },
    }).encode('utf-8')
    handler, resp = make_handler('/api/task-documents/append', temp_repo)
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}):
        handler.do_POST()

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    linked_content = linked.read_text(encoding='utf-8')
    assert '> This is the markdown body of the task.' in linked_content
    assert '"schema": "selection-anchor/v1"' in linked_content
    assert '"task_id": "HER-1"' in linked_content


def test_selection_quick_explain_is_marked_transient(temp_repo):
    handler, resp = make_handler('/api/ai-run', temp_repo)
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'tool': 'codex',
        'prompt': '解释这段话',
        'display_message': '快速解释',
        'origin': 'selection_quick_explain',
        'source_quote': {
            'quote_text': 'This is the markdown body of the task.',
            'source_locator': {'task_path': 'project/Hermes/sample-task.md'},
        },
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next'):
        handler.do_POST()

    assert resp.status_code == 200
    queue_data = json.loads((temp_repo / '.ai-queue.json').read_text(encoding='utf-8'))
    dialogue = queue_data['entries'][0]['metadata']['dialogue']
    assert dialogue['origin'] == 'selection_quick_explain'
    assert dialogue['lifecycle'] == 'transient'
    assert queue_data['entries'][0]['ai_profile'] == 'quick_explain'


def test_selection_quick_explain_rejects_write_or_wrong_tool_profile(temp_repo):
    handler, resp = make_handler('/api/ai-run', temp_repo)
    payload = json.dumps({
        'path': 'project/Hermes/sample-task.md',
        'tool': 'codex',
        'profile': 'execute_codex',
        'prompt': '解释这段话',
        'display_message': '快速解释',
        'origin': 'selection_quick_explain',
    }).encode('utf-8')
    handler.headers = {'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(temp_repo)]}), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, '_queue_consume_next'):
        handler.do_POST()

    assert resp.status_code == 400
    assert '只允许 profile quick_explain' in resp.json['error']


def test_ai_profile_command_and_resume_keep_read_only_config():
    profile = scan_mod.AI_PROFILES['deep_codex']
    entry = {'ai_profile': 'deep_codex'}
    command = scan_mod._ai_command_for_entry('codex', entry)

    assert command == profile['command']
    assert 'sandbox_mode=read-only' in command
    assert 'approval_policy=never' in command

    resumed = scan_mod._normalize_codex_resume_command(command, 'thread-123')
    assert resumed[:5] == ['codex', 'exec', 'resume', 'thread-123', '-']
    assert 'sandbox_mode=read-only' in resumed
    assert 'approval_policy=never' in resumed
    assert resumed.count('--skip-git-repo-check') == 1


def test_codex_command_allows_non_git_workdir_without_duplicate_flag():
    command = scan_mod._normalize_codex_command(['codex', 'exec', '--yolo', '--json'])
    fallback = scan_mod._normalize_codex_command([])
    configured = scan_mod._normalize_codex_command([
        'codex', 'exec', '--skip-git-repo-check', '--json',
    ])
    resumed_fallback = scan_mod._normalize_codex_resume_command([], 'thread-fallback')

    assert command[:2] == ['codex', 'exec']
    assert command.count('--skip-git-repo-check') == 1
    assert fallback.count('--skip-git-repo-check') == 1
    assert configured.count('--skip-git-repo-check') == 1
    assert resumed_fallback.count('--skip-git-repo-check') == 1


def test_parse_claude_json_uses_model_usage_key_when_model_is_omitted():
    parsed = scan_mod._parse_claude_json_output(json.dumps({
        'result': 'OK',
        'session_id': 'session-1',
        'modelUsage': {'claude-sonnet-5': {'inputTokens': 10}},
        'usage': {'input_tokens': 10, 'output_tokens': 1},
    }))

    assert parsed['model'] == 'claude-sonnet-5'
