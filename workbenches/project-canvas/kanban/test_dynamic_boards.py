#!/usr/bin/env python3
"""Tests for dynamic board providers."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _provider_config(tmp_path, *, provider=None):
    workdir = tmp_path / 'work'
    workdir.mkdir()
    output = workdir / 'out.html'
    state = workdir / 'state.json'
    log = workdir / 'run.log'
    base = {
        'id': 'demo',
        'title': 'Demo',
        'workdir': str(workdir),
        'command': [sys.executable, '-c', 'from pathlib import Path; Path("out.html").write_text("ok"); Path("state.json").write_text("{\\"generated_at\\": \\"2026-06-11T00:00:00+00:00\\", \\"ok\\": true, \\"summary\\": \\"ok\\", \\"sources\\": [{\\"name\\": \\"test\\", \\"as_of\\": \\"2026-06-11T00:00:00+00:00\\"}], \\"stages\\": {}}")'],
        'env': {'PYTHONUNBUFFERED': '1'},
        'timeout_seconds': 10,
        'freshness_days': 7,
        'surfaces': ['test'],
        'artifacts': {
            'output_path': str(output),
            'state_path': str(state),
            'log_path': str(log),
            'stdout_excerpt_chars': 2000,
            'stderr_excerpt_chars': 2000,
        },
    }
    if provider:
        base.update(provider)
    return {'open_allowed_roots': [str(tmp_path)], 'dynamic_boards': [base]}, base


def test_unknown_provider_id_returns_404(tmp_path):
    cfg, _ = _provider_config(tmp_path)
    result, status = scan_mod.run_dynamic_board('missing', cfg)
    assert status == 404
    assert result['ok'] is False


def test_missing_env_rejects_provider(tmp_path):
    cfg, provider = _provider_config(tmp_path)
    provider.pop('env')
    result, status = scan_mod.run_dynamic_board('demo', cfg)
    assert status == 400
    assert 'env' in result['error']


def test_rejects_workdir_outside_allowed_roots(tmp_path):
    outside = tmp_path.parent / f'{tmp_path.name}-outside'
    outside.mkdir()
    cfg, provider = _provider_config(tmp_path, provider={'workdir': str(outside)})
    result = scan_mod.get_dynamic_boards(cfg)
    assert result['providers'][0]['ok'] is False
    assert 'workdir 不在可信根内' in result['providers'][0]['last_error']


def test_rejects_artifact_outside_allowed_roots(tmp_path):
    outside = tmp_path.parent / f'{tmp_path.name}-artifact.log'
    cfg, provider = _provider_config(tmp_path)
    provider['artifacts']['log_path'] = str(outside)
    result = scan_mod.get_dynamic_boards(cfg)
    assert result['providers'][0]['ok'] is False
    assert 'log_path 不在可信根内' in result['providers'][0]['last_error']


def test_provider_status_preserves_surfaces(tmp_path):
    cfg, _ = _provider_config(tmp_path, provider={'surfaces': ['console', 'governance']})

    result = scan_mod.get_dynamic_boards(cfg)

    assert result['providers'][0]['surfaces'] == ['console', 'governance']


def test_provider_freshness_key_uses_shared_config(tmp_path):
    freshness = tmp_path / 'freshness.json'
    freshness.write_text(json.dumps({
        'thresholds': {'dynamic_provider': {'days': 11}},
    }), encoding='utf-8')
    cfg, _ = _provider_config(tmp_path, provider={
        'freshness_key': 'dynamic_provider',
        'freshness_days': 3,
    })
    cfg['freshness_config'] = str(freshness)

    result = scan_mod.get_dynamic_boards(cfg)

    assert result['providers'][0]['freshness_days'] == 11
    assert result['providers'][0]['freshness_key'] == 'dynamic_provider'


def test_already_running_returns_conflict(tmp_path):
    cfg, _ = _provider_config(tmp_path)
    lock = scan_mod._dynamic_board_lock('demo')
    lock.acquire()
    try:
        result, status = scan_mod.run_dynamic_board('demo', cfg)
    finally:
        lock.release()
    assert status == 409
    assert result['status'] == 'already_running'


def test_auto_run_debounces_without_blocking_manual_refresh(tmp_path):
    scan_mod._DYNAMIC_BOARD_AUTO_RUNS.clear()
    cfg, _ = _provider_config(tmp_path)

    first, first_status = scan_mod.run_dynamic_board('demo', cfg, auto=True)
    second, second_status = scan_mod.run_dynamic_board('demo', cfg, auto=True)
    manual, manual_status = scan_mod.run_dynamic_board('demo', cfg)

    assert first_status == 200
    assert first['ok'] is True
    assert second_status == 200
    assert second['ok'] is True
    assert second['skipped'] is True
    assert second['reason'] == 'debounced'
    assert manual_status == 200
    assert manual['ok'] is True
    assert not manual.get('skipped')


def test_timeout_returns_error_and_writes_log(tmp_path):
    cfg, provider = _provider_config(tmp_path, provider={
        'command': [sys.executable, '-c', 'import time; time.sleep(3)'],
        'timeout_seconds': 1,
    })
    result, status = scan_mod.run_dynamic_board('demo', cfg)
    assert status == 500
    assert result['run']['status'] == 'timeout'
    assert Path(provider['artifacts']['log_path']).exists()


def test_failure_preserves_old_state_card(tmp_path):
    cfg, provider = _provider_config(tmp_path, provider={
        'command': [sys.executable, '-c', 'import sys; sys.exit(2)'],
    })
    state_path = Path(provider['artifacts']['state_path'])
    output_path = Path(provider['artifacts']['output_path'])
    old_state = {
        'generated_at': '2026-06-11T00:00:00+00:00',
        'summary': 'old state',
        'sources': [{'name': 'old', 'as_of': '2026-06-11T00:00:00+00:00'}],
        'stages': {},
    }
    state_path.write_text(json.dumps(old_state), encoding='utf-8')
    output_path.write_text('old', encoding='utf-8')

    result, status = scan_mod.run_dynamic_board('demo', cfg)

    assert status == 500
    assert json.loads(state_path.read_text(encoding='utf-8')) == old_state
    assert result['provider']['summary'] == 'old state'


def test_user_config_cannot_inject_dynamic_boards(tmp_path):
    (tmp_path / '.kanban.config.json').write_text(json.dumps({'dynamic_boards': []}), encoding='utf-8')
    (tmp_path / '.kanban.user.config.json').write_text(json.dumps({
        'dynamic_boards': [{'id': 'bad'}],
        'tools': {'codex': {'command': 'codex exec --json'}},
    }), encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        config = scan_mod.load_config()

    assert config['dynamic_boards'] == []
    assert config['tools']['codex']['command'] == 'codex exec --json'
