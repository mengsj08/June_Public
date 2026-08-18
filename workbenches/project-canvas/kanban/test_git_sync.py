#!/usr/bin/env python3
"""Tests for git auto-sync runtime."""

import hmac
import hashlib
import json
import tempfile
from pathlib import Path
import io
from unittest.mock import patch
import threading
import time
import subprocess

import importlib.util

_HERE = Path(__file__).resolve().parent
_scan_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_scan_spec)
_scan_spec.loader.exec_module(scan_mod)
_spec = importlib.util.spec_from_file_location('kanban_git_sync', _HERE / 'git-sync.py')
git_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(git_sync)


class _DummyObserver:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def join(self, timeout=None):
        return None


def _observer_factory(manager):
    return _DummyObserver()


def _init_repo(tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=tmp_path, check=True)
    project_dir = tmp_path / 'project' / 'Hermes'
    project_dir.mkdir(parents=True)
    task_path = project_dir / 'sample-task.md'
    task_path.write_text(
        """---
title: Sample Task
task_id: HER-1
workdir: project/Hermes/
created: 2026-05-01
updated: 2026-05-01
assignee: Alice
priority: medium
status: todo
tags: []
---

Body
""",
        encoding='utf-8',
    )
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'commit', '-qm', 'init'], cwd=tmp_path, check=True)
    return task_path


def _init_repo_with_upstream(tmp_path):
    remote = tmp_path.parent / f'{tmp_path.name}-remote.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    task_path = _init_repo(tmp_path)
    subprocess.run(['git', 'branch', '-M', 'main'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'remote', 'add', 'origin', str(remote)], cwd=tmp_path, check=True)
    subprocess.run(['git', 'push', '-u', 'origin', 'HEAD'], cwd=tmp_path, check=True, capture_output=True)
    return task_path


class _DummyGitSyncManager:
    mode = 'server'

    def __init__(self):
        self.calls = []

    def get_status_snapshot(self):
        return {'state': 'idle', 'branch': 'main'}

    def verify_webhook_signature(self, body, signature):
        return signature == 'ok'

    def should_handle_github_push(self, event_name, body):
        if event_name != 'push':
            return False, 'ignored non-push event'
        payload = json.loads(body.decode('utf-8'))
        if payload.get('ref') != 'refs/heads/main':
            return False, 'ignored push for other branch'
        return True, None

    def request_reconcile(self, reason):
        self.calls.append(reason)


def test_webhook_signature_validation():
    with tempfile.TemporaryDirectory(prefix='git_sync_sig_') as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True, 'webhook_secret': 'secret'}, observer_factory=_observer_factory)
        body = b'{"ref":"refs/heads/main"}'
        signature = 'sha256=' + hmac.new(b'secret', body, hashlib.sha256).hexdigest()
        assert mgr.verify_webhook_signature(body, signature) is True
        assert mgr.verify_webhook_signature(body, 'sha256=bad') is False
        legacy = 'sha1=' + hmac.new(b'secret', body, hashlib.sha1).hexdigest()
        assert mgr.verify_webhook_signature(body, legacy) is False


def test_status_snapshot_detects_pending_and_paths():
    with tempfile.TemporaryDirectory(prefix='git_sync_status_') as tmp:
        repo = Path(tmp)
        task_path = _init_repo(repo)
        task_path.write_text(task_path.read_text(encoding='utf-8') + '\nchanged\n', encoding='utf-8')
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        mgr._refresh_status_snapshot()
        snapshot = mgr.get_status_snapshot()
        assert snapshot['pending_files_count'] == 1
        assert snapshot['pending_paths'][0] == 'project/Hermes/sample-task.md'
        assert snapshot['state'] == 'pending'


