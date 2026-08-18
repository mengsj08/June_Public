#!/usr/bin/env python3
"""P0 security hardening tests for mutating endpoints."""

import io
import json
import stat
from pathlib import Path
from unittest.mock import patch

import importlib.util
import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


class _Resp:
    def __init__(self):
        self.status_code = None
        self.json = None


def _make_handler(path, payload=None, headers=None):
    resp = _Resp()
    raw = json.dumps(payload if payload is not None else {}).encode('utf-8')

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.client_address = ('127.0.0.1', 12345)
            self.headers = {'Host': 'localhost', 'Content-Length': str(len(raw))}
            if headers:
                self.headers.update(headers)
            self.rfile = io.BytesIO(raw)
            self.wfile = io.BytesIO()

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


def _write_task(repo, rel_path, workdir):
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: Security Task
task_id: SEC-1
workdir: {workdir}
created: 2026-06-01
updated: 2026-06-01
assignee: Alice
priority: medium
status: todo
tags: []
---

Body.
""",
        encoding='utf-8',
    )
    return path


def test_state_change_guard_blocks_bad_origin_allows_same_origin_and_no_origin(tmp_path):
    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Alice'}), \
         patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        handler, resp = _make_handler('/api/save-user-config', {}, {'Origin': 'https://evil.example'})
        handler.do_POST()
        assert resp.status_code == 403
        assert resp.json == {'ok': False, 'error': 'cross-origin blocked'}

        handler, resp = _make_handler('/api/save-user-config', {}, {'Origin': f'http://localhost:{scan_mod.PORT}'})
        handler.do_POST()
        assert resp.status_code == 200
        assert resp.json['ok'] is True

        handler, resp = _make_handler('/api/save-user-config', {})
        handler.do_POST()
        assert resp.status_code == 200
        assert resp.json['ok'] is True


def test_state_change_guard_blocks_bad_host(tmp_path):
    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Alice'}), \
         patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        handler, resp = _make_handler('/api/save-user-config', {}, {'Host': 'evil.example'})
        handler.do_POST()
    assert resp.status_code == 403
    assert resp.json == {'ok': False, 'error': 'cross-origin blocked'}


def test_get_guard_blocks_malicious_and_comma_hosts_before_shell_or_api_dispatch():
    for path in ('/', '/static/kanban/main.js', '/api/health', '/api/data'):
        for host in ('evil.example', 'localhost,evil.example', 'localhost, evil.example'):
            handler, resp = _make_handler(path, headers={'Host': host})
            handler.do_GET()
            assert resp.status_code == 403, (path, host, resp.json)
            assert resp.json == {'ok': False, 'error': 'cross-origin blocked'}


def test_health_fingerprint_is_public_but_still_host_guarded():
    handler, resp = _make_handler('/api/health')
    handler.do_GET()
    assert resp.status_code == 200
    assert resp.json == {
        'ok': True,
        'product': 'project-canvas',
        'fingerprint': 'project-canvas/health-v1',
    }


def test_random_token_default_is_first_start_stable_owner_only_and_gitignored(tmp_path):
    config = {'auth': {'mode': 'token', 'token_file': '.kanban.auth-token'}}
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        first, token_path = scan_mod._ensure_local_auth_token(config)
        second, same_path = scan_mod._ensure_local_auth_token(config)

    assert scan_mod._auth_mode({}) == 'token'
    assert first == second
    assert len(first) >= 32
    assert token_path == same_path == tmp_path / '.kanban.auth-token'
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert '.kanban.auth-token' in (_HERE.parent / '.gitignore').read_text(encoding='utf-8')


def test_token_file_cannot_escape_repo_or_follow_symlink(tmp_path):
    outside = tmp_path / 'token-target'
    outside.write_text('x' * 40, encoding='utf-8')
    link = tmp_path / '.kanban.auth-token'
    link.symlink_to(outside)
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        with pytest.raises(ValueError, match='符号链接'):
            scan_mod._ensure_local_auth_token({'auth': {'token_file': '.kanban.auth-token'}})
        with pytest.raises(ValueError, match='必须位于仓库内'):
            scan_mod._ensure_local_auth_token({'auth': {'token_file': '../escape-token'}})


def test_token_login_uses_constant_time_secret_and_quiz_is_disabled_by_default():
    with patch.object(scan_mod, 'AUTH_MODE', 'token'), \
         patch.object(scan_mod, 'AUTH_ACCESS_TOKEN', 'a' * 43), \
         patch.object(scan_mod, 'LOGIN_MEMBERS', ['Project Owner']), \
         patch.object(scan_mod, 'ALL_MEMBERS', ['Project Owner']):
        handler, resp = _make_handler('/api/verify-token', {'access_token': 'a' * 43})
        handler.do_POST()
        assert resp.status_code == 200

        handler, resp = _make_handler('/api/verify-quiz', {
            'quiz_token': 'anything', 'selected': [0], 'name': 'Project Owner',
        })
        handler.do_POST()
        assert resp.status_code == 404
        assert resp.json['error'] == 'quiz 登录未启用'


def test_sync_webhook_exempts_same_origin_guard_with_hmac():
    class DummyManager:
        mode = 'server'

        def __init__(self):
            self.calls = []

        def verify_webhook_signature(self, body, signature):
            return signature == 'ok'

        def should_handle_github_push(self, event_name, body):
            return True, None

        def request_reconcile(self, reason):
            self.calls.append(reason)

        def get_status_snapshot(self):
            return {'state': 'idle'}

    manager = DummyManager()
    body = b'{"ref":"refs/heads/main"}'
    handler, resp = _make_handler('/api/sync/webhook')
    handler.headers = {
        'Host': 'evil.example',
        'Origin': 'https://evil.example',
        'Content-Length': str(len(body)),
        'X-Hub-Signature-256': 'ok',
        'X-GitHub-Event': 'push',
    }
    handler.rfile = io.BytesIO(body)

    with patch.object(scan_mod, 'GIT_SYNC_MANAGER', manager):
        handler.do_POST()

    assert resp.status_code == 200
    assert manager.calls == ['webhook']


def test_sync_webhook_rejects_invalid_hmac_even_though_host_guard_is_exempt():
    class DummyManager:
        mode = 'server'

        def verify_webhook_signature(self, body, signature):
            return False

    handler, resp = _make_handler('/api/sync/webhook')
    with patch.object(scan_mod, 'GIT_SYNC_MANAGER', DummyManager()):
        handler.do_POST()
    assert resp.status_code == 401
    assert resp.json == {'ok': False, 'error': 'invalid signature'}


def test_save_user_config_rejects_sensitive_keys_without_writing(tmp_path):
    for key in ('clash', 'tag', 'deepseek_api_url', 'open_allowed_roots', 'dynamic_boards'):
        handler, resp = _make_handler('/api/save-user-config', {key: 'bad'})
        with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Alice'}), \
             patch.object(scan_mod, 'REPO_ROOT', tmp_path):
            handler.do_POST()
        assert resp.status_code == 400
        assert resp.json['ok'] is False
        assert not (tmp_path / '.kanban.user.config.json').exists()


def test_save_user_config_allows_tools_whitelist(tmp_path):
    handler, resp = _make_handler('/api/save-user-config', {
        'tools': {'codex': {'command': 'codex exec --json'}}
    })

    old_cli = dict(scan_mod.CLI_COMMANDS)
    try:
        with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Alice'}), \
             patch.object(scan_mod, 'REPO_ROOT', tmp_path):
            handler.do_POST()
        assert resp.status_code == 200
        assert resp.json['ok'] is True
        saved = json.loads((tmp_path / '.kanban.user.config.json').read_text(encoding='utf-8'))
        assert saved == {'tools': {'codex': {'command': 'codex exec --json'}}}
    finally:
        scan_mod.CLI_COMMANDS.clear()
        scan_mod.CLI_COMMANDS.update(old_cli)


def test_ai_run_rejects_workdir_outside_allowed_roots_with_403_and_log(tmp_path, capsys):
    for workdir in ('/', '~/.ssh'):
        _write_task(tmp_path, 'project/Security/task.md', workdir)
        handler, resp = _make_handler('/api/ai-run', {
            'path': 'project/Security/task.md',
            'tool': 'claude',
            'create_workdir': True,
        })
        with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Alice'}), \
             patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
             patch.object(scan_mod, 'CLI_COMMANDS', {'claude': ['true']}), \
             patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(tmp_path / 'Documents')]}):
            handler.do_POST()
        assert resp.status_code == 403
        assert resp.json['ok'] is False
        assert 'workdir 不在可信根内' in resp.json['error']
    assert 'reason=workdir-outside-trusted-roots' in capsys.readouterr().err


def test_ai_run_allows_workdir_inside_allowed_roots(tmp_path):
    docs = tmp_path / 'Documents'
    workdir = docs / 'repo'
    workdir.mkdir(parents=True)
    _write_task(tmp_path, 'project/Security/task.md', str(workdir))
    handler, resp = _make_handler('/api/ai-run', {
        'path': 'project/Security/task.md',
        'tool': 'claude',
    })

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Alice'}), \
         patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'claude': ['true']}), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(docs)]}), \
         patch.object(scan_mod, '_queue_add_entry', return_value='run-1'), \
         patch.object(scan_mod, '_queue_consume_next'):
        handler.do_POST()

    assert resp.status_code == 200
    assert resp.json == {'ok': True, 'run_id': 'run-1'}


def test_ai_run_allows_skill_workspace_as_second_trusted_root(tmp_path):
    docs = tmp_path / 'Documents'
    skills = tmp_path / 'skills'
    workdir = skills / 'repo'
    workdir.mkdir(parents=True)
    docs.mkdir()
    _write_task(tmp_path, 'project/Security/task.md', str(workdir))
    handler, resp = _make_handler('/api/ai-run', {
        'path': 'project/Security/task.md',
        'tool': 'codex',
    })

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Alice'}), \
         patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'CLI_COMMANDS', {'codex': ['true']}), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(docs), str(skills)]}), \
         patch.object(scan_mod, '_queue_add_entry', return_value='run-2'), \
         patch.object(scan_mod, '_queue_consume_next'):
        handler.do_POST()

    assert resp.status_code == 200
    assert resp.json == {'ok': True, 'run_id': 'run-2'}


def test_open_rejects_executable_types_and_allows_markdown(tmp_path):
    docs = tmp_path / 'Documents'
    docs.mkdir()
    app = docs / 'x.app'
    app.mkdir()
    command = docs / 'x.command'
    command.write_text('#!/bin/zsh\n', encoding='utf-8')
    md = docs / 'x.md'
    md.write_text('ok\n', encoding='utf-8')

    cfg = {'open_allowed_roots': [str(docs)]}
    for target in (app, command):
        resolved, err, status = scan_mod.resolve_open_target(str(target), cfg)
        assert resolved is None
        assert status == 400
        assert err == '拒绝打开可执行类型'

    resolved, err, status = scan_mod.resolve_open_target(str(md), cfg)
    assert resolved == md.resolve()
    assert err is None
    assert status == 200
