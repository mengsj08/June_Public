#!/usr/bin/env python3
"""Server version bootstrap tests."""

import importlib.util
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location('scan_docs_server_version', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scan_mod)


def test_server_version_falls_back_to_nogit_when_git_unavailable(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise FileNotFoundError('git')

    monkeypatch.setattr(scan_mod, '_SERVER_VERSION_CACHE', None)
    monkeypatch.setattr(scan_mod.subprocess, 'run', fake_run)

    info = scan_mod.get_server_version_info()

    assert info['git_sha'] == 'nogit'
    assert isinstance(info['code_mtime'], str)
    assert isinstance(info['started_at'], str)
    assert info['code_mtime']
    assert info['started_at']

    assert scan_mod.get_server_version_info() == info
    assert len(calls) == 1