def test_status_separates_task_data_from_manual_source_review():
    with tempfile.TemporaryDirectory(prefix='git_sync_scope_status_') as tmp:
        repo = Path(tmp)
        task_path = _init_repo(repo)
        source_path = repo / 'shared' / 'toolkit' / 'kanban' / 'feature.py'
        source_path.parent.mkdir(parents=True)
        source_path.write_text('print("manual review")\n', encoding='utf-8')
        task_path.write_text(task_path.read_text(encoding='utf-8') + '\nchanged\n', encoding='utf-8')
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        mgr._refresh_status_snapshot()
        snapshot = mgr.get_status_snapshot()
        assert snapshot['pending_paths'] == ['project/Hermes/sample-task.md']
        assert snapshot['manual_review_paths'] == ['shared/toolkit/kanban/feature.py']
        assert snapshot['auto_commit_prefixes'] == ['project/']


def test_flush_commits_only_task_data_and_leaves_source_for_manual_review():
    with tempfile.TemporaryDirectory(prefix='git_sync_scope_commit_') as tmp:
        repo = Path(tmp)
        task_path = _init_repo(repo)
        source_path = repo / 'shared' / 'toolkit' / 'kanban' / 'feature.py'
        source_path.parent.mkdir(parents=True)
        source_path.write_text('print("manual review")\n', encoding='utf-8')
        task_path.write_text(task_path.read_text(encoding='utf-8') + '\nchanged\n', encoding='utf-8')
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        assert mgr.flush_now('scope-test', allow_push=False) is True
        committed = subprocess.run(
            ['git', 'show', '--format=', '--name-only', 'HEAD'], cwd=repo,
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        status = subprocess.run(
            ['git', 'status', '--short', '--untracked-files=all'], cwd=repo,
            capture_output=True, text=True, check=True,
        ).stdout
        assert committed == ['project/Hermes/sample-task.md']
        assert '?? shared/toolkit/kanban/feature.py' in status


def test_auto_push_refuses_ahead_source_commit():
    with tempfile.TemporaryDirectory(prefix='git_sync_scope_push_') as tmp:
        repo = Path(tmp)
        _init_repo_with_upstream(repo)
        source_path = repo / 'shared' / 'toolkit' / 'kanban' / 'feature.py'
        source_path.parent.mkdir(parents=True)
        source_path.write_text('print("manual push")\n', encoding='utf-8')
        subprocess.run(['git', 'add', str(source_path.relative_to(repo))], cwd=repo, check=True)
        subprocess.run(['git', 'commit', '-qm', 'manual source change'], cwd=repo, check=True)
        remote_before = subprocess.run(
            ['git', 'rev-parse', 'origin/main'], cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.strip()
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        assert mgr.flush_now('scope-push-test') is False
        snapshot = mgr.get_status_snapshot()
        remote_after = subprocess.run(
            ['git', 'rev-parse', 'origin/main'], cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert snapshot['state'] == 'paused_manual_git'
        assert snapshot['last_warning'] == '待推送提交包含需人工审阅的非任务数据，自动推送已跳过'
        assert remote_after == remote_before


def test_manual_git_pause_preserves_paused_state():
    with tempfile.TemporaryDirectory(prefix='git_sync_pause_') as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True, 'git_lock_wait_seconds': 0}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        (mgr._git_dir / 'index.lock').write_text('', encoding='utf-8')
        mgr.request_flush('fs-event')
        snapshot = mgr.get_status_snapshot()
        assert snapshot['state'] in ('idle', 'pending')
        mgr.flush_now('test')
        snapshot = mgr.get_status_snapshot()
        assert snapshot['state'] == 'paused_manual_git'
        mgr.request_flush('retry')
        snapshot = mgr.get_status_snapshot()
        assert snapshot['state'] == 'paused_manual_git'
        mgr.stop()


def test_sync_status_and_webhook_routes():
    dummy = _DummyGitSyncManager()
    handler, resp = _make_handler('/api/sync/status')
    with patch.object(scan_mod, 'GIT_SYNC_MANAGER', dummy), patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}):
        handler.do_GET()
    assert resp.status_code == 200
    assert resp.json['status']['state'] == 'idle'
    assert resp.json['status']['managers']['git']['state'] == 'idle'

    handler, resp = _make_handler('/api/sync/webhook')
    body = b'{"ref":"refs/heads/main"}'
    handler.headers = {
        'Content-Length': str(len(body)),
        'X-Hub-Signature-256': 'ok',
        'X-GitHub-Event': 'push',
    }
    handler.rfile = io.BytesIO(body)
    dummy = _DummyGitSyncManager()
    with patch.object(scan_mod, 'GIT_SYNC_MANAGER', dummy), patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}):
        handler.do_POST()
    assert resp.status_code == 200
    assert dummy.calls == ['webhook']

    handler, resp = _make_handler('/api/sync/webhook')
    body = b'{"ref":"refs/heads/main"}'
    handler.headers = {
        'Content-Length': str(len(body)),
        'X-Hub-Signature-256': 'bad',
        'X-GitHub-Event': 'push',
    }
    handler.rfile = io.BytesIO(body)
    with patch.object(scan_mod, 'GIT_SYNC_MANAGER', dummy), patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}):
        handler.do_POST()
    assert resp.status_code == 401

    handler, resp = _make_handler('/api/sync/webhook')
    body = b'{"ref":"refs/heads/main"}'
    handler.headers = {
        'Content-Length': str(len(body)),
        'X-Hub-Signature-256': 'ok',
        'X-GitHub-Event': 'ping',
    }
    handler.rfile = io.BytesIO(body)
    with patch.object(scan_mod, 'GIT_SYNC_MANAGER', dummy), patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}):
        handler.do_POST()
    assert resp.status_code == 202
    assert resp.json['ignored'] is True

    handler, resp = _make_handler('/api/sync/webhook')
    body = b'{"ref":"refs/heads/release"}'
    handler.headers = {
        'Content-Length': str(len(body)),
        'X-Hub-Signature-256': 'ok',
        'X-GitHub-Event': 'push',
    }
    handler.rfile = io.BytesIO(body)
    with patch.object(scan_mod, 'GIT_SYNC_MANAGER', dummy), patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}):
        handler.do_POST()
    assert resp.status_code == 202
    assert resp.json['ignored'] is True


