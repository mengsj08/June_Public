#!/usr/bin/env python3
"""Tests for startup PATH augmentation used by local AI CLIs."""

import importlib.util
import os
import stat
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


class _RunResult:
    def __init__(self, stdout):
        self.stdout = stdout


def _write_executable(path):
    path.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_augment_path_for_clis_resolves_tools_from_login_path_under_reduced_path(tmp_path, monkeypatch):
    fake_bin = tmp_path / 'login-bin'
    fake_bin.mkdir()
    for tool in ('claude', 'codex', 'node'):
        _write_executable(fake_bin / tool)

    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    monkeypatch.setattr(scan_mod, '_CLI_PATH_STATIC_BIN_DIRS', ())
    monkeypatch.setattr(
        scan_mod.subprocess,
        'run',
        lambda *args, **kwargs: _RunResult(f'ignored startup output\n{fake_bin}\n'),
    )

    resolved = scan_mod._augment_path_for_clis(emit_log=False)

    for tool in ('claude', 'codex', 'node'):
        assert Path(resolved[tool]) == (fake_bin / tool).resolve()

    entries = os.environ['PATH'].split(os.pathsep)
    assert entries.index(str(fake_bin)) < entries.index('/usr/bin')
    first_path = os.environ['PATH']

    scan_mod._augment_path_for_clis(emit_log=False)

    assert os.environ['PATH'] == first_path
    assert os.environ['PATH'].split(os.pathsep).count(str(fake_bin)) == 1


def test_augment_path_for_clis_uses_latest_nvm_node_bin_when_node_still_missing(tmp_path, monkeypatch):
    system_bin = tmp_path / 'system-bin'
    system_bin.mkdir()
    old_node_bin = tmp_path / '.nvm' / 'versions' / 'node' / 'v18.20.0' / 'bin'
    new_node_bin = tmp_path / '.nvm' / 'versions' / 'node' / 'v20.11.1' / 'bin'
    old_node_bin.mkdir(parents=True)
    new_node_bin.mkdir(parents=True)
    _write_executable(old_node_bin / 'node')
    _write_executable(new_node_bin / 'node')

    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('PATH', str(system_bin))
    monkeypatch.setattr(scan_mod, '_CLI_PATH_STATIC_BIN_DIRS', ())
    monkeypatch.setattr(scan_mod.subprocess, 'run', lambda *args, **kwargs: _RunResult(''))

    resolved = scan_mod._augment_path_for_clis(emit_log=False)

    assert Path(resolved['node']) == (new_node_bin / 'node').resolve()
    assert os.environ['PATH'].split(os.pathsep)[0] == str(new_node_bin)
