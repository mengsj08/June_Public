#!/usr/bin/env python3
"""scan_dirs allowlist guard tests."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _write_allowlist(repo_root, entries):
    (repo_root / '.kanban.scan-allowlist.json').write_text(
        json.dumps({'scan_dirs': entries}, ensure_ascii=False),
        encoding='utf-8',
    )


def test_configured_scan_dirs_pass_when_subset_of_allowlist(tmp_path):
    _write_allowlist(tmp_path, [
        'project/个人调度',
        'project/场景库运营',
        'project/研究方法咨询',
    ])

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        scan_dirs = scan_mod._configured_scan_dirs({
            'scan_dirs': ['project/个人调度', 'project/场景库运营'],
        })

    assert scan_dirs == ['project/个人调度', 'project/场景库运营']


def test_configured_scan_dirs_rejects_outside_allowlist(tmp_path):
    _write_allowlist(tmp_path, ['project/个人调度'])

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         pytest.raises(scan_mod.ScanDirAllowlistError) as exc:
        scan_mod._configured_scan_dirs({
            'scan_dirs': ['project/个人调度', 'project/_deferred'],
        })

    msg = str(exc.value)
    assert 'project/_deferred' in msg
    assert '.kanban.scan-allowlist.json' in msg


def test_configured_scan_dirs_rejects_missing_allowlist(tmp_path):
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         pytest.raises(scan_mod.ScanDirAllowlistError) as exc:
        scan_mod._configured_scan_dirs({'scan_dirs': ['project/个人调度']})

    msg = str(exc.value)
    assert '白名单文件缺失' in msg
    assert '.kanban.scan-allowlist.json' in msg