def test_sync_toggle_routes_to_requested_manager():
    class DummyToggleManager:
        def __init__(self, mode):
            self.mode = mode
            self.enabled = False
            self.calls = []

        def is_enabled(self):
            return self.enabled

        def set_enabled(self, enabled):
            self.enabled = bool(enabled)
            self.calls.append(self.enabled)
            return True

        def get_status_snapshot(self):
            return {
                'enabled': self.enabled,
                'mode': self.mode,
                'state': 'idle' if self.enabled else 'disabled',
                'ahead': 0,
                'behind': 0,
            }

    git_mgr = DummyToggleManager('desktop')
    handler, resp = _make_handler('/api/sync/toggle')
    body = json.dumps({'target': 'git', 'enabled': True}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = io.BytesIO(body)
    with (
        patch.object(scan_mod, 'GIT_SYNC_MANAGER', git_mgr),
        patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}),
        patch.object(scan_mod.Handler, '_state_change_guard', return_value=True),
    ):
        handler.do_POST()
    assert resp.status_code == 200
    assert resp.json['target'] == 'git'
    assert git_mgr.calls == [True]
    assert resp.json['status']['managers']['git']['enabled'] is True
    assert 'claude' not in resp.json['status']['managers']

    handler, resp = _make_handler('/api/sync/toggle')
    body = json.dumps({'target': 'claude', 'enabled': True}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = io.BytesIO(body)
    with (
        patch.object(scan_mod, 'GIT_SYNC_MANAGER', git_mgr),
        patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}),
        patch.object(scan_mod.Handler, '_state_change_guard', return_value=True),
    ):
        handler.do_POST()
    assert resp.status_code == 400
    assert resp.json['error'] == 'unknown sync target'


def test_sync_toggle_rejects_unknown_target():
    handler, resp = _make_handler('/api/sync/toggle')
    body = json.dumps({'target': 'shell', 'enabled': True}).encode('utf-8')
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = io.BytesIO(body)
    with (
        patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}),
        patch.object(scan_mod.Handler, '_state_change_guard', return_value=True),
    ):
        handler.do_POST()
    assert resp.status_code == 400
    assert resp.json['ok'] is False


