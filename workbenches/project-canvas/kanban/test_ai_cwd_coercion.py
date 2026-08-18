#!/usr/bin/env python3
"""Tests for coercing task workdir values into AI subprocess cwd paths."""

import importlib.util
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def test_coerce_workdir_file_to_parent_for_ai_cwd(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    workdir_file = root / 'task.md'
    workdir_file.write_text('task\n', encoding='utf-8')
    config = {'open_allowed_roots': [str(tmp_path)]}

    resolved, err = scan_mod.resolve_workdir(str(workdir_file), '', config=config)
    cwd, cwd_err = scan_mod._coerce_workdir_to_cwd(resolved, config=config)

    assert err is None
    assert cwd_err is None
    assert cwd == root.resolve()


def test_coerce_workdir_directory_stays_unchanged_for_ai_cwd(tmp_path):
    workdir = tmp_path / 'workspace'
    workdir.mkdir()
    config = {'open_allowed_roots': [str(tmp_path)]}

    resolved, err = scan_mod.resolve_workdir(str(workdir), '', config=config)
    cwd, cwd_err = scan_mod._coerce_workdir_to_cwd(resolved, config=config)

    assert err is None
    assert cwd_err is None
    assert cwd == workdir.resolve()


def test_coerce_workdir_file_rejects_parent_outside_allowed_roots(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    workdir_file = root / 'task.md'
    workdir_file.write_text('task\n', encoding='utf-8')
    config = {'open_allowed_roots': [str(workdir_file)]}

    resolved, err = scan_mod.resolve_workdir(str(workdir_file), '', config=config)
    cwd, cwd_err = scan_mod._coerce_workdir_to_cwd(resolved, config=config)

    assert err is None
    assert cwd is None
    assert '父目录不在可信根内' in cwd_err
