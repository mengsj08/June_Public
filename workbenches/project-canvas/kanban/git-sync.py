#!/usr/bin/env python3
"""Kanban Git auto-sync runtime."""

from __future__ import annotations

import hashlib
import hmac
import json
import queue
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path


DEFAULT_AUTO_COMMIT_PREFIXES = ('project/',)


def _now():
    return datetime.now().astimezone()


def _iso_now():
    return _now().isoformat(timespec='seconds')


def _run_git(repo_root, *args, input_text=None, check=False, text=True):
    return subprocess.run(
        ['git', *args],
        cwd=str(repo_root),
        input=input_text,
        capture_output=True,
        text=text,
        check=check,
    )


def _decode_path(raw):
    return raw.decode('utf-8', errors='surrogateescape')


def _read_repo_text(repo_root, rel_path):
    abspath = repo_root / rel_path
    if abspath.exists():
        try:
            return abspath.read_text(encoding='utf-8')
        except OSError:
            return None
    result = _run_git(repo_root, 'show', f'HEAD:{rel_path}')
    if result.returncode != 0:
        return None
    return result.stdout


def _task_ids_from_paths(repo_root, changed_items):
    task_ids = []
    seen = set()
    candidate_paths = []
    candidate_seen = set()
    for item in changed_items:
        if isinstance(item, dict):
            paths = [item.get('path'), item.get('orig_path')]
        else:
            paths = [item]
        for rel_path in paths:
            if not rel_path:
                continue
            if not rel_path.endswith('.md'):
                continue
            if rel_path in candidate_seen:
                continue
            candidate_seen.add(rel_path)
            candidate_paths.append(rel_path)
    for rel_path in candidate_paths:
        raw = _read_repo_text(repo_root, rel_path)
        if not raw:
            continue
        match = re.search(r'^\s*task_id:\s*([A-Z]+-\d+)\s*$', raw, re.MULTILINE)
        if not match:
            continue
        task_id = match.group(1)
        if task_id in seen:
            continue
        seen.add(task_id)
        task_ids.append(task_id)
    return task_ids