def test_request_reconcile_retries_until_sync_lock_is_available():
    with tempfile.TemporaryDirectory(prefix='git_sync_reconcile_') as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        calls = []

        def fake_inbound(reason):
            calls.append(reason)
            return True

        with patch.object(mgr, '_perform_inbound_sync', side_effect=fake_inbound):
            mgr._sync_lock.acquire()
            try:
                assert mgr.request_reconcile('webhook') is True
                time.sleep(0.3)
                assert calls == []
            finally:
                mgr._sync_lock.release()
            deadline = time.time() + 2
            while time.time() < deadline and not calls:
                time.sleep(0.05)
            assert calls == ['webhook']
            mgr.stop()


def test_fetch_uses_upstream_remote_not_preferred_remote():
    with tempfile.TemporaryDirectory(prefix='git_sync_remote_') as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        mgr = git_sync.GitSyncManager(
            repo,
            config={'enabled': True, 'preferred_remote': 'origin'},
            observer_factory=_observer_factory,
        )
        mgr._git_dir = mgr._resolve_git_dir()
        commands = []
        real_run_git = git_sync._run_git

        def fake_run_git(repo_root, *args, **kwargs):
            commands.append(args)
            if args[:4] == ('fetch', '--prune', 'backup'):
                return type('Proc', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()
            return real_run_git(repo_root, *args, **kwargs)

        with patch.object(mgr, '_git_output') as fake_output, patch.object(git_sync, '_run_git', side_effect=fake_run_git):
            fake_output.side_effect = lambda *args, **kwargs: {
                ('branch', '--show-current'): 'main',
                ('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'): 'backup/main',
            }.get(args, '')
            assert mgr._perform_inbound_sync('test') is False
        assert ('fetch', '--prune', 'backup') in commands
        assert ('fetch', '--prune', 'origin') not in commands


def test_deleted_task_path_still_contributes_task_id_to_commit_body():
    with tempfile.TemporaryDirectory(prefix='git_sync_deleted_task_') as tmp:
        repo = Path(tmp)
        task_path = _init_repo(repo)
        task_rel = str(task_path.relative_to(repo))
        task_path.unlink()
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True}, observer_factory=_observer_factory)
        entries = [{'path': task_rel, 'orig_path': None, 'code': ' D'}]
        subject, body = mgr._compose_commit_message(entries, 'main', 'origin/main', [])
        assert subject.startswith('chore(auto-sync): batch-')
        assert 'task_ids: HER-1' in body


def test_start_auto_sets_upstream_when_enabled():
    with tempfile.TemporaryDirectory(prefix='git_sync_start_no_upstream_') as tmp:
        repo = Path(tmp)
        remote = repo.parent / f'{repo.name}-remote.git'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        _init_repo(repo)
        subprocess.run(['git', 'branch', '-M', 'main'], cwd=repo, check=True)
        subprocess.run(['git', 'remote', 'add', 'origin', str(remote)], cwd=repo, check=True)
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True}, observer_factory=_observer_factory)
        mgr.start()
        snapshot = mgr.get_status_snapshot()
        assert snapshot['state'] in ('idle', 'pending')
        assert snapshot['watcher_status'] == 'watching'
        assert snapshot['upstream'] == 'origin/main'
        mgr.stop()


def test_start_disables_sync_when_branch_has_no_upstream_and_auto_set_disabled():
    with tempfile.TemporaryDirectory(prefix='git_sync_start_no_upstream_disabled_') as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        mgr = git_sync.GitSyncManager(
            repo,
            config={'enabled': True, 'auto_set_upstream': False},
            observer_factory=_observer_factory,
        )
        mgr.start()
        snapshot = mgr.get_status_snapshot()
        assert snapshot['state'] == 'error'
        assert snapshot['watcher_status'] == 'error'
        assert snapshot['last_error'] == '当前分支没有 upstream，自动同步已停用'


