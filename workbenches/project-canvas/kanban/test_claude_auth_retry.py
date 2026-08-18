#!/usr/bin/env python3
"""Claude CLI 鉴权失败自动重试：失败判定 + 重试触发路径。

背景：OAuth token 过期叠加多实例并发刷新竞态时，claude --print 会以
"Failed to authenticate. API Error: 403 Request not allowed" 退出（exit 1），
按 30s/60s 退避重试两次。_run_cli / _run_cli_resume 共用同一策略。
"""

import json
from pathlib import Path
from unittest.mock import patch

import importlib.util

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _parsed(content):
    return {'content': content, 'session_id': None, 'model': None,
            'input_tokens': None, 'output_tokens': None}


class TestIsClaudeAuthFailure:
    def test_403_request_not_allowed_in_stdout(self):
        out = 'Failed to authenticate. API Error: 403 Request not allowed'
        assert scan_mod._is_claude_auth_failure(_parsed(out), out, '')

    def test_authentication_failed_marker(self):
        assert scan_mod._is_claude_auth_failure(_parsed(''), '', 'authentication_failed')

    def test_oauth_expired_marker(self):
        msg = 'OAuth token has expired'
        assert scan_mod._is_claude_auth_failure(_parsed(msg), msg, '')

    def test_normal_error_not_matched(self):
        msg = '执行超时或其他普通错误'
        assert not scan_mod._is_claude_auth_failure(_parsed(msg), msg, '')

    def test_session_not_found_not_matched(self):
        msg = 'No conversation found with session ID xxx'
        assert not scan_mod._is_claude_auth_failure(_parsed(msg), msg, '')


class _FakeSemaphore:
    def release(self):
        pass


class _FakeProc:
    """按 results 顺序返回子进程结果。"""
    _calls = []

    def __init__(self, results):
        self._results = results
        self.pid = 12345

    def communicate(self, input=None, timeout=None):
        returncode, stdout = self._results[len(type(self)._calls)]
        type(self)._calls.append(returncode)
        self.returncode = returncode
        return stdout, ''


