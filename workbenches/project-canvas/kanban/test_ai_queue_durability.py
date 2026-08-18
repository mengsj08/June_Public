#!/usr/bin/env python3
"""KAN-1597: AI 队列运行账落盘与重启孤儿对账回归。"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('scan_docs_queue_durability', HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan_mod)


def _task(tmp_path):
    rel = 'project/Test/KAN-1597.md'
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text('---\ntitle: durability\nstatus: in-progress\n---\n', encoding='utf-8')
    return rel


def _write_running_queue(tmp_path, rel, *, status='running'):
    entry = {
        'id': 'run1597',
        'tool': 'codex',
        'path': rel,
        'workdir': str(tmp_path),
        'status': status,
        'read': False,
        'order': 0,
        'pid': 43210,
        'pid_started_at': 'Fri Aug 14 10:00:00 2026',
        'timestamp': '2026-08-14T10:00:00',
        'started_at': '2026-08-14T10:00:00',
        'completed_at': None,
        'duration_ms': None,
        'output': None,
        'error': None,
        'session_id': None,
        'session_valid': True,
        'messages': [],
        'title': None,
        'prompt_length': 87,
        'output_length': 0,
        'ai_profile': 'execute_codex',
        'metadata': {'origin': 'task_detail'},
    }
    (tmp_path / '.ai-queue.json').write_text(
        json.dumps({'concurrency': 3, 'entries': [entry]}, ensure_ascii=False),
        encoding='utf-8',
    )
    return entry


def test_queue_runtime_fields_are_atomically_persisted(tmp_path):
    rel = _task(tmp_path)
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'AI_MAX_CONCURRENT', 3), \
         patch.object(scan_mod.os, 'replace', wraps=scan_mod.os.replace) as replace:
        run_id = scan_mod._queue_add_entry(
            'codex', rel, str(tmp_path),
            metadata={'origin': 'task_detail'},
            ai_profile='execute_codex',
        )
        scan_mod._queue_update_entry(run_id, {
            'status': 'running',
            'pid': 43210,
            'started_at': '2026-08-14T10:00:00',
            'prompt_length': 87,
        })

    persisted = json.loads((tmp_path / '.ai-queue.json').read_text(encoding='utf-8'))['entries'][0]
    assert replace.call_count >= 2
    assert not list(tmp_path.glob('.ai-queue.json.*.tmp'))
    assert persisted['id'] == run_id
    assert persisted['path'] == rel
    assert persisted['tool'] == 'codex'
    assert persisted['pid'] == 43210
    assert persisted['prompt_length'] == 87
    assert persisted['started_at'] == '2026-08-14T10:00:00'
    assert persisted['ai_profile'] == 'execute_codex'
    assert persisted['metadata'] == {'origin': 'task_detail'}


def test_restart_marks_live_pid_as_orphaned_running(tmp_path):
    rel = _task(tmp_path)
    original = _write_running_queue(tmp_path, rel)
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod.server_instance, 'process_matches_started_at', return_value=True), \
         patch.object(scan_mod, '_queue_consume_next'):
        scan_mod._recover_queue()

    recovered = json.loads((tmp_path / '.ai-queue.json').read_text(encoding='utf-8'))['entries'][0]
    assert recovered['status'] == 'orphaned-running'
    assert recovered['pid'] == original['pid']
    assert recovered['prompt_length'] == original['prompt_length']
    assert recovered['ai_profile'] == original['ai_profile']
    assert recovered['metadata'] == original['metadata']
    assert recovered['recovery_state'] == 'pid-still-running-output-detached'
    assert '输出管道已断' in recovered['error']


def test_restart_marks_exited_pid_as_orphaned_unknown(tmp_path):
    rel = _task(tmp_path)
    original = _write_running_queue(tmp_path, rel)
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod.server_instance, 'process_matches_started_at', return_value=False), \
         patch.object(scan_mod, '_queue_consume_next'):
        scan_mod._recover_queue()

    recovered = json.loads((tmp_path / '.ai-queue.json').read_text(encoding='utf-8'))['entries'][0]
    assert recovered['status'] == 'orphaned-unknown'
    assert recovered['pid'] == original['pid']
    assert recovered['completed_at']
    assert recovered['recovery_state'] == 'pid-exited-output-unknown'
    assert '最终结果未知' in recovered['error']


def test_restart_reconciles_running_ledger_even_if_task_path_disappeared(tmp_path):
    rel = 'project/Test/missing-after-restart.md'
    _write_running_queue(tmp_path, rel)
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod.server_instance, 'process_matches_started_at', return_value=True), \
         patch.object(scan_mod, '_queue_consume_next'):
        scan_mod._recover_queue()

    recovered = json.loads((tmp_path / '.ai-queue.json').read_text(encoding='utf-8'))['entries'][0]
    assert recovered['path'] == rel
    assert recovered['status'] == 'orphaned-running'


def test_orphaned_running_becomes_terminal_after_pid_exit(tmp_path):
    rel = _task(tmp_path)
    _write_running_queue(tmp_path, rel, status='orphaned-running')
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod.server_instance, 'process_matches_started_at', return_value=False), \
         patch.object(scan_mod, '_queue_consume_next') as consume:
        changed = scan_mod._reconcile_orphaned_runs()

    recovered = json.loads((tmp_path / '.ai-queue.json').read_text(encoding='utf-8'))['entries'][0]
    assert changed is True
    assert recovered['status'] == 'orphaned-unknown'
    assert recovered['completed_at']
    assert '观察到孤儿进程已退出' in recovered['error']
    consume.assert_called_once_with()


def test_queue_ui_declares_both_orphan_states():
    modules = HERE / 'static' / 'kanban' / 'modules'
    source = '\n'.join(
        (modules / name).read_text(encoding='utf-8')
        for name in ('ai.js', 'ai-threads.js', 'ai-queue.js')
    )
    assert "'orphaned-running'" in source
    assert "'orphaned-unknown'" in source
    assert '孤儿进程 · 输出已断' in source