def test_stop_flushes_pending_changes_without_push():
    with tempfile.TemporaryDirectory(prefix='git_sync_stop_flush_') as tmp:
        repo = Path(tmp)
        task_path = _init_repo(repo)
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True, 'debounce_seconds': 60}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        task_path.write_text(task_path.read_text(encoding='utf-8') + '\nshutdown change\n', encoding='utf-8')
        mgr.request_flush('test-stop')
        mgr.stop()
        log = subprocess.run(['git', 'log', '--oneline', '-n', '2'], cwd=repo, capture_output=True, text=True, check=True).stdout
        status = subprocess.run(['git', 'status', '--short'], cwd=repo, capture_output=True, text=True, check=True).stdout
        assert 'chore(auto-sync): batch-' in log
        assert status.strip() == ''


def test_flush_retries_after_sync_lock_is_released():
    with tempfile.TemporaryDirectory(prefix='git_sync_flush_retry_') as tmp:
        repo = Path(tmp)
        task_path = _init_repo_with_upstream(repo)
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True, 'debounce_seconds': 0.2}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        task_path.write_text(task_path.read_text(encoding='utf-8') + '\nretry change\n', encoding='utf-8')
        try:
            mgr._sync_lock.acquire()
            try:
                mgr.request_flush('busy')
                time.sleep(0.35)
            finally:
                mgr._sync_lock.release()
            deadline = time.time() + 3
            while time.time() < deadline:
                snapshot = mgr.get_status_snapshot()
                if snapshot.get('last_push') and snapshot.get('pending_files_count') == 0 and snapshot.get('state') == 'idle':
                    break
                time.sleep(0.05)
            snapshot = mgr.get_status_snapshot()
            assert snapshot['last_commit'] is not None
            assert snapshot['last_push'] is not None
            assert snapshot['pending_files_count'] == 0
            assert snapshot['state'] == 'idle'
        finally:
            mgr.stop()


def test_successful_push_resets_state_to_idle():
    with tempfile.TemporaryDirectory(prefix='git_sync_state_reset_') as tmp:
        repo = Path(tmp)
        task_path = _init_repo_with_upstream(repo)
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        task_path.write_text(task_path.read_text(encoding='utf-8') + '\nstate reset\n', encoding='utf-8')
        try:
            assert mgr.flush_now('state-test') is True
            snapshot = mgr.get_status_snapshot()
            assert snapshot['state'] == 'idle'
            assert snapshot['pending_files_count'] == 0
        finally:
            mgr.stop()


def test_stop_does_not_block_when_sync_lock_is_busy():
    with tempfile.TemporaryDirectory(prefix='git_sync_stop_busy_') as tmp:
        repo = Path(tmp)
        task_path = _init_repo(repo)
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True, 'debounce_seconds': 60}, observer_factory=_observer_factory)
        mgr._git_dir = mgr._resolve_git_dir()
        task_path.write_text(task_path.read_text(encoding='utf-8') + '\nbusy stop\n', encoding='utf-8')
        mgr.request_flush('busy-stop')
        mgr._sync_lock.acquire()
        try:
            started = time.time()
            mgr.stop()
            elapsed = time.time() - started
        finally:
            mgr._sync_lock.release()
        assert elapsed < 1.0


def test_should_handle_github_push_requires_push_event_and_matching_branch():
    with tempfile.TemporaryDirectory(prefix='git_sync_webhook_filter_') as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        subprocess.run(['git', 'branch', '-M', 'main'], cwd=repo, check=True)
        mgr = git_sync.GitSyncManager(repo, config={'enabled': True}, observer_factory=_observer_factory)
        assert mgr.should_handle_github_push('push', b'{"ref":"refs/heads/main"}') == (True, None)
        allowed, reason = mgr.should_handle_github_push('ping', b'{"ref":"refs/heads/main"}')
        assert allowed is False
        assert reason == 'ignored non-push event'
        allowed, reason = mgr.should_handle_github_push('push', b'{"ref":"refs/heads/release"}')
        assert allowed is False
        assert reason == 'ignored push for refs/heads/release'


def _make_handler(path):
    response = type('Resp', (), {'status_code': None, 'json': None})()

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {}

        def send_response(self, code, message=None):
            response.status_code = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

        def _json(self, data, code=200):
            response.status_code = code
            response.json = data

        def send_error(self, code, message=None):
            response.status_code = code
            response.json = {'ok': False, 'error': message or 'Not Found'}

    return TestHandler(), response