class TestRunCliAuthRetry:
    def test_run_cli_retries_twice_with_backoff_then_succeeds(self, tmp_path):
        task = tmp_path / 'card.md'
        task.write_text('---\ntitle: t\n---\nbody', encoding='utf-8')

        fail_out = json.dumps({
            'type': 'result', 'is_error': True,
            'result': 'Failed to authenticate. API Error: 403 Request not allowed',
            'session_id': 'sess-fail',
        })
        ok_out = json.dumps({
            'type': 'result', 'is_error': False,
            'result': 'ok', 'session_id': 'sess-ok',
        })
        _FakeProc._calls = []
        results = [(1, fail_out), (1, fail_out), (0, ok_out)]
        updates = []

        def fake_popen(*args, **kwargs):
            return _FakeProc(results)

        with patch.object(scan_mod.subprocess, 'Popen', side_effect=fake_popen), \
             patch.object(scan_mod.time, 'sleep') as fake_sleep, \
             patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
             patch.object(scan_mod, 'CLI_COMMANDS', {'claude': ['claude', '--print']}), \
             patch.object(scan_mod, 'resolve_workdir', lambda w, t: (tmp_path, None)), \
             patch.object(scan_mod, '_coerce_workdir_to_cwd', lambda p: (tmp_path, None)), \
             patch.object(scan_mod, '_queue_get_entry', lambda rid: {'status': 'running'}), \
             patch.object(scan_mod, '_queue_update_entry',
                          lambda rid, fields, **kw: updates.append(fields)), \
             patch.object(scan_mod, '_queue_append_message', lambda rid, msg: None), \
             patch.object(scan_mod, '_ai_run_is_killed', lambda rid: False), \
             patch.object(scan_mod, '_queue_consume_next', lambda: None), \
             patch.object(scan_mod, '_ai_semaphore', _FakeSemaphore()):
            scan_mod._run_cli('rid-1', 'card.md', 'claude', 'prompt')

        assert _FakeProc._calls == [1, 1, 0], '应在连续鉴权失败后退避重试两次'
        assert [call.args[0] for call in fake_sleep.call_args_list] == [30, 60]
        final = [u for u in updates if u.get('status')]
        assert final and final[-1]['status'] == 'completed'
        assert final[-1]['session_id'] == 'sess-ok'

    def test_run_cli_no_retry_for_plain_error(self, tmp_path):
        task = tmp_path / 'card.md'
        task.write_text('---\ntitle: t\n---\nbody', encoding='utf-8')

        err_out = json.dumps({'type': 'result', 'is_error': True, 'result': '普通失败'})
        _FakeProc._calls = []
        results = [(1, err_out), (0, err_out)]
        updates = []

        with patch.object(scan_mod.subprocess, 'Popen',
                          side_effect=lambda *a, **k: _FakeProc(results)), \
             patch.object(scan_mod.time, 'sleep') as fake_sleep, \
             patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
             patch.object(scan_mod, 'CLI_COMMANDS', {'claude': ['claude', '--print']}), \
             patch.object(scan_mod, 'resolve_workdir', lambda w, t: (tmp_path, None)), \
             patch.object(scan_mod, '_coerce_workdir_to_cwd', lambda p: (tmp_path, None)), \
             patch.object(scan_mod, '_queue_get_entry', lambda rid: {'status': 'running'}), \
             patch.object(scan_mod, '_queue_update_entry',
                          lambda rid, fields, **kw: updates.append(fields)), \
             patch.object(scan_mod, '_queue_append_message', lambda rid, msg: None), \
             patch.object(scan_mod, '_ai_run_is_killed', lambda rid: False), \
             patch.object(scan_mod, '_queue_consume_next', lambda: None), \
             patch.object(scan_mod, '_ai_semaphore', _FakeSemaphore()):
            scan_mod._run_cli('rid-2', 'card.md', 'claude', 'prompt')

        assert _FakeProc._calls == [1], '普通错误不应重试'
        fake_sleep.assert_not_called()
        final = [u for u in updates if u.get('status')]
        assert final and final[-1]['status'] == 'error'
        assert final[-1]['error'] == '普通失败'

    def test_real_failing_tool_surfaces_stdout_reason(self, tmp_path):
        task = tmp_path / 'card.md'
        task.write_text('---\ntitle: t\n---\nbody', encoding='utf-8')
        tool = tmp_path / 'fake-claude'
        tool.write_text(
            '#!/bin/sh\n'
            "printf '%s\\n' '{\"type\":\"result\",\"is_error\":true,\"result\":\"ROOT_CAUSE_FROM_STDOUT\"}'\n"
            'exit 1\n',
            encoding='utf-8',
        )
        tool.chmod(0o755)
        updates = []

        with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
             patch.object(scan_mod, 'CLI_COMMANDS', {'claude': [str(tool)]}), \
             patch.object(scan_mod, 'resolve_workdir', lambda w, t: (tmp_path, None)), \
             patch.object(scan_mod, '_coerce_workdir_to_cwd', lambda p: (tmp_path, None)), \
             patch.object(scan_mod, '_queue_get_entry', lambda rid: {'status': 'running'}), \
             patch.object(scan_mod, '_queue_update_entry',
                          lambda rid, fields, **kw: updates.append(fields)), \
             patch.object(scan_mod, '_ai_run_is_killed', lambda rid: False), \
             patch.object(scan_mod, '_queue_consume_next', lambda: None), \
             patch.object(scan_mod, '_ai_semaphore', _FakeSemaphore()):
            scan_mod._run_cli('rid-real-failure', 'card.md', 'claude', 'prompt')

        final = [u for u in updates if u.get('status')]
        assert final[-1]['status'] == 'error'
        assert final[-1]['error'] == 'ROOT_CAUSE_FROM_STDOUT'
        assert final[-1]['error'] != 'Exit code 1'