class GitSyncManager:
    def __init__(self, repo_root, config=None, observer_factory=None, task_id_extractor=None, logger=None):
        self.repo_root = Path(repo_root).resolve()
        self.config = dict(config or {})
        self.enabled = bool(self.config.get('enabled', False))
        self.mode = self.config.get('mode') or 'desktop'
        self.debounce_seconds = max(float(self.config.get('debounce_seconds', 15) or 15), 0.1)
        self.desktop_poll_seconds = max(float(self.config.get('desktop_poll_seconds', 30) or 30), 1)
        self.git_lock_wait_seconds = max(float(self.config.get('git_lock_wait_seconds', 3) or 0), 0)
        self.preferred_remote = self.config.get('preferred_remote') or 'origin'
        self.auto_set_upstream = bool(self.config.get('auto_set_upstream', True))
        self.warn_large_file_mb = float(self.config.get('warn_large_file_mb', 10) or 10)
        self.webhook_secret = str(self.config.get('webhook_secret') or '')
        self.auto_commit_prefixes = self._normalize_auto_commit_prefixes(
            self.config.get('auto_commit_prefixes')
        )
        self._observer_factory = observer_factory
        self._task_id_extractor = task_id_extractor or _task_ids_from_paths
        self._logger = logger or (lambda message: None)
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._timer = None
        self._observer = None
        self._poll_thread = None
        self._reconcile_thread = None
        self._stop_event = threading.Event()
        self._subscribers = set()
        self._git_dir = None
        self._fatal = False
        self._reconcile_requested = False
        self._reconcile_reason = None
        self._config_path = self.repo_root / '.kanban.config.json'
        self._status = {
            'enabled': self.enabled,
            'mode': self.mode,
            'state': 'disabled' if not self.enabled else 'idle',
            'branch': None,
            'upstream': None,
            'remote': self.preferred_remote,
            'watcher_status': 'disabled' if not self.enabled else 'starting',
            'pending_files_count': 0,
            'pending_paths': [],
            'manual_review_files_count': 0,
            'manual_review_paths': [],
            'auto_commit_prefixes': list(self.auto_commit_prefixes),
            'ahead': 0,
            'behind': 0,
            'last_commit': None,
            'last_push': None,
            'last_pull': None,
            'last_error': None,
            'last_warning': None,
            'updated_at': _iso_now(),
        }

    @staticmethod
    def _normalize_auto_commit_prefixes(value):
        raw = value if isinstance(value, list) else list(DEFAULT_AUTO_COMMIT_PREFIXES)
        prefixes = []
        for item in raw:
            prefix = str(item or '').strip().replace('\\', '/')
            if not prefix or prefix.startswith('/') or '..' in prefix.split('/'):
                continue
            prefix = prefix.lstrip('./').rstrip('/') + '/'
            if prefix not in prefixes:
                prefixes.append(prefix)
        return tuple(prefixes or DEFAULT_AUTO_COMMIT_PREFIXES)

    def _path_is_auto_commit(self, rel_path):
        path = str(rel_path or '').replace('\\', '/').lstrip('./')
        return any(path == prefix.rstrip('/') or path.startswith(prefix) for prefix in self.auto_commit_prefixes)

    def _event_path_is_auto_commit(self, path):
        if not path:
            return False
        try:
            rel_path = Path(path).resolve().relative_to(self.repo_root).as_posix()
        except (OSError, ValueError):
            return False
        return self._path_is_auto_commit(rel_path)

    def _schedule_flush_unlocked(self, reason, delay):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(delay, self._flush_from_timer, args=(reason,))
        self._timer.daemon = True
        self._timer.start()

    def start(self):
        with self._lock:
            if not self.enabled:
                self._status['watcher_status'] = 'disabled'
                self._status['state'] = 'disabled'
                self._status['updated_at'] = _iso_now()
                self._emit('status')
                return
            git_dir = self._resolve_git_dir()
            if not git_dir:
                self._mark_error('当前目录不是可写 Git 仓库', fatal=True)
                return
            self._git_dir = git_dir
            self._refresh_status_snapshot()
            setup_error = self._sync_setup_error(
                self._status.get('branch'),
                self._status.get('upstream'),
            )
            if setup_error:
                self._status['watcher_status'] = 'error'
                self._mark_error(setup_error, fatal=True)
                return
            observer, watcher_error = self._build_observer()
            if watcher_error:
                self._status['watcher_status'] = 'error'
                self._mark_error(watcher_error, fatal=True)
                return
            self._observer = observer
            self._observer.start()
            self._status['watcher_status'] = 'watching'
            self._emit('status')
            if self.mode == 'desktop':
                self._poll_thread = threading.Thread(target=self._desktop_poll_loop, daemon=True)
                self._poll_thread.start()
            if self._status['pending_files_count'] > 0 or self._status['ahead'] > 0:
                self.request_flush('startup')

    def stop(self):
        self._stop_event.set()
        with self._lock:
            had_timer = self._timer is not None
            if had_timer:
                self._timer.cancel()
                self._timer = None
        if self._observer:
            try:
                self._observer.stop()
            except Exception:
                pass
            try:
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2)
        if self._reconcile_thread and self._reconcile_thread.is_alive():
            self._reconcile_thread.join(timeout=2)
        if self.enabled and (had_timer or self._status_entries()):
            self.flush_now(
                'shutdown',
                allow_push=False,
                blocking=False,
                retry_on_busy=False,
                ignore_fatal=True,
            )

    def set_enabled(self, enabled):
        """Toggle deterministic git sync on/off. Persists to .kanban.config.json."""
        enabled = bool(enabled)
        if not self._persist_enabled(enabled):
            return False
        with self._lock:
            was_enabled = self.enabled
            self.enabled = enabled
            self._status['enabled'] = enabled
            self._status['updated_at'] = _iso_now()
            if enabled:
                self._stop_event.clear()
                self._fatal = False
                self._status['state'] = 'idle'
                self._status['watcher_status'] = 'starting'
                self._status['last_error'] = None
                self._status['last_warning'] = None
            else:
                self._status['state'] = 'disabled'
                self._status['watcher_status'] = 'disabled'
        if enabled:
            if not was_enabled:
                self.start()
            else:
                self._emit('status')
        else:
            self.stop()
            self._emit('status')
        self._log(f'{"enabled" if enabled else "disabled"}')
        return True

    def request_flush(self, reason='fs-event'):
        with self._lock:
            if not self.enabled or self._fatal or self._stop_event.is_set():
                return
            self._schedule_flush_unlocked(reason, self.debounce_seconds)
            if self._status['state'] not in ('syncing', 'error') and not str(self._status['state']).startswith('paused_'):
                self._status['state'] = 'pending'
                self._status['updated_at'] = _iso_now()
        self._refresh_status_snapshot()
        self._emit('status')

    def flush_now(self, reason='manual', allow_push=True, blocking=False, retry_on_busy=True, ignore_fatal=False):
        acquired = self._sync_lock.acquire() if blocking else self._sync_lock.acquire(blocking=False)
        if not acquired:
            if retry_on_busy:
                self._retry_flush_soon(reason)
            return False
        try:
            return self._perform_outbound_sync(reason, allow_push=allow_push, ignore_fatal=ignore_fatal)
        finally:
            self._sync_lock.release()

    def reconcile_now(self, reason='manual'):
        if not self.enabled or self._fatal:
            return False
        if not self._sync_lock.acquire(blocking=False):
            return False
        try:
            return self._perform_inbound_sync(reason)
        finally:
            self._sync_lock.release()

    def request_reconcile(self, reason='manual'):
        with self._lock:
            if not self.enabled or self._fatal or self._stop_event.is_set():
                return False
            self._reconcile_requested = True
            self._reconcile_reason = reason
            if self._reconcile_thread and self._reconcile_thread.is_alive():
                return True
            self._reconcile_thread = threading.Thread(target=self._reconcile_loop, daemon=True)
            self._reconcile_thread.start()
            return True

    def get_status_snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self._status, ensure_ascii=False))

    def subscribe(self):
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(q)
        q.put({
            'type': 'status',
            'status': self.get_status_snapshot(),
            'at': _iso_now(),
        })
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subscribers.discard(q)

    def verify_webhook_signature(self, body, signature_header):
        if not self.webhook_secret or not signature_header:
            return False
        signature_header = signature_header.strip()
        if signature_header.startswith('sha256='):
            digest = 'sha256=' + hmac.new(
                self.webhook_secret.encode('utf-8'),
                body,
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(digest, signature_header)
        return False

    def should_handle_github_push(self, event_name, body):
        if event_name != 'push':
            return False, 'ignored non-push event'
        try:
            payload = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, 'invalid JSON payload'
        branch = self._git_output('branch', '--show-current') or ''
        if not branch:
            return False, 'detached HEAD 状态下无法处理 webhook'
        payload_ref = str(payload.get('ref') or '')
        expected_ref = f'refs/heads/{branch}'
        if payload_ref != expected_ref:
            return False, f'ignored push for {payload_ref or "unknown ref"}'
        return True, None

    def _flush_from_timer(self, reason):
        with self._lock:
            self._timer = None
        self.flush_now(reason)

    def _retry_flush_soon(self, reason):
        with self._lock:
            if not self.enabled or self._stop_event.is_set():
                return
            if self._timer:
                return
            delay = min(self.debounce_seconds, 0.5)
            self._schedule_flush_unlocked(f'{reason}-retry', delay)

    def _desktop_poll_loop(self):
        while not self._stop_event.wait(self.desktop_poll_seconds):
            try:
                self.reconcile_now('desktop-poll')
            except Exception as exc:
                self._mark_error(f'desktop poll 失败: {exc}', fatal=False)

    def _reconcile_loop(self):
        while not self._stop_event.is_set():
            with self._lock:
                if not self._reconcile_requested:
                    return
                reason = self._reconcile_reason or 'manual'
            if not self._sync_lock.acquire(blocking=False):
                if self._stop_event.wait(0.2):
                    return
                continue
            try:
                with self._lock:
                    run_reason = self._reconcile_reason or reason
                    self._reconcile_requested = False
                    self._reconcile_reason = None
                self._perform_inbound_sync(run_reason)
            finally:
                self._sync_lock.release()

    def _build_observer(self):
        if self._observer_factory:
            return self._observer_factory(self), None
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return None, 'watchdog 未安装，自动同步已停用'

        manager = self

        class RepoChangeHandler(FileSystemEventHandler):
            def on_any_event(self, event):
                path = getattr(event, 'src_path', '') or ''
                dest_path = getattr(event, 'dest_path', '') or ''
                if manager._is_git_internal_path(path) or manager._is_git_internal_path(dest_path):
                    return
                if not manager._event_path_is_auto_commit(path) and not manager._event_path_is_auto_commit(dest_path):
                    return
                manager.request_flush(getattr(event, 'event_type', 'fs-event'))

        observer = Observer()
        observer.schedule(RepoChangeHandler(), str(self.repo_root), recursive=True)
        return observer, None

    def _is_git_internal_path(self, path):
        if not path:
            return False
        try:
            candidate = Path(path).resolve()
        except OSError:
            return False
        git_dir = self._git_dir or (self.repo_root / '.git')
        try:
            return candidate == git_dir or git_dir in candidate.parents
        except Exception:
            return False

    def _resolve_git_dir(self):
        result = _run_git(self.repo_root, 'rev-parse', '--git-dir')
        if result.returncode != 0:
            return None
        git_dir = result.stdout.strip()
        if not git_dir:
            return None
        path = Path(git_dir)
        if not path.is_absolute():
            path = (self.repo_root / path).resolve()
        return path

    def _refresh_status_snapshot(self, reset_state=False):
        branch = self._git_output('branch', '--show-current') or None
        upstream = self._git_output('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}', ok_empty=True) or None
        ahead, behind = self._ahead_behind(upstream)
        all_entries = self._worktree_status_entries()
        entries = [entry for entry in all_entries if self._entry_is_auto_commit(entry)]
        manual_entries = [entry for entry in all_entries if not self._entry_is_auto_commit(entry)]
        pending_paths = [self._format_entry_path(entry) for entry in entries]
        manual_paths = [self._format_entry_path(entry) for entry in manual_entries]
        with self._lock:
            self._status['branch'] = branch
            self._status['upstream'] = upstream
            self._status['pending_files_count'] = len(entries)
            self._status['pending_paths'] = pending_paths
            self._status['manual_review_files_count'] = len(manual_entries)
            self._status['manual_review_paths'] = manual_paths
            self._status['ahead'] = ahead
            self._status['behind'] = behind
            if upstream and '/' in upstream:
                self._status['remote'] = upstream.split('/', 1)[0]
            else:
                self._status['remote'] = self.preferred_remote
            if self.enabled and not self._fatal and (
                reset_state or (
                    self._status['state'] not in ('syncing', 'error') and
                    not str(self._status['state']).startswith('paused_')
                )
            ):
                if entries or ahead > 0:
                    self._status['state'] = 'pending'
                else:
                    self._status['state'] = 'idle'
            self._status['updated_at'] = _iso_now()

    def _worktree_status_entries(self):
        result = _run_git(self.repo_root, 'status', '--porcelain=v1', '--untracked-files=all', '-z', text=False)
        if result.returncode != 0:
            return []
        chunks = result.stdout.split(b'\0')
        entries = []
        idx = 0
        while idx < len(chunks):
            chunk = chunks[idx]
            idx += 1
            if not chunk:
                continue
            if len(chunk) < 4:
                continue
            code = chunk[:2].decode('utf-8', errors='replace')
            path = _decode_path(chunk[3:])
            orig_path = None
            if 'R' in code or 'C' in code:
                if idx < len(chunks):
                    orig_path = path
                    path = _decode_path(chunks[idx])
                    idx += 1
            entries.append({
                'code': code,
                'path': path,
                'orig_path': orig_path,
            })
        return entries

    def _entry_is_auto_commit(self, entry):
        paths = [entry.get('path'), entry.get('orig_path')]
        return all(self._path_is_auto_commit(path) for path in paths if path)

    def _status_entries(self):
        return [entry for entry in self._worktree_status_entries() if self._entry_is_auto_commit(entry)]

    def _staged_paths(self):
        result = _run_git(self.repo_root, 'diff', '--cached', '--name-only', '-z', text=False)
        if result.returncode != 0:
            return []
        return [_decode_path(item) for item in result.stdout.split(b'\0') if item]

    def _ahead_changed_paths(self, upstream):
        if not upstream:
            return []
        result = _run_git(self.repo_root, 'diff', '--name-only', '-z', f'{upstream}..HEAD', text=False)
        if result.returncode != 0:
            return []
        return [_decode_path(item) for item in result.stdout.split(b'\0') if item]

    @staticmethod
    def _entry_paths(entries):
        paths = []
        for entry in entries:
            for path in (entry.get('path'), entry.get('orig_path')):
                if path and path not in paths:
                    paths.append(path)
        return paths

    def _format_entry_path(self, entry):
        if entry.get('orig_path'):
            return f"{entry['orig_path']} -> {entry['path']}"
        return entry['path']

    def _git_output(self, *args, ok_empty=False):
        result = _run_git(self.repo_root, *args)
        if result.returncode != 0:
            return '' if ok_empty else None
        return result.stdout.strip()

    def _ahead_behind(self, upstream):
        if not upstream:
            return 0, 0
        result = _run_git(self.repo_root, 'rev-list', '--left-right', '--count', f'{upstream}...HEAD')
        if result.returncode != 0:
            return 0, 0
        raw = result.stdout.strip().split()
        if len(raw) != 2:
            return 0, 0
        behind = int(raw[0])
        ahead = int(raw[1])
        return ahead, behind

    def _remote_for_upstream(self, upstream):
        if upstream and '/' in upstream:
            return upstream.split('/', 1)[0]
        return self.preferred_remote

    def _sync_setup_error(self, branch, upstream):
        if not branch:
            return 'detached HEAD 状态下无法自动同步'
        if not upstream:
            if self.auto_set_upstream:
                return self._ensure_upstream(branch)
            return '当前分支没有 upstream，自动同步已停用'
        remote_name = self._remote_for_upstream(upstream)
        if not self._remote_exists(remote_name):
            return f'远端 {remote_name} 不存在，自动同步已停用'
        return None

    def _ensure_upstream(self, branch):
        remote_name = self.preferred_remote
        if not self._remote_exists(remote_name):
            return f'远端 {remote_name} 不存在，无法自动建立 upstream'
        push_result = _run_git(self.repo_root, 'push', '-u', remote_name, 'HEAD')
        if push_result.returncode != 0:
            stderr = push_result.stderr.strip() or push_result.stdout.strip()
            return stderr or f'自动建立 upstream 失败: {remote_name}/{branch}'
        self._refresh_status_snapshot(reset_state=True)
        return None

    def _manual_git_state(self):
        git_dir = self._git_dir or self._resolve_git_dir()
        if not git_dir:
            return '当前目录不是 Git 仓库'
        lock_checks = {
            git_dir / 'index.lock': '检测到 index.lock，疑似人工 Git 操作中',
            git_dir / 'HEAD.lock': '检测到 HEAD.lock，疑似正在切分支',
        }
        deadline = time.monotonic() + self.git_lock_wait_seconds
        while True:
            active_locks = [(path, message) for path, message in lock_checks.items() if path.exists()]
            if not active_locks:
                break
            if time.monotonic() >= deadline:
                return active_locks[0][1]
            time.sleep(0.1)

        state_checks = {
            git_dir / 'rebase-merge': '检测到 rebase-merge，疑似人工 rebase 中',
            git_dir / 'rebase-apply': '检测到 rebase-apply，疑似人工 rebase/apply 中',
            git_dir / 'MERGE_HEAD': '检测到 MERGE_HEAD，疑似人工 merge 中',
            git_dir / 'CHERRY_PICK_HEAD': '检测到 CHERRY_PICK_HEAD，疑似人工 cherry-pick 中',
        }
        for path, message in state_checks.items():
            if path.exists():
                return message
        return None

    def _remote_exists(self, remote_name):
        result = _run_git(self.repo_root, 'remote')
        if result.returncode != 0:
            return False
        remotes = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        return remote_name in remotes

    def _remote_branch_exists(self, remote_name, branch):
        result = _run_git(self.repo_root, 'ls-remote', '--heads', remote_name, branch)
        if result.returncode != 0:
            return False
        return bool(result.stdout.strip())

    def _warn_large_files(self, entries):
        warnings = []
        threshold_bytes = int(self.warn_large_file_mb * 1024 * 1024)
        for entry in entries:
            path = entry.get('path')
            if not path:
                continue
            abspath = self.repo_root / path
            if not abspath.exists() or not abspath.is_file():
                continue
            try:
                size = abspath.stat().st_size
            except OSError:
                continue
            if size <= threshold_bytes:
                continue
            warnings.append(
                f"large file: {path} ({size / 1024 / 1024:.1f} MB)"
            )
        return warnings

    def _compose_commit_message(self, entries, branch, upstream, warnings):
        task_ids = self._task_id_extractor(self.repo_root, entries)
        stamp = _now().strftime('%Y%m%dT%H%M%S')
        subject = f"chore(auto-sync): batch-{stamp} [{len(entries)} files]"
        body_lines = [
            f"mode: {self.mode}",
            f"branch: {branch or 'unknown'}",
            f"remote/upstream: {upstream or self.preferred_remote}",
            f"task_ids: {', '.join(task_ids) if task_ids else '-'}",
            "paths:",
        ]
        for entry in entries:
            body_lines.append(f"- {self._format_entry_path(entry)}")
        if warnings:
            body_lines.append("warnings:")
            for warning in warnings:
                body_lines.append(f"- {warning}")
        return subject, '\n'.join(body_lines)

    def _mark_error(self, message, fatal=False):
        with self._lock:
            self._status['state'] = 'error'
            self._status['last_error'] = message
            self._status['updated_at'] = _iso_now()
            if fatal:
                self._fatal = True
        self._log(message)
        self._emit('error')

    def _persist_enabled(self, val):
        try:
            if self._config_path.exists():
                raw = self._config_path.read_text(encoding='utf-8')
                cfg = json.loads(raw)
            else:
                cfg = {}
            if 'git_sync' not in cfg or not isinstance(cfg['git_sync'], dict):
                cfg['git_sync'] = {}
            cfg['git_sync']['enabled'] = bool(val)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._config_path.parent),
                prefix='.kanban.config.',
                suffix='.tmp',
                text=True,
            )
            try:
                with open(fd, 'w', encoding='utf-8') as handle:
                    json.dump(cfg, handle, ensure_ascii=False, indent=2)
                    handle.write('\n')
                Path(tmp).replace(self._config_path)
            finally:
                tmp_path = Path(tmp)
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
            return True
        except Exception as exc:
            self._log(f'persist enabled failed: {exc}')
            return False

    def _pause(self, state, message, schedule_retry=False):
        with self._lock:
            self._status['state'] = state
            self._status['last_warning'] = message
            self._status['updated_at'] = _iso_now()
        self._log(message)
        self._emit('paused')
        if schedule_retry:
            self.request_flush(state)

    def _perform_outbound_sync(self, reason, allow_push=True, ignore_fatal=False):
        if not self.enabled or (self._fatal and not ignore_fatal):
            return False
        manual_state = self._manual_git_state()
        if manual_state:
            self._pause('paused_manual_git', manual_state, schedule_retry=True)
            return False
        branch = self._git_output('branch', '--show-current') or ''
        if not branch:
            self._mark_error('detached HEAD 状态下无法自动同步', fatal=True)
            return False
        entries = self._status_entries()
        staged_outside_scope = [path for path in self._staged_paths() if not self._path_is_auto_commit(path)]
        if staged_outside_scope:
            self._pause(
                'paused_manual_git',
                '暂存区包含需人工审阅的非任务数据，自动提交已跳过',
                schedule_retry=False,
            )
            return False
        self._refresh_status_snapshot()
        current_upstream = self.get_status_snapshot().get('upstream')
        ahead = self.get_status_snapshot().get('ahead', 0)
        if allow_push:
            setup_error = self._sync_setup_error(branch, current_upstream)
            if setup_error:
                self._mark_error(setup_error, fatal=True)
                return False
        if not entries and (not allow_push or ahead == 0):
            self._emit('status')
            return False
        with self._lock:
            self._status['state'] = 'syncing'
            self._status['last_error'] = None
            self._status['last_warning'] = None
            self._status['updated_at'] = _iso_now()
        self._emit('status')
        warnings = self._warn_large_files(entries)
        if warnings:
            with self._lock:
                self._status['last_warning'] = '; '.join(warnings)
        if entries:
            add_result = _run_git(self.repo_root, 'add', '-A', '--', *self._entry_paths(entries))
            if add_result.returncode != 0:
                self._mark_error(add_result.stderr.strip() or 'git add 失败')
                return False
            staged = _run_git(self.repo_root, 'diff', '--cached', '--name-only')
            if staged.returncode != 0:
                self._mark_error(staged.stderr.strip() or 'git diff --cached 失败')
                return False
            if staged.stdout.strip():
                subject, body = self._compose_commit_message(entries, branch, current_upstream, warnings)
                commit_result = _run_git(self.repo_root, 'commit', '-m', subject, '-m', body)
                if commit_result.returncode != 0:
                    stderr = commit_result.stderr.strip()
                    if 'nothing to commit' not in stderr.lower():
                        self._mark_error(stderr or 'git commit 失败')
                        return False
                else:
                    head = self._git_output('rev-parse', 'HEAD')
                    with self._lock:
                        self._status['last_commit'] = {
                            'hash': head,
                            'subject': subject,
                            'at': _iso_now(),
                            'reason': reason,
                        }
        if not allow_push:
            self._refresh_status_snapshot(reset_state=True)
            self._emit('status')
            return True
        ahead_outside_scope = [
            path for path in self._ahead_changed_paths(current_upstream)
            if not self._path_is_auto_commit(path)
        ]
        if ahead_outside_scope:
            self._pause(
                'paused_manual_git',
                '待推送提交包含需人工审阅的非任务数据，自动推送已跳过',
                schedule_retry=False,
            )
            return False
        fetch_remote = self._remote_for_upstream(current_upstream)
        fetch_result = _run_git(self.repo_root, 'fetch', '--prune', fetch_remote)
        if fetch_result.returncode != 0:
            self._mark_error(fetch_result.stderr.strip() or 'git fetch 失败')
            self.request_flush('fetch-error')
            return False
        upstream = self._git_output('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}', ok_empty=True) or None
        remote_ref = upstream
        if remote_ref:
            ahead, behind = self._ahead_behind(remote_ref)
            if behind > 0:
                rebase_result = _run_git(self.repo_root, 'rebase', remote_ref)
                if rebase_result.returncode != 0:
                    _run_git(self.repo_root, 'rebase', '--abort')
                    self._pause('paused_conflict', 'git rebase 冲突，已自动 abort，等待人工处理', schedule_retry=False)
                    return False
        push_args = ['push']
        push_result = _run_git(self.repo_root, *push_args)
        if push_result.returncode != 0:
            self._mark_error(push_result.stderr.strip() or 'git push 失败')
            self.request_flush('push-error')
            return False
        self._refresh_status_snapshot(reset_state=True)
        snapshot = self.get_status_snapshot()
        with self._lock:
            self._status['last_push'] = {
                'at': _iso_now(),
                'branch': snapshot.get('branch'),
                'upstream': snapshot.get('upstream'),
            }
        self._emit('pushed')
        self._emit('status')
        if self.get_status_snapshot().get('pending_files_count', 0) > 0:
            self.request_flush('post-push-pending')
        return True

    def _perform_inbound_sync(self, reason):
        if not self.enabled or self._fatal:
            return False
        manual_state = self._manual_git_state()
        if manual_state:
            self._pause('paused_manual_git', manual_state, schedule_retry=False)
            return False
        branch = self._git_output('branch', '--show-current') or ''
        if not branch:
            self._mark_error('detached HEAD 状态下无法拉取远端变更', fatal=True)
            return False
        upstream = self._git_output('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}', ok_empty=True) or None
        if not upstream:
            self._refresh_status_snapshot()
            self._emit('status')
            return False
        fetch_remote = self._remote_for_upstream(upstream)
        fetch_result = _run_git(self.repo_root, 'fetch', '--prune', fetch_remote)
        if fetch_result.returncode != 0:
            self._mark_error(fetch_result.stderr.strip() or 'git fetch 失败')
            return False
        self._refresh_status_snapshot()
        snapshot = self.get_status_snapshot()
        if snapshot.get('behind', 0) == 0:
            self._emit('status')
            return False
        if self._worktree_status_entries():
            with self._lock:
                self._status['last_warning'] = '工作区存在未提交变更，跳过自动 pull'
                self._status['state'] = 'pending'
                self._status['updated_at'] = _iso_now()
            self._emit('status')
            return False
        with self._lock:
            self._status['state'] = 'syncing'
            self._status['last_error'] = None
            self._status['last_warning'] = None
            self._status['updated_at'] = _iso_now()
        self._emit('status')
        rebase_result = _run_git(self.repo_root, 'rebase', upstream)
        if rebase_result.returncode != 0:
            _run_git(self.repo_root, 'rebase', '--abort')
            self._pause('paused_conflict', '远端拉取触发 rebase 冲突，已自动 abort', schedule_retry=False)
            return False
        self._refresh_status_snapshot(reset_state=True)
        snapshot = self.get_status_snapshot()
        with self._lock:
            self._status['last_pull'] = {
                'at': _iso_now(),
                'branch': snapshot.get('branch'),
                'upstream': snapshot.get('upstream'),
                'reason': reason,
            }
        self._emit('pulled')
        self._emit('status')
        return True

    def _log(self, message):
        self._logger(f'[git-sync] {message}')

    def _emit(self, event_type):
        payload = {
            'type': event_type,
            'status': self.get_status_snapshot(),
            'at': _iso_now(),
        }
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except queue.Full:
                pass
